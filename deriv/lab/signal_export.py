"""통과 신호의 날짜를 대시보드용으로 내보낸다(deriv/lab/signals/passed_signals.csv) — 2026-11-22 사용자 요청(코스피 대시보드 한눈에 보기 그래프 표시).

규칙은 통과한 날 그대로 고정(갈래 B 라운드 30, id A4zc_Q_1.5_벽 물량 5일 증가 + 하루 늦춰 진입 + 첫 신호만(5일)_m3):
  조건일 t  = 분기물(Q) 콜벽이 지수 위 0~1.5% 안 + 그 벽 미결제 5일 변화 > 0 (t일 장 마감 뒤 앎), 직전 5거래일 안에 같은 조건이 없던 첫날만
  건너뜀    = t+1 거래일
  매수      = t+2 거래일 시가
  매도      = t+4 거래일 종가(매수일 포함 3거래일 보유)
라운드 설정(round*.json)과 무관하게 A2 지표(work/lab_feat.pkl)에서 직접 계산한다. 아직 오지 않은 날짜는 평일로 세어 적고 status 에 '예정'(휴장 조정 전).
"""
import os
import pickle
import sys

import numpy as np
import pandas as pd

LAB = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, LAB)
import lab_common as L  # noqa: E402

RULE = '분기물 콜벽 아래 1.5% 안 + 벽 물량 5일 증가 → 하루 쉬고 매수, 3거래일 보유'
BAND, FIRST_N, HOLD = 1.5, 5, 3


def main():
    feat = pickle.load(open(os.path.join(LAB, 'work', 'lab_feat.pkl'), 'rb'))
    k2 = L.k200_index(); td = k2.index
    X = feat['wide'].reindex(td) if 'wide' in feat else feat['X'].reindex(td)
    dist, oi5 = X['OW_Q_wall_dist%'], X['OW_Q_wall_oi_chg5%']
    m = ((dist > 0) & (dist <= BAND) & (oi5 > 0)).fillna(False).values
    idx = np.where(m)[0]
    idx = idx[np.r_[True, np.diff(idx) > FIRST_N]] if len(idx) else idx      # 직전 5거래일 안 같은 조건 없는 첫날(연구소 정의와 같음: 늦춘 날짜 기준 간격 = 조건일 기준 간격)
    fut = L.prices()['K200F']
    fday = lambda i: td[i] if i < len(td) else (pd.bdate_range(td[-1] + pd.Timedelta(days=1), periods=i - len(td) + 1)[-1])
    rows = []
    for i in idx:
        c, s, e, x = fday(i), fday(i + 1), fday(i + 2), fday(i + 1 + HOLD)
        known_e, known_x = i + 2 < len(td), i + 1 + HOLD < len(td)
        ret = None
        if known_x and e in fut.index and x in fut.index:
            ret = round((fut['close'].loc[x] / fut['open'].loc[e] - 1) * 100, 2)
        status = '끝남' if known_x else ('보유 중' if known_e else '예정')
        rows.append({'cond': c.date(), 'skip': s.date(), 'buy': e.date(), 'sell': x.date(), 'status': status, 'ret_pct': ret,
                     'k200_cond': round(float(k2['close'].loc[c]), 2), 'wall_dist_pct': round(float(dist.loc[c]), 2), 'rule': RULE})
    out = pd.DataFrame(rows)
    os.makedirs(os.path.join(LAB, 'signals'), exist_ok=True)
    out.to_csv(os.path.join(LAB, 'signals', 'passed_signals.csv'), index=False, encoding='utf-8')
    d = out[out['status'] == '끝남']
    print('신호', len(out), '끝남', len(d), '맞음', int((d['ret_pct'] > 0).sum()), '자료 끝', td[-1].date(), '진행', out[out['status'] != '끝남'][['cond', 'buy', 'sell', 'status']].to_dict('records'))


if __name__ == '__main__':
    main()
