# -*- coding: utf-8 -*-
"""W4 변동성 꺾임 방아쇠만 따로(상태 없이) — SPEC.md 그대로 구현(돌린 뒤 고치지 않는다). 오름 방향만.

격자: 크기 문턱 7 × 자리 문턱 6 × 보유일 3 = 126칸(kind='fixed').  방아쇠 정의는 T2 의 T8 과 같다(문턱만 격자로).
절차: 미리 정한 칸(5%·80) 그대로 3 + 해마다 그 전 자료로 칸을 고르는 절차 16 = 19개(kind='wf').
조각 1개 = 격자 칸(크기 × 자리)의 조건일 표. merge = 솎기 → 해마다 고르기 → 후보·표.
명령: python run.py --nparts | --part i/n | --merge  (+ --quick)
"""
import io
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE))
import sa_common as C   # noqa: E402

TRACK = 'w4'
ROOT = '변동성 꺾임'
SIZES = [0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.10]
PLACES = [None, 50, 60, 70, 80, 90]
HOLDS = [3, 5, 10]
Q_SIZES = [0.05, 0.07]; Q_PLACES = [None, 80]; Q_HOLDS = [3, 5]
PRE = (0.05, 80)                                                    # T2 가 미리 정했던 칸
CRITS = ['hit', 'lb']
TOPS = [1, 3]
Y0 = C.START.year
NOT_INCLUDED = ['내림 방향(변동성 급등 → 하락)과 낮은 자리에서 급등 꼴',
                '보유일 없는 채점(±5% 먼저 닿기)과 보유일 1·2·7·20일',
                '이틀 누적 하락(2일 합 −S)·VKOSPI 5일 변화 같은 다른 크기 재는 법, 자리 창 120·500일',
                '대표 IV(V1_대표IV)·VIX 로 바꾼 같은 방아쇠',
                '신호 뒤 하루 늦춤, 직전 5일 안 첫 신호만',
                '고르는 절차의 다른 꼴(아무 날 대비 차이로 고르기, 상위 5칸, 2칸 이상 함께 켜질 때만)']


def _grid(quick):
    return (Q_SIZES, Q_PLACES, Q_HOLDS) if quick else (SIZES, PLACES, HOLDS)


def _pname(p): return 'none' if p is None else str(int(p))
def _pko(p): return '자리 조건 없음' if p is None else f'자리 {int(p)} 이상'
def cell_id(s, p, h): return f'G_s{int(round(s * 100)):02d}_p{_pname(p)}_h{h}'


def cell_desc(s, p, h):
    where = 'VKOSPI 가' if p is None else f'VKOSPI 가 높은 자리(전날 값이 지난 250일 가운데 {int(p)} 이상)에서'
    return f'상태 없이 변동성 꺾임만: {where} 하루 {s * 100:g}% 이상 하락 → 다음 날 시가 매수 → {h}일째 종가 매도'


def masks(D, sizes, places):
    """격자 칸(크기 × 자리)의 조건일 표 [칸, 날]. T2 의 T8 과 같은 계산(t2/run.py triggers 의 T[8])에 문턱만 바꿈."""
    X = D.X
    for col in ('V1_VKOSPI', 'M_VKOSPI'):
        if col not in X.columns: raise RuntimeError(f'고정 자료에 {col} 열이 없음 — 멈춤(추정하지 않음)')
    v = X['V1_VKOSPI'].where(X['V1_VKOSPI'].notna(), X['M_VKOSPI'])
    if int(v.notna().sum()) < 1000: raise RuntimeError('VKOSPI 값이 1,000일 미만 — 자료를 못 읽은 것으로 보고 멈춤')
    vr = (v.rolling(250, min_periods=120).rank(pct=True) * 100).shift(1).values; v = v.values; v1 = np.r_[np.nan, v[:-1]]
    live = np.asarray(D.td >= C.START); cells = [(s, p) for s in sizes for p in places]; M = np.zeros((len(cells), D.n), dtype=bool)
    with np.errstate(invalid='ignore', divide='ignore'):
        chg = v / v1 - 1
        for i, (s, p) in enumerate(cells):
            m = chg <= -s
            if p is not None: m = m & (vr >= p)
            M[i] = np.nan_to_num(np.asarray(m, float)).astype(bool) & live
    return cells, M


# ------------------------------------------------------------------ 약속된 함수
def n_parts():
    return 1


def run_part(i, n, quick=False):
    D = C.Data(); sizes, places, _ = _grid(quick); cells, M = masks(D, sizes, places)
    return {'quick': bool(quick), 'cells': cells, 'M': np.packbits(M, axis=1), 'n': D.n, 'nsig': M.sum(1).astype(int)}


def _nmin(Y): return max(12, int(round(35 * (Y - Y0) / 17)))


def _md(df):
    out = ['| ' + ' | '.join(map(str, df.columns)) + ' |', '|' + '---|' * len(df.columns)]
    return out + ['| ' + ' | '.join(str(v) for v in r) + ' |' for r in df.values.tolist()]


def _pc(x): return '–' if x is None or (isinstance(x, float) and not np.isfinite(x)) else f'{100 * x:.1f}%'


def merge(parts, quick=False):
    parts = list(parts or [])
    if not parts or any(p is None for p in parts): raise RuntimeError('W4 조각 결과가 없음 — 합치지 않고 멈춤')
    P = parts[0]
    if bool(P.get('quick')) != bool(quick): raise RuntimeError('W4 조각이 quick/전체 가운데 다른 쪽 결과임 — 멈춤')
    D = C.Data(); n = D.n; sizes, places, holds = _grid(quick)
    cells = [(s, p) for s in sizes for p in places]
    if [tuple(x) for x in P['cells']] != cells or P['n'] != n: raise RuntimeError('W4 조각의 격자·날 수가 SPEC 과 다름 — 멈춤')
    M = np.unpackbits(P['M'], axis=1)[:, :n].astype(bool)
    years = [y for y, _ in C.wf_splits()]
    # ---- 격자 칸(규칙) = 칸 × 보유일. 순서 = 크기 → 자리 → 보유일(칸 번호)
    R = {h: D.fwd(h) for h in holds}
    rules = []
    for ci, (s, p) in enumerate(cells):
        pos = np.flatnonzero(M[ci])
        for h in holds:
            ind = D.thin_pos(pos, h); r = R[h][ind]; ok = np.isfinite(r); ind = ind[ok]; hit = r[ok] > 0
            rules.append({'s': s, 'p': p, 'h': h, 'pos': pos, 'ind': ind, 'hit': hit, 'ey': D.year[ind + h]})
    nr = len(rules)

    cands = []; rows = []
    # ---- fixed 126칸
    for j, r in enumerate(rules):
        s, p, h = r['s'], r['p'], r['h']; tr = D.trades_from_pos(r['pos'], h)
        c = {'id': cell_id(s, p, h), 'family': _pko(p), 'desc': cell_desc(s, p, h), 'direction': 1, 'hold': h, 'kind': 'fixed', 'trades': tr, 'root': ROOT,
             'params': {'size': s, 'place': p, 'hold': h}}
        if (s, p) == PRE: c['wf_of'] = f'WF_pre_h{h}'
        cands.append(c)
        a = C.score(tr, 1, D.K); p1 = C.score(tr, 1, D.K, C.START, pd.Timestamp('2023-12-31')); p2 = C.score(tr, 1, D.K, C.SPLIT, C.END)
        b = C.base_for(D, a['t'], h, 1) if a['n'] else None
        rows.append({'칸': cell_id(s, p, h), '크기 문턱': f'{s * 100:g}%', '자리 문턱': '없음' if p is None else int(p), '보유일': h, '신호 수': int(len(r['pos'])), '독립 거래': a['n'],
                     '적중': (round(a['hit'], 4) if a['n'] >= 10 else None), '앞 거래': p1['n'], '앞 적중': (round(p1['hit'], 4) if p1['n'] >= 10 else None),
                     '뒤 거래': p2['n'], '뒤 적중': (round(p2['hit'], 4) if p2['n'] >= 10 else None), '같은 해 아무 날': (round(b, 4) if b is not None else None),
                     '차이': (round(a['hit'] - b, 4) if (a['n'] >= 10 and b is not None) else None), '수익 합계': round(a['sum'], 4)})
    T_grid = pd.DataFrame(rows)

    # ---- wf 절차
    def year_trades(sel, Y):
        """고른 칸(순위 순 규칙 번호 목록)의 Y 년 신호 → (신호 위치, 보유일). 같은 날 여럿이면 순위가 가장 높은 칸의 보유일."""
        seen = {}
        for j in sel:
            for q in rules[j]['pos'][D.year[rules[j]['pos']] == Y].tolist():
                if q not in seen: seen[q] = rules[j]['h']
        ks = sorted(seen)
        return np.asarray(ks, dtype=int), np.asarray([seen[q] for q in ks], dtype=int)

    def to_trades(s, h):
        ok = s + h < n
        return pd.DataFrame({'signal': D.td[s[ok]], 'exit': D.td[(s + h)[ok]]})

    picks = []; wf = []
    pre_ci = cells.index(PRE) if PRE in cells else None
    if pre_ci is None: raise RuntimeError('미리 정한 칸(5%·80)이 격자에 없음 — 멈춤')
    ywf = np.isin(D.year, years)
    for h in holds:
        pos = np.flatnonzero(M[pre_ci] & ywf)
        wf.append({'id': f'WF_pre_h{h}', 'family': 'wf 절차', 'desc': f'[고르지 않음 — T2 가 미리 정한 칸, 이미 본 숫자] {cell_desc(PRE[0], PRE[1], h)} (2016~2026)', 'direction': 1, 'hold': h, 'kind': 'wf',
                   'trades': D.trades_from_pos(pos, h), 'root': ROOT, 'params': {'proc': 'pre', 'hold': h}})
    scopes = [(f'h{h}', [j for j in range(nr) if rules[j]['h'] == h], h) for h in holds] + [('hall', list(range(nr)), None)]
    crit_ko = {'hit': '적중이 가장 높은', 'lb': '윌슨 하한이 가장 높은'}
    for sc, pool, hfix in scopes:
        stats = {}
        for Y in years:
            st = []
            for j in pool:
                tr_ = rules[j]['ey'] < Y; nn = int(tr_.sum()); kk = int(rules[j]['hit'][tr_].sum())
                if nn >= _nmin(Y): st.append((j, nn, kk, kk / nn, C.wilson(kk, nn)[0]))
            stats[Y] = st
        for cr in CRITS:
            order = {Y: sorted(st, key=lambda x: (-(x[3] if cr == 'hit' else x[4]), -x[1], x[0])) for Y, st in stats.items()}
            for top in TOPS:
                ss = []; hh = []
                for Y in years:
                    sel = [x[0] for x in order[Y][:top]]
                    s_, h_ = year_trades(sel, Y); ss.append(s_); hh.append(h_)
                    row = {'절차': f'WF_{cr}_top{top}_{sc}', '해': Y, '최소 거래 수': _nmin(Y), '거래 수 채운 칸': len(order[Y]), '고른 칸 수': len(sel), '그 해 신호 수': int(len(s_))}
                    for r_, x in enumerate(order[Y][:top], 1):
                        row[f'{r_}위 칸'] = cell_id(rules[x[0]]['s'], rules[x[0]]['p'], rules[x[0]]['h']); row[f'{r_}위 그때까지'] = f'{x[1]}거래 {100 * x[3]:.1f}%(하한 {100 * x[4]:.1f}%)'
                    picks.append(row)
                s_ = np.concatenate(ss) if ss else np.zeros(0, dtype=int); h_ = np.concatenate(hh) if hh else np.zeros(0, dtype=int)
                rng = f'보유 {hfix}일 칸 {len(pool)}개' if hfix else f'보유일까지 함께 칸 {len(pool)}개'
                use = '1위 칸만 사용' if top == 1 else '상위 3칸 가운데 하나라도 켜진 날(같은 날 여럿이면 순위 높은 칸의 보유일)'
                wf.append({'id': f'WF_{cr}_top{top}_{sc}', 'family': 'wf 절차', 'direction': 1, 'hold': hfix, 'kind': 'wf', 'trades': to_trades(s_, h_), 'root': ROOT,
                           'desc': f'상태 없이 변동성 꺾임만: 해마다 그 전 자료에서 {crit_ko[cr]} 칸(크기·자리 문턱, {rng})을 골라 {use} → 다음 날 시가 매수' + (f' → {hfix}일째 종가 매도' if hfix else ' → 그 칸의 보유일째 종가 매도'),
                           'params': {'proc': cr, 'top': top, 'scope': sc}})
    cands = wf + cands
    T_pick = pd.DataFrame(picks)

    # ---- 가짓수
    fam = {_pko(p): len(sizes) * len(holds) for p in places}; fam['wf 절차'] = len(wf)
    n_tested = int(sum(fam.values())); m_fixed = len(cells) * len(holds)
    if not quick and (n_tested != 145 or len(wf) != 19 or m_fixed != 126): raise RuntimeError(f'가짓수가 SPEC 과 다름: {n_tested}·{len(wf)}·{m_fixed}')
    if not cands or n_tested == 0: raise RuntimeError('W4 후보 0개 — 멈춤')
    if not quick and int(M.sum()) == 0: raise RuntimeError('W4 격자 전체에 신호가 하나도 없음 — 자료를 못 읽은 것으로 보고 멈춤')

    # ---- summary.md
    md = ['### W4 변동성 꺾임 방아쇠만 따로(상태 없이): 따로 낸 표' + (' [quick 시험]' if quick else ''), '',
          f'- 격자 {m_fixed}칸(크기 문턱 {len(sizes)} × 자리 문턱 {len(places)} × 보유일 {len(holds)}), 해마다 고르는 절차 {len(wf)}개. 오름 방향만, 상태 조건 없음.',
          '- **아래 격자 표는 전체 기간(2010~) 결과를 보고 고르는 숫자다.** 칸끼리 서로 포함 관계라 많이 닮았다. 믿을 숫자는 판정 표의 다음 해 성적(절차)이다.',
          '- 칸 = 적중(독립 거래 수), 괄호 뒤 ± = 같은 해 아무 날과의 차이. 독립 거래 10건 미만은 %를 적지 않는다. 굵은 칸 = T2 가 미리 정했던 칸(5%·80).', '']
    for h in holds:
        g = T_grid[T_grid['보유일'] == h]
        md += [f'#### 보유 {h}일 — 크기 문턱(세로) × 자리 문턱(가로)', '', '| 하루 하락 | ' + ' | '.join(_pko(p) for p in places) + ' |', '|' + '---|' * (len(places) + 1)]
        for s in sizes:
            line = []
            for p in places:
                r = g[g['칸'] == cell_id(s, p, h)].iloc[0]
                txt = f"{_pc(r['적중'])} ({r['독립 거래']})" + (f" {100 * r['차이']:+.1f}%p" if r['차이'] is not None and np.isfinite(r['차이']) else '')
                line.append(f'**{txt}**' if (s, p) == PRE else txt)
            md.append(f'| {s * 100:g}% 이상 | ' + ' | '.join(line) + ' |')
        md.append('')
    md += ['#### 해마다 고른 칸(1위) — 절차별', '', '고른 칸이 해마다 바뀌는지, 한 칸에 머무는지 본다. 전부는 tables/pick_by_year.csv.', '']
    if len(T_pick):
        top1 = T_pick[T_pick['절차'].str.contains('_top1_')]
        piv = top1.pivot(index='절차', columns='해', values='1위 칸').fillna('–') if '1위 칸' in top1 else pd.DataFrame()
        if len(piv): md += _md(piv.reset_index().rename(columns=str)) + ['']
    names = ['grid_cells.csv', 'pick_by_year.csv']; tables_csv = {}
    for nm, df in zip(names, (T_grid, T_pick)):
        b = io.StringIO(); df.to_csv(b, index=False); tables_csv[nm] = b.getvalue()
    notes = ['W4 는 T2 의 방아쇠 T8(변동성 꺾임)을 상태 없이, 크기·자리 문턱 격자로 본 것이다. 방아쇠 정의는 T2 와 같다.',
             'fixed 126칸은 전체 기간 결과를 보고 고르는 숫자다(칸끼리 포함 관계라 서로 닮음). 믿을 숫자는 wf 절차 19개.',
             "절차 'WF_pre_h3·h5·h10'(5%·80 칸 그대로)은 T2 에서 이미 본 숫자와 같은 규칙이다(3일 129거래 64.3% 대 아무 날 55.0%). 새 시험이 아니라 견줌용.",
             '2차를 원장에 더하면 가짓수 보정이 그만큼 엄해진다.']
    if quick: notes.append('시험용(quick) 결과 — 격자 일부.')
    meta = {'n_tested': n_tested, 'families': fam, 'm_fixed': m_fixed, 'm_wf': len(wf), 'not_included': list(NOT_INCLUDED), 'parts_failed': [], 'notes': notes,
            'tables': names, 'summary_md': '\n'.join(md) + '\n', 'tables_csv': tables_csv}
    return cands, meta


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
