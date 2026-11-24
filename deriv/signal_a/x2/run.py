# -*- coding: utf-8 -*-
"""X2 — 15가지 조건별 '시작지점에서 1~5거래일 안 +3% 닿을 확률'(앞 2010~2023 · 뒤 2024~2026-11-20). SPEC.md 그대로.

조건 정의는 t1/run.py(components)·w1/labform.py·w3/run.py(lab_age)·sa_common 의 것을 불러 쓴다.
연구소 코드에만 있는 두 식(13번 'down', 15번 vrank)은 a04_flows.py 의 식을 줄 그대로 옮겼다(SPEC 1절).
출력: x2/report.md, x2/out/table_a.csv·table_b.csv·signals.csv·done.json.
"""
import importlib.util
import json
import os
import sys
import time

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
SA = os.path.dirname(HERE)
for _p in (SA, os.path.join(SA, 'w1')):
    if _p not in sys.path: sys.path.insert(0, _p)
import sa_common as C  # noqa: E402
import labform as LF  # noqa: E402

OUT = os.path.join(HERE, 'out')
K = 0.03                       # +3%
NS = [1, 2, 3, 4, 5]
WIN = 5                        # 독립 신호: 앞 신호의 5거래일 창이 끝난 뒤
FIRST_N = 5
G4 = ['F0', 'F1', 'F2', 'ALL']
PERIODS = [('앞', C.START, C.SPLIT - pd.Timedelta(days=1), '2010~2023'), ('뒤', C.SPLIT, C.END, '2024~2026-11-20')]
DELAYS = [(0, '기본 시작지점(신호 다음 거래일 시가)'), (1, '4번 판: 하루 늦춘 시작지점(신호 다음다음 거래일 시가)')]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


# ------------------------------------------------------------------ 조건
def conditions(D):
    T1 = _load('t1_run', os.path.join(SA, 't1', 'run.py'))
    W3 = _load('w3_run', os.path.join(SA, 'w3', 'run.py'))
    comp = T1.components(D, False)
    live = comp['_live']; q = comp['Q']
    k2c = LF.k200_close(D); s5 = LF.sig5(D, k2c); reg = LF.regime(D, k2c); fl = LF.flows(D)
    ages = {t: LF.lab_age(D, t) for t in G4}
    X = D.X
    col = lambda c: LF.need_col(D, c)
    with np.errstate(invalid='ignore'):
        c1 = live & (q['dist'] > 0) & (q['dist'] <= 1.5)
        c2 = live & q['chg']['up1']
        m12 = c1 & c2
        b0_ref = D.first_only(m12, FIRST_N)
        # 3: 직전 5거래일 안에 (1·2) 날이 없음 — 1·2·3 = first_only(1&2, 5) 와 같아야 한다
        prev = pd.Series(m12.astype(int)).shift(1).rolling(FIRST_N, min_periods=1).sum().fillna(0).values
        c3 = live & (prev == 0)
        assert np.array_equal(m12 & c3, b0_ref), '3번 정의가 D.first_only 와 다름'
        c5 = live & (col('OW_Q_wall_top3') >= 0.40)
        c6 = live & (col('OW_Q_wall_share') >= 0.16)
        c7 = live & (col('OW_Q_wall_ratio12') >= 1.18)
        c8 = live & reg['above']
        dte = col('OW_Q_dte'); c9 = live & ((dte < 21) | (dte > 40))
        c10 = live & (q['dist'] > 0) & (q['dist'] <= 1.0) & comp['_flow']['fut']
        c11 = LF.k2_mask(D, ages, s5, G4, 1, band_pct=np.inf)
        c12 = LF.k2_mask(D, ages, s5, G4, np.inf, band_k=1.75)
        # 13: 연구소 a04_flows.py 라운드 46 — 'down' = new & ~roll & (오늘 벽 < 어제 벽). new·roll 은 W3.lab_age(연구소 234~243·421~441줄과 같음)
        _, orig = W3.lab_age(D)
        W = D.walls.copy(); W['date'] = pd.to_datetime(W['date']); W = W.drop_duplicates(['date', 'tag'], keep='last')
        down = {}
        for t in G4:
            g = W[W['tag'] == t].sort_values('date').set_index('date')
            kk = g['K'].astype(float).reindex(D.td).values; kp = np.r_[np.nan, kk[:-1]]
            down[t] = orig[t]['new'] & ~orig[t]['roll'] & (kk < kp)
        c13 = live & np.any([down[t] for t in G4], axis=0)
        c14 = live & fl['fut3']
        # 15: 연구소 vrank = sig5.rolling(250, min_periods=120).apply(lambda a: (a <= a[-1]).mean()) ≤ 0.8
        s5s = pd.Series(s5, index=D.td)
        vrank = s5s.rolling(250, min_periods=120).apply(lambda a: (a <= a[-1]).mean(), raw=True).values
        c15 = live & (vrank <= 0.8)
        # A0 = 연구소 K2(나이 ≤ 1 · 0 < 거리 ≤ 1.75σ 인 결제월 둘 이상) + 14
        band = s5 * 1.75; hits = {}
        for t in G4:
            dist = col(f'OW_{t}_wall_dist%'); hits[t] = (ages[t] <= 1) & (dist > 0) & (dist <= band)
        cnt = sum(hits[t].astype(int) for t in G4); k2m = live & (cnt >= 2)
        assert np.array_equal(k2m, LF.k2_mask(D, ages, s5, G4, 1, band_k=1.75)), 'K2 다시 만든 것이 labform.k2_mask 와 다름'
        ndn = sum((hits[t] & down[t]).astype(int) for t in G4)
        a0 = k2m & c14
        a0_13 = k2m & (ndn >= 1) & c14
    single = {1: c1, 2: c2, 3: c3, 4: live.copy(), 5: c5, 6: c6, 7: c7, 8: c8, 9: c9, 10: c10, 11: c11, 12: c12, 13: c13, 14: c14, 15: c15}
    b0 = b0_ref
    combo = [('B0 = 1·2·3', b0), ('B0 + 5', b0 & c5), ('B0 + 6', b0 & c6), ('B0 + 7', b0 & c7), ('B0 + 8', b0 & c8), ('B0 + 9', b0 & c9),
             ('B0 또는 10', b0 | c10), ('A0 = 11·12·14', a0), ('A0 + 13', a0_13), ('A0 + 15', a0 & c15), ('B0 또는 A0', b0 | a0),
             ('전부 그리고(1~3·5~9·11~15)', b0 & c5 & c6 & c7 & c8 & c9 & a0_13 & c15)]
    extra = {'B0_indep_d1_h5_all': int(len(D.thin_pos(np.flatnonzero(b0), 5, 1))), 'vrank_nan': int(np.isnan(vrank[live]).sum())}
    return single, combo, extra


NAMES = {1: '분기물 콜벽 지수 위 0~1.5%', 2: '벽 콜 미결제 전날보다 늘어남', 3: '직전 5거래일 안 1·2 함께 켜진 날 없음',
         4: '(시작지점 규칙) 모든 거래일 · 하루 늦춘 시작', 5: '분기물 상위3 행사가 콜 몫 ≥ 0.4', 6: '벽 하나의 몫 ≥ 0.16', 7: '벽 1위/2위 ≥ 1.18',
         8: '코스피200 종가 > 60일선', 9: '분기물 만기 21~40거래일 아님', 10: '분기물 콜벽 0~1% + 외국인 선물 3일 누적 순매수',
         11: '결제월 둘 이상 같은 날 새 콜벽(나이 ≤1)', 12: '결제월 둘 이상 벽이 0~1.75σ 안', 13: '새 벽이 옛 벽보다 아래로(하나 이상)',
         14: '외국인 선물 3일 누적 순매수', 15: '20일 변동성 지난 250일 하위 80%'}


# ------------------------------------------------------------------ 채점
def hit_table(D, delay):
    """hit[N-1, i] = 신호일 i → 시작 e = i+1+delay 시가, e..e+N-1 고가 최대 ≥ 시가×1.03 → 1/0, 창이 자료 밖이면 nan."""
    n = D.n; H = np.full((len(NS), n), np.nan)
    for i in range(n):
        e = i + 1 + delay
        if e >= n: continue
        thr = D.o[e] * (1 + K); run = -np.inf
        for k, N in enumerate(NS):
            j = e + N - 1
            if j >= n: break
            run = max(run, D.h[j]); H[k, i] = float(run >= thr)
    return H


def measure(D, mask, H, delay, a, b):
    per = np.asarray((D.td >= a) & (D.td <= b))
    pos = np.flatnonzero(np.asarray(mask, dtype=bool) & per)
    ind = D.thin_pos(pos, WIN, delay)
    out = {}
    for kind, p in (('독립', ind), ('전부', pos)):
        r = {'n': int(len(p))}
        for k, N in enumerate(NS):
            v = H[k, p]; v = v[np.isfinite(v)]
            r[f'n{N}'] = int(len(v)); r[f'k{N}'] = int(v.sum()); r[f'p{N}'] = (float(v.mean()) if len(v) else None)
        out[kind] = r
    return out, pos, ind


def pct(p, n):
    return '–' if (p is None or n < 10) else f'{100 * p:.1f}%'


def main():
    t0 = time.time(); os.makedirs(OUT, exist_ok=True)
    D = C.Data(); print('자료', D.n, '거래일', D.td[0].date(), '~', D.td[-1].date(), flush=True)
    single, combo, extra = conditions(D)
    print('조건 만들기 끝', round(time.time() - t0, 1), '초', extra, flush=True)
    rowsA, rowsB, sigs, base = [], [], [], {}
    for d, _ in DELAYS:
        H = hit_table(D, d); live = np.asarray(D.td >= C.START)
        for pn, a, b, _ in PERIODS:
            bm, _, _ = measure(D, live, H, d, a, b); base[(d, pn)] = bm['전부']
        for c, m in single.items():
            dd = 1 if c == 4 else d          # 4번 줄: 늦춘 시작지점
            if c == 4 and d == 1: continue
            Hc = H if dd == d else hit_table(D, dd)
            for pn, a, b, _ in PERIODS:
                r, pos, ind = measure(D, m, Hc, dd, a, b)
                for kind in ('독립', '전부'):
                    x = r[kind]; rowsA.append({'시작지점': d, '조건': c, '이름': NAMES[c], '구간': pn, '구분': kind, **x})
        for name, m in combo:
            for pn, a, b, _ in PERIODS:
                r, pos, ind = measure(D, m, H, d, a, b)
                for kind in ('독립', '전부'):
                    rowsB.append({'시작지점': d, '식': name, '구간': pn, '구분': kind, **r[kind]})
                if d == 0:
                    iset = set(ind.tolist())
                    for p in pos:
                        sigs.append({'식': name, '신호일': str(D.td[p].date()), '구간': pn, '독립': int(p in iset),
                                     **{f'맞음_N{N}_기본': (None if not np.isfinite(H[k, p]) else int(H[k, p])) for k, N in enumerate(NS)}})
        print('시작지점', d, '끝', round(time.time() - t0, 1), '초', flush=True)
    A = pd.DataFrame(rowsA); B = pd.DataFrame(rowsB)
    for df in (A, B):
        for N in NS: df[f'p{N}'] = df[f'p{N}'].astype(float).round(4)
    A.to_csv(os.path.join(OUT, 'table_a.csv'), index=False, encoding='utf-8')
    B.to_csv(os.path.join(OUT, 'table_b.csv'), index=False, encoding='utf-8')
    pd.DataFrame(sigs).to_csv(os.path.join(OUT, 'signals.csv'), index=False, encoding='utf-8')
    Bs = pd.DataFrame([{'시작지점': d, '구간': pn, **{k: v for k, v in r.items()}} for (d, pn), r in base.items()])
    Bs.to_csv(os.path.join(OUT, 'base.csv'), index=False, encoding='utf-8')
    write_report(A, B, base, extra)
    json.dump({'done': pd.Timestamp.now(tz='Asia/Seoul').strftime('%Y-%m-%d %H:%M'), 'data_end': str(C.END.date()), 'seconds': round(time.time() - t0, 1),
               'rows_a': len(A), 'rows_b': len(B), 'check': extra}, open(os.path.join(OUT, 'done.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('끝', round(time.time() - t0, 1), '초', flush=True)


# ------------------------------------------------------------------ 보고서
def _cells(r):
    return [pct(r[f'p{N}'], r[f'n{N}']) for N in NS]


def _base_line(base, d, pn):
    r = base[(d, pn)]
    return f"{r['n']:,}일 · " + ' / '.join(f'N{N} {pct(r[f"p{N}"], r[f"n{N}"])}' for N in NS)


def write_report(A, B, base, extra):
    L = ['# X2 — 15가지 조건별 \'1~5거래일 안 +3% 닿을 확률\'', '',
         f"자료: 릴리스 signal-a-data-v1(끝 {C.END.date()}). 앞 = 2010~2023, 뒤 = 2024~2026-11-20(신호일 기준). 정의는 SPEC.md.",
         '맞음 = 시작지점 날부터 N거래일 안(시작일 = 1일째) 코스피 지수 고가가 시작가 × 1.03 이상. N 마다 누적 확률.',
         '독립 = 앞 독립 신호의 5거래일 창이 끝난 뒤 신호만. 10건 미만은 % 로 적지 않음(–). 확률의 n 은 N 창이 자료 안에 든 신호만.', '',
         f"검산: B0 를 늦춤 1·보유 5 로 솎은 독립 거래 수(2010~끝) = {extra['B0_indep_d1_h5_all']} (final_v1.json 관찰 목록 ① 기록 47).", '']
    for d, dlab in DELAYS:
        L += [f'## {dlab}', '', '### 아무 날(바탕)', '']
        for pn, _, _, plab in PERIODS: L.append(f'- {pn}({plab}): ' + _base_line(base, d, pn))
        L += ['', '### 표 A — 조건 하나씩', '']
        if d == 1: L += ['(4번 줄은 기본 시작지점 표에 있음 — 4번 자체가 늦춘 시작지점이다.)', '']
        hdr = '| # | 조건 | 구간 | 독립 수 | N1 | N2 | N3 | N4 | N5 | 전부 수 | N1 | N2 | N3 | N4 | N5 |'
        L += [hdr, '|' + '---|' * 15]
        a = A[A['시작지점'] == d]
        for c in sorted(a['조건'].unique()):
            for pn, _, _, _ in PERIODS:
                ri = a[(a['조건'] == c) & (a['구간'] == pn) & (a['구분'] == '독립')].iloc[0]
                ra = a[(a['조건'] == c) & (a['구간'] == pn) & (a['구분'] == '전부')].iloc[0]
                L.append(f"| {c} | {NAMES[c]} | {pn} | {ri['n']:,} | " + ' | '.join(_cells(ri)) + f" | {ra['n']:,} | " + ' | '.join(_cells(ra)) + ' |')
        L += ['', '### 표 B — 합친 식', '', '| 식 | 구간 | 독립 수 | N1 | N2 | N3 | N4 | N5 | 전부 수 | N1 | N2 | N3 | N4 | N5 |', '|' + '---|' * 14]
        bb = B[B['시작지점'] == d]
        for name in bb['식'].drop_duplicates():
            for pn, _, _, _ in PERIODS:
                ri = bb[(bb['식'] == name) & (bb['구간'] == pn) & (bb['구분'] == '독립')].iloc[0]
                ra = bb[(bb['식'] == name) & (bb['구간'] == pn) & (bb['구분'] == '전부')].iloc[0]
                L.append(f"| {name} | {pn} | {ri['n']:,} | " + ' | '.join(_cells(ri)) + f" | {ra['n']:,} | " + ' | '.join(_cells(ra)) + ' |')
        L.append('')
    L += ['## 정의를 연구소와 다르게 한 것', '',
          '1. 11번에 위클리는 넣지 않음(고정 자료 벽 표에 위클리 결제월 없음). 묶음 = 근월·차월·차차월·합산(연구소 A 규칙과 같음).',
          '2. 11·12 단독은 연구소 K2 를 둘로 나눈 것(11 = 띠 없음, 12 = 나이 없음). A0 는 나누지 않은 연구소 K2 그대로.',
          '3. 13 단독은 K2·띠 없이 묶음 가운데 하나라도 아래로 옮겨 간 새 벽. A0+13 은 연구소 K2dn 그대로.',
          '4. 3 단독은 \'직전 5거래일 안에 1·2 함께 켜진 날 없음\' — 그 자체로는 대부분의 날이다.',
          '5. 외국인 선물은 고정 자료 F_외국인_1d(연구소는 자기 수급 파일). 가격은 코스피 지수(연구소는 코스피200 선물).', '',
          '## 읽을 때 주의', '',
          '- 15개 조건과 문턱은 앞선 연구에서 결과를 보고 고른 것이 섞여 있다 — 이 표의 확률도 그 고른 몫을 안고 있다(특히 B0 계열 앞 구간).',
          '- 독립 신호가 10건 안팎인 줄은 한두 건으로 확률이 크게 흔들린다. 같은 뿌리 식(B0 계열)은 신호가 많이 겹친다 — 따로 센 근거로 보지 말 것.',
          '- 투자 권유 아님.', '']
    open(os.path.join(HERE, 'report.md'), 'w', encoding='utf-8').write('\n'.join(L))


if __name__ == '__main__':
    main()
