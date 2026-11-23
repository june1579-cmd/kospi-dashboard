# -*- coding: utf-8 -*-
"""krx_lock.py — KRX 로그인 줄(2026-11-23). 같은 계정으로 두 작업이 동시에 로그인하지 않게 한 번에 하나만 들어간다.

방법: 이 가지(krx-lock)의 lock.json 을 고쳐 push 하는 데 성공한 작업만 들어간다(push 는 한 번에 하나만 성공하므로 겹치지 않는다).
  acquire : 줄이 비었거나 앞 작업의 유효 시간이 지났으면 내 이름을 적고 들어간다. 아니면 30초마다 다시 본다.
            KRX_LOCK_WAIT_MIN 분을 기다려도 안 비면 KRX_LOCK_ON_TIMEOUT 대로 — proceed(경고만 하고 진행) · skip(KRX_SKIP=1 을 남기고 정상 종료) · fail(종료 코드 3)
  release : 내가 잡은 줄이면 비운다(다른 작업이 잡은 줄은 건드리지 않는다).
줄이 고장 나도 본 작업을 막지 않도록, 잠금 저장소를 못 읽으면 경고만 하고 진행한다. GitHub 가 준 실행 토큰만 쓰며 비밀값은 다루지 않는다.
"""
import datetime as dt, json, os, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__)); LOCK = os.path.join(HERE, 'lock.json')
ME = f"{os.environ.get('GITHUB_RUN_ID', 'local')}-{os.environ.get('GITHUB_RUN_ATTEMPT', '1')}-{os.environ.get('GITHUB_JOB', 'job')}"
WHO = f"{os.environ.get('GITHUB_WORKFLOW', '?')} ({os.environ.get('GITHUB_REF_NAME', '?')})"
WAIT = float(os.environ.get('KRX_LOCK_WAIT_MIN', '30')); TTL = float(os.environ.get('KRX_LOCK_TTL_MIN', '60')); MODE = os.environ.get('KRX_LOCK_ON_TIMEOUT', 'proceed')
now = lambda: dt.datetime.now(dt.timezone.utc)


def git(*a):
    return subprocess.run(['git', '-C', HERE, *a], capture_output=True, text=True, timeout=120)


def sync():
    r = git('fetch', '-q', 'origin', 'krx-lock')
    if r.returncode != 0: raise RuntimeError('fetch 실패')
    git('reset', '-q', '--hard', 'origin/krx-lock')
    try: return json.load(open(LOCK, encoding='utf-8'))
    except Exception: return {}


def write(d, msg):
    json.dump(d, open(LOCK, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    git('-c', 'user.name=dashboard-bot', '-c', 'user.email=dashboard-bot@users.noreply.github.com', 'commit', '-q', '-am', msg)
    return git('push', '-q', 'origin', 'HEAD:krx-lock').returncode == 0


def held(d):
    if not d.get('holder'): return False
    try: return now() < dt.datetime.fromisoformat(d['until'])
    except Exception: return False


def acquire():
    t0 = time.time(); said = False
    while True:
        try: d = sync()
        except Exception as ex:
            print(f'KRX 줄: 잠금 저장소를 읽지 못함({ex}) — 줄 없이 진행'); return 0
        if d.get('holder') == ME or not held(d):
            if write({'holder': ME, 'who': WHO, 'at': now().isoformat(timespec='seconds'), 'until': (now() + dt.timedelta(minutes=TTL)).isoformat(timespec='seconds')}, f'잡음: {WHO}'):
                print(f'KRX 줄: 들어감({WHO}, 유효 {TTL:.0f}분, 기다린 시간 {(time.time() - t0) / 60:.1f}분)'); return 0
            time.sleep(3); continue                       # 다른 작업이 먼저 push — 다시 본다
        if not said: print(f"KRX 줄: {d.get('who')} 가 쓰는 중(~{d.get('until')}) — 기다림(최대 {WAIT:.0f}분)"); said = True
        if time.time() - t0 > WAIT * 60:
            print(f'KRX 줄: {WAIT:.0f}분을 기다려도 비지 않음 → {MODE}')
            if MODE == 'skip':
                env = os.environ.get('GITHUB_ENV')
                if env: open(env, 'a').write('KRX_SKIP=1\n')
                return 0
            return 3 if MODE == 'fail' else 0
        time.sleep(30)


def release():
    for _ in range(5):
        try: d = sync()
        except Exception: return 0
        if d.get('holder') != ME: return 0
        if write({'holder': '', 'last': WHO, 'released': now().isoformat(timespec='seconds')}, f'비움: {WHO}'):
            print('KRX 줄: 비움'); return 0
        time.sleep(2)
    return 0


if __name__ == '__main__':
    sys.exit(acquire() if (sys.argv[1:] or ['acquire'])[0] == 'acquire' else release())
