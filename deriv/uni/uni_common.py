# -*- coding: utf-8 -*-
"""통합 예측 연구소(갈래 U) 공통 — 경로·대상 정의·통계. 2026-11-23 사용자 요청.

목적: 대시보드 최적화 신호가 쓰지 않던 자료(선물·옵션·미국·해외)까지 모두 넣어 코스피 방향을 예측하고 매수·매도 신호를 다시 만든다.
시각 규칙(연구소 deriv/scan 과 같음): t일 지표 = t일 장 마감 뒤 ~ 다음 거래일(t+1) 개장 전까지 알 수 있는 값. 금투협은 하루 늦춤.
"""
import os

import numpy as np
import pandas as pd

UNI = os.path.dirname(os.path.abspath(__file__)); DERIV = os.path.dirname(UNI); REPO = os.path.dirname(DERIV)
OUT = os.path.join(UNI, 'out'); STATE = os.path.join(UNI, 'state'); NOTIFY = os.path.join(UNI, 'notify')
for _d in (OUT, STATE, NOTIFY): os.makedirs(_d, exist_ok=True)
MAIN = os.environ.get('UNI_MAIN', os.path.join(REPO, '_main'))      # main 가지를 받아 둔 폴더(자금 원자료·기준선 계산)

TRAIN_START = pd.Timestamp('2010-01-01')
FIRST_PRED_YEAR = 2013        # 2013~2015 예측은 문턱(분위) 정하는 데만 쓴다
EVAL_START = pd.Timestamp('2016-01-01')     # 성적은 여기부터(표본 밖)
SPLIT = pd.Timestamp('2022-01-01')          # 앞 = 2016~2021, 뒤 = 2022~
Z = 1.645

# 대상: (이름, 종류, 보유 거래일). IDX = 코스피, 신호 다음 날 종가에 들어가 H거래일 뒤 종가(대시보드 방식). FUT = 코스피200 선물, 다음 날 시가 → H일째 종가(연구소 방식).
TARGETS = [('IDX20', 'IDX', 20), ('IDX10', 'IDX', 10), ('IDX5', 'IDX', 5), ('FUT3', 'FUT', 3), ('FUT1', 'FUT', 1)]
SETS = ['base', 'fut', 'opt', 'us', 'all']
SET_NAME = {'base': '기존 재료(가격·자금·수급·변동성)', 'fut': '기존 + 선물', 'opt': '기존 + 옵션', 'us': '기존 + 미국·해외', 'all': '전부'}
MODELS = ['gb', 'lr', 'ens']
MODEL_NAME = {'gb': '나무 모형', 'lr': '선형 모형', 'ens': '둘 평균'}


def target_arrays(P, kind, H):
    """ent[i]·ext[i] = t=i 신호의 진입·청산 위치, r = 수익률(없으면 nan)."""
    K = P['KOSPI']; F = P['K200F']; n = len(K); i = np.arange(n)
    if kind == 'IDX':
        ent = i + 1; ext = i + 1 + H; c = K['close'].values.astype(float)
        ok = ext < n; r = np.full(n, np.nan); r[ok] = c[ext[ok]] / c[ent[ok]] - 1
    else:
        ent = i + 1; ext = i + H; o = F['open'].values.astype(float); c = F['close'].values.astype(float)
        ok = ext < n; r = np.full(n, np.nan); r[ok] = c[ext[ok]] / o[ent[ok]] - 1
    return ent, ext, r


def wilson_lb(k, n):
    if n <= 0: return 0.0
    p = k / n; d = 1 + Z * Z / n; c = p + Z * Z / (2 * n); h = Z * np.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n))
    return float((c - h) / d)


def thin(sig_idx, ext):
    """겹치지 않는 독립 신호만: 앞 거래가 끝난(ext) 뒤의 첫 신호부터 다시 센다."""
    out = []; free = -1
    for i in sig_idx:
        if i > free: out.append(i); free = ext[i]
    return np.asarray(out, dtype=int)
