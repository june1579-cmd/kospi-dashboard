# -*- coding: utf-8 -*-
"""자료 출처 시험(탐색)용 — GitHub 실행기에서만 돈다. 결과는 out/ 아래 글 파일로 남긴다. 비밀값은 출력하지 않는다."""
import datetime as dt, json, os, re, sys, time, traceback
import requests

KST = dt.timezone(dt.timedelta(hours=9))
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36'
SECRETS = [v for k, v in os.environ.items() if k in ('KRX_API_KEY', 'KRX_ID', 'KRX_PW') and v]
os.makedirs('out', exist_ok=True)

def red(s):
    s = str(s)
    for v in SECRETS:
        if v and len(v) >= 4: s = s.replace(v, '***')
    return s
def w(name, text):
    open(os.path.join('out', name), 'w', encoding='utf-8').write(red(text))
def safe(fn, name):
    try: return fn()
    except Exception as e:
        w(name + '.err.txt', traceback.format_exc()); return None
def head(js, n=1500): return json.dumps(js, ensure_ascii=False)[:n]

def get(url, params=None, headers=None, timeout=30, method='GET', data=None, sess=None):
    h = {'User-Agent': UA}; h.update(headers or {})
    s = sess or requests
    r = s.request(method, url, params=params, headers=h, timeout=timeout, data=data)
    return r

LOG = []
def log(*a):
    m = ' '.join(str(x) for x in a); LOG.append(m); print(red(m), flush=True)

# ---------------------------------------------------------------- A 시각
def a_time():
    from zoneinfo import ZoneInfo
    now = dt.datetime.now(dt.timezone.utc)
    log('UTC', now.isoformat(), '| KST', now.astimezone(KST).isoformat(), '| NY', now.astimezone(ZoneInfo('America/New_York')).isoformat())

# ---------------------------------------------------------------- B KRX 정보데이터시스템
def krx_session():
    """pykrx 가 쓰는 세션(로그인 포함)을 그대로 쓴다. 안 되면 익명 세션."""
    try:
        from pykrx.website.krx import krxio
        log('pykrx krxio 속성:', [x for x in dir(krxio) if not x.startswith('__')][:40])
    except Exception as e: log('pykrx import 실패', repr(e))
def krx_read(bld, **params):
    from pykrx.website.krx.krxio import KrxWebIo
    class Any(KrxWebIo):
        @property
        def bld(self): return bld
    return Any().read(**params)
def krx_raw(sess, bld, **params):
    r = sess.post('https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd', data={'bld': bld, 'locale': 'ko_KR', **params},
                  headers={'User-Agent': UA, 'Referer': 'https://data.krx.co.kr/contents/MDC/MDI/mdiLoader/index.cmd', 'X-Requested-With': 'XMLHttpRequest'}, timeout=30)
    try: return r.status_code, r.json()
    except Exception: return r.status_code, {'_text': r.text[:300]}
def rows_of(js):
    if not isinstance(js, dict): return []
    for k in ('output', 'OutBlock_1', 'block1', 'out'):
        if isinstance(js.get(k), list): return js[k]
    for k, v in js.items():
        if isinstance(v, list) and v and isinstance(v[0], dict): return v
    return []

def b_night():
    out = []
    for d in ('20261113', '20261112'):
        for extra in ({'mktTpCd': 'T', 'rghtTpCd': 'T'}, {'mktTpCd': '1', 'rghtTpCd': 'T'}, {'mktTpCd': '2', 'rghtTpCd': 'T'}, {'mktTpCd': '3', 'rghtTpCd': 'T'}, {'mktTpCd': 'N', 'rghtTpCd': 'T'},
                      {'mktTpCd': 'A', 'rghtTpCd': 'T'}, {'mktTpCd': 'T', 'rghtTpCd': 'T', 'trdTpCd': '2'}, {'mktTpCd': 'T', 'rghtTpCd': 'T', 'sessTpCd': '2'}, {'mktTpCd': 'T', 'rghtTpCd': 'T', 'nightYn': 'Y'},
                      {'mktTpCd': 'T', 'rghtTpCd': 'T', 'trdSessTpCd': 'N'}, {'rghtTpCd': 'T'}, {}):
            for prod in ('KRDRVFUK2I', 'KRDRVFUMKI'):
                try:
                    js = krx_read('dbms/MDC/STAT/standard/MDCSTAT12501', trdDd=d, prodId=prod, **extra); rs = rows_of(js)
                    names = sorted({str(r.get('ISU_NM', '')) for r in rs})
                    out.append(f'{d} {prod} {extra} → {len(rs)}행 keys={list(rs[0].keys()) if rs else list(js.keys())[:8]}\n   이름: {names[:14]}')
                    if rs and d == '20261113' and extra == {'mktTpCd': 'T', 'rghtTpCd': 'T'}: out.append('   첫 3행: ' + head(rs[:3], 2500))
                except Exception as e: out.append(f'{d} {prod} {extra} → 오류 {e!r}')
                time.sleep(0.4)
            if d != '20261113': break
    w('b1_night_12501.txt', '\n'.join(out))

def b_screens():
    s = requests.Session(); s.headers['User-Agent'] = UA
    out = []
    pages = ['https://data.krx.co.kr/contents/MDC/STAT/standard/MDCSTAT12501.cmd', 'https://data.krx.co.kr/contents/MDC/STAT/standard/MDCSTAT12601.cmd', 'https://data.krx.co.kr/contents/MDC/STAT/standard/MDCSTAT12502.cmd',
             'https://data.krx.co.kr/contents/MDC/STAT/standard/MDCSTAT01001.cmd', 'https://data.krx.co.kr/contents/MDC/STAT/standard/MDCSTAT01101.cmd', 'https://data.krx.co.kr/contents/MDC/STAT/standard/MDCSTAT01201.cmd',
             'https://data.krx.co.kr/contents/MDC/STAT/standard/MDCSTAT00901.cmd', 'https://data.krx.co.kr/contents/MDC/STAT/standard/MDCSTAT00801.cmd', 'https://data.krx.co.kr/contents/MDC/STAT/standard/MDCSTAT01301.cmd',
             'https://data.krx.co.kr/contents/MDC/MAIN/main/index.cmd']
    for u in pages:
        try:
            r = s.get(u, headers={'Referer': 'https://data.krx.co.kr/contents/MDC/MDI/mdiLoader/index.cmd'}, timeout=30); t = r.text
            out.append(f'\n===== {u} status={r.status_code} len={len(t)}')
            ttl = re.findall(r'<h2[^>]*>(.*?)</h2>|<title>(.*?)</title>', t, flags=re.S)[:3]; out.append('  제목: ' + str(ttl)[:300])
            for m in re.finditer(r'name="([A-Za-z0-9_]+)"', t): pass
            names = sorted(set(re.findall(r'name="([A-Za-z0-9_]+)"', t))); out.append('  name=: ' + str(names)[:900])
            blds = sorted(set(re.findall(r'dbms/[A-Za-z0-9_/]+', t))); out.append('  bld: ' + str(blds)[:900])
            for kw in ('야간', 'mktTpCd', '변동성', 'clssCd', 'indTpCd', '시장구분'):
                hits = [m.start() for m in re.finditer(kw, t)][:6]
                for h in hits: out.append(f'  [{kw}] …' + re.sub(r'\s+', ' ', t[max(0, h - 260):h + 420]) + '…')
            if u.endswith('main/index.cmd'):
                ids = re.findall(r'(MDC\d{8,})', t); out.append('  menuId 수: ' + str(len(set(ids))))
                for m in re.finditer(r'(MDC\d{8,})[^<>]{0,160}?>([^<>]{2,40})<', t):
                    lab = m.group(2).strip()
                    if any(k in lab for k in ('파생', '야간', '지수', '선물', '변동성')): out.append(f'  menu {m.group(1)} {lab}')
        except Exception as e: out.append(f'{u} 오류 {e!r}')
    w('b2_screens.txt', '\n'.join(out))

def b_vkospi():
    out = []
    today = '20261113'
    cands = []
    for bld in ('MDCSTAT01001', 'MDCSTAT01101', 'MDCSTAT00901', 'MDCSTAT00801', 'MDCSTAT01301', 'MDCSTAT01401'):
        for p in ({'trdDd': today}, {'trdDd': today, 'clssCd': '0201'}, {'trdDd': today, 'clssCd': '0202'}, {'trdDd': today, 'clssCd': '0300'}, {'trdDd': today, 'clssCd': '1300'}, {'trdDd': today, 'idxIndMidclssCd': '01'},
                  {'trdDd': today, 'clssCd': '0101'}, {'trdDd': today, 'clssCd': '0400'}, {'trdDd': today, 'clssCd': '0500'}, {'trdDd': today, 'clssCd': '0600'}):
            cands.append(('dbms/MDC/STAT/standard/' + bld, p))
    for bld in ('MDCSTAT01201', 'MDCSTAT01202', 'MDCSTAT00301'):
        for p in ({'indTpCd': '1', 'idxIndCd': '300', 'idxCd': '1', 'idxCd2': '300', 'strtDd': '20261105', 'endDd': '20261114'}, {'indTpCd': '1', 'idxIndCd': '300', 'strtDd': '20261105', 'endDd': '20261114'},
                  {'indTpCd': '5', 'idxIndCd': '300', 'idxCd': '5', 'idxCd2': '300', 'strtDd': '20261105', 'endDd': '20261114'}, {'indTpCd': '1', 'idxIndCd': '004', 'strtDd': '20261105', 'endDd': '20261114'}):
            cands.append(('dbms/MDC/STAT/standard/' + bld, p))
    for bld, p in cands:
        try:
            js = krx_read(bld, **p); rs = rows_of(js)
            vk = [r for r in rs if '변동성' in json.dumps(r, ensure_ascii=False)]
            out.append(f'{bld[-12:]} {p} → {len(rs)}행 keys={list(rs[0].keys())[:14] if rs else list(js.keys())[:6]} 변동성행={len(vk)}')
            if vk: out.append('   변동성: ' + head(vk[:4], 1800))
            elif rs and 'strtDd' in p: out.append('   첫행: ' + head(rs[:2], 900))
            elif rs: out.append('   이름 예: ' + str(sorted({str(r.get('IDX_NM', r.get('IDX_IND_NM', '')))[:18] for r in rs})[:12]))
        except Exception as e: out.append(f'{bld[-12:]} {p} → 오류 {e!r}')
        time.sleep(0.35)
    for fb, p in (('dbms/comm/finder/finder_drvetcidx', {'mktsel': 'ALL', 'searchText': '변동성'}), ('dbms/comm/finder/finder_equidx', {'mktsel': '1', 'searchText': '변동성'}), ('dbms/comm/finder/finder_drvetcidx', {'mktsel': '1'}),
                  ('dbms/comm/finder/finder_drvprodisu', {'mktsel': 'ALL', 'searchText': '야간'}), ('dbms/comm/finder/finder_drvprodisu', {'mktsel': 'ALL', 'searchText': '코스피200'})):
        try:
            js = krx_read(fb, **p); rs = rows_of(js)
            out.append(f'finder {fb[-18:]} {p} → {len(rs)}행 ' + head(rs[:25], 2600))
        except Exception as e: out.append(f'finder {fb} {p} → 오류 {e!r}')
    w('b3_vkospi.txt', '\n'.join(out))

# ---------------------------------------------------------------- C KRX Open API
def c_openapi():
    key = os.environ.get('KRX_API_KEY', '')
    out = ['키 있음' if key else '키 없음']
    if key:
        s = requests.Session(); s.headers.update({'AUTH_KEY': key, 'User-Agent': UA})
        for svc in ('drv/fut_bydd_trd', 'drv/eqsfu_stk_bydd_trd', 'drv/opt_bydd_trd', 'idx/drvprod_dd_trd', 'idx/kospi_dd_trd', 'idx/krx_dd_trd', 'sto/stk_bydd_trd', 'etp/etf_bydd_trd'):
            for d in ('20261113', '20261112'):
                try:
                    r = s.get('https://data-dbg.krx.co.kr/svc/apis/' + svc, params={'basDd': d}, timeout=40)
                    try: js = r.json()
                    except Exception: js = {'_text': r.text[:200]}
                    rs = js.get('OutBlock_1', []) if isinstance(js, dict) else []
                    line = f'{svc} {d} status={r.status_code} respCode={js.get("respCode") if isinstance(js, dict) else None} 행={len(rs)} keys={list(rs[0].keys()) if rs else list(js.keys())[:6]}'
                    out.append(line)
                    if svc == 'drv/fut_bydd_trd' and rs:
                        out.append('   구분: ' + str(sorted({(x.get('PROD_NM'), x.get('MKT_NM')) for x in rs}))[:1500])
                        k2 = [x for x in rs if '코스피200' in str(x.get('PROD_NM', '')) and '미니' not in str(x.get('PROD_NM', ''))]
                        out.append('   코스피200 선물 행: ' + head(k2[:12], 5000))
                    if svc == 'idx/drvprod_dd_trd' and rs:
                        out.append('   변동성: ' + head([x for x in rs if '변동성' in str(x.get('IDX_NM', ''))], 1500))
                    if svc in ('idx/kospi_dd_trd',) and rs:
                        out.append('   코스피: ' + head([x for x in rs if str(x.get('IDX_NM', '')).replace(' ', '') in ('코스피', '코스피200')], 1200))
                except Exception as e: out.append(f'{svc} {d} 오류 {e!r}')
                time.sleep(0.4)
    w('c_openapi.txt', '\n'.join(out))

# ---------------------------------------------------------------- D 네이버 · E 다음
def d_naver():
    out = []
    H = {'Referer': 'https://m.stock.naver.com/'}
    urls = ['https://m.stock.naver.com/api/index/KOSPI/basic', 'https://m.stock.naver.com/api/index/KOSPI/price?pageSize=6&page=1', 'https://m.stock.naver.com/api/index/KPI200/basic', 'https://m.stock.naver.com/api/index/KPI200/price?pageSize=6&page=1',
            'https://m.stock.naver.com/api/index/KOSDAQ/price?pageSize=3&page=1', 'https://m.stock.naver.com/api/index/FUT/basic', 'https://m.stock.naver.com/api/index/FUT/price?pageSize=6&page=1',
            'https://m.stock.naver.com/api/index/VKOSPI/basic', 'https://m.stock.naver.com/api/index/VKOSPI/price?pageSize=6&page=1', 'https://m.stock.naver.com/api/index/KVI200/basic',
            'https://polling.finance.naver.com/api/realtime/domestic/index/KOSPI', 'https://polling.finance.naver.com/api/realtime/domestic/index/KOSPI,KPI200,FUT,KOSDAQ',
            'https://m.stock.naver.com/api/index/majors', 'https://m.stock.naver.com/api/indices/domestic', 'https://m.stock.naver.com/api/index/meta/KOSPI', 'https://api.stock.naver.com/index/KOSPI/price?page=1&pageSize=5',
            'https://api.stock.naver.com/index/.VIX/price?page=1&pageSize=6', 'https://api.stock.naver.com/index/.VIX/basic', 'https://api.stock.naver.com/futures/nation/KOR', 'https://api.stock.naver.com/index/nation/KOR',
            'https://m.stock.naver.com/api/domestic/futures', 'https://m.stock.naver.com/front-api/marketIndex/domestic/futures', 'https://api.stock.naver.com/futures/KOSPI200/basic',
            'https://finance.naver.com/sise/sise_index_day.naver?code=FUT', 'https://finance.naver.com/sise/sise_index.naver?code=FUT']
    for u in urls:
        try:
            r = get(u, headers=H); t = r.text
            out.append(f'\n== {u}\n   status={r.status_code} len={len(t)} ct={r.headers.get("content-type")}\n   ' + re.sub(r'\s+', ' ', t[:1400]))
        except Exception as e: out.append(f'{u} 오류 {e!r}')
        time.sleep(0.3)
    w('d_naver.txt', '\n'.join(out))

def e_daum():
    out = []
    s = requests.Session(); s.headers.update({'User-Agent': UA, 'Accept': 'application/json'})
    reqs = [('https://finance.daum.net/api/market_index/days', {'market': 'KOSPI', 'page': 1, 'perPage': 5, 'pagination': 'true'}, 'https://finance.daum.net/domestic/index'),
            ('https://finance.daum.net/api/future/KR4A016C0004/days', {'page': 1, 'perPage': 5, 'pagination': 'true'}, 'https://finance.daum.net/domestic/futures'),
            ('https://finance.daum.net/api/future/KR4A016C0004', {}, 'https://finance.daum.net/domestic/futures'),
            ('https://finance.daum.net/api/futures/masters', {}, 'https://finance.daum.net/domestic/futures'),
            ('https://finance.daum.net/api/future/masters', {}, 'https://finance.daum.net/domestic/futures'),
            ('https://finance.daum.net/api/domestic/futures', {}, 'https://finance.daum.net/domestic/futures'),
            ('https://finance.daum.net/api/future/KR4A016C0004/night/days', {'page': 1, 'perPage': 5}, 'https://finance.daum.net/domestic/futures'),
            ('https://finance.daum.net/api/night_future/days', {'page': 1, 'perPage': 5}, 'https://finance.daum.net/domestic/futures'),
            ('https://finance.daum.net/api/market_index/days', {'market': 'KOSPI200', 'page': 1, 'perPage': 3, 'pagination': 'true'}, 'https://finance.daum.net/domestic/index'),
            ('https://finance.daum.net/api/investor/KOSPI/days', {'details': 'true', 'page': 1, 'perPage': 3, 'pagination': 'true'}, 'https://finance.daum.net/domestic/investors'),
            ('https://finance.daum.net/domestic/futures', {}, 'https://finance.daum.net/')]
    for u, p, ref in reqs:
        try:
            r = s.get(u, params=p, headers={'Referer': ref}, timeout=30); t = r.text
            out.append(f'\n== {u} {p}\n   status={r.status_code} len={len(t)}\n   ' + re.sub(r'\s+', ' ', t[:1500]))
            if u.endswith('/domestic/futures') and r.status_code == 200:
                out.append('   api 주소들: ' + str(sorted(set(re.findall(r'/api/[A-Za-z0-9_/\-{}$.]+', t)))[:80]))
                out.append('   js: ' + str(re.findall(r'src="([^"]+\.js[^"]*)"', t)[:20]))
        except Exception as e: out.append(f'{u} 오류 {e!r}')
        time.sleep(0.3)
    w('e_daum.txt', '\n'.join(out))

# ---------------------------------------------------------------- F VIX·유가
def f_vix():
    from zoneinfo import ZoneInfo
    out = []
    try:
        r = get('https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv'); t = r.text.strip().splitlines()
        out.append(f'CBOE status={r.status_code} 줄={len(t)} 머리={t[0]} 꼬리={t[-12:]}')
    except Exception as e: out.append(f'CBOE 오류 {e!r}')
    for host in ('query1', 'query2'):
        try:
            r = get(f'https://{host}.finance.yahoo.com/v8/finance/chart/%5EVIX', params={'range': '1mo', 'interval': '1d'}); js = r.json()
            res = js['chart']['result'][0]; ts = res['timestamp']; cl = res['indicators']['quote'][0]['close']; meta = res.get('meta', {})
            ny = ZoneInfo('America/New_York')
            out.append(f'Yahoo {host} status={r.status_code} n={len(ts)} 꼬리=' + str([(dt.datetime.fromtimestamp(t_, ny).strftime('%Y-%m-%d %H:%M'), None if c is None else round(c, 2)) for t_, c in list(zip(ts, cl))[-8:]]))
            out.append('   meta: ' + head({k: meta.get(k) for k in ('regularMarketTime', 'regularMarketPrice', 'chartPreviousClose', 'previousClose', 'gmtoffset', 'exchangeTimezoneName', 'currentTradingPeriod', 'hasPrePostMarketData', 'dataGranularity', 'range')}, 1500))
        except Exception as e: out.append(f'Yahoo {host} 오류 {e!r}')
    try:
        r = get('https://stooq.com/q/d/l/', params={'s': '^vix', 'i': 'd'}); t = r.text.strip().splitlines(); out.append(f'stooq status={r.status_code} 줄={len(t)} 머리={t[0][:80]} 꼬리={t[-6:]}')
    except Exception as e: out.append(f'stooq 오류 {e!r}')
    for sid in ('VIXCLS', 'DCOILWTICO', 'DCOILBRENTEU', 'DGS10', 'BAMLH0A0HYM2', 'DEXKOUS'):
        try:
            r = get('https://fred.stlouisfed.org/graph/fredgraph.csv', params={'id': sid, 'cosd': '2026-10-01'}, timeout=40); t = r.text.strip().splitlines(); out.append(f'FRED {sid} status={r.status_code} 줄={len(t)} 꼬리={t[-9:]}')
        except Exception as e: out.append(f'FRED {sid} 오류 {e!r}')
    for u in ('https://query1.finance.yahoo.com/v8/finance/chart/CL%3DF?range=1mo&interval=1d', 'https://query1.finance.yahoo.com/v8/finance/chart/BZ%3DF?range=1mo&interval=1d', 'https://query1.finance.yahoo.com/v8/finance/chart/%5EKS200?range=5d&interval=1d',
              'https://query1.finance.yahoo.com/v8/finance/chart/%5EKS11?range=5d&interval=1d'):
        try:
            r = get(u); js = r.json(); res = js['chart']['result'][0]; ts = res['timestamp']; cl = res['indicators']['quote'][0]['close']
            out.append(f'{u[-40:]} status={r.status_code} 꼬리=' + str([(dt.datetime.fromtimestamp(t_, dt.timezone.utc).strftime('%Y-%m-%d %H:%M'), None if c is None else round(c, 2)) for t_, c in list(zip(ts, cl))[-6:]]))
        except Exception as e: out.append(f'{u[-40:]} 오류 {e!r}')
    w('f_vix.txt', '\n'.join(out))

# ---------------------------------------------------------------- G 야간선물 공개 사이트
def g_sites():
    out = []
    for u in ('https://sonmul.co.kr', 'https://www.sonmul.co.kr', 'https://chartlog.net', 'https://www.chartlog.net', 'https://kr.investing.com/indices/korea-200-futures', 'https://www.investing.com/indices/korea-200-futures-historical-data',
              'https://esignal.co.kr/kospi200-futures-night/', 'https://finance.daum.net/domestic/futures', 'https://m.stock.naver.com/domestic/index/FUT/total'):
        try:
            r = get(u, headers={'Accept-Language': 'ko-KR,ko;q=0.9'}, timeout=30); t = r.text
            out.append(f'\n===== {u} status={r.status_code} len={len(t)} 최종주소={r.url}')
            out.append('  제목: ' + str(re.findall(r'<title[^>]*>(.*?)</title>', t, flags=re.S)[:1])[:200])
            out.append('  script: ' + str(re.findall(r'<script[^>]+src="([^"]+)"', t)[:25])[:1500])
            out.append('  주소: ' + str(sorted(set(re.findall(r'["\'](/?(?:api|data|ajax|json)[A-Za-z0-9_/\-.?=&]*)["\']', t)))[:40])[:1500])
            out.append('  https: ' + str(sorted(set(re.findall(r'https?://[A-Za-z0-9_\-./?=&%]+', t)))[:60])[:2500])
            for kw in ('야간', 'night', 'Night'):
                for m in list(re.finditer(kw, t))[:5]: out.append(f'  [{kw}] …' + re.sub(r'\s+', ' ', t[max(0, m.start() - 200):m.start() + 300]) + '…')
            w('g_' + re.sub(r'[^a-z0-9]+', '_', u.lower())[:40] + '.html', t[:60000])
        except Exception as e: out.append(f'{u} 오류 {e!r}')
    w('g_sites.txt', '\n'.join(out))

if __name__ == '__main__':
    only = set(sys.argv[1:])
    for name, fn in (('a', a_time), ('ks', krx_session), ('b1', b_night), ('b2', b_screens), ('b3', b_vkospi), ('c', c_openapi), ('d', d_naver), ('e', e_daum), ('f', f_vix), ('g', g_sites)):
        if only and name not in only: continue
        t0 = time.time(); safe(fn, name); log(f'[{name}] {time.time() - t0:.1f}s')
    w('_log.txt', '\n'.join(LOG))
