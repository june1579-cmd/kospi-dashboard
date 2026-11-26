# 장중 도달 확률(코스피200 현물·근월물 선물) — 자료 만들기·걷기 전진 검증·전체 학습(2026-11-26).
# 대상: 다음 거래일 고가가 기준점 +x% 이상 / 저가가 기준점 −x% 이하가 될 확률, x = 0.1% 단위. 기준점: 전날 종가(c)·시가(o).
# 시각: pre(08:30, 야간선물·간밤 미국·변동성) · post(09:10, pre + 시가 갭). post 의 장중 앞부분 고가·저가는 live.py 에서 조건부로 반영.
# 모형: 위치(평균)와 폭을 선형으로 맞추고, 표준화 잔차의 실제 분포로 모든 칸의 확률을 한 번에 계산 → 칸이 올라갈수록 확률이 항상 줄어든다.
# 비교 대상: 지난 250일 실제 분포(기후값), 변동성만 쓴 모형. 통과 기준: 수정 기준(사용자 승인 2026-11-26) — 아래 judge().
# 원자료: deriv-research 가지 deriv/data(KRX 현물·선물·유렉스 야간·투자자별), main 의 out/night_fut.csv(KRX 야간), fo/data(미국·VIX).
import argparse, json, os, sys
import numpy as np, pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
SEED = 20261122
LEVELS = np.round(np.arange(0.1, 10.0001, 0.1), 1)       # 표시 칸(0.1%~10%)
SCORE_LV = LEVELS[LEVELS <= 5.0001]                       # 점수 계산 칸(0.1%~5%)
REP = [0.5, 1.0, 2.0, 3.0]
ZQ = np.linspace(0.0005, 0.9995, 2000)
num = lambda s: pd.to_numeric(pd.Series(s).astype(str).str.replace(',', ''), errors='coerce').to_numpy()


def overnight(kd, U, C):
    nxt = np.append(kd[1:], '9999-12-31'); lo = np.searchsorted(U, kd, 'left'); hi = np.searchsorted(U, nxt, 'left')
    out = np.full(len(kd), np.nan); ok = (hi > lo) & (lo >= 1); out[ok] = 100 * (C[hi[ok] - 1] / C[lo[ok] - 1] - 1); return out


def load(DV):
    k = pd.read_csv(os.path.join(DV, 'k200_long.csv'), encoding='utf-8-sig'); k['date'] = k['날짜'].astype(str).str[:10]
    k = k.drop_duplicates('date', keep='last').set_index('date').sort_index()
    D = pd.DataFrame({'o': num(k['시가']), 'h': num(k['고가']), 'l': num(k['저가']), 'c': num(k['종가'])}, index=k.index)
    fr = pd.read_csv(os.path.join(DV, 'fut_front_daily.csv'), encoding='utf-8-sig', dtype=str)
    fd = fr[fr['TRD_DD'].str.contains('주간')].copy(); fd['date'] = fd['TRD_DD'].str[:10].str.replace('/', '-'); fd = fd.drop_duplicates('date', keep='last').set_index('date')
    F = pd.DataFrame({'fo': num(fd['TDD_OPNPRC']), 'fh': num(fd['TDD_HGPRC']), 'fl': num(fd['TDD_LWPRC']), 'fc': num(fd['TDD_CLSPRC']), 'fchg': num(fd['CMPPREVDD_PRC']),
                      'fvol': num(fd['ACC_TRDVOL']), 'fval': num(fd['ACC_TRDVAL']), 'ym': fd['ISU_NM'].astype(str).str.extract(r'(\d{6})')[0].to_numpy()}, index=fd.index)
    F['fprev'] = F['fc'] - F['fchg']; F['vwap'] = F['fval'] / (F['fvol'] * 250000)
    ng = fr[fr['TRD_DD'].str.contains('야간')].copy(); ng['date'] = ng['TRD_DD'].str[:10].str.replace('/', '-'); ng['nc'] = num(ng['TDD_CLSPRC'])
    ng = ng.dropna(subset=['nc']).drop_duplicates('date', keep='last').set_index('date')['nc']
    D = D.join(F, how='left')
    nf_p = os.path.join(ROOT, 'out', 'night_fut.csv')
    nf = pd.read_csv(nf_p).drop_duplicates('date', keep='last').set_index('date') if os.path.exists(nf_p) else pd.DataFrame(columns=['night_close', 'night_pct'])
    D['night_krx'] = pd.to_numeric(nf['night_pct'], errors='coerce').reindex(D.index)          # 날짜 D = D 저녁에 시작한 세션
    D['night_eur'] = 100 * (ng.reindex(D.index) / D['fc'] - 1)                                   # 유렉스 시절(2009-11~2020)
    D.loc[D['night_eur'].abs() > 20, 'night_eur'] = np.nan
    D['night'] = D['night_krx'].fillna(D['night_eur'])
    # 미국 간밤·VIX
    px = pd.read_csv(os.path.join(ROOT, 'fo', 'data', 'px.csv')); pxc = px.pivot(index='date', columns='sym', values='close').sort_index()
    vp = os.path.join(ROOT, 'fo', 'data', 'vix.csv')
    if os.path.exists(vp): pxc = pxc.join(pd.read_csv(vp).set_index('date')[['vix']], how='outer')
    kd = D.index.to_numpy()
    for col, nm in (('spx', 'us_on'), ('vix', 'vix_on')):
        s = pxc[col].dropna() if col in pxc else pd.Series(dtype=float)
        D[nm] = overnight(kd, s.index.to_numpy(), s.to_numpy()) if len(s) else np.nan
    # 외국인(후보 지표): 전날 주간 순매수(평소 대비), 그 물량의 종가 기준 수익, 장 전 끝난 야간 세션 외국인 순매수(평소 대비)
    iv = pd.read_csv(os.path.join(DV, 'inv_daily.csv.gz'), dtype=str); iv = iv[(iv['상품'] == 'FUK2I') & (iv['권리'] == 'ALL')]; iv['date'] = iv['TRD_DD'].str.replace('/', '-')
    day = iv[(iv['장구분'] == '정규') & (iv['상세'] == 'Y')].drop_duplicates('date', keep='last').set_index('date')
    nig = iv[iv['장구분'] == '야간'].drop_duplicates('date', keep='last').set_index('date')      # 날짜 = 세션이 끝난 날
    fct = pd.Series(num(day['A11']), index=day.index).reindex(D.index) / (D['vwap'] * 250000)
    D['f1'] = fct / fct.abs().rolling(250, min_periods=60).mean()
    D['pnl1'] = np.sign(fct) * (D['fc'] / D['vwap'] - 1) * 100
    na = pd.Series(num(nig['A12']), index=nig.index).reindex(D.index).shift(-1)                 # 행 t = t 저녁 시작·t+1 아침 끝 세션
    D['n1'] = na / na.abs().rolling(60, min_periods=20).mean()
    # 가격 지표
    D['own'] = 100 * D['c'].pct_change(); lr = 100 * np.log(D['c'] / D['c'].shift(1)); D['rv20'] = lr.rolling(20).std()
    D['park20'] = (100 * np.log(D['h'] / D['l'])).rolling(20).mean()
    D['fpark20'] = (100 * np.log(D['fh'] / D['fl'])).rolling(20).mean()
    # 다음 날 목표
    nx = D.shift(-1)
    D['S_gap'] = 100 * (nx['o'] / D['c'] - 1)
    D['S_up_c'] = 100 * (nx['h'] / D['c'] - 1); D['S_dn_c'] = 100 * (nx['l'] / D['c'] - 1)
    D['S_up_o'] = 100 * (nx['h'] / nx['o'] - 1); D['S_dn_o'] = 100 * (nx['l'] / nx['o'] - 1)
    fp = nx['fprev']                                                                               # 같은 월물 기준 전날 종가
    D['F_gap'] = 100 * (nx['fo'] / fp - 1)
    D['F_up_c'] = 100 * (nx['fh'] / fp - 1); D['F_dn_c'] = 100 * (nx['fl'] / fp - 1)
    D['F_up_o'] = 100 * (nx['fh'] / nx['fo'] - 1); D['F_dn_o'] = 100 * (nx['fl'] / nx['fo'] - 1)
    for c_ in ('S_gap', 'S_up_c', 'S_dn_c', 'S_up_o', 'S_dn_o', 'F_gap', 'F_up_c', 'F_dn_c', 'F_up_o', 'F_dn_o'):
        D.loc[D[c_].abs() > 25, c_] = np.nan                                                         # 값이 0 등으로 잘못 들어온 날
    return D[D.index >= '2009-01-02']


PRE = ['night_f', 'us_on', 'vix_on', 'own', 'rv20', 'park20']
FOR = ['f1', 'pnl1', 'n1']


def feats(time, inst, foreign):
    mu = PRE + ([f'{inst}_gap'] if time == 'post' else []) + (FOR if foreign else [])
    sc = ['rv20', 'park20', 'abs_night'] + (['abs_gap'] if time == 'post' else [])
    return mu, sc


class Dist:
    """위치·폭 선형 + 표준화 잔차의 실제 분포. 야간선물 없는 날은 학습 구간의 간밤 미국·VIX로 메운다."""
    def __init__(self, mu_cols, sc_cols, inst='S'):
        self.mu_cols, self.sc_cols, self.inst = mu_cols, sc_cols, inst

    def _X(self, df):
        X = df.copy()
        ok = X['night'].notna()
        X['night_f'] = np.where(ok, X['night'], self.ni[0] + self.ni[1] * X['us_on'].fillna(0) + self.ni[2] * X['vix_on'].fillna(0))
        X['abs_night'] = X['night_f'].abs()
        if f'{self.inst}_gap' in X: X['abs_gap'] = X[f'{self.inst}_gap'].abs()
        M = X[self.mu_cols].to_numpy(float); S = X[self.sc_cols].to_numpy(float)
        M = np.where(np.isnan(M), self.mmed, M); S = np.where(np.isnan(S), self.smed, S)
        return np.c_[np.ones(len(X)), M], np.c_[np.ones(len(X)), S]

    def fit(self, df, y):
        o = df['night'].notna() & df['us_on'].notna()
        A = np.c_[np.ones(o.sum()), df.loc[o, 'us_on'].to_numpy(float), df.loc[o, 'vix_on'].fillna(0).to_numpy(float)]
        self.ni = np.linalg.lstsq(A, df.loc[o, 'night'].to_numpy(float), rcond=None)[0] if o.sum() > 30 else np.array([0, 1.4, 0])
        self.mmed = np.zeros(len(self.mu_cols)); self.smed = np.zeros(len(self.sc_cols))
        X = df.copy(); X['night_f'] = np.where(X['night'].notna(), X['night'], self.ni[0] + self.ni[1] * X['us_on'].fillna(0) + self.ni[2] * X['vix_on'].fillna(0))
        X['abs_night'] = X['night_f'].abs()
        if f'{self.inst}_gap' in X: X['abs_gap'] = X[f'{self.inst}_gap'].abs()
        self.mmed = np.nan_to_num(np.nanmedian(X[self.mu_cols].to_numpy(float), 0)); self.smed = np.nan_to_num(np.nanmedian(X[self.sc_cols].to_numpy(float), 0))
        Xm, Xs = self._X(df)
        self.bm = np.linalg.lstsq(Xm, y, rcond=None)[0]; res = y - Xm @ self.bm
        self.bs = np.linalg.lstsq(Xs, np.abs(res), rcond=None)[0]; s = np.maximum(Xs @ self.bs, 0.05)
        self.z = np.quantile(res / s, ZQ); return self

    def loc_scale(self, df):
        Xm, Xs = self._X(df); return Xm @ self.bm, np.maximum(Xs @ self.bs, 0.05)

    def cdf(self, t):                                   # P(z <= t)
        return np.interp(t, self.z, ZQ, left=0.0, right=1.0)

    def ladder(self, df, side, levels=LEVELS):
        mu, s = self.loc_scale(df); L = np.asarray(levels)[None, :]
        if side == 'up': return 1 - self.cdf((L - mu[:, None]) / s[:, None])      # P(y >= +x)
        return self.cdf((-L - mu[:, None]) / s[:, None])                            # P(y <= −x)

    def params(self):
        return dict(mu_cols=self.mu_cols, sc_cols=self.sc_cols, inst=self.inst, ni=self.ni.tolist(), mmed=self.mmed.tolist(), smed=self.smed.tolist(),
                    bm=self.bm.tolist(), bs=self.bs.tolist(), z=self.z.tolist())

    @classmethod
    def from_params(cls, p):
        m = cls(p['mu_cols'], p['sc_cols'], p['inst'])
        for kk in ('ni', 'mmed', 'smed', 'bm', 'bs', 'z'): setattr(m, kk, np.array(p[kk]))
        return m


def hits(y, side, levels):
    Y = np.asarray(y)[:, None]; L = np.asarray(levels)[None, :]
    return (Y >= L).astype(float) if side == 'up' else (Y <= -L).astype(float)


TARGETS = [(inst, ref, side) for inst in ('S', 'F') for ref in ('c', 'o') for side in ('up', 'dn')]
NAME = {'S': '현물', 'F': '선물', 'c': '전날 종가 기준', 'o': '시가 기준', 'up': '고가', 'dn': '저가', 'pre': '08:30판', 'post': '09:10판'}


def walk(D, ycol, side, mk, start=750, step=21):
    n = len(D); P = np.full((n, len(SCORE_LV)), np.nan); y = D[ycol].to_numpy(float)
    for i in range(start, n, step):
        tr = np.arange(i); ok = ~np.isnan(y[tr]); m = mk().fit(D.iloc[tr[ok]], y[tr[ok]])
        P[i:i + step] = m.ladder(D.iloc[i:i + step], side, SCORE_LV)
    return P


def clim(D, ycol, side, win=250):
    y = D[ycol].to_numpy(float); n = len(y); P = np.full((n, len(SCORE_LV)), np.nan); H = hits(y, side, SCORE_LV)
    ok = ~np.isnan(y); Hn = np.where(ok[:, None], H, 0); cs = np.cumsum(Hn, 0); cn = np.cumsum(ok)
    for i in range(win, n):
        a = i - win; cnt = cn[i - 1] - (cn[a - 1] if a > 0 else 0)
        if cnt >= 100: P[i] = (cs[i - 1] - (cs[a - 1] if a > 0 else 0)) / cnt
    return P


def block_ci(d, B=1000, L=20, rng=None):
    rng = rng or np.random.default_rng(SEED); k = len(d); idx = np.arange(k); r = np.empty(B)
    for b in range(B):
        st = rng.integers(0, k, int(np.ceil(k / L))); s = np.concatenate([np.take(idx, range(a, a + L), mode='wrap') for a in st])[:k]; r[b] = d[s].mean()
    return r


def judge(Bm, Bb, segs):
    """수정 기준: 검증·보류 두 구간 모두 가장 좋은 비교 대상보다 3% 이상 낮고, 보류 구간 블록 부트스트랩 p<0.05, 2026년은 90% 구간 상단 +5% 미만"""
    out = {}
    for nm, m in segs.items():
        mm = m & ~np.isnan(Bm) & ~np.isnan(Bb)
        if mm.sum() < 60: out[nm] = None; continue
        d = Bm[mm] - Bb[mm]; base = Bb[mm].mean(); r = block_ci(d) / base
        out[nm] = dict(n=int(mm.sum()), model=float(Bm[mm].mean()), base=float(base), imp=float(-d.mean() / base * 100), p=float(np.mean(r >= 0)),
                       ci90=[float(-np.percentile(r, 95) * 100), float(-np.percentile(r, 5) * 100)])
    v, h, y26 = out.get('검증'), out.get('보류'), out.get('2026')
    ok = bool(v and h and v['imp'] >= 3 and h['imp'] >= 3 and h['p'] < 0.05 and (y26 is None or -y26['ci90'][0] < 5))
    return ok, out


def evaluate(D):
    idx = D.index; segs = {'검증': (idx >= '2016-01-01') & (idx < '2021-06-24'), '보류': idx >= '2021-06-24', '2026': idx >= '2026-01-01', 'KRX 야간 시기': idx >= '2025-06-09'}
    segs = {k: np.asarray(v) for k, v in segs.items()}
    res = []
    for time in ('pre', 'post'):
        for inst, ref, side in TARGETS:
            if time == 'post' and False: continue
            yc = f'{inst}_{side}_{ref}'; y = D[yc].to_numpy(float); H = hits(y, side, SCORE_LV); ok = ~np.isnan(y)
            mu, sc = feats(time, inst, False); muF, _ = feats(time, inst, True)
            P_m = walk(D, yc, side, lambda: Dist(mu, sc, inst)); P_f = walk(D, yc, side, lambda: Dist(muF, sc, inst))
            P_v = walk(D, yc, side, lambda: Dist([], ['rv20', 'park20'], inst)); P_c = clim(D, yc, side)
            br = lambda P: np.where(ok, np.nanmean((P - H) ** 2, 1), np.nan)
            Bm, Bf, Bv, Bc = br(P_m), br(P_f), br(P_v), br(P_c)
            hold = segs['보류'] & ~np.isnan(Bm) & ~np.isnan(Bv) & ~np.isnan(Bc)
            best_is_v = np.nanmean(Bv[hold]) <= np.nanmean(Bc[hold]); Bb = Bv if best_is_v else Bc
            passed, det = judge(Bm, Bb, segs)
            fpass, fdet = judge(Bf, Bm, segs)                       # 외국인 지표를 더했을 때 더 나은가(같은 기준)
            # 대표 칸의 맞춤표(보류 구간)
            rel = {}
            for lv in REP:
                j = int(np.argmin(np.abs(SCORE_LV - lv))); p = P_m[:, j]; h = H[:, j]; mm = segs['보류'] & ~np.isnan(p) & ok
                bins = []
                for a, b in ((0, .2), (.2, .4), (.4, .6), (.6, .8), (.8, 1.01)):
                    q = mm & (p >= a) & (p < b)
                    if q.sum(): bins.append([int(a * 100), int(min(b, 1) * 100), int(q.sum()), round(float(p[q].mean() * 100), 1), round(float(h[q].mean() * 100), 1)])
                rel[str(lv)] = dict(freq=round(float(h[mm].mean() * 100), 1), bins=bins)
            res.append(dict(time=time, inst=inst, ref=ref, side=side, ycol=yc, base_name='변동성만' if best_is_v else '지난 250일 분포', passed=passed, detail=det,
                            foreign_pass=fpass, foreign_detail=fdet, reliability=rel))
            h_ = det.get('보류') or {}; f_ = fdet.get('보류') or {}
            print(f"{NAME[time]} {NAME[inst]} {NAME[ref]} {NAME[side]}: 보류 개선 {h_.get('imp', float('nan')):.1f}% (p {h_.get('p', float('nan')):.3f}) · 통과 {passed} · 외국인 더하면 {f_.get('imp', float('nan')):+.1f}% 통과 {fpass}", flush=True)
    return res


def fit_all(D, ev=None):
    P = {}
    for time in ('pre', 'post'):
        for inst, ref, side in TARGETS:
            yc = f'{inst}_{side}_{ref}'
            fpass = any(r['foreign_pass'] for r in (ev or []) if r['ycol'] == yc and r['time'] == time)
            mu, sc = feats(time, inst, fpass); y = D[yc].to_numpy(float); ok = ~np.isnan(y)
            P[f'{time}_{yc}'] = dict(Dist(mu, sc, inst).fit(D[ok], y[ok]).params(), foreign=fpass)
    return P


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--deriv', default=os.path.join(ROOT, '_deriv', 'deriv', 'data')); ap.add_argument('--eval', action='store_true'); a = ap.parse_args()
    D = load(a.deriv); os.makedirs(os.path.join(ROOT, 'reach', 'out'), exist_ok=True); os.makedirs(os.path.join(ROOT, 'docs', 'reach', 'data'), exist_ok=True)
    print('자료', D.index[0], '~', D.index[-1], len(D), '일 · 야간선물 있는 날', int(D['night'].notna().sum()), flush=True)
    ev = None
    if a.eval:
        ev = evaluate(D)
        meta = dict(built=pd.Timestamp.now(tz='Asia/Seoul').strftime('%Y-%m-%d %H:%M KST'), data=[D.index[0], D.index[-1]], n=len(D), night_days=int(D['night'].notna().sum()),
                    seed=SEED, rule='검증(2016-01~2021-06)·보류(2021-06-24~) 모두 가장 좋은 비교 대상보다 0.1~5% 칸 평균 Brier 3% 이상 낮음 + 보류 블록 부트스트랩 p<0.05 + 2026 90% 구간 상단 +5% 미만',
                    versions=f'pandas {pd.__version__} · numpy {np.__version__}')
        json.dump(dict(meta=meta, results=ev), open(os.path.join(ROOT, 'docs', 'reach', 'data', 'eval.json'), 'w', encoding='utf-8'), ensure_ascii=False)
    else:
        try: ev = json.load(open(os.path.join(ROOT, 'docs', 'reach', 'data', 'eval.json'), encoding='utf-8'))['results']
        except Exception: ev = None
    P = fit_all(D, ev)
    json.dump(dict(fitted=pd.Timestamp.now(tz='Asia/Seoul').strftime('%Y-%m-%d %H:%M KST'), last=D.index[-1], models=P), open(os.path.join(ROOT, 'reach', 'out', 'params.json'), 'w'))
    print('저장 완료', flush=True)


if __name__ == '__main__':
    main()
