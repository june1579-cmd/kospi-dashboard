#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""turn_probe.py — 전환점 연구 (사용자 지시 2026-11-23).

"무작정 훑지 말고, 하락에서 상승으로·상승에서 하락으로 돌아설 때 공통으로 일어난 지수·수급 변화를 찾고,
 어떤 조합이 전환점을 가장 많이, 높은 확률로 찾아내고 성과를 내는지 본다."

1) 전환점을 먼저 정한다: 코스피200 선물 종가가 저점에서 5%(또는 8%) 이상 오르면 그 저점이 '하락→상승 전환점', 고점에서 그만큼 내리면 '상승→하락 전환점'.
2) 공통점(조건 1개): 전환점 직전 5일 / 당일 / 직후 3일에 그 조건이 켜져 있던 전환점의 비율을, 전환점 날짜를 통째로 옮긴 가짜와 비교한다(묶음별).
   + '많이 내린(오른) 날' 가운데 실제로 전환이 온 날에만 유독 겹쳐 있던 조건(진짜 전환과 계속 간 날을 가른 조건).
3) 조합(조건 1~3개, 빠짐없이): 조합이 켜진 날이 '앞 구간(전환점 3일 전~당일)' 또는 '뒤 구간(전환점 다음 날~3일 뒤)' 안인 비율과 찾아낸 전환점 수,
   그리고 켜진 뒤의 수익 방향을 센다. 조건 묶음별(전부 / 지수만 / 수급만 / 선물·옵션 구조만 / 지수 빼고 전부)로 따로 훑는다.
   해마다 그 해 이전 자료로만(전환점도 그때까지의 가격으로만 정해) 고르고, 그 해에 실제로 찾아냈는지·그 뒤 수익이 났는지 채점한다.
자료·조건은 deriv/combo 와 같다(통합 자료표, 학습 구간 분위 조건). 계산 핵심은 deriv/combo/combo.c.
"""
import argparse
import hashlib
import json
import os
import pickle
import sys
import time

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, '..', 'combo'))
import combo_core as K          # noqa: E402
from combo_probe import conditions, TRAIN_START, DEV_END, HOLD_START   # noqa: E402

TH = [0.05, 0.08]; LEADW = 3; CONFW = 3; PRE = 5
# (이름, 저점 L / 고점 H, 문턱, 구간, 솎는 간격)   앞 = 전환점 3일 전~당일(4거래일) · 뒤 = 전환점 다음 날~3일 뒤(3거래일)
ROWS = [('저점5앞', 'L', 0.05, '앞', 5), ('저점5뒤', 'L', 0.05, '뒤', 5), ('고점5앞', 'H', 0.05, '앞', 5), ('고점5뒤', 'H', 0.05, '뒤', 5),
        ('저점8앞', 'L', 0.08, '앞', 5), ('저점8뒤', 'L', 0.08, '뒤', 5), ('고점8앞', 'H', 0.08, '앞', 5), ('고점8뒤', 'H', 0.08, '뒤', 5),
        ('수익5일', None, None, None, 5), ('수익10일', None, None, None, 10), ('수익20일', None, None, None, 20)]
NW = 8; RET = [(8, 5), (9, 10), (10, 20)]; COMP = 9
# 규칙(값 12개): 최소 신호 수, 구간 안 비율, -,-,-,-, 찾은 전환점 수, 1 = 전환 구간 줄에만, 그 뒤 10일 방향 적중(저점 = 오름, 고점 = 내림), 그 거래 수
RULES = [('구간 안 50% 이상 · 8개 이상 찾음', [15, 0.50, 0, 0, 0, 0, 8, 1, 0, 0, 0, 0]),
         ('구간 안 35% 이상 · 8개 이상 찾음', [20, 0.35, 0, 0, 0, 0, 8, 1, 0, 0, 0, 0]),
         ('구간 안 25% 이상 · 10개 이상 찾음', [30, 0.25, 0, 0, 0, 0, 10, 1, 0, 0, 0, 0]),
         ('35%·8개 + 그 뒤 10일 방향 65% 이상(20거래)', [20, 0.35, 0, 0, 0, 0, 8, 1, 0.65, 20, 0, 0]),
         ('35%·8개 + 그 뒤 10일 방향 80% 이상(20거래)', [20, 0.35, 0, 0, 0, 0, 8, 1, 0.80, 20, 0, 0])]
TOPRULE = 1; PTOP = 0.35; KTOP = 100; KEEP = 40
MIN_RAW = 15; MIN_N = 15
CATS = {'price': '지수·가격', 'flow': '수급(투자자별 매매)', 'credit': '신용·미수·대주', 'futs': '선물 구조', 'opt': '옵션 구조', 'vol': '변동성 지수', 'us': '미국·해외·환율', 'cal': '달력'}
SETS = [('ALL', '전부', None), ('PRICE', '지수만', {'price'}), ('FLOW', '수급만', {'flow', 'credit'}), ('OPT', '선물·옵션 구조만', {'opt', 'futs'}), ('NOPX', '지수 빼고 전부', set(CATS) - {'price'})]


def cat_of(name):
    """지표 이름 → 묶음. '지수·가격' = 코스피·선물 자기 가격에서 나온 것(전환점 정의와 기계적으로 얽힌다)."""
    if name.startswith(('PK_', 'PF_')) and name != 'PF_베이시스%': return 'price'
    if name in ('BASE_오늘등락', 'BASE_5일등락', 'BASE_HV20', 'D_RSI14', 'D_SMA8/22%', 'US_k2_r1', 'US_k2_r5', 'NT_야간선물등락', 'K2_코스닥150선물_등락'): return 'price'
    if name.startswith('K_') or name == 'E1_만기까지일수' or name.endswith('_dte'): return 'cal'
    if name.startswith(('S_', 'F_', 'F2_', 'F4_', 'P1_', 'O1_', 'O2_', 'O3_', 'US_for_fut')): return 'flow'
    if name.startswith('K2_') and ('_외국인' in name or '_기관' in name): return 'flow'
    if name.startswith('C_') or name in ('D_대주_20d%', 'D_대주_순위', 'D_담보융자_20d%', 'D_RP_순위', 'D_대주/신용%'): return 'credit'
    if name.startswith(('B1_', 'M1_', 'T1_')) or name == 'PF_베이시스%' or (name.startswith('K2_') and '미결제' in name): return 'futs'
    if name.startswith(('OW_', 'E1_', 'G1_', 'R1_', 'V2_')) or name == 'US_k_pcr': return 'opt'
    if name.startswith(('V1_', 'M_VKOSPI', 'US_vix', 'US_vk', 'W_VIX')) or name in ('US_vvix', 'US_skew', 'US_vrp', 'US_vx_lev'): return 'vol'
    return 'us'


def zigzag(c, th):
    """종가 c 에서 th 이상 되돌린 고점·저점. 반환 [(위치, 'L' 또는 'H')] — 마지막 진행 중인 것은 넣지 않는다(아직 전환으로 확정되지 않음)."""
    piv = []; ok = np.where(np.isfinite(c))[0]
    if not len(ok): return piv
    lo = hi = int(ok[0]); mode = None
    for i in ok[1:]:
        i = int(i)
        if mode is None:
            if c[i] > c[hi]: hi = i
            if c[i] < c[lo]: lo = i
            if c[i] >= c[lo] * (1 + th) and lo < i: piv.append((lo, 'L')); mode = 'up'; hi = i
            elif c[i] <= c[hi] * (1 - th) and hi < i: piv.append((hi, 'H')); mode = 'dn'; lo = i
        elif mode == 'up':
            if c[i] > c[hi]: hi = i
            elif c[i] <= c[hi] * (1 - th): piv.append((hi, 'H')); mode = 'dn'; lo = i
        else:
            if c[i] < c[lo]: lo = i
            elif c[i] >= c[lo] * (1 + th): piv.append((lo, 'L')); mode = 'up'; hi = i
    return piv


def win_days(p, kind):
    return range(p - LEADW, p + 1) if kind == '앞' else range(p + 1, p + CONFW + 1)


def thin(days, h):
    out = []; last = -10 ** 6
    for d in days:
        if d - last >= h: out.append(int(d)); last = d
    return out


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--fit', required=True); ap.add_argument('--panel', default=os.path.join(HERE, '..', 'uni', 'out', 'panel.pkl'))
    ap.add_argument('--out', default=os.path.join(HERE, 'out')); ap.add_argument('--maxlevel', type=int, default=3); ap.add_argument('--null', type=int, default=2); ap.add_argument('--limit-cond', type=int, default=0)
    ap.add_argument('--sets', default=','.join(s[0] for s in SETS))
    a = ap.parse_args(); t_all = time.time()
    D = pickle.load(open(a.panel, 'rb')); X, P = D['X'], D['P']; td = X.index; F = P['K200F']; n = len(td)
    o = F['open'].values.astype(float); c_ = F['close'].values.astype(float)
    i0 = int(td.searchsorted(TRAIN_START)); full = a.fit.upper() == 'FULL'
    if full:
        i1 = n; test_start = i1 - i0; TE = test_start; split = int(td.searchsorted(HOLD_START)) - i0; tr_rows = (td >= TRAIN_START) & (td <= DEV_END); cut = n
    else:
        Y = int(a.fit); te = np.where(td.year == Y)[0]; i1 = te[-1] + 1; test_start = te[0] - i0; TE = test_start - 1; split = int(td.searchsorted(pd.Timestamp(f'{Y - 3}-01-01'))) - i0
        tr_rows = (np.arange(n) >= i0) & (np.arange(n) < te[0]); cut = te[0]
    T = i1 - i0; idx = td[i0:i1]; TT = T - test_start
    names, fid, Bt = conditions(X[tr_rows], X.iloc[i0:i1]); n_all = len(names)
    cnt = Bt[:TE].sum(0); seen = {}; keep = []
    for c in range(Bt.shape[1]):
        if cnt[c] < MIN_RAW: continue
        h_ = hashlib.md5(Bt[:, c].tobytes()).hexdigest()
        if h_ in seen: continue
        seen[h_] = c; keep.append(c)
    rng = np.random.default_rng(7); keep = np.array(keep)[rng.permutation(len(keep))]
    if a.limit_cond: keep = keep[:a.limit_cond]
    names = [names[c] for c in keep]; fid = fid[keep]; Bt = np.ascontiguousarray(Bt[:, keep]); C = len(keep)
    cat = np.array([cat_of(X.columns[f]) for f in fid])
    # ---- 전환점: 학습 구간 표지는 '시험 해 시작 전 가격'으로만 정한다(piv_tr 는 piv_all 의 앞부분과 같다). 시험 해 표지는 전체 가격으로.
    piv_tr = {th: zigzag(c_[:cut], th) for th in TH}; piv_all = {th: zigzag(c_, th) for th in TH}
    H = np.array([r[4] for r in ROWS], np.int32); nH = len(ROWS); val = np.full((nH, T), -1, np.int8); rowwin = np.zeros(nH, np.int32); ptop = np.zeros(nH); events = {}
    ret = {}
    for hi, (nm, typ, th, kind, h) in enumerate(ROWS):
        if typ:
            rowwin[hi] = 1 if typ == 'L' else 2; ptop[hi] = PTOP; v = np.zeros(T, np.int8)
            for p, t in piv_tr[th]:
                if t != typ: continue
                for d in win_days(p, kind):
                    if i0 <= d < i0 + TE: v[d - i0] = 1
            for p, t in piv_all[th]:
                if t != typ: continue
                for d in win_days(p, kind):
                    if i0 + test_start <= d < i1: v[d - i0] = 1
            val[hi] = v
            events[nm] = dict(n_train=int(sum(1 for p, t in piv_tr[th] if t == typ and i0 <= p < i0 + TE)), test=[int(p - i0 - test_start) for p, t in piv_all[th] if t == typ and i0 + test_start <= p < i1])
        else:
            r = np.full(n, np.nan); ii = np.arange(n)[np.arange(n) + h < n]; r[ii] = c_[ii + h] / o[ii + 1] - 1; rr = r[i0:i1]; ret[h] = rr
            val[hi] = np.where(np.isfinite(rr) & (rr > 0), 1, np.where(np.isfinite(rr) & (rr < 0), 0, -1))
    trend = np.array([(test_start - h) if not full else (T - (0 if rowwin[hi] else h)) for hi, h in enumerate(H)], np.int32)
    nB = a.null; valn = np.full((max(nB, 1), nH, T), -1, np.int8); shifts = rng.integers(250, TE - 250, size=max(nB, 1)); null_types = []; yr_loc = idx.year.values
    for b in range(nB):
        if b < (nB + 1) // 2: valn[b, :, :TE] = np.roll(val[:, :TE], int(shifts[b]), axis=1); null_types.append('global')
        else:
            for y in np.unique(yr_loc[:TE]):
                w = np.where(yr_loc[:TE] == y)[0]
                valn[b][:, w] = np.roll(val[:, w], int(rng.integers(len(w) // 4, max(3 * len(w) // 4, len(w) // 4 + 1))), axis=1) if len(w) >= 40 else val[:, w]
            null_types.append('year')
    R = np.array([r for _, r in RULES], float); L3 = min(a.maxlevel, 3); B = Bt.astype(bool)

    def fwd(days, h, lim):
        """days(오름차순) 가운데 lim 앞, 수익이 정해진 날을 h 일 간격으로 솎아 [거래, 오름, 평균 수익%]"""
        rr = ret[h]; out = []; last = -10 ** 6
        for d in days:
            if d >= lim or d - last < h or not np.isfinite(rr[d]) or rr[d] == 0: continue
            last = d; out.append(rr[d])
        return [len(out), int(sum(1 for x in out if x > 0)), round(float(np.mean(out)) * 100, 3) if out else 0.0]

    def detail(cid, hi, st8):
        """상위 표에 든 조합 하나를 파이썬으로 다시 세어(핵심 계산과 같은지 확인) 그 뒤 수익·시험 해 성적을 붙인다."""
        m = B[:, cid].all(axis=1); A = np.where(m[:TE])[0]; sig = [d for d in thin([d for d in A if d < trend[hi]], 5)]
        na = len(sig); ua = int(sum(val[hi][d] for d in sig)); assert (na, ua) == (st8[0], st8[1]), ('핵심 계산과 다름', cid, hi, na, ua, st8)
        e = dict(tr={f'f{h}': fwd(A, h, trend[h2]) for h2, h in RET}); f10 = e['tr']['f10']; up_ok = rowwin[hi] == 1
        assert (f10[0], f10[1] if up_ok else f10[0] - f10[1]) == (st8[4], st8[5]), ('그 뒤 10일 수익이 핵심 계산과 다름', cid, hi, f10, st8)
        if not full:
            E = np.where(m[test_start:])[0]; es = thin(E, 5); wv = val[hi, test_start:]; tk = int(sum(wv[d] for d in es)); assert (len(es), tk) == (st8[2], st8[3]), ('시험 구간이 핵심 계산과 다름', cid, hi)
            on = set(int(d) for d in E); kind = ROWS[hi][3]; evs = events[ROWS[hi][0]]['test']
            e['te'] = dict(sig=len(es), hit=tk, found=int(sum(1 for p in evs if any(d in on for d in win_days(p, kind)))), **{f'f{h}': fwd(E + test_start, h, T) for h2, h in RET}); g10 = e['te']['f10']
            assert (g10[0], g10[1] if up_ok else g10[0] - g10[1]) == (st8[6], st8[7]), ('시험 구간 10일 수익이 핵심 계산과 다름', cid, hi, g10, st8)
        else:
            yrs = sorted({int(yr_loc[d]) for d in sig if val[hi][d] == 1}); al = np.where(m)[0]
            e['years_hit'] = len(yrs); e['last'] = str(idx[al[-1]].date()) if len(al) else None; e['on'] = bool(m[-1])
            rec = thin([d for d in al if d >= T - 250], 5); e['recent'] = [[str(idx[d].date()), int(val[hi][d])] for d in rec[-6:]]
        return e

    out = dict(fit=a.fit, made=pd.Timestamp.now(tz='Asia/Seoul').strftime('%Y-%m-%d %H:%M'), features=int(X.shape[1]), cond_all=int(n_all), cond=int(C), days=int(T), train_days=int(TE), last_day=str(idx[-1].date()),
               rows=[r[0] for r in ROWS], H=[int(x) for x in H], rowwin=[int(x) for x in rowwin], rules=[nm for nm, _ in RULES], null_types=null_types, events=events, sets={},
               base_train={ROWS[hi][0]: [int((val[hi, :TE] >= 0).sum()), int((val[hi, :TE] == 1).sum())] for hi in range(nH)}, cat_count={k: int((cat == k).sum()) for k in CATS})
    if not full:
        out['test'] = [str(idx[test_start].date()), str(idx[-1].date())]; out['test_val'] = val[:, test_start:].astype(int).tolist()
        out['test_ret'] = {str(h): [None if not np.isfinite(x) else round(float(x) * 100, 3) for x in ret[h][test_start:]] for _, h in RET}
    for skey, slabel, scats in SETS:
        if skey not in a.sets.split(','): continue
        cols = np.arange(C) if scats is None else np.where(np.isin(cat, list(scats)))[0]
        if len(cols) < 3: continue
        res = K.scan(np.ascontiguousarray(Bt[:, cols]), fid[cols], H, trend, val, valn[:nB] if nB else valn[:0], R, TE, test_start, split, maxlevel=a.maxlevel, min_raw=MIN_RAW, min_n=MIN_N, K=KTOP,
                     rowwin=rowwin, ptop=ptop, comp=COMP, toprule=TOPRULE, top2_min_n=20)
        so = dict(label=slabel, cond=int(len(cols)), enum=[int(x) for x in res['enum'][1:4]], seconds=round(res['misc'][4] / 1000.0, 1), threads=int(res['misc'][3]),
                  sel=res['sel'][:L3, :, :NW, 0].tolist(), seln=res['seln'][:max(nB, 1), :L3, :, :NW, 0].tolist(), pool=res['pool'][:L3, :, :NW, 0].tolist(), xpool=res['xpool'][:L3, :, :NW, NW:].tolist())
        if not full: so['votes'] = res['votes'][:L3, :, :NW, 0].astype(int).tolist()
        for tkey, klb, kid, kst in (('top1', 'toplb', 'topid', 'topst8'), ('top2', 'top2lb', 'top2id', 'top2st')):
            tt = {}
            for hi in range(NW):
                cand = []
                for L in range(L3):
                    lb = res[klb][:, L, hi, 0].ravel(); ids = res[kid][:, L, hi, 0].reshape(-1, 4); st = res[kst][:, L, hi, 0].reshape(-1, K.NST)
                    cand += [(float(lb[q]), L + 1, [int(cols[i]) for i in ids[q] if i >= 0], [int(x) for x in st[q]]) for q in np.where(lb > 0)[0]]
                cand.sort(key=lambda x: (-x[0], x[1])); seen_h = set(); kept = []
                for sc, L, cid, st8 in cand:      # 켜진 날이 똑같은 조합(뜻 없는 조건이 하나 더 붙은 것)은 하나만 남긴다
                    hh = hashlib.md5(np.packbits(B[:, cid].all(axis=1)).tobytes()).digest()
                    if hh in seen_h: continue
                    seen_h.add(hh); kept.append(dict(L=L, score=round(sc, 4), names=[names[i] for i in cid], cats=[str(cat[i]) for i in cid], st=st8, **detail(cid, hi, st8)))
                    if len(kept) >= KEEP: break
                tt[ROWS[hi][0]] = kept
            so[tkey] = tt
        out['sets'][skey] = so
        print(skey, so['cond'], so['enum'], so['seconds'], flush=True)
    if full:
        # ---- 공통점(조건 1개): 전환점 직전 5일 / 당일 / 직후 3일에 켜져 있던 전환점의 비율 vs 전환점을 통째로 옮긴 가짜 300번. 묶음마다 위 12개.
        com = {}; rs = np.random.default_rng(11); sh = rs.integers(60, T - 60, size=300); dates = {}; evpos = {}
        for nm, typ, th in (('저점5', 'L', 0.05), ('고점5', 'H', 0.05), ('저점8', 'L', 0.08), ('고점8', 'H', 0.08)):
            ev = np.array([p - i0 for p, t in piv_all[th] if t == typ and i0 + PRE <= p < i1 - CONFW]); dates[nm] = [str(idx[p].date()) for p in ev]; evpos[nm] = ev
            for wn, (a0, a1) in (('직전 5일', (-PRE, -1)), ('당일', (0, 0)), ('직후 3일', (1, CONFW))):
                def cov(pos):
                    m = np.zeros((len(pos), C), bool)
                    for k in range(a0, a1 + 1): m |= B[np.clip(pos + k, 0, T - 1)]
                    return m.mean(0)
                real = cov(ev); nul = np.array([cov((ev + s) % T) for s in sh]); mu = nul.mean(0); sd = nul.std(0) + 1e-9; q95 = np.quantile(nul, 0.95, axis=0); z = (real - mu) / sd
                bycat = {}
                for k in CATS:
                    ii = np.where(cat == k)[0]; od = ii[np.argsort(-z[ii])][:12]
                    bycat[k] = [[names[i], round(float(real[i]), 3), round(float(mu[i]), 3), round(float(z[i]), 2)] for i in od]
                    bycat[k + '|n'] = [int(len(ii)), int((real[ii] > q95[ii]).sum())]
                com[f'{nm}|{wn}'] = dict(n_events=int(len(ev)), n_over95=int((real > q95).sum()), expect_over95=round(0.05 * C, 1), bycat=bycat)
        out['common'] = com; out['event_dates'] = dates
        # ---- 진짜 전환과 계속 간 날을 가른 조건: '선물 5일 등락 하위(상위) 20%'인 날 가운데, 3일 안에 실제 저점(고점)이 온 날에만 유독 겹쳐 있던 조건
        lift = {}; B32 = Bt.astype(np.float32)
        for nm, rowname, ctxname in (('저점5', '저점5앞', 'PF_등락_5d≤하위20%'), ('고점5', '고점5앞', 'PF_등락_5d≥상위20%')):
            if ctxname not in names: continue
            ci = names.index(ctxname); hi = [r[0] for r in ROWS].index(rowname); W = val[hi] == 1; ctx = B[:, ci]; cw = (ctx & W).astype(np.float32); c0 = ctx.astype(np.float32)
            a_real = B32.T @ cw; t_real = B32.T @ c0; pr = np.where(t_real > 0, a_real / np.maximum(t_real, 1), np.nan)
            nul = []
            for s in sh:
                a_s = B32.T @ np.roll(cw, int(s)); t_s = B32.T @ np.roll(c0, int(s)); nul.append(np.where(t_s > 0, a_s / np.maximum(t_s, 1), np.nan))
            nul = np.array(nul); mu = np.nanmean(nul, 0); sd = np.nanstd(nul, 0) + 1e-9; z = (pr - mu) / sd
            base_sig = thin(np.where(ctx)[0], 5); rows_ = {}
            for k in CATS:
                ii = [i for i in np.where(cat == k)[0] if fid[i] != fid[ci] and t_real[i] >= 20]; lst = []
                for i in ii:
                    sg = thin(np.where(ctx & B[:, i])[0], 5); hit = int(sum(W[d] for d in sg))
                    if hit < 10: continue
                    lst.append([names[i], len(sg), hit, round(float(z[i]), 2), fwd(np.where(ctx & B[:, i])[0], 10, T - 10)])
                lst.sort(key=lambda x: -x[3]); rows_[k] = lst[:8]
            lift[nm] = dict(context=ctxname, ctx_signals=len(base_sig), ctx_hits=int(sum(W[d] for d in base_sig)), ctx_days=int(ctx.sum()), ctx_days_in=int((ctx & W).sum()), ctx_f10=fwd(np.where(ctx)[0], 10, T - 10), bycat=rows_)
        out['lift'] = lift
        out['events_by_year'] = {nm: {str(y): int(sum(1 for p in ev if yr_loc[p] == y)) for y in np.unique(yr_loc)} for nm, ev in evpos.items()}
        out['base_fwd'] = {str(h): [int(np.isfinite(ret[h]).sum()), int((ret[h][np.isfinite(ret[h])] > 0).sum()), round(float(np.nanmean(ret[h])) * 100, 3)] for _, h in RET}
    os.makedirs(a.out, exist_ok=True); out['wall_seconds'] = round(time.time() - t_all, 1)
    json.dump(out, open(os.path.join(a.out, f'fit_{a.fit}.json'), 'w', encoding='utf-8'), ensure_ascii=False)
    print(json.dumps({k: out[k] for k in ('fit', 'cond', 'days', 'train_days', 'wall_seconds')}, ensure_ascii=False), {k: (v['n_train'], len(v['test'])) for k, v in out['events'].items()})


if __name__ == '__main__':
    main()
