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
2026-11-26: 업그레이드 에이전트(UPGRADE_AGENT.md)가 ops/upgrade_queue.json 에 적은 요청 중 '열림(open)·승인됨(approved)'도 수리 요청에 함께 넣는다(키 upgrade:<번호>).
  끝난 요청(done·failed 등)은 빠진다. `python3 watchdog.py --sync-only` 는 감시 점검 없이 수리 요청 파일만 다시 맞춘다(ops-sync.yml).
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
QUEUE = 'ops/upgrade_queue.json'   # 2026-11-26 업그레이드 요청 대기열
REQ_NOTE = '열린 요청이 있을 때만 Claude 수리 에이전트가 일한다(REPAIR_AGENT.md). 문제가 사라지면 watchdog.py 가 지운다. upgrade: 요청은 ops/upgrade_queue.json 에서 끝남으로 바뀌면 빠진다.'

# 워크플로 실패 감시: need = 연속 실패 몇 번이면 문제로 보나, grace_h = 실패 뒤 주인이 스스로 고칠 시간, rerun = GitHub 에서 다시 돌려도 되는가(safe_jobs 가 있으면 그 작업만 실패했을 때)
RUNS = [
    dict(key='run:update', wf='update.yml', br='main', label='코스피 대시보드 갱신', need=2, grace_h=0, rerun=False, repair=True, why='하루 3번씩 예약된 다음 실행이 재시도 역할'),
    dict(key='run:fo', wf='fo-dashboard.yml', br='main', label='선물옵션 대시보드 갱신', need=1, grace_h=0, rerun=True, safe_jobs=['build'], repair=True),
    dict(key='run:ai-board', wf='ai-board.yml', br='main', label='AI 경고판 계산(원자료 수집 포함)', need=2, grace_h=0, rerun=True, repair=True, why='하루 여러 번 도는 다음 실행이 재시도 역할'),
    dict(key='run:audit', wf='audit.yml', br='main', label='신호·종목 명단 검증', need=1, grace_h=0, rerun=True, repair=True),
    dict(key='run:short', wf='short-backfill.yml', br='main', label='공매도 수집', need=1, grace_h=0, rerun=False, repair=True),
    dict(key='run:lab-a', wf='deriv-lab.yml', br='deriv-research', label='연구소 갈래 A 라운드', need=1, grace_h=3, rerun=False, repair=True),
    dict(key='run:lab-b', wf='deriv-lab-b.yml', br='deriv-research', label='연구소 갈래 B 라운드', need=1, grace_h=3, rerun=False, repair=True),
    dict(key='run:lab-d', wf='deriv-lab-d.yml', br='deriv-research', label='연구소 갈래 D 라운드', need=1, grace_h=3, rerun=False, repair=True),
    dict(key='run:usk', wf='usk.yml', br='main', label='미국·한국 연동 계산', need=1, grace_h=0, rerun=True, repair=True),
    dict(key='run:criteria', wf='criteria-study.yml', br='deriv-research', label='통과 기준 검증 계산', need=1, grace_h=0, rerun=True, repair=True),
    dict(key='run:uni', wf='uni-lab.yml', br='main', label='통합 예측 연구소 계산(정해진 시각)', need=1, grace_h=0, rerun=True, repair=True),
    dict(key='run:uni-push', wf='uni-lab.yml', br='deriv-research', label='통합 예측 연구소 계산(실험)', need=1, grace_h=0, rerun=True, repair=True),
    dict(key='run:collect', wf='deriv-research.yml', br='deriv-research', label='선물·옵션 원자료 수집(KRX)', need=1, grace_h=3, rerun=False, repair=False),
    dict(key='run:lab-notify', wf='deriv-notify.yml', br='deriv-research', label='연구소 카카오 알림', need=1, grace_h=0, rerun=False, repair=True),
    # 2026-11-24: 미국 옵션 아침 추정(화~토 07:40 카톡)과 공개 시각 측정
    dict(key='run:uswalls', wf='us-walls.yml', br='main', label='미국 옵션 아침 추정(07:40 카톡)', need=1, grace_h=0, rerun=True, repair=True, event='schedule'),
    dict(key='run:occwalls', wf='occ-walls.yml', br='main', label='미국 옵션 공식 확정(OCC, 낮 카톡)', need=1, grace_h=0, rerun=True, repair=True, event='schedule'),
    # 2026-11-26: 장중 도달 확률(08:30판)·장중 선물 수급 수집(09:10판 포함)
    dict(key='run:reach', wf='reach.yml', br='main', label='장중 도달 확률(08:30판·검증)', need=1, grace_h=0, rerun=True, repair=True),
    dict(key='run:flow', wf='intraday-flow.yml', br='main', label='장중 선물 수급 수집·09:10판', need=1, grace_h=0, rerun=False, repair=True, event='schedule', why='수집 시간대가 지나면 다시 돌려도 의미 없음'),
    dict(key='run:pubwatch', wf='pub-watch.yml', br='main', label='미국 옵션 공개 시각 측정', need=2, grace_h=0, rerun=False, repair=True, why='한 시간마다 도는 다음 실행이 재시도 역할'),
]
# 자료 멈춤 감시: rule = age(max_h 시간 넘게 그대로면 멈춤) | trading_am(거래일 11:30 뒤인데 오늘 갱신 없음) | weekday_pm(평일 21:30 뒤인데 오늘 19시 뒤 갱신 없음)
#                | us_am(화~토 08:40 뒤인데 오늘 06:30 뒤 갱신 없음 — 미국 장 다음 날 아침 자료) | us_pm(화~토 16:30 뒤인데 오늘 09:00 뒤 갱신 없음 — OCC 확정)
FRESH = [
    dict(key='stale:kospi', br='main', path='docs/meta.json', label='코스피 대시보드 웹판', rule='trading_am', repair=True),
    dict(key='stale:ai', br='main', path='out/ai_feed.csv', label='AI 경고판 원자료', rule='age', max_h=30, repair=True),
    dict(key='stale:ai-board', br='main', path='ai_board/status.json', label='AI 경고판 계산 결과', rule='age', max_h=30, repair=True),
    dict(key='stale:fo', br='main', path='docs/fo/data', label='선물옵션 대시보드 자료', rule='weekday_pm', repair=True),
    # 2026-11-24: Signal A 프로젝트 동안 갈래 A·B·D 총괄 예약을 멈춰 두었으므로(사용자 지시) 이 세 줄의 '세션이 돌지 않음' 감시도 끈다. 예약을 다시 켜면 주석을 풀 것
    # dict(key='stale:lab-a', br='deriv-research', path='deriv/lab/state/latest_status.json', label='연구소 갈래 A(총괄 세션)', rule='age', max_h=15, repair=False, hint='Claude 예약 세션이 돌지 않음(사용량 한도일 수 있음)'),
    # dict(key='stale:lab-b', br='deriv-research', path='deriv/lab/state_b/latest_status.json', label='연구소 갈래 B(총괄 세션)', rule='age', max_h=16, repair=False, hint='Claude 예약 세션이 돌지 않음(사용량 한도일 수 있음)'),
    # dict(key='stale:lab-d', br='deriv-research', path='deriv/lab/state_d/latest_status.json', label='연구소 갈래 D(총괄 세션)', rule='age', max_h=12, repair=False, hint='Claude 예약 세션이 돌지 않음(사용량 한도일 수 있음)'),
    dict(key='stale:reach', br='main', path='docs/reach/data/pre.json', label='장중 도달 확률 08:30판', rule='trading_am', repair=True),
    dict(key='stale:usk', br='deriv-research', path='deriv/us/out/dash.json', label='미국·한국 연동 자료(웹판 10절)', rule='age', max_h=40, repair=True),
    dict(key='stale:uswalls', br='main', path='uswalls/latest.json', label='미국 옵션 아침 추정(웹판 11절)', rule='us_am', repair=True),
    dict(key='stale:occwalls', br='main', path='uswalls/occ_latest.json', label='미국 옵션 공식 확정(웹판 11절)', rule='us_pm', repair=True),
    # 2026-11-26 업그레이드 요청 U-1126-1: 방어종목 통합 명단 웹판(stocks-daily 가 매 거래일 갱신). 80시간 = 주말(금 저녁 → 월 저녁)을 넘기는 기준
    dict(key='stale:stocks', br='main', path='docs/stocks/stocks.json', label='방어종목 통합 명단 웹판', rule='age', max_h=80, repair=True),
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
    if c.get('event') == 'schedule':   # 예약 실행만 본다(손으로 돌린 시험 실행은 빼기). 2026-11-26: 깨우기 장치(ops/wake)가 부른 실행(이름에 '깨우기')도 예약 실행으로 본다
        rs = gh('api', f'repos/{REPO}/actions/workflows/{c["wf"]}/runs?branch={c["br"]}&per_page=20').get('workflow_runs', [])
        rs = [r for r in rs if r['event'] == 'schedule' or (r['event'] == 'workflow_dispatch' and '깨우기' in (r.get('display_title') or ''))][:6]
    else:
        ev = f'&event={c["event"]}' if c.get('event') else ''   # event 가 있으면 그 실행만 본다
        rs = gh('api', f'repos/{REPO}/actions/workflows/{c["wf"]}/runs?branch={c["br"]}&per_page=6{ev}').get('workflow_runs', [])
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
    elif c['rule'] == 'us_pm': stale = 1 <= NOW.weekday() <= 5 and (NOW.hour, NOW.minute) >= (16, 30) and last < NOW.replace(hour=9, minute=0, second=0, microsecond=0)
    elif c['rule'] == 'us_am': stale = 1 <= NOW.weekday() <= 5 and (NOW.hour, NOW.minute) >= (8, 40) and last < NOW.replace(hour=6, minute=30, second=0, microsecond=0)
    return f"{c['label']} 멈춤(마지막 갱신 {last:%m/%d %H:%M}, {age_h:.0f}시간 전){' · ' + c['hint'] if c.get('hint') else ''}" if stale else None


def check_content():
    """수집은 돌았지만 일부 출처를 못 받은 경우(파일 안의 상태 칸) — 기본 가지 checkout 에서 읽는다."""
    out = {}
    try:
        import csv
        bad = [r.get('name') or r.get('key') for r in csv.DictReader(open('out/ai_feed.csv', encoding='utf-8')) if (r.get('status') or '').strip() not in ('정상', '')]
        out['src:ai'] = ('AI 경고판 수집 일부 실패', f"AI 경고판 원자료 {len(bad)}개 항목을 못 받음: {', '.join(bad[:3])}{' 외' if len(bad) > 3 else ''}" if bad else None)
    except Exception as ex: print('AI 경고판 상태 읽기 실패', ex)
    try:
        S = json.load(open('fo/data/status.json', encoding='utf-8')); bad = [k for k, v in S.items() if isinstance(v, dict) and v.get('ok') is False]
        out['src:fo'] = ('선물옵션 대시보드 수집 일부 실패', f"선물옵션 대시보드 미국 자료 {len(bad)}개 출처를 못 받음: {', '.join(bad[:4])}" if bad else None)
    except Exception as ex: print('선물옵션 대시보드 상태 읽기 실패', ex)
    try:   # 2026-11-24: 미국 옵션 아침 추정 — 오늘 실행이 일부/전부 실패로 끝났는지
        U = json.load(open('uswalls/latest.json', encoding='utf-8'))
        fresh = str(U.get('at_kst', ''))[:10] == NOW.strftime('%Y-%m-%d') and not U.get('test')
        bad = fresh and U.get('status') in ('partial', 'fail')
        out['src:uswalls'] = ('미국 옵션 아침 추정 일부 실패', f"미국 옵션 아침 추정 {U.get('status')}: {' / '.join(U.get('errors') or [])[:120]}" if bad else None)
    except Exception as ex: print('미국 옵션 아침 추정 상태 읽기 실패', ex)
    try:   # 2026-11-24: 미국 옵션 공식 확정(OCC) — 오늘 실행이 시간 초과·실패로 끝났는지
        O = json.load(open('uswalls/occ_latest.json', encoding='utf-8'))
        fresh = str(O.get('at_kst', ''))[:10] == NOW.strftime('%Y-%m-%d') and not O.get('test')
        bad = fresh and O.get('status') in ('partial', 'fail', 'timeout')
        out['src:occwalls'] = ('미국 옵션 공식 확정 문제', f"미국 옵션 공식 확정(OCC) {O.get('status')}: {(O.get('note') or ' / '.join(O.get('errors') or []))[:120]}" if bad else None)
    except Exception as ex: print('미국 옵션 공식 확정 상태 읽기 실패', ex)
    return out


def check_wake():
    """2026-11-26(U-1126-2): 깨우기 장치(Cloudflare Worker)가 켜져 있으면(ops/wake/active.json) 감시 자신이 최근 3시간 안에 깨워졌는지 본다.
    장치가 멈추면(토큰 만료·Cloudflare 문제) GitHub 예비 예약만 남아 다시 몇 시간씩 늦어지므로 알린다."""
    try: A = json.load(open('ops/wake/active.json', encoding='utf-8'))
    except Exception: return {}
    if not A.get('active'): return {}
    try:
        on = dt.datetime.strptime(A.get('since', ''), '%Y-%m-%d %H:%M').replace(tzinfo=KST)
        if (NOW - on).total_seconds() < 3 * 3600: return {}                 # 막 켰으면 기다린다
    except Exception: pass
    rs = gh('api', f'repos/{REPO}/actions/workflows/watchdog.yml/runs?event=workflow_dispatch&per_page=20').get('workflow_runs', [])
    w = [r for r in rs if '깨우기' in (r.get('display_title') or '')]
    last = t(w[0]['created_at']) if w else None
    if last and (NOW - last).total_seconds() < 3 * 3600: return {'wake:down': ('정해진 시각 깨우기 장치', None)}
    head = f"마지막 깨우기 {last:%m/%d %H:%M}" if last else '깨운 기록 없음'
    return {'wake:down': ('정해진 시각 깨우기 장치', f"정해진 시각 깨우기(Cloudflare Worker) 멈춤 — {head} · 비밀값 WAKE_GITHUB_TOKEN(만료?)·Cloudflare 계정 확인 필요, 그동안은 GitHub 예비 예약만 돎")}


def upgrade_requests():
    """2026-11-26: 업그레이드 대기열에서 수리 에이전트가 할 차례인 것(open = 위험 낮음 자동, approved = 사용자 승인)만 고른다."""
    try: items = json.load(open(QUEUE, encoding='utf-8')).get('items', [])
    except Exception: return []
    out = []
    for i in items:
        if i.get('status') in ('open', 'approved'):
            out.append(dict(key=f"upgrade:{i.get('id')}", label=f"업그레이드 {i.get('id')} · {i.get('system', '')}",
                            text=f"{i.get('title', '')} — 할 일·확인 방법은 ops/upgrade_queue.json 의 {i.get('id')}(do·check) · 위험 {i.get('risk', '')}{' · 사용자 승인됨' if i.get('status') == 'approved' else ''}"[:300],
                            since=i.get('created', '')))
    return out


def write_req(st):
    """감시가 연 문제(repair=True) + 업그레이드 요청 → state/repair_request.json. 내용이 바뀐 때만 쓴다. 돌려주는 값: 바뀌었는지."""
    opn = {k: v for k, v in st.items() if v.get('open')}
    req = {'open': [dict(key=k, label=v['label'], text=v['text'], since=v['since']) for k, v in sorted(opn.items()) if v.get('repair')] + upgrade_requests(),
           'note': REQ_NOTE}
    new = json.dumps(req, ensure_ascii=False, indent=1)
    old = open(REQ, encoding='utf-8').read() if os.path.exists(REQ) else ''
    if new == old: return False
    os.makedirs('state', exist_ok=True); open(REQ, 'w', encoding='utf-8').write(new)
    return True


def sync_only():
    st = json.load(open(STATE, encoding='utf-8')) if os.path.exists(STATE) else {}
    ch = write_req(st)
    print(f"수리 요청 동기화: {'바뀜' if ch else '그대로'} · 업그레이드 요청 {len(upgrade_requests())}건")
    out = os.environ.get('GITHUB_OUTPUT')
    if out: open(out, 'a').write(f"changed={'1' if ch else '0'}\n")
    return 0


def main():
    st = json.load(open(STATE, encoding='utf-8')) if os.path.exists(STATE) else {}
    before = json.dumps(st, ensure_ascii=False, sort_keys=True); msgs = []; errs = []
    try: wake = check_wake()
    except Exception as ex: wake = {}; errs.append(f'깨우기 장치: 확인 불가({str(ex)[:80]})')
    extra = [dict(key=k, label=lab, text=txt, repair=True, content=True) for k, (lab, txt) in {**check_content(), **wake}.items()]
    for c in RUNS + FRESH + extra:
        try:
            if c.get('content'): txt = c['text']
            elif 'wf' in c: txt, _ = check_run(c, st)
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
        L = ['# 감시 상태', '', f'- 바뀐 시각: {NOW:%Y-%m-%d %H:%M} KST', '']
        L += [f"- {'열림' if v.get('open') else '다시 돌리는 중'} · {v.get('label')} · {v.get('text', '')} · {v.get('since')}부터 · 재시도 {v.get('reruns', 0)}번" for k, v in sorted(st.items())] or ['- 열린 문제 없음']
        open(MD, 'w', encoding='utf-8').write('\n'.join(L) + '\n')
    req_changed = write_req(st)      # 2026-11-26: 감시 상태가 그대로여도 업그레이드 요청이 바뀌면 다시 쓴다
    cut = lambda m: m if len(m) <= 195 else m[:194] + '…'
    if msgs: open(KAKAO, 'w', encoding='utf-8').write('\n=====\n'.join(cut(m) for m in msgs[:5]) + '\n')
    for e in errs: print(e)
    print(f'감시: 항목 {len(RUNS) + len(FRESH)}개 · 열린 문제 {sum(1 for v in st.values() if v.get("open"))}개 · 알림 {len(msgs)}통 · 확인 불가 {len(errs)}개')
    out = os.environ.get('GITHUB_OUTPUT')
    if out: open(out, 'a').write(f"send={'1' if msgs else '0'}\nchanged={'1' if after != before or msgs or req_changed else '0'}\n")


if __name__ == '__main__':
    sys.exit(sync_only() if '--sync-only' in sys.argv else main())
