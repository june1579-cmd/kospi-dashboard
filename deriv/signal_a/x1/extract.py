# -*- coding: utf-8 -*-
"""Signal A X1 보조 — 연구소 거래일 파일(candidates.pkl)을 판다스 판과 상관없는 꼴(JSON)로 옮긴다.

까닭: 연구소 워크플로는 판다스 최신판으로 candidates.pkl 을 쓰고, Signal A 파이프라인은 requirements.txt 의 고정판(2.3.3)을 쓴다.
      고정판에서는 그 pkl 이 읽히지 않는다(NotImplementedError — 날짜 칸의 저장 꼴이 다름). 1차 실행이 이 때문에 갈래 A·B·D 를 못 읽었다.
하는 일: 연구소와 같은 환경(판다스 최신판)에서 이 파일만 돌려, 순위표(leaderboard.csv)에 한 번이라도 오른 id 의 거래일(signal·exit)과
        trades_dev 를 날짜 글자(YYYY-MM-DD)로 옮겨 <out>/lab_trades_<갈래>.json 에 쓴다. 판정(run.py)은 파이프라인과 같은 고정판 환경에서 그 JSON 을 읽는다.
계산·판정·고르기는 하지 않는다. 연구소 폴더는 읽기만 한다. **하나라도 못 읽으면 실패로 끝낸다**(조용히 '확인 불가'로 넘기지 않는다).
사용: python extract.py --out 폴더
"""
import argparse
import glob
import json
import os
import re
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
LAB = os.path.join(os.path.dirname(os.path.dirname(HERE)), 'lab')
BR = {'A': 'out', 'B': 'out_b', 'C': 'out_c', 'D': 'out_d'}


def dates(df):
    """거래표 → [[signal, exit], …] (날짜 글자). 빈 날짜가 든 줄은 뺀다(run.py 의 _norm 과 같음)."""
    if df is None or not len(df): return []
    t = pd.DataFrame({'signal': pd.to_datetime(df['signal']), 'exit': pd.to_datetime(df['exit'])}).dropna()
    return [[s.strftime('%Y-%m-%d'), e.strftime('%Y-%m-%d')] for s, e in zip(t['signal'], t['exit'])]


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--out', required=True); a = ap.parse_args(); os.makedirs(a.out, exist_ok=True)
    bad = []
    for g, sub in BR.items():
        ids = set()
        for f in sorted(glob.glob(os.path.join(LAB, sub, 'round_*', 'leaderboard.csv'))):
            try:
                x = pd.read_csv(f)
                if 'id' in x: ids |= set(x['id'].dropna().astype(str))
            except Exception as e:                                   # noqa: BLE001
                bad.append(f'{f}: {type(e).__name__}')
        files = sorted(glob.glob(os.path.join(LAB, sub, 'round_*', '*', 'candidates.pkl'))); cands = []
        for p in files:
            r = int(re.search(r'round_(\d+)', p).group(1))
            try:
                cs = pd.read_pickle(p)
            except Exception as e:                                   # noqa: BLE001
                bad.append(f'{os.path.relpath(p, LAB)}: {type(e).__name__}'); continue
            for c in cs:
                if not (isinstance(c, dict) and str(c.get('id')) in ids and isinstance(c.get('trades'), pd.DataFrame)): continue
                cands.append({'round': r, 'id': str(c['id']), 'desc': c.get('desc'), 'direction': int(c.get('direction') or 0), 'trades': dates(c['trades']),
                              'trades_dev': (dates(c['trades_dev']) if isinstance(c.get('trades_dev'), pd.DataFrame) else None)})
            del cs
        json.dump({'branch': g, 'pandas': pd.__version__, 'files': len(files), 'ids': len(ids), 'cands': cands},
                  open(os.path.join(a.out, f'lab_trades_{g}.json'), 'w', encoding='utf-8'), ensure_ascii=False)
        print(f'{g}: 거래일 파일 {len(files)}개 · 순위표에 오른 id {len(ids)}개 · 옮긴 기록 {len(cands)}건 (판다스 {pd.__version__})', flush=True)
    if bad:
        print('못 읽은 파일:\n  ' + '\n  '.join(bad[:40]), file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
