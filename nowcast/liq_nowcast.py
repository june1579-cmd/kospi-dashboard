#!/usr/bin/env python3
"""반대매매 당일 예정치(2026-11-24 사용자 요청: "가장 좋은 방법으로 예정치를 대시보드와 웹판에 표시하고 결과가 나오면 확정치로 교체").

방법 = liq-nowcast 가지 시험(research/liq_nowcast, 2026-11-24 11:57 결과)에서 2019~2025 로 고른 가장 좋은 것:
  · 점 예측: 선형 10개 설정 평균(종목 자료 없이) — 목표 = 로그(반대매매 ÷ 전날 반대매매), 달마다 그 전 자료로만 다시 학습, 최근 자료 가중/창
  · 범위: '최근 오차 크기 반영'(지난 오차 크기의 지수 평균 × 지난 500일 표준화 오차의 10·90%/5·95% 분위) — T-1 까지의 오차만 씀
  확인 구간 2026: 절대 오차 중앙값 27.5%, 80%가 ±47.7% 안 / 80% 범위 적중 76%(2019~2025 80%)
입력은 행 T = T일 저녁에 알 수 있는 값만(금투협은 T-1 기준일까지) — liq_features.py 그대로.
만드는 것
  out/liq_nowcast.csv          date, pred_eok, lo80, hi80, lo90, hi90, liq_eok(확정치, 아직 없으면 빈칸), kofia_asof — 2019~ 전 거래일(지난 날은 걷기 검증 예측)
  state/liq_nowcast_live.csv   확정치가 없을 때 낸 예정치의 기록(처음·마지막 값) + 나중에 들어온 확정치 → 실제 성적 확인용
자료를 추정으로 채우지 않는다: 확정치 칸(liq_eok)은 금투협 원자료 그대로, 예정치는 따로 '예정' 열에만.
"""
import os, sys, datetime as dt, re, time, warnings
import numpy as np, pandas as pd
warnings.filterwarnings('ignore')
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import liq_features as F

START = 2017
MEMBERS = ['F4|ridge|chg|M|win2', 'F4|ridge|chg|M|tau1', 'F4|ridge|chg|M|tau2', 'C3|ridge|chg|M|win1', 'F4|rob|chg|M|win2',
           'C3|rob|chg|M|win1', 'C3|ridge|chg|M|tau1', 'F4|rob|chg|M|tau2', 'F4|rob|chg|M|tau1', 'F2|ridge|chg|M|win2']
FS = {'F0': ['base_kofia', 'base_mkt'], 'F1': ['base_kofia', 'base_mkt', 'kofia_x', 'credit', 'cal']}
FS['F2'] = FS['F1'] + ['struct', 'flow']; FS['F3'] = FS['F2'] + ['vkospi']; FS['F4'] = FS['F3'] + ['kosdaq']
FS['C1'] = ['core']; FS['C2'] = ['core', 'core_x']; FS['C3'] = ['core', 'core_x', 'core_q']


def refresh_kosdaq():
    """코스닥 지수 일봉(네이버 금융 공개 차트, 로그인 없음)을 다시 받아 nowcast/data/kosdaq_index.csv 를 갱신. 못 받으면 전에 받은 파일 그대로."""
    p = os.path.join(HERE, 'data', 'kosdaq_index.csv')
    try:
        import requests
        r = requests.get('https://fchart.stock.naver.com/sise.nhn', params={'symbol': 'KOSDAQ', 'timeframe': 'day', 'count': 3000, 'requestType': 0},
                         headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://finance.naver.com/'}, timeout=30)
        rows = re.findall(r'<item data="([^"]+)"', r.text)
        if len(rows) < 2000: raise ValueError(f'행 {len(rows)}개')
        df = pd.DataFrame([x.split('|')[:5] for x in rows], columns=['date', 'open', 'high', 'low', 'close'])
        df['date'] = pd.to_datetime(df['date'], format='%Y%m%d').dt.strftime('%Y-%m-%d')
        for c in ['open', 'high', 'low', 'close']: df[c] = pd.to_numeric(df[c], errors='coerce')
        old = pd.read_csv(p) if os.path.exists(p) else df.iloc[:0]
        df = pd.concat([old[~old['date'].isin(df['date'])], df]).sort_values('date')
        df.to_csv(p, index=False); return f'코스닥 지수 {df["date"].iloc[-1]}까지'
    except Exception as e:
        return f'코스닥 지수 새로 받기 실패({e!r}) — 전 파일 사용'


# ---------------------------------------------------------------- 모형(시험 코드 run_experiments.py 의 _prep_lin·fit_predict(ridge·rob)·walk 그대로)
def _prep_lin(Xtr, Xte):
    med = np.nanmedian(Xtr, 0); med = np.where(np.isnan(med), 0, med); Xtr = np.where(np.isnan(Xtr), med, Xtr); Xte = np.where(np.isnan(Xte), med, Xte)
    lo, hi = np.percentile(Xtr, 0.5, 0), np.percentile(Xtr, 99.5, 0); Xtr = np.clip(Xtr, lo, hi); Xte = np.clip(Xte, lo, hi)
    mu, sd = Xtr.mean(0), Xtr.std(0); sd[sd < 1e-12] = 1; return (Xtr - mu) / sd, (Xte - mu) / sd


def fit_predict(model, Xtr, ytr, Xte, w=None):
    A, B = _prep_lin(Xtr, Xte); n = len(A); cut = int(n * 0.8); w0 = np.ones(n) if w is None else np.asarray(w, float)
    def rfit(A_, y_, w_, alphas):
        sw = w_ / w_.sum(); mx = sw @ A_; my = sw @ y_; Ac = A_ - mx; Aw = Ac * w_[:, None]; Gm = Ac.T @ Aw; rhs = Aw.T @ (y_ - my); out = []
        for al in alphas:
            bb = np.linalg.solve(Gm + al * np.eye(Gm.shape[0]), rhs); out.append((bb, my - mx @ bb))
        return out
    als = (0.1, 1, 10, 30, 100, 300, 1000); fits = rfit(A[:cut], ytr[:cut], w0[:cut], als)
    errs = [np.median(np.abs(A[cut:] @ bb + b0 - ytr[cut:])) for bb, b0 in fits]; ba = als[int(np.argmin(errs))]
    bb, b0 = rfit(A, ytr, w0, (ba,))[0]
    if model == 'rob':
        for _ in range(3):
            r = ytr - (A @ bb + b0); sc = 1.4826 * np.median(np.abs(r - np.median(r))) + 1e-9; ww = w0 * np.minimum(1.0, 1.345 * sc / (np.abs(r) + 1e-12)); bb, b0 = rfit(A, ytr, ww, (ba,))[0]
    return B @ bb + b0


def walk(df, feats, model, tau=None, win=None):
    """달마다 그 달 첫날 이전 행으로만 학습 → 그 달 예측(로그 금액). 목표 = 로그(반대매매 ÷ 전날 반대매매)."""
    X = df[feats].values.astype(float); y = df['y_chg'].values; dts = df['date'].values; yrs = df['date'].dt.year.values; mon = df['date'].dt.month.values
    pred = np.full(len(df), np.nan); okx = ~np.isnan(y) & (~np.isnan(X).all(1))
    for yy in range(START, int(yrs.max()) + 1):
        for mm in range(1, 13):
            te = (yrs == yy) & (mon == mm)
            if not te.any(): continue
            t0 = np.datetime64(f'{yy}-{mm:02d}-01'); tr = okx & (dts < t0)
            if win: tr &= dts >= (t0 - np.timedelta64(int(win * 365), 'D'))
            if tr.sum() < 200: continue
            w = None
            if tau: age = (t0 - dts[tr]).astype('timedelta64[D]').astype(float) / 365.0; w = np.exp(-age / tau); w = w / w.mean()
            pred[te] = fit_predict(model, X[tr], y[tr], X[te], w)
    return pred + np.log(df['liq_prev'].values)


def featset(G, fs):
    out = []
    for g in FS[fs]:
        for c in G.get(g, []):
            if c not in out: out.append(c)
    return out


def main():
    note = refresh_kosdaq(); t0 = time.time()
    R = F.load_raw(); df, G = F.build(R)
    if 'kosdaq' not in G or not G['kosdaq']: raise SystemExit('코스닥 지수 자료 없음 — 예정치를 만들지 않음')
    preds = []
    for m in MEMBERS:
        fs, model, _, _, *rest = m.split('|'); kw = {}
        for x in rest:
            if x.startswith('tau'): kw['tau'] = float(x[3:])
            if x.startswith('win'): kw['win'] = float(x[3:])
        preds.append(walk(df, featset(G, fs), model, **kw))
    pred = np.nanmean(np.vstack(preds), 0)                                   # 10개 평균(로그 금액)
    # 범위: '최근 오차 크기 반영' — 오차는 T-1 까지만(shift 1)
    y = df['y_lvl'].values; e = pd.Series(y - pred); sc = e.abs().shift(1).ewm(halflife=10, min_periods=20).mean(); z = (e / sc)
    zq = lambda q: z.shift(1).rolling(500, min_periods=100).quantile(q)
    # 확정치가 없는 마지막 날들은 오차가 아직 없으므로 마지막으로 계산된 크기·분위를 그대로 이어 쓴다
    scf, q = sc.ffill(), {k: zq(k).ffill() for k in (.05, .10, .90, .95)}
    out = pd.DataFrame({'date': df['date'].dt.strftime('%Y-%m-%d'), 'pred_eok': np.exp(pred),
                        'lo80': np.exp(pred + scf * q[.10]), 'hi80': np.exp(pred + scf * q[.90]), 'lo90': np.exp(pred + scf * q[.05]), 'hi90': np.exp(pred + scf * q[.95]),
                        'liq_eok': df['liq'], 'kofia_asof': df['kdate'].dt.strftime('%Y-%m-%d')})
    out = out[(df['date'].dt.year >= 2019).values & ~np.isnan(pred)]
    for c in ['pred_eok', 'lo80', 'hi80', 'lo90', 'hi90']: out[c] = out[c].round(1)
    out.to_csv('out/liq_nowcast.csv', index=False, float_format='%.2f')
    # 실제로 낸 예정치 기록(처음 낸 값·마지막 값, 확정치가 들어오면 채움)
    lp = 'state/liq_nowcast_live.csv'; os.makedirs('state', exist_ok=True)
    live = pd.read_csv(lp, dtype=str) if os.path.exists(lp) else pd.DataFrame(columns=['date', 'first_at', 'first_pred', 'first_lo80', 'first_hi80', 'last_at', 'last_pred', 'last_lo80', 'last_hi80', 'actual'])
    now = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).strftime('%Y-%m-%d %H:%M'); act = dict(zip(out['date'], out['liq_eok']))
    for _, r in out[out['liq_eok'].isna()].iterrows():
        v = [f"{r['pred_eok']:.1f}", f"{r['lo80']:.1f}", f"{r['hi80']:.1f}"]
        if (live['date'] == r['date']).any():
            live.loc[live['date'] == r['date'], ['last_at', 'last_pred', 'last_lo80', 'last_hi80']] = [now] + v
        else:
            live.loc[len(live)] = [r['date'], now] + v + [now] + v + ['']
    live['actual'] = [('' if pd.isna(act.get(d)) else f'{act.get(d):.1f}') if (pd.isna(a) or a == '') else a for d, a in zip(live['date'], live['actual'])]
    live.to_csv(lp, index=False)
    last = out.iloc[-1]
    print(f"{note} · {len(out)}행 · {time.time() - t0:.0f}초 · 마지막 {last['date']} 예정 {last['pred_eok']:.0f}억(80% {last['lo80']:.0f}~{last['hi80']:.0f}) 확정치 {'있음' if pd.notna(last['liq_eok']) else '아직'}")


if __name__ == '__main__':
    main()
