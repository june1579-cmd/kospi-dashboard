# 방어1 세부 점수(방어30·버틴 실적20·성장20·수급15·공통점15)를 성장 조건 밖 종목에도 같은 식으로 매긴다.
# 입력은 KRX 원자료(일별 수정 종가·순매수·외국인 보유율·급락 구간 등락률)로 다시 계산하고,
# 백분위 기준은 원래 성장 종목 250개(composite.json)의 값 분포를 그대로 쓴다(점수끼리 비교 가능하게).
import os, json, glob, numpy as np, pandas as pd
ROOT = os.path.dirname(os.path.abspath(__file__)); RAW = os.path.join(ROOT, 'raw')
END = '20261116'
J = '/home/claude/gr/merged_lists.json'
D = json.load(open(J)); comp = json.load(open('/home/claude/gr/data2/composite.json')); C = {r['code']: r for r in comp}
def rd(p, idx=True):
    f = os.path.join(RAW, p)
    if not os.path.exists(f): return None
    d = pd.read_csv(f, compression='gzip', index_col=0 if idx else None)
    if idx: d.index = d.index.astype(str).str.zfill(6)
    return d
MK = {r['code']: ('KOSPI' if r['market'] == '코스피' else 'KOSDAQ') for r in D}
ix = pd.read_csv(os.path.join(RAW, 'index_daily.csv.gz'), dtype={'date': str}).set_index('date')
CAP = {m: rd(f'snap/CAP_{m}_{END}.csv.gz') for m in ('KOSPI', 'KOSDAQ')}
CAP0 = {m: rd(f'd1/CAP_{m}_20241115.csv.gz') for m in ('KOSPI', 'KOSDAQ')}
EXCL = '스팩|SPAC|리츠|ETN|ETF|KODEX|TIGER|기업인수목적|인프라|맥쿼리|선박|부동산투자'
EPS_O = json.load(open('/home/claude/gr/data/episodes.json'))
EPIS = [('20241030', '20241209'), ('20250220', '20250409'), ('20251104', '20251124'), ('20260227', '20260331'), ('20260515', '20260520'), ('20260603', '20260608'), ('20260623', END)]

def universe(m):
    c = CAP[m]; c0 = CAP0[m]
    u = c[(c['시가총액'] >= 5e10)].index
    u = [x for x in u if c0 is not None and x in c0.index]
    return u

# ---------------- 급락 7구간: 같은 시장 분석 대상 중앙값 대비
EP = {}
for m in ('KOSPI', 'KOSDAQ'):
    U = universe(m)
    for a, b in EPIS:
        p = rd(f'd1/P_{m}_{a}_{b}.csv.gz')
        if p is None: continue
        p = p[~p['종목명'].astype(str).str.contains(EXCL)]
        med = p.loc[p.index.intersection(U), '등락률'].median()
        EP[(m, a)] = (p['등락률'].astype(float), float(med))

def feats(code):
    m = MK[code]; f = {}
    d = rd(f'daily/D_{code}.csv.gz')
    if d is not None and len(d):
        d.index = pd.to_datetime(d.index).strftime('%Y%m%d')
        cl = d['종가'].astype(float); cl = cl[cl > 0]; cl_all = cl
        cl = cl[cl.index >= '20241115']
        s = ix[m.lower()].astype(float); s = s[(s.index >= '20241115') & (s.index <= END)]
        j = cl.index.intersection(s.index)
        rs, ri = cl[j].pct_change().dropna(), s[j].pct_change().dropna()
        if len(rs) > 100:
            f['beta'] = float(np.cov(rs, ri)[0, 1] / np.var(ri, ddof=1))
            g = cl[j]; f['mdd'] = float((g / g.cummax() - 1).min() * 100)
            cd = ri[ri <= -0.03].index
            f['crash_day_beat'] = float((rs[cd] > ri[cd]).mean() * 100) if len(cd) else np.nan
    b = []
    if d is not None and len(d):
        for e in EPS_O:
            st_, en_ = e['start'].replace('-', ''), e['end'].replace('-', '')
            if en_ > END: en_ = END
            c0 = cl_all[cl_all.index <= st_]; c1 = cl_all[cl_all.index <= en_]
            if len(c0) and len(c1) and c0.index[-1] == st_ and c1.index[-1] == en_:
                ret = (c1.iloc[-1] / c0.iloc[-1] - 1) * 100
                b.append(ret - (e['med_kospi'] if m == 'KOSPI' else e['med_kosdaq']))
    if b: f['beats'] = sum(x > 0 for x in b); f['excess_avg'] = float(np.mean(b)); f['n_eps'] = len(b)
    sh = float(CAP[m].at[code, '상장주식수']) if code in CAP[m].index else np.nan
    def nb(who, a):
        x = rd(f'd1/NB_{m}_{who}_{a}_{END}.csv.gz')
        return float(x.at[code, '순매수거래량']) / sh * 100 if (x is not None and code in x.index and sh) else np.nan
    f['inst'] = nb('기관합계', '20250102'); f['frgn'] = nb('외국인', '20250102'); f['inst_crash'] = nb('기관합계', '20260623')
    fr = rd(f'snap/FR_{m}_{END}.csv.gz')
    f['frgn_ratio'] = float(fr.at[code, '지분율']) if fr is not None and code in fr.index else np.nan
    for dd in ('20241115', '20250102', '20251117', '20260515'):
        x = rd(f'd1/FR_{m}_{dd}.csv.gz')
        f['frc_' + dd] = f['frgn_ratio'] - float(x.at[code, '지분율']) if (x is not None and code in x.index) else np.nan
    p2 = rd(f'd1/P_{m}_20241118_{END}.csv.gz')
    f['ret2y'] = float(p2.at[code, '등락률']) if p2 is not None and code in p2.index else np.nan
    return f

F = {r['code']: feats(r['code']) for r in D}
# ---------------- 정합 점검: 원래 값이 있는 성장 종목과 비교
chk = []
for c, f in F.items():
    if c in C:
        o = C[c]; chk.append({**{k: f.get(k) for k in f}, **{'o_' + k: o.get(k) for k in ('beta', 'mdd', 'crash_day_beat', 'beats', 'excess_avg', 'inst', 'frgn', 'inst_crash', 'frgn_ratio', 'frgn_ratio_chg', 'ret2y')}})
K = pd.DataFrame(chk)
print('비교 종목', len(K))
for k in ('beta', 'mdd', 'crash_day_beat', 'beats', 'excess_avg', 'inst', 'frgn', 'inst_crash', 'frgn_ratio', 'ret2y'):
    a, b = K[k].astype(float), K['o_' + k].astype(float); ok = a.notna() & b.notna()
    print(f'{k:15s} n={ok.sum():3d} 상관 {a[ok].corr(b[ok]):.3f} 순위상관 {a[ok].rank().corr(b[ok].rank()):.3f} 차이 중앙값 {np.median(np.abs(a[ok]-b[ok])):.2f}')
best = None
for dd in ('20241115', '20250102', '20251117', '20260515'):
    a, b = K['frc_' + dd].astype(float), K['o_frgn_ratio_chg'].astype(float); ok = a.notna() & b.notna()
    cr = a[ok].corr(b[ok]); print(f'frgn_ratio_chg vs {dd}: 상관 {cr:.3f} 차이 중앙값 {np.median(np.abs(a[ok]-b[ok])):.2f}')
    if best is None or cr > best[1]: best = (dd, cr)
print('보유율 변화 기준일', best)
json.dump({'best_frc': best[0]}, open('/tmp/d1_cal.json', 'w'))
pd.to_pickle(F, '/tmp/d1_F.pkl')
