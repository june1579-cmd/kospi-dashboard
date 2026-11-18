import os, json, numpy as np, pandas as pd
ROOT = os.path.dirname(os.path.abspath(__file__)); OUT = os.path.join(ROOT, 'stable')
P = pd.read_csv(os.path.join(OUT, 'panel.csv.gz'), dtype={'code': str, 'peak': str})
P['code'] = P['code'].str.zfill(6)
P['oos'] = P['peak'] < '20250601'
P['inst_flow'] = P['inst_1y']; P['big_flow'] = P['inst_1y'].fillna(0) + P['frgn_1y'].fillna(0)
# 방향: +면 값이 클수록 덜 빠질 것으로 기대
F = {
 'beta2y': ('베타(2년)', -1, '가격 위험'), 'down_beta': ('하락 베타(지수 하락 주만)', -1, '가격 위험'),
 'vol1y': ('변동성(1년)', -1, '가격 위험'), 'mdd2y': ('최대 낙폭(2년)', +1, '가격 위험'),
 'max_week': ('1년 중 최대 주간 상승', -1, '가격 위험'), 'up_week': ('오른 주 비율(1년)', +1, '가격 위험'),
 'ret2y': ('2년 수익률', -1, '모멘텀'), 'ret1y': ('1년 수익률', -1, '모멘텀'), 'ret3m': ('3개월 수익률', -1, '모멘텀'),
 'off_high': ('52주 고점 대비', +1, '모멘텀'),
 'div': ('배당수익률', +1, '가치'), 'pbr': ('PBR', -1, '가치'), 'earn_yield': ('이익수익률(1/PER)', +1, '가치'), 'eps_pos': ('EPS 흑자', +1, '가치'),
 'profit_years': ('영업흑자 연수(4년)', +1, '실적'), 'op_up3y': ('영업이익 3년 전보다 증가', +1, '실적'),
 'log_mcap': ('시가총액(로그)', +1, '규모·거래'), 'turnover': ('회전율(1년 거래대금/시총)', -1, '규모·거래'),
 'frgn_ratio': ('외국인 보유율', +1, '보유'), 'frgn_chg1y': ('외국인 보유율 1년 변화', +1, '보유'),
 'short': ('공매도 잔고 비중', -1, '보유'),
 'inst_1y': ('기관 순매수 1년(시총 대비)', +1, '수급'), 'frgn_1y': ('외국인 순매수 1년(시총 대비)', +1, '수급'),
 'inst_3m': ('기관 순매수 3개월(시총 대비)', +1, '수급'), 'big_flow': ('외국인+기관 1년(시총 대비)', +1, '수급'),
 'prior_rate': ('과거 급락에서 덜 빠진 비율', +1, '과거 성적'), 'prior_x': ('과거 급락 평균 초과 수익', +1, '과거 성적'),
 'prior_worst': ('과거 급락 최악 초과 수익', +1, '과거 성적'),
}
eps = sorted(P['peak'].unique())


def auc(s, y):
    ok = s.notna() & y.notna(); s, y = s[ok], y[ok]
    n1 = (y == 1).sum(); n0 = (y == 0).sum()
    if n1 < 10 or n0 < 10: return np.nan
    r = s.rank(); return (r[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0)


rows = []
for f, (lab, sgn, cat) in F.items():
    for T in eps:
        d = P[P['peak'] == T]
        s = d[f] * sgn
        if s.notna().sum() < 200 or s.nunique() < 3: continue
        ok = s.notna()
        rho = s[ok].rank().corr(d.loc[ok, 'x'].rank())
        q = pd.qcut(s[ok].rank(method='first'), 5, labels=False)
        xq = d.loc[ok, 'x'].groupby(q).median()
        bq = d.loc[ok, 'beat'].groupby(q).mean()
        rows.append(dict(f=f, peak=T, rho=rho, auc=auc(s, d['beat']), q5=xq.iloc[-1], q1=xq.iloc[0], spread=xq.iloc[-1] - xq.iloc[0],
                         b5=bq.iloc[-1], b1=bq.iloc[0], oos=T < '20250601',
                         x252=(d.loc[ok, 'x_f252'].groupby(q).median().iloc[-1] - d.loc[ok, 'x_f252'].groupby(q).median().iloc[0]) if d['x_f252'].notna().sum() > 100 else np.nan))
R = pd.DataFrame(rows)
summ = []
for f, g in R.groupby('f'):
    lab, sgn, cat = F[f]
    o = g[g.oos]
    summ.append(dict(key=f, trait=lab, cat=cat, dir='높을수록 좋음 기대' if sgn > 0 else '낮을수록 좋음 기대',
                     n=len(g), rho=g.rho.median(), pos=int((g.rho > 0).sum()), rho_oos=o.rho.median(), pos_oos=int((o.rho > 0).sum()), n_oos=len(o),
                     auc=g.auc.median(), spread=g.spread.median() * 100, b5=g.b5.median() * 100, b1=g.b1.median() * 100,
                     spread_min=g.spread.min() * 100, x252=g.x252.median() * 100, n252=int(g.x252.notna().sum()), pos252=int((g.x252 > 0).sum())))
S = pd.DataFrame(summ).sort_values('rho', ascending=False)
pd.set_option('display.width', 250)
print(S.round(3).to_string(index=False))
R.to_csv(os.path.join(OUT, 'trait_by_ep.csv'), index=False); S.to_csv(os.path.join(OUT, 'trait_summary.csv'), index=False)
