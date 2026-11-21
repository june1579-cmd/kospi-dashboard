"""A4 외국인 흐름 에이전트 — 지수가 콜벽 근처에 왔을 때 외국인이 선물·콜을 어떻게 사고팔았고, 그 뒤 지수가 어떻게 됐나.

날마다(개발 구간) 근월물(F0)·분기물(Q) 콜벽까지 거리(%)로 '벽 근처'(−band ~ +band%)를 정하고:
  - 그날 외국인 선물 순매수 / 콜 순매수 / 풋 순매수(조원) 부호별로 다음 m일 수익(다음 날 시가 → m일 뒤 종가)
  - 벽 근처에서 외국인이 선물을 팔면(또는 콜을 팔면) 하락하나 — 사용자 가설의 2단계를 매일 단위로
  - 벽이 커지는 동안(콜 미결제 5일 증가 상위) 외국인 콜 순매수가 많으면 위로 끌려가나 — 1단계
후보 신호를 A8 로 넘긴다.
"""
import os
import pickle
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lab_common as L  # noqa: E402

cfg = L.round_cfg().get('a04', {})
BANDS = cfg.get('bands', [1.0, 2.0])
MS = cfg.get('post_m', [1, 3, 5, 10])
TAGS = cfg.get('tags', ['F0', 'Q'])


WLAB = {'WT': '목 위클리', 'WM': '월 위클리'}


def weekly_walls(kind, k2, td):
    """위클리(wt·wm) 그날 콜벽: 현재가(K200 종가) 위 콜 미결제 최대 행사가. 자료 확인(2026-11-21): 하루 한 시리즈, 상장일~만기 전날 약 5거래일.
    빠진 날(월물 만기 주 목 위클리 없음, 2026-05~07 빈 응답 등)은 빈칸으로 둬 나이 연속을 끊는다(추정으로 채우지 않음)."""
    c = L.chain(kind)
    if c is None or not len(c): return None
    c = c[(c['cp'] == 'C') & (c['oi'] > 0)].copy()
    first = c.groupby('exp')['date'].min()
    rows = []
    for d, g in c.groupby('date'):
        s = float(k2['close'].get(d, np.nan))
        if not np.isfinite(s): continue
        if g['exp'].nunique() > 1:
            e = min(g['exp'].unique(), key=lambda x: first[x]); g = g[g['exp'] == e]
        ca = g[g['K'] > s]
        if len(ca) < 2: continue
        o = ca.sort_values('oi', ascending=False)
        rows.append({'date': d, 'exp': str(g['exp'].iloc[0]), 'K': float(o['K'].iloc[0]), 'dist%': (float(o['K'].iloc[0]) / s - 1) * 100,
                     'share': float(o['oi'].iloc[0] / o['oi'].sum())})
    if not rows: return None
    return pd.DataFrame(rows).set_index('date').sort_index().reindex(td)


def weekly_block(wc, k2, td, F, od):
    """갈래 A 라운드 17(a04.weekly, 설정 없으면 꺼짐 → 갈래 B 영향 없음): 위클리 옵션 콜벽으로 '천장 지킴'을 사건 수가 많은 곳에서.
    라운드 14~16: 월물 근월 벽이 7~10일 이상 그대로일 때만 벽 2% 아래 → 5일 하락 92%(개발 12일)였지만 9년에 22일뿐이라 판정 불가.
    위클리는 주마다 새 시리즈(연 약 50번) — (1) 같은 위클리 시리즈 안 벽 나이 N일 이상 + 벽 바로 아래 + 외국인 흐름 → m일,
    (1x) 다음 주 시리즈로 넘어가도 같은 행사가면 이어 센 나이(천장 연장의 주 단위판), (2) 위클리 만기(새 시리즈 첫날) 새 벽이 옛 벽보다
    내림·같음·올림 × 옛 벽이 2% 안이었나 × 외국인 선물 → m일. 모두 하락·상승 양방향 사전 등록. 교차 모드라 앞(~2023)·뒤(2024~) 서술표를 같이 낸다."""
    MSW = wc.get('post_m', [1, 2, 3, 5]); AGES = wc.get('age', [2, 3, 4]); BW = wc.get('bands', [1.0, 2.0])
    fwd = {m: (k2['close'].shift(-m) / k2['open'].shift(-1) - 1) * 100 for m in MSW}
    p1 = td <= L.DEV_END; p2 = td >= L.HOLD_START
    flows = [('흐름 무관', '', pd.Series(True, index=td))]
    for who, col in (('외국인 선물', 'fut_for'), ('외국인 콜', 'call_for')):
        flows += [(who, '순매도', F[col] < 0), (who, '순매수', F[col] > 0)]
    cands, trows, arows, rrows = [], [], [], []

    def add(cid, fam, desc, mask, m, direction):
        sig = td[mask.fillna(False).values]
        t = pd.DataFrame({'signal': sig, 'exit': [L.exit_after(td, s, m) for s in sig]}).dropna()
        cands.append({'id': cid, 'agent': 'A4', 'family': fam, 'desc': desc, 'direction': direction, 'trades': t})

    for kind in wc.get('tags', ['WT', 'WM']):
        Wk = weekly_walls({'WT': 'wt', 'WM': 'wm'}[kind], k2, td)
        if Wk is None: print('위클리 자료 없음', kind); continue
        K = Wk['K']; dist = Wk['dist%']; valid = K.notna()
        up1 = (K.shift(-1) > K) & (Wk['exp'].shift(-1) == Wk['exp'])   # 다음 날 같은 시리즈 벽이 위로(설명표만)
        for name, cross in ((kind, False), (kind + 'x', True)):
            if name not in wc.get('age_tags', [kind, kind + 'x']): continue
            key = K.round(3).astype(str) + ('' if cross else '|' + Wk['exp'].astype(str))
            age = key.groupby(key.ne(key.shift()).cumsum()).cumcount().add(1).where(valid)
            lab = WLAB[kind] + (' (다음 주 시리즈로 같은 행사가 이어 셈)' if cross else '')
            for lo, hi in ((1, 1), (2, 2), (3, 3), (4, 5), (6, 999)):
                for band in BW:
                    mm = (age >= lo) & (age <= hi) & (dist > 0) & (dist <= band)
                    r = {'시리즈': name, '벽 나이(일)': f'{lo}' if lo == hi else (f'{lo}~{hi}' if hi < 999 else f'{lo}+'), '근처폭%': band}
                    for pn, pm in (('앞', p1), ('뒤', p2)):
                        x = mm & pm; r[f'{pn} 날수'] = int(x.sum())
                        for m in (1, 3):
                            if m in fwd:
                                v = fwd[m][x].dropna(); r[f'{pn} {m}일 하락%'] = (v < 0).mean() * 100 if len(v) else np.nan
                        r[f'{pn} 다음 날 벽 위로%'] = up1[x].mean() * 100 if x.sum() else np.nan
                    arows.append(r)
            for na in AGES:
                for band in BW:
                    zm = (age >= na) & (dist > 0) & (dist <= band)
                    for who, sgn, sm in flows:
                        mall = zm & sm
                        for m in MSW:
                            v1 = fwd[m][mall & p1].dropna(); v2 = fwd[m][mall & p2].dropna()
                            trows.append({'시리즈': name, '나이': na, '근처폭%': band, '누가': who, '부호': sgn, 'm일': m,
                                          '앞 날수': len(v1), '앞 하락%': (v1 < 0).mean() * 100 if len(v1) else np.nan,
                                          '뒤 날수': len(v2), '뒤 하락%': (v2 < 0).mean() * 100 if len(v2) else np.nan})
                            if len(v1) < 20 and len(v2) < 12: continue
                            for direction in (-1, 1):
                                add(f'A4w_{name}_{na}d_{band}_{who}_{sgn}_m{m}_{"dn" if direction < 0 else "up"}', 'weekly_wall_age',
                                    f'{lab} 같은 콜벽 {na}일 이상 + 벽 바로 아래(±{band}%)' + (f' + {who} {sgn}' if sgn else '') +
                                    f' → {m}일 {"하락" if direction < 0 else "상승"}', mall, m, direction)
        # (2) 위클리 만기 = 새 시리즈 첫날: 새 벽 vs 옛 시리즈 마지막 벽
        e = Wk['exp']; newday = valid & e.ne(e.shift(1)) & valid.shift(1, fill_value=False)
        oldK = K.shift(1); oldd = dist.shift(1)
        rels = {'내림': newday & (K < oldK), '같음': newday & (K == oldK), '올림': newday & (K > oldK)}
        nears = {'옛 벽 무관': pd.Series(True, index=td), '옛 벽 2% 안': (oldd > 0) & (oldd <= 2.0)}
        fl2 = [x for x in flows if x[0] in ('흐름 무관', '외국인 선물')]
        for rel, rm in rels.items():
            for nn, nm in nears.items():
                for who, sgn, sm in fl2:
                    mall = rm & nm & sm
                    for m in MSW:
                        v1 = fwd[m][mall & p1].dropna(); v2 = fwd[m][mall & p2].dropna()
                        rrows.append({'시리즈': kind, '새 벽': rel, '옛 벽': nn, '누가': who, '부호': sgn, 'm일': m,
                                      '앞 날수': len(v1), '앞 하락%': (v1 < 0).mean() * 100 if len(v1) else np.nan,
                                      '뒤 날수': len(v2), '뒤 하락%': (v2 < 0).mean() * 100 if len(v2) else np.nan})
                        if len(v1) < 20 and len(v2) < 12: continue
                        for direction in (-1, 1):
                            add(f'A4wr_{kind}_{rel}_{nn}_{who}_{sgn}_m{m}_{"dn" if direction < 0 else "up"}', 'weekly_roll',
                                f'{WLAB[kind]} 만기(새 시리즈 첫날) 새 콜벽이 옛 벽보다 {rel}({nn})' + (f' + {who} {sgn}' if sgn else '') +
                                f' → {m}일 {"하락" if direction < 0 else "상승"}', mall, m, direction)
    pd.DataFrame(arows).round(1).to_csv(os.path.join(od, 'wall_age_weekly.csv'), index=False, encoding='utf-8')
    pd.DataFrame(trows).round(1).to_csv(os.path.join(od, 'weekly_wall_age_dev.csv'), index=False, encoding='utf-8')
    pd.DataFrame(rrows).round(1).to_csv(os.path.join(od, 'weekly_roll.csv'), index=False, encoding='utf-8')
    print('위클리 후보', len(cands), flush=True)
    return cands


ZSIG = {}   # 갈래 B 라운드 19: 위치 가족 후보 id → (신호 날(진행 중 포함), 보유일, 방향) — 전진 검증 표용


def main():
    feat = pickle.load(open(os.path.join(L.LAB, 'work', 'lab_feat.pkl'), 'rb'))
    wide = feat['wide']
    k2 = L.k200_index(); td = k2.index
    F = L.flows().reindex(td)
    X = wide.reindex(td)
    fwd = {m: (k2['close'].shift(-m) / k2['open'].shift(-1) - 1) * 100 for m in MS}
    od = L.out_dir('a04')
    rows, cands, erows = [], [], []
    dev = (td <= L.DEV_END) & (td >= pd.Timestamp('2015-01-01'))
    p2 = td >= L.HOLD_START   # flow_edge 표(설명용, 갈래 B 라운드 11 — 교차 모드에서는 탐색이 전 기간 허용)
    q_call5 = None
    # 라운드 6: 부호만이 아니라 크기·동시·연속 — 원인 분해에서 사슬 중 기준선과 가설 방향으로 다른 단계는 ④외국인 콜 순매도(76.5% vs 67.7%)뿐이고,
    # 최고 후보도 외국인 콜 흐름(벽 아래 콜 순매수 → 상승). 개발 구간 분위로 '대량'을 정하고, 선물·콜 같은 방향, 이틀 연속을 더한다(양방향 사전 등록).
    cf, ff = F['call_for'], F['fut_for']
    cq = cf[dev].quantile([0.25, 0.75]); fq = ff[dev].quantile([0.25, 0.75])
    flow_masks = []
    for who, col in (('외국인 선물', 'fut_for'), ('외국인 콜', 'call_for'), ('외국인 풋', 'put_for')):
        flow_masks += [(who, '순매도', F[col] < 0), (who, '순매수', F[col] > 0)]
    if cfg.get('flow_ext', True):
        flow_masks += [('외국인 콜 대량(개발 하위25%)', '순매도', cf <= cq.iloc[0]), ('외국인 콜 대량(개발 상위25%)', '순매수', cf >= cq.iloc[1]),
                       ('외국인 선물·콜 함께', '순매도', (cf < 0) & (ff < 0)), ('외국인 선물·콜 함께', '순매수', (cf > 0) & (ff > 0)),
                       ('외국인 선물 대량·콜 함께', '순매도', (ff <= fq.iloc[0]) & (cf < 0)), ('외국인 선물 대량·콜 함께', '순매수', (ff >= fq.iloc[1]) & (cf > 0)),
                       ('외국인 콜 이틀 연속', '순매도', (cf < 0) & (cf.shift(1) < 0)), ('외국인 콜 이틀 연속', '순매수', (cf > 0) & (cf.shift(1) > 0))]
    # 갈래 B 라운드 7(a04.flow_sum3): 하루치 부호 대신 3일 누적 순매수 부호 — 하루 흐름은 잡음이 커서 '같은 신호가 해마다 고르지 않음'의 한 원인일 수 있음.
    #   라운드 8(a04.flow_sum: 창 목록): 3일 누적이 개발 하한을 63%→68% 로 올려(풋 3일 누적 순매수 → 5·10일 상승 개발 통과) 5·10일 창도 시험.
    for nsum in (cfg.get('flow_sum') or ([3] if cfg.get('flow_sum3') else [])):
        for who, col in ((f'외국인 선물 {nsum}일 누적', 'fut_for'), (f'외국인 콜 {nsum}일 누적', 'call_for'), (f'외국인 풋 {nsum}일 누적', 'put_for')):
            s3 = F[col].rolling(nsum, min_periods=nsum).sum()
            flow_masks += [(who, '순매도', s3 < 0), (who, '순매수', s3 > 0)]
    # 갈래 B 라운드 10(a04.flow_vote: [k, …], 설정 없으면 꺼짐 → 갈래 A 영향 없음): 라운드 7~9 에서 선물·콜·풋 어느 쪽 3일 누적 순매수든
    #   '벽 바로 아래 → 짧게 상승'이 비슷하게 나와(정보가 한 갈래에 있지 않음) 세 흐름의 합의 수로 — k개 이상 같은 부호. 양방향 사전 등록.
    nv = int(cfg.get('flow_vote_win', 3))
    for k in (cfg.get('flow_vote') or []):
        sums = [F[c].rolling(nv, min_periods=nv).sum() for c in ('fut_for', 'call_for', 'put_for')]
        buy = sum((s > 0).astype(int) for s in sums); sell = sum((s < 0).astype(int) for s in sums)
        ok = pd.concat(sums, axis=1).notna().all(axis=1)
        flow_masks += [(f'외국인 선물·콜·풋 {nv}일 누적 {k}개 이상', '순매도', ok & (sell >= k)),
                       (f'외국인 선물·콜·풋 {nv}일 누적 {k}개 이상', '순매수', ok & (buy >= k))]
    # 갈래 B 라운드 7(a04.sigma_bands): '벽 근처'를 고정 %가 아니라 변동성 단위로 — 직전 20일 일간 등락 표준편차 × √5(1주 σ) × k.
    #   2017 처럼 조용한 해의 2% 는 먼 거리, 2020 처럼 거친 해의 2% 는 바로 옆이라 해마다 '근처'의 뜻이 달라짐(해마다 성적이 고르지 않은 원인 후보). 그날 종가까지 아는 값.
    sig5 = (k2['close'].pct_change().rolling(20).std() * np.sqrt(5) * 100).reindex(td)
    band_list = [(b, f'{b}%', b, False) for b in BANDS] + [(f's{k}', f'{k}σ', sig5 * k, True) for k in (cfg.get('sigma_bands') or [])]
    # 갈래 A 라운드 14(a04.wall_age: [N, …], 설정 없으면 꺼짐 → 갈래 B 영향 없음): '천장 지킴' — 라운드 7·11·13 에서 가설 방향(하락)은
    #   천장이 옮겨 가지 않을 때(같은 자리 연장)만 나왔는데, 만기일 사건이라 연 1~2번꼴이라 거래 20개를 못 채움. 같은 뜻을 날마다로:
    #   그 시리즈 콜벽 행사가가 N거래일 이상 같은 자리(같은 결제월, ALL 은 결제월 무관)인 날 + 벽 바로 아래 + 외국인 흐름 → m일. 양방향 사전 등록.
    W = feat.get('walls')
    age_of = {}; kser_of = {}
    # 라운드 15(a04.age_tags·age_bands, 없으면 라운드 14 그대로 TAGS·BANDS): 라운드 14 에서 근월물(F0) '같은 벽 5일 + 2% 아래 + 외국인 콜 순매도 → 5일 하락'
    #   12거래 92%(가설 방향, 위약 p 0.000)였지만 거래 20개 미만. 표본을 넓히려고 3·7일, 3% 폭, 차월(F1)도 보고,
    #   'F0x' = 근월물 벽을 결제월이 바뀌어도 같은 행사가면 이어 세는 나이(만기 롤오버로 천장을 그대로 다시 쓰는 '연장' — 라운드 13 의 가설 방향 사건을 날마다로).
    AGE_TAGS = cfg.get('age_tags') or TAGS
    AGE_BANDS = cfg.get('age_bands') or BANDS
    if (cfg.get('wall_age') or cfg.get('young_age')) and W is not None and len(W):
        W = W.copy(); W['date'] = pd.to_datetime(W['date'])   # 벽 없는 날(K 빈칸)은 연속을 끊는 날로 둠
        W = W.drop_duplicates(['date', 'tag'], keep='last')
        for tag, g in W.sort_values('date').groupby('tag'):
            g = g.set_index('date')
            variants = [(tag, tag == 'ALL')] + ([('F0x', True)] if tag == 'F0' and 'F0x' in AGE_TAGS else [])
            for name, cross_ym in variants:
                key = g['K'].astype(float).round(3).astype(str) + ('' if cross_ym else '|' + g['ym'].astype(str))
                run = key.ne(key.shift()).cumsum()
                age_of[name] = g.groupby(run).cumcount().add(1).where(g['K'].notna()).reindex(td)
                kser_of[name] = g["K"].astype(float).reindex(td)
    age_flows = [x for x in flow_masks if x[0] in ('외국인 선물', '외국인 콜', '외국인 풋', '외국인 선물·콜 함께', '외국인 선물 대량·콜 함께')]
    if cfg.get('age_table') and age_of:
        # 라운드 16 원인 표(개발 구간만): 벽 나이 구간별 '벽 2% 아래' 날의 5일 하락 비율과 3일 안 벽이 위로 옮겨 간 비율 — 새 벽은 옮겨 가고 오래된 벽만 버티나.
        arows = []
        for tag in [t for t in AGE_TAGS if t in age_of]:
            dist = X.get(f'OW_{"F0" if tag == "F0x" else tag}_wall_dist%')
            if dist is None: continue
            kk = kser_of[tag]   # 그 시리즈 벽 행사가(a02 walls)
            up3 = pd.concat([kk.shift(-j) > kk for j in (1, 2, 3)], axis=1).any(axis=1)
            for lo, hi in ((1, 1), (2, 3), (4, 6), (7, 10), (11, 20), (21, 999)):
                for band in (1.0, 2.0, 3.0):
                    mm = (age_of[tag] >= lo) & (age_of[tag] <= hi) & (dist > 0) & (dist <= band) & dev
                    v = fwd[5][mm].dropna() if 5 in fwd else pd.Series(dtype=float)
                    # 라운드 17(교차 모드): 같은 표를 뒤 구간(2024~)에도 — 앞·뒤가 같은 모양인지(정보가 옮겨지나) 보려고.
                    m2 = (age_of[tag] >= lo) & (age_of[tag] <= hi) & (dist > 0) & (dist <= band) & (td >= L.HOLD_START)
                    v2 = fwd[5][m2].dropna() if 5 in fwd else pd.Series(dtype=float)
                    arows.append({'시리즈': tag, '벽 나이(일)': f'{lo}~{hi}' if hi < 999 else f'{lo}+', '근처폭%': band, '날수': int(mm.sum()),
                                  '5일 하락%': (v < 0).mean() * 100 if len(v) else np.nan,
                                  '3일 안 벽 위로%': up3[mm].mean() * 100 if mm.sum() else np.nan,
                                  '뒤 날수': int(m2.sum()), '뒤 5일 하락%': (v2 < 0).mean() * 100 if len(v2) else np.nan,
                                  '뒤 3일 안 벽 위로%': up3[m2].mean() * 100 if m2.sum() else np.nan})
        pd.DataFrame(arows).round(1).to_csv(os.path.join(od, 'wall_age_dev.csv'), index=False, encoding='utf-8')
    for tag in [t for t in AGE_TAGS if t in age_of]:
        dist = X.get(f'OW_{"F0" if tag == "F0x" else tag}_wall_dist%')
        if dist is None: continue
        for na in (cfg.get('wall_age') or []):
            held = age_of[tag] >= na
            for band in AGE_BANDS:
                zm = held & (dist > 0) & (dist <= band)
                conds = [('흐름 무관', '', pd.Series(True, index=td))] + age_flows
                # 라운드 16(a04.age_oi, 없으면 꺼짐): 오래된 벽의 물량이 5일 동안 늘었나(콜 매도자가 천장을 더 쌓음)·줄었나(천장 풀림) — 흐름 조건과 곱해 양방향.
                oi5 = X.get(f'OW_{"F0" if tag == "F0x" else tag}_wall_oi_chg5%')
                if cfg.get('age_oi') and oi5 is not None:
                    conds = conds + [((f'{w}{" " + sg if sg else ""} + ' if w != '흐름 무관' else '') + f'벽 물량 5일 {nm}', sg + nm, sm & om)
                                     for w, sg, sm in conds for nm, om in (('증가', oi5 > 0), ('감소', oi5 < 0))]
                for who, sgn, sm in conds:
                    m_all = zm & sm
                    for m in MS:
                        v = fwd[m][m_all & dev].dropna()
                        rows.append({'시리즈': tag, '근처폭%': f'{band}%', '구역': f'같은 벽 {na}일 이상 + 벽 바로 아래', '누가': who, '부호': sgn, 'm일': m,
                                     '날수': len(v), '하락%': (v < 0).mean() * 100 if len(v) else np.nan, '평균%': v.mean() if len(v) else np.nan})
                        if len(v) < 15: continue
                        sig = td[(m_all.fillna(False)).values]
                        t = pd.DataFrame({'signal': sig, 'exit': [L.exit_after(td, s, m) for s in sig]}).dropna()
                        lab = '근월물(만기 넘어 같은 행사가 이어 셈)' if tag == 'F0x' else tag
                        for direction in (-1, 1):   # 양방향 사전 등록(가설 = 하락)
                            cands.append({'id': f'A4age_{tag}_{na}d_{band}_{who}_{sgn}_m{m}_{"dn" if direction < 0 else "up"}', 'agent': 'A4',
                                          'family': 'flow_wall_age',
                                          'desc': f'{lab} 같은 콜벽 {na}일 이상 유지 + 벽 바로 아래(±{band}%)' + (f' + {who}' if '벽 물량' in who else (f' + {who} {sgn}' if sgn else '')) +
                                                  f' → {m}일 {"하락" if direction < 0 else "상승"}',
                                          'direction': direction, 'trades': t})
    # 갈래 A 라운드 18(a04.young_age: [N, …], 설정 없으면 꺼짐 → 갈래 B 영향 없음): 라운드 17 교차 모드에서 앞·뒤 구간 모두 같은 모양은
    #   '새로 생긴 가까운 벽'뿐 — 근월 벽 나이 1일 + 2% 아래 → 5일 하락 앞 30%·뒤 28%(상승 70%대), 3일 안 벽 위로 앞 95%·뒤 72%.
    #   오래된 벽(천장)은 뒤 구간에서 약해짐. 그래서 벽 나이 N일 이하 + 벽 바로 아래 × (흐름 무관·외국인 선물 순매수·순매도·오늘 벽이 위로 옮겨 감·
    #   5일 안 2번 이상 위로·60일선 위·아래) → m일, 하락·상승 양방향 사전 등록(가족 young_wall). 60일선은 그날 종가까지 아는 값.
    YB = cfg.get('young_bands') or [1.0, 2.0]; YM = cfg.get('young_m') or MS
    # 라운드 22(a04.young_sigma: [k, …], 설정 없으면 없음): 고정 % 대신 변동성 단위 폭(직전 20일 σ×√5×k) — 라운드 21 통과 후보의 앞 구간 약한 해(2017·2018·2021)는 조용한 해라 2.5% 가 먼 거리였을 수 있음.
    YBL = [(b, f'{b}%', b) for b in YB] + [(f's{k}', f'{k}σ', sig5 * k) for k in (cfg.get('young_sigma') or [])]
    # 갈래 A 라운드 23(a04.young_volcap: [q, …], 설정 없으면 없음): 라운드 22 최고 후보의 뒤 구간 약한 해가 2026(고변동)이라 σ 폭이 넓어져 먼 벽까지 잡힘 —
    #   그날 변동성(sig5)이 직전 250거래일 안에서 몇 번째인지(그날 종가까지 아는 값, 앞을 보지 않음)가 q 이하인 날만 남기는 조건을 각 흐름 조건에 곱한 변형을 더함.
    vrank = sig5.rolling(250, min_periods=120).apply(lambda a: (a <= a[-1]).mean(), raw=True) if cfg.get('young_volcap') else None
    def _volcap(conds):
        if vrank is None: return conds
        return conds + [(f'{cn} + 변동성 하위 {int(q * 100)}%', cm.fillna(False) & (vrank <= q)) for cn, cm in conds for q in cfg['young_volcap']]
    if cfg.get('young_age') and age_of:
        ma60 = k2['close'].rolling(60, min_periods=60).mean()
        trend_up = (k2['close'] > ma60).reindex(td); trend_dn = (k2['close'] < ma60).reindex(td)
        yfwd = {m: (fwd[m] if m in fwd else (k2['close'].shift(-m) / k2['open'].shift(-1) - 1) * 100) for m in YM}
        for tag in [t for t in (cfg.get('young_tags') or AGE_TAGS) if t in age_of]:   # 라운드 20: young_tags 있으면 시리즈별 후보는 그 시리즈만
            base = tag[:-1] if tag.endswith('x') else tag
            dist = X.get(f'OW_{base}_wall_dist%')
            if dist is None: continue
            kk = kser_of[tag]; mup = X.get(f'OW_{base}_wall_mig_up5')
            ycond = [('흐름 무관', pd.Series(True, index=td)),
                     ('외국인 선물 순매수', F['fut_for'] > 0), ('외국인 선물 순매도', F['fut_for'] < 0),
                     ('오늘 벽이 위로 옮겨 감', kk > kk.shift(1)),
                     ('60일선 위', trend_up), ('60일선 아래', trend_dn)]
            if mup is not None: ycond.append(('벽이 5일 안 2번 이상 위로', mup >= 2))
            # 라운드 19: 라운드 18 에서 '근월 새 벽 + 2% 아래 → 5일 상승'이 앞 44거래 75%·뒤 19거래 74%(버팀)로 두 구간이 같았지만 80% 미만 —
            #   올릴 조건 후보: 분기물 벽도 2% 아래(갈래 B 의 분기물 위치 신호와 겹침), 직전 5일 하락(눌림 뒤), 외국인 선물 3일 누적 순매수.
            qd = X.get('OW_Q_wall_dist%')
            if qd is not None: ycond.append(('분기물 벽도 2% 아래', (qd > 0) & (qd <= 2.0)))
            r5 = (k2['close'] / k2['close'].shift(5) - 1).reindex(td)
            ycond += [('직전 5일 하락', r5 < 0), ('직전 5일 상승', r5 > 0), ('외국인 선물 3일 누적 순매수', F['fut_for'].rolling(3, min_periods=3).sum() > 0)]
            # 라운드 21(a04.young_flow_sum: [N, …], 설정 없으면 없음): 외국인 선물 N일 누적 순매수 — 라운드 20 에서 3일 누적이 두 구간 모두 가장 높아 창을 넓혀 봄.
            ycond += [(f'외국인 선물 {n}일 누적 순매수', F['fut_for'].rolling(n, min_periods=n).sum() > 0) for n in (cfg.get('young_flow_sum') or []) if n != 3]
            if cfg.get('young_conds'): ycond = [c for c in ycond if c[0] in cfg['young_conds']]
            ycond = _volcap(ycond)
            lab = {'F0x': '근월물(만기 넘어 같은 행사가 이어 셈)', 'ALL': '결제월 4개 합산'}.get(tag, tag)
            for ny in cfg.get('young_age'):
                for bkey, blab, band in YBL:
                    zm = (age_of[tag] <= ny) & (dist > 0) & (dist <= band)
                    for cn, cm in ycond:
                        mall = zm & cm
                        for m in YM:
                            v1 = yfwd[m][mall & dev].dropna(); v2 = yfwd[m][mall & p2].dropna()
                            rows.append({'시리즈': tag, '근처폭%': blab, '구역': f'새 벽(나이 {ny}일 이하) + 벽 바로 아래', '누가': cn, '부호': '', 'm일': m,
                                         '날수': len(v1), '하락%': (v1 < 0).mean() * 100 if len(v1) else np.nan, '평균%': v1.mean() if len(v1) else np.nan,
                                         '뒤 날수': len(v2), '뒤 하락%': (v2 < 0).mean() * 100 if len(v2) else np.nan})
                            if len(v1) < 20 and len(v2) < 12: continue
                            sig = td[(mall.fillna(False)).values]
                            t = pd.DataFrame({'signal': sig, 'exit': [L.exit_after(td, s_, m) for s_ in sig]}).dropna()
                            for direction in (-1, 1):
                                cands.append({'id': f'A4young_{tag}_{ny}d_{bkey}_{cn}_m{m}_{"dn" if direction < 0 else "up"}', 'agent': 'A4', 'family': 'young_wall',
                                              'desc': f'{lab} 새 콜벽(나이 {ny}일 이하) + 벽 바로 아래(±{blab})' + ('' if cn == '흐름 무관' else f' + {cn}') +
                                                      f' → {m}일 {"하락" if direction < 0 else "상승"}', 'direction': direction, 'trades': t})
        # 갈래 A 라운드 20(a04.young_union: [[시리즈, …], …], 설정 없으면 꺼짐 → 갈래 B 영향 없음): 라운드 19 에서 '근월 새 벽 + 2% 아래 → 5일 상승'이
        #   앞 75%·뒤 76% 로 두 구간이 같았지만, 뒤 구간 근월 새 벽 사건이 24일뿐이라 조건 하나만 더해도 거래 12 아래로 떨어짐.
        #   표본을 늘리려고 여러 결제월(근월·차월·합산) 중 '하나라도' 새 벽(나이 N일 이하) + 벽 바로 아래인 날(ANY), 그리고 '둘 이상 동시'인 날(K2,
        #   여러 결제월이 같이 새 벽을 쓰면 더 강한 뒤따름인지)을 묶음. 조건은 시리즈와 무관한 것만. 양방향 사전 등록.
        r5u = (k2['close'] / k2['close'].shift(5) - 1).reindex(td)
        qdu = X.get('OW_Q_wall_dist%')
        ucond = [('흐름 무관', pd.Series(True, index=td)),
                 ('외국인 선물 순매수', F['fut_for'] > 0), ('외국인 선물 순매도', F['fut_for'] < 0),
                 ('60일선 위', trend_up), ('60일선 아래', trend_dn),
                 ('직전 5일 하락', r5u < 0), ('직전 5일 상승', r5u > 0),
                 ('외국인 선물 3일 누적 순매수', F['fut_for'].rolling(3, min_periods=3).sum() > 0)]
        if qdu is not None: ucond.append(('분기물 벽도 2% 아래', (qdu > 0) & (qdu <= 2.0)))
        ucond += [(f'외국인 선물 {n}일 누적 순매수', F['fut_for'].rolling(n, min_periods=n).sum() > 0) for n in (cfg.get('young_flow_sum') or []) if n != 3]
        if cfg.get('young_conds'): ucond = [c for c in ucond if c[0] in cfg['young_conds']]
        ucond = _volcap(ucond)
        for grp in (cfg.get('young_union') or []):
            gtags = [t for t in grp if t in age_of and X.get(f'OW_{t[:-1] if t.endswith("x") else t}_wall_dist%') is not None]
            if len(gtags) < 2: continue
            glab = '·'.join({'F0': '근월', 'F1': '차월', 'F2': '차차월', 'F3': '분기 다음', 'ALL': '합산', 'Q': '분기물', 'Q2': '차기 분기물'}.get(t, t) for t in gtags)
            for ny in cfg.get('young_age'):
                for bkey, blab, band in YBL:
                    hits = [((age_of[t] <= ny) & (X[f'OW_{t[:-1] if t.endswith("x") else t}_wall_dist%'] > 0) &
                             (X[f'OW_{t[:-1] if t.endswith("x") else t}_wall_dist%'] <= band)).fillna(False).astype(int) for t in gtags]
                    cnt = sum(hits)
                    # 라운드 21(a04.young_union_kinds, 없으면 ANY·K2): F0K2 = 근월 새 벽이 있고 다른 결제월도 같이 새 벽(둘 이상) — 라운드 20 에서 ANY 는 흐려지고 K2 가 양방향 선별.
                    f0hit = hits[gtags.index('F0')] if 'F0' in gtags else None
                    kinds = [('ANY', cnt >= 1, '하나라도'), ('K2', cnt >= 2, '둘 이상 동시')]
                    if f0hit is not None: kinds.append(('F0K2', (f0hit >= 1) & (cnt >= 2), '근월 포함 둘 이상 동시'))
                    # 라운드 24(young_union_kinds 에 K3 있을 때만): 셋 이상 동시 — 여러 결제월이 함께 새 벽을 쓸수록 더 맞는지(ANY < K2 < K3 용량-반응, 앞·뒤 모두) 확인.
                    if len(gtags) >= 3: kinds.append(('K3', cnt >= 3, '셋 이상 동시'))
                    kinds = [k for k in kinds if k[0] in (cfg.get('young_union_kinds') or ['ANY', 'K2'])]
                    for uk, umask, ulab in kinds:
                        for cn, cm in ucond:
                            mall = umask & cm.fillna(False)
                            for m in YM:
                                v1 = yfwd[m][mall & dev].dropna(); v2 = yfwd[m][mall & p2].dropna()
                                rows.append({'시리즈': f'{uk}({"+".join(gtags)})', '근처폭%': blab, '구역': f'새 벽(나이 {ny}일 이하) + 벽 바로 아래 — {ulab}',
                                             '누가': cn, '부호': '', 'm일': m,
                                             '날수': len(v1), '하락%': (v1 < 0).mean() * 100 if len(v1) else np.nan, '평균%': v1.mean() if len(v1) else np.nan,
                                             '뒤 날수': len(v2), '뒤 하락%': (v2 < 0).mean() * 100 if len(v2) else np.nan})
                                if len(v1) < 20 and len(v2) < 12: continue
                                sig = td[(mall.fillna(False)).values]
                                t = pd.DataFrame({'signal': sig, 'exit': [L.exit_after(td, s_, m) for s_ in sig]}).dropna()
                                for direction in (-1, 1):
                                    cands.append({'id': f'A4yu_{uk}_{"+".join(gtags)}_{ny}d_{bkey}_{cn}_m{m}_{"dn" if direction < 0 else "up"}', 'agent': 'A4',
                                                  'family': 'young_union',
                                                  'desc': f'{glab} 중 {ulab} 새 콜벽(나이 {ny}일 이하) + 벽 바로 아래(±{blab})' + ('' if cn == '흐름 무관' else f' + {cn}') +
                                                          f' → {m}일 {"하락" if direction < 0 else "상승"}', 'direction': direction, 'trades': t})
    for tag in TAGS:
        dist = X.get(f'OW_{tag}_wall_dist%'); pdist = X.get(f'OW_{tag}_passed_wall_dist%')
        grow = X.get(f'OW_{tag}_callotm_chg5%')
        if dist is None: continue
        for band_key, band_lab, band, is_sig in band_list:
            # 벽 바로 아래(아직 못 넘음, 거리 0~band%) 또는 막 넘어선 직후(지나간 벽이 −band~0%)
            near_below = (dist > 0) & (dist <= band)
            just_above = (pdist >= -band) & (pdist <= 0) if pdist is not None else pd.Series(False, index=td)
            for zone, zm in (('벽 바로 아래', near_below), ('벽 막 넘음', just_above)):
                # 갈래 B 라운드 11(a04.zone_only, 설정 없으면 꺼짐 → 갈래 A 영향 없음): 라운드 10 에서 '벽 바로 아래 → 상승'이 외국인 순매수·순매도 어느 조건에서도
                #   나옴 — 흐름 없이 벽 위치만의 후보('흐름 무관')를 같이 내고, 흐름별로 위치만보다 얼마나 더 아는지(flow_edge.csv, 앞·뒤 구간 따로) 원인 분해.
                zconds = ([('흐름 무관', '', pd.Series(True, index=td))] if cfg.get('zone_only') else []) + flow_masks
                for who, sgn, sm in zconds:
                        m_all = zm & sm
                        for m in MS:
                            v = fwd[m][m_all & dev].dropna()
                            if len(v) < 15: continue
                            rows.append({'시리즈': tag, '근처폭%': band_lab, '구역': zone, '누가': who, '부호': sgn, 'm일': m, '날수': len(v),
                                         '하락%': (v < 0).mean() * 100, '평균%': v.mean()})
                            if cfg.get('zone_only'):
                                v2 = fwd[m][m_all & p2].dropna()
                                erows.append({'시리즈': tag, '근처폭%': band_lab, '구역': zone, '누가': who, '부호': sgn, 'm일': m,
                                              '앞 날수': len(v), '앞 상승%': (v > 0).mean() * 100, '뒤 날수': len(v2),
                                              '뒤 상승%': (v2 > 0).mean() * 100 if len(v2) else np.nan})
                            sig = td[(m_all.fillna(False)).values]
                            direction = -1 if (v < 0).mean() >= 0.5 else 1
                            t = pd.DataFrame({'signal': sig, 'exit': [L.exit_after(td, s, m) for s in sig]}).dropna()
                            ZSIG[f'A4_{tag}_{band_key}_{zone}_{who}_{sgn}_m{m}'] = (sig, m, direction)
                            cands.append({'id': f'A4_{tag}_{band_key}_{zone}_{who}_{sgn}_m{m}', 'agent': 'A4', 'family': 'flow_wall_sigma' if is_sig else 'flow_wall',
                                          'desc': f'{tag} {zone}(±{band_lab})에서 {who} {sgn} → {m}일 {"하락" if direction < 0 else "상승"}', 'direction': direction, 'trades': t})
        # 1단계: 콜 물량이 늘고 외국인이 콜을 사면 위로
        if grow is not None:
            g_hi = grow >= grow[dev].quantile(0.8)
            for m in MS:
                mm = g_hi & (F['call_for'] > 0) & (dist > 0)
                v = fwd[m][mm & dev].dropna()
                if len(v) < 15: continue
                rows.append({'시리즈': tag, '근처폭%': np.nan, '구역': '콜 물량 5일 증가 상위20% + 벽 위', '누가': '외국인 콜', '부호': '순매수', 'm일': m,
                             '날수': len(v), '하락%': (v < 0).mean() * 100, '평균%': v.mean()})
                sig = td[(mm.fillna(False)).values]
                t = pd.DataFrame({'signal': sig, 'exit': [L.exit_after(td, s, m) for s in sig]}).dropna()
                cands.append({'id': f'A4_{tag}_grow_callbuy_m{m}', 'agent': 'A4', 'family': 'flow_build',
                              'desc': f'{tag} 콜 물량 증가 상위20% + 외국인 콜 순매수 → {m}일 상승', 'direction': 1, 'trades': t})
    # 갈래 B 라운드 13(a04.zone_conds, 설정 없으면 꺼짐 → 갈래 A 영향 없음): 라운드 11~12 에서 정보는 외국인 흐름이 아니라 '분기물 벽 바로 아래' 위치에 있고
    #   두 구간 모두 같은 방향(3일 상승)이지만 앞 구간 74% 안팎·뒤 구간 90% — 앞 구간 적중을 올릴 조건 후보를 흐름 없이 위치만에 곱한다.
    #   (1) 진입 늦춤: 신호 다음 날(t+1)이 시가→종가 하락이었으면 / 전일 대비 하락이었으면 / 무조건 — t+1 장 마감 뒤 신호, t+2 시가 진입(그날 아는 값만).
    #   (2) 만기까지 남은 거래일(그 시리즈, a02 dte): ≤10 · 11~30 · 31+. (3) 직전 5일 하락·상승. (4) 벽 물량 5일 증가·감소(문턱 없음, 부호만).
    #   방향은 다른 위치 후보와 같이 앞 구간 다수(뒤 구간에서 뒤집히면 mirror_p2 가 '{id}__P2' 거울을 만듦). 설명표 zone_cond.csv(앞·뒤 상승%).
    zc = cfg.get('zone_conds')
    if zc:
        o1, c1 = k2['open'].reindex(td), k2['close'].reindex(td)
        dn_oc_next = (c1 < o1).shift(-1, fill_value=False)        # t+1 시가→종가 하락(t+1 장 마감 뒤 앎)
        dn_cc_next = (c1 < c1.shift(1)).shift(-1, fill_value=False)
        r5 = c1 / c1.shift(5) - 1
        bk = zc.get('barrier_k', 1.0)
        bex = {W: L.barrier_exits(k2, W, bk) for W in (zc.get('barrier') or [])}   # 라운드 16: 큰 변동 대상(아래 barrier 블록)
        zrows = []
        for tag in zc.get('tags', ['Q']):
            dist = X.get(f'OW_{tag}_wall_dist%'); dte = X.get(f'OW_{tag}_dte'); oi5 = X.get(f'OW_{tag}_wall_oi_chg5%')
            if dist is None: continue
            conds = [('다음 날 시가→종가 하락 뒤 진입', dn_oc_next, True), ('다음 날 종가 하락 뒤 진입', dn_cc_next, True),
                     ('하루 늦춰 진입', pd.Series(True, index=td), True),
                     ('직전 5일 하락', r5 < 0, False), ('직전 5일 상승', r5 > 0, False)]
            if dte is not None:
                conds += [('만기 10거래일 이내', dte <= 10, False), ('만기 11~30거래일', (dte >= 11) & (dte <= 30), False), ('만기 31거래일 이상', dte >= 31, False)]
            if oi5 is not None:
                conds += [('벽 물량 5일 증가', oi5 > 0, False), ('벽 물량 5일 감소', oi5 < 0, False)]
                # 라운드 14(zone_conds.combo): 라운드 13 에서 뒤 구간을 가장 올린 두 조건(하루 늦춤·벽 물량 5일 증가)을 함께
                if zc.get('combo'): conds += [('벽 물량 5일 증가 + 하루 늦춰 진입', oi5 > 0, True)]
            # 라운드 15(zone_conds.combo_lags: [1, 3]): 라운드 14 앞→뒤 통과 조합이 '5일' 물량 창에만 기대는지 — 1·3일 물량 증가로 바꿔도 버티나
            for lg in (zc.get('combo_lags') or []):
                oil = X.get(f'OW_{tag}_wall_oi_chg{lg}%')
                if oil is not None: conds += [(f'벽 물량 {lg}일 증가 + 하루 늦춰 진입', oil > 0, True)]
            # 라운드 17(zone_conds.extra: [{name, col, ge|le}, …] × extra_base): 사용자 가설의 '콜이 압도적으로 우세'를 위치 가족에 직접 — 벽 1위/2위 물량비·
            #   벽 몫·상위3 몫·OTM 콜/풋 등 그날 아는 a02 지표의 고정 문턱(설정에 적은 값, 결과를 보고 고른 값 아님)을 기존 조건(extra_base)에 곱함. 자료 없는 날은 빠짐.
            extra_names = []
            for ex in (zc.get('extra') or []):
                col = X.get(ex['col'].replace('{tag}', tag))
                if col is None: continue
                em = (col >= ex['ge']) if 'ge' in ex else (col <= ex['le'])
                em = em & col.notna()
                for bn in (zc.get('extra_base') or ['하루 늦춰 진입']):
                    base = [c for c in conds if c[0] == bn]
                    if base:
                        _, bm, bd = base[0]
                        conds.append((f"{bn} + {ex['name']}", bm & em, bd)); extra_names.append(f"{bn} + {ex['name']}")
            # 라운드 14(zone_conds.plain): 조건 없는 위치만 — σ 근처폭에서 기준으로 쓰려고(% 근처폭은 zone_only 후보와 같아 σ 만)
            if zc.get('plain'): conds = [('조건 없음', pd.Series(True, index=td), False)] + conds
            if zc.get('conds'): conds = [c for c in conds if c[0] in zc['conds'] or c[0] in extra_names]
            # 라운드 14(zone_conds.sigma: [k, …]): 라운드 13 에서 ±1% 날은 앞 구간 거래가 2017·2020 에 몰림(조용한 해엔 1% 가 멀고 거친 해엔 가까움) —
            #   벽 거리를 1주 σ(직전 20일 일간 표준편차 × √5, 그날 아는 값) 단위로도. 라운드 7 의 σ 시험은 흐름 조건과 함께였고 위치만은 처음.
            zbands = [(b, f'{b}%', b) for b in zc.get('bands', [0.5, 1.0, 2.0])] + [(f's{k}', f'{k}σ', sig5 * k) for k in (zc.get('sigma') or [])]
            for band_key, band_lab, band in zbands:
                if zc.get('plain') and not str(band_key).startswith('s'): conds_b = [c for c in conds if c[0] != '조건 없음']
                else: conds_b = conds
                zm = (dist > 0) & (dist <= band)
                for cn, cm, delay in conds_b:
                    mall = (zm & cm).fillna(False).values
                    idx = np.where(mall)[0] + (1 if delay else 0)
                    idx = idx[idx < len(td)]
                    sig = td[idx]
                    for m in zc.get('post_m', MS):
                        f = fwd[m] if m in fwd else (k2['close'].shift(-m) / k2['open'].shift(-1) - 1) * 100
                        f = f.reindex(td)
                        v_all = pd.Series(f.values[idx], index=sig)
                        v1 = v_all[(sig <= L.DEV_END) & (sig >= pd.Timestamp('2015-01-01'))].dropna(); v2 = v_all[sig >= L.HOLD_START].dropna()
                        zrows.append({'시리즈': tag, '근처폭%': band_lab, '조건': cn, 'm일': m, '앞 날수': len(v1), '앞 해 수': int(v1.index.year.nunique()),
                                      '앞 상승%': (v1 > 0).mean() * 100 if len(v1) else np.nan,
                                      '뒤 날수': len(v2), '뒤 상승%': (v2 > 0).mean() * 100 if len(v2) else np.nan})
                        if len(v1) < 15: continue
                        direction = -1 if (v1 < 0).mean() >= 0.5 else 1
                        t = pd.DataFrame({'signal': sig, 'exit': [L.exit_after(td, s_, m) for s_ in sig]}).dropna()
                        ZSIG[f'A4zc_{tag}_{band_key}_{cn}_m{m}'] = (sig, m, direction)
                        cands.append({'id': f'A4zc_{tag}_{band_key}_{cn}_m{m}', 'agent': 'A4', 'family': 'zone_cond',
                                      'desc': f'{tag} 벽 바로 아래(±{band_lab}), 흐름 무관' + ('' if cn == '조건 없음' else f' + {cn}') + f' → {m}일 {"하락" if direction < 0 else "상승"}',
                                      'direction': direction, 'trades': t})
                    # 갈래 B 라운드 16(zone_conds.barrier: [W, …], 설정 없으면 꺼짐 → 갈래 A 영향 없음): 라운드 15 에서 위치 가족이 3일 고정 보유에서만 앞 72~85%·
                    #   뒤 88~95% — 고정 보유 대신 '큰 변동 대상'(W 거래일 안 ±kσ√W 중 먼저 닿는 쪽, L.barrier_exits, A6·A7 의 큰 변동 창과 같은 정의)으로도 맞나.
                    #   진입·청산: 신호(늦춤이면 t+1 마감 뒤) 다음 날 시가 → 처음 넘은 날 종가(못 넘으면 W 번째 날). 방향은 앞 구간 '먼저 닿음' 다수.
                    for W in (zc.get('barrier') or []):
                        yW, exW = bex[W]
                        yv = yW.reindex(sig); ev = exW.reindex(sig)
                        y1 = yv[(sig <= L.DEV_END) & (sig >= pd.Timestamp('2015-01-01'))].dropna(); y2 = yv[sig >= L.HOLD_START].dropna()
                        zrows.append({'시리즈': tag, '근처폭%': band_lab, '조건': cn, 'm일': f'b{W}', '앞 날수': len(y1), '앞 해 수': int(y1.index.year.nunique()) if len(y1) else 0,
                                      '앞 상승%': y1.mean() * 100 if len(y1) else np.nan, '뒤 날수': len(y2), '뒤 상승%': y2.mean() * 100 if len(y2) else np.nan})
                        if len(y1) < 15: continue
                        direction = 1 if y1.mean() >= 0.5 else -1
                        t = pd.DataFrame({'signal': sig, 'exit': ev.values}).dropna()
                        cands.append({'id': f'A4zc_{tag}_{band_key}_{cn}_b{W}', 'agent': 'A4', 'family': 'zone_cond_big',
                                      'desc': f'{tag} 벽 바로 아래(±{band_lab}), 흐름 무관' + ('' if cn == '조건 없음' else f' + {cn}') +
                                              f' → {W}일 안 큰 변동(±{bk:g}σ) 먼저 {"하락" if direction < 0 else "상승"}',
                                      'direction': direction, 'trades': t})
        pd.DataFrame(zrows).round(1).to_csv(os.path.join(od, 'zone_cond.csv'), index=False, encoding='utf-8')
        print('위치 조건 후보', sum(1 for c in cands if c.get('family') == 'zone_cond'), flush=True)
    if cfg.get('weekly'):
        try:
            cands += weekly_block(cfg['weekly'], k2, td, F, od)
        except Exception as e:   # 위클리 실패가 나머지 후보 저장을 막지 않게
            print('위클리 벽 실패', repr(e))
    pd.DataFrame(rows).round(3).to_csv(os.path.join(od, 'flow_wall_dev.csv'), index=False, encoding='utf-8')
    if erows:
        E = pd.DataFrame(erows); key = ['시리즈', '근처폭%', '구역', 'm일']
        base = E[E['누가'] == '흐름 무관'][key + ['앞 상승%', '뒤 상승%']].rename(columns={'앞 상승%': '앞 위치만%', '뒤 상승%': '뒤 위치만%'})
        E = E.merge(base, on=key, how='left')
        E['앞 흐름 몫%p'] = E['앞 상승%'] - E['앞 위치만%']; E['뒤 흐름 몫%p'] = E['뒤 상승%'] - E['뒤 위치만%']
        E.round(2).to_csv(os.path.join(od, 'flow_edge.csv'), index=False, encoding='utf-8')
    # 갈래 A 라운드 25(a04.prereg_ids, 설정 없으면 없음): 2010~2014 옵션 자료(chainx_early, 라운드 24 때 새로 받음)는 지금까지 어떤 후보도 보지 않은 새 표본.
    #   라운드 24 기록(state/plan.md)에 자료를 보기 전 미리 적어 둔 후보만, 정의를 바꾸지 않고 구간별(2010~14·2015~23·2024~) 독립 거래·적중·기본·p 를 따로 적음(설명용, A8 판정은 그대로).
    if cfg.get('prereg_ids'):
        try: px = L.prices()['K200F']   # A8 과 같은 값(연속 선물)으로 — 없으면 지수
        except Exception as e: print('선물 가격 못 읽음, 지수로', repr(e)); px = k2
        prow = []; byid = {c['id']: c for c in cands}
        for pid in cfg['prereg_ids']:
            c = byid.get(pid)
            if c is None: prow.append({'id': pid, '구간': '후보 없음'}); continue
            tr = c['trades'].assign(signal=lambda d: pd.to_datetime(d['signal']), exit=lambda d: pd.to_datetime(d['exit'])).dropna()
            for lab, lo, hi in (('2010~2014(새 표본)', '2010-01-01', '2014-12-31'), ('2015~2023', '2015-01-01', '2023-12-31'), ('2024~', '2024-01-01', '2100-01-01')):
                tt = tr[(tr['signal'] >= lo) & (tr['exit'] <= hi)].sort_values('signal'); keep = []; last = pd.Timestamp('1900-01-01')
                for s_, e_ in zip(tt['signal'], tt['exit']):   # A8 independent() 와 같은 규칙: 앞 거래 청산 뒤 신호만
                    if s_ >= last: keep.append((s_, e_)); last = e_
                tt = pd.DataFrame(keep, columns=['signal', 'exit'])
                ret = L.trade_returns(tt, px) if len(tt) else np.array([]); okm = ~np.isnan(ret); tt = tt[okm]; ret = ret[okm]
                hit = c['direction'] * ret > 0; n = len(ret); k = int(hit.sum())
                tdp = px.index; hold = [((tdp > a) & (tdp <= b)).sum() for a, b in zip(tt['signal'], tt['exit'])]
                h = int(max(1, np.median(hold))) if hold else 5
                fr = (px['close'].shift(-h) / px['open'].shift(-1) - 1); fb = fr[(fr.index >= lo) & (fr.index <= hi)].dropna()
                base = float((c['direction'] * fb > 0).mean()) if len(fb) else np.nan
                yh = pd.Series(hit, index=pd.DatetimeIndex(tt['signal']).year) if n else pd.Series(dtype=float)
                prow.append({'id': pid, 'desc': c['desc'], '구간': lab, '독립 거래': n, '적중%': round(k / n * 100, 1) if n else np.nan,
                             '하한%': round(L.wilson(k, n)[0] * 100, 1) if n else np.nan, '기본%': round(base * 100, 1) if base == base else np.nan,
                             'p': round(L.binom_p(k, n, base), 4) if n and base == base else np.nan,
                             '해마다': str({int(y): [int(g.size), round(float(g.mean()), 2)] for y, g in yh.groupby(level=0)})})
        pd.DataFrame(prow).to_csv(os.path.join(od, 'prereg_p0.csv'), index=False, encoding='utf-8')
        print('사전 등록 새 표본 표', len(prow), flush=True)
    # 갈래 B 라운드 19(a04.forward, 설정 없으면 없음 → 갈래 A 영향 없음): 앞→뒤 통과·사전 등록 후보를 정의 그대로 매일 기록하는 전진 검증 표.
    #   신호(그날 장 마감 뒤 아는 값, 늦춤이면 t+1 마감 뒤) → 다음 거래일 시가 진입(연속 선물) → m 거래일째 종가 청산. 청산일이 자료 밖이면 '진행 중'.
    #   start(기본 2026-11-21) 이후 신호만 '전진' 으로 세고, 맥락용으로 최근 recent 개 신호도 함께 적음(전진 성적에는 넣지 않음). A8 판정과 무관(설명용).
    fw = cfg.get('forward')
    if fw:
      try:
          try: px = L.prices()['K200F']
          except Exception as e: print('선물 가격 못 읽음, 지수로', repr(e)); px = k2
          fstart = pd.Timestamp(fw.get('start', '2026-11-21')); frows = []; tdp = px.index
          for fid in fw.get('ids', []):
              if fid not in ZSIG: frows.append({'id': fid, '구분': '후보 없음'}); continue
              sig, m, direction = ZSIG[fid]
              sig = pd.DatetimeIndex(sig)
              pick = sorted(set(list(sig[sig >= fstart]) + list(sig[-int(fw.get('recent', 8)):])))
              for s_ in pick:
                  i = tdp.searchsorted(s_, side='right')
                  ent = tdp[i] if i < len(tdp) else pd.NaT
                  ex = L.exit_after(td, s_, m)
                  r = {'id': fid, '구분': '전진' if s_ >= fstart else '최근(맥락)', '신호일': s_.date(), '방향': '상승' if direction > 0 else '하락', '보유일': m,
                       '진입일': ent.date() if ent == ent else '다음 거래일', '진입가': float(px['open'].iloc[i]) if i < len(tdp) else np.nan,
                       '청산일': ex.date() if ex == ex else '자료 밖'}
                  if ex == ex and ex in tdp and i < len(tdp):
                      ret = (float(px['close'].loc[ex]) / float(px['open'].iloc[i]) - 1) * 100
                      r.update({'청산가': float(px['close'].loc[ex]), '수익%': round(ret, 2), '결과': '적중' if direction * ret > 0 else '빗나감'})
                  else:
                      r.update({'청산가': np.nan, '수익%': np.nan, '결과': '진행 중'})
                  frows.append(r)
          F_ = pd.DataFrame(frows); F_.to_csv(os.path.join(od, 'forward_log.csv'), index=False, encoding='utf-8')
          if len(F_) and '구분' in F_:
              done = F_[(F_['구분'] == '전진') & F_['결과'].isin(['적중', '빗나감'])] if '결과' in F_ else F_.iloc[:0]
              print('전진 검증 표', len(F_), '줄 · 전진 끝난 거래', len(done), '· 적중', int((done['결과'] == '적중').sum()) if len(done) else 0, flush=True)
      except Exception as e:   # 전진 표 실패가 후보 저장을 막지 않게
        print('전진 검증 표 실패', repr(e))
    L.save_candidates('a04', cands)
    print('표', len(rows), '후보', len(cands))


if __name__ == '__main__':
    main()
