# -*- coding: utf-8 -*-
"""ops/wake/guard.py — 늦게 온 GitHub 예약 실행이 '깨우기 장치'가 이미 돌린 칸이면 스스로 취소한다(2026-11-26, 업그레이드 요청 U-1126-2).

깨우기 장치(Cloudflare Worker, ops/wake/README.md)가 정해진 시각에 workflow_dispatch 로 워크플로를 부르고,
GitHub 자체 예약(schedule)은 예비로 남겨 둔다. GitHub 예약이 몇 시간 늦게 오면 같은 칸을 두 번 돌게 되므로,
예약(schedule)으로 시작한 실행만 이 단계에서 확인한다:
  · ops/wake/active.json 의 active 가 true 가 아니면(장치를 아직 안 켬) 아무것도 하지 않는다.
  · 이 실행의 예약 식(cron)으로 '원래 시각' T 를 구하고, T 2분 전부터 지금까지 이 워크플로의 workflow_dispatch 실행이 있으면
    (장치가 그 칸을 이미 돌림) 이 실행을 취소한다. 없으면(장치가 그 칸을 놓침) 그대로 진행한다 — 예비가 일한다.
  · 장치 실행과 거의 같은 때 시작했으면 T+3분까지 기다린 뒤 확인한다(둘 다 도는 일을 막음).
워크플로에서는 main 의 이 파일을 받아(curl raw) `python3 … || true` 로 부른다 — 작업이 다른 가지를 받아도 같고, 이 단계가 실패해도 실행은 그대로 간다.
비밀값은 읽지 않는다(GitHub 가 준 실행 토큰만). 표준 라이브러리와 gh 만 쓴다.
"""
import datetime as dt
import json
import os
import subprocess
import sys
import time

UTC = dt.timezone.utc


def gh(*args, parse=True):
    r = subprocess.run(['gh', *args], capture_output=True, text=True, timeout=60)
    if r.returncode != 0: raise RuntimeError((r.stderr or r.stdout).strip()[:200])
    return json.loads(r.stdout) if parse else r.stdout


def field_ok(spec, v, lo, hi):
    for part in spec.split(','):
        step = 1
        if '/' in part: part, s = part.split('/'); step = int(s)
        if part == '*': a, b = lo, hi
        elif '-' in part: a, b = map(int, part.split('-'))
        else: a = b = int(part)
        if a <= v <= b and (v - a) % step == 0: return True
    return False


def cron_match(expr, t):
    mi, ho, dom, mon, dow = expr.split()
    wd = (t.weekday() + 1) % 7                     # 일=0 … 토=6
    d_ok = field_ok(dom, t.day, 1, 31); w_ok = field_ok(dow, wd, 0, 6)
    day = (d_ok and w_ok) if (dom == '*' or dow == '*') else (d_ok or w_ok)
    return field_ok(mi, t.minute, 0, 59) and field_ok(ho, t.hour, 0, 23) and field_ok(mon, t.month, 1, 12) and day


def last_tick(expr, at):
    t = at.replace(second=0, microsecond=0)
    for _ in range(60 * 48):
        if cron_match(expr, t): return t
        t -= dt.timedelta(minutes=1)
    return None


def main():
    if os.environ.get('GITHUB_EVENT_NAME') != 'schedule': return 0
    repo, run_id = os.environ['GITHUB_REPOSITORY'], os.environ['GITHUB_RUN_ID']
    try:                                           # 켜짐 여부는 main 의 ops/wake/active.json(작업이 다른 가지를 받았어도 같은 기준)
        A = json.loads(gh('api', f'repos/{repo}/contents/ops/wake/active.json?ref=main', '-H', 'Accept: application/vnd.github.raw', parse=False))
    except Exception:
        try: A = json.load(open('ops/wake/active.json', encoding='utf-8'))
        except Exception: A = {}
    if not A.get('active'): print('깨우기 장치 꺼짐 — 확인 안 함'); return 0
    ev = json.load(open(os.environ['GITHUB_EVENT_PATH'], encoding='utf-8'))
    expr = (ev.get('schedule') or '').strip()
    wf = os.environ.get('GITHUB_WORKFLOW_REF', '').split('@')[0].rsplit('/', 1)[-1]
    if not expr or not wf: print('예약 식 또는 워크플로 이름 없음 — 확인 안 함'); return 0
    run = gh('api', f'repos/{repo}/actions/runs/{run_id}')
    created = dt.datetime.fromisoformat(run['created_at'].replace('Z', '+00:00'))
    T = last_tick(expr, created)
    if not T: print('원래 시각을 못 찾음 — 확인 안 함'); return 0
    wait = (T + dt.timedelta(minutes=3) - dt.datetime.now(UTC)).total_seconds()
    if wait > 0: time.sleep(min(wait, 200))
    since = (T - dt.timedelta(minutes=2)).strftime('%Y-%m-%dT%H:%M:%SZ')
    rs = gh('api', f'repos/{repo}/actions/workflows/{wf}/runs?event=workflow_dispatch&created=>={since}&per_page=20').get('workflow_runs', [])
    rs = [r for r in rs if str(r['id']) != str(run_id)]
    late = round((created - T).total_seconds() / 60)
    if not rs:
        print(f'예약 {expr} 원래 시각 {T:%m/%d %H:%M} UTC · {late}분 늦게 옴 · 깨우기 실행 없음 → 예비로 그대로 진행'); return 0
    print(f'예약 {expr} 원래 시각 {T:%m/%d %H:%M} UTC · {late}분 늦게 옴 · 깨우기 장치가 이미 돌림(실행 {rs[0]["id"]}) → 이 실행 취소')
    gh('run', 'cancel', str(run_id), '-R', repo, parse=False)
    time.sleep(120)                                # 취소가 닿을 때까지 기다린다(다음 단계로 가지 않게)
    return 0


if __name__ == '__main__':
    try: sys.exit(main())
    except Exception as ex:
        print('깨우기 중복 확인 실패 — 그대로 진행:', str(ex)[:200]); sys.exit(0)
