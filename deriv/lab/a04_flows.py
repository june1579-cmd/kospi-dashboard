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
    if cfg.get('young_age') and age_of:
        ma60 = k2['close'].rolling(60, min_periods=60).mean()
        trend_up = (k2['close'] > ma60).reindex(td); trend_dn = (k2['close'] < ma60).reindex(td)
        yfwd = {m: (fwd[m] if m in fwd else (k2['close'].shift(-m) / k2['open'].shift(-1) - 1) * 100) for m in YM}
        for tag in [t for t in AGE_TAGS if t in age_of]:
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
            if cfg.get('young_conds'): ycond = [c for c in ycond if c[0] in cfg['young_conds']]
            lab = {'F0x': '근월물(만기 넘어 같은 행사가 이어 셈)', 'ALL': '결제월 4개 합산'}.get(tag, tag)
            for ny in cfg.get('young_age'):
                for band in YB:
                    zm = (age_of[tag] <= ny) & (dist > 0) & (dist <= band)
                    for cn, cm in ycond:
                        mall = zm & cm
                        for m in YM:
                            v1 = yfwd[m][mall & dev].dropna(); v2 = yfwd[m][mall & p2].dropna()
                            rows.append({'시리즈': tag, '근처폭%': f'{band}%', '구역': f'새 벽(나이 {ny}일 이하) + 벽 바로 아래', '누가': cn, '부호': '', 'm일': m,
                                         '날수': len(v1), '하락%': (v1 < 0).mean() * 100 if len(v1) else np.nan, '평균%': v1.mean() if len(v1) else np.nan,
                                         '뒤 날수': len(v2), '뒤 하락%': (v2 < 0).mean() * 100 if len(v2) else np.nan})
                            if len(v1) < 20 and len(v2) < 12: continue
                            sig = td[(mall.fillna(False)).values]
                            t = pd.DataFrame({'signal': sig, 'exit': [L.exit_after(td, s_, m) for s_ in sig]}).dropna()
                            for direction in (-1, 1):
                                cands.append({'id': f'A4young_{tag}_{ny}d_{band}_{cn}_m{m}_{"dn" if direction < 0 else "up"}', 'agent': 'A4', 'family': 'young_wall',
                                              'desc': f'{lab} 새 콜벽(나이 {ny}일 이하) + 벽 바로 아래(±{band}%)' + ('' if cn == '흐름 무관' else f' + {cn}') +
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
            # 라운드 14(zone_conds.plain): 조건 없는 위치만 — σ 근처폭에서 기준으로 쓰려고(% 근처폭은 zone_only 후보와 같아 σ 만)
            if zc.get('plain'): conds = [('조건 없음', pd.Series(True, index=td), False)] + conds
            if zc.get('conds'): conds = [c for c in conds if c[0] in zc['conds']]
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
                        cands.append({'id': f'A4zc_{tag}_{band_key}_{cn}_m{m}', 'agent': 'A4', 'family': 'zone_cond',
                                      'desc': f'{tag} 벽 바로 아래(±{band_lab}), 흐름 무관' + ('' if cn == '조건 없음' else f' + {cn}') + f' → {m}일 {"하락" if direction < 0 else "상승"}',
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
    L.save_candidates('a04', cands)
    print('표', len(rows), '후보', len(cands))


if __name__ == '__main__':
    main()
