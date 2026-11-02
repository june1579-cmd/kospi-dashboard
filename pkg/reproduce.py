# -*- coding: utf-8 -*-
"""
reproduce.py — '코스피_반대매매_원자료_통합' 엑셀 하나로 대시보드 데이터(CSV)를 처음부터 다시 계산한다.

사용:  python3 reproduce.py 통합.xlsx 출력폴더 [--trend-end 2026-10-20]
출력:  market_daily, liq_daily, credit, monthly, flows_daily, lag, alarms, combo, lead_cmp,
       trend_years(계산 열만 다시 계산), trend_champ·trend_champ_rules(해마다 그해 1위 조합), fut_daily, etf_lev, reentry, buy3, sell3, night_fut, gap_table, q_*(정밀 검증), combo_table·combo_select·combo_wf·combo_now(매수×매도 조합 감시)  (+ checks.txt 검증용 매매 결과)
고정 자료(fx_daily, events, ind_*, ret26, concentration, episodes, credit_change, leverage, flows)는
패키지의 datasets/ 폴더 것을 그대로 쓴다 — 이 스크립트는 만들지 않는다.

규칙 요약 (프롬프트의 정의와 같다)
- 같은 날짜가 여러 파일에 있으면 통합 엑셀에 이미 '나중 파일 우선'으로 합쳐져 있다.
- 금투협(신용·예탁금·미수금·미수 반대매매)은 다음 영업일에 공시되므로 신호 계산에는 하루 늦춰(shift 1) 쓴다.
- 큰 흐름(실제) = 코스피 종가 10% 지그재그. 표시용 줄(leg)은 전환일 당일을 새 방향으로 본다.
"""
import sys, os, re, json, argparse, warnings
import numpy as np, pandas as pd
warnings.filterwarnings('ignore')

# ----------------------------------------------------------------------------- 입력
def load(xlsx):
    X = pd.read_excel(xlsx, sheet_name=None)
    def S(name):
        df = X[name].copy(); df['일자'] = pd.to_datetime(df['일자']); return df.set_index('일자').sort_index()
    K = S('코스피_일별').rename(columns={'종가(pt)': 'close', '대비(pt)': 'diff', '등락률(%)': 'chg', '시가(pt)': 'open', '고가(pt)': 'high', '저가(pt)': 'low',
                                    '거래량(천주)': 'vol', '거래대금(백만원)': 'val'})
    V = S('VKOSPI_일별').rename(columns={'종가': 'close', '고가': 'high', '저가': 'low', '시가': 'open'})
    F = S('투자자별_코스피_일별').rename(columns={'기관 합계(십억원)': 'inst', '기타법인(십억원)': 'other', '개인(십억원)': 'indiv', '외국인 합계(십억원)': 'foreign'})
    L = S('증시자금추이_금투협'); L.columns = ['deposit', 'deriv', 'rp', 'misu', 'liq', 'ratio', 'file']
    C = S('신용공여잔고_금투협'); C.columns = ['credit', 'kospi', 'kosdaq', 'short', 'short_k', 'short_q', 'sub', 'pledge', 'file']
    PUB = S('참고_공개수집_2024.10~')
    ETF = S('레버리지ETF_시세'); EI = S('ETF_투자자별')
    NF = S('야간선물_일별') if '야간선물_일별' in X else None
    if NF is not None:
        for col in ('시가', '고가', '저가', '종가', '대비', '거래량', '미결제약정'): NF[col] = pd.to_numeric(NF[col], errors='coerce')
    for df in (K, V, F, L, C):
        for col in df.columns:
            if col not in ('원본 파일', '출처 구분', 'file'): df[col] = pd.to_numeric(df[col], errors='coerce')
    VIX = None
    if '참고_VIX_유가' in X:
        vx = X['참고_VIX_유가'].copy(); vx['일자'] = pd.to_datetime(vx['일자']); VIX = vx.set_index('일자')['VIX 종가'].dropna().sort_index()
    vf = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'vix_daily.csv')
    if os.path.exists(vf):   # 보조 파일(공개 수집)로 시트 이후 날짜를 채움
        vd = pd.read_csv(vf, parse_dates=['date']).set_index('date')['close'].dropna().sort_index()
        VIX = vd if VIX is None else pd.concat([VIX, vd[vd.index > VIX.index.max()]]).sort_index()
    return dict(K=K, V=V, F=F, L=L, C=C, PUB=PUB, ETF=ETF, EI=EI, NF=NF, VIX=VIX)

# ----------------------------------------------------------------------------- 공통 도구
def zigzag(s, th):
    """종가 s에서 th(0.10 = 10%) 이상 되돌림이 확인될 때마다 고점(P)·저점(T)을 찍는다."""
    piv = []; mode = None; ext_i = s.index[0]; ext_v = s.iloc[0]
    for d, v in s.items():
        if mode is None:
            if v >= ext_v * (1 + th): mode = 'up'; piv.append((ext_i, 'T')); ext_i, ext_v = d, v
            elif v <= ext_v * (1 - th): mode = 'down'; piv.append((ext_i, 'P')); ext_i, ext_v = d, v
            else:
                if abs(v / s.iloc[0] - 1) > abs(ext_v / s.iloc[0] - 1): ext_i, ext_v = d, v
        elif mode == 'up':
            if v > ext_v: ext_i, ext_v = d, v
            elif v <= ext_v * (1 - th): piv.append((ext_i, 'P')); mode = 'down'; ext_i, ext_v = d, v
        else:
            if v < ext_v: ext_i, ext_v = d, v
            elif v >= ext_v * (1 + th): piv.append((ext_i, 'T')); mode = 'up'; ext_i, ext_v = d, v
    return piv

def leg_new_dir(idx, piv):
    """표시용 '실제' 줄: 전환일 당일부터 새 방향(+1 상승 / -1 하락)."""
    leg = pd.Series(np.nan, index=idx); last = idx[0]
    for d, t in piv:
        leg[(leg.index >= last) & (leg.index <= d)] = 1 if t == 'P' else -1; last = d
    leg[leg.index > last] = -1 if piv[-1][1] == 'P' else 1
    return leg

def ffill0(A):
    """0(판단 없음)은 직전 판단으로 채운다. 맨 앞의 0은 0으로 남는다."""
    A = np.atleast_2d(A)
    p = np.where(A != 0, np.arange(A.shape[1]), 0); p = np.maximum.accumulate(p, axis=1)
    return np.take_along_axis(A, p, axis=1)

def hyst(idx, buy, sell, fill0=True):
    s = pd.Series(np.where(buy, 1.0, np.where(sell, -1.0, np.nan)), index=idx).ffill()
    return s.fillna(0) if fill0 else s

def ema(x, n): return x.ewm(span=n, adjust=False).mean()

def true_range(c, H, L): return pd.concat([H - L, (H - c.shift()).abs(), (L - c.shift()).abs()], axis=1).max(axis=1)

pct = lambda a, b: (a / b - 1) * 100

# ----------------------------------------------------------------------------- 1. 2026 표시용 자료
SRC_KRX_K = 'KRX 정보데이터시스템 코스피 일별 시세(사용자 제공 파일)'
SRC_KOFIA_L = '금융투자협회 freesis 증시자금추이(사용자 제공 파일)'
SRC_KOFIA_C = '금융투자협회 freesis(사용자 제공 파일)'
SRC_FLOW = 'KRX 정보데이터시스템 투자자별 거래실적(사용자 제공 파일, 원자료 십억원, 표시 조원)'
SRC_FLOW_PUB = 'KRX 투자자별 거래실적 확정치(다음 금융 경유 다음 날 아침 값 — 2026-10-20~26 KRX 파일과 5일 모두 일치 확인, 공개 수집 저장소, 원자료 억원, 표시 조원)'
Y0 = pd.Timestamp('2026-01-01')
YC = pd.Timestamp('2015-01-01')   # 그래프용 일별·월별 자료 시작(2015-01-02부터, 화면 기본은 2025~2026). 표·검증(급락일 표·번복 검사 등)은 Y0(2026) 그대로

def market_daily(D):
    K, V, PUB = D['K'], D['V'], D['PUB']
    k = K[K.index >= YC]; rows = []
    for d, r in k.iterrows():
        kd = PUB['코스닥(pt)'].get(d, np.nan); vc = V['close'].get(d, np.nan); vh = V['high'].get(d, np.nan)
        hv = not pd.isna(vc)
        kf = str(r.get('원본 파일', '')); vf = str(V['원본 파일'].get(d, '')) if '원본 파일' in V.columns else ''
        _m = re.search(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2})', kf)
        ksrc = ('KRX 정보데이터시스템 코스피 일별 시세(pykrx 자동 수집, GitHub Actions ' + (_m.group(1) if _m else '') + ')') if kf.startswith('자동 수집') else \
               'KRX 정보데이터시스템 코스피 일별 시세(pykrx 자동 수집, 사용자 제공 ' + kf.split('/')[0] + ')' if 'pykrx' in kf else (kf if kf.startswith('공개') else SRC_KRX_K)
        vsrc = ('VKOSPI 종가 KRX(공개 수집 저장소), 시가·고가·저가 확인 불가' if '확인 불가' in vf else ('VKOSPI ' + vf.split(' — ')[0] if vf.startswith('종가') else 'VKOSPI KRX(사용자 제공 파일)')) if hv else ''
        rows.append({'date': d.strftime('%Y-%m-%d'), 'kospi': r.close, 'kospi_chg_pct': r.chg, 'kosdaq': '' if pd.isna(kd) else kd,
                     'vkospi': vc if hv else '', 'vkospi_high': '' if (not hv or pd.isna(vh)) else vh, 'vkospi_basis': '종가(KRX)' if hv else '',
                     'basis': 'KRX 원자료(pykrx 자동 수집)' if 'pykrx' in kf else ('공개 시세(원천 KRX)' if kf.startswith('공개') else 'KRX 원자료'),
                     'source': ksrc + (' · ' + vsrc if vsrc else '') + (' · 코스닥 다음 금융(원천 KRX)' if not pd.isna(kd) else '')})
    return pd.DataFrame(rows)

def liq_daily(D):
    L = D['L'][D['L'].index >= YC]
    return pd.DataFrame({'date': L.index.strftime('%Y-%m-%d'), 'liq_eok': (L.liq / 100).round(2).values, 'ratio_pct': L.ratio.values,
                         'misu_eok': (L.misu / 100).round(2).values, 'basis': '금투협 원자료', 'source': SRC_KOFIA_L})

def credit(D):
    L = D['L'][D['L'].index >= YC]; C = D['C'][D['C'].index >= YC].copy()
    C['chg'] = C.credit.pct_change() * 100                    # 그래프 기간 안에서만 계산(2015-01-02는 빈칸)
    rows = []
    for d in sorted(set(L.index) | set(C.index)):
        r = C.loc[d] if d in C.index else None
        rows.append({'date': d.strftime('%Y-%m-%d'),
                     'credit_jo': round(r.credit / 1e6, 3) if r is not None else '',
                     'kospi_jo': round(r.kospi / 1e6, 3) if r is not None and pd.notna(r.kospi) else '',
                     'kosdaq_jo': round(r.kosdaq / 1e6, 3) if r is not None and pd.notna(r.kosdaq) else '',
                     'deposit_jo': round(L.deposit[d] / 1e6, 3) if d in L.index else '',
                     'chg_pct': round(r.chg, 2) if r is not None and pd.notna(r.chg) else '',
                     'basis': '금투협 원자료' if r is not None else '예탁금만(신용 미공시)', 'source': SRC_KOFIA_C})
    return pd.DataFrame(rows)

def flows_daily(D):
    F = D['F'][D['F'].index >= YC]
    def _src(s):
        s = str(s)
        if s.startswith('공개 수집') and '잠정' in s: return 'KRX 투자자별 거래실적 잠정치(다음 금융 경유, 공개 수집 저장소 — ' + ('18시 집계' if '18시' in s else '장 마감 직후') + ', 다음 날 아침 확정치로 교체)'
        if s.startswith('공개 수집'): return SRC_FLOW_PUB
        if '잠정' in s: return 'KRX 투자자별 거래실적 잠정치(장 마감 직후 다음 금융 경유 — 다음 실행에서 확정치로 교체)'
        if 'pykrx' in s: return 'KRX 정보데이터시스템 투자자별 거래실적 확정치(pykrx 자동 수집, 사용자 제공 파일, 원자료 원 → 십억원 반올림, 표시 조원)'
        return SRC_FLOW
    src = [_src(s) for s in F['출처 구분']]
    basis = ['KRX 잠정치(확정 전)' if '잠정' in str(s) else 'KRX 원자료' for s in F['출처 구분']]
    return pd.DataFrame({'date': F.index.strftime('%Y-%m-%d'), 'foreign_jo': np.round(F.foreign.values / 1000, 4), 'inst_jo': np.round(F.inst.values / 1000, 4),
                         'indiv_jo': np.round(F.indiv.values / 1000, 4), 'other_jo': np.round(F.other.values / 1000, 4), 'basis': basis, 'source': src})   # 십억원(소수 1자리) → 조원, 부동소수 찌꺼기 제거

def monthly(D):
    L = D['L'][D['L'].index >= YC]; F = D['F'][D['F'].index >= YC]
    fo = (F.groupby(F.index.strftime('%Y-%m')).foreign.sum() / 1000).round(3).to_dict()
    pub_months = {d.strftime('%Y-%m') for d, s in F['출처 구분'].items() if str(s).startswith('공개 수집')}
    lastm = L.index.max().strftime('%Y-%m'); rows = []
    for m, g in L.groupby(L.index.strftime('%Y-%m')):
        part = f"{g.index.min().month}/{g.index.min().day}~{g.index.max().day}, {len(g)}거래일" if m == lastm else ''
        fm = F[F.index.strftime('%Y-%m') == m]
        frng = f" ({fm.index.min().month}/{fm.index.min().day}~{fm.index.max().day})" if part and len(fm) else ''
        rows.append({'month': m, 'avg_eok': round(g.liq.mean() / 100, 1), 'total_eok': round(g.liq.sum() / 100, 1), 'max_eok': round(g.liq.max() / 100, 1),
                     'days': len(g), 'foreign_jo': fo.get(m, ''), 'partial': part,
                     'basis': '미수 반대매매는 금투협 원자료 집계' + (f' (부분월: {part})' if part else '') + '. 외국인은 KRX 원자료 합계' + frng,
                     'source': '금융투자협회 freesis 증시자금추이·KRX 투자자별 거래실적(사용자 제공 파일' + (', 일부 날짜 투자자별은 공개 수집 확정치' if m in pub_months else '') + ')'})
    return pd.DataFrame(rows)

def lag_table(D):
    """2026년 코스피 -5% 이하 급락일마다 T0~T+3 거래일의 미수 반대매매(억원)."""
    K = D['K'][D['K'].index >= Y0]; L = D['L']
    days = list(K.index); pos = {d: i for i, d in enumerate(days)}
    lv = {d: round(v / 100, 2) for d, v in L.liq.items()}; lastpub = L.index.max()
    crash = [d for d in days if K.chg[d] <= -5]; ci = [pos[d] for d in crash]
    md = lambda d: f"{d.month}/{d.day}"; rows = []
    for j, d in enumerate(crash):
        i = pos[d]; r = {'crash': md(d), 'date': d.strftime('%Y-%m-%d'), 'crash_pct': K.chg[d]}
        pend = []; vals = []
        for k in range(4):
            dk = days[i + k] if i + k < len(days) else None
            r[f'd{k}'] = dk.strftime('%Y-%m-%d') if dk is not None else ''
            if dk is not None and dk in lv: r[f't{k}'] = lv[dk]; vals.append((lv[dk], k))
            else: r[f't{k}'] = ''; pend.append(k)
        nb = [crash[j2] for j2 in (j - 1, j + 1) if 0 <= j2 < len(crash) and abs(ci[j2] - i) <= 3]
        r['overlap'] = '겹침' if nb else ''; r['overlap_with'] = '·'.join(md(x) for x in nb)
        r['pending'] = ' '.join(f't{k}' for k in pend)
        pk = max(vals)[1] if vals else None
        r['peak'] = '' if pk is None else ('T0' if pk == 0 else f'T+{pk}')
        note = f"정점 {r['peak']}" if pk is not None else ''
        if pend: note += ' · ' + '·'.join((f"T+{k}" if k else 'T0') + (f"({md(days[i + k])})" if i + k < len(days) else '') for k in pend) + ' 미공시'
        r['note'] = note; rows.append(r)
    cols = ['crash', 'date', 'crash_pct', 't0', 't1', 't2', 't3', 'd0', 'd1', 'd2', 'd3', 'overlap', 'overlap_with', 'pending', 'peak', 'note']
    return pd.DataFrame(rows)[cols]

def fut_daily(D):
    P = D['PUB'][D['PUB'].index >= YC]; MULT = 250000
    P = P.dropna(subset=['선물 외국인 순매수(계약)', '선물 기관 순매수(계약)', '선물 개인 순매수(계약)', '선물 가격(pt)', '선물 미결제약정(계약)'])   # 선물 값이 없는 날(2025-12-31 휴장) 제외
    out = pd.DataFrame({'date': P.index.strftime('%Y-%m-%d'), 'foreign_ct': P['선물 외국인 순매수(계약)'].astype(int).values,
                        'inst_ct': P['선물 기관 순매수(계약)'].astype(int).values, 'indiv_ct': P['선물 개인 순매수(계약)'].astype(int).values,
                        'price': P['선물 가격(pt)'].values, 'oi': P['선물 미결제약정(계약)'].astype(int).values})
    for k, col in (('foreign', '선물 외국인 순매수(계약)'), ('inst', '선물 기관 순매수(계약)'), ('indiv', '선물 개인 순매수(계약)')):
        out[k + '_jo'] = (P[col] * P['선물 가격(pt)'] * MULT / 1e12).round(3).values
    out['basis'] = '계약 수는 원자료, 조원은 계약 수 × 그날 선물 종가 × 25만원으로 환산'
    out['source'] = '다음 금융 코스피200 선물 투자자별(원천 KRX, 전 월물 합계) · 공개 수집 저장소 github.com/Jaey27/kr-flow-dashboard'
    return out

def etf_lev(D):
    E = D['ETF'].copy(); EI = D['EI']
    E['flow_eok'] = (E['상장좌수(좌)'].diff() * E['NAV(원)'] / 1e8).round(0)
    E = E[E.index >= YC]
    out = pd.DataFrame({'date': E.index.strftime('%Y-%m-%d'), 'etf_close': E['종가(원)'].values, 'units': pd.array(E['상장좌수(좌)'].values, dtype='Int64'), 'flow_eok': E.flow_eok.values})
    for k, col in (('inst', '기관합계(원)'), ('other', '기타법인(원)'), ('indiv', '개인(원)'), ('foreign', '외국인 합계(원)')):
        out[k + '_eok'] = (EI[col] / 1e8).round(1).reindex(E.index).values
    out['basis'] = 'KRX 원자료. flow_eok = 상장좌수 증감 × NAV(설정·환매 자금, 억원)'; out['source'] = 'KRX ETF 개별종목 시세·투자자별(사용자 제공 파일)'
    return out

# ----------------------------------------------------------------------------- 2. 매도·매수 신호 6개 (2015~)
RULES = {('매도', '민감형'): '20일 신고가·VKOSPI 3일 +5%(지수 상승)·신용/예탁금 10일 +0.5%p',
         ('매도', '중간형'): '20일 신고가·VKOSPI 3일 +5%(지수 상승)·예탁금 10일 -3%',
         ('매도', '엄격형'): 'VKOSPI 10일 +10%(지수 상승)·신용 3일 +1%·신용/예탁금 20일 +0.5%p',
         ('매수', '민감형'): '60일선보다 3% 이상 아래·개인 5일 순매수 상위 20%·신용 5일 -1%',
         ('매수', '중간형'): '15일 -7% 이상 하락·개인 5일 순매수 상위 20%·신용 5일 -1%',
         ('매수', '엄격형'): '3일 -7% 이상 급락·20일 저점 1% 이내·신용 5일 -1%'}

def signal_series(D):
    K, V, F, L, C = D['K'], D['V'], D['F'], D['L'], D['C']
    c = K.close; idx = c.index
    vk = V.close.reindex(idx); ind = F.indiv.reindex(idx)                       # 개인 순매수(십억원)
    cred = (C.credit / 1e6).reindex(idx).shift(1); dep = (L.deposit / 1e6).reindex(idx).shift(1)   # 전날 공시분(조원)
    cd = cred / dep * 100
    up3 = (pct(vk, vk.shift(3)) >= 5) & (c > c.shift(3)); hi20 = c >= c.rolling(20).max()
    i5 = ind.rolling(5).sum(); i5top = i5 >= i5.rolling(250, min_periods=120).quantile(0.8); cr5 = pct(cred, cred.shift(5)) <= -1
    S = {('매도', '민감형'): hi20 & up3 & (cd - cd.shift(10) >= 0.5),
         ('매도', '중간형'): hi20 & up3 & (pct(dep, dep.shift(10)) <= -3),
         ('매도', '엄격형'): (pct(vk, vk.shift(10)) >= 10) & (c > c.shift(10)) & (pct(cred, cred.shift(3)) >= 1) & (cd - cd.shift(20) >= 0.5),
         ('매수', '민감형'): (pct(c, c.rolling(60).mean()) <= -3) & i5top & cr5,
         ('매수', '중간형'): (pct(c, c.shift(15)) <= -7) & i5top & cr5,
         ('매수', '엄격형'): (pct(c, c.shift(3)) <= -7) & (c <= c.rolling(20).min() * 1.01) & cr5}
    return {k: v.fillna(False) for k, v in S.items()}

def classify(D, S, rules, extra=None):
    """신호 날짜마다 이후 20거래일 최고·최저와 큰 전환 대비 판정(alarms·buy3·sell3 공용). S = {(side, type): bool Series}."""
    c = D['K'].close; idx = c.index; T = len(c)
    piv = zigzag(c, 0.10)
    legs = list(zip(piv[:-1], piv[1:])); last = piv[-1]
    legs.append((last, (c[last[0]:].idxmin(), 'T')) if last[1] == 'P' else (last, (c[last[0]:].idxmax(), 'P')))
    win = {'매도': {}, '매수': {}}; inleg = {'매도': pd.Series(False, index=idx), '매수': pd.Series(False, index=idx)}
    for (d1, t1), (d2, t2) in legs:
        side = '매도' if t1 == 'P' else '매수'; inleg[side][d1:d2] = True
        move = (c[d2] / c[d1] - 1) * 100
        if abs(move) < 15: continue
        i = idx.get_loc(d1); end = i; lvl = c[d1] * (0.95 if side == '매도' else 1.05)
        ok = (lambda v: v > lvl) if side == '매도' else (lambda v: v < lvl)
        while end + 1 < T and ok(c.iloc[end + 1]): end += 1
        for t in range(max(0, i - 10), end + 1):
            if (c.iloc[t] >= lvl) if side == '매도' else (c.iloc[t] <= lvl):
                win[side][idx[t]] = f"큰 {'하락' if side == '매도' else '상승'} 직전({d1.month}/{d1.day} {'고점' if side == '매도' else '바닥'} → {move:+.1f}%)"
    rows = []
    for (side, typ), A in S.items():
        prev = None
        for d in idx[A.values]:
            i = idx.get_loc(d); fut = c.iloc[i + 1:i + 21]
            up = round((fut.max() / c.iloc[i] - 1) * 100, 1) if len(fut) else np.nan
            dn = round((fut.min() / c.iloc[i] - 1) * 100, 1) if len(fut) else np.nan
            start = prev is None or i - prev > 5; prev = i
            if d in win[side]: res = win[side][d]
            elif side == '매도': res = '10% 이상 하락 앞' if dn <= -10 else ('하락 구간 중' if inleg['매도'][d] else ('판정 전' if len(fut) < 20 else '헛경보'))
            else: res = '20일 안 10% 이상 상승' if up >= 10 else ('상승 구간 중' if inleg['매수'][d] else ('판정 전' if len(fut) < 20 else '헛신호'))
            if side == '매수' and dn <= -10 and d not in win[side]: res += ' · 이후 10% 넘게 더 하락'
            row = {'date': d.strftime('%Y-%m-%d'), 'side': side, 'type': typ, 'start': '시작' if start else '지속', 'kospi': round(c.iloc[i], 2),
                   'up20': '' if np.isnan(up) else up, 'dn20': '' if np.isnan(dn) else dn, 'result': res, 'rule': rules[(side, typ)]}
            if extra: row.update(extra[(side, typ)])
            rows.append(row)
    return pd.DataFrame(rows).sort_values(['date', 'side', 'type']).reset_index(drop=True)

def alarms(D):
    return classify(D, signal_series(D), RULES)

# ----------------------------------------------------------------------------- 2b. 2015~2024 최적화 매수·매도 신호 1·2·3위 (2026-10-26 탐색)
BUY3 = [
 (1, '3개 중 2개: VKOSPI 5일 상승 · VKOSPI 하루 −10%↓ · 대주 누적 하위10%', '2015~24 +308%(보유 60일)·+300%(20일), 묶음 44. "대주 누적 하위10%"는 공매도 금지 기간(2020-03~2021-05)에만 켜지는 국면 표시'),
 (2, 'VKOSPI 5일 하락 + 예탁금 5일 +0%↑ + 신용/예탁금<35% + VIX 5일 상승', '2015~24 +294%(보유 20일), 묶음 54. 4조건 AND 27억 9천만 개 중 1위. VIX(전날 미국 종가)가 필요'),
 (3, '예탁금 5일 −3%↑ + VKOSPI 하루 −10%↓ + 담보융자 20일 감소', '2015~24 +283%(보유 120일), 묶음 11. 3조건 AND 1,580만 개 중 보유 120일 1위')]
SELL3 = [
 (1, 'SMA8>SMA22 + 기관 60일 순매도 + 신용/예탁금>35%', '2015~24 보유+회피 전략 +398%(현금 20일, 그냥 보유 +25%), 묶음 40. "신용/예탁금>35%"는 2018~19 약세장 대부분에 켜져 있던 국면 표시. 2025~26에는 한 번도 안 켜짐'),
 (2, '(RSI14>70 또는 개인 60일 순매수>0) 그리고 VIX<20', '2015~24 +304%(현금 20일), 묶음 38. 2025~26에는 상승장 중 현금(전략 +30% vs 보유 +125%). VIX(전날 미국 종가) 필요'),
 (3, '3개 중 2개: 대주 20일 증가 · RP 누적 상위10% · 신용/예탁금>35%', '2015~24 +304%(현금 20일), 묶음 47. 2025~26에는 상승장 대부분 현금(전략 −21% vs 보유 +125%)')]
def _vix_asof(D, idx):
    """VIX(미국 d일 종가)는 한국 d+1일 장 마감 때 아는 값."""
    VIX = D.get('VIX')
    if VIX is None or not len(VIX): return None
    vs = VIX.copy(); vs.index = pd.to_datetime(vs.index) + pd.Timedelta(days=1)
    return vs.reindex(vs.index.union(idx)).ffill().reindex(idx)
def _opt_atoms(D):
    """최적화 매수·매도 1·2·3위에 쓰는 조건(원자) 전부 — 탐색 때와 같은 정의. 금투협(예탁금·신용·대주·담보융자·RP)은 전날 공시분, VIX는 전날 미국 종가."""
    K, V, F, L, C = D['K'], D['V'], D['F'], D['L'], D['C']; c = K.close; idx = c.index
    vk = V.close.reindex(idx).ffill()
    ins = F.inst.reindex(idx); ind = F.indiv.reindex(idx)
    dep = L.deposit.reindex(idx).shift(1); rp = L.rp.reindex(idx).shift(1); cred = C.credit.reindex(idx).shift(1); short = C.short.reindex(idx).shift(1); pledge = C.pledge.reindex(idx).shift(1)
    b = lambda s: s.fillna(False).astype(bool) if s.dtype != bool else s
    vix = _vix_asof(D, idx); novix = pd.Series(False, index=idx)
    dlt = c.diff(); g = dlt.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean(); l_ = (-dlt.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean(); rsi = 100 - 100 / (1 + g / l_)
    i60 = ins.rolling(60).sum(); d60 = ind.rolling(60).sum(); dep5 = dep / dep.shift(5) - 1
    A = {
        'vk5up': ('VKOSPI 5일 상승', b(vk / vk.shift(5) - 1 > 0)), 'vk5dn': ('VKOSPI 5일 하락', b(vk / vk.shift(5) - 1 < 0)), 'vk1': ('VKOSPI 하루 −10%↓', b(vk / vk.shift(1) - 1 <= -0.10)),
        'short_lo': ('대주 누적 하위10%', b(short < short.expanding(250).quantile(0.1))),
        'dep5_0': ('예탁금 5일 +0%↑', b(dep5 > 0)), 'dep5_m3': ('예탁금 5일 −3%↑', b(dep5 > -0.03)),
        'cd_lt35': ('신용/예탁금<35%', b(cred / dep * 100 < 35)), 'cd_gt35': ('신용/예탁금>35%', b(cred / dep * 100 > 35)),
        'pl20': ('담보융자 20일 감소', b(pledge / pledge.shift(20) - 1 < 0)),
        'vix5up': ('VIX 5일 상승', b(vix / vix.shift(5) - 1 > 0) if vix is not None else novix), 'vix20': ('VIX<20', b(vix < 20) if vix is not None else novix),
        'sma8_22': ('SMA8>SMA22', b(c.rolling(8).mean() > c.rolling(22).mean())),
        'inst_sell60': ('기관 60일 순매도', (~(i60 > 0)) & i60.notna()),
        'rsi70': ('RSI14>70', b(rsi > 70)), 'ind_buy60': ('개인 60일 순매수', (~(0 > d60)) & d60.notna()),
        'short20': ('대주 20일 증가', b(short / short.shift(20) - 1 > 0)), 'rp_hi': ('RP 누적 상위10%', b(rp > rp.expanding(250).quantile(0.9)))}
    return A
# 게이지(그래프 아래 띠)용 2·3위 조건 묶음: (키, 쪽, 순위, 조건 목록[(원자 키, 설명)], 켜지는 데 필요한 조건 수, 논리 설명)
GAUGE = [('b2', '매수', 2, [('vk5dn',), ('dep5_0',), ('cd_lt35',), ('vix5up',)], 4, '4개 모두'),
         ('b3', '매수', 3, [('dep5_m3',), ('vk1',), ('pl20',)], 3, '3개 모두'),
         ('s2', '매도', 2, [('rsi70|ind_buy60',), ('vix20',)], 2, '2개 모두(앞 칸은 둘 중 하나)'),
         ('s3', '매도', 3, [('short20',), ('rp_hi',), ('cd_gt35',)], 2, '3개 중 2개')]
def _gauge_cond(A, key):
    if '|' in key:
        ks = key.split('|'); return ' 또는 '.join(A[k][0] for k in ks), np.logical_or.reduce([A[k][1].values for k in ks])
    return A[key][0], A[key][1].values
def buy3_series(D):
    """탐색 조건과 같은 정의(_opt_atoms)."""
    A = _opt_atoms(D); a = lambda k: A[k][1]
    s1 = (a('vk5up') & a('vk1')) | (a('vk5up') & a('short_lo')) | (a('vk1') & a('short_lo'))
    s2 = a('vk5dn') & a('dep5_0') & a('cd_lt35') & a('vix5up')
    s3 = a('dep5_m3') & a('vk1') & a('pl20')
    return {('매수', '최적화 1위'): s1, ('매수', '최적화 2위'): s2, ('매수', '최적화 3위'): s3}
def sell3_series(D):
    """2015~2024 최적화 매도 신호 1·2·3위 — 탐색 조건과 같은 정의(_opt_atoms)."""
    A = _opt_atoms(D); a = lambda k: A[k][1]
    s1 = a('sma8_22') & a('inst_sell60') & a('cd_gt35')
    s2 = (a('rsi70') | a('ind_buy60')) & a('vix20')
    s3 = (a('short20') & a('rp_hi')) | (a('short20') & a('cd_gt35')) | (a('rp_hi') & a('cd_gt35'))
    return {('매도', '최적화 1위'): s1, ('매도', '최적화 2위'): s2, ('매도', '최적화 3위'): s3}
def opt_gauge(D):
    """그래프 아래 게이지 띠용: 날짜마다 2·3위 매수·매도 조건이 몇 개 맞는지(lvl)와 조건별 0/1. 켜짐(on) = lvl ≥ need."""
    A = _opt_atoms(D); idx = D['K'].close.index
    out = pd.DataFrame({'date': idx.strftime('%Y-%m-%d')})
    for key, side, rank, conds, need, logic in GAUGE:
        cols = []
        for j, (ck,) in enumerate(conds):
            nm, v = _gauge_cond(A, ck); col = f'{key}_c{j + 1}'; out[col] = v.astype(int); cols.append(col)
        out[f'{key}_lvl'] = out[cols].sum(axis=1); out[f'{key}_need'] = need; out[f'{key}_on'] = (out[f'{key}_lvl'] >= need).astype(int)
    out['kospi'] = D['K'].close.round(2).values
    return out
def gauge_spec():
    """페이지 설명용 조건 이름(자료 설명에 적음)."""
    return {key: dict(side=side, rank=rank, need=need, logic=logic, conds=[(_gauge_cond_name(ck)) for (ck,) in conds]) for key, side, rank, conds, need, logic in GAUGE}
def _gauge_cond_name(ck):
    names = {'vk5up': 'VKOSPI 5일 상승', 'vk5dn': 'VKOSPI 5일 하락', 'vk1': 'VKOSPI 하루 −10%↓', 'short_lo': '대주 누적 하위10%', 'dep5_0': '예탁금 5일 +0%↑', 'dep5_m3': '예탁금 5일 −3%↑',
             'cd_lt35': '신용/예탁금<35%', 'cd_gt35': '신용/예탁금>35%', 'pl20': '담보융자 20일 감소', 'vix5up': 'VIX 5일 상승', 'vix20': 'VIX<20', 'sma8_22': 'SMA8>SMA22',
             'inst_sell60': '기관 60일 순매도', 'rsi70': 'RSI14>70', 'ind_buy60': '개인 60일 순매수', 'short20': '대주 20일 증가', 'rp_hi': 'RP 누적 상위10%'}
    return ' 또는 '.join(names[k] for k in ck.split('|'))
def _opt_out(D, S, spec, side):
    rules = {(side, f'최적화 {r}위'): txt for r, txt, _ in spec}
    extra = {(side, f'최적화 {r}위'): {'rank': r, 'note': note} for r, txt, note in spec}
    out = classify(D, S, rules, extra)
    last_vix = D['VIX'].index.max().strftime('%Y-%m-%d') if D.get('VIX') is not None and len(D['VIX']) else ''
    out['basis'] = ['2015~2024 최적화(2025~26 제외) · 탐색 2026-10-26' for _ in range(len(out))]
    out['vix_asof'] = [last_vix if t == '최적화 2위' else '' for t in out['type']]
    return out
def buy3(D): return _opt_out(D, buy3_series(D), BUY3, '매수')
def sell3(D): return _opt_out(D, sell3_series(D), SELL3, '매도')

# ----------------------------------------------------------------------------- 3. 큰 흐름 비교 줄 (2015~)
def strips(D):
    K, F = D['K'], D['F']
    c = K.close; idx = c.index; H = K.high.fillna(c); L_ = K.low.fillna(c); fo = F.foreign.reindex(idx); ind = F.indiv.reindex(idx)
    tr = true_range(c, H, L_)
    sgn = lambda x: np.nan_to_num(np.sign(x.values)).astype(np.int8)
    st = {}
    st['67일선'] = ffill0(sgn(c - ema(c, 67)))[0]
    # ADX10>30 방향: Wilder 방식(ewm alpha=1/n, adjust=True)
    n = 10; atr = tr.ewm(alpha=1 / n).mean(); up = H.diff(); dn = -L_.diff()
    pdm = np.where((up > dn) & (up > 0), up, 0); ndm = np.where((dn > up) & (dn > 0), dn, 0)
    pdi = 100 * pd.Series(pdm, index=idx).ewm(alpha=1 / n).mean() / atr; ndi = 100 * pd.Series(ndm, index=idx).ewm(alpha=1 / n).mean() / atr
    adx = (100 * (pdi - ndi).abs() / (pdi + ndi)).ewm(alpha=1 / n).mean()
    adx_dir = pd.Series(np.where(adx > 30, np.sign(pdi - ndi), np.nan), index=idx).ffill()
    a_adx = ffill0(np.nan_to_num(adx_dir.values).astype(np.int8))[0]
    a_ema1255 = ffill0(sgn(ema(c, 12) - ema(c, 55)))[0]
    vote = lambda *xs: ffill0(np.sign(np.sum([x.astype(int) for x in xs], axis=0)).astype(np.int8))[0]
    st['3개 다수결'] = vote(a_adx, st['67일선'], a_ema1255)
    # 2026 1위: 외국인 1일 상위20% 추세 + 개인 10일 하위20% 역추세 + SMA52>SMA95 (분위는 2015년부터 누적, 최소 250일)
    def q_trend(x, n, q):
        s = x.rolling(n).sum(); lo, hi = s.expanding(250).quantile(q), s.expanding(250).quantile(1 - q)
        return hyst(idx, s > hi, s < lo).values.astype(np.int8)
    def q_contra(x, n, q):
        s = x.rolling(n).sum(); lo, hi = s.expanding(250).quantile(q), s.expanding(250).quantile(1 - q)
        return hyst(idx, s < lo, s > hi).values.astype(np.int8)
    a_f1 = ffill0(q_trend(fo, 1, 0.2))[0]; a_i10 = ffill0(q_contra(ind, 10, 0.2))[0]
    a_sma = ffill0(sgn(c.rolling(52).mean() - c.rolling(95).mean()))[0]
    st['2026 1위'] = vote(a_f1, a_i10, a_sma)
    # 조합(2015~ 전체 자료로 계산한 판): ATR7 추적 + SMA8>SMA22 + 외국인 60일 역추세
    a7 = tr.rolling(7).mean()
    s_atr = hyst(idx, c > (c.rolling(7).min() + a7).shift(1), c < (c.rolling(7).max() - a7).shift(1), fill0=False)
    s_ma = np.sign(c.rolling(8).mean() - c.rolling(22).mean()); f60 = fo.rolling(60).sum()
    s_f = hyst(idx, f60 < f60.expanding(20).quantile(.3), f60 > f60.expanding(20).quantile(.7), fill0=False)
    v = np.sign(s_atr.fillna(0) + s_ma.fillna(0) + s_f.fillna(0)); v[v == 0] = np.nan
    st['조합'] = v.ffill().fillna(0).values.astype(np.int8)
    # 빠른 전환: 외국인 5일 상·하위 10% + 큰 하루 전환(ATR25, 1.4/1.5) + 큰 하루 전환(ATR25, 1.0/1.5) 중 2개 이상
    mid = (H + L_) / 2
    def bigday(n, mu, md):
        a = tr.ewm(alpha=1 / n).mean(); return hyst(idx, c > (mid + mu * a).shift(1), c < (mid - md * a).shift(1)).values.astype(np.int8)
    s5 = fo.rolling(5).sum(); lo, hi = s5.expanding(250).quantile(0.1), s5.expanding(250).quantile(0.9)
    a_fo5 = hyst(idx, s5 > hi, s5 < lo).values.astype(np.int8)
    st['빠른 전환'] = ffill0(np.sign(a_fo5.astype(int) + bigday(25, 1.4, 1.5) + bigday(25, 1.0, 1.5)).astype(np.int8))[0]
    return idx, st

def combo_1y(D, start='2025-10-17'):
    """대시보드 '조합' 줄(combo·atr·ma·f60 열)은 2025-10-17부터의 1년 자료만으로 계산한 판이다(start=None이면 전체 자료)."""
    K, F = D['K'], D['F']; K = K[K.index >= pd.Timestamp(start)] if start else K
    c = K.close; idx = c.index; H = K.high.fillna(c); L_ = K.low.fillna(c); fo = F.foreign.reindex(idx)
    a = true_range(c, H, L_).rolling(7).mean()
    up_, dn_ = c.rolling(7).max() - 1 * a, c.rolling(7).min() + 1 * a
    s_atr = hyst(idx, c > dn_.shift(1), c < up_.shift(1), fill0=False)
    s_ma = np.sign(c.rolling(8).mean() - c.rolling(22).mean())
    f60 = fo.rolling(60).sum(); lo, hi = f60.expanding(20).quantile(.3), f60.expanding(20).quantile(.7)
    s_f = hyst(idx, f60 < lo, f60 > hi, fill0=False)
    v = np.sign(s_atr.fillna(0) + s_ma.fillna(0) + s_f.fillna(0)); v[v == 0] = np.nan; combo = v.ffill()
    return pd.DataFrame({'combo': combo, 'atr': s_atr, 'ma': s_ma, 'f60': s_f}, index=idx)

def combo_csv(D):
    idx, st = strips(D); c = D['K'].close
    leg = leg_new_dir(idx, zigzag(c, 0.10))
    cb = combo_1y(D); d26 = idx[idx >= YC]
    out = pd.DataFrame(index=d26); out.index.name = 'date'
    out['leg'] = leg.reindex(d26).values
    for col in ('combo', 'atr', 'ma', 'f60'): out[col] = cb[col].reindex(d26).values
    # 1년판(2025-10-17~)이 아직 값을 못 내는 앞 구간은 같은 규칙을 2015년부터의 자료로 계산한 값(combo_basis = '전체 자료')
    cf = combo_1y(D, start=None); early = out['combo'].isna()
    for col in ('combo', 'atr', 'ma', 'f60'): out.loc[early, col] = cf[col].reindex(d26[early]).values
    cbasis = np.where(early, '전체 자료(2015~)', '1년 자료(2025-10-17~)')
    out['match'] = (out.combo == out.leg).astype(int)
    pos = [idx.get_loc(d) for d in d26]
    out['ema67'] = st['67일선'][pos].astype(float); out['match_ema'] = (out.ema67 == out.leg).astype(int)
    out['vote3'] = st['3개 다수결'][pos].astype(float); out['match_vote3'] = (out.vote3 == out.leg).astype(int)
    t26 = st['2026 1위'][pos]; out['top26'] = np.where(t26 == 1, 1.0, np.where(t26 == -1, -1.0, np.nan))   # 판단 전(2015년 초 0)은 빈칸
    out['fast'] = st['빠른 전환'][pos].astype(float); out['match_fast'] = (out.fast == out.leg).astype(int)
    out['combo_basis'] = cbasis
    out.index = out.index.strftime('%Y-%m-%d')
    return out.reset_index()

# ----------------------------------------------------------------------------- 4. 전환 시점(시차) 비교
def lag_matrix(A, P, T, early_cap=20, persist=10, need=0.8, miss_cap=60):
    """실제 전환일 대비 그 줄이 새 방향으로 바뀌어 이후 10거래일 중 8일 이상 유지된 첫날까지의 거래일 수(음수 = 먼저).
    NaN = 앞 구간을 반영하지 못해 이번 전환을 '놓침'."""
    n = A.shape[0]; out = np.full((n, len(P)), np.nan, np.float32)
    ch = np.zeros(A.shape, bool); ch[:, 1:] = A[:, 1:] != A[:, :-1]
    RS = np.maximum.accumulate(np.where(ch, np.arange(A.shape[1]), 0), axis=1)
    for k, (i, Dn, d, t) in enumerate(P):
        prev = P[k - 1][0] if k else 0; mid = (prev + i) // 2
        ws = max(i - early_cap, mid, 0); we = P[k + 1][0] if k + 1 < len(P) else T
        W = (A[:, ws:we] == Dn); w = W.shape[1]
        cs = np.zeros((n, w + 1), np.int32); cs[:, 1:] = np.cumsum(W, axis=1)
        j = np.arange(w); j2 = np.minimum(j + persist, w); cnt = cs[:, j2] - cs[:, j]; den = (j2 - j)
        ok = W & (cnt >= need * den); has = ok.any(1); first = ok.argmax(1)
        lag = (ws + first - i).astype(np.float32); lag[~has] = min(we - i, miss_cap)
        a0 = has & (first == 0); good0 = RS[:, ws] >= mid; lag[a0 & ~good0] = np.nan
        unknown = (A[:, ws:we] == 0).all(1); lag[unknown] = np.nan
        out[:, k] = lag
    return out

def lead_cmp(D):
    idx, st = strips(D); c = D['K'].close; T = len(idx); yrs = idx.year.values
    piv = zigzag(c, 0.10); pos = {d: i for i, d in enumerate(idx)}
    P = [(pos[d], -1 if t == 'P' else 1, d, t) for d, t in piv]
    leg = np.zeros(T, np.int8); last = 0
    for i, Dn, d, t in P: leg[last:i] = -Dn; last = i                     # 전환일 당일 = 새 방향
    leg[last:] = P[-1][1]
    names = ['빠른 전환', '67일선', '3개 다수결', '조합', '2026 1위']
    Mx = np.vstack([st[k] for k in names]); LAG = lag_matrix(Mx, P, T)
    PM = {'tr': yrs <= 2023, 'te': yrs >= 2024, 'y26': yrs == 2026}
    rows = []
    for k, nm in enumerate(names):
        r = {'strip': nm}
        for lab, m in PM.items():
            A = Mx[k]; known = A[m] != 0
            acc = ((A[m] == leg[m]) & known).sum() / max(known.sum(), 1)
            fl = (A[1:] != A[:-1])[m[1:]].sum() / (m.sum() / 250)
            sel = [m[i] for i, Dn, d, t in P]; L = LAG[k, sel]
            r[f'{lab}_acc'] = round(acc * 100); med = np.nanmedian(L) if (~np.isnan(L)).any() else np.nan
            r[f'{lab}_lag'] = None if np.isnan(med) else float(med); r[f'{lab}_flips'] = round(float(fl), 1); r[f'{lab}_miss'] = int(np.isnan(L).sum())
        r['turns26'] = ' · '.join(f"{d.month}/{d.day} {'고점' if t == 'P' else '바닥'} " + ('놓침' if np.isnan(LAG[k, j]) else f'{int(LAG[k, j]):+d}')
                                  for j, (i, Dn, d, t) in enumerate(P) if d.year == 2026)
        rows.append(r)
    T_ = pd.DataFrame(rows)
    T_['rule'] = ['외국인 5일 순매수 상·하위 10% + 큰 하루 전환 2개(ATR25: 상승 1.4배·1.0배 / 하락 1.5배) 중 2개 이상', '종가 > 67일 지수이동평균',
                  'ADX10>30 방향 + 67일선 + EMA12>EMA55 중 2개 이상', 'ATR7 추적 + 8/22일선 + 외국인 60일(역) 중 2개 이상', '외국인 1일 상위 20% + 개인 10일 하위 20%(역) + 52/95일선 중 2개 이상']
    T_['note'] = ['2015~2023에서만 골라 2024~2026에 확인', '고정 규칙', '고정 규칙', '2026년 보고 고름(올해는 사후 결과)', '2026년 수익률로 고름(올해는 사후 결과)']
    return T_

def trend_years(D, fixed_csv, end):
    """11년 표: pivots·always_up·fast·ema67·vote3·combo 는 다시 계산, wf3·wf·wf_pick(연도별 검증)은 고정값."""
    idx, st = strips(D); K = D['K']; c = K.close
    m = idx <= pd.Timestamp(end); idx2 = idx[m]
    piv = zigzag(c[m], 0.10); leg = leg_new_dir(idx2, piv)
    yrs = idx2.year; Yr = sorted(set(yrs))
    # 이 표의 67일선·조합 열은 처음 계산할 때 쓴 판을 그대로 따른다(2015~2016만 영향):
    #   67일선 = EMA67 pandas 기본값(adjust=True), 조합 = 외국인 60일 분위를 최소 250일 누적으로 계산
    t = st.copy(); H = K.high.fillna(c); L_ = K.low.fillna(c); fo = D['F'].foreign.reindex(idx)
    t['67일선'] = np.sign(c - c.ewm(span=67).mean()).values
    a7 = true_range(c, H, L_).rolling(7).mean()
    s_atr = hyst(idx, c > (c.rolling(7).min() + a7).shift(1), c < (c.rolling(7).max() - a7).shift(1), fill0=False)
    s_ma = np.sign(c.rolling(8).mean() - c.rolling(22).mean()); f60 = fo.rolling(60).sum()
    s_f = hyst(idx, f60 < f60.expanding(250).quantile(.3), f60 > f60.expanding(250).quantile(.7), fill0=False)
    v = np.sign(s_atr.fillna(0) + s_ma.fillna(0) + s_f.fillna(0)); v[v == 0] = np.nan; t['조합'] = v.ffill().fillna(0).values
    acc = {k: pd.Series(t[k][m] == leg.values, index=idx2).groupby(yrs).mean() for k in ('빠른 전환', '67일선', '3개 다수결', '조합')}
    F = pd.read_csv(fixed_csv, dtype=str, keep_default_na=False).set_index('year'); rows = []
    for y in Yr:
        lab = f"{y}(1~{idx2[yrs == y].max().month}/{idx2[yrs == y].max().day})" if y == idx2.max().year and idx2.max().month < 12 else str(y)
        fx = F.loc[lab] if lab in F.index else None
        rows.append({'year': lab, 'pivots': sum(1 for d, t in piv if d.year == y), 'always_up': round((leg[yrs == y] == 1).mean() * 100),
                     'fast': round(acc['빠른 전환'][y] * 100), 'ema67': round(acc['67일선'][y] * 100), 'vote3': round(acc['3개 다수결'][y] * 100),
                     'combo': round(acc['조합'][y] * 100), 'wf3': fx['wf3'] if fx is not None else '', 'wf': fx['wf'] if fx is not None else '',
                     'wf_pick': fx['wf_pick'] if fx is not None else ''})
    fa = F.loc['평균']
    rows.append({'year': '평균', 'pivots': len(piv), 'always_up': round((leg == 1).mean() * 100), 'fast': round(acc['빠른 전환'].mean() * 100),
                 'ema67': round(acc['67일선'].mean() * 100), 'vote3': round(acc['3개 다수결'].mean() * 100), 'combo': round(acc['조합'].mean() * 100),
                 'wf3': fa['wf3'], 'wf': fa['wf'], 'wf_pick': fa['wf_pick']})
    return pd.DataFrame(rows)

# ----------------------------------------------------------------------------- 5. 매매 검증(대화에서 보고한 수익률)
def backtest(D, alarms_df, start, end, sell_t, buy_t, start_hold, fee=0.0015):
    """신호 다음 날 시가에 매매, 한쪽 0.15%(왕복 0.3%) 비용. 보유 중 매수 신호·현금 중 매도 신호는 무시."""
    K = D['K']; K = K[(K.index >= pd.Timestamp(start)) & (K.index <= pd.Timestamp(end))]
    op, cl = K.open.fillna(K.close.shift(1)), K.close; days = K.index
    A = alarms_df.assign(date=pd.to_datetime(alarms_df.date))
    S = set(A[(A.side == '매도') & (A.type == sell_t)].date); B = set(A[(A.side == '매수') & (A.type == buy_t)].date)
    hold = start_hold; units = (1 - fee) / op.iloc[0] if hold else 0; cash = 1.0; val = []
    for i, d in enumerate(days):
        val.append(units * cl[d] if hold else cash)
        if i + 1 == len(days): break
        nx = days[i + 1]
        if not hold and d in B: units = cash * (1 - fee) / op[nx]; hold = True
        elif hold and d in S: cash = units * op[nx] * (1 - fee); hold = False
    v = pd.Series(val, index=days)
    return (v.iloc[-1] - 1) * 100, ((v / v.cummax()) - 1).min() * 100

def backtest_report(D, al):
    out = []; T = ['민감형', '중간형', '엄격형']
    for (a, b, lab) in (('2026-01-01', '2026-10-20', '2026년(1/2 시가~10/20 종가)'), ('2025-01-01', '2025-12-31', '2025년'), ('2015-01-01', '2025-12-31', '2015~2025년')):
        K = D['K']; k = K[(K.index >= a) & (K.index <= b)]
        bh = (k.close.iloc[-1] / k.open.iloc[0] * (1 - 0.0015) - 1) * 100; bh0 = (k.close.iloc[-1] / k.open.iloc[0] - 1) * 100
        out.append(f'## {lab} — 그냥 보유 {bh:+.1f}% (매수 비용 빼기 전 {bh0:+.1f}%)')
        for s in T:
            for bb in T:
                r1, d1 = backtest(D, al, a, b, s, bb, False); r2, d2 = backtest(D, al, a, b, s, bb, True)
                out.append(f'매도 {s} + 매수 {bb}: 현금 시작 {r1:+.1f}% (최대 낙폭 {d1:.1f}%) | 보유 시작 {r2:+.1f}% (최대 낙폭 {d2:.1f}%)')
    return '\n'.join(out)

def repaint_check(D):
    """번복 검사: 2026년 거래일마다 그날까지의 자료만으로 신호를 다시 계산해 전체 자료로 계산한 신호와 비교."""
    full = signal_series(D); days = D['K'].index[D['K'].index >= Y0]; changed = 0; fired = 0
    for cut in days:
        Dc = {k: (v[v.index <= cut] if k in ('K', 'V', 'F', 'L', 'C') else v) for k, v in D.items()}
        part = signal_series(Dc)
        for key, A in part.items():
            changed += int((A != full[key][:cut]).sum()); fired += int(A.iloc[-1])
    return f'## 번복 검사 — 2026년 거래일 {len(days)}개 시점: 과거 신호가 바뀐 경우 {changed}건, 그날 켜진 신호 합계 {fired}개'


# ----------------------------------------------------------------------------- 재진입 조합(헛신호 때 다시 사고팔기)
RE_RULE = {'재매수': '판 뒤(엄격형 매도 또는 재매도) RSI14 > 60이면 다시 산다',
           '재매도': '산 뒤(엄격형 매수·재매수·처음 보유) 10거래일부터 10일선 < 104일선이면 다시 판다'}
def reentry(D):
    """재진입 조합(2015~2026 탐색 추천 B): 엄격형 매도 → 현금, 엄격형 매수 → 보유, 현금일 때 RSI14>60 → 재매수,
    보유 10거래일 뒤부터 SMA10<SMA104 → 재매도. 그날 장 마감 값으로 판단(매매는 다음 날 시가). 2015-01-02 보유로 시작."""
    c = D['K'].close; idx = c.index; T = len(c); S = signal_series(D)
    sell = S[('매도', '엄격형')].values.astype(bool); buy = S[('매수', '엄격형')].values.astype(bool)
    dlt = c.diff(); gain = dlt.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean(); loss = (-dlt.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rsi = 100 - 100 / (1 + gain / loss); rb = (rsi > 60).values
    s10, s104 = c.rolling(10).mean(), c.rolling(104).mean(); rs = ((~(s10 > s104)) & s10.notna() & s104.notna()).values
    # 큰 전환 판정(alarms와 같은 방식)
    piv = zigzag(c, 0.10)
    legs = list(zip(piv[:-1], piv[1:])); last = piv[-1]
    legs.append((last, (c[last[0]:].idxmin(), 'T')) if last[1] == 'P' else (last, (c[last[0]:].idxmax(), 'P')))
    win = {'매도': {}, '매수': {}}; inleg = {'매도': pd.Series(False, index=idx), '매수': pd.Series(False, index=idx)}
    for (d1, t1), (d2, t2) in legs:
        side = '매도' if t1 == 'P' else '매수'; inleg[side][d1:d2] = True
        move = (c[d2] / c[d1] - 1) * 100
        if abs(move) < 15: continue
        i = idx.get_loc(d1); end = i; lvl = c[d1] * (0.95 if side == '매도' else 1.05)
        ok = (lambda v: v > lvl) if side == '매도' else (lambda v: v < lvl)
        while end + 1 < T and ok(c.iloc[end + 1]): end += 1
        for t in range(max(0, i - 10), end + 1):
            if (c.iloc[t] >= lvl) if side == '매도' else (c.iloc[t] <= lvl):
                win[side][idx[t]] = f"큰 {'하락' if side == '매도' else '상승'} 직전({d1.month}/{d1.day} {'고점' if side == '매도' else '바닥'} → {move:+.1f}%)"
    pos, reason, since = 1, 0, 0; ev = []                    # reason: 0 처음 보유, 1 매도 신호, 2 매수 신호, 3 재매수, 4 재매도
    for t in range(T):
        if t > 0: since += 1
        act = None; why = ''
        if pos == 1:
            if sell[t]: pos, reason, since, act, why = 0, 1, 0, '매도 신호', '엄격형 매도 신호'
            else:
                if buy[t]: reason, since = 2, 0
                if reason in (0, 2, 3) and since >= 10 and not buy[t] and rs[t]:
                    why = '엄격형 매수 헛신호 판정' if reason == 2 else ('재매수 뒤 하락' if reason == 3 else '보유 중 하락')
                    pos, reason, since, act = 0, 4, 0, '재매도'
        else:
            if buy[t]: pos, reason, since, act, why = 1, 2, 0, '매수 신호', '엄격형 매수 신호'
            else:
                if sell[t]: reason, since = 1, 0
                if reason in (1, 4) and not sell[t] and rb[t]:
                    why = '엄격형 매도 헛신호 판정' if reason == 1 else '재매도 뒤 회복'
                    pos, reason, since, act = 1, 3, 0, '재매수'
        if act: ev.append((t, act, why, pos))
    rows = []
    for k, (t, act, why, p) in enumerate(ev):
        d = idx[t]; fut = c.iloc[t + 1:t + 21]
        up = round((fut.max() / c.iloc[t] - 1) * 100, 1) if len(fut) else np.nan
        dn = round((fut.min() / c.iloc[t] - 1) * 100, 1) if len(fut) else np.nan
        side = '매수' if p == 1 else '매도'
        if d in win[side]: res = win[side][d]
        elif side == '매도': res = '10% 이상 하락 앞' if dn <= -10 else ('하락 구간 중' if inleg['매도'][d] else ('판정 전' if len(fut) < 20 else '헛경보'))
        else: res = '20일 안 10% 이상 상승' if up >= 10 else ('상승 구간 중' if inleg['매수'][d] else ('판정 전' if len(fut) < 20 else '헛신호'))
        if side == '매수' and dn <= -10 and d not in win[side]: res += ' · 이후 10% 넘게 더 하락'
        t2 = ev[k + 1][0] if k + 1 < len(ev) else T - 1
        rows.append({'date': d.strftime('%Y-%m-%d'), 'action': act, 'reason': why, 'state': '보유' if p == 1 else '현금', 'kospi': round(c.iloc[t], 2),
                     'up20': '' if np.isnan(up) else up, 'dn20': '' if np.isnan(dn) else dn, 'result': res,
                     'held_days': int(t2 - t), 'held_chg_pct': round((c.iloc[t2] / c.iloc[t] - 1) * 100, 1), 'open_end': '' if k + 1 < len(ev) else '진행 중',
                     'rule': RE_RULE.get(act, '대시보드 엄격형 신호')})
    return pd.DataFrame(rows)

# ----------------------------------------------------------------------------- 야간선물 → 다음 날 시초가
NIGHT_EDGES = [-2, -1, -0.5, -0.25, 0, 0.25, 0.5, 1, 2]
NIGHT_LABELS = ['−2% 이하', '−2~−1%', '−1~−0.5%', '−0.5~−0.25%', '−0.25~0%', '0~+0.25%', '+0.25~+0.5%', '+0.5~+1%', '+1~+2%', '+2% 이상']
def night_fut(D):
    """한국 t일 장 마감 뒤 야간장(끝난 날 = 다음 거래일 t1) 종가의 직전 주간 종가 대비 등락과 t1 시초가 갭(코스피, t일 종가 대비)."""
    N, K = D['NF'], D['K']
    if N is None or not len(N): return None
    idx = K.index; rows = []
    for i, t in enumerate(idx):
        if t < N.index[0] - pd.Timedelta(days=7): continue
        t1 = idx[i + 1] if i + 1 < len(idx) else None
        if t1 is not None:
            if t1 not in N.index: continue
            r = N.loc[t1]
        else:
            later = N.index[N.index > t]
            if not len(later): continue
            r = N.loc[later[0]]; t1n = later[0]
        dc = round(float(r['종가'] - r['대비']), 2)
        rows.append({'date': t.strftime('%Y-%m-%d'), 'night_date': (t1 if t1 is not None else t1n).strftime('%Y-%m-%d'), 'contract': r['월물'],
                     'night_close': float(r['종가']), 'day_close': dc,
                     'night_pct': round((float(r['종가']) / dc - 1) * 100, 2), 'night_high_pct': round((float(r['고가']) / dc - 1) * 100, 2), 'night_low_pct': round((float(r['저가']) / dc - 1) * 100, 2),
                     'volume': int(r['거래량']) if pd.notna(r['거래량']) else None,
                     'gap_next': round((float(K.loc[t1, 'open']) / float(K.loc[t, 'close']) - 1) * 100, 2) if t1 is not None else np.nan,
                     'source': r['원본 파일']})
    out = pd.DataFrame(rows); out['volume'] = out['volume'].astype('Int64')
    return out

def night_bucket(x):
    for k, e in enumerate(NIGHT_EDGES):
        if x <= e: return k
    return len(NIGHT_EDGES)

def gap_table(nf):
    """야간 등락 구간별: 날 수, 다음 날 시초가 상승 비율, 방향 일치(야간 부호 = 시초가 부호), 오를 때·내릴 때 중앙값, 갭 중앙값·10%·90%."""
    h = nf[nf.gap_next.notna()].copy(); h['b'] = [night_bucket(x) for x in h.night_pct]
    lo = [np.nan] + NIGHT_EDGES; hi = NIGHT_EDGES + [np.nan]; rows = []
    def stats(g, label, a, b):
        x = g.gap_next.values; up, dn = x[x > 0], x[x < 0]
        return {'bucket': label, 'lo': a, 'hi': b, 'n': int(len(x)),
                'p_up': round(float(np.mean(x > 0)), 3) if len(x) else np.nan,
                'hit': round(float(np.mean(np.sign(g.night_pct.values) == np.sign(x))), 3) if len(x) else np.nan,
                'med_up': round(float(np.median(up)), 2) if len(up) else np.nan, 'med_dn': round(float(np.median(dn)), 2) if len(dn) else np.nan,
                'med_gap': round(float(np.median(x)), 2) if len(x) else np.nan,
                'q10': round(float(np.quantile(x, 0.1)), 2) if len(x) else np.nan, 'q90': round(float(np.quantile(x, 0.9)), 2) if len(x) else np.nan,
                'night_med': round(float(np.median(g.night_pct.values)), 2) if len(x) else np.nan}
    for k, lab in enumerate(NIGHT_LABELS): rows.append(stats(h[h.b == k], lab, lo[k], hi[k]))
    rows.append(stats(h, '전체', np.nan, np.nan))
    out = pd.DataFrame(rows); out['period'] = f"{h.date.iloc[0]} ~ {h.date.iloc[-1]}" if len(h) else ''
    return out

# ----------------------------------------------------------------------------- 실행
if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('xlsx'); ap.add_argument('out'); ap.add_argument('--trend-end', default='2026-10-20')
    ap.add_argument('--fixed', default=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'datasets'))
    a = ap.parse_args(); os.makedirs(a.out, exist_ok=True)
    D = load(a.xlsx)
    outs = {'market_daily': market_daily(D), 'liq_daily': liq_daily(D), 'credit': credit(D), 'monthly': monthly(D), 'flows_daily': flows_daily(D),
            'lag': lag_table(D), 'fut_daily': fut_daily(D), 'etf_lev': etf_lev(D)}
    al = alarms(D); outs['alarms'] = al
    outs['combo'] = combo_csv(D); outs['lead_cmp'] = lead_cmp(D)
    outs['trend_years'] = trend_years(D, os.path.join(a.fixed, 'trend_years.csv'), a.trend_end)
    outs['reentry'] = reentry(D)
    outs['buy3'] = buy3(D)
    outs['sell3'] = sell3(D)   # opt_gauge(D)는 게이지 띠를 뺀 뒤(v59) 쓰지 않음
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import quant; outs.update(quant.run(D))   # 8. 정밀 검증(2015~, 3년 학습·연도별 검증): q_daily, q_models, q_years, q_strat, q_sens, q_ic, q_now
    # 큰 흐름 비교: 해마다 그해 가장 잘 맞은 1위 조합(champ.py). 확정된 해는 지난 결과(out/ 또는 패키지 datasets/)의 조합을 다시 씀
    import champ
    _c = D['K'].close; _leg = leg_new_dir(_c.index, zigzag(_c, 0.10)); _prev = None
    for _p in (os.path.join(a.out, 'trend_champ_rules.csv'), os.path.join(a.fixed, 'trend_champ_rules.csv')):
        if os.path.exists(_p): _prev = pd.read_csv(_p, dtype=str, keep_default_na=False); break
    outs.update(champ.run(D, _leg, _prev))
    _cr = outs['trend_champ_rules'].set_index('year')['acc_year']
    outs['trend_years']['champ'] = [(_cr.get(str(y)[:4], '') if str(y)[:4].isdigit() else (round(float(_cr.mean()), 1) if len(_cr) else '')) for y in outs['trend_years']['year']]
    import combo_track; outs.update(combo_track.run(D, outs.get('q_daily')))   # 매수×매도 신호 49개 조합 성적표·걸어가며 검증·지금 1위(combo_table, combo_select, combo_wf, combo_now)
    nf = night_fut(D)
    if nf is not None: outs['night_fut'] = nf; outs['gap_table'] = gap_table(nf)
    for k, v in outs.items(): v.to_csv(os.path.join(a.out, k + '.csv'), index=False)
    open(os.path.join(a.out, 'checks.txt'), 'w').write(backtest_report(D, al) + '\n' + repaint_check(D) + '\n')
    print('written:', ', '.join(sorted(outs)), '+ checks.txt ->', a.out)
