# -*- coding: utf-8 -*-
"""연구소용 웹판 자료 내보내기 (deriv/labweb/AGENT.md, 2026-11-24 사용자 지시).

새로 계산하는 것은 '조합별 매매 날짜' 하나뿐이다. 그것도 X1(deriv/signal_a/x1/run.py)이 쓰는 함수를 그대로 불러
(rank_pool → attach_trades → sa_common.score) 같은 거래를 파일로 옮길 뿐이다. 판정·수익·거름 숫자는 x1/out 의 결과를 그대로 읽는다.

  combos.json  조합 표(갈래 A·B·C·D 상위 251개 = x1/out/pool.csv + fixed.csv, Signal A 관찰 목록 3개 = signals/final_v1.json,
               Signal A 2차 네 거름 45개 = s2/out/pool.csv·candidates.json + wN/out/cands.pkl)
  trades.json  조합별 독립 거래(신호일·매수일·매수가·매도일·매도가·코스피 등락·방향 반영 수익·맞음)
  prices.json  코스피 지수·코스피200 연속 선물 일봉(릴리스 signal-a-data-v1 고정 자료 — 거래 수익을 잰 바로 그 가격), 2026-11-20 까지
  meta.json    만든 때·확인 결과(내보낸 거래가 x1/out/fixed.csv 의 독립거래·수익합계와 같은지)

연구소·Signal A 결과 파일은 읽기만 한다. 거래일 기록이 없는 조합은 '거래 내역 없음'으로 두고 추정하지 않는다.
사용: X1_LAB_CACHE=… SA_DATA=… python deriv/labweb/export.py --out 폴더
"""
import argparse
import importlib.util
import json
import math
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DERIV = os.path.dirname(HERE)
SA = os.path.join(DERIV, 'signal_a')
X1 = os.path.join(SA, 'x1')
sys.path.insert(0, SA)
import sa_common as C  # noqa: E402

spec = importlib.util.spec_from_file_location('x1run', os.path.join(X1, 'run.py'))
R = importlib.util.module_from_spec(spec); spec.loader.exec_module(R)

WATCH = [(1, 't1', 'R_Q_b15_any_up1_none_any_d1_f1_h5_up', '전체_기간_성적_결과를_보고_고른_숫자'),
         (2, 't3', 'P_h5_allev_gb_q90', '다음_해_성적_그_전_자료로_고름'),
         (3, 't4', 't2_V_S10_T8_h5', '다음_해_성적_그_전_자료로_고름')]


def num(v, nd=4):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if not math.isfinite(f) else round(f, nd)


def yes(v):
    if isinstance(v, (bool, np.bool_)): return bool(v)
    return str(v).strip().lower() == 'true'


def trade_rows(D, t, d):
    """sa_common.score 가 채점한 독립 거래표 t → [신호일, 매수일, 매수가, 매도일, 매도가, 코스피 등락, 방향 반영 수익, 맞음]."""
    td = D.K.index; o = D.K['open'].values; c = D.K['close'].values; out = []
    for s, e, r, ok in zip(t['signal'], t['exit'], t['ret'], t['ok']):
        si = td.searchsorted(pd.Timestamp(s), side='right'); ei = td.get_indexer([pd.Timestamp(e)])[0]
        if si >= len(td) or ei < 0: continue
        out.append([str(pd.Timestamp(s).date()), str(td[si].date()), round(float(o[si]), 2), str(pd.Timestamp(e).date()), round(float(c[ei]), 2),
                    round(float(r), 5), round(float(d * r), 5), int(ok)])
    return out


def px_json(df, start):
    df = df[(df.index >= start) & (df.index <= C.END)].dropna()
    return {'d': [str(x.date()) for x in df.index], 'o': [round(float(v), 2) for v in df['open']], 'h': [round(float(v), 2) for v in df['high']],
            'l': [round(float(v), 2) for v in df['low']], 'c': [round(float(v), 2) for v in df['close']]}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--out', required=True); a = ap.parse_args(); os.makedirs(a.out, exist_ok=True)
    D = C.Data(); log = []; checks = {'same': 0, 'diff': [], 'no_trades': 0}
    pool = pd.read_csv(os.path.join(X1, 'out', 'pool.csv')); fixed = pd.read_csv(os.path.join(X1, 'out', 'fixed.csv'))
    FX = {(r['갈래'], int(r['순위'])): r for _, r in fixed.iterrows()}
    combos = []; trades = {}
    # 2차 W7 이 git 옛 기록에서 되살린 거래(X1 에서 '거래 내역 없음'이던 122개, 2026-11-24 사용자 지시 "전부 채워") — w7/out/cands.pkl 의 R_<key> + w7/out/fixed_all.csv 의 w7:R_<key>
    W7C = {x['id']: x for x in C.load_result('w7')[0] if x.get('kind') == 'fixed'}
    W7F = {r['key']: r for _, r in pd.read_csv(os.path.join(SA, 'w7', 'out', 'fixed_all.csv')).iterrows()}
    for g in 'ABCD':
        P, _ = R.rank_pool(g); P, TR = R.attach_trades(D, g, P, log)
        old = pool[pool['갈래'] == g]
        if list(P['id']) != list(old['id']):
            raise RuntimeError(f'갈래 {g}: 다시 매긴 순위가 x1/out/pool.csv 와 다름 — 내보내지 않음')
        for (_, pr), (_, po) in zip(P.iterrows(), old.iterrows()):
            rk = int(po['rank']); key = f'{g}{rk:03d}'; d = int(po['direction']); fx = FX.get((g, rk))
            row = {'key': key, 'src': g, 'rank': rk, 'round': int(po['round']), 'grade': po['grade'] if isinstance(po['grade'], str) else '–',
                   'id': po['id'], 'desc': po['desc'], 'family': po['family'], 'dir': d, 'trade_src': po['src'], 'trade_note': (po['src_note'] if isinstance(po['src_note'], str) else ''),
                   'lab': {'all_n': num(po['all_n'], 0), 'all_hit': num(po['all_hit']), 'all_lb': num(po['all_lb']), 'dev_n': num(po['dev_n'], 0), 'dev_hit': num(po['dev_hit']),
                           'p2_n': num(po['p2_n'], 0), 'p2_hit': num(po['p2_hit'])},
                   'has_trades': False}
            if rk in TR and fx is not None:
                sc = C.score(TR[rk], d, D.K); t = sc['t']; rows = trade_rows(D, t, d)
                same = (len(rows) == int(fx['독립거래'])) and abs(sc['sum'] - float(fx['수익합계'])) < 1e-4
                if same: checks['same'] += 1
                else: checks['diff'].append({'key': key, 'n': len(rows), 'fixed_n': int(fx['독립거래']), 'sum': round(sc['sum'], 5), 'fixed_sum': float(fx['수익합계'])})
                trades[key] = rows
                n = int(fx['독립거래']); s = float(fx['수익합계'])
                row.update({'has_trades': True, 'check': bool(same), 'n': n, 'hit': num(fx['적중']), 'base': num(fx['아무날']), 'edge': num(fx['차이']), 'sum': num(s, 5),
                            'avg': (num(s / n, 5) if n else None), 'last': (str(pd.Timestamp(TR[rk]['signal'].max()).date()) if len(TR[rk]) else None),
                            'n_sig': int(len(TR[rk])), 'hold': num(fx['보유일_가운뎃값'], 0),
                            'f': [yes(fx['거름1']), yes(fx['거름2']), yes(fx['거름3']), yes(fx['거름4'])], 'all4': yes(fx['넷다']),
                            'falsify': f"{int(fx['반증버틴수'])}/8", 'p': num(fx['가짜p']), 'big_na': yes(fx['거름2_큰변동해_판정불가']),
                            'p1': [num(fx['앞n'], 0), num(fx['앞적중'])], 'p2': [num(fx['뒤n'], 0), num(fx['뒤적중'])], 'overlap': fx['관찰목록과'] if isinstance(fx['관찰목록과'], str) else ''})
            elif ('R_' + key) in W7C and ('w7:R_' + key) in W7F:
                c7 = W7C['R_' + key]; f7 = W7F['w7:R_' + key]
                if f7['id'] != po['id']: raise RuntimeError(f'{key}: W7 되살린 기록의 id 가 X1 과 다름 — 내보내지 않음')
                sc = C.score(c7['trades'], d, D.K); t = sc['t']; rows = trade_rows(D, t, d)
                n = int(f7['독립거래']); s7 = float(f7['수익합계'])
                same = len(rows) == n and abs(sc['sum'] - s7) < 1e-4
                if same: checks['same'] += 1
                else: checks['diff'].append({'key': key, 'src': 'w7', 'n': len(rows), 'fixed_n': n, 'sum': round(sc['sum'], 5), 'fixed_sum': s7})
                trades[key] = rows
                g7 = lambda k, dv=None: (f7[k] if k in f7 and not (isinstance(f7[k], float) and math.isnan(f7[k])) else dv)
                row.update({'has_trades': True, 'check': bool(same), 'n': n, 'hit': num(f7['적중']), 'base': num(f7['아무날']), 'edge': num(f7['차이']), 'sum': num(s7, 5),
                            'avg': (num(s7 / n, 5) if n else None), 'last': (str(pd.Timestamp(pd.to_datetime(c7['trades']['signal']).max()).date()) if len(c7['trades']) else None),
                            'n_sig': int(len(c7['trades'])), 'hold': num(g7('보유일_가운뎃값'), 0),
                            'f': [yes(f7['거름1']), yes(f7['거름2']), yes(f7['거름3']), yes(f7['거름4'])], 'all4': yes(f7['넷다']),
                            'falsify': (f"{int(g7('반증버틴수'))}/8" if g7('반증버틴수') is not None else None), 'p': num(g7('가짜p')), 'big_na': yes(g7('거름2_큰변동해_판정불가', False)),
                            'p1': [num(g7('앞n'), 0), num(g7('앞적중'))], 'p2': [num(g7('뒤n'), 0), num(g7('뒤적중'))],
                            'overlap': g7('관찰목록과', '') if isinstance(g7('관찰목록과', ''), str) else '',
                            'trade_src': 'git 옛 기록에서 되살림(Signal A 2차 W7)', 'trade_note': '오래된 회차의 연구소 거래일 파일이 지워져 X1 에서 확인 불가였던 것을 2차가 되살림'})
            else:
                checks['no_trades'] += 1
            combos.append(row)
    # Signal A 관찰 목록 3개
    fin = json.load(open(os.path.join(SA, 'signals', 'final_v1.json'), encoding='utf-8'))
    for no, tk, cid, part in WATCH:
        w = next(x for x in fin['관찰_목록'] if x['순번'] == no); S = w.get(part) or {}
        cs, _ = C.load_result(tk); c = next(x for x in cs if x['id'] == cid); d = int(c['direction'])
        sc = C.score(c['trades'], d, D.K); t = sc['t']; rows = trade_rows(D, t, d); key = f'S{no}'
        n = S.get('독립거래'); s = S.get('수익합계_단순합')
        same = n is not None and len(rows) == int(n) and s is not None and abs(sc['sum'] - float(s)) < 1e-3
        if same: checks['same'] += 1
        else: checks['diff'].append({'key': key, 'n': len(rows), 'fixed_n': n, 'sum': round(sc['sum'], 5), 'fixed_sum': s})
        trades[key] = rows
        exact = w.get('규칙_정확히') or {}
        combos.append({'key': key, 'src': 'S', 'rank': no, 'round': None, 'grade': '관찰 목록', 'id': f'{tk}:{cid}', 'desc': w['규칙_쉬운말'], 'name': w['이름'], 'family': w.get('줄기'),
                       'dir': d, 'trade_src': f'{tk}/out/cands.pkl', 'trade_note': ('전체 기간(2010~) 고정 규칙 숫자' if no == 1 else '2016~2026 해마다 그 전 자료로 고른 절차의 숫자'),
                       'exact': json.dumps(exact, ensure_ascii=False), 'lab': None, 'has_trades': True, 'check': bool(same),
                       'n': n, 'hit': num(S.get('적중')), 'base': num(S.get('같은해_아무날')), 'edge': num(S.get('차이') if S.get('차이') is not None else (S['적중'] - S['같은해_아무날'] if S.get('적중') is not None and S.get('같은해_아무날') is not None else None)),
                       'sum': num(s, 5), 'avg': (num(float(s) / int(n), 5) if n else None), 'last': (str(pd.Timestamp(pd.to_datetime(c['trades']['signal']).max()).date()) if len(c['trades']) else None),
                       'n_sig': int(len(c['trades'])), 'hold': 5, 'f': [True, True, True, True], 'all4': True, 'falsify': (w.get('반증_시험') or {}).get('버틴_수'),
                       'p': None, 'big_na': False,
                       'p1': [((S.get('앞_2010_2023') or S.get('앞_2016_2023') or {}).get('독립거래')), num((S.get('앞_2010_2023') or S.get('앞_2016_2023') or {}).get('적중'))],
                       'p2': [((S.get('뒤_2024_') or {}).get('독립거래')), num((S.get('뒤_2024_') or {}).get('적중'))],
                       'overlap': '', 'caution': w.get('조심할_점') or []})
    # Signal A 2차에서 네 거름을 모두 넘은 45개(2026-11-24 사용자 지시 "45개 조합 연구소 조합 매매 확인 웹판에 추가해")
    #  목록·숫자 = s2/out/pool.csv(넷다) + s2/out/candidates.json, 거래 = 그 줄기의 wN/out/cands.pkl(판정한 바로 그 거래). 순서·번호 = 수익 합계 큰 순.
    S2 = os.path.join(SA, 's2', 'out')
    p2 = pd.read_csv(os.path.join(S2, 'pool.csv')); p2 = p2[p2['넷다'].map(yes)].copy()
    if len(p2) != 45: raise RuntimeError(f'2차 네 거름 통과 수가 45 가 아님({len(p2)}) — 내보내지 않음')
    CJ = {c['key']: c for c in json.load(open(os.path.join(S2, 'candidates.json'), encoding='utf-8'))['candidates']}
    p2 = p2.sort_values('수익합계', ascending=False, kind='mergesort').reset_index(drop=True)
    cache = {}
    for i, r in p2.iterrows():
        k2 = r['key']; tk, cid = k2.split(':', 1); cj = CJ.get(k2)
        if cj is None: raise RuntimeError(f'{k2}: candidates.json 에 없음')
        if tk not in cache: cache[tk] = {x['id']: x for x in C.load_result(tk)[0]}
        c = cache[tk].get(cid)
        if c is None: raise RuntimeError(f'{k2}: {tk}/out/cands.pkl 에 거래 기록 없음 — 내보내지 않음')
        d = int(cj['direction']); sc = C.score(c['trades'], d, D.K); t = sc['t']; rows = trade_rows(D, t, d); key = f'W{i + 1:02d}'
        n = int(cj['all_n']); s = float(cj['all_sum'])
        same = len(rows) == n and abs(sc['sum'] - s) < 1e-3
        if same: checks['same'] += 1
        else: checks['diff'].append({'key': key, 'src_key': k2, 'n': len(rows), 'fixed_n': n, 'sum': round(sc['sum'], 5), 'fixed_sum': round(s, 5)})
        trades[key] = rows
        touch = 'hit' in c['trades'].columns
        hold = int(cj['hold']) if cj.get('hold') is not None else None
        if touch: sell_n, sell_full = None, '보유일 없음 — 매수 뒤 시가 기준 ±5% 가운데 먼저 닿는 쪽으로 맞음·틀림을 정하고 그날 판다(조건 설명 원문)'
        elif cj.get('hold_fixed') and hold: sell_n, sell_full = hold, f'신호 다음 거래일 시가에 사서, 그날을 1일째로 세어 {hold}거래일째 종가에 판다.'
        else: sell_n, sell_full = None, f'고른 규칙마다 제 보유일(가운뎃값 {hold}일) — 먼저 난 신호부터, 보유 중 새 신호는 건너뜀(조건 설명 원문)'
        f = cj.get('filters') or {}; fz = cj.get('falsify') or {}; w = cj.get('watch') or {}
        combos.append({'key': key, 'src': 'W', 'rank': i + 1, 'round': None, 'grade': '2차 네 거름', 'id': k2, 'desc': cj['desc'],
                       'name': f"{tk.upper()} 묶음 {cj.get('cluster')}" + (' ★' if cj.get('cluster_rep') else ''), 'family': cj.get('root') or cj.get('family'),
                       'dir': d, 'trade_src': f'{tk}/out/cands.pkl', 'trade_note': '2016~2026 해마다 그 전 자료로 고른 절차의 숫자(다음 해 성적)',
                       'lab': None, 'has_trades': True, 'check': bool(same), 'sell_n': sell_n, 'sell_full': sell_full,
                       'n': n, 'hit': num(cj['all_hit']), 'base': num(cj['base']), 'edge': num(cj['edge']), 'sum': num(s, 5), 'avg': num(s / n, 5) if n else None,
                       'last': cj.get('last_signal'), 'n_sig': int(len(c['trades'])), 'hold': hold,
                       'f': [bool(f.get('f1_next_year')), bool(f.get('f2_2026_big')), bool(f.get('f3_falsify8')), bool(f.get('f4_p_raw_lt_1pct'))], 'all4': True,
                       'falsify': f"{sum(1 for v in (fz.get('tests') or {}).values() if v)}/8", 'p': num(cj.get('fake_p')), 'p_adj': num(cj.get('fake_p_adj')), 'big_na': False,
                       'p1': [cj.get('p1_n'), num(cj.get('p1_hit'))], 'p2': [cj.get('p2_n'), num(cj.get('p2_hit'))],
                       'overlap': (w.get('label', '') + (' — ' + w['closest'] if w.get('closest') else '')) if w else '',
                       'cluster': cj.get('cluster'), 'cluster_rep': bool(cj.get('cluster_rep'))})
    prices = {'kospi': px_json(D.K, pd.Timestamp('2009-07-01')), 'fut': px_json(D.F, pd.Timestamp('2009-07-01'))}
    now = pd.Timestamp.now(tz='Asia/Seoul').strftime('%Y-%m-%d %H:%M')
    meta = {'at': now, 'data_end': str(C.END.date()), 'combos': len(combos), 'with_trades': sum(1 for x in combos if x['has_trades']),
            'no_trades': sum(1 for x in combos if not x['has_trades']), 'check_same': checks['same'], 'check_diff': checks['diff'],
            'price_src': '릴리스 signal-a-data-v1 고정 자료(sa_common.Data 의 K = 코스피 지수, F = 코스피200 연속 선물) — X1·Signal A 가 거래 수익을 잰 가격',
            'x1_at': json.load(open(os.path.join(X1, 'out', 'summary.json'), encoding='utf-8')).get('at'), 'log': log}
    dump = lambda o, f: json.dump(o, open(os.path.join(a.out, f), 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    dump(combos, 'combos.json'); dump(trades, 'trades.json'); dump(prices, 'prices.json')
    json.dump(meta, open(os.path.join(a.out, 'meta.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f"조합 {meta['combos']}개 · 거래 있음 {meta['with_trades']} · 거래 내역 없음 {meta['no_trades']} · 숫자 일치 {checks['same']} · 다름 {len(checks['diff'])}")
    for x in checks['diff'][:20]: print('  다름:', x)


if __name__ == '__main__':
    main()
