"""선물·옵션 수급 대시보드용 자료 만들기 — deriv/out 결과 → deriv/dash/*.csv
analyze.py 를 돌린 뒤 실행. 대시보드(claude.ai Data)의 첨부 파일로 올린다.
"""
import json
import os

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, 'out')
DASH = os.path.join(ROOT, 'dash')
os.makedirs(DASH, exist_ok=True)
sys_path = os.path.join(ROOT)
import sys  # noqa: E402
sys.path.insert(0, ROOT)
from analyze import load_price  # noqa: E402

X = pd.read_csv(os.path.join(OUT, 'indicators_daily.csv.gz'), index_col=0, parse_dates=True)
px = load_price()

# 1) 최신 값 카드
CARDS = [('F_외국인_1d', '외국인 선물 순매수(당일)', '조원', 3), ('F_외국인_5d', '외국인 선물 순매수(5일 합계)', '조원', 3),
         ('N1_야간등락', '야간 선물 등락', '%', 2), ('B1_시장베이시스율', '시장 베이시스율', '%', 2),
         ('V1_대표IV', '옵션 대표 내재변동성', '%', 1), ('V1_VKOSPI', 'VKOSPI', 'pt', 2), ('R1_PCR_5d', '풋콜비율(5일 평균)', '배', 2),
         ('P1_차익_1d', '프로그램 차익 순매수', '조원', 3), ('P1_비차익_1d', '프로그램 비차익 순매수', '조원', 3),
         ('K2_코스닥150선물_외국인_5d', '코스닥150 선물 외국인(5일 합계)', '십억원', 0), ('K2_10년국채선물_외국인_5d', '10년 국채선물 외국인(5일 합계)', '십억원', 0),
         ('K2_달러선물_외국인_5d', '달러선물 외국인(5일 합계)', '십억원', 0),
         ('W_S&P선물_등락', '미국 S&P500 선물 등락(밤사이)', '%', 2), ('W_반도체_등락', '필라델피아 반도체 등락', '%', 2), ('W_VIX_변화', 'VIX 변화', 'pt', 2)]
rows = []
for code, name, unit, nd in CARDS:
    if code not in X: continue
    s = X[code].dropna()
    if not len(s): continue
    hist = s[s.index >= s.index[-1] - pd.Timedelta(days=400)].tail(250)
    pct = float((hist <= s.iloc[-1]).mean() * 100)
    rows.append({'지표': name, '코드': code, '값': round(float(s.iloc[-1]), nd), '단위': unit, '기준일': s.index[-1].strftime('%Y-%m-%d'),
                 '전일값': round(float(s.iloc[-2]), nd) if len(s) > 1 else None, '1년백분위': round(pct)})
pd.DataFrame(rows).to_csv(os.path.join(DASH, 'latest.csv'), index=False, encoding='utf-8')

# 2) 최근 250거래일 흐름
keep = ['F_외국인_1d', 'F_외국인_5d', 'B1_시장베이시스율', 'V1_대표IV', 'R1_PCR_5d', 'N1_야간등락']
R = X[[c for c in keep if c in X]].copy()
R['kospi'] = px['close']; R['kospi_open_next'] = px['open'].shift(-1)
R['gap_next_pct'] = (px['open'].shift(-1) / px['close'] - 1) * 100
R = R.dropna(subset=['kospi']).tail(250)
R.index.name = 'date'; R = R.reset_index(); R['date'] = R['date'].dt.strftime('%Y-%m-%d')
R.round(4).to_csv(os.path.join(DASH, 'recent.csv'), index=False, encoding='utf-8')

# 3) 검증 결과(등급 있는 것 + 짧은 표본 참고)
S = pd.read_csv(os.path.join(OUT, 'backtest_summary.csv'))
TN = {'gap': '다음 날 시가 갭', 'dir': '다음 날 종가 방향', 'oc': '다음 날 시가→종가', 'wk': '5일 수익률', 'crash': '5일 안 급락', 'bottom': '저점'}
G = S[S['등급'].isin(['A', 'B', 'C', '동시성'])].copy()
G['대상명'] = G['대상'].map(TN)
G = G[['대상명', '지표', '방향', '평균IC(방향맞춤)', '기준선제외IC', '상위평균', '하위평균', '기본값', 'q_BH', '등급']].rename(
    columns={'대상명': '대상', '평균IC(방향맞춤)': 'IC', '기준선제외IC': '증분IC', 'q_BH': 'q'})
order = {'A': 0, 'B': 1, '동시성': 2, 'C': 3}
G = G.sort_values(['등급', 'q'], key=lambda c: c.map(order) if c.name == '등급' else c)
G['순번'] = range(1, len(G) + 1)
prob = G['대상'].isin(['다음 날 종가 방향', '5일 안 급락', '저점'])
fmt = lambda v, p: (f"{v * 100:.1f}%" if p else f"{v * 100:+.2f}%") if pd.notna(v) else ''
for a, b in (('상위평균', '상위'), ('하위평균', '하위'), ('기본값', '평소')):
    G[b] = [fmt(v, p) for v, p in zip(G[a], prob)]
G['단계'] = G['지표'].map(lambda c: '3차 해외' if c.startswith('W_') else ('2차 국내' if c.startswith('K2_') else '1차 국내'))
G['IC'] = G['IC'].round(3); G['증분IC'] = G['증분IC'].round(3); G['q'] = G['q'].round(3)
G = G.drop(columns=['상위평균', '하위평균', '기본값'])
G.round(4).to_csv(os.path.join(DASH, 'results.csv'), index=False, encoding='utf-8')
cnt = S['등급'].value_counts().reindex(['A', 'B', 'C', '동시성', '탈락', '판정 불가']).fillna(0).astype(int)
pd.DataFrame({'등급': cnt.index, '개수': cnt.values}).to_csv(os.path.join(DASH, 'grades.csv'), index=False, encoding='utf-8')

# 4) 사건 전후
E = pd.read_csv(os.path.join(OUT, 'event_study.csv'))
E = E[['날짜', '사건', '코스피_당일%', '코스피_후5일%', 'F_외국인_1d_당일', 'F2_현선합계_5d_전5일평균', 'B1_시장베이시스율_당일', 'V1_VKOSPI_당일']].rename(
    columns={'코스피_당일%': '코스피당일', '코스피_후5일%': '코스피후5일', 'F_외국인_1d_당일': '외국인선물당일', 'F2_현선합계_5d_전5일평균': '외국인현선5일', 'B1_시장베이시스율_당일': '베이시스율', 'V1_VKOSPI_당일': 'VKOSPI'})
E.to_csv(os.path.join(DASH, 'events.csv'), index=False, encoding='utf-8')

# 5) 야간 선물 → 다음 날 시가 갭(2025-06~)
N = X[['N1_야간등락']].join((px['open'].shift(-1) / px['close'] - 1).rename('gap') * 100).dropna()
N.index.name = 'date'; N = N.reset_index(); N['date'] = N['date'].dt.strftime('%Y-%m-%d')
N.round(3).to_csv(os.path.join(DASH, 'night_gap.csv'), index=False, encoding='utf-8')
print('ok', len(rows), len(R), len(G), len(E), len(N))
