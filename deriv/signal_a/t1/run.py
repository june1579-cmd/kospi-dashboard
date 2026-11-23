# -*- coding: utf-8 -*-
"""T1 위치·사건 규칙 전수 — SPEC.md 그대로 구현(돌린 뒤 고치지 않는다).

가족: 벽 종류 7 × 거리 5 × 벽 나이 3 × 물량 변화 4 × 수급 확인 4 × 장세 3 × 늦춤 2 × 첫 신호 2 × 보유일 4 × 방향 2
      (ALL 의 물량 변화 3가지·K2 의 벽 나이 2가지는 뺌) = 128,640개.  wf 절차 28개.
조각 = 벽 종류 하나씩(7개): (조건 묶음 × 늦춤 × 보유일)별 독립 거래의 신호 위치만 넘긴다(수익은 merge 에서).
merge = 해마다 n·k 누적표 → 고르기·그 해 채점 → 같은 절차를 가짜(해 안에서 수익률 줄 회전) 200번 → 표·후보.
vol=True(T4 가 부름): 같은 가짓수, 거리는 σ 단위(OW_<tag>_wall_dist_sig), 수급은 직전 250일 표준편차의 0.5배 초과. id 앞 'V_', desc 앞 '[변동폭 맞춤]'.
"""
import math
import os
import sys

import numpy as np
import pandas as pd
from joblib import Parallel, delayed

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import sa_common as C  # noqa: E402

TRACK = 't1'
NJ = max(1, min(4, os.cpu_count() or 1))
WALLS = ['F0', 'F1', 'F2', 'F3', 'Q', 'ALL', 'K2']
TAGS = ['F0', 'F1', 'F2', 'F3', 'Q', 'ALL']
K2_TAGS = ['F0', 'F1', 'F2', 'ALL']
DIST = {False: [0.5, 1.0, 1.5, 2.0, 3.0], True: [0.5, 1.0, 1.5, 2.0, 2.5]}
AGE = ['any', 'new', 'old']
CHG = ['any', 'up5', 'up1', 'dn5']
FLOW = ['none', 'fut', 'spot', 'both']
REG = ['any', 'above', 'below']
DELAY = [0, 1]
FIRST = [0, 1]
HOLDS = [1, 3, 5, 10]
FIRST_N = 5
MAXH = 10
SHAPES = [('goal', 0.85), ('watch', 0.80)]
COUNTS = [1, 5, 20, 0]                      # 0 = 전부
HOWS = ['any', 'cons']
PROCS = [(dn, sh, cn, how) for dn in ('up', 'dn') for sh, _ in SHAPES for cn in COUNTS for how in HOWS if not (cn == 1 and how == 'cons')]   # 28
N_FAKE = 200
Y0 = C.START.year
NYB = C.END.year - Y0 + 1                   # 청산 해 칸(2010~2026)
NOT_INCLUDED = [
    '연구소 꼴 그대로의 거리 띠(직전 20일 σ×√5×k, 1.75σ)와 분기물 만기 21~40거래일 아님 조건, 결제월 교체도 새 벽으로 세는 나이',
    '같은 자리를 3·5·7일 이상 지킨 오래된 벽(벽 나이 세분), 셋 이상 동시 새 벽(K3), 새 벽이 생긴 까닭(물량 이동·넘어섬·만기 교체)',
    '위클리 옵션 콜벽·차기 분기물(Q2)·풋벽·이미 넘어선 벽',
    '외국인 콜·풋 옵션 흐름, 수급 누적 창 5·10일, 기관·개인 수급',
    '고르는 꼴의 다른 문턱(적중 75%·90%, 윌슨 하한 문턱)과 합의 비율 10%·30%, 두 방향 신호 함께 쓰기',
    '익절·손절(±k%) 청산과 보유일 2·7·20일(T6 에서 남은 후보만)',
]


def _walls(quick): return ['Q', 'K2'] if quick else WALLS
def _holds(quick): return [3, 5] if quick else HOLDS
def _ages(w): return ['new'] if w == 'K2' else AGE
def _chgs(w): return ['any'] if w == 'ALL' else CHG


def cond_list(w, vol):
    """벽 종류 w 의 조건 묶음(거리·나이·물량·수급·장세·첫 신호) 목록 — 순서가 곧 번호."""
    return [(bi, a, c, f, r, fs) for bi in range(len(DIST[bool(vol)])) for a in _ages(w) for c in _chgs(w) for f in FLOW for r in REG for fs in FIRST]


def family_counts(quick=False, vol=False):
    return {w: len(cond_list(w, vol)) * len(DELAY) * len(_holds(quick)) * 2 for w in _walls(quick)}


def _par(fn, argsets):
    """joblib 4코어. 프로세스 실행이 안 되는 환경(모듈을 못 찾는 등)이면 차례로 돈다."""
    argsets = list(argsets)
    if NJ > 1 and len(argsets) > 1:
        try: return Parallel(n_jobs=NJ)(delayed(fn)(*a) for a in argsets)
        except Exception as e: print('joblib 실패 → 차례로 계산:', repr(e)[:200])
    return [fn(*a) for a in argsets]


# ------------------------------------------------------------------ 조건 마스크
def components(D, vol):
    X = D.X; n = D.n; ones = np.ones(n, dtype=bool); dcol = 'wall_dist_sig' if vol else 'wall_dist%'
    col = lambda t, c: X[f'OW_{t}_{c}'].values.astype(float) if f'OW_{t}_{c}' in X.columns else np.full(n, np.nan)
    comp = {}
    with np.errstate(invalid='ignore'):
        for t in TAGS:
            d = col(t, dcol); new = col(t, 'wall_new'); c5 = col(t, 'wall_oi_chg5%'); c1 = col(t, 'wall_oi_chg1%')
            comp[t] = {'dist': d, 'age': {'any': ones, 'new': new == 1, 'old': new == 0}, 'chg': {'any': ones, 'up5': c5 > 0, 'up1': c1 > 0, 'dn5': c5 < 0}}
        news = {t: comp[t]['age']['new'] for t in K2_TAGS}
        k2 = sum(v.astype(int) for v in news.values()) >= 2
        dmin = np.fmin.reduce([np.where(news[t] & (comp[t]['dist'] > 0), comp[t]['dist'], np.nan) for t in K2_TAGS])
        dmin = np.where(k2, dmin, np.nan)
        anyc = lambda key: k2 & np.any([news[t] & comp[t]['chg'][key] for t in ('F0', 'F1', 'F2')], axis=0)
        comp['K2'] = {'dist': dmin, 'age': {'new': k2}, 'chg': {'any': ones, 'up5': anyc('up5'), 'up1': anyc('up1'), 'dn5': anyc('dn5')}}
        f3 = X['F_외국인_1d'].rolling(3, min_periods=3).sum(); s3 = X['S_외국인현물_1d'].rolling(3, min_periods=3).sum()
        if vol:
            fut = (f3 > 0.5 * f3.shift(1).rolling(250, min_periods=120).std()).values; spot = (s3 > 0.5 * s3.shift(1).rolling(250, min_periods=120).std()).values
        else:
            fut = (f3 > 0).values; spot = (s3 > 0).values
        c = pd.Series(D.c, index=D.td); ma = c.rolling(60, min_periods=60).mean()
        comp['_flow'] = {'none': ones, 'fut': fut, 'spot': spot, 'both': fut & spot}
        comp['_reg'] = {'any': ones, 'above': (c > ma).values, 'below': (c < ma).values}
    comp['_live'] = np.asarray(D.td >= C.START)
    return comp


def build_M(D, comp, w, vol):
    """벽 종류 w 의 조건 묶음별 조건일 마스크(첫 신호 처리까지) [묶음 수, 날 수]."""
    cl = cond_list(w, vol); M = np.zeros((len(cl), D.n), dtype=bool); cw = comp[w]; cache = {}
    with np.errstate(invalid='ignore'):
        for i, (bi, a, c, f, r, fs) in enumerate(cl):
            key = (bi, a, c, f, r)
            if key not in cache:
                b = DIST[bool(vol)][bi]
                cache = {key: comp['_live'] & (cw['dist'] > 0) & (cw['dist'] <= b) & cw['age'][a] & cw['chg'][c] & comp['_flow'][f] & comp['_reg'][r]}
            m = cache[key]
            M[i] = D.first_only(m, FIRST_N) if fs else m
    return M


def _thin_rows(Msub, holds, n):
    """조건 묶음마다 (늦춤 × 보유일)별 독립 거래의 신호 위치(= 조건일 + 늦춤). D.thin_pos 와 같은 규칙."""
    out = []
    for row in Msub:
        pos = np.flatnonzero(row).tolist()
        for d in DELAY:
            for h in holds:
                keep = []; last = -1
                for p in pos:
                    s = p + d
                    if s >= last and s + h < n: keep.append(s); last = s + h
                out.append(np.asarray(keep, dtype=np.int16))
    return out


# ------------------------------------------------------------------ 조각
def n_parts(vol=False):
    return len(WALLS)


def run_part(i, n, vol=False, quick=False):
    D = C.Data(); comp = components(D, vol); holds = _holds(quick); out = {'vol': bool(vol), 'quick': bool(quick), 'walls': {}}
    ws = (_walls(True) if i == 1 else []) if quick else [w for k, w in enumerate(WALLS) if k % n == (i - 1) % n]
    for w in ws:
        M = build_M(D, comp, w, vol)
        chunks = [c for c in np.array_split(np.arange(len(M)), NJ * 2) if len(c)]
        res = _par(_thin_rows, [(M[c], holds, D.n) for c in chunks])
        segs = [s for r in res for s in r]
        out['walls'][w] = {'S': np.concatenate(segs) if segs else np.zeros(0, np.int16), 'cnt': np.asarray([len(s) for s in segs], dtype=np.int32), 'nsig': M.sum(1).astype(np.int32)}
    return out


# ------------------------------------------------------------------ 고르기·채점 (실제·가짜 공통)
def _wilson_lb(k, n, z=C.Z90):
    p = k / n; d = 1 + z * z / n; c = p + z * z / (2 * n); h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (c - h) / d


def _sig_matrix(G, U, a, e):
    """쓰는 규칙 U(윌슨 하한 순)의 그 해 신호일 표 [규칙, 그 해 날]. 신호일 = 조건일 + 늦춤."""
    cs = G['cs'][U]; out = G['M'][cs, a:e]; d1 = np.flatnonzero(G['delay'][U] == 1)
    if len(d1): out[d1] = G['M'][cs[d1], a - 1:e - 1]
    return out


def _median_hold(S, h):
    vals = np.unique(h); cum = np.stack([(S & (h == v)[:, None]).sum(0) for v in vals]).cumsum(0); tot = cum[-1]
    lo = vals[(cum >= np.ceil(tot / 2)[None]).argmax(0)]; hi = vals[(cum >= (tot // 2 + 1)[None]).argmax(0)]
    return np.floor((lo + hi) / 2 + 0.5).astype(int)


def _score(s, h, n, R, OK, year=None):
    """절차의 거래(신호 위치 s·보유일 h, 날짜 순)를 솎아 (독립 거래 수, 맞은 수, 해마다)."""
    if not len(s): return 0, 0, {}
    keep = []; last = -1
    for i, (a, b) in enumerate(zip(s.tolist(), h.tolist())):
        if a >= last and a + b < n: keep.append(i); last = a + b
    s = s[keep]; h = h[keep]; ok = OK[h - 1, s]; hit = R[h - 1, s] & ok; by = {}
    if year is not None:
        y = year[s]
        for a in np.unique(y): by[int(a)] = (int(ok[y == a].sum()), int(hit[y == a].sum()))
    return int(ok.sum()), int(hit.sum()), by


def evaluate(G, perm=None, detail=False):
    """고르기(해마다 그 전 자료) → 그 해 채점. perm = 수익률 줄의 자리 바꿈(가짜). detail=True 면 거래·고른 규칙도 돌려준다."""
    n = G['n']; nb = G['nb']; years = G['years']
    RU, RD, OK = (G['RU'], G['RD'], G['OK']) if perm is None else (G['RU'][:, perm], G['RD'][:, perm], G['OK'][:, perm])
    res = {'proc': np.zeros((len(PROCS), 2), dtype=np.int64), 'nsel': np.zeros((2, len(SHAPES), len(years)), dtype=np.int64), 'ins': np.zeros((2, 2), dtype=np.int64)}
    if detail: res.update({'K': {}, 'trades': {}, 'by': {}, 'sel': []})
    tn = G['cumN'][:, -1]; big = tn >= 35
    for di, (dn, R) in enumerate((('up', RU), ('dn', RD))):
        K = np.bincount(G['bin'], weights=R.ravel()[G['flat']], minlength=nb * NYB).reshape(nb, NYB).cumsum(1) if nb else np.zeros((0, NYB))
        tk = K[:, -1]; res['ins'][di] = [int((big & (tk >= 0.85 * tn - 1e-9)).sum()), int((big & (tk >= 0.80 * tn - 1e-9)).sum())]
        if detail: res['K'][dn] = K
        tr = {p: ([], []) for p in PROCS if p[0] == dn}
        for yi, Y in enumerate(years):
            b = Y - 1 - Y0; nn = G['cumN'][:, b]; idx = np.flatnonzero(nn >= G['nmin'][yi])
            if not len(idx): continue
            kk = K[idx, b]; nv = nn[idx].astype(float); hit = kk / nv; lb = _wilson_lb(kk, nv); a, e = G['yr'][yi]
            for si, (sh, thr) in enumerate(SHAPES):
                m = hit >= thr - 1e-9; sel = idx[m]; res['nsel'][di, si, yi] = len(sel)
                if detail and not len(sel): res['sel'].append({'year': Y, 'dir': dn, 'shape': sh, 'n_min': G['nmin'][yi], 'n_enough': len(idx), 'n_sel': 0})
                if not len(sel): continue
                U = sel[np.lexsort((sel, -nv[m], -lb[m]))]; SY = _sig_matrix(G, U, a, e); hU = G['hold'][U]
                if detail:
                    j = int(U[0]); res['sel'].append({'year': Y, 'dir': dn, 'shape': sh, 'n_min': G['nmin'][yi], 'n_enough': len(idx), 'n_sel': len(sel),
                                                      'top_j': j, 'top_n': int(nn[j]), 'top_k': int(K[j, b])})
                for cn in COUNTS:
                    k = len(U) if cn == 0 else min(cn, len(U)); S = SY[:k]
                    days = np.flatnonzero(S.any(0))
                    if len(days):
                        t = tr[(dn, sh, cn, 'any')]; t[0].append(a + days); t[1].append(hU[S[:, days].argmax(0)])
                    if cn != 1:
                        need = max(2, math.ceil(0.2 * k)); days = np.flatnonzero(S.sum(0) >= need)
                        if len(days):
                            t = tr[(dn, sh, cn, 'cons')]; t[0].append(a + days); t[1].append(_median_hold(S[:, days], hU[:k]))
        for p, (ss, hh) in tr.items():
            s = np.concatenate(ss) if ss else np.zeros(0, dtype=np.int64); h = np.concatenate(hh).astype(np.int64) if hh else np.zeros(0, dtype=np.int64)
            nn_, kk_, by = _score(s, h, n, R, OK, G['year'] if detail else None)
            res['proc'][PROCS.index(p)] = (nn_, kk_)
            if detail: res['trades'][p] = (s, h); res['by'][p] = by
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
        out.append((r['proc'], r['nsel'], r['ins']))
    return out


# ------------------------------------------------------------------ 말(쉬운 한국어)
WALL_KO = {'F0': '근월물', 'F1': '차월물', 'F2': '차차월물', 'F3': '넷째 결제월', 'Q': '분기물', 'ALL': '전 결제월 합산'}
AGE_KO = {'any': '', 'new': ' + 오늘 새로 생긴 벽', 'old': ' + 어제와 같은 벽'}
CHG_KO = {'any': '', 'up5': ' + 벽 물량 5일 증가', 'up1': ' + 벽 물량 1일 증가', 'dn5': ' + 벽 물량 5일 감소'}
REG_KO = {'any': '', 'above': ' + 코스피 60일선 위', 'below': ' + 코스피 60일선 아래'}
SH_KO = {'goal': '통과 꼴(적중 85% 이상)', 'watch': '관찰 꼴(적중 80% 이상)'}
CN_KO = {1: '윌슨 하한 상위 1개', 5: '상위 5개', 20: '상위 20개', 0: '고른 것 전부'}
HOW_KO = {'any': '하나라도 켜진 날 매수(그 규칙 보유일)', 'cons': '쓰는 규칙의 20% 이상이 함께 켜진 날 매수(보유일 가운뎃값)'}


def rule_desc(w, bi, a, c, f, r, fs, d, h, direction, vol):
    b = DIST[bool(vol)][bi]; u = 'σ' if vol else '%'
    fl = {'none': '', 'fut': ' + 외국인 선물 3일 누적 순매수', 'spot': ' + 외국인 현물 3일 누적 순매수', 'both': ' + 외국인 선물·현물 3일 누적 함께 순매수'}[f]
    if vol and f != 'none': fl += '(직전 250일 표준편차의 0.5배 초과)'
    if w == 'K2': head = f'근월·차월·차차월·합산 중 둘 이상이 같은 날 새 콜벽 + 가장 가까운 새 벽이 지수 위 0~{b}{u} 안' + CHG_KO[c].replace('벽 물량', '새 벽 물량(하나라도)')
    else: head = f'{WALL_KO[w]} 콜벽이 지수 위 0~{b}{u} 안' + AGE_KO[a] + CHG_KO[c]
    return (('[변동폭 맞춤] ' if vol else '') + head + fl + REG_KO[r] + (' + 직전 5일 안 같은 조건 없던 첫날만' if fs else '')
            + ' → ' + ('하루 쉬고 ' if d else '다음 날 시가 ') + f"매수, {h}일 보유, {'오름' if direction > 0 else '내림'}")


def rule_id(w, bi, a, c, f, r, fs, d, h, direction, vol):
    return ('V_' if vol else '') + f"R_{w}_b{int(round(DIST[bool(vol)][bi] * 10)):02d}_{a}_{c}_{f}_{r}_d{d}_f{fs}_h{h}_{'up' if direction > 0 else 'dn'}"


def proc_id(p, vol): return ('V_' if vol else '') + f"WF_{p[1]}_{'all' if p[2] == 0 else 'top%d' % p[2]}_{p[3]}_{p[0]}"


def proc_desc(p, vol):
    return (('[변동폭 맞춤] ' if vol else '') + f"해마다 그 전 자료에서 {SH_KO[p[1]]} 규칙을 골라 {CN_KO[p[2]]} 사용 · {HOW_KO[p[3]]} → {'오름' if p[0] == 'up' else '내림'}")


def _pc(k, n): return '–' if n < 10 else f'{100 * k / n:.1f}%'


def _md(df):
    out = ['| ' + ' | '.join(map(str, df.columns)) + ' |', '|' + '---|' * len(df.columns)]
    return out + ['| ' + ' | '.join(str(v) for v in r) + ' |' for r in df.values.tolist()]


# ------------------------------------------------------------------ merge
def merge(parts, vol=False, quick=False, out_dir=None):
    """parts[i-1] 이 None 이면 그 조각 실패. (cands, meta) 반환. out_dir 을 주면 그 아래 tables/*.csv·summary.md 를 쓴다(vol 이면 파일 이름 앞 'V_')."""
    vol = bool(vol); D = C.Data(); comp = components(D, vol); holds = _holds(quick); nH = len(holds); n = D.n; pre = 'V_' if vol else ''
    parts = list(parts or []); good = lambda p: p is not None and bool(p.get('vol')) == vol and bool(p.get('quick')) == bool(quick)
    have = {}; failed = []
    if quick:
        if parts and good(parts[0]): have = dict(parts[0]['walls'])
        else: failed = [1]
    else:
        for i in range(1, n_parts(vol) + 1):
            p = parts[i - 1] if i - 1 < len(parts) else None
            if good(p): have.update(p['walls'])
            else: failed.append(i)
    walls = [w for w in _walls(quick) if w in have]
    fam = {w: len(cond_list(w, vol)) * len(DELAY) * nH * 2 for w in walls}; n_tested = int(sum(fam.values()))
    plan = family_counts(quick, vol)
    notes = [f"가족 = 벽 종류. 미리 정한 가짓수 {sum(plan.values()):,}개 중 {n_tested:,}개를 시험(실패 조각 {failed or '없음'})." + (' [quick 시험: 벽 2개·보유일 2개·가짜 5번]' if quick else ''),
             'fixed 후보는 전체 기간 성적을 보고 고른 것(방향별 적중 상위 100개 + 연구소 부품 규칙 2개)이라 다음 해 성적이 아니다. 믿을 숫자는 wf 절차 28개.']
    meta = {'n_tested': n_tested, 'families': fam, 'm_fixed': n_tested, 'm_wf': len(PROCS), 'not_included': list(NOT_INCLUDED), 'parts_failed': failed, 'notes': notes, 'tables': [], 'vol': vol}
    if not walls:
        meta['summary_md'] = '계산 조각이 없어 표를 만들지 못함.'
        return [], meta

    # 규칙(방향 빼고) 표와 조건 마스크
    Ms = []; attr = []; cs0 = 0; Sl = []; cl_ = []
    for w in walls:
        cl = cond_list(w, vol); M = build_M(D, comp, w, vol); Ms.append(M)
        assert len(have[w]['cnt']) == len(cl) * len(DELAY) * nH, f'조각 {w} 의 규칙 수가 SPEC 과 다름'
        for ci, t in enumerate(cl):
            for d in DELAY:
                for h in holds: attr.append((w,) + t + (d, h, cs0 + ci))
        cs0 += len(cl); Sl.append(have[w]['S'].astype(np.int64)); cl_.append(have[w]['cnt'].astype(np.int64))
    M = np.concatenate(Ms); S = np.concatenate(Sl); cnt = np.concatenate(cl_); nb = len(attr); off = np.r_[0, np.cumsum(cnt)]
    hold = np.asarray([t[8] for t in attr], dtype=np.int64); delay = np.asarray([t[7] for t in attr], dtype=np.int64); cs = np.asarray([t[9] for t in attr], dtype=np.int64)
    jrep = np.repeat(np.arange(nb), cnt); ht = hold[jrep]
    flat = ((ht - 1) * n + S).astype(np.int32); bins = (jrep * NYB + (D.year[S + ht] - Y0)).astype(np.int32)
    cumN = np.bincount(bins, minlength=nb * NYB).reshape(nb, NYB).cumsum(1)
    RU = np.zeros((MAXH, n), dtype=bool); RD = RU.copy(); OK = RU.copy()
    with np.errstate(invalid='ignore'):
        for h in range(1, MAXH + 1):
            r = D.fwd(h); RU[h - 1] = r > 0; RD[h - 1] = r < 0; OK[h - 1] = np.isfinite(r)
    years = [y for y, _ in C.wf_splits()]
    G = {'n': n, 'nb': nb, 'years': years, 'nmin': [max(12, int(round(35 * (y - Y0) / 17))) for y in years], 'cumN': cumN, 'flat': flat, 'bin': bins,
         'RU': RU, 'RD': RD, 'OK': OK, 'M': M, 'cs': cs, 'delay': delay, 'hold': hold, 'year': D.year.astype(np.int64),
         'yr': [(int(np.flatnonzero(D.year == y)[0]), int(np.flatnonzero(D.year == y)[-1]) + 1) for y in years]}

    real = evaluate(G, None, detail=True)
    nf = 5 if quick else N_FAKE
    fk = [x for r in _par(_fake_chunk, [(G, c) for c in np.array_split(np.arange(nf), min(nf, NJ * 2)) if len(c)]) for x in r]
    FP = np.stack([x[0] for x in fk]).astype(float); FS = np.stack([x[1] for x in fk]).astype(float); FI = np.stack([x[2] for x in fk]).astype(float)

    key = lambda j, direction: (attr[j][0],) + attr[j][1:9] + (direction, vol)
    cands = []
    # ---- wf 절차 28개
    T_fake = []
    for pi, p in enumerate(PROCS):
        s, h = real['trades'][p]; ok = s + h < n; direction = 1 if p[0] == 'up' else -1
        tr = pd.DataFrame({'signal': D.td[s[ok]], 'exit': D.td[(s + h)[ok]]})
        cands.append({'id': proc_id(p, vol), 'family': 'wf 절차', 'desc': proc_desc(p, vol), 'direction': direction, 'hold': None, 'kind': 'wf', 'trades': tr,
                      'params': {'shape': p[1], 'count': p[2], 'how': p[3], 'vol': vol}})
        rn, rk = map(int, real['proc'][pi]); fn = FP[:, pi, 0]; fh = np.where(fn > 0, FP[:, pi, 1] / np.maximum(fn, 1), np.nan); v = fh[fn >= 10]
        rh = rk / rn if rn else np.nan
        q = (lambda x: f'{100 * np.quantile(v, x):.1f}%') if len(v) else (lambda x: '–')
        T_fake.append({'절차': proc_id(p, vol), '설명': proc_desc(p, vol), '실제 독립 거래': rn, '실제 다음 해 적중': _pc(rk, rn), '가짜 평균 거래': round(float(fn.mean()), 1),
                       '가짜 적중 평균': (f'{100 * v.mean():.1f}%' if len(v) else '–'), '가짜 5%': q(0.05), '가짜 50%': q(0.5), '가짜 95%': q(0.95),
                       '가짜가 실제 이상인 비율': (round(float((1 + np.nansum(fh >= rh - 1e-12)) / (1 + nf)), 3) if rn >= 10 else '–'), '가짜 횟수': nf})
    T_fake = pd.DataFrame(T_fake)
    T_year = pd.DataFrame([{'절차': proc_id(p, vol), **{str(y): '/'.join(map(str, real['by'][p].get(y, (0, 0)))) for y in years}} for p in PROCS])

    # ---- 고른 규칙 수: 실제 대 가짜
    rows = []
    for r_ in real['sel']:
        di = 0 if r_['dir'] == 'up' else 1; si = [s_ for s_, _ in SHAPES].index(r_['shape']); yi = years.index(r_['year']); f = FS[:, di, si, yi]
        row = {'해': r_['year'], '방향': '오름' if di == 0 else '내림', '꼴': SH_KO[r_['shape']], '최소 거래 수': r_['n_min'], '거래 수 채운 규칙': r_['n_enough'], '고른 규칙 수(실제)': r_['n_sel'],
               '고른 규칙 수(가짜 평균)': round(float(f.mean()), 1), '가짜 95%': round(float(np.quantile(f, 0.95)), 1)}
        if r_.get('top_j') is not None:
            j = r_['top_j']; row.update({'1위 규칙': rule_desc(*key(j, 1 if di == 0 else -1)), '1위 그때까지 거래': r_['top_n'], '1위 그때까지 적중': _pc(r_['top_k'], r_['top_n'])})
        rows.append(row)
    T_sel = pd.DataFrame(rows).sort_values(['방향', '꼴', '해'], ascending=[False, True, True]) if rows else pd.DataFrame()

    # ---- 전체 기간: 35건 이상·적중 85%(80%) 이상 규칙 수, 실제 대 가짜 + 가족별 수
    tn = cumN[:, -1]; rows = []
    for di, dn in enumerate(('up', 'dn')):
        for ti, thr in enumerate((85, 80)):
            f = FI[:, di, ti]
            rows.append({'방향': '오름' if di == 0 else '내림', '기준': f'독립 35건 이상·적중 {thr}% 이상', '규칙 수(실제)': int(real['ins'][di, ti]), '규칙 수(가짜 평균)': round(float(f.mean()), 1),
                         '가짜 95%': round(float(np.quantile(f, 0.95)), 1), '가짜가 실제 이상인 비율': round(float((1 + (f >= real['ins'][di, ti]).sum()) / (1 + nf)), 3)})
    T_ins = pd.DataFrame(rows)
    wj = np.asarray([t[0] for t in attr])
    T_fam = pd.DataFrame([{'가족(벽 종류)': w, '시험한 가짓수(방향 2 포함)': fam[w], '독립 10건 이상': int(2 * ((wj == w) & (tn >= 10)).sum()), '독립 35건 이상': int(2 * ((wj == w) & (tn >= 35)).sum()),
                           '조건 묶음당 평균 신호일': round(float(have[w]['nsig'].mean()), 1)} for w in walls])

    # ---- fixed: 방향별 적중 상위 100개(독립 35건 이상) + 연구소 부품 규칙
    jof = {attr[j][:9]: j for j in range(nb)}
    def fixed_cand(j, direction, family):
        a_ = attr[j]; pos = np.flatnonzero(M[a_[9]])
        return {'id': rule_id(*key(j, direction)), 'family': family, 'desc': rule_desc(*key(j, direction)), 'direction': direction, 'hold': int(a_[8]), 'kind': 'fixed',
                'trades': D.trades_from_pos(pos, int(a_[8]), int(a_[7])), 'params': {'wall': a_[0], 'dist': DIST[vol][a_[1]], 'age': a_[2], 'chg': a_[3], 'flow': a_[4], 'reg': a_[5],
                                                                                   'first': a_[6], 'delay': a_[7], 'hold': a_[8], 'vol': vol}}
    lab = [('Q 규칙', ('Q', 2, 'any', 'up5', 'none', 'any', 1, 1, 3), True)]
    lab += [(f"K2 규칙({DIST[vol][bi]}{'σ' if vol else '%'})", ('K2', bi, 'new', 'any', 'both', 'above', 0, 0, 5), bi == (2 if vol else 4)) for bi in range(len(DIST[vol]))]
    seen = set()
    for nm, t, main in lab:
        if main and t in jof:
            c_ = fixed_cand(jof[t], 1, '연구소 부품 규칙'); c_['desc'] = f'(연구소 통과 신호의 부품 — {nm}) ' + c_['desc']; cands.append(c_); seen.add(c_['id'])
    for di, dn in enumerate(('up', 'dn')):
        K = real['K'][dn]; tk = K[:, -1]; idx = np.flatnonzero(tn >= 35)
        o = idx[np.lexsort((idx, -tn[idx], -(tk[idx] / tn[idx])))][:100]
        for j in o:
            c_ = fixed_cand(int(j), 1 if di == 0 else -1, f'벽 {attr[j][0]}')
            if c_['id'] not in seen: cands.append(c_); seen.add(c_['id'])

    # ---- 연구소 부품 규칙이 해마다 뽑혔는지와 그 해 성적
    rows = []; Ku = real['K']['up']
    for nm, t, main in lab:
        if t not in jof: continue
        j = jof[t]; sg = S[off[j]:off[j + 1]]; ys = D.year[sg]; hit = RU[hold[j] - 1, sg]
        for yi, Y in enumerate(years):
            b = Y - 1 - Y0; n_tr = int(cumN[j, b]); k_tr = int(Ku[j, b]); nm_ = G['nmin'][yi]; ny = int((ys == Y).sum()); ky = int(hit[ys == Y].sum())
            ok85 = bool(n_tr >= nm_ and k_tr >= 0.85 * n_tr - 1e-9); ok80 = bool(n_tr >= nm_ and k_tr >= 0.80 * n_tr - 1e-9)
            rows.append({'규칙': nm, '해': Y, '그때까지 독립 거래': n_tr, '최소 거래 수': nm_, '그때까지 적중': _pc(k_tr, n_tr), '통과 꼴로 뽑힘': '예' if ok85 else '아니오', '관찰 꼴로 뽑힘': '예' if ok80 else '아니오',
                         '그 해 독립 거래': ny, '그 해 맞은 수': ky, '_g': ok85, '_w': ok80})
    T_lab = pd.DataFrame(rows); lab_sum = []
    if len(T_lab):
        for nm, g in T_lab.groupby('규칙', sort=False):
            f = lambda m: f"{int(m.sum())}해 · {int(g.loc[m, '그 해 독립 거래'].sum())}거래 · 적중 {_pc(int(g.loc[m, '그 해 맞은 수'].sum()), int(g.loc[m, '그 해 독립 거래'].sum()))}"
            lab_sum.append({'규칙': nm, '통과 꼴로 뽑힌 해의 그 해 성적': f(g['_g']), '관찰 꼴로 뽑힌 해의 그 해 성적': f(g['_w']), '안 뽑힌 해(관찰 꼴 기준)': f(~g['_w']), '2016~2026 전부': f(g['_w'] | True)})
        T_lab = T_lab.drop(columns=['_g', '_w'])
    T_labsum = pd.DataFrame(lab_sum)

    # ---- 표·요약
    md = ['### T1 따로 낸 표' + (' [변동폭 맞춤판]' if vol else '') + (' [quick 시험]' if quick else ''), '',
          f'시험한 규칙 {n_tested:,}개(방향 포함), 해마다 고르는 절차 {len(PROCS)}개, 가짜 {nf}번(수익률 줄을 해 안에서만 통째로 돌림).', '',
          '#### (1) 가족별 가짓수', ''] + _md(T_fam) + ['',
          '#### (2) 전체 기간에 통과 숫자를 채운 규칙 수 — 실제 대 가짜 (우연히도 이만큼은 나온다)', ''] + _md(T_ins) + ['',
          '#### (3) 해마다 고르는 절차의 다음 해 적중 — 실제 대 가짜', '', '가짜에서도 같은 절차로 고르고 채점했다. 실제가 가짜 95% 선보다 높아야 우연이 아니라고 볼 수 있다. 독립 거래 10건 미만은 %를 적지 않는다.', '']
    md += _md(T_fake.drop(columns=['절차', '가짜 횟수'])) + ['', '#### (4) 절차별 해마다 (독립 거래 수/맞은 수)', ''] + _md(T_year) + ['']
    if len(T_sel):
        g = T_sel.groupby(['방향', '꼴'], sort=False).agg(**{'고른 규칙 수(실제, 해 평균)': ('고른 규칙 수(실제)', 'mean'), '고른 규칙 수(가짜 평균, 해 평균)': ('고른 규칙 수(가짜 평균)', 'mean')}).round(1).reset_index()
        md += ['#### (5) 해마다 고른 규칙 수 — 실제 대 가짜 (해별 표는 tables 의 wf_sel_counts.csv)', ''] + _md(g) + ['']
    md += ['#### (6) 연구소 통과 신호의 부품 규칙 — 해마다 이 절차로 뽑혔는지와 그 해 성적', '',
           'Q 규칙 = 분기물 콜벽 0~1.5 안 + 벽 물량 5일 증가 + 첫날만 + 하루 쉬고 3일. K2 규칙 = 둘 이상 동시 새 콜벽 + 외국인 선물·현물 순매수 + 60일선 위, 5일(거리 5가지를 참고로 다 적음).', '']
    md += (_md(T_labsum) if len(T_labsum) else ['- 이번 계산 범위에 해당 규칙 없음']) + ['']
    if len(T_lab): md += _md(T_lab[T_lab['규칙'].isin([nm for nm, _, main in lab if main])]) + ['']
    meta['summary_md'] = '\n'.join(md)
    tabs = {'family_counts.csv': T_fam, 'insample_counts.csv': T_ins, 'wf_fake.csv': T_fake, 'wf_by_year.csv': T_year, 'wf_sel_counts.csv': T_sel, 'lab_rule_by_year.csv': T_lab, 'lab_rule_summary.csv': T_labsum}
    meta['tables'] = [pre + k for k in tabs]
    if out_dir:
        os.makedirs(os.path.join(out_dir, 'tables'), exist_ok=True)
        for k, df in tabs.items(): df.to_csv(os.path.join(out_dir, 'tables', pre + k), index=False, encoding='utf-8')
        open(os.path.join(out_dir, pre + 'summary.md'), 'w', encoding='utf-8').write(meta['summary_md'] + '\n')
    return cands, meta


if __name__ == '__main__':
    a = C.parse_part()
    if a['nparts']:
        print(n_parts())
    elif a['part']:
        i, n_ = a['part']; C.save_part(TRACK, i, n_, run_part(i, n_, quick=a['quick'])); print(f'조각 {i}/{n_} 저장')
    elif a['merge']:
        cands, meta = merge(C.load_parts(TRACK, n_parts()), quick=a['quick'], out_dir=os.path.join(C.track_dir(TRACK), 'out'))
        C.save_result(TRACK, cands, meta); print(f"후보 {len(cands)}개 · 시험 {meta['n_tested']:,}가지 · wf 절차 {meta['m_wf']}개 · 실패 조각 {meta['parts_failed']}")
