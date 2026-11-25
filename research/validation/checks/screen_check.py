# 11/16 자료로 재선별을 돌려 원래 명단(안정 관찰·점수 순위·방어1 성장 조건)과 대조(점검용)
import os, sys, json, glob, numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE); sys.path.insert(0, ROOT)
import screen as SC
RAW = SC.RAW; END = sys.argv[1] if len(sys.argv) > 1 else '20261116'
rd = SC.rd
ix = pd.read_csv(os.path.join(RAW, 'index_daily.csv.gz'), dtype={'date': str}).set_index('date')[['kospi', 'kosdaq']].astype(float)
ix = ix[ix.index <= END]; days = pd.Index(ix.index)
dd = pd.to_datetime(pd.Series(days)); grp = dd.groupby(dd.dt.strftime('%G-%V').values)
allw = sorted(zip(grp.min().dt.strftime('%Y%m%d'), grp.max().dt.strftime('%Y%m%d')), key=lambda x: x[1])
weeks = allw[-104:]; wend = [b for _, b in weeks]; wend_ix = [b for _, b in allw[-105:]]
wdays = {b: int(((days >= a) & (days <= b)).sum()) for a, b in weeks}
CAP, W, V, NAMES, IW = {}, {}, {}, {}, {}
for m in ('KOSPI', 'KOSDAQ'):
    CAP[m] = rd(f'snap/CAP_{m}_{END}.csv.gz')
    R, A_, N = {}, {}, {}
    for a, b in weeks:
        x = rd(f'weekly/W_{m}_{b}.csv.gz'); R[b] = x['등락률'].astype(float) / 100; A_[b] = x['거래대금'].astype(float); N.update(x['종목명'].to_dict())
    W[m] = pd.DataFrame(R); V[m] = pd.DataFrame(A_); NAMES.update(N)
    s = ix[m.lower()]; IW[m] = pd.Series([s.iloc[s.index.searchsorted(c, side='right') - 1] for c in wend_ix], index=wend_ix).pct_change().reindex(wend)
NAMES = pd.Series(NAMES)
st = SC.Static()
U = SC.stable_list(CAP, NAMES, W, V, IW, wend, st)
o = pd.DataFrame(json.load(open(os.path.join(ROOT, 'ref', 'st_watch_1116.json')))).set_index('code')
print('안정 관찰 대상', len(U), '(원래', len(o), ')', '· 상위100 겹침', len(set(U.index[:100]) & set(o.sort_values('rank').index[:100])),
      '· 순위 상관', round(U.st_rank.reindex(o.index).corr(o['rank'], method='spearman'), 4))
A = SC.universe_A(CAP, NAMES, V, wend, wdays, st)
C = {r['code']: r for r in json.load(open(os.path.join(ROOT, 'ref', 'composite.json')))}
print('분석 대상', len(A))
p2 = pd.concat([rd(f'd1/P_{m}_20241118_{END}.csv.gz')['등락률'].astype(float) for m in ('KOSPI', 'KOSDAQ')])
y26 = pd.concat([rd(f'year/Y_{m}_2026.csv.gz')['등락률'].astype(float) for m in ('KOSPI', 'KOSDAQ')])
g = A[(p2.reindex(A.index) >= 30) & (st.yr[2025].reindex(A.index) > 0) & (y26.reindex(A.index) > 0)]
print('성장 조건', len(g), '(원래', len(C), ') · 겹침', len(set(g.index) & set(C)), '· 원래에만', sorted(set(C) - set(g.index))[:15], '· 새로', len(set(g.index) - set(C)))
miss = sorted(set(C) - set(g.index))
for c in miss[:12]:
    print('  ', c, C[c]['name'], 'inA', c in A.index, 'r2', round(p2.get(c, np.nan), 1), C[c]['ret2y'], 'r25', st.yr[2025].get(c), C[c]['ret25'], 'r26', y26.get(c), C[c]['ret26'], 'mcap', CAP['KOSPI']['시가총액'].get(c, CAP['KOSDAQ']['시가총액'].get(c)), 'cap0', c in st.cap0)
U.to_csv('/tmp/st_check.csv'); A.to_csv('/tmp/A_check.csv'); g.to_csv('/tmp/g_check.csv')
