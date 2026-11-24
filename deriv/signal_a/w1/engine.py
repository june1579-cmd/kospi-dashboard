# -*- coding: utf-8 -*-
"""T1 식 계산 틀(W1·W2 공용) — t1/run.py 의 조각·evaluate·가짜 회전·표를 복사해, 가족(조건 묶음)을 바꿔 끼울 수 있게만 고친 것.
t1/run.py 는 고치지 않는다. 고르기·채점·가짜의 셈법은 T1 과 한 글자도 다르지 않게 두었다(가족을 만드는 부분만 spec 이 준다).

spec(줄기 run.py 가 주는 물건)이 갖출 것
  TRACK                      'w1' | 'w2'
  SUBS, QUICK_SUBS           작은 가족 이름 목록(조각으로 나누는 단위)과 quick 시험 때 쓸 것
  HOLDS, QUICK_HOLDS         보유일 목록(1~10)
  NOT_INCLUDED               SPEC '안 넣은 것'
  SUB_KO                     {작은 가족: 쉬운 이름}(가족별 가짓수 표·meta.families 의 이름)
  ROOT                       후보의 뿌리 이름
  make_ctx(D)                조건 재료(한 번만 만든다). 자료를 못 읽으면 raise
  cond_list(sub)             조건 묶음 목록(tuple, 마지막 원소 = 첫 신호 0/1) — 순서가 곧 번호
  build_M(D, ctx, sub)       조건 묶음별 조건일 마스크 [묶음 수, 날 수] (첫 신호 처리까지)
  rule_id(sub, cond, d, h, direction) / rule_desc(…) / rule_params(sub, cond, d, h)
  LAB                        [(이름, (sub, cond, d, h), fixed 후보로 넘길지)] — 연구소 규칙(오름) 따로 표
  LAB_NOTE                   그 표 위에 적을 한 줄
가족 차원: 조건 묶음 × 늦춤(0·1) × 보유일 × 방향(오름·내림).
"""
import math
import os
import sys

import numpy as np
import pandas as pd
from joblib import Parallel, delayed

HERE = os.path.dirname(os.path.abspath(__file__))
SA = os.path.dirname(HERE)
for _p in (SA, HERE):
    if _p not in sys.path: sys.path.insert(0, _p)
# joblib 일꾼(새 프로세스)이 이 모듈과 sa_common 을 찾게 한다
os.environ['PYTHONPATH'] = os.pathsep.join([HERE, SA] + [x for x in os.environ.get('PYTHONPATH', '').split(os.pathsep) if x and x not in (HERE, SA)])
import sa_common as C  # noqa: E402

NJ = max(1, min(4, os.cpu_count() or 1))
DELAY = [0, 1]
FIRST_N = 5
MAXH = 10
SHAPES = [('goal', 0.85), ('watch', 0.80)]
COUNTS = [1, 5, 20, 0]                      # 0 = 전부
HOWS = ['any', 'cons']
PROCS = [(dn, sh, cn, how) for dn in ('up', 'dn') for sh, _ in SHAPES for cn in COUNTS for how in HOWS if not (cn == 1 and how == 'cons')]   # 28
N_FAKE = 200
Y0 = C.START.year
NYB = C.END.year - Y0 + 1                   # 청산 해 칸(2010~2026)


def _subs(spec, quick): return list(spec.QUICK_SUBS) if quick else list(spec.SUBS)
def _holds(spec, quick): return list(spec.QUICK_HOLDS) if quick else list(spec.HOLDS)


def family_counts(spec, quick=False):
    return {s: len(spec.cond_list(s)) * len(DELAY) * len(_holds(spec, quick)) * 2 for s in _subs(spec, quick)}


def _par(fn, argsets):
    """joblib 4코어. 프로세스 실행이 안 되는 환경(모듈을 못 찾는 등)이면 차례로 돈다."""
    argsets = list(argsets)
    if NJ > 1 and len(argsets) > 1:
        try: return Parallel(n_jobs=NJ)(delayed(fn)(*a) for a in argsets)
        except Exception as e: print('joblib 실패 → 차례로 계산:', repr(e)[:200])
    return [fn(*a) for a in argsets]


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
def run_part(spec, i, n, quick=False):
    D = C.Data(); ctx = spec.make_ctx(D); holds = _holds(spec, quick); out = {'track': spec.TRACK, 'quick': bool(quick), 'subs': {}}
    ss = (_subs(spec, True) if i == 1 else []) if quick else [s for k, s in enumerate(spec.SUBS) if k % n == (i - 1) % n]
    for s in ss:
        M = spec.build_M(D, ctx, s)
        if M.shape != (len(spec.cond_list(s)), D.n): raise RuntimeError(f'{s}: 조건 마스크 크기가 SPEC 과 다름 {M.shape}')
        chunks = [c for c in np.array_split(np.arange(len(M)), NJ * 2) if len(c)]
        res = _par(_thin_rows, [(M[c], holds, D.n) for c in chunks])
        segs = [x for r in res for x in r]
        out['subs'][s] = {'S': np.concatenate(segs) if segs else np.zeros(0, np.int16), 'cnt': np.asarray([len(x) for x in segs], dtype=np.int32), 'nsig': M.sum(1).astype(np.int32)}
        print(f'{spec.TRACK} 조각 {i}/{n}: {s} 조건 묶음 {len(M):,}개 · 신호일 합 {int(M.sum()):,}', flush=True)
    return out


# ------------------------------------------------------------------ 고르기·채점 (실제·가짜 공통) — T1 과 같음
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
SH_KO = {'goal': '통과 꼴(적중 85% 이상)', 'watch': '관찰 꼴(적중 80% 이상)'}
CN_KO = {1: '윌슨 하한 상위 1개', 5: '상위 5개', 20: '상위 20개', 0: '고른 것 전부'}
HOW_KO = {'any': '하나라도 켜진 날 매수(그 규칙 보유일)', 'cons': '쓰는 규칙의 20% 이상이 함께 켜진 날 매수(보유일 가운뎃값)'}


def proc_id(p): return f"WF_{p[1]}_{'all' if p[2] == 0 else 'top%d' % p[2]}_{p[3]}_{p[0]}"


def proc_desc(spec, p):
    return f"[{spec.ROOT}] 해마다 그 전 자료에서 {SH_KO[p[1]]} 규칙을 골라 {CN_KO[p[2]]} 사용 · {HOW_KO[p[3]]} → {'오름' if p[0] == 'up' else '내림'}"


def _pc(k, n): return '–' if n < 10 else f'{100 * k / n:.1f}%'


def md_table(df):
    out = ['| ' + ' | '.join(map(str, df.columns)) + ' |', '|' + '---|' * len(df.columns)]
    return out + ['| ' + ' | '.join(str(v) for v in r) + ' |' for r in df.values.tolist()]


# ------------------------------------------------------------------ merge
def merge(spec, parts, quick=False):
    """조각을 합쳐 (cands, meta, tabs) 를 돌려준다. 조각이 하나라도 없거나 다른 꼴이면 멈춘다(조용히 넘기지 않음). tabs = {표 파일 이름: DataFrame}."""
    D = C.Data(); ctx = spec.make_ctx(D); holds = _holds(spec, quick); nH = len(holds); n = D.n
    if max(holds) > MAXH: raise RuntimeError('보유일이 계산 틀의 한도(10일)를 넘음')
    parts = list(parts or []); good = lambda p: p is not None and p.get('track') == spec.TRACK and bool(p.get('quick')) == bool(quick)
    need = [1] if quick else list(range(1, spec.n_parts() + 1)); have = {}
    for i in need:
        p = parts[i - 1] if i - 1 < len(parts) else None
        if not good(p): raise RuntimeError(f'{spec.TRACK}: 조각 {i}/{len(need)} 결과가 없거나 꼴이 다름 — 합치지 않고 멈춤')
        have.update(p['subs'])
    subs = _subs(spec, quick); miss = [s for s in subs if s not in have]
    if miss: raise RuntimeError(f'{spec.TRACK}: 작은 가족 {miss} 의 조각 결과가 없음 — 합치지 않고 멈춤')
    fam = {spec.SUB_KO[s]: len(spec.cond_list(s)) * len(DELAY) * nH * 2 for s in subs}; n_tested = int(sum(fam.values()))
    notes = [f"가족 {len(subs)}개, 시험한 규칙 {n_tested:,}개(방향 포함)." + (' [quick 시험: 가족·보유일 일부, 가짜 5번]' if quick else ''),
             'fixed 후보는 전체 기간 성적을 보고 고른 것(방향별 적중 상위 100개 + 연구소 규칙)이라 다음 해 성적이 아니다. 믿을 숫자는 wf 절차 28개.']
    meta = {'n_tested': n_tested, 'families': fam, 'm_fixed': n_tested, 'm_wf': len(PROCS), 'not_included': list(spec.NOT_INCLUDED), 'parts_failed': [], 'notes': notes, 'tables': []}

    # 규칙(방향 빼고) 표와 조건 마스크
    Ms = []; attr = []; cs0 = 0; Sl = []; cl_ = []
    for s in subs:
        cl = spec.cond_list(s); M = spec.build_M(D, ctx, s); Ms.append(M)
        if len(have[s]['cnt']) != len(cl) * len(DELAY) * nH: raise RuntimeError(f'{s}: 조각의 규칙 수가 SPEC 과 다름')
        if not np.array_equal(have[s]['nsig'], M.sum(1).astype(np.int32)): raise RuntimeError(f'{s}: 조각을 만들 때와 조건 마스크가 다름(자료·코드가 바뀜)')
        for ci, t in enumerate(cl):
            for d in DELAY:
                for h in holds: attr.append((s, t, d, h, cs0 + ci))
        cs0 += len(cl); Sl.append(have[s]['S'].astype(np.int64)); cl_.append(have[s]['cnt'].astype(np.int64))
    M = np.concatenate(Ms); S = np.concatenate(Sl); cnt = np.concatenate(cl_); nb = len(attr); off = np.r_[0, np.cumsum(cnt)]
    hold = np.asarray([t[3] for t in attr], dtype=np.int64); delay = np.asarray([t[2] for t in attr], dtype=np.int64); cs = np.asarray([t[4] for t in attr], dtype=np.int64)
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

    rid = lambda j, direction: spec.rule_id(attr[j][0], attr[j][1], attr[j][2], attr[j][3], direction)
    rdesc = lambda j, direction: spec.rule_desc(attr[j][0], attr[j][1], attr[j][2], attr[j][3], direction)
    cands = []
    # ---- wf 절차 28개
    T_fake = []
    for pi, p in enumerate(PROCS):
        s, h = real['trades'][p]; ok = s + h < n; direction = 1 if p[0] == 'up' else -1
        tr = pd.DataFrame({'signal': D.td[s[ok]], 'exit': D.td[(s + h)[ok]]})
        cands.append({'id': proc_id(p), 'family': 'wf 절차', 'desc': proc_desc(spec, p), 'direction': direction, 'hold': None, 'kind': 'wf', 'trades': tr, 'root': spec.ROOT,
                      'params': {'shape': p[1], 'count': p[2], 'how': p[3]}})
        rn, rk = map(int, real['proc'][pi]); fn = FP[:, pi, 0]; fh = np.where(fn > 0, FP[:, pi, 1] / np.maximum(fn, 1), np.nan); v = fh[fn >= 10]
        rh = rk / rn if rn else np.nan
        q = (lambda x: f'{100 * np.quantile(v, x):.1f}%') if len(v) else (lambda x: '–')
        T_fake.append({'절차': proc_id(p), '설명': proc_desc(spec, p), '실제 독립 거래': rn, '실제 다음 해 적중': _pc(rk, rn), '가짜 평균 거래': round(float(fn.mean()), 1),
                       '가짜 적중 평균': (f'{100 * v.mean():.1f}%' if len(v) else '–'), '가짜 5%': q(0.05), '가짜 50%': q(0.5), '가짜 95%': q(0.95),
                       '가짜가 실제 이상인 비율': (round(float((1 + np.nansum(fh >= rh - 1e-12)) / (1 + nf)), 3) if rn >= 10 else '–'), '가짜 횟수': nf})
    T_fake = pd.DataFrame(T_fake)
    T_year = pd.DataFrame([{'절차': proc_id(p), **{str(y): '/'.join(map(str, real['by'][p].get(y, (0, 0)))) for y in years}} for p in PROCS])

    # ---- 고른 규칙 수: 실제 대 가짜
    rows = []
    for r_ in real['sel']:
        di = 0 if r_['dir'] == 'up' else 1; si = [s_ for s_, _ in SHAPES].index(r_['shape']); yi = years.index(r_['year']); f = FS[:, di, si, yi]
        row = {'해': r_['year'], '방향': '오름' if di == 0 else '내림', '꼴': SH_KO[r_['shape']], '최소 거래 수': r_['n_min'], '거래 수 채운 규칙': r_['n_enough'], '고른 규칙 수(실제)': r_['n_sel'],
               '고른 규칙 수(가짜 평균)': round(float(f.mean()), 1), '가짜 95%': round(float(np.quantile(f, 0.95)), 1)}
        if r_.get('top_j') is not None:
            j = r_['top_j']; row.update({'1위 규칙': rdesc(j, 1 if di == 0 else -1), '1위 그때까지 거래': r_['top_n'], '1위 그때까지 적중': _pc(r_['top_k'], r_['top_n'])})
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
    sj = np.asarray([t[0] for t in attr])
    T_fam = pd.DataFrame([{'가족': spec.SUB_KO[s], '시험한 가짓수(방향 2 포함)': fam[spec.SUB_KO[s]], '독립 10건 이상': int(2 * ((sj == s) & (tn >= 10)).sum()), '독립 35건 이상': int(2 * ((sj == s) & (tn >= 35)).sum()),
                           '조건 묶음당 평균 신호일': round(float(have[s]['nsig'].mean()), 1)} for s in subs])

    # ---- fixed: 방향별 적중 상위 100개(독립 35건 이상) + 연구소 규칙
    jof = {attr[j][:4]: j for j in range(nb)}
    def fixed_cand(j, direction, family):
        a_ = attr[j]; pos = np.flatnonzero(M[a_[4]])
        return {'id': rid(j, direction), 'family': family, 'desc': rdesc(j, direction), 'direction': direction, 'hold': int(a_[3]), 'kind': 'fixed', 'root': spec.ROOT,
                'trades': D.trades_from_pos(pos, int(a_[3]), int(a_[2])), 'params': spec.rule_params(a_[0], a_[1], a_[2], a_[3])}
    seen = set(); lab_missing = []
    for nm, t, main in spec.LAB:
        if t not in jof:
            if not quick: raise RuntimeError(f'연구소 규칙 {nm} 이 가족 안에 없음 — SPEC 과 코드가 어긋남')
            lab_missing.append(nm); continue
        if main:
            c_ = fixed_cand(jof[t], 1, '연구소 규칙'); c_['desc'] = f'(연구소 규칙 — {nm}) ' + c_['desc']; c_['lab'] = nm; cands.append(c_); seen.add(c_['id'])
    for di, dn in enumerate(('up', 'dn')):
        K = real['K'][dn]; tk = K[:, -1]; idx = np.flatnonzero(tn >= 35)
        o = idx[np.lexsort((idx, -tn[idx], -(tk[idx] / tn[idx])))][:100]
        for j in o:
            c_ = fixed_cand(int(j), 1 if di == 0 else -1, spec.SUB_KO[attr[j][0]])
            if c_['id'] not in seen: cands.append(c_); seen.add(c_['id'])

    # ---- 연구소 규칙이 해마다 뽑혔는지와 그 해 성적
    rows = []; Ku = real['K']['up']
    for nm, t, main in spec.LAB:
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
    md = [f'### {spec.TRACK.upper()} 따로 낸 표' + (' [quick 시험]' if quick else ''), '',
          f'시험한 규칙 {n_tested:,}개(방향 포함), 해마다 고르는 절차 {len(PROCS)}개, 가짜 {nf}번(수익률 줄을 해 안에서만 통째로 돌림).', '',
          '#### (1) 가족별 가짓수', ''] + md_table(T_fam) + ['',
          '#### (2) 전체 기간에 통과 숫자를 채운 규칙 수 — 실제 대 가짜 (우연히도 이만큼은 나온다)', ''] + md_table(T_ins) + ['',
          '#### (3) 해마다 고르는 절차의 다음 해 적중 — 실제 대 가짜', '', '가짜에서도 같은 절차로 고르고 채점했다. 실제가 가짜 95% 선보다 높아야 우연이 아니라고 볼 수 있다. 독립 거래 10건 미만은 %를 적지 않는다.', '']
    md += md_table(T_fake.drop(columns=['절차', '가짜 횟수'])) + ['', '#### (4) 절차별 해마다 (독립 거래 수/맞은 수)', ''] + md_table(T_year) + ['']
    if len(T_sel):
        g = T_sel.groupby(['방향', '꼴'], sort=False).agg(**{'고른 규칙 수(실제, 해 평균)': ('고른 규칙 수(실제)', 'mean'), '고른 규칙 수(가짜 평균, 해 평균)': ('고른 규칙 수(가짜 평균)', 'mean')}).round(1).reset_index()
        md += ['#### (5) 해마다 고른 규칙 수 — 실제 대 가짜 (해별 표는 tables 의 wf_sel_counts.csv)', ''] + md_table(g) + ['']
    md += ['#### (6) 연구소 규칙 — 해마다 이 절차로 뽑혔는지와 그 해 성적', '', spec.LAB_NOTE, '']
    md += (md_table(T_labsum) if len(T_labsum) else ['- 이번 계산 범위에 해당 규칙 없음']) + ['']
    if lab_missing: md += [f"- quick 시험 범위 밖이라 빠진 연구소 규칙: {', '.join(lab_missing)}", '']
    if len(T_lab): md += md_table(T_lab[T_lab['규칙'].isin([nm for nm, _, main in spec.LAB if main])]) + ['']
    meta['summary_md'] = '\n'.join(md)
    tabs = {'family_counts.csv': T_fam, 'insample_counts.csv': T_ins, 'wf_fake.csv': T_fake, 'wf_by_year.csv': T_year, 'wf_sel_counts.csv': T_sel, 'lab_rule_by_year.csv': T_lab, 'lab_rule_summary.csv': T_labsum}
    meta['tables'] = list(tabs)
    if not quick and (not cands or n_tested <= 0): raise RuntimeError(f'{spec.TRACK}: 후보 0개 또는 가짓수 0 — 비정상이라 멈춤')
    return cands, meta, tabs


def write_out(track, meta, tabs):
    """표(out/tables/*.csv)와 요약(out/summary.md)을 쓴다."""
    od = os.path.join(C.track_dir(track), 'out'); os.makedirs(os.path.join(od, 'tables'), exist_ok=True)
    for k, df in tabs.items(): df.to_csv(os.path.join(od, 'tables', k), index=False, encoding='utf-8')
    open(os.path.join(od, 'summary.md'), 'w', encoding='utf-8').write(meta['summary_md'] + '\n')


def main(spec, merge_fn=None):
    """run.py 의 명령: --nparts · --part i/n · --merge · --quick. merge_fn(parts, quick) → (cands, meta, tabs) 를 주면 그것을 쓴다(덧붙일 것이 있는 줄기)."""
    a = C.parse_part()
    if a['nparts']:
        print(spec.n_parts())
    elif a['part']:
        i, n_ = a['part']; C.save_part(spec.TRACK, i, n_, run_part(spec, i, n_, quick=a['quick'])); print(f'조각 {i}/{n_} 저장')
    elif a['merge']:
        parts = C.load_parts(spec.TRACK, spec.n_parts())
        cands, meta, tabs = (merge_fn or (lambda p, q: merge(spec, p, q)))(parts, a['quick'])
        write_out(spec.TRACK, meta, tabs); C.save_result(spec.TRACK, cands, meta)
        print(f"후보 {len(cands)}개 · 시험 {meta['n_tested']:,}가지 · wf 절차 {meta['m_wf']}개")
    else:
        print('사용: --nparts | --part i/n | --merge [--quick]')
