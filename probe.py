# -*- coding: utf-8 -*-
"""자료 출처 시험 4차 — KRX 파생상품 화면의 시장구분(aggBasTpCd: ''=전체, 0=정규, 2=야간)로 야간선물 받기. 비밀값은 출력하지 않는다."""
import json, os, time, traceback
SECRETS = [v for k, v in os.environ.items() if k in ('KRX_API_KEY', 'KRX_ID', 'KRX_PW') and v]
os.makedirs('out', exist_ok=True)
def red(s):
    s = str(s)
    for v in SECRETS:
        if v and len(v) >= 4: s = s.replace(v, '***')
    return s
def w(name, text): open(os.path.join('out', name), 'w', encoding='utf-8').write(red(text))
def rd(bld, **p):
    from pykrx.website.krx.krxio import KrxWebIo
    class Any(KrxWebIo):
        @property
        def bld(self): return bld
    return Any().read(**p)
out = []
def tryit(label, bld, **p):
    try:
        js = rd(bld, **p); rs = js.get('output', []) if isinstance(js, dict) else []
        out.append(f'\n== {label} {p} → {len(rs)}행 keys={list(rs[0].keys()) if rs else list(js.keys())}')
        for r in rs[:40]: out.append('   ' + json.dumps(r, ensure_ascii=False))
    except Exception as e: out.append(f'\n== {label} {p} → 오류 {e!r}')
    time.sleep(1.2)
try:
    B = 'dbms/MDC/STAT/standard/'
    tryit('12701 야간', B + 'MDCSTAT12701', prodId='KRDRVFUK2I', strtDd='20261020', endDd='20261116', aggBasTpCd='2')
    tryit('12701 전체', B + 'MDCSTAT12701', prodId='KRDRVFUK2I', strtDd='20261109', endDd='20261116', aggBasTpCd='')
    tryit('12701 정규', B + 'MDCSTAT12701', prodId='KRDRVFUK2I', strtDd='20261111', endDd='20261116', aggBasTpCd='0')
    tryit('12701 야간+subProd', B + 'MDCSTAT12701', prodId='KRDRVFUK2I', subProdId='KRDRVFUK2I', strtDd='20261109', endDd='20261116', aggBasTpCd='2')
    tryit('12501 야간 1113', B + 'MDCSTAT12501', trdDd='20261113', prodId='KRDRVFUK2I', aggBasTpCd='2', rghtTpCd='T', mktTpCd='T')
    tryit('12501 야간 1116', B + 'MDCSTAT12501', trdDd='20261116', prodId='KRDRVFUK2I', aggBasTpCd='2', rghtTpCd='T', mktTpCd='T')
    tryit('12501 야간 1114', B + 'MDCSTAT12501', trdDd='20261114', prodId='KRDRVFUK2I', aggBasTpCd='2', rghtTpCd='T', mktTpCd='T')
    tryit('12501 전체 1113', B + 'MDCSTAT12501', trdDd='20261113', prodId='KRDRVFUK2I', aggBasTpCd='', rghtTpCd='T', mktTpCd='T')
    tryit('12601 야간', B + 'MDCSTAT12601', isuCd='KR4A016C0004', isuCd2='KR4A016C0004', strtDd='20261109', endDd='20261116', aggBasTpCd='2', rghtTpCd='T')
    tryit('01201 VKOSPI', B + 'MDCSTAT01201', indTpCd='1', idxIndCd='300', idxCd='1', idxCd2='300', strtDd='20261109', endDd='20261116')
except Exception: out.append(traceback.format_exc())
w('t_night.txt', '\n'.join(out))
