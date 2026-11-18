"""3차(해외) 일별 자료 — Yahoo(yfinance, 무료·비공식). KRX 로그인 없음.
저장: deriv/data/overseas_daily.csv (열: date, 종목코드별 종가). 날짜는 그 시장의 현지 거래일.
시각 맞춤은 analyze.py 에서 한다: 한국 t일 지표 = 그 종목의 현지 날짜 ≤ t 인 마지막 종가 기준 등락.
  미국 t일 종가(한국 t+1일 06~07시)는 한국 t일 종가 뒤·t+1일 시가 전에 나오므로 gap·oc·dir 모두 앞을 보지 않는다.
"""
import os

import pandas as pd
import yfinance as yf

ROOT = os.path.dirname(os.path.abspath(__file__))
TICK = {
    'ES=F': 'S&P500선물', 'NQ=F': '나스닥100선물', '^GSPC': 'S&P500', '^SOX': '필라델피아반도체', '^VIX': 'VIX',
    '^N225': '닛케이225', '^HSI': '항셍', '000001.SS': '상하이종합', '^TWII': '대만가권',
    'EWY': 'EWY(미국상장 한국ETF)', 'KRW=X': '원달러', 'DX-Y.NYB': '달러인덱스', '^TNX': '미국10년금리',
    'CL=F': 'WTI', 'GC=F': '금', 'HG=F': '구리',
}


def main():
    d = yf.download(list(TICK), start='2000-01-01', interval='1d', auto_adjust=False, progress=False, group_by='column', threads=True)
    c = d['Close'] if isinstance(d.columns, pd.MultiIndex) else d
    c = c.dropna(how='all'); c.index = pd.to_datetime(c.index).tz_localize(None).normalize(); c.index.name = 'date'
    # 미국 시간대 종목은 뉴욕 날짜로 오늘 행이 아직 장중 값일 수 있어 뺀다(확정 종가만 쓴다). 아시아 종목은 한국 18시 이후 실행이면 확정.
    ny_today = pd.Timestamp.now(tz='America/New_York').normalize().tz_localize(None)
    kst_now = pd.Timestamp.now(tz='Asia/Seoul')
    asia = {'^N225', '^HSI', '000001.SS', '^TWII'}
    for t in c.columns:
        if t in asia:
            if kst_now.hour < 18: c.loc[c.index >= kst_now.normalize().tz_localize(None), t] = float('nan')
        else:
            c.loc[c.index >= ny_today, t] = float('nan')
    c = c.dropna(how='all')
    os.makedirs(os.path.join(ROOT, 'data'), exist_ok=True)
    c.round(6).to_csv(os.path.join(ROOT, 'data', 'overseas_daily.csv'), encoding='utf-8')
    for t in TICK:
        s = c[t].dropna() if t in c else pd.Series(dtype=float)
        print(f'{t:10s} {TICK[t]:16s} {len(s):6d}행 {s.index.min().date() if len(s) else "-"} ~ {s.index.max().date() if len(s) else "-"}')


if __name__ == '__main__':
    main()
