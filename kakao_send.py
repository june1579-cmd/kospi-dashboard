# -*- coding: utf-8 -*-
"""kakao_send.py — report/kakao.txt 의 메시지(===== 로 구분, 각 200자 이내)를 카카오톡 '나에게 보내기'로 보낸다.
   환경변수: KAKAO_REST_KEY, KAKAO_REFRESH_TOKEN (GitHub Secrets), 선택 KAKAO_CLIENT_SECRET, DASH_LINK(버튼 링크)
   갱신 토큰 보관: 카카오가 새 refresh 토큰을 주면 state/kakao_token.json 에 REST 키로 만든 키로 암호화해 저장하고 다음 실행부터 그것을 쓴다(비밀값 수정 권한 없이도 연장).
   글 두 통: ① 매수·매도 신호 발생/미발생 ② 결론. 그래프·버튼은 보내지 않는다.
   사용: python kakao_send.py --file report/kakao.txt [--alerts report/alerts.json] [--link https://...]
"""
import argparse, base64, hashlib, json, os, sys
import requests

STATE = 'state/kakao_token.json'

def fernet(key_src):
    try:
        from cryptography.fernet import Fernet
    except Exception: return None
    return Fernet(base64.urlsafe_b64encode(hashlib.pbkdf2_hmac('sha256', key_src.encode(), b'kospi-dashboard-kakao', 200000, 32)))

def load_refresh(rest_key):
    env = os.environ.get('KAKAO_REFRESH_TOKEN', '').strip()
    if os.path.exists(STATE):
        try:
            js = json.load(open(STATE, encoding='utf-8')); f = fernet(rest_key)
            if f and js.get('seed') == hashlib.sha256(env.encode()).hexdigest()[:16]:   # 비밀값이 바뀌었으면(재발급) 파일보다 비밀값 우선
                return f.decrypt(js['token'].encode()).decode()
        except Exception as e: print('state 토큰 읽기 실패(비밀값 사용):', repr(e))
    return env

def save_refresh(rest_key, token, env_token):
    f = fernet(rest_key)
    if not f: return
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    json.dump({'token': f.encrypt(token.encode()).decode(), 'seed': hashlib.sha256(env_token.encode()).hexdigest()[:16]}, open(STATE, 'w', encoding='utf-8'))

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--file', default='report/kakao.txt'); ap.add_argument('--alerts', default='report/alerts.json'); ap.add_argument('--link', default=os.environ.get('DASH_LINK', 'https://june1579-cmd.github.io/kospi-dashboard/'))
    a = ap.parse_args()
    key = os.environ.get('KAKAO_REST_KEY', '').strip(); secret = os.environ.get('KAKAO_CLIENT_SECRET', '').strip()
    if not key: print('KAKAO_REST_KEY 없음 — 카카오톡 발송 건너뜀'); return 0
    refresh = load_refresh(key)
    if not refresh: print('KAKAO_REFRESH_TOKEN 없음 — kakao_auth.py 를 한 번 실행해 비밀값을 넣어 주세요'); return 0
    data = {'grant_type': 'refresh_token', 'client_id': key, 'refresh_token': refresh}
    if secret: data['client_secret'] = secret
    r = requests.post('https://kauth.kakao.com/oauth/token', data=data, timeout=30); js = r.json()
    if 'access_token' not in js:
        print('토큰 갱신 실패(두 달 넘게 안 썼으면 kakao_auth.py 재실행):', js); return 2
    if js.get('refresh_token'): save_refresh(key, js['refresh_token'], os.environ.get('KAKAO_REFRESH_TOKEN', '')); print('refresh 토큰 연장 → state/ 저장')
    msgs = [m.strip() for m in open(a.file, encoding='utf-8').read().split('=====') if m.strip()]
    sent = 0; H = {'Authorization': 'Bearer ' + js['access_token']}
    # 그래프·대시보드 버튼 없이 글만(매수·매도 신호 발생/미발생 + 결론)
    for m in msgs:
        tpl = {'object_type': 'text', 'text': m[:200], 'link': {'web_url': a.link, 'mobile_web_url': a.link}}   # link 는 템플릿 필수 항목(버튼 없음)
        t = requests.post('https://kapi.kakao.com/v2/api/talk/memo/default/send', headers=H, data={'template_object': json.dumps(tpl, ensure_ascii=False)}, timeout=30)
        print('발송', t.status_code, t.text[:120]); sent += t.status_code == 200
    return 0 if sent == len(msgs) else 3

if __name__ == '__main__': sys.exit(main())
