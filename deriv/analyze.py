"""선물·옵션 수급 지표 — 지표 계산(A7) · 코스피 연관 분석(A8) · 백테스트(A9)

규칙(매뉴얼 8장)
  - 지표는 t일 18:00(야간 선물은 t+1일 아침)에 알 수 있는 값, 대상은 t+1일 이후.
  - 워크포워드: 학습 750거래일 → 시험 250거래일, 250일씩 이동. 문턱·표준화·방향은 학습 구간으로만 정함.
  - 다중 검정: 후보 × 대상 전체에 벤야미니-호크버그(거짓 발견 비율 10%).
  - 제도 구간(deriv/data/regimes.csv)별로 방향이 같은지 확인.
  - 기준선: 단순 추세(오늘 등락), 기존 대시보드 확률(q_daily.p_up), 날짜 섞기(무작위).
  - 묶음: 학습 구간 성적 상위 5개의 방향 맞춘 표준점수 평균(대시보드의 750일·상위 5개 묶음과 같은 방식).
결과: deriv/out/*.csv, deriv/out/latest.json
"""
import json
import os
import sys
import warnings

import numpy as np
import pandas as pd
from scipy import stats

warnings.filterwarnings('ignore')
ROOT = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(ROOT)
DATA = os.path.join(ROOT, 'data')
OUT = os.path.join(ROOT, 'out')
os.makedirs(OUT, exist_ok=True)
TRAIN, TEST = 750, 250


def rd(name):
    for ext in ('.csv.gz', '.csv'):   # 커지면 .gz 로 바뀌므로 .gz 우선
        p = os.path.join(DATA, name + ext)
        if os.path.exists(p): return pd.read_csv(p, low_memory=False)
    return None


def num(s):
    return pd.to_numeric(s.astype(str).str.replace(',', '').str.replace('−', '-').replace({'-': None, '': None, 'nan': None}), errors='coerce')


def ddate(s):
    s = s.astype(str).str.slice(0, 10).str.replace('/', '-')
    return pd.to_datetime(s, errors='coerce')


def collect_latest(fname):
    cdir = os.path.join(REPO, 'data', 'collect')
    if not os.path.isdir(cdir): return None
    parts = []
    for d in sorted(os.listdir(cdir)):
        p = os.path.join(cdir, d, fname)
        if os.path.exists(p): parts.append(pd.read_csv(p))
    return pd.concat(parts, ignore_index=True) if parts else None


# ------------------------------------------------------------------ 가격·대상
def load_price():
    parts = []
    k = rd('kospi_long')
    if k is not None and len(k) > 1000:
        k = k.rename(columns={'날짜': 'date'}); k['date'] = ddate(k['date']); parts.append(k)
    h = pd.read_csv(os.path.join(REPO, 'pkg', 'history', '01_코스피_일별시세.csv'))
    h = h.rename(columns={'날짜': 'date'}); h['date'] = ddate(h['date']); parts.append(h)
    cdir = os.path.join(REPO, 'data', 'collect')
    for d in sorted(os.listdir(cdir)) if os.path.isdir(cdir) else []:
        p = os.path.join(cdir, d, '01_코스피_일별시세.csv')
        if os.path.exists(p):
            c = pd.read_csv(p).rename(columns={'날짜': 'date'}); c['date'] = ddate(c['date']); parts.append(c)
    px = pd.concat(parts, ignore_index=True)
    for c in ('시가', '고가', '저가', '종가', '거래대금'): px[c] = num(px[c])
    px = px.dropna(subset=['date', '종가']).drop_duplicates('date', keep='last').sort_values('date').set_index('date')
    px = px[px['시가'] > 0]
    return px[['시가', '고가', '저가', '종가', '거래대금']].rename(columns={'시가': 'open', '고가': 'high', '저가': 'low', '종가': 'close', '거래대금': 'value'})


def targets(px):
    c, o = px['close'], px['open']
    T = pd.DataFrame(index=px.index)
    T['gap'] = o.shift(-1) / c - 1                       # 다음 날 시가 갭
    T['dir'] = (c.shift(-1) > c).astype(float).where(c.shift(-1).notna())   # 다음 날 종가 방향
    T['wk'] = c.shift(-5) / c - 1                         # 1주(5거래일) 수익률
    r = c.pct_change()
    fwd_min_day = pd.concat([r.shift(-k) for k in range(1, 6)], axis=1).min(axis=1)
    fwd_min_cum = pd.concat([c.shift(-k) / c - 1 for k in range(1, 6)], axis=1).min(axis=1)
    T['crash'] = ((fwd_min_day <= -0.03) | (fwd_min_cum <= -0.05)).astype(float).where(c.shift(-5).notna())
    # 저점 신호(앞만 보는 정의): 20거래일 뒤 +5% 이상이고, 그 사이 10거래일 안에 오늘 종가보다 2% 넘게 내려가지 않음
    fwd_low10 = pd.concat([c.shift(-k) for k in range(1, 11)], axis=1).min(axis=1)
    T['bottom'] = ((c.shift(-20) / c - 1 >= 0.05) & (fwd_low10 >= c * 0.98)).astype(float).where(c.shift(-20).notna())
    T['ret1'] = c.shift(-1) / c - 1                       # 전략 수익 계산용(대상 아님)
    return T


TARGETS = ['gap', 'dir', 'wk', 'crash', 'bottom']


# ------------------------------------------------------------------ 지표(A7)
def z250(s):
    m = s.rolling(250, min_periods=120).mean(); sd = s.rolling(250, min_periods=120).std()
    return (s - m) / sd


INV_COLS = None   # probe 로 확정: 13102 일별추이 열 → 투자자


def investor_frame(inv, prod, opt, unit='AMT', detail=False):
    if inv is None: return None
    q = (inv['상품'] == prod) & (inv['권리'] == opt) & (inv['단위'] == unit) & (inv['장구분'] == '정규')
    q &= (inv['상세'] == 'Y') if (detail and '상세' in inv) else ~(inv.get('상세', pd.Series('', index=inv.index)) == 'Y')
    d = inv[q].copy()
    if not len(d): return None
    d['date'] = ddate(d['TRD_DD'])
    m13102 = {'A07': '기관', 'A08': '기타법인', 'A09': '개인', 'A12': '외국인', 'AMT_OR_QTY': '전체'}
    m13103 = {'A01': '금융투자', 'A02': '보험', 'A03': '투신', 'A04': '은행', 'A05': '기타금융', 'A06': '연기금',
              'A08': '기타법인', 'A09': '개인', 'A10': '외국인', 'A11': '기타외국인', 'AMT_OR_QTY': '전체'}
    m = m13103 if detail else m13102
    keep = {k: v for k, v in m.items() if k in d.columns}
    out = d[['date'] + list(keep)].rename(columns=keep)
    for c in keep.values(): out[c] = num(out[c])
    return out.dropna(subset=['date']).drop_duplicates('date', keep='last').set_index('date').sort_index()


def build_indicators(px):
    I = {}
    note = {}
    inv = rd('inv_daily')
    if inv is not None:
        for c in ('상세',):
            if c not in inv: inv[c] = ''
        inv['상세'] = inv['상세'].fillna('')
    fut = investor_frame(inv, 'FUK2I', 'ALL')
    if fut is not None:
        for who in ('외국인', '기관', '개인'):
            if who in fut:
                s = fut[who] / 1e12   # 조원
                I[f'F_{who}_1d'] = s; I[f'F_{who}_5d'] = s.rolling(5).sum(); I[f'F_{who}_20d'] = s.rolling(20).sum(); I[f'F_{who}_z'] = z250(s.rolling(5).sum())
        # F2 현·선물 동시 방향
        cash = pd.read_csv(os.path.join(REPO, 'pkg', 'history', '01_코스피_투자자별_순매수_거래대금.csv')).rename(columns={'날짜': 'date'})
        cash['date'] = ddate(cash['date']); cf = num(cash.set_index('date')['외국인합계'])
        cl = collect_latest('03_코스피_투자자별_순매수_거래대금.csv')
        if cl is not None:
            cl['date'] = ddate(cl['날짜']); f2 = cl.set_index('date')
            add = num(f2['외국인']) + num(f2.get('기타외국인', pd.Series(0, index=f2.index))).fillna(0)
            cf = pd.concat([cf, add[~add.index.isin(cf.index)]])
        cf = cf[~cf.index.duplicated(keep='last')].sort_index() / 1e12
        if '외국인' in fut:
            j = pd.concat([cf.rename('c'), (fut['외국인'] / 1e12).rename('f')], axis=1).dropna()
            I['F2_현선동시'] = np.sign(j['c']) + np.sign(j['f'])
            I['F2_현선합계_5d'] = (j['c'] + j['f']).rolling(5).sum()
    futd = investor_frame(inv, 'FUK2I', 'ALL', detail=True)
    if futd is not None:
        for who in ('금융투자', '연기금', '투신'):
            if who in futd: I[f'F4_{who}_5d'] = (futd[who] / 1e12).rolling(5).sum()
    call, put = investor_frame(inv, 'OPK2I', 'C'), investor_frame(inv, 'OPK2I', 'P')
    if call is not None and put is not None:
        for who in ('외국인', '개인', '기관'):
            if who in call and who in put:
                d = (call[who] - put[who]) / 1e9   # 십억원(프리미엄)
                I[f'O1_{who}_콜-풋_1d'] = d; I[f'O1_{who}_콜-풋_5d'] = d.rolling(5).sum()
        if '개인' in put: I['O2_개인풋_5d'] = (put['개인'] / 1e9).rolling(5).sum()
    for wk in ('OPWKI', 'OPWKM'):
        c2, p2 = investor_frame(inv, wk, 'C'), investor_frame(inv, wk, 'P')
        if c2 is not None and p2 is not None and '외국인' in c2:
            I[f'O3_{wk}_외국인콜-풋_5d'] = ((c2['외국인'] - p2['외국인']) / 1e9).rolling(5, min_periods=1).sum()
            if '개인' in c2: I[f'O3_{wk}_개인콜-풋_5d'] = ((c2['개인'] - p2['개인']) / 1e9).rolling(5, min_periods=1).sum()
    # B1 베이시스
    b = rd('basis_daily')
    if b is not None and len(b):
        # 화면이 날짜마다 상장 월물 전부를 주므로, 거래된(종가>0) 가장 가까운 월물만 남긴다
        b['date'] = ddate(b['TRD_DD']); b['ym'] = b['ISU_NM'].astype(str).str.extract(r'F\s+(\d{6})')[0]
        b['fp'] = num(b['TDD_CLSPRC'])
        b = b[(b['fp'] > 0) & b['ym'].notna()].sort_values(['date', 'ym']).drop_duplicates('date', keep='first').set_index('date')
        mb, dr, sp = num(b['MKT_BASIS']), num(b['DIFF_RT']), num(b['SPOT_PRC'])
        I['B1_시장베이시스율'] = mb / sp * 100; I['B1_베이시스율_5d변화'] = (mb / sp * 100).diff(5)
        I['B1_괴리율'] = dr; I['B1_괴리율_z'] = z250(dr)
    # P1 프로그램매매
    pg = rd('program_daily')
    if pg is not None and len(pg):
        pg['date'] = ddate(pg['날짜']); pg['v'] = num(pg['NETBID_TRDVAL'])
        piv = pg.pivot_table(index='date', columns='ITM_TP_NM', values='v', aggfunc='last')
        note['program_cols'] = list(map(str, piv.columns))
        for col in piv.columns:
            nm = str(col)
            if '비차익' in nm: I['P1_비차익_5d'] = (piv[col] / 1e12).rolling(5).sum(); I['P1_비차익_1d'] = piv[col] / 1e12
            elif '차익' in nm: I['P1_차익_5d'] = (piv[col] / 1e12).rolling(5).sum(); I['P1_차익_1d'] = piv[col] / 1e12
    # V1·V2 변동성
    iv = rd('iv_daily')
    if iv is not None and len(iv):
        iv['date'] = ddate(iv['BAS_DD'] if 'BAS_DD' in iv else iv['TRD_DD']); iv = iv.drop_duplicates('date', keep='last').set_index('date').sort_index()
        rep, cl, pu = num(iv.get('REP_IMP_VOLT')), num(iv.get('CALL_AVG_IMP_VOLT')), num(iv.get('PUT_AVG_IMP_VOLT'))
        hv20 = num(iv['HIST_VOLT2']) if 'HIST_VOLT2' in iv else None
        if rep is not None:
            I['V1_대표IV'] = rep; I['V1_IV_5d변화'] = rep.diff(5)
            if hv20 is not None: I['V1_IV-HV20'] = rep - hv20
        if cl is not None and pu is not None: I['V2_풋-콜IV'] = pu - cl
    md = pd.read_csv(os.path.join(REPO, 'pkg', 'datasets', 'market_daily.csv')); md['date'] = ddate(md['date']); md = md.set_index('date')
    vk = num(md['vkospi'])
    vl = collect_latest('10_VKOSPI_일별.csv')
    if vl is not None:
        vl['date'] = ddate(vl['일자']); v2 = num(vl.drop_duplicates('date', keep='last').set_index('date')['종가'])
        vk = pd.concat([vk, v2[~v2.index.isin(vk.index)]]).sort_index()
    I['V1_VKOSPI'] = vk; I['V1_VKOSPI_5d변화'] = vk.diff(5); I['V1_VKOSPI_z'] = z250(vk)
    # R1 풋콜비율
    pc = rd('pcr_daily')
    if pc is not None and len(pc):
        pc['date'] = ddate(pc['TRD_DD']); pc = pc.drop_duplicates('date', keep='last').set_index('date').sort_index()
        pv, cv = num(pc['PVOL']), num(pc['CVOL'])
        r = pv / cv.replace(0, np.nan)
        I['R1_PCR_5d'] = r.rolling(5).mean(); I['R1_PCR_z'] = z250(r.rolling(5).mean())
    # M1 미결제약정 4분면
    fr = rd('fut_front_daily')
    if fr is not None and len(fr):
        fr = fr[~fr['TRD_DD'].astype(str).str.contains('야간')]
        fr['date'] = ddate(fr['TRD_DD']); fr = fr.drop_duplicates('date', keep='last').set_index('date').sort_index()
        tv = num(fr['ACC_TRDVAL'])
        cashv = px['value'].reindex(fr.index)
        I['T1_선물/현물거래대금'] = (tv / cashv).rolling(5).mean()
        oi, pr = num(fr.get('ACC_OPNINT_QTY')), num(fr.get('TDD_CLSPRC'))
        if oi is not None and pr is not None:
            doi, dpr = oi.diff(), pr.diff()
            I['M1_4분면'] = np.sign(dpr) * np.sign(doi)          # +1 신규매수 or 청산(가격↓ 미결제↓), −1 신규매도 or 숏커버
            I['M1_미결제_5d변화율'] = oi.pct_change(5) * np.sign(pr.diff(5))
    # E1·G1 옵션 행사가별
    ch = chain_metrics()
    if ch is not None:
        for c in ch.columns: I[c] = ch[c]
    # N1 야간 선물(다음 날 시가 갭에만)
    nf = pd.read_csv(os.path.join(REPO, 'pkg', 'datasets', 'night_fut.csv')); nf['date'] = ddate(nf['date']); nf = nf.set_index('date')
    n1 = num(nf['night_pct'])
    nl = collect_latest('09_야간선물_일별.csv')   # 일자 = 야간 종료일(다음 거래일) → 하루 앞 날짜(주간 날짜)에 붙인다
    if nl is not None:
        nl['end'] = ddate(nl['일자']); nl = nl.drop_duplicates('end', keep='last').set_index('end').sort_index()
        pct = num(nl['대비']) / (num(nl['종가']) - num(nl['대비'])) * 100
        idx = px.index
        for e, v in pct.items():
            prev = idx[idx < e]
            if len(prev) and prev[-1] not in n1.index: n1.loc[prev[-1]] = v
    I['N1_야간등락'] = n1.sort_index()
    # 기준선
    c = px['close']; I['BASE_오늘등락'] = c.pct_change() * 100; I['BASE_5일등락'] = c.pct_change(5) * 100
    q = pd.read_csv(os.path.join(REPO, 'pkg', 'datasets', 'q_daily.csv')); q['date'] = ddate(q['date']); q = q.set_index('date')
    I['DASH_p_up'] = num(q['p_up'])
    X = pd.DataFrame(I).sort_index()
    X = X[~X.index.duplicated()]
    return X, note


def bs_price(cp, S, K, T, sig, r=0.0):
    d1 = (np.log(S / K) + (r + 0.5 * sig ** 2) * T) / (sig * np.sqrt(T)); d2 = d1 - sig * np.sqrt(T)
    call = S * stats.norm.cdf(d1) - K * np.exp(-r * T) * stats.norm.cdf(d2)
    return np.where(cp == 'C', call, call - S + K * np.exp(-r * T))


def implied_vol(cp, S, K, T, price):
    lo, hi = np.full(len(K), 0.01), np.full(len(K), 3.0)
    for _ in range(60):
        mid = (lo + hi) / 2; pm = bs_price(cp, S, K, T, mid)
        up = pm > price; hi = np.where(up, mid, hi); lo = np.where(up, lo, mid)
    iv = (lo + hi) / 2
    intrinsic = np.where(cp == 'C', np.maximum(S - K, 0), np.maximum(K - S, 0))
    return np.where((price > intrinsic + 0.005) & (iv > 0.011) & (iv < 2.99), iv, np.nan)


def chain_metrics():
    """옵션 전종목(압축본) → 날짜별 풋콜 미결제비, 콜·풋 최대 미결제 행사가 거리, 최대 고통 거리, 감마 노출 추정.
    내재변동성은 화면에 없어서 정산가로 역산(블랙숄즈, 금리 0 가정). 감마 노출은 '딜러가 콜 롱·풋 숏' 가정의 추정치."""
    ch = rd('opt_chain_daily')
    if ch is None or not len(ch): return None
    ch['date'] = pd.to_datetime(ch['날짜']); ch['ym'] = ch['ym'].astype(str).str.slice(0, 6)
    ch = ch.dropna(subset=['K', 'oi', 'spot'])
    rows = []
    for d, g in ch.groupby('date'):
        yms = sorted(g['ym'].unique())
        f = g[g['ym'] == yms[0]]
        dte = days_to_expiry(d, yms[0])
        if (not np.isfinite(dte) or dte < 2) and len(yms) > 1: f = g[g['ym'] == yms[1]]; dte = days_to_expiry(d, yms[1])
        S = float(f['spot'].median()); c, p = f[f['cp'] == 'C'], f[f['cp'] == 'P']
        r = {'date': d, 'E1_만기까지일수': dte}
        if c['oi'].sum() and p['oi'].sum():
            r['E1_풋콜미결제비'] = p['oi'].sum() / c['oi'].sum()
            r['E1_콜벽거리%'] = (c.loc[c['oi'].idxmax(), 'K'] / S - 1) * 100
            r['E1_풋벽거리%'] = (p.loc[p['oi'].idxmax(), 'K'] / S - 1) * 100
            Ks = np.sort(f['K'].unique())
            pain = [((np.maximum(0, x - c['K']) * c['oi']).sum() + (np.maximum(0, p['K'] - x) * p['oi']).sum()) for x in Ks]
            r['E1_최대고통거리%'] = (Ks[int(np.argmin(pain))] / S - 1) * 100
            T = max(dte, 1) / 250
            px_ = f['settle'].where(f['settle'] > 0, f['close'])
            iv = implied_vol(f['cp'].values, S, f['K'].values, T, px_.values)
            ok = np.isfinite(iv)
            if ok.sum() >= 6:
                ivs = pd.Series(iv, index=f.index).fillna(np.nanmedian(iv))
                d1 = (np.log(S / f['K']) + 0.5 * ivs ** 2 * T) / (ivs * np.sqrt(T))
                gam = stats.norm.pdf(d1) / (S * ivs * np.sqrt(T))
                sign = np.where(f['cp'] == 'C', 1, -1)
                r['G1_감마노출추정'] = float((sign * gam * f['oi'] * S * S * 0.01).sum())
                atm = (f['K'] - S).abs()
                pc = f[ok & (f['cp'] == 'P')]; cc = f[ok & (f['cp'] == 'C')]
                if len(pc) and len(cc):
                    ivp = pd.Series(iv, index=f.index)
                    p95 = pc.iloc[(pc['K'] - S * 0.95).abs().argsort()[:1]].index; c105 = cc.iloc[(cc['K'] - S * 1.05).abs().argsort()[:1]].index
                    r['V2_스큐_풋95-콜105'] = float(ivp[p95].iloc[0] - ivp[c105].iloc[0]) * 100
        rows.append(r)
    if not rows: return None
    M = pd.DataFrame(rows).set_index('date').sort_index()
    if 'G1_감마노출추정' in M: M['G1_감마노출_z'] = z250(M['G1_감마노출추정']); M['G1_감마부호'] = np.sign(M['G1_감마노출추정'])
    return M


_K2 = None
def load_k200():
    global _K2
    if _K2 is not None: return _K2
    k = rd('k200_long')
    if k is None:
        _K2 = {}; return _K2
    k['date'] = ddate(k['날짜']); _K2 = dict(zip(k['date'], num(k['종가']))); return _K2


def second_thursday(y, m):
    d = pd.Timestamp(y, m, 1)
    th = [d + pd.Timedelta(days=i) for i in range(31) if (d + pd.Timedelta(days=i)).month == m and (d + pd.Timedelta(days=i)).weekday() == 3]
    return th[1]


def days_to_expiry(d, ym):
    try:
        e = second_thursday(int(ym[:4]), int(ym[4:6]))
        return int(np.busday_count(d.date(), e.date()))
    except Exception: return np.nan


# ------------------------------------------------------------------ 연관 분석(A8)
def lead_lag(X, T):
    rows = []
    r0 = T['ret1'].shift(1)   # 당일 수익률(t-1→t)
    for c in X.columns:
        s = X[c]
        for lag in range(-5, 6):
            # lag>0 : 지표가 lag일 앞섬(지표 t, 수익률 t+lag), lag<0 : 수익률이 앞섬
            j = pd.concat([s, r0.shift(-lag)], axis=1).dropna()
            if len(j) < 200: continue
            rho = stats.spearmanr(j.iloc[:, 0], j.iloc[:, 1])[0]
            rows.append({'지표': c, '지연': lag, '순위상관': round(rho, 4), 'n': len(j)})
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ 백테스트(A9)
def windows(idx):
    w = []; s = 0
    while s + TRAIN + 20 < len(idx):
        w.append((idx[s], idx[s + TRAIN - 1], idx[s + TRAIN], idx[min(s + TRAIN + TEST, len(idx)) - 1])); s += TEST
    return w


def load_regimes():
    r = pd.read_csv(os.path.join(DATA, 'regimes.csv'))
    r['start'] = pd.to_datetime(r['start']); r['end'] = pd.to_datetime(r['end'])
    return r


def regime_tag(idx):
    """백테스트 구간 나누기 — 승수(2012·2017) · 공매도 금지 · 위클리 이후."""
    t = pd.Series('보통', index=idx)
    t[idx < '2012-06-15'] = '승수10만(~2012.6)'
    t[(idx >= '2012-06-15') & (idx < '2017-03-27')] = '승수50만(2012.6~2017.3)'
    t[(idx >= '2017-03-27') & (idx < '2019-09-23')] = '승수25만(2017.3~2019.9)'
    t[idx >= '2019-09-23'] = '위클리 이후(2019.9~)'
    for _, r in load_regimes().iterrows():
        if str(r['regime']).startswith('short_ban'):
            e = r['end'] if pd.notna(r['end']) else pd.Timestamp('2100-01-01')
            t[(idx >= r['start']) & (idx <= e)] = '공매도금지'
    return t


def eval_pair(x, y, w):
    """한 지표 × 한 대상의 워크포워드. 방향은 학습 구간 순위상관 부호."""
    recs = []; tdays = []
    for a, b, c, d in w:
        tr = pd.concat([x[a:b], y[a:b]], axis=1).dropna(); te = pd.concat([x[c:d], y[c:d]], axis=1).dropna()
        if len(tr) < 250 or len(te) < 60 or tr.iloc[:, 0].nunique() < 3: continue
        rho_tr = stats.spearmanr(tr.iloc[:, 0], tr.iloc[:, 1])[0]
        if not np.isfinite(rho_tr) or rho_tr == 0: continue
        s = np.sign(rho_tr)
        lo, hi = tr.iloc[:, 0].quantile(0.2), tr.iloc[:, 0].quantile(0.8)
        rho_te = stats.spearmanr(te.iloc[:, 0], te.iloc[:, 1])[0]
        top = te[te.iloc[:, 0] >= hi].iloc[:, 1]; bot = te[te.iloc[:, 0] <= lo].iloc[:, 1]
        if s < 0: top, bot = bot, top
        recs.append({'start': c, 'ic': s * rho_te if np.isfinite(rho_te) else np.nan, 'n_top': len(top), 'n_bot': len(bot),
                     'spread': (top.mean() - bot.mean()) if len(top) >= 5 and len(bot) >= 5 else np.nan,
                     'top_mean': top.mean(), 'bot_mean': bot.mean(), 'base': te.iloc[:, 1].mean()})
        tdays.append(pd.DataFrame({'y': pd.concat([top, bot]), 'grp': [1] * len(top) + [0] * len(bot)}))
    if not recs: return None, None
    R = pd.DataFrame(recs); D = pd.concat(tdays)
    return R, D


def run_backtest(X, T):
    idx = T.dropna(subset=['dir']).index
    idx = idx[idx >= '2008-01-01']
    w = windows(idx)
    reg = regime_tag(idx)
    rows = []
    for tgt in TARGETS:
        y = T[tgt]
        for c in X.columns:
            if c == 'N1_야간등락' and tgt != 'gap': continue
            x = X[c].reindex(idx)
            if x.notna().sum() < TRAIN + 100: continue
            R, D = eval_pair(x, y.reindex(idx), w)
            if R is None: continue
            g1, g0 = D[D.grp == 1]['y'], D[D.grp == 0]['y']
            if len(g1) < 30 or len(g0) < 30: continue
            # 주 검정: 시험창마다 (상위−하위) 차이를 하나의 표본으로 보고 0과 비교 — 겹치는 기간(1주·20일 대상)의 자기상관에 덜 속는다
            sp = R['spread'].dropna()
            p = stats.ttest_1samp(sp, 0)[1] if len(sp) >= 5 and sp.std() > 0 else np.nan
            # 참고 검정: 날짜 단위(겹침 때문에 과대평가될 수 있음)
            if tgt in ('dir', 'crash', 'bottom'):
                tab = [[g1.sum(), len(g1) - g1.sum()], [g0.sum(), len(g0) - g0.sum()]]
                p_day = stats.fisher_exact(tab)[1]
            else:
                p_day = stats.ttest_ind(g1, g0, equal_var=False)[1]
            # 제도 구간별 부호 일관성
            regs = {}
            for rg in reg.unique():
                ii = reg[reg == rg].index
                j = pd.concat([x.reindex(ii), y.reindex(ii)], axis=1).dropna()
                if len(j) >= 120: regs[rg] = stats.spearmanr(j.iloc[:, 0], j.iloc[:, 1])[0]
            sgn = np.sign(R['ic'].mean())
            overall_sign = np.sign(stats.spearmanr(*pd.concat([x, y.reindex(idx)], axis=1).dropna().T.values)[0])
            consist = np.mean([np.sign(v) == overall_sign for v in regs.values()]) if regs else np.nan
            rows.append({'대상': tgt, '지표': c, '시험창': len(R), '시험일수': int(R['n_top'].sum() + R['n_bot'].sum()),
                         '평균IC(방향맞춤)': R['ic'].mean(), 'IC양수창비율': (R['ic'] > 0).mean(),
                         '상위평균': g1.mean(), '하위평균': g0.mean(), '차이': g1.mean() - g0.mean(), '기본값': R['base'].mean(),
                         '차이양수창비율': (R['spread'].dropna() > 0).mean(), 'p': p, 'p_날짜단위(참고)': p_day, '구간일관성': consist, '전체부호': overall_sign,
                         '구간별상관': json.dumps({k: round(v, 3) for k, v in regs.items()}, ensure_ascii=False), '시작': str(x.dropna().index.min().date())})
    S = pd.DataFrame(rows)
    if not len(S): return S
    S = S.sort_values('p')
    m = S['p'].notna(); pv = S.loc[m, 'p'].values; n = len(pv)
    order = np.argsort(pv); q = np.empty(n); prev = 1.0
    for rank, i in enumerate(order[::-1]):
        k = n - rank; prev = min(prev, pv[i] * n / k); q[i] = prev
    S.loc[m, 'q_BH'] = q
    def grade(r):
        ok = r['평균IC(방향맞춤)'] > 0 and r['차이'] > 0
        if ok and pd.notna(r['q_BH']) and r['q_BH'] <= 0.10 and r['차이양수창비율'] >= 0.7 and (r['구간일관성'] == 1 or pd.isna(r['구간일관성'])): return 'A'
        if ok and pd.notna(r['q_BH']) and r['q_BH'] <= 0.10 and r['차이양수창비율'] >= 0.6: return 'B'
        if ok and pd.notna(r['p']) and r['p'] <= 0.05: return 'C'
        return '탈락'
    S['등급'] = S.apply(grade, axis=1)
    return S


def permutation_check(X, T, S, n=300, seed=7):
    """상위 후보만: 지표 날짜를 섞어 같은 계산을 n번 — 무작위보다 나은지."""
    rng = np.random.default_rng(seed); rows = []
    idx = T.dropna(subset=['dir']).index; idx = idx[idx >= '2008-01-01']; w = windows(idx)
    for _, r in S[S['등급'].isin(['A', 'B'])].head(12).iterrows():
        x = X[r['지표']].reindex(idx); y = T[r['대상']].reindex(idx); obs = r['평균IC(방향맞춤)']; cnt = 0; k = 0
        for _ in range(n):
            xs = pd.Series(rng.permutation(x.values), index=idx)
            R, _ = eval_pair(xs, y, w)
            if R is None: continue
            k += 1; cnt += R['ic'].mean() >= obs
        rows.append({'대상': r['대상'], '지표': r['지표'], '관측IC': obs, '무작위초과확률': (cnt + 1) / (k + 1), '반복': k})
    return pd.DataFrame(rows)


def ensemble(X, T, S):
    """대상마다: 학습 750일 성적 상위 5개 지표 → 방향 맞춘 표준점수 평균 → 시험 250일 평가."""
    idx = T.dropna(subset=['dir']).index; idx = idx[idx >= '2008-01-01']; w = windows(idx); out = []; days = []
    cand = [c for c in X.columns if not c.startswith(('BASE_', 'DASH_'))]
    for tgt in TARGETS:
        y = T[tgt].reindex(idx)
        for a, b, c, d in w:
            sc = []
            for col in cand:
                if col == 'N1_야간등락' and tgt != 'gap': continue
                tr = pd.concat([X[col].reindex(idx)[a:b], y[a:b]], axis=1).dropna()
                if len(tr) < 250 or tr.iloc[:, 0].nunique() < 3: continue
                rho = stats.spearmanr(tr.iloc[:, 0], tr.iloc[:, 1])[0]
                if np.isfinite(rho): sc.append((abs(rho), col, np.sign(rho), tr.iloc[:, 0].mean(), tr.iloc[:, 0].std()))
            top5 = sorted(sc, reverse=True)[:5]
            if len(top5) < 3: continue
            zs = [s * (X[col].reindex(idx)[c:d] - mu) / (sd or 1) for _, col, s, mu, sd in top5]
            score = pd.concat(zs, axis=1).mean(axis=1, skipna=True)
            # 학습 구간 점수 분위
            ztr = pd.concat([s * (X[col].reindex(idx)[a:b] - mu) / (sd or 1) for _, col, s, mu, sd in top5], axis=1).mean(axis=1)
            hi, lo = ztr.quantile(0.8), ztr.quantile(0.2)
            te = pd.concat([score.rename('s'), y[c:d].rename('y'), T['ret1'].reindex(idx)[c:d].rename('r')], axis=1).dropna()
            if len(te) < 40: continue
            rho = stats.spearmanr(te['s'], te['y'])[0]
            out.append({'대상': tgt, '시험시작': str(c.date()), '고른지표': ' | '.join(col for _, col, *_ in top5), 'IC': rho,
                        '상위평균': te[te['s'] >= hi]['y'].mean(), '하위평균': te[te['s'] <= lo]['y'].mean(), '기본값': te['y'].mean(), 'n': len(te)})
            te['tgt'] = tgt; te['hi'] = te['s'] >= hi; te['lo'] = te['s'] <= lo; days.append(te)
    E = pd.DataFrame(out); D = pd.concat(days) if days else pd.DataFrame()
    return E, D


def strategy(D):
    """종가 방향(dir) 묶음 점수 상위 20%일 때만 다음 날 보유(비용 0.1%/왕복). 매수 후 보유와 비교."""
    if not len(D): return {}
    d = D[D['tgt'] == 'dir'].copy()
    if not len(d): return {}
    pos = d['hi'].astype(float); trades = pos.diff().abs().fillna(pos.iloc[0]); r = pos * d['r'] - trades * 0.0005
    eq = (1 + r).cumprod(); bh = (1 + d['r']).cumprod()
    mdd = lambda e: float((e / e.cummax() - 1).min())
    yrs = len(d) / 250
    return {'기간': f"{d.index.min().date()}~{d.index.max().date()}", '보유일비율': float(pos.mean()),
            '전략_연수익': float(eq.iloc[-1] ** (1 / yrs) - 1), '전략_최대손실': mdd(eq),
            '보유_연수익': float(bh.iloc[-1] ** (1 / yrs) - 1), '보유_최대손실': mdd(bh),
            '보유일_적중률': float((d.loc[d['hi'], 'y'] == 1).mean()), '전체_상승일비율': float(d['y'].mean())}


def event_study(X, T, px):
    """제도·사건 날짜와 급락일 상위 15개 전후 5일 수급."""
    ev = []
    named = [('2008-10-01', '공매도 금지 시작(2008)'), ('2010-11-11', '11·11 옵션쇼크'), ('2011-08-10', '공매도 금지 시작(2011)'),
             ('2013-12-12', '한맥투자증권 옵션 주문 사고'), ('2017-03-27', '승수 50만→25만'), ('2019-09-23', '위클리(목) 상장'),
             ('2020-03-16', '공매도 금지 시작(2020)'), ('2023-07-31', '조기개장·위클리(월)'), ('2023-11-06', '공매도 금지 시작(2023)'),
             ('2025-03-31', '공매도 재개'), ('2025-06-09', 'KRX 자체 야간 개시')]
    r = px['close'].pct_change()
    crashes = r[r.index >= '2006-01-01'].nsmallest(15)
    for d, v in crashes.items(): named.append((str(d.date()), f'급락일 코스피 {v * 100:.2f}%'))
    cols = [c for c in ('F_외국인_1d', 'F2_현선합계_5d', 'B1_시장베이시스율', 'P1_차익_1d', 'P1_비차익_1d', 'V1_VKOSPI', 'R1_PCR_5d', 'O1_외국인_콜-풋_1d') if c in X]
    for ds, name in named:
        d = pd.Timestamp(ds)
        if d not in px.index:
            nxt = px.index[px.index >= d]
            if not len(nxt): continue
            d = nxt[0]
        i = px.index.get_loc(d)
        row = {'날짜': str(d.date()), '사건': name, '코스피_당일%': round(r.iloc[i] * 100, 2),
               '코스피_전5일%': round((px['close'].iloc[i - 1] / px['close'].iloc[max(i - 6, 0)] - 1) * 100, 2) if i > 5 else np.nan,
               '코스피_후5일%': round((px['close'].iloc[min(i + 5, len(px) - 1)] / px['close'].iloc[i] - 1) * 100, 2) if i + 5 < len(px) else np.nan}
        for c in cols:
            s = X[c]
            pre = s[px.index[max(i - 5, 0)]:px.index[i - 1]] if i > 0 else s.iloc[0:0]
            row[f'{c}_전5일평균'] = round(pre.mean(), 3) if len(pre.dropna()) else np.nan
            row[f'{c}_당일'] = round(s.get(d, np.nan), 3) if pd.notna(s.get(d, np.nan)) else np.nan
        ev.append(row)
    return pd.DataFrame(ev)


def short_history(X, T):
    """자료가 짧아 워크포워드를 못 하는 지표(예: KRX 자체 야간 2025-06~) — 전체 표본 참고 결과(등급 없음)."""
    rows = []
    for c in X.columns:
        n = X[c].notna().sum()
        if n < 120 or n >= TRAIN + 100: continue
        for tgt in TARGETS:
            if c == 'N1_야간등락' and tgt != 'gap': continue
            j = pd.concat([X[c], T[tgt]], axis=1).dropna()
            if len(j) < 100: continue
            rho, p = stats.spearmanr(j.iloc[:, 0], j.iloc[:, 1])
            hi, lo = j.iloc[:, 0].quantile(0.8), j.iloc[:, 0].quantile(0.2)
            rows.append({'대상': tgt, '지표': c, 'n': len(j), '기간': f"{j.index.min().date()}~{j.index.max().date()}", '순위상관': rho, 'p(참고)': p,
                         '상위20%평균': j[j.iloc[:, 0] >= hi].iloc[:, 1].mean(), '하위20%평균': j[j.iloc[:, 0] <= lo].iloc[:, 1].mean(),
                         '부호일치율': float((np.sign(j.iloc[:, 0]) == np.sign(j.iloc[:, 1])).mean()) if tgt == 'gap' else np.nan})
    return pd.DataFrame(rows)


def main():
    px = load_price(); T = targets(px)
    X, note = build_indicators(px)
    X = X.reindex(px.index)
    cov = pd.DataFrame({'지표': X.columns, '시작': [str(X[c].dropna().index.min().date()) if X[c].notna().any() else '' for c in X.columns],
                        '끝': [str(X[c].dropna().index.max().date()) if X[c].notna().any() else '' for c in X.columns],
                        '값개수': [int(X[c].notna().sum()) for c in X.columns]})
    cov.to_csv(os.path.join(OUT, 'coverage.csv'), index=False, encoding='utf-8-sig')
    X.to_csv(os.path.join(OUT, 'indicators_daily.csv.gz'), encoding='utf-8')
    LL = lead_lag(X, T); LL.to_csv(os.path.join(OUT, 'lead_lag.csv'), index=False, encoding='utf-8-sig')
    S = run_backtest(X, T); S.to_csv(os.path.join(OUT, 'backtest_summary.csv'), index=False, encoding='utf-8-sig')
    P = permutation_check(X, T, S) if len(S) else pd.DataFrame(); P.to_csv(os.path.join(OUT, 'backtest_permutation.csv'), index=False, encoding='utf-8-sig')
    E, D = ensemble(X, T, S); E.to_csv(os.path.join(OUT, 'backtest_ensemble.csv'), index=False, encoding='utf-8-sig')
    ST = strategy(D)
    SH = short_history(X, T); SH.to_csv(os.path.join(OUT, 'backtest_short_history.csv'), index=False, encoding='utf-8-sig')
    EV = event_study(X, T, px); EV.to_csv(os.path.join(OUT, 'event_study.csv'), index=False, encoding='utf-8-sig')
    last = X.dropna(how='all').iloc[-1]
    latest = {'기준일': str(X.dropna(how='all').index[-1].date()), '값': {k: (None if pd.isna(v) else round(float(v), 4)) for k, v in last.items()},
              '묶음전략': ST, 'note': note, '등급수': S['등급'].value_counts().to_dict() if len(S) else {}}
    json.dump(latest, open(os.path.join(OUT, 'latest.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=str)
    print(json.dumps(latest['등급수'], ensure_ascii=False), ST)


if __name__ == '__main__':
    main()
