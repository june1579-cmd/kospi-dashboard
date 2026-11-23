# -*- coding: utf-8 -*-
"""combo.c 를 불러 쓰는 파이썬 쪽 껍데기 + 느리지만 뻔한 파이썬 계산(검산용)."""
import ctypes
import itertools
import os
import subprocess

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
MAXL, NBIN = 4, 21


def build():
    src = os.path.join(HERE, 'combo.c'); so = os.path.join(HERE, 'combo.so')
    if not os.path.exists(so) or os.path.getmtime(so) < os.path.getmtime(src):
        subprocess.check_call(['gcc', '-O3', '-march=native', '-fopenmp', '-shared', '-fPIC', '-o', so, src, '-lm'])
    return so


NRV, NST = 12, 8      # 규칙 하나의 값 수, 상위 표 한 줄의 숫자 수(combo.c 와 같아야 한다)


def pad_rules(rules):
    """규칙을 값 12개 꼴로 맞춘다(옛 6·7개 꼴은 나머지를 0으로: 모든 줄에 적용, 동반 수익 조건 없음)."""
    rules = np.asarray(rules, dtype=np.float64)
    if rules.shape[1] < NRV: rules = np.hstack([rules, np.zeros((len(rules), NRV - rules.shape[1]))])
    return np.ascontiguousarray(rules)


def scan(Bt, fid, H, trend, val, valn, rules, TE, test_start, split, maxlevel=3, min_raw=35, min_n=35, K=50, do_hash=0, hash_cap=0, budget=0.0, nthreads=0, rowwin=None, ptop=None,
         comp=-1, toprule=-1, top2_min_n=20):
    """rowwin: 줄 종류(0 수익 부호, 1 전환 구간·저점, 2 전환 구간·고점). comp: 동반 수익 줄 번호. toprule: 둘째 상위 표에 들 자격 규칙 번호."""
    lib = ctypes.CDLL(build()); T, C = Bt.shape; nH = len(H); nB = valn.shape[0] if valn is not None and valn.size else 0; nR = len(rules)
    nth = nthreads or os.cpu_count(); TT = max(T - test_start, 0)
    Bt = np.ascontiguousarray(Bt, dtype=np.uint8); fid = np.ascontiguousarray(fid, dtype=np.int32); H = np.ascontiguousarray(H, dtype=np.int32); trend = np.ascontiguousarray(trend, dtype=np.int32)
    val = np.ascontiguousarray(val, dtype=np.int8); valn = np.ascontiguousarray(valn if nB else np.zeros((1, nH, T)), dtype=np.int8)
    rules = pad_rules(rules); rowwin = np.ascontiguousarray(rowwin if rowwin is not None else np.zeros(nH), dtype=np.int32); ptop = np.ascontiguousarray(ptop if ptop is not None else np.zeros(nH), dtype=np.float64)
    ip = np.array([C, T, nH, nB, nR, maxlevel, min_raw, min_n, TE, test_start, split, K, do_hash, nth, comp, toprule, top2_min_n], dtype=np.int32); dp = np.array([budget], dtype=np.float64)
    k1 = max(K, 1)
    o = dict(enum=np.zeros(MAXL + 2, np.int64), hist=np.zeros((MAXL, nH, 2, NBIN), np.int64), histn=np.zeros((max(nB, 1), MAXL, nH, 2, NBIN), np.int64), sel=np.zeros((MAXL, nR, nH, 2), np.int64),
             seln=np.zeros((max(nB, 1), MAXL, nR, nH, 2), np.int64), pool=np.zeros((MAXL, nR, nH, 2, 4), np.int64), votes=np.zeros((MAXL, nR, nH, 2, max(TT, 1)), np.int32),
             toplb=np.full((nth, MAXL, nH, 2, k1), -1.0), topid=np.full((nth, MAXL, nH, 2, k1, 4), -1, np.int32), topst8=np.zeros((nth, MAXL, nH, 2, k1, NST), np.int32),
             top2lb=np.full((nth, MAXL, nH, 2, k1), -1.0), top2id=np.full((nth, MAXL, nH, 2, k1, 4), -1, np.int32), top2st=np.zeros((nth, MAXL, nH, 2, k1, NST), np.int32),
             xpool=np.zeros((MAXL, nR, nH, nH, 4), np.int64), hbuf=np.zeros((nth, max(hash_cap, 1)), np.uint64), hmeta=np.zeros((nth, max(hash_cap, 1)), np.int32), hcount=np.zeros(nth, np.int64), misc=np.zeros(8, np.int64))
    P = lambda a: a.ctypes.data_as(ctypes.c_void_p)
    lib.combo_scan.restype = ctypes.c_int
    rc = lib.combo_scan(P(ip), P(dp), P(Bt), P(fid), P(H), P(trend), P(val), P(valn), P(rules), ctypes.c_int64(hash_cap), P(rowwin), P(ptop), P(o['xpool']),
                        P(o['enum']), P(o['hist']), P(o['histn']), P(o['sel']), P(o['seln']), P(o['pool']), P(o['votes']),
                        P(o['toplb']), P(o['topid']), P(o['topst8']), P(o['hbuf']), P(o['hmeta']), P(o['hcount']), P(o['misc']),
                        P(o['top2lb']), P(o['top2id']), P(o['top2st']))
    if rc != 0: raise RuntimeError(f'combo_scan rc={rc}')
    o['votes'] = o['votes'][..., :TT]; o['nB'] = nB; o['topst'] = o['topst8'][..., :4]        # topst: 옛 꼴(숫자 4개) 그대로
    return o


def wilson(k, n, z=1.28):
    p = k / n; d = 1 + z * z / n; c = p + z * z / (2.0 * n); h = z * np.sqrt(p * (1 - p) / n + z * z / (4.0 * n * n))
    return (c - h) / d


# ---------------------------------------------------------------- 검산용(느림)
def trade_stats(days, H, trend, val, split):
    """days(오름차순 신호일) → 보유일별 [앞 토막 거래, 앞 오름, 뒤 토막 거래, 뒤 오름] (연구소 솎기: 앞 신호 뒤 h 거래일 지나야 다음 신호)"""
    out = np.zeros((len(H), 4), np.int64)
    for hi, h in enumerate(H):
        last = -10 ** 6
        for d in days:
            if d >= trend[hi] or d - last < h: continue
            v = val[hi, d]
            if v < 0: continue
            last = d; s = int(d >= split); out[hi, 2 * s] += 1; out[hi, 2 * s + 1] += v
    return out


def rule_ok(R, na, ua, n0, u0, n1, u1, rw=0, cn=0, cu=0):
    R = list(R) + [0] * (NRV - len(R))
    if (R[7] == 1 and not rw) or (R[7] == 2 and rw): return False
    if na < R[0] or ua < R[1] * na - 1e-9 or ua < R[6]: return False
    if R[2] > 0 and (n0 < R[2] or u0 < R[3] * n0 - 1e-9): return False
    if R[4] > 0 and (n1 < R[4] or u1 < R[5] * n1 - 1e-9): return False
    if R[8] > 0 and rw and (cn < R[9] or cu < R[8] * cn - 1e-9): return False
    return True


def brute(Bt, fid, H, trend, val, valn, rules, TE, test_start, split, maxlevel=3, min_raw=35, min_n=35, rowwin=None, ptop=None, comp=-1, toprule=-1, top2_min_n=20):
    """combo.c 와 같은 것을 뻔하게 센다. 상위 표는 조합마다의 (점수, 숫자 8개, 켜진 날)를 모두 돌려준다: t1[(L, 줄, 방향)][조합], t2[(L, 줄)][조합]."""
    T, C = Bt.shape; nH = len(H); nB = valn.shape[0]; nR = len(rules); TT = max(T - test_start, 0); rules = pad_rules(rules)
    o = dict(enum=np.zeros(MAXL + 2, np.int64), hist=np.zeros((MAXL, nH, 2, NBIN), np.int64), histn=np.zeros((max(nB, 1), MAXL, nH, 2, NBIN), np.int64), sel=np.zeros((MAXL, nR, nH, 2), np.int64),
             seln=np.zeros((max(nB, 1), MAXL, nR, nH, 2), np.int64), pool=np.zeros((MAXL, nR, nH, 2, 4), np.int64), votes=np.zeros((MAXL, nR, nH, 2, TT), np.int32), xpool=np.zeros((MAXL, nR, nH, nH, 4), np.int64), t1={}, t2={})
    big = np.full(len(H), 10 ** 9); rowwin = np.zeros(nH, int) if rowwin is None else rowwin; ptop = np.zeros(nH) if ptop is None else ptop
    for L in range(1, maxlevel + 1):
        for ids in itertools.combinations(range(C), L):
            if len({fid[c] for c in ids}) < L: continue
            m = Bt[:, list(ids)].all(axis=1); A = np.where(m[:TE])[0]; E = np.where(m)[0]; E = E[E >= test_start]
            if L > 1 and len(A) < min_raw: continue
            o['enum'][L] += 1; st = trade_stats(A, H, trend, val, split); te = trade_stats(E, H, big, val, 10 ** 9); dk = (tuple(int(d) for d in A), tuple(int(d) for d in E))
            sbs = [trade_stats_null(A, H, trend, val, valn[b], split) for b in range(nB)]
            cn = int(st[comp, 0] + st[comp, 2]) if comp >= 0 else 0; cup = int(st[comp, 1] + st[comp, 3]) if comp >= 0 else 0
            ctn = int(te[comp, 0]) if comp >= 0 else 0; ctup = int(te[comp, 1]) if comp >= 0 else 0
            for hi in range(nH):
                rw = int(rowwin[hi]); cu = cn - cup if rw == 2 else cup
                for dr in range(2):
                    if rw and dr: continue
                    n0, x0, n1, x1 = st[hi]; u0, u1 = (x0, x1) if dr == 0 else (n0 - x0, n1 - x1); na, ua = n0 + n1, u0 + u1
                    tn = te[hi, 0]; tu = te[hi, 1] if dr == 0 else te[hi, 0] - te[hi, 1]
                    if na >= min_n:
                        o['hist'][L - 1, hi, dr, int(ua * 20.0 / na + 1e-9)] += 1; passed = []
                        for r in range(nR):
                            if rule_ok(rules[r], na, ua, n0, u0, n1, u1, rw, cn, cu):
                                passed.append(r); o['sel'][L - 1, r, hi, dr] += 1
                                o['pool'][L - 1, r, hi, dr] += [na, ua, tn, tu]
                                for d in E: o['votes'][L - 1, r, hi, dr, d - test_start] += 1
                                if rw:
                                    for h2 in range(nH):
                                        if not rowwin[h2]: o['xpool'][L - 1, r, hi, h2] += [st[h2, 0] + st[h2, 2], st[h2, 1] + st[h2, 3], te[h2, 0], te[h2, 1]]
                        s8 = [int(na), int(ua), int(tn), int(tu)] + ([cn, cu, ctn, ctn - ctup if rw == 2 else ctup] if rw else [0, 0, 0, 0])
                        lb = wilson(ua, na)
                        if rw: lb = ua + lb if ua >= ptop[hi] * na - 1e-9 else -1.0
                        if lb > -1.0: o['t1'].setdefault((L, hi, dr), {})[ids] = (float(lb), s8, dk)
                        if rw and toprule >= 0 and toprule in passed and cn >= top2_min_n and cn > 0: o['t2'].setdefault((L, hi), {})[ids] = (float(wilson(cu, cn)), s8, dk)
                    for b in range(nB):
                        m0, y0, m1, y1 = sbs[b][hi]
                        w0, w1 = (y0, y1) if dr == 0 else (m0 - y0, m1 - y1); ma, wa = m0 + m1, w0 + w1
                        if ma < min_n: continue
                        o['histn'][b, L - 1, hi, dr, int(wa * 20.0 / ma + 1e-9)] += 1
                        cnb = int(sbs[b][comp, 0] + sbs[b][comp, 2]) if comp >= 0 else 0; cupb = int(sbs[b][comp, 1] + sbs[b][comp, 3]) if comp >= 0 else 0
                        for r in range(nR):
                            if rule_ok(rules[r], ma, wa, m0, w0, m1, w1, rw, cnb, cnb - cupb if rw == 2 else cupb): o['seln'][b, L - 1, r, hi, dr] += 1
    return o


def trade_stats_null(days, H, trend, val, vn, split):
    """거래일은 진짜 수익 기준으로 솎고(신호는 그대로), 맞았는지만 가짜 수익으로 센다."""
    out = np.zeros((len(H), 4), np.int64)
    for hi, h in enumerate(H):
        last = -10 ** 6
        for d in days:
            if d >= trend[hi] or d - last < h: continue
            if val[hi, d] < 0: continue
            last = d; s = int(d >= split)
            if vn[hi, d] >= 0: out[hi, 2 * s] += 1; out[hi, 2 * s + 1] += vn[hi, d]
    return out
