# -*- coding: utf-8 -*-
"""random_check.py — 종목 명단을 무작위 명단과 비교(2026-11-23). KRX 로그인 없음 — validate.py 가 남긴 result/panel_<고점일>.csv.gz 만 읽는다.

validate.py 는 급락 구간의 고점일마다 '그날까지의 자료'로 점수를 다시 매겨 상위 종목의 그 뒤 성적을 잰다.
여기서는 같은 후보군에서 같은 개수를 아무렇게나 뽑은 명단 2,000개와 견줘, 상위 명단의 성적이 우연으로도 나올 수준인지 본다.
  · 구간마다: 상위 10·30·100개의 초과수익 가운데 값이 무작위 명단 중 몇 % 위치인지
  · 전체: '구간별 가운데 값의 가운데 값'과 '시장보다 나았던 구간 수'가 무작위로 나올 확률
  · 시기 나눔: 점수 기준을 만들 때 본 최근 구간(2025년 이후)과 그 전 구간을 따로
출력: result/random_check.json · result/random_check.md
"""
import glob, json, os
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__)); OUT = os.path.join(ROOT, 'result')
B = 2000; rng = np.random.default_rng(20261123)
HZ = [('crash', '급락 구간'), ('f63', '3개월 뒤'), ('f126', '6개월 뒤'), ('f252', '12개월 뒤')]
TOPS = (10, 30, 100)


def main():
    eps = []
    for f in sorted(glob.glob(os.path.join(OUT, 'panel_*.csv.gz'))):
        U = pd.read_csv(f, compression='gzip', index_col=0); T = os.path.basename(f)[6:14]
        e = {'peak': T, 'universe': int(len(U)), 'cells': {}}
        for lab, _ in HZ:
            c = 'x_' + lab
            if c not in U: continue
            V = U[['rank', c]].dropna(); x = V[c].values * 100; rk = V['rank'].values
            for k in TOPS:
                sel = rk <= k
                if sel.sum() < max(5, k // 2) or len(x) < k * 2: continue
                act = float(np.median(x[sel])); n = int(sel.sum())
                sim = np.array([np.median(x[rng.choice(len(x), n, replace=False)]) for _ in range(B)])
                e['cells'][f'{lab}_top{k}'] = {'n': n, 'median_excess': round(act, 2), 'rand_median': round(float(np.median(sim)), 2), 'pctile': round(float((sim < act).mean() * 100), 1), 'sim': sim}
        eps.append(e)
    agg = {}
    for nm, pick in (('전체', lambda e: True), ('2024년까지 고점', lambda e: e['peak'] <= '20241231'), ('2025년 이후 고점', lambda e: e['peak'] >= '20250101')):
        E = [e for e in eps if pick(e)]; agg[nm] = {'episodes': len(E)}
        for lab, _ in HZ:
            for k in TOPS:
                key = f'{lab}_top{k}'; C = [e['cells'][key] for e in E if key in e['cells']]
                if len(C) < 3: continue
                act = np.array([c['median_excess'] for c in C]); S = np.vstack([c['sim'] for c in C])          # 구간 × 무작위 2,000
                am, ap = float(np.median(act)), int((act > 0).sum()); sm = np.median(S, axis=0); sp = (S > 0).sum(axis=0)
                agg[nm][key] = {'n_ep': len(C), 'median_of_medians': round(am, 2), 'better_than_market': ap, 'rand_median_of_medians': round(float(np.median(sm)), 2),
                                'p_median': round(float((sm >= am).mean()), 4), 'p_count': round(float((sp >= ap).mean()), 4), 'mean_pctile': round(float(np.mean([c['pctile'] for c in C])), 1)}
    for e in eps:
        for c in e['cells'].values(): c.pop('sim')
    json.dump({'made': pd.Timestamp.now(tz='Asia/Seoul').strftime('%Y-%m-%d %H:%M'), 'draws': B, 'episodes': eps, 'agg': agg}, open(os.path.join(OUT, 'random_check.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    L = ['# 종목 명단 검증 — 무작위 명단과 비교', '', f'- 급락 구간 {len(eps)}개 · 구간마다 무작위 명단 {B:,}개 · 초과수익 = 종목 수익률 − 그 시장(코스피·코스닥) 가운데 값',
         '- 명단은 고점일까지의 자료로만 다시 만든 것(validate.py). 다만 점수 식 자체는 최근 급락장을 보고 정했으므로 2025년 이후 구간은 표본 안 성적이다.', '']
    for nm, A in agg.items():
        L += [f'## {nm} (구간 {A["episodes"]}개)', '', '| 기간 | 명단 | 구간 수 | 초과수익 가운데 값 | 무작위 명단 | 무작위로 이만큼 나올 확률 | 시장보다 나았던 구간 | 그 확률 |', '|---|---|---|---|---|---|---|---|']
        for lab, ln in HZ:
            for k in TOPS:
                c = A.get(f'{lab}_top{k}')
                if c: L.append(f"| {ln} | 상위 {k} | {c['n_ep']} | {c['median_of_medians']:+.2f}%p | {c['rand_median_of_medians']:+.2f}%p | {c['p_median'] * 100:.1f}% | {c['better_than_market']}/{c['n_ep']} | {c['p_count'] * 100:.1f}% |")
        L.append('')
    L += ['확률이 5% 아래면 무작위로는 나오기 어려운 성적이다. 구간 수가 적어(특히 12개월 뒤) 넓게 읽어야 한다. 투자 권유 아님.']
    open(os.path.join(OUT, 'random_check.md'), 'w', encoding='utf-8').write('\n'.join(L) + '\n')
    print('무작위 비교: 구간', len(eps))


if __name__ == '__main__':
    main()
