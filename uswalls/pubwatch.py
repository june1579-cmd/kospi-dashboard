# -*- coding: utf-8 -*-
"""uswalls/pubwatch.py — 미국 옵션 자료가 실제로 몇 시(KST)에 바뀌는지 재는 기록기(2026-11-24 사용자 요청). GitHub 워크플로 pub-watch 가 돌린다.

10분마다 출처별 '지금 보이는 기준값'을 읽고, 값이 바뀐 첫 시각을 pub-watch 가지의 log.csv 에 적는다(자료·대시보드는 고치지 않음, 기록만).
  occ_flex    : OCC FLEX 미결제 보고서(일별 파일) — 새 날짜 파일이 처음 보인 시각 = OCC 일일 미결제 처리 완료 무렵
  occ_series  : OCC 시리즈 검색(SPY) 응답 내용(해시) — 바뀐 시각
  yahoo       : 야후 SPY 12월 월물 미결제 합 — 비워지는 시각과 다시 채워지는 시각
  optioncharts: OptionCharts SPY 'as of' 날짜
  spotgamma   : SpotGamma 무료 레벨 페이지 수정 시각
  (CME ES 옵션 일일 보고서는 GitHub 에서 403 으로 막혀 측정하지 않는다)
  cboe_pc     : Cboe 일별 시장 통계(풋/콜) 날짜별 파일이 처음 보인 날짜
  cboe_vix    : Cboe VIX 이력 CSV 의 마지막 날짜
가볍게 읽는다(출처마다 10분에 한 번, 작은 요청). 5거래일치가 모이거나 시작 뒤 8일이 지나면 카카오톡으로 한 번 요약하고 스스로 멈춘다.
"""
import csv
import datetime as dt
import hashlib
import json
import os
import re
import sys
import time

import requests

OUT = sys.argv[1] if len(sys.argv) > 1 else 'pw'
LOOP_MIN = int(os.environ.get('LOOP_MIN', '55')); STEP = int(os.environ.get('STEP_SEC', '600'))
KST = dt.timezone(dt.timedelta(hours=9)); now = lambda: dt.datetime.now(KST)
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36', 'Accept': '*/*'}
NEED_EVENTS = 5; MAX_DAYS = 8
try:
    from zoneinfo import ZoneInfo; NY = ZoneInfo('America/New_York')
except Exception: NY = dt.timezone(dt.timedelta(hours=-5))


def bdays_back(n):
    d = dt.datetime.now(NY).date(); out = []
    while len(out) < n:
        if d.weekday() < 5: out.append(d)
        d -= dt.timedelta(days=1)
    return out


def get(url, **kw):
    return requests.get(url, headers=UA, timeout=30, **kw)


def occ_flex():
    for d in bdays_back(4):
        r = get('https://marketdata.theocc.com/flex-reports', params={'reportType': 'OI', 'optionType': 'I', 'reportDate': d.strftime('%Y%m%d')})
        if r.status_code == 200 and len(r.content) > 300 and b'rror' not in r.content[:300] and b'<html' not in r.content[:300].lower(): return str(d)
    return '없음(최근 4거래일)'


def occ_series():
    r = get('https://marketdata.theocc.com/series-search', params={'symbolType': 'U', 'symbol': 'SPY'})
    if r.status_code != 200 or len(r.content) < 1000: raise RuntimeError(f'HTTP {r.status_code} · {len(r.content)}바이트')
    return hashlib.md5(r.content).hexdigest()[:12]


def yahoo():
    import yfinance as yf
    tk = yf.Ticker('SPY'); exps = [e for e in tk.options if e[8:] >= '15' and e[8:] <= '21' and dt.date.fromisoformat(e).weekday() == 4]
    if not exps: raise RuntimeError('월물 만기 없음')
    ch = tk.option_chain(exps[0])
    tot = int(ch.calls['openInterest'].fillna(0).sum() + ch.puts['openInterest'].fillna(0).sum())
    return f'{exps[0]}:{tot}'


def optioncharts():
    r = get('https://optioncharts.io/options/SPY/open-interest')
    m = re.search(r'as of ([A-Z][a-z]{2} \d{1,2}, \d{4})', r.text)
    if not m: raise RuntimeError(f'HTTP {r.status_code} · 날짜 문구 없음')
    return m.group(1)


def spotgamma():
    r = get('https://spotgamma.com/spx-gex-levels-today/')
    m = re.search(r'article:modified_time"\s+content="([^"]+)"', r.text)
    if not m: raise RuntimeError(f'HTTP {r.status_code} · 수정 시각 없음')
    return m.group(1)


def cme():
    u = 'https://www.cmegroup.com/daily_bulletin/current/Section47_E_Mini_S_And_P_500_Call_Options.pdf'
    r = requests.head(u, headers=UA, timeout=30, allow_redirects=True)
    lm = r.headers.get('Last-Modified')
    if not lm:
        r = get(u, stream=True); lm = r.headers.get('Last-Modified'); r.close()
    if not lm: raise RuntimeError(f'HTTP {r.status_code} · Last-Modified 없음')
    return lm


def cboe_pc():
    for d in bdays_back(4):
        r = get(f'https://cdn.cboe.com/data/us/options/market_statistics/daily/{d}_daily_options')
        if r.status_code == 200:
            try:
                if r.json().get('ratios'): return str(d)
            except Exception: pass
    return '없음(최근 4거래일)'


def cboe_vix():
    r = get('https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv')
    if r.status_code != 200: raise RuntimeError(f'HTTP {r.status_code}')
    last = [l for l in r.text.strip().splitlines() if l[:1].isdigit()][-1].split(',')[0]
    return last


SRC = {'occ_flex': ('OCC FLEX 미결제 보고서', occ_flex), 'occ_series': ('OCC 시리즈 검색(SPY)', occ_series), 'yahoo': ('야후 SPY 월물 미결제 합', yahoo),
       'optioncharts': ('OptionCharts 기준일', optioncharts), 'spotgamma': ('SpotGamma 레벨 페이지', spotgamma),   # CME 는 GitHub 에서 403(차단)이라 뺐다(2026-11-24 시험)
       'cboe_pc': ('Cboe 풋/콜 날짜별 파일', cboe_pc), 'cboe_vix': ('Cboe VIX 이력 CSV', cboe_vix)}


def hm(s): return s[11:16] if s and len(s) >= 16 else '?'


def summarize(st, rows):
    S = {'updated': now().strftime('%Y-%m-%d %H:%M'), 'started': st.get('started'), 'done': st.get('done'), 'sources': {}}
    days = max(1, (now() - dt.datetime.strptime(st['started'], '%Y-%m-%d %H:%M').replace(tzinfo=KST)).days + 1)
    for k, (nm, _) in SRC.items():
        ev = [r for r in rows if r['source'] == k and r['note'] != '첫 확인']
        if len(ev) > 4 * days:   # 읽을 때마다 바뀌는 출처(응답에 시각이 섞인 경우) — 공개 시각으로 쓸 수 없음
            S['sources'][k] = {'name': nm, 'last': st.get(k, {}).get('last'), 'checked': st.get(k, {}).get('checked'), 'err': st.get(k, {}).get('err'),
                               'n': len(ev), 'median_kst': None, 'range_kst': None, 'noisy': True, 'events': []}
            continue
        mins = sorted(int(hm(r['first_seen'])[:2]) * 60 + int(hm(r['first_seen'])[3:]) for r in ev if hm(r['first_seen']) != '?')
        med = mins[len(mins) // 2] if mins else None
        S['sources'][k] = {'name': nm, 'last': st.get(k, {}).get('last'), 'checked': st.get(k, {}).get('checked'), 'err': st.get(k, {}).get('err'),
                           'n': len(ev), 'median_kst': (f'{med // 60:02d}:{med % 60:02d}' if med is not None else None),
                           'range_kst': (f'{mins[0] // 60:02d}:{mins[0] % 60:02d}~{mins[-1] // 60:02d}:{mins[-1] % 60:02d}' if mins else None),
                           'events': [{'value': r['value'], 'first_seen': r['first_seen'], 'prev_check': r['prev_check']} for r in ev[-12:]]}
    return S


def main():
    os.makedirs(OUT, exist_ok=True)
    sp, lp = os.path.join(OUT, 'state.json'), os.path.join(OUT, 'log.csv')
    st = json.load(open(sp, encoding='utf-8')) if os.path.exists(sp) else {}
    st.setdefault('started', now().strftime('%Y-%m-%d %H:%M'))
    if not os.path.exists(lp): open(lp, 'w', encoding='utf-8').write('source,value,first_seen,prev_check,note\n')
    if st.get('done'): print('측정 끝남(', st['done'], ') — 아무것도 하지 않음'); return
    end = time.time() + LOOP_MIN * 60
    while True:
        t = now().strftime('%Y-%m-%d %H:%M')
        for k, (nm, fn) in SRC.items():
            s0 = st.setdefault(k, {})
            try:
                v = str(fn())
                if v != s0.get('last'):
                    note = '첫 확인' if s0.get('last') is None else ''
                    with open(lp, 'a', encoding='utf-8', newline='') as f: csv.writer(f).writerow([k, v, t, s0.get('checked', ''), note])
                    print(t, '바뀜', k, s0.get('last'), '→', v, flush=True)
                    s0['last'] = v
                s0['checked'] = t; s0.pop('err', None)
            except Exception as e:
                s0['err'] = f'{t} {e!r}'[:160]; print(t, '읽기 실패', k, repr(e)[:160], flush=True)
            time.sleep(1)
        json.dump(st, open(sp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        if time.time() + STEP > end: break
        time.sleep(STEP)
    rows = list(csv.DictReader(open(lp, encoding='utf-8')))
    S = summarize(st, rows)
    n = {k: v['n'] for k, v in S['sources'].items()}
    age = (now() - dt.datetime.strptime(st['started'], '%Y-%m-%d %H:%M').replace(tzinfo=KST)).days
    if (min(n['occ_flex'], n['yahoo'], n['spotgamma']) >= NEED_EVENTS or age >= MAX_DAYS) and not st.get('done'):
        st['done'] = now().strftime('%Y-%m-%d %H:%M'); S['done'] = st['done']
        L1 = [f"[미국옵션 공개 시각 {age}일 측정·KST]"]
        for k in ('occ_flex', 'yahoo', 'optioncharts', 'spotgamma'):
            v = S['sources'][k]; L1.append(f"{v['name']}: " + (f"보통 {v['median_kst']}({v['range_kst']})" if v['median_kst'] else '확인 못 함'))
        L2 = ['[미국옵션 공개 시각 2]']
        for k in ('cboe_pc', 'cboe_vix', 'occ_series'):
            v = S['sources'][k]; L2.append(f"{v['name']}: " + (f"보통 {v['median_kst']}({v['range_kst']})" if v['median_kst'] else '확인 못 함'))
        L2.append('측정 끝 — 기록은 pub-watch 가지')
        open(os.path.join(OUT, 'notify.txt'), 'w', encoding='utf-8').write('\n'.join(L1)[:195] + '\n=====\n' + '\n'.join(L2)[:195] + '\n')
        if os.environ.get('GITHUB_OUTPUT'): open(os.environ['GITHUB_OUTPUT'], 'a').write('send=1\n')
    json.dump(st, open(sp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    json.dump(S, open(os.path.join(OUT, 'summary.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
