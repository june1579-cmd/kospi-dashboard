#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""combine_study.py — 대시보드 '묶음 규칙'과 연구소 통과 신호를 한 계좌에서 같이 썼을 때의 성적 (사용자 요청 2026-11-23).

읽기 전용 계산이다. 신호·기준·대시보드 자료는 건드리지 않고 report/combine_study.md·json 만 쓴다.

입력(모두 --dir 폴더 안)
  combo_daily.csv  — pkg/combo_track.py --daily 가 만든 묶음 규칙의 하루 단위 수익(ens_ret)·보유 비중(ens_expo, 그날 종가 뒤)
  sim_daily.csv    — 연구소 deriv/lab/study/criteria_study.py 가 만든 합치는 방식별 하루 단위 손익(코스피200 선물 1배, 비용 제외)
  sim_trades.csv   — 연구소 '한 번에 하나' 거래 목록

합치는 방식(자금은 매일 다시 맞춘다고 가정)
  반반       : 자금의 절반은 묶음 규칙, 절반은 연구소 신호
  겹쳐 쓰기  : 묶음 규칙은 그대로 100%, 연구소 신호가 나오면 선물 1배를 더 얹음(최대 2배)
  빈자리만   : 묶음 규칙이 현금으로 들고 있는 비중만큼만 연구소 신호에 씀(최대 1배)
"""
import argparse
import json
import os

import numpy as np
import pandas as pd

LAB_COST = 0.001      # 민감도용: 연구소 거래 한 번(왕복)에 0.1% 비용


def stats(r, idx, k=None):
    eq = np.cumprod(1 + r); peak = np.maximum.accumulate(eq); dd = eq / peak - 1
    t = int(dd.argmin()); p = int(eq[:t + 1].argmax()) if t > 0 else 0
    yrs = (idx[-1] - idx[0]).days / 365.25
    pre = idx.year <= 2024
    by = pd.Series(r, index=idx).groupby(idx.year).apply(lambda v: float(np.prod(1 + v) - 1) * 100)
    out = dict(total=round(float(eq[-1] - 1) * 100, 1), cagr=round((float(eq[-1]) ** (1 / yrs) - 1) * 100, 1), mdd=round(float(dd.min()) * 100, 1),
               mdd_from=str(idx[p].date()), mdd_to=str(idx[t].date()),
               to_2024=round(float(np.prod(1 + r[pre]) - 1) * 100, 1), y2025_26=round(float(np.prod(1 + r[~pre]) - 1) * 100, 1),
               worst_year=[int(by.idxmin()), round(float(by.min()), 1)], worst_day=round(float(r.min()) * 100, 2),
               vol=round(float(r.std() * np.sqrt(250)) * 100, 1), by_year={int(y): round(float(v), 1) for y, v in by.items()})
    out['ret_per_dd'] = round(out['cagr'] / abs(out['mdd']), 2) if out['mdd'] else None
    if k is not None:
        kb = pd.Series(k, index=idx).groupby(idx.year).apply(lambda v: float(np.prod(1 + v) - 1) * 100)
        out['beat'] = int((by > kb).sum()); out['years'] = int(len(by)); out['loss_years'] = int((by < 0).sum())
    return out


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--dir', required=True); ap.add_argument('--report', default='report'); a = ap.parse_args()
    D = pd.read_csv(os.path.join(a.dir, 'combo_daily.csv'), parse_dates=['date']).set_index('date')
    L = pd.read_csv(os.path.join(a.dir, 'sim_daily.csv'), parse_dates=['date']).set_index('date')
    T = pd.read_csv(os.path.join(a.dir, 'sim_trades.csv'), parse_dates=['entry', 'exit'])
    end = min(D.index[-1], L.index[-1])
    D = D[D.index <= end]; start = D.index[1]                      # 첫 줄은 기준일(수익 0)
    miss = int((~D.index.isin(L.index)).sum()); extra = L.index[(L.index >= start) & (L.index <= end) & ~L.index.isin(D.index)]
    Lr = L.reindex(D.index).fillna(0.0)
    idx = D.index[1:]; k = D['kospi_ret'].values[1:]; e = D['ens_ret'].values[1:]; xp = D['ens_expo'].values[:-1]   # xp = 그날 장중 묶음 규칙 보유 비중(전날 종가 뒤)
    g = lambda nm: (Lr['pnl_' + nm].values[1:], Lr['expo_' + nm].values[1:]) if 'pnl_' + nm in Lr else (np.zeros(len(idx)), np.zeros(len(idx)))
    l1, x1 = g('core_one_at_a_time'); l2, x2 = g('core_each_full'); l3, x3 = g('core_aux_one_at_a_time')
    # 비용 민감도: 연구소 거래마다 진입·청산일에 반씩
    Tc = T[(T['mode'] == 'core_one_at_a_time') & (T['entry'] >= start) & (T['exit'] <= end)].copy()
    cost = pd.Series(0.0, index=idx)
    for d in list(Tc['entry']) + list(Tc['exit']):
        if d in cost.index: cost[d] += LAB_COST / 2
    l1c = l1 - cost.values

    modes = [
        ('kospi', '코스피 그냥 보유', k, np.ones(len(idx))),
        ('ens', '묶음 규칙만', e, xp),
        ('lab', '연구소 신호만(한 번에 하나)', l1, x1),
        ('half', '반반(자금 절반씩)', 0.5 * e + 0.5 * l1, 0.5 * xp + 0.5 * x1),
        ('fill', '빈자리만(묶음 규칙의 현금 비중만큼)', e + (1 - xp) * l1, xp + (1 - xp) * x1),
        ('overlay', '겹쳐 쓰기(묶음 100% + 연구소 선물 1배)', e + l1, xp + x1),
        ('overlay_cost', '겹쳐 쓰기 · 연구소 거래마다 비용 0.1%', e + l1c, xp + x1),
        ('overlay_aux', '겹쳐 쓰기 + 하락 관찰 신호', e + l3, xp + x3),
        ('overlay_full', '겹쳐 쓰기 · 연구소 둘 다 전액(겹친 날 2배)', e + l2, xp + x2),
    ]
    R = dict(made=pd.Timestamp.now(tz='Asia/Seoul').strftime('%Y-%m-%d %H:%M'), start=str(idx[0].date()), end=str(idx[-1].date()), days=int(len(idx)),
             dash_days_missing_in_lab=miss, lab_days_missing_in_dash=[str(d.date()) for d in extra][:10], lab_cost=LAB_COST, modes=[])
    for key, label, r, ex in modes:
        s = stats(r, idx, k); s.update(key=key, label=label, max_expo=round(float(ex.max()), 2), avg_expo=round(float(ex.mean()), 2)); R['modes'].append(s)

    # 두 쪽이 얼마나 따로 노는가
    act = x1 > 0
    R['relation'] = dict(corr_all=round(float(np.corrcoef(e, l1)[0, 1]), 3), corr_lab_days=round(float(np.corrcoef(e[act], l1[act])[0, 1]), 3) if act.sum() > 5 else None,
                         lab_days=int(act.sum()), lab_days_ens_cash=int((act & (xp == 0)).sum()), lab_days_ens_part=int((act & (xp > 0) & (xp < 1)).sum()),
                         lab_days_ens_full=int((act & (xp >= 1)).sum()), ens_expo_on_lab_days=round(float(xp[act].mean()), 2) if act.any() else None,
                         ens_expo_all=round(float(xp.mean()), 2), both_loss_days=int(((e < 0) & (l1 < 0)).sum()),
                         worst_both_day=round(float((e + l1)[act].min()) * 100, 2) if act.any() else None)
    # 연구소 거래를 진입일의 묶음 규칙 상태로 나눠 보기
    xs = pd.Series(xp, index=idx); rows = {}
    Tc['ens'] = [float(xs.get(d, np.nan)) for d in Tc['entry']]
    for nm, m in (('묶음 규칙이 절반 이상 보유 중', Tc['ens'] >= 0.5), ('묶음 규칙이 절반 미만 보유', (Tc['ens'] < 0.5) & (Tc['ens'] > 0)), ('묶음 규칙이 전부 현금', Tc['ens'] == 0)):
        t = Tc[m]
        rows[nm] = dict(n=int(len(t)), hit=round(float((t['ret'] > 0).mean()) * 100, 1) if len(t) else None, mean=round(float(t['ret'].mean()), 2) if len(t) else None, total=round(float(t['ret'].sum()), 1))
    R['lab_by_ens_state'] = rows; R['lab_trades'] = int(len(Tc)); R['lab_hit'] = round(float((Tc['ret'] > 0).mean()) * 100, 1) if len(Tc) else None
    # 묶음 규칙이 가장 크게 빠진 구간에 연구소 신호는 무엇을 했나
    se = next(m for m in R['modes'] if m['key'] == 'ens'); w = (idx >= pd.Timestamp(se['mdd_from'])) & (idx <= pd.Timestamp(se['mdd_to']))
    R['ens_worst'] = {'from': se['mdd_from'], 'to': se['mdd_to'], 'ens': se['mdd'], 'lab_in_window': round(float(np.prod(1 + l1[w][1:]) - 1) * 100, 1) if w.sum() > 1 else 0.0,
                      'lab_days': int((x1[w] > 0).sum()), 'overlay': round(float(np.prod(1 + (e + l1)[w][1:]) - 1) * 100, 1) if w.sum() > 1 else 0.0}

    os.makedirs(a.report, exist_ok=True)
    json.dump(R, open(os.path.join(a.report, 'combine_study.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    f = lambda v: ('+' if v > 0 else '−' if v < 0 else '') + f'{abs(v):,.1f}%'
    M = [f"# 묶음 규칙 + 연구소 신호를 같이 썼을 때", '', f"- 기간: {R['start']} ~ {R['end']} ({R['days']:,}거래일) · 만든 때 {R['made']} KST",
         '- 묶음 규칙: 코스피를 사고파는 것으로 계산(왕복 비용 0.3% 포함). 연구소 신호: 코스피200 선물 1배, 다음 날 시가 진입(비용 제외).',
         '- 모두 과거 자료 성적이다. 묶음 규칙의 창·개수(750일·5개)는 2026-11-15에, 연구소 통과 신호는 2026-11에 결과를 보고 정했다.', '',
         '| 방식 | 누적 | 연 환산 | 최대 낙폭 | 2016~2024 | 2025~26 | 가장 나쁜 해 | 손실 난 해 | 최대 노출 |', '|---|---|---|---|---|---|---|---|---|']
    for m in R['modes']:
        M.append(f"| {m['label']} | {f(m['total'])} | {f(m['cagr'])} | {f(m['mdd'])} | {f(m['to_2024'])} | {f(m['y2025_26'])} | {m['worst_year'][0]}년 {f(m['worst_year'][1])} | {m['loss_years']}/{m['years']} | {m['max_expo']}배 |")
    ys = sorted(R['modes'][0]['by_year']); keys = ['kospi', 'ens', 'lab', 'half', 'fill', 'overlay']; mm = {m['key']: m for m in R['modes']}
    M += ['', '## 해마다', '', '| 해 | ' + ' | '.join(mm[q]['label'].split('(')[0] for q in keys) + ' |', '|---|' + '---|' * len(keys)]
    for y in ys: M.append(f'| {y} | ' + ' | '.join(f(mm[q]['by_year'].get(y, 0.0)) for q in keys) + ' |')
    rl = R['relation']
    M += ['', '## 두 쪽은 얼마나 따로 움직이나', '', f"- 하루 수익 상관: 전체 {rl['corr_all']}, 연구소 신호가 켜진 날만 {rl['corr_lab_days']}",
          f"- 연구소 신호가 켜진 {rl['lab_days']}일 가운데 묶음 규칙이 전부 현금 {rl['lab_days_ens_cash']}일 · 일부 보유 {rl['lab_days_ens_part']}일 · 전부 보유 {rl['lab_days_ens_full']}일 (그날 평균 보유 비중 {rl['ens_expo_on_lab_days']}, 전체 평균 {rl['ens_expo_all']})",
          f"- 둘 다 손실인 날 {rl['both_loss_days']}일, 겹쳐 썼을 때 연구소 신호일의 가장 나쁜 하루 {f(rl['worst_both_day'])}", '',
          '## 연구소 거래를 진입일의 묶음 규칙 상태로 나누면', '', '| 진입일 상태 | 거래 | 적중 | 거래당 평균 |', '|---|---|---|---|']
    for nm, v in R['lab_by_ens_state'].items():
        M.append(f"| {nm} | {v['n']} | {v['hit']}% | {f(v['mean'])} |" if v['n'] else f'| {nm} | 0 | — | — |')
    ew = R['ens_worst']
    M += ['', '## 묶음 규칙이 가장 크게 빠진 구간', '', f"- {ew['from']} ~ {ew['to']}: 묶음 규칙 {f(ew['ens'])}, 같은 구간 연구소 신호 {f(ew['lab_in_window'])}({ew['lab_days']}일 보유), 겹쳐 쓰면 {f(ew['overlay'])}"]
    open(os.path.join(a.report, 'combine_study.md'), 'w', encoding='utf-8').write('\n'.join(M) + '\n')
    print('\n'.join(M))


if __name__ == '__main__':
    main()
