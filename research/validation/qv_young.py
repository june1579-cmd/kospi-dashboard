# -*- coding: utf-8 -*-
"""상장 1~2년 된 종목에도 새 점수식이 맞는가 — 대상 조건을 '날짜 고정'에서 '52주 이상 거래'로 풀었을 때의 검증

qv.py 와 같은 기준일·결과·평점 규칙. 새 식(ref/qv_formula.json)의 성분으로
  strict : 지금 검증의 대상(점수 순위·방어1은 104주 중 100주 이상 거래)
  relaxed: 52주 중 40주 이상 거래(상장 약 1년)면 넣음. 방어1 성장 조건은 2년이 안 되면 상장 뒤(있는 기간) 수익률 +30%
  young  : relaxed 중 104주 거래가 100주 미만인 종목만(상장 1~2년)
을 각각 채점한다. 안정 관찰 대상은 qv.py 에서 이미 '104주 중 50주 이상·급락 주 5번 이상'이라 relaxed 와 같다.
"""
import os, json, time
import numpy as np, pandas as pd
import qv as Q

OUT = Q.OUT; T0 = time.time()


def main():
    F_ = json.load(open(os.path.join(Q.ROOT, 'ref', 'qv_formula.json')))
    W = Q.load_weekly(); R = W[0]; IX = Q.load_index(R.index)
    S = {k: Q.snaps(k) for k in ('CAP', 'FUND', 'FR', 'SHORT', 'SECT')}
    DART, _ = Q.load_dart()
    anchors = []
    for q in pd.date_range('2018-03-31', '2025-09-30', freq='QE'):
        i = int(R.index.searchsorted(q, side='right')) - 1
        if i + Q.H < len(R.index) and i >= 103: anchors.append(i)
    if Q.ONLY: anchors = anchors[:int(Q.ONLY)]
    RES = {k: {'strict': [], 'relaxed': [], 'young': [], 'old_only': []} for k in ('st', 'sc', 'd1')}
    cnt = []
    for i in anchors:
        t = R.index[i]
        F = Q.features(i, W, IX, S['CAP'], S['FUND'], S['FR'], S['SHORT'], S['SECT'], DART)
        O, kret = Q.outcomes(i, R, IX)
        r104 = R.iloc[i - 103:i + 1].values
        F['ret_avail'] = np.where(F.nobs52 >= 40, np.nanprod(r104 + 1, axis=0)[R.columns.get_indexer(F.index)] - 1, np.nan)
        nm = F['name'].astype(str); base = ~nm.str.contains(Q.EXCL)
        U = Q.universes(F)
        A_r = base & (F.mcap >= 5e10) & (F.tv20 >= 1e8) & (F.nobs52 >= 40) & F.beta2y.notna()
        g_ret = np.where(F.nobs104 >= 100, F.ret2y, F.ret_avail)
        G_r = A_r & (pd.Series(g_ret, index=F.index) >= 0.30) & (F.ret_prev > 0) & (F.ytd > 0)
        young = F.nobs104 < 100
        sets = {'st': {'strict': U['st'], 'relaxed': U['st']}, 'sc': {'strict': U['sc'], 'relaxed': A_r}, 'd1': {'strict': U['d1'], 'relaxed': G_r}}
        for k in ('st', 'sc', 'd1'):
            for nm_, msk in (('strict', sets[k]['strict']), ('relaxed', sets[k]['relaxed']), ('young', sets[k]['relaxed'] & young), ('old_only', sets[k]['relaxed'] & ~young)):
                Uk = F[msk.reindex(F.index).fillna(False)]
                if len(Uk) < 20: continue
                keys = F_[k]['keys']
                s = np.mean([Q.pct(Uk[c].where(Uk[c] > 0, 99) if c == 'pbr' else Uk[c], Q.CN[c][0]).values for c in keys], axis=0)
                s = pd.Series(s, index=Uk.index); o = O.reindex(Uk.index)
                q5 = s >= s.quantile(0.8); q1 = s <= s.quantile(0.2)
                RES[k][nm_].append({'anchor': str(t.date()), 'kret': kret, 'ic_safe': Q.rc(s, o.fwd_mdd), 'ic_ret': Q.rc(s, o.fwd_ex), 'ic_ind': Q.rc(s, -o.fwd_beta),
                                    'q5_ex': o.fwd_ex[q5].mean(), 'q1_ex': o.fwd_ex[q1].mean(), 'q5_mdd': o.fwd_mdd[q5].mean(), 'q1_mdd': o.fwd_mdd[q1].mean(),
                                    'q5_beta': o.fwd_beta[q5].mean(), 'q1_beta': o.fwd_beta[q1].mean(), 'n': len(Uk)})
        cnt.append({'anchor': str(t.date()), **{f'{k}_{s}': int(sets[k][s].sum()) for k in sets for s in ('strict', 'relaxed')},
                    **{f'{k}_young': int((sets[k]['relaxed'] & young).sum()) for k in sets}})
        Q.log('기준일', t.date(), cnt[-1], f'{time.time() - T0:.0f}초')
    out = {'rule': 'qv.py 와 같은 평점 규칙. 확인 구간 = 2022~2025 기준일', 'counts': cnt, 'lists': {}}
    for k in RES:
        out['lists'][k] = {}
        for nm_, per in RES[k].items():
            chk = [p for p in per if p['anchor'] >= '2022']; des = [p for p in per if p['anchor'] < '2022']
            out['lists'][k][nm_] = {'check': Q.rate(chk), 'design': Q.rate(des), 'all': Q.rate(per), 'n_mean': round(float(np.mean([p['n'] for p in chk])), 1) if chk else 0}
            Q.log(k, nm_, out['lists'][k][nm_]['check'])
    json.dump(out, open(os.path.join(OUT, 'young.json'), 'w'), ensure_ascii=False, indent=1, default=float)


if __name__ == '__main__':
    try:
        main()
    finally:
        open(os.path.join(OUT, 'log_young.txt'), 'w', encoding='utf-8').write('\n'.join(Q.LOG))
