# -*- coding: utf-8 -*-
"""연구소용 웹판 자료 내보내기 (deriv/labweb/AGENT.md, 2026-11-24 사용자 지시).

새로 계산하는 것은 '조합별 매매 날짜' 하나뿐이다. 그것도 X1(deriv/signal_a/x1/run.py)이 쓰는 함수를 그대로 불러
(rank_pool → attach_trades → sa_common.score) 같은 거래를 파일로 옮길 뿐이다. 판정·수익·거름 숫자는 x1/out 의 결과를 그대로 읽는다.

  combos.json  조합 표(갈래 A·B·C·D 상위 251개 = x1/out/pool.csv + fixed.csv, Signal A 관찰 목록 3개 = signals/final_v1.json)
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
