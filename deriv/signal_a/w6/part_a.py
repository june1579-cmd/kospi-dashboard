# -*- coding: utf-8 -*-
"""W6 앞쪽(part_a) — T2·T5 SPEC 의 '안 넣은 것' (SPEC_a.md 그대로. 돌린 뒤 고치지 않는다).

T2 몫(T2x_, 전부 wf 684개): 상태 구간 3·20일 / 저점의 20%·60% 잡기 / 구간 안 첫 방아쇠만 / 하루 늦춤 / 가격 묶음 뺀 상태 / 8% 전환점 상태 /
                           방아쇠 T6 의 다른 값 6가지 / 내림 방향(꼭지 상태 → 하락 방아쇠).
T5 몫(T5x_, fixed 4,036 · wf 262): 새 조건 7개 / 장세 겹침 4 / 문턱 5%·20% / 순위 창 3년 / 하루 늦춤 / 조건 짝 703쌍 / 확률 모형 / 새 채점(±3%·변동폭 맞춤 닿기).
원래 정의는 t2/run.py·t5/run.py 를 불러 쓴다(고치지 않음). 판정은 sa_judge.py.

총괄의 w6/run.py 가 부르는 함수: n_parts() · run_part(k, n, quick) · merge(parts, quick, out_dir) → (cands, meta).
혼자 시험: python w6/part_a.py --nparts | --part i/n | --merge  (+ --quick) — 시험용 줄기 이름 'w6a'.
"""
import importlib.util
import itertools
import os
import sys
import warnings

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__)); SA = os.path.dirname(HERE)
if SA not in sys.path: sys.path.insert(0, SA)
import sa_common as C  # noqa: E402

TRACK = 'w6a'
NJ = max(1, min(4, os.cpu_count() or 1))


def _load(name, rel):
    """다른 줄기의 run.py 를 다른 이름으로 불러온다(읽기만 — 고치지 않는다)."""
    if name in sys.modules: return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, os.path.join(SA, rel)); m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m; spec.loader.exec_module(m)
    return m


def _T2(): return _load('sa_t2_run', os.path.join('t2', 'run.py'))
def _T5(): return _load('sa_t5_run', os.path.join('t5', 'run.py'))


# ====================================================================== 미리 정한 것(SPEC_a.md)
# ---- T2 몫
STATE_VARS = ['base', 'nop', 'mv8', 'top']               # 기본 · 가격 묶음 뺌 · 8% 전환점 · 꼭지(내림)
STATE_KO = {'base': '기본 상태(원래 T2 와 같음)', 'nop': '지수·가격 묶음을 뺀 상태', 'mv8': '8% 전환점 기준 상태', 'top': '꼭지 상태(내림)'}
MOVE8 = 0.08
CATCHES = (0.20, 0.60)
WINS_NEW = (3, 20); WINS_BASE = (5, 10)
T6_VARS = [('s20', 0.8, 80, None, '직전 5일 최고보다 20% 이상 줄어든 첫 날'), ('s40', 0.6, 80, None, '직전 5일 최고보다 40% 이상 줄어든 첫 날'),
           ('r70', 0.7, 70, None, '자리 70 이상 뒤 30% 이상 줄어든 첫 날'), ('r90', 0.7, 90, None, '자리 90 이상 뒤 30% 이상 줄어든 첫 날'),
           ('dl10', 0.7, 80, 10, '자리 80 이상 뒤 10거래일 안에 30% 이상 줄어든 첫 날'), ('dl20', 0.7, 80, 20, '자리 80 이상 뒤 20거래일 안에 30% 이상 줄어든 첫 날')]
DN_TRIG = {1: '첫 반락일(내린 날이고 전날은 오름)', 2: '전일 저가 이탈(종가 < 전날 저가)', 3: '이틀 연속 하락 마감', 4: '장대 음봉(하루 −1.5% 이하)',
           5: '5일선 이탈(종가가 5일 평균 위에서 아래로)', 7: '외국인 매수 둔화(현물 5일 합 자리 80 이상에서 당일 순매도 전환)', 8: '변동성 되오름(VKOSPI 자리 20 이하에서 하루 5% 이상 상승)'}
DN_SHORT = {0: '방아쇠 없음', 1: '첫 반락일', 2: '전일 저가 이탈', 3: '이틀 연속 하락', 4: '장대 음봉', 5: '5일선 이탈', 7: '외국인 매수 둔화', 8: '변동성 되오름'}
T2_SCORES = [('h3', 3), ('h5', 5), ('h10', 10), ('touch', None)]
UP_SC = {'h3': '다음 날 시가 매수 → 3일째 종가 매도', 'h5': '다음 날 시가 매수 → 5일째 종가 매도', 'h10': '다음 날 시가 매수 → 10일째 종가 매도',
         'touch': '다음 날 시가 기준 +5% 에 −5% 보다 먼저 닿으면 맞음(보유일 없음)'}
DN_SC = {'h3': '다음 날 시가에 팔고 3일째 종가에 되삼(내림)', 'h5': '다음 날 시가에 팔고 5일째 종가에 되삼(내림)', 'h10': '다음 날 시가에 팔고 10일째 종가에 되삼(내림)',
         'touch': '다음 날 시가 기준 −5% 에 +5% 보다 먼저 닿으면 맞음(보유일 없음, 내림)'}
T2X_FAM = {'t2x_win': 72, 't2x_catch': 144, 't2x_first': 64, 't2x_delay': 96, 't2x_noprice': 72, 't2x_move8': 72, 't2x_t6': 72, 't2x_down': 92}      # 합계 684

# ---- T5 몫
NEW_CONDS = [
    ('e1', 'ra', 'hi', 'OW_ALL_wall_share', '전 결제월 합산 콜벽 비중 상위 10%'),
    ('e2', 'ra', 'ge2', 'OW_F3_wall_mig_up5', '넷째 결제월(원월) 콜벽이 5일 중 2일 이상 위로 옮김'),
    ('e3', 'ra', 'lo', 'OW_F0_callotm_oi', '근월물 외가격 콜 미결제 하위 10%'),
    ('e4', 'ra', 'hi', 'W_EWY_등락', 'EWY 등락 상위 10%'),
    ('f1', 'ra', 'fs', 1, '외국인 선물·현물 같은 날 동시 대량 순매도(둘 다 하위 10%)'),
    ('f3', 'ra', 'fs', 3, '외국인 선물·현물 3일 합 동시 대량 순매도(둘 다 하위 10%)'),
    ('f5', 'ra', 'fs', 5, '외국인 선물·현물 5일 합 동시 대량 순매도(둘 다 하위 10%)'),
]
RANK_KINDS = ('hi', 'lo', 'd5hi', 'd5lo', 'fs')
G_KO = {'ga': '신용·반대매매', 'na': '옵션 구조', 'da': '해외', 'ra': '추가(꼭지 전 지표·수급)'}
REGS = [('R3', '하락 추세(코스피 종가 ≤ 60일 평균)'), ('R8', '조정 중(60일 최고 대비 −5% 이하)'), ('R7', '5일 급등 뒤(5일 등락 > 지난 750일 표준편차의 1.5배)'), ('R9', '신고가 근처(60일 최고 대비 −1% 이내)')]
THRS = [('thr5', 0.95, '상·하위 5%'), ('thr20', 0.80, '상·하위 20%')]
WIN3 = (750, 360)
BASE_SCORES = ['h3', 'h5', 'h10', 't5']; NEW_SCORES = ['t3', 'ts']
SC_KO = {'h3': '3일째 종가에 되삼', 'h5': '5일째 종가에 되삼', 'h10': '10일째 종가에 되삼', 't5': '보유일 없이 시가 기준 −5% 에 먼저 닿으면 맞음(+5% 먼저면 틀림)',
         't3': '보유일 없이 시가 기준 −3% 에 먼저 닿으면 맞음(+3% 먼저면 틀림)', 'ts': '보유일 없이 시가 기준 −1.0σ√20 에 먼저 닿으면 맞음(+쪽 먼저면 틀림, σ = 직전 60일 표준편차)'}
SEL_EDGE, SEL_N = 0.10, 20
MODEL_YEARS = list(range(2013, 2027)); MIN_PREV = 200; MODEL_Q = [('q90', 0.90, '상위 10%'), ('q95', 0.95, '상위 5%')]
N_FIX_TOP = 100; MIN_N_FIX = 35
QUICK_YEARS = (2018, 2022, 2026)
QUICK_T5 = dict(ids=['a1', 'a5', 'a6', 'b1', 'b4', 'b5', 'b7', 'b8', 'b9', 'b10', 'c1', 'c7', 'c9', 'e1', 'e2', 'f3'], scores=['h5', 't5'], new_scores=['t3'], regs=['R3', 'R7'], thrs=['thr5'],
                model_years=list(range(2021, 2027)))
T5X_FULL = dict(fixed=4036, wf=262)
NOT_INCLUDED = [
    '[T2·T5 더 보기] 차원을 서로 곱한 것(8% 전환점 × 구간 20일, 장세 겹침 × 문턱 5%, 조건 짝 × 장세 등 — 이번에는 차원을 하나씩만 바꿈)',
    '[T2 더 보기] 내림 쪽의 다른 값(구간 3·20일, 20%·60% 잡기, 변동폭 맞춤 전환점)과 반대매매의 거울 방아쇠',
    '[T5 더 보기] 조건 3개 이상 조합, 짝 고르기의 다른 문턱(독립 30건·+5%p·+15%p), 짝 상위 1·20개',
    '[T5 더 보기] 확률 모형의 다른 입력(지표 434개 전부)·다른 문턱(상위 20%·고정 0.6)',
    '[T5 더 보기] 새 채점의 다른 폭(±2%·±7%, 0.5σ·2σ), 장세의 다른 정의(120일선·20일 고점)',
]
UNSOLVABLE = [
    '[T5] 실제 인버스 ETF 시세 기준 수익·청산 규칙 — 고정 자료에 인버스 ETF 시세가 없음(raw_main 의 etf_lev.csv 는 레버리지 ETF 한 종목의 2025-10 이후뿐). 확인 불가',
    '[T5] VVIX·SKEW — 고정 자료에서 두 열의 값이 날짜 숫자로 깨져 있음. 확인 불가',
]
MOVED = ['[T2] 방아쇠 두 개 이상 겹침 → W5', '[T2] 방아쇠 T8(변동성 꺾임)의 크기·자리 문턱 → W4', '[T5] 밤사이 미국 급등 뒤 다음 날 되밀림(1일 보유) → W7']


def n_parts():
    return 2


def _par(fn, argsets):
    """joblib 4코어. 프로세스 실행이 안 되는 환경이면 차례로 돈다(결과는 같다 — 씨앗이 해마다 고정)."""
    argsets = list(argsets)
    if NJ > 1 and len(argsets) > 1:
        try:
            from joblib import Parallel, delayed
            return Parallel(n_jobs=NJ)(delayed(fn)(*a) for a in argsets)
        except Exception as e:
            print('joblib 실패 → 차례로 계산:', repr(e)[:200], flush=True)
    return [fn(*a) for a in argsets]


# ====================================================================== T2 몫: 상태(조각 1)
def build_state_x(c, th, R, mj, lo_, cut, seed, nn, ev_kind='L', allow=None):
    """t2/run.py build_state 의 복사본 + 두 가지 차원: ev_kind('L' 저점 / 'H' 고점 = 꼭지 상태), allow(고를 수 있는 지표 표시 — None 이면 전부).
    ev_kind='L'·allow=None 이면 원래 함수와 같은 결과다(같은 씨앗·같은 순서)."""
    T2 = _T2(); n = len(c); rs = np.random.default_rng(seed)
    thc = th if np.isscalar(th) else th[:cut]
    ev = np.array([p for p, t in T2.zigzag(c[:cut], thc) if t == ev_kind and p >= lo_], dtype=int); E = len(ev); span = cut - lo_
    empty = dict(comps=[], k=2, E=E, score=np.zeros(n, np.int8), table=[])
    if E < T2.MIN_EV or span < 400: return empty
    lev = lambda pos: np.nanmean(R[pos - 1], 0)
    with np.errstate(invalid='ignore'), warnings.catch_warnings():
        warnings.simplefilter('ignore')
        real = lev(ev); nul = np.array([lev(lo_ + (ev - lo_ + int(s)) % span) for s in rs.integers(40, span - 40, size=nn)]); z = (real - np.nanmean(nul, 0)) / (np.nanstd(nul, 0) + 1e-9)
        ok = np.zeros(n, bool); ok[lo_:cut] = np.isfinite(R[lo_:cut, mj])
        for p in ev: ok[max(p - 10, 0):p + 1] = False
        b_all = np.clip(np.nan_to_num(R[:, mj]) // 10, 0, 9).astype(int); pool = [np.where(ok & (b_all == b))[0] for b in range(10)]; eb = b_all[ev - 1]; us = np.isfinite(R[ev - 1, mj])
        mn = np.array([lev(np.array([rs.choice(pool[b]) + 1 if u and len(pool[b]) else p for p, b, u in zip(ev, eb, us)])) for _ in range(nn)])
        ctrl = np.nanmean(mn, 0); zm = (real - ctrl) / (np.nanstd(mn, 0) + 1e-9)
        cover = np.isfinite(R[ev - 1]).mean(0); recent = np.isfinite(R[max(cut - 250, 0):cut]).mean(0)
        cand = [j for j in np.argsort(-np.abs(np.nan_to_num(zm))) if (allow is None or allow[j]) and np.isfinite(z[j]) and np.isfinite(zm[j]) and abs(z[j]) >= 3 and abs(zm[j]) >= 2.5
                and cover[j] >= 0.7 and recent[j] >= 0.9 and ((real[j] >= 55 and real[j] > ctrl[j]) or (real[j] <= 45 and real[j] < ctrl[j]))]
        Rt = pd.DataFrame(R[lo_:cut]); comps = []
        for j in cand:
            if any(abs(Rt[j].corr(Rt[q[0]])) > 0.8 for q in comps): continue
            comps.append((int(j), 'hi' if real[j] >= 55 else 'lo', round(float(real[j]), 1), round(float(ctrl[j]), 1), round(float(z[j]), 1), round(float(zm[j]), 1)))
            if len(comps) >= T2.MAXC: break
        score = np.zeros(n, np.int8)
        for j, side, *_ in comps: score += np.nan_to_num((R[:, j] >= T2.HI) if side == 'hi' else (R[:, j] <= T2.LO)).astype(np.int8)
    k = 2; table = []
    for kk in range(len(comps), 1, -1):
        on = np.zeros(n, bool); on[lo_:cut] = score[lo_:cut] >= kk
        caught = int(sum(on[max(p - T2.WIN, 0):p + 1].any() for p in ev)); table.append([kk, int(on.sum()), caught, E])
    for kk, _, caught, _ in table:
        if E and caught / E >= T2.CATCH: k = kk; break
    return dict(comps=comps, k=int(k), E=E, score=score, table=table)


def _state_job(var, Y, c, R, mj, lo_, cut, nn, allow, cols):
    T2 = _T2(); seed = C.SEED + Y
    if var == 'base': m = T2.build_state(c, T2.MOVE, R, mj, lo_, cut, seed, nn)
    elif var == 'mv8': m = T2.build_state(c, MOVE8, R, mj, lo_, cut, seed, nn)
    elif var == 'nop': m = build_state_x(c, T2.MOVE, R, mj, lo_, cut, seed, nn, 'L', allow)
    elif var == 'top': m = build_state_x(c, T2.MOVE, R, mj, lo_, cut, seed, nn, 'H', None)
    else: raise ValueError(var)
    m['comps'] = [(cols[j], side, a, b, z, zm) for j, side, a, b, z, zm in m['comps']]
    return var, Y, m


def noprice_allow(D):
    """고를 수 있는 지표 표시: 묶음 'price' 와 선물 가격 지표(PF_)를 뺀 것."""
    cols = list(D.X.columns)
    for c in cols:
        if c not in D.groups: raise RuntimeError(f'지표 {c} 의 묶음(groups)이 고정 자료에 없음')
    return np.array([not (D.groups[c] == 'price' or c.startswith('PF_')) for c in cols], dtype=bool)


def t2x_states(D, quick):
    T2 = _T2(); years = [y for y in C.WF_YEARS if (not quick or y in QUICK_YEARS)]
    R = T2.ranks(D.X); cols = list(D.X.columns); mj = cols.index(T2.MATCH); lo_ = int(D.td.searchsorted(C.START)) + 10; nn = 40 if quick else T2.NN
    allow = noprice_allow(D)
    jobs = [(v, Y, D.c, R, mj, lo_, int(np.where(D.year == Y)[0][0]), nn, allow, cols) for v in STATE_VARS for Y in years]
    res = _par(_state_job, jobs); ST = {v: {} for v in STATE_VARS}
    for v, Y, m in res: ST[v][int(Y)] = m
    return dict(kind='t2x', quick=bool(quick), years=years, states=ST, n_allow=int(allow.sum()), n_cols=len(cols))


# ====================================================================== T2 몫: 방아쇠·신호(merge)
def t6_var(D, mult, rk_thr, deadline):
    """방아쇠 T6(반대매매 정점 통과)의 값 바꾼 판. mult = 직전 5일 최고의 몇 배 이하(원래 0.7), rk_thr = 자리 문턱(원래 80), deadline = 대기 기한(거래일, None = 없음)."""
    x = D.X['C_반대매매_억']; rk = (x.rolling(250, min_periods=120).rank(pct=True) * 100).values; mx = x.rolling(5, min_periods=3).max().shift(1).values; x = x.values
    out = np.zeros(D.n, bool); armed = False; last = -1
    for t in range(D.n):
        if not np.isfinite(x[t]): continue
        if armed and deadline is not None and t - last > deadline: armed = False
        if armed and np.isfinite(mx[t]) and x[t] <= mult * mx[t]: out[t] = True; armed = False
        elif np.isfinite(rk[t]) and rk[t] >= rk_thr: armed = True; last = t
    return out


def down_triggers(D):
    """하락 방아쇠 7개(오름 방아쇠의 거울 꼴, 전체 기간 같은 정의). 모두 t일 장 마감 뒤 아는 값."""
    T2 = _T2(); c = D.c; lw = D.l; X = D.X; T = {}
    with np.errstate(invalid='ignore'):
        c1 = np.r_[np.nan, c[:-1]]; c2 = np.r_[np.nan, np.nan, c[:-2]]; l1 = np.r_[np.nan, lw[:-1]]; r = c / c1 - 1
        T[1] = (c < c1) & (c1 > c2)
        T[2] = c < l1
        T[3] = (c < c1) & (c1 < c2)
        T[4] = r <= -0.015
        ma = pd.Series(c).rolling(5).mean().values; ma1 = np.r_[np.nan, ma[:-1]]
        T[5] = (c < ma) & (c1 >= ma1)
        s5 = (X['S_외국인현물_5d'].rolling(250, min_periods=120).rank(pct=True) * 100).shift(1).values; s1 = X['S_외국인현물_1d'].values; s1p = np.r_[np.nan, s1[:-1]]
        T[7] = (s5 >= T2.HI) & (s1 < 0) & (s1p >= 0)
        v = X['V1_VKOSPI'].where(X['V1_VKOSPI'].notna(), X['M_VKOSPI']); vr = (v.rolling(250, min_periods=120).rank(pct=True) * 100).shift(1).values; v = v.values; v1 = np.r_[np.nan, v[:-1]]
        T[8] = (vr <= T2.LO) & (v / v1 - 1 >= 0.05)
    return {k: np.nan_to_num(np.asarray(a, float)).astype(bool) for k, a in T.items()}


def _k_catch(m, catch):
    k = 2
    for kk, _, caught, E in m['table']:
        if E and caught / E >= catch: k = kk; break
    return int(k)


def _on(ST, D, years, wins, catch=None):
    """상태 켜짐 구간(해 Y 규칙을 Y 년의 날에 — t2/run.py merge 와 같음). catch 를 주면 점수 문턱을 그 잡기 비율로 다시 정한다."""
    n = D.n; ON = {w: np.zeros(n, bool) for w in wins}; on0 = np.zeros(n, bool)
    for Y in years:
        m = ST[Y]; k = m['k'] if catch is None else _k_catch(m, catch)
        on = (m['score'] >= k) & (len(m['comps']) >= 2); iy = D.year == Y; on0[iy] = on[iy]
        for w in wins: ON[w][iy] = (pd.Series(on.astype(float)).rolling(w, min_periods=1).max().values > 0)[iy]
    return on0, ON


def _first_in_run(on, trig):
    """켜짐 구간(이어진 켜진 날 묶음)마다 방아쇠가 처음 나온 날의 위치."""
    start = on & ~np.r_[False, on[:-1]]; rid = np.cumsum(start); idx = np.where(on & trig)[0]
    if not len(idx): return idx
    r = rid[idx]
    return idx[np.r_[True, r[1:] != r[:-1]]]


def t2x_merge(D, P1, quick):
    T2 = _T2(); n = D.n; ST = P1['states']; years_all = [y for y in C.WF_YEARS if (not quick or y in QUICK_YEARS)]
    for v in STATE_VARS:
        miss = [y for y in years_all if y not in ST.get(v, {})]
        if miss: raise RuntimeError(f'T2 몫 상태 {v} 의 해 {miss} 결과가 조각에 없음')
    T = T2.triggers(D, False); TD = down_triggers(D); ywf = np.isin(D.year, years_all)
    if not np.array_equal(t6_var(D, 0.7, T2.HI, None), T[6]): raise RuntimeError('T6 복사본이 원래 정의와 다름')
    for Y in years_all:
        if _k_catch(ST['base'][Y], T2.CATCH) != ST['base'][Y]['k']: raise RuntimeError('점수 문턱 다시 셈이 원래와 다름')
    yu, exu = C.first_touch(D, T2.MOVE); up_touch = (yu, exu); dn_touch = (np.where(np.isfinite(yu), (yu == 0).astype(float), np.nan), exu)
    cands = []; rows = []

    def add(cid, fam, desc, pos, key, h, direction, delay=0, root='', params=None):
        pos = np.asarray(pos, dtype=int); y, ex = up_touch if direction > 0 else dn_touch
        if h is not None: tr = D.trades_from_pos(pos, h, delay)
        else:
            s = pos + delay; s = s[s < n]; s = s[np.isfinite(y[s])]
            tr = pd.DataFrame({'signal': D.td[s], 'exit': D.td[ex[s]], 'hit': y[s].astype(int)})
        sc = (UP_SC if direction > 0 else DN_SC)[key]
        c = dict(id=cid, family=fam, desc=f'{desc} → {sc}', direction=int(direction), hold=h, kind='wf', trades=tr, root=root, params=dict(params or {}, score=key, delay=delay))
        if h is None: c['base_y'] = y.astype(np.float32)
        cands.append(c)
        s_ = C.score(tr, direction, D.K); b = C.base_for(D, s_['t'], h or 1, direction, c.get('base_y')) if s_['n'] else None
        rows.append(dict(id=cid, 가족=fam, 설명=c['desc'], 채점=key, 방향=('오름' if direction > 0 else '내림'), 신호수=int(len(pos)), 독립거래=s_['n'], 맞음=s_['k'],
                         적중=(round(s_['hit'], 4) if s_['n'] >= 10 else None), 아무날=(round(b, 4) if b is not None else None),
                         차이=(round(s_['hit'] - b, 4) if (s_['n'] >= 10 and b is not None) else None)))

    st_txt = lambda w, extra='': f'바닥 전 상태{extra}(해마다 그 전 자료로 고른 지표 점수 ≥ 문턱)가 최근 {w}거래일 안에 켜짐'
    tr_txt = lambda j: ('방아쇠 없이 켜진 날 전부' if j == 0 else T2.TRIG[j])
    # ---- 기본 상태로 만드는 것: 구간 3·20일 / 20%·60% 잡기 / 첫 방아쇠만 / 하루 늦춤 / T6 의 다른 값
    _, ONb = _on(ST['base'], D, years_all, WINS_BASE + WINS_NEW)
    for w in WINS_NEW:
        for j in range(0, 9):
            pos = np.where(ONb[w] & (T[j] if j else True))[0]
            for key, h in T2_SCORES: add(f'T2x_win_S{w}_T{j}_{key}', 't2x_win', f'{st_txt(w)} + {tr_txt(j)}', pos, key, h, 1, root=f'바닥 전 상태 → {T2.SHORT[j]}', params=dict(win=w, trigger=j))
    for ct in CATCHES:
        _, ONc = _on(ST['base'], D, years_all, WINS_BASE, catch=ct); lab = f' — 점수 문턱은 저점의 {int(ct * 100)}% 를 잡는 값'
        for w in WINS_BASE:
            for j in range(0, 9):
                pos = np.where(ONc[w] & (T[j] if j else True))[0]
                for key, h in T2_SCORES:
                    add(f'T2x_catch{int(ct * 100)}_S{w}_T{j}_{key}', 't2x_catch', f'{st_txt(w, lab)} + {tr_txt(j)}', pos, key, h, 1, root=f'바닥 전 상태 → {T2.SHORT[j]}', params=dict(win=w, trigger=j, catch=ct))
    for w in WINS_BASE:
        for j in range(1, 9):
            pos = _first_in_run(ONb[w], T[j])
            for key, h in T2_SCORES:
                add(f'T2x_first_S{w}_T{j}_{key}', 't2x_first', f'{st_txt(w)} + {T2.TRIG[j]} — 그 켜짐 구간에서 처음 나온 날만', pos, key, h, 1, root=f'바닥 전 상태 → {T2.SHORT[j]}', params=dict(win=w, trigger=j, first=1))
    for arm in [f'S{w}' for w in WINS_BASE] + ['TO']:
        for j in range(1, 9):
            pos = np.where((ywf if arm == 'TO' else ONb[int(arm[1:])]) & T[j])[0]
            who = f'상태 없이 방아쇠만: {T2.TRIG[j]}' if arm == 'TO' else f'{st_txt(int(arm[1:]))} + {T2.TRIG[j]}'
            for key, h in T2_SCORES:
                add(f'T2x_delay_{arm}_T{j}_{key}', 't2x_delay', f'{who} — 하루 쉬고 그다음 날', pos, key, h, 1, delay=1,
                    root=(f'방아쇠만({T2.SHORT[j]})' if arm == 'TO' else f'바닥 전 상태 → {T2.SHORT[j]}'), params=dict(arm=arm, trigger=j))
    for tag, mult, rk, dl, txt in T6_VARS:
        t6 = t6_var(D, mult, rk, dl)
        for arm in [f'S{w}' for w in WINS_BASE] + ['TO']:
            pos = np.where((ywf if arm == 'TO' else ONb[int(arm[1:])]) & t6)[0]
            who = f'상태 없이 방아쇠만: 반대매매 정점 통과({txt})' if arm == 'TO' else f'{st_txt(int(arm[1:]))} + 반대매매 정점 통과({txt})'
            for key, h in T2_SCORES:
                add(f'T2x_t6_{tag}_{arm}_{key}', 't2x_t6', who, pos, key, h, 1, root=('방아쇠만(반대매매 정점 통과)' if arm == 'TO' else '바닥 전 상태 → 반대매매 정점 통과'),
                    params=dict(arm=arm, t6=tag))
    # ---- 다시 고른 상태: 가격 묶음 뺌 / 8% 전환점
    for v, fam, lab in (('nop', 't2x_noprice', ' — 지수·가격 묶음 지표를 빼고 고름'), ('mv8', 't2x_move8', ' — 전환 저점을 8% 기준으로')):
        _, ONv = _on(ST[v], D, years_all, WINS_BASE)
        for w in WINS_BASE:
            for j in range(0, 9):
                pos = np.where(ONv[w] & (T[j] if j else True))[0]
                for key, h in T2_SCORES:
                    add(f'T2x_{v}_S{w}_T{j}_{key}', fam, f'{st_txt(w, lab)} + {tr_txt(j)}', pos, key, h, 1, root=f'바닥 전 상태 → {T2.SHORT[j]}', params=dict(win=w, trigger=j, state=v))
    # ---- 내림: 꼭지 상태 → 하락 방아쇠
    _, ONt = _on(ST['top'], D, years_all, WINS_BASE)
    for w in WINS_BASE:
        for j in [0] + sorted(DN_TRIG):
            pos = np.where(ONt[w] & (TD[j] if j else True))[0]
            who = f'꼭지 전 상태(해마다 그 전 자료로 고른 지표 점수 ≥ 문턱)가 최근 {w}거래일 안에 켜짐 + ' + ('방아쇠 없이 켜진 날 전부' if j == 0 else DN_TRIG[j])
            for key, h in T2_SCORES: add(f'T2x_dn_S{w}_D{j}_{key}', 't2x_down', who, pos, key, h, -1, root=f'꼭지 상태 → {DN_SHORT[j]}', params=dict(win=w, trigger=j, state='top'))
    for j in sorted(DN_TRIG):
        pos = np.where(ywf & TD[j])[0]
        for key, h in T2_SCORES: add(f'T2x_dn_TO_D{j}_{key}', 't2x_down', f'상태 없이 하락 방아쇠만: {DN_TRIG[j]}', pos, key, h, -1, root=f'하락 방아쇠만({DN_SHORT[j]})', params=dict(arm='TO', trigger=j))
    fam = {}
    for c in cands: fam[c['family']] = fam.get(c['family'], 0) + 1
    if fam != T2X_FAM: raise RuntimeError(f'T2 몫 가짓수가 SPEC 과 다름: {fam}')
    # ---- 표: 해마다 고른 상태
    srows = []
    for v in STATE_VARS:
        on0, ONv = _on(ST[v], D, years_all, WINS_BASE)
        for Y in years_all:
            m = ST[v][Y]; iy = D.year == Y
            srows.append(dict(상태=STATE_KO[v], 해=Y, 그때까지_전환점수=m['E'], 조건수=len(m['comps']), 점수문턱_40=m['k'], 점수문턱_20=_k_catch(m, 0.20), 점수문턱_60=_k_catch(m, 0.60),
                              그해_점수켜진날=int(on0[iy].sum()), 그해_5일구간=int(ONv[5][iy].sum()), 그해_10일구간=int(ONv[10][iy].sum()),
                              지표=' · '.join(f"{nm}({'80 이상' if sd == 'hi' else '20 이하'})" for nm, sd, *_ in m['comps'])))
    return cands, fam, pd.DataFrame(srows), pd.DataFrame(rows)


# ====================================================================== T5 몫(조각 2)
def _rank_hi(s, win, minp):
    return s.rolling(win, min_periods=minp).rank(method='max', pct=True)


def build_pool(D, ids, top=0.9, win=250, minp=120):
    """조건 묶음(원래 31 + 새 7 가운데 ids). 반환 (M {id: bool 배열}, V {자리 조건 id: 자리 값 0~1}). top·win·minp 기본값이면 원래 31개는 t5/run.py 와 같다."""
    T5 = _T5(); X = D.X; n = D.n
    S = D.walls.drop_duplicates('date').set_index('date')['S'].astype(float).reindex(D.td)
    M = {}; V = {}
    for cid, grp, kind, col, _ in list(T5.CONDS) + NEW_CONDS:
        if cid not in ids: continue
        v = None
        if kind == 'hi': v = _rank_hi(X[col], win, minp)
        elif kind == 'lo': v = _rank_hi(-X[col], win, minp)
        elif kind == 'd5hi': v = _rank_hi(X[col].diff(5), win, minp)
        elif kind == 'd5lo': v = _rank_hi(-X[col].diff(5), win, minp)
        elif kind == 'fs':
            f = X['F_외국인_1d'].rolling(col, min_periods=col).sum(); s = X['S_외국인현물_1d'].rolling(col, min_periods=col).sum()
            rf = _rank_hi(-f, win, minp); rs = _rank_hi(-s, win, minp); v = pd.concat([rf, rs], axis=1).min(axis=1, skipna=False)
            m = (f < 0) & (s < 0) & (v >= top)
        elif kind == 'neg': m = X[col] < 0
        elif kind == 'ge2': m = X[col] >= 2
        elif kind in ('pbrk', 'cback'):
            same = X[f'OW_{col}_dte'].diff() < 0
            lv = lambda c_: (S * (1 + X[f'OW_{col}_{c_}'] / 100)).shift(1)
            ev = ((S < lv('pwall_dist%')) | (S < lv('pcent_dist%'))) if kind == 'pbrk' else (S < lv('passed_wall_dist%'))
            m = pd.Series(D.first_only((ev & same).fillna(False).values, 5), index=D.td)
        else: raise ValueError(kind)
        if kind in ('hi', 'lo', 'd5hi', 'd5lo'): m = v >= top
        M[cid] = np.asarray(m.fillna(False).values, dtype=bool)
        if v is not None: V[cid] = np.asarray(v.values, dtype=float)
        if len(M[cid]) != n: raise RuntimeError(f'조건 {cid} 길이가 거래일 수와 다름')
    return M, V


def regimes(D):
    """장세 4(코스피 종가, t일 마감 뒤 아는 값) — 갈래 D 의 R3·R8·R7·R9 와 같은 정의."""
    c = pd.Series(D.c, index=D.td); ma = c.rolling(60).mean(); hi = c.rolling(60).max(); dd = c / hi - 1
    r5 = c.pct_change(5); s5 = r5.rolling(750, min_periods=250).std()
    R = {'R3': (c <= ma) & ma.notna(), 'R8': (dd <= -0.05) & hi.notna(), 'R7': (r5 > 1.5 * s5) & s5.notna(), 'R9': (dd >= -0.01) & hi.notna()}
    return {k: np.asarray(v.fillna(False).values, dtype=bool) for k, v in R.items()}


def outcomes_x(D, scores):
    """채점마다 hit(내림 맞음 1/0/nan)·ex(청산 위치)·ret·hold. h3·h5·h10·t5 는 t5/run.py 그대로, t3 = ±3% 닿기, ts = ±1.0σ√20 닿기."""
    T5 = _T5(); T2 = _T2(); n = D.n; i = np.arange(n); O = T5.outcomes(D, [s for s in scores if s in BASE_SCORES])
    for sc in scores:
        if sc in O: continue
        if sc == 't3': y, ex = C.first_touch(D, 0.03)
        elif sc == 'ts': y, ex = T2.first_touch_var(D, T2.VOLK * T2.SQ20 * T2.sigma_prev(D.c))
        else: raise ValueError(sc)
        ok = np.isfinite(y); r = np.full(n, np.nan); r[ok] = D.c[ex[ok]] / D.o[i[ok] + 1] - 1
        O[sc] = {'hit': np.where(ok, (y == 0).astype(float), np.nan), 'ex': np.where(ok, ex, -1), 'ret': r, 'hold': None}
    return O


def fit_predict(Xtr, ytr, Xte):
    """t3/run.py·uni_model.py 와 같은 학습 함수(나무 + 선형). 설정은 그대로."""
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    ok = (np.isfinite(Xtr).sum(0) >= 60) & (np.nan_to_num(np.nanstd(Xtr, 0)) > 0)
    Xtr, Xte = Xtr[:, ok], Xte[:, ok]
    gb = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05, max_depth=3, min_samples_leaf=40, l2_regularization=1.0, max_bins=64, early_stopping=False, random_state=7)
    gb.fit(Xtr, ytr); pg = gb.predict_proba(Xte)[:, 1]
    keep = np.isfinite(Xtr).mean(0) >= 0.6
    A, B = Xtr[:, keep], Xte[:, keep]
    med = np.nanmedian(A, 0); lo = np.nanpercentile(A, 1, 0); hi = np.nanpercentile(A, 99, 0)
    prep = lambda M_: np.clip(np.where(np.isfinite(M_), M_, med), lo, hi)
    A, B = prep(A), prep(B); mu = A.mean(0); sd = A.std(0); sd[sd == 0] = 1
    lr = LogisticRegression(C=0.05, max_iter=400); lr.fit((A - mu) / sd, ytr); pl = lr.predict_proba((B - mu) / sd)[:, 1]
    return pg, pl


def _thr_by_year(p, year, q):
    out = np.full(len(p), np.nan)
    for Y in np.unique(year):
        prev = p[year < Y]; prev = prev[np.isfinite(prev)]
        if len(prev) >= MIN_PREV: out[year == Y] = np.quantile(prev, q)
    return out


def t5x_part(D, quick):
    T5 = _T5(); n = D.n
    info = {c[0]: c for c in list(T5.CONDS) + NEW_CONDS}
    ids = [c for c in info if (not quick or c in QUICK_T5['ids'])]
    scores = QUICK_T5['scores'] if quick else BASE_SCORES; new_scores = QUICK_T5['new_scores'] if quick else NEW_SCORES
    regs = [r for r in REGS if (not quick or r[0] in QUICK_T5['regs'])]; thrs = [t for t in THRS if (not quick or t[0] in QUICK_T5['thrs'])]
    new_ids = [c[0] for c in NEW_CONDS if c[0] in ids]; rank_ids = [c for c in ids if info[c][2] in RANK_KINDS]
    base, Vb = build_pool(D, ids)
    orig = T5.build_conds(D, [c[0] for c in T5.CONDS if c[0] in ids])
    for cid, m in orig.items():
        if not np.array_equal(m, base[cid]): raise RuntimeError(f'조건 {cid} 가 원래 T5 정의와 다름')
    for cid in ids:
        if info[cid][2] in ('hi', 'lo', 'd5hi', 'd5lo', 'neg', 'ge2') and not D.X[info[cid][3]].loc[C.START:].notna().any(): raise RuntimeError(f'조건 {cid} 의 열 {info[cid][3]} 에 값이 없음')
    O = outcomes_x(D, scores + new_scores); RG = regimes(D)
    since = np.asarray(D.td >= C.START); wfm = np.isin(D.year, C.WF_YEARS)
    EB = {sc: {y: since & T5.exit_before(D, O[sc], pd.Timestamp(f'{y}-01-01')) & np.isfinite(O[sc]['hit']) for y, _ in C.wf_splits()} for sc in O}
    gk = lambda cid: G_KO[info[cid][1]]
    tail = lambda sc: f"다음 날 시가에 팔고 {SC_KO[sc]}(내림)"
    fam = {}; frows = []; FIX = {}; wf_cands = []; wrows = []; srows = []

    def count(f, k=1): fam[f] = fam.get(f, 0) + k

    def fixed(fid, f, desc, mask, sc, root, params):
        s = T5.stat(D, mask, O[sc], since); count(f)
        frows.append(dict(id=fid, family=f, desc=desc, score=sc, sig=s['sig'], n=s['n'], k=s['k'], hit=s['hit'], base=s['base'], edge=(s['hit'] - s['base'] if s['n'] else None), mean=s['mean']))
        FIX[fid] = (f, desc, mask, sc, root, params)

    def wf(wid, f, desc, mask, sc, root, params):
        count(f)
        c = dict(id=wid, family=f, desc=desc, direction=-1, hold=O[sc]['hold'], kind='wf', trades=T5.trades(D, mask, O[sc], wfm), root=root, params=dict(params, score=sc))
        if O[sc]['hold'] is None: c['base_y'] = O[sc]['hit'].astype(np.float32)
        wf_cands.append(c); s = T5.stat(D, mask, O[sc], wfm)
        wrows.append(dict(id=wid, family=f, desc=desc, score=sc, sig=s['sig'], n=s['n'], k=s['k'], hit=s['hit'], base=s['base'], edge=(s['hit'] - s['base'] if s['n'] else None), mean=s['mean']))

    def proc_B(pool, sc, tag):
        o = O[sc]; b1 = np.zeros(n, bool); b2 = np.zeros(n, bool)
        for y, _ in C.wf_splits():
            tr = EB[sc][y]; b = float(o['hit'][tr].mean()) if tr.any() else np.nan; picked = []
            for cid in ids:
                kp = T5.thin(np.where(pool[cid] & tr)[0], o['ex'])
                if len(kp) >= SEL_N and float(o['hit'][kp].mean()) >= b + SEL_EDGE - 1e-12: picked.append(cid)
            cnt = np.sum([pool[c] for c in picked], axis=0) if picked else np.zeros(n, dtype=int); iny = D.year == y
            b1 |= iny & (cnt >= 1); b2 |= iny & (cnt >= 2)
            srows.append(dict(절차=f'{tag}_B', year=y, score=sc, train_base=b, n_picked=len(picked), picked=' '.join(picked)))
        return b1, b2

    def cons_and_B(var, lab, pool, scs, fam_c, fam_b, do_cons=True):
        if do_cons:
            G = T5.build_cons(pool)
            for g, d in T5.CONS:
                for sc in scs: wf(f'T5x_{var}_A_{g}_{sc}', fam_c, f'[합의{lab}] {d} → {tail(sc)}', G[g], sc, '하락 조건 합의', dict(var=var, cons=g))
        for sc in scs:
            b1, b2 = proc_B(pool, sc, var)
            for tg, m, d in (('any1', b1, '하나라도 켜진 날'), ('any2', b2, '2개 이상 켜진 날')):
                wf(f'T5x_{var}_B_{tg}_{sc}', fam_b, f'[해마다 고름{lab}] 그 전 자료에서 내림 적중이 아무 날보다 10%p 이상 높던(독립 20건 이상) 조건({len(ids)}개 묶음) 가운데 {d} → {tail(sc)}',
                   m, sc, '하락 조건 해마다 고름', dict(var=var, proc=tg))

    # ---- 새 조건 단독 + 38개 묶음 절차 B
    for cid in new_ids:
        for sc in scores: fixed(f'T5x_new_{cid}_{sc}', 't5x_new', f'[{gk(cid)}] {info[cid][4]} → {tail(sc)}', base[cid], sc, f'하락 조건({gk(cid)})', dict(var='new', cond=cid))
    cons_and_B('new', '', base, scores, None, 't5x_newB', do_cons=False)
    # ---- 장세 겹침
    for rk, rd in regs:
        pool = {c: base[c] & RG[rk] for c in ids}
        for cid in ids:
            for sc in scores: fixed(f'T5x_{rk}_{cid}_{sc}', 't5x_reg', f'[{gk(cid)}] {info[cid][4]} + {rd} → {tail(sc)}', pool[cid], sc, f'하락 조건({gk(cid)}) + 장세', dict(var=rk, cond=cid))
        cons_and_B(rk, f' + {rd}', pool, scores, 't5x_regcons', 't5x_regB')
    # ---- 문턱 5%·20%
    for tk, tv, tl in thrs:
        pool, _ = build_pool(D, ids, top=tv)
        for cid in rank_ids:
            for sc in scores:
                fixed(f'T5x_{tk}_{cid}_{sc}', 't5x_thr', f"[{gk(cid)}] {info[cid][4].replace('10%', f'{int(round((1 - tv) * 100))}%')} → {tail(sc)}", pool[cid], sc, f'하락 조건({gk(cid)})', dict(var=tk, cond=cid))
        cons_and_B(tk, f', 문턱 {tl}', pool, scores, 't5x_thrcons', 't5x_thrB')
    # ---- 순위 창 3년
    pool, _ = build_pool(D, ids, win=WIN3[0], minp=WIN3[1])
    for cid in rank_ids:
        for sc in scores: fixed(f'T5x_win3y_{cid}_{sc}', 't5x_win', f'[{gk(cid)}] {info[cid][4]} (자리를 지난 750거래일로) → {tail(sc)}', pool[cid], sc, f'하락 조건({gk(cid)})', dict(var='win3y', cond=cid))
    cons_and_B('win3y', ', 자리를 지난 750거래일로', pool, scores, 't5x_wincons', 't5x_winB')
    # ---- 하루 늦춤
    pool = {c: np.r_[False, base[c][:-1]] for c in ids}
    for cid in ids:
        for sc in scores: fixed(f'T5x_delay_{cid}_{sc}', 't5x_delay', f'[{gk(cid)}] {info[cid][4]} + 하루 쉬고 → 그다음 날 시가에 팔고 {SC_KO[sc]}(내림)', pool[cid], sc, f'하락 조건({gk(cid)})', dict(var='delay', cond=cid))
    cons_and_B('delay', ', 하루 늦춤', pool, scores, 't5x_delaycons', 't5x_delayB')
    # ---- 새 채점(±3%·변동폭 맞춤 닿기)
    for cid in ids:
        for sc in new_scores: fixed(f'T5x_touch_{cid}_{sc}', 't5x_touch', f'[{gk(cid)}] {info[cid][4]} → {tail(sc)}', base[cid], sc, f'하락 조건({gk(cid)})', dict(var='touch', cond=cid))
    cons_and_B('touch', '', base, new_scores, 't5x_touchcons', 't5x_touchB')
    # ---- 조건 짝(AND)
    pairs = list(itertools.combinations(ids, 2)); PM = np.array([base[a] & base[b] for a, b in pairs], dtype=bool)
    for pi, (a, b) in enumerate(pairs):
        for sc in scores:
            fixed(f'T5x_pair_{a}_{b}_{sc}', 't5x_pair', f'[짝] {info[a][4]} + {info[b][4]} (같은 날 둘 다) → {tail(sc)}', PM[pi], sc, '하락 조건 짝', dict(var='pair', cond=f'{a}+{b}'))
    for sc in scores:
        o = O[sc]; a1 = np.zeros(n, bool); t5m = np.zeros(n, bool)
        for y, _ in C.wf_splits():
            tr = EB[sc][y]; b = float(o['hit'][tr].mean()) if tr.any() else np.nan; picked = []
            for pi in np.flatnonzero((PM & tr).sum(1) >= SEL_N):
                kp = T5.thin(np.where(PM[pi] & tr)[0], o['ex'])
                if len(kp) >= SEL_N:
                    p = float(o['hit'][kp].mean())
                    if p >= b + SEL_EDGE - 1e-12: picked.append((p - b, len(kp), int(pi)))
            iny = D.year == y
            if picked:
                top = sorted(picked, key=lambda x: (-x[0], -x[1], x[2]))[:5]
                a1 |= iny & PM[[x[2] for x in picked]].any(0); t5m |= iny & PM[[x[2] for x in top]].any(0)
            srows.append(dict(절차='pairwf', year=y, score=sc, train_base=b, n_picked=len(picked),
                              picked=' '.join('+'.join(pairs[x[2]]) for x in sorted(picked, key=lambda x: (-x[0], -x[1], x[2]))[:5]) + (' …' if len(picked) > 5 else '')))
        for tg, m, d in (('any1', a1, '하나라도 켜진 날'), ('top5', t5m, '차이 큰 순 5개 중 하나라도 켜진 날')):
            wf(f'T5x_pairwf_{tg}_{sc}', 't5x_pairwf', f'[짝을 해마다 고름] 그 전 자료에서 내림 적중이 아무 날보다 10%p 이상 높던(독립 20건 이상) 조건 짝({len(pairs)}쌍 묶음) 가운데 {d} → {tail(sc)}',
               m, sc, '하락 조건 짝 해마다 고름', dict(var='pairwf', proc=tg))
    # ---- 확률 모형
    F = np.column_stack([Vb[c] if c in Vb else base[c].astype(float) for c in ids]); i0 = int(D.td.searchsorted(C.START)); idx = np.arange(n)
    myears = QUICK_T5['model_years'] if quick else MODEL_YEARS; mrows = []
    for sc in scores:
        y = O[sc]['hit']; ex = O[sc]['ex']; P = np.full(n, np.nan)
        for Y in myears:
            te = np.where(D.year == Y)[0]
            if not len(te): continue
            a = te[0]; tr = np.where((idx >= i0) & (idx < a) & np.isfinite(y) & (ex >= 0) & (ex < a))[0]
            if len(tr) < 400 or len(set(y[tr])) < 2: mrows.append(dict(score=sc, year=Y, n_train=int(len(tr)), fit='학습 표본 부족')); continue
            pg, pl = fit_predict(F[tr], y[tr], F[te]); P[te] = (pg + pl) / 2; mrows.append(dict(score=sc, year=Y, n_train=int(len(tr)), fit='ok'))
        if not np.isfinite(P).any(): raise RuntimeError(f'확률 모형({sc}) 예측이 하나도 없음')
        for qk, qv, ql in MODEL_Q:
            thr = _thr_by_year(P, D.year, qv); m = wfm & np.isfinite(P) & np.isfinite(thr) & (P >= thr)
            wf(f'T5x_model_{qk}_{sc}', 't5x_model', f'[확률 모형] 하락 조건 {len(ids)}개를 입력으로 해마다 다시 학습한 모형(나무·선형 평균)의 내릴 확률이 그 전 예측의 {ql} 선 이상 → {tail(sc)}',
               m, sc, '하락 확률 모형', dict(var='model', q=qv))
    # ---- 넘길 fixed 후보: 전체 기간 독립 35건 이상 중 내림 적중 상위 100 + 새 조건 단독 h5
    FA = pd.DataFrame(frows)
    for col in ('hit', 'base', 'edge', 'mean'): FA[col] = pd.to_numeric(FA[col], errors='coerce')
    okf = FA[FA['n'] >= MIN_N_FIX].sort_values(['hit', 'n', 'id'], ascending=[False, False, True]).head(N_FIX_TOP)
    pick = list(okf['id']) + [f'T5x_new_{cid}_h5' for cid in new_ids if 'h5' in scores and f'T5x_new_{cid}_h5' not in set(okf['id'])]
    fx_cands = []
    for fid in pick:
        f, desc, mask, sc, root, params = FIX[fid]
        c = dict(id=fid, family=f, desc=desc, direction=-1, hold=O[sc]['hold'], kind='fixed', trades=T5.trades(D, mask, O[sc], since), root=root, params=dict(params, score=sc))
        if O[sc]['hold'] is None: c['base_y'] = O[sc]['hit'].astype(np.float32)
        fx_cands.append(c)
    m_fixed = int(len(FA)); m_wf = int(len(wf_cands))
    if not quick and (m_fixed, m_wf) != (T5X_FULL['fixed'], T5X_FULL['wf']): raise RuntimeError(f'T5 몫 가짓수가 SPEC 과 다름: fixed {m_fixed} · wf {m_wf}')
    return dict(kind='t5x', quick=bool(quick), cands=wf_cands + fx_cands, fam=fam, m_fixed=m_fixed, m_wf=m_wf, n_ids=len(ids), n_pairs=len(pairs),
                fixed_all=FA.to_csv(index=False), wf=pd.DataFrame(wrows).to_csv(index=False), selected=pd.DataFrame(srows).to_csv(index=False), model=pd.DataFrame(mrows).to_csv(index=False))


# ====================================================================== 약속된 함수
def run_part(k, n, quick=False):
    D = C.Data()
    if k == 1: return t2x_states(D, quick)
    if k == 2: return t5x_part(D, quick)
    raise ValueError(f'조각 번호 {k} 는 없음(1~{n_parts()})')


def _pc(x): return '–' if x is None or (isinstance(x, float) and not np.isfinite(x)) else f'{100 * x:.1f}%'


def _md(head, rows):
    return ['| ' + ' | '.join(head) + ' |', '|' + '---|' * len(head)] + ['| ' + ' | '.join(str(v) for v in r) + ' |' for r in rows]


def _best(df, ncol, hcol, bcol, dcol, top=12, nmin=30):
    """독립 nmin 건 이상인 것 가운데 아무 날과의 차이가 큰 순."""
    d = df[(df[ncol] >= nmin) & df[hcol].notna() & df[bcol].notna()].copy()
    if not len(d): return []
    d['_e'] = d[hcol].astype(float) - d[bcol].astype(float); d = d.sort_values(['_e', ncol], ascending=[False, False]).head(top)
    return [[r[dcol], int(r[ncol]), _pc(float(r[hcol])), _pc(float(r[bcol])), f"{100 * r['_e']:+.1f}%p"] for _, r in d.iterrows()]


def merge(parts, quick=False, out_dir=None):
    """parts = [조각 1(T2 몫 상태), 조각 2(T5 몫)]. 하나라도 없으면 멈춘다(조용히 넘기지 않음). (cands, meta) 반환."""
    import io
    parts = list(parts or [])
    if len(parts) != n_parts() or any(p is None for p in parts): raise RuntimeError(f'W6 앞쪽: 조각 결과가 없음({[i + 1 for i, p in enumerate(parts) if p is None] or "개수 다름"}) — 합치지 않고 멈춤')
    P1, P2 = parts
    if P1.get('kind') != 't2x' or P2.get('kind') != 't5x': raise RuntimeError('W6 앞쪽: 조각 순서·종류가 다름')
    if bool(P1.get('quick')) != bool(quick) or bool(P2.get('quick')) != bool(quick): raise RuntimeError('W6 앞쪽: 조각이 quick 여부가 다른 계산에서 나옴')
    D = C.Data()
    c2, fam2, S_state, S_cmp = t2x_merge(D, P1, quick)
    c5 = P2['cands']; fam5 = dict(P2['fam'])
    FA = pd.read_csv(io.StringIO(P2['fixed_all'])); WF = pd.read_csv(io.StringIO(P2['wf'])); SEL = pd.read_csv(io.StringIO(P2['selected'])); MOD = pd.read_csv(io.StringIO(P2['model']))
    cands = c2 + c5; ids_ = [c['id'] for c in cands]
    if len(set(ids_)) != len(ids_): raise RuntimeError('W6 앞쪽: 후보 id 가 겹침')
    fam = {**fam2, **fam5}; n2 = int(sum(fam2.values())); n5 = int(sum(fam5.values())); n_tested = n2 + n5
    m_wf = n2 + int(P2['m_wf']); m_fixed = int(P2['m_fixed'])
    if not quick and (n_tested, m_wf, m_fixed) != (4982, 946, 4036): raise RuntimeError(f'W6 앞쪽 가짓수가 SPEC 과 다름: {n_tested}·{m_wf}·{m_fixed}')
    if not cands or not n_tested: raise RuntimeError('W6 앞쪽: 후보 0개 — 비정상')
    # ---- 요약 글
    q = ' [quick 시험 — 해·조건·채점 일부]' if quick else ''
    M = [f'### W6 앞쪽 — T2·T5 의 "안 넣은 것"{q}', '',
         f'- 시험 {n_tested:,}가지 = T2 몫 {n2:,}(전부 해마다 고르는 절차) + T5 몫 {n5:,}(고정 규칙 {m_fixed:,} · 해마다 고르는 절차 {int(P2["m_wf"]):,}). 차원은 하나씩만 바꿨다.',
         f'- 해마다 고르는 절차가 {m_wf:,}개라 가짓수 보정 뒤 가짜 시험(2,000번)은 셈으로 넘을 수 없다(W8 참고 분석이 따로 잰다).',
         '- 적중은 독립 거래 기준, 같은 채점 방식의 같은 해 아무 날과 견준다. 표본 10건 미만은 %를 적지 않는다.', '',
         '#### (1) 가족별 가짓수와 "아무 날보다 높은" 수(독립 30건 이상)', '']
    rows = []
    for f, k in fam2.items():
        g = S_cmp[S_cmp['가족'] == f]; g30 = g[(g['독립거래'] >= 30) & g['차이'].notna()]
        rows.append([f, '해마다(wf)', k, len(g30), int((g30['차이'] > 0).sum()), int((g30['차이'] >= 0.10).sum())])
    for f, k in fam5.items():
        g = (FA if f in set(FA['family']) else WF); g = g[g['family'] == f]; g30 = g[(g['n'] >= 30) & g['edge'].notna()]
        rows.append([f, ('고정(fixed) — 전체 기간, 결과를 보고 고르는 숫자' if f in set(FA['family']) else '해마다(wf)'), k, len(g30), int((g30['edge'] > 0).sum()), int((g30['edge'] >= 0.10).sum())])
    M += _md(['가족', '종류', '가짓수', '독립 30건 이상', '그중 아무 날보다 높음', '그중 +10%p 이상'], rows)
    M += ['', '#### (2) T2 몫 — 아무 날과의 차이가 큰 순(독립 30건 이상, 2016~2026)', '']
    b = _best(S_cmp, '독립거래', '적중', '아무날', '설명'); M += _md(['절차', '독립 거래', '적중', '같은 해 아무 날', '차이'], b) if b else ['- 독립 30건 이상인 절차 없음']
    M += ['', '#### (3) T5 몫(내림) 해마다 고르는 절차 — 아무 날과의 차이가 큰 순(독립 30건 이상, 2016~2026)', '']
    b = _best(WF, 'n', 'hit', 'base', 'desc'); M += _md(['절차', '독립 거래', '내림 적중', '같은 해 아무 날', '차이'], b) if b else ['- 독립 30건 이상인 절차 없음']
    M += ['', '#### (4) T5 몫(내림) 고정 규칙 — 전체 기간(2010~) 차이가 큰 순(독립 35건 이상). **결과를 보고 고른 숫자 — 다음 해 성적과 섞어 읽지 말 것**', '']
    b = _best(FA, 'n', 'hit', 'base', 'desc', nmin=MIN_N_FIX); M += _md(['규칙', '독립 거래', '내림 적중', '같은 해 아무 날', '차이'], b) if b else ['- 독립 35건 이상인 규칙 없음']
    M += ['', '#### (5) 다시 고른 상태(T2 몫) — 해마다 고른 지표 수와 점수 문턱', '']
    M += _md(['상태', '해', '그때까지 전환점', '조건 수', '문턱(40%·20%·60% 잡기)', '그 해 켜진 날(당일/5일/10일 구간)'],
             [[r['상태'], r['해'], r['그때까지_전환점수'], r['조건수'], f"{r['점수문턱_40']}·{r['점수문턱_20']}·{r['점수문턱_60']}", f"{r['그해_점수켜진날']}/{r['그해_5일구간']}/{r['그해_10일구간']}"] for _, r in S_state.iterrows()])
    M += ['', '#### (6) 계산으로 풀 수 없던 것 · 다른 줄기가 맡은 것', ''] + [f'- {x}' for x in UNSOLVABLE] + [f'- (다른 줄기) {x}' for x in MOVED]
    tabs = {'a_t2x_state_by_year.csv': S_state, 'a_t2x_compare.csv': S_cmp, 'a_t5x_fixed_all.csv': FA, 'a_t5x_wf.csv': WF, 'a_t5x_selected.csv': SEL, 'a_t5x_model_fit.csv': MOD}
    if out_dir:
        os.makedirs(os.path.join(out_dir, 'tables'), exist_ok=True)
        for nm, df in tabs.items(): df.to_csv(os.path.join(out_dir, 'tables', nm), index=False, encoding='utf-8')
    notes = ['W6 앞쪽(T2·T5 의 "안 넣은 것"): 원래 정의는 그대로 두고 차원을 하나씩만 바꿨다. T2 몫은 전부 해마다 고르는 절차(상태를 해마다 다시 고름), T5 몫의 조건 단독·짝은 전체 기간 고정 규칙(결과를 보고 고르는 숫자).',
             f'가짓수: T2 몫 {n2:,} + T5 몫 {n5:,} = {n_tested:,}. 해마다 고르는 절차 {m_wf:,}개 — 가짓수 보정 뒤 가짜 시험은 셈으로 넘을 수 없다.',
             'T5 몫 fixed 후보는 4,036개 가운데 전체 기간 내림 적중 상위 100개(독립 35건 이상)와 새 조건 단독 7개(h5)만 넘겼다. 전부는 tables/a_t5x_fixed_all.csv.'] + \
            [f'확인 불가: {x}' for x in UNSOLVABLE]
    ys = sorted(P1['states']['base']); same = [y for y in ys if [c[:2] for c in P1['states']['nop'][y]['comps']] == [c[:2] for c in P1['states']['base'][y]['comps']]]
    notes.append(f"가격 묶음을 뺀 상태(t2x_noprice): {len(ys)}해 가운데 {len(same)}해는 기본 상태와 고른 지표가 똑같다(기본 상태가 원래 가격 지표를 고르지 않은 해) — 그 해의 신호는 원래 T2 와 같다.")
    if quick: notes.append('quick 시험 결과 — 해·조건·채점 일부, 가짓수도 그만큼만.')
    meta = dict(n_tested=n_tested, families=fam, m_fixed=m_fixed, m_wf=m_wf, m_by={'T2x': {'wf': n2}, 'T5x': {'wf': int(P2['m_wf']), 'fixed': m_fixed}},
                not_included=list(NOT_INCLUDED), unsolvable=list(UNSOLVABLE), moved=list(MOVED), parts_failed=[], notes=notes, tables=list(tabs), summary_md='\n'.join(M) + '\n')
    return cands, meta


def main():
    a = C.parse_part(); N = n_parts()
    if a['nparts']: print(N); return
    if a['part']:
        i, n = a['part']; C.save_part(TRACK, i, n, run_part(i, n, quick=a['quick'])); print(f'{TRACK} 조각 {i}/{n} 끝'); return
    if a['merge']:
        od = os.path.join(C.track_dir(TRACK), 'out')
        cands, meta = merge(C.load_parts(TRACK, N), quick=a['quick'], out_dir=od)
        open(os.path.join(od, 'summary.md'), 'w', encoding='utf-8').write(meta['summary_md'])
        C.save_result(TRACK, cands, meta); print(f"{TRACK} 합침: 후보 {len(cands)}개 · 시험 {meta['n_tested']:,}가지 · wf 절차 {meta['m_wf']}개 · fixed 모집단 {meta['m_fixed']:,}"); return
    print('사용: python part_a.py --nparts | --part i/n | --merge [--quick]')


if __name__ == '__main__':
    main()
