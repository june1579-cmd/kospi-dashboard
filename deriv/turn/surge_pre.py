#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""surge_pre.py — 3거래일 안 +4% 급등 / -4% 급락 직전 10일의 변화와 공통점 (사용자 지시 2026-11-24).
- 정답(급등): 코스피 지수 종가 기준, 기준일 종가 대비 다음 3거래일 안에 종가가 한 번이라도 +4% 이상.
  급락은 -4% 이하. 조건을 채운 날이 3거래일 안에 이어지면 하나로 묶는다(묶음의 첫날 = 기준일).
- '10일 전 ~ 1일 전' = 기준일 9일 전 ~ 기준일(그날 종가까지 알려진 값). 상승·하락이 나오는 다음 날부터는 보지 않는다.
- 갈래: 바닥형(기준일까지 20일 등락이 0 이하인데 급등 / 0 이상인데 급락) · 추세 중형(같은 방향 20일 흐름 위에서 한 번 더).
- 지표 값·우연 비교 방식은 turn_pre.py 와 같다(지난 250일 자리 0~100, 날짜 통째로 옮긴 가짜 300번, 지수 비슷한 날 가짜 300번).
- 끝에 통과 기준 산정(제안)을 같은 자료로 계산해 붙인다 — 기준은 사용자가 정한다."""
import json, os, pickle, sys
import numpy as np
from scipy.stats import binom
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, '..', 'combo')); sys.path.insert(0, HERE)
from turn_probe import cat_of, CATS   # noqa: E402
from combo_probe import TRAIN_START   # noqa: E402
from turn_pre import measures   # noqa: E402
H, TH, LB = 3, 0.04, 20
OFFS = np.arange(-10, 0); SHOW = [-10, -7, -5, -3, -2, -1]; NNULL = 300; MATCH = 'PF_등락_5d'
PERIODS = [('2010~15', 2010, 2015), ('2016~20', 2016, 2020), ('2021~25', 2021, 2025), ('2026', 2026, 2026)]
NTEST = 100000   # 신호 찾기에서 시험할 조합 가짓수(보정용, 넉넉히)


def episodes(flag):
    days = np.where(flag)[0]; eps = []
    for d in days:
        if eps and d - eps[-1][-1] <= H: eps[-1].append(int(d))
        else: eps.append([int(d)])
    return eps


def min_hits(N, p, alpha):
    for k in range(N + 1):
        if binom.sf(k - 1, N, p) < alpha: return k
    return None


def main():
    panel = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, '..', 'uni', 'out', 'panel.pkl')
    D = pickle.load(open(panel, 'rb')); X = D['X']; td = X.index; n = len(td); yr = td.year.values
    kc = D['P']['KOSPI']['close'].reindex(td).values.astype(float); i0 = int(td.searchsorted(TRAIN_START))
    up = np.zeros(n, bool); dn = np.zeros(n, bool)
    for t in range(n - H):
        w = kc[t + 1:t + 1 + H]
        if not (np.isfinite(kc[t]) and np.isfinite(w).all()): continue
        up[t] = w.max() / kc[t] - 1 >= TH; dn[t] = w.min() / kc[t] - 1 <= -TH
    r20 = np.full(n, np.nan); r20[LB:] = kc[LB:] / kc[:-LB] - 1
    R = X.rolling(250, min_periods=120).rank(pct=True).values * 100; cols = list(X.columns); cat = np.array([cat_of(x) for x in cols]); rs = np.random.default_rng(5)
    lo_ = i0 + 10; span = n - lo_; sh = rs.integers(60, span - 60, size=NNULL); mj = cols.index(MATCH)
    z_of = lambda real, nul: (real - np.nanmean(nul, 0)) / (np.nanstd(nul, 0) + 1e-9); get = lambda pos: R[pos[:, None] + OFFS[None, :]]
    out = dict(last_day=str(td[-1].date()), rule=f'코스피 종가, 다음 {H}거래일 안 ±{TH * 100:.0f}%, {H}일 안에 이어지면 1번', features=len(cols), types={})
    ep_up = [e[0] for e in episodes(up) if e[0] >= lo_ - 1]; ep_dn = [e[0] for e in episodes(dn) if e[0] >= lo_ - 1]
    base = dict(up=up, down=dn)
    types = [('up', '급등 전체 (+4%)', ep_up), ('up_bottom', '급등 · 바닥형 (앞 20일 0 이하)', [t for t in ep_up if r20[t] <= 0]), ('up_trend', '급등 · 추세 중형 (앞 20일 0 초과)', [t for t in ep_up if r20[t] > 0]),
             ('down', '급락 전체 (-4%)', ep_dn), ('down_top', '급락 · 고점형 (앞 20일 0 이상)', [t for t in ep_dn if r20[t] >= 0]), ('down_trend', '급락 · 추세 중형 (앞 20일 0 미만)', [t for t in ep_dn if r20[t] < 0])]
    M = [f'# 3거래일 안 ±4% 급등·급락 직전 10일의 변화와 공통점 (2010-01 ~ {td[-1].date()})', '',
         f'- 정답 = 코스피 종가가 기준일 종가 대비 다음 {H}거래일 안에 +4% 이상(급등) / -4% 이하(급락). {H}일 안에 이어지면 1번으로 묶고 묶음 첫날이 기준일.',
         '- 본 구간 = 기준일 9일 전 ~ 기준일(그날 종가까지 알려진 값). 표의 "-1일" = 기준일.',
         '- 숫자 = 지난 250일 가운데 몇 번째 자리(0 가장 낮음 · 50 보통 · 100 가장 높음)의 평균. 순매수 지표는 낮을수록 많이 판 것.',
         '- z = 날짜를 통째로 옮긴 우연과의 차이. 지수 감안 z = 지수가 비슷하게 움직인 다른 날과의 차이(이게 커야 지수 움직임만으로 설명되지 않는다).',
         '- 바닥형/고점형 = 기준일까지 20일 흐름과 반대 방향의 급변, 추세 중형 = 같은 방향 흐름 위에서 한 번 더.', '']
    summ = []
    for key, lab, ts in types:
        ev = np.array(ts, int) + 1; ev = ev[(ev - 10 >= 0) & (ev < n)]; E = len(ev)
        if E < 5: summ.append((lab, E)); continue
        A = get(ev); real = measures(A); path = np.nanmean(A, 0)
        nul = [measures(get(lo_ + (ev - lo_ + int(s)) % span)) for s in sh]; Z = {k: z_of(real[k], np.array([x[k] for x in nul])) for k in real}
        ok = np.zeros(n, bool); ok[lo_:] = np.isfinite(R[lo_:, mj])
        for p in ev: ok[max(p - 10, 0):p + H + 1] = False
        binof = lambda d: np.clip((np.nan_to_num(R[d, mj], nan=0) // 10).astype(int), 0, 9); bins = binof(np.arange(n)); pool = [np.where(ok & (bins == b))[0] for b in range(10)]
        eb = binof(ev - 1); usable = np.isfinite(R[ev - 1, mj]); mn = []
        for _ in range(NNULL):
            pos = np.array([rs.choice(pool[b]) + 1 if u and len(pool[b]) else p for p, b, u in zip(ev, eb, usable)]); mn.append(measures(get(pos)))
        ZM = {k: z_of(real[k], np.array([x[k] for x in mn])) for k in ('level', 'trend', 'late')}; ctrl = {k: np.nanmean(np.array([x[k] for x in mn]), 0) for k in ('level', 'trend', 'late')}
        per = {}
        for pn, a, b in PERIODS:
            m = (yr[ev] >= a) & (yr[ev] <= b); per[pn] = dict(n=int(m.sum()), **({k: v for k, v in measures(A[m]).items() if k in ('level',)} if m.sum() else {}))
        rec = {}
        for j, col in enumerate(cols):
            if not np.isfinite(path[:, j]).all(): continue
            rec[col] = dict(cat=str(cat[j]), path=[round(float(x), 1) for x in path[:, j]], level=round(float(real['level'][j]), 1), z_level=round(float(Z['level'][j]), 2), zm_level=round(float(ZM['level'][j]), 2), ctrl_level=round(float(ctrl['level'][j]), 1),
                            trend=round(float(real['trend'][j]), 1), z_trend=round(float(Z['trend'][j]), 2), zm_trend=round(float(ZM['trend'][j]), 2), late=round(float(real['late'][j]), 1), z_late=round(float(Z['late'][j]), 2), zm_late=round(float(ZM['late'][j]), 2),
                            per={pn: (round(float(per[pn]['level'][j]), 1) if per[pn]['n'] else None) for pn, _, _ in PERIODS})
        bp = {pn: per[pn]['n'] for pn, _, _ in PERIODS}
        out['types'][key] = dict(label=lab, events=E, dates=[str(td[p - 1].date()) for p in ev], by_period=bp, feat=rec); summ.append((lab, E))
        ix = [OFFS.tolist().index(o) for o in SHOW]; ph = ' | '.join(f'{o}일' for o in SHOW); pc = lambda v: ' | '.join(f"{v['path'][i]:.0f}" for i in ix)
        pr = lambda v: ' / '.join('—' if v['per'][pn] is None else f"{v['per'][pn]:.0f}" for pn, _, _ in PERIODS)
        strong = lambda k, v: abs(v['z_' + k]) >= 3 and abs(v['zm_' + k]) >= 2
        M += [f'## {lab} — {E}번 (' + ' · '.join(f'{pn} {bp[pn]}번' for pn in bp) + ')', '']
        M += ['우연과 뚜렷이 달랐던 지표 수 (|z| 3 이상 / 그중 지수 감안 |z| 2 이상 / 지표 수):', '', '| 묶음 | 기준일 자리 | 10일간 변화 | 막판 3일 변화 |', '|---|---|---|---|']
        for ck in CATS:
            vs = [v for v in rec.values() if v['cat'] == ck]
            if vs: M.append(f"| {CATS[ck]} | " + ' | '.join(f"{sum(abs(v['z_' + k]) >= 3 for v in vs)} / {sum(strong(k, v) for v in vs)} / {len(vs)}" for k in ('level', 'trend', 'late')) + ' |')
        M.append('')
        full = key in ('up', 'down'); nshow = 12 if full else 8
        M += ['### 가. 기준일에 한쪽으로 치우쳐 있던 지표 (지수 감안 |z| 순, 지수·가격 묶음 제외)', '', f'| 묶음 | 지표 | {ph} | z | 지수 감안 z (다른 날 평균) | 기간별 기준일 자리 ' + '/'.join(p[0] for p in PERIODS) + ' |', '|---|---|' + '---|' * (len(SHOW) + 3)]
        for k, v in sorted([(k, v) for k, v in rec.items() if v['cat'] != 'price' and abs(v['z_level']) >= 2], key=lambda t: -abs(t[1]['zm_level']))[:nshow]:
            M.append(f"| {CATS[v['cat']]} | {k} | {pc(v)} | {v['z_level']:+.1f} | {v['zm_level']:+.1f} ({v['ctrl_level']:.0f}) | {pr(v)} |")
        M += ['', '### 나. 10일 동안 꾸준히 움직인 지표 (지수 감안 |z| 순, 지수·가격 제외)', '', f'| 묶음 | 지표 | {ph} | 변화 | z | 지수 감안 z |', '|---|---|' + '---|' * (len(SHOW) + 3)]
        for k, v in sorted([(k, v) for k, v in rec.items() if v['cat'] != 'price' and abs(v['z_trend']) >= 2], key=lambda t: -abs(t[1]['zm_trend']))[:nshow]:
            M.append(f"| {CATS[v['cat']]} | {k} | {pc(v)} | {v['trend']:+.0f} | {v['z_trend']:+.1f} | {v['zm_trend']:+.1f} |")
        if full:
            M += ['', '### 다. 막판 3일에 급히 움직인 지표 (지수 감안 |z| 순, 지수·가격 제외)', '', f'| 묶음 | 지표 | {ph} | 막판 변화 | z | 지수 감안 z |', '|---|---|' + '---|' * (len(SHOW) + 3)]
            for k, v in sorted([(k, v) for k, v in rec.items() if v['cat'] != 'price' and abs(v['z_late']) >= 2], key=lambda t: -abs(t[1]['zm_late']))[:nshow]:
                M.append(f"| {CATS[v['cat']]} | {k} | {pc(v)} | {v['late']:+.0f} | {v['z_late']:+.1f} | {v['zm_late']:+.1f} |")
            M += ['', '### 라. 지수·가격 묶음 (참고 — 정답 정의와 얽혀 있음)', '', f'| 지표 | {ph} | z | 지수 감안 z |', '|---|' + '---|' * (len(SHOW) + 2)]
            for k, v in sorted([(k, v) for k, v in rec.items() if v['cat'] == 'price'], key=lambda t: -abs(t[1]['z_level']))[:6]:
                M.append(f"| {k} | {pc(v)} | {v['z_level']:+.1f} | {v['zm_level']:+.1f} |")
        M.append('')
    # ---- 급등 직전과 급락 직전을 나란히
    if 'up' in out['types'] and 'down' in out['types']:
        U, Dn = out['types']['up']['feat'], out['types']['down']['feat']; both = [k for k in U if k in Dn and U[k]['cat'] != 'price']
        mir = sorted([k for k in both if U[k]['z_level'] * Dn[k]['z_level'] < 0 and min(abs(U[k]['z_level']), abs(Dn[k]['z_level'])) >= 2.5], key=lambda k: -min(abs(U[k]['z_level']), abs(Dn[k]['z_level'])))
        same = sorted([k for k in both if U[k]['z_level'] * Dn[k]['z_level'] > 0 and min(abs(U[k]['z_level']), abs(Dn[k]['z_level'])) >= 2.5], key=lambda k: -min(abs(U[k]['z_level']), abs(Dn[k]['z_level'])))
        out['compare'] = dict(mirror=mir, same=same)
        M += ['## 급등 직전과 급락 직전을 나란히 (기준일 자리, 지수·가격 제외)', '', f'- 서로 반대였던 지표 {len(mir)}개 · 둘 다 같은 쪽이던 지표 {len(same)}개 (같은 쪽 = 방향이 아니라 "큰 변동이 온다"는 신호일 수 있음)', '',
              '| 구분 | 묶음 | 지표 | 급등 직전 (z · 지수 감안 z) | 급락 직전 (z · 지수 감안 z) |', '|---|---|---|---|---|']
        for nm, lst in (('서로 반대', mir[:12]), ('같은 쪽', same[:12])):
            for k in lst: M.append(f"| {nm} | {CATS[U[k]['cat']]} | {k} | {U[k]['level']:.0f} ({U[k]['z_level']:+.1f} · {U[k]['zm_level']:+.1f}) | {Dn[k]['level']:.0f} ({Dn[k]['z_level']:+.1f} · {Dn[k]['zm_level']:+.1f}) |")
        M.append('')
    # ---- 통과 기준 산정(제안)
    M += ['## 통과 기준 산정 (제안 — 기준은 사용자가 정함)', '',
          f'- 아무 날이나 골랐을 때 맞을 확률(기준일 종가 대비 {H}일 안 ±4%)과, 조합 {NTEST:,}가지를 시험해도 우연으로는 5% 미만인 최소 적중 수. 앞·뒤 기간은 단독 1% 미만.', '',
          '| 정답 | 묶음 수 (앞 2010~23 / 뒤 2024~ / 2026) | 아무 날 확률 전체 · 앞 · 뒤 · 2026 · 2025까지 | 전체 최소 적중 (신호 수: 적중) | 앞 최소 적중 | 뒤 최소 적중 |', '|---|---|---|---|---|---|']
    crit = {}
    for key, lab, ts in (('up', '+4% 급등', ep_up), ('down', '-4% 급락', ep_dn)):
        f = base[key]; valid = np.zeros(n, bool); valid[lo_ - 1:n - H] = True; ty = np.array([yr[t] for t in ts])
        pr_ = lambda m: float(f[valid & m].mean()); p_all, p_f, p_b, p26, p25 = pr_(np.ones(n, bool)), pr_(yr <= 2023), pr_(yr >= 2024), pr_(yr == 2026), pr_(yr <= 2025)
        tb = {N: min_hits(N, p_all, 0.05 / NTEST) for N in (10, 15, 20, 25, 30, 40)}; tf = {N: min_hits(N, p_f, 0.01) for N in (5, 8, 10, 15)}; tbk = {N: min_hits(N, p_b, 0.01) for N in (5, 8, 10, 15)}; t25 = {N: min_hits(N, p25, 0.01) for N in (5, 8, 10, 15)}
        crit[key] = dict(events=len(ts), front=int((ty <= 2023).sum()), back=int((ty >= 2024).sum()), y2026=int((ty == 2026).sum()), base=dict(all=p_all, front=p_f, back=p_b, y2026=p26, to2025=p25), min_all=tb, min_front=tf, min_back=tbk, min_to2025=t25)
        fm = lambda d: ' · '.join(f'{N}:{k}' for N, k in d.items())
        M.append(f"| {lab} | {len(ts)} ({crit[key]['front']} / {crit[key]['back']} / {crit[key]['y2026']}) | {p_all * 100:.1f}% · {p_f * 100:.1f}% · {p_b * 100:.1f}% · {p26 * 100:.1f}% · {p25 * 100:.1f}% | {fm(tb)} | {fm(tf)} | {fm(tbk)} |")
    out['criteria_calc'] = crit
    M += ['', '- 뒤 기간(특히 2026)은 아무 날이나 사도 맞을 확률이 크게 높다 → 전체 적중률만 보면 2026에 몰린 신호가 좋아 보인다. 그래서 기간별·같은 해 안 가짜 신호 비교가 꼭 필요하다.', '', '모두 과거 자료를 정리한 것이다. 투자 권유 아님']
    od = os.path.join(HERE, 'out'); os.makedirs(od, exist_ok=True)
    open(os.path.join(od, 'surge_report.md'), 'w', encoding='utf-8').write('\n'.join(M) + '\n'); json.dump(out, open(os.path.join(od, 'surge_summary.json'), 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'), default=float)
    print(len(M), '줄', summ)


if __name__ == '__main__':
    main()
