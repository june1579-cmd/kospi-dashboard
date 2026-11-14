import pickle, numpy as np, pandas as pd, sys, warnings
from sklearn.metrics import roc_auc_score
warnings.filterwarnings('ignore'); pd.set_option('display.width', 250)
R = pickle.load(open(sys.argv[1] if len(sys.argv) > 1 else 'res3.pkl','rb')); df, names, C, valid, r10, r20, yrs = [R[k] for k in ('df','names','C','valid','r10','r20','yrs')]
f = pickle.load(open('feat.pkl','rb')); idx = f['RK'].index; N = len(idx)
TEST = list(range(2018, 2027)); share = {}
def episodes(mask, gap=10):
    p = np.where(mask)[0]; return 0 if not len(p) else 1 + int((np.diff(p) > gap).sum())
for tg in ('up10','up20'):
    r = r10 if tg == 'up10' else r20; d = df[df.tg == tg].sort_values(['fold','score'], ascending=[True, False])
    for K in (10, 100, 1000):
        s = np.full(N, np.nan)
        for y in TEST:
            g = d[d.fold == y].head(K)
            S = np.stack([C[:, a] & C[:, b] & C[:, c_] for a, b, c_ in g[['a','b','c']].values], 1); ym = yrs == y; s[ym] = S[ym].mean(1)
        share[(tg, K)] = s
        m = valid & (yrs >= 2018); print(f'\n== {tg} 상위 {K}개 규칙 중 켜진 비율별 실제 결과(2018~2026 검증)  AUC {roc_auc_score(r[m] > 0, s[m]):.3f}')
        bins = [(-1, 0, '0'), (0, 0.05, '0~5%'), (0.05, 0.2, '5~20%'), (0.2, 0.5, '20~50%'), (0.5, 1.01, '50%+')]
        for lo, hi, lab in bins:
            mm = m & (s > lo) & (s <= hi)
            if mm.sum(): print(f'  켜진 비율 {lab:>7}: {int(mm.sum()):5d}일 · 묶음 {episodes(mm):3d}번 · 상승 비율 {(r[mm] > 0).mean() * 100:5.1f}% · 평균 {r[mm].mean():+5.2f}% · 중앙 {np.median(r[mm]):+5.2f}% · 최악 {r[mm].min():+6.1f}% | 연도 ' + ' '.join(f"{y % 100}:{int((mm & (yrs == y)).sum())}" for y in TEST if (mm & (yrs == y)).sum()))
pickle.dump(share, open('share.pkl','wb'))
# 지금(목표를 아직 모르는 최근 날 포함) 2026년 규칙이 켜진 날
s = share[('up10', 100)]; s1 = share[('up10', 10)]; s20 = share[('up20', 100)]
t = pd.DataFrame({'up10_top10': s1, 'up10_top100': s, 'up20_top100': s20, 'kospi': f['c'].values, 'r10': r10, 'r20': r20}, index=idx)
print('\n2026년 하반기: 규칙이 켜진 날(상위 100개 중 5% 이상)'); print(t[(t.index >= '2026-06-01') & ((t.up10_top100 >= 0.05) | (t.up20_top100 >= 0.05))].round(2).to_string())
print('\n최근 12거래일'); print(t.tail(12).round(2).to_string())
