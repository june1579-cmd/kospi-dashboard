# -*- coding: utf-8 -*-
"""자료 출처 시험 5차(2026-11-24) — 미국 옵션 미결제를 더 빨리 받을 수 있는지: OCC 시리즈 검색·FLEX 미결제 파일 내용, 야후 미결제 상태. KRX 로그인 안 씀."""
import os, time, traceback, datetime as dt
import requests
os.makedirs('out', exist_ok=True)
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36'}
out = [f'시각 {dt.datetime.utcnow():%Y-%m-%d %H:%M} UTC']
def head(label, url, **p):
    try:
        r = requests.get(url, headers=UA, params=p, timeout=60)
        t = r.text; lines = t.splitlines()
        out.append(f'\n== {label} HTTP {r.status_code} · {len(r.content)}바이트 · {len(lines)}줄 · type {r.headers.get("content-type")} · last-modified {r.headers.get("last-modified")}')
        out.extend('   ' + l[:220] for l in lines[:25])
        hit = [l for l in lines if ' 750 ' in l or '750.000' in l or '00750' in l][:6]
        if hit: out.append('   … 행사가 750 근처 줄:'); out.extend('   ' + l[:220] for l in hit)
    except Exception as e: out.append(f'\n== {label} 오류 {e!r}')
    time.sleep(1)
try:
    head('OCC 시리즈 검색 SPY', 'https://marketdata.theocc.com/series-search', symbolType='U', symbol='SPY')
    head('OCC FLEX 미결제 20261123 지수', 'https://marketdata.theocc.com/flex-reports', reportType='OI', optionType='I', reportDate='20261123')
    head('OCC 거래량 조회 SPY 20261123', 'https://marketdata.theocc.com/volume-query', reportDate='20261123', format='csv', volumeQueryType='O', symbolType='U', symbol='SPY', reportType='D', accountType='ALL', productKind='ALL', porc='BOTH')
    import yfinance as yf
    tk = yf.Ticker('SPY'); ch = tk.option_chain('2026-12-18')
    out.append(f"\n== 야후 SPY 12/18 미결제 합 콜 {int(ch.calls['openInterest'].fillna(0).sum())} 풋 {int(ch.puts['openInterest'].fillna(0).sum())} · 거래량 콜 {int(ch.calls['volume'].fillna(0).sum())}")
except Exception: out.append(traceback.format_exc())
open('out/g_occ.txt', 'w', encoding='utf-8').write('\n'.join(out))
