import json, math, bisect
import numpy as np
D = 'docs/lab/data/'
T = json.load(open(D + 'trades.json', encoding='utf-8'))
C = json.load(open(D + 'combos.json', encoding='utf-8')); C = C.get('combos', C) if isinstance(C, dict) else C
P = json.load(open(D + 'prices.json', encoding='utf-8'))['kospi']
CM = json.load(open('/tmp/cond_map.json', encoding='utf-8'))
by = {c['key']: c for c in C}
d = P['d']; o = np.array(P['o'], float); cl = np.array(P['c'], float); idx = {x: i for i, x in enumerate(d)}
yr = np.array([int(x[:4]) for x in d])
# 바탕: 같은 해 아무 날 시가에 사서 같은 보유 거래일 뒤 종가에 팔았을 때 방향이 맞은 비율(해·보유일·방향별)
BC = {}
def base(y, h, s):
    k = (y, h, s)
    if k not in BC:
        ii = np.flatnonzero(yr == y); ii = ii[ii + h < len(d)]
        r = cl[ii + h] / o[ii] - 1
        BC[k] = float(((r * s) > 0).mean()) if len(ii) else np.nan
    return BC[k]
def wilson_lb(k, n, z=1.96):
    if n == 0: return np.nan
    p = k / n; den = 1 + z * z / n
    return (p + z * z / (2 * n) - z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / den
def binom_sf(k, n, p):   # P(X >= k)
    if n == 0: return np.nan
    return float(min(1.0, sum(math.comb(n, j) * p ** j * (1 - p) ** (n - j) for j in range(k, n + 1))))
BONF = 0.05 / len(CM)
out = []
for m in CM:
    rows = {}
    for k in m['keys']:
        c = by[k]; s = 1 if c['dir'] > 0 else -1
        for t in T.get(k, []):
            sig, buy, sell, ok = t[0], t[1], t[3], t[7]
            if buy not in idx or sell not in idx: continue
            h = idx[sell] - idx[buy]
            rows.setdefault(buy, []).append((ok, base(int(buy[:4]), max(h, 0), s), sig))
    res = {}
    for per, f in (('전체', lambda b: True), ('앞', lambda b: b < '2024-01-01'), ('뒤', lambda b: b >= '2024-01-01')):
        L = [(np.mean([x[0] for x in v]) >= 0.5, np.mean([x[1] for x in v])) for b, v in rows.items() if f(b)]   # 같은 매수일은 한 건(맞음은 다수결)
        n = len(L); k = int(sum(x[0] for x in L)); b0 = float(np.mean([x[1] for x in L])) if n else np.nan
        res[per] = dict(n=n, k=k, hit=k / n if n else np.nan, base=b0, lb=wilson_lb(k, n), p=binom_sf(k, n, b0) if n else np.nan)
    a, b, t = res['앞'], res['뒤'], res['전체']
    okA = a['n'] >= 20 and a['lb'] > a['base']; okB = b['n'] >= 20 and b['lb'] > b['base']
    sig = t['p'] < BONF
    v = '신뢰 가능' if (okA and okB and sig) else ('한 구간만' if (okA or okB) else ('표본 부족' if (a['n'] < 20 or b['n'] < 20) and not (okA or okB) else '근거 부족'))
    out.append(dict(rank=m['rank'], name=m['name'], ncomb=len(m['keys']), res=res, v=v, sig=sig))
json.dump(out, open('/tmp/validate_out.json', 'w', encoding='utf-8'), ensure_ascii=False)
import collections
print('Bonferroni', BONF, collections.Counter(x['v'] for x in out))
f = lambda r: f"{r['n']} | {100*r['hit']:.1f}% | {100*r['base']:.1f}% | {100*r['lb']:.1f}%" if r['n'] else '0 | – | – | –'
for x in out:
    if x['v'] in ('신뢰 가능', '한 구간만'):
        print(f"| {x['rank']} | {x['name'][:70]} | {f(x['res']['앞'])} | {f(x['res']['뒤'])} | {x['res']['전체']['p']:.1e} | {x['v']} |")
