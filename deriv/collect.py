"""선물·옵션 수급 지표 연구 — 1차(국내 핵심) 자료 수집 [A5 국내 자료 수집 에이전트]

모드
  probe : 각 화면(bld)을 짧은 기간으로 불러 응답 열 이름·행 수·첫 행을 deriv/out/probe/ 에 남긴다(인자 조합 확인용).
  full  : 1차 단계 자료 전부를 deriv/data/ 에 CSV 로 저장한다(원자료 열 그대로 + 날짜·출처).
          인자로 할 일만 고를 수 있다. 예) python deriv/collect.py full inv basis

자료 출처: KRX 정보데이터시스템(data.krx.co.kr, 무료·로그인 필요 — 저장소 비밀값 KRX_ID/KRX_PW)
화면 번호 → bld (화면 jsp 에서 확인, 2026-11-18)
  [15001] 전종목 시세                MDCSTAT12501
  [15003] 최근월물 시세 추이(선물)    MDCSTAT12701
  [15008] 투자자별 거래실적           MDCSTAT13101(기간합계) · 13102(일별추이) · 13103(일별추이 상세)
  베이시스 추이(선물)                 MDCSTAT13401(상품) · 13402(개별종목)
  내재변동성 추이(옵션)               MDCSTAT13501
  P/C Ratio 추이(옵션)                MDCSTAT13601
  [12012] 프로그램매매(주식)          MDCSTAT02601
원칙: 못 받은 값은 추정하지 않는다(빈칸 = 확인 불가). 모든 행에 출처·수집 시각을 남긴다.
"""
import datetime as dt
import json
import os
import sys
import time
import traceback

import pandas as pd

KST = dt.timezone(dt.timedelta(hours=9))
ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, 'data')
OUT = os.path.join(ROOT, 'out')
os.makedirs(DATA, exist_ok=True); os.makedirs(os.path.join(OUT, 'probe'), exist_ok=True)
LOG = []
STAMP = dt.datetime.now(KST).strftime('%Y-%m-%d %H:%M KST')
TODAY = dt.datetime.now(KST).date()
_now = dt.datetime.now(KST)
END = TODAY if _now.time() >= dt.time(18, 30) else TODAY - dt.timedelta(days=1)   # 18:30 전이면 오늘 줄(잠정)을 받지 않는다
FAILED = []


def log(m):
    s = f'[{dt.datetime.now(KST):%H:%M:%S}] {m}'
    print(s, flush=True); LOG.append(s)


# 대시보드 수집(같은 KRX 계정 로그인)과 겹치지 않게 기다린다.
# 대시보드 실행 기록(2026-11-15~18): 08:23·15:43·20:23 수동 실행이 2~11분, 나머지 예약 재시도는 1~3분.
BUSY = [((8, 15), (8, 45)), ((9, 18), (9, 35)), ((10, 18), (10, 35)), ((15, 35), (16, 5)), ((16, 38), (16, 55)),
        ((17, 38), (17, 55)), ((20, 15), (20, 45)), ((21, 18), (21, 35)), ((22, 18), (22, 35))]
def wait_clear():
    while True:
        now = dt.datetime.now(KST)
        if now.weekday() >= 5: return
        hm = (now.hour, now.minute); hit = [b for b in BUSY if b[0] <= hm < b[1]]
        if not hit: return
        end = now.replace(hour=hit[0][1][0], minute=hit[0][1][1], second=0)
        log(f'대시보드 수집 시간대 — {end:%H:%M} KST 까지 대기'); time.sleep(max(30, (end - now).total_seconds() + 5))


wait_clear()  # pykrx 를 import 하는 순간 KRX 에 로그인하므로 그 전에 대시보드 시간대를 피한다
from pykrx.website.krx.krxio import KrxWebIo  # noqa: E402,F401  (import 할 때 KRX_ID/PW 로 로그인)


from pykrx.website.comm.webio import get_session  # noqa: E402
URL = 'https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd'
HDR = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://data.krx.co.kr/contents/MDC/MDI/outerLoader/index.cmd', 'X-Requested-With': 'XMLHttpRequest'}


LOGOUTS = [0]
def relogin():
    """같은 계정의 다른 세션이 로그인하면 이 세션은 LOGOUT 을 받는다 → 한 번 다시 로그인. 5번 넘게 반복되면 멈춘다."""
    LOGOUTS[0] += 1
    if LOGOUTS[0] > 20: raise SystemExit('KRX 로그인이 계속 끊김(다른 곳에서 같은 계정 사용 중일 수 있음) — 중단')
    krxs = get_session()
    if krxs is not None:
        ok = krxs.refresh(os.environ.get('KRX_ID', ''), os.environ.get('KRX_PW', ''))
        log(f'  재로그인 {"성공" if ok else "실패"} ({LOGOUTS[0]}회째)')


def post_once(bld, p, timeout=40):
    """KRX 한 번 호출(시간 제한 있음 — pykrx 기본 호출은 시간 제한이 없어 멈춘 연결에서 영원히 기다렸다)."""
    krxs = get_session()
    data = dict(p, bld='dbms/MDC/STAT/standard/' + bld)
    if krxs is None:
        import requests
        r = requests.post(URL, headers=HDR, data=data, timeout=timeout)
    else:
        h = krxs.get_headers(); h.update(HDR)
        r = krxs.session.post(URL, headers=h, data=data, timeout=timeout)
    t = r.text.strip()
    if t.startswith('LOGOUT'):
        relogin(); raise ValueError('LOGOUT(재로그인함)')
    if not t.startswith('{'): raise ValueError(f'응답 이상: {t[:80]}')
    js = r.json()
    key = 'output' if 'output' in js else next((x for x in js if isinstance(js[x], list)), None)
    return (js.get(key) or []) if key else [], list(js.keys())


def call(bld, tries=3, chunk=729, **p):
    """화면 호출. 기간(strtDd~endDd)이 2년보다 길면 2년씩 나눠 부르고, 조각마다 따로 재시도한다(실패 조각은 기록하고 넘어감)."""
    if 'strtDd' in p and 'endDd' in p:
        s, e = pd.Timestamp(p['strtDd']), pd.Timestamp(p['endDd']); out = []; keys = []
        while s <= e:
            t = min(s + pd.Timedelta(days=chunk), e); q = dict(p, strtDd=s.strftime('%Y%m%d'), endDd=t.strftime('%Y%m%d'))
            for k in range(tries):
                try:
                    rows, keys = post_once(bld, q); out += rows; break
                except Exception as ex:
                    if k == tries - 1:
                        log(f'  조각 실패 {bld} {q["strtDd"]}~{q["endDd"]}: {ex!r}'[:200]); FAILED.append({'bld': bld, '시작': q['strtDd'], '끝': q['endDd'], '조건': json.dumps({k2: v for k2, v in q.items() if k2 not in ('strtDd', 'endDd')}, ensure_ascii=False), '오류': repr(ex)[:150]})
                    time.sleep(3 + 5 * k)
            s = t + pd.Timedelta(days=1); time.sleep(0.4); wait_clear()
        return out, keys
    last = None
    for k in range(tries):
        try: return post_once(bld, p)
        except Exception as ex: last = ex; time.sleep(3 + 5 * k)
    raise last


def frame(rows, **extra):
    df = pd.DataFrame(rows)
    for k, v in extra.items(): df[k] = v
    df['수집시각'] = STAMP; df['원본'] = 'KRX 정보데이터시스템'
    return df


KEYS = {'inv_daily': ['TRD_DD', '상품', '권리', '단위', '장구분', '상세']}


def save(df, name):
    if name in KEYS and all(k in df for k in KEYS[name]):
        df = df.assign(**{k: df[k].fillna('') for k in KEYS[name]}).drop_duplicates(KEYS[name], keep='last')
    p = os.path.join(DATA, name + ('.csv.gz' if len(df) > 20000 else '.csv'))
    other = os.path.join(DATA, name + ('.csv' if p.endswith('.gz') else '.csv.gz'))
    if os.path.exists(other): os.remove(other)   # 같은 자료가 두 이름으로 남지 않게
    df.to_csv(p, index=False, encoding='utf-8-sig' if not p.endswith('.gz') else 'utf-8')
    log(f'저장 {os.path.basename(p)} {len(df)}행'); return p


# 상품 코드: KRX 화면 값은 10자리(앞 5자리 접두 + 상품 5자리). 접두는 probe 로 확정한다.
PROD = {'FUK2I': '코스피200 선물', 'OPK2I': '코스피200 옵션', 'FUMKI': '미니 코스피200 선물', 'OPMKI': '미니 코스피200 옵션',
        'OPWKI': '코스피200 위클리 옵션(목)', 'OPWKM': '코스피200 위클리 옵션(월)'}
PREFIXES = ['KRDRV', 'KR___']


def d8(d): return pd.Timestamp(d).strftime('%Y%m%d')


# ------------------------------------------------------------------ probe
def probe():
    res = {}
    s, e = '20261101', d8(TODAY - dt.timedelta(days=1))
    def rec(name, bld, **p):
        try:
            rows, keys = call(bld, tries=1, **p)
            res[name] = {'bld': bld, 'params': p, 'n': len(rows), 'keys': keys, 'cols': list(rows[0].keys()) if rows else [], 'head': rows[:3], 'tail': rows[-2:]}
        except Exception as ex:
            res[name] = {'bld': bld, 'params': p, 'error': repr(ex)[:300]}
        log(f"probe {name}: {res[name].get('n', res[name].get('error'))}"); time.sleep(0.6)
    for pre in PREFIXES:
        rec(f'inv13102_{pre}_FUK2I_AMT', 'MDCSTAT13102', inqTpCd='2', prtType='AMT', prtCheck='SUN', isuCd=pre + 'FUK2I', isuCd2='', isuOpt='ALL', aggBasTpCd='0', strtDd=s, endDd=e, share='1', money='1')
    rec('inv13102_FUK2I_QTY_all', 'MDCSTAT13102', inqTpCd='2', prtType='QTY', prtCheck='SUN', isuCd='KRDRVFUK2I', isuCd2='', isuOpt='ALL', aggBasTpCd='', strtDd=s, endDd=e, share='1', money='1')
    rec('inv13103_FUK2I_AMT', 'MDCSTAT13103', inqTpCd='2', prtType='AMT', prtCheck='SUN', isuCd='KRDRVFUK2I', isuCd2='', isuOpt='ALL', aggBasTpCd='0', strtDd=s, endDd=e, share='1', money='1', detailView='1')
    rec('inv13102_OPK2I_C_AMT', 'MDCSTAT13102', inqTpCd='2', prtType='AMT', prtCheck='SUN', isuCd='KRDRVOPK2I', isuCd2='', isuOpt='C', aggBasTpCd='0', strtDd=s, endDd=e, share='1', money='1')
    rec('inv13102_OPWKM_P_AMT', 'MDCSTAT13102', inqTpCd='2', prtType='AMT', prtCheck='SUN', isuCd='KRDRVOPWKM', isuCd2='', isuOpt='P', aggBasTpCd='0', strtDd=s, endDd=e, share='1', money='1')
    rec('inv13101_FUK2I_period', 'MDCSTAT13101', inqTpCd='1', isuCd='KRDRVFUK2I', isuCd2='', isuOpt='ALL', aggBasTpCd='0', strtDd=s, endDd=e, share='1', money='1')
    rec('inv13102_FUK2I_2008', 'MDCSTAT13102', inqTpCd='2', prtType='AMT', prtCheck='SUN', isuCd='KRDRVFUK2I', isuCd2='', isuOpt='ALL', aggBasTpCd='0', strtDd='20081001', endDd='20081031', share='1', money='1')
    rec('inv13102_FUK2I_2001', 'MDCSTAT13102', inqTpCd='2', prtType='AMT', prtCheck='SUN', isuCd='KRDRVFUK2I', isuCd2='', isuOpt='ALL', aggBasTpCd='0', strtDd='20010901', endDd='20010930', share='1', money='1')
    rec('basis13401', 'MDCSTAT13401', secugrpId='1', prodId='KRDRVFUK2I', subProdId='', aggBasTpCd='0', strtDd=s, endDd=e, share='1', money='1')
    rec('basis13401_2008', 'MDCSTAT13401', secugrpId='1', prodId='KRDRVFUK2I', subProdId='', aggBasTpCd='0', strtDd='20081001', endDd='20081031', share='1', money='1')
    rec('iv13501', 'MDCSTAT13501', prodId='KRDRVOPK2I', strtDd=s, endDd=e, share='1', money='1')
    rec('iv13501_2008', 'MDCSTAT13501', prodId='KRDRVOPK2I', strtDd='20081001', endDd='20081031', share='1', money='1')
    rec('pcr13601', 'MDCSTAT13601', prodId='KRDRVOPK2I', aggBasTpCd='0', strtDd=s, endDd=e, share='1', money='1')
    rec('pcr13601_2008', 'MDCSTAT13601', prodId='KRDRVOPK2I', aggBasTpCd='0', strtDd='20081001', endDd='20081031', share='1', money='1')
    rec('front12701', 'MDCSTAT12701', prodId='KRDRVFUK2I', strtDd=s, endDd=e, share='1', money='1')
    rec('front12701_2008', 'MDCSTAT12701', prodId='KRDRVFUK2I', strtDd='20081001', endDd='20081031', share='1', money='1')
    rec('prog02601_range', 'MDCSTAT02601', mktId='STK', strtDd=s, endDd=e, share='1', money='1')
    rec('prog02601_day', 'MDCSTAT02601', mktId='STK', strtDd=e, endDd=e, share='1', money='1')
    rec('prog02601_2008day', 'MDCSTAT02601', mktId='STK', strtDd='20081024', endDd='20081024', share='1', money='1')
    rec('chain12501_OPK2I', 'MDCSTAT12501', trdDd=e, prodId='KRDRVOPK2I', mktTpCd='T', rghtTpCd='T', aggBasTpCd='0', share='1', money='1')
    rec('chain12502_OPK2I', 'MDCSTAT12502', trdDd=e, prodId='KRDRVOPK2I', mktTpCd='T', rghtTpCd='T', aggBasTpCd='0', share='1', money='1')
    rec('chain12501_OPK2I_2010', 'MDCSTAT12501', trdDd='20100105', prodId='KRDRVOPK2I', mktTpCd='T', rghtTpCd='T', aggBasTpCd='0', share='1', money='1')
    rec('chain12501_FUK2I', 'MDCSTAT12501', trdDd=e, prodId='KRDRVFUK2I', mktTpCd='T', rghtTpCd='T', aggBasTpCd='0', share='1', money='1')
    with open(os.path.join(OUT, 'probe', 'probe.json'), 'w', encoding='utf-8') as f:
        json.dump(res, f, ensure_ascii=False, indent=1, default=str)


# ------------------------------------------------------------------ full
START_LONG = '20080101'   # 일별 추이 화면(기간 조회) — KRX 가 주는 데까지(앞쪽은 빈 응답이면 그대로 둔다)
START_DAYLOOP = '20100101'  # 프로그램매매(날짜마다 1번) — 2010년부터
START_CHAIN = '20150101'    # 옵션 전종목(날짜마다 1번, 응답이 큼) — VKOSPI 자료와 맞춰 2015년부터


def inv(pre='KR___'):   # probe(2026-11-18): 투자자별 화면은 'KR___' 접두만 응답. 긴 기간은 매우 느려 120일 조각으로.
    """투자자별 거래실적 일별추이(정규장, 순매수 금액) — 상품 × 권리. 상품마다 상장 무렵부터."""
    start = {'FUK2I': START_LONG, 'OPK2I': START_LONG, 'FUMKI': '20150701', 'OPMKI': '20150701', 'OPWKI': '20190901', 'OPWKM': '20230701'}
    jobs = [('FUK2I', 'ALL', False), ('OPK2I', 'C', False), ('OPK2I', 'P', False), ('OPWKI', 'C', False), ('OPWKI', 'P', False),
            ('OPWKM', 'C', False), ('OPWKM', 'P', False), ('FUMKI', 'ALL', False), ('OPMKI', 'C', False), ('OPMKI', 'P', False),
            ('FUK2I', 'ALL', True), ('OPK2I', 'C', True), ('OPK2I', 'P', True)]
    p0 = next((os.path.join(DATA, 'inv_daily' + x) for x in ('.csv.gz', '.csv') if os.path.exists(os.path.join(DATA, 'inv_daily' + x))), None)
    out = [pd.read_csv(p0)] if p0 else []
    done = set(); last = {}
    if out:
        o = out[0]; o['상세'] = o.get('상세', pd.Series('', index=o.index)).fillna('')
        o['_d'] = pd.to_datetime(o['TRD_DD'].astype(str).str[:10], errors='coerce')
        for key, g in o.groupby(['상품', '권리', '상세', '장구분']):
            prod = key[0]; n_exp = len(pd.bdate_range(start[prod], TODAY)) * 0.93   # 휴장일 감안
            if len(g) >= n_exp: done.add((key[0], key[1], key[2] == 'Y', key[3])); last[(key[0], key[1], key[2] == 'Y')] = g['_d'].max()
            else: log(f'inv {key} 불완전({len(g)}행 < {int(n_exp)}) — 다시 받음')
        keep = o.apply(lambda r: (r['상품'], r['권리'], r['상세'] == 'Y', r['장구분']) in done, axis=1)   # 야간 행은 아래에서 새로 받음(중복 방지)
        out = [o[keep].drop(columns=['_d'])]
    for prod, opt, det in jobs:
        st = start[prod]
        if (prod, opt, det, '정규') in done:
            lt = last.get((prod, opt, det))
            if lt is None or lt.date() >= END: continue
            st = (lt + pd.Timedelta(days=1)).strftime('%Y%m%d')        # 이어받기: 마지막 날짜 다음부터
        wait_clear()
        try:
            extra = dict(detailView='1') if det else {}
            rows, _ = call('MDCSTAT13103' if det else 'MDCSTAT13102', chunk=120, inqTpCd='2', prtType='AMT', prtCheck='SUN', isuCd=pre + prod,
                           isuCd2='', isuOpt=opt, aggBasTpCd='0', strtDd=st, endDd=d8(END), share='1', money='1', **extra)
            df = frame(rows, 상품=prod, 상품명=PROD[prod], 권리=opt, 단위='AMT', 장구분='정규', 상세='Y' if det else '')
            out.append(df); log(f'inv {prod} {opt} {"상세" if det else ""}: {len(df)}행')
            save(pd.concat(out, ignore_index=True), 'inv_daily'); git_save(f'inv {prod} {opt}{" 상세" if det else ""}')
        except Exception as e: log(f'inv {prod} {opt} 실패: {e!r}'[:300])
    wait_clear()
    try:
        rows, _ = call('MDCSTAT13102', chunk=120, inqTpCd='2', prtType='AMT', prtCheck='SUN', isuCd=pre + 'FUK2I', isuCd2='', isuOpt='ALL',
                       aggBasTpCd='2', strtDd='20250601', endDd=d8(END), share='1', money='1')
        out.append(frame(rows, 상품='FUK2I', 상품명=PROD['FUK2I'], 권리='ALL', 단위='AMT', 장구분='야간', 상세=''))
        save(pd.concat(out, ignore_index=True), 'inv_daily')
    except Exception as e: log(f'inv 야간 실패: {e!r}'[:300])


def ranged(name, bld, **p):
    wait_clear()
    try:
        rows, _ = call(bld, strtDd=START_LONG, endDd=d8(END), share='1', money='1', **p)
        save(frame(rows), name)
    except Exception as e: log(f'{name} 실패: {e!r}'[:300])


def basis(): ranged('basis_daily', 'MDCSTAT13401', secugrpId='1', prodId='KRDRVFUK2I', subProdId='', aggBasTpCd='0')
def iv(): ranged('iv_daily', 'MDCSTAT13501', prodId='KRDRVOPK2I')
def pcr(): ranged('pcr_daily', 'MDCSTAT13601', prodId='KRDRVOPK2I', aggBasTpCd='0')
def front(): ranged('fut_front_daily', 'MDCSTAT12701', prodId='KRDRVFUK2I')


def trading_days(start):
    try:
        mk = pd.read_csv(os.path.join(ROOT, '..', 'pkg', 'datasets', 'market_daily.csv'), usecols=['date'])
        known = set(mk['date'])
    except Exception: known = set()
    days = [d for d in pd.bdate_range(start, TODAY - dt.timedelta(days=1))]
    return days, known


def dayloop(name, bld, start, maker, every_save=250, post=None):
    """날짜마다 한 번 부르는 화면. 이어받기: 이미 받은 날짜는 건너뛴다."""
    p = os.path.join(DATA, name + '.csv.gz')
    have = pd.read_csv(p) if os.path.exists(p) else pd.DataFrame()
    done = set(have['날짜']) if len(have) else set()
    days, known = trading_days(start); buf = []; n = 0
    for d in days:
        ds = d.strftime('%Y-%m-%d')
        if ds in done: continue
        if known and ds < '2015-01-02' and False: pass
        wait_clear()
        try:
            rows, _ = call(bld, **maker(d8(d)))
        except Exception as e:
            log(f'{name} {ds} 실패: {e!r}'[:200]); rows = []
        if rows:
            df = pd.DataFrame(rows); df.insert(0, '날짜', ds)
            if post is not None:
                try: df = post(df)
                except Exception as e: log(f'{name} {ds} 정리 실패: {e!r}'[:200])
            buf.append(df)
        n += 1; time.sleep(0.25)
        if n % every_save == 0 and buf:
            have = pd.concat([have] + buf, ignore_index=True); buf = []; have.to_csv(p, index=False); log(f'{name} 중간 저장 {ds} ({len(have)}행)')
            git_save(f'{name} 중간 {ds}')
    if buf: have = pd.concat([have] + buf, ignore_index=True)
    if len(have):
        have['수집시각'] = have.get('수집시각', STAMP); have.to_csv(p, index=False); log(f'저장 {name}.csv.gz {len(have)}행')


def program(): dayloop('program_daily', 'MDCSTAT02601', START_DAYLOOP, lambda s8: dict(mktId='STK', strtDd=s8, endDd=s8, share='1', money='1'))


def compact_chain(df):
    """옵션 전종목 응답을 줄여 저장: 가까운 두 결제월, 기초자산 ±20% 행사가, 필요한 열만."""
    nm = df['ISU_NM'].astype(str)
    m = nm.str.extract(r'\s([CP])\s+(\d{6})\s+([\d.]+)')
    df = df.assign(cp=m[0], ym=m[1], K=pd.to_numeric(m[2], errors='coerce'))
    df = df[df['cp'].notna()]
    n = lambda c: pd.to_numeric(df[c].astype(str).str.replace(',', '').replace({'-': None}), errors='coerce')
    df = df.assign(settle=n('SETL_PRC'), close=n('TDD_CLSPRC'), vol=n('ACC_TRDVOL'), oi=n('ACC_OPNINT_QTY'), spot=n('SPOT_PRC'))
    yms = sorted(df['ym'].dropna().unique())[:2]
    S = df['spot'].median()
    df = df[df['ym'].isin(yms) & (df['K'] >= S * 0.8) & (df['K'] <= S * 1.2)]
    return df[['날짜', 'cp', 'ym', 'K', 'settle', 'close', 'vol', 'oi', 'spot']]


def chain(): dayloop('opt_chain_daily', 'MDCSTAT12501', START_CHAIN, lambda s8: dict(trdDd=s8, prodId='KRDRVOPK2I', mktTpCd='T', rghtTpCd='T', aggBasTpCd='0', share='1', money='1'), post=compact_chain)


def index_long():
    """코스피·코스피200 지수 일별(가능한 처음부터) — pykrx."""
    from pykrx import stock
    for code, nm in (('1001', 'kospi_long'), ('1028', 'k200_long')):
        wait_clear()
        try:
            df = stock.get_index_ohlcv('19960101', d8(END), code).reset_index(); df['수집시각'] = STAMP; df['원본'] = 'KRX 정보데이터시스템(pykrx)'
            save(df, nm)
        except Exception as e: log(f'{nm} 실패: {e!r}'[:300])


def git_save(msg):
    """Actions 안에서만: 할 일 하나가 끝날 때마다 커밋·push(작업 시간 초과로 결과를 잃지 않게)."""
    if not os.environ.get('GITHUB_ACTIONS'): return
    import subprocess
    with open(os.path.join(OUT, 'log_full_running.txt'), 'w', encoding='utf-8') as f: f.write('\n'.join(LOG))
    cmds = ['git config user.name dashboard-bot', 'git config user.email dashboard-bot@users.noreply.github.com',
            'git add -A deriv/data deriv/out', f'git commit -q -m "deriv-research 수집 {msg}"',
            'git pull -q --rebase origin deriv-research', 'git push -q origin HEAD:deriv-research']
    for c in cmds:
        r = subprocess.run(c, shell=True, capture_output=True, text=True, cwd=os.path.dirname(ROOT))
        if r.returncode and 'commit' not in c: log(f'git 실패: {c} {r.stderr[:200]}')


TASKS = {'index': index_long, 'inv': inv, 'basis': basis, 'iv': iv, 'pcr': pcr, 'front': front, 'program': program, 'chain': chain}


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else 'probe'
    log(f'시작 {mode} {sys.argv[2:]} — 로그인 계정 설정 {"있음" if os.environ.get("KRX_ID") else "없음"}')
    wait_clear()
    try:
        if mode == 'probe': probe()
        else:
            for t in (sys.argv[2:] or list(TASKS)):
                log(f'== {t}')
                try: TASKS[t]()
                except Exception: log(traceback.format_exc()[-800:])
                git_save(t)
    finally:
        if FAILED: pd.DataFrame(FAILED).to_csv(os.path.join(OUT, f'failed_chunks_{dt.datetime.now(KST):%Y%m%d_%H%M}.csv'), index=False, encoding='utf-8-sig')
        with open(os.path.join(OUT, f'log_{mode}_{dt.datetime.now(KST):%Y%m%d_%H%M}.txt'), 'w', encoding='utf-8') as f: f.write('\n'.join(LOG))


if __name__ == '__main__':
    main()
