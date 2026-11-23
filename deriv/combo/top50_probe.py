#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""top50_probe.py — 전체 기간에서 '거래 50번 이상'인 조합(조건 1~3개 전부) 가운데 적중이 가장 높은 10개 (사용자 요청 2026-11-23).
보유 1·3·5·10·20일, 오름·내림. 신호 다음 날 시가 → h일째 종가. 켜진 날이 똑같은 조합은 하나로 친다.
전체 기간을 다 보고 뽑는 것이므로 '고를 때 성적'이다(다음 해 성적은 deriv/combo/FINDINGS.md)."""
import argparse, hashlib, json, os, pickle
import numpy as np, pandas as pd
import combo_core as K
from combo_probe import conditions, TRAIN_START, DEV_END, HOLD_START

HERE = os.path.dirname(os.path.abspath(__file__)); HS = [1, 3, 5, 10, 20]; MINN = 50; KTOP = 300


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--panel', default=os.path.join(HERE, '..', 'uni', 'out', 'panel.pkl')); ap.add_argument('--out', default=os.path.join(HERE, 'out50')); ap.add_argument('--limit-cond', type=int, default=0)
    a = ap.parse_args(); D = pickle.load(open(a.panel, 'rb')); X, F = D['X'], D['P']['K200F']; td = X.index; n = len(td)
    o = F['open'].values.astype(float); c = F['close'].values.astype(float); i0 = int(td.searchsorted(TRAIN_START)); T = n - i0; idx = td[i0:]; yr = idx.year.values; split = int(td.searchsorted(HOLD_START)) - i0
    names, fid, Bt = conditions(X[(td >= TRAIN_START) & (td <= DEV_END)], X.iloc[i0:]); cnt = Bt.sum(0); seen = {}; keep = []
    for j in range(Bt.shape[1]):
        if cnt[j] < MINN: continue
        h_ = hashlib.md5(Bt[:, j].tobytes()).hexdigest()
        if h_ in seen: continue
        seen[h_] = j; keep.append(j)
    keep = np.array(keep)[np.random.default_rng(7).permutation(len(keep))]
    if a.limit_cond: keep = keep[:a.limit_cond]
    names = [names[j] for j in keep]; fid = fid[keep]; Bt = np.ascontiguousarray(Bt[:, keep]); B = Bt.astype(bool)
    ret = {}; val = np.full((len(HS), T), -1, np.int8)
    for hi, h in enumerate(HS):
        r = np.full(n, np.nan); ii = np.arange(n)[np.arange(n) + h < n]; r[ii] = c[ii + h] / o[ii + 1] - 1; ret[h] = r[i0:]
        val[hi] = np.where(np.isfinite(ret[h]) & (ret[h] > 0), 1, np.where(np.isfinite(ret[h]) & (ret[h] < 0), 0, -1))
    H = np.array(HS, np.int32); trend = np.array([T - h for h in HS], np.int32); R = np.array([[10 ** 9, 2.0, 0, 0, 0, 0, 0]], float)
    res = K.scan(Bt, fid, H, trend, val, np.zeros((0, len(HS), T), np.int8), R, T, T, split, maxlevel=3, min_raw=MINN, min_n=MINN, K=KTOP)

    def detail(cid, hi, dr):
        h = HS[hi]; m = B[:, cid].all(axis=1); tr = []; last = -10 ** 6; openn = 0
        for d in np.where(m)[0]:
            if d - last < h: continue
            if d >= trend[hi]: openn += 1; last = d; continue
            if val[hi, d] < 0: continue
            last = d; tr.append((int(d), float(ret[h][d])))
        ok = lambda r: (r > 0) if dr == 0 else (r < 0)
        by = {}
        for d, r in tr: y = int(yr[d]); by.setdefault(y, [0, 0, 1.0]); by[y][0] += 1; by[y][1] += int(ok(r)); by[y][2] *= 1 + r
        f = [(d, r) for d, r in tr if d < split]; b = [(d, r) for d, r in tr if d >= split]
        return dict(n=len(tr), hit=int(sum(ok(r) for _, r in tr)), mean=round(float(np.mean([r for _, r in tr])) * 100, 3), front=[len(f), int(sum(ok(r) for _, r in f))], back=[len(b), int(sum(ok(r) for _, r in b))],
                    years={str(y): [v[0], v[1], round((v[2] - 1) * 100, 1)] for y, v in sorted(by.items())}, years_traded=len(by), worst=round(min(r for _, r in tr) * 100, 1) if dr == 0 else round(max(r for _, r in tr) * 100, 1),
                    open_now=openn, last=str(idx[np.where(m)[0][-1]].date()), on=bool(m[-1]))

    out = dict(made=pd.Timestamp.now(tz='Asia/Seoul').strftime('%Y-%m-%d %H:%M'), last_day=str(idx[-1].date()), cond=len(names), enum=[int(x) for x in res['enum'][1:4]], seconds=round(res['misc'][4] / 1000, 1), min_n=MINN, cells={}, base={})
    for hi, h in enumerate(HS):
        v = val[hi][val[hi] >= 0]; out['base'][str(h)] = [int(len(v)), int(v.sum()), round(float(np.nanmean(ret[h])) * 100, 3)]
        for dr in (0, 1):
            cand = []; full_min = []
            for L in range(3):
                lb = res['toplb'][:, L, hi, dr]; ids = res['topid'][:, L, hi, dr]; st = res['topst8'][:, L, hi, dr]
                for q in range(lb.shape[0]):
                    if (lb[q] > -1).all(): full_min.append(float(lb[q].min()))
                    for x in np.where(lb[q] > -1)[0]: cand.append((st[q, x, 1] / st[q, x, 0], int(st[q, x, 0]), L + 1, [int(i) for i in ids[q, x] if i >= 0]))
            cand.sort(key=lambda t: (-t[0], -t[1], t[2])); seen_h = set(); top = []
            for p, nn, L, cid in cand:
                hh = hashlib.md5(np.packbits(B[:, cid].all(axis=1)).tobytes()).digest()
                if hh in seen_h: continue
                seen_h.add(hh); d = detail(cid, hi, dr); assert (d['n'], d['hit']) == (nn, round(p * nn)), ('핵심 계산과 다름', cid, d['n'], d['hit'], nn, p)
                top.append(dict(L=L, names=[names[i] for i in cid], **d))
                if len(top) >= 10: break
            # 빠짐 없는지: 10등의 적중이 거래 50번일 때의 하한보다, 꽉 찬 표의 꼴찌 하한이 낮아야 한다
            need = float(K.wilson(top[-1]['hit'] / top[-1]['n'] * MINN, MINN)) if len(top) == 10 else -1
            out['cells'][f'{h}|{dr}'] = dict(top=top, complete=bool(all(x < need for x in full_min)) if full_min else True)
    os.makedirs(a.out, exist_ok=True); json.dump(out, open(os.path.join(a.out, 'top50.json'), 'w', encoding='utf-8'), ensure_ascii=False)
    M = [f"# 전체 기간(2010-01 ~ {out['last_day']}) · 거래 50번 이상 · 적중 상위 10개", '', f"조건 {out['cond']}개에서 조합 1개 {out['enum'][0]:,} · 2개 {out['enum'][1]:,} · 3개 {out['enum'][2]:,}개를 전부 봤다(계산 {out['seconds']}초). 전체 기간을 다 보고 뽑은 '고를 때 성적'이다.", '']
    for h in HS:
        for dr, dn in ((0, '오름'), (1, '내림')):
            ce = out['cells'][f'{h}|{dr}']; b = out['base'][str(h)]; bp = b[1] / b[0] if dr == 0 else 1 - b[1] / b[0]
            M += [f"## 보유 {h}일 · {dn} (아무 날 {bp * 100:.1f}%, 평균 {b[2]:+.2f}%){'' if ce['complete'] else ' — 빠진 것이 있을 수 있음'}", '', '| 순위 | 조합 | 거래 | 맞음 | 적중 | 평균 | 앞(~2023) | 뒤(2024~) | 거래한 해 | 2026년 거래·맞음·수익 | 가장 나쁜 거래 |', '|---|---|---|---|---|---|---|---|---|---|---|']
            for k, e in enumerate(ce['top'], 1):
                y = e['years'].get('2026', [0, 0, 0.0])
                M.append(f"| {k} | {' + '.join(e['names'])} | {e['n']} | {e['hit']} | {e['hit'] / e['n'] * 100:.1f}% | {e['mean']:+.2f}% | {e['front'][1]}/{e['front'][0]} | {e['back'][1]}/{e['back'][0]} | {e['years_traded']} | {y[0]}·{y[1]}·{y[2]:+.1f}% | {e['worst']:+.1f}% |")
            M.append('')
    M += ['투자 권유 아님']; open(os.path.join(a.out, 'report.md'), 'w', encoding='utf-8').write('\n'.join(M) + '\n'); print(out['enum'], out['seconds'], {k: v['complete'] for k, v in out['cells'].items()})


if __name__ == '__main__':
    main()
