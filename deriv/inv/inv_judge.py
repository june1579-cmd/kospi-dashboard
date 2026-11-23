#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""I3 판정 — 표본 밖 '내릴 확률'로 인버스 매수 신호와 인버스 매수·매도 규칙을 만들고 CRITERIA.md 로 판정한다.

입력: deriv/uni/out/panel.pkl · out/prices.pkl · out/preds.pkl
출력: out/verdicts.csv · out/strategies.csv · out/baseline.json · out/now.json · out/report.md · state/registry.json · state/status.json · notify/kakao.txt(+send.flag)
기준 숫자(CRIT·RT·STRAT·FAMILY)는 잠금 — 사용자만 바꾼다. 솎기·문턱·성적 함수는 통합 예측 연구소(uni_judge)와 같은 것을 쓴다.
"""
import json
import os
import pickle
import time

import numpy as np
import pandas as pd

import inv_common as C
import uni_judge as UJ

U = C.U
CRIT = {'pass': dict(n=40, hit=0.65, pn=15, ph=0.60), 'watch': dict(n=40, hit=0.60, pn=15, ph=0.55)}
RT = dict(p=0.05, loyo_margin=0.05, conc=0.40)
STRAT = {'pass': dict(mdd=-15.0, ratio=0.5, loss_years=3), 'watch': dict(mdd=-20.0)}
FAMILY = 0.05
QS = (0.8, 0.9)
PAIRS = ((0.8, 0.5), (0.9, 0.5), (0.9, 0.7))        # (살 때 문턱, 팔 때 문턱) — 지난 3년 예측의 분위
B = int(os.environ.get('UNI_B', '500')); SEED = 20261123


def num_grade(n, hit, n1, hit1, n2, hit2, m1, m2):
    for g in ('pass', 'watch'):
        c = CRIT[g]
        if n >= c['n'] and hit >= c['hit'] and n1 >= c['pn'] and hit1 >= c['ph'] and n2 >= c['pn'] and hit2 >= c['ph'] and m1 > 0 and m2 > 0: return g
    return ''


def want_state(p, hi, lo, maxhold):
    w = np.zeros(len(p)); s = 0; held = 0
    for i in range(len(p)):
        if s:
            held += 1
            if (np.isfinite(p[i]) and np.isfinite(lo[i]) and p[i] <= lo[i]) or held >= maxhold: s = 0; held = 0
        elif np.isfinite(p[i]) and np.isfinite(hi[i]) and p[i] >= hi[i]: s = 1; held = 0
        w[i] = s
    return w


def rule_ret(want, o, c):
    """want[t] = t일 장 마감 뒤 정한 보유 여부 → t+1 시가에 사거나 판다."""
    n = len(want); hold = np.zeros(n); hold[1:] = want[:-1]; r = np.zeros(n)
    for i in range(1, n):
        if hold[i] and hold[i - 1]: r[i] = c[i] / c[i - 1] - 1
        elif hold[i]: r[i] = c[i] / o[i] - 1 - C.COST_SIDE
        elif hold[i - 1]: r[i] = o[i] / c[i - 1] - 1 - C.COST_SIDE
    return r, hold


def main():
    t0 = time.time(); D = pickle.load(open(os.path.join(C.UNI, 'out', 'panel.pkl'), 'rb')); full = D['X'].index
    PX = pickle.load(open(os.path.join(C.OUT, 'prices.pkl'), 'rb')); PR = pickle.load(open(os.path.join(C.OUT, 'preds.pkl'), 'rb'))
    idx = PR.index; off = int(full.searchsorted(idx[0])); n = len(idx); sl = slice(off, off + n)
    ev = np.where(idx >= U.EVAL_START)[0]; e0 = ev[0]; W = len(ev); fh = (idx[ev] < U.SPLIT); ie = idx[ev]
    rng = np.random.default_rng(SEED); shifts = rng.integers(250, W - 250, size=B)
    px1, px2 = PX['inv1'], PX['inv2']; T = {tn: dict(kind=k, H=H, r=C.hold_ret(px1, H)[sl][ev], r2=C.hold_ret(px2, H)[sl][ev]) for tn, k, H, th in C.TARGETS}
    today = pd.Timestamp.now(tz='Asia/Seoul').strftime('%Y-%m-%d')

    # ---------------- 1) 인버스 매수 신호
    rows = []; fam = {'pass': np.zeros(B, bool), 'watch': np.zeros(B, bool)}; SIG = {}
    def halves(k, x, h1):
        n1 = int(h1.sum()); n2 = len(x) - n1
        return n1, (float((x[h1] > 0).mean()) if n1 else 0.0), n2, (float((x[~h1] > 0).mean()) if n2 else 0.0), (float(x[h1].mean()) if n1 else 0.0), (float(x[~h1].mean()) if n2 else 0.0)
    for col in PR.columns:
        tn, sn, mn = col.split('|'); t = T[tn]; p = PR[col].values; rr = t['r']; known = np.isfinite(rr); base = float((rr[known] > 0).mean())
        for q in QS:
            hi = UJ.thr_series(p, idx, q); va = (p >= hi) & np.isfinite(p) & np.isfinite(hi); v = va[ev]; cid = f'{col}|buy|q{int(q * 100)}'; SIG[cid] = va
            rec = dict(id=cid, target=tn, set=sn, model=mn, q=q, n=0, hit=np.nan, n1=0, hit1=np.nan, n2=0, hit2=np.nan, base=round(base, 4), lb=0.0, mean=np.nan, grade_num='', rt_ok=False)
            st = UJ.stat_sig(v & known, rr, t['H'], fh)
            if st is not None:
                k, x, h1 = st; nn = len(x); hit = float((x > 0).mean()); n1, hit1, n2, hit2, m1, m2 = halves(k, x, h1)
                ys = ie[k].year; by = pd.Series(x).groupby(ys); loyo = min([float((x[ys != y] > 0).mean()) for y in np.unique(ys) if (ys != y).sum() >= 20] or [np.nan])
                tot = float(x.sum()); conc = float(by.sum().max() / tot) if tot > 0 else np.nan; x2 = t['r2'][k]
                rec.update(n=nn, hit=round(hit, 4), n1=n1, hit1=round(hit1, 4), n2=n2, hit2=round(hit2, 4), lb=round(U.wilson_lb(int((x > 0).sum()), nn), 4), mean=round(float(x.mean()) * 100, 3),
                           mean1=round(m1 * 100, 3), mean2=round(m2 * 100, 3), mean_2x=round(float(np.nanmean(x2)) * 100, 3), worst=round(float(x.min()) * 100, 2),
                           loyo=round(loyo, 4) if np.isfinite(loyo) else np.nan, conc=round(conc, 3) if np.isfinite(conc) else np.nan, last=str(ie[k][-1].date()),
                           by_year=json.dumps({int(y): [int(g.size), round(float((g > 0).mean()), 2), round(float(g.sum()) * 100, 1)] for y, g in by}))
                rec['grade_num'] = num_grade(nn, hit, n1, hit1, n2, hit2, m1, m2); ge = 0
                for bi, s in enumerate(shifts):
                    st2 = UJ.stat_sig(np.roll(v, s) & known, rr, t['H'], fh)
                    if st2 is None: continue
                    k2, y2, g2 = st2; h_ = float((y2 > 0).mean()); ge += h_ >= hit; a1, b1, a2, b2, c1, c2 = halves(k2, y2, g2); gn = num_grade(len(y2), h_, a1, b1, a2, b2, c1, c2)
                    if gn == 'pass': fam['pass'][bi] = True; fam['watch'][bi] = True
                    elif gn == 'watch': fam['watch'][bi] = True
                rec['placebo_p'] = round((ge + 1) / (B + 1), 4); c = CRIT[rec['grade_num']] if rec['grade_num'] else None
                rec['rt_ok'] = bool(c and rec['placebo_p'] < RT['p'] and rec['lb'] > base and np.isfinite(loyo) and loyo >= c['hit'] - RT['loyo_margin'] and np.isfinite(conc) and conc < RT['conc'])
            rows.append(rec)
    V = pd.DataFrame(rows); fw = {g: round(float(fam[g].mean()), 4) for g in fam}
    V['grade'] = [('보류(우연 가능)' if (g == 'pass' and fw['pass'] >= FAMILY) or (g == 'watch' and fw['watch'] >= 0.5) else {'pass': '통과', 'watch': '관찰'}[g]) if (g and ok) else ('숫자만 채움(반증 탈락)' if g else '') for g, ok in zip(V['grade_num'], V['rt_ok'])]
    V.sort_values('lb', ascending=False).to_csv(os.path.join(C.OUT, 'verdicts.csv'), index=False, encoding='utf-8')

    # ---------------- 2) 인버스 매수·매도 규칙(사고파는 규칙 전체)
    o1 = px1['open'].values.astype(float)[sl]; c1 = px1['close'].values.astype(float)[sl]; o2 = px2['open'].values.astype(float)[sl]; c2 = px2['close'].values.astype(float)[sl]
    seg = {'all': np.ones(W, bool), 'h1': fh, 'h2': ~fh}; pf = lambda r_: {s: UJ.perf(r_[ev][m], ie[m]) for s, m in seg.items()}
    def sgrade(S, loss):
        if all(S[s]['total'] > 0 for s in seg) and S['all']['mdd'] >= STRAT['pass']['mdd'] and S['all']['ratio'] >= STRAT['pass']['ratio'] and loss <= STRAT['pass']['loss_years']: return 'pass'
        if all(S[s]['total'] > 0 for s in seg) and S['all']['mdd'] >= STRAT['watch']['mdd']: return 'watch'
        return ''
    lossy = lambda r_: int((pd.Series(r_[ev]).groupby(ie.year).apply(lambda v_: float(np.prod(1 + v_) - 1)) < 0).sum())
    srows = []; sfam = np.zeros(B, bool)
    for col in PR.columns:
        tn, sn, mn = col.split('|'); H = T[tn]['H']
        if tn not in ('DN3', 'DN5', 'DN10', 'DROP5', 'DROP10'): continue
        p = PR[col].values
        for qh, ql in PAIRS:
            w = want_state(p, UJ.thr_series(p, idx, qh), UJ.thr_series(p, idx, ql), 2 * H); r_, hold = rule_ret(w, o1, c1); S = pf(r_); ly = lossy(r_); g = sgrade(S, ly)
            r2_, _ = rule_ret(w, o2, c2); S2x = pf(r2_); by = pd.Series(r_[ev]).groupby(ie.year).apply(lambda v_: float(np.prod(1 + v_) - 1)); ge = 0
            buys = int((np.diff(hold[ev]) > 0).sum())
            for bi, s in enumerate(shifts):
                w2 = w.copy(); w2[ev] = np.roll(w[ev], s); rb, _ = rule_ret(w2, o1, c1); Sb = pf(rb); ge += Sb['all']['total'] >= S['all']['total']
                if sgrade(Sb, lossy(rb)) == 'pass': sfam[bi] = True
            pv = round((ge + 1) / (B + 1), 4)
            srows.append(dict(id=f'{col}|rule|{int(qh * 100)}-{int(ql * 100)}', target=tn, set=sn, model=mn, hi=qh, lo=ql, maxhold=2 * H, total=S['all']['total'], cagr=S['all']['cagr'], mdd=S['all']['mdd'], ratio=S['all']['ratio'],
                              total1=S['h1']['total'], total2=S['h2']['total'], buys=buys, days_in=round(float(hold[ev].mean()), 3), loss_years=ly, years=int(len(by)), total_2x=S2x['all']['total'], mdd_2x=S2x['all']['mdd'],
                              placebo_p=pv, grade_num=g, by_year=json.dumps({int(y): round(v_ * 100, 1) for y, v_ in by.items()})))
    SV = pd.DataFrame(srows); sfw = round(float(sfam.mean()), 4)
    SV['grade'] = [('보류(우연 가능)' if g == 'pass' and sfw >= FAMILY else {'pass': '통과', 'watch': '관찰'}[g]) if (g and pv < RT['p']) else ('숫자만 채움(반증 탈락)' if g else '') for g, pv in zip(SV['grade_num'], SV['placebo_p'])]
    SV.sort_values('total', ascending=False).to_csv(os.path.join(C.OUT, 'strategies.csv'), index=False, encoding='utf-8')

    # ---------------- 3) 기준선: 인버스를 그냥 들고 있기 · 대시보드 매도 신호에 인버스 사기
    alw = np.zeros(n); alw[1:] = c1[1:] / c1[:-1] - 1; alw2 = np.zeros(n); alw2[1:] = c2[1:] / c2[:-1] - 1; AH = pf(alw); AH2 = pf(alw2); base_rows = []
    fp = os.path.join(U.MAIN, 'out', 'sell3.csv')
    if os.path.exists(fp):
        d = pd.read_csv(fp); d = d[d['start'] == '시작']
        for ty, gdf in d.groupby('type'):
            v = np.isin(ie.strftime('%Y-%m-%d'), gdf['date'].astype(str).values)
            for H in (5, 10, 20):
                rr = C.hold_ret(px1, H)[sl][ev]; known = np.isfinite(rr); st = UJ.stat_sig(v & known, rr, H, fh)
                if st is None: continue
                k, x, h1 = st; n1, hit1, n2, hit2, m1, m2 = halves(k, x, h1)
                base_rows.append(dict(name=f'대시보드 매도 {ty}', hold=H, n=int(len(x)), hit=round(float((x > 0).mean()), 4), n1=n1, hit1=round(hit1, 4), n2=n2, hit2=round(hit2, 4), base=round(float((rr[known] > 0).mean()), 4), mean=round(float(x.mean()) * 100, 2)))
    json.dump(dict(always=AH, always_2x=AH2, dashboard_sell=base_rows, prices=PX['meta']), open(os.path.join(C.OUT, 'baseline.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

    # ---------------- 4) 등록·오늘 상태·전진 기록
    rp = os.path.join(C.STATE, 'registry.json'); REG = json.load(open(rp, encoding='utf-8')) if os.path.exists(rp) else {}; new = []
    cur = {r_['id']: ('pass' if r_['grade'] == '통과' else 'watch') for _, r_ in pd.concat([V[['id', 'grade']], SV[['id', 'grade']]]).iterrows() if r_['grade'] in ('통과', '관찰')}
    for cid, g in cur.items():
        if cid not in REG: REG[cid] = dict(grade=g, since=today, first_grade=g, data_end=str(idx[-1].date())); new.append((cid, g))
        elif REG[cid]['grade'] != g:
            if g == 'pass' and REG[cid]['grade'] == 'watch': new.append((cid, g))
            REG[cid]['grade'] = g; REG[cid]['changed'] = today
    last = n - 1; now = dict(date=str(idx[last].date()), made=today, signals={}, probs={})
    for cid, info in REG.items():
        info['now'] = cur.get(cid, '기준 미달')
        if cid in SIG:
            va = SIG[cid]; t = T[cid.split('|')[0]]; since = pd.Timestamp(info.get('data_end', info['since']))
            info['forward'] = [dict(date=str(idx[i].date()), ret=(None if not np.isfinite(t['r'][i - e0]) else round(float(t['r'][i - e0]) * 100, 2))) for i in np.where(va)[0] if idx[i] > since and i >= e0]
            now['signals'][cid] = bool(va[last])
    for col in PR.columns:
        if col.endswith('|all|ens'): now['probs'][col] = None if not np.isfinite(PR[col].values[last]) else round(float(PR[col].values[last]), 3)
    json.dump(REG, open(rp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1); json.dump(now, open(os.path.join(C.OUT, 'now.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    cnt = lambda df, g: int((df['grade'] == g).sum())
    status = dict(made=pd.Timestamp.now(tz='Asia/Seoul').strftime('%Y-%m-%d %H:%M'), data_end=str(idx[-1].date()), eval=[str(ie[0].date()), str(ie[-1].date())], candidates=int(len(V)), rules=int(len(SV)),
                  signal_pass=cnt(V, '통과'), signal_watch=cnt(V, '관찰'), signal_held=cnt(V, '보류(우연 가능)'), signal_num_only=cnt(V, '숫자만 채움(반증 탈락)'),
                  rule_pass=cnt(SV, '통과'), rule_watch=cnt(SV, '관찰'), rule_held=cnt(SV, '보류(우연 가능)'), rule_num_only=cnt(SV, '숫자만 채움(반증 탈락)'),
                  family_chance=dict(signal_pass=fw['pass'], signal_watch=fw['watch'], rule_pass=sfw), registered=len(REG), new=[list(x) for x in new], placebo_draws=B, prices=PX['meta'], seconds=round(time.time() - t0))
    json.dump(status, open(os.path.join(C.STATE, 'status.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

    # ---------------- 5) 보고서
    pc = lambda v_: '—' if v_ is None or (isinstance(v_, float) and not np.isfinite(v_)) else f'{v_ * 100:.1f}%'
    sgn = lambda v_: '—' if v_ is None or not np.isfinite(v_) else ('+' if v_ > 0 else '−' if v_ < 0 else '') + f'{abs(v_):,.1f}%'
    sg2 = lambda v_: '—' if v_ is None or not np.isfinite(v_) else ('+' if v_ > 0 else '−' if v_ < 0 else '') + f'{abs(v_):,.2f}%'
    nm = lambda r_: f"{C.TARGET_NAME[r_['target']]} · {U.SET_NAME[r_['set']]} · {U.MODEL_NAME[r_['model']]}"; pm = PX['meta']['inv1']
    M = ['# 인버스 매수·매도 연구(갈래 I) 결과', '', f"- 만든 때 {status['made']} KST · 자료 끝 {status['data_end']} · 평가 {status['eval'][0]} ~ {status['eval'][1]} (표본 밖 예측만)",
         f"- 인버스 가격: {pm['name']} — 평가 기간의 {pm['eval_real_share'] * 100:.0f}%가 실제 ETF 시세({pm['note']}" + (f", 선물과의 하루 수익 상관 {pm['corr_with_futures']}" if pm['corr_with_futures'] is not None else '') + '), 나머지는 선물 수익으로 계산한 값',
         f"- 인버스 매수 신호 후보 {len(V)}개: 통과 {status['signal_pass']} · 관찰 {status['signal_watch']} · 보류 {status['signal_held']} · 숫자만 채우고 반증 탈락 {status['signal_num_only']}",
         f"- 매수·매도 규칙 후보 {len(SV)}개: 통과 {status['rule_pass']} · 관찰 {status['rule_watch']} · 보류 {status['rule_held']} · 숫자만 채우고 반증 탈락 {status['rule_num_only']}",
         f"- 우연만으로 통과 숫자를 채우는 후보가 하나라도 나올 비율: 신호 통과 {pc(fw['pass'])} · 신호 관찰 {pc(fw['watch'])} · 규칙 통과 {pc(sfw)} (가짜 신호 {B}번)", '',
         '기준은 `deriv/inv/CRITERIA.md`. 모두 과거 자료 성적이다.', '', '## 기준선', '',
         f"- 인버스를 그냥 들고 있으면: 1배 {sgn(AH['all']['total'])} (최대 낙폭 {sgn(AH['all']['mdd'])}), 2배 {sgn(AH2['all']['total'])} (최대 낙폭 {sgn(AH2['all']['mdd'])})", '',
         '## 인버스 매수 신호: 등급을 받은 후보와 가장 가까운 후보', '', '다음 날 시가에 사서 정해진 보유일 종가에 팔 때(1배, 왕복 비용 0.1% 뺌).', '',
         '| 등급 | 대상 · 자료 · 모형 | 문턱 | 독립 신호 | 적중 | 앞 | 뒤 | 바탕 | 거래당(1배) | 거래당(2배) | 가장 나쁜 거래 | 가짜 신호 p |', '|---|---|---|---|---|---|---|---|---|---|---|---|']
    vs = V[V['n'] >= 30].copy(); vs['rk'] = vs['grade'].map({'통과': 0, '관찰': 1, '보류(우연 가능)': 2, '숫자만 채움(반증 탈락)': 3}).fillna(4)
    for _, r_ in vs.sort_values(['rk', 'lb'], ascending=[True, False]).head(12).iterrows():
        M.append(f"| {r_['grade'] or '미달'} | {nm(r_)} | 상위 {int(round((1 - r_['q']) * 100))}% | {int(r_['n'])} | {pc(r_['hit'])} | {int(r_['n1'])}건 {pc(r_['hit1'])} | {int(r_['n2'])}건 {pc(r_['hit2'])} | {pc(r_['base'])} | {sg2(r_['mean'])} | {sg2(r_.get('mean_2x'))} | {sg2(r_.get('worst'))} | {r_.get('placebo_p')} |")
    M += ['', '## 대시보드 매도 신호가 켜진 날 인버스를 샀다면(같은 잣대)', '', '| 신호 | 보유 | 독립 신호 | 적중 | 앞 | 뒤 | 바탕 | 거래당 |', '|---|---|---|---|---|---|---|---|']
    for b in base_rows: M.append(f"| {b['name']} | {b['hold']}일 | {b['n']} | {pc(b['hit'])} | {b['n1']}건 {pc(b['hit1'])} | {b['n2']}건 {pc(b['hit2'])} | {pc(b['base'])} | {sg2(b['mean'])} |")
    M += ['', '대시보드 매도 신호는 2015~2024년 자료로 고른 것이라 그 기간 성적이 부풀어 있다.', '', '## 인버스 매수·매도 규칙(내릴 확률이 높아지면 사고, 낮아지거나 최대 보유일이 지나면 판다)', '',
          '| 등급 | 대상 · 자료 · 모형 | 살 때-팔 때 문턱 | 누적(1배) | 최대 낙폭 | 수익÷낙폭 | 앞 | 뒤 | 산 횟수 | 들고 있던 날 | 손실 난 해 | 누적(2배) | 가짜 신호 p |', '|---|---|---|---|---|---|---|---|---|---|---|---|---|']
    sv = SV.copy(); sv['rk'] = sv['grade'].map({'통과': 0, '관찰': 1, '보류(우연 가능)': 2, '숫자만 채움(반증 탈락)': 3}).fillna(4)
    for _, r_ in sv.sort_values(['rk', 'total'], ascending=[True, False]).head(10).iterrows():
        M.append(f"| {r_['grade'] or '미달'} | {nm(r_)} | 상위 {int(round((1 - r_['hi']) * 100))}% - 상위 {int(round((1 - r_['lo']) * 100))}% 밖 | {sgn(r_['total'])} | {sgn(r_['mdd'])} | {r_['ratio']} | {sgn(r_['total1'])} | {sgn(r_['total2'])} | {int(r_['buys'])} | {r_['days_in'] * 100:.0f}% | {int(r_['loss_years'])}/{int(r_['years'])} | {sgn(r_['total_2x'])} | {r_['placebo_p']} |")
    M += ['', '## 등록된 후보(등록일 뒤 실제 신호만 따로 적음)', '']
    if REG:
        M += ['| 후보 | 등급 | 등록일 | 지금 기준 | 등록 뒤 신호 | 오늘 |', '|---|---|---|---|---|---|']
        for cid, info in REG.items():
            fw_ = info.get('forward', []); done = [x for x in fw_ if x['ret'] is not None]; g_ = {'pass': '통과', 'watch': '관찰'}
            M.append(f"| {cid} | {g_[info['grade']]} | {info['since']} | {g_.get(info['now'], info['now'])} | {len(fw_)}건(끝난 것 {len(done)}건 중 {sum(x['ret'] > 0 for x in done)}건 맞음) | {'켜짐' if now['signals'].get(cid) else '꺼짐' if cid in now['signals'] else '—'} |")
    else: M.append('아직 없음.')
    M += ['', f"## 오늘({now['date']} 장 마감 기준) 내릴 확률 — 전부 넣은 둘 평균 모형", '', '통과한 후보가 없으면 참고하지 않는다.', '', '| 대상 | 내릴 확률 |', '|---|---|'] + [f"| {C.TARGET_NAME[k.split('|')[0]]} | {('—' if v_ is None else f'{v_ * 100:.0f}%')} |" for k, v_ in now['probs'].items()]
    M += ['', '투자 권유 아님']
    open(os.path.join(C.OUT, 'report.md'), 'w', encoding='utf-8').write('\n'.join(M) + '\n')

    # ---------------- 6) 카카오톡(새 통과·관찰이 있을 때만)
    flag = os.path.join(C.NOTIFY, 'send.flag')
    if os.path.exists(flag): os.remove(flag)
    if new:
        msg = [f"[인버스 연구] 전보다 나은 결과 {today}\n새 통과 {sum(g == 'pass' for _, g in new)}개 · 새 관찰 {sum(g == 'watch' for _, g in new)}개\n(누적 등록 {len(REG)}개, 자료 끝 {status['data_end']})"]
        for c, g in new[:4]:
            p_ = c.split('|'); gk = '통과' if g == 'pass' else '관찰'; row = V[V['id'] == c]
            if len(row): r_ = row.iloc[0]; msg.append(f"{gk}: 인버스 매수 신호 — {C.TARGET_NAME[p_[0]]}({U.SET_NAME[p_[1]]})\n독립 신호 {int(r_['n'])}건 적중 {pc(r_['hit'])} (앞 {pc(r_['hit1'])} · 뒤 {pc(r_['hit2'])}, 바탕 {pc(r_['base'])})\n거래당 {sg2(r_['mean'])} · 가짜 신호 p {r_['placebo_p']}")
            else: r_ = SV[SV['id'] == c].iloc[0]; msg.append(f"{gk}: 인버스 매수·매도 규칙 — {C.TARGET_NAME[p_[0]]}({U.SET_NAME[p_[1]]})\n누적 {sgn(r_['total'])} · 낙폭 {sgn(r_['mdd'])} · 산 횟수 {int(r_['buys'])}\n(인버스 그냥 보유 {sgn(AH['all']['total'])})")
        msg.append('과거 자료 성적입니다. 등록일 뒤 실제 신호는 따로 기록합니다. 투자 권유 아님')
        open(os.path.join(C.NOTIFY, 'kakao.txt'), 'w', encoding='utf-8').write('\n=====\n'.join(m[:200] for m in msg) + '\n'); open(flag, 'w').write(today)
    print(json.dumps({k: v for k, v in status.items() if k != 'prices'}, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
