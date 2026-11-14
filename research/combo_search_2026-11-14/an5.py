import pickle, numpy as np, pandas as pd, sys, warnings
warnings.filterwarnings('ignore'); pd.set_option('display.width', 250)
R = pickle.load(open(sys.argv[1],'rb')); df, names, C, yrs = [R[k] for k in ('df','names','C','yrs')]
f = pickle.load(open('feat.pkl','rb')); idx = f['RK'].index; N = len(idx); c = f['c'].values
SH = int(sys.argv[2]) if len(sys.argv) > 2 else 0
Y = f['Y']; RR = {'10': np.roll(Y['r10'].values, SH) if SH else Y['r10'].values, '20': np.roll(Y['r20'].values, SH) if SH else Y['r20'].values}
TEST = list(range(2018, 2027))
def episodes(mask, gap=10):
    p = np.where(mask)[0]; return 0 if not len(p) else 1 + int((np.diff(p) > gap).sum())
print('검증: 2018~2026에서 목표를 아는 모든 날(연말·최근 포함)')
for tg in ('up10','dn10','up20','dn20'):
    r = RR[tg[-2:]]; ok = ~np.isnan(r) & (yrs >= 2018); hit = (r > 0) if tg.startswith('up') else (r <= 0)
    d = df[df.tg == tg].sort_values(['fold','score'], ascending=[True, False]); line = f'{tg} 기준 {hit[ok].mean()*100:.1f}% |'
    for K in (1, 10, 100, 1000):
        s = np.zeros(N); 
        for y in TEST:
            g = d[d.fold == y].head(K)
            if len(g): S = np.stack([C[:, a] & C[:, b] & C[:, c_] for a, b, c_ in g[['a','b','c']].values], 1); ym = yrs == y; s[ym] = S[ym].mean(1)
        a = ok & (s > 0); m = ok & (s >= 0.5)
        line += f' 상위{K}: 하나라도 {int(a.sum())}일 {hit[a].mean()*100:.1f}%({episodes(a)}묶음), 과반 {int(m.sum())}일 {hit[m].mean()*100 if m.sum() else float("nan"):.1f}%({episodes(m)}묶음) |'
        if tg == 'up10' and K == 10: s10 = s.copy()
        if tg == 'up10' and K == 100: s100 = s.copy()
    print(line)
if not SH:
    r = RR['10']; ok = ~np.isnan(r) & (yrs >= 2018)
    print('\nup10 상위 10개 규칙 과반(50%+) 켜진 묶음별 결과')
    m = (s10 >= 0.5) & (yrs >= 2018); p = np.where(m)[0]; st = [p[0]] + [p[i] for i in range(1, len(p)) if p[i] - p[i-1] > 10]
    for a0 in st:
        q = [i for i in p if a0 <= i and (i - a0) < 400 and all(True for _ in [0])]; grp = [a0]
        for i in p[p > a0]:
            if i - grp[-1] <= 10: grp.append(i)
            else: break
        rr = r[grp]; kn = ~np.isnan(rr)
        print(f'  {str(idx[grp[0]])[:10]} ~ {str(idx[grp[-1]])[:10]} · {len(grp)}일 · 첫날 코스피 {c[grp[0]]:,.0f} · 10일 뒤 상승 {int((rr[kn] > 0).sum())}/{int(kn.sum())}일 · 평균 {np.nanmean(rr) if kn.any() else float("nan"):+.1f}% · 첫날 진입 {rr[0]:+.1f}%' + (' · 결과 미확정 ' + str(int((~kn).sum())) + '일' if (~kn).any() else ''))
    pickle.dump(dict(s10=s10, s100=s100), open('s_up10.pkl','wb'))
