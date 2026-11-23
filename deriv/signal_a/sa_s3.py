# -*- coding: utf-8 -*-
"""Signal A S3 통합 — T1~T6 판정이 남긴 후보를 모아 겹침·함께 쓰기·반증 시험 표와 보고서 초안을 만든다.

미리 정한 목록·버팀 기준은 s3/SPEC.md 에 있고 이 파일은 그대로 구현한다(새 신호를 찾지 않는다, 기준 숫자를 바꾸지 않는다).
  1) 모으기   tN/out/judge.json 의 final·c31·goal_pass·watch_pass 줄 → 등급, 60개까지
  2) 겹침     후보 쌍의 보유 기간 겹침·신호일 ±2거래일 근접 → s3/out/overlap.csv, 0.8 이상(양쪽) = 같은 묶음
  3) 함께 쓰기 묶음 대표 위 10개의 쌍: '둘 중 하나라도'·'둘 다 5거래일 안' → s3/out/together.csv (결과를 보고 고르는 숫자)
  4) 반증 시험 8개 → s3/out/falsify.csv, 7개 이상 버팀 = '버팀', 5~6 '부분', 그 아래 '무너짐'
  5) 보고서 초안 REPORT_draft.md, s3/out/candidates.json·done.json, 상태·카카오(--no-state 면 건드리지 않음)
사용: python sa_s3.py [--no-state] [--iters 2000]      환경 변수 SA_S3_TRACKS=t1,t2 (읽을 줄기, 기본 t1~t6)
"""
import argparse
import json
import os

import numpy as np
import pandas as pd

import sa_common as C

try:
    from sa_judge import NAMES
except Exception:                                                   # 판정 파일을 못 읽어도 이름만 없을 뿐 계속 간다
    NAMES = {}

TRACKS = [x.strip() for x in (os.environ.get('SA_S3_TRACKS') or 't1,t2,t3,t4,t5,t6').split(',') if x.strip()]
OUT = os.path.join(C.SA, 's3', 'out')
MAX_CANDS = 60          # 후보 상한
SAME = 0.8              # 보유 기간 겹침이 양쪽 모두 이 이상이면 '사실상 같은 신호'
NEAR = 2                # 신호일 근접: ±2거래일
TOP_TOGETHER = 10       # 함께 쓰기: 묶음 대표 위 10개
BOTH_WIN = 5            # '둘 다 켜짐' 창: 5거래일
MARGIN = 0.05           # 버팀: 적중 ≥ 바탕 + 5%p
KEEP = 0.70             # 버팀: 독립 거래 ≥ 원래의 70%
COST = 0.0015           # 왕복 비용 0.15%
ALPHA = 0.05            # ⑦ p < 0.05 (보정 없음)
MIN_PCT = 10            # 표본 10개 미만은 %로 말하지 않는다
REG_MIN = 20            # ⑥ (해, 장세 칸) 날 수가 이보다 적으면 그 칸의 전체 기간 적중으로 대신
GRADES = {1: '최종 후보', 2: '다음 해 기준 넘음', 3: '통과 숫자만', 4: '관찰'}
TESTS = ['① 하루 늦게 매수', '② 하루 일찍·늦게 청산', '③ 가장 좋았던 해 빼기', '④ 선물로 재기', '⑤ 비용 0.15%', '⑥ 장세 감안 바탕', '⑦ 날짜 옮기기 가짜', '⑧ 몰린 달 빼기']


# ------------------------------------------------------------------ 작은 도구
def _js(o):
    if hasattr(o, 'item'): return o.item()
    if isinstance(o, (pd.Timestamp,)): return str(o.date())
    return str(o)


def _read(p):
    try:
        return json.load(open(p, encoding='utf-8'))
    except Exception:
        return None


def _p(x, n=None, d=1):
    """% 로 적기. 표본(n)이 10개 미만이면 적지 않는다."""
    if x is None or (n is not None and (n or 0) < MIN_PCT): return '–'
    return C.pct(float(x), d)


def _pp(x, n=None):
    if x is None or (n is not None and (n or 0) < MIN_PCT) or not np.isfinite(x): return '–'
    return f'{100 * x:+.1f}%p'


def _sum(x):
    return '–' if x is None or not np.isfinite(x) else f'{100 * x:+.1f}%'


def _cut(s, n=70):
    s = str(s or '').replace('|', '/').replace('\n', ' ')
    return s if len(s) <= n else s[:n - 1] + '…'


def table(rows, cols, head):
    out = ['| ' + ' | '.join(head) + ' |', '|' + '---|' * len(head)]
    for r in rows: out.append('| ' + ' | '.join(str(f(r)) for f in cols) + ' |')
    return out


# ------------------------------------------------------------------ 1. 모으기
def grade_of(r):
    if r.get('final'): return 1
    if r.get('c31'): return 2
    if r.get('goal_pass'): return 3
    if r.get('watch_pass'): return 4
    return 0


def enrich(tr, d, px):
    """솎기 전 거래표에 ret(수익률)·hit(적중)를 다 채운다 — 후보가 미리 정한 값이 있으면 그것, 없으면 시가→종가. C.score 가 그대로 읽는다."""
    t = C.prep(tr); t = t[(t['signal'] >= C.START) & (t['exit'] <= C.END)].sort_values('signal').reset_index(drop=True)
    r = t['ret'].values.astype(float) if 'ret' in t else C.trade_returns(t, px)
    hit = (t['hit'].values.astype(float) > 0) if 'hit' in t else (d * r > 0)
    return pd.DataFrame({'signal': t['signal'].values, 'exit': t['exit'].values, 'ret': r, 'hit': hit.astype(int)})


def gather(D):
    """줄기별 판정을 읽어 후보 목록을 만든다. 반환 (후보 목록, 줄기 정보 {줄기: dict}, 잘린 수)."""
    info = {}; cands = []
    for tk in TRACKS:
        jd = _read(os.path.join(C.SA, tk, 'out', 'judge.json'))
        if not jd:
            info[tk] = None; continue
        rows = jd.get('rows') or []; info[tk] = {'judge': jd, 'n_rows': len(rows), 'note': ''}
        picked = [r for r in rows if grade_of(r)]
        if not picked: continue
        try:
            cs, _meta = C.load_result(tk); by = {c['id']: c for c in cs}
        except Exception as e:
            info[tk]['note'] = f'cands.pkl 을 못 읽어 후보 {len(picked)}개의 신호 날짜가 없음({type(e).__name__})'; continue
        jby = {r['id']: r for r in rows}; miss = 0
        for r in picked:
            c = by.get(r['id'])
            if c is None or c.get('trades') is None or not len(c['trades']): miss += 1; continue
            d = int(r.get('direction') or c.get('direction') or 1); raw = c['trades']
            w = jby.get(r.get('wf_of') or '') if r.get('kind') != 'wf' else None
            cands.append({'key': f"{tk}:{r['id']}", 'track': tk, 'id': r['id'], 'grade': grade_of(r), 'row': r, 'wf_row': w, 'd': d,
                          'h': int(r.get('hold') or 1), 'hold_fixed': bool(c.get('hold')), 'has_hit': 'hit' in raw, 'has_ret': 'ret' in raw, 'tr': enrich(raw, d, D.K),
                          'by': (C.base_arr(D, c.get('base_y')) if ('hit' in raw and c.get('base_y') is not None) else None),   # 보유일 없는 채점의 '아무 날' 채점표
                          'family': c.get('family'), 'params': c.get('params')})
        if miss: info[tk]['note'] = f'후보 {miss}개는 cands.pkl 에 신호 날짜가 없어 뺌'
    cands.sort(key=lambda c: (c['grade'], -(c['row'].get('edge') if c['row'].get('edge') is not None else -9), -(c['row'].get('all_n') or 0), c['key']))
    cut = max(0, len(cands) - MAX_CANDS)
    return cands[:MAX_CANDS], info, cut


def hlabel(c):
    return str(c['h']) if c['hold_fixed'] else f"정해진 보유일 없음(가운뎃값 {c['h']}일)"


def glabel(c):
    g = GRADES[c['grade']]
    return g + ('(결과를 보고 고른 숫자)' if c['grade'] == 3 and c['row'].get('kind') != 'wf' else '')


# ------------------------------------------------------------------ 바탕(아무 날)
class Base:
    """같은 해 아무 날 적중(가격·보유일별로 한 번만 계산)과 장세 감안 바탕."""

    def __init__(self, D):
        self.D = D; self.F = D.F.reindex(D.td); self._by = {}
        c = pd.Series(D.c, index=D.td); ma = c.rolling(60).mean(); vol = c.pct_change().rolling(20).std(); med = vol.rolling(250).median()
        ok = (ma.notna() & vol.notna() & med.notna()).values
        self.cell = np.where(ok, 2 * (c > ma).values.astype(int) + (vol > med).values.astype(int), -1)   # 0~3, 못 정하면 −1 (그날까지 자료만)
        self._reg = {}

    def by_year(self, h, d, fut=False):
        k = (int(h), int(d), bool(fut))
        if k not in self._by:
            D = self.D; r = D.fwd(int(h), px=self.F if fut else None); out = {}
            for y in np.unique(D.year):
                m = (D.year == y) & np.isfinite(r); out[int(y)] = (int(m.sum()), int((d * r[m] > 0).sum()))
            self._by[k] = out
        return self._by[k]

    def same_year(self, t, h, d, fut=False, by=None):
        """거래표 t 와 같은 해 구성으로 맞춘 아무 날 적중(판정의 C.base_for 와 같은 계산, 가격만 고를 수 있음). by(base_y)가 있으면 그 채점 방식으로."""
        if not len(t): return None
        if by is not None: return C.base_for(self.D, t, h, d, base_y=by)
        b = self.by_year(h, d, fut); y = pd.DatetimeIndex(t['signal']).year.values; num = den = 0.0
        for a in np.unique(y):
            nd, kd = b.get(int(a), (0, 0))
            if nd: num += (y == a).sum() * kd / nd; den += (y == a).sum()
        return float(num / den) if den else None

    def mixed(self, t, d):
        """거래마다 보유일이 다를 때(함께 쓰기): 거래마다 '그 해·자기 보유일'의 아무 날 적중을 구해 평균."""
        if not len(t): return None
        td = self.D.td; si = td.searchsorted(pd.DatetimeIndex(t['signal']), side='right'); ei = td.get_indexer(pd.DatetimeIndex(t['exit']))
        y = pd.DatetimeIndex(t['signal']).year.values; v = []
        for s, e, a in zip(si, ei, y):
            nd, kd = self.by_year(max(1, int(e - s + 1)), d).get(int(a), (0, 0))
            if nd: v.append(kd / nd)
        return float(np.mean(v)) if v else None

    def regime(self, t, h, d, by=None):
        """⑥ 장세 감안 바탕: 신호일과 같은 해·같은 장세 칸의 아무 날 적중을 거래 수로 가중 평균. by(base_y)가 있으면 아무 날을 그 채점 방식으로 잰다."""
        if not len(t): return None
        D = self.D; k = (int(h), int(d))
        if by is not None or k not in self._reg:
            if by is None: r = D.fwd(int(h)); fin = np.isfinite(r); w = d * r > 0
            else: fin = np.isfinite(by); w = np.where(fin, by, 0.0) > 0
            cellb = {}; yc = {}; yb = {}; since = D.td >= C.START
            for q in range(4):
                m = fin & since & (self.cell == q); cellb[q] = (float(w[m].mean()) if m.sum() else None)
            for y in np.unique(D.year):
                m = fin & (D.year == y); yb[int(y)] = float(w[m].mean()) if m.sum() else None
                for q in range(4):
                    m = fin & (D.year == y) & (self.cell == q)
                    yc[(int(y), q)] = float(w[m].mean()) if m.sum() >= REG_MIN else cellb[q]
            if by is None: self._reg[k] = (yc, yb)
        else: yc, yb = self._reg[k]
        pos = D.td.get_indexer(pd.DatetimeIndex(t['signal'])); v = []
        for p_, a in zip(pos, pd.DatetimeIndex(t['signal']).year.values):
            q = int(self.cell[p_]) if p_ >= 0 else -1; b = yc.get((int(a), q)) if q >= 0 else None
            if b is None: b = yb.get(int(a))
            if b is not None: v.append(b)
        return float(np.mean(v)) if v else None


# ------------------------------------------------------------------ 2. 겹침
def held_mask(D, t):
    """독립 거래가 들고 있는 날(매수일~청산일)."""
    m = np.zeros(D.n, dtype=bool)
    if not len(t): return m
    si = D.td.searchsorted(pd.DatetimeIndex(t['signal']), side='right'); ei = D.td.get_indexer(pd.DatetimeIndex(t['exit']))
    for s, e in zip(si, ei):
        if e >= s: m[s:e + 1] = True
    return m


def sig_mask(D, tr):
    m = np.zeros(D.n, dtype=bool)
    if len(tr):
        p = D.td.searchsorted(pd.DatetimeIndex(tr['signal']), side='right') - 1; m[p[p >= 0]] = True
    return m


def dilate(m, k):
    out = m.copy()
    for j in range(1, k + 1):
        out[j:] |= m[:-j]; out[:-j] |= m[j:]
    return out


def overlap(D, cands):
    """후보 쌍 전부의 겹침 표와 묶음 번호(cands 에 'cluster' 를 적음)."""
    n = len(cands); par = list(range(n))

    def find(x):
        while par[x] != x: par[x] = par[par[x]]; x = par[x]
        return x
    for c in cands:
        c['held'] = held_mask(D, c['t0']); c['sig'] = sig_mask(D, c['tr']); c['sig_d'] = dilate(c['sig'], NEAR)
    rows = []
    for i in range(n):
        for j in range(i + 1, n):
            a, b = cands[i], cands[j]; both = int((a['held'] & b['held']).sum()); na, nb = int(a['held'].sum()), int(b['held'].sum())
            oa = both / na if na else 0.0; ob = both / nb if nb else 0.0
            sa_, sb = int(a['sig'].sum()), int(b['sig'].sum())
            ga = float((a['sig'] & b['sig_d']).sum() / sa_) if sa_ else 0.0; gb = float((b['sig'] & a['sig_d']).sum() / sb) if sb else 0.0
            same_dir = a['d'] == b['d']; same = bool(same_dir and min(oa, ob) >= SAME)
            if same: par[find(i)] = find(j)
            rows.append({'a': a['key'], 'b': b['key'], '방향_같음': same_dir, '독립거래_a': len(a['t0']), '독립거래_b': len(b['t0']), '보유일수_a': na, '보유일수_b': nb,
                         '겹침_a기준': round(oa, 3), '겹침_b기준': round(ob, 3), '신호근접_a기준': round(ga, 3), '신호근접_b기준': round(gb, 3),
                         '판정': '사실상 같은 신호' if same else ('한쪽이 다른 쪽에 포함' if same_dir and max(oa, ob) >= SAME else '')})
    num = {}
    for i, c in enumerate(cands):                                   # 묶음 번호는 등급 순(cands 가 이미 등급 순)
        r = find(i); num.setdefault(r, len(num) + 1); c['cluster'] = num[r]
    key2cl = {c['key']: c['cluster'] for c in cands}
    for r in rows: r['묶음_a'] = key2cl[r['a']]; r['묶음_b'] = key2cl[r['b']]
    cols = ['a', 'b', '묶음_a', '묶음_b', '방향_같음', '독립거래_a', '독립거래_b', '보유일수_a', '보유일수_b', '겹침_a기준', '겹침_b기준', '신호근접_a기준', '신호근접_b기준', '판정']
    return pd.DataFrame(rows, columns=cols)


# ------------------------------------------------------------------ 3. 함께 쓰기
def _sc(D, B, tr, d):
    a = C.score(tr, d, D.K); t = a['t']; base = B.mixed(t, d) if a['n'] else None
    return {'n': a['n'], 'hit': a['hit'], 'sum': a['sum'], 'base': base, 'edge': (a['hit'] - base) if (a['n'] and base is not None) else None}


def together(D, B, cands):
    reps = []; seen = set()
    for c in cands:
        if c['cluster'] not in seen: seen.add(c['cluster']); reps.append(c)
    reps = reps[:TOP_TOGETHER]; rows = []
    for i in range(len(reps)):
        for j in range(i + 1, len(reps)):
            a, b = reps[i], reps[j]
            if a['d'] != b['d']: continue
            d = a['d']; ta, tb = a['tr'], b['tr']
            pa = D.td.searchsorted(pd.DatetimeIndex(ta['signal']), side='right') - 1; pb = D.td.searchsorted(pd.DatetimeIndex(tb['signal']), side='right') - 1
            ma = np.zeros(D.n, dtype=bool); ma[pa[pa >= 0]] = True; mb = np.zeros(D.n, dtype=bool); mb[pb[pb >= 0]] = True
            # 둘 중 하나라도: 같은 날이면 a(등급 높은 쪽) 거래
            either = pd.concat([ta, tb[~ma[pb]]], ignore_index=True)
            # 둘 다 5거래일 안: 나중에 난 쪽 거래. a 는 b 가 [p−5, p] 에, b 는 a 가 [p−5, p−1] 에 있을 때
            cb = np.r_[0, np.cumsum(mb)]; ca = np.r_[0, np.cumsum(ma)]
            cnt = lambda cs, lo, hi: cs[np.clip(hi + 1, 0, D.n)] - cs[np.clip(lo, 0, D.n)]
            ka = cnt(cb, pa - BOTH_WIN, pa) > 0; kb = cnt(ca, pb - BOTH_WIN, pb - 1) > 0
            both = pd.concat([ta[ka], tb[kb]], ignore_index=True)
            for name, tr in (('둘 중 하나라도', either), (f'둘 다 {BOTH_WIN}거래일 안에 켜짐', both)):
                s = _sc(D, B, tr, d)
                rows.append({'주의': '결과를 보고 고르는 숫자(다음 해 성적 아님)', 'a': a['key'], 'b': b['key'], '방향': d, '방식': name, '독립거래': s['n'],
                             '적중': None if s['n'] < MIN_PCT else round(s['hit'], 4), '수익합계': round(s['sum'], 5),
                             '같은해_아무날': None if s['n'] < MIN_PCT or s['base'] is None else round(s['base'], 4),
                             '차이': None if s['n'] < MIN_PCT or s['edge'] is None else round(s['edge'], 4),
                             'a_독립거래': a['row'].get('all_n'), 'a_적중': a['row'].get('all_hit'), 'b_독립거래': b['row'].get('all_n'), 'b_적중': b['row'].get('all_hit')})
    cols = ['주의', 'a', 'b', '방향', '방식', '독립거래', '적중', '수익합계', '같은해_아무날', '차이', 'a_독립거래', 'a_적중', 'b_독립거래', 'b_적중']
    return pd.DataFrame(rows, columns=cols), [c['key'] for c in reps]


# ------------------------------------------------------------------ 4. 반증 시험
def shifted(D, tr, ds=0, de=0):
    """솎기 전 거래의 신호일을 ds, 청산일을 de 거래일 옮긴 [signal, exit]. 청산이 매수일보다 앞서면 매수일로 맞춘다(보유 1일). 자료 밖은 뺀다."""
    if not len(tr): return pd.DataFrame({'signal': [], 'exit': []}), 0
    s = D.td.searchsorted(pd.DatetimeIndex(tr['signal']), side='right') - 1 + ds; e = D.td.get_indexer(pd.DatetimeIndex(tr['exit']))
    ok = (e >= 0) & (s >= 0); s = s[ok]; e0 = e[ok]; e = np.maximum(e0 + de, s + 1); ok = (e < D.n) & (s < D.n)
    moved = int(((e != e0) & ok).sum()) if de else 0
    return pd.DataFrame({'signal': D.td[s[ok]], 'exit': D.td[e[ok]]}), moved


def falsify(D, B, c, iters):
    """후보 하나의 반증 시험 8개. 반환 (표 줄들, 요약 dict)."""
    d = c['d']; h = c['h']; tr = c['tr']; t0 = c['t0']; n0 = len(t0); R = []
    ok0 = t0['ok'].values.astype(bool) if n0 else np.zeros(0, dtype=bool); r0 = t0['ret'].values.astype(float) if n0 else np.zeros(0)
    y0 = pd.DatetimeIndex(t0['signal']).year.values if n0 else np.zeros(0, dtype=int)
    by = c.get('by'); hit0 = float(ok0.mean()) if n0 else None; base0 = B.same_year(t0, h, d, by=by) if n0 else None
    re = '수익 부호로 다시 채점' if (c['has_hit'] or c['has_ret']) else ''

    def add(no, sub, name, n, hit, base, sm, p=None, note='', alone=False):
        if n0 < MIN_PCT: ok = False; note = (note + ' ' if note else '') + '원래 표본 10 미만'
        elif alone: ok = bool(p is not None and p < ALPHA)
        else:
            ok = bool(n >= MIN_PCT and n >= KEEP * n0 - 1e-9 and hit is not None and base is not None and hit - base >= MARGIN - 1e-12)
            if n < MIN_PCT: note = (note + ' ' if note else '') + '남은 표본 10 미만'
        R.append({'후보': c['key'], '등급': GRADES[c['grade']], '시험': no, '갈래': sub, '이름': name, '독립거래': int(n), '원래의_비율': (round(n / n0, 3) if n0 else None),
                  '적중': (None if hit is None or n < MIN_PCT else round(hit, 4)), '바탕': (None if base is None else round(base, 4)),
                  '차이': (None if hit is None or base is None or n < MIN_PCT else round(hit - base, 4)), '수익합계': (None if sm is None else round(sm, 5)),
                  'p': (None if p is None else round(p, 4)), '버팀': ok, '비고': note})
        return ok

    def rescore(no, sub, name, trades, hh, fut=False, note=''):
        a = C.score(trades, d, B.F if fut else D.K); base = B.same_year(a['t'], hh, d, fut) if a['n'] else None
        return add(no, sub, name, a['n'], a['hit'], base, a['sum'], note=' '.join(x for x in (re, note) if x))

    R.append({'후보': c['key'], '등급': GRADES[c['grade']], '시험': 0, '갈래': '', '이름': '원래(판정과 같은 계산)', '독립거래': n0, '원래의_비율': 1.0 if n0 else None,
              '적중': (None if n0 < MIN_PCT else round(hit0, 4)), '바탕': (None if base0 is None else round(base0, 4)),
              '차이': (None if n0 < MIN_PCT or base0 is None else round(hit0 - base0, 4)), '수익합계': round(float((d * r0).sum()), 5), 'p': None, '버팀': None,
              '비고': ('바탕 = 같은 채점 방식의 아무 날(base_y) ' if by is not None else '') + ('' if c['row'].get('all_n') == n0 and abs((c['row'].get('all_hit') or 0) - (hit0 or 0)) < 1e-9 else f"판정 숫자와 다름(판정 {c['row'].get('all_n')}거래)")})
    res = {}
    # ① 하루 더 늦게 매수
    s1, _ = shifted(D, tr, ds=1); res[1] = rescore(1, '', '하루 더 늦게 매수', s1, max(1, h - 1))
    # ② 하루 일찍 청산 · 하루 늦게 청산 (둘 다 버텨야 버팀. 보유 1일짜리는 늦게만)
    s2a, moved = shifted(D, tr, de=-1); s2b, _ = shifted(D, tr, de=1)
    oka = rescore(2, '가', '하루 일찍 청산', s2a, max(1, h - 1)) if moved else True
    okb = rescore(2, '나', '하루 늦게 청산', s2b, h + 1, note='' if moved else '보유 1일이라 일찍 청산은 없음'); res[2] = bool(oka and okb)
    # ③ 가장 좋았던 해 하나 빼기 (뺐을 때 남은 적중이 가장 낮아지는 해)
    if n0:
        best = None
        for y in np.unique(y0):
            m = y0 != y; v = (float(ok0[m].mean()) if m.any() else -1.0, -float((d * r0[~m]).sum()))
            if best is None or v < best[0]: best = (v, int(y))
        m = y0 != best[1]; res[3] = add(3, '', '가장 좋았던 해 하나 빼기', int(m.sum()), float(ok0[m].mean()) if m.any() else None, B.same_year(t0[m], h, d, by=by),
                                        float((d * r0[m]).sum()), note=f'뺀 해 {best[1]}({int((~m).sum())}거래)')
    else: res[3] = add(3, '', '가장 좋았던 해 하나 빼기', 0, None, None, None)
    # ④ 코스피200 선물로 바꿔 재기
    res[4] = rescore(4, '', '코스피200 선물로 재기', tr[['signal', 'exit']], h, fut=True)
    # ⑤ 왕복 비용 0.15% 빼기 (바탕에는 비용을 빼지 않는다)
    okc = ok0 if c['has_hit'] else (d * r0 - COST > 0)
    res[5] = add(5, '', '왕복 비용 0.15% 빼기', n0, float(okc.mean()) if n0 else None, base0, float((d * r0 - COST).sum()) if n0 else None,
                 note='미리 정한 적중(hit)은 그대로, 수익 합계만 줄어듦' if c['has_hit'] else '')
    # ⑥ 장세 감안 바탕
    res[6] = add(6, '', '장세 감안 바탕', n0, hit0, B.regime(t0, h, d, by=by) if n0 else None, float((d * r0).sum()) if n0 else None)
    # ⑦ 같은 해 안 날짜 옮기기 가짜 (보정 없이 원래 p)
    pl = C.placebo_same_year(D, t0, d, h=h, n_iter=iters, base_y=by) if n0 >= MIN_PCT else {'p': None}
    res[7] = add(7, '', f'같은 해 안 날짜 옮기기 가짜 {iters:,}번', n0, pl.get('real'), pl.get('fake_mean'), None, p=pl.get('p'), alone=True,
                 note='바탕 칸 = 가짜 평균 적중' + (', 실제·가짜 모두 같은 채점 방식(base_y)' if by is not None else (', 실제도 보유일 수익 부호로 채점' if c['has_hit'] or c['has_ret'] else '')))
    # ⑧ 신호가 몰린 달 하나 빼기 (독립 거래가 가장 많은 달)
    if n0:
        mon = pd.DatetimeIndex(t0['signal']).to_period('M'); g = pd.DataFrame({'m': mon.astype(str), 'ok': ok0}).groupby('m')['ok'].agg(['size', 'sum']).reset_index()
        g = g.sort_values(['size', 'sum', 'm'], ascending=[False, False, True]); mm = g.iloc[0]['m']; m = np.asarray(mon.astype(str) != mm)
        res[8] = add(8, '', '신호가 몰린 달 하나 빼기', int(m.sum()), float(ok0[m].mean()) if m.any() else None, B.same_year(t0[m], h, d, by=by), float((d * r0[m]).sum()),
                     note=f"뺀 달 {mm}({int(g.iloc[0]['size'])}거래)")
    else: res[8] = add(8, '', '신호가 몰린 달 하나 빼기', 0, None, None, None)
    k = int(sum(res.values()))
    verdict = '판정 불가' if n0 < MIN_PCT else ('버팀' if k >= 7 else ('부분' if k >= 5 else '무너짐'))
    R.append({'후보': c['key'], '등급': GRADES[c['grade']], '시험': 9, '갈래': '', '이름': '종합', '독립거래': n0, '원래의_비율': None, '적중': None, '바탕': None, '차이': None, '수익합계': None,
              'p': None, '버팀': verdict == '버팀', '비고': f'8개 중 {k}개 버팀 → {verdict}'})
    return R, {'tests': {str(i): bool(res[i]) for i in range(1, 9)}, 'n_hold': k, 'verdict': verdict, 'p_raw': pl.get('p'), 'rescored': bool(re)}


# ------------------------------------------------------------------ 5. 보고서 초안
def track_line(tk, inf, S):
    name = NAMES.get(tk, tk); rp = os.path.join(C.SA, tk, 'report.md'); link = f'[보고서]({tk}/report.md)' if os.path.exists(rp) else '없음'
    if not inf:
        st = (S.get('tracks') or {}).get(tk)
        return [name, f'결과 없음({st})' if st else '결과 없음', '–', '–', '–', '–', '–', '–', link]
    jd = inf['judge']; sm = jd.get('summary') or {}
    if tk == 't6':                                                  # T6(청산)은 등급을 매기지 않는다 — 청산 방법 비교일 뿐
        return [name, '청산 비교(등급 없음) — t6/report.md', f"{int(jd.get('n_tested') or 0):,}", '–', '–', '–', '–', '–', link]
    wf = [r for r in jd.get('rows', []) if r.get('kind') == 'wf' and (r.get('all_n') or 0) >= MIN_PCT and r.get('edge') is not None]
    b = max(wf, key=lambda r: r['edge']) if wf else None
    best = f"{_p(b['all_hit'])} 대 아무 날 {_p(b['base'])} ({b['all_n']}거래)" if b else '다음 해 성적 낼 절차 없음'
    return [name, '끝' + (f" · {inf['note']}" if inf.get('note') else ''), f"{int(jd.get('n_tested') or 0):,}", sm.get('pass', 0), sm.get('watch', 0), sm.get('c31', 0), sm.get('final', 0), best, link]


def report(cands, info, cut, ov, tg, reps, fz, S, wish, now, iters):
    L = _read(os.path.join(C.STATE, 'ledger.json')) or {}
    done = [tk for tk in TRACKS if info.get(tk)]; tot = lambda k: sum(int((info[tk]['judge'].get('summary') or {}).get(k, 0) or 0) for tk in done)
    ng = {g: sum(c['grade'] == g for c in cands) for g in GRADES}
    nv = {v: sum(c['fz']['verdict'] == v for c in cands) for v in ('버팀', '부분', '무너짐', '판정 불가')}
    M = [f'# Signal A 보고서 초안 — S3 통합 ({now}, 자료 끝 {C.END.date()})', '',
         '> 이 문서는 GitHub 가 자동으로 만든 초안이다. 숫자·표는 자동, **결론은 총괄이 최종 심사 뒤에 채운다.**', '',
         '## 결론', '', '(총괄이 최종 심사 뒤 채움)', '', '자동 요약(숫자만):', '',
         f"- 판정이 끝난 줄기 {len(done)}개 / {len(TRACKS)}개" + (f" (결과 없음: {', '.join(t for t in TRACKS if not info.get(t))})" if len(done) < len(TRACKS) else ''),
         f"- 줄기 합계: 시험 {sum(int(info[t]['judge'].get('n_tested') or 0) for t in done):,}가지 · 통과 숫자 {tot('pass')}개 · 관찰 {tot('watch')}개 · 다음 해 기준 넘음 {tot('c31')}개 · 최종 후보 {tot('final')}개",
         f"- 원장(state/ledger.json)에 적힌 누적 시험 가짓수: {int(L.get('total') or 0):,}가지 (줄기 {len(L.get('trials') or [])}개 기록)",
         (f"- S3 후보 {len(cands)}개 = 최종 후보 {ng[1]} · 다음 해 기준 넘음 {ng[2]} · 통과 숫자만 {ng[3]} · 관찰 {ng[4]}" + (f' (등급·차이 순 {MAX_CANDS}개만, {cut}개는 잘림)' if cut else '')
          if cands else '- **후보 없음** — 최종 후보·다음 해 기준 넘음·통과 숫자·관찰 등급에 든 신호가 하나도 없다.')]
    if cands:
        M.append(f"- 반증 시험 8개 종합: 버팀 {nv['버팀']}개 · 부분 {nv['부분']}개 · 무너짐 {nv['무너짐']}개" + (f" · 판정 불가 {nv['판정 불가']}개" if nv['판정 불가'] else '')
                 + f" · 서로 다른 신호 묶음 {len(set(c['cluster'] for c in cands))}개")
    M += ['- 매매 기준: 코스피 지수, 신호 다음 날 시가 매수 → 정한 날 종가 매도, 수익 합계는 거래별 단순 합. 표본 10개 미만은 %를 적지 않는다.', '',
          '## 1. 줄기별 요약', '']
    M += table([track_line(tk, info.get(tk), S) for tk in TRACKS], [(lambda r, i=i: r[i]) for i in range(9)],
               ['줄기', '상태', '시험 가짓수', '통과 숫자', '관찰', '다음 해 기준 넘음', '최종 후보', '다음 해 성적이 가장 좋은 절차', '줄기 보고서'])
    M += ['', '## 2. 후보', '']
    if not cands:
        M += ['**후보 없음.** 아래 표는 비어 있다.', '']
    else:
        M += ['등급: 최종 후보(통과 숫자 + 우연 거르기 셋 다) > 다음 해 기준 넘음(아무 날 +10%p·30거래) > 통과 숫자만 > 관찰.',
              '**전체 기간 적중은 결과를 보고 고른 숫자, 다음 해 적중은 해마다 그 전 자료로만 고른 숫자다 — 섞어 읽지 말 것.**', '']

    def full_hit(c):
        r = c['row']
        return '–' if r.get('kind') == 'wf' else f"{_p(r.get('all_hit'), r.get('all_n'))} ({r.get('all_n')}거래)"

    def next_hit(c):
        r = c['row'] if c['row'].get('kind') == 'wf' else c.get('wf_row')
        if not r: return '–'
        return f"{_p(r.get('all_hit'), r.get('all_n'))} ({r.get('all_n')}거래, 아무 날 {_p(r.get('base'), r.get('all_n'))})"
    M += table(cands, [lambda c: c['no'], lambda c: glabel(c), lambda c: c['track'].upper(), lambda c: _cut(c['row'].get('desc')), lambda c: '오름' if c['d'] > 0 else '내림', hlabel,
                       lambda c: c['row'].get('all_n'), full_hit, next_hit, lambda c: _p(c['row'].get('base'), c['row'].get('all_n')), lambda c: _sum(c['row'].get('all_sum')),
                       lambda c: f"{c['row'].get('y26_n', 0)}건 {_p(c['row'].get('y26_hit'), c['row'].get('y26_n'))}",
                       lambda c: f"{c['row'].get('big_n', 0)}건 {_p(c['row'].get('big_hit'), c['row'].get('big_n'))}",
                       lambda c: f"{c['fz']['verdict']}({c['fz']['n_hold']}/8)", lambda c: c['cluster']],
               ['번호', '등급', '줄기', '규칙', '방향', '보유일', '독립 거래', '전체 기간 적중(결과를 보고 고른 숫자)', '다음 해 적중(그 전 자료로 고름)', '같은 해 아무 날', '수익 합계', '2026년', '큰 변동 해(2011·2020·2026)', '반증 종합', '묶음'])
    if os.path.exists(os.path.join(C.SA, 't6', 'out', 'summary.md')):
        M += ['', '- 청산 방법 비교(T6, 등급 없음 — 후보 표에 넣지 않음): [t6/out/summary.md](t6/out/summary.md)']
    M += ['', '## 3. 겹침 (같은 신호를 두 번 세지 않기)', '']
    if len(cands) < 2:
        M += ['후보가 2개 미만이라 겹침 표 없음.']
    else:
        M += [f'보유 기간이 양쪽 기준 모두 {SAME:.0%} 이상 겹치고 방향이 같으면 사실상 같은 신호로 보고 한 묶음으로 센다. 전부는 s3/out/overlap.csv.', '']
        cl = {}
        for c in cands: cl.setdefault(c['cluster'], []).append(c)
        M += table(sorted(cl.items()), [lambda kv: kv[0], lambda kv: len(kv[1]), lambda kv: f"{kv[1][0]['no']}번 {_cut(kv[1][0]['row'].get('desc'), 50)}",
                                        lambda kv: ', '.join(f"{c['no']}번" for c in kv[1][1:]) or '–'], ['묶음', '후보 수', '대표(등급·차이 맨 위)', '같은 묶음의 다른 후보'])
        o = ov.assign(_m=ov[['겹침_a기준', '겹침_b기준']].min(axis=1)); o = o[o['묶음_a'] != o['묶음_b']].sort_values('_m', ascending=False).head(10)
        if len(o):
            no = {c['key']: c['no'] for c in cands}
            M += ['', '묶음이 다른 쌍 가운데 많이 겹치는 순(10개까지):', '']
            M += table(o.to_dict('records'), [lambda r: f"{no[r['a']]}번", lambda r: f"{no[r['b']]}번", lambda r: f"{r['겹침_a기준']:.0%}", lambda r: f"{r['겹침_b기준']:.0%}",
                                              lambda r: f"{r['신호근접_a기준']:.0%}", lambda r: f"{r['신호근접_b기준']:.0%}", lambda r: r['판정'] or '–'],
                       ['후보 a', '후보 b', '보유 겹침(a 기준)', '보유 겹침(b 기준)', f'신호일 ±{NEAR}일(a 기준)', f'신호일 ±{NEAR}일(b 기준)', '비고'])
    M += ['', '## 4. 함께 쓰기 (**결과를 보고 고르는 숫자** — 다음 해 성적이 아니므로 그대로 믿지 말 것)', '']
    if not len(tg):
        M += ['묶음이 다르고 방향이 같은 후보 쌍이 없어 표 없음.']
    else:
        no = {c['key']: c['no'] for c in cands}
        M += [f'묶음 대표 위 {TOP_TOGETHER}개({", ".join(str(no[k]) + "번" for k in reps)}) 안의 쌍. 차이 큰 순 20줄까지, 전부는 s3/out/together.csv.', '']
        t = tg.assign(_e=tg['차이'].fillna(-9)).sort_values(['_e', '독립거래'], ascending=[False, False]).head(20)
        M += table(t.to_dict('records'), [lambda r: f"{no[r['a']]}번 + {no[r['b']]}번", lambda r: r['방식'], lambda r: r['독립거래'], lambda r: _p(r['적중'] if pd.notna(r['적중']) else None),
                                          lambda r: _p(r['같은해_아무날'] if pd.notna(r['같은해_아무날']) else None), lambda r: _pp(r['차이'] if pd.notna(r['차이']) else None),
                                          lambda r: _sum(r['수익합계']), lambda r: f"{r['a_독립거래']}거래 {_p(r['a_적중'], r['a_독립거래'])} / {r['b_독립거래']}거래 {_p(r['b_적중'], r['b_독립거래'])}"],
                   ['쌍', '방식', '독립 거래', '적중', '같은 해 아무 날', '차이', '수익 합계', '따로 쓸 때(a / b)'])
    M += ['', '## 5. 반증 시험 (깨 보려는 시험 8개 — 목록·버팀 기준은 s3/SPEC.md 에 미리 고정)', '']
    if not cands:
        M += ['후보가 없어 표 없음.']
    else:
        M += [f'버팀(O) = 적중이 바탕(같은 해 아무 날, ⑥은 장세 감안 바탕)보다 {MARGIN * 100:.0f}%p 이상 높고 독립 거래가 원래의 {KEEP:.0%} 이상 남음. ⑦은 가짜 {iters:,}번의 p < {ALPHA}(보정 없음).',
              '종합: 7개 이상 버팀 = 버팀, 5~6개 = 부분, 4개 이하 = 무너짐. 칸 안 숫자는 그 시험의 적중률(⑦은 p). 자세한 숫자는 s3/out/falsify.csv.', '']
        fb = {}
        for r in fz.to_dict('records'): fb.setdefault(r['후보'], {}).setdefault(int(r['시험']), []).append(r)

        def cell(c, i):
            rs = fb.get(c['key'], {}).get(i, []); ok = c['fz']['tests'][str(i)]
            v = ' / '.join((f"p {r['p']:.3f}" if i == 7 and pd.notna(r['p']) else _p(r['적중'] if pd.notna(r['적중']) else None)) for r in rs)
            return f"{'O' if ok else 'X'} {v}"
        M += table(cands, [lambda c: c['no'], lambda c: _cut(c['row'].get('desc'), 40), lambda c: f"{len(c['t0'])}거래 {_p(c['row'].get('all_hit'), c['row'].get('all_n'))}"]
                   + [(lambda c, i=i: cell(c, i)) for i in range(1, 9)] + [lambda c: f"**{c['fz']['verdict']}** ({c['fz']['n_hold']}/8)"],
                   ['번호', '규칙', '원래'] + TESTS + ['종합'])
        if any(c['fz']['rescored'] for c in cands):
            M += ['', '- 미리 정한 적중(±k% 먼저 닿기)이나 손절·익절 수익을 가진 후보는 ①②④에서 시가→종가 수익의 부호로 다시 채점했다(번호: '
                  + ', '.join(f"{c['no']}번" for c in cands if c['fz']['rescored']) + ').']
    M += ['', '## 6. 아쉬운 줄기 (자동으로 다시 돌리지 않음 — 사용자가 정함)', '']
    M += [f'- {w}' for w in wish] or ['- 없음']
    M += ['', '## 7. 다음 프로젝트 인계 (새 자료로 실전 확인) — 뼈대', '',
          f'- 고정 자료는 {C.END.date()} 까지다. 그 뒤에 쌓이는 자료는 이 연구에 쓰지 않았고, 다음 프로젝트에서 확인에 쓴다.',
          '- 확인할 신호: signals/final_v1.json (총괄이 5개 이하로 추려 규칙·문턱·보유일을 고정) — (총괄이 채움)',
          '- **최종 후보도 새 자료에서 실제 신호 10건이 쌓이기 전에는 확정이라고 쓰지 않는다**(CRITERIA 4절). 그 전에는 "확인 중"으로만 적는다.',
          '- 적는 법: 신호가 난 날·매수가(다음 날 시가)·청산일·종가·수익을 그때그때 기록하고, 규칙·문턱은 바꾸지 않는다. 바꾸면 새 신호로 치고 0건부터 다시 센다.',
          '- 중간 점검 기준(몇 건에서 무엇을 볼지)과 그만둘 기준 — (총괄이 채움)', '']
    if cands:
        top = [c for c in cands if c['grade'] <= 2][:10] or cands[:5]
        yrs = lambda c: max(1.0, (C.END - max(C.START, pd.Timestamp(f'{C.WF_YEARS[0]}-01-01') if c['row'].get('kind') == 'wf' else C.START)).days / 365.25)

        def pace(c):
            v = (c['row'].get('all_n') or 0) / yrs(c)
            return f'{v:.1f}건', (f'약 {10 / v:.1f}년' if v > 0 else '–')
        M += ['과거 빈도로 어림한 "신호 10건이 쌓이는 데 걸리는 기간"(어림일 뿐, 앞으로 같다는 보장 없음):', '']
        M += table(top, [lambda c: c['no'], lambda c: glabel(c), lambda c: _cut(c['row'].get('desc'), 50), hlabel, lambda c: pace(c)[0], lambda c: pace(c)[1]],
                   ['번호', '등급', '규칙', '보유일', '한 해 평균 독립 거래', '10건까지'])
    else:
        M += ['후보가 없으므로 넘길 신호도 없다. 다음 프로젝트를 할지는 6절(아쉬운 줄기)을 보고 사용자가 정한다.']
    M += ['', '투자 권유 아님']
    return '\n'.join(M) + '\n'


# ------------------------------------------------------------------ 실행
def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--no-state', action='store_true'); ap.add_argument('--iters', type=int, default=2000)
    a = ap.parse_args(); os.makedirs(OUT, exist_ok=True); now = pd.Timestamp.now(tz='Asia/Seoul').strftime('%Y-%m-%d %H:%M')
    D = C.Data(); B = Base(D); S = _read(os.path.join(C.STATE, 'status.json')) or {}
    cands, info, cut = gather(D)
    for i, c in enumerate(cands):
        c['no'] = i + 1; c['t0'] = C.score(c['tr'], c['d'], D.K)['t']
    ov = overlap(D, cands); ov.to_csv(os.path.join(OUT, 'overlap.csv'), index=False, encoding='utf-8')
    tg, reps = together(D, B, cands); tg.to_csv(os.path.join(OUT, 'together.csv'), index=False, encoding='utf-8')
    frows = []
    for c in cands:
        R, c['fz'] = falsify(D, B, c, a.iters); frows += R
    fcols = ['후보', '등급', '시험', '갈래', '이름', '독립거래', '원래의_비율', '적중', '바탕', '차이', '수익합계', 'p', '버팀', '비고']
    fz = pd.DataFrame(frows, columns=fcols); fz.to_csv(os.path.join(OUT, 'falsify.csv'), index=False, encoding='utf-8')
    wish = []
    for w in list(S.get('wish') or []) + [w for tk in TRACKS if info.get(tk) for w in (info[tk]['judge'].get('wish') or [])]:
        if w not in wish: wish.append(w)
    open(os.path.join(C.SA, 'REPORT_draft.md'), 'w', encoding='utf-8').write(report(cands, info, cut, ov, tg, reps, fz, S, wish, now, a.iters))
    keep = ('kind', 'family', 'desc', 'wf_of', 'n_signals', 'all_n', 'all_k', 'all_hit', 'all_lb', 'all_sum', 'all_mean', 'p1_n', 'p1_hit', 'p2_n', 'p2_hit', 'base', 'edge', 'goal_pass', 'watch_pass',
            'c31', 'c32', 'c33', 'c33_same', 'c33_big', 'final', 'fake_p', 'fake_p_adj', 'fake_m', 'ex26_n', 'ex26_hit', 'ex26_base', 'y26_n', 'y26_hit', 'big_n', 'big_hit', 'big_base', 'by_year')
    out = []
    for c in cands:
        r = c['row']; w = c['row'] if r.get('kind') == 'wf' else c.get('wf_row')
        o = {'no': c['no'], 'key': c['key'], 'track': c['track'], 'id': c['id'], 'grade': c['grade'], 'grade_label': glabel(c), 'direction': c['d'], 'hold': c['h'], 'hold_fixed': c['hold_fixed'], 'cluster': c['cluster'],
             'cluster_rep': all(x['cluster'] != c['cluster'] or x['no'] >= c['no'] for x in cands)}
        o.update({k: r.get(k) for k in keep})
        o['full_period'] = None if r.get('kind') == 'wf' else {'n': r.get('all_n'), 'hit': r.get('all_hit'), 'sum': r.get('all_sum')}          # 결과를 보고 고른 숫자
        o['next_year'] = None if not w else {'id': w.get('id'), 'n': w.get('all_n'), 'hit': w.get('all_hit'), 'base': w.get('base'), 'edge': w.get('edge'), 'sum': w.get('all_sum')}
        o['falsify'] = c['fz']; o['params'] = c.get('params'); o['has_hit'] = c['has_hit']; o['has_ret'] = c['has_ret']; o['base_y_used'] = c.get('by') is not None
        o['first_signal'] = str(c['tr']['signal'].min().date()) if len(c['tr']) else None; o['last_signal'] = str(c['tr']['signal'].max().date()) if len(c['tr']) else None
        out.append(o)
    ng = {g: sum(c['grade'] == g for c in cands) for g in GRADES}; nhold = sum(c['fz']['verdict'] == '버팀' for c in cands)
    json.dump({'at': now, 'data_end': str(C.END.date()), 'tracks': TRACKS, 'tracks_read': [t for t in TRACKS if info.get(t)], 'n_cut': cut, 'together_reps': reps,
               'note': 'full_period = 결과를 보고 고른 숫자, next_year = 해마다 그 전 자료로 고른 절차의 성적. 섞어 쓰지 말 것. 최종 후보도 새 자료 신호 10건 전에는 확정 아님.',
               'candidates': out}, open(os.path.join(OUT, 'candidates.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=_js)
    done = {'at': now, 'n_cands': len(cands), 'n_final': ng[1], 'n_c31': ng[2], 'n_goal_only': ng[3], 'n_watch': ng[4], 'n_cut': cut, 'n_clusters': len(set(c['cluster'] for c in cands)),
            'n_falsify_hold': nhold, 'n_falsify_part': sum(c['fz']['verdict'] == '부분' for c in cands), 'n_falsify_broken': sum(c['fz']['verdict'] == '무너짐' for c in cands),
            'tracks_read': [t for t in TRACKS if info.get(t)], 'tracks_missing': [t for t in TRACKS if not info.get(t)], 'iters': a.iters}
    json.dump(done, open(os.path.join(OUT, 'done.json'), 'w', encoding='utf-8'), ensure_ascii=False)
    msg = ((f"[Signal A] 통합 끝. 후보 {len(cands)}개(최종 후보 {ng[1]}·다음 해 기준 {ng[2]}·통과 숫자만 {ng[3]}·관찰 {ng[4]}). 반증 버팀 {nhold}개." if cands
            else '[Signal A] 통합 끝. 후보 없음(최종 후보 0·다음 해 기준 0·관찰 0).') + (f' 아쉬운 줄기 {len(wish)}건.' if wish else '') + ' 다음: 총괄 최종 심사.')[:198]
    print(msg)
    if a.no_state: return
    os.makedirs(os.path.join(C.SA, 'notify'), exist_ok=True)
    open(os.path.join(C.SA, 'notify', 'kakao_s3.txt'), 'w', encoding='utf-8').write(msg + '\n')
    S = C.read_status(); S['stage'] = 'S3 끝'; S['need_claude'] = True; S['why'] = '최종 심사·보고서 결론 차례'; S['next'] = 'Claude 최종 심사 → signals/final_v1.json·REPORT.md'
    C.write_status(S)


if __name__ == '__main__':
    main()
