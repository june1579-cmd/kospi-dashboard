# -*- coding: utf-8 -*-
"""kakao_lab.py — 콜 우위 연구소 보고를 카카오톡 '나에게 보내기'로 보낸다(글만, ===== 로 나눈 한 통마다 200자 이내).

대시보드와 같은 비밀값(KAKAO_REST_KEY·KAKAO_REFRESH_TOKEN·KAKAO_CLIENT_SECRET)을 쓰지만 토큰은 '읽기만' 한다.
  - 카카오는 refresh 토큰이 1개월 미만 남았을 때 갱신 요청을 받으면 새 토큰을 주고 옛 토큰을 폐기한다.
    그 연장은 대시보드(main)만 하도록, 연구소는 연장이 일어날 수 없는 기간(발급·연장 뒤 28일 안)에만 보낸다.
  - 발급·연장 시각 = main 의 state/kakao_token.json 마지막 커밋 시각(대시보드가 연장하면 그 파일을 커밋한다).
    그 파일이 아직 없으면 kakao_auth.py 가 저장소에 들어온 시각(2026-11-01 17:01 KST)을 가장 이른 발급 시각으로 본다.
  - 기간 밖이면 보내지 않고 '보류'로 기록한다(총괄이 휴대폰 알림으로 대신 보냄). 대시보드가 연장을 커밋하면 다시 보낸다.
  - main 은 읽기만 하고 절대 쓰지 않는다. 토큰 값은 화면에 찍지 않는다.
결과: deriv/lab/notify/last.json {status: sent|deferred|failed|skipped, at, sent, total, reason}
사용: python deriv/lab/kakao_lab.py --file deriv/lab/notify/kakao.txt --main-state <main 토큰 파일 사본> --link https://...
"""
import argparse
import base64
import datetime as dt
import hashlib
import json
import os
import sys

import requests

LAB = os.path.dirname(os.path.abspath(__file__))
LAST = os.environ.get('KAKAO_LAST') or os.path.join(LAB, 'notify', 'last.json')   # 다른 갈래(통합 예측 연구소)는 자기 기록 파일을 따로 쓴다(2026-11-23)
RENEWED = os.path.join(LAB, 'state', 'kakao_renewed.json')
KST = dt.timezone(dt.timedelta(hours=9))
FIRST_ISSUE = dt.datetime(2026, 11, 1, 8, 1, 40, tzinfo=dt.timezone.utc)   # kakao_auth.py 가 main 에 들어온 시각
SAFE_DAYS = 28                                                              # 연장은 30일 지난 뒤부터 → 28일까지만(여유 2일)


def fernet(key_src):
    from cryptography.fernet import Fernet
    return Fernet(base64.urlsafe_b64encode(hashlib.pbkdf2_hmac('sha256', key_src.encode(), b'kospi-dashboard-kakao', 200000, 32)))


def record(status, **kw):
    os.makedirs(os.path.dirname(LAST), exist_ok=True)
    js = {'status': status, 'at': dt.datetime.now(KST).strftime('%Y-%m-%d %H:%M KST'), **kw}
    json.dump(js, open(LAST, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('기록:', json.dumps(js, ensure_ascii=False))


def issued_at():
    s = (os.environ.get('TOKEN_RENEWED_AT') or '').strip()
    if s and s != 'null':
        try:
            return max(FIRST_ISSUE, dt.datetime.fromisoformat(s.replace('Z', '+00:00')))
        except Exception:
            pass
    return FIRST_ISSUE


def load_refresh(rest_key, env_token, main_state):
    if main_state and os.path.exists(main_state):
        try:
            js = json.load(open(main_state, encoding='utf-8'))
            if js.get('seed') == hashlib.sha256(env_token.encode()).hexdigest()[:16]:
                return fernet(rest_key).decrypt(js['token'].encode()).decode(), 'main 연장 토큰'
        except Exception as e:
            print('main 토큰 파일 읽기 실패(비밀값 사용):', type(e).__name__)
    return env_token, '비밀값'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--file', default=os.path.join(LAB, 'notify', 'kakao.txt'))
    ap.add_argument('--main-state', default='')
    ap.add_argument('--link', default='https://claude.ai/artifact/PtZRViSn6y88UTNmYVsspR')
    a = ap.parse_args()
    msgs = [m.strip() for m in open(a.file, encoding='utf-8').read().split('=====') if m.strip()]
    if not msgs:
        record('skipped', sent=0, total=0, reason='보낼 글 없음'); return 0
    key = os.environ.get('KAKAO_REST_KEY', '').strip(); env_rt = os.environ.get('KAKAO_REFRESH_TOKEN', '').strip()
    secret = os.environ.get('KAKAO_CLIENT_SECRET', '').strip()
    if not key or not env_rt:
        record('skipped', sent=0, total=len(msgs), reason='카카오 비밀값 없음'); return 0
    t0 = issued_at(); now = dt.datetime.now(dt.timezone.utc); until = t0 + dt.timedelta(days=SAFE_DAYS)
    print(f'토큰 발급·연장 기준 {t0.astimezone(KST):%Y-%m-%d %H:%M} KST → 연구소 사용 가능 {until.astimezone(KST):%Y-%m-%d %H:%M} KST 까지')
    if now > until:
        record('deferred', sent=0, total=len(msgs), reason=f'대시보드 토큰 연장 기간({until.astimezone(KST):%m-%d %H:%M} 이후) — 대시보드가 연장을 커밋할 때까지 보류')
        return 0
    refresh, src = load_refresh(key, env_rt, a.main_state)
    data = {'grant_type': 'refresh_token', 'client_id': key, 'refresh_token': refresh}
    if secret: data['client_secret'] = secret
    js = requests.post('https://kauth.kakao.com/oauth/token', data=data, timeout=30).json()
    if 'access_token' not in js:
        record('failed', sent=0, total=len(msgs), reason=f"토큰 갱신 실패 {js.get('error', '')} {js.get('error_code', '')}".strip()); return 2
    print('access 토큰 받음(', src, ')')
    if js.get('refresh_token'):
        # 일어나면 안 되는 일(기간 계산이 틀림): 새 토큰을 잃지 않게 연구소 가지에 암호화해 두고 크게 알린다.
        os.makedirs(os.path.dirname(RENEWED), exist_ok=True)
        json.dump({'token': fernet(key).encrypt(js['refresh_token'].encode()).decode(),
                   'seed': hashlib.sha256(env_rt.encode()).hexdigest()[:16],
                   'at': dt.datetime.now(KST).strftime('%Y-%m-%d %H:%M KST')}, open(RENEWED, 'w', encoding='utf-8'))
        print('::error::카카오가 refresh 토큰을 연장함 — 새 토큰을 deriv/lab/state/kakao_renewed.json 에 보관. 대시보드 토큰 파일로 옮겨야 함')
        msgs = ['[긴급·연구소] 카카오 토큰이 예상보다 일찍 연장됐습니다. 새 토큰은 연구소 가지에 암호화해 두었습니다. 대시보드 카톡이 끊기면 Claude에게 "연장 토큰 옮겨"라고 말씀해 주세요.'] + msgs
    H = {'Authorization': 'Bearer ' + js['access_token']}
    sent = 0
    for m in msgs:
        tpl = {'object_type': 'text', 'text': m[:200], 'link': {'web_url': a.link, 'mobile_web_url': a.link}}
        r = requests.post('https://kapi.kakao.com/v2/api/talk/memo/default/send', headers=H,
                          data={'template_object': json.dumps(tpl, ensure_ascii=False)}, timeout=30)
        print('발송', r.status_code, r.text[:80]); sent += r.status_code == 200
    record('sent' if sent == len(msgs) else 'failed', sent=sent, total=len(msgs),
           reason='' if sent == len(msgs) else '일부 발송 실패', first=msgs[0][:60])
    return 0 if sent == len(msgs) else 3


if __name__ == '__main__':
    sys.exit(main())
