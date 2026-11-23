#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""turn_report.py — turn_probe.py 의 맞춤별 결과(out/fit_*.json)를 모아 out/report.md · out/summary.json 으로."""
import glob
import json
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__)); OUT = os.environ.get('TURN_OUT') or os.path.join(HERE, 'out')
LEADW = 3; CONFW = 3
CATS = {'price': '지수·가격', 'flow': '수급(투자자별 매매)', 'credit': '신용·미수·대주', 'futs': '선물 구조', 'opt': '옵션 구조', 'vol': '변동성 지수', 'us': '미국·해외·환율', 'cal': '달력'}
SETN = {'ALL': '전부', 'PRICE': '지수만', 'FLOW': '수급만', 'OPT': '선물·옵션 구조만', 'NOPX': '지수 빼고 전부'}
RN = {'저점5앞': '하락→상승 · 미리(저점 3일 전~당일)', '저점5뒤': '하락→상승 · 직후(저점 다음 날~3일 뒤)', '고점5앞': '상승→하락 · 미리(고점 3일 전~당일)', '고점5뒤': '상승→하락 · 직후(고점 다음 날~3일 뒤)',
      '저점8앞': '하락→상승 8% · 미리', '저점8뒤': '하락→상승 8% · 직후', '고점8앞': '상승→하락 8% · 미리', '고점8뒤': '상승→하락 8% · 직후'}
EVN = {'저점5': '하락→상승 전환(저점에서 5% 이상 반등)', '고점5': '상승→하락 전환(고점에서 5% 이상 하락)', '저점8': '하락→상승 전환(8% 이상)', '고점8': '상승→하락 전환(8% 이상)'}
MAIN = ['저점5앞', '저점5뒤', '고점5앞', '고점5뒤']
TAGS = [('1개 이상', 'abs', 1), ('고른 것의 5% 이상', 'frac', 0.05), ('고른 것의 20% 이상', 'frac', 0.20)]
HS = [5, 10, 20]


def pct(a, b, d=1): return '—' if not b else f'{a / b * 100:.{d}f}%'
def sg(x): return '—' if x is None else f'{x:+.2f}%'
def bh(x): return '—' if x is None else f'{x * 100:.0f}%'
def fcell(f): return '—' if not f['n'] else f"{f['hit'] / f['n'] * 100:.0f}% ({f['n']}) · {f['mean']:+.2f}%"      # 방향 적중 (거래) · 평균 수익
def bcell(F): return ' / '.join('—' if F[h]['base_hit'] is None else f"{F[h]['base_hit'] * 100:.0f}% · {F[h]['base_mean']:+.2f}%" for h in HS)


def thin(days, h):
    out = []; last = -10 ** 6
    for d in days:
        if d - last >= h: out.append(int(d)); last = d
    return out


def win_days(p, kind): return range(p - LEADW, p + 1) if kind == '앞' else range(p + 1, p + CONFW + 1)
def up_ok(row): return row.startswith('저점')
def dirn(row): return '오름' if up_ok(row) else '내림'
def hit(row, n, up): return up if up_ok(row) else n - up


def fwd_cell(row, f):
    """[거래, 오름, 평균%] → '방향 적중 (거래) · 평균'"""
    n, up, mean = f
    return '—' if not n else f'{hit(row, n, up) / n * 100:.0f}% ({n}) · {mean:+.2f}%'


def main():
    fits = {}
    for fp in glob.glob(os.path.join(OUT, 'fit_*.json')):
        o = json.load(open(fp, encoding='utf-8')); fits[o['fit']] = o
    full = fits.get('FULL'); wf = {int(k): v for k, v in fits.items() if k != 'FULL'}; ys = sorted(wf); S = {}
    any_ = full or wf[ys[0]]; rows = any_['rows']; rules = any_['rules']; NW = 8; h_i = {5: 0, 10: 1, 20: 2}
    M = ['# 전환점 연구 결과', '',
         '- 전환점: 코스피200 선물 종가가 저점에서 5%(또는 8%) 이상 오르면 그 저점이 "하락→상승 전환점", 고점에서 그만큼 내리면 "상승→하락 전환점". 지나고 나서야 확정되는 표지다.',
         '- 조합이 켜진 날이 "미리 구간(전환점 3일 전~당일)" 또는 "직후 구간(전환점 다음 날~3일 뒤)" 안이면 그 전환점을 찾아낸 것으로 센다. 신호는 5거래일 간격으로 솎아 센다.',
         '- "그 뒤 수익" = 신호 다음 날 시가에 들어가 5·10·20거래일째 종가까지. 저점 쪽은 오른 비율, 고점 쪽은 내린 비율이 "방향 적중"이다. 평균은 그 기간 선물 등락(비용 전).',
         f"- 조건: 지표 {any_['features']}개의 분위 조건(하위 10·20%, 상위 20·10%). 조합은 서로 다른 지표의 조건 1~3개를 빠짐없이 봤다. 조건 묶음: " + ' / '.join(f'{v}' for v in SETN.values()) + '.',
         '- "지수만" 묶음은 코스피·선물 자기 가격에서 나온 조건이다. 저점은 정의상 하락 뒤에 오므로 이 묶음이 전환점과 겹치는 것은 당연한 부분이 있다(기준선으로 본다).', '']
    # ---------------------------------------------------------------- 1) 전환점 수
    if full:
        ed = full['event_dates']; by = full['events_by_year']; S['events'] = {k: len(v) for k, v in ed.items()}; S['events_by_year'] = by; S['last_day'] = full['last_day']; S['base_fwd'] = full['base_fwd']
        M += [f"## 1. 전환점은 몇 번 있었나 (2010 ~ {full['last_day']})", '', '| 종류 | 횟수 | 최근 5번 |', '|---|---|---|']
        for nm in ('저점5', '고점5', '저점8', '고점8'): M.append(f"| {EVN[nm]} | {len(ed[nm])} | {', '.join(ed[nm][-5:])} |")
        yy = sorted(by['저점5']); M += ['', '해마다(5% 기준 저점 / 고점): ' + ' · '.join(f"{y} {by['저점5'][y]}/{by['고점5'][y]}" for y in yy), '']
        bf = full['base_fwd']; M += ['아무 날에나 샀을 때(기준): ' + ' · '.join(f"{h}일 뒤 오름 {pct(bf[str(h)][1], bf[str(h)][0])}, 평균 {bf[str(h)][2]:+.2f}%" for h in HS), '']
        # ------------------------------------------------------------ 2) 공통점
        M += ['## 2. 전환 때 공통으로 나타난 변화 (조건 1개씩)', '', '"나타난 비율" = 전환점 가운데 그 구간에 그 조건이 켜져 있던 비율. "우연이면" = 전환점 날짜를 통째로 옮겼을 때의 평균. z 가 클수록 전환 때만 유독 나타난 변화다.', '']
        S['common'] = {}
        for nm in ('저점5', '고점5'):
            M += [f'### {EVN[nm]}', '']
            for title, cats, k in (('지수의 변화', ['price'], 6), ('수급의 변화', ['flow', 'credit'], 6), ('옵션·선물 구조, 변동성, 해외', ['opt', 'futs', 'vol', 'us'], 4)):
                M += [f'**{title}**', '', '| 구간 | 조건 | 묶음 | 나타난 비율 | 우연이면 | z |', '|---|---|---|---|---|---|']
                for wn in ('직전 5일', '당일', '직후 3일'):
                    c = full['common'][f'{nm}|{wn}']; lst = sorted([(x, ck) for ck in cats for x in c['bycat'][ck]], key=lambda t: -t[0][3])[:k]
                    for (name, real, mu, z), ck in lst: M.append(f'| {wn} | {name} | {CATS[ck]} | {real * 100:.0f}% | {mu * 100:.0f}% | {z:+.1f} |')
                M.append('')
            for wn in ('직전 5일', '당일', '직후 3일'):
                c = full['common'][f'{nm}|{wn}']; S['common'][f'{nm}|{wn}'] = dict(n_events=c['n_events'], over={ck: c['bycat'][ck + '|n'] for ck in CATS}, top={ck: c['bycat'][ck][:8] for ck in CATS})
            M += ['우연 범위(상위 5%)를 넘은 조건 수(묶음별, 넘은 수/조건 수 — 우연이면 5%): ' + ' · '.join(
                f"{wn}: " + ', '.join(f"{CATS[ck]} {full['common'][f'{nm}|{wn}']['bycat'][ck + '|n'][1]}/{full['common'][f'{nm}|{wn}']['bycat'][ck + '|n'][0]}" for ck in ('price', 'flow', 'credit', 'opt', 'vol', 'us')) for wn in ('직전 5일', '당일')), '']
        for nm in ('저점8', '고점8'):
            for wn in ('직전 5일', '당일', '직후 3일'):
                c = full['common'][f'{nm}|{wn}']; S['common'][f'{nm}|{wn}'] = dict(n_events=c['n_events'], over={ck: c['bycat'][ck + '|n'] for ck in CATS}, top={ck: c['bycat'][ck][:8] for ck in CATS})
        # ------------------------------------------------------------ 3) 진짜 전환과 계속 간 날
        M += ['## 3. 진짜 전환과 "계속 간 날"을 가른 조건', '',
              '많이 내린 날이라고 다 바닥이 아니고, 많이 오른 날이라고 다 꼭지가 아니다. 그런 날들 가운데 실제로 3일 안에 전환점이 온 날에만 유독 겹쳐 있던 조건을 찾았다.',
              '"z" = 그 조건의 날짜를 통째로 옮겼을 때와 견준 차이(클수록 우연이 아님). 전체 기간을 다 보고 찾은 것이므로 고른 뒤 성적은 6절에서 따로 본다.', '']
        S['lift'] = {}
        for nm, lab in (('저점5', '바닥'), ('고점5', '꼭지')):
            lf = full.get('lift', {}).get(nm)
            if not lf: continue
            row = nm + '앞'; f0 = lf['ctx_f10']
            M += [f"### {EVN[nm]} — 바탕 조건 `{lf['context']}`", '',
                  f"바탕 조건만 켜진 신호 {lf['ctx_signals']}번 가운데 3일 안에 {lab}이 온 것은 {lf['ctx_hits']}번({pct(lf['ctx_hits'], lf['ctx_signals'])}). 그 뒤 10일 {dirn(row)} {fwd_cell(row, f0)}.", '',
                  f'| 묶음 | 겹친 조건 | 신호 | 3일 안에 {lab} | 비율 | z | 그 뒤 10일 {dirn(row)} (거래) · 평균 |', '|---|---|---|---|---|---|---|']
            for ck in ('flow', 'credit', 'opt', 'futs', 'vol', 'us', 'price'):
                for name, ns, hs, z, f10 in lf['bycat'][ck][:5]: M.append(f'| {CATS[ck]} | {name} | {ns} | {hs} | {pct(hs, ns)} | {z:+.1f} | {fwd_cell(row, f10)} |')
            M.append(''); S['lift'][nm] = lf
        # ------------------------------------------------------------ 4·5) 전체 기간 상위 조합
        for tkey, title, note in (('top1', '## 4. 전환점을 가장 많이 찾아낸 조합 (전체 기간)', '신호의 35% 이상이 구간 안인 조합 가운데 찾아낸 전환점이 많은 순. 켜진 날이 똑같은 조합은 하나만 남겼다.'),
                                  ('top2', '## 5. 전환점도 찾고 그 뒤 수익 방향도 가장 좋았던 조합 (전체 기간)', '"구간 안 35% 이상 · 8개 이상 찾음"을 채운 조합 가운데 그 뒤 10일 방향 적중이 높은 순(20거래 이상). 수많은 조합에서 고른 것이라 이 숫자는 부풀어 있다 — 고른 뒤 성적은 6절.')):
            M += [title, '', note, '']; S[tkey] = {}
            for row in MAIN:
                tot = full['events'][row]['n_train']; M += [f'### {RN[row]} — 전환점 {tot}번', '', f'| 묶음 | 조합 | 신호 | 구간 안 | 찾은 전환점 | 5일 뒤 {dirn(row)} | 10일 뒤 | 20일 뒤 | 맞은 해 | 최근 신호(맞음 ○) |', '|---|---|---|---|---|---|---|---|---|---|']
                for sk in SETN:
                    if sk not in full['sets']: continue
                    ent = full['sets'][sk][tkey][row][:4 if sk == 'ALL' else 3]; S[tkey][f'{sk}|{row}'] = full['sets'][sk][tkey][row][:10]
                    for e in ent:
                        rec = ' '.join(f"{d[5:]}{'○' if h else '×'}" for d, h in e.get('recent', [])[-3:])
                        M.append(f"| {SETN[sk]} | {' + '.join(e['names'])} | {e['st'][0]} | {pct(e['st'][1], e['st'][0])} | {e['st'][1]}/{tot} ({pct(e['st'][1], tot, 0)}) | {fwd_cell(row, e['tr']['f5'])} | {fwd_cell(row, e['tr']['f10'])} | {fwd_cell(row, e['tr']['f20'])} | {e.get('years_hit', '—')} | {rec}{' · 지금 켜짐' if e.get('on') else ''} |")
                M.append('')
        # 전체 기간: 규칙을 채우는 조합 수 — 실제 / 가짜
        M += ['### 전체 기간에서 규칙을 채우는 조합 수 — 실제 / 전환 구간을 통째로 옮긴 가짜 / 해 안에서만 옮긴 가짜', '', '| 묶음 | 구간 | 규칙 | 조건 2개 | 3개 |', '|---|---|---|---|---|']; S['full_counts'] = {}
        for sk in SETN:
            if sk not in full['sets']: continue
            so = full['sets'][sk]; sel = np.array(so['sel']); seln = np.array(so['seln']); g_ = np.array([t == 'global' for t in full['null_types']])
            for hi, row in enumerate(rows[:4]):
                for r in (0, 1, 3, 4):
                    cells = []
                    for L in (1, 2):
                        if L >= sel.shape[0]: cells.append('—'); continue
                        a = int(sel[L, r, hi]); b = seln[:, L, r, hi].astype(float); gm = b[g_].mean() if g_.any() else float('nan'); ym = b[~g_].mean() if (~g_).any() else float('nan')
                        cells.append(f'{a:,} / {gm:,.0f} / {ym:,.0f}'); S['full_counts'][f'{sk}|{row}|{r}|{L + 1}'] = [a, float(gm), float(ym)]
                    M.append(f'| {SETN[sk]} | {RN[row]} | {rules[r]} | ' + ' | '.join(cells) + ' |')
        M.append('')
    # ---------------------------------------------------------------- 6) 고른 뒤 성적
    if wf:
        yall = ys; yex = [y for y in ys if y != 2026]
        M += ['## 6. 지난 자료로 고른 조합이 그 다음 해에 통했나', '',
              f"해마다 그 해 이전 자료만으로(전환점도 그때까지의 가격으로만 정해) 조합을 전부 훑어 고르고, 그 해에 켜진 날을 채점했다 ({ys[0]}~{ys[-1]}, {len(ys)}개 해).",
              '2026년은 하루 변동이 평소의 3~4배라 5% 전환점이 유난히 많다(1절). 그래서 "2026 빼고"를 따로 적었다.', '']

        def base_in(o, hi): tv = np.array(o['test_val'][hi]); return float((tv == 1).mean())

        def base_f(o, h, row):
            r = np.array([x for x in o['test_ret'][str(h)] if x is not None and x != 0], float)
            if not len(r): return 0.5, 0.0
            u = float((r > 0).mean()); return (u if up_ok(row) else 1 - u), float(r.mean())

        # ---- 6-1 규칙을 채운 조합 전체
        M += ['### 6-1. 규칙을 채운 조합을 하나하나 채점 (조건 3개 조합)', '', '"구간 안" = 신호 가운데 전환 구간 안이었던 비율, "5일·10일 방향" = 신호 뒤 방향 적중. 각각 고를 때 → 그 해(같은 해 아무 날이면).', '',
              '| 묶음 | 구간 | 규칙 | 고른 수(해 평균) | 가짜(통째로/해 안)면 | 구간 안: 고를 때 → 그 해 (아무 날) | 5일 방향: 고를 때 → 그 해 (아무 날) | 10일 방향: 고를 때 → 그 해 (아무 날) | 2026 빼고: 구간 안 · 5일 · 10일 (아무 날) |', '|---|---|---|---|---|---|---|---|---|']
        S['wf_each'] = {}
        for sk in SETN:
            for hi, row in enumerate(rows[:NW]):
                for r in range(len(rules)):
                    for L in (1, 2):
                        acc = {}
                        for tag, yy in (('all', yall), ('ex', yex)):
                            ns = ng = ny = trn = trh = ten = teh = bw = 0.0; cnt = 0; X = {h: [0.0] * 5 for h in HS}
                            for y in yy:
                                o = wf[y]
                                if sk not in o['sets']: continue
                                so = o['sets'][sk]; sel = np.array(so['sel'])
                                if L >= sel.shape[0]: continue
                                cnt += 1; seln = np.array(so['seln']); p = np.array(so['pool'])[L, r, hi]; gg = np.array([t == 'global' for t in o['null_types']])
                                ns += sel[L, r, hi]; sb = seln[:, L, r, hi].astype(float); ng += sb[gg].mean() if gg.any() else 0; ny += sb[~gg].mean() if (~gg).any() else 0
                                trn += p[0]; trh += p[1]; ten += p[2]; teh += p[3]; bw += p[2] * base_in(o, hi)
                                for h in HS:
                                    xp = np.array(so['xpool'])[L, r, hi, h_i[h]]; bf, _ = base_f(o, h, row); v = X[h]
                                    v[0] += xp[0]; v[1] += hit(row, xp[0], xp[1]); v[2] += xp[2]; v[3] += hit(row, xp[2], xp[3]); v[4] += xp[2] * bf
                            acc[tag] = dict(years=cnt, sel=ns / max(cnt, 1), null_g=ng / max(cnt, 1), null_y=ny / max(cnt, 1), tr_in=[trh, trn], te_in=[teh, ten], base_in=bw / ten if ten else None,
                                            f={h: dict(tr=[v[1], v[0]], te=[v[3], v[2]], base=v[4] / v[2] if v[2] else None) for h, v in X.items()})
                        A, E = acc['all'], acc['ex']
                        if A['sel'] == 0: continue
                        S['wf_each'][f'{sk}|{row}|{r}|{L + 1}'] = acc
                        if L == 2 and row in MAIN:
                            fc = lambda a_, h: f"{pct(*a_['f'][h]['tr'])} → {pct(*a_['f'][h]['te'])} ({bh(a_['f'][h]['base'])})"
                            M.append(f"| {SETN[sk]} | {RN[row]} | {rules[r]} | {A['sel']:,.0f} | {A['null_g']:,.0f} / {A['null_y']:,.0f} | {pct(*A['tr_in'])} → {pct(*A['te_in'])} ({bh(A['base_in'])}) | {fc(A, 5)} | {fc(A, 10)} | "
                                     f"{pct(*E['te_in'])} ({bh(E['base_in'])}) · {pct(*E['f'][5]['te'])} ({bh(E['f'][5]['base'])}) · {pct(*E['f'][10]['te'])} ({bh(E['f'][10]['base'])}) |")
        M.append('')

        # ---- 6-2·6-3 그때의 상위 N개
        def topn(sk, row, tkey, N, yy):
            hi = rows.index(row); sig = hitw = found = evn = 0; bsum = 0.0; f = {h: [0, 0, 0.0, 0.0, 0.0] for h in HS}; used = 0      # f: 거래, 방향 적중, 수익 합, 기준 적중 합, 기준 평균 합
            for y in yy:
                o = wf[y]
                if sk not in o['sets']: continue
                ent = o['sets'][sk][tkey][row][:N]
                if not ent: continue
                used += 1; evs = len(o['events'][row]['test']); b_in = base_in(o, hi)
                for e in ent:
                    t = e['te']; sig += t['sig']; hitw += t['hit']; found += t['found']; evn += evs; bsum += t['sig'] * b_in
                    for h in HS:
                        n_, u_, m_ = t[f'f{h}']; bf, bm = base_f(o, h, row); f[h][0] += n_; f[h][1] += hit(row, n_, u_); f[h][2] += m_ * n_; f[h][3] += bf * n_; f[h][4] += bm * n_
            return dict(years=used, sig=sig, hit=hitw, base_in=bsum / sig if sig else None, found=found, events=evn, f={h: dict(n=v[0], hit=v[1], mean=v[2] / v[0] if v[0] else None, base_hit=v[3] / v[0] if v[0] else None, base_mean=v[4] / v[0] if v[0] else None) for h, v in f.items()})

        for tkey, title, note in (('top1', '### 6-2. 그때 "가장 많이 찾던" 조합 상위 N개를 다음 해에 썼다면', '해마다 그 해 이전 자료에서 4절과 같은 방법으로 뽑은 상위 N개(켜진 날이 다른 것)의 그 해 성적을 모았다.'),
                                  ('top2', '### 6-3. 그때 "전환점도 찾고 수익도 가장 좋던" 조합 상위 N개를 다음 해에 썼다면', '해마다 그 해 이전 자료에서 5절과 같은 방법으로 뽑은 상위 N개의 그 해 성적.')):
            M += [title, '', note + ' "찾은 전환점" = 조합 하나가 그 해 전환점 가운데 찾은 비율(평균). 방향 칸 = 적중 (거래) · 평균 수익, 괄호 밖 "아무 날" = 같은 해 아무 날의 적중 · 평균.', '',
                  '| 묶음 | 구간 | N | 신호 | 구간 안 (아무 날) | 찾은 전환점 | 5일 방향 | 10일 방향 | 20일 방향 | 아무 날 5일 / 10일 / 20일 | 2026 빼고: 구간 안 · 5일 · 10일 |', '|---|---|---|---|---|---|---|---|---|---|---|']
            S['wf_' + tkey] = {}
            for sk in SETN:
                for row in rows[:NW]:
                    for N in (1, 5, 20):
                        A = topn(sk, row, tkey, N, yall); E = topn(sk, row, tkey, N, yex); S['wf_' + tkey][f'{sk}|{row}|{N}'] = dict(all=A, ex=E)
                        if not A['sig'] or row not in MAIN: continue
                        M.append(f"| {SETN[sk]} | {RN[row]} | {N} | {A['sig']} | {pct(A['hit'], A['sig'])} ({bh(A['base_in'])}) | {pct(A['found'], A['events'], 0)} | {fcell(A['f'][5])} | {fcell(A['f'][10])} | {fcell(A['f'][20])} | {bcell(A['f'])} | "
                                 f"{pct(E['hit'], E['sig'])} ({bh(E['base_in'])}) · {fcell(E['f'][5])} · {fcell(E['f'][10])} |")
            M.append('')

        # ---- 6-4 합친 신호
        def union(sk, row, r, L, kind, x, yy, per_year=False):
            hi = rows.index(row); found = tot = sig = inw = 0; bsum = 0.0; f = {h: [0, 0, 0.0, 0.0, 0.0] for h in HS}; py = {}
            for y in yy:
                o = wf[y]
                if sk not in o['sets']: continue
                so = o['sets'][sk]; sel = np.array(so['sel'])
                if L >= sel.shape[0]: continue
                ns = int(sel[L, r, hi]); evs = o['events'][row]['test']; tot += len(evs); tv = np.array(o['test_val'][hi]); rec = dict(events=len(evs), found=0, sig=0, inw=0, n10=0, hit10=0, mean10=None)
                if ns:
                    v = np.array(so['votes'])[L, r, hi]; k = x if kind == 'abs' else max(1, int(np.ceil(x * ns))); days = np.where(v >= k)[0]; ds = set(int(d) for d in days)
                    f_ = sum(1 for p in evs if any(d in ds for d in win_days(p, row[-1]))); found += f_; tr = thin(days, 5); iw = sum(int(tv[d] == 1) for d in tr); sig += len(tr); inw += iw; bsum += len(tr) * base_in(o, hi)
                    rec.update(found=f_, sig=len(tr), inw=iw)
                    for h in HS:
                        rr = o['test_ret'][str(h)]; th_ = [d for d in thin([d for d in days if rr[d] is not None and rr[d] != 0], h)]; vals = [rr[d] for d in th_]; bf, bm = base_f(o, h, row)
                        u = sum(1 for z in vals if z > 0); f[h][0] += len(vals); f[h][1] += hit(row, len(vals), u); f[h][2] += sum(vals); f[h][3] += bf * len(vals); f[h][4] += bm * len(vals)
                        if h == 10: rec.update(n10=len(vals), hit10=hit(row, len(vals), u), mean10=float(np.mean(vals)) if vals else None)
                py[y] = rec
            res = dict(found=found, events=tot, sig=sig, inw=inw, base_in=bsum / sig if sig else None, f={h: dict(n=v[0], hit=v[1], mean=v[2] / v[0] if v[0] else None, base_hit=v[3] / v[0] if v[0] else None, base_mean=v[4] / v[0] if v[0] else None) for h, v in f.items()})
            if per_year: res['per_year'] = py
            return res

        M += ['### 6-4. 고른 조합들을 하나의 신호로 합쳐서 썼다면 (조건 3개 조합)', '', '그날 켜진 조합 수가 문턱 이상이면 신호. "찾은 전환점" = 구간 안에 신호가 하루라도 있었던 전환점. "신호 중 구간 안" = 5일 간격으로 솎은 신호 가운데 전환 구간 안이었던 비율.', '',
              '| 묶음 | 구간 | 규칙 | 문턱 | 찾은 전환점 | 신호 | 신호 중 구간 안 (아무 날) | 5일 방향 | 10일 방향 | 20일 방향 | 아무 날 5일 / 10일 / 20일 | 2026 빼고: 찾음 · 구간 안 · 5일 · 10일 |', '|---|---|---|---|---|---|---|---|---|---|---|---|']
        S['wf_union'] = {}
        for sk in SETN:
            for row in rows[:NW]:
                for r in range(len(rules)):
                    for L in (1, 2):
                        for tag, kind, x in TAGS:
                            A = union(sk, row, r, L, kind, x, yall, per_year=(L == 2 and r in (1, 3) and kind == 'frac')); E = union(sk, row, r, L, kind, x, yex)
                            if not A['sig']: continue
                            S['wf_union'][f'{sk}|{row}|{r}|{L + 1}|{tag}'] = dict(all=A, ex=E)
                            if L != 2 or row not in MAIN or r not in (1, 3, 4): continue
                            M.append(f"| {SETN[sk]} | {RN[row]} | {rules[r]} | {tag} | {A['found']}/{A['events']} ({pct(A['found'], A['events'], 0)}) | {A['sig']} | {pct(A['inw'], A['sig'])} ({bh(A['base_in'])}) | {fcell(A['f'][5])} | {fcell(A['f'][10])} | {fcell(A['f'][20])} | {bcell(A['f'])} | "
                                     f"{E['found']}/{E['events']} · {pct(E['inw'], E['sig'])} ({bh(E['base_in'])}) · {fcell(E['f'][5])} · {fcell(E['f'][10])} |")
        M.append('')
        # ---- 6-5 해마다
        M += ['### 6-5. 해마다 (합친 신호 · 규칙 "구간 안 35% 이상 · 8개 이상" · 조건 3개 · 문턱 "고른 것의 5% 이상")', '', '칸 = 찾은 전환점/그 해 전환점 · 구간 안 신호/신호 · 10일 방향 적중(거래) · 평균', '']
        for row in MAIN:
            M += [f'**{RN[row]}**', '', '| 해 | ' + ' | '.join(SETN[sk] for sk in SETN) + ' |', '|---|' + '---|' * len(SETN)]
            for y in ys:
                cells = []
                for sk in SETN:
                    u = S['wf_union'].get(f'{sk}|{row}|1|3|고른 것의 5% 이상'); p = u['all']['per_year'].get(y) if u else None
                    cells.append('—' if not p or not p['sig'] else f"{p['found']}/{p['events']} · {p['inw']}/{p['sig']} · {pct(p['hit10'], p['n10'], 0)} ({p['n10']}) · {sg(p['mean10'])}")
                M.append(f'| {y} | ' + ' | '.join(cells) + ' |')
            M.append('')
        S['times'] = {str(y): {sk: [wf[y]['sets'][sk]['enum'], wf[y]['sets'][sk]['seconds']] for sk in wf[y]['sets']} for y in ys}
    if full: S['times_full'] = {sk: [full['sets'][sk]['cond'], full['sets'][sk]['enum'], full['sets'][sk]['seconds']] for sk in full['sets']}
    M += ['', '모두 과거 자료 성적이다. 투자 권유 아님']
    open(os.path.join(OUT, 'report.md'), 'w', encoding='utf-8').write('\n'.join(M) + '\n'); json.dump(S, open(os.path.join(OUT, 'summary.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(len(M), '줄')


if __name__ == '__main__':
    main()
