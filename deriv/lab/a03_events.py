"""A3 경로 가설 에이전트 — "콜 물량이 우세한 행사가가 있으면 지수를 그 위로 올린 뒤(1단계) 외국인이 판다(2단계)".

지난 검증(E1 콜벽 거리 → h일 수익의 순위상관)은 '정해진 h일 뒤 수익'만 봐서, 올라갔다가 내려오는 두 단계 모양을 놓칠 수 있었다.
여기서는 만기 주기마다 한 번씩(관측일 = 만기까지 N거래일 남은 날) 벽을 정하고 경로를 따라간다.
  1단계: 관측일 다음 날 ~ 만기 사이에 코스피200 고가가 벽에 닿았나(touch), 종가로 넘었나(cross).
         무작위 걷기(20일 변동성)였다면 닿았을 확률(2·(1−Φ(ln(K/S)/(σ√T))))과 비교 — 벽이 '끌어당기는' 힘이 있나.
  2단계: 처음 종가로 넘은 날(t*) 다음 날 시가 → m일 뒤 종가 수익, 그 사이 외국인 선물 순매수.
통계(서술)는 개발 구간(~2023)만. 후보 신호는 전체 기간 날짜를 만들어 A8 에 넘긴다(잠금 구간 결과는 A8 만 계산).
"""
import os
import pickle
import sys

import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lab_common as L  # noqa: E402

cfg = L.round_cfg().get('a03', {})
TAGS = cfg.get('tags', ['F0', 'F1', 'Q'])
OBS = cfg.get('obs_dte', [20, 15, 10, 5])
MS = cfg.get('post_m', [1, 3, 5, 10, 20])


def main():
    feat = pickle.load(open(os.path.join(L.LAB, 'work', 'lab_feat.pkl'), 'rb'))
    W = feat['walls'].dropna(subset=['K'])
    k2 = L.k200_index(); td = k2.index
    sig20 = np.log(k2['close']).diff().rolling(20).std() * np.sqrt(250)
    F = L.flows()
    ffor = F['fut_for'].reindex(td)
    ev = []
    for (tag, ym), g in W[W['tag'].isin(TAGS)].groupby(['tag', 'ym']):
        g = g.sort_values('date'); exp = g['exp'].iloc[0]
        for N in OBS:
            o = g[(g['dte'] <= N) & (g['dte'] >= 1)]
            if not len(o): continue
            r0 = o.iloc[0]; d = r0['date']; K = r0['K']; S = r0['S']
            path = k2[(k2.index > d) & (k2.index <= exp)]
            rec = {'tag': tag, 'ym': ym, 'obs_dte': N, 'date': d, 'exp': exp, 'K': K, 'S': S, 'dte': r0['dte'],
                   'share': r0['share'], 'ratio12': r0['ratio12'], 'otm_cp': r0['otm_cp'], 'dist%': r0['dist%'], 'dist_sig': r0['dist_sig'],
                   'year': d.year, 'complete': bool(exp <= td[-1])}
            sg = sig20.get(d, np.nan); T = max(r0['dte'], 1) / 250
            rec['rw_touch'] = 2 * (1 - stats.norm.cdf(np.log(K / S) / (sg * np.sqrt(T)))) if sg > 0 else np.nan
            if rec['complete'] and len(path):
                rec['touch'] = bool((path['high'] >= K).any())
                rec['cross'] = bool((path['close'] >= K).any())
                rec['settle_above'] = bool(path['close'].iloc[-1] >= K)
                rec['ret_to_exp%'] = (path['close'].iloc[-1] / S - 1) * 100
                if rec['cross']:
                    t = path.index[np.argmax(path['close'].values >= K)]
                    rec['cross_date'] = t
                    rec['days_to_cross'] = int(((td > d) & (td <= t)).sum())
                    i = td.get_loc(t)
                    for m in MS:
                        if i + m < len(td) and i + 1 < len(td):
                            rec[f'post{m}%'] = (k2['close'].iloc[i + m] / k2['open'].iloc[i + 1] - 1) * 100
                    if i + 5 < len(td): rec['for_fut_5d'] = float(ffor.iloc[i + 1:i + 6].sum())
                    if i + 1 < len(td): rec['for_fut_1d'] = float(ffor.iloc[i + 1])
                    rec['for_fut_pre5'] = float(ffor.iloc[max(0, i - 4):i + 1].sum())
                    after = k2['close'].iloc[i + 1:i + 11]
                    if len(after): rec['max_dd_10d%'] = (after.min() / k2['close'].iloc[i] - 1) * 100; rec['max_up_10d%'] = (after.max() / k2['close'].iloc[i] - 1) * 100
            ev.append(rec)
    E = pd.DataFrame(ev)
    od = L.out_dir('a03'); E.to_csv(os.path.join(od, 'events_all.csv'), index=False, encoding='utf-8')
    dev = E[(E['date'] <= L.DEV_END) & (E['complete'])].copy()
    # 우위 단계(개발 구간 분위수)
    q = {c: dev[c].quantile([0.5, 0.75]).values for c in ('share', 'ratio12', 'otm_cp')}
    def tiers(df):
        return {'전체': pd.Series(True, index=df.index),
                '집중 상위50%': df['share'] >= q['share'][0], '집중 상위25%': df['share'] >= q['share'][1],
                '1위/2위 상위25%': df['ratio12'] >= q['ratio12'][1], '콜/풋 상위25%': df['otm_cp'] >= q['otm_cp'][1],
                '집중25%+콜/풋25%': (df['share'] >= q['share'][1]) & (df['otm_cp'] >= q['otm_cp'][1]),
                '가까움(≤1σ)': df['dist_sig'] <= 1, '가까움+집중25%': (df['dist_sig'] <= 1) & (df['share'] >= q['share'][1])}
    T1, T2 = [], []
    for (tag, N), g in dev.groupby(['tag', 'obs_dte']):
        for tn, m in tiers(g).items():
            x = g[m]
            if len(x) < 8: continue
            T1.append({'시리즈': tag, '관측(만기까지 일)': N, '조건': tn, '주기수': len(x), '닿음%': x['touch'].mean() * 100, '무작위걷기 예상%': x['rw_touch'].mean() * 100,
                       '종가로 넘음%': x['cross'].mean() * 100, '만기에 위%': x['settle_above'].mean() * 100, '평균 거리σ': x['dist_sig'].mean(),
                       '닿음 p(무작위 대비)': stats.binomtest(int(x['touch'].sum()), len(x), float(np.clip(x['rw_touch'].mean(), 0.01, 0.99))).pvalue})
            c = x[x['cross'] == True]
            for mm in MS:
                col = f'post{mm}%'
                if col not in c: continue
                v = c[col].dropna()
                if len(v) < 6: continue
                sold = c.loc[v.index, 'for_fut_5d'] < 0 if 'for_fut_5d' in c else pd.Series(False, index=v.index)
                T2.append({'시리즈': tag, '관측': N, '조건': tn, 'm일': mm, '넘은 주기': len(v), '하락%': (v < 0).mean() * 100, '평균%': v.mean(),
                           '외국인 5일 순매도%': sold.mean() * 100, '순매도 때 하락%': (v[sold] < 0).mean() * 100 if sold.any() else np.nan,
                           '순매수 때 하락%': (v[~sold] < 0).mean() * 100 if (~sold).any() else np.nan})
    pd.DataFrame(T1).round(3).to_csv(os.path.join(od, 'touch_dev.csv'), index=False, encoding='utf-8')
    pd.DataFrame(T2).round(3).to_csv(os.path.join(od, 'post_cross_dev.csv'), index=False, encoding='utf-8')
    by_year = dev.groupby(['tag', 'obs_dte', 'year']).agg(주기=('touch', 'size'), 닿음=('touch', 'mean'), 예상=('rw_touch', 'mean'), 넘음=('cross', 'mean')).round(3)
    by_year.to_csv(os.path.join(od, 'touch_by_year_dev.csv'), encoding='utf-8')
    # 후보 신호(전체 기간 날짜, 문턱은 개발 구간 분위수)
    cands = []
    allE = E.copy()
    for (tag, N), g in allE.groupby(['tag', 'obs_dte']):
        for tn, m in tiers(g).items():
            x = g[m]
            # (1) 끌어당김: 관측일에 사서 만기 종가까지(벽이 현재가 위에 있고 2σ 안)
            y = x[(x['dist_sig'] > 0) & (x['dist_sig'] <= 2)]
            if len(y) >= 10:
                cands.append({'id': f'A3_magnet_{tag}_{N}_{tn}', 'agent': 'A3', 'desc': f'{tag} 콜벽(만기 {N}일 전, {tn}) → 만기까지 상승', 'direction': 1,
                              'trades': pd.DataFrame({'signal': y['date'].values, 'exit': y['exp'].values}), 'family': 'magnet'})
            # (2) 넘은 뒤 하락: 처음 종가로 넘은 날 신호 → m일 뒤
            cr = x.dropna(subset=['cross_date']) if 'cross_date' in x else x.iloc[0:0]
            cr = cr.drop_duplicates(['tag', 'ym'])
            for mm in MS:
                if len(cr) < 10: continue
                ex = [L.exit_after(td, s, mm) for s in cr['cross_date']]
                t = pd.DataFrame({'signal': cr['cross_date'].values, 'exit': ex}).dropna()
                cands.append({'id': f'A3_crossdown_{tag}_{N}_{tn}_m{mm}', 'agent': 'A3', 'desc': f'{tag} 콜벽({tn}) 종가 돌파 다음 날부터 {mm}일 하락', 'direction': -1,
                              'trades': t, 'family': 'cross_down'})
                # (3) 넘은 다음 날 외국인 선물 순매도 확인 뒤
                conf = []
                for s in cr['cross_date']:
                    i = td.get_loc(s)
                    if i + 1 < len(td) and ffor.iloc[i + 1] < 0: conf.append(td[i + 1])
                if len(conf) >= 8:
                    t = pd.DataFrame({'signal': conf, 'exit': [L.exit_after(td, s, mm) for s in conf]}).dropna()
                    cands.append({'id': f'A3_crossdown_conf_{tag}_{N}_{tn}_m{mm}', 'agent': 'A3', 'desc': f'{tag} 콜벽({tn}) 돌파 + 다음 날 외국인 선물 순매도 → {mm}일 하락',
                                  'direction': -1, 'trades': t, 'family': 'cross_down_conf'})
    for c in cands: c['trades'] = c['trades'].sort_values('signal').reset_index(drop=True)
    L.save_candidates('a03', cands)
    print('사건', len(E), '개발', len(dev), '후보', len(cands))


if __name__ == '__main__':
    main()
