"""A4 외국인 흐름 에이전트 — 지수가 콜벽 근처에 왔을 때 외국인이 선물·콜을 어떻게 사고팔았고, 그 뒤 지수가 어떻게 됐나.

날마다(개발 구간) 근월물(F0)·분기물(Q) 콜벽까지 거리(%)로 '벽 근처'(−band ~ +band%)를 정하고:
  - 그날 외국인 선물 순매수 / 콜 순매수 / 풋 순매수(조원) 부호별로 다음 m일 수익(다음 날 시가 → m일 뒤 종가)
  - 벽 근처에서 외국인이 선물을 팔면(또는 콜을 팔면) 하락하나 — 사용자 가설의 2단계를 매일 단위로
  - 벽이 커지는 동안(콜 미결제 5일 증가 상위) 외국인 콜 순매수가 많으면 위로 끌려가나 — 1단계
후보 신호를 A8 로 넘긴다.
"""
import os
import pickle
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lab_common as L  # noqa: E402

cfg = L.round_cfg().get('a04', {})
BANDS = cfg.get('bands', [1.0, 2.0])
MS = cfg.get('post_m', [1, 3, 5, 10])
TAGS = cfg.get('tags', ['F0', 'Q'])


def main():
    feat = pickle.load(open(os.path.join(L.LAB, 'work', 'lab_feat.pkl'), 'rb'))
    wide = feat['wide']
    k2 = L.k200_index(); td = k2.index
    F = L.flows().reindex(td)
    X = wide.reindex(td)
    fwd = {m: (k2['close'].shift(-m) / k2['open'].shift(-1) - 1) * 100 for m in MS}
    od = L.out_dir('a04')
    rows, cands = [], []
    dev = (td <= L.DEV_END) & (td >= pd.Timestamp('2015-01-01'))
    q_call5 = None
    # 라운드 6: 부호만이 아니라 크기·동시·연속 — 원인 분해에서 사슬 중 기준선과 가설 방향으로 다른 단계는 ④외국인 콜 순매도(76.5% vs 67.7%)뿐이고,
    # 최고 후보도 외국인 콜 흐름(벽 아래 콜 순매수 → 상승). 개발 구간 분위로 '대량'을 정하고, 선물·콜 같은 방향, 이틀 연속을 더한다(양방향 사전 등록).
    cf, ff = F['call_for'], F['fut_for']
    cq = cf[dev].quantile([0.25, 0.75]); fq = ff[dev].quantile([0.25, 0.75])
    flow_masks = []
    for who, col in (('외국인 선물', 'fut_for'), ('외국인 콜', 'call_for'), ('외국인 풋', 'put_for')):
        flow_masks += [(who, '순매도', F[col] < 0), (who, '순매수', F[col] > 0)]
    if cfg.get('flow_ext', True):
        flow_masks += [('외국인 콜 대량(개발 하위25%)', '순매도', cf <= cq.iloc[0]), ('외국인 콜 대량(개발 상위25%)', '순매수', cf >= cq.iloc[1]),
                       ('외국인 선물·콜 함께', '순매도', (cf < 0) & (ff < 0)), ('외국인 선물·콜 함께', '순매수', (cf > 0) & (ff > 0)),
                       ('외국인 선물 대량·콜 함께', '순매도', (ff <= fq.iloc[0]) & (cf < 0)), ('외국인 선물 대량·콜 함께', '순매수', (ff >= fq.iloc[1]) & (cf > 0)),
                       ('외국인 콜 이틀 연속', '순매도', (cf < 0) & (cf.shift(1) < 0)), ('외국인 콜 이틀 연속', '순매수', (cf > 0) & (cf.shift(1) > 0))]
    for tag in TAGS:
        dist = X.get(f'OW_{tag}_wall_dist%'); pdist = X.get(f'OW_{tag}_passed_wall_dist%')
        grow = X.get(f'OW_{tag}_callotm_chg5%')
        if dist is None: continue
        for band in BANDS:
            # 벽 바로 아래(아직 못 넘음, 거리 0~band%) 또는 막 넘어선 직후(지나간 벽이 −band~0%)
            near_below = (dist > 0) & (dist <= band)
            just_above = (pdist >= -band) & (pdist <= 0) if pdist is not None else pd.Series(False, index=td)
            for zone, zm in (('벽 바로 아래', near_below), ('벽 막 넘음', just_above)):
                for who, sgn, sm in flow_masks:
                        m_all = zm & sm
                        for m in MS:
                            v = fwd[m][m_all & dev].dropna()
                            if len(v) < 15: continue
                            rows.append({'시리즈': tag, '근처폭%': band, '구역': zone, '누가': who, '부호': sgn, 'm일': m, '날수': len(v),
                                         '하락%': (v < 0).mean() * 100, '평균%': v.mean()})
                            sig = td[(m_all.fillna(False)).values]
                            direction = -1 if (v < 0).mean() >= 0.5 else 1
                            t = pd.DataFrame({'signal': sig, 'exit': [L.exit_after(td, s, m) for s in sig]}).dropna()
                            cands.append({'id': f'A4_{tag}_{band}_{zone}_{who}_{sgn}_m{m}', 'agent': 'A4', 'family': 'flow_wall',
                                          'desc': f'{tag} {zone}(±{band}%)에서 {who} {sgn} → {m}일 {"하락" if direction < 0 else "상승"}', 'direction': direction, 'trades': t})
        # 1단계: 콜 물량이 늘고 외국인이 콜을 사면 위로
        if grow is not None:
            g_hi = grow >= grow[dev].quantile(0.8)
            for m in MS:
                mm = g_hi & (F['call_for'] > 0) & (dist > 0)
                v = fwd[m][mm & dev].dropna()
                if len(v) < 15: continue
                rows.append({'시리즈': tag, '근처폭%': np.nan, '구역': '콜 물량 5일 증가 상위20% + 벽 위', '누가': '외국인 콜', '부호': '순매수', 'm일': m,
                             '날수': len(v), '하락%': (v < 0).mean() * 100, '평균%': v.mean()})
                sig = td[(mm.fillna(False)).values]
                t = pd.DataFrame({'signal': sig, 'exit': [L.exit_after(td, s, m) for s in sig]}).dropna()
                cands.append({'id': f'A4_{tag}_grow_callbuy_m{m}', 'agent': 'A4', 'family': 'flow_build',
                              'desc': f'{tag} 콜 물량 증가 상위20% + 외국인 콜 순매수 → {m}일 상승', 'direction': 1, 'trades': t})
    pd.DataFrame(rows).round(3).to_csv(os.path.join(od, 'flow_wall_dev.csv'), index=False, encoding='utf-8')
    L.save_candidates('a04', cands)
    print('표', len(rows), '후보', len(cands))


if __name__ == '__main__':
    main()
