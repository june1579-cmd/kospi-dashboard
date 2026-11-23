#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""U2b 규칙 후보 — 대시보드 최적화 매수·매도 신호가 켜진 날에 선물·옵션·미국 지표 조건을 더 건다(실험 2, 2026-11-23).

  바탕 신호  main 의 pkg/reproduce.py 가 만드는 최적화 매수·매도 1·2·3위(켜진 날 전부). t일 신호 = t일 장 마감 뒤에 아는 값
             (금투협은 전날 공시분, VIX 는 전날 미국 종가 — reproduce._opt_atoms 정의 그대로).
  더하는 조건  선물·옵션·미국 묶음 지표 하나의 '학습 구간 분위(1/3·1/2·2/3) 이상/이하'. 문턱은 시험 해 이전 날의 값으로만 정한다.
  고르는 법  시험 해 Y 마다, Y 이전에 결과가 끝난 '바탕 신호가 켜진 날'만 보고 적중률의 윌슨 하한이 가장 높은 조건을 고른다
             (연구소 A6 방식: 유효 표본 = 켜진 날 ÷ √보유일, 바탕 신호의 25~80%가 남는 조건만, 바탕 신호보다 적중이 높은 것만).
             c1 = 가장 좋은 조건 1개 / v3 = 서로 덜 겹치는 조건 3개 가운데 2개 이상.
             학습할 날이 모자란 해(켜진 날 30일 미만 등)는 조건을 못 고른 것으로 두고 그 해에는 신호를 내지 않는다(추정으로 채우지 않음).
  누설 점검  같은 과정을 지표를 하루 더 늦춰서도 돌려 둔다(sig_lag1) — 성적이 비슷해야 정상.
  주의      바탕 신호 자체는 2015~2024 자료를 보고 고른 규칙이다. 그래서 이 후보의 2016~2024 성적에는 그 부풀림이 섞여 있고,
            깨끗한 구간은 2025년부터다(판정 뒤 보고서에 따로 적는다).
출력: out/rules.pkl {'sig', 'sig_lag1', 'base', 'meta', 'names'} · out/rules_pick.csv(해마다 고른 조건) · out/rules_meta.json
판정은 uni_judge.py 가 다른 후보와 똑같이 한다(표본 밖, 솎기, 가짜 신호 시험, 여러 번 시도 보정).
"""
import json
import os
import pickle
import sys
import time
import warnings

import numpy as np
import pandas as pd

import uni_common as U

warnings.filterwarnings('ignore')
POOL = ('fut', 'opt', 'us')                 # 새로 더한 자료 묶음에서만 조건을 고른다
QTS = (1 / 3, 1 / 2, 2 / 3)
RULE_TARGETS = ('IDX5', 'IDX10', 'IDX20')   # 대시보드 신호는 코스피 대상
FRAC = (0.25, 0.80)                         # 조건을 건 뒤 바탕 신호가 이만큼은 남아야 한다
MIN_ROWS = 30                               # 학습 구간에서 바탕 신호가 켜진 날(결과가 끝난 날) 최소
MIN_NEFF = 6.0                              # 조건을 건 뒤 유효 표본(켜진 날 ÷ √보유일) 최소
MIN_FINITE = 250                            # 문턱을 정할 때 지표 값이 있는 날 최소
OVERLAP = 0.70                              # v3: 켜진 날이 이만큼 넘게 겹치는 조건은 하나만
FIRST_YEAR = U.EVAL_START.year
CLEAN_START = pd.Timestamp('2025-01-01')    # 대시보드 최적화가 보지 않은 기간(2015~2024 최적화)
TYPES = ('최적화 1위', '최적화 2위', '최적화 3위')
BASES = [('dB1', 'buy', TYPES[:1]), ('dB2', 'buy', TYPES[1:2]), ('dBA', 'buy', TYPES),
         ('dS1', 'sell', TYPES[:1]), ('dS2', 'sell', TYPES[1:2]), ('dS3', 'sell', TYPES[2:3]), ('dSA', 'sell', TYPES)]
SET_NAME = {'dB1': '대시보드 매수 1위 + 조건', 'dB2': '대시보드 매수 2위 + 조건', 'dBA': '대시보드 매수 1~3위 아무거나 + 조건',
            'dS1': '대시보드 매도 1위 + 조건', 'dS2': '대시보드 매도 2위 + 조건', 'dS3': '대시보드 매도 3위 + 조건', 'dSA': '대시보드 매도 1~3위 아무거나 + 조건'}
MODEL_NAME = {'c1': '조건 1개', 'v3': '조건 3개 중 2개'}
VARIANTS = (('c1', 1, 1), ('v3', 3, 2))     # (이름, 고르는 조건 수, 켜지는 데 필요한 수)
SIDE_KO = {'buy': '매수', 'sell': '매도'}


def base_signals(idx):
    """바탕 신호(켜진 날) — reproduce 의 정의 그대로. 안 되면 out/buy3.csv·sell3.csv 의 날짜(시작+지속)로."""
    out = {}; note = ''
    try:
        xl = os.path.join(U.MAIN, 'data', '통합_원자료.xlsx'); sys.path.insert(0, os.path.join(U.MAIN, 'pkg')); import reproduce as R
        D = R.load(xl); S = dict(R.buy3_series(D)); S.update(R.sell3_series(D)); last = pd.to_datetime(D['K'].index).max()
        for (side, ty), s in S.items():
            s = pd.Series(np.asarray(s.values, dtype=float), index=pd.to_datetime(s.index))
            out[('buy' if side == '매수' else 'sell', ty)] = np.nan_to_num(s.reindex(idx).values.astype(float)) > 0
        note = f'reproduce 정의 그대로(자료 끝 {last.date()})'
    except Exception as e:
        out = {}
        for fn, side in (('buy3.csv', 'buy'), ('sell3.csv', 'sell')):
            d = pd.read_csv(os.path.join(U.MAIN, 'out', fn))
            for ty, g in d.groupby('type'): out[(side, str(ty))] = np.isin(idx.strftime('%Y-%m-%d'), g['date'].astype(str).values)
        note = f'out/buy3·sell3.csv 날짜로 대신함({type(e).__name__}: {str(e)[:60]})'
    return out, note


def wilson_vec(p, n):
    n = np.maximum(n, 1e-9); z = U.Z; d = 1 + z * z / n; c = p + z * z / (2 * n); h = z * np.sqrt(np.maximum(p * (1 - p) / n + z * z / (4 * n * n), 0))
    return (c - h) / d


def cond_block(M, lo, a, hi):
    """문턱 = [lo, a) 날의 분위(시험 해 이전 값만). 돌려주는 조건표는 [lo, hi) 날 × (지표 × 분위 × 이상/이하)."""
    tr = M[lo:a]; fin = np.isfinite(tr).sum(0) >= MIN_FINITE
    thr = np.full((len(QTS), M.shape[1]), np.nan)
    if fin.any(): thr[:, fin] = np.nanquantile(tr[:, fin], QTS, axis=0)
    blk = M[lo:hi]; parts = []; desc = []
    for j, q in enumerate(QTS):
        for op in ('ge', 'le'):
            parts.append((blk >= thr[j]) if op == 'ge' else (blk <= thr[j]))       # 빈칸·문턱 없음은 거짓
            desc += [(f, op, q, thr[j, f]) for f in range(M.shape[1])]
    return np.concatenate(parts, axis=1), desc


def pick(Ctr, ytr, hold, k, feat):
    """학습 구간의 '바탕 신호가 켜진 날' Ctr(날 × 조건)·ytr(맞음) 에서 윌슨 하한이 높은 조건 k개(지표가 서로 다르고 덜 겹치게). feat = 조건마다 지표 번호."""
    n = len(ytr); cnt = Ctr.sum(0).astype(float); hits = (Ctr & ytr[:, None]).sum(0).astype(float)
    p = hits / np.maximum(cnt, 1); neff = cnt / np.sqrt(hold); lb = wilson_vec(p, neff); p0 = float(ytr.mean())
    ok = (cnt >= FRAC[0] * n) & (cnt <= FRAC[1] * n) & (neff >= MIN_NEFF) & (p > p0)
    order = np.lexsort((-cnt, -np.where(ok, lb, -1.0))); chosen = []
    for j in order:
        if not ok[j]: break
        if any(feat[j] == feat[c] for c in chosen): continue
        if any(np.logical_and(Ctr[:, j], Ctr[:, c]).sum() / max(np.logical_or(Ctr[:, j], Ctr[:, c]).sum(), 1) > OVERLAP for c in chosen): continue
        chosen.append(int(j))
        if len(chosen) == k: break
    return chosen, dict(cnt=cnt, p=p, lb=lb, p0=p0, n=n)


def build(X, G, P, base, lag=0, picks=None):
    idx = X.index; n = len(idx); cols = [c for c in X.columns if G.get(c) in POOL]; M = X[cols].values.astype(float)
    if lag: M = np.vstack([np.full((lag, M.shape[1]), np.nan), M[:-lag]])                 # 지표를 하루 더 늦춤(누설 점검용)
    yr = idx.year.values; i0 = int(idx.searchsorted(U.TRAIN_START)); years = [int(y) for y in np.unique(yr) if y >= FIRST_YEAR]
    TA = {tn: U.target_arrays(P, kind, H) for tn, kind, H in U.TARGETS if tn in RULE_TARGETS}; HOLD = {tn: H + 1 for tn, kind, H in U.TARGETS if tn in RULE_TARGETS}
    sig = {f'{tn}|{bk}|{vn}|{side}|rule': np.zeros(n, bool) for tn in RULE_TARGETS for bk, side, _ in BASES for vn, _, _ in VARIANTS}
    for Y in years:
        te = np.where(yr == Y)[0]; a = int(te[0]); hi = int(te[-1]) + 1
        C, desc = cond_block(M, i0, a, hi); pos = np.arange(i0, hi); feat = np.array([d[0] for d in desc])
        for bk, side, tys in BASES:
            b = np.zeros(n, bool)
            for ty in tys: b |= base.get((side, ty), np.zeros(n, bool))
            for tn in RULE_TARGETS:
                ent, ext, r = TA[tn]; y = (r > 0) if side == 'buy' else (r < 0)
                trm = (pos < a) & b[i0:hi] & np.isfinite(r[i0:hi]) & (ext[i0:hi] < a)       # 결과가 시험 해 시작 전에 끝난, 바탕 신호가 켜진 날
                tem = (pos >= a) & b[i0:hi]
                for vn, k, need in VARIANTS:
                    cid = f'{tn}|{bk}|{vn}|{side}|rule'; rec = dict(year=Y, id=cid, train_days=int(trm.sum()), chosen=0, test_base_days=int(tem.sum()), test_days=0)
                    if trm.sum() >= MIN_ROWS:
                        ch, st = pick(C[trm], y[i0:hi][trm], HOLD[tn], k, feat); rec.update(chosen=len(ch), train_base_hit=round(st['p0'], 3))
                        if len(ch) == k:
                            on = C[:, ch].sum(1) >= need; v = tem & on; sig[cid][pos[v]] = True; rec['test_days'] = int(v.sum())
                            rec['conds'] = ' / '.join(f"{cols[desc[j][0]]} {'≥' if desc[j][1] == 'ge' else '≤'} {desc[j][3]:.4g}(분위 {desc[j][2]:.2f})" for j in ch)
                            rec['train_cond'] = ' / '.join(f"{int(st['cnt'][j])}일 {st['p'][j] * 100:.0f}%(하한 {st['lb'][j] * 100:.0f}%)" for j in ch)
                    if picks is not None: picks.append(rec)
    return pd.DataFrame(sig, index=idx), len(cols)


def main():
    t0 = time.time()
    D = pickle.load(open(os.path.join(U.OUT, 'panel.pkl'), 'rb')); X, G, P = D['X'], D['groups'], D['P']; idx = X.index
    base, note = base_signals(idx); picks = []
    S, nfeat = build(X, G, P, base, 0, picks); S1, _ = build(X, G, P, base, 1, None)
    BD = {}
    for bk, side, tys in BASES:
        b = np.zeros(len(idx), bool)
        for ty in tys: b |= base.get((side, ty), np.zeros(len(idx), bool))
        BD[bk] = b
    PK = pd.DataFrame(picks)
    got = PK[PK['conds'].notna()].groupby('id')['year'].apply(lambda v: sorted(int(y) for y in v)).to_dict() if 'conds' in PK else {}
    meta = {cid: dict(target=cid.split('|')[0], set=cid.split('|')[1], model=cid.split('|')[2], side=cid.split('|')[3], years=got.get(cid, [])) for cid in S.columns}   # years = 조건을 고를 수 있었던 해
    pickle.dump(dict(sig=S, sig_lag1=S1, base=pd.DataFrame(BD, index=idx), meta=meta, names=dict(set=SET_NAME, model=MODEL_NAME), clean_start=str(CLEAN_START.date())), open(os.path.join(U.OUT, 'rules.pkl'), 'wb'))
    PK.to_csv(os.path.join(U.OUT, 'rules_pick.csv'), index=False, encoding='utf-8')
    ev = idx >= U.EVAL_START
    info = dict(made=pd.Timestamp.now(tz='Asia/Seoul').strftime('%Y-%m-%d %H:%M'), base_note=note, pool_features=int(nfeat), conditions_per_year=int(nfeat * len(QTS) * 2), candidates=int(S.shape[1]),
                base_days_eval={f'{SIDE_KO[s]} {ty}': int((v & ev).sum()) for (s, ty), v in base.items()}, base_first={f'{SIDE_KO[s]} {ty}': (str(idx[v][0].date()) if v.any() else None) for (s, ty), v in base.items()},
                years_no_pick=int((PK['conds'].isna() if 'conds' in PK else pd.Series(True, index=PK.index)).sum()), year_rows=int(len(PK)), seconds=round(time.time() - t0),
                timing='바탕 신호·지표 모두 t일 장 마감 뒤~다음 개장 전에 아는 값. 조건 문턱·고르기는 시험 해 이전(결과가 끝난 날)만. 진입은 t+1일 종가')
    json.dump(info, open(os.path.join(U.OUT, 'rules_meta.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(json.dumps(info, ensure_ascii=False))
    return info


if __name__ == '__main__':
    main()
