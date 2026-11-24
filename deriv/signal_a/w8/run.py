# -*- coding: utf-8 -*-
"""Signal A W8 — 참고 분석: 가짜 신호 시험의 가짓수 보정을 다른 방식으로 다시 재기(SPEC.md 그대로, 기준은 바꾸지 않는다).

  (가) 가짜 20,000번: sa_common.placebo_same_year 를 횟수만 늘려(대상 A 1차 후보 60 · B X1 통과 · C 2차 후보).
  (나) 묶음 전체에서 가장 좋은 가짜와 견주기: 해마다 고르는 절차 전부, 신호 날짜는 두고 결과 줄을 해 안에서만 통째로 돌림(묶음 안 모든 절차에 같은 돌림).
  python run.py --nparts | --part 1/1 | --merge [--quick]
시험용 환경 변수: W8_T1(1차 줄기, 기본 t1~t5) · W8_T2(2차 줄기, 기본 w1~w7).
읽을 줄기 결과가 없으면 멈춘다. 원장에는 더하지 않는다(이미 정해진 후보를 다시 재는 것).
"""
import hashlib
import json
import os
import sys

import numpy as np
import pandas as pd
from joblib import Parallel, delayed

HERE = os.path.dirname(os.path.abspath(__file__))
SA = os.path.dirname(HERE)
for _p in (SA, HERE):
    if _p not in sys.path: sys.path.insert(0, _p)
os.environ['PYTHONPATH'] = os.pathsep.join([HERE, SA] + [p for p in os.environ.get('PYTHONPATH', '').split(os.pathsep) if p and p not in (HERE, SA)])
import sa_common as C  # noqa: E402

TRACK = 'w8'
OUT = os.path.join(SA, TRACK, 'out')
NJ = max(1, min(4, os.cpu_count() or 1))
T1 = [x.strip() for x in (os.environ.get('W8_T1') or 't1,t2,t3,t4,t5').split(',') if x.strip()]
T2 = [x.strip() for x in (os.environ.get('W8_T2') or 'w1,w2,w3,w4,w5,w6,w7').split(',') if x.strip()]
N_ITER = 20000          # (가)·(나) 가짜 횟수
CHUNK = 500             # (나) 한 조각의 돌림 수 → 40조각
SUB = 100               # 한 번에 계산하는 돌림 수(메모리)
MAXP = 40000            # 결과 줄 묶음 하나의 신호 수 상한(메모리)
MIN_N = 10              # 독립 거래 10건 미만은 가짜 시험을 하지 않는다(판정과 같음)
ALPHA = 0.05


def _js(o):
    if hasattr(o, 'item'): return o.item()
    if isinstance(o, (pd.Timestamp,)): return str(o.date())
    return str(o)


def grade_of(r):
    """S3 1절과 같은 등급. 0 = 후보 아님."""
    if r.get('final'): return 1
    if r.get('c31'): return 2
    if r.get('goal_pass'): return 3
    if r.get('watch_pass'): return 4
    return 0


def read_track(tk):
    jp = os.path.join(SA, tk, 'out', 'judge.json')
    if not os.path.exists(jp): raise RuntimeError(f'W8: {tk} 의 판정(out/judge.json)이 없음 — 멈춤')
    jd = json.load(open(jp, encoding='utf-8')); cands, meta = C.load_result(tk)
    return jd, {c['id']: c for c in cands}, meta


def prep(D, tk, r, c):
    """판정과 같은 계산으로 독립 거래표·보유일·base_y 를 만든다."""
    d = int(r.get('direction') or c.get('direction') or 1); tr = c['trades']
    by = C.base_arr(D, c.get('base_y')) if ('hit' in tr and c.get('base_y') is not None) else None
    a = C.score(tr, d, D.K); t = a['t']; h = int(r.get('hold') or C.hold_days(t, D.td))
    return {'key': f"{tk}:{r['id']}", 'track': tk, 'id': r['id'], 'd': d, 'h': h, 't': t, 'by': by, 'row': r, 'kind': r.get('kind', 'fixed'), 'n': int(a['n']), 'hit': a['hit']}


# ------------------------------------------------------------------ (나) 결과 줄을 해 안에서 통째로 돌리기
def _rot_chunk(seed, nb, ya, yl, groups):
    """돌림 nb 번. groups = [(H 결과 줄[n], pos 신호 위치[P], yi 해 번호[P], off 절차별 시작[m])]. 반환 = 묶음마다 가짜 적중률 [nb, m] (float32)."""
    rng = np.random.default_rng(seed); ny = len(ya)
    R = np.stack([rng.integers(1, max(2, int(yl[y])), size=nb) for y in range(ny)], axis=1).astype(np.int64)   # [nb, 해]
    out = []
    for H, pos, yi, off in groups:
        a = ya[yi].astype(np.int64); L = yl[yi].astype(np.int64); rel = pos.astype(np.int64) - a; res = np.empty((nb, len(off)), dtype=np.float32)
        for s in range(0, nb, SUB):
            r = R[s:s + SUB][:, yi]
            idx = a[None, :] + (rel[None, :] - r) % L[None, :]
            v = H[idx]; fin = np.isfinite(v)
            cs = np.add.reduceat(np.where(fin, v, 0.0), off, axis=1); cn = np.add.reduceat(fin.astype(np.int32), off, axis=1)
            res[s:s + SUB] = np.where(cn > 0, cs / np.maximum(cn, 1), 0.0)
        out.append(res)
    return out


def rotation(D, members, n_iter):
    """members(절차 목록, 독립 거래 10건 이상) → S[j, b](가짜 적중률), real[j]. 묶음 안 모든 절차에 같은 돌림을 쓴다."""
    years = np.unique(D.year); ya = np.asarray([int(np.flatnonzero(D.year == y)[0]) for y in years]); yl = np.asarray([int((D.year == y).sum()) for y in years])
    ymap = {int(y): i for i, y in enumerate(years)}
    Hs = {}; gm = {}
    for j, m in enumerate(members):
        if m['by'] is not None:
            b = np.asarray(m['by'], dtype=float); k = ('by', hashlib.sha1(np.nan_to_num(b, nan=-1.0).tobytes()).hexdigest()); Hs.setdefault(k, b)
        else:
            k = ('hold', m['d'], m['h'])
            if k not in Hs:
                r = D.fwd(m['h']); Hs[k] = np.where(np.isfinite(r), (m['d'] * r > 0).astype(float), np.nan)
        pos = D.td.get_indexer(pd.DatetimeIndex(m['t']['signal'])); ok = pos >= 0
        m['_pos'] = pos[ok].astype(np.int64); m['_k'] = k
        if m['by'] is not None and 'ok' in m['t']: m['_real'] = float(np.asarray(m['t']['ok'], dtype=float)[ok].mean())
        else:
            v = Hs[k][m['_pos']]; m['_real'] = float(np.nanmean(v)) if np.isfinite(v).any() else np.nan
        gm.setdefault(k, []).append(j)
    groups = []; order = []                                         # 묶음 하나의 신호 수가 MAXP 를 넘지 않게 나눈다
    for k, js in gm.items():
        cur = []; tot = 0
        for j in js + [None]:
            if j is None or (cur and tot + len(members[j]['_pos']) > MAXP):
                pos = np.concatenate([members[x]['_pos'] for x in cur]); off = np.r_[0, np.cumsum([len(members[x]['_pos']) for x in cur])[:-1]].astype(np.int64)
                yi = np.asarray([ymap[int(y)] for y in D.year[pos]], dtype=np.int64)
                groups.append((Hs[k], pos, yi, off)); order += cur; cur = []; tot = 0
            if j is not None: cur.append(j); tot += len(members[j]['_pos'])
    nch = int(np.ceil(n_iter / CHUNK)); sizes = [min(CHUNK, n_iter - i * CHUNK) for i in range(nch)]
    res = Parallel(n_jobs=NJ)(delayed(_rot_chunk)(C.SEED + 800000 + i, sizes[i], ya, yl, groups) for i in range(nch))
    S = np.empty((len(members), n_iter), dtype=np.float32); col = 0
    for i, r in enumerate(res):
        blk = np.concatenate(r, axis=1)                             # [nb, 절차(order 순)]
        S[np.asarray(order), col:col + sizes[i]] = blk.T; col += sizes[i]
    real = np.asarray([m['_real'] for m in members], dtype=float)
    return S, real


def family_p(S, real, fam_idx):
    """묶음(절차 번호 목록)마다 p_fam. 반환 (cnt[j] = 가짜가 실제 이상인 횟수, {묶음 이름: minq[b]}).
    적중률은 k/n 꼴이라 같은 값이 자주 나온다 — 실제도 가짜와 같은 float32 로 바꿔 '이상'을 정확히 센다. 실제 값이 없으면(nan) 가짜가 모두 이상인 것으로 친다(p = 1)."""
    B = S.shape[1]; r32 = real.astype(np.float32); cnt = (S >= r32[:, None]).sum(1); cnt[~np.isfinite(real)] = B
    q_min = {}
    for name, idx in fam_idx.items():
        mq = np.ones(B, dtype=np.float32)
        for j in idx:
            s = S[j]; o = np.sort(s); q = (B - np.searchsorted(o, s, side='left')) / B
            np.minimum(mq, q.astype(np.float32), out=mq)
        q_min[name] = mq
    return cnt, q_min


def _p_fam(cnt_j, mq, B):
    return float((1 + (mq <= cnt_j / B + 1e-12).sum()) / (1 + B))


def _p20k_chunk(items, n_iter):
    """(가) 가짜 n_iter 번 — 일꾼마다 자료를 따로 읽는다(판정과 같은 함수·같은 씨앗)."""
    D = C.Data(); out = []
    for t, d, h, by in items:
        out.append(C.placebo_same_year(D, t, d, h=h, n_iter=n_iter, base_y=by)['p'])
    return out


# ------------------------------------------------------------------ 조각(하나) — 계산 전부
def n_parts(vol=False):
    return 1


def run_part(i, n, vol=False, quick=False):
    n_iter = 200 if quick else N_ITER
    D = C.Data(); tracks = T1 + T2; J = {}; CA = {}; META = {}
    for tk in tracks: J[tk], CA[tk], META[tk] = read_track(tk)
    rows_of = {tk: {r['id']: r for r in J[tk].get('rows') or []} for tk in tracks}

    # ---- 묶음(가족): 해마다 고르는 절차 전부
    members = []; midx = {}
    for tk in tracks:
        if tk == 't6': continue
        for r in J[tk].get('rows') or []:
            if r.get('kind') != 'wf' or (r.get('all_n') or 0) < MIN_N: continue
            c = CA[tk].get(r['id'])
            if c is None: raise RuntimeError(f"W8: {tk}:{r['id']} 의 거래일이 cands.pkl 에 없음")
            m = prep(D, tk, r, c)
            if m['n'] < MIN_N: continue
            midx[m['key']] = len(members); members.append(m)
    if not members: raise RuntimeError('W8: 해마다 고르는 절차(독립 10건 이상)가 하나도 없음 — 멈춤')
    S, real = rotation(D, members, n_iter)
    stage = lambda tk: '1차' if tk in T1 else '2차'
    fam_idx = {}
    for j, m in enumerate(members):
        fam_idx.setdefault(m['track'], []).append(j)
    cnt, mq = family_p(S, real, fam_idx)
    mq_stage = {}
    for st in ('1차', '2차'):
        tks = [tk for tk in fam_idx if stage(tk) == st]
        if tks: mq_stage[st] = np.minimum.reduce([mq[tk] for tk in tks])
    mq_all = np.minimum.reduce(list(mq.values()))
    B = S.shape[1]; procs = []
    for j, m in enumerate(members):
        r = m['row']
        procs.append({'key': m['key'], 'track': m['track'], 'stage': stage(m['track']), 'id': m['id'], 'desc': r.get('desc'), 'direction': m['d'], 'hold': m['h'], 'n': m['n'], 'hit': m['hit'],
                      'base': r.get('base'), 'edge': r.get('edge'), 'goal_pass': bool(r.get('goal_pass')), 'watch_pass': bool(r.get('watch_pass')), 'c31': bool(r.get('c31')), 'c33': bool(r.get('c33')),
                      'final': bool(r.get('final')), 'fake_p': r.get('fake_p'), 'fake_m': r.get('fake_m'), 'fake_p_adj': r.get('fake_p_adj'),
                      'real_rot': float(real[j]) if np.isfinite(real[j]) else None, 'fake_mean_rot': float(S[j].mean()),
                      'p_rot': float((1 + cnt[j]) / (1 + B)), 'p_fam_track': _p_fam(cnt[j], mq[m['track']], B), 'p_fam_stage': _p_fam(cnt[j], mq_stage[stage(m['track'])], B),
                      'p_fam_all': _p_fam(cnt[j], mq_all, B)})
    pby = {p['key']: p for p in procs}

    # ---- 대상 A·B·C
    targets = []; seen = set()

    def add(group, tk, rid, extra=None):
        key = f'{tk}:{rid}'
        if (group, key) in seen: return
        r = rows_of[tk].get(rid); c = CA[tk].get(rid)
        if r is None or c is None: raise RuntimeError(f'W8: 대상 {key} 를 판정·후보 파일에서 못 찾음')
        seen.add((group, key)); t = prep(D, tk, r, c); t['group'] = group; t['extra'] = extra or {}; targets.append(t)

    sp = os.path.join(SA, 's3', 'out', 'candidates.json')
    if not os.path.exists(sp): raise RuntimeError('W8: s3/out/candidates.json 이 없음(1차 후보 60개) — 멈춤')
    for o in json.load(open(sp, encoding='utf-8')).get('candidates') or []:
        if o['track'] in T1: add('A 1차 후보', o['track'], o['id'], {'no': o.get('no'), 'grade': o.get('grade_label')})
    nA = sum(t['group'].startswith('A') for t in targets)
    if not nA and not quick: raise RuntimeError('W8: 1차 후보(대상 A)가 0개 — 멈춤')
    nB = 0
    if 'w7' in T2:
        for cid, c in CA['w7'].items():
            p = c.get('params') or {}
            if c.get('kind') == 'fixed' and p.get('origin') == 'X1' and p.get('pass4'): add('B X1 통과', 'w7', cid, {'branch': p.get('branch')}); nB += 1
    for tk in T2:
        for r in J[tk].get('rows') or []:
            if grade_of(r): add('C 2차 후보', tk, r['id'], {'grade': grade_of(r)})
        if tk == 'w7':
            for cid, c in CA['w7'].items():
                p = c.get('params') or {}
                if p.get('pass4') and (c.get('kind') == 'wf' or p.get('origin') in ('R', 'V')): add('C 2차 후보', 'w7', cid, {'w7_pass4': True, 'branch': p.get('branch')})

    def one(t, p20):
        r = t['row']; m = int(r.get('fake_m') or 1); o = {'group': t['group'], 'key': t['key'], 'track': t['track'], 'id': t['id'], 'kind': t['kind'], 'desc': r.get('desc'), 'direction': t['d'], 'hold': t['h'],
                                                          'n': t['n'], 'hit': t['hit'], 'base': r.get('base'), 'edge': r.get('edge'), 'goal_pass': bool(r.get('goal_pass')), 'watch_pass': bool(r.get('watch_pass')),
                                                          'c31': bool(r.get('c31')), 'c33': bool(r.get('c33')), 'final': bool(r.get('final')), 'fake_p': r.get('fake_p'), 'fake_m': m, 'fake_p_adj': r.get('fake_p_adj'), **t['extra']}
        o['p20k'] = p20; o['p20k_adj'] = (min(1.0, p20 * m) if p20 is not None else None)
        p = pby.get(t['key'])
        for k in ('p_rot', 'p_fam_track', 'p_fam_stage', 'p_fam_all'): o[k] = p[k] if p else None
        return o
    todo = [i for i, t in enumerate(targets) if t['n'] >= MIN_N]; p20 = {}
    if todo:
        chunks = [c for c in np.array_split(np.asarray(todo), NJ * 2) if len(c)]
        res = Parallel(n_jobs=NJ)(delayed(_p20k_chunk)([(targets[i]['t'][['signal', 'exit'] + [x for x in ('ok',) if x in targets[i]['t']]], targets[i]['d'], targets[i]['h'], targets[i]['by']) for i in c], n_iter) for c in chunks)
        for c, r in zip(chunks, res):
            for i, v in zip(c, r): p20[int(i)] = v
    trows = [one(t, p20.get(i)) for i, t in enumerate(targets)]

    fam = []
    for tk in tracks:
        if tk == 't6': continue
        ps = [p for p in procs if p['track'] == tk]; rows = [r for r in J[tk].get('rows') or [] if r.get('kind') == 'wf']
        adj = [r['fake_p_adj'] for r in rows if r.get('fake_p_adj') is not None]
        ok1 = [p for p in ps if p['p_fam_track'] < ALPHA]; ok3 = [p for p in ps if p['p_fam_all'] < ALPHA]
        fam.append({'track': tk, 'stage': stage(tk), 'm_wf': int(J[tk].get('m_wf') or META[tk].get('m_wf') or len(rows)), 'n_wf_rows': len(rows), 'n_members': len(ps),
                    'n_c31': sum(bool(r.get('c31')) for r in rows), 'min_p_adj_now': (min(adj) if adj else None), 'n_c32_now': sum(bool(r.get('c32')) for r in rows),
                    'min_p_fam_track': (min(p['p_fam_track'] for p in ps) if ps else None), 'min_p_fam_stage': (min(p['p_fam_stage'] for p in ps) if ps else None),
                    'min_p_fam_all': (min(p['p_fam_all'] for p in ps) if ps else None),
                    'n_fam_track': len(ok1), 'n_fam_track_c3': sum(p['c31'] and p['c33'] for p in ok1), 'n_fam_track_final_like': sum(p['c31'] and p['c33'] and p['goal_pass'] for p in ok1),
                    'n_fam_all': len(ok3), 'n_fam_all_c3': sum(p['c31'] and p['c33'] for p in ok3), 'n_fam_all_final_like': sum(p['c31'] and p['c33'] and p['goal_pass'] for p in ok3),
                    'can_pass_2000': bool(int(J[tk].get('m_wf') or 1) / 2001 < ALPHA), 'can_pass_20000': bool(int(J[tk].get('m_wf') or 1) / (n_iter + 1) < ALPHA)})
    return {'quick': bool(quick), 'n_iter': n_iter, 'tracks1': T1, 'tracks2': T2, 'procs': procs, 'targets': trows, 'families': fam, 'n_B': nB,
            'at': pd.Timestamp.now(tz='Asia/Seoul').strftime('%Y-%m-%d %H:%M')}


# ------------------------------------------------------------------ 합치기: 표·요약
def _pc(x): return '–' if x is None or (isinstance(x, float) and not np.isfinite(x)) else f'{100 * x:.1f}%'
def _pv(x): return '–' if x is None or (isinstance(x, float) and not np.isfinite(x)) else (f'{x:.5f}' if x < 0.001 else f'{x:.3f}')


def _md(head, rows):
    return ['| ' + ' | '.join(head) + ' |', '|' + '---|' * len(head)] + ['| ' + ' | '.join(str(v) for v in r) + ' |' for r in rows]


def _cut(s, n=90):
    s = str(s or '').replace('|', '/').replace('\n', ' ')
    return s if len(s) <= n else s[:n - 1] + '…'


def merge(parts, vol=False, quick=False):
    if not parts or parts[0] is None: raise RuntimeError('W8: 계산 조각이 없음 — 멈춤')
    P = parts[0]; os.makedirs(OUT, exist_ok=True); n_iter = P['n_iter']; procs = P['procs']; tg = P['targets']; fam = P['families']
    pd.DataFrame(fam).to_csv(os.path.join(OUT, 'families.csv'), index=False, encoding='utf-8')
    pd.DataFrame(tg).to_csv(os.path.join(OUT, 'targets.csv'), index=False, encoding='utf-8')
    pd.DataFrame(procs).to_csv(os.path.join(OUT, 'procs.csv'), index=False, encoding='utf-8')
    grp = {}
    for t in tg: grp.setdefault(t['group'], []).append(t)

    def gsum(ts):
        v = lambda k: [t[k] for t in ts if t.get(k) is not None]
        return {'n': len(ts), 'n_wf': sum(t['kind'] == 'wf' for t in ts), 'n_c31': sum(t['c31'] for t in ts),
                'n_now_c32': sum(1 for t in ts if t.get('fake_p_adj') is not None and t['fake_p_adj'] < ALPHA),
                'n_p20k_adj': sum(1 for t in ts if t.get('p20k_adj') is not None and t['p20k_adj'] < ALPHA),
                'n_fam_track': sum(1 for t in ts if t.get('p_fam_track') is not None and t['p_fam_track'] < ALPHA),
                'n_fam_stage': sum(1 for t in ts if t.get('p_fam_stage') is not None and t['p_fam_stage'] < ALPHA),
                'n_fam_all': sum(1 for t in ts if t.get('p_fam_all') is not None and t['p_fam_all'] < ALPHA),
                'min_now_adj': (min(v('fake_p_adj')) if v('fake_p_adj') else None), 'min_p20k_adj': (min(v('p20k_adj')) if v('p20k_adj') else None),
                'min_fam_track': (min(v('p_fam_track')) if v('p_fam_track') else None), 'min_fam_all': (min(v('p_fam_all')) if v('p_fam_all') else None)}
    gs = {g: gsum(ts) for g, ts in grp.items()}
    like = lambda k: [{'key': p['key'], 'desc': p['desc'], 'n': p['n'], 'hit': p['hit'], 'base': p['base'], 'edge': p['edge'], 'goal_pass': p['goal_pass'], 'p_fam_track': p['p_fam_track'], 'p_fam_stage': p['p_fam_stage'],
                       'p_fam_all': p['p_fam_all'], 'fake_p_adj': p['fake_p_adj']} for p in sorted(procs, key=lambda p: p[k]) if p['c31'] and p['c33'] and p[k] < ALPHA]
    c3_track = like('p_fam_track'); c3_all = like('p_fam_all')
    summ = {'at': P['at'], 'n_iter': n_iter, 'quick': bool(P['quick']), 'tracks1': P['tracks1'], 'tracks2': P['tracks2'], 'n_procs': len(procs), 'families': fam, 'groups': gs, 'n_B': P['n_B'],
            'ref_c3_track': c3_track[:50], 'ref_c3_all': c3_all[:50], 'n_ref_c3_track': len(c3_track), 'n_ref_c3_all': len(c3_all),
            'n_ref_final_like_track': sum(x['goal_pass'] for x in c3_track), 'n_ref_final_like_all': sum(x['goal_pass'] for x in c3_all),
            'note': '참고 분석 — CRITERIA 3절 2번과 판정(sa_judge.py)은 그대로다. 이 숫자로 최종 후보를 정하지 않는다.'}
    json.dump(summ, open(os.path.join(OUT, 'summary.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=_js)

    M = [f"### W8 참고 분석 — 가짜 시험의 가짓수 보정을 다른 방식으로 ({P['at']}, 가짜 {n_iter:,}번)" + (' [quick 시험]' if P['quick'] else ''), '',
         '**기준은 바꾸지 않았습니다.** 아래는 "지금 방식(가짜 2,000번 × 절차 수)" 옆에 두 가지 다른 재는 법을 나란히 적은 참고 숫자입니다. 이 숫자로 최종 후보를 정하지 않습니다.',
         '- (가) 가짜 20,000번: 같은 방식에서 횟수만 10배 → 절차 수 1,000개 미만 묶음은 셈으로 5% 를 넘을 수 있게 됨.',
         '- (나) 묶음 최고값: 신호 날짜는 두고 결과 줄을 해 안에서 통째로 돌림(묶음 안 모든 절차에 같은 돌림) → 가짜마다 묶음에서 가장 좋은 절차와 견줌. 닮은 절차가 많아도 지나치게 엄해지지 않음.',
         '', '#### (1) 줄기별 — 해마다 고르는 절차', '']
    M += _md(['줄기', '절차 수', '10건 이상', '다음 해 기준 넘음', '지금 방식 보정 뒤 p 최소', '지금 방식으로 넘은 수', '가짜 2,000번으로 셈이 되나', '참고(나) 줄기 묶음 p 최소', '참고(나) 단계 묶음 p 최소', '참고(나) 1·2차 전체 p 최소',
              '참고: 줄기 묶음 5% 미만', '그중 3절 1·3번도 넘음', '그중 통과 숫자도(최종 후보 꼴)', '참고: 전체 묶음 5% 미만 · 3절 1·3번도 · 통과 숫자도'],
             [[f['track'].upper(), f['m_wf'], f['n_members'], f['n_c31'], _pv(f['min_p_adj_now']), f['n_c32_now'], '됨' if f['can_pass_2000'] else '안 됨', _pv(f['min_p_fam_track']), _pv(f['min_p_fam_stage']), _pv(f['min_p_fam_all']),
               f['n_fam_track'], f['n_fam_track_c3'], f['n_fam_track_final_like'], f"{f['n_fam_all']} · {f['n_fam_all_c3']} · {f['n_fam_all_final_like']}"] for f in fam])
    M += ['', "- '최종 후보 꼴'은 1절 통과 숫자 + 3절 1·3번 + 참고 방식의 가짜 시험을 함께 채운 수입니다. **참고일 뿐 최종 후보가 아닙니다**(기준은 사용자만 바꿉니다).",
          '- 1·2차 전체 묶음이 가장 엄합니다. 2차에서 절차를 더 시험한 만큼 이 값은 엄해집니다.', '', '#### (2) 대상별 요약', '']
    M += _md(['대상', '후보 수', '그중 절차', '다음 해 기준 넘음', '지금 방식 5% 미만', '(가) 20,000번 × 가짓수 5% 미만', '(나) 줄기 묶음 5% 미만', '(나) 단계 묶음', '(나) 전체 묶음', '지금 방식 p 최소', '(가) p 최소', '(나) 줄기 묶음 p 최소', '(나) 전체 묶음 p 최소'],
             [[g, s['n'], s['n_wf'], s['n_c31'], s['n_now_c32'], s['n_p20k_adj'], s['n_fam_track'], s['n_fam_stage'], s['n_fam_all'], _pv(s['min_now_adj']), _pv(s['min_p20k_adj']), _pv(s['min_fam_track']), _pv(s['min_fam_all'])]
              for g, s in sorted(gs.items())])
    M += ['', f"- 대상 B(X1 통과 고정 규칙)는 {P['n_B']}개를 읽었습니다. 고정 규칙은 고른 모집단의 거래일이 없어 (나)를 잴 수 없고, (가)도 연구소가 시험한 수(수만~수십만)를 곱하면 넘을 수 없습니다.", '']
    for g, ts in sorted(grp.items()):
        ts = sorted(ts, key=lambda t: (t.get('p_fam_track') if t.get('p_fam_track') is not None else 9, t.get('p20k') if t.get('p20k') is not None else 9))[:25]
        M += [f'#### (3) {g} — 참고 p 가 작은 순 25개 (전부는 out/targets.csv)', '']
        M += _md(['후보', '종류', '독립 거래', '적중', '아무 날', '가짜 p(2,000)', '× 가짓수', '(가) p(20,000)', '× 가짓수', '(나) 돌림 p', '(나) 줄기 묶음', '(나) 단계 묶음', '(나) 전체 묶음'],
                 [[_cut(f"{t['key']} · {t['desc']}"), '절차' if t['kind'] == 'wf' else '고정 규칙', t['n'], _pc(t['hit']) if t['n'] >= MIN_N else '–', _pc(t['base']) if t['n'] >= MIN_N else '–', _pv(t['fake_p']),
                   f"{_pv(t['fake_p_adj'])}(×{t['fake_m']:,})", _pv(t['p20k']), _pv(t['p20k_adj']), _pv(t['p_rot']), _pv(t['p_fam_track']), _pv(t['p_fam_stage']), _pv(t['p_fam_all'])] for t in ts])
        M += ['']
    M += ["읽는 법: '고정 규칙'의 (나) 칸이 '–' 인 것은 잴 수 없어서입니다(모집단 거래일 없음). 근거 파일: w8/SPEC.md · out/families.csv · out/targets.csv · out/procs.csv", '']
    open(os.path.join(OUT, 'summary.md'), 'w', encoding='utf-8').write('\n'.join(M))
    json.dump({'at': P['at'], 'n_iter': n_iter, 'n_procs': len(procs), 'n_targets': len(tg), 'quick': bool(P['quick'])}, open(os.path.join(OUT, 'done.json'), 'w', encoding='utf-8'), ensure_ascii=False)
    return summ


if __name__ == '__main__':
    a = C.parse_part()
    if a['nparts']:
        print(n_parts())
    elif a['part']:
        i, n_ = a['part']; C.save_part(TRACK, i, n_, run_part(i, n_, quick=a['quick'])); print(f'w8 조각 {i}/{n_} 저장')
    elif a['merge']:
        s = merge(C.load_parts(TRACK, n_parts()), quick=a['quick'])
        print(f"w8: 절차 {s['n_procs']}개 · 가짜 {s['n_iter']:,}번 · 참고(줄기 묶음) 3절 셋 넘은 절차 {s['n_ref_c3_track']}개 · 전체 묶음 {s['n_ref_c3_all']}개")
    else:
        print(__doc__)
