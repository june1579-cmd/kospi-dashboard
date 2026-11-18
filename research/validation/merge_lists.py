# 안정 관찰 종목 1~100 + 현재 점수 순위 1~100 + 방어종목 1번 결과물 1~100 → 합친 명단(11/16 KRX 값으로 공통 지표)
import os, glob, json, numpy as np, pandas as pd
ROOT = os.path.dirname(os.path.abspath(__file__)); RAW = os.path.join(ROOT, 'raw'); OUT = os.path.join(ROOT, 'stable')
END = '20261116'
def rd(p):
    f = os.path.join(RAW, p)
    if not os.path.exists(f): return None
    d = pd.read_csv(f, compression='gzip', index_col=0); d.index = d.index.astype(str).str.zfill(6); return d

# 1) 세 명단
st = pd.DataFrame(json.load(open('/home/claude/gr/data4/st_watch.json')))[['code', 'rank', 'score']].rename(columns={'rank': 'st_rank', 'score': 'st_score'})
sc = pd.DataFrame(json.load(open('/home/claude/gr/data2/scores.json')))
sc['mix'] = (5 * sc['flow'].astype(float) + 5 * sc['chk'].astype(float) * 25) / 10
sc = sc.sort_values('mix', ascending=False, kind='stable').reset_index(drop=True); sc['sc_rank'] = range(1, len(sc) + 1)
scT = sc[sc.sc_rank <= 100][['code', 'sc_rank', 'mix', 'flow', 'chk', 'big7']].rename(columns={'mix': 'sc_mix', 'flow': 'sc_flow', 'chk': 'sc_chk', 'big7': 'sc_big7'})
r1 = pd.DataFrame(json.load(open('/home/claude/gr/data2/result1.json')))
r1T = r1[['code', 'rank', 'total', 's_def', 's_hold', 's_grow', 's_flow', 's_com', 'group']].rename(columns={'rank': 'd1_rank', 'total': 'd1_total', 's_def': 'd1_def', 's_hold': 'd1_hold', 's_grow': 'd1_grow', 's_flow': 'd1_flow', 's_com': 'd1_com', 'group': 'd1_group'})
for d in (st, scT, r1T): d['code'] = d['code'].astype(str).str.zfill(6)
M = st.merge(scT, on='code', how='outer').merge(r1T, on='code', how='outer')
M['in_st'] = M.st_rank.notna(); M['in_sc'] = M.sc_rank.notna(); M['in_d1'] = M.d1_rank.notna()
M['n_lists'] = M[['in_st', 'in_sc', 'in_d1']].sum(axis=1)
print('합친 종목', len(M), '· 겹침', M.n_lists.value_counts().to_dict())

# 2) 공통 지표(11/16, KRX 원자료로 같은 방식 계산)
P = pd.read_csv(os.path.join(OUT, 'panel.csv.gz'), dtype={'code': str, 'peak': str}); P['code'] = P.code.str.zfill(6)
rec = P.groupby('code').agg(n_rec=('x', 'size'), rec_rate=('beat', 'mean'))
last2 = P[P.peak.isin(['20260622', '20260923'])].pivot_table(index='code', columns='peak', values='ret'); last2.columns = ['ret_0622', 'ret_0923']
ix = pd.read_csv(os.path.join(RAW, 'index_daily.csv.gz'), dtype={'date': str}).sort_values('date').set_index('date')
rows = []
for m in ('KOSPI', 'KOSDAQ'):
    R, N = {}, {}
    for f in sorted(glob.glob(os.path.join(RAW, 'weekly', f'W_{m}_*.csv.gz')))[-110:]:
        d = rd(os.path.relpath(f, RAW)); R[os.path.basename(f)[-15:-7]] = d['등락률'].astype(float) / 100; N.update(d['종목명'].to_dict())
    W = pd.DataFrame(R); cols = list(W.columns); c104, c52 = cols[-104:], cols[-52:]
    s = ix[m.lower()]; iw = pd.Series([s.iloc[s.index.searchsorted(c, side='right') - 1] for c in cols], index=cols).pct_change(); X = iw[c104].values
    CAP = rd(f'snap/CAP_{m}_{END}.csv.gz'); FU = rd(f'snap/FUND_{m}_{END}.csv.gz'); SC = rd(f'snap/SECT_{m}_{END}.csv.gz'); SH = rd(f'snap/SHORT_{m}_{END}.csv.gz'); FR = rd(f'snap/FR_{m}_{END}.csv.gz')
    codes = [c for c in M.code if c in CAP.index]
    w = W.reindex(codes)
    for c in codes:
        Y = w.loc[c, c104].values.astype(float); ok = ~np.isnan(Y) & ~np.isnan(X)
        g = (1 + w.loc[c, c104].fillna(0)).cumprod()
        rows.append(dict(code=c, name=N.get(c) or (SC['종목명'].get(c) if SC is not None else None), market='코스피' if m == 'KOSPI' else '코스닥',
                         sector=SC['업종명'].get(c) if SC is not None else None, close=float(CAP['종가'].get(c)), mcap=float(CAP['시가총액'].get(c)) / 1e8,
                         vol1y=float(w.loc[c, c52].std() * np.sqrt(52) * 100) if w.loc[c, c52].notna().sum() >= 26 else np.nan,
                         beta2y=float(np.cov(Y[ok], X[ok])[0, 1] / np.var(X[ok], ddof=1)) if ok.sum() >= 30 else np.nan,
                         mdd2y=float((g / g.cummax() - 1).min() * 100), ret2y=float((g.iloc[-1] - 1) * 100) if w.loc[c, c104].notna().sum() >= 90 else np.nan,
                         ret1y=float(((1 + w.loc[c, c52].fillna(0)).prod() - 1) * 100),
                         ret_ytd=float(((1 + w.loc[c, [k for k in cols if k >= '20260101']].fillna(0)).prod() - 1) * 100),
                         pbr=float(FU['PBR'].get(c)) if FU is not None and FU['PBR'].get(c) else np.nan, per=float(FU['PER'].get(c)) if FU is not None and FU['PER'].get(c) else np.nan,
                         div=float(FU['DIV'].get(c)) if FU is not None and c in FU.index else np.nan,
                         frgn=float(FR['지분율'].get(c)) if FR is not None and c in FR.index else np.nan,
                         short=float(SH['비중'].get(c)) if SH is not None and c in SH.index and '비중' in SH else np.nan))
F = pd.DataFrame(rows)
M = M.merge(F, on='code', how='left').merge(rec, left_on='code', right_index=True, how='left').merge(last2, left_on='code', right_index=True, how='left')
M['rec_rate'] = M.rec_rate * 100; M['ret_0622'] = M.ret_0622 * 100; M['ret_0923'] = M.ret_0923 * 100
# 4년 흑자(2022~2025 영업이익)
dt = pd.read_csv(os.path.join(RAW, 'dart_op.csv.gz'), dtype=str); dt['_p'] = (dt.fs_div != 'CFS').astype(int); dt = dt.sort_values('_p').drop_duplicates(['stock_code', 'bsns_year'])
r = []
for _, x in dt.iterrows():
    for k, off in (('thstrm_amount', 0), ('frmtrm_amount', 1), ('bfefrmtrm_amount', 2)):
        try: r.append((x.stock_code.zfill(6), int(x.bsns_year) - off, float(str(x[k]).replace(',', ''))))
        except Exception: pass
OP = pd.DataFrame(r, columns=['code', 'year', 'op']).drop_duplicates(['code', 'year']).pivot_table(index='code', columns='year', values='op')
sub = OP.reindex(M.code)[[2022, 2023, 2024, 2025]]; cnt = (sub > 0).sum(axis=1).astype(float); cnt[sub.isna().any(axis=1)] = np.nan
M['profit_years'] = cnt.values; M['op2025'] = (sub[2025] / 1e8).round(0).values
miss = M[M.name.isna()]
print('11/16 단면에 없는 종목', len(miss), miss.code.tolist())
# 이름이 없으면 명단 원본 이름
nm = {**{r['code']: r['name'] for r in json.load(open('/home/claude/gr/data2/result1.json'))}, **{r['code']: r['name'] for r in json.load(open('/home/claude/gr/data2/scores.json'))}, **{r['code']: r['name'] for r in json.load(open('/home/claude/gr/data4/st_watch.json'))}}
M['name'] = M.name.fillna(M.code.map(nm))
M = M.sort_values(['n_lists', 'st_rank'], ascending=[False, True])
num = M.select_dtypes('number').columns
M[num] = M[num].round(3)
out = M.replace({np.nan: None}).to_dict('records')
for o in out:
    for k in ('in_st', 'in_sc', 'in_d1'): o[k] = bool(o[k])
json.dump(out, open('/home/claude/gr/merged_lists.json', 'w'), ensure_ascii=False, separators=(',', ':'))
print(len(out), os.path.getsize('/home/claude/gr/merged_lists.json'))
print(M[['code', 'name', 'n_lists', 'st_rank', 'sc_rank', 'd1_rank', 'vol1y', 'beta2y', 'rec_rate', 'pbr', 'div', 'profit_years', 'ret_ytd']].head(25).to_string(index=False))
print(M[['vol1y','beta2y','rec_rate','pbr','div','frgn','short','ret_ytd','ret2y','profit_years','close']].notna().sum().to_dict())
