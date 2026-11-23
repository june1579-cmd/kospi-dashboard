#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""combo_probe.py — '조건 조합을 전부 훑으면 어떻게 되나'를 실제로 재는 검증 계산 (사용자 요청 2026-11-23).

묻는 것
  1) 조합이 실제로 몇 개이고 다 보는 데 얼마나 걸리나(조건 1~4개, 신호일 35일 이상인 것 전부)
  2) 전부 훑으면 통과 숫자를 채우는 조합이 몇 개 나오고, 그중 우연(가짜 수익)으로도 나오는 것이 몇 개인가
  3) 지난 자료에서 고른 조합이 그 다음 해에 실제로 맞는가(해마다 그 해 이전 자료로만 고름)
  4) 지금 연구소 방식(A6: 조건 2개는 전부, 3개는 상위 40쌍에만 붙임)이 전부 훑기와 얼마나 다른가

자료: 통합 예측 연구소 자료표(deriv/uni/out/panel.pkl, 지표 434개). 조건은 연구소와 같은 꼴(학습 구간 분위 하위 10·20%, 상위 20·10%).
대상: 코스피200 선물, 신호 다음 날 시가 → h일째 종가, h = 1·3·5·10·20, 오름·내림.
한 번 실행 = 한 '맞춤'(--fit 2016 … 2026 = 그 해를 시험, FULL = 전체 기간에서 통과 숫자 세기).
"""
import argparse
import hashlib
import json
import os
import pickle
import time

import numpy as np
import pandas as pd

import combo_core as K

HERE = os.path.dirname(os.path.abspath(__file__))
TRAIN_START = pd.Timestamp('2010-01-01'); DEV_END = pd.Timestamp('2023-12-31'); HOLD_START = pd.Timestamp('2024-01-01')
HS = [1, 3, 5, 10, 20]
MIN_RAW = 35; MIN_N = 35
# 걸어가며 고르는 규칙: (전체 거래, 전체 적중, 앞 토막 거래, 앞 적중, 뒤 토막(최근 3년) 거래, 뒤 적중)
RULES_WF = [('85% 이상', [35, 0.85, 0, 0, 0, 0]), ('80% 이상', [35, 0.80, 0, 0, 0, 0]), ('75% 이상', [35, 0.75, 0, 0, 0, 0]),
            ('85% 이상 + 최근 3년 8거래·75%', [35, 0.85, 0, 0, 8, 0.75]), ('80% 이상 + 최근 3년 8거래·75%', [35, 0.80, 0, 0, 8, 0.75]), ('60거래·75% 이상', [60, 0.75, 0, 0, 0, 0]),
            # 2차 실행에서 추가: 연구소 통과·관찰 숫자를 과거에 그대로 적용한 꼴(앞 = 최근 3년 이전, 뒤 = 최근 3년)
            ('연구소 통과 숫자 꼴(35거래·85%, 앞·최근 3년 각 12거래·80%)', [35, 0.85, 12, 0.80, 12, 0.80]), ('연구소 관찰 숫자 꼴(35거래·80%, 앞·최근 3년 각 12거래·75%)', [35, 0.80, 12, 0.75, 12, 0.75])]
# 전체 기간: 연구소 통과·관찰 숫자(앞 = 2023년까지, 뒤 = 2024년부터)
RULES_FULL = [('통과 숫자(35거래·85%, 앞·뒤 12거래·80%)', [35, 0.85, 12, 0.80, 12, 0.80]), ('관찰 숫자(35거래·80%, 앞·뒤 12거래·75%)', [35, 0.80, 12, 0.75, 12, 0.75]),
              ('전체만 85%', [35, 0.85, 0, 0, 0, 0]), ('전체만 80%', [35, 0.80, 0, 0, 0, 0])]


def conditions(Xtr, Xall):
    """deriv/scan/scan_run.py 의 conditions 와 같은 규칙: 학습 구간 분위로 조건을 만든다(값이 3가지 이하면 값마다)."""
    names, fid, cols = [], [], []
    for j, col in enumerate(Xtr.columns):
        a, b = Xtr[col], Xall[col]
        if a.notna().sum() < 200: continue
        vals = a.dropna().unique()
        if len(vals) <= 3:
            for v in sorted(vals): names.append(f'{col}={v:g}'); fid.append(j); cols.append((b == v).values)
            continue
        q = a.quantile([0.1, 0.2, 0.8, 0.9]).values
        for lab, m in ((f'{col}≤하위10%', b <= q[0]), (f'{col}≤하위20%', b <= q[1]), (f'{col}≥상위20%', b >= q[2]), (f'{col}≥상위10%', b >= q[3])):
            names.append(lab); fid.append(j); cols.append(m.fillna(False).values)
    return names, np.array(fid, np.int32), np.array(cols).T.astype(np.uint8)


def thin(days, h):
    out = []; last = -10 ** 6
    for d in days:
        if d - last >= h: out.append(d); last = d
    return out


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--fit', required=True); ap.add_argument('--panel', default=os.path.join(HERE, '..', 'uni', 'out', 'panel.pkl'))
    ap.add_argument('--out', default=os.path.join(HERE, 'out')); ap.add_argument('--maxlevel', type=int, default=4); ap.add_argument('--budget', type=float, default=1500.0)
    ap.add_argument('--null', type=int, default=3); ap.add_argument('--limit-cond', type=int, default=0); a = ap.parse_args(); t_all = time.time()
    D = pickle.load(open(a.panel, 'rb')); X, P = D['X'], D['P']; td = X.index; F = P['K200F']
    i0 = int(td.searchsorted(TRAIN_START)); full = a.fit.upper() == 'FULL'
    if full:
        i1 = len(td); test_start = i1 - i0; TE = test_start; split = int(td.searchsorted(HOLD_START)) - i0; trend = [test_start - h for h in HS]
        tr_rows = (td >= TRAIN_START) & (td <= DEV_END); rules = RULES_FULL
    else:
        Y = int(a.fit); te = np.where(td.year == Y)[0]; i1 = te[-1] + 1; test_start = te[0] - i0; TE = test_start - 1; trend = [test_start - h for h in HS]
        split = int(td.searchsorted(pd.Timestamp(f'{Y - 3}-01-01'))) - i0; tr_rows = (np.arange(len(td)) >= i0) & (np.arange(len(td)) < te[0]); rules = RULES_WF
    T = i1 - i0; idx = td[i0:i1]
    names, fid, Bt = conditions(X[tr_rows], X.iloc[i0:i1])
    n_all_cond = len(names)
    # 같은 조건(참·거짓이 날마다 똑같음)은 하나만, 학습 신호일 35일 미만은 뺌(어떤 조합에도 못 들어감) → 순서 섞기(병렬 균형)
    cnt = Bt[:TE].sum(0); seen = {}; keep = []
    for c in range(Bt.shape[1]):
        if cnt[c] < MIN_RAW: continue
        hsh = hashlib.md5(Bt[:, c].tobytes()).hexdigest()
        if hsh in seen: continue
        seen[hsh] = c; keep.append(c)
    rng = np.random.default_rng(7); keep = np.array(keep)[rng.permutation(len(keep))]
    if a.limit_cond: keep = keep[:a.limit_cond]
    names = [names[c] for c in keep]; fid = fid[keep]; Bt = np.ascontiguousarray(Bt[:, keep]); C = len(keep)
    # 수익 부호
    o = F['open'].values.astype(float); c_ = F['close'].values.astype(float); n = len(td); val = np.full((len(HS), T), -1, np.int8)
    for hi, h in enumerate(HS):
        r = np.full(n, np.nan); ok = np.arange(n) + h < n; ii = np.arange(n)[ok]; r[ii] = c_[ii + h] / o[ii + 1] - 1
        rr = r[i0:i1]; val[hi] = np.where(np.isfinite(rr) & (rr > 0), 1, np.where(np.isfinite(rr) & (rr < 0), 0, -1))
    # 가짜 수익 두 가지: (1) 통째로 옮김 = 학습 구간 전체에서 1년 이상 밀기 (2) 해 안에서만 옮김 = 해마다 그 해 안에서만 밀기(그 해의 오른 날 비율은 그대로 → '강세장에 켜져 있었을 뿐'인 조합도 가짜에서 살아남는다, 더 엄한 비교)
    nB = a.null; valn = np.full((max(nB, 1), len(HS), T), -1, np.int8); shifts = rng.integers(250, TE - 250, size=max(nB, 1)); null_types = []
    yr_loc = idx.year.values
    for b in range(nB):
        if b < (nB + 1) // 2:
            valn[b, :, :TE] = np.roll(val[:, :TE], int(shifts[b]), axis=1); null_types.append('global')
        else:
            for y in np.unique(yr_loc[:TE]):
                w = np.where(yr_loc[:TE] == y)[0]
                if len(w) < 40: valn[b][:, w] = val[:, w]; continue
                valn[b][:, w] = np.roll(val[:, w], int(rng.integers(len(w) // 4, 3 * len(w) // 4)), axis=1)
            null_types.append('year')
    R = np.array([r for _, r in rules], float)
    hash_cap = 3_000_000 if full else 0
    res = K.scan(Bt, fid, np.array(HS, np.int32), np.array(trend, np.int32), val, valn[:nB] if nB else valn[:0], R, TE, test_start, split,
                 maxlevel=a.maxlevel, min_raw=MIN_RAW, min_n=MIN_N, K=50, do_hash=int(full), hash_cap=hash_cap, budget=a.budget)
    sec = res['misc'][4] / 1000.0
    out = dict(fit=a.fit, made=pd.Timestamp.now(tz='Asia/Seoul').strftime('%Y-%m-%d %H:%M'), features=int(X.shape[1]), cond_all=int(n_all_cond), cond=int(C), days=int(T), train_days=int(TE),
               test=[str(idx[test_start].date()), str(idx[-1].date())] if not full else None, H=HS, rules=[nm for nm, _ in rules], null_shifts=[int(s) for s in shifts[:nB]], null_types=null_types,
               enum=[int(x) for x in res['enum'][1:5]], seconds=round(sec, 1), threads=int(res['misc'][3]), level4_stopped=bool(res['misc'][0]), l3_total=int(res['misc'][1]), l3_expanded=int(res['misc'][2]),
               hist=res['hist'].tolist(), histn=res['histn'][:max(nB, 1)].tolist(), sel=res['sel'].tolist(), seln=res['seln'][:max(nB, 1)].tolist(), pool=res['pool'].tolist(), maxlevel=a.maxlevel)
    # 시험 해 바탕 확률, 날짜별 표(고른 조합이 그날 몇 개 켜졌나), 시험 해 수익 부호 — '합친 신호' 성적은 combo_report.py 가 여기서 계산한다
    #   (1차 실행은 여기서 계산하다 합계 변수가 8비트(127)에서 넘쳐 숫자가 틀렸다 → 2차 실행부터 원자료를 저장)
    if not full:
        base = {}
        for hi, h in enumerate(HS):
            v = val[hi, test_start:]; ok = v >= 0; base[h] = [int(ok.sum()), int(v[ok].astype(np.int64).sum())]
        out['base'] = base; out['votes'] = res['votes'][:min(a.maxlevel, 3)].astype(int).tolist(); out['test_val'] = val[:, test_start:].astype(int).tolist()
    # 가장 좋아 보이는 것(하한 기준 상위 50) — 스레드별 표를 합쳐 다시 고름
    tops = []
    for L in range(K.MAXL):
        for hi, h in enumerate(HS):
            for dr in range(2):
                lb = res['toplb'][:, L, hi, dr].ravel(); ids = res['topid'][:, L, hi, dr].reshape(-1, 4); st = res['topst'][:, L, hi, dr].reshape(-1, 4)
                od = np.argsort(-lb)[:50]
                for q in od:
                    if lb[q] <= 0: continue
                    tops.append([L + 1, h, dr, round(float(lb[q]), 4), [names[i] for i in ids[q] if i >= 0], [int(x) for x in st[q]]])
    out['top'] = tops
    if full:
        hc = res['hcount']; over = bool((hc > hash_cap).any()); hb = np.concatenate([res['hbuf'][q, :min(int(hc[q]), hash_cap)] for q in range(len(hc))]); hm = np.concatenate([res['hmeta'][q, :min(int(hc[q]), hash_cap)] for q in range(len(hc))])
        dd = {}
        for r in range(2):
            m = (hm & 15) == r
            dd[rules[r][0]] = dict(count=int(m.sum()), distinct_signal_days=int(len(np.unique(hb[m]))),
                                   by_level={int(L): [int((m & ((hm >> 16) == L)).sum()), int(len(np.unique(hb[m & ((hm >> 16) == L)])))] for L in range(1, 5)})
        out['distinct'] = dd; out['hash_overflow'] = over
        # 지금 연구소 방식(A6)이 만드는 후보: 조건 1개 상위 150, 2개 상위 400, 3개 = 상위 40쌍 × 6 → 같은 잣대로 정확히 재서 통과 숫자를 채우는지
        trm = np.asarray(tr_rows)[i0:i1]; Ctr = Bt[trm].astype(np.float32); beam = {}
        for hi, h in enumerate(HS):
            for dr in range(2):
                yv = val[hi][trm]; okd = yv >= 0; y = (yv == 1).astype(np.float32) if dr == 0 else (yv == 0).astype(np.float32); Cq = Ctr[okd]; y = y[okd]; heff = np.sqrt(h)
                def wl(k, n_, z=1.28):
                    with np.errstate(divide='ignore', invalid='ignore'):
                        p = k / n_; d = 1 + z * z / n_; c2 = p + z * z / (2 * n_); hh = z * np.sqrt(p * (1 - p) / n_ + z * z / (4 * n_ * n_)); return (c2 - hh) / d
                Cy = Cq * y[:, None]; N1 = Cq.sum(0); H1 = Cy.sum(0); N2 = Cq.T @ Cq; H2 = Cq.T @ Cy; same = fid[:, None] == fid[None, :]
                LB2 = wl(H2 / heff, N2 / heff); LB2[(N2 / heff < 15) | same | ~np.isfinite(LB2)] = 0; LB1 = wl(H1 / heff, N1 / heff); LB1[(N1 / heff < 15) | ~np.isfinite(LB1)] = 0
                cand = [(int(i),) for i in np.argsort(-LB1, kind='stable')[:150] if LB1[i] > 0]; iu = np.triu_indices_from(LB2, k=1); flat = LB2[iu]; top2 = np.argsort(-flat, kind='stable')[:400]
                pairs = [(int(iu[0][k]), int(iu[1][k])) for k in top2 if flat[k] > 0]; cand += pairs
                for (i, j) in pairs[:40]:
                    pm = Cq[:, i] * Cq[:, j]; N3 = pm @ Cq; H3 = (pm * y) @ Cq; LB3 = wl(H3 / heff, N3 / heff); LB3[(N3 / heff < 15) | ~np.isfinite(LB3) | (fid == fid[i]) | (fid == fid[j])] = 0
                    cand += [tuple(sorted((i, j, int(k)))) for k in np.argsort(-LB3, kind='stable')[:6] if LB3[k] > 0]
                got = {1: [0, 0, 0], 2: [0, 0, 0], 3: [0, 0, 0]}
                for ids in set(cand):
                    days = np.where(Bt[:, list(ids)].all(axis=1))[0]; st = K.trade_stats(days, [h], [trend[hi]], val[hi:hi + 1], split)[0]; n0, x0, n1, x1 = [int(x) for x in st]
                    u0, u1 = (x0, x1) if dr == 0 else (n0 - x0, n1 - x1); g = got[len(ids)]; g[0] += 1
                    for r in range(2): g[1 + r] += int(K.rule_ok(R[r], n0 + n1, u0 + u1, n0, u0, n1, u1))
                beam[f'{h}|{dr}'] = got
        out['beam'] = beam
    os.makedirs(a.out, exist_ok=True); out['wall_seconds'] = round(time.time() - t_all, 1)
    json.dump(out, open(os.path.join(a.out, f'fit_{a.fit}.json'), 'w', encoding='utf-8'), ensure_ascii=False)
    print(json.dumps({k: out[k] for k in ('fit', 'features', 'cond_all', 'cond', 'days', 'train_days', 'enum', 'seconds', 'threads', 'level4_stopped', 'l3_total', 'l3_expanded', 'wall_seconds')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
