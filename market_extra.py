# -*- coding: utf-8 -*-
"""market_extra.py — 커넥터 검증(2026-11-20)에서 도움이 확인된 보조 수집. 본 파이프라인(run_pipeline.py)과 따로 돈다.
   이 단계가 실패해도 본 갱신·카톡에는 영향이 없다(워크플로에서 continue-on-error).

 1) 밤사이 미국장
    - 야후(키 불필요): 필라델피아 반도체(^SOX)·S&P500(^GSPC)·S&P500 선물(ES=F)·VIX(^VIX)
    - Twelve Data(비밀값 TWELVEDATA_API_KEY 가 있을 때만): SOXX·SPY·QQQ ETF, 원달러(USD/KRW) — 야후 대조·예비
      (Twelve Data 는 지수 자체를 주지 않아 ETF 로 받는다. 무료 한도 하루 800회 — 한 번 실행에 4회 사용)
    → out/overnight.csv 에 누적(뉴욕 장이 끝난 날만).
    → 아침(0831) 실행에서 카톡이 나가는 경우에만 '밤사이 미국' 한 통을 덧붙이고, report/latest.md 에 절을 추가한다.
      해석 근거: out/overnight_stats.csv (2015~2026 검증 — 미국 반도체 하락 하위 5% 밤의 다음 날 코스피 갭하락 87%)

 2) 급락일 뉴스(비밀값 TAVILY_API_KEY 가 있을 때만)
    - 코스피 종가 −3% 이하인 날, 잠정·확정(1540·1840) 실행에서 'OO월 OO일 코스피 급락 속 상승 종목 이유'를 검색해
      out/crash_news_auto.csv 에 누적(날짜마다 한 번). --crash-backfill N 으로 지난 급락일 N개를 채운다.
    - out/crash_news.csv 는 Claude 가 Tavily 커넥터로 모아 종목·이유를 정리한 표(2026-11-20 시작).

 원자료를 추정으로 채우지 않는다 — 못 받은 값은 '확인 불가'로 둔다.
 사용: python market_extra.py --tag 0831 [--no-kakao] [--crash-backfill 6]
"""
import argparse, datetime as dt, json, os, sys
import pandas as pd, requests
from zoneinfo import ZoneInfo

KST, NY = ZoneInfo('Asia/Seoul'), ZoneInfo('America/New_York')
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36'
OUT = 'out'
OV_CSV, STATS_CSV, NEWS_AUTO = f'{OUT}/overnight.csv', f'{OUT}/overnight_stats.csv', f'{OUT}/crash_news_auto.csv'
YAHOO = {'^SOX': '필라델피아 반도체', '^GSPC': 'S&P500', 'ES=F': 'S&P500 선물', '^VIX': 'VIX'}
TD = {'SOXX': '반도체 ETF(SOXX)', 'SPY': 'S&P500 ETF(SPY)', 'QQQ': '나스닥100 ETF(QQQ)', 'USD/KRW': '원달러'}

def log(m): print(f'[{dt.datetime.now(KST):%H:%M:%S}] {m}', flush=True)

def ny_done(d):
    """뉴욕 날짜 d 의 장이 끝났는지(16:30 이후) — 끝나지 않은 날의 값은 종가로 쓰지 않는다."""
    now = dt.datetime.now(NY)
    return d < now.strftime('%Y-%m-%d') or (d == now.strftime('%Y-%m-%d') and now.hour * 60 + now.minute >= 16 * 60 + 30)

def fetch_yahoo(sym):
    r = requests.get(f'https://query1.finance.yahoo.com/v8/finance/chart/{requests.utils.quote(sym)}',
                     params={'range': '3mo', 'interval': '1d'}, headers={'User-Agent': UA}, timeout=30)
    res = r.json()['chart']['result'][0]
    rows = []
    for t, c in zip(res['timestamp'], res['indicators']['quote'][0]['close']):
        if c is None: continue
        d = dt.datetime.fromtimestamp(t, NY).strftime('%Y-%m-%d')
        if ny_done(d) and not (rows and rows[-1][0] == d): rows.append((d, float(c)))   # 선물은 같은 날짜에 장중 봉이 하나 더 붙는다 — 날짜마다 첫 일봉(정산가)만 쓴다
    # 야후는 마지막 날 일봉 종가를 비워 두는 때가 있다(2026-11-19 CRWV 확인) — 같은 응답의 정규장 마감 가격으로 채운다
    m = res.get('meta', {})
    if m.get('regularMarketPrice') and m.get('regularMarketTime'):
        mt = dt.datetime.fromtimestamp(m['regularMarketTime'], NY); md_ = mt.strftime('%Y-%m-%d')
        if mt.hour >= 16 and ny_done(md_) and (not rows or rows[-1][0] < md_): rows.append((md_, float(m['regularMarketPrice'])))
    return rows

def fetch_td(sym, key, size):
    r = requests.get('https://api.twelvedata.com/time_series',
                     params={'symbol': sym, 'interval': '1day', 'outputsize': size, 'apikey': key}, timeout=30)
    js = r.json()
    if js.get('status') == 'error': raise RuntimeError(js.get('message', 'error')[:120])
    rows = [(v['datetime'][:10], float(v['close'])) for v in js.get('values', [])]
    return [x for x in rows if sym == 'USD/KRW' or ny_done(x[0])]

def collect_overnight():
    old = pd.read_csv(OV_CSV, dtype=str) if os.path.exists(OV_CSV) else pd.DataFrame(columns=['date', 'symbol', 'name', 'close', 'source'])
    new, fails = [], []
    for s, nm in YAHOO.items():
        try:
            for d, c in fetch_yahoo(s): new.append({'date': d, 'symbol': s, 'name': nm, 'close': round(c, 4), 'source': 'Yahoo Finance'})
        except Exception as e: fails.append(f'야후 {s}: {repr(e)[:80]}')
    key = os.environ.get('TWELVEDATA_API_KEY', '').strip()
    if key:
        have_td = old['source'].eq('Twelve Data').any() if len(old) else False
        for s, nm in TD.items():
            try:
                for d, c in fetch_td(s, key, 30 if have_td else 5000):   # 처음 한 번은 과거 전체(최대 5000일)를 채운다
                    new.append({'date': d, 'symbol': s, 'name': nm, 'close': round(c, 4), 'source': 'Twelve Data'})
            except Exception as e: fails.append(f'Twelve Data {s}: {repr(e)[:80]}')
    else:
        log('TWELVEDATA_API_KEY 없음 — Twelve Data 대조·예비는 건너뜀(야후만)')
    df = pd.concat([old, pd.DataFrame(new, dtype=str)], ignore_index=True)
    df = df.drop_duplicates(['date', 'symbol', 'source'], keep='last').sort_values(['symbol', 'source', 'date'])
    df['close'] = pd.to_numeric(df['close'], errors='coerce')
    df['chg_pct'] = (df.groupby(['symbol', 'source'])['close'].pct_change() * 100).round(2)
    df[['date', 'symbol', 'name', 'close', 'chg_pct', 'source']].to_csv(OV_CSV, index=False, encoding='utf-8')
    for f in fails: log('실패 ' + f)
    log(f'밤사이 미국장 {len(new)}행 수집 → {OV_CSV} (총 {len(df)}행)')
    return df, fails

def last_session(df):
    """가장 최근에 끝난 미국 거래일의 등락. 야후 우선, 없으면 Twelve Data ETF(같은 지수를 따르는 ETF)로 대신하고 그렇게 적는다."""
    out = {}
    pick = {'^SOX': ('^SOX', 'SOXX'), '^GSPC': ('^GSPC', 'SPY'), '^VIX': ('^VIX', None)}
    for k, (y, t) in pick.items():
        a = df[(df.symbol == y) & (df.source == 'Yahoo Finance')].dropna(subset=['chg_pct'])
        if len(a): r = a.iloc[-1]; out[k] = (r['date'], float(r['close']), float(r['chg_pct']), '야후'); continue
        if t:
            b = df[(df.symbol == t) & (df.source == 'Twelve Data')].dropna(subset=['chg_pct'])
            if len(b): r = b.iloc[-1]; out[k] = (r['date'], float(r['close']), float(r['chg_pct']), f'Twelve Data {t}')
    return out

def sgn(v): return ('+' if v > 0 else '−' if v < 0 else '±') + f'{abs(v):.2f}%'

def overnight_text(df, today):
    ls = last_session(df)
    if '^SOX' not in ls and '^GSPC' not in ls: return None, None
    st = pd.read_csv(STATS_CSV).set_index('src') if os.path.exists(STATS_CSV) else None
    us_d = (ls.get('^SOX') or ls.get('^GSPC'))[0]
    part = []
    if '^SOX' in ls: part.append(f"반도체 {sgn(ls['^SOX'][2])}")
    else: part.append('반도체 확인 불가')
    if '^GSPC' in ls: part.append(f"S&P {sgn(ls['^GSPC'][2])}")
    if '^VIX' in ls: part.append(f"VIX {ls['^VIX'][1]:.1f}")
    lines = [f"[{int(today[5:7])}/{int(today[8:10])} 밤사이 미국 {int(us_d[5:7])}/{int(us_d[8:10])}]", ' · '.join(part)]
    note = ''
    if st is not None and '^SOX' in ls and '^SOX' in st.index:
        s = st.loc['^SOX']; v = ls['^SOX'][2]
        if v <= float(s['worst5pct_thr']):
            note = f"반도체 하위5% 밤({sgn(float(s['worst5pct_thr']))} 이하) 다음날: 갭하락 {s['worst5_gap_down']:.0f}%·하락마감 {s['worst5_ret_down']:.0f}%"
        else:
            note = f"반도체 방향=코스피 시가 방향 {s['hit_gap']:.0f}%(종가는 {s['hit_ret']:.0f}%)"
        lines.append(note + ' (2015~)')
    src = sorted({v[3] for v in ls.values()})
    msg = '\n'.join(lines)
    md = ['', '## 밤사이 미국장 (보조 수집)', '',
          f"- 미국 거래일 {us_d}: " + ' · '.join(part) + f" (출처: {', '.join(src)})",
          f"- {note} — 근거 out/overnight_stats.csv(2015~2026 검증, 시가 갭과는 관계가 크고 장중 흐름과는 거의 무관)" if note else '- 해석 근거 없음(overnight_stats.csv 확인 불가)']
    return msg[:200], md

def kospi_today(today):
    p = f'{OUT}/market_daily.csv'
    if not os.path.exists(p): return None
    m = pd.read_csv(p); r = m[m.date == today]
    return float(r.iloc[-1]['kospi_chg_pct']) if len(r) else None

def tavily(day, key):
    d = dt.date.fromisoformat(day)
    body = {'query': f'{d.month}월 {d.day}일 코스피 급락 속 상승 종목 이유', 'max_results': 5, 'search_depth': 'advanced',
            'start_date': day, 'end_date': (d + dt.timedelta(days=2)).isoformat(), 'country': 'south korea', 'include_published_date': True,
            'exclude_domains': ['instagram.com', 'tiktok.com', 'facebook.com', 'threads.net']}   # 첫 수집에서 SNS 짧은 글이 7% 섞여 뺀다
    r = requests.post('https://api.tavily.com/search', json=body, headers={'Authorization': f'Bearer {key}'}, timeout=60)
    js = r.json()
    if 'results' not in js: raise RuntimeError(str(js)[:120])
    return [{'date': day, 'query': body['query'], 'title': x.get('title', ''), 'url': x.get('url', ''),
             'published': x.get('published_date', ''), 'snippet': ' '.join(str(x.get('content', '')).split())[:300],
             'score': round(float(x.get('score', 0)), 3), 'collected': dt.datetime.now(KST).strftime('%Y-%m-%d %H:%M')} for x in js['results']]

def crash_news(today, tag, backfill):
    key = os.environ.get('TAVILY_API_KEY', '').strip()
    if not key: log('TAVILY_API_KEY 없음 — 급락일 뉴스 자동 수집은 건너뜀'); return []
    old = pd.read_csv(NEWS_AUTO, dtype=str) if os.path.exists(NEWS_AUTO) else pd.DataFrame(columns=['date'])
    done = set(old['date']) if len(old) else set()
    days = []
    if tag in ('1540', '1840'):
        c = kospi_today(today)
        if c is not None and c <= -3 and today not in done: days.append(today)
    if backfill:
        m = pd.read_csv(f'{OUT}/market_daily.csv')
        days += [d for d in m[m.kospi_chg_pct <= -3].date.tolist()[::-1] if d not in done and d not in days][:backfill]
    rows = []
    for d in days:
        try: rows += tavily(d, key); log(f'급락일 뉴스 {d} 수집')
        except Exception as e: log(f'급락일 뉴스 {d} 실패: {repr(e)[:100]}')
    if rows:
        pd.concat([old, pd.DataFrame(rows)], ignore_index=True).to_csv(NEWS_AUTO, index=False, encoding='utf-8')
    return sorted({r['date'] for r in rows})

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--tag', default='')
    ap.add_argument('--no-kakao', action='store_true'); ap.add_argument('--crash-backfill', type=int, default=0)
    a = ap.parse_args()
    today = dt.datetime.now(KST).strftime('%Y-%m-%d')
    os.makedirs(OUT, exist_ok=True); os.makedirs('report', exist_ok=True)
    try:
        df, fails = collect_overnight()
        msg, md = overnight_text(df, today)
    except Exception as e:
        log(f'밤사이 미국장 단계 실패: {repr(e)[:120]}'); msg, md = None, None
    news_days = crash_news(today, a.tag[:4], a.crash_backfill)
    if md or news_days:
        extra = (md or []) + ([f'- 급락일 뉴스 자동 수집: {", ".join(news_days)} → out/crash_news_auto.csv'] if news_days else [])
        cur = open('report/latest.md', encoding='utf-8').read() if os.path.exists('report/latest.md') else ''
        if '## 밤사이 미국장' in cur: cur = cur.split('\n## 밤사이 미국장')[0].rstrip('\n') + '\n'   # 재시도 실행에서 같은 절이 쌓이지 않게 바꿔 쓴다
        open('report/latest.md', 'w', encoding='utf-8').write(cur + '\n'.join(extra) + '\n')
    kt = 'report/kakao.txt'
    if msg and a.tag[:4] == '0831' and not a.no_kakao and os.path.exists(kt) and os.path.getsize(kt) > 0:
        txt = open(kt, encoding='utf-8').read().rstrip('\n')
        if '밤사이 미국' not in txt:
            open(kt, 'w', encoding='utf-8').write(txt + '\n=====\n' + msg + '\n'); log('카톡에 밤사이 미국 한 통 덧붙임')
    if msg: print(msg)
    return 0

if __name__ == '__main__': sys.exit(main())
