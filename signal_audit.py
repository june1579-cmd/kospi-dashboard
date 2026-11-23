# -*- coding: utf-8 -*-
"""signal_audit.py — 대시보드 매매 신호 검증(2026-11-23 추가). GitHub 가 주 1회 돌린다(.github/workflows/audit.yml). KRX 로그인 없음.

왜: 신호는 과거 자료를 보고 고른 것이라 과거 성적이 좋게 보이는 것이 당연하다. 네 가지로 따로 본다.
  1 시기별 성적: 고를 때 쓴 기간(2015~2024) · 고른 뒤(2025~알림 전) · 실제 알림 뒤(2026-10-28~). 기준가는 신호 다음 거래일 종가.
  2 가짜 신호 시험: 신호일을 통째로 20~120거래일 뒤로 옮긴 가짜 신호가 진짜만큼 맞는 비율(높으면 '시점'에 정보가 없다는 뜻).
  3 저장 이력 재현: 저장소에 남은 날짜별 파일을 되짚어, 과거 신호가 나중에 사라지거나 뒤늦게 나타난 적이 있는지.
  4 자른 자료 시험: 원자료를 과거 어느 날에서 자르고 같은 코드로 다시 계산해, 그날 이전 신호가 지금 것과 같은지(앞날 자료를 미리 쓰는 실수 찾기).
출력: report/signal_audit.md · report/signal_audit.json. 원자료를 추정으로 채우지 않는다.
"""
import argparse, io, json, os, shutil, subprocess, sys, tempfile
import numpy as np
import pandas as pd

HZ = (5, 10, 20)
ERAS = [('고를 때 쓴 기간(2015~2024)', '2015-01-01', '2024-12-31'), ('고른 뒤(2025~알림 전)', '2025-01-01', '2026-10-27'), ('실제 알림 뒤(2026-10-28~)', '2026-10-28', '2099-12-31')]
FILES = {'alarms': lambda r: f"{r['side']} {r['type']}", 'buy3': lambda r: f"매수 최적화 {int(r['rank'])}위", 'sell3': lambda r: f"매도 최적화 {int(r['rank'])}위"}


def starts(df, fn):
    if df is None or 'start' not in df.columns: return set()
    return {(str(r['date'])[:10], fn(r)) for _, r in df[df['start'] == '시작'].iterrows()}


def load_starts(out):
    S = set()
    for f, fn in FILES.items():
        p = os.path.join(out, f + '.csv')
        if os.path.exists(p): S |= starts(pd.read_csv(p), fn)
    return S


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--out', default='out'); ap.add_argument('--report', default='report')
    ap.add_argument('--workbook', default='data/통합_원자료.xlsx'); ap.add_argument('--cuts', default='2025-06-30,2026-06-30'); a = ap.parse_args()
    mk = pd.read_csv(os.path.join(a.out, 'market_daily.csv'))[['date', 'kospi']].dropna(); dates = mk['date'].astype(str).tolist(); px = mk['kospi'].astype(float).values
    pos = {d: i for i, d in enumerate(dates)}; N = len(dates)
    S = load_starts(a.out); labels = sorted({l for _, l in S})
    R = {'made': pd.Timestamp.now(tz='Asia/Seoul').strftime('%Y-%m-%d %H:%M'), 'data_end': dates[-1], 'signals': len(S)}

    def score(idx, buy, h):          # idx = 신호일 위치들. 기준가 = 다음 거래일 종가, h 거래일 뒤 종가와 비교
        idx = np.array([i for i in idx if 0 <= i and i + 1 + h < N], int)
        if not len(idx): return 0, None, None
        r = (px[idx + 1 + h] / px[idx + 1] - 1) * 100 * (1 if buy else -1)
        return int(len(r)), float((r > 0).mean() * 100), float(r.mean())

    # 1 시기별 성적 + 바탕(그 시기 아무 날에나 같은 방향으로 잡았을 때)
    era_rows = []
    for lab in labels:
        buy = lab.startswith('매수'); ds = sorted(d for d, l in S if l == lab and d in pos)
        for en, a0, a1 in ERAS:
            idx = [pos[d] for d in ds if a0 <= d <= a1]; allidx = [i for d, i in pos.items() if a0 <= d <= a1]
            row = {'label': lab, 'era': en, 'signals': len(idx)}
            for h in HZ:
                n, hit, mean = score(idx, buy, h); _, bh, _ = score(allidx, buy, h)
                row.update({f'n{h}': n, f'hit{h}': None if hit is None else round(hit, 1), f'mean{h}': None if mean is None else round(mean, 2), f'base{h}': None if bh is None else round(bh, 1)})
            era_rows.append(row)
    R['eras'] = era_rows
    # 2 가짜 신호 시험(전체 기간, 10·20일): 신호일 전체를 k 거래일 뒤로
    pl = []
    for lab in labels:
        buy = lab.startswith('매수'); idx = [pos[d] for d, l in S if l == lab and d in pos]; row = {'label': lab}
        for h in (10, 20):
            n, hit, _ = score(idx, buy, h)
            sh = [score([i + k for i in idx], buy, h)[1] for k in range(20, 121)]; sh = [v for v in sh if v is not None]
            row.update({f'n{h}': n, f'hit{h}': None if hit is None else round(hit, 1), f'fake_mean{h}': round(float(np.mean(sh)), 1) if sh else None,
                        f'fake_ge{h}': round(float(np.mean([v >= hit for v in sh]) * 100), 1) if sh and hit is not None else None})
        pl.append(row)
    R['placebo'] = pl
    # 3 저장 이력 재현
    hist = {'commits': 0, 'vanished': [], 'late': [], 'note': ''}
    try:
        first_seen, ever = {}, set(); t0 = None
        for f, fn in FILES.items():
            log = subprocess.run(['git', 'log', '--reverse', '--format=%H %cs', '--', f'{a.out}/{f}.csv'], capture_output=True, text=True, timeout=120).stdout.split('\n')
            for ln in [x for x in log if x.strip()][-400:]:
                h, d = ln.split(); t0 = d if t0 is None or d < t0 else t0; hist['commits'] += 1
                try: df = pd.read_csv(io.StringIO(subprocess.run(['git', 'show', f'{h}:{a.out}/{f}.csv'], capture_output=True, text=True, timeout=60).stdout))
                except Exception: continue
                for k in starts(df, fn):
                    ever.add(k); first_seen.setdefault(k, d)
        hist['since'] = t0
        if t0:
            hist['vanished'] = sorted([list(k) for k in ever - S if k[0] >= t0])                    # 한때 있었는데 지금은 없는 신호
            hist['late'] = sorted([[k[0], k[1], v] for k, v in first_seen.items() if k[0] >= t0 and k in S and (pd.Timestamp(v) - pd.Timestamp(k[0])).days > 4])   # 신호일보다 5일 넘게 늦게 처음 나타남
        if hist['commits'] < 5: hist['note'] = '저장 이력이 짧아 판단 불가'
    except Exception as ex:
        hist['note'] = f'확인 불가({type(ex).__name__})'
    R['history'] = hist
    # 4 자른 자료 시험
    cuts = []
    for cut in [c for c in a.cuts.split(',') if c.strip()]:
        res = {'cut': cut, 'ok': None, 'only_full': [], 'only_cut': [], 'note': ''}
        try:
            tmp = tempfile.mkdtemp(); wb = os.path.join(tmp, 'cut.xlsx'); od = os.path.join(tmp, 'out'); os.makedirs(od)
            X = pd.read_excel(a.workbook, sheet_name=None)
            with pd.ExcelWriter(wb, engine='openpyxl') as w:
                for name, df in X.items():
                    if '일자' in df.columns: df = df[pd.to_datetime(df['일자'], errors='coerce') <= pd.Timestamp(cut)]
                    df.to_excel(w, sheet_name=name, index=False)
            p = subprocess.run([sys.executable, 'pkg/reproduce.py', wb, od, '--trend-end', cut], capture_output=True, text=True, timeout=1500)
            if p.returncode != 0: res['note'] = '다시 계산 실패: ' + (p.stderr.strip().splitlines()[-1] if p.stderr.strip() else '')[:160]
            else:
                C = load_starts(od); lim = (pd.Timestamp(cut) - pd.Timedelta(days=7)).strftime('%Y-%m-%d')      # 자른 날 직전 1주는 뺀다(끝자락 계산 차이)
                A_, B_ = {k for k in S if k[0] <= lim}, {k for k in C if k[0] <= lim}
                res.update(ok=(A_ == B_), n_full=len(A_), n_cut=len(B_), only_full=sorted(map(list, A_ - B_))[:30], only_cut=sorted(map(list, B_ - A_))[:30])
            shutil.rmtree(tmp, ignore_errors=True)
        except Exception as ex:
            res['note'] = f'확인 불가({type(ex).__name__}: {str(ex)[:120]})'
        cuts.append(res)
    R['truncate'] = cuts
    R['problems'] = len(hist['vanished']) + len(hist['late']) + sum(1 for c in cuts if c['ok'] is False)
    os.makedirs(a.report, exist_ok=True)
    json.dump(R, open(os.path.join(a.report, 'signal_audit.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    f = lambda v, s='': '—' if v is None else f'{v}{s}'
    L = ['# 대시보드 매매 신호 검증', '', f"- 계산 {R['made']} KST · 코스피 {R['data_end']} 까지 · 신호 시작 {len(S)}건 · 기준가 = 신호 다음 거래일 종가", '',
         '## 1. 시기별 성적 (10거래일 뒤 · 20거래일 뒤)', '', '| 신호 | 시기 | 신호 수 | 10일 적중 | 바탕 | 평균 | 20일 적중 | 바탕 | 평균 |', '|---|---|---|---|---|---|---|---|---|']
    L += [f"| {r['label']} | {r['era']} | {r['signals']} | {f(r['hit10'], '%')} ({r['n10']}건) | {f(r['base10'], '%')} | {f(r['mean10'], '%')} | {f(r['hit20'], '%')} ({r['n20']}건) | {f(r['base20'], '%')} | {f(r['mean20'], '%')} |" for r in era_rows if r['signals']]
    L += ['', '바탕 = 그 시기 아무 날에나 같은 방향으로 잡았을 때 맞는 비율. 평균은 신호 방향 기준(매도는 내린 만큼 +).', '',
          '## 2. 가짜 신호 시험 (신호일을 20~120거래일 뒤로 옮김, 전체 기간)', '', '| 신호 | 10일 적중 | 가짜 평균 | 가짜가 진짜 이상인 비율 | 20일 적중 | 가짜 평균 | 가짜가 진짜 이상인 비율 |', '|---|---|---|---|---|---|---|']
    L += [f"| {r['label']} | {f(r['hit10'], '%')} ({r['n10']}건) | {f(r['fake_mean10'], '%')} | {f(r['fake_ge10'], '%')} | {f(r['hit20'], '%')} ({r['n20']}건) | {f(r['fake_mean20'], '%')} | {f(r['fake_ge20'], '%')} |" for r in pl]
    L += ['', "'가짜가 진짜 이상인 비율'이 5% 아래면 신호 시점에 정보가 있다고 볼 수 있고, 높으면 시점을 옮겨도 비슷하다는 뜻.", '',
          '## 3. 저장 이력 재현', '', f"- 저장 이력: {f(hist.get('since'))} 부터 파일 {hist['commits']}번 저장분 {hist['note']}",
          f"- 한때 있었다가 사라진 신호 {len(hist['vanished'])}건" + (': ' + ' / '.join(f'{d} {l}' for d, l in hist['vanished'][:10]) if hist['vanished'] else ''),
          f"- 신호일보다 5일 넘게 늦게 나타난 신호 {len(hist['late'])}건" + (': ' + ' / '.join(f'{d} {l}(처음 보인 날 {v})' for d, l, v in hist['late'][:10]) if hist['late'] else ''), '',
          '## 4. 자른 자료 시험', '']
    for c in cuts:
        L.append(f"- {c['cut']} 에서 자름: " + (c['note'] if c['ok'] is None else (f"그 전 신호 {c['n_full']}건 모두 같음" if c['ok'] else f"다름 — 지금만 있음 {len(c['only_full'])}건, 자른 쪽만 있음 {len(c['only_cut'])}건: " + ' / '.join(f'{d} {l}' for d, l in (c['only_full'] + c['only_cut'])[:8]))))
    L += ['', '표본이 20건이 안 되는 칸은 판단 근거로 쓰지 않는다. 투자 권유 아님.']
    open(os.path.join(a.report, 'signal_audit.md'), 'w', encoding='utf-8').write('\n'.join(L) + '\n')
    print(f"신호 검증: 신호 {len(S)}건 · 이력 문제 {len(hist['vanished']) + len(hist['late'])}건 · 자른 자료 {[c['ok'] for c in cuts]}")


if __name__ == '__main__':
    main()
