# -*- coding: utf-8 -*-
"""T2 상태 → 방아쇠 (SPEC.md 그대로). 오름 방향만.
상태 = 바닥 전 공통점 지표를 해마다 그 해 이전 자료로 다시 골라 만든 점수(deriv/turn/turn_signal.py build() 와 같은 방식, 코스피 종가 기준).
신호 = 상태 켜짐 구간(최근 5일/10일 안에 점수 ≥ 문턱) 안에서 방아쇠 8가지 가운데 하나가 나온 날. 견줄 것: 상태만 / 방아쇠만.
명령: python run.py --nparts | --part i/n | --merge  (+ --quick)
T4 가 부르는 함수: n_parts(vol) · run_part(i, n, vol, quick) · merge(parts, vol, quick) → (cands, meta). merge 는 저장하지 않는다.
  meta 에는 표가 글로 들어 있다: meta['summary_md'](summary.md 내용), meta['tables_csv']{파일 이름: csv 글}. 저장은 부르는 쪽이 한다(이 파일의 main 은 t2/out 에 쓴다)."""
import io
import os
import sys
import warnings

import numpy as np
import pandas as pd
from joblib import Parallel, delayed

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE))
import sa_common as C   # noqa: E402

TRACK = 't2'
MATCH = 'PK_등락_5d'; NN = 200; MAXC = 8; HI, LO = 80, 20; WIN = 3; CATCH = 0.40; MOVE = 0.05; MIN_EV = 5
VOLK = 1.0; SQ20 = float(np.sqrt(20)); SIGN = 60
WINS = (5, 10); HOLDS = (3, 5, 10); QUICK_YEARS = (2018, 2022, 2026)
TRIG = {1: '첫 반등일(오른 날이고 전날은 내림)', 2: '전일 고가 돌파(종가 > 전날 고가)', 3: '이틀 연속 상승 마감', 4: '장대 양봉(하루 +1.5% 이상)',
        5: '5일선 회복(종가가 5일 평균 아래에서 위로)', 6: '반대매매 정점 통과(자리 80 이상 뒤 직전 5일 최고보다 30% 이상 줄어든 첫 날)',
        7: '외국인 매도 둔화(현물 5일 합 자리 20 이하에서 당일 순매수 전환)', 8: '변동성 꺾임(VKOSPI 자리 80 이상에서 하루 5% 이상 하락)'}
TRIG_V4 = '장대 양봉(하루 등락이 직전 60일 표준편차의 1.0배 이상)'
SHORT = {0: '방아쇠 없음', 1: '첫 반등일', 2: '전일 고가 돌파', 3: '이틀 연속 상승', 4: '장대 양봉', 5: '5일선 회복', 6: '반대매매 정점 통과', 7: '외국인 매도 둔화', 8: '변동성 꺾임'}
SCORES = [('h3', 3), ('h5', 5), ('h10', 10), ('touch', None)]
FAMILIES = {'state_trigger': len(WINS) * 8 * 4, 'state_only': len(WINS) * 4, 'trigger_only': 8 * 4}
NOT_INCLUDED = ['방아쇠 두 개 이상이 겹칠 때만 신호(예: 첫 반등일 + 외국인 순매수 전환)',
                '상태 구간 3일·20일, 점수 문턱을 저점의 20%·60% 잡기로 바꾼 것',
                '상태 구간 안의 첫 방아쇠만 쓰기, 방아쇠 뒤 하루 늦춤',
                '지수·가격 묶음 지표를 뺀 상태(수급·옵션·해외만), 8% 전환점 기준 상태',
                '방아쇠 T6·T8 의 크기 문턱(30%·5%)과 자리 문턱(80/20)의 다른 값, T6 대기 기한',
                '내림 방향(꼭지 상태 → 하락 방아쇠)']


# ------------------------------------------------------------------ 공통 조각
def zigzag(c, th):
    """종가 c 에서 th 이상 되돌린 고점·저점 [(위치, 'L'/'H')]. th 가 배열이면 그날(i)의 문턱 th[i] 를 쓴다(변동폭 맞춤).
    th 가 숫자 하나면 deriv/turn/turn_probe.zigzag 와 같다. 마지막 진행 중인 것은 넣지 않는다(확정된 전환만)."""
    c = np.asarray(c, float); th = np.broadcast_to(np.asarray(th, float), c.shape)
    piv = []; ok = np.where(np.isfinite(c) & np.isfinite(th))[0]
    if not len(ok): return piv
    lo = hi = int(ok[0]); mode = None
    for i in ok[1:]:
        i = int(i); t = th[i]
        if mode is None:
            if c[i] > c[hi]: hi = i
            if c[i] < c[lo]: lo = i
            if c[i] >= c[lo] * (1 + t) and lo < i: piv.append((lo, 'L')); mode = 'up'; hi = i
            elif c[i] <= c[hi] * (1 - t) and hi < i: piv.append((hi, 'H')); mode = 'dn'; lo = i
        elif mode == 'up':
            if c[i] > c[hi]: hi = i
            elif c[i] <= c[hi] * (1 - t): piv.append((hi, 'H')); mode = 'dn'; lo = i
        else:
            if c[i] < c[lo]: lo = i
            elif c[i] >= c[lo] * (1 + t): piv.append((lo, 'L')); mode = 'up'; hi = i
    return piv


def sigma_prev(c):
    """σ[t] = r[t−60..t−1] 의 표준편차(당일 제외, 60일이 다 있어야 값)."""
    return pd.Series(c).pct_change().rolling(SIGN).std().shift(1).values


def move_th(D, vol):
    """전환 크기: 5% 고정 또는 날마다 σ[t]×√20×1.0."""
    return (VOLK * SQ20 * sigma_prev(D.c)) if vol else MOVE


def ranks(X):
    """자리 = 그날까지의 지난 250거래일(최소 120일) 가운데 순위(0~100)."""
    return X.rolling(250, min_periods=120).rank(pct=True).values * 100


# ------------------------------------------------------------------ 상태(해마다 고르기)
def build_state(c, th, R, mj, lo_, cut, seed, nn):
    """cut 앞 자료만으로 상태 지표(최대 8개)와 점수 문턱을 정한다. 반환 dict(comps, k, E, score(전체 날, int8), table)."""
    n = len(c); rs = np.random.default_rng(seed)
    thc = th if np.isscalar(th) else th[:cut]
    ev = np.array([p for p, t in zigzag(c[:cut], thc) if t == 'L' and p >= lo_], dtype=int); E = len(ev); span = cut - lo_
    empty = dict(comps=[], k=2, E=E, score=np.zeros(n, np.int8), table=[])
    if E < MIN_EV or span < 400: return empty
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
        cand = [j for j in np.argsort(-np.abs(np.nan_to_num(zm))) if np.isfinite(z[j]) and np.isfinite(zm[j]) and abs(z[j]) >= 3 and abs(zm[j]) >= 2.5 and cover[j] >= 0.7 and recent[j] >= 0.9
                and ((real[j] >= 55 and real[j] > ctrl[j]) or (real[j] <= 45 and real[j] < ctrl[j]))]
        Rt = pd.DataFrame(R[lo_:cut]); comps = []
        for j in cand:
            if any(abs(Rt[j].corr(Rt[q[0]])) > 0.8 for q in comps): continue
            comps.append((int(j), 'hi' if real[j] >= 55 else 'lo', round(float(real[j]), 1), round(float(ctrl[j]), 1), round(float(z[j]), 1), round(float(zm[j]), 1)))
            if len(comps) >= MAXC: break
        score = np.zeros(n, np.int8)
        for j, side, *_ in comps: score += np.nan_to_num((R[:, j] >= HI) if side == 'hi' else (R[:, j] <= LO)).astype(np.int8)
    k = 2; table = []
    for kk in range(len(comps), 1, -1):
        on = np.zeros(n, bool); on[lo_:cut] = score[lo_:cut] >= kk
        caught = int(sum(on[max(p - WIN, 0):p + 1].any() for p in ev)); table.append([kk, int(on.sum()), caught, E])
    for kk, _, caught, _ in table:
        if E and caught / E >= CATCH: k = kk; break
    return dict(comps=comps, k=int(k), E=E, score=score, table=table)


def _one_year(Y, c, th, R, mj, lo_, cut, nn, cols):
    m = build_state(c, th, R, mj, lo_, cut, C.SEED + Y, nn)
    m['comps'] = [(cols[j], side, a, b, z, zm) for j, side, a, b, z, zm in m['comps']]
    return Y, m


# ------------------------------------------------------------------ 방아쇠
def triggers(D, vol):
    """방아쇠 8가지(전체 기간 같은 정의). 반환 {번호: bool 배열}. 모두 t일 장 마감 뒤 아는 값."""
    n = D.n; c = D.c; h = D.h; X = D.X; T = {}
    with np.errstate(invalid='ignore'):
        c1 = np.r_[np.nan, c[:-1]]; c2 = np.r_[np.nan, np.nan, c[:-2]]; h1 = np.r_[np.nan, h[:-1]]; r = c / c1 - 1
        T[1] = (c > c1) & (c1 < c2)
        T[2] = c > h1
        T[3] = (c > c1) & (c1 > c2)
        T[4] = (r >= VOLK * sigma_prev(c)) if vol else (r >= 0.015)
        ma = pd.Series(c).rolling(5).mean().values; ma1 = np.r_[np.nan, ma[:-1]]
        T[5] = (c > ma) & (c1 <= ma1)
        # T6 반대매매 정점 통과
        x = X['C_반대매매_억']; rk = (x.rolling(250, min_periods=120).rank(pct=True) * 100).values; mx = x.rolling(5, min_periods=3).max().shift(1).values; x = x.values
        t6 = np.zeros(n, bool); armed = False
        for t in range(n):
            if not np.isfinite(x[t]): continue
            if armed and np.isfinite(mx[t]) and x[t] <= 0.7 * mx[t]: t6[t] = True; armed = False
            elif np.isfinite(rk[t]) and rk[t] >= HI: armed = True
        T[6] = t6
        # T7 외국인 매도 둔화
        s5 = (X['S_외국인현물_5d'].rolling(250, min_periods=120).rank(pct=True) * 100).shift(1).values; s1 = X['S_외국인현물_1d'].values; s1p = np.r_[np.nan, s1[:-1]]
        T[7] = (s5 <= LO) & (s1 > 0) & (s1p <= 0)
        # T8 변동성 꺾임
        v = X['V1_VKOSPI'].where(X['V1_VKOSPI'].notna(), X['M_VKOSPI']); vr = (v.rolling(250, min_periods=120).rank(pct=True) * 100).shift(1).values; v = v.values; v1 = np.r_[np.nan, v[:-1]]
        T[8] = (vr >= HI) & (v / v1 - 1 <= -0.05)
    return {k: np.nan_to_num(np.asarray(a, float)).astype(bool) for k, a in T.items()}


def first_touch_var(D, kk, max_days=60):
    """C.first_touch 를 본뜬 변동폭 맞춤판: 매수일 e = i+1 의 시가 기준 ±kk[e] 에 먼저 닿는 쪽(위 = 1, 아래 = 0, 같은 날 둘 다 = 0, 끝까지 없으면 nan)."""
    n = D.n; y = np.full(n, np.nan); ex = np.full(n, -1, dtype=int)
    for i in range(n - 1):
        e = i + 1; k = kk[e]
        if not np.isfinite(k) or k <= 0: continue
        o1 = D.o[e]; up = o1 * (1 + k); dn = o1 * (1 - k); end = min(n - 1, e + max_days - 1)
        for j in range(e, end + 1):
            if D.l[j] <= dn: y[i] = 0.0; ex[i] = j; break
            if D.h[j] >= up: y[i] = 1.0; ex[i] = j; break
    return y, ex


# ------------------------------------------------------------------ 약속된 함수
def n_parts(vol=False):
    return 1


def run_part(i, n, vol=False, quick=False):
    """조각 i/n: 해마다(그 해 이전 자료로) 상태 지표·점수 문턱 고르기. 해 목록을 n 으로 나눠 맡는다."""
    D = C.Data(); years = [y for y in C.WF_YEARS if (not quick or y in QUICK_YEARS)][i - 1::n]
    R = ranks(D.X); cols = list(D.X.columns); mj = cols.index(MATCH); lo_ = int(D.td.searchsorted(C.START)) + 10; th = move_th(D, vol); nn = 40 if quick else NN
    jobs = [(Y, int(np.where(D.year == Y)[0][0])) for Y in years]
    res = Parallel(n_jobs=min(4, os.cpu_count() or 1))(delayed(_one_year)(Y, D.c, th, R, mj, lo_, cut, nn, cols) for Y, cut in jobs)
    return dict(vol=bool(vol), quick=bool(quick), years={int(Y): m for Y, m in res})


def _trades(D, pos, key, h, touch):
    pos = np.asarray(pos, dtype=int)
    if h is not None: return D.trades_from_pos(pos, h)
    y, ex = touch; pos = pos[np.isfinite(y[pos])]
    return pd.DataFrame({'signal': D.td[pos], 'exit': D.td[ex[pos]], 'hit': y[pos].astype(int)})


def _base(D, t, h, touch):
    """같은 해 아무 날 적중(해 구성 맞춤). 보유일 없는 채점은 아무 날의 '+쪽 먼저 닿기' 비율."""
    if not len(t): return None
    if h is not None: return C.base_for(D, t, h, 1)
    y = touch[0]; ys = pd.DatetimeIndex(t['signal']).year.values; num = den = 0.0
    for a in np.unique(ys):
        m = (D.year == a) & np.isfinite(y)
        if m.any(): num += (ys == a).sum() * y[m].mean(); den += (ys == a).sum()
    return float(num / den) if den else None


def merge(parts, vol=False, quick=False):
    D = C.Data(); n = D.n; failed = [i + 1 for i, p in enumerate(parts) if p is None]; ST = {}
    for p in parts:
        if p is not None: ST.update(p['years'])
    years_all = [y for y in C.WF_YEARS if (not quick or y in QUICK_YEARS)]; years = [y for y in years_all if y in ST]
    T = triggers(D, vol); th = move_th(D, vol)
    touch = first_touch_var(D, VOLK * SQ20 * sigma_prev(D.c)) if vol else C.first_touch(D, MOVE)
    pre = 'V_' if vol else ''; tag = '[변동폭 맞춤] ' if vol else ''
    tname = dict(TRIG); tname[4] = TRIG_V4 if vol else TRIG[4]
    sc_txt = {'h3': '다음 날 시가 매수 → 3일째 종가 매도', 'h5': '다음 날 시가 매수 → 5일째 종가 매도', 'h10': '다음 날 시가 매수 → 10일째 종가 매도',
              'touch': ('다음 날 시가 기준 +1.0σ√20 에 −쪽보다 먼저 닿으면 맞음(보유일 없음)' if vol else '다음 날 시가 기준 +5% 에 −5% 보다 먼저 닿으면 맞음(보유일 없음)')}
    # 상태 켜짐 구간(해 Y 규칙을 Y 년의 날에)
    ON = {w: np.zeros(n, bool) for w in WINS}; on0 = np.zeros(n, bool)
    for Y in years:
        m = ST[Y]; on = (m['score'] >= m['k']) & (len(m['comps']) >= 2); iy = D.year == Y; on0[iy] = on[iy]
        for w in WINS: ON[w][iy] = (pd.Series(on.astype(float)).rolling(w, min_periods=1).max().values > 0)[iy]
    ywf = np.isin(D.year, years_all)
    # 신호 위치
    POS = {}
    for w in WINS:
        POS[(f'S{w}', 0)] = np.where(ON[w])[0]
        for j in range(1, 9): POS[(f'S{w}', j)] = np.where(ON[w] & T[j])[0]
    for j in range(1, 9): POS[('TO', j)] = np.where(ywf & T[j])[0]
    cands = []; rows2 = []
    for (arm, j), pos in POS.items():
        fam = 'trigger_only' if arm == 'TO' else ('state_only' if j == 0 else 'state_trigger')
        if arm != 'TO' and not years: continue                      # 조각 실패로 상태가 없으면 상태 절차는 넘기지 않는다
        st_txt = '' if arm == 'TO' else f'바닥 전 상태(해마다 그 전 자료로 고른 지표 점수 ≥ 문턱)가 최근 {arm[1:]}거래일 안에 켜짐'
        tr_txt = '' if j == 0 else tname[j]
        who = (f'{st_txt} + {tr_txt}' if (st_txt and tr_txt) else (f'{st_txt}, 방아쇠 없이 켜진 날 전부' if st_txt else f'상태 없이 방아쇠만: {tr_txt}'))
        for key, h in SCORES:
            tr = _trades(D, pos, key, h, touch)
            cands.append(dict(id=f'{pre}{arm}_T{j}_{key}', family=fam, desc=f'{tag}{who} → {sc_txt[key]}', direction=1, hold=h, kind='wf', trades=tr,
                              params=dict(arm=arm, trigger=j, score=key, vol=bool(vol))))
            if h is None: cands[-1]['base_y'] = touch[0].astype(np.float32)   # 판정이 '같은 해 아무 날'·가짜 신호를 같은 닿기 채점으로 재도록(TRACKS 3절)
            s = C.score(tr, 1, D.K); b = _base(D, s['t'], h, touch)
            rows2.append(dict(구분=('방아쇠만' if arm == 'TO' else (f'상태{arm[1:]}일만' if j == 0 else f'상태{arm[1:]}일+방아쇠')), arm=arm, 방아쇠번호=j, 방아쇠=SHORT[j], 채점=key,
                              신호수=int(len(pos)), 독립거래=s['n'], 맞음=s['k'], 적중=(round(s['hit'], 4) if s['n'] >= 10 else None), 아무날=(round(b, 4) if b is not None else None)))
    # 표 1: 해마다 고른 상태
    rows1 = []
    for Y in years:
        m = ST[Y]; iy = D.year == Y
        rows1.append(dict(해=Y, 그때까지_저점수=m['E'], 조건수=len(m['comps']), 점수문턱=m['k'], 그해_점수켜진날=int(on0[iy].sum()), 그해_5일구간=int(ON[5][iy].sum()), 그해_10일구간=int(ON[10][iy].sum()),
                          지표=' · '.join(f"{nm}({'80 이상' if sd == 'hi' else '20 이하'})" for nm, sd, *_ in m['comps']),
                          저점1일전_평균자리=' · '.join(f'{a:.0f}(다른 날 {b:.0f})' for _, _, a, b, *_ in m['comps'])))
    # 표 3: 신호일 ↔ 가장 가까운 실제 저점(전체 자료로 확정된 저점 — 채점용)
    lows = np.array([p for p, t in zigzag(D.c, th) if t == 'L'], dtype=int); rows3 = []

    def dist(pos):
        pos = np.asarray(pos, dtype=int); pos = pos[pos <= lows[-1]] if len(lows) else pos[:0]
        if not len(pos): return None
        ix = np.searchsorted(lows, pos, side='right'); prev = lows[np.clip(ix - 1, 0, len(lows) - 1)]; nxt = lows[np.clip(ix, 0, len(lows) - 1)]
        dp = np.where(ix > 0, pos - prev, 10 ** 6); dn = np.where(ix < len(lows), pos - nxt, -10 ** 6)
        return np.where(np.abs(dn) < np.abs(dp), dn, dp)
    arms3 = [('아무 날', '–', np.where(ywf)[0])] + [((f'상태{a[1:]}일만' if j == 0 else f'상태{a[1:]}일+방아쇠') if a != 'TO' else '방아쇠만', SHORT[j], p) for (a, j), p in POS.items() if (a == 'TO' or years)]
    for nm, tg, pos in arms3:
        d = dist(pos)
        rows3.append(dict(구분=nm, 방아쇠=tg, 신호수=int(len(pos)), 잰신호수=(0 if d is None else int(len(d))), 저점과의_거리_가운뎃값=(None if d is None else float(np.median(d))),
                          거리_절댓값_가운뎃값=(None if d is None else float(np.median(np.abs(d)))), 저점3일전_당일=(None if d is None else round(float(((d >= -WIN) & (d <= 0)).mean()), 4)),
                          저점뒤1_3일=(None if d is None else round(float(((d >= 1) & (d <= 3)).mean()), 4)), 저점뒤1_10일=(None if d is None else round(float(((d >= 1) & (d <= 10)).mean()), 4))))
    T1, T2, T3 = pd.DataFrame(rows1), pd.DataFrame(rows2), pd.DataFrame(rows3)
    names = [f'{pre}state_by_year.csv', f'{pre}trigger_compare.csv', f'{pre}dist_to_low.csv']
    tables_csv = {}
    for nm, df in zip(names, (T1, T2, T3)):
        b = io.StringIO(); df.to_csv(b, index=False); tables_csv[nm] = b.getvalue()
    # summary.md
    pc = lambda x: '–' if x is None or (isinstance(x, float) and not np.isfinite(x)) else f'{100 * x:.0f}%'
    M = [f"### {tag}T2 상태 → 방아쇠: 따로 낸 표 ({'해 ' + '·'.join(map(str, years_all)) + '만(시험용)' if quick else '2016~2026, 해마다 그 전 자료로 고른 상태'})", '',
         f"- 전환 저점 = 코스피 종가 저점에서 {'그날 직전 60일 표준편차×√20' if vol else '5%'} 이상 오른 그 저점. 상태 지표는 해마다 그 해 이전 자료로만 다시 골랐다.",
         '- 적중은 독립 거래(보유 기간이 겹치지 않게 솎음) 기준, 10건 미만은 %를 적지 않는다. 괄호 = (독립 거래 수 / 신호 수).', '',
         '#### ① 해마다 고른 상태 지표와 점수 문턱', '', '| 해 | 그때까지 저점 | 조건 수 중 문턱 | 그 해 켜진 날(당일 / 5일 구간 / 10일 구간) | 고른 지표(조건) |', '|---|---|---|---|---|']
    for r in rows1: M.append(f"| {r['해']} | {r['그때까지_저점수']} | {r['조건수']}개 중 {r['점수문턱']} | {r['그해_점수켜진날']} / {r['그해_5일구간']} / {r['그해_10일구간']} | {r['지표'] or '없음'} |")
    if not rows1: M.append('| – | 상태 계산 조각이 없어 표를 못 냄 | | | |')
    M += ['', "#### ② 방아쇠별 '상태+방아쇠' 대 '방아쇠만' 대 '상태만'", '']
    cell = lambda r: '–' if r is None else f"{pc(r['적중'])} ({r['독립거래']}/{r['신호수']})"
    for key, h in SCORES:
        g = {(r['arm'], r['방아쇠번호']): r for r in rows2 if r['채점'] == key}
        M += [f"**{sc_txt[key]}**", '', '| 방아쇠 | 상태 5일 구간 + 방아쇠 | 상태 10일 구간 + 방아쇠 | 방아쇠만(상태 없음) | 같은 해 아무 날 |', '|---|---|---|---|---|']
        for j in range(1, 9): M.append(f"| {SHORT[j]} | {cell(g.get(('S5', j)))} | {cell(g.get(('S10', j)))} | {cell(g.get(('TO', j)))} | {pc((g.get(('TO', j)) or {}).get('아무날'))} |")
        M += [f"| 상태만(방아쇠 없음) | {cell(g.get(('S5', 0)))} | {cell(g.get(('S10', 0)))} | – | {pc((g.get(('S10', 0)) or {}).get('아무날'))} |", '']
    M += ['#### ③ 신호가 실제 저점에서 며칠 떨어져 있었나', '', '- 가장 가까운 실제 저점(전체 자료로 확정된 저점 — 이 표에서만 뒤를 봄)까지의 거래일 수. + = 저점 뒤, − = 저점 앞. 마지막 확정 저점 뒤의 신호는 뺐다.', '',
          '| 구분 | 방아쇠 | 신호 수 | 거리 가운뎃값 | 거리(크기) 가운뎃값 | 저점 3일 전~당일 | 저점 뒤 1~3일 | 저점 뒤 1~10일 |', '|---|---|---|---|---|---|---|---|']
    fd = lambda x: '–' if x is None else ('0일' if x == 0 else f'{x:+g}일')
    fa = lambda x: '–' if x is None else f'{x:g}일'
    for r in rows3: M.append(f"| {r['구분']} | {r['방아쇠']} | {r['신호수']} | {fd(r['저점과의_거리_가운뎃값'])} | {fa(r['거리_절댓값_가운뎃값'])} | {pc(r['저점3일전_당일'])} | {pc(r['저점뒤1_3일'])} | {pc(r['저점뒤1_10일'])} |")
    notes = ['T2 는 고정 후보 없이 해마다 고른 절차만 낸다(상태 지표는 해마다 다시 고르고, 방아쇠 정의는 전 기간 같음).',
             "'방아쇠만'(family trigger_only)은 상태를 쓰지 않아 2016~2026 전 기간 같은 규칙이다 — 상태가 보태는 몫을 가르는 견줌용.",
             "보유일 없는 채점의 '같은 해 아무 날'은 판정 표에서는 보유일 수익 부호 기준이므로, 아무 날의 '+쪽 먼저 닿기' 비율은 summary 표 ②를 볼 것."]
    if vol: notes.append('변동폭 맞춤판: 전환 크기·장대 양봉·먼저 닿기 문턱을 직전 60일 표준편차 단위로 바꿈. 자리 문턱(80/20)과 T6·T8 의 비율 문턱은 그대로.')
    if failed: notes.append(f'상태 계산 조각 {failed} 실패 — 상태를 쓰는 절차 가운데 해 {sorted(set(years_all) - set(years))} 이 빠졌다.')
    if quick: notes.append('시험용(quick) 결과 — 해 일부·가짜 40번.')
    meta = dict(n_tested=int(sum(FAMILIES.values())), families=dict(FAMILIES), m_fixed=1, m_wf=int(sum(FAMILIES.values())), not_included=list(NOT_INCLUDED), parts_failed=failed, notes=notes,
                tables=names, summary_md='\n'.join(M) + '\n', tables_csv=tables_csv, vol=bool(vol))
    return cands, meta


def main():
    a = C.parse_part(); N = n_parts()
    if a['nparts']: print(N); return
    if a['part']:
        i, n = a['part']; C.save_part(TRACK, i, n, run_part(i, n, quick=a['quick'])); print(f'part {i}/{n} 끝'); return
    if a['merge']:
        cands, meta = merge(C.load_parts(TRACK, N), quick=a['quick'])
        od = os.path.join(C.track_dir(TRACK), 'out'); os.makedirs(os.path.join(od, 'tables'), exist_ok=True)
        for nm, txt in meta.pop('tables_csv').items(): open(os.path.join(od, 'tables', nm), 'w', encoding='utf-8').write(txt)
        open(os.path.join(od, 'summary.md'), 'w', encoding='utf-8').write(meta.pop('summary_md'))
        C.save_result(TRACK, cands, meta); print(f"merge 끝: 후보 {len(cands)}개, 시험 {meta['n_tested']}가지, 실패 조각 {meta['parts_failed']}"); return
    print('사용: python run.py --nparts | --part i/n | --merge [--quick]')


if __name__ == '__main__':
    main()
