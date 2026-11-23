# -*- coding: utf-8 -*-
"""T4 변동폭 맞춤 — t1·t2·t3 의 같은 가족을 '그때 변동폭에 맞춘 문턱'(vol=True)으로 다시 돌린다. 새 가족을 늘리지 않는다(SPEC.md).

t1·t2·t3 의 run.py 가 가진 n_parts(vol=True)·run_part(i, n, vol=True)·merge(parts, vol=True) 를 그대로 부른다(그 파일들은 고치지 않는다).
조각 번호는 t1 → t2 → t3 순서로 이어 붙인다. 합치기는 줄기마다 따로 프로세스를 띄워(같은 이름 run.py 가 섞이지 않게) 한 뒤 모은다.
명령: python run.py --nparts | --part i/n | --merge [--quick]      (--submerge tN 은 --merge 가 안에서 부른다)
"""
import importlib
import os
import subprocess
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__)); SA = os.path.dirname(HERE)
sys.path.insert(0, SA)
import sa_common as C  # noqa: E402

TRACK = 't4'
SUBS = ['t1', 't2', 't3']
NAME = {'t1': '위치·사건 규칙', 't2': '상태 → 방아쇠', 't3': '합의·확률'}
NOT_INCLUDED = ['변동폭 재는 창을 60일 말고 20·120일로, 문턱 배수를 다른 값으로 바꿔 보기',
                '변동폭이 큰 날에만 켜는 신호처럼 변동폭 자체를 조건으로 넣기',
                'T5(하락) 가족의 변동폭 맞춤판',
                't1~t3 각 SPEC 의 "안 넣은 것"은 변동폭 맞춤판에도 그대로 안 넣음']


def sub_mod(s):
    """줄기 s 의 run.py 를 'run' 이라는 이름으로 불러온다. joblib 일꾼 프로세스도 찾을 수 있게 PYTHONPATH 에 그 폴더를 넣는다. 한 프로세스에서 한 줄기만."""
    d = os.path.join(SA, s)
    assert 'run' not in sys.modules or os.path.dirname(os.path.abspath(sys.modules['run'].__file__)) == d, '한 프로세스에서 줄기 둘을 부르면 안 됨'
    if d not in sys.path: sys.path.insert(0, d)
    os.environ['PYTHONPATH'] = os.pathsep.join([d, SA] + [p for p in os.environ.get('PYTHONPATH', '').split(os.pathsep) if p and p not in (d, SA)])
    return importlib.import_module('run')


def sub_nparts(s):
    """줄기 s 의 변동폭 맞춤판 조각 수(따로 프로세스로 물어본다 — 같은 이름 run.py 가 섞이지 않게)."""
    code = f"import sys; sys.path.insert(0, {SA!r}); sys.path.insert(0, {os.path.join(SA, s)!r}); import run; print('NP', run.n_parts(vol=True))"
    out = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, check=True).stdout
    return int([x for x in out.split('\n') if x.startswith('NP ')][-1].split()[1])


def layout():
    """[(줄기, 그 줄기 안 조각 번호, 그 줄기 조각 수)] — t4 조각 번호 순서."""
    out = []
    for s in SUBS:
        n = sub_nparts(s); out += [(s, i, n) for i in range(1, n + 1)]
    return out


def n_parts(vol=True):
    return len(layout())


def run_part(i, n, vol=True, quick=False):
    L = layout(); assert n == len(L), f'조각 수가 다름: {n} != {len(L)}'
    s, j, m = L[i - 1]
    return {'sub': s, 'i': j, 'n': m, 'obj': sub_mod(s).run_part(j, m, vol=True, quick=quick)}


def submerge(s, quick):
    """줄기 s 의 조각만 골라 그 줄기의 merge(vol=True) 를 부르고 (cands, meta) 를 t4/out/sub_<s>.pkl 로 저장."""
    L = layout(); parts = C.load_parts(TRACK, len(L)); mine = [p['obj'] if p is not None else None for p, (ss, _, _) in zip(parts, L) if ss == s]
    failed = [k + 1 for k, (p, (ss, _, _)) in enumerate(zip(parts, L)) if ss == s and p is None]
    M = sub_mod(s); od = os.path.join(C.track_dir(TRACK), 'out')
    try: cands, meta = M.merge(mine, vol=True, quick=quick, out_dir=od)        # t1 은 표를 직접 쓴다(이름 앞 V_)
    except TypeError: cands, meta = M.merge(mine, vol=True, quick=quick)
    pd.to_pickle({'cands': cands, 'meta': meta, 'failed_t4_parts': failed}, os.path.join(od, f'sub_{s}.pkl'))


def big_year_table(D, cands):
    """큰 변동 해(2011·2020·2026)만 따로: 절차마다 그 해 독립 거래 수·적중·같은 해 아무 날(같은 채점 방식)."""
    rows = []
    for c in cands:
        if c.get('kind') != 'wf': continue
        d = int(c['direction']); a = C.score(c['trades'], d, D.K); t = a['t']
        if not len(t): continue
        h = int(c.get('hold') or C.hold_days(t, D.td)); by = c.get('base_y') if 'hit' in c['trades'] else None
        y = pd.DatetimeIndex(t['signal']).year.values; r = {'id': c['id'], '절차': c['desc'], '전체 독립 거래': a['n'], '전체 적중': round(a['hit'], 4)}
        for Y in C.BIG_YEARS:
            m = y == Y; r[f'{Y} 거래'] = int(m.sum()); r[f'{Y} 맞음'] = int(t['ok'].values[m].sum())
            b = C.base_for(D, t[m], h, d, by) if m.any() else None; r[f'{Y} 아무 날'] = None if b is None else round(b, 4)
        rows.append(r)
    return pd.DataFrame(rows)


def merge(parts=None, vol=True, quick=False):
    od = os.path.join(C.track_dir(TRACK), 'out'); os.makedirs(os.path.join(od, 'tables'), exist_ok=True)
    cands, fam, notes, failed, md, tabs = [], {}, [], [], [], []; n_tested = m_fixed = m_wf = 0
    for s in SUBS:
        f = os.path.join(od, f'sub_{s}.pkl')
        if os.path.exists(f): os.remove(f)
        subprocess.run([sys.executable, os.path.abspath(__file__), '--submerge', s] + (['--quick'] if quick else []), check=True)
        R = pd.read_pickle(f); os.remove(f); meta = R['meta']; failed += R['failed_t4_parts']
        ids = {c['id'] for c in R['cands']}
        for c in R['cands']:
            c = dict(c); c['id'] = f"{s}_{c['id']}"; c['family'] = f"{s}:{c.get('family')}"
            if c.get('wf_of') in ids: c['wf_of'] = f"{s}_{c['wf_of']}"
            if '[변동폭 맞춤]' not in str(c.get('desc')): c['desc'] = '[변동폭 맞춤] ' + str(c.get('desc'))
            cands.append(c)
        n_tested += int(meta.get('n_tested', 0)); m_fixed += int(meta.get('m_fixed', 0) or 0); m_wf += int(meta.get('m_wf', 0) or 0)
        for k, v in (meta.get('families') or {}).items(): fam[f'{s}:{k}'] = int(v)
        notes += [f'[{s}] {x}' for x in meta.get('notes', [])]
        for nm, txt in (meta.get('tables_csv') or {}).items():
            open(os.path.join(od, 'tables', nm if nm.startswith('V_') else 'V_' + nm), 'w', encoding='utf-8').write(txt)
        if meta.get('summary_md'): md += [f'### {s.upper()} {NAME[s]} — 변동폭 맞춤판', '', str(meta['summary_md']).strip(), '']
    D = C.Data(); B = big_year_table(D, cands); B.to_csv(os.path.join(od, 'tables', 'big_years.csv'), index=False, encoding='utf-8')
    top = B.sort_values('2026 거래', ascending=False).head(15) if len(B) else B
    head = ['### 큰 변동 해(2011·2020·2026)만 따로 — 절차마다 그 해 독립 거래 수/맞은 수(같은 해 아무 날 적중)', '',
            '해마다 고르는 절차는 2016년부터 채점하므로 2011년 칸은 비어 있다(2011년은 전체 기간 고정 규칙에서만 볼 수 있음). 2026년 거래가 많은 순 15개, 전부는 out/tables/big_years.csv.', '',
            '| 절차 | 전체 | 2020 | 2026 |', '|---|---|---|---|']
    for _, r in top.iterrows():
        cell = lambda Y: f"{r[f'{Y} 거래']}/{r[f'{Y} 맞음']}" + (f" ({C.pct(r[f'{Y} 아무 날'])})" if pd.notna(r[f'{Y} 아무 날']) else '')
        head.append(f"| {r['절차']} | {r['전체 독립 거래']}건 {C.pct(r['전체 적중'])} | {cell(2020)} | {cell(2026)} |")
    open(os.path.join(od, 'summary.md'), 'w', encoding='utf-8').write('\n'.join(head + [''] + md) + '\n')
    meta = dict(n_tested=n_tested, families=fam, m_fixed=max(1, m_fixed), m_wf=max(1, m_wf), not_included=NOT_INCLUDED, parts_failed=sorted(failed),
                notes=['t1·t2·t3 과 같은 가족·같은 가짓수를 문턱만 변동폭에 맞춰 다시 돌린 것(새 가족 없음). 원래 판(t1~t3)과 나란히 읽을 것.'] + notes,
                tables=sorted(os.listdir(os.path.join(od, 'tables'))))
    return cands, meta


def main():
    a = C.parse_part(); argv = sys.argv[1:]
    if '--submerge' in argv: submerge(argv[argv.index('--submerge') + 1], a['quick']); return
    if a['nparts']: print(n_parts()); return
    if a['part']:
        i, n = a['part']; C.save_part(TRACK, i, n, run_part(i, n, quick=a['quick'])); print(f'part {i}/{n} 끝'); return
    if a['merge']:
        cands, meta = merge(quick=a['quick']); C.save_result(TRACK, cands, meta)
        print(f"merge 끝: 후보 {len(cands)}개, 시험 {meta['n_tested']}가지, 실패 조각 {meta['parts_failed']}"); return
    print('사용: python run.py --nparts | --part i/n | --merge [--quick]')


if __name__ == '__main__':
    main()
