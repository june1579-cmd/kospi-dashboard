# -*- coding: utf-8 -*-
"""통합 명단(웹판 docs/stocks/stocks.json = 대시보드 datasets/merged) 매일 갱신.

매일 바뀌는 값 (가장 최근 거래일 KRX 종가 기준)
  종가·시총·PBR·PER·배당·외국인 보유율, 공매도 잔고 비중(KRX 공표가 2거래일 늦어 공표된 가장 최근 날),
  올해 수익률(KRX 수정 등락률), 1년·2년 수익률·변동성·베타(KRX 주간 수정 등락률 52·104주), 2년 최대 낙폭(KRX 일별 수정 종가, 조사 기간 시작 직전 종가부터 전고점 대비),
  방어1 세부 점수 5개·종합·순위(원래 식 그대로, 그날 성장 종목 250개 분포를 백분위 기준으로)
고정 값 (11/16 연구 결과)
  세 명단 소속, 안정 순위·점수, 점수 순위(sc_), 급락 기록(rec_rate·n_rec·ret_0622·ret_0923), 2022~2025 수익률,
  흑자 연수·2025 영업이익, 방어1 성장 조건 250종목 구성, 급락 7구간 성적(11/16까지 구간)
자료는 pykrx(KRX 로그인)만 쓴다. 비밀값은 출력하지 않는다.

실행: python stocks_daily.py                 # KRX에서 받아 계산 (GitHub Actions)
      python stocks_daily.py --local 20261116  # 이미 받은 raw/ 자료로 계산만 (점검용)
"""
import os, sys, json, time, traceback, datetime as dt
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import screen as SCR

ROOT = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(ROOT, 'raw'); REFD = os.path.join(ROOT, 'ref'); OUT = os.path.join(ROOT, 'stocks_out')
CACHE = os.environ.get('STOCKS_CACHE', '/tmp/stocks_cache')
KST = dt.timezone(dt.timedelta(hours=9))
LOCAL = '--local' in sys.argv
LOG, WARN = [], []
SECRETS = [v for k, v in os.environ.items() if k in ('KRX_API_KEY', 'KRX_ID', 'KRX_PW') and v]
D_START = '20241001'      # 일별 수정 종가 시작(방어1 창 2024-11-15 시작·급락 1구간 2024-10-29 포함)
W0 = '20241115'           # 방어1 베타·최대 낙폭·급락일 창 시작
PREF = {'005935': '005930', '010955': '010950', '02826K': '028260', '03473K': '034730', '078935': '078930'}


def pref_base(c, name):
    """우선주면 보통주 코드(끝자리를 0으로)."""
    if c in PREF: return PREF[c]
    if name and __import__('re').search(SCR.PREF_RE, str(name)): return c[:5] + '0'
    return None


def log(*a):
    s = ' '.join(str(x) for x in a)
    for v in SECRETS:
        s = s.replace(v, '***')
    print(s, flush=True); LOG.append(s)


def warn(s):
    WARN.append(s); log('주의:', s)


def num(x):
    try:
        v = float(x)
        return None if np.isnan(v) or np.isinf(v) else v
    except Exception:
        return None


# ------------------------------------------------------------------ 자료 받기
class Src:
    """KRX 원자료. 받은 것은 CACHE 에 저장하고, 같은 실행 안에서 다시 묻지 않는다."""
    def __init__(self):
        os.makedirs(CACHE, exist_ok=True)
        if not LOCAL:
            from pykrx import stock
            from pykrx.website import krx
            self.stock, self.krx = stock, krx

    def _get(self, name, fn, tries=4, sleep=0.5, need=None):
        f = os.path.join(CACHE, name + '.csv.gz')
        if os.path.exists(f):
            return pd.read_csv(f, compression='gzip', index_col=0)
        for k in range(tries):
            try:
                d = fn(); time.sleep(sleep)
                if d is None: d = pd.DataFrame()
                if need and (d.empty or need not in d.columns):
                    raise ValueError(f'빈 표 또는 {need} 칸 없음')
                d.to_csv(f, compression='gzip')
                return pd.read_csv(f, compression='gzip', index_col=0)
            except Exception as e:
                log(f'  실패 {name} ({k + 1}/{tries}): {type(e).__name__} {str(e)[:150]}')
                time.sleep(8 * (k + 1))
        return None

    @staticmethod
    def _codes(d):
        if d is not None and len(d):
            d.index = d.index.astype(str).str.zfill(6)
        return d

    def index(self, end_max):
        if LOCAL:
            ix = pd.read_csv(os.path.join(RAW, 'index_daily.csv.gz'), dtype={'date': str}).set_index('date')
            return ix[ix.index <= end_max][['kospi', 'kosdaq']].astype(float)
        a = (dt.datetime.strptime(D_START, '%Y%m%d') - dt.timedelta(days=10)).strftime('%Y%m%d')
        out = {}
        for tk, nm in (('1001', 'kospi'), ('2001', 'kosdaq')):
            d = self._get(f'IDX_{nm}_{end_max}', lambda tk=tk: self.krx.get_index_ohlcv_by_date(a, end_max, tk))
            if d is None or d.empty:
                raise RuntimeError(f'지수 {nm} 못 받음')
            d.index = pd.to_datetime(d.index).strftime('%Y%m%d')
            out[nm] = d['종가'].astype(float)
        return pd.DataFrame(out).dropna()

    def day_all(self, day, m):
        """그날 전종목 시세(KRX). 등락률은 KRX 기준가(액면분할·증자 반영) 대비라 이어 곱하면 수정 종가가 된다.
        저장소 raw/dailyall 에 남겨 다음 실행은 새 날짜만 받는다. (네이버 수정주가는 2026-08 이후 종가가 확정 종가와 달라 쓰지 않음)"""
        p = os.path.join(RAW, 'dailyall', f'{m}_{day}.csv.gz')
        if os.path.exists(p):
            return self._codes(pd.read_csv(p, compression='gzip', index_col=0))
        if LOCAL:
            return None
        d = self._codes(self._get(f'DA_{m}_{day}', lambda: self.stock.get_market_ohlcv_by_ticker(day, m), sleep=0.3, need='등락률'))
        if d is None or d.empty:
            return None
        d = d[['종가', '등락률']]
        os.makedirs(os.path.dirname(p), exist_ok=True)
        d.to_csv(p, compression='gzip')
        return d

    def snap(self, kind, m, day):
        if LOCAL:
            sub = 'd1' if kind == 'NB' else 'snap'
            f = os.path.join(RAW, sub, f'{kind}_{m}_{day}.csv.gz')
            return self._codes(pd.read_csv(f, compression='gzip', index_col=0)) if os.path.exists(f) else None
        fn = {'CAP': self.stock.get_market_cap_by_ticker, 'FUND': self.stock.get_market_fundamental_by_ticker,
              'FR': self.stock.get_exhaustion_rates_of_foreign_investment_by_ticker, 'SHORT': self.stock.get_shorting_balance_by_ticker,
              'SECT': self.stock.get_market_sector_classifications}[kind]
        return self._codes(self._get(f'{kind}_{m}_{day}', lambda: fn(day, m)))

    def netbuy(self, m, who, a, end):
        if LOCAL:
            return self.snap('NB', m, f'{who}_{a}_{end}')
        return self._codes(self._get(f'NB_{m}_{who}_{a}_{end}', lambda: self.stock.get_market_net_purchases_of_equities_by_ticker(a, end, m, who)))

    def pc(self, a, b, m, keep=None):
        """a(포함)~b 전종목 수정 등락률(KRX). keep=파일 경로면 저장소 raw/ 에 남김(끝난 주처럼 다시 안 바뀌는 것)."""
        if keep and os.path.exists(os.path.join(RAW, keep)):
            return self._codes(pd.read_csv(os.path.join(RAW, keep), compression='gzip', index_col=0))
        if LOCAL:
            return None
        d = self._codes(self._get(f'PC_{m}_{a}_{b}', lambda: self.krx.get_market_price_change_by_ticker(a, b, m, True), need='등락률'))
        if keep and d is not None and len(d):
            os.makedirs(os.path.dirname(os.path.join(RAW, keep)), exist_ok=True)
            d.to_csv(os.path.join(RAW, keep), compression='gzip')
        return d

    def static_fr(self, m, day):
        f = os.path.join(RAW, 'd1', f'FR_{m}_{day}.csv.gz')
        return self._codes(pd.read_csv(f, compression='gzip', index_col=0)) if os.path.exists(f) else None


def latest_ok(src, kind, m, days, end, col, back=6):
    """end 부터 거꾸로 거래일을 보며 값이 들어 있는 첫 단면(공매도 잔고는 2거래일 늦게 공표)."""
    i = days.get_loc(end)
    for k in range(back + 1):
        if i - k < 0: break
        d = days[i - k]
        x = src.snap(kind, m, d)
        if x is not None and len(x) and col in x and pd.to_numeric(x[col], errors='coerce').fillna(0).abs().sum() > 0:
            return x, d
    return None, None


# ------------------------------------------------------------------ 계산
def main():
    t0 = time.time()
    static = SCR.Static()
    sec = {r['sector']: r['lift'] for r in json.load(open(os.path.join(REFD, 'sectors.json')))}
    eps = json.load(open(os.path.join(REFD, 'episodes.json')))
    src = Src()
    now = dt.datetime.now(KST)
    if LOCAL:
        end_max = sys.argv[sys.argv.index('--local') + 1]
    else:
        end_max = now.strftime('%Y%m%d')
    ix = src.index(end_max)
    # 장중에 돌면 오늘 행은 아직 종가가 아니다
    if not LOCAL and ix.index[-1] == now.strftime('%Y%m%d') and now.hour < 16:
        ix = ix.iloc[:-1]
    days = pd.Index(ix.index)
    END = days[-1]
    log('기준일', END, '· 지수 일수', len(days))
    prev = {}
    pf = os.path.join(OUT, 'meta.json')
    if os.path.exists(pf):
        prev = json.load(open(pf))
    if not LOCAL and prev.get('asof_ymd') == END and prev.get('ok') and prev.get('mode') == 'screen' and '--force' not in sys.argv:
        log('이미 같은 기준일로 만들어 둠 — 건너뜀')
        prev['checked_at'] = now.isoformat(timespec='seconds'); prev['skipped'] = True
        prev['marker'] = open(os.path.join(ROOT, 'stocks_run.txt')).read().strip() if os.path.exists(os.path.join(ROOT, 'stocks_run.txt')) else ''
        json.dump(prev, open(pf, 'w'), ensure_ascii=False, indent=1)
        return

    # 단면
    S = {}
    for m in ('KOSPI', 'KOSDAQ'):
        S[('CAP', m)], dcap = latest_ok(src, 'CAP', m, days, END, '종가', back=0)
        S[('FUND', m)], dfund = latest_ok(src, 'FUND', m, days, END, 'PBR', back=3)
        S[('FR', m)], dfr = latest_ok(src, 'FR', m, days, END, '지분율', back=3)
        S[('SHORT', m)], dsh = latest_ok(src, 'SHORT', m, days, END, '비중', back=6)
        S[('dates', m)] = dict(cap=dcap, fund=dfund, fr=dfr, short=dsh)
        S[('FR0', m)] = src.static_fr(m, '20250102')
        S[('SECT', m)] = src.snap('SECT', m, END)
        for who, a in (('기관합계', '20250102'), ('외국인', '20250102'), ('기관합계', '20260623')):
            S[('NB', m, who, a)] = src.netbuy(m, who, a, END)
        log(m, '단면 날짜', S[('dates', m)])
        if dcap != END:
            raise RuntimeError(f'{m} 시가총액 단면이 기준일 {END} 에 없음')
        for k, v in S[('dates', m)].items():
            if v is None: warn(f'{m} {k} 단면 없음')
            elif v != END and k != 'short': warn(f'{m} {k} 단면은 {v} 값')
    d_short = max(v for v in (S[('dates', 'KOSPI')]['short'], S[('dates', 'KOSDAQ')]['short']) if v) if any(S[('dates', m)]['short'] for m in ('KOSPI', 'KOSDAQ')) else None
    d_fund = S[('dates', 'KOSPI')]['fund']
    MK = ('KOSPI', 'KOSDAQ')
    mk = {}
    for m in MK:
        for c in S[('CAP', m)].index: mk.setdefault(c, m)

    # 일별 수정 종가: KRX 전종목 일별 등락률을 이어 곱하고 기준일 종가에 맞춤
    dlist = [d for d in days if d >= D_START]
    RT, CLOSE_END = {}, {}
    for m in ('KOSPI', 'KOSDAQ'):
        cols, miss = {}, []
        for k, d in enumerate(dlist):
            x = src.day_all(d, m)
            if x is None or x.empty:
                miss.append(d); continue
            cols[d] = pd.to_numeric(x['등락률'], errors='coerce')
            if d == END: CLOSE_END[m] = pd.to_numeric(x['종가'], errors='coerce')
            if (k + 1) % 100 == 0: log(f'  {m} 일별 {k + 1}/{len(dlist)} ({(time.time() - t0) / 60:.1f}분)')
        if miss:
            raise RuntimeError(f'{m} 일별 전종목 시세 {len(miss)}일 못 받음: {miss[:5]}')
        RT[m] = pd.DataFrame(cols)
    class LazyCL(dict):
        """종목별 일별 수정 종가(KRX 전종목 일별 등락률을 이어 곱하고 기준일 종가에 맞춤). 처음 물을 때 만든다."""
        def get(self, c, default=None):
            if c not in self:
                m = mk.get(c); R = RT.get(m) if m else None; v = None
                if R is not None and c in R.index:
                    r = R.loc[c]; fv = r.first_valid_index()
                    if fv is not None:
                        r = r[r.index >= fv].fillna(0) / 100
                        p = (1 + r).cumprod()
                        ce = CLOSE_END.get(m)
                        close_end = float(ce[c]) if (ce is not None and c in ce.index and ce[c] > 0) else None
                        v = p * (close_end / p.iloc[-1]) if close_end else p
                self[c] = v
            v = dict.get(self, c)
            return default if v is None else v
    CL = LazyCL()
    log('일별 전종목 시세(KRX)', {m: RT[m].shape for m in MK}, '·', dlist[0], '~', dlist[-1])

    # 주간 전종목 수정 등락률(ISO 주, 원래 연구와 같은 파일) — 끝난 주는 raw/weekly 에 남기고, 기준일이 든 주는 그날 값만
    dd = pd.to_datetime(pd.Series(days))
    grp = dd.groupby(dd.dt.strftime('%G-%V').values)
    allw = sorted(zip(grp.min().dt.strftime('%Y%m%d'), grp.max().dt.strftime('%Y%m%d')), key=lambda x: x[1])
    weeks = allw[-104:]
    wend = [b for _, b in weeks]
    wend_ix = [b for _, b in allw[-105:]]   # 지수 주간 수익률은 한 주 앞 종가부터
    W, V, NM = {}, {}, {}
    wdays = {b: int(((days >= a) & (days <= b)).sum()) for a, b in weeks}
    for m in ('KOSPI', 'KOSDAQ'):
        cols, cols_v = {}, {}
        for a, b in weeks:
            last = b == END
            x = src.pc(a, b, m, keep=None if last else f'weekly/W_{m}_{b}.csv.gz') if not (LOCAL and last) else src.pc(a, b, m, keep=f'weekly/W_{m}_{b}.csv.gz')
            if x is None or x.empty:
                raise RuntimeError(f'{m} 주간 등락률 {a}~{b} 못 받음')
            cols[b] = x['등락률'].astype(float) / 100
            if '거래대금' in x: cols_v[b] = pd.to_numeric(x['거래대금'], errors='coerce')
            if '종목명' in x: NM.update(x['종목명'].astype(str).to_dict())
        W[m] = pd.DataFrame(cols); V[m] = pd.DataFrame(cols_v)
    log('주간 등락률', len(wend), '주', wend[0], '~', wend[-1])
    bad = []
    _prev = json.load(open(os.path.join(OUT, 'stocks.json'))) if os.path.exists(os.path.join(OUT, 'stocks.json')) else []
    prev_codes = [r['code'] for r in _prev]; prev_names = {r['code']: r.get('name', r['code']) for r in _prev}
    for c in prev_codes:
        cl = CL.get(c)
        if cl is None or c not in mk: continue
        m = mk[c]
        if c not in W[m].index: continue
        s_ = cl.reindex(days).ffill()
        for a, b in weeks[-8:]:
            pa = days[days < a][-1]
            if pd.notna(s_.get(pa)) and pd.notna(s_.get(b)) and pd.notna(W[m].at[c, b]):
                if abs((s_[b] / s_[pa] - 1) - W[m].at[c, b]) > 0.006: bad.append((c, b))
    log('일별 수정 종가 ↔ KRX 주간 등락률 대조(최근 8주, 0.6%p 초과)', len(bad), '건')
    if len(bad) > 20: warn(f'일별·주간 등락률 불일치 {len(bad)}건 (예: {bad[:3]})')
    mdd_base = days[days < weeks[0][0]][-1]   # 조사 기간 시작 직전 종가(전고점 후보에 포함)
    c104, c52 = wend[-104:], wend[-52:]
    IW = {}
    for m in ('KOSPI', 'KOSDAQ'):
        s_ = ix[m.lower()]
        IW[m] = pd.Series([s_.iloc[s_.index.searchsorted(c, side='right') - 1] for c in wend_ix], index=wend_ix).pct_change().reindex(wend)
    # 올해 수익률(작년 마지막 거래일 종가 대비)·방어1 2년 수익률(2024-11-15 종가 대비) — KRX 기간 등락률
    y0 = days[days >= END[:4] + '0101'][0]
    YTD, R2 = {}, {}
    for m in ('KOSPI', 'KOSDAQ'):
        y = src.pc(y0, END, m, keep=f'year/Y_{m}_{END[:4]}.csv.gz' if LOCAL else None)
        if y is None:
            raise RuntimeError(f'{m} 올해 기간 등락률 못 받음')
        YTD[m] = y['등락률'].astype(float)
    # 방어1 2년 수익률(2024-11-15 종가 대비): KRX 기간 등락률은 2년 넘는 구간을 거부하므로 KRX 일별 수정 종가로 계산
    b0 = days[days < '20241118'][-1]
    def r2_of(c):
        cl = CL.get(c)
        return float((cl.iloc[-1] / cl[b0] - 1) * 100) if (cl is not None and b0 in cl.index and cl.index[-1] == END) else None

    def common(c, m):
        f = {}
        if c not in W[m].index:
            return f
        w = W[m].loc[c]
        r104, r52 = w.reindex(c104), w.reindex(c52)
        X = IW[m].reindex(c104).values; Y = r104.values.astype(float); ok = ~np.isnan(X) & ~np.isnan(Y)
        g = (1 + r104.fillna(0)).cumprod()
        f['vol1y'] = float(r52.std() * np.sqrt(52) * 100) if r52.notna().sum() >= 26 else None
        f['beta2y'] = float(np.cov(Y[ok], X[ok])[0, 1] / np.var(X[ok], ddof=1)) if ok.sum() >= 30 else None
        f['mdd2y_weekly'] = float((g / g.cummax() - 1).min() * 100)
        cl = CL.get(c)
        if cl is not None:
            s_ = cl[cl.index >= mdd_base]
            dd_ = s_ / s_.cummax() - 1; t = dd_.idxmin()
            f['mdd2y'] = float(dd_.min() * 100)
            f['mdd2y_peak'] = s_[:t].idxmax(); f['mdd2y_trough'] = t
        f['ret2y'] = float((g.iloc[-1] - 1) * 100) if r104.notna().sum() >= 90 else None
        f['ret1y'] = float(((1 + r52.fillna(0)).prod() - 1) * 100)
        f['ret_ytd'] = float(YTD[m][c]) if c in YTD[m].index else None
        return f

    def d1feat(c, m):
        f = {}
        cl = CL.get(c)
        if cl is None:
            return f
        s_ = ix[m.lower()]; s_ = s_[s_.index >= W0]
        cw = cl[cl.index >= W0]; j = cw.index.intersection(s_.index)
        rs, ri = cw[j].pct_change().dropna(), s_[j].pct_change().dropna()
        if len(rs) > 100:
            f['beta'] = float(np.cov(rs, ri)[0, 1] / np.var(ri, ddof=1))
            g = cw[j]; f['mdd'] = float((g / g.cummax() - 1).min() * 100)
            cd = ri[ri <= -0.03].index
            f['crash_day_beat'] = float((rs[cd] > ri[cd]).mean() * 100) if len(cd) else None
        b = []
        for e in eps:
            st_, en_ = e['start'].replace('-', ''), e['end'].replace('-', '')
            c0, c1 = cl[cl.index <= st_], cl[cl.index <= en_]
            if len(c0) and len(c1) and c0.index[-1] == st_ and c1.index[-1] == en_:
                b.append((c1.iloc[-1] / c0.iloc[-1] - 1) * 100 - (e['med_kospi'] if m == 'KOSPI' else e['med_kosdaq']))
        if b:
            f['beats'] = int(sum(x > 0 for x in b)); f['excess_avg'] = float(np.mean(b))
        f['ret2y_d1'] = r2_of(c)
        cap = S[('CAP', m)]
        sh = float(cap.at[c, '상장주식수']) if cap is not None and c in cap.index else None
        def nb(who, a):
            x = S[('NB', m, who, a)]
            return float(x.at[c, '순매수거래량']) / sh * 100 if (x is not None and sh and c in x.index) else None
        f['inst'] = nb('기관합계', '20250102'); f['frgn'] = nb('외국인', '20250102'); f['inst_crash'] = nb('기관합계', '20260623')
        fr, fr0 = S[('FR', m)], S[('FR0', m)]
        f['frgn_ratio'] = float(fr.at[c, '지분율']) if fr is not None and c in fr.index else None
        f['frc'] = f['frgn_ratio'] - float(fr0.at[c, '지분율']) if (f['frgn_ratio'] is not None and fr0 is not None and c in fr0.index) else None
        return f

    os.makedirs(OUT, exist_ok=True)
    asof = f'{END[:4]}-{END[4:6]}-{END[6:]}'
    NAMES = pd.Series(NM)
    CAPd = {m: S[('CAP', m)] for m in MK}
    fu_all = pd.concat([S[('FUND', m)] for m in MK if S[('FUND', m)] is not None])
    fu_all = fu_all[~fu_all.index.duplicated()]
    alot = static.alot

    def fundv(c, col):
        return num(fu_all.at[c, col]) if c in fu_all.index and col in fu_all else None

    def close_of(c):
        cap = S[('CAP', mk[c])] if c in mk else None
        return float(cap.at[c, '종가']) if cap is not None and c in cap.index else None

    def val_pbr(c):
        """PBR: KRX 단면 → 우선주는 보통주 BPS → 외국 기업은 OpenDART 지배주주 자본. (값, 기준 설명)"""
        v = fundv(c, 'PBR')
        if v: return v, None
        b = pref_base(c, NAMES.get(c))
        if b:
            bps = fundv(b, 'BPS'); cl = close_of(c)
            if bps and bps > 0 and cl: return round(cl / bps, 2), '보통주 BPS 기준'
        eq = static.eq.get(c, {}).get(2025)
        cap = S[('CAP', mk[c])] if c in mk else None
        if eq and eq > 0 and cap is not None and c in cap.index:
            return round(float(cap.at[c, '시가총액']) / eq, 2), '2025년 말 지배주주 자본 기준'
        return None, None

    def val_div(c):
        """배당수익률: KRX 단면 → 없으면 OpenDART 2025 결산 주당배당금 ÷ 종가. (값, 기준 설명)"""
        if c in fu_all.index and fundv(c, 'DIV') is not None: return fundv(c, 'DIV'), None
        if alot is not None:
            cl = close_of(c)
            a = alot[(alot.code == c) & alot.se.fillna('').str.contains('주당 현금배당금') & alot.stock_knd.fillna('').str.contains('보통')]
            a2 = alot[(alot.code == c) & alot.se.fillna('').str.contains('주당 현금배당금')]
            if len(a) and cl:
                dps = SCR.amt(a.thstrm.iloc[0])
                if not np.isnan(dps): return (round(dps / cl * 100, 2) if dps > 0 else 0.0), '2025 결산 주당배당금 ÷ 기준일 종가(OpenDART)'
            elif len(a2) and a2.thstrm.fillna('-').str.strip().eq('-').all():
                return 0.0, '2025 결산 현금배당 없음(OpenDART)'
        return None, None

    def beta_daily(c):
        cl = CL.get(c); m = mk.get(c)
        if cl is None or m is None: return None
        s_ = ix[m.lower()]; s_ = s_[s_.index >= W0]
        cw = cl[cl.index >= W0]; j = cw.index.intersection(s_.index)
        rs, ri = cw[j].pct_change().dropna(), s_[j].pct_change().dropna()
        return float(np.cov(rs, ri)[0, 1] / np.var(ri, ddof=1)) if len(rs) > 100 else None

    # 0) 전체 종목 재선별
    stU = SCR.stable_list(CAPd, NAMES, W, V, IW, wend, static)
    A = SCR.universe_A(CAPd, NAMES, V, wend, wdays, static)
    shares = pd.concat([S[('CAP', m)]['상장주식수'].astype(float) for m in MK]); shares = shares[~shares.index.duplicated()]
    V52 = pd.concat([V[m].reindex(columns=c52).sum(axis=1) for m in MK]); V52 = V52[~V52.index.duplicated()]
    FR_END = pd.concat([pd.to_numeric(S[('FR', m)]['지분율'], errors='coerce') for m in MK if S[('FR', m)] is not None]); FR_END = FR_END[~FR_END.index.duplicated()]
    FL = SCR.load_flows(END, list(days), {m: [c for c in A.index if A.at[c, 'market'] == m] for m in MK}, shares, ix, V52, FR_END, log)
    A['sc_flow'] = SCR.flow_score(FL, A.index)
    chk = []
    for c in A.index:
        b = beta_daily(c); dv = val_div(c)[0]; pb = val_pbr(c)[0]; py = static.profit(c)[0]
        chk.append(int(b is not None and b < 0.6) + int(dv is not None and dv >= 2) + int(py == 4) + int(pb is not None and pb < 1.2))
    A['sc_chk'] = chk
    A['sc_mix'] = ((5 * A.sc_flow.fillna(0) + 5 * A.sc_chk * 25) / 10).round(2)
    A['sc_big7'] = FL['big7'].reindex(A.index).round(2)
    A = A.sort_values(['sc_mix', 'sc_flow'], ascending=False, kind='stable'); A['sc_rank'] = range(1, len(A) + 1)
    yr25 = static.yr[2025]
    def ytd_of(c):
        m = mk.get(c); return float(YTD[m][c]) if (m and c in YTD[m].index) else None
    GW = {}
    for c in A.index:
        r2, r25, r26 = r2_of(c), yr25.get(c), ytd_of(c)
        why = [t for t, ok in (('2년 +30% 미만', r2 is not None and r2 >= 30), ('2025년 하락', r25 is not None and r25 > 0), (END[:4] + '년 하락', r26 is not None and r26 > 0)) if not ok]
        GW[c] = why
    G0 = [c for c in A.index if not GW[c]]
    CMP = {c: dict(name=str(NAMES.get(c, c)), market='코스피' if mk[c] == 'KOSPI' else '코스닥', sector=static.wics.get(c),
                   profit_years=static.profit(c)[0], ret25=yr25.get(c)) for c in G0}
    st100, sc100 = list(stU.index[:100]), list(A.index[:100])
    log('재선별: 안정 관찰 대상', len(stU), '· 분석 대상', len(A), '· 성장 조건', len(G0))

    # 1) 방어1 세부 점수(원래 식): 성장 조건 종목으로 분포를 만들고, 다른 명단 종목도 같은 기준으로
    X = {}
    for c in dict.fromkeys(G0 + st100 + sc100):
        m = mk[c]; f = d1feat(c, m)
        shd = S[('SHORT', m)]
        x = dict(beta=f.get('beta'), mdd=f.get('mdd'), crash_day_beat=f.get('crash_day_beat'), beats=f.get('beats'), excess_avg=f.get('excess_avg'),
                 inst=f.get('inst'), frgn=f.get('frgn'), inst_crash=f.get('inst_crash'), frgn_ratio=f.get('frgn_ratio'), frc=f.get('frc'), ret2y=f.get('ret2y_d1'),
                 div=(val_div(c)[0] or 0.0), pbr=val_pbr(c)[0], profit_years=static.profit(c)[0], ret25=yr25.get(c), ret26=ytd_of(c),
                 short=float(shd.at[c, '비중']) if (shd is not None and c in shd.index and num(shd.at[c, '비중']) is not None) else None,
                 kospi=m == 'KOSPI', sector=static.wics.get(c))
        need = ('beta', 'mdd', 'crash_day_beat', 'beats', 'excess_avg', 'inst', 'frgn', 'inst_crash', 'frgn_ratio', 'frc', 'ret2y', 'ret25', 'ret26')
        if any(x.get(k) is None for k in need):
            continue
        X[c] = x
    G = [c for c in G0 if c in X]
    log('방어1 계산 가능: 성장 조건', len(G), '/', len(G0), '· 다른 명단', sum(1 for c in X if c not in CMP))
    if len(G) < 100:
        raise RuntimeError(f'방어1 성장 종목 분포가 너무 적음({len(G)})')
    n = len(G)

    def pct(vals, hi=True):
        vals = sorted(vals)
        def P(v):
            lo = int(np.searchsorted(vals, v, 'left')); up = int(np.searchsorted(vals, v, 'right'))
            p = ((lo + max(up, lo + 1) - 1) / 2) / (n - 1) * 100
            return p if hi else 100 - p
        return P
    R = [X[c] for c in G]
    P = dict(beta=pct([x['beta'] for x in R], False), div=pct([x['div'] for x in R]), pbr=pct([x['pbr'] if x['pbr'] is not None else 99 for x in R], False),
             r2=pct([x['ret2y'] for x in R]), r25=pct([x['ret25'] for x in R]), r26=pct([x['ret26'] for x in R]),
             beats=pct([x['beats'] for x in R]), exc=pct([x['excess_avg'] for x in R]), mdd=pct([x['mdd'] for x in R]), cdb=pct([x['crash_day_beat'] for x in R]),
             ic=pct([x['inst_crash'] for x in R]), cum=pct([x['inst'] + x['frgn'] for x in R]), frc=pct([x['frc'] for x in R]), fr=pct([x['frgn_ratio'] for x in R]))
    ksh = sorted(x['short'] for x in R if x['kospi'] and x['short'] is not None)

    def shscore(v, kospi):
        if not kospi or v is None or len(ksh) < 2: return 50
        below = int(np.searchsorted(ksh, v, 'left')); eq = int(np.searchsorted(ksh, v, 'right')) - below
        return 100 - ((below + (max(eq, 1) - 1) / 2) / (len(ksh) - 1) * 100)

    def score(x):
        d = (P['beta'](x['beta']) + P['div'](x['div']) + P['pbr'](x['pbr'] if x['pbr'] is not None else 99) + (100 if x['profit_years'] == 4 else (x['profit_years'] or 0) * 25 * 0.6)) / 4
        h = (P['beats'](x['beats']) + P['exc'](x['excess_avg']) + P['mdd'](x['mdd']) + P['cdb'](x['crash_day_beat'])) / 4
        g = (P['r2'](x['ret2y']) + P['r25'](x['ret25']) + P['r26'](x['ret26'])) / 3
        fl = (P['ic'](x['inst_crash']) * 2 + P['cum'](x['inst'] + x['frgn']) + P['frc'](x['frc'])) / 4
        lift = sec.get(x['sector'])
        cm = (P['fr'](x['frgn_ratio']) + shscore(x['short'], x['kospi']) + (50 if lift is None else min(100, lift / 3 * 100))) / 3
        return dict(d1_def=round(d, 1), d1_hold=round(h, 1), d1_grow=round(g, 1), d1_flow=round(fl, 1), d1_com=round(cm, 1),
                    d1_total=round(0.30 * d + 0.20 * h + 0.20 * g + 0.15 * fl + 0.15 * cm, 1))
    SC = {c: score(X[c]) for c in X}
    order = sorted(G, key=lambda c: -SC[c]['d1_total'])
    RANK = {c: i + 1 for i, c in enumerate(order)}
    d1100 = order[:100]

    # 2) 통합 명단(세 명단 1~100위 합침)
    rec, last2 = static.rec, static.last2
    def st_reason(c):
        nm = str(NAMES.get(c, '')); cap = S[('CAP', mk[c])]; mc = float(cap.at[c, '시가총액']) if c in cap.index else 0
        t = []
        if __import__('re').search(SCR.PREF_RE, nm): t.append('우선주')
        if mc < 1e11: t.append('시총 1,000억 미만')
        if not t and (c not in rec.index or rec.at[c, 'n_rec'] < 10): t.append('급락 기록 10번 미만')
        return '·'.join(t) if t else '회전율 하위 20%·거래 부족'
    def make_row(c):
        m = mk[c]; nn = {}
        r = dict(code=c, name=str(NAMES.get(c, c)), market='코스피' if m == 'KOSPI' else '코스닥')
        sect = S[('SECT', m)]
        r['sector'] = str(sect.at[c, '업종명']) if (sect is not None and c in sect.index and '업종명' in sect) else None
        if c in stU.index:
            r['st_rank'] = int(stU.at[c, 'st_rank']); r['st_score'] = round(float(stU.at[c, 'st_score']), 1)
        else:
            r['st_rank'] = None; r['st_score'] = None; nn['st_rank'] = f'{len(stU)}개 밖({st_reason(c)})'; nn['st_score'] = '—'
        if c in A.index and A.at[c, 'sc_rank'] <= 300:
            r['sc_rank'] = int(A.at[c, 'sc_rank'])
            for k in ('sc_mix', 'sc_flow', 'sc_chk', 'sc_big7'):
                v = A.at[c, k]; r[k] = None if pd.isna(v) else float(v)
        else:
            t = '300위 밖' if c in A.index else '분석 대상 밖'
            for k in ('sc_rank', 'sc_mix', 'sc_flow', 'sc_chk', 'sc_big7'): r[k] = None; nn[k] = t
        r['d1_rank'] = RANK.get(c)
        if r['d1_rank'] is None:
            nn['d1_rank'] = '성장 조건 밖' + (f"({'·'.join(GW[c])})" if GW.get(c) else ('(분석 대상 밖)' if c not in A.index else ''))
        r['in_st'] = c in st100; r['in_sc'] = c in sc100; r['in_d1'] = c in d1100
        r['n_lists'] = int(r['in_st']) + int(r['in_sc']) + int(r['in_d1']); r['st_top100'] = r['in_st']
        if c in rec.index:
            r['n_rec'] = float(rec.at[c, 'n_rec']); r['rec_rate'] = round(float(rec.at[c, 'rec_rate']) * 100, 3)
        else:
            r['n_rec'] = None; r['rec_rate'] = None; nn['rec_rate'] = '확인 불가'; nn['n_rec'] = '확인 불가'
        for k, col in (('ret_0622', 'ret_0622'), ('ret_0923', 'ret_0923')):
            v = last2.at[c, col] if (c in last2.index and col in last2) else np.nan
            r[k] = None if pd.isna(v) else round(float(v) * 100, 2)
        for y in (2022, 2023, 2024, 2025):
            v = static.yr[y].get(c); r[f'ret_{y}'] = None if v is None or pd.isna(v) else float(v)
            if r[f'ret_{y}'] is None and y < 2025: nn[f'ret_{y}'] = '상장 전'
        base_c = pref_base(c, r['name']) or c
        py, pnote = static.profit(base_c); r['profit_years'] = py
        if py is None: nn['profit_years'] = pnote
        r['op2025'] = static.op2025(base_c)
        if r['op2025'] is None: nn['op2025'] = '확인 불가'
        pb, pbn = val_pbr(c); r['pbr'] = pb
        if pbn: nn['pbr_x'] = pbn
        dv, dvn = val_div(c); r['div'] = dv
        if dvn: nn['div_x'] = dvn
        e = fundv(c, 'PER'); r['per'] = e if e else None
        b = pref_base(c, r['name'])
        if not r['per'] and b:
            eps_ = fundv(b, 'EPS'); cl = close_of(c)
            if eps_ and eps_ > 0 and cl: r['per'] = round(cl / eps_, 1); nn['per_x'] = '보통주 EPS 기준'
        if not r['per']:
            eps_ = fundv(b or c, 'EPS'); nn['per'] = '적자' if (eps_ is not None and eps_ < 0) else '적자·없음'
        r['_n'] = nn
        return r
    members = list(dict.fromkeys(st100 + sc100 + d1100))
    D = [make_row(c) for c in members]
    D.sort(key=lambda r: (-r['n_lists'], r['st_rank'] if r['st_rank'] is not None else 1e9))
    MDDC = []
    for r in D:
        c = r['code']; m = mk[c]; nn = r.setdefault('_n', {})
        cap, fu, fr, shd = S[('CAP', m)], S[('FUND', m)], S[('FR', m)], S[('SHORT', m)]
        old_close = r.get('close')
        if c in cap.index:
            r['close'] = float(cap.at[c, '종가']); r['mcap'] = round(float(cap.at[c, '시가총액']) / 1e8, 3)
        else:
            warn(f'{r["name"]} 시가총액 단면에 없음(거래정지·상장폐지 확인 필요) — 종가 이전 값'); nn['close_x'] = f'{asof} 단면에 없음 — 이전 값'
        ratio = (old_close / r['close']) if (old_close and r.get('close')) else 1.0
        # PBR·PER·배당
        bc = PREF.get(c)
        frow = fu.loc[c] if (fu is not None and c in fu.index) else None
        if bc and fu is not None and bc in fu.index:
            bps, e_ = float(fu.at[bc, 'BPS']), float(fu.at[bc, 'EPS'])
            r['pbr'] = round(r['close'] / bps, 2) if bps > 0 else None
            r['per'] = round(r['close'] / e_, 1) if e_ > 0 else None
            if r['per'] is None: nn['per'] = '적자'
        else:
            pbr = num(frow['PBR']) if frow is not None else None
            if pbr:
                r['pbr'] = pbr; nn.pop('pbr_x', None); nn.pop('pbr', None)
            elif r.get('pbr') and nn.get('pbr_x'):
                r['pbr'] = round(r['pbr'] / ratio, 2)           # 자본 기준 값: 주가만 바뀜
            per = num(frow['PER']) if frow is not None else None
            if per:
                r['per'] = per; nn.pop('per_x', None); nn.pop('per', None)
            elif r.get('per') and nn.get('per_x'):
                r['per'] = round(r['per'] / ratio, 1)
            elif frow is not None and r.get('per') is not None and not nn.get('per_x'):
                r['per'] = None; nn['per'] = '적자' if (num(frow['EPS']) or 0) < 0 else '—'
        if frow is not None and num(frow['DIV']) is not None and not nn.get('div_x'):
            r['div'] = float(frow['DIV'])
        elif r.get('div') is not None and nn.get('div_x'):
            r['div'] = round(r['div'] * ratio, 2)               # 주당배당금 ÷ 종가
        if fr is not None and c in fr.index:
            r['frgn'] = float(fr.at[c, '지분율'])
        if shd is not None and c in shd.index and num(shd.at[c, '비중']) is not None:
            r['short'] = float(shd.at[c, '비중']); nn.pop('short', None)
        f = common(c, m)
        if f:
            for k, v in f.items():
                if k == 'mdd2y_weekly': continue
                if k in ('mdd2y_peak', 'mdd2y_trough'):
                    r[k] = f'{v[:4]}-{v[4:6]}-{v[6:]}'; continue
                r[k] = round(v, 3) if v is not None else None
            MDDC.append(dict(code=c, name=r['name'], mdd2y_daily=round(f.get('mdd2y'), 2) if f.get('mdd2y') is not None else None,
                             mdd2y_weekly=round(f['mdd2y_weekly'], 2), peak=r.get('mdd2y_peak'), trough=r.get('mdd2y_trough')))
            if r.get('ret_ytd') is not None: nn.pop('ret_ytd', None)
        else:
            warn(f'{r["name"]} 일별 종가 없음 — 수익률·변동성 이전 값')
        r['asof'] = asof; r['asof_short'] = f'{d_short[:4]}-{d_short[4:6]}-{d_short[6:]}' if d_short else None


    # 3) 방어1 칸
    BY = {r['code']: r for r in D}
    tot = sorted((SC[c]['d1_total'] for c in G), reverse=True)
    for r in D:
        c = r['code']; nn = r.setdefault('_n', {})
        for k in [k for k in nn if k.startswith('d1_') and k != 'd1_rank']:
            nn.pop(k)
        if c not in SC:
            for k in ('d1_total', 'd1_def', 'd1_hold', 'd1_grow', 'd1_flow', 'd1_com'):
                r[k] = None; nn[k] = f'{asof} 입력 자료 부족'
            if c in CMP: r['d1_rank'] = None; nn['d1_rank'] = f'{asof} 입력 자료 부족'
            continue
        r.update(SC[c])
        if c in CMP:
            r['d1_rank'] = RANK[c]; nn.pop('d1_rank', None)
        else:
            pos = 1 + sum(1 for t in tot if t > SC[c]['d1_total'])
            bnote = '성장 조건 밖 종목이라 같은 식·같은 기준(그날 성장 조건 종목 분포)으로 KRX 자료에서 계산'
            nn['d1_total_x'] = f'{bnote}. 성장 종목 사이에 넣으면 {pos}위 수준'
            for k in ('d1_def', 'd1_hold', 'd1_grow', 'd1_flow'): nn[k + '_x'] = bnote
            nn['d1_com_x'] = bnote + '. 업종 배율은 원래 업종 분류(WICS)가 없어 원래 규칙대로 중립 50' + ('' if r['market'] == '코스피' else ', 코스닥 공매도 잔고도 원래 규칙대로 중립 50')
        if not nn: r.pop('_n')

    # 3) 저장
    os.makedirs(OUT, exist_ok=True)
    for r in D:
        for k, v in list(r.items()):
            if isinstance(v, float) and (np.isnan(v) or np.isinf(v)): r[k] = None
    json.dump(D, open(os.path.join(OUT, 'stocks.json'), 'w'), ensure_ascii=False, separators=(',', ':'))
    mc = pd.DataFrame(MDDC); mc['diff'] = mc.mdd2y_daily - mc.mdd2y_weekly
    mc.sort_values('diff').to_csv(os.path.join(OUT, 'mdd_check.csv'), index=False, encoding='utf-8-sig')
    mdd_sum = dict(window=f'{mdd_base}~{END}', n=int(mc.mdd2y_daily.notna().sum()), deeper_5=int((mc['diff'] < -5).sum()), deeper_10=int((mc['diff'] < -10).sum()),
                   median_diff=round(float(mc['diff'].median()), 2))
    top = [(BY[c]['name'] if c in BY else CMP[c]['name'], SC[c]['d1_total']) for c in order[:5]]
    # 들어오고 나간 종목 기록
    hp = os.path.join(OUT, 'membership.json')
    hist = json.load(open(hp)) if os.path.exists(hp) else {}
    prev = set(prev_codes); now_c = set(BY)
    added = [c for c in members if c not in prev] if prev else []
    removed = sorted(prev - now_c)
    first_run = not hist
    for c in now_c:   # 처음 돌 때(기록 없음) 이미 명단에 있던 종목은 11/16(원래 명단 날짜)부터로
        if c in added or c not in hist:
            hist[c] = dict(since=asof if (c in added or not prev or not first_run) else '2026-11-16', name=BY[c]['name'])
    for c in removed: hist.pop(c, None)
    for r in D: r['since'] = hist.get(r['code'], {}).get('since')
    json.dump(D, open(os.path.join(OUT, 'stocks.json'), 'w'), ensure_ascii=False, separators=(',', ':'))
    json.dump(hist, open(hp, 'w'), ensure_ascii=False, indent=0)
    pm = dict(prev_names)
    if os.path.exists(os.path.join(OUT, 'prev_names.json')): pm.update(json.load(open(os.path.join(OUT, 'prev_names.json'))))
    changes = dict(asof=asof, added=[[c, BY[c]['name'], ''.join(k for k, f in (('안', 'in_st'), ('점', 'in_sc'), ('방', 'in_d1')) if BY[c][f])] for c in added],
                   removed=[[c, pm.get(c, c)] for c in removed])
    json.dump({r['code']: r['name'] for r in D}, open(os.path.join(OUT, 'prev_names.json'), 'w'), ensure_ascii=False)
    with open(os.path.join(OUT, 'changes.csv'), 'a', encoding='utf-8') as fh:
        for c, nm_, ls in changes['added']: fh.write(f'{asof},들어옴,{c},{nm_},{ls}\n')
        for c, nm_ in changes['removed']: fh.write(f'{asof},빠짐,{c},{nm_},\n')
    log('들어온 종목', len(added), '· 빠진 종목', len(removed))
    meta = dict(ok=True, mode='screen', asof=asof, asof_ymd=END, asof_short=D[0]['asof_short'], asof_fund=d_fund, run_at=now.isoformat(timespec='seconds'),
                marker=open(os.path.join(ROOT, 'stocks_run.txt')).read().strip() if os.path.exists(os.path.join(ROOT, 'stocks_run.txt')) else '',
                n=len(D), d1_growth_n=len(G), universe=dict(stable=len(stU), analysis=len(A), growth=len(G0)), changes=changes, mdd_check=mdd_sum, d1_top5=top, warnings=WARN, minutes=round((time.time() - t0) / 60, 1), local=LOCAL)
    json.dump(meta, open(pf, 'w'), ensure_ascii=False, indent=1)
    log('저장', len(D), '종목 · 방어1 1~5위', top, f'· {meta["minutes"]}분')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        log(traceback.format_exc())
        os.makedirs(OUT, exist_ok=True)
        pf = os.path.join(OUT, 'meta.json')
        m = json.load(open(pf)) if os.path.exists(pf) else {}
        m.update(ok=False, failed_at=dt.datetime.now(KST).isoformat(timespec='seconds'), error=LOG[-1][-300:] if LOG else '',
                 marker=open(os.path.join(ROOT, 'stocks_run.txt')).read().strip() if os.path.exists(os.path.join(ROOT, 'stocks_run.txt')) else '')
        json.dump(m, open(pf, 'w'), ensure_ascii=False, indent=1)
        sys.exit(1)
    finally:
        os.makedirs(OUT, exist_ok=True)
        open(os.path.join(OUT, 'log.txt'), 'w').write('\n'.join(LOG) + '\n')
