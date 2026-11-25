# 11/16 수급 지표를 원래 점수 순위(scores_1116)와 대조
import os, sys, json, numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE); sys.path.insert(0, ROOT)
exec(open(os.path.join(HERE, 'screen_check.py')).read().split("U = SC.stable_list")[0])
END = '20261116'
A = SC.universe_A(CAP, NAMES, V, wend, wdays, st)
shares = pd.concat([CAP[m]['상장주식수'].astype(float) for m in ('KOSPI', 'KOSDAQ')])
c52 = wend[-52:]
V52 = pd.concat([V[m][c52].sum(axis=1) for m in ('KOSPI', 'KOSDAQ')])
FR_END = pd.concat([rd(f'snap/FR_{m}_{END}.csv.gz')['지분율'].astype(float) for m in ('KOSPI', 'KOSDAQ')])
FL = SC.load_flows(END, list(days), {m: [c for c in A.index if A.at[c, 'market'] == m] for m in ('KOSPI', 'KOSDAQ')}, shares, ix, V52, FR_END, print)
O = pd.DataFrame(json.load(open(os.path.join(ROOT, 'ref', 'scores_1116.json')))).set_index('code')
cmp = {'fr': 1, 'fr_off': 1, 'big': 1, 'big_mpos': 100, 'big_wpos': 100, 'crash_buy': 100, 'crash_net': 1, 'big7': 1, 'crash_buy7': 100}
for k, mul in cmp.items():
    a = FL[k].reindex(O.index) * mul; b = O[k]; ok = a.notna() & b.notna()
    print(f'{k:11s} n={ok.sum():3d} corr={a[ok].corr(b[ok]):.3f} medabs={np.median(np.abs(a[ok]-b[ok])):.2f} exact%={(np.abs(a[ok]-b[ok])<0.6).mean()*100:.0f}')
fs = SC.flow_score(FL, A.index)
ok = fs.reindex(O.index).notna()
print('수급 가중 점수 corr', round(fs.reindex(O.index)[ok].corr(O.flow[ok]), 3), 'spearman', round(fs.reindex(O.index)[ok].corr(O.flow[ok], method='spearman'), 3), 'n', ok.sum(), 'in A', O.index.isin(A.index).sum())
FL.to_pickle('/tmp/FL1116.pkl'); A.to_pickle('/tmp/A1116.pkl')
