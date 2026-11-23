#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""U1 자료 통합 — 연구소·대시보드의 일별 지표를 날짜별 한 표로 합치고 묶음(기존 재료·선물·옵션·미국)을 붙인다.

다시 쓰는 것(새로 만들지 않음)
  deriv/scan/scan_data.py  일별 지표 207개(선물·옵션 수급, 베이시스, 프로그램, 변동성, 해외, 신용·반대매매, 현물 수급, 가격, 달력) — 시각 규칙 적용됨
  deriv/lab/a02_features.py 옵션 행사가 벽 지표(콜벽·풋벽·최대 고통·물량 변화)
  deriv/us/us_features.py   미국 지표(한국 거래일에 맞춤: 다음 개장 전에 나온 값만)
새로 더하는 것: 대시보드 최적화 신호가 쓰던 금투협 대주·담보융자·RP 순위, RSI·이동평균(main 의 통합 원자료). 금투협은 하루 늦춤.
못 넣는 것: 거래소 공매도(거래대금·잔고)는 2026-01 부터만 있어 해마다 다시 학습하는 검증에 쓸 수 없다 → 표에는 넣지 않고 meta 에 '자료 부족'으로 적는다.
출력: out/panel.pkl {'X', 'groups', 'P', 'meta'}
"""
import json
import os
import pickle
import sys

import numpy as np
import pandas as pd

import uni_common as U

sys.path.insert(0, os.path.join(U.DERIV, 'scan')); sys.path.insert(0, os.path.join(U.DERIV, 'lab')); sys.path.insert(0, U.DERIV)

OPT_V1 = ('V1_대표IV', 'V1_IV_5d변화', 'V1_IV-HV20')
US_KOREA = {'vkospi': 'vol', 'vk_c5': 'vol', 'vk_vix': 'vol', 'k_pcr': 'opt', 'for_fut3': 'fut', 'for_fut10': 'fut', 'for_fut1': 'fut', 'k2_r1': 'price', 'k2_r5': 'price'}
US_VIX = {'vix', 'vix_c1', 'vix_c5'}


def group_of(c):
    if c.startswith('US_'):
        k = c[3:]
        return US_KOREA.get(k, 'vol' if k in US_VIX else 'us')
    if c.startswith(('PK_', 'BASE_', 'K_', 'D_RSI', 'D_SMA')): return 'price'
    if c.startswith(('C_', 'S_', 'D_')): return 'fund'
    if c in OPT_V1: return 'opt'
    if c.startswith(('V1_', 'M_VKOSPI', 'W_VIX')): return 'vol'
    if c.startswith(('F_', 'F2_', 'F4_', 'B1_', 'P1_', 'T1_', 'M1_', 'K2_', 'PF_', 'NT_')): return 'fut'
    if c.startswith(('O1_', 'O2_', 'O3_', 'V2_', 'R1_', 'E1_', 'G1_', 'OW_')): return 'opt'
    if c.startswith(('W_', 'M_')): return 'us'
    return 'other'


def main_extras(idx):
    """대시보드 최적화 신호의 재료 가운데 연구소 표에 없는 것(금투협 대주·담보융자·RP 순위, RSI, 이동평균). 금투협은 하루 늦춤."""
    xl = os.path.join(U.MAIN, 'data', '통합_원자료.xlsx')
    if not os.path.exists(xl): return pd.DataFrame(index=idx), '통합 원자료 없음'
    sys.path.insert(0, os.path.join(U.MAIN, 'pkg')); import reproduce as R
    D = R.load(xl); K, L, C = D['K'], D['L'], D['C']; c = K.close.reindex(idx)
    lag = lambda s: s.reindex(idx).shift(1)
    short, pledge, rp, dep, cred = lag(C.short), lag(C.pledge), lag(L.rp), lag(L.deposit), lag(C.credit)
    E = pd.DataFrame(index=idx)
    E['D_대주_20d%'] = (short / short.shift(20) - 1) * 100
    E['D_대주_순위'] = short.expanding(250).rank(pct=True)
    E['D_담보융자_20d%'] = (pledge / pledge.shift(20) - 1) * 100
    E['D_RP_순위'] = rp.expanding(250).rank(pct=True)
    E['D_대주/신용%'] = short / cred * 100
    dlt = c.diff(); g = dlt.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean(); l_ = (-dlt.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    E['D_RSI14'] = 100 - 100 / (1 + g / l_)
    E['D_SMA8/22%'] = (c.rolling(8).mean() / c.rolling(22).mean() - 1) * 100
    return E, ''


def main():
    import scan_run as SR
    X = SR.X0.copy(); X.index = pd.to_datetime(X.index); P = {k: v.copy() for k, v in SR.D['P'].items()}
    notes = {}
    try:
        W = pickle.load(open(os.path.join(U.DERIV, 'lab', 'work', 'lab_feat.pkl'), 'rb'))['wide']
        X = X.join(W.reindex(X.index).add_prefix('') if all(c.startswith('OW_') for c in W.columns) else W.reindex(X.index).add_prefix('OW_'), how='left')
        notes['옵션 벽 지표'] = f'{W.shape[1]}개, {W.index.min().date()}~{W.index.max().date()}'
    except Exception as e:
        notes['옵션 벽 지표'] = f'못 읽음({type(e).__name__})'
    try:
        us = pd.read_csv(os.path.join(U.DERIV, 'us', 'out', 'features_kr.csv.gz'), parse_dates=['date']).set_index('date')
        X = X.join(us.reindex(X.index).add_prefix('US_'), how='left'); notes['미국 지표'] = f'{us.shape[1]}개, ~{us.index.max().date()}'
    except Exception as e:
        notes['미국 지표'] = f'못 읽음({type(e).__name__})'
    try:
        E, why = main_extras(X.index); X = X.join(E, how='left'); notes['대시보드 자금 재료'] = why or f'{E.shape[1]}개'
    except Exception as e:
        notes['대시보드 자금 재료'] = f'못 읽음({type(e).__name__}: {str(e)[:80]})'
    X = X.loc[:, ~X.columns.duplicated()]
    X = X.replace([np.inf, -np.inf], np.nan)
    groups = {c: group_of(c) for c in X.columns}
    sp = os.path.join(U.MAIN, 'data', 'short', 'market_daily.csv'); short_note = '파일 없음'
    if os.path.exists(sp):
        s = pd.read_csv(sp); short_note = f"{s['date'].min()}~{s['date'].max()} {len(s)}일 — 해마다 다시 학습하는 검증에는 3년 이상 필요(자료 부족, 표에 넣지 않음)"
    cnt = pd.Series(groups).value_counts().to_dict()
    cov = {g: str(X[[c for c in X.columns if groups[c] == g]].dropna(how='all').index.min().date()) for g in cnt}
    meta = dict(made=pd.Timestamp.now(tz='Asia/Seoul').strftime('%Y-%m-%d %H:%M'), start=str(X.index.min().date()), end=str(X.index.max().date()), n_features=int(X.shape[1]),
                group_count=cnt, group_start=cov, notes=notes, missing={'거래소 공매도(거래대금·잔고)': short_note})
    pickle.dump({'X': X, 'groups': groups, 'P': P, 'meta': meta}, open(os.path.join(U.OUT, 'panel.pkl'), 'wb'))
    json.dump(meta, open(os.path.join(U.OUT, 'panel_meta.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(json.dumps(meta, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
