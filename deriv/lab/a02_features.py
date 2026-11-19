"""A2 정의 에이전트 — '콜 우위'를 여러 방식으로 정의해 날짜별 지표로 만든다(월물 근월·분기물, 위클리는 자료가 생기면).

시리즈: F0 = 오늘보다 뒤에 만기인 가장 가까운 월물, F1 = 그다음 월물, Q = 가장 가까운 분기물(3·6·9·12월).
  분기 만기가 지나면 Q 는 다음 분기물로 넘어간다(롤오버로 연장되는 물량 추적). 월물 4개 자료(opt_chainx)가 있으면 그것을, 없으면 가까운 2개 자료를 쓴다.
정의(시리즈마다)
  콜벽     = 현재가 위 행사가 중 콜 미결제 최대(K_ca1). 거리 %, 거리 σ(20일 변동성 × √(만기까지/250)).
  우위     = 그 행사가 미결제 ÷ 현재가 위 콜 미결제 합(share), 1위 ÷ 2위(ratio12), 상위 3개 비중(top3)
  콜/풋    = 현재가 위 콜 미결제 ÷ 현재가 아래 풋 미결제(otm_cp), 전체 콜/풋(cp_all)
  증가     = 콜벽 행사가 미결제 1·3·5일 변화(%), 현재가 위 콜 미결제 합 5일 변화(%)
  거래량벽 = 오늘 거래량 최대 콜 행사가(위쪽) 거리 %
  풋벽     = 현재가 아래 풋 미결제 최대 행사가 거리 %, share
  최대고통 = 만기 정산 시 매수자 손실이 가장 큰 행사가 거리 %
  (라운드 4) 벽 이동 = 최근 5일 벽이 위로·아래로 옮겨 간 날 수(같은 결제월), 5일 전 대비 벽 이동 %
  (라운드 4) 무게중심 = 현재가 ±15% 안 콜(풋) 미결제 가중 평균 행사가 거리 %, 콜−풋 무게중심 간격
출력: work/lab_feat.pkl {'wide': 날짜×지표, 'walls': 날짜·시리즈별 벽 행사가·만기일(경로 사건용)}
"""
import os
import pickle
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lab_common as L  # noqa: E402

WORK = os.path.join(L.LAB, 'work'); os.makedirs(WORK, exist_ok=True)


def series_feats(g, S, sig, dte):
    c = g[(g['cp'] == 'C') & (g['oi'] > 0)]; p = g[(g['cp'] == 'P') & (g['oi'] > 0)]
    r = {'dte': dte}
    if len(c) < 3 or len(p) < 3: return r, None
    ca = c[c['K'] > S]; pb = p[p['K'] < S]
    r['cp_all'] = c['oi'].sum() / p['oi'].sum()
    if len(ca) >= 2:
        o = ca.sort_values('oi', ascending=False)
        k1 = float(o['K'].iloc[0]); tot = o['oi'].sum()
        r['wall_dist%'] = (k1 / S - 1) * 100
        r['wall_dist_sig'] = np.log(k1 / S) / (sig * np.sqrt(max(dte, 1) / 250)) if sig > 0 else np.nan
        r['wall_share'] = o['oi'].iloc[0] / tot
        r['wall_ratio12'] = o['oi'].iloc[0] / max(o['oi'].iloc[1], 1)
        r['wall_top3'] = o['oi'].iloc[:3].sum() / tot
        r['wall_oi'] = float(o['oi'].iloc[0])
        r['callotm_oi'] = float(tot)
        if len(pb): r['otm_cp'] = tot / max(pb['oi'].sum(), 1)
        v = ca[ca['vol'] > 0]
        if len(v): r['volwall_dist%'] = (float(v.loc[v['vol'].idxmax(), 'K']) / S - 1) * 100
    else:
        k1 = np.nan
    if len(pb) >= 2:
        o = pb.sort_values('oi', ascending=False)
        r['pwall_dist%'] = (float(o['K'].iloc[0]) / S - 1) * 100
        r['pwall_share'] = o['oi'].iloc[0] / o['oi'].sum()
    Ks = np.sort(g['K'].unique())
    if len(Ks) > 3:
        pain = [((np.maximum(0, x - c['K']) * c['oi']).sum() + (np.maximum(0, p['K'] - x) * p['oi']).sum()) for x in Ks]
        r['maxpain_dist%'] = (Ks[int(np.argmin(pain))] / S - 1) * 100
    # 현재가 바로 위·아래 이외에 '현재가 아래 콜 최대'(이미 넘어선 벽)
    cb = c[c['K'] <= S]
    if len(cb): r['passed_wall_dist%'] = (float(cb.loc[cb['oi'].idxmax(), 'K']) / S - 1) * 100
    # 라운드 4: 무게중심(현재가 ±15% 안 미결제 가중 평균 행사가) — 벽 '하나' 대신 콜 물량 전체의 위치
    cw = c[(c['K'] >= S * 0.85) & (c['K'] <= S * 1.15)]; pw = p[(p['K'] >= S * 0.85) & (p['K'] <= S * 1.15)]
    if len(cw) >= 3 and cw['oi'].sum() > 0:
        r['ccent'] = float((cw['K'] * cw['oi']).sum() / cw['oi'].sum()); r['ccent_dist%'] = (r['ccent'] / S - 1) * 100
    if len(pw) >= 3 and pw['oi'].sum() > 0:
        r['pcent_dist%'] = (float((pw['K'] * pw['oi']).sum() / pw['oi'].sum()) / S - 1) * 100
        if 'ccent_dist%' in r: r['cpcent_gap%'] = r['ccent_dist%'] - r['pcent_dist%']
    return r, k1


def main():
    td = L.k200_index().index
    k2 = L.k200_index()
    sig20 = np.log(k2['close']).diff().rolling(20).std() * np.sqrt(250)
    src = 'x' if L.chain('x') is not None else 'm'
    ch = L.chain(src)
    print('옵션 자료', src, ch.shape)
    ch = ch[ch['ym'].str.len() == 6]
    exp_of = {ym: L.expiry_of_ym(ym, td) for ym in ch['ym'].unique()}
    ch['exp'] = ch['ym'].map(exp_of)
    oi_key = ch.set_index(['date', 'ym', 'cp', 'K'])['oi']
    oi_key = oi_key[~oi_key.index.duplicated()]
    dates = np.sort(ch['date'].unique())
    by_date = dict(tuple(ch.groupby('date')))
    pos = {d: i for i, d in enumerate(dates)}
    rows, walls = [], []
    last_k = {}
    khist = {}          # 라운드 4: 벽 이동 지표용 — 시리즈별 (ym, 벽 행사가) 최근 6일
    for d, g in ch.groupby('date'):
        Hd = float(k2['high'].get(d, np.nan))
        S = float(k2['close'].get(d, np.nan))
        if not np.isfinite(S): S = float(g['spot'].median())
        sg = float(sig20.get(d, np.nan))
        live = sorted([ym for ym in g['ym'].unique() if exp_of[ym] > d])
        picks = {}
        if live: picks['F0'] = live[0]
        if len(live) > 1: picks['F1'] = live[1]
        q = [ym for ym in live if int(ym[4:6]) in (3, 6, 9, 12)]
        if q: picks['Q'] = q[0]
        for tag, ym in picks.items():
            gg = g[g['ym'] == ym]
            dte = L.tdays_between(d, exp_of[ym], td)
            r, k1 = series_feats(gg, S, sg, dte)
            r.update({'date': d, 'tag': tag, 'ym': ym})
            if np.isfinite(k1 if k1 is not None else np.nan) and np.isfinite(Hd):
                # 라운드 3: 새 벽(오늘 벽 행사가가 바뀜)과 고가까지 거리 — 원인 분해에서 '새 벽이 고가 바로 위에 생기면 상승'이 보여 조합·기계학습에도 넣는다
                r['wall_to_high%'] = (k1 / Hd - 1) * 100
                if tag in last_k:
                    r['wall_new'] = float(k1 != last_k[tag])
                    r['newwall_near'] = float(k1 != last_k[tag] and 0 <= r['wall_to_high%'] <= 1.5)
                last_k[tag] = k1
            if np.isfinite(k1 if k1 is not None else np.nan):
                # 라운드 4: 벽 이동(같은 결제월 안에서) — 최근 5일 동안 벽이 위로 옮겨 간 날 수·아래로 옮겨 간 날 수, 5일 전 대비 벽 이동 폭
                hq = [x for x in khist.get(tag, []) if x[0] == ym][-5:] + [(ym, k1)]
                if len(hq) >= 2:
                    dk = np.diff([x[1] for x in hq])
                    r['wall_mig_up5'] = float((dk > 0).sum()); r['wall_mig_dn5'] = float((dk < 0).sum())
                    r['wall_mig_today'] = float(np.sign(dk[-1]))
                if len(hq) == 6: r['wall_shift5%'] = (k1 / hq[0][1] - 1) * 100
                khist[tag] = (khist.get(tag, []) + [(ym, k1)])[-6:]
                i = pos[d]
                for lag in (1, 3, 5):
                    if i - lag >= 0:
                        prev = oi_key.get((dates[i - lag], ym, 'C', k1), np.nan)
                        if prev and prev > 0: r[f'wall_oi_chg{lag}%'] = (r['wall_oi'] / prev - 1) * 100
                if i - 5 >= 0:
                    pg = by_date[dates[i - 5]]; pg = pg[(pg['ym'] == ym) & (pg['cp'] == 'C') & (pg['K'] > S)]
                    if len(pg) and pg['oi'].sum() > 0: r['callotm_chg5%'] = (r['callotm_oi'] / pg['oi'].sum() - 1) * 100
                walls.append({'date': d, 'tag': tag, 'ym': ym, 'exp': exp_of[ym], 'K': k1, 'S': S, 'share': r.get('wall_share'),
                              'ratio12': r.get('wall_ratio12'), 'otm_cp': r.get('otm_cp'), 'dist%': r.get('wall_dist%'), 'dist_sig': r.get('wall_dist_sig'), 'dte': dte, 'ccent': r.get('ccent', np.nan)})
            rows.append(r)
    F = pd.DataFrame(rows)
    feat_cols = [c for c in F.columns if c not in ('date', 'tag', 'ym', 'ccent')]
    wide = F.pivot_table(index='date', columns='tag', values=feat_cols)
    wide.columns = [f'OW_{t}_{c}' for c, t in wide.columns]
    wide = wide.sort_index()
    W = pd.DataFrame(walls)
    pickle.dump({'wide': wide, 'walls': W, 'source': src}, open(os.path.join(WORK, 'lab_feat.pkl'), 'wb'))
    od = L.out_dir('a02'); wide.describe().T.round(3).to_csv(os.path.join(od, 'feature_summary.csv'), encoding='utf-8')
    print(wide.shape, W.shape)


if __name__ == '__main__':
    main()
