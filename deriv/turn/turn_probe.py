#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""turn_probe.py — 전환점 연구 (사용자 지시 2026-11-23).

"무작정 훑지 말고, 하락에서 상승으로·상승에서 하락으로 돌아설 때 공통으로 일어난 지수·수급 변화를 찾고,
 어떤 조합이 전환점을 가장 많이, 높은 확률로 찾아내는지 본다."

1) 전환점을 먼저 정한다: 코스피200 선물 종가가 저점에서 5%(또는 8%) 이상 오르면 그 저점이 '하락→상승 전환점', 고점에서 그만큼 내리면 '상승→하락 전환점'.
2) 공통점(조건 1개): 전환점 직전 5일 / 당일~3일 뒤에 그 조건이 켜져 있던 전환점의 비율을, 전환점 날짜를 통째로 옮긴 가짜와 비교한다.
3) 조합(조건 1~3개, 빠짐없이): 조합이 켜진 날이 '전환 구간(전환점 당일~3일 뒤)' 안인 비율과 찾아낸 전환점 수를 센다.
   해마다 그 해 이전 자료로만(전환점도 그때까지의 가격으로만 정해) 고르고, 그 해에 실제로 찾아냈는지·그 뒤 수익이 났는지 채점한다.
자료·조건은 deriv/combo 와 같다(통합 자료표, 학습 구간 분위 조건). 계산 핵심은 deriv/combo/combo.c 를 그대로 쓴다.
"""
import argparse
import hashlib
import json
import os
import pickle
import sys
import time

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, '..', 'combo'))
import combo_core as K          # noqa: E402
from combo_probe import conditions, thin, TRAIN_START, DEV_END, HOLD_START   # noqa: E402

TH = [0.05, 0.08]; WIN = 4; LEAD = 5         # 전환 구간 = 전환점 당일부터 4거래일(당일~3일 뒤), 직전 구간 = 앞 5거래일
ROWS = [('저점5', 'L', 0.05, 5), ('저점8', 'L', 0.08, 5), ('고점5', 'H', 0.05, 5), ('고점8', 'H', 0.08, 5), ('수익5일', None, None, 5), ('수익10일', None, None, 10), ('수익20일', None, None, 20)]
ROWNAME = {'저점5': '하락→상승 전환(5% 이상 반등한 저점)', '저점8': '하락→상승 전환(8% 이상)', '고점5': '상승→하락 전환(5% 이상 내린 고점)', '고점8': '상승→하락 전환(8% 이상)'}
RULES = [('구간 안 50% 이상 · 전환점 8개 이상 찾음', [15, 0.50, 0, 0, 0, 0, 8]), ('구간 안 35% 이상 · 8개 이상 찾음', [20, 0.35, 0, 0, 0, 0, 8]), ('구간 안 25% 이상 · 10개 이상 찾음', [30, 0.25, 0, 0, 0, 0, 10]),
         ('수익 80% 이상(35거래)', [35, 0.80, 0, 0, 0, 0, 0]), ('수익 75% 이상(35거래)', [35, 0.75, 0, 0, 0, 0, 0])]
MIN_RAW = 15; MIN_N = 15


def zigzag(c, th):
    """종가 c 에서 th 이상 되돌린 고점·저점. 반환 [(위치, 'L' 또는 'H')] — 마지막 진행 중인 것은 넣지 않는다(아직 전환으로 확정되지 않음)."""
    piv = []; n = len(c); ok = np.where(np.isfinite(c))[0]
    if not len(ok): return piv
    lo = hi = int(ok[0]); mode = None
    for i in ok[1:]:
        i = int(i)
        if mode is None:
            if c[i] > c[hi]: hi = i
            if c[i] < c[lo]: lo = i
            if c[i] >= c[lo] * (1 + th) and lo < i: piv.append((lo, 'L')); mode = 'up'; hi = i
            elif c[i] <= c[hi] * (1 - th) and hi < i: piv.append((hi, 'H')); mode = 'dn'; lo = i
        elif mode == 'up':
            if c[i] > c[hi]: hi = i
            elif c[i] <= c[hi] * (1 - th): piv.append((hi, 'H')); mode = 'dn'; lo = i
        else:
            if c[i] < c[lo]: lo = i
            elif c[i] >= c[lo] * (1 + th): piv.append((lo, 'L')); mode = 'up'; hi = i
    return piv


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--fit', required=True); ap.add_argument('--panel', default=os.path.join(HERE, '..', 'uni', 'out', 'panel.pkl'))
    ap.add_argument('--out', default=os.path.join(HERE, 'out')); ap.add_argument('--maxlevel', type=int, default=3); ap.add_argument('--null', type=int, default=4); ap.add_argument('--limit-cond', type=int, default=0)
    a = ap.parse_args(); t_all = time.time()
    D = pickle.load(open(a.panel, 'rb')); X, P = D['X'], D['P']; td = X.index; F = P['K200F']; n = len(td)
    o = F['open'].values.astype(float); c_ = F['close'].values.astype(float)
    i0 = int(td.searchsorted(TRAIN_START)); full = a.fit.upper() == 'FULL'
    if full:
        i1 = n; test_start = i1 - i0; TE = test_start; split = int(td.searchsorted(HOLD_START)) - i0; tr_rows = (td >= TRAIN_START) & (td <= DEV_END); cut = n
    else:
        Y = int(a.fit); te = np.where(td.year == Y)[0]; i1 = te[-1] + 1; test_start = te[0] - i0; TE = test_start - 1; split = int(td.searchsorted(pd.Timestamp(f'{Y - 3}-01-01'))) - i0
        tr_rows = (np.arange(n) >= i0) & (np.arange(n) < te[0]); cut = te[0]
    T = i1 - i0; idx = td[i0:i1]
    names, fid, Bt = conditions(X[tr_rows], X.iloc[i0:i1]); n_all = len(names)
    cnt = Bt[:TE].sum(0); seen = {}; keep = []
    for c in range(Bt.shape[1]):
        if cnt[c] < MIN_RAW: continue
        h_ = hashlib.md5(Bt[:, c].tobytes()).hexdigest()
        if h_ in seen: continue
        seen[h_] = c; keep.append(c)
    rng = np.random.default_rng(7); keep = np.array(keep)[rng.permutation(len(keep))]
    if a.limit_cond: keep = keep[:a.limit_cond]
    names = [names[c] for c in keep]; fid = fid[keep]; Bt = np.ascontiguousarray(Bt[:, keep]); C = len(keep)
    # ---- 전환점: 학습 구간 표지는 '시험 해 시작 전 가격'으로만 정한다. 시험 해 표지는 전체 가격으로.
    piv_tr = {th: zigzag(c_[:cut], th) for th in TH}; piv_all = {th: zigzag(c_, th) for th in TH}
    H = np.array([r[3] for r in ROWS], np.int32); nH = len(ROWS); val = np.full((nH, T), -1, np.int8); rowwin = np.zeros(nH, np.int32); ptop = np.zeros(nH); events = {}
    for hi, (nm, typ, th, h) in enumerate(ROWS):
        if typ:
            rowwin[hi] = 1; ptop[hi] = 0.35; v = np.zeros(T, np.int8); ev_tr = [p - i0 for p, t in piv_tr[th] if t == typ and p >= i0]; ev_all = [p - i0 for p, t in piv_all[th] if t == typ and i0 <= p < i1]
            for p in ev_tr:
                if p < TE: v[p:min(p + WIN, TE)] = 1
            for p in ev_all:
                if p >= test_start: v[p:min(p + WIN, T)] = 1
                elif p + WIN > test_start: v[test_start:min(p + WIN, T)] = 1
            val[hi] = v; events[nm] = dict(train=[int(p) for p in ev_tr if p < TE], test=[int(p - test_start) for p in ev_all if p >= test_start], carry=[int(p - test_start) for p in ev_all if p < test_start < p + WIN])
        else:
            r = np.full(n, np.nan); ii = np.arange(n)[np.arange(n) + h < n]; r[ii] = c_[ii + h] / o[ii + 1] - 1; rr = r[i0:i1]
            val[hi] = np.where(np.isfinite(rr) & (rr > 0), 1, np.where(np.isfinite(rr) & (rr < 0), 0, -1))
    trend = np.array([(test_start - h) if not full else (T - (0 if rowwin[hi] else h)) for hi, h in enumerate(H)], np.int32)
    nB = a.null; valn = np.full((max(nB, 1), nH, T), -1, np.int8); shifts = rng.integers(250, TE - 250, size=max(nB, 1)); null_types = []; yr_loc = idx.year.values
    for b in range(nB):
        if b < (nB + 1) // 2: valn[b, :, :TE] = np.roll(val[:, :TE], int(shifts[b]), axis=1); null_types.append('global')
        else:
            for y in np.unique(yr_loc[:TE]):
                w = np.where(yr_loc[:TE] == y)[0]
                valn[b][:, w] = np.roll(val[:, w], int(rng.integers(len(w) // 4, max(3 * len(w) // 4, len(w) // 4 + 1))), axis=1) if len(w) >= 40 else val[:, w]
            null_types.append('year')
    R = np.array([r for _, r in RULES], float)
    res = K.scan(Bt, fid, H, trend, val, valn[:nB] if nB else valn[:0], R, TE, test_start, split, maxlevel=a.maxlevel, min_raw=MIN_RAW, min_n=MIN_N, K=30, rowwin=rowwin, ptop=ptop)
    L3 = min(a.maxlevel, 3)
    out = dict(fit=a.fit, made=pd.Timestamp.now(tz='Asia/Seoul').strftime('%Y-%m-%d %H:%M'), features=int(X.shape[1]), cond_all=int(n_all), cond=int(C), days=int(T), train_days=int(TE), rows=[r[0] for r in ROWS], H=[int(x) for x in H],
               rowwin=[int(x) for x in rowwin], rules=[nm for nm, _ in RULES], null_types=null_types, enum=[int(x) for x in res['enum'][1:5]], seconds=round(res['misc'][4] / 1000.0, 1), threads=int(res['misc'][3]),
               sel=res['sel'][:L3].tolist(), seln=res['seln'][:max(nB, 1), :L3].tolist(), pool=res['pool'][:L3].tolist(), xpool=res['xpool'][:L3].tolist(), events={k: dict(n_train=len(v['train']), test=v['test'], carry=v['carry']) for k, v in events.items()},
               base_train={ROWS[hi][0]: [int((val[hi, :TE] >= 0).sum()), int((val[hi, :TE] == 1).sum())] for hi in range(nH)})
    if not full:
        out['test'] = [str(idx[test_start].date()), str(idx[-1].date())]; out['votes'] = res['votes'][:L3].astype(int).tolist(); out['test_val'] = val[:, test_start:].astype(int).tolist()
    tops = []
    for L in range(L3):
        for hi in range(nH):
            for dr in range(1 if rowwin[hi] else 2):
                lb = res['toplb'][:, L, hi, dr].ravel(); ids = res['topid'][:, L, hi, dr].reshape(-1, 4); st = res['topst'][:, L, hi, dr].reshape(-1, 4)
                for q in np.argsort(-lb)[:30]:
                    if lb[q] <= 0: continue
                    cid = [int(i) for i in ids[q] if i >= 0]; extra = None
                    if rowwin[hi]:      # 이 조합이 켜진 뒤의 수익(같은 잣대, 학습 구간): 수익 줄마다 [거래, 오름]
                        days = np.where(Bt[:TE, cid].all(axis=1))[0]; extra = {ROWS[h2][0]: [int(x) for x in K.trade_stats(days, [int(H[h2])], [int(trend[h2])], val[h2:h2 + 1], 10 ** 9)[0][:2]] for h2 in range(nH) if not rowwin[h2]}
                    tops.append([L + 1, ROWS[hi][0], dr, round(float(lb[q]), 3), [names[i] for i in cid], [int(x) for x in st[q]], extra])
    out['top'] = tops
    if full:
        # ---- 공통점(조건 1개): 전환점 직전 5일 / 당일~3일 뒤에 켜져 있던 전환점의 비율 vs 전환점을 통째로 옮긴 가짜 300번
        com = {}; rs = np.random.default_rng(11); B = Bt.astype(bool); sh = rs.integers(60, T - 60, size=300)
        dates = {}
        for nm, typ, th, h in ROWS[:4]:
            ev = np.array([p - i0 for p, t in piv_all[th] if t == typ and i0 + LEAD <= p < i1 - WIN]); dates[nm] = [str(idx[p].date()) for p in ev]
            for wn, (a0, a1) in (('직전 5일', (-LEAD, 0)), ('당일~3일 뒤', (0, WIN))):
                def cov(pos):
                    m = np.zeros((len(pos), C), bool)
                    for k in range(a0, a1): m |= B[np.clip(pos + k, 0, T - 1)]
                    return m.mean(0)
                real = cov(ev); nul = np.array([cov((ev + s) % T) for s in sh]); mu = nul.mean(0); sd = nul.std(0) + 1e-9; q95 = np.quantile(nul, 0.95, axis=0); z = (real - mu) / sd
                od = np.argsort(-z)[:40]
                com[f'{nm}|{wn}'] = dict(n_events=int(len(ev)), n_over95=int((real > q95).sum()), expect_over95=round(0.05 * C, 1),
                                         top=[[names[i], round(float(real[i]), 3), round(float(mu[i]), 3), round(float(q95[i]), 3), round(float(z[i]), 2), int(fid[i])] for i in od])
        out['common'] = com; out['event_dates'] = dates
        out['group_of_feature'] = {int(j): D['groups'][cn] for j, cn in enumerate(X.columns)}
    os.makedirs(a.out, exist_ok=True); out['wall_seconds'] = round(time.time() - t_all, 1)
    json.dump(out, open(os.path.join(a.out, f'fit_{a.fit}.json'), 'w', encoding='utf-8'), ensure_ascii=False)
    print(json.dumps({k: out[k] for k in ('fit', 'cond', 'days', 'train_days', 'enum', 'seconds', 'threads', 'wall_seconds')}, ensure_ascii=False), {k: (v['n_train'], len(v['test'])) for k, v in out['events'].items()})


if __name__ == '__main__':
    main()
