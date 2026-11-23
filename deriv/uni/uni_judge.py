#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""U3 판정 — 표본 밖 예측으로 매수·매도 신호와 보유·현금 전략을 만들고 CRITERIA.md 기준으로 판정한다.

입력: out/panel.pkl, out/preds.pkl, --bench (main 의 pkg/combo_track.py --daily 가 만든 combo_daily.csv: 묶음 규칙·코스피 하루 수익)
출력: out/verdicts.csv(신호 후보 전부) · out/strategies.csv · out/ablation.csv · out/baseline.json · out/now.json · out/report.md
      state/registry.json(통과·관찰 등록, 등록일 고정) · state/status.json · notify/kakao.txt(새 통과·관찰이 있을 때만 바뀜) · notify/send.flag
기준 숫자(CRIT·RT·STRAT)는 잠금 — 사용자만 바꾼다.
"""
import argparse
import json
import os
import pickle
import time

import numpy as np
import pandas as pd
from scipy.stats import rankdata

import uni_common as U

CRIT = {'buy': {'pass': dict(n=40, hit=0.75, pn=15, ph=0.70), 'watch': dict(n=40, hit=0.70, pn=15, ph=0.65)},
        'sell': {'pass': dict(n=40, hit=0.65, pn=15, ph=0.60), 'watch': dict(n=40, hit=0.60, pn=15, ph=0.55)}}
RT = dict(p=0.05, loyo_margin=0.05, conc=0.40)
STRAT = {'pass': dict(mdd=-15.0), 'watch': dict(mdd=-20.0)}
FAMILY = 0.05
QS = (0.8, 0.9)
PAIRS = ((0.5, 0.3), (0.6, 0.4), (0.7, 0.3))
COST = 0.003
B = int(os.environ.get('UNI_B', '500'))
SEED = 20261123


def thr_series(p, idx, q):
    """그 해 문턱 = 직전 3개 해 표본 밖 예측의 q 분위(그 해 예측은 쓰지 않음)."""
    yr = idx.year.values; out = np.full(len(p), np.nan)
    for Y in np.unique(yr):
        prev = p[(yr >= Y - 3) & (yr < Y)]; prev = prev[np.isfinite(prev)]
        if len(prev) >= 400: out[yr == Y] = np.quantile(prev, q)
    return out


def thin_pos(a, hold):
    keep = []; i = 0; n = len(a)
    while i < n:
        keep.append(a[i]); i = int(np.searchsorted(a, a[i] + hold, side='right'))
    return np.asarray(keep, dtype=int)


def stat_sig(v, rr, hold, first_half):
    """v = 평가 구간 안 신호(참·거짓), rr = 그 방향 수익, hold = 솎는 간격(평가 구간 위치 기준)."""
    a = np.where(v)[0]
    if not len(a): return None
    k = thin_pos(a, hold); x = rr[k]; ok = np.isfinite(x); k, x = k[ok], x[ok]
    if not len(k): return None
    h1 = first_half[k]
    return k, x, h1


def num_grade(side, n, hit, n1, hit1, n2, hit2):
    for g in ('pass', 'watch'):
        c = CRIT[side][g]
        if n >= c['n'] and hit >= c['hit'] and n1 >= c['pn'] and hit1 >= c['ph'] and n2 >= c['pn'] and hit2 >= c['ph']: return g
    return ''


def perf(r, idx):
    if not len(r): return dict(total=0.0, cagr=0.0, mdd=0.0, ratio=0.0)
    eq = np.cumprod(1 + r); dd = float((eq / np.maximum.accumulate(eq) - 1).min()); yrs = max((idx[-1] - idx[0]).days / 365.25, 0.1)
    cagr = float(eq[-1]) ** (1 / yrs) - 1
    return dict(total=round(float(eq[-1] - 1) * 100, 1), cagr=round(cagr * 100, 2), mdd=round(dd * 100, 1), ratio=round(cagr / abs(dd), 3) if dd < 0 else 99.0)


def desired_state(p, hi, lo):
    d = np.zeros(len(p)); s = 0.0
    for i in range(len(p)):
        if np.isfinite(p[i]) and np.isfinite(hi[i]):
            if p[i] >= hi[i]: s = 1.0
            elif p[i] <= lo[i]: s = 0.0
        d[i] = s
    return d


def strat_ret(des, kr):
    pos = np.zeros(len(des)); pos[1:] = des[:-1]                  # t일 예측 → t+1일 종가에 체결
    r = np.zeros(len(des)); r[1:] = kr[1:] * pos[:-1] - COST / 2 * np.abs(np.diff(pos))
    return r, pos


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--bench', default=''); a = ap.parse_args(); t0 = time.time()
    D = pickle.load(open(os.path.join(U.OUT, 'panel.pkl'), 'rb')); P = D['P']
    PR = pickle.load(open(os.path.join(U.OUT, 'preds.pkl'), 'rb')); full = D['X'].index
    idx = PR.index; off = int(full.searchsorted(idx[0])); n = len(idx)
    ev = np.where(idx >= U.EVAL_START)[0]; e0 = ev[0]; W = len(ev); fh = (idx[ev] < U.SPLIT)
    rng = np.random.default_rng(SEED); shifts = rng.integers(250, W - 250, size=B)
    T = {}
    for tn, kind, H in U.TARGETS:
        ent, ext, r = U.target_arrays(P, kind, H); T[tn] = dict(kind=kind, H=H, r=r[off:off + n][ev], hold=(H + 1 if kind == 'IDX' else H))
    today = pd.Timestamp.now(tz='Asia/Seoul').strftime('%Y-%m-%d')

    # ---------------- 1) 신호 후보
    rows = []; fam = {'pass': np.zeros(B, bool), 'watch': np.zeros(B, bool)}; SIG = {}
    for col in PR.columns:
        tn, sn, mn = col.split('|'); t = T[tn]; p = PR[col].values
        for q in QS:
            hi = thr_series(p, idx, q); lo = thr_series(p, idx, 1 - q)
            for side, v_all, sg in (('buy', p >= hi, 1.0), ('sell', p <= lo, -1.0)):
                v = (v_all & np.isfinite(p) & np.isfinite(hi))[ev]; rr = sg * t['r']; cid = f'{col}|{side}|q{int(q * 100)}'; SIG[cid] = (v_all & np.isfinite(p) & np.isfinite(hi))
                known = np.isfinite(rr); base = float((rr[known] > 0).mean()); base1 = float((rr[known & fh] > 0).mean()); base2 = float((rr[known & ~fh] > 0).mean())
                st = stat_sig(v & known, rr, t['hold'], fh)
                rec = dict(id=cid, target=tn, set=sn, model=mn, side=side, q=q, n=0, hit=np.nan, n1=0, hit1=np.nan, n2=0, hit2=np.nan, base=round(base, 4), lb=0.0, mean=np.nan, grade_num='', days=int((v & known).sum()))
                if st is not None:
                    k, x, h1 = st; nn = len(x); hit = float((x > 0).mean()); n1 = int(h1.sum()); n2 = nn - n1
                    hit1 = float((x[h1] > 0).mean()) if n1 else np.nan; hit2 = float((x[~h1] > 0).mean()) if n2 else np.nan
                    ys = idx[ev][k].year; by = pd.Series(x).groupby(ys)
                    loyo = min([float((x[ys != y] > 0).mean()) for y in np.unique(ys) if (ys != y).sum() >= 20] or [np.nan])
                    tot = float(x.sum()); conc = float(by.sum().max() / tot) if tot > 0 else np.nan
                    rec.update(n=nn, hit=round(hit, 4), n1=n1, hit1=round(hit1, 4) if n1 else np.nan, n2=n2, hit2=round(hit2, 4) if n2 else np.nan, lb=round(U.wilson_lb(int((x > 0).sum()), nn), 4),
                               mean=round(float(x.mean()) * 100, 3), loyo=round(loyo, 4) if np.isfinite(loyo) else np.nan, conc=round(conc, 3) if np.isfinite(conc) else np.nan,
                               base1=round(base1, 4), base2=round(base2, 4), last=str(idx[ev][k][-1].date()),
                               by_year=json.dumps({int(y): [int(g.size), round(float((g > 0).mean()), 2)] for y, g in by}, ensure_ascii=False))
                    rec['grade_num'] = num_grade(side, nn, hit, n1, hit1 if n1 else 0, n2, hit2 if n2 else 0)
                    # 가짜 신호(통째로 옮김): 가까운 후보만 정밀하게, 전체는 가족 보정용으로
                    ge = 0; near = hit >= CRIT[side]['watch']['hit'] - 0.08 and nn >= 25
                    for bi, s in enumerate(shifts):
                        st2 = stat_sig(np.roll(v, s) & known, rr, t['hold'], fh)
                        if st2 is None: continue
                        k2, x2, g2 = st2; n_ = len(x2); h_ = float((x2 > 0).mean()); ge += h_ >= hit
                        m1 = int(g2.sum()); m2 = n_ - m1
                        gnum = num_grade(side, n_, h_, m1, float((x2[g2] > 0).mean()) if m1 else 0, m2, float((x2[~g2] > 0).mean()) if m2 else 0)
                        if gnum == 'pass': fam['pass'][bi] = True; fam['watch'][bi] = True
                        elif gnum == 'watch': fam['watch'][bi] = True
                    rec['placebo_p'] = round((ge + 1) / (B + 1), 4)
                    c = CRIT[side][rec['grade_num']] if rec['grade_num'] else None
                    rec['rt_ok'] = bool(c and rec['placebo_p'] < RT['p'] and rec['lb'] > base and np.isfinite(loyo) and loyo >= c['hit'] - RT['loyo_margin'] and np.isfinite(conc) and conc < RT['conc'])
                rows.append(rec)
    V = pd.DataFrame(rows); fw = {g: round(float(fam[g].mean()), 4) for g in fam}
    V['grade'] = [('보류(우연 가능)' if (g == 'pass' and fw['pass'] >= FAMILY) or (g == 'watch' and fw['watch'] >= 0.5) else {'pass': '통과', 'watch': '관찰'}[g]) if (g and ok) else ('숫자만 채움(반증 탈락)' if g else '') for g, ok in zip(V['grade_num'], V.get('rt_ok', False).fillna(False))]
    V.sort_values(['lb'], ascending=False).to_csv(os.path.join(U.OUT, 'verdicts.csv'), index=False, encoding='utf-8')

    # ---------------- 2) 자료 묶음별 보탬(표본 밖 AUC·상위 20% 적중)
    ab = []
    for col in PR.columns:
        tn, sn, mn = col.split('|'); p = PR[col].values[ev]; r = T[tn]['r']; ok = np.isfinite(p) & np.isfinite(r)
        if ok.sum() < 300: continue
        y = (r[ok] > 0); pp = p[ok]; rk = rankdata(pp); n1 = y.sum(); n0 = len(y) - n1
        auc = (rk[y].sum() - n1 * (n1 + 1) / 2) / (n1 * n0) if n1 and n0 else np.nan
        top = pp >= np.quantile(pp, 0.8); bot = pp <= np.quantile(pp, 0.2)
        ab.append(dict(target=tn, set=sn, model=mn, auc=round(float(auc), 4), base_up=round(float(y.mean()), 4), top20_up=round(float(y[top].mean()), 4), bot20_down=round(float((~y[bot]).mean()), 4), days=int(ok.sum())))
    AB = pd.DataFrame(ab); AB.to_csv(os.path.join(U.OUT, 'ablation.csv'), index=False, encoding='utf-8')

    # ---------------- 3) 보유·현금 전략
    kc = P['KOSPI']['close'].values.astype(float)[off:off + n]; kr = np.zeros(n); kr[1:] = kc[1:] / kc[:-1] - 1
    bench = None
    if a.bench and os.path.exists(a.bench):
        bd = pd.read_csv(a.bench, parse_dates=['date']).set_index('date'); bench = bd['ens_ret'].reindex(idx).fillna(0.0).values
    seg = {'all': np.ones(W, bool), 'h1': fh, 'h2': ~fh}; ie = idx[ev]
    pf = lambda r_: {s: perf(r_[ev][m], ie[m]) for s, m in seg.items()}
    KP = pf(kr); BP = pf(bench) if bench is not None else None
    srows = []; sfam = np.zeros(B, bool)
    def sgrade(S):
        if BP is not None and all(S[s]['ratio'] > BP[s]['ratio'] for s in seg) and S['all']['mdd'] >= STRAT['pass']['mdd'] and S['all']['total'] > KP['all']['total']: return 'pass'
        if all(S[s]['ratio'] > KP[s]['ratio'] for s in seg) and S['all']['mdd'] >= STRAT['watch']['mdd']: return 'watch'
        return ''
    for col in PR.columns:
        tn, sn, mn = col.split('|')
        if T[tn]['kind'] != 'IDX': continue
        p = PR[col].values
        for qh, ql in PAIRS:
            des = desired_state(p, thr_series(p, idx, qh), thr_series(p, idx, ql)); r_, pos = strat_ret(des, kr); S = pf(r_); g = sgrade(S)
            by = pd.Series(r_[ev]).groupby(ie.year).apply(lambda v_: float(np.prod(1 + v_) - 1)); kb = pd.Series(kr[ev]).groupby(ie.year).apply(lambda v_: float(np.prod(1 + v_) - 1))
            ge = 0
            for bi, s in enumerate(shifts):
                d2 = des.copy(); d2[ev] = np.roll(des[ev], s); r2, _ = strat_ret(d2, kr); S2 = pf(r2); ge += S2['all']['ratio'] >= S['all']['ratio']
                if sgrade(S2) == 'pass': sfam[bi] = True
            pv = round((ge + 1) / (B + 1), 4)
            srows.append(dict(id=f'{col}|hold|{int(qh * 100)}-{int(ql * 100)}', target=tn, set=sn, model=mn, hi=qh, lo=ql, total=S['all']['total'], cagr=S['all']['cagr'], mdd=S['all']['mdd'], ratio=S['all']['ratio'],
                              ratio1=S['h1']['ratio'], ratio2=S['h2']['ratio'], total1=S['h1']['total'], total2=S['h2']['total'], expo=round(float(pos[ev].mean()), 2), trades=int((np.diff(pos[ev]) > 0).sum()),
                              loss_years=int((by < 0).sum()), beat_years=int((by > kb).sum()), years=int(len(by)), placebo_p=pv, grade_num=g,
                              by_year=json.dumps({int(y): round(v_ * 100, 1) for y, v_ in by.items()})))
    SV = pd.DataFrame(srows); sfw = round(float(sfam.mean()), 4)
    SV['grade'] = [('보류(우연 가능)' if g == 'pass' and sfw >= FAMILY else {'pass': '통과', 'watch': '관찰'}[g]) if (g and pv < RT['p']) else ('숫자만 채움(반증 탈락)' if g else '') for g, pv in zip(SV['grade_num'], SV['placebo_p'])]
    SV.sort_values('ratio', ascending=False).to_csv(os.path.join(U.OUT, 'strategies.csv'), index=False, encoding='utf-8')

    # ---------------- 4) 기존 신호를 같은 잣대로(대시보드 최적화 신호, 코스피 20일)
    base_rows = []
    for fn, side in (('buy3.csv', 'buy'), ('sell3.csv', 'sell')):
        fp = os.path.join(U.MAIN, 'out', fn)
        if not os.path.exists(fp): continue
        d = pd.read_csv(fp); d = d[d['start'] == '시작']; t = T['IDX20']; rr = (1.0 if side == 'buy' else -1.0) * t['r']; known = np.isfinite(rr)
        for ty, gdf in d.groupby('type'):
            v = np.isin(ie.strftime('%Y-%m-%d'), gdf['date'].astype(str).values); st = stat_sig(v & known, rr, t['hold'], fh)
            if st is None: continue
            k, x, h1 = st; n1 = int(h1.sum()); n2 = len(x) - n1
            base_rows.append(dict(name=f"대시보드 {'매수' if side == 'buy' else '매도'} {ty}", side=side, n=int(len(x)), hit=round(float((x > 0).mean()), 4), n1=n1, hit1=round(float((x[h1] > 0).mean()), 4) if n1 else None,
                                  n2=n2, hit2=round(float((x[~h1] > 0).mean()), 4) if n2 else None, base=round(float((rr[known] > 0).mean()), 4), mean=round(float(x.mean()) * 100, 2),
                                  note='2015~2024 자료로 고른 신호라 그 기간 성적은 부풀어 있음'))
    BASE = dict(signals=base_rows, kospi=KP, bundle=BP, bundle_note='묶음 규칙의 창·개수는 2026-11-15에 결과를 보고 정함' if BP else '기준선 파일 없음')
    json.dump(BASE, open(os.path.join(U.OUT, 'baseline.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

    # ---------------- 5) 등록(등록일 고정)·오늘 상태·전진 기록
    rp = os.path.join(U.STATE, 'registry.json'); REG = json.load(open(rp, encoding='utf-8')) if os.path.exists(rp) else {}
    new = []
    cur = {r_['id']: ('pass' if r_['grade'] == '통과' else 'watch') for _, r_ in pd.concat([V[['id', 'grade']], SV[['id', 'grade']]]).iterrows() if r_['grade'] in ('통과', '관찰')}
    for cid, g in cur.items():
        if cid not in REG: REG[cid] = dict(grade=g, since=today, first_grade=g, data_end=str(idx[-1].date())); new.append((cid, g))
        elif REG[cid]['grade'] != g:
            if g == 'pass' and REG[cid]['grade'] == 'watch': new.append((cid, g))
            REG[cid]['grade'] = g; REG[cid]['changed'] = today
    for cid in REG: REG[cid]['now'] = cur.get(cid, '기준 미달')
    last = n - 1; now = dict(date=str(idx[last].date()), made=today, signals={}, probs={})
    for cid, info in REG.items():
        if cid in SIG:
            v = SIG[cid]; tn = cid.split('|')[0]; t = T[tn]; since = pd.Timestamp(info.get('data_end', info['since']))
            fwd = [dict(date=str(idx[i].date()), ret=(None if not np.isfinite(t['r'][i - e0]) else round(float(t['r'][i - e0]) * 100 * (1 if '|buy|' in cid else -1), 2))) for i in np.where(v)[0] if idx[i] > since and i >= e0]
            info['forward'] = fwd; now['signals'][cid] = bool(v[last])
    for col in PR.columns:
        if col.endswith('|all|ens'): now['probs'][col] = None if not np.isfinite(PR[col].values[last]) else round(float(PR[col].values[last]), 3)
    json.dump(REG, open(rp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    json.dump(now, open(os.path.join(U.OUT, 'now.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

    cnt = lambda df, g: int((df['grade'] == g).sum())
    status = dict(made=pd.Timestamp.now(tz='Asia/Seoul').strftime('%Y-%m-%d %H:%M'), data_end=str(idx[-1].date()), eval=[str(ie[0].date()), str(ie[-1].date())], candidates=int(len(V)), strategies=int(len(SV)),
                  signal_pass=cnt(V, '통과'), signal_watch=cnt(V, '관찰'), signal_held=cnt(V, '보류(우연 가능)'), signal_num_only=cnt(V, '숫자만 채움(반증 탈락)'),
                  strat_pass=cnt(SV, '통과'), strat_watch=cnt(SV, '관찰'), strat_held=cnt(SV, '보류(우연 가능)'), family_chance=dict(signal_pass=fw['pass'], signal_watch=fw['watch'], strat_pass=sfw),
                  registered=len(REG), new=[list(x) for x in new], placebo_draws=B, seconds=round(time.time() - t0))
    json.dump(status, open(os.path.join(U.STATE, 'status.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

    # ---------------- 6) 보고서
    pc = lambda v_: '—' if v_ is None or (isinstance(v_, float) and not np.isfinite(v_)) else f'{v_ * 100:.1f}%'
    sgn = lambda v_: ('+' if v_ > 0 else '−' if v_ < 0 else '') + f'{abs(v_):,.1f}%'
    nm = lambda r_: f"{r_['target']} · {U.SET_NAME[r_['set']]} · {U.MODEL_NAME[r_['model']]}"
    M = ['# 통합 예측 연구소(갈래 U) 결과', '', f"- 만든 때 {status['made']} KST · 자료 끝 {status['data_end']} · 평가 {status['eval'][0]} ~ {status['eval'][1]} (표본 밖 예측만)",
         f"- 신호 후보 {len(V)}개: 통과 {status['signal_pass']} · 관찰 {status['signal_watch']} · 보류 {status['signal_held']} · 숫자만 채우고 반증 탈락 {status['signal_num_only']}",
         f"- 전략 후보 {len(SV)}개: 통과 {status['strat_pass']} · 관찰 {status['strat_watch']} · 보류 {status['strat_held']}",
         f"- 우연만으로 통과 숫자를 채우는 후보가 하나라도 나올 비율: 신호 통과 {pc(fw['pass'])} · 신호 관찰 {pc(fw['watch'])} · 전략 통과 {pc(sfw)} (가짜 신호 {B}번)", '',
         '기준은 `deriv/uni/CRITERIA.md`. 모두 과거 자료 성적이다.', '', '## 신호: 등급을 받은 후보와 가장 가까운 후보', '',
         '| 등급 | 쪽 | 대상 · 자료 · 모형 | 문턱 | 독립 신호 | 적중 | 앞 | 뒤 | 바탕 | 가짜 신호 p | 거래당 |', '|---|---|---|---|---|---|---|---|---|---|---|']
    for side in ('buy', 'sell'):
        vs = V[(V['side'] == side) & (V['n'] >= 30)].copy(); vs['rk'] = vs['grade'].map({'통과': 0, '관찰': 1, '보류(우연 가능)': 2, '숫자만 채움(반증 탈락)': 3}).fillna(4)
        for _, r_ in vs.sort_values(['rk', 'lb'], ascending=[True, False]).head(8).iterrows():
            M.append(f"| {r_['grade'] or '미달'} | {'매수' if side == 'buy' else '매도'} | {nm(r_)} | {'상' if side == 'buy' else '하'}위 {int(round((1 - r_['q']) * 100))}% | {int(r_['n'])} | {pc(r_['hit'])} | {int(r_['n1'])}건 {pc(r_['hit1'])} | {int(r_['n2'])}건 {pc(r_['hit2'])} | {pc(r_['base'])} | {r_.get('placebo_p', float('nan'))} | {sgn(r_['mean']) if np.isfinite(r_['mean']) else '—'} |")
    M += ['', '## 기존 신호를 같은 잣대로 잰 값(코스피 20거래일)', '', '| 신호 | 독립 신호 | 적중 | 앞 | 뒤 | 바탕 |', '|---|---|---|---|---|---|']
    for b in base_rows: M.append(f"| {b['name']} | {b['n']} | {pc(b['hit'])} | {b['n1']}건 {pc(b['hit1'])} | {b['n2']}건 {pc(b['hit2'])} | {pc(b['base'])} |")
    M += ['', '기존 최적화 신호는 2015~2024년 자료로 고른 것이라 그 기간(앞 구간 전부와 뒤 구간 일부) 성적이 부풀어 있다.', '',
          '## 자료를 더하면 예측이 나아지나(둘 평균 모형, 표본 밖)', '', '맞히는 힘(AUC)은 0.5면 동전 던지기, 높을수록 좋다.', '', '| 대상 | ' + ' | '.join(U.SET_NAME[s] for s in U.SETS) + ' |', '|---|' + '---|' * len(U.SETS)]
    for tn, _, _ in U.TARGETS:
        g = AB[(AB['target'] == tn) & (AB['model'] == 'ens')].set_index('set')
        if len(g): M.append(f'| {tn} | ' + ' | '.join((f"{g.loc[s, 'auc']:.3f} (상위20% {pc(g.loc[s, 'top20_up'])} · 하위20% 하락 {pc(g.loc[s, 'bot20_down'])})" if s in g.index else '—') for s in U.SETS) + ' |')
    M += ['', '## 보유·현금 전략(코스피, 다음 날 종가 체결, 왕복 0.3%)', '', '| 등급 | 대상 · 자료 · 모형 | 문턱(들어감-나옴) | 누적 | 연 환산 | 최대 낙폭 | 수익÷낙폭 | 앞 | 뒤 | 손실 난 해 | 가짜 신호 p |', '|---|---|---|---|---|---|---|---|---|---|---|']
    M.append(f"| 기준 | 코스피 그냥 보유 | — | {sgn(KP['all']['total'])} | {sgn(KP['all']['cagr'])} | {sgn(KP['all']['mdd'])} | {KP['all']['ratio']} | {KP['h1']['ratio']} | {KP['h2']['ratio']} | — | — |")
    if BP: M.append(f"| 기준 | 대시보드 묶음 규칙 | — | {sgn(BP['all']['total'])} | {sgn(BP['all']['cagr'])} | {sgn(BP['all']['mdd'])} | {BP['all']['ratio']} | {BP['h1']['ratio']} | {BP['h2']['ratio']} | — | — |")
    sv = SV.copy(); sv['rk'] = sv['grade'].map({'통과': 0, '관찰': 1, '보류(우연 가능)': 2}).fillna(3)
    for _, r_ in sv.sort_values(['rk', 'ratio'], ascending=[True, False]).head(10).iterrows():
        M.append(f"| {r_['grade'] or '미달'} | {nm(r_)} | 상위 {int(round((1 - r_['hi']) * 100))}% - 하위 {int(round(r_['lo'] * 100))}% | {sgn(r_['total'])} | {sgn(r_['cagr'])} | {sgn(r_['mdd'])} | {r_['ratio']} | {r_['ratio1']} | {r_['ratio2']} | {r_['loss_years']}/{r_['years']} | {r_['placebo_p']} |")
    M += ['', '## 등록된 후보(등록일 뒤 실제 신호만 따로 적음)', '']
    if REG:
        M += ['| 후보 | 등급 | 등록일 | 지금 기준 | 등록 뒤 신호 | 오늘 |', '|---|---|---|---|---|---|']
        for cid, info in REG.items():
            fw_ = info.get('forward', []); done = [x for x in fw_ if x['ret'] is not None]
            M.append(f"| {cid} | {'통과' if info['grade'] == 'pass' else '관찰'} | {info['since']} | {info['now'] if info['now'] not in ('pass', 'watch') else ('통과' if info['now'] == 'pass' else '관찰')} | {len(fw_)}건(끝난 것 {len(done)}건 중 {sum(x['ret'] > 0 for x in done)}건 맞음) | {'켜짐' if now['signals'].get(cid) else '꺼짐' if cid in now['signals'] else '—'} |")
    else: M.append('아직 없음.')
    M += ['', f"## 오늘({now['date']} 장 마감 기준) 오를 확률 — 전부 넣은 둘 평균 모형", '', '| 대상 | 오를 확률 |', '|---|---|'] + [f"| {k.split('|')[0]} | {('—' if v_ is None else f'{v_ * 100:.0f}%')} |" for k, v_ in now['probs'].items()]
    M += ['', '## 넣지 못한 자료', ''] + [f'- {k}: {v_}' for k, v_ in D['meta'].get('missing', {}).items()] + ['', '투자 권유 아님']
    open(os.path.join(U.OUT, 'report.md'), 'w', encoding='utf-8').write('\n'.join(M) + '\n')

    # ---------------- 7) 카카오톡(새 통과·관찰이 있을 때만)
    flag = os.path.join(U.NOTIFY, 'send.flag')
    if os.path.exists(flag): os.remove(flag)
    if new:
        lab = lambda cid: (lambda p_: f"{p_[0]} {'매수' if p_[3] == 'buy' else '매도' if p_[3] == 'sell' else '보유·현금 전략'}({U.SET_NAME[p_[1]]})")(cid.split('|'))
        np_ = [c for c, g in new if g == 'pass']; nw = [c for c, g in new if g == 'watch']
        msg = [f"[통합 예측 연구소] 전보다 나은 결과 {today}\n새 통과 {len(np_)}개 · 새 관찰 {len(nw)}개\n(누적 등록 {len(REG)}개, 자료 끝 {status['data_end']})"]
        for c, g in (new[:4]):
            row = V[V['id'] == c]; 
            if len(row): r_ = row.iloc[0]; msg.append(f"{'통과' if g == 'pass' else '관찰'}: {lab(c)}\n독립 신호 {int(r_['n'])}건 적중 {pc(r_['hit'])} (앞 {pc(r_['hit1'])} · 뒤 {pc(r_['hit2'])}, 바탕 {pc(r_['base'])})\n가짜 신호 p {r_['placebo_p']}")
            else:
                r_ = SV[SV['id'] == c].iloc[0]; msg.append(f"{'통과' if g == 'pass' else '관찰'}: {lab(c)}\n누적 {sgn(r_['total'])} · 낙폭 {sgn(r_['mdd'])} · 수익÷낙폭 {r_['ratio']}\n(코스피 {KP['all']['ratio']}" + (f" · 묶음 규칙 {BP['all']['ratio']})" if BP else ')'))
        msg.append('과거 자료 성적입니다. 등록일 뒤 실제 신호는 따로 기록합니다. 투자 권유 아님')
        open(os.path.join(U.NOTIFY, 'kakao.txt'), 'w', encoding='utf-8').write('\n=====\n'.join(m[:200] for m in msg) + '\n'); open(flag, 'w').write(today)
    print(json.dumps(status, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
