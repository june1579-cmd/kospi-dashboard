# -*- coding: utf-8 -*-
"""W2 갈래 A 뿌리(둘 이상 동시 새 콜벽)를 연구소 꼴 그대로 — SPEC.md 그대로 구현(돌린 뒤 고치지 않는다).

뿌리 사건(연구소 a04_flows.py K2): 결제월 묶음 안에서 '벽 나이 ≤ N일 + 0 < 벽 거리 ≤ 띠'인 결제월이 둘 이상인 날.
가족: 묶음 2 × 나이 2 × 띠 7(σ 1.25·1.5·1.75·2.0 / 고정 % 2.0·2.5·3.0) × 수급 6 × 장세 3 × 늦춤 2 × 첫 신호 2 × 보유일 5 × 방향 2 = 20,160개
      + 함께 쓰기(연구소 통과 신호 A4xu_B2xA1 을 고정 자료로 다시 만든 것) 1개 = 20,161개.  wf 절차 28개(T1 과 같은 꼴).
조각 1개. 계산 틀·연구소 꼴 지표는 ../w1/engine.py·labform.py 를 불러 쓴다.
"""
import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
SA = os.path.dirname(HERE)
W1 = os.path.join(SA, 'w1')
if not os.path.exists(os.path.join(W1, 'engine.py')): raise RuntimeError('w1/engine.py 가 없음 — W2 는 W1 폴더의 계산 틀을 불러 쓴다')
for _p in (SA, W1):
    if _p not in sys.path: sys.path.insert(0, _p)
import sa_common as C  # noqa: E402
import engine as E  # noqa: E402
import labform as LF  # noqa: E402

TRACK = 'w2'
GROUPS = {'G3': ['F0', 'F1', 'ALL'], 'G4': ['F0', 'F1', 'F2', 'ALL']}
GROUP_KO = {'G3': '근월·차월·합산', 'G4': '근월·차월·차차월·합산'}
SUBDEF = {'G3n1': ('G3', 1), 'G3n2': ('G3', 2), 'G4n1': ('G4', 1), 'G4n2': ('G4', 2)}
BANDS = [('s125', 1.25, True), ('s150', 1.5, True), ('s175', 1.75, True), ('s200', 2.0, True), ('p20', 2.0, False), ('p25', 2.5, False), ('p30', 3.0, False)]
BAND = {k: (v, s) for k, v, s in BANDS}
FLOW = ['none', 'fut1', 'fut3', 'both3', 'both1', 'spot3']
REG = ['any', 'above', 'below']
FIRST = [0, 1]
N_PARTS = 1
NOT_INCLUDED = [
    '셋 이상 동시(K3)·하나라도(ANY)·근월 포함 둘 이상(F0K2), 새 벽이 생긴 까닭(물량 이동·넘어섬·만기 교체·위/아래로 옮겨 감) — 셋 이상·까닭은 W3 에서 봄',
    '위클리 콜벽을 동시 표에 더하기(K2W), 분기물·차기 분기물을 묶음에 넣기',
    '외국인 콜·풋 옵션 흐름, 차익 프로그램, 수급 누적 창 5·10일, 변동성 하위 구간에서만 켜기',
    '연구소의 익절·손절(±kσ) 청산 꼴',
    '함께 쓰기의 다른 짝(B1xA1, 띠 1.75σ 짝)과 함께 쓰기를 해마다 고르는 절차로 만드는 것',
]
FLOW_KO = {'none': '', 'fut1': ' + 외국인 선물 순매수(그날)', 'fut3': ' + 외국인 선물 3일 누적 순매수', 'both3': ' + 외국인 선물·현물 3일 누적 함께 순매수',
           'both1': ' + 외국인 선물·현물 함께 순매수(그날)', 'spot3': ' + 외국인 현물 3일 누적 순매수'}
REG_KO = {'any': '', 'above': ' + 코스피200 60일선 위', 'below': ' + 코스피200 60일선 아래'}
A_RULE = {'s150': ('G4n1', ('s150', 'both3', 'above', 0), 0, 5), 's175': ('G4n1', ('s175', 'both3', 'above', 0), 0, 5)}
REF_A = 'A4yu_K2_F0+F1+F2+ALL_1d_s1.75_외국인 선물·현물 3일 누적 함께 순매수 + 60일선 위_m5_up'
REF_XU = 'A4xu_B2xA1'


def band_ko(b):
    v, sig = BAND[b]
    return f'{v:g}σ(직전 20일 1주 σ)' if sig else f'{v:g}%'


def sub_ko(sub):
    g, na = SUBDEF[sub]
    return f"{'+'.join(GROUPS[g])} · 나이 {na}일 이하"


class Spec:
    TRACK = TRACK
    SUBS = list(SUBDEF)
    QUICK_SUBS = ['G4n1']
    HOLDS = [1, 3, 5, 7, 10]
    QUICK_HOLDS = [3, 5]
    NOT_INCLUDED = NOT_INCLUDED
    SUB_KO = {s: sub_ko(s) for s in SUBDEF}
    ROOT = '동시 새 콜벽(연구소 꼴)'
    LAB = [('A 규칙(1.5σ)', A_RULE['s150'], True), ('A 규칙(1.75σ)', A_RULE['s175'], True),
           ('A 규칙(1.5σ)의 묶음을 F0+F1+ALL 로', ('G3n1', ('s150', 'both3', 'above', 0), 0, 5), False),
           ('A 규칙(1.75σ)의 묶음을 F0+F1+ALL 로', ('G3n1', ('s175', 'both3', 'above', 0), 0, 5), False)]
    LAB_NOTE = ('A 규칙 = 연구소 갈래 A 그대로: 근월·차월·차차월·합산 가운데 둘 이상이 같은 날 새 콜벽(나이 1일 이하)이면서 띠 안 + 외국인 선물·현물 3일 누적 함께 순매수 + 60일선 위 → 5일 보유, 오름. '
                '1.5σ 는 연구소 통과 신호의 A 쪽, 1.75σ 는 갈래 A 최고 후보.')

    @staticmethod
    def n_parts(): return N_PARTS

    @staticmethod
    def make_ctx(D):
        k2c = LF.k200_close(D)
        return {'s5': LF.sig5(D, k2c), 'ages': {t: LF.lab_age(D, t) for t in ('F0', 'F1', 'F2', 'ALL')}, 'flow': LF.flows(D), 'reg': LF.regime(D, k2c)}

    @staticmethod
    def cond_list(sub):
        return [(b, f, r, fs) for b, _, _ in BANDS for f in FLOW for r in REG for fs in FIRST]

    @staticmethod
    def event(D, ctx, sub, b):
        g, na = SUBDEF[sub]; v, sig = BAND[b]
        return LF.k2_mask(D, ctx['ages'], ctx['s5'], GROUPS[g], na, band_k=v if sig else None, band_pct=None if sig else v)

    @staticmethod
    def build_M(D, ctx, sub):
        cl = Spec.cond_list(sub); M = np.zeros((len(cl), D.n), dtype=bool); ev = {}; last = None; m = None
        for i, (b, f, r, fs) in enumerate(cl):
            if b not in ev: ev[b] = Spec.event(D, ctx, sub, b)
            key = (b, f, r)
            if key != last: m = ev[b] & ctx['flow'][f] & ctx['reg'][r]; last = key
            M[i] = D.first_only(m, E.FIRST_N) if fs else m
        return M

    @staticmethod
    def rule_id(sub, cond, d, h, direction):
        b, f, r, fs = cond
        return f"R_{sub}_{b}_{f}_{r}_d{d}_f{fs}_h{h}_{'up' if direction > 0 else 'dn'}"

    @staticmethod
    def rule_desc(sub, cond, d, h, direction):
        b, f, r, fs = cond; g, na = SUBDEF[sub]
        return (f"{GROUP_KO[g]} 가운데 둘 이상이 같은 날 새 콜벽(나이 {na}일 이하, 결제월 교체 포함)이면서 지수 위 0~{band_ko(b)} 안" + FLOW_KO[f] + REG_KO[r]
                + (' + 직전 5일 안 같은 조건 없던 첫날만' if fs else '') + ' → ' + ('하루 쉬고 ' if d else '다음 날 시가 ') + f"매수, {h}일 보유, {'오름' if direction > 0 else '내림'}")

    @staticmethod
    def rule_params(sub, cond, d, h):
        b, f, r, fs = cond; g, na = SUBDEF[sub]; v, sig = BAND[b]
        return {'group': GROUPS[g], 'age_le': na, 'band': v, 'band_unit': 'sigma5' if sig else 'pct', 'flow': f, 'reg': r, 'first': fs, 'delay': d, 'hold': h}


# ------------------------------------------------------------------ 함께 쓰기(연구소 통과 신호 A4xu_B2xA1 을 고정 자료로 다시 만듦)
def cross_union(tb, ta):
    """연구소 a04_flows.py cross_union 과 같은 합치기: 신호일 순(같은 날이면 B 먼저), 앞 거래 청산일 전의 신호는 건너뜀. 각자 자기 보유일."""
    T = pd.concat([tb.assign(src=0), ta.assign(src=1)], ignore_index=True).sort_values(['signal', 'src'], kind='mergesort')
    keep = []; last = pd.Timestamp('1900-01-01')
    for s_, e_, src in zip(T['signal'], T['exit'], T['src']):
        if s_ >= last: keep.append((s_, e_, src)); last = e_
    return pd.DataFrame(keep, columns=['signal', 'exit', 'src'])


def _ref_trades(name):
    p = os.path.join(SA, 'ref', 'lab_ref.json')
    if not os.path.exists(p): raise RuntimeError('ref/lab_ref.json 이 없음 — 연구소 거래일과 견줄 수 없음')
    J = json.load(open(p, encoding='utf-8'))['signals']
    if name not in J: raise RuntimeError(f'ref/lab_ref.json 에 {name} 이 없음')
    t = pd.DataFrame(J[name]['trades'], columns=['signal', 'exit']); t['signal'] = pd.to_datetime(t['signal']); t['exit'] = pd.to_datetime(t['exit'])
    return t[t['exit'] <= C.END].reset_index(drop=True)


def _match(ref, mine):
    """연구소 거래(ref) 가운데 여기서 다시 만든 거래(mine)에도 있는 것: (신호일·청산일 모두 같음, 신호일만 같음)."""
    both = set(zip(mine['signal'], mine['exit'])); sig = set(mine['signal'])
    return int(sum((s, e) in both for s, e in zip(ref['signal'], ref['exit']))), int(sum(s in sig for s in ref['signal']))


def union_extra(D, ctx):
    """함께 쓰기 후보 1개와 연구소 거래일 견줌 표."""
    tb = D.trades_from_pos(np.flatnonzero(LF.b_rule_mask(D)), 3, 1)
    sub, cond, d, h = A_RULE['s150']; ma = Spec.event(D, ctx, sub, cond[0]) & ctx['flow'][cond[1]] & ctx['reg'][cond[2]]
    ta = D.trades_from_pos(np.flatnonzero(ma), h, d)
    U = cross_union(tb, ta)
    if not len(U): raise RuntimeError('함께 쓰기 후보의 거래가 0건 — 비정상이라 멈춤')
    cand = {'id': 'XU_B2xA1', 'family': '함께 쓰기', 'kind': 'fixed', 'direction': 1, 'hold': None, 'root': '분기물 콜벽 + 동시 새 콜벽(연구소 통과 신호)',
            'desc': ('(연구소 통과 신호 A4xu_B2xA1 을 고정 자료로 다시 만듦) 함께 쓰기[B: 분기물 콜벽 0~1.5% + 벽 물량 5일 증가 + 하루 쉬고 + 분기물 만기 21~40거래일 아님 + 첫날만 → 3일 | '
                     'A: 둘 이상 동시 새 콜벽(1.5σ) + 외국인 선물·현물 3일 누적 함께 순매수 + 60일선 위 → 5일] 먼저 난 신호부터 각자 보유일, 보유 중 새 신호는 건너뜀, 오름'),
            'trades': U[['signal', 'exit']].reset_index(drop=True), 'params': {'b': 'W1 B 규칙', 'a': 'W2 A 규칙(1.5σ)', 'n_b': int((U['src'] == 0).sum()), 'n_a': int((U['src'] == 1).sum())}}
    rows = []
    rx = _ref_trades(REF_XU); k2, k1 = _match(rx, U)
    rows.append({'견준 것': '함께 쓰기(B 규칙 + A 규칙 1.5σ)', '연구소 기록': REF_XU, '연구소 거래 수(끝 날짜까지)': len(rx), '여기서 다시 만든 거래 수': len(U),
                 '신호일·청산일 모두 같음': k2, '신호일만 같음': k1})
    sub7, cond7, d7, h7 = A_RULE['s175']; m7 = Spec.event(D, ctx, sub7, cond7[0]) & ctx['flow'][cond7[1]] & ctx['reg'][cond7[2]]
    t7 = D.trades_from_pos(np.flatnonzero(m7), h7, d7); ra = _ref_trades(REF_A); k2, k1 = _match(ra, t7)
    rows.append({'견준 것': 'A 규칙(1.75σ) — 솎지 않은 모든 신호', '연구소 기록': REF_A, '연구소 거래 수(끝 날짜까지)': len(ra), '여기서 다시 만든 거래 수': len(t7),
                 '신호일·청산일 모두 같음': k2, '신호일만 같음': k1})
    return cand, pd.DataFrame(rows), {'b_signals': len(tb), 'a_signals': len(ta), 'union': len(U), 'from_b': int((U['src'] == 0).sum()), 'from_a': int((U['src'] == 1).sum())}


def n_parts():
    return N_PARTS


def run_part(i, n, quick=False):
    return E.run_part(Spec, i, n, quick=quick)


def merge(parts, quick=False, with_tabs=False):
    cands, meta, tabs = E.merge(Spec, parts, quick=quick)
    D = C.Data(); ctx = Spec.make_ctx(D)
    xc, T_ref, st = union_extra(D, ctx)
    cands.append(xc)
    meta['families'] = dict(meta['families']); meta['families']['함께 쓰기(연구소 통과 신호 다시 만듦)'] = 1
    meta['n_tested'] = int(meta['n_tested']) + 1; meta['m_fixed'] = meta['n_tested']
    meta['notes'] = list(meta['notes']) + [f"함께 쓰기 후보 XU_B2xA1: B 규칙 신호 {st['b_signals']}일 + A 규칙(1.5σ) 신호 {st['a_signals']}일 → 겹치지 않게 {st['union']}거래(B {st['from_b']} · A {st['from_a']}). "
                                           '전체 기간 고정 규칙이며 연구소가 결과를 보고 고른 신호다(가짓수 1개로 셈).']
    md = ['', '#### (7) 연구소 거래일과 견줌 (고정 자료로 다시 만든 것이 연구소 기록과 같은가)', '',
          '연구소 기록(ref/lab_ref.json)의 거래 가운데 여기서 다시 만든 거래에도 있는 것의 수. 연구소는 그 뒤 자료를 고쳐 다시 받은 날이 있을 수 있어 조금 다를 수 있다. 성적 판정은 위 판정 표(XU_B2xA1)에 있다.', '']
    meta['summary_md'] = meta['summary_md'] + '\n' + '\n'.join(md + E.md_table(T_ref)) + '\n'
    tabs = dict(tabs); tabs['lab_ref_match.csv'] = T_ref; meta['tables'] = list(tabs)
    return (cands, meta, tabs) if with_tabs else (cands, meta)


if __name__ == '__main__':
    E.main(Spec, lambda parts, quick: merge(parts, quick, with_tabs=True))
