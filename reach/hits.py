# 날짜별 적중 분석(2026-11-26): 최근 거래일마다 16:20판·08:30판·09:10판이 낸 값과 실제(코스피200 현물, 전날 종가 기준 고가·저가)를 맞춰 본다.
# 실제로 낸 기록(docs/reach/data/log/날짜_판.json)이 있으면 그것을 쓰고, 없으면 그날 전까지 자료로만 다시 학습해 계산한 값(재계산)을 쓴다.
# 09:10판 재계산은 시가까지만 반영(장 초반 고가·저가 조건은 과거 분봉이 없어 빠짐). 결과: docs/reach/data/hits.json
import json, os, sys
import numpy as np, pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from reach.model import Dist, feats, ZQ

OUT = os.path.join(ROOT, 'docs', 'reach', 'data'); LOG = os.path.join(OUT, 'log')
BOARDS = ('eve', 'pre', 'post')


def _rec(p_up, p_dn, hq, lq, hi, lo, src):
    """hq·lq = (10%, 90%, 중간) 예상 고가·저가(%)"""
    r = dict(src=src, p_up1=round(float(p_up), 1), p_dn1=round(float(p_dn), 1), hi_q10=round(float(hq[0]), 2), hi_q90=round(float(hq[1]), 2),
             lo_q10=round(float(lq[0]), 2), lo_q90=round(float(lq[1]), 2), hi_q50=round(float(hq[2]), 2), lo_q50=round(float(lq[2]), 2))
    if hi is not None and not np.isnan(hi):
        r.update(hi_in=bool(hq[0] <= hi <= hq[1]), lo_in=bool(lq[0] <= lo <= lq[1]), up1=bool(hi >= 1), dn1=bool(lo <= -1),
                 hi_diff=round(float(hi - hq[2]), 2), lo_diff=round(float(lo - lq[2]), 2))
    return r


def build(D, n_days=30, n_sum=20):
    idx = D.index; rows = []
    # 실제가 있는 마지막 n_days 거래일(행 t 의 목표 = t 다음 거래일의 고가·저가)
    ok = np.where(D['S_up_c'].notna().to_numpy())[0][-n_days:]
    dates = list(idx[1:])                                                     # 행 t → 예측 날짜 = 다음 행 날짜
    for i in ok:
        d = dates[i] if i < len(dates) else None
        if d is None: continue
        hi, lo = float(D['S_up_c'].iloc[i]), float(D['S_dn_c'].iloc[i]); rec = dict(date=d, hi=round(hi, 2), lo=round(lo, 2), boards={})
        for b in BOARDS:
            lp = os.path.join(LOG, f'{d}_{b}.json')
            if os.path.exists(lp):
                L = json.load(open(lp, encoding='utf-8'))['ladders']; U, Dn = L['S_c_up'], L['S_c_dn']
                rec['boards'][b] = _rec(U['p'][9], Dn['p'][9], (U['q']['0.1'], U['q']['0.9'], U['q']['0.5']), (Dn['q']['0.1'], Dn['q']['0.9'], Dn['q']['0.5']), hi, lo, '기록')
                continue
            tr = D.iloc[:i]; mu, sc = feats(b, 'S', False); res = {}
            for side, yc in (('up', 'S_up_c'), ('dn', 'S_dn_c')):
                y = tr[yc].to_numpy(float); m = ~np.isnan(y); M = Dist(mu, sc, 'S').fit(tr[m], y[m]); row = D.iloc[[i]]
                p = M.ladder(row, side, [1.0])[0][0] * 100; mu_, s_ = M.loc_scale(row)
                q = [float(mu_[0] + s_[0] * np.interp(qq, ZQ, M.z)) for qq in (0.1, 0.9, 0.5)]; res[side] = (p, q)
            rec['boards'][b] = _rec(res['up'][0], res['dn'][0], res['up'][1], res['dn'][1], hi, lo, '재계산' + ('(시가까지만)' if b == 'post' else ''))
        rows.append(rec)
    last = rows[-n_sum:]; summ = {}
    for b in BOARDS:
        x = [r['boards'][b] for r in last if b in r['boards'] and 'hi_in' in r['boards'][b]]
        if not x: continue
        bu = np.mean([(r['p_up1'] / 100 - r['up1']) ** 2 for r in x]); bd = np.mean([(r['p_dn1'] / 100 - r['dn1']) ** 2 for r in x])
        fu = np.mean([r['up1'] for r in x]); fd = np.mean([r['dn1'] for r in x])
        summ[b] = dict(n=len(x), hi_in=round(100 * np.mean([r['hi_in'] for r in x]), 1), lo_in=round(100 * np.mean([r['lo_in'] for r in x]), 1),
                       brier_up1=round(float(bu), 3), brier_dn1=round(float(bd), 3), brier_up1_base=round(float(fu * (1 - fu)), 3), brier_dn1_base=round(float(fd * (1 - fd)), 3),
                       live=sum(1 for r in x if r['src'] == '기록'), mae_hi=round(float(np.mean([abs(r['hi_diff']) for r in x])), 2), mae_lo=round(float(np.mean([abs(r['lo_diff']) for r in x])), 2))
    return dict(built=pd.Timestamp.now(tz='Asia/Seoul').strftime('%Y-%m-%d %H:%M KST'), rows=rows[::-1], summary=summ, n_sum=n_sum,
                note='예상 = 그 판의 중간(50%) 예상 고가·저가, 차이 = 실제 − 예상(%p). 범위 적중 = 실제 고가(저가)가 그 판의 10~90% 예상 범위 안. 정확한 범위라면 약 80%. 브라이어 = +1%·−1% 확률의 점수(낮을수록 좋음), base = 그 기간 실제 빈도로 찍었을 때')


def save(D):
    H = build(D); os.makedirs(OUT, exist_ok=True); json.dump(H, open(os.path.join(OUT, 'hits.json'), 'w', encoding='utf-8'), ensure_ascii=False)
    print('적중표 저장', len(H['rows']), '일 ·', {b: (v['hi_in'], v['lo_in']) for b, v in H['summary'].items()}, flush=True)
    return H
