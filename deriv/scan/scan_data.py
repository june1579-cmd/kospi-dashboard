"""기간별 예측 가능성 탐색 — 자료 만들기(일별). GitHub Actions 에서 돈다(KRX 로그인 없음, 저장소 자료만 씀).

입력(저장소에 이미 있는 것 전부)
  deriv/out/indicators_daily.csv.gz   1·2·3차 지표 120개(투자자별 선물·옵션, 베이시스, IV, PCR, 옵션 행사가별, 2차 국내, 3차 해외)
  pkg/history/*                        코스피 일별(2006~), 코스피 투자자별 현물(2006~), 금투협 신용·예탁금·미수·반대매매(2006~)
  pkg/datasets/market_daily·fx_daily·night_fut  VKOSPI·원달러(2015~), KRX 야간선물(2025-06~)
  deriv/data/fut_front_daily.csv       코스피200 선물 최근월물 주간·야간(유렉스 연계 2009-11~2020-12)
  deriv/data/kospi_long.csv            코스피 1996~
시각 규칙(미래를 보지 않음)
  t일 지표는 t일 장 마감 뒤(투자자별 18시, 미국 종가 t+1일 06시)까지 알 수 있는 값. 금투협 신용·반대매매는 하루 늦게 공표되므로 하루 밀어 씀.
  맞힐 대상은 t+1일 시가에 들어가 t+h일 종가까지(현물·선물 모두 실제로 체결 가능한 구간).
출력: deriv/scan/work/daily.pkl  {'X': 지표 표, 'P': {'KOSPI': 가격표, 'K200F': 가격표}, 'meta': ...}
"""
import os
import pickle
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DERIV = os.path.dirname(HERE)
REPO = os.path.dirname(DERIV)
sys.path.insert(0, DERIV)
import analyze as A  # noqa: E402

WORK = os.path.join(HERE, 'work')
os.makedirs(WORK, exist_ok=True)


def num(s):
    return pd.to_numeric(s.astype(str).str.replace(',', '').replace({'-': None, '': None, 'nan': None}), errors='coerce')


def kospi_price():
    px = A.load_price()[['open', 'high', 'low', 'close', 'value']]
    return px[px.index >= '2006-01-01']


def k200f_price():
    """최근월물 주간 시세를 이어 붙인 연속 선물(비율 조정). 월물이 바뀌는 날은 코스피200 지수 등락으로 대신 이음."""
    fr = A.rd('fut_front_daily'); s = fr['TRD_DD'].astype(str)
    fr['d'] = pd.to_datetime(s.str[:10]); fr['ses'] = np.where(s.str.contains('야간'), 'N', 'D')
    for c in ('TDD_OPNPRC', 'TDD_HGPRC', 'TDD_LWPRC', 'TDD_CLSPRC'): fr[c] = num(fr[c])
    D = fr[fr.ses == 'D'].drop_duplicates('d', keep='last').set_index('d').sort_index()
    k2 = pd.read_csv(os.path.join(DERIV, 'data', 'k200_long.csv'))
    k2.columns = [c.lstrip('﻿') for c in k2.columns]
    k2 = k2.assign(d=pd.to_datetime(k2['날짜'])).set_index('d').sort_index()
    kc = num(k2['종가']).reindex(D.index)
    roll = D['ISU_NM'] != D['ISU_NM'].shift(1)
    r = D['TDD_CLSPRC'].pct_change()
    r[roll] = kc.pct_change()[roll]            # 월물 교체일: 지수 등락으로 대신
    adj = (1 + r.fillna(0)).cumprod()
    f = adj / D['TDD_CLSPRC']                  # 그날 원래 가격 → 조정 가격 비율
    out = pd.DataFrame({'open': D['TDD_OPNPRC'] * f, 'high': D['TDD_HGPRC'] * f, 'low': D['TDD_LWPRC'] * f, 'close': adj * 1.0})
    # 시가: 월물 교체일 다음 날 시가는 새 월물 기준이라 비율로 맞춤(같은 날 종가와 같은 월물이므로 f 로 충분)
    out = out * (D['TDD_CLSPRC'].iloc[0])      # 첫날 가격 수준으로
    N = fr[fr.ses == 'N'].drop_duplicates('d', keep='last').set_index('d').sort_index()
    night = pd.Series(np.nan, index=D.index)
    same = N['ISU_NM'].reindex(D.index) == D['ISU_NM']
    night[same] = (N['TDD_CLSPRC'].reindex(D.index) / D['TDD_CLSPRC'] - 1)[same] * 100   # d일 저녁 유렉스 연계 야간(다음 날 시가 전에 앎)
    return out, night, roll


def history_extra(idx):
    """금투협 신용·예탁금·미수·반대매매(2006~) + 코스피 현물 투자자별(2006~) + VKOSPI·원달러."""
    H = os.path.join(REPO, 'pkg', 'history')
    cr = pd.read_csv(os.path.join(H, '01_금투협_신용공여잔고.csv')); cr.columns = [c.lstrip('﻿') for c in cr.columns]
    cr = cr.assign(d=pd.to_datetime(cr['일자'].astype(str))).set_index('d').sort_index()
    fu = pd.read_csv(os.path.join(H, '01_금투협_증시자금추이.csv')); fu.columns = [c.lstrip('﻿') for c in fu.columns]
    fu = fu.assign(d=pd.to_datetime(fu['일자'].astype(str))).set_index('d').sort_index()
    E = pd.DataFrame(index=idx)
    credit = cr['TMPV2'].reindex(idx).ffill(limit=3) / 1e6          # 조원(백만원 → 조)
    dep = fu['TMPV2'].reindex(idx).ffill(limit=3) / 1e6
    misu = fu['TMPV5'].reindex(idx).ffill(limit=3) / 1e6
    liq = fu['TMPV6'].reindex(idx).ffill(limit=3) / 1e2               # 억원(백만원 → 억)
    ratio = fu['TMPV7'].reindex(idx).ffill(limit=3)
    rp = fu['TMPV4'].reindex(idx).ffill(limit=3) / 1e6
    lag = lambda s: s.shift(1)                                         # 금투협은 하루 늦게 공표
    E['C_신용잔고_5d%'] = lag(credit.pct_change(5) * 100); E['C_신용잔고_20d%'] = lag(credit.pct_change(20) * 100)
    E['C_신용/예탁금%'] = lag(credit / dep * 100); E['C_신용/예탁금_20d변화'] = E['C_신용/예탁금%'].diff(20)
    E['C_예탁금_5d%'] = lag(dep.pct_change(5) * 100); E['C_예탁금_20d%'] = lag(dep.pct_change(20) * 100)
    E['C_미수금_5d%'] = lag(misu.pct_change(5) * 100)
    E['C_반대매매_억'] = lag(liq); E['C_반대매매_5d평균'] = lag(liq.rolling(5).mean()); E['C_반대매매비중%'] = lag(ratio)
    E['C_RP_20d%'] = lag(rp.pct_change(20) * 100)
    E['C_신용_1년고점대비%'] = lag((credit / credit.rolling(250, min_periods=120).max() - 1) * 100)
    # 코스피 현물 투자자별(조원)
    cf = pd.read_csv(os.path.join(H, '01_코스피_투자자별_순매수_거래대금.csv')); cf.columns = [c.lstrip('﻿') for c in cf.columns]
    cf = cf.assign(d=pd.to_datetime(cf['날짜'])).set_index('d').sort_index()
    fd = os.path.join(REPO, 'pkg', 'datasets', 'flows_daily.csv')
    if os.path.exists(fd):
        f2 = pd.read_csv(fd, parse_dates=['date']).set_index('date')
        for k_new, k_old in (('foreign_jo', '외국인합계'), ('inst_jo', '기관합계'), ('indiv_jo', '개인')):
            add = f2[k_new] * 1e12
            cf[k_old] = pd.concat([cf[k_old], add[~add.index.isin(cf.index)]]).sort_index()
            cf = cf.reindex(cf.index.union(add.index)); cf[k_old] = cf[k_old].fillna(add)
    for k, nm in (('외국인합계', '외국인'), ('기관합계', '기관'), ('개인', '개인')):
        s = num(cf[k]).reindex(idx) / 1e12
        for w in (1, 5, 20, 60):
            E[f'S_{nm}현물_{w}d'] = s.rolling(w, min_periods=max(1, w // 2)).sum()
    mk = pd.read_csv(os.path.join(REPO, 'pkg', 'datasets', 'market_daily.csv'), parse_dates=['date']).set_index('date')
    E['M_VKOSPI'] = mk['vkospi'].reindex(idx); E['M_VKOSPI_20d변화'] = E['M_VKOSPI'].diff(20)
    fx = pd.read_csv(os.path.join(REPO, 'pkg', 'datasets', 'fx_daily.csv'), parse_dates=['date']).set_index('date')['usdkrw'].reindex(idx).ffill(limit=3)
    E['M_원달러_20d%'] = fx.pct_change(20, fill_method=None) * 100
    return E


def price_features(px, tag):
    """가격만으로 만든 지표(그날 종가까지)."""
    c, o, h, l = px['close'], px['open'], px['high'], px['low']
    F = pd.DataFrame(index=px.index)
    r1 = c.pct_change()
    for w in (1, 2, 3, 5, 10, 20, 60, 120, 250):
        F[f'{tag}_등락_{w}d'] = c.pct_change(w) * 100
    for w in (5, 20, 60, 120, 200):
        F[f'{tag}_이평괴리_{w}'] = (c / c.rolling(w).mean() - 1) * 100
    for w in (5, 20, 60):
        F[f'{tag}_변동성_{w}d'] = r1.rolling(w).std() * np.sqrt(250) * 100
    F[f'{tag}_변동성비_5/60'] = F[f'{tag}_변동성_5d'] / F[f'{tag}_변동성_60d']
    F[f'{tag}_고점대비_250d'] = (c / c.rolling(250, min_periods=60).max() - 1) * 100
    F[f'{tag}_저점대비_250d'] = (c / c.rolling(250, min_periods=60).min() - 1) * 100
    F[f'{tag}_범위위치_20d'] = (c - l.rolling(20).min()) / (h.rolling(20).max() - l.rolling(20).min())
    F[f'{tag}_상승일수_10d'] = (r1 > 0).rolling(10).sum()
    d = c.diff(); up = d.clip(lower=0).rolling(14).mean(); dn = (-d.clip(upper=0)).rolling(14).mean()
    F[f'{tag}_RSI14'] = 100 - 100 / (1 + up / dn)
    F[f'{tag}_오늘갭%'] = (o / c.shift(1) - 1) * 100
    F[f'{tag}_장중%'] = (c / o - 1) * 100
    F[f'{tag}_꼬리위치'] = (c - l) / (h - l)
    if 'value' in px:
        F[f'{tag}_거래대금_20d비'] = px['value'] / px['value'].rolling(60).mean()
    return F


def calendar_features(idx):
    F = pd.DataFrame(index=idx)
    F['K_요일'] = idx.dayofweek
    F['K_월'] = idx.month
    sec = pd.Series(idx, index=idx).apply(lambda d: (pd.Timestamp(d.year, d.month, 1) + pd.Timedelta(days=(3 - pd.Timestamp(d.year, d.month, 1).weekday()) % 7 + 7)))
    days_to = (sec - pd.Series(idx, index=idx)).dt.days
    F['K_만기까지일수'] = days_to.where(days_to >= 0, np.nan)
    F['K_만기주'] = ((days_to >= 0) & (days_to <= 6)).astype(int)
    F['K_분기만기주'] = (F['K_만기주'].astype(bool) & idx.month.isin([3, 6, 9, 12])).astype(int)
    m = pd.Series(idx.to_period('M'), index=idx)
    F['K_월말3일'] = (m != m.shift(-3)).astype(int)
    F['K_월초3일'] = (m != m.shift(3)).astype(int)
    return F


def main():
    kp = kospi_price()
    fp, night_eurex, roll = k200f_price()
    idx = kp.index[kp.index >= '2007-01-01']
    X = pd.read_csv(os.path.join(DERIV, 'out', 'indicators_daily.csv.gz'), index_col=0, parse_dates=True)
    X = X.drop(columns=[c for c in X.columns if c.startswith('DASH_')])   # 대시보드 모델 출력(전 기간 학습값일 수 있음) 제외
    X = X.reindex(idx)
    nt = night_eurex.reindex(idx)
    if 'N1_야간등락' in X: nt = nt.fillna(X['N1_야간등락'])
    X['NT_야간선물등락'] = nt
    X = X.drop(columns=['N1_야간등락'], errors='ignore')
    X = X.join(history_extra(idx)).join(price_features(kp, 'PK').reindex(idx)).join(price_features(fp, 'PF').reindex(idx)).join(calendar_features(idx))
    X['PF_베이시스%'] = (fp['close'].reindex(idx) / kp['close'].reindex(idx))   # 조정 가격이라 수준 대신 변화만 의미
    X['PF_베이시스%'] = X['PF_베이시스%'].pct_change(5) * 100
    X = X.replace([np.inf, -np.inf], np.nan)
    keep = [c for c in X.columns if X[c].notna().sum() >= 400]
    X = X[keep]
    P = {'KOSPI': kp.reindex(idx), 'K200F': fp.reindex(idx)}
    meta = {'start': str(idx.min().date()), 'end': str(idx.max().date()), 'n_features': X.shape[1],
            'coverage': {c: [str(X[c].first_valid_index().date()), int(X[c].notna().sum())] for c in X.columns}}
    with open(os.path.join(WORK, 'daily.pkl'), 'wb') as f: pickle.dump({'X': X, 'P': P, 'meta': meta}, f)
    print(meta['start'], meta['end'], X.shape)
    pd.DataFrame([{'지표': k, '처음': v[0], '일수': v[1]} for k, v in meta['coverage'].items()]).to_csv(os.path.join(HERE, 'out_features.csv'), index=False, encoding='utf-8')


if __name__ == '__main__':
    main()
