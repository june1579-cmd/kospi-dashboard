#!/usr/bin/env python3
"""미래 자료 섞임 점검 — 통과하지 못하면 시험 결과는 무효.
 (1) 잘라 보기: 날짜 T 뒤의 원자료(금투협은 T 당일 포함)를 지우고 입력을 다시 만들어, 전체 자료로 만든 행 T 와 같은지 본다.
 (2) 오염시켜 보기: T 이후 값을 엉뚱한 수로 바꿔도 행 T 입력이 그대로인지 본다.
 (3) 점검기 자체 확인: 일부러 당일 금투협 값을 넣은 입력(zz_leak)은 (1)에서 걸려야 한다.
"""
import os, sys, numpy as np, pandas as pd
import features as F

def main():
    out = os.path.join(F.HERE, 'out'); os.makedirs(out, exist_ok=True); R = F.load_raw(); full, G = F.build(R, _leaky=True)
    cols = [c for c in full.columns if c not in ('date', 'kdate', 'liq', 'y_lvl', 'y_ratio', 'y_chg')]
    ev = full.index[full['date'] >= '2019-01-01'].values; rng = np.random.RandomState(7)
    pick = sorted(set(rng.choice(ev, size=min(120, len(ev)), replace=False)) | set(ev[-15:])); lines = []; bad = {}; leak_hit = 0
    for i in pick:
        T = full.at[i, 'date']; cut, _ = F.build(R, cutoff=T, _leaky=True); a = full.loc[i, cols].astype(float).values; b = cut.loc[cut['date'] == T, cols].iloc[0].astype(float).values
        ne = ~np.isclose(np.nan_to_num(a, nan=-9e9), np.nan_to_num(b, nan=-9e9), rtol=1e-9, atol=1e-9)
        for c in np.array(cols)[ne]:
            if c == 'zz_leak': leak_hit += 1
            else: bad[c] = bad.get(c, 0) + 1
    lines.append(f'(1) 잘라 보기: {len(pick)}개 날짜 × 입력 {len(cols) - 1}개 — 불일치 입력 {len(bad)}개 {dict(list(bad.items())[:10]) if bad else ""}')
    # (2) 오염
    bad2 = 0; pick2 = pick[::8]
    for i in pick2:
        T = full.at[i, 'date']; R2 = {k: (v.copy() if v is not None else None) for k, v in R.items()}
        m = R2['kofia']['date'] >= T; R2['kofia'].loc[m, ['liq_eok', 'misu_eok', 'credit_jo', 'kospi_jo', 'kosdaq_jo', 'deposit_jo']] *= 7.7
        for key in ('mkt', 'kq', 'br'):
            if R2[key] is None: continue
            m = R2[key]['date'] > T; num = [c for c in R2[key].columns if c != 'date']; R2[key][num] = R2[key][num].astype(float); R2[key].loc[m, num] = R2[key].loc[m, num] * 3.3 + 1
        p2, _ = F.build(R2); cc = [c for c in cols if c != 'zz_leak']; a = full.loc[i, cc].astype(float).values; b = p2.loc[p2['date'] == T, cc].iloc[0].astype(float).values
        if not np.allclose(np.nan_to_num(a, nan=-9e9), np.nan_to_num(b, nan=-9e9), rtol=1e-9, atol=1e-9): bad2 += 1
    lines.append(f'(2) 오염시켜 보기: {len(pick2)}개 날짜 — 입력이 바뀐 날짜 {bad2}개')
    lines.append(f'(3) 점검기 확인: 일부러 넣은 당일 금투협 값(zz_leak)이 걸린 날짜 {leak_hit}/{len(pick)} (대부분 걸려야 정상)')
    # 시점 요약
    g = full[full['date'] >= '2019-01-01']; lines.append(f"금투협 입력의 기준일과 예측일 간격(달력일): 최소 {g['kofia_gap'].min():.0f} · 중앙 {g['kofia_gap'].median():.0f} · 최대 {g['kofia_gap'].max():.0f} (0 이면 당일 값이 섞인 것)")
    ok = (not bad) and bad2 == 0 and leak_hit >= 0.9 * len(pick) and g['kofia_gap'].min() >= 1
    lines.insert(0, '판정: ' + ('통과 — 입력에 미래 자료 없음' if ok else '실패 — 결과 무효'))
    open(os.path.join(out, 'leak_check.txt'), 'w').write('\n'.join(lines) + '\n'); print('\n'.join(lines)); sys.exit(0 if ok else 4)

if __name__ == '__main__':
    main()
