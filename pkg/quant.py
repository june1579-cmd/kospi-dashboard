# -*- coding: utf-8 -*-
"""quant.py — 8. 정밀 검증(2015~, 3년 학습 · 연도별 검증) : q_daily, q_models, q_years, q_strat, q_sens, q_ic, q_now, q_attr(확률이 바뀐 이유)
   2026-10-27 재구축. 10/20판(2026년 자료만, 80일 학습·20일 검증)은 초기화로 코드가 사라져 같은 틀을 2015년부터의 자료로 다시 만들었다.

   정의
   - 지표(그날 장 마감 때 아는 값; 금투협 예탁금·신용·미수금·반대매매는 전날 공시분 = shift 1):
     신용/예탁금 비율, 예탁금 5일 변화율, MACD 히스토그램(÷종가), ATR14/종가, 외국인 20일 순매수(조원), 거래대금/20일 평균, VKOSPI 5일 변화율,
     신용 연중고점 대비(250일 최고 대비 %), 미수 반대매매 5일 합계(억원), 신용 5일 증감률, 20일 이격도, 신용 일간 증감률, 거래대금/예탁금, VKOSPI, 개인 20일 순매수(조원), 20일 수익률
   - 예측 대상: 10일 상승 = 10거래일 뒤 종가 > 오늘 종가. 5일 내 급락·청산 = 다음 1~5거래일 안에 사건(코스피 하루 −3% 이하 · 미수 반대매매 금액이 지난 250일 상위 5% · VKOSPI 하루 +20% 이상) 발생.
     (10/20판의 '미수 반대매매 비중 7%'는 2019~2023년 비중이 5~9%로 늘 넘고 2024~25년은 1% 아래라 해마다 비교가 안 돼 금액 분위로 바꿈)
   - 국면: 고변동 청산(신용 5일 −3% 이하이거나 VKOSPI 5일 +25% 이상) > 상승 추세(종가 > 20일선이고 20일 수익률 +3% 초과) > 하락 추세(종가 < 20일선이고 20일 수익률 −3% 미만) > 횡보.
   - 검증: 해마다 앞 3년(끝의 10거래일은 비움)으로 학습해 그 해를 예측(2018~2026). 모형 = 단순 규칙(외국인 20일 순매수가 학습 구간 60% 분위 이상이면 매수, VKOSPI가 80% 분위 이상이면 위험),
     로지스틱(표준화, class_weight balanced), 부스팅(HistGradientBoosting, depth 3, 200회). 신호 = 확률이 학습 구간 기준 비율 이상.
   - 매매: 신호 다음 날 종가 진입, 10거래일 보유 뒤 종가 청산, 왕복 비용 0.3%. 위험 시 보류 = 위험 신호가 켜진 날은 진입하지 않음. 위험 신호 나오면 청산 = 보유 중 위험 신호면 다음 날 종가 청산.
"""
import numpy as np, pandas as pd, warnings
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score
from scipy.stats import spearmanr
warnings.filterwarnings('ignore')

FEAT = [('cd_ratio', '신용/예탁금 비율'), ('dep_5d', '예탁금 5일 변화율'), ('macd_hist', 'MACD히스토그램'), ('atr14_pct', 'ATR14/종가'), ('for20', '외국인 20일 순매수'),
        ('val_ratio', '거래대금/20일평균'), ('vk_5d', 'VKOSPI 5일 변화율'), ('cr_vs_high', '신용 연중고점 대비'), ('liq5', '미수 반대매매 5일 합계'), ('cr_5d', '신용 5일 증감률'),
        ('disp20', '20일 이격도'), ('cr_1d', '신용 일간 증감률'), ('val_dep', '거래대금/예탁금'), ('vk', 'VKOSPI'), ('ind20', '개인 20일 순매수'), ('ret20', '20일 수익률')]
FKEYS = [k for k, _ in FEAT]; FNAME = dict(FEAT)
HOLD, COST, GAP, TRAIN_Y, FIRST_TEST = 10, 0.003, 10, 12, 2018   # 10/27: 학습 3년 → 12년(2006~ 장기 자료, pkg/history). 걷기 검증 risk5 AUC 0.66 → 0.72
YC = pd.Timestamp('2015-01-01')
Q_BUY, Q_RISK = 0.6, 0.8
MODELS = ['단순 규칙', '로지스틱', '부스팅']
TARGETS = {'up10': '10일 상승', 'risk5': '5일 내 급락·청산'}

def load_history(D):
    """pkg/history/ 의 2006~ 장기 자료(사용자 첨부)를 2015년 이전 구간에 앞붙임. 없으면 그대로."""
    import os
    H = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'history')
    f = lambda n: os.path.join(H, n)
    if not os.path.exists(f('01_코스피_일별시세.csv')): return D
    def rd(p):
        d = pd.read_csv(p, encoding='utf-8-sig'); dc = d.columns[0]; d[dc] = pd.to_datetime(d[dc].astype(str), errors='coerce'); return d.dropna(subset=[dc]).set_index(dc).sort_index()
    K2 = rd(f('01_코스피_일별시세.csv')).rename(columns={'종가': 'close', '시가': 'open', '고가': 'high', '저가': 'low', '거래량': 'vol', '거래대금': 'val'})
    K2['val'] = K2['val'] / 1e6; K2['vol'] = K2['vol'] / 1000; K2['chg'] = K2['close'].pct_change() * 100; K2['diff'] = K2['close'].diff()
    F2 = rd(f('01_코스피_투자자별_순매수_거래대금.csv')).rename(columns={'기관합계': 'inst', '기타법인': 'other', '개인': 'indiv', '외국인합계': 'foreign'})[['inst', 'other', 'indiv', 'foreign']] / 1e9
    L2 = rd(f('01_금투협_증시자금추이.csv')); L2.columns = ['deposit', 'deriv', 'rp', 'misu', 'liq', 'ratio']
    C2 = rd(f('01_금투협_신용공여잔고.csv')); C2.columns = ['credit', 'kospi', 'kosdaq', 'short', 'short_k', 'short_q', 'sub', 'pledge']
    D = dict(D)
    for k, old in (('K', K2), ('F', F2), ('L', L2), ('C', C2)):
        cur = D[k]; cut = cur.index.min(); D[k] = pd.concat([old[old.index < cut], cur]).sort_index()
    return D

def build(D):
    D = load_history(D)
    K, V, F, L, C = D['K'], D['V'], D['F'], D['L'], D['C']
    c, h, l = K.close, K.high, K.low; idx = c.index
    vk = V.close.reindex(idx).ffill()
    dep = L.deposit.reindex(idx).shift(1) / 1e6; cred = C.credit.reindex(idx).shift(1) / 1e6
    liq = L.liq.reindex(idx).shift(1) / 100                                                    # 전날 공시분(억원). 사건 판정에는 shift(-1)로 그날 금액을 씀
    foreign = F.foreign.reindex(idx) / 1000; indiv = F.indiv.reindex(idx) / 1000; val = K.val / 1e6   # 조원
    X = pd.DataFrame(index=idx)
    X['cd_ratio'] = cred / dep * 100
    X['dep_5d'] = dep.pct_change(5) * 100
    e12, e26 = c.ewm(span=12, adjust=False).mean(), c.ewm(span=26, adjust=False).mean(); macd = e12 - e26
    X['macd_hist'] = (macd - macd.ewm(span=9, adjust=False).mean()) / c * 100
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    X['atr14_pct'] = tr.rolling(14).mean() / c * 100
    X['for20'] = foreign.rolling(20).sum()
    X['val_ratio'] = val / val.rolling(20).mean()
    X['vk_5d'] = vk.pct_change(5) * 100
    X['cr_vs_high'] = (cred / cred.rolling(250, min_periods=60).max() - 1) * 100
    X['liq5'] = liq.rolling(5).sum()
    X['cr_5d'] = cred.pct_change(5) * 100
    ma20 = c.rolling(20).mean(); X['disp20'] = (c / ma20 - 1) * 100
    X['cr_1d'] = cred.pct_change() * 100
    X['val_dep'] = val / dep * 100
    X['vk'] = vk
    X['ind20'] = indiv.rolling(20).sum()
    X['ret20'] = c.pct_change(20) * 100
    # 예측 대상
    Y = pd.DataFrame(index=idx)
    fwd = lambda n: c.shift(-n) / c - 1
    Y['r5'], Y['r10'], Y['r20'] = fwd(5) * 100, fwd(10) * 100, fwd(20) * 100
    Y['up10'] = np.where(Y['r10'].isna(), np.nan, (Y['r10'] > 0).astype(float))
    liq_p95 = liq.shift(-1).rolling(250, min_periods=120).quantile(0.95)   # 그날 금액(사건 판정용, 공시는 다음 날)의 250일 95% 분위
    ev = (K.chg <= -3) | (liq.shift(-1) >= liq_p95) | (vk.pct_change() >= 0.20)
    ev_f = ev.astype(float).values; T = len(idx); r5 = np.full(T, np.nan)
    for i in range(T):
        if i + 5 < T: r5[i] = ev_f[i + 1:i + 6].max()
    Y['risk5'] = r5; Y['event'] = ev.astype(int)
    # 국면
    hv = (X['cr_5d'] <= -3) | (X['vk_5d'] >= 25)
    up = (c > ma20) & (X['ret20'] > 3); dn = (c < ma20) & (X['ret20'] < -3)
    regime = pd.Series(np.select([hv.fillna(False), up.fillna(False), dn.fillna(False)], ['고변동 청산', '상승 추세', '하락 추세'], '횡보'), index=idx)
    return X, Y, regime, c

FUNIT = {'cd_ratio': '%', 'dep_5d': '%', 'macd_hist': '%', 'atr14_pct': '%', 'for20': '조원', 'val_ratio': '배', 'vk_5d': '%', 'cr_vs_high': '%', 'liq5': '억원',
         'cr_5d': '%', 'disp20': '%', 'cr_1d': '%', 'val_dep': '%', 'vk': '', 'ind20': '조원', 'ret20': '%'}

def explain(Xf, Yf, cf, regf, D):
    """마지막 날 확률이 전 거래일보다 바뀐 이유(q_attr)와 국면 판정 이유·다음 거래일 국면 기준선(q_now 줄).
       기여(%p) = [오늘 확률 − (그 입력만 전날 값으로 되돌린 확률)]와 [(전날에 그 입력만 오늘 값을 넣은 확률) − 전날 확률]의 평균.
       모형은 그 해 예측에 쓴 것과 같게(앞 12년, 끝 10거래일 비움, 같은 설정) 다시 학습. 그날 빈칸(자료 없음) 입력은 따로 표시."""
    d1, d0 = Xf.index[-1], Xf.index[-2]; Yv = int(d1.year); yrs = Xf.index.year
    tr = (yrs >= Yv - TRAIN_Y) & (yrs <= Yv - 1); tr_idx = Xf.index[tr][:-GAP] if GAP else Xf.index[tr]
    x0, x1 = Xf.loc[[d0], FKEYS], Xf.loc[[d1], FKEYS]
    rows, summ = [], {}
    for t, tn in TARGETS.items():
        y = Yf.loc[tr_idx, t]; lab = y.notna(); Xtr = Xf.loc[tr_idx[lab.values], FKEYS]; ytr = y[lab].values
        m = HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=200, l2_regularization=1.0, random_state=0)
        ok = Xtr.notna().any(axis=1); m.fit(Xtr[ok], ytr[ok])
        p0, p1 = m.predict_proba(x0)[0, 1], m.predict_proba(x1)[0, 1]; ctb = {}
        for f in FKEYS:
            a = x1.copy(); a[f] = x0[f].values; b = x0.copy(); b[f] = x1[f].values
            ctb[f] = ((p1 - m.predict_proba(a)[0, 1]) + (m.predict_proba(b)[0, 1] - p0)) / 2 * 100
        miss = [f for f in FKEYS if pd.isna(x1[f].iloc[0]) and not pd.isna(x0[f].iloc[0])]
        order = sorted(FKEYS, key=lambda f: -abs(ctb[f]))
        summ[t] = dict(name=tn, p0=p0 * 100, p1=p1 * 100, miss=sum(ctb[f] for f in miss), top=[(FNAME[f], ctb[f]) for f in order if f not in miss][:3])
        rows.append({'kind': 'sum', 'target': tn, 'prev_date': d0.strftime('%Y-%m-%d'), 'date': d1.strftime('%Y-%m-%d'), 'p_prev': round(p0 * 100, 1), 'p_now': round(p1 * 100, 1),
                     'delta_pp': round((p1 - p0) * 100, 1), 'sum_pp': round(sum(ctb.values()), 1), 'missing_pp': round(summ[t]['miss'], 1)})
        for r, f in enumerate(order, 1):
            v0, v1 = x0[f].iloc[0], x1[f].iloc[0]
            rows.append({'kind': 'feat', 'target': tn, 'feat': f, 'name': FNAME[f], 'unit': FUNIT[f], 'prev_date': d0.strftime('%Y-%m-%d'), 'date': d1.strftime('%Y-%m-%d'),
                         'prev_value': round(float(v0), 3) if pd.notna(v0) else np.nan, 'value': round(float(v1), 3) if pd.notna(v1) else np.nan,
                         'contrib_pp': round(ctb[f], 1), 'missing': int(f in miss), 'rank': r})
    q_attr = pd.DataFrame(rows)
    vk_stale = pd.isna(D['V'].close.reindex([d1]).iloc[0]) if D.get('V') is not None else False   # 그날 VKOSPI 미수집 → 전날 값으로 계산됨
    q_attr['note'] = np.where(q_attr['kind'] == 'sum', (f'VKOSPI {d1.month}/{d1.day} 미수집 — 전날 값으로 계산' if vk_stale else ''), '')
    sg = lambda v, n=1: ('+' if v > 0 else ('−' if v < 0 else '')) + f'{abs(v):,.{n}f}'
    # 국면 판정 이유
    c = cf; ma20 = c.rolling(20).mean(); cr5, vk5, r20 = Xf['cr_5d'].iloc[-1], Xf['vk_5d'].iloc[-1], Xf['ret20'].iloc[-1]
    why = (f"{regf.iloc[-1]} — 신용 5일 {sg(cr5, 2)}%(고변동 청산 기준 −3% 이하 {'맞음' if cr5 <= -3 else '아님'}), VKOSPI 5일 {sg(vk5)}%(기준 +25% 이상 {'맞음' if vk5 >= 25 else '아님'}), "
           f"종가 {c.iloc[-1]:,.2f} {'>' if c.iloc[-1] > ma20.iloc[-1] else '<'} 20일선 {ma20.iloc[-1]:,.1f}, 20일 수익률 {sg(r20)}%(추세 기준 ±3%)")
    # 다음 거래일 국면 기준선
    thr_ma = float(c.iloc[-19:].mean()); c20 = float(c.iloc[-20]); thr_m3, thr_p3 = c20 * 0.97, c20 * 1.03
    try:
        DH = load_history(D); craw = DH['C'].credit.reindex(Xf.index) / 1e6
        thr_cr = float(craw.iloc[-6]) * 0.97; known = craw.iloc[:-1].dropna(); last_cr = float(known.iloc[-1]); last_cd = known.index[-1]
        cr_txt = f"다음 공시 신용이 {thr_cr:,.2f}조원 이하({last_cd:%m/%d} {last_cr:,.2f}조 대비 {sg((thr_cr / last_cr - 1) * 100, 2)}%)"
    except Exception:
        cr_txt = '다음 공시 신용 5일 감소율이 −3% 이하'
    thr_vk = float(Xf['vk'].iloc[-5]) * 1.25
    nxt = (f"다음 거래일 종가 {max(thr_ma, thr_p3):,.1f} 넘으면 상승 추세, {min(thr_ma, thr_m3):,.1f} 아래면 하락 추세, 그 사이는 횡보"
           f"(20일선 {thr_ma:,.1f}, 20일 수익률 −3%·+3% 선 {thr_m3:,.1f}·{thr_p3:,.1f}). 단 {cr_txt}이거나 VKOSPI {thr_vk:.2f} 이상이면 고변동 청산이 먼저.")
    md_ = lambda d: f'{d.month}/{d.day}'
    extra = []
    for t in TARGETS:
        s_ = summ[t]
        extra.append({'item': f"확률 변화 · {s_['name']}", 'value': round(s_['p1'] - s_['p0'], 1),
                      'text': f"{s_['p0']:.1f}% → {s_['p1']:.1f}%({md_(d0)} → {md_(d1)}). 큰 이유: " + ' · '.join(f'{n} {sg(v)}%p' for n, v in s_['top'])
                              + (f" · 그날 자료 빈칸(거래대금·고저가 등) {sg(s_['miss'])}%p" if abs(s_['miss']) >= 0.05 else '') + (f' · VKOSPI {d1.month}/{d1.day} 미수집(전날 값으로 계산)' if vk_stale else '') + ' (기여 계산: 맨 위 그래프 아래 표)'})
    extra.append({'item': '국면 판정 이유', 'value': np.nan, 'text': why})
    extra.append({'item': '다음 거래일 국면 기준선', 'value': np.nan, 'text': nxt})
    return q_attr, extra

def _fit_predict(model, Xtr, ytr, Xte):
    if model == '로지스틱':
        m = make_pipeline(StandardScaler(), LogisticRegression(C=1.0, class_weight='balanced', max_iter=2000))
        ok = Xtr.notna().all(axis=1); m.fit(Xtr[ok], ytr[ok]); te_ok = Xte.notna().all(axis=1)
        p = pd.Series(np.nan, index=Xte.index); p[te_ok] = m.predict_proba(Xte[te_ok])[:, 1]; return p
    if model == '부스팅':
        m = HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=200, l2_regularization=1.0, random_state=0)
        ok = Xtr.notna().any(axis=1); m.fit(Xtr[ok], ytr[ok]); te_ok = Xte.notna().any(axis=1)
        p = pd.Series(np.nan, index=Xte.index); p[te_ok] = m.predict_proba(Xte[te_ok])[:, 1]; return p
    raise ValueError(model)

def walk_forward(X, Y, years):
    """연도별: 앞 3년(끝 10거래일 비움)으로 학습 → 그 해 예측. 결과: P[target][model] 확률 Series(검증 구간만), THR[year] 단순 규칙 기준값, BASE[target][year]."""
    P = {t: {m: pd.Series(np.nan, index=X.index) for m in MODELS} for t in TARGETS}
    THR, BASE = {}, {t: {} for t in TARGETS}
    yrs = X.index.year
    for Yv in years:
        tr = (yrs >= Yv - TRAIN_Y) & (yrs <= Yv - 1); te = yrs == Yv
        tr_idx = X.index[tr][:-GAP] if GAP else X.index[tr]
        if len(tr_idx) < 200 or te.sum() == 0: continue
        q_for = X.loc[tr_idx, 'for20'].quantile(Q_BUY); q_vk = X.loc[tr_idx, 'vk'].quantile(Q_RISK)
        THR[Yv] = {'for20': q_for, 'vk': q_vk}
        te_idx = X.index[te]
        P['up10']['단순 규칙'][te_idx] = (X.loc[te_idx, 'for20'] >= q_for).astype(float)
        P['risk5']['단순 규칙'][te_idx] = (X.loc[te_idx, 'vk'] >= q_vk).astype(float)
        for t in TARGETS:
            y = Y.loc[tr_idx, t]; lab = y.notna()
            BASE[t][Yv] = float(y[lab].mean())
            for m in ('로지스틱', '부스팅'):
                P[t][m][te_idx] = _fit_predict(m, X.loc[tr_idx[lab.values], FKEYS], y[lab].values, X.loc[te_idx, FKEYS])
    return P, THR, BASE

def _metrics(p, y, thr):
    ok = p.notna() & y.notna(); p, y = p[ok], y[ok]
    if len(y) < 20 or y.nunique() < 2: return dict(auc=np.nan, precision=np.nan, recall=np.nan, base=np.nan, signals=int((p >= thr).sum()) if len(p) else 0, days=int(len(y)))
    sig = p >= thr; tp = int((sig & (y == 1)).sum())
    return dict(auc=round(float(roc_auc_score(y, p)), 3), precision=round(tp / sig.sum() * 100, 1) if sig.sum() else np.nan, recall=round(tp / (y == 1).sum() * 100, 1),
                base=round(float(y.mean() * 100), 1), signals=int(sig.sum()), days=int(len(y)))

def simulate(c, buy, risk, idx_oos, exit_on_risk=False, hold=HOLD, cost=COST):
    """buy·risk: bool Series(날짜 인덱스). 신호 다음 날 종가 진입, hold일 보유. 반환: 일별 전략 수익률(Series, OOS), 거래 목록."""
    cl = c.reindex(idx_oos); pos = np.zeros(len(cl)); trades = []; i = 0; n = len(cl)
    b = buy.reindex(idx_oos).fillna(False).values; r = risk.reindex(idx_oos).fillna(False).values
    while i < n - 1:
        if b[i] and not r[i]:
            e = i + 1; x = min(e + hold, n - 1)
            if e >= n - 1: break          # 마지막 날 신호: 다음 날 종가 진입이라 아직 거래가 없다(수익률 없음)
            risk_exit = False
            if exit_on_risk:
                for j in range(e + 1, x + 1):
                    if r[j - 1]: x = j; risk_exit = True; break
            pos[e + 1:x + 1] = 1          # e일 종가 진입 → e+1일부터 x일까지의 종가 수익률을 먹는다
            is_open = (not risk_exit) and (e + hold > n - 1)   # 아직 보유 기간이 안 끝난 거래: 마지막 날은 청산이 아니라 '보유 중'(11/11 수정 — 전엔 날마다 마지막 날에 청산 표시가 찍혀 카톡에 '정밀검증 청산'이 매일 나갔음)
            trades.append((idx_oos[e], idx_oos[x], float(cl.iloc[x] / cl.iloc[e] - 1 - cost), is_open))
            i = x
        else: i += 1
    ret = cl.pct_change().fillna(0).values * pos
    for (d0, d1, *_) in trades: ret[idx_oos.get_loc(d0) + 1] -= cost       # 비용은 진입 다음 날에 한 번
    return pd.Series(ret, index=idx_oos), trades, pos

def _stats(ret, trades, pos):
    eq = (1 + ret).cumprod(); total = eq.iloc[-1] - 1; mdd = (eq / eq.cummax() - 1).min()
    sharpe = ret.mean() / ret.std() * np.sqrt(250) if ret.std() > 0 else np.nan
    wins = [t[2] for t in trades if t[2] > 0]; losses = [t[2] for t in trades if t[2] <= 0]
    return dict(total=round(total * 100, 2), mdd=round(mdd * 100, 2), sharpe=round(float(sharpe), 2) if pd.notna(sharpe) else np.nan, trades=len(trades),
                win=round(len(wins) / len(trades) * 100, 1) if trades else np.nan, payoff=round(np.mean(wins) / abs(np.mean(losses)), 2) if wins and losses else np.nan,
                exposure=round(float(pos.mean() * 100), 2))

def rand_pct(c, idx_oos, n_trades, total, hold=HOLD, cost=COST, n=1000, seed=0):
    if n_trades == 0: return np.nan
    rng = np.random.default_rng(seed); cl = c.reindex(idx_oos).values; m = len(cl); tot = []
    for _ in range(n):
        starts = np.sort(rng.choice(np.arange(1, m - hold - 1), size=n_trades, replace=False))
        eq = 1.0; last_end = -1
        for s in starts:
            if s <= last_end: continue
            e = min(s + hold, m - 1); eq *= (cl[e] / cl[s]) * (1 - cost); last_end = e
        tot.append(eq - 1)
    return round(float(np.mean(np.array(tot) < total / 100) * 100), 1)

def run(D):
    X, Y, regime, c = build(D)
    last_year = int(X.index[-1].year); years = list(range(FIRST_TEST, last_year + 1))
    P, THR, BASE = walk_forward(X, Y, years)
    idx_oos = X.index[X.index.year >= FIRST_TEST]
    # ---- q_models(검증 구간 전체) · q_years(연도별)
    rows_m, rows_y = [], []
    for t, tn in TARGETS.items():
        for m in MODELS:
            p = P[t][m]
            thr = 0.5 if m == '단순 규칙' else np.nan
            if m == '단순 규칙': st = _metrics(p[idx_oos], Y.loc[idx_oos, t], 0.5)
            else:
                # 신호 문턱 = 그 해 학습 구간 기준 비율
                thr_s = pd.Series(np.nan, index=idx_oos)
                for Yv in years:
                    if Yv in BASE[t]: thr_s[idx_oos.year == Yv] = BASE[t][Yv]
                pp = p[idx_oos]; yy = Y.loc[idx_oos, t]; ok = pp.notna() & yy.notna()
                sig = pp[ok] >= thr_s[ok]; tp = int((sig & (yy[ok] == 1)).sum())
                st = dict(auc=round(float(roc_auc_score(yy[ok], pp[ok])), 3), precision=round(tp / sig.sum() * 100, 1) if sig.sum() else np.nan, recall=round(tp / (yy[ok] == 1).sum() * 100, 1),
                          base=round(float(yy[ok].mean() * 100), 1), signals=int(sig.sum()), days=int(ok.sum()))
            rows_m.append(dict(target=tn, model=m, **st))
            for Yv in years:
                ii = idx_oos[idx_oos.year == Yv]
                if not len(ii): continue
                thr_y = 0.5 if m == '단순 규칙' else BASE[t].get(Yv, 0.5)
                sy = _metrics(p[ii], Y.loc[ii, t], thr_y)
                rows_y.append(dict(year=str(Yv), target=tn, model=m, auc=sy['auc'], base=sy['base'], days=sy['days'], signals=sy['signals']))
    q_models = pd.DataFrame(rows_m)
    qy = pd.DataFrame(rows_y); q_years = []
    for Yv in years:
        g = qy[qy.year == str(Yv)]
        if not len(g): continue
        pick = lambda tn, m, col: (g[(g.target == tn) & (g.model == m)][col].iloc[0] if len(g[(g.target == tn) & (g.model == m)]) else np.nan)
        q_years.append({'year': str(Yv), 'days': int(pick('10일 상승', '부스팅', 'days')), 'base_up': pick('10일 상승', '부스팅', 'base'),
                        'auc_up_rule': pick('10일 상승', '단순 규칙', 'auc'), 'auc_up_log': pick('10일 상승', '로지스틱', 'auc'), 'auc_up_bst': pick('10일 상승', '부스팅', 'auc'),
                        'base_risk': pick('5일 내 급락·청산', '부스팅', 'base'), 'auc_risk_rule': pick('5일 내 급락·청산', '단순 규칙', 'auc'), 'auc_risk_log': pick('5일 내 급락·청산', '로지스틱', 'auc'), 'auc_risk_bst': pick('5일 내 급락·청산', '부스팅', 'auc'),
                        'train': f'{Yv - TRAIN_Y}~{Yv - 1}'})
    q_years = pd.DataFrame(q_years)
    # ---- 매매 시뮬레이션(검증 구간 2018~)
    def thr_series(t):
        s = pd.Series(np.nan, index=idx_oos)
        for Yv in years:
            if Yv in BASE[t]: s[idx_oos.year == Yv] = BASE[t][Yv]
        return s
    rule_buy = P['up10']['단순 규칙'] >= 0.5; rule_risk = P['risk5']['단순 규칙'] >= 0.5
    bst_buy = P['up10']['부스팅'] >= 0.5; bst_risk = P['risk5']['부스팅'] >= thr_series('risk5').reindex(P['risk5']['부스팅'].index)
    log_buy = P['up10']['로지스틱'] >= 0.5; log_risk = P['risk5']['로지스틱'] >= thr_series('risk5').reindex(P['risk5']['로지스틱'].index)
    strat = [('코스피 보유(비교)', None), ('단순 규칙 매수(외국인20)·위험 시 보류', (rule_buy, rule_risk, False)), ('단순 규칙 매수·위험 신호 나오면 청산', (rule_buy, rule_risk, True)),
             ('부스팅 매수·위험 시 보류', (bst_buy, bst_risk, False)), ('로지스틱 매수·위험 시 보류', (log_buy, log_risk, False))]
    rows_s = []; bst_trades = []
    cl = c.reindex(idx_oos); bh = cl.pct_change().fillna(0)
    for name, spec in strat:
        if spec is None:
            eq = (1 + bh).cumprod(); rows_s.append(dict(strategy=name, total=round((eq.iloc[-1] - 1) * 100, 2), mdd=round(((eq / eq.cummax()) - 1).min() * 100, 2),
                                                        sharpe=round(float(bh.mean() / bh.std() * np.sqrt(250)), 2), trades=1, win=np.nan, payoff=np.nan, exposure=100.0, rand_pct=np.nan)); continue
        ret, trades, pos = simulate(c, spec[0], spec[1], idx_oos, exit_on_risk=spec[2]); st = _stats(ret, trades, pos)
        st['rand_pct'] = rand_pct(c, idx_oos, len(trades), st['total']); rows_s.append(dict(strategy=name, **st))
        if name.startswith('부스팅'): bst_trades = trades
    q_strat = pd.DataFrame(rows_s)
    # ---- 민감도(단순 규칙 분위 ±10~20%)
    rows_sen = []
    for sh in (-0.2, -0.1, 0.0, 0.1, 0.2):
        qb, qr = min(0.95, max(0.05, Q_BUY * (1 + sh))), min(0.95, max(0.05, Q_RISK * (1 + sh)))
        b = pd.Series(False, index=X.index); r = pd.Series(False, index=X.index)
        for Yv in years:
            if Yv not in THR: continue
            tr = (X.index.year >= Yv - TRAIN_Y) & (X.index.year <= Yv - 1); tr_idx = X.index[tr][:-GAP]
            te = X.index.year == Yv
            b[te] = X.loc[te, 'for20'] >= X.loc[tr_idx, 'for20'].quantile(qb); r[te] = X.loc[te, 'vk'] >= X.loc[tr_idx, 'vk'].quantile(qr)
        ret, trades, pos = simulate(c, b, r, idx_oos); st = _stats(ret, trades, pos)
        rows_sen.append(dict(shift=f'{sh:+.0%}', total=st['total'], mdd=st['mdd'], sharpe=st['sharpe'], trades=st['trades'], win=st['win']))
    q_sens = pd.DataFrame(rows_sen)
    # ---- 지표 선별(IC · 거짓 발견률 · 연도별 안정성 · 국면별)
    Xf, Yf, cf, regf, Pf = X, Y, c, regime, P   # 학습엔 2006~ 전체, 표·그래프 자료는 2015~
    X, Y, c, regime = X[X.index >= YC], Y[Y.index >= YC], c[c.index >= YC], regime[regime.index >= YC]
    P = {t: {m: P[t][m][P[t][m].index >= YC] for m in P[t]} for t in P}
    rows_ic = []; pvals = []
    for k in FKEYS:
        rec = {'name': FNAME[k]}
        for n in (5, 10, 20):
            ok = X[k].notna() & Y[f'r{n}'].notna(); rho, pv = spearmanr(X.loc[ok, k], Y.loc[ok, f'r{n}'])
            rec[f'ic{n}'] = round(float(rho), 3)
            if n == 10: pvals.append(pv); rec['_n'] = int(ok.sum())
        ok = X[k].notna() & Y['r10'].notna(); same = 0; tot = 0
        for Yv, g in X[ok].groupby(X.index[ok].year):
            if len(g) < 60: continue
            rho, _ = spearmanr(g[k], Y.loc[g.index, 'r10']); tot += 1; same += int(np.sign(rho) == np.sign(rec['ic10']))
        rec['stability'] = f'{same}/{tot}'
        for rn, rk in (('상승 추세', 'ic_up'), ('하락 추세', 'ic_down'), ('고변동 청산', 'ic_hv'), ('횡보', 'ic_side')):
            okr = ok & (regime == rn)
            rec[rk] = round(float(spearmanr(X.loc[okr, k], Y.loc[okr, 'r10'])[0]), 2) if okr.sum() >= 60 else np.nan
        rows_ic.append(rec)
    # BH 보정
    pv = np.array(pvals); order = np.argsort(pv); q = np.empty(len(pv)); prev = 1.0
    for rank, i in enumerate(order[::-1]):
        val = min(prev, pv[i] * len(pv) / (len(pv) - rank)); q[i] = val; prev = val
    for rec, qq in zip(rows_ic, q): rec['q10'] = round(float(qq), 3)
    corr = X[FKEYS].corr(method='spearman').abs()
    keep = []
    for rec in sorted(rows_ic, key=lambda r: -abs(r['ic10'])):
        k = [kk for kk, nm in FEAT if nm == rec['name']][0]
        rec['rep'] = '중복' if any(corr.loc[k, j] > 0.8 for j in keep) else '대표'
        if rec['rep'] == '대표': keep.append(k)
    q_ic = pd.DataFrame(rows_ic).drop(columns=['_n']).sort_values('ic10', key=lambda s: -s.abs()).reset_index(drop=True)
    q_ic = q_ic[['name', 'ic5', 'ic10', 'ic20', 'q10', 'stability', 'ic_up', 'ic_down', 'ic_hv', 'ic_side', 'rep']]
    # ---- q_daily
    q_daily = pd.DataFrame({'date': X.index.strftime('%Y-%m-%d'), 'kospi': c.round(2).values, 'regime': regime.values,
                            'p_up': P['up10']['부스팅'].round(3).values, 'p_risk': P['risk5']['부스팅'].round(3).values})
    q_daily['trade'] = ''; q_daily['trade_ret'] = np.nan
    pos_of = {d: i for i, d in enumerate(X.index)}
    for d0, d1, r, *rest in bst_trades:
        q_daily.loc[pos_of[d0], 'trade'] = 'enter'
        if rest and rest[0]: continue                        # 보유 중인 거래는 청산 표시를 찍지 않는다(청산일은 보유 기간이 끝나는 날 확정)
        q_daily.loc[pos_of[d1], 'trade'] = 'exit'; q_daily.loc[pos_of[d1], 'trade_ret'] = round(r * 100, 2)
    q_daily['kospi_basis'] = 'KRX 원자료'
    q_daily['p_up'] = q_daily['p_up'].where(q_daily['p_up'].notna(), ''); q_daily['p_risk'] = q_daily['p_risk'].where(q_daily['p_risk'].notna(), '')
    q_daily['trade_ret'] = q_daily['trade_ret'].where(q_daily['trade_ret'].notna(), '')
    # ---- q_now
    last = X.index[-1]; ly = int(last.year); thr = THR.get(ly, {})
    pu, pr = P['up10']['부스팅'][last], P['risk5']['부스팅'][last]
    base_r = BASE['risk5'].get(ly, np.nan)
    auc_up = q_models[(q_models.target == '10일 상승') & (q_models.model == '부스팅')].auc.iloc[0]; auc_r = q_models[(q_models.target == '5일 내 급락·청산') & (q_models.model == '부스팅')].auc.iloc[0]
    q_now = pd.DataFrame([
        {'item': '국면', 'value': np.nan, 'text': regime.iloc[-1] + f" (신용 5일 {X['cr_5d'].iloc[-1]:+.1f}%, 20일 수익률 {X['ret20'].iloc[-1]:+.1f}%, 종가 {'>' if c.iloc[-1] > c.rolling(20).mean().iloc[-1] else '<'} 20일선)"},
        {'item': '10일 상승 확률(부스팅)', 'value': round(pu * 100, 1) if pd.notna(pu) else np.nan, 'text': f'{ly - TRAIN_Y}~{ly - 1}년으로 학습한 모형(2006~ 장기 자료). 2018~{ly} 검증 AUC {auc_up:.2f}' + (' — 0.5 근처라 참고만' if abs(auc_up - 0.5) < 0.05 else '')},
        {'item': '5일 내 급락·청산 확률(부스팅)', 'value': round(pr * 100, 1) if pd.notna(pr) else np.nan, 'text': f'신호 기준 {base_r * 100:.0f}%(학습 구간 기준 비율) 이상이면 위험. 검증 AUC {auc_r:.2f}' + (' — 0.5 근처라 참고만' if abs(auc_r - 0.5) < 0.05 else '')},
        {'item': '외국인 20일 순매수(조원)', 'value': round(X['for20'].iloc[-1], 2), 'text': f"매수 규칙 기준 {thr.get('for20', np.nan):+.2f} 이상이면 매수 신호 — 지금 {'켜짐' if X['for20'].iloc[-1] >= thr.get('for20', np.inf) else '꺼짐'}"},
        {'item': 'VKOSPI', 'value': round(X['vk'].iloc[-1], 2), 'text': f"위험 규칙 기준 {thr.get('vk', np.nan):.2f} 이상이면 위험 신호 — 지금 {'켜짐' if X['vk'].iloc[-1] >= thr.get('vk', np.inf) else '꺼짐'}"},
        {'item': '신용 5일 증감률(%)', 'value': round(X['cr_5d'].iloc[-1], 2), 'text': '−3% 이하면 고변동 청산 국면(VKOSPI 5일 +25% 이상도)'},
        {'item': 'VKOSPI 5일 변화율(%)', 'value': round(X['vk_5d'].iloc[-1], 2), 'text': '+25% 이상이면 고변동 청산 국면'}])
    try:
        q_attr, extra = explain(Xf, Yf, cf, regf, D)
        q_now = pd.concat([q_now, pd.DataFrame(extra)], ignore_index=True)
    except Exception as e:
        q_attr = pd.DataFrame([{'kind': 'error', 'target': '', 'text': repr(e)}])
    return dict(q_daily=q_daily, q_models=q_models, q_years=q_years, q_strat=q_strat, q_sens=q_sens, q_ic=q_ic, q_now=q_now, q_attr=q_attr)
