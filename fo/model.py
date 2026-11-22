# -*- coding: utf-8 -*-
"""방향 확률 모형 — 다음 1·5·20거래일 뒤 종가가 기준일 종가보다 높을 확률.

검증 방법(결과를 보기 전에 정해 둔 규칙, 실행할 때마다 같은 입력이면 같은 결과)
  · 시간 순서로 앞 60% 학습 / 다음 20% 검증(모형 고르기) / 마지막 20% 보류(고른 뒤 확인)
  · 걷기 전진: 예측하는 날의 모형은 라벨이 그 전에 확정된 날만으로 맞춘다(퍼지 = 라벨 기간). 21거래일마다(부스팅은 63거래일마다) 다시 맞춤
  · 기준선 = 그때까지의 상승 비율. 개선(%) = 기준선 대비 브라이어 점수가 줄어든 비율
  · 통과 = 검증·보류 구간 모두 기준선보다 낫고, 보류 구간 개선이 블록 부트스트랩으로 유의(p<0.10)하며, 적중률이 '늘 상승'보다 낮지 않을 때
  · 통과하지 못하면 모형 값 대신 기준선(표본 전체 상승 비율)을 쓴다 — '예측력 없음'을 그대로 적는다
  · 지표 하나씩 시험한 p값은 Benjamini–Hochberg(q<0.10)로 보정
"""
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression

SEED = 20261122
HORIZONS = (1, 5, 20)
PRIOR = 20.0
NB = 2000


# ------------------------------------------------------------------ 모형
class Base:
    name = '기준선'
    def fit(self, X, y): self.p = float(np.mean(y)) if len(y) else 0.5; return self
    def predict(self, X): return np.full(len(X), self.p)


class Tercile:
    """지표 하나를 학습 구간 3분위로 나눠 구간별 상승 비율(기준선 쪽으로 조금 당김)."""
    def __init__(self, col): self.col = col; self.name = f'조건부 빈도({col})'
    def fit(self, X, y):
        x = X[self.col].to_numpy(float); ok = ~np.isnan(x); self.p0 = float(np.mean(y))
        if ok.sum() < 60: self.cut = None; return self
        self.cut = np.quantile(x[ok], [1 / 3, 2 / 3]); b = np.digitize(x[ok], self.cut); yy = y[ok]
        self.r = np.array([(yy[b == k].sum() + PRIOR * self.p0) / ((b == k).sum() + PRIOR) for k in range(3)])
        return self
    def predict(self, X):
        x = X[self.col].to_numpy(float); out = np.full(len(x), self.p0)
        if self.cut is None: return out
        ok = ~np.isnan(x); out[ok] = self.r[np.digitize(x[ok], self.cut)]; return out


class Cond3:
    """상위 지표 3개가 각각 학습 구간 중앙값 위·아래인지로 8칸을 나눠 칸별 상승 비율."""
    name = '조건부 빈도(지표 3개)'
    def __init__(self, cols): self.cols = list(cols)
    def _cell(self, X):
        v = X[self.cols].to_numpy(float); v = np.where(np.isnan(v), self.med, v)
        return ((v > self.med) * np.array([1, 2, 4][:len(self.cols)])).sum(1)
    def fit(self, X, y):
        self.med = np.nanmedian(X[self.cols].to_numpy(float), axis=0); self.p0 = float(np.mean(y)); c = self._cell(X)
        self.r = np.array([(y[c == k].sum() + PRIOR * self.p0) / ((c == k).sum() + PRIOR) for k in range(8)]); return self
    def predict(self, X): return self.r[self._cell(X)]


class Logit:
    name = '로지스틱 회귀'
    def fit(self, X, y):
        v = X.to_numpy(float); self.med = np.nanmedian(v, axis=0); self.med = np.where(np.isnan(self.med), 0, self.med)
        v = np.where(np.isnan(v), self.med, v); self.mu = v.mean(0); self.sd = v.std(0); self.sd[self.sd == 0] = 1
        self.m = LogisticRegression(C=0.3, max_iter=500).fit(np.clip((v - self.mu) / self.sd, -4, 4), y); return self
    def predict(self, X):
        v = X.to_numpy(float); v = np.where(np.isnan(v), self.med, v)
        return self.m.predict_proba(np.clip((v - self.mu) / self.sd, -4, 4))[:, 1]


class Boost:
    name = '그래디언트 부스팅'
    def fit(self, X, y):
        self.m = HistGradientBoostingClassifier(max_depth=3, max_iter=120, learning_rate=0.04, l2_regularization=2.0, min_samples_leaf=40, random_state=SEED).fit(X.to_numpy(float), y); return self
    def predict(self, X): return np.clip(self.m.predict_proba(X.to_numpy(float))[:, 1], 0.05, 0.95)


def walk(X, y, h, start, make, step):
    """start 번째 날부터 끝까지 걷기 전진 예측. 학습에는 라벨이 확정된 날(j + h <= i)만 쓴다."""
    n = len(X); out = np.full(n, np.nan)
    for i in range(start, n, step):
        tr = np.arange(0, max(0, i - h + 1)); tr = tr[~np.isnan(y[tr])]
        if len(tr) < 250: continue
        out[i:i + step] = make().fit(X.iloc[tr], y[tr]).predict(X.iloc[i:i + step])
    return out


# ------------------------------------------------------------------ 점수
def boot(d_base, d_model, h, rng):
    """원형 블록 부트스트랩: 기준선 대비 브라이어 개선의 p값과 90% 구간."""
    n = len(d_base)
    if n < 30: return np.nan, np.nan, np.nan
    L = max(5, 2 * h); k = int(np.ceil(n / L))
    st = rng.integers(0, n, size=(NB, k)); idx = (st[:, :, None] + np.arange(L)[None, None, :]) % n
    idx = idx.reshape(NB, -1)[:, :n]
    sb = d_base[idx].sum(1); sm = d_model[idx].sum(1); bss = 100 * (1 - sm / sb)
    return float(np.mean(bss <= 0)), float(np.percentile(bss, 5)), float(np.percentile(bss, 95))


def score(p, p0, y, sl, h, rng):
    i = np.arange(sl.start, sl.stop); i = i[~np.isnan(p[i]) & ~np.isnan(p0[i]) & ~np.isnan(y[i])]
    if len(i) < 30: return dict(n=len(i))
    db = (p0[i] - y[i]) ** 2; dm = (p[i] - y[i]) ** 2; pv, lo, hi = boot(db, dm, h, rng)
    return dict(n=int(len(i)), brier=float(dm.mean()), brier_base=float(db.mean()), bss=float(100 * (1 - dm.sum() / db.sum())), p=pv, lo=lo, hi=hi,
                acc=float(100 * np.mean((p[i] > 0.5) == (y[i] > 0.5))), acc_base=float(100 * max(y[i].mean(), 1 - y[i].mean())), up=float(100 * y[i].mean()))


def wilson(k, n):
    if n == 0: return np.nan, np.nan
    z = 1.96; ph = k / n; den = 1 + z * z / n; c = (ph + z * z / (2 * n)) / den; w = z * np.sqrt(ph * (1 - ph) / n + z * z / (4 * n * n)) / den
    return 100 * (c - w), 100 * (c + w)


def bh(p):
    p = np.asarray(p, float); ok = ~np.isnan(p); q = np.full(len(p), np.nan); pv = p[ok]; o = np.argsort(pv); m = len(pv)
    if m == 0: return q
    adj = pv[o] * m / (np.arange(m) + 1); adj = np.minimum.accumulate(adj[::-1])[::-1]; r = np.empty(m); r[o] = np.minimum(adj, 1); q[ok] = r
    return q


# ------------------------------------------------------------------ 한 지수
def run_target(tkey, tname, X, close, names, asof):
    """X: 지표(행 = 거래일, 마지막 행 = 지금), close: 그 지수 종가. 표 조각들을 돌려준다."""
    rng = np.random.default_rng(SEED)
    X = X.reset_index(drop=True); c = np.asarray(close, float); n = len(X); cols = list(X.columns)
    out = dict(prob=[], basis=[], valid=[], calib=[], uni=[])
    for h in HORIZONS:
        y = np.full(n, np.nan); y[:n - h] = (c[h:] > c[:n - h]).astype(float); y[:n - h][np.isnan(c[h:]) | np.isnan(c[:n - h])] = np.nan
        nl = n - h; a, b = int(nl * 0.6), int(nl * 0.8); tr, va, ho = slice(0, a), slice(a, b), slice(b, nl)
        p0 = walk(X, y, h, a, Base, 21)
        # 지표 하나씩(검증 구간)
        uni = []
        ytr = y[:a]; oktr = ~np.isnan(ytr)
        for col in cols:
            p = walk(X, y, h, a, lambda col=col: Tercile(col), 21); s = score(p, p0, y, va, h, rng)
            x = X[col].to_numpy(float)[:a]; ok = oktr & ~np.isnan(x)
            if ok.sum() > 90:
                q = np.quantile(x[ok], [1 / 3, 2 / 3]); lo_ = 100 * ytr[ok][x[ok] <= q[0]].mean(); hi_ = 100 * ytr[ok][x[ok] > q[1]].mean()
                t = Tercile(col).fit(X.iloc[:a][ok], ytr[ok]); gain = float(np.mean((ytr[ok].mean() - ytr[ok]) ** 2) - np.mean((t.predict(X.iloc[:a][ok]) - ytr[ok]) ** 2))
            else: lo_ = hi_ = np.nan; gain = -1
            uni.append(dict(key=f'{tkey}_{h}_{col}', tkey=tkey, tname=tname, h=h, col=col, name=names.get(col, col), bss_val=s.get('bss'), p_val=s.get('p'), up_low=lo_, up_high=hi_, gain=gain))
        top3 = [u['col'] for u in sorted(uni, key=lambda u: -u['gain'])[:3]]
        makers = {'조건부 빈도(지표 3개)': (lambda: Cond3(top3), 21), '로지스틱 회귀': (Logit, 21), '그래디언트 부스팅': (Boost, 63)}
        res = {}
        for nm, (mk, step) in makers.items():
            p = walk(X, y, h, a, mk, step); res[nm] = (p, score(p, p0, y, va, h, rng), score(p, p0, y, ho, h, rng))
        simple = max(('조건부 빈도(지표 3개)', '로지스틱 회귀'), key=lambda k: res[k][1].get('bss', -1e9))
        chosen = '그래디언트 부스팅' if res['그래디언트 부스팅'][1].get('bss', -1e9) > max(res[k][1].get('bss', -1e9) for k in ('조건부 빈도(지표 3개)', '로지스틱 회귀')) else simple

        def verdict(v, s):
            if not s.get('n', 0) >= 30 or 'bss' not in s or 'bss' not in v: return '판정 불가(표본 부족)', False
            if v['bss'] > 0 and s['bss'] > 0 and s['p'] < 0.10 and s['acc'] >= s['acc_base'] - 1e-9: return '통과', True
            if s['bss'] <= 0 or v['bss'] <= 0: return '통과 못 함(예측력 없음)', False
            return '통과 못 함(약함)', False
        for nm, (p, v, s) in res.items():
            vd, _ = verdict(v, s)
            out['valid'].append(dict(key=f'{tkey}_{h}_{nm}', tkey=tkey, tname=tname, h=h, model=nm, chosen_txt='선택' if nm == chosen else '', bss_val=v.get('bss'), n_hold=s.get('n'),
                                     acc_hold=s.get('acc'), acc_base=s.get('acc_base'), acc_random=50, brier_hold=s.get('brier'), brier_base=s.get('brier_base'), bss_hold=s.get('bss'),
                                     bss_lo=s.get('lo'), bss_hi=s.get('hi'), p_hold=s.get('p'), verdict=vd))
        p, v, s = res[chosen]; vd, passed = verdict(v, s)
        # 보정 곡선(보류 구간, 고른 모형)
        i = np.arange(ho.start, ho.stop); i = i[~np.isnan(p[i]) & ~np.isnan(y[i])]
        if len(i) >= 50:
            g = pd.qcut(pd.Series(p[i]).rank(method='first'), 5, labels=False).to_numpy()
            for k in range(5):
                m = g == k
                out['calib'].append(dict(tkey=f'{tkey}_{h}', bin=k, p_pred=float(100 * p[i][m].mean()), p_obs=float(100 * y[i][m].mean()), n=int(m.sum()), model=chosen))
        # 지금 값: 라벨이 확정된 모든 날로 다시 맞춤
        known = np.where(~np.isnan(y))[0]; yk = y[known]; Xk = X.iloc[known]; now = X.iloc[[n - 1]]
        mk = makers[chosen][0]; pm = float(mk().fit(Xk, yk).predict(now)[0]); base = float(yk.mean())
        L = max(20, 2 * h); nb = 200 if chosen != '그래디언트 부스팅' else 60; kblk = int(np.ceil(len(known) / L)); bm = []; bb = []
        for _ in range(nb):
            st = rng.integers(0, len(known), kblk); ii = ((st[:, None] + np.arange(L)[None, :]) % len(known)).ravel()[:len(known)]
            bb.append(yk[ii].mean())
            try: bm.append(float(mk().fit(Xk.iloc[ii], yk[ii]).predict(now)[0]))
            except Exception: pass
        m_lo, m_hi = (np.percentile(bm, [2.5, 97.5]) if len(bm) >= 20 else (np.nan, np.nan)); b_lo, b_hi = np.percentile(bb, [2.5, 97.5])
        up, lo, hi = (pm, m_lo, m_hi) if passed else (base, b_lo, b_hi)
        # 상위 지표 3개가 지금과 같은 쪽이던 과거
        med = np.nanmedian(Xk[top3].to_numpy(float), axis=0); nowv = now[top3].to_numpy(float)[0]
        if np.isnan(nowv).any(): cn = 0; cu = np.nan
        else:
            same = ((Xk[top3].to_numpy(float) > med) == (nowv > med)).all(1); cn = int(same.sum()); cu = float(100 * yk[same].mean()) if cn else np.nan
        cl, ch = wilson(int(round(cu * cn / 100)) if cn else 0, cn) if cn >= 10 else (np.nan, np.nan)
        out['prob'].append(dict(key=f'{tkey}_{h}', tkey=tkey, tname=tname, h=h, asof=asof, kind=f'모형 통과 — {chosen}' if passed else '기준선(과거 상승 비율)',
                                up=round(100 * up, 1), down=round(100 - 100 * up, 1), lo=round(100 * lo, 1), hi=round(100 * hi, 1), n=int(len(known)), verdict=vd,
                                n_hold=s.get('n'), acc_hold=s.get('acc'), acc_base=s.get('acc_base'), features=' · '.join(names.get(k, k) for k in top3), model=chosen,
                                model_ref=round(100 * pm, 1), model_lo=None if np.isnan(m_lo) else round(100 * m_lo, 1), model_hi=None if np.isnan(m_hi) else round(100 * m_hi, 1),
                                cond_n=cn, cond_up=cu if cn >= 10 else None, cond_lo=None if np.isnan(cl) else cl, cond_hi=None if np.isnan(ch) else ch, cond_txt='' if cn >= 10 else '표본 부족(10일 미만)',
                                passed=1 if passed else 0))
        for u in uni:
            if u['col'] in top3:
                x = Xk[u['col']].to_numpy(float); v0 = float(now[u['col']].iloc[0]); ok = ~np.isnan(x)
                out['basis'].append(dict(key=u['key'], tname=tname, h=h, name=u['name'], value=None if np.isnan(v0) else v0, pctile=None if np.isnan(v0) or not ok.any() else float(100 * np.mean(x[ok] <= v0)),
                                         up_low=u['up_low'], up_high=u['up_high'], bss_val=u['bss_val'], p_val=u['p_val'], ukey=u['key']))
        out['uni'] += uni
    return out


def finish(parts, extra_meta):
    """지수별 조각을 합치고 다중 비교 보정을 붙인다."""
    T = {k: [r for p in parts for r in p[k]] for k in ('prob', 'basis', 'valid', 'calib', 'uni')}
    q = bh([np.nan if u['p_val'] is None else u['p_val'] for u in T['uni']])
    for u, qq in zip(T['uni'], q): u['q_bh'] = None if np.isnan(qq) else float(qq); u['sig_txt'] = '유의' if (not np.isnan(qq) and qq < 0.10 and (u['bss_val'] or 0) > 0) else ''
    sig = {u['key']: u['sig_txt'] for u in T['uni']}
    for b in T['basis']: b['sig'] = sig.get(b.pop('ukey'), '') or '유의하지 않음'
    top = sorted([u for u in T['uni'] if u['p_val'] is not None and not np.isnan(u['p_val'])], key=lambda u: (u['p_val'], -(u['bss_val'] or 0)))[:20]
    for u in T['uni']: u.pop('gain', None); u.pop('col', None)
    meta = dict(id='meta', n_tests=len(T['uni']), n_sig=sum(1 for u in T['uni'] if u['sig_txt']), n_targets=len(T['prob']), n_chosen_pass=sum(p['passed'] for p in T['prob']),
                n_pass=sum(1 for v in T['valid'] if v['verdict'] == '통과'), seed=SEED, **extra_meta)
    return dict(prob=T['prob'], basis=T['basis'], valid=T['valid'], calib=T['calib'], uni_top=top, model_meta=[meta])
