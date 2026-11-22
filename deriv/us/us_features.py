"""미국 자료 → 한국 거래일에 맞춘 지표(앞을 보지 않게).

시각 규칙: 한국 t일 신호는 t일 장 마감 뒤 정하고 다음 거래일(n) 09:00 시가에 진입한다.
  뉴욕 날짜 D 의 종가는 한국 D+1일 05~07시에 나오므로, '뉴욕 날짜 ≤ n-1일'인 값까지만 쓴다(n 개장 전에 이미 나온 값).
  Cboe 풋콜 비율·야후 환율은 한국 개장 전에 받을 수 있는지 불확실해 한 거래일 더 늦춘다. CFTC 는 화요일 기준 → 금요일 공개(휴일 주는 월요일)라 기준일+6일 뒤부터 쓴다.
  미국 정부 업무 정지로 공개가 밀린 기간(2013-10, 2018-12~2019-02, 2025-09-30~2026-01-13 기준분)의 CFTC 값은 비운다(공개일 확인 불가).
백분위는 직전 756거래일(3년, 최소 252일) 안에서 그날 값의 순위 — 그 시점에 알 수 있던 값만 쓴다.
"""
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__)); DERIV = os.path.dirname(ROOT)
DATA = os.path.join(ROOT, 'data')
sys.path.insert(0, os.path.join(DERIV, 'lab')); sys.path.insert(0, DERIV)

NAMES = {
    'es_r1': 'S&P500 선물 1일 등락', 'es_r5': 'S&P500 선물 5일 등락', 'es_r20': 'S&P500 선물 20일 등락', 'nq_r1': '나스닥100 선물 1일 등락', 'nq_r5': '나스닥100 선물 5일 등락',
    'sox_r1': '필라델피아 반도체 1일 등락', 'sox_r5': '필라델피아 반도체 5일 등락', 'sox_r20': '필라델피아 반도체 20일 등락', 'ewy_r1': 'EWY 1일 등락',
    'ewy_gap': 'EWY 1일 등락 − 코스피200 당일 등락', 'krw_r1': '원달러 1일 등락', 'krw_r5': '원달러 5일 등락', 'tnx_d5': '미국 10년 금리 5일 변화', 'dxy_r5': '달러 인덱스 5일 등락',
    'hyg_r5': '하이일드 채권 ETF 5일 등락', 'nq_es5': '나스닥−S&P 5일 등락 차', 'sox_es5': '반도체−S&P 5일 등락 차', 'es_dd60': 'S&P500 선물 60일 고점 대비', 'es_ma200': 'S&P500 선물 200일선 대비',
    'vix': 'VIX', 'vix_c1': 'VIX 1일 변화율', 'vix_c5': 'VIX 5일 변화율', 'vix_ts': 'VIX ÷ VIX 3개월', 'vix9_ts': 'VIX 9일 ÷ VIX', 'vvix': 'VVIX', 'skew': 'SKEW', 'vrp': 'VIX − 실현 변동성(20일)',
    'vkospi': 'VKOSPI', 'vk_vix': 'VKOSPI − VIX', 'vk_c5': 'VKOSPI 5일 변화율',
    'pcr_eq': '미국 주식 옵션 풋콜 비율', 'pcr_tot': '미국 전체 옵션 풋콜 비율', 'pcr_idx': '미국 지수 옵션 풋콜 비율', 'pcr_eq5': '미국 주식 풋콜 비율 5일 평균', 'k_pcr': '코스피200 옵션 풋콜 비율',
    'es_am': 'S&P 선물 자산운용 순포지션(미결제 대비)', 'es_lev': 'S&P 선물 레버리지 펀드 순포지션', 'es_dl': 'S&P 선물 딜러 순포지션', 'es_am_d4': 'S&P 자산운용 순포지션 4주 변화', 'es_lev_d4': 'S&P 레버리지 펀드 순포지션 4주 변화',
    'nq_am': '나스닥 선물 자산운용 순포지션', 'nq_lev': '나스닥 선물 레버리지 펀드 순포지션', 'nq_lev_d4': '나스닥 레버리지 펀드 순포지션 4주 변화', 'vx_lev': 'VIX 선물 레버리지 펀드 순포지션',
    'for_fut3': '외국인 코스피200 선물 3일 순매수', 'for_fut10': '외국인 코스피200 선물 10일 순매수', 'k2_r1': '코스피200 당일 등락', 'k2_r5': '코스피200 5일 등락',
}
GROUP = {'가격': ['es_r1', 'es_r5', 'es_r20', 'nq_r1', 'nq_r5', 'sox_r1', 'sox_r5', 'sox_r20', 'ewy_r1', 'ewy_gap', 'krw_r1', 'krw_r5', 'tnx_d5', 'dxy_r5', 'hyg_r5', 'nq_es5', 'sox_es5', 'es_dd60', 'es_ma200'],
         '변동성': ['vix', 'vix_c1', 'vix_c5', 'vix_ts', 'vix9_ts', 'vvix', 'skew', 'vrp', 'vkospi', 'vk_vix', 'vk_c5'],
         '옵션': ['pcr_eq', 'pcr_tot', 'pcr_idx', 'pcr_eq5', 'k_pcr'],
         '포지션': ['es_am', 'es_lev', 'es_dl', 'es_am_d4', 'es_lev_d4', 'nq_am', 'nq_lev', 'nq_lev_d4', 'vx_lev', 'for_fut3', 'for_fut10']}
FRESH = {'es_r1', 'nq_r1', 'sox_r1', 'ewy_r1', 'ewy_gap', 'krw_r1', 'vix_c1'}   # 하루 등락은 새 미국 장이 있었던 날에만 신호
KOREA = {'vkospi', 'vk_c5', 'k_pcr', 'for_fut3', 'for_fut10', 'k2_r1', 'k2_r5'}


def pct_rank(s, win=756, minp=252):
    return s.rolling(win, min_periods=minp).apply(lambda x: (x[:-1] <= x[-1]).mean() if len(x) > 1 else np.nan, raw=True)


def us_native():
    o = pd.read_csv(os.path.join(DATA, 'us_ohlc.csv.gz'), parse_dates=['date'])
    C = o.pivot_table(index='date', columns='ticker', values='close').sort_index()
    ci = pd.read_csv(os.path.join(DATA, 'cboe_index.csv.gz'), parse_dates=['date']).pivot_table(index='date', columns='sym', values='close')
    cal = C['^GSPC'].dropna().index   # 뉴욕 거래일
    C = C.reindex(cal); ci = ci.reindex(cal)
    r = lambda t, n: (C[t] / C[t].shift(n) - 1) * 100
    U = pd.DataFrame(index=cal)
    es, nq = C['ES=F'].ffill(limit=2), C['NQ=F'].ffill(limit=2)
    U['es_r1'] = (es / es.shift(1) - 1) * 100; U['es_r5'] = (es / es.shift(5) - 1) * 100; U['es_r20'] = (es / es.shift(20) - 1) * 100
    U['nq_r1'] = (nq / nq.shift(1) - 1) * 100; U['nq_r5'] = (nq / nq.shift(5) - 1) * 100
    U['sox_r1'] = r('^SOX', 1); U['sox_r5'] = r('^SOX', 5); U['sox_r20'] = r('^SOX', 20); U['ewy_r1'] = r('EWY', 1)
    kr = C['KRW=X'].ffill(limit=3); U['krw_r1'] = (kr / kr.shift(1) - 1) * 100; U['krw_r5'] = (kr / kr.shift(5) - 1) * 100
    U['krw_r1'] = U['krw_r1'].shift(1); U['krw_r5'] = U['krw_r5'].shift(1)   # 야후 환율 일봉 마감 시각이 한국 개장과 겹칠 수 있어 하루 늦춤
    U['tnx_d5'] = C['^TNX'] - C['^TNX'].shift(5); U['dxy_r5'] = r('DX-Y.NYB', 5).shift(1); U['hyg_r5'] = r('HYG', 5)
    U['nq_es5'] = U['nq_r5'] - U['es_r5']; U['sox_es5'] = U['sox_r5'] - U['es_r5']
    U['es_dd60'] = (es / es.rolling(60).max() - 1) * 100; U['es_ma200'] = (es / es.rolling(200).mean() - 1) * 100
    vix = ci['VIX'].combine_first(C['^VIX']); v3 = ci['VIX3M'].combine_first(C['^VIX3M']); v9 = ci['VIX9D'].combine_first(C['^VIX9D'])
    U['vix'] = vix; U['vix_c1'] = (vix / vix.shift(1) - 1) * 100; U['vix_c5'] = (vix / vix.shift(5) - 1) * 100
    U['vix_ts'] = vix / v3; U['vix9_ts'] = v9 / vix; U['vvix'] = ci['VVIX'].combine_first(C['^VVIX']); U['skew'] = ci['SKEW'].combine_first(C['^SKEW'])
    rv = np.log(C['^GSPC']).diff().rolling(20).std() * np.sqrt(252) * 100; U['vrp'] = vix - rv
    # 풋콜 비율: 옛 보관 파일(~2019-10-04) + 일별 통계(있으면)
    pa = pd.read_csv(os.path.join(DATA, 'cboe_pcr_archive.csv.gz'), parse_dates=['date']).pivot_table(index='date', columns='kind', values='pcr')
    P = pd.DataFrame({'pcr_eq': pa.get('equitypc'), 'pcr_tot': pa.get('totalpc'), 'pcr_idx': pa.get('indexpc')})
    pd_ = os.path.join(DATA, 'cboe_pcr_daily.csv.gz')
    if os.path.exists(pd_):
        d = pd.read_csv(pd_, parse_dates=['date']); d['name'] = d['name'].astype(str).str.upper()
        m = {'EQUITY PUT/CALL RATIO': 'pcr_eq', 'TOTAL PUT/CALL RATIO': 'pcr_tot', 'INDEX PUT/CALL RATIO': 'pcr_idx'}
        d = d[d['name'].isin(m)].assign(k=lambda x: x['name'].map(m)).pivot_table(index='date', columns='k', values='value')
        P = P.combine_first(d)
    P = P.reindex(cal)
    for c in ('pcr_eq', 'pcr_tot', 'pcr_idx'): U[c] = P[c] if c in P else np.nan
    for c in ('pcr_eq', 'pcr_tot', 'pcr_idx'): U[c] = U[c].shift(1)   # Cboe 파일이 한국 개장 뒤(11~14시)에 올라와 실제로는 하루 늦게 받음 → 한 거래일 늦춤
    U['pcr_eq5'] = U['pcr_eq'].rolling(5, min_periods=4).mean()
    # CFTC: 기준일 + 6일 뒤부터
    t = pd.read_csv(os.path.join(DATA, 'cftc_tff.csv.gz'), parse_dates=['date'])
    for c in t.columns:
        if c not in ('date', 'cftc_contract_market_code', 'market_and_exchange_names'): t[c] = pd.to_numeric(t[c], errors='coerce')
    bad = [('2013-09-24', '2013-10-29'), ('2018-12-18', '2019-02-26'), ('2025-09-30', '2026-01-13')]
    for code, pre in (('13874A', 'es'), ('209742', 'nq'), ('1170E1', 'vx')):
        x = t[t['cftc_contract_market_code'].astype(str) == code].drop_duplicates('date').set_index('date').sort_index()
        oi = x['open_interest_all']
        W = pd.DataFrame({'am': (x['asset_mgr_positions_long'] - x['asset_mgr_positions_short']) / oi * 100,
                          'lev': (x['lev_money_positions_long'] - x['lev_money_positions_short']) / oi * 100,
                          'dl': (x['dealer_positions_long_all'] - x['dealer_positions_short_all']) / oi * 100})
        W['am_d4'] = W['am'] - W['am'].shift(4); W['lev_d4'] = W['lev'] - W['lev'].shift(4)
        for a, b in bad: W[(W.index >= a) & (W.index <= b)] = np.nan
        W.index = W.index + pd.Timedelta(days=6)
        W = W.reindex(W.index.union(cal)).ffill(limit=12).reindex(cal)
        for c in W:
            if f'{pre}_{c}' in NAMES: U[f'{pre}_{c}'] = W[c]
    return U, C, ci


def build():
    """한국 거래일 기준 지표 F(값), Q(백분위), fresh(새 미국 장 여부), 원자료 묶음."""
    import lab_common as L
    k2 = L.k200_index(); td = k2.index
    U, C, ci = us_native()
    UQ = U.apply(pct_rank)
    nxt = pd.Series(list(td[1:]) + [td[-1] + pd.Timedelta(days=1)], index=td)
    cut = nxt - pd.Timedelta(days=1)                      # 이 날짜(뉴욕)까지의 값은 다음 한국 개장 전에 나와 있음
    pos = U.index.searchsorted(cut.values, side='right') - 1
    ok = pos >= 0
    F = pd.DataFrame(U.values[np.clip(pos, 0, None)], index=td, columns=U.columns); F[~ok] = np.nan
    Q = pd.DataFrame(UQ.values[np.clip(pos, 0, None)], index=td, columns=U.columns); Q[~ok] = np.nan
    usd = pd.Series(U.index[np.clip(pos, 0, None)], index=td)
    stale = (cut.values - usd.values) > np.timedelta64(4, 'D')
    F[stale] = np.nan; Q[stale] = np.nan
    fresh = pd.Series(usd.values >= td.values, index=td)   # 한국 t일 장 마감 뒤에 끝난 미국 장이 있음
    # 한국 쪽
    K = pd.DataFrame(index=td)
    K['k2_r1'] = (k2['close'] / k2['close'].shift(1) - 1) * 100; K['k2_r5'] = (k2['close'] / k2['close'].shift(5) - 1) * 100
    iv = pd.read_csv(os.path.join(DERIV, 'data', 'iv_daily.csv')); iv.columns = [c.lstrip('﻿') for c in iv.columns]
    vk = pd.Series(pd.to_numeric(iv['REP_IMP_VOLT'], errors='coerce').values, index=pd.to_datetime(iv['BAS_DD'])).sort_index()
    vk = vk[~vk.index.duplicated()].reindex(td)
    K['vkospi'] = vk; K['vk_c5'] = (vk / vk.shift(5) - 1) * 100
    pc = pd.read_csv(os.path.join(DERIV, 'data', 'pcr_daily.csv')); pc.columns = [c.lstrip('﻿') for c in pc.columns]
    kp = pd.Series(pd.to_numeric(pc['PCRATIO'], errors='coerce').values, index=pd.to_datetime(pc['TRD_DD'])).sort_index()
    K['k_pcr'] = kp[~kp.index.duplicated()].reindex(td)
    try:
        fl = L.flows()['fut_for'].reindex(td)
        K['for_fut3'] = fl.rolling(3, min_periods=3).sum(); K['for_fut10'] = fl.rolling(10, min_periods=10).sum(); K['for_fut1'] = fl
    except Exception as e:
        print('투자자별 자료 실패', e); K['for_fut3'] = K['for_fut10'] = K['for_fut1'] = np.nan
    KQ = K.apply(pct_rank)
    for c in K: F[c] = K[c]; Q[c] = KQ[c]
    F['ewy_gap'] = F['ewy_r1'] - F['k2_r1']; F['vk_vix'] = F['vkospi'] - F['vix']
    Q['ewy_gap'] = pct_rank(F['ewy_gap']); Q['vk_vix'] = pct_rank(F['vk_vix'])
    for c in FRESH: F.loc[~fresh, c] = np.nan; Q.loc[~fresh, c] = np.nan
    return {'F': F, 'Q': Q, 'fresh': fresh, 'usd': usd, 'k2': k2, 'td': td, 'U': U, 'C': C, 'ci': ci}
