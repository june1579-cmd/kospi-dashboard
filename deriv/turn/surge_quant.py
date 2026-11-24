#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""surge_quant.py — 급등·급락 직전 공통점을 수치 조건으로 바꾸고, 기존 전환 매수·매도 조건 8가지와 같은 잣대로 채점한 비교표 (사용자 지시 2026-11-24).
- 표만 만든다(분석은 나중에).
- 조건 = 지표의 지난 250일 순위(0~100)가 80 이상 / 20 이하 (기존 전환 조건과 같은 방식). '막판 3일 변화'는 순위가 3일 동안 20 이상 내려감.
- 신호 = 조건이 켜진 날. 3거래일 안에 이어지면 1번으로 묶고 묶음 첫날을 신호일로 본다(정답 묶는 방식과 같음).
- 채점(신호일 종가 기준): 급등 적중 = 다음 3거래일 안 종가 +4% 이상 / 급락 적중 = -4% 이하.
  기존 정답 맞음 = 코스피200 선물 지그재그 5% 시작점(매수 쪽 저점, 매도 쪽 고점)이 신호일~3일 뒤 안.
- 제안 기준 판정 = 아직 확정 전인 통과 기준안(신호 15건↑, 신호 수별 적중률, 앞·뒤·2026 제외 조건)."""
import json, os, pickle, sys
import numpy as np
from scipy.stats import binom
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, '..', 'combo')); sys.path.insert(0, HERE)
from turn_probe import zigzag   # noqa: E402
from combo_probe import TRAIN_START   # noqa: E402
H, TH, WIN = 3, 0.04, 3

# (구분, 이름, 지표, 조건, 방향) — 조건: 'hi' = 80 이상, 'lo' = 20 이하, 'drop3' = 3일 동안 순위 20 이상 하락
NEW_UP = [('V1_대표IV', 'hi', '변동성 높음 (대표 IV)'), ('V1_VKOSPI', 'hi', '변동성 높음 (VKOSPI)'), ('C_신용/예탁금%', 'lo', '신용 비중 낮음'), ('F4_투신_5d', 'lo', '투신 5일 매도'),
          ('F4_투신_5d', 'drop3', '투신 막판 3일 급매도'), ('PK_등락_3d', 'lo', '지수 3일 급락'), ('PK_등락_2d', 'lo', '지수 2일 급락'), ('US_ewy_gap', 'hi', 'EWY 먼저 상승')]
NEW_UP_BOTTOM = [('C_신용_1년고점대비%', 'lo', '[바닥형] 신용 1년 고점 대비 많이 줄어듦'), ('OW_ALL_callotm_chg5%', 'lo', '[바닥형] 콜 외가격 미결제 감소')]
NEW_UP_TREND = [('US_sox_r20', 'hi', '[추세 중형] 미국 반도체 20일 강세'), ('S_외국인현물_1d', 'lo', '[추세 중형] 그날 외국인 매도'), ('W_대만_등락', 'lo', '[추세 중형] 대만 약세')]
NEW_DN = [('V1_대표IV', 'hi', '변동성 높음 (대표 IV)'), ('US_vix', 'hi', 'VIX 높음'), ('US_hyg_r5', 'lo', '하이일드(HYG) 5일 약세'), ('OW_ALL_cp_all', 'hi', '옵션 콜/풋 비율 높음'), ('PK_등락_1d', 'hi', '기준일 상승')]
OLD_BUY = [('US_vkospi', 'hi'), ('PK_범위위치_20d', 'lo'), ('US_es_r20', 'lo'), ('OW_ALL_volwall_dist%', 'hi'), ('US_sox_r20', 'lo'), ('US_vix_ts', 'hi'), ('PK_변동성_20d', 'hi'), ('US_vix', 'hi')]
OLD_SELL = [('OW_ALL_callotm_oi', 'lo'), ('OW_ALL_wall_share', 'hi'), ('OW_F1_callotm_oi', 'lo'), ('OW_ALL_cpcent_gap%', 'lo'), ('OW_F2_wall_top3', 'hi'), ('W_반도체_등락', 'hi'), ('OW_F1_wall_top3', 'hi'), ('US_nq_r1', 'hi')]
CN = {'hi': '80 이상', 'lo': '20 이하', 'drop3': '3일간 20 이상 하락'}


def need_hits(N, p, alpha):
    for k in range(N + 1):
        if binom.sf(k - 1, N, p) < alpha: return k
    return N + 1


def main():
    panel = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, '..', 'uni', 'out', 'panel.pkl')
    D = pickle.load(open(panel, 'rb')); X = D['X']; td = X.index; n = len(td); yr = td.year.values
    kc = D['P']['KOSPI']['close'].reindex(td).values.astype(float); fc = D['P']['K200F']['close'].reindex(td).values.astype(float); i0 = int(td.searchsorted(TRAIN_START))
    R = X.rolling(250, min_periods=120).rank(pct=True) * 100
    up = np.zeros(n, bool); dn = np.zeros(n, bool); known = np.zeros(n, bool)
    for t in range(n - H):
        w = kc[t + 1:t + 1 + H]
        if np.isfinite(kc[t]) and np.isfinite(w).all(): known[t] = True; up[t] = w.max() / kc[t] - 1 >= TH; dn[t] = w.min() / kc[t] - 1 <= -TH
    valid = known.copy(); valid[:i0] = False
    piv = zigzag(fc, 0.05); PL = set(p for p, t in piv if t == 'L'); PH = set(p for p, t in piv if t == 'H')

    def episodes(flag):
        eps = []
        for d in np.where(flag)[0]:
            if eps and d - eps[-1][-1] <= H: eps[-1].append(int(d))
            else: eps.append([int(d)])
        return eps
    EU = [e[0] for e in episodes(up & valid)]; ED = [e[0] for e in episodes(dn & valid)]
    base = {k: dict(up=float(up[valid & m].mean()), dn=float(dn[valid & m].mean())) for k, m in (('all', np.ones(n, bool)), ('front', yr <= 2023), ('back', yr >= 2024), ('to2025', yr <= 2025))}

    def cond(col, how):
        if col not in R.columns: return None
        r = R[col].values
        with np.errstate(invalid='ignore'):
            if how == 'hi': f = r >= 80
            elif how == 'lo': f = r <= 20
            else: f = np.full(n, False); f[3:] = (r[3:] - r[:-3]) <= -20
        f = f & np.isfinite(r); f[:i0] = False; return f

    def judge(N, h, Nf, hf, Nb, hb, N25, h25, side):
        if N < 15: return '미달(신호 수)'
        need = 0.55 if N < 20 else 0.45 if N < 30 else 0.35 if N < 40 else 0.30
        if h / N < need: return f'미달(적중 {need * 100:.0f}% 필요)'
        if Nf < 5 or hf < 3: return '미달(앞 기간)'
        if Nb < 5 or hb < need_hits(Nb, base['back'][side], 0.01): return '미달(뒤 기간)'
        if N25 < 8 or h25 < 3: return '미달(2026 제외)'
        return '통과(제안 기준)'

    def score(flag, side):
        on = flag & valid; days = int(on.sum()); sg = [e[0] for e in episodes(on)]; sg = np.array(sg, int)
        if not len(sg): return None
        hu = up[sg]; hd = dn[sg]; hit = hu if side == 'up' else hd; P = PL if side == 'up' else PH
        old = np.array([any((d + q) in P for q in range(WIN + 1)) for d in sg])
        f, b, t25 = yr[sg] <= 2023, yr[sg] >= 2024, yr[sg] <= 2025
        E = EU if side == 'up' else ED; ds = set(np.where(on)[0].tolist()); caught = sum(1 for e in E if any((e - q) in ds for q in range(WIN)))
        N = len(sg); h = int(hit.sum())
        return dict(days=days, N=N, hit_up=int(hu.sum()), hit_dn=int(hd.sum()), lift=(h / N) / base['all'][side] if N else 0, Nf=int(f.sum()), hf=int(hit[f].sum()), Nb=int(b.sum()), hb=int(hit[b].sum()),
                    N25=int(t25.sum()), h25=int(hit[t25].sum()), old=int(old.sum()), caught=caught, E=len(E), judge=judge(N, h, int(f.sum()), int(hit[f].sum()), int(b.sum()), int(hit[b].sum()), int(t25.sum()), int(hit[t25].sum()), side))

    rows = []
    def add(group, name, col, how, flag, side):
        s = score(flag, side) if flag is not None else None
        rows.append(dict(group=group, name=name, col=col, cond=how, side=side, **(s or {'N': 0, 'judge': '확인 불가(지표 없음)' if flag is None else '신호 없음'})))
    for col, how, nm in NEW_UP + NEW_UP_BOTTOM + NEW_UP_TREND: add('새 급등 조건', nm, col, CN[how], cond(col, how), 'up')
    for col, how, nm in NEW_DN: add('새 급락 조건', nm, col, CN[how], cond(col, how), 'dn')
    for i, (col, how) in enumerate(OLD_BUY, 1): add('기존 전환 매수 조건', f'매수 {i}', col, CN[how], cond(col, how), 'up')
    for i, (col, how) in enumerate(OLD_SELL, 1): add('기존 전환 매도 조건', f'매도 {i}', col, CN[how], cond(col, how), 'dn')
    # 점수(켜진 조건 수) 묶음
    def total(lst):
        fs = [cond(c, h) for c, h, *_ in lst]; fs = [f for f in fs if f is not None]; return np.sum(fs, 0) if fs else None, len(fs)
    core_up = [NEW_UP[0], NEW_UP[2], NEW_UP[3], NEW_UP[4], NEW_UP[5], NEW_UP[7]]   # 대표IV·신용비중·투신5일·투신막판·지수3일급락·EWY (같은 계열 중복 뺌)
    sc, m = total(core_up)
    for k in range(2, m + 1): add('새 급등 점수', f'급등 핵심 {m}개 중 {k}개 이상', '대표IV·신용비중·투신5일·투신막판·지수3일급락·EWY', f'{k}/{m}', sc >= k, 'up')
    sc, m = total(core_up + NEW_UP_BOTTOM)
    for k in range(3, m + 1): add('새 급등 점수', f'급등 핵심+바닥형 {m}개 중 {k}개 이상', '위 6개 + 신용1년고점대비·콜외가격감소', f'{k}/{m}', sc >= k, 'up')
    sc, m = total(NEW_DN)
    for k in range(2, m + 1): add('새 급락 점수', f'급락 {m}개 중 {k}개 이상', '대표IV·VIX·HYG·콜풋비율·기준일상승', f'{k}/{m}', sc >= k, 'dn')
    sc, m = total(OLD_BUY)
    for k in range(4, m + 1): add('기존 전환 매수 점수', f'매수 {m}개 중 {k}개 이상' + (' (지금 쓰는 문턱)' if k == 6 else ''), '기존 매수 조건 8개', f'{k}/{m}', sc >= k, 'up')
    sc, m = total(OLD_SELL)
    for k in range(3, m + 1): add('기존 전환 매도 점수', f'매도 {m}개 중 {k}개 이상' + (' (지금 쓰는 문턱)' if k == 5 else ''), '기존 매도 조건 8개', f'{k}/{m}', sc >= k, 'dn')
    # 변동성 + 방향 조건 짝
    iv = cond('V1_대표IV', 'hi')
    for col, how, nm in (NEW_UP[2], NEW_UP[3], NEW_UP[5], NEW_UP_BOTTOM[0]): add('변동성+방향 짝', f'대표IV 높음 + {nm}', f'V1_대표IV & {col}', f'80 이상 & {CN[how]}', iv & cond(col, how), 'up')
    for col, how, nm in (NEW_DN[2], NEW_DN[3], NEW_DN[4]): add('변동성+방향 짝', f'대표IV 높음 + {nm}', f'V1_대표IV & {col}', f'80 이상 & {CN[how]}', iv & cond(col, how), 'dn')

    pc = lambda a, b: '—' if not b else f'{a / b * 100:.0f}%'
    M = [f'# 급등·급락 조건 수치화 비교표 (2010-01 ~ {td[-1].date()}) — 표만, 분석은 나중에', '',
         '- 조건 = 지난 250일 순위 80 이상 / 20 이하 (기존 전환 조건과 같은 방식). 신호는 3거래일 안에 이어지면 1번(묶음 첫날).',
         f'- 급등 적중 = 신호일 종가 대비 3거래일 안 +4% 이상 · 급락 적중 = -4% 이하. 기존 정답 맞음 = 선물 지그재그 5% 시작점이 신호일~3일 뒤 안.',
         f"- 아무 날 확률: 급등 전체 {base['all']['up'] * 100:.1f}% · 앞 {base['front']['up'] * 100:.1f}% · 뒤 {base['back']['up'] * 100:.1f}% · 2025까지 {base['to2025']['up'] * 100:.1f}% / 급락 전체 {base['all']['dn'] * 100:.1f}% · 앞 {base['front']['dn'] * 100:.1f}% · 뒤 {base['back']['dn'] * 100:.1f}% · 2025까지 {base['to2025']['dn'] * 100:.1f}%",
         f'- 급등 묶음 {len(EU)}번 · 급락 묶음 {len(ED)}번. "잡음" = 그 묶음 기준일 또는 1~2일 전에 조건이 켜져 있었던 수.',
         '- 배수 = 노린 쪽 적중률 ÷ 아무 날 확률. 판정은 확정 전 제안 기준(신호 15건↑ · 신호 수별 적중 55/45/35/30% · 앞 5건↑·3적중↑ · 뒤 기간 우연 1% 미만 · 2025까지 8건↑·3적중↑).', '',
         '| 구분 | 이름 | 지표 | 조건 | 노린 쪽 | 켜진 날 | 신호 | 급등 적중 | 급락 적중 | 배수 | 앞 2010~23 (적중/신호) | 뒤 2024~ | 2025까지 | 기존 정답 맞음 | 잡음 | 제안 기준 판정 |',
         '|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|']
    for r in rows:
        if not r.get('N'):
            M.append(f"| {r['group']} | {r['name']} | {r['col']} | {r['cond']} | {'급등' if r['side'] == 'up' else '급락'} | — | 0 | — | — | — | — | — | — | — | — | {r['judge']} |"); continue
        M.append(f"| {r['group']} | {r['name']} | {r['col']} | {r['cond']} | {'급등' if r['side'] == 'up' else '급락'} | {r['days']} | {r['N']} | {r['hit_up']} ({pc(r['hit_up'], r['N'])}) | {r['hit_dn']} ({pc(r['hit_dn'], r['N'])}) | {r['lift']:.1f} | "
                 f"{r['hf']}/{r['Nf']} ({pc(r['hf'], r['Nf'])}) | {r['hb']}/{r['Nb']} ({pc(r['hb'], r['Nb'])}) | {r['h25']}/{r['N25']} ({pc(r['h25'], r['N25'])}) | {r['old']} ({pc(r['old'], r['N'])}) | {r['caught']}/{r['E']} | {r['judge']} |")
    M += ['', '과거 자료를 정리한 표다. 투자 권유 아님']
    od = os.path.join(HERE, 'out'); os.makedirs(od, exist_ok=True)
    open(os.path.join(od, 'surge_quant.md'), 'w', encoding='utf-8').write('\n'.join(M) + '\n')
    json.dump(dict(last_day=str(td[-1].date()), base=base, events=dict(up=len(EU), dn=len(ED)), rows=rows), open(os.path.join(od, 'surge_quant.json'), 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'), default=float)
    print(len(rows), '줄', sum(r['judge'].startswith('통과') for r in rows), '통과')


if __name__ == '__main__':
    main()
