# -*- coding: utf-8 -*-
"""Signal A 판정 — 줄기 결과(tN/out/cands.pkl·meta.json)를 CRITERIA.md 1~3절로 판정하고 표·보고서·'아쉬운 줄기'를 만든다.

기준 숫자는 CRITERIA.md 그대로다. **이 파일의 기준 숫자는 사용자만 바꾼다**(총괄·에이전트는 고치지 않는다).
  1절 통과: 독립 거래 전체 35건·85%, 앞(2010~2023)·뒤(2024~) 각 12건·80%.  관찰: 전체 35건·80%, 앞·뒤 각 12건·75%.
  3절 1번(다음 해 성적): 해마다 그 전 자료만으로 고른 절차(kind='wf')의 적중률이 같은 해 아무 날보다 10%p 이상 높고 독립 거래 30건 이상.
  3절 2번(가짜 신호): 신호 날짜를 같은 해 안에서만 옮긴 가짜 2,000번 가운데 실제 이상인 비율 × 그 묶음 가짓수 < 5%.
  3절 3번(2026년): 2026년을 넣어도 빼도 아무 날보다 높고, 큰 변동 해(2011·2020·2026)만 모아도 아무 날보다 낮지 않다.
읽는 법(2026-11-24 총괄이 정함, log.md 에 적음):
  - 3절 2번의 가짓수: wf 절차는 그 줄기의 wf 절차 수(meta.m_wf), fixed 후보는 그 후보를 고른 모집단 크기(meta.m_fixed).
  - 3절 3번에서 큰 변동 해 독립 거래가 10건 미만이면 %로 말하지 않으므로 '판정 불가'(통과로 치지 않음)로 두고 아쉬운 줄기에 적는다.
  - 보유일 없는 채점(hit 칸) 후보는 '같은 해 아무 날'과 가짜 신호도 같은 채점 방식(후보가 넘긴 base_y)으로 잰다.
  - T6(청산)은 등급을 매기지 않는다(손절·익절은 2절의 매매가 아니고 익절은 적중률을 저절로 올린다).
  - '최종 후보' = 1절 통과 + 3절 셋 다. fixed 후보는 3절 1번을 직접 잴 수 없으므로 wf_of 로 이어진 wf 절차의 3절 결과를 물려받는다(없으면 최종 후보 아님).
사용: python sa_judge.py --track t1 [--iters 2000] [--no-state]
"""
import argparse
import json
import os

import numpy as np
import pandas as pd

import sa_common as C

GOAL = dict(all_n=35, all_hit=0.85, part_n=12, part_hit=0.80)      # CRITERIA 1절 통과
WATCH = dict(all_n=35, all_hit=0.80, part_n=12, part_hit=0.75)     # CRITERIA 1절 관찰
C31 = dict(edge=0.10, n=30)                                        # CRITERIA 3절 1번
C32 = dict(iters=2000, alpha=0.05)                                 # CRITERIA 3절 2번
MIN_PCT = 10                                                       # 표본 10개 미만은 %로 말하지 않는다
P1_END = pd.Timestamp('2023-12-31')
NAMES = {'t1': 'T1 위치·사건 규칙 전수', 't2': 'T2 상태 → 방아쇠', 't3': 'T3 합의·확률', 't4': 'T4 변동폭 맞춤', 't5': 'T5 하락·인버스', 't6': 'T6 청산'}


def _meets(a, p1, p2, need):
    return bool(a['n'] >= need['all_n'] and (a['hit'] or 0) >= need['all_hit'] and p1['n'] >= need['part_n'] and (p1['hit'] or 0) >= need['part_hit']
                and p2['n'] >= need['part_n'] and (p2['hit'] or 0) >= need['part_hit'])


def judge_one(D, c, m, iters):
    d = int(c['direction']); tr = c['trades']; by = c.get('base_y') if 'hit' in tr else None
    a = C.score(tr, d, D.K); p1 = C.score(tr, d, D.K, C.START, P1_END); p2 = C.score(tr, d, D.K, C.SPLIT, C.END)
    t = a['t']; h = int(c.get('hold') or C.hold_days(t, D.td))
    row = {'id': c['id'], 'track': c.get('track'), 'kind': c.get('kind', 'fixed'), 'family': c.get('family'), 'desc': c.get('desc'), 'direction': d, 'hold': h,
           'wf_of': c.get('wf_of'), 'n_signals': int(len(tr)), 'scoring': ('touch' if 'hit' in tr else 'hold'), 'base_same_scoring': bool('hit' not in tr or by is not None),
           'all_n': a['n'], 'all_k': a['k'], 'all_hit': a['hit'], 'all_lb': a['lb'], 'all_sum': a['sum'], 'all_mean': a['mean'],
           'p1_n': p1['n'], 'p1_hit': p1['hit'], 'p2_n': p2['n'], 'p2_hit': p2['hit'], 'by_year': a['by_year']}
    row['goal_pass'] = _meets(a, p1, p2, GOAL); row['watch_pass'] = bool(not row['goal_pass'] and _meets(a, p1, p2, WATCH))
    base = C.base_for(D, t, h, d, by) if a['n'] else None
    row['base'] = base; row['edge'] = (a['hit'] - base) if (a['n'] and base is not None) else None
    row['c31'] = bool(row['kind'] == 'wf' and a['n'] >= C31['n'] and row['edge'] is not None and row['edge'] >= C31['edge'])
    # 3절 2번
    if a['n'] >= MIN_PCT:
        pl = C.placebo_same_year(D, t, d, h=h, n_iter=iters, base_y=by)
        row['fake_p'] = pl['p']; row['fake_mean'] = pl['fake_mean']; row['fake_m'] = int(m); row['fake_p_adj'] = min(1.0, pl['p'] * m)
        row['c32'] = bool(row['fake_p_adj'] < C32['alpha'])
    else:
        row.update({'fake_p': None, 'fake_mean': None, 'fake_m': int(m), 'fake_p_adj': None, 'c32': False})
    # 3절 3번
    if a['n']:
        y = pd.DatetimeIndex(t['signal']).year.values; ok = t['ok'].values.astype(bool)
        ex = t[y != 2026]; big = t[np.isin(y, C.BIG_YEARS)]
        row['ex26_n'] = int(len(ex)); row['ex26_hit'] = float(ok[y != 2026].mean()) if len(ex) else None; row['ex26_base'] = C.base_for(D, ex, h, d, by) if len(ex) else None
        row['y26_n'] = int((y == 2026).sum()); row['y26_hit'] = float(ok[y == 2026].mean()) if row['y26_n'] else None
        row['big_n'] = int(len(big)); row['big_hit'] = float(ok[np.isin(y, C.BIG_YEARS)].mean()) if len(big) else None; row['big_base'] = C.base_for(D, big, h, d, by) if len(big) else None
        same = bool(row['edge'] is not None and row['edge'] > 0 and row['ex26_hit'] is not None and row['ex26_base'] is not None and row['ex26_hit'] - row['ex26_base'] > 0)
        row['c33_same'] = same
        row['c33_big'] = None if row['big_n'] < MIN_PCT else bool(row['big_hit'] >= row['big_base'])
        row['c33'] = bool(same and row['c33_big'] is True)
    else:
        row.update({'ex26_n': 0, 'ex26_hit': None, 'ex26_base': None, 'y26_n': 0, 'y26_hit': None, 'big_n': 0, 'big_hit': None, 'big_base': None, 'c33_same': False, 'c33_big': None, 'c33': False})
    return row


def _f(x, d=1):
    return C.pct(x, d)


def wishes(track, rows, meta):
    W = []; tn = track.upper()
    if track == 't6':
        if meta.get('parts_failed'): W.append(f"[{tn}] 계산 조각 {meta['parts_failed']} 이 끝내 실패해 가족 일부를 못 봄")
        return W + [f"[{tn}] 안 넣은 것: {x}" for x in meta.get('not_included', [])]
    goal = [r for r in rows if r['goal_pass']]; watch = [r for r in rows if r['watch_pass']]
    if watch and not goal:
        b = max(watch, key=lambda r: (r['all_hit'] or 0, r['all_n']))
        lack = []
        if (b['all_hit'] or 0) < GOAL['all_hit']: lack.append(f"전체 적중 {_f(b['all_hit'])}(통과 85%까지 {100 * (GOAL['all_hit'] - b['all_hit']):.1f}%p 모자람)")
        if (b['p1_hit'] or 0) < GOAL['part_hit']: lack.append(f"앞 구간 {_f(b['p1_hit'])}(80% 필요)")
        if (b['p2_hit'] or 0) < GOAL['part_hit']: lack.append(f"뒤 구간 {_f(b['p2_hit'])}(80% 필요)")
        W.append(f"[{tn}] 관찰 등급 {len(watch)}개, 통과 0개 — 가장 가까운 것: {b['desc']} · 독립 {b['all_n']}거래 · " + ', '.join(lack))
    wf = [r for r in rows if r['kind'] == 'wf']
    short = [r for r in wf if r['edge'] is not None and r['edge'] >= C31['edge'] and MIN_PCT <= r['all_n'] < C31['n']]
    if short:
        b = max(short, key=lambda r: r['all_n'])
        W.append(f"[{tn}] 다음 해 성적은 넘었는데 독립 거래 수가 모자람 {len(short)}개 — 예: {b['desc']} · {b['all_n']}거래(30건 필요) · 적중 {_f(b['all_hit'])} 대 아무 날 {_f(b['base'])}")
    flip = [r for r in wf if r['all_n'] >= C31['n'] and r['edge'] is not None and r['ex26_hit'] is not None and r['ex26_base'] is not None
            and ((r['ex26_hit'] - r['ex26_base'] >= C31['edge']) != (r['edge'] >= C31['edge']))]
    if flip:
        b = max(flip, key=lambda r: abs((r['ex26_hit'] - r['ex26_base']) - r['edge']))
        W.append(f"[{tn}] 2026년을 넣고 빼면 결론이 바뀜 {len(flip)}개 — 예: {b['desc']} · 2026 넣음 {_f(b['all_hit'])}(아무 날 {_f(b['base'])}) / 뺌 {_f(b['ex26_hit'])}(아무 날 {_f(b['ex26_base'])})")
    nobig = [r for r in wf if r['c31'] and r['c33_big'] is None]
    if nobig: W.append(f"[{tn}] 다음 해 성적은 넘었지만 큰 변동 해(2011·2020·2026) 독립 거래가 10건 미만이라 판정 불가 {len(nobig)}개")
    if meta.get('parts_failed'): W.append(f"[{tn}] 계산 조각 {meta['parts_failed']} 이 끝내 실패해 가족 일부를 못 봄")
    for s in meta.get('not_included', []): W.append(f"[{tn}] 안 넣은 것: {s}")
    return W


def table(rows, cols, head):
    out = ['| ' + ' | '.join(head) + ' |', '|' + '---|' * len(head)]
    for r in rows: out.append('| ' + ' | '.join(str(f(r)) for f in cols) + ' |')
    return out


def report(track, rows, meta, W, summ):
    wf = sorted([r for r in rows if r['kind'] == 'wf'], key=lambda r: (-(r['edge'] if r['edge'] is not None and r['all_n'] >= MIN_PCT else -9), -r['all_n']))
    fx = sorted([r for r in rows if r['kind'] != 'wf'], key=lambda r: (not r['goal_pass'], not r['watch_pass'], -(r['all_hit'] or 0) if r['all_n'] >= GOAL['all_n'] else 1, -r['all_n']))
    yn = lambda b: '예' if b is True else ('판정 불가' if b is None else '아니오')
    M = [f"# {NAMES.get(track, track)} — 판정 ({pd.Timestamp.now(tz='Asia/Seoul'):%Y-%m-%d %H:%M}, 자료 끝 {C.END.date()})", '',
         f"- 시험한 가짓수 {meta.get('n_tested', 0):,}개 (가족별: " + ', '.join(f'{k} {v:,}' for k, v in (meta.get('families') or {}).items()) + ')',
         f"- 넘겨받은 후보 {len(rows)}개 = 해마다 고른 절차 {len(wf)}개 + 전체 기간 고정 규칙 {len(fx)}개",
         f"- 통과 숫자(35거래·85%, 앞·뒤 12거래·80%) {summ['pass']}개 · 관찰(80%·75%) {summ['watch']}개 · 다음 해 성적 기준(아무 날 +10%p·30거래) {summ['c31']}개 · 최종 후보 {summ['final']}개",
         '- 매매: 코스피 지수, 신호 다음 날 시가 매수 → 정한 날 종가 매도. 수익 합계는 거래별 단순 합. 표본 10개 미만은 %를 적지 않는다.', '']
    if track == 't6':
        M += ['**T6 은 청산 방법 비교다 — 통과·관찰·최종 후보 등급은 매기지 않는다(등급은 원래 줄기에서). 손절·익절은 적중률을 저절로 올리므로 비용 뒤 수익 합계로 읽을 것.**', '']
    elif summ['c31'] == 0:
        M += ['**이 줄기에서는 다음 해 성적 기준을 넘은 절차가 없다.**' + (' 하락 신호는 이 자료로는 안 됨.' if track == 't5' else ''), '']
    for s in meta.get('notes', []): M.append(f'- {s}')
    M += ['', '## 1. 다음 해 성적 (해마다 그 전 자료만으로 고른 절차 — 믿을 숫자)', '']
    hp = lambda r, k, n: _f(r[k]) if (r[n] or 0) >= MIN_PCT else '–'
    M += table(wf[:25], [lambda r: r['desc'], lambda r: r['all_n'], lambda r: hp(r, 'all_hit', 'all_n'), lambda r: hp(r, 'base', 'all_n'),
                         lambda r: (f"{100 * r['edge']:+.1f}%p" if r['edge'] is not None and r['all_n'] >= MIN_PCT else '–'), lambda r: f"{100 * r['all_sum']:+.1f}%",
                         lambda r: (f"{r['fake_p_adj']:.3f}" if r['fake_p_adj'] is not None else '–'), lambda r: f"{r['y26_n']}건 {hp(r, 'y26_hit', 'y26_n')}",
                         lambda r: hp(r, 'ex26_hit', 'ex26_n'), lambda r: f"{r['big_n']}건 {hp(r, 'big_hit', 'big_n')}",
                         lambda r: yn(r['c31']), lambda r: yn(r['c32']), lambda r: yn(r['c33'] if r['c33_big'] is not None or not r['c33_same'] else None), lambda r: yn(r['final'])],
               ['절차', '독립 거래', '적중', '같은 해 아무 날', '차이', '수익 합계', f"가짜 시험 p(×{meta.get('m_wf', 1)})", '2026년', '2026 빼면', '큰 변동 해', '①다음 해', '②가짜', '③2026', '최종 후보'])
    if len(wf) > 25: M.append(f'\n(절차 {len(wf)}개 중 차이 큰 순 25개만 — 전부는 out/judge.csv)')
    M += ['', '## 2. 전체 기간 고정 규칙 (결과를 보고 고른 숫자 — 다음 해 성적과 섞어 읽지 말 것)', '']
    M += table(fx[:20], [lambda r: r['desc'], lambda r: r['all_n'], lambda r: hp(r, 'all_hit', 'all_n'), lambda r: f"{r['p1_n']}건 {hp(r, 'p1_hit', 'p1_n')}", lambda r: f"{r['p2_n']}건 {hp(r, 'p2_hit', 'p2_n')}",
                         lambda r: hp(r, 'base', 'all_n'), lambda r: f"{100 * r['all_sum']:+.1f}%", lambda r: (f"{r['fake_p_adj']:.3f}" if r['fake_p_adj'] is not None else '–'),
                         lambda r: '통과' if r['goal_pass'] else ('관찰' if r['watch_pass'] else '–')],
               ['규칙', '독립 거래', '적중', '앞(~2023)', '뒤(2024~)', '같은 해 아무 날', '수익 합계', f"가짜 시험 p(×{meta.get('m_fixed', 1):,})", '등급'])
    if wf:
        M += ['', '## 3. 해마다 (차이가 가장 큰 절차 3개: 독립 거래 수 / 맞은 수)', '']
        ys = C.WF_YEARS
        M += table(wf[:3], [lambda r: r['desc']] + [(lambda r, y=y: '/'.join(map(str, r['by_year'].get(y, r['by_year'].get(str(y), [0, 0]))[:2]))) for y in ys], ['절차'] + [str(y) for y in ys])
    M += ['', '## 4. 아쉬운 줄기 (자동으로 다시 돌리지 않음 — 사용자가 정함)', '']
    M += [f'- {w}' for w in W] or ['- 없음']
    sp = os.path.join(C.SA, track, 'out', 'summary.md')
    if os.path.exists(sp): M += ['', '## 5. 이 줄기에서 따로 낸 표', '', open(sp, encoding='utf-8').read()]
    return '\n'.join(M) + '\n'


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--track', required=True); ap.add_argument('--iters', type=int, default=C32['iters']); ap.add_argument('--no-state', action='store_true')
    a = ap.parse_args(); track = a.track
    D = C.Data(); cands, meta = C.load_result(track)
    m_wf = max(1, int(meta.get('m_wf') or sum(1 for c in cands if c.get('kind') == 'wf') or 1)); m_fx = max(1, int(meta.get('m_fixed') or meta.get('n_tested') or 1))
    rows = [judge_one(D, c, m_wf if c.get('kind') == 'wf' else m_fx, a.iters) for c in cands]
    by = {r['id']: r for r in rows}
    for r in rows:
        if r['kind'] == 'wf': r['final'] = bool(r['goal_pass'] and r['c31'] and r['c32'] and r['c33'])
        else:
            w = by.get(r.get('wf_of') or '')
            r['final'] = bool(r['goal_pass'] and w is not None and w['c31'] and w['c32'] and w['c33'])
    if track == 't6':   # T6 은 청산 비교다. 손절·익절은 CRITERIA 2절의 매매(정한 날 종가 매도)가 아니고 익절은 적중률을 저절로 올리므로 등급을 매기지 않는다(숫자만 보고, 비용 뒤 수익 합계로 읽는다)
        for r in rows: r['goal_pass'] = r['watch_pass'] = r['c31'] = r['final'] = False
    summ = {'pass': sum(r['goal_pass'] for r in rows), 'watch': sum(r['watch_pass'] for r in rows), 'c31': sum(r['c31'] for r in rows), 'final': sum(r['final'] for r in rows),
            'n_wf': sum(r['kind'] == 'wf' for r in rows), 'n_fixed': sum(r['kind'] != 'wf' for r in rows)}
    W = wishes(track, rows, meta); od = os.path.join(C.SA, track, 'out'); now = pd.Timestamp.now(tz='Asia/Seoul').strftime('%Y-%m-%d %H:%M')
    json.dump({'track': track, 'at': now, 'n_tested': meta.get('n_tested', 0), 'm_fixed': m_fx, 'm_wf': m_wf, 'iters': a.iters, 'summary': summ, 'wish': W, 'rows': rows},
              open(os.path.join(od, 'judge.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=0, default=lambda o: o.item() if hasattr(o, 'item') else str(o))
    pd.DataFrame([{k: v for k, v in r.items() if k != 'by_year'} for r in rows]).to_csv(os.path.join(od, 'judge.csv'), index=False, encoding='utf-8')
    open(os.path.join(C.SA, track, 'report.md'), 'w', encoding='utf-8').write(report(track, rows, meta, W, summ))
    wf = [r for r in rows if r['kind'] == 'wf' and r['all_n'] >= MIN_PCT and r['edge'] is not None]
    wf30 = [r for r in wf if r['all_n'] >= C31['n']]      # 알림에는 독립 30건 이상인 절차를 먼저(없으면 10건 이상)
    best = max(wf30 or wf, key=lambda r: r['edge']) if wf else None
    core = (f"다음 해 최고 {_f(best['all_hit'])}(아무 날 {_f(best['base'])}, {best['all_n']}거래)" if best else '다음 해 성적 낼 절차 없음')
    msg = (f"[Signal A] {NAMES.get(track, track)} 끝. 시험 {meta.get('n_tested', 0):,}가지 · 통과 {summ['pass']} · 관찰 {summ['watch']} · 다음 해 기준 넘음 {summ['c31']} · 최종 후보 {summ['final']}. {core}."
           + (f" 아쉬운 줄기 {len(W)}건." if W else ''))[:198]
    os.makedirs(os.path.join(C.SA, 'notify'), exist_ok=True)
    open(os.path.join(C.SA, 'notify', f'kakao_{track}.txt'), 'w', encoding='utf-8').write(msg + '\n')
    json.dump({'at': now, 'n_tested': meta.get('n_tested', 0), **summ, 'parts_failed': meta.get('parts_failed', [])}, open(os.path.join(od, 'done.json'), 'w', encoding='utf-8'), ensure_ascii=False)
    print(msg)
    if a.no_state: return
    L = C.ledger_add(track, {k: int(v) for k, v in (meta.get('families') or {'전체': meta.get('n_tested', 0)}).items()}, note=f"통과 {summ['pass']}·관찰 {summ['watch']}·다음 해 {summ['c31']}·최종 {summ['final']}")
    S = C.read_status(); S.setdefault('tracks', {})[track] = '끝'
    S['wish'] = [w for w in S.get('wish', []) if not w.startswith(f'[{track.upper()}]')] + W
    C.write_status(S)
    lp = os.path.join(C.SA, 'log.md'); lines = open(lp, encoding='utf-8').read().rstrip('\n').split('\n')
    nums = [int(x.split('|')[1]) for x in lines if x.startswith('|') and x.split('|')[1].strip().isdigit()]
    lines.append(f"| {max(nums) + 1 if nums else 1} | {now[:10]} | {track.upper()} 판정(GitHub) | {NAMES.get(track, track)} 계산·판정 끝 | {core} | 통과 {summ['pass']}·관찰 {summ['watch']}·다음 해 {summ['c31']}·최종 {summ['final']} | {meta.get('n_tested', 0):,} (누적 {L['total']:,}) |")
    open(lp, 'w', encoding='utf-8').write('\n'.join(lines) + '\n')


if __name__ == '__main__':
    main()
