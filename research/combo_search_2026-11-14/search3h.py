import pickle, numpy as np, pandas as pd, time, sys, warnings
warnings.filterwarnings('ignore')
HA, HB = int(sys.argv[1]), int(sys.argv[2]); OUT = sys.argv[3]; SHIFT = 0; GAPD = max(HA, HB)
f = pickle.load(open('feat.pkl','rb')); RK, Y, c = f['RK'], f['Y'], f['c']
idx = RK.index; N = len(idx); yrs = idx.year.values
HI = (0.5,0.6,0.7,0.8,0.9,0.95); LO = (0.5,0.4,0.3,0.2,0.1,0.05)
cols, names = [np.ones(N, bool)], ['(항상)']
for ft in RK.columns:
    v = RK[ft].values
    for q in HI: cols.append(np.nan_to_num(v, nan=-1) >= q); names.append(f'{ft}>=p{int(q*100)}')
    for q in LO: cols.append(np.where(np.isnan(v), 2, v) <= q); names.append(f'{ft}<=p{int(q*100)}')
C = np.stack(cols, 1); M = C.shape[1]; print('conds', M, 'triples', M*(M-1)*(M-2)//6, flush=True)
r10, r20 = ((c.shift(-HA) / c - 1) * 100).values.copy(), ((c.shift(-HB) / c - 1) * 100).values.copy()
if SHIFT: r10 = np.roll(r10, SHIFT); r20 = np.roll(r20, SHIFT)
# 유효한 날: 목표를 알고, 그 해의 마지막 20거래일이 아닌 날(학습·검증 사이 정보 누출 차단)
pos_from_end = pd.Series(np.arange(N)).groupby(yrs).transform(lambda s: s.max() - s).values
valid = ~np.isnan(r10) & ~np.isnan(r20) & (pos_from_end >= GAPD) & (yrs >= 2007)
u10, u20 = (r10 > 0) & valid, (r20 > 0) & valid
YEARS = [y for y in range(2007, 2027)]; TEST = list(range(2018, 2027))
rows = {y: np.where((yrs == y) & valid)[0] for y in YEARS}
Cf = C.astype(np.float32)
TOP = 30; TG = ['upA','dnA','upB','dnB']
tri = np.triu(np.ones((M, M), bool), 1)
res = []; best_full = []
t0 = time.time()
for k in range(M - 2):
    m = M - k - 1; ck = C[:, k]
    nC = np.zeros((m, m), np.float32); h10C = np.zeros_like(nC); h20C = np.zeros_like(nC); act = np.zeros_like(nC); g10 = np.zeros_like(nC); g20 = np.zeros_like(nC); b10 = np.zeros_like(nC); b20 = np.zeros_like(nC)
    tmask = tri[k+1:, k+1:]; pend = {}
    for y in YEARS + [None]:
        if y in TEST or y is None:
            # 학습 구간(y 이전)만으로 점수
            p10 = h10C.sum() / max(nC.sum(), 1); p20 = h20C.sum() / max(nC.sum(), 1)
            el = (nC >= 120) & (act >= 5) & tmask
            sc = {'upA': np.where(el & (g10 >= 0.7 * act), (h10C + 40 * p10) / (nC + 40), -1), 'dnA': np.where(el & (b10 >= 0.7 * act), (nC - h10C + 40 * (1 - p10)) / (nC + 40), -1),
                  'upB': np.where(el & (g20 >= 0.7 * act), (h20C + 40 * p20) / (nC + 40), -1), 'dnB': np.where(el & (b20 >= 0.7 * act), (nC - h20C + 40 * (1 - p20)) / (nC + 40), -1)}
            for tg in TG:
                s = sc[tg].ravel(); kk = min(TOP, s.size - 1); top = np.argpartition(s, -kk)[-kk:]; top = top[s[top] > 0]
                hC = h10C if tg.endswith('A') else h20C
                for t in top:
                    i, j = divmod(int(t), m); rec = [y or 0, tg, k, k + 1 + i, k + 1 + j, float(s[t]), float(nC[i, j]), float(hC[i, j]), np.nan, np.nan]
                    if y is None: best_full.append(rec)
                    else: pend.setdefault(y, []).append((i, j, tg, rec))
        if y is None: break
        R = rows[y]; sel = R[ck[R]]
        if len(sel) == 0:
            for (i, j, tg, rec) in pend.get(y, []): rec[8] = 0.0; rec[9] = 0.0; res.append(rec)
            continue
        A = Cf[sel, k+1:]; n_y = A.T @ A
        A1 = Cf[sel[u10[sel]], k+1:]; h10_y = A1.T @ A1; A2 = Cf[sel[u20[sel]], k+1:]; h20_y = A2.T @ A2
        for (i, j, tg, rec) in pend.get(y, []):
            rec[8] = float(n_y[i, j]); rec[9] = float((h10_y if tg.endswith('A') else h20_y)[i, j]); res.append(rec)
        nC += n_y; h10C += h10_y; h20C += h20_y
        a = n_y >= 5; act += a; g10 += a & (h10_y > 0.5 * n_y); b10 += a & (h10_y < 0.5 * n_y); g20 += a & (h20_y > 0.5 * n_y); b20 += a & (h20_y < 0.5 * n_y)
    if k % 25 == 0: print(k, round(time.time() - t0), 's', len(res), flush=True)
df = pd.DataFrame(res, columns=['fold','tg','a','b','c','score','n_tr','h_tr','n_te','h_te']); bf = pd.DataFrame(best_full, columns=df.columns)
df['tg'] = df.tg.map({'upA': f'up{HA}', 'dnA': f'dn{HA}', 'upB': f'up{HB}', 'dnB': f'dn{HB}'}); bf['tg'] = bf.tg.map({'upA': f'up{HA}', 'dnA': f'dn{HA}', 'upB': f'up{HB}', 'dnB': f'dn{HB}'})
pickle.dump(dict(df=df, bf=bf, names=names, C=C, valid=valid, yrs=yrs, GAPD=GAPD), open(OUT, 'wb'))
print('done', round(time.time() - t0), 's', len(df))
