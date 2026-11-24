# -*- coding: utf-8 -*-
"""Signal A W7 보조 — 연구소 거래일 파일(candidates.pkl)을 지금 저장소와 **git 옛 기록(지워진 것 포함)** 에서 읽어 판다스 판과 상관없는 꼴(JSON)로 옮긴다.

까닭: (1) 연구소 pkl 은 판다스 최신판으로 저장돼 Signal A 고정판(2.3.3)으로 읽히지 않는다(x1/extract.py 와 같은 까닭).
      (2) 오래된 회차의 candidates.pkl 은 저장소 크기 관리로 지워져 X1 이 122개를 '확인 불가'로 셌다. 지워진 파일은 git 옛 기록에 남아 있다.
하는 일: 대상 id(rank.py — X1 대상 + verdicts 로 다시 매긴 상위 100개)의 거래일(signal·exit, trades_dev)을 날짜 글자로 옮겨 <out>/lab_trades_<갈래>.json 에 쓴다.
        같은 id·설명·거래일은 한 번만 적고 어느 회차(지금 저장소 / 옛 기록)에 있었는지 붙인다. 계산·판정·고르기는 하지 않는다. 연구소 폴더·git 은 읽기만 한다.
**하나라도 못 읽으면 실패로 끝낸다**(조용히 '확인 불가'로 넘기지 않는다). 옛 기록이 얕게(shallow) 받아져 있으면 멈춘다 — 전체 기록이 있어야 한다.
사용: python extract.py --out 폴더 [--git-dir 저장소 폴더] [--quick]
       --git-dir = 옛 기록을 읽을 저장소(기본: 이 저장소). blob 없이 받은 저장소(filter=blob:none)여도 된다 — 필요한 파일만 한 번에 내려받는다.
       --quick   = 시험용(옛 기록은 갈래마다 12개 파일만 읽는다. run.py 는 --quick 일 때만 이 결과를 받는다)
"""
import argparse
import glob
import hashlib
import io
import json
import os
import re
import subprocess
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rank as RK  # noqa: E402

LAB = RK.LAB
REPO = os.path.dirname(os.path.dirname(RK.SA))
BR = RK.BR
SUB2G = {v: k for k, v in BR.items()}
PATHSPEC = 'deriv/lab/out*/round_*/*/candidates.pkl'
PAT = re.compile(r'^deriv/lab/(out[^/]*)/round_(\d+)/([^/]+)/candidates\.pkl$')


def dates(df):
    """거래표 → [[signal, exit], …] (날짜 글자). 빈 날짜가 든 줄은 뺀다(x1/extract.py 와 같음)."""
    if df is None or not len(df): return []
    t = pd.DataFrame({'signal': pd.to_datetime(df['signal']), 'exit': pd.to_datetime(df['exit'])}).dropna()
    return [[s.strftime('%Y-%m-%d'), e.strftime('%Y-%m-%d')] for s, e in zip(t['signal'], t['exit'])]


def git(gd, *args, inp=None, binary=False, env=None):
    r = subprocess.run(['git', '-C', gd, *args], input=inp, capture_output=True, env=env)
    if r.returncode: raise RuntimeError(f"git {' '.join(args[:4])} … 실패: {r.stderr.decode('utf-8', 'replace').strip()[-400:]}")
    return r.stdout if binary else r.stdout.decode('utf-8', 'replace')


def history(gd):
    """옛 기록의 candidates.pkl 경로마다 마지막 판. 반환 {경로: (blob id, 커밋, 지워졌나)}."""
    if git(gd, 'rev-parse', '--is-shallow-repository').strip() == 'true':
        raise RuntimeError('저장소의 옛 기록이 얕게(shallow) 받아져 있음 — 전체 기록(fetch-depth 0)으로 받아야 지워진 candidates.pkl 을 찾을 수 있음')
    out = {}; cur = None; gone = set()
    txt = git(gd, '-c', 'core.quotepath=off', 'log', '--raw', '--no-abbrev', '--no-renames', '--format=C %H %ct', '--', PATHSPEC)
    for ln in txt.split('\n'):                                       # 최신 커밋부터 나온다
        if ln.startswith('C '): cur = ln.split()[1]; continue
        if not ln.startswith(':') or '\t' not in ln: continue
        meta, path = ln.split('\t', 1); f = meta.split(); path = path.strip().strip('"')
        if not PAT.match(path): continue
        if f[4].startswith('D'):
            if path not in out: gone.add(path)
            continue
        if path not in out: out[path] = (f[3], cur, path in gone)   # 그 경로의 가장 최근 판
    return out


def prefetch(gd, oids):
    """blob 없이 받은 저장소면 필요한 파일을 한 번에 내려받는다(이미 있으면 아무 일도 없음). 실패해도 뒤에서 하나씩 읽을 때 다시 시도된다."""
    if not oids: return
    try: partial = git(gd, 'config', '--get', 'remote.origin.promisor').strip() == 'true'
    except Exception:                                                # noqa: BLE001 — 설정이 없으면(파일까지 다 받은 저장소) 내려받을 것이 없다
        partial = False
    if not partial: return
    try:
        git(gd, '-c', 'fetch.negotiationAlgorithm=noop', 'fetch', 'origin', '--no-tags', '--no-write-fetch-head', '--recurse-submodules=no', '--filter=blob:none', '--stdin',
            inp=('\n'.join(oids) + '\n').encode())
    except Exception as e:                                           # noqa: BLE001
        print(f'한 번에 내려받기 실패({str(e)[-200:]}) — 하나씩 읽음', flush=True)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--out', required=True); ap.add_argument('--git-dir', default=REPO); ap.add_argument('--quick', action='store_true')
    a = ap.parse_args(); os.makedirs(a.out, exist_ok=True); gd = a.git_dir
    T = RK.targets()                                                 # 못 읽으면 여기서 멈춘다
    H = history(gd)
    by_g = {g: [] for g in BR}
    for path, (oid, commit, deleted) in sorted(H.items()):
        m = PAT.match(path); g = SUB2G.get(m.group(1))
        if g is None: continue
        if os.path.exists(os.path.join(REPO, path)): continue       # 지금 저장소에 있는 것은 아래에서 파일로 읽는다
        by_g[g].append((int(m.group(2)), path, oid, commit))
    if a.quick:
        for g in by_g: by_g[g] = sorted(by_g[g], key=lambda x: -x[0])[:12]
    prefetch(gd, sorted({x[2] for g in by_g for x in by_g[g]}))
    bad = []
    for g, sub in BR.items():
        ids = set(T[g]['ids']); recs = {}

        def take(cs, rnd, where):
            for c in cs:
                if not (isinstance(c, dict) and str(c.get('id')) in ids and isinstance(c.get('trades'), pd.DataFrame)): continue
                tr = dates(c['trades']); tdv = dates(c['trades_dev']) if isinstance(c.get('trades_dev'), pd.DataFrame) else None
                key = hashlib.sha1(json.dumps([str(c['id']), c.get('desc'), int(c.get('direction') or 0), tr, tdv], ensure_ascii=False).encode()).hexdigest()
                r = recs.setdefault(key, {'id': str(c['id']), 'desc': c.get('desc'), 'direction': int(c.get('direction') or 0), 'trades': tr, 'trades_dev': tdv, 'rounds_tree': [], 'rounds_hist': []})
                k = 'rounds_tree' if where == 'tree' else 'rounds_hist'
                if rnd not in r[k]: r[k].append(rnd)

        files = sorted(glob.glob(os.path.join(LAB, sub, 'round_*', '*', 'candidates.pkl')))
        for p in files:
            rnd = int(re.search(r'round_(\d+)', p).group(1))
            try: cs = pd.read_pickle(p)
            except Exception as e:                                   # noqa: BLE001
                bad.append(f'{os.path.relpath(p, LAB)}: {type(e).__name__}'); continue
            take(cs, rnd, 'tree'); del cs
        n_hist = 0
        for rnd, path, oid, commit in sorted(by_g[g]):
            try:
                raw = git(gd, 'cat-file', 'blob', oid, binary=True); cs = pd.read_pickle(io.BytesIO(raw))
            except Exception as e:                                   # noqa: BLE001
                bad.append(f'옛 기록 {path}@{commit[:8]}: {type(e).__name__} {str(e)[-120:]}'); continue
            take(cs, rnd, 'hist'); n_hist += 1; del cs, raw
        hist_rounds = sorted({x[0] for x in by_g[g]})
        json.dump({'branch': g, 'pandas': pd.__version__, 'quick': bool(a.quick), 'tree_files': len(files), 'hist_files': n_hist, 'hist_rounds': hist_rounds,
                   'target_ids': sorted(ids), 'cands': list(recs.values())},
                  open(os.path.join(a.out, f'lab_trades_{g}.json'), 'w', encoding='utf-8'), ensure_ascii=False)
        print(f"{g}: 대상 id {len(ids)}개 · 지금 저장소 파일 {len(files)}개 · 옛 기록에서 되살려 읽은 파일 {n_hist}개(회차 {hist_rounds[0] if hist_rounds else '–'}~{hist_rounds[-1] if hist_rounds else '–'}) "
              f"· 옮긴 기록 {len(recs)}건 (판다스 {pd.__version__})", flush=True)
    if bad:
        print('못 읽은 파일:\n  ' + '\n  '.join(bad[:40]), file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
