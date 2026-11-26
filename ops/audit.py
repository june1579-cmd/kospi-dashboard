# -*- coding: utf-8 -*-
"""ops/audit.py — 업그레이드 에이전트용 운영 점검 자료 만들기(2026-11-26 추가).
GitHub 가 돌린다(.github/workflows/ops-audit.yml). Claude 를 쓰지 않는다. 숫자만 모으고 판단은 하지 않는다.

모으는 것(기간 AUDIT_DAYS 일, 기본 7)
  1 워크플로마다: 실행 수·결과별 수·성공률·연속 실패·마지막 성공·걸린 시간(중앙값·p90·합계)·다시 돌린 수·
    예약(schedule) 지킴률(예정 횟수 대비 실제)·예약 지연(중앙값·최대)·걸린 시간 추세
  2 자료 최신성: ops/systems.json 의 fresh 목록(파일·폴더·가지 끝) 마지막 커밋 시각
  3 가지(branch)마다 마지막 커밋 시각
  4 저장소: 크기, 큰 파일, 웹판 페이지 크기(아티팩트 256KB 한도 대비)
  5 감시·수리: 열린 수리 요청, 기간 안 수리 기록 수, 업그레이드 대기열 상태별 수
  6 Claude 예약 작업: ops/out/claude_tasks.json(업그레이드 에이전트가 적어 둔 것)이 있으면 요약만 옮김
결과: ops/out/audit_<기간>d.json → docs/ops/data/audit_<기간>d.json(웹판 '운영 점검')
비밀값은 읽지 않는다(GitHub 가 준 실행 토큰만 쓴다). 다른 코드를 실행하지 않는다.
"""
import datetime as dt
import glob
import json
import os
import re
import statistics
import subprocess
import sys
from collections import Counter

import yaml
from croniter import croniter

KST = dt.timezone(dt.timedelta(hours=9))
UTC = dt.timezone.utc
REPO = os.environ.get('GITHUB_REPOSITORY', 'june1579-cmd/kospi-dashboard')
DAYS = int(os.environ.get('AUDIT_DAYS') or 7)
NOW = dt.datetime.now(UTC)
SINCE = NOW - dt.timedelta(days=DAYS)
BAD = {'failure', 'timed_out', 'startup_failure'}
SKIP = {'cancelled', 'skipped', 'neutral', 'action_required', 'stale'}
ERRS = []


def gh_json(path):
    r = subprocess.run(['gh', 'api', path], capture_output=True, text=True, timeout=90)
    if r.returncode != 0: raise RuntimeError((r.stderr or r.stdout).strip()[:200])
    return json.loads(r.stdout)


def gh_lines(path, jq):
    r = subprocess.run(['gh', 'api', '--paginate', path, '--jq', jq], capture_output=True, text=True, timeout=600)
    if r.returncode != 0: raise RuntimeError((r.stderr or r.stdout).strip()[:200])
    return [json.loads(x) for x in r.stdout.splitlines() if x.strip()]


def t(s):
    return dt.datetime.fromisoformat(s.replace('Z', '+00:00')).astimezone(UTC) if s else None


def k(d):
    return d.astimezone(KST).strftime('%Y-%m-%d %H:%M') if d else None


def mins(a, b):
    return round((b - a).total_seconds() / 60, 1) if a and b else None


def pct(a, b):
    return round(100 * a / b, 1) if b else None


def load_workflow_files():
    """기본 가지(main)의 워크플로 파일 → {경로: {name, crons, triggers}}. 예약은 기본 가지 파일만 돈다."""
    out = {}
    for f in sorted(glob.glob('.github/workflows/*.yml') + glob.glob('.github/workflows/*.yaml')):
        try:
            y = yaml.safe_load(open(f, encoding='utf-8')) or {}
            on = y.get('on', y.get(True))        # pyyaml 은 키 on 을 True 로 읽는다
            trig = list(on.keys()) if isinstance(on, dict) else ([on] if isinstance(on, str) else list(on or []))
            sch = (on.get('schedule') if isinstance(on, dict) else None) or []
            out[f] = dict(name=y.get('name') or os.path.basename(f), crons=[s['cron'] for s in sch if isinstance(s, dict) and s.get('cron')], triggers=trig)
        except Exception as ex:
            ERRS.append(f'워크플로 파일 읽기 실패 {f}: {str(ex)[:80]}')
    return out


def cron_ticks(expr, a, b):
    out = []; it = croniter(expr, a)
    for _ in range(5000):
        x = it.get_next(dt.datetime)
        if x > b: break
        out.append(x)
    return out


def last_tick(exprs, at):
    best = None
    for e in exprs:
        try:
            x = croniter(e, at).get_prev(dt.datetime)
            if best is None or x > best: best = x
        except Exception: pass
    return best


def analyze_runs(runs, files, sysmap, api):
    by = {}
    for r in runs: by.setdefault(r['path'], []).append(r)
    paths = set(by) | set(files)
    res = []
    for p in sorted(paths):
        rs = sorted(by.get(p, []), key=lambda r: r['created_at'], reverse=True)
        f = files.get(p, {})
        name = api.get(p, {}).get('name') or f.get('name') or (rs[0]['name'] if rs else None) or p   # 실행 이름(run-name)이 아니라 워크플로 이름
        born = t(api.get(p, {}).get('created_at')) or SINCE
        concl = Counter((r['conclusion'] or r['status']) for r in rs)
        done = [r for r in rs if r['status'] == 'completed' and r['conclusion'] not in SKIP]
        ok = [r for r in done if r['conclusion'] == 'success']
        streak = 0
        for r in done:
            if r['conclusion'] in BAD: streak += 1
            else: break
        durs = [d for d in (mins(t(r.get('run_started_at')), t(r['updated_at'])) for r in done) if d is not None and d >= 0]
        recent = [mins(t(r.get('run_started_at')), t(r['updated_at'])) for r in done if t(r['created_at']) > NOW - dt.timedelta(hours=48)]
        older = [mins(t(r.get('run_started_at')), t(r['updated_at'])) for r in done if t(r['created_at']) <= NOW - dt.timedelta(hours=48)]
        recent = [x for x in recent if x is not None]; older = [x for x in older if x is not None]
        w = dict(name=name, path=p, on_main=p in files, triggers=f.get('triggers', []), crons=f.get('crons', []),
                 system=sysmap.get(name), runs=len(rs), by_result=dict(concl), completed=len(done), success=len(ok),
                 success_rate=pct(len(ok), len(done)), fail_streak=streak,
                 reruns=sum(1 for r in rs if (r.get('run_attempt') or 1) > 1),
                 events=dict(Counter(r['event'] for r in rs)),
                 last=dict(at=k(t(rs[0]['created_at'])), result=rs[0]['conclusion'] or rs[0]['status'], event=rs[0]['event'], branch=rs[0]['head_branch'], id=rs[0]['id']) if rs else None,
                 last_success=k(t(ok[0]['updated_at'])) if ok else None,
                 last_failure=dict(at=k(t(next(r for r in done if r['conclusion'] in BAD)['updated_at'])), id=next(r for r in done if r['conclusion'] in BAD)['id']) if any(r['conclusion'] in BAD for r in done) else None,
                 dur_median=round(statistics.median(durs), 1) if durs else None,
                 dur_p90=round(sorted(durs)[int(0.9 * (len(durs) - 1))], 1) if durs else None,
                 dur_total=round(sum(durs), 1) if durs else 0,
                 dur_recent_median=round(statistics.median(recent), 1) if recent else None,
                 dur_older_median=round(statistics.median(older), 1) if older else None,
                 branches=dict(Counter(r['head_branch'] for r in rs)))
        # 예약 지킴률·지연(기본 가지 파일의 예약만)
        if w['crons']:
            ticks = []; gap = None
            for e in w['crons']:
                try:
                    ticks += cron_ticks(e, max(SINCE, born), NOW - dt.timedelta(hours=1))     # 워크플로가 생긴 뒤의 예정만 센다
                    d = cron_ticks(e, NOW - dt.timedelta(days=8), NOW)
                    g = min((b - a).total_seconds() / 60 for a, b in zip(d, d[1:])) if len(d) > 1 else None
                    if g is not None: gap = g if gap is None else min(gap, g)
                except Exception as ex: ERRS.append(f'예약 식 해석 실패 {name} {e}: {ex}')
            # 2026-11-26: 깨우기 장치(ops/wake)가 부른 실행(이름에 '깨우기')도 예약 실행으로 센다. 늦게 와서 스스로 취소한 예약 실행(중복)은 빼고 따로 센다
            wake = [r for r in rs if r['event'] == 'workflow_dispatch' and '깨우기' in (r.get('display_title') or '')]
            dup = [r for r in rs if r['event'] == 'schedule' and r.get('conclusion') == 'cancelled' and wake]
            sch = [r for r in rs if r['event'] == 'schedule' and r not in dup] + wake
            delays = []
            for r in sch:
                c = t(r['created_at']); lt = last_tick(w['crons'], c)
                if lt: delays.append(mins(lt, c))
            w['schedule'] = dict(expected=len(ticks), actual=len(sch), coverage=pct(len(sch), len(ticks)) if ticks else None,
                                 delay_median=round(statistics.median(delays), 1) if delays else None,
                                 delay_max=max(delays) if delays else None,
                                 delay_over60=sum(1 for d in delays if d >= 60), min_gap=gap, woken=len(wake), dup_cancelled=len(dup),
                                 delay_note='예약 간격이 짧아 지연은 간격보다 작게만 보임(지킴률을 볼 것)' if gap is not None and gap < 120 else None)
        flags = []
        if streak >= 2: flags.append(f'연속 실패 {streak}번')
        elif streak == 1: flags.append('마지막 실행 실패')
        if len(done) >= 3 and (w['success_rate'] or 0) < 80: flags.append(f"성공률 {w['success_rate']}%")
        s = w.get('schedule')
        if s and s['expected'] >= 3 and (s['coverage'] or 0) < 70: flags.append(f"예약 지킴 {s['coverage']}%({s['actual']}/{s['expected']})")
        if s and (s['delay_max'] or 0) >= 60: flags.append(f"예약 지연 최대 {s['delay_max']:.0f}분")
        if w['on_main'] and w['crons'] and not rs: flags.append('예약이 있는데 실행 없음')
        if not w['crons'] and not rs: flags.append(f'{DAYS}일 동안 실행 없음')
        if w['dur_recent_median'] and w['dur_older_median'] and w['dur_recent_median'] > 2 and w['dur_recent_median'] > 1.5 * w['dur_older_median']:
            flags.append(f"걸린 시간 늘어남({w['dur_older_median']}→{w['dur_recent_median']}분)")
        if (w['dur_p90'] or 0) >= 60: flags.append(f"오래 걸림(p90 {w['dur_p90']}분)")
        if w['reruns'] >= 2: flags.append(f"다시 돌림 {w['reruns']}번")
        if not w['system']: flags.append('분류 안 됨(ops/systems.json)')
        w['flags'] = flags
        res.append(w)
    return res


def freshness(systems):
    out = []; tips = {}
    for s in systems:
        for fr in s.get('fresh', []):
            try:
                if fr.get('path'):
                    cm = gh_json(f"repos/{REPO}/commits?sha={fr['br']}&path={fr['path']}&per_page=1")
                    last = t(cm[0]['commit']['committer']['date']) if cm else None
                else:
                    if fr['br'] not in tips: tips[fr['br']] = t(gh_json(f"repos/{REPO}/branches/{fr['br']}")['commit']['commit']['committer']['date'])
                    last = tips[fr['br']]
                age = round((NOW - last).total_seconds() / 3600, 1) if last else None
                out.append(dict(system=s['id'], label=fr['label'], br=fr['br'], path=fr.get('path') or '(가지 끝)', last=k(last), age_h=age,
                                max_h=fr.get('max_h'), stale=bool(age is None or (fr.get('max_h') and age > fr['max_h']))))
            except Exception as ex:
                out.append(dict(system=s['id'], label=fr['label'], br=fr['br'], path=fr.get('path'), last=None, age_h=None, max_h=fr.get('max_h'), stale=None, error=str(ex)[:100]))
    return out


def branches():
    out = []
    try:
        for b in gh_lines(f'repos/{REPO}/branches?per_page=100', '.[] | {name, sha: .commit.sha}'):
            try:
                c = gh_json(f"repos/{REPO}/commits/{b['sha']}")
                d = t(c['commit']['committer']['date'])
                out.append(dict(name=b['name'], last=k(d), age_d=round((NOW - d).total_seconds() / 86400, 1), msg=(c['commit']['message'] or '').splitlines()[0][:80]))
            except Exception as ex:
                out.append(dict(name=b['name'], error=str(ex)[:80]))
    except Exception as ex:
        ERRS.append(f'가지 목록 실패: {str(ex)[:100]}')
    return sorted(out, key=lambda x: x.get('age_d') or 0)


def repo_files():
    big = []; dirs = Counter()
    for root, ds, fs in os.walk('.'):
        if '/.git' in root or root.startswith('./.git'): continue
        for fn in fs:
            p = os.path.join(root, fn)[2:]
            try: sz = os.path.getsize(p)
            except OSError: continue
            big.append((sz, p)); dirs[p.split('/')[0] if '/' in p else '(맨 위)'] += sz
    big.sort(reverse=True)
    pages = {p: os.path.getsize(p) for p in ['docs/page.html', 'docs/index.html', 'docs/ai/page.html', 'docs/ai/index.html', 'docs/fo/index.html', 'docs/lab/index.html', 'docs/stocks/index.html'] if os.path.exists(p)}
    return dict(largest=[dict(path=p, kb=round(s / 1024)) for s, p in big[:15]],
                dirs_mb={d: round(s / 1048576, 1) for d, s in dirs.most_common(12)},
                total_mb=round(sum(dirs.values()) / 1048576, 1),
                pages_kb={p: round(s / 1024, 1) for p, s in pages.items()},
                over_50mb=[p for s, p in big if s > 50 * 1048576])


def ops_state():
    o = {}
    try: o['repair_open'] = json.load(open('state/repair_request.json', encoding='utf-8')).get('open', [])
    except Exception: o['repair_open'] = None
    try:
        heads = re.findall(r'^## (\d{4}-\d{2}-\d{2})', open('state/repair_log.md', encoding='utf-8').read(), re.M)
        o['repair_log_in_window'] = sum(1 for h in heads if h >= SINCE.astimezone(KST).strftime('%Y-%m-%d'))
        o['repair_log_total'] = len(heads)
    except Exception: pass
    try:
        q = json.load(open('ops/upgrade_queue.json', encoding='utf-8')).get('items', [])
        o['upgrade_queue'] = dict(Counter(i.get('status') for i in q))
    except Exception: o['upgrade_queue'] = None
    try:
        ct = json.load(open('ops/out/claude_tasks.json', encoding='utf-8'))
        tasks = ct.get('tasks', [])
        o['claude_tasks'] = dict(at=ct.get('at'), total=len(tasks), enabled=sum(1 for x in tasks if x.get('enabled')),
                                 failed_recent=[x.get('name') for x in tasks if x.get('enabled') and 'FAILED' in str(x.get('last_status', ''))])
    except Exception: o['claude_tasks'] = None
    return o


def main():
    systems = json.load(open('ops/systems.json', encoding='utf-8'))['systems']
    sysmap = {w: s['id'] for s in systems for w in s.get('workflows', [])}
    files = load_workflow_files()
    since = SINCE.strftime('%Y-%m-%dT%H:%M:%SZ')
    try:
        runs = gh_lines(f'repos/{REPO}/actions/runs?per_page=100&created=>={since}',
                        '.workflow_runs[] | {id,name,path,head_branch,event,status,conclusion,created_at,run_started_at,updated_at,run_attempt,display_title}')
    except Exception as ex:
        ERRS.append(f'실행 목록 실패: {str(ex)[:150]}'); runs = []
    # 기본 가지 파일에 없고 기간 안 실행도 없는 워크플로(다른 가지에만 있는 것 포함)도 목록에 넣는다
    api = {}
    try:
        for w in gh_lines(f'repos/{REPO}/actions/workflows?per_page=100', '.workflows[] | {name, path, state, created_at}'):
            api[w['path']] = w
            if w['path'] not in files and not any(r['path'] == w['path'] for r in runs):
                files.setdefault(w['path'], dict(name=w['name'], crons=[], triggers=['(기본 가지에 파일 없음)'], off_main=True))
    except Exception as ex:
        ERRS.append(f'워크플로 목록 실패: {str(ex)[:100]}')
    main_files = {p: v for p, v in files.items() if not v.get('off_main')}
    wf = analyze_runs(runs, main_files, sysmap, api)
    for p, v in files.items():
        if v.get('off_main') and not any(x['path'] == p for x in wf):
            wf.append(dict(name=v['name'], path=p, on_main=False, triggers=v['triggers'], crons=[], system=sysmap.get(v['name']), runs=0, by_result={}, completed=0, success=0,
                           success_rate=None, fail_streak=0, reruns=0, events={}, last=None, last_success=None, last_failure=None, dur_median=None, dur_p90=None, dur_total=0,
                           dur_recent_median=None, dur_older_median=None, branches={},
                           flags=[f'{DAYS}일 동안 실행 없음', '기본 가지에 파일 없음'] + ([] if sysmap.get(v['name']) else ['분류 안 됨(ops/systems.json)'])))
    fresh = freshness(systems)
    sys_sum = []
    for s in systems + [dict(id=None, label='분류 안 됨')]:
        ws = [w for w in wf if w['system'] == s['id']]
        if s['id'] is None and not ws: continue
        comp = sum(w['completed'] for w in ws); succ = sum(w['success'] for w in ws)
        sys_sum.append(dict(id=s['id'] or 'unmapped', label=s['label'], workflows=len(ws), runs=sum(w['runs'] for w in ws), completed=comp, success=succ,
                            success_rate=pct(succ, comp), failures=sum(sum(v for c, v in w['by_result'].items() if c in BAD) for w in ws),
                            run_minutes=round(sum(w['dur_total'] for w in ws), 1), flagged=[w['name'] for w in ws if w['flags']],
                            stale=[f['label'] for f in fresh if f['system'] == s['id'] and f.get('stale')]))
    comp = sum(w['completed'] for w in wf); succ = sum(w['success'] for w in wf)
    out = dict(generated_at=k(NOW), days=DAYS, since=k(SINCE), repo=REPO,
               summary=dict(workflows=len(wf), active=sum(1 for w in wf if w['runs']), runs=len(runs), completed=comp, success=succ, success_rate=pct(succ, comp),
                            failures=sum(1 for r in runs if r['conclusion'] in BAD), run_minutes=round(sum(w['dur_total'] for w in wf), 1),
                            flagged_workflows=sum(1 for w in wf if w['flags']), stale_data=sum(1 for f in fresh if f.get('stale'))),
               systems=sys_sum, workflows=sorted(wf, key=lambda w: (-len(w['flags']), -(w['runs'] or 0))), freshness=fresh,
               branches=branches(), repo_files=repo_files(), ops=ops_state(), errors=ERRS)
    try: out['repo_size_mb'] = round(gh_json(f'repos/{REPO}').get('size', 0) / 1024, 1)
    except Exception as ex: ERRS.append(f'저장소 정보 실패: {str(ex)[:80]}')
    os.makedirs('ops/out', exist_ok=True); os.makedirs('docs/ops/data', exist_ok=True)
    for p in (f'ops/out/audit_{DAYS}d.json', f'docs/ops/data/audit_{DAYS}d.json'):
        json.dump(out, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    S = out['summary']
    print(f"운영 점검 {DAYS}일: 워크플로 {S['workflows']}개(돈 것 {S['active']}) · 실행 {S['runs']} · 성공률 {S['success_rate']}% · 실패 {S['failures']} · "
          f"표시된 워크플로 {S['flagged_workflows']} · 멈춘 자료 {S['stale_data']} · 오류 {len(ERRS)}")
    for e in ERRS: print('  !', e)
    return 0


if __name__ == '__main__':
    sys.exit(main())
