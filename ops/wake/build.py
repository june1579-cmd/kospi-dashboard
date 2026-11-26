# -*- coding: utf-8 -*-
"""ops/wake/build.py — 깨우기 장치(Cloudflare Worker) 배포 파일 만들기(2026-11-26, U-1126-2). wake-deploy 워크플로가 돌린다.
ops/wake/targets.json 의 워크플로 파일에서 예약(cron)을 그대로 읽어 표를 만들고 ops/wake/dist/worker.js·wrangler.toml 을 쓴다.
워크플로 파일에 workflow_dispatch 입력 slot 과 깨우기 중복 확인(ops/wake/guard.py)이 없으면 그 워크플로는 빼고 알린다
(slot 이 없으면 GitHub 가 '모르는 입력'으로 거절하고, 확인 단계가 없으면 늦게 온 예약과 두 번 돈다).
결과 요약은 ops/wake/dist/table.json 에도 쓴다. 비밀값을 읽지 않는다.
"""
import json
import os
import sys

import yaml

T = json.load(open('ops/wake/targets.json', encoding='utf-8'))
rows, skipped = [], []
for f in T['targets']:
    p = f'.github/workflows/{f}'
    try:
        src = open(p, encoding='utf-8').read(); y = yaml.safe_load(src) or {}
    except Exception as ex:
        skipped.append(f'{f}: 읽지 못함({str(ex)[:60]})'); continue
    on = y.get('on', y.get(True)) or {}
    crons = [s['cron'] for s in (on.get('schedule') or []) if isinstance(s, dict) and s.get('cron')]
    inputs = ((on.get('workflow_dispatch') or {}) or {}).get('inputs') or {}
    if not crons: skipped.append(f'{f}: 예약 없음'); continue
    if 'slot' not in inputs: skipped.append(f'{f}: workflow_dispatch 입력 slot 없음'); continue
    if 'ops/wake/guard.py' not in src: skipped.append(f'{f}: 깨우기 중복 확인 단계 없음'); continue
    rows += [dict(wf=f, cron=c) for c in crons]
os.makedirs('ops/wake/dist', exist_ok=True)
js = open('ops/wake/worker.template.js', encoding='utf-8').read()
js = js.replace('__SCHEDULE__', json.dumps(rows, ensure_ascii=False)).replace('__REPO__', json.dumps(T['repo'])).replace('__REF__', json.dumps(T.get('ref', 'main')))
open('ops/wake/dist/worker.js', 'w', encoding='utf-8').write(js)
open('ops/wake/dist/wrangler.toml', 'w', encoding='utf-8').write(
    'name = "kospi-wake"\nmain = "worker.js"\ncompatibility_date = "2024-11-01"\nworkers_dev = false\n\n[triggers]\ncrons = ["* * * * *"]\n')
json.dump({'entries': rows, 'skipped': skipped, 'workflows': sorted({r['wf'] for r in rows})}, open('ops/wake/dist/table.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print(f'깨우기 표: 워크플로 {len({r["wf"] for r in rows})}개 · 예약 칸 {len(rows)}개')
for s in skipped: print('  뺌 —', s)
sys.exit(0 if rows else 1)
