import pickle, numpy as np, pandas as pd, sys, warnings
warnings.filterwarnings('ignore'); pd.set_option('display.width', 250); pd.set_option('display.max_colwidth', 90)
R = pickle.load(open(sys.argv[1] if len(sys.argv) > 1 else 'res3.pkl','rb')); df, bf, names, C, valid, r10, r20, yrs = [R[k] for k in ('df','bf','names','C','valid','r10','r20','yrs')]
TEST = list(range(2018, 2027)); out = []
def fwd(tg): return r10 if tg.endswith('10') else r20
def hit(tg, r): return (r > 0) if tg.startswith('up') else (r <= 0)
for tg in ['up10','dn10','up20','dn20']:
    r = fwd(tg); te = valid & (yrs >= 2018); base = hit(tg, r[te]).mean() * 100; base_r = r[te].mean()
    d = df[df.tg == tg].sort_values(['fold','score'], ascending=[True, False])
    print(f'\n===== {tg}: 검증 구간(2018~2026) 기준 비율 {base:.1f}% · 평균 수익률 {base_r:+.2f}%  (후보 {len(d):,}개 보관)')
    for K in (1, 10, 100, 1000):
        tr_n = tr_h = 0; any_m = np.zeros(len(yrs), bool); vote_m = np.zeros(len(yrs), bool); one_n = one_h = 0
        for y in TEST:
            g = d[d.fold == y].head(K)
            if not len(g): continue
            tr_n += g.n_tr.sum(); tr_h += (g.h_tr if tg.startswith('up') else g.n_tr - g.h_tr).sum()
            one_n += g.n_te.sum(); one_h += (g.h_te if tg.startswith('up') else g.n_te - g.h_te).sum()
            S = np.stack([C[:, a] & C[:, b] & C[:, c_] for a, b, c_ in g[['a','b','c']].values], 1); ym = (yrs == y) & valid
            any_m |= ym & S.any(1); vote_m |= ym & (S.mean(1) >= 0.5)
        f = lambda m: (int(m.sum()), round(hit(tg, r[m]).mean() * 100, 1) if m.sum() else np.nan, round(r[m].mean(), 2) if m.sum() else np.nan)
        print(f' 상위 {K:>4}개: 학습 구간 적중 {tr_h / max(tr_n, 1) * 100:5.1f}% → 검증 적중 {one_h / max(one_n, 1) * 100:5.1f}% (규칙별 합산 {int(one_n):,}일) | 하나라도 켜진 날 n,적중,수익 {f(any_m)} | 과반 켜진 날 {f(vote_m)}')
        if K == 1: top1 = any_m.copy()
    # 상위 1개 연도별
    print('  상위 1개 규칙(해마다 그 전 자료로 뽑음):')
    for y in TEST:
        g = d[d.fold == y].head(1)
        if not len(g): print('  ', y, '조건 맞는 규칙 없음'); continue
        x = g.iloc[0]; hte = x.h_te if tg.startswith('up') else x.n_te - x.h_te; htr = x.h_tr if tg.startswith('up') else x.n_tr - x.h_tr
        ym = (yrs == y) & valid; by = hit(tg, r[ym]).mean() * 100
        print(f"   {y}: 학습 {htr / x.n_tr * 100:4.0f}%({int(x.n_tr)}일) → 검증 {hte / x.n_te * 100 if x.n_te else float('nan'):4.0f}%({int(x.n_te)}일) · 그해 기준 {by:4.0f}% | {names[int(x.a)]} & {names[int(x.b)]} & {names[int(x.c)]}")
    out.append((tg, top1))
    b = bf[bf.tg == tg].sort_values('score', ascending=False).head(3)
    for _, x in b.iterrows():
        hh = x.h_tr if tg.startswith('up') else x.n_tr - x.h_tr; print(f"  [사후 최고·전 기간에 맞춘 것] 적중 {hh / x.n_tr * 100:.1f}%({int(x.n_tr)}일) | {names[int(x.a)]} & {names[int(x.b)]} & {names[int(x.c)]}")
pickle.dump(dict(out), open('top1_' + (sys.argv[1] if len(sys.argv) > 1 else 'res3.pkl'), 'wb'))
