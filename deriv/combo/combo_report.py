#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""combo_report.py — combo_probe.py 의 맞춤별 결과(out/fit_*.json)를 모아 표로 만든다. → out/report.md · out/summary.json"""
import glob
import json
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__)); OUT = os.environ.get('COMBO_OUT') or os.path.join(HERE, 'out')
PERIODS = [('2016~2026', range(2016, 2027)), ('2016~2023', range(2016, 2024)), ('2024~2026', range(2024, 2027))]
DIR = ['오름', '내림']


def pct(a, b): return '—' if not b else f'{a / b * 100:.1f}%'
def num(x): return f'{x:,.0f}'


def main():
    fits = {}
    for fp in glob.glob(os.path.join(OUT, 'fit_*.json')):
        o = json.load(open(fp, encoding='utf-8')); fits[o['fit']] = o
    full = fits.get('FULL'); wf = {int(k): v for k, v in fits.items() if k != 'FULL'}; S = dict(fits=sorted(fits), periods={})
    M = ['# 조건 조합 전부 훑기 검증 결과', '']
    if fits:
        any_ = next(iter(fits.values()))
        M += [f"- 자료: 통합 예측 연구소 자료표(지표 {any_['features']}개) · 대상: 코스피200 선물, 신호 다음 날 시가 → 1·3·5·10·20일째 종가, 오름·내림",
              '- 조건: 연구소와 같은 꼴(학습 구간 분위 하위 10·20%, 상위 20·10%). 서로 다른 지표의 조건을 1~4개 묶음. 학습 신호일 35일 미만인 조합은 통과할 수 없으므로 세지 않음(빠지는 것 없음).',
              '- 거래는 겹치지 않게 솎음(연구소 규칙). 가짜 수익 = 수익을 1년 이상 통째로 옮긴 것.', '']
    # ---------------- 1) 크기와 시간
    M += ['## 1. 조합이 몇 개이고 다 보는 데 얼마나 걸리나', '', '| 맞춤 | 조건 수 | 1개 | 2개 조합 | 3개 조합 | 4개 조합 | 계산 시간 | 4개 조합을 다 봤나 |', '|---|---|---|---|---|---|---|---|']
    size = {}
    for k in (['FULL'] if full else []) + sorted(wf):
        o = fits[str(k)]; e = o['enum']; cov = '다 봄' if not o['level4_stopped'] else f"{o['l3_expanded'] / max(o['l3_total'], 1) * 100:.0f}%만(시간 제한)"
        if o.get('maxlevel', 4) < 4: cov = '안 봄'
        M.append(f"| {'전체 기간' if k == 'FULL' else str(k) + '년 시험'} | {o['cond']:,} | {e[0]:,} | {e[1]:,} | {e[2]:,} | {e[3]:,} | {o['seconds']:.0f}초({o['threads']}코어) | {cov} |")
        size[str(k)] = dict(cond=o['cond'], enum=e, seconds=o['seconds'], threads=o['threads'], l4_cov=(1.0 if not o['level4_stopped'] else o['l3_expanded'] / max(o['l3_total'], 1)))
    S['size'] = size
    if full:
        C = full['cond']; e = full['enum']; tot = sum(e); per = full['seconds'] * full['threads'] / max(tot, 1) * 1e6
        M += ['', f"- 조건 {C:,}개로 만들 수 있는 조합(같은 지표끼리 포함한 단순 계산): 2개 {C * (C - 1) // 2:,} · 3개 {C * (C - 1) * (C - 2) // 6:,} · 4개 {C * (C - 1) * (C - 2) * (C - 3) // 24:,}",
              f"- 그중 신호일 35일 이상이라 실제로 판정 대상이 되는 것: 2개 {e[1]:,} · 3개 {e[2]:,} · 4개 {e[3]:,}{'(시간 제한으로 일부)' if full['level4_stopped'] else ''}",
              f"- 속도: 조합 1개에 약 {per:.2f}마이크로초(코어 1개 기준, 5개 보유일 × 2방향 판정과 가짜 수익 {len(full['null_shifts'])}번 포함)"]
        S['speed_us_per_combo_core'] = per
    # ---------------- 2) 전체 기간에서 통과 숫자를 채우는 조합: 실제 대 가짜
    if full:
        sel = np.array(full['sel']); seln = np.array(full['seln']); hist = np.array(full['hist']); histn = np.array(full['histn']); nb = len(full['null_shifts']) or 1
        nt = full.get('null_types') or ['global'] * nb; G = np.array([t == 'global' for t in nt]); Yr = ~G
        mean_ = lambda arr, m: float(arr[m].mean()) if m.any() else float('nan')
        M += ['', '## 2. 전체 기간에서 통과 숫자를 채우는 조합 수 — 실제 수익 대 가짜 수익', '',
              '가짜 수익은 두 가지다. "통째로" = 수익을 1년 이상 통째로 옮김. "해 안에서만" = 해마다 그 해 안에서만 옮김(그 해가 강세장이었다는 사실은 그대로 남으므로, 강세장에 켜져 있었을 뿐인 조합은 가짜에서도 통과한다 — 더 엄한 비교).', '',
              '| 규칙 | 조합 크기 | 실제 | 가짜(통째로) | 가짜(해 안에서만) | 오름: 실제 / 통째로 / 해 안 | 내림: 실제 / 통째로 / 해 안 |', '|---|---|---|---|---|---|---|']
        S['full'] = {}
        for r, rn in enumerate(full['rules']):
            for L in range(4):
                a = int(sel[L, r].sum()); bs = seln[:, L, r].sum(axis=(1, 2)).astype(float)
                if a == 0 and bs.sum() == 0: continue
                ud = [seln[:, L, r, :, d].sum(axis=1).astype(float) for d in range(2)]; up = int(sel[L, r, :, 0].sum()); dn = int(sel[L, r, :, 1].sum())
                M.append(f"| {rn} | {L + 1}개 | {a:,} | {mean_(bs, G):,.1f} | {mean_(bs, Yr):,.1f} | {up:,} / {mean_(ud[0], G):,.1f} / {mean_(ud[0], Yr):,.1f} | {dn:,} / {mean_(ud[1], G):,.1f} / {mean_(ud[1], Yr):,.1f} |")
                S['full'][f'{r}|{L + 1}'] = dict(rule=rn, real=a, null_global=mean_(bs, G), null_year=mean_(bs, Yr), null_each=[int(x) for x in bs], up=up, up_null_global=mean_(ud[0], G), up_null_year=mean_(ud[0], Yr), dn=dn, dn_null_global=mean_(ud[1], G), dn_null_year=mean_(ud[1], Yr))
        if 'distinct' in full:
            M += ['', '같은 날짜에 켜지는 조합은 사실상 같은 신호다. 신호일이 서로 다른 것만 세면:', '']
            for rn, d in full['distinct'].items():
                M.append(f"- {rn}: 조합 {d['count']:,}개 → 신호일이 다른 것 {d['distinct_signal_days']:,}개" + (' (기록 한도 넘침 — 일부만 셈)' if full.get('hash_overflow') else ''))
            S['distinct'] = full['distinct']
        M += ['', '적중률 꼬리(35거래 이상인 조합 가운데 적중률이 높은 것의 수, 5개 보유일 × 2방향 합계 — 실제 / 가짜 통째로 / 가짜 해 안에서만):', '', '| 조합 크기 | 판정 대상 | 80% 이상 | 85% 이상 | 90% 이상 |', '|---|---|---|---|---|']
        S['tail'] = {}
        for L in range(4):
            h = hist[L].sum(axis=(0, 1)); hb = histn[:, L].sum(axis=(1, 2)).astype(float)
            if h.sum() == 0: continue
            row = [f'{L + 1}개', f'{int(h.sum()):,}']; S['tail'][L + 1] = dict(total=int(h.sum()))
            for b0 in (16, 17, 18):
                g_ = float(hb[G][:, b0:].sum(axis=1).mean()) if G.any() else float('nan'); y_ = float(hb[Yr][:, b0:].sum(axis=1).mean()) if Yr.any() else float('nan')
                row.append(f'{int(h[b0:].sum()):,} / {g_:,.1f} / {y_:,.1f}'); S['tail'][L + 1][f'ge{b0 * 5}'] = [int(h[b0:].sum()), g_, y_]
            M.append('| ' + ' | '.join(row) + ' |')
        if 'beam' in full:
            M += ['', '## 3. 지금 연구소 방식(A6)이 닿는 범위', '', 'A6 은 조건 2개 조합은 전부 훑어 상위 400개를, 3개 조합은 상위 40쌍에 조건 하나씩 붙인 것(최대 240개)만 후보로 삼는다. 그 후보를 같은 잣대로 정확히 재면:', '',
                  '| 조합 크기 | A6 후보 수 | 그중 통과 숫자 채움 | 그중 관찰 숫자 채움 | 전부 훑었을 때 통과 숫자 | 전부 훑었을 때 관찰 숫자 |', '|---|---|---|---|---|---|']
            bm = {1: [0, 0, 0], 2: [0, 0, 0], 3: [0, 0, 0]}
            for v in full['beam'].values():
                for L in ('1', '2', '3'):
                    for q in range(3): bm[int(L)][q] += v[L][q]
            for L in (1, 2, 3): M.append(f"| {L}개 | {bm[L][0]:,} | {bm[L][1]:,} | {bm[L][2]:,} | {int(sel[L - 1, 0].sum()):,} | {int(sel[L - 1, 1].sum()):,} |")
            S['beam'] = {str(k): v for k, v in bm.items()}
    # ---------------- 4) 걸어가며 검증
    if wf:
        any_ = next(iter(wf.values())); rules = any_['rules']; HS = any_['H']
        M += ['', '## 4. 지난 자료에서 고른 조합이 다음 해에 맞았나', '', '해마다 그 해 이전 자료만으로 조건(분위)을 정하고 조합을 전부 훑어 규칙에 맞는 것을 고른 뒤, 그 해에 낸 신호만 채점했다.',
              '"바탕"은 같은 해·같은 보유일에 아무 날이나 들어갔을 때의 확률(거래 수로 가중).', '']
        def base_rate(o, h, dr):
            v, u = o['base'][str(h)]; return (u / v if dr == 0 else 1 - u / v) if v else 0.5
        for pn, yrs in PERIODS:
            ys = [y for y in yrs if y in wf]
            if not ys: continue
            M += [f'### {pn} ({len(ys)}개 해)', '', '고른 조합을 하나하나 따로 채점(겹치는 조합이 많아 거래 수는 부풀어 있음):', '',
                  '| 방향 | 규칙 | 조합 크기 | 고른 수(해 평균) | 가짜(통째로)면 | 가짜(해 안)면 | 학습 적중 | 다음 해 적중 | 바탕 | 차이 | 다음 해 거래 |', '|---|---|---|---|---|---|---|---|---|---|---|']
            P = {}
            for dr in range(2):
                for r, rn in enumerate(rules):
                    for L in range(4):
                        ns = nn_ = ny_ = trn = trh = ten = teh = bw = 0.0
                        for y in ys:
                            o = wf[y]; sel = np.array(o['sel']); seln = np.array(o['seln']); pool = np.array(o['pool']); nt_ = o.get('null_types') or ['global'] * len(o['null_shifts'])
                            g_ = np.array([t == 'global' for t in nt_]); sb = seln[:, L, r, :, dr].sum(axis=1).astype(float)
                            ns += sel[L, r, :, dr].sum(); nn_ += sb[g_].mean() if g_.any() else 0.0; ny_ += sb[~g_].mean() if (~g_).any() else 0.0
                            for hi, h in enumerate(HS):
                                p = pool[L, r, hi, dr]; trn += p[0]; trh += p[1]; ten += p[2]; teh += p[3]; bw += p[2] * base_rate(o, h, dr)
                        if ns == 0: continue
                        d = (teh / ten - bw / ten) * 100 if ten else None
                        M.append(f"| {DIR[dr]} | {rn} | {L + 1}개 | {ns / len(ys):,.0f} | {nn_ / len(ys):,.0f} | {ny_ / len(ys):,.0f} | {pct(trh, trn)} | {pct(teh, ten)} | {pct(bw, ten)} | {'—' if d is None else f'{d:+.1f}%p'} | {num(ten)} |")
                        P[f'{dr}|{r}|{L + 1}'] = dict(sel_per_year=ns / len(ys), null_global_per_year=nn_ / len(ys), null_year_per_year=ny_ / len(ys), train_hit=trh / trn if trn else None, test_hit=teh / ten if ten else None, base=bw / ten if ten else None, test_n=ten)
            M += ['', '고른 조합들을 하나의 신호로 합쳐 채점(그날 켜진 조합이 k개 이상이면 신호, 겹치지 않게 솎음) — 실제로 매매한다면 이쪽이 맞는 숫자:', '',
                  '| 방향 | 규칙 | 조합 크기 | 켜진 조합 수 | 거래 | 적중 | 바탕 | 차이 |', '|---|---|---|---|---|---|---|---|']
            Vt = {}
            for y in ys:
                o = wf[y]
                for L, r, h, dr, km, raw, tr_, hit in o['vote_signals']:
                    k = (dr, r, L, km); v = Vt.setdefault(k, [0, 0, 0.0]); v[0] += tr_; v[1] += hit; v[2] += tr_ * base_rate(o, h, dr)
            Pv = {}
            for (dr, r, L, km), (tn, th, bw) in sorted(Vt.items()):
                if tn < 20: continue
                M.append(f"| {DIR[dr]} | {rules[r]} | {L}개 | {km}개 이상 | {tn:,} | {pct(th, tn)} | {pct(bw, tn)} | {(th / tn - bw / tn) * 100:+.1f}%p |")
                Pv[f'{dr}|{r}|{L}|{km}'] = dict(n=tn, hit=th / tn, base=bw / tn)
            M += ['', '가장 좋아 보이는 50개(적중률 하한 기준, 보유일·방향마다)만 골랐을 때:', '', '| 방향 | 조합 크기 | 학습 적중 | 다음 해 적중 | 바탕 | 차이 | 다음 해 거래 |', '|---|---|---|---|---|---|---|']
            Pt = {}
            for dr in range(2):
                for L in range(1, 5):
                    trn = trh = ten = teh = bw = 0.0
                    for y in ys:
                        o = wf[y]
                        for l_, h, d_, lb, nm, st in o['top']:
                            if l_ != L or d_ != dr: continue
                            trn += st[0]; trh += st[1]; ten += st[2]; teh += st[3]; bw += st[2] * base_rate(o, h, dr)
                    if not ten: continue
                    M.append(f"| {DIR[dr]} | {L}개 | {pct(trh, trn)} | {pct(teh, ten)} | {pct(bw, ten)} | {(teh / ten - bw / ten) * 100:+.1f}%p | {num(ten)} |")
                    Pt[f'{dr}|{L}'] = dict(train_hit=trh / trn, test_hit=teh / ten, base=bw / ten, test_n=ten)
            M.append(''); S['periods'][pn] = dict(each=P, votes=Pv, top50=Pt)
        # 보유일별(80% 규칙, 조합 3개, 전체 기간)
        ys = sorted(wf); M += ['### 보유일별로 나눠 보면 (2016~2026, "80% 이상" 규칙)', '', '| 방향 | 조합 크기 | 보유일 | 고른 수(해 평균) | 다음 해 적중 | 바탕 | 차이 | 다음 해 거래 |', '|---|---|---|---|---|---|---|---|']; BH = {}
        for dr in range(2):
            for L in (1, 2, 3):
                for hi, h in enumerate(HS):
                    ns = ten = teh = bw = 0.0
                    for y in ys:
                        o = wf[y]; p = np.array(o['pool'])[L, 1, hi, dr]; ns += np.array(o['sel'])[L, 1, hi, dr]; ten += p[2]; teh += p[3]; bw += p[2] * base_rate(o, h, dr)
                    if not ten: continue
                    M.append(f"| {DIR[dr]} | {L + 1}개 | {h}일 | {ns / len(ys):,.0f} | {pct(teh, ten)} | {pct(bw, ten)} | {(teh / ten - bw / ten) * 100:+.1f}%p | {num(ten)} |")
                    BH[f'{dr}|{L + 1}|{h}'] = dict(sel=ns / len(ys), hit=teh / ten, base=bw / ten, n=ten)
        S['by_hold'] = BH
    M += ['', '모두 과거 자료 성적이다. 투자 권유 아님']
    open(os.path.join(OUT, 'report.md'), 'w', encoding='utf-8').write('\n'.join(M) + '\n')
    json.dump(S, open(os.path.join(OUT, 'summary.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('\n'.join(M[:60]))


if __name__ == '__main__':
    main()
