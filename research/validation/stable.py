# 안정 종목의 특이점 조사(전 종목). 2018~2026 코스피 급락 22번마다
#  - 그 급락에서 같은 시장 보통 종목(중앙값) 대비 초과 수익(x), 덜 빠졌는지(beat)
#  - 고점일에 알 수 있던 특징(가격 위험·가치·실적·수급·보유·업종·과거 급락 성적)
# 을 종목×급락 한 줄로 만든다. 출력: stable/panel.parquet(csv.gz)
import os, glob
import numpy as np, pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(ROOT, 'raw'); OUT = os.path.join(ROOT, 'stable'); os.makedirs(OUT, exist_ok=True)
MK = ('KOSPI', 'KOSDAQ')
EXCL = '스팩|SPAC|리츠|ETN|ETF|KODEX|TIGER|기업인수목적|인프라|맥쿼리|선박|부동산투자'


def rd(p):
    f = os.path.join(RAW, p)
    if not os.path.exists(f):
        return None
    try:
        d = pd.read_csv(f, compression='gzip', index_col=0)
    except Exception:
        return None
    d.index = d.index.astype(str).str.zfill(6)
    return d


ix = pd.read_csv(os.path.join(RAW, 'index_daily.csv.gz'), dtype={'date': str}).sort_values('date')
days = pd.Index(ix['date'].astype(str))
ixs = {m: ix.set_index('date')['kospi' if m == 'KOSPI' else 'kosdaq'].dropna() for m in MK}
ep = pd.read_csv(os.path.join(ROOT, 'episodes.csv'), dtype={'peak': str, 'trough': str}).sort_values('peak').reset_index(drop=True)


def shift(d, n):
    i = days.searchsorted(d) + n
    return days[min(max(i, 0), len(days) - 1)]


def nxt(d):
    i = days.searchsorted(d, side='right')
    return days[i] if i < len(days) else None


# ---- 주간 행렬(시장별): 수익률, 거래대금, 이름
W, V, NAME = {}, {}, {}
for m in MK:
    R, A = {}, {}
    for f in sorted(glob.glob(os.path.join(RAW, 'weekly', f'W_{m}_*.csv.gz'))):
        d = os.path.basename(f)[-15:-7]
        df = rd(os.path.relpath(f, RAW))
        if df is None or df.empty:
            continue
        R[d] = df['등락률'].astype(float) / 100
        A[d] = df['거래대금'].astype(float)
        NAME.update(df['종목명'].to_dict())
    W[m] = pd.DataFrame(R); V[m] = pd.DataFrame(A)
    print(m, W[m].shape)


def idx_week(m, cols):
    s = ixs[m]; out = []; prev = None
    for d in cols:
        i = s.index.searchsorted(d, side='right') - 1
        v = s.iloc[i]
        out.append(np.nan if prev is None else v / prev - 1); prev = v
    return pd.Series(out, index=cols)


# ---- DART 영업이익(연도별, 연결 우선)
dart = pd.read_csv(os.path.join(RAW, 'dart_op.csv.gz'), dtype=str)
dart['_p'] = (dart['fs_div'] != 'CFS').astype(int)
dart = dart.sort_values('_p').drop_duplicates(['stock_code', 'bsns_year'])
rows = []
for _, r in dart.iterrows():
    y = int(r['bsns_year'])
    for k, off in (('thstrm_amount', 0), ('frmtrm_amount', 1), ('bfefrmtrm_amount', 2)):
        try:
            rows.append((r['stock_code'].zfill(6), y - off, float(str(r[k]).replace(',', ''))))
        except Exception:
            pass
OP = pd.DataFrame(rows, columns=['code', 'year', 'op']).dropna().drop_duplicates(['code', 'year']).pivot_table(index='code', columns='year', values='op', aggfunc='first')


def op_feats(codes, T):
    y = int(T[:4]) - 1 - (1 if T[4:] < '0401' else 0)
    yrs = [yy for yy in range(y - 3, y + 1)]
    if not all(yy in OP.columns for yy in yrs):
        return None
    sub = OP.reindex(codes)[yrs]
    cnt = (sub > 0).sum(axis=1).astype(float); cnt[sub.isna().any(axis=1)] = np.nan
    gr = (sub[yrs[-1]] > sub[yrs[0]]).astype(float); gr[sub[[yrs[0], yrs[-1]]].isna().any(axis=1)] = np.nan
    return pd.DataFrame({'profit_years': cnt, 'op_up3y': gr, 'op_pos_last': (sub[yrs[-1]] > 0).astype(float).where(sub[yrs[-1]].notna())})


# ---- 급락 기록 누적(그 고점 이전 급락만 씀)
hist = {}   # code -> list of (peak, x, beat)
panel = []
for i, e in ep.iterrows():
    T, TR = str(e['peak']), str(e['trough']); a = nxt(T)
    for m in MK:
        cols = [c for c in W[m].columns if c <= T]
        if len(cols) < 60:
            continue
        P = rd(f'period/P_{m}_{a}_{TR}.csv.gz')
        if P is None:
            # 2015~2016 구간: 주간 누적으로 근사, 기록용으로만
            cw = [c for c in W[m].columns if T < c <= TR]
            if not cw:
                continue
            cr = (1 + W[m][cw].fillna(0)).prod(axis=1) - 1
            cr = cr[W[m][cw].notna().sum(axis=1) >= len(cw) * 0.8]
            med = cr.median()
            for c, v in cr.items():
                hist.setdefault(c, []).append((T, v - med, v > med))
            continue
        ret = P['등락률'].astype(float) / 100
        names = P['종목명']
        CAP = rd(f'snap/CAP_{m}_{T}.csv.gz'); FU = rd(f'snap/FUND_{m}_{T}.csv.gz')
        FR = rd(f'snap/FR_{m}_{T}.csv.gz'); FR1 = rd(f'snap/FR_{m}_{shift(T, -250)}.csv.gz')
        SH = rd(f'snap/SHORT_{m}_{T}.csv.gz'); SC = rd(f'snap/SECT_{m}_{T}.csv.gz')
        fl = {}
        for code, a_ in (('INST', shift(T, -250)), ('FRGN', shift(T, -250))):
            fl[code + '_1y'] = rd(f'flow/F_{m}_{code}_{a_}_{T}.csv.gz')
        fl['INST_3m'] = rd(f'flow/F_{m}_INST_{shift(T, -63)}_{T}.csv.gz')
        U = pd.DataFrame(index=CAP.index)
        U['name'] = names.reindex(U.index).fillna(pd.Series(NAME)).reindex(U.index)
        U['mcap'] = CAP['시가총액'].astype(float)
        U = U[(U['mcap'] >= 3e10) & ~U['name'].astype(str).str.contains(EXCL, na=False) & ~U['name'].astype(str).str.contains(r'우$|우B$|우C$|\d우', na=False)]
        w = W[m].loc[U.index.intersection(W[m].index), cols]
        n104 = w[cols[-104:]].notna().sum(axis=1)
        U = U.loc[n104[n104 >= 50].index]
        w = W[m].loc[U.index, cols]
        c104, c52, c13 = cols[-104:], cols[-52:], cols[-13:]
        iw = idx_week(m, c104)
        X = iw.values; X1 = X[52:] if len(X) > 52 else X
        def beta(Y, Xv):
            ok = ~np.isnan(Y) & ~np.isnan(Xv)
            if ok.sum() < 30 or np.var(Xv[ok]) == 0:
                return np.nan
            return np.cov(Y[ok], Xv[ok])[0, 1] / np.var(Xv[ok], ddof=1)
        Wv = w[c104].values
        U['beta2y'] = [beta(Wv[j], X) for j in range(len(U))]
        dn = X < 0
        U['down_beta'] = [beta(Wv[j][dn], X[dn]) for j in range(len(U))]
        U['vol1y'] = w[c52].std(axis=1) * np.sqrt(52)
        g = (1 + w[c104].fillna(0)).cumprod(axis=1)
        U['mdd2y'] = (g / g.cummax(axis=1) - 1).min(axis=1)
        U['ret2y'] = g.iloc[:, -1] - 1
        U['ret1y'] = (1 + w[c52].fillna(0)).prod(axis=1) - 1
        U['ret3m'] = (1 + w[c13].fillna(0)).prod(axis=1) - 1
        g52 = (1 + w[c52].fillna(0)).cumprod(axis=1)
        U['off_high'] = g52.iloc[:, -1] / g52.max(axis=1) - 1
        U['up_week'] = (w[c52] > 0).sum(axis=1) / w[c52].notna().sum(axis=1)
        U['max_week'] = w[c52].max(axis=1)
        U['turnover'] = V[m].loc[U.index, c52].sum(axis=1) / U['mcap']
        U['log_mcap'] = np.log10(U['mcap'])
        if FU is not None:
            U['div'] = FU['DIV'].astype(float).reindex(U.index)
            U['pbr'] = FU['PBR'].astype(float).replace(0, np.nan).reindex(U.index)
            per = FU['PER'].astype(float).reindex(U.index)
            U['earn_yield'] = np.where(per > 0, 1 / per, 0.0)
            U['eps_pos'] = (FU['EPS'].astype(float).reindex(U.index) > 0).astype(float)
        U['frgn_ratio'] = FR['지분율'].astype(float).reindex(U.index) if FR is not None else np.nan
        U['frgn_chg1y'] = U['frgn_ratio'] - (FR1['지분율'].astype(float).reindex(U.index) if FR1 is not None else np.nan)
        U['short'] = SH['비중'].astype(float).reindex(U.index) if (SH is not None and '비중' in SH) else np.nan
        U['sector'] = SC['업종명'].reindex(U.index) if SC is not None else ''
        for k, df in fl.items():
            U[k.lower()] = (df['순매수거래대금'].astype(float).reindex(U.index) / U['mcap']) if (df is not None and '순매수거래대금' in df) else np.nan
        of = op_feats(U.index, T)
        if of is not None:
            U = U.join(of)
        # 과거 급락 성적
        U['n_prior'] = [len(hist.get(c, [])) for c in U.index]
        U['prior_rate'] = [np.mean([b for _, _, b in hist[c]]) if hist.get(c) else np.nan for c in U.index]
        U['prior_x'] = [np.mean([x for _, x, _ in hist[c]]) if hist.get(c) else np.nan for c in U.index]
        U['prior_worst'] = [np.min([x for _, x, _ in hist[c]]) if hist.get(c) else np.nan for c in U.index]
        # 결과
        U['ret'] = ret.reindex(U.index)
        U = U[U['ret'].notna()]
        med = U['ret'].median()
        U['x'] = U['ret'] - med; U['beat'] = (U['x'] > 0).astype(int)
        for lab, h in (('f63', 63), ('f126', 126), ('f252', 252)):
            j = days.searchsorted(T) + h
            if j < len(days):
                Pf = rd(f'period/P_{m}_{a}_{days[j]}.csv.gz')
                if Pf is not None:
                    rf = Pf['등락률'].astype(float).reindex(U.index) / 100
                    U['x_' + lab] = rf - rf.median()
        U['market'] = m; U['peak'] = T; U['trough'] = TR; U['ep_no'] = i
        U['idx_dd'] = ixs[m].get(TR, np.nan) / ixs[m].get(T, np.nan) - 1
        U['med_ret'] = med
        panel.append(U)
        for c in U.index:
            hist.setdefault(c, []).append((T, float(U.at[c, 'x']), bool(U.at[c, 'beat'])))
    print(T, TR, sum(len(p) for p in panel))

PN = pd.concat(panel).rename_axis('code').reset_index()
PN['name'] = PN['code'].map(NAME).fillna(PN['name'])
PN.to_csv(os.path.join(OUT, 'panel.csv.gz'), index=False, compression='gzip')
print(PN.shape); print(PN.groupby('peak').size().to_string())
