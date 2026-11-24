# -*- coding: utf-8 -*-
"""연구소 꼴 지표(W1·W2 공용) — 연구소 a04_flows.py 의 정의를 고정 자료(릴리스 signal-a-data-v1)로 그대로 다시 만든다.

  sig5      코스피200 지수 종가 pct_change 의 직전 20일 표준편차 × √5 × 100 (a04_flows.py 222줄 — 1주 σ, %)
  lab_age   D.walls 에서 (행사가 K, 결제월 ym)이 같은 날이 이어진 길이(1부터). 결제월이 바뀌면 새 벽. ALL 은 행사가만(a04_flows.py 234~244줄)
  flows     외국인 선물(F_외국인_1d)·현물(S_외국인현물_1d)의 그날 값과 3일 누적 부호(spot_conds 와 같은 꼴)
  regime    코스피200 종가와 60일선(오늘 포함)
자료를 읽지 못하면 조용히 넘기지 않고 멈춘다(RuntimeError).
"""
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
SA = os.path.dirname(HERE)
if SA not in sys.path: sys.path.insert(0, SA)
import sa_common as C  # noqa: E402

FIRST_N = 5


def need_col(D, name):
    if name not in D.X.columns: raise RuntimeError(f'고정 자료에 열이 없음(확인 불가): {name}')
    v = D.X[name].values.astype(float)
    if not np.isfinite(v).any(): raise RuntimeError(f'고정 자료의 열이 전부 빈칸(확인 불가): {name}')
    return v


def k200_close(D):
    """코스피200 지수 종가(자료에 있는 날 그대로, 2007~끝 날짜). 고정 원자료 k200_long.csv 에서 읽는다. D.walls 의 S 칸(2010~)과 같은 값인지 확인한다."""
    p = os.path.join(C.raw_dir('deriv'), 'deriv', 'data', 'k200_long.csv')
    if not os.path.exists(p): raise RuntimeError(f'고정 원자료에 코스피200 지수 파일이 없음: {p}')
    k = pd.read_csv(p); k.columns = [str(c).lstrip('\ufeff') for c in k.columns]
    if '날짜' not in k.columns or '종가' not in k.columns: raise RuntimeError(f'k200_long.csv 의 열이 예상과 다름: {list(k.columns)[:6]}')
    s = pd.Series(pd.to_numeric(k['종가'], errors='coerce').values, index=pd.to_datetime(k['날짜'])).dropna().sort_index()
    s = s[~s.index.duplicated(keep='last')]; s = s[(s.index >= pd.Timestamp('2007-01-01')) & (s.index <= C.END)]
    out = s.reindex(D.td); live_ = D.td >= C.START
    if out[live_].isna().mean() > 0.01: raise RuntimeError(f'코스피200 종가가 거래일의 {100 * out[live_].isna().mean():.1f}% 에서 비어 있음')
    w = D.walls.dropna(subset=['S']).drop_duplicates('date', keep='last'); ws = pd.Series(w['S'].values.astype(float), index=pd.to_datetime(w['date'])).reindex(D.td)
    both = out.notna() & ws.notna()
    if both.sum() < 1000: raise RuntimeError('코스피200 종가와 벽 표(S 칸)를 견줄 날이 모자람')
    bad = int((np.abs(out[both] / ws[both] - 1) > 0.01).sum())
    if bad: raise RuntimeError(f'코스피200 종가(k200_long.csv)가 벽 표의 S 칸과 1% 넘게 다른 날 {bad}일 — 자료 확인 필요')
    return s


def sig5(D, k2c):
    """연구소 σ 띠의 바탕: 직전 20일(오늘 포함) 일간 등락 표준편차 × √5 × 100 (%). 코스피200 자료의 날짜 순서로 계산한 뒤 D.td 에 맞춘 길이 D.n 배열."""
    return (k2c.pct_change().rolling(20).std() * np.sqrt(5) * 100).reindex(D.td).values.astype(float)


def lab_age(D, tag):
    """연구소 방식 벽 나이(1 = 오늘 새 벽). 벽 없는 날은 nan. 결제월이 바뀌면 새 벽(ALL 은 행사가만 본다)."""
    W = D.walls[D.walls['tag'] == tag].copy()
    if not len(W): raise RuntimeError(f'벽 표에 결제월 {tag} 가 없음')
    W['date'] = pd.to_datetime(W['date']); W = W.drop_duplicates(['date', 'tag'], keep='last').sort_values('date').set_index('date')
    key = W['K'].astype(float).round(3).astype(str) + ('' if tag == 'ALL' else '|' + W['ym'].astype(str))
    run = key.ne(key.shift()).cumsum()
    age = W.groupby(run.values).cumcount().add(1).astype(float).where(W['K'].notna().values)
    age.index = W.index
    return age.reindex(D.td).values.astype(float)


def flows(D):
    """외국인 선물·현물 순매수 조건(연구소 spot_conds 꼴). 빈칸 날은 False."""
    f = pd.Series(need_col(D, 'F_외국인_1d'), index=D.td); s = pd.Series(need_col(D, 'S_외국인현물_1d'), index=D.td)
    f3 = f.rolling(3, min_periods=3).sum(); s3 = s.rolling(3, min_periods=3).sum(); ones = np.ones(D.n, dtype=bool)
    with np.errstate(invalid='ignore'):
        return {'none': ones, 'fut1': (f > 0).values, 'fut3': (f3 > 0).values, 'spot3': (s3 > 0).values,
                'both3': ((f3 > 0) & (s3 > 0)).values, 'both1': ((f > 0) & (s > 0)).values}


def regime(D, k2c):
    """장세: 코스피200 종가와 60일선(오늘 포함, 60일 다 있을 때만)."""
    ma = k2c.rolling(60, min_periods=60).mean()
    return {'any': np.ones(D.n, dtype=bool), 'above': (k2c > ma).reindex(D.td).fillna(False).values.astype(bool),
            'below': (k2c < ma).reindex(D.td).fillna(False).values.astype(bool)}


def live(D):
    return np.asarray(D.td >= C.START)


def b_rule_mask(D):
    """연구소 B 규칙의 조건일(늦춤 전): 분기물 콜벽 0~1.5% + 벽 물량 5일 증가 + 분기물 만기 21~40거래일 아님 + 첫 신호(5일). 늦춤 1·보유 3일은 부르는 쪽에서."""
    d = need_col(D, 'OW_Q_wall_dist%'); c5 = need_col(D, 'OW_Q_wall_oi_chg5%'); dte = need_col(D, 'OW_Q_dte')
    with np.errstate(invalid='ignore'):
        m = live(D) & (d > 0) & (d <= 1.5) & (c5 > 0) & ((dte < 21) | (dte > 40))
    return D.first_only(m, FIRST_N)


def k2_mask(D, ages, s5, tags, n_age, band_k=None, band_pct=None):
    """연구소 K2: 묶음 tags 가운데 '나이 ≤ n_age 그리고 0 < 벽 거리 ≤ 띠'인 결제월이 둘 이상인 날. 띠 = σ 띠(sig5 × band_k) 또는 고정 %(band_pct)."""
    band = s5 * band_k if band_k is not None else np.full(D.n, float(band_pct)); cnt = np.zeros(D.n, dtype=int)
    with np.errstate(invalid='ignore'):
        for t in tags:
            dist = need_col(D, f'OW_{t}_wall_dist%')
            cnt += ((ages[t] <= n_age) & (dist > 0) & (dist <= band)).astype(int)
    return live(D) & (cnt >= 2)
