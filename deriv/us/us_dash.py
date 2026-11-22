"""미국·한국 선물옵션 대시보드 자료(deriv/us/out/dash.json) — 수집·검증 결과를 화면용으로 줄인다. 숫자는 전부 저장소 자료에서 계산, 없으면 null('확인 불가').
감마 노출은 추정: 옵션 체인의 미결제약정 × 블랙숄즈 감마, '딜러가 콜은 사고 풋은 판 상태'라는 통상 가정(실제 포지션은 알 수 없음).
"""
import glob
import json
import os
import sys

import numpy as np
import pandas as pd
from scipy.stats import norm

ROOT = os.path.dirname(os.path.abspath(__file__)); DERIV = os.path.dirname(ROOT)
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(DERIV, 'lab'))
import lab_common as L  # noqa: E402
import us_features as UF  # noqa: E402

OUT = os.path.join(ROOT, 'out'); DATA = os.path.join(ROOT, 'data')
fz = lambda v, n=2: None if v is None or not np.isfinite(v) else round(float(v), n)


def bs_gamma(S, K, T, iv):
    T = np.maximum(T, 1 / 365); iv = np.clip(iv, 0.03, 3)
    d1 = (np.log(S / K) + 0.5 * iv * iv * T) / (iv * np.sqrt(T))
    return norm.pdf(d1) / (S * iv * np.sqrt(T))


def max_pain(o):
    ks = np.sort(o['K'].unique()); c = o[o.cp == 'C']; p = o[o.cp == 'P']
    pay = [(c['oi'] * np.maximum(k - c['K'], 0)).sum() + (p['oi'] * np.maximum(p['K'] - k, 0)).sum() for k in ks]
    return float(ks[int(np.argmin(pay))]) if len(ks) else None


def structure(o, spot, mult, band=0.10, step=None):
    """o: cp,K,oi,(gamma) — 한 만기 또는 여러 만기 합. 행사가별 미결제·콜벽·풋벽·최대 고통·감마."""
    o = o[(o['K'] >= spot * (1 - band)) & (o['K'] <= spot * (1 + band))]
    if step: o = o.assign(K=(o['K'] / step).round() * step)
    g = o.groupby(['K', 'cp'])['oi'].sum().unstack(fill_value=0).reindex(columns=['C', 'P'], fill_value=0)
    out = {'strikes': [fz(k) for k in g.index], 'call_oi': [int(v) for v in g['C']], 'put_oi': [int(v) for v in g['P']]}
    up = g[g.index >= spot]; dn = g[g.index <= spot]
    out['call_wall'] = fz(up['C'].idxmax()) if len(up) and up['C'].max() > 0 else None
    out['put_wall'] = fz(dn['P'].idxmax()) if len(dn) and dn['P'].max() > 0 else None
    out['pcr_oi'] = fz(g['P'].sum() / g['C'].sum(), 3) if g['C'].sum() else None
    if 'gamma' in o:
        o = o.assign(gex=np.where(o.cp == 'C', 1, -1) * o['gamma'] * o['oi'] * mult * spot * spot * 0.01)
        gg = o.groupby('K')['gex'].sum().reindex(g.index).fillna(0)
        out['gex'] = [fz(v / 1e9, 4) for v in gg]; out['gex_total'] = fz(gg.sum() / 1e9, 3)
    return out


def zero_gamma(o, spot, mult):
    grid = np.linspace(spot * 0.9, spot * 1.1, 81); tot = []
    for s in grid:
        gm = bs_gamma(s, o['K'].values, o['T'].values, o['iv'].values)
        tot.append((np.where(o.cp == 'C', 1, -1) * gm * o['oi'].values * mult * s * s * 0.01).sum())
    tot = np.array(tot); sg = np.sign(tot); ix = np.where(sg[:-1] * sg[1:] < 0)[0]
    if not len(ix): return None
    i = ix[np.argmin(np.abs(grid[ix] - spot))]
    return fz(grid[i] - tot[i] * (grid[i + 1] - grid[i]) / (tot[i + 1] - tot[i]))


def us_chain():
    res = {}
    for p in sorted(glob.glob(os.path.join(DATA, 'chain_now_*.csv.gz'))):
        sym = os.path.basename(p)[10:-7]
        if sym not in ('SPX', 'SPY', 'QQQ'): continue
        o = pd.read_csv(p, parse_dates=['exp']).rename(columns={'open_interest': 'oi'})
        o = o[(o['oi'] > 0) & o['K'].notna()]
        if not len(o): continue
        spot = float(o['spot'].iloc[0]); ts = str(o['ts'].iloc[0]); now = pd.Timestamp(ts[:10])
        o = o[o['exp'] >= now]; o['T'] = ((o['exp'] - now).dt.days + 1) / 365
        o['iv'] = pd.to_numeric(o['iv'], errors='coerce'); o = o[o['iv'] > 0.01]
        if o['gamma'].isna().all() or (o['gamma'].fillna(0) == 0).all(): o['gamma'] = bs_gamma(spot, o['K'].values, o['T'].values, o['iv'].values)
        o = o[o['T'] <= 46 / 365]   # 45일 안 만기만
        step = 5 if sym == 'SPY' else (5 if sym == 'QQQ' else 25)
        st = structure(o, spot, 100, 0.08, step); st.update({'spot': fz(spot), 'ts': ts, 'zero_gamma': zero_gamma(o, spot, 100), 'expiries': int(o['exp'].nunique())})
        near = o[o['exp'] == o['exp'].min()]
        fri = o[o['exp'].dt.weekday == 4]; m = fri[(fri['exp'].dt.day >= 15) & (fri['exp'].dt.day <= 21)]
        tgt = m[m['exp'] == m['exp'].min()] if len(m) else near
        st['max_pain'] = max_pain(tgt); st['max_pain_exp'] = str(tgt['exp'].iloc[0].date())
        res[sym] = st
    return res


def kr_chain(k2):
    kind, c = L.chain_best()
    d = c['date'].max(); x = c[c['date'] == d].copy(); td = k2.index
    x['exp'] = x['ym'].map(lambda y: L.expiry_of_ym(y, td)); x = x[x['exp'] >= d]
    ym = x.sort_values('exp')['ym'].iloc[0]; f = x[x['ym'] == ym]
    spot = float(f['spot'].dropna().iloc[0]) if f['spot'].notna().any() else float(k2['close'].asof(d))
    st = structure(f[['cp', 'K', 'oi']], spot, 250000, 0.10)
    st.update({'spot': fz(spot), 'date': str(d.date()), 'ym': str(ym), 'exp': str(f['exp'].iloc[0].date()), 'max_pain': max_pain(f[['cp', 'K', 'oi']]), 'kind': kind})
    # 지난 60거래일 콜벽·풋벽·최대 고통(최근월물)
    H = []
    for dd in sorted(c['date'].unique())[-60:]:
        y = c[c['date'] == dd].copy(); y['exp'] = y['ym'].map(lambda v: L.expiry_of_ym(v, td)); y = y[y['exp'] >= dd]
        if not len(y): continue
        y = y[y['ym'] == y.sort_values('exp')['ym'].iloc[0]]; sp = float(y['spot'].dropna().iloc[0]) if y['spot'].notna().any() else np.nan
        if not np.isfinite(sp): continue
        s2 = structure(y[['cp', 'K', 'oi']], sp, 250000, 0.10)
        H.append({'d': str(pd.Timestamp(dd).date()), 'spot': fz(sp), 'cw': s2['call_wall'], 'pw': s2['put_wall'], 'mp': max_pain(y[['cp', 'K', 'oi']])})
    st['hist'] = H
    return st


def third_friday(y, m):
    d = pd.Timestamp(y, m, 1); return d + pd.Timedelta(days=(4 - d.weekday()) % 7 + 14)


def main():
    B = UF.build(); F, Q, td, k2, U, C = B['F'], B['Q'], B['td'], B['k2'], B['U'], B['C']
    fut = L.prices()['K200F']
    J = {'at_kst': pd.Timestamp.now(tz='Asia/Seoul').strftime('%Y-%m-%d %H:%M'), 'kr_date': str(td[-1].date()), 'us_date': str(U.index[-1].date())}
    try: J['collect'] = {k: (v.get('ok') if isinstance(v, dict) else None) for k, v in json.load(open(os.path.join(OUT, 'collect_log.json'), encoding='utf-8')).items() if isinstance(v, dict) and 'ok' in v}
    except Exception: J['collect'] = {}
    # 지표 카드: 가장 최근 값(뉴욕 최신 거래일 기준 미국 지표는 U, 한국 지표는 F 마지막 행)
    UQ = U.apply(UF.pct_rank)
    tiles = {}
    for g, fs in UF.GROUP.items():
        for f in fs:
            if f in UF.KOREA or f in ('ewy_gap', 'vk_vix'):
                s = F[f].dropna(); q = Q[f].dropna()
            elif f in U:
                s = U[f].dropna(); q = UQ[f].dropna()
            else: continue
            if not len(s): continue
            tiles[f] = {'name': UF.NAMES[f], 'group': g, 'v': fz(s.iloc[-1], 3), 'pct': fz(q.iloc[-1] * 100, 0) if len(q) and q.index[-1] == s.index[-1] else None, 'd': str(s.index[-1].date())}
    J['tiles'] = tiles
    # 시계열(최근 260 한국 거래일)
    n = 260; ix = td[-n:]
    es = C['ES=F'].ffill(limit=2); nq = C['NQ=F'].ffill(limit=2)
    asof = lambda s: [fz(s.dropna().asof(d), 3) if len(s.dropna()) and d >= s.dropna().index[0] else None for d in ix]
    fl = F['for_fut1'].reindex(ix).fillna(0).cumsum() if 'for_fut1' in F else pd.Series(np.nan, index=ix)
    J['series'] = {'d': [str(d.date()) for d in ix], 'k200f': [fz(v) for v in fut['close'].reindex(ix)], 'k200': [fz(v) for v in k2['close'].reindex(ix)],
                   'es': asof(es), 'nq': asof(nq), 'sox': asof(C['^SOX']), 'vix': asof(U['vix']), 'vkospi': [fz(v) for v in F['vkospi'].reindex(ix)],
                   'vix_ts': asof(U['vix_ts']), 'krw': asof(C['KRW=X']), 'for_cum': [fz(v, 3) for v in fl], 'k_pcr': [fz(v) for v in F['k_pcr'].reindex(ix)], 'pcr_eq': asof(U['pcr_eq']),
                   'es_am': asof(U['es_am']), 'es_lev': asof(U['es_lev']), 'nq_lev': asof(U['nq_lev']), 'vx_lev': asof(U['vx_lev'])}
    # 한국 마감 뒤 미국 선물(1시간 봉, 한국 시각)
    try:
        h = pd.read_csv(os.path.join(DATA, 'us_fut_hourly.csv.gz'), parse_dates=['kst']); H = {}
        for t, nm in (('ES=F', 'es'), ('NQ=F', 'nq')):
            x = h[h.ticker == t].set_index('kst')['close'].sort_index(); last = x.index[-1]
            bd = pd.bdate_range(last.normalize() - pd.Timedelta(days=10), last.normalize())
            kd = [d for d in bd if d + pd.Timedelta(hours=16) <= last][-1]   # 가장 최근 평일의 한국 장 마감 무렵(15시 봉 = 15~16시)
            ref = x[x.index <= kd + pd.Timedelta(hours=15, minutes=59)]
            H[nm] = {'last': fz(x.iloc[-1]), 'last_kst': last.strftime('%Y-%m-%d %H:%M'), 'ref': fz(ref.iloc[-1]) if len(ref) else None, 'ref_kst': ref.index[-1].strftime('%Y-%m-%d %H:%M') if len(ref) else None,
                     'chg%': fz((x.iloc[-1] / ref.iloc[-1] - 1) * 100) if len(ref) else None, 'tail': [[i.strftime('%m-%d %H'), fz(v)] for i, v in x.iloc[-72:].items()]}
        J['since_close'] = H
    except Exception as e:
        J['since_close'] = {'err': repr(e)[:100]}
    try: J['us_chain'] = us_chain()
    except Exception as e: J['us_chain'] = {'err': repr(e)[:200]}
    try: J['kr_chain'] = kr_chain(k2)
    except Exception as e: J['kr_chain'] = {'err': repr(e)[:200]}
    # 벽 기록 쌓기(미국은 과거가 없어 오늘부터)
    wp = os.path.join(DATA, 'us_walls_hist.csv')
    rows = [{'date': v['ts'][:10], 'sym': s, 'spot': v['spot'], 'call_wall': v['call_wall'], 'put_wall': v['put_wall'], 'zero_gamma': v['zero_gamma'], 'gex_total': v.get('gex_total'), 'max_pain': v['max_pain']}
            for s, v in J['us_chain'].items() if isinstance(v, dict) and 'spot' in v]
    if rows:
        W = pd.concat([pd.read_csv(wp)] if os.path.exists(wp) else [] + [pd.DataFrame(rows)]) if False else pd.DataFrame(rows)
        if os.path.exists(wp): W = pd.concat([pd.read_csv(wp), W])
        W.drop_duplicates(['date', 'sym'], keep='last').to_csv(wp, index=False)
    # 달력
    today = pd.Timestamp.now(tz='Asia/Seoul').normalize().tz_localize(None); cal = []
    for k in range(0, 4):
        y, m = (today + pd.DateOffset(months=k)).year, (today + pd.DateOffset(months=k)).month
        ke = L.second_thursday(y, m); ue = third_friday(y, m)
        if ke >= today: cal.append({'d': str(ke.date()), 'what': '한국 옵션 만기(둘째 목요일)' + (' · 선물 동시 만기' if m in (3, 6, 9, 12) else ''), 'days': int((ke - today).days)})
        if ue >= today: cal.append({'d': str(ue.date()), 'what': '미국 옵션 만기(셋째 금요일)' + (' · 분기 동시 만기' if m in (3, 6, 9, 12) else ''), 'days': int((ue - today).days)})
    J['calendar'] = sorted(cal, key=lambda r: r['d'])[:6]
    # 분해표·검증 결과
    dp = os.path.join(OUT, 'decomp.csv')
    if os.path.exists(dp): J['decomp'] = json.loads(pd.read_csv(dp).to_json(orient='records', force_ascii=False))
    os.environ.setdefault('LAB_TRACK', 'c')
    try:
        rd = L.out_dir(); V = pd.read_csv(os.path.join(rd, 'a08', 'verdicts.csv')); st = json.load(open(os.path.join(rd, 'status.json'), encoding='utf-8'))
        rt = os.path.join(rd, 'a10', 'redteam.csv'); R = pd.read_csv(rt).set_index('id') if os.path.exists(rt) else pd.DataFrame()
        V['ex1'] = V['dev_hit'] - V['dev_base']; V['ex2'] = V['p2_hit'] - V['p2_base']; V['exmin'] = V[['ex1', 'ex2']].min(axis=1)
        led = L.ledger()
        J['verdict'] = {'round': st.get('round'), 'candidates': int(len(V)), 'sel_fwd': int(V['sel_fwd'].sum()), 'sel_rev': int(V['sel_rev'].sum()), 'fwd_pass': int(V['fwd_pass'].sum()),
                        'rev_pass': int(V['rev_pass'].sum()), 'both_pass': int(V['hold_pass'].sum()), 'trials_total': led.get('trials_total'),
                        'hit80_both': int(((V['dev_hit'] >= 0.8) & (V['p2_hit'] >= 0.8) & (V['dev_n'] >= 20) & (V['p2_n'] >= 12)).sum()),
                        'p1': '2010~2023', 'p2': '2024~'}
        cols = ['desc', 'family', 'dev_n', 'dev_hit', 'dev_base', 'p2_n', 'p2_hit', 'p2_base', 'p2_p', 'sel_fwd', 'sel_rev', 'fwd_pass', 'rev_pass']
        def pack(x):
            o = []
            for _, r in x.iterrows():
                o.append({'desc': r['desc'], 'family': r['family'], 'n1': int(r['dev_n']), 'h1': fz(r['dev_hit'] * 100, 1), 'b1': fz(r['dev_base'] * 100, 1), 'n2': int(r['p2_n']), 'h2': fz(r['p2_hit'] * 100, 1),
                          'b2': fz(r['p2_base'] * 100, 1), 'sel': ('앞' if r['sel_fwd'] else '') + ('뒤' if r['sel_rev'] else ''), 'ok': bool(r['fwd_pass'] or r['rev_pass']),
                          'rt': (None if r['id'] not in R.index else bool(R.loc[r['id'], '버팀']))})
            return o
        ok = V[(V['dev_n'] >= 20) & (V['p2_n'] >= 12)]
        J['verdict']['selected'] = pack(V[V['dev_pass']].sort_values('exmin', ascending=False).head(12))
        J['verdict']['closest'] = pack(ok.sort_values('exmin', ascending=False).head(12))
        fam = ok.assign(g=ok['family'].str.replace('(절대값)', '', regex=False)).groupby('g').agg(n=('id', 'size'), best=('exmin', 'max'), med=('exmin', 'median'),
                                                                                              pos=('exmin', lambda s: (s > 0.05).mean())).reset_index()
        J['verdict']['families'] = [{'g': r['g'], 'n': int(r['n']), 'best': fz(r['best'] * 100, 1), 'med': fz(r['med'] * 100, 1), 'pos': fz(r['pos'] * 100, 0)} for _, r in fam.iterrows()]
    except Exception as e:
        J['verdict'] = {'err': repr(e)[:200]}
    json.dump(J, open(os.path.join(OUT, 'dash.json'), 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'), default=str)
    print('dash.json', os.path.getsize(os.path.join(OUT, 'dash.json')), 'bytes', {k: (list(v)[:6] if isinstance(v, dict) else type(v).__name__) for k, v in J.items()})


if __name__ == '__main__':
    main()
