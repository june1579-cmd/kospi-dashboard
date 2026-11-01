# -*- coding: utf-8 -*-
"""champ.py — 큰 흐름 비교: 해마다(2015~) 그해 실제 큰 흐름(코스피 10% 지그재그)과 가장 잘 맞은 1위 조합·설정을 찾는다.

   후보
   - 단일 지표: 가격(이평·교차·MACD·수익률·신고가 돌파·ATR 추적·x% 되돌림 전환·ADX 방향·RSI·볼린저·이격도 역추세·범위 위치),
     수급(외국인·기관·개인 n일 순매수 부호·분위 추세/역추세), 금투협(신용·예탁금·신용/예탁금·미수금 n일 변화, 전날 공시분),
     변동성(VKOSPI·VIX가 n일 평균 아래·n일 하락; VIX는 전날 미국 종가). 같은 날 판단이 2015~ 전 기간 똑같은 것은 하나만 남긴다.
   - 조합: 2개 모두 상승일 때 상승(AND) · 둘 중 하나라도 상승이면 상승(OR) · 3개 중 2개(다수결).
   - 점수 = 그해 거래일 중 판단(상승/하락)이 실제 큰 흐름과 같은 날의 비율. 같으면 그해 전환(판단 바뀜) 횟수가 적은 쪽 → 단순한 쪽(단일 < 2개 < 3개).
   - 그해 안에 판단이 없는 날(지표 준비 기간)이 있는 지표는 그해 후보에서 뺀다.
   - '실제'는 사후 판정이라 그해 1위는 사후 최적(그해 자료를 보고 고른 것)이다. 다음 해 일치율이 실제로 썼을 때의 성적.
   - 자동 갱신: 마지막으로 확정된 전환점(10% 되돌림 확인) 이전에 끝난 해는 지난 결과(조합 이름)를 그대로 쓰고 다시 계산만 한다.
     그 뒤의 해(지금은 올해)는 자료가 들어올 때마다 다시 찾는다.
   출력: trend_champ(일별: date, y2015..), trend_champ_rules(해마다 1줄)
"""
import os, json, time
import numpy as np, pandas as pd

# ----------------------------------------------------------------------------- 도구
def _ff0(a):
    """0(판단 없음)은 직전 판단으로 채움. 맨 앞 0은 0."""
    a = np.asarray(a, dtype=np.int8)
    ix = np.where(a != 0, np.arange(len(a)), -1); ix = np.maximum.accumulate(ix)
    return np.where(ix >= 0, a[np.maximum(ix, 0)], 0).astype(np.int8)

def _sgn(x):
    v = np.sign(np.asarray(x, dtype=float)); v[np.isnan(v)] = 0
    return _ff0(v.astype(np.int8))

def _hyst(up, dn):
    up = np.asarray(up, dtype=bool); dn = np.asarray(dn, dtype=bool)
    v = np.where(up, 1, np.where(dn, -1, 0)).astype(np.int8)
    return _ff0(v)

def _ema(x, n): return x.ewm(span=n, adjust=False).mean()

def _zz_dir2(c, x):
    """위 함수의 간결판(처음 방향은 첫 x% 움직임으로 정함)."""
    v = c.values; th = x / 100; out = np.zeros(len(v), np.int8)
    mode = 0; hi = lo = None
    for i, p in enumerate(v):
        if np.isnan(p): out[i] = mode; continue
        if hi is None: hi = lo = p
        if mode == 0:
            hi = max(hi, p); lo = min(lo, p)
            if p >= lo * (1 + th): mode = 1; hi = p
            elif p <= hi * (1 - th): mode = -1; lo = p
        elif mode == 1:
            if p > hi: hi = p
            elif p <= hi * (1 - th): mode = -1; lo = p
        else:
            if p < lo: lo = p
            elif p >= lo * (1 + th): mode = 1; hi = p
        out[i] = mode
    return out

# ----------------------------------------------------------------------------- 단일 지표
INV = {'foreign': '외국인', 'inst': '기관', 'indiv': '개인', 'other': '기타법인'}

def singles(D):
    """반환: idx(2015~ 거래일), keys, names, A(int8, n×T: +1 상승 / −1 하락 / 0 판단 없음). 계산은 2006~ 장기 자료(있으면)로 해서 준비 기간을 앞에 둔다."""
    try:
        import quant; DH = quant.load_history(D)
    except Exception:
        DH = D
    K, F, L, C = DH['K'], DH['F'], DH['L'], DH['C']
    c = K.close.astype(float); H = K.high.fillna(c).astype(float); Lo = K.low.fillna(c).astype(float)
    ix = c.index; out = []
    def add(key, name, arr): out.append((key, name, np.asarray(arr, dtype=np.int8)))
    tr = pd.concat([H - Lo, (H - c.shift()).abs(), (Lo - c.shift()).abs()], axis=1).max(axis=1)
    NS = [5, 10, 15, 20, 25, 30, 40, 50, 60, 67, 75, 90, 100, 120, 150, 180, 200, 250]
    _sm = {}; _em = {}
    SMA = lambda n: _sm.setdefault(n, c.rolling(n).mean()); EMA = lambda n: _em.setdefault(n, _ema(c, n))
    for n in NS: add(f'p_sma:{n}', f'종가>SMA{n}', _sgn(c - SMA(n)))
    for n in NS: add(f'p_ema:{n}', f'종가>EMA{n}', _sgn(c - EMA(n)))
    for a in (3, 5, 8, 10, 13, 15, 20, 30, 40, 50, 60):
        for b in (10, 15, 20, 22, 30, 40, 50, 60, 75, 90, 104, 120, 150, 200, 250):
            if b >= 2 * a: add(f'p_sx:{a}:{b}', f'SMA{a}>SMA{b}', _sgn(SMA(a) - SMA(b)))
    for a in (5, 8, 12, 15, 20, 30, 40, 50):
        for b in (20, 26, 40, 55, 60, 80, 100, 120, 150, 200):
            if b >= 1.5 * a: add(f'p_ex:{a}:{b}', f'EMA{a}>EMA{b}', _sgn(EMA(a) - EMA(b)))
    for f in (5, 8, 12, 19):
        for s_ in (20, 26, 39, 50):
            if s_ < 1.5 * f: continue
            for g_ in (5, 9):
                m_ = EMA(f) - EMA(s_); add(f'p_macd:{f}:{s_}:{g_}', f'MACD({f},{s_},{g_})>시그널', _sgn(m_ - _ema(m_, g_)))
    for n in (5, 10, 20, 40, 60, 90, 120, 250): add(f'p_roc:{n}', f'{n}일 수익률>0', _sgn(c - c.shift(n)))
    for n in (10, 20, 40, 60, 90, 120, 250):
        add(f'p_don:{n}', f'{n}일 신고가·신저가 돌파', _hyst(c > c.shift(1).rolling(n).max(), c < c.shift(1).rolling(n).min()))
    for n in (5, 7, 10, 14, 22, 50):
        a_ = tr.rolling(n).mean()
        for m in (1, 1.5, 2, 2.5, 3, 4):
            add(f'p_atr:{n}:{m}', f'ATR{n}×{m:g} 추적', _hyst(c > (c.rolling(n).min() + m * a_).shift(1), c < (c.rolling(n).max() - m * a_).shift(1)))
    for x in (2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 15, 20): add(f'p_zz:{x}', f'{x}% 되돌림 전환', _zz_dir2(c, x))
    up = H.diff(); dn = -Lo.diff()
    for n in (7, 10, 14, 20, 28):
        atr = tr.ewm(alpha=1 / n).mean()
        pdm = pd.Series(np.where((up > dn) & (up > 0), up, 0), index=ix).ewm(alpha=1 / n).mean(); ndm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0), index=ix).ewm(alpha=1 / n).mean()
        pdi, ndi = 100 * pdm / atr, 100 * ndm / atr; adx = (100 * (pdi - ndi).abs() / (pdi + ndi)).ewm(alpha=1 / n).mean()
        for t in (15, 20, 25, 30, 35):
            add(f'p_adx:{n}:{t}', f'ADX{n}>{t} 방향', _hyst((adx > t) & (pdi > ndi), (adx > t) & (ndi > pdi)))
    d = c.diff()
    for n in (5, 9, 14, 21, 28, 42):
        g = d.clip(lower=0).ewm(alpha=1 / n).mean(); l_ = (-d.clip(upper=0)).ewm(alpha=1 / n).mean(); rsi = 100 - 100 / (1 + g / l_)
        for hi, lo in ((50, 50), (55, 45), (60, 40), (70, 30)):
            add(f'p_rsi:{n}:{hi}', f'RSI{n} {hi}/{lo} 돌파', _hyst(rsi > hi, rsi < lo))
    for n in (10, 20, 40, 60):
        mu, sd = c.rolling(n).mean(), c.rolling(n).std()
        for k in (1, 1.5, 2, 2.5):
            add(f'p_bb:{n}:{k}', f'볼린저{n},{k:g} 돌파', _hyst(c > mu + k * sd, c < mu - k * sd))
    for n in (5, 10, 20, 40, 60, 120):
        dsp = (c / SMA(n) - 1) * 100
        for x in (3, 5, 8, 10, 15, 20):
            add(f'p_disp:{n}:{x}', f'이격도{n} 역추세(±{x}%)', _hyst(dsp < -x, dsp > x))
    for n in (20, 60, 120, 250):
        hi_, lo_ = c.rolling(n).max(), c.rolling(n).min(); add(f'p_pos:{n}', f'{n}일 범위 중간 위', _sgn((c - lo_) / (hi_ - lo_) - 0.5))
    # 수급(그날 장 마감 뒤 확정치)
    for inv, nm in INV.items():
        x = F[inv].reindex(ix).astype(float)
        for n in (1, 3, 5, 10, 20, 40, 60, 120, 250):
            s = x.rolling(n).sum()
            add(f'f_sg:{inv}:{n}:t', f'{nm} {n}일 순매수>0', _sgn(s)); add(f'f_sg:{inv}:{n}:c', f'{nm} {n}일 순매도(역)', _sgn(-s))
            for q in (0.1, 0.2, 0.3):
                lo_, hi_ = s.expanding(250).quantile(q), s.expanding(250).quantile(1 - q)
                add(f'f_q:{inv}:{n}:{q}:t', f'{nm} {n}일 상·하위{int(q * 100)}% 추세', _hyst(s > hi_, s < lo_))
                add(f'f_q:{inv}:{n}:{q}:c', f'{nm} {n}일 상·하위{int(q * 100)}% 역추세', _hyst(s < lo_, s > hi_))
    # 금투협(다음 영업일 공시 → 하루 늦춤)
    cred = C.credit.reindex(ix).ffill().shift(1).astype(float); dep = L.deposit.reindex(ix).ffill().shift(1).astype(float); misu = L.misu.reindex(ix).ffill().shift(1).astype(float)
    cd = cred / dep; liq5 = L.liq.reindex(ix).shift(1).astype(float).rolling(5).sum()
    for n in (1, 5, 10, 20, 60, 120):
        add(f'k_cr:{n}:t', f'신용 {n}일 증가', _sgn(cred - cred.shift(n))); add(f'k_cr:{n}:c', f'신용 {n}일 감소(역)', _sgn(cred.shift(n) - cred))
        add(f'k_dep:{n}:t', f'예탁금 {n}일 증가', _sgn(dep - dep.shift(n))); add(f'k_dep:{n}:c', f'예탁금 {n}일 감소(역)', _sgn(dep.shift(n) - dep))
        add(f'k_cd:{n}:t', f'신용/예탁금 {n}일 상승', _sgn(cd - cd.shift(n))); add(f'k_cd:{n}:c', f'신용/예탁금 {n}일 하락(역)', _sgn(cd.shift(n) - cd))
        add(f'k_mi:{n}:c', f'미수금 {n}일 감소(역)', _sgn(misu.shift(n) - misu)); add(f'k_mi:{n}:t', f'미수금 {n}일 증가', _sgn(misu - misu.shift(n)))
    for qh, ql in ((0.95, 0.7), (0.9, 0.5), (0.8, 0.5)):
        add(f'k_liq:{qh}:{ql}', f'미수 반대매매 5일 합계 상위{int(round((1 - qh) * 100))}% 하락·하위{int(ql * 100)}% 상승', _hyst(liq5 < liq5.expanding(250).quantile(ql), liq5 > liq5.expanding(250).quantile(qh)))
    # 변동성
    V = D['V']; vk = V.close.reindex(ix).astype(float) if V is not None else pd.Series(np.nan, index=ix)
    for n in (5, 10, 20, 40, 60, 120): add(f'v_vk:{n}', f'VKOSPI<{n}일 평균', _sgn(vk.rolling(n).mean() - vk))
    for n in (1, 5, 10, 20): add(f'v_vkc:{n}', f'VKOSPI {n}일 하락', _sgn(vk.shift(n) - vk))
    for ql, qh in ((0.3, 0.7), (0.5, 0.5), (0.2, 0.8)):
        add(f'v_vkq:{ql}:{qh}', f'VKOSPI 하위{int(ql * 100)}% 상승·상위{int(round((1 - qh) * 100))}% 하락', _hyst(vk < vk.expanding(120).quantile(ql), vk > vk.expanding(120).quantile(qh)))
    if D.get('VIX') is not None and len(D['VIX']):
        vx = D['VIX'].copy(); vx.index = vx.index + pd.Timedelta(days=1)          # 미국 D일 종가 → 한국 D+1 아침에 앎
        vx = vx.reindex(vx.index.union(ix)).ffill().reindex(ix)
        for n in (5, 10, 20, 40, 60): add(f'v_vix:{n}', f'VIX<{n}일 평균(전날 미국)', _sgn(vx.rolling(n).mean() - vx))
        for lo, hi in ((15, 20), (20, 25), (20, 30)): add(f'v_vixl:{lo}:{hi}', f'VIX {lo} 아래 상승·{hi} 위 하락(전날 미국)', _hyst(vx < lo, vx > hi))
    # 2015~ 구간으로 자르고 같은 판단은 하나만
    K15 = D['K'].index; pos = ix.get_indexer(K15)
    keys, names, rows, seen = [], [], [], set()
    for key, name, arr in out:
        a = arr[pos]; h = hash(a.tobytes())
        if h in seen: continue
        seen.add(h); keys.append(key); names.append(name); rows.append(a)
    return K15, keys, names, np.vstack(rows)

# ----------------------------------------------------------------------------- 조합 계산
def series_of(spec, KEY, A):
    """spec: 'single|k' / 'and|a|b' / 'or|a|b' / 'maj3|a|b|c' → int8 방향."""
    p = spec.split('|'); g = lambda k: A[KEY[k]]
    if p[0] == 'single': return g(p[1])
    if p[0] in ('and', 'or'):
        a, b = g(p[1]), g(p[2]); z = (a == 0) | (b == 0)
        u = (a == 1) & (b == 1) if p[0] == 'and' else (a == 1) | (b == 1)
        return np.where(z, 0, np.where(u, 1, -1)).astype(np.int8)
    if p[0] == 'maj3':
        a, b, c = g(p[1]), g(p[2]), g(p[3]); z = (a == 0) | (b == 0) | (c == 0)
        u = (a.astype(int) + b + c) > 0
        return np.where(z, 0, np.where(u, 1, -1)).astype(np.int8)
    raise ValueError(spec)

FAM = {'single': '단일', 'and': '2개 모두', 'or': '2개 중 하나', 'maj3': '3개 중 2개'}
def spec_text(spec, NAME):
    p = spec.split('|'); nm = [NAME.get(k, k) for k in p[1:]]
    if p[0] == 'single': return nm[0]
    if p[0] == 'and': return '둘 다 상승일 때만 상승: ' + ' · '.join(nm)
    if p[0] == 'or': return '둘 중 하나라도 상승이면 상승: ' + ' · '.join(nm)
    return '3개 중 2개: ' + ' · '.join(nm)

def flips(a):
    a = a[a != 0]; return int((a[1:] != a[:-1]).sum()) if len(a) > 1 else 0

# ----------------------------------------------------------------------------- 찾기(한 해)
def _pack(bits):
    """bool (n, T) → uint64 (n, W)"""
    bits = np.atleast_2d(bits); n, T = bits.shape; Wb = (T + 63) // 64 * 64
    pad = np.zeros((n, Wb), bool); pad[:, :T] = bits
    return np.packbits(pad, axis=1, bitorder='little').view(np.uint64)

def search_year(A, leg, m, keep=400):
    """A(n×T) 중 그해(m) 판단이 모두 있는 지표만. 반환: 최고 점수(맞힌 날 수), 후보 spec 목록(동점 포함, keep개까지), 시험한 개수."""
    sub = A[:, m]; ok = np.where((sub != 0).all(axis=1))[0]; S = sub[ok]; n = len(ok)
    lg = leg[m]; LU = _pack(lg == 1)[0]; LD = _pack(lg == -1)[0]; nLD = int((lg == -1).sum())
    U = _pack(S == 1)
    pc = np.bitwise_count
    def score(M): return (pc(M & LU).sum(-1).astype(np.int32) - pc(M & LD).sum(-1).astype(np.int32)) + nLD
    best = -1; cand = []
    def take(sc, specs_fn):
        nonlocal best, cand
        mx = int(sc.max()) if sc.size else -1
        if mx < best: return
        where = np.argwhere(sc == mx)
        if mx > best: best = mx; cand = []
        for w in where[:max(0, keep - len(cand))]: cand.append(specs_fn(w))
    s1 = score(U); take(s1, lambda w: f'single|{ok[w[0]]}')
    iu = np.triu_indices(n, 1)
    AND = U[:, None, :] & U[None, :, :]; sA = score(AND)[iu]; take(sA, lambda w: f'and|{ok[iu[0][w[0]]]}|{ok[iu[1][w[0]]]}')
    OR = U[:, None, :] | U[None, :, :]; sO = score(OR)[iu]; take(sO, lambda w: f'or|{ok[iu[0][w[0]]]}|{ok[iu[1][w[0]]]}')
    del AND, OR
    ntri = 0
    for a in range(n - 2):
        Ub = U[a + 1:]; mb = len(Ub)
        and_ab = U[a] & Ub; or_ab = U[a] | Ub
        M = and_ab[:, None, :] | (or_ab[:, None, :] & Ub[None, :, :])
        sc = score(M); sc[np.tril_indices(mb)] = -1; ntri += mb * (mb - 1) // 2
        mx = int(sc.max())
        if mx >= best:
            take(sc, lambda w, a=a: f'maj3|{ok[a]}|{ok[a + 1 + w[0]]}|{ok[a + 1 + w[1]]}')
    return best, cand, {'single': n, 'and': len(iu[0]), 'or': len(iu[0]), 'maj3': ntri}

def pick(cand, A, m):
    """동점 후보 중: 그해 전환 적은 것 → 단순한 것(단일 < 2개 < 3개) → 먼저 나온 것."""
    rank = {'single': 0, 'and': 1, 'or': 1, 'maj3': 2}
    def keyf(sp):
        s = series_of(sp, IDENT, A)[m]
        return (flips(s), rank[sp.split('|')[0]])
    return min(cand, key=keyf)

class _Ident(dict):
    def __missing__(self, k): return int(k)
IDENT = _Ident()

# ----------------------------------------------------------------------------- 실행
def run(D, leg, prev_rules=None, log=print):
    """leg: 2015~ 거래일의 실제 큰 흐름(+1/−1, 표시용 줄과 같은 것). prev_rules: 지난 trend_champ_rules(DataFrame) — 확정된 해는 그 조합을 다시 씀."""
    t0 = time.time()
    idx, keys, names, A = singles(D)
    KEY = {k: i for i, k in enumerate(keys)}; NAME = dict(zip(keys, names))
    lg = np.asarray(leg.reindex(idx).fillna(0).values, dtype=np.int8)
    yrs = idx.year.values; years = sorted(set(yrs)); last = idx[-1]
    # 마지막으로 확정된 전환점: leg 가 바뀐 마지막 날(그 전 해들은 '실제'가 더 바뀌지 않음)
    ch = np.where(lg[1:] != lg[:-1])[0]; settled_until = idx[ch[-1] + 1] if len(ch) else idx[0]
    prev, prow = {}, {}
    if prev_rules is not None and len(prev_rules):
        for _, r in prev_rules.iterrows():
            try: y_ = int(str(r['year'])[:4]); prev[y_] = str(r['spec']); prow[y_] = r.to_dict()
            except Exception: pass
    today = pd.Timestamp.now(tz='Asia/Seoul').strftime('%Y-%m-%d')
    rows, series = [], {}
    for y in years:
        m = yrs == y; yend = idx[m][-1]
        reuse = (y in prev) and (yend < settled_until) and all(k in KEY for k in prev[y].split('|')[1:])
        if reuse:
            spec_k = prev[y]; pr = prow[y]; tested = None; nties = None
            searched = str(pr.get('searched_at', '') or '') or '2026-10-28'
            how = f'{searched} 찾은 조합 그대로(확정된 해, 값만 다시 계산)'
        else:
            best, cand, tested = search_year(A, lg, m)
            sp = pick(cand, A, m); p = sp.split('|'); spec_k = '|'.join([p[0]] + [keys[int(i)] for i in p[1:]])
            how = '이번 갱신에서 다시 찾음' + (' (마지막 전환점 확정 뒤 구간이 있어 자료가 들어올 때마다 다시 찾음)' if yend >= settled_until else ''); nties = len(cand); searched = today
            log(f'  {y}: 맞힌 날 {best}/{int(m.sum())} 후보 {sum(tested.values()):,}개 동점 {len(cand)}{"+" if len(cand) >= 400 else ""} → {spec_text(spec_k, NAME)}  ({time.time() - t0:.0f}s)')
        s = series_of(spec_k, KEY, A); series[y] = s
        acc = lambda mm: (float(((s[mm] == lg[mm]) & (s[mm] != 0)).sum()) / max(int(mm.sum()), 1) * 100)
        mn = yrs == y + 1
        rows.append({'year': str(y), 'spec': spec_k, 'family': FAM[spec_k.split('|')[0]], 'rule': spec_text(spec_k, NAME),
                     'acc_year': round(acc(m), 1), 'days_year': int(m.sum()), 'flips_year': flips(s[m]),
                     'acc_next': round(acc(mn), 1) if mn.any() else np.nan, 'acc_all': round(acc(np.ones(len(s), bool)), 1),
                     'acc_last_year': round(acc(yrs == years[-1]), 1), 'acc_r60': round(acc(np.arange(len(s)) >= len(s) - 60), 1),
                     'acc_r20': round(acc(np.arange(len(s)) >= len(s) - 20), 1), 'now': '상승' if s[-1] == 1 else ('하락' if s[-1] == -1 else '—'),
                     'tested': (sum(tested.values()) if tested else prow.get(y, {}).get('tested', '')), 'tested_detail': (json.dumps(tested, ensure_ascii=False) if tested else prow.get(y, {}).get('tested_detail', '')),
                     'ties': (prow.get(y, {}).get('ties', '') if nties is None else (f'{nties}+' if nties >= 400 else nties)), 'how': how, 'searched_at': searched, 'year_end': yend.strftime('%Y-%m-%d'),
                     'settled': 'Y' if yend < settled_until else 'N'})
    R = pd.DataFrame(rows)
    daily = pd.DataFrame({'date': idx.strftime('%Y-%m-%d')})
    for y in years: daily[f'y{y}'] = np.where(series[y] == 0, np.nan, series[y].astype(float))
    log(f'  큰 흐름 그해 1위: 단일 지표 {len(keys)}개, {time.time() - t0:.0f}초')
    R['n_singles'] = len(keys); R['asof'] = last.strftime('%Y-%m-%d')
    return {'trend_champ': daily, 'trend_champ_rules': R}
