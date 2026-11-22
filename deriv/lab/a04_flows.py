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


def arb_series(td):
    """차익 프로그램 순매수(조원, KRX program_daily). 빠진 날은 빈칸(추정으로 채우지 않음)."""
    try:
        pg = pd.read_csv(os.path.join(os.path.dirname(L.LAB), 'data', 'program_daily.csv.gz'), low_memory=False)
        pg['날짜'] = pd.to_datetime(pg['날짜'])
        pg['v'] = pd.to_numeric(pg['NETBID_TRDVAL'].astype(str).str.replace(',', ''), errors='coerce') / 1e12
        return pg[pg['ITM_TP_NM'] == '차익'].drop_duplicates('날짜', keep='last').set_index('날짜')['v'].reindex(td)
    except Exception as e:
        print('차익 프로그램 자료 실패', repr(e)); return None


def spot_conds(F, td):
    """갈래 A 라운드 33(a04.young_spot, 설정 없으면 없음 → 갈래 B 영향 없음): 새 콜벽 가족의 '외국인 선물 순매수' 확인이 방향 매수인지 —
    외국인 현물(cash_for)도 함께 샀나, 같은 날들 차익 프로그램(현물-선물 맞바꿈)은 어느 쪽이었나로 나눔. 빈칸 날은 False(추정 안 함)."""
    f3 = F['fut_for'].rolling(3, min_periods=3).sum(); c3 = F['cash_for'].rolling(3, min_periods=3).sum()
    out = [('외국인 선물·현물 3일 누적 함께 순매수', (f3 > 0) & (c3 > 0)),
           ('외국인 선물 3일 누적 순매수 + 현물 3일 누적 순매도', (f3 > 0) & (c3 < 0)),
           ('외국인 선물·현물 함께 순매수', (F['fut_for'] > 0) & (F['cash_for'] > 0)),
           ('외국인 선물 순매수 + 현물 순매도', (F['fut_for'] > 0) & (F['cash_for'] < 0)),
           ('외국인 현물 3일 누적 순매수', c3 > 0)]   # 라운드 34: 현물만(선물 조건 없음) — 효과가 현물 쪽인지 '함께'인지 가르기
    a = arb_series(td)
    if a is not None:
        a3 = a.rolling(3, min_periods=3).sum()
        out += [('외국인 선물 3일 누적 순매수 + 차익 3일 누적 순매수', (f3 > 0) & (a3 > 0)),
                ('외국인 선물 3일 누적 순매수 + 차익 3일 누적 순매도', (f3 > 0) & (a3 < 0))]
    return [(n, m.reindex(td).fillna(False)) for n, m in out]


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
            if cfg.get('young_spot'): ycond += spot_conds(F, td)
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
                                ZSIG[f'A4young_{tag}_{ny}d_{bkey}_{cn}_m{m}_{"dn" if direction < 0 else "up"}'] = (sig, m, direction)   # 갈래 A 라운드 26: 전진 검증 표용(진행 중 신호 포함)
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
        if cfg.get('young_spot'): ucond += spot_conds(F, td)
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
                                    ZSIG[f'A4yu_{uk}_{"+".join(gtags)}_{ny}d_{bkey}_{cn}_m{m}_{"dn" if direction < 0 else "up"}'] = (sig, m, direction)   # 갈래 A 라운드 26: 전진 검증 표용
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
                # 갈래 B 라운드 23: ge·gt·le·lt 를 함께 줄 수 있음(모두 만족 = 구간). 예전 설정(ge 하나 또는 le 하나)은 같은 결과.
                em = pd.Series(True, index=col.index)
                if 'ge' in ex: em &= col >= ex['ge']
                if 'gt' in ex: em &= col > ex['gt']
                if 'le' in ex: em &= col <= ex['le']
                if 'lt' in ex: em &= col < ex['lt']
                em = em & col.notna()
                for bn in (zc.get('extra_base') or ['하루 늦춰 진입']):
                    base = [c for c in conds if c[0] == bn]
                    if base:
                        _, bm, bd = base[0]
                        conds.append((f"{bn} + {ex['name']}", bm & em, bd)); extra_names.append(f"{bn} + {ex['name']}")
            # 갈래 B 라운드 24(zone_conds.trend_extra: [n, …], 설정 없으면 꺼짐): 라운드 22 에서 위치 가족이 하락·횡보 해(2010·2024)에 약함 —
            #   직전 n 거래일 코스피200 수익(그날 종가까지, 문턱 0 = 정의상 값) 상승/하락을 기존 조건(extra_base)에 곱해 장세 탓인지 봄.
            for n_tr in (zc.get('trend_extra') or []):
                rn = c1 / c1.shift(int(n_tr)) - 1
                for lab_tr, tm in ((f'직전 {n_tr}일 상승', rn > 0), (f'직전 {n_tr}일 하락', rn < 0)):
                    for bn in (zc.get('extra_base') or ['하루 늦춰 진입']):
                        base = [c for c in conds if c[0] == bn]
                        if base:
                            _, bm, bd = base[0]
                            conds.append((f"{bn} + {lab_tr}", bm & tm.fillna(False), bd)); extra_names.append(f"{bn} + {lab_tr}")
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
        # 갈래 B 라운드 26(zone_conds.union: [{name, ids, m, min_votes?}], 설정 없으면 꺼짐 → 갈래 A 영향 없음): 위치 가족 안의 서로 다른 신호
        #   (벽 물량 5일 증가 + 하루 늦춤 / 외국인 선물 3일 누적 순매수 / 외국인 풋 순매수)는 앞 구간 거래 23~27개씩이라 하나로는 표본·적중이 모자람 —
        #   같은 방향(상승) 신호 날을 합쳐(min_votes 1 = 어느 하나, 2 = 둘 이상 같은 날) 독립 거래를 늘려도 적중이 버티는지. 주의: 구성 신호는 두 구간을 본 뒤 고른 것.
        urows, uprows = [], []
        for un in (zc.get('union') or []):
            parts = [ZSIG[i] for i in un.get('ids', []) if i in ZSIG]
            miss = [i for i in un.get('ids', []) if i not in ZSIG]
            if miss: print('합친 신호 구성 없음', un.get('name'), miss, flush=True)
            if len(parts) < 2: continue
            cnt = pd.Series(0, index=td)
            memb = []
            for sig_, _m, _d in parts:
                ix = pd.DatetimeIndex(sig_).intersection(td)
                cnt.loc[ix] += 1; memb.append(pd.Series(td.isin(ix), index=td))
            mu = int(un.get('m', 3)); dr = int(un.get('direction', 1))
            # 갈래 B 라운드 27: 구성별 기여(날 단위, 설명용 — 후보 안 만듦) — 한 구성만 켜진 날 / 둘 이상 켜진 날의 앞·뒤 상승%
            fu = ((k2['close'].shift(-mu) / k2['open'].shift(-1) - 1) * 100).reindex(td)
            pid = [i for i in un.get('ids', []) if i in ZSIG]
            for j, mj in enumerate(memb):
                only = mj & (cnt == 1)
                for lab_, mk in ((f'{pid[j]} 만', only),) + (((f'둘 이상 같은 날', cnt >= 2),) if j == 0 else ()):
                    w1 = fu[mk & (td <= L.DEV_END)].dropna(); w2 = fu[mk & (td >= L.HOLD_START)].dropna()
                    uprows.append({'이름': un.get('name'), '구분': lab_, 'm일': mu, '앞 날수': len(w1), '앞 상승%': (w1 > 0).mean() * 100 if len(w1) else np.nan,
                                   '뒤 날수': len(w2), '뒤 상승%': (w2 > 0).mean() * 100 if len(w2) else np.nan,
                                   '앞 평균%': w1.mean() if len(w1) else np.nan, '뒤 평균%': w2.mean() if len(w2) else np.nan})
            sig = td[(cnt >= int(un.get('min_votes', 1))).values]
            # 갈래 B 라운드 28(union 의 first_n, 없으면 그대로 → 예전과 같음): 라운드 27 에서 날 단위 65~70% < 독립 거래 78~79% —
            #   몰려 나오는 신호 중 첫 신호가 더 맞는지. 직전 first_n 거래일 안에 같은 합친 신호가 없던 날만 남김(미리 정한 n, 결과 보고 고른 값 아님).
            fn = int(un.get('first_n', 0) or 0)
            if fn > 0 and len(sig):
                ps = np.searchsorted(td.values, sig.values)
                keep = np.r_[True, np.diff(ps) > fn]
                sig = sig[keep]
            # 갈래 B 라운드 28(union 의 first_table, 설명용 — 후보 안 만듦): 신호 날마다 독립 거래 여부·직전 신호와의 간격·변동성 분위·추세 → zone_first.csv
            if un.get('first_table') and len(sig):
                ps = np.searchsorted(td.values, sig.values)
                gap = np.r_[9999, np.diff(ps)]
                ind = set(L.thin(list(sig), mu, td))
                c_ = k2['close']; rv = c_.pct_change().rolling(20).std()
                rvp = rv.rolling(250, min_periods=120).apply(lambda a: (a[:-1] < a[-1]).mean() * 100 if len(a) > 1 else np.nan, raw=True)
                ma60 = c_.rolling(60).mean()
                fx = ((c_.shift(-mu) / k2['open'].shift(-1) - 1) * 100)
                frows_ = []
                for d_, g_ in zip(sig, gap):
                    frows_.append({'이름': un.get('name'), '날짜': d_.date(), '구간': 'P1' if d_ <= L.DEV_END else 'P2', '해': d_.year,
                                   '독립 거래': d_ in ind, '직전 신호 간격(거래일)': int(g_) if g_ < 9999 else np.nan,
                                   '첫 신호(5일)': bool(g_ > 5), '첫 신호(10일)': bool(g_ > 10),
                                   '20일 변동성 분위(직전 250일)': rvp.get(d_, np.nan), '60일선 위': bool(c_.get(d_, np.nan) > ma60.get(d_, np.nan)),
                                   f'{mu}일 수익%': fx.get(d_, np.nan)})
                FT = pd.DataFrame(frows_)
                FT.round(2).to_csv(os.path.join(od, f"zone_first_{un.get('name')}.csv"), index=False, encoding='utf-8')
                srows = []
                rcol = f'{mu}일 수익%'
                for per in ('P1', 'P2'):
                    G = FT[(FT['구간'] == per) & FT[rcol].notna()]
                    for lab_, mk in (('모든 신호 날', pd.Series(True, index=G.index)), ('독립 거래', G['독립 거래']),
                                     ('독립 거래 · 첫 신호(5일)', G['독립 거래'] & G['첫 신호(5일)']), ('독립 거래 · 뒤따름(5일 안)', G['독립 거래'] & ~G['첫 신호(5일)']),
                                     ('뒤따름(독립 아님)', ~G['독립 거래']),
                                     ('독립 거래 · 변동성 분위 ≥ 60', G['독립 거래'] & (G['20일 변동성 분위(직전 250일)'] >= 60)),
                                     ('독립 거래 · 변동성 분위 < 60', G['독립 거래'] & (G['20일 변동성 분위(직전 250일)'] < 60)),
                                     ('독립 거래 · 60일선 아래', G['독립 거래'] & ~G['60일선 위'])):
                        x = G.loc[mk.fillna(False), rcol]
                        srows.append({'이름': un.get('name'), '구간': per, '묶음': lab_, '수': len(x),
                                      '상승%': (x > 0).mean() * 100 if len(x) else np.nan, '평균%': x.mean() if len(x) else np.nan})
                pd.DataFrame(srows).round(1).to_csv(os.path.join(od, f"zone_first_summary_{un.get('name')}.csv"), index=False, encoding='utf-8')
            t = pd.DataFrame({'signal': sig, 'exit': [L.exit_after(td, s_, mu) for s_ in sig]}).dropna()
            f = ((k2['close'].shift(-mu) / k2['open'].shift(-1) - 1) * 100).reindex(sig)
            v1 = f[(sig <= L.DEV_END)].dropna(); v2 = f[sig >= L.HOLD_START].dropna()
            urows.append({'이름': un.get('name'), '구성': len(parts), '최소 겹침': un.get('min_votes', 1), 'm일': mu, '앞 날수': len(v1),
                          '앞 상승%': (v1 > 0).mean() * 100 if len(v1) else np.nan, '뒤 날수': len(v2), '뒤 상승%': (v2 > 0).mean() * 100 if len(v2) else np.nan})
            uid = f"A4zu_{un.get('name')}_m{mu}"
            ZSIG[uid] = (sig, mu, dr)
            cands.append({'id': uid, 'agent': 'A4', 'family': 'zone_union',
                          'desc': f"합친 위치 신호[{un.get('label', un.get('name'))}]" + (f" 중 {un['min_votes']}개 이상 같은 날" if un.get('min_votes', 1) > 1 else '') +
                                  (f" · 직전 {fn}거래일 안 같은 신호 없는 첫 신호만" if fn > 0 else '') +
                                  f" → {mu}일 {'상승' if dr > 0 else '하락'}", 'direction': dr, 'trades': t})
        if urows: pd.DataFrame(urows).round(1).to_csv(os.path.join(od, 'zone_union.csv'), index=False, encoding='utf-8')
        if uprows: pd.DataFrame(uprows).round(2).to_csv(os.path.join(od, 'zone_union_parts.csv'), index=False, encoding='utf-8')
    # 갈래 A 라운드 29(a04.cross_long, 설정 없으면 없음 → 갈래 B 영향 없음): 가설 본선을 '장기'까지 — 원인 분해(라운드 26~28)에서
    #   ④ 콜벽을 넘은 뒤 외국인 선물 5일 순매도는 세 구간 모두 기준보다 많았지만 ⑤ 10일 하락은 기준과 같거나 반대였다.
    #   사용자 가설은 '단기든 장기든' 이므로 같은 사건을 보유 1·5·10·20·40·60일로 열어 본다(2026-11-21~ 기간 전부 열기).
    #   사건 = 그 시리즈 어제 콜벽(K, 어제 현재가 위 최대 미결제 콜)을 오늘 종가가 처음 넘은 날(같은 결제월일 때만, ALL 은 무관).
    #   조건: (0) 넘은 날 그대로, (1) 넘은 뒤 n일 외국인 선물 누적 순매도(신호 = 넘은 날 + n 거래일 마감 뒤, 그때 아는 값),
    #   (2) (1) + 그날 종가가 여전히 옛 벽 위('위로 만든 뒤 매도' 그대로), (3) 넘은 뒤 n일 누적 순매수(대조). 양방향 사전 등록.
    #   표 a04/cross_long.csv: 구간(앞 2010~2023·뒤 2024~)별 날수·하락%·같은 구간 아무 날 m일 하락%(기준).
    cl = cfg.get('cross_long')
    if cl:
        try:
            Wc = feat.get('walls')
            Wc = Wc.copy(); Wc['date'] = pd.to_datetime(Wc['date']); Wc = Wc.drop_duplicates(['date', 'tag'], keep='last')
            close = k2['close']; ff_ = F['fut_for']
            CM = cl.get('m', [1, 5, 10, 20, 40, 60]); POST = cl.get('post', [3, 5])
            cfw = {m: (close.shift(-m) / k2['open'].shift(-1) - 1) * 100 for m in CM}
            pos_ = pd.Series(np.arange(len(td)), index=td)
            crow = []; nc0 = len(cands)
            arb_ = None
            if cl.get('arb_split'):   # 라운드 32: 차익 프로그램 순매수(조원) — deriv/data/program_daily.csv.gz(KRX), 빠진 날은 빈칸
                try:
                    pg = pd.read_csv(os.path.join(os.path.dirname(L.LAB), 'data', 'program_daily.csv.gz'), low_memory=False)
                    pg['날짜'] = pd.to_datetime(pg['날짜'])
                    pg['v'] = pd.to_numeric(pg['NETBID_TRDVAL'].astype(str).str.replace(',', ''), errors='coerce') / 1e12
                    arb_ = pg[pg['ITM_TP_NM'] == '차익'].drop_duplicates('날짜', keep='last').set_index('날짜')['v'].reindex(td)
                except Exception as e:
                    print('차익 프로그램 자료 실패', repr(e)); arb_ = None
            cf_ = F['cash_for'] if 'cash_for' in F else None
            for tag_ in cl.get('tags', ['F0', 'Q', 'ALL']):
                # 라운드 31: 'Q@touch' = 그 시리즈 어제 콜벽을 오늘 고가로 처음 건드린 날(장중에 '위로 만든' 날, 종가 무관) — 표본이 종가 돌파보다 많음
                tag, _, evk = tag_.partition('@')
                if tag in ('WT', 'WM'):   # 라운드 31: 위클리 콜벽(시리즈 = 만기일, 같은 시리즈 안에서만 돌파로 셈)
                    Wk = weekly_walls({'WT': 'wt', 'WM': 'wm'}[tag], k2, td)
                    if Wk is None: print('돌파 장기: 위클리 자료 없음', tag); continue
                    K = Wk['K'].astype(float); ym = Wk['exp'].where(Wk['exp'].notna(), None).astype(object)
                else:
                    g = Wc[Wc['tag'] == tag].set_index('date').sort_index()
                    if not len(g): print('돌파 장기: 벽 없음', tag); continue
                    K = g['K'].astype(float).reindex(td); ym = g['ym'].astype(str).reindex(td)
                Kp = K.shift(1); same = (ym == ym.shift(1)) if tag != 'ALL' else pd.Series(True, index=td)
                if evk == 'touch':
                    hi_ = k2['high']; ev = (hi_.shift(1) < Kp) & (hi_ >= Kp) & same & Kp.notna()
                else:
                    ev = (close.shift(1) < Kp) & (close >= Kp) & same & Kp.notna()
                evd = td[ev.fillna(False).values]
                lab = {'ALL': '결제월 4개 합산', 'Q': '분기물', 'F0': '근월물', 'WT': '목 위클리', 'WM': '월 위클리'}.get(tag, tag)
                conds = [('넘은 날', '', pd.DatetimeIndex(evd))]
                for n in POST:
                    s_sell, s_hold, s_buy = [], [], []
                    s_hedge, s_dirn, s_cash, s_cashb = [], [], [], []
                    for d in evd:
                        i = int(pos_[d])
                        if i + n >= len(td): continue
                        dn = td[i + n]; sm = ff_.iloc[i + 1:i + n + 1].sum()
                        if ff_.iloc[i + 1:i + n + 1].notna().sum() < n: continue   # 빠진 날은 추정으로 채우지 않음
                        if sm < 0:
                            s_sell.append(dn)
                            if close.iloc[i + n] >= Kp.loc[d]: s_hold.append(dn)
                            # 라운드 32(a04.cross_long.arb_split): 넘은 뒤 외국인 선물 매도가 헤지·차익인가 방향 매도인가
                            if arb_ is not None and arb_.iloc[i + 1:i + n + 1].notna().sum() == n:
                                (s_hedge if arb_.iloc[i + 1:i + n + 1].sum() > 0 else s_dirn).append(dn)
                            if cl.get('arb_split') and cf_ is not None and cf_.iloc[i + 1:i + n + 1].notna().sum() == n:
                                (s_cash if cf_.iloc[i + 1:i + n + 1].sum() < 0 else s_cashb).append(dn)
                        elif sm > 0: s_buy.append(dn)
                    if cl.get('arb_split'):
                        conds += [(f'넘은 뒤 {n}일 외국인 선물 누적 순매도 + 차익 프로그램 누적 순매수(헤지·차익형)', f'_a{n}', pd.DatetimeIndex(s_hedge)),
                                  (f'넘은 뒤 {n}일 외국인 선물 누적 순매도 + 차익 프로그램 누적 순매도(방향형)', f'_d{n}', pd.DatetimeIndex(s_dirn)),
                                  (f'넘은 뒤 {n}일 외국인 선물 + 현물 함께 누적 순매도', f'_c{n}', pd.DatetimeIndex(s_cash)),
                                  (f'넘은 뒤 {n}일 외국인 선물 누적 순매도 + 현물 누적 순매수', f'_k{n}', pd.DatetimeIndex(s_cashb))]
                    if cl.get('trend_split'):   # 라운드 30: 장세 나눔 — 신호 날 종가가 60일선 아래·위(그날 마감 뒤 아는 값)
                        ma60c = close.rolling(60, min_periods=60).mean()
                        dn_ = [x for x in s_sell if close.loc[x] < ma60c.loc[x]]; up_ = [x for x in s_sell if close.loc[x] >= ma60c.loc[x]]
                        conds += [(f'넘은 뒤 {n}일 외국인 선물 누적 순매도 + 60일선 아래', f'_s{n}d', pd.DatetimeIndex(dn_)),
                                  (f'넘은 뒤 {n}일 외국인 선물 누적 순매도 + 60일선 위', f'_s{n}u', pd.DatetimeIndex(up_))]
                    conds += [(f'넘은 뒤 {n}일 외국인 선물 누적 순매도', f'_s{n}', pd.DatetimeIndex(s_sell)),
                              (f'넘은 뒤 {n}일 외국인 선물 누적 순매도 + 여전히 옛 벽 위', f'_h{n}', pd.DatetimeIndex(s_hold)),
                              (f'넘은 뒤 {n}일 외국인 선물 누적 순매수(대조)', f'_b{n}', pd.DatetimeIndex(s_buy))]
                for cn, ck, sig in conds:
                    sig = pd.DatetimeIndex(sorted(set(sig)))
                    for m in CM:
                        fr = cfw[m]
                        for pn, lo, hi in (('앞 2010~2023', '2010-01-01', '2023-12-31'), ('뒤 2024~', '2024-01-01', '2100-01-01')):
                            v = fr.reindex(sig[(sig >= lo) & (sig <= hi)]).dropna()
                            b = fr[(fr.index >= lo) & (fr.index <= hi)].dropna()
                            crow.append({'시리즈': tag_, '조건': cn, 'm일': m, '구간': pn, '날수': len(v),
                                         '하락%': round(float((v < 0).mean() * 100), 1) if len(v) else np.nan,
                                         '평균%': round(float(v.mean()), 2) if len(v) else np.nan,
                                         '기준 하락%(아무 날)': round(float((b < 0).mean() * 100), 1) if len(b) else np.nan})
                        if len(sig) < 12: continue
                        t = pd.DataFrame({'signal': sig, 'exit': [L.exit_after(td, s_, m) for s_ in sig]}).dropna()
                        for direction in (-1, 1):
                            cid = f'A4x{"t" if evk == "touch" else "l"}_{tag}{ck}_m{m}_{"dn" if direction < 0 else "up"}'
                            ZSIG[cid] = (sig, m, direction)
                            cands.append({'id': cid, 'agent': 'A4', 'family': 'cross_long',
                                          'desc': f'{lab} 콜벽 ' + ('고가로 처음 건드림' if evk == 'touch' else '종가 돌파') + ('' if cn == '넘은 날' else f' → {cn}') + f' → {m}일 {"하락" if direction < 0 else "상승"}',
                                          'direction': direction, 'trades': t})
            pd.DataFrame(crow).to_csv(os.path.join(od, 'cross_long.csv'), index=False, encoding='utf-8')
            print('돌파 장기 표', len(crow), '후보', len(cands) - nc0, flush=True)
        except Exception as e:   # 실패가 나머지 후보 저장을 막지 않게
            print('돌파 장기 실패', repr(e))
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
    # 갈래 A 라운드 27(a04.dose, 설정 없으면 없음 → 갈래 B 영향 없음): 용량-반응(원인 확인, 후보는 만들지 않아 A8 나눗수 그대로).
    #   새 콜벽 가족 신호 날(ZSIG)을 그날 외국인 선물 순매수 크기(직전 250거래일 안 백분위, 그날 마감 뒤 아는 값)로 3구간(≤60%·60~85%·85%↑) →
    #   구간(앞 2010~2023·뒤 2024~)별 날수·m일 상승%. 순매수가 클수록 적중이 오르면 '외국인 매수가 원인' 쪽, 평평하면 위치(새 벽) 자체의 힘.
    dz = cfg.get('dose')
    if dz:
        try:
            ff = F['fut_for']
            pr = ff.rolling(250, min_periods=120).apply(lambda a: (a[:-1] < a[-1]).mean() if len(a) > 1 else np.nan, raw=True)
            cum3 = ff.rolling(3, min_periods=3).sum()
            pr3 = cum3.rolling(250, min_periods=120).apply(lambda a: (a[:-1] < a[-1]).mean() if len(a) > 1 else np.nan, raw=True)
            drows = []
            for did in dz.get('ids', []):
                if did not in ZSIG: drows.append({'id': did, '구간': '후보 없음'}); continue
                sig, m, direction = ZSIG[did]; sig = pd.DatetimeIndex(sig)
                q = (pr3 if '3일 누적' in did else pr).reindex(sig)
                fr = ((k2['close'].shift(-m) / k2['open'].shift(-1) - 1) * 100).reindex(sig)
                for pn, lo, hi in (('앞 2010~2023', '2010-01-01', '2023-12-31'), ('뒤 2024~', '2024-01-01', '2100-01-01')):
                    inp = (sig >= lo) & (sig <= hi)
                    for qn, a, b in (('60% 이하', -1, 0.6), ('60~85%', 0.6, 0.85), ('85% 초과', 0.85, 2)):
                        mk = inp & (q.values > a) & (q.values <= b)
                        v = fr[mk].dropna()
                        drows.append({'id': did, '구간': pn, '외국인 선물 순매수 크기(직전 250일 백분위)': qn, 'm일': m, '날수': len(v),
                                      '맞음%': round(float((direction * v > 0).mean() * 100), 1) if len(v) else np.nan,
                                      '평균%': round(float(v.mean()), 2) if len(v) else np.nan})
            pd.DataFrame(drows).to_csv(os.path.join(od, 'flow_dose.csv'), index=False, encoding='utf-8')
            print('용량-반응 표', len(drows), flush=True)
        except Exception as e:
            print('용량-반응 표 실패', repr(e))
    # 갈래 A 라운드 28(a04.mom_base, 설정 없으면 없음 → 갈래 B 영향 없음): 새 콜벽 가족의 힘이 '이미 오르는 중'(추세)일 뿐인지 확인(후보 안 만듦).
    #   신호 날마다 직전 5일·20일 상승률 5분위(그 구간 모든 날 기준) 칸을 찾고, 같은 칸 아무 날의 m일 맞음%를 평균 → '추세 맞춤 기준%'.
    #   신호 맞음% − 추세 맞춤 기준% = 벽·흐름 정보가 추세 위에 더한 몫. 구간(앞 2010~2023·뒤 2024~)별, 날 단위(겹침 포함, 설명용).
    mb = cfg.get('mom_base')
    if mb:
        try:
            c_ = k2['close']; r5_ = c_ / c_.shift(5) - 1; r20_ = c_ / c_.shift(20) - 1
            mrows = []
            for mid in mb.get('ids', []):
                if mid not in ZSIG: mrows.append({'id': mid, '구간': '후보 없음'}); continue
                sig, m, direction = ZSIG[mid]; sig = pd.DatetimeIndex(sig)
                fr = (c_.shift(-m) / k2['open'].shift(-1) - 1) * 100
                for pn, lo, hi in (('앞 2010~2023', '2010-01-01', '2023-12-31'), ('뒤 2024~', '2024-01-01', '2100-01-01')):
                    allm = (td >= lo) & (td <= hi) & fr.notna().values & r5_.notna().values & r20_.notna().values
                    q5 = np.nanquantile(r5_[allm], [0.2, 0.4, 0.6, 0.8]); q20 = np.nanquantile(r20_[allm], [0.2, 0.4, 0.6, 0.8])
                    b5 = pd.Series(np.digitize(r5_.values, q5), index=td); b20 = pd.Series(np.digitize(r20_.values, q20), index=td)
                    hitd = pd.Series(direction * fr.values > 0, index=td)
                    cell = hitd[allm].groupby([b5[allm], b20[allm]]).mean()
                    ss = sig[(sig >= lo) & (sig <= hi)]; ss = ss[fr.reindex(ss).notna().values & r20_.reindex(ss).notna().values]
                    if not len(ss): mrows.append({'id': mid, '구간': pn, '날수': 0}); continue
                    h_ = hitd.reindex(ss); bb = [cell.get((int(b5[d]), int(b20[d])), np.nan) for d in ss]
                    base_all = float(hitd[allm].mean())
                    mrows.append({'id': mid, '구간': pn, 'm일': m, '날수': len(ss), '신호 맞음%': round(float(h_.mean()) * 100, 1),
                                  '추세 맞춤 기준%': round(float(np.nanmean(bb)) * 100, 1), '아무 날 기준%': round(base_all * 100, 1),
                                  '추세 위 더한 몫%p': round((float(h_.mean()) - float(np.nanmean(bb))) * 100, 1),
                                  '신호 날 직전 20일 상승 5분위 평균(0~4)': round(float(np.mean([b20[d] for d in ss])), 2)})
            pd.DataFrame(mrows).to_csv(os.path.join(od, 'mom_base.csv'), index=False, encoding='utf-8')
            print('추세 맞춤 기준 표', len(mrows), flush=True)
        except Exception as e:
            print('추세 맞춤 기준 표 실패', repr(e))
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
