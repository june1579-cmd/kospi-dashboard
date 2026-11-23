#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""turn_report.py — turn_probe.py 의 맞춤별 결과(out/fit_*.json)를 모아 out/report.md · out/summary.json 으로."""
import glob
import json
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__)); OUT = os.environ.get('TURN_OUT') or os.path.join(HERE, 'out')
WIN = 4
GN = {'price': '가격', 'fund': '자금·수급', 'vol': '변동성', 'fut': '선물', 'opt': '옵션', 'us': '미국·해외', 'other': '기타'}
RN = {'저점5': '하락→상승 전환(저점에서 5% 이상 반등)', '저점8': '하락→상승 전환(8% 이상)', '고점5': '상승→하락 전환(고점에서 5% 이상 하락)', '고점8': '상승→하락 전환(8% 이상)'}
TAGS = [('1개 이상', 'abs', 1), ('고른 것의 5% 이상', 'frac', 0.05), ('고른 것의 20% 이상', 'frac', 0.20)]


def pct(a, b): return '—' if not b else f'{a / b * 100:.1f}%'


def thin(days, h):
    out = []; last = -10 ** 6
    for d in days:
        if d - last >= h: out.append(int(d)); last = d
    return out


def main():
    fits = {}
    for fp in glob.glob(os.path.join(OUT, 'fit_*.json')):
        o = json.load(open(fp, encoding='utf-8')); fits[o['fit']] = o
    full = fits.get('FULL'); wf = {int(k): v for k, v in fits.items() if k != 'FULL'}; S = {}
    M = ['# 전환점 연구 결과', '', '- 전환점: 코스피200 선물 종가가 저점에서 5%(또는 8%) 이상 오르면 그 저점이 "하락→상승 전환점", 고점에서 그만큼 내리면 "상승→하락 전환점".',
         '- 전환 구간 = 전환점 당일부터 3일 뒤까지(4거래일). 조합이 이 구간 안에 켜지면 "찾아냈다"고 센다. 전환점은 지나고 나서야 확정되므로 과거를 분석하는 표지다.',
         '- 조건: 지표 434개의 분위 조건(하위 10·20%, 상위 20·10%). 조합은 서로 다른 지표의 조건 1~3개를 빠짐없이 봤다.', '']
    if full:
        rows = full['rows']; ev = full['events']; ed = full['event_dates']; gof = full['group_of_feature']
        M += ['## 1. 전환점은 몇 번 있었나 (2010 ~ 지금)', '', '| 종류 | 횟수 | 최근 5번 |', '|---|---|---|']
        for nm in rows[:4]: M.append(f"| {RN[nm]} | {len(ed[nm])} | {', '.join(ed[nm][-5:])} |")
        S['events'] = {nm: len(ed[nm]) for nm in rows[:4]}
        # ---- 공통점
        M += ['', '## 2. 전환 때 공통으로 나타난 변화 (조건 1개씩)', '', '"나타난 비율" = 전환점 가운데 그 조건이 켜져 있던 비율. "우연이면" = 전환점 날짜를 통째로 옮겼을 때의 평균. 차이가 클수록(z 가 클수록) 전환 때만 유독 나타난 변화다.', '']
        S['common'] = {}
        for nm in ('저점5', '고점5'):
            for wn in ('직전 5일', '당일~3일 뒤'):
                c = full['common'][f'{nm}|{wn}']
                M += [f"### {RN[nm]} — {wn} (전환점 {c['n_events']}번)", '', f"우연 범위(상위 5%)를 넘은 조건 {c['n_over95']}개 (우연이면 약 {c['expect_over95']:.0f}개)", '', '| 조건 | 묶음 | 나타난 비율 | 우연이면 | z |', '|---|---|---|---|---|']
                for name, real, mu, q95, z, f_ in c['top'][:14]: M.append(f"| {name} | {GN.get(gof.get(str(f_), 'other'), '기타')} | {real * 100:.0f}% | {mu * 100:.0f}% | {z:+.1f} |")
                M.append(''); S['common'][f'{nm}|{wn}'] = dict(n_over95=c['n_over95'], expect=c['expect_over95'], top=c['top'][:14])
        for nm in ('저점8', '고점8'):
            for wn in ('직전 5일', '당일~3일 뒤'):
                c = full['common'][f'{nm}|{wn}']; S['common'][f'{nm}|{wn}'] = dict(n_over95=c['n_over95'], expect=c['expect_over95'], top=c['top'][:14])
        # ---- 가장 많이 찾아낸 조합(전체 기간)
        M += ['## 3. 전환점을 가장 많이 찾아낸 조합 (전체 기간, 켜진 날의 35% 이상이 전환 구간 안인 것 가운데)', '', '이 표는 전체 기간을 다 보고 고른 것이다(고를 때 성적). 고른 뒤 성적은 4절.', '']
        S['best'] = {}
        for nm in rows[:4]:
            tot = ev[nm]['n_train']; M += [f'### {RN[nm]} — 전환점 {tot}번', '', '| 조합 | 켜진 횟수 | 전환 구간 안 | 찾은 전환점 | 그 뒤 10일 ' + ('오름' if nm.startswith('저점') else '내림') + ' |', '|---|---|---|---|---|']; bl = []
            cand = sorted([t for t in full['top'] if t[1] == nm], key=lambda t: -t[3])[:8]
            for L, _, dr, sc, names, st, extra in cand:
                e10 = extra['수익10일'] if extra else [0, 0]; f10 = (e10[1] if nm.startswith('저점') else e10[0] - e10[1])
                M.append(f"| {' + '.join(names)} | {st[0]} | {pct(st[1], st[0])} | {st[1]}/{tot} ({pct(st[1], tot)}) | {pct(f10, e10[0])} ({e10[0]}거래) |")
                bl.append(dict(names=names, n=st[0], hits=st[1], total=tot, fwd10=[e10[0], f10]))
            M.append(''); S['best'][nm] = bl
        # ---- 전체 기간 실제 대 가짜
        sel = np.array(full['sel']); seln = np.array(full['seln']); g_ = np.array([t == 'global' for t in full['null_types']])
        M += ['전체 기간에서 규칙을 채우는 조합 수 — 실제 / 전환 구간을 통째로 옮긴 가짜 / 해 안에서만 옮긴 가짜:', '', '| 종류 | 규칙 | 조합 1개 | 2개 | 3개 |', '|---|---|---|---|---|']; S['full_counts'] = {}
        for hi, nm in enumerate(rows[:4]):
            for r in range(3):
                cells = []
                for L in range(sel.shape[0]):
                    a = int(sel[L, r, hi, 0]); b = seln[:, L, r, hi, 0].astype(float); cells.append(f"{a:,} / {b[g_].mean():,.0f} / {b[~g_].mean():,.0f}"); S['full_counts'][f'{nm}|{r}|{L + 1}'] = [a, float(b[g_].mean()), float(b[~g_].mean())]
                M.append(f"| {RN[nm]} | {full['rules'][r]} | " + ' | '.join(cells) + ' |')
        M.append('')
    # ---------------- 4) 고른 뒤 성적
    if wf:
        ys = sorted(wf); any_ = wf[ys[0]]; rows = any_['rows']; rules = any_['rules']; H = any_['H']; h10 = rows.index('수익10일')
        M += ['## 4. 지난 자료로 고른 조합이 그 다음 해에 전환점을 찾아냈나', '', f"해마다 그 해 이전 자료만으로(전환점도 그때까지의 가격으로만 정해) 조합을 전부 훑어 고르고, 그 해에 켜진 날을 채점했다 ({ys[0]}~{ys[-1]}, {len(ys)}개 해).", '',
              '### 고른 조합을 하나하나 채점', '', '| 종류 | 고른 규칙 | 조합 크기 | 고른 수(해 평균) | 가짜(통째로/해 안)면 | 고를 때 구간 안 | 그 해 구간 안 | 그 해 아무 날 | 고를 때 10일 뒤 | 그 해 10일 뒤 | 그 해 아무 날 10일 뒤 |', '|---|---|---|---|---|---|---|---|---|---|---|']
        S['wf_each'] = {}
        for hi, nm in enumerate(rows[:4]):
            up = nm.startswith('저점')
            for r in range(3):
                for L in range(3):
                    ns = ng = ny = trn = trh = ten = teh = bw = xa = xb = xc = xd = xbw = 0.0
                    for y in ys:
                        o = wf[y]; sel = np.array(o['sel']); seln = np.array(o['seln']); p = np.array(o['pool'])[L, r, hi, 0]; xp = np.array(o['xpool'])[L, r, hi, h10]; gg = np.array([t == 'global' for t in o['null_types']]); tv = np.array(o['test_val'])
                        ns += sel[L, r, hi, 0]; sb = seln[:, L, r, hi, 0].astype(float); ng += sb[gg].mean(); ny += sb[~gg].mean(); trn += p[0]; trh += p[1]; ten += p[2]; teh += p[3]
                        bw += p[2] * float((tv[hi] == 1).mean()); v10 = tv[h10]; ok = v10 >= 0; b10 = float(v10[ok].mean()) if ok.any() else 0.5
                        xa += xp[0]; xb += xp[1] if up else xp[0] - xp[1]; xc += xp[2]; xd += xp[3] if up else xp[2] - xp[3]; xbw += xp[2] * (b10 if up else 1 - b10)
                    if ns == 0: continue
                    M.append(f"| {RN[nm]} | {rules[r]} | {L + 1}개 | {ns / len(ys):,.0f} | {ng / len(ys):,.0f} / {ny / len(ys):,.0f} | {pct(trh, trn)} | {pct(teh, ten)} | {pct(bw, ten)} | {pct(xb, xa)} | {pct(xd, xc)} | {pct(xbw, xc)} |")
                    S['wf_each'][f'{nm}|{r}|{L + 1}'] = dict(sel=ns / len(ys), null_g=ng / len(ys), null_y=ny / len(ys), train_in=trh / trn if trn else None, test_in=teh / ten if ten else None, base_in=bw / ten if ten else None, test_n=ten,
                                                             train_f10=xb / xa if xa else None, test_f10=xd / xc if xc else None, base_f10=xbw / xc if xc else None, test_f10_n=xc)
        M += ['', '### 고른 조합들을 하나의 신호로 합쳐 채점 — 그 해 전환점 중 몇 개를 찾아냈나', '', '그날 켜진 조합 수가 문턱 이상이면 신호. "찾은 전환점" = 전환 구간 안에 신호가 하루라도 있었던 전환점. "신호 중 구간 안" = 겹치지 않게 솎은 신호 가운데 전환 구간 안이었던 비율.', '',
              '| 종류 | 고른 규칙 | 조합 크기 | 문턱 | 찾은 전환점 | 신호(솎은 것) | 신호 중 구간 안 | 아무 날 | 신호 뒤 10일 | 아무 날 10일 뒤 |', '|---|---|---|---|---|---|---|---|---|---|']
        S['wf_union'] = {}
        for hi, nm in enumerate(rows[:4]):
            up = nm.startswith('저점')
            for r in range(3):
                for L in range(3):
                    for tag, kind, x in TAGS:
                        found = tot = sig = inw = 0; bsum = f10n = f10h = 0.0; b10sum = 0.0; per_year = {}
                        for y in ys:
                            o = wf[y]; v = np.array(o['votes'])[L, r, hi, 0]; ns = int(np.array(o['sel'])[L, r, hi, 0]); tv = np.array(o['test_val']); evs = o['events'][nm]['test']; tot += len(evs)
                            b10 = tv[h10]; okb = b10 >= 0; bb = float(b10[okb].mean()) if okb.any() else 0.5
                            if ns == 0: per_year[y] = [0, len(evs), 0, 0]; continue
                            k = x if kind == 'abs' else max(1, int(np.ceil(x * ns))); days = np.where(v >= k)[0]; ds = set(int(d) for d in days)
                            f_ = sum(1 for p in evs if any((p + q) in ds for q in range(WIN))); found += f_
                            tr = thin(days, 5); sig += len(tr); iw = sum(int(tv[hi][d] == 1) for d in tr); inw += iw; bsum += len(tr) * float((tv[hi] == 1).mean())
                            t10 = [d for d in thin(days, 10) if tv[h10][d] >= 0]; f10n += len(t10); u = sum(int(tv[h10][d]) for d in t10); f10h += u if up else len(t10) - u; b10sum += len(t10) * (bb if up else 1 - bb)
                            per_year[y] = [f_, len(evs), len(tr), iw]
                        if sig == 0: continue
                        M.append(f"| {RN[nm]} | {rules[r]} | {L + 1}개 | {tag} | {found}/{tot} ({pct(found, tot)}) | {sig:,} | {pct(inw, sig)} | {pct(bsum, sig)} | {pct(f10h, f10n)} ({int(f10n)}거래) | {pct(b10sum, f10n)} |")
                        S['wf_union'][f'{nm}|{r}|{L + 1}|{tag}'] = dict(found=found, total=tot, signals=sig, in_window=inw, base_in=bsum / sig, f10=[f10n, f10h, b10sum], per_year=per_year)
    M += ['', '모두 과거 자료 성적이다. 투자 권유 아님']
    open(os.path.join(OUT, 'report.md'), 'w', encoding='utf-8').write('\n'.join(M) + '\n'); json.dump(S, open(os.path.join(OUT, 'summary.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(len(M), '줄')


if __name__ == '__main__':
    main()
