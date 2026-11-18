import os, numpy as np, pandas as pd
exec(open('stable_an.py').read().split("rows = []")[0])
# 1) 유동성 있는 종목만: 시총 1000억 이상 + 1년 회전율 하위 20% 제외(에피소드별)
def liquid(d):
    d = d[d['mcap'] >= 1e11]
    return d[d['turnover'] >= d['turnover'].quantile(0.2)]
keys = ['vol1y','beta2y','down_beta','max_week','turnover','pbr','div','earn_yield','mdd2y','short','prior_rate','log_mcap','ret1y','frgn_ratio','inst_1y','big_flow','up_week']
out = []
for f in keys:
    lab, sgn, cat = F[f]; r1 = []; r2 = []; sp = []; b5=[]; b1=[]
    for T in eps:
        d = liquid(P[P['peak'] == T]); s = d[f] * sgn; ok = s.notna()
        if ok.sum() < 200: continue
        r1.append(s[ok].rank().corr(d.loc[ok, 'x'].rank()))
        q = pd.qcut(s[ok].rank(method='first'), 5, labels=False)
        xq = d.loc[ok,'x'].groupby(q).median(); bq = d.loc[ok,'beat'].groupby(q).mean()
        sp.append(xq.iloc[-1]-xq.iloc[0]); b5.append(bq.iloc[-1]); b1.append(bq.iloc[0])
    out.append(dict(key=f, trait=lab, n=len(r1), rho=np.median(r1), pos=int(sum(x>0 for x in r1)), spread=np.median(sp)*100, b5=np.median(b5)*100, b1=np.median(b1)*100))
L = pd.DataFrame(out).sort_values('rho', ascending=False)
print('== 유동성 있는 종목만(시총 1000억+, 회전율 하위 20% 제외), 종목 수 중앙값', int(np.median([len(liquid(P[P.peak==T])) for T in eps])))
print(L.round(3).to_string(index=False))
L.to_csv(os.path.join(OUT,'trait_liquid.csv'), index=False)

# 2) 변동성을 통제한 뒤 남는 힘(에피소드 안 순위 → 변동성 순위로 회귀한 잔차와 x 순위 상관)
print('\n== 변동성(1년)을 뺀 뒤 남는 힘 (전체 / 유동성)')
res = []
for f in keys + ['profit_years']:
    if f == 'vol1y': continue
    lab, sgn, cat = F[f]
    for nm, sel in (('all', lambda d: d), ('liq', liquid)):
        rr = []
        for T in eps:
            d = sel(P[P['peak'] == T]); d = d[d[f].notna() & d['vol1y'].notna()]
            if len(d) < 200: continue
            a = (d[f]*sgn).rank(pct=True); v = (-d['vol1y']).rank(pct=True); y = d['x'].rank(pct=True)
            ra = a - np.polyval(np.polyfit(v, a, 1), v); ry = y - np.polyval(np.polyfit(v, y, 1), v)
            rr.append(np.corrcoef(ra, ry)[0,1])
        res.append(dict(key=f, trait=lab, sample=nm, n=len(rr), pcor=np.median(rr), pos=int(sum(x>0 for x in rr))))
Rp = pd.DataFrame(res).pivot_table(index=['key','trait'], columns='sample', values=['pcor','pos','n']).round(3)
print(Rp.sort_values(('pcor','all'), ascending=False).to_string())
pd.DataFrame(res).to_csv(os.path.join(OUT,'trait_partial.csv'), index=False)
