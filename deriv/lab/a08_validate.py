"""A8 검증 에이전트 — 모든 후보를 같은 잣대로 판정. 잠금 구간(2024~)을 열 수 있는 유일한 에이전트.

1) 개발 구간(~2023) 성적: 후보의 trades_dev(해마다 따로 고른 신호, A6·A7) 또는 trades 중 개발 구간 부분(A3~A5, 문턱이 개발 구간에서 정해진 규칙).
   겹치는 거래는 버림(앞 거래 청산 뒤 신호만) → 독립 거래 수 n, 적중(방향 × 수익 > 0), 윌슨 90% 하한, 같은 보유 기간 무작위 적중률(기본).
   통과: n ≥ 20, 적중 ≥ 75%, 하한 ≥ 60%, 기본 ≤ 60%(누구나 맞히는 방향 제외), 거래 있는 해의 과반에서 적중 ≥ 70%.
2) 개발 통과 후보만 잠금 구간을 연다(원장에 열람 횟수 누적). 통과: n ≥ 12, 적중 ≥ 80%, 기본 대비 단측 이항 p < 0.05 ÷ (누적 열람 횟수).
대상 가격: 코스피200 선물(연속, 주 판정) + 코스피200 지수(참고).

교차 검증 방식(cv_mode='cross', 사용자 지시 2026-11-20 — 오늘까지 위 잠금 규칙, 2026-11-21 KST 부터 자동 전환):
  잠금 규칙 없이 양방향으로 본다. 앞 구간 P1(2010~2023)·뒤 구간 P2(2024~) 성적을 모두 계산하고
  · 앞→뒤: P1 에서 위 '개발' 기준 통과(선별) → P2 에서 확인(독립 거래 ≥ 12, 적중 ≥ 80%, 기본 대비 p < 0.05 ÷ 이 라운드 앞→뒤 선별 수)
  · 뒤→앞: P2 에서 선별(독립 거래 ≥ 12, 적중 ≥ 75%, 하한 ≥ 60%, 기본 ≤ 60%, 해마다 과반) → P1 에서 같은 확인(÷ 뒤→앞 선별 수)
  · 목표 판정(hold_pass) = 두 방향 모두 통과. 한 방향만 통과는 따로 보고. 잠금 열람 횟수는 더 쌓지 않고 cross_tests 를 센다.
  round.json 의 a08.cv_mode 에 'holdout'·'cross' 를 적으면 날짜와 상관없이 그 방식을 쓴다.
"""
import os
import pickle
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lab_common as L  # noqa: E402

cfg = L.round_cfg().get('a08', {})
DEV = dict(n=cfg.get('dev_n', 20), hit=cfg.get('dev_hit', 0.75), lb=cfg.get('dev_lb', 0.60), base_max=cfg.get('base_max', 0.60), year_hit=0.70)
HOLD = dict(n=cfg.get('hold_n', 12), hit=cfg.get('hold_hit', 0.80), alpha=0.05)
REV = dict(n=cfg.get('rev_n', 12), hit=cfg.get('dev_hit', 0.75), lb=cfg.get('dev_lb', 0.60), base_max=cfg.get('base_max', 0.60), year_hit=0.70)
CONF = dict(n=cfg.get('conf_n', 12), hit=cfg.get('conf_hit', 0.80), alpha=0.05)
CROSS_FROM = pd.Timestamp('2026-11-21')   # 사용자 지시(2026-11-20): 오늘까지 잠금 규칙, 내일부터 잠금 규칙 없이 양방향 교차 검증


def cv_mode():
    m = cfg.get('cv_mode')
    if m in ('holdout', 'cross'): return m
    return 'cross' if pd.Timestamp.now(tz='Asia/Seoul').tz_localize(None).normalize() >= CROSS_FROM else 'holdout'


def honest_trades(c):
    """앞 구간은 해마다 따로 고른 신호(trades_dev, 없으면 trades), 뒤 구간은 trades — 두 구간 모두 그 시점에 알 수 있던 규칙의 거래."""
    tr = c['trades']; trd = c.get('trades_dev', tr)
    tr = tr.assign(signal=pd.to_datetime(tr['signal']), exit=pd.to_datetime(tr['exit']))
    trd = trd.assign(signal=pd.to_datetime(trd['signal']), exit=pd.to_datetime(trd['exit']))
    return trd, tr, pd.concat([trd[trd['exit'] <= L.DEV_END], tr[tr['signal'] >= L.HOLD_START]], ignore_index=True)


def independent(trades):
    t = trades.sort_values('signal'); keep = []; last_exit = pd.Timestamp('1900-01-01')
    for s, e in zip(t['signal'], t['exit']):
        if s >= last_exit: keep.append((s, e)); last_exit = e
    return pd.DataFrame(keep, columns=['signal', 'exit'])


def base_rate(px, hold_days, direction, start, end):
    """같은 보유 기간을 아무 날에나 잡았을 때 그 방향이 맞을 확률."""
    h = int(max(1, np.median(hold_days)))
    r = (px['close'].shift(-h) / px['open'].shift(-1) - 1)
    r = r[(r.index >= start) & (r.index <= end)].dropna()
    return float((direction * r > 0).mean()) if len(r) else np.nan


def evaluate(trades, px, direction, start, end):
    t = trades[(trades['signal'] >= start) & (trades['exit'] <= end)].dropna()
    t = independent(t)
    if not len(t): return {'n': 0}
    ret = L.trade_returns(t, px); ok = ~np.isnan(ret)
    t = t[ok]; ret = ret[ok]
    hit = direction * ret > 0
    n = len(ret); k = int(hit.sum())
    td = px.index
    hold = [((td > s) & (td <= e)).sum() for s, e in zip(t['signal'], t['exit'])]
    b = base_rate(px, hold, direction, start, end)
    lb, ub = L.wilson(k, n)
    yrs = pd.Series(hit, index=pd.DatetimeIndex(t['signal']).year)
    gy = yrs.groupby(level=0).agg(['size', 'mean'])
    ok_years = int(((gy['size'] >= 2) & (gy['mean'] >= DEV['year_hit'])).sum()); yrs_with = int((gy['size'] >= 2).sum())
    return {'n': n, 'hit': k / n if n else np.nan, 'lb': lb, 'base': b, 'mean_ret%': float(np.mean(direction * ret)), 'hold_med': float(np.median(hold)),
            'years_ok': ok_years, 'years_with': yrs_with, 'p_vs_base': L.binom_p(k, n, b if np.isfinite(b) else 0.5),
            'by_year': {int(y): [int(r['size']), round(float(r['mean']), 3)] for y, r in gy.iterrows()}}


def selected(d, need):
    return bool(d.get('n', 0) >= need['n'] and (d.get('hit') or 0) >= need['hit'] and (d.get('lb') or 0) >= need['lb']
                and (d.get('base') or 1) <= need['base_max'] and d.get('years_with', 0) > 0 and d['years_ok'] * 2 > d['years_with'])


def main_cross(cands, fut, idx, led):
    """잠금 규칙 없는 양방향 교차 검증(2026-11-21~)."""
    P1 = (pd.Timestamp('2010-01-01'), L.DEV_END); P2 = (L.HOLD_START, fut.index[-1])
    rows, sel = [], []
    for c in cands:
        trd, tr, both = honest_trades(c)
        d1 = evaluate(trd, fut, c['direction'], *P1); d2 = evaluate(tr, fut, c['direction'], *P2)
        da = evaluate(both, fut, c['direction'], P1[0], P2[1]); di = evaluate(trd, idx, c['direction'], *P1)
        rec = {'id': c['id'], 'agent': c['agent'], 'family': c.get('family'), 'desc': c['desc'], 'direction': c['direction'], 'cv_mode': 'cross',
               'dev_n': d1.get('n', 0), 'dev_hit': d1.get('hit'), 'dev_lb': d1.get('lb'), 'dev_base': d1.get('base'), 'dev_mean%': d1.get('mean_ret%'),
               'dev_years_ok': d1.get('years_ok'), 'dev_years_with': d1.get('years_with'), 'dev_hit_index': di.get('hit'), 'dev_by_year': d1.get('by_year'),
               'p2_n': d2.get('n', 0), 'p2_hit': d2.get('hit'), 'p2_lb': d2.get('lb'), 'p2_base': d2.get('base'), 'p2_p': d2.get('p_vs_base'),
               'p2_years_ok': d2.get('years_ok'), 'p2_years_with': d2.get('years_with'), 'p2_by_year': d2.get('by_year'),
               'all_n': da.get('n', 0), 'all_hit': da.get('hit'), 'all_lb': da.get('lb'), 'all_base': da.get('base'), 'all_by_year': da.get('by_year')}
        rec['sel_fwd'] = selected(d1, DEV); rec['sel_rev'] = selected(d2, REV)
        if c.get('fit_period') == 'p2': rec['sel_fwd'] = False   # 뒤 구간에서 정한 후보는 뒤→앞 방향만(앞→뒤는 표본 안 확인이라 뺌, 2026-11-20 갈래 B)
        rec['fit_period'] = c.get('fit_period', 'p1')
        rec['dev_pass'] = bool(rec['sel_fwd'] or rec['sel_rev'])
        rec['fwd_pass'] = rec['rev_pass'] = rec['hold_pass'] = False
        rows.append(rec)
        if rec['dev_pass']: sel.append((c, rec, d1, d2))
    m_f = max(1, sum(r['sel_fwd'] for _, r, _, _ in sel)); m_r = max(1, sum(r['sel_rev'] for _, r, _, _ in sel))
    conf = lambda d, m: bool(d.get('n', 0) >= CONF['n'] and (d.get('hit') or 0) >= CONF['hit'] and (d.get('p_vs_base') or 1) < CONF['alpha'] / m)
    for c, rec, d1, d2 in sel:
        rec['fwd_pass'] = bool(rec['sel_fwd'] and conf(d2, m_f)); rec['rev_pass'] = bool(rec['sel_rev'] and conf(d1, m_r))
        rec['hold_pass'] = bool(rec['fwd_pass'] and rec['rev_pass'])   # 목표 판정 = 두 방향 모두 통과
        rec.update({'hold_n': d2.get('n', 0), 'hold_hit': d2.get('hit'), 'hold_lb': d2.get('lb'), 'hold_base': d2.get('base'), 'hold_p': d2.get('p_vs_base'),
                    'hold_by_year': d2.get('by_year'), 'dev_p': d1.get('p_vs_base'), 'conf_div_fwd': m_f, 'conf_div_rev': m_r})
    led['trials_total'] = led.get('trials_total', 0) + len(cands)
    led['cross_tests'] = led.get('cross_tests', 0) + sum(r['sel_fwd'] for _, r, _, _ in sel) + sum(r['sel_rev'] for _, r, _, _ in sel)
    R = pd.DataFrame(rows).sort_values(['hold_pass', 'dev_pass', 'dev_hit'], ascending=[False, False, False])
    od = L.out_dir('a08'); R.to_csv(os.path.join(od, 'verdicts.csv'), index=False, encoding='utf-8')
    pickle.dump([c for c, _, _, _ in sel], open(os.path.join(od, 'dev_passed.pkl'), 'wb'))
    led['rounds'].append({'round': L.round_cfg()['round'], 'mode': 'cross', 'candidates': len(cands), 'sel_fwd': int(R['sel_fwd'].sum()), 'sel_rev': int(R['sel_rev'].sum()),
                          'fwd_pass': int(R['fwd_pass'].sum()), 'rev_pass': int(R['rev_pass'].sum()), 'hold_pass': int(R['hold_pass'].sum())})
    L.save_ledger(led)
    print('교차 검증: 후보', len(cands), '앞 선별', int(R['sel_fwd'].sum()), '뒤 선별', int(R['sel_rev'].sum()), '앞→뒤', int(R['fwd_pass'].sum()), '뒤→앞', int(R['rev_pass'].sum()), '양방향', int(R['hold_pass'].sum()))


def main():
    P = L.prices(); fut, idx = P['K200F'], P['K200']
    rd = L.out_dir()
    cands = []
    for a in sorted(os.listdir(rd)):
        p = os.path.join(rd, a, 'candidates.pkl')
        if os.path.exists(p): cands += pickle.load(open(p, 'rb'))
    led = L.ledger()
    if cv_mode() == 'cross': return main_cross(cands, fut, idx, led)
    rows, passed_dev = [], []
    end_all = fut.index[-1]
    for c in cands:
        tr = c['trades']; trd = c.get('trades_dev', tr)
        tr = tr.assign(signal=pd.to_datetime(tr['signal']), exit=pd.to_datetime(tr['exit']))
        trd = trd.assign(signal=pd.to_datetime(trd['signal']), exit=pd.to_datetime(trd['exit']))
        d = evaluate(trd, fut, c['direction'], pd.Timestamp('2010-01-01'), L.DEV_END)
        di = evaluate(trd, idx, c['direction'], pd.Timestamp('2010-01-01'), L.DEV_END)
        rec = {'id': c['id'], 'agent': c['agent'], 'family': c.get('family'), 'desc': c['desc'], 'direction': c['direction'],
               'dev_n': d.get('n', 0), 'dev_hit': d.get('hit'), 'dev_lb': d.get('lb'), 'dev_base': d.get('base'), 'dev_mean%': d.get('mean_ret%'),
               'dev_years_ok': d.get('years_ok'), 'dev_years_with': d.get('years_with'), 'dev_hit_index': di.get('hit'), 'dev_by_year': d.get('by_year')}
        ok = (d.get('n', 0) >= DEV['n'] and (d.get('hit') or 0) >= DEV['hit'] and (d.get('lb') or 0) >= DEV['lb']
              and (d.get('base') or 1) <= DEV['base_max'] and d.get('years_with', 0) > 0 and d['years_ok'] * 2 > d['years_with'])
        rec['dev_pass'] = bool(ok)
        if ok: passed_dev.append((c, rec, tr))
        rows.append(rec)
    led['trials_total'] = led.get('trials_total', 0) + len(cands)
    led['holdout_peeks'] = led.get('holdout_peeks', 0) + len(passed_dev)
    peeks = max(1, led['holdout_peeks'])
    for c, rec, tr in passed_dev:
        hdd = evaluate(tr, fut, c['direction'], L.HOLD_START, end_all)
        rec.update({'hold_n': hdd.get('n', 0), 'hold_hit': hdd.get('hit'), 'hold_lb': hdd.get('lb'), 'hold_base': hdd.get('base'),
                    'hold_p': hdd.get('p_vs_base'), 'hold_mean%': hdd.get('mean_ret%'), 'hold_by_year': hdd.get('by_year'), 'peeks_total': peeks})
        rec['hold_pass'] = bool(hdd.get('n', 0) >= HOLD['n'] and (hdd.get('hit') or 0) >= HOLD['hit'] and (hdd.get('p_vs_base') or 1) < HOLD['alpha'] / peeks)
    R = pd.DataFrame(rows).sort_values(['dev_pass', 'dev_hit'], ascending=[False, False])
    od = L.out_dir('a08'); R.to_csv(os.path.join(od, 'verdicts.csv'), index=False, encoding='utf-8')
    pickle.dump([c for c, _, _ in passed_dev], open(os.path.join(od, 'dev_passed.pkl'), 'wb'))
    led['rounds'].append({'round': L.round_cfg()['round'], 'candidates': len(cands), 'dev_pass': len(passed_dev),
                          'hold_pass': int(R.get('hold_pass', pd.Series(dtype=bool)).fillna(False).sum()) if 'hold_pass' in R else 0})
    L.save_ledger(led)
    print('후보', len(cands), '개발 통과', len(passed_dev), '누적 열람', peeks)


if __name__ == '__main__':
    main()
