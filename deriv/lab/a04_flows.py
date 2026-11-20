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
    # 갈래 B 라운드 7(a04.flow_sum3): 하루치 부호 대신 3일 누적 순매수 부호 — 하루 흐름은 잡음이 커서 '같은 신호가 해마다 고르지 않음'의 한 원인일 수 있음.
    #   라운드 8(a04.flow_sum: 창 목록): 3일 누적이 개발 하한을 63%→68% 로 올려(풋 3일 누적 순매수 → 5·10일 상승 개발 통과) 5·10일 창도 시험.
    for nsum in (cfg.get('flow_sum') or ([3] if cfg.get('flow_sum3') else [])):
        for who, col in ((f'외국인 선물 {nsum}일 누적', 'fut_for'), (f'외국인 콜 {nsum}일 누적', 'call_for'), (f'외국인 풋 {nsum}일 누적', 'put_for')):
            s3 = F[col].rolling(nsum, min_periods=nsum).sum()
            flow_masks += [(who, '순매도', s3 < 0), (who, '순매수', s3 > 0)]
    # 갈래 B 라운드 7(a04.sigma_bands): '벽 근처'를 고정 %가 아니라 변동성 단위로 — 직전 20일 일간 등락 표준편차 × √5(1주 σ) × k.
    #   2017 처럼 조용한 해의 2% 는 먼 거리, 2020 처럼 거친 해의 2% 는 바로 옆이라 해마다 '근처'의 뜻이 달라짐(해마다 성적이 고르지 않은 원인 후보). 그날 종가까지 아는 값.
    sig5 = (k2['close'].pct_change().rolling(20).std() * np.sqrt(5) * 100).reindex(td)
    band_list = [(b, f'{b}%', b, False) for b in BANDS] + [(f's{k}', f'{k}σ', sig5 * k, True) for k in (cfg.get('sigma_bands') or [])]
    # 갈래 A 라운드 14(a04.wall_age: [N, …], 설정 없으면 꺼짐 → 갈래 B 영향 없음): '천장 지킴' — 라운드 7·11·13 에서 가설 방향(하락)은
    #   천장이 옮겨 가지 않을 때(같은 자리 연장)만 나왔는데, 만기일 사건이라 연 1~2번꼴이라 거래 20개를 못 채움. 같은 뜻을 날마다로:
    #   그 시리즈 콜벽 행사가가 N거래일 이상 같은 자리(같은 결제월, ALL 은 결제월 무관)인 날 + 벽 바로 아래 + 외국인 흐름 → m일. 양방향 사전 등록.
    W = feat.get('walls')
    age_of = {}
    if cfg.get('wall_age') and W is not None and len(W):
        W = W.copy(); W['date'] = pd.to_datetime(W['date'])   # 벽 없는 날(K 빈칸)은 연속을 끊는 날로 둠
        W = W.drop_duplicates(['date', 'tag'], keep='last')
        for tag, g in W.sort_values('date').groupby('tag'):
            g = g.set_index('date')
            key = g['K'].astype(float).round(3).astype(str) + ('' if tag == 'ALL' else '|' + g['ym'].astype(str))
            run = key.ne(key.shift()).cumsum()
            age_of[tag] = g.groupby(run).cumcount().add(1).where(g['K'].notna()).reindex(td)   # 오늘 포함 같은 벽 연속 거래일 수(그날 장 마감 뒤 아는 값)
    age_flows = [x for x in flow_masks if x[0] in ('외국인 선물', '외국인 콜', '외국인 풋', '외국인 선물·콜 함께', '외국인 선물 대량·콜 함께')]
    for tag in TAGS:
        dist = X.get(f'OW_{tag}_wall_dist%'); pdist = X.get(f'OW_{tag}_passed_wall_dist%')
        grow = X.get(f'OW_{tag}_callotm_chg5%')
        if dist is None: continue
        if tag in age_of:
            for na in cfg.get('wall_age'):
                held = age_of[tag] >= na
                for band in BANDS:
                    zm = held & (dist > 0) & (dist <= band)
                    for who, sgn, sm in [('흐름 무관', '', pd.Series(True, index=td))] + age_flows:
                        m_all = zm & sm
                        for m in MS:
                            v = fwd[m][m_all & dev].dropna()
                            rows.append({'시리즈': tag, '근처폭%': f'{band}%', '구역': f'같은 벽 {na}일 이상 + 벽 바로 아래', '누가': who, '부호': sgn, 'm일': m,
                                         '날수': len(v), '하락%': (v < 0).mean() * 100 if len(v) else np.nan, '평균%': v.mean() if len(v) else np.nan})
                            if len(v) < 15: continue
                            sig = td[(m_all.fillna(False)).values]
                            t = pd.DataFrame({'signal': sig, 'exit': [L.exit_after(td, s, m) for s in sig]}).dropna()
                            for direction in (-1, 1):   # 양방향 사전 등록(가설 = 하락)
                                cands.append({'id': f'A4age_{tag}_{na}d_{band}_{who}_{sgn}_m{m}_{"dn" if direction < 0 else "up"}', 'agent': 'A4',
                                              'family': 'flow_wall_age',
                                              'desc': f'{tag} 같은 콜벽 {na}일 이상 유지 + 벽 바로 아래(±{band}%)' + (f' + {who} {sgn}' if sgn else '') +
                                                      f' → {m}일 {"하락" if direction < 0 else "상승"}',
                                              'direction': direction, 'trades': t})
        for band_key, band_lab, band, is_sig in band_list:
            # 벽 바로 아래(아직 못 넘음, 거리 0~band%) 또는 막 넘어선 직후(지나간 벽이 −band~0%)
            near_below = (dist > 0) & (dist <= band)
            just_above = (pdist >= -band) & (pdist <= 0) if pdist is not None else pd.Series(False, index=td)
            for zone, zm in (('벽 바로 아래', near_below), ('벽 막 넘음', just_above)):
                for who, sgn, sm in flow_masks:
                        m_all = zm & sm
                        for m in MS:
                            v = fwd[m][m_all & dev].dropna()
                            if len(v) < 15: continue
                            rows.append({'시리즈': tag, '근처폭%': band_lab, '구역': zone, '누가': who, '부호': sgn, 'm일': m, '날수': len(v),
                                         '하락%': (v < 0).mean() * 100, '평균%': v.mean()})
                            sig = td[(m_all.fillna(False)).values]
                            direction = -1 if (v < 0).mean() >= 0.5 else 1
                            t = pd.DataFrame({'signal': sig, 'exit': [L.exit_after(td, s, m) for s in sig]}).dropna()
                            cands.append({'id': f'A4_{tag}_{band_key}_{zone}_{who}_{sgn}_m{m}', 'agent': 'A4', 'family': 'flow_wall_sigma' if is_sig else 'flow_wall',
                                          'desc': f'{tag} {zone}(±{band_lab})에서 {who} {sgn} → {m}일 {"하락" if direction < 0 else "상승"}', 'direction': direction, 'trades': t})
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
