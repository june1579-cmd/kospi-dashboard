# -*- coding: utf-8 -*-
"""T5 하락·인버스 — SPEC.md 의 시험 묶음 하나를 그대로 한 번 계산한다(방향은 전부 내림 −1).

조건 31개(가 신용·반대매매 8 · 나 옵션 구조 14 · 다 해외 9) × 채점 4(h3·h5·h10·t5=±5% 중 −5% 먼저)
  + 합의 신호 5개 × 4 + 해마다 고르는 절차 B 2개 × 4.  n_tested 152 · m_fixed 124 · m_wf 28.
자리(순위)는 그날까지 지난 250거래일(값 120일 이상) rolling — 전체 기간 분위는 쓰지 않는다.
명령: python run.py --nparts | --part 1/1 | --merge   (+ --quick 시험용). vol 인자는 받되 무시(t5 는 변동폭 맞춤판 없음).
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sa_common as C  # noqa: E402

TRACK = 't5'
DIRN = -1
WIN, MINP, TOP = 250, 120, 0.9
SCORES = ['h3', 'h5', 'h10', 't5']
SC_KO = {'h3': '3일째 종가에 되삼', 'h5': '5일째 종가에 되삼', 'h10': '10일째 종가에 되삼',
         't5': '보유일 없이 시가 기준 −5% 에 먼저 닿으면 맞음(+5% 먼저면 틀림)'}
SC_SHORT = {'h3': '3일', 'h5': '5일', 'h10': '10일', 't5': '−5% 먼저'}
SEL_EDGE, SEL_N = 0.10, 20                      # 절차 B: 아무 날 + 10%p 이상 · 독립 20건 이상
GROUPS = {'ga': '가_신용반대매매_단독', 'na': '나_옵션구조_단독', 'da': '다_해외_단독'}
G_KO = {'ga': '신용·반대매매', 'na': '옵션 구조', 'da': '해외'}

# (id, 갈래, 꼴, 열, 쉬운 말)  꼴: hi=자리 상위 10% · lo=하위 10% · d5hi/d5lo=5일 차의 자리 · neg=0 미만 · ge2=2 이상 · pbrk/cback=사건(첫날)
CONDS = [
    ('a1', 'ga', 'hi', 'C_반대매매_억', '반대매매 금액 상위 10%'),
    ('a2', 'ga', 'hi', 'C_반대매매_5d평균', '반대매매 5일 평균 상위 10%'),
    ('a3', 'ga', 'hi', 'C_반대매매비중%', '반대매매 비중 상위 10%'),
    ('a4', 'ga', 'hi', 'C_신용잔고_20d%', '신용잔고 20일 증가율 상위 10%'),
    ('a5', 'ga', 'hi', 'C_신용/예탁금%', '신용/예탁금 비율 상위 10%'),
    ('a6', 'ga', 'hi', 'C_신용_1년고점대비%', '신용잔고 1년 고점 근처(상위 10%)'),
    ('a7', 'ga', 'hi', 'C_미수금_5d%', '미수금 5일 증가율 상위 10%'),
    ('a8', 'ga', 'hi', 'C_예탁금_20d%', '예탁금 20일 증가율 상위 10%'),
    ('b1', 'na', 'pbrk', 'Q', '분기물 풋벽·풋 무게중심 아래로 내려간 첫날'),
    ('b2', 'na', 'pbrk', 'F0', '근월물 풋벽·풋 무게중심 아래로 내려간 첫날'),
    ('b3', 'na', 'cback', 'Q', '분기물 넘어선 콜벽 아래로 되돌아온 첫날'),
    ('b4', 'na', 'cback', 'F0', '근월물 넘어선 콜벽 아래로 되돌아온 첫날'),
    ('b5', 'na', 'ge2', 'OW_Q_wall_mig_dn5', '분기물 콜벽이 5일 중 2일 이상 아래로 옮김'),
    ('b6', 'na', 'ge2', 'OW_F0_wall_mig_dn5', '근월물 콜벽이 5일 중 2일 이상 아래로 옮김'),
    ('b7', 'na', 'd5hi', 'E1_풋콜미결제비', '풋/콜 미결제 비 5일 변화 상위 10%'),
    ('b8', 'na', 'd5lo', 'OW_ALL_cp_all', '전체 결제월 콜÷풋 미결제 비 5일 변화 하위 10%(풋 급증)'),
    ('b9', 'na', 'neg', 'G1_감마부호', '감마 부호 음'),
    ('b10', 'na', 'lo', 'G1_감마노출_z', '감마 노출 z 하위 10%'),
    ('b11', 'na', 'hi', 'V2_스큐_풋95-콜105', '스큐(풋95−콜105) 상위 10%'),
    ('b12', 'na', 'hi', 'V2_풋-콜IV', '풋−콜 IV 상위 10%'),
    ('b13', 'na', 'hi', 'R1_PCR_z', '풋/콜 거래량 비 z 상위 10%'),
    ('b14', 'na', 'hi', 'V1_IV_5d변화', '대표 IV 5일 상승 상위 10%'),
    ('c1', 'da', 'hi', 'US_vix_ts', 'VIX 기간구조(VIX÷3개월) 상위 10%(뒤집힘 쪽)'),
    ('c2', 'da', 'hi', 'US_vix_c5', 'VIX 5일 변화 상위 10%'),
    ('c3', 'da', 'lo', 'US_hyg_r5', '하이일드 채권 5일 등락 하위 10%'),
    ('c4', 'da', 'lo', 'US_es_dd60', 'S&P 선물 60일 고점 대비 하위 10%'),
    ('c5', 'da', 'lo', 'US_sox_r5', '반도체 지수 5일 등락 하위 10%'),
    ('c6', 'da', 'hi', 'US_krw_r5', '원달러 5일 등락 상위 10%(원화 약세)'),
    ('c7', 'da', 'lo', 'US_ewy_gap', 'EWY − 코스피200 괴리 하위 10%'),
    ('c8', 'da', 'hi', 'W_VIX_수준z', 'VIX 수준 z 상위 10%'),
    ('c9', 'da', 'hi', 'US_vk_vix', 'VKOSPI − VIX 상위 10%'),
]
QUICK_IDS = ['a1', 'a5', 'a6', 'b1', 'b4', 'b5', 'b7', 'b8', 'b9', 'b10', 'c1', 'c7', 'c9']
CONS = [('ga2', '신용·반대매매 조건 중 2개 이상 켜짐'), ('na2', '옵션 구조 조건 중 2개 이상 켜짐'), ('da2', '해외 조건 중 2개 이상 켜짐'),
        ('any2', '세 갈래(신용·옵션·해외) 중 둘 이상에서 조건이 하나 이상 켜짐'), ('all3', '세 갈래 모두에서 조건이 하나 이상 켜짐')]
NOT_INCLUDED = [
    '장세 겹침(하락 추세·조정 중·급등 뒤·신고가 근처에서만 신호)',
    '밤사이 미국 급등 뒤 다음 날 되밀림(갈래 D 관찰 등급, 1일 보유 — 이 묶음 보유일 밖)',
    '꼭지 전 공통점으로 남았던 옵션·해외 지표(콜벽 비중 상위·원월 콜벽 5일 위로 이동·외가격 콜 미결제 하위·EWY 등락 상위)',
    '외국인 선물·현물 동시 대량 순매도 같은 수급 조건',
    '문턱 바꾸기(상·하위 5%·20%), 순위 창 3년, 하루 늦춤',
    '조건 둘씩 짝(AND) 조합·확률 모형',
    'VVIX·SKEW(고정 자료에서 값이 깨져 있어 확인 불가)',
    '변동폭 맞춤판(±kσ 닿기)·±3% 닿기',
    '실제 인버스 ETF 시세 기준 수익·청산 규칙(여기는 코스피 지수 기준)',
]


def n_parts(vol=False):
    return 1


# ------------------------------------------------------------------ 조건
def rank_hi(s):
    """그날까지 지난 250거래일(값 120일 이상) 가운데 오늘 값 이하인 날의 비율(오늘 포함, 같은 값은 위쪽)."""
    return s.rolling(WIN, min_periods=MINP).rank(method='max', pct=True)


def build_conds(D, ids):
    X = D.X; n = D.n
    S = D.walls.drop_duplicates('date').set_index('date')['S'].astype(float).reindex(D.td)      # 코스피200 종가
    M = {}
    for cid, grp, kind, col, _ in CONDS:
        if cid not in ids: continue
        if kind == 'hi': m = rank_hi(X[col]) >= TOP
        elif kind == 'lo': m = rank_hi(-X[col]) >= TOP
        elif kind == 'd5hi': m = rank_hi(X[col].diff(5)) >= TOP
        elif kind == 'd5lo': m = rank_hi(-X[col].diff(5)) >= TOP
        elif kind == 'neg': m = X[col] < 0
        elif kind == 'ge2': m = X[col] >= 2
        elif kind in ('pbrk', 'cback'):
            same = X[f'OW_{col}_dte'].diff() < 0                                               # 같은 결제월(만기까지 날 수가 줄어든 날)
            lv = lambda c: (S * (1 + X[f'OW_{col}_{c}'] / 100)).shift(1)                        # 어제의 행사가(무게중심) 수준
            ev = ((S < lv('pwall_dist%')) | (S < lv('pcent_dist%'))) if kind == 'pbrk' else (S < lv('passed_wall_dist%'))
            m = pd.Series(D.first_only((ev & same).fillna(False).values, 5), index=D.td)
        else: raise ValueError(kind)
        M[cid] = np.asarray(m.fillna(False).values, dtype=bool)
        assert len(M[cid]) == n
    return M


def build_cons(M):
    cnt = {g: np.sum([M[c[0]] for c in CONDS if c[0] in M and c[1] == g], axis=0) for g in GROUPS}
    on = sum((cnt[g] >= 1).astype(int) for g in GROUPS)
    return {'ga2': cnt['ga'] >= 2, 'na2': cnt['na'] >= 2, 'da2': cnt['da'] >= 2, 'any2': on >= 2, 'all3': on >= 3}


# ------------------------------------------------------------------ 채점
def outcomes(D, scores):
    """채점마다 hit(내림 맞음 1/0, 못 재면 nan)·ex(청산 위치)·ret(지수 수익률)."""
    n = D.n; i = np.arange(n); O = {}
    for sc in scores:
        if sc.startswith('h'):
            h = int(sc[1:]); r = D.fwd(h); ok = np.isfinite(r)
            O[sc] = {'hit': np.where(ok, (r < 0).astype(float), np.nan), 'ex': np.where(ok, i + h, -1), 'ret': r, 'hold': h}
        else:
            y, ex = C.first_touch(D, 0.05); ok = np.isfinite(y); r = np.full(n, np.nan)
            r[ok] = D.c[ex[ok]] / D.o[i[ok] + 1] - 1
            O[sc] = {'hit': np.where(ok, (y == 0).astype(float), np.nan), 'ex': np.where(ok, ex, -1), 'ret': r, 'hold': None}
    return O


def thin(pos, ex):
    """겹치지 않는 거래만(앞 거래 청산일 이후의 신호부터) — C.independent 와 같은 규칙."""
    keep = []; last = -1
    for p in pos:
        if p >= last: keep.append(p); last = ex[p]
    return np.asarray(keep, dtype=int)


def stat(D, mask, o, sel):
    """sel(쓸 수 있는 날) 안에서 mask 신호의 독립 거래 성적과 같은 해 구성의 아무 날 내림 적중."""
    ok = sel & np.isfinite(o['hit']); pos = np.where(mask & ok)[0]; kp = thin(pos, o['ex'])
    n = len(kp); k = int(o['hit'][kp].sum()) if n else 0
    base = None
    if n:
        yk = D.year[kp]; num = 0.0
        for y in np.unique(yk):
            a = ok & (D.year == y); num += (yk == y).sum() * float(o['hit'][a].mean())
        base = num / n
    return {'sig': int(len(pos)), 'n': n, 'k': k, 'hit': (k / n if n else None), 'base': base,
            'mean': (float(-o['ret'][kp].mean()) if n else None)}


def trades(D, mask, o, sel):
    pos = np.where(mask & sel & np.isfinite(o['hit']))[0]
    t = pd.DataFrame({'signal': D.td[pos], 'exit': D.td[o['ex'][pos]]})
    if o['hold'] is None: t['hit'] = o['hit'][pos].astype(int)
    return t


def exit_before(D, o, cut):
    """청산일이 cut 날짜 전인 날."""
    ex = o['ex']; out = np.zeros(D.n, dtype=bool); ok = ex >= 0
    out[ok] = D.td.values[ex[ok]] < np.datetime64(cut)
    return out


# ------------------------------------------------------------------ 조각(1개)
def run_part(i, n, vol=False, quick=False):
    D = C.Data()
    ids = QUICK_IDS if quick else [c[0] for c in CONDS]
    scores = ['h5', 't5'] if quick else SCORES
    info = {c[0]: c for c in CONDS}
    M = build_conds(D, ids); G = build_cons(M); O = outcomes(D, scores)
    since = np.asarray(D.td >= C.START); wfm = np.isin(D.year, C.WF_YEARS)
    desc_c = lambda cid, sc: f"[{G_KO[info[cid][1]]}] {info[cid][4]} → 다음 날 시가에 팔고 {SC_KO[sc]}(내림)"
    cands = []; rows = []; big = []; wfr = []
    # --- 조건 단독·합의: 전체 기간 표 + 큰 변동 해
    sigs = [(cid, GROUPS[info[cid][1]], info[cid][4], M[cid]) for cid in ids] + [(g, '합의_고정', d, G[g]) for g, d in CONS]
    for sid, fam, d, m in sigs:
        first = D.td[np.where(m & since)[0][0]].date() if (m & since).any() else None
        for sc in scores:
            s = stat(D, m, O[sc], since)
            rows.append({'id': sid, 'family': fam, 'desc': d, 'score': sc, 'first_on': first, **s,
                         'edge': (s['hit'] - s['base'] if s['n'] else None)})
            tot = {'n': 0, 'k': 0, 'b': 0.0}
            for y in C.BIG_YEARS:
                b = stat(D, m, O[sc], since & (D.year == y))
                big.append({'id': sid, 'family': fam, 'desc': d, 'score': sc, 'year': str(y), 'n': b['n'], 'k': b['k'], 'hit': b['hit'], 'base': b['base']})
                tot['n'] += b['n']; tot['k'] += b['k']; tot['b'] += (b['base'] or 0) * b['n']
            big.append({'id': sid, 'family': fam, 'desc': d, 'score': sc, 'year': '셋 합', 'n': tot['n'], 'k': tot['k'],
                        'hit': (tot['k'] / tot['n'] if tot['n'] else None), 'base': (tot['b'] / tot['n'] if tot['n'] else None)})
    # --- 절차 C: 조건 단독 h5 를 고정 규칙 후보로
    for cid in ids:
        cands.append({'id': f'C_{cid}_h5', 'family': GROUPS[info[cid][1]], 'desc': desc_c(cid, 'h5'), 'direction': DIRN, 'hold': 5, 'kind': 'fixed',
                      'trades': trades(D, M[cid], O['h5'], since), 'params': {'cond': cid, 'score': 'h5'}})
    # --- 절차 A: 합의 신호(고르지 않음) 2016~2026
    for g, d in CONS:
        for sc in scores:
            cands.append({'id': f'A_{g}_{sc}', 'family': '합의_고정', 'desc': f"[합의] {d} → 다음 날 시가에 팔고 {SC_KO[sc]}(내림)", 'direction': DIRN,
                          'hold': O[sc]['hold'], 'kind': 'wf', 'trades': trades(D, G[g], O[sc], wfm), 'params': {'cons': g, 'score': sc}})
            wfr.append({'id': f'A_{g}', 'family': '합의_고정', 'desc': f'[합의] {d}', 'score': sc, **stat(D, G[g], O[sc], wfm)})
    # --- 절차 B: 해마다 그 전 자료로 조건 고르기
    sel_rows = []
    for sc in scores:
        o = O[sc]; b1 = np.zeros(D.n, dtype=bool); b2 = np.zeros(D.n, dtype=bool)
        for y, _ in C.wf_splits():
            tr = since & exit_before(D, o, pd.Timestamp(f'{y}-01-01')) & np.isfinite(o['hit'])
            base = float(o['hit'][tr].mean()) if tr.any() else np.nan
            picked = []
            for cid in ids:
                kp = thin(np.where(M[cid] & tr)[0], o['ex'])
                if len(kp) >= SEL_N and float(o['hit'][kp].mean()) >= base + SEL_EDGE - 1e-12: picked.append(cid)
            cnt = np.sum([M[c] for c in picked], axis=0) if picked else np.zeros(D.n, dtype=int)
            iny = D.year == y
            b1 |= iny & (cnt >= 1); b2 |= iny & (cnt >= 2)
            sel_rows.append({'year': y, 'score': sc, 'train_base': base, 'n_picked': len(picked), 'picked': ' '.join(picked),
                             'picked_desc': ' / '.join(info[c][4] for c in picked)})
        for tag, m, d in (('any1', b1, '하나라도 켜진 날'), ('any2', b2, '2개 이상 켜진 날')):
            cands.append({'id': f'B_{tag}_{sc}', 'family': '해마다고름_B',
                          'desc': f"[해마다 고름] 그 전 자료에서 내림 적중이 아무 날보다 10%p 이상 높던(독립 20건 이상) 조건 가운데 {d} → 다음 날 시가에 팔고 {SC_KO[sc]}(내림)",
                          'direction': DIRN, 'hold': o['hold'], 'kind': 'wf', 'trades': trades(D, m, o, wfm), 'params': {'proc': tag, 'score': sc}})
            wfr.append({'id': f'B_{tag}', 'family': '해마다고름_B', 'desc': f'[해마다 고름] 고른 조건 중 {d}', 'score': sc, **stat(D, m, o, wfm)})
    # 보유일 없는 채점(hit 칸) 후보: 판정이 '같은 해 아무 날'·가짜 신호를 같은 채점 방식으로 재도록 base_y(그 날이 신호일이었다면 −5% 먼저였나, 내림 기준)를 같이 넘긴다
    for c in cands:
        if 'hit' in c['trades']: c['base_y'] = O[c['params']['score']]['hit'].astype(np.float32)
    return {'cands': cands, 'ids': ids, 'scores': scores, 'cond_full': pd.DataFrame(rows), 'big_years': pd.DataFrame(big), 'wf_selected': pd.DataFrame(sel_rows),
            'wf_base': pd.DataFrame(wfr)}


# ------------------------------------------------------------------ 합치기·표
def _cell(n, k, base):
    if not n: return '0건'
    if n < 10: return f'{n}건 중 {k}'
    return f'{n}건 {100 * k / n:.0f}% ({100 * base:.0f}%)'


def _wide(df, scores, where=None):
    d = df if where is None else df[where]
    out = ['| 신호 | ' + ' | '.join(SC_SHORT[s] for s in scores) + ' |', '|---|' + '---|' * len(scores)]
    for sid, g in d.groupby('id', sort=False):
        r = {x['score']: x for _, x in g.iterrows()}
        out.append(f"| {g['desc'].iloc[0]} | " + ' | '.join(_cell(int(r[s]['n']), int(r[s]['k']), r[s]['base']) if s in r else '–' for s in scores) + ' |')
    return out


def write_tables(P, quick):
    od = os.path.join(C.track_dir(TRACK), 'out'); td = os.path.join(od, 'tables'); os.makedirs(td, exist_ok=True)
    names = []
    for nm in ('cond_full', 'wf_selected', 'big_years', 'wf_base'):
        P[nm].to_csv(os.path.join(td, nm + '.csv'), index=False, encoding='utf-8'); names.append(nm + '.csv')
    sc = P['scores']; cf = P['cond_full']; by = P['big_years']; ws = P['wf_selected']
    S = ['### T5 하락·인버스 — 따로 낸 표' + (' (quick 시험 — 조건·채점 일부)' if quick else ''), '',
         '칸 읽는 법: `독립 거래 수 · 내림 적중 (같은 해 구성의 아무 날 내림 적중)`. 거래 10건 미만은 %를 적지 않는다. 전부 과거 자료 성적이고, 조건 단독 표는 결과를 보고 고르는 숫자다(다음 해 성적 아님).', '',
         '#### 가. 조건 단독 — 전체 기간(2010~) 내림 적중 대 아무 날', '']
    S += _wide(cf, sc, cf['family'] != '합의_고정')
    S += ['', '#### 나. 합의 신호 — 전체 기간(2010~)', ''] + _wide(cf, sc, cf['family'] == '합의_고정')
    S += ['', '#### 다. 해마다 고른 조건(절차 B: 그 전 자료에서 아무 날 + 10%p 이상 · 독립 20건 이상)', '',
          '| 해 | ' + ' | '.join(SC_SHORT[s] for s in sc) + ' |', '|---|' + '---|' * len(sc)]
    for y in C.WF_YEARS:
        g = ws[ws['year'] == y].set_index('score')
        S.append(f'| {y} | ' + ' | '.join((f"{int(g.loc[s, 'n_picked'])}개: {g.loc[s, 'picked_desc']}" if g.loc[s, 'n_picked'] else '없음') for s in sc) + ' |')
    S += ['', '#### 라. 큰 변동 해(2011·2020·2026 셋 합)', ''] + _wide(by, sc, by['year'] == '셋 합')
    for y in C.BIG_YEARS:
        S += ['', f'#### 라-{y}. 합의 신호 — {y}년만', ''] + _wide(by, sc, (by['year'] == str(y)) & (by['family'] == '합의_고정'))
    S += ['', '#### 마. 해마다 고르는 절차의 2016~2026 성적 — 같은 채점 방식의 아무 날과 견줌', '',
          '(위 판정표는 −5% 먼저 채점 후보도 "가운데 보유일의 등락"으로 아무 날을 잰다. 이 표는 −5% 먼저 채점은 −5% 먼저 닿은 아무 날 비율과 견준다.)', '']
    S += _wide(P['wf_base'], sc)
    open(os.path.join(od, 'summary.md'), 'w', encoding='utf-8').write('\n'.join(S) + '\n')
    return names


def merge(parts, vol=False, quick=False):
    failed = [i + 1 for i, p in enumerate(parts) if p is None]
    ids = QUICK_IDS if quick else [c[0] for c in CONDS]; nsc = 2 if quick else len(SCORES)
    grp = {c[0]: c[1] for c in CONDS}
    fam = {GROUPS[g]: sum(1 for c in ids if grp[c] == g) * nsc for g in GROUPS}
    fam['합의_고정'] = len(CONS) * nsc; fam['해마다고름_B'] = 2 * nsc
    m_fixed = len(ids) * nsc; m_wf = len(CONS) * nsc + 2 * nsc
    if not quick: assert (sum(fam.values()), m_fixed, m_wf) == (152, 124, 28), 'SPEC 가짓수와 다름'
    notes = ['방향은 전부 내림(−1): 신호 다음 날 시가에 지수를 팔았다고 보고 정한 날 종가에 되사는 셈. 장세 겹침·하루 늦춤 없음.',
             '자리(순위)는 그날까지 지난 250거래일(값 120일 이상) 기준, 문턱은 상·하위 10% 하나.',
             '풋벽 이탈은 자료의 뜻에 맞게 "어제 풋벽(또는 풋 무게중심) 행사가 아래로 종가가 내려간 첫날"로 바로잡음(풋벽만으로는 17년에 14번·7번뿐).',
             'US_vvix·US_skew 는 고정 자료에서 값이 깨져 있어 뺌(확인 불가). 대신 VKOSPI−VIX 하나를 넣어 해외는 9개, 조건 합계 31개.',
             '보유일 없는 채점(−5% 먼저) 후보의 위 판정표 "같은 해 아무 날"은 판정이 가운데 보유일의 등락 부호로 잰 값이다. −5% 먼저 닿기 기준의 아무 날 적중은 아래 따로 낸 표에 있다.']
    if quick: notes.append('quick 시험: 조건 13개·채점 2개만 계산함(가짓수도 그만큼).')
    meta = {'n_tested': int(sum(fam.values())), 'families': fam, 'm_fixed': m_fixed, 'm_wf': m_wf, 'not_included': NOT_INCLUDED,
            'parts_failed': failed, 'notes': notes, 'tables': []}
    if failed: return [], meta
    P = parts[0]
    meta['tables'] = write_tables(P, quick)
    return P['cands'], meta


if __name__ == '__main__':
    a = C.parse_part()
    if a['nparts']:
        print(n_parts())
    elif a['part']:
        i, n = a['part']; C.save_part(TRACK, i, n, run_part(i, n, quick=a['quick']))
        print(f'{TRACK} 조각 {i}/{n} 끝')
    elif a['merge']:
        cands, meta = merge(C.load_parts(TRACK, n_parts()), quick=a['quick']); C.save_result(TRACK, cands, meta)
        print(f"{TRACK} 합침: 후보 {len(cands)}개 · 시험 {meta['n_tested']}가지 · 실패 조각 {meta['parts_failed']}")
    else:
        print('사용: python run.py --nparts | --part 1/1 | --merge  [--quick]')
