# -*- coding: utf-8 -*-
"""자료 출처 시험 2차 — KRX 화면 구조(로그인 세션) · 차트로그 야간선물 쪽 · 네이버 선물 목록. 비밀값은 출력하지 않는다."""
import datetime as dt, json, os, re, sys, time, traceback
import requests
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36'
SECRETS = [v for k, v in os.environ.items() if k in ('KRX_API_KEY', 'KRX_ID', 'KRX_PW') and v]
os.makedirs('out', exist_ok=True)
def red(s):
    s = str(s)
    for v in SECRETS:
        if v and len(v) >= 4: s = s.replace(v, '***')
    return s
def w(name, text): open(os.path.join('out', name), 'w', encoding='utf-8').write(red(text))
LOG = []
def log(*a):
    m = ' '.join(str(x) for x in a); LOG.append(m); print(red(m), flush=True)
def safe(fn, name):
    try: return fn()
    except Exception: w(name + '.err.txt', traceback.format_exc())

def krx_sess():
    from pykrx.website.comm.webio import get_session
    ks = get_session()
    if ks is None: return requests.Session(), {'User-Agent': UA}
    h = ks.get_headers(); h['User-Agent'] = h.get('User-Agent') or UA
    return ks.session, h

def forms(t):
    out = []
    out.append('  name=: ' + str(sorted(set(re.findall(r'name="([A-Za-z0-9_]+)"', t))))[:1500])
    out.append('  bld: ' + str(sorted(set(re.findall(r'dbms/[A-Za-z0-9_/]+', t))))[:1500])
    for m in re.finditer(r'<select[^>]*name="([^"]+)"[^>]*>(.*?)</select>', t, flags=re.S):
        opts = re.findall(r'<option[^>]*value="([^"]*)"[^>]*>([^<]*)', m.group(2)); out.append(f'  select {m.group(1)}: {opts[:30]}')
    for m in re.finditer(r'<input[^>]*type="(?:radio|checkbox)"[^>]*>', t):
        tag = m.group(0); nm = re.findall(r'name="([^"]+)"', tag); val = re.findall(r'value="([^"]*)"', tag)
        lab = re.sub(r'\s+', ' ', t[m.end():m.end() + 120]); out.append(f'  radio {nm} {val} …{lab[:80]}')
    for kw in ('야간', 'mktTpCd', '주간', 'trdTm', 'sess'):
        for mm in list(re.finditer(kw, t))[:6]: out.append(f'  [{kw}] …' + re.sub(r'\s+', ' ', t[max(0, mm.start() - 200):mm.start() + 320]) + '…')
    return out

def k_screens():
    s, h = krx_sess(); out = []
    urls = ['https://data.krx.co.kr/contents/MDC/MDI/mdiLoader/index.cmd?menuId=MDC0201050101', 'https://data.krx.co.kr/contents/MDC/MDI/outerLoader/index.cmd?screenId=MDCSTAT125&locale=ko_KR',
            'https://data.krx.co.kr/contents/MDC/MDI/outerLoader/index.cmd?screenId=MDCSTAT12501&locale=ko_KR', 'https://data.krx.co.kr/contents/MDC/STAT/standard/MDCSTAT12501.cmd',
            'https://data.krx.co.kr/contents/MDC/STAT/standard/MDCSTAT125.cmd', 'https://data.krx.co.kr/contents/MDC/MDI/outerLoader/index.cmd?screenId=MDCSTAT126&locale=ko_KR',
            'https://data.krx.co.kr/contents/MDC/MDI/outerLoader/index.cmd?screenId=MDCSTAT127&locale=ko_KR', 'https://data.krx.co.kr/contents/MDC/MDI/outerLoader/index.cmd?screenId=MDCSTAT129&locale=ko_KR',
            'https://data.krx.co.kr/contents/MDC/MDI/outerLoader/index.cmd?screenId=MDCSTAT130&locale=ko_KR', 'https://data.krx.co.kr/contents/MDC/MDI/outerLoader/index.cmd?screenId=MDCSTAT131&locale=ko_KR']
    for u in urls:
        try:
            hh = dict(h); hh['Referer'] = 'https://data.krx.co.kr/contents/MDC/MAIN/main/index.cmd'; hh.pop('X-Requested-With', None)
            r = s.get(u, headers=hh, timeout=30); t = r.text
            out.append(f'\n===== {u} status={r.status_code} len={len(t)} 제목={re.findall(r"<title>(.*?)</title>", t, flags=re.S)[:1]} h2={re.findall(r"<h2[^>]*>(.*?)</h2>", t, flags=re.S)[:2]}')
            out += forms(t)
            inc = sorted(set(re.findall(r'["\'](/contents/[A-Za-z0-9_/.]+\.(?:cmd|jsp|js))["\']', t))); out.append('  내부 주소: ' + str(inc)[:1500])
        except Exception as e: out.append(f'{u} 오류 {e!r}')
    w('k1_screens.txt', '\n'.join(out))
    # 메뉴 전체
    try:
        hh = dict(h); hh.pop('X-Requested-With', None)
        t = s.get('https://data.krx.co.kr/contents/MDC/MAIN/main/index.cmd', headers=hh, timeout=40).text
        items = re.findall(r"menuId=(MDC\d+)','MDC\d+'\);\"[^>]*><span class=\"menu-name\" data-menu-name=\"([^\"]+)\" data-screen-no=\"([^\"]*)\"", t)
        seen = {}; [seen.setdefault(a, (b, c)) for a, b, c in items]
        w('k2_menu.txt', '\n'.join(f'{a}\t{c}\t{b}' for a, (b, c) in sorted(seen.items())))
        log('메뉴', len(seen))
    except Exception as e: w('k2_menu.txt', '오류 ' + repr(e))

def k_try():
    """파생상품 화면 후보 bld 를 번호 순으로 불러 응답 열 이름을 본다(야간 관련 열·화면 찾기)."""
    from pykrx.website.krx.krxio import KrxWebIo
    out = []
    def rd(bld, **p):
        class Any(KrxWebIo):
            @property
            def bld(self): return bld
        return Any().read(**p)
    for n in list(range(12501, 12509)) + list(range(12601, 12604)) + list(range(12701, 12704)) + list(range(12901, 12904)) + list(range(13001, 13004)) + list(range(13101, 13104)) + list(range(13201, 13204)) + list(range(13301, 13303)) + list(range(13401, 13403)) + list(range(13501, 13503)):
        bld = f'dbms/MDC/STAT/standard/MDCSTAT{n}'
        try:
            js = rd(bld, trdDd='20261113', prodId='KRDRVFUK2I', mktTpCd='T', rghtTpCd='T', strtDd='20261109', endDd='20261113', isuCd='KR4A016C0004', isuCd2='KR4A016C0004', secugrpId='FU', aggBasTpCd='0', juya='ALL')
            ks = [k for k in js.keys()] if isinstance(js, dict) else []
            rs = next((v for v in js.values() if isinstance(v, list) and v and isinstance(v[0], dict)), []) if isinstance(js, dict) else []
            txt = json.dumps(rs[:2], ensure_ascii=False)[:500]
            out.append(f'{n} keys={ks[:5]} 행={len(rs)} 열={list(rs[0].keys())[:18] if rs else ""}\n     {txt}' + ('   ★야간' if '야간' in json.dumps(rs, ensure_ascii=False) else ''))
        except Exception as e: out.append(f'{n} 오류 {str(e)[:80]}')
        time.sleep(0.3)
    w('k3_blds.txt', '\n'.join(out))

def c_chartlog():
    out = []; s = requests.Session(); s.headers.update({'User-Agent': UA, 'Accept-Language': 'ko-KR,ko;q=0.9'})
    for u in ('https://chartlog.net/stats/market-index/kospi-night-futures/', 'https://chartlog.net/stats/market-index/'):
        try:
            r = s.get(u, timeout=40); t = r.text
            out.append(f'\n===== {u} status={r.status_code} len={len(t)}')
            w('c_' + re.sub(r'[^a-z0-9]+', '_', u.lower())[-40:] + '.html', t[:400000])
            for kw in ('initialData', 'history', 'daily', 'timestamp', 'session_open', '/api/', 'fetch(', 'night'):
                hits = list(re.finditer(re.escape(kw), t)); out.append(f'  [{kw}] {len(hits)}곳')
                for mm in hits[:3]: out.append('     …' + re.sub(r'\s+', ' ', t[max(0, mm.start() - 160):mm.start() + 520]) + '…')
            chunks = sorted(set(re.findall(r'(/_next/static/chunks/[A-Za-z0-9_\-.]+\.js)', t)))
            out.append(f'  js {len(chunks)}개')
            found = set()
            for c in chunks[:40]:
                try:
                    j = s.get('https://chartlog.net' + c, timeout=30).text
                    for mm in re.finditer(r'["\'`](/api/[A-Za-z0-9_\-/${}.?=&]*)', j): found.add((c[-22:], mm.group(1)))
                    for mm in re.finditer(r'["\'`](https?://[A-Za-z0-9_\-./]+(?:api|socket|ws)[A-Za-z0-9_\-./?=&${}]*)', j): found.add((c[-22:], mm.group(1)))
                    for mm in re.finditer(r'night[A-Za-z_\-/]{0,40}', j): found.add((c[-22:], 'kw:' + mm.group(0)[:50]))
                except Exception as e: out.append(f'   {c} 오류 {e!r}')
            out.append('  찾은 주소: ' + json.dumps(sorted(found), ensure_ascii=False)[:6000])
        except Exception as e: out.append(f'{u} 오류 {e!r}')
    for u in ('https://chartlog.net/api/market-index/kospi-night-futures', 'https://chartlog.net/api/night-futures', 'https://chartlog.net/api/kospi-night-futures', 'https://chartlog.net/api/stats/market-index/kospi-night-futures',
              'https://chartlog.net/api/realtime/kospi-night-futures', 'https://chartlog.net/api/night-futures/history', 'https://chartlog.net/api/night-futures/daily', 'https://chartlog.net/robots.txt'):
        try:
            r = s.get(u, timeout=20); out.append(f'\n== {u} status={r.status_code} ct={r.headers.get("content-type")} len={len(r.text)}\n   ' + re.sub(r'\s+', ' ', r.text[:900]))
        except Exception as e: out.append(f'{u} 오류 {e!r}')
    w('c_chartlog.txt', '\n'.join(out))

def n_naver():
    out = []
    for u in ('https://api.stock.naver.com/futures/nation/KOR', 'https://api.stock.naver.com/index/nation/KOR', 'https://api.stock.naver.com/index/.VIX/price?page=1&pageSize=12', 'https://m.stock.naver.com/api/index/FUT/price?pageSize=3&page=1',
              'https://polling.finance.naver.com/api/realtime/domestic/index/FUT'):
        try:
            r = requests.get(u, headers={'User-Agent': UA, 'Referer': 'https://m.stock.naver.com/'}, timeout=30); js = r.json()
            if isinstance(js, list): out.append(f'\n== {u} {len(js)}건: ' + json.dumps([{k: x.get(k) for k in ('reutersCode', 'futuresName', 'indexName', 'closePrice', 'localTradedAt', 'worldIndexSymbol', 'openPrice') if k in x} for x in js], ensure_ascii=False)[:3000])
            else: out.append(f'\n== {u}: ' + json.dumps(js, ensure_ascii=False)[:1500])
        except Exception as e: out.append(f'{u} 오류 {e!r}')
    w('n_naver.txt', '\n'.join(out))

if __name__ == '__main__':
    only = set(sys.argv[1:])
    for name, fn in (('k1', k_screens), ('k3', k_try), ('c', c_chartlog), ('n', n_naver)):
        if only and name not in only: continue
        t0 = time.time(); safe(fn, name); log(f'[{name}] {time.time() - t0:.1f}s')
    w('_log.txt', '\n'.join(LOG))
