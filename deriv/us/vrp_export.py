"""「VIX − 실현 변동성(20일) 3년 백분위 상위 20% → 20일 상승」 신호의 날짜를 대시보드용으로 내보낸다(deriv/lab/signals/vrp_signals.csv)
— 2026-11-24 사용자 요청(코스피 대시보드 한눈에 보기 그래프에 세로선으로 표시).

규칙은 갈래 C 라운드 1 의 후보 A11_vrp_상위20%_h20_U 그대로(us_study.py 와 같은 계산, 연구소 통과 기준에는 못 미친 신호):
  조건일 t = 그날까지의 3년 백분위가 0.80 이상(t일 한국 장 마감 뒤 앎) — 앞 거래의 매도일 이후에 난 첫 조건일만(보유 중 난 조건은 건너뜀)
  매수     = t+1 거래일 시가,  매도 = t+20 거래일 종가(매수일 포함 20거래일 보유)
수익률은 코스피 지수 기준(비용 없음). 아직 오지 않은 날짜는 평일로 세어 적고 status 에 '보유 중'·'예정'(휴장 조정 전).
"""
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__)); DERIV = os.path.dirname(ROOT); LAB = os.path.join(DERIV, 'lab')
sys.path.insert(0, LAB)
import lab_common as L  # noqa: E402

RULE = 'VIX − 실현 변동성(20일) 3년 백분위 상위 20% → 다음 날 시가 매수, 20거래일 보유'
TOP, HOLD = 0.80, 20


def main():
    F = pd.read_csv(os.path.join(ROOT, 'out', 'features_kr.csv.gz'), index_col=0, parse_dates=True)
    Q = pd.read_csv(os.path.join(ROOT, 'out', 'features_pct.csv.gz'), index_col=0, parse_dates=True)
    td = L.prices()['K200'].index
    m = ((Q['vrp'] >= TOP) & F['vrp'].notna()).reindex(td).fillna(False).values.astype(bool)
    k = pd.read_csv(os.path.join(DERIV, 'data', 'kospi_long.csv')); k.columns = [c.lstrip('﻿') for c in k.columns]
    k['날짜'] = pd.to_datetime(k['날짜']); k = k.set_index('날짜')
    fday = lambda i: td[i] if i < len(td) else pd.bdate_range(td[-1] + pd.Timedelta(days=1), periods=i - len(td) + 1)[-1]
    rows = []; last = -1
    for i in np.where(m)[0]:
        if td[i] < pd.Timestamp('2010-01-01') or i < last: continue
        b, x = i + 1, i + HOLD; last = x
        c, e, s = td[i], fday(b), fday(x)
        ret = None
        if x < len(td) and e in k.index and s in k.index: ret = round((k['종가'].loc[s] / k['시가'].loc[e] - 1) * 100, 2)
        status = '끝남' if x < len(td) else ('보유 중' if b < len(td) else '예정')
        rows.append({'cond': c.date(), 'buy': e.date(), 'sell': s.date(), 'status': status, 'ret_pct': ret, 'vrp': round(float(F['vrp'].reindex(td).iloc[i]), 2), 'pct': round(float(Q['vrp'].reindex(td).iloc[i]), 3), 'rule': RULE})
    out = pd.DataFrame(rows)
    q = Q['vrp'].reindex(td).dropna()
    os.makedirs(os.path.join(LAB, 'signals'), exist_ok=True)
    out.to_csv(os.path.join(LAB, 'signals', 'vrp_signals.csv'), index=False, encoding='utf-8')
    d = out[out['status'] == '끝남']
    print('신호', len(out), '끝남', len(d), '수익', int((d['ret_pct'] > 0).sum()), '합계', round(float(d['ret_pct'].sum()), 1), '자료 끝', td[-1].date(),
          '지금 백분위', None if not len(q) else (str(q.index[-1].date()), round(float(q.iloc[-1]), 3)), '진행', out[out['status'] != '끝남'][['cond', 'buy', 'sell', 'status']].to_dict('records'))


if __name__ == '__main__':
    main()
