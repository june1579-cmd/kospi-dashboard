# 방어종목 1번 결과물 점수(방어30·버틴 실적20·성장20·수급15·공통점15)를
# 과거 급락 구간 고점일마다 "그 날까지의 자료"로만 다시 매겨, 그 뒤 급락 수익률과 3·6·12개월 수익률로 검증한다.
# 입력: raw/ (collect.py 결과), episodes.csv. 출력: result/*.json, result/summary.json
import os, json, glob, math, statistics as st
import pandas as pd
import numpy as np

ROOT = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(ROOT, 'raw')
OUT = os.path.join(ROOT, 'result')
os.makedirs(OUT, exist_ok=True)
MK = ('KOSPI', 'KOSDAQ')


def rd(path, idx=True):
    full = os.path.join(RAW, path)
    if not os.path.exists(full):
        return None
    try:
        df = pd.read_csv(full, compression='gzip', index_col=0 if idx else None, dtype={0: str} if idx else None)
    except Exception:
        return None
    if idx:
        df.index = df.index.astype(str).str.zfill(6)
    return df


ix = pd.read_csv(os.path.join(RAW, 'index_daily.csv.gz'), dtype={'date': str}, compression='gzip')
ix['date'] = ix['date'].astype(str)
ix = ix.sort_values('date')
days = pd.Index(ix['date'])
ep = pd.read_csv(os.path.join(ROOT, 'episodes.csv'), dtype={'peak': str, 'trough': str})

# ---------------- 주간 등락률 → 종목×주 수익률 행렬
wfiles = {}
for m in MK:
    fs = sorted(glob.glob(os.path.join(RAW, 'weekly', f'W_{m}_*.csv.gz')))
    wfiles[m] = [(os.path.basename(f)[-15:-7], f) for f in fs]


def weekly_matrix(m, upto):
    """고점일 upto 이전(주 마지막 거래일 <= upto)의 주간 등락률(소수). 행=종목, 열=주 마지막일."""
    cols = {}
    names = {}
    for d, f in wfiles[m]:
        if d > upto:
            break
        df = rd(os.path.relpath(f, RAW))
        if df is None or df.empty or '등락률' not in df.columns:
            continue
        cols[d] = df['등락률'].astype(float) / 100.0
        if '종목명' in df.columns:
            names.update(df['종목명'].to_dict())
    if not cols:
        return pd.DataFrame(), names
    return pd.DataFrame(cols), names


def idx_weekly(m, wk_dates):
    """같은 주 경계로 지수 수익률. 주의 마지막일 종가 / 직전 주 마지막일 종가 - 1."""
    s = ix.set_index('date')['kospi' if m == 'KOSPI' else 'kosdaq'].dropna()
    out = []
    prev = None
    for d in wk_dates:
        v = s.get(d)
        if v is None:
            # 주 마지막일이 지수 자료에 없으면 그 이전 가장 가까운 날
            i = s.index.searchsorted(d, side='right') - 1
            v = s.iloc[i] if i >= 0 else np.nan
        out.append(np.nan if prev is None else v / prev - 1)
        prev = v
    return pd.Series(out, index=wk_dates)


def cum(w):
    return (1 + w.fillna(0)).prod(axis=1) - 1


def pct_rank(s, hi=True):
    """백분위 0~100. hi=True 면 클수록 100."""
    r = s.rank(pct=True, method='average') * 100
    r = r.clip(0, 100)
    return r if hi else 100 - r


def shift(d, n):
    i = days.searchsorted(d) + n
    return days[min(max(i, 0), len(days) - 1)]


def period_ret(m, a, b):
    df = rd(f'period/P_{m}_{a}_{b}.csv.gz')
    if df is None or df.empty:
        return None
    return df['등락률'].astype(float) / 100.0


def nxt(d):
    i = days.searchsorted(d, side='right')
    return days[i] if i < len(days) else None


# ---------------- DART 4년 흑자(있을 때만)
dart = rd('dart_op.csv.gz', idx=False)
profit_years = None
if dart is not None and not dart.empty:
    dart['stock_code'] = dart['stock_code'].astype(str).str.zfill(6)
    # 회사·보고서 연도마다 연결(CFS)이 있으면 연결, 없으면 별도(OFS)
    dart['_p'] = (dart['fs_div'] != 'CFS').astype(int)
    dart = dart.sort_values('_p').drop_duplicates(['stock_code', 'bsns_year'])
    def amt(x):
        try:
            return float(str(x).replace(',', ''))
        except Exception:
            return np.nan
    rows = []
    for _, r in dart.iterrows():
        y = int(r['bsns_year'])
        for k, off in (('thstrm_amount', 0), ('frmtrm_amount', 1), ('bfefrmtrm_amount', 2)):
            rows.append((r['stock_code'], y - off, amt(r[k])))
    po = pd.DataFrame(rows, columns=['code', 'year', 'op']).dropna().drop_duplicates(['code', 'year'])
    profit_years = po.pivot_table(index='code', columns='year', values='op', aggfunc='first')


def four_year_profit(codes, peak):
    """고점일 기준 직전 4개 사업연도(보고서가 나온 해 기준: 고점 연도-1 까지) 영업이익 흑자 수."""
    if profit_years is None:
        return None
    y = int(peak[:4]) - 1
    if peak[4:] < '0401':   # 3월 말 이전엔 전년 사업보고서가 아직 없음
        y -= 1
    yrs = [yy for yy in range(y - 3, y + 1) if yy in profit_years.columns]
    if len(yrs) < 4:
        return None
    sub = profit_years.reindex(codes)[yrs]
    cnt = (sub > 0).sum(axis=1)
    cnt[sub.isna().any(axis=1)] = np.nan
    return cnt


# ---------------- 검증 본체
results = []
ALLCODES = set()
prior_lifts = []      # 이전 급락들에서 얻은 업종 lift (고점일 시점엔 그 이전 것만 사용)
prior_crash = {}      # (m) -> {code: [excess list]} 이전 급락 초과수익 기록
ep = ep.sort_values('peak').reset_index(drop=True)

for i, e in ep.iterrows():
    T, TR = str(e['peak']), str(e['trough'])
    a = nxt(T)
    if T < '20180101' or a is None:
        # 2018 이전 구간은 "버틴 실적" 이력용으로만 쓴다(주간 자료로 급락 수익률 근사)
        for m in MK:
            W, _ = weekly_matrix(m, TR)
            if W.empty:
                continue
            cols = [c for c in W.columns if c > T and c <= TR]
            if not cols:
                continue
            cr = cum(W[cols])
            med = cr.median()
            prior_crash.setdefault(m, {})
            for c, v in cr.items():
                prior_crash[m].setdefault(c, []).append(v - med)
        continue
    per_m = []
    for m in MK:
        W, names = weekly_matrix(m, T)
        if W.empty or W.shape[1] < 60:
            continue
        wk = list(W.columns)
        iw = idx_weekly(m, wk)
        last2y = wk[-104:] if len(wk) >= 104 else wk
        y2a, y2b = last2y[:len(last2y) // 2], last2y[len(last2y) // 2:]
        f = pd.DataFrame(index=W.index)
        f['ret2y'] = cum(W[last2y])
        f['ret_y1'] = cum(W[y2a])
        f['ret_y2'] = cum(W[y2b])
        f['weeks'] = W[last2y].notna().sum(axis=1)
        # 베타(2년 주간)
        X = iw[last2y].values.astype(float)
        beta = []
        for c in W.index:
            Y = W.loc[c, last2y].values.astype(float)
            ok = ~np.isnan(X) & ~np.isnan(Y)
            if ok.sum() < 40 or np.var(X[ok]) == 0:
                beta.append(np.nan)
            else:
                beta.append(np.cov(Y[ok], X[ok])[0, 1] / np.var(X[ok], ddof=1))
        f['beta'] = beta
        # 최대낙폭(2년 주간 누적)
        g = (1 + W[last2y].fillna(0)).cumprod(axis=1)
        f['mdd'] = (g / g.cummax(axis=1) - 1).min(axis=1)
        # 가치·배당·외국인·공매도·업종·시총
        FU = rd(f'snap/FUND_{m}_{T}.csv.gz'); CAP = rd(f'snap/CAP_{m}_{T}.csv.gz')
        FR = rd(f'snap/FR_{m}_{T}.csv.gz'); FR1 = rd(f'snap/FR_{m}_{shift(T, -250)}.csv.gz')
        SH = rd(f'snap/SHORT_{m}_{T}.csv.gz'); SC = rd(f'snap/SECT_{m}_{T}.csv.gz')
        f['pbr'] = FU['PBR'].astype(float).replace(0, np.nan) if FU is not None and 'PBR' in FU else np.nan
        f['div'] = FU['DIV'].astype(float) if FU is not None and 'DIV' in FU else np.nan
        f['mcap'] = CAP['시가총액'].astype(float) if CAP is not None and '시가총액' in CAP else np.nan
        f['frgn_ratio'] = FR['지분율'].astype(float) if FR is not None and '지분율' in FR else np.nan
        f['frgn_ratio_chg'] = f['frgn_ratio'] - (FR1['지분율'].astype(float) if FR1 is not None and '지분율' in FR1 else np.nan)
        if SH is not None and '비중' in SH.columns:
            f['short'] = SH['비중'].astype(float)
        elif SH is not None and '공매도잔고' in SH.columns and CAP is not None:
            f['short'] = SH['공매도잔고'].astype(float) / CAP['시가총액'].astype(float) * 100
        else:
            f['short'] = np.nan
        f['sector'] = SC['업종명'] if SC is not None and '업종명' in SC else ''
        f['name'] = SC['종목명'] if SC is not None and '종목명' in SC else pd.Series(names)
        # 수급(고점일 이전 1년·3개월 순매수 / 시총)
        t1y, t3m = shift(T, -250), shift(T, -63)
        def flow(code, a_, b_):
            df = rd(f'flow/F_{m}_{code}_{a_}_{b_}.csv.gz')
            if df is None or '순매수거래대금' not in df.columns:
                return pd.Series(np.nan, index=f.index)
            return df['순매수거래대금'].astype(float).reindex(f.index)
        f['inst_1y'] = flow('INST', t1y, T) / f['mcap']
        f['frgn_1y'] = flow('FRGN', t1y, T) / f['mcap']
        f['inst_3m'] = flow('INST', t3m, T) / f['mcap']
        # 버틴 실적(이전 급락들의 초과수익)
        pc_ = prior_crash.get(m, {})
        f['beats'] = [sum(1 for v in pc_.get(c, []) if v > 0) for c in f.index]
        f['n_prior'] = [len(pc_.get(c, [])) for c in f.index]
        f['excess_avg'] = [np.mean(pc_[c]) if pc_.get(c) else np.nan for c in f.index]
        f['market'] = m
        # 성장 조건: 2년 +30%, 두 해 모두 플러스, 2년 자료 있음, 시총 있음
        f = f[(f['weeks'] >= 90) & (f['ret2y'] >= 0.30) & (f['ret_y1'] > 0) & (f['ret_y2'] > 0) & f['mcap'].notna()]
        per_m.append(f)
    if not per_m:
        continue
    U = pd.concat(per_m)
    U = U[~U['name'].astype(str).str.contains('스팩|SPAC|우$|우B$|리츠|ETN|ETF|KODEX|TIGER', regex=True, na=False)]
    if len(U) < 30:
        continue
    ALLCODES.update(U.index)
    # 4년 흑자
    py = four_year_profit(U.index, T)
    U['profit_years'] = py if py is not None else np.nan
    # ---- 점수(원 방식과 같은 가중·같은 백분위)
    P = {}
    P['beta'] = pct_rank(U['beta'].fillna(U['beta'].median()), hi=False)
    P['div'] = pct_rank(U['div'].fillna(0))
    P['pbr'] = pct_rank(U['pbr'].fillna(99), hi=False)
    if py is not None:
        prof = U['profit_years'].apply(lambda v: 100 if v == 4 else (0 if np.isnan(v) else v * 25 * 0.6))
        s_def = (P['beta'] + P['div'] + P['pbr'] + prof) / 4
    else:
        s_def = (P['beta'] + P['div'] + P['pbr']) / 3
    has_hist = U['n_prior'].max() > 0
    if has_hist:
        s_hold = (pct_rank(U['beats']) + pct_rank(U['excess_avg'].fillna(U['excess_avg'].median())) + pct_rank(U['mdd'])) / 3
    else:
        s_hold = pct_rank(U['mdd'])
    s_grow = (pct_rank(U['ret2y']) + pct_rank(U['ret_y1']) + pct_rank(U['ret_y2'])) / 3
    s_flow = (pct_rank(U['inst_3m'].fillna(0)) * 2 + pct_rank((U['inst_1y'].fillna(0) + U['frgn_1y'].fillna(0))) + pct_rank(U['frgn_ratio_chg'].fillna(0))) / 4
    # 공매도: 코스피만 백분위(낮을수록 좋음), 코스닥 50
    sh = pd.Series(50.0, index=U.index)
    k = (U['market'] == 'KOSPI') & U['short'].notna()
    if k.sum() > 10:
        sh[k] = pct_rank(U.loc[k, 'short'], hi=False)
    # 업종 lift: 이전 급락에서 상위 1/4 버틴 종목 중 업종 비중 / 전체 비중 (3배 cap)
    lift = pd.Series(50.0, index=U.index)
    if prior_lifts:
        L = {}
        for d in prior_lifts:
            for s_, v in d.items():
                L.setdefault(s_, []).append(v)
        L = {s_: np.mean(v) for s_, v in L.items()}
        lift = U['sector'].map(lambda s_: min(100.0, L.get(s_, 1.0) / 3 * 100))
    s_com = (pct_rank(U['frgn_ratio'].fillna(0)) + sh + lift) / 3
    U['s_def'], U['s_hold'], U['s_grow'], U['s_flow'], U['s_com'] = s_def, s_hold, s_grow, s_flow, s_com
    U['total'] = 0.30 * s_def + 0.20 * s_hold + 0.20 * s_grow + 0.15 * s_flow + 0.15 * s_com
    U = U.sort_values('total', ascending=False)
    U['rank'] = range(1, len(U) + 1)
    # ---- 결과: 급락(고점 다음날~저점)과 3·6·12개월
    hz = {'crash': TR}
    for h, lab in ((63, 'f63'), (126, 'f126'), (252, 'f252')):
        j = days.searchsorted(T) + h
        if j < len(days):          # 자료 끝(20261116)을 넘는 기간은 뺀다(잘린 기간을 12개월로 셈하지 않음)
            hz[lab] = days[j]
    rets = {}
    mkt_med = {}
    for lab, b in hz.items():
        parts = []
        for m in MK:
            r = period_ret(m, a, b)
            if r is None:
                continue
            parts.append(r)
            mkt_med[(lab, m)] = float(r.median())
        if parts:
            rets[lab] = pd.concat(parts)
    for lab, r in rets.items():
        U[lab] = r.reindex(U.index)
        U['x_' + lab] = U[lab] - U['market'].map(lambda m: mkt_med.get((lab, m), np.nan))
    # 이번 급락 결과를 다음 고점일의 "버틴 실적"·업종 lift 에 추가(이후 구간에서만 사용)
    if 'crash' in rets:
        for m in MK:
            r = period_ret(m, a, TR)
            if r is None:
                continue
            med = r.median()
            prior_crash.setdefault(m, {})
            for c, v in r.items():
                prior_crash[m].setdefault(c, []).append(v - med)
        top = U[U['x_crash'] >= U['x_crash'].quantile(0.75)]
        base = U['sector'].value_counts(normalize=True)
        tp = top['sector'].value_counts(normalize=True)
        prior_lifts.append({s_: float(tp.get(s_, 0) / base[s_]) for s_ in base.index if base[s_] > 0})

    def grp(sel):
        d = {}
        for lab in rets:
            v = U.loc[sel, 'x_' + lab].dropna()
            d[lab] = {'n': int(len(v)), 'median_excess': round(float(v.median()) * 100, 2) if len(v) else None,
                      'win_rate': round(float((v > 0).mean()) * 100, 1) if len(v) else None,
                      'median_ret': round(float(U.loc[sel, lab].dropna().median()) * 100, 2) if len(v) else None}
        return d
    n = len(U)
    summ = {
        'peak': T, 'trough': TR, 'dd': round(float(e['dd']) * 100, 1), 'universe': n,
        'profit_used': py is not None, 'history_used': bool(has_hist), 'n_prior_episodes': len(prior_lifts) - (1 if 'crash' in rets else 0),
        'market_median': {f'{lab}_{m}': round(v * 100, 2) for (lab, m), v in mkt_med.items()},
        'top10': grp(U['rank'] <= 10), 'top30': grp(U['rank'] <= 30), 'top100': grp(U['rank'] <= min(100, n)),
        'bottom100': grp(U['rank'] > n - min(100, n)), 'all': grp(U['rank'] > 0),
        'spearman': {},
    }
    for lab in rets:
        v = U[['total', 'x_' + lab]].dropna()
        summ['spearman'][lab] = round(float(v['total'].rank().corr(v['x_' + lab].rank())), 3) if len(v) > 10 else None
        # 부문별 상관
        for part in ('s_def', 'ated_dummy', 's_hold', 's_grow', 's_flow', 's_com'):
            if part not in U:
                continue
            vv = U[[part, 'x_' + lab]].dropna()
            summ['spearman'][f'{part}_{lab}'] = round(float(vv[part].rank().corr(vv['x_' + lab].rank())), 3) if len(vv) > 10 else None
    # 5분위
    U['q5'] = pd.qcut(U['rank'], 5, labels=[1, 2, 3, 4, 5])
    summ['quintile'] = {}
    for lab in rets:
        summ['quintile'][lab] = [round(float(U.loc[U['q5'] == q, 'x_' + lab].median()) * 100, 2) for q in (1, 2, 3, 4, 5)]
    results.append(summ)
    cols = ['rank', 'name', 'market', 'sector', 'total', 's_def', 's_hold', 's_grow', 's_flow', 's_com', 'beta', 'div', 'pbr', 'profit_years', 'ret2y', 'mdd', 'beats', 'inst_3m', 'frgn_ratio', 'short'] + [c for c in U.columns if c.startswith('x_') or c in rets]
    top = U[cols].head(100).reset_index().rename(columns={'index': 'code'})
    top = top.replace({np.nan: None})
    top.to_json(os.path.join(OUT, f'top_{T}.json'), orient='records', force_ascii=False)
    print(T, TR, f"dd {e['dd']*100:.1f}% n={n}", 'top30 crash excess', summ['top30'].get('crash'), 'rho', summ['spearman'].get('crash'))

json.dump(results, open(os.path.join(OUT, 'summary.json'), 'w'), ensure_ascii=False, indent=1)
open(os.path.join(ROOT, 'dart_codes.txt'), 'w').write('\n'.join(sorted(ALLCODES)))
print('구간', len(results))
