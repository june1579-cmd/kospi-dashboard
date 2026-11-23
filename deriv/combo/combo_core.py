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


def scan(Bt, fid, H, trend, val, valn, rules, TE, test_start, split, maxlevel=3, min_raw=35, min_n=35, K=50, do_hash=0, hash_cap=0, budget=0.0, nthreads=0, rowwin=None, ptop=None):
    lib = ctypes.CDLL(build()); T, C = Bt.shape; nH = len(H); nB = valn.shape[0] if valn is not None and valn.size else 0; nR = len(rules)
    nth = nthreads or os.cpu_count(); TT = max(T - test_start, 0)
    Bt = np.ascontiguousarray(Bt, dtype=np.uint8); fid = np.ascontiguousarray(fid, dtype=np.int32); H = np.ascontiguousarray(H, dtype=np.int32); trend = np.ascontiguousarray(trend, dtype=np.int32)
    val = np.ascontiguousarray(val, dtype=np.int8); valn = np.ascontiguousarray(valn if nB else np.zeros((1, nH, T)), dtype=np.int8)
    rules = np.asarray(rules, dtype=np.float64)
    if rules.shape[1] == 6: rules = np.hstack([rules, np.zeros((len(rules), 1))])      # 7번째 = 최소 맞은 수(없으면 0)
    rules = np.ascontiguousarray(rules); rowwin = np.ascontiguousarray(rowwin if rowwin is not None else np.zeros(nH), dtype=np.int32); ptop = np.ascontiguousarray(ptop if ptop is not None else np.zeros(nH), dtype=np.float64)
    ip = np.array([C, T, nH, nB, nR, maxlevel, min_raw, min_n, TE, test_start, split, K, do_hash, nth], dtype=np.int32); dp = np.array([budget], dtype=np.float64)
    o = dict(enum=np.zeros(MAXL + 2, np.int64), hist=np.zeros((MAXL, nH, 2, NBIN), np.int64), histn=np.zeros((max(nB, 1), MAXL, nH, 2, NBIN), np.int64), sel=np.zeros((MAXL, nR, nH, 2), np.int64),
             seln=np.zeros((max(nB, 1), MAXL, nR, nH, 2), np.int64), pool=np.zeros((MAXL, nR, nH, 2, 4), np.int64), votes=np.zeros((MAXL, nR, nH, 2, max(TT, 1)), np.int32),
             toplb=np.full((nth, MAXL, nH, 2, max(K, 1)), -1.0), topid=np.full((nth, MAXL, nH, 2, max(K, 1), 4), -1, np.int32), topst=np.zeros((nth, MAXL, nH, 2, max(K, 1), 4), np.int32),
             xpool=np.zeros((MAXL, nR, nH, nH, 4), np.int64), hbuf=np.zeros((nth, max(hash_cap, 1)), np.uint64), hmeta=np.zeros((nth, max(hash_cap, 1)), np.int32), hcount=np.zeros(nth, np.int64), misc=np.zeros(8, np.int64))
    P = lambda a: a.ctypes.data_as(ctypes.c_void_p)
    lib.combo_scan.restype = ctypes.c_int
    rc = lib.combo_scan(P(ip), P(dp), P(Bt), P(fid), P(H), P(trend), P(val), P(valn), P(rules), ctypes.c_int64(hash_cap), P(rowwin), P(ptop), P(o['xpool']),
                        P(o['enum']), P(o['hist']), P(o['histn']), P(o['sel']), P(o['seln']), P(o['pool']), P(o['votes']),
                        P(o['toplb']), P(o['topid']), P(o['topst']), P(o['hbuf']), P(o['hmeta']), P(o['hcount']), P(o['misc']))
    if rc != 0: raise RuntimeError(f'combo_scan rc={rc}')
    o['votes'] = o['votes'][..., :TT]; o['nB'] = nB
    return o


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


def rule_ok(R, na, ua, n0, u0, n1, u1):
    if na < R[0] or ua < R[1] * na - 1e-9 or (len(R) > 6 and ua < R[6]): return False
    if R[2] > 0 and (n0 < R[2] or u0 < R[3] * n0 - 1e-9): return False
    if R[4] > 0 and (n1 < R[4] or u1 < R[5] * n1 - 1e-9): return False
    return True


def brute(Bt, fid, H, trend, val, valn, rules, TE, test_start, split, maxlevel=3, min_raw=35, min_n=35, rowwin=None):
    T, C = Bt.shape; nH = len(H); nB = valn.shape[0]; nR = len(rules); TT = max(T - test_start, 0)
    o = dict(enum=np.zeros(MAXL + 2, np.int64), hist=np.zeros((MAXL, nH, 2, NBIN), np.int64), histn=np.zeros((max(nB, 1), MAXL, nH, 2, NBIN), np.int64), sel=np.zeros((MAXL, nR, nH, 2), np.int64),
             seln=np.zeros((max(nB, 1), MAXL, nR, nH, 2), np.int64), pool=np.zeros((MAXL, nR, nH, 2, 4), np.int64), votes=np.zeros((MAXL, nR, nH, 2, TT), np.int32), xpool=np.zeros((MAXL, nR, nH, nH, 4), np.int64))
    big = np.full(len(H), 10 ** 9); rowwin = np.zeros(nH, int) if rowwin is None else rowwin
    for L in range(1, maxlevel + 1):
        for ids in itertools.combinations(range(C), L):
            if len({fid[c] for c in ids}) < L: continue
            m = Bt[:, list(ids)].all(axis=1); A = np.where(m[:TE])[0]; E = np.where(m)[0]; E = E[E >= test_start]
            if L > 1 and len(A) < min_raw: continue
            o['enum'][L] += 1; st = trade_stats(A, H, trend, val, split); te = trade_stats(E, H, big, val, 10 ** 9)
            for hi in range(nH):
                for dr in range(2):
                    if rowwin[hi] and dr: continue
                    n0, x0, n1, x1 = st[hi]; u0, u1 = (x0, x1) if dr == 0 else (n0 - x0, n1 - x1); na, ua = n0 + n1, u0 + u1
                    if na >= min_n:
                        o['hist'][L - 1, hi, dr, int(ua * 20.0 / na + 1e-9)] += 1
                        for r in range(nR):
                            if rule_ok(rules[r], na, ua, n0, u0, n1, u1):
                                o['sel'][L - 1, r, hi, dr] += 1; tn = te[hi, 0]; tu = te[hi, 1] if dr == 0 else te[hi, 0] - te[hi, 1]
                                o['pool'][L - 1, r, hi, dr] += [na, ua, tn, tu]
                                for d in E: o['votes'][L - 1, r, hi, dr, d - test_start] += 1
                                if rowwin[hi]:
                                    for h2 in range(nH):
                                        if not rowwin[h2]: o['xpool'][L - 1, r, hi, h2] += [st[h2, 0] + st[h2, 2], st[h2, 1] + st[h2, 3], te[h2, 0], te[h2, 1]]
                    for b in range(nB):
                        sb = trade_stats_null(A, H, trend, val, valn[b], split)[hi]; m0, y0, m1, y1 = sb
                        w0, w1 = (y0, y1) if dr == 0 else (m0 - y0, m1 - y1); ma, wa = m0 + m1, w0 + w1
                        if ma < min_n: continue
                        o['histn'][b, L - 1, hi, dr, int(wa * 20.0 / ma + 1e-9)] += 1
                        for r in range(nR):
                            if rule_ok(rules[r], ma, wa, m0, w0, m1, w1): o['seln'][b, L - 1, r, hi, dr] += 1
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
