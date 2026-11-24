# -*- coding: utf-8 -*-
"""Signal A 2차 도우미 — .github/workflows/signal-a-stage2.yml 이 부른다(STAGE2.md 그대로).

1차 코드(sa_common·sa_judge·sa_s3·sa_pipeline)는 고치지 않고 불러 쓴다. 기준 숫자·판정은 sa_judge.py 그대로다.
1차·X1 결과(t1~t6·s3·x1·REPORT.md·signals/final_v1.json·state/status.json)는 읽기만 한다. 2차 상태는 state/stage2.json, 알림은 notify2/.

하위 명령
  plan                    준비된 줄기(wN/run.py·SPEC.md 가 있고 wN/out/done.json 이 없는 것)의 조각 목록 → {"include": [{track, part, n}, …]} 한 줄
  judge --matrix --art    조각(artifact)을 wN/out/parts 에 놓고 줄기마다 합치기 → 결과 확인(대상 0개면 실패) → 판정(sa_judge.py --no-state) 을 3번까지.
                          끝난 줄기는 원장(state/ledger.json)·log.md·state/stage2.json 에 적는다. 조각이 하나라도 실패한 줄기는 판정하지 않고 '실패'로 둔다.
  ready                   w1~w7 이 모두 끝났고 보고서가 아직이면 yes
  final [--iters N]       2차 후보 모으기 → 네 거름(REPORT 4절) → 관찰 목록과 견주기 → 아쉬운 줄기 모으기 → REPORT2.md · signals/final_v2_proposal.json · notify2/kakao_final.txt · 상태 '끝'
  fail --track --part --log   실패 기록(3번 실패 뒤): stage2.json need_claude=true + notify2/kakao_fail_<줄기>.txt
  status [--jobs …]       stage2.json 을 실제 파일 상태로 맞춘다
  kakao [--mark]          notify2/ 의 새 글만 notify2/kakao.txt 로 모은다(--mark = 보낸 뒤 '보냄'으로 적음)
시험용 환경 변수: SA2_TRACKS(기본 w1~w7).
"""
import argparse
import glob
import json
import os
import shutil
import sys
import tempfile

import numpy as np
import pandas as pd

import sa_common as C

TRACKS2 = [x.strip() for x in (os.environ.get('SA2_TRACKS') or 'w1,w2,w3,w4,w5,w6,w7').split(',') if x.strip()]
NAMES2 = {'w1': 'W1 분기물 콜벽 연구소 꼴', 'w2': 'W2 동시 새 콜벽(갈래 A 뿌리) 연구소 꼴', 'w3': "W3 T1 '안 넣은 것' 전부", 'w4': 'W4 변동성 꺾임만 따로',
          'w5': 'W5 방아쇠 두 개 겹침', 'w6': "W6 T2~T6 '안 넣은 것' 전부", 'w7': 'W7 X1 에서 남은 것', 'w8': 'W8 참고 분석(가짜 시험 보정 다시 재기)'}
ST2 = os.path.join(C.STATE, 'stage2.json')
NOTIFY2 = os.path.join(C.SA, 'notify2')
S2OUT = os.path.join(C.SA, 's2', 'out')
MIN_PCT = 10
REFS = [('① 분기물 콜벽 바로 아래 + 벽 물량 늘어남', 't1', 'WF_watch_top1_any_up', '절차'),
        ('① 분기물 콜벽 바로 아래 + 벽 물량 늘어남', 't1', 'R_Q_b15_any_up1_none_any_d1_f1_h5_up', '고정 규칙'),
        ('② 오를 확률 모형 상위 10%', 't3', 'P_h5_allev_gb_q90', '절차'),
        ('③ 바닥 전 상태 + 변동성 꺾임', 't4', 't2_V_S10_T8_h5', '절차')]
OV_FROM = pd.Timestamp('2016-01-01')
P_RAW = 0.01                                                       # 네 거름 ④: 보정 전 가짜 시험 p 1% 미만(REPORT 4절)


def now(fmt='%Y-%m-%d %H:%M'):
    return pd.Timestamp.now(tz='Asia/Seoul').strftime(fmt)


def _js(o):
    if hasattr(o, 'item'): return o.item()
    if isinstance(o, pd.Timestamp): return str(o.date())
    return str(o)


def _read(p):
    try: return json.load(open(p, encoding='utf-8'))
    except Exception: return None


def _must(p, what):
    j = _read(p)
    if j is None: raise RuntimeError(f'{what} 를 읽지 못함({os.path.relpath(p, C.SA)}) — 멈춤')
    return j


def has_code(t):
    d = os.path.join(C.SA, t)
    return os.path.exists(os.path.join(d, 'run.py')) and os.path.exists(os.path.join(d, 'SPEC.md'))


def done(t):
    return os.path.exists(os.path.join(C.SA, t, 'out', 'done.json'))


def report_done():
    return os.path.exists(os.path.join(S2OUT, 'done.json'))


# ------------------------------------------------------------------ 상태(state/stage2.json)
def read_st():
    return _read(ST2) or {'stage': '코드 준비', 'tracks': {}, 'need_claude': False, 'fail': None, 'fails': [], 'updated': ''}


def refresh(S):
    fails = [f for f in (S.get('fails') or []) if not ((f.get('track') in TRACKS2 and done(f['track'])) or (f.get('track') == 'final' and report_done()))]
    S['fails'] = fails; S['fail'] = fails[0] if fails else None; bad = {f.get('track') for f in fails}
    os.makedirs(NOTIFY2, exist_ok=True)
    for f in glob.glob(os.path.join(NOTIFY2, 'kakao_fail_*.txt')):      # 풀린 실패의 글은 지운다(뒤늦게 보내지 않게)
        if os.path.basename(f)[len('kakao_fail_'):-len('.txt')] not in bad: os.remove(f)
    S['tracks'] = {t: ('끝' if done(t) else '코드 없음' if not has_code(t) else '실패' if t in bad else '준비') for t in TRACKS2}
    S['tracks']['w8'] = '끝' if os.path.exists(os.path.join(C.SA, 'w8', 'out', 'done.json')) else ('코드 없음' if not has_code('w8') else '준비')
    S['tracks']['w9'] = '돌리지 않음(목록만 REPORT2 에)'
    if report_done(): S['stage'] = '끝'
    elif fails: S['stage'] = '실패(수리 대기)'
    elif all(done(t) for t in TRACKS2): S['stage'] = '판정 끝 — 보고서 차례'
    else: S['stage'] = '계산 중'
    S['need_claude'] = bool(fails) or any(v == '코드 없음' for k, v in S['tracks'].items() if k != 'w9')
    try: S['ledger_total'] = json.load(open(os.path.join(C.STATE, 'ledger.json'), encoding='utf-8')).get('total')
    except Exception: pass
    return S


def write_st(S):
    S['updated'] = now(); json.dump(S, open(ST2, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


def add_fail(track, part, tail):
    S = read_st(); rec = {'track': track, 'part': part, 'tail': tail, 'at': now()}
    S['fails'] = [f for f in (S.get('fails') or []) if f.get('track') != track] + [rec]
    os.makedirs(NOTIFY2, exist_ok=True)
    where = '보고서 단계' if track == 'final' else f"{track.upper()} {'합치기' if part == 'merge' else '판정' if part == 'judge' else '결과 비정상' if part == 'check' else f'조각 {part}'}"
    open(os.path.join(NOTIFY2, f'kakao_fail_{track}.txt'), 'w', encoding='utf-8').write(f'[Signal A 2차] {where} 3번 실패 — 수리 대기 ({now("%m-%d %H:%M")})\n')
    if track in TRACKS2:                                            # 아쉬운 줄기(조각이 끝내 실패해 못 본 부분) — 줄기가 끝나면 판정이 그 줄기 것을 다시 적는다
        S['wish'] = [w for w in (S.get('wish') or []) if not str(w).startswith(f'[{track.upper()}]')] + [f'[{track.upper()}] 계산이 끝내 실패해 이 줄기를 아직 못 봄({where}) — 수리 대기']
    write_st(refresh(S))


def log_line(stage, text, nums='—', verdict='—', n=None):
    lp = os.path.join(C.SA, 'log.md'); lines = open(lp, encoding='utf-8').read().rstrip('\n').split('\n')
    ns = [int(x.split('|')[1]) for x in lines if x.startswith('|') and x.split('|')[1].strip().isdigit()]
    try: total = json.load(open(os.path.join(C.STATE, 'ledger.json'), encoding='utf-8')).get('total', 0)
    except Exception: total = 0
    cell = lambda s: (str(s).replace('|', '/').replace('\n', ' ').strip() or '—')
    lines.append(f"| {max(ns) + 1 if ns else 1} | {now('%Y-%m-%d')} | {cell(stage)}(GitHub) | {cell(text)} | {cell(nums)} | {cell(verdict)} | {(f'{n:,}' if n is not None else '—')} (누적 {total:,}) |")
    open(lp, 'w', encoding='utf-8').write('\n'.join(lines) + '\n')


# ------------------------------------------------------------------ plan · judge
def cmd_plan(a):
    import sa_pipeline as P
    inc = []
    for t in TRACKS2:
        if has_code(t) and not done(t):
            n = P.n_parts(t); inc += [{'track': t, 'part': i, 'n': n} for i in range(1, n + 1)]
    print(json.dumps({'include': inc}, ensure_ascii=False)); return 0


def check_result(t):
    """합친 결과가 정상인지(STAGE2: 대상 0개·읽기 실패면 실패로). 문제 있으면 까닭 글, 없으면 ''."""
    mp = os.path.join(C.SA, t, 'out', 'meta.json'); m = _read(mp)
    if m is None: return 'meta.json 이 없음'
    if not os.path.exists(os.path.join(C.SA, t, 'out', 'cands.pkl')): return 'cands.pkl 이 없음'
    if int(m.get('n_cands') or 0) <= 0: return '후보 0개'
    if int(m.get('n_tested') or 0) <= 0: return '시험 가짓수 0'
    if m.get('parts_failed'): return f"실패 조각 {m['parts_failed']}"
    if m.get('quick') and os.environ.get('SA2_ALLOW_QUICK') != '1': return 'quick(시험용) 결과임'
    if t == 'w7':
        s = _read(os.path.join(C.SA, 'w7', 'out', 'summary.json'))
        if s is None: return 'w7/out/summary.json 이 없음'
        if int(s.get('n_checked') or 0) <= 0: return 'W7: 거름에 넣은 대상 0개'
    return ''


def cmd_judge(a):
    import sa_pipeline as P
    inc = (json.loads(a.matrix) if (a.matrix or '').strip() else {}).get('include') or []
    plan = {}
    for x in inc: plan[x['track']] = int(x['n'])
    logd = os.path.join(os.environ.get('RUNNER_TEMP') or tempfile.gettempdir(), 'sa2_log'); os.makedirs(logd, exist_ok=True)
    py = sys.executable; new = 0
    for t in sorted(plan):
        n = plan[t]; bad = P.place_parts(t, n, a.art); log = os.path.join(logd, f'{t}.log')
        if bad:
            print(f'{t}: 조각 {[i for i, _ in bad]} 실패 — 판정하지 않고 실패로 둠', flush=True); add_fail(t, bad[0][0], bad[0][1]); continue
        qk = ['--quick'] if os.environ.get('SA2_QUICK') == '1' else []      # 시험용(이 줄은 GitHub 실행에서는 쓰이지 않음)
        if not P.run_tries([py, os.path.join(C.SA, t, 'run.py'), '--merge'] + qk, log):
            add_fail(t, 'merge', P.tail_of(log)); continue
        why = check_result(t)
        if why:
            print(f'{t}: 결과 비정상({why}) — 실패로 둠', flush=True); add_fail(t, 'check', why); continue
        if not P.run_tries([py, os.path.join(C.SA, 'sa_judge.py'), '--track', t, '--no-state'] + (['--iters', '50'] if qk else []), log, check=lambda: done(t)):
            add_fail(t, 'judge', P.tail_of(log)); continue
        kk = os.path.join(C.SA, 'notify', f'kakao_{t}.txt')      # 판정이 만든 줄기별 글은 2차에서는 보내지 않는다(전부 끝났을 때 1통만)
        if os.path.exists(kk): os.remove(kk)
        jd = _must(os.path.join(C.SA, t, 'out', 'judge.json'), f'{t} 판정'); meta = _must(os.path.join(C.SA, t, 'out', 'meta.json'), f'{t} meta'); s = jd['summary']
        fam = {k: int(v) for k, v in (meta.get('families') or {'전체': meta.get('n_tested', 0)}).items()}
        C.ledger_add(t, fam, note=f"2차 · 통과 {s['pass']}·관찰 {s['watch']}·다음 해 {s['c31']}·최종 {s['final']}")
        b = best_wf(jd['rows']); core = (f"다음 해 최고 {C.pct(b['all_hit'])}(아무 날 {C.pct(b['base'])}, {b['all_n']}거래)" if b else '다음 해 성적 낼 절차 없음')
        log_line(f'{t.upper()} 판정', f'{NAMES2.get(t, t)} 계산·판정 끝', core, f"통과 {s['pass']}·관찰 {s['watch']}·다음 해 {s['c31']}·최종 {s['final']}", int(meta.get('n_tested') or 0))
        S = read_st(); S['fails'] = [f for f in (S.get('fails') or []) if f.get('track') != t]
        S['wish'] = [w for w in (S.get('wish') or []) if not str(w).startswith(f'[{t.upper()}]')] + list(jd.get('wish') or [])      # 2차에서 새로 생긴 아쉬운 줄기(자동으로 다시 돌리지 않음)
        write_st(refresh(S)); new += 1
        print(f'{t}: 합치기·판정 끝 — {core}', flush=True)
    write_st(refresh(read_st())); P.gh_out(done=new)
    return 0


def best_wf(rows, nmin=30):
    wf = [r for r in rows if r.get('kind') == 'wf' and (r.get('all_n') or 0) >= MIN_PCT and r.get('edge') is not None]
    big = [r for r in wf if r['all_n'] >= nmin]
    return max(big or wf, key=lambda r: r['edge']) if wf else None


def cmd_ready(a):
    print('yes' if (all(done(t) for t in TRACKS2) and not report_done()) else 'no'); return 0


def cmd_fail(a):
    import sa_pipeline as P
    add_fail(a.track, (int(a.part) if str(a.part).isdigit() else a.part), P.tail_of(a.log) if a.log else ''); print(f'실패 기록: {a.track} {a.part}'); return 0


def cmd_status(a):
    S = read_st()
    if a.jobs:
        res = dict(x.split('=', 1) for x in a.jobs.split(',') if '=' in x)
        badj = [j for j in ('plan', 'judge', 'final') if res.get(j) == 'failure']
        S['fails'] = [f for f in (S.get('fails') or []) if f.get('track') != 'pipeline']
        if badj and not S['fails']:
            S['fails'].append({'track': 'pipeline', 'part': '·'.join(badj), 'tail': 'GitHub 작업 자체가 실패함 — Actions 실행 기록의 그 작업 로그를 볼 것', 'at': now()})
    S = refresh(S)
    if any(f.get('track') == 'pipeline' for f in S['fails']): S['need_claude'] = True; S['stage'] = '실패(수리 대기)'
    write_st(S); print(f"상태: stage={S['stage']} tracks={S['tracks']} need_claude={S['need_claude']}"); return 0


def cmd_kakao(a):
    import sa_pipeline as P
    os.makedirs(NOTIFY2, exist_ok=True); P.NOTIFY = NOTIFY2          # 같은 방식, 폴더만 notify2 (1차 알림 기록은 건드리지 않음)
    return P.cmd_kakao(a)


# ------------------------------------------------------------------ final: 후보 모으기 → 네 거름 → 견주기 → 보고서
def grade_of(r):
    if r.get('final'): return 1
    if r.get('c31'): return 2
    if r.get('goal_pass'): return 3
    if r.get('watch_pass'): return 4
    return 0


def held16(D, S3, t):
    m = S3.held_mask(D, t); m[D.td < OV_FROM] = False
    return m


def ov_label(same_dir, oa, ob):
    if not same_dir: return '방향이 달라 견줄 수 없음'
    if min(oa, ob) >= 0.8: return '사실상 같은 신호'
    if max(oa, ob) >= 0.8: return '한쪽이 다른 쪽에 포함'
    if max(oa, ob) >= 0.5: return '많이 겹침'
    return '다른 신호'


def gather2(D, S3):
    """2차 후보 = w1~w7 판정에서 최종 후보·다음 해 기준·통과 숫자·관찰 가운데 하나라도 채운 줄(S3 1절과 같은 규칙, 상한 없음)."""
    info = {}; cands = []
    for tk in TRACKS2:
        jd = _must(os.path.join(C.SA, tk, 'out', 'judge.json'), f'{tk} 판정'); meta = _must(os.path.join(C.SA, tk, 'out', 'meta.json'), f'{tk} meta')
        rows = jd.get('rows') or []; info[tk] = {'judge': jd, 'meta': meta}
        picked = [r for r in rows if grade_of(r)]
        if not picked: continue
        cs, _m = C.load_result(tk); by = {c['id']: c for c in cs}; jby = {r['id']: r for r in rows}
        for r in picked:
            c = by.get(r['id'])
            if c is None or c.get('trades') is None or not len(c['trades']): raise RuntimeError(f"{tk}:{r['id']} 의 거래일이 cands.pkl 에 없음 — 멈춤")
            d = int(r.get('direction') or c.get('direction') or 1); raw = c['trades']
            w = jby.get(r.get('wf_of') or '') if r.get('kind') != 'wf' else None
            cands.append({'key': f"{tk}:{r['id']}", 'track': tk, 'id': r['id'], 'grade': grade_of(r), 'row': r, 'wf_row': w, 'd': d, 'h': int(r.get('hold') or 1), 'hold_fixed': bool(c.get('hold')),
                          'has_hit': 'hit' in raw, 'has_ret': 'ret' in raw, 'tr': S3.enrich(raw, d, D.K),
                          'by': (C.base_arr(D, c.get('base_y')) if ('hit' in raw and c.get('base_y') is not None) else None),
                          'family': c.get('family'), 'params': c.get('params'), 'root': c.get('root')})
    cands.sort(key=lambda c: (c['grade'], -(c['row'].get('edge') if c['row'].get('edge') is not None else -9), -(c['row'].get('all_n') or 0), c['key']))
    return cands, info


def load_refs(D, S3):
    out = []
    for name, tk, rid, kind in REFS:
        jd = _must(os.path.join(C.SA, tk, 'out', 'judge.json'), f'1차 {tk} 판정'); r = next((x for x in jd['rows'] if x['id'] == rid), None)
        cs, _m = C.load_result(tk); c = next((x for x in cs if x['id'] == rid), None)
        if r is None or c is None: raise RuntimeError(f'관찰 목록의 기준 신호 {tk}:{rid} 를 1차 결과에서 못 찾음 — 멈춤')
        d = int(r['direction']); t0 = C.score(S3.enrich(c['trades'], d, D.K), d, D.K)['t']
        out.append({'name': name, 'key': f'{tk}:{rid}', 'kind': kind, 'd': d, 'row': r, 'held': held16(D, S3, t0), 'n16': int((pd.DatetimeIndex(t0['signal']) >= OV_FROM).sum())})
    return out


def _p(x, n=None):
    if x is None or (n is not None and (n or 0) < MIN_PCT): return '–'
    return C.pct(x)


def _pp(x, n=None):
    if x is None or (n is not None and (n or 0) < MIN_PCT): return '–'
    return f'{100 * x:+.1f}%p'


def _pv(x):
    return '–' if x is None else (f'{x:.5f}' if x < 0.001 else f'{x:.3f}')


def _sum(x):
    return '–' if x is None else f'{100 * x:+.1f}%'


def _cut(s, n=110):
    s = str(s or '').replace('|', '/').replace('\n', ' ')
    return s if len(s) <= n else s[:n - 1] + '…'


def table(head, rows):
    return ['| ' + ' | '.join(head) + ' |', '|' + '---|' * len(head)] + ['| ' + ' | '.join(str(v) for v in r) + ' |' for r in rows]


def w9_lists():
    """W9: 1차에서 거래 수가 모자라 판정하지 못한 것(sa_judge.wishes 와 같은 규칙) — 돌리지 않고 목록만."""
    import sa_judge as J
    short = []; nobig = []
    for tk in ('t1', 't2', 't3', 't4', 't5'):
        jd = _must(os.path.join(C.SA, tk, 'out', 'judge.json'), f'1차 {tk} 판정')
        for r in jd['rows']:
            if r.get('kind') != 'wf': continue
            if r.get('edge') is not None and r['edge'] >= J.C31['edge'] and J.MIN_PCT <= (r.get('all_n') or 0) < J.C31['n']: short.append((tk, r))
            if r.get('c31') and r.get('c33_big') is None: nobig.append((tk, r))
    return short, nobig


def cmd_final(a):
    import sa_judge as J
    import sa_s3 as S3
    for t in TRACKS2:
        if not done(t): raise RuntimeError(f'{t} 가 아직 끝나지 않음 — 보고서를 만들지 않음')
        why = check_result(t)
        if why: raise RuntimeError(f'{t} 결과 비정상({why}) — 보고서를 만들지 않음(틀린 숫자가 나가지 않게)')
    W8 = _must(os.path.join(C.SA, 'w8', 'out', 'summary.json'), 'W8 요약')
    if W8.get('quick') and os.environ.get('SA2_ALLOW_QUICK') != '1': raise RuntimeError('W8 결과가 quick(시험용)임 — 멈춤')
    w8md = open(os.path.join(C.SA, 'w8', 'out', 'summary.md'), encoding='utf-8').read()
    W7 = _must(os.path.join(C.SA, 'w7', 'out', 'summary.json'), 'W7 요약') if 'w7' in TRACKS2 else None
    os.makedirs(S2OUT, exist_ok=True); D = C.Data(); B = S3.Base(D); t_now = now()
    cands, info = gather2(D, S3); refs = load_refs(D, S3)
    w8t = {}
    try:
        for _, r in pd.read_csv(os.path.join(C.SA, 'w8', 'out', 'procs.csv')).iterrows(): w8t[r['key']] = r
    except Exception as e:
        raise RuntimeError(f'W8 절차 표(w8/out/procs.csv)를 읽지 못함: {e!r}')

    # ---- 네 거름 + 관찰 목록과 견주기
    frows = []; orows = []
    for i, c in enumerate(cands):
        c['no'] = i + 1; c['t0'] = C.score(c['tr'], c['d'], D.K)['t']
        R, c['fz'] = S3.falsify(D, B, c, a.iters); frows += R
        r = c['row']
        c['f1'] = bool(r.get('c31')); c['f2'] = bool(r.get('c33')); c['f3'] = bool(c['fz']['n_hold'] == 8); c['f4'] = bool(c['fz'].get('p_raw') is not None and c['fz']['p_raw'] < P_RAW)
        c['pass4'] = bool(c['f1'] and c['f2'] and c['f3'] and c['f4'])
        c['held'] = held16(D, S3, c['t0']); nh = int(c['held'].sum()); best = None; rel = []
        for rf in refs:
            both = int((c['held'] & rf['held']).sum()); nr = int(rf['held'].sum()); oa = both / nh if nh else 0.0; ob = both / nr if nr else 0.0
            lab = ov_label(c['d'] == rf['d'], oa, ob); rel.append((rf, oa, ob, lab))
            orows.append({'후보': c['key'], '관찰 목록': rf['name'], '기준 신호': rf['key'], '겹침_후보기준': round(oa, 3), '겹침_관찰기준': round(ob, 3), '판정': lab})
            if best is None or max(oa, ob) > max(best[1], best[2]): best = (rf, oa, ob, lab)
        c['rel'] = rel; c['ov_best'] = best
        c['same_root'] = any(l in ('사실상 같은 신호', '한쪽이 다른 쪽에 포함', '많이 겹침') for _, _, _, l in rel)
        w = w8t.get(c['key']); c['w8'] = ({k: (None if pd.isna(w[k]) else float(w[k])) for k in ('p_rot', 'p_fam_track', 'p_fam_stage', 'p_fam_all')} if w is not None else None)
    fcols = ['후보', '등급', '시험', '갈래', '이름', '독립거래', '원래의_비율', '적중', '바탕', '차이', '수익합계', 'p', '버팀', '비고']
    pd.DataFrame(frows, columns=fcols).to_csv(os.path.join(S2OUT, 'falsify.csv'), index=False, encoding='utf-8')
    pd.DataFrame(orows).to_csv(os.path.join(S2OUT, 'overlap_watch.csv'), index=False, encoding='utf-8')
    # 네 거름을 넘은 것끼리 '사실상 같은 신호' 묶음(양쪽 겹침 0.8 이상, 같은 방향)
    P4 = [c for c in cands if c['pass4']]; par = list(range(len(P4)))

    def find(x):
        while par[x] != x: par[x] = par[par[x]]; x = par[x]
        return x
    for i in range(len(P4)):
        for j in range(i + 1, len(P4)):
            x, y = P4[i], P4[j]; both = int((x['held'] & y['held']).sum()); nx, ny = int(x['held'].sum()), int(y['held'].sum())
            if x['d'] == y['d'] and nx and ny and min(both / nx, both / ny) >= 0.8: par[find(i)] = find(j)
    num = {}
    for i, c in enumerate(P4): c['cluster'] = num.setdefault(find(i), len(num) + 1)
    P4.sort(key=lambda c: (-(c['row'].get('edge') or -9), -(c['row'].get('all_n') or 0)))
    reps = []; seen = set()
    for c in P4:
        if c['cluster'] not in seen: seen.add(c['cluster']); c['rep'] = True; reps.append(c)
        else: c['rep'] = False
    finals = [c for c in cands if c['grade'] == 1]
    new_root = [c for c in reps if not c['same_root']]

    # ---- 후보 표 저장
    keep = ('kind', 'family', 'desc', 'wf_of', 'all_n', 'all_k', 'all_hit', 'all_lb', 'all_sum', 'all_mean', 'p1_n', 'p1_hit', 'p2_n', 'p2_hit', 'base', 'edge', 'goal_pass', 'watch_pass', 'c31', 'c32', 'c33', 'c33_same', 'c33_big',
            'final', 'fake_p', 'fake_p_adj', 'fake_m', 'ex26_n', 'ex26_hit', 'ex26_base', 'y26_n', 'y26_hit', 'big_n', 'big_hit', 'big_base', 'by_year')
    out = []
    for c in cands:
        r = c['row']; b = c['ov_best']
        o = {'no': c['no'], 'key': c['key'], 'track': c['track'], 'id': c['id'], 'grade': c['grade'], 'grade_label': S3.GRADES[c['grade']], 'direction': c['d'], 'hold': c['h'], 'hold_fixed': c['hold_fixed'], 'root': c.get('root')}
        o.update({k: r.get(k) for k in keep})
        o['full_period'] = None if r.get('kind') == 'wf' else {'n': r.get('all_n'), 'hit': r.get('all_hit'), 'sum': r.get('all_sum')}
        o['next_year'] = ({'n': r.get('all_n'), 'hit': r.get('all_hit'), 'base': r.get('base'), 'edge': r.get('edge'), 'sum': r.get('all_sum')} if r.get('kind') == 'wf' else None)
        o['filters'] = {'f1_next_year': c['f1'], 'f2_2026_big': c['f2'], 'f3_falsify8': c['f3'], 'f4_p_raw_lt_1pct': c['f4'], 'pass4': c['pass4'], 'n_hold': c['fz']['n_hold'], 'p_raw': c['fz'].get('p_raw')}
        o['watch'] = {'closest': b[0]['name'] if b else None, 'ref': b[0]['key'] if b else None, 'ov_cand': round(b[1], 3) if b else None, 'ov_watch': round(b[2], 3) if b else None, 'label': b[3] if b else None, 'same_root': c['same_root']}
        o['cluster'] = c.get('cluster'); o['cluster_rep'] = c.get('rep'); o['w8_ref'] = c['w8']; o['params'] = c.get('params'); o['falsify'] = c['fz']
        o['first_signal'] = str(c['tr']['signal'].min().date()) if len(c['tr']) else None; o['last_signal'] = str(c['tr']['signal'].max().date()) if len(c['tr']) else None
        out.append(o)
    json.dump({'at': t_now, 'data_end': str(C.END.date()), 'tracks': TRACKS2, 'iters': a.iters,
               'note': 'full_period = 결과를 보고 고른 숫자, next_year = 해마다 그 전 자료로 고른 절차의 성적. 섞어 쓰지 말 것. w8_ref 는 참고 분석(기준 아님).', 'candidates': out},
              open(os.path.join(S2OUT, 'candidates.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=_js)
    pd.DataFrame([{'no': c['no'], 'key': c['key'], '등급': S3.GRADES[c['grade']], '종류': c['row'].get('kind'), '설명': c['row'].get('desc'), '뿌리': c.get('root'), '방향': c['d'], '보유일': c['h'],
                   '독립거래': c['row'].get('all_n'), '적중': c['row'].get('all_hit'), '아무날': c['row'].get('base'), '차이': c['row'].get('edge'), '수익합계': c['row'].get('all_sum'),
                   '①다음해': c['f1'], '②2026·큰변동해': c['f2'], '③반증8개': c['f3'], '반증_버틴수': c['fz']['n_hold'], '④가짜p<1%': c['f4'], '가짜p': c['fz'].get('p_raw'), '넷다': c['pass4'],
                   '보정뒤p': c['row'].get('fake_p_adj'), '곱한수': c['row'].get('fake_m'), '관찰목록_가까운것': (c['ov_best'][0]['name'] if c['ov_best'] else None), '겹침판정': (c['ov_best'][3] if c['ov_best'] else None),
                   '같은뿌리': c['same_root'], '묶음': c.get('cluster'), '묶음대표': c.get('rep'),
                   '참고_줄기묶음p': (c['w8'] or {}).get('p_fam_track'), '참고_전체묶음p': (c['w8'] or {}).get('p_fam_all')} for c in cands]).to_csv(os.path.join(S2OUT, 'pool.csv'), index=False, encoding='utf-8')

    # ---- 줄기별 요약
    L = _must(os.path.join(C.STATE, 'ledger.json'), '원장'); lt = {x['track']: x['n'] for x in L.get('trials', [])}
    for t in TRACKS2:                                                # 원장에 빠진 줄기가 있으면 가짓수가 틀리게 나간다 → 멈춤(시험용 실행만 건너뜀)
        if int(lt.get(t, -1)) != int(info[t]['meta'].get('n_tested') or 0) and os.environ.get('SA2_ALLOW_QUICK') != '1':
            raise RuntimeError(f"{t}: 원장(state/ledger.json)의 가짓수({lt.get(t)})가 줄기 결과({info[t]['meta'].get('n_tested')})와 다름 — 보고서를 만들지 않음")
    n2 = int(sum(lt.get(t, 0) for t in TRACKS2)); total = int(L.get('total') or 0); tr_rows = []; tot = {'pass': 0, 'watch': 0, 'c31': 0, 'final': 0, 'p4': 0, 'wf': 0}
    for t in TRACKS2:
        jd = info[t]['judge']; meta = info[t]['meta']; s = jd['summary']; b = best_wf(jd['rows']); p4 = sum(c['pass4'] for c in cands if c['track'] == t)
        fx = [r for r in jd['rows'] if r.get('kind') != 'wf' and (r.get('all_n') or 0) >= 35 and r.get('all_hit') is not None]; bf = max(fx, key=lambda r: (r['all_hit'], r['all_n'])) if fx else None
        for k in ('pass', 'watch', 'c31', 'final'): tot[k] += int(s[k])
        tot['p4'] += p4; tot['wf'] += int(s.get('n_wf') or 0)
        tr_rows.append([NAMES2.get(t, t), f"{int(meta.get('n_tested') or 0):,}", f"{int(s.get('n_wf') or 0):,}", s['pass'], s['watch'], s['c31'], p4, s['final'],
                        (f"{_p(b['all_hit'])} 대 아무 날 {_p(b['base'])} ({b['all_n']}거래)" if b else '–'), (f"{bf['all_n']}거래 {_p(bf['all_hit'])}" if bf else '–')])
    all_best = None
    for t in TRACKS2:
        b = best_wf(info[t]['judge']['rows'])
        if b and (b.get('all_n') or 0) >= 30 and (all_best is None or b['edge'] > all_best[1]['edge']): all_best = (t, b)
    wrow = {rf['key']: rf['row'] for rf in refs}; w_edge_max = max((rf['row'].get('edge') or 0) for rf in refs if rf['kind'] == '절차')
    better = [c for c in reps if (c['row'].get('all_n') or 0) >= 30 and (c['row'].get('edge') or 0) > w_edge_max]
    short, nobig = w9_lists()
    s2short = []; s2nobig = []
    for t in TRACKS2:
        for r in info[t]['judge']['rows']:
            if r.get('kind') != 'wf': continue
            if r.get('edge') is not None and r['edge'] >= J.C31['edge'] and J.MIN_PCT <= (r.get('all_n') or 0) < J.C31['n']: s2short.append((t, r))
            if r.get('c31') and r.get('c33_big') is None: s2nobig.append((t, r))
    now_c32 = sum(1 for t in TRACKS2 for r in info[t]['judge']['rows'] if r.get('kind') == 'wf' and r.get('c31') and r.get('c32'))
    # 2차에서 새로 생긴 아쉬운 줄기(STAGE2: 1차와 같은 다섯 경우 — sa_judge.wishes 가 줄기마다 가린 것을 그대로 모음)
    wish = []
    for t in TRACKS2:
        for w in (info[t]['judge'].get('wish') or []):
            if w not in wish: wish.append(w)
    near = None                                                     # 가장 가까웠던 것 1개: 관찰 등급(통과 아님) 가운데 전체 적중이 가장 높은 것 → 없으면 다음 해 성적은 넘었는데 거래 수가 모자란 절차 가운데 거래가 가장 많은 것
    wl = [(t, r) for t in TRACKS2 for r in info[t]['judge']['rows'] if r.get('watch_pass')]
    if wl:
        t_, r_ = max(wl, key=lambda x: (x[1].get('all_hit') or 0, x[1].get('all_n') or 0))
        near = {'track': t_, 'row': r_, 'text': f"{t_.upper()} 관찰 등급 {r_.get('all_n')}거래 {_p(r_.get('all_hit'))}(통과 85%까지 {100 * (J.GOAL['all_hit'] - (r_.get('all_hit') or 0)):.1f}%p)", 'why': '관찰 등급(결과를 보고 고른 숫자일 수 있음)'}
    elif s2short:
        t_, r_ = max(s2short, key=lambda x: x[1].get('all_n') or 0)
        near = {'track': t_, 'row': r_, 'text': f"{t_.upper()} {r_.get('all_n')}거래 {_p(r_.get('all_hit'))}(아무 날 {_p(r_.get('base'))}, 30건 필요)", 'why': '다음 해 성적은 넘었는데 거래 수 모자람'}
    f2 = [f for f in W8.get('families', []) if f.get('stage') == '2차']; f1 = [f for f in W8.get('families', []) if f.get('stage') == '1차']
    ref2_track = sum(f['n_fam_track_c3'] for f in f2); ref2_all = sum(f['n_fam_all_c3'] for f in f2); ref1_track = sum(f['n_fam_track_c3'] for f in f1); ref1_all = sum(f['n_fam_all_c3'] for f in f1)
    ref_final_like = sum(f['n_fam_track_final_like'] for f in W8.get('families', []))

    # ---- 제안 파일(관찰 목록은 바꾸지 않는다)
    def prop(c):
        r = c['row']; b = c['ov_best']
        return {'줄기': NAMES2.get(c['track'], c['track']), 'key': c['key'], '뿌리': c.get('root'), '규칙_쉬운말': r.get('desc'), '방향': '오름' if c['d'] > 0 else '내림', '보유일': c['h'], 'params': c.get('params'),
                '다음_해_성적': {'독립거래': r.get('all_n'), '적중': r.get('all_hit'), '같은_해_아무_날': r.get('base'), '차이': r.get('edge'), '수익합계': r.get('all_sum'), '앞_2016_2023': [r.get('p1_n'), r.get('p1_hit')],
                             '뒤_2024': [r.get('p2_n'), r.get('p2_hit')], '2026년': [r.get('y26_n'), r.get('y26_hit')], '큰_변동_해': [r.get('big_n'), r.get('big_hit'), r.get('big_base')]},
                '네_거름': {'①다음_해_기준': c['f1'], '②2026·큰_변동_해': c['f2'], '③반증_8개_모두': c['f3'], '④가짜_p_1%_미만': c['f4'], '가짜_p_보정_전': c['fz'].get('p_raw'), '가짜_p_보정_뒤': r.get('fake_p_adj'), '곱한_가짓수': r.get('fake_m')},
                '관찰_목록과_겹침': {'가장_가까운_것': b[0]['name'] if b else None, '겹침_후보기준': round(b[1], 3) if b else None, '겹침_관찰기준': round(b[2], 3) if b else None, '판정': b[3] if b else None},
                '같은_묶음의_다른_절차_수': sum(1 for x in P4 if x.get('cluster') == c.get('cluster')) - 1, '참고_W8': c['w8'],
                '주의': ('연구소 상위 100위 묶음은 전체 기간 결과로 뽑힌 것이라 이 다음 해 성적은 좋게 나오는 쪽으로 기운 숫자' if c['track'] == 'w7' else None)}
    main_prop = [prop(c) for c in new_root if c['track'] != 'w7']; bias_prop = [prop(c) for c in new_root if c['track'] == 'w7']
    PJ = {'이름': 'Signal A 2차 — 관찰 목록에 넣을 만한 것(제안)', '만든_때': t_now, '자료_끝': str(C.END.date()),
          '알림': '제안일 뿐이다. 관찰 목록(signals/final_v1.json)은 바꾸지 않았다. 넣을지는 사용자가 정한다. 최종 후보가 아니며, 새 자료에서 실제 신호 10건이 쌓이기 전에는 확정이라고 쓰지 않는다.',
          '고른_법': '2차 후보(w1~w7 판정에서 등급이 붙은 것) 가운데 네 거름(① 다음 해 기준 ② 2026년·큰 변동 해 ③ 반증 시험 8개 모두 버팀 ④ 보정 전 가짜 p 1% 미만)을 모두 넘고, '
                  '1차 관찰 목록 3개(기준 신호 4개)와 2016년 이후 보유 기간 겹침이 어느 쪽 기준으로도 50% 미만인 것. 서로 사실상 같은 신호(양쪽 겹침 80% 이상)는 아무 날과의 차이가 가장 큰 하나만. 규칙으로 자동 작성.',
          '최종_후보': [prop(c) for c in finals], '제안': main_prop, '참고_제안_기운_숫자': bias_prop,
          '네_거름_통과_수': len(P4), '그중_묶음_대표_수': len(reps), '그중_관찰_목록과_뿌리가_다른_수': len(new_root),
          '읽는_법': ["'다음 해 성적'은 해마다 그 전 자료로만 고른 숫자다. 전체 기간 성적과 섞어 쓰지 말 것.", '2차에서 시험을 더 한 만큼 가짓수 보정은 엄해졌다. 가짜 p 보정 뒤 값이 5% 미만이 아니면 우연이 아니라고 말할 수 없다.', '투자 권유 아님.'],
          '근거_파일': ['REPORT2.md', 's2/out/candidates.json', 's2/out/pool.csv', 's2/out/falsify.csv', 's2/out/overlap_watch.csv', 'w8/out/summary.md']}
    os.makedirs(os.path.join(C.SA, 'signals'), exist_ok=True)
    json.dump(PJ, open(os.path.join(C.SA, 'signals', 'final_v2_proposal.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=_js)

    # ---- REPORT2.md
    M = [f'# Signal A 2차 보고서 — 아쉬운 줄기 전부 ({t_now}, 자료 끝 {C.END.date()})', '',
         '> 사용자 지시(2026-11-24): "아쉬운 줄기 전부 진행해". 숫자·표·아래 문장은 **GitHub 가 계산·판정해 규칙으로 자동 작성**한 것입니다(미리 정한 목록: wN/SPEC.md, 방식: STAGE2.md).',
         '> 매매 기준: 코스피 지수, 신호 다음 날 시가 매수 → 정한 날 종가 매도, 수익 합계는 거래별 단순 합. 표본 10개 미만은 %로 적지 않습니다. 기준(CRITERIA.md)은 바꾸지 않았습니다.',
         '> 1차 보고서(REPORT.md)·관찰 목록(signals/final_v1.json)은 그대로입니다.', '']
    if finals:
        M += [f'## ★ 최종 후보 {len(finals)}개 (CRITERIA 1절 통과 숫자 + 3절 셋 모두)', '']
        M += table(['줄기', '절차·규칙', '독립 거래', '다음 해 적중', '같은 해 아무 날', '차이', '수익 합계', '가짜 p(보정 뒤)', '반증 8개'],
                   [[NAMES2.get(c['track']), _cut(c['row'].get('desc')), c['row'].get('all_n'), _p(c['row'].get('all_hit')), _p(c['row'].get('base')), _pp(c['row'].get('edge')), _sum(c['row'].get('all_sum')),
                     _pv(c['row'].get('fake_p_adj')), f"{c['fz']['n_hold']}/8"] for c in finals])
        M += ['', "새 자료에서 실제 신호 10건이 쌓이기 전에는 '확정'이라고 쓰지 않습니다(CRITERIA 4절).", '']
    M += ['## 1. 결론', '']
    k = 1

    def line(s):
        nonlocal k
        M.append(f'{k}. {s}'); k += 1
    line(f"**최종 후보는 {len(finals)}개입니다.** 2차에서 {n2:,}가지를 더 시험했고(1차·X1 포함 누적 {total:,}가지), 해마다 고르는 절차 {tot['wf']:,}개를 판정했습니다."
         + ('' if finals else ' CRITERIA.md 의 기준을 모두 넘은 것은 이번에도 없습니다.'))
    line(f"통과 숫자(독립 35건·85%)를 채운 것 {tot['pass']}개 · 관찰(80%) {tot['watch']}개 · 다음 해 기준(아무 날 +10%p·30건)을 넘은 절차 {tot['c31']}개입니다. "
         + (f"다음 해 성적이 가장 좋은 절차(독립 30건 이상)는 {NAMES2.get(all_best[0])} 의 {all_best[1]['all_n']}거래 {_p(all_best[1]['all_hit'])}(같은 해 아무 날 {_p(all_best[1]['base'])}, 차이 {_pp(all_best[1]['edge'])})입니다."
            if all_best else '다음 해 성적을 낼 만한 절차(독립 30건 이상)가 없습니다.'))
    line(f"1차 관찰 목록을 골랐던 **네 거름을 모두 넘은 것은 {len(P4)}개**(서로 사실상 같은 신호를 하나로 묶으면 {len(reps)}묶음)입니다. "
         + (f"이 가운데 1차 관찰 목록 3개와 **뿌리가 다른 것은 {len(new_root)}묶음**으로, signals/final_v2_proposal.json 에 **제안으로만** 적었습니다(넣을지는 사용자가 정합니다)." if new_root
            else '이 가운데 1차 관찰 목록 3개와 뿌리가 다른 것은 없습니다(모두 관찰 목록과 겹치는 신호) — 제안할 것이 없습니다.' if P4 else '제안할 것이 없습니다.'))
    line((f"네 거름을 넘고 독립 30건 이상이면서 아무 날과의 차이가 1차 관찰 목록의 가장 큰 값({_pp(w_edge_max)})보다 큰 것은 {len(better)}묶음입니다(4절)." if better
          else f"네 거름을 넘은 것 가운데 아무 날과의 차이가 1차 관찰 목록의 가장 큰 값({_pp(w_edge_max)})보다 큰 것(독립 30건 이상)은 없습니다 — **1차 관찰 목록보다 뚜렷이 나은 것은 나오지 않았습니다.**"))
    line(f"가짜 신호 시험(3절 2번)을 지금 방식(가짜 2,000번 × 절차 수)으로 넘은 절차는 다음 해 기준을 넘은 {tot['c31']}개 가운데 {now_c32}개입니다. "
         f"**2차에서 시험을 더 한 만큼 가짓수 보정은 엄해졌습니다**(절차 수가 100개를 넘는 줄기는 가짜 2,000번으로는 셈으로 넘을 수 없음).")
    line(f"참고 분석(W8, 기준 아님): '묶음 전체에서 가장 좋은 가짜'와 견주는 방식(가짜 {W8.get('n_iter'):,}번)으로 3절 1·2·3번을 함께 넘는 절차는 줄기 묶음 기준 1차 {ref1_track}개·2차 {ref2_track}개, "
         f"1·2차 전체 묶음 기준(가장 엄함) 1차 {ref1_all}개·2차 {ref2_all}개입니다. 그 가운데 1절 통과 숫자(35건·85%)까지 채운 것은 {ref_final_like}개입니다. **이 숫자로 최종 후보를 정하지 않습니다 — 기준을 바꿀지는 사용자가 정합니다.**")
    if W7:
        line(f"X1 에서 남은 것(W7): 확인 불가였던 후보 가운데 {W7.get('n_restored')}개를 옛 기록에서 되살렸고, 다시 매긴 상위 100위를 더해 대상 {W7.get('n_target')}개 중 {W7.get('n_checked')}개를 거름에 넣었습니다"
             f"(여전히 확인 불가 {W7.get('n_unverifiable')}개). X1 꼴 네 거름을 모두 넘은 고정 규칙 {W7.get('pass4_fixed')}개 · 절차 {W7.get('pass4_wf')}개 — 묶음 자체가 전체 기간 결과로 뽑힌 **기운 숫자**입니다(5절).")
    line(f"거래 수가 모자라 판정하지 못한 것(W9)은 고정 자료로는 풀 수 없어 돌리지 않았습니다: 1차 독립 30건 미만 {len(short)}개 · 큰 변동 해 10건 미만 {len(nobig)}개(7절). 새 자료가 쌓여야 풀립니다.")
    line(f"2차에서 새로 생긴 아쉬운 줄기는 {len(wish)}건입니다(8절)." + (f" 가장 가까웠던 것: {near['text']}." if near else '') + ' 자동으로 다시 돌리지 않았습니다 — 돌릴지는 사용자가 정합니다.')
    M += ['', '## 2. 줄기별 숫자', '']
    M += table(['줄기', '시험 가짓수', '해마다 고르는 절차', '통과 숫자(85%)', '관찰(80%)', '다음 해 기준 넘음', '네 거름 모두', '최종 후보', '**다음 해 성적**이 가장 좋은 절차(독립 30건 이상)', '전체 기간 최고 고정 규칙(**결과를 보고 고른 숫자**)'],
               tr_rows + [['**합계**', f'**{n2:,}**', f"**{tot['wf']:,}**", f"**{tot['pass']}**", f"**{tot['watch']}**", f"**{tot['c31']}**", f'**{len(P4)}**', f"**{tot['final']}**", '', '']])
    M += ['', "- '다음 해 성적' 칸과 '전체 기간' 칸은 다른 숫자입니다. 전체 기간 숫자는 결과를 보고 고른 값이라 앞으로의 기대값이 아닙니다.",
          '- W8(참고 분석)은 새 규칙을 시험하지 않아 가짓수에 넣지 않았고, W9 는 돌리지 않았습니다.',
          f'- 누적 가짓수 {total:,} = 1차 264,750 + X1 209 + 2차 {n2:,}. 줄기별 자세한 표: wN/report.md · wN/out/summary.md', '']
    M += ['## 3. 네 거름을 모두 넘은 것', '',
          '네 거름(REPORT.md 4절과 같음): ① 다음 해 기준(3절 1번) ② 2026년·큰 변동 해(3절 3번) ③ 반증 시험 8개 모두 버팀 ④ 보정 전 가짜 p 1% 미만. '
          '①은 해마다 고르는 절차만 넘을 수 있습니다(고정 규칙은 결과를 보고 고른 것). 최종 후보가 아니라 새 자료로 지켜볼 만한지 가리는 거름입니다.', '']
    if P4:
        M += table(['묶음', '줄기', '절차', '뿌리', '독립 거래', '**다음 해 적중**', '같은 해 아무 날', '차이', '수익 합계', '앞(2016~2023)·뒤(2024~)', '가짜 p(보정 전 → 뒤)', '관찰 목록과', '참고: 묶음 p(줄기/전체)'],
                   [[(f"{c['cluster']}" + (' ★' if c.get('rep') else '')), c['track'].upper(), _cut(c['row'].get('desc'), 90), _cut(c.get('root') or '–', 24), c['row'].get('all_n'), _p(c['row'].get('all_hit')), _p(c['row'].get('base')),
                     _pp(c['row'].get('edge')), _sum(c['row'].get('all_sum')), f"{c['row'].get('p1_n')}건 {_p(c['row'].get('p1_hit'), c['row'].get('p1_n'))} · {c['row'].get('p2_n')}건 {_p(c['row'].get('p2_hit'), c['row'].get('p2_n'))}",
                     f"{_pv(c['fz'].get('p_raw'))} → {_pv(c['row'].get('fake_p_adj'))}(×{int(c['row'].get('fake_m') or 1):,})", f"{c['ov_best'][3]}({c['ov_best'][0]['name'][:1]})" if c['ov_best'] else '–',
                     f"{_pv((c['w8'] or {}).get('p_fam_track'))} / {_pv((c['w8'] or {}).get('p_fam_all'))}"] for c in P4[:40]])
        M += ['', f"- ★ = 그 묶음(사실상 같은 신호)의 대표(아무 날과의 차이가 가장 큼). 전부 {len(P4)}개 중 차이 큰 순 40개까지 — 전체는 s2/out/pool.csv.",
              '- 해마다 고르는 절차는 전체 기간 고정 숫자가 따로 없습니다(해마다 다시 고름). 절차가 고른 고정 규칙의 전체 기간 숫자는 각 줄기 report.md 2절에 "결과를 보고 고른 숫자"로 따로 있습니다.',
              '- W7 의 절차는 연구소 상위 100위 묶음이 전체 기간 결과로 뽑힌 것이라 다음 해 성적도 좋게 나오는 쪽으로 기웁니다.', '']
    else:
        M += ['네 거름을 모두 넘은 것이 없습니다.', '']
    nf = {k_: sum(c[k_] for c in cands) for k_ in ('f1', 'f2', 'f3', 'f4')}
    M += [f"- 2차 후보(등급이 붙은 것) {len(cands)}개의 거름별 통과 수: ① {nf['f1']} · ② {nf['f2']} · ③ {nf['f3']} · ④ {nf['f4']} · 넷 다 {len(P4)}.", '']
    M += ['## 4. 1차 관찰 목록 3개와 견준 표', '',
          '견주는 법(X1 과 같음): 2016년 이후 독립 거래가 들고 있는 날의 겹침. 양쪽 모두 80% 이상 = 사실상 같은 신호 / 한쪽만 80% 이상 = 한쪽이 다른 쪽에 포함 / 어느 한쪽 50% 이상 = 많이 겹침 / 그 밖 = 다른 신호. '
          "'같은 뿌리' = 다른 신호가 아닌 것.", '']
    rows = []
    for name in dict.fromkeys(rf['name'] for rf in refs):
        rf = next(x for x in refs if x['name'] == name and x['kind'] == '절차'); wr = rf['row']
        rel = [c for c in P4 if any(r_[0]['name'] == name and r_[3] in ('사실상 같은 신호', '한쪽이 다른 쪽에 포함', '많이 겹침') for r_ in c['rel'])]
        bb = max(rel, key=lambda c: c['row'].get('edge') or -9) if rel else None
        bt = [c for c in rel if (c['row'].get('all_n') or 0) >= 30 and (c['row'].get('edge') or 0) > (wr.get('edge') or 0)]
        rows.append([name, f"{wr.get('all_n')}거래 {_p(wr.get('all_hit'))} (아무 날 {_p(wr.get('base'))}, 차이 {_pp(wr.get('edge'))})", len(rel),
                     (f"{bb['track'].upper()} · {_cut(bb['row'].get('desc'), 70)} — {bb['row'].get('all_n')}거래 {_p(bb['row'].get('all_hit'))} (차이 {_pp(bb['row'].get('edge'))})" if bb else '–'),
                     (f'있음 {len(bt)}개' if bt else '없음')])
    oth = [c for c in P4 if not c['same_root']]; bo = max(oth, key=lambda c: c['row'].get('edge') or -9) if oth else None
    rows.append(['(관찰 목록과 다른 뿌리)', '–', len(oth), (f"{bo['track'].upper()} · {_cut(bo['row'].get('desc'), 70)} — {bo['row'].get('all_n')}거래 {_p(bo['row'].get('all_hit'))} (차이 {_pp(bo['row'].get('edge'))})" if bo else '–'),
                 (f'제안 {len(new_root)}묶음(signals/final_v2_proposal.json)' if new_root else '제안 없음')])
    M += table(['1차 관찰 신호', '1차의 다음 해 성적', '2차에서 네 거름을 넘은 같은 뿌리 수', '그 가운데 아무 날과의 차이가 가장 큰 것', '1차보다 나은 것(차이가 더 크고 독립 30건 이상)'], rows)
    M += ['', '- 같은 뿌리에서 숫자가 더 좋게 나온 것은 같은 신호를 다시 고른 것일 수 있어, 관찰 목록의 규칙·문턱은 바꾸지 않았습니다(바꾸면 새 신호로 치고 0건부터 다시 셈 — REPORT.md 8절).',
          '- 겹침 전체는 s2/out/overlap_watch.csv.', '']
    M += ['## 5. X1 에서 남은 것 (W7)', '']
    if W7:
        d7 = W7.get('d_refit') or {}
        M += [f"- 대상 {W7.get('n_target')}개 · 거름에 넣음 {W7.get('n_checked')}개 · 옛 기록으로 되살림 {W7.get('n_restored')}개 · 여전히 확인 불가 {W7.get('n_unverifiable')}개.",
              f"- X1 꼴 네 거름(고정 규칙은 ①을 '2016~2026 거래의 숫자 꼴'로 봄 — 결과를 보고 고른 규칙의 숫자)을 모두 넘은 고정 규칙 **{W7.get('pass4_fixed')}개**, 절차 **{W7.get('pass4_wf')}개**.",
              f"- 갈래 D '갭 되밀림 1일'을 보유 1일에 맞는 반증 꼴로 다시 잰 것(참고 판정): 네 거름 모두 통과 원래 꼴 {d7.get('orig_pass4_fixed')}개 → 1일 꼴 {d7.get('refit_pass4_fixed')}개.", '']
        w7p = os.path.join(C.SA, 'w7', 'out', 'summary.md')
        if not os.path.exists(w7p): raise RuntimeError('w7/out/summary.md 가 없음 — 멈춤')
        w7l = open(w7p, encoding='utf-8').read().split('\n'); cutat = next((i for i, x in enumerate(w7l) if x.startswith('#### 갈래별 숫자')), min(len(w7l), 25))
        M += w7l[:cutat] + ['- 자세한 표와 글: w7/out/summary.md · w7/out/fixed_all.csv · w7/out/wf.csv', '']
    else:
        M += ['W7 결과 없음.', '']
    M += ['## 6. 참고 분석 — 가짜 시험 보정을 다른 방식으로 (W8, 기준은 그대로)', '', w8md, '']
    M += ['## 7. 여전히 못 푼 것', '', '### (가) 거래 수가 모자라 판정하지 못한 것 (W9 — 고정 자료로는 풀 수 없어 돌리지 않음)', '',
          f'다음 해 성적은 넘었는데 독립 거래가 30건 미만인 1차 절차 {len(short)}개:', '']
    M += table(['줄기', '절차', '독립 거래', '적중', '같은 해 아무 날'], [[tk.upper(), _cut(r.get('desc'), 120), r.get('all_n'), _p(r.get('all_hit')), _p(r.get('base'))] for tk, r in short]) if short else ['- 없음']
    M += ['', f'다음 해 기준은 넘었지만 큰 변동 해(2011·2020·2026) 독립 거래가 10건 미만이라 판정 불가인 1차 절차 {len(nobig)}개:', '']
    M += table(['줄기', '절차', '독립 거래', '적중', '큰 변동 해 거래'], [[tk.upper(), _cut(r.get('desc'), 120), r.get('all_n'), _p(r.get('all_hit')), f"{r.get('big_n')}건"] for tk, r in nobig]) if nobig else ['- 없음']
    M += ['', f'- 2차에서도 같은 까닭으로 판정하지 못한 절차: 독립 30건 미만 {len(s2short)}개 · 큰 변동 해 10건 미만 {len(s2nobig)}개(각 줄기 report.md 4절).', '- 새 자료가 쌓이면 저절로 풀립니다.', '',
          '### (나) 고정 자료에 없어 계산하지 못한 것 (확인 불가)', '']
    uns = []
    for t in TRACKS2:
        meta = info[t]['meta']
        for x in (meta.get('unsolvable') or []): uns.append(f'[{t.upper()}] {x}')
        for x in (meta.get('not_included') or []):
            if '확인 불가' in str(x): uns.append(f'[{t.upper()}] {x}')
    M += [f'- {x}' for x in dict.fromkeys(uns)] or ['- 없음']
    M += ['', '## 8. 아쉬운 줄기 (2차에서 새로 생긴 것 — 자동으로 다시 돌리지 않습니다. 돌릴지는 사용자가 정합니다)', '',
          '1차와 같은 다섯 경우를 줄기마다 자동으로 가렸습니다: 관찰은 있는데 통과 없음 / 다음 해 성적은 넘었는데 거래 수 모자람 / 2026년을 넣고 빼면 결론이 바뀜 / 조각이 끝내 실패해 못 본 부분 / SPEC 의 \'안 넣은 것\'.',
          f"모두 **{len(wish)}건**입니다." + (f" 가장 가까웠던 것: **{near['text']}** — {_cut(near['row'].get('desc'), 160)}" if near else ''), '']
    kinds = [('관찰 등급', '관찰은 있는데 통과 없음'), ('독립 거래 수가 모자람', '다음 해 성적은 넘었는데 거래 수 모자람'), ('2026년을 넣고 빼면', '2026년을 넣고 빼면 결론이 바뀜'), ('판정 불가', '큰 변동 해 거래가 모자라 판정 불가'),
             ('끝내 실패', '조각이 끝내 실패해 못 본 부분'), ('안 넣은 것', "SPEC 의 '안 넣은 것'")]
    used = set()
    for key_, title_ in kinds:
        ws = [w for w in wish if key_ in w and w not in used]; used.update(ws)
        M += [f'### {title_} — {len(ws)}건', ''] + ([f'- {_cut(w, 420)}' for w in ws] or ['- 없음']) + ['']
    rest = [w for w in wish if w not in used]
    if rest: M += ['### 그 밖', ''] + [f'- {_cut(w, 420)}' for w in rest] + ['']
    M += ['## 9. 숫자를 읽을 때', '',
          "- '전체 기간 적중'과 '다음 해 적중'은 다른 숫자입니다. 앞의 것은 결과를 보고 고른 값입니다.",
          '- 2차는 1차 결과를 본 뒤에 고른 방향들입니다(아쉬운 줄기). 그래서 시험 목록은 돌리기 전에 고정했고, 가짓수는 모두 원장에 더했습니다. 시험을 많이 할수록 우연히 좋아 보이는 것이 늘어납니다.',
          '- 선물로 잰 연구소 숫자와 코스피 지수로 잰 숫자는 5~10%p 다릅니다(NOTES.md 1절). 여기 숫자는 전부 코스피 지수 기준입니다.',
          '- 관찰 목록·제안 모두 최종 후보가 아닙니다. 새 자료에서 실제 신호 10건이 쌓이기 전에는 확정이라고 쓰지 않습니다(CRITERIA 4절).', '',
          '## 10. 근거 파일', '',
          '- 줄기별: w1~w7/SPEC.md(미리 정한 목록) · w1~w7/report.md(판정) · wN/out/summary.md · wN/out/tables/',
          '- 2차 후보·네 거름·겹침: s2/out/candidates.json · s2/out/pool.csv · s2/out/falsify.csv · s2/out/overlap_watch.csv',
          '- 제안: signals/final_v2_proposal.json / 참고 분석: w8/SPEC.md · w8/out/ / 가짓수 원장: state/ledger.json / 2차 상태: state/stage2.json', '', '투자 권유 아님', '']
    open(os.path.join(C.SA, 'REPORT2.md'), 'w', encoding='utf-8').write('\n'.join(M))

    # ---- 카카오톡 1통 · 상태 · 기록
    core = (f"다음 해 최고 {_p(all_best[1]['all_hit'])}(아무 날 {_p(all_best[1]['base'])}, {all_best[1]['all_n']}거래)" if all_best else '다음 해 성적 낼 절차 없음')
    msg = (f"[Signal A 2차] 끝. {n2:,}가지 더 시험. 최종 후보 {len(finals)} · 통과 {tot['pass']} · 관찰 {tot['watch']} · 다음 해 기준 {tot['c31']} · 네 거름 {len(P4)}(새 뿌리 제안 {len(new_root)}). {core}. "
           f"아쉬운 줄기 {len(wish)}건" + (f"(가장 가까운 것 {near['text']})" if near else '') + '. REPORT2.md')
    if len(msg) > 198:
        msg = (f"[Signal A 2차] 끝. {n2:,}가지 더 시험. 최종 후보 {len(finals)} · 통과 {tot['pass']} · 관찰 {tot['watch']} · 다음 해 기준 {tot['c31']} · 네 거름 {len(P4)}(새 뿌리 {len(new_root)}). {core}. "
               f"아쉬운 줄기 {len(wish)}건" + (f"(가까운 것 {near['track'].upper()} {near['row'].get('all_n')}거래 {_p(near['row'].get('all_hit'))})" if near else '') + '. REPORT2.md')[:198]
    os.makedirs(NOTIFY2, exist_ok=True); open(os.path.join(NOTIFY2, 'kakao_final.txt'), 'w', encoding='utf-8').write(msg + '\n')
    json.dump({'at': t_now, 'n_cands': len(cands), 'n_pass4': len(P4), 'n_reps': len(reps), 'n_new_root': len(new_root), 'n_final': len(finals), 'n_tested_stage2': n2, 'ledger_total': total, 'iters': a.iters},
              open(os.path.join(S2OUT, 'done.json'), 'w', encoding='utf-8'), ensure_ascii=False)
    log_line('2차 보고', 'REPORT2.md · signals/final_v2_proposal.json(제안만) · 네 거름 · W8 참고 분석. 관찰 목록·기준은 그대로', core,
             f"최종 후보 {len(finals)} · 네 거름 {len(P4)} · 새 뿌리 제안 {len(new_root)} · 끝", None)
    S = read_st(); S['fails'] = [f for f in (S.get('fails') or []) if f.get('track') != 'final']; S['result'] = {'final': len(finals), 'pass4': len(P4), 'new_root': len(new_root), 'n_tested': n2}
    S['wish'] = wish; S['wish_nearest'] = (near['text'] + ' — ' + str(near['row'].get('desc')) if near else None)
    write_st(refresh(S)); print(msg)
    return 0


def main():
    ap = argparse.ArgumentParser(description='Signal A 2차 도우미'); sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('plan'); p.set_defaults(f=cmd_plan)
    p = sub.add_parser('judge'); p.add_argument('--matrix', default=''); p.add_argument('--art', required=True); p.set_defaults(f=cmd_judge)
    p = sub.add_parser('ready'); p.set_defaults(f=cmd_ready)
    p = sub.add_parser('final'); p.add_argument('--iters', type=int, default=2000); p.set_defaults(f=cmd_final)
    p = sub.add_parser('fail'); p.add_argument('--track', required=True); p.add_argument('--part', default='0'); p.add_argument('--log', default=''); p.set_defaults(f=cmd_fail)
    p = sub.add_parser('status'); p.add_argument('--jobs', default=''); p.set_defaults(f=cmd_status)
    p = sub.add_parser('kakao'); p.add_argument('--mark', action='store_true'); p.set_defaults(f=cmd_kakao)
    a = ap.parse_args()
    return a.f(a)


if __name__ == '__main__':
    sys.exit(main())
