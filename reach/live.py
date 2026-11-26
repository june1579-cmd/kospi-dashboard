# 오늘의 장중 도달 확률표 — pre(08:30판, 장 전) · post(09:10판, 시가와 장 초반 고가·저가 반영)(2026-11-26).
# pre : python reach/live.py --pre [--wait 40]   (야간선물이 아직 안 들어왔으면 git pull 하며 기다림, 끝내 없으면 간밤 미국으로 대체하고 표시)
# post: reach/flow.py 가 09:12:30 에 run_post(idx, fut) 호출 — KIS 실시간 시가·고가·저가 사용
import argparse, json, os, subprocess, sys, time
from datetime import date, datetime, timedelta, timezone
import numpy as np, pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from reach.model import Dist, LEVELS, TARGETS, NAME, load

OUT = os.path.join(ROOT, 'docs', 'reach', 'data')
QS = (0.1, 0.5, 0.9)


def holidays():
    try: return set(json.load(open(os.path.join(ROOT, 'pkg', 'holidays_kr.json'), encoding='utf-8'))['holidays'])
    except Exception: return set()


def next_trading(d, hol):
    d = d + timedelta(days=1)
    while d.weekday() >= 5 or d.isoformat() in hol: d += timedelta(days=1)
    return d


def prev_trading(d, hol):
    d = d - timedelta(days=1)
    while d.weekday() >= 5 or d.isoformat() in hol: d -= timedelta(days=1)
    return d


def params():
    return json.load(open(os.path.join(ROOT, 'reach', 'out', 'params.json')))


def r1(v): return None if v is None or (isinstance(v, float) and np.isnan(v)) else round(float(v), 4)


def ladders(row, P, time, cond=None):
    """row: 한 줄 DataFrame. cond: {(inst,ref,side): 이미 찍은 값(%)} — 장 초반에 이미 닿은 칸은 100%, 그 위는 조건부 확률"""
    out = {}
    for inst, ref, side in TARGETS:
        key = f'{time}_{inst}_{side}_{ref}'
        if key not in P['models']: continue
        m = Dist.from_params(P['models'][key]); p = m.ladder(row, side, LEVELS)[0]
        mu, s = m.loc_scale(row); q = {str(qq): r1(mu[0] + s[0] * np.interp(qq, np.linspace(0.0005, 0.9995, 2000), m.z)) for qq in QS}
        seen = (cond or {}).get((inst, ref, side))
        if seen is not None and not np.isnan(seen):
            x = seen if side == 'up' else -seen                       # 이미 닿은 폭(양수, 반대 방향이면 음수)
            if x > 0:
                p_seen = m.ladder(row, side, [x])[0][0]
                p = np.where(LEVELS <= x + 1e-9, 1.0, np.minimum(1.0, p / max(p_seen, 1e-6)))
        out[f'{inst}_{ref}_{side}'] = dict(p=[round(float(v) * 100, 1) for v in p], q=q, seen=r1(seen), foreign=P['models'][key].get('foreign', False))
    return out


def night_from_kis(t, fc):
    """장 전 야간선물 종가: KIS 1분봉(시장 CM)에서 t 저녁 세션의 마지막 봉(06:00). 키가 없거나 실패하면 None"""
    try:
        from reach.kis import KIS, front_code, pick
        k = KIS(gap=0.45)
        if not k.ok() or not fc: return None, '키 없음'
        code, _ = front_code(date.fromisoformat(t) + timedelta(days=1))
        d1 = (date.fromisoformat(t) + timedelta(days=1)).strftime('%Y%m%d')
        r = k.get('/uapi/domestic-futureoption/v1/quotations/inquire-time-fuopchartprice', 'FHKIF03020200', {'FID_COND_MRKT_DIV_CODE': 'CM', 'FID_INPUT_ISCD': code, 'FID_HOUR_CLS_CODE': '60',
                  'FID_PW_DATA_INCU_YN': 'Y', 'FID_FAKE_TICK_INCU_YN': 'N', 'FID_INPUT_DATE_1': d1, 'FID_INPUT_HOUR_1': '060000'})
        allr = r.get('output2') or []
        rows = [x for x in allr if x.get('stck_bsop_date') == t.replace('-', '')]
        if not rows:   # 요청 방식 둘째: 세션 날짜 t, 시각 300000(24시 넘는 표기)
            r2 = k.get('/uapi/domestic-futureoption/v1/quotations/inquire-time-fuopchartprice', 'FHKIF03020200', {'FID_COND_MRKT_DIV_CODE': 'CM', 'FID_INPUT_ISCD': code, 'FID_HOUR_CLS_CODE': '60',
                       'FID_PW_DATA_INCU_YN': 'Y', 'FID_FAKE_TICK_INCU_YN': 'N', 'FID_INPUT_DATE_1': t.replace('-', ''), 'FID_INPUT_HOUR_1': '300000'})
            all2 = r2.get('output2') or []; rows = [x for x in all2 if x.get('stck_bsop_date') == t.replace('-', '')]
            if not rows:
                seen = sorted({(x.get('stck_bsop_date'), x.get('stck_cntg_hour')) for x in allr + all2})
                return None, f"KIS 야간 봉 없음({code}, 받은 {len(allr)}+{len(all2)}개 {seen[:1]}~{seen[-1:]})"[:160]
        last = max(rows, key=lambda x: x.get('stck_cntg_hour'))
        if last.get('stck_cntg_hour') < '295500': return None, f"야간 세션이 아직 안 끝남(마지막 {last.get('stck_cntg_hour')})"
        c = pick(last, 'prpr'); return (100 * (c / fc - 1) if c else None), f'KIS 야간 1분봉({code}) 종가 {c}'
    except Exception as e:
        return None, repr(e)[:80]


def log(res, board):
    """날짜별 적중 분석용 기록: docs/reach/data/log/대상날짜_판.json(같은 날 다시 계산하면 덮어씀)"""
    d = os.path.join(OUT, 'log'); os.makedirs(d, exist_ok=True)
    keep = {k: res[k] for k in ('kind', 'label', 'built', 'for_date', 'status', 'ref_price', 'ladders') if k in res}
    for v in keep['ladders'].values(): v['p'] = v['p'][:60]                    # 0.1~6% 만 남겨 가볍게
    json.dump(keep, open(os.path.join(d, f"{res['for_date']}_{board}.json"), 'w', encoding='utf-8'), ensure_ascii=False)


def run_eve(wait=0, deriv=None):
    """16:20판: 오늘 장 마감 직후 알 수 있는 값(오늘 종가·고가·저가·변동성)만으로 다음 거래일 도달 확률"""
    hol = holidays(); deriv = deriv or os.path.join(ROOT, '_deriv', 'deriv', 'data')
    today = (datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=9)).date()
    t0 = time.time()
    while True:
        D = load(deriv); last = D.index[-1]
        if last >= today.isoformat() or time.time() - t0 > wait * 60: break
        print(f'오늘 코스피200 자료 기다림 (마지막 {last})', flush=True); time.sleep(120)
        subprocess.run(['git', 'pull', '-q', '--rebase'], cwd=ROOT)
    for_date = next_trading(date.fromisoformat(last), hol); st = []
    if last < today.isoformat() and today.weekday() < 5 and today.isoformat() not in hol: st.append(f'오늘({today}) 장 자료가 아직 없어 {last} 자료로 계산')
    P = params(); row = D.iloc[[-1]].copy(); lad = ladders(row, P, 'eve')
    g = lambda c: r1(row[c].iloc[0]) if c in row else None
    res = dict(kind='eve', label='16:20판', built=(datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=9)).strftime('%Y-%m-%d %H:%M KST'), for_date=for_date.isoformat(),
               base_date=last, status=st, levels=[float(x) for x in LEVELS], ref_price={'S_c': g('c'), 'F_c': g('fc'), 'S_o': None, 'F_o': None},
               inputs={'오늘 코스피200(%)': g('own'), '20일 변동성(%)': g('rv20'), '20일 평균 하루 폭(%)': g('park20'), '오늘 종가': g('c'), '오늘 선물 종가': g('fc')},
               ladders=lad, params_fitted=P.get('fitted'))
    os.makedirs(OUT, exist_ok=True); json.dump(res, open(os.path.join(OUT, 'eve.json'), 'w', encoding='utf-8'), ensure_ascii=False); log(res, 'eve')
    print('16:20판 저장', for_date, '· 상태', st or '정상', flush=True)
    from reach import hits
    hits.save(D)
    return res


def run_pre(wait=0, deriv=None):
    hol = holidays(); deriv = deriv or os.path.join(ROOT, '_deriv', 'deriv', 'data'); night_src = '코스피 대시보드 수집(KRX)'
    today = (datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=9)).date()
    for_date = today if (today.weekday() < 5 and today.isoformat() not in hol) else next_trading(today, hol)
    t_exp = prev_trading(for_date, hol).isoformat()
    # 간밤 미국 일봉이 밀려 있으면 직접 받아 둔다(저장소 fo/data 는 커밋하지 않음 — 이 계산에만 씀)
    if subprocess.run([sys.executable, 'fo/us_due.py'], cwd=ROOT).returncode == 0:
        subprocess.run([sys.executable, 'fo/collect_us.py', 'px', 'vix'], cwd=ROOT)
    t0 = time.time()
    while True:
        D = load(deriv); last = D.index[-1]
        night_ok = last == t_exp and not np.isnan(D['night'].iloc[-1])
        if night_ok or time.time() - t0 > wait * 60: break
        if last == t_exp and np.isnan(D['night'].iloc[-1]):                 # 야간선물: KIS 에서 직접(대시보드 08:23 수집보다 빠름)
            v, why = night_from_kis(last, D['fc'].iloc[-1]); print('야간선물 KIS:', v, why, flush=True)
            if v is not None:
                D.loc[last, 'night'] = v; night_src = why; break
        print(f'야간선물·전날 자료 기다림 (마지막 {last}, 야간 {D["night"].iloc[-1]})', flush=True); time.sleep(120)
        subprocess.run(['git', 'stash', '-q'], cwd=ROOT); subprocess.run(['git', 'pull', '-q', '--rebase'], cwd=ROOT); subprocess.run(['git', 'stash', 'pop', '-q'], cwd=ROOT)
    if last >= for_date.isoformat():                                   # 장 마감 뒤 손으로 돌린 경우: 다음 거래일 것
        for_date = next_trading(date.fromisoformat(last), hol); t_exp = last
    if os.environ.get('NIGHT_KIS_TEST'):
        v, why = night_from_kis(last, D['fc'].iloc[-1]); print(f"[시험] KIS 야간선물 {v} ({why}) vs 저장소 값 {D['night'].iloc[-1]}", flush=True)
    P = params(); row = D.iloc[[-1]].copy(); st = []
    if last != t_exp: st.append(f'전날({t_exp}) 자료가 아직 없어 {last} 자료로 계산')
    if np.isnan(row['night'].iloc[0]): st.append('야간선물 값이 없어 간밤 미국·VIX로 대신 계산'); night_src = '없음'
    us_dates = [d for d in pd.read_csv(os.path.join(ROOT, 'fo', 'data', 'px.csv')).query("sym == 'spx'")['date'] if d >= last]
    if not us_dates and subprocess.run([sys.executable, 'fo/us_due.py'], cwd=ROOT).returncode == 0: st.append('간밤 미국 일봉을 받지 못함')
    elif not us_dates: st.append('간밤 미국 장이 열리지 않음(휴장) — 간밤 S&P500·VIX 없이 계산')
    # 빠진 입력은 모형이 학습 기간 중앙값으로 대신하므로 '정상'으로 두지 않고 적는다(2026-11-27 사용자 지적)
    miss = [nm for c, nm in (('own', '전날 코스피200'), ('rv20', '20일 변동성'), ('park20', '20일 평균 하루 폭'), ('us_on', '간밤 S&P500'), ('vix_on', '간밤 VIX'))
            if c in row and np.isnan(row[c].iloc[0])]
    if miss: st.append('빠진 입력: ' + '·'.join(miss) + ' (과거 중앙값으로 대신)')
    lad = ladders(row, P, 'pre')
    g = lambda c: r1(row[c].iloc[0]) if c in row else None
    res = dict(kind='pre', label='08:30판', built=(datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=9)).strftime('%Y-%m-%d %H:%M KST'), for_date=for_date.isoformat(), base_date=last,
               status=st, levels=[float(x) for x in LEVELS], night_source=night_src,
               ref_price={'S_c': g('c'), 'F_c': g('fc'), 'S_o': None, 'F_o': None},
               inputs={'야간선물(%)': g('night'), '간밤 S&P500(%)': g('us_on'), '간밤 VIX 변화(%)': g('vix_on'), '전날 코스피200(%)': g('own'), '20일 변동성(%)': g('rv20'),
                       '20일 평균 하루 폭(%)': g('park20'), '외국인 전날 순매수(평소 대비)': g('f1'), '외국인 야간 순매수(평소 대비)': g('n1')},
               features={c: g(c) for c in ('night', 'us_on', 'vix_on', 'own', 'rv20', 'park20', 'fpark20', 'f1', 'pnl1', 'n1', 'c', 'fc')}, ladders=lad, params_fitted=P.get('fitted'))
    os.makedirs(OUT, exist_ok=True); json.dump(res, open(os.path.join(OUT, 'pre.json'), 'w', encoding='utf-8'), ensure_ascii=False); log(res, 'pre')
    print('08:30판 저장', for_date, '· 상태', st or '정상', flush=True)
    for kk in ('S_c_up', 'S_c_dn'):
        v = lad.get(kk)
        if v: print(' ', kk, '1%', v['p'][9], '2%', v['p'][19], '3%', v['p'][29], flush=True)
    return res


def run_post(idx, fut, fut_code=None, asof=None):
    pre = json.load(open(os.path.join(OUT, 'pre.json'), encoding='utf-8')); P = params()
    today = (datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=9)).date().isoformat(); st = []
    if asof and asof[11:16] > '09:30': st.append(f'정해진 09:12 계산이 아닌 시험 계산({asof[11:16]} 기준 고가·저가)')
    if pre.get('for_date') != today: st.append(f"08:30판이 오늘 것이 아님({pre.get('for_date')}) — 그 입력으로 계산")
    f = pre['features']; row = pd.DataFrame([f])
    row['night'] = f.get('night'); s_prev = (idx or {}).get('prev') or f.get('c'); f_prev = (fut or {}).get('prev') or f.get('fc')
    pct = lambda a, b: 100 * (a / b - 1) if (a is not None and b) else np.nan
    so, sh, sl = (idx or {}).get('open'), (idx or {}).get('high'), (idx or {}).get('low')
    fo, fh, fl = (fut or {}).get('open'), (fut or {}).get('high'), (fut or {}).get('low')
    row['S_gap'] = pct(so, s_prev); row['F_gap'] = pct(fo, f_prev)
    if np.isnan(row['S_gap'].iloc[0]): st.append('현물 시가를 받지 못함')
    if np.isnan(row['F_gap'].iloc[0]): st.append('선물 시가를 받지 못함')
    cond = {('S', 'c', 'up'): pct(sh, s_prev), ('S', 'c', 'dn'): pct(sl, s_prev), ('S', 'o', 'up'): pct(sh, so), ('S', 'o', 'dn'): pct(sl, so),
            ('F', 'c', 'up'): pct(fh, f_prev), ('F', 'c', 'dn'): pct(fl, f_prev), ('F', 'o', 'up'): pct(fh, fo), ('F', 'o', 'dn'): pct(fl, fo)}
    lad = ladders(row, P, 'post', cond)
    res = dict(kind='post', label='09:10판', built=(datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=9)).strftime('%Y-%m-%d %H:%M KST'), asof=asof, for_date=today, status=st,
               levels=[float(x) for x in LEVELS], fut_code=fut_code,
               ref_price={'S_c': r1(s_prev), 'F_c': r1(f_prev), 'S_o': r1(so), 'F_o': r1(fo)},
               observed={'현물 시가': r1(so), '현물 고가(지금까지)': r1(sh), '현물 저가(지금까지)': r1(sl), '선물 시가(08:45)': r1(fo), '선물 고가(지금까지)': r1(fh), '선물 저가(지금까지)': r1(fl),
                         '현물 갭(%)': r1(row['S_gap'].iloc[0]), '선물 갭(%)': r1(row['F_gap'].iloc[0])},
               ladders=lad, params_fitted=P.get('fitted'))
    json.dump(res, open(os.path.join(OUT, 'post.json'), 'w', encoding='utf-8'), ensure_ascii=False)
    if not st or all('시험 계산' not in x for x in st): log(res, 'post')
    print('09:10판 저장', today, '· 상태', st or '정상', flush=True)
    return res


if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('--pre', action='store_true'); ap.add_argument('--eve', action='store_true'); ap.add_argument('--wait', type=float, default=0); ap.add_argument('--deriv', default=None)
    a = ap.parse_args()
    if a.pre: run_pre(a.wait, a.deriv)
    if a.eve: run_eve(a.wait, a.deriv)
