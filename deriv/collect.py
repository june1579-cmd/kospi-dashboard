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


def log(m):
    s = f'[{dt.datetime.now(KST):%H:%M:%S}] {m}'
    print(s, flush=True); LOG.append(s)


# 대시보드 수집(같은 KRX 계정 로그인)과 겹치지 않게 기다린다.
BUSY = [((8, 15), (10, 50)), ((15, 35), (18, 5)), ((20, 15), (22, 50))]
def wait_clear():
    while True:
        now = dt.datetime.now(KST)
        if now.weekday() >= 5: return
        hm = (now.hour, now.minute); hit = [b for b in BUSY if b[0] <= hm < b[1]]
        if not hit: return
        end = now.replace(hour=hit[0][1][0], minute=hit[0][1][1], second=0)
        log(f'대시보드 수집 시간대 — {end:%H:%M} KST 까지 대기'); time.sleep(max(30, (end - now).total_seconds() + 5))


wait_clear()  # pykrx 를 import 하는 순간 KRX 에 로그인하므로 그 전에 대시보드 시간대를 피한다
from pykrx.website.krx.krxio import KrxWebIo  # noqa: E402  (import 할 때 KRX_ID/PW 로 로그인)


class Bld(KrxWebIo):
    def __init__(self, bld):
        super().__init__(); self._b = bld
    @property
    def bld(self): return 'dbms/MDC/STAT/standard/' + self._b
    def fetch(self, **p): return self.read(**p)


def call(bld, tries=3, **p):
    """화면 하나 호출 → (행 목록, 응답 키). 실패하면 예외."""
    last = None
    for k in range(tries):
        try:
            js = Bld(bld).read(**p)
            if not isinstance(js, dict): raise ValueError(f'응답이 dict 아님: {str(js)[:120]}')
            key = 'output' if 'output' in js else next((x for x in js if isinstance(js[x], list)), None)
            return (js.get(key) or []) if key else [], list(js.keys())
        except Exception as e:
            last = e; time.sleep(2 + 3 * k)
    raise last


def frame(rows, **extra):
    df = pd.DataFrame(rows)
    for k, v in extra.items(): df[k] = v
    df['수집시각'] = STAMP; df['원본'] = 'KRX 정보데이터시스템'
    return df


def save(df, name):
    p = os.path.join(DATA, name + ('.csv.gz' if len(df) > 20000 else '.csv'))
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
START_LONG = '20040101'   # 일별 추이 화면(기간 조회) — KRX 가 주는 데까지(앞쪽은 빈 응답이면 그대로 둔다)
START_DAYLOOP = '20100101'  # 프로그램매매(날짜마다 1번) — 2010년부터
START_CHAIN = '20150101'    # 옵션 전종목(날짜마다 1번, 응답이 큼) — VKOSPI 자료와 맞춰 2015년부터


def inv(pre='KR___'):   # probe(2026-11-18): 투자자별 화면은 'KR___' 접두만 응답
    """투자자별 거래실적 일별추이(정규장) — 상품 × 권리 × 거래대금/거래량."""
    jobs = [('FUK2I', 'ALL'), ('FUMKI', 'ALL'), ('OPK2I', 'C'), ('OPK2I', 'P'), ('OPMKI', 'C'), ('OPMKI', 'P'),
            ('OPWKI', 'C'), ('OPWKI', 'P'), ('OPWKM', 'C'), ('OPWKM', 'P')]
    out = []
    for prod, opt in jobs:
        for pt in ('AMT', 'QTY'):
            wait_clear()
            try:
                rows, _ = call('MDCSTAT13102', inqTpCd='2', prtType=pt, prtCheck='SUN', isuCd=pre + prod, isuCd2='', isuOpt=opt,
                               aggBasTpCd='0', strtDd=START_LONG, endDd=d8(TODAY), share='1', money='1')
                df = frame(rows, 상품=prod, 상품명=PROD[prod], 권리=opt, 단위=pt, 장구분='정규')
                out.append(df); log(f'inv {prod} {opt} {pt}: {len(df)}행')
            except Exception as e: log(f'inv {prod} {opt} {pt} 실패: {e!r}'[:300])
            time.sleep(1)
    # 상세 투자자(금융투자·보험·투신·은행·기타금융·연기금·기타법인·개인·외국인·기타외국인) — 코스피200 선물·옵션
    for prod, opt in (('FUK2I', 'ALL'), ('OPK2I', 'C'), ('OPK2I', 'P')):
        wait_clear()
        try:
            rows, _ = call('MDCSTAT13103', inqTpCd='2', prtType='AMT', prtCheck='SUN', isuCd=pre + prod, isuCd2='', isuOpt=opt,
                           aggBasTpCd='0', strtDd=START_LONG, endDd=d8(TODAY), share='1', money='1', detailView='1')
            df = frame(rows, 상품=prod, 상품명=PROD[prod], 권리=opt, 단위='AMT', 장구분='정규', 상세='Y')
            out.append(df); log(f'inv 상세 {prod} {opt}: {len(df)}행')
        except Exception as e: log(f'inv 상세 {prod} {opt} 실패: {e!r}'[:300])
        time.sleep(1)
    # 야간(KRX 자체 야간) — 코스피200 선물
    wait_clear()
    try:
        rows, _ = call('MDCSTAT13102', inqTpCd='2', prtType='AMT', prtCheck='SUN', isuCd=pre + 'FUK2I', isuCd2='', isuOpt='ALL',
                       aggBasTpCd='2', strtDd='20250101', endDd=d8(TODAY), share='1', money='1')
        out.append(frame(rows, 상품='FUK2I', 상품명=PROD['FUK2I'], 권리='ALL', 단위='AMT', 장구분='야간'))
    except Exception as e: log(f'inv 야간 실패: {e!r}'[:300])
    if out: save(pd.concat(out, ignore_index=True), 'inv_daily')


def ranged(name, bld, **p):
    wait_clear()
    try:
        rows, _ = call(bld, strtDd=START_LONG, endDd=d8(TODAY), share='1', money='1', **p)
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
            df = stock.get_index_ohlcv('19960101', d8(TODAY), code).reset_index(); df['수집시각'] = STAMP; df['원본'] = 'KRX 정보데이터시스템(pykrx)'
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
        with open(os.path.join(OUT, f'log_{mode}_{dt.datetime.now(KST):%Y%m%d_%H%M}.txt'), 'w', encoding='utf-8') as f: f.write('\n'.join(LOG))


if __name__ == '__main__':
    main()
