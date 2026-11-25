# -*- coding: utf-8 -*-
"""전체 종목 재선별: 안정 관찰·점수 순위·방어1 성장 조건 (stocks_daily.py 가 불러 씀).

안정 관찰 (watch.py 와 같은 식)
  대상: 기준일 시총 1,000억 원 이상, 스팩·ETF·리츠 등과 우선주 제외, 최근 104주 중 50주 이상 거래,
        최근 13주 중 등락률 0 인 주 4개 미만, 52주 거래대금/시총 하위 20% 제외, 과거 급락 기록 10번 이상
  점수: 1년 변동성 낮음·2년 베타 낮음·과거 급락 덜 빠진 비율 백분위의 같은 비중 평균
점수 순위
  대상(분석 대상): 2024-11-15 이전 상장(그날 시총 단면에 있음), 기준일 시총 500억 원 이상,
        최근 20거래일 이상(주 단위) 하루 평균 거래대금 1억 원 이상, 스팩·ETF·리츠 등 제외(우선주 포함)
  종합 = (수급 가중 점수 × 5 + 위험·가치 체크리스트(4개 × 25점) × 5) ÷ 10
  수급 가중 점수: 수급·보유 지표 20개(flowtraits)를 대상 안 백분위로 바꿔 학습 구분력(AUC−0.5)만큼 가중 평균
        (원래 다음 금융 종목별 수급 → KRX 투자자별 일별 순매수·월말 외국인 보유율로 같은 정의 재구성)
  체크리스트: 베타(2024-11-15 이후 일간, 같은 시장 지수) 0.6 미만, 배당 2% 이상, 2022~2025 4년 흑자, PBR 1.2 미만
방어1 성장 조건
  분석 대상 중 2024-11-15 종가 대비 수익률 +30% 이상, 2025년·올해 수익률 모두 플러스
"""
import os, json, numpy as np, pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__)); RAW = os.path.join(ROOT, 'raw'); REFD = os.path.join(ROOT, 'ref')
EXCL = '스팩|SPAC|리츠|ETN|ETF|KODEX|TIGER|기업인수목적|인프라|맥쿼리|선박|부동산투자'
PREF_RE = r'우$|우B$|우C$|\d우'
FLOW_KEYS = ['fr', 'fr_dW', 'fr_d6', 'fr_off', 'inst', 'frgn', 'big', 'big6', 'inst6', 'frgn6', 'big_mpos', 'inst_mpos', 'frgn_mpos',
             'big_streak', 'big_last6', 'fr_mup', 'big_wpos', 'crash_buy', 'crash_net', 'big_tv']
# 지표 정의에 쓰는 기간(11/16 원래 점수와 맞춰 확인한 값)
#  누적 순매수('1년' 이름의 지표)·주 비율·하락일 매수: 기준일이 든 주까지 79주(11/16 기준 2025-05-19부터)
#  6개월: 27주, 달 비율·연속·최근 6달: 이번 달을 뺀 18달
WIN_WEEKS, H6_WEEKS, WIN_MONTHS = 79, 27, 18
CRASH_TH = -0.02


def rd(p):
    f = os.path.join(RAW, p)
    if not os.path.exists(f): return None
    d = pd.read_csv(f, compression='gzip', index_col=0); d.index = d.index.astype(str).str.zfill(6); return d


def pct(s, hi=True):
    """대상 안 백분위(0~100, 같은 값은 평균 순위)."""
    r = s.rank(pct=True, method='average') * 100
    return r if hi else 100 - r + (100 / s.notna().sum() if s.notna().sum() else 0)


def amt(x):
    try: return float(str(x).replace(',', ''))
    except Exception: return np.nan


class Static:
    """매일 바뀌지 않는 자료: 과거 급락 기록, 연도별 수익률, OpenDART 영업이익·자본·배당, 2024-11-15 상장 여부."""
    def __init__(self):
        P = pd.read_csv(os.path.join(ROOT, 'stable', 'panel.csv.gz'), dtype={'code': str, 'peak': str}); P['code'] = P['code'].str.zfill(6)
        self.rec = P.groupby('code').agg(n_rec=('x', 'size'), rec_rate=('beat', 'mean'))
        l2 = P[P.peak.isin(['20260622', '20260923'])].pivot_table(index='code', columns='peak', values='ret')
        l2.columns = ['ret_0622', 'ret_0923']; self.last2 = l2
        self.yr = {}
        for y in (2022, 2023, 2024, 2025):
            parts = [rd(f'year/Y_{m}_{y}.csv.gz') for m in ('KOSPI', 'KOSDAQ')]
            s = pd.concat([p['등락률'].astype(float) for p in parts if p is not None])
            self.yr[y] = s[~s.index.duplicated()]
        self.cap0 = set()
        for m in ('KOSPI', 'KOSDAQ'):
            c0 = rd(f'd1/CAP_{m}_20241115.csv.gz')
            if c0 is not None: self.cap0 |= set(c0.index)
        # OpenDART 영업이익(연도별)·지배주주 자본
        self.op, self.eq = {}, {}
        dt = pd.read_csv(os.path.join(RAW, 'dart_op.csv.gz'), dtype=str); dt['code'] = dt.stock_code.str.zfill(6)
        dt['_p'] = (dt.fs_div != 'CFS').astype(int); dt = dt.sort_values('_p').drop_duplicates(['code', 'bsns_year'])
        for _, x in dt.iterrows():
            for k, off in (('thstrm_amount', 0), ('frmtrm_amount', 1), ('bfefrmtrm_amount', 2)):
                v = amt(x[k])
                if x.code.startswith('9'): v *= 1000
                if not np.isnan(v): self.op.setdefault(x.code, {}).setdefault(int(x.bsns_year) - off, v)
        fp = os.path.join(RAW, 'dart_fill.csv.gz')
        if os.path.exists(fp):
            fill = pd.read_csv(fp, dtype=str)
            if len(fill):
                fill['code'] = fill.stock_code.str.zfill(6); fill['_p'] = (fill.fs_div != 'CFS').astype(int)
                for kind in ('op', 'eq'):
                    f2 = fill[fill.kind == kind].sort_values(['_p']).drop_duplicates(['code', 'bsns_year'])
                    for _, x in f2.iterrows():
                        y = int(x.bsns_year)
                        for k, off in (('thstrm_amount', 0), ('frmtrm_amount', 1)):
                            v = amt(x[k])
                            if np.isnan(v): continue
                            if x.code.startswith('9'): v *= 1000
                            if kind == 'op':
                                d = self.op.setdefault(x.code, {})
                                if off == 0 or (y - off) not in d: d[y - off] = v
                            else:
                                self.eq.setdefault(x.code, {})[y - off] = v
        ap = os.path.join(RAW, 'dart_alot.csv.gz')
        self.alot = pd.read_csv(ap, dtype=str) if os.path.exists(ap) and os.path.getsize(ap) > 30 else None
        if self.alot is not None: self.alot['code'] = self.alot.stock_code.str.zfill(6)
        # 원래 분석의 업종 분류(WICS, 업종 배율용) — 없는 종목은 원래 규칙대로 중립 50
        self.wics = {r['code']: r['sector'] for r in json.load(open(os.path.join(REFD, 'composite.json')))}

    def profit(self, code):
        o = self.op.get(code, {}); yrs = [2022, 2023, 2024, 2025]
        if all(y in o for y in yrs): return int(sum(o[y] > 0 for y in yrs)), None
        have = [y for y in yrs if y in o]
        return None, (f'{len(have)}년치만({have[0]}~)' if have else '영업이익 항목 없음')

    def op2025(self, code):
        v = self.op.get(code, {}).get(2025)
        return round(v / 1e8) if v is not None else None


def load_flows(END, days, codes_by_mkt, shares, ix, V52, FR_END, log):
    """KRX 투자자별 일별 순매수·월말 외국인 보유율로 수급·보유 지표 20개."""
    end_ts = pd.Timestamp(END)
    monday = end_ts - pd.Timedelta(days=end_ts.weekday())
    wstart = (monday - pd.Timedelta(weeks=WIN_WEEKS - 1)).strftime('%Y%m%d')
    h6 = (monday - pd.Timedelta(weeks=H6_WEEKS - 1)).strftime('%Y%m%d')
    mlist = [str(end_ts.to_period('M') - k).replace('-', '') for k in range(WIN_MONTHS, 0, -1)]
    win_start = mlist[0] + '01'
    y1 = wstart
    first = min(win_start, wstart)
    dl = [d for d in days if first <= d <= END]
    out = []
    for m, codes in codes_by_mkt.items():
        Q, Vv, miss = {'외국인': {}, '기관합계': {}}, {'외국인': {}, '기관합계': {}}, []
        for d in dl:
            for w in ('외국인', '기관합계'):
                x = rd(f'nbday/{m}_{w}_{d}.csv.gz')
                if x is None: miss.append((d, w)); continue
                Q[w][d] = pd.to_numeric(x['순매수거래량'], errors='coerce'); Vv[w][d] = pd.to_numeric(x['순매수거래대금'], errors='coerce')
        if miss:
            log(f'  {m} 투자자별 일별 순매수 빠진 날 {len(miss)}건 (예 {miss[:3]})')
        F = pd.DataFrame(Q['외국인']).reindex(codes).reindex(columns=dl).fillna(0)
        I = pd.DataFrame(Q['기관합계']).reindex(codes).reindex(columns=dl).fillna(0)
        FV = pd.DataFrame(Vv['외국인']).reindex(codes).reindex(columns=dl).fillna(0)
        IV = pd.DataFrame(Vv['기관합계']).reindex(codes).reindex(columns=dl).fillna(0)
        B = F + I
        sh = shares.reindex(codes)
        cy1 = [d for d in dl if d >= wstart]; ch6 = [d for d in dl if d >= h6]; cw = [d for d in dl if d >= wstart]
        cm = [d for d in dl if d[:6] in mlist]
        o = pd.DataFrame(index=codes)
        o['inst'] = I[cy1].sum(axis=1) / sh * 100; o['frgn'] = F[cy1].sum(axis=1) / sh * 100; o['big'] = o.inst + o.frgn
        o['inst6'] = I[ch6].sum(axis=1) / sh * 100; o['frgn6'] = F[ch6].sum(axis=1) / sh * 100; o['big6'] = o.inst6 + o.frgn6
        mon = pd.Index([d[:6] for d in cm])
        MB = B[cm].T.groupby(mon.values).sum().T; MI = I[cm].T.groupby(mon.values).sum().T; MF = F[cm].T.groupby(mon.values).sum().T
        o['big_mpos'] = (MB > 0).mean(axis=1); o['inst_mpos'] = (MI > 0).mean(axis=1); o['frgn_mpos'] = (MF > 0).mean(axis=1)
        pos = (MB > 0).astype(int).values
        o['big_streak'] = [max((len(s) for s in ''.join(map(str, row)).split('0')), default=0) for row in pos]
        o['big_last6'] = (MB.iloc[:, -6:] > 0).sum(axis=1)
        wk = pd.Index(pd.to_datetime(cw).strftime('%G-%V'))
        WB = B[cw].T.groupby(wk.values).sum().T
        o['big_wpos'] = (WB > 0).mean(axis=1)
        ir = ix[m.lower()].pct_change()
        cdays = [d for d in cw if d in ir.index and ir[d] <= CRASH_TH]
        o['crash_buy'] = (B[cdays] > 0).mean(axis=1) if cdays else np.nan
        o['crash_net'] = B[cdays].sum(axis=1) / sh * 100 if cdays else np.nan
        tv = V52.reindex(codes)
        o['big_tv'] = (FV[cy1].sum(axis=1) + IV[cy1].sum(axis=1)) / tv * 100
        # 외국인 보유율(월말)
        fr_now = FR_END.reindex(codes)
        mends = sorted({d for d in dl if d >= win_start})
        ms = pd.Series(mends, index=pd.to_datetime(mends)); mend = list(ms.groupby(ms.index.to_period('M')).max())
        prev_m = (pd.Timestamp(win_start) - pd.Timedelta(days=1)).strftime('%Y%m%d')
        pre = [d for d in days if d <= prev_m]
        if pre: mend = [pre[-1]] + mend
        FRM = {}
        for d in mend:
            x = rd(f'frm/{m}_{d}.csv.gz')
            if x is not None: FRM[d] = pd.to_numeric(x['지분율'], errors='coerce')
        FRM = pd.DataFrame(FRM).reindex(codes)
        FRM[END] = fr_now
        FRM = FRM.reindex(columns=sorted(FRM.columns))
        def ago(months):
            t = (end_ts - pd.DateOffset(months=months)).strftime('%Y%m%d')
            c = [x for x in FRM.columns if x <= t]
            return FRM[c[-1]] if c else np.nan
        o['fr'] = fr_now; o['fr_dW'] = fr_now - ago(12); o['fr_d6'] = fr_now - ago(6)
        c12 = [x for x in FRM.columns if x >= (end_ts - pd.DateOffset(months=12)).strftime('%Y%m%d')]
        o['fr_off'] = fr_now - FRM[c12].max(axis=1)
        mcols = [x for x in FRM.columns if x != END or x in mend]
        o['fr_mup'] = (FRM[mcols].diff(axis=1).iloc[:, 1:] > 0).mean(axis=1)
        o['big7'] = B[[d for d in dl if d >= '20260623']].sum(axis=1) / sh * 100
        c7 = [d for d in cdays if d >= '20260623']
        o['crash_buy7'] = (B[c7] > 0).mean(axis=1) if c7 else np.nan
        out.append(o)
    return pd.concat(out)


def flow_score(FL, A):
    """학습 구분력(AUC−0.5)만큼 가중한 백분위 평균(0~100). 값이 없는 지표는 그 종목에서 빼고 평균."""
    ft = {t['key']: t for t in json.load(open(os.path.join(ROOT, 'ref', 'flowtraits.json')))}
    X = FL.reindex(A)
    num, den = 0, 0
    for k in FLOW_KEYS:
        w = ft[k]['train'] - 0.5
        p = X[k].rank(pct=True, method='average') * 100
        num = num + (p * w).fillna(0); den = den + p.notna() * w
    return (num / den).round(1)


def stable_list(CAP, NAMES, W, V, IW, wend, static):
    """안정 관찰 순위(watch.py 와 같은 식). CAP·W·V·IW 는 시장별 dict."""
    c104, c52, c13 = wend[-104:], wend[-52:], wend[-13:]
    out = []
    for m in ('KOSPI', 'KOSDAQ'):
        cap = CAP[m]; U = pd.DataFrame(index=cap.index)
        U['name'] = NAMES.reindex(U.index); U['mcap'] = cap['시가총액'].astype(float)
        nm = U.name.astype(str)
        U = U[U.name.notna() & (U.mcap >= 1e11) & ~nm.str.contains(EXCL) & ~nm.str.contains(PREF_RE)]
        w = W[m].reindex(U.index)
        U = U[(w[c104].notna().sum(axis=1) >= 50) & ((w[c13] == 0).sum(axis=1) < 4)]; w = W[m].reindex(U.index)
        X = IW[m].reindex(c104).values
        def beta(Y):
            ok = ~np.isnan(Y) & ~np.isnan(X)
            return np.cov(Y[ok], X[ok])[0, 1] / np.var(X[ok], ddof=1) if ok.sum() >= 30 else np.nan
        U['beta2y'] = [beta(w.loc[c, c104].values.astype(float)) for c in U.index]
        U['vol1y'] = w[c52].std(axis=1) * np.sqrt(52)
        U['turnover'] = V[m].reindex(U.index)[c52].sum(axis=1) / U.mcap
        U['market'] = m
        out.append(U)
    U = pd.concat(out)
    U = U[U.turnover >= U.turnover.quantile(0.2)]
    U = U.join(static.rec)
    U = U[U.n_rec >= 10]
    U['s_vol'] = (-U.vol1y).rank(pct=True) * 100; U['s_beta'] = (-U.beta2y).rank(pct=True) * 100; U['s_rec'] = U.rec_rate.rank(pct=True) * 100
    U['st_score'] = (U.s_vol + U.s_beta + U.s_rec) / 3
    U = U.sort_values('st_score', ascending=False); U['st_rank'] = range(1, len(U) + 1)
    return U


def universe_A(CAP, NAMES, V, wend, wdays, static):
    """분석 대상: 2024-11-15 이전 상장, 시총 500억 원 이상, 최근 20거래일 하루 평균 거래대금 1억 원 이상, 스팩·ETF·리츠 등 제외."""
    c4, nd = [], 0                       # 최근 거래일 20일 이상이 되도록 주를 거꾸로 모음
    for wb in reversed(wend):
        c4.append(wb); nd += wdays.get(wb, 5)
        if nd >= 20: break
    out = []
    for m in ('KOSPI', 'KOSDAQ'):
        cap = CAP[m]; U = pd.DataFrame(index=cap.index)
        U['name'] = NAMES.reindex(U.index); U['mcap'] = cap['시가총액'].astype(float); U['market'] = m
        U['tv20'] = V[m].reindex(U.index)[c4].sum(axis=1) / nd
        nm = U.name.astype(str)
        U = U[U.name.notna() & ~nm.str.contains(EXCL) & (U.mcap >= 5e10) & (U.tv20 >= 1e8) & U.index.isin(static.cap0)]
        out.append(U)
    return pd.concat(out)
