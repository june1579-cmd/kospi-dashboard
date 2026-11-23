#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""U2 예측 — 해마다 그 해 이전 자료로만 학습해 그 해를 예측한다(걸어가며 검증). 모든 성적은 이 '표본 밖' 예측으로만 잰다.

  대상   uni_common.TARGETS (코스피 5·10·20일, 코스피200 선물 1·3일) — 오를 확률
  자료   묶음 5가지(기존 재료 / + 선물 / + 옵션 / + 미국·해외 / 전부) → 새 자료가 실제로 보탬이 되는지 따로 본다
  모형   나무 모형(HistGradientBoosting, 빈칸 그대로 받음) · 선형 모형(로지스틱, 빈칸은 학습 구간 가운뎃값) · 둘 평균
  누설 방지  학습에는 결과(청산일)가 시험 해 시작 전에 끝난 날만 쓴다. 지표 고르기·문턱도 지난 자료로만.
출력: out/preds.pkl (날짜 × '대상|묶음|모형' 오를 확률), out/model_meta.json
환경: UNI_QUICK=1 이면 시험용으로 작게(대상 2개·묶음 2개·최근 해만).
"""
import json
import os
import pickle
import time
import warnings

import numpy as np
import pandas as pd
from joblib import Parallel, delayed
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression

import uni_common as U

warnings.filterwarnings('ignore')
QUICK = os.environ.get('UNI_QUICK') == '1'
SET_GROUPS = {'base': {'price', 'fund', 'vol'}, 'fut': {'price', 'fund', 'vol', 'fut'}, 'opt': {'price', 'fund', 'vol', 'opt'}, 'us': {'price', 'fund', 'vol', 'us'},
              'all': {'price', 'fund', 'vol', 'fut', 'opt', 'us', 'other'}}


def fit_predict(Xtr, ytr, Xte):
    out = {}
    ok = (np.isfinite(Xtr).sum(0) >= 60) & (np.nan_to_num(np.nanstd(Xtr, 0)) > 0)      # 학습 구간에 값이 거의 없거나 한 가지뿐인 지표는 뺀다
    Xtr, Xte = Xtr[:, ok], Xte[:, ok]
    gb = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05, max_depth=3, min_samples_leaf=40, l2_regularization=1.0, max_bins=64, random_state=7)
    gb.fit(Xtr, ytr); out['gb'] = gb.predict_proba(Xte)[:, 1]
    keep = np.isfinite(Xtr).mean(0) >= 0.6                      # 선형 모형: 학습 구간에서 60% 이상 값이 있는 지표만
    A, B = Xtr[:, keep], Xte[:, keep]
    med = np.nanmedian(A, 0); lo = np.nanpercentile(A, 1, 0); hi = np.nanpercentile(A, 99, 0)
    prep = lambda M: np.clip(np.where(np.isfinite(M), M, med), lo, hi)
    A, B = prep(A), prep(B); mu = A.mean(0); sd = A.std(0); sd[sd == 0] = 1
    lr = LogisticRegression(C=0.05, max_iter=400); lr.fit((A - mu) / sd, ytr); out['lr'] = lr.predict_proba((B - mu) / sd)[:, 1]
    out['ens'] = (out['gb'] + out['lr']) / 2
    return out


def job(tname, kind, H, sname, cols, X, P, years):
    idx = X.index; n = len(idx); ent, ext, r = U.target_arrays(P, kind, H)
    y = (r > 0).astype(float); known = np.isfinite(r); M = X[cols].values.astype(float)
    res = {m: np.full(n, np.nan) for m in U.MODELS}; yr = idx.year.values; i0 = int(idx.searchsorted(U.TRAIN_START))
    for Y in years:
        te = np.where(yr == Y)[0]
        if not len(te): continue
        a = te[0]
        tr = np.where((np.arange(n) >= i0) & (np.arange(n) < a) & known & (ext < a))[0]      # 결과가 시험 해 시작 전에 끝난 날만
        if len(tr) < 400 or len(set(y[tr])) < 2: continue
        p = fit_predict(M[tr], y[tr], M[te])
        for m in U.MODELS: res[m][te] = p[m]
    return {f'{tname}|{sname}|{m}': res[m] for m in U.MODELS}


def main():
    t0 = time.time()
    D = pickle.load(open(os.path.join(U.OUT, 'panel.pkl'), 'rb')); X, G, P = D['X'], D['groups'], D['P']
    last_year = int(X.index.year.max()); years = list(range(U.FIRST_PRED_YEAR, last_year + 1))
    targets, sets = U.TARGETS, U.SETS
    if QUICK: targets, sets, years = [U.TARGETS[0], U.TARGETS[3]], ['base', 'all'], list(range(last_year - 5, last_year + 1))
    jobs = []
    for tname, kind, H in targets:
        for s in sets:
            cols = [c for c in X.columns if G[c] in SET_GROUPS[s]]
            jobs.append((tname, kind, H, s, cols))
    out = Parallel(n_jobs=int(os.environ.get('UNI_JOBS', '4')))(delayed(job)(t, k, H, s, cols, X, P, years) for t, k, H, s, cols in jobs)
    preds = {}
    for d in out: preds.update(d)
    PR = pd.DataFrame(preds, index=X.index); PR = PR[PR.index.year >= years[0]]
    pickle.dump(PR, open(os.path.join(U.OUT, 'preds.pkl'), 'wb'))
    PR[[c for c in PR.columns if c.endswith('|ens')]].round(4).to_csv(os.path.join(U.OUT, 'preds_ens.csv.gz'), encoding='utf-8')   # 사람·에이전트가 읽을 사본(둘 평균 모형만)
    meta = dict(made=pd.Timestamp.now(tz='Asia/Seoul').strftime('%Y-%m-%d %H:%M'), quick=QUICK, years=[years[0], years[-1]], columns=int(PR.shape[1]),
                set_features={s: int(sum(G[c] in SET_GROUPS[s] for c in X.columns)) for s in sets}, seconds=round(time.time() - t0),
                last_pred=str(PR.dropna(how='all').index.max().date()))
    json.dump(meta, open(os.path.join(U.OUT, 'model_meta.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(json.dumps(meta, ensure_ascii=False))


if __name__ == '__main__':
    main()
