# -*- coding: utf-8 -*-
"""watchdog.py — 감시·재시도·수리 요청(2026-11-23 추가). GitHub 가 한 시간마다 돌린다(.github/workflows/watchdog.yml).

하는 일
  1 워크플로 실패 감시: 대시보드·AI 경고판·선물옵션 대시보드·연구소·미국 한국 연동의 마지막 실행이 실패했는지 본다.
     · 다시 돌려도 안전한 것(공개 자료 수집·읽기 전용 계산)은 GitHub 에서 실패한 작업만 최대 2번 다시 돌린다.
     · KRX 로그인이 들어가는 작업, 총괄 세션이 관리하는 연구소 라운드는 다시 돌리지 않는다(계정 잠김·옛 설정으로 덮어쓰기 위험) — 알리기만 한다.
  2 자료 멈춤 감시: 각 대시보드의 결과 파일이 와 있어야 할 시각까지 갱신됐는지 본다.
  3 재시도로도 안 풀리면: 카카오톡으로 알리고(alerts/watchdog.txt) state/repair_request.json 에 수리 요청을 적는다.
     Claude 수리 에이전트(예약 작업)가 이 파일에 열린 요청이 있을 때만 일한다. 문제가 사라지면 요청을 지우고 '해결됨'을 알린다.
비밀값은 읽지 않는다(GitHub 가 준 실행 토큰만 쓴다). 상태 파일은 문제 목록이 바뀔 때만 커밋되게 시각을 넣지 않는다.
"""
import datetime as dt
import json
import os
import subprocess
import sys

KST = dt.timezone(dt.timedelta(hours=9))
REPO = os.environ.get('GITHUB_REPOSITORY', 'june1579-cmd/kospi-dashboard')
NOW = dt.datetime.now(KST)
BAD = ('failure', 'timed_out', 'startup_failure')
MAX_RERUN = 2
STATE, REQ, MD, KAKAO = 'state/watchdog.json', 'state/repair_request.json', 'report/watchdog.md', 'alerts/watchdog.txt'

# 워크플로 실패 감시: need = 연속 실패 몇 번이면 문제로 보나, grace_h = 실패 뒤 주인이 스스로 고칠 시간, rerun = GitHub 에서 다시 돌려도 되는가(safe_jobs 가 있으면 그 작업만 실패했을 때)
RUNS = [
    dict(key='run:update', wf='update.yml', br='main', label='코스피 대시보드 갱신', need=2, grace_h=0, rerun=False, repair=True, why='하루 3번씩 예약된 다음 실행이 재시도 역할'),
    dict(key='run:fo', wf='fo-dashboard.yml', br='main', label='선물옵션 대시보드 갱신', need=1, grace_h=0, rerun=True, safe_jobs=['build'], repair=True),
    dict(key='run:ai-feed', wf='ai-feed.yml', br='main', label='AI 경고판 원자료 수집', need=1, grace_h=0, rerun=True, repair=True),
    dict(key='run:short', wf='short-backfill.yml', br='main', label='공매도 수집', need=1, grace_h=0, rerun=False, repair=True),
    dict(key='run:lab-a', wf='deriv-lab.yml', br='deriv-research', label='연구소 갈래 A 라운드', need=1, grace_h=3, rerun=False, repair=True),
    dict(key='run:lab-b', wf='deriv-lab-b.yml', br='deriv-research', label='연구소 갈래 B 라운드', need=1, grace_h=3, rerun=False, repair=True),
    dict(key='run:lab-d', wf='deriv-lab-d.yml', br='deriv-research', label='연구소 갈래 D 라운드', need=1, grace_h=3, rerun=False, repair=True),
    dict(key='run:usk', wf='usk.yml', br='deriv-research', label='미국·한국 연동 계산', need=1, grace_h=3, rerun=False, repair=True),
    dict(key='run:criteria', wf='criteria-study.yml', br='deriv-research', label='통과 기준 검증 계산', need=1, grace_h=0, rerun=True, repair=True),
    dict(key='run:collect', wf='deriv-research.yml', br='deriv-research', label='선물·옵션 원자료 수집(KRX)', need=1, grace_h=3, rerun=False, repair=False),
    dict(key='run:lab-notify', wf='deriv-notify.yml', br='deriv-research', label='연구소 카카오 알림', need=1, grace_h=0, rerun=False, repair=True),
]
# 자료 멈춤 감시: rule = age(max_h 시간 넘게 그대로면 멈춤) | trading_am(거래일 11:30 뒤인데 오늘 갱신 없음) | weekday_pm(평일 21:30 뒤인데 오늘 19시 뒤 갱신 없음)
FRESH = [
    dict(key='stale:kospi', br='main', path='docs/meta.json', label='코스피 대시보드 웹판', rule='trading_am', repair=True),
    dict(key='stale:ai', br='main', path='out/ai_feed.csv', label='AI 경고판 원자료', rule='age', max_h=30, repair=True),
    dict(key='stale:fo', br='main', path='docs/fo/data', label='선물옵션 대시보드 자료', rule='weekday_pm', repair=True),
    dict(key='stale:lab-a', br='deriv-research', path='deriv/lab/state/latest_status.json', label='연구소 갈래 A(총괄 세션)', rule='age', max_h=15, repair=False, hint='Claude 예약 세션이 돌지 않음(사용량 한도일 수 있음)'),
    dict(key='stale:lab-b', br='deriv-research', path='deriv/lab/state_b/latest_status.json', label='연구소 갈래 B(총괄 세션)', rule='age', max_h=16, repair=False, hint='Claude 예약 세션이 돌지 않음(사용량 한도일 수 있음)'),
    dict(key='stale:lab-d', br='deriv-research', path='deriv/lab/state_d/latest_status.json', label='연구소 갈래 D(총괄 세션)', rule='age', max_h=12, repair=False, hint='Claude 예약 세션이 돌지 않음(사용량 한도일 수 있음)'),
    dict(key='stale:usk', br='deriv-research', path='deriv/us/out/dash.json', label='미국·한국 대시보드 자료', rule='age', max_h=40, repair=False, hint='Claude 예약 세션이 돌지 않음(사용량 한도일 수 있음)'),
]


def gh(*args, parse=True):
    r = subprocess.run(['gh', *args], capture_output=True, text=True, timeout=60)
    if r.returncode != 0: raise RuntimeError((r.stderr or r.stdout).strip()[:200])
    return json.loads(r.stdout) if parse else r.stdout


def t(s):
    return dt.datetime.fromisoformat(s.replace('Z', '+00:00')).astimezone(KST)


def trading_day(d):
    try: hol = set(json.load(open('pkg/holidays_kr.json', encoding='utf-8')).get('holidays', []))
    except Exception: hol = set()
    return d.weekday() < 5 and d.isoformat() not in hol


def check_run(c, st):
    """돌려주는 값: (문제 글 or None, 방금 다시 돌렸는지)"""
    rs = gh('api', f'repos/{REPO}/actions/workflows/{c["wf"]}/runs?branch={c["br"]}&per_page=6').get('workflow_runs', [])
    if not rs: return None, False
    if rs[0]['status'] != 'completed': return ('__keep__' if c['key'] in st else None), False     # 지금 도는 중(재시도 포함) — 판단 미룸
    done = [r for r in rs if r['status'] == 'completed' and r['conclusion'] != 'cancelled'][:c['need']]
    if len(done) < c['need'] or not all(r['conclusion'] in BAD for r in done): return None, False
    last = done[0]; age_h = (NOW - t(last['updated_at'])).total_seconds() / 3600
    if age_h < c['grace_h']: return ('__keep__' if c['key'] in st else None), False
    n = st.get(c['key'], {}).get('reruns', 0)
    if c['rerun'] and n < MAX_RERUN and last.get('run_attempt', 1) <= MAX_RERUN:
        ok = True
        if c.get('safe_jobs'):
            jobs = gh('api', f'repos/{REPO}/actions/runs/{last["id"]}/jobs?per_page=50').get('jobs', [])
            ok = all(j['name'] in c['safe_jobs'] for j in jobs if j.get('conclusion') in BAD)
        if ok:
            try:
                if os.environ.get('WATCHDOG_DRY') == '1': raise RuntimeError('시험 실행 — 다시 돌리지 않음')
                gh('run', 'rerun', str(last['id']), '--failed', '-R', REPO, parse=False)
                st.setdefault(c['key'], {})['reruns'] = n + 1
                return f'__rerun__{n + 1}', True
            except Exception as ex:
                print('다시 돌리기 실패', c['wf'], ex)
    why = '' if c['rerun'] else f" · 자동 재시도 안 함({c.get('why') or 'KRX 로그인 또는 총괄 세션 담당'})"
    return f"{c['label']} 실패({t(last['updated_at']):%m/%d %H:%M}{', 재시도 ' + str(n) + '번 뒤에도' if n else ''}){why} · 실행 번호 {last['id']}", False


def check_fresh(c):
    cm = gh('api', f'repos/{REPO}/commits?sha={c["br"]}&path={c["path"]}&per_page=1')
    if not cm: return f"{c['label']}: 파일이 없음({c['path']})"
    last = t(cm[0]['commit']['committer']['date']); age_h = (NOW - last).total_seconds() / 3600; stale = False
    if c['rule'] == 'age': stale = age_h > c['max_h']
    elif c['rule'] == 'trading_am': stale = trading_day(NOW.date()) and (NOW.hour, NOW.minute) >= (11, 30) and last.date() < NOW.date()
    elif c['rule'] == 'weekday_pm': stale = NOW.weekday() < 5 and (NOW.hour, NOW.minute) >= (21, 30) and last < NOW.replace(hour=19, minute=0, second=0, microsecond=0)
    return f"{c['label']} 멈춤(마지막 갱신 {last:%m/%d %H:%M}, {age_h:.0f}시간 전){' · ' + c['hint'] if c.get('hint') else ''}" if stale else None


def main():
    st = json.load(open(STATE, encoding='utf-8')) if os.path.exists(STATE) else {}
    before = json.dumps(st, ensure_ascii=False, sort_keys=True); msgs = []; errs = []
    for c in RUNS + FRESH:
        try:
            if 'wf' in c: txt, _ = check_run(c, st)
            else: txt = check_fresh(c)
        except Exception as ex:
            errs.append(f"{c['label']}: 확인 불가({str(ex)[:80]})"); continue      # 확인 자체가 안 되면 문제로 치지 않고 기록만(다음 시간에 다시 봄)
        cur = st.get(c['key'])
        if txt == '__keep__': continue
        if txt and txt.startswith('__rerun__'):
            st[c['key']].update(label=c['label'], open=False, since=st[c['key']].get('since') or f'{NOW:%Y-%m-%d %H:%M}')
            print(f"{c['label']}: 실패한 작업만 다시 돌림({txt[9:]}번째)"); continue
        if txt:
            e = st.setdefault(c['key'], {}); first = not e.get('open')
            last_n = e.get('notified'); due = first or (last_n and (NOW - dt.datetime.fromisoformat(last_n)).total_seconds() > 24 * 3600)
            e.update(label=c['label'], text=txt, open=True, repair=bool(c.get('repair')), since=e.get('since') or f'{NOW:%Y-%m-%d %H:%M}')
            if due:
                e['notified'] = NOW.isoformat(timespec='minutes')
                msgs.append(f"[감시] {txt}" + (' · 수리 에이전트에 넘김' if c.get('repair') else '') + ('' if first else ' (24시간째 그대로)'))
        elif cur:
            if cur.get('open') and cur.get('notified'): msgs.append(f"[감시 해결] {cur.get('label')} — 정상으로 돌아옴({NOW:%m/%d %H:%M} 확인)")
            elif cur.get('reruns'): print(f"{cur.get('label')}: 다시 돌린 뒤 정상")
            st.pop(c['key'], None)
    os.makedirs('state', exist_ok=True); os.makedirs('report', exist_ok=True); os.makedirs('alerts', exist_ok=True)
    after = json.dumps(st, ensure_ascii=False, sort_keys=True)
    if after != before:
        json.dump(st, open(STATE, 'w', encoding='utf-8'), ensure_ascii=False, indent=1, sort_keys=True)
        opn = {k: v for k, v in st.items() if v.get('open')}
        json.dump({'open': [dict(key=k, label=v['label'], text=v['text'], since=v['since']) for k, v in sorted(opn.items()) if v.get('repair')],
                   'note': '열린 요청이 있을 때만 Claude 수리 에이전트가 일한다(REPAIR_AGENT.md). 문제가 사라지면 watchdog.py 가 지운다.'}, open(REQ, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        L = ['# 감시 상태', '', f'- 바뀐 시각: {NOW:%Y-%m-%d %H:%M} KST', '']
        L += [f"- {'열림' if v.get('open') else '다시 돌리는 중'} · {v.get('label')} · {v.get('text', '')} · {v.get('since')}부터 · 재시도 {v.get('reruns', 0)}번" for k, v in sorted(st.items())] or ['- 열린 문제 없음']
        open(MD, 'w', encoding='utf-8').write('\n'.join(L) + '\n')
    cut = lambda m: m if len(m) <= 195 else m[:194] + '…'
    if msgs: open(KAKAO, 'w', encoding='utf-8').write('\n=====\n'.join(cut(m) for m in msgs[:5]) + '\n')
    for e in errs: print(e)
    print(f'감시: 항목 {len(RUNS) + len(FRESH)}개 · 열린 문제 {sum(1 for v in st.values() if v.get("open"))}개 · 알림 {len(msgs)}통 · 확인 불가 {len(errs)}개')
    out = os.environ.get('GITHUB_OUTPUT')
    if out: open(out, 'a').write(f"send={'1' if msgs else '0'}\nchanged={'1' if after != before or msgs else '0'}\n")


if __name__ == '__main__':
    sys.exit(main())
