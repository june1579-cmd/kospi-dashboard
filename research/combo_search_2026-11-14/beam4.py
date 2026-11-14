import pickle, numpy as np, pandas as pd, warnings, time
warnings.filterwarnings('ignore')
R = pickle.load(open('res3.pkl','rb')); df, names, C, valid, yrs = [R[k] for k in ('df','names','C','valid','yrs')]
f = pickle.load(open('feat.pkl','rb')); Y = f['Y']; N, M = C.shape; Cf = C.astype(np.float32)
TEST = list(range(2018, 2027)); BEAM = 400; t0 = time.time(); total = 0
def episodes(mask, gap=10):
    p = np.where(mask)[0]; return 0 if not len(p) else 1 + int((np.diff(p) > gap).sum())
for tg in ('up10', 'up20', 'dn10'):
    r = Y['r' + tg[-2:]].values; u = (r > 0) & valid; up = tg.startswith('up'); ok = ~np.isnan(r)
    d = df[df.tg == tg].sort_values(['fold','score'], ascending=[True, False]); agg = {1: [0, 0], 10: [0, 0]}; anym = {1: np.zeros(N, bool), 10: np.zeros(N, bool)}; votem = np.zeros(N, bool); tr_h = tr_n = 0; ex = []
    for y in TEST:
        g = d[d.fold == y].head(BEAM)[['a','b','c']].values
        T = np.stack([C[:, a] & C[:, b] & C[:, c_] for a, b, c_ in g], 1); Tf = T.astype(np.float32)
        nC = np.zeros((len(g), M), np.float32); hC = np.zeros_like(nC); act = np.zeros_like(nC); good = np.zeros_like(nC)
        for yy in range(2007, y):
            rw = np.where((yrs == yy) & valid)[0]; ru = rw[u[rw]]
            n_y = Tf[rw].T @ Cf[rw]; h_y = Tf[ru].T @ Cf[ru]
            if not up: h_y = n_y - h_y
            nC += n_y; hC += h_y; a = n_y >= 5; act += a; good += a & (h_y > 0.5 * n_y)
        total += nC.size
        p0 = (u[(yrs < y) & valid].mean() if up else 1 - u[(yrs < y) & valid].mean())
        sc = np.where((nC >= 120) & (act >= 5) & (good >= 0.7 * act), (hC + 40 * p0) / (nC + 40), -1)
        for ti, (a, b, c_) in enumerate(g): sc[ti, [a, b, c_]] = -1          # 같은 조건을 다시 붙인 것은 제외(3조건과 같음)
        flat = np.argsort(sc.ravel())[::-1][:10]; ym = (yrs == y) & ok; S = []
        for rank, t in enumerate(flat):
            if sc.ravel()[t] <= 0: break
            ti, cj = divmod(int(t), M); m = T[:, ti] & C[:, cj]; S.append(m)
            if rank == 0: tr_h += hC[ti, cj]; tr_n += nC[ti, cj]; ex.append(f"{y}: " + ' & '.join(names[i] for i in list(g[ti]) + [cj]))
        if S:
            S = np.stack(S, 1)
            if y == 2026 and tg == 'up10': LAST10 = S.any(1)
            anym[1] |= ym & S[:, 0]; anym[10] |= ym & S.any(1); votem |= ym & (S.mean(1) >= 0.5)
    hit = (r > 0) if up else (r <= 0); base = hit[ok & (yrs >= 2018)].mean() * 100
    pr = lambda m: f'{int(m.sum())}일 {hit[m].mean() * 100 if m.sum() else float("nan"):.1f}%({episodes(m)}묶음)'
    print(f'{tg} 4조건(3조건 상위 {BEAM}개 × 조건 {M}개, 해마다): 기준 {base:.1f}% | 상위1 학습 {tr_h / max(tr_n, 1) * 100:.1f}% → 검증 {pr(anym[1])} | 상위10 하나라도 {pr(anym[10])} · 과반 {pr(votem)}')
    print('   ', ' / '.join(ex[-2:]))
    if tg == 'up10':
        idx = f['RK'].index; cc = f['c'].values; m = anym[10] | ((yrs == 2026) & np.isnan(r) & LAST10); p = np.where(m)[0]; grp = [[p[0]]]
        for i in p[1:]:
            if i - grp[-1][-1] <= 10: grp[-1].append(i)
            else: grp.append([i])
        for g_ in grp:
            rr = r[g_]; kn = ~np.isnan(rr); print(f'     {str(idx[g_[0]])[:10]}~{str(idx[g_[-1]])[:10]} {len(g_)}일 · 코스피 {cc[g_[0]]:,.0f} · 상승 {int((rr[kn] > 0).sum())}/{int(kn.sum())} · 평균 {np.nanmean(rr) if kn.any() else float("nan"):+.1f}%' + (f' · 미확정 {int((~kn).sum())}일' if (~kn).any() else ''))
print('평가한 4조건 조합 수', f'{total:,}', round(time.time() - t0), 's')
