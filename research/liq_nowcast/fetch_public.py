#!/usr/bin/env python3
"""공개 자료 수집 (로그인·인증키 없음) — 네이버 금융 일봉 차트(fchart.stock.naver.com)

만드는 파일(research/liq_nowcast/data/):
  kosdaq_index.csv   코스닥 지수 일봉(시가·고가·저가·종가)
  breadth_daily.csv  종목별 일봉을 하루 단위로 모은 값(급락 종목 수, 매수일 T-3 이후 손실 집계 등)
  fetch_status.json  받은 것·못 받은 것

지킨 것
  · 날짜 d 의 값은 d 까지의 종목 자료만 쓴다(자체 점검: --selfcheck 로 뒤 날짜를 지운 뒤 다시 계산해 비교).
  · 한계(추정으로 메우지 않고 그대로 적음):
      - 종목 목록은 "지금 상장된 종목"뿐이다. 과거에 상장폐지된 종목은 빠진다(과거 급락 종목 수가 실제보다 적게 잡힘).
      - 네이버 일봉은 가격만 수정주가이고 거래량은 원래 값이다. 그래서 '가격×거래량' 거래대금은 액면분할·무상증자 이전 구간에서
        실제보다 작다. 거래대금 가중 값은 이름에 vw_ 를 붙여 따로 둔다(종목 수 기준 값은 영향 없음).
"""
import os, re, sys, json, time, argparse, concurrent.futures as cf
import warnings
import numpy as np, pandas as pd, requests
warnings.filterwarnings("ignore")

HERE = os.path.dirname(os.path.abspath(__file__)); DATA = os.path.join(HERE, 'data')
UA = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36', 'Referer': 'https://finance.naver.com/'}


def fchart(symbol, count=3000, tries=4):
    last = None
    for k in range(tries):
        try:
            r = requests.get('https://fchart.stock.naver.com/sise.nhn', params={'symbol': symbol, 'timeframe': 'day', 'count': count, 'requestType': 0}, headers=UA, timeout=30)
            if r.status_code == 200:
                rows = re.findall(r'<item data="([^"]+)"', r.text)
                if rows:
                    a = [x.split('|') for x in rows]
                    df = pd.DataFrame(a, columns=['date', 'open', 'high', 'low', 'close', 'volume'])
                    df['date'] = pd.to_datetime(df['date'], format='%Y%m%d')
                    for c in ['open', 'high', 'low', 'close', 'volume']: df[c] = pd.to_numeric(df[c], errors='coerce')
                    return df
                last = 'empty'
            else: last = f'http {r.status_code}'
        except Exception as e:  # noqa
            last = type(e).__name__
        time.sleep(1.5 * (k + 1))
    raise RuntimeError(f'{symbol}: {last}')


def stock_list(market):
    out = []; page = 1
    while True:
        for k in range(4):
            try:
                r = requests.get(f'https://m.stock.naver.com/api/stocks/marketValue/{market}', params={'page': page, 'pageSize': 100}, headers=UA, timeout=30); j = r.json(); break
            except Exception:
                time.sleep(2 * (k + 1)); j = None
        if not j or not j.get('stocks'): break
        for s in j['stocks']:
            if s.get('stockEndType') == 'stock': out.append((s['itemCode'], s['stockName']))
        if page * 100 >= int(j.get('totalCount', 0)): break
        page += 1
    return out


def aggregate(panel, cal):
    """panel: {(market, code): df(date, open, close, volume)} · cal: 거래일(DatetimeIndex). 날짜 d 의 값은 d 이하 자료만 쓴다."""
    res = pd.DataFrame(index=cal)
    for mk in ('ks', 'kq'):
        codes = sorted(c for (m, c) in panel if m == mk)
        if not codes: continue
        D, N = len(cal), len(codes)
        C = np.full((D, N), np.nan); O = np.full((D, N), np.nan); V = np.zeros((D, N))
        pos = pd.Series(np.arange(D), index=cal)
        for jx, c in enumerate(codes):
            df = panel[(mk, c)]; df = df[df['date'].isin(cal)]
            if not len(df): continue
            ix = pos.loc[df['date']].values
            C[ix, jx] = df['close'].values; o = df['open'].values.astype(float); o[o <= 0] = np.nan; O[ix, jx] = o; V[ix, jx] = np.nan_to_num(df['volume'].values)
        C[C <= 0] = np.nan
        # 상장 이후 구간에서만 거래정지일 종가를 앞 값으로 채운다(첫 자료 이전은 비워 둠)
        Cf = pd.DataFrame(C).ffill().values
        O = np.where(np.isnan(O), Cf, O)                       # 시가 없음(거래 없음) → 그날 종가(=전일 종가)
        ret1 = Cf / np.vstack([np.full((1, N), np.nan), Cf[:-1]]) - 1
        val = np.nan_to_num(Cf * V) / 1e8                      # 억원(수정주가×원거래량 — 위 한계 참고)
        live = ~np.isnan(ret1)
        def cnt(mask): return np.where(live, mask, False).sum(1).astype(float)
        res[f'{mk}_n'] = live.sum(1)
        res[f'{mk}_dn10'] = cnt(ret1 <= -0.10); res[f'{mk}_dn15'] = cnt(ret1 <= -0.15); res[f'{mk}_dn20'] = cnt(ret1 <= -0.20)
        res[f'{mk}_lim'] = cnt(ret1 <= -0.29); res[f'{mk}_up10'] = cnt(ret1 >= 0.10); res[f'{mk}_uplim'] = cnt(ret1 >= 0.29)
        with np.errstate(all='ignore'):
            res[f'{mk}_ret_med'] = np.nanmedian(ret1, 1) * 100; res[f'{mk}_ret_p10'] = np.nanpercentile(ret1, 10, axis=1) * 100
        res[f'{mk}_vw_val'] = val.sum(1)
        # ---- 매수일 T-3 묶음: 미수 매수(T-3) → 결제(T-1) → 못 갚으면 T 아침 반대매매. 행 T 에 놓는다(T 이하 자료만 사용).
        def sh(a, k):
            b = np.full_like(a, np.nan, dtype=float); b[k:] = a[:-k]; return b
        c3, c1 = sh(Cf, 3), sh(Cf, 1); r21 = c1 / c3 - 1                      # T-3 종가 → T-1 종가
        ro = O / c3 - 1                                                       # T-3 종가 → T 시가(반대매매가 나가는 가격)
        r3 = sh(ret1, 3); v3 = sh(val, 3); vol3 = sh(V, 3)
        medv = pd.DataFrame(V).rolling(20, min_periods=10).median().values    # 그날 포함 지난 20일 거래량 중앙값
        medv_b = sh(medv, 4)                                                  # T-4 까지의 중앙값(매수일 이전)
        ok = ~np.isnan(r21)
        with np.errstate(all='ignore'):
            hot = ok & ((r3 >= 0.10) | (vol3 >= 5 * medv_b)) & (vol3 > 0)
            res[f'{mk}_c_n10'] = np.where(ok, r21 <= -0.10, False).sum(1).astype(float); res[f'{mk}_c_n20'] = np.where(ok, r21 <= -0.20, False).sum(1).astype(float)
            res[f'{mk}_c_p10'] = np.nanpercentile(np.where(ok, r21, np.nan), 10, axis=1) * 100; res[f'{mk}_c_med'] = np.nanmedian(np.where(ok, r21, np.nan), 1) * 100
            res[f'{mk}_c_hot_n'] = hot.sum(1).astype(float)
            hl = np.where(hot, np.maximum(0, -r21), np.nan); hlo = np.where(hot, np.maximum(0, -ro), np.nan)
            res[f'{mk}_c_hot_loss'] = np.nan_to_num(np.nanmean(hl, 1)) * 100; res[f'{mk}_c_hot_loss_o'] = np.nan_to_num(np.nanmean(hlo, 1)) * 100
            res[f'{mk}_c_hot_n10'] = np.where(hot, r21 <= -0.10, False).sum(1).astype(float)
            w = np.where(ok, np.nan_to_num(v3), 0.0); ws = w.sum(1); ws[ws <= 0] = np.nan
            loss = np.where(ok, np.maximum(0, -np.nan_to_num(r21)), 0.0); loss_o = np.where(ok, np.maximum(0, -np.nan_to_num(ro)), 0.0)
            res[f'{mk}_vw_loss'] = (w * loss).sum(1) / ws * 100; res[f'{mk}_vw_loss_o'] = (w * loss_o).sum(1) / ws * 100
            res[f'{mk}_vw_l10'] = (w * np.where(ok, r21 <= -0.10, False)).sum(1) / ws * 100
            res[f'{mk}_vw_lossamt'] = (w * loss).sum(1)
        res.loc[res.index[:3], [c for c in res.columns if c.startswith(f'{mk}_c_') or c.startswith(f'{mk}_vw_l')]] = np.nan
    return res


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--end', required=True, help='마지막 날짜(이 날짜 뒤 자료는 버림, YYYY-MM-DD)')
    ap.add_argument('--limit', type=int, default=0, help='시험용: 시장별 종목 수 제한'); ap.add_argument('--workers', type=int, default=6)
    ap.add_argument('--raw', default='', help='종목별 원자료 저장·재사용 경로(parquet 대신 pickle)'); ap.add_argument('--selfcheck', type=int, default=12)
    a = ap.parse_args(); os.makedirs(DATA, exist_ok=True); end = pd.Timestamp(a.end); st = {'end': a.end, 'source': 'fchart.stock.naver.com (공개, 로그인 없음)'}
    kq = fchart('KOSDAQ'); kq = kq[kq['date'] <= end]; kq[['date', 'open', 'high', 'low', 'close']].to_csv(os.path.join(DATA, 'kosdaq_index.csv'), index=False)
    ks = fchart('KOSPI'); ks = ks[ks['date'] <= end]; cal = pd.DatetimeIndex(sorted(ks['date'])); st['kosdaq_index'] = f"{kq['date'].min():%Y-%m-%d}~{kq['date'].max():%Y-%m-%d} {len(kq)}일"
    panel = {}
    if a.raw and os.path.exists(a.raw):
        panel = pd.read_pickle(a.raw); st['stocks_cache'] = '재사용'
        if max(df['date'].max() for df in panel.values()) < end: panel = {}
    if not panel:
        lst = []
        for mk, nm in (('ks', 'KOSPI'), ('kq', 'KOSDAQ')):
            l = stock_list(nm); st[f'list_{mk}'] = len(l)
            if a.limit: l = l[:a.limit]
            lst += [(mk, c) for c, _ in l]
        fail = []
        def job(t):
            try:
                df = fchart(t[1]); return t, df[df['date'] <= end][['date', 'open', 'close', 'volume']]
            except Exception as e:  # noqa
                return t, str(e)
        with cf.ThreadPoolExecutor(a.workers) as ex:
            for i, (t, df) in enumerate(ex.map(job, lst)):
                if isinstance(df, str): fail.append(t[1])
                else: panel[t] = df
                if i % 400 == 0: print(f'  종목 {i}/{len(lst)} 실패 {len(fail)}', flush=True)
        st['stocks_ok'] = len(panel); st['stocks_fail'] = len(fail); st['stocks_fail_codes'] = fail[:50]
        if a.raw: pd.to_pickle(panel, a.raw)
    st['stocks_used'] = len(panel)
    if len(panel) < 200 and not a.limit:
        st['breadth'] = '확인 불가(종목 일봉을 충분히 받지 못함)'; json.dump(st, open(os.path.join(DATA, 'fetch_status.json'), 'w'), ensure_ascii=False, indent=1); print(st); return
    agg = aggregate(panel, cal)
    # ---- 자체 점검: 임의 날짜 d 뒤의 종목 자료를 지우고 다시 계산해 d 행이 같은지 본다(미래 자료 섞임 점검)
    rng = np.random.RandomState(0); bad = 0; chk = sorted(rng.choice(np.arange(300, len(cal)), size=min(a.selfcheck, len(cal) - 300), replace=False)) if len(cal) > 400 else []
    for i in chk:
        d = cal[i]; p2 = {k: v[v['date'] <= d] for k, v in panel.items()}; g2 = aggregate({k: v for k, v in p2.items() if len(v)}, cal[:i + 1])
        x, y = agg.loc[d].astype(float).values, g2.loc[d].reindex(agg.columns).astype(float).values
        if not np.allclose(np.nan_to_num(x, nan=-9e9), np.nan_to_num(y, nan=-9e9), rtol=1e-9, atol=1e-9): bad += 1; print('  자체 점검 불일치', d.date(), [c for c, u, v in zip(agg.columns, x, y) if not np.isclose(np.nan_to_num(u, nan=-9e9), np.nan_to_num(v, nan=-9e9))][:8])
    st['selfcheck'] = f'{len(chk)}개 날짜 중 불일치 {bad}개'
    agg.round(4).rename_axis('date').reset_index().to_csv(os.path.join(DATA, 'breadth_daily.csv'), index=False)
    first = {k: v['date'].min() for k, v in panel.items()}; st['stocks_listed_by_2019'] = int(sum(d <= pd.Timestamp('2019-01-02') for d in first.values()))
    st['breadth'] = f'{agg.index.min():%Y-%m-%d}~{agg.index.max():%Y-%m-%d} {len(agg)}일'
    json.dump(st, open(os.path.join(DATA, 'fetch_status.json'), 'w'), ensure_ascii=False, indent=1); print(json.dumps(st, ensure_ascii=False, indent=1))
    if bad: sys.exit(3)


if __name__ == '__main__':
    main()
