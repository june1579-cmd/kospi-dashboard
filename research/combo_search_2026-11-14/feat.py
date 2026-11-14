import pickle, numpy as np, pandas as pd, warnings
warnings.filterwarnings('ignore')
D = pickle.load(open('D2.pkl','rb')); K,V,F,L,C = D['K'],D['V'],D['F'],D['L'],D['C']
c,o,h,l = K.close,K.open,K.high,K.low; idx = c.index; r = c.pct_change()
X = pd.DataFrame(index=idx)
for n in (1,3,5,10,20,60,120): X[f'ret{n}'] = c.pct_change(n)*100
for n in (5,20,60,120,200): X[f'disp{n}'] = (c/c.rolling(n).mean()-1)*100
X['dd250'] = (c/c.rolling(250,min_periods=120).max()-1)*100; X['up250'] = (c/c.rolling(250,min_periods=120).min()-1)*100
X['dd60'] = (c/c.rolling(60).max()-1)*100; X['up60'] = (c/c.rolling(60).min()-1)*100
def rsi(n):
    d = c.diff(); u = d.clip(lower=0).ewm(alpha=1/n,adjust=False).mean(); dn = (-d.clip(upper=0)).ewm(alpha=1/n,adjust=False).mean(); return 100-100/(1+u/dn)
X['rsi14'] = rsi(14); X['rsi5'] = rsi(5)
e12,e26 = c.ewm(span=12,adjust=False).mean(), c.ewm(span=26,adjust=False).mean(); macd = e12-e26; X['macd_hist'] = (macd-macd.ewm(span=9,adjust=False).mean())/c*100; X['macd'] = macd/c*100
tr = pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1); X['atr14'] = tr.rolling(14).mean()/c*100
for n in (5,20,60): X[f'rv{n}'] = r.rolling(n).std()*np.sqrt(250)*100
X['rv_5_60'] = X['rv5']/X['rv60']; X['rng_pos'] = (c-l)/(h-l).replace(0,np.nan); X['gap'] = (o/c.shift()-1)*100; X['intra'] = (c/o-1)*100
up = (r>0).astype(int); X['streak'] = up.groupby((up!=up.shift()).cumsum()).cumcount().add(1)*np.where(up==1,1,-1)
X['up_days10'] = up.rolling(10).sum()
val = K.val/1e6; X['val_r20'] = val/val.rolling(20).mean(); X['val5_r60'] = val.rolling(5).mean()/val.rolling(60).mean()
mc = pd.to_numeric(K['상장시가총액'], errors='coerce').fillna(pd.to_numeric(K['상장시가총액(백만원)'], errors='coerce'))
mc = mc/mc.dropna().iloc[-1]*1.0   # 단위가 섞여 있을 수 있어 비율로만 씀
fo, ind, ins = F.foreign.reindex(idx)/1000, F.indiv.reindex(idx)/1000, F.inst.reindex(idx)/1000
for nm, s in (('for',fo),('ind',ind),('ins',ins)):
    for n in (1,5,20,60):
        X[f'{nm}{n}'] = s.rolling(n).sum() if n>1 else s
    X[f'{nm}20_val'] = s.rolling(20).sum()/val.rolling(20).sum()*100
fb = (fo>0).astype(int); X['for_streak'] = fb.groupby((fb!=fb.shift()).cumsum()).cumcount().add(1)*np.where(fb==1,1,-1)
dep = L.deposit.reindex(idx).shift(1)/1e6; cred = C.credit.reindex(idx).shift(1)/1e6; liq = L.liq.reindex(idx).shift(1)/100; misu = L.misu.reindex(idx).shift(1)/100
X['cd_ratio'] = cred/dep*100
for n in (5,20,60): X[f'dep_{n}d'] = dep.pct_change(n)*100; X[f'cr_{n}d'] = cred.pct_change(n)*100
X['cr_1d'] = cred.pct_change()*100; X['cr_vs_high'] = (cred/cred.rolling(250,min_periods=60).max()-1)*100; X['dep_vs_high'] = (dep/dep.rolling(250,min_periods=60).max()-1)*100
X['liq1'] = liq; X['liq5'] = liq.rolling(5).sum(); X['liq_ratio'] = liq/misu.shift(1)*100; X['misu_5d'] = misu.pct_change(5)*100; X['misu_dep'] = misu/(dep*1e4)*100
X['val_dep'] = val/dep*100; X['liq5_r60'] = liq.rolling(5).mean()/liq.rolling(60).mean()
vk = V.close.reindex(idx).ffill(limit=3); X['vk'] = vk; X['vk_1d'] = vk.pct_change()*100; X['vk_5d'] = vk.pct_change(5)*100; X['vk_20d'] = vk.pct_change(20)*100; X['vk_r60'] = vk/vk.rolling(60).mean(); X['vk_rv20'] = vk/X['rv20']
vix = D['VIX']; vix = vix.reindex(idx.union(vix.index)).ffill().reindex(idx).shift(1); X['vix'] = vix; X['vix_5d'] = vix.pct_change(5)*100; X['vix_r60'] = vix/vix.rolling(60).mean()
fx = pd.read_csv('/home/claude/kospi-dashboard/out/fx_daily.csv', parse_dates=['date']).set_index('date').usdkrw; fx = fx.reindex(idx.union(fx.index)).ffill().reindex(idx).shift(1)
X['fx_5d'] = fx.pct_change(5)*100; X['fx_20d'] = fx.pct_change(20)*100; X['fx_r250'] = fx/fx.rolling(250,min_periods=120).mean()
X = X.replace([np.inf,-np.inf],np.nan)
print(X.shape, 'features'); print(X.notna().sum().sort_values().head(12))
# 인과적 순위: 지난 750거래일 안에서 오늘 값의 백분위
RK = X.rolling(750, min_periods=250).rank(pct=True)
Y = pd.DataFrame(index=idx)
for n in (5,10,20): Y[f'r{n}'] = (c.shift(-n)/c-1)*100
pickle.dump(dict(X=X,RK=RK,Y=Y,c=c), open('feat.pkl','wb'))
print(RK.notna().sum().min(), RK.index[RK.notna().all(axis=1)][0] if RK.notna().all(axis=1).any() else None)
