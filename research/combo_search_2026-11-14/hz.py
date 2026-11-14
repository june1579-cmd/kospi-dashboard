import pickle, numpy as np, pandas as pd, sys, warnings
warnings.filterwarnings('ignore')
f = pickle.load(open('feat.pkl','rb')); c = f['c']; idx = c.index; N = len(idx); cv = c.values
TEST = list(range(2018, 2027))
def fwd(h): return ((c.shift(-h) / c - 1) * 100).values
def episodes(mask, gap=10):
    p = np.where(mask)[0]; g = []
    for i in p:
        if g and i - g[-1][-1] <= gap: g[-1].append(i)
        else: g.append([i])
    return g
def signals(resfile, h, BEAM=400):
    R = pickle.load(open(resfile,'rb')); df, C, valid, yrs = R['df'], R['C'], R['valid'], R['yrs']; M = C.shape[1]; Cf = C.astype(np.float32)
    r = fwd(h); u = (r > 0) & valid; d = df[df.tg == f'up{h}'].sort_values(['fold','score'], ascending=[True, False])
    out = {k: np.zeros(N, bool) for k in ('3조건 1위', '3조건 상위10', '4조건 1위', '4조건 상위10')}; learn = {'3조건 1위': [0, 0], '4조건 1위': [0, 0]}
    for y in TEST:
        ym = yrs == y; g = d[d.fold == y]
        if not len(g): continue
        t10 = np.stack([C[:, a] & C[:, b] & C[:, c_] for a, b, c_ in g.head(10)[['a','b','c']].values], 1)
        out['3조건 1위'] |= ym & t10[:, 0]; out['3조건 상위10'] |= ym & t10.any(1); learn['3조건 1위'][0] += g.iloc[0].h_tr; learn['3조건 1위'][1] += g.iloc[0].n_tr
        gg = g.head(BEAM)[['a','b','c']].values; T = np.stack([C[:, a] & C[:, b] & C[:, c_] for a, b, c_ in gg], 1); Tf = T.astype(np.float32)
        nC = np.zeros((len(gg), M), np.float32); hC = np.zeros_like(nC); act = np.zeros_like(nC); good = np.zeros_like(nC)
        for yy in range(2007, y):
            rw = np.where((yrs == yy) & valid)[0]; ru = rw[u[rw]]; n_y = Tf[rw].T @ Cf[rw]; h_y = Tf[ru].T @ Cf[ru]
            nC += n_y; hC += h_y; a = n_y >= 5; act += a; good += a & (h_y > 0.5 * n_y)
        p0 = u[(yrs < y) & valid].mean(); sc = np.where((nC >= 120) & (act >= 5) & (good >= 0.7 * act), (hC + 40 * p0) / (nC + 40), -1)
        for ti, (a, b, c_) in enumerate(gg): sc[ti, [a, b, c_]] = -1
        flat = np.argsort(sc.ravel())[::-1][:10]; S = []
        for rank, t in enumerate(flat):
            if sc.ravel()[t] <= 0: break
            ti, cj = divmod(int(t), M); S.append(T[:, ti] & C[:, cj])
            if rank == 0: learn['4조건 1위'][0] += hC[ti, cj]; learn['4조건 1위'][1] += nC[ti, cj]
        if S: S = np.stack(S, 1); out['4조건 1위'] |= ym & S[:, 0]; out['4조건 상위10'] |= ym & S.any(1)
    return out, {k: v[0] / max(v[1], 1) * 100 for k, v in learn.items()}
def stat(mask, h):
    r = fwd(h); yrs = idx.year.values; ok = ~np.isnan(r) & (yrs >= 2018); m = mask & ok; base = (r[ok] > 0).mean() * 100; br = r[ok].mean()
    if not m.sum(): return None
    ep = episodes(m); first = np.array([r[g[0]] for g in ep]); epm = np.array([r[g].mean() for g in ep])
    return dict(일수=int(m.sum()), 묶음=len(ep), 적중=round((r[m] > 0).mean() * 100, 1), 기준=round(base, 1), 차이=round((r[m] > 0).mean() * 100 - base, 1), 평균수익=round(r[m].mean(), 2), 기준수익=round(br, 2),
                묶음승=f'{int((epm > 0).sum())}/{len(ep)}', 첫날진입승=f'{int((first > 0).sum())}/{len(ep)}', 최악=round(r[m].min(), 1), 큰묶음비중=round(max(len(g) for g in ep) / m.sum() * 100))
if __name__ == '__main__':
    pd.set_option('display.width', 250)
    mode = sys.argv[1]
    if mode == 'A':   # 10일 기준으로 고른 신호를 여러 기간으로 채점
        sg, _ = signals('res3.pkl', 10); pickle.dump(sg, open('sig10.pkl', 'wb'))
        for fam in ('4조건 상위10', '3조건 1위'):
            print(f'\n[10일 기준으로 고른 {fam} 신호] 보유 기간만 바꿔 채점'); rows = []
            for h in (1, 2, 3, 5, 7, 10, 15, 20, 30, 40, 60, 90, 120): rows.append(dict(기간=h, **stat(sg[fam], h)))
            print(pd.DataFrame(rows).to_string(index=False))
    else:             # 기간별로 조합을 다시 고름
        rows = []
        for resfile, hs in (('res_3_5.pkl', (3, 5)), ('res3.pkl', (10, 20)), ('res_40_60.pkl', (40, 60))):
            for h in hs:
                try: sg, lr = signals(resfile, h)
                except FileNotFoundError: continue
                pickle.dump(sg, open(f'sig{h}.pkl', 'wb'))
                for fam in ('3조건 1위', '3조건 상위10', '4조건 1위', '4조건 상위10'):
                    s = stat(sg[fam], h)
                    if s: rows.append(dict(목표기간=h, 조합=fam, 학습적중=round(lr.get(fam, float('nan')), 1), **s))
        print(pd.DataFrame(rows).to_string(index=False))
