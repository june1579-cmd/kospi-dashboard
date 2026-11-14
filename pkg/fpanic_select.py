# -*- coding: utf-8 -*-
"""fpanic_select.py — 외국인 투매·개인 매수 신호의 그해 조합 10개를 다시 뽑는다(해마다 1월 1일 자동 실행: .github/workflows/fpanic-yearly.yml)

   python pkg/fpanic_select.py [--year 2027] [--wb data/통합_원자료.xlsx] [--force]
   · 그해(year) 이전 자료만 쓴다. 지표 77개 × 최근 3년 백분위 조건 924개의 3조건 조합 1억 3천만 개를 '10거래일 뒤 상승'으로 채점해 상위 400개를 고르고,
     조건 하나를 더 붙인 4조건 중 상위 10개를 pkg/fpanic_rules.json 의 "<year>" 에 적는다(이미 있으면 --force 없이는 건너뜀).
   · 고르는 기준: 신호 120일 이상, 5개 해 이상에서 켜짐, 켜진 해의 70% 이상에서 적중률 > 50%, 점수 = (맞은 날 + 40·평균 적중률) ÷ (켜진 날 + 40).
   · 해마다 마지막 20거래일과 결과를 아직 모르는 날은 채점에서 뺀다(다음 해 정보가 섞이지 않게).
   · 동점은 조건 번호 순으로 정한다(실행 환경이 달라도 같은 결과가 나오게).
   연구 기록: research/combo_search_2026-11-14/ (걷기 검증 2018~2026: 110일·10묶음, 10일 뒤 상승 80.9% vs 아무 날 54.3%)"""
import argparse, json, os, sys, time, datetime as dt, numpy as np, pandas as pd, warnings
warnings.filterwarnings('ignore')
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE); sys.path.insert(0, HERE)
HI = (0.5, 0.6, 0.7, 0.8, 0.9, 0.95); LO = (0.5, 0.4, 0.3, 0.2, 0.1, 0.05); H = 10; GAP = 20; TOP = 30; BEAM = 400; KEEP = 10

def features77(D, fx_csv):
    K, V, F, L, C = D['K'], D['V'], D['F'], D['L'], D['C']; c, o, h, l = K.close, K.open, K.high, K.low; idx = c.index; r = c.pct_change(); X = pd.DataFrame(index=idx)
    for n in (1, 3, 5, 10, 20, 60, 120): X[f'ret{n}'] = c.pct_change(n) * 100
    for n in (5, 20, 60, 120, 200): X[f'disp{n}'] = (c / c.rolling(n).mean() - 1) * 100
    X['dd250'] = (c / c.rolling(250, min_periods=120).max() - 1) * 100; X['up250'] = (c / c.rolling(250, min_periods=120).min() - 1) * 100
    X['dd60'] = (c / c.rolling(60).max() - 1) * 100; X['up60'] = (c / c.rolling(60).min() - 1) * 100
    def rsi(n):
        d = c.diff(); u = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean(); dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean(); return 100 - 100 / (1 + u / dn)
    X['rsi14'] = rsi(14); X['rsi5'] = rsi(5)
    e12, e26 = c.ewm(span=12, adjust=False).mean(), c.ewm(span=26, adjust=False).mean(); macd = e12 - e26; X['macd_hist'] = (macd - macd.ewm(span=9, adjust=False).mean()) / c * 100; X['macd'] = macd / c * 100
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1); X['atr14'] = tr.rolling(14).mean() / c * 100
    for n in (5, 20, 60): X[f'rv{n}'] = r.rolling(n).std() * np.sqrt(250) * 100
    X['rv_5_60'] = X['rv5'] / X['rv60']; X['rng_pos'] = (c - l) / (h - l).replace(0, np.nan); X['gap'] = (o / c.shift() - 1) * 100; X['intra'] = (c / o - 1) * 100
    up = (r > 0).astype(int); X['streak'] = up.groupby((up != up.shift()).cumsum()).cumcount().add(1) * np.where(up == 1, 1, -1); X['up_days10'] = up.rolling(10).sum()
    val = K.val / 1e6; X['val_r20'] = val / val.rolling(20).mean(); X['val5_r60'] = val.rolling(5).mean() / val.rolling(60).mean()
    fo, ind, ins = F.foreign.reindex(idx) / 1000, F.indiv.reindex(idx) / 1000, F.inst.reindex(idx) / 1000
    for nm, s in (('for', fo), ('ind', ind), ('ins', ins)):
        for n in (1, 5, 20, 60): X[f'{nm}{n}'] = s.rolling(n).sum() if n > 1 else s
        X[f'{nm}20_val'] = s.rolling(20).sum() / val.rolling(20).sum() * 100
    fb = (fo > 0).astype(int); X['for_streak'] = fb.groupby((fb != fb.shift()).cumsum()).cumcount().add(1) * np.where(fb == 1, 1, -1)
    dep = L.deposit.reindex(idx).shift(1) / 1e6; cred = C.credit.reindex(idx).shift(1) / 1e6; liq = L.liq.reindex(idx).shift(1) / 100; misu = L.misu.reindex(idx).shift(1) / 100
    X['cd_ratio'] = cred / dep * 100
    for n in (5, 20, 60): X[f'dep_{n}d'] = dep.pct_change(n) * 100; X[f'cr_{n}d'] = cred.pct_change(n) * 100
    X['cr_1d'] = cred.pct_change() * 100; X['cr_vs_high'] = (cred / cred.rolling(250, min_periods=60).max() - 1) * 100; X['dep_vs_high'] = (dep / dep.rolling(250, min_periods=60).max() - 1) * 100
    X['liq1'] = liq; X['liq5'] = liq.rolling(5).sum(); X['liq_ratio'] = liq / misu.shift(1) * 100; X['misu_5d'] = misu.pct_change(5) * 100; X['misu_dep'] = misu / (dep * 1e4) * 100
    X['val_dep'] = val / dep * 100; X['liq5_r60'] = liq.rolling(5).mean() / liq.rolling(60).mean()
    vk = V.close.reindex(idx).ffill(limit=3); X['vk'] = vk; X['vk_1d'] = vk.pct_change() * 100; X['vk_5d'] = vk.pct_change(5) * 100; X['vk_20d'] = vk.pct_change(20) * 100; X['vk_r60'] = vk / vk.rolling(60).mean(); X['vk_rv20'] = vk / X['rv20']
    vix = D['VIX']; vix = vix.reindex(idx.union(vix.index)).ffill().reindex(idx).shift(1); X['vix'] = vix; X['vix_5d'] = vix.pct_change(5) * 100; X['vix_r60'] = vix / vix.rolling(60).mean()
    fx = pd.read_csv(fx_csv, parse_dates=['date']).set_index('date').usdkrw; fx = fx.reindex(idx.union(fx.index)).ffill().reindex(idx).shift(1)
    X['fx_5d'] = fx.pct_change(5) * 100; X['fx_20d'] = fx.pct_change(20) * 100; X['fx_r250'] = fx / fx.rolling(250, min_periods=120).mean()
    X = X.replace([np.inf, -np.inf], np.nan)
    return X.rolling(750, min_periods=250).rank(pct=True), c

def select(RK, c, year, log=print):
    idx = RK.index; N = len(idx); yrs = idx.year.values
    cols, names = [np.ones(N, bool)], ['(항상)']
    for ft in RK.columns:
        v = RK[ft].values
        for q in HI: cols.append(np.nan_to_num(v, nan=-1) >= q); names.append(f'{ft}>=p{int(q * 100)}')
        for q in LO: cols.append(np.where(np.isnan(v), 2, v) <= q); names.append(f'{ft}<=p{int(q * 100)}')
    C = np.stack(cols, 1); M = C.shape[1]; Cf = C.astype(np.float32)
    r = ((c.shift(-H) / c - 1) * 100).values; r20 = ((c.shift(-GAP) / c - 1) * 100).values
    from_end = pd.Series(np.arange(N)).groupby(yrs).transform(lambda s: s.max() - s).values
    valid = ~np.isnan(r) & ~np.isnan(r20) & (from_end >= GAP) & (yrs >= 2007) & (yrs < year); u = (r > 0) & valid
    YEARS = [y for y in range(2007, year)]; rows = {y: np.where((yrs == y) & valid)[0] for y in YEARS}
    tri = np.triu(np.ones((M, M), bool), 1); cand = []; t0 = time.time()
    for k in range(M - 2):
        m = M - k - 1; ck = C[:, k]; nC = np.zeros((m, m), np.float32); hC = np.zeros_like(nC); act = np.zeros_like(nC); good = np.zeros_like(nC)
        for y in YEARS:
            R = rows[y]; sel = R[ck[R]]
            if not len(sel): continue
            A = Cf[sel, k + 1:]; n_y = A.T @ A; A1 = Cf[sel[u[sel]], k + 1:]; h_y = A1.T @ A1
            nC += n_y; hC += h_y; a = n_y >= 5; act += a; good += a & (h_y > 0.5 * n_y)
        p0 = hC.sum() / max(nC.sum(), 1)
        s = np.where((nC >= 120) & (act >= 5) & tri[k + 1:, k + 1:] & (good >= 0.7 * act), (hC + 40 * p0) / (nC + 40), -1).ravel()
        kk = min(TOP, s.size - 1); top = np.argpartition(s, -kk)[-kk:]
        for t in top:
            if s[t] > 0: i, j = divmod(int(t), m); cand.append((float(s[t]), k, k + 1 + i, k + 1 + j))
        if k % 100 == 0: log(f'  3조건 {k}/{M} · {time.time() - t0:.0f}초 · 후보 {len(cand):,}')
    cand.sort(key=lambda x: (-x[0], x[1], x[2], x[3])); gg = [x[1:] for x in cand[:BEAM]]
    T = np.stack([C[:, a] & C[:, b] & C[:, c_] for a, b, c_ in gg], 1); Tf = T.astype(np.float32)
    nC = np.zeros((len(gg), M), np.float32); hC = np.zeros_like(nC); act = np.zeros_like(nC); good = np.zeros_like(nC)
    for y in YEARS:
        rw = rows[y]; ru = rw[u[rw]]; n_y = Tf[rw].T @ Cf[rw]; h_y = Tf[ru].T @ Cf[ru]; nC += n_y; hC += h_y; a = n_y >= 5; act += a; good += a & (h_y > 0.5 * n_y)
    p0 = u[valid].mean(); sc = np.where((nC >= 120) & (act >= 5) & (good >= 0.7 * act), (hC + 40 * p0) / (nC + 40), -1)
    for ti, g in enumerate(gg): sc[ti, list(g)] = -1
    flat = sc.ravel(); order = np.lexsort((np.arange(flat.size), -flat))[:KEEP]; rules = []
    for t in order:
        if flat[t] <= 0: break
        ti, cj = divmod(int(t), M); rules.append({'conds': [names[i] for i in list(gg[ti]) + [cj]], 'train_n': int(nC[ti, cj]), 'train_hit': round(float(hC[ti, cj] / nC[ti, cj] * 100), 1)})
    return rules, dict(conds=M, triples=M * (M - 1) * (M - 2) // 6, last=str(idx[-1])[:10], train_days=int(valid.sum()), secs=round(time.time() - t0))

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--year', type=int, default=(dt.datetime.utcnow() + dt.timedelta(hours=9)).year)
    ap.add_argument('--wb', default=os.path.join(ROOT, 'data', '통합_원자료.xlsx')); ap.add_argument('--fx', default=os.path.join(ROOT, 'out', 'fx_daily.csv'))
    ap.add_argument('--rules', default=os.path.join(HERE, 'fpanic_rules.json')); ap.add_argument('--force', action='store_true'); ap.add_argument('--dry', action='store_true'); a = ap.parse_args()
    RULES = json.load(open(a.rules, encoding='utf-8'))
    if str(a.year) in RULES and not a.force and not a.dry: print(f'{a.year}년 조합이 이미 있다 — 건너뜀(--force 로 다시 뽑기)'); return 0
    import reproduce, quant
    D = reproduce.load(a.wb); D = D if isinstance(D, dict) else D[0]; RK, c = features77(quant.load_history(D), a.fx)
    print(f'{a.year}년용 조합 고르기 — 자료 {str(c.index[0])[:10]} ~ {str(c.index[-1])[:10]}, 지표 {RK.shape[1]}개')
    rules, info = select(RK, c, a.year); print(json.dumps(info, ensure_ascii=False))
    for i, x in enumerate(rules): print(f"  {i + 1}. {' & '.join(x['conds'])} · 학습 {x['train_n']}일 {x['train_hit']}%")
    if len(rules) < KEEP: print(f'조합이 {len(rules)}개뿐 — 저장하지 않는다(지난해 것을 계속 씀)'); return 1
    if a.dry: json.dump(rules, open(f'/tmp/fpanic_{a.year}.json', 'w'), ensure_ascii=False); return 0
    RULES[str(a.year)] = rules; json.dump(dict(sorted(RULES.items())), open(a.rules, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    os.makedirs(os.path.join(ROOT, 'report'), exist_ok=True)
    top = rules[0]['conds']; msg = f"[{a.year}년 외국인 투매·개인 매수 신호]\n조합 10개를 {a.year - 1}년까지 자료로 다시 뽑음\n1위: " + ' · '.join(top) + f"\n(학습 {rules[0]['train_n']}일 중 {rules[0]['train_hit']}% 상승, 3조건 {info['triples']:,}개 채점)\n다음 자동 갱신부터 적용"
    open(os.path.join(ROOT, 'report', 'kakao_fpanic.txt'), 'w', encoding='utf-8').write(msg[:200] + '\n'); print(msg)
    return 0

if __name__ == '__main__': sys.exit(main())
