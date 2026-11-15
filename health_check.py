# -*- coding: utf-8 -*-
"""health_check.py — 매 실행 끝에 자료 상태를 점검한다(2026-11-15 추가).

왜 만들었나: 11/15 점검에서 ① 미국 VIX 가 2주 동안 '장이 끝나기 전 값'으로 굳어 있었고(11/13 「최적화 2위」 매수 신호가 잘못 켜짐)
  ② 야간선물이 18일째 끊겨 있었고 ③ 투자자별 저녁 확정치가 잠정치로 덮였고 ④ 오후 실행의 코스피 종가가 사흘 연속 틀렸는데도
  알림은 매번 「자료: 정상」이었다. 수집 항목별 실패가 README 에만 적히고 오류 목록으로 올라오지 않았고, 값이 맞는지 대조하는 단계가 없었기 때문이다.

무엇을 보나
  1 수집 항목별 성공·실패·주의(dashboard_collect.py 가 쓴 status.json)
  2 자료마다 마지막 날짜가 '지금쯤 와 있어야 할 날짜'까지 왔는지(멈춤 감지) — 거래일·공표 시각·미국 장 마감을 따져 기대일을 정한다
  3 출처 간 대조 결과(daily_update.py 의 warnings: 코스피 종가 ↔ 네이버·다음, 투자자별 KRX ↔ 다음, VKOSPI 화면 ↔ Open API, 야간선물 KRX ↔ 공개 출처, VIX 과거 값 정정)
  4 값 범위·같은 값 되풀이(자료가 멈춘 채 날짜만 늘어나는 경우)
  5 확정된 지 한참 지난 날짜의 값이 바뀐 것(값_교체_기록)

출력
  out/health.csv      대시보드 「자료 상태」 칸(자료·마지막 날짜·기대일·상태·설명)
  report/health.json  알림 「자료:」 줄(line), 오류·주의 목록, 직전 알림과 달라진 것(new·resolved)
상태: 정상 / 참고(늦지만 정해진 시각 전) / 주의(받았지만 확인 필요·하루 늦음) / 정정(과거 값이 고쳐짐) / 오류(멈춤·불일치)

사용: python health_check.py --workbook data/통합_원자료.xlsx --out out --report report --collect data/collect/dashboard_YYYYMMDD_tag --summary data/update_summary.json --tag 1840 [--public data/public] [--now '2026-11-16 08:30']
"""
import argparse, datetime as dt, json, os
import numpy as np, pandas as pd

KST = dt.timezone(dt.timedelta(hours=9))
HERE = os.path.dirname(os.path.abspath(__file__))
US_HOLIDAYS = {  # 뉴욕 증시 휴장일(VIX 종가 없음). 목록 밖의 해는 하루 늦음을 '참고'로만 본다
    '2026-01-01', '2026-01-19', '2026-02-16', '2026-04-03', '2026-05-25', '2026-06-19', '2026-07-03', '2026-09-07', '2026-11-26', '2026-12-25',
    '2027-01-01', '2027-01-18', '2027-02-15', '2027-03-26', '2027-05-31', '2027-06-18', '2027-07-05', '2027-09-06', '2027-11-25', '2027-12-24'}
ORDER = {'오류': 0, '정정': 1, '주의': 2, '참고': 3, '정상': 4}


def load_holidays(public):
    for p in (os.path.join(public or '', 'data', 'holidays_kr.json'), os.path.join(HERE, 'pkg', 'holidays_kr.json')):
        try:
            if os.path.exists(p): return set(json.load(open(p, encoding='utf-8')).get('holidays', []))
        except Exception: pass
    return set()


class Cal:
    def __init__(self, holi): self.h = holi
    def is_trading(self, d): return d.weekday() < 5 and d.isoformat() not in self.h
    def prev(self, d):
        d = d - dt.timedelta(days=1)
        while not self.is_trading(d): d -= dt.timedelta(days=1)
        return d
    def next(self, d):
        d = d + dt.timedelta(days=1)
        while not self.is_trading(d): d += dt.timedelta(days=1)
        return d
    def on_or_before(self, d):
        while not self.is_trading(d): d -= dt.timedelta(days=1)
        return d
    def lag(self, last, exp):
        """last 가 exp 보다 몇 거래일 늦은지(0 이하면 늦지 않음)."""
        if last is None: return 99
        n = 0; d = exp
        while d > last and n < 60:
            d = self.prev(d); n += 1
        return n


def us_lag(last, exp):
    """미국 영업일 기준(주말·알려진 휴장일 제외) last 가 exp 보다 며칠 늦은지."""
    if last is None: return 99
    n = 0; d = exp
    while d > last and n < 60:
        if d.weekday() < 5 and d.isoformat() not in US_HOLIDAYS: n += 1
        d -= dt.timedelta(days=1)
    return n


def us_final_date(now):
    from zoneinfo import ZoneInfo
    n = now.astimezone(ZoneInfo('America/New_York'))
    d = n.date() if n.time() >= dt.time(16, 30) else n.date() - dt.timedelta(days=1)
    while d.weekday() >= 5 or d.isoformat() in US_HOLIDAYS: d -= dt.timedelta(days=1)
    return d


def last_date(df, col='일자', valcol=None):
    if df is None or not len(df) or col not in df.columns: return None
    x = df if valcol is None else df[df[valcol].notna()]
    if not len(x): return None
    return pd.to_datetime(x[col]).max().date()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--workbook', required=True); ap.add_argument('--out', default='out'); ap.add_argument('--report', default='report'); ap.add_argument('--collect', default='')
    ap.add_argument('--summary', default='data/update_summary.json'); ap.add_argument('--tag', default=''); ap.add_argument('--public', default='data/public'); ap.add_argument('--now', default='')
    ap.add_argument('--docs', default='docs', help='웹판 폴더(page.html 의 수기 결론 카드 기준일 확인)'); ap.add_argument('--state', default='state/health_state.json'); ap.add_argument('--pipeline-errors', default='', help='run_pipeline.py 가 모은 단계 오류(JSON 목록 파일)')
    a = ap.parse_args()
    now = pd.Timestamp(a.now).to_pydatetime().replace(tzinfo=KST) if a.now else dt.datetime.now(KST)
    today = now.date(); cal = Cal(load_holidays(a.public))
    X = pd.read_excel(a.workbook, sheet_name=None)
    summ = json.load(open(a.summary, encoding='utf-8')) if os.path.exists(a.summary) else {}
    st_p = os.path.join(a.collect, 'status.json') if a.collect else ''
    status = json.load(open(st_p, encoding='utf-8')) if st_p and os.path.exists(st_p) else None
    rows = []      # {key, name, last, expected, status, note}
    def add(key, name, last, exp, status_, note=''):
        rows.append({'key': key, 'name': name, 'last': '' if last is None else str(last), 'expected': '' if exp is None else str(exp), 'status': status_, 'note': note})
    md = lambda d: '' if d is None else f'{d.month}/{d.day}'

    # ------------------------------------------------------------------ 기대일
    closed_today = cal.is_trading(today) and now.time() >= dt.time(15, 40)
    kexp = today if closed_today else cal.on_or_before(today - dt.timedelta(days=1))    # 종가가 나와 있어야 할 마지막 거래일
    same_day = (kexp == today)

    # ------------------------------------------------------------------ 1 코스피 일별
    K = X.get('코스피_일별'); kl = last_date(K, valcol='종가(pt)')
    lg = cal.lag(kl, kexp)
    if lg <= 0: add('kospi', '코스피 종가', kl, kexp, '정상', 'KRX 정보데이터시스템 · 네이버·다음 실시간 값과 대조')
    else: add('kospi', '코스피 종가', kl, kexp, '오류', f'{md(kexp)}분이 와 있어야 하는데 {md(kl)}까지만 있음({lg}거래일 늦음)')
    if K is not None and kl is not None:
        r = K[pd.to_datetime(K['일자']).dt.date == kl].iloc[-1]
        if pd.isna(r.get('시가(pt)')) and (not same_day or now.time() >= dt.time(18, 30)):
            add('kospi_ohlc', '코스피 시가·고가·저가', kl, kexp, '주의', f'{md(kl)} 종가만 있고 시가·고가·저가·거래량이 비어 있음(KRX 일별 시세 미수집)')
        try:
            ch = abs(float(r['등락률(%)']))
            if ch > 15: add('kospi_range', '코스피 등락률 범위', kl, kexp, '오류', f'{md(kl)} 등락률 {ch:.1f}% — 값 확인 필요')
        except Exception: pass
        tail = K.sort_values('일자').tail(3)['종가(pt)'].tolist()
        if len(tail) == 3 and tail[-1] == tail[-2]: add('kospi_repeat', '코스피 종가 되풀이', kl, kexp, '주의', f'최근 두 거래일 종가가 똑같음({tail[-1]}) — 자료가 멈춘 채 날짜만 늘었는지 확인')

    # ------------------------------------------------------------------ 2 투자자별
    F = X.get('투자자별_코스피_일별'); fl = last_date(F, valcol='외국인 합계(십억원)')
    lg = cal.lag(fl, kexp)
    if lg > 0: add('investor', '투자자별 순매수', fl, kexp, '오류', f'{md(kexp)}분이 없음({md(fl)}까지, {lg}거래일 늦음)')
    else:
        r = F[pd.to_datetime(F['일자']).dt.date == fl].iloc[-1]; lbl = str(r.get('출처 구분', ''))
        prov = '잠정' in lbl
        if prov and (fl < today or now.time() >= dt.time(20, 15)): add('investor', '투자자별 순매수', fl, kexp, '주의', f'{md(fl)}분이 아직 잠정치(확정치 미도착) — KRX 투자자별 거래실적 수집 확인')
        elif prov: add('investor', '투자자별 순매수', fl, kexp, '참고', f'{md(fl)}분 잠정치(정규장 집계) — 저녁 20:23 실행에서 확정')
        else: add('investor', '투자자별 순매수', fl, kexp, '정상', 'KRX 확정치')
        try:
            if max(abs(float(r['외국인 합계(십억원)'])), abs(float(r['개인(십억원)'])), abs(float(r['기관 합계(십억원)']))) > 15000: add('investor_range', '투자자별 값 범위', fl, kexp, '오류', f'{md(fl)} 순매수가 15조 원을 넘음 — 단위·값 확인 필요')
        except Exception: pass

    # ------------------------------------------------------------------ 3 VKOSPI
    V = X.get('VKOSPI_일별'); vl = last_date(V, valcol='종가')
    vexp = kexp if (not same_day or now.time() >= dt.time(16, 20)) else cal.prev(kexp)      # 당일 값은 16:10 이후 KRX 화면에서
    lg = cal.lag(vl, vexp)
    if lg <= 0: add('vkospi', 'VKOSPI', vl, vexp, '정상', 'KRX(당일은 정보데이터시스템 화면, 다음 날 아침 Open API 로 재확인)' + ('' if vexp == kexp else ' · 오늘 값은 16:10 이후'))
    elif lg == 1: add('vkospi', 'VKOSPI', vl, vexp, '주의', f'{md(vexp)}분 미도착({md(vl)}까지) — VKOSPI 를 쓰는 신호(최적화 1~3위·매도 민감·중간·엄격형)는 판정 보류')
    else: add('vkospi', 'VKOSPI', vl, vexp, '오류', f'{md(vexp)}분이 와 있어야 하는데 {md(vl)}까지만 있음({lg}거래일 늦음)')
    if V is not None and vl is not None:
        vt = V.sort_values('일자').tail(3)['종가'].tolist()
        if not (5 < float(vt[-1]) < 150): add('vkospi_range', 'VKOSPI 값 범위', vl, vexp, '오류', f'{md(vl)} 값 {vt[-1]} — VKOSPI 범위(5~150) 밖, 다른 지수가 섞였을 수 있음')
        if len(vt) == 3 and vt[-1] == vt[-2] == vt[-3]: add('vkospi_repeat', 'VKOSPI 값 되풀이', vl, vexp, '주의', f'최근 세 거래일 값이 똑같음({vt[-1]})')

    # ------------------------------------------------------------------ 4 금투협(예탁금·반대매매 / 신용잔고): 기준일 다음 거래일 15시쯤 공표
    pub_day = today if (cal.is_trading(today) and now.time() >= dt.time(15, 20)) else cal.on_or_before(today - dt.timedelta(days=1))   # 가장 최근 공표가 있었던 날
    fexp = cal.prev(pub_day)
    for key, nm, sheet in (('kofia_funds', '금투협 예탁금·미수금·반대매매', '증시자금추이_금투협'), ('kofia_credit', '금투협 신용융자 잔고', '신용공여잔고_금투협')):
        S = X.get(sheet); sl = last_date(S)
        lg = cal.lag(sl, fexp)
        if lg <= 0: add(key, nm, sl, fexp, '정상', '금융투자협회 FreeSIS(기준일 다음 거래일 15시쯤 공표)')
        elif lg == 1: add(key, nm, sl, fexp, '주의', f'{md(fexp)}분 미도착({md(sl)}까지) — 금투협 공표·수집 확인')
        else: add(key, nm, sl, fexp, '오류', f'{md(fexp)}분이 와 있어야 하는데 {md(sl)}까지만 있음({lg}거래일 늦음)')
    try:
        L = X['증시자금추이_금투협'].sort_values('일자'); C = X['신용공여잔고_금투협'].sort_values('일자')
        c2 = C.iloc[-2:, 1].astype(float).tolist()
        if len(c2) == 2 and c2[0] == c2[1]: add('credit_repeat', '신용잔고 값 되풀이', last_date(C), fexp, '주의', '최근 두 거래일 신용융자 잔고가 똑같음 — 자료가 멈췄는지 확인')
    except Exception: pass

    # ------------------------------------------------------------------ 5 미국 VIX
    VX = X.get('참고_VIX_유가'); xl = last_date(VX, valcol='VIX 종가'); uexp = us_final_date(now)
    lg = us_lag(xl, uexp)
    if lg <= 0: add('vix', '미국 VIX', xl, uexp, '정상', 'CBOE 공식 일별 파일(야후·네이버와 대조) — 뉴욕 장이 끝난 날만 저장')
    elif lg == 1: add('vix', '미국 VIX', xl, uexp, '주의', f'{md(uexp)}분 미도착({md(xl)}까지) — VIX 조건(최적화 2위 매수 등)이 하루 전 값으로 계산됨(미국 휴장일이면 정상)')
    else: add('vix', '미국 VIX', xl, uexp, '오류', f'{md(uexp)}분이 와 있어야 하는데 {md(xl)}까지만 있음(미국 영업일 {lg}일 늦음)')
    if VX is not None and xl is not None:
        vv = VX[VX['VIX 종가'].notna()].sort_values('일자')
        if pd.to_datetime(vv['일자']).max().date() > uexp: add('vix_future', '미국 VIX 날짜', xl, uexp, '오류', f'{md(xl)} 값이 들어 있음 — 뉴욕 장이 아직 끝나지 않은 날의 값(종가 아님)')
        if not (8 < float(vv['VIX 종가'].iloc[-1]) < 100): add('vix_range', '미국 VIX 값 범위', xl, uexp, '오류', f"{md(xl)} 값 {vv['VIX 종가'].iloc[-1]} — 범위(8~100) 밖")

    # ------------------------------------------------------------------ 6 야간선물(일자 = 야간거래 종료일 T+1 거래일)
    N = X.get('야간선물_일별'); nl = last_date(N, valcol='종가')
    # 기대 표기일 = 지금까지 끝난 야간장 가운데 가장 늦은 것. 표기일 D 의 세션은 직전 거래일 18:00~다음 날 06:00 — 금요일 저녁장(월요일 표기)은 토요일 06:00 에 끝나므로 주말에는 월요일 표기분까지 기대한다
    nexp = cal.next(today - dt.timedelta(days=1)); nnow = now.replace(tzinfo=None)
    while dt.datetime.combine(cal.prev(nexp) + dt.timedelta(days=1), dt.time(6, 30)) > nnow: nexp = cal.prev(nexp)
    lg = cal.lag(nl, nexp)
    nsrc = ''
    try: nsrc = str(N.sort_values('일자').iloc[-1]['원본 파일'])
    except Exception: pass
    if lg <= 0: add('night', '코스피200 야간선물', nl, nexp, '정상' if '차트로그' not in nsrc else '주의', 'KRX 정보데이터시스템(시장구분 야간) · 공개 출처와 대조' if '차트로그' not in nsrc else f'{md(nl)}분은 KRX 값이 없어 공개 출처(차트로그) 값으로 채움 — 주간 선물 종가 대조는 통과')
    elif lg == 1: add('night', '코스피200 야간선물', nl, nexp, '주의', f'{md(nexp)} 표기분(전 거래일 저녁장) 미도착({md(nl)}까지) — 휴장 전날이면 정상')
    else: add('night', '코스피200 야간선물', nl, nexp, '오류', f'{md(nexp)} 표기분이 와 있어야 하는데 {md(nl)}까지만 있음({lg}거래일 늦음) — 다음 날 시초가 카드의 야간선물 값이 비어 있음')

    # ------------------------------------------------------------------ 7 환율·미국 금리(공개 수집, 뉴욕 마감 기준 → 하루 늦게)
    for key, nm, sheet, tol in (('fx', '원/달러 환율', '참고_원달러', 2), ('us_rates', '미국 금리', '참고_미국금리', 3)):
        S = X.get(sheet); sl = last_date(S)
        lg = cal.lag(sl, kexp)
        add(key, nm, sl, kexp, '정상' if lg <= tol else '주의', '공개 수집 저장소(뉴욕 마감 기준, 한두 거래일 늦게 들어옴)' if lg <= tol else f'{md(sl)}에서 멈춤({lg}거래일 늦음) — 공개 수집 저장소 갱신 확인')

    # ------------------------------------------------------------------ 8 공개 수집 저장소 갱신 시각
    try:
        j = json.load(open(os.path.join(a.public, 'data', 'ledger', 'daum_index.json'), encoding='utf-8')); fa = pd.Timestamp(j.get('fetched_at'))
        fa = fa.tz_convert('Asia/Seoul').tz_localize(None) if fa.tzinfo is not None else fa
        age_h = (now.replace(tzinfo=None) - fa.to_pydatetime()).total_seconds() / 3600
        need = pd.Timestamp(dt.datetime.combine(kexp, dt.time(15, 35)))
        if fa < need and (now.replace(tzinfo=None) - need.to_pydatetime()).total_seconds() > 3 * 3600: add('public_repo', '공개 수집 저장소', fa.date(), kexp, '주의', f'마지막 갱신 {fa:%m/%d %H:%M} — {md(kexp)} 장 마감 뒤 갱신이 없음(이 대시보드의 직접 수집은 정상일 수 있음)')
        else: add('public_repo', '공개 수집 저장소', fa.date(), kexp, '정상', f'마지막 갱신 {fa:%m/%d %H:%M}(예비·대조용)')
    except Exception as e: add('public_repo', '공개 수집 저장소', None, kexp, '주의', '갱신 시각을 읽지 못함: ' + repr(e)[:60])

    # ------------------------------------------------------------------ 9 계산 결과 파일(선물·ETF·애프터마켓)이 종가 날짜까지 왔는지
    for key, nm, fn_, after in (('fut', '코스피200 선물(주간)·베이시스', 'fut_daily.csv', dt.time(18, 30)), ('etf', 'KODEX 레버리지', 'etf_lev.csv', dt.time(18, 30)), ('am', '애프터마켓', 'am_daily.csv', dt.time(20, 15))):
        p = os.path.join(a.out, fn_)
        if not os.path.exists(p): add(key, nm, None, kexp, '주의', f'{fn_} 없음'); continue
        try:
            df = pd.read_csv(p); sl = pd.to_datetime(df['date']).max().date()
            exp = kexp if (not same_day or now.time() >= after) else cal.prev(kexp)
            lg = cal.lag(sl, exp)
            add(key, nm, sl, exp, '정상' if lg <= 0 else ('주의' if lg == 1 else '오류'), '' if lg <= 0 else f'{md(exp)}분 미도착({md(sl)}까지)')
        except Exception as e: add(key, nm, None, kexp, '주의', f'{fn_} 읽기 실패: ' + repr(e)[:60])

    # ------------------------------------------------------------------ 10 수집 항목별 실패·주의(status.json)
    lv = {r['key']: r['status'] for r in rows}
    if status is None and a.collect: add('collect', '수집 실행 기록', None, None, '오류', 'status.json 없음 — 수집 단계가 끝까지 돌지 못함')
    elif status is not None:
        behind = lambda k: lv.get(k) in ('오류', '주의')
        for name, msg in status.get('fail', []):
            key = ('night' if name.startswith('09_') else 'vkospi' if name.startswith('10') else 'kofia_funds' if name.startswith('07') else 'kofia_credit' if name.startswith('08') else 'vix' if name.startswith('13') else
                   'kospi' if name.startswith('01') else 'investor' if name.startswith('03') else 'etf' if name.startswith(('04_ETF', '05', '06')) else 'fut' if name.startswith('04') else '')
            short = str(msg).split(' — ')[0][:110]
            if name.startswith('10_VKOSPI') and '키 없음' in str(msg): continue
            if key and not behind(key): add('collect_' + name[:12], f'수집 실패(예비 출처로 채움): {name}', None, None, '주의', short)
            else: add('collect_' + name[:12], f'수집 실패: {name}', None, None, '오류', short)
        for name, msg in status.get('warn', []): add('collectw_' + name[:12], f'수집 주의: {name}', None, None, '주의', str(msg)[:160])
        if status.get('krx_today_ok') is False: pass      # 위 warn 에 이미 들어 있음

    # ------------------------------------------------------------------ 11 출처 간 대조·정정(daily_update warnings)
    for w in summ.get('warnings', []):
        add('x_' + str(w.get('key', '')), {'kospi_close': '코스피 종가 대조', 'investor': '투자자별 대조', 'vkospi': 'VKOSPI 대조', 'night': '야간선물 대조', 'vix_fix': '미국 VIX 정정'}.get(w.get('key'), '대조'), None, None, w.get('level', '주의'), str(w.get('msg', ''))[:220])

    # ------------------------------------------------------------------ 12 확정된 지 오래된 날짜의 값이 바뀐 것(값_교체_기록 — 출처 표기·반올림 0.1 은 제외)
    old = []
    for ch in summ.get('changes', []):
        try:
            sheet, d_, col, o, _, n = ch[0], ch[1], ch[2], ch[3], ch[4], ch[5]
            if sheet not in ('코스피_일별', 'VKOSPI_일별', '증시자금추이_금투협', '신용공여잔고_금투협', '투자자별_코스피_일별') or '출처' in col or '원본' in col: continue
            dd = dt.date.fromisoformat(str(d_)[:10])
            if (kexp - dd).days < 6: continue
            fo, fn2 = float(o), float(n)
            if np.isnan(fo) or abs(fo - fn2) <= max(0.11, abs(fn2) * 1e-4): continue
            old.append(f'{sheet.split("_")[0]} {dd.month}/{dd.day} {col.split("(")[0]} {fo:g}→{fn2:g}')
        except Exception: continue
    if old: add('old_change', '확정 뒤 값 변경', None, None, '주의', f'확정된 지 6일 넘은 날짜의 값 {len(old)}건이 바뀜: ' + '; '.join(old[:3]))

    # ------------------------------------------------------------------ 13 파이프라인 단계 오류(run_pipeline.py)
    perr = []
    if a.pipeline_errors and os.path.exists(a.pipeline_errors):
        try: perr = json.load(open(a.pipeline_errors, encoding='utf-8'))
        except Exception: perr = []
    for e in perr:
        if str(e).startswith('VKOSPI') and '미반영' in str(e): continue        # VKOSPI 항목에서 따로 본다
        add('step', '실행 단계 오류', None, None, '오류', str(e)[:200])

    # ------------------------------------------------------------------ 14 취소된 신호: 이미 알림으로 나간 매수·매도 신호가 자료 확정·정정 뒤 사라졌는지
    #   (11/13 「매수 최적화 2위」는 틀린 VIX 값 때문에 켜졌고 값이 고쳐지면 사라진다 — 조용히 없어지지 않게 정정으로 남기고 다음 알림에 싣는다)
    try:
        sp = os.path.join(a.report, 'sent_signals.json'); rt_fn = os.path.join(a.report, 'retractions.json')
        rts = json.load(open(rt_fn, encoding='utf-8')) if os.path.exists(rt_fn) else []
        if os.path.exists(sp):
            sent = set(tuple(x) for x in json.load(open(sp, encoding='utf-8')))
            rdc = lambda f_: pd.read_csv(os.path.join(a.out, f_)) if os.path.exists(os.path.join(a.out, f_)) else None
            M = rdc('market_daily.csv'); mk = str(M.iloc[-1]['date']); cut10 = (dt.date.fromisoformat(mk[:10]) - dt.timedelta(days=10)).isoformat()
            cur = set()
            for df, fn_ in ((rdc('alarms.csv'), lambda r: f"{r['side']} {r['type']}"), (rdc('buy3.csv'), lambda r: f"매수 최적화 {int(r['rank'])}위"), (rdc('sell3.csv'), lambda r: f"매도 최적화 {int(r['rank'])}위")):
                if df is None or 'start' not in df.columns: continue
                for _, r in df[(df['start'] == '시작') & (df['date'] >= cut10)].iterrows(): cur.add((r['date'], fn_(r)))
            why = '미국 VIX 값 정정' if any(w.get('key') == 'vix_fix' for w in summ.get('warnings', [])) else '자료 확정·정정'
            have = {(x['date'], x['label']) for x in rts}
            for d_, lab in sorted(x for x in sent if x[0] >= cut10 and x not in cur):
                if (d_, lab) not in have: rts.append({'date': d_, 'label': lab, 'found_at': f'{now:%Y-%m-%d %H:%M}', 'reason': why, 'notified': None})
            # 다시 켜진 신호는 취소 목록에서 뺀다
            rts = [x for x in rts if (x['date'], x['label']) not in cur and (now.date() - dt.date.fromisoformat(x['found_at'][:10])).days <= 30]
            json.dump(rts, open(rt_fn, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        for x in rts:
            if (now.date() - dt.date.fromisoformat(x['found_at'][:10])).days <= 7:
                dd = dt.date.fromisoformat(x['date'][:10])
                add(f"retract_{x['date']}_{x['label']}", '신호 취소', x['date'], None, '정정', f"{dd.month}/{dd.day} {x['label']} 신호 취소 — {x['reason']}으로 조건이 맞지 않게 됨(이미 알림에 나갔던 신호, {x['found_at'][5:10].replace('-', '/')} 확인)")
    except Exception as e: add('retract', '신호 취소 확인', None, None, '주의', '확인 실패: ' + repr(e)[:80])

    # ------------------------------------------------------------------ 15 웹판 수기 결론 카드(docs/page.html): 아침 08:55 Claude 예약 작업이 쓴 카드가 웹판에 왔는지
    #   (11/15 확인: 웹판에는 11/11 작성 카드가 사흘째 그대로였다 — 예약 작업의 웹판 반영 단계가 조용히 건너뛰어졌는데 어디에도 표시가 없었다)
    #   카드는 다음 거래일 아침 09시에 쓰므로 카드 기준일이 마지막 종가보다 1거래일 이른 것은 정상, 2거래일부터 주의
    #   (수기 해설이 늦은 것이지 신호에 쓰는 자료가 틀린 것은 아니므로 며칠이 지나도 '오류'로 올리지 않는다 — 자료 오류와 섞여 묻히지 않게)
    try:
        pg = os.path.join(a.docs, 'page.html')
        if os.path.exists(pg) and K is not None and kl is not None:
            import re
            m = re.search(r'아래 네 카드는\s*(\d{1,2})/(\d{1,2})\s*장 마감', open(pg, encoding='utf-8').read())
            if not m: add('web_cards', '웹판 결론 카드(수기)', None, None, '주의', '기준일 문장(「아래 네 카드는 M/D 장 마감」)을 찾지 못함 — 카드 형식이 바뀌었는지 확인')
            else:
                base = dt.date(kl.year, int(m.group(1)), int(m.group(2)))
                if base > kl: base = dt.date(kl.year - 1, int(m.group(1)), int(m.group(2)))
                kd = sorted(set(d_ for d_ in pd.to_datetime(K['일자']).dt.date if d_ <= kl)); after = [d_ for d_ in kd if d_ > base]
                wexp = kd[-2] if len(kd) >= 2 else None
                if len(after) <= 1: add('web_cards', '웹판 결론 카드(수기)', base, wexp, '정상', f'{md(base)} 장 마감 기준 — 평일 08:55 예약 작업이 다음 거래일 아침에 다시 쓴다')
                else: add('web_cards', '웹판 결론 카드(수기)', base, wexp, '주의', f'{md(base)} 장 마감 기준에서 멈춤 — 그 뒤 {len(after)}거래일({md(after[0])}~{md(after[-1])})이 지났는데 아침 카드가 웹판에 오지 않음(08:55 예약 작업의 웹판 반영 확인)')
    except Exception as e: add('web_cards', '웹판 결론 카드(수기)', None, None, '주의', '확인 실패: ' + repr(e)[:80])

    # ------------------------------------------------------------------ 결과
    H = pd.DataFrame(rows); H['checked_at'] = f'{now:%Y-%m-%d %H:%M}'; H['tag'] = a.tag
    H['ord'] = H['status'].map(ORDER).fillna(9); H = H.sort_values(['ord']).drop(columns='ord').reset_index(drop=True)
    os.makedirs(a.out, exist_ok=True); H.to_csv(os.path.join(a.out, 'health.csv'), index=False)
    errs = H[H.status == '오류']; cauts = H[H.status == '주의']; fixes = H[H.status == '정정']
    SHORT = {'kospi': '코스피 종가', 'kospi_ohlc': '코스피 시고저', 'investor': '투자자별', 'vkospi': 'VKOSPI', 'kofia_funds': '금투협', 'kofia_credit': '금투협 신용', 'vix': 'VIX', 'vix_future': 'VIX 날짜', 'night': '야간선물',
             'fx': '환율', 'us_rates': '미국 금리', 'public_repo': '공개 저장소', 'fut': '선물', 'etf': 'ETF', 'am': '애프터마켓', 'x_vix_fix': 'VIX 정정', 'x_kospi_close': '종가 불일치', 'x_investor': '투자자별 대조',
             'x_vkospi': 'VKOSPI 대조', 'x_night': '야간선물 대조', 'old_change': '과거 값 변경', 'step': '실행 단계', 'collect': '수집 기록', 'web_cards': '웹판 카드'}
    def short(r):
        k = str(r['key'])
        if k.startswith('retract'): return '신호 취소'
        if k.startswith('collect'): return r['name'].split(': ')[-1].split('_', 1)[-1][:8] + ' 수집'
        return SHORT.get(k, SHORT.get(k.rsplit('_', 1)[0], r['name'][:8]))
    parts = []
    if len(errs): parts.append(f'오류 {len(errs)}건')
    if len(fixes): parts.append(f'정정 {len(fixes)}건')
    if len(cauts): parts.append(f'주의 {len(cauts)}건')
    if parts:
        top = pd.concat([errs, fixes, cauts]).head(2)
        names = list(dict.fromkeys(short(r) for _, r in top.iterrows()))
        line = ('·'.join(parts) + '(' + ', '.join(names) + (' 등' if len(errs) + len(fixes) + len(cauts) > 2 else '') + ')')[:36]
    else: line = '정상'
    issues = [{'key': r['key'], 'status': r['status'], 'name': r['name'], 'note': r['note']} for _, r in pd.concat([errs, fixes, cauts]).iterrows()]
    prev = json.load(open(a.state, encoding='utf-8')) if os.path.exists(a.state) else {}
    pk = {x['key']: x for x in prev.get('issues', [])}; ck = {x['key']: x for x in issues}
    new = [x for k, x in ck.items() if k not in pk or ORDER.get(x['status'], 9) < ORDER.get(pk[k]['status'], 9)]
    resolved = [x for k, x in pk.items() if k not in ck]
    out = {'checked_at': f'{now:%Y-%m-%d %H:%M}', 'tag': a.tag, 'level': 'error' if len(errs) else ('fix' if len(fixes) else ('warn' if len(cauts) else 'ok')), 'line': line,
           'counts': {'오류': int(len(errs)), '정정': int(len(fixes)), '주의': int(len(cauts)), '참고': int((H.status == '참고').sum()), '정상': int((H.status == '정상').sum())},
           'issues': issues, 'new': new, 'resolved': resolved, 'errors': [f"{r['name']}: {r['note']}" for _, r in errs.iterrows()],
           'expected': {'kospi': str(kexp), 'vkospi': str(vexp), 'kofia': str(fexp), 'vix': str(uexp), 'night': str(nexp)}}
    os.makedirs(a.report, exist_ok=True); json.dump(out, open(os.path.join(a.report, 'health.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('자료 점검:', line); print(H[['name', 'last', 'expected', 'status', 'note']].to_string(max_colwidth=70))


if __name__ == '__main__': main()
