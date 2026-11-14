import pickle, numpy as np, pandas as pd, sys, warnings
warnings.filterwarnings('ignore'); sys.path.insert(0,'/home/claude/kospi-dashboard/pkg'); import quant
f = pickle.load(open('feat.pkl','rb')); c = f['c']; idx = c.index; s = pickle.load(open('s_up10.pkl','rb'))
oos = idx[idx.year >= 2018]; r = c.reindex(oos).pct_change().fillna(0)
def st(ret, pos, name, ntr):
    eq = (1+ret).cumprod(); tot = eq.iloc[-1]-1; mdd = (eq/eq.cummax()-1).min(); sh = ret.mean()/ret.std()*np.sqrt(250) if ret.std()>0 else float('nan')
    print(f'{name:<44} 총 {tot*100:+7.1f}% · 낙폭 {mdd*100:6.1f}% · 샤프 {sh:5.2f} · 보유 {pos.mean()*100:4.1f}% · 거래 {ntr}')
st(r, np.ones(len(r)), '코스피 보유', 1)
no = pd.Series(False, index=idx)
for nm, sig in (('상위10 과반 신호 → 다음 날 종가 매수, 10일 보유', pd.Series(s['s10'] >= 0.5, index=idx)), ('상위10 중 하나라도 → 10일 보유', pd.Series(s['s10'] > 0, index=idx)), ('상위100 중 20% 이상 → 10일 보유', pd.Series(s['s100'] >= 0.2, index=idx)), ('상위100 과반 → 10일 보유', pd.Series(s['s100'] >= 0.5, index=idx))):
    ret, tr, pos = quant.simulate(c, sig, no, oos); st(ret, pos, nm, len(tr))
    T = pd.DataFrame([(a, b, x*100, o) for a, b, x, o in tr], columns=['in','out','ret','open'])
    print('    승률', round((T.ret > 0).mean()*100, 1), '평균', round(T.ret.mean(), 2), '최악', round(T.ret.min(), 1), '| 연도별 합', T.assign(y=T['in'].dt.year).groupby('y').ret.sum().round(1).to_dict(), '| 무작위 대비 백분위', quant.rand_pct(c, oos, len(tr), (np.prod(1 + ret) - 1) * 100))
