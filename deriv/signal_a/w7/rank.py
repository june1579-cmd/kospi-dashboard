# -*- coding: utf-8 -*-
"""Signal A W7 — 대상 정하기(순위). extract.py(판다스 최신판)와 run.py(고정판)가 함께 쓴다. pandas·numpy 만 쓴다(sa_common 을 부르지 않음).

  pool_x1()        x1/out/pool.csv 를 그대로 읽는다((가)의 대상 — X1 순위 그대로).
  rank_verdicts(g) 갈래 g 의 모든 round_*/a08/verdicts.csv(+ 같은 회차 a10/redteam.csv 의 버팀)로 X1 1절과 같은 규칙의 상위 100개((다)).
  targets()        갈래별로 거래일이 필요한 id 모음(X1 대상 + (다) 상위 100개).
못 읽는 파일이 있으면 멈춘다(조용히 넘기지 않는다). 열이 없는 옛 회차만 X1 처럼 건너뛰고 수를 적는다.
"""
import glob
import os
import re

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
SA = os.path.dirname(HERE)
LAB = os.path.join(os.path.dirname(SA), 'lab')
BR = {'A': 'out', 'B': 'out_b', 'C': 'out_c', 'D': 'out_d'}
NEED = ['id', 'family', 'desc', 'direction', 'all_n', 'all_hit', 'all_lb', 'dev_n', 'dev_hit', 'p2_n', 'p2_hit']
TOP = 100
POOL_X1 = os.path.join(SA, 'x1', 'out', 'pool.csv')


def pool_x1():
    """X1 의 대상표(갈래·rank·grade·id·desc·round·연구소 숫자·src …). 없거나 못 읽으면 멈춘다."""
    if not os.path.exists(POOL_X1): raise RuntimeError(f'X1 대상표가 없음({POOL_X1}) — W7 은 X1 결과가 있어야 함')
    p = pd.read_csv(POOL_X1)
    miss = [c for c in ['갈래', 'rank', 'grade', 'id', 'desc', 'direction', 'round', 'dev_n', 'dev_hit', 'src'] if c not in p.columns]
    if miss or not len(p): raise RuntimeError(f'X1 대상표의 열이 모자라거나 비어 있음: {miss}')
    p['rank'] = p['rank'].astype(int); p['round'] = p['round'].astype(int); p['direction'] = p['direction'].astype(int)
    p['src'] = p['src'].astype(str); p['id'] = p['id'].astype(str)
    return p


def rank_verdicts(g):
    """갈래 g 의 (다) 상위 100개. 반환 (표, 정보). 표의 열 = NEED + 버팀·round·lb_pos·P·W·rank·grade."""
    L = []; skipped = []; rounds = []; nored = []
    for f in sorted(glob.glob(os.path.join(LAB, BR[g], 'round_*', 'a08', 'verdicts.csv'))):
        r = int(re.search(r'round_(\d+)', f).group(1)); rounds.append(r)
        try:
            x = pd.read_csv(f, low_memory=False)
        except Exception as e:                                       # noqa: BLE001
            raise RuntimeError(f'갈래 {g}: {os.path.relpath(f, LAB)} 를 못 읽음({type(e).__name__})') from e
        if not set(NEED) <= set(x.columns): skipped.append(r); continue
        x = x[NEED].copy(); x['버팀'] = False
        rp = os.path.join(os.path.dirname(os.path.dirname(f)), 'a10', 'redteam.csv')
        if os.path.exists(rp):
            try:
                R = pd.read_csv(rp)
            except Exception as e:                                   # noqa: BLE001
                raise RuntimeError(f'갈래 {g}: {os.path.relpath(rp, LAB)} 를 못 읽음({type(e).__name__})') from e
            if 'id' in R.columns and '버팀' in R.columns:
                ok = set(R.loc[R['버팀'].map(lambda v: str(v).strip().lower() == 'true'), 'id'].astype(str))
                x['버팀'] = x['id'].astype(str).isin(ok).values
            else: nored.append(r)
        else: nored.append(r)
        x['round'] = r; x['lb_pos'] = np.arange(len(x)); L.append(x)
    info = {'rounds': len(rounds), 'skipped': len(skipped), 'no_redteam': len(nored), 'rows': 0, 'uniq': 0}
    cols = NEED + ['버팀', 'round', 'lb_pos', 'P', 'W', 'rank', 'grade']
    if not L: return pd.DataFrame(columns=cols), info
    A = pd.concat(L, ignore_index=True); info['rows'] = int(len(A))
    A = A.dropna(subset=['id', 'desc']); A['id'] = A['id'].astype(str)
    A = A.sort_values(['round', 'lb_pos'], kind='stable').drop_duplicates('desc', keep='last')
    for k in ('direction', 'all_n', 'all_hit', 'all_lb', 'dev_n', 'dev_hit', 'p2_n', 'p2_hit'): A[k] = pd.to_numeric(A[k], errors='coerce')
    A = A.dropna(subset=['direction']); A['direction'] = A['direction'].astype(int)
    if g == 'D': A = A[A['direction'] == -1]
    info['uniq'] = int(len(A))
    b = A['버팀'].astype(bool)
    ge = lambda k, v: A[k].fillna(-1) >= v
    A['P'] = ge('all_n', 35) & ge('all_hit', 0.85) & ge('dev_n', 12) & ge('dev_hit', 0.80) & ge('p2_n', 12) & ge('p2_hit', 0.80) & b
    A['W'] = ge('all_n', 35) & ge('all_hit', 0.80) & ge('dev_n', 12) & ge('dev_hit', 0.75) & ge('p2_n', 12) & ge('p2_hit', 0.75) & b
    A['_lb'] = A['all_lb'].fillna(-1.0)
    A = A.sort_values(['P', 'W', '_lb', 'round', 'id'], ascending=[False, False, False, False, True], kind='stable').head(TOP).reset_index(drop=True)
    A['rank'] = np.arange(1, len(A) + 1); A['grade'] = np.where(A['P'], '통과', np.where(A['W'], '관찰', '–'))
    return A.drop(columns=['_lb']), info


def targets():
    """갈래별 대상. 반환 {갈래: {'x1': X1 대상표(그 갈래), 'v': (다) 순위표, 'info': 정보, 'ids': 거래일이 필요한 id 모음}}."""
    PX = pool_x1(); out = {}
    for g in 'ABCD':
        px = PX[PX['갈래'] == g].sort_values('rank').reset_index(drop=True); v, info = rank_verdicts(g)
        v = v.copy(); v['in_x1'] = v['desc'].isin(set(px['desc'])).values if len(v) else []
        out[g] = {'x1': px, 'v': v, 'info': info, 'ids': sorted(set(px['id']) | set(v['id']))}
    return out
