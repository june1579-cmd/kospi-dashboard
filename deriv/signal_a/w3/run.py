# -*- coding: utf-8 -*-
"""W3 — T1 SPEC '안 넣은 것' 전부. SPEC.md 그대로 구현(돌린 뒤 고치지 않는다).

조각 5개(조각마다 조건 만들기 → 독립 거래 솎기 → 해마다 고르기·채점 → 가짜 → 표·후보까지 다 한다)
  1 G1 벽 쪽 새 차원(나이 세분·K3·까닭·위클리·차기 분기물·풋벽·넘어선 벽) 272,640가지 · wf 28
  2 G2 수급 쪽 새 차원(외국인 콜·풋, 누적 창 5·10일, 기관·개인) 127,680가지 · wf 28
  3 G3 보유일 2·7·20(T1 조건 묶음 그대로) 96,480가지 · wf 28
  4 (나) 고르는 절차의 다른 꼴(T1 원래 가족 128,640개에 새 절차 100개)
  5 (다) 익절·손절 ±3%·±5% 닿기(표만, 64,320가지 + 절차 12개)
merge = 조각을 모아 확인하고 표·요약을 쓴다(조각이 하나라도 없으면 멈춘다).
계산 틀은 t1/run.py 의 것을 복사해 넓혔다(결과 줄 = 보유일 1~20일 + 닿기 줄, 꼴·합의 비율을 절차마다).
"""
import importlib.util
import math
import os
import sys

import numpy as np
import pandas as pd
from joblib import Parallel, delayed

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import sa_common as C  # noqa: E402

TRACK = 'w3'
NJ = max(1, min(4, os.cpu_count() or 1))
N_PARTS = 5
DIST = [0.5, 1.0, 1.5, 2.0, 3.0]
TAGS = ['F0', 'F1', 'F2', 'F3', 'Q', 'ALL']
K_TAGS = ['F0', 'F1', 'F2', 'ALL']
FLOW = ['none', 'fut', 'spot', 'both']
REG = ['any', 'above', 'below']
DELAY = [0, 1]
FIRST = [0, 1]
HOLDS = [1, 3, 5, 10]
HOLDS_G3 = [2, 7, 20]
FIRST_N = 5
MAXH = 20                                   # 결과 줄 0~19 = 보유일 1~20
TOUCH = [0.03, 0.05]                        # (다) 결과 줄 20, 21 = ±3%, ±5% 닿기
TOUCH_DAYS = 60
N_FAKE = 200
TOP_FIXED = 33                              # 묶음·방향마다 fixed 후보 수
Y0 = C.START.year
NYB = C.END.year - Y0 + 1
SHAPES = {'goal': ('hit', 0.85), 'watch': ('hit', 0.80), 'h75': ('hit', 0.75), 'h90': ('hit', 0.90), 'lb60': ('lb', 0.60), 'lb70': ('lb', 0.70)}
HOWS = {'any': None, 'cons': 0.20, 'cons10': 0.10, 'cons30': 0.30}
COUNTS = [1, 5, 20, 0]                      # 0 = 전부


def _procs(shapes, hows=('any', 'cons'), counts=COUNTS):
    return [(dn, sh, cn, how) for dn in ('up', 'dn') for sh in shapes for cn in counts for how in hows if not (cn == 1 and how != 'any')]


PROCS_T1 = _procs(('goal', 'watch'))                                           # 28 (T1 과 같은 꼴)
PROCS_ALT = _procs(('h75', 'h90', 'lb60', 'lb70'))                             # 56
PROCS_RATIO = _procs(('goal', 'watch'), hows=('cons10', 'cons30'), counts=[20, 0])   # 16
PROCS_TP = _procs(('watch',), hows=('any',), counts=[1, 5, 20])                # 6 (폭마다)
EXPECT = {'A': 120960, 'B': 7680, 'C': 34560, 'C2': 5760, 'D': 34560, 'E': 23040, 'F': 34560, 'G': 11520, 'H': 127680, 'I': 96480, 'K': 64320}
FAM_KO = {'A': 'A 벽 나이 세분', 'B': 'B 셋 이상 동시 새 벽', 'C': 'C 새 벽이 생긴 까닭', 'C2': 'C2 동시 새 벽(까닭별)', 'D': 'D 위클리 콜벽', 'E': 'E 차기 분기물 콜벽',
          'F': 'F 풋벽', 'G': 'G 이미 넘어선 콜벽', 'H': 'H 다른 수급', 'I': 'I 보유일 2·7·20', 'J': 'J 고르는 절차 다른 꼴(절차 수)', 'K': 'K 익절·손절 닿기(표만)'}
BUNDLE_KO = {'G1': '벽 쪽 새 차원', 'G2': '수급 쪽 새 차원', 'G3': '보유일 2·7·20'}
NOT_INCLUDED = [
    '새 벽 쪽 가족(나이 세분·까닭·위클리·차기 분기물·풋벽·넘어선 벽)에 다른 수급 14가지·보유일 2·7·20 을 곱한 것(차원을 하나씩만 넓혔음)',
    '까닭(물량 이동·넘어섬·만기 교체) × 벽 물량 변화, 넷 모두 동시 새 벽(K4), 벽 나이 2·10·20일 이상',
    '위클리 풋벽·위클리 넘어선 벽, 위클리와 월물이 함께 새 벽, 차기 분기물의 풋벽',
    '수급 문턱을 부호가 아니라 크기(상위 25% 등)로, 외국인 콜·풋 흐름의 5·10일 창, 금융투자·연기금 따로, 수급 조건 두 개 겹치기',
    '고르는 꼴의 더 많은 문턱(적중 70%·95%, 윌슨 하한 50%·80%), 합의 비율 5%·50%, W3 새 가족에 다른 고르는 꼴 적용',
    '익절과 손절 폭이 다른 청산, 변동폭에 맞춘 폭, 추적 손절, 보유일 15·30·60일, 익절·손절을 등급 후보로 판정하기(기준은 사용자가 정함)',
    'W3 가족 전부의 변동폭 맞춤판(거리를 σ 로)',
]


def _t1():
    """t1/run.py 를 읽기만 해서 불러 쓴다(조건 묶음·마스크·규칙 이름). 고치지 않는다."""
    if 'sa_t1_run' not in sys.modules:
        p = os.path.join(C.SA, 't1', 'run.py')
        if not os.path.exists(p): raise FileNotFoundError(f't1/run.py 없음: {p}')
        spec = importlib.util.spec_from_file_location('sa_t1_run', p); m = importlib.util.module_from_spec(spec)
        sys.modules['sa_t1_run'] = m; spec.loader.exec_module(m)
    return sys.modules['sa_t1_run']


def _par(fn, argsets):
    argsets = list(argsets)
    if NJ > 1 and len(argsets) > 1:
        try: return Parallel(n_jobs=NJ)(delayed(fn)(*a) for a in argsets)
        except Exception as e: print('joblib 실패 → 차례로 계산:', repr(e)[:200], flush=True)
    return [fn(*a) for a in argsets]


# ------------------------------------------------------------------ 고정 원자료 읽기(없으면 멈춘다)
def _raw(name):
    p = os.path.join(C.raw_dir('deriv'), 'deriv', 'data', name)
    if not os.path.exists(p): raise FileNotFoundError(f'고정 원자료에 {name} 없음(확인 불가) — 멈춤')
    return p


def _num(s):
    return pd.to_numeric(s.astype(str).str.replace(',', '', regex=False).str.replace('−', '-', regex=False).replace({'-': None, '': None, 'nan': None}), errors='coerce')


def k200_close(D):
    k = pd.read_csv(_raw('k200_long.csv')); k.columns = [c.lstrip('﻿') for c in k.columns]
    if '날짜' not in k or '종가' not in k: raise KeyError('k200_long.csv 에 날짜·종가 열 없음')
    s = pd.Series(k['종가'].astype(float).values, index=pd.to_datetime(k['날짜'])).sort_index()
    s = s[~s.index.duplicated(keep='last')]; s = s[s.index <= C.END].reindex(D.td)
    if s[D.td >= C.START].notna().mean() < 0.99: raise RuntimeError('코스피200 종가가 거래일의 99% 미만 — 멈춤')
    return s


def opt_flows(D):
    """외국인 콜·풋 순매수(원자료 inv_daily: 상품 OPK2I · 권리 C/P · 단위 AMT · 장구분 정규 · 상세 Y · 열 A11) — lab_common.flows 의 call_for·put_for 와 같은 값(단위만 원)."""
    inv = pd.read_csv(_raw('inv_daily.csv.gz'), low_memory=False)
    for c in ('상품', '권리', '단위', '장구분', '상세', 'TRD_DD', 'A11'):
        if c not in inv: raise KeyError(f'inv_daily 에 {c} 열 없음')
    out = {}
    for cp in ('C', 'P'):
        q = inv[(inv['상품'] == 'OPK2I') & (inv['권리'] == cp) & (inv['단위'] == 'AMT') & (inv['장구분'] == '정규') & (inv['상세'].fillna('') == 'Y')]
        d = pd.to_datetime(q['TRD_DD'].astype(str).str.slice(0, 10).str.replace('/', '-', regex=False), errors='coerce')
        s = pd.Series(_num(q['A11']).values, index=d); s = s[s.index.notna()]; s = s[~s.index.duplicated(keep='last')].sort_index()
        s = s[s.index <= C.END].reindex(D.td)
        if s[D.td >= C.START].notna().sum() < 3000: raise RuntimeError(f'외국인 옵션({cp}) 흐름이 3,000일 미만 — 멈춤')
        out[cp] = s
    return out['C'], out['P']


def _chain(name):
    c = pd.read_csv(_raw(name), low_memory=False)
    for col in ('날짜', 'cp', 'K', 'oi'):
        if col not in c: raise KeyError(f'{name} 에 {col} 열 없음')
    c['date'] = pd.to_datetime(c['날짜']); c = c[c['date'] <= C.END].dropna(subset=['K'])
    c['K'] = c['K'].astype(float); c['oi'] = pd.to_numeric(c['oi'], errors='coerce').fillna(0.0)
    return c


def weekly(D, kind, k2):
    """위클리 콜벽(a04_flows.weekly_walls 와 같음) → dict(dist, new, old, up1, dn1) 길이 D.n."""
    c = _chain({'WT': 'opt_chainwt_daily.csv.gz', 'WM': 'opt_chainwm_daily.csv.gz'}[kind])
    if 'exp' not in c: raise KeyError('위클리 자료에 exp 열 없음')
    calls = c[c['cp'] == 'C']; live = calls[calls['oi'] > 0]
    first = live.groupby('exp')['date'].min().to_dict()
    oimap = {(e, k, d): o for e, k, d, o in zip(calls['exp'].astype(str), calls['K'], calls['date'], calls['oi'])}
    n = D.n; pos = {d: i for i, d in enumerate(D.td)}
    K = np.full(n, np.nan); dist = np.full(n, np.nan); E = [None] * n
    for d, g in live.groupby('date'):
        i = pos.get(d); s = float(k2.get(d, np.nan))
        if i is None or not np.isfinite(s): continue
        if g['exp'].nunique() > 1:
            e = min(g['exp'].unique(), key=lambda x: first[x]); g = g[g['exp'] == e]
        ca = g[g['K'] > s]
        if len(ca) < 2: continue
        j = ca['oi'].values.argmax()
        K[i] = float(ca['K'].values[j]); dist[i] = (K[i] / s - 1) * 100; E[i] = str(g['exp'].iloc[0])
    if np.isfinite(K).sum() < 200: raise RuntimeError(f'위클리({kind}) 콜벽이 200일 미만 — 멈춤')
    new = np.zeros(n, bool); old = np.zeros(n, bool); up1 = np.zeros(n, bool); dn1 = np.zeros(n, bool); last = None
    for i in range(n):
        if not np.isfinite(K[i]): continue
        if last is not None:
            if round(K[i], 3) != round(last, 3): new[i] = True
            else: old[i] = True
        last = K[i]
        if i > 0:
            a = oimap.get((E[i], K[i], D.td[i])); b = oimap.get((E[i], K[i], D.td[i - 1]))
            if a is not None and b is not None:
                up1[i] = a - b > 0; dn1[i] = a - b < 0
    return {'dist': dist, 'new': new, 'old': old, 'up1': up1, 'dn1': dn1}


def _second_thursday(y, m):
    d = pd.Timestamp(year=y, month=m, day=1)
    return d + pd.Timedelta(days=(3 - d.weekday()) % 7 + 7)


def _expiry(ym, td):
    st = _second_thursday(int(ym[:4]), int(ym[4:6]))
    if st > td[-1]: return st
    i = td.searchsorted(st, side='right') - 1
    return td[i] if i >= 0 else st


def q2_wall(D, k2):
    """차기 분기물(Q2) 콜벽 — a02_features.py 의 계산을 '살아 있는 결제월 4개 중 두 번째 분기월'에 그대로. → dict(dist, new, old, up5, up1, dn5)."""
    ch = _chain('opt_chainx_daily.csv.gz')
    if 'ym' not in ch: raise KeyError('opt_chainx 에 ym 열 없음')
    ch['ym'] = ch['ym'].astype(str).str.slice(0, 6); ch = ch[ch['ym'].str.len() == 6]
    exp_of = {ym: _expiry(ym, D.td) for ym in ch['ym'].unique()}
    dates = np.sort(ch['date'].unique()); dpos = {pd.Timestamp(d): i for i, d in enumerate(dates)}
    pick = {}
    for d, yms in ch.groupby('date')['ym'].unique().items():
        q = [y for y in sorted(y for y in yms if exp_of[y] > d) if int(y[4:6]) in (3, 6, 9, 12)]
        if len(q) > 1: pick[d] = q[1]
    if len(pick) < 500: raise RuntimeError('차기 분기물이 있는 날이 500일 미만 — 멈춤')
    sub = ch[ch['ym'] == ch['date'].map(pick)]
    qc = ch[(ch['cp'] == 'C') & ch['ym'].str.slice(4, 6).isin(['03', '06', '09', '12'])]
    oikey = {(d, ym, k): o for d, ym, k, o in zip(qc['date'], qc['ym'], qc['K'], qc['oi'])}
    n = D.n; pos = {d: i for i, d in enumerate(D.td)}
    dist = np.full(n, np.nan); new = np.zeros(n, bool); old = np.zeros(n, bool); c5 = np.full(n, np.nan); c1 = np.full(n, np.nan); last = None
    for d, g in sub.groupby('date'):
        i = pos.get(d); s = float(k2.get(d, np.nan))
        if i is None: continue
        if not np.isfinite(s):
            s = float(g['spot'].median()) if 'spot' in g else np.nan
            if not np.isfinite(s): continue
        c = g[(g['cp'] == 'C') & (g['oi'] > 0)]; p = g[(g['cp'] == 'P') & (g['oi'] > 0)]
        if len(c) < 3 or len(p) < 3: continue
        ca = c[c['K'] > s]
        if len(ca) < 2: continue
        j = ca['oi'].values.argmax(); k1 = float(ca['K'].values[j]); woi = float(ca['oi'].values[j]); ym = pick[d]
        dist[i] = (k1 / s - 1) * 100
        if last is not None:
            if k1 != last: new[i] = True
            else: old[i] = True
        last = k1; di = dpos[d]
        for lag, arr in ((5, c5), (1, c1)):
            if di - lag >= 0:
                prev = oikey.get((pd.Timestamp(dates[di - lag]), ym, k1))
                if prev is not None and prev > 0: arr[i] = (woi / prev - 1) * 100
    if np.isfinite(dist).sum() < 500: raise RuntimeError('차기 분기물 콜벽이 500일 미만 — 멈춤')
    with np.errstate(invalid='ignore'):
        return {'dist': dist, 'new': new, 'old': old, 'up5': c5 > 0, 'up1': c1 > 0, 'dn5': c5 < 0}


def lab_age(D):
    """연구소 나이(같은 K·같은 결제월이 이어진 날 수, ALL 은 K 만)와 새 벽이 생긴 까닭(a04_flows.py 234~243·421~441줄과 같음)."""
    W = D.walls.copy(); W['date'] = pd.to_datetime(W['date'])
    for c in ('tag', 'ym', 'K', 'S'):
        if c not in W: raise KeyError(f'walls 표에 {c} 열 없음')
    W = W.drop_duplicates(['date', 'tag'], keep='last'); age = {}; orig = {}
    for tag in TAGS:
        g = W[W['tag'] == tag].sort_values('date').set_index('date')
        if len(g) < 1000: raise RuntimeError(f'walls 표의 {tag} 가 1,000일 미만 — 멈춤')
        key = g['K'].astype(float).round(3).astype(str) + ('' if tag == 'ALL' else '|' + g['ym'].astype(str))
        run = key.ne(key.shift()).cumsum()
        a = g.groupby(run).cumcount().add(1).where(g['K'].notna()).reindex(D.td).values.astype(float)
        kk = g['K'].astype(float).reindex(D.td).values; S = g['S'].astype(float).reindex(D.td).values
        ym = g['ym'].astype(str).reindex(D.td); ymv = np.where(ym.notna().values, ym.astype(object).values, None)
        kp = np.r_[np.nan, kk[:-1]]; ymp = np.r_[np.array([None], dtype=object), ymv[:-1]]
        with np.errstate(invalid='ignore'):
            new = (a <= 1) & np.isfinite(kk) & np.isfinite(kp)
            hasp = np.array([x is not None for x in ymp]); roll = new & hasp & np.array([x != y for x, y in zip(ymv, ymp)])
            cross = new & ~roll & (kp <= S); shift = new & ~roll & (kp > S)
        age[tag] = a; orig[tag] = {'new': new, 'roll': roll, 'cross': cross, 'shift': shift}
    return age, orig


# ------------------------------------------------------------------ 조건 묶음(마스크 + 설명)
WALL_KO = {'F0': '근월물', 'F1': '차월물', 'F2': '차차월물', 'F3': '넷째 결제월', 'Q': '분기물', 'ALL': '전 결제월 합산'}
FLOW_KO = {'none': '', 'fut': ' + 외국인 선물 3일 누적 순매수', 'spot': ' + 외국인 현물 3일 누적 순매수', 'both': ' + 외국인 선물·현물 3일 누적 함께 순매수'}
REG_KO = {'any': '', 'above': ' + 코스피 60일선 위', 'below': ' + 코스피 60일선 아래'}
CHG_KO = {'any': '', 'up5': ' + 벽 물량 5일 증가', 'up1': ' + 벽 물량 1일 증가', 'dn5': ' + 벽 물량 5일 감소'}
FLOW2 = [('fc3', ' + 외국인 콜 3일 누적 순매수'), ('fp3s', ' + 외국인 풋 3일 누적 순매도'), ('fcp3', ' + 외국인 콜 3일 누적 순매수·풋 3일 누적 순매도'), ('fp3b', ' + 외국인 풋 3일 누적 순매수'),
         ('fut5', ' + 외국인 선물 5일 누적 순매수'), ('spot5', ' + 외국인 현물 5일 누적 순매수'), ('both5', ' + 외국인 선물·현물 5일 누적 함께 순매수'),
         ('fut10', ' + 외국인 선물 10일 누적 순매수'), ('spot10', ' + 외국인 현물 10일 누적 순매수'), ('both10', ' + 외국인 선물·현물 10일 누적 함께 순매수'),
         ('ifut3', ' + 기관 선물 3일 누적 순매수'), ('pfut3', ' + 개인 선물 3일 누적 순매수'), ('ispot3', ' + 기관 현물 3일 누적 순매수'), ('pspot3', ' + 개인 현물 3일 누적 순매수')]


def _xcol(D, name):
    if name not in D.X.columns: raise KeyError(f'고정 자료에 {name} 열 없음(확인 불가) — 멈춤')
    return D.X[name]


def _band(d, b, below=False, incl0=False):
    with np.errstate(invalid='ignore'):
        if below: return (d >= -b) & ((d <= 0) if incl0 else (d < 0))
        return (d > 0) & (d <= b)


def _wall_ko(tag): return '동시 새 콜벽' if tag in ('K2', 'K3') else WALL_KO[tag] + ' 콜벽'


def _expand(D, comp, bases, fam, flows, flow_ko, quick=False):
    """벽 조건 목록 bases[(머리 id, 머리 설명, 뿌리, 마스크)] × 수급 × 장세 × 첫 신호 → (M, metas). metas[i] = dict(fam, id, desc, root)."""
    out_m = []; metas = []; live = comp['_live']
    for hid, htxt, root, bm in bases:
        b0 = live & bm
        for f in flows:
            bf = b0 & comp['_flow'][f]
            for r in REG:
                m = bf & comp['_reg'][r]
                for fs in FIRST:
                    out_m.append(D.first_only(m, FIRST_N) if fs else m)
                    metas.append({'fam': fam, 'id': f'{hid}_{f}_{r}_f{fs}', 'root': root,
                                  'desc': htxt + flow_ko[f] + REG_KO[r] + (' + 직전 5일 안 같은 조건 없던 첫날만' if fs else '')})
    return out_m, metas


def _sub(M, metas, quick, cap=300):
    M = np.asarray(M, dtype=bool) if not isinstance(M, np.ndarray) else M
    if quick and len(metas) > cap:
        idx = np.unique(np.linspace(0, len(metas) - 1, cap).astype(int)); return M[idx], [metas[i] for i in idx]
    return M, metas


def conds_g1(D, quick=False):
    T1 = _t1(); comp = T1.components(D, False); k2 = k200_close(D); age, orig = lab_age(D); Mx = []; metas = []
    def add(bases, fam):
        m, me = _expand(D, comp, bases, fam, FLOW, FLOW_KO); Mx.extend(m); metas.extend(me)
    # A 벽 나이 세분
    bases = []
    for t in TAGS:
        for b in DIST:
            for na in (3, 5, 7):
                for c in (['any'] if t == 'ALL' else ['any', 'up5', 'up1', 'dn5']):
                    with np.errstate(invalid='ignore'): m = _band(comp[t]['dist'], b) & (age[t] >= na) & comp[t]['chg'][c]
                    bases.append((f'AGE_{t}_b{int(round(b * 10)):02d}_a{na}_{c}', f'{WALL_KO[t]} 콜벽이 지수 위 0~{b}% 안 + 같은 벽 {na}일 이상 유지' + CHG_KO[c], _wall_ko(t), m))
    add(bases, 'A')
    # B 셋 이상 동시 새 벽(T1 의 K2 정의에서 둘 → 셋)
    news = {t: comp[t]['age']['new'] for t in K_TAGS}
    with np.errstate(invalid='ignore'):
        k3 = sum(v.astype(int) for v in news.values()) >= 3
        dmin = np.fmin.reduce([np.where(news[t] & (comp[t]['dist'] > 0), comp[t]['dist'], np.nan) for t in K_TAGS]); dmin = np.where(k3, dmin, np.nan)
    bases = []
    for b in DIST:
        for c in ('any', 'up5', 'up1', 'dn5'):
            cm = np.ones(D.n, bool) if c == 'any' else (k3 & np.any([news[t] & comp[t]['chg'][c] for t in ('F0', 'F1', 'F2')], axis=0))
            bases.append((f'K3_b{int(round(b * 10)):02d}_{c}', f'근월·차월·차차월·합산 중 셋 이상이 같은 날 새 콜벽 + 가장 가까운 새 벽이 지수 위 0~{b}% 안' + CHG_KO[c].replace('벽 물량', '새 벽 물량(하나라도)'),
                          '동시 새 콜벽', k3 & _band(dmin, b) & cm))
    add(bases, 'B')
    # C 새 벽이 생긴 까닭
    OR_KO = {'shift': '물량 이동으로 생긴 새 벽(옛 벽이 아직 지수 위)', 'cross': '지수가 옛 벽을 넘어서 생긴 새 벽', 'roll': '만기 교체로 생긴 새 벽'}
    bases = []
    for t in TAGS:
        for o in ('shift', 'cross', 'roll'):
            for b in DIST:
                bases.append((f'ORG_{t}_{o}_b{int(round(b * 10)):02d}', f'{WALL_KO[t]} 콜벽이 지수 위 0~{b}% 안 + {OR_KO[o]}', _wall_ko(t), _band(comp[t]['dist'], b) & orig[t][o]))
    add(bases, 'C')
    # C2 둘 이상 동시 새 벽(연구소 나이 1일)을 까닭으로
    nl = {t: orig[t]['new'] for t in K_TAGS}; cnt = sum(v.astype(int) for v in nl.values())
    nsh = sum(orig[t]['shift'].astype(int) for t in K_TAGS); ncr = sum(orig[t]['cross'].astype(int) for t in K_TAGS); nro = sum(orig[t]['roll'].astype(int) for t in K_TAGS)
    with np.errstate(invalid='ignore'):
        k2m = cnt >= 2; d2 = np.fmin.reduce([np.where(nl[t] & (comp[t]['dist'] > 0), comp[t]['dist'], np.nan) for t in K_TAGS]); d2 = np.where(k2m, d2, np.nan)
    bases = []
    for kid, km, kt in (('K2s', k2m & (nsh == cnt), '모두 물량 이동으로 생김'), ('K2c', k2m & (ncr >= 1), '하나 이상은 지수가 옛 벽을 넘어서 생김'), ('K2n', k2m & (nro == 0), '만기 교체로 생긴 벽 없음')):
        for b in DIST:
            bases.append((f'{kid}_b{int(round(b * 10)):02d}', f'근월·차월·차차월·합산 중 둘 이상이 같은 날 새 콜벽({kt}) + 가장 가까운 새 벽이 지수 위 0~{b}% 안', '동시 새 콜벽', km & _band(d2, b)))
    add(bases, 'C2')
    # D 위클리 콜벽
    bases = []
    for wk, wko in (('WT', '목 위클리'), ('WM', '월 위클리')):
        w = weekly(D, wk, k2); ones = np.ones(D.n, bool)
        for b in DIST:
            for a, am, at in (('any', ones, ''), ('new', w['new'], ' + 새 벽(앞 자료일과 다른 행사가)'), ('old', w['old'], ' + 앞 자료일과 같은 벽')):
                for c, cm, ct in (('any', ones, ''), ('up1', w['up1'], ' + 벽 물량 전일 대비 증가'), ('dn1', w['dn1'], ' + 벽 물량 전일 대비 감소')):
                    bases.append((f'{wk}_b{int(round(b * 10)):02d}_{a}_{c}', f'{wko} 콜벽이 지수 위 0~{b}% 안' + at + ct, '위클리 콜벽', _band(w['dist'], b) & am & cm))
    add(bases, 'D')
    # E 차기 분기물
    q2 = q2_wall(D, k2); ones = np.ones(D.n, bool); bases = []
    for b in DIST:
        for a, am, at in (('any', ones, ''), ('new', q2['new'], ' + 오늘 새로 생긴 벽'), ('old', q2['old'], ' + 앞서와 같은 벽')):
            for c in ('any', 'up5', 'up1', 'dn5'):
                bases.append((f'Q2_b{int(round(b * 10)):02d}_{a}_{c}', f'차기 분기물 콜벽이 지수 위 0~{b}% 안' + at + CHG_KO[c], '차기 분기물 콜벽', _band(q2['dist'], b) & am & (ones if c == 'any' else q2[c])))
    add(bases, 'E')
    # F 풋벽 · G 넘어선 벽
    W = D.walls.drop_duplicates('date'); S = pd.Series(W['S'].astype(float).values, index=pd.to_datetime(W['date'])).reindex(D.td).values
    bf = []; bg = []
    for t in TAGS:
        pd_ = _xcol(D, f'OW_{t}_pwall_dist%').values.astype(float); ps = _xcol(D, f'OW_{t}_passed_wall_dist%').values.astype(float)
        kp = np.round(S * (1 + pd_ / 100), 2); new = np.zeros(D.n, bool); old = np.zeros(D.n, bool); last = None
        for i in range(D.n):
            if not np.isfinite(kp[i]): continue
            if last is not None:
                if kp[i] != last: new[i] = True
                else: old[i] = True
            last = kp[i]
        ones = np.ones(D.n, bool)
        for b in DIST:
            for a, am, at in (('any', ones, ''), ('new', new, ' + 오늘 새로 생긴 풋벽'), ('old', old, ' + 앞서와 같은 풋벽')):
                bf.append((f'PUT_{t}_b{int(round(b * 10)):02d}_{a}', f'{WALL_KO[t]} 풋벽이 지수 아래 0~{b}% 안' + at, '풋벽', _band(pd_, b, below=True) & am))
            bg.append((f'PAS_{t}_b{int(round(b * 10)):02d}', f'{WALL_KO[t]} 이미 넘어선 콜벽이 지수 아래 0~{b}% 안', '넘어선 콜벽', _band(ps, b, below=True, incl0=True)))
    add(bf, 'F'); add(bg, 'G')
    return _sub(np.asarray(Mx, dtype=bool), metas, quick)


def conds_g2(D, quick=False):
    T1 = _t1(); comp = T1.components(D, False); cf, pf = opt_flows(D); X = D.X
    rs = lambda s, w: s.rolling(w, min_periods=w).sum()
    fut = _xcol(D, 'F_외국인_1d'); spot = _xcol(D, 'S_외국인현물_1d')
    with np.errstate(invalid='ignore'):
        fl = {'fc3': (rs(cf, 3) > 0).values, 'fp3s': (rs(pf, 3) < 0).values, 'fp3b': (rs(pf, 3) > 0).values}
        fl['fcp3'] = fl['fc3'] & fl['fp3s']
        for w in (5, 10):
            fl[f'fut{w}'] = (rs(fut, w) > 0).values; fl[f'spot{w}'] = (rs(spot, w) > 0).values; fl[f'both{w}'] = fl[f'fut{w}'] & fl[f'spot{w}']
        for k, col in (('ifut3', 'F_기관_1d'), ('pfut3', 'F_개인_1d'), ('ispot3', 'S_기관현물_1d'), ('pspot3', 'S_개인현물_1d')):
            fl[k] = (rs(_xcol(D, col), 3) > 0).values
    comp2 = dict(comp); comp2['_flow'] = fl; AGE_KO = {'any': '', 'new': ' + 오늘 새로 생긴 벽', 'old': ' + 어제와 같은 벽'}; bases = []
    for t in TAGS:
        for b in DIST:
            for a in ('any', 'new', 'old'):
                bases.append((f'FL_{t}_b{int(round(b * 10)):02d}_{a}', f'{WALL_KO[t]} 콜벽이 지수 위 0~{b}% 안' + AGE_KO[a], _wall_ko(t), _band(comp[t]['dist'], b) & comp[t]['age'][a]))
    for b in DIST:
        bases.append((f'FL_K2_b{int(round(b * 10)):02d}_new', f'근월·차월·차차월·합산 중 둘 이상이 같은 날 새 콜벽 + 가장 가까운 새 벽이 지수 위 0~{b}% 안', '동시 새 콜벽', _band(comp['K2']['dist'], b) & comp['K2']['age']['new']))
    M, metas = _expand(D, comp2, bases, 'H', [k for k, _ in FLOW2], dict(FLOW2))
    return _sub(np.asarray(M, dtype=bool), metas, quick)


def conds_t1(D, quick=False, fam='I'):
    """T1 의 조건 묶음 그대로(8,040개). metas 에 T1 의 규칙 이름을 만들 재료(t1)를 둔다."""
    T1 = _t1(); comp = T1.components(D, False); Ms = []; metas = []
    for w in T1.WALLS:
        cl = T1.cond_list(w, False); Ms.append(T1.build_M(D, comp, w, False))
        metas += [{'fam': fam, 't1': (w,) + tuple(t), 'root': _wall_ko(w)} for t in cl]
    return _sub(np.concatenate(Ms), metas, quick)


def rule_id(me, d, row, direction):
    dn = 'up' if direction > 0 else 'dn'
    if 't1' in me:
        w, bi, a, c, f, r, fs = me['t1']; return _t1().rule_id(w, bi, a, c, f, r, fs, d, row + 1, direction, False)
    return f"{me['id']}_d{d}_h{row + 1}_{dn}"


def rule_desc(me, d, row, direction):
    if 't1' in me:
        w, bi, a, c, f, r, fs = me['t1']; return _t1().rule_desc(w, bi, a, c, f, r, fs, d, row + 1, direction, False)
    return me['desc'] + ' → ' + ('하루 쉬고 ' if d else '다음 날 시가 ') + f"매수, {row + 1}일 보유, {'오름' if direction > 0 else '내림'}"


# ------------------------------------------------------------------ 결과 줄(보유일 1~20 + 닿기)·솎기
def outcome_rows(D, touch=False):
    n = D.n; nr = MAXH + (len(TOUCH) if touch else 0)
    RU = np.zeros((nr, n), bool); RD = RU.copy(); OK = RU.copy(); EX = np.full((nr, n), -1, dtype=np.int32); ar = np.arange(n)
    with np.errstate(invalid='ignore'):
        for h in range(1, MAXH + 1):
            r = D.fwd(h); RU[h - 1] = r > 0; RD[h - 1] = r < 0; OK[h - 1] = np.isfinite(r); EX[h - 1] = np.where(ar + h < n, ar + h, -1)
        Y = {}
        if touch:
            for j, k in enumerate(TOUCH):
                y, ex = C.first_touch(D, k=k, max_days=TOUCH_DAYS); RU[MAXH + j] = y == 1; RD[MAXH + j] = y == 0; OK[MAXH + j] = np.isfinite(y)
                EX[MAXH + j] = np.where(np.isfinite(y), ex, -1); Y[k] = y
    return RU, RD, OK, EX, Y


def _thin_rows(Msub, rows, EXr, n):
    """조건 묶음마다 (늦춤 × 결과 줄)별 독립 거래의 신호 위치(= 조건일 + 늦춤). 청산 위치 EX[줄, 신호] 가 없으면(-1) 뺀다. D.thin_pos 와 같은 규칙."""
    out = []; exl = [e.tolist() for e in EXr]
    for row in Msub:
        pos = np.flatnonzero(row).tolist()
        for d in DELAY:
            for ri in range(len(rows)):
                ex = exl[ri]; keep = []; last = -1
                for p in pos:
                    s = p + d
                    if s < n and s >= last:
                        e = ex[s]
                        if e >= 0: keep.append(s); last = e
                out.append(np.asarray(keep, dtype=np.int16))
    return out


def build_G(D, M, rows, RU, RD, OK, EX, procs):
    """규칙 = 조건 묶음 × 늦춤 × 결과 줄(방향은 채점에서). 독립 거래를 솎아 해마다 누적표를 만든다."""
    n = D.n; rows = list(rows)
    chunks = [c for c in np.array_split(np.arange(len(M)), NJ * 2) if len(c)]
    res = _par(_thin_rows, [(M[c], rows, EX[rows], n) for c in chunks]); segs = [s for r in res for s in r]
    nc = len(M); nb = nc * len(DELAY) * len(rows)
    assert len(segs) == nb
    cs = np.repeat(np.arange(nc), len(DELAY) * len(rows)); delay = np.tile(np.repeat(DELAY, len(rows)), nc); row = np.tile(np.asarray(rows), nc * len(DELAY))
    S = (np.concatenate(segs) if segs else np.zeros(0)).astype(np.int64); cnt = np.asarray([len(s) for s in segs], dtype=np.int64); off = np.r_[0, np.cumsum(cnt)]
    jrep = np.repeat(np.arange(nb), cnt); rr = row[jrep]
    flat = (rr * n + S).astype(np.int32); bins = (jrep * NYB + (D.year[EX[rr, S]] - Y0)).astype(np.int32)
    cumN = np.bincount(bins, minlength=nb * NYB).reshape(nb, NYB).cumsum(1)
    years = [y for y, _ in C.wf_splits()]
    rowh = np.r_[np.arange(1, MAXH + 1), np.zeros(RU.shape[0] - MAXH, dtype=int)]
    return {'n': n, 'nb': nb, 'years': years, 'nmin': [max(12, int(round(35 * (y - Y0) / 17))) for y in years], 'cumN': cumN, 'flat': flat, 'bin': bins,
            'RU': RU, 'RD': RD, 'OK': OK, 'EX': EX, 'M': M, 'cs': cs, 'delay': delay, 'row': row, 'rowh': rowh, 'year': D.year.astype(np.int64), 'S': S, 'off': off,
            'yr': [(int(np.flatnonzero(D.year == y)[0]), int(np.flatnonzero(D.year == y)[-1]) + 1) for y in years], 'procs': list(procs)}


def _wilson_lb(k, n, z=C.Z90):
    p = k / n; d = 1 + z * z / n; c = p + z * z / (2 * n); h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (c - h) / d


def _sig_matrix(G, U, a, e):
    cs = G['cs'][U]; out = G['M'][cs, a:e]; d1 = np.flatnonzero(G['delay'][U] == 1)
    if len(d1): out[d1] = G['M'][cs[d1], a - 1:e - 1]
    return out


def _median_hold(S, h):
    vals = np.unique(h); cum = np.stack([(S & (h == v)[:, None]).sum(0) for v in vals]).cumsum(0); tot = cum[-1]
    lo = vals[(cum >= np.ceil(tot / 2)[None]).argmax(0)]; hi = vals[(cum >= (tot // 2 + 1)[None]).argmax(0)]
    return np.floor((lo + hi) / 2 + 0.5).astype(int)


def _thin_tr(s, r, EX):
    """절차의 거래(신호 위치 s·결과 줄 r, 날짜 순)를 한 계좌로 솎은 자리."""
    keep = []; last = -1; ex = EX[r, s].tolist()
    for i, a in enumerate(s.tolist()):
        if a >= last and ex[i] >= 0: keep.append(i); last = ex[i]
    return np.asarray(keep, dtype=int)


def _score(s, r, EX, R, OK, year=None):
    if not len(s): return 0, 0, {}
    kp = _thin_tr(s, r, EX); s = s[kp]; r = r[kp]; ok = OK[r, s]; hit = R[r, s] & ok; by = {}
    if year is not None:
        y = year[s]
        for a in np.unique(y): by[int(a)] = (int(ok[y == a].sum()), int(hit[y == a].sum()))
    return int(ok.sum()), int(hit.sum()), by


def evaluate(G, perm=None, detail=False):
    """고르기(해마다 그 전 자료) → 그 해 채점. perm = 결과 줄의 자리 바꿈(가짜). 절차 = (방향, 꼴, 쓰는 수, 만드는 법)."""
    n = G['n']; nb = G['nb']; years = G['years']; procs = G['procs']; EX = G['EX']; rowh = G['rowh']
    RU, RD, OK = (G['RU'], G['RD'], G['OK']) if perm is None else (G['RU'][:, perm], G['RD'][:, perm], G['OK'][:, perm])
    res = {'proc': np.zeros((len(procs), 2), dtype=np.int64), 'ins': np.zeros((2, 2), dtype=np.int64)}
    if detail: res.update({'K': {}, 'trades': {}, 'by': {}, 'sel': []})
    tn = G['cumN'][:, -1]; big = tn >= 35
    for di, (dn, R) in enumerate((('up', RU), ('dn', RD))):
        K = np.bincount(G['bin'], weights=R.ravel()[G['flat']], minlength=nb * NYB).reshape(nb, NYB).cumsum(1) if nb else np.zeros((0, NYB))
        tk = K[:, -1]; res['ins'][di] = [int((big & (tk >= 0.85 * tn - 1e-9)).sum()), int((big & (tk >= 0.80 * tn - 1e-9)).sum())]
        if detail: res['K'][dn] = K
        mine = [p for p in procs if p[0] == dn]
        if not mine: continue
        shapes = sorted({p[1] for p in mine}); tr = {p: ([], []) for p in mine}
        for yi, Y in enumerate(years):
            b = Y - 1 - Y0; nn = G['cumN'][:, b]; idx = np.flatnonzero(nn >= G['nmin'][yi])
            if not len(idx): continue
            kk = K[idx, b]; nv = nn[idx].astype(float); hit = kk / nv; lb = _wilson_lb(kk, nv); a, e = G['yr'][yi]
            for sh in shapes:
                kind, thr = SHAPES[sh]; m = (hit if kind == 'hit' else lb) >= thr - 1e-9; sel = idx[m]
                if detail:
                    rec = {'year': Y, 'dir': dn, 'shape': sh, 'n_min': G['nmin'][yi], 'n_enough': len(idx), 'n_sel': len(sel)}
                if not len(sel):
                    if detail: res['sel'].append(rec)
                    continue
                U = sel[np.lexsort((sel, -nv[m], -lb[m]))]
                if detail:
                    j = int(U[0]); rec.update({'top_j': j, 'top_n': int(nn[j]), 'top_k': int(K[j, b])}); res['sel'].append(rec)
                ps = [p for p in mine if p[1] == sh]; kmax = max(len(U) if p[2] == 0 else min(p[2], len(U)) for p in ps)
                U = U[:kmax]; SY = _sig_matrix(G, U, a, e); rU = G['row'][U]; hU = rowh[rU]
                for p in ps:
                    k = len(U) if p[2] == 0 else min(p[2], len(U)); S = SY[:k]; ratio = HOWS[p[3]]
                    if ratio is None:
                        days = np.flatnonzero(S.any(0))
                        if len(days): tr[p][0].append(a + days); tr[p][1].append(rU[S[:, days].argmax(0)])
                    else:
                        need = max(2, math.ceil(ratio * k - 1e-9)); days = np.flatnonzero(S.sum(0) >= need)
                        if len(days): tr[p][0].append(a + days); tr[p][1].append(_median_hold(S[:, days], hU[:k]) - 1)
        for p, (ss, rr) in tr.items():
            s = np.concatenate(ss).astype(np.int64) if ss else np.zeros(0, dtype=np.int64); r = np.concatenate(rr).astype(np.int64) if rr else np.zeros(0, dtype=np.int64)
            nn_, kk_, by = _score(s, r, EX, R, OK, G['year'] if detail else None)
            res['proc'][procs.index(p)] = (nn_, kk_)
            if detail: res['trades'][p] = (s, r); res['by'][p] = by
    return res


def _rot_perm(year, rng):
    perm = np.arange(len(year))
    for y in np.unique(year):
        idx = np.flatnonzero(year == y)
        if len(idx) > 1: perm[idx] = np.roll(idx, int(rng.integers(1, len(idx))))
    return perm


def _fake_chunk(G, its):
    out = []
    for it in its:
        r = evaluate(G, _rot_perm(G['year'], np.random.default_rng(C.SEED + 1 + int(it))))
        out.append((r['proc'], r['ins']))
    return out


def run_fakes(G, nf):
    Gs = {k: v for k, v in G.items() if k not in ('S', 'off')}
    fk = [x for r in _par(_fake_chunk, [(Gs, c) for c in np.array_split(np.arange(nf), min(nf, NJ * 2)) if len(c)]) for x in r]
    return np.stack([x[0] for x in fk]).astype(float), np.stack([x[1] for x in fk]).astype(float)


# ------------------------------------------------------------------ 말
SH_KO = {'goal': '통과 꼴(적중 85% 이상)', 'watch': '관찰 꼴(적중 80% 이상)', 'h75': '적중 75% 이상', 'h90': '적중 90% 이상', 'lb60': '윌슨 하한 60% 이상', 'lb70': '윌슨 하한 70% 이상'}
CN_KO = {1: '윌슨 하한 상위 1개', 5: '상위 5개', 20: '상위 20개', 0: '고른 것 전부'}
HOW_KO = {'any': '하나라도 켜진 날 매수(그 규칙 보유일)', 'cons': '쓰는 규칙의 20% 이상이 함께 켜진 날 매수(보유일 가운뎃값)',
          'cons10': '쓰는 규칙의 10% 이상이 함께 켜진 날 매수(보유일 가운뎃값)', 'cons30': '쓰는 규칙의 30% 이상이 함께 켜진 날 매수(보유일 가운뎃값)'}


def proc_id(pre, p): return f"{pre}_{p[1]}_{'all' if p[2] == 0 else 'top%d' % p[2]}_{p[3]}_{p[0]}"


def proc_desc(head, p):
    return f"[{head}] 해마다 그 전 자료에서 {SH_KO[p[1]]} 규칙을 골라 {CN_KO[p[2]]} 사용 · {HOW_KO[p[3]]} → {'오름' if p[0] == 'up' else '내림'}"


def _pc(k, n): return '–' if n < 10 else f'{100 * k / n:.1f}%'


def _md(df):
    if df is None or not len(df): return ['- (줄 없음)']
    out = ['| ' + ' | '.join(map(str, df.columns)) + ' |', '|' + '---|' * len(df.columns)]
    return out + ['| ' + ' | '.join(str(v) for v in r) + ' |' for r in df.values.tolist()]


def _trades_df(D, s, r, EX):
    ex = EX[r, s]; ok = ex >= 0
    return pd.DataFrame({'signal': D.td[s[ok]], 'exit': D.td[ex[ok]]})


def wf_tables(G, real, FP, pre, head, procs=None, nf=0):
    """절차별 실제 대 가짜 표와 해마다 표. FP = None 이면 가짜 칸은 '–'."""
    procs = G['procs'] if procs is None else procs; rows = []; yrs = G['years']
    for p in procs:
        pi = G['procs'].index(p); rn, rk = map(int, real['proc'][pi]); row = {'절차': proc_id(pre, p), '설명': proc_desc(head, p), '실제 독립 거래': rn, '실제 다음 해 적중': _pc(rk, rn)}
        if FP is not None:
            fn = FP[:, pi, 0]; fh = np.where(fn > 0, FP[:, pi, 1] / np.maximum(fn, 1), np.nan); v = fh[fn >= 10]; rh = rk / rn if rn else np.nan
            q = (lambda x: f'{100 * np.quantile(v, x):.1f}%') if len(v) else (lambda x: '–')
            row.update({'가짜 평균 거래': round(float(fn.mean()), 1), '가짜 적중 평균': (f'{100 * v.mean():.1f}%' if len(v) else '–'), '가짜 5%': q(0.05), '가짜 50%': q(0.5), '가짜 95%': q(0.95),
                        '가짜가 실제 이상인 비율': (round(float((1 + np.nansum(fh >= rh - 1e-12)) / (1 + nf)), 3) if rn >= 10 else '–'), '가짜 횟수': nf})
        rows.append(row)
    T_year = pd.DataFrame([{'절차': proc_id(pre, p), **{str(y): '/'.join(map(str, real['by'][p].get(y, (0, 0)))) for y in yrs}} for p in procs])
    return pd.DataFrame(rows), T_year


# ------------------------------------------------------------------ 묶음 하나(G1·G2·G3) 계산
def run_bundle(D, name, M, metas, rows, quick):
    if not quick:                                                   # 가족이 통째로 비어 있으면(자료를 못 읽은 것과 같음) 조용히 넘기지 않고 멈춘다
        days = {}
        for i, me_ in enumerate(metas): days[me_['fam']] = days.get(me_['fam'], 0) + int(M[i].sum())
        empty = [FAM_KO[k] for k, v in days.items() if v == 0]
        if empty: raise RuntimeError(f'조건이 한 번도 켜지지 않는 가족: {empty} — 자료를 확인할 것(멈춤)')
    RU, RD, OK, EX, _ = outcome_rows(D); G = build_G(D, M, rows, RU, RD, OK, EX, PROCS_T1); nb = G['nb']; n = D.n
    real = evaluate(G, None, detail=True); nf = 3 if quick else N_FAKE; FP, FI = run_fakes(G, nf)
    head = f'W3 {BUNDLE_KO[name]}'; pre = f'WF_{name}'; cands = []; tn = G['cumN'][:, -1]
    meta_of = lambda j: metas[G['cs'][j]]
    for p in PROCS_T1:
        s, r = real['trades'][p]
        cands.append({'id': proc_id(pre, p), 'family': f'wf 절차({BUNDLE_KO[name]})', 'desc': proc_desc(head, p), 'direction': 1 if p[0] == 'up' else -1, 'hold': None, 'kind': 'wf',
                      'trades': _trades_df(D, s, r, EX), 'root': f'W3 {BUNDLE_KO[name]} 묶음에서 해마다 고름', 'params': {'bundle': name, 'shape': p[1], 'count': p[2], 'how': p[3]}})
    T_fake, T_year = wf_tables(G, real, FP, pre, head, nf=nf)
    # 해마다 고른 규칙 수와 1위 규칙
    rows_ = []
    for r_ in real['sel']:
        row = {'해': r_['year'], '방향': '오름' if r_['dir'] == 'up' else '내림', '꼴': SH_KO[r_['shape']], '최소 거래 수': r_['n_min'], '거래 수 채운 규칙': r_['n_enough'], '고른 규칙 수': r_['n_sel']}
        if r_.get('top_j') is not None:
            j = r_['top_j']; row.update({'1위 규칙': rule_desc(meta_of(j), int(G['delay'][j]), int(G['row'][j]), 1 if r_['dir'] == 'up' else -1), '1위 그때까지 거래': r_['top_n'], '1위 그때까지 적중': _pc(r_['top_k'], r_['top_n'])})
        rows_.append(row)
    T_sel = pd.DataFrame(rows_)
    # 전체 기간: 통과 숫자를 채운 규칙 수 실제 대 가짜
    rows_ = []
    for di, dn in enumerate(('up', 'dn')):
        for ti, thr in enumerate((85, 80)):
            f = FI[:, di, ti]
            rows_.append({'방향': '오름' if di == 0 else '내림', '기준': f'독립 35건 이상·적중 {thr}% 이상', '규칙 수(실제)': int(real['ins'][di, ti]), '규칙 수(가짜 평균)': round(float(f.mean()), 1),
                          '가짜 95%': round(float(np.quantile(f, 0.95)), 1), '가짜가 실제 이상인 비율': round(float((1 + (f >= real['ins'][di, ti]).sum()) / (1 + nf)), 3)})
    T_ins = pd.DataFrame(rows_)
    # 가족별
    famj = np.asarray([metas[c]['fam'] for c in G['cs']]); fams = list(dict.fromkeys(m['fam'] for m in metas)); fam = {}; rows_ = []
    for f in fams:
        mj = famj == f; fam[f] = int(2 * mj.sum()); row = {'가족': FAM_KO[f], '시험한 가짓수(방향 2 포함)': fam[f], '독립 10건 이상': int(2 * (mj & (tn >= 10)).sum()), '독립 35건 이상': int(2 * (mj & (tn >= 35)).sum())}
        for dn, ko in (('up', '오름'), ('dn', '내림')):
            tk = real['K'][dn][:, -1]
            row[f'35건·85% 이상({ko})'] = int((mj & (tn >= 35) & (tk >= 0.85 * tn - 1e-9)).sum()); row[f'35건·80% 이상({ko})'] = int((mj & (tn >= 35) & (tk >= 0.80 * tn - 1e-9)).sum())
        rows_.append(row)
    T_fam = pd.DataFrame(rows_)
    # fixed: 방향별 적중 상위
    seen = set()
    for di, dn in enumerate(('up', 'dn')):
        tk = real['K'][dn][:, -1]; idx = np.flatnonzero(tn >= 35)
        o = idx[np.lexsort((idx, -tn[idx], -(tk[idx] / tn[idx])))][:TOP_FIXED]; direction = 1 if di == 0 else -1
        for j in o:
            j = int(j); me = meta_of(j); d = int(G['delay'][j]); row = int(G['row'][j]); rid = rule_id(me, d, row, direction)
            if rid in seen: continue
            seen.add(rid)
            cands.append({'id': rid, 'family': FAM_KO[me['fam']], 'desc': rule_desc(me, d, row, direction), 'direction': direction, 'hold': row + 1, 'kind': 'fixed',
                          'trades': D.trades_from_pos(np.flatnonzero(M[G['cs'][j]]), row + 1, d), 'root': me['root'], 'params': {'bundle': name, 'delay': d, 'hold': row + 1}})
    md = [f'#### 묶음 {name} — {BUNDLE_KO[name]}' + (' [quick 시험]' if quick else ''), '',
          f'시험한 규칙 {2 * nb:,}개(방향 포함), 해마다 고르는 절차 {len(PROCS_T1)}개, 가짜 {nf}번(수익률 줄을 해 안에서만 통째로 돌림).', '',
          '(1) 가족별 가짓수와 전체 기간에 통과 숫자를 채운 규칙 수(결과를 보고 센 숫자)', ''] + _md(T_fam) + ['',
          '(2) 통과 숫자를 채운 규칙 수 — 실제 대 가짜(우연히도 이만큼은 나온다)', ''] + _md(T_ins) + ['',
          '(3) 해마다 고르는 절차의 다음 해 적중 — 실제 대 가짜. 독립 거래 10건 미만은 %를 적지 않는다.', ''] + _md(T_fake.drop(columns=['절차', '가짜 횟수'])) + ['',
          '(4) 절차별 해마다(독립 거래 수/맞은 수)', ''] + _md(T_year) + ['']
    return {'cands': cands, 'fam': fam, 'm_wf': len(PROCS_T1), 'm_fixed_pool': int(2 * nb), 'md': md,
            'tables': {f'{name}_family_counts.csv': T_fam, f'{name}_insample_counts.csv': T_ins, f'{name}_wf_fake.csv': T_fake, f'{name}_wf_by_year.csv': T_year, f'{name}_wf_picks.csv': T_sel}}


# ------------------------------------------------------------------ (나) 고르는 절차의 다른 꼴
def run_alt(D, quick):
    M, metas = conds_t1(D, quick, fam='J'); RU, RD, OK, EX, _ = outcome_rows(D)
    procs = PROCS_T1 + PROCS_ALT + PROCS_RATIO; G = build_G(D, M, [h - 1 for h in HOLDS], RU, RD, OK, EX, procs)
    real = evaluate(G, None, detail=True); nf = 3 if quick else N_FAKE; FP, _ = run_fakes(G, nf)
    head = 'W3 고르는 꼴 바꿈 · T1 원래 가족'; cands = []; new = PROCS_ALT + PROCS_RATIO
    for p in new:
        s, r = real['trades'][p]
        cands.append({'id': proc_id('ALT', p), 'family': 'wf 절차(고르는 꼴 바꿈)', 'desc': proc_desc(head, p), 'direction': 1 if p[0] == 'up' else -1, 'hold': None, 'kind': 'wf',
                      'trades': _trades_df(D, s, r, EX), 'root': 'T1 가족에서 해마다 고름(다른 문턱·합의 비율)', 'params': {'shape': p[1], 'count': p[2], 'how': p[3]}})
    T_fake, T_year = wf_tables(G, real, FP, 'ALT', head, procs=new, nf=nf)
    # 두 방향 함께: 같은 날 두 방향이 함께 켜지면 둘 다 버리고, 한 계좌로 솎는다
    rows_ = []
    for pu in [p for p in PROCS_T1 if p[0] == 'up']:
        pdn = ('dn',) + pu[1:]; su, ru = real['trades'][pu]; sd, rd = real['trades'][pdn]
        both = np.intersect1d(su, sd); ku = ~np.isin(su, both); kd = ~np.isin(sd, both)
        s = np.r_[su[ku], sd[kd]]; r = np.r_[ru[ku], rd[kd]]; dr = np.r_[np.ones(int(ku.sum()), int), -np.ones(int(kd.sum()), int)]
        o = np.argsort(s, kind='mergesort'); s, r, dr = s[o], r[o], dr[o]; kp = _thin_tr(s, r, EX); s, r, dr = s[kp], r[kp], dr[kp]
        ok = OK[r, s]; hit = np.where(dr > 0, RU[r, s], RD[r, s]) & ok; ex = EX[r, s]
        with np.errstate(invalid='ignore'): ret = np.where(ok, dr * (D.c[np.maximum(ex, 0)] / D.o[np.minimum(s + 1, D.n - 1)] - 1), np.nan)
        label = f"{SH_KO[pu[1]]} · {CN_KO[pu[2]]} · {HOW_KO[pu[3]]}"
        rows_.append({'절차': proc_id('BOTH', pu)[:-3], '설명': label, '계좌 독립 거래': int(ok.sum()), '오름 거래': int((ok & (dr > 0)).sum()), '내림 거래': int((ok & (dr < 0)).sum()),
                      '같은 날 두 방향이라 버린 날': int(len(both)), '방향 맞춘 적중': _pc(int(hit.sum()), int(ok.sum())), '오름 거래 적중': _pc(int(hit[dr > 0].sum()), int((ok & (dr > 0)).sum())),
                      '내림 거래 적중': _pc(int(hit[dr < 0].sum()), int((ok & (dr < 0)).sum())), '수익 합계': f'{100 * float(np.nansum(ret)):+.1f}%'})
        for dv, dn in ((1, 'up'), (-1, 'dn')):
            m = dr == dv; p = (dn,) + pu[1:]
            cands.append({'id': proc_id('BOTH', p), 'family': 'wf 절차(두 방향 함께)', 'direction': dv, 'hold': None, 'kind': 'wf', 'trades': _trades_df(D, s[m], r[m], EX),
                          'desc': f"[W3 두 방향 함께 · T1 원래 가족] 오름 절차와 내림 절차를 한 계좌에서 함께 쓸 때의 {'오름' if dv > 0 else '내림'} 거래 — {label}",
                          'root': 'T1 가족에서 해마다 고름(두 방향 함께)', 'params': {'shape': pu[1], 'count': pu[2], 'how': pu[3], 'both': True}})
    T_both = pd.DataFrame(rows_)
    md = ['#### (나) 고르는 절차의 다른 꼴 — T1 원래 가족' + (' [quick 시험]' if quick else ''), '',
          f'T1 규칙 {2 * G["nb"]:,}개(방향 포함, T1 에서 이미 센 것)를 다시 만들어 새 절차 {len(new) + 28}개를 돌림. 가짜 {nf}번은 다른 문턱·합의 비율 {len(new)}개에만.', '',
          '(1) 다른 문턱(75%·90%·윌슨 하한 60%·70%)·합의 비율(10%·30%) 절차의 다음 해 적중 — 실제 대 가짜', ''] + _md(T_fake.drop(columns=['절차', '가짜 횟수'])) + ['',
          '(2) 두 방향을 한 계좌에서 함께 쓴 성적(같은 날 두 방향이 함께 켜지면 그날은 버림)', ''] + _md(T_both) + ['']
    return {'cands': cands, 'fam': {'J': len(new) + 28}, 'm_wf': len(new) + 28, 'm_fixed_pool': 0, 'md': md,
            'tables': {'alt_wf_fake.csv': T_fake, 'alt_wf_by_year.csv': T_year, 'alt_both_account.csv': T_both}}


# ------------------------------------------------------------------ (다) 익절·손절 닿기 — 표만
def run_tp(D, quick):
    M, metas = conds_t1(D, quick, fam='K'); RU, RD, OK, EX, Y = outcome_rows(D, touch=True); rows_r = []; rows_w = []; n_rules = 0; n_proc = 0
    for j, k in enumerate(TOUCH):
        row = MAXH + j; G = build_G(D, M, [row], RU, RD, OK, EX, PROCS_TP); real = evaluate(G, None, detail=True); tn = G['cumN'][:, -1]; n_rules += 2 * G['nb']; y = Y[k]
        for di, (dn, ko) in enumerate((('up', '오름'), ('dn', '내림'))):
            tk = real['K'][dn][:, -1]; yy = y if di == 0 else 1 - y; live = np.isfinite(yy) & (D.td >= C.START)
            rows_r.append({'폭': f'±{int(k * 100)}%', '방향': ko, '시험한 규칙': G['nb'], '독립 35건 이상': int((tn >= 35).sum()), '35건·85% 이상': int(((tn >= 35) & (tk >= 0.85 * tn - 1e-9)).sum()),
                           '35건·80% 이상': int(((tn >= 35) & (tk >= 0.80 * tn - 1e-9)).sum()), '아무 날 적중(2010~, 같은 닿기 채점)': f'{100 * float(np.nanmean(yy[live])):.1f}%'})
            by = {int(a): float(np.nanmean(yy[(D.year == a) & np.isfinite(yy)])) for a in np.unique(D.year) if np.isfinite(yy[D.year == a]).any()}
            for p in [p for p in PROCS_TP if p[0] == dn]:
                pi = PROCS_TP.index(p); rn, rk = map(int, real['proc'][pi]); n_proc += 1; cnt = real['by'][p]
                den = sum(v[0] for v in cnt.values()); base = sum(v[0] * by.get(a, np.nan) for a, v in cnt.items()) / den if den else np.nan
                rows_w.append({'폭': f'±{int(k * 100)}%', '방향': ko, '절차': f'{SH_KO[p[1]]} · {CN_KO[p[2]]} · 하나라도', '다음 해 독립 거래': rn, '다음 해 적중': _pc(rk, rn),
                               '같은 해 아무 날(같은 닿기 채점)': (f'{100 * base:.1f}%' if rn >= 10 and np.isfinite(base) else '–'),
                               '차이': (f'{100 * (rk / rn - base):+.1f}%p' if rn >= 10 and np.isfinite(base) else '–')})
    T_r = pd.DataFrame(rows_r); T_w = pd.DataFrame(rows_w)
    md = ['#### (다) 익절·손절(±3%·±5% 먼저 닿기, 60거래일 안) — 표만, 등급 후보 아님' + (' [quick 시험]' if quick else ''), '',
          '익절·손절은 CRITERIA 2절의 매매(정한 날 종가 매도)가 아니라서 등급을 매기지 않는다. T1 의 조건 묶음을 그대로 쓰고 채점만 닿기로 바꿨다.', '',
          '(1) 전체 기간에 통과 숫자 꼴을 채운 규칙 수(결과를 보고 센 숫자)', ''] + _md(T_r) + ['', '(2) 해마다 고르는 절차(관찰 꼴 × 상위 1·5·20 × 하나라도)의 다음 해 성적', ''] + _md(T_w) + ['']
    return {'cands': [], 'fam': {'K': n_rules + n_proc}, 'm_wf': 0, 'm_fixed_pool': 0, 'md': md, 'tables': {'tp_rules.csv': T_r, 'tp_wf.csv': T_w}, 'n_rules_tp': n_rules}


# ------------------------------------------------------------------ 조각·merge
def n_parts(vol=False):
    return N_PARTS


def run_part(i, n, vol=False, quick=False):
    if n != N_PARTS or not (1 <= i <= N_PARTS): raise ValueError(f'조각 번호가 SPEC 과 다름: {i}/{n} (조각 수 {N_PARTS})')
    D = C.Data()
    if i == 1: M, me = conds_g1(D, quick); out = run_bundle(D, 'G1', M, me, [h - 1 for h in HOLDS], quick)
    elif i == 2: M, me = conds_g2(D, quick); out = run_bundle(D, 'G2', M, me, [h - 1 for h in HOLDS], quick)
    elif i == 3: M, me = conds_t1(D, quick, fam='I'); out = run_bundle(D, 'G3', M, me, [h - 1 for h in HOLDS_G3], quick)
    elif i == 4: out = run_alt(D, quick)
    else: out = run_tp(D, quick)
    if not quick:                                                   # 가짓수가 SPEC 과 같은지 확인(다르면 멈춘다)
        exp = {1: {k: EXPECT[k] for k in ('A', 'B', 'C', 'C2', 'D', 'E', 'F', 'G')}, 2: {'H': EXPECT['H']}, 3: {'I': EXPECT['I']}, 4: {'J': 100}, 5: {'K': EXPECT['K'] + 12}}[i]
        if out['fam'] != exp: raise RuntimeError(f'조각 {i} 의 가짓수가 SPEC 과 다름: {out["fam"]} != {exp}')
        if i <= 4 and not out['cands']: raise RuntimeError(f'조각 {i} 에서 후보가 하나도 안 나옴 — 멈춤')
    out.update({'part': i, 'quick': bool(quick)})
    return out


def merge(parts, vol=False, quick=False, out_dir=None):
    parts = list(parts or [])
    if quick: have = [p for p in parts if p is not None and p.get('quick')]
    else:
        miss = [i + 1 for i in range(N_PARTS) if i >= len(parts) or parts[i] is None or parts[i].get('quick')]
        if miss: raise RuntimeError(f'W3 조각 {miss} 이 없음(또는 quick 조각) — 합치지 않고 멈춤')
        have = parts[:N_PARTS]
    if not have: raise RuntimeError('W3 조각이 하나도 없음 — 멈춤')
    cands = [c for p in have for c in p['cands']]; fam = {}
    for p in have:
        for k, v in p['fam'].items(): fam[FAM_KO[k]] = int(v)
    n_tested = int(sum(fam.values())); m_wf = int(sum(p['m_wf'] for p in have)); m_fixed = int(sum(p['m_fixed_pool'] for p in have))
    ids = [c['id'] for c in cands]
    if len(set(ids)) != len(ids): raise RuntimeError('후보 id 가 겹침 — 멈춤')
    if not quick:
        if n_tested != 561232 or m_wf != 184 or m_fixed != 496800: raise RuntimeError(f'가짓수가 SPEC 과 다름: n_tested {n_tested} · m_wf {m_wf} · m_fixed {m_fixed}')
        if sum(c['kind'] == 'wf' for c in cands) != 184: raise RuntimeError('wf 후보 수가 SPEC(184)과 다름')
    if not cands or n_tested <= 0: raise RuntimeError('후보 0개 또는 가짓수 0 — 멈춤')
    od = out_dir or os.path.join(C.track_dir(TRACK), 'out'); os.makedirs(os.path.join(od, 'tables'), exist_ok=True); tabs = []
    for p in have:
        for k, df in p['tables'].items(): df.to_csv(os.path.join(od, 'tables', k), index=False, encoding='utf-8'); tabs.append(k)
    md = ['### W3 따로 낸 표 — T1 SPEC 에서 안 넣었던 것 전부' + (' [quick 시험 — 숫자는 뜻 없음]' if quick else ''), '',
          f'시험한 가짓수 {n_tested:,}개, 해마다 고르는 절차 {m_wf}개, fixed 후보를 고른 모집단 {m_fixed:,}개.',
          'fixed 후보(묶음·방향마다 적중 상위 33개)는 전체 기간 결과를 보고 고른 숫자다. 믿을 숫자는 해마다 고르는 절차의 다음 해 성적.', '']
    for p in sorted(have, key=lambda x: x['part']): md += p['md']
    open(os.path.join(od, 'summary.md'), 'w', encoding='utf-8').write('\n'.join(md) + '\n')
    notes = [f"미리 정한 가짓수 561,232개(G1 272,640 · G2 127,680 · G3 96,480 · 고르는 절차 다른 꼴 100 · 익절·손절 닿기 64,332) 중 {n_tested:,}개를 시험." + (' [quick 시험]' if quick else ''),
             '(나)의 절차 100개는 T1 원래 가족(128,640개, T1 원장에 이미 있음)에 고르는 법만 바꾼 것이라 가짓수에는 절차 수만 더했다.',
             '(다) 익절·손절 닿기는 CRITERIA 2절의 매매가 아니라 등급 후보로 넘기지 않고 표(tp_rules.csv·tp_wf.csv)로만 냈다.',
             '위클리 콜벽은 목 2019-09~·월 2023-07~, 차기 분기물은 분기월이 둘 살아 있는 날(약 절반)에만 조건이 켜진다.',
             'fixed 후보는 전체 기간 성적을 보고 고른 것(묶음·방향마다 적중 상위 33개)이라 다음 해 성적이 아니다.']
    meta = {'n_tested': n_tested, 'families': fam, 'm_fixed': m_fixed or n_tested, 'm_wf': m_wf, 'not_included': list(NOT_INCLUDED), 'parts_failed': [], 'notes': notes, 'tables': tabs}
    return cands, meta


if __name__ == '__main__':
    a = C.parse_part()
    if a['nparts']:
        print(n_parts())
    elif a['part']:
        i, n_ = a['part']; C.save_part(TRACK, i, n_, run_part(i, n_, quick=a['quick'])); print(f'조각 {i}/{n_} 저장')
    elif a['merge']:
        cands, meta = merge(C.load_parts(TRACK, n_parts()), quick=a['quick'])
        C.save_result(TRACK, cands, meta); print(f"후보 {len(cands)}개 · 시험 {meta['n_tested']:,}가지 · wf 절차 {meta['m_wf']}개")
