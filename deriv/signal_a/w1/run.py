# -*- coding: utf-8 -*-
"""W1 분기물 콜벽 규칙을 연구소 꼴 그대로 — SPEC.md 그대로 구현(돌린 뒤 고치지 않는다).

가족: 거리 띠 7(고정 % 1.0·1.5·2.0 / 연구소 σ 띠 0.5·0.75·1.0·1.25) × 만기 5 × 벽 나이(연구소 방식) 3 × 물량 변화 4 × 수급 4 × 장세 3
      × 늦춤 2 × 첫 신호 2 × 보유일 4 × 방향 2 = 161,280개.  wf 절차 28개(T1 과 같은 꼴).
조각 4개 = 띠를 번호로 나눔. 계산 틀은 engine.py(T1 복사), 연구소 꼴 지표는 labform.py.
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (os.path.dirname(HERE), HERE):
    if _p not in sys.path: sys.path.insert(0, _p)
import sa_common as C  # noqa: E402
import engine as E  # noqa: E402
import labform as LF  # noqa: E402

TRACK = 'w1'
BANDS = [('p10', 1.0, False), ('p15', 1.5, False), ('p20', 2.0, False), ('s050', 0.5, True), ('s075', 0.75, True), ('s100', 1.0, True), ('s125', 1.25, True)]   # (이름, 값, σ 띠인가)
BAND = {k: (v, s) for k, v, s in BANDS}
DTE = ['any', 'out', 'le20', 'in', 'ge41']
AGE = ['any', 'new', 'old']
CHG = ['any', 'up5', 'up1', 'dn5']
FLOW = ['none', 'fut', 'spot', 'both']
REG = ['any', 'above', 'below']
FIRST = [0, 1]
N_PARTS = 4
NOT_INCLUDED = [
    '분기물 말고 다른 결제월(근월·차월 등)에 같은 연구소 꼴(σ 띠·만기 조건·연구소 나이)을 적용한 것',
    'σ 띠의 다른 값(1.5σ 이상)·σ 창 60일, 고정 % 0.5·3.0(T1 에 있음)',
    '만기 구간의 다른 나눔(10일 이하·11~30일·31일 이상), 근월 만기와의 겹침 조건',
    '벽 나이 3·5·7일 이상 세분, 새 벽이 생긴 까닭(W3 에서 봄)',
    '첫 신호 창 3·10일, 다음 날 양봉 확인 뒤 진입 같은 연구소의 다른 늦춤 꼴',
    '익절·손절 청산과 보유일 2·7·20일(W3·W6 에서 봄)',
]
DTE_KO = {'any': '', 'out': ' + 분기물 만기 21~40거래일 아님', 'le20': ' + 분기물 만기 20거래일 이하', 'in': ' + 분기물 만기 21~40거래일', 'ge41': ' + 분기물 만기 41거래일 이상'}
AGE_KO = {'any': '', 'new': ' + 오늘 새로 생긴 벽(결제월 교체 포함)', 'old': ' + 어제와 같은 벽'}
CHG_KO = {'any': '', 'up5': ' + 벽 물량 5일 증가', 'up1': ' + 벽 물량 1일 증가', 'dn5': ' + 벽 물량 5일 감소'}
FLOW_KO = {'none': '', 'fut': ' + 외국인 선물 3일 누적 순매수', 'spot': ' + 외국인 현물 3일 누적 순매수', 'both': ' + 외국인 선물·현물 3일 누적 함께 순매수'}
REG_KO = {'any': '', 'above': ' + 코스피200 60일선 위', 'below': ' + 코스피200 60일선 아래'}


def band_ko(sub):
    v, sig = BAND[sub]
    return f'{v:g}σ(직전 20일 1주 σ)' if sig else f'{v:g}%'


class Spec:
    TRACK = TRACK
    SUBS = [k for k, _, _ in BANDS]
    QUICK_SUBS = ['p15', 's075']
    HOLDS = [1, 3, 5, 10]
    QUICK_HOLDS = [3, 5]
    NOT_INCLUDED = NOT_INCLUDED
    SUB_KO = {k: f'띠 {band_ko(k)}' for k, _, _ in BANDS}
    ROOT = '분기물 콜벽(연구소 꼴)'
    LAB = [('B 규칙', ('p15', ('out', 'any', 'up5', 'none', 'any', 1), 1, 3), True),
           ('B 규칙에서 만기 조건을 뺀 것(= T1 의 Q 규칙)', ('p15', ('any', 'any', 'up5', 'none', 'any', 1), 1, 3), False),
           ('B 규칙의 띠를 0.75σ 로 바꾼 것', ('s075', ('out', 'any', 'up5', 'none', 'any', 1), 1, 3), False)]
    LAB_NOTE = 'B 규칙 = 연구소 통과 신호의 B 쪽 그대로: 분기물 콜벽 0~1.5% 안 + 벽 물량 5일 증가 + 분기물 만기 21~40거래일 아님 + 첫날만 + 하루 쉬고 3일 보유, 오름. 나머지 둘은 참고.'

    @staticmethod
    def n_parts(): return N_PARTS

    @staticmethod
    def make_ctx(D):
        k2c = LF.k200_close(D); s5 = LF.sig5(D, k2c); ones = np.ones(D.n, dtype=bool)
        dist = LF.need_col(D, 'OW_Q_wall_dist%'); dte = LF.need_col(D, 'OW_Q_dte'); c5 = LF.need_col(D, 'OW_Q_wall_oi_chg5%'); c1 = LF.need_col(D, 'OW_Q_wall_oi_chg1%')
        age = LF.lab_age(D, 'Q'); fl = LF.flows(D)
        with np.errstate(invalid='ignore'):
            ctx = {'dist': dist, 's5': s5, 'live': LF.live(D),
                   'dte': {'any': ones, 'out': (dte < 21) | (dte > 40), 'le20': dte <= 20, 'in': (dte >= 21) & (dte <= 40), 'ge41': dte >= 41},
                   'age': {'any': ones, 'new': age <= 1, 'old': age >= 2},
                   'chg': {'any': ones, 'up5': c5 > 0, 'up1': c1 > 0, 'dn5': c5 < 0},
                   'flow': {'none': ones, 'fut': fl['fut3'], 'spot': fl['spot3'], 'both': fl['both3']},
                   'reg': LF.regime(D, k2c)}
        return ctx

    @staticmethod
    def cond_list(sub):
        return [(e, a, c, f, r, fs) for e in DTE for a in AGE for c in CHG for f in FLOW for r in REG for fs in FIRST]

    @staticmethod
    def build_M(D, ctx, sub):
        v, sig = BAND[sub]; cl = Spec.cond_list(sub); M = np.zeros((len(cl), D.n), dtype=bool)
        with np.errstate(invalid='ignore'):
            band = ctx['s5'] * v if sig else v
            zone = ctx['live'] & (ctx['dist'] > 0) & (ctx['dist'] <= band)
            last = None; m = None
            for i, (e, a, c, f, r, fs) in enumerate(cl):
                key = (e, a, c, f, r)
                if key != last:
                    m = zone & ctx['dte'][e] & ctx['age'][a] & ctx['chg'][c] & ctx['flow'][f] & ctx['reg'][r]; last = key
                M[i] = D.first_only(m, E.FIRST_N) if fs else m
        return M

    @staticmethod
    def rule_id(sub, cond, d, h, direction):
        e, a, c, f, r, fs = cond
        return f"R_Q_{sub}_{e}_{a}_{c}_{f}_{r}_d{d}_f{fs}_h{h}_{'up' if direction > 0 else 'dn'}"

    @staticmethod
    def rule_desc(sub, cond, d, h, direction):
        e, a, c, f, r, fs = cond
        return (f'분기물 콜벽이 지수 위 0~{band_ko(sub)} 안' + DTE_KO[e] + AGE_KO[a] + CHG_KO[c] + FLOW_KO[f] + REG_KO[r] + (' + 직전 5일 안 같은 조건 없던 첫날만' if fs else '')
                + ' → ' + ('하루 쉬고 ' if d else '다음 날 시가 ') + f"매수, {h}일 보유, {'오름' if direction > 0 else '내림'}")

    @staticmethod
    def rule_params(sub, cond, d, h):
        e, a, c, f, r, fs = cond; v, sig = BAND[sub]
        return {'wall': 'Q', 'band': v, 'band_unit': 'sigma5' if sig else 'pct', 'dte': e, 'age': a, 'chg': c, 'flow': f, 'reg': r, 'first': fs, 'delay': d, 'hold': h}


def n_parts():
    return N_PARTS


def run_part(i, n, quick=False):
    return E.run_part(Spec, i, n, quick=quick)


def merge(parts, quick=False, with_tabs=False):
    cands, meta, tabs = E.merge(Spec, parts, quick=quick)
    return (cands, meta, tabs) if with_tabs else (cands, meta)


if __name__ == '__main__':
    E.main(Spec, lambda parts, quick: merge(parts, quick, with_tabs=True))
