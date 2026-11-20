"""연구소(deriv/lab) 공통 — 자료 읽기, 만기 달력, 통계, 원장(시험 횟수·최종 구간 열람 횟수).

규칙(모든 에이전트 공통)
  - 개발 구간: 2015-01-01 ~ 2023-12-31. 탐색·학습·문턱 정하기는 이 구간 안에서만.
  - 잠금 구간: 2024-01-01 ~ 현재. A8(검증)만, 개발 구간 기준을 통과한 후보에 한해 연다. 열 때마다 원장에 횟수를 적고,
    통과 판정은 지금까지 연 횟수 전체로 보정한다(본페로니).
  - t일 지표는 t일 장 마감 뒤 알 수 있는 값. 매매는 t+1일 시가 진입(분봉 단계 전까지).
"""
import json
import os
import sys

import numpy as np
import pandas as pd
from scipy import stats

LAB = os.path.dirname(os.path.abspath(__file__))
DERIV = os.path.dirname(LAB)
REPO = os.path.dirname(DERIV)
DATA = os.path.join(DERIV, 'data')
sys.path.insert(0, DERIV)
sys.path.insert(0, os.path.join(DERIV, 'scan'))

DEV_END = pd.Timestamp('2023-12-31')
HOLD_START = pd.Timestamp('2024-01-01')
STATE = os.path.join(LAB, 'state')
os.makedirs(STATE, exist_ok=True)


def round_cfg():
    return json.load(open(os.path.join(LAB, 'round.json'), encoding='utf-8'))


def out_dir(sub=None):
    r = round_cfg()['round']
    d = os.path.join(LAB, 'out', f'round_{r:03d}', *( [sub] if sub else []))
    os.makedirs(d, exist_ok=True)
    return d


# ------------------------------------------------------------------ 가격
def k200_index():
    k = pd.read_csv(os.path.join(DATA, 'k200_long.csv')); k.columns = [c.lstrip('﻿') for c in k.columns]
    k['date'] = pd.to_datetime(k['날짜']); k = k.set_index('date').sort_index()
    out = pd.DataFrame({'open': k['시가'], 'high': k['고가'], 'low': k['저가'], 'close': k['종가']}).astype(float)
    return out[out.index >= '2007-01-01']


def prices():
    """K200(지수), K200F(연속 선물), KOSPI, ETF(069500, 있으면)."""
    import scan_data as SD
    import analyze as A
    P = {'K200': k200_index()}
    fp, night, roll = SD.k200f_price(); P['K200F'] = fp
    kp = A.load_price(); P['KOSPI'] = kp[['open', 'high', 'low', 'close']]
    ep = os.path.join(DATA, 'etf_069500.csv')
    if os.path.exists(ep):
        e = pd.read_csv(ep, parse_dates=['date']).set_index('date'); P['ETF'] = e[['open', 'high', 'low', 'close']]
    return P


def fetch_etf():
    try:
        import yfinance as yf
        d = yf.download('069500.KS', start='2014-01-01', progress=False, auto_adjust=False)
        if isinstance(d.columns, pd.MultiIndex): d.columns = d.columns.get_level_values(0)
        d = d.rename(columns=str.lower)[['open', 'high', 'low', 'close']]; d.index.name = 'date'
        d = d[d.index < pd.Timestamp.now().normalize()]
        d.to_csv(os.path.join(DATA, 'etf_069500.csv'))
    except Exception as e:
        print('ETF 받기 실패', e)


# ------------------------------------------------------------------ 옵션 행사가별
def chain(kind='m'):
    """kind m: 월물 가까운 2개(2015~), x: 월물 4개(있으면), wt/wm: 위클리."""
    f = {'m': 'opt_chain_daily', 'x': 'opt_chainx_daily', 'wt': 'opt_chainwt_daily', 'wm': 'opt_chainwm_daily'}[kind]
    p = os.path.join(DATA, f + '.csv.gz')
    if not os.path.exists(p): return None
    c = pd.read_csv(p)
    c['date'] = pd.to_datetime(c['날짜'])
    if 'ym' in c: c['ym'] = c['ym'].astype(str).str.slice(0, 6)
    return c.dropna(subset=['K'])


def chain_best():
    """월물 4개(x)는 수집이 끝나 가까운 2개(m)와 같은 기간을 덮을 때만 쓴다(수집 중 일부만 있는 x 로 지표가 짧아지는 것을 막음)."""
    m = chain('m'); x = chain('x')
    if x is not None and m is not None and len(x):
        if x['date'].min() <= m['date'].min() + pd.Timedelta(days=10) and x['date'].max() >= m['date'].max() - pd.Timedelta(days=10) \
                and x['date'].nunique() >= 0.97 * m['date'].nunique():
            return 'x', x
    return 'm', m


def second_thursday(y, m):
    d = pd.Timestamp(y, m, 1)
    return d + pd.Timedelta(days=(3 - d.weekday()) % 7 + 7)


def expiry_of_ym(ym, td):
    """월물 만기일(둘째 목요일, 휴장이면 앞 거래일)."""
    y, m = int(str(ym)[:4]), int(str(ym)[4:6])
    st = second_thursday(y, m)
    if st > td[-1]: return st          # 자료 끝보다 뒤 만기는 달력 날짜 그대로(휴장 조정은 확인 불가)
    i = td.searchsorted(st, side='right') - 1
    return td[i] if i >= 0 else st


def tdays_between(d, e, td):
    """d 다음 거래일부터 e 까지 거래일 수(자료 끝 뒤는 평일로 셈)."""
    n = int(((td > d) & (td <= e)).sum())
    if e > td[-1]: n += len(pd.bdate_range(td[-1] + pd.Timedelta(days=1), e))
    return n


# ------------------------------------------------------------------ 투자자별
def flows():
    """외국인·기관·개인: 코스피200 선물(조원), 옵션 콜·풋 순매수(조원, 프리미엄), 코스피 현물(조원)."""
    import expiry_study as ES
    import expiry_foreign as EF
    F = pd.DataFrame({
        'fut_for': ES.FUT['외국인'], 'fut_inst': ES.FUT['기관'], 'fut_ind': ES.FUT['개인'], 'fut_fi': ES.FUT['금융투자'],
        'call_for': ES.flows_detail('OPK2I', 'C')['외국인'], 'put_for': ES.flows_detail('OPK2I', 'P')['외국인'],
        'call_ind': ES.flows_detail('OPK2I', 'C')['개인'], 'put_ind': ES.flows_detail('OPK2I', 'P')['개인'],
    }) / 1e12
    F['cash_for'] = EF.CF.reindex(F.index.union(EF.CF.index)) / 1e12 if True else np.nan
    return F.sort_index()


# ------------------------------------------------------------------ 통계
def wilson(k, n, z=1.645):
    if n == 0: return (np.nan, np.nan)
    p = k / n; d = 1 + z * z / n; c = p + z * z / (2 * n); h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - h) / d, (c + h) / d)


def binom_p(k, n, p0=0.5):
    return stats.binomtest(int(k), int(n), p0, alternative='greater').pvalue if n else np.nan


def thin(dates, h, td):
    """겹치지 않는 신호만: 앞 신호의 보유 기간(h 거래일) 안에 든 신호는 버림."""
    pos = np.searchsorted(td.values, pd.DatetimeIndex(dates).values)
    keep, last = [], -10 ** 9
    for d, p in zip(dates, pos):
        if p - last >= h: keep.append(d); last = p
    return keep


# ------------------------------------------------------------------ 원장
def ledger():
    p = os.path.join(STATE, 'ledger.json')
    return json.load(open(p, encoding='utf-8')) if os.path.exists(p) else {'trials_total': 0, 'holdout_peeks': 0, 'rounds': []}


def save_ledger(L):
    json.dump(L, open(os.path.join(STATE, 'ledger.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


# ------------------------------------------------------------------ 후보 신호 형식(A3·A4·A5·A6·A7 → A8)
# 후보 하나 = dict(id, agent, desc, direction(+1 오름/−1 내림), trades=DataFrame[signal, exit], dev_note)
#   signal = 신호를 아는 날(그날 장 마감 뒤), 진입 = 다음 거래일 시가, 청산 = exit 날 종가.
#   잠금 구간(2024~)의 신호 날짜도 같은 규칙으로 만들어 넘기되, 그 구간 결과는 A8 만 계산한다.
def save_candidates(agent, cands):
    import pickle
    d = out_dir(agent)
    pickle.dump(cands, open(os.path.join(d, 'candidates.pkl'), 'wb'))
    pd.DataFrame([{k: v for k, v in c.items() if k != 'trades'} | {'n_signals': len(c['trades'])} for c in cands]).to_csv(
        os.path.join(d, 'candidates.csv'), index=False, encoding='utf-8')


def trade_returns(trades, px):
    """trades[signal, exit] → 다음 날 시가 진입, exit 날 종가 청산 수익(%). 자료 밖이면 빈칸."""
    td = px.index
    out = []
    for s, e in zip(trades['signal'], trades['exit']):
        i = td.searchsorted(s, side='right')
        if i >= len(td) or e not in td or td[i] > e: out.append(np.nan); continue
        out.append((px['close'].loc[e] / px['open'].iloc[i] - 1) * 100)
    return np.array(out)


def exit_after(td, s, h):
    i = td.searchsorted(s, side='right') + h - 1
    return td[i] if i < len(td) else pd.NaT
