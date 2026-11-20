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
            # 라운드 6: 분기 만기 전 콜 물량이 만기 뒤 새 분기물로 '연장'됐는가 × 선물 이월이 평소보다 많았나/적었나(롤 자료 2020~2026 추가로 개발 분기 늘어남)
            if len(E):
                M = E.merge(RR[['exp', 'roll_vs4', 'spread_vs4']], on='exp', how='inner')
                for same in (True, False):
                    for col in ('roll_vs4', 'spread_vs4'):
                        for side, f in (('높음', lambda s: s > 0), ('낮음', lambda s: s <= 0)):
                            x = M[(M['same_wall'] == same) & M[col].notna() & f(M[col])]
                            if len(x) < 8: continue
                            xd = x[x['signal'] <= L.DEV_END]
                            for m in MS:
                                v = xd[f'post{m}%'].dropna() if f'post{m}%' in xd else pd.Series(dtype=float)
                                if len(v) < 6: continue
                                rows.append({'구분': f'벽 연장={same} + {col} {side}', 'm일': m, '사건': len(v), '상승%': (v > 0).mean() * 100, '평균%': v.mean()})
                                d = 1 if (v > 0).mean() >= 0.5 else -1
                                sig = x['signal']
                                cands.append({'id': f'A5_wallext_{same}_{col}_{side}_m{m}', 'agent': 'A5', 'family': 'roll_wall_fut',
                                              'desc': f'분기 만기 뒤 콜벽 연장={same} + 선물 {col} {side} → {m}일 {"상승" if d > 0 else "하락"}',
                                              'direction': d, 'trades': pd.DataFrame({'signal': sig.values, 'exit': [L.exit_after(td, s, m) for s in sig]}).dropna()})
    # 라운드 7: 월물 만기마다(분기 포함, 개발 약 108번) 옵션 '콜 물량 이월' — 만기 전날 차월물 콜(현재가 위) 미결제 ÷ (근월+차월),
    # 직전 6번 만기 평균 대비 높음/낮음, 근월물 콜벽이 새 근월물에서도 같은 행사가로 이어지나(월물 벽 연장). 라운드 6 최고(분기 벽 연장 안 됨 + 선물 이월 낮음)를
    # 표본이 많은 월물로 넓혀 같은 방향인지 사전 등록으로 본다(양방향, 방향은 개발 구간으로).
    if cfg.get('monthly', True):
        wide = feat['wide']
        F0 = W[W['tag'] == 'F0'].sort_values('date')
        mrec = []
        for e in sorted(F0['exp'].unique()):
            if e > td[-1]: continue
            b = F0[(F0['exp'] == e) & (F0['date'] < e)].tail(1)
            a = F0[F0['date'] > e].head(1)
            if not len(b) or not len(a): continue
            bd, kb, ka = b['date'].iloc[0], b['K'].iloc[0], a['K'].iloc[0]
            step = 2.5 if kb < 400 else 5.0
            c0 = wide['OW_F0_callotm_oi'].get(bd, np.nan) if 'OW_F0_callotm_oi' in wide else np.nan
            c1 = wide['OW_F1_callotm_oi'].get(bd, np.nan) if 'OW_F1_callotm_oi' in wide else np.nan
            sgl = a['date'].iloc[0]
            # 라운드 10(갈래 A, a05.monthly_x): 월물 4개 자료로 '이월·연장'을 뒤 결제월 3개까지 — 만기 전날 차월·차차월·넷째 월물 콜(현재가 위) 미결제 ÷ 4개 합,
            #   근월물 콜벽 행사가가 만기 전날 차월 또는 차차월에서도 콜벽인가(같은 천장이 뒤 달에 이미 준비됨). 설정 없으면 계산만 하고 후보는 안 만듦.
            cx = [wide[f'OW_{t}_callotm_oi'].get(bd, np.nan) if f'OW_{t}_callotm_oi' in wide else np.nan for t in ('F1', 'F2', 'F3')]
            kl = []
            for t in ('F1', 'F2'):
                wt = W[(W['tag'] == t) & (W['date'] == bd)]
                kl.append(float(wt['K'].iloc[0]) if len(wt) else np.nan)
            tot_x = c0 + np.nansum(cx) if np.isfinite(c0) and np.isfinite(cx).all() else np.nan
            mrec.append({'call_roll_x': (np.nansum(cx) / tot_x) if np.isfinite(tot_x) and tot_x > 0 else np.nan,
                         'wall_ahead': bool(np.isfinite(kb) and any(np.isfinite(k) and abs(k - kb) <= step for k in kl)) if np.isfinite(kl).any() else np.nan,'exp': e, 'obs': bd, 'signal': sgl, 'same_wall': bool(np.isfinite(kb) and np.isfinite(ka) and abs(kb - ka) <= step),
                         'call_roll': c1 / (c0 + c1) if np.isfinite(c0) and np.isfinite(c1) and (c0 + c1) > 0 else np.nan,
                         'quarterly': int(pd.Timestamp(e).month) in (3, 6, 9, 12)})
        MR = pd.DataFrame(mrec)
        if len(MR) >= 12:
            MR['call_roll_vs6'] = MR['call_roll'] - MR['call_roll'].rolling(6, min_periods=4).mean().shift(1)
            ii = [td.searchsorted(x, side='right') for x in MR['signal']]
            for m in MS:
                MR[f'post{m}%'] = [(k2['close'].iloc[i + m - 1] / k2['open'].iloc[i] - 1) * 100 if i + m - 1 < len(td) else np.nan for i in ii]
            MR.to_csv(os.path.join(od, 'monthly_roll_all.csv'), index=False, encoding='utf-8')
            conds = {}
            for same in (True, False):
                conds[f'월물 콜벽 연장={same}'] = MR['same_wall'] == same
            if cfg.get('monthly_x') and MR['call_roll_x'].notna().sum() >= 24:
                MR['call_roll_x_vs6'] = MR['call_roll_x'] - MR['call_roll_x'].rolling(6, min_periods=4).mean().shift(1)
                okx = MR['call_roll_x_vs6'].notna() & MR['wall_ahead'].notna()
                hix = okx & (MR['call_roll_x_vs6'] > 0); lox = okx & (MR['call_roll_x_vs6'] <= 0)
                wa = MR['wall_ahead'] == True  # noqa: E712
                conds['뒤 결제월(차월·차차월)에 같은 콜벽 있음'] = okx & wa
                conds['뒤 결제월(차월·차차월)에 같은 콜벽 없음'] = okx & ~wa
                conds['뒤 결제월 3개 콜 이월 평소보다 적음'] = lox; conds['뒤 결제월 3개 콜 이월 평소보다 많음'] = hix
                for wn, wm in (('있음', wa), ('없음', ~wa)):
                    conds[f'뒤 결제월에 같은 콜벽 {wn} + 3개 콜 이월 적음'] = lox & wm
                    conds[f'뒤 결제월에 같은 콜벽 {wn} + 3개 콜 이월 많음'] = hix & wm
                    conds[f'월물 콜벽 연장=True + 뒤 결제월에 같은 콜벽 {wn}'] = okx & (MR['same_wall'] == True) & wm  # noqa: E712
            hi = MR['call_roll_vs6'] > 0; lo = MR['call_roll_vs6'] <= 0; ok = MR['call_roll_vs6'].notna()
            conds['콜 물량 이월 평소보다 많음'] = ok & hi; conds['콜 물량 이월 평소보다 적음'] = ok & lo
            for same in (True, False):
                conds[f'월물 콜벽 연장={same} + 콜 이월 많음'] = (MR['same_wall'] == same) & ok & hi
                conds[f'월물 콜벽 연장={same} + 콜 이월 적음'] = (MR['same_wall'] == same) & ok & lo
            for nm, mk in conds.items():
                x = MR[mk]
                if len(x) < 12: continue
                xd = x[x['signal'] <= L.DEV_END]
                for m in MS:
                    v = xd[f'post{m}%'].dropna()
                    if len(v) < 10: continue
                    rows.append({'구분': nm, 'm일': m, '사건': len(v), '상승%': (v > 0).mean() * 100, '평균%': v.mean()})
                    d = 1 if (v > 0).mean() >= 0.5 else -1
                    sig = x['signal']
                    key = nm.replace(' ', '').replace('+', '_').replace('=', '')
                    cands.append({'id': f'A5_m_{key}_m{m}', 'agent': 'A5', 'family': 'roll_monthly_call',
                                  'desc': f'{nm}(월물 만기 다음 날 신호) → {m}일 {"상승" if d > 0 else "하락"}',
                                  'direction': d, 'trades': pd.DataFrame({'signal': sig.values, 'exit': [L.exit_after(td, s, m) for s in sig]}).dropna()})
    pd.DataFrame(rows).round(3).to_csv(os.path.join(od, 'roll_dev.csv'), index=False, encoding='utf-8')
    L.save_candidates('a05', cands)
    print('표', len(rows), '후보', len(cands))


if __name__ == '__main__':
    main()
