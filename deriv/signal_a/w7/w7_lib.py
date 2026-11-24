# -*- coding: utf-8 -*-
"""Signal A W7 — X1 에서 남은 것. 미리 정한 목록은 w7/SPEC.md, 이 파일은 그대로 구현한다(run.py 가 부른다).

  (가) X1 이 '확인 불가'로 둔 후보의 거래일을 git 옛 기록(extract.py 가 옮겨 둔 것)에서 되살려 네 거름에 넣는다.
  (나) 갈래 D 의 보유 1일 후보에 '1일 꼴' 반증(①′②′만 바꿈, 참고 판정)을 원래 꼴과 나란히 적는다.
  (다) verdicts.csv 전체로 다시 매긴 상위 100위 가운데 X1 대상이 아닌 새 대상을 같은 네 거름에 넣는다.
  갈래별 '해마다 고르는 절차' 20개를 묶음 P(X1 순위 + 되살림)·묶음 V((다) 순위)로 다시 돌린다(모두 160개).
기준 숫자·네 거름·반증 8개는 sa_judge.py·sa_s3.py·x1/run.py 것을 그대로 불러 쓴다(여기서 바꾸지 않는다). x1/ 결과에는 쓰지 않는다.
조각 = 갈래 하나(A·B·C·D). 환경 변수 W7_LAB_CACHE = extract.py 가 쓴 폴더(꼭 있어야 함).
"""
import glob
import importlib.util
import json
import math
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
SA = os.path.dirname(HERE)
for _p_ in (SA, HERE):
    if _p_ not in sys.path: sys.path.insert(0, _p_)
import sa_common as C  # noqa: E402
import sa_judge as J  # noqa: E402
import sa_s3 as S3  # noqa: E402
import rank as RK  # noqa: E402


def _load_x1():
    """x1/run.py 를 읽기만 해서 그 함수(lab_check·recon_c·falsify_one·four·overlap_watch …)를 그대로 쓴다."""
    if 'sa_x1_run' in sys.modules: return sys.modules['sa_x1_run']
    spec = importlib.util.spec_from_file_location('sa_x1_run', os.path.join(SA, 'x1', 'run.py')); m = importlib.util.module_from_spec(spec)
    sys.modules['sa_x1_run'] = m; spec.loader.exec_module(m)
    return m


X = _load_x1()
TRACK = 'w7'
G4 = 'ABCD'
NJ = max(1, min(4, os.cpu_count() or 1))
OUT = os.path.join(HERE, 'out')
M_WF = 2 * 4 * len(X.PROCS)                    # 160 — 묶음 2 × 갈래 4 × 20
BUNDLES = {'P': 'X1 순위 + 되살림', 'V': 'verdicts 로 다시 매긴 상위 100'}
UNK = '확인 불가(거래일 기록 없음)'
D1_NAMES = [('①′', '', '장중에 늦게 매수(어림): 매수가 = 그날 (고가+저가)÷2'), ('②′', '가', '장중에 일찍 청산(어림): 청산가 = 그날 (고가+저가+종가)÷3'),
            ('②′', '나', '밤을 넘겨 조금 늦게 청산: 청산 = 다음 거래일 시가')]
NOT_INCLUDED = [
    '연구소 코드로 규칙을 처음부터 다시 계산하기(고정 자료로) — 옛 기록에도 없는 후보는 여전히 확인 불가',
    '열이 없어 건너뛴 옛 회차(갈래 A 1~16·B 1~10)의 후보를 순위에 넣기',
    '상위 100위 밖(예: 상위 300위)·갈래를 섞은 묶음·고른 것 전부 쓰기·합의 비율 10%·30%·적중 문턱 75%·90%',
    '1일 꼴 반증의 다른 어림(분봉·야간 선물로 실제 장중 값 쓰기 — 고정 자료에 없음), 보유 2~3일 규칙에 맞춘 꼴, 갈래 D 밖 보유 1일 후보에 적용',
    '묶음을 그 해까지 나온 순위만으로 다시 짜기(연구소가 2026-11 에야 시작돼 할 수 없음 — 절차 숫자는 기운 숫자)',
    '코스피200 선물·ETF 로 사고파는 판(Signal A 기준은 코스피 지수)',
]
BIAS = ('상위 100개라는 묶음 자체가 전체 기간(2026년까지) 결과로 뽑힌 것이라, 이 \'다음 해 성적\'도 좋게 나오는 쪽으로 기운다. '
        'Signal A 줄기의 다음 해 성적(묶음도 미리 정함)과 같은 값으로 읽으면 안 된다.')

_p, _pp, _sum, _cut, table = S3._p, S3._pp, S3._sum, S3._cut, S3.table
hv, yn, fmt_p = X.hv, X.yn, X.fmt_p


def n_parts():
    return len(G4)


# ------------------------------------------------------------------ 거래일 기록(extract.py 가 옮겨 둔 것)
def _df(rows):
    return X._norm(pd.DataFrame(rows, columns=['signal', 'exit'])) if rows else X._norm(None)


def load_cache(g, ids, quick, log):
    """{id: [기록, …]} — 기록 = dict(desc, direction, trades, trades_dev, rounds_tree, rounds_hist). 맞지 않으면 멈춘다."""
    cache = os.environ.get('W7_LAB_CACHE', '').strip()
    if not cache: raise RuntimeError('환경 변수 W7_LAB_CACHE 가 없음 — extract.py 를 먼저 돌려(판다스 최신판) 그 폴더를 줘야 함')
    p = os.path.join(cache, f'lab_trades_{g}.json')
    if not os.path.exists(p): raise RuntimeError(f'갈래 {g}: 옮겨 둔 거래일 파일이 없음({p}) — extract.py 를 먼저 돌려야 함')
    Z = json.load(open(p, encoding='utf-8'))
    if Z.get('quick') and not quick: raise RuntimeError(f'갈래 {g}: 옮겨 둔 기록이 시험용(--quick)으로 만든 것 — 옛 기록 전부로 다시 만들어야 함')
    files = glob.glob(os.path.join(RK.LAB, RK.BR[g], 'round_*', '*', 'candidates.pkl'))
    if int(Z.get('tree_files', -1)) != len(files): raise RuntimeError(f"갈래 {g}: 옮겨 둔 기록의 파일 수({Z.get('tree_files')})가 저장소의 candidates.pkl 수({len(files)})와 다름")
    miss = set(ids) - set(Z.get('target_ids', []))
    if miss: raise RuntimeError(f'갈래 {g}: extract.py 가 본 대상과 run.py 의 대상이 다름(빠진 id {len(miss)}개, 예: {sorted(miss)[:2]})')
    idx = {}
    for c in Z['cands']:
        if c['id'] not in ids: continue
        idx.setdefault(c['id'], []).append({'desc': c.get('desc'), 'direction': c.get('direction'), 'trades': _df(c['trades']),
                                            'trades_dev': (_df(c['trades_dev']) if c.get('trades_dev') is not None else None),
                                            'rounds_tree': [int(r) for r in c.get('rounds_tree', [])], 'rounds_hist': [int(r) for r in c.get('rounds_hist', [])]})
    log.append(f"{g}: 지금 저장소 거래일 파일 {Z.get('tree_files')}개 + git 옛 기록에서 되살려 읽은 파일 {Z.get('hist_files')}개"
               f"(회차 {(Z.get('hist_rounds') or ['–'])[0]}~{(Z.get('hist_rounds') or ['–'])[-1]})를 연구소와 같은 환경(판다스 {Z.get('pandas')})에서 날짜 글자로 옮긴 뒤 읽음(extract.py)")
    return idx


def _cdict(v):
    c = {'trades': v['trades']}
    if v.get('trades_dev') is not None: c['trades_dev'] = v['trades_dev']
    return c


def find_trades(D, g, row, idx, FQ, use_hist=True):
    """SPEC 2절. 반환 (출처, 메모, 확인 결과 또는 None, 거래표 또는 None). use_hist=False = 지금 저장소 기록만(X1 이 이미 구한 후보를 X1 과 같게 다시 읽을 때)."""
    vers = idx.get(str(row['id']), []); rnd = int(row['round']); src = UNK; note = ''; ck = None
    L = [v for v in vers if rnd in v['rounds_tree']]
    if L:
        v = next((x for x in L if x['desc'] == row['desc']), L[0]); ck = X.lab_check(D, row, _cdict(v)); src = '그 회차 기록'
    else:
        opts = []
        for v in vers:
            if v['desc'] != row['desc']: continue
            opts += [(abs(r - rnd), -r, 0, r, v) for r in v['rounds_tree']] + ([(abs(r - rnd), -r, 1, r, v) for r in v['rounds_hist']] if use_hist else [])
        opts.sort(key=lambda o: o[:3]); tried = {}; bad = None
        for dist, _nr, hist, r, v in opts:
            if id(v) not in tried: tried[id(v)] = X.lab_check(D, row, _cdict(v))
            k = tried[id(v)]
            if k['dev_ok']:
                ck = k; note = f'{r}회차 기록'
                src = ('옛 기록(그 회차, 앞 구간 숫자 일치)' if dist == 0 else '옛 기록(다른 회차, 앞 구간 숫자 일치)') if hist else '다른 회차 기록(앞 구간 숫자 일치)'
                break
            if bad is None: bad = (r, k['dev_n'])
        if ck is None:
            if g == 'C' and FQ is not None and not opts:
                tr, why = X.recon_c(row, *FQ)
                if tr is None: note = why
                else:
                    k = X.lab_check(D, row, {'trades': tr})
                    if k['dev_ok']: ck = k; src = '다시 만듦(미국 지표, 앞 구간 숫자 일치)'
                    else: note = f"다시 만든 신호의 앞 구간 숫자가 순위표와 다름({k['dev_n']}건 대 {float(row['dev_n']):.0f}건) — 쓰지 않음"
            elif bad is not None: note = f"같은 id·설명은 {len(tried)}가지 기록에 있으나 앞 구간 숫자가 다름(가장 가까운 {bad[0]}회차 기록 {bad[1]}건, 순위표 {float(row['dev_n']):.0f}건) — 쓰지 않음"
            elif vers: note = 'id 는 기록에 있으나 설명이 다름 — 쓰지 않음'
            else: note = '옛 기록에도 같은 id 없음'
    x = None
    if ck is not None:
        x = ck['x1']; x = x[(x['signal'] >= C.START) & (x['exit'] <= C.END)].reset_index(drop=True)
        if not len(x): src = UNK; note = '기록은 있으나 2010~끝 날짜 사이 거래가 없음'; ck = None; x = None
    return src, note, ck, x


# ------------------------------------------------------------------ (나) 1일 꼴 반증
def d1_refit(D, B, key, d, t0, fz):
    """SPEC 5절. t0 = 판정과 같은 독립 거래(signal·exit·ret·ok), fz = 원래 꼴 반증 결과. 반환 (표 줄들, 요약 dict)."""
    n0 = len(t0)
    if n0 < S3.MIN_PCT or fz.get('verdict') == '판정 불가' or not fz.get('tests'): return [], {'n_hold': None, 'verdict': '판정 불가', 'tests': {}}
    td = D.td; e = td.searchsorted(pd.DatetimeIndex(t0['signal']), side='right'); x = td.get_indexer(pd.DatetimeIndex(t0['exit'])); n = D.n
    hl2 = (D.h + D.l) / 2.0; hlc3 = (D.h + D.l + D.c) / 3.0; i = np.arange(n); e1 = i + 1
    f1 = lambda ee, xx: D.c[xx] / hl2[ee] - 1; f2a = lambda ee, xx: hlc3[xx] / D.o[ee] - 1; f2b = lambda ee, xx: D.o[xx + 1] / D.o[ee] - 1
    R = []; ok_ = []
    for (no, sub, name), fn, nxt in zip(D1_NAMES, (f1, f2a, f2b), (0, 0, 1)):
        b = np.full(n, np.nan); m = e1 + nxt < n
        with np.errstate(invalid='ignore', divide='ignore'):
            rb = fn(e1[m], e1[m]); b[np.flatnonzero(m)[np.isfinite(rb)]] = (d * rb[np.isfinite(rb)] > 0).astype(float)
            v = (x >= 0) & (e <= x) & (e < n) & (x + nxt < n); r = np.full(n0, np.nan); r[v] = fn(e[v], x[v])
        v = v & np.isfinite(r); k = int(v.sum()); hit = float((d * r[v] > 0).mean()) if k else None
        base = C.base_for(D, t0[v], 1, d, base_y=b) if k else None
        ok = bool(k >= S3.MIN_PCT and k >= S3.KEEP * n0 - 1e-9 and hit is not None and base is not None and hit - base >= S3.MARGIN - 1e-12)
        R.append({'후보': key, '시험': no, '시험갈래': sub, '이름': name, '독립거래': k, '원래의_비율': round(k / n0, 3), '적중': (None if hit is None or k < S3.MIN_PCT else round(hit, 4)),
                  '바탕': (None if base is None else round(base, 4)), '차이': (None if hit is None or base is None or k < S3.MIN_PCT else round(hit - base, 4)),
                  '수익합계': (round(float((d * r[v]).sum()), 5) if k else None), '버팀': ok, '비고': '바탕 = 같은 채점으로 잰 같은 해 아무 날(보유 1일)'})
        ok_.append(ok)
    res = {'1': bool(ok_[0]), '2': bool(ok_[1] and ok_[2])}
    for t in '345678': res[t] = bool(fz['tests'].get(t))
    k = int(sum(res.values())); verdict = '버팀' if k >= 7 else ('부분' if k >= 5 else '무너짐')
    R.append({'후보': key, '시험': '종합', '시험갈래': '', '이름': '1일 꼴 종합(①′②′ + 원래 꼴 ③~⑧)', '독립거래': n0, '원래의_비율': None, '적중': None, '바탕': None, '차이': None, '수익합계': None,
              '버팀': verdict == '버팀', '비고': f"8개 중 {k}개 버팀 → {verdict} (원래 꼴은 {fz.get('n_hold')}개)"})
    return R, {'n_hold': k, 'verdict': verdict, 'tests': res}


# ------------------------------------------------------------------ 후보 하나 재기(일꾼)
def eval_fixed(D, B, refs, sp):
    """고정 규칙 하나: X1 4절과 같은 계산(x1/run.py run_fixed 의 한 줄). (나)의 1일 꼴은 갈래 D·보유일 가운뎃값 1일일 때만."""
    g = sp['g']; pr = sp['pr']; d = int(pr['direction']); tr = sp['tr']; key = sp['key']; iters = sp['iters']; m = sp['m_fixed']
    c = {'id': sp['id'], 'track': TRACK, 'kind': 'fixed', 'family': pr.get('family'), 'desc': pr['desc'], 'direction': d, 'hold': None, 'trades': tr}
    rf = J.judge_one(D, c, m, iters)
    t0 = C.score(tr, d, D.K)['t']; t16 = t0[t0['signal'] >= X.Y16][['signal', 'exit']].reset_index(drop=True) if len(t0) else X._norm(None)
    r16 = J.judge_one(D, dict(c, kind='wf', trades=t16), m, iters)
    R, fz = X.falsify_one(D, B, key, d, tr, rf, iters, 3)
    R16, fz16 = X.falsify_one(D, B, key + ':2016~', d, t16, r16, iters, 2)
    f1, f2, f3, f4 = X.four(r16, rf, fz); _, g2, g3, g4 = X.four(r16, r16, fz16)
    ov, ovs = X.overlap_watch(D, refs, d, t0)
    orows = [{'후보': key, '종류': '고정 규칙', '갈래': g, '출처구분': sp['origin_ko'], **o} for o in ov]
    for x in R: x['구간'] = '전체(주 판정)'
    for x in R16: x['구간'] = '2016~(참고)'
    row = {'key': key, '갈래': g, '출처구분': sp['origin_ko'], 'x1순위': sp['x1rank'], 'v순위': sp['vrank'], '순위': (sp['x1rank'] if sp['x1rank'] is not None else sp['vrank']),
           '연구소등급': pr['grade'], 'id': pr['id'], '설명': pr['desc'], '가족': pr.get('family'), '방향': d, '회차': int(pr['round']),
           '거래일출처': sp['src'], '연구소_전체n': pr.get('all_n'), '연구소_전체적중': pr.get('all_hit'), '연구소_윌슨하한': pr.get('all_lb'), '신호수': int(len(tr)), '보유일_가운뎃값': rf['hold'],
           '독립거래': rf['all_n'], '적중': hv(rf['all_hit'], rf['all_n']), '아무날': hv(rf['base'], rf['all_n']), '차이': hv(rf['edge'], rf['all_n']), '수익합계': round(rf['all_sum'], 5),
           '앞n': rf['p1_n'], '앞적중': hv(rf['p1_hit'], rf['p1_n']), '뒤n': rf['p2_n'], '뒤적중': hv(rf['p2_hit'], rf['p2_n']),
           '코스피_통과숫자': bool(rf['goal_pass']), '코스피_관찰숫자': bool(rf['watch_pass']),
           'n16': r16['all_n'], '적중16': hv(r16['all_hit'], r16['all_n']), '아무날16': hv(r16['base'], r16['all_n']), '차이16': hv(r16['edge'], r16['all_n']), '수익합계16': round(r16['all_sum'], 5),
           '거름1': f1, '거름2': f2, '거름2_큰변동해_판정불가': bool(rf.get('c33_big') is None), '거름3': f3, '반증버틴수': fz['n_hold'], '반증종합': fz['verdict'],
           '거름4': f4, '가짜p': rf['fake_p'], '가짜p_보정뒤': rf['fake_p_adj'], '가짜_곱한수': int(m), '넷다': bool(f1 and f2 and f3 and f4), '통과한_거름수': int(f1) + int(f2) + int(f3) + int(f4),
           'y26_n': rf['y26_n'], 'y26_hit': hv(rf['y26_hit'], rf['y26_n']), 'ex26_hit': hv(rf['ex26_hit'], rf['ex26_n']), 'ex26_base': hv(rf['ex26_base'], rf['ex26_n']),
           'big_n': rf['big_n'], 'big_hit': hv(rf['big_hit'], rf['big_n']), 'big_base': hv(rf['big_base'], rf['big_n']),
           '참고16_거름2': g2, '참고16_거름3': g3, '참고16_반증버틴수': fz16['n_hold'], '참고16_거름4': g4, '참고16_가짜p': r16['fake_p'], '참고16_넷다': bool(f1 and g2 and g3 and g4),
           '뿌리표시': X.root_tag(pr['id'], pr['desc']), '관찰목록과': ovs, 'by_year': json.dumps(rf['by_year'], ensure_ascii=False)}
    d1rows = _d1_into(D, B, row, key, d, t0, fz, g, rf['hold'], f1, f2, f4)
    return {'kind': 'fixed', 'row': row, 'frows': R + R16, 'orows': orows, 'd1rows': d1rows}


def _d1_into(D, B, row, key, d, t0, fz, g, hold, f1, f2, f4):
    """갈래 D·보유 1일이면 1일 꼴 결과를 줄에 붙인다. 아니면 빈칸('해당 없음')."""
    row.update({'1일꼴_해당': False, '거름3_1일꼴': None, '반증버틴수_1일꼴': None, '반증종합_1일꼴': None, '넷다_1일꼴': None})
    if g != 'D' or int(hold or 0) != 1: return []
    R1, s1 = d1_refit(D, B, key, d, t0, fz)
    if s1['n_hold'] is None: return []
    f3b = bool(s1['n_hold'] == 8)
    row.update({'1일꼴_해당': True, '거름3_1일꼴': f3b, '반증버틴수_1일꼴': s1['n_hold'], '반증종합_1일꼴': s1['verdict'], '넷다_1일꼴': bool(f1 and f2 and f3b and f4)})
    return R1


def eval_wf(D, B, refs, sp):
    """절차 하나: X1 5절과 같은 계산(x1/run.py run_wf 의 한 줄)."""
    g = sp['g']; p = sp['p']; d = sp['d']; tr = sp['tr']; key = sp['key']; iters = sp['iters']
    c = {'id': sp['id'], 'track': TRACK, 'kind': 'wf', 'family': sp['family'], 'desc': sp['desc'], 'direction': d, 'hold': None, 'trades': tr}
    r = J.judge_one(D, c, M_WF, iters)
    R, fz = X.falsify_one(D, B, key, d, tr, r, iters, 2)
    for x in R: x['구간'] = '2016~(절차)'
    f1, f2, f3, f4 = X.four(r, r, fz)
    t0 = C.score(tr, d, D.K)['t']; ov, ovs = X.overlap_watch(D, refs, d, t0)
    orows = [{'후보': key, '종류': '절차', '갈래': g, '출처구분': f"묶음 {sp['bundle']}", **o} for o in ov]
    row = {'key': key, '갈래': g, '묶음': sp['bundle'], 'id': sp['id'], '설명': sp['desc'], '꼴': p[0], '최소건수': p[1], '쓰는수': p[2], '만드는법': p[3], '방향': d, '묶음_규칙수': sp['n_rules'], '신호수': int(len(tr)),
           '거래있는_해수': int(len(r['by_year'])), '보유일_가운뎃값': r['hold'],
           '독립거래': r['all_n'], '적중': hv(r['all_hit'], r['all_n']), '아무날': hv(r['base'], r['all_n']), '차이': hv(r['edge'], r['all_n']), '수익합계': round(r['all_sum'], 5),
           '앞n_2016_2023': r['p1_n'], '앞적중': hv(r['p1_hit'], r['p1_n']), '뒤n_2024_': r['p2_n'], '뒤적중': hv(r['p2_hit'], r['p2_n']),
           '통과숫자_35건_85': bool(r['goal_pass']), '관찰숫자_35건_80': bool(r['watch_pass']),
           '거름1': f1, '거름2': f2, '거름2_큰변동해_판정불가': bool(r.get('c33_big') is None), '거름3': f3, '반증버틴수': fz['n_hold'], '반증종합': fz['verdict'],
           '거름4': f4, '가짜p': r['fake_p'], '가짜p_보정뒤': r['fake_p_adj'], '가짜_곱한수': M_WF, '넷다': bool(f1 and f2 and f3 and f4), '통과한_거름수': int(f1) + int(f2) + int(f3) + int(f4),
           'y26_n': r['y26_n'], 'y26_hit': hv(r['y26_hit'], r['y26_n']), 'ex26_hit': hv(r['ex26_hit'], r['ex26_n']), 'ex26_base': hv(r['ex26_base'], r['ex26_n']),
           'big_n': r['big_n'], 'big_hit': hv(r['big_hit'], r['big_n']), 'big_base': hv(r['big_base'], r['big_n']),
           '1위로_가장_자주_뽑힌_순위': sp['mode'], '1위로_뽑힌_해수': sp['mode_n'], '관찰목록과': ovs, 'by_year': json.dumps(r['by_year'], ensure_ascii=False)}
    d1rows = _d1_into(D, B, row, key, d, t0, fz, g, r['hold'], f1, f2, f4)
    return {'kind': 'wf', 'row': row, 'frows': R, 'orows': orows, 'd1rows': d1rows}


def _work(specs):
    """일꾼 하나: 자료를 한 번 읽고 맡은 후보들을 차례로 잰다."""
    if not specs: return []
    D = C.Data(); B = S3.Base(D); log = []; refs = X.watch_refs(D, log)
    out = [(eval_fixed if sp['what'] == 'fixed' else eval_wf)(D, B, refs, sp) for sp in specs]
    if out and log: out[0]['log'] = log
    return out


def _par(specs):
    """joblib 4코어(일꾼마다 자료를 따로 읽음). 프로세스 실행이 안 되는 환경이면 차례로 돈다."""
    nj = min(NJ, max(1, len(specs) // 4))
    if nj > 1:
        try:
            from joblib import Parallel, delayed
            os.environ['PYTHONPATH'] = os.pathsep.join([SA, HERE] + [x for x in os.environ.get('PYTHONPATH', '').split(os.pathsep) if x and x not in (SA, HERE)])
            res = Parallel(n_jobs=nj)(delayed(_work)(specs[k::nj]) for k in range(nj)); out = [None] * len(specs)
            for k in range(nj): out[k::nj] = res[k]
            return out
        except Exception as e:                                       # noqa: BLE001
            print('joblib 실패 → 차례로 계산:', repr(e)[:200], flush=True)
    return _work(specs)


# ------------------------------------------------------------------ 절차의 거래 만들기(x1/run.py run_wf 의 앞부분과 같은 계산)
def build_wf(D, g, bundle, rules, TR):
    """rules = 묶음의 규칙 순위(주 방향·거래일 있음), TR = {순위: 거래표}. 반환 ({절차: 거래표}, 해마다 고른 규칙 줄들, {(꼴, 건수): 1위 순위 목록})."""
    d = X.WF_DIR[g]; S = {}
    for rk in rules:
        t = C.score(TR[rk], d, D.K)['t']
        raw = TR[rk].drop_duplicates('signal').sort_values('signal').reset_index(drop=True)
        raw = raw[D.td.get_indexer(pd.DatetimeIndex(raw['exit'])) >= 0].reset_index(drop=True)
        S[rk] = {'ex': pd.DatetimeIndex(t['exit']) if len(t) else pd.DatetimeIndex([]), 'ok': (t['ok'].values.astype(int) if len(t) else np.zeros(0, dtype=int)), 'raw': raw, 'yr': pd.DatetimeIndex(raw['signal']).year.values}
    parts = {p: [] for p in X.PROCS}; picks = []
    for Y, _end in C.wf_splits():
        y0 = pd.Timestamp(f'{Y}-01-01'); stats = []
        for rk in rules:
            m = np.asarray(S[rk]['ex'] < y0); n = int(m.sum()); k = int(S[rk]['ok'][m].sum())
            if n: stats.append((rk, n, k, k / n, C.wilson(k, n)[0]))
        for nm in X.NMINS:
            nmin = 35 if nm == 'n35' else max(12, int(round(35 * (Y - 2010) / 17)))
            for sh, thr in X.SHAPES:
                sel = sorted([s for s in stats if s[1] >= nmin and s[3] >= thr - 1e-9], key=lambda s: (-s[4], -s[1], s[0]))
                picks.append({'갈래': g, '묶음': bundle, '해': Y, '꼴': sh, '최소건수': nm, 'n_min': nmin, '묶음_규칙수': len(rules), '건수_채운_규칙수': sum(s[1] >= nmin for s in stats), '고른_규칙수': len(sel),
                              '상위20_순위': ' '.join(str(s[0]) for s in sel[:20]), '1위_순위': (sel[0][0] if sel else None), '1위_n': (sel[0][1] if sel else None), '1위_맞음': (sel[0][2] if sel else None)})
                for cn in X.COUNTS:
                    U = sel[:cn]
                    if not U: continue
                    fr = []
                    for o, s in enumerate(U):
                        x = S[s[0]]['raw'][S[s[0]]['yr'] == Y]
                        if len(x): fr.append(x.assign(order=o))
                    if not fr: continue
                    al = pd.concat(fr, ignore_index=True)
                    parts[(sh, nm, cn, 'any')].append(al.sort_values(['signal', 'order'], kind='stable').drop_duplicates('signal', keep='first')[['signal', 'exit']])
                    if cn != 1 and len(U) >= 2:
                        need = max(2, math.ceil(0.2 * len(U))); al['ep'] = D.td.get_indexer(pd.DatetimeIndex(al['exit']))
                        gb = al.groupby('signal')['ep'].agg(['size', 'median']); gb = gb[gb['size'] >= need]
                        if len(gb):
                            ep = np.floor(gb['median'].values + 0.5).astype(int)
                            parts[(sh, nm, cn, 'cons')].append(pd.DataFrame({'signal': gb.index.values, 'exit': D.td[ep].values}))
    top1 = {}
    for x in picks:
        if x['1위_순위'] is not None: top1.setdefault((x['꼴'], x['최소건수']), []).append(int(x['1위_순위']))
    trades = {p: (X._norm(pd.concat(parts[p], ignore_index=True)) if parts[p] else X._norm(None)) for p in X.PROCS}
    return trades, picks, top1


def proc_id(bundle, g, p): return f'WF7{bundle}_{g}_{p[0]}_{p[1]}_top{p[2]}_{p[3]}'


def proc_desc(bundle, g, p, d):
    nm = '35건' if p[1] == 'n35' else '줄인 건수(2016년 12 … 2026년 33건)'
    what = 'X1 대상(순위표 상위 100개, 옛 기록으로 되살린 것 포함)' if bundle == 'P' else 'verdicts 전체로 다시 매긴 상위 100개'
    return (f"{X.BR_NAME[g]} {what} 묶음에서 해마다 그 전 자료로 {nm}·적중 {85 if p[0] == 'goal' else 80}% 이상인 규칙을 골라 윌슨 하한 상위 {p[2]}개 사용 · "
            f"{X.HOW_KO[p[3]]} 매수(청산은 그 규칙대로) → {'오름' if d > 0 else '내림'}")


def root_of(g, cid, desc):
    return f"연구소 {X.BR_NAME[g]}" + ('(분기물 콜벽)' if X.root_tag(cid, desc) else '')


# ------------------------------------------------------------------ 조각 = 갈래 하나
def run_part(i, n, quick=False):
    g = G4[(i - 1) % len(G4)]; iters = 50 if quick else J.C32['iters']; log = []
    D = C.Data(); T = RK.targets()[g]; px = T['x1']; v = T['v']
    idx = load_cache(g, set(T['ids']), quick, log)
    FQ = None
    if g == 'C':
        try:
            F = pd.read_csv(os.path.join(X.US_OUT, 'features_kr.csv.gz'), index_col=0, parse_dates=True); Q = pd.read_csv(os.path.join(X.US_OUT, 'features_pct.csv.gz'), index_col=0, parse_dates=True)
        except Exception as e:                                       # noqa: BLE001
            raise RuntimeError(f'갈래 C: 미국 지표 파일(deriv/us/out)을 못 읽음({type(e).__name__}) — 신호일을 다시 만들 수 없음') from e
        F = F[F.index <= C.END]; Q = Q[Q.index <= C.END].reindex(F.index); ea, how = X._exit_after(); FQ = (F, Q, F.index, ea)
        log.append(f'C: 미국 지표 파일 {F.index[0].date()}~{F.index[-1].date()} {F.shape[1]}개, 청산일 계산 = {how}')
    lab_tr = X.lab_trials(g, len(px) + len(v)); m_fixed = max(1, lab_tr)
    vmap = {r['desc']: int(r['rank']) for _, r in v.iterrows()}
    # ---- 대상 하나하나의 거래일
    units = []
    for _, r in px.iterrows():
        was_unk = str(r['src']).startswith('확인 불가')
        units.append({'origin': 'R' if was_unk else 'X1', 'row': r.to_dict(), 'x1rank': int(r['rank']), 'vrank': vmap.get(r['desc'])})
    for _, r in v[~v['in_x1'].astype(bool)].iterrows():
        units.append({'origin': 'V', 'row': r.to_dict(), 'x1rank': None, 'vrank': int(r['rank'])})
    TRx = {}; TRv = {}
    for u in units:
        src, note, ck, x = find_trades(D, g, u['row'], idx, FQ, use_hist=(u['origin'] != 'X1'))
        u.update({'src': src, 'note': note, 'tr': x, 'has_tdev': (None if ck is None else bool(ck['has_tdev'])),
                  'lab_dev_ok': (None if ck is None else bool(ck['dev_ok'])), 'lab_p2_ok': (None if ck is None else bool(ck['p2_ok'])), 'lab_all_ok': (None if ck is None else bool(ck['all_ok']))})
        if u['origin'] == 'X1' and x is None: log.append(f"{g}: X1 이 거래일을 구했던 {u['x1rank']}위({u['row']['id']})를 이번에는 못 구함({note}) — 후보 파일에서 빠짐")
        if x is not None:
            if u['x1rank'] is not None: TRx[u['x1rank']] = x
            if u['vrank'] is not None: TRv[u['vrank']] = x
    okey = {'X1': 'X1', 'R': 'R', 'V': 'V'}; oko = {'X1': 'X1 이 이미 넣음', 'R': '(가) 되살림', 'V': '(다) 새 대상'}
    for u in units:
        rk = u['x1rank'] if u['origin'] != 'V' else u['vrank']
        u['id'] = f"{okey[u['origin']]}_{g}{rk:03d}"; u['key'] = f"w7:{u['id']}" if u['origin'] != 'X1' else f'x1:{g}{rk:03d}'
    # ---- 재야 할 것
    specs = []; lim = {'R': 0, 'V': 0, 'X1': 0}
    for u in units:
        if u['tr'] is None: continue
        if u['origin'] == 'X1' and g != 'D': continue                # X1 이 넣은 것은 다시 재지 않는다(갈래 D 만 1일 꼴 때문에 다시)
        if quick:
            if lim[u['origin']] >= 2: continue
            lim[u['origin']] += 1
        pr = dict(u['row'])
        specs.append({'what': 'fixed', 'g': g, 'key': u['key'], 'id': u['id'], 'origin': u['origin'], 'origin_ko': oko[u['origin']], 'x1rank': u['x1rank'], 'vrank': u['vrank'], 'pr': pr,
                      'src': u['src'], 'tr': u['tr'], 'm_fixed': m_fixed, 'iters': iters})
    d = X.WF_DIR[g]; picks = []; wf_tr = {}
    rules_p = [int(r) for r, dd in zip(px['rank'], px['direction']) if int(r) in TRx and int(dd) == d]
    rules_v = [int(r) for r, dd in zip(v['rank'], v['direction']) if int(r) in TRv and int(dd) == d]
    for bundle, rules, TR in (('P', rules_p, TRx), ('V', rules_v, TRv)):
        trades, pk, top1 = build_wf(D, g, bundle, rules, TR); picks += pk
        for p in X.PROCS:
            tl = top1.get((p[0], p[1]), []); mode = (max(set(tl), key=lambda z: (tl.count(z), -z)) if tl else None)
            pid = proc_id(bundle, g, p); wf_tr[pid] = trades[p]
            specs.append({'what': 'wf', 'g': g, 'bundle': bundle, 'p': p, 'd': d, 'id': pid, 'key': f'w7:{pid}', 'family': f'해마다 고름({g}, 묶음 {bundle})', 'desc': proc_desc(bundle, g, p, d),
                          'tr': trades[p], 'n_rules': len(rules), 'mode': mode, 'mode_n': (tl.count(mode) if tl else 0), 'iters': iters})
    print(f"{g}: X1 대상 {len(px)}(확인 불가였던 것 {sum(u['origin'] == 'R' for u in units)}) · (다) 상위 {len(v)}(새 대상 {sum(u['origin'] == 'V' for u in units)}) · "
          f"거래일 구함: 되살림 {sum(u['origin'] == 'R' and u['tr'] is not None for u in units)} · 새 대상 {sum(u['origin'] == 'V' and u['tr'] is not None for u in units)} · 잴 것 {len(specs)}개", flush=True)
    res = _par(specs)
    fx = []; wf = []; frows = []; orows = []; d1rows = []
    for r in res:
        (fx if r['kind'] == 'fixed' else wf).append(r['row']); frows += r['frows']; orows += r['orows']; d1rows += r['d1rows']
        for x in r.get('log', []):
            if x not in log: log.append(x)
    # ---- 표준 후보(판정·W8 이 읽음): 거름에 넣은 고정 규칙 전부 + 절차
    fxby = {r['key']: r for r in fx}; cands = []
    for u in units:
        if u['tr'] is None: continue
        r = fxby.get(u['key']); row = u['row']
        cands.append({'id': u['id'], 'family': f"연구소 갈래 {g} 고정 규칙({oko[u['origin']]})", 'desc': f"[연구소 {X.BR_NAME[g]}] {row['desc']}", 'direction': int(row['direction']), 'hold': None, 'kind': 'fixed',
                      'trades': u['tr'][['signal', 'exit']].reset_index(drop=True), 'root': root_of(g, row['id'], row['desc']),
                      'params': {'branch': g, 'origin': u['origin'], 'x1_rank': u['x1rank'], 'v_rank': u['vrank'], 'lab_id': row['id'], 'lab_round': int(row['round']), 'lab_grade': row.get('grade'),
                                 'src': u['src'], 'key': u['key'], 'pass4': (bool(r['넷다']) if r is not None else None)}})
    for r in wf:
        cands.append({'id': r['id'], 'family': f"해마다 고름({g}, 묶음 {r['묶음']})", 'desc': r['설명'], 'direction': d, 'hold': None, 'kind': 'wf', 'trades': wf_tr[r['id']][['signal', 'exit']].reset_index(drop=True),
                      'root': f"연구소 {X.BR_NAME[g]} 묶음", 'params': {'branch': g, 'bundle': r['묶음'], 'shape': r['꼴'], 'nmin': r['최소건수'], 'count': r['쓰는수'], 'how': r['만드는법'], 'pass4': bool(r['넷다'])}})
    # ---- 대상표(출처 포함)
    cols_u = ['src', 'note', 'has_tdev', 'lab_dev_ok', 'lab_p2_ok', 'lab_all_ok']
    ux = {u['x1rank']: u for u in units if u['x1rank'] is not None}; uv = {u['vrank']: u for u in units if u['vrank'] is not None}
    px2 = px.copy()
    for k in cols_u: px2['w7_' + k] = [ux[int(r)][k] for r in px2['rank']]
    px2['w7_n_signals'] = [0 if ux[int(r)]['tr'] is None else len(ux[int(r)]['tr']) for r in px2['rank']]; px2['v_rank'] = [ux[int(r)]['vrank'] for r in px2['rank']]
    v2 = v.copy(); v2.insert(0, '갈래', g)
    for k in cols_u: v2[k] = [uv[int(r)][k] for r in v2['rank']]
    v2['n_signals'] = [0 if uv[int(r)]['tr'] is None else len(uv[int(r)]['tr']) for r in v2['rank']]; v2['x1_rank'] = [uv[int(r)]['x1rank'] for r in v2['rank']]
    v2['w7_id'] = [uv[int(r)]['id'] for r in v2['rank']]
    return {'g': g, 'quick': bool(quick), 'iters': iters, 'pool_x1': px2, 'pool_v': v2, 'info': T['info'], 'fx': fx, 'wf': wf, 'frows': frows, 'orows': orows, 'd1rows': d1rows, 'picks': picks,
            'cands': cands, 'log': log, 'lab_trials': int(lab_tr), 'n_specs': len(specs)}


# ------------------------------------------------------------------ merge
def best_proc(rows):
    a = [r for r in rows if r['독립거래'] >= J.C31['n'] and r['차이'] is not None] or [r for r in rows if r['독립거래'] >= S3.MIN_PCT and r['차이'] is not None]
    return max(a, key=lambda r: (r['차이'], r['독립거래'])) if a else None


def _b(v):
    return str(v).strip().lower() == 'true' if not isinstance(v, (bool, np.bool_)) else bool(v)


def _js(o):
    if hasattr(o, 'item'): return o.item()
    if isinstance(o, pd.Timestamp): return str(o.date())
    return str(o)


def merge(parts, quick=False):
    parts = list(parts or []); bad = [i + 1 for i in range(n_parts()) if i >= len(parts) or parts[i] is None]
    if bad: raise RuntimeError(f'W7: 조각 {bad} 결과가 없음 — 합치지 않음(조용히 넘기지 않는다)')
    if any(bool(p.get('quick')) != bool(quick) for p in parts): raise RuntimeError('W7: 조각이 시험용(--quick)과 섞여 있음')
    P = {p['g']: p for p in parts}; now = pd.Timestamp.now(tz='Asia/Seoul').strftime('%Y-%m-%d %H:%M'); iters = parts[0]['iters']; log = []
    for p in parts: log += [x for x in p['log'] if x not in log]
    os.makedirs(OUT, exist_ok=True)
    # ---- X1 이 이미 넣은 줄(읽기만)
    fp = os.path.join(SA, 'x1', 'out', 'fixed.csv')
    if not os.path.exists(fp): raise RuntimeError('x1/out/fixed.csv 가 없음 — X1 결과를 합칠 수 없음')
    X1F = pd.read_csv(fp); x1rows = X1F.to_dict('records')
    for r in x1rows:
        for k in ('거름1', '거름2', '거름3', '거름4', '넷다', '참고16_넷다', '코스피_통과숫자', '코스피_관찰숫자', '거름2_큰변동해_판정불가'): r[k] = _b(r[k])
        r['출처구분'] = 'X1 이 이미 넣음'; r['x1순위'] = int(r['순위']); r['v순위'] = None
        for k in list(r):
            if isinstance(r[k], float) and not np.isfinite(r[k]): r[k] = None
    w7fx = [r for g in G4 for r in P[g]['fx']]; wf = [r for g in G4 for r in P[g]['wf']]
    new = [r for r in w7fx if r['출처구분'] != 'X1 이 이미 넣음']; redo = {r['key']: r for r in w7fx if r['출처구분'] == 'X1 이 이미 넣음'}
    d1cols = ['1일꼴_해당', '거름3_1일꼴', '반증버틴수_1일꼴', '반증종합_1일꼴', '넷다_1일꼴']; n_diff = 0
    PV = pd.concat([P[g]['pool_v'] for g in G4], ignore_index=True); PX = pd.concat([P[g]['pool_x1'] for g in G4], ignore_index=True)
    vr = {(r['갈래'], int(r['x1_rank'])): int(r['rank']) for _, r in PV.iterrows() if pd.notna(r['x1_rank'])}
    for r in x1rows:
        r['v순위'] = vr.get((r['갈래'], r['x1순위'])); q = redo.get(r['key'])
        for k in d1cols: r[k] = (q[k] if q is not None else (False if k == '1일꼴_해당' else None))
        if q is not None and (q['독립거래'] != r['독립거래'] or bool(q['넷다']) != r['넷다'] or q['반증버틴수'] != r['반증버틴수']): n_diff += 1
    if n_diff: log.append(f'갈래 D: X1 이 넣은 후보를 다시 잰 숫자가 X1 표와 다른 것 {n_diff}개(합친 표에는 X1 숫자를 그대로 두고 1일 꼴 칸만 붙임)')
    fx_all = x1rows + new
    if not quick and not new: raise RuntimeError('W7: 새로 거름에 넣은 후보가 0개 — 옛 기록·verdicts 를 못 읽었을 수 있어 멈춤')
    if not fx_all or len(wf) != M_WF: raise RuntimeError(f'W7: 결과가 비정상(고정 규칙 {len(fx_all)}개·절차 {len(wf)}개, 절차는 {M_WF}개여야 함)')
    # ---- 표 저장
    front = ['key', '갈래', '출처구분', 'x1순위', 'v순위']
    FA = pd.DataFrame(fx_all); FA = FA[front + [c for c in FA.columns if c not in front]]
    FA.to_csv(os.path.join(OUT, 'fixed_all.csv'), index=False, encoding='utf-8')
    pd.DataFrame(wf).to_csv(os.path.join(OUT, 'wf.csv'), index=False, encoding='utf-8')
    pd.DataFrame([x for g in G4 for x in P[g]['picks']]).to_csv(os.path.join(OUT, 'wf_picks.csv'), index=False, encoding='utf-8')
    fc = ['후보', '구간', '시험', '시험갈래', '이름', '독립거래', '원래의_비율', '적중', '바탕', '차이', '수익합계', 'p', '버팀', '비고']
    pd.DataFrame([x for g in G4 for x in P[g]['frows']]).rename(columns={'갈래': '시험갈래'}).reindex(columns=fc).to_csv(os.path.join(OUT, 'falsify.csv'), index=False, encoding='utf-8')
    pd.DataFrame([x for g in G4 for x in P[g]['d1rows']]).reindex(columns=[c for c in fc if c not in ('구간', 'p')]).to_csv(os.path.join(OUT, 'falsify_d1.csv'), index=False, encoding='utf-8')
    pd.DataFrame([x for g in G4 for x in P[g]['orows']]).to_csv(os.path.join(OUT, 'overlap_watch.csv'), index=False, encoding='utf-8')
    PX.to_csv(os.path.join(OUT, 'pool_x1.csv'), index=False, encoding='utf-8'); PV.drop(columns=['lb_pos'], errors='ignore').to_csv(os.path.join(OUT, 'pool_v.csv'), index=False, encoding='utf-8')
    # ---- 수 세기
    unk = lambda s: s.astype(str).str.startswith('확인 불가')
    S = {}
    for g in G4:
        px = PX[PX['갈래'] == g]; pv = PV[PV['갈래'] == g]; F = [r for r in fx_all if r['갈래'] == g]; W = [r for r in wf if r['갈래'] == g]
        was = unk(px['src']); still = was & unk(px['w7_src']); newv = pv[~pv['in_x1'].astype(bool)]
        o = lambda s: [r for r in F if r['출처구분'] == s]
        hist = px.loc[was & ~still, 'w7_src'].astype(str)
        S[g] = {'x1_target': int(len(px)), 'x1_unverifiable_before': int(was.sum()), 'restored': int((was & ~still).sum()), 'restored_from_history': int(hist.str.startswith('옛 기록').sum()),
                'restored_other': int((~hist.str.startswith('옛 기록')).sum()), 'x1_unverifiable_after': int(still.sum()),
                'v_target': int(len(pv)), 'v_overlap_x1': int(pv['in_x1'].astype(bool).sum()), 'v_new': int(len(newv)), 'v_new_checked': len(o('(다) 새 대상')), 'v_new_unverifiable': int(unk(newv['src']).sum()),
                'n_target': int(len(px) + len(newv)), 'n_checked': len(F), 'n_unverifiable': int(still.sum() + unk(newv['src']).sum()),
                'f1': sum(r['거름1'] for r in F), 'f2': sum(r['거름2'] for r in F), 'f3': sum(r['거름3'] for r in F), 'f4': sum(r['거름4'] for r in F),
                'pass4_fixed': sum(r['넷다'] for r in F), 'pass4_x1': sum(r['넷다'] for r in o('X1 이 이미 넣음')), 'pass4_restored': sum(r['넷다'] for r in o('(가) 되살림')),
                'pass4_new': sum(r['넷다'] for r in o('(다) 새 대상')), 'checked_restored': len(o('(가) 되살림')),
                'pass4_wf': sum(r['넷다'] for r in W), 'pass4_wf_P': sum(r['넷다'] for r in W if r['묶음'] == 'P'), 'pass4_wf_V': sum(r['넷다'] for r in W if r['묶음'] == 'V'),
                'rules_P': next((r['묶음_규칙수'] for r in W if r['묶음'] == 'P'), 0), 'rules_V': next((r['묶음_규칙수'] for r in W if r['묶음'] == 'V'), 0),
                'verdict_rounds': P[g]['info']['rounds'], 'verdict_skipped': P[g]['info']['skipped'], 'verdict_uniq': P[g]['info']['uniq'], 'lab_trials': P[g]['lab_trials']}
    tot = lambda k: int(sum(S[g][k] for g in G4))
    best = {(g, b): best_proc([r for r in wf if r['갈래'] == g and r['묶음'] == b]) for g in G4 for b in 'PV'}

    def bline(g, b):
        x = best[(g, b)]
        if x is None: return f'{X.BR_NAME[g]} 묶음 {b}: 거래 10건 이상인 절차 없음'
        return (f"{X.BR_NAME[g]} 묶음 {b}: {x['독립거래']}거래 {_p(x['적중'], x['독립거래'])}(아무 날 {_p(x['아무날'], x['독립거래'])}, 차이 {_pp(x['차이'], x['독립거래'])}) — "
                f"{X.SH_KO[x['꼴']]}·{X.NM_KO[x['최소건수']]}·상위 {x['쓰는수']}개·{X.HOW_KO[x['만드는법']]} — 네 거름 {'모두 통과' if x['넷다'] else str(x['통과한_거름수']) + '개 통과'} (기운 숫자)")
    DF = [r for r in fx_all if r['갈래'] == 'D' and r.get('1일꼴_해당') is True]; DW = [r for r in wf if r['갈래'] == 'D' and r.get('1일꼴_해당') is True]
    d_refit = {'n_fixed_d': sum(r['갈래'] == 'D' for r in fx_all), 'n_applied_fixed': len(DF), 'orig_pass3_fixed': sum(r['거름3'] for r in DF), 'refit_pass3_fixed': sum(bool(r['거름3_1일꼴']) for r in DF),
               'orig_pass4_fixed': sum(r['넷다'] for r in DF), 'refit_pass4_fixed': sum(bool(r['넷다_1일꼴']) for r in DF),
               'n_applied_wf': len(DW), 'orig_pass3_wf': sum(r['거름3'] for r in DW), 'refit_pass3_wf': sum(bool(r['거름3_1일꼴']) for r in DW),
               'orig_pass4_wf': sum(r['넷다'] for r in DW), 'refit_pass4_wf': sum(bool(r['넷다_1일꼴']) for r in DW),
               'note': '1일 꼴은 참고 판정(①′②′만 바꿈, 기준 숫자 그대로). 통과 수·최종 판정에는 원래 꼴만 쓴다.'}
    passers = sorted([r for r in fx_all if r['넷다']], key=lambda r: (r['출처구분'] == 'X1 이 이미 넣음', r['갈래'], r['순위'] if r['순위'] is not None else 999))
    pl = [{'id': (r['key'].replace('w7:', '') if r['key'].startswith('w7:') else 'X1_' + r['key'].split(':')[1]), 'key': r['key'], 'branch': r['갈래'], 'origin': r['출처구분'], 'desc': r['설명'], 'direction': r['방향'],
           'n': r['독립거래'], 'hit': r['적중'], 'edge': r['차이'], 'n16': r['n16'], 'hit16': r['적중16'], 'edge16': r['차이16'], 'fake_p': r['가짜p'], 'falsify_hold': r['반증버틴수'], 'sum': r['수익합계'],
           'root': r['뿌리표시'], 'watch_overlap': r['관찰목록과']} for r in passers[:50]]
    wfp = [r for r in wf if r['넷다']]
    notes = [BIAS, '거름 ①(가)는 결과를 보고 고른 규칙의 숫자다(고정 규칙의 2016~2026 거래). 진짜 다음 해 성적은 절차뿐이고 그것도 묶음이 결과로 뽑혀 기운 숫자다.',
             '연구소 등급·순위는 코스피200 선물 기준이고, 이 줄기의 적중은 모두 코스피 지수 기준이다.',
             f"X1 이 이미 넣은 129개는 다시 세지 않았다(가짓수는 새로 넣은 {len(new)}개 + 절차 {len(wf)}개)."] + log
    fam = {}
    for g in G4:
        fam[f'가_되살린_고정규칙_갈래{g}'] = S[g]['checked_restored']; fam[f'다_새대상_고정규칙_갈래{g}'] = S[g]['v_new_checked']
        fam[f'나_절차_묶음P_갈래{g}'] = sum(r['갈래'] == g and r['묶음'] == 'P' for r in wf); fam[f'나_절차_묶음V_갈래{g}'] = sum(r['갈래'] == g and r['묶음'] == 'V' for r in wf)
    n_tested = int(sum(fam.values()))
    summ = {'at': now, 'data_end': str(C.END.date()), 'iters': iters, 'quick': bool(quick), 'n_tested': n_tested, 'families': fam,
            'n_target': tot('n_target'), 'n_checked': tot('n_checked'), 'n_unverifiable': tot('n_unverifiable'), 'n_restored': tot('restored'),
            'n_restored_from_history': tot('restored_from_history'), 'n_x1_unverifiable_before': tot('x1_unverifiable_before'), 'n_new_targets': tot('v_new'), 'n_new_checked': tot('v_new_checked'),
            'pass4_fixed': tot('pass4_fixed'), 'pass4_fixed_x1': tot('pass4_x1'), 'pass4_fixed_restored': tot('pass4_restored'), 'pass4_fixed_new': tot('pass4_new'),
            'pass4_wf': tot('pass4_wf'), 'n_wf': len(wf), 'pass4_list': pl,
            'pass4_wf_list': [{'id': r['id'], 'branch': r['갈래'], 'bundle': r['묶음'], 'desc': r['설명'], 'n': r['독립거래'], 'hit': r['적중'], 'base': r['아무날'], 'edge': r['차이'], 'fake_p': r['가짜p'],
                               'fake_p_adj': r['가짜p_보정뒤'], 'sum': r['수익합계'], 'watch_overlap': r['관찰목록과']} for r in wfp],
            'by_track': S, 'best_wf': {g: {b: bline(g, b) for b in 'PV'} for g in G4},
            'best_wf_rows': {f'{g}{b}': best[(g, b)] for g in G4 for b in 'PV'}, 'd_refit': d_refit, 'notes': notes}
    json.dump(summ, open(os.path.join(OUT, 'summary.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=_js)
    md = summary_md(now, iters, quick, S, summ, fx_all, new, wf, best, DF, DW, d_refit, PX, PV, log)
    open(os.path.join(OUT, 'summary.md'), 'w', encoding='utf-8').write(md)
    cands = [c for g in G4 for c in P[g]['cands']]
    x1pass = {r['key']: r['넷다'] for r in x1rows}
    for c in cands:
        if c['kind'] == 'fixed' and c['params'].get('origin') == 'X1': c['params']['pass4'] = bool(x1pass.get(c['params']['key'], False))
    ids = [c['id'] for c in cands]
    if len(ids) != len(set(ids)): raise RuntimeError('W7: 후보 id 가 겹침')
    meta = {'n_tested': n_tested, 'families': fam, 'm_fixed': int(sum(S[g]['lab_trials'] for g in G4)), 'm_wf': M_WF, 'not_included': list(NOT_INCLUDED), 'parts_failed': [],
            'notes': [f"대상 {summ['n_target']}개(X1 251 + 새 대상 {summ['n_new_targets']}) 중 거름에 넣은 것 {summ['n_checked']}개 · 여전히 확인 불가 {summ['n_unverifiable']}개 · 옛 기록 등으로 되살린 것 {summ['n_restored']}개",
                      f"네 거름(X1 꼴) 모두 통과: 고정 규칙 {summ['pass4_fixed']}개(X1 {summ['pass4_fixed_x1']} + 되살림 {summ['pass4_fixed_restored']} + 새 대상 {summ['pass4_fixed_new']}) · 절차 {len(wf)}개 중 {summ['pass4_wf']}개 — 표는 out/fixed_all.csv·out/wf.csv",
                      '이 줄기의 고정 규칙은 연구소가 전체 기간 결과를 보고 고른 것이고 X1 이 이미 넣은 129개도 후보 파일에 함께 들어 있다(가짓수에는 넣지 않음). ' + BIAS],
            'tables': ['fixed_all.csv', 'wf.csv', 'wf_picks.csv', 'falsify.csv', 'falsify_d1.csv', 'overlap_watch.csv', 'pool_x1.csv', 'pool_v.csv', 'summary.json'], 'quick': bool(quick)}
    return cands, meta


def summary_md(now, iters, quick, S, summ, fx_all, new, wf, best, DF, DW, d_refit, PX, PV, log):
    G = list(G4); M = []; s = summ
    M += [f'### W7 — X1 에서 남은 것 ({now}, 자료 끝 {C.END.date()})', '',
          '> 숫자·표·문장은 GitHub 가 w7/run.py 로 계산해 자동으로 쓴 것입니다(미리 정한 목록: w7/SPEC.md). 매매 기준: 코스피 지수, 신호 다음 날 시가 매수 → 그 후보의 청산일 종가 매도, 독립 거래, 단순 합. 표본 10개 미만은 %로 적지 않습니다.', '']
    if quick: M += ['**(시험용 실행 — 가짜 횟수와 대상 수를 줄였습니다. 이 숫자는 쓰지 마세요.)**', '']
    M += ['#### 결론', '',
          f"1. **(가) 옛 기록 되살리기**: X1 이 '확인 불가'로 둔 {s['n_x1_unverifiable_before']}개 가운데 **{s['n_restored']}개의 거래일을 되찾았습니다**(git 옛 기록에서 {s['n_restored_from_history']}개). "
          f"되살린 것 중 네 거름을 모두 넘은 것은 **{s['pass4_fixed_restored']}개**입니다. X1 대상 가운데 여전히 확인 불가는 {sum(S[g]['x1_unverifiable_after'] for g in G)}개입니다.",
          f"2. **(다) verdicts 전체로 다시 매긴 상위 100위**: 새 대상 {s['n_new_targets']}개(" + '·'.join(f"{g} {S[g]['v_new']}" for g in G) + f") 가운데 거래일을 구한 {s['n_new_checked']}개를 넣었고, "
          f"네 거름을 모두 넘은 것은 **{s['pass4_fixed_new']}개**입니다.",
          f"3. 합치면 대상 {s['n_target']}개 중 {s['n_checked']}개를 거름에 넣었고, **네 거름 모두 통과는 {s['pass4_fixed']}개**(X1 {s['pass4_fixed_x1']} + 되살림 {s['pass4_fixed_restored']} + 새 대상 {s['pass4_fixed_new']}; "
          + '·'.join(f"{g} {S[g]['pass4_fixed']}" for g in G) + ')입니다. **이 후보들은 전체 기간 결과를 보고 고른 규칙이라 거름 ①의 숫자는 Signal A 의 \'다음 해 성적\'과 같은 뜻이 아닙니다.**',
          f"4. '해마다 그 전 자료로 고르는 절차' {len(wf)}개(묶음 P = X1 순위 + 되살림, 묶음 V = 다시 매긴 상위 100, 갈래마다 20개씩) 가운데 네 거름을 모두 넘은 것은 **{s['pass4_wf']}개**입니다. **{BIAS}**",
          f"5. **(나) 갈래 D '1일 꼴' 반증(참고 판정)**: 보유 1일인 갈래 D 고정 규칙 {d_refit['n_applied_fixed']}개에서 반증 8개 모두 버팀이 원래 꼴 {d_refit['orig_pass3_fixed']}개 → 1일 꼴 {d_refit['refit_pass3_fixed']}개, "
          f"네 거름 모두 통과가 원래 꼴 {d_refit['orig_pass4_fixed']}개 → 1일 꼴 {d_refit['refit_pass4_fixed']}개입니다(절차는 {d_refit['n_applied_wf']}개 중 {d_refit['orig_pass4_wf']} → {d_refit['refit_pass4_wf']}). 통과 수에는 원래 꼴만 셉니다.",
          f"6. 이번에 더한 시험 가짓수는 {s['n_tested']:,}가지(되살린 고정 규칙 {sum(S[g]['checked_restored'] for g in G)} + 새 대상 {s['n_new_checked']} + 절차 {len(wf)})입니다. X1 의 209가지는 다시 세지 않았습니다. 최종 후보·관찰 목록은 바꾸지 않았습니다.", '']
    M += ['#### 갈래별 숫자 — 고정 규칙(네 거름은 X1 과 같은 꼴)', '']
    M += table(G, [lambda g: X.BR_NAME[g], lambda g: S[g]['x1_target'], lambda g: f"{S[g]['x1_unverifiable_before']} → {S[g]['x1_unverifiable_after']}", lambda g: f"{S[g]['restored']}({S[g]['restored_from_history']})",
                   lambda g: f"{S[g]['v_target']}(겹침 {S[g]['v_overlap_x1']})", lambda g: f"{S[g]['v_new']} / {S[g]['v_new_checked']} / {S[g]['v_new_unverifiable']}", lambda g: S[g]['n_checked'],
                   lambda g: f"{S[g]['f1']}·{S[g]['f2']}·{S[g]['f3']}·{S[g]['f4']}", lambda g: f"**{S[g]['pass4_fixed']}**", lambda g: f"{S[g]['pass4_x1']} + {S[g]['pass4_restored']} + {S[g]['pass4_new']}"],
               ['갈래', 'X1 대상', 'X1 확인 불가(전 → 뒤)', '되살린 수(그중 git 옛 기록)', '(다) 다시 매긴 상위(X1 대상과 겹침)', '(다) 새 대상 / 넣음 / 확인 불가', '거름에 넣은 것(X1 포함)',
                '①·②·③·④ 통과', '넷 다 통과', 'X1 + 되살림 + 새 대상'])
    M += ['', f"- (다) 순위는 회차마다의 판정 전부(verdicts.csv)에 같은 회차 반증 결과(redteam.csv 의 버팀)를 붙여 X1 과 같은 규칙으로 매겼습니다. 열이 없어 건너뛴 옛 회차: " + '·'.join(f"{g} {S[g]['verdict_skipped']}" for g in G) + '개.',
          '- 되살린 거래일은 id 와 설명이 모두 같고, 그 거래일로 연구소 방식(선물, 앞 구간)으로 다시 잰 숫자가 순위표와 똑같을 때만 썼습니다.', '']
    why = PX[PX['w7_src'].astype(str).str.startswith('확인 불가') & PX['src'].astype(str).str.startswith('확인 불가')]
    if len(why):
        k = why['w7_note'].fillna('').astype(str).map(lambda x: '옛 기록에도 같은 id 없음' if x.startswith('옛 기록에도') else ('id 는 있으나 설명이 다름' if x.startswith('id 는') else ('같은 id·설명은 있으나 앞 구간 숫자가 다름' if x.startswith('같은 id') else (x[:30] or '기타'))))
        M += ['X1 대상 가운데 여전히 확인 불가인 까닭: ' + ' · '.join(f'{a} {b}개' for a, b in k.value_counts().items()), '']
    np_ = sorted([r for r in new if r['넷다']], key=lambda r: (r['갈래'], r['출처구분'], r['순위']))
    M += ['#### 새로 네 거름을 모두 넘은 후보(되살림·새 대상)', '']
    if np_:
        M += ['**이 표의 적중·차이는 모두 결과를 보고 고른 규칙의 숫자입니다(해마다 그 전 자료로 고른 다음 해 성적이 아님).**', '']
        M += table(np_[:40], [lambda r: r['갈래'], lambda r: r['출처구분'], lambda r: r['순위'], lambda r: r['연구소등급'], lambda r: _cut(r['설명'], 100), lambda r: '오름' if r['방향'] > 0 else '내림', lambda r: r['독립거래'],
                              lambda r: _p(r['적중'], r['독립거래']), lambda r: _pp(r['차이'], r['독립거래']), lambda r: f"{r['n16']}건 {_p(r['적중16'], r['n16'])} / {_pp(r['차이16'], r['n16'])}",
                              lambda r: fmt_p(r['가짜p']), lambda r: f"{r['반증버틴수']}/8", lambda r: _sum(r['수익합계']), lambda r: r['뿌리표시'] or '–', lambda r: _cut(r['관찰목록과'], 60)],
                   ['갈래', '어디서', '순위', '연구소 등급(선물)', '조건 설명', '방향', '독립 거래(2010~)', '코스피 지수 적중(전체 기간)', '아무 날과 차이', '2016~: 거래·적중 / 차이', '가짜 p(보정 전)', '반증', '수익 합계',
                    '글자로 본 뿌리', 'Signal A 관찰 목록과'])
        if len(np_) > 40: M.append('\n(40개만 — 전부는 out/fixed_all.csv)')
        nq = sum(bool(r['뿌리표시']) for r in np_); ns = sum(str(r['관찰목록과']).startswith(('사실상 같은', '한쪽이', '많이 겹침')) for r in np_)
        M += ['', f"- 새로 넘은 {len(np_)}개 가운데 '분기물 콜벽' 글자가 든 것 {nq}개, Signal A 관찰 목록과 보유 기간이 많이 겹치는 것(50% 이상) {ns}개입니다. 같은 뿌리의 규칙(문턱만 조금 다른 것)이 여러 개 올라 있을 수 있습니다."]
    else:
        M += ['**없습니다.** 되살린 후보와 새 대상 가운데 네 거름을 모두 넘은 것은 0개입니다.']
    M += ['', '#### 갈래별 \'해마다 고르는 절차\'(묶음 P·V, 갈래마다 20개씩)', '', f'> **조심: {BIAS}**', '']
    gb = [(g, b) for g in G for b in 'PV']; W = lambda g, b: [r for r in wf if r['갈래'] == g and r['묶음'] == b]; cnt = lambda rows, k: sum(bool(r[k]) for r in rows)
    M += table(gb, [lambda x: X.BR_NAME[x[0]], lambda x: f"{x[1]}({BUNDLES[x[1]]})", lambda x: S[x[0]]['rules_' + x[1]], lambda x: sum(r['독립거래'] >= 30 for r in W(*x)),
                    lambda x: f"{cnt(W(*x), '거름1')}·{cnt(W(*x), '거름2')}·{cnt(W(*x), '거름3')}·{cnt(W(*x), '거름4')}", lambda x: f"**{cnt(W(*x), '넷다')}**",
                    lambda x: '없음' if best[x] is None else f"{best[x]['독립거래']}거래 {_p(best[x]['적중'], best[x]['독립거래'])} 대 {_p(best[x]['아무날'], best[x]['독립거래'])} ({_pp(best[x]['차이'], best[x]['독립거래'])})",
                    lambda x: '–' if best[x] is None else f"{fmt_p(best[x]['가짜p'])} → {fmt_p(best[x]['가짜p_보정뒤'])}",
                    lambda x: '–' if best[x] is None else ('**넷 다 통과**' if best[x]['넷다'] else f"{best[x]['통과한_거름수']}개 통과")],
               ['갈래', '묶음', '묶음의 규칙 수(주 방향·거래일 있음)', '독립 30건 이상 절차(20개 중)', '①·②·③·④ 통과', '넷 다 통과', '가장 좋은 절차: 다음 해 적중 대 아무 날(차이)', f'가짜 p(보정 전 → ×{M_WF})', '네 거름'])
    wfp = [r for r in wf if r['넷다']]
    if wfp:
        M += ['', f'네 거름을 모두 넘은 절차 {len(wfp)}개', '']
        M += table(wfp, [lambda r: r['갈래'], lambda r: r['묶음'], lambda r: f"{X.SH_KO[r['꼴']]} · {X.NM_KO[r['최소건수']]} · 상위 {r['쓰는수']}개 · {X.HOW_KO[r['만드는법']]}", lambda r: r['독립거래'],
                         lambda r: _p(r['적중'], r['독립거래']), lambda r: _p(r['아무날'], r['독립거래']), lambda r: _pp(r['차이'], r['독립거래']), lambda r: _sum(r['수익합계']),
                         lambda r: f"{fmt_p(r['가짜p'])} → {fmt_p(r['가짜p_보정뒤'])}", lambda r: f"{r['y26_n']}건 {_p(r['y26_hit'], r['y26_n'])}", lambda r: _cut(r['관찰목록과'], 60)],
                   ['갈래', '묶음', '절차', '독립 거래', '다음 해 적중', '같은 해 아무 날', '차이', '수익 합계', f'가짜 p(보정 전 → ×{M_WF})', '2026년', 'Signal A 관찰 목록과'])
    M += ['', '#### (나) 갈래 D — 보유 1일에 맞는 반증 꼴(참고 판정)', '',
          '원래 반증 ①(매수를 하루 늦춤)·②(하루 늦게 청산)는 하루짜리 사건 신호에는 다른 날을 사거나 보유를 두 배로 늘리는 꼴입니다. 1일 꼴은 ①′ 장중에 늦게 매수(어림: 그날 (고가+저가)÷2 에 매수), '
          '②′ 장중에 일찍 청산(어림: (고가+저가+종가)÷3)·밤을 넘겨 다음 날 시가 청산으로만 바꾸고 ③~⑧과 버팀 기준은 그대로 둡니다. **이 꼴은 X1 의 갈래 D 결과를 본 뒤 정한 것이라 참고 판정입니다.**', '']
    if DF or DW:
        M += table([('고정 규칙', DF, d_refit['n_fixed_d']), ('절차(묶음 P·V)', DW, sum(r['갈래'] == 'D' for r in wf))],
                   [lambda x: x[0], lambda x: x[2], lambda x: len(x[1]), lambda x: sum(r['거름3'] for r in x[1]), lambda x: sum(bool(r['거름3_1일꼴']) for r in x[1]),
                    lambda x: sum(r['반증종합'] == '버팀' for r in x[1]), lambda x: sum(r['반증종합_1일꼴'] == '버팀' for r in x[1]), lambda x: sum(r['넷다'] for r in x[1]), lambda x: sum(bool(r['넷다_1일꼴']) for r in x[1])],
                   ['갈래 D', '거름에 넣은 것', '보유 1일(1일 꼴 적용)', '반증 8개 모두: 원래 꼴', '반증 8개 모두: 1일 꼴', '종합 버팀(7개 이상): 원래 꼴', '종합 버팀: 1일 꼴', '넷 다 통과: 원래 꼴', '넷 다 통과: 1일 꼴(참고)'])
        d1p = sorted([r for r in DF if r['넷다_1일꼴']], key=lambda r: (r['순위'] if r['순위'] is not None else 999))
        if d1p:
            M += ['', f'1일 꼴로는 네 거름을 모두 넘는 갈래 D 고정 규칙 {len(d1p)}개(참고 — 통과로 세지 않음, 결과를 보고 고른 규칙의 숫자)', '']
            M += table(d1p[:20], [lambda r: r['출처구분'], lambda r: r['순위'], lambda r: _cut(r['설명'], 100), lambda r: r['독립거래'], lambda r: _p(r['적중'], r['독립거래']), lambda r: _pp(r['차이'], r['독립거래']),
                                  lambda r: f"{r['n16']}건 {_pp(r['차이16'], r['n16'])}", lambda r: fmt_p(r['가짜p']), lambda r: f"{r['반증버틴수']}/8 → {r['반증버틴수_1일꼴']}/8", lambda r: _sum(r['수익합계'])],
                       ['어디서', '순위', '조건 설명', '독립 거래', '적중(내림을 맞음으로)', '아무 날과 차이', '2016~ 거래·차이', '가짜 p', '반증: 원래 → 1일 꼴', '수익 합계'])
        M += ['', '- (고가+저가)÷2 와 (고가+저가+종가)÷3 은 실제로 그 값에 사고팔 수 있었다는 뜻이 아닙니다(하루 안 순서를 모름). 시험별 줄은 out/falsify_d1.csv.']
    else:
        M += ['- 1일 꼴을 적용할 갈래 D 후보(보유일 가운뎃값 1일, 독립 거래 10건 이상)가 없습니다.']
    M += ['', '#### 조심할 점', '',
          f"- **여전히 확인 불가 {s['n_unverifiable']}개**는 옛 기록에도 맞는 거래일이 없어 넣지 못했습니다(추정으로 채우지 않음). 넷 다 통과 수는 '넣은 것 가운데'의 수입니다.",
          '- 연구소 후보는 전체 기간 결과를 보고 고른 고정 규칙입니다. 거름 ①은 숫자 꼴만 맞춘 것이고, 진짜 \'다음 해 성적\'은 절차뿐입니다. 그 절차도 묶음이 결과를 보고 뽑힌 것이라 기운 숫자입니다.',
          '- (다)의 상위 100위는 최근 회차 후보가 많습니다(설명이 같은 후보는 가장 최근 회차 줄만 남기므로). 같은 뿌리의 규칙이 여러 개 올라 있어, 통과가 여러 개여도 서로 다른 신호가 여러 개라는 뜻이 아닙니다.',
          '- 연구소 등급·순위는 코스피200 선물 기준입니다. 이 표의 적중은 모두 코스피 지수 기준입니다(NOTES.md 1절).',
          '- 네 거름은 Signal A 최종 심사 때 결과를 본 뒤 총괄이 정한 것으로, CRITERIA.md 의 \'최종 후보\' 기준과 다릅니다. 새 자료에서 실제 신호 10건이 쌓이기 전에는 어느 것도 \'확정\'이라고 쓰지 않습니다.']
    if log: M += ['', '계산 중 적어 둔 것', ''] + [f'- {x}' for x in log]
    M += ['', f"근거 파일: w7/SPEC.md · out/fixed_all.csv(고정 규칙 전부) · out/wf.csv · out/wf_picks.csv · out/falsify.csv · out/falsify_d1.csv · out/pool_x1.csv · out/pool_v.csv · out/overlap_watch.csv · out/summary.json (가짜 {iters:,}번)", '']
    return '\n'.join(M)
