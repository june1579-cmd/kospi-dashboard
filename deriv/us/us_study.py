"""미국 → 한국 선물·옵션 연동 연구(에이전트 A11) — 미리 정한 지표·문턱·보유 기간 전부를 후보로 내고, 판정은 연구소 A8(양방향 교차 검증)·A10(반증)에 맡긴다.

후보 = (지표 조건) × (방향 상승·하락 둘 다) × (보유 1·2·3·5·10·20일). 문턱은 그 시점까지의 3년 백분위(상위 10·20%, 하위 20·10%)와
미리 정한 절대값만 — 어느 구간 성적도 보고 정하지 않는다. 한국 t일 신호 → 다음 거래일 시가 진입(코스피200 선물), 독립 거래만 센다.
그리고 '미국 밤사이 등락 → 한국 시가 갭 / 시가 뒤 장중' 분해표를 따로 낸다(갭은 살 수 없는 구간이라 신호로 세지 않음).
"""
import json
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__)); DERIV = os.path.dirname(ROOT)
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(DERIV, 'lab'))
import lab_common as L  # noqa: E402
import us_features as UF  # noqa: E402

OUT = os.path.join(ROOT, 'out'); os.makedirs(OUT, exist_ok=True)
HS = [1, 2, 3, 5, 10, 20]
PCT = [('상위10%', lambda q: q >= 0.90), ('상위20%', lambda q: q >= 0.80), ('하위20%', lambda q: q <= 0.20), ('하위10%', lambda q: q <= 0.10)]
ABS = [('es_r1', '≤-1.5%', lambda v: v <= -1.5), ('es_r1', '≤-1%', lambda v: v <= -1.0), ('es_r1', '≥+1%', lambda v: v >= 1.0), ('es_r1', '≥+1.5%', lambda v: v >= 1.5),
       ('nq_r1', '≤-2%', lambda v: v <= -2.0), ('nq_r1', '≥+2%', lambda v: v >= 2.0), ('sox_r1', '≤-3%', lambda v: v <= -3.0), ('sox_r1', '≤-2%', lambda v: v <= -2.0),
       ('sox_r1', '≥+2%', lambda v: v >= 2.0), ('sox_r1', '≥+3%', lambda v: v >= 3.0), ('vix_ts', '>1(역전)', lambda v: v > 1.0), ('vix_ts', '<0.85', lambda v: v < 0.85),
       ('vix', '≥30', lambda v: v >= 30), ('vix', '≤13', lambda v: v <= 13), ('vix_c1', '≥+15%', lambda v: v >= 15), ('ewy_gap', '≤-1.5%p', lambda v: v <= -1.5), ('ewy_gap', '≥+1.5%p', lambda v: v >= 1.5)]


def mk(cid, fam, desc, mask, td):
    sig = td[np.asarray(mask.reindex(td).fillna(False).values, dtype=bool)]
    out = []
    if len(sig) < 12: return out
    for h in HS:
        tr = pd.DataFrame({'signal': sig, 'exit': [L.exit_after(td, s, h) for s in sig]}).dropna()
        for d, dn in ((1, '상승'), (-1, '하락')):
            out.append({'id': f'A11_{cid}_h{h}_{"U" if d > 0 else "D"}', 'agent': 'A11', 'family': fam, 'desc': f'{desc} → {h}일 {dn}', 'direction': d, 'trades': tr})
    return out


def first_day(mask, gap=5):
    """직전 gap 거래일 안에 같은 신호가 없던 첫날만."""
    m = mask.fillna(False).astype(bool); prev = m.shift(1).rolling(gap, min_periods=1).max().fillna(0).astype(bool)
    return m & ~prev


def main():
    B = UF.build(); F, Q, td, k2 = B['F'], B['Q'], B['td'], B['k2']
    fut = L.prices()['K200F']
    F.round(4).to_csv(os.path.join(OUT, 'features_kr.csv.gz')); Q.round(4).to_csv(os.path.join(OUT, 'features_pct.csv.gz'))
    cands = []; grp = {f: g for g, fs in UF.GROUP.items() for f in fs}
    for f in [x for fs in UF.GROUP.values() for x in fs]:
        if f not in F: continue
        for nm, fn in PCT:
            cands += mk(f'{f}_{nm}', grp[f], f'{UF.NAMES[f]} 3년 백분위 {nm}', fn(Q[f]) & F[f].notna(), td)
    for f, nm, fn in ABS:
        cands += mk(f'{f}_abs{nm}', grp[f] + '(절대값)', f'{UF.NAMES[f]} {nm}', fn(F[f]) & F[f].notna(), td)
    cands += mk('vix_ts_first', '변동성(절대값)', 'VIX 기간 구조 역전 첫날(직전 5일 없음)', first_day(F['vix_ts'] > 1), td)
    hi = lambda f, p=0.80: (Q[f] >= p); lo = lambda f, p=0.20: (Q[f] <= p)
    PAIRS = [('es_dn_bw', 'S&P 선물 ≤-1.5% + VIX 기간 구조 역전', (F['es_r1'] <= -1.5) & (F['vix_ts'] > 1)),
             ('es_dn_ct', 'S&P 선물 ≤-1.5% + VIX 기간 구조 정상', (F['es_r1'] <= -1.5) & (F['vix_ts'] <= 1)),
             ('sox_dn_kup', '반도체 ≤-3% + 코스피200 당일 상승', (F['sox_r1'] <= -3) & (F['k2_r1'] > 0)),
             ('for_hi_es_hi', '외국인 선물 3일 순매수 상위20% + S&P 선물 5일 상위20%', hi('for_fut3') & hi('es_r5')),
             ('for_lo_es_lo', '외국인 선물 3일 순매수 하위20% + S&P 선물 5일 하위20%', lo('for_fut3') & lo('es_r5')),
             ('for_hi_es_lo', '외국인 선물 3일 순매수 상위20% + S&P 선물 5일 하위20%(엇갈림)', hi('for_fut3') & lo('es_r5')),
             ('for_lo_es_hi', '외국인 선물 3일 순매수 하위20% + S&P 선물 5일 상위20%(엇갈림)', lo('for_fut3') & hi('es_r5')),
             ('vix_hi_vk_lo', 'VIX 상위10% + VKOSPI−VIX 하위20%', hi('vix', 0.9) & lo('vk_vix')),
             ('lev_lo_bw', 'S&P 레버리지 펀드 순포지션 하위10% + VIX 기간 구조 역전', lo('es_lev', 0.1) & (F['vix_ts'] > 1)),
             ('am_hi_vix_lo', 'S&P 자산운용 순포지션 상위10% + VIX 하위20%', hi('es_am', 0.9) & lo('vix')),
             ('pcr_hi_es_dn', '미국 주식 풋콜 상위10% + S&P 선물 5일 하위20%', hi('pcr_eq', 0.9) & lo('es_r5'))]
    for cid, desc, m in PAIRS: cands += mk(cid, '조합(미리 정함)', desc, m, td)
    print('후보', len(cands), flush=True)
    L.save_candidates('a11', cands)

    # ---- 분해표: 미국 밤사이 등락 → 한국 갭 / 장중 / 종가까지 (코스피200 선물)
    o1 = fut['open'].shift(-1); c1 = fut['close'].shift(-1); c0 = fut['close']
    D = pd.DataFrame({'us': F['es_r1'], 'sox': F['sox_r1'], 'gap': (o1 / c0 - 1) * 100, 'oc': (c1 / o1 - 1) * 100, 'cc': (c1 / c0 - 1) * 100}).dropna(subset=['gap', 'oc'])
    rows = []
    PER = [('2010~2014', '2010-01-01', '2014-12-31'), ('2015~2019', '2015-01-01', '2019-12-31'), ('2020~2023', '2020-01-01', '2023-12-31'), ('2024~', '2024-01-01', '2100-01-01'), ('전체 2010~', '2010-01-01', '2100-01-01')]
    for src, snm in (('us', 'S&P500 선물'), ('sox', '필라델피아 반도체')):
        for pn, a, b in PER:
            x = D[(D.index >= a) & (D.index <= b)].dropna(subset=[src])
            if len(x) < 60: continue
            rows.append({'미국 지표': snm, '기간': pn, '구분': '전체', '날 수': len(x), '갭 상관': x[src].corr(x['gap']), '장중 상관': x[src].corr(x['oc']),
                         '갭 같은 방향%': (np.sign(x[src]) == np.sign(x['gap'])).mean() * 100, '장중 같은 방향%': (np.sign(x[src]) == np.sign(x['oc'])).mean() * 100,
                         '갭 평균%': x['gap'].mean(), '장중 평균%': x['oc'].mean(), '장중 상승%': (x['oc'] > 0).mean() * 100})
            for bn, m in (('미국 ≤-1.5%', x[src] <= -1.5), ('미국 -1.5~-0.5%', (x[src] > -1.5) & (x[src] <= -0.5)), ('미국 ±0.5% 안', x[src].abs() < 0.5),
                          ('미국 +0.5~+1.5%', (x[src] >= 0.5) & (x[src] < 1.5)), ('미국 ≥+1.5%', x[src] >= 1.5)):
                y = x[m]
                if len(y) < 10: continue
                rows.append({'미국 지표': snm, '기간': pn, '구분': bn, '날 수': len(y), '갭 상관': np.nan, '장중 상관': np.nan, '갭 같은 방향%': np.nan, '장중 같은 방향%': np.nan,
                             '갭 평균%': y['gap'].mean(), '장중 평균%': y['oc'].mean(), '장중 상승%': (y['oc'] > 0).mean() * 100})
    pd.DataFrame(rows).round(3).to_csv(os.path.join(OUT, 'decomp.csv'), index=False, encoding='utf-8')
    json.dump({'candidates': len(cands), 'features': int(F.shape[1]), 'kr_last': str(td[-1].date()), 'us_last': str(B['U'].index[-1].date()),
               'at_kst': pd.Timestamp.now(tz='Asia/Seoul').strftime('%Y-%m-%d %H:%M')}, open(os.path.join(OUT, 'study_meta.json'), 'w'), ensure_ascii=False)


if __name__ == '__main__':
    main()
