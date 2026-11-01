# -*- coding: utf-8 -*-
"""kakao_auth.py — 카카오톡 '나에게 보내기'용 토큰을 한 번만 발급받는다 (PC에서 실행).

준비(developers.kakao.com, 한 번만):
  1) 내 애플리케이션 > 애플리케이션 추가 → 앱 이름 아무거나(예: 대시보드 알림)
  2) 앱 설정 > 앱 키 > 'REST API 키' 복사
  3) 제품 설정 > 카카오 로그인 > 활성화 ON, Redirect URI 에  https://localhost:3000  추가
  4) 제품 설정 > 카카오 로그인 > 동의항목 > '카카오톡 메시지 전송(talk_message)' 를 '이용 중 동의' 로 설정
     (내 애플리케이션 > 앱 설정 > 플랫폼 은 안 넣어도 됨. '카카오 로그인 보안 > Client Secret' 은 켜지 말 것 — 켰다면 KAKAO_CLIENT_SECRET 도 GitHub 비밀로 넣는다)
실행:  python kakao_auth.py
  → 브라우저가 열리면 카카오 로그인·동의 → 'localhost 연결 거부' 화면이 떠도 정상. 그 주소창의 전체 주소(https://localhost:3000/?code=...)를 복사해 붙여넣는다
  → 화면에 KAKAO_REST_KEY / KAKAO_REFRESH_TOKEN 두 줄이 나온다 → GitHub 저장소 Settings > Secrets and variables > Actions 에 같은 이름으로 넣는다.
  refresh 토큰은 2개월짜리지만 날마다 쓰면 자동으로 연장(갱신 토큰을 저장소 state/ 에 암호화해 둠). 두 달 넘게 멈췄다가 다시 쓰면 이 파일을 한 번 더 실행.
"""
import sys, json, webbrowser, urllib.parse
import requests

REDIRECT = 'https://localhost:3000'

def main():
    key = input('REST API 키: ').strip()
    secret = input('Client Secret (안 켰으면 그냥 Enter): ').strip()
    url = 'https://kauth.kakao.com/oauth/authorize?' + urllib.parse.urlencode({'client_id': key, 'redirect_uri': REDIRECT, 'response_type': 'code', 'scope': 'talk_message'})
    print('\n브라우저에서 열리는 주소:\n ', url, '\n')
    try: webbrowser.open(url)
    except Exception: pass
    back = input('로그인·동의 뒤 주소창의 전체 주소를 붙여넣기: ').strip()
    code = urllib.parse.parse_qs(urllib.parse.urlparse(back).query).get('code', [''])[0] or back
    data = {'grant_type': 'authorization_code', 'client_id': key, 'redirect_uri': REDIRECT, 'code': code}
    if secret: data['client_secret'] = secret
    r = requests.post('https://kauth.kakao.com/oauth/token', data=data, timeout=30); js = r.json()
    if 'refresh_token' not in js: print('실패:', js); sys.exit(1)
    # 시험 발송
    t = requests.post('https://kapi.kakao.com/v2/api/talk/memo/default/send', headers={'Authorization': 'Bearer ' + js['access_token']},
                      data={'template_object': json.dumps({'object_type': 'text', 'text': '대시보드 알림 연결 확인 ✔', 'link': {'web_url': 'https://claude.ai', 'mobile_web_url': 'https://claude.ai'}}, ensure_ascii=False)}, timeout=30)
    print('\n시험 발송:', '성공(카카오톡 "나와의 채팅" 확인)' if t.status_code == 200 else f'실패 {t.status_code} {t.text[:200]}')
    print('\n==== GitHub 저장소 Settings > Secrets and variables > Actions > New repository secret 에 넣을 값 ====')
    print('KAKAO_REST_KEY      =', key)
    print('KAKAO_REFRESH_TOKEN =', js['refresh_token'])
    if secret: print('KAKAO_CLIENT_SECRET =', secret)
    print(f"(refresh 토큰 유효 {js.get('refresh_token_expires_in', 0)//86400}일 — 날마다 쓰면 자동 연장)")

if __name__ == '__main__': main()
