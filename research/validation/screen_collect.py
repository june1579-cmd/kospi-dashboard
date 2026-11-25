# -*- coding: utf-8 -*-
"""전체 종목 재선별용 KRX 원자료 모으기(이미 있는 파일은 건너뜀, 시간 제한 안에서 이어 받기).
- raw/nbday/{시장}_{외국인|기관합계}_{날짜}.csv.gz : 그날 전종목 투자자별 순매수(거래량·거래대금)
- raw/frm/{시장}_{날짜}.csv.gz                    : 달마다 마지막 거래일 외국인 보유율
- raw/snap/SECT_{시장}_{기준일}.csv.gz             : KRX 업종
pykrx(KRX 로그인)만 쓴다. 비밀값은 출력하지 않는다.
"""
import os, sys, time, datetime as dt
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__)); RAW = os.path.join(ROOT, 'raw')
OUT = os.path.join(ROOT, 'screen_out'); os.makedirs(OUT, exist_ok=True)
NB_START = os.environ.get('NB_START', '20250401')
CAP_MIN = float(os.environ.get('COLLECT_MINUTES', '80'))
KST = dt.timezone(dt.timedelta(hours=9))
SECRETS = [v for k, v in os.environ.items() if k in ('KRX_API_KEY', 'KRX_ID', 'KRX_PW') and v]
LOG = []
t0 = time.time()


def log(*a):
    s = ' '.join(str(x) for x in a)
    for v in SECRETS: s = s.replace(v, '***')
    print(s, flush=True); LOG.append(s)


def save(path, df):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    df.to_csv(path, compression='gzip')


def get(fn, need, tries=4):
    for k in range(tries):
        try:
            d = fn(); time.sleep(0.4)
            if d is not None and not d.empty and need in d.columns:
                return d
            raise ValueError(f'빈 표 또는 {need} 칸 없음')
        except Exception as e:
            log(f'  실패({k + 1}/{tries}): {type(e).__name__} {str(e)[:120]}')
            time.sleep(6 * (k + 1))
    return None


def main():
    from pykrx import stock
    from pykrx.website import krx
    now = dt.datetime.now(KST)
    ix = krx.get_index_ohlcv_by_date(NB_START, now.strftime('%Y%m%d'), '1001')
    days = list(pd.to_datetime(ix.index).strftime('%Y%m%d'))
    if days and days[-1] == now.strftime('%Y%m%d') and now.hour < 16: days = days[:-1]
    END = days[-1]
    log('기준일', END, '· 거래일', len(days), days[0], '~', END)
    # 업종
    for m in ('KOSPI', 'KOSDAQ'):
        p = os.path.join(RAW, 'snap', f'SECT_{m}_{END}.csv.gz')
        if not os.path.exists(p):
            d = get(lambda m=m: stock.get_market_sector_classifications(END, m), '업종명')
            if d is not None: save(p, d)
    # 달마다 마지막 거래일 외국인 보유율
    s = pd.Series(days, index=pd.to_datetime(days))
    mends = list(s.groupby(s.index.to_period('M')).max())
    for d in mends:
        for m in ('KOSPI', 'KOSDAQ'):
            p = os.path.join(RAW, 'frm', f'{m}_{d}.csv.gz')
            if os.path.exists(p) and d != END: continue
            x = get(lambda m=m, d=d: stock.get_exhaustion_rates_of_foreign_investment_by_ticker(d, m), '지분율')
            if x is not None: save(p, x[['지분율']])
    log('월말 외국인 보유율', len(mends), '달')
    # 투자자별 일별 순매수(새 날짜부터 거꾸로가 아니라 오래된 날부터 채움)
    todo = [(d, m, w) for d in days for m in ('KOSPI', 'KOSDAQ') for w in ('외국인', '기관합계')
            if not os.path.exists(os.path.join(RAW, 'nbday', f'{m}_{w}_{d}.csv.gz'))]
    log('투자자별 일별 순매수 받을 것', len(todo), '건')
    done = 0
    for d, m, w in todo:
        if (time.time() - t0) / 60 > CAP_MIN:
            log(f'시간 제한 {CAP_MIN}분 — 다음 실행에서 이어 받음'); break
        x = get(lambda d=d, m=m, w=w: stock.get_market_net_purchases_of_equities_by_ticker(d, d, m, w), '순매수거래량')
        if x is None:
            log('  건너뜀', d, m, w); continue
        save(os.path.join(RAW, 'nbday', f'{m}_{w}_{d}.csv.gz'), x[['순매수거래량', '순매수거래대금']])
        done += 1
        if done % 100 == 0: log(f'  {done}/{len(todo)} ({(time.time() - t0) / 60:.1f}분)')
    left = len(todo) - done
    log('받음', done, '· 남음', left, f'· {(time.time() - t0) / 60:.1f}분')
    open(os.path.join(OUT, 'collect_status.txt'), 'w').write(f'{END} left={left}\n')


if __name__ == '__main__':
    try:
        main()
    finally:
        open(os.path.join(OUT, 'collect_log.txt'), 'w').write('\n'.join(LOG) + '\n')
