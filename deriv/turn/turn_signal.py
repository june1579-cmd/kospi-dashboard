#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""turn_signal.py — 시작 전 10일 조사(turn_pre)로 매매 신호 만들기 (사용자 지시 2026-11-23).
만드는 법(사람이 고르지 않고 규칙으로):
 1) 그때까지의 시작점(5% 전환점)에서 '1일 전 자리'가 우연과도, 지수가 비슷하게 움직인 다른 날과도 달랐던 지표를 고른다(겹치는 지표는 하나만, 최대 8개).
 2) 지표마다 조건 = 자리(지난 250일 중 순위)가 80 이상 또는 20 이하. 그날 켜진 조건 수 = 점수.
 3) 점수 문턱 = 그때까지의 시작점 가운데 40% 이상을 '3일 전~당일'에 잡는 가장 높은 점수.
채점은 보유일 없이: 신호가 시작점 3일 전~당일 안이었나, 신호 뒤 ±5% 중 어느 쪽에 먼저 닿았나.
해마다 그 해 이전 자료로만 1)~3)을 하고 그 해를 채점한다(2016~). 마지막으로 전체 자료로 만든 것이 '지금 쓰는 신호'다."""
import json, os, pickle, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, '..', 'combo')); sys.path.insert(0, HERE)
from turn_probe import zigzag, cat_of, CATS, thin   # noqa: E402
from combo_probe import TRAIN_START   # noqa: E402
MATCH = 'PF_등락_5d'; NN = 200; MAXC = 8; HI, LO = 80, 20; WIN = 3; CATCH = 0.40; MOVE = 0.05


def main():
    panel = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, '..', 'uni', 'out', 'panel.pkl')
    D = pickle.load(open(panel, 'rb')); X, F = D['X'], D['P']['K200F']; td = X.index; n = len(td); c = F['close'].values.astype(float); i0 = int(td.searchsorted(TRAIN_START)); yr = td.year.values
    R = X.rolling(250, min_periods=120).rank(pct=True).values * 100; cols = list(X.columns); cat = [cat_of(x) for x in cols]; mj = cols.index(MATCH); lo_ = i0 + 10
    ft = np.full(n, np.nan)
    for d in range(i0, n):
        for k in range(d + 1, n):
            r = c[k] / c[d] - 1
            if r >= MOVE: ft[d] = 1; break
            if r <= -MOVE: ft[d] = 0; break
    piv_all = zigzag(c, 0.05)

    def build(typ, cut, seed):
        """cut 앞 자료만으로 조건과 문턱을 정한다."""
        rs = np.random.default_rng(seed); ev = np.array([p for p, t in zigzag(c[:cut], 0.05) if t == typ and p >= lo_]); E = len(ev); span = cut - lo_
        lev = lambda pos: np.nanmean(R[pos - 1], 0)
        with np.errstate(invalid='ignore'):
            real = lev(ev); nul = np.array([lev(lo_ + (ev - lo_ + int(s)) % span) for s in rs.integers(40, span - 40, size=NN)]); z = (real - np.nanmean(nul, 0)) / (np.nanstd(nul, 0) + 1e-9)
            ok = np.zeros(n, bool); ok[lo_:cut] = np.isfinite(R[lo_:cut, mj])
            for p in ev: ok[max(p - 10, 0):p + 1] = False
            b_all = np.clip(np.nan_to_num(R[:, mj]) // 10, 0, 9).astype(int); pool = [np.where(ok & (b_all == b))[0] for b in range(10)]; eb = b_all[ev - 1]; us = np.isfinite(R[ev - 1, mj])
            mn = np.array([lev(np.array([rs.choice(pool[b]) + 1 if u and len(pool[b]) else p for p, b, u in zip(ev, eb, us)])) for _ in range(NN)]); ctrl = np.nanmean(mn, 0); zm = (real - ctrl) / (np.nanstd(mn, 0) + 1e-9)
        cover = np.isfinite(R[ev - 1]).mean(0); recent = np.isfinite(R[max(cut - 250, 0):cut]).mean(0)
        cand = [j for j in np.argsort(-np.abs(zm)) if abs(z[j]) >= 3 and abs(zm[j]) >= 2.5 and cover[j] >= 0.7 and recent[j] >= 0.9 and ((real[j] >= 55 and real[j] > ctrl[j]) or (real[j] <= 45 and real[j] < ctrl[j]))]
        Rt = pd.DataFrame(R[lo_:cut]); comps = []
        for j in cand:
            if any(abs(Rt[j].corr(Rt[q[0]])) > 0.8 for q in comps): continue
            comps.append((int(j), 'hi' if real[j] >= 55 else 'lo', round(float(real[j]), 1), round(float(ctrl[j]), 1), round(float(z[j]), 1), round(float(zm[j]), 1)))
            if len(comps) >= MAXC: break
        score = np.zeros(n, int)
        for j, side, *_ in comps: score += np.nan_to_num((R[:, j] >= HI) if side == 'hi' else (R[:, j] <= LO)).astype(int)
        k = 2; table = []
        for kk in range(len(comps), 1, -1):
            on = score[lo_:cut] >= kk; days = np.where(on)[0] + lo_; ds = set(days.tolist()); caught = sum(1 for p in ev if any((p - q) in ds for q in range(WIN + 1))); sg = thin(days, 5); evs = set(ev.tolist()); hit = sum(1 for d in sg if any((d + q) in evs for q in range(WIN + 1)))
            table.append([kk, len(sg), hit, caught, E])
        for kk, ns, hit, caught, _ in table:
            if E and caught / E >= CATCH: k = kk; break
        return dict(comps=comps, k=k, score=score, E=E, table=table)

    def judge(score, k, typ, a, b):
        """[a, b) 구간 채점."""
        evs = [p for p, t in piv_all if t == typ and a <= p < b]; es = set(p for p, t in piv_all if t == typ); days = np.where(score[a:b] >= k)[0] + a; ds = set(days.tolist()); sg = thin(days, 5)
        caught = sum(1 for p in evs if any((p - q) in ds for q in range(WIN + 1))); hit = sum(1 for d in sg if any((d + q) in es for q in range(WIN + 1)))
        want = 1 if typ == 'L' else 0; dec = [d for d in sg if np.isfinite(ft[d])]; okk = sum(1 for d in dec if ft[d] == want); al = ft[a:b][np.isfinite(ft[a:b])]; base = float((al == want).mean()) if len(al) else None
        inwin = np.zeros(b - a, bool)
        for p in es:
            for q in range(WIN + 1):
                if a <= p - q < b: inwin[p - q - a] = True
        return dict(events=len(evs), caught=caught, sig=len(sg), hit=hit, base_in=float(inwin.mean()), dec=len(dec), ok=okk, base_ft=base, dates=[[str(td[d].date()), int(any((d + q) in es for q in range(WIN + 1))), None if not np.isfinite(ft[d]) else int(ft[d] == want)] for d in sg])

    out = dict(last_day=str(td[-1].date()), rule=dict(max_components=MAXC, hi=HI, lo=LO, window='시작점 3일 전~당일', catch=CATCH), types={})
    M = [f'# 시작 전 공통점으로 만든 매매 신호 (자료 ~ {td[-1].date()})', '', '- 조건 = 지표의 자리(지난 250일 중 순위, 0~100)가 80 이상 또는 20 이하. 점수 = 그날 켜진 조건 수. 점수가 문턱 이상이면 신호(5거래일 간격으로 솎음).',
         '- 조건과 문턱은 규칙으로 고른다: 시작점 1일 전 자리가 우연과도, 지수가 비슷하게 움직인 다른 날과도 달랐던 지표(겹치는 것은 하나만, 최대 8개), 문턱은 과거 시작점의 40% 이상을 잡는 가장 높은 점수.',
         '- 채점은 보유일 없이: "맞음" = 신호가 시작점 3일 전~당일 안. "먼저 닿음" = 신호일 종가에서 원하는 쪽 5%에 먼저 닿음.', '']
    daily = pd.DataFrame(index=td[i0:])
    for key, typ, lab, act in (('buy', 'L', '매수 신호(상승 시작 전)', '+5%'), ('sell', 'H', '매도 신호(하락 시작 전)', '−5%')):
        fin = build(typ, n, 1); wf = {}; tot = dict(events=0, caught=0, sig=0, hit=0, dec=0, ok=0); bw = bf = 0.0; ex = dict(tot); exw = exf = 0.0; alt = {t: dict(tot, bw=0.0, bf=0.0) for t in (0.2, 0.6)}
        for Y in range(2016, int(yr[-1]) + 1):
            a = int(np.where(yr == Y)[0][0]); b = int(np.where(yr == Y)[0][-1]) + 1; m = build(typ, a, Y); j = judge(m['score'], m['k'], typ, a, b); j.update(k=m['k'], comps=[[cols[x[0]], x[1]] for x in m['comps']]); wf[Y] = j
            for tg, at in alt.items():      # 문턱을 다르게 잡았다면(과거 시작점의 20% / 60% 이상을 잡는 가장 높은 점수)
                ka = next((kk for kk, ns, hit, cg, E_ in m['table'] if E_ and cg / E_ >= tg), 2); ja = judge(m['score'], ka, typ, a, b)
                for q in ('events', 'caught', 'sig', 'hit', 'dec', 'ok'): at[q] += ja[q]
                at['bw'] += ja['sig'] * ja['base_in']; at['bf'] += ja['dec'] * (ja['base_ft'] or 0)
            for t_, w_ in ((tot, 1), (ex, Y != 2026)):
                if w_:
                    for q in ('events', 'caught', 'sig', 'hit', 'dec', 'ok'): t_[q] += j[q]
            bw += j['sig'] * j['base_in']; bf += j['dec'] * (j['base_ft'] or 0)
            if Y != 2026: exw += j['sig'] * j['base_in']; exf += j['dec'] * (j['base_ft'] or 0)
        ins = judge(fin['score'], fin['k'], typ, lo_, n); sc = fin['score']; cur = [[cols[x[0]], x[1], None if not np.isfinite(R[-1, x[0]]) else round(float(R[-1, x[0]]), 0), bool((R[-1, x[0]] >= HI) if x[1] == 'hi' else (R[-1, x[0]] <= LO))] for x in fin['comps']]
        daily[key + '_score'] = sc[i0:]; daily[key + '_signal'] = (sc[i0:] >= fin['k']).astype(int)
        out['types'][key] = dict(label=lab, comps=[[cols[x[0]], cat[x[0]], x[1], x[2], x[3], x[4], x[5]] for x in fin['comps']], k=fin['k'], table=fin['table'], insample={q: ins[q] for q in ('events', 'caught', 'sig', 'hit', 'dec', 'ok', 'base_in', 'base_ft')},
                                 wf_total=dict(tot, base_in=bw / max(tot['sig'], 1), base_ft=bf / max(tot['dec'], 1)), wf_ex2026=dict(ex, base_in=exw / max(ex['sig'], 1), base_ft=exf / max(ex['dec'], 1)), wf=wf, now=dict(score=int(sc[-1]), on=bool(sc[-1] >= fin['k']), comps=cur), recent=ins['dates'][-8:])
        pc = lambda a_, b_: '—' if not b_ else f'{a_ / b_ * 100:.0f}%'
        M += [f'## {lab}', '', f"### 지금 쓰는 신호(전체 자료로 만든 것) — 조건 {len(fin['comps'])}개 가운데 {fin['k']}개 이상 켜지면 신호", '', '| 묶음 | 지표 | 조건 | 시작 1일 전 평균 자리 | 비슷한 다른 날 | z · 지수 감안 z | 지금 자리 | 지금 켜짐 |', '|---|---|---|---|---|---|---|---|']
        for (j_, side, lv, ct, z_, zm_), cu in zip(fin['comps'], cur): M.append(f"| {CATS[cat[j_]]} | {cols[j_]} | {'80 이상' if side == 'hi' else '20 이하'} | {lv:.0f} | {ct:.0f} | {z_:+.1f} · {zm_:+.1f} | {'—' if cu[2] is None else int(cu[2])} | {'○' if cu[3] else ''} |")
        M += ['', f"지금({td[-1].date()}) 점수 {int(sc[-1])} / 문턱 {fin['k']} → {'신호 켜짐' if sc[-1] >= fin['k'] else '신호 없음'}. 최근 신호: " + ', '.join(f"{d}{'(맞음)' if h else '(아님)'}" for d, h, _ in ins['dates'][-6:]), '',
              '문턱별(전체 기간, 만들 때 본 자료): ' + ' · '.join(f"{kk}개 이상: 신호 {ns}, 맞음 {hit}({pc(hit, ns)}), 시작점 {cg}/{E_} 잡음" for kk, ns, hit, cg, E_ in fin['table']), '',
              '### 해마다 그 해 이전 자료로만 만들어 그 해에 썼다면', '', f'| 해 | 조건 수·문턱 | 시작점 | 잡은 것 | 신호 | 맞음 | {act} 먼저 닿음 |', '|---|---|---|---|---|---|---|']
        for Y, j in wf.items(): M.append(f"| {Y} | {len(j['comps'])}개 중 {j['k']} | {j['events']} | {j['caught']} | {j['sig']} | {j['hit']} | {j['ok']}/{j['dec']} |")
        for nm, t_, w1, w2 in (('합계', tot, bw, bf), ('2026 빼고', ex, exw, exf)):
            M.append(f"| **{nm}** | | {t_['events']} | {t_['caught']} ({pc(t_['caught'], t_['events'])}) | {t_['sig']} | {t_['hit']} ({pc(t_['hit'], t_['sig'])} · 아무 날 {w1 / max(t_['sig'], 1) * 100:.0f}%) | {t_['ok']}/{t_['dec']} ({pc(t_['ok'], t_['dec'])} · 아무 날 {w2 / max(t_['dec'], 1) * 100:.0f}%) |")
        for tg, at in sorted(alt.items()):
            M.append(f"| 문턱을 '과거 시작점의 {int(tg * 100)}% 잡기'로 했다면 | | {at['events']} | {at['caught']} ({pc(at['caught'], at['events'])}) | {at['sig']} | {at['hit']} ({pc(at['hit'], at['sig'])} · 아무 날 {at['bw'] / max(at['sig'], 1) * 100:.0f}%) | {at['ok']}/{at['dec']} ({pc(at['ok'], at['dec'])} · 아무 날 {at['bf'] / max(at['dec'], 1) * 100:.0f}%) |")
        out['types'][key]['wf_alt'] = {str(tg): at for tg, at in alt.items()}
        M += ['', f"(만들 때 본 자료 전체로는: 신호 {ins['sig']}, 맞음 {ins['hit']}({pc(ins['hit'], ins['sig'])}), 시작점 {ins['caught']}/{ins['events']} 잡음, {act} 먼저 닿음 {ins['ok']}/{ins['dec']}({pc(ins['ok'], ins['dec'])}))", '']
    M += ['모두 과거 자료 성적이다. 투자 권유 아님']; od = os.path.join(HERE, 'out'); os.makedirs(od, exist_ok=True)
    open(os.path.join(od, 'signal_report.md'), 'w', encoding='utf-8').write('\n'.join(M) + '\n'); json.dump(out, open(os.path.join(od, 'signal_summary.json'), 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    daily.tail(520).to_csv(os.path.join(od, 'signal_daily.csv'), encoding='utf-8'); print({k: (v['k'], len(v['comps']), v['wf_total']) for k, v in out['types'].items()})


if __name__ == '__main__':
    main()
