# -*- coding: utf-8 -*-
"""uswalls/walls.py — 미국 옵션 아침 추정(SPY·QQQ). GitHub 워크플로 us-walls 가 화~토 06:47 KST 에 돌리고 07:40 에 카카오톡으로 보낸다(2026-11-24).

왜 필요한가
  미국 옵션 미결제약정(벽 물량)은 OCC 가 밤사이 한 번 집계해 다음 날 공개한다. 그래서 방금 끝난 장(직전 장)의 포지션 변화는
  그날 밤(한국 시각)에야 공식 숫자로 나온다. 이 스크립트는 장 마감 직후 받을 수 있는 '전날 공식 미결제 + 직전 장 거래량'으로
  직전 장 마감 뒤 콜벽·풋벽을 추정한다.

계산
  - 자료: 야후 옵션 체인(만기 45일 안). 미결제약정 = 직전 장 '전' 마감 포지션(공식), 거래량 = 직전 장.
  - 벽: 현재가 위(콜)·아래(풋)에서 감마×미결제 합이 가장 큰 행사가(SpotGamma 의 콜벽·풋벽과 같은 기준, 블랙숄즈 감마·야후 내재변동성).
        현재가 ±10% 안의 행사가만 본다. 물량(미결제)만으로 본 최대 행사가도 참고로 함께 적는다.
  - 추정 미결제 = 공식 미결제 + k × 직전 장 거래량 (0 아래면 0). k(거래 반영 비율)는 날마다 '전날 거래량 → 오늘 공식 미결제 변화'로
    콜·풋 따로 다시 맞추고, 최근 5번의 가운데값을 쓴다. 기록이 없으면 0.35.
  - 정확도: 어제 추정한 벽과 오늘 공식 미결제로 계산한 벽(같은 현재가 기준)을 비교해 적는다.
  - 신규/청산은 거래량만으로 구분할 수 없으므로 추정치다. 원자료(가격·미결제·거래량)는 추정으로 채우지 않는다.
출력: uswalls/latest.json(웹판), uswalls/kakao.txt(카카오톡, 한 통 200자 이내 · ===== 로 구분), uswalls/data/hist.csv, uswalls/data/snap/*.csv.gz
"""
import datetime as dt
import glob
import json
import math
import os
import sys
import time
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, 'data'); SNAP = os.path.join(DATA, 'snap')
HIST = os.path.join(DATA, 'hist.csv'); LATEST = os.path.join(ROOT, 'latest.json'); KAKAO = os.path.join(ROOT, 'kakao.txt')
SYMS = ('SPY', 'QQQ'); BAND = 0.10; K_DEFAULT = 0.35; K_WIN = 5; KEEP_SNAP = 40; DAYS = 45
KST = ZoneInfo('Asia/Seoul'); NY = ZoneInfo('America/New_York')
TEST = os.environ.get('USW_TEST') == '1'
HIST_COLS = ['session', 'sym', 'spot', 'chg_pct', 'cw_est', 'pw_est', 'cw_off', 'pw_off', 'cwoi_est', 'pwoi_est', 'pcr_oi', 'pcr_vol',
             'k_c', 'k_p', 'kc_used', 'kp_used', 'iv_atm', 'acc_cw', 'acc_pw', 'new_c', 'new_p', 'warn', 'run_kst']


def log(m): print(f'[{dt.datetime.now(KST):%H:%M:%S}] {m}', flush=True)


def fk(v):
    """행사가 표시: 정수면 정수로."""
    if v is None or (isinstance(v, float) and not math.isfinite(v)): return '—'
    return str(int(round(v))) if abs(v - round(v)) < 1e-6 else f'{v:.1f}'


def num(v, n=2):
    return None if v is None or (isinstance(v, float) and not math.isfinite(v)) else round(float(v), n)


# ---------------------------------------------------------------- 수집
def fetch(sym):
    import yfinance as yf
    tk = yf.Ticker(sym)
    h = tk.history(period='15d', interval='1d', auto_adjust=False)
    if h is None or len(h) < 2: raise RuntimeError(f'{sym} 일봉 없음')
    idx = pd.to_datetime(h.index)
    idx = idx.tz_convert(NY).tz_localize(None) if idx.tz is not None else idx
    h.index = idx.normalize()
    now = dt.datetime.now(NY); today = pd.Timestamp(now.date())
    closed = now.hour * 60 + now.minute >= 16 * 60 + 20          # 뉴욕 16:20 전이면 오늘 봉은 장중일 수 있어 뺀다
    h = h[(h.index < today) | ((h.index == today) & closed)].dropna(subset=['Close'])
    if len(h) < 2: raise RuntimeError(f'{sym} 확정 일봉 부족')
    sess = h.index[-1]; spot = float(h['Close'].iloc[-1]); prev = float(h['Close'].iloc[-2])
    bars = [str(d.date()) for d in h.index]
    if sess != today:
        if closed and now.weekday() < 5:   # 평일 장 마감 뒤인데 오늘 봉이 없음 = 미국 휴장
            return str(sess.date()), spot, prev, bars, None
        # 뉴욕 자정~장 마감 전: 야후 미결제가 비었거나 이미 다음 날 값으로 바뀌어 있어 직전 장 추정이 틀어진다 — 계산하지 않는다
        raise RuntimeError(f'계산 시간대 아님(뉴욕 {now:%m/%d %H:%M}) — 뉴욕 장 마감 뒤~자정 전(한국 06:20~13:59)에만 계산')
    lim = sess + pd.Timedelta(days=DAYS); rows = []
    exps = [e for e in tk.options if sess <= pd.Timestamp(e) <= lim]
    if not exps: raise RuntimeError(f'{sym} 만기 목록 없음')
    for e in exps:
        for i in range(3):
            try:
                ch = tk.option_chain(e); break
            except Exception as ex:
                if i == 2: raise RuntimeError(f'{sym} {e} 체인 실패 {ex!r}'[:200])
                time.sleep(3 + 3 * i)
        for cp, x in (('C', ch.calls), ('P', ch.puts)):
            rows.append(pd.DataFrame({'exp': e, 'cp': cp, 'K': x['strike'].astype(float), 'oi': x['openInterest'], 'vol': x['volume'], 'iv': x['impliedVolatility']}))
        time.sleep(0.4)
    o = pd.concat(rows, ignore_index=True)
    o['oi'] = pd.to_numeric(o['oi'], errors='coerce').fillna(0).astype(int)
    o['vol'] = pd.to_numeric(o['vol'], errors='coerce').fillna(0).astype(int)
    o['iv'] = pd.to_numeric(o['iv'], errors='coerce')
    if len(o) < 200: raise RuntimeError(f'{sym} 체인 행 {len(o)} — 자료 이상')
    if o['oi'].sum() < max(100000, 0.2 * o['vol'].sum()):   # 야후는 뉴욕 새벽~아침에 미결제를 0 으로 비워 둔다(2026-11-24 01:09 ET 실행에서 확인)
        raise RuntimeError(f'{sym} 야후 미결제 합 {o["oi"].sum():,} — 비어 있음(야후 밤사이 초기화 시간대로 보임)')
    return str(sess.date()), spot, prev, bars, o


# ---------------------------------------------------------------- 계산
def bs_gamma(S, K, T, iv):
    from scipy.stats import norm
    T = np.maximum(T, 0.5 / 365); iv = np.clip(iv, 0.03, 3.0)
    d1 = (np.log(S / K) + 0.5 * iv * iv * T) / (iv * np.sqrt(T))
    return norm.pdf(d1) / (S * iv * np.sqrt(T))


def prep(o, spot, asof):
    """asof(날짜 문자열) 뒤에 살아 있는 계약만, 현재가 ±BAND, 감마 붙이기."""
    d = o[pd.to_datetime(o['exp']) > pd.Timestamp(asof)].copy()
    d = d[(d['K'] >= spot * (1 - BAND)) & (d['K'] <= spot * (1 + BAND))]
    if not len(d): return d
    d['T'] = (pd.to_datetime(d['exp']) - pd.Timestamp(asof)).dt.days / 365
    d['ivc'] = d['exp'].map(exp_iv(o, spot))
    d['gam'] = bs_gamma(spot, d['K'].values, d['T'].values, d['ivc'].values)
    return d


def valid_iv(iv):
    """야후 장 마감 뒤 내재변동성에는 자리채움 값(0.00001, 1/32 의 배수 0.03125·0.0625·0.125…)이 많다 — 빼고 0.05~3 만 쓴다."""
    iv = pd.to_numeric(iv, errors='coerce')
    ph = (iv * 32 - (iv * 32).round()).abs() < 1e-3
    return iv.where((iv > 0.05) & (iv < 3) & ~ph)


def exp_iv(o, spot):
    """만기별 하나의 변동성: 현재가 ±3% 안 유효값의 가운데값 → 없으면 ±10% → 없으면 전체 가운데값 → 0.20."""
    v = o.assign(v=valid_iv(o['iv'])); out = {}
    allm = v['v'].median() if v['v'].notna().any() else 0.20
    for e, x in v.groupby('exp'):
        m = x[(x['K'] - spot).abs() <= spot * 0.03]['v'].median()
        if not math.isfinite(m if m is not None else float('nan')): m = x[(x['K'] - spot).abs() <= spot * 0.10]['v'].median()
        out[e] = float(m) if m is not None and math.isfinite(m) else float(allm)
    return out


def walls(o, spot, asof, col='oi'):
    d = prep(o, spot, asof)
    if not len(d): return None
    d = d.assign(g=d['gam'] * d[col])
    c = d[(d.cp == 'C') & (d.K >= spot)]; p = d[(d.cp == 'P') & (d.K <= spot)]
    cg = c.groupby('K')['g'].sum(); pg = p.groupby('K')['g'].sum()
    co = c.groupby('K')[col].sum(); po = p.groupby('K')[col].sum()
    sc = d[d.cp == 'C'][col].sum(); sp_ = d[d.cp == 'P'][col].sum()
    return {'cw': float(cg.idxmax()) if len(cg) and cg.max() > 0 else None, 'pw': float(pg.idxmax()) if len(pg) and pg.max() > 0 else None,
            'cw_oi': float(co.idxmax()) if len(co) and co.max() > 0 else None, 'pw_oi': float(po.idxmax()) if len(po) and po.max() > 0 else None,
            'pcr': float(sp_ / sc) if sc > 0 else None,
            'top_c': [[float(k), int(round(v))] for k, v in co.sort_values(ascending=False).head(5).items()],
            'top_p': [[float(k), int(round(v))] for k, v in po.sort_values(ascending=False).head(5).items()]}


def calibrate(prev, prev_sess, prev_spot, cur):
    """전날 거래량 → 오늘 공식 미결제 변화. 콜·풋 따로 '순증 ÷ 거래량'."""
    m = prev[pd.to_datetime(prev['exp']) > pd.Timestamp(prev_sess)].merge(cur[['exp', 'cp', 'K', 'oi']], on=['exp', 'cp', 'K'], suffixes=('_p', '_c'))
    m = m[(m['K'] >= prev_spot * (1 - BAND)) & (m['K'] <= prev_spot * (1 + BAND))]
    out = {}
    for cp in 'CP':
        x = m[m.cp == cp]; v = x['vol'].sum()
        out[cp] = float(np.clip((x['oi_c'] - x['oi_p']).sum() / v, -1, 1)) if v > 1000 else None
    same = float((m['oi_c'] == m['oi_p'])[m['vol'] > 0].mean()) if (m['vol'] > 0).any() else None
    return out, same


def iv_atm(o, spot, sess):
    d = o[pd.to_datetime(o['exp']) > pd.Timestamp(sess)]
    if not len(d): return None
    for e in sorted(d['exp'].unique())[:3]:            # 가장 가까운 만기부터, 등가격 근처 유효값이 있는 첫 만기
        x = d[d['exp'] == e].assign(v=lambda t: valid_iv(t['iv'])).dropna(subset=['v'])
        x = x[(x['K'] - spot).abs() <= spot * 0.01]
        if len(x): return float(x['v'].median())
    return None


def new_flow(o, spot, sess):
    """거래량이 기존 미결제보다 많은 행사가(신규로 보이는 곳) — 콜은 현재가 -2% 위, 풋은 +2% 아래에서 거래량 순."""
    d = o[pd.to_datetime(o['exp']) > pd.Timestamp(sess)].groupby(['cp', 'K'])[['oi', 'vol']].sum().reset_index()
    d = d[(d['vol'] > d['oi']) & (d['vol'] >= 5000)]
    c = d[(d.cp == 'C') & (d.K >= spot * 0.98) & (d.K <= spot * (1 + BAND))].sort_values('vol', ascending=False).head(2)
    p = d[(d.cp == 'P') & (d.K <= spot * 1.02) & (d.K >= spot * (1 - BAND))].sort_values('vol', ascending=False).head(2)
    return [[float(k), int(v)] for k, v in zip(c.K, c.vol)], [[float(k), int(v)] for k, v in zip(p.K, p.vol)]


def k_used(H, sym, cp, today_k):
    col = 'k_c' if cp == 'C' else 'k_p'
    ks = list(H[H.sym == sym][col].dropna().tail(K_WIN - 1)) if len(H) and col in H else []
    if today_k is not None: ks.append(today_k)
    return (float(np.median(ks)), len(ks)) if ks else (K_DEFAULT, 0)


def snap_files(sym):
    return sorted(glob.glob(os.path.join(SNAP, f'{sym}_*.csv.gz')))


def load_hist():
    if os.path.exists(HIST):
        H = pd.read_csv(HIST, dtype={'session': str})
        for c in HIST_COLS:
            if c not in H: H[c] = None
        return H[HIST_COLS]
    return pd.DataFrame(columns=HIST_COLS)


# ---------------------------------------------------------------- 흐름 말
def direction(vals, tol=0.004):
    v = [x for x in vals if x is not None and math.isfinite(x)]
    if len(v) < 2: return '기록 쌓는 중'
    r = (v[-1] - v[0]) / v[0]
    return '옆걸음' if abs(r) < tol else ('올라가는 중' if r > 0 else '내려가는 중')


def trend(H, sym, cur):
    rows = H[H.sym == sym].sort_values('session').tail(4).to_dict('records') + [cur]
    cw = [r.get('cw_est') for r in rows]; pw = [r.get('pw_est') for r in rows]; pc = [r.get('pcr_oi') for r in rows]
    width = [c - p for c, p in zip(cw, pw) if c is not None and p is not None]
    wtxt = '기록 쌓는 중' if len(width) < 2 else ('벽 사이 넓어짐' if width[-1] > width[0] * 1.03 else '벽 사이 좁아짐' if width[-1] < width[0] * 0.97 else '벽 사이 비슷')
    pcv = [x for x in pc if x is not None and math.isfinite(x)]
    ptxt = '' if len(pcv) < 2 else ('풋 우세 강해짐' if pcv[-1] - pcv[0] > 0.05 else '풋 우세 약해짐' if pcv[0] - pcv[-1] > 0.05 else '풋·콜 비중 비슷')
    seq = '→'.join(fk(x) for x in cw if x is not None)
    return {'n': len(rows), 'cw_dir': direction(cw), 'pw_dir': direction(pw), 'width': wtxt, 'pcr': ptxt, 'cw_seq': seq,
            'pw_seq': '→'.join(fk(x) for x in pw if x is not None), 'sessions': [r.get('session') for r in rows]}


def arrow(new, old):
    if new is None or old is None: return ''
    d = new - old
    return ' 그대로' if abs(d) < 1e-6 else f' {"▲" if d > 0 else "▼"}{fk(abs(d))}'


def cut(m, n=200):
    return m if len(m) <= n else m[:n - 1] + '…'


# ---------------------------------------------------------------- 한 종목
def run_sym(sym, H, now_kst):
    sess, spot, prev_close, bars, o = fetch(sym)
    files = snap_files(sym); name = lambda f: os.path.basename(f)[len(sym) + 1:-7]
    if o is None:                                                      # 미국 휴장(평일인데 오늘 봉 없음)
        hr = H[(H.sym == sym) & (H.session == sess)]
        log(f'{sym}: 미국 휴장 — 마지막 장 {sess}')
        return {'sym': sym, 'status': 'holiday', 'session': sess, 'spot': spot, 'last': (hr.iloc[-1].to_dict() if len(hr) else None)}
    if files and name(files[-1]) == sess:
        hr = H[(H.sym == sym) & (H.session == sess)]
        if len(hr) and str(hr.iloc[-1]['run_kst'])[:10] == f'{now_kst:%Y-%m-%d}':
            files = files[:-1]; log(f'{sym}: 오늘 같은 장({sess})을 다시 계산(재시도)')
        else:
            log(f'{sym}: 새 거래 없음(마지막 장 {sess}) — 미국 휴장 또는 아직 마감 전')
            return {'sym': sym, 'status': 'holiday', 'session': sess, 'spot': spot, 'last': (hr.iloc[-1].to_dict() if len(hr) else None)}
    H = H[~((H.sym == sym) & (H.session == sess))]                    # 같은 장을 다시 계산할 때 앞선 시도의 줄은 빼고 본다
    last = name(files[-1]) if files else None
    warn = []
    # 전날 스냅숏(직전 거래일이어야 비율을 맞춘다)
    prev = None; prev_sess = None; prev_spot = None
    if files:
        prev_sess = last; ps = pd.read_csv(files[-1], dtype={'exp': str})
        prev_spot = float(ps['spot'].iloc[0]) if 'spot' in ps else None
        if len(bars) >= 2 and bars[-2] == prev_sess and prev_spot: prev = ps
        else: warn.append(f'전날 스냅숏 {prev_sess} 이 직전 거래일({bars[-2] if len(bars) >= 2 else "?"})이 아님 — 비율 맞춤 건너뜀')
    kc = kp = None; same = None
    if prev is not None:
        kk, same = calibrate(prev, prev_sess, prev_spot, o); kc, kp = kk['C'], kk['P']
        if same is not None and same > 0.9: warn.append('야후 미결제가 전날과 거의 같음(미갱신 의심) — 추정이 작게 나올 수 있음')
    kcu, nc = k_used(H, sym, 'C', kc); kpu, np_ = k_used(H, sym, 'P', kp)
    est = o.copy(); kk_ = np.where(est['cp'] == 'C', kcu, kpu)
    est['est'] = np.maximum(0, est['oi'] + kk_ * est['vol']).round()
    W_est = walls(est, spot, sess, 'est') or {}
    W_off = walls(o, spot, prev_sess or sess, 'oi') or {}           # 전날 장 마감 공식 포지션(같은 현재가로)
    acc_cw = acc_pw = None
    ph = H[(H.sym == sym) & (H.session == prev_sess)] if prev_sess else H.iloc[0:0]
    if prev is not None and len(ph) and prev_spot:
        act = walls(o, prev_spot, prev_sess, 'oi') or {}               # 어제 추정했던 것(전날 장 마감 뒤 포지션)의 실제값
        pe = ph.iloc[-1]
        if act.get('cw') is not None and pd.notna(pe['cw_est']): acc_cw = act['cw'] - float(pe['cw_est'])
        if act.get('pw') is not None and pd.notna(pe['pw_est']): acc_pw = act['pw'] - float(pe['pw_est'])
    d0 = o[pd.to_datetime(o['exp']) > pd.Timestamp(sess)]
    band = d0[(d0['K'] >= spot * (1 - BAND)) & (d0['K'] <= spot * (1 + BAND))]
    vc, vp = band[band.cp == 'C']['vol'].sum(), band[band.cp == 'P']['vol'].sum()
    nfc, nfp = new_flow(o, spot, sess)
    row = {'session': sess, 'sym': sym, 'spot': round(spot, 2), 'chg_pct': round((spot / prev_close - 1) * 100, 2),
           'cw_est': W_est.get('cw'), 'pw_est': W_est.get('pw'), 'cw_off': W_off.get('cw'), 'pw_off': W_off.get('pw'),
           'cwoi_est': W_est.get('cw_oi'), 'pwoi_est': W_est.get('pw_oi'), 'pcr_oi': num(W_off.get('pcr'), 3), 'pcr_vol': num(vp / vc, 3) if vc else None,
           'k_c': num(kc, 3), 'k_p': num(kp, 3), 'kc_used': round(kcu, 3), 'kp_used': round(kpu, 3), 'iv_atm': num(iv_atm(o, spot, sess), 4),
           'acc_cw': num(acc_cw, 2), 'acc_pw': num(acc_pw, 2), 'new_c': ' '.join(fk(k) + 'C' for k, _ in nfc), 'new_p': ' '.join(fk(k) + 'P' for k, _ in nfp),
           'warn': ' / '.join(warn), 'run_kst': f'{now_kst:%Y-%m-%d %H:%M}'}
    # 스냅숏 저장(만기 ≥ 이 장 — 내일 비율 맞춤·정확도 비교에 씀). 시험 실행은 기록을 남기지 않는다
    if not TEST:
        os.makedirs(SNAP, exist_ok=True)
        s = o[pd.to_datetime(o['exp']) >= pd.Timestamp(sess)].copy(); s['spot'] = round(spot, 4)
        s.to_csv(os.path.join(SNAP, f'{sym}_{sess}.csv.gz'), index=False)
        for f in snap_files(sym)[:-KEEP_SNAP]: os.remove(f)
    tr = trend(H, sym, row)
    return {'sym': sym, 'status': 'ok', 'session': sess, 'row': row, 'trend': tr, 'k_n': [nc, np_], 'est_top': {'C': W_est.get('top_c'), 'P': W_est.get('top_p')},
            'off_top': {'C': W_off.get('top_c'), 'P': W_off.get('top_p')}, 'new': {'C': nfc, 'P': nfp}, 'prev_session': prev_sess}


# ---------------------------------------------------------------- 글
def msg_sym(r):
    w = r['row']; tr = r['trend']; tag = ' 시험' if TEST else ''
    d = pd.Timestamp(w['session'])
    lines = [f"[미국옵션 {d:%m/%d}장{tag}] {w['sym']} {w['spot']:.2f} ({w['chg_pct']:+.2f}%)",
             f"콜벽 {fk(w['cw_est'])} (전날 {fk(w['cw_off'])}{arrow(w['cw_est'], w['cw_off'])})",
             f"풋벽 {fk(w['pw_est'])} (전날 {fk(w['pw_off'])}{arrow(w['pw_est'], w['pw_off'])})",
             f"풋/콜 거래 {w['pcr_vol']:.2f} · 미결제 {w['pcr_oi']:.2f}" if w['pcr_vol'] is not None and w['pcr_oi'] is not None else '풋/콜 확인 불가']
    nf = ' '.join(x for x in (w['new_c'], w['new_p']) if x)
    if nf: lines.append(f'새로 몰린 곳 {nf}')
    lines.append(f"흐름 콜벽 {tr['cw_dir']}·풋벽 {tr['pw_dir']}·{tr['width']}" + (f"·{tr['pcr']}" if tr['pcr'] else ''))
    return cut('\n'.join(lines))


def msg_tail(res):
    tag = ' 시험' if TEST else ''
    acc = []
    for r in res:
        if r['status'] != 'ok': continue
        w = r['row']; a = lambda v: '기록 쌓는 중' if v is None else ('맞음' if abs(v) <= 1 else f'{v:+g} 차이')
        acc.append(f"{w['sym']} 콜벽 {a(w['acc_cw'])}·풋벽 {a(w['acc_pw'])}")
    ks = ' / '.join(f"{r['sym']} 콜{r['row']['kc_used']:.2f}·풋{r['row']['kp_used']:.2f}" for r in res if r['status'] == 'ok')
    seq = ' / '.join(f"{r['sym']} {r['trend']['cw_seq']}" for r in res if r['status'] == 'ok' and r['trend']['n'] > 1)
    t = [f'[미국옵션 정확도{tag}] 어제 추정 vs 공식: ' + (' / '.join(acc) or '기록 쌓는 중')]
    if seq: t.append(f'콜벽 흐름 {seq}')
    t.append(f'거래 반영 비율 {ks}')
    t.append('공식 확정은 오늘 밤 23:45 전후(SpotGamma) · 추정치 · 투자 권유 아님')
    return cut('\n'.join(t))


def msg_holiday(res):
    tag = ' 시험' if TEST else ''
    parts = []
    for r in res:
        l = r.get('last') or {}
        parts.append(f"{r['sym']} {r['spot']:.2f} 콜벽 {fk(l.get('cw_est'))}·풋벽 {fk(l.get('pw_est'))}")
    s = res[0]['session'] if res else '?'
    return cut(f"[미국옵션{tag}] 새 미국 장 거래 없음(휴장 또는 마감 전) — 마지막 장 {s} 기준 그대로\n" + ' / '.join(parts))


def main():
    now = dt.datetime.now(KST); H = load_hist(); res = []; errs = []
    for sym in SYMS:
        try: res.append(run_sym(sym, H, now)); log(f'{sym} 완료')
        except Exception as e: errs.append(f'{sym}: {e!r}'[:200]); log(f'{sym} 실패 {e!r}')
    ok = [r for r in res if r['status'] == 'ok']; hol = [r for r in res if r['status'] == 'holiday']
    if ok and not TEST:
        H = pd.concat([H[~H.set_index(['session', 'sym']).index.isin([(r['row']['session'], r['sym']) for r in ok])], pd.DataFrame([r['row'] for r in ok])], ignore_index=True)
        H = H.sort_values(['sym', 'session']); os.makedirs(DATA, exist_ok=True); H[HIST_COLS].to_csv(HIST, index=False)
    msgs = [msg_sym(r) for r in ok]
    if ok: msgs.append(msg_tail(ok))
    if hol and not ok: msgs.append(msg_holiday(hol))
    if errs: msgs.append(cut(f"[미국옵션{' 시험' if TEST else ''}] 일부 실패 — " + ' / '.join(errs) + ' · GitHub 감시가 다시 돌립니다'))
    status = 'fail' if not res else ('ok' if ok and not errs else 'holiday' if hol and not ok and not errs else 'partial')
    J = {'at_kst': f'{now:%Y-%m-%d %H:%M}', 'test': TEST, 'status': status, 'errors': errs,
         'note': '추정치: 공식 미결제(직전 장 전 마감) + 거래 반영 비율 × 직전 장 거래량. 벽 = 감마×미결제가 가장 큰 행사가(현재가 ±10%, 만기 45일 안).',
         'syms': {}, 'hist': {}}
    for r in res:
        J['syms'][r['sym']] = {k: v for k, v in r.items() if k not in ('sym',)}
    for s in SYMS:
        J['hist'][s] = json.loads(H[H.sym == s].tail(30).to_json(orient='records', force_ascii=False)) if len(H) else []
    J['msgs'] = msgs
    json.dump(J, open(LATEST, 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=str)
    open(KAKAO, 'w', encoding='utf-8').write('\n=====\n'.join(msgs) + '\n')
    for m in msgs: print('---\n' + m + f'\n({len(m)}자)')
    out = os.environ.get('GITHUB_OUTPUT')
    if out: open(out, 'a').write(f'status={status}\n')
    if status == 'fail': sys.exit(2)
    if status == 'partial' and os.environ.get('USW_LAST') != '1': sys.exit(3)   # 워크플로가 2분 뒤 다시 돈다(마지막 시도면 일부 실패 그대로 보냄)


def seed(sym, path, sess, prev_close):
    """처음 한 번: 기존 스냅숏(deriv/us/data/chain_now_*.csv.gz)으로 시작 기록을 만든다(비율은 기본값)."""
    c = pd.read_csv(path)
    o = pd.DataFrame({'exp': pd.to_datetime(c['exp']).dt.strftime('%Y-%m-%d'), 'cp': c['cp'], 'K': c['K'].astype(float),
                      'oi': pd.to_numeric(c['open_interest'], errors='coerce').fillna(0).astype(int), 'vol': pd.to_numeric(c['volume'], errors='coerce').fillna(0).astype(int),
                      'iv': pd.to_numeric(c['iv'], errors='coerce')})
    spot = float(c['spot'].iloc[0])
    os.makedirs(SNAP, exist_ok=True)
    s = o[pd.to_datetime(o['exp']) >= pd.Timestamp(sess)].copy(); s['spot'] = round(spot, 4); s.to_csv(os.path.join(SNAP, f'{sym}_{sess}.csv.gz'), index=False)
    est = o.copy(); est['est'] = (est['oi'] + K_DEFAULT * est['vol']).round()
    We = walls(est, spot, sess, 'est'); Wo = walls(o, spot, sess, 'oi')
    d0 = o[pd.to_datetime(o['exp']) > pd.Timestamp(sess)]; band = d0[(d0['K'] >= spot * (1 - BAND)) & (d0['K'] <= spot * (1 + BAND))]
    vc, vp = band[band.cp == 'C']['vol'].sum(), band[band.cp == 'P']['vol'].sum()
    H = load_hist(); H = H[~((H.sym == sym) & (H.session == sess))]
    row = {'session': sess, 'sym': sym, 'spot': round(spot, 2), 'chg_pct': round((spot / prev_close - 1) * 100, 2), 'cw_est': We['cw'], 'pw_est': We['pw'],
           'cw_off': Wo['cw'], 'pw_off': Wo['pw'], 'cwoi_est': We['cw_oi'], 'pwoi_est': We['pw_oi'], 'pcr_oi': num(Wo['pcr'], 3), 'pcr_vol': num(vp / vc, 3),
           'kc_used': K_DEFAULT, 'kp_used': K_DEFAULT, 'iv_atm': num(iv_atm(o, spot, sess), 4), 'warn': '시작 기록(기존 스냅숏 · 기본 비율 0.35)',
           'run_kst': f'{dt.datetime.now(KST):%Y-%m-%d %H:%M}'}
    H = pd.concat([H, pd.DataFrame([row])], ignore_index=True).sort_values(['sym', 'session']); os.makedirs(DATA, exist_ok=True); H[HIST_COLS].to_csv(HIST, index=False)
    print(sym, row)


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'seed': seed(sys.argv[2], sys.argv[3], sys.argv[4], float(sys.argv[5]))
    else: main()
