"""A10 반증 에이전트 — 좋아 보이는 후보를 깨 보려고 한다(개발 구간만 사용).

대상: 개발 통과 후보 + 개발 성적 상위 N개.
  (1) 시점 이동 위약: 신호 날짜를 같은 해 안에서 20~60거래일 무작위로 옮겨 300번 → 원래 적중률이 우연으로 나올 확률(p)
  (2) 한 해 빼기: 해마다 하나씩 빼고 적중률 → 최저값(특정 해 하나에 기대는지)
  (3) 2020년(코로나)·2022년(하락장) 빼기
  (4) 신호가 한 시기에 몰렸는지: 독립 거래가 가장 많은 해의 비중
판정: p < 0.05, 한 해 빼기 최저 ≥ 70%, 몰림 < 40% 이면 '버팀'.
"""
import os
import pickle
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lab_common as L  # noqa: E402
from a08_validate import honest_trades, independent  # noqa: E402

cfg = L.round_cfg().get('a10', {})
TOPN = cfg.get('top_n', 10)
rng = np.random.default_rng(0)


def hits(t, px, direction):
    r = L.trade_returns(t, px)
    ok = ~np.isnan(r)
    return pd.Series(direction * r[ok] > 0, index=pd.DatetimeIndex(t['signal'].values[ok]))


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
    pick = pd.concat([V[V['dev_pass']], V[~V['dev_pass'] & (V['dev_n'] >= 10)].sort_values('dev_hit', ascending=False).head(TOPN)])
    px = L.prices()['K200F']; td = px.index
    cross = 'cv_mode' in V.columns and bool((V['cv_mode'] == 'cross').any())   # 2026-11-21~: 잠금 없이 전 기간(앞 구간은 해마다 고른 신호)
    END = td[-1] if cross else L.DEV_END
    rows = []
    for _, v in pick.iterrows():
        c = cands.get(v['id'])
        if c is None: continue
        if cross: tr = honest_trades(c)[2]
        else:
            tr = c.get('trades_dev', c['trades'])
            tr = tr.assign(signal=pd.to_datetime(tr['signal']), exit=pd.to_datetime(tr['exit']))
        t = independent(tr[(tr['exit'] <= END)].dropna())
        if len(t) < 5: continue
        hs = hits(t, px, c['direction']); h0 = hs.mean()
        hold = [max(1, ((td > s) & (td <= e)).sum()) for s, e in zip(t['signal'], t['exit'])]
        sims = []
        for _ in range(300):
            sh = []
            for s, hd in zip(t['signal'], hold):
                # 교차 모드(2026-11-21~)는 앞 구간 2010~ 신호까지 들어와 선물 가격표에 없는 날(휴장·자료 시작 전)이 생김 — get_loc 대신 그날 이후 첫 거래일 위치(있는 날이면 같은 값)
                i = int(td.searchsorted(s)) + int(rng.integers(20, 61)) * (1 if rng.random() < 0.5 else -1)
                i = int(np.clip(i, 0, len(td) - hd - 2))
                sh.append((td[i], td[i + hd]))
            st = pd.DataFrame(sh, columns=['signal', 'exit'])
            st = st[st['exit'] <= END]
            if len(st): sims.append(hits(st, px, c['direction']).mean())
        p = float((np.array(sims) >= h0).mean()) if sims else np.nan
        yrs = hs.index.year
        loyo = [hs[yrs != y].mean() for y in sorted(set(yrs))] if len(set(yrs)) > 1 else [np.nan]
        ex20 = hs[(yrs != 2020)].mean(); ex22 = hs[(yrs != 2022)].mean()
        conc = pd.Series(yrs).value_counts(normalize=True).max()
        robust = bool(p < 0.05 and np.nanmin(loyo) >= 0.70 and conc < 0.40)
        rows.append({'id': v['id'], 'n': len(hs), '적중': h0, '위약p': p, '한해빼기_최저': np.nanmin(loyo), '2020빼고': ex20, '2022빼고': ex22,
                     '한해쏠림': conc, '버팀': robust})
    od = L.out_dir('a10'); pd.DataFrame(rows).round(3).to_csv(os.path.join(od, 'redteam.csv'), index=False, encoding='utf-8')
    print('반증', len(rows))


if __name__ == '__main__':
    main()
