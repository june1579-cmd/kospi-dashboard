import pickle, numpy as np, pandas as pd, warnings
from sklearn.metrics import roc_auc_score
warnings.filterwarnings('ignore'); pd.set_option('display.width', 220)
q = pickle.load(open('q.pkl','rb')); X,Y,reg,c,P,BASE = q['X'],q['Y'],q['regime'],q['c'],q['P'],q['BASE']
oos = X.index[X.index.year >= 2018]
pu, pr = P['up10']['부스팅'][oos], P['risk5']['부스팅'][oos]
Yo = Y.loc[oos]; r = c.pct_change()
print('OOS', oos[0].date(), oos[-1].date(), len(oos))
# ---------- 1. p_up
ok = pu.notna() & Yo.up10.notna()
print('\n[1] 10일 상승 확률  AUC', round(roc_auc_score(Yo.up10[ok], pu[ok]),3), 'base', round(Yo.up10[ok].mean()*100,1))
b = pd.qcut(pu[ok], 5, labels=False)
t = pd.DataFrame({'p':pu[ok],'up':Yo.up10[ok],'r10':Yo.r10[ok],'b':b}).groupby('b').agg(n=('p','size'),p_avg=('p','mean'),up_rate=('up','mean'),r10=('r10','mean'),r10_med=('r10','median'))
print((t*[1,100,100,1,1]).round(1))
brier = ((pu[ok]-Yo.up10[ok])**2).mean(); base = Yo.up10[ok].mean(); print('Brier', round(brier,4), 'climatology', round(base*(1-base),4), 'skill', round(1-brier/(base*(1-base)),3))
hi = pu[ok]>=0.5; print('p>=0.5: n', hi.sum(), 'up', round(Yo.up10[ok][hi].mean()*100,1), 'r10', round(Yo.r10[ok][hi].mean(),2), '| p<0.5: n', (~hi).sum(), 'up', round(Yo.up10[ok][~hi].mean()*100,1), 'r10', round(Yo.r10[ok][~hi].mean(),2))
for thr in (0.7,0.8,0.9):
    h = pu[ok]>=thr; print(f'  p>={thr}: n {h.sum()} up {Yo.up10[ok][h].mean()*100:.1f} r10 {Yo.r10[ok][h].mean():.2f}')
print('연도별 AUC·p>=0.5일 때 r10 − 나머지 r10')
for y in range(2018,2027):
    m = ok & (oos.year==y); h = pu[m]>=0.5
    print(y, 'auc', round(roc_auc_score(Yo.up10[m], pu[m]),3), 'n_hi', int(h.sum()), 'r10 hi', round(Yo.r10[m][h].mean(),2), 'lo', round(Yo.r10[m][~h].mean(),2), 'all', round(Yo.r10[m].mean(),2))
# ---------- 2. p_risk
ok2 = pr.notna() & Yo.risk5.notna()
print('\n[2] 5일 내 급락·청산  AUC', round(roc_auc_score(Yo.risk5[ok2], pr[ok2]),3), 'base', round(Yo.risk5[ok2].mean()*100,1))
ev = Y['event']; past5 = ev.rolling(5).max().reindex(oos); past20 = ev.rolling(20).mean().reindex(oos); vk = X['vk'].reindex(oos)
for nm, s in (('지난 5일에 사건 있었나', past5), ('지난 20일 사건 비율', past20), ('VKOSPI 수준', vk), ('ATR14', X['atr14_pct'].reindex(oos))):
    m = ok2 & s.notna(); print('  단순 기준 AUC —', nm, round(roc_auc_score(Yo.risk5[m], s[m]),3))
b = pd.qcut(pr[ok2], 5, labels=False, duplicates='drop')
fmin5 = pd.concat([c.shift(-k)/c-1 for k in range(1,6)],axis=1).min(axis=1)*100
t = pd.DataFrame({'p':pr[ok2],'ev':Yo.risk5[ok2],'r5':Yo.r5[ok2],'min5':fmin5.reindex(oos)[ok2],'b':b}).groupby('b').agg(n=('p','size'),p_avg=('p','mean'),ev_rate=('ev','mean'),r5=('r5','mean'),min5=('min5','mean'))
print((t*[1,100,100,1,1]).round(2))
# 사건을 '코스피 하루 -3% 이하'만으로 좁히면
crash = (r*100 <= -3); c5 = pd.Series(np.nan, index=c.index); cv = crash.astype(float).values
for i in range(len(c)-5): c5.iloc[i] = cv[i+1:i+6].max()
m = pr.notna() & c5.reindex(oos).notna(); print('  좁은 사건(5일 안 코스피 하루 −3% 이하) base', round(c5.reindex(oos)[m].mean()*100,1), 'AUC 모형', round(roc_auc_score(c5.reindex(oos)[m], pr[m]),3), 'AUC VKOSPI', round(roc_auc_score(c5.reindex(oos)[m & vk.notna()], vk[m & vk.notna()]),3))
thr = pd.Series({y: BASE['risk5'][y] for y in BASE['risk5']}); thr_s = pd.Series(oos.year.map(thr).values, index=oos); sig = pr >= thr_s
print('  위험 신호 켜진 날 비율', round(sig[ok2].mean()*100,1), '| 켜진 날 r5', round(Yo.r5[ok2][sig[ok2]].mean(),2), '꺼진 날 r5', round(Yo.r5[ok2][~sig[ok2]].mean(),2), '| r10 켜짐', round(Yo.r10[sig & Yo.r10.notna()].mean(),2), '꺼짐', round(Yo.r10[(~sig) & Yo.r10.notna() & pr.notna()].mean(),2))
print('연도별: base, AUC, 신호 비율, r5 켜짐/꺼짐')
for y in range(2018,2027):
    m = ok2 & (oos.year==y); s = sig[m]
    print(y, round(Yo.risk5[m].mean()*100,1), round(roc_auc_score(Yo.risk5[m], pr[m]),3), round(s.mean()*100,1), round(Yo.r5[m][s].mean(),2), round(Yo.r5[m][~s].mean(),2))
# ---------- 3. 국면
print('\n[3] 국면별 이후 수익률(2018~, 겹치는 구간 평균)')
rg = reg.reindex(oos); df = pd.DataFrame({'rg':rg,'r1':(c.shift(-1)/c-1).reindex(oos)*100,'r5':Yo.r5,'r10':Yo.r10,'r20':Yo.r20,'min10':(pd.concat([c.shift(-k)/c-1 for k in range(1,11)],axis=1).min(axis=1)*100).reindex(oos)})
print(df.groupby('rg').agg(days=('r5','size'),r1=('r1','mean'),r5=('r5','mean'),r10=('r10','mean'),r20=('r20','mean'),up10=('r10',lambda s:(s>0).mean()*100),min10=('min10','mean')).round(2))
print('전체', df[['r1','r5','r10','r20']].mean().round(2).to_dict(), 'up10', round((df.r10>0).mean()*100,1))
print('연도별 r10 평균 by 국면'); print(df.assign(y=oos.year).pivot_table(index='y', columns='rg', values='r10', aggfunc='mean').round(1)); print(df.assign(y=oos.year).pivot_table(index='y', columns='rg', values='r10', aggfunc='size'))
pickle.dump(dict(sig=sig, thr_s=thr_s), open('sig.pkl','wb'))
