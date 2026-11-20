"""연구소(deriv/lab) 공통 — 자료 읽기, 만기 달력, 통계, 원장(시험 횟수·최종 구간 열람 횟수).

규칙(모든 에이전트 공통)
  - 개발 구간: 2015-01-01 ~ 2023-12-31. 탐색·학습·문턱 정하기는 이 구간 안에서만.
  - 잠금 구간: 2024-01-01 ~ 현재. A8(검증)만, 개발 구간 기준을 통과한 후보에 한해 연다. 열 때마다 원장에 횟수를 적고,
    통과 판정은 지금까지 연 횟수 전체로 보정한다(본페로니).
  - t일 지표는 t일 장 마감 뒤 알 수 있는 값. 매매는 t+1일 시가 진입(분봉 단계 전까지).
"""
import json
import os
import sys

import numpy as np
import pandas as pd
from scipy import stats

LAB = os.path.dirname(os.path.abspath(__file__))
DERIV = os.path.dirname(LAB)
REPO = os.path.dirname(DERIV)
DATA = os.path.join(DERIV, 'data')
sys.path.insert(0, DERIV)
sys.path.insert(0, os.path.join(DERIV, 'scan'))

DEV_END = pd.Timestamp('2023-12-31')
HOLD_START = pd.Timestamp('2024-01-01')
TRACK = os.environ.get('LAB_TRACK', '').strip().lower()   # '' = 갈래 A(기본), 'b' = 갈래 B (2026-11-20 두 갈래 동시 진행)
SFX = f'_{TRACK}' if TRACK else ''
STATE = os.path.join(LAB, 'state' + SFX)
os.makedirs(STATE, exist_ok=True)


def cv_mode():
    """a08_validate.cv_mode 와 같은 규칙(2026-11-21 KST 부터 'cross'). 뒤 구간 적합(fit_period='p2') 변형은 'cross' 일 때만 만든다 —
    11/20 까지 잠금 규칙에서는 잠금 구간으로 무엇도 정하지 않음."""
    m = (round_cfg().get('a08') or {}).get('cv_mode')
    if m in ('holdout', 'cross'): return m
    return 'cross' if pd.Timestamp.now(tz='Asia/Seoul').tz_localize(None).normalize() >= pd.Timestamp('2026-11-21') else 'holdout'


def fit_p2_enabled(agent_cfg):
    return 'p2' in (agent_cfg.get('fit_period') or []) and cv_mode() == 'cross'


def round_cfg():
    return json.load(open(os.path.join(LAB, f'round{SFX}.json'), encoding='utf-8'))


def out_dir(sub=None):
    r = round_cfg()['round']
    d = os.path.join(LAB, 'out' + SFX, f'round_{r:03d}', *( [sub] if sub else []))
    os.makedirs(d, exist_ok=True)
    return d


# ------------------------------------------------------------------ 가격
def k200_index():
    k = pd.read_csv(os.path.join(DATA, 'k200_long.csv')); k.columns = [c.lstrip('﻿') for c in k.columns]
    k['date'] = pd.to_datetime(k['날짜']); k = k.set_index('date').sort_index()
    out = pd.DataFrame({'open': k['시가'], 'high': k['고가'], 'low': k['저가'], 'close': k['종가']}).astype(float)
    return out[out.index >= '2007-01-01']


def prices():
    """K200(지수), K200F(연속 선물), KOSPI, ETF(069500, 있으면)."""
    import scan_data as SD
    import analyze as A
    P = {'K200': k200_index()}
    fp, night, roll = SD.k200f_price(); P['K200F'] = fp
    kp = A.load_price(); P['KOSPI'] = kp[['open', 'high', 'low', 'close']]
    ep = os.path.join(DATA, 'etf_069500.csv')
    if os.path.exists(ep):
        e = pd.read_csv(ep, parse_dates=['date']).set_index('date'); P['ETF'] = e[['open', 'high', 'low', 'close']]
    return P


def fetch_etf():
    try:
        import yfinance as yf
        d = yf.download('069500.KS', start='2014-01-01', progress=False, auto_adjust=False)
        if isinstance(d.columns, pd.MultiIndex): d.columns = d.columns.get_level_values(0)
        d = d.rename(columns=str.lower)[['open', 'high', 'low', 'close']]; d.index.name = 'date'
        d = d[d.index < pd.Timestamp.now().normalize()]
        d.to_csv(os.path.join(DATA, 'etf_069500.csv'))
    except Exception as e:
        print('ETF 받기 실패', e)


# ------------------------------------------------------------------ 옵션 행사가별
def chain(kind='m'):
    """kind m: 월물 가까운 2개(2015~), x: 월물 4개(있으면), wt/wm: 위클리."""
    f = {'m': 'opt_chain_daily', 'x': 'opt_chainx_daily', 'wt': 'opt_chainwt_daily', 'wm': 'opt_chainwm_daily'}[kind]
    p = os.path.join(DATA, f + '.csv.gz')
    if not os.path.exists(p): return None
    c = pd.read_csv(p)
    c['date'] = pd.to_datetime(c['날짜'])
    if 'ym' in c: c['ym'] = c['ym'].astype(str).str.slice(0, 6)
    return c.dropna(subset=['K'])


def chain_best():
    """월물 4개(x)는 수집이 끝나 가까운 2개(m)와 같은 기간을 덮을 때만 쓴다(수집 중 일부만 있는 x 로 지표가 짧아지는 것을 막음)."""
    m = chain('m'); x = chain('x')
    if x is not None and m is not None and len(x):
        if x['date'].min() <= m['date'].min() + pd.Timedelta(days=10) and x['date'].max() >= m['date'].max() - pd.Timedelta(days=10) \
                and x['date'].nunique() >= 0.97 * m['date'].nunique():
            return 'x', x
    return 'm', m


def second_thursday(y, m):
    d = pd.Timestamp(y, m, 1)
    return d + pd.Timedelta(days=(3 - d.weekday()) % 7 + 7)


def expiry_of_ym(ym, td):
    """월물 만기일(둘째 목요일, 휴장이면 앞 거래일)."""
    y, m = int(str(ym)[:4]), int(str(ym)[4:6])
    st = second_thursday(y, m)
    if st > td[-1]: return st          # 자료 끝보다 뒤 만기는 달력 날짜 그대로(휴장 조정은 확인 불가)
    i = td.searchsorted(st, side='right') - 1
    return td[i] if i >= 0 else st


def tdays_between(d, e, td):
    """d 다음 거래일부터 e 까지 거래일 수(자료 끝 뒤는 평일로 셈)."""
    n = int(((td > d) & (td <= e)).sum())
    if e > td[-1]: n += len(pd.bdate_range(td[-1] + pd.Timedelta(days=1), e))
    return n


# ------------------------------------------------------------------ 투자자별
def flows():
    """외국인·기관·개인: 코스피200 선물(조원), 옵션 콜·풋 순매수(조원, 프리미엄), 코스피 현물(조원)."""
    import expiry_study as ES
    import expiry_foreign as EF
    F = pd.DataFrame({
        'fut_for': ES.FUT['외국인'], 'fut_inst': ES.FUT['기관'], 'fut_ind': ES.FUT['개인'], 'fut_fi': ES.FUT['금융투자'],
        'call_for': ES.flows_detail('OPK2I', 'C')['외국인'], 'put_for': ES.flows_detail('OPK2I', 'P')['외국인'],
        'call_ind': ES.flows_detail('OPK2I', 'C')['개인'], 'put_ind': ES.flows_detail('OPK2I', 'P')['개인'],
    }) / 1e12
    F['cash_for'] = EF.CF.reindex(F.index.union(EF.CF.index)) / 1e12 if True else np.nan
    return F.sort_index()


# ------------------------------------------------------------------ 통계
def wilson(k, n, z=1.645):
    if n == 0: return (np.nan, np.nan)
    p = k / n; d = 1 + z * z / n; c = p + z * z / (2 * n); h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - h) / d, (c + h) / d)


def binom_p(k, n, p0=0.5):
    return stats.binomtest(int(k), int(n), p0, alternative='greater').pvalue if n else np.nan


def thin(dates, h, td):
    """겹치지 않는 신호만: 앞 신호의 보유 기간(h 거래일) 안에 든 신호는 버림."""
    pos = np.searchsorted(td.values, pd.DatetimeIndex(dates).values)
    keep, last = [], -10 ** 9
    for d, p in zip(dates, pos):
        if p - last >= h: keep.append(d); last = p
    return keep


# ------------------------------------------------------------------ 원장
def ledger():
    p = os.path.join(STATE, 'ledger.json')
    return json.load(open(p, encoding='utf-8')) if os.path.exists(p) else {'trials_total': 0, 'holdout_peeks': 0, 'rounds': []}


def save_ledger(L):
    json.dump(L, open(os.path.join(STATE, 'ledger.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


# ------------------------------------------------------------------ 후보 신호 형식(A3·A4·A5·A6·A7 → A8)
# 후보 하나 = dict(id, agent, desc, direction(+1 오름/−1 내림), trades=DataFrame[signal, exit], dev_note)
#   signal = 신호를 아는 날(그날 장 마감 뒤), 진입 = 다음 거래일 시가, 청산 = exit 날 종가.
#   잠금 구간(2024~)의 신호 날짜도 같은 규칙으로 만들어 넘기되, 그 구간 결과는 A8 만 계산한다.
REGIME_CODES = {'R0': '변동성 높음', 'R1': '변동성 낮음', 'R2': '상승 추세(60일선 위)', 'R3': '하락 추세(60일선 아래)',
                'R4': '변동성 상대 높음(직전 250일 상위 40%)', 'R5': '변동성 상대 낮음(직전 250일 하위 40%)',
                'R6': '5일 급락 뒤(−1.5σ 아래)', 'R7': '5일 급등 뒤(+1.5σ 위)',
                'R8': '60일 고점 대비 −5% 넘게 조정 중', 'R9': '60일 고점 1% 안(신고가 근처)',
                'R10': '조용한 상승장(60일선 위 + 변동성 상대 낮음)', 'R11': '조용한 신고가 근처(60일 고점 1% 안 + 변동성 상대 낮음)'}


def regime_states():
    """장세 상태(그날 종가까지 아는 값). 열 이름 = 코드(R0~R7, REGIME_CODES).
    R0·R1 변동성(20일 일간 등락 표준편차)의 개발 구간 중앙값 기준(라운드 2) — 2024~ 는 96% 가 '높음'이라 잠금 구간에서 낮음 표본이 거의 없음.
    R4·R5 같은 변동성을 직전 250거래일 안 백분위로(고정 문턱 없음, 라운드 3). R2·R3 종가 vs 60일 이평.
    R6·R7 직전 5일 등락이 직전 750일 5일 등락 표준편차의 ±1.5배 밖(큰 변동 뒤, 라운드 3). 2026-11-20 갈래 B, round 설정 'regime' 이 있을 때만 쓰임."""
    k = k200_index(); c = k['close']
    rv = c.pct_change().rolling(20).std()
    med = rv[(rv.index >= '2010-01-01') & (rv.index <= DEV_END)].median()
    pr = rv.rolling(250, min_periods=120).apply(lambda w: (w[:-1] < w[-1]).mean() if len(w) > 1 else np.nan, raw=True)
    ma = c.rolling(60).mean()
    r5 = c.pct_change(5); s5 = r5.rolling(750, min_periods=250).std()
    S = pd.DataFrame(index=k.index)
    S['R0'] = (rv > med) & rv.notna(); S['R1'] = (rv <= med) & rv.notna()
    S['R2'] = (c > ma) & ma.notna(); S['R3'] = (c <= ma) & ma.notna()
    S['R4'] = (pr >= 0.6) & pr.notna(); S['R5'] = (pr <= 0.4) & pr.notna()
    S['R6'] = (r5 < -1.5 * s5) & s5.notna(); S['R7'] = (r5 > 1.5 * s5) & s5.notna()
    hi = c.rolling(60).max(); dd = c / hi - 1   # R8·R9 (라운드 4): 60일 고점과의 거리
    S['R8'] = (dd <= -0.05) & hi.notna(); S['R9'] = (dd >= -0.01) & hi.notna()
    S['R10'] = S['R2'] & S['R5']; S['R11'] = S['R9'] & S['R5']   # 라운드 6: 벽 신호가 장세보다 더 아는 장세(라운드 4 개발 구간 기준선 표)끼리 겹침
    return S


def regime_features():
    """장세 연속 지표(그날 종가까지 아는 값) — A6 조건·A7 특징으로 쓰는 용도(갈래 B 라운드 4, round 설정 a06.regime_feats 일 때만).
    rg_volpct 20일 변동성의 직전 250일 백분위, rg_r5z·rg_r20z 5·20일 등락 ÷ 직전 750일 같은 등락 표준편차, rg_ma60 60일선 이격, rg_dd60 60일 고점 대비."""
    k = k200_index(); c = k['close']
    rv = c.pct_change().rolling(20).std()
    F = pd.DataFrame(index=k.index)
    F['rg_volpct'] = rv.rolling(250, min_periods=120).apply(lambda w: (w[:-1] < w[-1]).mean() if len(w) > 1 else np.nan, raw=True)
    for n in (5, 20):
        r = c.pct_change(n); F[f'rg_r{n}z'] = r / r.rolling(750, min_periods=250).std()
    F['rg_ma60'] = c / c.rolling(60).mean() - 1
    F['rg_dd60'] = c / c.rolling(60).max() - 1
    return F


def regime_variants(cands):
    """후보마다 장세 조건을 붙인 변형(신호 날 장세가 맞을 때만). 방향은 원 후보(개발 구간에서 정함) 그대로.
    많아지지 않게: 개발 구간 신호 40개 이상인 후보 중 개발 구간 단순 적중(지수, 겹침 무시) 상위 max_base 개만."""
    rc = round_cfg().get('regime') or {}
    if not rc or not cands: return []
    S = regime_states(); S = S[[c for c in rc.get('states', ['R0', 'R1', 'R2', 'R3']) if c in S]]; k = k200_index(); td = k.index
    min_sig = rc.get('min_dev_signals', 40); max_base = rc.get('max_base', 250)
    scored = []
    for c in cands:
        if c.get('regime') or 'trades_dev' in c: continue
        t = c['trades']; t = t[pd.to_datetime(t['exit']) <= DEV_END]
        if len(t) < min_sig: continue
        r = trade_returns(t.assign(signal=pd.to_datetime(t['signal']), exit=pd.to_datetime(t['exit'])), k)
        r = r[~np.isnan(r)]
        if len(r) < min_sig: continue
        scored.append((float((c['direction'] * r > 0).mean()), c))
    scored.sort(key=lambda x: -x[0])
    out, edge = [], []
    for _, c in scored[:max_base]:
        t = c['trades'].copy(); sd = pd.to_datetime(t['signal'])
        for code in S.columns:
            nm = REGIME_CODES[code]
            st = S[code].reindex(sd).fillna(False).values
            tt = t[st]
            if len(tt[pd.to_datetime(tt['exit']) <= DEV_END]) < rc.get('min_dev_after', 15): continue
            try:   # 원인 분해(라운드 4): 장세 변형의 적중이 '장세 자체'의 기본 확률보다 얼마나 높은가(개발 구간, 겹침 무시 단순 비율)
                edge.append(_regime_edge(c, tt, code, S, k))
            except Exception as e:
                print('장세 기준선 계산 실패', c['id'], code, e)
            v = {kk: vv for kk, vv in c.items() if kk != 'trades'}
            v.update({'id': f"{c['id']}__{code}", 'desc': f"[{nm}] {c['desc']}", 'family': f"{c.get('family')}_regime",
                      'regime': nm, 'trades': tt.reset_index(drop=True)})
            out.append(v)
    print('장세 조건 변형', len(out), '(원 후보', len(scored), '중 상위', min(len(scored), max_base), ')', flush=True)
    if edge: _EDGE_ROWS.extend(edge)
    return out


_EDGE_ROWS = []


def _fwd_up(k, h):
    """t일 신호 → t+1 시가 진입, t+h 종가 청산 수익 부호(지수)."""
    r = k['close'].shift(-h) / k['open'].shift(-1) - 1
    return r.where(r != 0)


def _regime_edge(c, tt, code, S, k):
    td = k.index
    t = tt.assign(signal=pd.to_datetime(tt['signal']), exit=pd.to_datetime(tt['exit']))
    t = t[t['exit'] <= DEV_END]
    hs = [max(1, int(td.searchsorted(e) - td.searchsorted(s))) for s, e in zip(t['signal'], t['exit']) if e in td]
    h = int(np.median(hs)) if hs else 1
    r = trade_returns(t, k); r = r[~np.isnan(r)]
    fr = _fwd_up(k, h); dev = (td >= '2015-01-01') & (td <= DEV_END - pd.Timedelta(days=int(h * 1.5)))
    st = S[code].reindex(td).fillna(False).values
    g = fr[dev & st].dropna(); u = fr[dev].dropna()
    d = c['direction']
    rb = float((d * g > 0).mean()) if len(g) else np.nan; ub = float((d * u > 0).mean()) if len(u) else np.nan
    hit = float((d * r > 0).mean()) if len(r) else np.nan
    return {'id': f"{c['id']}__{code}", 'base_id': c['id'], 'regime': code, 'h': h, 'direction': d, 'n_dev_signals': len(r),
            'hit_simple': hit, 'regime_base': rb, 'uncond_base': ub, 'edge_vs_regime': hit - rb, 'regime_vs_uncond': rb - ub}


def regime_baselines():
    """장세만으로 낸 신호(장세 상태인 날마다, 독립 거래는 A8 이 셈) — 벽 신호가 장세보다 더 아는지 비교용 후보(갈래 B 라운드 4, regime.baseline)."""
    rc = round_cfg().get('regime') or {}
    S = regime_states(); k = k200_index(); td = k.index
    out = []
    for code in [c for c in rc.get('states', []) if c in S]:
        sd = td[S[code].reindex(td).fillna(False).values & (td >= '2015-01-01')]
        for h in rc.get('baseline_h', [1, 3, 5, 10, 20]):
            ex = [exit_after(td, s_, h) for s_ in sd]
            tr = pd.DataFrame({'signal': sd, 'exit': ex}).dropna()
            for d in (1, -1):
                out.append({'id': f'RG_{code}_m{h}_{"up" if d > 0 else "dn"}', 'agent': 'RG', 'family': 'regime_only',
                            'desc': f'[장세만] {REGIME_CODES[code]} → {h}일 {"상승" if d > 0 else "하락"}', 'direction': d,
                            'regime': REGIME_CODES[code], 'trades': tr.copy()})
    return out


def mirror_p2_cfg():
    """뒤 구간 방향 거울(갈래 B 라운드 7, round 설정 'mirror_p2' 가 있고 교차 모드(2026-11-21~)일 때만).
    A3·A3c·A4·A5 후보는 방향(상승/하락)과 장세 변형 고르기(상위 max_base)를 앞 구간(개발)에서 정하므로, 교차 검증의 뒤→앞(뒤 구간 선별 → 앞 구간 확인)
    방향에서 앞 구간 확인이 표본 안이 된다. 거울 후보는 같은 신호 날짜에 방향을 뒤 구간(2024~)만으로 정하고(fit_period='p2', A8 이 앞→뒤 선별에서 뺌),
    장세 변형도 뒤 구간 단순 적중으로 골라 뒤→앞 방향을 공정하게 만든다. 11/20 까지(잠금 규칙)는 꺼짐 — 잠금 구간으로 무엇도 정하지 않음."""
    mc = round_cfg().get('mirror_p2')
    if not mc or cv_mode() != 'cross': return None
    return mc if isinstance(mc, dict) else {}


def _flip_desc(desc):
    i, j = desc.rfind('상승'), desc.rfind('하락')
    if i < 0 and j < 0: return desc
    if i > j: return desc[:i] + '하락' + desc[i + 2:]
    return desc[:j] + '상승' + desc[j + 2:]


def _p2_simple(t, k):
    """t(trades)에서 뒤 구간(2024~) 신호만 → 지수 단순 수익(겹침 무시, 방향 정하기용)."""
    t = t.assign(signal=pd.to_datetime(t['signal']), exit=pd.to_datetime(t['exit']))
    t = t[t['signal'] >= HOLD_START]
    r = trade_returns(t, k) if len(t) else np.array([])
    return r[~np.isnan(r)] if len(r) else r


def p2_mirror(cands, mc):
    """앞 구간에서 방향을 정한 원 후보(장세 변형·A6/A7 제외) → 뒤 구간 방향 거울 후보 '{id}__P2'."""
    k = k200_index(); min_n = mc.get('min_p2_signals', 12); out = []
    for c in cands:
        if c.get('regime') or c.get('fit_period') or 'trades_dev' in c: continue
        r = _p2_simple(c['trades'], k)
        if len(r) < min_n: continue
        d = 1 if (r > 0).mean() >= 0.5 else -1
        # 갈래 B 라운드 12(mirror_p2.only_flip, 없으면 예전대로): 뒤 구간 방향이 원 후보와 같으면 거울은 원 후보와 거래가 똑같아
        #   A8 뒤→앞 선별 수(확인 p 의 나눗수)만 두 배로 늘림(라운드 11: 뒤 선별 70 중 같은 쌍 다수) — 방향이 뒤집힐 때만 거울을 만든다.
        if mc.get('only_flip') and d == c['direction']: continue
        v = {kk: vv for kk, vv in c.items() if kk != 'trades'}
        v.update({'id': f"{c['id']}__P2", 'direction': d, 'fit_period': 'p2', 'base_id': c['id'],
                  'desc': '[뒤 구간 방향] ' + (c['desc'] if d == c['direction'] else _flip_desc(c['desc'])), 'trades': c['trades'].copy()})
        out.append(v)
    return out


def regime_variants_p2(cands, mc):
    """장세 변형의 뒤 구간판: 원 후보 고르기(상위 max_base)·방향을 뒤 구간 단순 적중으로 — '{id}__{장세}__P2'."""
    rc = round_cfg().get('regime') or {}
    if not rc or not cands: return []
    S = regime_states(); S = S[[c for c in rc.get('states', []) if c in S]]; k = k200_index()
    min_sig = mc.get('min_p2_signals_regime', 20); min_after = mc.get('min_p2_after', 8); max_base = mc.get('max_base', rc.get('max_base', 120))
    scored = []
    for c in cands:
        if c.get('regime') or c.get('fit_period') or 'trades_dev' in c: continue
        r = _p2_simple(c['trades'], k)
        if len(r) < min_sig: continue
        up = float((r > 0).mean()); scored.append((max(up, 1 - up), c))
    scored.sort(key=lambda x: -x[0]); out = []
    for _, c in scored[:max_base]:
        t = c['trades'].copy(); sd = pd.to_datetime(t['signal'])
        for code in S.columns:
            tt = t[S[code].reindex(sd).fillna(False).values].reset_index(drop=True)
            r = _p2_simple(tt, k)
            if len(r) < min_after: continue
            d = 1 if (r > 0).mean() >= 0.5 else -1
            v = {kk: vv for kk, vv in c.items() if kk != 'trades'}
            v.update({'id': f"{c['id']}__{code}__P2", 'base_id': c['id'], 'direction': d, 'fit_period': 'p2', 'regime': REGIME_CODES[code],
                      'family': f"{c.get('family')}_regime", 'trades': tt,
                      'desc': f"[뒤 구간 방향][{REGIME_CODES[code]}] " + (c['desc'] if d == c['direction'] else _flip_desc(c['desc']))})
            out.append(v)
    return out


def barrier_exits(px, W, k=1.0, vol_win=60):
    """큰 변동 대상(2026-11-20 갈래 B): t일 신호 → t+1 시가 기준, W 거래일 안에 종가가 +kσ√W 를 먼저 넘으면 1, −kσ√W 를 먼저 넘으면 0,
    둘 다 아니면 NaN. σ = 직전 vol_win 일 일간 종가 등락 표준편차(t일에 아는 값). exit = 처음 넘은 날(없으면 W 번째 날).
    반환 (y_up Series, exit Series)."""
    c, o = px['close'].values, px['open'].values; td = px.index; n = len(td)
    sig = px['close'].pct_change().rolling(vol_win).std().values
    y = np.full(n, np.nan); ex = np.full(n, np.datetime64('NaT'), dtype='datetime64[ns]')
    for i in range(n - 1):
        if not np.isfinite(sig[i]): continue
        o1 = o[i + 1]
        if not np.isfinite(o1) or o1 <= 0: continue
        b = k * sig[i] * np.sqrt(W); end = min(n - 1, i + W)
        if i + W > n - 1: continue
        hit = None
        for j in range(i + 1, end + 1):
            r = c[j] / o1 - 1
            if r >= b: hit = (1.0, j); break
            if r <= -b: hit = (0.0, j); break
        if hit: y[i] = hit[0]; ex[i] = td.values[hit[1]]
        else: ex[i] = td.values[end]
    return pd.Series(y, index=td), pd.Series(ex, index=td)


def save_candidates(agent, cands):
    import pickle
    ex = round_cfg().get('exclude_ids') or []   # 이미 잠금 구간에서 탈락한 후보(+그 장세 변형)는 다시 열지 않게 뺌 — 열람 낭비 방지
    if ex: cands = [c for c in cands if not any(c['id'] == e or c['id'].startswith(e + '__R') for e in ex)]
    if round_cfg().get('regime') and agent in (round_cfg().get('regime') or {}).get('agents', ['a03', 'a03c', 'a04', 'a05']):
        try:
            cands = cands + regime_variants(cands)
        except Exception as e:   # 장세 변형 실패가 원 후보 저장을 막지 않게
            print('장세 조건 변형 실패', e)
        if ex: cands = [c for c in cands if not any(c['id'] == e or c['id'].startswith(e + '__R') for e in ex)]
        if _EDGE_ROWS:
            pd.DataFrame(_EDGE_ROWS).round(4).to_csv(os.path.join(out_dir(agent), 'regime_edge_dev.csv'), index=False, encoding='utf-8')
    mc = mirror_p2_cfg()
    if mc is not None and agent in mc.get('agents', ['a03', 'a03c', 'a04', 'a05']):
        try:
            base = [c for c in cands if not c.get('regime')]
            m1 = p2_mirror(base, mc); m2 = regime_variants_p2(base, mc) if round_cfg().get('regime') else []
            cands = cands + m1 + m2
            print('뒤 구간 방향 거울', len(m1), '· 뒤 구간 장세 변형', len(m2), flush=True)
        except Exception as e:   # 거울 실패가 원 후보 저장을 막지 않게
            print('뒤 구간 방향 거울 실패', e)
    rc = round_cfg().get('regime') or {}
    if rc.get('baseline') and agent == rc.get('baseline_agent', 'a05'):
        try:
            cands = cands + regime_baselines()
        except Exception as e:
            print('장세만 후보 실패', e)
    d = out_dir(agent)
    pickle.dump(cands, open(os.path.join(d, 'candidates.pkl'), 'wb'))
    pd.DataFrame([{k: v for k, v in c.items() if k != 'trades'} | {'n_signals': len(c['trades'])} for c in cands]).to_csv(
        os.path.join(d, 'candidates.csv'), index=False, encoding='utf-8')


def trade_returns(trades, px):
    """trades[signal, exit] → 다음 날 시가 진입, exit 날 종가 청산 수익(%). 자료 밖이면 빈칸."""
    td = px.index
    out = []
    for s, e in zip(trades['signal'], trades['exit']):
        i = td.searchsorted(s, side='right')
        if i >= len(td) or e not in td or td[i] > e: out.append(np.nan); continue
        out.append((px['close'].loc[e] / px['open'].iloc[i] - 1) * 100)
    return np.array(out)


def exit_after(td, s, h):
    i = td.searchsorted(s, side='right') + h - 1
    return td[i] if i < len(td) else pd.NaT
