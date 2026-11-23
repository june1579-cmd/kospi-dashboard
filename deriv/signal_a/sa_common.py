# -*- coding: utf-8 -*-
"""Signal A 공통 계산(시험대) — 모든 줄기(t1~t6)·판정(sa_judge.py)·통합(sa_s3.py)이 이것만 불러 쓴다.

규칙(AGENT.md 절대 규칙 그대로)
  - 자료: 릴리스 signal-a-data-v1 의 고정 자료만(panel.pkl·lab_feat.pkl·raw_*.tgz). 끝 날짜 state/freeze.json 의 end 뒤는 잘라 버린다.
  - 매매: 코스피 지수. t일 신호(장 마감 뒤 확정) → t+1 거래일 시가 매수 → 보유 h 일째(t+h) 종가 매도. 옵션 없음.
  - 합계: 거래별 수익률의 단순 합계(복리 아님). 적중 = 방향 × 수익 > 0.
  - 독립 거래: 앞 거래가 끝난 날(청산일) 이후의 신호만 남긴다(연구소 a08_validate.independent 와 같음).
  - 하루 늦춤(delay=1): 조건일 t → 신호일은 t+1 로 적는다(매수는 t+2 시가). 연구소 후보의 signal 칸과 같은 꼴.

후보 꼴(줄기 → 판정):  dict(id, track, family, desc, direction(+1 오름/−1 내림), hold(보유일, 없으면 None), kind, trades)
  kind  'fixed' = 전체 기간에 규칙·문턱을 고정한 신호(결과를 보고 고른 것 — CRITERIA 1절 통과 숫자만 본다)
        'wf'    = 해마다 그 전 자료만으로 고른 절차의 그 해 거래를 이어 붙인 것(다음 해 성적 — CRITERIA 3절)
  trades DataFrame[signal, exit] (+ 선택: hit 0/1 = 보유일 없는 채점에서 미리 정한 적중, ret = 미리 계산한 수익률)
  base_y (선택) hit 칸을 쓰는 후보가 꼭 같이 넘기는 것: 거래일마다 '그 날이 신호일이었다면 같은 채점 방식으로 맞았나'(1/0/nan, D.td 순서 Series·배열).
         판정이 '같은 해 아무 날'과 가짜 신호를 이 배열로 잰다(없으면 h 일째 종가 수익 부호로 재서 채점 방식이 어긋난다).
"""
import hashlib
import json
import os
import subprocess
import sys
import tarfile

import numpy as np
import pandas as pd

SA = os.path.dirname(os.path.abspath(__file__))
DERIV = os.path.dirname(SA)
REPO = os.path.dirname(DERIV)
STATE = os.path.join(SA, 'state')
DATA = os.environ.get('SA_DATA') or os.path.join(SA, '_data')      # 내려받은 고정 자료(저장소에 올리지 않음)
RELEASE = 'signal-a-data-v1'
GH_REPO = os.environ.get('GITHUB_REPOSITORY', 'june1579-cmd/kospi-dashboard')
FREEZE = json.load(open(os.path.join(STATE, 'freeze.json'), encoding='utf-8'))
END = pd.Timestamp(FREEZE['end'])                                  # 2026-11-20 — 이 날 뒤 자료는 쓰지 않는다
START = pd.Timestamp('2010-01-01')                                 # 성적을 재는 첫날(옵션 벽 지표 시작)
SPLIT = pd.Timestamp('2024-01-01')                                 # 앞 = 2010~2023, 뒤 = 2024~ (CRITERIA 1절)
WF_YEARS = list(range(2016, 2027))                                 # 해마다 나누기: 2016~2026 을 그 전 자료로 골라 채점
BIG_YEARS = (2011, 2020, 2026)                                     # 큰 변동 해(CRITERIA 3절 3번)
Z90 = 1.645
SEED = 20261124
BAD_COLS = ('US_vvix', 'US_skew')                                   # 고정 자료에서 값이 날짜 숫자로 깨져 있는 열(2026-11-24 확인) — 빈칸으로 둔다(추정으로 채우지 않음)


# ------------------------------------------------------------------ 자료
def _sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''): h.update(b)
    return h.hexdigest()


def _expected_sha():
    out = {}
    for ln in open(os.path.join(STATE, 'freeze_sha256.txt'), encoding='utf-8'):
        p = ln.split()
        if len(p) == 2: out[p[1]] = p[0]
    return out


def fetch(files=('panel.pkl', 'lab_feat.pkl')):
    """릴리스 파일을 DATA 로 내려받고 고정 기록(freeze_sha256.txt)과 같은지 확인한다. 이미 있고 같으면 그대로 둔다."""
    os.makedirs(DATA, exist_ok=True); exp = _expected_sha()
    for f in files:
        p = os.path.join(DATA, f)
        if not (os.path.exists(p) and _sha(p) == exp.get(f)):
            url = f'https://github.com/{GH_REPO}/releases/download/{RELEASE}/{f}'
            ok = False
            if os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN'):
                ok = subprocess.call(['gh', 'release', 'download', RELEASE, '-R', GH_REPO, '-p', f, '-D', DATA, '--clobber']) == 0
            if not ok:
                subprocess.check_call(['curl', '-sSL', '--retry', '3', '-o', p, url])
        got = _sha(p)
        if got != exp.get(f):
            raise RuntimeError(f'고정 자료 {f} 가 기록과 다름(확인 불가): {got[:12]} != {str(exp.get(f))[:12]}')
    return DATA


def raw_dir(which='deriv'):
    """원자료 묶음(raw_deriv.tgz / raw_main.tgz)을 DATA/raw_<which> 에 풀고 그 폴더를 돌려준다(필요한 줄기만 부른다)."""
    f = f'raw_{which}.tgz'; d = os.path.join(DATA, f'raw_{which}')
    if not os.path.exists(os.path.join(d, '.ok')):
        fetch((f,)); os.makedirs(d, exist_ok=True)
        with tarfile.open(os.path.join(DATA, f)) as t: t.extractall(d)
        open(os.path.join(d, '.ok'), 'w').close()
    return d


class Data:
    """고정 자료 한 벌. td = 거래일(코스피 지수 기준), X = 지표 434개(t일 장 마감 뒤 아는 값), K = 코스피 지수 시고저종,
    F = 코스피200 연속 선물 시고저종(연구소 판정 가격, 참고용), wide = 옵션 벽 지표(X 의 OW_ 열과 같음), walls = 날짜×결제월 벽 표, groups = 지표 → 묶음."""

    def __init__(self):
        fetch()
        P = pd.read_pickle(os.path.join(DATA, 'panel.pkl')); L = pd.read_pickle(os.path.join(DATA, 'lab_feat.pkl'))
        cut = lambda df: df[df.index <= END]
        self.X = cut(P['X']).astype(float)
        for _c in BAD_COLS:
            if _c in self.X: self.X[_c] = np.nan
        self.K = cut(P['P']['KOSPI'])[['open', 'high', 'low', 'close']].astype(float)
        self.F = cut(P['P']['K200F'])[['open', 'high', 'low', 'close']].astype(float)
        self.groups = dict(P['groups'])
        self.wide = cut(L['wide']).reindex(self.K.index)
        w = L['walls']; self.walls = w[pd.to_datetime(w['date']) <= END].reset_index(drop=True)
        self.td = self.K.index
        assert self.td.equals(self.X.index) and self.td[-1] <= END
        self.n = len(self.td)
        self.year = self.td.year.values
        self.o = self.K['open'].values; self.h = self.K['high'].values; self.l = self.K['low'].values; self.c = self.K['close'].values

    # ---- 위치(정수) 계산: 규칙 수천~수만 개를 빨리 채점할 때 쓴다
    def fwd(self, h, delay=0, px=None):
        """r[i] = 조건일 i → (i+delay) 신호 → (i+delay+1) 시가 매수 → (i+delay+h) 종가 매도 수익률. 자료 밖이면 nan."""
        o, c = (self.o, self.c) if px is None else (px['open'].values, px['close'].values)
        r = np.full(self.n, np.nan); i = np.arange(self.n); e = i + delay + 1; x = i + delay + h; ok = x < self.n
        r[ok] = c[x[ok]] / o[e[ok]] - 1
        return r

    def thin_pos(self, pos, h, delay=0):
        """조건일 위치 pos(오름차순) → 독립 거래만. 신호 위치 s = pos+delay, 청산 위치 s+h, 다음 신호는 s ≥ 앞 청산 위치."""
        keep = []; last = -10 ** 9
        for p in pos:
            s = p + delay
            if s >= last and s + h < self.n: keep.append(p); last = s + h
        return np.asarray(keep, dtype=int)

    def trades_from_pos(self, pos, h, delay=0):
        """조건일 위치 → trades[signal, exit] (signal = 늦춘 신호일, exit = 보유 h 일째). 자료 밖 청산은 뺀다."""
        pos = np.asarray(pos, dtype=int); pos = pos[pos + delay + h < self.n]
        return pd.DataFrame({'signal': self.td[pos + delay], 'exit': self.td[pos + delay + h]})

    def first_only(self, mask, n):
        """첫 신호만: 직전 n 거래일 안에 같은 조건이 없던 날(연구소 '첫 신호(5일)' 와 같은 정의: 앞 조건일과의 간격 > n)."""
        idx = np.where(np.asarray(mask, dtype=bool))[0]
        if not len(idx): return np.zeros(self.n, dtype=bool)
        idx = idx[np.r_[True, np.diff(idx) > n]]
        out = np.zeros(self.n, dtype=bool); out[idx] = True
        return out


# ------------------------------------------------------------------ 통계·채점
def wilson(k, n, z=Z90):
    """윌슨 구간(기본 90% 양쪽 → 하한은 단측 95%). (하한, 상한)."""
    if n <= 0: return (np.nan, np.nan)
    p = k / n; d = 1 + z * z / n; c = p + z * z / (2 * n); h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (float((c - h) / d), float((c + h) / d))


def independent(trades):
    """겹치지 않는 거래만: 앞 거래 청산일 이후(같은 날 포함)의 신호부터 다시 센다."""
    t = trades.sort_values('signal').reset_index(drop=True); keep = []; last = pd.Timestamp('1900-01-01')
    for i, (s, e) in enumerate(zip(t['signal'], t['exit'])):
        if s >= last: keep.append(i); last = e
    return t.iloc[keep].reset_index(drop=True)


def trade_returns(trades, px):
    """trades[signal, exit] → 신호 다음 거래일 시가 매수, exit 날 종가 매도 수익률(소수). 자료 밖이면 nan."""
    td = px.index; o = px['open'].values; c = px['close'].values; out = np.full(len(trades), np.nan)
    si = td.searchsorted(pd.DatetimeIndex(trades['signal']), side='right'); ei = td.get_indexer(pd.DatetimeIndex(trades['exit']))
    ok = (si < len(td)) & (ei >= 0) & (si <= ei)
    out[ok] = c[ei[ok]] / o[si[ok]] - 1
    return out


def prep(trades):
    t = trades.copy(); t['signal'] = pd.to_datetime(t['signal']); t['exit'] = pd.to_datetime(t['exit'])
    return t.dropna(subset=['signal', 'exit'])


def score(trades, direction, px, start=START, end=END, thin=True):
    """구간 [start, end] 의 독립 거래 성적. 반환 dict(n, k, hit, lb, sum, mean, by_year{해: [n, k, 합계]}, t=채점한 거래표)."""
    t = prep(trades); t = t[(t['signal'] >= start) & (t['exit'] <= end)]
    if thin: t = independent(t)
    if not len(t): return {'n': 0, 'k': 0, 'hit': None, 'lb': None, 'sum': 0.0, 'mean': None, 'by_year': {}, 't': t}
    r = t['ret'].values.astype(float) if 'ret' in t else trade_returns(t, px)
    ok = np.isfinite(r); t = t[ok].reset_index(drop=True); r = r[ok]
    hit = (t['hit'].values.astype(float) > 0) if 'hit' in t else (direction * r > 0)
    n = len(r); k = int(hit.sum()); y = pd.DatetimeIndex(t['signal']).year.values
    by = {int(a): [int((y == a).sum()), int(hit[y == a].sum()), round(float((direction * r[y == a]).sum()), 5)] for a in np.unique(y)}
    t = t.assign(ret=r, ok=hit.astype(int))
    return {'n': n, 'k': k, 'hit': (k / n if n else None), 'lb': (wilson(k, n)[0] if n else None), 'sum': float((direction * r).sum()),
            'mean': (float((direction * r).mean()) if n else None), 'by_year': by, 't': t}


def hold_days(trades, td):
    t = prep(trades)
    if not len(t): return 1
    si = td.searchsorted(pd.DatetimeIndex(t['signal']), side='right'); ei = td.get_indexer(pd.DatetimeIndex(t['exit']))
    h = (ei - si + 1)[(ei >= 0)]
    return int(max(1, np.median(h))) if len(h) else 1


def base_by_year(D, h, direction):
    """아무 날 기준: 해마다, 그 해 모든 날을 신호일로 삼았을 때(다음 날 시가 → h 일째 종가) 방향이 맞은 비율. {해: (날 수, 맞은 수)}."""
    r = D.fwd(h); out = {}
    for y in np.unique(D.year):
        m = (D.year == y) & np.isfinite(r)
        out[int(y)] = (int(m.sum()), int((direction * r[m] > 0).sum()))
    return out


def base_arr(D, base_y):
    """후보의 base_y(그 날이 신호일이었다면 그 후보의 채점 방식으로 맞았나: 1/0/nan, 거래일 순서)를 길이 D.n 배열로."""
    if base_y is None: return None
    if isinstance(base_y, pd.Series): base_y = base_y.reindex(D.td).values
    b = np.asarray(base_y, dtype=float)
    assert len(b) == D.n, 'base_y 길이가 거래일 수와 다름'
    return b


def base_for(D, t, h, direction, base_y=None):
    """채점한 거래표 t 와 같은 해 구성으로 맞춘 아무 날 적중률(해마다 아무 날 적중률을 그 해 거래 수로 가중 평균).
    base_y 가 있으면(보유일 없는 채점·손절 익절처럼 '다음 날 시가 → h 일째 종가'가 아닌 채점) 아무 날도 같은 채점 방식(base_y)으로 잰다."""
    if not len(t): return None
    by = base_arr(D, base_y)
    if by is None: b = base_by_year(D, h, direction)
    else: b = {int(a): (int(((D.year == a) & np.isfinite(by)).sum()), float(np.nansum(by[D.year == a]))) for a in np.unique(D.year)}
    y = pd.DatetimeIndex(t['signal']).year.values; num = den = 0.0
    for a in np.unique(y):
        nd, kd = b.get(int(a), (0, 0))
        if nd: num += (y == a).sum() * kd / nd; den += (y == a).sum()
    return float(num / den) if den else None


def placebo_same_year(D, t, direction, h=None, n_iter=2000, seed=SEED, base_y=None):
    """가짜 신호 시험(CRITERIA 3절 2번): 채점한 독립 거래 t 의 신호 날짜를 '같은 해 안에서만' 아무 날로 옮긴 가짜 n_iter 번.
    가짜도 같은 보유일(거래마다 다르면 가운뎃값)·같은 독립 거래 규칙으로 솎아 채점하고, 가짜 적중률이 실제 이상인 비율 p = (1 + 이상인 횟수)/(1 + n_iter).
    base_y 가 없으면 실제·가짜 모두 '다음 날 시가 → h 일째 종가' 수익 부호로 잰다. base_y 가 있으면 실제는 t 의 ok(그 후보의 채점), 가짜는 base_y(같은 채점)로 잰다."""
    if not len(t): return {'p': None, 'n_iter': 0}
    h = int(h or hold_days(t, D.td)); rng = np.random.default_rng(seed); by = base_arr(D, base_y)
    hitv = by if by is not None else np.where(np.isfinite(D.fwd(h)), (direction * D.fwd(h) > 0).astype(float), np.nan)
    si = D.td.get_indexer(pd.DatetimeIndex(t['signal'])); keep = si >= 0; si = si[keep]
    if by is not None and 'ok' in t: real = float(np.asarray(t['ok'], dtype=float)[keep].mean()) if len(si) else np.nan
    else: real = float(np.nanmean(hitv[si])) if np.isfinite(hitv[si]).any() else np.nan
    ys = D.year[si]; pools = {int(y): np.where((D.year == y) & np.isfinite(hitv))[0] for y in np.unique(ys)}
    cnt = {int(y): int((ys == y).sum()) for y in np.unique(ys)}; ge = 0; vals = np.empty(n_iter)
    for b in range(n_iter):
        pos = np.sort(np.concatenate([rng.choice(pools[y], size=min(c, len(pools[y])), replace=False) for y, c in cnt.items() if len(pools[y])] or [np.empty(0, dtype=int)])).astype(int)
        pos = D.thin_pos(pos, h); v = float(hitv[pos].mean()) if len(pos) else 0.0
        vals[b] = v; ge += v >= real - 1e-12
    return {'p': (1 + ge) / (1 + n_iter), 'n_iter': n_iter, 'real': real, 'fake_mean': float(vals.mean()), 'fake_p95': float(np.quantile(vals, 0.95)), 'h': h}


def first_touch(D, k=0.05, max_days=60, delay=0):
    """보유일 없는 채점(±k 먼저 닿기): 조건일 i → (i+delay+1) 시가 기준, 그날부터 max_days 거래일 안에 고가가 +k 를 먼저 넘으면 1,
    저가가 −k 를 먼저 넘으면 0, 같은 날 둘 다면 0(불리하게), 끝까지 둘 다 아니면 nan. 반환 (y, exit 위치)."""
    n = D.n; y = np.full(n, np.nan); ex = np.full(n, -1, dtype=int)
    for i in range(n - delay - 1):
        e = i + delay + 1; o1 = D.o[e]; up = o1 * (1 + k); dn = o1 * (1 - k); end = min(n - 1, e + max_days - 1)
        for j in range(e, end + 1):
            d_, u_ = D.l[j] <= dn, D.h[j] >= up
            if d_: y[i] = 0.0; ex[i] = j; break
            if u_: y[i] = 1.0; ex[i] = j; break
    return y, ex


def wf_splits(years=WF_YEARS):
    """해마다 나누기: (시험 해, 학습 끝 = 그 해 1월 1일 직전). 학습에는 청산일이 학습 끝 이전인 거래만 쓴다."""
    return [(y, pd.Timestamp(f'{y}-01-01') - pd.Timedelta(days=1)) for y in years]


# ------------------------------------------------------------------ 줄기 결과 저장·읽기
def track_dir(track):
    d = os.path.join(SA, track); os.makedirs(os.path.join(d, 'out'), exist_ok=True)
    return d


def parse_part(argv=None):
    """--part i/n (1부터), --merge, --nparts, --quick 를 읽는다. 반환 dict(part=(i, n) 또는 None, merge, nparts, quick)."""
    a = list(sys.argv[1:] if argv is None else argv); out = {'part': None, 'merge': '--merge' in a, 'nparts': '--nparts' in a, 'quick': '--quick' in a or os.environ.get('SA_QUICK') == '1'}
    if '--part' in a:
        i, n = a[a.index('--part') + 1].split('/'); out['part'] = (int(i), int(n))
    return out


def save_part(track, i, n, obj):
    p = os.path.join(track_dir(track), 'out', 'parts'); os.makedirs(p, exist_ok=True)
    pd.to_pickle(obj, os.path.join(p, f'part_{i:02d}_of_{n:02d}.pkl'))


def load_parts(track, n):
    """조각 결과를 순서대로 읽는다. 없는 조각은 None(판정에서 '조각 실패'로 적힌다)."""
    p = os.path.join(track_dir(track), 'out', 'parts'); out = []
    for i in range(1, n + 1):
        f = os.path.join(p, f'part_{i:02d}_of_{n:02d}.pkl')
        out.append(pd.read_pickle(f) if os.path.exists(f) else None)
    return out


def save_result(track, cands, meta):
    """줄기 결과 저장. cands = 후보 목록(위 꼴), meta = dict(n_tested 시험한 가짓수 합계, families {가족: 가짓수}, m_fixed, m_wf,
    not_included [SPEC '안 넣은 것'], parts_failed [], notes [], tables [표 파일 이름]). 판정(sa_judge.py)이 이 둘만 읽는다."""
    d = os.path.join(track_dir(track), 'out')
    for c in cands:
        c.setdefault('track', track); c['trades'] = prep(c['trades'])[[x for x in ('signal', 'exit', 'hit', 'ret') if x in c['trades']]].reset_index(drop=True)
    pd.to_pickle(cands, os.path.join(d, 'cands.pkl'))
    meta = dict(meta); meta.setdefault('track', track); meta.setdefault('parts_failed', []); meta.setdefault('not_included', []); meta.setdefault('notes', [])
    meta['n_cands'] = len(cands); meta['data_end'] = str(END.date())
    json.dump(meta, open(os.path.join(d, 'meta.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


def load_result(track):
    d = os.path.join(SA, track, 'out')
    return pd.read_pickle(os.path.join(d, 'cands.pkl')), json.load(open(os.path.join(d, 'meta.json'), encoding='utf-8'))


def ledger_add(track, families, note=''):
    """원장(state/ledger.json)에 시험한 가짓수를 적는다. families = {가족 이름: 가짓수}. 같은 줄기를 다시 적으면 덮어쓴다(다시 돌려도 두 번 세지 않음)."""
    p = os.path.join(STATE, 'ledger.json'); L = json.load(open(p, encoding='utf-8')) if os.path.exists(p) else {'trials': []}
    L['trials'] = [x for x in L.get('trials', []) if x.get('track') != track]
    L['trials'].append({'track': track, 'families': families, 'n': int(sum(families.values())), 'note': note,
                        'at': pd.Timestamp.now(tz='Asia/Seoul').strftime('%Y-%m-%d %H:%M')})
    L['total'] = int(sum(x['n'] for x in L['trials']))
    json.dump(L, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return L


def read_status():
    return json.load(open(os.path.join(STATE, 'status.json'), encoding='utf-8'))


def write_status(S):
    S['updated'] = pd.Timestamp.now(tz='Asia/Seoul').strftime('%Y-%m-%d %H:%M')
    json.dump(S, open(os.path.join(STATE, 'status.json'), 'w', encoding='utf-8'), ensure_ascii=False)


def pct(x, d=1):
    return '–' if x is None or (isinstance(x, float) and not np.isfinite(x)) else f'{100 * x:.{d}f}%'
