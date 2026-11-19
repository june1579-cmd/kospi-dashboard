"""라운드 정리 — A2~A10 결과를 모아 순위표·라운드 보고(한국어)·상태 파일을 만든다(오케스트레이터와 사용자가 읽음)."""
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lab_common as L  # noqa: E402


def f(x, d=1, pct=False):
    if x is None or (isinstance(x, float) and not np.isfinite(x)): return '—'
    return f'{x * 100:.{d}f}%' if pct else f'{x:.{d}f}'


def main():
    cfg = L.round_cfg(); rnd = cfg['round']
    rd = L.out_dir()
    V = pd.read_csv(os.path.join(rd, 'a08', 'verdicts.csv'))
    T = pd.read_csv(os.path.join(rd, 'a09', 'trades.csv')) if os.path.exists(os.path.join(rd, 'a09', 'trades.csv')) else pd.DataFrame()
    R = pd.read_csv(os.path.join(rd, 'a10', 'redteam.csv')) if os.path.exists(os.path.join(rd, 'a10', 'redteam.csv')) else pd.DataFrame()
    led = L.ledger()
    top = V[V['dev_n'] >= 10].sort_values(['dev_pass', 'dev_lb'], ascending=[False, False]).head(15)
    if len(R): top = top.merge(R[['id', '위약p', '한해빼기_최저', '버팀']], on='id', how='left')
    top.to_csv(os.path.join(rd, 'leaderboard.csv'), index=False, encoding='utf-8')
    passed = V[V.get('hold_pass', pd.Series(False, index=V.index)).fillna(False).astype(bool)] if 'hold_pass' in V else V.iloc[0:0]
    if len(passed) and len(R):
        passed = passed.merge(R[['id', '버팀']], on='id', how='left')
        final = passed[passed['버팀'] == True]
    else:
        final = passed.iloc[0:0]
    st = {'round': rnd, 'candidates': int(len(V)), 'dev_pass': int(V['dev_pass'].sum()), 'hold_pass': int(len(passed)), 'final_pass': int(len(final)),
          'trials_total': led.get('trials_total'), 'holdout_peeks': led.get('holdout_peeks'),
          'best': top.head(5)[['id', 'desc', 'dev_n', 'dev_hit', 'dev_lb', 'dev_base']].to_dict('records'),
          'goal_reached': bool(len(final) > 0), 'note': cfg.get('note', '')}
    json.dump(st, open(os.path.join(rd, 'status.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=str)
    json.dump(st, open(os.path.join(L.STATE, 'latest_status.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=str)
    # 보고(한국어)
    lines = [f'# 라운드 {rnd} 보고', '', f'- 계획: {cfg.get("note", "")}',
             f'- 후보 {len(V)}개 → 개발 구간 통과 {int(V["dev_pass"].sum())}개 → 잠금 구간 통과 {len(passed)}개 → 반증까지 통과 {len(final)}개',
             f'- 누적: 후보 {led.get("trials_total")}개 시험, 잠금 구간 열람 {led.get("holdout_peeks")}번(통과 기준 p < 0.05 ÷ 열람 횟수)', '']
    a3 = os.path.join(rd, 'a03', 'touch_dev.csv')
    if os.path.exists(a3):
        t = pd.read_csv(a3); t0 = t[(t['시리즈'] == 'F0') & (t['조건'] == '전체')]
        if len(t0):
            lines += ['## 1단계(벽까지 올라가나) — 근월물 콜벽, 개발 구간', '| 관측(만기까지) | 주기 | 닿음 | 무작위 걷기 예상 |', '|---|---|---|---|']
            lines += [f'| {int(r["관측(만기까지 일)"])}일 | {int(r["주기수"])} | {r["닿음%"]:.0f}% | {r["무작위걷기 예상%"]:.0f}% |' for _, r in t0.iterrows()]
            lines += ['']
    lines += ['## 상위 후보(개발 구간, 독립 거래 기준)', '| 후보 | 거래 | 적중 | 하한 | 기본 | 위약 p | 버팀 |', '|---|---|---|---|---|---|---|']
    for _, r in top.head(10).iterrows():
        lines.append(f'| {r["desc"]} | {int(r["dev_n"])} | {f(r["dev_hit"], 0, True)} | {f(r["dev_lb"], 0, True)} | {f(r["dev_base"], 0, True)} | '
                     f'{f(r.get("위약p"), 3)} | {r.get("버팀", "—")} |')
    if len(passed):
        lines += ['', '## 잠금 구간(2024~) 결과 — 개발 통과 후보만']
        for _, r in V[V['dev_pass']].iterrows():
            lines.append(f'- {r["desc"]}: 거래 {int(r.get("hold_n", 0) or 0)}, 적중 {f(r.get("hold_hit"), 0, True)}, 기본 {f(r.get("hold_base"), 0, True)}, p {f(r.get("hold_p"), 4)}, 통과 {r.get("hold_pass")}')
    lines += ['', f'목표(방향 적중 80% 이상, 잠금 구간·반증 통과) 도달: {"예" if len(final) else "아니오"}', '', '투자 권유 아님']
    open(os.path.join(rd, 'report.md'), 'w', encoding='utf-8').write('\n'.join(lines))
    hist = os.path.join(L.STATE, 'history.md')
    with open(hist, 'a', encoding='utf-8') as fh:
        fh.write(f'\n## 라운드 {rnd} — {pd.Timestamp.now(tz="Asia/Seoul"):%Y-%m-%d %H:%M}\n- 계획: {cfg.get("note", "")}\n'
                 f'- 후보 {len(V)} / 개발 통과 {int(V["dev_pass"].sum())} / 잠금 통과 {len(passed)} / 최종 {len(final)}\n'
                 f'- 최상위: {top.iloc[0]["desc"] if len(top) else "—"} (개발 적중 {f(top.iloc[0]["dev_hit"], 0, True) if len(top) else "—"}, 거래 {int(top.iloc[0]["dev_n"]) if len(top) else 0})\n')
    print('\n'.join(lines[:12]))


if __name__ == '__main__':
    main()
