# -*- coding: utf-8 -*-
"""인버스 매수·매도 연구(갈래 I) 공통. 2026-11-23 사용자 요청.

통합 예측 연구소(deriv/uni)의 자료표(out/panel.pkl)와 판정 도구를 그대로 쓴다 — 같은 잣대.
대상: 코스피200 선물이 내릴 확률. 사고파는 것: 인버스 ETF(1배 KODEX 인버스 114800, 참고로 2배 252670).
시각: t일 장 마감 뒤 ~ 다음 개장 전에 신호를 정하고, 다음 거래일(t+1) 시가에 사서 H일째 종가에 판다.
"""
import os
import sys

import numpy as np
import pandas as pd

INV = os.path.dirname(os.path.abspath(__file__)); DERIV = os.path.dirname(INV); UNI = os.path.join(DERIV, 'uni')
sys.path.insert(0, UNI)
import uni_common as U   # noqa: E402  (평가 기간·솎기·윌슨 하한을 같이 쓴다)

OUT = os.path.join(INV, 'out'); STATE = os.path.join(INV, 'state'); NOTIFY = os.path.join(INV, 'notify'); DATA = os.path.join(INV, 'data')
for _d in (OUT, STATE, NOTIFY, DATA): os.makedirs(_d, exist_ok=True)

# (이름, 종류, 보유 거래일, 문턱). DN = 보유 기간 선물 수익 < 0. DROP = 보유 기간 선물 수익 ≤ 문턱(큰 하락).
TARGETS = [('DN1', 'DN', 1, 0.0), ('DN3', 'DN', 3, 0.0), ('DN5', 'DN', 5, 0.0), ('DN10', 'DN', 10, 0.0), ('DROP5', 'DROP', 5, -0.02), ('DROP10', 'DROP', 10, -0.03)]
TARGET_NAME = {'DN1': '1일 하락', 'DN3': '3일 하락', 'DN5': '5일 하락', 'DN10': '10일 하락', 'DROP5': '5일 −2% 이상 하락', 'DROP10': '10일 −3% 이상 하락'}
ETF = {'inv1': ('114800', 'KODEX 인버스', 1.0), 'inv2': ('252670', 'KODEX 200선물인버스2X', 2.0)}
FEE_YEAR = 0.0064      # 선물 수익으로 계산할 때만 쓰는 연 보수(실제 시세에는 이미 들어 있음)
COST_SIDE = 0.0005     # 한쪽 거래 비용(수수료·호가 차이). ETF 는 매도세 없음


def fut_ret(P, H):
    """t 신호 → t+1 시가 ~ t+H 종가의 선물 수익."""
    F = P['K200F']; o = F['open'].values.astype(float); c = F['close'].values.astype(float); n = len(F); i = np.arange(n)
    ent = i + 1; ext = i + H; ok = ext < n; r = np.full(n, np.nan); r[ok] = c[ext[ok]] / o[ent[ok]] - 1
    return ent, ext, r


def hold_ret(px, H):
    """인버스 ETF 를 t+1 시가에 사서 t+H 종가에 팔 때 수익(왕복 비용 뺌)."""
    o = px['open'].values.astype(float); c = px['close'].values.astype(float); n = len(px); i = np.arange(n)
    ent = i + 1; ext = i + H; ok = ext < n; r = np.full(n, np.nan); r[ok] = c[ext[ok]] / o[ent[ok]] - 1 - 2 * COST_SIDE
    return r
