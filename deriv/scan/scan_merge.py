"""기간별 예측 가능성 탐색 — 행렬 작업 결과 합치기·요약. 출력: deriv/scan/result/*.csv, summary.json"""
import glob
import json
import os
import re

import numpy as np
import pandas as pd
from scipy import stats

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'out'); RES = os.path.join(HERE, 'result'); os.makedirs(RES, exist_ok=True)
FOCUS = [2020, 2025, 2026]
TYPE_KO = {'dir': '방향(상승)', 'big_up': '급등', 'big_dn': '급락(끝값)', 'path_dn': '보유 중 급락', 'path_up': '보유 중 급등', 'trend': '추세 지속', 'ret': '수익 크기'}


def cat(name):
    fs = [f for f in glob.glob(os.path.join(OUT, '*', f'{name}.csv')) if os.path.getsize(f) > 5]
    return pd.concat([pd.read_csv(f) for f in fs], ignore_index=True) if fs else pd.DataFrame()


def binom_p(k, n):
    return stats.binomtest(int(k), int(n), 0.5, alternative='greater').pvalue if n > 0 else np.nan


def main():
    ml = cat('ml_oos'); ens = cat('ens_oos'); rules = cat('rules_oos'); now = cat('now_ml'); fin = cat('rules_final')
    ml['단위'] = np.where(ml['대상'].str.endswith('_1h'), '시간봉', '일')
    ens['단위'] = np.where(ens['대상'].str.endswith('_1h'), '시간봉', '일')
    # 1) 기간·종류별 기계학습 예측력(해마다 따로 잰 AUC 의 평균·일관성)
    rows = []
    for (inst, h, ty), g in ml.groupby(['대상', 'h', '종류']):
        r = {'대상': inst, 'h': h, '종류': ty, '종류명': TYPE_KO.get(ty, ty), '해수': len(g)}
        if ty == 'ret':
            v = g['IC'].dropna(); r['평균IC'] = v.mean(); r['IC양수해'] = int((v > 0).sum()); r['일관성p'] = binom_p((v > 0).sum(), len(v))
            for y in FOCUS: r[f'IC_{y}'] = g.loc[g['해'] == y, 'IC'].mean() if (g['해'] == y).any() else np.nan
        else:
            v = g['AUC'].dropna()
            r['평균AUC'] = v.mean(); r['중앙AUC'] = v.median(); r['AUC>0.5해'] = int((v > 0.5).sum()); r['AUC>0.55해'] = int((v > 0.55).sum())
            r['일관성p'] = binom_p((v > 0.5).sum(), len(v))
            r['평균BSS'] = g['BSS'].mean() if 'BSS' in g else np.nan
            r['상위20%실현'] = g['상위20%적중'].mean(); r['하위20%실현'] = g['하위20%적중'].mean(); r['기본'] = g['기본'].mean()
            r['상위/기본'] = r['상위20%실현'] / r['기본'] if r['기본'] > 0 else np.nan
            for y in FOCUS: r[f'AUC_{y}'] = g.loc[g['해'] == y, 'AUC'].mean() if (g['해'] == y).any() else np.nan
            r['예측력점수'] = (r['평균AUC'] - 0.5) * (r['AUC>0.5해'] / max(1, len(v)))
        rows.append(r)
    HS = pd.DataFrame(rows)
    n_tests = int(HS['일관성p'].notna().sum())
    HS.loc[HS['일관성p'].notna(), 'q'] = stats.false_discovery_control(HS.loc[HS['일관성p'].notna(), '일관성p'].values, method='bh')
    HS.round(4).to_csv(os.path.join(RES, 'horizon_skill.csv'), index=False, encoding='utf-8')
    # 2) 해마다 AUC 표(대상·종류·기간 × 해)
    YM = ml[ml['종류'] != 'ret'].pivot_table(index=['대상', '종류', 'h'], columns='해', values='AUC').round(3)
    YM.to_csv(os.path.join(RES, 'year_auc.csv'), encoding='utf-8')
    # 3) 조합 규칙 묶음 신호의 실현 확률(해마다 시험 결과를 모음)
    rows = []
    for (inst, h, ty, side), g in ens.groupby(['대상', 'h', '종류', '쪽']):
        if '적중' not in g: continue
        if '적중합' in g:   # 시간봉
            hit = g['적중합'].sum(); n = g['신호봉'].sum(); base = g['기본합'].sum() / g['시험봉'].sum()
        else:
            n = g['신호일'].sum(); hit = (g['적중'] * g['신호일']).sum(); base = (g['기본'] * g['시험일']).sum() / g['시험일'].sum()
        p = hit / n if n else np.nan
        gg = g[g.get('신호일', g.get('신호봉')) > 0]
        better = int(((gg['적중'] > gg['기본']) if side == '높임' else (gg['적중'] < gg['기본'])).sum())
        r = {'대상': inst, 'h': h, '종류': ty, '종류명': TYPE_KO.get(ty, ty), '쪽': side, '신호수': int(n), '실현확률': p, '기본확률': base,
             '차이%p': (p - base) * 100 if pd.notna(p) else np.nan, '신호있는해': len(gg), '맞는쪽해': better}
        for y in FOCUS:
            gy = g[g['해'] == y]
            r[f'실현_{y}'] = float(gy['적중'].iloc[0]) if len(gy) and pd.notna(gy['적중'].iloc[0]) else np.nan
            r[f'기본_{y}'] = float(gy['기본'].iloc[0]) if len(gy) else np.nan
        rows.append(r)
    ER = pd.DataFrame(rows); ER.round(4).to_csv(os.path.join(RES, 'rule_signal_prob.csv'), index=False, encoding='utf-8')
    # 4) 해마다 반복해서 뽑힌 규칙(문턱 숫자를 지운 이름으로 묶음)
    if len(rules):
        rules['규칙틀'] = rules['규칙'].str.replace(r'\([^)]*\)', '', regex=True)
        g = rules.groupby(['대상', 'h', '종류', '방향', '규칙틀'])
        S = g.agg(뽑힌해=('해', 'nunique'), 시험발생=('시험발생일', 'sum'), 학습확률=('학습확률', 'mean'), 학습기본=('학습기본', 'mean')).reset_index()
        hits = rules.assign(w=rules['시험적중'] * rules['시험발생일']).groupby(['대상', 'h', '종류', '방향', '규칙틀'])['w'].sum().values
        base = rules.assign(w=rules['시험기본'] * rules['시험발생일']).groupby(['대상', 'h', '종류', '방향', '규칙틀'])['w'].sum().values
        S['시험실현'] = hits / S['시험발생'].replace(0, np.nan); S['시험기본'] = base / S['시험발생'].replace(0, np.nan)
        S = S[S['뽑힌해'] >= 3].sort_values(['뽑힌해', '시험발생'], ascending=False)
        S.round(4).to_csv(os.path.join(RES, 'stable_rules.csv'), index=False, encoding='utf-8')
    # 5) 지금(마지막 날) 상태
    if len(now): now.round(4).to_csv(os.path.join(RES, 'now_ml.csv'), index=False, encoding='utf-8')
    if len(fin):
        fin[fin.get('오늘발생', False) == True].round(4).to_csv(os.path.join(RES, 'now_rules.csv'), index=False, encoding='utf-8')
        fin.round(4).to_csv(os.path.join(RES, 'rules_final.csv'), index=False, encoding='utf-8')
    # 6) 요약
    best = HS[HS['종류'] != 'ret'].sort_values('예측력점수', ascending=False).head(25)
    summ = {'시험 수(기간×종류×대상)': n_tests, '상위': best[['대상', 'h', '종류명', '평균AUC', 'AUC>0.5해', '해수', 'q']].round(3).to_dict('records')}
    json.dump(summ, open(os.path.join(RES, 'summary.json'), 'w'), ensure_ascii=False, indent=1)
    print(best[['대상', 'h', '종류명', '평균AUC', 'AUC>0.5해', '해수', '상위/기본', 'AUC_2020', 'AUC_2025', 'AUC_2026', 'q']].round(3).to_string())


if __name__ == '__main__':
    main()
