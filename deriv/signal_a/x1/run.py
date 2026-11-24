# -*- coding: utf-8 -*-
"""Signal A X1 — 연구소 갈래 A·B·C·D 상위 100위 거름 시험. 미리 정한 목록은 x1/SPEC.md 에 있고 이 파일은 그대로 구현한다.

  1) 순위: 갈래별 모든 round_*/leaderboard.csv → desc 같은 것은 최근 회차만 → 통과 P → 관찰 W → all_lb 내림차순 상위 100개(D 는 방향 −1 만)
  2) 거래일: 그 회차 candidates.pkl → 다른 회차(같은 id·desc + 앞 구간 숫자 일치) → 갈래 C 는 미국 지표로 다시 만듦 → 못 구하면 '확인 불가'
  3) (가) 후보마다 네 거름: ① 2016~2026 거래로 아무 날 +10%p·30건(결과를 보고 고른 규칙의 숫자) ② 2026년·큰 변동 해 ③ 반증 8개 모두 ④ 가짜 2,000번 p < 1%
  4) (나) 갈래별 '해마다 고르는 절차' 20개(모두 80개)에 같은 네 거름
  5) Signal A 관찰 목록 3개와 겹침, 보고서(x1/report.md)·표(x1/out)·카카오 글(x1/notify/kakao.txt)·원장(state/ledger.json 의 x1)·log.md 한 줄
기준 숫자는 CRITERIA.md·sa_judge.py·sa_s3.py 것을 그대로 불러 쓴다(여기서 바꾸지 않는다). s3/out 에는 쓰지 않는다.
사용: python run.py [--iters 2000] [--no-state] [--quick] [--out 폴더]
       --quick = 시험용(가짜 50번, 갈래마다 (가) 앞 6개만), --out = 결과를 다른 폴더에(시험용, 저장소 파일을 건드리지 않음)
"""
import argparse
import glob
import json
import math
import os
import re
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
SA = os.path.dirname(HERE)
sys.path.insert(0, SA)
import sa_common as C  # noqa: E402
import sa_judge as J  # noqa: E402
import sa_s3 as S3  # noqa: E402

LAB = os.path.join(C.DERIV, 'lab')
US_OUT = os.path.join(C.DERIV, 'us', 'out')
BR = {'A': 'out', 'B': 'out_b', 'C': 'out_c', 'D': 'out_d'}
BR_STATE = {'A': 'state', 'B': 'state_b', 'C': 'state_c', 'D': 'state_d'}
BR_NAME = {'A': '갈래 A', 'B': '갈래 B', 'C': '갈래 C(미국·한국 연동)', 'D': '갈래 D(하락 전담)'}
NEED = ['id', 'family', 'desc', 'direction', 'all_n', 'all_hit', 'all_lb', 'dev_n', 'dev_hit', 'p2_n', 'p2_hit', '버팀']
TOP = 100
P1_END = pd.Timestamp('2023-12-31')
Y16 = pd.Timestamp('2016-01-01')
P_RAW = 0.01                                   # 거름 ④: 보정 전 p < 1%
WF_DIR = {'A': 1, 'B': 1, 'C': 1, 'D': -1}     # (나) 갈래의 주 방향
SHAPES = [('goal', 0.85), ('watch', 0.80)]
NMINS = ['n35', 'nT1']
COUNTS = [1, 5, 20]
HOWS = ['any', 'cons']
PROCS = [(sh, nm, cn, how) for sh, _ in SHAPES for nm in NMINS for cn in COUNTS for how in HOWS if not (cn == 1 and how == 'cons')]   # 20
M_WF = 4 * len(PROCS)                          # 80 — 보정 뒤 p 에 곱하는 수(참고)
WATCH = [('① 분기물 콜벽(절차)', 't1', 'WF_watch_top1_any_up'), ('① 분기물 콜벽(고정 규칙)', 't1', 'R_Q_b15_any_up1_none_any_d1_f1_h5_up'),
         ('② 오를 확률 모형', 't3', 'P_h5_allev_gb_q90'), ('③ 바닥 전 상태+변동성 꺾임', 't4', 't2_V_S10_T8_h5')]
SH_KO = {'goal': '통과 꼴(85%)', 'watch': '관찰 꼴(80%)'}
NM_KO = {'n35': '35건 고정', 'nT1': 'T1 과 같은 줄인 건수'}
HOW_KO = {'any': '하나라도 켜진 날', 'cons': '20% 이상 함께 켜진 날'}
# deriv/us/us_study.py 의 PCT·ABS 정의를 그대로 옮김(갈래 C 신호일을 다시 만들 때만 씀)
PCT = [('상위10%', lambda q: q >= 0.90), ('상위20%', lambda q: q >= 0.80), ('하위20%', lambda q: q <= 0.20), ('하위10%', lambda q: q <= 0.10)]
ABS = [('es_r1', '≤-1.5%', lambda v: v <= -1.5), ('es_r1', '≤-1%', lambda v: v <= -1.0), ('es_r1', '≥+1%', lambda v: v >= 1.0), ('es_r1', '≥+1.5%', lambda v: v >= 1.5),
       ('nq_r1', '≤-2%', lambda v: v <= -2.0), ('nq_r1', '≥+2%', lambda v: v >= 2.0), ('sox_r1', '≤-3%', lambda v: v <= -3.0), ('sox_r1', '≤-2%', lambda v: v <= -2.0),
       ('sox_r1', '≥+2%', lambda v: v >= 2.0), ('sox_r1', '≥+3%', lambda v: v >= 3.0), ('vix_ts', '>1(역전)', lambda v: v > 1.0), ('vix_ts', '<0.85', lambda v: v < 0.85),
       ('vix', '≥30', lambda v: v >= 30), ('vix', '≤13', lambda v: v <= 13), ('vix_c1', '≥+15%', lambda v: v >= 15), ('ewy_gap', '≤-1.5%p', lambda v: v <= -1.5), ('ewy_gap', '≥+1.5%p', lambda v: v >= 1.5)]

_p, _pp, _sum, _cut, table = S3._p, S3._pp, S3._sum, S3._cut, S3.table


def _js(o):
    if hasattr(o, 'item'): return o.item()
    if isinstance(o, pd.Timestamp): return str(o.date())
    return str(o)


def _norm(tr):
    """거래표를 [signal, exit] 날짜 두 칸으로(빈 날짜는 뺌)."""
    if tr is None or not len(tr): return pd.DataFrame({'signal': pd.to_datetime([]), 'exit': pd.to_datetime([])})
    t = pd.DataFrame({'signal': pd.to_datetime(tr['signal']).values.astype('datetime64[ns]'), 'exit': pd.to_datetime(tr['exit']).values.astype('datetime64[ns]')})
    return t.dropna().sort_values('signal').reset_index(drop=True)


def _exit_after():
    """연구소 lab_common.exit_after(읽기만). 못 불러오면 같은 두 줄을 그대로 쓴다."""
    try:
        if LAB not in sys.path: sys.path.insert(0, LAB)
        import lab_common as L
        return L.exit_after, 'lab_common'
    except Exception as e:                                           # noqa: BLE001
        def f(td, s, h):
            i = td.searchsorted(s, side='right') + h - 1
            return td[i] if i < len(td) else pd.NaT
        return f, f'같은 계산을 직접({type(e).__name__})'


# ------------------------------------------------------------------ 1. 순위
def rank_pool(g):
    """갈래 g 의 상위 100개. 반환 (표, 정보)."""
    L = []; skipped = []; rounds = []
    for f in sorted(glob.glob(os.path.join(LAB, BR[g], 'round_*', 'leaderboard.csv'))):
        r = int(re.search(r'round_(\d+)', f).group(1)); rounds.append(r)
        try:
            x = pd.read_csv(f)
        except Exception:                                            # noqa: BLE001
            skipped.append(r); continue
        if not set(NEED) <= set(x.columns): skipped.append(r); continue
        x = x[NEED].copy(); x['round'] = r; x['lb_pos'] = np.arange(len(x)); L.append(x)
    info = {'rounds': len(rounds), 'skipped': len(skipped), 'rows': 0, 'uniq': 0}
    cols = NEED + ['round', 'lb_pos', 'P', 'W', 'rank', 'grade']
    if not L: return pd.DataFrame(columns=cols), info
    A = pd.concat(L, ignore_index=True); info['rows'] = len(A)
    A = A.dropna(subset=['id', 'desc'])
    A = A.sort_values(['round', 'lb_pos'], kind='stable').drop_duplicates('desc', keep='last')
    for k in ('direction', 'all_n', 'all_hit', 'all_lb', 'dev_n', 'dev_hit', 'p2_n', 'p2_hit'): A[k] = pd.to_numeric(A[k], errors='coerce')
    A = A.dropna(subset=['direction']); A['direction'] = A['direction'].astype(int)
    if g == 'D': A = A[A['direction'] == -1]
    info['uniq'] = len(A)
    b = A['버팀'].map(lambda v: str(v).strip().lower() == 'true')
    ge = lambda k, v: A[k].fillna(-1) >= v
    A['P'] = ge('all_n', 35) & ge('all_hit', 0.85) & ge('dev_n', 12) & ge('dev_hit', 0.80) & ge('p2_n', 12) & ge('p2_hit', 0.80) & b
    A['W'] = ge('all_n', 35) & ge('all_hit', 0.80) & ge('dev_n', 12) & ge('dev_hit', 0.75) & ge('p2_n', 12) & ge('p2_hit', 0.75) & b
    A['_lb'] = A['all_lb'].fillna(-1.0)
    A = A.sort_values(['P', 'W', '_lb', 'round', 'id'], ascending=[False, False, False, False, True], kind='stable').head(TOP).reset_index(drop=True)
    A['rank'] = np.arange(1, len(A) + 1); A['grade'] = np.where(A['P'], '통과', np.where(A['W'], '관찰', '–'))
    return A.drop(columns=['_lb']), info


# ------------------------------------------------------------------ 2. 거래일
def lab_lists(c):
    """연구소 판정과 같은 거래표: (앞 구간용, 뒤 구간용, 전체 = 앞(청산 ≤ 2023) + 뒤(신호 ≥ 2024), trades_dev 가 있었나)."""
    t = _norm(c['trades']); has = isinstance(c.get('trades_dev'), pd.DataFrame)
    td_ = _norm(c['trades_dev']) if has else t
    both = pd.concat([td_[td_['exit'] <= P1_END], t[t['signal'] >= C.SPLIT]], ignore_index=True)
    return td_, t, both, has


def lab_check(D, row, c):
    """그 거래일을 연구소 방식(코스피200 선물, 독립 거래)으로 다시 재서 순위표 숫자와 견준다."""
    d = int(row['direction']); td_, t, both, has = lab_lists(c)
    a = C.score(td_, d, D.F, C.START, P1_END); b = C.score(t, d, D.F, C.SPLIT, C.END); al = C.score(both, d, D.F)
    same = lambda s, n, h: bool(pd.notna(n) and s['n'] == int(n) and (s['n'] == 0 or (pd.notna(h) and abs((s['hit'] or 0) - float(h)) < 1e-6)))
    return {'dev_ok': same(a, row['dev_n'], row['dev_hit']), 'p2_ok': same(b, row['p2_n'], row['p2_hit']), 'all_ok': same(al, row['all_n'], row['all_hit']),
            'dev_n': a['n'], 'dev_hit': a['hit'], 'has_tdev': has, 'x1': (both if has else t)}


def recon_c(row, F, Q, td, exit_after):
    """갈래 C: id 에서 조건·보유일·방향을 읽어 신호일을 다시 만든다. 반환 (거래표 또는 None, 까닭)."""
    m = re.match(r'A11_(.+)_h(\d+)_([UD])$', str(row['id']))
    if not m: return None, 'id 꼴이 A11_…_hN_U/D 가 아님'
    cid, h, ud = m.group(1), int(m.group(2)), m.group(3)
    if (1 if ud == 'U' else -1) != int(row['direction']): return None, 'id 의 방향과 순위표 방향이 다름'
    mask = None
    if cid == 'pcr_hi_es_dn':
        if 'pcr_eq' in Q and 'es_r5' in Q: mask = (Q['pcr_eq'] >= 0.9) & (Q['es_r5'] <= 0.2)
    else:
        for nm, fn in PCT:
            f = cid[:-len(nm) - 1]
            if cid.endswith('_' + nm) and f in F.columns and f in Q.columns: mask = fn(Q[f]) & F[f].notna()
        for f, nm, fn in ABS:
            if cid == f'{f}_abs{nm}' and f in F.columns: mask = fn(F[f]) & F[f].notna()
    if mask is None: return None, '조건 정의를 찾지 못함(PCT·ABS·pcr_hi_es_dn 밖)'
    sig = td[np.asarray(mask.reindex(td).fillna(False).values, dtype=bool)]
    if len(sig) < 12: return None, '신호 12건 미만'
    tr = pd.DataFrame({'signal': sig, 'exit': [exit_after(td, s, h) for s in sig]}).dropna()
    return tr, ''


def load_lab(g, ids, log):
    """연구소 거래일 기록 {id: {회차: [후보, …]}}. 못 읽는 파일이 있으면 멈춘다 — 읽기 실패를 '확인 불가(기록 없음)'로 세면 안 된다.
    환경 변수 X1_LAB_CACHE 가 있으면 extract.py 가 연구소와 같은 환경(판다스 최신판)에서 옮겨 둔 JSON 을 읽는다(고정판 판다스로는 연구소 pkl 이 안 읽힘)."""
    idx = {}; cache = os.environ.get('X1_LAB_CACHE', '').strip()
    files = sorted(glob.glob(os.path.join(LAB, BR[g], 'round_*', '*', 'candidates.pkl')))
    if cache:
        p = os.path.join(cache, f'lab_trades_{g}.json')
        if not os.path.exists(p): raise RuntimeError(f'갈래 {g}: 옮겨 둔 거래일 파일이 없음({p}) — extract.py 를 먼저 돌려야 함')
        Z = json.load(open(p, encoding='utf-8'))
        if int(Z.get('files', -1)) != len(files): raise RuntimeError(f"갈래 {g}: 옮겨 둔 기록의 파일 수({Z.get('files')})가 저장소의 candidates.pkl 수({len(files)})와 다름")
        for c in Z['cands']:
            if c['id'] not in ids: continue
            cc = {'id': c['id'], 'desc': c.get('desc'), 'direction': c.get('direction'), 'trades': pd.DataFrame(c['trades'], columns=['signal', 'exit'])}
            if c.get('trades_dev') is not None: cc['trades_dev'] = pd.DataFrame(c['trades_dev'], columns=['signal', 'exit'])
            idx.setdefault(c['id'], {}).setdefault(int(c['round']), []).append(cc)
        if files: log.append(f"{g}: 연구소 거래일 파일 {len(files)}개는 연구소와 같은 환경(판다스 {Z.get('pandas')})에서 날짜 글자로 옮긴 뒤 읽음(extract.py) — 판정은 파이프라인과 같은 고정판 환경")
        return idx
    for p in files:
        r = int(re.search(r'round_(\d+)', p).group(1))
        try:
            cs = pd.read_pickle(p)
        except Exception as e:                                       # noqa: BLE001
            raise RuntimeError(f'갈래 {g}: {os.path.relpath(p, LAB)} 를 못 읽음({type(e).__name__}) — 판다스 판이 연구소와 다르면 extract.py 로 옮긴 뒤 X1_LAB_CACHE 를 줄 것') from e
        for c in cs:
            if isinstance(c, dict) and c.get('id') in ids and isinstance(c.get('trades'), pd.DataFrame):
                idx.setdefault(c['id'], {}).setdefault(r, []).append(c)
        del cs
    return idx


def attach_trades(D, g, pool, log):
    """pool 에 거래일 출처 칸을 붙이고 {순위: 거래표} 를 돌려준다."""
    TR = {}; src = []; note = []; chk = {k: [] for k in ('lab_dev_ok', 'lab_p2_ok', 'lab_all_ok', 'has_tdev')}
    ids = set(pool['id']); idx = load_lab(g, ids, log)
    FQ = None
    if g == 'C':
        try:
            F = pd.read_csv(os.path.join(US_OUT, 'features_kr.csv.gz'), index_col=0, parse_dates=True); Q = pd.read_csv(os.path.join(US_OUT, 'features_pct.csv.gz'), index_col=0, parse_dates=True)
            F = F[F.index <= C.END]; Q = Q[Q.index <= C.END].reindex(F.index); ea, how = _exit_after(); FQ = (F, Q, F.index, ea)
            log.append(f'C: 미국 지표 파일 {F.index[0].date()}~{F.index[-1].date()} {F.shape[1]}개, 청산일 계산 = {how}')
        except Exception as e:                                       # noqa: BLE001
            log.append(f'C: 미국 지표 파일을 못 읽음({type(e).__name__}) — 다시 만들 수 없음')
    for _, row in pool.iterrows():
        m = idx.get(row['id'], {}); s = '확인 불가(거래일 기록 없음)'; nt = ''; ck = None; c = None
        if int(row['round']) in m:
            L = m[int(row['round'])]; c = next((x for x in L if x.get('desc') == row['desc']), L[0]); ck = lab_check(D, row, c); s = '그 회차 기록'
        else:
            rs = sorted((r for r in m if any(x.get('desc') == row['desc'] for x in m[r])), key=lambda r: (abs(r - int(row['round'])), -r))
            if rs:
                c = next(x for x in m[rs[0]] if x.get('desc') == row['desc']); ck = lab_check(D, row, c)
                if ck['dev_ok']: s = '다른 회차 기록(앞 구간 숫자 일치)'; nt = f'{rs[0]}회차 기록'
                else: nt = f"{rs[0]}회차에 같은 id·설명이 있으나 앞 구간 숫자가 다름(기록 {ck['dev_n']}건, 순위표 {row['dev_n']:.0f}건) — 쓰지 않음"; c = None; ck = None
            elif g == 'C' and FQ is not None:
                tr, why = recon_c(row, *FQ)
                if tr is None: nt = why
                else:
                    c = {'trades': tr}; ck = lab_check(D, row, c)
                    if ck['dev_ok']: s = '다시 만듦(미국 지표, 앞 구간 숫자 일치)'
                    else: nt = f"다시 만든 신호의 앞 구간 숫자가 순위표와 다름({ck['dev_n']}건 대 {row['dev_n']:.0f}건) — 쓰지 않음"; c = None; ck = None
            elif m: nt = '같은 id 는 다른 회차에 있으나 설명이 다름 — 쓰지 않음'
        if c is not None and ck is not None:
            x = ck['x1']; x = x[(x['signal'] >= C.START) & (x['exit'] <= C.END)].reset_index(drop=True)
            if len(x): TR[int(row['rank'])] = x
            else: s = '확인 불가(거래일 기록 없음)'; nt = '기록은 있으나 2010~끝 날짜 사이 거래가 없음'; ck = None
        src.append(s); note.append(nt)
        for k in chk: chk[k].append(None if ck is None else bool(ck[k.replace('lab_', '')] if k != 'has_tdev' else ck['has_tdev']))
    pool = pool.copy(); pool['src'] = src; pool['src_note'] = note
    for k in chk: pool[k] = chk[k]
    pool['n_signals'] = [len(TR[r]) if r in TR else 0 for r in pool['rank']]
    return pool, TR


# ------------------------------------------------------------------ 3. 판정·반증(기존 함수 그대로)
def falsify_one(D, B, key, d, raw, row, iters, grade):
    """sa_s3.falsify 를 그대로 부른다(결과는 돌려주기만 — s3/out 에 쓰지 않음)."""
    tr = S3.enrich(raw, d, D.K)
    c = {'key': key, 'grade': grade, 'row': row, 'd': d, 'h': int(row.get('hold') or 1), 'hold_fixed': False, 'has_hit': False, 'has_ret': False, 'tr': tr, 'by': None}
    c['t0'] = C.score(tr, d, D.K)['t']
    if not len(c['t0']): return [], {'tests': {}, 'n_hold': 0, 'verdict': '판정 불가', 'p_raw': None, 'rescored': False}
    return S3.falsify(D, B, c, iters)


def four(r1, r, fz):
    """네 거름. r1 = ①을 재는 판정 줄, r = ②④를 재는 판정 줄, fz = ③ 반증 결과."""
    f1 = bool(r1.get('c31')); f2 = bool(r.get('c33')); f3 = bool(fz.get('n_hold') == 8 and fz.get('verdict') != '판정 불가')
    f4 = bool(r.get('fake_p') is not None and r['fake_p'] < P_RAW)
    return f1, f2, f3, f4


def held16(D, t):
    m = S3.held_mask(D, t[t['signal'] >= Y16]) if len(t) else np.zeros(D.n, dtype=bool)
    return m


def watch_refs(D, log):
    out = []
    for name, tk, cid in WATCH:
        try:
            cs, _ = C.load_result(tk); c = next(x for x in cs if x['id'] == cid); d = int(c['direction'])
            out.append({'name': name, 'key': f'{tk}:{cid}', 'd': d, 'held': held16(D, C.score(c['trades'], d, D.K)['t'])})
        except Exception as e:                                       # noqa: BLE001
            log.append(f'관찰 목록 {tk}:{cid} 의 거래일을 못 읽음({type(e).__name__}) — 견줌에서 뺌')
    return out


def overlap_watch(D, refs, d, t0):
    """후보(독립 거래 t0)와 관찰 목록 대상들의 2016~ 보유 기간 겹침. 반환 (줄들, 한 줄 요약)."""
    h = held16(D, t0); na = int(h.sum()); rows = []; best = None
    for r in refs:
        nb = int(r['held'].sum()); both = int((h & r['held']).sum()); oa = both / na if na else 0.0; ob = both / nb if nb else 0.0
        if r['d'] != d: lab = '방향이 달라 견줄 수 없음'
        elif min(oa, ob) >= 0.8: lab = '사실상 같은 신호'
        elif max(oa, ob) >= 0.8: lab = '한쪽이 다른 쪽에 포함'
        elif max(oa, ob) >= 0.5: lab = '많이 겹침'
        else: lab = '다른 신호'
        rows.append({'관찰목록': r['name'], '관찰_key': r['key'], '겹침_후보기준': round(oa, 3), '겹침_관찰기준': round(ob, 3), '말': lab})
        if r['d'] == d and (best is None or max(oa, ob) > best[0]): best = (max(oa, ob), r['name'], oa, ob, lab)
    if not refs: return rows, '견줄 관찰 목록 자료 없음'
    if best is None: return rows, '방향이 달라 견줄 수 없음(관찰 목록은 모두 오름)'
    return rows, f"{best[4]} — 가장 많이 겹치는 것 {best[1]}(후보 기준 {100 * best[2]:.0f}%·관찰 기준 {100 * best[3]:.0f}%)"


def root_tag(cid, desc):
    s = f'{cid} {desc}'
    return '분기물 콜벽 뿌리' if ('_Q_' in s or 'Q 벽' in s or '분기물' in s) else ''


def hv(x, n):
    """표본 10개 미만이면 적중을 적지 않는다."""
    return None if (x is None or (n or 0) < S3.MIN_PCT) else round(float(x), 4)


# ------------------------------------------------------------------ 4. (가) 고정 규칙 판
def run_fixed(D, B, g, pool, TR, refs, iters, m_fixed, limit=None):
    rows = []; frows = []; orows = []; done = 0
    for _, pr in pool.iterrows():
        rk = int(pr['rank'])
        if rk not in TR: continue
        if limit is not None and done >= limit: break
        done += 1
        d = int(pr['direction']); tr = TR[rk]; key = f'x1:{g}{rk:03d}'
        c = {'id': pr['id'], 'track': 'x1', 'kind': 'fixed', 'family': pr['family'], 'desc': pr['desc'], 'direction': d, 'hold': None, 'trades': tr}
        rf = J.judge_one(D, c, m_fixed, iters)
        t0 = C.score(tr, d, D.K)['t']; t16 = t0[t0['signal'] >= Y16][['signal', 'exit']].reset_index(drop=True) if len(t0) else _norm(None)
        r16 = J.judge_one(D, dict(c, kind='wf', trades=t16), m_fixed, iters)
        R, fz = falsify_one(D, B, key, d, tr, rf, iters, 3)
        R16, fz16 = falsify_one(D, B, key + ':2016~', d, t16, r16, iters, 2)
        f1, f2, f3, f4 = four(r16, rf, fz); _, g2, g3, g4 = four(r16, r16, fz16)
        ov, ovs = overlap_watch(D, refs, d, t0)
        for o in ov: orows.append({'후보': key, '종류': '(가) 고정 규칙', '갈래': g, '순위': rk, **o})
        for x in R: x['구간'] = '전체(주 판정)'
        for x in R16: x['구간'] = '2016~(참고)'
        frows += R + R16
        rows.append({'key': key, '갈래': g, '순위': rk, '연구소등급': pr['grade'], 'id': pr['id'], '설명': pr['desc'], '가족': pr['family'], '방향': d, '회차': int(pr['round']),
                     '거래일출처': pr['src'], '연구소_전체n': pr['all_n'], '연구소_전체적중': pr['all_hit'], '연구소_윌슨하한': pr['all_lb'], '신호수': int(len(tr)), '보유일_가운뎃값': rf['hold'],
                     '독립거래': rf['all_n'], '적중': hv(rf['all_hit'], rf['all_n']), '아무날': hv(rf['base'], rf['all_n']), '차이': hv(rf['edge'], rf['all_n']), '수익합계': round(rf['all_sum'], 5),
                     '앞n': rf['p1_n'], '앞적중': hv(rf['p1_hit'], rf['p1_n']), '뒤n': rf['p2_n'], '뒤적중': hv(rf['p2_hit'], rf['p2_n']),
                     '코스피_통과숫자': bool(rf['goal_pass']), '코스피_관찰숫자': bool(rf['watch_pass']),
                     'n16': r16['all_n'], '적중16': hv(r16['all_hit'], r16['all_n']), '아무날16': hv(r16['base'], r16['all_n']), '차이16': hv(r16['edge'], r16['all_n']), '수익합계16': round(r16['all_sum'], 5),
                     '거름1': f1, '거름2': f2, '거름2_큰변동해_판정불가': bool(rf.get('c33_big') is None), '거름3': f3, '반증버틴수': fz['n_hold'], '반증종합': fz['verdict'],
                     '거름4': f4, '가짜p': rf['fake_p'], '가짜p_보정뒤': rf['fake_p_adj'], '가짜_곱한수': int(m_fixed), '넷다': bool(f1 and f2 and f3 and f4), '통과한_거름수': int(f1) + int(f2) + int(f3) + int(f4),
                     'y26_n': rf['y26_n'], 'y26_hit': hv(rf['y26_hit'], rf['y26_n']), 'ex26_hit': hv(rf['ex26_hit'], rf['ex26_n']), 'ex26_base': hv(rf['ex26_base'], rf['ex26_n']),
                     'big_n': rf['big_n'], 'big_hit': hv(rf['big_hit'], rf['big_n']), 'big_base': hv(rf['big_base'], rf['big_n']),
                     '참고16_거름2': g2, '참고16_거름3': g3, '참고16_반증버틴수': fz16['n_hold'], '참고16_거름4': g4, '참고16_가짜p': r16['fake_p'], '참고16_넷다': bool(f1 and g2 and g3 and g4),
                     '뿌리표시': root_tag(pr['id'], pr['desc']), '관찰목록과': ovs, 'by_year': json.dumps(rf['by_year'], ensure_ascii=False)})
    return rows, frows, orows


# ------------------------------------------------------------------ 5. (나) 해마다 고르는 절차
def proc_id(g, p): return f'WF_{g}_{p[0]}_{p[1]}_top{p[2]}_{p[3]}'


def proc_desc(g, p, d):
    nm = '35건' if p[1] == 'n35' else '줄인 건수(2016년 12 … 2026년 33건)'
    return (f"{BR_NAME[g]} 상위 100개 묶음에서 해마다 그 전 자료로 {nm}·적중 {85 if p[0] == 'goal' else 80}% 이상인 규칙을 골라 윌슨 하한 상위 {p[2]}개 사용 · "
            f"{HOW_KO[p[3]]} 매수(청산은 그 규칙대로) → {'오름' if d > 0 else '내림'}")


def run_wf(D, B, g, pool, TR, refs, iters):
    d = WF_DIR[g]; rules = [int(r) for r, dd in zip(pool['rank'], pool['direction']) if int(r) in TR and int(dd) == d]
    S = {}
    for rk in rules:
        t = C.score(TR[rk], d, D.K)['t']
        raw = TR[rk].drop_duplicates('signal').sort_values('signal').reset_index(drop=True)
        raw = raw[D.td.get_indexer(pd.DatetimeIndex(raw['exit'])) >= 0].reset_index(drop=True)
        S[rk] = {'ex': pd.DatetimeIndex(t['exit']) if len(t) else pd.DatetimeIndex([]), 'ok': (t['ok'].values.astype(int) if len(t) else np.zeros(0, dtype=int)), 'raw': raw, 'yr': pd.DatetimeIndex(raw['signal']).year.values}
    parts = {p: [] for p in PROCS}; picks = []
    for Y, _end in C.wf_splits():
        y0 = pd.Timestamp(f'{Y}-01-01'); stats = []
        for rk in rules:
            m = np.asarray(S[rk]['ex'] < y0); n = int(m.sum()); k = int(S[rk]['ok'][m].sum())
            if n: stats.append((rk, n, k, k / n, C.wilson(k, n)[0]))
        for nm in NMINS:
            nmin = 35 if nm == 'n35' else max(12, int(round(35 * (Y - 2010) / 17)))
            for sh, thr in SHAPES:
                sel = sorted([s for s in stats if s[1] >= nmin and s[3] >= thr - 1e-9], key=lambda s: (-s[4], -s[1], s[0]))
                picks.append({'갈래': g, '해': Y, '꼴': sh, '최소건수': nm, 'n_min': nmin, '묶음_규칙수': len(rules), '건수_채운_규칙수': sum(s[1] >= nmin for s in stats), '고른_규칙수': len(sel),
                              '상위20_순위': ' '.join(str(s[0]) for s in sel[:20]), '1위_순위': (sel[0][0] if sel else None), '1위_n': (sel[0][1] if sel else None), '1위_맞음': (sel[0][2] if sel else None)})
                for cn in COUNTS:
                    U = sel[:cn]
                    if not U: continue
                    fr = []
                    for o, s in enumerate(U):
                        x = S[s[0]]['raw'][S[s[0]]['yr'] == Y]
                        if len(x): fr.append(x.assign(order=o))
                    if not fr: continue
                    al = pd.concat(fr, ignore_index=True)
                    parts[(sh, nm, cn, 'any')].append(al.sort_values(['signal', 'order'], kind='stable').drop_duplicates('signal', keep='first')[['signal', 'exit']])
                    if cn != 1 and len(U) >= 2:
                        need = max(2, math.ceil(0.2 * len(U))); al['ep'] = D.td.get_indexer(pd.DatetimeIndex(al['exit']))
                        gb = al.groupby('signal')['ep'].agg(['size', 'median']); gb = gb[gb['size'] >= need]
                        if len(gb):
                            ep = np.floor(gb['median'].values + 0.5).astype(int)
                            parts[(sh, nm, cn, 'cons')].append(pd.DataFrame({'signal': gb.index.values, 'exit': D.td[ep].values}))
    rows = []; frows = []; orows = []
    top1 = {}
    for x in picks:
        if x['1위_순위'] is not None: top1.setdefault((x['꼴'], x['최소건수']), []).append(int(x['1위_순위']))
    for p in PROCS:
        tr = _norm(pd.concat(parts[p], ignore_index=True)) if parts[p] else _norm(None)
        pid = proc_id(g, p); key = f'x1:{pid}'
        c = {'id': pid, 'track': 'x1', 'kind': 'wf', 'family': f'해마다 고름({g})', 'desc': proc_desc(g, p, d), 'direction': d, 'hold': None, 'trades': tr}
        r = J.judge_one(D, c, M_WF, iters)
        R, fz = falsify_one(D, B, key, d, tr, r, iters, 2)
        for x in R: x['구간'] = '2016~(절차)'
        frows += R
        f1, f2, f3, f4 = four(r, r, fz)
        t0 = C.score(tr, d, D.K)['t']; ov, ovs = overlap_watch(D, refs, d, t0)
        for o in ov: orows.append({'후보': key, '종류': '(나) 절차', '갈래': g, '순위': None, **o})
        tl = top1.get((p[0], p[1]), []); mode = (max(set(tl), key=lambda v: (tl.count(v), -v)) if tl else None)
        rows.append({'key': key, '갈래': g, 'id': pid, '설명': c['desc'], '꼴': p[0], '최소건수': p[1], '쓰는수': p[2], '만드는법': p[3], '방향': d, '묶음_규칙수': len(rules), '신호수': int(len(tr)),
                     '거래있는_해수': int(len(r['by_year'])), '보유일_가운뎃값': r['hold'],
                     '독립거래': r['all_n'], '적중': hv(r['all_hit'], r['all_n']), '아무날': hv(r['base'], r['all_n']), '차이': hv(r['edge'], r['all_n']), '수익합계': round(r['all_sum'], 5),
                     '앞n_2016_2023': r['p1_n'], '앞적중': hv(r['p1_hit'], r['p1_n']), '뒤n_2024_': r['p2_n'], '뒤적중': hv(r['p2_hit'], r['p2_n']),
                     '통과숫자_35건_85': bool(r['goal_pass']), '관찰숫자_35건_80': bool(r['watch_pass']),
                     '거름1': f1, '거름2': f2, '거름2_큰변동해_판정불가': bool(r.get('c33_big') is None), '거름3': f3, '반증버틴수': fz['n_hold'], '반증종합': fz['verdict'],
                     '거름4': f4, '가짜p': r['fake_p'], '가짜p_보정뒤': r['fake_p_adj'], '가짜_곱한수': M_WF, '넷다': bool(f1 and f2 and f3 and f4), '통과한_거름수': int(f1) + int(f2) + int(f3) + int(f4),
                     'y26_n': r['y26_n'], 'y26_hit': hv(r['y26_hit'], r['y26_n']), 'ex26_hit': hv(r['ex26_hit'], r['ex26_n']), 'ex26_base': hv(r['ex26_base'], r['ex26_n']),
                     'big_n': r['big_n'], 'big_hit': hv(r['big_hit'], r['big_n']), 'big_base': hv(r['big_base'], r['big_n']),
                     '1위로_가장_자주_뽑힌_순위': mode, '1위로_뽑힌_해수': (tl.count(mode) if tl else 0), '관찰목록과': ovs, 'by_year': json.dumps(r['by_year'], ensure_ascii=False)})
    return rows, frows, orows, picks


def best_proc(rows):
    a = [r for r in rows if r['독립거래'] >= J.C31['n'] and r['차이'] is not None] or [r for r in rows if r['독립거래'] >= S3.MIN_PCT and r['차이'] is not None]
    return max(a, key=lambda r: (r['차이'], r['독립거래'])) if a else None


# ------------------------------------------------------------------ 6. 보고서
def yn(b): return '예' if b else '아니오'


def fmt_p(x): return '–' if x is None or (isinstance(x, float) and not np.isfinite(x)) else f'{x:.4f}'


def report(now, iters, quick, pools, infos, fx, wf, picks, lab_tr, log, n_tested, ledger_total):
    G = 'ABCD'; M = []
    F = {g: [r for r in fx if r['갈래'] == g] for g in G}; W = {g: [r for r in wf if r['갈래'] == g] for g in G}
    cnt = lambda rows, k: sum(bool(r[k]) for r in rows)
    tot_pool = sum(len(pools[g]) for g in G); tot_has = sum(len(F[g]) for g in G); tot_all = cnt(fx, '넷다')
    unk = {g: int((pools[g]['src'].str.startswith('확인 불가')).sum()) if len(pools[g]) else 0 for g in G}
    has = {g: len(pools[g]) - unk[g] for g in G}
    unk_g = lambda g, s: int((pools[g]['src'].str.startswith('확인 불가') & (pools[g]['grade'] == s)).sum()) if len(pools[g]) else 0
    src_n = lambda g, s: int(pools[g]['src'].str.startswith(s).sum()) if len(pools[g]) else 0
    passers = sorted([r for r in fx if r['넷다']], key=lambda r: (r['갈래'], r['순위']))
    wf_pass = [r for r in wf if r['넷다']]; best = {g: best_proc(W[g]) for g in G}
    M += [f'# Signal A X1 — 연구소 갈래 A·B·C·D 상위 100위 거름 시험 ({now}, 자료 끝 {C.END.date()})', '',
          '> 사용자 지시 "전에 조사한 a b c d 의 각각 상위 100위 전부 거름 테스트". 숫자·표·아래 문장은 GitHub 가 x1/run.py 로 계산해 자동으로 쓴 것입니다(미리 정한 목록: x1/SPEC.md).',
          '> 매매 기준: 코스피 지수, 신호 다음 날 시가 매수 → 그 후보의 청산일 종가 매도, 독립 거래, 수익 합계는 단순 합. 표본 10개 미만은 %로 적지 않습니다.', '']
    if quick: M += ['**(시험용 실행 — 가짜 횟수와 대상 수를 줄였습니다. 이 숫자는 쓰지 마세요.)**', '']
    # ---- 결론
    M += ['## 1. 결론', '']
    M.append(f"1. 연구소 네 갈래의 상위 후보는 모두 **{tot_pool}개**(A {len(pools['A'])}·B {len(pools['B'])}·C {len(pools['C'])}·D {len(pools['D'])})입니다. "
             f"이 가운데 거래일 기록을 구한 **{sum(has.values())}개**를 네 거름에 넣었고, 나머지 **{sum(unk.values())}개는 확인 불가(거래일 기록 없음)** 입니다"
             f"(확인 불가 가운데 연구소 통과 등급 {sum(unk_g(g, '통과') for g in G)}개·관찰 등급 {sum(unk_g(g, '관찰') for g in G)}개).")
    if tot_all:
        M.append(f"2. **네 거름을 모두 넘은 후보는 {tot_all}개**입니다(" + '·'.join(f"{g} {cnt(F[g], '넷다')}" for g in G) + '). 아래 3절 표에 있습니다. '
                 '다만 이 후보들은 전체 기간 결과를 보고 고른 규칙이라, 거름 ①의 숫자는 Signal A 의 \'다음 해 성적\'과 같은 뜻이 아닙니다.')
    else:
        M.append('2. **네 거름을 모두 넘은 후보는 없습니다(0개).** 거름별 통과 수는 2절 표에 있습니다.')
    M.append('3. 거름별로 보면: ' + ' / '.join(f"{g}: ① {cnt(F[g], '거름1')} · ② {cnt(F[g], '거름2')} · ③ {cnt(F[g], '거름3')} · ④ {cnt(F[g], '거름4')} (넣은 {len(F[g])}개 중)" for g in G) + '.')
    bl = []
    for g in G:
        b = best[g]
        if b is None: bl.append(f'{g}: 거래가 10건 이상인 절차 없음')
        else: bl.append(f"{g}: {b['독립거래']}거래 {_p(b['적중'], b['독립거래'])}(아무 날 {_p(b['아무날'], b['독립거래'])}, 차이 {_pp(b['차이'], b['독립거래'])}) — 네 거름 {'모두 통과' if b['넷다'] else str(b['통과한_거름수']) + '개 통과'}")
    M.append(f"4. '해마다 그 전 자료로 고르는 절차'(갈래마다 20개, 모두 {len(wf)}개) 가운데 네 거름을 모두 넘은 것은 **{len(wf_pass)}개**입니다. 갈래별로 가장 좋은 절차: " + ' / '.join(bl) + '. '
             '**상위 100개라는 묶음 자체가 전체 기간 결과로 뽑힌 것이라 이 숫자도 좋게 나오는 쪽으로 기웁니다.**')
    same = [r for r in passers if r['관찰목록과'].startswith(('사실상 같은', '한쪽이', '많이 겹침'))]
    if passers:
        M.append(f"5. Signal A 관찰 목록 3개와 견주면: 넷 다 통과한 {len(passers)}개 가운데 관찰 목록과 겹치는 것(많이 겹침 이상) {len(same)}개, "
                 f"'분기물 콜벽' 글자가 든 것 {sum(bool(r['뿌리표시']) for r in passers)}개입니다(5절).")
    else:
        M.append('5. Signal A 관찰 목록 3개와 견줄 \'넷 다 통과\' 후보가 없습니다. 갈래별 가장 좋은 절차와 관찰 목록의 겹침은 5절에 적었습니다.')
    M.append(f"6. 이번에 더한 시험 가짓수는 {n_tested:,}가지(고정 규칙 {tot_has} + 절차 {len(wf)})이고, Signal A 원장 누적은 {ledger_total:,}가지입니다. 최종 후보·관찰 목록(signals/final_v1.json)은 바꾸지 않았습니다.")
    M += ['', '## 2. 갈래별 숫자 — (가) 고정 규칙 판', '',
          '거름 ①(가)는 **결과를 보고 고른 규칙의 숫자**입니다(그 규칙의 2016~2026 거래가 같은 해 아무 날보다 10%p 이상 높고 독립 30건 이상). ②③④는 전체 기간(2010~) 거래로 쟀습니다.', '']
    M += table(list(G), [lambda g: BR_NAME[g], lambda g: len(pools[g]), lambda g: (has[g] if has[g] == len(F[g]) else f'{has[g]}(이번 시험용 실행은 {len(F[g])}개만 넣음)'), lambda g: unk[g], lambda g: cnt(F[g], '거름1'), lambda g: cnt(F[g], '거름2'),
                         lambda g: cnt(F[g], '거름3'), lambda g: cnt(F[g], '거름4'), lambda g: f"**{cnt(F[g], '넷다')}**", lambda g: cnt(F[g], '참고16_넷다')],
               ['갈래', '대상', '거래일 기록 있음', '확인 불가', '① 다음 해 꼴(결과를 보고 고른 규칙의 숫자)', '② 2026년·큰 변동 해', '③ 반증 8개 모두', '④ 가짜 p 1% 미만', '넷 다 통과', '참고: ②③④도 2016~만으로'])
    M += ['', '- 대상이 100개가 안 되는 갈래는 순위표에 오른 서로 다른 후보가 그만큼뿐입니다(갈래 D 는 내림 방향만).',
          f"- ②에서 큰 변동 해(2011·2020·2026) 독립 거래가 10건 미만이라 '판정 불가'(넘지 못한 것으로 침)인 후보: " + '·'.join(f"{g} {cnt(F[g], '거름2_큰변동해_판정불가')}" for g in G) + '개.',
          f"- ③을 '8개 모두' 대신 '종합 버팀(7개 이상)'으로 세면: " + '·'.join(f"{g} {sum(r['반증종합'] == '버팀' for r in F[g])}" for g in G) + '개.', '',
          '거래일을 어디서 구했나', '']
    M += table(list(G), [lambda g: BR_NAME[g], lambda g: f"{infos[g]['rounds']}개(건너뜀 {infos[g]['skipped']})", lambda g: infos[g]['uniq'], lambda g: len(pools[g]),
                         lambda g: f"{int(pools[g]['P'].sum()) if len(pools[g]) else 0} / {int((pools[g]['W'] & ~pools[g]['P']).sum()) if len(pools[g]) else 0}",
                         lambda g: src_n(g, '그 회차'), lambda g: src_n(g, '다른 회차'), lambda g: src_n(g, '다시 만듦'), lambda g: unk[g], lambda g: f"{unk_g(g, '통과')} / {unk_g(g, '관찰')}"],
               ['갈래', '순위표(열이 없어 건너뛴 옛 회차)', '서로 다른 후보', '대상(상위 100)', '연구소 통과 / 관찰(선물 기준)', '그 회차 기록', '다른 회차 기록(숫자 일치)', '다시 만듦(갈래 C)', '확인 불가',
                '확인 불가 중 연구소 통과 / 관찰'])
    M += ['', '- 확인 불가는 대부분 오래된 회차의 거래일 파일(candidates.pkl)이 저장소 크기 관리로 지워졌기 때문입니다. 추정으로 채우지 않았습니다.',
          '- 다른 회차 기록은 id 와 설명이 모두 같고, 그 거래일로 연구소 방식(선물, 앞 구간)으로 다시 잰 숫자가 순위표와 똑같을 때만 썼습니다.', '',
          '통과한 거름 수별 후보 수', '']
    M += table(list(G), [lambda g: BR_NAME[g]] + [(lambda g, k=k: sum(r['통과한_거름수'] == k for r in F[g])) for k in (4, 3, 2, 1, 0)], ['갈래', '4개', '3개', '2개', '1개', '0개'])
    M += ['', '연구소 등급(선물 기준)과 코스피 지수 기준 숫자', '']
    lab_g = lambda g, s: [r for r in F[g] if r['연구소등급'] == s]
    M += table(list(G), [lambda g: BR_NAME[g], lambda g: len(lab_g(g, '통과')), lambda g: cnt(lab_g(g, '통과'), '코스피_통과숫자'), lambda g: cnt(lab_g(g, '통과'), '코스피_관찰숫자'),
                         lambda g: len(lab_g(g, '관찰')), lambda g: cnt(lab_g(g, '관찰'), '코스피_통과숫자') + cnt(lab_g(g, '관찰'), '코스피_관찰숫자'),
                         lambda g: cnt(F[g], '코스피_통과숫자'), lambda g: cnt(F[g], '코스피_관찰숫자')],
               ['갈래', '연구소 통과(거름에 넣은 것)', '그중 코스피 지수로도 통과 숫자(35건·85%)', '그중 코스피 지수로는 관찰 숫자(80%)', '연구소 관찰(거름에 넣은 것)', '그중 코스피 지수로 통과·관찰 숫자',
                '넣은 것 전체 중 코스피 통과 숫자', '넣은 것 전체 중 코스피 관찰 숫자'])
    # ---- 넷 다 통과
    M += ['', '## 3. 네 거름을 모두 넘은 후보', '']
    cols = [lambda r: r['갈래'], lambda r: r['순위'], lambda r: r['연구소등급'], lambda r: _cut(r['설명'], 110), lambda r: '오름' if r['방향'] > 0 else '내림', lambda r: r['독립거래'],
            lambda r: _p(r['적중'], r['독립거래']), lambda r: _pp(r['차이'], r['독립거래']), lambda r: f"{r['n16']}건 {_p(r['적중16'], r['n16'])} / {_p(r['아무날16'], r['n16'])} / {_pp(r['차이16'], r['n16'])}",
            lambda r: fmt_p(r['가짜p']), lambda r: f"{r['y26_n']}건 {_p(r['y26_hit'], r['y26_n'])}", lambda r: f"{r['big_n']}건 {_p(r['big_hit'], r['big_n'])}", lambda r: f"{r['반증버틴수']}/8",
            lambda r: _sum(r['수익합계']), lambda r: r['거래일출처'][:8]]
    head = ['갈래', '순위', '연구소 등급(선물)', '조건 설명', '방향', '독립 거래(2010~)', '코스피 지수 적중(전체 기간 — 결과를 보고 고른 숫자)', '아무 날과 차이(전체 기간)',
            '2016~2026: 거래·적중 / 아무 날 / 차이(결과를 보고 고른 규칙의 숫자)', '가짜 p(보정 전)', '2026년', '큰 변동 해', '반증', '수익 합계', '거래일 출처']
    if passers:
        M += ['**이 표의 적중·차이는 모두 결과를 보고 고른 규칙의 숫자입니다. 해마다 그 전 자료로 고른 \'다음 해 성적\'이 아닙니다(그것은 4절).**', '']
        M += table(passers, cols, head)
        M += ['', '- 가짓수 보정 뒤 가짜 p 는 모두 1.0 에 가깝습니다(곱하는 수 = 연구소가 그 갈래에서 시험한 수: ' + '·'.join(f"{g} {lab_tr[g]:,}" for g in G) + '). 고정 규칙은 CRITERIA 3절 2번을 셈으로 넘을 수 없습니다(NOTES.md 2절).']
    else:
        M += ['**없습니다.** 네 거름을 모두 넘은 연구소 후보는 0개입니다.']
    near = sorted([r for r in fx if r['통과한_거름수'] == 3], key=lambda r: (r['갈래'], r['순위']))
    if near:
        miss = lambda r: next(n for n, k in (('① 다음 해 꼴', '거름1'), ('② 2026년·큰 변동 해', '거름2'), ('③ 반증 8개 모두', '거름3'), ('④ 가짜 p', '거름4')) if not r[k])
        M += ['', f'거름 셋만 넘은 후보 {len(near)}개(참고 — 통과 아님)', '']
        M += table(near[:30], [lambda r: r['갈래'], lambda r: r['순위'], lambda r: r['연구소등급'], lambda r: _cut(r['설명'], 90), lambda r: r['독립거래'], lambda r: _p(r['적중'], r['독립거래']),
                               lambda r: f"{r['n16']}건 {_pp(r['차이16'], r['n16'])}", lambda r: fmt_p(r['가짜p']), lambda r: f"{r['반증버틴수']}/8", miss],
                   ['갈래', '순위', '연구소 등급', '조건 설명', '독립 거래', '적중(결과를 보고 고른 숫자)', '2016~ 거래·차이', '가짜 p', '반증', '못 넘은 거름'])
        if len(near) > 30: M.append(f'\n(30개만 — 전부는 out/fixed.csv)')
    # ---- (나)
    M += ['', '## 4. (나) 갈래별 \'해마다 고르는 절차\'', '',
          '해 Y(2016~2026)마다 그 갈래 상위 100개 가운데 **Y 전 자료만으로** 통과 꼴(적중 85%)·관찰 꼴(80%)을 채운 규칙을 골라 Y 에 쓴 성적입니다. 쓰는 법은 T1 과 같은 꼴(윌슨 하한 상위 1·5·20개 × 하나라도 / 20% 이상 함께).',
          '최소 거래 수는 둘 다 돌렸습니다: 35건 고정(지시 그대로) / T1 과 같은 줄인 건수(2016년 12건 … 2026년 33건).', '',
          '> **조심: 상위 100개라는 묶음 자체가 전체 기간(2026년까지) 결과로 뽑힌 것이라 이 숫자도 좋게 나오는 쪽으로 기웁니다.** Signal A 줄기의 다음 해 성적(묶음도 미리 정함)과 같은 값으로 읽으면 안 됩니다.', '']
    M += table(list(G), [lambda g: BR_NAME[g], lambda g: (W[g][0]['묶음_규칙수'] if W[g] else 0), lambda g: sum(r['독립거래'] >= 30 for r in W[g]), lambda g: cnt(W[g], '거름1'), lambda g: cnt(W[g], '거름2'),
                         lambda g: cnt(W[g], '거름3'), lambda g: cnt(W[g], '거름4'), lambda g: f"**{cnt(W[g], '넷다')}**", lambda g: cnt(W[g], '통과숫자_35건_85'), lambda g: cnt(W[g], '관찰숫자_35건_80')],
               ['갈래', '묶음의 규칙 수(주 방향·거래일 있음)', '독립 30건 이상 절차(20개 중)', '① 다음 해 기준', '② 2026년·큰 변동 해', '③ 반증 8개 모두', '④ 가짜 p 1% 미만', '넷 다 통과', '통과 숫자(35건·85%)를 다음 해 성적으로', '관찰 숫자(80%)'])
    M += ['', '갈래별 가장 좋은 절차(독립 30건 이상 가운데 아무 날과의 차이가 가장 큰 것)', '']
    bl = [(g, best[g]) for g in G]
    M += table(bl, [lambda x: BR_NAME[x[0]], lambda x: '없음' if x[1] is None else f"{SH_KO[x[1]['꼴']]} · {NM_KO[x[1]['최소건수']]} · 상위 {x[1]['쓰는수']}개 · {HOW_KO[x[1]['만드는법']]}",
                    lambda x: '–' if x[1] is None else x[1]['독립거래'], lambda x: '–' if x[1] is None else _p(x[1]['적중'], x[1]['독립거래']), lambda x: '–' if x[1] is None else _p(x[1]['아무날'], x[1]['독립거래']),
                    lambda x: '–' if x[1] is None else _pp(x[1]['차이'], x[1]['독립거래']), lambda x: '–' if x[1] is None else _sum(x[1]['수익합계']),
                    lambda x: '–' if x[1] is None else f"{x[1]['앞n_2016_2023']}건 {_p(x[1]['앞적중'], x[1]['앞n_2016_2023'])} · {x[1]['뒤n_2024_']}건 {_p(x[1]['뒤적중'], x[1]['뒤n_2024_'])}",
                    lambda x: '–' if x[1] is None else f"{x[1]['y26_n']}건 {_p(x[1]['y26_hit'], x[1]['y26_n'])}",
                    lambda x: '–' if x[1] is None else f"{fmt_p(x[1]['가짜p'])} → {fmt_p(x[1]['가짜p_보정뒤'])}",
                    lambda x: '–' if x[1] is None else f"① {yn(x[1]['거름1'])} · ② {yn(x[1]['거름2'])} · ③ {yn(x[1]['거름3'])}({x[1]['반증버틴수']}/8) · ④ {yn(x[1]['거름4'])}",
                    lambda x: '–' if x[1] is None else ('**넷 다 통과**' if x[1]['넷다'] else f"{x[1]['통과한_거름수']}개 통과")],
               ['갈래', '절차', '독립 거래', '다음 해 적중', '같은 해 아무 날', '차이', '수익 합계', '앞(2016~2023) · 뒤(2024~)', '2026년', f'가짜 p(보정 전 → ×{M_WF})', '네 거름', '종합'])
    for g in G:
        rows = sorted([r for r in W[g] if r['독립거래'] >= S3.MIN_PCT], key=lambda r: (-(r['차이'] if r['차이'] is not None else -9), -r['독립거래']))
        M += ['', f"{BR_NAME[g]} — 절차 20개 가운데 거래 10건 이상 {len(rows)}개(차이 큰 순)", '']
        if not rows: M.append('- 거래가 10건 이상인 절차가 없습니다(그 전 자료로 꼴을 채운 규칙이 거의 없었음).'); continue
        M += table(rows[:10], [lambda r: f"{SH_KO[r['꼴']]} · {NM_KO[r['최소건수']]} · 상위 {r['쓰는수']}개 · {HOW_KO[r['만드는법']]}", lambda r: r['독립거래'], lambda r: _p(r['적중'], r['독립거래']),
                               lambda r: _p(r['아무날'], r['독립거래']), lambda r: _pp(r['차이'], r['독립거래']), lambda r: _sum(r['수익합계']), lambda r: fmt_p(r['가짜p']),
                               lambda r: f"{yn(r['거름1'])}/{yn(r['거름2'])}/{yn(r['거름3'])}/{yn(r['거름4'])}", lambda r: '**예**' if r['넷다'] else '아니오'],
                   ['절차', '독립 거래', '다음 해 적중', '같은 해 아무 날', '차이', '수익 합계', '가짜 p(보정 전)', '①/②/③/④', '넷 다'])
        if len(rows) > 10: M.append(f'\n(10개만 — 전부는 out/wf.csv)')
    if wf_pass:
        M += ['', f'네 거름을 모두 넘은 절차 {len(wf_pass)}개', '']
        M += table(wf_pass, [lambda r: r['갈래'], lambda r: f"{SH_KO[r['꼴']]} · {NM_KO[r['최소건수']]} · 상위 {r['쓰는수']}개 · {HOW_KO[r['만드는법']]}", lambda r: r['독립거래'], lambda r: _p(r['적중'], r['독립거래']),
                             lambda r: _pp(r['차이'], r['독립거래']), lambda r: f"{fmt_p(r['가짜p'])} → {fmt_p(r['가짜p_보정뒤'])}", lambda r: f"{r['y26_n']}건 {_p(r['y26_hit'], r['y26_n'])}",
                             lambda r: (f"{r['1위로_가장_자주_뽑힌_순위']}위({r['1위로_뽑힌_해수']}해)" if r['1위로_가장_자주_뽑힌_순위'] is not None else '–'), lambda r: _cut(r['관찰목록과'], 70)],
                   ['갈래', '절차', '독립 거래', '다음 해 적중', '차이', f'가짜 p(보정 전 → ×{M_WF})', '2026년', '1위로 가장 자주 뽑힌 규칙(순위표 순위)', 'Signal A 관찰 목록과'])
    # ---- 해마다 고른 규칙 수
    M += ['', '해마다 고른 규칙 수(관찰 꼴 · 줄인 건수 기준 / 35건 고정 기준)', '']
    pk = {(x['갈래'], x['해'], x['꼴'], x['최소건수']): x for x in picks}
    M += table(list(G), [lambda g: BR_NAME[g]] + [(lambda g, y=y: f"{pk.get((g, y, 'watch', 'nT1'), {}).get('고른_규칙수', 0)} / {pk.get((g, y, 'watch', 'n35'), {}).get('고른_규칙수', 0)}") for y in C.WF_YEARS],
               ['갈래'] + [str(y) for y in C.WF_YEARS])
    # ---- 관찰 목록과
    M += ['', '## 5. Signal A 관찰 목록 3개와 견줌 (같은 뿌리인지)', '',
          '재는 법: 2016년 이후 독립 거래가 들고 있는 날(매수일~청산일)의 겹침. 양쪽 모두 80% 이상 = 사실상 같은 신호, 한쪽만 80% 이상 = 한쪽이 포함, 한쪽 50% 이상 = 많이 겹침.', '']
    if passers:
        M += table(passers, [lambda r: f"{r['갈래']} {r['순위']}위", lambda r: _cut(r['설명'], 80), lambda r: r['뿌리표시'] or '–', lambda r: r['관찰목록과']], ['넷 다 통과한 후보', '조건 설명', '글자로 본 뿌리', 'Signal A 관찰 목록과'])
        nq = sum(bool(r['뿌리표시']) for r in passers)
        M += ['', f"- 한 줄: 넷 다 통과한 {len(passers)}개 가운데 **{nq}개가 '분기물 콜벽' 뿌리**(관찰 목록 ①과 같은 원리)이고, 보유 기간이 관찰 목록과 많이 겹치는 것(50% 이상)은 {len(same)}개입니다."
              + (' 즉 새로 나온 뿌리가 아니라 Signal A 가 이미 관찰 목록에 올린 것과 같은 줄기입니다.' if nq == len(passers) and nq else '')]
    else:
        M += ['- 넷 다 통과한 연구소 후보가 없어 견줄 것이 없습니다.']
    bb = [(g, best[g]) for g in G if best[g] is not None]
    if bb:
        M += ['', '갈래별 가장 좋은 절차와 관찰 목록', '']
        M += table(bb, [lambda x: BR_NAME[x[0]], lambda x: f"{SH_KO[x[1]['꼴']]} · {NM_KO[x[1]['최소건수']]} · 상위 {x[1]['쓰는수']}개 · {HOW_KO[x[1]['만드는법']]}",
                        lambda x: (f"{x[1]['1위로_가장_자주_뽑힌_순위']}위 — " + _cut(next((r['desc'] for _, r in pools[x[0]].iterrows() if int(r['rank']) == x[1]['1위로_가장_자주_뽑힌_순위']), ''), 70)
                                   if x[1]['1위로_가장_자주_뽑힌_순위'] is not None else '–'), lambda x: x[1]['관찰목록과']],
                   ['갈래', '절차', '1위로 가장 자주 뽑힌 규칙', 'Signal A 관찰 목록과'])
    # ---- 조심할 점
    M += ['', '## 6. 조심할 점', '',
          f"- **확인 불가 {sum(unk.values())}개**(" + '·'.join(f'{g} {unk[g]}' for g in G) + ')는 거래일 기록이 없어 거름에 넣지 못했습니다. 넷 다 통과 수는 \'넣은 것 가운데\'의 수입니다.',
          '- 연구소 후보는 전체 기간 결과를 보고 고른 고정 규칙입니다. 거름 ①(가)는 숫자 꼴만 맞춘 것이고, 진짜 \'다음 해 성적\'은 4절의 절차뿐입니다. 그 4절도 묶음이 결과를 보고 뽑힌 것이라 기운 숫자입니다.',
          '- 연구소 등급·순위는 코스피200 선물 기준입니다. 코스피 지수로 재면 적중이 5~10%p 낮아질 수 있습니다(NOTES.md 1절). 이 보고서의 적중은 모두 코스피 지수 기준입니다.',
          '- 같은 뿌리의 규칙(문턱만 조금 다른 것)이 순위표에 여러 개 올라 있습니다. 넷 다 통과가 여러 개여도 서로 다른 신호가 여러 개라는 뜻이 아닙니다.',
          '- 갈래 C 의 신호일은 저장소의 미국 지표 파일(deriv/us/out)로 다시 만든 것입니다(고정 릴리스에는 없는 자료, 끝 날짜로 자름). 연구소 순위표의 앞 구간 숫자와 같을 때만 썼습니다.',
          '- 거름 ②는 큰 변동 해(2011·2020·2026) 독립 거래가 10건 미만이면 판정 불가(넘지 못함)입니다. 거래가 드문 규칙에 불리합니다.',
          '- 이 거름(네 가지)은 Signal A 최종 심사 때 결과를 본 뒤 총괄이 정한 것입니다. CRITERIA.md 의 \'최종 후보\' 기준(통과 숫자 + 3절 셋 다)과는 다릅니다. 이번 시험으로 최종 후보·관찰 목록을 바꾸지 않았습니다.',
          '- 새 자료에서 실제 신호 10건이 쌓이기 전에는 어느 것도 \'확정\'이라고 쓰지 않습니다(CRITERIA 4절).']
    if log: M += ['', '계산 중 적어 둔 것', ''] + [f'- {x}' for x in log]
    M += ['', '## 7. 시험 가짓수·근거 파일', '',
          f"- 이번 시험: (가) 고정 규칙 {tot_has}개(" + '·'.join(f'{g} {len(F[g])}' for g in G) + f") + (나) 절차 {len(wf)}개 = **{n_tested:,}가지**. 원장(state/ledger.json) 누적 {ledger_total:,}가지.",
          '- 연구소가 이 후보들을 찾으려고 시험한 수(연구소 원장, Signal A 원장에는 더하지 않음): ' + '·'.join(f"{g} {lab_tr[g]:,}" for g in G) + '.',
          f'- 가짜 신호 {iters:,}번(같은 해 안 날짜 옮기기), 반증 시험 8개(s3/SPEC.md 4절 그대로). 참고 판정(2016~ 구간)·반증·겹침은 가짓수에 더하지 않았습니다.',
          '- 미리 정한 목록: [x1/SPEC.md](SPEC.md) · 후보별 숫자: out/fixed.csv · 절차: out/wf.csv · 해마다 고른 규칙: out/wf_picks.csv · 반증: out/falsify.csv · 순위·출처: out/pool.csv · 겹침: out/overlap_watch.csv',
          '', '투자 권유 아님', '']
    return '\n'.join(M)


# ------------------------------------------------------------------ 7. 실행
def lab_trials(g, fallback):
    try:
        return int(json.load(open(os.path.join(LAB, BR_STATE[g], 'ledger.json'), encoding='utf-8'))['trials_total'])
    except Exception:                                                # noqa: BLE001
        return int(fallback)


def add_log(line_core, n_tested, total, now):
    """log.md 에 한 줄(다시 돌리면 그 줄을 고쳐 쓴다 — 한 줄만 남게)."""
    lp = os.path.join(C.SA, 'log.md'); lines = open(lp, encoding='utf-8').read().rstrip('\n').split('\n')
    old = [i for i, x in enumerate(lines) if '| X1 거름 시험(GitHub) |' in x]
    nums = [int(x.split('|')[1]) for i, x in enumerate(lines) if x.startswith('|') and x.split('|')[1].strip().isdigit() and i not in old]
    no = max(nums) + 1 if nums else 1
    new = f"| {no} | {now[:10]} | X1 거름 시험(GitHub) | 연구소 갈래 A·B·C·D 상위 100위를 네 거름에 넣음(x1/SPEC.md·x1/report.md). 최종 후보·관찰 목록은 그대로 | {line_core[0]} | {line_core[1]} | {n_tested:,} (누적 {total:,}) |"
    lines = [x for i, x in enumerate(lines) if i not in old] + [new]
    open(lp, 'w', encoding='utf-8').write('\n'.join(lines) + '\n')


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--iters', type=int, default=2000); ap.add_argument('--no-state', action='store_true')
    ap.add_argument('--quick', action='store_true'); ap.add_argument('--out', default='')
    a = ap.parse_args(); iters = 50 if a.quick and a.iters == 2000 else a.iters
    base = a.out or HERE; OUT = os.path.join(base, 'out'); os.makedirs(OUT, exist_ok=True); os.makedirs(os.path.join(base, 'notify'), exist_ok=True)
    now = pd.Timestamp.now(tz='Asia/Seoul').strftime('%Y-%m-%d %H:%M'); log = []
    rp = os.path.join(HERE, 'redo.txt'); redo = open(rp, encoding='utf-8').read().strip() if os.path.exists(rp) else ''   # 다시 돌린 까닭(있으면 보고서·카카오 글에 '정정'으로 적는다)
    if redo: log.append('다시 돌림(정정): ' + redo.replace('\n', ' '))
    D = C.Data(); B = S3.Base(D); refs = watch_refs(D, log)
    pools = {}; infos = {}; TRS = {}; fx = []; wf = []; frows = []; orows = []; picks = []; lab_tr = {}
    for g in 'ABCD':
        pool, info = rank_pool(g); pool, TR = attach_trades(D, g, pool, log); pools[g] = pool; infos[g] = info; TRS[g] = TR
        lab_tr[g] = lab_trials(g, len(pool))
        print(f"{g}: 순위표 {info['rounds']}개(건너뜀 {info['skipped']}) · 서로 다른 후보 {info['uniq']} · 대상 {len(pool)} · 거래일 있음 {len(TR)}", flush=True)
        r1, f1, o1 = run_fixed(D, B, g, pool, TR, refs, iters, max(1, lab_tr[g]), limit=6 if a.quick else None); fx += r1; frows += f1; orows += o1
        print(f"{g}: (가) {len(r1)}개 끝 · 넷 다 {sum(r['넷다'] for r in r1)}", flush=True)
        r2, f2, o2, pk = run_wf(D, B, g, pool, TR, refs, iters); wf += r2; frows += f2; orows += o2; picks += pk
        print(f"{g}: (나) {len(r2)}개 끝 · 넷 다 {sum(r['넷다'] for r in r2)}", flush=True)
    # ---- 표 저장
    pc = ['갈래', 'rank', 'grade', 'P', 'W', 'id', 'family', 'desc', 'direction', 'round', 'all_n', 'all_hit', 'all_lb', 'dev_n', 'dev_hit', 'p2_n', 'p2_hit', '버팀',
          'src', 'src_note', 'n_signals', 'has_tdev', 'lab_dev_ok', 'lab_p2_ok', 'lab_all_ok']
    PL = pd.concat([pools[g].assign(갈래=g) for g in 'ABCD'], ignore_index=True)
    PL.reindex(columns=pc).to_csv(os.path.join(OUT, 'pool.csv'), index=False, encoding='utf-8')
    pd.DataFrame(fx).to_csv(os.path.join(OUT, 'fixed.csv'), index=False, encoding='utf-8')
    pd.DataFrame(wf).to_csv(os.path.join(OUT, 'wf.csv'), index=False, encoding='utf-8')
    pd.DataFrame(picks).to_csv(os.path.join(OUT, 'wf_picks.csv'), index=False, encoding='utf-8')
    fc = ['후보', '구간', '시험', '시험갈래', '이름', '독립거래', '원래의_비율', '적중', '바탕', '차이', '수익합계', 'p', '버팀', '비고']
    pd.DataFrame(frows).rename(columns={'갈래': '시험갈래'}).reindex(columns=fc).to_csv(os.path.join(OUT, 'falsify.csv'), index=False, encoding='utf-8')
    pd.DataFrame(orows).to_csv(os.path.join(OUT, 'overlap_watch.csv'), index=False, encoding='utf-8')
    # ---- 가짓수·원장
    fam = {f'가_고정규칙_갈래{g}': sum(r['갈래'] == g for r in fx) for g in 'ABCD'}; fam.update({f'나_해마다고름_갈래{g}': sum(r['갈래'] == g for r in wf) for g in 'ABCD'})
    n_tested = int(sum(fam.values())); n_all = sum(r['넷다'] for r in fx); n_wf_all = sum(r['넷다'] for r in wf)
    Lp = os.path.join(C.STATE, 'ledger.json'); L0 = json.load(open(Lp, encoding='utf-8')) if os.path.exists(Lp) else {'trials': []}
    total = int(sum(x['n'] for x in L0.get('trials', []) if x.get('track') != 'x1')) + n_tested
    bests = {g: best_proc([r for r in wf if r['갈래'] == g]) for g in 'ABCD'}
    bb = [b for b in bests.values() if b is not None and b['독립거래'] >= J.C31['n']]; top = max(bb, key=lambda r: r['차이']) if bb else None
    core = (f"다음 해 최고 {_p(top['적중'], top['독립거래'])}(아무 날 {_p(top['아무날'], top['독립거래'])}, {top['독립거래']}거래, 갈래 {top['갈래']} — 기운 숫자)" if top else '해마다 고르기: 30건 이상 절차 없음')
    n_pool = sum(len(pools[g]) for g in 'ABCD'); n_unk = n_pool - sum(len(TRS[g]) for g in 'ABCD')
    verdict = f"넷 다 통과: 고정 규칙 {n_all}개(" + '·'.join(f"{g} {sum(r['넷다'] for r in fx if r['갈래'] == g)}" for g in 'ABCD') + f") · 절차 {n_wf_all}개 · 확인 불가 {n_unk}개"
    if not a.no_state and not a.quick and not a.out:
        C.ledger_add('x1', fam, note=f"연구소 갈래 A·B·C·D 상위 100위 거름 시험 — {verdict}")
        add_log((core, verdict), n_tested, total, now)
    rep = report(now, iters, a.quick, pools, infos, fx, wf, picks, lab_tr, log, n_tested, total)
    if redo: rep = rep.replace('\n## 1. 결론\n', '\n> **정정본입니다.** ' + redo.replace('\n', ' ') + '\n\n## 1. 결론\n', 1)
    open(os.path.join(base, 'report.md'), 'w', encoding='utf-8').write(rep)
    summ = {'at': now, 'data_end': str(C.END.date()), 'iters': iters, 'quick': bool(a.quick), 'n_tested': n_tested, 'families': fam, 'ledger_total': total, 'lab_trials': lab_tr,
            'branches': {g: {'pool': len(pools[g]), 'with_trades': len(TRS[g]), 'unknown': len(pools[g]) - len(TRS[g]), 'tested': sum(r['갈래'] == g for r in fx),
                             'f1': sum(r['거름1'] for r in fx if r['갈래'] == g), 'f2': sum(r['거름2'] for r in fx if r['갈래'] == g), 'f3': sum(r['거름3'] for r in fx if r['갈래'] == g),
                             'f4': sum(r['거름4'] for r in fx if r['갈래'] == g), 'all4': sum(r['넷다'] for r in fx if r['갈래'] == g), 'ref16_all4': sum(r['참고16_넷다'] for r in fx if r['갈래'] == g),
                             'wf_all4': sum(r['넷다'] for r in wf if r['갈래'] == g), 'wf_best': bests[g], 'rounds': infos[g]['rounds'], 'skipped': infos[g]['skipped'], 'uniq': infos[g]['uniq']} for g in 'ABCD'},
            'passers': [r['key'] for r in fx if r['넷다']], 'wf_passers': [r['key'] for r in wf if r['넷다']], 'log': log}
    json.dump(summ, open(os.path.join(OUT, 'summary.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=_js)
    json.dump({'at': now, 'n_tested': n_tested, 'all4_fixed': int(n_all), 'all4_wf': int(n_wf_all), 'unknown': int(n_unk), 'iters': iters}, open(os.path.join(OUT, 'done.json'), 'w', encoding='utf-8'), ensure_ascii=False)
    msg = (f"[Signal A X1] {'(정정) ' if redo else ''}연구소 A·B·C·D 상위 {n_pool}개 중 거래일 있는 {n_pool - n_unk}개 거름 시험 끝. 네 거름 모두 통과: "
           + '·'.join(f"{g} {sum(r['넷다'] for r in fx if r['갈래'] == g)}" for g in 'ABCD') + f"개, 해마다 고르는 절차 {len(wf)}개 중 {n_wf_all}개. {core}. 확인 불가 {n_unk}개. 보고서 x1/report.md. 투자 권유 아님")
    if len(msg) > 198: msg = msg[:186].rstrip() + '… 투자 권유 아님'
    open(os.path.join(base, 'notify', 'kakao.txt'), 'w', encoding='utf-8').write(msg + '\n')
    print(msg)


if __name__ == '__main__':
    main()
