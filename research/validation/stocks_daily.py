# -*- coding: utf-8 -*-
"""통합 명단(웹판 docs/stocks/stocks.json = 대시보드 datasets/merged) 매일 갱신.

매일 바뀌는 값 (가장 최근 거래일 KRX 종가 기준)
  종가·시총·PBR·PER·배당·외국인 보유율, 공매도 잔고 비중(KRX 공표가 2거래일 늦어 공표된 가장 최근 날),
  올해 수익률(KRX 수정 등락률), 1년·2년 수익률·변동성·베타·최대 낙폭(KRX 주간 수정 등락률 52·104주),
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

    def _get(self, name, fn, tries=3, sleep=0.5):
        f = os.path.join(CACHE, name + '.csv.gz')
        if os.path.exists(f):
            return pd.read_csv(f, compression='gzip', index_col=0)
        for k in range(tries):
            try:
                d = fn(); time.sleep(sleep)
                if d is None: d = pd.DataFrame()
                d.to_csv(f, compression='gzip')
                return pd.read_csv(f, compression='gzip', index_col=0)
            except Exception as e:
                log(f'  실패 {name} ({k + 1}/{tries}): {type(e).__name__} {str(e)[:150]}')
                time.sleep(4 * (k + 1))
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

    def daily(self, code, end):
        if LOCAL:
            f = os.path.join(RAW, 'daily', f'D_{code}.csv.gz')
            d = pd.read_csv(f, compression='gzip', index_col=0) if os.path.exists(f) else None
        else:
            d = self._get(f'D_{code}_{end}', lambda: self.stock.get_market_ohlcv(D_START, end, code, adjusted=True), sleep=0.35)
        if d is None or d.empty or '종가' not in d:
            return None
        d.index = pd.to_datetime(d.index).strftime('%Y%m%d')
        c = d['종가'].astype(float)
        return c[(c > 0) & (c.index <= end)]

    def snap(self, kind, m, day):
        if LOCAL:
            sub = 'd1' if kind == 'NB' else 'snap'
            f = os.path.join(RAW, sub, f'{kind}_{m}_{day}.csv.gz')
            return self._codes(pd.read_csv(f, compression='gzip', index_col=0)) if os.path.exists(f) else None
        fn = {'CAP': self.stock.get_market_cap_by_ticker, 'FUND': self.stock.get_market_fundamental_by_ticker,
              'FR': self.stock.get_exhaustion_rates_of_foreign_investment_by_ticker, 'SHORT': self.stock.get_shorting_balance_by_ticker}[kind]
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
        d = self._codes(self._get(f'PC_{m}_{a}_{b}', lambda: self.krx.get_market_price_change_by_ticker(a, b, m, True)))
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
    base = json.load(open(os.path.join(REFD, 'stocks_base.json')))
    comp = json.load(open(os.path.join(REFD, 'composite.json'))); CMP = {r['code']: r for r in comp}
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
    if not LOCAL and prev.get('asof_ymd') == END and prev.get('ok') and '--force' not in sys.argv:
        log('이미 같은 기준일로 만들어 둠 — 건너뜀')
        prev['checked_at'] = now.isoformat(timespec='seconds'); prev['skipped'] = True
        prev['marker'] = open(os.path.join(ROOT, 'stocks_run.txt')).read().strip() if os.path.exists(os.path.join(ROOT, 'stocks_run.txt')) else ''
        json.dump(prev, open(pf, 'w'), ensure_ascii=False, indent=1)
        return

    mk = {r['code']: ('KOSPI' if r['market'] == '코스피' else 'KOSDAQ') for r in base}
    for c, r in CMP.items():
        mk.setdefault(c, 'KOSPI' if r['market'] == '코스피' else 'KOSDAQ')
    codes = list(dict.fromkeys([r['code'] for r in base] + list(CMP)))
    log('종목', len(codes), '(통합 명단', len(base), '+ 방어1 성장 종목 중 명단 밖', len(codes) - len(base), ')')

    # 단면
    S = {}
    for m in ('KOSPI', 'KOSDAQ'):
        S[('CAP', m)], dcap = latest_ok(src, 'CAP', m, days, END, '종가', back=0)
        S[('FUND', m)], dfund = latest_ok(src, 'FUND', m, days, END, 'PBR', back=3)
        S[('FR', m)], dfr = latest_ok(src, 'FR', m, days, END, '지분율', back=3)
        S[('SHORT', m)], dsh = latest_ok(src, 'SHORT', m, days, END, '비중', back=6)
        S[('dates', m)] = dict(cap=dcap, fund=dfund, fr=dfr, short=dsh)
        S[('FR0', m)] = src.static_fr(m, '20250102')
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

    # 일별 수정 종가
    CL = {}
    for i, c in enumerate(codes):
        cl = src.daily(c, END)
        if cl is not None and len(cl):
            CL[c] = cl
        if (i + 1) % 100 == 0:
            log(f'  일별 {i + 1}/{len(codes)} ({(time.time() - t0) / 60:.1f}분)')
    log('일별 종가', len(CL), '/', len(codes))

    # 주간 전종목 수정 등락률(ISO 주, 원래 연구와 같은 파일) — 끝난 주는 raw/weekly 에 남기고, 기준일이 든 주는 그날 값만
    dd = pd.to_datetime(pd.Series(days))
    grp = dd.groupby(dd.dt.strftime('%G-%V').values)
    allw = sorted(zip(grp.min().dt.strftime('%Y%m%d'), grp.max().dt.strftime('%Y%m%d')), key=lambda x: x[1])
    weeks = allw[-104:]
    wend = [b for _, b in weeks]
    wend_ix = [b for _, b in allw[-105:]]   # 지수 주간 수익률은 한 주 앞 종가부터
    W = {}
    for m in ('KOSPI', 'KOSDAQ'):
        cols = {}
        for a, b in weeks:
            last = b == END
            x = src.pc(a, b, m, keep=None if last else f'weekly/W_{m}_{b}.csv.gz') if not (LOCAL and last) else src.pc(a, b, m, keep=f'weekly/W_{m}_{b}.csv.gz')
            if x is None or x.empty:
                raise RuntimeError(f'{m} 주간 등락률 {a}~{b} 못 받음')
            cols[b] = x['등락률'].astype(float) / 100
        W[m] = pd.DataFrame(cols)
    log('주간 등락률', len(wend), '주', wend[0], '~', wend[-1])
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
        p2 = src.pc('20241118', END, m, keep=f'd1/P_{m}_20241118_{END}.csv.gz' if LOCAL else None)
        if y is None or p2 is None:
            raise RuntimeError(f'{m} 기간 등락률 못 받음')
        YTD[m], R2[m] = y['등락률'].astype(float), p2['등락률'].astype(float)

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
        f['mdd2y'] = float((g / g.cummax() - 1).min() * 100)
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
        if c in R2[m].index:
            f['ret2y_d1'] = float(R2[m][c])
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

    # 1) 통합 명단 공통 지표
    D = json.loads(json.dumps(base))
    asof = f'{END[:4]}-{END[4:6]}-{END[6:]}'
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
                r[k] = round(v, 3) if v is not None else None
            if r.get('ret_ytd') is not None: nn.pop('ret_ytd', None)
        else:
            warn(f'{r["name"]} 일별 종가 없음 — 수익률·변동성 이전 값')
        r['asof'] = asof; r['asof_short'] = f'{d_short[:4]}-{d_short[4:6]}-{d_short[6:]}' if d_short else None

    # 2) 방어1 세부 점수: 성장 조건 250종목 + 명단 밖 종목, 원래 식(comp.py)
    BY = {r['code']: r for r in D}
    X = {}
    fallback = 0
    for c in codes:
        m = mk[c]; f = d1feat(c, m)
        r = BY.get(c); o = CMP.get(c)
        fu = S[('FUND', m)]
        if r is not None:
            div, pbr, py, r25, r26, short = r.get('div'), r.get('pbr'), r.get('profit_years'), r.get('ret_2025'), r.get('ret_ytd'), r.get('short')
        else:
            frow = fu.loc[c] if (fu is not None and c in fu.index) else None
            div = num(frow['DIV']) if frow is not None else None
            pbr = (num(frow['PBR']) or None) if frow is not None else None
            py, r25 = o.get('profit_years'), o.get('ret25')
            cf = common(c, m); r26 = cf.get('ret_ytd')
            shd = S[('SHORT', m)]; short = float(shd.at[c, '비중']) if (shd is not None and c in shd.index and num(shd.at[c, '비중']) is not None) else None
        x = dict(beta=f.get('beta'), mdd=f.get('mdd'), crash_day_beat=f.get('crash_day_beat'), beats=f.get('beats'), excess_avg=f.get('excess_avg'),
                 inst=f.get('inst'), frgn=f.get('frgn'), inst_crash=f.get('inst_crash'), frgn_ratio=f.get('frgn_ratio'), frc=f.get('frc'), ret2y=f.get('ret2y_d1'),
                 div=div if div is not None else 0.0, pbr=pbr, profit_years=py, ret25=r25, ret26=r26, short=short, kospi=m == 'KOSPI',
                 sector=o['sector'] if o else None)
        if LOCAL and o is not None and r is None and not f:
            # 점검용: 원자료가 없는 성장 종목은 원래 입력값으로 분포를 채운다(운영에서는 쓰지 않음)
            x.update(beta=o['beta'], mdd=o['mdd'], crash_day_beat=o['crash_day_beat'], beats=o['beats'], excess_avg=o['excess_avg'], inst=o['inst'], frgn=o['frgn'],
                     inst_crash=o['inst_crash'], frgn_ratio=o['frgn_ratio'], frc=o['frgn_ratio_chg'], ret2y=o['ret2y'], ret26=o['ret26'], div=o['div'], pbr=o['pbr'], short=o.get('short'))
            fallback += 1
        need = ('beta', 'mdd', 'crash_day_beat', 'beats', 'excess_avg', 'inst', 'frgn', 'inst_crash', 'frgn_ratio', 'frc', 'ret2y', 'ret25', 'ret26')
        miss = [k for k in need if x.get(k) is None]
        if miss:
            if o is not None or r is not None:
                warn(f'방어1 입력 부족 {c} {(r or o).get("name")}: {",".join(miss)}')
            continue
        X[c] = x
    G = [c for c in CMP if c in X]
    log('방어1 계산 가능: 성장 종목', len(G), '/ 250 · 명단 밖', sum(1 for c in X if c not in CMP), ('· 점검용 원래 값 대체 ' + str(fallback)) if fallback else '')
    if len(G) < 200:
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
            bnote = '성장 조건 밖 종목이라 같은 식·같은 기준(그날 성장 종목 250개 분포)으로 KRX 자료에서 계산'
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
    top = [(BY[c]['name'] if c in BY else CMP[c]['name'], SC[c]['d1_total']) for c in order[:5]]
    meta = dict(ok=True, asof=asof, asof_ymd=END, asof_short=D[0]['asof_short'], asof_fund=d_fund, run_at=now.isoformat(timespec='seconds'),
                marker=open(os.path.join(ROOT, 'stocks_run.txt')).read().strip() if os.path.exists(os.path.join(ROOT, 'stocks_run.txt')) else '',
                n=len(D), d1_growth_n=len(G), d1_top5=top, warnings=WARN, minutes=round((time.time() - t0) / 60, 1), local=LOCAL)
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
