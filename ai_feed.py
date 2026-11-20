# -*- coding: utf-8 -*-
"""ai_feed.py — AI 선행지표 경고판용 원자료 자동 수집(2026-11-20 시작).
   경고판 예약 작업(07:30·15:50·19:30 KST)이 이 값들을 웹 검색으로 다시 찾지 않고 이 파일을 먼저 읽는다.
   (예약 작업이 사용량 한도로 멈춰 경고판이 이틀 멈췄던 일을 줄이려는 것 — 숫자 수집은 GitHub Actions 가 맡는다)

 출처(모두 1차 원자료, 키가 필요 없는 것 위주)
   FRED   하이일드 OAS(BAMLH0A0HYM2) · 미국 10년물(DGS10) · 미국 실업률(UNRATE)
          · Ramp AI Index(RAMPAIALL) · 전기요금 CPI 계절조정 전(CUUR0000SEHF01)
   Yahoo  필라델피아 반도체지수(^SOX) — 2026년 최고 종가 대비 하락률 · WTI(CL=F, NYMEX 근월물 — 경고판 보도 기준과 같음)
   코어위브(CRWV) 주가 — Twelve Data(비밀값 TWELVEDATA_API_KEY 가 있을 때), 없거나 실패하면 Yahoo
          (코어위브 5년 CDS 는 무료 원자료가 없어 주가를 보조로만 둔다)

 출력
   out/ai_feed.csv       항목마다 최신 값 한 줄(key, board_key, name, value, unit, as_of, prev_value, prev_as_of,
                         text, stage, near, source, url, fetched_at, status)
   out/ai_feed_hist.csv  date,key,value,source,fetched_at 누적(경계값 백테스트용)
 stage·near 는 docs/ai/data/thresholds.json 의 경계로 경고판 페이지와 같은 식으로 계산한 참고값이다(판정은 경고판이 한다).
 못 받은 항목은 직전 줄을 그대로 두고 status 에 실패를 적는다 — 추정으로 채우지 않는다.
 사용: python ai_feed.py
"""
import csv, datetime as dt, io, json, os, time
import requests
from zoneinfo import ZoneInfo

KST, NY = ZoneInfo('Asia/Seoul'), ZoneInfo('America/New_York')
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36'
FEED, HIST, TH = 'out/ai_feed.csv', 'out/ai_feed_hist.csv', 'docs/ai/data/thresholds.json'
COLS = ['key', 'board_key', 'name', 'value', 'unit', 'as_of', 'prev_value', 'prev_as_of', 'text',
        'stage', 'near', 'source', 'url', 'fetched_at', 'status']
SOX_PEAK, SOX_PEAK_DATE = 14634.72, '2026-06-22'      # 경고판 정의(sox_dd)의 2026년 최고 종가
NOW = dt.datetime.now(KST)

def log(m): print(f'[{dt.datetime.now(KST):%H:%M:%S}] {m}', flush=True)
def sgn(x, d=1): return f'{"−" if x < 0 else "+"}{abs(x):,.{d}f}'
def md(d): return f'{int(d[5:7])}.{int(d[8:10])}' if len(d) >= 10 else d

def get(url, ua=UA, timeout=30, **kw):
    err = None
    for i in range(3):
        try:
            r = requests.get(url, headers={'User-Agent': ua} if ua else None, timeout=timeout, **kw)
            r.raise_for_status(); return r
        except Exception as e:
            err = e; time.sleep(3 * (i + 1))
    raise err

def fred(sid, start):
    """FRED 그래프 CSV → [(date, float)] (빈 값·'.' 은 건너뜀).
       FRED 는 브라우저 흉내 User-Agent 를 붙이면 응답을 끊는다(2026-11-20 확인) — 기본 헤더로 받는다."""
    txt = get('https://fred.stlouisfed.org/graph/fredgraph.csv', ua=None, timeout=20, params={'id': sid, 'cosd': start}).text
    rows = list(csv.reader(io.StringIO(txt)))
    out = []
    for r in rows[1:]:
        if len(r) >= 2 and r[1] not in ('', '.'):
            out.append((r[0][:10], float(r[1])))
    if not out: raise RuntimeError(f'FRED {sid} 값 없음')
    return out

def ny_done(d):
    now = dt.datetime.now(NY)
    return d < now.strftime('%Y-%m-%d') or (d == now.strftime('%Y-%m-%d') and now.hour * 60 + now.minute >= 16 * 60 + 30)

def yahoo(sym, rng='2y'):
    js = get(f'https://query1.finance.yahoo.com/v8/finance/chart/{requests.utils.quote(sym)}',
             params={'range': rng, 'interval': '1d'}).json()
    res = js['chart']['result'][0]
    out = []
    for t, c in zip(res['timestamp'], res['indicators']['quote'][0]['close']):
        if c is None: continue
        d = dt.datetime.fromtimestamp(t, NY).strftime('%Y-%m-%d')
        if ny_done(d) and not (out and out[-1][0] == d): out.append((d, float(c)))   # 선물은 같은 날짜에 장중 봉이 하나 더 붙는다 — 날짜마다 첫 일봉(정산가)만 쓴다
    # 야후는 마지막 날 일봉 종가를 비워 두는 때가 있다(2026-11-19 CRWV) — 같은 응답의 정규장 마감 가격(16:00 이후 시각)으로 채운다
    m = res.get('meta', {})
    if m.get('regularMarketPrice') and m.get('regularMarketTime'):
        mt = dt.datetime.fromtimestamp(m['regularMarketTime'], NY)
        md_ = mt.strftime('%Y-%m-%d')
        if mt.hour >= 16 and ny_done(md_) and (not out or out[-1][0] < md_):
            out.append((md_, float(m['regularMarketPrice'])))
    if not out: raise RuntimeError(f'Yahoo {sym} 값 없음')
    return out

def twelve(sym, key, size=40):
    js = get('https://api.twelvedata.com/time_series',
             params={'symbol': sym, 'interval': '1day', 'outputsize': size, 'apikey': key}).json()
    if js.get('status') == 'error': raise RuntimeError(js.get('message', 'error')[:120])
    out = sorted((v['datetime'][:10], float(v['close'])) for v in js.get('values', []))
    out = [x for x in out if ny_done(x[0])]
    if not out: raise RuntimeError(f'Twelve Data {sym} 값 없음')
    return out

# ── 경고판과 같은 식으로 단계·near 계산(참고값) ─────────────────────────────
STAGES = ['정상', '주의', '경고', '위험']
def load_th():
    try:
        t = json.load(open(TH, encoding='utf-8'))
        t = t if isinstance(t, list) else t.get('rows', [])
        return {r['key']: r for r in t}
    except Exception as e:
        log(f'경계값 파일을 못 읽음({e!r}) — 단계 계산 건너뜀'); return {}

def stage_of(cur, r):
    if r is None or r.get('kind') != 'number' or cur is None: return '', ''
    sign = -1 if r['dir'] == 'down' else 1
    xs = [r[k] * sign for k in ('s0', 't1', 't2', 't3', 's4')]
    v = min(max(cur * sign, xs[0]), xs[4])
    i = 0
    while i < 3 and v >= xs[i + 1]: i += 1          # 경계값과 같으면 높은 단계
    pos = i + (v - xs[i]) / (xs[i + 1] - xs[i])
    near = i < 3 and (xs[i + 1] - v) <= 0.1 * (xs[i + 1] - xs[i])
    return STAGES[min(3, int(pos))], ('참' if near else '')

# ── 항목별 계산 ─────────────────────────────────────────────────────────────
def last2(rows): return rows[-1], (rows[-2] if len(rows) > 1 else (None, None))

def item_daily(key, sid, name, unit, fmt, board_key=''):
    rows = fred(sid, (NOW - dt.timedelta(days=60)).strftime('%Y-%m-%d'))
    (d, v), (pd_, pv) = last2(rows)
    return dict(key=key, board_key=board_key, name=name, value=v, unit=unit, as_of=d, prev_value=pv, prev_as_of=pd_,
                text=fmt(v, d), source=f'FRED {sid}', url=f'https://fred.stlouisfed.org/series/{sid}')

def item_unrate():
    rows = fred('UNRATE', (NOW - dt.timedelta(days=200)).strftime('%Y-%m-%d'))
    (d, v), (pd_, pv) = last2(rows)
    return dict(key='us_unemp', board_key='us_unemp', name='미국 실업률(계절조정)', value=v, unit='%', as_of=d[:7],
                prev_value=pv, prev_as_of=(pd_ or '')[:7], text=f'{v:.1f}%({int(d[5:7])}월)',
                source='FRED UNRATE', url='https://fred.stlouisfed.org/series/UNRATE')

def item_ramp():
    rows = fred('RAMPAIALL', (NOW - dt.timedelta(days=500)).strftime('%Y-%m-%d'))
    q = {}
    for d, v in rows:
        k = (int(d[:4]), (int(d[5:7]) - 1) // 3 + 1); q.setdefault(k, []).append(v)
    full = [(k, sum(v) / 3) for k, v in sorted(q.items()) if len(v) == 3]      # 석 달이 다 찬 분기만
    if len(full) < 3: raise RuntimeError('Ramp 완결 분기 3개 미만')
    (k1, a1), (k2, a2), (k3, a3) = full[-3:]
    d2, d3 = a2 - a1, a3 - a2
    val, prev = (d2 + d3) / 2, None
    if len(full) >= 4: prev = ((full[-3][1] - full[-4][1]) + d2) / 2
    end_m = f'{k3[0]}-{k3[1] * 3:02d}'
    last_d, last_v = rows[-1]
    txt = (f'{sgn(val)}%p({k2[1]}·{k3[1]}분기 평균; 분기 평균 {a1:.2f}→{a2:.2f}→{a3:.2f}, '
           f'최신 월 {int(last_d[5:7])}월 {last_v:.2f})')
    return dict(key='ramp_q', board_key='ramp_q', name='Ramp AI Index 분기 증가 폭(최근 2개 분기 평균)', value=round(val, 3),
                unit='%p', as_of=end_m, prev_value=(round(prev, 3) if prev is not None else ''), prev_as_of='',
                text=txt, source='FRED RAMPAIALL(완결 분기만 계산)', url='https://fred.stlouisfed.org/series/RAMPAIALL')

def item_elec():
    rows = fred('CUUR0000SEHF01', (NOW - dt.timedelta(days=800)).strftime('%Y-%m-%d'))
    m = {d[:7]: v for d, v in rows}
    yoy = []
    for ym in sorted(m):
        y0 = f'{int(ym[:4]) - 1}{ym[4:]}'
        if y0 in m: yoy.append((ym, (m[ym] / m[y0] - 1) * 100))
    if not yoy: raise RuntimeError('전기요금 CPI 전년비 계산 불가')
    (d, v), (pd_, pv) = last2(yoy)
    newest = max(m)
    gap = '' if newest == d else f' — {int(newest[5:7])}월은 전년 같은 달 원자료가 없어 계산 불가'
    return dict(key='elec_cpi', board_key='elec_cpi', name='미국 전기요금 CPI 전년비(계절조정 전)', value=round(v, 2), unit='%',
                as_of=d, prev_value=(round(pv, 2) if pv is not None else ''), prev_as_of=pd_ or '',
                text=f'{sgn(v)}%({int(d[5:7])}월){gap}', source='FRED CUUR0000SEHF01',
                url='https://fred.stlouisfed.org/series/CUUR0000SEHF01')

def item_sox():
    rows = yahoo('^SOX', '2y')
    y26 = [c for d, c in rows if d.startswith('2026')]
    peak = max([SOX_PEAK] + y26)
    note = '' if abs(peak - SOX_PEAK) < 0.5 else f' (2026년 최고 종가가 {peak:,.2f}로 바뀜)'
    (d, c), (pd_, pc) = last2(rows)
    v, pv = (c / peak - 1) * 100, ((pc / peak - 1) * 100 if pc else None)
    return dict(key='sox_dd', board_key='sox_dd', name='필라델피아 반도체지수 2026년 고점 대비', value=round(v, 2), unit='%',
                as_of=d, prev_value=(round(pv, 2) if pv is not None else ''), prev_as_of=pd_ or '',
                text=f'{sgn(v)}%({md(d)}, {c:,.2f}){note}', source=f'Yahoo ^SOX(고점 {SOX_PEAK_DATE} {SOX_PEAK:,.2f})',
                url='https://finance.yahoo.com/quote/%5ESOX/history/')

def item_wti():
    """경고판 macro 'WTI 유가'는 NYMEX 근월물 종가(보도 기준)다 — FRED DCOILWTICO(현물)는 3달러가량 달라 쓰지 않는다(2026-11-20 대조)."""
    rows = yahoo('CL=F', '3mo')
    (d, v), (pd_, pv) = last2(rows)
    return dict(key='wti', board_key='', name='WTI 유가(NYMEX 근월물)', value=round(v, 2), unit='달러/배럴', as_of=d,
                prev_value=round(pv, 2) if pv else '', prev_as_of=pd_ or '',
                text=f'{v:.2f}달러({md(d)}, 근월물{", " + sgn((v / pv - 1) * 100, 2) + "%" if pv else ""})',
                source='Yahoo CL=F(NYMEX WTI 근월물)', url='https://finance.yahoo.com/quote/CL%3DF/history/')

def item_crwv():
    key, src, rows = os.environ.get('TWELVEDATA_API_KEY', '').strip(), '', None
    if key:
        try: rows, src = twelve('CRWV', key), 'Twelve Data CRWV'
        except Exception as e: log(f'Twelve Data CRWV 실패 — 야후로: {e!r}'[:160])
    if rows is None: rows, src = yahoo('CRWV', '3mo'), 'Yahoo CRWV'
    (d, c), (pd_, pc) = last2(rows)
    ch = lambda n: (c / rows[-1 - n][1] - 1) * 100 if len(rows) > n else None
    c5, c20 = ch(5), ch(20)
    parts = [f'{c:,.2f}달러({md(d)})'] + ([f'5거래일 {sgn(c5)}%'] if c5 is not None else []) + ([f'20거래일 {sgn(c20)}%'] if c20 is not None else [])
    return dict(key='crwv_px', board_key='', name='코어위브 주가(CDS 보조 참고)', value=round(c, 4), unit='달러', as_of=d,
                prev_value=round(pc, 4) if pc else '', prev_as_of=pd_ or '', text=' · '.join(parts), source=src,
                url='https://finance.yahoo.com/quote/CRWV/history/')

ITEMS = [
    ('hy_oas', lambda: item_daily('hy_oas', 'BAMLH0A0HYM2', '미국 하이일드 스프레드(ICE BofA OAS)', '%',
                                   lambda v, d: f'{v:.2f}%({md(d)})', 'hy_oas')),
    ('us10y', lambda: item_daily('us10y', 'DGS10', '미국 10년물 금리', '%', lambda v, d: f'{v:.2f}%({md(d)})')),
    ('wti', item_wti),
    ('us_unemp', item_unrate), ('ramp_q', item_ramp), ('elec_cpi', item_elec), ('sox_dd', item_sox), ('crwv_px', item_crwv),
]

def main():
    os.makedirs('out', exist_ok=True)
    old = {}
    if os.path.exists(FEED):
        with open(FEED, encoding='utf-8') as f: old = {r['key']: r for r in csv.DictReader(f)}
    th, stamp = load_th(), NOW.strftime('%Y-%m-%dT%H:%M:%S+09:00')
    out, hist_new, fails = [], [], []
    for key, fn in ITEMS:
        try:
            r = fn()
            r['stage'], r['near'] = stage_of(float(r['value']), th.get(r['board_key'])) if r['board_key'] else ('', '')
            r.update(fetched_at=stamp, status='정상')
            hist_new.append({'date': r['as_of'], 'key': key, 'value': r['value'], 'source': r['source'], 'fetched_at': stamp})
            log(f"{key}: {r['text']} {r['stage']}{' near' if r['near'] else ''}")
        except Exception as e:
            fails.append(key)
            msg = f'이번 수집 실패({repr(e)[:90]})'
            if key in old:
                r = dict(old[key]); r['status'] = f"{msg} — 직전 값({r.get('fetched_at', '')}) 유지"
            else:
                r = {c: '' for c in COLS}; r.update(key=key, status=f'{msg} — 값 없음')
            log(f'{key}: {msg}')
        out.append({c: r.get(c, '') for c in COLS})
    with open(FEED, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=COLS); w.writeheader(); w.writerows(out)
    hist = []
    if os.path.exists(HIST):
        with open(HIST, encoding='utf-8') as f: hist = list(csv.DictReader(f))
    seen = {(h['date'], h['key']): i for i, h in enumerate(hist)}
    for h in hist_new:
        k = (str(h['date']), h['key'])
        if k in seen: hist[seen[k]] = h
        else: seen[k] = len(hist); hist.append(h)
    hist.sort(key=lambda h: (h['key'], str(h['date'])))
    with open(HIST, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['date', 'key', 'value', 'source', 'fetched_at']); w.writeheader(); w.writerows(hist)
    log(f'완료: {len(ITEMS) - len(fails)}/{len(ITEMS)} 정상' + (f' · 실패 {", ".join(fails)}' if fails else ''))

if __name__ == '__main__':
    main()
