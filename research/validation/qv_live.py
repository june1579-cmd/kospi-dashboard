# -*- coding: utf-8 -*-
"""새 점수식(검증 통과분)을 오늘 자료로 계산 — stocks_daily.py 가 불러 씀.

ref/qv_formula.json 의 명단별 식(keys·sector_neutral·adopt)을 읽어,
qv.py 와 같은 정의의 특성을 가장 최근 주간 자료 기준으로 만들고 '기준 집단' 안의 백분위 같은 비중 평균(0~100)을 돌려준다.
기준 집단 밖 종목(다른 명단 종목)은 기준 집단 분포에 놓고 백분위를 매긴다.
"""
import os, json
import numpy as np, pandas as pd
import qv as Q

ROOT = os.path.dirname(os.path.abspath(__file__))
FORM = os.path.join(ROOT, 'ref', 'qv_formula.json')


def formula():
    return json.load(open(FORM)) if os.path.exists(FORM) else {}


class Live:
    def __init__(self, log=print):
        W = Q.load_weekly(); R = W[0]
        IX = Q.load_index(R.index)
        S = {k: Q.snaps(k) for k in ('CAP', 'FUND', 'FR', 'SHORT', 'SECT')}
        DART, _ = Q.load_dart()
        i = len(R.index) - 1
        self.t = R.index[i]
        self.F = Q.features(i, W, IX, S['CAP'], S['FUND'], S['FR'], S['SHORT'], S['SECT'], DART)
        log('새 점수식 특성: 기준 주', str(self.t.date()), '종목', len(self.F))

    def score(self, keys, ref_codes, codes, sector_neutral=False):
        """ref_codes 분포 기준 백분위 평균. 반환: {코드: 점수}, {코드: {특성: 백분위}}"""
        F = self.F
        ref = F.reindex([c for c in ref_codes if c in F.index])
        out, parts = {}, {}
        cols = {}
        for k in keys:
            hi = Q.CN[k][0]
            x = F[k].astype(float) if k in F else pd.Series(np.nan, index=F.index)
            if k == 'pbr': x = x.where(x > 0, 99)
            v = x if hi else -x
            cols[k] = v
        for c in codes:
            parts[c] = {}
            for k in keys:
                v = cols[k]
                if sector_neutral and 'sector' in F and c in F.index and pd.notna(F.at[c, 'sector']):
                    pool = v.reindex(ref.index[ref['sector'] == F.at[c, 'sector']]).dropna()
                else:
                    pool = v.reindex(ref.index).dropna()
                x = v.get(c, np.nan)
                if c not in F.index or pd.isna(x) or len(pool) < 2:
                    parts[c][k] = 50.0; continue
                a = np.sort(pool.values)
                lo = np.searchsorted(a, x, 'left'); up = np.searchsorted(a, x, 'right')
                parts[c][k] = float((lo + up) / 2 / len(a) * 100)
            out[c] = round(float(np.mean(list(parts[c].values()))), 1)
        return out, parts
