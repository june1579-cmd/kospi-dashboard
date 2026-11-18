"""KRX 전종목 공매도(거래·잔고) 수집 — pykrx 핵심 클래스로 KRX 정보데이터시스템에 로그인해 받는다(2026-11-18 추가).

받는 것(코스피, 주식만)
  거래  [32001] 개별종목 공매도 거래(전종목)  MDCSTAT30101 → data/short/trade/YYYYMMDD.csv.gz
        공매도 거래량·거래대금, 전체 거래량·거래대금, 비중(%)
  잔고  [33001] 개별종목 공매도 잔고(전종목)  MDCSTAT30501 → data/short/balance/YYYYMMDD.csv.gz
        공매도 순보유 잔고 수량·금액, 상장주식수, 시가총액, 잔고 비율(%) — 보고의무 때문에 거래일 T 의 잔고는 T+2 거래일에 공개된다
  시장 합계 → data/short/market_daily.csv (날짜별 공매도 거래 비중·잔고 금액·잔고 비율)

조회를 아끼는 규칙(2026-11-16 KRX 가 반복 조회로 접속을 하루 막은 일이 있었다)
  - 날짜 하나에 한 번 조회하면 전 종목이 온다. 이미 받은 날짜는 다시 조회하지 않는다.
  - 조회 사이에 4~6초 쉰다. 한 번 실행에 조회 횟수 상한(--max-calls)을 둔다.
  - 연달아 2번 오류(응답이 JSON 이 아님·연결 실패)가 나거나, 지난 날짜가 연달아 3번 비어 오면 접속이 막힌 것으로 보고 바로 멈춘다.
  - 할 일이 없으면 KRX 에 로그인하지 않는다(pykrx 는 import 할 때 로그인하므로 import 를 미룬다).
  - 지난 날짜(최근 3거래일 밖)가 비어 오면 실행마다 세고, 3번 비면 더 묻지 않는다(status.json 의 empty_tries).

실행
  python short_collect.py --mode daily              # 20:23 확정 실행(run_pipeline.py 4c 단계): 최근 10거래일 중 빈 날짜만, 상한 8번
  python short_collect.py --mode backfill           # 밤 예약(short-backfill.yml): 2026-01-02 부터 빈 날짜를 우선순위대로, 상한 60번
  python short_collect.py --summary-only            # 조회 없이 시장 합계만 다시 만든다
종료 코드: 0 정상(받을 것이 아직 공개 안 된 경우 포함) · 2 접속이 막힘/오류로 멈춤(파이프라인 오류 줄에 나온다)
"""
import argparse, datetime as dt, glob, json, os, random, sys, time
import pandas as pd

ROOT = 'data/short'; TRD = f'{ROOT}/trade'; BAL = f'{ROOT}/balance'; ST = f'{ROOT}/status.json'
WB = 'data/통합_원자료.xlsx'
KST = dt.timezone(dt.timedelta(hours=9))
RECENT = 3            # 최근 3거래일 안의 빈 응답은 '아직 공개 전'으로 본다
GIVE_UP = 3           # 지난 날짜가 실행 3번 연속 비면 더 묻지 않는다

def log(m): print(f'[{dt.datetime.now(KST):%H:%M:%S}] 공매도 {m}', flush=True)

def trading_days(start):
    """거래일 목록 — 통합 원자료 엑셀의 코스피 일별 날짜(KRX 시세가 들어온 날)"""
    d = pd.read_excel(WB, sheet_name='코스피_일별', usecols=[0]).iloc[:, 0]
    d = pd.to_datetime(d, errors='coerce').dropna().dt.date
    return sorted(x for x in set(d) if x >= start)

def have(kind, d): return os.path.exists(f'{TRD if kind == "trade" else BAL}/{d:%Y%m%d}.csv.gz')

def num(s):
    return pd.to_numeric(s.astype(str).str.replace(',', '', regex=False).str.strip().replace({'': None, '-': None}), errors='coerce')

def fetch(kind, d):
    """KRX 한 번 조회. 반환: DataFrame(비었으면 빈 표). 접속 문제는 예외로 올린다"""
    from pykrx.website.krx.market.core import 개별종목_공매도_거래_전종목, 전종목_공매도_잔고
    if kind == 'trade':
        raw = 개별종목_공매도_거래_전종목().fetch(f'{d:%Y%m%d}', 'STK', ['STMFRTSCIFDRFS'])
        if raw.empty: return raw
        df = pd.DataFrame({'date': f'{d:%Y-%m-%d}', 'code': raw['ISU_CD'].astype(str), 'name': raw['ISU_ABBRV'],
                           'short_vol': num(raw['CVSRTSELL_TRDVOL']), 'total_vol': num(raw['ACC_TRDVOL']), 'vol_ratio': num(raw['TRDVOL_WT']),
                           'short_val': num(raw['CVSRTSELL_TRDVAL']), 'total_val': num(raw['ACC_TRDVAL']), 'val_ratio': num(raw['TRDVAL_WT'])})
    else:
        raw = 전종목_공매도_잔고().fetch(f'{d:%Y%m%d}', 1)
        if raw.empty: return raw
        df = pd.DataFrame({'date': f'{d:%Y-%m-%d}', 'code': raw['ISU_CD'].astype(str), 'name': raw['ISU_ABBRV'],
                           'bal_qty': num(raw['BAL_QTY']), 'list_shrs': num(raw['LIST_SHRS']), 'bal_amt': num(raw['BAL_AMT']),
                           'mktcap': num(raw['MKTCAP']), 'bal_ratio': num(raw['BAL_RTO'])})
    # 모든 종목이 0 이면(공개 전 자리만 있는 응답) 빈 것으로 본다
    vals = df['short_val'] if kind == 'trade' else df['bal_qty']
    if vals.fillna(0).abs().sum() == 0: return pd.DataFrame()
    return df

def plan(mode, days, st):
    """조회할 (종류, 날짜) 목록 — 이미 받은 것·포기한 것 빼고 우선순위대로"""
    last = days[-1]; recent = set(days[-RECENT:])
    tries = st.setdefault('empty_tries', {'trade': {}, 'balance': {}})
    def want(kind, d):
        if have(kind, d): return False
        if tries[kind].get(f'{d}', 0) >= GIVE_UP and d not in recent: return False
        return True
    if mode == 'daily':
        win = days[-10:]
        # 최신 날짜부터 거래·잔고를 번갈아(상한에 걸려도 둘 다 최신 것부터 채워지게)
        res = []
        for d in reversed(win):
            if want('trade', d): res.append(('trade', d))
            if d != last and want('balance', d): res.append(('balance', d))
        return res
    # backfill: ① 비어 있던 4월 이후 거래 ② 월말 잔고 ③ 나머지 날짜 잔고 ④ 1~3월 거래 — 각 묶음 안에서는 옛 날짜부터
    gap = dt.date(2026, 3, 27)
    month_end = sorted({max(x for x in days if (x.year, x.month) == (d.year, d.month)) for d in days} - {last})
    out = [('trade', d) for d in days if d >= gap]
    out += [('balance', d) for d in month_end]
    out += [('balance', d) for d in days if d not in month_end]
    out += [('trade', d) for d in days if d < gap]
    seen = set(); res = []
    for k, d in out:
        if (k, d) in seen or not want(k, d): continue
        seen.add((k, d)); res.append((k, d))
    return res

def summary():
    """시장 합계(코스피 주식) — 날짜별 공매도 거래 비중·잔고 비율"""
    rows = {}
    for f in sorted(glob.glob(f'{TRD}/*.csv.gz')):
        t = pd.read_csv(f, dtype={'code': str}); d = t['date'].iloc[0]
        sv, tv = t['short_val'].sum(), t['total_val'].sum()
        rows.setdefault(d, {})
        rows[d].update(short_val=int(sv), total_val=int(tv), short_val_ratio=round(100 * sv / tv, 3) if tv else None)
    for f in sorted(glob.glob(f'{BAL}/*.csv.gz')):
        b = pd.read_csv(f, dtype={'code': str}); d = b['date'].iloc[0]
        ba, mc = b['bal_amt'].sum(), b['mktcap'].sum()
        rows.setdefault(d, {})
        rows[d].update(bal_amt=int(ba), mktcap=int(mc), bal_ratio=round(100 * ba / mc, 4) if mc else None, bal_stocks=int((b['bal_qty'] > 0).sum()))
    if not rows: return
    cols = ['short_val', 'total_val', 'short_val_ratio', 'bal_amt', 'mktcap', 'bal_ratio', 'bal_stocks']
    df = pd.DataFrame.from_dict(rows, orient='index').reindex(columns=cols); df.index.name = 'date'
    df.sort_index().to_csv(f'{ROOT}/market_daily.csv', encoding='utf-8')

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--mode', choices=['daily', 'backfill'], default='daily')
    ap.add_argument('--max-calls', type=int, default=None)
    ap.add_argument('--start', default='2026-01-02')
    ap.add_argument('--sleep', type=float, default=4.0)
    ap.add_argument('--summary-only', action='store_true')
    a = ap.parse_args()
    os.makedirs(TRD, exist_ok=True); os.makedirs(BAL, exist_ok=True)
    st = json.load(open(ST, encoding='utf-8')) if os.path.exists(ST) else {}
    if a.summary_only: summary(); return 0
    days = trading_days(dt.date.fromisoformat(a.start))
    todo = plan(a.mode, days, st)
    cap = a.max_calls if a.max_calls is not None else (8 if a.mode == 'daily' else 60)
    log(f'{a.mode}: 받을 것 {len(todo)}건(이번 상한 {cap}번) — 거래일 {days[0]}~{days[-1]}')
    got = []; empty = []; err = None; fails = 0; old_empty = 0; calls = 0
    recent = set(days[-RECENT:])
    for kind, d in todo[:cap]:
        if calls: time.sleep(a.sleep + random.uniform(0, 2))
        calls += 1
        try:
            df = fetch(kind, d); fails = 0
        except Exception as e:
            fails += 1; log(f'{kind} {d} 오류: {repr(e)[:160]}')
            if fails >= 2: err = f'연달아 오류 2번({repr(e)[:80]}) — 접속 제한·로그인 문제로 보고 멈춤'; break
            continue
        if df.empty:
            empty.append(f'{kind} {d}')
            if d in recent: log(f'{kind} {d}: 아직 공개 전'); continue
            k = f'{d}'; st['empty_tries'][kind][k] = st['empty_tries'][kind].get(k, 0) + 1
            old_empty += 1; log(f'{kind} {d}: 비어 있음({st["empty_tries"][kind][k]}번째)')
            if old_empty >= 3: err = '지난 날짜가 연달아 3번 비어 옴 — 접속 제한으로 보고 멈춤'; break
            continue
        old_empty = 0
        df.to_csv(f'{TRD if kind == "trade" else BAL}/{d:%Y%m%d}.csv.gz', index=False, encoding='utf-8', compression='gzip')
        st['empty_tries'][kind].pop(f'{d}', None)
        got.append(f'{kind} {d}'); log(f'{kind} {d}: {len(df)}종목 저장')
    if err:      # 막혔을 때 센 '빈 날짜'는 믿을 수 없으니 이번 실행분은 되돌린다
        for x in empty:
            kind, d = x.split(' '); v = st['empty_tries'][kind].get(d)
            if v and v > 1: st['empty_tries'][kind][d] = v - 1
            elif v: st['empty_tries'][kind].pop(d, None)
    summary()
    left = len(plan(a.mode, days, dict(st)))
    trd = sorted(glob.glob(f'{TRD}/*.csv.gz')); bal = sorted(glob.glob(f'{BAL}/*.csv.gz'))
    st.update(updated=f'{dt.datetime.now(KST):%Y-%m-%d %H:%M}', mode=a.mode, calls=calls, saved=got, error=err, left=left,
              last_trade=os.path.basename(trd[-1])[:8] if trd else None, last_balance=os.path.basename(bal[-1])[:8] if bal else None,
              n_trade=len(trd), n_balance=len(bal))
    json.dump(st, open(ST, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    log(f'끝 — 조회 {calls}번, 저장 {len(got)}건, 남은 것 {left}건, 거래 {st["last_trade"]} · 잔고 {st["last_balance"]}' + (f' · 멈춤: {err}' if err else ''))
    return 2 if err else 0

if __name__ == '__main__':
    sys.exit(main())
