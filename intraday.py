"""장중 분봉 매일 쌓기 — intraday-data 가지 전용(대시보드·KRX 계정과 무관).

출처(2026-11-18 실측)
  yahoo : ^KS11(코스피) ^KS200(코스피200) — 1분봉 최근 약 30일(8일씩 나눠 요청), 5분봉 약 60거래일, 1시간봉 약 2년. 비공식 공개 경로.
  naver : 코스피·코스피200·코스닥 지수, 코스피200 선물(근월물, 주간 08:45~15:45) 1분봉 — 최근 6거래일. 비공식 공개 경로.
  kis   : 한국투자증권 Open API(공식, 무료, 계좌 필요) — 비밀값 KIS_APP_KEY·KIS_APP_SECRET 이 있으면 켜짐.
          지수·선물 주간/야간 분봉, 시장별 투자자 시간대별. 키가 없으면 건너뛰고 기록만 남김.
저장: intraday/<출처>_<종목>_<간격>/<YYYY-MM>.csv.gz — 날짜시각(KST) 기준 중복 제거, 기존 행은 덮지 않고 새 행만 더함.
실행: python intraday.py daily | backfill
"""
import datetime as dt
import gzip
import io
import json
import os
import sys
import time

import pandas as pd
import requests

KST = dt.timezone(dt.timedelta(hours=9))
ROOT = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.join(ROOT, 'intraday')
LOG = []
UA = {'User-Agent': 'Mozilla/5.0 (research; daily minute archive)'}


def log(m):
    s = f'[{dt.datetime.now(KST):%Y-%m-%d %H:%M:%S}] {m}'; print(s, flush=True); LOG.append(s)


def store(df, src, sym, iv):
    """df: 열 ts(KST, tz 없는 'YYYY-MM-DD HH:MM'), open high low close volume. 월별 파일에 새 행만 더한다."""
    if df is None or not len(df): return 0
    df = df.dropna(subset=['ts', 'close']).copy()
    df['ts'] = pd.to_datetime(df['ts']).dt.strftime('%Y-%m-%d %H:%M')
    d = os.path.join(BASE, f'{src}_{sym}_{iv}'.replace('^', '').replace('/', '-'))
    os.makedirs(d, exist_ok=True); added = 0
    for ym, g in df.groupby(df['ts'].str[:7]):
        p = os.path.join(d, f'{ym}.csv.gz')
        old = pd.read_csv(p) if os.path.exists(p) else pd.DataFrame(columns=g.columns)
        new = g[~g['ts'].isin(set(old['ts']))]
        if not len(new): continue
        out = pd.concat([old, new], ignore_index=True).sort_values('ts')
        with gzip.open(p, 'wt', encoding='utf-8') as f: out.to_csv(f, index=False)
        added += len(new)
    log(f'{src} {sym} {iv}: 새 행 {added}')
    return added


# ---------------------------------------------------------------- Yahoo
def yahoo(sym, iv, days):
    import yfinance as yf
    end = dt.datetime.now(dt.timezone.utc); parts = []
    step = 7 if iv == '1m' else days
    s = end - dt.timedelta(days=days)
    while s < end:
        e = min(s + dt.timedelta(days=step), end)
        try:
            d = yf.download(sym, interval=iv, start=s, end=e, progress=False, auto_adjust=False)
            if len(d):
                if isinstance(d.columns, pd.MultiIndex): d.columns = d.columns.get_level_values(0)
                d = d.rename(columns=str.lower)
                idx = d.index.tz_convert('Asia/Seoul') if d.index.tz is not None else d.index.tz_localize('UTC').tz_convert('Asia/Seoul')
                parts.append(pd.DataFrame({'ts': idx.tz_localize(None), 'open': d['open'].values, 'high': d['high'].values, 'low': d['low'].values,
                                           'close': d['close'].values, 'volume': d['volume'].values}))
        except Exception as ex: log(f'yahoo {sym} {iv} {s:%m-%d} 실패: {ex!r}'[:200])
        s = e; time.sleep(1)
    return pd.concat(parts, ignore_index=True) if parts else None


# ---------------------------------------------------------------- Naver
NAVER = [('index', 'KOSPI'), ('index', 'KPI200'), ('index', 'KOSDAQ'), ('futures', 'FUT')]


def naver(kind, code, days=10):
    end = dt.datetime.now(KST); start = end - dt.timedelta(days=days)
    u = f'https://api.stock.naver.com/chart/domestic/{kind}/{code}/minute?startDateTime={start:%Y%m%d}0000&endDateTime={end:%Y%m%d}2359'
    r = requests.get(u, headers=UA, timeout=40); r.raise_for_status(); d = r.json()
    if not isinstance(d, list) or not d: return None
    df = pd.DataFrame(d)
    ts = pd.to_datetime(df['localDateTime'], format='%Y%m%d%H%M%S')
    # 누적 거래량 → 1분 거래량(같은 날 안에서 차분)
    vol = df['accumulatedTradingVolume'].astype(float)
    day = ts.dt.date
    v1 = vol.groupby(day).diff().fillna(vol)
    return pd.DataFrame({'ts': ts, 'open': df['openPrice'], 'high': df['highPrice'], 'low': df['lowPrice'], 'close': df['currentPrice'], 'volume': v1, 'cum_volume': vol})


# ---------------------------------------------------------------- KIS(키가 있을 때만)
def kis():
    k, s = os.environ.get('KIS_APP_KEY'), os.environ.get('KIS_APP_SECRET')
    if not (k and s):
        log('kis: 비밀값(KIS_APP_KEY·KIS_APP_SECRET) 없음 — 건너뜀'); return
    base = 'https://openapi.koreainvestment.com:9443'
    tok_p = os.path.join(BASE, '.kis_token.json')   # 저장소에 올리지 않음(.gitignore)
    tok = None
    if os.path.exists(tok_p):
        t = json.load(open(tok_p))
        if t.get('exp', 0) > time.time() + 600: tok = t['tok']
    if not tok:
        r = requests.post(base + '/oauth2/tokenP', json={'grant_type': 'client_credentials', 'appkey': k, 'appsecret': s}, timeout=30)
        j = r.json(); tok = j.get('access_token')
        if not tok: log(f'kis 토큰 실패: {str(j)[:150]}'); return
        json.dump({'tok': tok, 'exp': time.time() + 23 * 3600}, open(tok_p, 'w'))
    H = {'authorization': f'Bearer {tok}', 'appkey': k, 'appsecret': s, 'custtype': 'P'}

    def fut_minutes(code, mkt, date):
        """선물 분봉(FHKIF03020200): 기준 시각부터 과거로 최대 102개씩. mkt: F 주간, CM 야간."""
        rows, hour = [], '235959'
        for _ in range(20):
            p = {'FID_COND_MRKT_DIV_CODE': mkt, 'FID_INPUT_ISCD': code, 'FID_HOUR_CLS_CODE': '60', 'FID_PW_DATA_INCU_YN': 'Y',
                 'FID_FAKE_TICK_INCU_YN': 'N', 'FID_INPUT_DATE_1': date, 'FID_INPUT_HOUR_1': hour}
            r = requests.get(base + '/uapi/domestic-futureoption/v1/quotations/inquire-time-fuopchartprice', headers=dict(H, tr_id='FHKIF03020200'), params=p, timeout=30)
            j = r.json(); out = j.get('output2') or []
            out = [o for o in out if o.get('stck_cntg_hour')]
            if not out: break
            rows += out; last = out[-1]
            if last.get('stck_bsop_date') != date: break
            hour = last['stck_cntg_hour']; time.sleep(0.12)
            if len(out) < 100: break
        return rows

    today = dt.datetime.now(KST).strftime('%Y%m%d')
    code = os.environ.get('KIS_FUT_CODE', '101000')   # 근월물 코드는 종목 마스터로 바꿔 넣는다(아래 note)
    for mkt, nm in (('F', 'day'), ('CM', 'night')):
        try:
            rows = fut_minutes(code, mkt, today)
            if rows:
                df = pd.DataFrame(rows)
                store(pd.DataFrame({'ts': pd.to_datetime(df['stck_bsop_date'] + df['stck_cntg_hour'], format='%Y%m%d%H%M%S'),
                                    'open': pd.to_numeric(df.get('futs_oprc')), 'high': pd.to_numeric(df.get('futs_hgpr')), 'low': pd.to_numeric(df.get('futs_lwpr')),
                                    'close': pd.to_numeric(df.get('futs_prpr')), 'volume': pd.to_numeric(df.get('cntg_vol'))}), 'kis', f'K200F_{nm}', '1m')
            else: log(f'kis 선물 {nm}: 행 없음')
        except Exception as ex: log(f'kis 선물 {nm} 실패: {ex!r}'[:200])


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else 'daily'
    log(f'시작 {mode}')
    ylist = [('1m', 30 if mode == 'backfill' else 8)] + ([('5m', 59), ('60m', 729)] if mode == 'backfill' else [('5m', 10), ('60m', 10)])
    for sym in ('^KS11', '^KS200'):
        for iv, days in ylist:
            try: store(yahoo(sym, iv, days), 'yahoo', sym, iv)
            except Exception as ex: log(f'yahoo {sym} {iv} 실패: {ex!r}'[:200])
    for kind, code in NAVER:
        try: store(naver(kind, code), 'naver', code, '1m'); time.sleep(1)
        except Exception as ex: log(f'naver {code} 실패: {ex!r}'[:200])
    kis()
    os.makedirs(BASE, exist_ok=True)
    with open(os.path.join(BASE, 'log.txt'), 'a', encoding='utf-8') as f: f.write('\n'.join(LOG) + '\n')
    # 보관 현황
    rows = []
    for d in sorted(os.listdir(BASE)):
        p = os.path.join(BASE, d)
        if not os.path.isdir(p): continue
        fs = sorted(os.listdir(p)); n = 0; first = last = ''
        for f in fs:
            x = pd.read_csv(os.path.join(p, f)); n += len(x)
            first = first or x['ts'].min(); last = x['ts'].max()
        rows.append({'계열': d, '행수': n, '처음': first, '끝': last, '파일수': len(fs)})
    pd.DataFrame(rows).to_csv(os.path.join(BASE, 'coverage.csv'), index=False, encoding='utf-8')
    print(pd.DataFrame(rows).to_string())


if __name__ == '__main__':
    main()
