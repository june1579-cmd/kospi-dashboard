# -*- coding: utf-8 -*-
"""자료 출처 시험 3차 — KRX 파생상품 화면의 조회 조건(주간/야간) 찾기. 비밀값은 출력하지 않는다."""
import json, os, re, sys, time, traceback
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
def krx_sess():
    from pykrx.website.comm.webio import get_session
    ks = get_session()
    if ks is None: return requests.Session(), {'User-Agent': UA}
    h = ks.get_headers(); h['User-Agent'] = h.get('User-Agent') or UA
    return ks.session, h
def rd(bld, **p):
    from pykrx.website.krx.krxio import KrxWebIo
    class Any(KrxWebIo):
        @property
        def bld(self): return bld
    return Any().read(**p)

def shell():
    s, h = krx_sess(); out = []
    hh = dict(h); hh.pop('X-Requested-With', None); hh['Referer'] = 'https://data.krx.co.kr/contents/MDC/MAIN/main/index.cmd'
    t = s.get('https://data.krx.co.kr/contents/MDC/MDI/mdiLoader/index.cmd?menuId=MDC0201050101', headers=hh, timeout=40).text
    out.append(f'shell len={len(t)}')
    for kw in ('MDCSTAT', 'screenId', 'loadScreen', 'viewPage', 'ajaxUrl', '.cmd\'', 'mdiLoader', 'outerLoader', 'pageUrl', 'menuUrl', 'data-screen'):
        hits = list(re.finditer(re.escape(kw), t)); out.append(f'\n[{kw}] {len(hits)}곳')
        for mm in hits[:5]: out.append('   …' + re.sub(r'\s+', ' ', t[max(0, mm.start() - 220):mm.start() + 380]) + '…')
    # 메뉴 항목의 화면 주소 속성
    m = re.search(r'[^<]{0,400}MDC0201050101[^>]{0,400}>', t); out.append('\n메뉴 항목: ' + (m.group(0) if m else '없음'))
    js = sorted(set(re.findall(r'src="([^"]+\.js[^"]*)"', t))); out.append('\njs: ' + str(js))
    w('s1_shell.txt', '\n'.join(out))
    # js 파일에서 화면 주소 규칙 찾기
    out = []
    for j in js:
        if 'jquery' in j.lower() or 'chart' in j.lower(): continue
        u = j if j.startswith('http') else 'https://data.krx.co.kr' + j
        try:
            c = s.get(u, headers=hh, timeout=30).text
            for kw in ('screenId', 'menuId', '/contents/MDC/', 'STAT/standard'):
                for mm in list(re.finditer(re.escape(kw), c))[:6]: out.append(f'{j[-40:]} [{kw}] …' + re.sub(r'\s+', ' ', c[max(0, mm.start() - 200):mm.start() + 320]) + '…')
        except Exception as e: out.append(f'{j} 오류 {e!r}')
    w('s2_js.txt', '\n'.join(out)[:120000])
    # 화면 주소 후보
    out = []
    cands = []
    for sid in ('MDCSTAT125', 'MDCSTAT126', 'MDCSTAT127', 'MDCSTAT130'):
        for pat in ('https://data.krx.co.kr/contents/MDC/STAT/standard/{}.cmd', 'https://data.krx.co.kr/contents/MDC/STAT/standard/{}.jsp', 'https://data.krx.co.kr/contents/MDC/MDI/mdiLoader/index.cmd?screenId={}',
                    'https://data.krx.co.kr/contents/MDC/STAT/standard/{}.cmd?menuId=MDC0201050101'):
            cands.append(pat.format(sid))
    for u in cands:
        for xr in (True, False):
            for method in ('GET', 'POST'):
                try:
                    h2 = dict(hh); h2['Referer'] = 'https://data.krx.co.kr/contents/MDC/MDI/mdiLoader/index.cmd?menuId=MDC0201050101'
                    if xr: h2['X-Requested-With'] = 'XMLHttpRequest'
                    r = s.request(method, u, headers=h2, timeout=30); tt = r.text
                    ttl = re.findall(r'<title>(.*?)</title>', tt, flags=re.S)[:1]
                    ok = ('에러' not in str(ttl)) and len(tt) > 3000
                    out.append(f'{method} xr={xr} {u} → {r.status_code} len={len(tt)} {ttl} {"★" if ok else ""}')
                    if ok:
                        w('s3_' + re.sub(r'[^A-Za-z0-9]+', '_', u)[-50:] + f'_{method}_{int(xr)}.html', tt[:300000])
                except Exception as e: out.append(f'{u} 오류 {e!r}')
    w('s3_cands.txt', '\n'.join(out))

def brute():
    """개별종목 시세 추이(12601)·최근월물 추이(12701)·거래실적(13001)에 주간/야간 조건 이름 후보를 넣어 본다."""
    out = []
    base = {'12601': dict(isuCd='KR4A016C0004', isuCd2='KR4A016C0004', strtDd='20261109', endDd='20261113', prodId='KRDRVFUK2I', aggBasTpCd='0'),
            '12701': dict(prodId='KRDRVFUK2I', strtDd='20261109', endDd='20261113', aggBasTpCd='0'),
            '13001': dict(trdDd='20261113', secugrpId='FU')}
    names = ['juya', 'juyaTpCd', 'mktTpCd', 'mktTp', 'trdTmTpCd', 'trdTpCd', 'sessTpCd', 'trdSessTpCd', 'mktSessTpCd', 'boardId', 'brdId', 'mktId', 'trdTm', 'dayNightTpCd', 'dnTpCd', 'ngtTpCd', 'nghtTpCd', 'nightTpCd', 'trdSessId', 'sessId', 'mktSect', 'regNgtTpCd', 'trdSect', 'inqTpCd', 'inqTpCd2', 'tmTpCd', 'trdTmCd', 'mktStatTpCd']
    vals = ['2', 'N', 'T', 'ALL', 'A', '02', 'NIGHT', '야간', '3', '0']
    def sig(js):
        rs = next((v for v in js.values() if isinstance(v, list) and v and isinstance(v[0], dict)), []) if isinstance(js, dict) else []
        txt = json.dumps(rs, ensure_ascii=False)
        return len(rs), ('야간' in txt), txt[:160]
    for n, b in base.items():
        bld = 'dbms/MDC/STAT/standard/MDCSTAT' + n
        try: n0, y0, t0 = sig(rd(bld, **b)); out.append(f'{n} 기본 → {n0}행 야간={y0} {t0}')
        except Exception as e: out.append(f'{n} 기본 오류 {e!r}'); continue
        for nm in names:
            for v in vals:
                try:
                    n1, y1, t1 = sig(rd(bld, **b, **{nm: v}))
                    if y1 or n1 != n0 or t1 != t0: out.append(f'{n} {nm}={v} → {n1}행 야간={y1} {"★★★" if y1 else ""} {t1}')
                except Exception as e: pass
                time.sleep(0.12)
    w('s4_brute.txt', '\n'.join(out))
    # 13001 전체 이름
    try:
        js = rd('dbms/MDC/STAT/standard/MDCSTAT13001', trdDd='20261113', secugrpId='ALL'); rs = js.get('output', [])
        w('s5_13001.txt', '\n'.join(json.dumps(r, ensure_ascii=False) for r in rs))
    except Exception as e: w('s5_13001.txt', '오류 ' + repr(e))

if __name__ == '__main__':
    for name, fn in (('shell', shell), ('brute', brute)):
        try: fn()
        except Exception: w(name + '.err.txt', traceback.format_exc())
