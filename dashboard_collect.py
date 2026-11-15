# -*- coding: utf-8 -*-
"""dashboard_collect.py — 코스피 미수 반대매매·신용 대시보드용 자료 자동 수집 (PC에서 실행)

실행:  python dashboard_collect.py            (최근 10거래일, 기본 — 18:30 전이면 오늘 줄 제외)
       python dashboard_collect.py --allow-today --tag 1540   (15:40 실행용: 오늘 시세 포함, 투자자별은 잠정 표시)
       python dashboard_collect.py --days 30  (더 길게)
결과:  dashboard_YYYYMMDD/ 폴더와 dashboard_YYYYMMDD.zip — 이 zip 하나를 대화에 첨부하면 된다.

언제:  평일 18:40 (KST) 한 번. KRX 투자자별 확정치가 18:30에 나오고, 시세·ETF는 장 마감 뒤 확정이라 이 시각이면 그날치가 다 들어온다.
       금투협(신용·예탁금·반대매매)은 기준일 다음 영업일 아침 07시 이후에 올라오므로 18:40 실행이면 '어제분까지' 들어온다. (오늘분은 내일 저녁 실행 때 들어옴)
       장중(15:30 전)에 돌리면 오늘 날짜 줄은 장중 잠정치라 저장하지 않는다.

준비:  pip install pykrx requests pandas
       (KRX 정보데이터시스템 접속이 막힌 회사망에서는 pykrx·ETF 항목이 실패한다. 집 PC나 휴대폰 핫스팟에서 돌리면 된다.)

수집 항목(각각 따로 성공/실패를 README.txt에 적는다):
  01 코스피 일별 시세(시가·고가·저가·종가·거래량·거래대금·시가총액)      pykrx(KRX)
  02 코스피200 일별 시세                                              pykrx(KRX)
  03 코스피 투자자별 순매수 거래대금(상세 12구분, 원)                    pykrx(KRX, 18:30 확정치)
  04 KODEX 레버리지(122630) 시세·NAV·기초지수                          pykrx(KRX)
  05 KODEX 레버리지 시가총액·순자산·상장좌수(설정·환매 계산용)              KRX 정보데이터시스템 'ETF 개별종목 시세 추이' 화면 API
  06 KODEX 레버리지 투자자별 순매수(원)                                 pykrx(KRX, etf=True)
  07 금투협 증시자금추이(예탁금·파생예수금·RP·미수금·반대매매·비중)          FreeSIS 화면 API (백업용 — 대시보드 쪽에서도 공개 저장소로 받음)
  08 금투협 신용공여 잔고 추이(신용융자·대주·담보융자)                      FreeSIS 화면 API (백업용)
  09 코스피200 선물 야간시장 일별(근월물 시가·고가·저가·종가·대비·거래량·미결제)        KRX 정보데이터시스템 [15002] 개별종목 시세 추이(시장구분 야간 = aggBasTpCd 2) · 09b 차트로그 일별 이력(대조·예비)
  10 VKOSPI 시가·고가·저가·종가                                        KRX Open API(무료 인증키 필요: 아래) — 기준일 다음 날 아침에 열림
  10b VKOSPI 당일 값                                                  KRX 정보데이터시스템 [11012] 개별지수 시세 추이(코스피 200 변동성지수) — 16:10 이후 실행에서 오늘 줄 포함
  11 (15:40 실행) 오늘 투자자별 잠정치 · 코스피 종가 보충                   다음 금융 화면 API(원천 KRX 잠정치) · 종가는 네이버·다음 실시간 값 대조
  13 미국 VIX 종가                                                   CBOE 공식 일별 파일 > FRED > 야후 > 네이버 — 뉴욕 기준 장이 끝난 날만, 출처끼리 대조
  14 유가(참고 칸)                                                    WTI·브렌트 선물 근월물 종가(야후)
  15 지수 대조                                                       네이버·다음 실시간 종가(코스피·코스피200·코스닥·선물) — KRX 값 검증, 15:40 실행의 마감 확인 기준
  status.json                                                       항목별 성공·실패·주의·참고(자료 점검 health_check.py 가 읽는다)

KRX Open API 키(10번용, 한 번만): openapi.krx.co.kr 회원가입 → 인증키 신청 → '지수 > 파생상품지수 일별시세' 서비스 이용신청(승인까지 1~2일)
  → 받은 키를 이 파일과 같은 폴더의 krx_api_key.txt 에 한 줄로 저장(또는 환경변수 KRX_API_KEY).
KRX 정보데이터시스템 로그인(선택): 익명으로 막히면 data.krx.co.kr 회원가입 뒤 환경변수 KRX_ID, KRX_PW 를 넣으면 pykrx가 로그인해서 받는다.
  실행 때 'KRX 로그인 실패: KRX_ID 또는 KRX_PW ...' 한 줄이 찍히는 건 pykrx 안내문이라 무시해도 된다(로그인 없이도 받아진다).
"""
import argparse, datetime as dt, json, os, sys, time, zipfile, shutil
import pandas as pd, requests

KST = dt.timezone(dt.timedelta(hours=9))
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36'
ETF = {'code': '122630', 'isin': 'KR7122630007', 'name': 'KODEX 레버리지'}
ok, fail, warn, info = [], [], [], []      # warn: 받았지만 주의가 필요한 것(출처 간 불일치 등) · info: 참고(오류 아님)
KRX_TODAY_OK = None                         # 15:40 실행에서 KRX 당일 값이 마감 값으로 확인됐는지(None=해당 없음, False=아직 마감 전 값)

def log(m): print(f'[{dt.datetime.now(KST):%H:%M:%S}] {m}', flush=True)

def save(df, path, name):
    if df is None or len(df) == 0: raise ValueError('빈 데이터')
    df.to_csv(path, index=False, encoding='utf-8-sig'); ok.append(name); log(f'저장 {os.path.basename(path)} ({len(df)}행, {df.iloc[0,0]}~{df.iloc[-1,0]})')

ALLOW_TODAY = False   # --allow-today: 15:35 이후면 오늘 줄도 넣고(시세는 확정, 투자자별은 18:30 전이면 잠정), 그 전엔 뺀다
def cutoff_dates(df, datecol, today, now, prelim_col=None):
    """오늘 날짜 줄 처리. 기본: 18:30 전이면 오늘 줄 제외. --allow-today: 15:35 이후면 포함하고 prelim_col 이 있으면 18:30 전 오늘 줄에 잠정=1 표시."""
    df = df.copy(); d = pd.to_datetime(df[datecol]).dt.date
    keep_today = now.time() >= dt.time(18, 30) or (ALLOW_TODAY and now.time() >= dt.time(15, 35))
    if keep_today and KRX_TODAY_OK is False and now.time() < dt.time(18, 30): keep_today = False   # KRX 화면이 아직 마감 전 값(20분 지연) → 오늘 줄 제외(종가는 실시간 출처로 보충)
    if not keep_today: df = df[d < today]
    if prelim_col and ALLOW_TODAY and now.time() < dt.time(18, 30):
        df[prelim_col] = (pd.to_datetime(df[datecol]).dt.date == today).astype(int)
    return df

# ---------------------------------------------------------------- pykrx (KRX 정보데이터시스템)
def krx_items(s8, e8, today, now, out):
    from pykrx import stock
    # 01 코스피 · 02 코스피200
    for code, fn in (('1001', '01_코스피_일별시세'), ('1028', '04_코스피200_일별')):
        try:
            df = stock.get_index_ohlcv(s8, e8, code).reset_index().rename(columns={'날짜': '날짜'})
            df = cutoff_dates(df, '날짜', today, now); df['날짜'] = pd.to_datetime(df['날짜']).dt.strftime('%Y-%m-%d')
            save(df, f'{out}/{fn}.csv', fn)
        except Exception as e: fail.append((fn, repr(e)))
    # 03 투자자별(상세) — 거래대금 순매수(원)
    for on, fn in (('순매수', '03_코스피_투자자별_순매수_거래대금'),):
        try:
            df = stock.get_market_trading_value_by_date(s8, e8, 'KOSPI', detail=True, on=on).reset_index()
            df = cutoff_dates(df, '날짜', today, now, prelim_col='잠정'); df['날짜'] = pd.to_datetime(df['날짜']).dt.strftime('%Y-%m-%d')
            save(df, f'{out}/{fn}.csv', fn)
        except Exception as e: fail.append((fn, repr(e)))
    # 04 ETF 시세
    fn = f"04_ETF시세_{ETF['code']}_{ETF['name']}"
    try:
        df = stock.get_etf_ohlcv_by_date(s8, e8, ETF['code']).reset_index()
        df = cutoff_dates(df, '날짜', today, now); df['날짜'] = pd.to_datetime(df['날짜']).dt.strftime('%Y-%m-%d')
        save(df, f'{out}/{fn}.csv', fn)
    except Exception as e: fail.append((fn, repr(e)))
    # 06 ETF 투자자별(개별종목 일별, 거래대금 순매수 원) — KRX 화면 [13207] 과 같은 호출(pykrx 핵심 클래스, MDCSTAT04902). 당일분은 18시 이후 제공
    fn = f"06_ETF투자자별_{ETF['code']}_{ETF['name']}"
    try:
        from pykrx.website.krx.etx.core import ETF_투자자별거래실적_개별종목_일별추이
        raw = ETF_투자자별거래실적_개별종목_일별추이().fetch(s8, e8, ETF['isin'], 1, 1)
        if raw is None or not len(raw): raise ValueError('빈 데이터')
        df = pd.DataFrame({'날짜': pd.to_datetime(raw['TRD_DD'], format='%Y/%m/%d').dt.strftime('%Y-%m-%d'),
                           '기관합계': raw.get('NUM_ITM_VAL21'), '기타법인': raw.get('NUM_ITM_VAL22'), '개인': raw.get('NUM_ITM_VAL23'), '외국인합계': raw.get('NUM_ITM_VAL24'), '전체': raw.get('NUM_ITM_VAL25')})
        for c in df.columns[1:]: df[c] = pd.to_numeric(df[c].astype(str).str.replace(',', ''), errors='coerce')
        df = df.sort_values('날짜'); df = cutoff_dates(df, '날짜', today, now)
        save(df, f'{out}/{fn}.csv', fn)
    except Exception as e: fail.append((fn, repr(e) + ' — 실패하면 KRX 정보데이터시스템 > 증권상품 > ETF > 거래실적 > 투자자별 거래실적(개별종목) KODEX 레버리지'))

# ---------------------------------------------------------------- 05 ETF 개별종목 시세 추이(시가총액·순자산·상장좌수 포함) — KRX 화면 [13103], pykrx 핵심 클래스(MDCSTAT04501)
def krx_etf_detail(s8, e8, today, now, out):
    fn = f"05_ETF상세_{ETF['code']}_{ETF['name']}"
    try:
        from pykrx.website.krx.etx.core import 개별종목시세_ETF
        raw = 개별종목시세_ETF().fetch(s8, e8, ETF['isin'])
        if raw is None or not len(raw): raise ValueError('빈 데이터')
        df = raw.copy()
        for c in df.columns:
            if c not in ('TRD_DD', 'IDX_IND_NM', 'FLUC_TP_CD', 'FLUC_TP_CD1'): df[c] = pd.to_numeric(df[c].astype(str).str.replace(',', '').replace({'-': None, '': None}), errors='coerce')
        df['날짜'] = pd.to_datetime(df['TRD_DD'], format='%Y/%m/%d', errors='coerce').dt.strftime('%Y-%m-%d')
        df = df.sort_values('날짜'); df = cutoff_dates(df, '날짜', today, now)
        ren = {'TDD_CLSPRC': '종가', 'CMPPREVDD_PRC': '대비', 'FLUC_RT': '등락률', 'LST_NAV': 'NAV', 'NAV': 'NAV', 'TDD_OPNPRC': '시가', 'TDD_HGPRC': '고가', 'TDD_LWPRC': '저가', 'ACC_TRDVOL': '거래량', 'ACC_TRDVAL': '거래대금',
               'MKTCAP': '시가총액', 'INVSTASST_NETASST_TOTAMT': '순자산총액', 'LIST_SHRS': '상장좌수', 'IDX_IND_NM': '기초지수명', 'OBJ_STKPRC_IDX': '기초지수종가', 'CMPPREVDD_IDX': '기초지수대비', 'FLUC_RT1': '기초지수등락률'}
        cols = ['날짜'] + [c for c in df.columns if c not in ('날짜', 'TRD_DD')]
        df = df[cols].rename(columns=ren)
        save(df, f'{out}/{fn}.csv', fn)
    except Exception as e: fail.append((fn, repr(e) + ' — 실패하면 KRX 정보데이터시스템 > 증권상품 > ETF > 개별종목 시세 추이에서 KODEX 레버리지(상장좌수 열이 있는 화면)'))

# ---------------------------------------------------------------- 09 야간선물
# 2026-11-15 고침: 옛 방식(파생상품 전종목 시세 MDCSTAT12501 에 mktTpCd 를 바꿔 넣기)은 어떤 값을 넣어도 '(주간)' 행만 와서 10/28부터 매 실행 실패했다(실패가 알림에 드러나지 않았음).
#   KRX 화면의 시장구분 조건 이름은 aggBasTpCd 다('' 전체 · '0' 정규 · '2' 야간). 야간 행은 [15002] 개별종목 시세 추이(MDCSTAT12601)에 종목(근월물 ISIN)을 주고 aggBasTpCd='2' 로 받는다.
#   날짜 표기는 KRX 기준 '야간거래 종료일(T+1 거래일)' — 금요일 저녁장은 다음 월요일 날짜로 나온다(통합 원자료 「야간선물_일별」의 일자와 같은 기준).
#   09  = KRX 공식 값(시가·고가·저가·종가·대비·거래량·미결제)
#   09b = 차트로그(chartlog.net) 일별 이력(세션 시작일·종가·대비·미결제) — 대조용, KRX 가 실패한 날의 예비. robots.txt 가 허용하는 쪽 하나만 연다(/api/ 는 쓰지 않는다).
#         2026-03-13~11-13 대조: KRX 원자료와 종가 150/152일 일치, 「종가 − 대비 = 그날 주간 선물 종가」 164/165일 일치.
NIGHT_URL = 'https://chartlog.net/stats/market-index/kospi-night-futures/'
def _front_isins(s8, e8):
    """기간의 첫 거래일·마지막 거래일에 거래량이 가장 많은 코스피200 선물 종목(근월물) ISIN 목록. 만기 주에는 두 개가 된다."""
    from pykrx.website.krx.future.core import 전종목시세
    num = lambda v: pd.to_numeric(str(v).replace(',', ''), errors='coerce')
    days = list(pd.bdate_range(pd.to_datetime(s8), pd.to_datetime(e8))); found = {}
    for seq in (reversed(days), days):
        for d in seq:
            js = 전종목시세().read(trdDd=d.strftime('%Y%m%d'), prodId='KRDRVFUK2I', aggBasTpCd='0', rghtTpCd='T', mktTpCd='T')
            fut = [r for r in (js.get('output') or []) if ' F ' in str(r.get('ISU_NM', '')) and pd.notna(num(r.get('ACC_TRDVOL')))]
            time.sleep(0.4)
            if fut:
                b = max(fut, key=lambda r: num(r.get('ACC_TRDVOL'))); found[str(b['ISU_CD'])] = str(b.get('ISU_NM', '')); break
    return found
def night_futures(s8, e8, today, now, out):
    fn = '09_야간선물_일별'
    try:
        import re as _re
        from pykrx.website.krx.krxio import KrxWebIo
        class _Isu(KrxWebIo):
            @property
            def bld(self): return 'dbms/MDC/STAT/standard/MDCSTAT12601'
        num = lambda v: pd.to_numeric(str(v).replace(',', ''), errors='coerce')
        isins = _front_isins(s8, e8)
        if not isins: raise ValueError('근월물 종목을 못 찾음(전종목 시세 응답 없음)')
        e9 = (pd.Timestamp(today) + pd.Timedelta(days=5)).strftime('%Y%m%d')      # 금요일 저녁장은 다음 거래일 날짜로 나오므로 끝 날짜를 넉넉히
        rows = []
        for isin, nm in isins.items():
            js = _Isu().read(isuCd=isin, isuCd2=isin, strtDd=s8, endDd=e9, aggBasTpCd='2', rghtTpCd='T')
            mm = _re.search(r'F\s*(\d{4})(\d{2})', nm); wol = f'{mm.group(1)}-{mm.group(2)}물' if mm else nm
            for x in js.get('output') or []:
                td = str(x.get('TRD_DD', ''))
                if '야간' not in td: continue                                    # 날짜 뒤에 '(야간)' 이 붙은 행만(조건이 안 먹어 주간 행이 오면 버린다)
                d = pd.to_datetime(td[:10], format='%Y/%m/%d', errors='coerce'); c = num(x.get('TDD_CLSPRC')); v = num(x.get('ACC_TRDVOL'))
                if pd.isna(d) or pd.isna(c) or pd.isna(v) or v < 1000: continue
                rows.append({'일자': d.strftime('%Y-%m-%d'), '월물': wol, '시가': num(x.get('TDD_OPNPRC')), '고가': num(x.get('TDD_HGPRC')), '저가': num(x.get('TDD_LWPRC')), '종가': c, '대비': num(x.get('CMPPREVDD_PRC')),
                             '거래량': v, '미결제약정': num(x.get('ACC_OPNINT_QTY')), '원본': 'KRX 정보데이터시스템 [15002] 개별종목 시세 추이(시장구분 야간, 근월물)'})
            time.sleep(0.6)
        if not rows: raise ValueError(f"야간 행이 없음(종목 {list(isins.values())}) — KRX 화면 > 파생상품 > 종목시세 > 개별종목 시세 추이에서 시장구분 '야간'으로 확인")
        df = pd.DataFrame(rows).sort_values(['일자', '거래량']).drop_duplicates('일자', keep='last').sort_values('일자')   # 같은 날 두 종목이면 거래량 많은 쪽(근월물)
        save(df.reset_index(drop=True), f'{out}/{fn}.csv', fn)
    except Exception as e: fail.append((fn, repr(e)))
    fn = '09b_야간선물_공개'
    try:
        import re as _re
        r = requests.get(NIGHT_URL, headers={'User-Agent': UA, 'Accept-Language': 'ko-KR,ko;q=0.9'}, timeout=40); r.raise_for_status()
        u = r.text.replace('\\"', '"')
        i = u.find('"historicalData":[{"')
        if i < 0: raise ValueError('일별 이력(historicalData)을 못 찾음 — 쪽 구조가 바뀜')
        j = u.find(']', i); arr = _re.sub(r'"\$-?0"', '0', u[i + len('"historicalData":'):j + 1])
        H = pd.DataFrame(json.loads(arr))
        if not {'date', 'close_price', 'change_value'}.issubset(H.columns) or len(H) < 20: raise ValueError(f'이력 열·행 수가 예상과 다름: {list(H.columns)} {len(H)}행')
        H = H.rename(columns={'date': '세션일', 'close_price': '종가', 'change_value': '대비', 'change_rate': '등락률', 'volume': '미결제약정'})
        for c in ('종가', '대비', '등락률', '미결제약정'):
            if c in H.columns: H[c] = pd.to_numeric(H[c], errors='coerce')
        H['시가'] = float('nan'); H['고가'] = float('nan'); H['저가'] = float('nan')
        m = _re.search(r'"initialData":\{"timestamp":"(\d{8}) (\d\d:\d\d:\d\d)"[^{}]*?"price":([\d.]+)[^{}]*?"session_open":([\d.]+),"session_high":([\d.]+),"session_low":([\d.]+)\}', u)
        ms = _re.search(r'"sessionDateStr":"(\d{8})"', u)
        if m and ms:   # 마지막 세션의 시가·고가·저가(끝난 세션이고 종가가 이력의 마지막 줄과 같을 때만)
            sd = f'{ms.group(1)[:4]}-{ms.group(1)[4:6]}-{ms.group(1)[6:]}'; hit = H.index[H['세션일'] == sd]
            if len(hit) and abs(float(m.group(3)) - float(H.at[hit[0], '종가'])) < 0.011 and '05:55:00' <= m.group(2) <= '06:10:00':
                H.at[hit[0], '시가'] = float(m.group(4)); H.at[hit[0], '고가'] = float(m.group(5)); H.at[hit[0], '저가'] = float(m.group(6))
        H = H.dropna(subset=['종가', '대비']).sort_values('세션일')
        H['원본'] = '차트로그(chartlog.net) 코스피200 야간선물 일별 이력 — 비공식 출처(대조·예비용)'
        save(H[['세션일', '종가', '대비', '등락률', '미결제약정', '시가', '고가', '저가', '원본']].tail(60).reset_index(drop=True), f'{out}/{fn}.csv', fn)
    except Exception as e: warn.append((fn, '대조용 공개 출처 실패: ' + repr(e)[:160]))

def _krx_key():
    kf = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'krx_api_key.txt')
    return os.environ.get('KRX_API_KEY') or (open(kf, encoding='utf-8').read().strip() if os.path.exists(kf) else '')

# ---------------------------------------------------------------- 10 VKOSPI 시가·고가·저가·종가: KRX Open API(인증키) 파생상품지수 일별시세
def vkospi_ohlc(s8, e8, today, now, out):
    fn = '10_VKOSPI_일별'
    key = os.environ.get('KRX_API_KEY') or (open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'krx_api_key.txt'), encoding='utf-8').read().strip() if os.path.exists(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'krx_api_key.txt')) else '')
    if not key: fail.append((fn, '건너뜀 — KRX Open API 키 없음(krx_api_key.txt). 종가는 대시보드 쪽에서 공개 자료로 받으므로 없어도 됨')); return
    try:
        import time as _t
        s = requests.Session(); s.headers['AUTH_KEY'] = key; s.headers['User-Agent'] = UA
        rows = []
        for d in pd.bdate_range(pd.to_datetime(s8), pd.to_datetime(e8)):
            if d.date() >= today: continue           # 기준일 D의 값은 D+1 아침에 열림
            r = s.get('https://data-dbg.krx.co.kr/svc/apis/idx/drvprod_dd_trd', params={'basDd': d.strftime('%Y%m%d')}, timeout=30); js = r.json()
            if str(js.get('respCode')) == '401': raise ValueError("KRX Open API '파생상품지수 일별시세' 미승인(401) — openapi.krx.co.kr 에서 서비스 이용신청")
            for x in js.get('OutBlock_1', []):
                nm = x.get('IDX_NM', '')
                if nm.replace(' ', '') == '코스피200변동성지수':      # VKOSPI 만. '최소변동성지수'·'가치저변동성'·'변동성매칭 양매도' 등은 다른 지수(10/12~30 오염 원인)
                    g = lambda k: pd.to_numeric(str(x.get(k, '')).replace(',', ''), errors='coerce')
                    rows.append({'일자': d.strftime('%Y-%m-%d'), '지수명': nm, '시가': g('OPNPRC_IDX'), '고가': g('HGPRC_IDX'), '저가': g('LWPRC_IDX'), '종가': g('CLSPRC_IDX'), '원본': 'KRX Open API idx/drvprod_dd_trd'})
            _t.sleep(0.3)
        if not rows: raise ValueError('응답에 변동성지수 행 없음')
        save(pd.DataFrame(rows), f'{out}/{fn}.csv', fn)
    except Exception as e: fail.append((fn, repr(e)))

# ---------------------------------------------------------------- 금투협 FreeSIS (백업)
FREESIS = {'07_금투협_증시자금추이': 'STATSCU0100000060BO', '08_금투협_신용공여잔고추이': 'STATSCU0100000070BO'}
def freesis_items(s8, e8, out):
    base = 'https://freesis.kofia.or.kr'
    warm = base + '/stat/FreeSIS.do?parentDivId=MSIS10000000000000&serviceId=STATSCU0100000060'
    s = requests.Session(); s.headers['User-Agent'] = UA; s.headers['Referer'] = warm
    try: s.get(warm, timeout=30)      # 세션 쿠키 없이는 HTML 오류가 온다
    except Exception as e: log(f'freesis 워밍업 실패 {e!r}')
    for fn, obj in FREESIS.items():
        try:
            body = {'dmSearch': {'tmpV40': '1000000', 'tmpV41': '1', 'tmpV1': 'D', 'tmpV45': s8, 'tmpV46': e8, 'OBJ_NM': obj}}
            r = s.post(base + '/meta/getMetaDataList.do', json=body, timeout=30); js = r.json()
            if 'ds1' not in js: raise ValueError('예상 밖 응답 ' + str(js)[:150])
            df = pd.DataFrame(js['ds1'])
            cols = ['TMPV1'] + sorted([c for c in df.columns if c.startswith('TMPV') and c != 'TMPV1'], key=lambda c: int(c[4:]))
            df = df[cols].rename(columns={'TMPV1': '일자'}).sort_values('일자')
            save(df, f'{out}/{fn}.csv', fn)
        except Exception as e: fail.append((fn, repr(e)))

# ---------------------------------------------------------------- 11 다음 금융(장 마감 직후 잠정치) — 15:40 실행에서 KRX 03 파일에 오늘 줄이 없을 때만
DAUM = 'https://finance.daum.net/api'
def daum_session(ref):
    s = requests.Session(); s.headers.update({'User-Agent': UA, 'Referer': ref, 'Accept': 'application/json'}); return s
def daum_today(today, now, out, ref=None):
    if not ALLOW_TODAY or now.time() < dt.time(15, 35): return
    fn = '03_코스피_투자자별_순매수_거래대금'; path = f'{out}/{fn}.csv'
    try:
        df = pd.read_csv(path, encoding='utf-8-sig') if os.path.exists(path) else None
        if df is not None and (pd.to_datetime(df['날짜']).dt.date == today).any(): log('03 에 오늘 줄 있음(KRX) — 다음 금융 잠정치 생략')
        else:
            s = daum_session('https://finance.daum.net/domestic/investors')
            js = s.get(f'{DAUM}/investor/KOSPI/days', params={'details': 'true', 'page': 1, 'perPage': 5, 'pagination': 'true'}, timeout=30).json()
            t = [x for x in (js.get('data') or []) if str(x.get('date', ''))[:10] == today.isoformat()]
            if not t: raise ValueError('다음 금융에 오늘 줄 없음(아직 미공표)')
            x = t[0]; det = x.get('details') or {}; g = lambda k: det.get(k)
            fo_all = x.get('foreignStraightPurchasePrice'); etc_fo = g('ETC_FOREIGN') or 0
            row = {'날짜': today.isoformat(), '금융투자': g('FINANCIAL_INVESTOR'), '보험': g('INSURANCE_COMPANIES'), '투신': g('MUTUAL_FUND'), '사모': g('PRIVATE_EQUITY_FUND'), '은행': g('BANK'), '기타금융': g('ETC_FINANCIAL_INSTITUTION'),
                   '연기금': g('PENSION_FUND'), '기타법인': g('ETC_CORPORATION'), '개인': x.get('individualStraightPurchasePrice'),
                   '외국인': (fo_all - etc_fo) if fo_all is not None else None, '기타외국인': etc_fo, '전체': 0, '잠정': 1, '원본': '다음 금융 투자자별(KRX 잠정치, 장 마감 직후)'}   # 다음 foreign 은 기타외국인 포함 합계
            if df is None: df = pd.DataFrame(columns=[c for c in row if c != '원본'])
            if '잠정' not in df.columns: df['잠정'] = 0
            df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
            save(df, path, fn + '(오늘 잠정치 추가, 다음 금융)')
    except Exception as e: fail.append((fn + '(오늘 잠정치)', repr(e)))
    # 코스피 종가 보충: 01 이 실패했거나 오늘 줄이 없으면(KRX 화면이 아직 마감 전 값인 경우 포함) 종가만 실시간 출처에서(시가·고가·저가·거래량은 비움)
    fn = '01_코스피_일별시세'; path = f'{out}/{fn}.csv'
    try:
        df = pd.read_csv(path, encoding='utf-8-sig') if os.path.exists(path) else None
        if df is None or not (pd.to_datetime(df['날짜']).dt.date == today).any():
            rc, why = realtime_close(today, ref or {})
            if rc is not None:
                row = {'날짜': today.isoformat(), '시가': None, '고가': None, '저가': None, '종가': rc, '거래량': None, '거래대금': None, '상장시가총액': None}
                pd.DataFrame([{**row, '원본': f'실시간 지수 종가({why}, 장 마감 15:30 값) — KRX 화면은 20분 지연'}]).to_csv(f'{out}/01b_코스피_종가_실시간.csv', index=False, encoding='utf-8-sig'); ok.append(f'01b 코스피 종가(실시간 출처, {why})')
            else: fail.append(('01b 코스피 종가(실시간)', why))
    except Exception as e: fail.append(('01b 코스피 종가(실시간)', repr(e)))

# ---------------------------------------------------------------- 10b VKOSPI 당일 값: KRX 정보데이터시스템 [11012] 파생및기타지수 개별지수 시세 추이
# 2026-11-15 고침: 옛 탐색(12번)은 화면 번호를 못 찾아 매번 실패했고 VKOSPI 는 늘 다음 날 아침(Open API)에야 들어왔다 → 그날 VKOSPI 신호가 하루 늦게 판정됨.
#   화면 = MDCSTAT01201 (indTpCd=1, idxIndCd=300 → 코스피 200 변동성지수). 지수 코드가 바뀌어 다른 지수가 섞이는 일을 막으려고(10/12~30 오염 전례)
#   같은 날 전체지수 시세(MDCSTAT01001, 옵션지수 clssCd=0202)의 '코스피 200 변동성지수' 종가와 같은지 확인한 뒤에만 저장한다.
#   오늘 줄은 옵션 장 마감(15:45) + KRX 화면 지연 20분 뒤인 16:10 이후 실행에서만 넣는다(그 전 값은 장중 값).
def vkospi_krx(s8, e8, today, now, out):
    fn = '10b_VKOSPI_KRX화면'
    try:
        from pykrx.website.krx.krxio import KrxWebIo
        class _Series(KrxWebIo):
            @property
            def bld(self): return 'dbms/MDC/STAT/standard/MDCSTAT01201'
        class _All(KrxWebIo):
            @property
            def bld(self): return 'dbms/MDC/STAT/standard/MDCSTAT01001'
        g = lambda v: pd.to_numeric(str(v).replace(',', ''), errors='coerce')
        js = _Series().read(indTpCd='1', idxIndCd='300', idxCd='1', idxCd2='300', strtDd=s8, endDd=e8)
        rows = [{'일자': pd.to_datetime(x['TRD_DD'], format='%Y/%m/%d').strftime('%Y-%m-%d'), '지수명': '코스피 200 변동성지수', '시가': g(x.get('OPNPRC_IDX')), '고가': g(x.get('HGPRC_IDX')), '저가': g(x.get('LWPRC_IDX')), '종가': g(x.get('CLSPRC_IDX')),
                 '원본': 'KRX 정보데이터시스템 [11012] 개별지수 시세 추이(코스피 200 변동성지수)'} for x in js.get('output', [])]
        df = pd.DataFrame(rows).dropna(subset=['종가']).sort_values('일자') if rows else pd.DataFrame()
        if not len(df): raise ValueError('응답에 행 없음')
        if now.time() < dt.time(16, 10): df = df[df['일자'] < today.isoformat()]           # 오늘 값은 16:10 이후에만
        if not len(df): raise ValueError('확정된 날짜 행 없음')
        chk = df.iloc[-1]; ja = _All().read(trdDd=chk['일자'].replace('-', ''), clssCd='0202')
        ref = [g(x.get('CLSPRC_IDX')) for x in ja.get('output', []) if str(x.get('IDX_NM', '')).replace(' ', '') == '코스피200변동성지수']
        if not ref: raise ValueError(f"전체지수 시세에서 '코스피 200 변동성지수' 행을 못 찾음({chk['일자']}) — 지수 확인 불가라 저장하지 않음")
        if abs(float(ref[0]) - float(chk['종가'])) > 0.011: raise ValueError(f"지수 확인 실패: 시세 추이 {chk['종가']} ≠ 전체지수 시세 {ref[0]} ({chk['일자']}) — 다른 지수일 수 있어 저장하지 않음")
        df = df[(df['종가'] > 5) & (df['종가'] < 150)]
        save(df.reset_index(drop=True), f'{out}/{fn}.csv', fn)
    except Exception as e: fail.append((fn, repr(e)))

# ---------------------------------------------------------------- 15 실시간 출처 대조(네이버·다음): 코스피·코스피200·코스닥·선물(주간) 일별 종가
# KRX 화면 값이 맞는지 매 실행 대조하고, 15:40 실행에서는 장 마감 값이 KRX 화면에 반영됐는지 확인하는 기준으로 쓴다.
def _num(v):
    try: return float(str(v).replace(',', ''))
    except Exception: return float('nan')
def naver_days(code, n=12):
    r = requests.get(f'https://m.stock.naver.com/api/index/{code}/price', params={'pageSize': n, 'page': 1}, headers={'User-Agent': UA, 'Referer': 'https://m.stock.naver.com/'}, timeout=20)
    return {str(x['localTradedAt'])[:10]: _num(x['closePrice']) for x in r.json() if x.get('closePrice') not in (None, '')}
def daum_index_days(n=12):
    s = daum_session('https://finance.daum.net/domestic/index')
    js = s.get(f'{DAUM}/market_index/days', params={'market': 'KOSPI', 'page': 1, 'perPage': n, 'pagination': 'true'}, timeout=20).json()
    return {str(x['date'])[:10]: float(x['tradePrice']) for x in (js.get('data') or []) if x.get('tradePrice')}
def cross_refs(out):
    """15_지수_대조.csv 를 쓰고 {'kospi_naver': {...}, 'kospi_daum': {...}, ...} 를 돌려준다. 실패한 출처는 빠진다."""
    ref = {}
    for key, fnc in (('kospi_naver', lambda: naver_days('KOSPI')), ('kospi200_naver', lambda: naver_days('KPI200')), ('kosdaq_naver', lambda: naver_days('KOSDAQ')), ('fut_naver', lambda: naver_days('FUT')), ('kospi_daum', daum_index_days)):
        try: ref[key] = fnc()
        except Exception as e: info.append(('15_지수_대조 ' + key, repr(e)[:120]))
    if ref:
        dates = sorted(set().union(*[set(v) for v in ref.values()]))
        df = pd.DataFrame([{'date': d, **{k: v.get(d) for k, v in ref.items()}} for d in dates])
        try: save(df, f'{out}/15_지수_대조.csv', '15_지수_대조(네이버·다음 실시간 종가)')
        except Exception as e: info.append(('15_지수_대조', repr(e)[:120]))
    else: warn.append(('15_지수_대조', '네이버·다음 모두 실패 — 이번 실행은 KRX 값 대조 없음'))
    return ref
def realtime_close(today, ref):
    """오늘 코스피 종가(실시간 출처). 네이버·다음이 0.011 안으로 같으면 그 값, 한 곳뿐이면 그 값(출처 1곳 표시). 반환 (값, 설명) 또는 (None, 이유)."""
    t = today.isoformat(); a = ref.get('kospi_naver', {}).get(t); b = ref.get('kospi_daum', {}).get(t)
    if a is not None and b is not None:
        if abs(a - b) <= 0.011: return a, '네이버·다음 일치'
        return None, f'네이버 {a} ≠ 다음 {b}'
    if a is not None: return a, '네이버 1곳'
    if b is not None: return b, '다음 1곳'
    return None, '오늘 줄 없음(휴장이거나 아직 미공표)'
def wait_krx_final(today, out, limit=dt.time(16, 4), step=45):
    """15:40 실행 전용. KRX 정보데이터시스템은 20분 늦게 보여 15:50 전에는 마감 전 값이 온다(11/11·12·13 사흘 연속 오후 알림의 종가가 틀렸음: 5,297.51 ↔ 실제 5,290.53 등).
       실시간 출처(네이버·다음)의 오늘 종가와 KRX 화면의 오늘 종가가 같아질 때까지 기다린다(최대 16:04). 같아지면 True, 끝내 다르면 False(오늘 줄은 KRX 에서 받지 않고 종가만 실시간 출처로 넣는다)."""
    global KRX_TODAY_OK
    from pykrx import stock
    ref = cross_refs(out); rc, why = realtime_close(today, ref)
    if rc is None:
        info.append(('15:40 마감 확인', f'실시간 종가 없음({why}) — KRX 값 확인을 건너뜀')); KRX_TODAY_OK = None; return ref
    t8 = today.strftime('%Y%m%d'); last = None
    while True:
        try:
            df = stock.get_index_ohlcv(t8, t8, '1001'); last = float(df['종가'].iloc[-1]) if len(df) else None
        except Exception as e: last = None
        if last is not None and abs(last - rc) <= 0.011:
            KRX_TODAY_OK = True; log(f'KRX 오늘 종가 {last} = 실시간 {rc}({why}) — 마감 값 확인'); return ref
        if dt.datetime.now(KST).time() >= limit: break
        log(f'KRX 오늘 종가 {last} ≠ 실시간 {rc}({why}) — 마감 값 반영을 기다림({step}초)'); time.sleep(step)
    KRX_TODAY_OK = False
    warn.append(('15:40 마감 확인', f'KRX 화면 오늘 종가 {last} 가 {limit:%H:%M}까지 실시간 종가 {rc}({why})와 달라 오늘 줄은 KRX 에서 받지 않음 — 종가만 실시간 출처로 넣고 나머지는 저녁 실행에서 채움'))
    return ref

# ---------------------------------------------------------------- 13 미국 VIX 종가. 결과: 13_VIX_일별.csv (date, close, source, n_src, spread, others)
# 2026-11-15 고침: 야후 일봉에는 '아직 끝나지 않은 날'(개장 전·장중)의 값이 그날 날짜로 들어 있다. 그 값이 종가로 저장돼
#   11/2~11/13 값이 전부 틀렸고(11/5 16.83 ↔ 실제 28.18), 11/13 「최적화 2위」 매수 신호가 잘못 켜졌다.
#   → ① 뉴욕 시각으로 장이 끝난 날(16:30 이후)까지만 받는다 ② 출처 여러 곳(CBOE 공식 파일·야후·네이버·FRED)을 모두 받아 서로 대조한다
#     ③ 우선순위는 CBOE 공식 > FRED(CBOE 종가) > 야후 > 네이버, 출처끼리 0.05 넘게 다르면 README·status.json 에 적는다(stooq 는 봇 차단으로 뺌).
def us_final_date(now_utc=None):
    """미국 정규장이 끝나 종가가 확정된 마지막 날짜(뉴욕 기준). VIX 는 16:15 마감 → 16:30 이후면 오늘, 아니면 어제."""
    from zoneinfo import ZoneInfo
    n = (now_utc or dt.datetime.now(dt.timezone.utc)).astimezone(ZoneInfo('America/New_York'))
    return n.date() if n.time() >= dt.time(16, 30) else n.date() - dt.timedelta(days=1)
def _vix_sources(cut):
    """출처별 {날짜: 종가}. cut(뉴욕 기준 확정된 마지막 날짜) 뒤 날짜는 버린다."""
    import io
    from zoneinfo import ZoneInfo
    src = {}; ny = ZoneInfo('America/New_York')
    def keep(d): return bool(d) and d <= cut.isoformat()
    try:   # CBOE 공식 일별 파일(DATE MM/DD/YYYY, OPEN, HIGH, LOW, CLOSE)
        r = requests.get('https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv', headers={'User-Agent': UA}, timeout=40); r.raise_for_status()
        d = pd.read_csv(io.StringIO(r.text)); d.columns = [c.strip().upper() for c in d.columns]
        dd = pd.to_datetime(d['DATE'], format='%m/%d/%Y', errors='coerce').dt.strftime('%Y-%m-%d'); cc = pd.to_numeric(d['CLOSE'], errors='coerce')
        src['CBOE 공식 일별 파일(VIX_History.csv)'] = {a: round(float(b), 2) for a, b in zip(dd, cc) if isinstance(a, str) and pd.notna(b) and keep(a)}
    except Exception as e: fail.append(('13_VIX CBOE', repr(e)))
    try:   # 야후: 봉 시각을 뉴욕 날짜로 바꾸고, 끝나지 않은 날은 버린다
        r = requests.get('https://query1.finance.yahoo.com/v8/finance/chart/%5EVIX', params={'range': '3mo', 'interval': '1d'}, headers={'User-Agent': UA}, timeout=30); js = r.json()
        res = js['chart']['result'][0]; ts = res['timestamp']; cl = res['indicators']['quote'][0]['close']
        y = {}
        for t, c in zip(ts, cl):
            if c is None: continue
            d = dt.datetime.fromtimestamp(t, ny).strftime('%Y-%m-%d')
            if keep(d): y[d] = round(float(c), 2)
        src['Yahoo Finance ^VIX'] = y
    except Exception as e: fail.append(('13_VIX 야후', repr(e)))
    try:   # 네이버 세계지수(.VIX, 15분 지연 — 끝난 날만)
        r = requests.get('https://api.stock.naver.com/index/.VIX/price', params={'page': 1, 'pageSize': 60}, headers={'User-Agent': UA, 'Referer': 'https://m.stock.naver.com/'}, timeout=20)
        nv = {}
        for x in r.json():
            d = str(x.get('localTradedAt', ''))[:10]; c = _num(x.get('closePrice'))
            if keep(d) and c == c: nv[d] = round(c, 2)
        src['네이버 세계지수 .VIX'] = nv
    except Exception as e: info.append(('13_VIX 네이버', repr(e)[:120]))
    try:   # FRED(다음 날 올라옴). GitHub 실행기에서는 자주 시간 초과 → 짧게 한 번만, 실패해도 오류로 치지 않는다
        r = requests.get('https://fred.stlouisfed.org/graph/fredgraph.csv', params={'id': 'VIXCLS', 'cosd': (cut - dt.timedelta(days=120)).isoformat()}, headers={'User-Agent': UA}, timeout=8)
        d = pd.read_csv(io.StringIO(r.text)); d.columns = ['date', 'close']; d['close'] = pd.to_numeric(d['close'], errors='coerce'); d = d.dropna()
        src['FRED VIXCLS(CBOE 종가)'] = {str(a): round(float(b), 2) for a, b in zip(d['date'], d['close']) if keep(str(a))}
    except Exception as e: info.append(('13_VIX FRED', repr(e)[:80]))
    return {k: v for k, v in src.items() if v}
VIX_PRIORITY = ['CBOE 공식 일별 파일(VIX_History.csv)', 'FRED VIXCLS(CBOE 종가)', 'Yahoo Finance ^VIX', '네이버 세계지수 .VIX']
def vix_fetch(out, days=40, now_utc=None):
    fn = '13_VIX_일별'; cut = us_final_date(now_utc); src = _vix_sources(cut)
    if not src: fail.append((fn, '출처(CBOE·야후·네이버·FRED) 모두 실패')); return
    dates = sorted(set().union(*[set(v) for v in src.values()]))[-days:]
    rows = []; bad = []
    for d in dates:
        have = [(s, src[s][d]) for s in VIX_PRIORITY if s in src and d in src[s]]
        if not have: continue
        s0, v0 = have[0]; vals = [v for _, v in have]; spread = round(max(vals) - min(vals), 2)
        rows.append({'date': d, 'close': v0, 'source': s0, 'n_src': len(have), 'spread': spread, 'others': ' | '.join(f'{s.split(" ")[0]} {v}' for s, v in have[1:])})
        if spread > 0.05: bad.append(f'{d} ' + ' / '.join(f'{s.split(" ")[0]} {v}' for s, v in have))
    if not rows: fail.append((fn, f'확정된 날짜({cut}까지) 자료 없음')); return
    save(pd.DataFrame(rows), f'{out}/{fn}.csv', fn + f'(뉴욕 기준 {cut}까지 확정분, 출처 {len(src)}곳)')
    if bad: warn.append((fn, 'VIX 출처 간 차이 0.05 초과: ' + '; '.join(bad[-4:])))
    lastd = rows[-1]['date']
    if lastd < cut.isoformat() and (cut - dt.date.fromisoformat(lastd)).days >= 4: warn.append((fn, f'VIX 마지막 날짜 {lastd} — 확정 기준일 {cut}보다 4일 넘게 늦음'))

# ---------------------------------------------------------------- 14 유가(참고 칸, 계산에는 안 씀): WTI·브렌트 선물 근월물 종가(야후 CL=F·BZ=F) — 끝난 날만
# 「참고_VIX_유가」 시트의 유가 칸이 2026-10-14(EIA 현물가)에서 멈춰 있었다. 자동 경로가 없던 칸이라 선물 근월물 종가로 이어 붙인다(기준이 다르므로 출처 칸에 적는다).
def oil_fetch(out, days=45, now_utc=None):
    fn = '14_유가_일별'; cut = us_final_date(now_utc); cols = {}
    from zoneinfo import ZoneInfo
    ny = ZoneInfo('America/New_York')
    for name, sym in (('wti', 'CL%3DF'), ('brent', 'BZ%3DF')):
        try:
            r = requests.get(f'https://query1.finance.yahoo.com/v8/finance/chart/{sym}', params={'range': '3mo', 'interval': '1d'}, headers={'User-Agent': UA}, timeout=30); js = r.json()
            res = js['chart']['result'][0]; ts = res['timestamp']; cl = res['indicators']['quote'][0]['close']
            cols[name] = {dt.datetime.fromtimestamp(t, ny).strftime('%Y-%m-%d'): round(float(c), 2) for t, c in zip(ts, cl) if c is not None and dt.datetime.fromtimestamp(t, ny).date() <= cut}
        except Exception as e: info.append((fn + ' ' + name, repr(e)[:120]))
    if not cols: return
    dates = sorted(set().union(*[set(v) for v in cols.values()]))[-days:]
    df = pd.DataFrame([{'date': d, 'wti': cols.get('wti', {}).get(d), 'brent': cols.get('brent', {}).get(d), 'source': '선물 근월물 종가(Yahoo Finance CL=F·BZ=F)'} for d in dates])
    try: save(df, f'{out}/{fn}.csv', fn)
    except Exception as e: info.append((fn, repr(e)[:120]))

# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--days', type=int, default=10); ap.add_argument('--out', default='.'); ap.add_argument('--allow-today', action='store_true', help='15:35 이후 오늘 줄 포함(투자자별은 18:30 전이면 잠정 표시)'); ap.add_argument('--tag', default='')
    a = ap.parse_args(); now = dt.datetime.now(KST); today = now.date()
    global ALLOW_TODAY; ALLOW_TODAY = a.allow_today
    start = today - dt.timedelta(days=int(a.days * 1.6) + 3); s8, e8 = start.strftime('%Y%m%d'), today.strftime('%Y%m%d')
    tag = today.strftime('%Y%m%d') + (('_' + a.tag) if a.tag else ''); out = os.path.join(a.out, f'dashboard_{tag}'); os.makedirs(out, exist_ok=True)
    log(f'기간 {start}~{today} (장중이면 오늘 줄 제외) → {out}')
    # 15:40 실행: KRX 화면에 장 마감 값이 반영될 때까지 기다린다(실시간 출처와 대조). 그 밖의 실행: 대조 자료만 받는다
    ref = {}
    try:
        if ALLOW_TODAY and dt.time(15, 31) <= now.time() < dt.time(18, 30): ref = wait_krx_final(today, out); now = dt.datetime.now(KST)
        else: ref = cross_refs(out)
    except Exception as e: info.append(('15_지수_대조', repr(e)[:160]))
    try: krx_items(s8, e8, today, now, out)
    except Exception as e: fail.append(('pykrx', repr(e) + ' — pip install pykrx 했는지, KRX 접속이 되는지 확인'))
    krx_etf_detail(s8, e8, today, now, out)
    night_futures(s8, e8, today, now, out)
    vkospi_ohlc(s8, e8, today, now, out)
    vkospi_krx(s8, e8, today, now, out)
    freesis_items(s8, e8, out)
    daum_today(today, now, out, ref)
    vix_fetch(out)
    oil_fetch(out)
    # KRX 값 ↔ 실시간 출처 대조(같은 날짜의 코스피 종가가 0.011 넘게 다르면 주의)
    try:
        k1 = pd.read_csv(f'{out}/01_코스피_일별시세.csv', encoding='utf-8-sig'); bad = []
        for _, r in k1.tail(8).iterrows():
            for nm in ('kospi_naver', 'kospi_daum'):
                v = ref.get(nm, {}).get(str(r['날짜'])[:10])
                if v is not None and abs(float(r['종가']) - v) > 0.011: bad.append(f"{str(r['날짜'])[5:10]} KRX {float(r['종가']):,.2f} ≠ {nm.split('_')[1]} {v:,.2f}")
        if bad: warn.append(('01_코스피_일별시세', '코스피 종가 출처 간 불일치: ' + '; '.join(bad[:4])))
    except Exception as e: pass
    lines = [f'수집 {now:%Y-%m-%d %H:%M} KST · 기간 {start}~{today}' + (' · 오늘 줄 포함(투자자별 잠정)' if ALLOW_TODAY and now.time() < dt.time(18, 30) else ''), f'성공: {ok}', f'실패: {fail}', f'주의: {warn}', f'참고: {info}',
             '오늘 날짜 줄은 18:30 이후 실행분만 확정치로 포함(그 전 실행은 어제까지). 15:40 실행은 KRX 화면이 마감 값으로 바뀐 것을 실시간 출처와 대조해 확인한 뒤에만 오늘 줄을 넣는다.',
             '09 야간선물 = KRX 화면 개별종목 시세 추이(시장구분 야간) + 09b 차트로그 이력(대조·예비). 10 VKOSPI = KRX Open API(다음 날 아침) + 10b KRX 화면(당일 16:10 이후). 13 VIX = 뉴욕 기준 끝난 날만, 출처 여러 곳 대조.',
             '07·08 금투협 파일 열 이름(TMPV2…)은 화면 열 순서와 같다: 07 = 예탁금·파생예수금·RP·미수금·반대매매·비중, 08 = 신용융자 전체·유가·코스닥, 대주 전체·유가·코스닥, 청약자금대출, 담보융자.']
    json.dump({'run': f'{now:%Y-%m-%d %H:%M}', 'tag': a.tag, 'allow_today': bool(ALLOW_TODAY), 'krx_today_ok': KRX_TODAY_OK, 'ok': ok, 'fail': [list(x) for x in fail], 'warn': [list(x) for x in warn], 'info': [list(x) for x in info]},
              open(os.path.join(out, 'status.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    open(os.path.join(out, 'README.txt'), 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
    zp = os.path.join(a.out, f'dashboard_{tag}.zip')
    with zipfile.ZipFile(zp, 'w', zipfile.ZIP_DEFLATED) as z:
        for f in sorted(os.listdir(out)): z.write(os.path.join(out, f), arcname=f'dashboard_{tag}/{f}')
    log('\n'.join(lines)); log(f'zip: {zp}  ← 이 파일을 대화에 첨부')
    return 0 if ok else 1

if __name__ == '__main__': sys.exit(main())
