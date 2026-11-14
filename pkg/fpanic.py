# -*- coding: utf-8 -*-
"""fpanic.py — 외국인 투매·개인 매수 신호(2026-11-15 추가): fpanic, fpanic_eps, fpanic_now

   무엇: 시장이 크게 빠지며 외국인이 60일 내내 극단적으로 팔고 개인이 받아내는 변동성 큰 구간에서 켜지는 매수 쪽 신호. 켜진 뒤 10~15거래일 안의 반등을 본다.
   어떻게 골랐나(research/combo_search_2026-11-14): 지표 77개 × 최근 3년 백분위 조건 924개의 3조건 조합 1억 3,148만 개를 해마다 그 전 자료만으로 채점(10일 뒤 상승)해
     상위 400개에 조건 하나를 더 붙인 4조건 중 상위 10개를 그해에 쓴다. 해마다 쓴 10개는 fpanic_rules.json 에 있다(다음 해 것은 해가 바뀐 뒤 다시 뽑아 넣는다; 없으면 마지막 해 것을 쓴다).
   해마다 1월 1일에 .github/workflows/fpanic-yearly.yml 이 pkg/fpanic_select.py 로 그해 10개를 자동으로 다시 뽑는다.
   신호 = 그해 10개 중 하나라도 켜진 날. 핵심 = 그해 1위 조합이 켜진 날. 지표는 그날 장 마감 때 아는 값(금투협 신용은 전날 공시분).
   조건 표기: 지표>=pNN / 지표<=pNN = 최근 750거래일(자료 250일 이상) 안에서 오늘 값의 백분위가 NN% 이상/이하.
   검증(2018~2026 걷기 검증, 10일 뒤 상승): 110일·10묶음 80.9%(아무 날 54.3%), 묶음 8/10 평균 +. 2025~26: 27일·3묶음 77.8%(아무 날 66.7%). 표본이 적어 참고용."""
import os, json, numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
LAB = {'ret60': '60일 수익률', 'ret120': '120일 수익률', 'dd250': '1년 고점 대비', 'dd60': '60일 고점 대비', 'atr14': '변동성(ATR14/종가)', 'rv60': '60일 실현 변동성', 'for60': '외국인 60일 순매수',
       'ind60': '개인 60일 순매수', 'for20_val': '외국인 20일 순매수/거래대금', 'cr_60d': '신용 60일 증감률', 'cr_vs_high': '신용 1년 고점 대비'}
UNIT = {'for60': '조원', 'ind60': '조원'}

def features(D):
    K, F, C = D['K'], D['F'], D['C']; c, h, l = K.close, K.high, K.low; idx = c.index; r = c.pct_change(); X = pd.DataFrame(index=idx)
    X['ret60'] = c.pct_change(60) * 100; X['ret120'] = c.pct_change(120) * 100
    X['dd250'] = (c / c.rolling(250, min_periods=120).max() - 1) * 100; X['dd60'] = (c / c.rolling(60).max() - 1) * 100
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1); X['atr14'] = tr.rolling(14).mean() / c * 100
    X['rv60'] = r.rolling(60).std() * np.sqrt(250) * 100
    val = K.val / 1e6; fo, ind = F.foreign.reindex(idx) / 1000, F.indiv.reindex(idx) / 1000
    X['for60'] = fo.rolling(60).sum(); X['ind60'] = ind.rolling(60).sum(); X['for20_val'] = fo.rolling(20).sum() / val.rolling(20).sum() * 100
    cred = C.credit.reindex(idx).shift(1) / 1e6; X['cr_60d'] = cred.pct_change(60) * 100; X['cr_vs_high'] = (cred / cred.rolling(250, min_periods=60).max() - 1) * 100
    X = X.replace([np.inf, -np.inf], np.nan)
    return X, X.rolling(750, min_periods=250).rank(pct=True), c

def cond(RK, s):
    op = '>=' if '>=' in s else '<='; ft, q = s.split(op); v = RK[ft].values; q = int(q[1:]) / 100
    return (np.nan_to_num(v, nan=-1) >= q) if op == '>=' else (np.where(np.isnan(v), 2, v) <= q)

def episodes(mask, gap=10):
    g = []
    for i in np.where(mask)[0]:
        if g and i - g[-1][-1] <= gap: g[-1].append(i)
        else: g.append([i])
    return g

def run(D):
    import quant
    X, RK, c = features(quant.load_history(D)); idx = c.index; yrs = idx.year.values; N = len(idx)
    RULES = json.load(open(os.path.join(HERE, 'fpanic_rules.json'), encoding='utf-8')); ymax = max(int(k) for k in RULES)
    n10 = np.zeros(N, int); core = np.zeros(N, bool)
    for y in sorted(set(yrs[yrs >= 2018])):
        rs = RULES[str(min(int(y), ymax))]; ym = yrs == y
        S = np.stack([np.logical_and.reduce([cond(RK, s) for s in r_['conds']]) for r_ in rs], 1)
        n10[ym] = S[ym].sum(1); core[ym] = S[ym, 0]
    on = n10 > 0; fw = {h: ((c.shift(-h) / c - 1) * 100).values for h in (10, 15, 20)}
    m18 = yrs >= 2018; cur = RULES[str(min(int(yrs[-1]), ymax))][0]['conds']
    daily = pd.DataFrame({'date': idx.strftime('%Y-%m-%d'), 'kospi': c.values.round(2), 'on': on.astype(int), 'n10': n10, 'core': core.astype(int), 'r10': np.round(fw[10], 2), 'r20': np.round(fw[20], 2)})
    for s in cur:
        ft = s.split('>=')[0].split('<=')[0]; daily[ft] = X[ft].values.round(2); daily[ft + '_pct'] = (RK[ft].values * 100).round(1)
    daily = daily[m18].reset_index(drop=True)
    # 묶음(켜진 날이 10거래일 안에 이어지면 한 묶음)
    eps = []
    for g in episodes(on & m18):
        a, b = fw[10][g], fw[20][g]; ka, kb = ~np.isnan(a), ~np.isnan(b)
        eps.append(dict(start=idx[g[0]].strftime('%Y-%m-%d'), end=idx[g[-1]].strftime('%Y-%m-%d'), days=len(g), kospi=round(float(c.values[g[0]]), 2), core_days=int(core[g].sum()),
                        up10=f'{int((a[ka] > 0).sum())}/{int(ka.sum())}', avg10=round(float(np.nanmean(a)), 1) if ka.any() else '', up20=f'{int((b[kb] > 0).sum())}/{int(kb.sum())}', avg20=round(float(np.nanmean(b)), 1) if kb.any() else '',
                        status='결과 미확정' if not ka.all() else ('20일 미확정' if not kb.all() else '확정')))
    eps_df = pd.DataFrame(eps)
    def st(h, y0):
        r = fw[h]; ok = ~np.isnan(r) & (yrs >= y0); m = on & ok
        if not m.sum(): return None
        ep = [[i for i in g if ok[i]] for g in episodes(on & (yrs >= y0))]; ep = [g for g in ep if g]; w = sum(1 for g in ep if r[g].mean() > 0)
        return dict(days=int(m.sum()), eps=len(ep), wins=w, hit=round(float((r[m] > 0).mean() * 100), 1), base=round(float((r[ok] > 0).mean() * 100), 1), avg=round(float(r[m].mean()), 2), base_avg=round(float(r[ok].mean()), 2))
    rows = []; last = len(idx) - 1; md = lambda d: f'{d.month}/{d.day}'
    since = next((i for i in range(last, -1, -1) if not on[i]), -1) + 1
    state = '켜짐' if on[last] else '꺼짐'
    rows.append(('상태', int(on[last]), f"{state} — {md(idx[last])} 기준, 올해 조합 10개 중 {n10[last]}개 켜짐" + (f"(핵심 조합 {'켜짐' if core[last] else '꺼짐'})" if on[last] else '') + (f", {md(idx[since])}부터 {last - since + 1}거래일째" if on[last] else '')))
    for s in cur:
        op = '>=' if '>=' in s else '<='; ft, q = s.split(op); q = int(q[1:]); p = RK[ft].values[last] * 100; v = X[ft].values[last]; ok_ = (p >= q) if op == '>=' else (p <= q)
        rows.append((f'핵심 조건 · {LAB.get(ft, ft)}', round(float(p), 1) if not np.isnan(p) else '', f"{LAB.get(ft, ft)} {v:+.1f}{UNIT.get(ft, '%')} = 최근 3년 중 {'하위' if p <= 50 else '상위'} {min(p, 100 - p):.0f}% 위치 · 기준: {'상위 ' + str(100 - q) + '% 이내' if op == '>=' else '하위 ' + str(q) + '% 이내'} — {'맞음' if ok_ else '아님'}"))
    for nm, y0 in (('검증 2018~', 2018), ('검증 2025~', 2025)):
        for h in (10, 15, 20):
            s = st(h, y0)
            if s: rows.append((f'{nm} · {h}일 뒤 상승', s['hit'], f"{s['days']}일·{s['eps']}묶음 중 {s['hit']}% 상승(아무 날 {s['base']}%), 평균 {s['avg']:+.1f}%(아무 날 {s['base_avg']:+.1f}%), 묶음 평균이 플러스 {s['wins']}/{s['eps']}"))
    if len(eps_df): e = eps_df.iloc[-1]; rows.append(('최근 묶음', '', f"{e['start']} ~ {e['end']} · {e['days']}일 · 10일 뒤 상승 {e['up10']}" + (f" 평균 {e['avg10']:+.1f}%" if e['avg10'] != '' else '') + f" · {e['status']}"))
    rows.append(('읽는 법', '', '켜진 뒤 10~15거래일 안의 반등을 보는 매수 쪽 신호. 켜진 직후 1~2일은 더 빠지는 일이 흔했다. 30거래일 넘게는 근거가 없다. 매도·하락 쪽은 같은 탐색에서 살아남은 조합이 없었다. 표본이 10묶음뿐이라 참고용'))
    rows.append(('조합', '', '올해 1위(핵심): ' + ' · '.join(s for s in cur) + f" — {ymax}년용은 그 전 해까지 자료로 고름. 나머지 9개는 pkg/fpanic_rules.json"))
    return {'fpanic': daily, 'fpanic_eps': eps_df, 'fpanic_now': pd.DataFrame(rows, columns=['item', 'value', 'text'])}
