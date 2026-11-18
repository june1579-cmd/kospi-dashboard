import os, glob, numpy as np, pandas as pd
exec(open('stable_an.py').read().split("rows = []")[0])
def liquid(d):
    d = d[d['mcap'] >= 1e11]; return d[d['turnover'] >= d['turnover'].quantile(0.2)]
# 반등 비용: 저점 주 이후 26주(주간 자료), 같은 시장 중앙값 대비
RAW = os.path.join(ROOT,'raw'); W = {}
for m in ('KOSPI','KOSDAQ'):
    R = {}
    for f in sorted(glob.glob(os.path.join(RAW,'weekly',f'W_{m}_*.csv.gz'))):
        d = pd.read_csv(f, compression='gzip', index_col=0); d.index = d.index.astype(str).str.zfill(6)
        R[os.path.basename(f)[-15:-7]] = d['등락률'].astype(float)/100
    W[m] = pd.DataFrame(R)
def rebound(m, TR, n=26):
    cols = [c for c in W[m].columns if c > TR][:n]
    if len(cols) < n: return None
    return (1 + W[m][cols].fillna(0)).prod(axis=1) - 1
P['rb26'] = np.nan
for (T, m), g in P.groupby(['peak','market']):
    rb = rebound(m, str(g['trough'].iloc[0]))
    if rb is None: continue
    v = rb.reindex(g['code']).values
    P.loc[g.index, 'rb26'] = v - np.nanmedian(v)
# 점수: 에피소드 안 순위 평균(가중치 없음)
def pr(d, f): return (d[f]*F[f][1]).rank(pct=True)
SC = {'변동성만':['vol1y'], '변동성+베타':['vol1y','beta2y'], '변동성+베타+과거 성적':['vol1y','beta2y','prior_rate'],
      '+PBR':['vol1y','beta2y','prior_rate','pbr'], '+PBR+회전율':['vol1y','beta2y','prior_rate','pbr','turnover'],
      '+PBR+공매도':['vol1y','beta2y','prior_rate','pbr','short'], '배당+흑자(비교)':['div','profit_years'], '1번 결과물식 방어(비교)':['beta2y','div','pbr','profit_years']}
out = []; per = []
for nm, fs in SC.items():
    for uni, sel in (('전체', lambda d: d), ('유동성', liquid)):
        for T in eps:
            d = sel(P[P.peak == T]).copy()
            s = pd.concat([pr(d, f) for f in fs], axis=1).mean(axis=1, skipna=True)
            if fs == ['div','profit_years'] or 'profit_years' in fs:
                s = pd.concat([pr(d, f) for f in fs], axis=1).mean(axis=1)  # 흑자 없는 종목은 있는 것만
            ok = s.notna(); d = d[ok]; s = s[ok]
            rho = s.rank().corr(d['x'].rank())
            q = pd.qcut(s.rank(method='first'), 5, labels=False)
            top = d.loc[s.nlargest(50).index]
            per.append(dict(score=nm, uni=uni, peak=T, rho=rho, b5=d['beat'][q == 4].mean(), b1=d['beat'][q == 0].mean(),
                            x5=d['x'][q == 4].median(), x1=d['x'][q == 0].median(), top50=top['x'].median(), top50_beat=top['beat'].mean(),
                            rb5=d['rb26'][q == 4].median(), rb1=d['rb26'][q == 0].median(), f5=d['x_f252'][q == 4].median(), f1=d['x_f252'][q == 0].median(), oos=T < '20250601'))
PE = pd.DataFrame(per)
agg = PE.groupby(['score','uni'], sort=False).agg(rho=('rho','median'), rho_pos=('rho', lambda s: int((s>0).sum())), n=('rho','size'),
        b5=('b5','median'), b1=('b1','median'), x5=('x5','median'), x1=('x1','median'), top50=('top50','median'), top50_pos=('top50', lambda s: int((s>0).sum())),
        top50_beat=('top50_beat','median'), rb5=('rb5','median'), rb1=('rb1','median'), f5=('f5','median'), f1=('f1','median'))
for c in ('b5','b1','x5','x1','top50','top50_beat','rb5','rb1','f5','f1'): agg[c] = agg[c]*100
pd.set_option('display.width', 250)
print(agg.round(2).to_string())
PE.to_csv(os.path.join(OUT,'score_by_ep.csv'), index=False); agg.reset_index().to_csv(os.path.join(OUT,'score_summary.csv'), index=False)
# 급락 유형별
print('\n== 급락별: 지수 하락, 보통 종목 하락, 변동성·시총·PBR·베타 상관(유동성)')
rows=[]
for T in eps:
    d = liquid(P[P.peak==T])
    r = {'peak':T,'trough':str(d.trough.iloc[0]),'kospi_dd':P[(P.peak==T)&(P.market=='KOSPI')].idx_dd.iloc[0]*100,'med_kospi':P[(P.peak==T)&(P.market=='KOSPI')].med_ret.iloc[0]*100}
    for f in ('vol1y','beta2y','pbr','log_mcap','div','prior_rate'):
        s=(d[f]*F[f][1]); ok=s.notna(); r[f]=s[ok].rank().corr(d.loc[ok,'x'].rank())
    vq = pd.qcut((-d.vol1y).rank(method='first'),5,labels=False); r['lowvol_rb26'] = d.rb26[vq==4].median()*100; r['highvol_rb26']=d.rb26[vq==0].median()*100
    rows.append(r)
E = pd.DataFrame(rows); E['gap'] = E.kospi_dd - E.med_kospi
print(E.round(2).to_string(index=False))
E.to_csv(os.path.join(OUT,'by_episode.csv'), index=False)
P[['code','peak','rb26']].to_csv(os.path.join(OUT,'rb26.csv.gz'), index=False, compression='gzip')
