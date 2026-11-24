# -*- coding: utf-8 -*-
"""X4 — 신뢰 가능 21개 조건으로 반등 전 저점 맞히기: 저점(반등 하루 전) 날 켜진 신호 개수 분석. 앞 2010~2023 / 뒤 2024~2026-11-20.
입력: docs/lab/data(trades·combos·prices, main), 조건 묶음은 웹판 조건 조각(조합 설명)에서 뽑은 것(cond_map.json), 신뢰 가능 판정은 validate_out.json.
"""
import json, math, os, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); OUT = os.path.join(HERE, 'out')
LAB = sys.argv[1] if len(sys.argv) > 1 else '/home/claude/main/docs/lab/data'
T = json.load(open(os.path.join(LAB, 'trades.json'), encoding='utf-8'))
P = json.load(open(os.path.join(LAB, 'prices.json'), encoding='utf-8'))['kospi']
CM = json.load(open(os.path.join(HERE, 'cond_map.json'), encoding='utf-8'))
V = {x['rank']: x for x in json.load(open(os.path.join(HERE, 'validate_out.json'), encoding='utf-8'))}
d = np.array(P['d']); c = np.array(P['c'], float); h = np.array(P['h'], float); n = len(d)
pos = {x: i for i, x in enumerate(d)}
R21 = [r for r, x in V.items() if x['v'] == '신뢰 가능']
DOWN = {17, 19}; DUP = {82: 77}                       # 하락 신호 · 신호일이 똑같은 조건(82 = 77)
name = {m['rank']: m['name'] for m in CM}
sig = {}
for m in CM:
    if m['rank'] in R21:
        a = np.zeros(n, bool)
        for k in m['keys']:
            for t in T.get(k, []):
                if t[0] in pos: a[pos[t[0]]] = True
        sig[m['rank']] = a
UP = [r for r in R21 if r not in DOWN and r not in DUP]
cnt = np.sum([sig[r] for r in UP], axis=0); dn = np.sum([sig[r] for r in DOWN], axis=0)
live = d >= '2010-01-01'
PER = [('앞', live & (d < '2024-01-01')), ('뒤', d >= '2024-01-01')]

def lows(win, look, rise):
    L = np.zeros(n, bool)
    for i in range(win, n - max(win, 1)):
        if c[i] == c[max(0, i - win): i + win + 1].min() and i + look < n and h[i + 1: i + look + 1].max() >= c[i] * (1 + rise):
            L[i] = True
    return L

def wl(k, m, z=1.96):
    if m == 0: return float('nan')
    p = k / m; den = 1 + z * z / m
    return (p + z * z / (2 * m) - z * math.sqrt(p * (1 - p) / m + z * z / (4 * m * m))) / den

DEFS = [('기본(앞뒤 10일 최저 · 20일 안 +5%)', 10, 20, 0.05), ('작은 반등(앞뒤 5일 최저 · 10일 안 +3%)', 5, 10, 0.03)]
res = {'up': UP, 'down': sorted(DOWN), 'dup': DUP, 'names': {r: name[r] for r in R21}, 'defs': []}
for dname, win, look, rise in DEFS:
    L = lows(win, look, rise)
    near = np.zeros(n, bool)                        # 넓게: 저점 3거래일 전 ~ 저점
    for i in np.flatnonzero(L): near[max(0, i - 3): i + 1] = True
    D = {'name': dname, 'per': {}}
    for pn, pm in PER:
        valid = pm & (np.arange(n) < n - look)      # 끝 쪽은 반등 여부를 아직 모름
        nl = int((L & valid).sum()); nd = int(valid.sum())
        rows = []
        for k in range(0, int(cnt.max()) + 1):
            for mode in ('=', '≥'):
                on = valid & ((cnt == k) if mode == '=' else (cnt >= k))
                m = int(on.sum())
                ks = int((on & L).sum()); kn = int((on & near).sum())
                rows.append({'k': k, 'mode': mode, 'days': m, 'strict': ks, 'near': kn,
                             'p_strict': ks / m if m else None, 'p_near': kn / m if m else None,
                             'lb_strict': wl(ks, m), 'lb_near': wl(kn, m),
                             'recall': (int((L & valid & (cnt >= k)).sum()) / nl) if (mode == '≥' and nl) else None})
        # 저점 날 개수 분포
        dist = pd.Series(cnt[L & valid]).value_counts().sort_index().to_dict()
        dn_low = pd.Series(dn[L & valid]).value_counts().sort_index().to_dict()
        D['per'][pn] = {'lows': nl, 'days': nd, 'base_strict': nl / nd, 'base_near': float((near & valid).sum()) / nd,
                        'rows': rows, 'dist_at_low': {int(k): int(v) for k, v in dist.items()}, 'down_at_low': {int(k): int(v) for k, v in dn_low.items()},
                        'low_dates': [str(x) for x in d[L & valid]]}
    res['defs'].append(D)
# 날짜별 개수(웹판·확인용)
pd.DataFrame({'date': d, 'up_count': cnt, 'down_count': dn, **{f'c{r}': sig[r].astype(int) for r in R21}}).loc[live].to_csv(os.path.join(OUT, 'daily_count.csv'), index=False)
json.dump(res, open(os.path.join(OUT, 'result.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('UP', len(UP), 'max count', int(cnt.max()))
for D in res['defs']:
    print('==', D['name'])
    for pn, x in D['per'].items():
        print(pn, '저점', x['lows'], '/', x['days'], '일 · 바탕 엄격 %.1f%% 넓게 %.1f%%' % (100 * x['base_strict'], 100 * x['base_near']), '저점 날 개수 분포', x['dist_at_low'], '하락 신호', x['down_at_low'])
        for r in x['rows']:
            if r['days']: print('  ', r['mode'], r['k'], r['days'], '일 · 엄격', r['strict'], '(%.1f%%, 하한 %.1f%%)' % (100 * r['p_strict'], 100 * r['lb_strict']), '넓게', r['near'], '(%.1f%%, 하한 %.1f%%)' % (100 * r['p_near'], 100 * r['lb_near']), '잡은 저점 %s' % ('' if r['recall'] is None else '%.0f%%' % (100 * r['recall'])))
