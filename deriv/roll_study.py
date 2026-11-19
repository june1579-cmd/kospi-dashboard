"""선물 롤오버(근월물 → 차월물 이월) 지표 → 분기 만기 전후 코스피 — 조합마다 따로 검증.

자료: deriv/data/fut_roll_daily.csv.gz (collect.py roll1·roll2·roll3, 분기 만기 앞 15 ~ 뒤 2거래일, 코스피200 선물 전 월물 일별).
만기 규칙·거래일·수익률·검증 함수(test)·등급(grade)·BH 보정은 expiry_study.py 를 그대로 가져다 쓴다.
  분기 만기 T = 3·6·9·12월 둘째 목요일(휴장이면 앞 거래일).
근월물·차월물: 그날 상장된 월물을 ym 으로 정렬해 가장 가까운 두 결제월. 월물이 2개 미만인 날은 빈칸.
가격: 정산가 우선, 없으면 종가.
관측일: T-5, T-1, T. 지표(관측일 o 기준):
  이월률        = 차월물 미결제 ÷ (근월물 + 차월물 미결제)
  이월률차      = 이월률 − 직전 4개 분기 같은 관측일 이월률 평균 (음수 = 이월 부진, 양수 = 과열)
  스프레드%     = (차월물 − 근월물 가격) ÷ 코스피200 × 100
  스프레드차    = 스프레드% − 직전 4개 분기 같은 관측일 평균  (금리·배당 자료가 없어 이론 스프레드 대신 씀)
  스프레드전년차 = 스프레드% − 1년 전 같은 분기 같은 관측일  (보조: 배당 계절성 통제)
  근월물OI변화% = T-5 대비 관측일 근월물 미결제 변화율 (T-5 에서는 정의상 0이라 T-1·T 만)
  합계OI변화%   = T-5 대비 관측일 근+차 미결제 합계 변화율 (포지션 순증감)
  차월물거래비중 = 차월물 ÷ (근+차) 거래량
  T(만기일)에는 KRX 가 만기 월물 미결제를 0 으로 내므로(2008-03~2009-03 5번은 값이 있어 0 으로 맞춤) 이월률·이월률차·근월물OI변화% 는 빈칸
  (정의상 100%·−100%), 합계OI변화% 는 T-5 근+차 대비 만기일 차월물(새 근월물) 미결제 = 최종 이월 규모.
  T 의 스프레드는 새 근월물 − 만기 월물 최종결제가라 사실상 새 근월물 베이시스다.
구간(관측일 종가 → 끝 종가, 코스피): 만기주간 T-5→T, 만기당일 T-1→T, 다음날 T→T+1, 만기후5일 T→T+5, 만기후20일 T→T+20.
  구간 시작이 관측일과 같거나 뒤인 것만 짝짓는다(미래를 보지 않음).
검증: expiry_study.test (n<30 판정 불가, 스피어만 ρ·부분 ρ(직전 분기 만기→관측일 코스피 등락 통제)·상하위 1/3·앞뒤 절반·선행 시험),
  전체 조합 BH 보정 q, expiry_study.grade 로 A/B/C/탈락/판정 불가.
출력: deriv/out/roll_tests.csv, roll_events.csv
"""
import os
import sys

import numpy as np
import pandas as pd
from scipy import stats

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
import expiry_study as X  # noqa: E402  (만기 규칙·구간·검증·등급 기준을 그대로 씀)

OUT = X.OUT
DATA = os.path.join(ROOT, 'data')
OBS = {'T-5': -5, 'T-1': -1, 'T': 0}
WIN = {'만기주간': (-5, 0), '만기당일': (-1, 0), '다음날': (0, 1), '만기후5일': (0, 5), '만기후20일': (0, 20)}
IND = ['이월률', '이월률차', '스프레드%', '스프레드차', '스프레드전년차', '근월물OI변화%', '합계OI변화%', '차월물거래비중']


def load_roll():
    d = pd.read_csv(os.path.join(DATA, 'fut_roll_daily.csv.gz'), dtype={'ISU_CD': str})
    d['날짜'] = pd.to_datetime(d['날짜'])
    d = d.drop_duplicates(['날짜', 'ISU_CD'])
    d['ym'] = pd.to_numeric(d['ym'], errors='coerce')
    d = d[d['ym'].notna() & (d['ym'] % 100).isin([3, 6, 9, 12])]
    d['px'] = d['settle'].where(d['settle'].notna() & (d['settle'] > 0), d['close'])
    return d


def near_next(R, day):
    """그날 근월물·차월물 한 줄씩(없으면 None)."""
    g = R[R['날짜'] == day].sort_values('ym')
    if len(g) < 2: return None
    return g.iloc[0], g.iloc[1]


def snapshot(R, T):
    """만기 T 의 관측일별 원지표."""
    out = {}
    nn5 = None
    o5 = X.off(T, -5)
    if o5 is not None: nn5 = near_next(R, o5)
    for tag, k in OBS.items():
        o = X.off(T, k)
        r = {'관측일': o}
        nn = near_next(R, o) if o is not None else None
        if nn is None:
            out[tag] = r; continue
        a, b = nn
        r['근월물'] = int(a['ym']); r['차월물'] = int(b['ym'])
        r['근월물OI'] = a['oi']; r['차월물OI'] = b['oi']; r['근월물가'] = a['px']; r['차월물가'] = b['px']; r['코스피200'] = a['spot']
        r['근월물만기월'] = int(a['ym']) == int(T.strftime('%Y%m'))
        aoi = a['oi']
        if k == 0 and r['근월물만기월']: aoi = 0      # 만기일: 만기 월물은 현금결제로 소멸(2008-03~2009-03 5번은 KRX 가 0 대신 값을 내므로 0 으로 맞춤)
        tot = aoi + b['oi']
        if k < 0 and tot > 0: r['이월률'] = b['oi'] / tot
        if pd.notna(a['px']) and pd.notna(b['px']) and a['spot'] > 0: r['스프레드%'] = (b['px'] - a['px']) / a['spot'] * 100
        vt = a['vol'] + b['vol']
        if vt > 0: r['차월물거래비중'] = b['vol'] / vt
        if k > -5 and nn5 is not None and int(nn5[0]['ym']) == int(a['ym']):     # 같은 근·차월물끼리 비교
            a5, b5 = nn5
            if k < 0 and a5['oi'] > 0: r['근월물OI변화%'] = (a['oi'] / a5['oi'] - 1) * 100
            t5 = a5['oi'] + b5['oi']
            if t5 > 0: r['합계OI변화%'] = (tot / t5 - 1) * 100
        out[tag] = r
    return out


def build_events(Q, R):
    snaps = {T: snapshot(R, T) for T in Q}
    base = []
    for i, T in enumerate(Q):
        for tag in OBS:
            r = {'만기': T, '관측': tag, **snaps[T][tag]}
            prev4 = [snaps[t][tag] for t in Q[max(0, i - 4):i]] if i >= 4 else []
            for c, dc in (('이월률', '이월률차'), ('스프레드%', '스프레드차')):
                v = [p.get(c) for p in prev4]
                if len(v) == 4 and all(pd.notna(x) for x in v) and pd.notna(r.get(c)): r[dc] = r[c] - float(np.mean(v))
            if i >= 4:
                py = snaps[Q[i - 4]][tag].get('스프레드%')
                if pd.notna(py) and pd.notna(r.get('스프레드%')): r['스프레드전년차'] = r['스프레드%'] - py
            base.append(r)
    B = pd.DataFrame(base)
    rows = []
    for _, b in B.iterrows():
        T = b['만기']; k = OBS[b['관측']]; o = b['관측일']
        if pd.isna(o): continue
        i = Q.index(T)
        start = Q[i - 1] if i > 0 else None
        for w, (k0, k1) in WIN.items():
            if k0 < k: continue                       # 관측일보다 앞에서 시작하는 구간은 짝짓지 않음
            s = X.off(T, k0); e = X.off(T, k1)
            if s is None or e is None or e > X.LAST: continue
            r = b.to_dict(); r['구간'] = w; r['수익%'] = X.ret(s, e)
            r['누적기간등락%'] = X.ret(start, o) if start is not None else np.nan
            rows.append(r)
    return B, pd.DataFrame(rows)


def main():
    E = X.expiry_dates()
    Q = sorted(E[E['종류'] == '분기']['date'].tolist())
    R = load_roll()
    B, ev = build_events(Q, R)
    cols = ['만기', '관측', '관측일', '구간', '수익%', '누적기간등락%'] + IND + ['근월물', '차월물', '근월물만기월', '근월물OI', '차월물OI', '근월물가', '차월물가', '코스피200']
    ev = ev[[c for c in cols if c in ev]]
    ev.to_csv(os.path.join(OUT, 'roll_events.csv'), index=False, encoding='utf-8')
    tests = []
    for (tag, w), d in ev.groupby(['관측', '구간'], sort=False):
        for c in IND:
            if c not in d or d[c].notna().sum() == 0: continue
            tests.append({'관측': tag, '구간': w, '지표': c, **X.test(d, c)})
    T = pd.DataFrame(tests)
    ok = T['p'].notna()
    T.loc[ok, 'q'] = stats.false_discovery_control(T.loc[ok, 'p'].values, method='bh')
    T['등급'] = T.apply(X.grade, axis=1)
    order = {'A': 0, 'B': 1, 'C': 2, '탈락': 3, '판정 불가': 4}
    T = T.sort_values(['등급', 'p'], key=lambda c: c.map(order) if c.name == '등급' else c)
    T.round(4).to_csv(os.path.join(OUT, 'roll_tests.csv'), index=False, encoding='utf-8')
    # 요약 출력
    print(f'분기 만기 {len(Q)}개: {Q[0]:%Y-%m-%d} ~ {Q[-1]:%Y-%m-%d}')
    for tag in OBS:
        b = B[B['관측'] == tag]
        print(tag, '근·차월물 있음', b['근월물'].notna().sum(), '· 근월물=만기월', int(b['근월물만기월'].fillna(False).sum()),
              '·', {c: int(b[c].notna().sum()) for c in IND if c in b})
    print(len(T), T['등급'].value_counts().to_dict())
    show = ['관측', '구간', '지표', 'n', 'rho', 'p', 'q', '부분rho', '앞절반rho', '뒤절반rho', '선행rho', '선행p', '상위1/3평균%', '하위1/3평균%', '등급']
    print(T[show].round(3).head(25).to_string())


if __name__ == '__main__':
    main()
