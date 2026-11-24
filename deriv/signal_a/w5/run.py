# -*- coding: utf-8 -*-
"""W5 방아쇠 두 개가 겹칠 때만 — SPEC.md 그대로 구현(돌린 뒤 고치지 않는다). 오름 방향만.

방아쇠 8개·상태(바닥 전 상태, 해마다 그 전 자료로 다시 고름)는 T2 와 똑같다: t2/run.py 를 다른 이름으로 불러 triggers()·run_part() 를 그대로 쓴다(고치지 않음).
가족: pair_fixed 336(상태 없음, 전체 기간, fixed) · state_pair 672(S5·S10, wf) · pick 16(해마다 쌍 고르기, wf) · preset 12(T7+T8, wf) = 1,036.
조각 1개 = T2 의 상태 고르기. merge = 방아쇠 → 겹침 → 신호 → 고르기 → 후보·표.
명령: python run.py --nparts | --part i/n | --merge  (+ --quick)
"""
import importlib.util
import io
import itertools
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__)); SA = os.path.dirname(HERE); sys.path.insert(0, SA)
import sa_common as C   # noqa: E402

TRACK = 'w5'
TRIGS = [1, 2, 3, 4, 5, 6, 7, 8]
OVER = [0, 3, 5]                                                    # 0 = 같은 날, 3·5 = 최근 3·5거래일 안
WINS = (5, 10)
SCORES = [('h3', 3), ('h5', 5), ('h10', 10), ('touch', None)]
Q_TRIGS = [4, 7, 8]; Q_OVER = [0, 3]; Q_SCORES = [('h5', 5), ('touch', None)]
PRE = (7, 8)                                                        # REPORT 7절 3번이 이름 붙인 쌍: 외국인 매도 둔화 + 변동성 꺾임
MOVE = 0.05
CRITS = ['hit', 'lb']
TOPS = [1, 3]
Y0 = C.START.year
P1_END = pd.Timestamp('2023-12-31')
NOT_INCLUDED = ['방아쇠 세 개 이상이 겹칠 때, 8개 중 k개 이상 켜짐(합의 수)',
                '겹침 구간 2·10·20일, 순서를 정한 겹침(a 가 먼저 켜지고 b 가 뒤따를 때만)',
                '변동폭 맞춤판(장대 양봉 σ 기준, ±kσ 닿기)과 W4 격자의 다른 문턱으로 만든 변동성 꺾임과의 겹침',
                '겹친 뒤 하루 늦춤, 직전 5일 안 첫 신호만, 내림 방향',
                '상태 구간 3·20일, pick 절차의 다른 꼴(상위 5칸·2칸 이상 함께·상태 있는 칸에서 고르기)']
SC_TXT = {'h3': '다음 날 시가 매수 → 3일째 종가 매도', 'h5': '다음 날 시가 매수 → 5일째 종가 매도', 'h10': '다음 날 시가 매수 → 10일째 종가 매도',
          'touch': '다음 날 시가 기준 +5% 에 −5% 보다 먼저 닿으면 맞음(보유일 없음)'}
OV_TXT = {0: '같은 날 함께 켜짐', 3: '최근 3거래일 안에 둘 다 켜짐(둘째가 켜진 날 신호)', 5: '최근 5거래일 안에 둘 다 켜짐(둘째가 켜진 날 신호)'}
OV_SHORT = {0: '같은 날', 3: '3일 안', 5: '5일 안'}

_T2 = None


def t2mod():
    """t2/run.py 를 다른 이름으로 불러 온다(고치지 않고 정의만 빌려 씀). 못 읽으면 멈춘다."""
    global _T2
    if _T2 is None:
        p = os.path.join(SA, 't2', 'run.py')
        if not os.path.exists(p): raise RuntimeError('t2/run.py 가 없음 — 방아쇠·상태 정의를 못 읽어 멈춤')
        sp = importlib.util.spec_from_file_location('sa_t2_run_for_w5', p); m = importlib.util.module_from_spec(sp); sp.loader.exec_module(m); _T2 = m
    return _T2


def _cfg(quick):
    return (Q_TRIGS, Q_OVER, Q_SCORES) if quick else (TRIGS, OVER, SCORES)


def overlap(A, B, w):
    """겹침: w = 0 같은 날 둘 다. w > 0 이면 오늘 둘 중 하나가 켜졌고 둘 다 최근 w 거래일(오늘 포함) 안에 켜짐."""
    if w == 0: return A & B
    ra = pd.Series(A.astype(float)).rolling(w, min_periods=1).max().values > 0; rb = pd.Series(B.astype(float)).rolling(w, min_periods=1).max().values > 0
    return (A | B) & ra & rb


def _nmin(Y): return max(12, int(round(35 * (Y - Y0) / 17)))


def _thin(pos, ex):
    """독립 거래: 앞 거래 청산 위치 이후(같은 날 포함)의 신호만(D.thin_pos 와 같은 규칙, 청산 위치가 거래마다 달라도 됨)."""
    keep = []; last = -1
    for i, (s, e) in enumerate(zip(pos.tolist(), ex.tolist())):
        if s >= last: keep.append(i); last = e
    return np.asarray(keep, dtype=int)


def _md(df):
    out = ['| ' + ' | '.join(map(str, df.columns)) + ' |', '|' + '---|' * len(df.columns)]
    return out + ['| ' + ' | '.join(str(v) for v in r) + ' |' for r in df.values.tolist()]


def _pc(x): return '–' if x is None or (isinstance(x, float) and not np.isfinite(x)) else f'{100 * x:.0f}%'


# ------------------------------------------------------------------ 약속된 함수
def n_parts():
    return 1


def run_part(i, n, quick=False):
    """조각 = T2 의 상태 고르기 그대로(해마다 그 해 이전 자료로 지표·점수 문턱). 같은 씨앗 → T2 와 같은 상태."""
    out = t2mod().run_part(1, 1, vol=False, quick=quick)
    if not out.get('years'): raise RuntimeError('T2 상태 고르기 결과가 비어 있음 — 멈춤')
    return out


def merge(parts, quick=False):
    parts = list(parts or [])
    if not parts or any(p is None for p in parts): raise RuntimeError('W5 조각 결과가 없음 — 합치지 않고 멈춤')
    P = parts[0]
    if bool(P.get('quick')) != bool(quick) or P.get('vol'): raise RuntimeError('W5 조각이 quick/전체 가운데 다른 쪽 결과임 — 멈춤')
    T2 = t2mod(); D = C.Data(); n = D.n; trigs, overs, scores = _cfg(quick); ST = P['years']
    years_all = [y for y in C.WF_YEARS if (not quick or y in T2.QUICK_YEARS)]
    miss = [y for y in years_all if y not in ST]
    if miss: raise RuntimeError(f'상태가 없는 해 {miss} — 멈춤')
    T = T2.triggers(D, False); SHORT = T2.SHORT
    for j in trigs:
        if j not in T or len(T[j]) != n: raise RuntimeError(f'방아쇠 T{j} 를 못 만듦 — 멈춤')
    touch = C.first_touch(D, MOVE); ty, tex = touch; base_y = ty.astype(np.float32)          # 닿기 채점 후보 모두가 이 배열 하나를 함께 가리킨다
    FW = {h: D.fwd(h) for _, h in scores if h is not None}
    live = np.asarray(D.td >= C.START); ywf = np.isin(D.year, years_all)
    # 상태 켜짐 구간(T2 merge 와 같은 계산: 해 Y 규칙을 Y 년의 날에)
    ON = {w: np.zeros(n, bool) for w in WINS}; rows_st = []
    for Y in years_all:
        m = ST[Y]; on = (m['score'] >= m['k']) & (len(m['comps']) >= 2); iy = D.year == Y
        for w in WINS: ON[w][iy] = (pd.Series(on.astype(float)).rolling(w, min_periods=1).max().values > 0)[iy]
        rows_st.append({'해': Y, '그때까지_저점수': m['E'], '조건수': len(m['comps']), '점수문턱': m['k'], '그해_5일구간': int(ON[5][iy].sum()), '그해_10일구간': int(ON[10][iy].sum()),
                        '지표': ' · '.join(f"{nm}({'80 이상' if sd == 'hi' else '20 이하'})" for nm, sd, *_ in m['comps'])})
    pairs = list(itertools.combinations(trigs, 2))
    if PRE not in pairs: raise RuntimeError('이름 붙인 쌍(T7+T8)이 목록에 없음 — 멈춤')

    def arrays(pos, key, h):
        """신호 위치 → (쓸 수 있는 신호 위치, 청산 위치, 맞음)."""
        pos = np.asarray(pos, dtype=int)
        if h is not None:
            pos = pos[pos + h < n]; r = FW[h][pos]; ok = np.isfinite(r); pos = pos[ok]
            return pos, pos + h, r[ok] > 0
        pos = pos[np.isfinite(ty[pos])]
        return pos, tex[pos], ty[pos] > 0

    def trades(pos, h):
        pos, ex, hit = arrays(pos, None, h)
        if h is not None: return pd.DataFrame({'signal': D.td[pos], 'exit': D.td[ex]})
        return pd.DataFrame({'signal': D.td[pos], 'exit': D.td[ex], 'hit': hit.astype(int)})

    def base(t, h):
        """같은 해 아무 날 적중(해 구성 맞춤). 닿기 채점은 아무 날의 '+쪽 먼저 닿기' 비율."""
        if not len(t): return None
        return C.base_for(D, t, h, 1) if h is not None else C.base_for(D, t, 1, 1, base_y)

    def cand(cid, fam, desc, key, h, pos, kind, root, extra=None):
        c = {'id': cid, 'family': fam, 'desc': desc, 'direction': 1, 'hold': h, 'kind': kind, 'trades': trades(pos, h), 'root': root}
        if h is None: c['base_y'] = base_y
        if extra: c.update(extra)
        return c

    def stat(tr, h):
        s = C.score(tr, 1, D.K); b = base(s['t'], h) if s['n'] else None
        return s['n'], s['k'], (s['hit'] if s['n'] >= 10 else None), b

    # ---- 따로 쓸 때(방아쇠 하나만): 전체 기간(2010~)·2016~2026 두 기간
    single = {}
    for j in trigs:
        for key, h in scores:
            for per, msk in (('all', live), ('wf', ywf)):
                single[(j, key, per)] = stat(trades(np.flatnonzero(T[j] & msk), h), h)

    cands = []; rows = []; cells = []                                # cells = 상태 없는 칸(고르기용)
    for a, b in pairs:
        pname = f'{SHORT[a]} + {SHORT[b]}'; root = '방아쇠 겹침' + ('·변동성 꺾임 포함' if 8 in (a, b) else '')
        for w in overs:
            ov = overlap(T[a], T[b], w)
            for key, h in scores:
                # 상태 없음(fixed, 전체 기간)
                pos = np.flatnonzero(ov & live); cid = f'P_T{a}xT{b}_D{w}_{key}'
                extra = {'params': {'pair': [a, b], 'overlap': w, 'state': None, 'score': key}}
                if (a, b) == PRE: extra['wf_of'] = f'WF_pre_T{a}xT{b}_D{w}_{key}'
                c = cand(cid, 'pair_fixed', f'상태 없이 방아쇠 두 개 겹침: {pname} 이 {OV_TXT[w]} → {SC_TXT[key]}', key, h, pos, 'fixed', root, extra); cands.append(c)
                nn, kk, hit, bs = stat(c['trades'], h); sa, sb = single[(a, key, 'all')], single[(b, key, 'all')]
                best1 = max([x for x in (sa[2], sb[2]) if x is not None], default=None)
                rows.append({'쌍': f'T{a}xT{b}', '방아쇠': pname, '겹침': OV_SHORT[w], '상태': '없음', '기간': '2010~', '채점': key, '겹친 날 수': int(len(pos)), '독립 거래': nn, '맞은 수': kk,
                             '적중': hit, '같은 해 아무 날': bs, '차이': (hit - bs if hit is not None and bs is not None else None),
                             f'따로 a 적중': sa[2], '따로 a 거래': sa[0], '따로 b 적중': sb[2], '따로 b 거래': sb[0], '따로보다': (hit - best1 if hit is not None and best1 is not None else None)})
                p_, e_, h_ = arrays(pos, key, h); ind = _thin(p_, e_)
                cells.append({'id': cid, 'a': a, 'b': b, 'w': w, 'key': key, 'h': h, 'pos': p_, 'ex': e_, 'ind_hit': h_[ind], 'ind_ey': D.year[e_[ind]]})
                # 상태 있음(wf, 2016~2026)
                for win in WINS:
                    pos_s = np.flatnonzero(ov & ON[win]); sid = f'S{win}_T{a}xT{b}_D{w}_{key}'
                    c = cand(sid, 'state_pair', f'바닥 전 상태(해마다 그 전 자료로 고른 지표 점수 ≥ 문턱)가 최근 {win}거래일 안에 켜짐 + 방아쇠 두 개 겹침: {pname} 이 {OV_TXT[w]} → {SC_TXT[key]}',
                             key, h, pos_s, 'wf', root, {'params': {'pair': [a, b], 'overlap': w, 'state': win, 'score': key}}); cands.append(c)
                    nn, kk, hit, bs = stat(c['trades'], h); sa, sb = single[(a, key, 'wf')], single[(b, key, 'wf')]
                    best1 = max([x for x in (sa[2], sb[2]) if x is not None], default=None)
                    rows.append({'쌍': f'T{a}xT{b}', '방아쇠': pname, '겹침': OV_SHORT[w], '상태': f'S{win}', '기간': '2016~', '채점': key, '겹친 날 수': int(len(pos_s)), '독립 거래': nn, '맞은 수': kk,
                                 '적중': hit, '같은 해 아무 날': bs, '차이': (hit - bs if hit is not None and bs is not None else None),
                                 '따로 a 적중': sa[2], '따로 a 거래': sa[0], '따로 b 적중': sb[2], '따로 b 거래': sb[0], '따로보다': (hit - best1 if hit is not None and best1 is not None else None)})
                # 이름 붙인 쌍(wf, 상태 없음, 2016~2026)
                if (a, b) == PRE:
                    pos_w = np.flatnonzero(ov & ywf)
                    cands.append(cand(f'WF_pre_T{a}xT{b}_D{w}_{key}', 'preset', f'[고르지 않음 — REPORT 7절 3번이 T2 결과를 본 뒤 이름 붙인 쌍] 상태 없이 {pname} 이 {OV_TXT[w]} → {SC_TXT[key]} (2016~2026)',
                                      key, h, pos_w, 'wf', root, {'params': {'pair': [a, b], 'overlap': w, 'state': None, 'score': key, 'proc': 'pre'}}))
    T_pair = pd.DataFrame(rows)

    # ---- 해마다 쌍을 고르는 절차(pick)
    crit_ko = {'hit': '적중이 가장 높은', 'lb': '윌슨 하한이 가장 높은'}; picks = []
    for key, h in scores:
        pool = [i for i, c in enumerate(cells) if c['key'] == key]; stats = {}
        for Y in years_wf(quick):
            st = []
            for i in pool:
                tr_ = cells[i]['ind_ey'] < Y; nn = int(tr_.sum()); kk = int(cells[i]['ind_hit'][tr_].sum())
                if nn >= _nmin(Y): st.append((i, nn, kk, kk / nn, C.wilson(kk, nn)[0]))
            stats[Y] = st
        for cr in CRITS:
            order = {Y: sorted(st, key=lambda x: (-(x[3] if cr == 'hit' else x[4]), -x[1], x[0])) for Y, st in stats.items()}
            for top in TOPS:
                allpos = []
                for Y in years_wf(quick):
                    sel = order[Y][:top]; days = set()
                    for x in sel:
                        p_ = cells[x[0]]['pos']; days.update(p_[D.year[p_] == Y].tolist())
                    allpos += sorted(days)
                    row = {'절차': f'WF_{cr}_top{top}_{key}', '해': Y, '최소 거래 수': _nmin(Y), '거래 수 채운 칸': len(order[Y]), '고른 칸 수': len(sel), '그 해 신호 수': len(days)}
                    for r_, x in enumerate(sel, 1):
                        row[f'{r_}위 칸'] = cells[x[0]]['id']; row[f'{r_}위 그때까지'] = f'{x[1]}거래 {100 * x[3]:.1f}%(하한 {100 * x[4]:.1f}%)'
                    picks.append(row)
                use = '1위 칸만 사용' if top == 1 else '상위 3칸 가운데 하나라도 켜진 날'
                cands.append(cand(f'WF_{cr}_top{top}_{key}', 'pick', f'해마다 그 전 자료에서 {crit_ko[cr]} 방아쇠 쌍(상태 없는 쌍 {len(pairs)} × 겹침 {len(overs)} = {len(pool)}칸)을 골라 {use} → {SC_TXT[key]}',
                                  key, h, np.asarray(allpos, dtype=int), 'wf', '방아쇠 겹침(해마다 고름)', {'params': {'proc': cr, 'top': top, 'score': key}}))
    T_pick = pd.DataFrame(picks); T_state = pd.DataFrame(rows_st)

    # ---- 가짓수
    np_, no_, ns_ = len(pairs), len(overs), len(scores)
    fam = {'pair_fixed': np_ * no_ * ns_, 'state_pair': len(WINS) * np_ * no_ * ns_, 'pick': len(CRITS) * len(TOPS) * ns_, 'preset': no_ * ns_}
    n_tested = int(sum(fam.values())); m_fixed = fam['pair_fixed']; m_wf = fam['state_pair'] + fam['pick'] + fam['preset']
    cnt = {k: sum(1 for c in cands if c['family'] == k) for k in fam}
    if cnt != fam: raise RuntimeError(f'후보 수가 가짓수와 다름: {cnt} != {fam}')
    if len({c['id'] for c in cands}) != len(cands): raise RuntimeError('후보 id 가 겹침 — 멈춤')
    if not quick and (n_tested != 1036 or m_fixed != 336 or m_wf != 700): raise RuntimeError(f'가짓수가 SPEC 과 다름: {n_tested}·{m_fixed}·{m_wf}')
    if not cands or n_tested == 0: raise RuntimeError('W5 후보 0개 — 멈춤')
    if not quick and sum(len(c['trades']) for c in cands) == 0: raise RuntimeError('W5 전체에 신호가 하나도 없음 — 자료를 못 읽은 것으로 보고 멈춤')

    # ---- summary.md
    md = ['### W5 방아쇠 두 개가 겹칠 때만: 따로 낸 표' + (' [quick 시험]' if quick else ''), '',
          f'- 방아쇠 {len(trigs)}개의 쌍 {np_}개 × 겹침 정의 {no_} × 상태 3(없음·5일·10일 구간) × 채점 {ns_}. 방아쇠·상태 정의는 T2 와 같다. 오름 방향만.',
          "- **'상태 없음' 표는 전체 기간(2010~) 결과를 보고 고르는 숫자다.** 겹침 정의끼리(같은 날 ⊂ 3일 안 ⊂ 5일 안) 서로 포함 관계라 닮았다. 믿을 숫자는 판정 표의 다음 해 성적(절차)이다.",
          '- 칸 = 적중(독립 거래 수/겹친 날 수) · ± = 같은 해 아무 날과의 차이. 독립 거래 10건 미만은 %를 적지 않는다. 따로 = 그 방아쇠 하나만 썼을 때(같은 기간·같은 채점).', '']
    def cell(r):
        if r is None: return '–'
        d = r['차이']; d = f' {100 * d:+.0f}%p' if d is not None and np.isfinite(d) else ''
        return f"{_pc(r['적중'])} ({r['독립 거래']}/{r['겹친 날 수']}){d}"
    for key, h in scores:
        g = {(r['쌍'], r['겹침'], r['상태']): r for r in rows if r['채점'] == key}
        md += [f'#### 상태 없음 · {SC_TXT[key]}', '', '| 쌍 | ' + ' | '.join(OV_SHORT[w] for w in overs) + ' | 따로(앞 방아쇠 · 뒤 방아쇠) |', '|' + '---|' * (len(overs) + 2)]
        for a, b in pairs:
            sa, sb = single[(a, key, 'all')], single[(b, key, 'all')]
            md.append(f'| {SHORT[a]} + {SHORT[b]} | ' + ' | '.join(cell(g.get((f'T{a}xT{b}', OV_SHORT[w], '없음'))) for w in overs) + f' | {_pc(sa[2])} ({sa[0]}) · {_pc(sb[2])} ({sb[0]}) |')
        md.append('')
    a, b = PRE
    md += [f'#### 이름 붙인 쌍: {SHORT[a]} + {SHORT[b]} — 상태별(REPORT 7절 3번이 T2 결과를 본 뒤 붙인 이름)', '',
           '| 채점 | 겹침 | 상태 없음(2010~) | 상태 5일 구간(2016~) | 상태 10일 구간(2016~) |', '|---|---|---|---|---|']
    for key, h in scores:
        g = {(r['쌍'], r['겹침'], r['상태']): r for r in rows if r['채점'] == key}
        for w in overs:
            md.append(f"| {key} | {OV_SHORT[w]} | " + ' | '.join(cell(g.get((f'T{a}xT{b}', OV_SHORT[w], s_))) for s_ in ('없음', 'S5', 'S10')) + ' |')
    md += ['', '#### 해마다 고른 쌍(1위) — 절차별', '', '고른 칸이 해마다 바뀌는지 본다. 전부는 tables/pick_by_year.csv.', '']
    if len(T_pick) and '1위 칸' in T_pick:
        top1 = T_pick[T_pick['절차'].str.contains('_top1_')]; piv = top1.pivot(index='절차', columns='해', values='1위 칸').fillna('–')
        md += _md(piv.reset_index().rename(columns=str)) + ['']
    else: md += ['- 최소 거래 수를 채운 칸이 없어 고른 것이 없음', '']
    names = ['pair_compare.csv', 'pick_by_year.csv', 'state_by_year.csv']; tables_csv = {}
    for nm, df in zip(names, (T_pair, T_pick, T_state)):
        buf = io.StringIO(); df.to_csv(buf, index=False); tables_csv[nm] = buf.getvalue()
    notes = ['W5 는 T2 방아쇠 8개의 모든 쌍(28쌍)이 겹친 날만 신호로 본 것이다. 방아쇠·상태 정의는 T2 와 같다(t2/run.py 를 그대로 불러 씀).',
             'fixed 336개(상태 없는 쌍)는 전체 기간 결과를 보고 고르는 숫자다. 믿을 숫자는 wf 700개(상태 쓰는 쌍 672 + 해마다 쌍 고르기 16 + 이름 붙인 쌍 12).',
             "이름 붙인 쌍(외국인 매도 둔화 + 변동성 꺾임)은 T2 결과를 본 뒤 REPORT 7절 3번이 예로 든 것이라 '미리 정한 쌍'이라고만 읽으면 안 된다.",
             '해마다 고르는 절차가 700개라 가짜 2,000번으로는 가짓수 보정(CRITERIA 3절 2번)을 셈으로 넘을 수 없다(가장 작은 p 1/2001 × 700 = 0.35) — W8 참고 분석을 볼 것.',
             '2차를 원장에 더하면 가짓수 보정이 그만큼 엄해진다.']
    if quick: notes.append('시험용(quick) 결과 — 방아쇠 3개·겹침 2·채점 2, 상태는 해 3개·가짜 40번.')
    meta = {'n_tested': n_tested, 'families': fam, 'm_fixed': m_fixed, 'm_wf': m_wf, 'not_included': list(NOT_INCLUDED), 'parts_failed': [], 'notes': notes,
            'tables': names, 'summary_md': '\n'.join(md) + '\n', 'tables_csv': tables_csv}
    return cands, meta


def years_wf(quick):
    """고르는 절차의 해: 2016~2026 전부(quick 이어도 같음 — 상태를 쓰지 않으므로)."""
    return [y for y, _ in C.wf_splits()]


def main():
    a = C.parse_part(); N = n_parts()
    if a['nparts']: print(N); return
    if a['part']:
        i, n = a['part']; C.save_part(TRACK, i, n, run_part(i, n, quick=a['quick'])); print(f'조각 {i}/{n} 저장'); return
    if a['merge']:
        cands, meta = merge(C.load_parts(TRACK, N), quick=a['quick'])
        od = os.path.join(C.track_dir(TRACK), 'out'); os.makedirs(os.path.join(od, 'tables'), exist_ok=True)
        for nm, txt in meta.pop('tables_csv').items(): open(os.path.join(od, 'tables', nm), 'w', encoding='utf-8').write(txt)
        open(os.path.join(od, 'summary.md'), 'w', encoding='utf-8').write(meta.pop('summary_md'))
        C.save_result(TRACK, cands, meta); print(f"merge 끝: 후보 {len(cands)}개 · 시험 {meta['n_tested']}가지 · wf 절차 {meta['m_wf']}개"); return
    print('사용: python run.py --nparts | --part i/n | --merge [--quick]')


if __name__ == '__main__':
    main()
