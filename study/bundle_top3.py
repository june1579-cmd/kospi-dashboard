"""묶음 상위 3개(2026-11-24 사용자 요청)의 매매일을 대시보드 표시용으로 만든다 — 일회성 계산(자동 갱신 아님).

쓰는 법: deriv-research 가지를 받아 둔 폴더에서  python bundle_top3.py <deriv/lab 경로> <출력 json>
  갈래 A·B: 순위표(leaderboard.csv)를 전 회차 합쳐 지금 통과 기준으로 다시 줄 세운 상위 20위 가운데 매매일 기록(candidates.pkl)이 남은 것
  갈래 C  : deriv/us/out 의 지표·백분위 표에서 us_study.py 와 같은 규칙으로 신호일을 다시 만든다(순위표의 거래 수와 일치 확인)
  묶음    : 먼저 난 신호부터 따르고 보유 중 난 신호는 건너뜀(연구소 '함께 쓰기'와 같음). 수익률 = 신호 다음 거래일 코스피 시가 → 보유 마지막 날 종가, 비용 없음
  순위    : 1~3개씩 합친 11,480가지를 거래별 수익률 단순 합계로 줄 세워, C 구성이 서로 다른 것 가운데 위 3개 = A13+C2+C12, B2+C2+C8, A4+B8+C2
"""
import glob, json, os, pickle, re, sys
import numpy as np, pandas as pd
LAB = os.path.abspath(sys.argv[1]); OUT = sys.argv[2]
sys.path.insert(0, LAB); sys.path.insert(0, os.path.join(LAB, '..', 'us')); os.chdir(LAB)
import lab_common as L
import us_study as US

k = pd.read_csv('../data/kospi_long.csv'); k.columns = [c.lstrip('﻿') for c in k.columns]
k['날짜'] = pd.to_datetime(k['날짜']); k = k.set_index('날짜'); td = k.index; O = k['시가'].values; C = k['종가'].values

def rank(d):
    rows = []
    for f in sorted(glob.glob(d + '/round_*/leaderboard.csv')):
        V = pd.read_csv(f)
        if 'all_n' not in V or 'p2_n' not in V: continue
        V['round'] = int(f.split('round_')[1][:3]); rows.append(V)
    A = pd.concat(rows, ignore_index=True).sort_values('round').drop_duplicates('desc', keep='last')
    bt = A['버팀'].fillna(False).astype(bool)
    A['P'] = (A.all_n >= 35) & (A.all_hit >= .85) & (A.dev_n >= 12) & (A.dev_hit >= .8) & (A.p2_n >= 12) & (A.p2_hit >= .8) & bt
    A['W'] = (A.all_n >= 35) & (A.all_hit >= .80) & (A.dev_n >= 12) & (A.dev_hit >= .75) & (A.p2_n >= 12) & (A.p2_hit >= .75) & bt
    return A.sort_values(['P', 'W', 'all_lb'], ascending=False).head(20).reset_index(drop=True)

pool = {}
for tr, d in (('A', 'out'), ('B', 'out_b')):
    A = rank(d); cache = {}
    for i, r in A.iterrows():
        rn = int(r['round'])
        if rn not in cache:
            cache[rn] = {}
            for p in glob.glob(f'{d}/round_{rn:03d}/*/candidates.pkl'):
                for x in pickle.load(open(p, 'rb')): cache[rn][x['id']] = x
        c = cache[rn].get(r.id)
        if c is None: continue
        t = c['trades'].assign(signal=pd.to_datetime(c['trades']['signal']), exit=pd.to_datetime(c['trades']['exit'])).dropna()
        pool[f'{tr}{i + 1}'] = dict(desc=r.desc, round=rn, id=r.id, tr=t[['signal', 'exit']])
F = pd.read_csv('../us/out/features_kr.csv.gz', index_col=0, parse_dates=True); Q = pd.read_csv('../us/out/features_pct.csv.gz', index_col=0, parse_dates=True)
ktd = L.prices()['K200'].index
for i, r in rank('out_c').iterrows():
    m = re.match(r'A11_(.+)_h(\d+)_([UD])$', r.id); cid, h, ud = m.group(1), int(m.group(2)), m.group(3)
    if ud != 'U': continue
    mask = None
    for nm, fn in US.PCT:
        if cid.endswith('_' + nm): f = cid[:-len(nm) - 1]; mask = fn(Q[f]) & F[f].notna()
    if mask is None:
        for f, nm, fn in US.ABS:
            if cid == f'{f}_abs{nm}': mask = fn(F[f]) & F[f].notna()
    if mask is None and cid == 'pcr_hi_es_dn': mask = (Q['pcr_eq'] >= 0.9) & (Q['es_r5'] <= 0.2)
    if mask is None: continue
    sig = ktd[np.asarray(mask.reindex(ktd).fillna(False).values, dtype=bool)]
    t = pd.DataFrame({'signal': sig, 'exit': [L.exit_after(ktd, s, h) for s in sig]}).dropna()
    pool[f'C{i + 1}'] = dict(desc=r.desc, round=1, id=r.id, tr=t[t.signal >= '2010-01-01'])

def bundle(names):
    a = []
    for j, nm in enumerate(names):
        t = pool[nm]['tr']
        si = td.searchsorted(t['signal'].values); s = td.searchsorted(t['signal'].values, side='right'); e = td.searchsorted(t['exit'].values)
        ok = (s < len(td)) & (e < len(td)) & (s <= e) & (t['signal'].values >= np.datetime64('2010-01-01')) & (td[np.minimum(e, len(td) - 1)] == t['exit'].values)
        a += [(int(x), int(y), int(z), j) for x, y, z in zip(si[ok], s[ok], e[ok])]
    a.sort(key=lambda r: (r[0], r[2], r[3])); last = -1; out = []
    for si, s, e, j in a:
        if si >= last:
            out.append(dict(cond=str(td[si].date()), buy=str(td[s].date()), sell=str(td[e].date()), ret=round((C[e] / O[s] - 1) * 100, 2), src=names[j])); last = e
    return out

SETS = [['A13', 'C2', 'C12'], ['B2', 'C2', 'C8'], ['A4', 'B8', 'C2']]
res = {'made': str(td[-1].date()), 'bundles': []}
for i, names in enumerate(SETS):
    t = bundle(names); r = np.array([x['ret'] for x in t])
    res['bundles'].append({'rank': i + 1, 'names': names, 'desc': {n: pool[n]['desc'] for n in names}, 'src': {n: [pool[n]['round'], pool[n]['id']] for n in names}, 'n': len(t), 'win': int((r > 0).sum()), 'sum': round(float(r.sum()), 1), 'trades': t})
    print(i + 1, '+'.join(names), 'n', len(t), 'win%', round((r > 0).mean() * 100, 1), 'sum', round(r.sum(), 1))
json.dump(res, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False)
