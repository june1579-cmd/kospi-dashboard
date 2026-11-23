#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""turn_pre.py — 상승·하락이 시작되기 10일 전 ~ 1일 전의 변화와 공통점 (사용자 지시 2026-11-23).
"2010년부터 지금까지 5% 이상 변동폭을 기준으로, 상승 또는 하락이 시작되기 10일 전부터 1일 전까지 어떤 변화가 있었고 공통점은 무엇인지 조사."
- 시작점: 코스피200 선물 종가가 저점에서 5% 이상 오른 경우의 그 저점(상승 시작), 고점에서 5% 이상 내린 경우의 그 고점(하락 시작).
- 시작 당일과 그 뒤는 보지 않는다. 보유일·수익률도 쓰지 않는다.
- 지표 값은 '그날까지의 지난 250일 가운데 몇 번째 자리인가(0~100)'로 바꿔 본다(50 = 보통). 순매수 지표는 낮을수록 많이 판 것.
- 우연과 견주기 ①: 시작점 날짜를 통째로 옮긴 가짜 300번. ②: 지수가 비슷하게 움직인 다른 날(선물 5일 등락 자리가 같은 10칸 중 한 칸)에서 뽑은 가짜 300번 — 지수 움직임만으로 설명되는 부분을 걷어 낸다."""
import json, os, pickle, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, '..', 'combo')); sys.path.insert(0, HERE)
from turn_probe import zigzag, cat_of, CATS   # noqa: E402
from combo_probe import TRAIN_START   # noqa: E402
OFFS = np.arange(-10, 0); SHOW = [-10, -7, -5, -3, -2, -1]; PERIODS = [('2010~15', 2010, 2015), ('2016~20', 2016, 2020), ('2021~25', 2021, 2025), ('2026', 2026, 2026)]; NNULL = 300; MATCH = 'PF_등락_5d'


def measures(A):
    """A: (전환점, 10일, 지표) → 지표별 측정값. 9 = 1일 전, 6 = 4일 전, 0 = 10일 전."""
    with np.errstate(invalid='ignore'):
        v = np.isfinite(A[:, 9]); nv = np.maximum(v.sum(0), 1); tr = A[:, 9] - A[:, 0]; lt = A[:, 9] - A[:, 6]; er = A[:, 6] - A[:, 0]
        return dict(level=np.nanmean(A[:, 9], 0), trend=np.nanmean(tr, 0), late=np.nanmean(lt, 0), early=np.nanmean(er, 0),
                    hi=(A[:, 9] >= 80).sum(0) / nv, lo=(A[:, 9] <= 20).sum(0) / nv, up20=(tr >= 20).sum(0) / np.maximum(np.isfinite(tr).sum(0), 1), dn20=(tr <= -20).sum(0) / np.maximum(np.isfinite(tr).sum(0), 1))


def main():
    panel = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, '..', 'uni', 'out', 'panel.pkl')
    D = pickle.load(open(panel, 'rb')); X, F = D['X'], D['P']['K200F']; td = X.index; n = len(td); c = F['close'].values.astype(float); i0 = int(td.searchsorted(TRAIN_START)); yr = td.year.values
    R = X.rolling(250, min_periods=120).rank(pct=True).values * 100; cols = list(X.columns); cat = np.array([cat_of(x) for x in cols]); nF = len(cols); rs = np.random.default_rng(5)
    lo_, span = i0 + 10, n - i0 - 10; sh = rs.integers(60, span - 60, size=NNULL); mj = cols.index(MATCH); piv = zigzag(c, 0.05)
    out = dict(last_day=str(td[-1].date()), features=nF, types={}); z_of = lambda real, nul: (real - np.nanmean(nul, 0)) / (np.nanstd(nul, 0) + 1e-9)
    M = [f'# 상승·하락이 시작되기 10일 전 ~ 1일 전의 변화와 공통점 (2010-01 ~ {td[-1].date()})', '',
         '- 시작점 = 선물 종가 저점에서 5% 이상 오른 그 저점(상승 시작) / 고점에서 5% 이상 내린 그 고점(하락 시작). 당일과 그 뒤는 보지 않았다.',
         '- 숫자 = 그 지표가 "그날까지의 지난 250일 가운데 몇 번째 자리"였나(0 가장 낮음 · 50 보통 · 100 가장 높음)의 평균. 순매수 지표는 낮을수록 많이 판 것.',
         '- z = 날짜를 통째로 옮긴 우연과의 차이. "지수 감안 z" = 지수가 비슷하게 움직인 다른 날과의 차이(이게 커야 지수 움직임만으로는 설명되지 않는 변화다).',
         '- "극단" = 1일 전 자리가 80 이상(또는 20 이하)이었던 시작점 수 / 전체 (우연이면).', '']
    for key, typ, lab in (('up', 'L', '상승 시작(저점)'), ('down', 'H', '하락 시작(고점)')):
        ev = np.array([p for p, t in piv if t == typ and p >= lo_]); E = len(ev); get = lambda pos: R[pos[:, None] + OFFS[None, :]]
        A = get(ev); real = measures(A); path = np.nanmean(A, 0)
        nul = [measures(get(lo_ + (ev - lo_ + int(s)) % span)) for s in sh]; Z = {k: z_of(real[k], np.array([x[k] for x in nul])) for k in real}; chance = {k: np.nanmean(np.array([x[k] for x in nul]), 0) for k in ('hi', 'lo', 'up20', 'dn20')}
        # ② 지수가 비슷하게 움직인 다른 날: 1일 전의 선물 5일 등락 자리를 10칸으로 나눠 같은 칸의 다른 날에서 뽑는다(시작점 앞 10일~당일은 뺀다)
        ok = np.zeros(n, bool); ok[lo_:] = np.isfinite(R[lo_:, mj])
        for p in ev: ok[max(p - 10, 0):p + 1] = False
        binof = lambda d: np.clip((R[d, mj] // 10).astype(int), 0, 9); pool = [np.where(ok & (np.arange(n) >= lo_) & (binof(np.arange(n)) == b))[0] for b in range(10)]
        eb = binof(ev - 1); usable = np.isfinite(R[ev - 1, mj]); mn = []
        for _ in range(NNULL):
            pos = np.array([rs.choice(pool[b]) + 1 if u and len(pool[b]) else p for p, b, u in zip(ev, eb, usable)]); mn.append(measures(get(pos)))
        ZM = {k: z_of(real[k], np.array([x[k] for x in mn])) for k in ('level', 'trend', 'late')}; ctrl = {k: np.nanmean(np.array([x[k] for x in mn]), 0) for k in ('level', 'trend', 'late')}
        per = {}
        for pn, a, b in PERIODS:
            m = (yr[ev] >= a) & (yr[ev] <= b); per[pn] = dict(n=int(m.sum()), **({k: v for k, v in measures(A[m]).items() if k in ('level', 'trend', 'late')} if m.sum() else {}))
        rec = {}
        for j, col in enumerate(cols):
            if not np.isfinite(path[:, j]).all(): continue
            side = 'hi' if real['level'][j] >= 50 else 'lo'; mv = 'up20' if real['trend'][j] >= 0 else 'dn20'
            rec[col] = dict(cat=str(cat[j]), path=[round(float(x), 1) for x in path[:, j]], level=round(float(real['level'][j]), 1), z_level=round(float(Z['level'][j]), 2), zm_level=round(float(ZM['level'][j]), 2), ctrl_level=round(float(ctrl['level'][j]), 1),
                            trend=round(float(real['trend'][j]), 1), z_trend=round(float(Z['trend'][j]), 2), zm_trend=round(float(ZM['trend'][j]), 2), late=round(float(real['late'][j]), 1), z_late=round(float(Z['late'][j]), 2), zm_late=round(float(ZM['late'][j]), 2),
                            early=round(float(real['early'][j]), 1), z_early=round(float(Z['early'][j]), 2), side=side, ext=[int(round(real[side][j] * E)), E, round(float(chance[side][j]), 3), round(float(Z[side][j]), 2)],
                            move=[mv, int(round(real[mv][j] * E)), E, round(float(chance[mv][j]), 3), round(float(Z[mv][j]), 2)],
                            per={pn: [per[pn]['n']] + ([round(float(per[pn][k][j]), 1) for k in ('level', 'trend', 'late')] if per[pn]['n'] else []) for pn, _, _ in PERIODS})
        out['types'][key] = dict(label=lab, events=E, dates=[str(td[p].date()) for p in ev], by_period={pn: per[pn]['n'] for pn, _, _ in PERIODS}, feat=rec)
        ix = [OFFS.tolist().index(o) for o in SHOW]; ph = ' | '.join(f'{o}일' for o in SHOW); pc = lambda v: ' | '.join(f"{v['path'][i]:.0f}" for i in ix); pr = lambda v, q: ' / '.join('—' if len(v['per'][pn]) < 2 else f"{v['per'][pn][q]:+.0f}" if q > 1 else f"{v['per'][pn][q]:.0f}" for pn, _, _ in PERIODS)
        M += [f'## {lab} — {E}번 (' + ' · '.join(f'{pn} {per[pn]["n"]}번' for pn, _, _ in PERIODS) + ')', '']
        M += ['묶음별로 우연과 뚜렷이 달랐던 지표 수(|z| 3 이상 / 그중 지수 감안 뒤에도 |z| 3 이상 / 지표 수):', '', '| 묶음 | 1일 전 자리 | 10일간 변화 | 막판 3일 변화 |', '|---|---|---|---|']
        for ck in CATS:
            vs = [v for v in rec.values() if v['cat'] == ck]
            if vs: M.append(f"| {CATS[ck]} | " + ' | '.join(f"{sum(abs(v['z_' + k]) >= 3 for v in vs)} / {sum(abs(v['z_' + k]) >= 3 and abs(v['zm_' + k]) >= 3 for v in vs)} / {len(vs)}" for k in ('level', 'trend', 'late')) + ' |')
        M.append('')
        order = ('flow', 'credit', 'opt', 'futs', 'vol', 'us', 'price'); take = lambda ck: 6 if ck == 'flow' else 4 if ck in ('opt', 'credit') else 3
        M += ['### 가. 1일 전에 한쪽으로 치우쳐 있던 지표 (상태)', '', f'| 묶음 | 지표 | {ph} | z | 지수 감안 z (다른 날 평균) | 극단 (우연이면) | 기간별 1일 전 자리 ' + '/'.join(p[0] for p in PERIODS) + ' |', '|---|---|' + '---|' * (len(SHOW) + 4)]
        for ck in order:
            for k, v in sorted([(k, v) for k, v in rec.items() if v['cat'] == ck], key=lambda t: -abs(t[1]['z_level']))[:take(ck)]:
                M.append(f"| {CATS[ck]} | {k} | {pc(v)} | {v['z_level']:+.1f} | {v['zm_level']:+.1f} ({v['ctrl_level']:.0f}) | {'높음' if v['side'] == 'hi' else '낮음'} {v['ext'][0]}/{v['ext'][1]} ({v['ext'][2] * 100:.0f}%) | {pr(v, 1)} |")
        M += ['', '### 나. 10일 전부터 1일 전까지 꾸준히 움직인 지표 (변화)', '', f'| 묶음 | 지표 | {ph} | 변화 | z | 지수 감안 z | 20칸 이상 같은 쪽으로 움직인 시작점 (우연이면) | 기간별 변화 |', '|---|---|' + '---|' * (len(SHOW) + 5)]
        for ck in order:
            for k, v in sorted([(k, v) for k, v in rec.items() if v['cat'] == ck], key=lambda t: -abs(t[1]['z_trend']))[:take(ck)]:
                M.append(f"| {CATS[ck]} | {k} | {pc(v)} | {v['trend']:+.0f} | {v['z_trend']:+.1f} | {v['zm_trend']:+.1f} | {v['move'][1]}/{v['move'][2]} ({v['move'][3] * 100:.0f}%) | {pr(v, 2)} |")
        M += ['', '### 다. 막판 3일(4일 전→1일 전)에 급히 움직인 지표', '', f'| 묶음 | 지표 | {ph} | 막판 변화 | z | 지수 감안 z | 기간별 막판 변화 |', '|---|---|' + '---|' * (len(SHOW) + 4)]
        for ck in order:
            for k, v in sorted([(k, v) for k, v in rec.items() if v['cat'] == ck], key=lambda t: -abs(t[1]['z_late']))[:take(ck)]:
                M.append(f"| {CATS[ck]} | {k} | {pc(v)} | {v['late']:+.0f} | {v['z_late']:+.1f} | {v['zm_late']:+.1f} | {pr(v, 3)} |")
        rev = sorted([(k, v) for k, v in rec.items() if v['early'] * v['late'] < 0 and abs(v['z_early']) >= 2 and abs(v['z_late']) >= 2], key=lambda t: -min(abs(t[1]['z_early']), abs(t[1]['z_late'])))[:12]
        M += ['', '### 라. 앞 6일과 막판 3일의 방향이 반대였던 지표 (꺾임)', '', f'| 묶음 | 지표 | {ph} | 앞 6일 변화 (z) | 막판 3일 변화 (z) |', '|---|---|' + '---|' * (len(SHOW) + 2)]
        for k, v in rev: M.append(f"| {CATS[v['cat']]} | {k} | {pc(v)} | {v['early']:+.0f} ({v['z_early']:+.1f}) | {v['late']:+.0f} ({v['z_late']:+.1f}) |")
        if not rev: M.append('| — | 해당 없음 |' + ' |' * (len(SHOW) + 2))
        M.append('')
    # ---- 상승 시작과 하락 시작을 나란히
    U, Dn = out['types']['up']['feat'], out['types']['down']['feat']; both = [k for k in U if k in Dn]
    mir = sorted([k for k in both if U[k]['z_level'] * Dn[k]['z_level'] < 0 and min(abs(U[k]['z_level']), abs(Dn[k]['z_level'])) >= 3], key=lambda k: -min(abs(U[k]['z_level']), abs(Dn[k]['z_level'])))
    onlyu = sorted([k for k in both if abs(U[k]['z_level']) >= 4 and abs(Dn[k]['z_level']) < 1.5], key=lambda k: -abs(U[k]['z_level'])); onlyd = sorted([k for k in both if abs(Dn[k]['z_level']) >= 4 and abs(U[k]['z_level']) < 1.5], key=lambda k: -abs(Dn[k]['z_level']))
    same = sorted([k for k in both if U[k]['z_level'] * Dn[k]['z_level'] > 0 and min(abs(U[k]['z_level']), abs(Dn[k]['z_level'])) >= 3], key=lambda k: -min(abs(U[k]['z_level']), abs(Dn[k]['z_level'])))
    out['compare'] = dict(mirror=mir, only_up=onlyu, only_down=onlyd, same=same)
    M += ['## 상승 시작과 하락 시작을 나란히 (1일 전 자리)', '', f'- 서로 반대였던 지표 {len(mir)}개 · 상승 시작 전에만 뚜렷한 지표 {len(onlyu)}개 · 하락 시작 전에만 뚜렷한 지표 {len(onlyd)}개 · 둘 다 같은 쪽이던 지표 {len(same)}개', '',
          '| 구분 | 묶음 | 지표 | 상승 시작 1일 전 (z · 지수 감안 z) | 하락 시작 1일 전 (z · 지수 감안 z) |', '|---|---|---|---|---|']
    for nm, lst in (('서로 반대', [k for k in mir if U[k]['cat'] != 'price'][:14]), ('상승 시작 전에만', [k for k in onlyu if U[k]['cat'] != 'price'][:8]), ('하락 시작 전에만', [k for k in onlyd if U[k]['cat'] != 'price'][:8]), ('둘 다 같은 쪽', same[:8])):
        for k in lst: M.append(f"| {nm} | {CATS[U[k]['cat']]} | {k} | {U[k]['level']:.0f} ({U[k]['z_level']:+.1f} · {U[k]['zm_level']:+.1f}) | {Dn[k]['level']:.0f} ({Dn[k]['z_level']:+.1f} · {Dn[k]['zm_level']:+.1f}) |")
    M += ['', '모두 과거 자료를 정리한 것이다. 투자 권유 아님']; od = os.path.join(HERE, 'out'); os.makedirs(od, exist_ok=True)
    open(os.path.join(od, 'pre_report.md'), 'w', encoding='utf-8').write('\n'.join(M) + '\n'); json.dump(out, open(os.path.join(od, 'pre_summary.json'), 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    print(len(M), '줄', {k: v['events'] for k, v in out['types'].items()}, {k: len(v) for k, v in out['compare'].items()})


if __name__ == '__main__':
    main()
