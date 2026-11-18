import os, numpy as np, pandas as pd
exec(open('stable_an.py').read().split("rows = []")[0])
def liquid(d):
    d = d[d['mcap'] >= 1e11]; return d[d['turnover'] >= d['turnover'].quantile(0.2)]
L = pd.concat([liquid(P[P.peak == T]) for T in eps])
# 1) 과거 성적의 지속: 과거 급락 5번 이상 기록, 과거 덜 빠진 비율 구간별 이번 급락 결과
L5 = L[L.n_prior >= 5].copy()
L5['band'] = pd.cut(L5.prior_rate, [-0.01, 0.3, 0.45, 0.55, 0.7, 1.0], labels=['30% 이하','30~45%','45~55%','55~70%','70% 초과'])
g = L5.groupby('band', observed=True).agg(n=('x','size'), beat=('beat','mean'), x=('x','median'))
g['beat'] *= 100; g['x'] *= 100
print('== 과거 기록(5번 이상) 구간별 이번 급락(유동성 종목)'); print(g.round(1).to_string())
# 변동성 같은 구간 안에서도 과거 성적이 남는지: 변동성 3분위 × 과거 성적 상/하
L5['vq'] = L5.groupby('peak')['vol1y'].transform(lambda s: pd.qcut(s.rank(method='first'), 3, labels=['낮음','중간','높음']))
L5['pr_hi'] = L5.prior_rate >= 0.6
h = L5.groupby(['vq','pr_hi'], observed=True).agg(n=('x','size'), beat=('beat','mean'), x=('x','median'))
h['beat'] *= 100; h['x'] *= 100
print('\n== 변동성 3분위 × 과거 덜 빠진 비율 60% 이상'); print(h.round(1).to_string())
# 2) 업종: 급락마다 업종 중앙값이 보통 종목보다 나았는지 (유동성, 업종 종목 5개 이상)
rows = []
for T in eps:
    d = L[L.peak == T]
    for (m, s), gg in d.groupby(['market','sector']):
        if len(gg) >= 5:
            rows.append(dict(peak=T, market=m, sector=s, n=len(gg), x=gg.x.median(), beat=gg.beat.mean(), vol=gg.vol1y.median()))
S = pd.DataFrame(rows)
sec = S.groupby(['market','sector']).agg(eps=('peak','size'), n=('n','median'), win=('x', lambda v: (v > 0).mean() * 100), x=('x','median'), beat=('beat','median'), vol=('vol','median')).reset_index()
sec = sec[sec.eps >= 15]; sec['x'] *= 100; sec['beat'] *= 100
print('\n== 업종(15번 이상 급락에 5종목 이상) — 업종 중앙값이 보통 종목보다 나았던 급락 비율 상위·하위')
print(sec.sort_values('win', ascending=False).head(15).round(1).to_string(index=False))
print(sec.sort_values('win').head(10).round(1).to_string(index=False))
sec.to_csv(os.path.join(OUT,'sectors.csv'), index=False)
# 업종 효과가 변동성 밖에서도 남는지: 업종 안에서 변동성 하위 1/3 vs 상위 1/3
L['vq'] = L.groupby(['peak','sector'])['vol1y'].transform(lambda s: pd.qcut(s.rank(method='first'), 3, labels=False) if len(s) >= 6 else np.nan)
w = L.dropna(subset=['vq']).groupby('vq').agg(beat=('beat','mean'), x=('x','median'))
print('\n== 같은 업종 안 변동성 3분위', (w*100).round(1).to_string())
# 3) 종목 기록: 유동성 종목으로 15번 이상 급락을 겪은 종목
rec = L.groupby('code').agg(name=('name','last'), market=('market','last'), sector=('sector','last'), eps=('x','size'), beat=('beat','mean'), x=('x','median'), worst=('x','min'))
rec = rec[rec.eps >= 15]
print('\n== 15번 이상 겪은 유동성 종목', len(rec), '· 덜 빠진 비율 분포'); print((rec.beat*100).describe().round(1).to_string())
# 동전 던지기 기준: 15~22번 중 80% 이상 덜 빠질 확률
from math import comb
def tail(n, k): return sum(comb(n, j) for j in range(k, n + 1)) / 2 ** n
exp = sum(tail(int(n), int(np.ceil(0.8 * n))) for n in rec.eps)
print('80% 이상 덜 빠진 종목', int((rec.beat >= 0.8).sum()), '· 우연이라면 기대', round(exp, 1))
print('70% 이상', int((rec.beat >= 0.7).sum()), '· 우연 기대', round(sum(tail(int(n), int(np.ceil(0.7 * n))) for n in rec.eps), 1))
rec.to_csv(os.path.join(OUT,'records.csv'))
print(rec.sort_values(['beat','x'], ascending=False).head(30).round(3).to_string())
