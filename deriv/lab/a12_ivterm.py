"""A12 IV 기간구조 에이전트(2026-11-23 진화 에이전트가 추가) — 코스피200 옵션 근월 대 차월 등가격 내재변동성(IV) 비율로 하락·큰 하락을 찾는다.

왜: 연구소 지표에는 대표 IV·풋−콜 IV·스큐(V1·V2)는 있으나 결제월 사이 기간구조가 없다. 미국에서는 VIX 기간구조 역전(근월 > 차월)이
    시장 스트레스와 함께 나타난다(Johnson 2017, Risk Premia and the VIX Term Structure, JFQA 52(6) — 주로 분산 자산 수익 예측,
    주가 방향 예측은 약하다는 해석이 일반적). 갈래 D(하락·급락 전담)가 쓸 새 가족으로, 판정은 A8·A10 에 맡긴다.
자료: deriv/data/opt_chainx_daily.csv.gz(월물 결제월 4개, 행사가별 정산가·기초지수) — t일 장 마감 뒤 아는 값만.
계산: 결제월마다 기초지수에 가장 가까운 행사가(콜·풋 정산가 둘 다 > 0)의 콜+풋(스트래들)을 블랙 식으로 풀어 IV(할인 1, 선도가 = K + C − P).
      근월 = 만기까지 5거래일 이상 남은 가장 가까운 결제월, 차월 = 그다음 결제월. 비율 ts = 근월 IV ÷ 차월 IV (> 1 이면 역전).
조건(문턱은 미리 정한 값 또는 그 시점까지 3년 백분위 — 어느 구간 성적도 보고 정하지 않음):
      ts > 1, ts > 1.05, ts > 1 첫날(직전 5일 없음), ts 백분위 상위 10·5%, ts 백분위 하위 10%, 근월 IV 5일 변화 백분위 상위 10%,
      각 조건 그대로 / + 하락 추세(선물 종가 < 60일 평균).
대상: 코스피200 선물 다음 날 시가 → 1·2·3·5·10·20일 뒤 종가(상승·하락 둘 다), 큰 변동 창 5·10·20일(±1σ√W 먼저 닿는 쪽).
자료 없는 날은 빈칸(추정으로 채우지 않음).
"""
import os
import sys

import numpy as np
import pandas as pd
from scipy.special import ndtr

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lab_common as L  # noqa: E402

AG = 'a12'
HS = [1, 2, 3, 5, 10, 20]
BARRIER = [5, 10, 20]
BK = 1.0
MIN_TD_LEFT = 5
MIN_SIG = 12


def straddle_iv(F, K, T, prem):
    """블랙(할인 1) 스트래들 가격 = prem 이 되는 σ 를 이분법으로(벡터). 풀 수 없으면 NaN."""
    F, K, T, prem = (np.asarray(x, dtype=float) for x in (F, K, T, prem))
    lo = np.full(F.shape, 1e-3); hi = np.full(F.shape, 3.0)
    sq = np.sqrt(T)

    def price(s):
        d1 = (np.log(F / K) + 0.5 * s * s * T) / (s * sq); d2 = d1 - s * sq
        c = F * ndtr(d1) - K * ndtr(d2)
        return c + (c - F + K)   # 콜 + 풋(패리티, 할인 1)

    ok = (F > 0) & (K > 0) & (T > 0) & (prem > np.abs(F - K)) & np.isfinite(prem)
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        up = price(mid) < prem
        lo = np.where(up, mid, lo); hi = np.where(up, hi, mid)
    iv = 0.5 * (lo + hi)
    iv[~ok | (iv >= 2.99)] = np.nan
    return iv


def iv_table(td):
    """날짜 × (근월 IV, 차월 IV). td = 거래일(만기 달력용)."""
    c = L.chain('x')
    if c is None or not len(c): raise SystemExit('opt_chainx 자료 없음')
    c = c[['date', 'cp', 'ym', 'K', 'settle', 'spot']].dropna()
    c = c[(c['settle'] > 0) & (c['spot'] > 0)]
    c = c.drop_duplicates(['date', 'cp', 'ym', 'K'], keep='last')
    w = c.pivot_table(index=['date', 'ym', 'K'], columns='cp', values='settle', aggfunc='last').dropna(subset=['C', 'P']).reset_index()
    sp = c.groupby(['date', 'ym'])['spot'].last()
    w = w.join(sp, on=['date', 'ym'])
    w['dist'] = (w['K'] - w['spot']).abs()
    w = w.sort_values(['date', 'ym', 'dist', 'K'], kind='stable').drop_duplicates(['date', 'ym'], keep='first')   # 등가격(가까운 행사가, 같으면 낮은 행사가)
    exp = {ym: L.expiry_of_ym(ym, td) for ym in w['ym'].unique()}
    w['exp'] = w['ym'].map(exp)
    w = w[w['exp'] > w['date']]
    tdv = td.values
    w['left'] = np.searchsorted(tdv, w['exp'].values, side='right') - np.searchsorted(tdv, w['date'].values, side='right')
    w['T'] = (w['exp'] - w['date']).dt.days / 365.0
    w['F'] = w['K'] + w['C'] - w['P']
    w['iv'] = straddle_iv(w['F'], w['K'], w['T'], w['C'] + w['P']) * 100
    w = w[(w['left'] >= MIN_TD_LEFT) & w['iv'].notna()].sort_values(['date', 'exp'], kind='stable')
    g = w.groupby('date')
    front = g.nth(0).set_index('date'); nxt = g.nth(1).set_index('date')
    out = pd.DataFrame({'iv_f': front['iv'], 'ym_f': front['ym']}).join(pd.DataFrame({'iv_n': nxt['iv'], 'ym_n': nxt['ym']}), how='left')
    out['ts'] = out['iv_f'] / out['iv_n']
    return out.sort_index()


def pct_rank(s, win=756, minp=252):
    """그 시점까지(오늘 포함) 3년 창에서 오늘 값의 백분위."""
    return s.rolling(win, min_periods=minp).apply(lambda x: (x[:-1] <= x[-1]).mean() if len(x) > 1 else np.nan, raw=True)


def first_day(mask, gap=5):
    m = mask.fillna(False).astype(bool); prev = m.shift(1).rolling(gap, min_periods=1).max().fillna(0).astype(bool)
    return m & ~prev


def main():
    px = L.prices()['K200F']; td = px.index
    T = iv_table(td)
    T.round(4).to_csv(os.path.join(L.out_dir(AG), 'ivterm_daily.csv'), encoding='utf-8')
    F = T.reindex(td)
    ts = F['ts']; q = pct_rank(ts.dropna()).reindex(td)
    dv = (F['iv_f'] - F['iv_f'].shift(5)); qd = pct_rank(dv.dropna()).reindex(td)
    dn_trend = (px['close'] < px['close'].rolling(60, min_periods=60).mean()).reindex(td)
    have = ts.notna()
    conds = [('inv', '근월 IV > 차월 IV(역전)', have & (ts > 1.0)),
             ('inv105', '근월 IV ÷ 차월 IV > 1.05', have & (ts > 1.05)),
             ('inv_first', '근월·차월 IV 역전 첫날(직전 5일 없음)', first_day(have & (ts > 1.0))),
             ('tsq90', 'IV 기간구조 비율 3년 백분위 상위10%', have & (q >= 0.90)),
             ('tsq95', 'IV 기간구조 비율 3년 백분위 상위5%', have & (q >= 0.95)),
             ('tsq10', 'IV 기간구조 비율 3년 백분위 하위10%(가파른 정상)', have & (q <= 0.10)),
             ('dvq90', '근월 IV 5일 상승폭 3년 백분위 상위10%', F['iv_f'].notna() & (qd >= 0.90))]
    tgts = [(f'h{h}', f'{h}일', None, h) for h in HS]
    for W in BARRIER:
        y, ex = L.barrier_exits(px, W, BK)
        tgts.append((f'b{W}', f'{W}일 안 큰 변동(±{BK:g}σ) 먼저', ex.reindex(td).dropna().to_dict(), W))
    cands = []
    for cid, desc, m in conds:
        for tag, tdesc, mm in (('', '', m), ('_dt', ' + 하락 추세(60일선 아래)', m & dn_trend.fillna(False))):
            mk = np.asarray(mm.reindex(td).fillna(False).values, dtype=bool)
            sig = td[mk]
            if len(sig) < MIN_SIG: continue
            for tid, tname, exs, h in tgts:
                exits = [L.exit_after(td, s, h) for s in sig] if exs is None else [exs.get(s, pd.NaT) for s in sig]
                tr = pd.DataFrame({'signal': sig, 'exit': exits}).dropna()
                if len(tr) < MIN_SIG: continue
                for d, dn in ((1, '상승'), (-1, '하락')):
                    cands.append({'id': f'A12_iv_{cid}{tag}_{tid}_{"up" if d > 0 else "dn"}', 'agent': 'A12', 'family': 'ivterm' if exs is None else 'ivterm_big',
                                  'desc': f'{desc}{tdesc} → {tname} {dn}', 'direction': d, 'trades': tr})
    print('IV 기간구조 날짜', int(have.sum()), '· 역전 날', int((have & (ts > 1)).sum()), '· 후보', len(cands), flush=True)
    L.save_candidates(AG, cands)


if __name__ == '__main__':
    main()
