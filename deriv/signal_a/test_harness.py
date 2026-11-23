# -*- coding: utf-8 -*-
"""Signal A 시험대 확인 — 공통 계산(sa_common.py)이 맞는지 본다. 파이프라인이 계산 전에 매번 돌린다(종료 코드 0 = 통과).

1) 고정 자료: 릴리스 파일의 sha256 이 고정 기록과 같고, 끝 날짜가 state/freeze.json 의 end 를 넘지 않는다.
2) 연구소와 같은 숫자: 연구소 통과 신호(갈래 B, A4xu_B2xA1)와 갈래 A 최고 후보를 '연구소 결과의 거래일'(ref/lab_ref.json)로 넣어
   연구소 판정 가격(코스피200 연속 선물)으로 채점하면 앞·뒤·전체의 독립 거래 수와 적중이 연구소 판정과 같아야 한다.
   (연구소 '전체' = 앞 구간 거래(청산 ≤ 2023-12-31) + 뒤 구간 거래(신호 ≥ 2024-01-01)를 이어 붙인 것 — 해를 넘는 거래는 빠진다.)
   코스피 지수 기준 적중(Signal A 의 매매 기준)은 따로 적는다.
3) 계산끼리 맞는지: 위치 계산(fwd·thin_pos) = 거래표 계산(score·independent), 가짜 신호 시험의 재현성, 먼저 닿기, 윌슨 하한.
결과: state/harness.json {ok, at, checks[], lab{}}.
"""
import json
import os
import sys

import numpy as np
import pandas as pd

import sa_common as C

P1_END = pd.Timestamp('2023-12-31')


def lab_way(tr, px):
    """연구소 a08_validate.main_cross 와 같은 방식: 앞·뒤 따로, 전체 = 앞(청산 ≤ 2023) + 뒤(신호 ≥ 2024)."""
    t = C.prep(tr)
    both = pd.concat([t[t['exit'] <= P1_END], t[t['signal'] >= C.SPLIT]], ignore_index=True)
    return C.score(t, 1, px, C.START, P1_END), C.score(t, 1, px, C.SPLIT, C.END), C.score(both, 1, px)


def main():
    checks = []; lab = {}

    def chk(name, ok, detail=''):
        checks.append({'name': name, 'ok': bool(ok), 'detail': str(detail)}); print(('통과 ' if ok else '실패 ') + name, detail)

    D = C.Data()
    chk('고정 자료 sha256·끝 날짜', D.td[-1] <= C.END and D.X.shape[1] == C.FREEZE['n_features'], f'{D.td[0].date()}~{D.td[-1].date()} 지표 {D.X.shape[1]}개 거래일 {D.n}')
    chk('깨진 열은 빈칸', all(D.X[c].notna().sum() == 0 for c in C.BAD_COLS if c in D.X), ', '.join(C.BAD_COLS))
    ref = json.load(open(os.path.join(C.SA, 'ref', 'lab_ref.json'), encoding='utf-8'))['signals']
    for sid, v in ref.items():
        tr = pd.DataFrame(v['trades'], columns=['signal', 'exit']); d = int(v['direction']); L = v['lab']
        a, b, al = lab_way(tr, D.F)
        same = (a['n'] == L['dev_n'] and b['n'] == L['p2_n'] and al['n'] == L['all_n'] and abs(a['hit'] - L['dev_hit']) < 1e-9
                and abs(b['hit'] - L['p2_hit']) < 1e-9 and abs(al['hit'] - L['all_hit']) < 1e-9)
        chk(f'연구소와 같은 숫자(선물 기준) — 갈래 {v["lab_track"]} {sid[:28]}', same,
            f"앞 {a['n']}건 {C.pct(a['hit'])} · 뒤 {b['n']}건 {C.pct(b['hit'])} · 전체 {al['n']}건 {C.pct(al['hit'])} (연구소 {L['dev_n']}·{L['p2_n']}·{L['all_n']}건 {C.pct(L['all_hit'])})")
        ka, kb, _ = lab_way(tr, D.K); kall = C.score(tr, d, D.K)
        lab[sid] = {'lab_track': v['lab_track'], 'desc': v['desc'],
                    'futures': {'p1_n': a['n'], 'p1_hit': a['hit'], 'p2_n': b['n'], 'p2_hit': b['hit'], 'all_n': al['n'], 'all_hit': al['hit']},
                    'kospi': {'p1_n': ka['n'], 'p1_hit': ka['hit'], 'p2_n': kb['n'], 'p2_hit': kb['hit'], 'all_n': kall['n'], 'all_hit': kall['hit'], 'all_sum': kall['sum']}}
        print(f"   코스피 지수 기준(따로 적음): 앞 {ka['n']}건 {C.pct(ka['hit'])} · 뒤 {kb['n']}건 {C.pct(kb['hit'])} · 전체 {kall['n']}건 {C.pct(kall['hit'])} · 수익 합계 {100 * kall['sum']:+.1f}%")
    # 계산끼리 맞는지
    rng = np.random.default_rng(C.SEED); i0 = int(D.td.searchsorted(C.START)); ok_all = True; det = ''
    for h, delay in ((1, 0), (3, 1), (5, 0), (10, 1)):
        pos = np.sort(rng.choice(np.arange(i0, D.n), 400, replace=False)); r = D.fwd(h, delay)
        tp = D.thin_pos(pos, h, delay); s = C.score(D.trades_from_pos(pos, h, delay), 1, D.K)
        k1 = int((r[tp] > 0).sum()); same = (s['n'] == len(tp) and s['k'] == k1 and abs(s['sum'] - float(r[tp].sum())) < 1e-9)
        ok_all &= same; det += f'h{h}/늦춤{delay}: {s["n"]}건 {s["k"]}맞음 '
    chk('위치 계산 = 거래표 계산(독립 거래·적중·수익 합계)', ok_all, det)
    pos = np.sort(rng.choice(np.arange(i0, D.n - 12), 300, replace=False)); s = C.score(D.trades_from_pos(pos, 5), 1, D.K)
    p1 = C.placebo_same_year(D, s['t'], 1, h=5, n_iter=300); p2 = C.placebo_same_year(D, s['t'], 1, h=5, n_iter=300)
    b = C.base_for(D, s['t'], 5, 1)
    chk('가짜 신호 시험: 같은 씨앗이면 같은 값, 아무 날 신호는 가짜와 구별 안 됨(p > 0.01)', p1['p'] == p2['p'] and p1['p'] > 0.01 and abs(p1['fake_mean'] - b) < 0.05, f"p {p1['p']:.3f} 가짜 평균 {C.pct(p1['fake_mean'])} 아무 날 {C.pct(b)}")
    r5 = D.fwd(5); good = np.where((np.arange(D.n) >= i0) & (r5 > 0))[0]; s2 = C.score(D.trades_from_pos(np.sort(rng.choice(good, 200, replace=False)), 5), 1, D.K)
    p3 = C.placebo_same_year(D, s2['t'], 1, h=5, n_iter=300)
    chk('가짜 신호 시험: 미래를 본 신호는 잡아냄(p 최소)', s2['hit'] == 1.0 and p3['p'] <= 1 / 301 + 1e-12, f"적중 {C.pct(s2['hit'])} p {p3['p']:.4f}")
    y, ex = C.first_touch(D, 0.05); i = int(np.where(np.isfinite(y) & (np.arange(D.n) >= i0))[0][0]); o1 = D.o[i + 1]; j = ex[i]
    hit_ok = (D.h[j] >= o1 * 1.05) if y[i] == 1 else (D.l[j] <= o1 * 0.95)
    by = np.where(np.isfinite(y), y, np.nan); sy = D.trades_from_pos(pos, 5); sy['hit'] = y[pos[pos + 5 < D.n]]; sy = sy.dropna(); st = C.score(sy, 1, D.K)
    bb = C.base_for(D, st['t'], 5, 1, by)
    chk('먼저 닿기(±5%)와 같은 채점 방식 바탕(base_y)', hit_ok and 0.2 < np.nanmean(y[i0:]) < 0.8 and abs(st['hit'] - bb) < 0.15, f"아무 날 +5% 먼저 {C.pct(float(np.nanmean(y[i0:])))} · 아무 날 신호 {C.pct(st['hit'])} 대 바탕 {C.pct(bb)}")
    lo, hi = C.wilson(30, 35)
    chk('윌슨 하한(35건 중 30건 → 약 73.6%)', abs(lo - 0.7363) < 0.002, f'{lo:.4f}')
    ok = all(c['ok'] for c in checks)
    json.dump({'ok': ok, 'at': pd.Timestamp.now(tz='Asia/Seoul').strftime('%Y-%m-%d %H:%M'), 'data_end': str(D.td[-1].date()), 'checks': checks, 'lab': lab},
              open(os.path.join(C.STATE, 'harness.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('시험대', '통과' if ok else '실패')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
