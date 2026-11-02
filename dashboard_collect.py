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
  09 코스피200 선물 야간시장 일별(근월물 시가·고가·저가·종가·대비·거래량·미결제)        KRX 정보데이터시스템 '파생상품 전종목 시세' 화면(시장구분 야간)
  10 VKOSPI 시가·고가·저가·종가                                        KRX Open API(무료 인증키 필요: 아래) — 키가 없으면 건너뜀(종가는 대시보드 쪽에서 공개 자료로 받음)
  11 (15:40 실행) 오늘 투자자별 잠정치 · 코스피 종가 보충                   다음 금융 화면 API(원천 KRX 잠정치) — 03 에 오늘 줄이 없을 때만 잠정=1 로 덧붙임
  12 VKOSPI 당일 종가 탐색                                            KRX 정보데이터시스템 파생상품지수 화면(화면 번호를 실행 때 찾음; 못 찾으면 건너뜀 — 다음 날 10번·공개 저장소로 보충)
  13 미국 VIX 종가                                                   야후 파이낸스 → stooq → FRED 순으로 시도(어느 것이든 받으면 저장)

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
ok, fail = [], []

def log(m): print(f'[{dt.datetime.now(KST):%H:%M:%S}] {m}', flush=True)

def save(df, path, name):
    if df is None or len(df) == 0: raise ValueError('빈 데이터')
    df.to_csv(path, index=False, encoding='utf-8-sig'); ok.append(name); log(f'저장 {os.path.basename(path)} ({len(df)}행, {df.iloc[0,0]}~{df.iloc[-1,0]})')

ALLOW_TODAY = False   # --allow-today: 15:35 이후면 오늘 줄도 넣고(시세는 확정, 투자자별은 18:30 전이면 잠정), 그 전엔 뺀다
def cutoff_dates(df, datecol, today, now, prelim_col=None):
    """오늘 날짜 줄 처리. 기본: 18:30 전이면 오늘 줄 제외. --allow-today: 15:35 이후면 포함하고 prelim_col 이 있으면 18:30 전 오늘 줄에 잠정=1 표시."""
    df = df.copy(); d = pd.to_datetime(df[datecol]).dt.date
    keep_today = now.time() >= dt.time(18, 30) or (ALLOW_TODAY and now.time() >= dt.time(15, 35))
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

# ---------------------------------------------------------------- 09 야간선물: KRX '파생상품 전종목 시세' 화면(MDCSTAT12501)을 날짜마다 시장구분=야간으로 조회
# pykrx 자체 호출과 같게 rghtTpCd='T'(권리 전체)를 꼭 붙인다 — 빠지면 빈 응답. mktTpCd T(전체)면 '(주간)'·'(야간)' 행이 함께 온다
NIGHT_PARAM_CANDIDATES = [{'mktTpCd': 'T', 'rghtTpCd': 'T'}, {'mktTpCd': '2', 'rghtTpCd': 'T'}, {'mktTpCd': 'N', 'rghtTpCd': 'T'}, {'mktTpCd': '3', 'rghtTpCd': 'T'}, {'rghtTpCd': 'T'}, {}]
def _is_night(r): nm = str(r.get('ISU_NM', '')); return ('야간' in nm) or ('Night' in nm) or ('NIGHT' in nm.upper())
def night_futures(s8, e8, today, now, out):
    fn = '09_야간선물_일별'
    try:
        from pykrx.website.krx.future.core import 전종목시세
        import time as _t
        days = pd.bdate_range(pd.to_datetime(s8), pd.to_datetime(e8))
        if now.time() < dt.time(6, 30): days = days[days.date < today]       # 06:00 끝나는 야간장이 안 끝났으면 오늘 표기분 제외
        rows = []; found_param = None; seen_names = []
        for d in days:
            got = None
            for extra in ([found_param] if found_param is not None else NIGHT_PARAM_CANDIDATES):
                js = 전종목시세().read(trdDd=d.strftime('%Y%m%d'), prodId='KRDRVFUK2I', **extra)
                outp = js.get('output') or []
                night = [r for r in outp if _is_night(r)]
                if night: got = night; found_param = extra; break
                if outp and not seen_names: seen_names.extend(sorted({str(r.get('ISU_NM', ''))[-8:] for r in outp})[:6])
                _t.sleep(0.3)
            if not got: continue
            # 근월물(거래량 최대, 스프레드 제외)
            fut = [r for r in got if 'SP' not in str(r.get('ISU_NM', ''))]
            num = lambda v: pd.to_numeric(str(v).replace(',', ''), errors='coerce')
            best = max(fut, key=lambda r: num(r.get('ACC_TRDVOL')) if pd.notna(num(r.get('ACC_TRDVOL'))) else -1)
            if not pd.notna(num(best.get('TDD_CLSPRC'))) or num(best.get('ACC_TRDVOL')) < 1000: continue
            import re as _re; mm = _re.search(r'F\s*(\d{4})(\d{2})', str(best.get('ISU_NM'))); wol = f'{mm.group(1)}-{mm.group(2)}물' if mm else str(best.get('ISU_NM'))
            rows.append({'일자': d.strftime('%Y-%m-%d'), '월물': wol,
                         '시가': num(best.get('TDD_OPNPRC')), '고가': num(best.get('TDD_HGPRC')), '저가': num(best.get('TDD_LWPRC')), '종가': num(best.get('TDD_CLSPRC')),
                         '대비': num(best.get('CMPPREVDD_PRC')), '거래량': num(best.get('ACC_TRDVOL')), '미결제약정': num(best.get('ACC_OPNINT_QTY')),
                         '원본': 'KRX 정보데이터시스템 파생상품 전종목 시세(야간) ' + str(found_param)})
            _t.sleep(0.7)
        if not rows: raise ValueError('야간 시세 행을 못 찾음' + (f'(받은 종목명 끝부분 예: {seen_names})' if seen_names else '(응답 비어 있음)') + ' — KRX 정보데이터시스템 > 파생상품 > 종목시세 > 전종목 시세에서 시장구분 "야간"으로 받아 주세요')
        save(pd.DataFrame(rows), f'{out}/{fn}.csv', fn)
    except Exception as e: fail.append((fn, repr(e)))

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
def daum_today(today, now, out):
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
    # 코스피 종가 보충: 01 이 실패했거나 오늘 줄이 없으면 종가만(시가·고가·저가·거래량은 비움)
    fn = '01_코스피_일별시세'; path = f'{out}/{fn}.csv'
    try:
        df = pd.read_csv(path, encoding='utf-8-sig') if os.path.exists(path) else None
        if df is None or not (pd.to_datetime(df['날짜']).dt.date == today).any():
            s = daum_session('https://finance.daum.net/domestic/index')
            js = s.get(f'{DAUM}/market_index/days', params={'market': 'KOSPI', 'page': 1, 'perPage': 5, 'pagination': 'true'}, timeout=30).json()
            t = [x for x in (js.get('data') or []) if str(x.get('date', ''))[:10] == today.isoformat()]
            if t and t[0].get('tradePrice'):
                row = {'날짜': today.isoformat(), '시가': None, '고가': None, '저가': None, '종가': t[0]['tradePrice'], '거래량': None, '거래대금': None, '상장시가총액': None}
                pd.DataFrame([{**row, '원본': '다음 금융 지수(종가만, 원천 KRX)'}]).to_csv(f'{out}/01b_코스피_종가_다음.csv', index=False, encoding='utf-8-sig'); ok.append('01b 코스피 종가(다음 금융)')
    except Exception as e: fail.append(('01b 코스피 종가(다음)', repr(e)))

# ---------------------------------------------------------------- 12 VKOSPI 당일 종가 탐색: KRX 정보데이터시스템 '파생상품지수' 화면의 bld 를 메뉴에서 찾아 호출(못 찾으면 건너뜀)
def vkospi_probe(s8, e8, today, now, out):
    fn = '12_VKOSPI_탐색'
    try:
        s = requests.Session(); s.headers.update({'User-Agent': UA, 'Referer': 'https://data.krx.co.kr/contents/MDC/MDI/mdiLoader/index.cmd'})
        import re as _re
        html = s.get('https://data.krx.co.kr/contents/MDC/MAIN/main/index.cmd', timeout=30).text
        ids = _re.findall(r'menuId=(MDC\w+)[^>]*>[^<]*파생상품지수', html) or _re.findall(r'(MDC\d{10,})[^\n]{0,200}파생상품지수', html)
        blds = []
        for mid in dict.fromkeys(ids):
            page = s.get('https://data.krx.co.kr/contents/MDC/MDI/mdiLoader/loadmain.cmd', params={'menuId': mid}, timeout=30).text
            blds += _re.findall(r'dbms/MDC/STAT/standard/MDCSTAT\d{5}', page)
        blds = list(dict.fromkeys(blds)) or ['dbms/MDC/STAT/standard/MDCSTAT00901', 'dbms/MDC/STAT/standard/MDCSTAT01001', 'dbms/MDC/STAT/standard/MDCSTAT00801']
        rows = []
        for bld in blds:
            for params in ({'trdDd': today.strftime('%Y%m%d')}, {'trdDd': today.strftime('%Y%m%d'), 'idxIndMidclssCd': '01'}):
                try:
                    r = s.post('https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd', data={'bld': bld, 'locale': 'ko_KR', **params}, timeout=30); js = r.json()
                except Exception: continue
                for key in ('output', 'OutBlock_1', 'block1'):
                    for x in js.get(key, []) or []:
                        nm = str(x.get('IDX_NM', '')) + str(x.get('IDX_IND_NM', ''))
                        if nm.replace(' ', '') == '코스피200변동성지수':
                            g = lambda k: pd.to_numeric(str(x.get(k, '')).replace(',', ''), errors='coerce')
                            rows.append({'일자': today.isoformat(), '지수명': nm, '시가': g('OPNPRC_IDX'), '고가': g('HGPRC_IDX'), '저가': g('LWPRC_IDX'), '종가': g('CLSPRC_IDX'), '원본': f'KRX 정보데이터시스템 파생상품지수 {bld}'})
                if rows: break
            if rows: break
        if not rows: raise ValueError('파생상품지수 화면에서 변동성지수 행을 못 찾음(화면 번호 미확인) — 다음 날 10번(Open API)·공개 저장소로 보충')
        df = pd.DataFrame(rows[:1]); df = df[df['종가'].notna()]
        if now.time() < dt.time(15, 35): raise ValueError('장중 값이라 저장하지 않음')
        p10 = f'{out}/10_VKOSPI_일별.csv'
        if os.path.exists(p10):
            old = pd.read_csv(p10, encoding='utf-8-sig')
            if not (pd.to_datetime(old['일자']).dt.date == today).any(): df = pd.concat([old, df], ignore_index=True)
            else: df = old
        save(df, p10, fn + ' → 10_VKOSPI_일별 에 오늘 줄 추가')
    except Exception as e: fail.append((fn, repr(e)))

# ---------------------------------------------------------------- 13 미국 VIX 종가(야후 → stooq → FRED). 결과: 13_VIX_일별.csv (date, close, source)
def vix_fetch(out, days=40):
    fn = '13_VIX_일별'; got = None
    try:
        r = requests.get('https://query1.finance.yahoo.com/v8/finance/chart/%5EVIX', params={'range': '3mo', 'interval': '1d'}, headers={'User-Agent': UA}, timeout=30); js = r.json()
        res = js['chart']['result'][0]; ts = res['timestamp']; cl = res['indicators']['quote'][0]['close']
        got = pd.DataFrame({'date': [dt.datetime.fromtimestamp(t, dt.timezone(dt.timedelta(hours=-5))).strftime('%Y-%m-%d') for t in ts], 'close': cl}).dropna(); got['source'] = 'Yahoo Finance ^VIX'
        got['close'] = got['close'].round(2)
    except Exception as e: fail.append((fn + ' 야후', repr(e)))
    if got is None or not len(got):
        try:
            r = requests.get('https://stooq.com/q/d/l/', params={'s': '^vix', 'i': 'd'}, headers={'User-Agent': UA}, timeout=30)
            d = pd.read_csv(__import__('io').StringIO(r.text)); got = pd.DataFrame({'date': d['Date'], 'close': d['Close'], 'source': 'stooq ^VIX'}).tail(days)
        except Exception as e: fail.append((fn + ' stooq', repr(e)))
    if got is None or not len(got):
        try:
            r = requests.get('https://fred.stlouisfed.org/graph/fredgraph.csv', params={'id': 'VIXCLS'}, headers={'User-Agent': UA}, timeout=30)
            d = pd.read_csv(__import__('io').StringIO(r.text)); d.columns = ['date', 'close']; d['close'] = pd.to_numeric(d['close'], errors='coerce'); got = d.dropna().tail(days); got['source'] = 'FRED VIXCLS(CBOE)'
        except Exception as e: fail.append((fn + ' FRED', repr(e)))
    if got is not None and len(got):
        save(got.tail(days).reset_index(drop=True), f'{out}/{fn}.csv', fn)

# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--days', type=int, default=10); ap.add_argument('--out', default='.'); ap.add_argument('--allow-today', action='store_true', help='15:35 이후 오늘 줄 포함(투자자별은 18:30 전이면 잠정 표시)'); ap.add_argument('--tag', default='')
    a = ap.parse_args(); now = dt.datetime.now(KST); today = now.date()
    global ALLOW_TODAY; ALLOW_TODAY = a.allow_today
    start = today - dt.timedelta(days=int(a.days * 1.6) + 3); s8, e8 = start.strftime('%Y%m%d'), today.strftime('%Y%m%d')
    tag = today.strftime('%Y%m%d') + (('_' + a.tag) if a.tag else ''); out = os.path.join(a.out, f'dashboard_{tag}'); os.makedirs(out, exist_ok=True)
    log(f'기간 {start}~{today} (장중이면 오늘 줄 제외) → {out}')
    try: krx_items(s8, e8, today, now, out)
    except Exception as e: fail.append(('pykrx', repr(e) + ' — pip install pykrx 했는지, KRX 접속이 되는지 확인'))
    krx_etf_detail(s8, e8, today, now, out)
    night_futures(s8, e8, today, now, out)
    vkospi_ohlc(s8, e8, today, now, out)
    freesis_items(s8, e8, out)
    daum_today(today, now, out)
    vkospi_probe(s8, e8, today, now, out)
    vix_fetch(out)
    lines = [f'수집 {now:%Y-%m-%d %H:%M} KST · 기간 {start}~{today}' + (' · 오늘 줄 포함(투자자별 잠정)' if ALLOW_TODAY and now.time() < dt.time(18, 30) else ''), f'성공: {ok}', f'실패: {fail}',
             '오늘 날짜 줄은 18:30 이후 실행분만 확정치로 포함(그 전 실행은 어제까지).',
             '실패한 항목만 손으로: 09 야간선물 → KRX 정보데이터시스템 > 파생상품 > 종목시세 > 전종목 시세(상품 코스피200 선물, 시장구분 야간) 엑셀. 06 ETF 투자자별 → KRX > 증권상품 > ETF > 거래실적 > 투자자별(개별종목). 10 VKOSPI 시가·고가·저가는 키가 없으면 건너뜀(종가는 대시보드가 공개 자료로 받음).',
             '07·08 금투협 파일 열 이름(TMPV2…)은 화면 열 순서와 같다: 07 = 예탁금·파생예수금·RP·미수금·반대매매·비중, 08 = 신용융자 전체·유가·코스닥, 대주 전체·유가·코스닥, 청약자금대출, 담보융자.']
    open(os.path.join(out, 'README.txt'), 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
    zp = os.path.join(a.out, f'dashboard_{tag}.zip')
    with zipfile.ZipFile(zp, 'w', zipfile.ZIP_DEFLATED) as z:
        for f in sorted(os.listdir(out)): z.write(os.path.join(out, f), arcname=f'dashboard_{tag}/{f}')
    log('\n'.join(lines)); log(f'zip: {zp}  ← 이 파일을 대화에 첨부')
    return 0 if ok else 1

if __name__ == '__main__': sys.exit(main())
