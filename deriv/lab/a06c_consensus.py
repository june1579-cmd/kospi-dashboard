"""A6c 합의 신호(갈래 B 라운드 5, 2026-11-20) — 서로 다른 가족의 벽 신호가 같은 방향으로 겹칠 때만 신호.

A3·A3c·A4·A5 후보(장세 변형·장세만 후보 제외)에서, 개발 구간(청산 ≤ DEV_END) 단순 적중(지수, 겹침 무시)으로
방향마다 상위 top_n 개(적중 ≥ min_hit, 개발 신호 ≥ min_sig)를 고른다 — 고르기는 개발 구간 성적만 씀.
날짜 t 에 직전 w 거래일 안(t 포함) 신호를 낸 '서로 다른 가족' 수가 k 이상이면 t 에 신호, 다음 날 시가 진입·h 일 뒤 종가 청산.
round 설정 'consensus' 가 있을 때만 돈다(워크플로 judge 단계에서 A8 앞에). 결과 out_b/round_NNN/a06c/.
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lab_common as L  # noqa: E402

cfg = L.round_cfg().get('consensus')


def load_base():
    import pickle
    rd = L.out_dir(); out = []
    for a in ('a03', 'a03c', 'a04', 'a05'):
        p = os.path.join(rd, a, 'candidates.pkl')
        if not os.path.exists(p): continue
        for c in pickle.load(open(p, 'rb')):
            fam = str(c.get('family') or '')
            if c.get('regime') or 'trades_dev' in c or fam == 'regime_only' or fam.endswith('_regime'): continue
            out.append(c)
    return out


def main():
    if not cfg:
        print('consensus 설정 없음 — 건너뜀'); return
    k = L.k200_index(); td = k.index
    top_n = cfg.get('top_n', 40); min_hit = cfg.get('min_hit', 0.55); min_sig = cfg.get('min_sig', 20)
    base = load_base()
    rows, cands = [], []
    for d in (1, -1):
        sc = []
        for c in base:
            if c['direction'] != d: continue
            t = c['trades'].assign(signal=pd.to_datetime(c['trades']['signal']), exit=pd.to_datetime(c['trades']['exit']))
            tdv = t[t['exit'] <= L.DEV_END]
            if len(tdv) < min_sig: continue
            r = L.trade_returns(tdv, k); r = r[~np.isnan(r)]
            if len(r) < min_sig: continue
            hit = float((d * r > 0).mean())
            if hit >= min_hit: sc.append((hit, c, t))
        sc.sort(key=lambda x: -x[0]); sc = sc[:top_n]
        for hit, c, _ in sc:
            rows.append({'direction': d, 'id': c['id'], 'family': c.get('family'), 'dev_hit_simple': round(hit, 4)})
        if len(sc) < 2: continue
        fams = sorted({str(c.get('family')) for _, c, _ in sc})
        F = pd.DataFrame(0, index=td, columns=fams, dtype=np.int8)
        for _, c, t in sc:
            s = t['signal'][t['signal'].isin(td)]
            F.loc[s.values, str(c.get('family'))] = 1
        for w in cfg.get('w', [0, 2, 4]):
            Fw = F.rolling(w + 1, min_periods=1).max() if w > 0 else F
            cnt = Fw.sum(axis=1)
            for kk in cfg.get('k', [2, 3]):
                sd = td[(cnt >= kk).values]
                if len(sd) < 10: continue
                for h in cfg.get('h', [1, 2, 3, 5, 10, 20]):
                    tr = pd.DataFrame({'signal': sd, 'exit': [L.exit_after(td, s_, h) for s_ in sd]}).dropna()
                    cands.append({'id': f'A6c_k{kk}_w{w}_m{h}_{"up" if d > 0 else "dn"}', 'agent': 'A6c', 'family': 'consensus',
                                  'desc': f'서로 다른 벽 신호 가족 {kk}개 이상이 {w + 1}일 안 같은 방향(개발 적중 상위 {len(sc)}개 중) → {h}일 {"상승" if d > 0 else "하락"}',
                                  'direction': d, 'trades': tr})
    if cfg.get('meta'):
        try:
            cands += meta_label(base, k, td, top_n, min_hit, min_sig)
        except Exception as e:   # 메타 학습 실패가 합의 후보 저장을 막지 않게
            import traceback; traceback.print_exc(); print('메타 라벨 실패', e)
    od = L.out_dir('a06c')
    pd.DataFrame(rows).to_csv(os.path.join(od, 'members.csv'), index=False, encoding='utf-8')
    L.save_candidates('a06c', cands)
    print('합의 신호 후보', len(cands), '구성원', len(rows))


def meta_label(base, k, td, top_n, min_hit, min_sig):
    """메타 라벨(갈래 B 라운드 5): 1차 신호 = 개발 적중 상위 벽 신호들의 신호일 합집합(방향마다).
    2차 = 그 날들만으로 학습한 분류기(A6 자료 + 장세 지표 + 그날 겹친 가족 수)가 '이번엔 맞을' 확률이 문턱 이상일 때만 신호.
    해마다(2016~2023) 그 해 이전 사건으로 학습(끝 2년으로 문턱: 정밀도 ≥ target 이면서 사건 ≥ 10, 없으면 상위 20%) → 그 해 적용 = 개발 성적.
    최종 = 개발 구간 사건 전체로 같은 방식 → 전체 기간(잠금 구간은 A8 만 계산)."""
    import a06_rules as A6
    from sklearn.ensemble import HistGradientBoostingClassifier
    mc = cfg.get('meta') or {}
    X = A6.dataset()
    if 'rg_volpct' not in X.columns: X = X.join(L.regime_features(), how='left')
    target = mc.get('target_prec', 0.75)
    px = L.prices()['K200F']; tdx = X.index
    out = []

    def fit(Xa, ya):
        keep = np.sum(~np.isnan(Xa), axis=0) >= 30
        m = HistGradientBoostingClassifier(max_iter=150, learning_rate=0.05, max_leaf_nodes=7, min_samples_leaf=mc.get('min_leaf', 30),
                                           l2_regularization=1.0, random_state=0).fit(Xa[:, keep], ya)
        return lambda Z: m.predict_proba(Z[:, keep])[:, 1]

    def pick_tau(Xa, ya, da, h):
        cut = da[-1] - pd.Timedelta(days=730)
        a = da < cut - pd.Timedelta(days=int(h * 1.5)); b = da >= cut
        if a.sum() < mc.get('min_fit', 80) or b.sum() < 30: return None
        p = fit(Xa[a], ya[a])(Xa[b]); yb = ya[b]
        for tau in np.quantile(p, np.linspace(0.5, 0.97, 30)):
            s = p >= tau
            if s.sum() >= 10 and yb[s].mean() >= target: return float(tau)
        return float(np.quantile(p, 0.8))

    for d in (1, -1):
        sc = []
        for c in base:
            if c['direction'] != d: continue
            t = c['trades'].assign(signal=pd.to_datetime(c['trades']['signal']), exit=pd.to_datetime(c['trades']['exit']))
            tdv = t[t['exit'] <= L.DEV_END]
            if len(tdv) < min_sig: continue
            r = L.trade_returns(tdv, k); r = r[~np.isnan(r)]
            if len(r) < min_sig or float((d * r > 0).mean()) < min_hit: continue
            sc.append((float((d * r > 0).mean()), c, t))
        sc.sort(key=lambda x: -x[0]); sc = sc[:top_n]
        if not sc: continue
        fams = sorted({str(c.get('family')) for _, c, _ in sc})
        F = pd.DataFrame(0, index=tdx, columns=fams, dtype=np.int8)
        for _, c, t in sc:
            s = t['signal'][t['signal'].isin(tdx)]
            F.loc[s.values, str(c.get('family'))] = 1
        ev = tdx[(F.sum(axis=1) > 0).values]
        Xe = X.loc[ev].copy(); Xe['meta_nfam'] = F.loc[ev].sum(axis=1).values
        for fm in fams: Xe[f'meta_{fm}'] = F.loc[ev, fm].values
        cols = [c for c in Xe.columns if Xe.loc[:L.DEV_END, c].notna().sum() >= 100]
        Xv = Xe[cols].values.astype(float)
        for h in mc.get('h', [3, 5, 10]):
            r = (px['close'].shift(-h) / px['open'].shift(-1) - 1).reindex(ev)
            y = ((d * r) > 0).astype(float).where(r.notna() & (r != 0)).values
            oos = []
            for Y in range(2016, 2024):
                te = np.where(ev.year == Y)[0]
                if not len(te): continue
                tri = np.where((ev < pd.Timestamp(f'{Y}-01-01') - pd.Timedelta(days=int(h * 1.5))) & ~np.isnan(y))[0]
                if len(tri) < mc.get('min_train', 120): continue
                tau = pick_tau(Xv[tri], y[tri].astype(int), ev[tri], h)
                if tau is None: continue
                p = fit(Xv[tri], y[tri].astype(int))(Xv[te])
                oos += list(ev[te[p >= tau]])
            tri = np.where((ev <= L.DEV_END - pd.Timedelta(days=int(h * 1.5))) & ~np.isnan(y))[0]
            tau = pick_tau(Xv[tri], y[tri].astype(int), ev[tri], h) if len(tri) >= mc.get('min_train', 120) else None
            if tau is None or len(oos) < 10: continue
            p = fit(Xv[tri], y[tri].astype(int))(Xv)
            sig = ev[p >= tau]
            out.append({'id': f'A6c_meta_m{h}_{"up" if d > 0 else "dn"}', 'agent': 'A6c', 'family': 'meta_label',
                        'desc': f'메타 라벨: 벽 신호(개발 적중 상위 {len(sc)}개)가 난 날 중 학습 확률 상위만(목표 {target:.0%}) → {h}일 {"상승" if d > 0 else "하락"}',
                        'direction': d,
                        'trades': pd.DataFrame({'signal': sig, 'exit': [L.exit_after(td, s_, h) for s_ in sig]}).dropna(),
                        'trades_dev': pd.DataFrame({'signal': oos, 'exit': [L.exit_after(td, s_, h) for s_ in oos]}).dropna(),
                        'tau': tau, 'n_events': int(len(ev))})
            print('메타', d, h, '사건', len(ev), '개발 신호', len(oos), flush=True)
    return out


if __name__ == '__main__':
    main()
