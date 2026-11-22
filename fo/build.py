# -*- coding: utf-8 -*-
"""미국·한국 선물옵션 대시보드 — 지표 계산과 웹판 자료 만들기(GitHub Actions 에서 실행).

입력  fo/data/*.csv (collect_us.py) · out/*.csv (main, 코스피 대시보드 수집) · deriv-research 가지의 deriv/data (KRX 로그인 자료)
출력  docs/fo/data/us_daily.csv · cftc.csv · kr_fut.csv · kr_opt.csv · us2kr_pts.csv · tables.json
원칙  원자료를 추정으로 채우지 않는다. 받지 못한 값은 빈칸으로 두고 tables.json 의 unknown(확인하지 못한 값)에 적는다.
사용  python fo/build.py --deriv _deriv/deriv/data
"""
import argparse
import datetime as dt
import glob
import json
import os
import sys
import traceback

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import model  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FD = os.path.join(ROOT, 'fo', 'data'); OUT = os.path.join(ROOT, 'docs', 'fo', 'data'); MAIN = os.path.join(ROOT, 'out')
os.makedirs(OUT, exist_ok=True)
KST = dt.timezone(dt.timedelta(hours=9))
UNKNOWN = []; T = {}


def unk(item, why): UNKNOWN.append({'id': f'u{len(UNKNOWN)}', '항목': item, '사유': why}); print('확인 불가:', item, '—', why, flush=True)
def num(s): return pd.to_numeric(s.astype(str).str.replace(',', '').str.strip().replace({'-': None, '': None, 'nan': None}), errors='coerce')
def rd(path, **kw): return pd.read_csv(path, low_memory=False, **kw) if os.path.exists(path) else None
def md(d): return f'{int(d[5:7])}/{int(d[8:10])}' if isinstance(d, str) and len(d) >= 10 else ''


def nth_wd(y, m, wd, n):
    d = dt.date(y, m, 1); d += dt.timedelta(days=(wd - d.weekday()) % 7 + 7 * (n - 1)); return d


def adj(d, days):
    """휴장이면 앞 거래일(거래일 목록 안에 있을 때만 조정, 미래 날짜는 그대로)."""
    s = d.strftime('%Y-%m-%d')
    if not len(days) or s > days[-1]: return s
    i = np.searchsorted(days, s, side='right') - 1
    return days[i] if i >= 0 else s


def clean(o):
    if isinstance(o, dict): return {k: clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)): return [clean(v) for v in o]
    if isinstance(o, (np.floating, float)): return None if (np.isnan(o) or np.isinf(o)) else round(float(o), 6)
    if isinstance(o, np.integer): return int(o)
    if isinstance(o, (pd.Timestamp, dt.date)): return str(o)[:10]
    return o


def recs(df): return clean(df.replace({np.nan: None}).to_dict('records'))


def safe(name, fn):
    try: fn()
    except Exception:
        unk(name, '계산 실패 — ' + traceback.format_exc().strip().splitlines()[-1][:160]); traceback.print_exc()


# ================================================================== 미국
def build_us():
    px = rd(os.path.join(FD, 'px.csv'))
    if px is None: raise RuntimeError('fo/data/px.csv 없음(야후 일봉 수집 실패)')
    cl = px.pivot(index='date', columns='sym', values='close'); op = px.pivot(index='date', columns='sym', values='open')
    us = pd.DataFrame(index=cl.index[cl['spx'].notna()]); us.index.name = 'date'
    for c in ('spx', 'ndx', 'qqq', 'dia', 'es', 'nq'): us[c] = cl[c] if c in cl else np.nan
    v = rd(os.path.join(FD, 'vix.csv'))
    if v is not None: us = us.join(v.set_index('date'))
    else: unk('VIX 기간구조', 'Cboe 지수 이력을 받지 못함')
    for c in ('vix9d', 'vix', 'vix3m', 'vix6m', 'vix1y'):
        if c not in us: us[c] = np.nan
    us['vix_ratio'] = us['vix'] / us['vix3m']
    pc = rd(os.path.join(FD, 'cboe_pc.csv'))
    if pc is not None:
        pc = pc.set_index('date')
        for c in ('pc_total', 'pc_index', 'pc_equity', 'pc_spx'): us[c] = pc[c] if c in pc else np.nan
        us['oi_pc'] = pc['all_oi_put'] / pc['all_oi_call'] if 'all_oi_put' in pc else np.nan
        us['spx_oi_pc'] = pc['spx_oi_put'] / pc['spx_oi_call'] if 'spx_oi_put' in pc else np.nan
        us['put_vol'] = pc.get('all_vol_put'); us['call_vol'] = pc.get('all_vol_call')
    else:
        unk('Cboe 풋/콜', 'Cboe 일별 통계를 받지 못함')
        for c in ('pc_total', 'pc_index', 'pc_equity', 'pc_spx', 'oi_pc', 'spx_oi_pc', 'put_vol', 'call_vol'): us[c] = np.nan
    for c in ('pc_total', 'pc_equity', 'pc_spx'): us[c + '_ma10'] = us[c].rolling(10, min_periods=6).mean()
    days = us.index.to_numpy()
    opex = set()
    for y in range(1999, int(days[-1][:4]) + 2):
        for m in range(1, 13): opex.add(adj(nth_wd(y, m, 4, 3), days))
    us['opex'] = [1 if d in opex else 0 for d in us.index]
    return us, sorted(opex)


def build_cftc(us):
    c = rd(os.path.join(FD, 'cftc.csv'))
    if c is None: unk('CFTC 주체별 포지션', 'CFTC 자료를 받지 못함'); return None
    for w in ('lev', 'am', 'dealer', 'small'):
        c[w + '_net'] = c[w + '_long'] - c[w + '_short']; c[w + '_sl'] = (c[w + '_short'] / c[w + '_long']).round(4)
    return c.sort_values(['mkt', 'date']).reset_index(drop=True)


def t_cftc_latest(c):
    rows = []; WHO = {'lev': '헤지펀드(레버리지 펀드)', 'am': '자산운용사', 'dealer': '딜러', 'small': '소액(비보고)'}
    for mk in ('ES', 'NQ'):
        g = c[c['mkt'] == mk]
        if len(g) < 2: continue
        a, b = g.iloc[-1], g.iloc[-2]; h = g.tail(156)
        for w, nm in WHO.items():
            share = 100 * g[w + '_net'] / g['oi']
            rows.append(dict(key=f'{mk}_{w}', mkt=mk, who=nm, date=a['date'], long=a[w + '_long'], short=a[w + '_short'], net=a[w + '_net'], net_chg=a[w + '_net'] - b[w + '_net'],
                             sl=a[w + '_sl'], sl_prev=b[w + '_sl'], net_pct_oi=share.iloc[-1], pctile_3y=100 * (h[w + '_net'] / h['oi'] <= a[w + '_net'] / a['oi']).mean()))
    T['cftc_latest'] = clean(rows)


def t_term(us):
    u = us[us['vix'].notna()]
    if not len(u): return
    i0 = len(u) - 1; i1 = max(0, i0 - 5); i2 = max(0, i0 - 21)
    T['term'] = clean([{'만기': nm, '최신': u[c].iloc[i0], '일주일전': u[c].iloc[i1], '한달전': u[c].iloc[i2], '최신일': md(u.index[i0]), '일주일전일': md(u.index[i1]), '한달전일': md(u.index[i2])}
                       for c, nm in (('vix9d', '9일'), ('vix', '30일(VIX)'), ('vix3m', '3개월'), ('vix6m', '6개월'), ('vix1y', '1년'))])


def t_opex(us, opex):
    s = us['spx'].dropna(); d = s.index.to_numpy(); c = s.to_numpy(); pos = {x: i for i, x in enumerate(d)}
    ev = [pos[e] for e in opex if e in pos and e >= '2006-01-01']
    paths = []; last = None
    for i in ev:
        if i - 10 < 0: continue
        p = [100 * (c[i + k] / c[i - 10] - 1) if 0 <= i + k < len(c) else np.nan for k in range(-10, 11)]
        if i + 10 < len(c): paths.append(p)
        last = (d[i], p)
    A = np.array(paths)
    T['us_opex_path'] = clean([dict(k=k, mean=np.nanmean(A[:, j]), median=np.nanmedian(A[:, j]), p25=np.nanpercentile(A[:, j], 25), p75=np.nanpercentile(A[:, j], 75), n=len(A),
                                    latest=last[1][j], latest_date=md(last[0])) for j, k in enumerate(range(-10, 11))])
    def st(idn, nm, x):
        x = np.array(x); x = x[~np.isnan(x)]
        return {'id': idn, '구간': nm, 'n': len(x), '평균': x.mean(), '중앙값': np.median(x), '상승비율': 100 * (x > 0).mean()}
    T['us_opex_stat'] = clean([st('w0', '만기 주(만기일까지 5거래일)', [100 * (c[i] / c[i - 5] - 1) for i in ev if i >= 5]),
                               st('d0', '만기일 하루', [100 * (c[i] / c[i - 1] - 1) for i in ev if i >= 1]),
                               st('w1', '만기 다음 주(만기일 뒤 5거래일)', [100 * (c[i + 5] / c[i] - 1) for i in ev if i + 5 < len(c)]),
                               st('all5', '아무 5거래일 구간(비교용)', [100 * (c[i] / c[i - 5] - 1) for i in range(np.searchsorted(d, '2006-01-01') + 5, len(c))])])


def t_analog(px_spx):
    s = px_spx[px_spx.index >= '2000-01-01']; c = s.to_numpy(); d = s.index.to_numpy(); r5 = np.full(len(c), np.nan); r5[5:] = 100 * (c[5:] / c[:-5] - 1)
    hit = r5 <= -8; rows = []; i = 0
    while i < len(c):
        if hit[i]:
            j = i
            while j + 1 < len(c) and (hit[j + 1] or (j + 2 < len(c) and hit[j + 2])): j += 1
            f = lambda k: 100 * (c[i + k] / c[i] - 1) if i + k < len(c) else np.nan
            rows.append({'id': d[i], '시작일': d[i], '해당일수': int(hit[i:j + 1].sum()), '그날_5일등락': r5[i], '뒤1일': f(1), '뒤5일': f(5), '뒤20일': f(20)}); i = j + 1
        else: i += 1
    cur = r5[-1]; past = [r for r in rows if not np.isnan(r['뒤20일'])]
    T['analog'] = clean(rows[-25:])
    T['analog_sum'] = clean([{'id': 'sum', '에피소드': len(rows), '일수': int(hit.sum()), '현재값': cur, '현재해당': '해당' if cur <= -8 else '해당 아님', '확정': len(past),
                              '상승_1일': sum(r['뒤1일'] > 0 for r in past), '상승_5일': sum(r['뒤5일'] > 0 for r in past), '상승_20일': sum(r['뒤20일'] > 0 for r in past)}])


# ================================================================== 한국
def build_kr(DV, px):
    cl = px.pivot(index='date', columns='sym', values='close'); op = px.pivot(index='date', columns='sym', values='open')
    # 코스피200 시가·종가: pykrx 장기 이력 → 대시보드 수집 최신 폴더 → 야후(마지막 수단)
    parts = []
    k = rd(os.path.join(DV, 'k200_long.csv'))
    if k is not None: parts.append(pd.DataFrame({'date': k['날짜'].astype(str).str[:10], 'k200_open': k['시가'], 'k200': k['종가'], 'src': 'KRX(pykrx)'}))
    for f in sorted(glob.glob(os.path.join(ROOT, 'data', 'collect', 'dashboard_*', '04_코스피200_일별.csv')))[-3:]:
        k2 = pd.read_csv(f, encoding='utf-8-sig'); parts.append(pd.DataFrame({'date': k2['날짜'].astype(str).str[:10], 'k200_open': k2['시가'], 'k200': k2['종가'], 'src': 'KRX(대시보드 수집)'}))
    if 'k200y' in cl: parts.append(pd.DataFrame({'date': cl.index, 'k200_open': op['k200y'].to_numpy(), 'k200': cl['k200y'].to_numpy(), 'src': '야후'}).dropna(subset=['k200']))
    kk = pd.concat(parts, ignore_index=True).drop_duplicates('date', keep='first').sort_values('date')
    kk = kk[(kk['date'] >= '2000-01-01') & (kk['k200'] > 0)].set_index('date')
    if (kk['src'].tail(5) == '야후').any(): unk('코스피200 최근 값의 출처', '최근 며칠은 KRX 값이 저장소에 없어 야후 값을 썼습니다: ' + ', '.join(kk.index[-5:][kk['src'].tail(5) == '야후']))
    kr = kk.copy(); days = kr.index.to_numpy()
    mk = rd(os.path.join(MAIN, 'market_daily.csv'))
    if mk is not None: mk = mk.set_index('date'); kr['kospi'] = mk['kospi']; kr['vkospi'] = mk['vkospi']
    else: kr['kospi'] = np.nan; kr['vkospi'] = np.nan; unk('코스피·VKOSPI', 'out/market_daily.csv 없음')
    kl = rd(os.path.join(DV, 'kospi_long.csv'))
    if kl is not None: kr['kospi'] = kr['kospi'].fillna(pd.Series(kl['종가'].to_numpy(), index=kl['날짜'].astype(str).str[:10]))
    if 'kospiy' in cl: kr['kospi'] = kr['kospi'].fillna(cl['kospiy'])
    # 선물 근월물(KRX) + 대시보드 수집(전 월물 합계 미결제·계약 수)
    ff = rd(os.path.join(DV, 'fut_front_daily.csv'), encoding='utf-8-sig')
    kr['fut'] = np.nan; kr['fut_oi_front'] = np.nan; kr['front_ym'] = None
    if ff is not None:
        t = ff['TRD_DD'].astype(str); ff = ff[~t.str.contains('야간')]; t = ff['TRD_DD'].astype(str)
        f2 = pd.DataFrame({'date': t.str[:10].str.replace('/', '-'), 'fut': num(ff['TDD_CLSPRC']), 'oi': num(ff['ACC_OPNINT_QTY']), 'ym': ff['ISU_NM'].astype(str).str.extract(r'(\d{6})')[0]}).drop_duplicates('date').set_index('date')
        kr['fut'] = f2['fut']; kr['fut_oi_front'] = f2['oi']; kr['front_ym'] = f2['ym']
    else: unk('선물 근월물 시세·미결제(KRX)', 'deriv-research 가지에 fut_front_daily.csv 없음')
    fd = rd(os.path.join(MAIN, 'fut_daily.csv'))
    for c in ('foreign_ct', 'inst_ct', 'indiv_ct', 'fut_oi_all'): kr[c] = np.nan
    if fd is not None:
        fd = fd.set_index('date'); kr['fut'] = kr['fut'].fillna(fd['price']); kr['fut_oi_all'] = fd['oi']
        for c in ('foreign_ct', 'inst_ct', 'indiv_ct'): kr[c] = fd[c]
    else: unk('선물 투자자별 계약 수·전 월물 미결제', 'out/fut_daily.csv 없음')
    kr['basis'] = kr['fut'] - kr['k200']; kr['basis_pct'] = 100 * kr['basis'] / kr['k200']
    # 투자자별 순매수 금액(KRX 정규장, 억원)
    for c in ('foreign_amt', 'inst_amt', 'indiv_amt'): kr[c] = np.nan
    iv_ = rd(os.path.join(DV, 'inv_daily.csv.gz'))
    if iv_ is not None:
        g = iv_[(iv_['상품'] == 'FUK2I') & (iv_['권리'] == 'ALL') & (iv_['장구분'] == '정규') & (iv_['상세'] == 'Y')].copy()
        g['date'] = g['TRD_DD'].astype(str).str[:10].str.replace('/', '-'); g = g.drop_duplicates('date').set_index('date')
        kr['foreign_amt'] = num(g['A11']) / 1e8; kr['indiv_amt'] = num(g['A09']) / 1e8; kr['inst_amt'] = sum(num(g[c]) for c in ('A01', 'A02', 'A03', 'A04', 'A05', 'A06')) / 1e8
    else: unk('선물 투자자별 순매수 금액(KRX)', 'deriv-research 가지에 inv_daily 없음')
    for u in ('ct', 'amt'):
        for w in (20, 60): kr[f'foreign_{u}_c{w}'] = kr[f'foreign_{u}'].rolling(w, min_periods=w).sum()
    kr['indiv_amt_c20'] = kr['indiv_amt'].rolling(20, min_periods=20).sum()
    # 야간선물(그날 주간 종가 → 다음 날 06:00 야간 종가)
    nf = rd(os.path.join(MAIN, 'night_fut.csv'))
    kr['night_close'] = np.nan; kr['night_pct'] = np.nan
    if nf is not None: nf = nf.drop_duplicates('date', keep='last').set_index('date'); kr['night_close'] = nf['night_close']; kr['night_pct'] = nf['night_pct']
    else: unk('야간선물', 'out/night_fut.csv 없음')
    prev_ref = kr['night_close'].shift(1).fillna(kr['fut'].shift(1)); kr['day_pct'] = 100 * (kr['fut'] / prev_ref - 1)
    m = kr.index >= '2025-06-09'
    kr['cum_night'] = np.where(m, kr['night_pct'].where(m).fillna(0).cumsum(), np.nan); kr['cum_day'] = np.where(m, kr['day_pct'].where(m).fillna(0).cumsum(), np.nan)
    fx = rd(os.path.join(MAIN, 'fx_daily.csv'))
    kr['usdkrw'] = fx.set_index('date')['usdkrw'] if fx is not None else np.nan
    if 'usdkrw' in cl: kr['usdkrw'] = kr['usdkrw'].fillna(cl['usdkrw'])
    qexp = set(); mexp = set()
    for y in range(2000, int(days[-1][:4]) + 2):
        for mth in range(1, 13):
            e = adj(nth_wd(y, mth, 3, 2), days); mexp.add(e)
            if mth % 3 == 0: qexp.add(e)
    kr['qexp'] = [1 if d in qexp else 0 for d in kr.index]; kr['mexp'] = [1 if d in mexp else 0 for d in kr.index]
    # 옵션: KRX 공표 풋/콜·내재변동성
    p = rd(os.path.join(DV, 'pcr_daily.csv'), encoding='utf-8-sig')
    kr['pcr_krx'] = pd.Series(num(p['PCRATIO']).to_numpy(), index=p['TRD_DD'].astype(str).str[:10].str.replace('/', '-')).groupby(level=0).first() if p is not None else np.nan
    v = rd(os.path.join(DV, 'iv_daily.csv'), encoding='utf-8-sig')
    kr['iv_rep'] = pd.Series(num(v['REP_IMP_VOLT']).to_numpy(), index=v['BAS_DD'].astype(str).str[:10].str.replace('/', '-')).groupby(level=0).first() if v is not None else np.nan
    if p is None: unk('KRX 공표 풋/콜', 'deriv-research 가지에 pcr_daily.csv 없음')
    return kr, sorted(mexp), sorted(qexp)


def wk_expiry(code, wd, days):
    """'2611W4' → 그 달 n번째 목요일(월요일 위클리는 n번째 월요일). 규칙으로 계산한 날짜."""
    try: y, m, n = 2000 + int(code[:2]), int(code[2:4]), int(code[5:]); return adj(nth_wd(y, m, wd, n), days)
    except Exception: return ''


def build_chain(DV, kr, mexp):
    days = kr.index.to_numpy()
    cx = rd(os.path.join(DV, 'opt_chainx_daily.csv.gz'))
    kr['m_pcoi'] = np.nan; kr['all_pcv_ma5'] = np.nan
    if cx is None: unk('코스피200 옵션 행사가별 미결제', 'deriv-research 가지에 opt_chainx_daily 없음'); return
    cx = cx[cx['날짜'] >= '2015-01-01'].copy(); cx['ym'] = cx['ym'].astype(str).str[:6]
    exp_of = {ym: adj(nth_wd(int(ym[:4]), int(ym[4:]), 3, 2), days) for ym in cx['ym'].unique()}
    cx['expd'] = cx['ym'].map(exp_of); live = cx[cx['expd'] >= cx['날짜']]
    front = live.groupby('날짜')['ym'].min().rename('fym'); live = live.join(front, on='날짜')
    f = live[live['ym'] == live['fym']].groupby(['날짜', 'cp'])['oi'].sum().unstack(); kr['m_pcoi'] = f['P'] / f['C']
    vol = cx.groupby(['날짜', 'cp'])['vol'].sum().unstack().reindex(columns=['C', 'P']).fillna(0)
    wk = {}
    for nm, wd, lab in (('opt_chainwt_daily.csv.gz', 3, '위클리(목)'), ('opt_chainwm_daily.csv.gz', 0, '위클리(월)')):
        w = rd(os.path.join(DV, nm))
        if w is None: unk(f'{lab} 옵션 행사가별', f'deriv-research 가지에 {nm} 없음'); continue
        w['code'] = w['exp'].astype(str).str.extract(r'(\d{4}W\d)')[0]; wk[lab] = (w, wd)
        vol = vol.add(w.groupby(['날짜', 'cp'])['vol'].sum().unstack().reindex(columns=['C', 'P']).fillna(0), fill_value=0)
    kr['all_pcv_ma5'] = (vol['P'] / vol['C'].replace(0, np.nan)).rolling(5, min_periods=3).mean()
    # 가장 최근 날의 행사가별 표
    D = cx['날짜'].max(); alld = sorted(cx['날짜'].unique()); Dp = alld[-2] if len(alld) > 1 else None
    spot = float(cx.loc[cx['날짜'] == D, 'spot'].median()); strike = []; top = []

    def one(idn, label, expd, cur, prev):
        a = cur.pivot_table(index='K', columns='cp', values=['oi', 'vol'], aggfunc='sum').fillna(0)
        if a.empty or ('oi', 'C') not in a or ('oi', 'P') not in a: return
        b = prev.pivot_table(index='K', columns='cp', values='oi', aggfunc='sum').reindex(a.index) if prev is not None and len(prev) else None
        Ks = a.index.to_numpy(float); oc = a[('oi', 'C')].to_numpy(); opu = a[('oi', 'P')].to_numpy()
        pain = [(oc * np.maximum(k - Ks, 0)).sum() + (opu * np.maximum(Ks - k, 0)).sum() for k in Ks]
        for j, K in enumerate(Ks):
            strike.append(dict(exp=label, K=K, oi_C=oc[j], oi_P=opu[j], vol_C=a[('vol', 'C')].iloc[j], vol_P=a[('vol', 'P')].iloc[j],
                               doi_C=None if b is None or 'C' not in b or np.isnan(b['C'].iloc[j]) else oc[j] - b['C'].iloc[j], doi_P=None if b is None or 'P' not in b or np.isnan(b['P'].iloc[j]) else opu[j] - b['P'].iloc[j]))
        top.append({'id': idn, '만기': label, '만기일': expd, '콜미결제': oc.sum(), '풋미결제': opu.sum(), '풋콜_미결제': opu.sum() / oc.sum() if oc.sum() else None, '맥스페인': Ks[int(np.argmin(pain))],
                    '콜집중1': Ks[int(np.argmax(oc))], '콜집중1_미결제': oc.max(), '풋집중1': Ks[int(np.argmax(opu))], '풋집중1_미결제': opu.max(), '코스피200': spot, '기준일': D})
    cur = cx[cx['날짜'] == D]; yms = sorted(y for y in cur['ym'].unique() if exp_of[y] >= D)[:2]
    for n_, ym in enumerate(yms):
        one(f'm{n_ + 1}', f'월물 {ym[:4]}-{ym[4:]}', exp_of[ym], cur[cur['ym'] == ym], cx[(cx['날짜'] == Dp) & (cx['ym'] == ym)] if Dp else None)
    for lab, (w, wd) in wk.items():
        Dw = w['날짜'].max()
        if Dw != D: unk(f'{lab} 행사가별 미결제', f'마지막 수집일 {Dw} — 월물 기준일 {D} 과 달라 표에서 뺌'); continue
        c2 = w[w['날짜'] == Dw]; codes = [(wk_expiry(c, wd, days), c) for c in c2['code'].dropna().unique()]; codes = sorted(x for x in codes if x[0] and x[0] >= D)
        if not codes: continue
        e, code = codes[0]; wd_all = sorted(w['날짜'].unique()); pw = wd_all[-2] if len(wd_all) > 1 else None
        one('wt' if wd == 3 else 'wm', f'{lab} {code}', e, c2[c2['code'] == code], w[(w['날짜'] == pw) & (w['code'] == code)] if pw else None)
    T['kr_strike'] = clean(strike); T['kr_strike_top'] = clean(top)


def t_roll(DV, kr, qexp):
    days = kr.index.to_numpy(); pos = {d: i for i, d in enumerate(days)}
    r = rd(os.path.join(DV, 'fut_roll_daily.csv.gz'))
    if r is not None:
        r['ym'] = r['ym'].astype(str).str[:6]; rows = []
        for e in qexp:
            if e not in pos or e > days[-1]: continue
            ym = e[:4] + e[5:7]; g = r[(r['날짜'] <= e) & (r['날짜'] >= days[max(0, pos[e] - 15)])]
            if not len(g): continue
            tot = g.groupby('날짜')['oi'].sum(); fr = g[g['ym'] == ym].groupby('날짜')['oi'].sum()
            for d in tot.index:
                if d in pos and tot[d] > 0 and d in fr.index: rows.append((e, pos[e] - pos[d], 100 * (1 - fr[d] / tot[d])))
        if rows:
            R = pd.DataFrame(rows, columns=['e', 'dte', 's']); last_e = R['e'].max(); g = R.groupby('dte')['s']
            o = pd.DataFrame({'mean': g.mean(), 'p25': g.quantile(0.25), 'p75': g.quantile(0.75), 'n': R['e'].nunique()}).reset_index()
            o = o.merge(R[R['e'] == last_e][['dte', 's']].rename(columns={'s': 'last'}), on='dte', how='left'); o['last_label'] = last_e[:7] + ' 만기'
            T['kr_roll'] = recs(o)
    else: unk('선물 롤오버 과거 경로', 'deriv-research 가지에 fut_roll_daily 없음')
    L = days[-1]; nxt = None; y = int(L[:4])
    for yy in (y, y + 1):
        for m in (3, 6, 9, 12):
            e = nth_wd(yy, m, 3, 2).strftime('%Y-%m-%d')
            if e >= L and nxt is None: nxt = e
    if nxt:
        ym = nxt[:4] + nxt[5:7]; g = kr[(kr['front_ym'] == ym) & kr['fut_oi_front'].notna() & kr['fut_oi_all'].notna()].tail(25)
        T['kr_roll_cur'] = clean([dict(date=d, md=md(d), dte=int(np.busday_count(d, nxt)), front_oi=x['fut_oi_front'], all_oi=x['fut_oi_all'], next_share=100 * (1 - x['fut_oi_front'] / x['fut_oi_all']), expiry=nxt)
                                  for d, x in g.iterrows() if x['fut_oi_all'] >= x['fut_oi_front'] > 0])
        if not T['kr_roll_cur']: unk('이번 분기물 롤오버', 'KRX 근월물 미결제와 전 월물 미결제가 함께 있는 날이 없음')


def t_events(kr, us):
    L = kr.index[-1]; a = (pd.Timestamp(L) - pd.Timedelta(days=10)).date(); b = (pd.Timestamp(L) + pd.Timedelta(days=45)).date(); rows = []
    for y in {a.year, b.year}:
        for m in range(1, 13):
            e = nth_wd(y, m, 3, 2); rows.append((e, '한국', '선물·옵션 동시만기(분기)' if m % 3 == 0 else '옵션 월물 만기', '매월 둘째 목요일'))
            e = nth_wd(y, m, 4, 3); rows.append((e, '미국', '분기 동시만기' if m % 3 == 0 else '월간 옵션 만기', '매월 셋째 금요일'))
            for n in (1, 3, 4, 5):
                e = nth_wd(y, m, 3, n)
                if e.month == m: rows.append((e, '한국', '위클리 옵션(목) 만기', '둘째 주를 뺀 매주 목요일'))
            for n in (1, 2, 3, 4, 5):
                e = nth_wd(y, m, 0, n)
                if e.month == m: rows.append((e, '한국', '위클리 옵션(월) 만기', '매주 월요일'))
    rows = sorted(r for r in rows if a <= r[0] <= b and (r[2].find('위클리') < 0 or abs((r[0] - pd.Timestamp(L).date()).days) <= 9))
    T['events'] = [{'id': f'e{i}', 'date': str(r[0]), 'market': r[1], 'kind': r[2], 'note': r[3] + '(휴장이면 앞 거래일)', '지남': '지남' if str(r[0]) <= L else '예정'} for i, r in enumerate(rows)]


# ================================================================== 미국 → 한국
def overnight(kd, U, C):
    """한국 거래일 D 종가 뒤 ~ 다음 한국 개장 전 사이에 끝난 미국 장들의 누적 등락(%). 마지막 날은 지금까지 끝난 미국 장 전부."""
    nxt = np.append(kd[1:], '9999-12-31'); lo = np.searchsorted(U, kd, 'left'); hi = np.searchsorted(U, nxt, 'left')
    out = np.full(len(kd), np.nan); ok = (hi > lo) & (lo >= 1); out[ok] = 100 * (C[hi[ok] - 1] / C[lo[ok] - 1] - 1); return out


def t_us2kr(kr, pxc):
    kd = kr.index.to_numpy(); s = pxc['spx'].dropna(); vx = pxc['vix'].dropna() if 'vix' in pxc else None
    on = overnight(kd, s.index.to_numpy(), s.to_numpy())
    d = pd.DataFrame({'P': kd[:-1], 'date': kd[1:], 'us_on': on[:-1], 'gap': 100 * (kr['k200_open'].to_numpy()[1:] / kr['k200'].to_numpy()[:-1] - 1), 'c2c': 100 * (kr['k200'].to_numpy()[1:] / kr['k200'].to_numpy()[:-1] - 1),
                      'intra': 100 * (kr['k200'].to_numpy()[1:] / kr['k200_open'].to_numpy()[1:] - 1), 'night': kr['night_pct'].to_numpy()[:-1], 'own': 100 * kr['k200'].pct_change().to_numpy()[:-1]})
    d = d[(d['date'] >= '2000-01-10') & d['us_on'].notna()]
    d.loc[d['gap'].abs() > 15, ['gap', 'intra']] = np.nan            # 시가가 0 등으로 잘못 들어온 날
    now_on = on[-1]; own_now = 100 * (kr['k200'].iloc[-1] / kr['k200'].iloc[-2] - 1)
    vix_on = np.nan
    if vx is not None:
        v = overnight(kd, vx.index.to_numpy(), vx.to_numpy()); vix_on = v[-1]
    T['us2kr_now'] = clean([dict(id='now', kr_date=kd[-1], kr_md=md(kd[-1]), us_on=now_on, vix_on=vix_on, k200_day=own_now, night=kr['night_pct'].iloc[-1], have='있음' if not np.isnan(now_on) else '아직 없음')])
    bins = [(-99, -3, '−3% 이하'), (-3, -1.5, '−3 ~ −1.5%'), (-1.5, -0.5, '−1.5 ~ −0.5%'), (-0.5, 0.5, '−0.5 ~ +0.5%'), (0.5, 1.5, '+0.5 ~ +1.5%'), (1.5, 3, '+1.5 ~ +3%'), (3, 99, '+3% 이상')]
    rows = []
    for i, (a, b, nm) in enumerate(bins):
        g = d[(d['us_on'] > a) & (d['us_on'] <= b)]
        rows.append({'id': f'b{i}', '구간': nm, 'n': len(g), '야간선물_평균': g['night'].mean(), '시초가_평균': g['gap'].mean(), '종가_평균': g['c2c'].mean(), '종가_상승비율': 100 * (g['c2c'] > 0).mean(),
                     '장중_평균': g['intra'].mean(), '장중_상승비율': 100 * (g['intra'].dropna() > 0).mean(), '현재표시': '← 이번' if (not np.isnan(now_on) and a < now_on <= b) else ''})
    T['us2kr'] = clean(rows)
    reg = []
    for k, nm in (('gap', '코스피200 시초가'), ('c2c', '코스피200 종가'), ('intra', '코스피200 장중(시가→종가)'), ('night', '야간선물')):
        g = d[['us_on', k, 'date']].dropna()
        if len(g) < 30: continue
        b1, b0 = np.polyfit(g['us_on'], g[k], 1); r = np.corrcoef(g['us_on'], g[k])[0, 1]
        reg.append({'id': k, '대상': nm, 'n': len(g), '기울기': b1, '절편': b0, '상관': r, '설명력': 100 * r * r, '기간': f'{g["date"].min()[:7]} ~ {g["date"].max()[:7]}'})
    T['us2kr_reg'] = clean(reg)
    x = []
    for idn, nm, g in (('x0', '간밤 S&P500 −3% 이하(전체)', d[d['us_on'] <= -3]), ('x1', '그 가운데 그날 코스피200이 이미 −3% 이하로 내렸던 날', d[(d['us_on'] <= -3) & (d['own'] <= -3)]),
                       ('x2', '그 가운데 그날 코스피200이 −3%보다 덜 내렸거나 올랐던 날', d[(d['us_on'] <= -3) & (d['own'] > -3)])):
        n = len(g); up = int((g['c2c'] > 0).sum()); here = (not np.isnan(now_on)) and now_on <= -3 and (idn == 'x0' or (idn == 'x1') == (own_now <= -3))
        x.append({'id': idn, '조건': nm, 'n': n, '상승일수': up, '종가_상승비율': 100 * up / n if n >= 10 else None, '판정': '' if n >= 10 else '표본 부족', '시초가_평균': g['gap'].mean(), '장중_평균': g['intra'].mean(), '현재': '← 이번' if here else ''})
    T['us2kr_x'] = clean(x)
    cut = (pd.Timestamp(kd[-1]) - pd.DateOffset(years=5)).strftime('%Y-%m-%d'); pts = d[(d['date'] >= cut) | (d['us_on'].abs() >= 2.5)][['date', 'us_on', 'gap', 'c2c', 'intra', 'night']]
    pts.round(3).to_csv(os.path.join(OUT, 'us2kr_pts.csv'), index=False)
    return on


def t_xcorr(us, kr, cf):
    rows = []
    def add(target, ind, x, r, lags, unit):
        x = np.asarray(x, float); r = np.asarray(r, float)
        for lag in lags:
            a = x[:len(x) - lag] if lag > 0 else x[-lag:] if lag < 0 else x; b = r[lag:] if lag > 0 else r[:len(r) + lag] if lag < 0 else r
            ok = ~np.isnan(a) & ~np.isnan(b)
            if ok.sum() >= 100: rows.append(dict(target=target, indicator=ind + unit, lag=lag, corr=float(np.corrcoef(a[ok], b[ok])[0, 1]), n=int(ok.sum())))
    L = range(-5, 6); r = us['spx'].pct_change().to_numpy() * 100; rq = (us['ndx'] if us['ndx'].notna().sum() > 500 else us['qqq']).pct_change().to_numpy() * 100
    add('S&P500', 'VIX 변화', us['vix'].diff(), r, L, ''); add('S&P500', 'Cboe 풋/콜 전체', us['pc_total'], r, L, ''); add('S&P500', 'Cboe 풋/콜 개별주식', us['pc_equity'], r, L, '')
    add('나스닥100', 'VIX÷VIX3M 변화', us['vix_ratio'].diff(), rq, L, '')
    if cf is not None:
        for mk, tg, col in (('ES', 'S&P500', 'spx'), ('NQ', '나스닥100', 'ndx' if us['ndx'].notna().sum() > 500 else 'qqq')):
            g = cf[cf['mkt'] == mk].set_index('date'); w = us[col].reindex(g.index, method='ffill')
            add(tg, f'헤지펀드 {mk} 순포지션 변화', g['lev_net'].diff(), w.pct_change().to_numpy() * 100, range(-4, 5), '(주 단위)')
    rk = kr['k200'].pct_change().to_numpy() * 100; k8 = kr.index >= '2008-01-01'
    for nm, x in (('외국인 선물 순매수(억원)', kr['foreign_amt']), ('베이시스 변화', kr['basis'].diff()), ('KRX 풋/콜(월물 거래량)', kr['pcr_krx']), ('VKOSPI 변화', kr['vkospi'].diff()), ('원/달러 변화', kr['usdkrw'].pct_change() * 100)):
        add('코스피200', nm, x.to_numpy()[k8], rk[k8], L, '')
    T['link_xcorr'] = clean(rows)


# ================================================================== 방향 확률
US_NAMES = {'r1': '그날 등락(%)', 'r5': '5거래일 등락(%)', 'r20': '20거래일 등락(%)', 'dd': '1년 고점 대비(%)', 'vix': 'VIX', 'vix_chg5': 'VIX 5거래일 변화', 'vix_ratio': 'VIX÷VIX3M',
            'pc_total_ma10': '풋/콜 전체(10일 평균)', 'pc_equity_ma10': '풋/콜 개별주식(10일 평균)', 'lev_net_oi': '헤지펀드 순포지션÷미결제(%)', 'lev_net_chg4': '헤지펀드 순포지션 4주 변화÷미결제(%)', 'am_net_oi': '자산운용사 순포지션÷미결제(%)'}
KR_NAMES = {'us_on': '간밤 S&P500 등락(%)', 'ndx_on': '간밤 나스닥100 등락(%)', 'vix_on': '간밤 VIX 변화율(%)', 'r1': '그날 코스피200 등락(%)', 'r5': '5거래일 등락(%)', 'r20': '20거래일 등락(%)', 'dd': '1년 고점 대비(%)',
            'vkospi': 'VKOSPI', 'vkospi_chg5': 'VKOSPI 5거래일 변화', 'basis_pct': '베이시스÷현물(%)', 'foreign_amt': '외국인 선물 순매수(억원)', 'foreign_amt_c20': '외국인 선물 20일 누적(억원)',
            'indiv_amt_c20': '개인 선물 20일 누적(억원)', 'pcr_krx': 'KRX 풋/콜(월물 거래량)', 'usdkrw_chg5': '원/달러 5거래일 변화(%)'}


def price_feats(c):
    f = pd.DataFrame(index=c.index); f['r1'] = 100 * c.pct_change(); f['r5'] = 100 * c.pct_change(5); f['r20'] = 100 * c.pct_change(20); f['dd'] = 100 * (c / c.rolling(252, min_periods=60).max() - 1); return f


def run_model(us, kr, cf, pxc):
    parts = []; ndx_col = 'ndx' if us['ndx'].notna().sum() > 2000 else 'qqq'
    u = us[us.index >= '2007-01-03']
    for tkey, tname, col, mk in (('spx', 'S&P500', 'spx', 'ES'), ('ndx', '나스닥100', ndx_col, 'NQ')):
        c = u[col].dropna(); X = price_feats(us[col].dropna()).reindex(c.index)
        X['vix'] = u['vix']; X['vix_chg5'] = us['vix'].diff(5); X['vix_ratio'] = u['vix_ratio']; X['pc_total_ma10'] = u['pc_total_ma10']; X['pc_equity_ma10'] = u['pc_equity_ma10']
        if cf is not None:
            g = cf[cf['mkt'] == mk].copy(); g['avail'] = (pd.to_datetime(g['date']) + pd.Timedelta(days=3)).dt.strftime('%Y-%m-%d')   # 화요일 기준 → 금요일 공표
            g['lev_net_oi'] = 100 * g['lev_net'] / g['oi']; g['lev_net_chg4'] = 100 * g['lev_net'].diff(4) / g['oi']; g['am_net_oi'] = 100 * g['am_net'] / g['oi']
            g = g.sort_values('avail'); ix = np.searchsorted(g['avail'].to_numpy(), c.index.to_numpy(), 'right') - 1
            for k in ('lev_net_oi', 'lev_net_chg4', 'am_net_oi'): X[k] = np.where(ix >= 0, g[k].to_numpy()[np.clip(ix, 0, None)], np.nan)
        print('모형', tname, len(X), '일', flush=True)
        parts.append(model.run_target(tkey, tname, X[[k for k in US_NAMES if k in X]], c.to_numpy(), US_NAMES, md(c.index[-1]) + ' 종가'))
    k = kr[kr.index >= '2008-01-02']; kd = k.index.to_numpy(); X = price_feats(kr['k200']).reindex(k.index)
    s = pxc['spx'].dropna(); X['us_on'] = overnight(kd, s.index.to_numpy(), s.to_numpy())
    q = pxc[ndx_col].dropna(); X['ndx_on'] = overnight(kd, q.index.to_numpy(), q.to_numpy())
    if 'vix' in pxc: v = pxc['vix'].dropna(); X['vix_on'] = overnight(kd, v.index.to_numpy(), v.to_numpy())
    X['vkospi'] = k['vkospi']; X['vkospi_chg5'] = kr['vkospi'].diff(5); X['basis_pct'] = k['basis_pct']; X['usdkrw_chg5'] = 100 * kr['usdkrw'].pct_change(5)
    stale = []
    for c_ in ('foreign_amt', 'foreign_amt_c20', 'indiv_amt_c20', 'pcr_krx'):
        last = k[c_].last_valid_index(); X[c_] = k[c_].ffill(limit=3)
        if last is not None and last < kd[-1]: stale.append(f'{KR_NAMES[c_]} {md(last)}')
    if stale: unk('한국 모형 지표 가운데 최신일이 아닌 것', '마지막 값을 최대 3거래일 그대로 썼습니다 — ' + ', '.join(stale) + ' (KRX 자료 이어받기가 돌면 채워집니다)')
    print('모형 코스피200', len(X), '일', flush=True)
    asof = md(kd[-1]) + ' 종가' + (' + 그 뒤 끝난 미국 장' if not np.isnan(X['us_on'].iloc[-1]) else '')
    parts.append(model.run_target('k200', '코스피200', X[[c_ for c_ in KR_NAMES if c_ in X]], k['k200'].to_numpy(), KR_NAMES, asof))
    # 한 줄 규칙(간밤 S&P500 부호)의 보류 구간 적중률
    c = k['k200'].to_numpy(); y = (c[1:] > c[:-1]).astype(float); on = X['us_on'].to_numpy()[:-1]; b = int(len(y) * 0.8); ok = ~np.isnan(on[b:]) & (on[b:] != 0)
    import sklearn
    T.update(model.finish(parts, dict(rule_acc=float(100 * np.mean((on[b:][ok] > 0) == (y[b:][ok] > 0))), rule_n=int(ok.sum()), ndx_src='나스닥100 지수' if ndx_col == 'ndx' else 'QQQ ETF(지수 이력을 받지 못함)',
                                      versions=f'pandas {pd.__version__} · numpy {np.__version__} · scikit-learn {sklearn.__version__}')))


# ================================================================== 최근 일주일 · 자료 설명
def t_week(us, kr, cf):
    ud = us.index[-6:]; kdd = kr.index[-6:]; dates = sorted(set(ud) | set(kdd))[-7:]; rows = []
    up = us.pct_change() * 100
    for d in dates:
        r = {'date': d, 'md': md(d)}
        if d in us.index:
            r.update(spx=us.at[d, 'spx'], spx_pct=up.at[d, 'spx'], qqq_pct=up.at[d, 'qqq'], dia_pct=up.at[d, 'dia'], es=us.at[d, 'es'], nq=us.at[d, 'nq'], vix=us.at[d, 'vix'], pc_total=us.at[d, 'pc_total'], pc_spx=us.at[d, 'pc_spx'])
        if d in kr.index:
            x = kr.loc[d]; i = kr.index.get_loc(d)
            r.update(kospi=x['kospi'], kospi_pct=100 * (x['kospi'] / kr['kospi'].iloc[i - 1] - 1), k200=x['k200'], fut=x['fut'], basis=x['basis'], night_pct=x['night_pct'], foreign_ct=x['foreign_ct'], inst_ct=x['inst_ct'],
                     indiv_ct=x['indiv_ct'], fut_oi_all=x['fut_oi_all'], pcr_krx=x['pcr_krx'], vkospi=x['vkospi'])
        rows.append(r)
    T['week'] = clean(rows)
    L = us.index[-1]; i = len(us) - 1; s = us['spx']; hi = s.iloc[-252:]; ytd0 = us[us.index < L[:4] + '-01-01']
    q = us['ndx'] if us['ndx'].notna().sum() > 500 else us['qqq']
    streak = 0
    while streak < 30 and s.iloc[-1 - streak] < s.iloc[-2 - streak]: streak += 1
    w = dict(id='sum', us_asof=md(L), spx_asof=md(L), spx=s.iloc[-1], spx_day=up['spx'].iloc[-1], spx_week=100 * (s.iloc[-1] / s.iloc[-6] - 1), spx_high_date=md(hi.idxmax()), spx_dd=100 * (s.iloc[-1] / hi.max() - 1), spx_streak=streak,
             dia_day=up['dia'].iloc[-1], dia_week=100 * (us['dia'].iloc[-1] / us['dia'].iloc[-6] - 1), qqq_day=100 * (q.iloc[-1] / q.iloc[-2] - 1), qqq_week=100 * (q.iloc[-1] / q.iloc[-6] - 1),
             qqq_ytd=100 * (q.iloc[-1] / q.reindex(ytd0.index).dropna().iloc[-1] - 1) if len(ytd0) else None, qqq_dd=100 * (q.iloc[-1] / q.iloc[-252:].max() - 1),
             pc_total=us['pc_total'].iloc[-1], pc_index=us['pc_index'].iloc[-1], pc_equity=us['pc_equity'].iloc[-1], pc_spx=us['pc_spx'].iloc[-1], pc_spx_prev=us['pc_spx'].iloc[-2],
             pc_asof=md(us['pc_total'].last_valid_index()) if us['pc_total'].notna().any() else '', put_vol_m=us['put_vol'].iloc[-1] / 1e6 if 'put_vol' in us else None, call_vol_m=us['call_vol'].iloc[-1] / 1e6 if 'call_vol' in us else None,
             vix=us['vix'].iloc[-1], vix_week_ago=us['vix'].iloc[-6], vix_ratio=us['vix_ratio'].iloc[-1], opex_today='(이날은 미국 월간 옵션 만기일)' if us['opex'].iloc[-1] else '')
    if cf is not None:
        for mk in ('ES', 'NQ'):
            g = cf[cf['mkt'] == mk]
            if len(g) > 1:
                a, b = g.iloc[-1], g.iloc[-2]; p = mk.lower()
                w.update({f'{p}_lev_sl': a['lev_sl'], f'{p}_lev_sl_prev': b['lev_sl'], f'{p}_lev_net': a['lev_net'], f'{p}_lev_net_prev': b['lev_net'], f'{p}_lev_short_chg': a['lev_short'] - b['lev_short'], f'{p}_lev_long_chg': a['lev_long'] - b['lev_long'], 'cftc_asof': md(a['date'])})
    K = kr.index[-1]; x = kr.iloc[-1]; k5 = kr.tail(5)
    lastv = lambda c: (kr[c].dropna().iloc[-1], md(kr[c].last_valid_index())) if kr[c].notna().any() else (None, '')
    w.update(k200_asof=md(K), kr_asof=md(K), kospi=x['kospi'], kospi_day=100 * (x['kospi'] / kr['kospi'].iloc[-2] - 1), k200=x['k200'], k200_day=100 * (x['k200'] / kr['k200'].iloc[-2] - 1), kospi_week=100 * (x['kospi'] / kr['kospi'].iloc[-6] - 1),
             k200_week=100 * (x['k200'] / kr['k200'].iloc[-6] - 1), night=lastv('night_close')[0], night_pct=lastv('night_pct')[0], night_asof=lastv('night_pct')[1], foreign_ct_week=k5['foreign_ct'].sum(min_count=1), inst_ct_week=k5['inst_ct'].sum(min_count=1),
             indiv_ct_week=k5['indiv_ct'].sum(min_count=1), vkospi=lastv('vkospi')[0], vkospi_asof=lastv('vkospi')[1], basis=lastv('basis')[0], basis_asof=lastv('basis')[1])
    T['week_sum'] = clean([w])


def t_sources(us, kr, cf):
    st = json.load(open(os.path.join(FD, 'status.json'), encoding='utf-8')) if os.path.exists(os.path.join(FD, 'status.json')) else {}
    lv = lambda df, c: (df[c].last_valid_index() or '') if c in df and df[c].notna().any() else '없음'
    fv = lambda df, c: (df[c].first_valid_index() or '')[:7] if c in df and df[c].notna().any() else ''
    R = [('S&P500·나스닥100·QQQ·DIA 종가', '야후 일봉', lv(us, 'spx'), fv(us, 'spx') + '~', '화~토 07:47 · 월~금 19:17', st.get('px', {}).get('note', '')),
         ('ES·NQ 선물(근월물 연속)', '야후 일봉', lv(us, 'es'), fv(us, 'es') + '~', '위와 같음', ''),
         ('CFTC 주체별 포지션(ES·NQ, 선물만)', 'CFTC Traders in Financial Futures', cf['date'].max() if cf is not None else '없음', (cf['date'].min()[:7] + '~') if cf is not None else '', '매주 금요일 공표(화요일 기준)', st.get('cftc', {}).get('note', '')),
         ('Cboe 풋/콜(전체·지수·개별주식·SPX)', 'Cboe 일별 시장 통계', lv(us, 'pc_total'), fv(us, 'pc_total') + '~', '거래일마다', 'SPX는 ' + fv(us, 'pc_spx') + '~'),
         ('Cboe 미결제약정 풋÷콜', 'Cboe 일별 시장 통계', lv(us, 'oi_pc'), fv(us, 'oi_pc') + '~', '거래일마다', ''),
         ('VIX 기간구조(9일~1년)', 'Cboe 지수 이력', lv(us, 'vix'), fv(us, 'vix') + '~', '거래일마다', st.get('vix', {}).get('note', '')),
         ('코스피200 지수', 'KRX(pykrx·대시보드 수집), 없으면 야후', kr.index[-1], kr.index[0][:7] + '~', '거래일마다', '마지막 값 출처: ' + str(kr['src'].iloc[-1])),
         ('코스피200 선물 근월물 종가·미결제', 'KRX 정보데이터시스템(로그인)', lv(kr, 'fut_oi_front'), fv(kr, 'fut_oi_front') + '~', '월~금 19:17(KRX 이어받기)', ''),
         ('선물 투자자별 순매수 금액(정규장)', 'KRX 정보데이터시스템(로그인)', lv(kr, 'foreign_amt'), fv(kr, 'foreign_amt') + '~', '월~금 19:17', ''),
         ('선물 투자자별 계약 수·전 월물 미결제', '코스피 대시보드 수집(out/fut_daily.csv)', lv(kr, 'foreign_ct'), fv(kr, 'foreign_ct') + '~', '코스피 대시보드 갱신 때', ''),
         ('야간선물', '코스피 대시보드 수집(out/night_fut.csv)', lv(kr, 'night_pct'), fv(kr, 'night_pct') + '~', '코스피 대시보드 아침 갱신 때', '날짜 = 주간 세션일(야간은 다음 날 06:00 마감)'),
         ('KRX 공표 풋/콜·대표 내재변동성', 'KRX 정보데이터시스템(로그인)', lv(kr, 'pcr_krx'), fv(kr, 'pcr_krx') + '~', '월~금 19:17', ''),
         ('옵션 행사가별 미결제(월물·위클리)', 'KRX 정보데이터시스템(로그인)', lv(kr, 'm_pcoi'), fv(kr, 'm_pcoi') + '~', '월~금 19:17', '월물 4개·지수 ±25%, 위클리 ±20% 범위만 저장'),
         ('VKOSPI·코스피', '코스피 대시보드 수집(out/market_daily.csv)', lv(kr, 'vkospi'), fv(kr, 'vkospi') + '~', '코스피 대시보드 갱신 때', ''),
         ('원/달러', '코스피 대시보드 수집, 없으면 야후', lv(kr, 'usdkrw'), fv(kr, 'usdkrw') + '~', '거래일마다', '')]
    T['sources'] = [{'id': f's{i}', '지표': r[0], '출처': r[1], '기준': r[2], '기간': r[3], '갱신': r[4], '비고': r[5]} for i, r in enumerate(R)]
    K = kr.index[-1]
    for c, nm in (('fut_oi_front', '선물 근월물 미결제(KRX)'), ('foreign_amt', '선물 투자자별 순매수 금액(KRX)'), ('pcr_krx', 'KRX 공표 풋/콜'), ('iv_rep', '대표 내재변동성'), ('m_pcoi', '옵션 행사가별 미결제'), ('foreign_ct', '선물 투자자별 계약 수'), ('vkospi', 'VKOSPI')):
        l = lv(kr, c)
        if l != K: unk(f'{nm}의 {md(l) if l != "없음" else ""} 뒤 값', f'저장소에 {l} 까지만 있음(지수는 {K} 까지) — 다음 KRX 이어받기·대시보드 갱신 때 채워집니다')
    for k_, v in st.items():
        if not v.get('ok'): unk(f'{k_} 수집', f'이번 실행에서 실패 — {v.get("note", "")} (기존에 받은 값까지만 표시)')


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--deriv', default=os.path.join(ROOT, '_deriv', 'deriv', 'data')); a = ap.parse_args(); DV = a.deriv
    us, opex = build_us(); px = rd(os.path.join(FD, 'px.csv')); pxc = px.pivot(index='date', columns='sym', values='close')
    v = rd(os.path.join(FD, 'vix.csv'))
    if v is not None: pxc = pxc.join(v.set_index('date')[['vix']], how='outer')
    cf = build_cftc(us); kr, mexp, qexp = build_kr(DV, px)
    safe('옵션 행사가별 표', lambda: build_chain(DV, kr, mexp))
    if cf is not None: safe('CFTC 최신 보고서 표', lambda: t_cftc_latest(cf))
    safe('VIX 기간구조 표', lambda: t_term(us)); safe('월간 만기 전후 통계', lambda: t_opex(us, opex)); safe('비슷한 국면 표', lambda: t_analog(pxc['spx'].dropna()))
    safe('롤오버 표', lambda: t_roll(DV, kr, qexp)); safe('만기 일정', lambda: t_events(kr, us)); safe('미국→한국 표', lambda: t_us2kr(kr, pxc)); safe('선후 관계(교차상관)', lambda: t_xcorr(us, kr, cf))
    safe('방향 확률 모형', lambda: run_model(us, kr, cf, pxc)); safe('최근 일주일 표', lambda: t_week(us, kr, cf)); safe('자료 설명', lambda: t_sources(us, kr, cf))
    T['unknown'] = UNKNOWN
    T['meta'] = [dict(id='meta', built=dt.datetime.now(KST).strftime('%Y-%m-%d %H:%M KST'), us_asof=us.index[-1], kr_asof=kr.index[-1], run=os.environ.get('GITHUB_RUN_ID', ''), sha=os.environ.get('GITHUB_SHA', '')[:7])]
    uo = us[us.index >= '2006-01-03'].drop(columns=['put_vol', 'call_vol'], errors='ignore')
    uo.round(4).to_csv(os.path.join(OUT, 'us_daily.csv'))
    if cf is not None: cf[cf['date'] >= '2006-01-01'].to_csv(os.path.join(OUT, 'cftc.csv'), index=False)
    k8 = kr[kr.index >= '2008-01-02']
    k8[['k200', 'fut', 'basis', 'basis_pct', 'fut_oi_front', 'fut_oi_all', 'foreign_ct', 'inst_ct', 'indiv_ct', 'foreign_amt', 'inst_amt', 'indiv_amt', 'foreign_ct_c20', 'foreign_ct_c60', 'foreign_amt_c20', 'foreign_amt_c60',
        'night_pct', 'day_pct', 'cum_night', 'cum_day', 'usdkrw', 'qexp']].round(4).to_csv(os.path.join(OUT, 'kr_fut.csv'))
    k8[['k200', 'pcr_krx', 'm_pcoi', 'all_pcv_ma5', 'vkospi', 'iv_rep', 'mexp']].round(4).to_csv(os.path.join(OUT, 'kr_opt.csv'))
    json.dump(clean(T), open(os.path.join(OUT, 'tables.json'), 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    print('완료 — 표', len(T), '개 · 확인 불가', len(UNKNOWN), '건 · 미국', us.index[-1], '· 한국', kr.index[-1], flush=True)
    need = ['prob', 'valid', 'week_sum']
    if any(k not in T for k in need): print('핵심 표 누락:', [k for k in need if k not in T]); sys.exit(1)


if __name__ == '__main__':
    main()
