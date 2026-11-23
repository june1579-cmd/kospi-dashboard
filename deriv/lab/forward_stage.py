#!/usr/bin/env python
"""실전 확인 단계 · 관찰 등급 전진 기록 (사용자 지정 2026-11-23, 설정 파일로 못 바꿈).

통과(전체 35거래·85%, 앞·뒤 각 12거래·80%, 반증 버팀)는 '과거 자료 기준'일 뿐이라, 규칙을 고정한 날 뒤에 실제로 난 신호의 성적으로 매매 크기를 정한다.
  · 통과 신호: 고정 뒤 첫 10번까지는 절반 크기(확인 중).
      10번 안에 8번 이상 맞음 → 정식(전액) / 10번 중 6~7번 → 절반 유지 / 틀린 것이 5번이 되면(= 10번 중 5번 이하 확정) → 중단
  · 관찰 등급(전체 35거래·80%, 앞·뒤 각 12거래·75%, 반증 버팀): 매매 없이 기록만. 나중에 통과 기준을 넘으면 등급만 올리고 고정일·기록은 이어 간다.
규칙은 처음 등록된 날(고정일)로 고정한다. 한 번 적힌 거래 기록은 뒤에 다시 계산해도 고치지 않는다(나중에 본 자료로 과거 기록을 바꾸지 않게).

갈래마다 파일을 따로 쓴다: deriv/lab/signals/forward_<갈래>.json · .md  (갈래 A = a)
읽는 것: 이번 라운드의 a08/verdicts.csv, a10/redteam.csv, 모든 에이전트의 candidates.pkl. 판정·설정·상태 파일은 건드리지 않는다.
"""
import datetime
import glob
import json
import os
import pickle

import numpy as np
import pandas as pd

import lab_common as L
from a08_validate import honest_trades, independent

FIRST_N, FULL_K, STOP_MISS = 10, 8, 5
T = L.TRACK or 'a'
SIG = os.path.join(L.LAB, 'signals'); os.makedirs(SIG, exist_ok=True)
REG = os.path.join(SIG, f'forward_{T}.json'); MD = os.path.join(SIG, f'forward_{T}.md')
TODAY = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=9)).strftime('%Y-%m-%d')


def stage_of(e):
    done = [t for t in e.get('trades', []) if t.get('ret') is not None][:FIRST_N]
    n = len(done); k = sum(1 for t in done if t['hit']); m = n - k
    if e.get('tier') != '통과': return '관찰(매매 없음)', 0.0, n, k
    if m >= STOP_MISS: return '중단', 0.0, n, k
    if k >= FULL_K: return '정식(전액)', 1.0, n, k
    if n >= FIRST_N: return '절반 유지', 0.5, n, k
    return '확인 중(절반)', 0.5, n, k


def main():
    reg = json.load(open(REG, encoding='utf-8')) if os.path.exists(REG) else {'track': T.upper(), 'entries': []}
    ent = {e['id']: e for e in reg['entries']}
    rd = L.out_dir(); cfg = L.round_cfg(); rnd = cfg.get('round')
    # 1) 이번 라운드 판정에서 통과·관찰 등급을 읽어 새 것은 오늘 날짜로 고정
    vp, rp = os.path.join(rd, 'a08', 'verdicts.csv'), os.path.join(rd, 'a10', 'redteam.csv')
    fin, wat = set(), set()
    if os.path.exists(vp) and os.path.exists(rp):
        V = pd.read_csv(vp); R = pd.read_csv(rp)
        fd = cfg.get('focus_direction')
        if fd in (1, -1): V = V[V['direction'] == fd]
        ok = set(R.loc[R['버팀'] == True, 'id'])
        b = lambda col: V[col].fillna(False).astype(bool) if col in V else pd.Series(False, index=V.index)
        fin = set(V.loc[b('hold_pass'), 'id']) & ok; wat = (set(V.loc[b('watch_pass'), 'id']) & ok) - fin
        dsc = dict(zip(V['id'], V['desc'])); drc = dict(zip(V['id'], V['direction']))
        for cid in sorted(fin | wat):
            tier = '통과' if cid in fin else '관찰'
            if cid not in ent:
                ent[cid] = dict(id=cid, desc=dsc.get(cid, ''), direction=int(drc.get(cid, 1)), tier=tier, fixed=TODAY, round=rnd, trades=[])
            elif ent[cid].get('tier') == '관찰' and tier == '통과':
                ent[cid].update(tier='통과', promoted=TODAY)   # 등급만 올림 — 고정일·기록은 그대로
    for e in ent.values(): e['now'] = '통과' if e['id'] in fin else ('관찰' if e['id'] in wat else '이번 라운드 기준 미달·미계산')
    # 2) 이번 라운드 후보에서 고정된 규칙의 거래를 찾아 고정일 뒤 신호를 기록
    cands = {}
    for f in sorted(glob.glob(os.path.join(rd, '*', 'candidates.pkl'))):
        try:
            for c in pickle.load(open(f, 'rb')):
                if c['id'] in ent: cands[c['id']] = c
        except Exception as ex:
            print('읽기 실패', f, ex)
    fut = L.prices()['K200F']; td = fut.index; O = fut['open'].values.astype(float); C = fut['close'].values.astype(float)
    inmkt = {}
    for cid, e in ent.items():
        c = cands.get(cid); e['computed'] = bool(c is not None)
        if c is None: continue
        if not e.get('desc'): e['desc'] = c.get('desc', '')
        e['direction'] = int(c['direction'])
        t = independent(honest_trades(c)[2].dropna())
        days = set(); fixed = pd.Timestamp(e['fixed']); have = {x['signal']: x for x in e.get('trades', [])}
        for s, x in zip(pd.to_datetime(t['signal']), pd.to_datetime(t['exit'])):
            i = int(td.searchsorted(s, side='right')); j = int(td.get_indexer([x])[0]) if x in td else -1
            if i < len(td) and j >= i: days.update(range(i, j + 1))
            if s < fixed: continue
            key = s.strftime('%Y-%m-%d'); r = None
            if i < len(td) and j >= i and np.isfinite(O[i]) and np.isfinite(C[j]): r = round(float(e['direction'] * (C[j] / O[i] - 1) * 100), 2)
            rec = dict(signal=key, entry=td[i].strftime('%Y-%m-%d') if i < len(td) else None, exit=x.strftime('%Y-%m-%d'), ret=r, hit=bool(r > 0) if r is not None else None, seen=TODAY)
            if key not in have: e.setdefault('trades', []).append(rec)
            elif have[key].get('ret') is None and r is not None: have[key].update(ret=r, hit=rec['hit'])   # 보유 중이던 거래가 끝난 경우만 채움
        e['trades'] = sorted(e.get('trades', []), key=lambda z: z['signal']); e['last_data'] = td[-1].strftime('%Y-%m-%d'); inmkt[cid] = days
    # 3) 거래가 많이 겹치는 것끼리 같은 계열 번호(보유일 자카드 0.35 이상, 같은 방향)
    order = sorted(ent.values(), key=lambda z: (z['fixed'], z['id'])); reps = []
    for e in order:
        d = inmkt.get(e['id'])
        if d is None: e.setdefault('group', None); continue
        g = None
        for gid, rid in reps:
            o = inmkt[rid]; u = len(d | o)
            if u and len(d & o) / u >= 0.35 and ent[rid]['direction'] == e['direction']: g = gid; break
        if g is None: g = len(reps) + 1; reps.append((g, e['id']))
        e['group'] = g
    # 4) 단계
    for e in ent.values():
        st, size, n, k = stage_of(e); e.update(stage=st, size=size, fwd_n=n, fwd_hit=k)
    reg.update(entries=order, updated=TODAY, round=rnd,
               rule=f'통과 신호는 고정 뒤 첫 {FIRST_N}번까지 절반 크기. {FIRST_N}번 안에 {FULL_K}번 이상 맞으면 전액, 6~7번이면 절반 유지, 틀린 것이 {STOP_MISS}번이면 중단. 관찰 등급은 매매 없이 기록만.')
    json.dump(reg, open(REG, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    L_ = [f'# 갈래 {T.upper()} 실전 확인 단계 · 관찰 등급', '', f'- 규칙: {reg["rule"]}', f'- 마지막 갱신: {TODAY} (라운드 {rnd}, 자료 {td[-1].strftime("%Y-%m-%d")} 까지)', '',
          '| 계열 | 등급 | 단계 | 매매 크기 | 고정일 | 고정 뒤 신호(첫 10번) | 설명 |', '|---|---|---|---|---|---|---|']
    for e in sorted(order, key=lambda z: (z.get('group') or 99, z['fixed'], z['id'])):
        L_.append(f"| {e.get('group') or '-'} | {e['tier']} | {e['stage']} | {'전액' if e['size'] == 1 else '절반' if e['size'] == 0.5 else '없음'} | {e['fixed']} | {e['fwd_n']}번 중 {e['fwd_hit']}번 맞음 | "
                  f"{'↓ ' if e['direction'] < 0 else '↑ '}{e.get('desc') or e['id']}{'' if e.get('computed') else ' (이번 라운드에서 계산 안 됨)'} |")
    L_ += ['', '## 고정 뒤 신호 기록', '']
    any_ = False
    for e in order:
        for t in e.get('trades', []):
            any_ = True
            L_.append(f"- 계열 {e.get('group') or '-'} · {e['id']} · 신호 {t['signal']} · 진입 {t['entry']} 시가 · 청산 {t['exit']} 종가 · " +
                      ('보유 중·예정' if t['ret'] is None else f"{'맞음' if t['hit'] else '틀림'} {t['ret']:+.2f}%"))
    if not any_: L_.append('- (아직 없음)')
    open(MD, 'w', encoding='utf-8').write('\n'.join(L_) + '\n')
    print(f'실전 확인 단계: 등록 {len(order)}개(통과 {sum(e["tier"] == "통과" for e in order)}, 관찰 {sum(e["tier"] == "관찰" for e in order)}) · 이번 라운드 통과 {len(fin)} · 관찰 {len(wat)}')


if __name__ == '__main__':
    main()
