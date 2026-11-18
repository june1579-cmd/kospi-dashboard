# 관찰 종목: 2026-11-16 기준 유동성 있는 종목 중 '변동성 낮음·베타 낮음·과거 급락 성적 좋음' 순위(같은 비중 백분위 평균)
import os, glob, numpy as np, pandas as pd
ROOT = os.path.dirname(os.path.abspath(__file__)); RAW = os.path.join(ROOT, 'raw'); OUT = os.path.join(ROOT, 'stable')
END = '20261116'
EXCL = '스팩|SPAC|리츠|ETN|ETF|KODEX|TIGER|기업인수목적|인프라|맥쿼리|선박|부동산투자'
def rd(p):
    f = os.path.join(RAW, p)
    if not os.path.exists(f): return None
    d = pd.read_csv(f, compression='gzip', index_col=0); d.index = d.index.astype(str).str.zfill(6); return d
ix = pd.read_csv(os.path.join(RAW, 'index_daily.csv.gz'), dtype={'date': str}).sort_values('date').set_index('date')
P = pd.read_csv(os.path.join(OUT, 'panel.csv.gz'), dtype={'code': str, 'peak': str}); P['code'] = P['code'].str.zfill(6)
rec = P.groupby('code').agg(n_rec=('x', 'size'), rec_rate=('beat', 'mean'), rec_x=('x', 'median'), rec_worst=('x', 'min'))
recent = P[P.peak >= '20250101'].groupby('code').agg(n_recent=('x', 'size'), beat_recent=('beat', 'sum'))
last2 = P[P.peak.isin(['20260622', '20260923'])].pivot_table(index='code', columns='peak', values='ret')
last2.columns = ['ret_0622', 'ret_0923']
snapd = END if rd(f'snap/CAP_KOSPI_{END}.csv.gz') is not None else '20260923'
out = []
for m in ('KOSPI', 'KOSDAQ'):
    R, A, N = {}, {}, {}
    for f in sorted(glob.glob(os.path.join(RAW, 'weekly', f'W_{m}_*.csv.gz')))[-110:]:
        d = rd(os.path.relpath(f, RAW)); k = os.path.basename(f)[-15:-7]
        R[k] = d['등락률'].astype(float) / 100; A[k] = d['거래대금'].astype(float); N.update(d['종목명'].to_dict())
    W = pd.DataFrame(R); V = pd.DataFrame(A); cols = list(W.columns)
    s = ix[m.lower()]; iv = [s.iloc[s.index.searchsorted(c, side='right') - 1] for c in cols]
    iw = pd.Series(iv, index=cols).pct_change()
    CAP = rd(f'snap/CAP_{m}_{snapd}.csv.gz'); FU = rd(f'snap/FUND_{m}_{snapd}.csv.gz'); SC = rd(f'snap/SECT_{m}_{snapd}.csv.gz')
    SH = rd(f'snap/SHORT_{m}_{snapd}.csv.gz'); FR = rd(f'snap/FR_{m}_{snapd}.csv.gz')
    U = pd.DataFrame(index=CAP.index)
    U['name'] = pd.Series(N).reindex(U.index); U['mcap'] = CAP['시가총액'].astype(float)
    U = U[U.name.notna() & (U.mcap >= 1e11) & ~U.name.astype(str).str.contains(EXCL) & ~U.name.astype(str).str.contains(r'우$|우B$|우C$|\d우')]
    w = W.reindex(U.index); c104, c52, c13 = cols[-104:], cols[-52:], cols[-13:]
    U = U[(w[c104].notna().sum(axis=1) >= 50) & ((w[c13] == 0).sum(axis=1) < 4)]; w = W.reindex(U.index)
    X = iw[c104].values
    def beta(Y):
        ok = ~np.isnan(Y) & ~np.isnan(X)
        return np.cov(Y[ok], X[ok])[0, 1] / np.var(X[ok], ddof=1) if ok.sum() >= 30 else np.nan
    U['beta2y'] = [beta(w.loc[c, c104].values.astype(float)) for c in U.index]
    U['vol1y'] = w[c52].std(axis=1) * np.sqrt(52)
    U['turnover'] = V.reindex(U.index)[c52].sum(axis=1) / U.mcap
    g = (1 + w[c104].fillna(0)).cumprod(axis=1); U['mdd2y'] = (g / g.cummax(axis=1) - 1).min(axis=1)
    U['ret1y'] = (1 + w[c52].fillna(0)).prod(axis=1) - 1
    ytd = [c for c in cols if c >= '20260101']; U['ret_ytd'] = (1 + w[ytd].fillna(0)).prod(axis=1) - 1
    U['pbr'] = FU['PBR'].astype(float).replace(0, np.nan).reindex(U.index) if FU is not None else np.nan
    U['div'] = FU['DIV'].astype(float).reindex(U.index) if FU is not None else np.nan
    U['sector'] = SC['업종명'].reindex(U.index) if SC is not None else ''
    U['short'] = SH['비중'].astype(float).reindex(U.index) if SH is not None and '비중' in SH else np.nan
    U['frgn_ratio'] = FR['지분율'].astype(float).reindex(U.index) if FR is not None else np.nan
    U['market'] = '코스피' if m == 'KOSPI' else '코스닥'
    out.append(U)
U = pd.concat(out)
U = U[U.turnover >= U.turnover.quantile(0.2)]
U = U.join(rec).join(recent).join(last2)
U = U[U.n_rec >= 10]
U['s_vol'] = (-U.vol1y).rank(pct=True) * 100; U['s_beta'] = (-U.beta2y).rank(pct=True) * 100; U['s_rec'] = U.rec_rate.rank(pct=True) * 100
U['score'] = (U.s_vol + U.s_beta + U.s_rec) / 3
# 4년 흑자(가능하면)
d = os.path.join(RAW, 'dart_op.csv.gz')
if os.path.exists(d):
    dt = pd.read_csv(d, dtype=str); dt['_p'] = (dt.fs_div != 'CFS').astype(int); dt = dt.sort_values('_p').drop_duplicates(['stock_code', 'bsns_year'])
    r = []
    for _, x in dt.iterrows():
        for k, off in (('thstrm_amount', 0), ('frmtrm_amount', 1), ('bfefrmtrm_amount', 2)):
            try: r.append((x.stock_code.zfill(6), int(x.bsns_year) - off, float(str(x[k]).replace(',', ''))))
            except Exception: pass
    OP = pd.DataFrame(r, columns=['code', 'year', 'op']).drop_duplicates(['code', 'year']).pivot_table(index='code', columns='year', values='op')
    yrs = [2022, 2023, 2024, 2025]
    sub = OP.reindex(U.index)[yrs]; cnt = (sub > 0).sum(axis=1).astype(float); cnt[sub.isna().any(axis=1)] = np.nan
    U['profit_years'] = cnt
U = U.sort_values('score', ascending=False); U['rank'] = range(1, len(U) + 1)
U.index.name = 'code'
U.to_csv(os.path.join(OUT, 'watch_all.csv'))
print('기준 단면', snapd, '대상', len(U))
cols = ['rank', 'name', 'market', 'sector', 'score', 'vol1y', 'beta2y', 'rec_rate', 'n_rec', 'rec_x', 'rec_worst', 'beat_recent', 'n_recent', 'ret_0622', 'ret_0923', 'pbr', 'div', 'profit_years', 'ret_ytd', 'mcap']
pd.set_option('display.width', 260)
print(U[[c for c in cols if c in U]].head(50).round(3).to_string())
