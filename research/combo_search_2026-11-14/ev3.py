import pickle, numpy as np, pandas as pd, warnings, sys
warnings.filterwarnings('ignore'); pd.set_option('display.width', 220)
sys.path.insert(0,'/home/claude/kospi-dashboard/pkg'); import quant
q = pickle.load(open('q.pkl','rb')); X,Y,reg,c,P,BASE = q['X'],q['Y'],q['regime'],q['c'],q['P'],q['BASE']
s = pickle.load(open('sig.pkl','rb')); risk = s['sig']
oos = X.index[X.index.year >= 2018]; cl = c.reindex(oos); r = cl.pct_change().fillna(0)
pu, pr = P['up10']['부스팅'][oos], P['risk5']['부스팅'][oos]; rg = reg.reindex(oos)
def stats(ret, name, pos=None):
    eq = (1+ret).cumprod(); tot = eq.iloc[-1]-1; mdd = (eq/eq.cummax()-1).min(); sh = ret.mean()/ret.std()*np.sqrt(250) if ret.std()>0 else np.nan
    yrs = len(ret)/250; cagr = (1+tot)**(1/yrs)-1
    return dict(전략=name, 총수익=round(tot*100,1), 연환산=round(cagr*100,1), 최대낙폭=round(mdd*100,1), 샤프=round(sh,2), 보유비율=round(pos.mean()*100,1) if pos is not None else 100.0)
def overlay(hold_sig, name, lag=2, cost=0.0015):
    # hold_sig: 그날 종가 뒤 아는 '보유 여부'. lag=2: 다음 날 종가에 실행 → 그 다음 날 수익부터 반영
    pos = hold_sig.astype(float).shift(lag).fillna(0); ret = r*pos; sw = pos.diff().abs().fillna(0); ret = ret - sw*cost
    d = stats(ret, name, pos); d['매매횟수'] = int(sw.sum()); return d, ret
rows = [stats(r, '코스피 보유')]
# 대시보드의 부스팅 매매(10일 보유)
bst_buy = pu >= 0.5
ret, trades, pos = quant.simulate(c, bst_buy.reindex(c.index).fillna(False), risk.reindex(c.index).fillna(False), oos)
d = stats(ret, '정밀검증 매매(부스팅 매수·위험 시 보류, 10일 보유)', pd.Series(pos, index=oos)); d['매매횟수'] = len(trades); rows.append(d)
ret2, trades2, pos2 = quant.simulate(c, bst_buy.reindex(c.index).fillna(False), pd.Series(False, index=c.index), oos)
d = stats(ret2, '부스팅 매수만(위험 무시, 10일 보유)', pd.Series(pos2, index=oos)); d['매매횟수'] = len(trades2); rows.append(d)
for nm, sig in (('위험 신호 꺼진 날만 보유', ~risk), ('위험 신호 켜진 날만 보유(반대)', risk), ('상승확률 50% 이상인 날만 보유', pu>=0.5), ('상승확률 70% 이상인 날만 보유', pu>=0.7),
                ('국면: 고변동 청산만 피함', rg!='고변동 청산'), ('국면: 횡보만 피함', rg!='횡보'), ('국면: 상승 추세만 보유', rg=='상승 추세'), ('국면: 상승+하락 추세만 보유', rg.isin(['상승 추세','하락 추세'])), ('국면: 하락 추세만 피함', rg!='하락 추세')):
    d, _ = overlay(sig.fillna(False), nm); rows.append(d)
print(pd.DataFrame(rows).to_string(index=False))
# 연도별: 보유 vs 정밀검증 매매 vs 위험 회피 vs 횡보 회피
yr = lambda x: (1+x).groupby(x.index.year).prod()-1
o1 = overlay((~risk).fillna(False),'a')[1]; o2 = overlay((rg!='횡보'),'b')[1]; o3 = overlay((rg=='상승 추세'),'c')[1]
print('\n연도별 수익률(%)'); print((pd.DataFrame({'보유':yr(r),'정밀검증 매매':yr(ret),'위험 꺼진 날만':yr(o1),'횡보 피함':yr(o2),'상승 추세만':yr(o3)})*100).round(1))
# 매매 내역 요약
T = pd.DataFrame([(a,b,x*100,o) for a,b,x,o in trades], columns=['in','out','ret','open'])
print('\n정밀검증 매매', len(T), '건  승률', round((T.ret>0).mean()*100,1), '평균', round(T.ret.mean(),2), '중앙', round(T.ret.median(),2), '최악', round(T.ret.min(),1), '최고', round(T.ret.max(),1))
print(T.assign(y=T['in'].dt.year).groupby('y').ret.agg(['size','mean',lambda s:(s>0).mean()*100,'sum']).round(1))
print(T.tail(6).to_string(index=False))
# 같은 날 수만큼 무작위로 10일 보유했을 때 대비
print('무작위 진입 대비 백분위(위험 시 보류):', quant.rand_pct(c, oos, len(trades), stats(ret,'x')['총수익']), '| 위험 무시:', quant.rand_pct(c, oos, len(trades2), stats(ret2,'x')['총수익']))
# 국면 일간 수익률 t검정(다음 날 수익률, 겹치지 않음)
r1 = (c.shift(-1)/c-1).reindex(oos)*100
print('\n다음 날 수익률 국면별 평균·t값(0 대비)')
for g in ['고변동 청산','상승 추세','하락 추세','횡보']:
    x = r1[rg==g].dropna(); print(g, len(x), round(x.mean(),3), 't', round(x.mean()/(x.std()/np.sqrt(len(x))),2), '표준편차', round(x.std(),2))
# 블록 부트스트랩: 횡보 피함 − 보유 연환산 차이
rng = np.random.default_rng(1); n = len(r); B = 20; diffs = {k: [] for k in ('위험 꺼진 날만','횡보 피함','상승 추세만','정밀검증 매매')}
series = {'위험 꺼진 날만':o1,'횡보 피함':o2,'상승 추세만':o3,'정밀검증 매매':ret}
for _ in range(2000):
    st = rng.integers(0, n-B, size=n//B); idx = np.concatenate([np.arange(a, a+B) for a in st])
    base = np.log1p(r.values[idx]).sum()
    for k, v in series.items(): diffs[k].append(np.log1p(v.values[idx]).sum() - base)
print('\n블록 부트스트랩(20일 블록 2,000회): 보유보다 나았던 비율')
for k, v in diffs.items(): print(' ', k, round(np.mean(np.array(v) > 0)*100, 1), '%')
