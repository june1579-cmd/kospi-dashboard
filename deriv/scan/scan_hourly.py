"""시간 단위 예측 가능성 — Yahoo 1시간봉(코스피 ^KS11, 코스피200 ^KS200; 2024-11-20~). 선물 1시간봉은 무료 과거 자료가 없어 코스피200 지수로 대신.

맞힐 대상: 다음 봉 시가 → h봉 뒤 종가, h = 1·2·3봉(시간), 6봉(약 하루), 12봉(약 이틀), 30봉(약 1주). 종류는 scan_run.py 와 같다(σ 는 직전 700봉 h봉 등락 표준편차).
지표: 봉 자체(1~35봉 등락, 변동성, 이평 괴리, 35봉 범위 위치, 그날 몇 번째 봉, 요일, 그날 갭과 장중 누적) + 일별 지표 전체를 하루 늦춰 붙임(전날 장 마감 뒤까지 아는 값).
검증: 2025-04부터 분기마다, 그 전 자료만으로(끝 h봉 비움) 학습 → 그 분기 시험. 해마다(2025, 2026) 시험 결과를 모아 평가.
출력: deriv/scan/out/HOURLY/ 아래 csv
"""
import glob
import os
import sys

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.metrics import roc_auc_score

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import scan_run as S  # noqa: E402

INTRA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, '..', '..', 'intraday-data', 'intraday')
HS = [1, 2, 3, 6, 12, 30]


def load(sym):
    fs = sorted(glob.glob(os.path.join(INTRA, f'yahoo_{sym}_60m', '*.csv.gz')))
    d = pd.concat([pd.read_csv(f) for f in fs], ignore_index=True)
    d['ts'] = pd.to_datetime(d['ts']); d = d.drop_duplicates('ts').sort_values('ts').set_index('ts')
    d = d[(d.index.hour >= 9) & (d.index.hour <= 15)]
    return d[['open', 'high', 'low', 'close']].astype(float)


def features(b):
    c, o = b['close'], b['open']
    F = pd.DataFrame(index=b.index)
    r1 = c.pct_change()
    for w in (1, 2, 3, 6, 12, 30):
        F[f'H_등락_{w}봉'] = c.pct_change(w) * 100
    for w in (6, 30):
        F[f'H_변동성_{w}봉'] = r1.rolling(w).std() * 100
    for w in (6, 30, 60):
        F[f'H_이평괴리_{w}봉'] = (c / c.rolling(w).mean() - 1) * 100
    F['H_범위위치_30봉'] = (c - b['low'].rolling(30).min()) / (b['high'].rolling(30).max() - b['low'].rolling(30).min())
    day = pd.Series(b.index.date, index=b.index)
    F['H_봉순서'] = day.groupby(day).cumcount()
    F['H_요일'] = b.index.dayofweek
    first_open = o.groupby(day).transform('first')
    prev_close = c.groupby(day).last().shift(1)
    F['H_오늘갭%'] = (first_open / day.map(prev_close) - 1) * 100
    F['H_장중누적%'] = (c / first_open - 1) * 100
    # 일별 지표: 하루 늦춰(전날 값) 붙임
    X = S.X0.copy(); X.index = pd.to_datetime(X.index)
    Xl = X.shift(1)
    dd = pd.to_datetime(day.values)
    Xd = Xl.reindex(dd); Xd.index = b.index
    return F.join(Xd)


def htargets(b, h):
    c, o = b['close'], b['open']
    o1 = o.shift(-1); r = (c.shift(-h) / o1 - 1) * 100
    fut = pd.concat([c.shift(-k) for k in range(1, h + 1)], axis=1)
    pmin = (fut.min(axis=1) / o1 - 1) * 100; pmax = (fut.max(axis=1) / o1 - 1) * 100
    past = c.pct_change(h) * 100; sig = past.rolling(700, min_periods=200).std()
    ok = r.notna() & fut.notna().all(axis=1)
    T = pd.DataFrame(index=b.index)
    T['ret'] = r.where(ok); T['dir'] = (r > 0).astype(float).where(ok)
    T['big_up'] = (r > S.K * sig).astype(float).where(ok & sig.notna()); T['big_dn'] = (r < -S.K * sig).astype(float).where(ok & sig.notna())
    T['path_dn'] = (pmin < -S.K * sig).astype(float).where(ok & sig.notna()); T['path_up'] = (pmax > S.K * sig).astype(float).where(ok & sig.notna())
    T['trend'] = (np.sign(r) == np.sign(past)).astype(float).where(ok & past.notna() & (r != 0))
    return T


def main():
    out = os.path.join(HERE, 'out', 'HOURLY'); os.makedirs(out, exist_ok=True)
    rows_ml, rows_ens = [], []
    for sym, nm in (('KS11', 'KOSPI_1h'), ('KS200', 'K200_1h')):
        b = load(sym); X = features(b)
        q_starts = pd.date_range('2025-04-01', b.index.max(), freq='QS')
        for h in HS:
            T = htargets(b, h)
            preds = {ty: [] for ty in S.TYPES + ['ret']}
            ens = []
            for qs in q_starts:
                qe = qs + pd.offsets.QuarterBegin(1)
                te = X.index[(X.index >= qs) & (X.index < qe)]
                if len(te) < 30: continue
                pos = X.index.get_loc(te[0])
                tr = X.index[:max(0, pos - h)]; tr = tr[T.loc[tr, 'ret'].notna().values]
                if len(tr) < 400: continue
                Xtr, Xte = X.loc[tr], X.loc[te]
                mcols = [c for c in Xtr.columns if Xtr[c].notna().sum() >= 150]
                names, fid, Ctr, Cte = S.conditions(Xtr[mcols], Xte[mcols])
                for ty in S.TYPES + ['ret']:
                    ytr = T.loc[tr, ty]; yte = T.loc[te, ty]; ok = ytr.notna().values; okte = yte.notna().values
                    if ty != 'ret' and ytr[ok].nunique() < 2: continue
                    try:
                        mdl = S.ml_fit(Xtr[mcols].values[ok], ytr.values[ok] if ty == 'ret' else ytr.values[ok].astype(int), 'reg' if ty == 'ret' else 'clf')
                    except Exception as e:
                        print('ml 실패', nm, h, ty, qs.date(), e); continue
                    if okte.sum() == 0: continue
                    pr = mdl.predict(Xte[mcols].values[okte]) if ty == 'ret' else mdl.predict_proba(Xte[mcols].values[okte])[:, 1]
                    preds[ty].append(pd.DataFrame({'ts': te[okte], 'p': pr, 'y': yte.values[okte], 'base_tr': float(np.mean(ytr.values[ok]))}))
                    if ty != 'ret':
                        rules, base = S.mine(Ctr[ok], ytr.values[ok].astype(np.float32), fid, h)
                        up = np.zeros(len(te), bool); dn = np.zeros(len(te), bool)
                        for rule, sgn, p, n, sc in rules:
                            f = Cte[:, list(rule)].prod(axis=1) > 0
                            if sgn > 0: up |= f
                            else: dn |= f
                        for side, m in (('높임', up & ~dn), ('낮춤', dn & ~up)):
                            mm = m & okte
                            ens.append({'대상': nm, 'h': h, '종류': ty, '분기': str(qs.date()), '해': qs.year, '쪽': side, '신호봉': int(mm.sum()),
                                        '시험봉': int(okte.sum()), '적중합': float(yte[mm].sum()), '기본합': float(yte[okte].sum())})
            rows_ens += ens
            for ty, lst in preds.items():
                if not lst: continue
                P = pd.concat(lst); P['해'] = P['ts'].dt.year
                for yr, g in P.groupby('해'):
                    if ty == 'ret':
                        rows_ml.append({'대상': nm, 'h': h, '종류': ty, '해': yr, '시험봉': len(g), 'IC': stats.spearmanr(g['p'], g['y'])[0]})
                    else:
                        yy = g['y'].astype(int).values
                        auc = roc_auc_score(yy, g['p']) if len(set(yy)) == 2 else np.nan
                        top = g['p'] >= g['p'].quantile(0.8); bot = g['p'] <= g['p'].quantile(0.2)
                        rows_ml.append({'대상': nm, 'h': h, '종류': ty, '해': yr, '시험봉': len(g), 'AUC': auc, '상위20%적중': yy[top.values].mean(),
                                        '하위20%적중': yy[bot.values].mean(), '기본': yy.mean()})
            print(nm, h, 'done', flush=True)
    pd.DataFrame(rows_ml).to_csv(os.path.join(out, 'ml_oos.csv'), index=False, encoding='utf-8')
    E = pd.DataFrame(rows_ens)
    if len(E):
        E = E.groupby(['대상', 'h', '종류', '해', '쪽'], as_index=False)[['신호봉', '시험봉', '적중합', '기본합']].sum()
        E['적중'] = E['적중합'] / E['신호봉'].replace(0, np.nan); E['기본'] = E['기본합'] / E['시험봉']
    E.to_csv(os.path.join(out, 'ens_oos.csv'), index=False, encoding='utf-8')


if __name__ == '__main__':
    main()
