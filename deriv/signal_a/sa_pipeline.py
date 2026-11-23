# -*- coding: utf-8 -*-
"""Signal A 파이프라인 도우미 — .github/workflows/signal-a-pipeline.yml 이 부른다(셸에 긴 로직을 두지 않으려고 여기에 모음).

하는 일(하위 명령)
  plan --phase 1|2|3     할 일 정하기. 1 = 준비된 t1~t5, 2 = 준비된 t6 → 표준 출력에 {"include": [{track, part, n}, …]} 한 줄.
                         3 = S3 을 돌릴 차례면 yes, 아니면 no.
  fail --track --part --log [--out 파일]
                         실패 기록. status.json 에 need_claude=true·fail={track, part, tail(오류 끝 30줄)}·tracks[tN]='실패' 를 적고
                         카카오 글(notify/kakao_fail_<줄기>.txt)을 만든다. --out 을 주면 그 파일에 기록만 쓴다(계산 작업용, 상태는 안 건드림).
  judge --matrix JSON --art 폴더
                         내려받은 조각(artifact)을 tN/out/parts/ 에 놓고, 줄기마다 합치기(run.py --merge) → 판정(sa_judge.py)을 3번까지 시도.
                         조각 하나라도 실패·없음이면 그 줄기는 판정하지 않고 '실패'로 둔다(고친 뒤 줄기 전체를 다시 돌림).
  status [--new-done N] [--round R] [--harness 결과] [--jobs "plan=success,judge1=failure,…"] [--stuck]
                         status.json 을 실제 파일 상태로 다시 맞춘다(tracks·stage·need_claude·why). 다시 시작할지(restart=yes|no)도 알려 준다.
                         --jobs = 작업 결과(맨 끝 작업이 넘김): 작업 자체가 실패했으면 fail={track:'pipeline', part:작업 이름} 으로 적는다.
                         --stuck = 다시 시작이 실패했을 때: 준비된 일이 남았다고 적어 need_claude 를 켠다(총괄이 run.txt 로 띄우게).
  kakao [--mark]         이번에 새로 생긴 카카오 글만 notify/kakao.txt 로 모은다. --mark = 보낸 뒤 '보냄'으로 적는다(두 번 보내지 않게).
  log --stage --text     log.md 에 한 줄 붙인다(표 꼴을 지켜 마지막 번호 + 1).
  save --msg "한 일"      deriv/signal_a 만 커밋·push(조각 폴더 out/parts 와 _data 는 빼고). push 는 4번까지 다시 시도.

약속
  - 줄기 = t1..t6. '준비된 줄기' = tN/run.py 와 tN/SPEC.md 가 있고 tN/out/done.json 이 없는 것.
    t6 은 t1~t5 의 done.json 이 모두 있을 때만. S3 은 t1~t6 done.json 이 모두 있고 s3/out/done.json 이 없을 때(sa_s3.py 가 있어야 함).
  - 조각 결과 artifact 이름: sa-<줄기>-<조각 번호>, 실패 기록: sa-fail-<줄기>-<조각 번호>(안에 fail.json).
  - 자료(panel.pkl 등)는 읽지 않는다(C.Data() 를 부르지 않음). 기준 숫자·판정은 sa_judge.py 가 한다 — 여기서는 순서만 잇는다.
  - status.json 에 이 파일이 더 적는 칸: fails(실패 전부, fail 은 그 첫째), harness('ok' | '실패'), stuck(남은 일이 있는데 멈춘 까닭 또는 null).
"""
import argparse
import glob
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

import pandas as pd

import sa_common as C

T15 = ['t1', 't2', 't3', 't4', 't5']
TRACKS = T15 + ['t6']
NOTIFY = os.path.join(C.SA, 'notify')
TRIES = 3                                                          # 다시 돌리기: 3번까지
MAX_ROUND = 6                                                      # 스스로 다시 시작: round 가 6 이상이 되면 멈춤(무한 반복 방지)
WAIT = int(os.environ.get('SA_RETRY_WAIT', '10'))                  # 다시 시도 사이 쉬는 시간(초)
WHERE = {'merge': '합치기', 'judge': '판정'}


def now(fmt='%Y-%m-%d %H:%M'):
    return pd.Timestamp.now(tz='Asia/Seoul').strftime(fmt)


def gh_out(**kw):
    """워크플로 출력값. GitHub 안이면 $GITHUB_OUTPUT 파일에, 밖이면 화면에만."""
    p = os.environ.get('GITHUB_OUTPUT')
    for k, v in kw.items():
        print(f'{k}={v}', flush=True)
        if p:
            with open(p, 'a', encoding='utf-8') as f: f.write(f'{k}={v}\n')


# ------------------------------------------------------------------ 파일 상태로 할 일 정하기
def has_code(t):
    d = os.path.join(C.SA, t)
    return os.path.exists(os.path.join(d, 'run.py')) and os.path.exists(os.path.join(d, 'SPEC.md'))


def done(t):
    return os.path.exists(os.path.join(C.SA, t, 'out', 'done.json'))


def ready(phase):
    """준비된 줄기 목록. phase 1 = t1~t5, phase 2 = t6(t1~t5 가 모두 끝났을 때만)."""
    if phase == 1: return [t for t in T15 if has_code(t) and not done(t)]
    if has_code('t6') and not done('t6') and all(done(t) for t in T15): return ['t6']
    return []


def s3_wait():
    """t1~t6 이 모두 끝났고 S3 이 아직 안 끝났는가(코드가 있는지는 따로 본다)."""
    return all(done(t) for t in TRACKS) and not done('s3')


def s3_ready():
    return s3_wait() and os.path.exists(os.path.join(C.SA, 'sa_s3.py'))


def py_env():
    e = dict(os.environ); e['PYTHONPATH'] = C.SA + (os.pathsep + e['PYTHONPATH'] if e.get('PYTHONPATH') else '')
    return e


def n_parts(t):
    """줄기의 조각 수 = python tN/run.py --nparts 의 마지막 줄. 못 읽으면 1."""
    try:
        r = subprocess.run([sys.executable, os.path.join(C.SA, t, 'run.py'), '--nparts'], capture_output=True, text=True, timeout=300, env=py_env(), cwd=C.REPO)
        n = int([x for x in r.stdout.strip().split('\n') if x.strip()][-1].strip())
        return max(1, n)
    except Exception as e:
        print(f'{t}: 조각 수를 못 읽어 1로 둠({type(e).__name__})', file=sys.stderr)
        return 1


def cmd_plan(a):
    if a.phase == 3:
        if s3_wait() and not s3_ready(): print('S3 차례지만 sa_s3.py 가 없어 건너뜀', file=sys.stderr)
        print('yes' if s3_ready() else 'no'); return 0
    inc = []
    for t in ready(a.phase):
        n = n_parts(t); inc += [{'track': t, 'part': i, 'n': n} for i in range(1, n + 1)]
    print(json.dumps({'include': inc}, ensure_ascii=False))
    return 0


# ------------------------------------------------------------------ 상태 파일
def tail_of(path, n=30):
    """파일의 끝 n 줄(너무 긴 줄은 자른다). 없으면 빈 글."""
    try:
        txt = open(path, 'rb').read().decode('utf-8', errors='replace')
    except Exception:
        return ''
    return '\n'.join(x[:400] for x in txt.rstrip('\n').split('\n')[-n:])


def get_fails(S):
    """실패 기록 전부. fails 칸이 있으면 그것만 본다(비어 있어도). 없으면 옛 꼴(fail 하나)을 읽는다."""
    if isinstance(S.get('fails'), list): return list(S['fails'])
    return [S['fail']] if isinstance(S.get('fail'), dict) else []


def fail_name(f):
    t = f.get('track')
    return '시험대' if t == 'harness' else f"파이프라인 작업({f.get('part')})" if t == 'pipeline' else 'S3' if t == 's3' else f"{t} {part_name(f.get('part'))}"


def part_name(p):
    return WHERE.get(str(p), f'조각 {p}')


def refresh(S):
    """status.json 을 실제 파일 상태로 맞춘다: tracks(코드 없음 | 준비 | 끝 | 실패) · stage · need_claude · why."""
    fails = [f for f in get_fails(S) if not ((f.get('track') in TRACKS + ['s3'] and done(f['track'])) or (f.get('track') == 'harness' and S.get('harness') == 'ok'))]
    S['fails'] = fails; S['fail'] = fails[0] if fails else None
    bad = {f.get('track') for f in fails}
    for f in glob.glob(os.path.join(NOTIFY, 'kakao_fail_*.txt')):      # 풀린 실패의 카카오 글은 지운다(뒤늦게 보내지 않게)
        if os.path.basename(f)[len('kakao_fail_'):-len('.txt')] not in bad: os.remove(f)
    S['tracks'] = {t: ('끝' if done(t) else '코드 없음' if not has_code(t) else '실패' if t in bad else '준비') for t in TRACKS}
    if S.get('stage') != '끝':                                      # '끝' 은 총괄만 쓴다 — 건드리지 않음
        if done('s3'): S['stage'] = 'S3 끝'
        elif S.get('harness') == 'ok': S['stage'] = 'S2'
        elif S.get('harness') == '실패' or not S.get('stage'): S['stage'] = 'S1'
    nocode = [t for t in TRACKS if S['tracks'][t] == '코드 없음']
    why = []
    if fails:
        why.append('실패(수리 대기): ' + ', '.join(fail_name(f) for f in fails))
    if nocode: why.append('코드 없는 줄기: ' + '·'.join(nocode))
    if not os.path.exists(os.path.join(C.SA, 'test_harness.py')): why.append('시험대(test_harness.py) 없음')
    if s3_wait() and not s3_ready(): why.append('S3 코드(sa_s3.py) 없음')
    if S.get('stage') == 'S3 끝': why.append('S3 끝 — 최종 심사·보고서 결론 차례')
    if S.get('stuck'): why.append(S['stuck'])
    S['need_claude'] = bool(why)
    if not why:
        if S.get('stage') == '끝': why = ['끝']
        else:
            left = ready(1) + ready(2) + (['t6(t1~t5 뒤)'] if has_code('t6') and not done('t6') and not ready(2) else []) + (['S3'] if not done('s3') else [])
            why = ['Claude 할 일 없음 — GitHub 진행 중(남은 일: ' + '·'.join(left) + ')']
    S['why'] = ' / '.join(why)
    return S


def add_fail(S, track, part, tail, parts=None, notify=True):
    """실패 하나를 적는다(같은 줄기의 옛 기록은 바꿔 씀). notify = 카카오 글 "[Signal A] <줄기> 계산 3번 실패 — 수리 대기" 도 만든다."""
    rec = {'track': track, 'part': part, 'tail': tail, 'at': now()}
    if parts and len(parts) > 1: rec['parts'] = parts
    S['fails'] = [f for f in get_fails(S) if f.get('track') != track] + [rec]
    if track == 'harness': S['harness'] = '실패'
    if notify:
        os.makedirs(NOTIFY, exist_ok=True)
        head = '시험대 확인 실패' if track == 'harness' else f'{track.upper()} 계산 3번 실패'
        where = '' if track in ('harness', 's3') else part_name(part) + ' · '
        open(os.path.join(NOTIFY, f'kakao_fail_{track}.txt'), 'w', encoding='utf-8').write(f'[Signal A] {head} — 수리 대기 ({where}{now("%m-%d %H:%M")})\n')
    return refresh(S)


def clear_fail(S, track):
    S['fails'] = [f for f in get_fails(S) if f.get('track') != track]
    return refresh(S)


def cmd_fail(a):
    part = int(a.part) if str(a.part).isdigit() else a.part; tail = tail_of(a.log)
    if a.out:                                                       # 계산 작업: 기록 파일만 쓴다(artifact 로 올려 판정 작업이 읽음)
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        json.dump({'track': a.track, 'part': part, 'tail': tail, 'at': now()}, open(a.out, 'w', encoding='utf-8'), ensure_ascii=False)
        print(f'실패 기록 → {a.out}'); return 0
    C.write_status(add_fail(C.read_status(), a.track, part, tail))
    print(f"실패 기록: {fail_name({'track': a.track, 'part': part})} → status.json need_claude=true"); return 0


def cmd_status(a):
    S = C.read_status()
    if a.harness == 'success': S['harness'] = 'ok'                  # 준비 작업(시험대 확인 포함)이 성공으로 끝났을 때만
    if a.jobs:
        # 작업(job) 자체가 실패한 경우(코드 오류·push 실패 등): 계산 실패 기록이 없어도 need_claude 가 켜지게 적는다.
        # 계산 작업(calc)의 실패·시간 초과는 판정 작업이 줄기 실패로 이미 적으므로 여기서는 보지 않는다.
        res = dict(x.split('=', 1) for x in a.jobs.split(',') if '=' in x)
        S['fails'] = [f for f in get_fails(S) if f.get('track') != 'pipeline']
        badj = [j for j in ('plan', 'judge1', 'judge2', 's3') if res.get(j) == 'failure' and not (j == 'plan' and any(f.get('track') == 'harness' for f in S['fails']))]
        if badj:
            S = add_fail(S, 'pipeline', '·'.join(badj), 'GitHub 작업 자체가 실패함(줄기 계산 실패 기록과 다름) — Actions 실행 기록에서 그 작업의 로그를 볼 것. '
                         '조각 결과는 artifact 에 14일 남으므로 "실패한 작업만 다시 실행"으로 이어 갈 수 있음', notify=False)
    S = refresh(S)
    try: rnd = int(a.round)
    except Exception: rnd = 0
    left = ready(1) + ready(2) + (['S3'] if s3_ready() else [])
    go = bool(left) and not S['fails'] and a.new_done > 0 and rnd + 1 < MAX_ROUND
    # 멈춤 표시: 준비된 일이 남았는데 이 실행이 다시 시작하지 않으면(또는 다시 시작이 실패하면 --stuck) 아무도 띄우지 않는다
    # → need_claude 를 켜서 다음 총괄 회차가 run.txt 로 띄우게 한다. 다음 실행의 판정·맨 끝 작업이 이 표시를 다시 맞춘다.
    if a.jobs: S['stuck'] = None
    if a.stuck or (a.jobs and left and not go and not S['fails']):
        S['stuck'] = f"준비된 일({'·'.join(left) or '?'})이 남았는데 GitHub 가 스스로 다시 시작하지 못함 — run.txt 를 고쳐 push 해 띄울 것"
    S = refresh(S); C.write_status(S)
    print(f"상태: stage={S.get('stage')} tracks={S['tracks']} need_claude={S['need_claude']} why={S['why']}")
    print(f'다시 시작 판단: 남은 준비된 일 {left or "없음"} · 실패 {len(S["fails"])}건 · 이번에 새로 끝난 것 {a.new_done} · round {rnd}')
    gh_out(restart='yes' if go else 'no', next_round=rnd + 1)
    return 0


# ------------------------------------------------------------------ 합치기 → 판정
def run_tries(cmd, log, check=None):
    """명령을 3번까지 시도. 출력은 화면과 log 파일(마지막 시도) 둘 다에. check() 가 있으면 끝난 뒤 그것도 참이어야 성공."""
    for k in range(1, TRIES + 1):
        print(f"::group::{' '.join(os.path.relpath(x, C.REPO) if os.path.isabs(x) else x for x in cmd[1:])} — 시도 {k}/{TRIES}", flush=True)
        with open(log, 'w', encoding='utf-8') as f:
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors='replace', env=py_env(), cwd=C.REPO)
            for ln in p.stdout: sys.stdout.write(ln); f.write(ln)
            rc = p.wait()
            if rc == 0 and check and not check():
                rc = 1; f.write('명령은 끝났지만 결과 파일(done.json)이 없음\n')
        print('::endgroup::', flush=True)
        if rc == 0: return True
        print(f'시도 {k} 실패(종료 코드 {rc})', flush=True)
        if k < TRIES: time.sleep(WAIT)
    return False


def place_parts(t, n, art):
    """artifact 폴더의 조각을 tN/out/parts/ 에 놓는다. 반환 = 실패했거나 없는 조각 [(번호, 오류 끝 30줄)]."""
    dst = os.path.join(C.SA, t, 'out', 'parts'); os.makedirs(dst, exist_ok=True); bad = []
    for i in range(1, n + 1):
        fr = glob.glob(os.path.join(art, f'sa-fail-{t}-{i}', '**', '*.json'), recursive=True)
        fs = glob.glob(os.path.join(art, f'sa-{t}-{i}', '**', '*.pkl'), recursive=True)
        for f in fs: shutil.copy2(f, dst)
        if fr:
            try: tl = json.load(open(fr[0], encoding='utf-8')).get('tail', '')
            except Exception: tl = '실패 기록을 읽지 못함'
            bad.append((i, tl))
        elif not fs:
            bad.append((i, f'조각 {i}/{n} 결과가 없음(계산 작업이 시간 초과·취소되었거나 올리기에 실패)'))
    return bad


def cmd_judge(a):
    inc = (json.loads(a.matrix) if (a.matrix or '').strip() else {}).get('include') or []
    plan = {}
    for x in inc: plan[x['track']] = int(x['n'])
    S = C.read_status(); S['harness'] = 'ok'; S['stuck'] = None     # 판정 작업은 준비 작업(시험대 확인)이 성공했을 때만 돈다. 실행이 돌고 있으니 멈춤 표시도 지움
    C.write_status(refresh(S))
    logd = os.path.join(os.environ.get('RUNNER_TEMP') or tempfile.gettempdir(), 'sa_log'); os.makedirs(logd, exist_ok=True)
    py = sys.executable; new = 0
    for t in sorted(plan):
        n = plan[t]; bad = place_parts(t, n, a.art); log = os.path.join(logd, f'{t}.log')
        if bad:
            print(f'{t}: 조각 {[i for i, _ in bad]} 실패 — 판정하지 않고 실패로 둠', flush=True)
            C.write_status(add_fail(C.read_status(), t, bad[0][0], bad[0][1], [i for i, _ in bad])); continue
        if not run_tries([py, os.path.join(C.SA, t, 'run.py'), '--merge'], log):
            C.write_status(add_fail(C.read_status(), t, 'merge', tail_of(log))); continue
        if not run_tries([py, os.path.join(C.SA, 'sa_judge.py'), '--track', t], log, check=lambda: done(t)):
            C.write_status(add_fail(C.read_status(), t, 'judge', tail_of(log))); continue
        C.write_status(clear_fail(C.read_status(), t)); new += 1
        print(f'{t}: 합치기·판정 끝', flush=True)
    C.write_status(refresh(C.read_status()))
    gh_out(done=new)
    return 0


# ------------------------------------------------------------------ 카카오 글 모으기
def _sent():
    p = os.path.join(NOTIFY, 'sent.json')
    try: J = json.load(open(p, encoding='utf-8'))
    except Exception: J = {}
    J.setdefault('sent', {}); J.setdefault('pending', {})
    return p, J


def cmd_kakao(a):
    """줄기 판정이 만든 notify/kakao_<줄기>.txt, S3 의 kakao_s3.txt, 실패 글 kakao_fail_*.txt 가운데 아직 안 보낸 것(글이 바뀐 것 포함)만 모은다."""
    os.makedirs(NOTIFY, exist_ok=True); p, J = _sent()
    if a.mark:                                                      # 보낸 뒤: kakao_lab.py 의 기록(last.json)이 '보냄'일 때만 보낸 것으로 적는다
        try: L = json.load(open(os.path.join(NOTIFY, 'last.json'), encoding='utf-8'))
        except Exception: L = {}
        ok = L.get('status') == 'sent' and str(L.get('at', ''))[:16] >= str(J.get('pending_at', '9'))
        if ok: J['sent'].update(J['pending']); J['pending'] = {}
        json.dump(J, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print('카카오톡:', '보냄으로 적음' if ok else f"아직 안 보냄({L.get('status', '기록 없음')} {L.get('reason', '')}) — 다음 차례에 다시 보냄")
        return 0
    msgs = []; pend = {}
    for f in sorted(glob.glob(os.path.join(NOTIFY, 'kakao_*.txt'))):
        txt = open(f, encoding='utf-8').read().strip(); name = os.path.basename(f); h = hashlib.sha256(txt.encode()).hexdigest()[:16]
        if txt and J['sent'].get(name) != h: msgs.append(txt[:200]); pend[name] = h
    open(os.path.join(NOTIFY, 'kakao.txt'), 'w', encoding='utf-8').write('\n=====\n'.join(msgs) + ('\n' if msgs else ''))
    J['pending'] = pend; J['pending_at'] = now()
    json.dump(J, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'보낼 카카오 글 {len(msgs)}통: {list(pend)}')
    gh_out(send='yes' if msgs else 'no')
    return 0


# ------------------------------------------------------------------ log.md 한 줄
def cmd_log(a):
    lp = os.path.join(C.SA, 'log.md'); lines = open(lp, encoding='utf-8').read().rstrip('\n').split('\n')
    nums = [int(x.split('|')[1]) for x in lines if x.startswith('|') and x.split('|')[1].strip().isdigit()]
    try: total = json.load(open(os.path.join(C.STATE, 'ledger.json'), encoding='utf-8')).get('total', 0)
    except Exception: total = 0
    cell = lambda s: (str(s).replace('|', '/').replace('\n', ' ').strip() or '—')
    lines.append(f"| {max(nums) + 1 if nums else 1} | {now('%Y-%m-%d')} | {cell(a.stage)}(GitHub) | {cell(a.text)} | {cell(a.nums)} | {cell(a.verdict)} | — (누적 {total:,}) |")
    open(lp, 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
    print(lines[-1]); return 0


# ------------------------------------------------------------------ 저장(커밋·push)
def cmd_save(a):
    """deriv/signal_a 만 올린다. 조각 폴더(tN/out/parts)·내려받은 자료(_data)는 뺀다. 바뀐 것이 없으면 아무것도 안 한다."""
    def git(*x, quiet=False):
        r = subprocess.run(['git', '-C', C.REPO, *x], capture_output=True, text=True)
        if r.returncode and not quiet: print(f"git {' '.join(x[:3])} … 실패: {(r.stderr or r.stdout).strip()[-400:]}", flush=True)
        return r.returncode
    git('config', 'user.name', 'dashboard-bot'); git('config', 'user.email', 'dashboard-bot@users.noreply.github.com')
    # log.md 는 총괄과 파이프라인이 둘 다 끝에 한 줄씩 붙인다 → 겹치면 양쪽 줄을 다 남긴다(이 실행기 안에서만 쓰는 설정, 저장소 파일 아님)
    ga = subprocess.run(['git', '-C', C.REPO, 'rev-parse', '--git-path', 'info/attributes'], capture_output=True, text=True).stdout.strip()
    if ga:
        ga = ga if os.path.isabs(ga) else os.path.join(C.REPO, ga); os.makedirs(os.path.dirname(ga), exist_ok=True)
        if 'log.md merge=union' not in (open(ga, encoding='utf-8').read() if os.path.exists(ga) else ''):
            open(ga, 'a', encoding='utf-8').write('deriv/signal_a/log.md merge=union\n')
    git('add', 'deriv/signal_a')
    git('reset', '-q', '--', 'deriv/signal_a/*/out/parts/*', 'deriv/signal_a/_data/*', quiet=True)
    if git('diff', '--cached', '--quiet', quiet=True) == 0:
        print('저장: 바뀐 것 없음'); return 0
    if git('commit', '-q', '-m', f'Signal A 파이프라인: {a.msg} {now()}'): return 1
    for i in range(4):
        # 3번째부터: 같은 파일을 다른 쪽(총괄)이 함께 고쳐 겹치면 그 겹친 곳만 파이프라인 쪽 내용으로 둔다(status.json 은 맨 끝 작업이 파일 상태로 다시 맞춤)
        ours = ['-X', 'theirs'] if i >= 2 else []
        if git('pull', '-q', '--rebase', '--autostash', *ours, 'origin', 'deriv-research') == 0 and git('push', '-q', 'origin', 'HEAD:deriv-research') == 0:
            print(f'저장: push 끝({a.msg})' + (' — 겹친 곳은 파이프라인 쪽 내용으로 둠' if ours else '')); return 0
        git('rebase', '--abort', quiet=True)                        # 겹쳐서 멈춘 상태를 풀고 다시
        if i < 3: time.sleep(int(os.environ.get('SA_PUSH_WAIT', '15')))
    print('::error::저장 실패 — 4번 시도했지만 push 하지 못함(같은 파일을 다른 쪽이 함께 고쳤을 수 있음)')
    return 1


def main():
    ap = argparse.ArgumentParser(description='Signal A 파이프라인 도우미'); sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('plan'); p.add_argument('--phase', type=int, choices=[1, 2, 3], required=True); p.set_defaults(f=cmd_plan)
    p = sub.add_parser('fail'); p.add_argument('--track', required=True); p.add_argument('--part', default='0'); p.add_argument('--log', default=''); p.add_argument('--out', default=''); p.set_defaults(f=cmd_fail)
    p = sub.add_parser('judge'); p.add_argument('--matrix', default=''); p.add_argument('--art', required=True); p.set_defaults(f=cmd_judge)
    p = sub.add_parser('status'); p.add_argument('--new-done', type=int, default=0); p.add_argument('--round', default='0'); p.add_argument('--harness', default=''); p.add_argument('--jobs', default=''); p.add_argument('--stuck', action='store_true'); p.set_defaults(f=cmd_status)
    p = sub.add_parser('kakao'); p.add_argument('--mark', action='store_true'); p.set_defaults(f=cmd_kakao)
    p = sub.add_parser('log'); p.add_argument('--stage', required=True); p.add_argument('--text', required=True); p.add_argument('--nums', default='—'); p.add_argument('--verdict', default='—'); p.set_defaults(f=cmd_log)
    p = sub.add_parser('save'); p.add_argument('--msg', required=True); p.set_defaults(f=cmd_save)
    a = ap.parse_args()
    return a.f(a)


if __name__ == '__main__':
    sys.exit(main())
