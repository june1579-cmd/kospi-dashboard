import pickle, numpy as np, pandas as pd, warnings
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.impute import SimpleImputer
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import roc_auc_score
warnings.filterwarnings('ignore')
f = pickle.load(open('feat.pkl','rb')); X, RK, Y = f['X'], f['RK'], f['Y']; idx = X.index; yrs = idx.year.values
CFG = [('log', dict(C=c_)) for c_ in (0.003, 0.03, 0.3)] + [('hgb', dict(max_depth=d, learning_rate=lr, max_iter=it, l2_regularization=1.0, min_samples_leaf=ms)) for d, lr, it, ms in ((2, .03, 150, 40), (3, .05, 200, 20), (2, .05, 60, 80), (4, .03, 300, 40), (1, .05, 200, 40))]
def fit(kind, kw, Xa, ya, Xb):
    if kind == 'log': m = make_pipeline(SimpleImputer(strategy='median'), StandardScaler(), LogisticRegression(max_iter=2000, **kw))
    else: m = HistGradientBoostingClassifier(random_state=0, **kw)
    keep = ~np.isnan(Xa).all(0); m.fit(Xa[:, keep], ya); return m.predict_proba(Xb[:, keep])[:, 1]
for tgt, hz in (('up10', 10), ('up20', 20), ('up5', 5)):
    r = Y[f'r{hz}'].values; y = (r > 0).astype(float); known = ~np.isnan(r)
    for src, XX in (('원값', X), ('3년 순위', RK)):
        P = np.full(len(idx), np.nan); Pc = np.full(len(idx), np.nan); picks = []
        for Yv in range(2018, 2027):
            tr = np.where((yrs >= 2007) & (yrs < Yv) & known)[0]; tr = tr[:-hz]; te = np.where(yrs == Yv)[0]
            inner_va = tr[yrs[tr] >= Yv - 3]; inner_tr = tr[yrs[tr] < Yv - 3][:-hz]
            best = None; oof = {}
            for ci, (kind, kw) in enumerate(CFG):
                p = fit(kind, kw, XX.values[inner_tr], y[inner_tr], XX.values[inner_va]); a = roc_auc_score(y[inner_va], p); oof[ci] = p
                if best is None or a > best[0]: best = (a, ci)
            ci = best[1]; kind, kw = CFG[ci]; picks.append(ci)
            P[te] = fit(kind, kw, XX.values[tr], y[tr], XX.values[te])
            iso = IsotonicRegression(out_of_bounds='clip', y_min=0.02, y_max=0.98).fit(oof[ci], y[inner_va]); Pc[te] = iso.predict(P[te])
        m = known & (yrs >= 2018) & ~np.isnan(P); base = y[m].mean(); br = lambda p: 1 - ((p[m] - y[m]) ** 2).mean() / (base * (1 - base))
        q = pd.qcut(P[m], 5, labels=False, duplicates='drop'); cal = pd.DataFrame({'p': Pc[m], 'y': y[m], 'q': q}).groupby('q').agg(p=('p', 'mean'), y=('y', 'mean'))
        print(f'{tgt} [{src}] 검증 AUC {roc_auc_score(y[m], P[m]):.3f} · 기술점수(원 확률) {br(P):+.3f} · 보정 뒤 {br(Pc):+.3f} · 5구간 실제 상승률 ' + ' '.join(f'{v * 100:.0f}' for v in cal.y) + f' · 고른 설정 {picks}')
        ya = [round(roc_auc_score(y[m & (yrs == yy)], P[m & (yrs == yy)]), 2) for yy in range(2018, 2027)]; print('    연도별 AUC', ya)
