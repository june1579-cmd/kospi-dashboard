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
    cross = 'cv_mode' in V.columns and bool((V['cv_mode'] == 'cross').any())   # 2026-11-21~ 양방향 교차 검증
    if cross:
        for k in ('sel_fwd', 'sel_rev', 'fwd_pass', 'rev_pass', 'hold_pass'): V[k] = V[k].fillna(False).astype(bool)
        V['best_lb'] = V[['dev_lb', 'p2_lb']].max(axis=1)
        top = V[(V['dev_n'] >= 10) | (V['p2_n'] >= 10)].sort_values(['hold_pass', 'dev_pass', 'best_lb'], ascending=[False, False, False]).head(15)
    else:
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
          'best': top.head(5)[['id', 'desc', 'dev_n', 'dev_hit', 'dev_lb', 'dev_base'] + (['p2_n', 'p2_hit', 'p2_lb', 'p2_base', 'all_n', 'all_hit'] if cross else [])].to_dict('records'),
          'goal_reached': bool(len(final) > 0), 'note': cfg.get('note', '')}
    if cross:
        st.update({'cv_mode': 'cross', 'sel_fwd': int(V['sel_fwd'].sum()), 'sel_rev': int(V['sel_rev'].sum()), 'fwd_pass': int(V['fwd_pass'].sum()),
                   'rev_pass': int(V['rev_pass'].sum()), 'cross_tests': led.get('cross_tests')})
    json.dump(st, open(os.path.join(rd, 'status.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=str)
    json.dump(st, open(os.path.join(L.STATE, 'latest_status.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=str)
    # 보고(한국어)
    lines = [f'# 라운드 {rnd} 보고', '', f'- 계획: {cfg.get("note", "")}',
             (f'- 후보 {len(V)}개 → 앞(2010~2023) 선별 {int(V["sel_fwd"].sum())}·뒤(2024~) 선별 {int(V["sel_rev"].sum())} → 앞→뒤 확인 {int(V["fwd_pass"].sum())}·뒤→앞 확인 {int(V["rev_pass"].sum())} → 양방향 통과 {len(passed)}개 → 반증까지 통과 {len(final)}개'
              if cross else f'- 후보 {len(V)}개 → 개발 구간 통과 {int(V["dev_pass"].sum())}개 → 잠금 구간 통과 {len(passed)}개 → 반증까지 통과 {len(final)}개'),
             (f'- 누적: 후보 {led.get("trials_total")}개 시험, 교차 확인 {led.get("cross_tests")}번(라운드 안 확인 p 기준 = 0.05 ÷ 그 방향 선별 수) · 잠금 규칙 없이 양방향 교차 검증(2026-11-21~)'
              if cross else f'- 누적: 후보 {led.get("trials_total")}개 시험, 잠금 구간 열람 {led.get("holdout_peeks")}번(통과 기준 p < 0.05 ÷ 열람 횟수)'), '']
    a3 = os.path.join(rd, 'a03', 'touch_dev.csv')
    if os.path.exists(a3):
        t = pd.read_csv(a3); t0 = t[(t['시리즈'] == 'F0') & (t['조건'] == '전체')]
        if len(t0):
            lines += ['## 1단계(벽까지 올라가나) — 근월물 콜벽, 개발 구간', '| 관측(만기까지) | 주기 | 닿음 | 무작위 걷기 예상 |', '|---|---|---|---|']
            lines += [f'| {int(r["관측(만기까지 일)"])}일 | {int(r["주기수"])} | {r["닿음%"]:.0f}% | {r["무작위걷기 예상%"]:.0f}% |' for _, r in t0.iterrows()]
            lines += ['']
    cs = os.path.join(rd, 'a03c', 'cause_summary.json')
    if os.path.exists(cs):
        S = json.load(open(cs, encoding='utf-8')); fz = S.get('funnel_F0_20') or {}
        mg = {r.get('구간'): r.get('3일 안 벽 위로%') for r in S.get('migration', [])}
        hd = S.get('hindsight') or {}
        lines += ['## 원인 분해 — 사슬이 어디서 끊기나(근월물 콜벽, 만기 20일 전 관측, 개발 구간)',
                  '| 단계 | 실제 | 기준선(아무 힘이 없을 때) |', '|---|---|---|',
                  f"| ② 벽에 닿음 | {fz.get('②닿음%')}% | {fz.get('②기준%')}% (같은 거리 아무 가격선) |",
                  f"| ③ 종가로 넘음 | {fz.get('③넘음%')}% | {fz.get('③기준%')}% |",
                  f"| ④ 넘은 뒤 외국인 선물 5일 순매도 | {fz.get('④외국인 5일 순매도%')}% | {fz.get('④기준%(같은 상승 뒤)')}% (비슷하게 오른 뒤) |",
                  f"| ⑤ 넘은 뒤 10일 하락 | {fz.get('⑤10일 하락%')}% | {fz.get('⑤기준%')}% |",
                  f"- 사슬 완성(②~⑤ 모두): {fz.get('사슬 완성(②~⑤)')}번 / {fz.get('주기')}주기 (넘은 주기 {fz.get('넘은 주기(결과 확인)')}번)",
                  f"- 끌어당김: 벽이 같은 거리 다른 행사가보다 더 닿은 정도 {S.get('magnet_diff_pp')}%p · 닿은 날 막힌 정도 차 {S.get('resist_diff_pp')}%p",
                  f"- 벽 이동: 벽 1% 안으로 다가간 날 3일 안 벽이 위로 옮겨 간 비율 {mg.get('≤1%')}% (멀 때 {mg.get('>2%')}%), "
                  f"만기 20일 전 벽보다 만기 종가가 위인 주기 {S.get('cycles_exp_above_first_wall%')}%",
                  f"- 뒤늦게 보면: 고점 {hd.get('고점 수')}번 중 고점 날 벽이 고가 바로 위(1.5% 안) {hd.get('고점 날 벽이 고가 위 1.5% 안%')}% (아무 날 {hd.get('아무 날 벽이 고가 위 1.5% 안%')}%), "
                  f"그 벽이 20일 전에도 같은 벽 {hd.get('고점 벽이 20일 전에도 같은 벽%')}%", '']
    lines += ['## 상위 후보(개발 구간, 독립 거래 기준)', '| 후보 | 거래 | 적중 | 하한 | 기본 | 위약 p | 버팀 |', '|---|---|---|---|---|---|---|']
    for _, r in top.head(10).iterrows():
        lines.append(f'| {r["desc"]} | {int(r["dev_n"])} | {f(r["dev_hit"], 0, True)} | {f(r["dev_lb"], 0, True)} | {f(r["dev_base"], 0, True)} | '
                     f'{f(r.get("위약p"), 3)} | {r.get("버팀", "—")} |')
    if cross:
        S = V[V['dev_pass']]
        lines += ['', '## 교차 검증 — 한 구간에서 선별된 후보(앞 = 2010~2023, 뒤 = 2024~)', '| 후보 | 앞 거래·적중·기본 | 뒤 거래·적중·기본 | 앞→뒤 | 뒤→앞 |', '|---|---|---|---|---|']
        for _, r in S.head(20).iterrows():
            lines.append(f'| {r["desc"]} | {int(r["dev_n"])}·{f(r["dev_hit"], 0, True)}·{f(r["dev_base"], 0, True)} | {int(r["p2_n"])}·{f(r["p2_hit"], 0, True)}·{f(r["p2_base"], 0, True)} | '
                         f'{"통과" if r["fwd_pass"] else ("선별" if r["sel_fwd"] else "—")} | {"통과" if r["rev_pass"] else ("선별" if r["sel_rev"] else "—")} |')
        if not len(S): lines.append('| (선별 없음) | | | | |')
    elif len(passed):
        lines += ['', '## 잠금 구간(2024~) 결과 — 개발 통과 후보만']
        for _, r in V[V['dev_pass']].iterrows():
            lines.append(f'- {r["desc"]}: 거래 {int(r.get("hold_n", 0) or 0)}, 적중 {f(r.get("hold_hit"), 0, True)}, 기본 {f(r.get("hold_base"), 0, True)}, p {f(r.get("hold_p"), 4)}, 통과 {r.get("hold_pass")}')
    lines += ['', f'목표(방향 적중 80% 이상, {"양방향 교차 검증" if cross else "잠금 구간"}·반증 통과) 도달: {"예" if len(final) else "아니오"}', '', '투자 권유 아님']
    open(os.path.join(rd, 'report.md'), 'w', encoding='utf-8').write('\n'.join(lines))
    hist = os.path.join(L.STATE, 'history.md')
    with open(hist, 'a', encoding='utf-8') as fh:
        fh.write(f'\n## 라운드 {rnd} — {pd.Timestamp.now(tz="Asia/Seoul"):%Y-%m-%d %H:%M}\n- 계획: {cfg.get("note", "")}\n'
                 + (f'- 후보 {len(V)} / 앞 선별 {int(V["sel_fwd"].sum())}·뒤 선별 {int(V["sel_rev"].sum())} / 앞→뒤 {int(V["fwd_pass"].sum())}·뒤→앞 {int(V["rev_pass"].sum())} / 양방향 {len(passed)} / 최종 {len(final)}\n'
                    if cross else f'- 후보 {len(V)} / 개발 통과 {int(V["dev_pass"].sum())} / 잠금 통과 {len(passed)} / 최종 {len(final)}\n')
                 + (f'- 최상위: {top.iloc[0]["desc"]} (앞 적중 {f(top.iloc[0]["dev_hit"], 0, True)}·거래 {int(top.iloc[0]["dev_n"])}, 뒤 적중 {f(top.iloc[0]["p2_hit"], 0, True)}·거래 {int(top.iloc[0]["p2_n"])})\n'
                    if cross and len(top) else f'- 최상위: {top.iloc[0]["desc"] if len(top) else "—"} (개발 적중 {f(top.iloc[0]["dev_hit"], 0, True) if len(top) else "—"}, 거래 {int(top.iloc[0]["dev_n"]) if len(top) else 0})\n'))
    print('\n'.join(lines[:12]))


if __name__ == '__main__':
    main()
