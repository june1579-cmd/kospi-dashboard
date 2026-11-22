"""미국 선물·옵션·변동성·포지션 자료 수집(무료 공개 출처, KRX 로그인 없음) — GitHub Actions 에서만 돈다.
저장: deriv/us/data/*.csv(.gz). 날짜는 전부 그 시장(뉴욕) 현지 거래일. 한국 시각 맞춤은 us_features.py 에서 한다.
출처마다 따로 try — 한 곳이 막혀도 나머지는 받는다. 받은 결과는 deriv/us/out/collect_log.json 에 적는다(실패는 '확인 불가').
"""
import io
import json
import os
import sys
import time

import pandas as pd
import requests

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, 'data'); OUT = os.path.join(ROOT, 'out')
os.makedirs(DATA, exist_ok=True); os.makedirs(OUT, exist_ok=True)
UA = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36', 'Accept': '*/*'}
LOG = {}

YF = {'ES=F': 'S&P500 선물', 'NQ=F': '나스닥100 선물', 'RTY=F': '러셀2000 선물', '^GSPC': 'S&P500', '^NDX': '나스닥100', '^SOX': '필라델피아 반도체',
      '^VIX': 'VIX', '^VIX9D': 'VIX 9일', '^VIX3M': 'VIX 3개월', '^VIX6M': 'VIX 6개월', '^VVIX': 'VVIX', '^SKEW': 'SKEW',
      'EWY': 'EWY', 'SPY': 'SPY', 'QQQ': 'QQQ', 'HYG': 'HYG', 'KRW=X': '원달러', 'DX-Y.NYB': '달러 인덱스', '^TNX': '미국 10년 금리', 'VX=F': 'VIX 선물'}


def get(url, **kw):
    for i in range(3):
        try:
            r = requests.get(url, headers=UA, timeout=60, **kw)
            if r.status_code == 200: return r
            err = f'HTTP {r.status_code}'
        except Exception as e:
            err = repr(e)[:150]
        time.sleep(3 + 4 * i)
    raise RuntimeError(err)


def note(name, df=None, err=None, date_col='date'):
    if err is not None:
        LOG[name] = {'ok': False, 'err': str(err)[:300]}; print('실패', name, err, flush=True); return
    d = pd.to_datetime(df[date_col])
    LOG[name] = {'ok': True, 'rows': int(len(df)), 'from': str(d.min().date()), 'to': str(d.max().date())}
    print('받음', name, LOG[name], flush=True)


def yf_daily():
    import yfinance as yf
    d = yf.download(list(YF), start='2005-01-01', interval='1d', auto_adjust=False, progress=False, group_by='ticker', threads=True)
    ny_today = pd.Timestamp.now(tz='America/New_York').normalize().tz_localize(None)
    rows = []
    for t in YF:
        try:
            x = d[t][['Open', 'High', 'Low', 'Close', 'Volume']].dropna(subset=['Close']).copy()
        except Exception:
            continue
        x.index = pd.to_datetime(x.index).tz_localize(None).normalize()
        x = x[x.index < ny_today]   # 뉴욕 오늘 행은 장중일 수 있어 뺌(확정 종가만)
        x.columns = ['open', 'high', 'low', 'close', 'volume']; x['ticker'] = t; x.index.name = 'date'
        rows.append(x.reset_index())
    A = pd.concat(rows, ignore_index=True)
    p = os.path.join(DATA, 'us_ohlc.csv.gz')
    if os.path.exists(p):   # 야후가 이번에 빠뜨린 종목·날짜는 전에 받은 값으로 지킴
        A = pd.concat([pd.read_csv(p, parse_dates=['date']), A]).drop_duplicates(['date', 'ticker'], keep='last').sort_values(['ticker', 'date'])
    A.round(6).to_csv(p, index=False)
    note('yahoo_daily', A)
    LOG['yahoo_daily']['tickers'] = {t: [int((A.ticker == t).sum()), str(A[A.ticker == t].date.min().date()) if (A.ticker == t).any() else None] for t in YF}


def yf_hourly():
    """선물 1시간 봉(야후는 최근 약 730일만) — 한국 장 마감(15:30 KST) 뒤 미국 선물 움직임 계산용."""
    import yfinance as yf
    rows = []
    for t in ('ES=F', 'NQ=F'):
        h = yf.download(t, period='729d', interval='1h', auto_adjust=False, progress=False)
        if isinstance(h.columns, pd.MultiIndex): h.columns = h.columns.get_level_values(0)
        h = h[['Open', 'High', 'Low', 'Close']].dropna(); h.index = pd.to_datetime(h.index, utc=True).tz_convert('Asia/Seoul').tz_localize(None)
        h.columns = ['open', 'high', 'low', 'close']; h['ticker'] = t; h.index.name = 'kst'; rows.append(h.reset_index())
    A = pd.concat(rows, ignore_index=True)
    p = os.path.join(DATA, 'us_fut_hourly.csv.gz')
    if os.path.exists(p):   # 야후가 지우는 옛 구간을 지키려고 이어 붙임
        old = pd.read_csv(p, parse_dates=['kst']); A = pd.concat([old, A]).drop_duplicates(['kst', 'ticker'], keep='last').sort_values(['ticker', 'kst'])
    A.round(4).to_csv(p, index=False); note('yahoo_hourly', A, date_col='kst')


def cboe_index():
    rows = []
    for s in ('VIX', 'VIX9D', 'VIX3M', 'VIX6M', 'VVIX', 'SKEW', 'VIX1D', 'PUT', 'BXM'):
        try:
            r = get(f'https://cdn.cboe.com/api/global/us_indices/daily_prices/{s}_History.csv')
            x = pd.read_csv(io.StringIO(r.text)); x.columns = [c.strip().upper() for c in x.columns]
            x['date'] = pd.to_datetime(x['DATE']); v = x['CLOSE'] if 'CLOSE' in x else x[x.columns[-1]]
            rows.append(pd.DataFrame({'date': x['date'], 'sym': s, 'close': pd.to_numeric(v, errors='coerce')}))
        except Exception as e:
            LOG[f'cboe_index_{s}'] = {'ok': False, 'err': repr(e)[:200]}
    A = pd.concat(rows, ignore_index=True).dropna()
    A.to_csv(os.path.join(DATA, 'cboe_index.csv.gz'), index=False); note('cboe_index', A)
    LOG['cboe_index']['syms'] = {s: [int(n), str(A[A.sym == s].date.min().date()), str(A[A.sym == s].date.max().date())] for s, n in A.sym.value_counts().items()}


def cboe_pcr_archive():
    """Cboe 풋콜 비율 옛 보관 파일(~2019-10)."""
    rows = []
    for k in ('totalpc', 'equitypc', 'indexpc', 'vixpc', 'etppc'):
        try:
            r = get(f'https://cdn.cboe.com/resources/options/volume_and_call_put_ratios/{k}.csv')
            lines = r.text.splitlines(); i = next(j for j, l in enumerate(lines) if l.upper().startswith(('DATE', 'TRADE_DATE')))
            x = pd.read_csv(io.StringIO('\n'.join(lines[i:]))); x.columns = [c.strip().upper() for c in x.columns]
            dc = 'DATE' if 'DATE' in x else 'TRADE_DATE'
            rc = [c for c in x.columns if 'RATIO' in c][0]
            y = pd.DataFrame({'date': pd.to_datetime(x[dc], errors='coerce'), 'kind': k, 'pcr': pd.to_numeric(x[rc], errors='coerce'),
                              'call': pd.to_numeric(x.get('CALL', x.get('CALLS')), errors='coerce'), 'put': pd.to_numeric(x.get('PUT', x.get('PUTS')), errors='coerce')})
            rows.append(y.dropna(subset=['date', 'pcr']))
        except Exception as e:
            LOG[f'cboe_pcr_archive_{k}'] = {'ok': False, 'err': repr(e)[:200]}
    A = pd.concat(rows, ignore_index=True)
    A.to_csv(os.path.join(DATA, 'cboe_pcr_archive.csv.gz'), index=False); note('cboe_pcr_archive', A)
    LOG['cboe_pcr_archive']['kinds'] = {k: [int(n), str(A[A.kind == k].date.min().date()), str(A[A.kind == k].date.max().date())] for k, n in A.kind.value_counts().items()}


def cboe_pcr_daily(max_new=400):
    """Cboe 일별 시장 통계(2019-10~) — 날짜별 JSON. 이미 받은 날은 건너뛰고, 한 번에 max_new 일까지만(천천히)."""
    p = os.path.join(DATA, 'cboe_pcr_daily.csv.gz')
    old = pd.read_csv(p, parse_dates=['date']) if os.path.exists(p) else pd.DataFrame(columns=['date', 'name', 'value'])
    old['date'] = pd.to_datetime(old['date'])
    have = set(old['date'].dt.strftime('%Y-%m-%d'))
    ny = pd.Timestamp.now(tz='America/New_York').normalize().tz_localize(None)
    days = [d for d in pd.bdate_range('2019-10-01', ny - pd.Timedelta(days=1)) if d.strftime('%Y-%m-%d') not in have][::-1]
    rows, miss, first_err = [], 0, None
    for d in days[:max_new]:
        ds = d.strftime('%Y-%m-%d')
        try:
            r = requests.get(f'https://cdn.cboe.com/data/us/options/market_statistics/daily/{ds}_daily_options', headers=UA, timeout=40)
            if r.status_code != 200:
                miss += 1; first_err = first_err or f'{ds} HTTP {r.status_code}'
                if miss >= 15 and not rows: break
                continue
            j = r.json()
            for it in j.get('ratios', []):
                rows.append({'date': d, 'name': it.get('name'), 'value': pd.to_numeric(it.get('value'), errors='coerce')})
        except Exception as e:
            miss += 1; first_err = first_err or f'{ds} {repr(e)[:120]}'
        time.sleep(0.35)
    A = pd.concat([old, pd.DataFrame(rows)], ignore_index=True) if rows else old
    if len(A):
        A.drop_duplicates(['date', 'name'], keep='last').sort_values(['date', 'name']).to_csv(p, index=False); note('cboe_pcr_daily', A)
        LOG['cboe_pcr_daily'].update({'new_days': len({r['date'] for r in rows}), 'miss': miss, 'first_err': first_err, 'left': max(0, len(days) - max_new),
                                      'names': sorted(set(A['name'].dropna()))[:20]})
    else:
        note('cboe_pcr_daily', err=first_err or '행 없음')


# SqueezeMetrics(GEX·DIX)는 받지 않는다 — 이용 약관이 자동 수집·자료 쌓기를 허락 없이 금지(2026-11-22 확인). 감마 노출은 옵션 체인 스냅숏으로 직접 계산해 날마다 쌓는다.


def cftc():
    """CFTC 금융선물 투자자별 포지션(TFF, 선물만). 화요일 기준·금요일 15:30(뉴욕) 공개."""
    codes = "('13874A','209742','1170E1','239742','240741')"
    url = 'https://publicreporting.cftc.gov/resource/gpe5-46if.json'
    rows, off = [], 0
    while True:
        r = get(url, params={'$where': f'cftc_contract_market_code in {codes}', '$limit': 50000, '$offset': off, '$order': 'report_date_as_yyyy_mm_dd'})
        j = r.json(); rows += j
        if len(j) < 50000: break
        off += 50000
    x = pd.DataFrame(rows)
    keep = ['report_date_as_yyyy_mm_dd', 'cftc_contract_market_code', 'market_and_exchange_names', 'open_interest_all',
            'dealer_positions_long_all', 'dealer_positions_short_all', 'asset_mgr_positions_long', 'asset_mgr_positions_short',
            'lev_money_positions_long', 'lev_money_positions_short', 'other_rept_positions_long', 'other_rept_positions_short',
            'nonrept_positions_long_all', 'nonrept_positions_short_all']
    LOG['cftc_cols'] = [c for c in x.columns][:80]
    x = x[[c for c in keep if c in x.columns]].copy(); x['date'] = pd.to_datetime(x['report_date_as_yyyy_mm_dd']).dt.normalize()
    x.drop(columns=['report_date_as_yyyy_mm_dd']).to_csv(os.path.join(DATA, 'cftc_tff.csv.gz'), index=False); note('cftc_tff', x)
    LOG['cftc_tff']['codes'] = x['cftc_contract_market_code'].value_counts().to_dict()


def cboe_chain():
    """Cboe 지연 시세(약 15분) 옵션 전 종목 스냅숏 — 지금 시점만 있고 과거는 없다. 날마다 요약(행사가별 미결제·감마)을 쌓는다."""
    out = []
    for sym, u in (('SPX', '_SPX'), ('SPY', 'SPY'), ('QQQ', 'QQQ'), ('NDX', '_NDX'), ('VIX', '_VIX')):
        try:
            j = get(f'https://cdn.cboe.com/api/global/delayed_quotes/options/{u}.json').json()
            d = j['data']; spot = d.get('current_price') or d.get('close'); ts = j.get('timestamp')
            o = pd.DataFrame(d['options'])
            # 옵션 기호: 루트 + YYMMDD + C/P + 행사가×1000(8자리)
            s = o['option'].str.extract(r'^(?P<root>[A-Z]+)(?P<exp>\d{6})(?P<cp>[CP])(?P<k>\d{8})$')
            o = o.join(s); o['K'] = o['k'].astype(float) / 1000; o['exp'] = pd.to_datetime(o['exp'], format='%y%m%d')
            o = o[['root', 'exp', 'cp', 'K', 'open_interest', 'volume', 'iv', 'delta', 'gamma', 'bid', 'ask']]
            o['sym'] = sym; o['spot'] = spot; o['ts'] = ts
            o.to_csv(os.path.join(DATA, f'chain_now_{sym}.csv.gz'), index=False)
            out.append({'sym': sym, 'rows': int(len(o)), 'spot': spot, 'ts': ts, 'oi': float(o['open_interest'].sum())})
        except Exception as e:
            out.append({'sym': sym, 'err': repr(e)[:200]})
    if not any('rows' in x for x in out):   # Cboe 가 막으면 야후 옵션 체인(SPY·QQQ, 가까운 만기 8개)으로 대신 — 감마는 us_dash 에서 계산
        import yfinance as yf
        for sym in ('SPY', 'QQQ'):
            try:
                tk = yf.Ticker(sym); spot = float(tk.history(period='5d')['Close'].iloc[-1]); rows = []
                for e in list(tk.options)[:8]:
                    ch = tk.option_chain(e)
                    for cp, x in (('C', ch.calls), ('P', ch.puts)):
                        rows.append(pd.DataFrame({'root': sym, 'exp': pd.Timestamp(e), 'cp': cp, 'K': x['strike'], 'open_interest': x['openInterest'], 'volume': x['volume'],
                                                  'iv': x['impliedVolatility'], 'delta': float('nan'), 'gamma': float('nan'), 'bid': x['bid'], 'ask': x['ask']}))
                    time.sleep(0.5)
                o = pd.concat(rows, ignore_index=True); o['sym'] = sym; o['spot'] = spot; o['ts'] = pd.Timestamp.now(tz='America/New_York').strftime('%Y-%m-%d %H:%M ET(야후)')
                o.to_csv(os.path.join(DATA, f'chain_now_{sym}.csv.gz'), index=False)
                out.append({'sym': sym, 'src': 'yahoo', 'rows': int(len(o)), 'spot': spot, 'oi': float(o['open_interest'].sum())})
            except Exception as e:
                out.append({'sym': sym, 'src': 'yahoo', 'err': repr(e)[:200]})
    LOG['cboe_chain'] = {'ok': any('rows' in x for x in out), 'items': out}; print('옵션 스냅숏', out, flush=True)


STEPS = {'yf': yf_daily, 'yfh': yf_hourly, 'idx': cboe_index, 'pcra': cboe_pcr_archive, 'pcrd': cboe_pcr_daily, 'cftc': cftc, 'chain': cboe_chain}

if __name__ == '__main__':
    want = sys.argv[1:] or list(STEPS)
    for k in want:
        try:
            STEPS[k]()
        except Exception as e:
            note(k, err=repr(e))
    LOG['at_kst'] = pd.Timestamp.now(tz='Asia/Seoul').strftime('%Y-%m-%d %H:%M')
    json.dump(LOG, open(os.path.join(OUT, 'collect_log.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=str)
