"""A7 기계학습 에이전트 — 확률이 아주 높을 때만 신호를 내는(정밀도 80% 목표) 모형.

자료·대상은 A6 과 같다. 해마다(2016~2023) 그 해 이전 자료로:
  학습 구간 끝 2년을 떼어 문턱 고르기용으로 쓰고(그 2년에서 정밀도 ≥ 목표이면서 신호 ≥ 15일인 가장 낮은 문턱, 없으면 상위 5%),
  학습 구간 전체로 다시 학습 → 그 해에 문턱 적용. 모은 신호 = 개발 구간 성적(A8).
최종 모형은 개발 구간 전체로 같은 방식 → 잠금 구간 신호 날짜(결과 계산은 A8).
"""
import os
import sys

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lab_common as L  # noqa: E402
import a06_rules as A6  # noqa: E402

cfg = L.round_cfg().get('a07', {})
HS = cfg.get('h', [1, 3, 5, 10, 20])
BARRIER = cfg.get('barrier', [])   # 큰 변동 창(거래일, 먼저 닿는 쪽), 2026-11-20 갈래 B
BK = cfg.get('barrier_k', 1.0)
JOBS = [('h', h) for h in HS] + [('b', w) for w in BARRIER]
SHARD = os.environ.get('A07_SHARD', '')   # 'i/n' 이면 (보유 기간 + 큰 변동 창) 을 n 조각 중 i 번째만(워크플로가 조각을 동시에 돌림, 2026-11-20)
if SHARD:
    _i, _n = (int(v) for v in SHARD.split('/')); JOBS = JOBS[_i::_n]
SUB = f'a07s{SHARD.split("/")[0]}' if SHARD else 'a07'
TARGET = cfg.get('target_prec', 0.8)
YEARS = list(range(cfg.get('first_test_year', 2016), 2024))
TRAIN_START = pd.Timestamp(cfg.get('train_start', '2010-01-01'))


class Fitted:
    """학습 구간에 값이 거의 없는 열은 빼고 학습(그 열 목록을 기억해 예측에도 같게)."""
    def __init__(self, X, y):
        self.keep = (np.sum(~np.isnan(X), axis=0) >= 50)
        self.m = HistGradientBoostingClassifier(max_iter=cfg.get('max_iter', 200), learning_rate=0.05, max_leaf_nodes=cfg.get('leaves', 15),
                                                min_samples_leaf=cfg.get('min_leaf', 60), l2_regularization=1.0, random_state=0).fit(X[:, self.keep], y)

    def predict_proba(self, X):
        return self.m.predict_proba(X[:, self.keep])


def fit(X, y):
    return Fitted(X, y)


def pick_tau(Xa, ya, td_a, h):
    """앞부분으로 학습, 끝 2년으로 문턱을 고른다."""
    cut = td_a[-1] - pd.Timedelta(days=730)
    a = td_a < cut - pd.Timedelta(days=int(h * 1.5)); b = td_a >= cut
    if a.sum() < 400 or b.sum() < 200: return None
    m = fit(Xa[a], ya[a]); p = m.predict_proba(Xa[b])[:, 1]; yb = ya[b]
    for tau in np.quantile(p, np.linspace(0.80, 0.995, 40)):
        s = p >= tau
        if s.sum() >= 15 and yb[s].mean() >= TARGET: return float(tau)
    return float(np.quantile(p, 0.95))


def main():
    X = A6.dataset()
    P = L.prices(); px = P['K200F']
    td = X.index
    cols = [c for c in X.columns if X.loc[:L.DEV_END, c].notna().sum() >= 300]
    Xv = X[cols].values
    od = L.out_dir(SUB)
    cands, rows = [], []
    for kind, h in JOBS:
        if kind == 'h':
            r = (px['close'].shift(-h) / px['open'].shift(-1) - 1).reindex(td)
            yup = (r > 0).astype(float).where(r.notna() & (r != 0)); exs = None
        else:
            yup, ex = L.barrier_exits(px, h, BK); yup = yup.reindex(td); exs = ex.reindex(td).dropna().to_dict()
        ex_of = (lambda ss, h=h: [L.exit_after(td, s_, h) for s_ in ss]) if exs is None else (lambda ss, exs=exs: [exs.get(s_, pd.NaT) for s_ in ss])
        tgt = f'{h}일' if exs is None else f'{h}일 안 큰 변동(±{BK:g}σ) 먼저'
        idt = f'h{h}' if exs is None else f'b{h}'
        for direction in (1, -1):
            y = yup if direction > 0 else (1 - yup)
            oos = []
            for Y in YEARS:
                te = np.where(td.year == Y)[0]
                trm = (td >= TRAIN_START) & (np.arange(len(td)) < te[0] - h) & y.notna().values
                tri = np.where(trm)[0]
                tau = pick_tau(Xv[tri], y.values[tri].astype(int), td[tri], h)
                if tau is None: continue
                m = fit(Xv[tri], y.values[tri].astype(int))
                p = m.predict_proba(Xv[te])[:, 1]
                s = te[p >= tau]
                oos += list(td[s])
                yy = y.values[s]; yy = yy[~np.isnan(yy)]
                rows.append({'h': idt, '방향': direction, '해': Y, '문턱': tau, '신호일': len(s), '적중': float(yy.mean()) if len(yy) else np.nan})
            trm = (td >= TRAIN_START) & (td <= L.DEV_END - pd.Timedelta(days=int(h * 1.5))) & y.notna().values
            tri = np.where(trm)[0]
            tau = pick_tau(Xv[tri], y.values[tri].astype(int), td[tri], h)
            if tau is None or len(oos) < 10: continue
            m = fit(Xv[tri], y.values[tri].astype(int))
            p = m.predict_proba(Xv)[:, 1]
            sig = td[p >= tau]
            cands.append({'id': f'A7_ml_{idt}_{"up" if direction > 0 else "dn"}', 'agent': 'A7', 'family': 'ml' if exs is None else 'ml_big',
                          'desc': f'기계학습(확률 상위, 목표 정밀도 {TARGET:.0%}) → {tgt} {"상승" if direction > 0 else "하락"}', 'direction': direction,
                          'trades': pd.DataFrame({'signal': sig, 'exit': ex_of(sig)}).dropna(),
                          'trades_dev': pd.DataFrame({'signal': oos, 'exit': ex_of(oos)}).dropna(),
                          'tau': tau, 'p_last': float(p[-1])})
            # 뒤 구간 적합(fit_period p2, 2026-11-21~ 교차 모드에서만): 뒤 구간 앞 60% 학습·뒤 40% 문턱 → 뒤 구간 전체로 다시 학습 → 앞 구간에 적용
            if L.fit_p2_enabled(cfg):
                m2 = (td >= L.HOLD_START) & (td <= td[-1] - pd.Timedelta(days=int(h * 1.5))) & y.notna().values
                i2 = np.where(m2)[0]
                if len(i2) >= 300:
                    cut = i2[int(len(i2) * 0.6)]
                    a_ = i2[i2 < cut - h]; b_ = i2[i2 >= cut]
                    mm = fit(Xv[a_], y.values[a_].astype(int)); pb = mm.predict_proba(Xv[b_])[:, 1]; yb = y.values[b_]
                    tau2 = None
                    for tq in np.quantile(pb, np.linspace(0.80, 0.995, 40)):
                        ss = pb >= tq
                        if ss.sum() >= 12 and yb[ss].mean() >= TARGET: tau2 = float(tq); break
                    if tau2 is None: tau2 = float(np.quantile(pb, 0.95))
                    m2f = fit(Xv[i2], y.values[i2].astype(int)); p2 = m2f.predict_proba(Xv)[:, 1]
                    sig2 = td[p2 >= tau2]
                    t2 = pd.DataFrame({'signal': sig2, 'exit': ex_of(sig2)}).dropna()
                    cands.append({'id': f'A7_fp2_{idt}_{"up" if direction > 0 else "dn"}', 'agent': 'A7', 'family': 'ml_fp2',
                                  'desc': f'[뒤 구간 적합] 기계학습(목표 정밀도 {TARGET:.0%}) → {tgt} {"상승" if direction > 0 else "하락"}', 'direction': direction,
                                  'trades': t2, 'trades_dev': t2, 'fit_period': 'p2', 'tau': tau2})
            print(kind, h, 'dir', direction, flush=True)
    pd.DataFrame(rows).round(4).to_csv(os.path.join(od, 'ml_by_year.csv'), index=False, encoding='utf-8')
    L.save_candidates(SUB, cands)


if __name__ == '__main__':
    main()
