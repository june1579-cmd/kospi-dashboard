# -*- coding: utf-8 -*-
"""Signal A 2차 W6 뒤쪽 — T3·T4·T6 SPEC 의 '안 넣은 것'. SPEC_b.md 그대로 구현한다(돌린 뒤 격자·문턱을 고치지 않는다).

  T3x A1~A11  합의·확률의 안 넣은 것(내림 방향, 문턱의 다른 꼴, 확률 보정, 설정 탐색, 합의 격자, 합의 비율 입력, 보유 1·20일, 묶음별 모형, F2·F3·위클리 사건, 조건 쌍)
  T4x B1~B4   변동폭 맞춤의 안 넣은 것(T2·T3 변동폭판의 창·배수, 변동폭 자리 조건, T5 변동폭판)
  T6x C1~C5   청산의 안 넣은 것(추적 손절, 분할, 변동폭 손절·익절, 반대 신호 청산, 고르는 기준) — 등급 없는 비교라 후보로 넘기지 않고 표만
1차 줄기의 정의는 t2·t3·t5·t6 의 run.py 를 고치지 않고 다른 이름으로 불러 쓴다(_load). 조각 7개, 조각이 완성된 후보·표를 돌려주고 merge 는 잇고 센다.
명령(혼자 시험용, 줄기 이름 w6b): python part_b.py --nparts | --part i/n | --merge  [--quick]
총괄의 w6/run.py 가 부르는 함수: n_parts() · run_part(k, n, quick) · merge(parts, quick, out_dir) → (cands, meta)
"""
import importlib.util
import io
import math
import os
import sys
import time
import types
import warnings

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__)); SA = os.path.dirname(HERE)
for _p in (HERE, SA):
    if _p not in sys.path: sys.path.insert(0, _p)
# joblib 일꾼 프로세스도 이 파일과 sa_common 을 찾을 수 있게
os.environ['PYTHONPATH'] = os.pathsep.join([HERE, SA] + [p for p in os.environ.get('PYTHONPATH', '').split(os.pathsep) if p and p not in (HERE, SA)])
import sa_common as C  # noqa: E402

warnings.filterwarnings('ignore')
if __name__ != '__main__' and __name__ in sys.modules:      # 다른 이름으로 불려도 joblib 일꾼이 이 파일의 함수를 쓸 수 있게(값으로 넘김)
    try:
        from joblib.externals import cloudpickle as _cp
        _cp.register_pickle_by_value(sys.modules[__name__])
    except Exception:
        pass
TRACK = 'w6b'
NJ = max(1, min(int(os.environ.get('SA_JOBS', '4')), os.cpu_count() or 1))
HS = (3, 5, 10)
HS_X = (1, 20)                                   # A8 보유일 1·20일
MODELS = ('gb', 'lr', 'ens')
MODEL_NAME = {'gb': '나무 모형', 'lr': '선형 모형', 'ens': '나무·선형 평균'}
SETN = {'all': '입력 전부(434개)', 'allev': '입력 전부+사건 지표', 'opt': '옵션 묶음 지표만', 'fut': '선물 묶음 지표만',
        'allev2': '입력 전부+사건 지표+F2·F3·위클리 사건 지표 20개', 'allevc': '입력 전부+사건 지표+합의 비율 2개'}
QS = (0.90, 0.95)
MODEL_YEARS = list(range(2013, 2027)); QUICK_MODEL_YEARS = [2024, 2025, 2026]
MIN_PREV = 200
TH_FORMS = ('q80', 'f60', 'r3q90', 'r3q95')      # A3
TH_NAME = {'q80': '그 전 예측의 상위 20% 선 이상', 'f60': '0.60 이상(고정 문턱)', 'r3q90': '직전 3개 해 예측의 상위 10% 선 이상', 'r3q95': '직전 3개 해 예측의 상위 5% 선 이상'}
CAL_THR = (0.60, 0.65)                           # A4
CFGS = [('base', dict(max_depth=3, learning_rate=0.05, l2=1.0)), ('d2', dict(max_depth=2, learning_rate=0.05, l2=1.0)),
        ('d4', dict(max_depth=4, learning_rate=0.05, l2=1.0)), ('lr02', dict(max_depth=3, learning_rate=0.02, l2=1.0)),
        ('lr10', dict(max_depth=3, learning_rate=0.10, l2=1.0)), ('l2x10', dict(max_depth=3, learning_rate=0.05, l2=10.0))]   # A5
BASE_SELS = {'s60': ('hit', 0.60, 30), 'w50': ('wil', 50)}
BASE_THRS = {'f20': ('f', 0.20), 'p95': ('p', 0.95)}
SEL_NAME = {'s60': '과거 적중 60% 이상·독립 30건 이상인 조건', 'w50': '과거 윌슨 하한 상위 50개 조건', 's65': '과거 적중 65% 이상·독립 30건 이상인 조건',
            's70': '과거 적중 70% 이상·독립 30건 이상인 조건', 'ps60': '상위 50개 조건의 쌍 가운데 과거 적중 60% 이상·독립 30건 이상인 쌍', 'pw50': '상위 50개 조건의 쌍 가운데 과거 윌슨 하한 상위 50쌍'}
THR_NAME = {'f20': '20% 이상이 함께 켜진 날', 'p95': '함께 켜진 비율이 그 전 자료의 상위 5% 선 이상인 날', 'f10': '10% 이상이 함께 켜진 날', 'f30': '30% 이상이 함께 켜진 날',
            'any': '하나라도 켜진 날'}
CG_VARS = {'pos10': dict(win=250, minp=125, hi=0.9, lo=0.1, ko='자리 문턱 10%(상·하위 10%)'), 'pos30': dict(win=250, minp=125, hi=0.7, lo=0.3, ko='자리 문턱 30%(상·하위 30%)'),
           'win120': dict(win=120, minp=60, hi=0.8, lo=0.2, ko='순위 창 120일'), 'win500': dict(win=500, minp=250, hi=0.8, lo=0.2, ko='순위 창 500일')}   # A6 (가)
T2V = [(20, 1.0), (120, 1.0), (60, 0.5), (60, 2.0)]       # B1 (σ 창, 배수)
T3V = [(20, 0.5), (120, 0.5), (60, 0.25), (60, 1.0)]      # B2
REG = {'hi': '변동폭 큰 날(20일 변동폭 자리 0.8 이상)', 'lo': '변동폭 작은 날(20일 변동폭 자리 0.2 이하)'}   # B3
TRAILS = (0.02, 0.03, 0.05); MAXHOLDS = (5, 10, 20)       # C1
SPLIT_H = ((1, 3), (1, 5), (3, 5), (3, 10), (5, 10), (5, 20), (10, 20)); SPLIT_TP = (0.02, 0.03, 0.05)   # C2
VOL_MULT = (None, 1.0, 2.0)                               # C3
OPP_H = (10, 20)                                          # C4
N_NEW = len(TRAILS) * len(MAXHOLDS) + len(SPLIT_H) + len(SPLIT_TP) * len(MAXHOLDS) + (len(VOL_MULT) ** 2 - 1) * len(MAXHOLDS) + 5 * len(OPP_H)   # 59 (오름 대상)
N_CRIT = 3
COST = 0.0015
# SPEC 4절의 절차 수(문법 확인 때도 맞는지 본다)
M_T3X = (len(HS) * 2 * 3 * 2) + (len(HS) * (4 + 1)) + (len(HS) * 2 * 3 * len(TH_FORMS)) + (len(HS) * 2 * 3 * len(CAL_THR)) + (len(HS) * 2) \
    + (len(CG_VARS) * 12 + 12 + 12) + (len(HS) * 3 * 2) + (len(HS_X) * 2 * 3 * 2 + len(HS_X) * 5) + (len(HS) * 2 * 3 * 2) + (len(HS) * 3 * 2 + len(HS) * 4) + (len(HS) * 5)
M_T4X = 104 * len(T2V) + 51 * len(T3V) + (8 * 2 * 3 + 2 * 3 + 2 * 3) + 7
assert (M_T3X, M_T4X, N_NEW) == (370, 687, 59), 'SPEC_b.md 4절 가짓수와 다름'
NOT_INCLUDED = [
    'T1 가족(128,640개)의 변동폭판을 σ 창 60·120일로 다시 돌리기(T1 변동폭판은 60일 σ 를 쓰지 않고, σ 띠의 다른 꼴은 W1 이 함)',
    '조건 3개 조합의 합의, 전체 조건(893개)의 모든 쌍(여기서는 해마다 윌슨 하한 상위 50개 조건의 쌍만)',
    '합의 격자를 서로 곱한 조합(자리 × 창 × 적중 문턱 × 합의 문턱 — 여기서는 한 번에 하나만 바꿈), 문턱의 다른 꼴·확률 보정을 묶음별·새 사건 모형에도 적용하기',
    '모형 설정 탐색을 선형 모형·다른 묶음·더 넓은 격자(나무 수·잎 크기)로, 다른 모형(신경망 등)',
    'T5 변동폭판의 다른 배수(±0.5σ·±2σ)',
    '청산: 추적 손절·분할을 변동폭 단위로, 여러 가족을 겹친 청산(추적 손절 + 반대 신호), 분할 청산의 비용을 편도마다 따로 매기기',
]
UNSOLVABLE = [
    "위클리 사건 지표의 '물량 5일 증가'(위클리 시리즈는 상장~만기가 5~6거래일 → 전일 대비 증가로 바꿔 넣음; 목 위클리 2019-09·월 위클리 2023-08 부터만 값이 있음)",
    '실제 체결가 기준 청산 수익(지수는 시가·손절선 가격에 사고팔 수 없어 어림 — T6 과 같음), 인버스·선물 시세 기준(CRITERIA 2절 밖)',
    'VVIX·SKEW 를 쓰는 조건(고정 자료에서 값이 깨져 빈칸 — 가짓수에는 세지만 켜지지 않음)',
]


# ------------------------------------------------------------------ 1차 줄기 코드를 다른 이름으로 불러오기(고치지 않음)
def _load(track, alias=None, **patch):
    name = alias or f'w6b_{track}'
    if name not in sys.modules:
        p = os.path.join(SA, track, 'run.py')
        if not os.path.exists(p): raise FileNotFoundError(f'{p} 가 없음')
        spec = importlib.util.spec_from_file_location(name, p); m = importlib.util.module_from_spec(spec); sys.modules[name] = m
        spec.loader.exec_module(m)
        for k, v in patch.items(): setattr(m, k, v)
    return sys.modules[name]


def _new_out(name):
    return dict(name=name, cands=[], fam={}, tables={}, md=[], notes=[], t0=time.time())


def _fam(o, fam, n):
    o['fam'][fam] = o['fam'].get(fam, 0) + int(n)


def _tab(o, name, rows):
    df = rows if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
    o['tables'][name] = pd.concat([o['tables'][name], df], ignore_index=True) if name in o['tables'] else df


def _cand(D, cid, fam, desc, direction, h, pos, root, y=None, ex=None, params=None):
    """wf 후보 하나. y 를 주면 보유일 없는 채점(먼저 닿기): hit 칸과 base_y 를 넣는다."""
    pos = np.asarray(sorted(set(int(p) for p in np.asarray(pos).ravel())), dtype=int)
    if y is None:
        tr = D.trades_from_pos(pos, h)
    else:
        pos = pos[np.isfinite(y[pos]) & (ex[pos] >= 0)] if len(pos) else pos
        tr = pd.DataFrame({'signal': D.td[pos], 'exit': D.td[ex[pos]], 'hit': y[pos].astype(int)})
    c = dict(id=cid, family=fam, desc=desc, direction=int(direction), hold=h, kind='wf', trades=tr, root=root, params=params or {})
    if y is not None: c['base_y'] = np.asarray(y, dtype=np.float32)
    return c


# ------------------------------------------------------------------ 확률 모형(해마다 다시 학습) — t3 의 fit_predict 그대로
def _fit_gb(Xtr, ytr, Xte, cfg):
    from sklearn.ensemble import HistGradientBoostingClassifier
    ok = (np.isfinite(Xtr).sum(0) >= 60) & (np.nan_to_num(np.nanstd(Xtr, 0)) > 0)
    gb = HistGradientBoostingClassifier(max_iter=200, learning_rate=cfg['learning_rate'], max_depth=cfg['max_depth'], min_samples_leaf=40, l2_regularization=cfg['l2'],
                                        max_bins=64, early_stopping=False, random_state=7)
    gb.fit(Xtr[:, ok], ytr)
    return gb.predict_proba(Xte[:, ok])[:, 1]


def _fit_job(M, y, ex, i0, a, te, cfg):
    idx = np.arange(len(y)); tr = np.where((idx >= i0) & (idx < a) & np.isfinite(y) & (ex >= 0) & (ex < a))[0]   # 청산이 그 해 첫날보다 앞인 날만
    if len(tr) < 400 or len(set(y[tr])) < 2: return te, None, None
    if cfg is None:
        pg, pl = _load('t3').fit_predict(M[tr], y[tr], M[te])
    else:
        pg, pl = _fit_gb(M[tr], y[tr], M[te], cfg), None
    return te, pg, pl


def model_probs(D, M, y, ex, quick, cfg=None):
    """날짜별 표본 밖 확률 {gb, lr, ens}(cfg 를 주면 그 설정의 나무 모형 gb 만). 학습은 해마다 그 전 자료로만."""
    from joblib import Parallel, delayed
    M = np.ascontiguousarray(np.asarray(M, dtype=float)); i0 = int(D.td.searchsorted(C.START))
    jobs = [(int(te[0]), te) for te in (np.where(D.year == Y)[0] for Y in (QUICK_MODEL_YEARS if quick else MODEL_YEARS)) if len(te)]
    res = Parallel(n_jobs=NJ)(delayed(_fit_job)(M, y, ex, i0, a, te, cfg) for a, te in jobs)
    P = {'gb': np.full(D.n, np.nan), 'lr': np.full(D.n, np.nan)}
    for te, pg, pl in res:
        if pg is not None: P['gb'][te] = pg
        if pl is not None: P['lr'][te] = pl
    if not np.isfinite(P['gb']).any(): raise RuntimeError('확률 모형이 한 해도 학습되지 않음(자료 확인)')
    if cfg is None: P['ens'] = (P['gb'] + P['lr']) / 2
    return P


def thr_q(p, year, q, look=None):
    """해 Y 의 문턱 = Y 이전 표본 밖 예측(look 이 있으면 직전 look 개 해만)의 q 분위. 200개 미만이면 빈칸(신호 없음)."""
    out = np.full(len(p), np.nan)
    for Y in np.unique(year):
        m = (year < Y) if look is None else ((year < Y) & (year >= Y - look))
        prev = p[m]; prev = prev[np.isfinite(prev)]
        if len(prev) >= MIN_PREV: out[year == Y] = np.quantile(prev, q)
    return out


def calibrate(D, p, y, ex):
    """A4: 해 Y 마다 그 전 표본 밖 예측(청산이 Y 전)으로 isotonic 보정한 확률."""
    from sklearn.isotonic import IsotonicRegression
    pc = np.full(len(p), np.nan); idx = np.arange(len(p))
    for Y in C.WF_YEARS:
        te = np.where((D.year == Y) & np.isfinite(p))[0]
        if not len(te) or not (D.year == Y).any(): continue
        a = int(np.where(D.year == Y)[0][0]); m = (idx < a) & np.isfinite(p) & np.isfinite(y) & (ex >= 0) & (ex < a)
        if m.sum() < MIN_PREV or len(set(y[m])) < 2: continue
        iso = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds='clip').fit(p[m], y[m]); pc[te] = iso.predict(p[te])
    return pc


def _auc(y, p, m):
    from sklearn.metrics import roc_auc_score
    m = m & np.isfinite(p) & np.isfinite(y)
    return float(roc_auc_score(y[m], p[m])) if m.sum() > 50 and len(set(y[m])) == 2 else None


def k200_close(D):
    return D.walls.drop_duplicates('date').set_index('date')['S'].astype(float).reindex(D.td)


def weekly_wall(D, kind):
    """위클리(wt 목·wm 월) 그날 콜벽 = 코스피200 종가 위 콜 미결제 최대 행사가(연구소 a04.weekly_walls 와 같은 뜻). 원자료를 못 읽으면 멈춘다."""
    p = os.path.join(C.raw_dir('deriv'), 'deriv', 'data', f'opt_chain{kind}_daily.csv.gz')
    if not os.path.exists(p): raise FileNotFoundError(f'위클리 옵션 원자료가 없음: {p}')
    c = pd.read_csv(p, usecols=['날짜', 'cp', 'exp', 'K', 'oi'], low_memory=False)
    c['date'] = pd.to_datetime(c['날짜']); c = c[(c['cp'] == 'C') & (c['date'] <= C.END)].dropna(subset=['K'])
    if not len(c): raise RuntimeError(f'위클리 옵션 원자료가 비어 있음: {p}')
    c['K'] = c['K'].astype(float); c['oi'] = pd.to_numeric(c['oi'], errors='coerce').fillna(0.0); c['exp'] = c['exp'].astype(str)
    oi_all = c.drop_duplicates(['date', 'exp', 'K'], keep='last').set_index(['date', 'exp', 'K'])['oi']
    S = k200_close(D); live = c[c['oi'] > 0].copy(); live['S'] = live['date'].map(S)
    live['first'] = live.groupby('exp')['date'].transform('min')
    live = live[live['first'] == live.groupby('date')['first'].transform('min')]            # 하루에 시리즈가 둘이면 먼저 상장된 것
    live = live[live['K'] > live['S']]; live = live[live.groupby('date')['K'].transform('size') >= 2]
    w = live.sort_values(['date', 'oi', 'K'], ascending=[True, False, True]).drop_duplicates('date').set_index('date')[['exp', 'K', 'S', 'oi']].reindex(D.td)
    prev = pd.Series(D.td, index=D.td).shift(1)
    key = pd.MultiIndex.from_arrays([prev.values, w['exp'].astype(object).values, w['K'].values])
    w['oi_prev'] = oi_all.reindex(key).values
    return w


def events_extra(D):
    """A10: 새 사건 지표 20개(F2·F3 각 5 + 목·월 위클리 각 5). 값이 없는 날은 0."""
    X = D.X; E = {}
    for t in ('F2', 'F3'):
        dist = X[f'OW_{t}_wall_dist%']; oi5 = X[f'OW_{t}_wall_oi_chg5%']; n15 = (dist > 0) & (dist <= 1.5); up = oi5 > 0
        E[f'EV_{t}_near15'] = n15; E[f'EV_{t}_near30'] = (dist > 0) & (dist <= 3.0); E[f'EV_{t}_new'] = X[f'OW_{t}_wall_new'] == 1
        E[f'EV_{t}_oi5up'] = up; E[f'EV_{t}_near15_oi5up'] = n15 & up
    for t, kind in (('WT', 'wt'), ('WM', 'wm')):
        w = weekly_wall(D, kind); dist = (w['K'] / w['S'] - 1) * 100; n15 = (dist > 0) & (dist <= 1.5)
        new = w['K'].notna() & w['K'].shift(1).notna() & (w['K'] != w['K'].shift(1)); up = w['oi'] > w['oi_prev']
        E[f'EV_{t}_near15'] = n15; E[f'EV_{t}_near30'] = (dist > 0) & (dist <= 3.0); E[f'EV_{t}_new'] = new
        E[f'EV_{t}_oi1up'] = up; E[f'EV_{t}_near15_oi1up'] = n15 & up
    out = pd.DataFrame({k: np.asarray(v, dtype=bool) for k, v in E.items()}, index=D.td).astype(float)
    assert out.shape[1] == 20
    return out


def vol_regime(D):
    """B3: 20일 변동폭의 지난 250거래일(120일 이상, 그날 포함) 자리. hi = 0.8 이상, lo = 0.2 이하."""
    rk = pd.Series(D.c).pct_change().rolling(20).std().rolling(250, min_periods=120).rank(pct=True).values
    with np.errstate(invalid='ignore'):
        return {'hi': np.nan_to_num(rk >= 0.8).astype(bool), 'lo': np.nan_to_num(rk <= 0.2).astype(bool)}


# ------------------------------------------------------------------ 합의(t3.cons_part 와 같은 계산을 격자·방향·쌍까지 넓힌 것)
def conditions_x(D, quick, win=250, minp=125, hi=0.8, lo=0.2, extra=None):
    """조건 = 지표 × 자리 2(높음·낮음) + 사건 지표 25개(+ extra). win=250·minp=125·hi=0.8·lo=0.2 면 t3.conditions 와 같다."""
    T3 = _load('t3'); cols = T3.base_cols(D, quick); i_from = max(0, int(D.td.searchsorted(C.START)) - win - 5)
    R = D.X[cols].iloc[i_from:].rolling(win, min_periods=minp).rank(pct=True).reindex(D.td)
    E = T3.events(D, False); arrs = [(R >= hi).values, (R <= lo).values, E.values > 0]
    names = [f'{c}|높음' for c in cols] + [f'{c}|낮음' for c in cols] + list(E.columns)
    if extra is not None: arrs.append(extra.values > 0); names += list(extra.columns)
    return np.concatenate(arrs, axis=1), names


def _thin(pos, ex):
    keep = []; last = -1
    for p in pos:
        if p >= last: keep.append(p); last = ex[p]
    return np.asarray(keep, dtype=int)


def _wlb(k, n, z=C.Z90):
    n = np.maximum(n, 1e-9); p = k / n; d = 1 + z * z / n; c = p + z * z / (2 * n); h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (c - h) / d


def cons_engine(D, B, hs, tgt, years, sels, thrs, any_sel=None, want_frac=False, pairs=False, label=''):
    """해마다(years) 그 전 자료로 조건을 고르고(sels) 켜진 비율의 문턱(thrs)으로 신호를 낸다.
    tgt(h) → (y 1/0/nan = 그 방향으로 맞았나, ex 청산 위치). 반환 dict(sig{(h, 고르는 꼴, 문턱): 신호 위치}, rows, frac{(h, 꼴): 그 해에 쓰던 조건의 켜진 비율}, n_pairs)."""
    n = D.n; nc = B.shape[1]; i0 = int(D.td.searchsorted(C.START)); order = np.arange(nc)
    starts = {Y: int(np.where(D.year == Y)[0][0]) for Y in years if (D.year == Y).any()}
    sig = {}; rows = []; frac_out = {}; n_pairs = 0
    def put(key, d): sig.setdefault(key, []).append(np.asarray(d, dtype=int))
    for h in hs:
        y, ex = tgt(h); valid = np.isfinite(y) & (ex >= 0); valid[:i0] = False
        kept = [_thin(np.flatnonzero(B[:, j] & valid), ex) for j in range(nc)]             # 처음부터 차례로 솎으므로 어느 해에서 잘라도 그때까지와 같다
        exk = [ex[k] for k in kept]; cy = [np.cumsum(y[k]) for k in kept]
        for s in sels:
            for t in thrs: sig.setdefault((h, s, t), [])
            if s == any_sel: sig.setdefault((h, s, 'any'), [])
            if want_frac: frac_out[(h, s)] = np.full(n, np.nan)
        if pairs:
            for s in ('ps60', 'pw50'):
                for t in BASE_THRS: sig.setdefault((h, s, t), [])
            sig.setdefault((h, 'ps60', 'any'), [])
        for Y, a in starts.items():
            cnt = np.array([int(np.searchsorted(e, a)) for e in exk]); nn = cnt.astype(float)
            kk = np.array([c[m - 1] if m else 0.0 for c, m in zip(cy, cnt)])
            hit = np.where(nn > 0, kk / np.maximum(nn, 1), np.nan); lb = np.where(nn > 0, _wlb(kk, nn), -1.0)
            te = np.where(D.year == Y)[0]; picked = {}
            for s, spec in sels.items():
                if spec[0] == 'hit': ix = np.where((nn >= spec[2]) & (hit >= spec[1]))[0]
                else: ix = np.lexsort((order, -nn, -lb))[:spec[1]]; ix = ix[nn[ix] > 0]
                picked[s] = ix
                if not len(ix):
                    rows.append(dict(variant=label, year=Y, h=h, sel=s, n_sel=0)); continue
                frac = B[:, ix].mean(1); prev = frac[i0:a]
                if want_frac: frac_out[(h, s)][te] = frac[te]
                r = dict(variant=label, year=Y, h=h, sel=s, n_sel=int(len(ix)), past_hit=round(float(kk[ix].sum() / max(nn[ix].sum(), 1)), 4))
                for t, ts in thrs.items():
                    if ts[0] == 'f': d = te[frac[te] >= ts[1]]
                    else:
                        qv = float(np.quantile(prev, ts[1])) if len(prev) else np.inf; d = te[(frac[te] >= qv) & (frac[te] > 0)]
                    put((h, s, t), d); r[f'days_{t}'] = int(len(d))
                if s == any_sel:
                    d = te[frac[te] > 0]; put((h, s, 'any'), d); r['days_any'] = int(len(d))
                rows.append(r)
            if pairs:                                                                      # A11: w50 의 모든 쌍을 그 전 자료로 다시 채점
                ix = picked.get('w50', np.zeros(0, dtype=int)); pa, pb = np.triu_indices(len(ix), 1); n_pairs += len(pa)
                r = dict(variant='pair', year=Y, h=h, sel='pairs', n_sel=int(len(pa)))
                if len(pa):
                    A = B[:, ix]; Av = A[:a] & valid[:a, None]; pn = np.zeros(len(pa)); pk = np.zeros(len(pa))
                    for q_, (i_, j_) in enumerate(zip(pa, pb)):
                        kp = _thin(np.flatnonzero(Av[:, i_] & Av[:, j_]), ex); kp = kp[ex[kp] < a]; pn[q_] = len(kp); pk[q_] = y[kp].sum()
                    ph = np.where(pn > 0, pk / np.maximum(pn, 1), np.nan); plb = np.where(pn > 0, _wlb(pk, pn), -1.0)
                    psel = {'ps60': np.where((pn >= 30) & (ph >= 0.60))[0]}
                    o_ = np.lexsort((np.arange(len(pa)), -pn, -plb))[:50]; psel['pw50'] = o_[pn[o_] > 0]
                    for s, sx in psel.items():
                        r[f'n_{s}'] = int(len(sx))
                        if not len(sx): continue
                        frac = (A[:, pa[sx]] & A[:, pb[sx]]).mean(1); prev = frac[i0:a]
                        put((h, s, 'f20'), te[frac[te] >= 0.20]); qv = float(np.quantile(prev, 0.95)) if len(prev) else np.inf
                        put((h, s, 'p95'), te[(frac[te] >= qv) & (frac[te] > 0)])
                        if s == 'ps60': put((h, s, 'any'), te[frac[te] > 0])
                rows.append(r)
    sig = {k: (np.concatenate(v) if v else np.zeros(0, dtype=int)) for k, v in sig.items()}
    return dict(sig=sig, rows=rows, frac=frac_out, n_pairs=int(n_pairs), nc=int(nc))


def _cons_desc(pre, s, t, post):
    if t == 'any': return f'{pre}{SEL_NAME[s]}(해마다 그 전 자료로 고름) 가운데 하나라도 켜진 날 → {post}'
    return f'{pre}{SEL_NAME[s]}(해마다 그 전 자료로 고름) 가운데 {THR_NAME[t]} → {post}'


# ------------------------------------------------------------------ 조각 1~3: 보유일 h 하나의 확률 모형 변형(A1·A3·A4·A5·A7·A9·A10 모형·B3 다)
def part_h(D, h, quick):
    T3 = _load('t3'); o = _new_out(f'h{h}'); y, ex = T3.target(D, h, False); yr = D.year; ev = yr >= 2016
    cols = T3.base_cols(D, quick); EV = T3.events(D, False); XA = D.X[cols]; XE = pd.concat([XA, EV], axis=1)
    # A7 입력: 그 해에 쓰던 조건(s60·w50)의 켜진 비율 — 해마다 그 전 자료로 고른 조건으로 그 해 값만 채운다
    B, _ = conditions_x(D, quick)
    ce = cons_engine(D, B, (h,), lambda hh: (y, ex), ([2025, 2026] if quick else list(range(2012, 2027))), BASE_SELS, {}, want_frac=True, label='input')
    CF = pd.DataFrame({'CF_s60': ce['frac'][(h, 's60')], 'CF_w50': ce['frac'][(h, 'w50')]}, index=D.td)
    grp = lambda g: [c for c in D.X.columns if D.groups.get(c) == g][:(30 if quick else None)]
    feats = {'all': XA, 'allev': XE, 'opt': D.X[grp('opt')], 'fut': D.X[grp('fut')], 'allev2': pd.concat([XE, events_extra(D)], axis=1), 'allevc': pd.concat([XE, CF], axis=1)}
    for g in ('opt', 'fut'):
        if feats[g].shape[1] < 10: raise RuntimeError(f'{g} 묶음 지표를 찾지 못함(D.groups 확인)')
    use = ['allev', 'opt', 'allev2', 'allevc'] if quick else list(feats)
    P = {s: model_probs(D, feats[s].values, y, ex, quick) for s in use}
    post = f'{h}일 보유'; mrows = []

    def add(cid, fam, desc, direction, on, root, params):
        o['cands'].append(_cand(D, cid, fam, desc, direction, h, np.where(on)[0], root, params=params))
    for s in use:
        for m in MODELS:
            p = P[s][m]; fin = ev & np.isfinite(p); who = f'확률 모형({MODEL_NAME[m]}, {SETN[s]}, 해마다 다시 학습)'
            ok = ev & np.isfinite(p) & np.isfinite(y)
            mrows.append(dict(h=h, set=s, model=m, n_days=int(ok.sum()), base_up=(round(float(y[ok].mean()), 4) if ok.any() else None), auc=_auc(y, p, ev)))
            if s in ('all', 'allev'):
                for q in QS:                                                           # A1 내림 방향 확률
                    qn = int(round(q * 100)); thr = thr_q(p, yr, 1 - q)
                    add(f'T3x_DN_P_h{h}_{s}_{m}_q{qn}', 'T3x 내림 확률', f'{who} 오를 확률이 그 전 예측의 하위 {100 - qn}% 선 이하 → {post}, 내림', -1,
                        fin & np.isfinite(thr) & (p <= thr), '내림 확률·합의', dict(h=h, set=s, model=m, q=q, item='A1'))
                for f in TH_FORMS:                                                     # A3 문턱의 다른 꼴
                    if f == 'f60': on = fin & (p >= 0.60)
                    else:
                        thr = thr_q(p, yr, {'q80': 0.80, 'r3q90': 0.90, 'r3q95': 0.95}[f], look=(3 if f.startswith('r3') else None)); on = fin & np.isfinite(thr) & (p >= thr)
                    add(f'T3x_TH_h{h}_{s}_{m}_{f}', 'T3x 문턱의 다른 꼴', f'{who} 오를 확률이 {TH_NAME[f]} → {post}', 1, on, '확률 모형(오를 확률 상위)', dict(h=h, set=s, model=m, form=f, item='A3'))
                pc = calibrate(D, p, y, ex)                                           # A4 확률 보정
                for c_ in CAL_THR:
                    add(f'T3x_CAL_h{h}_{s}_{m}_c{int(round(c_ * 100))}', 'T3x 확률 보정',
                        f'{who} 오를 확률을 해마다 그 전 예측과 실제 결과로 보정(isotonic)한 값이 {c_:.2f} 이상 → {post}', 1, ev & np.isfinite(pc) & (pc >= c_),
                        '확률 모형(오를 확률 상위)', dict(h=h, set=s, model=m, cal=c_, item='A4'))
            else:                                                                      # A7·A9·A10: 기본 문턱(q90·q95)
                fam, pre, item = {'opt': ('T3x 묶음별 모형', 'GRP', 'A9'), 'fut': ('T3x 묶음별 모형', 'GRP', 'A9'), 'allev2': ('T3x F2·F3·위클리 사건 모형', 'EV_P', 'A10'),
                                  'allevc': ('T3x 합의 비율 입력 모형', 'CIN', 'A7')}[s]
                for q in QS:
                    qn = int(round(q * 100)); thr = thr_q(p, yr, q)
                    add(f'T3x_{pre}_h{h}_{s}_{m}_q{qn}', fam, f'{who} 오를 확률이 그 전 예측의 상위 {100 - qn}% 선 이상 → {post}', 1, fin & np.isfinite(thr) & (p >= thr),
                        '확률 모형(오를 확률 상위)', dict(h=h, set=s, model=m, q=q, item=item))
    _fam(o, 'T3x A1 내림 확률', sum(c['params'].get('item') == 'A1' for c in o['cands'])); _fam(o, 'T3x A3 문턱의 다른 꼴', sum(c['params'].get('item') == 'A3' for c in o['cands']))
    _fam(o, 'T3x A4 확률 보정', sum(c['params'].get('item') == 'A4' for c in o['cands'])); _fam(o, 'T3x A7 합의 비율 입력 모형', sum(c['params'].get('item') == 'A7' for c in o['cands']))
    _fam(o, 'T3x A9 묶음별 모형', sum(c['params'].get('item') == 'A9' for c in o['cands'])); _fam(o, 'T3x A10 F2·F3·위클리 사건(모형)', sum(c['params'].get('item') == 'A10' for c in o['cands']))
    # A5 모형 설정 탐색(나무 모형·allev): 해마다 그 전 표본 밖 AUC 가 가장 높은 설정
    cfgs = CFGS[:2] if quick else CFGS; PC = {'base': P['allev']['gb']}
    for nm, cfg in cfgs[1:]: PC[nm] = model_probs(D, XE.values, y, ex, quick, cfg=cfg)['gb']
    idx = np.arange(D.n); psel = np.full(D.n, np.nan); thr = {q: np.full(D.n, np.nan) for q in QS}; prow = []
    for Y in C.WF_YEARS:
        te = yr == Y
        if not te.any(): continue
        a = int(np.where(te)[0][0]); best = 'base'; bauc = None; aucs = {}
        for nm, _ in cfgs:
            p = PC[nm]; m = (idx < a) & np.isfinite(p) & np.isfinite(y) & (ex >= 0) & (ex < a)
            au = _auc(y, p, m) if m.sum() >= MIN_PREV else None; aucs[nm] = au
            if au is not None and (bauc is None or au > bauc + 1e-12): best, bauc = nm, au
        psel[te] = PC[best][te]; prev = PC[best][yr < Y]; prev = prev[np.isfinite(prev)]
        for q in QS:
            if len(prev) >= MIN_PREV: thr[q][te] = np.quantile(prev, q)
        prow.append(dict(year=Y, h=h, picked=best, **{f'auc_{k}': (None if v is None else round(v, 4)) for k, v in aucs.items()}))
    for q in QS:
        qn = int(round(q * 100))
        add(f'T3x_CFG_h{h}_q{qn}', 'T3x 모형 설정 탐색', f'확률 모형(나무 모형, {SETN["allev"]}, 설정 {len(cfgs)}개 가운데 해마다 그 전 표본 밖 구분력(AUC)이 가장 높은 것) 오를 확률이 그 설정의 그 전 예측 상위 {100 - qn}% 선 이상 → {post}',
            1, ev & np.isfinite(psel) & np.isfinite(thr[q]) & (psel >= thr[q]), '확률 모형(오를 확률 상위)', dict(h=h, q=q, item='A5'))
    _fam(o, 'T3x A5 모형 설정 탐색(새 설정×보유일 + 절차)', (len(cfgs) - 1) + len(QS))
    # B3 (다): 확률 모형(allev·ens·q90) 신호 × 변동폭 큰·작은 날
    VR = vol_regime(D); p = P['allev']['ens']; t90 = thr_q(p, yr, 0.90); base_on = ev & np.isfinite(p) & np.isfinite(t90) & (p >= t90)
    for g in ('hi', 'lo'):
        add(f'T4x_VC_P_h{h}_{g}', 'T4x 변동폭 자리 조건', f'확률 모형({MODEL_NAME["ens"]}, {SETN["allev"]}) 오를 확률이 그 전 예측의 상위 10% 선 이상 + {REG[g]} → {post}', 1, base_on & VR[g],
            '변동폭 자리 조건', dict(h=h, regime=g, item='B3'))
    _fam(o, 'T4x B3 변동폭 자리 조건', 2)
    _tab(o, 'b_t3x_models.csv', mrows); _tab(o, 'b_t3x_cfg_pick.csv', prow)
    o['md'] += [f"- 보유 {h}일 모형 설정 탐색(A5): 해마다 고른 설정 = " + ' / '.join(f"{r['year']} {r['picked']}" for r in prow)]
    return o


# ------------------------------------------------------------------ 조각 4: 보유 1·20일 모형(A8) + 합의 전부(A2·A6·A8·A10·A11) + B3 (가)(나)
def part_cons(D, quick):
    T3 = _load('t3'); T2 = _load('t2'); o = _new_out('cons'); yr = D.year; ev = yr >= 2016
    hs = (5,) if quick else HS; hx = (1,) if quick else HS_X; years = [2025, 2026] if quick else C.WF_YEARS
    tg = {}
    def tgt(h): return tg.setdefault(h, T3.target(D, h, False))
    def tgt_dn(h):
        y, ex = tgt(h); return np.where(np.isfinite(y), 1.0 - y, np.nan), ex
    add = lambda cid, fam, desc, d, h, pos, root, item: o['cands'].append(_cand(D, cid, fam, desc, d, h, pos, root, params=dict(h=h, item=item)))
    # A8 보유 1·20일 확률 모형
    cols = T3.base_cols(D, quick); EV = T3.events(D, False); mrows = []
    for h in hx:
        y, ex = tgt(h)
        for s in (('allev',) if quick else ('all', 'allev')):
            M = D.X[cols] if s == 'all' else pd.concat([D.X[cols], EV], axis=1); P = model_probs(D, M.values, y, ex, quick)
            for m in MODELS:
                p = P[m]; ok = ev & np.isfinite(p) & np.isfinite(y)
                mrows.append(dict(h=h, set=s, model=m, n_days=int(ok.sum()), base_up=(round(float(y[ok].mean()), 4) if ok.any() else None), auc=_auc(y, p, ev)))
                for q in QS:
                    qn = int(round(q * 100)); thr = thr_q(p, yr, q)
                    add(f'T3x_H_P_h{h}_{s}_{m}_q{qn}', 'T3x 보유일 1·20일 모형', f'확률 모형({MODEL_NAME[m]}, {SETN[s]}, 해마다 다시 학습) 오를 확률이 그 전 예측의 상위 {100 - qn}% 선 이상 → {h}일 보유',
                        1, h, np.where(ev & np.isfinite(p) & np.isfinite(thr) & (p >= thr))[0], '확률 모형(오를 확률 상위)', 'A8')
    n_a8p = len(o['cands']); _tab(o, 'b_t3x_models.csv', mrows)
    B, names = conditions_x(D, quick); nc = B.shape[1]; srows = []
    # 기본 조건 묶음 한 번: A6 (나)(다) + A11 쌍
    e = cons_engine(D, B, hs, tgt, years, {**BASE_SELS, 's65': ('hit', 0.65, 30), 's70': ('hit', 0.70, 30)}, {**BASE_THRS, 'f10': ('f', 0.10), 'f30': ('f', 0.30)},
                    pairs=True, label='base'); srows += e['rows']
    for h in hs:
        for s in ('s65', 's70'):
            for t in BASE_THRS: add(f'T3x_CG_base_h{h}_{s}_{t}', 'T3x 합의의 다른 격자', _cons_desc('', s, t, f'{h}일 보유'), 1, h, e['sig'][(h, s, t)], '합의(여러 조건 함께 켜짐)', 'A6')
        for s in BASE_SELS:
            for t in ('f10', 'f30'): add(f'T3x_CG_base_h{h}_{s}_{t}', 'T3x 합의의 다른 격자', _cons_desc('', s, t, f'{h}일 보유'), 1, h, e['sig'][(h, s, t)], '합의(여러 조건 함께 켜짐)', 'A6')
        for s, t in (('ps60', 'f20'), ('ps60', 'p95'), ('pw50', 'f20'), ('pw50', 'p95'), ('ps60', 'any')):
            add(f'T3x_PAIR_h{h}_{s}_{t}', 'T3x 조건 쌍의 합의', _cons_desc('[조건 쌍] ', s, t, f'{h}일 보유'), 1, h, e['sig'][(h, s, t)], '합의(여러 조건 함께 켜짐)', 'A11')
    n_pairs = e['n_pairs']
    # A6 (가): 조건 묶음을 바꾼 4가지
    cgv = {k: v for k, v in CG_VARS.items() if (not quick or k in ('pos10', 'win120'))}
    for vn, v in cgv.items():
        Bv, _ = conditions_x(D, quick, v['win'], v['minp'], v['hi'], v['lo'])
        ev_ = cons_engine(D, Bv, hs, tgt, years, BASE_SELS, BASE_THRS, label=vn); srows += ev_['rows']
        for (h, s, t), pos in sorted(ev_['sig'].items()):
            add(f'T3x_CG_{vn}_h{h}_{s}_{t}', 'T3x 합의의 다른 격자', _cons_desc(f"[{v['ko']}] ", s, t, f'{h}일 보유'), 1, h, pos, '합의(여러 조건 함께 켜짐)', 'A6')
    # A2 내림 방향 합의
    ed = cons_engine(D, B, hs, tgt_dn, years, BASE_SELS, BASE_THRS, any_sel='s60', label='down'); srows += ed['rows']
    for (h, s, t), pos in sorted(ed['sig'].items()):
        add(f'T3x_DN_C_h{h}_{s}_{t}', 'T3x 내림 합의', _cons_desc('[내림 적중으로 고름] ', s, t, f'{h}일 보유, 내림'), -1, h, pos, '내림 확률·합의', 'A2')
    # A8 보유 1·20일 합의
    eh = cons_engine(D, B, hx, tgt, years, BASE_SELS, BASE_THRS, any_sel='s60', label='h1_20'); srows += eh['rows']
    for (h, s, t), pos in sorted(eh['sig'].items()):
        add(f'T3x_H_C_h{h}_{s}_{t}', 'T3x 보유일 1·20일 합의', _cons_desc('', s, t, f'{h}일 보유'), 1, h, pos, '합의(여러 조건 함께 켜짐)', 'A8')
    # A10 새 사건 지표 20개를 더한 합의
    EX = events_extra(D); B2 = np.concatenate([B, EX.values > 0], axis=1)
    ee = cons_engine(D, B2, hs, tgt, years, BASE_SELS, BASE_THRS, label='events20'); srows += ee['rows']
    for (h, s, t), pos in sorted(ee['sig'].items()):
        add(f'T3x_EV_C_h{h}_{s}_{t}', 'T3x F2·F3·위클리 사건 합의', _cons_desc('[조건에 F2·F3·위클리 사건 지표 20개 더함] ', s, t, f'{h}일 보유'), 1, h, pos, '합의(여러 조건 함께 켜짐)', 'A10')
    cnt = lambda it: sum(c['params'].get('item') == it for c in o['cands'])
    nb = nc - 25                                                                       # 자리 조건 수(지표 × 2)
    _fam(o, 'T3x A2 내림 합의(조건×보유일 + 절차)', nc * len(hs) + cnt('A2')); _fam(o, 'T3x A6 합의의 다른 격자(새 조건×보유일 + 절차)', nb * len(hs) * len(cgv) + cnt('A6'))
    _fam(o, 'T3x A8 보유일 1·20일(모형 + 조건×보유일 + 합의)', n_a8p + nc * len(hx) + (cnt('A8') - n_a8p))
    _fam(o, 'T3x A10 F2·F3·위클리 사건(합의: 새 조건×보유일 + 절차)', 20 * len(hs) + cnt('A10')); _fam(o, 'T3x A11 조건 쌍의 합의(쌍 + 절차)', n_pairs + cnt('A11'))
    # B3 (가)(나): T2 방아쇠 8개(원래 정의) × 변동폭 큰·작은 날, 변동폭 자리만
    VR = vol_regime(D); TR = T2.triggers(D, False); ywf = np.isin(D.year, C.WF_YEARS); n0 = len(o['cands'])
    for g in ('hi', 'lo'):
        for h in HS:
            add(f'T4x_VC_only_{g}_h{h}', 'T4x 변동폭 자리 조건', f'{REG[g]}(다른 조건 없음) → {h}일 보유', 1, h, np.where(ywf & VR[g])[0], '변동폭 자리 조건', 'B3')
            for j in range(1, 9):
                add(f'T4x_VC_T{j}_{g}_h{h}', 'T4x 변동폭 자리 조건', f'방아쇠만: {T2.TRIG[j]} + {REG[g]} → {h}일 보유', 1, h, np.where(ywf & VR[g] & TR[j])[0],
                    ('변동성 꺾임 방아쇠' if j == 8 else '변동폭 자리 조건'), 'B3')
    _fam(o, 'T4x B3 변동폭 자리 조건', len(o['cands']) - n0)
    _tab(o, 'b_t3x_cons_select.csv', srows)
    o['md'] += [f'- 조건 쌍(A11): 해·보유일마다 윌슨 하한 상위 50개 조건의 쌍을 다시 채점 — 모두 {n_pairs:,}쌍.']
    return o


# ------------------------------------------------------------------ 조각 5·6: T3 변동폭판의 σ 창·배수(B2)
def part_t3v(D, variants, quick):
    o = _new_out('t3v'); yr = D.year; ev = yr >= 2016; hs = (5,) if quick else HS; years = [2025, 2026] if quick else C.WF_YEARS; mrows = []; srows = []
    for w, k in variants:
        kn = int(round(k * 100)); tagk = f'w{w}_k{kn:03d}'
        T3v = _load('t3', alias=f'w6b_t3_{tagk}'); T3v.VOL_K = k
        T3v.sigma60 = (lambda D_, w_=w: pd.Series(D_.c).pct_change().rolling(w_).std().values)   # σ = 직전 w 일 일간 등락 표준편차
        tg = {h: T3v.target(D, h, True) for h in hs}; EVv = T3v.events(D, True); cols = T3v.base_cols(D, quick)
        pre = f'[변동폭 맞춤·σ 창 {w}일·폭 {k}σ√h] '; fam = f'T4x T3 변동폭판(창 {w}일·폭 {k}σ)'; n0 = len(o['cands'])
        how = lambda h: f'{h}거래일 안에 +{k}σ√{h} 를 −{k}σ√{h} 보다 먼저 닿으면 맞음(닿은 날 청산)'
        for h in hs:
            y, ex = tg[h]
            for s in (('allev',) if quick else ('all', 'allev')):
                M = D.X[cols] if s == 'all' else pd.concat([D.X[cols], EVv], axis=1); P = model_probs(D, M.values, y, ex, quick)
                for m in MODELS:
                    p = P[m]; mrows.append(dict(variant=tagk, h=h, set=s, model=m, auc=_auc(y, p, ev)))
                    for q in QS:
                        qn = int(round(q * 100)); thr = thr_q(p, yr, q)
                        o['cands'].append(_cand(D, f'T4x_T3V_{tagk}_P_h{h}_{s}_{m}_q{qn}', fam,
                                                f'{pre}확률 모형({MODEL_NAME[m]}, {SETN[s]}, 해마다 다시 학습) 오를 확률이 그 전 예측의 상위 {100 - qn}% 선 이상 → {how(h)}', 1, h,
                                                np.where(ev & np.isfinite(p) & np.isfinite(thr) & (p >= thr))[0], '확률 모형(오를 확률 상위)', y=y, ex=ex, params=dict(h=h, set=s, model=m, q=q, w=w, k=k, item='B2')))
        B, _ = T3v.conditions(D, True, quick)
        e = cons_engine(D, B, hs, lambda h: tg[h], years, BASE_SELS, BASE_THRS, any_sel='s60', label=tagk); srows += e['rows']
        for (h, s, t), pos in sorted(e['sig'].items()):
            y, ex = tg[h]
            o['cands'].append(_cand(D, f'T4x_T3V_{tagk}_C_h{h}_{s}_{t}', fam, _cons_desc(pre, s, t, how(h)), 1, h, pos, '합의(여러 조건 함께 켜짐)', y=y, ex=ex, params=dict(h=h, w=w, k=k, item='B2')))
        _fam(o, f'T4x B2 T3 변동폭판 창 {w}일·폭 {k}σ(절차 + 조건×보유일)', (len(o['cands']) - n0) + B.shape[1] * len(hs))
    _tab(o, 'b_t4x_t3v_models.csv', mrows); _tab(o, 'b_t4x_t3v_cons_select.csv', srows)
    return o


# ------------------------------------------------------------------ 조각 7: T2 변동폭판의 창·배수(B1) + T5 변동폭판(B4) + 청산(T6x)
def _t2_year(Y, c, th, R, mj, lo_, cut, nn, cols):
    return _load('t2')._one_year(Y, c, th, R, mj, lo_, cut, nn, cols)


def t2v_block(D, o, variants, quick):
    from joblib import Parallel, delayed
    T2 = _load('t2'); R = T2.ranks(D.X); cols = list(D.X.columns); mj = cols.index(T2.MATCH); lo_ = int(D.td.searchsorted(C.START)) + 10
    years = [y for y in C.WF_YEARS if (not quick or y in T2.QUICK_YEARS)]; nn = 40 if quick else T2.NN; rows = []
    for w, k in variants:
        tagk = f'w{w}_k{int(round(k * 10)):02d}'
        T2v = _load('t2', alias=f'w6b_t2_{tagk}', SIGN=w, VOLK=k, TRIG_V4=f'장대 양봉(하루 등락이 직전 {w}일 표준편차의 {k}배 이상)')
        th = T2v.move_th(D, True)
        res = Parallel(n_jobs=NJ)(delayed(_t2_year)(Y, D.c, th, R, mj, lo_, int(np.where(D.year == Y)[0][0]), nn, cols) for Y in years)
        cands, meta = T2v.merge([dict(vol=True, quick=bool(quick), years={int(Y): m for Y, m in res})], vol=True, quick=quick)
        if not cands: raise RuntimeError(f'T2 변동폭판 {tagk}: 후보가 0개')
        for c in cands:
            c = dict(c); pr = c.get('params') or {}; j = int(pr.get('trigger', 0)); arm = str(pr.get('arm'))
            c['id'] = f"T4x_T2V_{tagk}_{str(c['id'])[2:] if str(c['id']).startswith('V_') else c['id']}"
            c['desc'] = str(c['desc']).replace('[변동폭 맞춤] ', f'[변동폭 맞춤·σ 창 {w}일·배수 {k}] ').replace('+1.0σ√20', f'+{k}σ√20')
            c['family'] = f"T4x T2 변동폭판(창 {w}일·배수 {k}):{c.get('family')}"
            c['root'] = '변동성 꺾임 방아쇠' if j == 8 else ('방아쇠만' if arm == 'TO' else ('바닥 전 상태만' if j == 0 else '바닥 전 상태 + 방아쇠'))
            c['params'] = dict(pr, w=w, k=k, item='B1'); o['cands'].append(c)
        _fam(o, f'T4x B1 T2 변동폭판 창 {w}일·배수 {k}', len(cands))
        t = pd.read_csv(io.StringIO(meta['tables_csv']['V_trigger_compare.csv'])); t.insert(0, 'variant', tagk); rows.append(t)
    _tab(o, 'b_t4x_t2v_trigger_compare.csv', pd.concat(rows, ignore_index=True))


def t5v_block(D, o, quick):
    T2 = _load('t2'); T5v = _load('t5', alias='w6b_t5v')
    ns = types.SimpleNamespace(**{k: getattr(C, k) for k in dir(C) if not k.startswith('__')})
    ns.first_touch = lambda D_, k=0.05, max_days=60, delay=0: T2.first_touch_var(D_, 1.0 * T2.SQ20 * T2.sigma_prev(D_.c), max_days)   # ±5% → ±1.0σ√20(σ = 직전 60일)
    ns.Data = lambda: D
    T5v.C = ns; T5v.SC_KO = dict(T5v.SC_KO)
    T5v.SC_KO['t5'] = '보유일 없이 시가 기준 −1.0σ√20 에 먼저 닿으면 맞음(+1.0σ√20 먼저면 틀림, σ = 직전 60일 일간 표준편차)'
    P = T5v.run_part(1, 1, quick=quick); n0 = len(o['cands'])
    for c in P['cands']:
        if (c.get('params') or {}).get('score') != 't5' or c.get('kind') != 'wf': continue
        c = dict(c); c['id'] = f"T4x_T5V_{c['id']}"; c['desc'] = '[변동폭 맞춤] ' + str(c['desc']); c['family'] = f"T4x T5 변동폭판:{c.get('family')}"; c['root'] = '하락(내림) 신호'
        c['params'] = dict(c.get('params') or {}, item='B4')
        if 'base_y' not in c: raise RuntimeError('T5 변동폭판 후보에 base_y 가 없음')
        o['cands'].append(c)
    n_cond = len(P['ids']); _fam(o, 'T4x B4 T5 변동폭판(조건 + 합의 + 해마다 고름)', n_cond + (len(o['cands']) - n0))
    cf = P['cond_full']; cf = cf[cf['score'] == 't5']; wb = P['wf_base']; wb = wb[wb['score'] == 't5']
    _tab(o, 'b_t4x_t5v_cond.csv', cf); _tab(o, 'b_t4x_t5v_wf.csv', wb); o['m_fixed'] = n_cond
    pc = lambda n, k: '–' if n < 10 else f'{100 * k / n:.0f}%'
    top = cf[cf['n'] >= 10].assign(edge=lambda d: d['hit'] - d['base']).sort_values('edge', ascending=False).head(5)
    o['md'] += ['', '#### T5 변동폭판(B4) — 조건·합의 신호, −1.0σ√20 먼저 닿기(전체 기간·결과를 보고 고르는 숫자, 아무 날과의 차이 큰 순 5개 — 다음 해 성적은 판정표의 T4x_T5V 줄)', '',
                '| 조건·합의 | 독립 거래 | 내림 적중 | 같은 해 아무 날 |', '|---|---|---|---|']
    o['md'] += [f"| {r['desc']} | {int(r['n'])} | {pc(int(r['n']), int(r['k']))} | {C.pct(r['base'], 0)} |" for _, r in top.iterrows()] or ['| (독립 10건 이상인 조건 없음) | | | |']


def _trail(P, tr, H):
    """C1 추적 손절: 가장 좋았던 값(전날까지의 고가와 오늘 시가) − tr 에 닿으면 청산. 시가가 이미 선 아래면 시가에."""
    m = P['ro'].shape[0]; peak = np.zeros(m); done = np.zeros(m, bool); off = np.full(m, H - 1); x = P['rc'][:, H - 1].copy()
    for k in range(H):
        ok = P['ok'][:, k] & ~done; ro = P['ro'][:, k]
        gap = ok & (ro <= peak - tr); pk2 = np.maximum(peak, ro); hit = ok & ~gap & (P['rlo'][:, k] <= pk2 - tr)
        x = np.where(gap, ro, np.where(hit, pk2 - tr, x)); off = np.where(gap | hit, k, off); done = done | gap | hit
        peak = np.where(done, peak, np.maximum(pk2, P['rhi'][:, k]))
    return off, x, done | P['ok'][:, H - 1]


def _tp_half(P, tp, H):
    """C2 (나): 절반은 익절 tp(안 닿으면 H 일째 종가), 나머지 절반은 H 일째 종가."""
    ri = np.arange(P['ro'].shape[0]); take = (P['rhi'][:, :H] >= tp) & P['ok'][:, :H]; has = take.any(1); kf = take.argmax(1); o_k = P['ro'][ri, kf]
    x1 = np.where(has, np.where(o_k >= tp, o_k, tp), P['rc'][:, H - 1])
    return np.full(len(ri), H - 1), 0.5 * x1 + 0.5 * P['rc'][:, H - 1], P['ok'][:, H - 1]


def _sltp_var(P, sl, tp, H):
    """C3: 거래마다 다른 손절선 sl(음수 배열)·익절선 tp(양수 배열). t6 의 손절·익절과 같은 순서 규칙(시가가 이미 넘었으면 시가, 같은 날 둘 다면 손절)."""
    m = P['ro'].shape[0]; ri = np.arange(m); ok = P['ok'][:, :H]; no = np.zeros_like(ok)
    stop = (P['rlo'][:, :H] <= sl[:, None]) if sl is not None else no; take = (P['rhi'][:, :H] >= tp[:, None]) if tp is not None else no
    ev = (stop | take) & ok; has = ev.any(1); kf = ev.argmax(1); o_k = P['ro'][ri, kf]
    gs = (o_k <= sl) if sl is not None else np.zeros(m, bool); gt = (o_k >= tp) if tp is not None else np.zeros(m, bool); st = stop[ri, kf]
    lvl = np.where(st, sl if sl is not None else np.nan, tp if tp is not None else np.nan)
    return np.where(has, kf, H - 1), np.where(has, np.where(gs | gt, o_k, lvl), P['rc'][:, H - 1]), has | P['ok'][:, H - 1]


def _opp(P, on, H):
    """C4: 매수일부터 반대 방향 신호가 켜진 첫날(장 마감 뒤 확인)의 다음 거래일 시가에 청산. 없으면 H 일째 종가."""
    ri = np.arange(P['ro'].shape[0]); o_ = on[P['ix'][:, :H - 1]] & P['ok'][:, :H - 1]; has = o_.any(1); kf = o_.argmax(1) + 1
    return np.where(has, kf, H - 1), np.where(has, P['ro'][ri, kf], P['rc'][:, H - 1]), np.where(has, P['ok'][ri, kf], P['ok'][:, H - 1])


def t6x_block(D, o, quick):
    T6 = _load('t6'); T5 = _load('t5')
    targets, notes, n_all = T6.load_targets(quick)
    if not targets: raise RuntimeError('T6x: 청산 비교 대상(t1~t5 의 다음 해 기준 통과 절차)을 읽지 못함 — tN/out/judge.json·cands.pkl 확인')
    Mc = T5.build_conds(D, [c[0] for c in T5.CONDS]); G = T5.build_cons(Mc); opp_dn = [(g, lab, np.asarray(G[g], dtype=bool)) for g, lab in T5.CONS]
    up_any = np.zeros(D.n, bool)
    for T in targets:
        if int(T['direction']) > 0: up_any[T6.entries(D, T['signals']) - 1] = True
    u_all = pd.Series(D.c).pct_change().rolling(60).std().values * math.sqrt(5)           # C3 폭 단위(신호일까지 아는 값)
    pcs = lambda v: f'{100 * v:.0f}%'; ex_rows, sm_rows, pk_rows, agg = [], [], [], []; n_rules_tot = 0; ORIG = T6.N_RULES - 1
    for T in targets:
        ev = T6.eval_target(D, T['signals'], T['direction'], T['hold']); E, sp, d = ev['E'], ev['sp'], ev['d']
        if not len(sp): notes.append(f"{T['track'].upper()} {T['id']}: 쓸 수 있는 신호 날짜가 없어 건너뜀"); continue
        key = f"{T['track']}_{T6._safe(T['id'])}"; P = T6.paths(D, E, d, 20); u = u_all[sp]; new = []
        for tr in TRAILS:
            for H in MAXHOLDS: new.append(('추적 손절', f'TR{int(round(tr * 100))}M{H}', f'고점 대비 {pcs(tr)} 되돌림 청산·최대 {H}일') + _trail(P, tr, H))
        for h1, h2 in SPLIT_H:
            new.append(('분할 청산', f'SP{h1}_{h2}', f'절반 {h1}일째·절반 {h2}일째 종가', np.full(len(E), h2 - 1), 0.5 * (P['rc'][:, h1 - 1] + P['rc'][:, h2 - 1]), P['ok'][:, h2 - 1]))
        for tp in SPLIT_TP:
            for H in MAXHOLDS: new.append(('분할 청산', f'SPT{int(round(tp * 100))}M{H}', f'절반 +{pcs(tp)} 익절·절반 {H}일째 종가') + _tp_half(P, tp, H))
        for a_ in VOL_MULT:
            for b_ in VOL_MULT:
                if a_ is None and b_ is None: continue
                for H in MAXHOLDS:
                    off, x, v = _sltp_var(P, (None if a_ is None else -a_ * u), (None if b_ is None else b_ * u), H)
                    new.append(('변동폭 손절·익절', f"VS{0 if a_ is None else int(a_)}T{0 if b_ is None else int(b_)}M{H}",
                                f"손절 {'없음' if a_ is None else f'−{a_:g}u'}·익절 {'없음' if b_ is None else f'+{b_:g}u'}(u = 60일 σ×√5)·최대 {H}일", off, x, v & np.isfinite(u)))
        for g, lab, on in (opp_dn if d > 0 else [('upany', '오름 대상 가운데 하나라도 켜짐', up_any)]):
            for H in OPP_H: new.append(('반대 신호 청산', f'OP_{g}_M{H}', f'내림 신호[{lab}]가 켜진 다음 날 시가·최대 {H}일' if d > 0 else f'[{lab}] 다음 날 시가·최대 {H}일') + _opp(P, on, H))
        EXn = np.stack([E + r[3] for r in new]); RDn = np.stack([np.where(r[5], r[4], np.nan) for r in new]); VAn = np.stack([r[5] for r in new]) & np.isfinite(RDn)
        EX = np.vstack([ev['ex'], EXn]); RD = np.vstack([ev['rd'], RDn]); VA = np.vstack([ev['valid'], VAn])
        KEEP = list(ev['keep']) + [T6.thin(sp, EXn[j], VAn[j]) for j in range(len(new))]
        labels = [r['label'] for r in ev['rules']] + [r[2] for r in new]; fams = [r['fam'] for r in ev['rules']] + [r[0] for r in new]; rids = [r['rid'] for r in ev['rules']] + [r[1] for r in new]
        nR = len(labels); n_rules_tot += len(new) + N_CRIT
        st = [T6.stats(RD[j][KEEP[j]], EX[j][KEEP[j]] - E[KEEP[j]] + 1) for j in range(nR)]
        base = dict(target=key, track=T['track'], id=T['id'], desc=T['desc'], direction=d, hold=ev['hold'], n_signals=int(len(sp)))
        for j in range(T6.N_RULES, nR): ex_rows.append({**base, 'family': fams[j], 'rule': rids[j], 'rule_label': labels[j], **st[j]})
        b55 = max(range(T6.N_RULES), key=lambda j: (st[j]['sum_c15'], -j)); bnew = max(range(T6.N_RULES, nR), key=lambda j: (st[j]['sum_c15'], -j))
        sm_rows.append({**base, 'row': '원래 보유일(전체 기간)', 'rule': labels[ORIG], **st[ORIG]})
        sm_rows.append({**base, 'row': 'T6 의 55개 중 1위(전체 기간·결과를 보고 고름)', 'rule': labels[b55], **st[b55]})
        sm_rows.append({**base, 'row': '새 규칙 59개 중 1위(전체 기간·결과를 보고 고름)', 'rule': labels[bnew], **st[bnew]})
        a = dict(target=key, orig=st[ORIG]['sum_c15'], orig_worst=st[ORIG]['worst'], best55=st[b55]['sum_c15'], bestnew=st[bnew]['sum_c15'], bestnew_fam=fams[bnew])
        for f in ('추적 손절', '분할 청산', '변동폭 손절·익절', '반대 신호 청산'):
            jj = [j for j in range(T6.N_RULES, nR) if fams[j] == f]; jb = max(jj, key=lambda j: (st[j]['sum_c15'], -j)); a[f'fam_{f}'] = st[jb]['sum_c15']; a[f'famw_{f}'] = st[jb]['worst']
        # C5: 해마다 그 전 독립 거래로 고르기(기준 3가지) + 원래 보유일 2016~
        ys = D.year[sp]

        def choose(year, crit):
            cut = int(D.td.searchsorted(pd.Timestamp(f'{year}-01-01'))); best, bkey, bn = ORIG, None, 0
            for j in range(nR):
                kp = KEEP[j]; x = RD[j][kp[EX[j][kp] < cut]] - COST
                if j == ORIG: bn0 = len(x)
                if len(x) < (20 if crit == 'worst' else 10): continue
                if crit == 'sum': k_ = (float(x.sum()),)
                elif crit == 'mean': k_ = (float(x.mean()),)
                else:
                    if not x.mean() > 0: continue
                    k_ = (float(x.min()), float(x.sum()))
                if bkey is None or k_ > bkey: best, bkey, bn = j, k_, len(x)
            return best, bn
        names = {'sum': '해마다 고름 ① 그 전 비용 뒤 수익 합계 1위(114개 중)', 'mean': '해마다 고름 ② 그 전 비용 뒤 거래 평균 1위', 'worst': '해마다 고름 ③ 그 전 최대 손실이 가장 작은 규칙(20건 이상·평균 > 0)', 'orig': '해마다 ④ 원래 보유일 그대로(2016~)'}
        for crit in ('sum', 'mean', 'worst', 'orig'):
            S_, X_, R_, used = [], [], [], []
            for yv in C.WF_YEARS:
                j, npr = (ORIG, 0) if crit == 'orig' else choose(yv, crit); m = (ys == yv) & VA[j]
                S_.append(sp[m]); X_.append(EX[j][m]); R_.append(RD[j][m])
                if m.any(): used.append(labels[j])
                if crit != 'orig': pk_rows.append(dict(target=key, crit=crit, year=yv, rule=rids[j], rule_label=labels[j], n_prior=int(npr), n_signals=int(m.sum())))
            s_ = np.concatenate(S_); x_ = np.concatenate(X_); r_ = np.concatenate(R_); od_ = np.argsort(s_, kind='stable'); s_, x_, r_ = s_[od_], x_[od_], r_[od_]
            kp = T6.thin(s_, x_, np.ones(len(s_), bool)); s2 = T6.stats(r_[kp], x_[kp] - s_[kp])
            uu = sorted(set(used)); sm_rows.append({**base, 'row': names[crit], 'rule': (uu[0] if len(uu) == 1 else f'{len(uu)}가지를 바꿔 씀'), **s2})
            a[f'wf_{crit}'] = s2['sum_c15']; a[f'wfw_{crit}'] = s2['worst']
        agg.append(a)
    if not agg: raise RuntimeError('T6x: 계산된 대상이 0개')
    N = len(agg); A = pd.DataFrame(agg)
    _tab(o, 'b_exits.csv', ex_rows); _tab(o, 'b_exits_summary.csv', sm_rows); _tab(o, 'b_exits_wf_rules.csv', pk_rows)
    _fam(o, 'T6x C1~C5 청산의 안 넣은 것(새 규칙 + 고르는 기준, 등급 없음)', n_rules_tot)
    f1 = lambda v: '–' if v is None or not np.isfinite(v) else f'{100 * v:+.1f}%'
    md = ['', f'#### 청산의 안 넣은 것(T6x) — 대상 {N}개(T6 과 같은 대상), 새 청산 규칙 {N_NEW}가지 + 고르는 기준 {N_CRIT}가지', '',
          '- 등급을 매기지 않는 비교다(손절·익절은 CRITERIA 2절의 매매가 아님). **비용 0.15% 뒤 수익 합계**와 최대 손실 거래로 읽는다. 지수는 그 가격에 사고팔 수 없어 수익은 어림이다.',
          "- '가족 1위'는 전체 기간 결과를 보고 고른 숫자다. 믿을 숫자는 '해마다 고름' 줄(그 전 거래만 보고 고른 규칙의 그 해 성적, 2016~2026)이고 견줄 바탕은 '원래 보유일 2016~'.", '',
          '| 가족(전체 기간·결과를 보고 고른 1위) | 원래 보유일보다 비용 뒤 합계가 많았던 대상 | 차이 가운뎃값 | 최대 손실 거래가 덜 나빴던 대상 |', '|---|---|---|---|']
    for f in ('추적 손절', '분할 청산', '변동폭 손절·익절', '반대 신호 청산'):
        dv = A[f'fam_{f}'] - A['orig']; md.append(f"| {f} | {int((dv > 1e-12).sum())} / {N} | {100 * dv.median():+.1f}%p | {int((A[f'famw_{f}'] > A['orig_worst'] + 1e-12).sum())} / {N} |")
    md += ['', '| 해마다 고르는 기준(2016~2026) | 원래 보유일(2016~)보다 비용 뒤 합계가 많았던 대상 | 차이 가운뎃값 | 최대 손실 거래가 덜 나빴던 대상 |', '|---|---|---|---|']
    for crit, nm in (('sum', '① 수익 합계 1위(규칙 114개로 넓힘)'), ('mean', '② 거래 평균 1위'), ('worst', '③ 최대 손실이 가장 작은 규칙')):
        dv = A[f'wf_{crit}'] - A['wf_orig']; md.append(f"| {nm} | {int((dv > 1e-12).sum())} / {N} | {100 * dv.median():+.1f}%p | {int((A[f'wfw_{crit}'] > A['wfw_orig'] + 1e-12).sum())} / {N} |")
    md += ['', '| 대상 | 원래 보유일 | T6 55개 중 1위 | 새 59개 중 1위(가족) | 해마다 ① | 해마다 ② | 해마다 ③ | 원래 2016~ |', '|---|---|---|---|---|---|---|---|']
    for _, r in A.iterrows():
        md.append(f"| {r['target']} | {f1(r['orig'])} | {f1(r['best55'])} | {f1(r['bestnew'])} ({r['bestnew_fam']}) | {f1(r['wf_sum'])} | {f1(r['wf_mean'])} | {f1(r['wf_worst'])} | {f1(r['wf_orig'])} |")
    md += ['', '(칸 = 비용 0.15% 뒤 수익 합계, 독립 거래 단순 합. 전체 표는 tables/b_exits.csv · b_exits_summary.csv · b_exits_wf_rules.csv)']
    o['md'] += md; o['notes'] += notes; o['t6x_targets'] = N


def part_misc(D, quick):
    o = _new_out('misc')
    t2v_block(D, o, (T2V[:1] if quick else T2V), quick)
    t5v_block(D, o, quick)
    t6x_block(D, o, quick)
    return o


# ------------------------------------------------------------------ 줄기 약속 함수
def n_parts():
    return 7


def _fin(o):
    o['secs'] = round(time.time() - o.pop('t0'), 1); print(f"[w6b] {o['name']}: 후보 {len(o['cands'])}개 · {o['secs']}초", flush=True)
    return o


def run_part(k, n, quick=False):
    D = C.Data()
    if quick:
        if k != 1: return {'kind': 'skip'}
        return {'kind': 'quick', 'subs': [_fin(part_h(D, 5, True)), _fin(part_cons(D, True)), _fin(part_t3v(D, T3V[:1], True)), _fin(part_misc(D, True))]}
    if n != n_parts(): raise ValueError(f'조각 수가 다름: {n} != {n_parts()}')
    if k in (1, 2, 3): return _fin(part_h(D, HS[k - 1], False))
    if k == 4: return _fin(part_cons(D, False))
    if k == 5: return _fin(part_t3v(D, T3V[:2], False))
    if k == 6: return _fin(part_t3v(D, T3V[2:], False))
    if k == 7: return _fin(part_misc(D, False))
    raise ValueError(f'조각 번호 {k}')


def merge(parts, quick=False, out_dir=None):
    """조각을 잇고 센다. 조각이 하나라도 없으면 멈춘다(조용히 넘기지 않음). (cands, meta) 반환."""
    parts = list(parts or [])
    if quick:
        if not parts or parts[0] is None or parts[0].get('kind') != 'quick': raise RuntimeError('W6 뒤쪽: quick 조각 1 이 없음')
        subs = parts[0]['subs']
    else:
        if len(parts) != n_parts(): raise RuntimeError(f'W6 뒤쪽: 조각 수가 다름({len(parts)} != {n_parts()})')
        miss = [i + 1 for i, p in enumerate(parts) if p is None or 'cands' not in p]
        if miss: raise RuntimeError(f'W6 뒤쪽: 조각 {miss} 결과가 없음 — 합치지 않고 멈춤')
        subs = parts
    cands = []; fam = {}; tables = {}; md = []; notes = []; m_fixed = 0; n_t6 = 0
    for s in subs:
        cands += s['cands']; md += s.get('md', []); notes += s.get('notes', []); m_fixed += int(s.get('m_fixed', 0)); n_t6 += int(s.get('t6x_targets', 0))
        for k, v in s['fam'].items(): fam[k] = fam.get(k, 0) + int(v)
        for k, v in s['tables'].items(): tables[k] = pd.concat([tables[k], v], ignore_index=True) if k in tables else v
    ids = [c['id'] for c in cands]
    if len(set(ids)) != len(ids): raise RuntimeError('W6 뒤쪽: 후보 id 가 겹침')
    if any(c.get('kind') != 'wf' or not str(c['id']).startswith(('T3x_', 'T4x_')) for c in cands): raise RuntimeError('W6 뒤쪽: 후보 꼴이 약속과 다름')
    n3 = sum(i.startswith('T3x_') for i in ids); n4 = sum(i.startswith('T4x_') for i in ids); n_tested = int(sum(fam.values()))
    if not quick:
        if (n3, n4) != (M_T3X, M_T4X): raise RuntimeError(f'W6 뒤쪽: 절차 수가 SPEC 과 다름(T3x {n3} != {M_T3X} 또는 T4x {n4} != {M_T4X})')
        if not cands or not n_tested or not n_t6: raise RuntimeError('W6 뒤쪽: 후보·가짓수·청산 대상이 0')
    S = ['### W6 뒤쪽 — T3·T4·T6 의 안 넣은 것' + (' [quick 시험: 자료·가족 일부]' if quick else ''), '',
         f'- 시험한 가짓수 {n_tested:,}개, 해마다 고르는 절차(판정에 넘긴 후보) {len(cands):,}개 = T3x {n3} + T4x {n4}. 청산(T6x)은 등급 없는 비교라 후보로 넘기지 않았다(대상 {n_t6}개).',
         f'- 절차가 {len(cands):,}개다 — 가짓수 보정 전 가짜 시험 p 가 1% 미만인 절차가 우연만으로도 {max(1, round(len(cands) / 100))}개쯤 나온다. 판정표의 성적은 이것을 알고 읽을 것.',
         '- 미리 정한 목록은 w6/SPEC_b.md. 모형 구분력·합의 고르기·청산 표는 tables/b_*.csv.', '',
         '| 가족 | 시험 가짓수 |', '|---|---|'] + [f'| {k} | {v:,} |' for k, v in fam.items()] + ['']
    summary = '\n'.join(S + md) + '\n'
    if out_dir:
        os.makedirs(os.path.join(out_dir, 'tables'), exist_ok=True)
        for k, df in tables.items(): df.to_csv(os.path.join(out_dir, 'tables', k), index=False, encoding='utf-8')
    notes = ['W6 뒤쪽(T3·T4·T6 의 안 넣은 것): 1차 정의는 그대로 두고 안 넣었던 차원만 바꿈. 후보는 모두 해마다 고르는 절차(wf).',
             f'청산(T6x)은 등급 없는 비교(대상 {n_t6}개 × 새 규칙 {N_NEW}가지·고르는 기준 {N_CRIT}가지) — 요약 글과 tables/b_exits*.csv 로만 냄.',
             '계산으로 풀 수 없던 것: ' + ' / '.join(UNSOLVABLE)] + notes + (['시험 실행(--quick): 가족·자료 일부만 돌린 결과다.'] if quick else [])
    meta = dict(n_tested=n_tested, families=fam, m_fixed=max(1, m_fixed), m_wf=len(cands), not_included=list(NOT_INCLUDED), unsolvable=list(UNSOLVABLE), parts_failed=[],
                notes=notes, tables=sorted(tables), summary_md=summary, quick=bool(quick), secs={s['name']: s.get('secs') for s in subs})
    return cands, meta


def main():
    a = C.parse_part()
    if a['nparts']: print(n_parts()); return
    if a['part']:
        i, n = a['part']; t0 = time.time(); C.save_part(TRACK, i, n, run_part(i, n, quick=a['quick']))
        print(f'[w6b] 조각 {i}/{n} 끝 {time.time() - t0:.0f}초', flush=True); return
    if a['merge']:
        od = os.path.join(C.track_dir(TRACK), 'out'); cands, meta = merge(C.load_parts(TRACK, n_parts()), quick=a['quick'], out_dir=od)
        open(os.path.join(od, 'summary.md'), 'w', encoding='utf-8').write(meta['summary_md'])
        C.save_result(TRACK, cands, meta)
        print(f"[w6b] 합침: 후보 {len(cands)}개 · 시험 {meta['n_tested']:,}가지 · wf 절차 {meta['m_wf']}", flush=True); return
    print(__doc__)


if __name__ == '__main__':
    main()
