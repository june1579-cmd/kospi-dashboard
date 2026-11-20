"""A6 조합 에이전트 — '맞으면 80% 이상'인 좁은 조건 조합을 찾는다(정밀도 우선 규칙 탐색).

자료: 콜벽 지표(A2, 2015~) + 일별 지표 207개(선물·옵션 수급, 해외, 신용·반대매매, 가격, 달력; deriv/scan) .
대상: 코스피200 선물(연속) 다음 날 시가 → h일 뒤 종가가 오를지(+1)·내릴지(−1). h = round.json a06.h.
방법: 조건 = 지표의 학습 구간 분위(하위10·20%, 상위20·10%) 또는 값(달력). 1~3개 조합, 정밀도 하한(윌슨, 유효 표본 = 발생일 ÷ √h)으로 고른다.
검증: 개발 구간 안에서 해마다 따로(2016~2023) — 그 해 이전 자료로만 골라 그 해에 적용한 신호를 모아 A8 의 개발 구간 성적으로 쓴다.
      최종 규칙은 개발 구간 전체로 다시 골라 잠금 구간(2024~) 신호 날짜를 만든다(결과 계산은 A8).
"""
import os
import pickle
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lab_common as L  # noqa: E402
import scan_run as SR  # noqa: E402

cfg = L.round_cfg().get('a06', {})
HS = cfg.get('h', [1, 3, 5, 10, 20])
MIN_PREC = cfg.get('min_train_prec', 0.72)
MIN_NEFF = cfg.get('min_neff', 15)
TOPK = cfg.get('topk', 10)
YEARS = list(range(cfg.get('first_test_year', 2016), 2024))
TRAIN_START = pd.Timestamp(cfg.get('train_start', '2010-01-01'))


def dataset():
    feat = pickle.load(open(os.path.join(L.LAB, 'work', 'lab_feat.pkl'), 'rb'))
    X0 = SR.X0
    keep_ow = cfg.get('ow_features')
    W = feat['wide'] if not keep_ow else feat['wide'][[c for c in feat['wide'].columns if any(k in c for k in keep_ow)]]
    X = X0.join(W, how='left')
    drop = cfg.get('drop_prefix', [])
    X = X[[c for c in X.columns if not any(c.startswith(p) for p in drop)]]
    if cfg.get('regime_feats'):   # 갈래 B 라운드 4: 장세 연속 지표를 조건·특징에 더함(A7 도 이 자료를 씀)
        X = X.join(L.regime_features(), how='left')
    if cfg.get('flow_sums'):   # 갈래 B 라운드 9: 외국인 선물·콜·풋 n일 누적 순매수(라운드 7 A4 에서 3일 누적이 개발 하한을 올림)를 조건·특징에 — A7 도 이 자료를 씀
        Fl = L.flows()[['fut_for', 'call_for', 'put_for']]
        add = pd.DataFrame({f'fl_{c}_s{n}': Fl[c].rolling(n, min_periods=n).sum() for c in Fl.columns for n in cfg['flow_sums']})
        X = X.join(add, how='left')
    return X


def wilson_lb(k, n, z=1.28):
    with np.errstate(divide='ignore', invalid='ignore'):
        p = k / n; d = 1 + z * z / n; c = p + z * z / (2 * n); h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
        return (c - h) / d


def mine_prec(C, y, fid, h):
    heff = np.sqrt(h)
    Cy = C * y[:, None]
    N1 = C.sum(0); H1 = Cy.sum(0)
    N2 = C.T @ C; H2 = C.T @ Cy
    same = fid[:, None] == fid[None, :]
    LB2 = wilson_lb(H2 / heff, N2 / heff); LB2[(N2 / heff < MIN_NEFF) | same | ~np.isfinite(LB2)] = 0
    LB1 = wilson_lb(H1 / heff, N1 / heff); LB1[(N1 / heff < MIN_NEFF) | ~np.isfinite(LB1)] = 0
    cand = [((int(i),), float(LB1[i])) for i in np.argsort(-LB1)[:150] if LB1[i] > 0]
    iu = np.triu_indices_from(LB2, k=1); flat = LB2[iu]
    top2 = np.argsort(-flat)[:400]
    pairs = [((int(iu[0][k]), int(iu[1][k])), float(flat[k])) for k in top2 if flat[k] > 0]
    cand += pairs
    for (i, j), _ in pairs[:40]:
        pm = C[:, i] * C[:, j]
        N3 = pm @ C; H3 = (pm * y) @ C
        LB3 = wilson_lb(H3 / heff, N3 / heff); LB3[(N3 / heff < MIN_NEFF) | ~np.isfinite(LB3) | (fid == fid[i]) | (fid == fid[j])] = 0
        for k in np.argsort(-LB3)[:6]:
            if LB3[k] > 0: cand.append((tuple(sorted((i, j, int(k)))), float(LB3[k])))
    cand.sort(key=lambda t: -t[1])
    chosen, masks, seen = [], [], set()
    for rule, lb in cand:
        if rule in seen: continue
        seen.add(rule)
        m = C[:, list(rule)].prod(axis=1) > 0
        prec = (y[m].mean() if m.any() else 0)
        if prec < MIN_PREC: continue
        if any((m & mm).sum() / max(1, (m | mm).sum()) > 0.6 for mm in masks): continue
        chosen.append((rule, lb, float(prec), int(m.sum()))); masks.append(m)
        if len(chosen) >= TOPK: break
    return chosen


def main():
    X = dataset()
    P = L.prices(); px = P['K200F']
    td = X.index
    od = L.out_dir('a06')
    cands, log_rows = [], []
    n_rules_tried = 0
    for tkey, h, yup, exs in targets(px, td):
        for direction in (1, -1):
            y_all = yup if direction > 0 else (1 - yup)
            ex_of = (lambda ss, h=h: [L.exit_after(td, s_, h) for s_ in ss]) if exs is None else (lambda ss, exs=exs: [exs.get(s_, pd.NaT) for s_ in ss])
            tgt = f'{h}일' if exs is None else f'{h}일 안 큰 변동(±{BK:g}σ) 먼저'
            idt = f'h{h}' if exs is None else f'b{h}'
            oos_sig = {k: [] for k in ('top1', 'top3', 'any')}
            templ = {}
            for Y in YEARS:
                te = td[(td.year == Y)]
                pos = td.get_loc(te[0])
                tr = td[(td >= TRAIN_START) & (np.arange(len(td)) < pos - h)]
                tr = tr[y_all.loc[tr].notna().values]
                names, fid, Ctr, Cte = SR.conditions(X.loc[tr], X.loc[te])
                rules = mine_prec(Ctr, y_all.loc[tr].values.astype(np.float32), fid, h)
                n_rules_tried += Ctr.shape[1] ** 2 // 2
                fires = [Cte[:, list(rr)].prod(axis=1) > 0 for rr, *_ in rules]
                for k, kk in (('top1', 1), ('top3', 3), ('any', len(fires))):
                    if fires[:kk]:
                        f = np.any(fires[:kk], axis=0)
                        oos_sig[k] += list(te[f])
                for (rr, lb, prec, n), f in zip(rules, fires):
                    tname = ' & '.join(SR_strip(names[i]) for i in rr)
                    templ.setdefault(tname, []).extend(list(te[f]))
                    log_rows.append({'h': h, '방향': direction, '해': Y, '규칙': ' & '.join(names[i] for i in rr), '학습정밀도': prec, '학습발생': n, '하한': lb, '시험발생': int(f.sum())})
            # 최종(개발 구간 전체로 고름) → 전체 기간 신호
            tr = td[(td >= TRAIN_START) & (td <= L.DEV_END - pd.Timedelta(days=int(h * 1.5)))]
            tr = tr[y_all.loc[tr].notna().values]
            names, fid, Ctr, Call = SR.conditions(X.loc[tr], X)
            rules = mine_prec(Ctr, y_all.loc[tr].values.astype(np.float32), fid, h)
            fires = [Call[:, list(rr)].prod(axis=1) > 0 for rr, *_ in rules]
            for k, kk in (('top1', 1), ('top3', 3), ('any', len(fires))):
                if not fires[:kk] or len(oos_sig[k]) < 10: continue
                f = np.any(fires[:kk], axis=0)
                sig_all = td[f]
                cands.append({'id': f'A6_ens_{k}_{idt}_{"up" if direction > 0 else "dn"}', 'agent': 'A6', 'family': 'rules_ens' if exs is None else 'rules_ens_big',
                              'desc': f'조합 규칙 묶음({k}) → {tgt} {"상승" if direction > 0 else "하락"}', 'direction': direction,
                              'trades': pd.DataFrame({'signal': sig_all, 'exit': ex_of(sig_all)}).dropna(),
                              'trades_dev': pd.DataFrame({'signal': oos_sig[k], 'exit': ex_of(oos_sig[k])}).dropna(),
                              'rules_final': [' & '.join(names[i] for i in rr) for rr, *_ in rules[:kk]]})
            # 뒤 구간 적합(fit_period p2, 2026-11-21~ 교차 모드에서만): 뒤 구간(2024~)에서 규칙을 골라 앞 구간에 적용 — 뒤→앞 방향 전용
            if L.fit_p2_enabled(cfg):
                tr2 = td[(td >= L.HOLD_START) & (td <= td[-1] - pd.Timedelta(days=int(h * 1.5)))]
                tr2 = tr2[y_all.loc[tr2].notna().values]
                if len(tr2) >= 250:
                    names2, fid2, C2, Call2 = SR.conditions(X.loc[tr2], X)
                    rules2 = mine_prec(C2, y_all.loc[tr2].values.astype(np.float32), fid2, h)
                    fires2 = [Call2[:, list(rr)].prod(axis=1) > 0 for rr, *_ in rules2]
                    for k, kk in (('top1', 1), ('top3', 3)):
                        if not fires2[:kk]: continue
                        sig2 = td[np.any(fires2[:kk], axis=0)]
                        t2 = pd.DataFrame({'signal': sig2, 'exit': ex_of(sig2)}).dropna()
                        cands.append({'id': f'A6_fp2_{k}_{idt}_{"up" if direction > 0 else "dn"}', 'agent': 'A6', 'family': 'rules_fp2',
                                      'desc': f'[뒤 구간 적합] 조합 규칙 묶음({k}) → {tgt} {"상승" if direction > 0 else "하락"}', 'direction': direction,
                                      'trades': t2, 'trades_dev': t2, 'fit_period': 'p2',
                                      'rules_final': [' & '.join(names2[i] for i in rr) for rr, *_ in rules2[:kk]]})
            # 해마다 거듭 뽑힌 규칙 틀(문턱만 다름)
            final_t = {' & '.join(SR_strip(names[i]) for i in rr): (rr, f) for (rr, *_), f in zip(rules, fires)}
            for tname, sigs in templ.items():
                yrs = len(set(pd.DatetimeIndex(sigs).year)) if sigs else 0
                if tname in final_t and len(sigs) >= 8 and yrs >= 3:
                    rr, f = final_t[tname]
                    sig_all = td[f]
                    cands.append({'id': f'A6_rule_{idt}_{"up" if direction > 0 else "dn"}_{abs(hash(tname)) % 10**6}', 'agent': 'A6', 'family': 'rule' if exs is None else 'rule_big',
                                  'desc': f'{tname} → {tgt} {"상승" if direction > 0 else "하락"}', 'direction': direction,
                                  'trades': pd.DataFrame({'signal': sig_all, 'exit': ex_of(sig_all)}).dropna(),
                                  'trades_dev': pd.DataFrame({'signal': sigs, 'exit': ex_of(sigs)}).dropna(),
                                  'rules_final': [' & '.join(names[i] for i in rr)]})
            print(tkey, h, 'dir', direction, '후보 누계', len(cands), flush=True)
    pd.DataFrame(log_rows).to_csv(os.path.join(od, 'rules_by_year.csv'), index=False, encoding='utf-8')
    L.save_candidates('a06', cands)
    open(os.path.join(od, 'trials.txt'), 'w').write(str(n_rules_tried))


BARRIER = cfg.get('barrier', [])   # 큰 변동 창(거래일), 2026-11-20 갈래 B
BK = cfg.get('barrier_k', 1.0)


def targets(px, td):
    """(종류, 기간, 오름=1 표지 Series(td), 청산일 dict 또는 None). 고정 보유 h일 + 큰 변동 창 W일(먼저 닿는 쪽)."""
    out = []
    for h in HS:
        r = (px['close'].shift(-h) / px['open'].shift(-1) - 1).reindex(td)
        out.append(('h', h, (r > 0).astype(float).where(r.notna() & (r != 0)), None))
    for W in BARRIER:
        y, ex = L.barrier_exits(px, W, BK)
        out.append(('b', W, y.reindex(td), ex.reindex(td).dropna().to_dict()))
    return out


def SR_strip(nm):
    import re
    return re.sub(r'\([^)]*\)', '', nm)


if __name__ == '__main__':
    main()
