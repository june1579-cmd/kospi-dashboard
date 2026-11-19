"""A5 롤오버 에이전트 — 분기 만기 전까지의 콜 물량과, 만기 뒤 다음 분기로 넘어가 '연장'되는 물량·선물 이월.

  (1) 분기물(Q) 콜벽이 만기 직후 새 분기물에서도 같은(±1행사가) 행사가에 다시 서는가(벽 연장) → 연장되면 다음 m일 방향
  (2) 선물 이월률(차월물 미결제 ÷ 근+차, 만기 1~5일 전)과 직전 4개 분기 평균 대비 차 → 만기 뒤 m일 방향
  (3) 롤 스프레드(차월물−근월물, 근월물 대비 %)의 직전 4개 분기 대비 차 → 만기 뒤 m일 방향
선물 전 월물 자료(fut_roll_daily)는 2008~ 분기 만기 무렵만 있다(수집 중이면 있는 데까지).
"""
import os
import pickle
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lab_common as L  # noqa: E402

cfg = L.round_cfg().get('a05', {})
MS = cfg.get('post_m', [1, 5, 10, 20])


def main():
    k2 = L.k200_index(); td = k2.index
    od = L.out_dir('a05')
    feat = pickle.load(open(os.path.join(L.LAB, 'work', 'lab_feat.pkl'), 'rb'))
    W = feat['walls']
    rows, cands = [], []
    # (1) 벽 연장
    Q = W[W['tag'] == 'Q'].sort_values('date')
    qexp = sorted(Q['exp'].unique())
    ext = []
    for e in qexp:
        if e > td[-1]: continue
        before = Q[(Q['exp'] == e) & (Q['date'] < e)].tail(1)
        after = Q[(Q['date'] > e)].head(1)
        if not len(before) or not len(after): continue
        kb, ka = before['K'].iloc[0], after['K'].iloc[0]
        step = 2.5 if kb < 400 else 5.0
        same = bool(np.isfinite(kb) and np.isfinite(ka) and abs(kb - ka) <= step)
        s = after['date'].iloc[0]
        rec = {'exp': e, 'signal': s, 'K_before': kb, 'K_after': ka, 'same_wall': same, 'dist_after%': after['dist%'].iloc[0], 'share_after': after['share'].iloc[0]}
        i = td.searchsorted(s, side='right')
        for m in MS:
            j = i + m - 1
            if j < len(td): rec[f'post{m}%'] = (k2['close'].iloc[j] / k2['open'].iloc[i] - 1) * 100
        ext.append(rec)
    E = pd.DataFrame(ext); E.to_csv(os.path.join(od, 'wall_extension_all.csv'), index=False, encoding='utf-8')
    devE = E[E['signal'] <= L.DEV_END]
    for same in (True, False):
        x = devE[devE['same_wall'] == same]
        for m in MS:
            v = x[f'post{m}%'].dropna() if f'post{m}%' in x else pd.Series(dtype=float)
            if len(v) >= 6:
                rows.append({'구분': f'벽 연장={same}', 'm일': m, '사건': len(v), '상승%': (v > 0).mean() * 100, '평균%': v.mean()})
            sig = E[E['same_wall'] == same]['signal']
            if len(sig) >= 8:
                d = 1 if (len(v) and (v > 0).mean() >= 0.5) else -1
                cands.append({'id': f'A5_wallext_{same}_m{m}', 'agent': 'A5', 'family': 'roll_wall', 'desc': f'분기 만기 뒤 콜벽 연장={same} → {m}일 {"상승" if d > 0 else "하락"}',
                              'direction': d, 'trades': pd.DataFrame({'signal': sig.values, 'exit': [L.exit_after(td, s, m) for s in sig]}).dropna()})
    # (2)(3) 선물 이월
    p = os.path.join(L.DATA, 'fut_roll_daily.csv.gz')
    if os.path.exists(p):
        R = pd.read_csv(p); R['date'] = pd.to_datetime(R['날짜']); R['ym'] = R['ym'].astype(str)
        qexp_all = [L.expiry_of_ym(f'{y}{m:02d}', td) for y in range(2008, 2027) for m in (3, 6, 9, 12)]
        recs = []
        for e in qexp_all:
            if e > td[-1]: continue
            ym_near = e.strftime('%Y%m')
            win = R[(R['date'] < e) & (R['date'] >= e - pd.Timedelta(days=10))]
            if not len(win): continue
            last = win[win['date'] == win['date'].max()]
            near = last[last['ym'] == ym_near]; nxt = last[last['ym'] > ym_near].sort_values('ym').head(1)
            if not len(near) or not len(nxt): continue
            oi_n, oi_x = float(near['oi'].iloc[0]), float(nxt['oi'].iloc[0])
            pn = near['settle'].iloc[0] if pd.notna(near['settle'].iloc[0]) else near['close'].iloc[0]
            px_ = nxt['settle'].iloc[0] if pd.notna(nxt['settle'].iloc[0]) else nxt['close'].iloc[0]
            recs.append({'exp': e, 'obs': last['date'].iloc[0], 'roll_ratio': oi_x / max(oi_n + oi_x, 1), 'spread%': (px_ / pn - 1) * 100 if pn else np.nan})
        RR = pd.DataFrame(recs)
        if len(RR) >= 8:
            RR['roll_vs4'] = RR['roll_ratio'] - RR['roll_ratio'].rolling(4).mean().shift(1)
            RR['spread_vs4'] = RR['spread%'] - RR['spread%'].rolling(4).mean().shift(1)
            RR.to_csv(os.path.join(od, 'roll_metrics.csv'), index=False, encoding='utf-8')
            for col in ('roll_vs4', 'spread_vs4'):
                for side, f in (('높음', lambda s: s > 0), ('낮음', lambda s: s <= 0)):
                    x = RR[f(RR[col]) & RR[col].notna()]
                    sig = x['exp']
                    for m in MS:
                        ex = [L.exit_after(td, s, m) for s in sig]
                        rets = L.trade_returns(pd.DataFrame({'signal': sig.values, 'exit': ex}).dropna(), k2)
                        devmask = (sig <= L.DEV_END).values[:len(rets)]
                        v = pd.Series(rets[devmask]).dropna()
                        if len(v) >= 6:
                            rows.append({'구분': f'{col} {side}', 'm일': m, '사건': len(v), '상승%': (v > 0).mean() * 100, '평균%': v.mean()})
                            d = 1 if (v > 0).mean() >= 0.5 else -1
                            cands.append({'id': f'A5_{col}_{side}_m{m}', 'agent': 'A5', 'family': 'roll_fut', 'desc': f'선물 {col} {side}(만기일 신호) → 만기 뒤 {m}일 {"상승" if d > 0 else "하락"}',
                                          'direction': d, 'trades': pd.DataFrame({'signal': sig.values, 'exit': ex}).dropna()})
    pd.DataFrame(rows).round(3).to_csv(os.path.join(od, 'roll_dev.csv'), index=False, encoding='utf-8')
    L.save_candidates('a05', cands)
    print('표', len(rows), '후보', len(cands))


if __name__ == '__main__':
    main()
