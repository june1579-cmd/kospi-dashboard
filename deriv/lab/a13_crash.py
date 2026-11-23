"""A13 하락·급락 에이전트(2026-11-23, 갈래 D 총괄이 추가) — 인버스(하락 방향)로 쓸 신호만 만든다(direction −1).

왜: 갈래 D 라운드 1 에서 하락 후보 703개 중 앞·뒤 어느 구간에서도 선별된 것이 0개 — 기존 가족(벽 막 넘음 + 외국인 매도 등)은 하락 적중이
    기본 확률(약 47~49%)과 같았다. 가설 뒷부분('콜벽 위로 올린 뒤 외국인 매도')을 '돌파 실패'로, 그리고 풋 쪽·급락 전 징후를 새로 본다.
가족(모두 t일 장 마감 뒤 아는 값, 문턱은 미리 정한 값 또는 그 시점까지 3년 백분위 — 어느 구간 성적도 보고 정하지 않음):
  xfail  콜벽 돌파 실패: 종가가 전날 콜벽(F0·Q, 같은 결제월) 위로 올라선 날부터 10거래일 안에 종가가 그 벽 아래로 되돌아온 첫날
         (+ 외국인 선물 3일 누적 순매도 / + 선물·현물 3일 동시 순매도).
  xpost  콜벽 돌파 뒤 외국인 매도: 돌파 뒤 1~5거래일 안에 외국인 선물 순매도가 3년 백분위 하위 20% 인 첫날.
  pbrk   풋 쪽 이탈: 종가가 전날 풋 무게중심(현재가 ±15% 풋 미결제 가중 평균 행사가, F0·Q) 아래로 내려간 첫날(직전 5일 없음), 풋벽(최대 풋 미결제) 이탈.
  poi    풋 물량 급증: 살아 있는 월물 풋 미결제 합 5일 변화 백분위 상위 10%, 풋/콜 미결제 비 5일 변화 상위 10%, 풋/콜 거래량 비(PCR) 상위 5%.
  pre    급락 전 징후: 외국인 선물·현물 동시 순매도(1·3·5일 합 모두 3년 백분위 하위 10%), 베이시스(근월물 시장 베이시스 ÷ 지수) 하위 10%,
         시장−이론 베이시스 괴리 하위 10%, 대표 IV 5일 상승 상위 10%, 풋−콜 평균 IV 차 상위 10%, 외국인 풋 3일 순매수 상위 10% + 선물 매도, 그리고 이들 2개 겹침.
  gap·gap2·gap3(라운드 3~5) 밤사이 미국 급등 뒤 갭 되밀림(1일), gap3 = 넓힌 기반 × 콜벽·외국인·IV·베이시스 거르개.
  장세 겹침: 그대로 / 하락 추세(R3) / 60일 고점 −5% 조정 중(R8) / 5일 급등 뒤(R7) / 60일 고점 1% 안(R9) — '올린 뒤 매도'는 R7·R9 쪽.
대상: 코스피200 선물 다음 날 시가 → 1·2·3·5·10·20일 뒤 종가 하락, 큰 변동 창 5·10·20일(±1σ√W 중 아래쪽 먼저).
자료 없는 날은 빈칸(추정으로 채우지 않음). 판정은 A8·A10.
"""
import os
import pickle
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lab_common as L  # noqa: E402

AG = 'a13'
HS = [1, 2, 3, 5, 10, 20]
BARRIER = [5, 10, 20]
BK = 1.0
MIN_SIG = 12
CROSS_WIN = 10


def pct_rank(s, win=756, minp=252):
    """그 시점까지(오늘 포함) 3년 창에서 오늘 값의 백분위. 빈칸은 빼고 계산한 뒤 원래 날짜로 되돌림."""
    x = s.dropna()
    r = x.rolling(win, min_periods=minp).apply(lambda a: (a[:-1] <= a[-1]).mean() if len(a) > 1 else np.nan, raw=True)
    return r.reindex(s.index)


def first_day(mask, gap=5):
    m = mask.fillna(False).astype(bool)
    prev = m.shift(1).rolling(gap, min_periods=1).max().fillna(0).astype(bool)
    return m & ~prev


def num(s):
    return pd.to_numeric(s.astype(str).str.replace(',', ''), errors='coerce')


def basis_front():
    b = pd.read_csv(os.path.join(L.DATA, 'basis_daily.csv.gz'), dtype=str)
    b['date'] = pd.to_datetime(b['TRD_DD'], format='%Y/%m/%d', errors='coerce')
    b['ym'] = b['ISU_NM'].str.extract(r'(\d{6})\s*$')[0]
    for c in ('TDD_CLSPRC', 'SPOT_PRC', 'MKT_BASIS', 'THRY_BASIS'): b[c] = num(b[c])
    b = b[(b['TDD_CLSPRC'] > 0) & (b['SPOT_PRC'] > 0) & b['ym'].notna() & b['date'].notna()]
    b = b[b['ym'] >= b['date'].dt.strftime('%Y%m')].sort_values(['date', 'ym'], kind='stable')
    f = b.groupby('date').first()
    return pd.DataFrame({'bp': f['MKT_BASIS'] / f['SPOT_PRC'] * 100, 'bgap': (f['MKT_BASIS'] - f['THRY_BASIS']) / f['SPOT_PRC'] * 100})


def iv_pcr():
    i = pd.read_csv(os.path.join(L.DATA, 'iv_daily.csv')); i.columns = [c.lstrip('﻿') for c in i.columns]
    i['date'] = pd.to_datetime(i['BAS_DD'], format='%Y/%m/%d', errors='coerce'); i = i.dropna(subset=['date']).set_index('date').sort_index()
    out = pd.DataFrame({'iv': num(i['REP_IMP_VOLT']), 'pcspread': num(i['PUT_AVG_IMP_VOLT']) - num(i['CALL_AVG_IMP_VOLT'])})
    p = pd.read_csv(os.path.join(L.DATA, 'pcr_daily.csv')); p.columns = [c.lstrip('﻿') for c in p.columns]
    p['date'] = pd.to_datetime(p['TRD_DD'], format='%Y/%m/%d', errors='coerce'); p = p.dropna(subset=['date']).set_index('date').sort_index()
    out = out.join(pd.DataFrame({'pcr': num(p['PCRATIO'])}), how='outer')
    out = out[~out.index.duplicated(keep='last')]
    return out


def put_oi():
    """살아 있는 월물(가까운 2개 자료) 콜·풋 미결제 합 — 날짜별."""
    c = L.chain('m')
    c = c[c['oi'] > 0]
    g = c.groupby(['date', 'cp'])['oi'].sum().unstack('cp')
    return pd.DataFrame({'poi': g.get('P'), 'coi': g.get('C')}).sort_index()


def wall_cross_events(feat, td, close):
    """(tag, 돌파일, 벽 행사가) — 종가가 전날 콜벽(같은 결제월) 위로 올라선 날."""
    W = feat['walls']
    ev = []
    for tag in ('F0', 'Q'):
        w = W[W['tag'] == tag].sort_values('date').drop_duplicates('date', keep='last').set_index('date')
        w = w.reindex(td)
        kprev = w['K'].shift(1); ymprev = w['ym'].shift(1)
        cond = (close > kprev) & (w['ym'] == ymprev) & kprev.notna()
        for d in td[cond.fillna(False).values]:
            ev.append((tag, d, float(kprev.loc[d])))
    return ev


def main():
    px = L.prices()['K200F']; td = px.index
    close = L.k200_index()['close'].reindex(td)   # 벽·풋 무게중심 거리는 A2 가 코스피200 지수 종가 기준으로 잼 → 같은 지수로 비교
    feat = pickle.load(open(os.path.join(L.LAB, 'work', 'lab_feat.pkl'), 'rb'))
    wide = feat['wide'].reindex(td)
    Fl = L.flows().reindex(td)
    fut1 = Fl['fut_for']; cash1 = Fl['cash_for']; put1 = Fl['put_for']
    fut3 = fut1.rolling(3, min_periods=3).sum(); cash3 = cash1.rolling(3, min_periods=3).sum(); put3 = put1.rolling(3, min_periods=3).sum()
    fut5 = fut1.rolling(5, min_periods=5).sum(); cash5 = cash1.rolling(5, min_periods=5).sum()
    q = {k: pct_rank(v) for k, v in (('fut1', fut1), ('cash1', cash1), ('fut3', fut3), ('cash3', cash3), ('fut5', fut5), ('cash5', cash5), ('put3', put3))}
    conds = []   # (id, 설명, 마스크)

    # --- xfail · xpost: 콜벽 돌파 실패 / 돌파 뒤 외국인 매도
    try:
        ev = wall_cross_events(feat, td, close)
        pos = {d: i for i, d in enumerate(td)}
        for tag in ('F0', 'Q'):
            m_back = pd.Series(False, index=td); m_back_f = m_back.copy(); m_back_fc = m_back.copy(); m_post = m_back.copy()
            for t, d, K in ev:
                if t != tag: continue
                i0 = pos[d]
                seg = td[i0 + 1: i0 + 1 + CROSS_WIN]
                if not len(seg): continue
                below = close.loc[seg] < K
                if below.any():
                    d1 = below.idxmax(); m_back.loc[d1] = True
                    if fut3.loc[d1] < 0: m_back_f.loc[d1] = True
                    if fut3.loc[d1] < 0 and cash3.loc[d1] < 0: m_back_fc.loc[d1] = True
                seg5 = td[i0 + 1: i0 + 6]
                hit = (q['fut1'].reindex(seg5) <= 0.20)
                if hit.any(): m_post.loc[hit.idxmax()] = True
            conds += [(f'xfail_{tag}', f'{tag} 콜벽 돌파 뒤 {CROSS_WIN}일 안 벽 아래로 되돌아온 첫날', m_back),
                      (f'xfail_{tag}_f3', f'{tag} 콜벽 돌파 실패(되돌아옴) + 외국인 선물 3일 누적 순매도', m_back_f),
                      (f'xfail_{tag}_fc3', f'{tag} 콜벽 돌파 실패(되돌아옴) + 외국인 선물·현물 3일 동시 순매도', m_back_fc),
                      (f'xpost_{tag}', f'{tag} 콜벽 돌파 뒤 5일 안 외국인 선물 순매도 하위20%(3년) 첫날', m_post)]
    except Exception as e:
        print('xfail 실패', e, flush=True)

    # --- pbrk: 풋 무게중심·풋벽 이탈
    try:
        for tag in ('F0', 'Q'):
            pc = wide.get(f'OW_{tag}_pcent_dist%'); pw = wide.get(f'OW_{tag}_pwall_dist%')
            if pc is not None:
                lvl = (close * (1 + pc / 100)).shift(1)   # 전날 지수 종가 × (1 + 거리%) = 전날 풋 무게중심 행사가
                conds.append((f'pbrk_cent_{tag}', f'{tag} 종가가 전날 풋 무게중심 아래로(첫날)', first_day(close < lvl)))
            if pw is not None:
                lvl = (close * (1 + pw / 100)).shift(1)
                conds.append((f'pbrk_wall_{tag}', f'{tag} 종가가 전날 풋벽(최대 풋 미결제) 아래로(첫날)', first_day(close < lvl)))
                conds.append((f'pnear_wall_{tag}', f'{tag} 풋벽까지 2% 안으로 내려옴(첫날)', first_day(pw.notna() & (pw > -2.0))))
    except Exception as e:
        print('pbrk 실패', e, flush=True)

    # --- poi: 풋 물량 급증
    try:
        P = put_oi().reindex(td)
        dpo = P['poi'] / P['poi'].shift(5) - 1
        dpc = (P['poi'] / P['coi']) / (P['poi'] / P['coi']).shift(5) - 1
        conds += [('poi_chg5q90', '풋 미결제 합 5일 증가율 3년 백분위 상위10%', pct_rank(dpo) >= 0.90),
                  ('pcoi_chg5q90', '풋/콜 미결제 비 5일 증가율 3년 백분위 상위10%', pct_rank(dpc) >= 0.90)]
    except Exception as e:
        print('poi 실패', e, flush=True)
    try:
        IV = iv_pcr().reindex(td)
        conds += [('pcr_q95', '풋/콜 거래량 비(PCR) 3년 백분위 상위5%', pct_rank(IV['pcr']) >= 0.95),
                  ('iv5_q90', '대표 IV 5일 상승폭 3년 백분위 상위10%', pct_rank(IV['iv'] - IV['iv'].shift(5)) >= 0.90),
                  ('pcs_q90', '풋−콜 평균 IV 차 3년 백분위 상위10%', pct_rank(IV['pcspread']) >= 0.90)]
        iv_up = pct_rank(IV['iv'] - IV['iv'].shift(5)) >= 0.90
    except Exception as e:
        print('IV 실패', e, flush=True); iv_up = pd.Series(False, index=td)

    # --- pre: 급락 전 징후(외국인 선물·현물 동시 매도, 베이시스)
    try:
        fs1 = (fut1 < 0) & (cash1 < 0) & (q['fut1'] <= 0.10) & (q['cash1'] <= 0.10)
        fs3 = (fut3 < 0) & (cash3 < 0) & (q['fut3'] <= 0.10) & (q['cash3'] <= 0.10)
        fs5 = (fut5 < 0) & (cash5 < 0) & (q['fut5'] <= 0.10) & (q['cash5'] <= 0.10)
        conds += [('fs1', '외국인 선물·현물 같은 날 순매도 모두 하위10%(3년)', fs1),
                  ('fs3', '외국인 선물·현물 3일 합 순매도 모두 하위10%(3년)', fs3),
                  ('fs5', '외국인 선물·현물 5일 합 순매도 모두 하위10%(3년)', fs5),
                  ('fs1_first', '외국인 선물·현물 같은 날 동시 하위10% 첫날(직전 5일 없음)', first_day(fs1)),
                  ('fs3_first', '외국인 선물·현물 3일 합 동시 하위10% 첫날', first_day(fs3)),
                  ('fput3', '외국인 풋 3일 순매수 상위10% + 선물 3일 순매도', (q['put3'] >= 0.90) & (fut3 < 0))]
        B = basis_front().reindex(td)
        blow = pct_rank(B['bp']) <= 0.10; bgap = pct_rank(B['bgap']) <= 0.10
        conds += [('basis_q10', '근월물 시장 베이시스(÷지수) 3년 백분위 하위10%', blow),
                  ('bgap_q10', '시장−이론 베이시스 괴리 3년 백분위 하위10%', bgap),
                  ('basis_neg', '근월물 시장 베이시스 음수(백워데이션)', B['bp'] < 0),
                  ('fs3_basis', '외국인 선물·현물 3일 동시 하위10% + 베이시스 하위10%', fs3 & blow),
                  ('fs3_iv', '외국인 선물·현물 3일 동시 하위10% + IV 5일 상승 상위10%', fs3 & iv_up.fillna(False)),
                  ('fs1_bgap', '외국인 선물·현물 같은 날 하위10% + 베이시스 괴리 하위10%', fs1 & bgap),
                  ('basis_iv', '베이시스 하위10% + IV 5일 상승 상위10%', blow & iv_up.fillna(False))]
    except Exception as e:
        print('pre 실패', e, flush=True)

    # --- gap: 밤사이 미국 급등 → 다음 날 시가 갭 상승 뒤 장중 되밀림(라운드 3, 갈래 D)
    #   라운드 2 에서 뒤 구간 적합 A6 조합(S&P·나스닥 선물 급등 + 코스피 3일 상승 등)이 앞 구간에서도 1일 하락 59.6%(104거래)로 기본 48.8% 보다 높았다.
    #   같은 생각을 고정 문턱(그 시점까지 3년 백분위)으로 다시 세워 어느 구간에도 맞추지 않은 판으로 시험한다.
    #   해외 값은 analyze.py 의 W_ 지표와 같은 규칙: 한국 t일 = 그 시장 현지 날짜 ≤ t 의 마지막 종가(미국 t일 종가는 한국 t+1일 시가 전에 나옴), 5일 넘게 비면 빈칸.
    try:
        ov = pd.read_csv(os.path.join(L.DATA, 'overseas_daily.csv'), parse_dates=['date']).set_index('date').sort_index()
        A = ov.reindex(ov.index.union(td)).ffill(limit=5).reindex(td)
        kp = L.prices()['KOSPI']['close'].reindex(td)
        es = A['ES=F'].pct_change(fill_method=None) * 100; nq = A['NQ=F'].pct_change(fill_method=None) * 100
        ewyg = (A['EWY'].pct_change(fill_method=None) + A['KRW=X'].pct_change(fill_method=None)) * 100 - kp.pct_change(fill_method=None) * 100
        qes, qnq, qew = pct_rank(es), pct_rank(nq), pct_rank(ewyg)
        k3 = pct_rank(close.pct_change(3)); otm = pct_rank(wide['OW_F0_otm_cp']) if 'OW_F0_otm_cp' in wide else pd.Series(np.nan, index=td)
        conds += [('gap_es', 'S&P500 선물 밤사이 등락 3년 백분위 상위10%', qes >= 0.90),
                  ('gap_esnq', 'S&P500·나스닥 선물 밤사이 등락 모두 상위10%', (qes >= 0.90) & (qnq >= 0.90)),
                  ('gap_ewy', 'EWY(원화 환산) − 코스피 괴리 상위10%(밤사이 재평가 큼)', qew >= 0.90),
                  ('gap_ewy95', 'EWY − 코스피 괴리 상위5%', qew >= 0.95),
                  ('gap_esnq_k3', 'S&P500·나스닥 선물 상위10% + 코스피200 3일 등락 상위20%', (qes >= 0.90) & (qnq >= 0.90) & (k3 >= 0.80)),
                  ('gap_ewy_k3', 'EWY 괴리 상위10% + 코스피200 3일 등락 상위20%', (qew >= 0.90) & (k3 >= 0.80)),
                  ('gap_ewy_otm', 'EWY 괴리 상위10% + 근월물 현재가 위 콜/아래 풋 미결제 비 상위20%', (qew >= 0.90) & (otm >= 0.80)),
                  ('gap_ewy_fsell', 'EWY 괴리 상위10% + 그날 외국인 선물 순매도', (qew >= 0.90) & (fut1 < 0)),
                  ('gap_es_fsell', 'S&P500 선물 상위10% + 그날 외국인 선물 순매도', (qes >= 0.90) & (fut1 < 0))]
        # 라운드 4(갈래 D): 라운드 3 에서 'S&P·나스닥 선물 상위10% + 코스피200 3일 상위20% → 1일 하락'이 앞 60거래 66.7%·뒤 21거래 90.5%,
        #   5일 급등 뒤(R7)를 겹치면 앞 14거래 85.7%·뒤 9거래 100%(표본 부족). '이미 오른 뒤일수록 되밀림이 강한가'(가설 5)와
        #   '문턱을 낮춰 거래 수를 늘려도 적중이 유지되나'(가설 6)를 미리 정한 격자로 본다(문턱은 모두 그 시점까지 3년 백분위·고정값, 어느 구간 성적도 안 봄).
        #   보유는 1일(다음 날 시가→종가)만 — gap2 가족.
        r5z = L.regime_features()['rg_r5z'].reindex(td)
        k5 = pct_rank(close.pct_change(5))
        us = {'u80': ('S&P·나스닥 선물 모두 상위20%', (qes >= 0.80) & (qnq >= 0.80)),
              'u85': ('S&P·나스닥 선물 모두 상위15%', (qes >= 0.85) & (qnq >= 0.85)),
              'u90': ('S&P·나스닥 선물 모두 상위10%', (qes >= 0.90) & (qnq >= 0.90)),
              'uor': ('S&P 또는 나스닥 선물 상위10%', (qes >= 0.90) | (qnq >= 0.90)),
              'e80': ('S&P 선물 상위20%', qes >= 0.80)}
        run = {'k3_70': ('코스피200 3일 등락 상위30%', k3 >= 0.70), 'k3_80': ('코스피200 3일 등락 상위20%', k3 >= 0.80),
               'k5_80': ('코스피200 5일 등락 상위20%', k5 >= 0.80), 'k5_90': ('코스피200 5일 등락 상위10%', k5 >= 0.90),
               'z1': ('5일 등락 ÷ 3년 5일 등락 표준편차 ≥ 1.0', r5z >= 1.0), 'z15': ('5일 급등(5일 등락 ≥ 1.5σ)', r5z >= 1.5)}
        for uk, (ud, um) in us.items():
            for rk, (rdsc, rm) in run.items():
                conds.append((f'gap2_{uk}_{rk}', f'{ud} + {rdsc}(밤사이 미국 급등 뒤 갭 되밀림)', um & rm))
        # 라운드 5(갈래 D): 라운드 4 최고 'S&P·나스닥 상위15% + 코스피200 3일 상위20% + 5일 급등 뒤'가 전체 35거래 82.9%(29/35)로
        #   새 기준(35거래·85%)에 1거래 모자람. 거래 수를 늘린 기반(문턱 완화·R7 또는 R9)에 '왜 되밀리나'를 가르는 거르개를 곱해 본다(gap3, 1일만).
        #   가설 7: 콜벽까지 올린 뒤 되밀림(사용자 가설 뒷부분의 1일 판) — 그날 종가가 근월물·분기물 콜벽 0.5% 아래까지 왔거나 넘어섬.
        #   가설 8: 외국인 추격 매수 뒤(선물 순매수 상위20%) 되밀림 vs 오른 날에도 외국인 선물 순매도.
        #   가설 9: 안심 국면(대표 IV 3년 백분위 30% 이하)에서 되밀림이 강함 / 선물 고평가(베이시스 상위20%) 차익 매도.
        #   거르개 문턱은 모두 미리 정한 값·그 시점까지 3년 백분위(어느 구간 성적도 안 봄).
        S0 = L.regime_states().reindex(td).fillna(False).astype(bool)
        r79 = S0['R7'] | S0['R9']
        bases = {'u85k3R7': ('S&P·나스닥 상위15% + 코스피200 3일 상위20% + 5일 급등 뒤', us['u85'][1] & run['k3_80'][1] & S0['R7']),
                 'u85k5R7': ('S&P·나스닥 상위15% + 코스피200 5일 상위20% + 5일 급등 뒤', us['u85'][1] & run['k5_80'][1] & S0['R7']),
                 'u80k5R7': ('S&P·나스닥 상위20% + 코스피200 5일 상위20% + 5일 급등 뒤', us['u80'][1] & run['k5_80'][1] & S0['R7']),
                 'u85k3R79': ('S&P·나스닥 상위15% + 코스피200 3일 상위20% + (5일 급등 뒤 또는 60일 고점 1% 안)', us['u85'][1] & run['k3_80'][1] & r79),
                 'u85k3': ('S&P·나스닥 상위15% + 코스피200 3일 상위20%', us['u85'][1] & run['k3_80'][1]),
                 'u80k3': ('S&P·나스닥 상위20% + 코스피200 3일 상위20%', us['u80'][1] & run['k3_80'][1])}
        filt = {'': ('', None)}
        for tg in ('F0', 'Q'):
            wd = wide.get(f'OW_{tg}_wall_dist%')
            if wd is not None:
                filt[f'cw{tg}'] = (f' + 종가가 {tg} 콜벽 0.5% 아래까지 오거나 넘어섬', wd.notna() & (wd <= 0.5))
                filt[f'cf{tg}'] = (f' + {tg} 콜벽까지 0.5% 넘게 남음', wd.notna() & (wd > 0.5))
        filt['ffb'] = (' + 그날 외국인 선물 순매수 상위20%(3년)', q['fut1'] >= 0.80)
        filt['ffs'] = (' + 그날 외국인 선물 순매도', fut1 < 0)
        filt['fcb'] = (' + 그날 외국인 현물 순매수 상위20%(3년)', q['cash1'] >= 0.80)
        try:
            ivq = pct_rank(iv_pcr().reindex(td)['iv'])
            filt['ivlo'] = (' + 대표 IV 3년 백분위 30% 이하(안심 국면)', ivq <= 0.30)
            filt['ivhi'] = (' + 대표 IV 3년 백분위 70% 이상', ivq >= 0.70)
        except Exception as e:
            print('gap3 IV 실패', e, flush=True)
        try:
            bq = pct_rank(basis_front().reindex(td)['bp'])
            filt['bhi'] = (' + 근월물 베이시스 3년 백분위 상위20%(선물 고평가)', bq >= 0.80)
        except Exception as e:
            print('gap3 베이시스 실패', e, flush=True)
        for bk, (bd, bm) in bases.items():
            for fk, (fd, fm) in filt.items():
                if fk == '' and bk in ('u85k3R7', 'u85k3', 'u80k3'): continue   # gap2·gap 가족에 이미 같은 조건 있음
                mm = bm if fm is None else (bm & fm.reindex(td).fillna(False).astype(bool))
                conds.append((f'gap3_{bk}' + (f'_{fk}' if fk else ''), f'{bd}{fd}(밤사이 미국 급등 뒤 갭 되밀림)', mm))
    except Exception as e:
        print('gap 실패', e, flush=True)

    # --- 장세 겹침
    S = L.regime_states().reindex(td).fillna(False).astype(bool)
    overlays = [('', '', None), ('_R3', ' + 하락 추세(60일선 아래)', 'R3'), ('_R8', ' + 60일 고점 −5% 넘게 조정 중', 'R8'),
                ('_R7', ' + 5일 급등 뒤', 'R7'), ('_R9', ' + 60일 고점 1% 안', 'R9')]
    tgts = [(f'h{h}', f'{h}일', None, h) for h in HS]
    for W in BARRIER:
        y, ex = L.barrier_exits(px, W, BK)
        tgts.append((f'b{W}', f'{W}일 안 큰 변동(±{BK:g}σ) 먼저', ex.reindex(td).dropna().to_dict(), W))
    cands = []; summ = []
    for cid, desc, m in conds:
        m = m.reindex(td).fillna(False).astype(bool)
        for tag, tdesc, rg in overlays:
            if cid.startswith('gap3_') and rg: continue   # gap3 = 장세 조건이 이미 기반에 들어 있음, 겹침 없이 한 번만
            mm = m & S[rg] if rg else m
            sig = td[mm.values]
            summ.append({'cond': cid + tag, 'desc': desc + tdesc, 'n_signals': len(sig)})
            if len(sig) < MIN_SIG: continue
            for tid, tname, exs, h in tgts:
                if cid.startswith(('gap2_', 'gap3_')) and tid != 'h1': continue   # gap2·gap3 = 1일(다음 날 시가→종가)만
                exits = [L.exit_after(td, s, h) for s in sig] if exs is None else [exs.get(s, pd.NaT) for s in sig]
                tr = pd.DataFrame({'signal': sig, 'exit': exits}).dropna()
                if len(tr) < MIN_SIG: continue
                cands.append({'id': f'A13_{cid}{tag}_{tid}_dn', 'agent': 'A13', 'family': cid.split('_')[0] + ('_big' if exs is not None else ''),
                              'desc': f'{desc}{tdesc} → {tname} 하락', 'direction': -1, 'trades': tr})
    pd.DataFrame(summ).to_csv(os.path.join(L.out_dir(AG), 'cond_counts.csv'), index=False, encoding='utf-8')
    print('조건', len(conds), '· 후보', len(cands), flush=True)
    L.save_candidates(AG, cands)


if __name__ == '__main__':
    main()
