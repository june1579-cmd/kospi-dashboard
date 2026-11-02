# -*- coding: utf-8 -*-
"""kakao_send.py — report/kakao.txt 의 메시지(===== 로 구분, 각 200자 이내)를 카카오톡 '나에게 보내기'로 보낸다.
   환경변수: KAKAO_REST_KEY, KAKAO_REFRESH_TOKEN (GitHub Secrets), 선택 KAKAO_CLIENT_SECRET, DASH_LINK(버튼 링크)
   갱신 토큰 보관: 카카오가 새 refresh 토큰을 주면 state/kakao_token.json 에 REST 키로 만든 키로 암호화해 저장하고 다음 실행부터 그것을 쓴다(비밀값 수정 권한 없이도 연장).
   첫 통은 그래프(report/chart.png, 환경변수 CHART_URL 로 공개 주소)와 중요 변동(report/alerts.json), 다음 통부터 글 요약.
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
    ap = argparse.ArgumentParser(); ap.add_argument('--file', default='report/kakao.txt'); ap.add_argument('--alerts', default='report/alerts.json'); ap.add_argument('--link', default=os.environ.get('DASH_LINK', 'https://claude.ai/artifact/LREkdE8UfEYhuNn6Jpn67c'))
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
    # 첫 통: 그래프 + 중요 변동(피드 템플릿). 그래프 주소(CHART_URL)는 워크플로가 commit·push 한 뒤 raw.githubusercontent 주소로 넘긴다
    chart = os.environ.get('CHART_URL', '').strip()
    if chart and os.path.exists(a.alerts):
        al = json.load(open(a.alerts, encoding='utf-8')); A = al.get('alerts', [])
        d = al.get('date', ''); dd = f'{int(d[5:7])}/{int(d[8:10])}' if len(d) >= 10 else d
        desc = ('\n'.join('· ' + x for x in A[:5]) + (f'\n외 {len(A) - 5}건' if len(A) > 5 else '')) if A else '중요 변동 없음 — 아래 요약 참고'
        feed = {'object_type': 'feed', 'content': {'title': f"대시보드 {dd} {al.get('label', '')} · 중요 변동 {len(A)}건", 'description': desc[:230], 'image_url': chart, 'image_width': 800, 'image_height': 840,
                                                   'link': {'web_url': a.link, 'mobile_web_url': a.link}},
                'buttons': [{'title': '대시보드 열기', 'link': {'web_url': a.link, 'mobile_web_url': a.link}}]}
        t = requests.post('https://kapi.kakao.com/v2/api/talk/memo/default/send', headers=H, data={'template_object': json.dumps(feed, ensure_ascii=False)}, timeout=30)
        print('그래프 발송', t.status_code, t.text[:120]); msgs_ok = t.status_code == 200
        if not msgs_ok: print('그래프 발송 실패 — 글 요약만 보냄')
        # 둘째 통: 매매 신호 전부 그래프(report/signals.png)
        sig_url = os.environ.get('SIGNAL_URL', '').strip()
        if sig_url:
            on = al.get('signals_on_today') or []
            sdesc = ('오늘 켜진 신호: ' + ', '.join(on)) if on else '오늘 켜진 신호 없음'
            if al.get('vkospi_hold'): sdesc += f"\nVKOSPI {al.get('vkospi_date', '')}까지 → VKOSPI 신호 6개 판정 보류(다음 날 08:31 확정)"
            sdesc += '\n▲ 매수 시작 ▼ 매도·청산 시작 · 막대 = 켜진 기간'
            feed2 = {'object_type': 'feed', 'content': {'title': f'매매 신호 전부 {dd} · 켜짐 {len(on)}개', 'description': sdesc[:230], 'image_url': sig_url, 'image_width': 800, 'image_height': 840,
                                                        'link': {'web_url': a.link, 'mobile_web_url': a.link}},
                     'buttons': [{'title': '대시보드 열기', 'link': {'web_url': a.link, 'mobile_web_url': a.link}}]}
            t = requests.post('https://kapi.kakao.com/v2/api/talk/memo/default/send', headers=H, data={'template_object': json.dumps(feed2, ensure_ascii=False)}, timeout=30)
            print('신호 그래프 발송', t.status_code, t.text[:120])
    for m in msgs:
        tpl = {'object_type': 'text', 'text': m[:200], 'link': {'web_url': a.link, 'mobile_web_url': a.link}, 'button_title': '대시보드 열기'}
        t = requests.post('https://kapi.kakao.com/v2/api/talk/memo/default/send', headers=H, data={'template_object': json.dumps(tpl, ensure_ascii=False)}, timeout=30)
        print('발송', t.status_code, t.text[:120]); sent += t.status_code == 200
    return 0 if sent == len(msgs) else 3

if __name__ == '__main__': sys.exit(main())
