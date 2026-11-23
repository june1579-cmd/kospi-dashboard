# -*- coding: utf-8 -*-
"""Signal A — T3 합의·확률. SPEC.md 그대로 구현한다(돌린 뒤 격자·문턱을 고치지 않는다).

  A 확률 모형: 해마다(2013~2026) 그 전 자료로 다시 학습 → 그 해 오를 확률. 문턱 = 그 전 표본 밖 예측의 상위 10%·5% 선. (36 절차)
  B 합의: 조건 893개(지표 434 × 자리 2 + 사건 25) 중 그 전 자료로 고른 것들이 같은 날 켜진 비율. (12 절차 + '하나라도' 3)
  vol=True(T4 가 부름): 대상만 '±0.5σ√h 먼저 닿기'로, 벽 거리는 σ 배수로 바꾼 같은 절차. id 앞 'V_', desc 앞 '[변동폭 맞춤]'.
명령: python run.py --nparts | --part i/n | --merge  [--quick]
"""
import os
import sys
import time
import warnings

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sa_common as C  # noqa: E402

warnings.filterwarnings('ignore')
TRACK = 't3'
HS = (3, 5, 10)
SETS = ('all', 'allev')
SET_NAME = {'all': '입력 전부(434개)', 'allev': '입력 전부+사건 지표'}
MODELS = ('gb', 'lr', 'ens')
MODEL_NAME = {'gb': '나무 모형', 'lr': '선형 모형', 'ens': '나무·선형 평균'}
QS = (0.90, 0.95)
MODEL_YEARS = list(range(2013, 2027))          # 2013~2015 예측은 문턱 정하는 데만
MIN_PREV = 200                                 # 문턱을 정할 때 필요한 그 전 표본 밖 예측 수
WALLS = ('F0', 'F1', 'Q', 'ALL')
RANK_WIN, RANK_MIN, HI, LO = 250, 125, 0.8, 0.2
SELS = ('s60', 'w50')
SEL_NAME = {'s60': '과거 적중 60% 이상·독립 30건 이상인 조건', 'w50': '과거 윌슨 하한 상위 50개 조건'}
THRS = ('f20', 'p95')
VOL_K = 0.5
PARTS = [(h, s) for h in HS for s in SETS]     # 조각 1~6 = 모형, 7 = 합의
NOT_INCLUDED = [
    '조건 쌍·3개 조합의 합의(전수 조사 deriv/combo 에서 이미 봄 — 여기서는 조건 하나짜리와 사건 지표만)',
    '내림(−1) 방향 확률·합의',
    '확률 문턱의 다른 꼴(상위 20%·고정 0.6·직전 3년 문턱), 확률 보정, 모형 설정 탐색',
    '합의의 다른 격자(자리 10%·30%, 순위 창 120·500일, 적중 문턱 65%·70%, 합의 문턱 10%·30%), 합의 비율을 모형 입력으로 넣기',
    '보유일 1·20일, 묶음별(옵션만·선물만) 모형, 벽 종류 F2·F3·위클리 사건 지표',
]
_OUT = {}                                      # merge 가 만든 표·요약(vol=False 일 때 main 이 out/ 에 쓴다)


# ------------------------------------------------------------------ 자료·대상
def sigma60(D):
    """신호일까지의 직전 60일 일간 종가 등락 표준편차(소수)."""
    return pd.Series(D.c).pct_change().rolling(60).std().values


def target(D, h, vol):
    """(y, ex): y = 1/0/nan(모름·뺌), ex = 청산 위치(없으면 -1)."""
    n = D.n
    if not vol:
        r = D.fwd(h); y = np.where(np.isfinite(r), (r > 0).astype(float), np.nan); ex = np.arange(n) + h; ex[ex >= n] = -1
        return y, ex
    sg = sigma60(D); y = np.full(n, np.nan); ex = np.full(n, -1, dtype=int)
    for i in range(n - 1):
        if not np.isfinite(sg[i]) or sg[i] <= 0: continue
        e = i + 1; w = VOL_K * sg[i] * np.sqrt(h); up = D.o[e] * (1 + w); dn = D.o[e] * (1 - w)
        for j in range(e, min(n - 1, e + h - 1) + 1):
            if D.l[j] <= dn: y[i] = 0.0; ex[i] = j; break       # 같은 날 둘 다면 0(불리하게)
            if D.h[j] >= up: y[i] = 1.0; ex[i] = j; break
    return y, ex


def events(D, vol):
    """사건 지표 25개(0/1). 값이 없는 날은 0."""
    X = D.X; E = {}
    sg = pd.Series(sigma60(D) * 100, index=D.td)
    b15, b30 = (1.5 * sg, 3.0 * sg) if vol else (1.5, 3.0)
    for t in WALLS:
        dist = X[f'OW_{t}_wall_dist%']
        if f'OW_{t}_wall_oi_chg5%' in X: oi5 = X[f'OW_{t}_wall_oi_chg5%']
        else: oi = X[f'OW_{t}_wall_oi']; oi5 = (oi / oi.shift(5).where(oi.shift(5) > 0) - 1) * 100
        n15 = (dist > 0) & (dist <= b15); up = oi5 > 0
        E[f'EV_{t}_near15'] = n15; E[f'EV_{t}_near30'] = (dist > 0) & (dist <= b30)
        E[f'EV_{t}_new'] = X[f'OW_{t}_wall_new'] == 1; E[f'EV_{t}_oi5up'] = up; E[f'EV_{t}_near15_oi5up'] = n15 & up
    f3 = X['F_외국인_1d'].rolling(3).sum() > 0; s3 = X['S_외국인현물_1d'].rolling(3).sum() > 0
    E['EV_fut3'] = f3; E['EV_spot3'] = s3; E['EV_both3'] = f3 & s3; E['EV_ma60'] = X['PK_이평괴리_60'] > 0
    E['EV_Q_near15_oi5up_lag1'] = E['EV_Q_near15_oi5up'].shift(1, fill_value=False)
    return pd.DataFrame(E, index=D.td).fillna(False).astype(float)


def base_cols(D, quick):
    cols = list(D.X.columns)
    return cols[::max(1, len(cols) // 50)][:50] if quick else cols


# ------------------------------------------------------------------ A 확률 모형
def fit_predict(Xtr, ytr, Xte):
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    ok = (np.isfinite(Xtr).sum(0) >= 60) & (np.nan_to_num(np.nanstd(Xtr, 0)) > 0)
    Xtr, Xte = Xtr[:, ok], Xte[:, ok]
    gb = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05, max_depth=3, min_samples_leaf=40, l2_regularization=1.0, max_bins=64,
                                        early_stopping=False, random_state=7)
    gb.fit(Xtr, ytr); pg = gb.predict_proba(Xte)[:, 1]
    keep = np.isfinite(Xtr).mean(0) >= 0.6
    A, B = Xtr[:, keep], Xte[:, keep]
    med = np.nanmedian(A, 0); lo = np.nanpercentile(A, 1, 0); hi = np.nanpercentile(A, 99, 0)
    prep = lambda M: np.clip(np.where(np.isfinite(M), M, med), lo, hi)
    A, B = prep(A), prep(B); mu = A.mean(0); sd = A.std(0); sd[sd == 0] = 1
    lr = LogisticRegression(C=0.05, max_iter=400); lr.fit((A - mu) / sd, ytr); pl = lr.predict_proba((B - mu) / sd)[:, 1]
    return pg, pl


def _year_job(M, y, ex, i0, a, te):
    idx = np.arange(len(y)); tr = np.where((idx >= i0) & (idx < a) & np.isfinite(y) & (ex >= 0) & (ex < a))[0]   # 청산이 그 해 첫날보다 앞인 날만
    if len(tr) < 400 or len(set(y[tr])) < 2: return te, None, None, len(tr)
    pg, pl = fit_predict(M[tr], y[tr], M[te])
    return te, pg, pl, len(tr)


def model_part(D, h, sname, vol, quick):
    from joblib import Parallel, delayed
    t0 = time.time(); cols = base_cols(D, quick); M = D.X[cols]
    if sname == 'allev': M = pd.concat([M, events(D, vol)], axis=1)
    M = M.values.astype(float); y, ex = target(D, h, vol); i0 = int(D.td.searchsorted(C.START))
    years = [2024, 2025, 2026] if quick else MODEL_YEARS
    jobs = []
    for Y in years:
        te = np.where(D.year == Y)[0]
        if len(te): jobs.append((te[0], te))
    res = Parallel(n_jobs=int(os.environ.get('SA_JOBS', '4')))(delayed(_year_job)(M, y, ex, i0, a, te) for a, te in jobs)
    P = {m: np.full(D.n, np.nan, dtype=np.float32) for m in ('gb', 'lr')}; ntr = {}
    for te, pg, pl, k in res:
        ntr[int(D.year[te[0]])] = int(k)
        if pg is not None: P['gb'][te] = pg; P['lr'][te] = pl
    return {'kind': 'model', 'h': h, 'set': sname, 'probs': P, 'nfeat': int(M.shape[1]), 'ntrain': ntr, 'secs': round(time.time() - t0, 1)}


# ------------------------------------------------------------------ B 합의
def conditions(D, vol, quick):
    cols = base_cols(D, quick); i_from = max(0, int(D.td.searchsorted(C.START)) - RANK_WIN - 5)
    R = D.X[cols].iloc[i_from:].rolling(RANK_WIN, min_periods=RANK_MIN).rank(pct=True).reindex(D.td)
    hi = (R >= HI).values; lo = (R <= LO).values; E = events(D, vol)
    names = [f'{c}|높음' for c in cols] + [f'{c}|낮음' for c in cols] + list(E.columns)
    return np.concatenate([hi, lo, E.values > 0], axis=1), names


def cons_part(D, vol, quick):
    t0 = time.time(); B, names = conditions(D, vol, quick); nc = B.shape[1]; n = D.n; i0 = int(D.td.searchsorted(C.START))
    hs = (5,) if quick else HS; years = [2025, 2026] if quick else C.WF_YEARS
    starts = {Y: int(np.where(D.year == Y)[0][0]) for Y in years if (D.year == Y).any()}
    sig = {}; rows = []
    for h in hs:
        y, ex = target(D, h, vol); valid = np.isfinite(y) & (ex >= 0); valid[:i0] = False
        kept = []                                          # 조건별 독립 거래(처음부터 차례로 솎으므로 어느 해에서 잘라도 그때까지의 결과와 같다)
        for j in range(nc):
            keep = []; last = -1
            for p in np.where(B[:, j] & valid)[0]:
                if p >= last: keep.append(p); last = ex[p]
            kept.append(np.asarray(keep, dtype=int))
        for Y, a in starts.items():
            nn = np.zeros(nc); kk = np.zeros(nc)
            for j in range(nc):
                kp = kept[j]; kp = kp[ex[kp] < a]; nn[j] = len(kp); kk[j] = y[kp].sum()
            hit = np.where(nn > 0, kk / np.maximum(nn, 1), np.nan)
            lb = np.array([C.wilson(k_, n_)[0] if n_ > 0 else -1.0 for k_, n_ in zip(kk, nn)])
            sel = {'s60': np.where((nn >= 30) & (hit >= 0.60))[0],
                   'w50': np.lexsort((np.arange(nc), -nn, -lb))[:50]}
            sel['w50'] = sel['w50'][nn[sel['w50']] > 0]
            te = np.where(D.year == Y)[0]
            for s in SELS:
                ix = sel[s]
                if not len(ix):
                    for t in THRS: sig[(h, s, t)] = np.r_[sig.get((h, s, t), np.zeros(0, dtype=int)), np.zeros(0, dtype=int)]
                    if s == 's60': sig[(h, s, 'any')] = sig.get((h, s, 'any'), np.zeros(0, dtype=int))
                    rows.append(dict(year=Y, h=h, sel=s, n_sel=0, past_hit=None, thr_p95=None, days_f20=0, days_p95=0, days_any=0)); continue
                frac = B[:, ix].mean(1); prev = frac[i0:a]; q95 = float(np.quantile(prev, 0.95))
                d20 = te[frac[te] >= 0.20]; d95 = te[(frac[te] >= q95) & (frac[te] > 0)]; dany = te[frac[te] > 0]
                sig[(h, s, 'f20')] = np.r_[sig.get((h, s, 'f20'), np.zeros(0, dtype=int)), d20]
                sig[(h, s, 'p95')] = np.r_[sig.get((h, s, 'p95'), np.zeros(0, dtype=int)), d95]
                if s == 's60': sig[(h, s, 'any')] = np.r_[sig.get((h, s, 'any'), np.zeros(0, dtype=int)), dany]
                rows.append(dict(year=Y, h=h, sel=s, n_sel=int(len(ix)), past_hit=round(float(kk[ix].sum() / max(nn[ix].sum(), 1)), 4), thr_p95=round(q95, 4),
                                 days_f20=int(len(d20)), days_p95=int(len(d95)), days_any=int(len(dany)),
                                 n_event_sel=int(sum(names[j].startswith('EV_') for j in ix))))
    return {'kind': 'cons', 'sig': {k: v.astype(int) for k, v in sig.items()}, 'rows': rows, 'n_conds': int(nc), 'hs': list(hs), 'secs': round(time.time() - t0, 1)}


# ------------------------------------------------------------------ 줄기 약속 함수
def n_parts(vol=False):
    return len(PARTS) + 1


def run_part(i, n, vol=False, quick=False):
    D = C.Data()
    if quick:
        if i != 1: return {'kind': 'skip'}
        return {'kind': 'quick', 'model': model_part(D, 5, 'allev', vol, True), 'cons': cons_part(D, vol, True)}
    if i <= len(PARTS):
        h, s = PARTS[i - 1]
        return model_part(D, h, s, vol, False)
    return cons_part(D, vol, False)


def _trades(D, pos, h, y, ex, vol):
    pos = np.asarray(sorted(set(int(p) for p in pos)), dtype=int)
    if not vol: return D.trades_from_pos(pos, h)
    pos = pos[np.isfinite(y[pos]) & (ex[pos] >= 0)] if len(pos) else pos
    return pd.DataFrame({'signal': D.td[pos], 'exit': D.td[ex[pos]], 'hit': y[pos].astype(int)})


def _thr_by_year(p, year, q):
    out = np.full(len(p), np.nan)
    for Y in np.unique(year):
        prev = p[(year < Y)]; prev = prev[np.isfinite(prev)]
        if len(prev) >= MIN_PREV: out[year == Y] = np.quantile(prev, q)
    return out


def _calib(p, y, r, ev):
    rows = []; m = ev & np.isfinite(p) & np.isfinite(y)
    if not m.any(): return rows
    pp, yy, rr = p[m], y[m], r[m]
    b = np.minimum((pp / 0.05).astype(int), 19)
    for k in np.unique(b):
        s = b == k; rows.append(dict(kind='구간', bin=f'{k * 0.05:.2f}~{k * 0.05 + 0.05:.2f}', n=int(s.sum()), p_mean=round(float(pp[s].mean()), 4),
                                     up=round(float(yy[s].mean()), 4), ret_mean=round(float(np.nanmean(rr[s])), 5)))
    dec = np.minimum((pd.Series(pp).rank(method='first').values - 1) * 10 // len(pp), 9).astype(int)
    for k in range(10):
        s = dec == k
        if s.any(): rows.append(dict(kind='10분위', bin=f'{k + 1}분위', n=int(s.sum()), p_mean=round(float(pp[s].mean()), 4),
                                     up=round(float(yy[s].mean()), 4), ret_mean=round(float(np.nanmean(rr[s])), 5)))
    return rows


def merge(parts, vol=False, quick=False):
    from sklearn.metrics import roc_auc_score
    D = C.Data(); pre = 'V_' if vol else ''; tag = '[변동폭 맞춤] ' if vol else ''
    failed = []; mods = []; cons = None
    if quick:
        p1 = parts[0] if parts else None
        if p1 is None: failed = [1]
        else: mods = [p1['model']]; cons = p1['cons']
    else:
        for i, p in enumerate(parts, 1):
            if p is None: failed.append(i)
            elif p.get('kind') == 'model': mods.append(p)
            elif p.get('kind') == 'cons': cons = p
    cands = []; cal = []; gain = []; notes = []; tg = {}
    tgt = lambda h: tg.setdefault(h, target(D, h, vol))
    ev = D.year >= 2016
    how = (lambda h: f'{h}거래일 안에 +0.5σ√{h} 를 −0.5σ√{h} 보다 먼저 닿으면 맞음(닿은 날 청산)') if vol else (lambda h: f'{h}일 보유')
    # ---- A 확률 모형
    auc = {}
    for mp in mods:
        h, s = mp['h'], mp['set']; y, ex = tgt(h); r = D.fwd(h)
        P = {'gb': mp['probs']['gb'].astype(float), 'lr': mp['probs']['lr'].astype(float)}; P['ens'] = (P['gb'] + P['lr']) / 2
        for m in MODELS:
            p = P[m]
            for row in _calib(p, y, r, ev): cal.append(dict(h=h, set=s, model=m, **row))
            ok = ev & np.isfinite(p) & np.isfinite(y)
            a_ = float(roc_auc_score(y[ok], p[ok])) if ok.sum() > 50 and len(set(y[ok])) == 2 else None
            g = dict(h=h, set=s, model=m, n_days=int(ok.sum()), base_up=(round(float(y[ok].mean()), 4) if ok.any() else None), auc=(round(a_, 4) if a_ is not None else None))
            for q in QS:
                thr = _thr_by_year(p, D.year, q); on = ev & np.isfinite(p) & np.isfinite(thr) & (p >= thr); pos = np.where(on)[0]
                top = on & np.isfinite(y); qn = int(round(q * 100))
                g[f'top{100 - qn}_days'] = int(top.sum()); g[f'top{100 - qn}_up'] = round(float(y[top].mean()), 4) if top.any() else None
                cands.append(dict(id=f'{pre}P_h{h}_{s}_{m}_q{qn}', family='확률 모형', direction=1, hold=h, kind='wf',
                                  desc=f'{tag}확률 모형({MODEL_NAME[m]}, {SET_NAME[s]}, 해마다 다시 학습) 오를 확률이 그 전 예측의 상위 {100 - qn}% 선 이상 → {how(h)}',
                                  params=dict(h=h, set=s, model=m, q=q), trades=_trades(D, pos, h, y, ex, vol)))
                if vol: cands[-1]['base_y'] = y.astype(np.float32)      # 판정이 '같은 해 아무 날'·가짜 신호를 같은 채점(닿기)으로 재게
            gain.append(g)
    # ---- B 합의
    sel_rows = []; n_conds = 0; n_cons = n_any = 0; hs_c = []
    if cons is not None:
        n_conds = cons['n_conds']; sel_rows = cons['rows']; hs_c = cons['hs']
        for (h, s, t), pos in sorted(cons['sig'].items()):
            y, ex = tgt(h)
            if t == 'any':
                n_any += 1; fam = '하나라도 켜지면'; d = f'{tag}{SEL_NAME[s]}(해마다 그 전 자료로 고름) 가운데 하나라도 켜진 날 → {how(h)}'
            else:
                n_cons += 1; fam = '합의'
                d = f'{tag}{SEL_NAME[s]}(해마다 그 전 자료로 고름) 가운데 ' + ('20% 이상이 함께 켜진 날' if t == 'f20' else '함께 켜진 비율이 그 전 자료의 상위 5% 선 이상인 날') + f' → {how(h)}'
            cands.append(dict(id=f'{pre}C_h{h}_{s}_{t}', family=fam, direction=1, hold=h, kind='wf', desc=d, params=dict(h=h, sel=s, thr=t), trades=_trades(D, pos, h, y, ex, vol)))
            if vol: cands[-1]['base_y'] = y.astype(np.float32)
    n_model = sum(1 for c in cands if c['family'] == '확률 모형')
    fam = {'확률 모형': n_model, '합의에 쓴 조건(조건×보유일)': n_conds * len(hs_c), '합의': n_cons, '하나라도 켜지면': n_any}
    # ---- 표·요약
    CAL = pd.DataFrame(cal); GAIN = pd.DataFrame(gain); SEL = pd.DataFrame(sel_rows)
    S = [f'### T3 따로 낸 표{" — 변동폭 맞춤판" if vol else ""}', '',
         '표본 밖 예측(2016~, 해마다 그 전 자료로만 학습)만 썼다. 10분위는 2016~ 예측 전체를 열 토막 낸 것이라 설명용이다(신호에는 그 전 자료 문턱만 씀).', '']
    f = lambda x, d=1: '–' if x is None or not np.isfinite(x) else f'{100 * x:.{d}f}%'
    if len(CAL):
        for kind, ttl in (('10분위', '확률 10분위별 실제 적중'), ('구간', '확률 0.05 구간별 실제 적중')):
            S += [f'**{ttl} (나무·선형 평균 모형)** — 칸 = 날 수 · 실제 오른 비율 · 평균 수익', '']
            sub = CAL[(CAL['model'] == 'ens') & (CAL['kind'] == kind)]; keys = sorted(set(zip(sub['h'], sub['set'])))
            bins = sorted(sub['bin'].unique(), key=lambda b: (int(b[:-2]) if kind == '10분위' else float(b[:4])))
            S += ['| 확률 ' + ('분위(1=낮음)' if kind == '10분위' else '구간') + ' | ' + ' | '.join(f'{h}일·{"사건 더함" if s == "allev" else "전부"}' for h, s in keys) + ' |', '|' + '---|' * (len(keys) + 1)]
            for b in bins:
                cells = []
                for h, s in keys:
                    x = sub[(sub['h'] == h) & (sub['set'] == s) & (sub['bin'] == b)]
                    cells.append('–' if not len(x) else (f"{int(x['n'].iloc[0])}일 · " + (f(x['up'].iloc[0]) if x['n'].iloc[0] >= 10 else '–') + f" · {100 * x['ret_mean'].iloc[0]:+.2f}%"))
                S.append(f'| {b} | ' + ' | '.join(cells) + ' |')
            S.append('')
    if len(GAIN):
        S += ['**사건 지표를 더하면 나아지나** — AUC(0.5 = 구분 못 함) · 그 전 예측 상위 10% 선 이상인 날의 실제 오른 비율(날 수)', '',
              '| 보유일 | 모형 | 아무 날 | AUC 전부 | AUC 사건 더함 | 상위 10% 전부 | 상위 10% 사건 더함 |', '|---|---|---|---|---|---|---|']
        for h in sorted(GAIN['h'].unique()):
            for m in MODELS:
                g = {s: GAIN[(GAIN['h'] == h) & (GAIN['model'] == m) & (GAIN['set'] == s)] for s in SETS}
                au = lambda s: '–' if not len(g[s]) or g[s]['auc'].iloc[0] is None or not np.isfinite(g[s]['auc'].iloc[0]) else f"{g[s]['auc'].iloc[0]:.3f}"
                tp = lambda s: '–' if not len(g[s]) else ((f(g[s]['top10_up'].iloc[0]) if g[s]['top10_days'].iloc[0] >= 10 else '–') + f" ({int(g[s]['top10_days'].iloc[0])}일)")
                bs = next((f(g[s]['base_up'].iloc[0]) for s in SETS if len(g[s])), '–')
                S.append(f'| {h}일 | {MODEL_NAME[m]} | {bs} | {au("all")} | {au("allev")} | {tp("all")} | {tp("allev")} |')
        S.append('')
    if len(SEL):
        S += ['**합의: 해마다 고른 조건 수(평균)와 신호 날 수(합계)**', '', '| 보유일 | 고르는 꼴 | 고른 조건(해 평균) | 그중 사건 지표(해 평균) | 20% 이상 켜진 날 | 상위 5% 선 이상인 날 | 하나라도 켜진 날 |', '|---|---|---|---|---|---|---|']
        for (h, s), x in SEL.groupby(['h', 'sel']):
            S.append(f"| {h}일 | {SEL_NAME[s]} | {x['n_sel'].mean():.0f} | {x.get('n_event_sel', pd.Series([0])).fillna(0).mean():.1f} | {int(x['days_f20'].sum())} | {int(x['days_p95'].sum())} | {int(x['days_any'].sum())} |")
        S.append('')
    summary = '\n'.join(S) + '\n'
    tables = {'calibration.csv': CAL, 'events_gain.csv': GAIN, 'consensus_select.csv': SEL}
    _OUT.clear(); _OUT.update(tables=tables, summary=summary)
    if quick: notes.append('시험 실행(--quick): 가족·자료 일부만 돌린 결과다.')
    notes.append('확률 구간별 실제 적중·사건 지표 보탬·합의 고르기 표는 아래 5절(summary.md)과 out/tables 에 있다.')
    notes.append('사건 지표는 SPEC 1절의 25개(과제 안내의 약 40개를 정확히 센 수).')
    meta = dict(n_tested=int(sum(fam.values())), families=fam, m_fixed=1, m_wf=int(n_model + n_cons + n_any), not_included=NOT_INCLUDED,
                parts_failed=failed, notes=notes, tables=([] if vol else list(tables)), vol=bool(vol), quick=bool(quick),
                secs={f"{p['h']}_{p['set']}": p['secs'] for p in mods} | ({'cons': cons['secs']} if cons else {}))
    if vol: meta['summary_md'] = summary
    return cands, meta


def main():
    a = C.parse_part()
    if a['nparts']: print(n_parts()); return
    if a['part']:
        i, n = a['part']; t0 = time.time(); C.save_part(TRACK, i, n, run_part(i, n, quick=a['quick']))
        print(f'[t3] 조각 {i}/{n} 끝 {time.time() - t0:.0f}초', flush=True); return
    if a['merge']:
        n = n_parts(); cands, meta = merge(C.load_parts(TRACK, n), quick=a['quick'])
        d = os.path.join(C.track_dir(TRACK), 'out'); os.makedirs(os.path.join(d, 'tables'), exist_ok=True)
        for name, df in _OUT['tables'].items(): df.to_csv(os.path.join(d, 'tables', name), index=False, encoding='utf-8-sig')
        open(os.path.join(d, 'summary.md'), 'w', encoding='utf-8').write(_OUT['summary'])
        C.save_result(TRACK, cands, meta)
        print(f"[t3] 합침: 후보 {len(cands)}개 · 시험 {meta['n_tested']:,}가지 · wf 절차 {meta['m_wf']} · 실패 조각 {meta['parts_failed']}", flush=True)


if __name__ == '__main__':
    main()
