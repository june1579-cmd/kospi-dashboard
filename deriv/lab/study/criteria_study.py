#!/usr/bin/env python
"""통과 기준 검증 · 통과 신호 합치기 연구 (사용자 요청 2026-11-23).

읽기 전용: 연구소 후보(candidates.pkl)와 가격만 읽는다. 판정(A8)·반증(A10)·설정·상태 파일은 건드리지 않고, 결과는 deriv/lab/study/out/ 에만 쓴다.
거래 정의는 A8 과 같다(honest_trades → independent → 신호 다음 거래일 시가 진입 · exit 날 종가 청산, 코스피200 선물, 비용 제외).

하는 일
  1) 저장된 모든 후보(갈래 A·B·D 최근 라운드)를 모아 같은 거래는 하나로 줄이고, 거래가 많이 겹치는 것끼리 '계열'로 묶는다.
  2) 통과 기준 격자(전체 거래 수 × 적중률 × 앞·뒤 조건, 윌슨 하한형, 수익 조건형)마다 실제 통과 수를 세고,
     우연만으로 몇 개가 통과하는지 두 가지 위약으로 잰다.
       · 전체 이동: 신호 전체를 1년 이상 통째로 옮김(무작위) → 신호와 수익 사이 연결을 모두 끊음
       · 가까운 이동: 신호 전체를 ±20~120거래일 옮김 → 큰 장세는 남기고 '정확한 시점'만 흐림
  3) 한쪽 구간에서 고른 것이 다른 구간에서 얼마나 유지되는지(옮겨 가기) 표.
  4) 해마다 그때까지 자료로 기준을 적용해 고르고 다음 해에 매매하는 모의(전진 모의) — 기준별 다음 해 적중·수익.
  5) 통과 신호 합치기: 하나씩(먼저 온 것) · 둘 이상 겹칠 때만 · 겹치는 수에 따른 적중.
"""
import glob
import json
import math
import os
import pickle
import sys
import time
import multiprocessing as mp

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__)); LAB = os.path.dirname(HERE)
sys.path.insert(0, LAB)
os.environ['LAB_TRACK'] = ''   # 공통 코드는 갈래 A 설정을 '읽기만' 한다
import lab_common as L  # noqa: E402
from a08_validate import honest_trades, independent  # noqa: E402

OUT = os.path.join(HERE, 'out'); os.makedirs(OUT, exist_ok=True)
QUICK = os.environ.get('STUDY_QUICK') == '1'          # 로컬 점검용: 갈래마다 마지막 라운드만, 위약 조금만
B_GLOBAL = int(os.environ.get('STUDY_B', '40' if QUICK else '1000'))
SEED = 20261123
TRACKS = [('A', 'out'), ('B', 'out_b'), ('D', 'out_d'), ('C', 'out_c')]
START = pd.Timestamp('2010-01-01')
Z = 1.645                                             # 윌슨 하한(한쪽 95%) — lab_common.wilson 과 같음
MIN_N = 15

FUT = L.prices()['K200F']; TD = FUT.index; N = len(TD)
O = FUT['open'].values.astype(float); C = FUT['close'].values.astype(float)
YEAR = TD.year.values
I0 = int(TD.searchsorted(START))                      # 2010년 첫 거래일 위치
W = N - I0                                            # 위약에서 돌리는 창 길이
J_DEV = int(TD.searchsorted(L.DEV_END, side='right')) - 1   # 앞 구간 마지막 거래일 위치
P_HOLD = int(TD.searchsorted(L.HOLD_START))           # 뒤 구간 첫 거래일 위치


def log(*a):
    print(time.strftime('%H:%M:%S'), *a, flush=True)


# ------------------------------------------------------------------ 1) 후보 모으기
def load_pool():
    latest, raw = {}, 0
    for tk, d in TRACKS:
        rds = sorted(glob.glob(os.path.join(LAB, d, 'round_*')))
        if QUICK: rds = rds[-1:]
        for rd in rds:
            for f in sorted(glob.glob(os.path.join(rd, '*', 'candidates.pkl'))):
                try:
                    cc = pickle.load(open(f, 'rb'))
                except Exception as e:
                    log('읽기 실패', f, e); continue
                for c in cc:
                    raw += 1; latest[(tk, c['id'])] = (c, os.path.basename(rd))
    log('저장 후보(중복 포함)', raw, '· 갈래×이름 기준', len(latest))
    j_common = N - 15                                  # 중복 판정은 마지막 15거래일을 빼고(갈래마다 자료 끝이 달라서)
    seen, meta, ents, exts, rets = {}, [], [], [], []
    for (tk, cid), (c, rd) in latest.items():
        try:
            both = honest_trades(c)[2]
            t = both[(both['signal'] >= START) & (both['exit'] <= TD[-1])].dropna()
            if len(t) < 5: continue
            t = independent(t)
            ent = TD.searchsorted(t['signal'].values, side='right'); ext = TD.get_indexer(pd.DatetimeIndex(t['exit']))
        except Exception as e:
            log('거래 계산 실패', cid, e); continue
        ok = (ent < N) & (ext >= 0) & (ent <= ext)
        ent, ext = ent[ok].astype(np.int64), ext[ok].astype(np.int64)
        d = int(c['direction'])
        r = d * (C[ext] / O[ent] - 1) * 100
        ok = np.isfinite(r); ent, ext, r = ent[ok], ext[ok], r[ok]
        if len(ent) < 5: continue
        cm = ext <= j_common
        key = (d, ent[cm].tobytes(), ext[cm].tobytes())
        m = dict(id=cid, desc=c.get('desc', ''), agent=c.get('agent', ''), family=str(c.get('family', '')), direction=d,
                 fit=c.get('fit_period', 'p1') or 'p1', regime=bool(c.get('regime')), tracks=tk, round=rd, n=int(len(ent)))
        if key in seen:
            k = seen[key]
            if tk not in meta[k]['tracks']: meta[k]['tracks'] += tk
            meta[k]['dups'] = meta[k].get('dups', 1) + 1
            if len(ent) > len(ents[k]): ents[k], exts[k], rets[k] = ent, ext, r; meta[k]['n'] = int(len(ent))
            if m['fit'] == 'p1' and meta[k]['fit'] != 'p1':   # 같은 거래면 앞 구간에서 정한 쪽 이름을 남김
                meta[k].update(id=cid, desc=m['desc'], agent=m['agent'], family=m['family'], fit='p1')
            continue
        seen[key] = len(meta); meta.append(m); ents.append(ent); exts.append(ext); rets.append(r)
    return meta, ents, exts, rets


def wilson_lb(k, n):
    n_ = np.maximum(n, 1).astype(float); p = k / n_
    d = 1 + Z * Z / n_; c = p + Z * Z / (2 * n_); h = Z * np.sqrt(p * (1 - p) / n_ + Z * Z / (4 * n_ * n_))
    return np.where(n > 0, (c - h) / d, 0.0)


# ------------------------------------------------------------------ 기준 격자
def make_grid():
    G = []
    for n in (20, 25, 30, 35, 40, 45, 50, 60):
        for h in (0.70, 0.75, 0.80, 0.85, 0.90):
            G.append(dict(N=n, H=h, pn=12, ph=round(h - 0.05, 2)))
            G.append(dict(N=n, H=h, pn=0, ph=0.0))
    for n in (30, 35, 40):
        for pn, ph in ((12, 0.75), (12, 0.70), (15, 0.80), (8, 0.80), (12, 0.85)):
            G.append(dict(N=n, H=0.85, pn=pn, ph=ph))
    for lb in (0.60, 0.65, 0.70, 0.73, 0.75, 0.78):
        for pn, ph in ((12, 0.80), (12, 0.75), (0, 0.0)):
            G.append(dict(N=30, H=0.0, lb=lb, pn=pn, ph=ph))
    for mr in (0.5, 1.0):
        G.append(dict(N=35, H=0.85, pn=12, ph=0.80, mr=mr))
    for g in G:
        g.setdefault('lb', None); g.setdefault('mr', None)
        g['name'] = (f"하한{g['lb']:.2f}·{g['N']}거래" if g['lb'] is not None else f"{g['N']}거래·{g['H'] * 100:.0f}%") + \
                    (f"·앞뒤{g['pn']}거래{g['ph'] * 100:.0f}%" if g['pn'] else '·앞뒤조건없음') + (f"·평균수익{g['mr']}%" if g['mr'] else '')
    return G


def derived(n1, k1, n2, k2, s):
    n = n1 + n2; k = k1 + k2
    with np.errstate(divide='ignore', invalid='ignore'):
        h = np.where(n > 0, k / np.maximum(n, 1), 0.0); h1 = np.where(n1 > 0, k1 / np.maximum(n1, 1), 0.0); h2 = np.where(n2 > 0, k2 / np.maximum(n2, 1), 0.0)
        mr = np.where(n > 0, s / np.maximum(n, 1), 0.0)
    return dict(n=n, k=k, h=h, h1=h1, h2=h2, n1=n1, n2=n2, lb=wilson_lb(k, n), mr=mr)


def crit_pass(g, D, scale=1.0):
    nreq = g['N'] if scale >= 1 else max(MIN_N, math.ceil(g['N'] * scale))
    ok = D['n'] >= nreq
    ok &= (D['lb'] >= g['lb']) if g['lb'] is not None else (D['h'] >= g['H'])
    if g['pn']: ok &= (D['n1'] >= g['pn']) & (D['h1'] >= g['ph']) & (D['n2'] >= g['pn']) & (D['h2'] >= g['ph'])
    if g['mr']: ok &= D['mr'] >= g['mr']
    return ok


# ------------------------------------------------------------------ 계열 묶기(보유일이 겹치는 정도)
def in_market(idx, PTR, ENT, EXT):
    M = np.zeros((len(idx), N + 1), np.int16)
    for a, i in enumerate(idx):
        sl = slice(PTR[i], PTR[i + 1])
        np.add.at(M[a], ENT[sl], 1); np.add.at(M[a], EXT[sl] + 1, -1)
    return np.cumsum(M, axis=1)[:, :N] > 0


def cluster(idx, DIRC, PTR, ENT, EXT, thr=0.35):
    """보유일 자카드 ≥ thr 이고 방향이 같으면 같은 계열. idx 는 대표가 될 차례대로."""
    IM = in_market(idx, PTR, ENT, EXT).astype(np.float32); days = IM.sum(1); dr = DIRC[idx]
    lab = np.zeros(len(idx), np.int64); reps = []
    CH = 1500
    for a0 in range(0, len(idx), CH):
        X = IM[a0:a0 + CH]; n0 = len(reps); ra = np.array(reps, np.int64)
        S0 = X @ IM[ra].T if n0 else np.zeros((len(X), 0), np.float32)
        S1 = X @ X.T; new = []
        for b in range(len(X)):
            g = a0 + b; best, bj = -1, 0.0
            if n0:
                ov = S0[b]; jac = ov / np.maximum(days[g] + days[ra] - ov, 1); jac[dr[ra] != dr[g]] = 0
                j = int(jac.argmax())
                if jac[j] >= thr: best, bj = j, jac[j]
            if new:
                na = np.array(new, np.int64); ov = S1[b, na]; jac = ov / np.maximum(days[g] + days[a0 + na] - ov, 1); jac[dr[a0 + na] != dr[g]] = 0
                j = int(jac.argmax())
                if jac[j] >= thr and jac[j] > bj: best = n0 + j
            if best < 0:
                best = len(reps); reps.append(g); new.append(b)
            lab[g] = best
    return lab


# ------------------------------------------------------------------ 위약(신호 전체를 같은 폭으로 옮김)
_G = {}


def _null_chunk(args):
    shifts, wrap = args
    CI, ENT, EXT, DIRT, K, GRID, FAM = _G['CI'], _G['ENT'], _G['EXT'], _G['DIRT'], _G['K'], _G['GRID'], _G['FAM']
    cnt = np.zeros((len(shifts), len(GRID)), np.int32); fam = np.zeros_like(cnt)
    for b, ks in enumerate(shifts):
        if wrap:
            e = I0 + (ENT - I0 + ks) % W; x = I0 + (EXT - I0 + ks) % W; ok = (e <= x) & (e > I0)
        else:
            e = ENT + ks; x = EXT + ks; ok = (e > I0) & (x < N); e = np.clip(e, 0, N - 1); x = np.clip(x, 0, N - 1)
        r = DIRT * (C[x] / O[e] - 1) * 100; ok &= np.isfinite(r); hit = ok & (r > 0)
        p1 = ok & (x <= J_DEV); p2 = ok & (e > P_HOLD); pa = p1 | p2
        D = derived(np.bincount(CI[p1], minlength=K), np.bincount(CI[p1 & hit], minlength=K), np.bincount(CI[p2], minlength=K),
                    np.bincount(CI[p2 & hit], minlength=K), np.bincount(CI[pa], weights=r[pa], minlength=K))
        for gi, g in enumerate(GRID):
            m = crit_pass(g, D); c = int(m.sum()); cnt[b, gi] = c
            if c: fam[b, gi] = len(np.unique(FAM[m]))
    return cnt, fam


def run_null(shifts, wrap, procs):
    parts = [(list(shifts[i::procs]), wrap) for i in range(procs)]
    with mp.get_context('fork').Pool(procs) as p:
        res = p.map(_null_chunk, parts)
    return np.vstack([r[0] for r in res]), np.vstack([r[1] for r in res])


# ------------------------------------------------------------------ 반증(A10 과 같은 세 가지)
def redteam(ent, ext, r, rng):
    n = len(ent); hd = ext - ent + 1; h0 = float((r > 0).mean())
    off = rng.integers(20, 61, size=(300, n)) * np.where(rng.random((300, n)) < 0.5, 1, -1)
    i = np.clip((ent - 1)[None, :] + off, 0, N - hd[None, :] - 2)
    return i, hd, h0


def redteam_all(idx, PTR, ENT, EXT, RET, DIRC, rng):
    rows = {}
    for c in idx:
        sl = slice(PTR[c], PTR[c + 1]); ent, ext, r = ENT[sl], EXT[sl], RET[sl]; d = DIRC[c]
        per = (ext <= J_DEV) | (ent > P_HOLD); ent, ext, r = ent[per], ext[per], r[per]
        if len(ent) < 5: continue
        i, hd, h0 = redteam(ent, ext, r, rng)
        sim = d * (C[i + hd[None, :]] / O[i + 1] - 1); sh = (sim > 0).mean(1)
        p = float((sh >= h0).mean())
        yr = YEAR[ent - 1]; hit = r > 0; ys = np.unique(yr)
        loyo = min(float(hit[yr != y].mean()) for y in ys) if len(ys) > 1 else float('nan')
        conc = float(np.bincount(yr - yr.min()).max() / len(yr))
        rows[int(c)] = dict(p=p, loyo=loyo, conc=conc, ok=bool(p < 0.05 and loyo >= 0.70 and conc < 0.40))
    return rows


# ------------------------------------------------------------------ 거래 묶음 통계
def tstats(r, ent=None):
    r = np.asarray(r, float); n = len(r)
    if not n: return dict(n=0)
    w = r[r > 0]; l = r[r <= 0]
    out = dict(n=int(n), hit=round(float((r > 0).mean()), 4), mean=round(float(r.mean()), 3), median=round(float(np.median(r)), 3),
               avg_win=round(float(w.mean()), 3) if len(w) else None, avg_loss=round(float(l.mean()), 3) if len(l) else None,
               pf=round(float(w.sum() / -l.sum()), 2) if len(l) and l.sum() < 0 else None, worst=round(float(r.min()), 2),
               total=round(float((np.prod(1 + r / 100) - 1) * 100), 1), lb=round(float(wilson_lb(np.array([(r > 0).sum()]), np.array([n]))[0]), 4))
    if ent is not None:
        ent = np.asarray(ent); a = ent <= J_DEV; b = ent > P_HOLD
        out.update(n1=int(a.sum()), hit1=round(float((r[a] > 0).mean()), 4) if a.any() else None, n2=int(b.sum()), hit2=round(float((r[b] > 0).mean()), 4) if b.any() else None)
        yy = YEAR[ent]
        out['by_block'] = {f'{ya}~{yb}': [int(((yy >= ya) & (yy <= yb)).sum()), round(float((r[(yy >= ya) & (yy <= yb)] > 0).mean()), 3) if ((yy >= ya) & (yy <= yb)).any() else None]
                           for ya, yb in ((2010, 2013), (2014, 2017), (2018, 2021), (2022, 2026))}
        y26 = YEAR[ent] == 2026
        out.update(n_2026=int(y26.sum()), total_2026=round(float((np.prod(1 + r[y26] / 100) - 1) * 100), 1) if y26.any() else 0.0)
    return out


def one_at_a_time(ent, ext, r, src):
    """여러 신호를 한 줄로 세우고 보유 중에는 새 신호를 건너뜀(A8 independent 와 같은 규칙: 신호일 ≥ 앞 거래 청산일)."""
    o = np.lexsort((src, ent)); keep = []; last = -1
    for j in o:
        if ent[j] - 1 >= last: keep.append(j); last = ext[j]
    return np.array(keep, np.int64)


def agree_count(e, x, s, dirs, cap=7000):
    """진입일에, 같은 방향의 '다른 계열' 대표가 보유 중이거나 앞 3거래일 안에 진입한 수. 거래가 너무 많으면 건너뜀(None)."""
    if len(e) > cap: return None
    cnt = np.zeros(len(e), np.int64)
    for q in range(len(e)):
        oth = (s != s[q]) & (e <= e[q]) & ((x >= e[q]) | (e >= e[q] - 3)) & (dirs == dirs[q])
        if oth.any(): cnt[q] = len(np.unique(s[oth]))
    return cnt


def main():
    t0 = time.time(); rng = np.random.default_rng(SEED); procs = max(1, os.cpu_count() or 1)
    meta, ents, exts, rets = load_pool()
    K = len(meta); log('서로 다른 거래를 가진 후보', K)
    PTR = np.zeros(K + 1, np.int64); PTR[1:] = np.cumsum([len(e) for e in ents])
    ENT = np.concatenate(ents); EXT = np.concatenate(exts); RET = np.concatenate(rets)
    CI = np.repeat(np.arange(K), np.diff(PTR)); DIRC = np.array([m['direction'] for m in meta]); DIRT = DIRC[CI].astype(float)
    FIT2 = np.array([m['fit'] != 'p1' for m in meta])
    log('거래 수', len(ENT))

    # --- 실제 성적
    per1 = EXT <= J_DEV; per2 = ENT > P_HOLD; hit = RET > 0; pa = per1 | per2
    bc = lambda m, w=None: np.bincount(CI[m], weights=None if w is None else w[m], minlength=K)
    D = derived(bc(per1), bc(per1 & hit), bc(per2), bc(per2 & hit), bc(pa, RET))
    GRID = make_grid()

    # --- 계열: 전체 거래 15 이상만(그 밑은 어떤 기준도 못 넘음), 윌슨 하한 높은 순으로 대표
    elig = np.where(D['n'] >= MIN_N)[0]; elig = elig[np.argsort(-(D['lb'][elig] + 1e-6 * D['n'][elig]), kind='stable')]
    FAM = -np.arange(1, K + 1)
    lab = cluster(elig, DIRC, PTR, ENT, EXT); FAM[elig] = lab
    log('거래 15 이상 후보', len(elig), '· 계열', int(lab.max()) + 1, f'({time.time() - t0:.0f}s)')

    # --- 반증: 적중 80% 이상·30거래 이상이거나 하한 0.70 이상(격자의 높은 기준들이 닿는 범위)
    rt_idx = np.where(((D['n'] >= 20) & (D['h'] >= 0.80)) | ((D['n'] >= 30) & (D['lb'] >= 0.60)))[0]
    RT = redteam_all(rt_idx, PTR, ENT, EXT, RET, DIRC, rng)
    RTOK = np.zeros(K, bool); RTOK[[c for c, v in RT.items() if v['ok']]] = True
    log('반증 계산', len(RT), '· 버팀', int(RTOK.sum()))

    def rep_of(mask, score):
        """통과 후보를 계열마다 하나(점수 가장 높은 것)로."""
        p = np.where(mask)[0]
        if not len(p): return p
        o = np.lexsort((-score[p], FAM[p])); p = p[o]
        return p[np.r_[True, FAM[p][1:] != FAM[p][:-1]]]

    score = D['lb'] + 1e-6 * D['n']
    rows = []
    for g in GRID:
        m = crit_pass(g, D); mr = m & RTOK
        rows.append(dict(name=g['name'], N=g['N'], H=g['H'], lb=g['lb'], pn=g['pn'], ph=g['ph'], mr=g['mr'],
                         cand=int(m.sum()), fam=len(np.unique(FAM[m])), cand_up=int((m & (DIRC > 0)).sum()), cand_dn=int((m & (DIRC < 0)).sum()),
                         fam_dn=len(np.unique(FAM[m & (DIRC < 0)])), cand_rt=int(mr.sum()), fam_rt=len(np.unique(FAM[mr])),
                         cand_fitp2=int((m & FIT2).sum())))
    GR = pd.DataFrame(rows)

    # --- 위약
    sub = np.where(D['n'] >= 18)[0]; remap = -np.ones(K, np.int64); remap[sub] = np.arange(len(sub))
    tm = remap[CI] >= 0
    _G.update(CI=remap[CI][tm], ENT=ENT[tm], EXT=EXT[tm], DIRT=DIRT[tm], K=len(sub), GRID=GRID, FAM=FAM[sub])
    gs = rng.integers(250, W - 250, size=B_GLOBAL)
    cg, fg = run_null(gs, True, procs); log('전체 이동 위약', cg.shape, f'({time.time() - t0:.0f}s)')
    ls = np.array([s for s in range(-120, 121) if abs(s) >= 20]) if not QUICK else np.array([-60, -30, 30, 60])
    cl, fl = run_null(ls, False, procs); log('가까운 이동 위약', cl.shape, f'({time.time() - t0:.0f}s)')
    for nm, cc, ff in (('g', cg, fg), ('l', cl, fl)):
        GR[f'{nm}_cand_mean'] = cc.mean(0).round(2); GR[f'{nm}_fam_mean'] = ff.mean(0).round(2); GR[f'{nm}_fam_p95'] = np.percentile(ff, 95, axis=0)
        GR[f'{nm}_p_any'] = (ff >= 1).mean(0).round(3); GR[f'{nm}_p_ge_actual'] = (ff >= GR['fam'].values[None, :]).mean(0).round(3)
        GR[f'{nm}_fam_max'] = ff.max(0)

    # --- 옮겨 가기: 한쪽 구간 성적 → 다른 쪽 구간 성적
    tr_rows = []
    for src, dst, lab_, excl in (('1', '2', '앞→뒤', FIT2), ('2', '1', '뒤→앞', np.zeros(K, bool))):
        ns, hs, nd, hd = D['n' + src], D['h' + src], D['n' + dst], D['h' + dst]
        ks = bc(per1 & hit) if src == '1' else bc(per2 & hit); kd = bc(per2 & hit) if dst == '2' else bc(per1 & hit)
        for nmin in (12, 20, 30):
            for lo, hi in ((0.0, 0.60), (0.60, 0.70), (0.70, 0.75), (0.75, 0.80), (0.80, 0.85), (0.85, 0.90), (0.90, 1.01)):
                m = (~excl) & (ns >= nmin) & (hs >= lo) & (hs < hi) & (nd >= 12)
                if not m.any(): tr_rows.append(dict(way=lab_, src_n_min=nmin, src_hit=f'{lo:.2f}~{hi:.2f}', cand=0)); continue
                fam_h = pd.Series(hd[m]).groupby(FAM[m]).mean()
                tr_rows.append(dict(way=lab_, src_n_min=nmin, src_hit=f'{lo:.2f}~{hi:.2f}', cand=int(m.sum()), fam=int(len(fam_h)),
                                    dst_hit_pooled=round(float(kd[m].sum() / nd[m].sum()), 4), dst_hit_fam_mean=round(float(fam_h.mean()), 4),
                                    dst_share_ge80=round(float((fam_h >= 0.80).mean()), 4), dst_share_ge70=round(float((fam_h >= 0.70).mean()), 4),
                                    up_share=round(float((DIRC[m] > 0).mean()), 3)))
    TRF = pd.DataFrame(tr_rows)

    # --- 전진 모의: 해 T 끝까지 자료로 고르고 T+1 년에 매매
    wf_rows, wf_year = [], []
    okfit = ~FIT2
    first_of = lambda y: int(np.searchsorted(YEAR, y)); last_of = lambda y: int(np.searchsorted(YEAR, y, side='right')) - 1
    acc = {g['name']: dict(sel=0, pool=[], oat=[], v2=[], years=0) for g in GRID}
    for T in range(2016, 2026):
        jT = last_of(T); jF = last_of(T - 3); pB = first_of(T - 2); jY = last_of(T + 1)
        known = EXT <= jT; a = known & (EXT <= jF); b = known & (ENT > pB); ab = a | b
        DT = derived(bc(a), bc(a & hit), bc(b), bc(b & hit), bc(ab, RET))
        sc = DT['lb'] + 1e-6 * DT['n']; scale = (T - 2010 + 1) / 16.9
        fwd = (ENT - 1 > jT) & (EXT <= jY)
        for g in GRID:
            m = crit_pass(g, DT, scale) & okfit
            reps = rep_of(m, sc); A = acc[g['name']]; A['sel'] += len(reps)
            row = dict(name=g['name'], year=T + 1, sel=len(reps), n=0)
            if len(reps):
                rm = np.zeros(K, bool); rm[reps] = True; tm_ = fwd & rm[CI]
                e, x, r, s = ENT[tm_], EXT[tm_], RET[tm_], CI[tm_]
                if len(e):
                    A['pool'].append(r)
                    keep = one_at_a_time(e, x, r, s); A['oat'].append(r[keep]); A['years'] += 1
                    # 둘 이상 겹침: 진입일에 다른 계열 대표가 보유 중(진입일 포함 앞 3거래일 안에 진입했거나 아직 보유)
                    if len(reps) > 1:
                        ac = agree_count(e, x, s, DIRC[s])
                        if ac is not None and (ac >= 1).any():
                            v = ac >= 1; kv = one_at_a_time(e[v], x[v], r[v], s[v]); A['v2'].append(r[v][kv])
                    row.update(n=int(len(keep)), hit=round(float((r[keep] > 0).mean()), 3), sum=round(float(r[keep].sum()), 2))
            wf_year.append(row)
    for g in GRID:
        A = acc[g['name']]; cat = lambda L_: np.concatenate(L_) if L_ else np.array([])
        p_, o_, v_ = cat(A['pool']), cat(A['oat']), cat(A['v2'])
        st = lambda r, pre: {pre + 'n': int(len(r)), pre + 'hit': round(float((r > 0).mean()), 4) if len(r) else None, pre + 'mean': round(float(r.mean()), 3) if len(r) else None,
                             pre + 'sum': round(float(r.sum()), 1) if len(r) else 0.0}
        wf_rows.append(dict(name=g['name'], wf_sel=A['sel'], wf_years=A['years']) | st(p_, 'wf_pool_') | st(o_, 'wf_oat_') | st(v_, 'wf_v2_'))
    GR = GR.merge(pd.DataFrame(wf_rows), on='name', how='left')

    # --- 구간 교차 모의: 2010~2026 을 네 구간으로 나눠, 세 구간 자료로 고르고 남은 한 구간에서 매매(전진 모의보다 시험 거래가 많음)
    BLOCKS = [(2010, 2013), (2014, 2017), (2018, 2021), (2022, 2026)]
    tb = np.full(len(ENT), -1, np.int64)
    for q, (ya, yb) in enumerate(BLOCKS): tb[(ENT - 1 >= first_of(ya)) & (EXT <= last_of(yb))] = q
    NB = [bc(tb == q) for q in range(4)]; KB = [bc((tb == q) & hit) for q in range(4)]; SB = [bc(tb == q, RET) for q in range(4)]
    cv_rows = []; accv = {g['name']: dict(sel=0, pool=[], oat=[], v2=[]) for g in GRID}
    for q, (ya, yb) in enumerate(BLOCKS):
        oth = [i for i in range(4) if i != q]
        n_ = sum(NB[i] for i in oth); k_ = sum(KB[i] for i in oth); s_ = sum(SB[i] for i in oth)
        DV = derived(n_, k_, np.zeros(K, np.int64), np.zeros(K, np.int64), s_); scv = DV['lb'] + 1e-6 * DV['n']
        yrs = sum(min(BLOCKS[i][1], 2026) - BLOCKS[i][0] + 1 for i in oth) - (0.1 if 3 in oth else 0); scale = yrs / 16.9
        for g in GRID:
            g0 = dict(g, pn=0); m = crit_pass(g0, DV, scale) & okfit
            if g['pn']:
                for i in oth: m &= (NB[i] >= 8) & (KB[i] >= g['ph'] * NB[i])
            reps = rep_of(m, scv); A = accv[g['name']]; A['sel'] += len(reps)
            if not len(reps): continue
            rm = np.zeros(K, bool); rm[reps] = True; tm_ = (tb == q) & rm[CI]
            e, x, r, s2 = ENT[tm_], EXT[tm_], RET[tm_], CI[tm_]
            if not len(e): continue
            A['pool'].append(r); keep = one_at_a_time(e, x, r, s2); A['oat'].append(r[keep])
            if len(reps) > 1:
                ac = agree_count(e, x, s2, DIRC[s2])
                if ac is not None and (ac >= 1).any():
                    v = ac >= 1; kv = one_at_a_time(e[v], x[v], r[v], s2[v]); A['v2'].append(r[v][kv])
            cv_rows.append(dict(name=g['name'], block=f'{ya}~{yb}', sel=len(reps), n=int(len(keep)), hit=round(float((r[keep] > 0).mean()), 3), sum=round(float(r[keep].sum()), 1)))
    rows2 = []
    for g in GRID:
        A = accv[g['name']]; cat = lambda L_: np.concatenate(L_) if L_ else np.array([])
        st = lambda r, pre: {pre + 'n': int(len(r)), pre + 'hit': round(float((r > 0).mean()), 4) if len(r) else None, pre + 'mean': round(float(r.mean()), 3) if len(r) else None,
                             pre + 'sum': round(float(r.sum()), 1) if len(r) else 0.0}
        rows2.append(dict(name=g['name'], cv_sel=A['sel']) | st(cat(A['pool']), 'cv_pool_') | st(cat(A['oat']), 'cv_oat_') | st(cat(A['v2']), 'cv_v2_'))
    GR = GR.merge(pd.DataFrame(rows2), on='name', how='left')
    pd.DataFrame(cv_rows).to_csv(os.path.join(OUT, 'cv_by_block.csv'), index=False, encoding='utf-8')
    log('구간 교차 모의 끝', f'({time.time() - t0:.0f}s)')

    # --- 격자 전체: 실제 자료에서 계열 대표를 '한 번에 하나'로 합쳤을 때(표본 안 성적 — 고른 자료로 잰 것이라 낙관적)
    rows3 = []
    valid_t = per1 | per2
    for g in GRID:
        for tag, m in (('is_', crit_pass(g, D)), ('isrt_', crit_pass(g, D) & RTOK)):
            reps = rep_of(m, score); o = {tag + 'fam': int(len(reps))}
            if len(reps):
                rm = np.zeros(K, bool); rm[reps] = True; tm_ = valid_t & rm[CI]
                e, x, r, s2 = ENT[tm_], EXT[tm_], RET[tm_], CI[tm_]; keep = one_at_a_time(e, x, r, s2); ts = tstats(r[keep], e[keep])
                o.update({tag + 'n': ts['n'], tag + 'hit': ts['hit'], tag + 'mean': ts['mean'], tag + 'total': ts['total'], tag + 'pf': ts['pf'], tag + 'worst': ts['worst'],
                          tag + 'hit1': ts.get('hit1'), tag + 'hit2': ts.get('hit2'), tag + 'n2026': ts.get('n_2026'), tag + 'days': int((x[keep] - e[keep] + 1).sum())})
            rows3.append(dict(name=g['name']) | o) if tag == 'is_' else rows3[-1].update(o)
    GR = GR.merge(pd.DataFrame(rows3), on='name', how='left')
    GR.to_csv(os.path.join(OUT, 'grid.csv'), index=False, encoding='utf-8')
    TRF.to_csv(os.path.join(OUT, 'transfer.csv'), index=False, encoding='utf-8')
    pd.DataFrame(wf_year).to_csv(os.path.join(OUT, 'wf_by_year.csv'), index=False, encoding='utf-8')
    log('전진 모의 끝', f'({time.time() - t0:.0f}s)')

    # --- 통과 신호 합치기(전체 기간, 실제 자료)
    def combo(mask, label):
        reps = rep_of(mask, score)
        res = dict(label=label, cand=int(mask.sum()), fam=int(len(reps)), reps=[])
        if not len(reps): return res
        E, X, R_, S = [], [], [], []
        for c in reps:
            sl = slice(PTR[c], PTR[c + 1]); e, x, r = ENT[sl], EXT[sl], RET[sl]; per = (x <= J_DEV) | (e > P_HOLD); e, x, r = e[per], x[per], r[per]
            res['reps'].append(dict(id=meta[c]['id'], desc=meta[c]['desc'], direction=int(DIRC[c]), fit=meta[c]['fit'], tracks=meta[c]['tracks'],
                                    members=int((mask & (FAM == FAM[c])).sum()), rt=RT.get(int(c)), hold_med=float(np.median(x - e + 1))) | tstats(r, e))
            E.append(e); X.append(x); R_.append(r); S.append(np.full(len(e), c))
        e, x, r, s = map(np.concatenate, (E, X, R_, S))
        k = one_at_a_time(e, x, r, s); res['one_at_a_time'] = tstats(r[k], e[k])
        yr = pd.Series(r[k]).groupby(YEAR[e[k]]).agg(['size', lambda v: float((v > 0).mean()), 'sum'])
        res['one_at_a_time_by_year'] = {int(y): [int(a_), round(b_, 2), round(float(c_), 1)] for y, (a_, b_, c_) in yr.iterrows()}
        res['all_trades_pooled'] = tstats(r)
        # 진입일에 보유 중이거나 앞 3거래일 안에 진입한 '다른 계열' 수
        cntv = agree_count(e, x, s, DIRC[s])
        if cntv is not None:
            res['by_agree'] = {str(v): tstats(r[cntv == v]) for v in sorted(set(cntv.tolist()))[:6]}
            for kk in (1, 2, 3):
                v = cntv >= kk
                if v.any():
                    kv = one_at_a_time(e[v], x[v], r[v], s[v]); res[f'agree_ge{kk}_one_at_a_time'] = tstats(r[v][kv], e[v][kv])
            v = cntv == 0
            if v.any():
                kv = one_at_a_time(e[v], x[v], r[v], s[v]); res['solo_one_at_a_time'] = tstats(r[v][kv], e[v][kv])
        # 겹칠 때 두 배: 하루 수익으로 계산(겹친 날은 포지션 합)
        return res

    cur = dict(N=35, H=0.85, pn=12, ph=0.80, lb=None, mr=None)
    key = [('현재(35거래·85%·앞뒤12거래80%)+반증', crit_pass(cur, D) & RTOK), ('현재 기준만(반증 전)', crit_pass(cur, D))]
    for nm, g in (('30거래·85%', dict(N=30, H=0.85, pn=12, ph=0.80)), ('40거래·85%', dict(N=40, H=0.85, pn=12, ph=0.80)), ('50거래·85%', dict(N=50, H=0.85, pn=12, ph=0.80)),
                  ('35거래·90%', dict(N=35, H=0.90, pn=12, ph=0.80)), ('35거래·80%·앞뒤75%', dict(N=35, H=0.80, pn=12, ph=0.75)), ('30거래·80%·앞뒤75%', dict(N=30, H=0.80, pn=12, ph=0.75)),
                  ('40거래·80%·앞뒤75%', dict(N=40, H=0.80, pn=12, ph=0.75)), ('50거래·80%·앞뒤75%', dict(N=50, H=0.80, pn=12, ph=0.75)),
                  ('35거래·75%·앞뒤70%', dict(N=35, H=0.75, pn=12, ph=0.70)), ('50거래·75%·앞뒤70%', dict(N=50, H=0.75, pn=12, ph=0.70)),
                  ('하한0.73·30거래·앞뒤80%', dict(N=30, H=0.0, lb=0.73, pn=12, ph=0.80)), ('하한0.70·30거래·앞뒤75%', dict(N=30, H=0.0, lb=0.70, pn=12, ph=0.75)),
                  ('하한0.65·30거래·앞뒤75%', dict(N=30, H=0.0, lb=0.65, pn=12, ph=0.75))):
        g.setdefault('lb', None); g.setdefault('mr', None)
        key.append((nm + '+반증', crit_pass(g, D) & RTOK)); key.append((nm + '(반증 전)', crit_pass(g, D)))
    COMBO = [combo(m, nm) for nm, m in key]

    # --- 현재 기준 통과 후보 전체 목록(계열 번호 포함)과 아슬아슬한 후보
    near = (D['n'] >= 25) & (D['h'] >= 0.78) & (D['n1'] >= 10) & (D['n2'] >= 10)
    rowsP = []
    for c in np.where(near)[0]:
        rowsP.append(dict(id=meta[c]['id'], desc=meta[c]['desc'], direction=int(DIRC[c]), fit=meta[c]['fit'], tracks=meta[c]['tracks'], fam=int(FAM[c]),
                          n=int(D['n'][c]), hit=round(float(D['h'][c]), 4), lb=round(float(D['lb'][c]), 4), n1=int(D['n1'][c]), hit1=round(float(D['h1'][c]), 4),
                          n2=int(D['n2'][c]), hit2=round(float(D['h2'][c]), 4), mean=round(float(D['mr'][c]), 3), cur_pass=bool(crit_pass(cur, D)[c]),
                          rt_p=RT.get(int(c), {}).get('p'), rt_loyo=RT.get(int(c), {}).get('loyo'), rt_conc=RT.get(int(c), {}).get('conc'), rt_ok=bool(RTOK[c])))
    pd.DataFrame(rowsP).sort_values(['cur_pass', 'lb'], ascending=False).to_csv(os.path.join(OUT, 'near_pass.csv'), index=False, encoding='utf-8')

    # --- 방향·보유 기간별 바탕 확률(아무 날에나 잡았을 때)
    base = {}
    for h in (1, 2, 3, 5, 10, 20):
        e = np.arange(I0 + 1, N - h); r = C[e + h - 1] / O[e] - 1
        base[str(h)] = dict(up=round(float((r > 0).mean()), 4), up_p1=round(float((r[e + h - 1 <= J_DEV] > 0).mean()), 4), up_p2=round(float((r[e > P_HOLD] > 0).mean()), 4))

    summ = dict(made=time.strftime('%Y-%m-%d %H:%M:%S'), quick=QUICK, data_end=str(TD[-1].date()), pool=dict(unique=K, trades=int(len(ENT)), elig15=int(len(elig)),
                families=int(lab.max()) + 1, up=int((DIRC > 0).sum()), down=int((DIRC < 0).sum()), fit_p2=int(FIT2.sum()),
                by_track={t: int(sum(t in m['tracks'] for m in meta)) for t in 'ABDC'}),
                null=dict(global_draws=int(len(gs)), local_shifts=int(len(ls))), base=base, combo=COMBO, redteam_n=len(RT), redteam_ok=int(RTOK.sum()))
    json.dump(summ, open(os.path.join(OUT, 'summary.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=lambda o: o.item() if hasattr(o, 'item') else str(o))
    log('끝', f'({time.time() - t0:.0f}s)')


if __name__ == '__main__':
    main()
