"""A9 매매 시뮬레이션 에이전트 — 후보 신호를 실제 포지션으로: 코스피200 선물, KODEX 200(ETF), 근월물 옵션(등가격 콜·풋 매수).

대상: 개발 통과 후보 전부 + 개발 성적 상위 N개(참고, 개발 구간만). 잠금 구간 성과는 A8 이 이미 연 후보만 계산한다.
비용(왕복): 선물 0.03%, ETF 0.15%, 옵션 프리미엄의 3%. 겹치는 신호는 버림(한 번에 한 포지션).
옵션: 신호 다음 거래일 정산가로 진입(장중 가격이 없어 종가 기준), 청산일 정산가로 청산. 그 사이 만기가 오면 만기일 정산가(내재가치)로 청산.
"""
import os
import pickle
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lab_common as L  # noqa: E402
from a08_validate import independent  # noqa: E402

cfg = L.round_cfg().get('a09', {})
TOPN = cfg.get('top_n', 10)
# 갈래 B 라운드 22(설정 없으면 꺼짐 → 갈래 A 영향 없음): ids = 선별 여부와 상관없이 늘 두 구간 모두 시뮬레이션할 후보,
#   by_year = 선물(K200F) 해마다 성적 표(trades_by_year.csv), baseline = 같은 보유 기간·같은 방향을 아무 날에나 잡았을 때의 평균 수익·승률(비용 뒤) 칸.
IDS = list(cfg.get('ids') or [])
COST = {'K200F': 0.03, 'ETF': 0.15}
K2C = {}


def option_trades(t, direction, ch, td):
    """등가격 근월물 콜(상승)/풋(하락) 매수 수익(%), 비용 3%."""
    out = []
    cp = 'C' if direction > 0 else 'P'
    for s, e in zip(t['signal'], t['exit']):
        i = td.searchsorted(s, side='right')
        if i >= len(td): out.append(np.nan); continue
        d0 = td[i]
        g = ch.get(d0)
        if g is None: out.append(np.nan); continue
        S = g['spot'].median()
        live = sorted(y for y in g['ym'].unique() if L.expiry_of_ym(y, td) > d0)
        if not live: out.append(np.nan); continue
        ym = live[0]; ex = L.expiry_of_ym(ym, td)
        gg = g[(g['ym'] == ym) & (g['cp'] == cp) & (g['settle'] > 0)]
        if not len(gg): out.append(np.nan); continue
        row = gg.iloc[(gg['K'] - S).abs().argsort(kind='stable')[:1]]
        K = float(row['K'].iloc[0]); p0 = float(row['settle'].iloc[0])
        d1 = min(e, ex)
        if d1 >= ex:                       # 만기 청산: 내재가치(코스피200 만기일 종가 기준 — 실제 최종결제가와 조금 다를 수 있음)
            S1 = float(K2C.get(ex, np.nan))
            if not np.isfinite(S1): out.append(np.nan); continue
            p1 = max(0.0, (S1 - K) if cp == 'C' else (K - S1))
        else:
            g1 = ch.get(d1)
            if g1 is None: out.append(np.nan); continue
            r1 = g1[(g1['ym'] == ym) & (g1['cp'] == cp) & (g1['K'] == K)]
            if not len(r1) or not np.isfinite(r1['settle'].iloc[0]): out.append(np.nan); continue
            p1 = float(r1['settle'].iloc[0])
        out.append(max(-100.0, (p1 / p0 - 1) * 100 - 3.0) if p0 > 0 else np.nan)
    return np.array(out)


def stats_of(ret, frac=1.0):
    """frac = 한 거래에 거는 자본 비중(옵션은 10%: 프리미엄을 다 잃어도 자본의 10%)."""
    ret = ret[~np.isnan(ret)]
    if not len(ret): return {}
    eq = np.cumprod(1 + frac * ret / 100)
    dd = (eq / np.maximum.accumulate(eq) - 1).min() * 100
    return {'n': len(ret), 'win%': float((ret > 0).mean() * 100), 'avg%': float(ret.mean()), 'total%': float((eq[-1] - 1) * 100), 'mdd%': float(dd)}


def main():
    rd = L.out_dir()
    V = pd.read_csv(os.path.join(rd, 'a08', 'verdicts.csv'))
    _fd = L.round_cfg().get('focus_direction')   # 갈래 D 라운드 2(2026-11-23): 설정 focus_direction(−1 등)이 있으면 그 방향 후보만 고른다 — 없으면(갈래 A·B) 예전과 같음
    if _fd in (1, -1): V = V[V['direction'] == _fd].reset_index(drop=True)
    cands = {}
    for a in sorted(os.listdir(rd)):
        p = os.path.join(rd, a, 'candidates.pkl')
        if os.path.exists(p):
            for c in pickle.load(open(p, 'rb')): cands[c['id']] = c
    pick = V[V['dev_pass']].copy()
    pick = pd.concat([pick, V[~V['dev_pass'] & (V['dev_n'] >= 10)].sort_values('dev_hit', ascending=False).head(TOPN)])
    if IDS: pick = pd.concat([pick, V[V['id'].isin(IDS)]]).drop_duplicates('id')
    P = L.prices()
    if 'ETF' not in P:
        L.fetch_etf(); P = L.prices()
    ch_raw = L.chain_best()[1]
    ch = dict(tuple(ch_raw.groupby('date')))
    td = P['K200'].index
    global K2C
    K2C = P['K200']['close'].to_dict()
    rows = []; yrows = []
    for _, v in pick.iterrows():
        c = cands.get(v['id'])
        if c is None: continue
        for part, tr, s0, s1 in (('개발', c.get('trades_dev', c['trades']), pd.Timestamp('2010-01-01'), L.DEV_END),
                                 ('잠금', c['trades'], L.HOLD_START, td[-1])):
            if part == '잠금' and not (v['dev_pass'] or v['id'] in IDS): continue
            tr = tr.assign(signal=pd.to_datetime(tr['signal']), exit=pd.to_datetime(tr['exit']))
            t = independent(tr[(tr['signal'] >= s0) & (tr['exit'] <= s1)].dropna())
            if not len(t): continue
            for inst in ('K200F', 'ETF'):
                if inst not in P: continue
                r = c['direction'] * L.trade_returns(t, P[inst]) - COST[inst]
                if inst == 'ETF' and c['direction'] < 0: r = np.full(len(t), np.nan)   # ETF 는 매수만(하락 신호 = 현금)
                extra = {}
                if cfg.get('baseline') and inst == 'K200F':
                    px = P[inst]; tdp = px.index
                    hd = [tdp.searchsorted(e) - tdp.searchsorted(s_, side='right') + 1 for s_, e in zip(t['signal'], t['exit'])]
                    h = int(max(1, np.median(hd)))
                    rb = c['direction'] * (px['close'].shift(-h) / px['open'].shift(-1) - 1) * 100 - COST[inst]
                    rb = rb[(rb.index >= max(s0, tdp[0])) & (rb.index <= s1)].dropna()
                    extra = {'base_h': h, 'base_avg%': float(rb.mean()) if len(rb) else np.nan, 'base_win%': float((rb > 0).mean() * 100) if len(rb) else np.nan}
                rows.append({'id': v['id'], '구간': part, '수단': inst, **stats_of(r), **extra})
                if cfg.get('by_year') and inst == 'K200F':
                    yrs = pd.DatetimeIndex(t['signal']).year
                    for y in sorted(set(yrs)):
                        st = stats_of(r[yrs == y])
                        if st: yrows.append({'id': v['id'], '해': int(y), **st})
            r = option_trades(t, c['direction'], ch, td)
            rows.append({'id': v['id'], '구간': part, '수단': '옵션(등가격 매수, 자본 10%씩)', **stats_of(r, 0.1)})
    od = L.out_dir('a09'); pd.DataFrame(rows).round(3).to_csv(os.path.join(od, 'trades.csv'), index=False, encoding='utf-8')
    if yrows: pd.DataFrame(yrows).round(3).to_csv(os.path.join(od, 'trades_by_year.csv'), index=False, encoding='utf-8')
    print('시뮬레이션', len(rows))


if __name__ == '__main__':
    main()
