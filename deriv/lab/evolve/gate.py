"""진화 시험 판정(GitHub Actions 의 evolve-gate 가 '기준 가지의 이 파일'로 돌린다 — 바꾸려는 쪽 코드가 자기 시험을 고칠 수 없게).

python gate.py <changed_files.txt> <base_full> <head_full> <base_trunc> <head_trunc> <cut 날짜>
통과 조건
  1. 잠금 파일을 건드리지 않음(검증 A8·반증 A10·정리·공통 규칙·원장·결과·원자료·워크플로·수집 속도·이 시험 자체).
  2. 바꾼 코드로 한 라운드가 끝까지 돎: 기준에서 성공하던 단계가 실패로 바뀌지 않음, 새 에이전트는 전부 성공.
  3. 기존 에이전트의 후보 수가 기준의 80% 아래로 줄지 않음.
  4. 앞을 보는 실수 없음: 자료 끝 1년을 잘라 다시 돌려도 그 전 신호가 같아야 함. 어긋난 후보가 기준보다 3개(또는 2%) 넘게 늘면 탈락(뒤 구간에서 정하는 후보 fit_period=p2 는 빼고 봄).
"""
import fnmatch
import json
import os
import pickle
import sys

import pandas as pd

PROTECTED = ['deriv/lab/a08_validate.py', 'deriv/lab/a10_redteam.py', 'deriv/lab/lab_merge.py', 'deriv/lab/lab_common.py', 'deriv/lab/prune_rounds.py', 'deriv/lab/kakao_lab.py', 'deriv/lab/forward_stage.py', 'deriv/lab/signals/*', 'deriv/lab/criteria_agent.md', 'deriv/lab/study/proposals.md',
             'deriv/lab/evolve/*', 'deriv/lab/evolver.md', 'deriv/lab/round*.json', 'deriv/lab/state*/*', 'deriv/lab/out*/*', 'deriv/lab/notify/*',
             'deriv/data/*', 'deriv/us/data/*', 'deriv/us/out/*', 'deriv/collect.py', 'deriv/trigger.txt', 'deriv/us/trigger.txt', 'deriv/scan/trigger.txt', '.github/*', 'docs/*']
MARGIN_DAYS = 90


def protected(files):
    return sorted(f for f in files if any(fnmatch.fnmatch(f, p) or f.startswith(p.rstrip('*')) and p.endswith('*') for p in PROTECTED))


def steps(d):
    p = os.path.join(d, 'steps.json')
    return {s['step']: s for s in json.load(open(p))} if os.path.exists(p) else None


def cands(d):
    out = {}; rd = os.path.join(d, 'out_t', 'round_001')
    if not os.path.isdir(rd): return out
    for a in sorted(os.listdir(rd)):
        p = os.path.join(rd, a, 'candidates.pkl')
        if os.path.exists(p):
            try: out[a] = pickle.load(open(p, 'rb'))
            except Exception as e: out[a] = e
    return out


def leak(full, trunc, cut):
    """에이전트별 (본 후보 수, 어긋난 후보 수, 예시)."""
    lim = pd.Timestamp(cut) - pd.Timedelta(days=MARGIN_DAYS); res = {}
    for a, cf in full.items():
        ct = trunc.get(a)
        if not isinstance(cf, list) or not isinstance(ct, list): continue
        T = {c['id']: c for c in ct}; n = bad = 0; ex = []
        for c in cf:
            if c.get('fit_period') == 'p2' or c['id'] not in T: continue
            s1 = set(pd.to_datetime(c['trades']['signal'])); s2 = set(pd.to_datetime(T[c['id']]['trades']['signal']))
            s1 = {s for s in s1 if s <= lim}; s2 = {s for s in s2 if s <= lim}
            n += 1
            if s1 != s2:
                bad += 1
                if len(ex) < 3: ex.append(c['id'])
        res[a] = (n, bad, ex)
    return res


def main():
    changed = [l.strip() for l in open(sys.argv[1], encoding='utf-8') if l.strip()]
    bf, hf, bt, ht, cut = sys.argv[2:7]
    fails, notes = [], []
    pr = protected(changed)
    if pr: fails.append('잠금 파일을 건드림: ' + ', '.join(pr[:8]))
    sb, sh = steps(bf), steps(hf)
    if sh is None: fails.append('바꾼 코드의 시험 라운드 결과가 없음')
    else:
        for k, s in sh.items():
            base_ok = sb is None or k not in sb or sb[k]['rc'] == 0
            if s['rc'] != 0 and base_ok: fails.append(f'단계 {k} 실패(rc {s["rc"]}) — 기준에서는 성공')
            elif s['rc'] != 0: notes.append(f'단계 {k} 는 기준에서도 실패(rc {s["rc"]})')
        if sb:
            fixed = [k for k in sh if sh[k]['rc'] == 0 and k in sb and sb[k]['rc'] != 0]
            if fixed: notes.append('기준에서 실패하던 단계를 고침: ' + ', '.join(fixed))
            notes.append(f'시험 라운드 시간: 기준 {sum(s["sec"] for s in sb.values())}초 → 바꾼 뒤 {sum(s["sec"] for s in sh.values())}초')
    cb, ch = cands(bf), cands(hf)
    for a, c in ch.items():
        if not isinstance(c, list): fails.append(f'{a} 후보 파일을 읽지 못함'); continue
        nb = len(cb[a]) if isinstance(cb.get(a), list) else None
        if nb is None: notes.append(f'새 후보 묶음 {a}: {len(c)}개')
        else:
            notes.append(f'{a} 후보 {nb} → {len(c)}')
            if nb > 0 and len(c) < 0.8 * nb: fails.append(f'{a} 후보가 기준의 80% 아래로 줄어듦({nb} → {len(c)})')
        for x in c[:50]:
            if not {'id', 'agent', 'desc', 'direction', 'trades'} <= set(x): fails.append(f'{a} 후보 형식이 맞지 않음(id·agent·desc·direction·trades 필요)'); break
    for a in cb:
        if a not in ch: fails.append(f'{a} 후보 묶음이 사라짐')
    lb = leak(cb, cands(bt), cut) if steps(bt) else None; lh = leak(ch, cands(ht), cut) if steps(ht) else None
    if lh is None or lb is None: notes.append('자른 자료 시험을 끝내지 못해 앞을 보는 실수 점검은 건너뜀(확인 불가)')
    else:
        for a, (n, bad, ex) in lh.items():
            if n == 0: continue
            rh = bad / n; nb, bb, _ = lb.get(a, (0, 0, []))
            rb = bb / nb if nb else 0.0
            notes.append(f'앞을 보는 실수 점검 {a}: {n}개 중 어긋남 {bad}개({rh:.1%}), 기준 {rb:.1%}')
            if bad > bb + max(3, 0.02 * n): fails.append(f'{a}: 자료 끝을 잘랐을 때 과거 신호가 달라지는 후보가 늘어남({rb:.1%} → {rh:.1%}), 예: {", ".join(ex)}')
    st = {}
    try: st = json.load(open(os.path.join(hf, 'out_t', 'round_001', 'status.json'), encoding='utf-8'))
    except Exception: pass
    res = {'pass': not fails, 'fails': fails, 'notes': notes, 'changed': changed[:60], 'status': {k: st.get(k) for k in ('candidates', 'dev_pass', 'hold_pass', 'final_pass')}}
    json.dump(res, open('gate_result.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    md = ['## 진화 시험 ' + ('통과 — 자동으로 합칩니다' if not fails else '탈락 — 합치지 않습니다'), '']
    if fails: md += ['**탈락 이유**'] + [f'- {f}' for f in fails] + ['']
    md += ['**점검 기록**'] + [f'- {n}' for n in notes] + ['', f'바꾼 파일: {", ".join(changed[:20])}']
    open('gate_result.md', 'w', encoding='utf-8').write('\n'.join(md))
    print('\n'.join(md)); sys.exit(0)


if __name__ == '__main__':
    main()
