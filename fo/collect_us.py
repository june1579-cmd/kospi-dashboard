# -*- coding: utf-8 -*-
"""미국·한국 선물옵션 대시보드 — 공개 자료 수집(GitHub Actions 에서 실행, 키 불필요).

받는 것 → fo/data/
  cftc.csv        CFTC Traders in Financial Futures(선물만) ES(13874A)·NQ(209742) 주체별 롱·숏·미결제 (2006~, 주간)
  cboe_pc.csv     Cboe 풋/콜(전체·지수·개별주식·SPX)과 거래량·미결제약정 합계 (일별, 받은 날은 다시 받지 않음)
  vix.csv         VIX9D·VIX·VIX3M·VIX6M·VIX1Y 종가 (Cboe 공표 이력)
  px.csv          야후 일봉: S&P500·나스닥100·QQQ·DIA·ES·NQ·코스피200·코스피·원/달러
  status.json     출처별 성공 여부·마지막 날짜(대시보드 '자료 설명'에 그대로 실린다)
원칙: 못 받은 값은 추정하지 않는다(빈칸 = 확인 불가). 실패한 출처는 기존 파일을 그대로 두고 status 에 사유를 적는다.
"""
import concurrent.futures as cf
import datetime as dt
import io
import json
import os
import sys
import time
import zipfile
from zoneinfo import ZoneInfo

import pandas as pd
import requests

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, 'data')
os.makedirs(DATA, exist_ok=True)
KST, NY = ZoneInfo('Asia/Seoul'), ZoneInfo('America/New_York')
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36'
STATUS = {}


def log(m): print(f'[{dt.datetime.now(KST):%H:%M:%S}] {m}', flush=True)


def get(url, tries=3, timeout=40, **kw):
    last = None
    for k in range(tries):
        try:
            r = requests.get(url, headers={'User-Agent': UA}, timeout=timeout, **kw)
            if r.status_code == 200: return r
            last = RuntimeError(f'HTTP {r.status_code}')
            if r.status_code in (403, 404): break
        except Exception as e:
            last = e
        time.sleep(2 + 3 * k)
    raise last


def mark(name, ok, last='', note=''):
    STATUS[name] = {'ok': bool(ok), 'last': str(last), 'note': str(note)[:200], 'at': dt.datetime.now(KST).strftime('%Y-%m-%d %H:%M KST')}
    log(f'{"성공" if ok else "실패"} {name} 마지막 {last} {note}'[:260])


# ------------------------------------------------------------------ CFTC
CFTC_MAP = {'date': 'report_date_as_yyyy', 'code': 'cftc_contract_market_code', 'oi': 'open_interest_all',
            'dealer_long': 'dealer_positions_long', 'dealer_short': 'dealer_positions_short',
            'am_long': 'asset_mgr_positions_long', 'am_short': 'asset_mgr_positions_short',
            'lev_long': 'lev_money_positions_long', 'lev_short': 'lev_money_positions_short',
            'other_long': 'other_rept_positions_long', 'other_short': 'other_rept_positions_short',
            'small_long': 'nonrept_positions_long', 'small_short': 'nonrept_positions_short'}
CODES = {'13874A': 'ES', '209742': 'NQ'}


def cftc_norm(df):
    low = {c.lower().strip(): c for c in df.columns}
    out = pd.DataFrame()
    for k, pre in CFTC_MAP.items():
        hit = [c for lc, c in low.items() if lc.startswith(pre)]
        if not hit: raise RuntimeError(f'CFTC 열 없음: {pre} / {list(df.columns)[:12]}')
        out[k] = df[hit[0]]
    out['code'] = out['code'].astype(str).str.strip()
    out = out[out['code'].isin(CODES)].copy()
    out['mkt'] = out['code'].map(CODES)
    out['date'] = pd.to_datetime(out['date'].astype(str).str[:10]).dt.strftime('%Y-%m-%d')
    for c in out.columns:
        if c not in ('date', 'code', 'mkt'): out[c] = pd.to_numeric(out[c].astype(str).str.replace(',', ''), errors='coerce')
    return out.drop(columns='code')


def cftc():
    p = os.path.join(DATA, 'cftc.csv'); parts = []; note = ''
    try:
        url = 'https://publicreporting.cftc.gov/resource/gpe5-46if.csv'
        r = get(url, params={'$where': "cftc_contract_market_code in('13874A','209742')", '$limit': 50000, '$order': 'report_date_as_yyyy_mm_dd'}, timeout=120)
        parts.append(cftc_norm(pd.read_csv(io.StringIO(r.text), low_memory=False))); note = 'CFTC 공개 API'
    except Exception as e:
        log(f'CFTC API 실패 → 연도별 압축 파일로: {e!r}'[:200])
        urls = ['https://www.cftc.gov/files/dea/history/fin_fut_txt_2006_2016.zip'] + [f'https://www.cftc.gov/files/dea/history/fut_fin_txt_{y}.zip' for y in range(2017, dt.date.today().year + 1)]
        for u in urls:
            try:
                z = zipfile.ZipFile(io.BytesIO(get(u, timeout=120).content))
                for n in z.namelist(): parts.append(cftc_norm(pd.read_csv(z.open(n), low_memory=False)))
            except Exception as e2: log(f'  {u.rsplit("/", 1)[-1]} 실패 {e2!r}'[:160])
        note = 'CFTC 연도별 압축 파일'
    if not parts: return mark('cftc', False, note='API·압축 파일 모두 실패 — 기존 파일 유지')
    new = pd.concat(parts, ignore_index=True)
    if os.path.exists(p): new = pd.concat([pd.read_csv(p), new], ignore_index=True)
    new = new.drop_duplicates(['date', 'mkt'], keep='last').sort_values(['mkt', 'date'])
    new.to_csv(p, index=False); mark('cftc', True, new['date'].max(), f'{note} · {len(new)}행 · {new["date"].min()}~')


# ------------------------------------------------------------------ Cboe 풋/콜
PC_RATIO = {'pc_total': 'TOTAL PUT/CALL RATIO', 'pc_index': 'INDEX PUT/CALL RATIO', 'pc_etp': 'EXCHANGE TRADED PRODUCTS PUT/CALL RATIO',
            'pc_equity': 'EQUITY PUT/CALL RATIO', 'pc_vix': 'CBOE VOLATILITY INDEX (VIX) PUT/CALL RATIO'}
PC_SECT = {'all': 'SUM OF ALL PRODUCTS', 'idx': 'INDEX OPTIONS', 'eq': 'EQUITY OPTIONS', 'etp': 'EXCHANGE TRADED PRODUCTS'}
_SAMPLE = [0]


def num(v):
    try: return float(str(v).replace(',', ''))
    except Exception: return None


def cboe_day(d):
    """하루치 Cboe 일별 시장 통계(JSON). 휴장일·미공표는 None."""
    try:
        r = requests.get(f'https://cdn.cboe.com/data/us/options/market_statistics/daily/{d}_daily_options', headers={'User-Agent': UA}, timeout=30)
        if r.status_code != 200: return None
        js = r.json()
    except Exception:
        return None
    if not _SAMPLE[0]:
        _SAMPLE[0] = 1; log(f'Cboe 응답 보기 {d}: 키 {list(js.keys())[:14]}')
    row = {'date': d}
    rat = {str(x.get('name', '')).upper().strip(): num(x.get('value')) for x in js.get('ratios', []) if isinstance(x, dict)}
    for k, nm in PC_RATIO.items(): row[k] = rat.get(nm)
    row['pc_spx'] = next((v for n, v in rat.items() if n.startswith('SPX') and 'PUT/CALL' in n), None)
    for key, val in js.items():
        if not isinstance(val, list): continue
        ku = str(key).upper().strip()
        tag = next((t for t, nm in PC_SECT.items() if ku == nm), 'spx' if ku.startswith('SPX') else None)
        if not tag: continue
        for x in val:
            if not isinstance(x, dict): continue
            n = str(x.get('name', '')).upper()
            kind = 'vol' if n == 'VOLUME' else 'oi' if n == 'OPEN INTEREST' else None
            if kind: row[f'{tag}_{kind}_call'] = num(x.get('call')); row[f'{tag}_{kind}_put'] = num(x.get('put'))
    return row if row.get('pc_total') is not None else None


def cboe_archive():
    """2019-10 이전 이력(Cboe 가 올려 둔 옛 CSV). 파일마다 머리말 줄 수가 달라 'DATE' 로 시작하는 줄을 찾는다."""
    base = 'https://cdn.cboe.com/resources/options/volume_and_call_put_ratios/'
    out = None
    for col, fn in (('pc_total', 'totalpc.csv'), ('pc_index', 'indexpc.csv'), ('pc_equity', 'equitypc.csv'), ('pc_spx', 'spxpc.csv'), ('pc_etp', 'etppc.csv'), ('pc_vix', 'vixpc.csv')):
        try:
            txt = get(base + fn, tries=2).text
            lines = txt.splitlines(); i = next(k for k, s in enumerate(lines) if s.upper().replace(' ', '').startswith('DATE,'))
            df = pd.read_csv(io.StringIO('\n'.join(lines[i:])))
            df.columns = [c.strip().upper() for c in df.columns]
            rc = next(c for c in df.columns if 'RATIO' in c)
            d = pd.DataFrame({'date': pd.to_datetime(df['DATE'], errors='coerce').dt.strftime('%Y-%m-%d'), col: pd.to_numeric(df[rc], errors='coerce')}).dropna()
            if col == 'pc_total':
                cc = next((c for c in df.columns if c.startswith('CALL')), None); pc = next((c for c in df.columns if c.startswith('PUT')), None)
                if cc and pc: d['all_vol_call'] = pd.to_numeric(df[cc], errors='coerce'); d['all_vol_put'] = pd.to_numeric(df[pc], errors='coerce')
            out = d if out is None else out.merge(d, on='date', how='outer')
            log(f'  옛 이력 {fn}: {len(d)}행 {d["date"].min()}~{d["date"].max()}')
        except Exception as e: log(f'  옛 이력 {fn} 없음/실패: {e!r}'[:140])
    return out


def cboe_pc():
    p = os.path.join(DATA, 'cboe_pc.csv')
    have = pd.read_csv(p) if os.path.exists(p) else pd.DataFrame(columns=['date'])
    if len(have) == 0 or have['date'].min() > '2015-01-01':
        arc = cboe_archive()
        if arc is not None and len(arc): have = pd.concat([arc[arc['date'] < '2019-10-07'], have], ignore_index=True).drop_duplicates('date', keep='last')
    done = set(have['date'])
    end = dt.datetime.now(NY).date()
    days = [d.strftime('%Y-%m-%d') for d in pd.bdate_range('2019-10-07', end) if d.strftime('%Y-%m-%d') not in done]
    recent = [d for d in days if d >= (end - dt.timedelta(days=12)).strftime('%Y-%m-%d')]
    old = [d for d in days if d not in recent]
    skip_p = os.path.join(DATA, 'cboe_skip.txt')   # 휴장일 등 자료가 없는 옛 날짜 — 매번 다시 묻지 않게 적어 둔다
    skip = set(open(skip_p).read().split()) if os.path.exists(skip_p) else set()
    old = [d for d in old if d not in skip]
    rows = []; miss = []
    with cf.ThreadPoolExecutor(6) as ex:
        for d, r in zip(old + recent, ex.map(cboe_day, old + recent)):
            if r: rows.append(r)
            elif d in old: miss.append(d)
    if miss and rows:   # 한 건이라도 받았을 때만(전체 장애일 때 휴장일로 잘못 적지 않게)
        with open(skip_p, 'w') as f: f.write('\n'.join(sorted(skip | set(miss))))
    if rows: have = pd.concat([have, pd.DataFrame(rows)], ignore_index=True)
    if len(have) == 0: return mark('cboe_pc', False, note='일별 통계·옛 이력 모두 받지 못함')
    have = have.drop_duplicates('date', keep='last').sort_values('date')
    have.to_csv(p, index=False)
    mark('cboe_pc', bool(rows) or not days, have['date'].max(), f'새로 {len(rows)}일 · 전체 {len(have)}일 · {have["date"].min()}~' + ('' if rows or not days else ' · 이번에는 새 값 없음'))


# ------------------------------------------------------------------ VIX 기간구조
def vix():
    p = os.path.join(DATA, 'vix.csv'); out = None; bad = []
    for col, sym in (('vix9d', 'VIX9D'), ('vix', 'VIX'), ('vix3m', 'VIX3M'), ('vix6m', 'VIX6M'), ('vix1y', 'VIX1Y')):
        try:
            df = pd.read_csv(io.StringIO(get(f'https://cdn.cboe.com/api/global/us_indices/daily_prices/{sym}_History.csv').text))
            df.columns = [c.strip().upper() for c in df.columns]
            vc = 'CLOSE' if 'CLOSE' in df.columns else df.columns[-1]
            d = pd.DataFrame({'date': pd.to_datetime(df['DATE'], errors='coerce').dt.strftime('%Y-%m-%d'), col: pd.to_numeric(df[vc], errors='coerce')}).dropna()
            out = d if out is None else out.merge(d, on='date', how='outer')
        except Exception as e: bad.append(sym); log(f'  {sym} 실패 {e!r}'[:140])
    if out is None or 'vix' not in out: return mark('vix', False, note='Cboe 지수 이력 실패 — 기존 파일 유지')
    if os.path.exists(p):
        old = pd.read_csv(p); out = pd.concat([old[~old['date'].isin(out['date'])], out], ignore_index=True)
    out = out.sort_values('date'); out.to_csv(p, index=False)
    mark('vix', True, out['date'].max(), f'{len(out)}일' + (f' · 못 받음 {",".join(bad)}' if bad else ''))


# ------------------------------------------------------------------ 야후 일봉
YH = {'^GSPC': 'spx', '^NDX': 'ndx', 'QQQ': 'qqq', 'DIA': 'dia', 'ES=F': 'es', 'NQ=F': 'nq', '^KS200': 'k200y', '^KS11': 'kospiy', 'KRW=X': 'usdkrw'}
CUT = {'America/New_York': (16, 30), 'Asia/Seoul': (15, 50)}


def yahoo(sym):
    r = get(f'https://query1.finance.yahoo.com/v8/finance/chart/{requests.utils.quote(sym)}', params={'period1': 0, 'period2': int(time.time()) + 86400, 'interval': '1d'})
    res = r.json()['chart']['result'][0]; tz = ZoneInfo(res['meta'].get('exchangeTimezoneName') or 'America/New_York')
    now = dt.datetime.now(tz); today = now.strftime('%Y-%m-%d'); cut = CUT.get(str(tz), (23, 59))
    closed = now.hour * 60 + now.minute >= cut[0] * 60 + cut[1]
    q = res['indicators']['quote'][0]; rows = {}
    for i, t in enumerate(res.get('timestamp') or []):
        c = q['close'][i]
        if c is None: continue
        d = dt.datetime.fromtimestamp(t, tz).strftime('%Y-%m-%d')
        if d > today or (d == today and not closed): continue      # 끝나지 않은 날의 값은 종가로 쓰지 않는다
        if d in rows: continue                                      # 같은 날짜에 장중 봉이 하나 더 붙는 경우 첫 일봉만
        rows[d] = (q['open'][i], q['high'][i], q['low'][i], c)
    return pd.DataFrame([(d, YH[sym], *v) for d, v in rows.items()], columns=['date', 'sym', 'open', 'high', 'low', 'close'])


def px():
    p = os.path.join(DATA, 'px.csv'); parts = []; bad = []
    for s in YH:
        try: parts.append(yahoo(s)); time.sleep(0.5)
        except Exception as e: bad.append(s); log(f'  야후 {s} 실패 {e!r}'[:140])
    if not parts: return mark('px', False, note='야후 일봉 전부 실패 — 기존 파일 유지')
    new = pd.concat(parts, ignore_index=True)
    if os.path.exists(p):
        old = pd.read_csv(p); got = set(new['sym'])
        new = pd.concat([old[~old['sym'].isin(got)], new], ignore_index=True)   # 이번에 못 받은 종목은 기존 값 유지
    new = new.sort_values(['sym', 'date']); new.to_csv(p, index=False)
    last = new.groupby('sym')['date'].max().to_dict()
    mark('px', not bad, last.get('spx', ''), ' · '.join(f'{k} {v}' for k, v in sorted(last.items())) + (f' · 실패 {",".join(bad)}' if bad else ''))


def main():
    todo = sys.argv[1:] or ['cftc', 'cboe_pc', 'vix', 'px']
    for t in todo:
        try: {'cftc': cftc, 'cboe_pc': cboe_pc, 'vix': vix, 'px': px}[t]()
        except Exception as e: mark(t, False, note=repr(e))
    sp = os.path.join(DATA, 'status.json')
    old = json.load(open(sp, encoding='utf-8')) if os.path.exists(sp) else {}
    old.update(STATUS)
    json.dump(old, open(sp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
