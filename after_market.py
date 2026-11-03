# -*- coding: utf-8 -*-
"""after_market.py — 애프터마켓(저녁 15:40~20:00) 자료 수집·누적·계산. run_pipeline.py 4b 단계에서 매 실행 호출.
  python after_market.py --out out --data data/after_market --tag 1840

누적(data/after_market/):
  nxt_stock_eod.csv.gz : 넥스트레이드 날짜별 20:05 스냅샷(기준가=KRX 전일 종가, 마지막 체결가=저녁 종료 가격, NXT 시·고·저·거래량·대금). 2025-03-04~
  krx_close.csv.gz     : 종목별 KRX 정규장 시가·종가(pykrx 자동 수집; 없는 날은 다음날 NXT 기준가로 보충). 2025-03-04~
  nxt_daily_sessions.csv, nxt_investor_daily.csv : NXT 세션별 거래대금·투자자별(매 실행 전체 기간 다시 받음)
  mcap_naver.csv       : 시가총액(가중치) — pykrx 당일 시가총액을 못 받으면 이 값
출력(out/):
  am_daily.csv  : 날짜별 저녁 등락(대형50 시총가중 등)·NXT 거래대금·투자자별·통합 수급·야간선물·다음날 시가 갭/종가
  am_bucket.csv : 저녁 등락 구간별 과거 다음날 시가·종가 결과(전 기간)
  am_stocks.csv : 마지막 저녁 종목별 등락(±1% 이상, 코스피·코스닥)
  am_now.csv    : 마지막 저녁 요약 한 줄
  am_stats.csv  : 검증 수치(적중률 등, 매 실행 다시 계산)
원자료 값은 그대로. 추정으로 채우지 않음.
"""
import argparse, os, sys, json, time, gzip, datetime as dt
import pandas as pd, numpy as np, requests
KST = dt.timezone(dt.timedelta(hours=9))
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36'
def log(m): print(f'[{dt.datetime.now(KST):%H:%M:%S}] 애프터마켓 {m}', flush=True)
NXT = 'https://www.nextrade.co.kr'
def nxt_session():
    s = requests.Session(); s.headers.update({'User-Agent': UA, 'Accept-Language': 'ko-KR,ko;q=0.9', 'X-Requested-With': 'XMLHttpRequest', 'Referer': NXT + '/menu/transactionStatusMain/menuList.do'})
    s.get(NXT + '/main.do', timeout=30); return s
def nxt_post(s, ep, data, tries=3):
    for i in range(tries):
        try: return s.post(NXT + ep, data=data, timeout=120).json()
        except Exception as e: log(f'재시도 {ep}: {e}'); time.sleep(3)
    return None
def d8(d): return d.replace('-', '')
def iso(d8s): return f'{d8s[:4]}-{d8s[4:6]}-{d8s[6:]}'

# ---------------------------------------------------------------- 1 NXT 수집
def collect_nxt(data_dir, today, now):
    s = nxt_session(); end = today.strftime('%Y%m%d')
    js = nxt_post(s, '/dailyInfo/dailyInfoList.do', {'pageIndex': 1, 'pageUnit': 3000, 'sortKey': 'AGG_DD', 'sortType': 'asc', 'scSecuGroup': 'STOCK', 'scBeginDe': '20250304', 'scEndDe': end})
    ses = pd.DataFrame(js['dailyInfoList']) if js else pd.DataFrame()
    if len(ses):
        ses = ses[['aggDd', 'preIsuCnt', 'preAccTdQty', 'preAccTrval', 'mainIsuCnt', 'mainAccTdQty', 'mainAccTrval', 'aftIsuCnt', 'aftAccTdQty', 'aftAccTrval', 'totalIsuCnt', 'totalAccTdQty', 'totalAccTrval', 'mktShr']].copy()
        ses['date'] = ses.aggDd.map(iso); ses = ses.drop(columns='aggDd').sort_values('date'); ses.to_csv(os.path.join(data_dir, 'nxt_daily_sessions.csv'), index=False, encoding='utf-8-sig')
    js = nxt_post(s, '/itpc/itpcList.do', {'pageIndex': 1, 'pageUnit': 3000, 'sortKey': 'AGG_DD', 'sortType': 'asc', 'scBeginDe': '20250304', 'scEndDe': end, 'scSecuGroup': 'STOCK'})
    inv = pd.DataFrame(js['investorInfoList']) if js else pd.DataFrame()
    if len(inv):
        inv = inv[['trdDe', 'indQtyAsk', 'indQtyBid', 'instQtyAsk', 'instQtyBid', 'frgnQtyAsk', 'frgnQtyBid', 'indValAsk', 'indValBid', 'instValAsk', 'instValBid', 'frgnValAsk', 'frgnValBid']].rename(columns={'trdDe': 'date'}).sort_values('date')
        inv.to_csv(os.path.join(data_dir, 'nxt_investor_daily.csv'), index=False, encoding='utf-8-sig')
    days = sorted(ses.date.unique()) if len(ses) else []
    # 종목별 스냅샷: 누적 파일에 없는 날만(오늘은 20:05 이후에만). 처음이면 전부(약 400회 호출)
    fn = os.path.join(data_dir, 'nxt_stock_eod.csv.gz')
    old = pd.read_csv(fn, dtype={'code': str}) if os.path.exists(fn) else pd.DataFrame(columns=['date'])
    have = set(old.date.astype(str)) if len(old) else set()
    todo = [d for d in days if d not in have and (d < today.isoformat() or now.time() >= dt.time(20, 6))]
    new = []
    for i, d in enumerate(todo):
        js = nxt_post(s, '/brdinfoTime/brdinfoTimeList.do', {'pageIndex': 1, 'pageUnit': 3000, 'scSecuGroup': 'STOCK', 'scAggDd': d8(d), 'scMktId': '', 'searchKeyword': ''})
        if not js: continue
        st = str(js.get('setTime') or '')
        if d == today.isoformat() and (len(st) < 16 or st[11:16] < '20:05'): log(f'{d} 스냅샷이 아직 20:05 전({st}) — 다음 실행에'); continue
        for x in js.get('brdinfoTimeList') or []:
            new.append({'date': d, 'market': x.get('mktNm'), 'code': str(x.get('isuSrdCd', '')).lstrip('A'), 'name': x.get('isuAbwdNm'), 'base_prc': x.get('basePrc'), 'last_prc': x.get('curPrc'), 'open': x.get('oppr'), 'high': x.get('hgpr'), 'low': x.get('lwpr'), 'volume': x.get('accTdQty'), 'value': x.get('accTrval'), 'snap_time': x.get('creTime')})
        if (i + 1) % 20 == 0: log(f'NXT 스냅샷 {i+1}/{len(todo)}')
        time.sleep(0.15)
    if new:
        eod = pd.concat([old, pd.DataFrame(new)], ignore_index=True) if len(old) else pd.DataFrame(new)
        eod = eod.drop_duplicates(['date', 'code'], keep='last').sort_values(['date', 'code']); eod.to_csv(fn, index=False, compression='gzip'); log(f'NXT 스냅샷 {len(new)}줄 추가({sorted(set(r["date"] for r in new))[-1]})')
    else: eod = old
    return eod, ses, inv

# ---------------------------------------------------------------- 2 KRX 정규장 종가(pykrx) — 못 받으면 다음날 NXT 기준가로 보충
def collect_krx_close(data_dir, eod, today, now):
    fn = os.path.join(data_dir, 'krx_close.csv.gz')
    kc = pd.read_csv(fn, dtype={'code': str}) if os.path.exists(fn) else pd.DataFrame(columns=['date', 'market', 'code', 'name', 'open', 'close', 'basis'])
    have = set(kc.date.astype(str)) if len(kc) else set()
    days = sorted(set(eod.date.astype(str)))
    want = [d for d in days if d not in have and d >= '2026-09-14']            # 9/14 전은 씨앗 파일(네이버)로 채워져 있음
    if today.isoformat() in days or now.time() >= dt.time(15, 35): want = sorted(set(want) | ({today.isoformat()} if today.isoformat() not in have and today.weekday() < 5 and now.time() >= dt.time(15, 35) else set()))
    rows = []; mcap_rows = []
    try:
        from pykrx import stock
        for d in want[-30:]:
            try:
                for mk in ['KOSPI', 'KOSDAQ']:
                    df = stock.get_market_ohlcv(d8(d), market=mk)
                    if df is None or not len(df) or '종가' not in df.columns or (df['종가'] == 0).all(): continue
                    for code, r in df.iterrows():
                        if r['종가'] > 0: rows.append({'date': d, 'market': mk, 'code': str(code), 'name': '', 'open': r['시가'], 'close': r['종가'], 'basis': 'KRX 정규장(pykrx 전종목 시세)'})
                time.sleep(0.5)
            except Exception as e: log(f'pykrx {d} 실패: {str(e)[:80]}')
        try:
            cap = stock.get_market_cap(d8(days[-1]), market='KOSPI')
            if cap is not None and len(cap) and '시가총액' in cap.columns: mcap_rows = [{'code': str(c), 'mcap_eok': v / 1e8, 'asof': days[-1]} for c, v in cap['시가총액'].items() if v > 0]
        except Exception as e: log(f'pykrx 시가총액 실패: {str(e)[:80]}')
    except Exception as e: log(f'pykrx 없음: {e}')
    # 보충: 다음날 NXT 기준가 = 그날 정규장 종가(배당락 등 예외는 그대로)
    nb = eod[['date', 'code', 'base_prc', 'market', 'name']].copy(); nb['prev'] = nb.groupby('code')['date'].shift(1)
    nb = nb.dropna(subset=['prev']); nb = nb[~nb.prev.isin(have)]
    got = set(r['date'] for r in rows)
    nb = nb[~nb.prev.isin(got)]
    for _, r in nb.iterrows(): rows.append({'date': r['prev'], 'market': r['market'], 'code': r['code'], 'name': r['name'], 'open': np.nan, 'close': r['base_prc'], 'basis': '다음날 NXT 기준가(=KRX 정규장 종가)'})
    if rows:
        kc = pd.concat([kc, pd.DataFrame(rows)], ignore_index=True).drop_duplicates(['date', 'code'], keep='first').sort_values(['date', 'code'])
        kc.to_csv(fn, index=False, compression='gzip'); log(f'KRX 정규장 종가 {len(rows)}줄 추가')
    if mcap_rows:
        pd.DataFrame(mcap_rows).to_csv(os.path.join(data_dir, 'mcap_krx.csv'), index=False, encoding='utf-8-sig')
    return kc

# ---------------------------------------------------------------- 3 지수(네이버 차트 API: KRX 지수 시가·종가와 일치 확인)
def naver_index(data_dir):
    out = []
    for idx in ['KOSPI', 'KPI200']:
        try:
            r = requests.get(f'https://api.stock.naver.com/chart/domestic/index/{idx}/day', params={'startDateTime': '202501010000', 'endDateTime': dt.date.today().strftime('%Y%m%d') + '0000'}, headers={'User-Agent': UA}, timeout=60)
            for x in r.json(): out.append({'index': idx, 'date': iso(x['localDate']), 'open': x.get('openPrice'), 'high': x.get('highPrice'), 'low': x.get('lowPrice'), 'close': x.get('closePrice')})
        except Exception as e: log(f'네이버 지수 {idx} 실패: {e}')
    df = pd.DataFrame(out)
    if len(df):
        now = dt.datetime.now(KST)
        if now.time() < dt.time(15, 35): df = df[df.date != now.date().isoformat()]      # 장중 값은 쓰지 않음
        df.to_csv(os.path.join(data_dir, 'index_daily.csv'), index=False, encoding='utf-8-sig')
    return df

# ---------------------------------------------------------------- 4 계산
EDGES = [-99, -1.5, -1, -0.5, -0.25, 0.25, 0.5, 1, 1.5, 99]; LABELS = ['-1.5% 이하', '-1.5~-1%', '-1~-0.5%', '-0.5~-0.25%', '±0.25%', '+0.25~0.5%', '+0.5~1%', '+1~1.5%', '+1.5% 이상']
def wavg(v, w):
    w = w.fillna(0); m = v.notna() & (w > 0); return float((v[m] * w[m]).sum() / w[m].sum()) if w[m].sum() > 0 else np.nan
def build(out_dir, data_dir, eod, ses, inv, kc, idx, tag, now):
    for c in ['base_prc', 'last_prc', 'value']: eod[c] = pd.to_numeric(eod[c], errors='coerce')
    kc['close'] = pd.to_numeric(kc['close'], errors='coerce'); kc['open'] = pd.to_numeric(kc['open'], errors='coerce')
    st = eod.merge(kc[['date', 'code', 'open', 'close']].rename(columns={'open': 'krx_open', 'close': 'krx_close'}), on=['date', 'code'], how='left')
    st['am_ret'] = (st.last_prc / st.krx_close - 1).where(st.krx_close > 0)
    st = st[st.am_ret.isna() | (st.am_ret.abs() < 0.31)]
    mc_fn = os.path.join(data_dir, 'mcap_krx.csv'); mc = pd.read_csv(mc_fn, dtype={'code': str}) if os.path.exists(mc_fn) else pd.read_csv(os.path.join(data_dir, 'mcap_naver.csv'), dtype={'code': str})
    mc_src = 'KRX 시가총액(pykrx)' if os.path.exists(mc_fn) else '네이버 시가총액(고정)'
    st = st.merge(mc[['code', 'mcap_eok']].drop_duplicates('code'), on='code', how='left')
    ks = st[(st.market == 'KOSPI') & st.am_ret.notna()]
    rows = []
    for d, g in ks.groupby('date'):
        top = g.nlargest(50, 'mcap_eok')
        rows.append({'date': d, 'n_kospi': len(g), 'am_cw_top50': wavg(top.am_ret, top.mcap_eok), 'am_cw_all': wavg(g.am_ret, g.mcap_eok), 'am_ew_all': g.am_ret.mean(), 'am_tw_all': wavg(g.am_ret, g.value),
                     'am_samsung': float(g.loc[g.code == '005930', 'am_ret'].iloc[0]) if (g.code == '005930').any() else np.nan, 'am_hynix': float(g.loc[g.code == '000660', 'am_ret'].iloc[0]) if (g.code == '000660').any() else np.nan,
                     'am_up_share': (g.am_ret > 0).mean(), 'am_down_share': (g.am_ret < 0).mean()})
    am = pd.DataFrame(rows).sort_values('date')
    if len(ses):
        ses = ses.copy(); ses['nxt_aft_trval_eok'] = ses.aftAccTrval / 1e8; ses['nxt_main_trval_eok'] = ses.mainAccTrval / 1e8; ses['nxt_total_trval_eok'] = ses.totalAccTrval / 1e8; ses['nxt_aft_share'] = ses.aftAccTrval / ses.totalAccTrval; ses['nxt_mkt_share_pct'] = ses.mktShr
        ses = ses.sort_values('date'); ses['nxt_aft_rel20'] = ses.nxt_aft_trval_eok / ses.nxt_aft_trval_eok.rolling(20, min_periods=10).mean().shift(1)
        am = am.merge(ses[['date', 'nxt_aft_trval_eok', 'nxt_main_trval_eok', 'nxt_total_trval_eok', 'nxt_aft_share', 'nxt_mkt_share_pct', 'nxt_aft_rel20']], on='date', how='outer')
    if len(inv):
        inv = inv.copy(); inv['nxt_ind_net_eok'] = (inv.indValBid - inv.indValAsk) / 1e8; inv['nxt_inst_net_eok'] = (inv.instValBid - inv.instValAsk) / 1e8; inv['nxt_frgn_net_eok'] = (inv.frgnValBid - inv.frgnValAsk) / 1e8
        am = am.merge(inv[['date', 'nxt_ind_net_eok', 'nxt_inst_net_eok', 'nxt_frgn_net_eok']], on='date', how='left')
    fl_fn = os.path.join(out_dir, 'flows_daily.csv')
    if os.path.exists(fl_fn):
        fl = pd.read_csv(fl_fn)[['date', 'foreign_jo', 'inst_jo', 'indiv_jo', 'other_jo', 'basis']].rename(columns={'foreign_jo': 'krx_foreign_jo', 'inst_jo': 'krx_inst_jo', 'indiv_jo': 'krx_indiv_jo', 'other_jo': 'krx_other_jo', 'basis': 'krx_basis'})
        am = am.merge(fl, on='date', how='left')
        for a, b, c in [('foreign', 'frgn', 'total_foreign_eok'), ('indiv', 'ind', 'total_indiv_eok'), ('inst', 'inst', 'total_inst_eok')]: am[c] = am[f'krx_{a}_jo'] * 1e4 + am[f'nxt_{b}_net_eok']
    nf_fn = os.path.join(out_dir, 'night_fut.csv')
    if os.path.exists(nf_fn): am = am.merge(pd.read_csv(nf_fn)[['date', 'night_pct']], on='date', how='left')
    if len(idx):
        k = idx[idx['index'] == 'KOSPI'].sort_values('date').reset_index(drop=True)
        k['next_date'] = k.date.shift(-1); k['next_open_gap'] = k.open.shift(-1) / k.close - 1; k['next_close_ret'] = k.close.shift(-1) / k.close - 1; k['next_range'] = (k.high.shift(-1) - k.low.shift(-1)) / k.close
        k['range'] = (k.high - k.low) / k.close; k['next_range_rel20'] = k.next_range / k.range.rolling(20, min_periods=10).mean()
        am = am.merge(k[['date', 'close', 'next_date', 'next_open_gap', 'next_close_ret', 'next_range', 'next_range_rel20']].rename(columns={'close': 'kospi_close'}), on='date', how='left')
    am = am[am.date >= '2025-03-04'].sort_values('date').reset_index(drop=True)
    am['era'] = np.where(am.date < '2026-09-14', 'NXT 애프터마켓+KRX 시간외단일가', 'KRX 애프터마켓+NXT')
    am['bucket'] = pd.cut(am.am_cw_top50 * 100, EDGES, labels=LABELS).astype(str).replace('nan', '')
    am['basis'] = '저녁 가격 NXT 20:05 스냅샷(=KRX 애프터마켓 종가와 일치 확인) ÷ KRX 정규장 종가 − 1 · 가중치 ' + mc_src + ' · 투자자별 통합 = KRX 확정 + NXT'
    am.round(6).to_csv(os.path.join(out_dir, 'am_daily.csv'), index=False, encoding='utf-8-sig')
    # 구간표(전 기간, 결과 있는 날)
    h = am.dropna(subset=['am_cw_top50', 'next_open_gap'])
    b = pd.cut(h.am_cw_top50 * 100, EDGES, labels=LABELS); rows = []
    for lab in LABELS:
        g = h[b == lab]; og = g.next_open_gap * 100; cr = g.next_close_ret.dropna() * 100
        rows.append({'bucket': lab, 'lo': EDGES[LABELS.index(lab)], 'hi': EDGES[LABELS.index(lab) + 1], 'n': len(g), 'p_up_open': round((og > 0).mean(), 3) if len(g) else np.nan, 'med_gap': round(og.median(), 2) if len(g) else np.nan, 'q10': round(og.quantile(.1), 2) if len(g) else np.nan, 'q90': round(og.quantile(.9), 2) if len(g) else np.nan,
                     'p_up_close': round((cr > 0).mean(), 3) if len(cr) else np.nan, 'med_close': round(cr.median(), 2) if len(cr) else np.nan, 'hit_open': round((np.sign(g.am_cw_top50) == np.sign(g.next_open_gap)).mean(), 3) if len(g) else np.nan})
    z = h[(h.am_cw_top50 != 0) & (h.next_open_gap != 0)]
    rows.append({'bucket': '전체', 'lo': '', 'hi': '', 'n': len(h), 'p_up_open': round((h.next_open_gap > 0).mean(), 3), 'med_gap': round(h.next_open_gap.median() * 100, 2), 'q10': round(h.next_open_gap.quantile(.1) * 100, 2), 'q90': round(h.next_open_gap.quantile(.9) * 100, 2), 'p_up_close': round((h.next_close_ret > 0).mean(), 3), 'med_close': round(h.next_close_ret.median() * 100, 2), 'hit_open': round((np.sign(z.am_cw_top50) == np.sign(z.next_open_gap)).mean(), 3) if len(z) else np.nan})
    bk = pd.DataFrame(rows); bk['period'] = f'{h.date.min()}~{h.date.max()}'; bk.to_csv(os.path.join(out_dir, 'am_bucket.csv'), index=False, encoding='utf-8-sig')
    # 검증 수치
    stats_rows = []
    def add(item, value, text): stats_rows.append({'item': item, 'value': value, 'text': text})
    if len(z): add('저녁 등락→다음날 시가 부호 적중', round((np.sign(z.am_cw_top50) == np.sign(z.next_open_gap)).mean() * 100, 1), f'{len(z)}일, 대형50 시총가중, {h.date.min()}~{h.date.max()}')
    zc = h.dropna(subset=['next_close_ret']); zc = zc[(zc.am_cw_top50 != 0) & (zc.next_close_ret != 0)]
    if len(zc): add('저녁 등락→다음날 종가 부호 적중', round((np.sign(zc.am_cw_top50) == np.sign(zc.next_close_ret)).mean() * 100, 1), f'{len(zc)}일')
    both = h.dropna(subset=['night_pct']); both = both[(both.night_pct != 0) & (both.am_cw_top50 != 0) & (both.next_open_gap != 0)]
    if len(both) >= 20:
        add('야간선물→다음날 시가 부호 적중(같은 날)', round((np.sign(both.night_pct) == np.sign(both.next_open_gap)).mean() * 100, 1), f'{len(both)}일')
        add('애프터마켓→다음날 시가 부호 적중(같은 날)', round((np.sign(both.am_cw_top50) == np.sign(both.next_open_gap)).mean() * 100, 1), f'{len(both)}일')
        dis = both[np.sign(both.night_pct) != np.sign(both.am_cw_top50)]
        if len(dis): add('엇갈릴 때 야간선물이 맞은 비율', round((np.sign(dis.night_pct) == np.sign(dis.next_open_gap)).mean() * 100, 1), f'{len(dis)}일 엇갈림')
        ag = both[np.sign(both.night_pct) == np.sign(both.am_cw_top50)]
        if len(ag): add('같은 방향일 때 시가 적중', round((np.sign(ag.night_pct) == np.sign(ag.next_open_gap)).mean() * 100, 1), f'{len(ag)}일')
    ext = h[h.am_cw_top50.abs() >= 0.015]
    if len(ext): add('저녁 ±1.5% 밖 날의 시가 같은 방향', round((np.sign(ext.am_cw_top50) == np.sign(ext.next_open_gap)).mean() * 100, 1), f'{len(ext)}일')
    vr = am.dropna(subset=['nxt_aft_rel20', 'next_range_rel20'])
    if len(vr) >= 30:
        from scipy import stats as sps
        add('NXT 애프터마켓 거래대금(20일 대비)→다음날 고저폭 스피어만', round(sps.spearmanr(vr.nxt_aft_rel20, vr.next_range_rel20).correlation, 3), f'{len(vr)}일')
        hi = vr[vr.nxt_aft_rel20 >= 1.3]; lo = vr[vr.nxt_aft_rel20 <= 0.8]
        if len(hi): add('거래대금 20일 평균의 1.3배 이상인 날 다음날 고저폭(20일 평균 대비) 중앙값', round(hi.next_range_rel20.median(), 2), f'{len(hi)}일')
        if len(lo): add('거래대금 20일 평균의 0.8배 이하인 날 다음날 고저폭 중앙값', round(lo.next_range_rel20.median(), 2), f'{len(lo)}일')
    # 종목 수준(대형50 또는 시총 상위): 저녁 등락 → 그 종목 다음날 시가
    top50 = set(mc.nlargest(50, 'mcap_eok').code) if len(mc) else set()
    s = st[st.code.isin(top50)].dropna(subset=['am_ret']).sort_values(['code', 'date']).copy()
    s['next_open'] = s.groupby('code')['krx_open'].shift(-1); s['next_gap'] = s.next_open / s.krx_close - 1
    s = s.dropna(subset=['next_gap']); s = s[(s.next_gap.abs() < 0.3)]
    s = s.merge(am[['date', 'am_cw_top50', 'next_open_gap']], on='date', how='left'); s['idio'] = s.am_ret - s.am_cw_top50; s['gap_idio'] = s.next_gap - s.next_open_gap
    zz = s[(s.am_ret != 0) & (s.next_gap != 0)]
    if len(zz) >= 200:
        add('종목 저녁 등락→그 종목 다음날 시가 부호 적중(대형50)', round((np.sign(zz.am_ret) == np.sign(zz.next_gap)).mean() * 100, 1), f'{len(zz)}건')
        b1 = zz[zz.am_ret.abs() >= 0.01]
        if len(b1): add('종목 저녁 ±1% 이상 → 시가 같은 방향', round((np.sign(b1.am_ret) == np.sign(b1.next_gap)).mean() * 100, 1), f'{len(b1)}건, 갭 중앙값 {round((b1.next_gap * np.sign(b1.am_ret)).median() * 100, 2)}%')
        i1 = zz.dropna(subset=['idio', 'gap_idio']); i1 = i1[i1.idio.abs() >= 0.01]
        if len(i1): add('종목 고유 저녁 등락 ±1% 이상 → 고유 시가 갭 같은 방향', round((np.sign(i1.idio) == np.sign(i1.gap_idio)).mean() * 100, 1), f'{len(i1)}건, 고유 갭 중앙값 {round((i1.gap_idio * np.sign(i1.idio)).median() * 100, 2)}%')
    add('기준일', str(am.date.max()), f'실행 {now:%Y-%m-%d %H:%M} {tag} · 구간 R1 2025-03-04~2026-09-11 NXT 애프터마켓+KRX 시간외단일가, R2 2026-09-14~ KRX 애프터마켓+NXT')
    pd.DataFrame(stats_rows).to_csv(os.path.join(out_dir, 'am_stats.csv'), index=False, encoding='utf-8-sig')
    # 마지막 저녁 종목별(코스피·코스닥 ±1% 이상, 고유 등락 큰 순)
    last = str(st.dropna(subset=['am_ret']).date.max())
    g = st[(st.date == last) & st.am_ret.notna()].copy(); mk = am.loc[am.date == last, 'am_cw_top50']; mkv = float(mk.iloc[0]) if len(mk) and pd.notna(mk.iloc[0]) else 0.0
    g['idio'] = g.am_ret - mkv; g['am_ret_pct'] = g.am_ret * 100; g['idio_pct'] = g.idio * 100; g['value_eok'] = g.value / 1e8
    g = g[(g.am_ret.abs() >= 0.01) & (g.value_eok >= 1)].sort_values('idio', key=abs, ascending=False)
    g[['date', 'market', 'code', 'name', 'krx_close', 'last_prc', 'am_ret_pct', 'idio_pct', 'value_eok', 'mcap_eok']].round(2).head(40).to_csv(os.path.join(out_dir, 'am_stocks.csv'), index=False, encoding='utf-8-sig')
    # 요약 한 줄
    r = am[am.date == last].iloc[0] if (am.date == last).any() else None
    nowrow = {}
    if r is not None:
        bkr = bk[bk.bucket == r.bucket]
        nf = r.get('night_pct'); agree = '' if pd.isna(nf) or pd.isna(r.am_cw_top50) else ('같은 방향' if np.sign(nf) == np.sign(r.am_cw_top50) else '엇갈림')
        nowrow = {'date': last, 'am_cw_top50_pct': round(r.am_cw_top50 * 100, 2) if pd.notna(r.am_cw_top50) else np.nan, 'am_samsung_pct': round(r.am_samsung * 100, 2) if pd.notna(r.am_samsung) else np.nan, 'am_up_share_pct': round(r.am_up_share * 100, 0) if pd.notna(r.am_up_share) else np.nan,
                  'bucket': r.bucket, 'bucket_n': int(bkr.n.iloc[0]) if len(bkr) else 0, 'bucket_p_up_open': float(bkr.p_up_open.iloc[0]) if len(bkr) else np.nan, 'bucket_med_gap': float(bkr.med_gap.iloc[0]) if len(bkr) else np.nan, 'bucket_p_up_close': float(bkr.p_up_close.iloc[0]) if len(bkr) else np.nan,
                  'night_pct': nf, 'night_agree': agree, 'nxt_aft_trval_eok': round(r.nxt_aft_trval_eok, 0) if pd.notna(r.get('nxt_aft_trval_eok')) else np.nan, 'nxt_aft_rel20': round(r.nxt_aft_rel20, 2) if pd.notna(r.get('nxt_aft_rel20')) else np.nan,
                  'nxt_frgn_net_eok': r.get('nxt_frgn_net_eok'), 'nxt_ind_net_eok': r.get('nxt_ind_net_eok'), 'nxt_inst_net_eok': r.get('nxt_inst_net_eok'), 'krx_foreign_jo': r.get('krx_foreign_jo'), 'krx_indiv_jo': r.get('krx_indiv_jo'), 'krx_inst_jo': r.get('krx_inst_jo'), 'krx_basis': r.get('krx_basis'),
                  'total_foreign_eok': r.get('total_foreign_eok'), 'total_indiv_eok': r.get('total_indiv_eok'), 'total_inst_eok': r.get('total_inst_eok'), 'next_open_gap_pct': round(r.next_open_gap * 100, 2) if pd.notna(r.get('next_open_gap')) else np.nan, 'next_close_ret_pct': round(r.next_close_ret * 100, 2) if pd.notna(r.get('next_close_ret')) else np.nan,
                  'n_movers': int(len(g)), 'era': r.era}
        vr2 = am.dropna(subset=['nxt_aft_rel20', 'next_range_rel20'])
        if pd.notna(nowrow['nxt_aft_rel20']) and len(vr2) >= 30:
            near = vr2[(vr2.nxt_aft_rel20 - nowrow['nxt_aft_rel20']).abs() <= 0.15]
            nowrow['range_hint_n'] = int(len(near)); nowrow['range_hint_med'] = round(near.next_range_rel20.median(), 2) if len(near) else np.nan
    pd.DataFrame([nowrow]).to_csv(os.path.join(out_dir, 'am_now.csv'), index=False, encoding='utf-8-sig')
    log(f'계산 완료: am_daily {len(am)}일(마지막 {last}), 구간표 {len(h)}일, 종목 {len(g)}개')

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--out', default='out'); ap.add_argument('--data', default='data/after_market'); ap.add_argument('--tag', default='')
    a = ap.parse_args(); now = dt.datetime.now(KST); today = now.date(); os.makedirs(a.data, exist_ok=True); os.makedirs(a.out, exist_ok=True)
    eod, ses, inv = collect_nxt(a.data, today, now)
    if not len(eod): log('NXT 스냅샷 없음 — 중단'); return
    kc = collect_krx_close(a.data, eod, today, now)
    idx = naver_index(a.data)
    build(a.out, a.data, eod, ses, inv, kc, idx, a.tag, now)

if __name__ == '__main__':
    try: main()
    except Exception as e:
        import traceback; traceback.print_exc(); log(f'오류 {e!r} — 이 단계만 건너뜀')
