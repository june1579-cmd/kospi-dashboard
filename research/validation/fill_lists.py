# 통합 명단 빈 칸 채우기: merge_lists.py 결과(merged_lists.json)에 덧붙인다.
#  - 명단 밖 종목의 안정 순위(848개 중)·점수 순위(분석 대상 중)·방어1(성장 조건 밖 사유)
#  - 우선주: 급락 기록·급락 수익률(KRX 원자료), 실적·PBR·PER(보통주 기준)
#  - 거래정지 등으로 빠졌던 급락 수익률은 KRX 구간 등락률 그대로
#  - OpenDART 회사별 전체 재무제표(dart_fill)로 영업이익·4년 흑자, 외국 기업 PBR·배당
#  - 값이 원래 없을 수밖에 없는 칸은 사유 글(_n)
import os, json, glob, numpy as np, pandas as pd
ROOT = os.path.dirname(os.path.abspath(__file__)); RAW = os.path.join(ROOT, 'raw'); OUT = os.path.join(ROOT, 'stable')
END = '20261116'
J = '/home/claude/gr/merged_lists.json'
D = json.load(open(J))
def rd(p):
    f = os.path.join(RAW, p)
    if not os.path.exists(f): return None
    d = pd.read_csv(f, compression='gzip', index_col=0); d.index = d.index.astype(str).str.zfill(6); return d
def note(r, k, t): r.setdefault('_n', {})[k] = t
def amt(x):
    try: return float(str(x).replace(',', ''))
    except Exception: return np.nan
PREF = {'005935': '005930', '010955': '010950', '02826K': '028260', '03473K': '034730', '078935': '078930'}
idx = pd.read_csv(os.path.join(RAW, 'index_daily.csv.gz'), dtype={'date': str}).sort_values('date')
days = pd.Index(idx['date'].astype(str))
nxt = lambda d: days[days.searchsorted(d, side='right')]
mk = {r['code']: ('KOSPI' if r['market'] == '코스피' else 'KOSDAQ') for r in D}
FU = {m: rd(f'snap/FUND_{m}_{END}.csv.gz') for m in ('KOSPI', 'KOSDAQ')}
CAP = {m: rd(f'snap/CAP_{m}_{END}.csv.gz') for m in ('KOSPI', 'KOSDAQ')}

# 1) 안정 순위: 848개 대상 전체 순위
W = pd.read_csv(os.path.join(OUT, 'watch_all.csv'), dtype={'code': str}).set_index('code')
P = pd.read_csv(os.path.join(OUT, 'panel.csv.gz'), dtype={'code': str, 'peak': str}); P['code'] = P.code.str.zfill(6)
for r in D:
    c = r['code']
    if r.get('st_rank') is None:
        if c in W.index:
            r['st_rank'] = int(W.at[c, 'rank']); r['st_score'] = round(float(W.at[c, 'score']), 1)
        else:
            why = []
            if c in PREF or r['name'].endswith(('우', '우B')): why.append('우선주')
            if (r.get('mcap') or 0) < 1000: why.append('시총 1,000억 미만')
            if (r.get('n_rec') or 0) < 10 and '우선주' not in why: why.append('급락 기록 10번 미만')
            note(r, 'st_rank', '848개 밖' + ('(' + '·'.join(why) + ')' if why else '(회전율 하위 20%)'))
            note(r, 'st_score', '—')
    r['st_top100'] = r.get('in_st')

# 2) 점수 순위: 분석 대상 1,439개 중 종합 점수 상위 300개+일부만 점수가 남아 있음
sc = pd.DataFrame(json.load(open('/home/claude/gr/data2/scores.json')))
sc['mix'] = (5 * sc['flow'].astype(float) + 5 * sc['chk'].astype(float) * 25) / 10
sc = sc.sort_values('mix', ascending=False, kind='stable').reset_index(drop=True); sc['rank'] = range(1, len(sc) + 1)
scm = sc.set_index('code')
for r in D:
    c = r['code']
    if r.get('sc_rank') is None:
        if c in scm.index:
            x = scm.loc[c]
            r['sc_mix'] = round(float(x['mix']), 1); r['sc_flow'] = float(x['flow']); r['sc_chk'] = int(x['chk']); r['sc_big7'] = float(x['big7']) if pd.notna(x['big7']) else None
            if int(x['rank']) <= 300: r['sc_rank'] = int(x['rank'])
            else: note(r, 'sc_rank', '300위 밖')
        else:
            for k in ('sc_rank', 'sc_mix', 'sc_flow', 'sc_chk', 'sc_big7'): note(r, k, '300위 밖')

# 3) 방어 1번: 성장 조건(2년 +30%, 2025·2026 모두 상승) 250개 안에서만 점수
comp = {x['code']: x for x in json.load(open('/home/claude/gr/data2/composite.json'))}
for r in D:
    c = r['code']
    if r.get('d1_rank') is None:
        if c in comp:
            x = comp[c]; r['d1_rank'] = x.get('rank'); r['d1_total'] = x.get('total')
            for k in ('def', 'hold', 'grow', 'flow', 'com'): r['d1_' + k] = x.get('s_' + k)
        else:
            why = []
            if r.get('ret2y') is not None and r['ret2y'] < 30: why.append('2년 +30% 미만')
            if r.get('ret_2025') is not None and r['ret_2025'] <= 0: why.append('2025년 하락')
            if r.get('ret_ytd') is not None and r['ret_ytd'] <= 0: why.append('2026년 하락')
            t = '성장 조건 밖' + ('(' + '·'.join(why) + ')' if why else '')
            for k in ('d1_rank', 'd1_total', 'd1_def', 'd1_hold', 'd1_grow', 'd1_flow', 'd1_com'): note(r, k, t if k == 'd1_rank' else '—')

# 4) 급락 수익률·기록: KRX 구간 등락률(거래정지 등으로 분석에서 빠졌던 종목·우선주 포함)
eps = P[['peak', 'trough', 'market', 'med_ret']].drop_duplicates(['peak', 'market'])
for r in D:
    c = r['code']; m = mk[c]
    for k, (a, b) in (('ret_0622', (nxt('20260622'), '20260730')), ('ret_0923', (nxt('20260923'), '20261109'))):
        if r.get(k) is None:
            d = rd(f'period/P_{m}_{a}_{b}.csv.gz')
            if d is not None and c in d.index:
                r[k] = round(float(d.at[c, '등락률']), 2)
                if float(d.at[c, '거래량']) == 0: note(r, k + '_x', '거래 없음')
    if r.get('rec_rate') is None:
        xs = []
        for _, e in eps[eps.market == m].iterrows():
            d = rd(f'period/P_{m}_{nxt(e.peak)}_{e.trough}.csv.gz')
            if d is not None and c in d.index and float(d.at[c, '거래량']) > 0:
                xs.append(float(d.at[c, '등락률']) / 100 - float(e.med_ret))
        if xs:
            r['n_rec'] = len(xs); r['rec_rate'] = round(100 * sum(1 for x in xs if x > 0) / len(xs), 1)

# 5) 우선주: 보통주 실적·주당 값으로 PBR·PER
for r in D:
    c = r['code']
    if c in PREF:
        base = PREF[c]; m = mk[c]
        b = next((x for x in D if x['code'] == base), None)
        f = FU[m]
        if f is not None and base in f.index:
            bps, eps_ = float(f.at[base, 'BPS']), float(f.at[base, 'EPS'])
            if r.get('pbr') is None and bps > 0: r['pbr'] = round(r['close'] / bps, 2); note(r, 'pbr_x', '보통주 BPS 기준')
            if r.get('per') is None and eps_ > 0: r['per'] = round(r['close'] / eps_, 1); note(r, 'per_x', '보통주 EPS 기준')
        r['_base'] = base

# 6) OpenDART 회사별 전체 재무제표
fill = rd('dart_fill.csv.gz') if False else (pd.read_csv(os.path.join(RAW, 'dart_fill.csv.gz'), dtype=str) if os.path.exists(os.path.join(RAW, 'dart_fill.csv.gz')) else None)
op = {}
dt = pd.read_csv(os.path.join(RAW, 'dart_op.csv.gz'), dtype=str); dt['code'] = dt.stock_code.str.zfill(6)
dt['_p'] = (dt.fs_div != 'CFS').astype(int); dt = dt.sort_values('_p').drop_duplicates(['code', 'bsns_year'])
for _, x in dt.iterrows():
    for k, off in (('thstrm_amount', 0), ('frmtrm_amount', 1), ('bfefrmtrm_amount', 2)):
        v = amt(x[k])
        if x.code.startswith('9'): v *= 1000
        if not np.isnan(v): op.setdefault(x.code, {}).setdefault(int(x.bsns_year) - off, v)
EQ = {}
if fill is not None and len(fill):
    fill['code'] = fill.stock_code.str.zfill(6)
    fill['_p'] = (fill.fs_div != 'CFS').astype(int)
    for kind in ('op', 'eq'):
        f2 = fill[fill.kind == kind].sort_values(['_p']).drop_duplicates(['code', 'bsns_year'])
        for _, x in f2.iterrows():
            y = int(x.bsns_year)
            for k, off in (('thstrm_amount', 0), ('frmtrm_amount', 1)):
                v = amt(x[k])
                if np.isnan(v): continue
                if x.code.startswith('9'): v *= 1000   # 외국 기업은 천 원 단위로 공시
                if kind == 'op': op.setdefault(x.code, {})[y - off] = op.get(x.code, {}).get(y - off, v) if off else v
                else: EQ.setdefault(x.code, {})[y - off] = v
for r in D:
    c = r['code']; base = r.get('_base', c)
    o = op.get(base, {})
    yrs = [2022, 2023, 2024, 2025]
    if all(y in o for y in yrs):
        r['profit_years'] = int(sum(o[y] > 0 for y in yrs))
    elif r.get('profit_years') is None:
        have = [y for y in yrs if y in o]
        if have: note(r, 'profit_years', f'{len(have)}년치만({have[0]}~)')
        else: note(r, 'profit_years', '영업이익 항목 없음')
    if (r.get('op2025') is None or base.startswith('9')) and 2025 in o: r['op2025'] = round(o[2025] / 1e8)
    # 외국 기업 PBR(지배주주 자본 기준)·배당
    if r.get('pbr') is None and base in EQ and 2025 in EQ[base] and EQ[base][2025] > 0:
        r['pbr'] = round(r['mcap'] * 1e8 / EQ[base][2025], 2); note(r, 'pbr_x', '2025년 말 지배주주 자본 기준')
al = os.path.join(RAW, 'dart_alot.csv.gz')
if os.path.exists(al) and os.path.getsize(al) > 30:
    A = pd.read_csv(al, dtype=str)
    for r in D:
        if r.get('div') is None:
            a = A[(A.stock_code.str.zfill(6) == r['code']) & A.se.fillna('').str.contains('주당 현금배당금') & A.stock_knd.fillna('').str.contains('보통')]
            a2 = A[(A.stock_code.str.zfill(6) == r['code']) & A.se.fillna('').str.contains('주당 현금배당금')]
            if len(a):
                dps = amt(a.thstrm.iloc[0])
                if not np.isnan(dps): r['div'] = round(dps / r['close'] * 100, 2) if dps > 0 else 0.0; note(r, 'div_x', '2025 결산 주당배당금 ÷ 11/16 종가')
            elif len(a2) and a2.thstrm.fillna('-').str.strip().eq('-').all():
                r['div'] = 0.0; note(r, 'div_x', '2025 결산 현금배당 없음(OpenDART)')
    for r in D:
        if r.get('per') is None:
            e = A[(A.stock_code.str.zfill(6) == r['code']) & A.se.fillna('').str.contains('주당순이익')]
            if len(e):
                v = amt(e.thstrm.iloc[0])
                if not np.isnan(v) and v > 0: r['per'] = round(r['close'] / v, 1); note(r, 'per_x', '2025 연결 주당순이익(OpenDART) 기준')
# 7) 원래 값이 없는 칸의 사유
for r in D:
    c = r['code']; base = r.get('_base', c); m = mk[c]
    f = FU[m]
    if r.get('per') is None:
        e = float(f.at[c, 'EPS']) if (f is not None and c in f.index) else np.nan
        if c in PREF: e = float(f.at[base, 'EPS']) if base in f.index else np.nan
        note(r, 'per', '적자' if (not np.isnan(e) and e < 0) else ('—' if np.isnan(e) else '적자·없음'))
    for y in (2022, 2023, 2024):
        if r.get(f'ret_{y}') is None: note(r, f'ret_{y}', '상장 전')
    for k in ('pbr', 'div', 'rec_rate', 'n_rec', 'op2025'):
        if r.get(k) is None: note(r, k, '확인 불가')
    r.pop('_base', None)
json.dump(D, open(J, 'w'), ensure_ascii=False, separators=(',', ':'))
keys = ['st_rank', 'sc_rank', 'sc_mix', 'd1_rank', 'rec_rate', 'pbr', 'per', 'div', 'profit_years', 'op2025', 'ret_2022', 'ret_0622', 'ret_0923']
print({k: sum(1 for r in D if r.get(k) is None) for k in keys})
print({k: sum(1 for r in D if r.get(k) is None and not r.get('_n', {}).get(k)) for k in keys})
