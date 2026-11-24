#!/usr/bin/env python3
"""반대매매 당일 예정치 — 오차를 줄이는 시험(걷기 검증).

규칙
  · 행 T 입력 = T일 20시에 알 수 있는 값(features.py). 목표 = 반대매매(T).
  · 해마다(또는 달마다) 그 전 자료로만 학습 → 그 기간 예측. 2017~2018 은 범위 계산용 예열, 평가는 2019~.
  · 설정 고르기는 2019~2025 로만(고르는 점수 = 절대 오차 중앙값 + 0.5 × 80% 지점). 2026 은 확인용.
  · 난수 고정(SEED). 오차 = (예정치 ÷ 실제 − 1) × 100.
"""
import os, sys, json, time, warnings, itertools
import numpy as np, pandas as pd
from joblib import Parallel, delayed
from sklearn.ensemble import HistGradientBoostingRegressor as HGB
from sklearn.linear_model import Ridge
import features as F

warnings.filterwarnings('ignore')
SEED = 20261124; OUT = os.path.join(F.HERE, 'out'); START = 2017; EVAL0 = 2019; SEL_END = 2025; JOBS = int(os.environ.get('LIQ_JOBS', str(os.cpu_count() or 2))); FAST = os.environ.get('LIQ_FAST', '') == '1'
YCOL = {'lvl': 'y_lvl', 'ratio': 'y_ratio', 'chg': 'y_chg'}
HGB_KW = dict(max_depth=3, learning_rate=0.05, max_iter=300, min_samples_leaf=20, l2_regularization=1.0, early_stopping=False, random_state=SEED)


# ---------------------------------------------------------------- 모형
def _prep_lin(Xtr, Xte):
    med = np.nanmedian(Xtr, 0); med = np.where(np.isnan(med), 0, med); Xtr = np.where(np.isnan(Xtr), med, Xtr); Xte = np.where(np.isnan(Xte), med, Xte)
    lo, hi = np.percentile(Xtr, 0.5, 0), np.percentile(Xtr, 99.5, 0); Xtr = np.clip(Xtr, lo, hi); Xte = np.clip(Xte, lo, hi)
    mu, sd = Xtr.mean(0), Xtr.std(0); sd[sd < 1e-12] = 1; return (Xtr - mu) / sd, (Xte - mu) / sd


def fit_predict(model, Xtr, ytr, Xte, w=None):
    if model == 'ols':     # 1차 시험과 같은 방식(손대지 않은 값, 최소제곱)
        ok = ~np.isnan(Xtr).any(1); A = np.c_[np.ones(ok.sum()), Xtr[ok]]; sw = np.sqrt(w[ok]) if w is not None else np.ones(ok.sum())
        b = np.linalg.lstsq(A * sw[:, None], ytr[ok] * sw, rcond=None)[0]; return np.c_[np.ones(len(Xte)), np.nan_to_num(Xte)] @ b
    if model in ('ridge', 'rob'):
        A, B = _prep_lin(Xtr, Xte); n = len(A); cut = int(n * 0.8); w0 = np.ones(n) if w is None else np.asarray(w, float)
        def rfit(A_, y_, w_, alphas):          # 가중 릿지(절편은 벌점 없음) — 닫힌 식, 벌점 여러 개를 한 번에
            sw = w_ / w_.sum(); mx = sw @ A_; my = sw @ y_; Ac = A_ - mx; Aw = Ac * w_[:, None]; Gm = Ac.T @ Aw; rhs = Aw.T @ (y_ - my); out = []
            for al in alphas:
                bb = np.linalg.solve(Gm + al * np.eye(Gm.shape[0]), rhs); out.append((bb, my - mx @ bb))
            return out
        als = (0.1, 1, 10, 30, 100, 300, 1000); fits = rfit(A[:cut], ytr[:cut], w0[:cut], als)      # 학습 자료의 뒤 20% 로 벌점 고르기(시간 순서 유지)
        errs = [np.median(np.abs(A[cut:] @ bb + b0 - ytr[cut:])) for bb, b0 in fits]; ba = als[int(np.argmin(errs))]
        bb, b0 = rfit(A, ytr, w0, (ba,))[0]
        if model == 'rob':                     # 튀는 날의 영향을 줄이는 반복 가중(Huber 방식, 3회)
            for _ in range(3):
                r = ytr - (A @ bb + b0); sc = 1.4826 * np.median(np.abs(r - np.median(r))) + 1e-9; ww = w0 * np.minimum(1.0, 1.345 * sc / (np.abs(r) + 1e-12)); bb, b0 = rfit(A, ytr, ww, (ba,))[0]
        return B @ bb + b0
    if model.startswith('hgb'):
        kw = dict(HGB_KW)
        if model == 'hgb_sq': kw['loss'] = 'squared_error'
        elif model == 'hgb_abs': kw['loss'] = 'absolute_error'
        elif model.startswith('hgb_q'): kw['loss'] = 'quantile'; kw['quantile'] = float(model[5:]) / 100
        elif model == 'hgb_deep': kw.update(loss='absolute_error', max_depth=5, max_iter=400, learning_rate=0.03)
        elif model == 'hgb_small': kw.update(loss='absolute_error', max_depth=2, max_iter=200)
        return HGB(**kw).fit(Xtr, ytr, sample_weight=w).predict(Xte)
    raise ValueError(model)


def walk(df, feats, target, model, refit='Y', tau=None, win=None, regime=None):
    """걷기 검증 예측(로그 금액). 기간 시작일 이전 날짜의 행으로만 학습한다."""
    X = df[feats].values.astype(float); y = df[YCOL[target]].values; dts = df['date'].values; yrs = df['date'].dt.year.values; mon = df['date'].dt.month.values
    pred = np.full(len(df), np.nan); okx = ~np.isnan(y) & (~np.isnan(X).all(1))
    per = [(yy, None) for yy in range(START, int(yrs.max()) + 1)] if refit == 'Y' else [(yy, mm) for yy in range(START, int(yrs.max()) + 1) for mm in range(1, 13)]
    for yy, mm in per:
        te = (yrs == yy) if mm is None else ((yrs == yy) & (mon == mm))
        if not te.any(): continue
        t0 = np.datetime64(f'{yy}-{(mm or 1):02d}-01'); tr = okx & (dts < t0)
        if win: tr &= dts >= (t0 - np.timedelta64(int(win * 365), 'D'))
        if tr.sum() < 200: continue
        w = None
        if tau: age = (t0 - dts[tr]).astype('timedelta64[D]').astype(float) / 365.0; w = np.exp(-age / tau); w = w / w.mean()
        if regime:
            col = df[regime].values; thr = np.nanmedian(col[tr]); hi_tr = col[tr] >= thr; hi_te = np.nan_to_num(col[te], nan=thr) >= thr; out = np.full(te.sum(), np.nan)
            for flag in (True, False):
                a, b = (hi_tr == flag), (hi_te == flag)
                if not b.any(): continue
                if a.sum() < 150: out[b] = fit_predict(model, X[tr], y[tr], X[te][b], w)
                else: out[b] = fit_predict(model, X[tr][a], y[tr][a], X[te][b], None if w is None else w[a])
            pred[te] = out
        else: pred[te] = fit_predict(model, X[tr], y[tr], X[te], w)
    if target == 'ratio': pred = pred + np.log(df['misu_prev'].values)
    elif target == 'chg': pred = pred + np.log(df['liq_prev'].values)
    return pred


def bias_correct(pred, y, n):
    """지난 n 일(평가일 기준, T-1 까지) 로그 오차 중앙값을 더한다 — T-1 실제값은 T일 15시에 공개되므로 20시에 알 수 있다."""
    e = pd.Series(y - pred); adj = e.shift(1).rolling(n, min_periods=5).median().fillna(0).values; return pred + adj


# ---------------------------------------------------------------- 평가
def seg_masks(df, base_pred):
    yr = df['date'].dt.year; ev = (yr >= EVAL0) & df['liq'].notna() & ~np.isnan(base_pred); thr = df.loc[ev, 'liq'].quantile(0.9)
    return {'all': ev.values, 'sel': (ev & (yr <= SEL_END)).values, 'y2026': (ev & (yr == 2026)).values, 'top10': (ev & (df['liq'] >= thr)).values}, thr


def met(pred, liq, m):
    e = (np.exp(pred[m]) / liq[m] - 1) * 100; e = e[~np.isnan(e)]; a = np.abs(e)
    if not len(e): return dict(n=0)
    return dict(n=len(e), med=np.median(a), p80=np.quantile(a, .8), p90=np.quantile(a, .9), q05=np.quantile(e, .05), q50=np.median(e), q95=np.quantile(e, .95))


def row(name, pred, df, masks, extra=None):
    liq = df['liq'].values; r = {'name': name}; r.update(extra or {})
    for s, m in masks.items():
        for k, v in met(pred, liq, m).items(): r[f'{s}_{k}'] = v
    r['score'] = r['sel_med'] + 0.5 * r['sel_p80']; return r


def run_cfg(df, G, cfg):
    feats = featset(G, cfg['fs']); p = walk(df, feats, cfg['target'], cfg['model'], cfg.get('refit', 'Y'), cfg.get('tau'), cfg.get('win'), cfg.get('regime')); return cfg, p


FS = {'F0': ['base_kofia', 'base_mkt'], 'F1': ['base_kofia', 'base_mkt', 'kofia_x', 'credit', 'cal']}
FS['F2'] = FS['F1'] + ['struct', 'flow']; FS['F3'] = FS['F2'] + ['vkospi']; FS['F3L'] = FS['F2'] + ['vkospi_lag']; FS['F4'] = FS['F3'] + ['kosdaq']
FS['F5'] = FS['F4'] + ['breadth']; FS['F6'] = FS['F5'] + ['cohort']; FS['F7'] = FS['F6'] + ['cohort_vw']
FS_DESC = {'F0': '1차와 같은 입력', 'F1': '+금투협 추가(비중·최근 수준·초과 미수·신용·예탁금)·요일', 'F2': '+미수 구조(매수일 T-3 이후 누적 손실·시가 갭)·개인 순매수·거래대금', 'F3': '+VKOSPI(당일 포함)', 'F3L': 'F2+VKOSPI(전날까지만)', 'F4': '+코스닥 지수', 'F5': '+급락·하한가 종목 수(현재 상장 종목)', 'F6': '+매수일 묶음 손실(종목 수 기준)', 'F7': '+매수일 묶음 손실(거래대금 가중)'}


def featset(G, fs):
    groups = FS[fs] if isinstance(fs, str) else fs; out = []
    for g in groups:
        for c in G.get(g, []):
            if c not in out: out.append(c)
    return out


def cname(c):
    s = f"{c['fs'] if isinstance(c['fs'], str) else '+'.join(c['fs'])}|{c['model']}|{c['target']}|{c.get('refit', 'Y')}"
    if c.get('tau'): s += f"|tau{c['tau']}"
    if c.get('win'): s += f"|win{c['win']}"
    if c.get('regime'): s += f"|reg:{c['regime']}"
    return s


def batch(df, G, cfgs):
    return Parallel(n_jobs=JOBS)(delayed(run_cfg)(df, G, c) for c in cfgs)


# ---------------------------------------------------------------- 범위
def intervals(df, pred, qpred, masks):
    """qpred: {5,10,90,95: 로그 금액 분위 예측}. 돌려주는 것: {방법: {80: (lo, hi), 90: (lo, hi)}} — 모두 T-1 까지의 오차만 사용."""
    y = df['y_lvl'].values; e = pd.Series(y - pred); res = {}
    def roll_q(s, q, n=None):
        s1 = s.shift(1); return (s1.expanding(min_periods=100).quantile(q) if n is None else s1.rolling(n, min_periods=100).quantile(q)).values
    for nm, n in (('지난 오차 전체', None), ('지난 오차 250일', 250), ('지난 오차 120일', 120)):
        res[nm] = {80: (pred + roll_q(e, .10, n), pred + roll_q(e, .90, n)), 90: (pred + roll_q(e, .05, n), pred + roll_q(e, .95, n))}
    sc = e.abs().shift(1).ewm(halflife=10, min_periods=20).mean(); z = e / sc     # 최근 오차 크기에 맞춰 넓히고 좁힘
    res['최근 오차 크기 반영'] = {80: (pred + sc.values * roll_q(z, .10, 500), pred + sc.values * roll_q(z, .90, 500)), 90: (pred + sc.values * roll_q(z, .05, 500), pred + sc.values * roll_q(z, .95, 500))}
    if qpred:
        res['분위 부스팅'] = {80: (qpred[10], qpred[90]), 90: (qpred[5], qpred[95])}
        for lv, (a, b) in ((80, (10, 90)), (90, (5, 95))):
            s = pd.Series(np.maximum(qpred[a] - y, y - qpred[b])); c = s.shift(1).rolling(250, min_periods=100).quantile(lv / 100).values
            res.setdefault('분위 부스팅+보정(250일)', {})[lv] = (qpred[a] - c, qpred[b] + c)
    return res


def ival_rows(df, res, masks):
    y = df['y_lvl'].values; rows = []
    for nm, d in res.items():
        r = {'method': nm}
        for lv, (lo, hi) in d.items():
            al = 1 - lv / 100
            for s, m in masks.items():
                ok = m & ~np.isnan(lo) & ~np.isnan(hi) & ~np.isnan(y)
                if not ok.any(): continue
                inside = (y[ok] >= lo[ok]) & (y[ok] <= hi[ok]); r[f'{s}_cov{lv}'] = inside.mean() * 100; r[f'{s}_below{lv}'] = (y[ok] < lo[ok]).mean() * 100; r[f'{s}_above{lv}'] = (y[ok] > hi[ok]).mean() * 100
                r[f'{s}_width{lv}'] = np.median(np.exp(hi[ok] - lo[ok])); r[f'{s}_n'] = int(ok.sum())
                r[f'{s}_wink{lv}'] = np.mean((hi[ok] - lo[ok]) + 2 / al * np.maximum(lo[ok] - y[ok], 0) + 2 / al * np.maximum(y[ok] - hi[ok], 0))
        rows.append(r)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- 실행
def baseline_v1(R):
    """1차 시험 그대로: 금투협과 코스피 날짜가 겹치는 날만 남겨 한 줄씩 밀어 만든 입력 + 최소제곱(해마다 그 전 자료로 학습)."""
    l = R['kofia'][['date', 'liq_eok', 'misu_eok']]; m = R['mkt'][['date', 'close']].copy(); m['chg'] = (m['close'] / m['close'].shift(1) - 1) * 100
    d = l.merge(m[['date', 'chg']], on='date', how='inner').reset_index(drop=True); d['y'] = np.log(d['liq_eok'])
    X = pd.DataFrame({'l1': d['y'].shift(1), 'l2': d['y'].shift(2), 'm1': np.log(d['misu_eok'].shift(1)), 'dm': np.log(d['misu_eok'].shift(1) / d['misu_eok'].shift(2))})
    for k in range(4): X[f'r{k}'] = d['chg'].shift(k); X[f'n{k}'] = d['chg'].shift(k).clip(upper=0)
    ok = X.notna().all(axis=1) & d['y'].notna(); pred = pd.Series(np.nan, index=d.index); yr = d['date'].dt.year
    for yv in range(EVAL0, int(yr.max()) + 1):
        tr = ok & (yr < yv); te = X.notna().all(axis=1) & (yr == yv); A = np.c_[np.ones(tr.sum()), X[tr].values]; b = np.linalg.lstsq(A, d['y'][tr].values, rcond=None)[0]; pred[te] = np.c_[np.ones(te.sum()), X[te].values] @ b
    return d[['date']].assign(p=pred.values)


def main():
    t00 = time.time(); os.makedirs(OUT, exist_ok=True); R = F.load_raw(); df, G = F.build(R); liq = df['liq'].values; y = df['y_lvl'].values; log = []
    def say(*a):
        s = ' '.join(str(x) for x in a); print(s, flush=True); log.append(s)
    have = {g: (g in G and len(G[g]) > 0) for g in ('kosdaq', 'breadth', 'cohort', 'cohort_vw')}; say('자료:', have, '행', len(df), '마지막', df['date'].max().date(), '병렬', JOBS)
    FS['C1'] = ['core']; FS['C2'] = ['core', 'core_x']; FS['C3'] = ['core', 'core_x', 'core_q']; FS['C4'] = ['core', 'core_x', 'core_q', 'core_s']; FS['C5'] = ['core', 'core_x', 'core_q', 'core_s', 'core_v']
    FS_DESC.update({'C1': '간추린 입력 14개(금투협+코스피 구조)', 'C2': 'C1+개인 순매수·VKOSPI 변화 등 12개', 'C3': 'C2+코스닥 지수 6개', 'C4': 'C3+종목 집계(종목 수 기준) 10개', 'C5': 'C4+종목 집계(거래대금 가중) 4개'})
    big = ['F0', 'F1', 'F2', 'F3', 'F3L'] + (['F4'] if have['kosdaq'] else []) + (['F5', 'F6', 'F7'] if have['breadth'] and have['kosdaq'] else [])
    small = ['C1', 'C2'] + (['C3'] if have['kosdaq'] else []) + (['C4', 'C5'] if have['breadth'] and have['kosdaq'] else []); fs_list = big + small
    if FAST: big = ['F0', 'F1', 'F2', 'F6']; fs_list = ['F0', 'F2', 'F6', 'C2', 'C4']
    clean_fs = {'F0', 'F1', 'F2', 'F3', 'F3L', 'F4', 'C1', 'C2', 'C3'}       # 종목 자료(현재 상장 종목만 — 생존 편향)를 쓰지 않는 입력 묶음
    b1 = df[['date']].merge(baseline_v1(R), on='date', how='left')['p'].values; masks, thr = seg_masks(df, b1); naive = np.log(df['liq_prev'].values); base = b1
    rows = [row('기준(1차)', base, df, masks, {'stage': 0, 'fs': 'F0'}), row('어제 값 그대로', naive, df, masks, {'stage': 0, 'fs': '-'})]
    say('기준 재현', {k: round(v, 1) for k, v in rows[0].items() if k in ('all_n', 'all_med', 'all_p80', 'all_p90', 'y2026_n', 'y2026_med', 'y2026_p80', 'y2026_p90', 'top10_med', 'top10_q05')}); P = {}
    def add(cfgs, stage):
        for c, p in batch(df, G, cfgs): P[cname(c)] = (c, p); rows.append(row(cname(c), p, df, masks, {'stage': stage, 'fs': c['fs']}))
        say(f'{stage}단계 {len(cfgs)}개 끝 {time.time() - t00:.0f}초')
    # ---- 1단계(1차와 같은 방식: 해마다 학습, 가중 없음): 입력 묶음 × 모형 × 목표
    cfgs = [dict(fs=f, model='ols', target='lvl') for f in fs_list] + [dict(fs=f, model=m, target=t) for f in fs_list for m in ('ridge', 'rob') for t in ('lvl', 'ratio', 'chg')]
    hm = ['hgb_abs'] if FAST else ['hgb_sq', 'hgb_abs', 'hgb_small']; cfgs += [dict(fs=f, model=m, target=t) for f in (big[2:] if FAST else fs_list) for m in hm for t in (('chg',) if FAST else ('ratio', 'chg'))]
    if not FAST: cfgs += [dict(fs=f, model='hgb_deep', target='chg') for f in big[2:]] + [dict(fs=f, model='hgb_abs', target='lvl') for f in big[2:]]
    add(cfgs, 1)
    def top(k, stage_max=9, clean=None, tree=None, stages=None):
        r = [x for x in rows if x['name'] in P and 'parts' not in P[x['name']][0] and 'bc' not in P[x['name']][0] and x.get('stage', 0) <= stage_max and (stages is None or x['stage'] in stages)]
        if clean is not None: r = [x for x in r if (str(x['fs']) in clean_fs) == clean]
        if tree is not None: r = [x for x in r if ('hgb' in P[x['name']][0]['model']) == tree]
        out = []
        for x in sorted(r, key=lambda x: x['score']):          # 예측이 사실상 같은 설정은 한 번만(섞을 때 같은 것이 여러 번 들어가지 않게)
            p = P[x['name']][1]; ok = masks['sel']
            if any(np.allclose(p[ok], P[cname(c)][1][ok], rtol=0, atol=1e-6) for c in out): continue
            out.append(P[x['name']][0])
            if len(out) >= k: break
        return out
    # ---- 2단계: 최근 자료 가중(tau=반감 기준 햇수)·학습 창(win=햇수)·달마다 다시 학습
    var = [dict(refit='Y', tau=1), dict(refit='Y', tau=2), dict(refit='Y', win=3), dict(refit='M'), dict(refit='M', tau=0.5), dict(refit='M', tau=1), dict(refit='M', tau=2), dict(refit='M', tau=4), dict(refit='M', win=1), dict(refit='M', win=2), dict(refit='M', win=3), dict(refit='M', win=5)]
    cfgs = [dict(fs=f, model=m, target=t, **v) for f in fs_list if f != 'F0' for m in ('ridge', 'rob') for t in ('chg',) for v in (var[4:6] + var[8:10] if FAST else var)]; add(cfgs, 2)
    tv = [dict(refit='Y', tau=1)] if FAST else [dict(refit='Y', tau=1), dict(refit='Y', tau=2), dict(refit='M'), dict(refit='M', tau=1), dict(refit='M', tau=2), dict(refit='M', win=2), dict(refit='M', win=3)]
    seen = set(); tseeds = []
    for c in top(1 if FAST else 2, 1, clean=True, tree=True) + ([] if FAST else top(2, 1, clean=False, tree=True)):
        if cname(c) not in seen: seen.add(cname(c)); tseeds.append(c)
    add([dict(s, **v) for s in tseeds for v in tv], 2)
    # ---- 3단계: 국면별 따로 학습 · 섞기(평균) · 최근 치우침 보정
    seeds = []; seen = set()
    for c in top(1, 2, clean=True, tree=False) + top(1, 2, clean=False, tree=False) + [x for x in top(1, 1, tree=True)]:
        if cname(c) not in seen: seen.add(cname(c)); seeds.append(c)
    add([dict(s, regime=g) for s in seeds for g in ('lvk1', 'mz60', 'rv20')], 3)
    def ens(nm, parts, fs_tag):
        if len(parts) < 2 or nm in P: return
        p = np.mean([P[cname(c)][1] for c in parts], 0); P[nm] = (dict(fs=fs_tag, model='ens', target='-', parts=parts), p); rows.append(row(nm, p, df, masks, {'stage': 3, 'fs': fs_tag}))
    for clean, tag, fst in ((True, '종목없이', 'F4'), (None, '전체', 'F7')):
        for k in (3, 5, 10): ens(f'섞기[{tag} 상위 {k}개 평균]', top(k, 3, clean=clean), fst)
        lin, tre = top(1, 3, clean=clean, tree=False), top(1, 3, clean=clean, tree=True)
        if lin and tre: ens(f'섞기[{tag} 선형 1위 + 부스팅 1위]', lin + tre, fst)
        lin3, tre3 = top(3, 3, clean=clean, tree=False), top(3, 3, clean=clean, tree=True); ens(f'섞기[{tag} 선형 상위 3 + 부스팅 상위 3]', lin3 + tre3, fst)
    pool = sorted([x for x in rows if x['name'] in P and 'bc' not in P[x['name']][0]], key=lambda x: x['score'])
    for x in [z for z in pool if str(z['fs']) in clean_fs][:3] + pool[:3]:
        for n in (10, 20, 60):
            nm = f"{x['name']}|치우침보정{n}"
            if nm not in P: p = bias_correct(P[x['name']][1], y, n); P[nm] = (dict(P[x['name']][0], bc=n, base=x['name']), p); rows.append(row(nm, p, df, masks, {'stage': 4, 'fs': x['fs']}))
    say(f'3단계 끝 {time.time() - t00:.0f}초')
    # ---- 고르기까지 걷기 검증(겹쳐 고르기): Y 해의 설정을 Y 이전 해(2017~Y-1)의 성적만으로 고른다 → 2019~2025 숫자가 "고른 뒤의 성적"으로 부풀지 않는다
    yrs_ = df['date'].dt.year.values; has_y = ~np.isnan(liq); pool_all = [x['name'] for x in rows if x['name'] in P and 'parts' not in P[x['name']][0] and 'bc' not in P[x['name']][0]]; nested_pick = {}
    def nested(pool, k, tag):
        out = np.full(len(df), np.nan); PP = np.array([P[n][1] for n in pool])
        for Y in range(EVAL0, int(yrs_.max()) + 1):
            prior = has_y & (yrs_ >= START) & (yrs_ < Y); E_ = np.abs(np.exp(PP[:, prior]) / liq[prior] - 1) * 100; okc = ~np.isnan(E_).any(1)
            sc = np.where(okc, np.nanmedian(E_, 1) + 0.5 * np.nanquantile(E_, 0.8, axis=1), np.inf); order = np.argsort(sc, kind='stable')[:k]; te = yrs_ == Y
            out[te] = PP[order][:, te].mean(0); nested_pick[f'{tag}_{k}_{Y}'] = [pool[i] for i in order]
        return out
    for tag, pool in (('종목없이', [n for n in pool_all if str(P[n][0]['fs']) in clean_fs or (not isinstance(P[n][0]['fs'], str))]), ('전체', pool_all)):
        pool = [n for n in pool if isinstance(P[n][0]['fs'], str)]
        if tag == '종목없이': pool = [n for n in pool if P[n][0]['fs'] in clean_fs]
        for k in (1, 5): rows.append(row(f'겹쳐 고르기[{tag} · 해마다 그 전 성적 상위 {k}개{" 평균" if k > 1 else ""}]', nested(pool, k, tag), df, masks, {'stage': 8, 'fs': 'F4' if tag == '종목없이' else 'F7'}))
    json.dump(nested_pick, open(os.path.join(OUT, 'nested_picks.json'), 'w'), ensure_ascii=False, indent=1)
    res = pd.DataFrame(rows); res['clean'] = res['fs'].astype(str).isin(clean_fs); res.sort_values('score').to_csv(os.path.join(OUT, 'results_point.csv'), index=False, float_format='%.3f')
    def is_yearly(name):          # 1차와 같은 규칙(해마다 한 번만 학습, 사후 보정 없음)만으로 된 설정인가
        c = P[name][0]; ps = c['parts'] if 'parts' in c else [c]; return 'bc' not in c and all(x.get('refit', 'Y') == 'Y' for x in ps)
    res['yearly'] = [bool(n in P and is_yearly(n)) for n in res['name']]; res.sort_values('score').to_csv(os.path.join(OUT, 'results_point.csv'), index=False, float_format='%.3f')
    cand = res[res['name'].isin(P.keys())].sort_values('score'); best_all = cand.iloc[0]; best_clean = cand[cand['clean']].iloc[0]; best_yearly = cand[cand['yearly'] & cand['clean']].iloc[0]
    say('가장 좋은 것(전체):', best_all['name'], '점수', round(best_all['score'], 2)); say('가장 좋은 것(종목 자료 없이):', best_clean['name'], '점수', round(best_clean['score'], 2))
    def parts_of(name):
        c = P[name][0]
        while 'base' in c: c = P[c['base']][0]
        return list(c['parts']) if 'parts' in c else [c]
    # ---- 입력 묶음 효과(같은 모형·같은 학습 방식으로 묶음만 바꿈)
    abl = []
    lin_best = top(1, 2, tree=False)[0]; tree_y = top(1, 1, tree=True)[0]
    for kind, c0 in (('선형·최근 가중', lin_best), ('부스팅·해마다', tree_y), ('선형·해마다', top(1, 1, tree=False)[0])):
        for f in fs_list:
            nm = cname(dict(c0, fs=f))
            if nm in P: abl.append(dict(row(nm, P[nm][1], df, masks), kind=kind, fs=f, desc=FS_DESC[f], model=c0['model'], target=c0['target'], how=cname(dict(c0, fs='*'))))
    c0 = lin_best; full_groups = FS[c0['fs']]; drops = [g for g in full_groups if g not in ('base_kofia', 'core')]
    for (c, p), dg in zip(batch(df, G, [dict(c0, fs=[g for g in full_groups if g != dg]) for dg in drops]), drops): abl.append(dict(row(f'{cname(c0)} 에서 {dg} 빼기', p, df, masks), kind='선형·최근 가중 — 빼기', fs=f'-{dg}', desc=f'{dg} 묶음 제외', model=c0['model'], target=c0['target'], how=cname(c0)))
    if 'vkospi' in full_groups or True:    # 당일 VKOSPI 를 못 쓸 때: F3 대 F3L 은 위 표에 있음
        pass
    pd.DataFrame(abl).to_csv(os.path.join(OUT, 'ablation.csv'), index=False, float_format='%.3f')
    # ---- 범위: 고른 점 예측 + 같은 입력의 분위 부스팅
    iv_all = []; finals = {}
    for tag, b in (('전체', best_all), ('종목 자료 없이', best_clean)):
        ps = parts_of(b['name']); hg = [x for x in ps if 'hgb' in x['model']]; c = dict((hg or ps)[0])
        if not hg: c.update(refit='Y'); c.pop('win', None); c['tau'] = c.get('tau') or 2
        qp = {q: p for q, (cc, p) in zip((5, 10, 90, 95), batch(df, G, [dict(c, model=f'hgb_q{q:02d}', target='chg' if c['target'] == '-' else c['target']) for q in (5, 10, 90, 95)]))}
        pred = P[b['name']][1]; ivs = intervals(df, pred, qp, masks); t = ival_rows(df, ivs, masks); t.insert(0, 'model', tag); iv_all.append(t)
        pick = t.sort_values('sel_wink80').iloc[0]['method']; finals[tag] = dict(name=b['name'], pred=pred, iv=ivs[pick], iv_name=pick, ivs=ivs); say(f'범위({tag}): 고른 방법 = {pick}')
    ivt = pd.concat(iv_all); ivt.to_csv(os.path.join(OUT, 'results_interval.csv'), index=False, float_format='%.3f')
    # ---- 미래 자료 섞임 점검(예측 단계): 2026 년 이후 자료를 엉뚱한 값으로 바꿔도 2025 년까지의 예측이 그대로여야 한다
    df2 = df.copy(); m26 = df2['date'] >= '2026-01-01'; rng = np.random.RandomState(SEED); num = [x for x in df2.columns if x not in ('date', 'kdate')]
    df2.loc[m26, num] = df2.loc[m26, num].values * rng.uniform(0.2, 5, size=(int(m26.sum()), len(num))); poison_ok, repro_ok = True, True; allparts = {cname(c): c for nm in (best_all['name'], best_clean['name']) for c in parts_of(nm)}
    for nm, c in allparts.items():
        kw = dict(refit=c.get('refit', 'Y'), tau=c.get('tau'), win=c.get('win'), regime=c.get('regime')); p1 = walk(df, featset(G, c['fs']), c['target'], c['model'], **kw); p2 = walk(df2, featset(G, c['fs']), c['target'], c['model'], **kw)
        pre = (df['date'] < '2026-01-01').values & ~np.isnan(p1); poison_ok &= bool(np.allclose(p1[pre], p2[pre], rtol=1e-9, atol=1e-9)); ok = ~np.isnan(p1); repro_ok &= bool(np.allclose(p1[ok], P[nm][1][ok], rtol=1e-9, atol=1e-9))
    say(f'예측 단계 점검({len(allparts)}개 모형) — 2026 이후 오염에도 2025 까지 예측 동일:', poison_ok, '· 다시 돌려 같은 값:', repro_ok)
    # ---- 참고(실전 불가): 당일 미수금 변화(T+1 공개)를 알았다면 — 무엇이 예측 불가능한지 보기 위한 상한
    c = dict(lin_best); d3 = df.merge(R['kofia'][['date', 'misu_eok']].rename(columns={'misu_eok': 'misu_T'}), on='date', how='left'); d3['zz_dm0'] = np.log(d3['misu_T'] / d3['misu_prev']); G3 = dict(G); G3['oracle'] = ['zz_dm0']
    kw = dict(refit=c.get('refit', 'Y'), tau=c.get('tau'), win=c.get('win')); orc = walk(d3, featset(G3, FS[c['fs']] + ['oracle']), c['target'], c['model'], **kw)
    orow = row(f'참고(실전 불가): 당일 미수금 변화를 안다면 [{cname(c)}+당일 미수금]', orc, df, masks, {'stage': 9, 'fs': 'oracle'}); orow0 = row(cname(c), P[cname(c)][1], df, masks)
    # ---- 저장
    fa, fc = finals['전체'], finals['종목 자료 없이']; o = df[['date', 'liq', 'misu_prev', 'liq_prev']].copy(); o['base_pred'] = np.exp(base)
    for tag, f in (('best', fa), ('clean', fc)):
        o[f'{tag}_pred'] = np.exp(f['pred']); o[f'{tag}_lo80'], o[f'{tag}_hi80'] = np.exp(f['iv'][80][0]), np.exp(f['iv'][80][1]); o[f'{tag}_lo90'], o[f'{tag}_hi90'] = np.exp(f['iv'][90][0]), np.exp(f['iv'][90][1])
    o[o['date'] >= f'{EVAL0}-01-01'].to_csv(os.path.join(OUT, 'preds.csv'), index=False, float_format='%.2f')
    yr = df['date'].dt.year; py = []
    for yv in range(EVAL0, int(yr.max()) + 1):
        m = masks['all'] & (yr == yv).values; r = {'year': yv, 'n': int(m.sum())}
        for tag, p in (('기준', base), ('어제값', naive), ('전체', fa['pred']), ('종목없이', fc['pred'])):
            mm = met(p, liq, m); r[f'{tag}_med'] = mm['med']; r[f'{tag}_p80'] = mm['p80']
        for tag, f in (('전체', fa), ('종목없이', fc)):
            lo, hi = f['iv'][80]; ok = m & ~np.isnan(lo); r[f'{tag}_cov80'] = ((y[ok] >= lo[ok]) & (y[ok] <= hi[ok])).mean() * 100 if ok.any() else np.nan
        py.append(r)
    pd.DataFrame(py).to_csv(os.path.join(OUT, 'by_year.csv'), index=False, float_format='%.2f')
    # 급증일(실제가 전날의 2배 이상) / 나머지, 그리고 급증일에 실제값이 범위 위쪽 끝 안에 들어온 비율
    jump = masks['all'] & (df['liq'].values >= 2 * df['liq_prev'].values); calm = masks['all'] & ~jump; j26 = jump & masks['y2026']; extra = {'jump_n': int(jump.sum()), 'jump26_n': int(j26.sum())}
    for tag, p in (('base', base), ('best', fa['pred']), ('clean', fc['pred'])):
        for nm, m in (('jump', jump), ('calm', calm), ('jump26', j26), ('calm26', calm & masks['y2026'])):
            mm = met(p, liq, m); extra[f'{tag}_{nm}_med'] = mm.get('med'); extra[f'{tag}_{nm}_q50'] = mm.get('q50')
    for tag, f in (('best', fa), ('clean', fc)):
        for lv in (80, 90):
            hi = f['iv'][lv][1]
            for nm, m in (('jump', jump), ('jump26', j26), ('top10', masks['top10'])):
                ok = m & ~np.isnan(hi); extra[f'{tag}_{nm}_under_hi{lv}'] = float((y[ok] <= hi[ok]).mean() * 100) if ok.any() else None
    # 고르기의 흔들림: 2019~2025 점수 상위 10개 설정의 2026 성적 분포(한 개만 고른 값이 운인지 보기)
    t10 = cand[cand['clean']].head(10); t10a = cand.head(10); rob = {'clean_top10_2026_med': [float(t10['y2026_med'].min()), float(t10['y2026_med'].median()), float(t10['y2026_med'].max())], 'clean_top10_2026_p80': [float(t10['y2026_p80'].min()), float(t10['y2026_p80'].median()), float(t10['y2026_p80'].max())],
           'all_top10_2026_med': [float(t10a['y2026_med'].min()), float(t10a['y2026_med'].median()), float(t10a['y2026_med'].max())], 'all_top10_2026_p80': [float(t10a['y2026_p80'].min()), float(t10a['y2026_p80'].median()), float(t10a['y2026_p80'].max())]}
    last = df.iloc[-1]; live = None
    if np.isnan(last['liq']):
        live = {'date': str(last['date'].date())}
        for tag, f in (('best', fa), ('clean', fc)): live[tag] = {'pred': float(np.exp(f['pred'][-1])), 'lo80': float(np.exp(f['iv'][80][0][-1])), 'hi80': float(np.exp(f['iv'][80][1][-1])), 'lo90': float(np.exp(f['iv'][90][0][-1])), 'hi90': float(np.exp(f['iv'][90][1][-1]))}
        live['base'] = float(np.exp(base[-1])) if not np.isnan(base[-1]) else None; live['liq_prev'] = float(last['liq_prev']); live['misu_prev'] = float(last['misu_prev'])
    fj = os.path.join(F.HERE, 'data', 'fetch_status.json')
    S = {'seed': SEED, 'n_configs': int(len(res)), 'top10_threshold_eok': float(thr), 'best_all': best_all['name'], 'best_clean': best_clean['name'], 'best_yearly': best_yearly['name'], 'best_all_parts': [cname(c) for c in parts_of(best_all['name'])], 'best_clean_parts': [cname(c) for c in parts_of(best_clean['name'])],
         'iv_all': fa['iv_name'], 'iv_clean': fc['iv_name'], 'poison_ok': poison_ok, 'repro_ok': repro_ok, 'have': have, 'jump': extra, 'robust': rob, 'live': live, 'oracle_base': orow0['name'], 'seconds': round(time.time() - t00), 'fetch': json.load(open(fj)) if os.path.exists(fj) else None}
    json.dump(S, open(os.path.join(OUT, 'summary.json'), 'w'), ensure_ascii=False, indent=1, default=float)
    write_md(res, ivt, pd.DataFrame(abl), pd.DataFrame(py), S, orow, orow0); open(os.path.join(OUT, 'run_log.txt'), 'w').write('\n'.join(log) + '\n'); say(f'끝 {time.time() - t00:.0f}초')


def write_md(res, ivt, abl, py, S, orow, orow0):
    L = ['# 반대매매 당일 예정치 — 오차 줄이기 시험 결과', '', f"- 난수 고정 {S['seed']} · 시험한 설정 {S['n_configs']}개 · 설정은 2019~2025 로만 고름(점수 = 절대 오차 중앙값 + 0.5×80% 지점), 2026 은 확인용", f"- 상위 10% 날 = 2019~ 평가 구간에서 반대매매 {S['top10_threshold_eok']:.0f}억 이상", '']
    lk = os.path.join(OUT, 'leak_check.txt'); L += ['## 미래 자료 섞임 점검', '```'] + (open(lk).read().strip().split('\n') if os.path.exists(lk) else ['입력 점검 파일 없음']) + [f"(예측 단계) 2026 이후 자료를 오염시켜도 2025 까지 예측 동일: {'예' if S['poison_ok'] else '아니오 — 무효'} · 다시 돌려 같은 값: {'예' if S['repro_ok'] else '아니오'}", '```', '']
    def line(r, nm):
        f = lambda s: ' / '.join(f"{r[f'{s}_{k}']:.1f}" for k in ('med', 'p80', 'p90'))
        return f"| {nm} | {f('all')} | {f('y2026')} | {f('top10')} | {r['top10_q05']:.0f} / {r['top10_q50']:+.0f} | {f('sel')} |"
    g = lambda n: res[res['name'] == n].iloc[0]
    L += ['## 점 예측: 절대 오차 중앙값 / 80% / 90% (단위 %)', '', '| 방법 | 2019~ 전체 | 2026년 | 상위 10% 날 | 상위 10% 날 5% 지점 / 중앙(부호) | 2019~2025(고르는 구간) |', '|---|---|---|---|---|---|']
    L += [line(g('기준(1차)'), '기준(1차)'), line(g('어제 값 그대로'), '어제 값 그대로'), line(g(S['best_yearly']), '해마다 학습만(1차와 같은 규칙, 종목 자료 없이) 중 가장 좋은 것'), line(g(S['best_clean']), '가장 좋은 것(종목 자료 없이)'), line(g(S['best_all']), '가장 좋은 것(전체)'), *[line(r, r['name']) for _, r in res[res['name'].str.startswith('겹쳐 고르기')].iterrows()], line(pd.Series(orow0), f"참고: {orow0['name']}"), line(pd.Series(orow), '참고(실전 불가): 위 모형 + 당일 미수금 변화'), '']
    L += [f"- 해마다 학습만 중 가장 좋은 것: `{S['best_yearly']}`", f"- 가장 좋은 것(종목 자료 없이): `{S['best_clean']}` = {S['best_clean_parts']}", f"- 가장 좋은 것(전체): `{S['best_all']}` = {S['best_all_parts']}", '']
    rb = S['robust']; L += [f"- 고르기의 흔들림(2019~2025 점수 상위 10개 설정의 2026 성적, 최소/중앙/최대): 종목 자료 없이 — 중앙 오차 {rb['clean_top10_2026_med'][0]:.1f}/{rb['clean_top10_2026_med'][1]:.1f}/{rb['clean_top10_2026_med'][2]:.1f}, 80% 지점 {rb['clean_top10_2026_p80'][0]:.1f}/{rb['clean_top10_2026_p80'][1]:.1f}/{rb['clean_top10_2026_p80'][2]:.1f} · 전체 — 중앙 오차 {rb['all_top10_2026_med'][0]:.1f}/{rb['all_top10_2026_med'][1]:.1f}/{rb['all_top10_2026_med'][2]:.1f}, 80% 지점 {rb['all_top10_2026_p80'][0]:.1f}/{rb['all_top10_2026_p80'][1]:.1f}/{rb['all_top10_2026_p80'][2]:.1f}", '']
    L += ['## 입력 묶음을 하나씩 더했을 때(같은 모형)', '', '| 종류 | 묶음 | 내용 | 2019~2025 중앙/80% | 2026 중앙/80% | 상위10% 중앙 / 5% 지점 |', '|---|---|---|---|---|---|']
    for _, r in abl.iterrows(): L.append(f"| {r['kind']} `{r['how']}` | {r['fs']} | {r['desc']} | {r['sel_med']:.1f} / {r['sel_p80']:.1f} | {r['y2026_med']:.1f} / {r['y2026_p80']:.1f} | {r['top10_med']:.1f} / {r['top10_q05']:.0f} |")
    L += ['', '## 범위가 실제로 맞는 비율(%) — 80% 범위 / 90% 범위, 괄호는 범위 폭(위÷아래, 중앙값)', '', '| 모형 | 범위 만드는 법 | 2019~2025 | 2026년 | 상위 10% 날 | 2026년 벗어난 쪽(80%: 아래/위) |', '|---|---|---|---|---|---|']
    for _, r in ivt.iterrows():
        f = lambda s: f"{r.get(f'{s}_cov80', np.nan):.0f} / {r.get(f'{s}_cov90', np.nan):.0f} (×{r.get(f'{s}_width80', np.nan):.1f} / ×{r.get(f'{s}_width90', np.nan):.1f})"
        star = ' ◀고름' if r['method'] == (S['iv_all'] if r['model'] == '전체' else S['iv_clean']) else ''
        L.append(f"| {r['model']} | {r['method']}{star} | {f('sel')} | {f('y2026')} | {f('top10')} | {r.get('y2026_below80', np.nan):.0f} / {r.get('y2026_above80', np.nan):.0f} |")
    L += ['', '## 해마다(절대 오차 중앙값 %, 80% 범위 적중률 %)', '', '| 해 | 일수 | 기준 | 어제값 | 종목없이 | 전체 | 80% 범위 적중(종목없이/전체) |', '|---|---|---|---|---|---|---|']
    for _, r in py.iterrows(): L.append(f"| {int(r['year'])} | {int(r['n'])} | {r['기준_med']:.1f} | {r['어제값_med']:.1f} | {r['종목없이_med']:.1f} | {r['전체_med']:.1f} | {r['종목없이_cov80']:.0f} / {r['전체_cov80']:.0f} |")
    j = S['jump']; L += ['', '## 급증일(실제가 전날의 2배 이상)과 나머지', '', f"- 급증일 {j['jump_n']}일(2026년 {j['jump26_n']}일)", '', '| 구분 | 기준 중앙 오차 / 부호 중앙 | 종목없이 | 전체 |', '|---|---|---|---|']
    for nm, lab in (('jump', '급증일(2019~)'), ('calm', '나머지(2019~)'), ('jump26', '급증일(2026)'), ('calm26', '나머지(2026)')):
        L.append(f"| {lab} | " + ' | '.join(f"{j[f'{t}_{nm}_med']:.1f} / {j[f'{t}_{nm}_q50']:+.1f}" if j.get(f'{t}_{nm}_med') is not None else '-' for t in ('base', 'clean', 'best')) + ' |')
    L += ['', '급증일·상위 10% 날에 실제값이 범위 위쪽 끝 이하였던 비율(%) — 80% 범위 위 끝 / 90% 범위 위 끝', '', '| 구분 | 종목없이 | 전체 |', '|---|---|---|']
    for nm, lab in (('jump', '급증일(2019~)'), ('jump26', '급증일(2026)'), ('top10', '상위 10% 날')):
        L.append(f"| {lab} | " + ' | '.join(f"{j[f'{t}_{nm}_under_hi80']:.0f} / {j[f'{t}_{nm}_under_hi90']:.0f}" if j.get(f'{t}_{nm}_under_hi80') is not None else '-' for t in ('clean', 'best')) + ' |')
    if S.get('live'):
        v = S['live']; L += ['', f"## 예시: {v['date']} 예정치(실제값은 다음 거래일 15시쯤 공개 — 아직 모름)", '', f"- 전날 반대매매 {v['liq_prev']:.0f}억 · 전날 미수금 {v['misu_prev']:.0f}억 · 어제 값 그대로면 {v['liq_prev']:.0f}억"]
        for tag, lab in (('clean', '종목 자료 없이'), ('best', '전체')): L.append(f"- {lab}: {v[tag]['pred']:.0f}억 (80% 범위 {v[tag]['lo80']:.0f}~{v[tag]['hi80']:.0f}억, 90% 범위 {v[tag]['lo90']:.0f}~{v[tag]['hi90']:.0f}억)")
    L += ['', '## 상위 설정 15개(2019~2025 점수 순)', '', '| 설정 | 점수 | 2019~2025 중앙/80% | 2026 중앙/80%/90% | 상위10% 중앙 |', '|---|---|---|---|---|']
    for _, r in res.sort_values('score').head(15).iterrows(): L.append(f"| `{r['name']}` | {r['score']:.1f} | {r['sel_med']:.1f} / {r['sel_p80']:.1f} | {r['y2026_med']:.1f} / {r['y2026_p80']:.1f} / {r['y2026_p90']:.1f} | {r['top10_med']:.1f} |")
    L += ['', '투자 권유 아님.', '']; open(os.path.join(OUT, 'summary.md'), 'w').write('\n'.join(L))


if __name__ == '__main__':
    main()
