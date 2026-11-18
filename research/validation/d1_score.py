# d1_fill.py가 만든 KRX 입력값(/tmp/d1_F.pkl)으로 방어1 세부 점수를 원래 식(comp.py) 그대로 계산.
# 백분위 기준 = 원래 성장 종목 250개 값 분포. 성장 종목 100개는 원래 점수를 그대로 두고, 재계산값으로 정합만 점검.
import json, numpy as np, pandas as pd, statistics as st
J = '/home/claude/gr/merged_lists.json'
D = json.load(open(J)); REF = json.load(open('/home/claude/gr/data2/composite.json')); C = {r['code']: r for r in REF}
F = pd.read_pickle('/tmp/d1_F.pkl'); n = len(REF)
sec = {r['sector']: r for r in json.load(open('/home/claude/gr/data/sectors.json'))}
def pct(vals, hi=True):
    vals = sorted(vals)
    def P(v):
        lo = sum(1 for x in vals if x < v); up = lo + sum(1 for x in vals if x == v)
        p = ((lo + max(up, lo + 1) - 1) / 2) / (n - 1) * 100   # 원래 분포에 없는 값도 같은 중간순위 방식
        return p if hi else 100 - p
    return P
P_beta = pct([r['beta'] for r in REF], False); P_div = pct([r['div'] for r in REF]); P_pbr = pct([r['pbr'] if r['pbr'] is not None else 99 for r in REF], False)
P_r2 = pct([r['ret2y'] for r in REF]); P_r25 = pct([r['ret25'] for r in REF]); P_r26 = pct([r['ret26'] for r in REF])
P_beats = pct([r['beats'] for r in REF]); P_exc = pct([r['excess_avg'] for r in REF]); P_mdd = pct([r['mdd'] for r in REF]); P_cdb = pct([r['crash_day_beat'] for r in REF])
P_ic = pct([r['inst_crash'] for r in REF]); P_cum = pct([r['inst'] + r['frgn'] for r in REF]); P_frc = pct([r['frgn_ratio_chg'] for r in REF]); P_fr = pct([r['frgn_ratio'] for r in REF])
ksh = [r['short'] for r in REF if r.get('short') is not None]
def shscore(v, kospi):
    if not kospi or v is None: return 50
    below = sum(1 for x in ksh if x < v); eq = sum(1 for x in ksh if x == v)
    return 100 - ((below + (max(eq, 1) - 1) / 2) / (len(ksh) - 1) * 100)
def secscore(s):
    s = sec.get(s); return 50 if not s else min(100, s['lift'] / 3 * 100)

def score(x):
    d = (P_beta(x['beta']) + P_div(x['div']) + P_pbr(x['pbr'] if x['pbr'] is not None else 99) + (100 if x['profit_years'] == 4 else (x['profit_years'] or 0) * 25 * 0.6)) / 4
    h = (P_beats(x['beats']) + P_exc(x['excess_avg']) + P_mdd(x['mdd']) + P_cdb(x['crash_day_beat'])) / 4
    g = (P_r2(x['ret2y']) + P_r25(x['ret25']) + P_r26(x['ret26'])) / 3
    fl = (P_ic(x['inst_crash']) * 2 + P_cum(x['inst'] + x['frgn']) + P_frc(x['frc'])) / 4
    cm = (P_fr(x['frgn_ratio']) + shscore(x['short'], x['kospi']) + secscore(x['sector'])) / 3
    return dict(d1_def=round(d, 1), d1_hold=round(h, 1), d1_grow=round(g, 1), d1_flow=round(fl, 1), d1_com=round(cm, 1), d1_total=round(0.30 * d + 0.20 * h + 0.20 * g + 0.15 * fl + 0.15 * cm, 1))

def inputs(r):
    f = F[r['code']]
    need = ('beta', 'mdd', 'crash_day_beat', 'beats', 'excess_avg', 'inst', 'frgn', 'inst_crash', 'frgn_ratio', 'frc_20250102', 'ret2y')
    miss = [k for k in need if f.get(k) is None or (isinstance(f.get(k), float) and np.isnan(f[k]))]
    return dict(beta=f.get('beta'), mdd=f.get('mdd'), crash_day_beat=f.get('crash_day_beat'), beats=f.get('beats'), excess_avg=f.get('excess_avg'),
                inst=f.get('inst'), frgn=f.get('frgn'), inst_crash=f.get('inst_crash'), frgn_ratio=f.get('frgn_ratio'), frc=f.get('frc_20250102'), ret2y=f.get('ret2y'),
                div=r['div'] or 0, pbr=r['pbr'], profit_years=r['profit_years'], ret25=r['ret_2025'], ret26=r['ret_ytd'],
                short=r.get('short'), kospi=r['market'] == '코스피', sector=C[r['code']]['sector'] if r['code'] in C else None), miss

# 1) 정합 점검: 성장 종목 100개를 KRX 입력으로 다시 계산해 원래 점수와 비교
rows = []
for r in D:
    if r['code'] in C:
        x, miss = inputs(r)
        if miss: continue
        s = score(x); o = C[r['code']]
        rows.append({k: s[k] for k in s} | {'o_' + k: o[v] for k, v in (('d1_def', 's_def'), ('d1_hold', 's_hold'), ('d1_grow', 's_grow'), ('d1_flow', 's_flow'), ('d1_com', 's_com'), ('d1_total', 'total'))})
K = pd.DataFrame(rows); cal = {}
print('정합 점검 종목', len(K))
for k in ('d1_def', 'd1_hold', 'd1_grow', 'd1_flow', 'd1_com', 'd1_total'):
    cal[k] = (round(K[k].corr(K['o_' + k]), 3), round(float(np.median(np.abs(K[k] - K['o_' + k]))), 2))
    print(f'{k:9s} 상관 {cal[k][0]}  차이 중앙값 {cal[k][1]}')

# 2) 성장 조건 밖 150개 채우기
tot_ref = sorted(r['total'] for r in REF); done = 0; skipped = []
for r in D:
    if r['code'] in C: continue
    x, miss = inputs(r)
    if miss: skipped.append((r['name'], miss)); continue
    s = score(x); r.update(s); done += 1
    pos = 1 + sum(1 for t in tot_ref if t > s['d1_total'])
    nn = r.setdefault('_n', {})
    for k in ('d1_total', 'd1_def', 'd1_hold', 'd1_grow', 'd1_flow', 'd1_com'): nn.pop(k, None)
    base = '성장 조건 밖 종목이라 같은 식·같은 기준(성장 종목 250개 분포)으로 KRX 자료에서 다시 계산'
    nn['d1_total_x'] = f'{base}. 성장 종목 250개 사이에 넣으면 {pos}위 수준'
    for k in ('d1_def', 'd1_hold', 'd1_grow', 'd1_flow'): nn[k + '_x'] = base
    nn['d1_com_x'] = base + ('. 업종 배율은 원래 업종 분류(WICS)가 없어 원래 규칙대로 중립 50' + ('' if x['kospi'] else ', 코스닥 공매도 잔고도 원래 규칙대로 중립 50'))
print('채운 종목', done, '못 채운 종목', skipped)
json.dump(D, open(J, 'w'), ensure_ascii=False, separators=(',', ':'))
json.dump(cal, open('/tmp/d1_cal_scores.json', 'w'), ensure_ascii=False)
N = [r for r in D if r['code'] not in C and r.get('d1_total') is not None]
N.sort(key=lambda r: -r['d1_total'])
for r in N[:12]: print(r['name'], r['d1_total'], r['d1_def'], r['d1_hold'], r['d1_grow'], r['d1_flow'], r['d1_com'], r['_n']['d1_total_x'][-12:])
print('분포', st.median([r['d1_total'] for r in N]), 'vs 원래', st.median(tot_ref))
