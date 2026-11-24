# -*- coding: utf-8 -*-
"""연구소 웹판용: 신뢰 가능 21개 가운데 '하루 늦춰 진입'·'첫 신호만(5일·3일)'을 뺀 18개 조건을 docs/lab/data/conds.json 으로 내보낸다.
조건 = 그 조건이 든 조합들의 거래를 같은 매수일 한 건으로 합친 것(맞음은 다수결, validate.py 와 같은 규칙). 대표 거래 = 다수결과 같은 결과를 낸 첫 조합(웹판 조합 순서)의 거래.
2026-11-24 사용자 지시: "웹판에 적중률 상위 20 제거, 신뢰 가능 21중 하루 늦춰 진입, 첫 신호만을 제외한 19 가지를 적중률 상위 20 위치에 같은 기능으로 대체".
"""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
LAB = sys.argv[1] if len(sys.argv) > 1 else '/home/claude/main/docs/lab/data'
T = json.load(open(os.path.join(LAB, 'trades.json'), encoding='utf-8'))
C = json.load(open(os.path.join(LAB, 'combos.json'), encoding='utf-8')); C = C.get('combos', C) if isinstance(C, dict) else C
order = {c['key']: i for i, c in enumerate(C)}; by = {c['key']: c for c in C}
CM = {m['rank']: m for m in json.load(open(os.path.join(HERE, 'cond_map.json'), encoding='utf-8'))}
V = {x['rank']: x for x in json.load(open(os.path.join(HERE, 'validate_out.json'), encoding='utf-8'))}
EXCL = {1: '하루 늦춰 진입', 20: '첫 신호만(5일)', 60: '첫 신호만(3일)'}
SHORT = {2: '상승 추세(60일선 위)', 3: '벽 물량 5일 증가', 4: 'Q 벽 바로 아래 ±1.5%', 6: '외국인 선물·현물 3일 순매수', 17: 'S&P·나스닥 상위10%(하락)',
         19: '코스피200 3일 상위20%(하락)', 21: '벽 물량 3일 증가', 25: '만기 21~40일 아님', 27: '둘 이상 동시 새 콜벽(1.5σ)', 35: '바닥 전 상태(5일 안)',
         38: '직전 120일 상승', 39: '직전 20일 상승', 77: '갈래 B 다시 매김·상위 1', 79: '갈래 B 다시 매김·상위 20', 80: '갈래 B 다시 매김·상위 5(20%)',
         81: '갈래 B 다시 매김·상위 5', 82: '갈래 B X1 대상·상위 1', 85: '갈래 B X1 대상·상위 5(20%)'}
out = []
for r in sorted(V):
    v = V[r]
    if v['v'] != '신뢰 가능' or r in EXCL: continue
    keys = sorted(CM[r]['keys'], key=lambda k: order[k])
    dirs = {by[k]['dir'] for k in keys}; assert len(dirs) == 1, (r, dirs)
    rows = {}
    for k in keys:
        for t in T.get(k, []): rows.setdefault(t[1], []).append((k, t))
    tr = []
    for buy in sorted(rows):
        L = rows[buy]; ok = 1 if sum(t[7] for _, t in L) / len(L) >= 0.5 else 0
        k, t = next((k, t) for k, t in L if t[7] == ok)
        tr.append(t)
    R = v['res']; assert len(tr) == R['전체']['n'], (r, len(tr), R['전체']['n'])
    hit = sum(t[7] for t in tr) / len(tr)
    out.append({'key': 'K%03d' % r, 'src': 'K', 'rank': r, 'name': CM[r]['name'], 'short': SHORT[r], 'dir': dirs.pop(), 'members': keys,
                'n': len(tr), 'hit': round(hit, 4), 'p1': [R['앞']['n'], round(R['앞']['hit'], 4)], 'p2': [R['뒤']['n'], round(R['뒤']['hit'], 4)],
                'base1': round(R['앞']['base'], 4), 'base2': round(R['뒤']['base'], 4), 'lb1': round(R['앞']['lb'], 4), 'lb2': round(R['뒤']['lb'], 4), 'p': R['전체']['p'],
                'sum': round(sum(t[6] for t in tr), 4), 'last': tr[-1][0], 'trades': tr})
out.sort(key=lambda x: (-x['hit'], -x['n']))
meta = {'made': '2026-11-24', 'rule': '그 조건이 든 조합들의 거래를 같은 매수일 한 건으로 합침(맞음 다수결). 대표 거래 = 다수결과 같은 결과의 첫 조합 거래.',
        'excluded': EXCL, 'judge': '앞·뒤 각 20건 이상 · 윌슨 95% 하한 > 같은 해 아무 날(같은 보유일) 맞음 비율 · 전체 이항 p < 0.05/189', 'from': 'combos.json·trades.json(같은 폴더) — 그 파일이 바뀌면 다시 만들 것(deriv/signal_a/x4/build_conds.py)'}
json.dump({'meta': meta, 'conds': out}, open(os.path.join(LAB, 'conds.json'), 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
for x in out: print(x['key'], x['short'], x['n'], x['hit'], x['p1'], x['p2'], len(x['members']))
print(len(out))
