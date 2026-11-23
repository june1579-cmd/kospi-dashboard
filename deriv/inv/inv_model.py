#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""I2 예측 — '내릴 확률'을 해마다 그 해 이전 자료로만 학습해 예측한다. 통합 예측 연구소의 학습 함수(uni_model.fit_predict)와 자료 묶음을 그대로 쓴다.

출력: out/preds.pkl (날짜 × '대상|묶음|모형' 내릴 확률) · out/preds_ens.csv.gz · out/model_meta.json
환경: INV_QUICK=1 이면 시험용으로 작게.
"""
import json
import os
import pickle
import time
import warnings

import numpy as np
import pandas as pd
from joblib import Parallel, delayed

import inv_common as C
import uni_model as UM

warnings.filterwarnings('ignore')
U = C.U; QUICK = os.environ.get('INV_QUICK') == '1'


def job(tname, kind, H, th, sname, cols, X, P, years):
    idx = X.index; n = len(idx); ent, ext, r = C.fut_ret(P, H)
    y = ((r < 0) if kind == 'DN' else (r <= th)).astype(float); known = np.isfinite(r); M = X[cols].values.astype(float)
    res = {m: np.full(n, np.nan) for m in U.MODELS}; yr = idx.year.values; i0 = int(idx.searchsorted(U.TRAIN_START)); pos = np.arange(n)
    for Y in years:
        te = np.where(yr == Y)[0]
        if not len(te): continue
        a = te[0]; tr = np.where((pos >= i0) & (pos < a) & known & (ext < a))[0]      # 결과가 시험 해 시작 전에 끝난 날만
        if len(tr) < 400 or len(set(y[tr])) < 2 or y[tr].sum() < 30: continue
        p = UM.fit_predict(M[tr], y[tr], M[te])
        for m in U.MODELS: res[m][te] = p[m]
    return {f'{tname}|{sname}|{m}': res[m] for m in U.MODELS}


def main():
    t0 = time.time(); D = pickle.load(open(os.path.join(C.UNI, 'out', 'panel.pkl'), 'rb')); X, G, P = D['X'], D['groups'], D['P']
    last_year = int(X.index.year.max()); years = list(range(U.FIRST_PRED_YEAR, last_year + 1)); targets, sets = C.TARGETS, U.SETS
    if QUICK: targets, sets, years = [C.TARGETS[1], C.TARGETS[4]], ['base', 'all'], list(range(last_year - 5, last_year + 1))
    jobs = [(t, k, H, th, s, [c for c in X.columns if G[c] in UM.SET_GROUPS[s]]) for t, k, H, th in targets for s in sets]
    out = Parallel(n_jobs=int(os.environ.get('UNI_JOBS', '4')))(delayed(job)(t, k, H, th, s, cols, X, P, years) for t, k, H, th, s, cols in jobs)
    preds = {}
    for d in out: preds.update(d)
    PR = pd.DataFrame(preds, index=X.index); PR = PR[PR.index.year >= years[0]]
    pickle.dump(PR, open(os.path.join(C.OUT, 'preds.pkl'), 'wb'))
    PR[[c for c in PR.columns if c.endswith('|ens')]].round(4).to_csv(os.path.join(C.OUT, 'preds_ens.csv.gz'), encoding='utf-8')
    meta = dict(made=pd.Timestamp.now(tz='Asia/Seoul').strftime('%Y-%m-%d %H:%M'), quick=QUICK, years=[years[0], years[-1]], columns=int(PR.shape[1]), seconds=round(time.time() - t0),
                last_pred=str(PR.dropna(how='all').index.max().date()))
    json.dump(meta, open(os.path.join(C.OUT, 'model_meta.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1); print(json.dumps(meta, ensure_ascii=False))


if __name__ == '__main__':
    main()
