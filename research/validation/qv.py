# -*- coding: utf-8 -*-
"""새 평점 규칙 검증 — '안전하고 수익률이 좋고 코스피에 덜 휘둘리는 종목' 순위가 실제로 맞았는가

기준일: 2018년 1분기 ~ 2025년 3분기 매 분기 말(마지막 주), 각 기준일에서 그날까지의 자료만 써서 점수를 매기고
        그 뒤 52주(1년) 동안의 결과와 비교한다.
결과(정답) 세 가지 — 모두 코스피 기준
  안전      : 다음 52주 최대 낙폭(주간 종가 경로)
  수익률    : 다음 52주 수익률 − 코스피 수익률
  덜 휘둘림 : 다음 52주 주간 수익률의 코스피 베타(낮을수록 좋음)
평점(100점)
  안전 30      = 30 × (점수와 '다음 최대 낙폭'의 순위상관 평균 ÷ 0.40), 0~30
  수익률 30    = 30 × (점수와 '다음 코스피 대비 수익률'의 순위상관 평균 ÷ 0.15), 0~30
  덜 휘둘림 20 = 20 × (점수와 '다음 베타(낮을수록)'의 순위상관 평균 ÷ 0.40), 0~20
  일관성 20    = 20 × min(코스피가 오른 해의 맞은 비율, 내린 해의 맞은 비율)
                 (맞은 비율 = 기준일 × 세 목표 중 순위상관이 0보다 큰 비율)
설계 구간 2018~2021 기준일로만 후보를 고르고, 확인 구간 2022~2025 기준일로 평점을 매긴다.
자료: raw/weekly(주간 수정 등락률·종가·거래대금), raw/index_daily, raw/snap(시총·PBR/배당·외국인·공매도·업종),
      raw/dart_op*(영업이익), raw/dart_main_*(주요 재무, 있으면)
"""
import os, re, json, math, time
import numpy as np, pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__)); RAW = os.path.join(ROOT, 'raw'); OUT = os.path.join(ROOT, 'qv_out')
os.makedirs(OUT, exist_ok=True)
EXCL = '스팩|SPAC|리츠|ETN|ETF|KODEX|TIGER|기업인수목적|인프라|맥쿼리|선박|부동산투자'
PREF_RE = r'우$|우B$|우C$|\d우'
H = 52
LOG = []
T0 = time.time()
ONLY = os.environ.get('QV_ANCHORS')  # 시험용: 앞의 몇 개 기준일만


def log(*a):
    s = ' '.join(str(x) for x in a); print(s, flush=True); LOG.append(s)


# ───────────────────────── 자료 읽기
def load_weekly():
    fs = sorted(os.listdir(os.path.join(RAW, 'weekly')))
    R, C, V, NM, MK = {}, {}, {}, {}, {}
    for f in fs:
        m, d = f[2:-7].split('_')
        df = pd.read_csv(os.path.join(RAW, 'weekly', f), dtype={'티커': str}, usecols=['티커', '종목명', '종가', '등락률', '거래대금'])
        df = df.drop_duplicates('티커').set_index('티커')
        R.setdefault(d, {}).update(pd.to_numeric(df['등락률'], errors='coerce').div(100).to_dict())
        C.setdefault(d, {}).update(pd.to_numeric(df['종가'], errors='coerce').to_dict())
        V.setdefault(d, {}).update(pd.to_numeric(df['거래대금'], errors='coerce').to_dict())
        NM.setdefault(d, {}).update(df['종목명'].astype(str).to_dict())
        MK.setdefault(d, {}).update({c: m for c in df.index})
    dates = sorted(R)
    mk = lambda D: pd.DataFrame.from_dict(D, orient='index').reindex(dates)
    R, C, V, NM, MK = mk(R), mk(C), mk(V), mk(NM), mk(MK)
    idx = pd.to_datetime(dates)
    for X in (R, C, V, NM, MK): X.index = idx
    R = R.where(V > 0)                       # 거래 없는 주는 빈칸
    return R, C, V, NM, MK


def load_index(widx):
    d = pd.read_csv(os.path.join(RAW, 'index_daily.csv.gz'), dtype={'date': str})
    d.index = pd.to_datetime(d['date']); d = d[['kospi', 'kosdaq']].astype(float).sort_index()
    w = d.reindex(d.index.union(widx)).ffill().reindex(widx)
    return w.pct_change()


def snaps(kind):
    out = {}
    for f in os.listdir(os.path.join(RAW, 'snap')):
        p = f[:-7].split('_')
        if p[0] != kind: continue
        out.setdefault(pd.Timestamp(p[2]), []).append(os.path.join(RAW, 'snap', f))
    return dict(sorted(out.items()))


def snap_at(S, t, cache={}):
    ks = [k for k in S if k <= t]
    if not ks: return None
    k = ks[-1]; key = (id(S), k)
    if key not in cache:
        frames = []
        for f in S[k]:
            df = pd.read_csv(f, dtype=str)
            df = df.rename(columns={'종목코드': '티커'}).drop_duplicates('티커').set_index('티커'); frames.append(df)
        cache[key] = pd.concat(frames)
    return cache[key]


def num(s):
    return pd.to_numeric(s.astype(str).str.replace(',', ''), errors='coerce')


def load_dart():
    """(종목, 연도) → 계정값. 영업이익은 dart_op*·dart_main 모두에서, 연결 우선."""
    D = {}
    def put(code, y, acc, v, fs):
        if code is None or v is None or (isinstance(v, float) and math.isnan(v)): return
        k = (code, int(y), acc)
        if k not in D or (fs == 'CFS' and D[k][1] != 'CFS'):
            D[k] = (v, fs)
    files = [f for f in os.listdir(RAW) if re.match(r'dart_op_\d{4}(_x)?\.csv\.gz$', f)]
    for f in files:
        df = pd.read_csv(os.path.join(RAW, f), dtype=str)
        for col, dy in (('thstrm_amount', 0), ('frmtrm_amount', 1), ('bfefrmtrm_amount', 2)):
            v = num(df[col])
            for code, y, fs, x in zip(df['stock_code'], df['bsns_year'], df['fs_div'], v):
                if pd.notna(x) and isinstance(code, str): put(code, int(y) - dy, 'op', float(x), fs)
    nmain = 0
    for f in sorted(os.listdir(RAW)):
        if not re.match(r'dart_main_\d{4}\.csv\.gz$', f): continue
        df = pd.read_csv(os.path.join(RAW, f), dtype=str); nmain += len(df)
        for col, dy in (('th', 0), ('fr', 1), ('bf', 2)):
            v = num(df[col])
            for code, y, fs, acc, x in zip(df['stock_code'], df['bsns_year'], df['fs_div'], df['acc'], v):
                if pd.notna(x) and isinstance(code, str): put(code.strip(), int(y) - dy, acc, float(x), fs)
    log('DART 값', len(D), '주요 재무 행', nmain)
    return {k: v[0] for k, v in D.items()}, nmain > 0


# ───────────────────────── 기준일별 특성
def regress(Y, X):
    """Y: (T, n) 빈칸 허용, X: (T,) → 베타, 고유 변동성(연), 설명력 R²"""
    M = ~np.isnan(Y) & ~np.isnan(X)[:, None]
    n = M.sum(0).astype(float)
    Yz = np.where(M, Y, 0.0); Xm = np.where(M, X[:, None], 0.0)
    with np.errstate(invalid='ignore', divide='ignore'):
        mx = Xm.sum(0) / n; my = Yz.sum(0) / n
        dx = np.where(M, Xm - mx, 0.0); dy = np.where(M, Yz - my, 0.0)
        sxx = (dx ** 2).sum(0); sxy = (dx * dy).sum(0); syy = (dy ** 2).sum(0)
        b = sxy / sxx
        res = syy - b * sxy
        idio = np.sqrt(np.maximum(res, 0) / (n - 2)) * np.sqrt(52)
        r2 = 1 - res / syy
    bad = n < 30
    b[bad] = np.nan; idio[bad] = np.nan; r2[bad] = np.nan
    return b, idio, r2


def path_mdd(Rw):
    P = np.nancumprod(np.where(np.isnan(Rw), 0, Rw) + 1, axis=0)
    P = np.vstack([np.ones((1, P.shape[1])), P])
    return (P / np.maximum.accumulate(P, axis=0) - 1).min(0)


def features(i, W, IX, CAP, FUND, FR, SH, SECT, DART):
    R, C, V, NM, MK = W
    t = R.index[i]; codes = R.columns
    r104 = R.iloc[i - 103:i + 1].values; r52 = r104[-52:]
    mk = MK.iloc[i]; nm = NM.iloc[i]
    live = nm.notna().values
    F = pd.DataFrame(index=codes)
    F['name'] = nm; F['market'] = mk
    F['nobs104'] = (~np.isnan(r104)).sum(0); F['nobs52'] = (~np.isnan(r52)).sum(0)
    with np.errstate(invalid='ignore'):
        F['vol1y'] = np.nanstd(r52, axis=0, ddof=1) * np.sqrt(52)
    F.loc[F.nobs52 < 40, 'vol1y'] = np.nan
    beta = np.full(len(codes), np.nan); idio = beta.copy(); r2 = beta.copy(); dbeta = beta.copy()
    cbeat = beta.copy(); cx = beta.copy(); cn = np.zeros(len(codes))
    for m, col in (('KOSPI', 'kospi'), ('KOSDAQ', 'kosdaq')):
        sel = (mk == m).values
        if not sel.any(): continue
        X = IX[col].iloc[i - 103:i + 1].values
        b, s, q = regress(r104[:, sel], X); beta[sel] = b; idio[sel] = s; r2[sel] = q
        Xd = np.where(X < 0, X, np.nan)
        bd, _, _ = regress(r104[:, sel], Xd); dbeta[sel] = bd
        cw = X <= -0.02
        Y = r104[cw][:, sel]; Xc = X[cw][:, None]
        ok = ~np.isnan(Y)
        cn[sel] = ok.sum(0)
        with np.errstate(invalid='ignore'):
            cbeat[sel] = np.where(ok, Y > Xc, False).sum(0) / ok.sum(0)
            cx[sel] = np.nansum(np.where(ok, Y - Xc, np.nan), axis=0) / ok.sum(0)
    F['beta2y'] = beta; F['idio2y'] = idio; F['r2_2y'] = r2; F['downbeta'] = dbeta
    F['crash_n'] = cn; F['crash_beat'] = np.where(cn >= 5, cbeat, np.nan); F['crash_x'] = np.where(cn >= 5, cx, np.nan)
    F['mdd2y'] = np.where(F.nobs104 >= 50, path_mdd(r104), np.nan)
    F['ret1y'] = np.where(F.nobs52 >= 40, np.nanprod(r52 + 1, axis=0) - 1, np.nan)
    F['ret2y'] = np.where(F.nobs104 >= 80, np.nanprod(r104 + 1, axis=0) - 1, np.nan)
    y0 = pd.Timestamp(t.year, 1, 1); yp = pd.Timestamp(t.year - 1, 1, 1)
    sl_ytd = (R.index > y0 - pd.Timedelta(days=1)) & (R.index <= t)
    sl_prev = (R.index >= yp) & (R.index < y0)
    F['ytd'] = np.nanprod(R.values[sl_ytd] + 1, axis=0) - 1
    F['ret_prev'] = np.nanprod(R.values[sl_prev] + 1, axis=0) - 1
    with np.errstate(invalid='ignore'):
        F['maxw'] = np.nanmax(np.where(np.isnan(r52), -9, r52), axis=0)
        F['bigw'] = (np.abs(np.nan_to_num(r52)) >= 0.15).sum(0)
        mu = np.nanmean(r52, axis=0); sd = np.nanstd(r52, axis=0)
        F['skew'] = np.nanmean((r52 - mu) ** 3, axis=0) / sd ** 3
    F.loc[F.nobs52 < 40, ['maxw', 'bigw', 'skew']] = np.nan
    v52 = V.iloc[i - 51:i + 1].values
    F['v52'] = np.nansum(v52, axis=0)
    with np.errstate(invalid='ignore', divide='ignore'):
        F['amihud'] = np.nanmean(np.where(v52 > 0, np.abs(r52) / v52, np.nan), axis=0) * 1e10
    F['tv20'] = np.nansum(V.iloc[i - 3:i + 1].values, axis=0) / 20
    r13 = R.iloc[i - 12:i + 1]; F['zero13'] = ((r13 == 0) | r13.isna()).sum().values
    cap = snap_at(CAP, t)
    sh = num(cap['상장주식수']).reindex(codes) if cap is not None else pd.Series(np.nan, index=codes)
    F['mcap'] = sh.values * C.iloc[i].values
    F['turnover'] = F['v52'] / F['mcap']
    fu = snap_at(FUND, t)
    if fu is not None:
        F['pbr'] = num(fu['PBR']).reindex(codes).values; F['div'] = num(fu['DIV']).reindex(codes).values
        per = num(fu['PER']).reindex(codes).values
        F['ey'] = np.where(per > 0, 1 / per, 0.0)
    fr = snap_at(FR, t)
    F['frgn'] = num(fr['지분율']).reindex(codes).values if fr is not None else np.nan
    s = snap_at(SH, t)
    F['short'] = num(s['비중']).reindex(codes).values if s is not None else np.nan
    se = snap_at(SECT, t)
    F['sector'] = se['업종명'].reindex(codes).values if se is not None else None
    ay = t.year - 1 if t.month >= 4 else t.year - 2
    def g(c, y, a): return DART.get((c, y, a))
    py, stab, eqr, cur, roa, opm, debt = [], [], [], [], [], [], []
    for c in codes:
        ops = [g(c, y, 'op') for y in range(ay - 3, ay + 1)]
        py.append(sum(1 for x in ops if x is not None and x > 0) if all(x is not None for x in ops) else np.nan)
        o5 = [x for x in (g(c, y, 'op') for y in range(ay - 4, ay + 1)) if x is not None]
        if len(o5) >= 4:
            m_, s_ = np.mean(o5), np.std(o5)
            stab.append((m_ / s_) if s_ > 0 else (9.0 if m_ > 0 else -9.0))
        else: stab.append(np.nan)
        ta, te, ca, cl, ni, rv, op, tl = (g(c, ay, a) for a in ('ta', 'te', 'ca', 'cl', 'ni', 'rev', 'op', 'tl'))
        eqr.append(te / ta if ta and te is not None else np.nan)
        cur.append(ca / cl if ca is not None and cl else np.nan)
        roa.append(ni / ta if ta and ni is not None else np.nan)
        opm.append(op / rv if rv and op is not None and rv > 0 else np.nan)
        debt.append(tl / te if te and tl is not None and te > 0 else np.nan)
    F['profit_years'] = py; F['op_stab'] = np.clip(stab, -9, 9); F['eq_ratio'] = eqr; F['cur_ratio'] = np.clip(cur, 0, 20)
    F['roa'] = roa; F['opm'] = np.clip(opm, -1, 1); F['debt'] = np.clip(debt, 0, 20)
    F['chk'] = ((F.beta2y < 0.6).astype(int) + (F['div'] >= 2).astype(int) + (F.profit_years == 4).astype(int)
                + ((F.pbr > 0) & (F.pbr < 1.2)).astype(int))
    F = F[live]
    return F


def outcomes(i, R, IX):
    fr = R.iloc[i + 1:i + 1 + H].values
    k = IX['kospi'].iloc[i + 1:i + 1 + H].values
    n = (~np.isnan(fr)).sum(0)
    ret = np.nanprod(fr + 1, axis=0) - 1
    kret = np.prod(k + 1) - 1
    mdd = path_mdd(fr)
    b, _, _ = regress(fr, k)
    O = pd.DataFrame({'fwd_ret': ret, 'fwd_ex': ret - kret, 'fwd_mdd': mdd, 'fwd_beta': b, 'fwd_n': n}, index=R.columns)
    O.loc[O.fwd_n < 26, ['fwd_ret', 'fwd_ex', 'fwd_mdd', 'fwd_beta']] = np.nan
    return O, kret


# ───────────────────────── 대상(유니버스)과 지금 식
def pct(s, hi=True):
    s = pd.Series(s, dtype=float)
    p = s.rank(pct=True) * 100
    return (p if hi else 101 - p).fillna(50)


def universes(F):
    nm = F['name'].astype(str)
    base = ~nm.str.contains(EXCL)
    st = base & ~nm.str.contains(PREF_RE) & (F.mcap >= 1e11) & (F.nobs104 >= 50) & (F.zero13 < 4) & (F.crash_n >= 5) & F.vol1y.notna() & F.beta2y.notna()
    q = F.loc[st, 'turnover'].quantile(0.2); st &= F.turnover >= q
    A = base & (F.mcap >= 5e10) & (F.tv20 >= 1e8) & (F.nobs104 >= 100) & F.beta2y.notna()
    G = A & (F.ret2y >= 0.30) & (F.ret_prev > 0) & (F.ytd > 0)
    return {'st': st, 'sc': A, 'd1': G}


def current_score(lst, U):
    if lst == 'st':
        return (pct(-U.vol1y) + pct(-U.beta2y) + pct(U.crash_beat)).values / 3
    if lst == 'sc':
        return U.chk.values * 25.0
    d = (pct(-U.beta2y) + pct(U['div']) + pct(-U.pbr.where(U.pbr > 0, 99)) + np.where(U.profit_years == 4, 100, U.profit_years.fillna(0) * 15)) / 4
    h = (pct(U.crash_beat) + pct(U.crash_x) + pct(U.mdd2y)) / 3
    gr = (pct(U.ret2y) + pct(U.ret_prev) + pct(U.ytd)) / 3
    sh = pct(-U.short) if U.short.notna().any() else 50
    cm = (pct(U.frgn) + sh + 50) / 3
    return (0.30 * d + 0.20 * h + 0.20 * gr + 0.15 * 50 + 0.15 * cm).values


CAND = [  # (특성, 높을수록 좋음?, 이름)
    ('vol1y', False, '1년 변동성 낮음'), ('beta2y', False, '2년 베타 낮음'), ('idio2y', False, '고유 변동성 낮음'),
    ('r2_2y', False, '코스피 설명력(R²) 낮음'), ('mdd2y', True, '2년 최대 낙폭 작음'), ('maxw', False, '1년 최대 주간 상승 작음'),
    ('bigw', False, '큰 등락(±15%) 주 적음'), ('skew', False, '수익률 왜도 낮음(복권형 아님)'), ('crash_beat', True, '급락 주 덜 빠진 비율'),
    ('crash_x', True, '급락 주 초과 수익'), ('downbeta', False, '하락 베타 낮음'), ('turnover', False, '회전율 낮음'),
    ('amihud', False, '비유동성 낮음(거래 잘 됨)'), ('div', True, '배당수익률'), ('pbr', False, 'PBR 낮음'), ('ey', True, '이익수익률(1/PER)'),
    ('profit_years', True, '4년 흑자 연수'), ('op_stab', True, '영업이익 안정성'), ('eq_ratio', True, '자기자본비율'),
    ('cur_ratio', True, '유동비율'), ('roa', True, 'ROA'), ('opm', True, '영업이익률'), ('debt', False, '부채비율 낮음'),
    ('ret1y', True, '1년 수익률'), ('ret2y', True, '2년 수익률'), ('frgn', True, '외국인 보유율'), ('short', False, '공매도 잔고 낮음'),
    ('chk', True, '위험·가치 체크리스트 개수'),
]
CN = {k: (hi, nm) for k, hi, nm in CAND}
START = {'st': ['vol1y', 'beta2y', 'crash_beat'], 'sc': ['chk'],
         'd1': ['beta2y', 'div', 'pbr', 'profit_years', 'crash_beat', 'crash_x', 'mdd2y', 'ret2y', 'frgn']}


def rc(a, b):
    a = pd.Series(a); b = pd.Series(b); ok = a.notna() & b.notna()
    if ok.sum() < 20 or a[ok].nunique() < 2: return np.nan
    return float(np.corrcoef(a[ok].rank(), b[ok].rank())[0, 1])


def rate(per):
    """per: [(기준일, 코스피 결과, ic_safe, ic_ret, ic_ind, 상하위 비교...)]"""
    if not per: return None
    P = pd.DataFrame(per)
    m = P[['ic_safe', 'ic_ret', 'ic_ind']].mean()
    safe = 30 * min(1, max(0, m.ic_safe / 0.40)); ret = 30 * min(1, max(0, m.ic_ret / 0.15)); ind = 20 * min(1, max(0, m.ic_ind / 0.40))
    sh = {}
    for reg, sub in (('up', P[P.kret > 0]), ('down', P[P.kret <= 0])):
        if len(sub): sh[reg] = float((sub[['ic_safe', 'ic_ret', 'ic_ind']] > 0).values.mean())
    cons = 20 * min(sh.values()) if sh else 0
    q = P[['q5_ex', 'q1_ex', 'q5_mdd', 'q1_mdd', 'q5_beta', 'q1_beta']].mean()
    return {'total': round(safe + ret + ind + cons, 1), 'safe': round(safe, 1), 'ret': round(ret, 1), 'ind': round(ind, 1), 'cons': round(cons, 1),
            'ic_safe': round(m.ic_safe, 3), 'ic_ret': round(m.ic_ret, 3), 'ic_ind': round(m.ic_ind, 3),
            'hit_up': round(sh.get('up', np.nan), 3), 'hit_down': round(sh.get('down', np.nan), 3), 'n': len(P),
            'n_up': int((P.kret > 0).sum()), 'n_down': int((P.kret <= 0).sum()),
            **{k: round(float(v) * 100, 1) for k, v in q.items()}}


def evaluate(score_fn, lst, anchors, DATA):
    per = []
    for a in anchors:
        U, O, kret = DATA[a][lst]
        if U is None: continue
        s = score_fn(lst, U, a)
        s = pd.Series(s, index=U.index)
        o = O.reindex(U.index)
        q5 = s >= s.quantile(0.8); q1 = s <= s.quantile(0.2)
        per.append({'anchor': str(a.date()), 'kret': kret, 'ic_safe': rc(s, o.fwd_mdd), 'ic_ret': rc(s, o.fwd_ex), 'ic_ind': rc(s, -o.fwd_beta),
                    'q5_ex': o.fwd_ex[q5].mean(), 'q1_ex': o.fwd_ex[q1].mean(), 'q5_mdd': o.fwd_mdd[q5].mean(), 'q1_mdd': o.fwd_mdd[q1].mean(),
                    'q5_beta': o.fwd_beta[q5].mean(), 'q1_beta': o.fwd_beta[q1].mean(), 'n': len(U)})
    return per


def main():
    W = load_weekly(); R = W[0]
    log('주간 자료', R.shape, str(R.index[0].date()), '~', str(R.index[-1].date()), f'{time.time() - T0:.0f}초')
    IX = load_index(R.index)
    CAP, FUND, FR, SH, SECT = snaps('CAP'), snaps('FUND'), snaps('FR'), snaps('SHORT'), snaps('SECT')
    DART, has_main = load_dart()
    anchors = []
    for q in pd.date_range('2018-03-31', '2025-09-30', freq='QE'):
        i = int(R.index.searchsorted(q, side='right')) - 1
        if i + H < len(R.index) and i >= 103: anchors.append(i)
    if ONLY: anchors = anchors[:int(ONLY)]
    DATA = {}; rows = []
    for i in anchors:
        t = R.index[i]
        F = features(i, W, IX, CAP, FUND, FR, SH, SECT, DART)
        O, kret = outcomes(i, R, IX)
        Us = universes(F); DATA[t] = {}
        for k, msk in Us.items():
            U = F[msk.reindex(F.index).fillna(False)]
            DATA[t][k] = (U if len(U) >= 30 else None, O, kret)
        rows.append({'anchor': str(t.date()), 'kospi_fwd': round(kret * 100, 1), **{f'n_{k}': int(m.sum()) for k, m in Us.items()}})
        log('기준일', t.date(), f'코스피 다음 1년 {kret * 100:+.1f}%', {k: int(m.sum()) for k, m in Us.items()}, f'{time.time() - T0:.0f}초')
    pd.DataFrame(rows).to_csv(os.path.join(OUT, 'anchors.csv'), index=False)
    AN = sorted(DATA); DES = [a for a in AN if a.year <= 2021]; CHK = [a for a in AN if a.year >= 2022]
    # 특성 백분위 미리 계산(대상 안, 업종 안 버전도)
    PC = {}
    for a in AN:
        for lst in ('st', 'sc', 'd1'):
            U = DATA[a][lst][0]
            if U is None: continue
            d = {}
            for k, hi, _ in CAND:
                x = U[k].astype(float) if k in U else pd.Series(np.nan, index=U.index)
                if k == 'pbr': x = x.where(x > 0, 99)
                d[k] = pct(x if hi else -x).values
                if U['sector'].notna().any():
                    xs = (x if hi else -x)
                    d['S:' + k] = xs.groupby(U['sector'].fillna('?')).rank(pct=True).mul(100).fillna(50).values
            PC[(a, lst)] = d

    def combo(keys, sect=False):
        def f(lst, U, a):
            d = PC[(a, lst)]
            return np.mean([d[('S:' + k) if sect and ('S:' + k) in d else k] for k in keys], axis=0)
        return f

    def cur(lst, U, a): return current_score(lst, U)
    RES = {'rule': '안전 30·수익률 30·덜 휘둘림 20·일관성 20, 설계 2018~2021 / 확인 2022~2025, 결과는 기준일 다음 52주(코스피 기준)',
           'anchors': rows, 'dart_main': has_main, 'lists': {}}
    LAB = {'st': '안정 관찰', 'sc': '점수 순위', 'd1': '방어 1번'}
    for lst in ('st', 'sc', 'd1'):
        info = {'label': LAB[lst]}
        pc_ = evaluate(cur, lst, AN, DATA)
        info['current'] = {'design': rate([p for p in pc_ if p['anchor'] < '2022']), 'check': rate([p for p in pc_ if p['anchor'] >= '2022']), 'all': rate(pc_)}
        pd.DataFrame(pc_).to_csv(os.path.join(OUT, f'per_{lst}_current.csv'), index=False)
        # 단일 특성 성적(설계·확인)
        single = []
        for k, hi, nm in CAND:
            p = evaluate(combo([k]), lst, AN, DATA)
            single.append({'key': k, 'label': nm, 'design': rate([x for x in p if x['anchor'] < '2022']), 'check': rate([x for x in p if x['anchor'] >= '2022'])})
        info['single'] = single
        # 탐색: 설계 구간 평점이 가장 많이 오르는 쪽으로 더하기·빼기 (같은 비중, 최대 7개)
        keys = list(START[lst]); path = []
        def score_of(ks, sect=False):
            p = evaluate(combo(ks, sect), lst, DES, DATA); return rate(p)['total'] if p else -1
        best = score_of(keys); path.append({'step': 'start', 'keys': list(keys), 'design': best})
        for step in range(10):
            trials = []
            for k, _, _ in CAND:
                if k not in keys and len(keys) < 7: trials.append((keys + [k], '+' + k))
            for k in keys:
                if len(keys) > 1: trials.append(([x for x in keys if x != k], '-' + k))
            sc = [(score_of(ks), ks, mv) for ks, mv in trials]
            s_, ks, mv = max(sc, key=lambda x: x[0])
            if s_ < best + 0.5: break
            best, keys = s_, ks; path.append({'step': mv, 'keys': list(keys), 'design': s_})
            log(LAB[lst], '탐색', mv, '설계 평점', s_)
        sect = score_of(keys, True) > best + 0.5
        pn = evaluate(combo(keys, sect), lst, AN, DATA)
        pd.DataFrame(pn).to_csv(os.path.join(OUT, f'per_{lst}_new.csv'), index=False)
        info['new'] = {'keys': keys, 'labels': [CN[k][1] for k in keys], 'sector_neutral': bool(sect), 'path': path,
                       'design': rate([p for p in pn if p['anchor'] < '2022']), 'check': rate([p for p in pn if p['anchor'] >= '2022']), 'all': rate(pn)}
        # 같은 비중의 지금 성분(비교용)
        pe = evaluate(combo(START[lst]), lst, AN, DATA)
        info['current_eq'] = {'design': rate([p for p in pe if p['anchor'] < '2022']), 'check': rate([p for p in pe if p['anchor'] >= '2022'])}
        RES['lists'][lst] = info
        log(LAB[lst], '지금', info['current']['check'], '\n   새 식', keys, info['new']['check'])
    json.dump(RES, open(os.path.join(OUT, 'summary.json'), 'w'), ensure_ascii=False, indent=1, default=float)
    log('끝', f'{time.time() - T0:.0f}초')


if __name__ == '__main__':
    try:
        main()
    finally:
        open(os.path.join(OUT, 'log.txt'), 'w', encoding='utf-8').write('\n'.join(LOG))
