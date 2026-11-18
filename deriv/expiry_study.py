"""만기까지 쌓은 선물·옵션 포지션 → 만기 전후 코스피 — 조합마다 따로 검증.

만기 종류: 분기(3·6·9·12월 둘째 목요일, 선물·옵션 동시), 월물(그 밖의 달 둘째 목요일), 목요일 위클리(2019-09~), 월요일 위클리(2023-08~).
  휴장일이면 목요일 만기는 앞 거래일, 월요일 만기는 뒤 거래일(증권사 상품안내). 월물 날짜는 옵션 전종목 자료(2015~)의 월물별 마지막 거래일과 대조.
투자자: 외국인, 기관(금융투자·보험·투신·은행·기타금융·연기금 합), 금융투자, 개인. 위클리 옵션 자료(13102 기본)에는 금융투자가 따로 없다.
포지션(관측일까지, 직전 같은 종류 만기 다음 날부터 누적):
  FUT  코스피200 선물 순매수 금액 누적(정규장, 원)
  FUTQ 분기 만기만: 직전 분기 만기 뒤 3개월 누적
  OPT  옵션 콜 순매수 − 풋 순매수 금액 누적(월물·분기는 코스피200 옵션, 위클리는 해당 위클리 옵션) — 프리미엄 기준
  OI   선물 최근월물 미결제약정 변화율(시장 전체, 투자자 구분 없음)
  OPC  만기 월물의 풋 미결제 ÷ 콜 미결제(시장 전체, 2015~)
  FUT|OI↑, FUT|OI↓: 미결제가 늘어난(새 포지션) 주기와 줄어든 주기로 나눈 FUT
구간(관측일 종가 → 끝 종가):
  남은기간 T-10→T, 만기주간 T-5→T, 만기당일 T-1→T, 다음날 T→T+1, 만기후5일 T→T+5 (위클리는 T-10·T-5 없음, 대신 T-2→T)
투자자별 확정치는 관측일 18시 이후 나오므로 관측일 종가 이후 움직임만 본다(미래를 보지 않음). 단 관측일 종가 자체로는 체결 못 한다.
검증(조합마다 따로):
  n<30 → 판정 불가. 스피어만 순위상관 ρ와 p, 누적 기간 코스피 등락을 통제한 부분 ρ, 상·하위 1/3 평균 차이, 앞·뒤 절반 부호 일치,
  선행 방향 시험(앞 40% 사건으로 방향을 정하고 뒤 60%에서만 ρ), 전체 조합 BH 보정 q.
  A: q≤0.10 · 앞뒤 절반 같은 부호 · 선행 시험 ρ>0, p<0.10 · 부분 ρ 같은 부호 / B: q≤0.10 · 앞뒤 같은 부호 / C: p<0.05 / 그 밖 탈락.
출력: deriv/out/expiry_tests.csv, expiry_events.csv, expiry_dates.csv
"""
import os
import sys

import numpy as np
import pandas as pd
from scipy import stats

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
import analyze as A  # noqa: E402

OUT = os.path.join(ROOT, 'out')
px = A.load_price()
TD = px.index                       # 코스피 거래일
TODAY = pd.Timestamp.now(tz='Asia/Seoul').normalize().tz_localize(None)
LAST = TD[TD < TODAY].max()         # 오늘(장중일 수 있음)은 빼고 확정된 날까지만


def prev_td(d):
    i = TD.searchsorted(d, side='right') - 1
    return TD[i] if i >= 0 else None


def next_td(d):
    i = TD.searchsorted(d, side='left')
    return TD[i] if i < len(TD) else None


def second_thursday(y, m):
    d = pd.Timestamp(y, m, 1)
    d += pd.Timedelta(days=(3 - d.weekday()) % 7)
    return d + pd.Timedelta(days=7)


def expiry_dates():
    rows = []
    for y in range(2008, 2027):
        for m in range(1, 13):
            st = second_thursday(y, m)
            t = prev_td(st)
            if t is None or t > LAST or t < pd.Timestamp('2008-01-01'): continue
            rows.append({'date': t, '종류': '분기' if m in (3, 6, 9, 12) else '월물', '원래': st})
    sec = {second_thursday(y, m) for y in range(2019, 2027) for m in range(1, 13)}
    d = pd.Timestamp('2019-09-26')
    while d <= LAST:
        if d not in sec:
            t = prev_td(d)
            if t is not None and t <= LAST: rows.append({'date': t, '종류': '위클리목', '원래': d})
        d += pd.Timedelta(days=7)
    d = pd.Timestamp('2023-08-07')
    while d <= LAST:
        t = next_td(d)
        if t is not None and t <= LAST: rows.append({'date': t, '종류': '위클리월', '원래': d})
        d += pd.Timedelta(days=7)
    E = pd.DataFrame(rows).drop_duplicates(['date', '종류']).sort_values('date').reset_index(drop=True)
    return E


def check_monthly(E):
    """월물 만기 = 옵션 전종목 자료의 월물별 마지막 거래일(2015~)과 대조."""
    ch = pd.read_csv(os.path.join(A.DATA, 'opt_chain_daily.csv.gz'), usecols=['날짜', 'ym'])
    ch['날짜'] = pd.to_datetime(ch['날짜'])
    last = ch.groupby('ym')['날짜'].max()
    em = E[E['종류'].isin(['분기', '월물'])]
    mine = pd.Series(em['date'].values, index=em['원래'].dt.strftime('%Y%m').astype(int).values)
    both = pd.concat([mine.rename('규칙'), last.rename('자료')], axis=1).dropna()
    both = both[both['자료'] < last.max()]          # 아직 만기 안 된 월물 제외
    bad = both[both['규칙'] != both['자료']]
    return len(both), bad


# ---------------------------------------------------------------- 자료
inv = A.rd('inv_daily')
INST = ['금융투자', '보험', '투신', '은행', '기타금융', '연기금']


def flows_detail(prod, opt):
    f = A.investor_frame(inv, prod, opt, detail=True)
    out = pd.DataFrame(index=f.index)
    out['외국인'] = f['외국인']; out['개인'] = f['개인']; out['금융투자'] = f['금융투자']
    out['기관'] = f[[c for c in INST if c in f]].sum(axis=1, min_count=1)
    return out


def flows_basic(prod, opt):
    f = A.investor_frame(inv, prod, opt)
    if f is None: return None
    return pd.DataFrame({'외국인': f['외국인'], '개인': f['개인'], '기관': f['기관']}, index=f.index)


FUT = flows_detail('FUK2I', 'ALL')
OPT_M = flows_detail('OPK2I', 'C') - flows_detail('OPK2I', 'P')
OPT_WT = (lambda c, p: None if c is None else c - p)(flows_basic('OPWKI', 'C'), flows_basic('OPWKI', 'P'))
OPT_WM = (lambda c, p: None if c is None else c - p)(flows_basic('OPWKM', 'C'), flows_basic('OPWKM', 'P'))

fr = A.rd('fut_front_daily'); fr['date'] = A.ddate(fr['TRD_DD'])
fr = fr.drop_duplicates('date', keep='last').set_index('date').sort_index()
FOI = A.num(fr['ACC_OPNINT_QTY'])
FNM = fr['ISU_NM'] if 'ISU_NM' in fr else pd.Series('', index=fr.index)

ch = pd.read_csv(os.path.join(A.DATA, 'opt_chain_daily.csv.gz'), usecols=['날짜', 'cp', 'ym', 'oi'])
ch['날짜'] = pd.to_datetime(ch['날짜'])
OIc = ch.pivot_table(index=['날짜', 'ym'], columns='cp', values='oi', aggfunc='sum')   # 월물별 콜·풋 미결제 합

close = px['close']


def ret(a, b):
    if a is None or b is None or a not in close.index or b not in close.index: return np.nan
    return (close[b] / close[a] - 1) * 100


def off(t, k):
    i = TD.get_loc(t) + k
    return TD[i] if 0 <= i < len(TD) else None


def cum(fl, a, b, who):
    """a 다음 거래일부터 b 까지 합(조원). 자료가 절반 넘게 비면 빈칸."""
    if fl is None or who not in fl: return np.nan
    s = fl[who][(fl.index > a) & (fl.index <= b)]
    n = ((TD > a) & (TD <= b)).sum()
    if n == 0 or s.notna().sum() < max(1, n * 0.5): return np.nan
    return s.sum() / 1e12


def oichg(a, b):
    s = FOI[(FOI.index > a) & (FOI.index <= b)].dropna()
    if len(s) < 2: return np.nan
    nm = FNM.reindex(s.index)
    if nm.nunique() > 1: s = s[nm == nm.iloc[-1]]   # 월물이 바뀌었으면 같은 월물 구간만
    return (s.iloc[-1] / s.iloc[0] - 1) * 100 if len(s) >= 2 and s.iloc[0] > 0 else np.nan


def opc(t, ym):
    try:
        r = OIc.loc[(t, ym)]
        return r['P'] / r['C'] if r['C'] > 0 else np.nan
    except KeyError:
        return np.nan


WIN = {'남은기간': (-10, 0), '만기주간': (-5, 0), '직전2일': (-2, 0), '만기당일': (-1, 0), '다음날': (0, 1), '만기후5일': (0, 5)}
WHO = ['외국인', '기관', '금융투자', '개인']


def build_events(E):
    rows = []
    for kind in ['분기', '월물', '위클리목', '위클리월']:
        ek = E[E['종류'] == kind]['date'].tolist()
        allm = E[E['종류'].isin(['분기', '월물'])]['date'].tolist()
        for i, T in enumerate(ek):
            if kind in ('분기', '월물'):
                prevs = [d for d in allm if d < T]
                start = prevs[-1] if prevs else None          # 직전 월 만기(분기·월물 공통 주기)
                startq = ek[i - 1] if (kind == '분기' and i > 0) else None
                wins = ['남은기간', '만기주간', '만기당일', '다음날', '만기후5일']
                optfl = OPT_M
            else:
                start = ek[i - 1] if i > 0 else None
                startq = None
                wins = ['직전2일', '만기당일', '다음날', '만기후5일']
                optfl = OPT_WT if kind == '위클리목' else OPT_WM
            if start is None: continue
            for w in wins:
                k0, k1 = WIN[w]
                o = off(T, k0); e = off(T, k1)
                if o is None or e is None or e > LAST or o <= start: continue
                r = {'종류': kind, '만기': T, '구간': w, '관측일': o, '수익%': ret(o, e), '누적기간등락%': ret(start, o)}
                for who in WHO:
                    r[f'FUT_{who}'] = cum(FUT, start, o, who)
                    r[f'OPT_{who}'] = cum(optfl, start, o, who)
                    if startq is not None and o > startq: r[f'FUTQ_{who}'] = cum(FUT, startq, o, who)
                r['OI'] = oichg(start, o)
                if kind in ('분기', '월물'): r['OPC'] = opc(o, int(T.strftime('%Y%m')))
                rows.append(r)
    return pd.DataFrame(rows)


def spear(x, y):
    m = x.notna() & y.notna()
    if m.sum() < 8 or x[m].nunique() < 3: return np.nan, np.nan, int(m.sum())
    r, p = stats.spearmanr(x[m], y[m]); return r, p, int(m.sum())


def partial(x, y, z):
    m = x.notna() & y.notna() & z.notna()
    if m.sum() < 10: return np.nan
    rx, ry, rz = (v[m].rank() for v in (x, y, z))
    ex = rx - np.polyval(np.polyfit(rz, rx, 1), rz); ey = ry - np.polyval(np.polyfit(rz, ry, 1), rz)
    return float(np.corrcoef(ex, ey)[0, 1])


def test(d, xcol):
    d = d.dropna(subset=[xcol, '수익%']).sort_values('만기')
    n = len(d)
    out = {'n': n}
    if n < 30:
        out['등급'] = '판정 불가'; return out
    x, y = d[xcol], d['수익%']
    r, p, _ = spear(x, y)
    out.update({'rho': r, 'p': p, '부분rho': partial(x, y, d['누적기간등락%'])})
    lo, hi = x.quantile(1 / 3), x.quantile(2 / 3)
    out['상위1/3평균%'] = y[x >= hi].mean(); out['하위1/3평균%'] = y[x <= lo].mean(); out['전체평균%'] = y.mean()
    out['상위1/3상승비율'] = (y[x >= hi] > 0).mean(); out['하위1/3상승비율'] = (y[x <= lo] > 0).mean()
    h = n // 2
    r1, _, _ = spear(x.iloc[:h], y.iloc[:h]); r2, _, _ = spear(x.iloc[h:], y.iloc[h:])
    out['앞절반rho'] = r1; out['뒤절반rho'] = r2
    k = int(n * 0.4)
    rp, _, _ = spear(x.iloc[:k], y.iloc[:k])
    if pd.notna(rp) and rp != 0:
        ro, po, _ = spear(np.sign(rp) * x.iloc[k:], y.iloc[k:])
        out['선행rho'] = ro; out['선행p'] = po
    out['기간'] = f"{d['만기'].min():%Y-%m}~{d['만기'].max():%Y-%m}"
    return out


def main():
    E = expiry_dates()
    nchk, bad = check_monthly(E)
    print(f'월물 만기 대조 {nchk}개, 불일치 {len(bad)}'); print(bad.to_string() if len(bad) else '')
    E.to_csv(os.path.join(OUT, 'expiry_dates.csv'), index=False, encoding='utf-8')
    ev = build_events(E)
    ev.to_csv(os.path.join(OUT, 'expiry_events.csv'), index=False, encoding='utf-8')
    tests = []
    for (kind, w), d in ev.groupby(['종류', '구간']):
        cols = [c for c in d.columns if c.startswith(('FUT_', 'FUTQ_', 'OPT_'))] + ['OI', 'OPC']
        for c in cols:
            if c not in d or d[c].notna().sum() == 0: continue
            name = c
            tests.append({'종류': kind, '구간': w, '포지션': name, **test(d, c)})
        # 미결제 증감으로 나눈 선물 누적
        for who in WHO:
            c = f'FUT_{who}'
            for tag, m in (('OI↑', d['OI'] > 0), ('OI↓', d['OI'] <= 0)):
                tests.append({'종류': kind, '구간': w, '포지션': f'{c}|{tag}', **test(d[m & d['OI'].notna()], c)})
    T = pd.DataFrame(tests)
    ok = T['p'].notna()
    T.loc[ok, 'q'] = stats.false_discovery_control(T.loc[ok, 'p'].values, method='bh')

    def grade(r):
        if r.get('등급') == '판정 불가' or pd.isna(r['p']): return '판정 불가'
        same = pd.notna(r['앞절반rho']) and pd.notna(r['뒤절반rho']) and np.sign(r['앞절반rho']) == np.sign(r['뒤절반rho']) == np.sign(r['rho'])
        if r['q'] <= 0.10 and same and pd.notna(r.get('선행rho')) and r['선행rho'] > 0 and r['선행p'] < 0.10 and np.sign(r['부분rho']) == np.sign(r['rho']):
            return 'A'
        if r['q'] <= 0.10 and same: return 'B'
        if r['p'] < 0.05: return 'C'
        return '탈락'
    T['등급'] = T.apply(grade, axis=1)
    T = T.sort_values(['등급', 'q'], key=lambda c: c.map({'A': 0, 'B': 1, 'C': 2, '탈락': 3, '판정 불가': 4}) if c.name == '등급' else c)
    T.round(4).to_csv(os.path.join(OUT, 'expiry_tests.csv'), index=False, encoding='utf-8')
    print(len(T), T['등급'].value_counts().to_dict())
    print(T[T['등급'].isin(['A', 'B', 'C'])][['종류', '구간', '포지션', 'n', 'rho', '부분rho', 'q', '선행rho', '앞절반rho', '뒤절반rho',
                                            '상위1/3평균%', '하위1/3평균%', '등급']].round(3).to_string())


if __name__ == '__main__':
    main()
