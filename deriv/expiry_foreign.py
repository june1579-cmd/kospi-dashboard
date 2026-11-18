"""외국인만: 만기까지 쌓은 선물·옵션(·현물) 방향 → 만기 전후 코스피. 조합마다 따로 검증(외국인만으로 다중 검정 가족을 좁혀 검정력을 높임).

expiry_study.py 의 만기일·구간·검증 규칙을 그대로 쓰고, 외국인 지표를 늘렸다.
  FUT/FUTz    직전 같은 종류 만기 뒤 선물 순매수 누적(조원) / 표준화(누적 ÷ (직전 250일 하루 순매수 표준편차 × √일수)) — 지수 수준·시장 규모 변화 보정
  FUTQ/FUTQz  분기 만기만: 직전 분기 만기 뒤 3개월 누적
  FUT5z       관측일 전 5거래일 누적(막판에 쌓은 방향), 표준화
  OPT/OPTz    옵션 콜 순매수 − 풋 순매수 누적(프리미엄), 표준화
  CASH/CASHz  코스피 현물 순매수 누적(조원), 표준화
  FC          선물 + 현물 누적(조원)
  AGREE       선물·옵션 방향이 같으면 ±1(둘 다 매수 쪽 +1, 둘 다 매도 쪽 −1), 엇갈리면 0
  DAYz        만기일 당일 선물 순매수(표준화) — 다음날·만기후5일 구간만
  FUTz|OI↑ / FUTz|OI↓  선물 미결제가 늘어난 주기 / 줄어든 주기
출력: deriv/out/expiry_foreign_tests.csv, expiry_foreign_events.csv
"""
import os
import sys

import numpy as np
import pandas as pd
from scipy import stats

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
import analyze as A  # noqa: E402
import expiry_study as S  # noqa: E402

OUT = S.OUT
TD = S.TD

# 외국인 현물(코스피) 순매수: analyze.py 와 같은 방식(history + 확정 수집본 우선)
cash = pd.read_csv(os.path.join(A.REPO, 'pkg', 'history', '01_코스피_투자자별_순매수_거래대금.csv')).rename(columns={'날짜': 'date'})
cash['date'] = A.ddate(cash['date']); CF = A.num(cash.set_index('date')['외국인합계'])
cl = A.collect_latest('03_코스피_투자자별_순매수_거래대금.csv')
if cl is not None:
    cl['date'] = A.ddate(cl['날짜']); f2 = cl.set_index('date'); f2 = f2[~f2.index.duplicated(keep='last')]
    add = A.num(f2['외국인']) + A.num(f2['기타외국인']) if '기타외국인' in f2 else A.num(f2['외국인'])
    CF = pd.concat([add, CF[~CF.index.isin(add.index)]])
CF = CF[~CF.index.duplicated(keep='first')].sort_index()

F = {'FUT': S.FUT['외국인'], 'OPT_M': S.OPT_M['외국인'], 'CASH': CF,
     'OPT_WT': S.OPT_WT['외국인'] if S.OPT_WT is not None else None, 'OPT_WM': S.OPT_WM['외국인'] if S.OPT_WM is not None else None}
SD = {k: (v.rolling(250, min_periods=120).std().shift(1) if v is not None else None) for k, v in F.items()}   # 관측일 전까지의 하루 표준편차


def csum(key, a, b):
    s = F[key]
    if s is None: return np.nan
    x = s[(s.index > a) & (s.index <= b)]
    n = ((TD > a) & (TD <= b)).sum()
    if n == 0 or x.notna().sum() < max(1, n * 0.5): return np.nan
    return x.sum() / 1e12


def zsum(key, a, b):
    s = F[key]
    if s is None: return np.nan
    x = s[(s.index > a) & (s.index <= b)]
    n = ((TD > a) & (TD <= b)).sum()
    if n == 0 or x.notna().sum() < max(1, n * 0.5): return np.nan
    sd = SD[key].reindex([b]).iloc[0] if b in SD[key].index else np.nan
    if pd.isna(sd) or sd == 0: return np.nan
    return x.sum() / (sd * np.sqrt(n))


def build(E):
    rows = []
    allm = E[E['종류'].isin(['분기', '월물'])]['date'].tolist()
    for kind in ['분기', '월물', '위클리목', '위클리월']:
        ek = E[E['종류'] == kind]['date'].tolist()
        for i, T in enumerate(ek):
            if kind in ('분기', '월물'):
                prevs = [d for d in allm if d < T]; start = prevs[-1] if prevs else None
                startq = ek[i - 1] if (kind == '분기' and i > 0) else None
                wins = ['남은기간', '만기주간', '만기당일', '다음날', '만기후5일']; ok = 'OPT_M'
            else:
                start = ek[i - 1] if i > 0 else None; startq = None
                wins = ['직전2일', '만기당일', '다음날', '만기후5일']; ok = 'OPT_WT' if kind == '위클리목' else 'OPT_WM'
            if start is None: continue
            for w in wins:
                k0, k1 = S.WIN[w]
                o = S.off(T, k0); e = S.off(T, k1)
                if o is None or e is None or e > S.LAST or o <= start: continue
                r = {'종류': kind, '만기': T, '구간': w, '관측일': o, '수익%': S.ret(o, e), '누적기간등락%': S.ret(start, o)}
                r['FUT'] = csum('FUT', start, o); r['FUTz'] = zsum('FUT', start, o)
                o5 = S.off(o, -5)
                if o5 is not None: r['FUT5z'] = zsum('FUT', o5, o)
                r['OPT'] = csum(ok, start, o); r['OPTz'] = zsum(ok, start, o)
                r['CASH'] = csum('CASH', start, o); r['CASHz'] = zsum('CASH', start, o)
                r['FC'] = r['FUT'] + r['CASH'] if pd.notna(r['FUT']) and pd.notna(r['CASH']) else np.nan
                if pd.notna(r['FUT']) and pd.notna(r['OPT']):
                    r['AGREE'] = 1 if (r['FUT'] > 0 and r['OPT'] > 0) else (-1 if (r['FUT'] < 0 and r['OPT'] < 0) else 0)
                if startq is not None and o > startq:
                    r['FUTQ'] = csum('FUT', startq, o); r['FUTQz'] = zsum('FUT', startq, o)
                if w in ('다음날', '만기후5일'):
                    r['DAYz'] = zsum('FUT', S.off(T, -1), T)
                r['OI'] = S.oichg(start, o)
                rows.append(r)
    return pd.DataFrame(rows)


def main():
    E = S.expiry_dates()
    ev = build(E)
    ev.to_csv(os.path.join(OUT, 'expiry_foreign_events.csv'), index=False, encoding='utf-8')
    MEAS = ['FUT', 'FUTz', 'FUT5z', 'FUTQ', 'FUTQz', 'OPT', 'OPTz', 'CASH', 'CASHz', 'FC', 'AGREE', 'DAYz']
    pool = ev.copy(); pool['종류'] = pool['종류'].map({'분기': '월간전체(분기+월물)', '월물': '월간전체(분기+월물)', '위클리목': '위클리전체(목+월)', '위클리월': '위클리전체(목+월)'})
    pool = pool.drop(columns=['FUTQ', 'FUTQz'], errors='ignore')
    evp = pd.concat([ev, pool], ignore_index=True)
    # 극단(표준화 선물 누적 상·하위 10%) — 서술용
    ext = []
    for (kind, w), d in evp.groupby(['종류', '구간']):
        m = d.dropna(subset=['FUTz', '수익%'])
        if len(m) < 40: continue
        hi, lo = m['FUTz'].quantile(0.9), m['FUTz'].quantile(0.1)
        a, b = m[m['FUTz'] >= hi]['수익%'], m[m['FUTz'] <= lo]['수익%']
        ext.append({'종류': kind, '구간': w, 'n': len(m), '상위10%n': len(a), '상위10%평균%': a.mean(), '상위10%상승비율': (a > 0).mean(),
                    '하위10%평균%': b.mean(), '하위10%상승비율': (b > 0).mean(), '전체평균%': m['수익%'].mean(), 'p(상위vs하위)': stats.ttest_ind(a, b, equal_var=False).pvalue})
    X = pd.DataFrame(ext); X.round(4).to_csv(os.path.join(OUT, 'expiry_foreign_extremes.csv'), index=False, encoding='utf-8')
    print(X.round(3).to_string())
    tests = []
    for (kind, w), d in evp.groupby(['종류', '구간']):
        for c in MEAS:
            if c not in d or d[c].notna().sum() == 0: continue
            t = S.test(d, c)
            m = d.dropna(subset=[c, '수익%'])
            if len(m) and m[c].nunique() > 1:
                t['방향일치율'] = float((np.sign(m[c]) == np.sign(m['수익%'])).mean())
            tests.append({'종류': kind, '구간': w, '포지션': c, **t})
        for tag, mm in (('OI↑', d['OI'] > 0), ('OI↓', d['OI'] <= 0)):
            tests.append({'종류': kind, '구간': w, '포지션': f'FUTz|{tag}', **S.test(d[mm & d['OI'].notna()], 'FUTz')})
    T = pd.DataFrame(tests)
    ok = T['p'].notna()
    T.loc[ok, 'q'] = stats.false_discovery_control(T.loc[ok, 'p'].values, method='bh')

    def grade(r):
        if pd.isna(r.get('p')): return '판정 불가'
        same = pd.notna(r['앞절반rho']) and pd.notna(r['뒤절반rho']) and np.sign(r['앞절반rho']) == np.sign(r['뒤절반rho']) == np.sign(r['rho'])
        if r['q'] <= 0.10 and same and pd.notna(r.get('선행rho')) and r['선행rho'] > 0 and r['선행p'] < 0.10 and np.sign(r['부분rho']) == np.sign(r['rho']):
            return 'A'
        if r['q'] <= 0.10 and same: return 'B'
        if r['p'] < 0.05: return 'C'
        return '탈락'
    T['등급'] = T.apply(grade, axis=1)
    T = T.sort_values(['등급', 'q'], key=lambda c: c.map({'A': 0, 'B': 1, 'C': 2, '탈락': 3, '판정 불가': 4}) if c.name == '등급' else c)
    T.round(4).to_csv(os.path.join(OUT, 'expiry_foreign_tests.csv'), index=False, encoding='utf-8')
    print(len(T), int(ok.sum()), T['등급'].value_counts().to_dict())
    cols = ['종류', '구간', '포지션', 'n', 'rho', 'p', 'q', '부분rho', '선행rho', '선행p', '앞절반rho', '뒤절반rho', '상위1/3평균%', '하위1/3평균%', '전체평균%', '상위1/3상승비율', '하위1/3상승비율', '방향일치율']
    print(T[T['등급'].isin(['A', 'B', 'C'])][cols].round(3).to_string())


if __name__ == '__main__':
    main()
