# -*- coding: utf-8 -*-
"""combo_track.py — 매수 신호 7개 × 매도 신호 7개 = 49개 조합의 성적을 매일 다시 계산하고,
   '최근 성적으로 1위를 고르는 규칙' 자체가 과거에 통했는지 걸어가며 검증한다(2016~).

   조합 규칙: 매수 신호가 '시작'된 다음 날 종가에 사고, 매도 신호가 '시작'된 다음 날 종가에 판다(그 사이 현금). 왕복 비용 0.3%.
   선택 규칙(미리 고정, 뒤에 바꾸지 않음): 매월 첫 거래일에 지난 250거래일 수익률 1위 조합을 뽑아 그 달 동안 그 조합대로 매매한다.
      닫힌 거래가 2건 미만인 조합은 후보에서 뺀다. 동점이면 거래당 적중률이 높은 쪽.
   묶음 규칙(2026-11-15 추가 — 지금의 기준 규칙. 위 250일 1위는 비교용으로 계속 계산한다):
      매월 첫 거래일에 지난 ENS_WIN(750)거래일 수익률 상위 ENS_K(5)개 조합을 뽑아 똑같이 나눠 든다(5개 중 3개가 보유면 60% 보유).
      후보 조건·동점 처리는 위와 같다. 2016~17년은 자료가 2015년부터라 창이 750일보다 짧다(있는 만큼만 본다).
      근거: 2026-11-15 신호 재검증 — 창 20~120일은 다음 달 순위 예측력이 우연 수준, 250일 1위는 2026년을 빼면 무작위 선택과 비슷,
      500~750일 창 + 상위 3~5개 묶음이 낙폭이 작고 코스피를 이긴 해가 많았다. 창·묶음 크기별 성적은 combo_now.csv 의 ens_grid 에 매번 다시 적는다.
   출력:
     combo_table.csv  — 49개 조합 × (2026 수익·적중률·거래, 최근 60/120/250일 수익·적중률·최대낙폭, 2015~ 누적, 지금 상태, 현재 순위)
     combo_select.csv — 걸어가며 검증: 달마다 뽑힌 조합과 그 달 실제 수익(선택 규칙·코스피 보유·고정 조합 비교)
     combo_wf.csv     — 연도별: 묶음 규칙(ens_ret) vs 250일 1위 규칙(walkforward_ret) vs 코스피 보유 vs 고정 조합(2015~24 누적 1위) 수익
     combo_now.csv    — 지금 1위 조합·뽑힌 날·뽑힌 뒤 성적·성적 저하 경고 + 묶음(ens_*: 구성·보유 비중·바뀐 조합·누적 성적·민감도)(한 줄)
   VKOSPI 가 들어가는 신호는 다음 날 08:31 에 확정되므로 '다음 날 종가 체결'이 실제 지연과 맞는다.
"""
import itertools
import numpy as np, pandas as pd

COST = 0.003          # 왕복
WIN = 250             # 선택 창(거래일)
MIN_TRADES = 2        # 창 안 닫힌 거래 최소
WF_START = '2016-01-01'
ENS_WIN = 750         # 묶음 규칙: 선택 창(거래일)
ENS_K = 5             # 묶음 규칙: 상위 몇 개를 똑같이 나눠 드나
ENS_GRID = [(250, 1), (250, 3), (500, 3), (500, 5), (750, 3), (750, 5)]   # 민감도 표(창, 묶음 크기) — 화면에 함께 보여 준다

def _starts(s): return (s & ~s.shift(1, fill_value=False)).values

def signal_sets(D, q_daily=None):
    import reproduce as R
    B, S = {}, {}
    for k, v in R.signal_series(D).items(): (B if k[0] == '매수' else S)[k[1]] = v.fillna(False).astype(bool)
    for k, v in R.buy3_series(D).items(): B[k[1]] = v.fillna(False).astype(bool)
    for k, v in R.sell3_series(D).items(): S[k[1]] = v.fillna(False).astype(bool)
    idx = D['K'].close.index
    if q_daily is not None and len(q_daily):
        qt = q_daily.set_index(pd.to_datetime(q_daily['date']))['trade'].reindex(idx)
        B['정밀검증 진입'] = (qt == 'enter'); S['정밀검증 청산'] = (qt == 'exit')
    return B, S

def positions(c, bs, ss):
    """날짜별 보유(1)/현금(0) — 신호 시작 다음 날 종가부터 적용. 거래 목록(진입 i, 청산 i, 수익률)도 반환."""
    n = len(c); pos = np.zeros(n, dtype=np.int8); bst = _starts(bs); sst = _starts(ss)
    held = False; ei = None; tr = []
    for i in range(n - 1):
        if not held and bst[i]: held = True; ei = i + 1
        elif held and sst[i]:
            held = False; xi = i + 1; tr.append((ei, xi, c[xi] * (1 - COST / 2) / (c[ei] * (1 + COST / 2)) - 1))
        if held and ei is not None and i + 1 >= ei: pos[i + 1] = 1
    return pos, tr, (ei if held else None)

def daily_ret(c, pos, tr):
    """일별 전략 수익률: 보유일엔 코스피 일수익, 체결일에 비용 반영."""
    r = np.zeros(len(c)); cr = np.diff(c) / c[:-1]
    r[1:] = cr * pos[:-1]      # 전날 보유였으면 오늘 수익
    # 진입 i: pos[i]=1 이지만 i 일 수익은 없음(종가 매수) → pos[i-1]=0 이라 이미 0. 비용: 진입·청산일에 반씩
    for ei, xi, _ in tr: r[ei] -= COST / 2; r[xi] -= COST / 2
    return r

def run(D, q_daily=None):
    c_ser = D['K'].close; idx = c_ser.index; c = c_ser.values.astype(float); n = len(c)
    B, S = signal_sets(D, q_daily)
    combos = list(itertools.product(B, S)); P = {}; TR = {}; R_ = {}; OPEN = {}
    for b, s in combos:
        pos, tr, oi = positions(c, B[b], S[s]); P[(b, s)] = pos; TR[(b, s)] = tr; R_[(b, s)] = daily_ret(c, pos, tr); OPEN[(b, s)] = oi
    kr = np.zeros(n); kr[1:] = np.diff(c) / c[:-1]
    def window_stats(key, a, b_):
        """[a, b_) 구간: 수익, 닫힌 거래 수·적중, 최대낙폭"""
        r = R_[key][a:b_]; eq = np.cumprod(1 + r); tot = eq[-1] - 1 if len(eq) else 0.0
        mdd = float((eq / np.maximum.accumulate(eq) - 1).min()) if len(eq) else 0.0
        tr = [t for t in TR[key] if a <= t[1] < b_]; w = sum(t[2] > 0 for t in tr)
        return tot, len(tr), w, mdd
    # ---- 표: 49개 조합
    y26 = int(np.searchsorted(idx, pd.Timestamp('2026-01-01'))); y25 = int(np.searchsorted(idx, pd.Timestamp('2025-01-01'))); y15 = int(np.searchsorted(idx, pd.Timestamp('2015-01-01')))
    rows = []
    for key in combos:
        b, s = key; t26, n26, w26, m26 = window_stats(key, y26, n); t25, n25, w25, _ = window_stats(key, y25, y26); tall, nall, wall, mall = window_stats(key, y15, y26)
        r60, n60, w60, m60 = window_stats(key, n - 60, n); r120, n120, w120, m120 = window_stats(key, n - 120, n); r250, n250, w250, m250 = window_stats(key, n - 250, n)
        rL, nL, wL, mL = window_stats(key, max(y15, n - ENS_WIN), n)
        oi = OPEN[key]
        rows.append({'buy': b, 'sell': s, 'combo': f'{b} → {s}',
                     'ret_2026': round(t26 * 100, 1), 'trades_2026': n26, 'wins_2026': w26, 'hit_2026': round(w26 / n26 * 100) if n26 else np.nan, 'mdd_2026': round(m26 * 100, 1),
                     'ret_2025': round(t25 * 100, 1), 'ret_2015_25': round(tall * 100, 1), 'trades_2015_25': nall, 'hit_2015_25': round(wall / nall * 100) if nall else np.nan, 'mdd_2015_25': round(mall * 100, 1),
                     'ret_60': round(r60 * 100, 1), 'ret_120': round(r120 * 100, 1), 'ret_250': round(r250 * 100, 1), 'trades_250': n250, 'hit_250': round(w250 / n250 * 100) if n250 else np.nan, 'mdd_250': round(m250 * 100, 1),
                     'ret_long': round(rL * 100, 1), 'trades_long': nL, 'hit_long': round(wL / nL * 100) if nL else np.nan, 'mdd_long': round(mL * 100, 1),
                     'state': '보유' if oi is not None else '현금', 'open_since': (idx[oi].strftime('%Y-%m-%d') if oi is not None else ''), 'open_ret': (round((c[-1] / c[oi] - 1) * 100, 1) if oi is not None else np.nan)})
    T = pd.DataFrame(rows)
    T['kospi_2026'] = round((c[-1] / c[y26 - 1] - 1) * 100, 1); T['kospi_250'] = round((c[-1] / c[n - 251] - 1) * 100, 1)
    T['eligible'] = T['trades_250'] >= MIN_TRADES
    T = T.sort_values(['eligible', 'ret_250', 'hit_250'], ascending=[False, False, False]).reset_index(drop=True); T['rank_250'] = np.where(T['eligible'], np.arange(1, len(T) + 1), np.nan)
    T['rank_2026'] = T['ret_2026'].rank(ascending=False, method='min').astype(int)
    T['eligible_long'] = T['trades_long'] >= MIN_TRADES; T['long_win'] = ENS_WIN
    _o = T.sort_values(['eligible_long', 'ret_long', 'hit_long'], ascending=[False, False, False], kind='mergesort').index
    T['rank_long'] = np.nan; T.loc[_o, 'rank_long'] = np.arange(1, len(T) + 1); T.loc[~T['eligible_long'], 'rank_long'] = np.nan
    T['date'] = idx[-1].strftime('%Y-%m-%d')
    # ---- 걸어가며 검증: 매월 첫 거래일에 지난 WIN 일 수익 1위(닫힌 거래 ≥ MIN_TRADES) 선택
    months = pd.Series(idx).dt.to_period('M'); first_days = [i for i in range(1, n) if months[i] != months[i - 1] and idx[i] >= pd.Timestamp(WF_START)]
    sel_rows = []; wf_r = np.zeros(n); chosen_prev = None
    for k, i in enumerate(first_days):
        j = first_days[k + 1] if k + 1 < len(first_days) else n
        a = i - WIN
        if a < y15: continue
        best = None
        for key in combos:
            tot, ntr, w, _ = window_stats(key, a, i)
            if ntr < MIN_TRADES: continue
            sc = (tot, w / ntr)
            if best is None or sc > best[0]: best = (sc, key, ntr, w)
        if best is None: continue
        key = best[1]
        # 그 달 실제 수익: 조합이 바뀌면 월초 첫날(i)은 전 조합 포지션으로 지나고, 그날 종가에 새 조합 포지션으로 바꾼다(바꾸는 쪽에 비용 반)
        rm = R_[key][i:j].copy()
        if chosen_prev is not None and key != chosen_prev:
            rm[0] = kr[i] * P[chosen_prev][i - 1]
            if P[chosen_prev][i - 1] != P[key][i]: rm[0] -= COST / 2
            if P[key][i] == 1 and P[key][i - 1] == 0 and len(rm) > 1: rm[1] = R_[key][i + 1]  # 새 조합이 i 일에 진입한 경우 그대로
        wf_r[i:j] = rm; mret = float(np.prod(1 + rm) - 1); kret = float(c[j - 1] / c[i - 1] - 1)
        sel_rows.append({'month': str(months[i]), 'from': idx[i].strftime('%Y-%m-%d'), 'to': idx[j - 1].strftime('%Y-%m-%d'), 'chosen': f'{key[0]} → {key[1]}',
                         'win_ret_250': round(best[0][0] * 100, 1), 'win_trades': best[2], 'win_hit': round(best[3] / best[2] * 100), 'changed': int(key != chosen_prev),
                         'month_ret': round(mret * 100, 2), 'kospi_month_ret': round(kret * 100, 2), 'pos_start': int(P[key][i - 1])})
        chosen_prev = key
    SEL = pd.DataFrame(sel_rows)
    # ---- 묶음 규칙(2026-11-15): 매월 첫 거래일에 지난 W 거래일 수익 상위 K 개(닫힌 거래 ≥ MIN_TRADES, 동점은 적중률 → 조합 나열 순서)를 뽑아 똑같이 나눠 든다
    def rank_window(i, W):
        a = max(y15, i - W); out = []
        for key in combos:
            tot, ntr, w, _ = window_stats(key, a, i)
            if ntr >= MIN_TRADES: out.append(((tot, w / ntr), key, ntr, w))
        out.sort(key=lambda t: t[0], reverse=True)
        return out
    def ens_run(W, K):
        """e[i] = i 일 종가 뒤 보유 비중(뽑힌 조합 중 보유 상태인 비율), r = 일별 수익(비중이 바뀐 만큼 비용 반씩), picks = [(월초 i, 뽑힌 목록)]"""
        e = np.zeros(n); r = np.zeros(n); picks = []; cur = None; fset = set(first_days)
        if not first_days: return e, r, picks
        for i in range(first_days[0], n):
            if i in fset:
                top = rank_window(i, W)[:K]
                if top: cur = [t[1] for t in top]; picks.append((i, top))
            if cur is not None: e[i] = float(np.mean([P[k][i] for k in cur]))
        r[1:] = kr[1:] * e[:-1] - COST / 2 * np.abs(np.diff(e)); r[:first_days[0] + 1] = 0
        return e, r, picks
    def perf(r, a, b_=None):
        x = r[a:b_]; eq = np.cumprod(1 + x)
        return (float(eq[-1] - 1) if len(eq) else 0.0), (float((eq / np.maximum.accumulate(eq) - 1).min()) if len(eq) else 0.0)
    ens_e, ens_r, ens_picks = ens_run(ENS_WIN, ENS_K)
    name = lambda k: f'{k[0]} → {k[1]}'
    ens_sel = []; prev_set = None
    for q, (i, top) in enumerate(ens_picks):
        j = ens_picks[q + 1][0] if q + 1 < len(ens_picks) else n
        cur_set = [t[1] for t in top]
        ens_sel.append({'month': str(months[i]), 'ens_from': idx[i].strftime('%Y-%m-%d'), 'ens_members': ' | '.join(name(k) for k in cur_set),
                        'ens_changed': (len(set(cur_set) - set(prev_set)) if prev_set is not None else len(cur_set)), 'ens_hold_start_pct': round(float(ens_e[i]) * 100),
                        'ens_month_ret': round((float(np.prod(1 + ens_r[i + 1:j + 1])) - 1) * 100, 2)})   # 그 달 구성으로 번 수익: 선정일 종가 ~ 다음 선정일 종가
        prev_set = cur_set
    ENS_SEL = pd.DataFrame(ens_sel)
    # 고정 조합 비교: 2015~2024 누적 1위(2025~26 를 빼고 고른다 — 실사용 성적과 분리)
    y_fix_end = y25
    fixed = max(combos, key=lambda k: window_stats(k, y15, y_fix_end)[0]); fixed_name = f'{fixed[0]} → {fixed[1]}'
    # 연도별 비교
    years = sorted(set(idx[idx >= pd.Timestamp(WF_START)].year))
    yrows = []
    wf_start_i = first_days[0] if first_days else n
    for y in years:
        a = int(np.searchsorted(idx, pd.Timestamp(f'{y}-01-01'))); b_ = int(np.searchsorted(idx, pd.Timestamp(f'{y + 1}-01-01'))); a = max(a, wf_start_i)
        if a >= b_: continue
        ys = SEL[SEL['month'].str.startswith(str(y))]; es = ENS_SEL[ENS_SEL['month'].str.startswith(str(y))] if len(ENS_SEL) else ENS_SEL
        yrows.append({'year': y, 'ens_ret': round(perf(ens_r, a, b_)[0] * 100, 1), 'ens_hold_avg': round(float(ens_e[a:b_].mean()) * 100), 'ens_changes': int(es['ens_changed'].sum()) if len(es) else 0, 'walkforward_ret': round((np.prod(1 + wf_r[a:b_]) - 1) * 100, 1), 'kospi_ret': round((c[b_ - 1] / c[a - 1] - 1) * 100, 1),
                      'fixed_ret': round((np.prod(1 + R_[fixed][a:b_]) - 1) * 100, 1), 'fixed_combo': fixed_name,
                      'changes': int(ys['changed'].sum()) if len(ys) else 0, 'months': len(ys), 'top_combo': (ys['chosen'].mode().iloc[0] if len(ys) else '')})
    WF = pd.DataFrame(yrows)
    a0 = wf_start_i; tot = lambda r: round((np.prod(1 + r[a0:]) - 1) * 100, 1)
    WF = pd.concat([WF, pd.DataFrame([{'year': '합계', 'ens_ret': tot(ens_r), 'ens_hold_avg': round(float(ens_e[a0:].mean()) * 100), 'ens_changes': int(ENS_SEL['ens_changed'].sum()) if len(ENS_SEL) else 0, 'walkforward_ret': tot(wf_r), 'kospi_ret': round((c[-1] / c[a0 - 1] - 1) * 100, 1), 'fixed_ret': tot(R_[fixed]), 'fixed_combo': fixed_name,
                                        'changes': int(SEL['changed'].sum()) if len(SEL) else 0, 'months': len(SEL), 'top_combo': (SEL['chosen'].mode().iloc[0] if len(SEL) else '')}])], ignore_index=True)
    # 2025~26 실사용 구간(선택 규칙·고정 조합 모두 2015~24 로 설계)
    a25 = y25
    WF = pd.concat([WF, pd.DataFrame([{'year': '2025~26 실사용', 'ens_ret': round(perf(ens_r, a25)[0] * 100, 1), 'ens_hold_avg': round(float(ens_e[a25:].mean()) * 100),
                                        'ens_changes': int(ENS_SEL[ENS_SEL['month'] >= '2025-01']['ens_changed'].sum()) if len(ENS_SEL) else 0, 'walkforward_ret': round((np.prod(1 + wf_r[a25:]) - 1) * 100, 1), 'kospi_ret': round((c[-1] / c[a25 - 1] - 1) * 100, 1),
                                        'fixed_ret': round((np.prod(1 + R_[fixed][a25:]) - 1) * 100, 1), 'fixed_combo': fixed_name, 'changes': int(SEL[SEL['month'] >= '2025-01']['changed'].sum()) if len(SEL) else 0,
                                        'months': int((SEL['month'] >= '2025-01').sum()) if len(SEL) else 0, 'top_combo': ''}])], ignore_index=True)
    # ---- 지금 1위·감시
    now = {}
    if len(SEL):
        last = SEL.iloc[-1]; key = tuple(last['chosen'].split(' → ')); since_i = None
        for r_ in SEL.iloc[::-1].itertuples():
            if r_.chosen == last['chosen']: since_i = int(np.searchsorted(idx, pd.Timestamp(r_._2)))
            else: break
        rs = R_[key][since_i:]; since_ret = float(np.prod(1 + rs) - 1); ks = float(c[-1] / c[since_i - 1] - 1)
        tr_since = [t for t in TR[key] if t[1] >= since_i]; w_since = sum(t[2] > 0 for t in tr_since)
        hit_hist = T.loc[T['combo'] == last['chosen'], 'hit_2015_25'].iloc[0]
        # 경고: 뽑힌 뒤 닫힌 거래 2건 이상이고 적중률이 2015~25 적중률보다 15%p 넘게 낮거나, 뽑힌 뒤 수익이 코스피보다 10%p 넘게 뒤질 때
        warn = []
        if len(tr_since) >= 2 and pd.notna(hit_hist) and (w_since / len(tr_since) * 100) < hit_hist - 15: warn.append(f'적중률 {w_since}/{len(tr_since)} — 과거 {hit_hist:.0f}%보다 15%p 넘게 낮음')
        if (since_ret - ks) * 100 < -10: warn.append(f'뽑힌 뒤 수익 {since_ret*100:+.1f}% — 코스피 {ks*100:+.1f}%보다 10%p 넘게 뒤짐')
        now = {'date': idx[-1].strftime('%Y-%m-%d'), 'top_combo': last['chosen'], 'chosen_since': idx[since_i].strftime('%Y-%m-%d'), 'win_ret_250': last['win_ret_250'], 'win_trades': last['win_trades'], 'win_hit': last['win_hit'],
               'since_ret': round(since_ret * 100, 1), 'since_kospi': round(ks * 100, 1), 'since_trades': len(tr_since), 'since_wins': w_since, 'hit_2015_25': hit_hist,
               'state': T.loc[T['combo'] == last['chosen'], 'state'].iloc[0], 'warn': ' / '.join(warn) if warn else '', 'rule': f'매월 첫 거래일, 지난 {WIN}거래일 수익 1위(닫힌 거래 {MIN_TRADES}건 이상), 동점은 적중률', 'fixed_combo': fixed_name,
               'next_select': (pd.Timestamp(idx[-1]) + pd.offsets.MonthBegin(1)).strftime('%Y-%m')}
    # ---- 묶음 규칙의 지금 상태(기준 규칙) — combo_now 에 ens_* 칸으로 덧붙인다
    T['in_ens'] = 0; T['ens_rank'] = np.nan
    if ens_picks:
        li, ltop = ens_picks[-1]; members = [t[1] for t in ltop]; si = li; prev_members = None
        for q in range(len(ens_picks) - 1, 0, -1):      # 지금 구성이 처음 뽑힌 달(구성이 그대로면 거슬러 올라간다)
            if set(t[1] for t in ens_picks[q - 1][1]) == set(members): si = ens_picks[q - 1][0]
            else: prev_members = [t[1] for t in ens_picks[q - 1][1]]; break
        states = ['보유' if OPEN[k] is not None else '현금' for k in members]; hold_n = sum(x == '보유' for x in states)
        e_tot, e_mdd = perf(ens_r, a0); o_tot, o_mdd = perf(wf_r, a0)
        def beat(r):   # 코스피를 이긴 해 수
            b = t = 0
            for y in years:
                ya = max(int(np.searchsorted(idx, pd.Timestamp(f'{y}-01-01'))), wf_start_i); yb = int(np.searchsorted(idx, pd.Timestamp(f'{y + 1}-01-01')))
                if ya >= yb: continue
                t += 1; b += int(perf(r, ya, yb)[0] > c[yb - 1] / c[ya - 1] - 1)
            return b, t
        eb, et = beat(ens_r); ob, _ = beat(wf_r)
        grid = []
        for W, K in ENS_GRID:
            gr = wf_r if (W, K) == (WIN, 1) else (ens_r if (W, K) == (ENS_WIN, ENS_K) else ens_run(W, K)[1])
            gt, gm = perf(gr, a0); gb, _ = beat(gr)
            grid.append(f"{W}일·{K}개 {gt * 100:+,.0f}%(낙폭 {gm * 100:.0f}%, {gb}해)".replace('-', '−'))
        for q, k in enumerate(members): T.loc[T['combo'] == name(k), ['in_ens', 'ens_rank']] = [1, q + 1]
        ens_now = {'ens_win': ENS_WIN, 'ens_k': ENS_K, 'ens_rule': f'매월 첫 거래일, 지난 {ENS_WIN}거래일 수익 상위 {ENS_K}개(닫힌 거래 {MIN_TRADES}건 이상, 동점은 적중률)를 똑같이 나눠 보유',
                   'ens_members': ' | '.join(name(k) for k in members), 'ens_states': ' | '.join(states), 'ens_hold_n': hold_n, 'ens_n': len(members), 'ens_hold_pct': round(hold_n / len(members) * 100),
                   'ens_selected': idx[li].strftime('%Y-%m-%d'), 'ens_since': idx[si].strftime('%Y-%m-%d'),
                   'ens_in': ' | '.join(name(k) for k in members if prev_members is not None and k not in prev_members), 'ens_out': ' | '.join(name(k) for k in (prev_members or []) if k not in members),
                   'ens_win_ret': ' | '.join(f"{t[0][0] * 100:+.0f}%" for t in ltop).replace('-', '−'),
                   'ens_since_ret': round((float(np.prod(1 + ens_r[si + 1:])) - 1) * 100, 1), 'ens_since_kospi': round((c[-1] / c[si] - 1) * 100, 1),
                   'ens_total': round(e_tot * 100, 1), 'ens_mdd': round(e_mdd * 100, 1), 'ens_beat': eb, 'ens_years': et, 'old_total': round(o_tot * 100, 1), 'old_mdd': round(o_mdd * 100, 1), 'old_beat': ob,
                   'kospi_total': round((c[-1] / c[a0 - 1] - 1) * 100, 1), 'ens_grid': ' | '.join(grid)}
        if not now: now = {'date': idx[-1].strftime('%Y-%m-%d'), 'next_select': (pd.Timestamp(idx[-1]) + pd.offsets.MonthBegin(1)).strftime('%Y-%m')}
        now.update(ens_now)
    T = T.sort_values(['in_ens', 'ens_rank', 'eligible_long', 'ret_long', 'hit_long'], ascending=[False, True, False, False, False], kind='mergesort').reset_index(drop=True)   # 묶음에 든 조합 먼저, 그다음 긴 창 순위
    NOW = pd.DataFrame([now]) if now else pd.DataFrame()
    SEL_OUT = SEL.merge(ENS_SEL, on='month', how='outer').sort_values('month').reset_index(drop=True) if len(ENS_SEL) and len(SEL) else (ENS_SEL if len(ENS_SEL) else SEL)
    for k in ('win_trades', 'win_hit', 'changed', 'pos_start', 'ens_changed', 'ens_hold_start_pct'):   # 한쪽 규칙만 있는 달(빈칸) 때문에 정수 열이 소수로 바뀌지 않게
        if k in SEL_OUT.columns: SEL_OUT[k] = SEL_OUT[k].astype('Int64')
    return {'combo_table': T, 'combo_select': SEL_OUT, 'combo_wf': WF, 'combo_now': NOW}

if __name__ == '__main__':
    import argparse, glob, os, sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import reproduce as R
    ap = argparse.ArgumentParser(); ap.add_argument('xlsx'); ap.add_argument('out'); a = ap.parse_args()
    D = R.load(a.xlsx); qd = pd.read_csv(os.path.join(a.out, 'q_daily.csv')) if os.path.exists(os.path.join(a.out, 'q_daily.csv')) else None
    outs = run(D, qd)
    for k, v in outs.items(): v.to_csv(os.path.join(a.out, k + '.csv'), index=False)
    pd.set_option('display.width', 250)
    print(outs['combo_wf'].to_string(index=False)); print(outs['combo_now'].T.to_string())
