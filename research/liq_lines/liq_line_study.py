# -*- coding: utf-8 -*-
"""liq_line_study.py — 반대매매(강제 청산) 기준선 후보를 같은 잣대로 비교한다.

자료(main 의 out/): credit.csv(코스피 신용잔고 kospi_jo, 조원), market_daily.csv(코스피 종가), liq_daily.csv(미수 반대매매 금액·비중).
신호: 그날(t) 종가가 기준선 아래. 기준선은 t-1 까지의 정보로만 계산(신용은 하루 늦게 공시 → t-1 까지).
결과(신호 다음 날부터):
  신용 물결   = 신용잔고 t → t+3 변화 ≤ -2%      (심한 물결 ≤ -3%)
  미수 물결   = t+1~t+3 미수 반대매매 비중 최고 ≥ 직전 120일 90% 분위
                (비중 수준이 2024년부터 크게 달라져 절대값 대신 최근 분포 대비로 봄)
평가: 정밀도(선 아래인 날 뒤 물결 비율), 재현율(물결 직전일 가운데 선 아래였던 비율), F1, 3일 신용 변화 평균, 이탈 구간 수, 해마다.
선택 규칙(미리 정함): 개발 구간 2016~2022 에서 이탈 일수 15 이상·이탈 구간 8 이상인 후보 가운데
  신용 F1 순위와 미수 F1 순위의 평균이 가장 좋은 것. 확인 구간 2023~2026 은 고르는 데 쓰지 않는다.
후보:
  prevlow  직전 N일 최저 종가 × (1+δ)          N 5·10·20·40·60·120·250, δ +2…-10%
  ddhigh   직전 N일 최고 종가 × (1-D)          N 20·60·120·250, D 5…45%
  avgcost  신용 평균 매수 지수 × 담보비율 × 대출 비중(대시보드 방식과 같은 계산 + 청산분을 빼는 방식들)
  prq      비례 상환 잔고 분포에서 신용 q% 가 선 밑에 들어가는 지수
  drop     비교용: 하루 -2%·-3% 이상 하락한 날
"""
import heapq
import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, 'data')
OUT = os.path.join(HERE, 'out'); os.makedirs(OUT, exist_ok=True)
DEV = (pd.Timestamp('2016-01-01'), pd.Timestamp('2022-12-31'))
TEST = (pd.Timestamp('2023-01-01'), pd.Timestamp('2099-12-31'))
CW, CW2 = -2.0, -3.0


def load():
    m = pd.read_csv(f'{DATA}/market_daily.csv', usecols=['date', 'kospi']).dropna()
    c = pd.read_csv(f'{DATA}/credit.csv', usecols=['date', 'kospi_jo'])
    l = pd.read_csv(f'{DATA}/liq_daily.csv', usecols=['date', 'liq_eok', 'ratio_pct'])
    for x in (m, c, l):
        x['date'] = pd.to_datetime(x['date'])
    df = m.set_index('date').join(c.set_index('date'), how='left').join(l.set_index('date'), how='left').sort_index()
    return df


def avgcost_lines(df):
    """대시보드 relief.js credit_entry 와 같은 평균 매수 지수(그날 t 는 t-1 까지의 신용·종가만) + 청산분을 빼는 방식들."""
    k = df['kospi'].values; crs = df['kospi_jo'].values; n = len(df)
    ci = np.where(np.isfinite(crs))[0]                      # 신용 값이 있는 날(위치)
    v = crs[ci]; p = k[ci]
    d = np.r_[np.nan, np.diff(v)]
    pos = np.where((d > 0) & np.isfinite(p), d, 0.0)
    P0 = np.cumsum(pos); P1 = np.cumsum(pos * np.where(np.isfinite(p), p, 0.0))
    # 날 t 에서 쓸 수 있는 마지막 신용 위치 J(t): ci 가운데 t 보다 앞선 마지막
    Jt = np.searchsorted(ci, np.arange(n), side='left') - 1
    names = ['recent', 'low250', 'low500', 'primary', 'fifo_tr', 'lifo_tr', 'worst_tr', 'fifo250', 'lifo250', 'worst250', 'prorata_all', 'fifo_all', 'lifo_all']
    E = {nm: np.full(len(ci), np.nan) for nm in names}
    PRQ = {(q, mm): np.full(len(ci), np.nan) for q in (0.1, 0.25, 0.5) for mm in (1.4, 1.3)}

    def inflow(t0, J):
        w = P0[J] - P0[t0]
        return (P1[J] - P1[t0]) / w if w > 1e-12 else np.nan, w

    def lots_from(t0, J, mode):
        L = []          # fifo/lifo: list of [amt, price]; worst: heap of (-price, amt)
        for kk in range(t0 + 1, J + 1):
            dd = v[kk] - v[kk - 1]
            if dd > 0:
                if np.isfinite(p[kk]):
                    if mode == 'worst': heapq.heappush(L, (-p[kk], dd))
                    else: L.append([dd, p[kk]])
            else:
                rem = -dd
                while rem > 1e-12 and L:
                    if mode == 'worst':
                        npx, a = heapq.heappop(L)
                        if a > rem: heapq.heappush(L, (npx, a - rem)); rem = 0
                        else: rem -= a
                    else:
                        i = 0 if mode == 'fifo' else -1
                        if L[i][0] <= rem: rem -= L[i][0]; L.pop(i)
                        else: L[i][0] -= rem; rem = 0
        if mode == 'worst':
            w = sum(a for _, a in L); return (sum(-npx * a for npx, a in L) / w) if w > 1e-12 else np.nan
        w = sum(a for a, _ in L); return (sum(a * px for a, px in L) / w) if w > 1e-12 else np.nan

    # 처음부터 이어지는 잔고(비례·선입·후입)
    amt = []; prc = []; FL = []; LL = []
    for J in range(len(ci)):
        if J == 0:
            if np.isfinite(p[0]):
                amt.append(v[0]); prc.append(p[0]); FL.append([v[0], p[0]]); LL.append([v[0], p[0]])
            continue
        dd = v[J] - v[J - 1]
        if dd > 0:
            if np.isfinite(p[J]):
                amt.append(dd); prc.append(p[J]); FL.append([dd, p[J]]); LL.append([dd, p[J]])
        else:
            rem = -dd; tot = sum(amt)
            if tot > 1e-12:
                f = max(0.0, 1 - rem / tot); amt = [a * f for a in amt]
            for Lx, i in ((FL, 0), (LL, -1)):
                r = rem
                while r > 1e-12 and Lx:
                    if Lx[i][0] <= r: r -= Lx[i][0]; Lx.pop(i)
                    else: Lx[i][0] -= r; r = 0
        A = np.array(amt); Pp = np.array(prc); tot = A.sum()
        if tot > 1e-12:
            E['prorata_all'][J] = (A * Pp).sum() / tot
            for mm in (1.4, 1.3):
                line = Pp * mm * 0.6; o = np.argsort(-line); cum = np.cumsum(A[o])
                for q in (0.1, 0.25, 0.5):
                    PRQ[(q, mm)][J] = line[o][min(len(o) - 1, int(np.searchsorted(cum, q * tot)))]
        for nm, Lx in (('fifo_all', FL), ('lifo_all', LL)):
            w = sum(a for a, _ in Lx); E[nm][J] = sum(a * px for a, px in Lx) / w if w > 1e-12 else np.nan
        # 대시보드와 같은 창(최근 250개 신용 값) — 정점·1년 저점·정점 뒤 최저·2년 저점
        s = max(0, J - 249); pk = s; lo250 = s
        for kk in range(s, J + 1):
            if v[kk] > v[pk]: pk = kk
            if v[kk] <= v[lo250]: lo250 = kk
        tr = pk
        for kk in range(pk, J + 1):
            if v[kk] <= v[tr]: tr = kk
        s5 = max(0, J - 499); lo500 = s5
        for kk in range(s5, J + 1):
            if v[kk] <= v[lo500]: lo500 = kk
        a, wa = inflow(tr, J); b, wb = inflow(lo250, J); b5, wb5 = inflow(lo500, J)
        E['recent'][J], E['low250'][J], E['low500'][J] = a, b, b5
        E['primary'][J] = next((e for e, w in ((a, wa), (b, wb), (b5, wb5)) if np.isfinite(e) and w >= 1), np.nan)
        E['fifo_tr'][J] = lots_from(tr, J, 'fifo'); E['lifo_tr'][J] = lots_from(tr, J, 'lifo'); E['worst_tr'][J] = lots_from(tr, J, 'worst')
        E['fifo250'][J] = lots_from(lo250, J, 'fifo'); E['lifo250'][J] = lots_from(lo250, J, 'lifo'); E['worst250'][J] = lots_from(lo250, J, 'worst')
    # 날 t 로 옮김(t-1 까지의 신용)
    toT = lambda arr: np.where(Jt >= 0, arr[np.clip(Jt, 0, None)], np.nan)
    lines = {}
    for nm in names:
        e = toT(E[nm])
        for mm in (1.4, 1.3):
            for ss in (0.6, 0.5):
                lines[f'avgcost|{nm}|m{mm}|s{ss}'] = e * mm * ss
    for (q, mm), arr in PRQ.items():
        lines[f'prq|q{int(q * 100)}|m{mm}'] = toT(arr)
    now = {nm: float(E[nm][-1]) for nm in names}
    now.update({f'prq|q{int(q * 100)}|m{mm}': float(arr[-1]) for (q, mm), arr in PRQ.items()})
    return lines, now


def main():
    df = load(); k = df['kospi']; n = len(df)
    cr3 = (df['kospi_jo'].shift(-3) / df['kospi_jo'] - 1) * 100
    q90 = df['ratio_pct'].rolling(120, min_periods=60).quantile(0.9)
    fmax = df['ratio_pct'].shift(-1).rolling(3).max().shift(-2)
    valid = cr3.notna() & fmax.notna() & q90.notna()
    Wc = (cr3 <= CW).values; Wc2 = (cr3 <= CW2).values; Wm = (fmax >= q90).values
    r = k.pct_change() * 100
    lines = {}
    for N in (5, 10, 20, 40, 60, 120, 250):
        lo = k.shift(1).rolling(N, min_periods=N).min()
        for dl in (2, 1, 0, -1, -2, -3, -4, -5, -7, -10):
            lines[f'prevlow|N{N}|d{dl}'] = (lo * (1 + dl / 100)).values
    for N in (20, 60, 120, 250):
        hi = k.shift(1).rolling(N, min_periods=N).max()
        for D in (5, 10, 15, 20, 25, 30, 35, 40, 45):
            lines[f'ddhigh|N{N}|D{D}'] = (hi * (1 - D / 100)).values
    ac, ac_now = avgcost_lines(df); lines.update(ac)
    sig = {nm: (k.values < L) & np.isfinite(L) for nm, L in lines.items()}
    sig['drop|r-2'] = (r <= -2).values; sig['drop|r-3'] = (r <= -3).values
    lo60 = k.shift(1).rolling(60, min_periods=60).min()
    sig['combo|r-2&prevlow60'] = ((r <= -2) & (k < lo60)).values
    sig['base|all'] = np.ones(n, bool)
    idx = df.index

    def ev(b, msk):
        m_ = msk & valid.values
        bb = b[m_]; nb = int(bb.sum())
        out = {'days': nb, 'eps': int(((bb[1:]) & ~(bb[:-1])).sum() + (1 if len(bb) and bb[0] else 0))}
        c3 = cr3.values[m_]
        out['cr3_mean'] = float(np.mean(c3[bb])) if nb else np.nan
        for tag, W in (('c', Wc), ('c3', Wc2), ('m', Wm)):
            w = W[m_]; tp = int((bb & w).sum()); P = tp / nb if nb else np.nan; R = tp / w.sum() if w.sum() else np.nan
            out[f'P_{tag}'] = P; out[f'R_{tag}'] = R; out[f'F1_{tag}'] = (2 * P * R / (P + R)) if nb and (P + R) > 0 else 0.0
        return out

    mdev = ((idx >= DEV[0]) & (idx <= DEV[1])); mtest = ((idx >= TEST[0]) & (idx <= TEST[1]))
    rows = []
    for nm, b in sig.items():
        fam = nm.split('|')[0]
        dv = ev(b, mdev); ts = ev(b, mtest)
        rows.append({'후보': nm, '가족': fam, **{f'개발_{k_}': v_ for k_, v_ in dv.items()}, **{f'확인_{k_}': v_ for k_, v_ in ts.items()}})
    R = pd.DataFrame(rows)
    ok = (R['개발_days'] >= 15) & (R['개발_eps'] >= 8) & ~R['가족'].isin(['base'])
    R['신용F1순위'] = R.loc[ok, '개발_F1_c'].rank(ascending=False); R['미수F1순위'] = R.loc[ok, '개발_F1_m'].rank(ascending=False)
    R['점수'] = (R['신용F1순위'] + R['미수F1순위']) / 2
    R = R.sort_values(['점수', '개발_F1_c'], ascending=[True, False], na_position='last')   # 점수가 같으면 신용 F1 이 높은 쪽
    R.to_csv(os.path.join(OUT, 'candidates.csv'), index=False, encoding='utf-8-sig')
    win = R[ok.reindex(R.index)].iloc[0]['후보']
    fam_best = R[ok.reindex(R.index)].groupby('가족').head(3)
    fam_best.to_csv(os.path.join(OUT, 'family_best.csv'), index=False, encoding='utf-8-sig')
    # 이긴 가족의 사다리(같은 창, 문턱만 바꿈)
    parts = win.split('|')
    if parts[0] == 'prevlow':
        lad = R[R['후보'].str.startswith(f'prevlow|{parts[1]}|')].copy(); lad['문턱'] = lad['후보'].str.split('|').str[2].str[1:].astype(int); lad = lad.sort_values('문턱', ascending=False)
    elif parts[0] == 'ddhigh':
        lad = R[R['후보'].str.startswith(f'ddhigh|{parts[1]}|')].copy(); lad['문턱'] = -lad['후보'].str.split('|').str[2].str[1:].astype(int); lad = lad.sort_values('문턱', ascending=False)
    else:
        lad = R[R['가족'] == parts[0]].copy(); lad['문턱'] = np.nan
    lad.to_csv(os.path.join(OUT, 'ladder.csv'), index=False, encoding='utf-8-sig')
    # 해마다(상위 후보·기존 대시보드 선·비교용)
    top = list(R[ok.reindex(R.index)]['후보'].head(8)) + ['avgcost|primary|m1.4|s0.6', 'avgcost|primary|m1.3|s0.6', 'drop|r-2', 'base|all']
    YR = []
    for nm in dict.fromkeys(top):
        b = sig[nm]
        for y in range(2016, idx[-1].year + 1):
            my = (idx.year == y)
            e = ev(b, my); YR.append({'후보': nm, '연도': y, '이탈일': e['days'], '신용물결 정밀도': e['P_c'], '신용 재현율': e['R_c'], '3일 신용 평균%': e['cr3_mean'], '미수물결 정밀도': e['P_m']})
    pd.DataFrame(YR).to_csv(os.path.join(OUT, 'by_year.csv'), index=False, encoding='utf-8-sig')
    # 지금 선 위치(마지막 종가까지 넣은 값 = 다음 거래일에 쓰는 선)
    last_close = float(k.iloc[-1]); now = {}
    for N in (5, 10, 20, 40, 60, 120, 250):
        lo_now = float(k.iloc[-N:].min()); lo_date = str(k.iloc[-N:].idxmin().date())
        for dl in (2, 1, 0, -1, -2, -3, -4, -5, -7, -10):
            now[f'prevlow|N{N}|d{dl}'] = {'line': round(lo_now * (1 + dl / 100), 2), 'base_low': lo_now, 'base_date': lo_date}
    for N in (20, 60, 120, 250):
        hi_now = float(k.iloc[-N:].max())
        for D in (5, 10, 15, 20, 25, 30, 35, 40, 45):
            now[f'ddhigh|N{N}|D{D}'] = {'line': round(hi_now * (1 - D / 100), 2), 'base_high': hi_now}
    for nm, e in ac_now.items():
        if nm.startswith('prq'): now[nm] = {'line': round(e, 2)}
        else:
            for mm in (1.4, 1.3):
                for ss in (0.6, 0.5): now[f'avgcost|{nm}|m{mm}|s{ss}'] = {'line': round(e * mm * ss, 2), 'entry': round(e, 2)}
    S = {'data_last': {'kospi': str(idx[-1].date()), 'credit': str(df['kospi_jo'].last_valid_index().date()), 'liq': str(df['ratio_pct'].last_valid_index().date())},
         'last_close': last_close, 'winner': win, 'winner_row': R[R['후보'] == win].iloc[0].to_dict(),
         'rule': '개발 2016~2022, 이탈 15일·8구간 이상, 신용 F1 순위와 미수 F1 순위 평균 1등(같으면 신용 F1 높은 쪽)',
         'targets': {'credit': f'신용잔고 3일 변화 ≤ {CW}%', 'credit_severe': f'≤ {CW2}%', 'misu': 't+1~t+3 미수 반대매매 비중 최고 ≥ 직전 120일 90% 분위'},
         'base_dev': R[R['후보'] == 'base|all'].iloc[0].to_dict(), 'now': now}
    json.dump(S, open(os.path.join(OUT, 'summary.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=float)
    cols = ['후보', '개발_days', '개발_eps', '개발_P_c', '개발_R_c', '개발_F1_c', '개발_P_m', '개발_F1_m', '개발_cr3_mean', '확인_days', '확인_eps', '확인_P_c', '확인_R_c', '확인_F1_c', '확인_P_m', '확인_cr3_mean', '점수']
    pd.set_option('display.width', 250)
    print('이긴 후보:', win)
    print(R[cols].head(25).round(3).to_string(index=False))
    print(R[R['후보'].isin(['base|all', 'drop|r-2', 'avgcost|primary|m1.4|s0.6', 'avgcost|primary|m1.3|s0.6', 'avgcost|lifo250|m1.4|s0.6', 'avgcost|worst250|m1.4|s0.6'])][cols].round(3).to_string(index=False))


if __name__ == '__main__':
    main()
