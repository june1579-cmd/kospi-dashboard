# -*- coding: utf-8 -*-
"""방어종목 1번 결과물 검증용 과거 자료 수집 (수동·push 실행 전용, main·웹판과 무관)

받는 것 (2016-01 ~ 2026-11-16, 상장폐지 종목 포함)
  index_daily.csv.gz        코스피(1001)·코스닥(2001) 일별 종가
  weekly/W_<시장>_<주말일>.csv.gz   주간 전종목 수정 등락률·거래대금 (KRX 전종목 등락률, 수정주가)
  period/P_<시장>_<시작>_<끝>.csv.gz  급락 구간·이후 3·6·12개월 전종목 수정 등락률
  snap/<종류>_<시장>_<날짜>.csv.gz   급락 직전(고점) 날의 시가총액·PER/PBR/배당·외국인 지분율·공매도 잔고
  flow/F_<시장>_<투자자>_<시작>_<끝>.csv.gz  기간 순매수 거래대금(외국인·기관합계)
  dart_op.csv.gz            OpenDART 연결(없으면 별도) 영업이익 2014~2025
  episodes.csv              코스피 7% 이상 하락 구간(고점·저점)
비밀값은 출력하지 않는다. 이미 받은 파일은 건너뛰므로 다시 돌려도 이어서 받는다.
"""
import io, json, os, sys, time, traceback, zipfile, datetime as dt
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(ROOT, 'raw')
for d in ('weekly', 'period', 'snap', 'flow'):
    os.makedirs(os.path.join(RAW, d), exist_ok=True)
LOG = []
SECRETS = [v for k, v in os.environ.items() if (k in ('KRX_API_KEY', 'KRX_ID', 'KRX_PW') or k.startswith('DKEY__')) and v]
# OpenDART 키: 저장소 비밀값 이름을 몰라 후보 이름을 DKEY__<이름> 으로 모두 넘겨받고, 값이 있는 첫 이름을 쓴다(값은 출력하지 않고 이름만 기록).
DART_NAME, DART_KEY = next(((k[6:], v) for k, v in sorted(os.environ.items()) if k.startswith('DKEY__') and v.strip()), ('', ''))
T0 = time.time()
BUDGET = float(os.environ.get('BUDGET_MIN', '320')) * 60  # 남은 시간이 모자라면 멈추고 저장(다음 실행이 이어 받음)
START, END = '20160101', '20261116'


def red(s):
    s = str(s)
    for v in SECRETS:
        if v and len(v) >= 4:
            s = s.replace(v, '***')
    return s


def log(*a):
    line = red(' '.join(str(x) for x in a))
    print(line, flush=True)
    LOG.append(line)


def save_log():
    with open(os.path.join(ROOT, 'collect_log.txt'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(LOG))


def out_of_time():
    return time.time() - T0 > BUDGET


def fetch(path, fn, sleep=1.0, tries=3):
    """path 가 있으면 건너뛰고, 없으면 fn() 결과(DataFrame)를 저장. 빈 결과도 표시 파일로 남겨 다시 묻지 않는다."""
    full = os.path.join(RAW, path)
    if os.path.exists(full):
        return 'skip'
    for k in range(tries):
        try:
            df = fn()
            time.sleep(sleep)
            if df is None:
                df = pd.DataFrame()
            df.to_csv(full, index=True, encoding='utf-8', compression='gzip')
            return len(df)
        except Exception as e:
            log(f'  실패 {path} ({k + 1}/{tries}): {e!r}'[:300])
            time.sleep(5 * (k + 1))
    return 'fail'


# ---------------------------------------------------------------- KRX (pykrx, 정보데이터시스템)
from pykrx import stock
from pykrx.website import krx


def index_daily():
    full = os.path.join(RAW, 'index_daily.csv.gz')
    if os.path.exists(full):
        return pd.read_csv(full, dtype={'date': str})
    rows = []
    for tk, nm in (('1001', 'kospi'), ('2001', 'kosdaq')):
        for y in range(2015, 2027):
            a, b = f'{y}0101', min(f'{y}1231', END)
            try:
                df = krx.get_index_ohlcv_by_date(a, b, tk)
                for d, r in df.iterrows():
                    rows.append({'date': pd.Timestamp(d).strftime('%Y%m%d'), 'idx': nm, 'close': float(r['종가'])})
            except Exception as e:
                log(f'  지수 {nm} {y} 실패: {e!r}'[:200])
            time.sleep(1.0)
    df = pd.DataFrame(rows).pivot_table(index='date', columns='idx', values='close').reset_index()
    df.to_csv(full, index=False, compression='gzip')
    return df


def episodes(ix, thr=0.07, rebound=0.10):
    """코스피 종가가 직전 고점에서 thr 이상 빠진 구간(고점일·저점일).
    구간은 고점을 되찾거나 저점에서 rebound 이상 반등하면 끝난다(2018~2020처럼 고점 회복이 늦은 시기를 여러 급락으로 나누기 위해).
    반등으로 끝나면 그 시점부터 고점을 다시 잰다."""
    s = ix.set_index('date')['kospi'].dropna()
    out, peak_d, peak_v, low_d, low_v, inside = [], None, -1, None, 1e18, False
    for d, v in s.items():
        if inside and (v >= peak_v or v >= low_v * (1 + rebound)):
            out.append((peak_d, low_d, peak_v, low_v))
            peak_d, peak_v, low_d, low_v, inside = d, v, d, v, False
            continue
        if v >= peak_v:
            peak_d, peak_v, low_d, low_v = d, v, d, v
        else:
            if v < low_v:
                low_d, low_v = d, v
            if v <= peak_v * (1 - thr):
                inside = True
    if inside:
        out.append((peak_d, low_d, peak_v, low_v))
    ep = pd.DataFrame(out, columns=['peak', 'trough', 'peak_v', 'trough_v'])
    ep['dd'] = ep['trough_v'] / ep['peak_v'] - 1
    return ep


def next_day(days, d):
    i = days.searchsorted(d, side='right')
    return days[i] if i < len(days) else None


def shift_day(days, d, n):
    i = days.searchsorted(d) + n
    return days[min(max(i, 0), len(days) - 1)]


def pc(a, b, mkt):
    """a(포함)~b 기간 전종목 수정 등락률. 등락률 기준가 = a 의 전 거래일 종가."""
    df = krx.get_market_price_change_by_ticker(a, b, mkt, True)
    return df


def main():
    log('시작', dt.datetime.now().isoformat(timespec='seconds'))
    log('KRX 로그인 값', '있음' if os.environ.get('KRX_ID') else '없음', '/ DART 키', ('있음 — 비밀값 이름 ' + DART_NAME) if DART_KEY else '없음(후보 이름에 없음)')
    ix = index_daily()
    ix['date'] = ix['date'].astype(str)
    days = pd.Index(sorted(ix['date'][ix['date'] <= END]))
    log('지수 일수', len(days), days[0], days[-1])
    ep = episodes(ix[ix['date'] >= '20150101'])
    ep.to_csv(os.path.join(ROOT, 'episodes.csv'), index=False)
    log('급락 구간', len(ep))
    for _, r in ep.iterrows():
        log('  ', r['peak'], '→', r['trough'], f"{r['dd'] * 100:.1f}%")

    # 1) 주간 전종목 등락률 (주 첫 거래일~마지막 거래일)
    dd = pd.to_datetime(pd.Series(days[days >= START]))
    wk = dd.groupby(dd.dt.strftime('%G-%V'))
    weeks = [(g.min().strftime('%Y%m%d'), g.max().strftime('%Y%m%d')) for _, g in wk]
    log('주 수', len(weeks))
    n = 0
    for a, b in weeks:
        for m in ('KOSPI', 'KOSDAQ'):
            if out_of_time():
                log('시간 한도 — 다음 실행에서 이어 받음'); return
            r = fetch(f'weekly/W_{m}_{b}.csv.gz', lambda a=a, b=b, m=m: pc(a, b, m), sleep=0.8)
            if r != 'skip':
                n += 1
                if n % 50 == 0:
                    log(f'  주간 {n}개 받음 ({b})', f'{(time.time() - T0) / 60:.0f}분')
    log('주간 끝')

    # 2) 급락 구간(고점 다음날~저점)과 고점 이후 3·6·12개월 수익률, 고점일 단면 자료
    for _, r in ep.iterrows():
        t, tr = str(r['peak']), str(r['trough'])
        if t < '20180101':
            continue
        a = next_day(days, t)
        if a is None:
            continue
        horizons = [('crash', tr)] + [(f'f{h}', shift_day(days, t, h)) for h in (63, 126, 252) if shift_day(days, t, h) > t]
        for lab, b in horizons:
            if b <= t:
                continue
            for m in ('KOSPI', 'KOSDAQ'):
                if out_of_time():
                    log('시간 한도'); return
                fetch(f'period/P_{m}_{a}_{b}.csv.gz', lambda a=a, b=b, m=m: pc(a, b, m))
        t1y = shift_day(days, t, -250)
        t3m = shift_day(days, t, -63)
        for m in ('KOSPI', 'KOSDAQ'):
            if out_of_time():
                log('시간 한도'); return
            fetch(f'snap/CAP_{m}_{t}.csv.gz', lambda m=m: stock.get_market_cap_by_ticker(t, m))
            fetch(f'snap/FUND_{m}_{t}.csv.gz', lambda m=m: stock.get_market_fundamental_by_ticker(t, m))
            fetch(f'snap/FR_{m}_{t}.csv.gz', lambda m=m: stock.get_exhaustion_rates_of_foreign_investment_by_ticker(t, m))
            fetch(f'snap/FR_{m}_{t1y}.csv.gz', lambda m=m: stock.get_exhaustion_rates_of_foreign_investment_by_ticker(t1y, m))
            fetch(f'snap/SHORT_{m}_{t}.csv.gz', lambda m=m: stock.get_shorting_balance_by_ticker(t, m))
            fetch(f'snap/SECT_{m}_{t}.csv.gz', lambda m=m: stock.get_market_sector_classifications(t, m))
            for inv, code in (('외국인', 'FRGN'), ('기관합계', 'INST')):
                fetch(f'flow/F_{m}_{code}_{t1y}_{t}.csv.gz', lambda m=m, inv=inv: stock.get_market_net_purchases_of_equities_by_ticker(t1y, t, m, inv))
            fetch(f'flow/F_{m}_INST_{t3m}_{t}.csv.gz', lambda m=m: stock.get_market_net_purchases_of_equities_by_ticker(t3m, t, m, '기관합계'))
        log('  단면 끝', t)
    log('KRX 끝', f'{(time.time() - T0) / 60:.0f}분')


# ---------------------------------------------------------------- OpenDART 영업이익
def dart():
    key = DART_KEY.strip()
    log('DART 비밀값', ('이름 ' + DART_NAME) if key else '찾지 못함')
    full = os.path.join(RAW, 'dart_op.csv.gz')
    if not key:
        log('DART 키 없음 — 영업이익 건너뜀(비밀값 이름 확인 필요)'); return
    if os.path.exists(full):
        log('DART 이미 있음'); return
    import requests
    r = requests.get('https://opendart.fss.or.kr/api/corpCode.xml', params={'crtfc_key': key}, timeout=60)
    try:
        z = zipfile.ZipFile(io.BytesIO(r.content))
    except Exception:
        log('DART corpCode 실패:', r.text[:200]); return
    import xml.etree.ElementTree as ET
    root = ET.fromstring(z.read(z.namelist()[0]))
    corps = [(e.findtext('corp_code'), (e.findtext('stock_code') or '').strip(), e.findtext('corp_name')) for e in root.iter('list')]
    corps = [c for c in corps if c[1]]
    log('DART 상장(이력) 회사', len(corps))
    pd.DataFrame(corps, columns=['corp_code', 'stock_code', 'corp_name']).to_csv(os.path.join(RAW, 'dart_corps.csv.gz'), index=False, compression='gzip')
    rows, codes = [], [c[0] for c in corps]
    for y in (2016, 2019, 2022, 2025):
        for i in range(0, len(codes), 100):
            batch = ','.join(codes[i:i + 100])
            for k in range(3):
                try:
                    js = requests.get('https://opendart.fss.or.kr/api/fnlttMultiAcnt.json', params={'crtfc_key': key, 'corp_code': batch, 'bsns_year': str(y), 'reprt_code': '11011'}, timeout=60).json()
                    break
                except Exception as e:
                    js = {'status': 'ERR', 'message': repr(e)}; time.sleep(3)
            st = js.get('status')
            if st == '000':
                for it in js.get('list', []):
                    if it.get('account_nm', '').replace(' ', '') in ('영업이익', '영업이익(손실)'):
                        rows.append({k2: it.get(k2) for k2 in ('corp_code', 'stock_code', 'bsns_year', 'fs_div', 'thstrm_amount', 'frmtrm_amount', 'bfefrmtrm_amount')})
            elif st not in ('013',):
                log('  DART', y, i, st, js.get('message', '')[:80])
                if st in ('020', '010', '011', '012', '901'):
                    log('  DART 중단(키·한도 문제)'); break
            time.sleep(0.3)
        log('  DART', y, '누적', len(rows))
    pd.DataFrame(rows).to_csv(full, index=False, compression='gzip')
    log('DART 끝', len(rows))


if __name__ == '__main__':
    try:
        if 'krx' not in sys.argv[1:]:
            dart()      # 몇 분이면 끝나므로 먼저(키를 찾았는지 바로 알 수 있게)
            save_log()
        if 'dart' not in sys.argv[1:]:
            main()
    except Exception:
        log(traceback.format_exc())
    finally:
        save_log()
