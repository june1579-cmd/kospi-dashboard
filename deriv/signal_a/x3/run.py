# -*- coding: utf-8 -*-
"""X3 — 15가지 조건의 모든 그리고 조합(32,767개) '1~5거래일 안 +3%' 확률. SPEC.md 그대로. 조건·채점은 x2/run.py 를 불러 씀."""
import importlib.util
import json
import math
import os
import sys
import time

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
SA = os.path.dirname(HERE)
for _p in (SA, os.path.join(SA, 'w1')):
    if _p not in sys.path: sys.path.insert(0, _p)
import sa_common as C  # noqa: E402

spec = importlib.util.spec_from_file_location('x2_run', os.path.join(SA, 'x2', 'run.py'))
X2 = importlib.util.module_from_spec(spec); spec.loader.exec_module(X2)

OUT = os.path.join(HERE, 'out')
NS = X2.NS; WIN = X2.WIN
PER = [(pn, a, b, lab) for pn, a, b, lab in X2.PERIODS]
MINS = [10, 20, 30]
IDS = list(range(1, 16))


def label(s):
    return '·'.join(str(c) for c in IDS if s >> (c - 1) & 1)


def binom_tail(n, k, p):
    if n <= 0 or p <= 0: return None
    return float(min(1.0, sum(math.comb(n, j) * p ** j * (1 - p) ** (n - j) for j in range(k, n + 1))))


def main():
    t0 = time.time(); os.makedirs(OUT, exist_ok=True)
    D = C.Data(); print('자료', D.n, flush=True)
    single, _, _ = X2.conditions(D)
    live = np.asarray(D.td >= C.START)
    M = {c: (np.asarray(single[c], dtype=bool) & live) for c in IDS if c != 4}
    H = {0: X2.hit_table(D, 0), 1: X2.hit_table(D, 1)}
    pm = {pn: np.asarray((D.td >= a) & (D.td <= b)) for pn, a, b, _ in PER}
    base = {}
    for d in (0, 1):
        for pn, a, b, _ in PER:
            r, _, _ = X2.measure(D, live, H[d], d, a, b); base[(d, pn)] = r['전부']
    print('조건·채점표 끝', round(time.time() - t0, 1), '초', flush=True)

    NSUB = 2 ** 15; bit4 = 1 << 3
    masks = np.zeros((NSUB, D.n), dtype=bool); masks[0] = live   # 0 = 아무 조건 없음(모든 거래일)
    rows = []; sig_key = {}
    for s in range(1, NSUB):
        low = s & -s; c = low.bit_length()
        masks[s] = masks[s ^ low] if c == 4 else (masks[s ^ low] & M[c])
        d = 1 if s & bit4 else 0
        mk = masks[s]
        key = hash((d, np.packbits(mk).tobytes())); sig_key[s] = key
        row = {'id': s, '조합': label(s), '조건수': bin(s).count('1'), '늦춤': d}
        for pn, a, b, _ in PER:
            pos = np.flatnonzero(mk & pm[pn]); ind = D.thin_pos(pos, WIN, d)
            row[f'{pn}_전부'] = int(len(pos)); row[f'{pn}_독립'] = int(len(ind))
            for k, N in enumerate(NS):
                v = H[d][k, ind]; v = v[np.isfinite(v)]
                row[f'{pn}_n{N}'] = int(len(v)); row[f'{pn}_k{N}'] = int(v.sum()); row[f'{pn}_p{N}'] = (float(v.mean()) if len(v) else np.nan)
            va = H[d][4, pos]; va = va[np.isfinite(va)]
            row[f'{pn}_전부p5'] = float(va.mean()) if len(va) else np.nan
        rows.append(row)
        if s % 4096 == 0: print(s, '/', NSUB - 1, round(time.time() - t0, 1), '초', flush=True)
    A = pd.DataFrame(rows)
    vc = pd.Series(list(sig_key.values())).value_counts()
    A['같은신호_조합수'] = [int(vc[sig_key[s]]) for s in A['id']]
    for pn, _, _, _ in PER:
        A[f'{pn}_바탕p5'] = [base[(d, pn)]['p5'] for d in A['늦춤']]
        A[f'{pn}_이항p'] = [binom_tail(int(n), int(k), float(p)) if n > 0 else None for n, k, p in zip(A[f'{pn}_n5'], A[f'{pn}_k5'], A[f'{pn}_바탕p5'])]
    A.round(5).to_csv(os.path.join(OUT, 'all.csv'), index=False, encoding='utf-8')

    def top(df, pn, mn, k=1):
        q = df[df[f'{pn}_n5'] >= mn]
        if q.empty: return q
        return q.sort_values([f'{pn}_p5', f'{pn}_n5', '조건수', 'id'], ascending=[False, False, True, True]).head(k)

    best = {'tiers': {}, 'by_size': {}, 'base': {f'{d}_{pn}': base[(d, pn)]['p5'] for (d, pn) in base}}
    for mn in MINS:
        for pn, _, _, _ in PER:
            t = top(A, pn, mn, 10); best['tiers'][f'{pn}_{mn}'] = t['id'].tolist()
    for size in range(1, 16):
        q = A[A['조건수'] == size]
        for pn, _, _, _ in PER:
            t = top(q, pn, 10, 1); best['by_size'][f'{pn}_{size}'] = (int(t['id'].iloc[0]) if len(t) else None)
    # 두 구간 모두 바탕을 넘은 조합 수(10건 이상) — 참고
    both = A[(A['앞_n5'] >= 10) & (A['뒤_n5'] >= 10)]
    best['both10'] = int(len(both)); best['both10_beat'] = int(((both['앞_p5'] > both['앞_바탕p5']) & (both['뒤_p5'] > both['뒤_바탕p5'])).sum())
    json.dump(best, open(os.path.join(OUT, 'best.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    write_report(A, best, base)
    json.dump({'done': pd.Timestamp.now(tz='Asia/Seoul').strftime('%Y-%m-%d %H:%M'), 'data_end': str(C.END.date()), 'combos': len(A),
               'seconds': round(time.time() - t0, 1)}, open(os.path.join(OUT, 'done.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('끝', round(time.time() - t0, 1), '초', flush=True)


def f(p, n):
    return '–' if (p is None or (isinstance(p, float) and np.isnan(p)) or n < 10) else f'{100 * p:.1f}%'


def line(r, pn):
    return f"{int(r[f'{pn}_독립'])}건 · " + ' / '.join(f(r[f'{pn}_p{N}'], r[f'{pn}_n{N}']) for N in NS)


def write_report(A, best, base):
    by = A.set_index('id')
    L = ['# X3 — 15가지 조건 모든 조합(32,767개) · 1~5거래일 안 +3% · 앞 최고 / 뒤 최고', '',
         '정의는 SPEC.md(X2 조건·채점 그대로, 고른 조건 모두 그리고, 4번 = 하루 늦춘 시작). 순위 = 독립 신호 N5 확률 → 독립 수 → 조건 수.', '',
         f"바탕(아무 날, N5): 앞 {100*base[(0,'앞')]['p5']:.1f}% · 뒤 {100*base[(0,'뒤')]['p5']:.1f}% (늦춘 시작: 앞 {100*base[(1,'앞')]['p5']:.1f}% · 뒤 {100*base[(1,'뒤')]['p5']:.1f}%)", '',
         '## 단계별 최고(상위 10)', '']
    for mn in MINS:
        for pn in ('앞', '뒤'):
            other = '뒤' if pn == '앞' else '앞'
            L += [f'### {pn} 최고 — 독립 {mn}건 이상', '', f'| 순위 | 조합 | 조건 수 | {pn} 독립 · N1/N2/N3/N4/N5 | {pn} 전부 수 · N5 | 이항 p | 같은 신호 조합 | {other}(교차) 독립 · N1~N5 |', '|---|---|---|---|---|---|---|---|']
            for i, s in enumerate(best['tiers'][f'{pn}_{mn}'], 1):
                r = by.loc[s]; bp = r[f'{pn}_이항p']
                L.append(f"| {i} | {r['조합']} | {r['조건수']} | {line(r, pn)} | {int(r[f'{pn}_전부'])} · {f(r[f'{pn}_전부p5'], r[f'{pn}_전부'])} | {('–' if bp is None or bp != bp else format(bp, '.1e'))} | {int(r['같은신호_조합수'])} | {line(r, other)} |")
            L.append('')
    L += ['## 조합 크기별 최고(독립 10건 이상)', '', '| 조건 수 | 앞 최고 조합 | 앞 독립 · N5 | 그 조합 뒤 · N5 | 뒤 최고 조합 | 뒤 독립 · N5 | 그 조합 앞 · N5 |', '|---|---|---|---|---|---|---|']
    for size in range(1, 16):
        a = best['by_size'][f'앞_{size}']; b = best['by_size'][f'뒤_{size}']
        ca = cb = ['–'] * 3
        if a is not None: r = by.loc[a]; ca = [r['조합'], f"{int(r['앞_독립'])} · {f(r['앞_p5'], r['앞_n5'])}", f"{int(r['뒤_독립'])} · {f(r['뒤_p5'], r['뒤_n5'])}"]
        if b is not None: r = by.loc[b]; cb = [r['조합'], f"{int(r['뒤_독립'])} · {f(r['뒤_p5'], r['뒤_n5'])}", f"{int(r['앞_독립'])} · {f(r['앞_p5'], r['앞_n5'])}"]
        L.append(f'| {size} | ' + ' | '.join(ca + cb) + ' |')
    L += ['', f"참고: 앞·뒤 모두 독립 10건 이상인 조합 {best['both10']:,}개 가운데 두 구간 모두 바탕을 넘은 것 {best['both10_beat']:,}개.", '',
          '## 읽을 때 주의', '', '- 32,767개 가운데 고른 최고라 우연한 몫이 크다. 본페로니 문턱 ≈ 1.5e-6. 앞 최고의 뒤(교차) 값이 실제 시험이다.',
          '- 조건 1~15 와 문턱 자체가 앞선 연구에서 결과를 보고 고른 것이 섞여 있다.', '- 투자 권유 아님.', '']
    open(os.path.join(HERE, 'report.md'), 'w', encoding='utf-8').write('\n'.join(L))


if __name__ == '__main__':
    main()
