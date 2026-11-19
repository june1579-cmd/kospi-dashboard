"""기간별 예측 가능성 탐색 — 조합 규칙 + 기계학습, 해마다 따로(워크포워드) 검증. GitHub Actions 행렬 작업 하나가 (대상, 기간 묶음) 하나를 맡는다.

사용: python scan_run.py KOSPI 1,2,3
맞힐 대상(t+1일 시가 → t+h일 종가 r, 단위 %)
  dir     r > 0 (오를 확률)
  big_up  r > 1.5σh, big_dn r < −1.5σh   (σh = 직전 750거래일 h일 등락 표준편차 — t일에 아는 값)
  path_dn 보유 중 종가 최저가 시가 대비 −1.5σh 아래로 한 번이라도(보유 중 급락 위험)
  path_up 보유 중 종가 최고가 +1.5σh 위로 한 번이라도
  trend   r 의 부호 = 직전 h일 등락 부호(추세가 이어짐)
  ret     r 그 자체(크기, 순위상관으로 평가)
검증(해마다 따로): 시험 해 Y 마다 Y 이전 자료만으로(끝 h일 비움) 문턱·규칙·모형을 정하고 Y 에서만 성적을 잰다. 2010~2026.
조합 규칙: 지표마다 학습 구간 분위수로 조건 4개(하위10·20%, 상위20·10%; 값이 3가지 이하인 달력 지표는 값마다 1개).
  단일·2개 조합은 전수(행렬곱), 3개 조합은 상위 2개 조합에 조건 하나씩 더해 보는 빔 탐색.
  점수 = (조건부 확률 − 기본 확률) × √(유효 표본), 유효 표본 = 발생일 ÷ √h(겹치는 보유 기간 보정, 보수적 근사), 유효 표본 20 이상만.
  같은 날 겹침이 70% 넘는 비슷한 규칙은 하나만 남기고, 확률을 높이는 쪽·낮추는 쪽 각 10개.
기계학습: HistGradientBoosting(빈칸 그대로 처리). 해마다 AUC·브라이어 기술점수·상위 20% 적중률, 크기는 순위상관.
출력: deriv/scan/out/<대상>_<기간들>/ 아래 csv.
"""
import json
import os
import pickle
import sys
import time

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.metrics import brier_score_loss, roc_auc_score

HERE = os.path.dirname(os.path.abspath(__file__))
D = pickle.load(open(os.path.join(HERE, 'work', 'daily.pkl'), 'rb'))
X0 = D['X']
TYPES = ['dir', 'big_up', 'big_dn', 'path_dn', 'path_up', 'trend']
YEARS = list(range(2010, 2027))
K = 1.5
START = pd.Timestamp('2008-01-02')


def targets(px, h):
    c, o = px['close'], px['open']
    o1 = o.shift(-1)
    r = (c.shift(-h) / o1 - 1) * 100
    fut = pd.concat([c.shift(-k) for k in range(1, h + 1)], axis=1)
    pmin = (fut.min(axis=1) / o1 - 1) * 100; pmax = (fut.max(axis=1) / o1 - 1) * 100
    past = c.pct_change(h) * 100
    sig = past.rolling(750, min_periods=250).std()
    ok = r.notna() & fut.notna().all(axis=1)
    T = pd.DataFrame(index=px.index)
    T['ret'] = r.where(ok)
    T['dir'] = (r > 0).astype(float).where(ok)
    T['big_up'] = (r > K * sig).astype(float).where(ok & sig.notna())
    T['big_dn'] = (r < -K * sig).astype(float).where(ok & sig.notna())
    T['path_dn'] = (pmin < -K * sig).astype(float).where(ok & sig.notna())
    T['path_up'] = (pmax > K * sig).astype(float).where(ok & sig.notna())
    T['trend'] = (np.sign(r) == np.sign(past)).astype(float).where(ok & past.notna() & (r != 0))
    T['sig'] = sig
    return T


def conditions(Xtr, Xte):
    """학습 구간 분위수로 조건 행렬. 반환: 조건 이름, 지표 번호, 학습·시험 불리언 행렬."""
    names, fid, ctr, cte = [], [], [], []
    for j, col in enumerate(Xtr.columns):
        a, b = Xtr[col], Xte[col]
        if a.notna().sum() < 200: continue
        vals = a.dropna().unique()
        if len(vals) <= 3:
            for v in sorted(vals):
                names.append(f'{col}={v:g}'); fid.append(j); ctr.append((a == v).values); cte.append((b == v).values)
            continue
        q = a.quantile([0.1, 0.2, 0.8, 0.9]).values
        for lab, m_tr, m_te in ((f'{col}≤하위10%({q[0]:.3g})', a <= q[0], b <= q[0]), (f'{col}≤하위20%({q[1]:.3g})', a <= q[1], b <= q[1]),
                                (f'{col}≥상위20%({q[2]:.3g})', a >= q[2], b >= q[2]), (f'{col}≥상위10%({q[3]:.3g})', a >= q[3], b >= q[3])):
            names.append(lab); fid.append(j); ctr.append(m_tr.fillna(False).values); cte.append(m_te.fillna(False).values)
    return names, np.array(fid), np.array(ctr).T.astype(np.float32), np.array(cte).T.astype(np.float32)


def mine(C, y, fid, h, n_keep=10):
    """단일·2개·3개 조합 규칙. 반환: [(조건 번호 tuple, 방향 +1/-1, 학습 확률, 발생일)]"""
    base = y.mean(); heff = np.sqrt(h)
    Cy = C * y[:, None]
    N1 = C.sum(0); H1 = Cy.sum(0)
    N2 = C.T @ C; H2 = C.T @ Cy
    same = fid[:, None] == fid[None, :]
    with np.errstate(divide='ignore', invalid='ignore'):
        p2 = H2 / N2
    ne2 = N2 / heff
    S2 = (p2 - base) * np.sqrt(np.maximum(ne2, 0))
    S2[(ne2 < 20) | same | ~np.isfinite(S2)] = 0
    iu = np.triu_indices_from(S2, k=1)
    s_flat = S2[iu]
    with np.errstate(divide='ignore', invalid='ignore'):
        p1 = H1 / N1
    S1 = (p1 - base) * np.sqrt(np.maximum(N1 / heff, 0)); S1[(N1 / heff < 20) | ~np.isfinite(S1)] = 0
    out = []
    for sgn in (1, -1):
        cand = []
        order1 = np.argsort(-sgn * S1)[:100]
        cand += [((int(i),), float(sgn * S1[i]), float(p1[i]), int(N1[i])) for i in order1 if sgn * S1[i] > 0]
        order2 = np.argsort(-sgn * s_flat)[:300]
        pairs = [((int(iu[0][k]), int(iu[1][k])), float(sgn * s_flat[k]), float(p2[iu[0][k], iu[1][k]]), int(N2[iu[0][k], iu[1][k]])) for k in order2 if sgn * s_flat[k] > 0]
        cand += pairs
        for (i, j), _, _, _ in pairs[:30]:      # 3개 조합(빔)
            pm = C[:, i] * C[:, j]
            N3 = pm @ C; H3 = (pm * y) @ C
            with np.errstate(divide='ignore', invalid='ignore'):
                p3 = H3 / N3
            S3 = (p3 - base) * np.sqrt(np.maximum(N3 / heff, 0))
            S3[(N3 / heff < 20) | ~np.isfinite(S3) | (fid == fid[i]) | (fid == fid[j])] = 0
            for k in np.argsort(-sgn * S3)[:5]:
                if sgn * S3[k] > 0: cand.append((tuple(sorted((i, j, int(k)))), float(sgn * S3[k]), float(p3[k]), int(N3[k])))
        cand.sort(key=lambda t: -t[1])
        chosen, masks = [], []
        seen = set()
        for rule, sc, p, n in cand:
            if rule in seen: continue
            seen.add(rule)
            m = C[:, list(rule)].prod(axis=1) > 0
            if any((m & mm).sum() / max(1, (m | mm).sum()) > 0.7 for mm in masks): continue
            chosen.append((rule, sgn, p, n, sc)); masks.append(m)
            if len(chosen) >= n_keep: break
        out += chosen
    return out, base


def ml_fit(Xtr, ytr, kind):
    if kind == 'reg':
        m = HistGradientBoostingRegressor(max_iter=150, learning_rate=0.05, max_leaf_nodes=15, min_samples_leaf=80, l2_regularization=1.0, random_state=0)
    else:
        m = HistGradientBoostingClassifier(max_iter=150, learning_rate=0.05, max_leaf_nodes=15, min_samples_leaf=80, l2_regularization=1.0, random_state=0)
    return m.fit(Xtr, ytr)


def run(inst, hs):
    px = D['P'][inst]
    outdir = os.path.join(HERE, 'out', f'{inst}_{"-".join(map(str, hs))}'); os.makedirs(outdir, exist_ok=True)
    R_rules, R_ens, R_ml, R_now, R_final = [], [], [], [], []
    for h in hs:
        T = targets(px, h)
        idx = T.index[(T.index >= START)]
        X = X0.reindex(idx); T = T.reindex(idx)
        for Y in YEARS + ['현재']:
            t0 = time.time()
            if Y == '현재':
                te = X.index[-1:]
                tr_mask = T['ret'].notna()
            else:
                te_mask = X.index.year == Y
                if te_mask.sum() < 20: continue
                te = X.index[te_mask]
                first = te[0]; pos = X.index.get_loc(first)
                tr_mask = pd.Series(False, index=X.index); tr_mask.iloc[:max(0, pos - h)] = True
                tr_mask &= T['ret'].notna()
            tr = X.index[tr_mask.values]
            if len(tr) < 500: continue
            Xtr, Xte = X.loc[tr], X.loc[te]
            names, fid, Ctr, Cte = conditions(Xtr, Xte)
            mcols = [c for c in Xtr.columns if Xtr[c].notna().sum() >= 150]   # 학습 구간에 값이 거의 없는 지표는 기계학습에서 뺌
            Xtr_m, Xte_m = Xtr[mcols].values, Xte[mcols].values
            for ty in TYPES + ['ret']:
                ytr = T.loc[tr, ty]; yte = T.loc[te, ty]
                ok = ytr.notna().values
                if ty != 'ret':
                    if ytr[ok].nunique() < 2: continue
                    rules, base = mine(Ctr[ok], ytr.values[ok].astype(np.float32), fid, h)
                    okte = yte.notna().values
                    base_te = float(yte[okte].mean()) if okte.any() else np.nan
                    up_any = np.zeros(len(te), bool); dn_any = np.zeros(len(te), bool)
                    for rule, sgn, p, n, sc in rules:
                        fire = Cte[:, list(rule)].prod(axis=1) > 0
                        if sgn > 0: up_any |= fire
                        else: dn_any |= fire
                        rec = {'대상': inst, 'h': h, '종류': ty, '해': Y, '규칙': ' & '.join(names[i] for i in rule), '조건수': len(rule),
                               '방향': '높임' if sgn > 0 else '낮춤', '학습확률': p, '학습기본': float(base), '학습발생일': n, '점수': sc,
                               '시험발생일': int((fire & okte).sum()), '시험적중': float(yte[fire & okte].mean()) if (fire & okte).any() else np.nan, '시험기본': base_te}
                        if Y == '현재': rec['오늘발생'] = bool(fire[-1]); R_final.append(rec)
                        else: R_rules.append(rec)
                    if Y != '현재':
                        for side, msk in (('높임', up_any & ~dn_any), ('낮춤', dn_any & ~up_any)):
                            mm = msk & okte
                            R_ens.append({'대상': inst, 'h': h, '종류': ty, '해': Y, '쪽': side, '신호일': int(mm.sum()), '시험일': int(okte.sum()),
                                          '적중': float(yte[mm].mean()) if mm.any() else np.nan, '기본': base_te, '학습기본': float(base)})
                # 기계학습
                Xm_tr = Xtr_m[ok]; y_m = ytr.values[ok]
                try:
                    mdl = ml_fit(Xm_tr, y_m if ty == 'ret' else y_m.astype(int), 'reg' if ty == 'ret' else 'clf')
                except Exception as e:
                    print('ml 실패', inst, h, ty, Y, e); continue
                if Y == '현재':
                    v = mdl.predict(Xte_m) if ty == 'ret' else mdl.predict_proba(Xte_m)[:, 1]
                    R_now.append({'대상': inst, 'h': h, '종류': ty, '날짜': str(te[-1].date()), '예측': float(v[-1]), '학습기본': float(np.mean(y_m))})
                    continue
                okte = yte.notna().values
                if okte.sum() < 15: continue
                if ty == 'ret':
                    pr = mdl.predict(Xte_m[okte]); ic = stats.spearmanr(pr, yte.values[okte])[0]
                    R_ml.append({'대상': inst, 'h': h, '종류': ty, '해': Y, '시험일': int(okte.sum()), 'IC': ic})
                else:
                    pr = mdl.predict_proba(Xte_m[okte])[:, 1]; yy = yte.values[okte].astype(int)
                    bt = float(np.mean(y_m))
                    auc = roc_auc_score(yy, pr) if len(set(yy)) == 2 else np.nan
                    bs = brier_score_loss(yy, pr); bs0 = brier_score_loss(yy, np.full(len(yy), bt))
                    top = pr >= np.quantile(pr, 0.8); bot = pr <= np.quantile(pr, 0.2)
                    R_ml.append({'대상': inst, 'h': h, '종류': ty, '해': Y, '시험일': int(okte.sum()), 'AUC': auc, 'BSS': 1 - bs / bs0 if bs0 > 0 else np.nan,
                                 '상위20%적중': float(yy[top].mean()), '하위20%적중': float(yy[bot].mean()), '기본': float(yy.mean()), '학습기본': bt, '평균예측': float(pr.mean())})
            print(inst, h, Y, f'{time.time() - t0:.0f}s', flush=True)
    for nm, rows in (('rules_oos', R_rules), ('ens_oos', R_ens), ('ml_oos', R_ml), ('now_ml', R_now), ('rules_final', R_final)):
        pd.DataFrame(rows).to_csv(os.path.join(outdir, f'{nm}.csv'), index=False, encoding='utf-8')
    json.dump({'inst': inst, 'h': hs, 'finished': time.strftime('%Y-%m-%d %H:%M')}, open(os.path.join(outdir, 'done.json'), 'w'))


if __name__ == '__main__':
    run(sys.argv[1], [int(x) for x in sys.argv[2].split(',')])
