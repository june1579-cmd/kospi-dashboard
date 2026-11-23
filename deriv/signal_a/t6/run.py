# -*- coding: utf-8 -*-
"""Signal A T6 청산 — SPEC.md 그대로. T1~T5 에서 다음 해 성적 기준(c31)을 넘은 후보의 신호 날짜에 청산 규칙 55가지를 견준다.

명령: python run.py --nparts | --part 1/1 | --merge | --quick   (vol 인자는 받되 쓰지 않는다)
"""
import json
import os
import re
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sa_common as C  # noqa: E402

TRACK = 't6'
SRC = ('t1', 't2', 't3', 't4', 't5')
MAX_T = 30                                   # 대상 후보 상한(edge 큰 순)
HOLDS = (1, 2, 3, 5, 7, 10, 15, 20)
STOPS = (None, -0.02, -0.03, -0.05)
TAKES = (None, 0.02, 0.03, 0.05)
MAXHOLDS = (5, 10, 20)
MAXH = 20                                    # 신호 꺼짐의 최대 보유일(= 손절·익절 최대 보유의 최댓값)
COSTS = (0.0, 0.0015, 0.0030)                # 왕복 비용 민감도
COST = 0.0015                                # 고를 때 쓰는 비용
MIN_N1, MIN_N2 = 10, 20                      # 절차 1·2 가 고르기 시작하는 '그 전 독립 거래 수'
MIN_PCT = 10
FAMS = ('보유일만', '손절·익절·최대 보유', '신호 꺼짐', '원래 보유일')
N_RULES = 55
NONE_NOTE = '다음 해 성적 기준을 넘은 후보가 없어 청산 비교 대상 없음'
NOT_INCLUDED = ['추적 손절(매수 뒤 최고가 대비 되돌림 청산)', '분할 청산(절반씩 나눠 팔기)',
                '변동폭에 맞춘 손절·익절 폭(직전 60일 일간 표준편차의 배수)', '다른 후보의 신호(반대 방향 신호)가 켜질 때 청산',
                '고르는 기준을 수익 합계·적중 말고 거래 평균·최대 손실로 바꿔 보기']
READ_NOTE = ('T6 은 적중이 아니라 비용 뒤 수익 합계·최대 손실로 읽는다 — 익절이 있는 규칙은 적중률이 저절로 높아지고, '
             "판정표의 '같은 해 아무 날' 비교는 보유일 종가 기준이라 손절·익절 규칙과 나란히 견줄 수 없다.")
OFF_NOTE = "신호 꺼짐 청산은 미래 자료를 막으려고 '신호가 없는 첫날 종가'가 아니라 '그 다음 거래일 시가'에 판다(그날 신호는 장 마감 뒤에야 알 수 있음)."


def _pc(x):
    return '없음' if x is None else f'{100 * x:+.0f}%'.replace('-', '−')


def rule_list(hold):
    """청산 규칙 55가지(순서 고정 = SPEC 3절). hold = 원 후보의 보유일."""
    R = [dict(fam=FAMS[0], rid=f'H{h}', label=f'보유 {h}일째 종가', type='hold', h=h) for h in HOLDS]
    for sl in STOPS:
        for tp in TAKES:
            if sl is None and tp is None: continue
            for H in MAXHOLDS:
                rid = f"S{0 if sl is None else int(round(-100 * sl))}T{0 if tp is None else int(round(100 * tp))}M{H}"
                R.append(dict(fam=FAMS[1], rid=rid, label=f'손절 {_pc(sl)}·익절 {_pc(tp)}·최대 {H}일', type='sltp', sl=sl, tp=tp, h=H))
    R.append(dict(fam=FAMS[2], rid='OFF', label=f'신호가 꺼진 다음 날 시가(최대 {MAXH}일)', type='off', h=None))
    R.append(dict(fam=FAMS[3], rid='ORIG', label=f'원래 보유 {hold}일째 종가', type='orig', h=int(hold)))
    assert len(R) == N_RULES
    return R


# ------------------------------------------------------------------ 청산 계산
def entries(D, signals):
    """신호 날짜 → 매수 위치 E(신호 다음 거래일, 겹침 없이 오름차순). 신호 위치 = E − 1."""
    s = pd.DatetimeIndex(pd.to_datetime(pd.Series(list(signals)), errors='coerce').dropna())
    s = s[(s >= C.START) & (s <= C.END)]
    E = np.unique(D.td.searchsorted(s, side='right'))
    return E[(E >= 1) & (E < D.n)].astype(int)


def paths(D, E, d, K):
    """매수가(시가) 대비 '방향을 곱한' 수익 길: 날 k=0..K−1 의 시가 ro·종가 rc·그날 가장 좋은 값 rhi·가장 나쁜 값 rlo, ok = 자료 안."""
    idx = E[:, None] + np.arange(K)[None, :]; ok = idx < D.n; ix = np.minimum(idx, D.n - 1); o0 = D.o[E][:, None]
    ro = d * (D.o[ix] / o0 - 1); rc = d * (D.c[ix] / o0 - 1); a = D.h[ix] / o0 - 1; b = D.l[ix] / o0 - 1
    rhi, rlo = (a, b) if d > 0 else (-b, -a)
    return dict(ro=ro, rc=rc, rhi=rhi, rlo=rlo, ok=ok, ix=ix)


def exit_rule(P, E, on, rule):
    """규칙 하나의 청산. 반환 (off = 매수일부터 센 청산 날 위치 0.., rd = 방향을 곱한 수익, valid = 자료 안에서 청산이 정해짐)."""
    m = len(E); r_i = np.arange(m); ok = P['ok']; t = rule['type']
    if t in ('hold', 'orig'):
        k = rule['h'] - 1
        return np.full(m, k), P['rc'][:, k], ok[:, k]
    if t == 'sltp':
        sl, tp, H = rule['sl'], rule['tp'], rule['h']; no = np.zeros_like(ok)
        stop = (P['rlo'] <= sl) if sl is not None else no
        take = (P['rhi'] >= tp) if tp is not None else no
        ev = (stop | take) & ok; ev[:, H:] = False
        has = ev.any(1); kf = ev.argmax(1); o_k = P['ro'][r_i, kf]
        gs = (o_k <= sl) if sl is not None else np.zeros(m, bool)          # 시가가 이미 손절선 아래
        gt = (o_k >= tp) if tp is not None else np.zeros(m, bool)          # 시가가 이미 익절선 위
        st = stop[r_i, kf]                                                 # 같은 날 둘 다면 손절
        rd_ev = np.where(gs | gt, o_k, np.where(st, np.nan if sl is None else sl, np.nan if tp is None else tp))
        return np.where(has, kf, H - 1), np.where(has, rd_ev, P['rc'][:, H - 1]), has | ok[:, H - 1]
    if t == 'off':
        K = MAXH; offd = (~on[P['ix'][:, :K - 1]]) & ok[:, :K - 1]         # 매수일부터 19일째까지 '신호 없는 날'(장 마감 뒤 확인)
        has = offd.any(1); kf = offd.argmax(1) + 1                         # 그 다음 거래일 시가에 청산
        return np.where(has, kf, K - 1), np.where(has, P['ro'][r_i, np.minimum(kf, K - 1)], P['rc'][:, K - 1]), np.where(has, ok[r_i, np.minimum(kf, K - 1)], ok[:, K - 1])
    raise ValueError(t)


def thin(sp, ex, valid):
    """독립 거래: 앞 거래 청산 위치 이후(같은 날 포함)의 신호만. sp 오름차순."""
    keep = []; last = -1
    for i in range(len(sp)):
        if valid[i] and sp[i] >= last: keep.append(i); last = ex[i]
    return np.asarray(keep, dtype=int)


def stats(rd, days=None):
    n = len(rd); out = {'n': int(n)}
    if not n:
        out.update({'hit': None, 'sum': 0.0, 'mean': None, 'worst': None, 'days': None})
        for c in COSTS: out[f'hit_c{int(round(c * 1e4))}'] = None; out[f'sum_c{int(round(c * 1e4))}'] = 0.0
        return out
    out.update({'hit': float((rd > 0).mean()), 'sum': float(rd.sum()), 'mean': float(rd.mean()), 'worst': float(rd.min()),
                'days': (float(np.mean(days)) if days is not None else None)})
    for c in COSTS:
        out[f'hit_c{int(round(c * 1e4))}'] = float((rd - c > 0).mean()); out[f'sum_c{int(round(c * 1e4))}'] = float((rd - c).sum())
    return out


def eval_target(D, signals, direction, hold):
    """대상 하나: 규칙 55가지의 청산을 모두 계산. 반환 dict(sp, rules, ex[55×m], rd[55×m], valid[55×m], keep[55개의 위치 배열])."""
    d = 1 if int(direction) >= 0 else -1; hold = max(1, int(hold)); E = entries(D, signals); sp = E - 1
    R = rule_list(hold); m = len(E); P = paths(D, E, d, max(MAXH, hold))
    on = np.zeros(D.n, dtype=bool); on[sp] = True
    ex = np.zeros((N_RULES, m), dtype=int); rd = np.zeros((N_RULES, m)); va = np.zeros((N_RULES, m), dtype=bool); keep = []
    for j, r in enumerate(R):
        off, x, v = exit_rule(P, E, on, r)
        ex[j] = E + off; rd[j] = np.where(v, x, np.nan); va[j] = v & np.isfinite(rd[j]); keep.append(thin(sp, ex[j], va[j]))
    return dict(d=d, hold=hold, E=E, sp=sp, rules=R, ex=ex, rd=rd, valid=va, keep=keep)


def choose(D, ev, year, proc):
    """해 year 에 쓸 규칙 번호. 각 규칙의 독립 거래 가운데 청산일이 그 해 1월 1일 전인 것만 본다. 반환 (규칙 번호, 그때 본 독립 거래 수)."""
    orig = N_RULES - 1; cut = int(D.td.searchsorted(pd.Timestamp(f'{year}-01-01')))
    prior = lambda j: ev['rd'][j][ev['keep'][j][ev['ex'][j][ev['keep'][j]] < cut]] - COST
    if proc == 3: return orig, int(len(prior(orig)))
    best, bkey, bn = orig, None, int(len(prior(orig)))
    for j in range(N_RULES):
        x = prior(j)
        if len(x) < (MIN_N1 if proc == 1 else MIN_N2): continue
        key = (float(x.sum()),) if proc == 1 else (float((x > 0).mean()), float(x.sum()))
        if bkey is None or key > bkey: best, bkey, bn = j, key, int(len(x))
    return best, bn


def wf_trades(D, ev, proc):
    """해마다 고른 규칙으로 그 해 신호 전부(솎지 않음)를 청산. 반환 (sp, ex, rd 배열, 해마다 고른 규칙 목록)."""
    ys = D.year[ev['sp']]; S, X, Rr, picks = [], [], [], []
    for y in C.WF_YEARS:
        j, n_prior = choose(D, ev, y, proc); m = (ys == y) & ev['valid'][j]
        picks.append({'year': y, 'rule': j, 'n_prior': n_prior, 'n_signals': int(m.sum())})
        S.append(ev['sp'][m]); X.append(ev['ex'][j][m]); Rr.append(ev['rd'][j][m])
    return np.concatenate(S), np.concatenate(X), np.concatenate(Rr), picks


def _frame(D, d, sp, ex, rd):
    """판정에 넘기는 trades: ret = 지수 기준 수익(비용 전, 방향은 판정이 곱함), hit = 방향 × 수익 > 0."""
    return pd.DataFrame({'signal': D.td[sp], 'exit': D.td[ex], 'ret': d * rd, 'hit': (rd > 0).astype(int)})


def _safe(s):
    return re.sub(r'[^0-9A-Za-z_]', '_', str(s))


# ------------------------------------------------------------------ 대상 읽기
def load_targets(quick=False):
    """t1~t5 의 judge.json 에서 c31 == true 인 줄 → edge 큰 순 30개 → 그 줄기 cands.pkl 에서 신호 날짜. 반환 (대상 목록, notes, 넘은 후보 수)."""
    rows, notes = [], []
    for tr in SRC:
        p = os.path.join(C.SA, tr, 'out', 'judge.json')
        if not os.path.exists(p): continue
        for r in json.load(open(p, encoding='utf-8')).get('rows', []):
            if r.get('c31') is True:
                rows.append(dict(track=tr, id=str(r['id']), desc=str(r.get('desc') or r['id']), direction=int(r.get('direction') or 1),
                                 hold=int(r.get('hold') or 1), edge=float(r.get('edge') or 0.0), all_n=r.get('all_n'), all_hit=r.get('all_hit'), base=r.get('base')))
    n_all = len(rows); rows.sort(key=lambda r: (-r['edge'], r['track'], r['id']))
    if n_all > MAX_T: notes.append(f'다음 해 성적 기준을 넘은 후보 {n_all}개 가운데 아무 날과의 차이가 큰 순 {MAX_T}개만 견줌')
    rows = rows[:3 if quick else MAX_T]; cache = {}; out = []
    for r in rows:
        tr = r['track']
        if tr not in cache:
            ok = os.path.exists(os.path.join(C.SA, tr, 'out', 'cands.pkl'))
            cache[tr] = {str(c['id']): c for c in C.load_result(tr)[0]} if ok else None
        c = (cache[tr] or {}).get(r['id'])
        if c is None:
            notes.append(f"{tr.upper()} {r['id']}: 신호 날짜 파일(cands.pkl)에서 찾지 못해 건너뜀"); continue
        r['signals'] = list(pd.to_datetime(c['trades']['signal']))
        out.append(r)
    return out, notes, n_all


# ------------------------------------------------------------------ 대상 하나 → 후보·표
def build_one(D, T):
    key = f"{T['track']}_{_safe(T['id'])}"; ev = eval_target(D, T['signals'], T['direction'], T['hold']); d = ev['d']; R = ev['rules']
    if not len(ev['sp']): return None
    src = f"{T['track'].upper()} {T['id']}"; od = T['desc'][:80]; cands, ex_rows, sm_rows, pk_rows = [], [], [], []
    base = dict(target=key, track=T['track'], id=T['id'], desc=T['desc'], direction=d, hold=ev['hold'], n_signals=int(len(ev['sp'])))
    st = []
    for j, r in enumerate(R):
        k = ev['keep'][j]; s = stats(ev['rd'][j][k], ev['ex'][j][k] - ev['E'][k] + 1); st.append(s)
        ex_rows.append({**base, 'rule_no': j + 1, 'family': r['fam'], 'rule': r['rid'], 'rule_label': r['label'], **s})
    orig = N_RULES - 1; best = max(range(N_RULES), key=lambda j: (st[j]['sum_c15'], -j))
    sm_rows.append({**base, 'row': '원래 보유일(전체 기간)', 'rule': R[orig]['label'], **st[orig]})
    sm_rows.append({**base, 'row': '가장 좋은 규칙(전체 기간·결과를 보고 고름)', 'rule': R[best]['label'], **st[best]})
    names = {1: '해마다 고름 ① 그 전 비용 뒤 수익 합계 1위', 2: '해마다 고름 ② 그 전 비용 뒤 적중 1위(20건 이상)', 3: '해마다 ③ 원래 보유일 그대로(2016~)'}
    for proc in (1, 2, 3):
        sp, ex, rd, picks = wf_trades(D, ev, proc); o = np.argsort(sp, kind='stable'); sp, ex, rd = sp[o], ex[o], rd[o]
        k = thin(sp, ex, np.ones(len(sp), bool)); s = stats(rd[k], ex[k] - sp[k])
        used = sorted({R[p['rule']]['label'] for p in picks if p['n_signals']})
        sm_rows.append({**base, 'row': names[proc], 'rule': (used[0] if len(used) == 1 else f'{len(used)}가지를 바꿔 씀'), **s})
        for p in picks:
            if proc != 3: pk_rows.append({'target': key, 'proc': proc, 'year': p['year'], 'rule': R[p['rule']]['rid'], 'rule_label': R[p['rule']]['label'],
                                          'n_prior': p['n_prior'], 'n_signals': p['n_signals']})
        how = {1: f'청산 규칙을 해마다 그 전 거래의 비용 0.15% 뒤 수익 합계 1위로 고름(55가지 중, 그 전 독립 {MIN_N1}건 미만이면 원래 보유 {ev["hold"]}일)',
               2: f'청산 규칙을 해마다 그 전 거래의 비용 0.15% 뒤 적중 1위로 고름(55가지 중, 그 전 독립 {MIN_N2}건 이상인 규칙만, 없으면 원래 보유 {ev["hold"]}일)',
               3: f'원래 보유 {ev["hold"]}일째 종가 청산 그대로(바탕)'}[proc]
        cands.append(dict(id=f'x6_{key}_wf{proc}', family='청산 해마다 고르기', desc=f'[{src}] {how} — 원 신호: {od}', direction=d,
                          hold=(ev['hold'] if proc == 3 else None), kind='wf', trades=_frame(D, d, sp, ex, rd),
                          params={'source_track': T['track'], 'source_id': T['id'], 'proc': proc, 'picks': {p['year']: R[p['rule']]['rid'] for p in picks}}))
    v = ev['valid'][best]; rb = R[best]
    cands.append(dict(id=f'x6_{key}_best', family='청산 전체 기간 1위', direction=d, hold=(rb['h'] if rb['type'] in ('hold', 'orig') else None), kind='fixed',
                      desc=f"[{src}] {rb['label']} 청산 — 전체 기간 비용 0.15% 뒤 수익 합계 1위(55가지 중, 결과를 보고 고른 숫자) — 원 신호: {od}",
                      wf_of=f'x6_{key}_wf1', trades=_frame(D, d, ev['sp'][v], ev['ex'][best][v], ev['rd'][best][v]),
                      params={'source_track': T['track'], 'source_id': T['id'], 'rule': rb['rid']}))
    return dict(key=key, cands=cands, exits=ex_rows, summary=sm_rows, picks=pk_rows, info={k: T[k] for k in ('track', 'id', 'desc', 'direction', 'edge', 'all_n', 'all_hit', 'base')} | {'hold': ev['hold']})


def build(D, targets):
    out = []; skipped = []
    for T in targets:
        r = build_one(D, T)
        if r is None: skipped.append(f"{T['track'].upper()} {T['id']}: 쓸 수 있는 신호 날짜가 없어 건너뜀")
        else: out.append(r)
    return out, skipped


# ------------------------------------------------------------------ 줄기 약속
def n_parts(vol=False):
    return 1


def run_part(i, n, vol=False, quick=False):
    targets, notes, n_all = load_targets(quick)
    if not targets: return dict(results=[], notes=notes, n_all=n_all)
    res, skipped = build(C.Data(), targets)
    return dict(results=res, notes=notes + skipped, n_all=n_all)


def _p(x, n=None):
    return '–' if x is None or (n is not None and n < MIN_PCT) else f'{100 * x:.1f}%'


def _s(x):
    return '–' if x is None else f'{100 * x:+.1f}%'


def summary_md(results, notes):
    by_tr = pd.Series([r['info']['track'].upper() for r in results]).value_counts().sort_index()
    M = ['### 청산 비교 (T6)', '',
         f"- 대상: 다음 해 성적 기준을 넘은 후보 {len(results)}개(" + ', '.join(f'{k} {v}개' for k, v in by_tr.items()) + f'). 후보마다 청산 규칙 {N_RULES}가지를 견줌.',
         '- 매수는 신호 다음 거래일 시가(코스피 지수). 내림 후보는 수익 부호를 뒤집어 계산. 독립 거래는 청산일이 정해진 뒤 솎음. 수익 합계는 단순 합.',
         f'- {READ_NOTE}', f'- {OFF_NOTE}',
         "- '가장 좋은 규칙'은 전체 기간 결과를 보고 고른 숫자다. 믿을 숫자는 '해마다 고름' 줄(그 전 거래만 보고 고른 규칙의 그 해 성적, 2016~2026).",
         '- 전체 표: out/tables/exits.csv · 요약: exits_summary.csv · 해마다 고른 규칙: exits_wf_rules.csv']
    M += [f'- {s}' for s in notes] + ['']
    head = ['줄', '청산 규칙', '독립 거래', '적중', '수익 합계(비용 0)', '비용 0.15% 뒤 적중·합계', '비용 0.30% 뒤 적중·합계', '거래 평균', '최대 손실 거래', '평균 보유일']
    for r in results:
        i = r['info']
        M += [f"#### {i['track'].upper()} · {i['id']} ({'오름' if i['direction'] > 0 else '내림'}, 원래 보유 {i['hold']}일)", '', f"원 신호: {i['desc']}", '',
              '| ' + ' | '.join(head) + ' |', '|' + '---|' * len(head)]
        for s in r['summary']:
            n = s['n']
            M.append('| ' + ' | '.join([s['row'], s['rule'], str(n), _p(s['hit'], n), _s(s['sum']), f"{_p(s['hit_c15'], n)} · {_s(s['sum_c15'])}",
                                        f"{_p(s['hit_c30'], n)} · {_s(s['sum_c30'])}", ('–' if s['mean'] is None else f"{100 * s['mean']:+.2f}%"),
                                        ('–' if s['worst'] is None else f"{100 * s['worst']:+.1f}%"), ('–' if s['days'] is None else f"{s['days']:.1f}")]) + ' |')
        for proc in (1, 2):
            pk = [p for p in r['picks'] if p['proc'] == proc]
            M += ['', f"해마다 고른 규칙 {'①' if proc == 1 else '②'}: " + ' / '.join(f"{p['year']} {p['rule_label']}" for p in pk)]
        M.append('')
    return '\n'.join(M) + '\n'


def merge(parts, vol=False, quick=False):
    od = os.path.join(C.track_dir(TRACK), 'out'); os.makedirs(os.path.join(od, 'tables'), exist_ok=True)
    failed = [i + 1 for i, p in enumerate(parts) if p is None]; results = []; notes = []
    for p in parts:
        if p is not None: results += p['results']; notes += p['notes']
    N = len(results); cands = [c for r in results for c in r['cands']]; tables = []
    if N:
        pd.DataFrame([x for r in results for x in r['exits']]).to_csv(os.path.join(od, 'tables', 'exits.csv'), index=False, encoding='utf-8')
        pd.DataFrame([x for r in results for x in r['summary']]).to_csv(os.path.join(od, 'tables', 'exits_summary.csv'), index=False, encoding='utf-8')
        pd.DataFrame([x for r in results for x in r['picks']]).to_csv(os.path.join(od, 'tables', 'exits_wf_rules.csv'), index=False, encoding='utf-8')
        tables = ['exits.csv', 'exits_summary.csv', 'exits_wf_rules.csv']
        notes = [f'청산 비교 대상 {N}개 × 청산 규칙 {N_RULES}가지', READ_NOTE, OFF_NOTE] + notes
        open(os.path.join(od, 'summary.md'), 'w', encoding='utf-8').write(summary_md(results, notes[3:]))
    else:
        n_all = sum(p['n_all'] for p in parts if p is not None)
        first = ('계산 조각이 실패해 청산 비교를 하지 못함' if failed else
                 f'다음 해 성적 기준을 넘은 후보 {n_all}개의 신호 날짜를 읽지 못해 청산 비교를 하지 못함' if n_all else NONE_NOTE)
        notes = [first] + notes
        open(os.path.join(od, 'summary.md'), 'w', encoding='utf-8').write('\n'.join(notes) + '\n')
    fam = dict(zip(FAMS, (len(HOLDS) * N, (len(STOPS) * len(TAKES) - 1) * len(MAXHOLDS) * N, N, N)))
    meta = dict(n_tested=int(sum(fam.values())), families=fam, m_fixed=N_RULES * N, m_wf=3 * N, not_included=NOT_INCLUDED, parts_failed=failed, notes=notes, tables=tables,
                targets=[r['info'] for r in results])
    assert meta['n_tested'] == N_RULES * N
    return cands, meta


def main():
    a = C.parse_part(); vol = '--vol' in sys.argv        # vol 은 받되 쓰지 않는다
    if a['nparts']: print(n_parts(vol)); return
    if a['part']:
        i, n = a['part']; C.save_part(TRACK, i, n, run_part(i, n, vol, a['quick'])); print(f'{TRACK} 조각 {i}/{n} 끝'); return
    if a['merge']:
        cands, meta = merge(C.load_parts(TRACK, n_parts(vol)), vol, a['quick']); C.save_result(TRACK, cands, meta)
        print(f"{TRACK} 합침: 후보 {len(cands)}개 · 시험 {meta['n_tested']:,}가지 · " + ' / '.join(meta['notes'][:1])); return
    print(__doc__)


if __name__ == '__main__':
    main()
