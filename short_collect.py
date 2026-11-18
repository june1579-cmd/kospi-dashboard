"""KRX 전종목 공매도(거래·잔고) 수집 — pykrx 핵심 클래스로 KRX 정보데이터시스템에 로그인해 받는다(2026-11-18 추가).

받는 것(코스피, 주식만)
  거래  [32001] 개별종목 공매도 거래(전종목)  MDCSTAT30101 → <root>/trade/YYYYMMDD.csv.gz
        공매도 거래량·거래대금, 전체 거래량·거래대금, 비중(%)
  잔고  [33001] 개별종목 공매도 잔고(전종목)  MDCSTAT30501 → <root>/balance/YYYYMMDD.csv.gz
        공매도 순보유 잔고 수량·금액, 상장주식수, 시가총액, 잔고 비율(%) — 거래일 T 의 잔고는 T+2 거래일에 공개
        잔고 공시 제도는 2016-06-30 부터라 그 전 날짜는 묻지 않는다.
  시장 합계 → <root>/market_daily.csv,  상태 → <root>/status.json

모드
  daily     최근 10거래일 중 빈 날짜(20:23 확정 실행 run_pipeline.py 4c, 상한 8번)              root = data/short
  backfill  2026-01-02 이후 빈 날짜(밤 예약 short-backfill.yml)                                root = data/short
  history   2016-01-04 ~ 2025-12-30 빈 날짜, 최신 날짜부터(밤 예약, 2026 을 다 받은 뒤)          root = short-history 가지의 data/short

조회를 아끼는 규칙(2026-11-16 KRX 가 반복 조회로 접속을 하루 막은 일이 있었다)
  - 날짜 하나에 한 번 조회하면 전 종목이 온다. 이미 받은 날짜는 다시 조회하지 않는다. 조회 사이 4~6초. 실행당 상한(--max-calls).
  - 연달아 오류 2번(응답이 JSON 이 아님·연결 실패)이면 막힌 것으로 보고 멈추고, 그 뒤 24시간은 실행해도 조회하지 않는다(blocked_at).
  - 지난 날짜가 연달아 3번 비어 오면, 이미 받은 날짜 하나를 다시 물어 확인한다(확인 조회).
      확인 조회가 정상이면 정말 자료가 없는 날로 보고 계속, 확인 조회도 비거나 오류면 막힌 것으로 보고 멈춘다.
  - 지난 날짜가 실행 3번 연속 비면 더 묻지 않는다(empty_tries). 최근 3거래일의 빈 응답은 '아직 공개 전'으로 보고 세지 않는다.
  - 모든 종목이 0 인 응답: 지난 날짜면 그대로 저장(공매도 금지 기간 2020-03-16~2021-05-02, 2023-11-06~2025-03-30 등), 최근 3거래일이면 공개 전으로 본다.
  - 할 일이 없거나 쉬는 중이면 pykrx 를 불러오지 않아 KRX 에 로그인하지 않는다.

종료 코드: 0 정상 · 2 막힘/오류로 멈춤
"""
import argparse, datetime as dt, glob, json, os, random, sys, time
import pandas as pd

WB = 'data/통합_원자료.xlsx'
KST = dt.timezone(dt.timedelta(hours=9))
RECENT = 3
GIVE_UP = 3
BAL_START = dt.date(2016, 6, 30)
COOL_H = 24
ROOT = 'data/short'

def d_trd(): return f'{ROOT}/trade'
def d_bal(): return f'{ROOT}/balance'
def log(m): print(f'[{dt.datetime.now(KST):%H:%M:%S}] 공매도 {m}', flush=True)

def trading_days(start, end=None):
    """거래일 목록 — 통합 원자료 엑셀의 코스피 일별 날짜(2015-01-02~)"""
    d = pd.read_excel(WB, sheet_name='코스피_일별', usecols=[0]).iloc[:, 0]
    d = pd.to_datetime(d, errors='coerce').dropna().dt.date
    return sorted(x for x in set(d) if x >= start and (end is None or x <= end))

def path(kind, d): return f'{d_trd() if kind == "trade" else d_bal()}/{d:%Y%m%d}.csv.gz'
def have(kind, d): return os.path.exists(path(kind, d))

def num(s):
    return pd.to_numeric(s.astype(str).str.replace(',', '', regex=False).str.strip().replace({'': None, '-': None}), errors='coerce')

def fetch(kind, d):
    """KRX 한 번 조회 → (표, 모두0여부). 행이 없으면 빈 표. 접속 문제는 예외로 올린다"""
    from pykrx.website.krx.market.core import 개별종목_공매도_거래_전종목, 전종목_공매도_잔고
    if kind == 'trade':
        raw = 개별종목_공매도_거래_전종목().fetch(f'{d:%Y%m%d}', 'STK', ['STMFRTSCIFDRFS'])
        if raw.empty: return raw, False
        df = pd.DataFrame({'date': f'{d:%Y-%m-%d}', 'code': raw['ISU_CD'].astype(str), 'name': raw['ISU_ABBRV'],
                           'short_vol': num(raw['CVSRTSELL_TRDVOL']), 'total_vol': num(raw['ACC_TRDVOL']), 'vol_ratio': num(raw['TRDVOL_WT']),
                           'short_val': num(raw['CVSRTSELL_TRDVAL']), 'total_val': num(raw['ACC_TRDVAL']), 'val_ratio': num(raw['TRDVAL_WT'])})
        zero = df['short_val'].fillna(0).abs().sum() == 0
    else:
        raw = 전종목_공매도_잔고().fetch(f'{d:%Y%m%d}', 1)
        if raw.empty: return raw, False
        df = pd.DataFrame({'date': f'{d:%Y-%m-%d}', 'code': raw['ISU_CD'].astype(str), 'name': raw['ISU_ABBRV'],
                           'bal_qty': num(raw['BAL_QTY']), 'list_shrs': num(raw['LIST_SHRS']), 'bal_amt': num(raw['BAL_AMT']),
                           'mktcap': num(raw['MKTCAP']), 'bal_ratio': num(raw['BAL_RTO'])})
        zero = df['bal_qty'].fillna(0).abs().sum() == 0
    return df, zero

def plan(mode, days, st, start):
    """조회할 (종류, 날짜) 목록 — 이미 받은 것·포기한 것 빼고 우선순위대로"""
    recent = set(days[-RECENT:]) if mode != 'history' else set()
    last = days[-1]
    tries = st.setdefault('empty_tries', {'trade': {}, 'balance': {}})
    def want(kind, d):
        if kind == 'balance' and d < BAL_START: return False
        if have(kind, d): return False
        if tries[kind].get(f'{d}', 0) >= GIVE_UP and d not in recent: return False
        return True
    if mode in ('daily', 'history'):
        # 최신 날짜부터 거래·잔고를 번갈아
        win = days[-10:] if mode == 'daily' else days
        res = []
        for d in reversed(win):
            if want('trade', d): res.append(('trade', d))
            if not (mode == 'daily' and d == last) and want('balance', d): res.append(('balance', d))
        return res
    # backfill: ① 비어 있던 3/27 이후 거래 ② 월말 잔고 ③ 나머지 잔고 ④ 그 전 거래 — 묶음 안에서는 옛 날짜부터
    gap = dt.date(2026, 3, 27)
    month_end = sorted({max(x for x in days if (x.year, x.month) == (d.year, d.month)) for d in days} - {last})
    out = [('trade', d) for d in days if d >= gap] + [('balance', d) for d in month_end]
    out += [('balance', d) for d in days if d not in month_end] + [('trade', d) for d in days if d < gap]
    seen = set(); res = []
    for k, d in out:
        if (k, d) in seen or not want(k, d): continue
        seen.add((k, d)); res.append((k, d))
    return res

def canary(kind):
    """이미 받은 날짜 하나를 다시 물어 접속이 정상인지 확인 — 받은 파일이 없으면 2026-11-13(받아 둔 날)"""
    files = sorted(glob.glob(f'{d_trd() if kind == "trade" else d_bal()}/*.csv.gz'))
    d = dt.datetime.strptime(os.path.basename(files[-1])[:8], '%Y%m%d').date() if files else dt.date(2026, 11, 13)
    try:
        df, zero = fetch(kind, d)
        ok = not df.empty
    except Exception as e:
        ok = False; log(f'확인 조회 오류: {repr(e)[:120]}')
    log(f'확인 조회 {kind} {d}: ' + ('정상' if ok else '실패'))
    return ok

def summary():
    rows = {}
    for f in sorted(glob.glob(f'{d_trd()}/*.csv.gz')):
        t = pd.read_csv(f, dtype={'code': str}); d = t['date'].iloc[0]
        sv, tv = t['short_val'].sum(), t['total_val'].sum()
        rows.setdefault(d, {}).update(short_val=int(sv), total_val=int(tv), short_val_ratio=round(100 * sv / tv, 3) if tv else None)
    for f in sorted(glob.glob(f'{d_bal()}/*.csv.gz')):
        b = pd.read_csv(f, dtype={'code': str}); d = b['date'].iloc[0]
        ba, mc = b['bal_amt'].sum(), b['mktcap'].sum()
        rows.setdefault(d, {}).update(bal_amt=int(ba), mktcap=int(mc), bal_ratio=round(100 * ba / mc, 4) if mc else None, bal_stocks=int((b['bal_qty'] > 0).sum()))
    if not rows: return
    cols = ['short_val', 'total_val', 'short_val_ratio', 'bal_amt', 'mktcap', 'bal_ratio', 'bal_stocks']
    df = pd.DataFrame.from_dict(rows, orient='index').reindex(columns=cols); df.index.name = 'date'
    df.sort_index().to_csv(f'{ROOT}/market_daily.csv', encoding='utf-8')

def main():
    global ROOT
    ap = argparse.ArgumentParser()
    ap.add_argument('--mode', choices=['daily', 'backfill', 'history'], default='daily')
    ap.add_argument('--root', default='data/short')
    ap.add_argument('--max-calls', type=int, default=None)
    ap.add_argument('--start', default=None)
    ap.add_argument('--end', default=None)
    ap.add_argument('--sleep', type=float, default=4.0)
    ap.add_argument('--summary-only', action='store_true')
    a = ap.parse_args()
    ROOT = a.root; st_fn = f'{ROOT}/status.json'
    os.makedirs(d_trd(), exist_ok=True); os.makedirs(d_bal(), exist_ok=True)
    st = json.load(open(st_fn, encoding='utf-8')) if os.path.exists(st_fn) else {}
    if a.summary_only: summary(); return 0
    now = dt.datetime.now(KST)
    if a.mode != 'daily' and st.get('blocked_at'):
        since = (now - dt.datetime.fromisoformat(st['blocked_at'])).total_seconds() / 3600
        if since < COOL_H:
            log(f'{a.mode}: {st["blocked_at"]}에 막혀 {COOL_H}시간 쉬는 중({since:.1f}시간 지남) — 조회하지 않음')
            st.update(calls=0, skipped='cooldown'); json.dump(st, open(st_fn, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
            return 0
    start = dt.date.fromisoformat(a.start) if a.start else (dt.date(2016, 1, 4) if a.mode == 'history' else dt.date(2026, 1, 2))
    end = dt.date.fromisoformat(a.end) if a.end else (dt.date(2025, 12, 31) if a.mode == 'history' else None)
    days = trading_days(start, end)
    todo = plan(a.mode, days, st, start)
    cap = a.max_calls if a.max_calls is not None else {'daily': 8, 'backfill': 60, 'history': 60}[a.mode]
    log(f'{a.mode}: 받을 것 {len(todo)}건(이번 상한 {cap}번) — 거래일 {days[0]}~{days[-1]} · 저장 {ROOT}')
    recent = set(days[-RECENT:]) if a.mode != 'history' else set()
    got = []; err = None; fails = 0; calls = 0; streak = []
    for kind, d in todo:
        if calls >= cap: break
        if calls: time.sleep(a.sleep + random.uniform(0, 2))
        calls += 1
        try:
            df, zero = fetch(kind, d); fails = 0
        except Exception as e:
            fails += 1; log(f'{kind} {d} 오류: {repr(e)[:160]}')
            if fails >= 2: err = f'연달아 오류 2번({repr(e)[:80]})'; break
            continue
        if df.empty or (zero and d in recent):
            if d in recent: log(f'{kind} {d}: 아직 공개 전'); continue
            streak.append((kind, d)); log(f'{kind} {d}: 비어 있음')
            if len(streak) >= 3:
                time.sleep(a.sleep); calls += 1
                if not canary(kind): err = '지난 날짜가 연달아 3번 비고 확인 조회도 실패'; break
                for k2, d2 in streak: st['empty_tries'][k2][f'{d2}'] = st['empty_tries'][k2].get(f'{d2}', 0) + 1
                streak = []
            continue
        if streak:      # 사이에 정상 날짜가 오면 앞의 빈 날짜는 진짜로 빈 날
            for k2, d2 in streak: st['empty_tries'][k2][f'{d2}'] = st['empty_tries'][k2].get(f'{d2}', 0) + 1
            streak = []
        df.to_csv(path(kind, d), index=False, encoding='utf-8', compression='gzip')
        st['empty_tries'][kind].pop(f'{d}', None)
        got.append(f'{kind} {d}'); log(f'{kind} {d}: {len(df)}종목 저장' + (' (모두 0)' if zero else ''))
    if streak and not err:
        for k2, d2 in streak: st['empty_tries'][k2][f'{d2}'] = st['empty_tries'][k2].get(f'{d2}', 0) + 1
    summary()
    left = len(plan(a.mode, days, dict(st), start))
    trd = sorted(glob.glob(f'{d_trd()}/*.csv.gz')); bal = sorted(glob.glob(f'{d_bal()}/*.csv.gz'))
    st.update(updated=f'{now:%Y-%m-%d %H:%M}', mode=a.mode, calls=calls, saved=got[-20:], n_saved=len(got), error=err, left=left, skipped=None,
              first_trade=os.path.basename(trd[0])[:8] if trd else None, last_trade=os.path.basename(trd[-1])[:8] if trd else None,
              first_balance=os.path.basename(bal[0])[:8] if bal else None, last_balance=os.path.basename(bal[-1])[:8] if bal else None,
              n_trade=len(trd), n_balance=len(bal))
    if err and a.mode != 'daily': st['blocked_at'] = now.isoformat(timespec='minutes')
    elif not err and calls: st.pop('blocked_at', None)
    json.dump(st, open(st_fn, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    log(f'끝 — 조회 {calls}번, 저장 {len(got)}건, 남은 것 {left}건, 거래 {st["first_trade"]}~{st["last_trade"]} · 잔고 {st["first_balance"]}~{st["last_balance"]}' + (f' · 멈춤: {err}' if err else ''))
    return 2 if err else 0

if __name__ == '__main__':
    sys.exit(main())
