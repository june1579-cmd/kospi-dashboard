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


def barrier_exits(px, sigs, bpct, max_m, sl_mult=1.0):
    """갈래 A 라운드 40(a04.young_barrier): 익절·손절 종가 규칙 — 신호 다음 날 시가(연속 선물) 진입 뒤 1~max_m 일째 종가 누적 수익이
    처음 +b% 이상 또는 −b% 이하가 된 날 청산, 둘 다 없으면 max_m 일째 종가. b = 신호날 1주 σ(직전 20일, 그날 마감까지 아는 값) × k.
    청산일이 자료 밖이면 빈칸(진행 중, 추정 안 함)."""
    tdp = px.index; o = px['open'].values; c = px['close'].values; out = []
    for s_ in sigs:
        b = float(bpct.get(s_, np.nan)); i = tdp.searchsorted(s_, side='right')
        if not np.isfinite(b) or b <= 0 or i >= len(tdp): out.append(pd.NaT); continue
        ex = pd.NaT
        for j in range(max_m):
            if i + j >= len(tdp): break
            r = (c[i + j] / o[i] - 1) * 100
            # 라운드 48(sl_mult, 기본 1.0 → 라운드 40 그대로): 손절 폭 = 익절 폭 × sl_mult(위쪽 익절·아래쪽 손절, 상승 후보용).
            if r >= b or r <= -b * sl_mult or j == max_m - 1: ex = tdp[i + j]; break
        out.append(ex)
    return out


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
    age_of = {}; kser_of = {}; ym_of = {}; s_of = {}
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
                # 갈래 A 라운드 41(a04.young_origin 에서만 씀): 새 벽이 왜 새로 생겼나 — 결제월(ym)·그날 종가(S)를 같이 둠. 앞 거래일 자료 없으면 빈칸(추정 안 함).
                if cfg.get('young_origin') and name == tag:
                    ym_of[name] = g['ym'].astype(str).reindex(td) if 'ym' in g else None
                    s_of[name] = g['S'].astype(float).reindex(td) if 'S' in g else None
    # 갈래 A 라운드 38(a04.young_weekly: ['WT', 'WM'], 설정 없으면 꺼짐 → 갈래 B·D 영향 없음): 통과 계열(여러 결제월 동시 새 콜벽)의 막힘이
    #   사건 수라서, 위클리 옵션 콜벽(목 2019-09~, 월 2023-08~)을 '동시' 표에 한 표로 더함. 나이는 시리즈가 바뀌어도 같은 행사가면 이어 셈(WTx·WMx)
    #   — 주마다 새 시리즈라 시리즈별 나이는 매주 1일로 돌아가 '새 벽'이 아닌 날까지 잡힘. 자료 없는 날(위클리 상장 전·월물 만기 주)은 빈칸 → 그날 위클리 표 없음(추정 안 함).
    if cfg.get('young_weekly') and cfg.get('young_age'):
        for wk in cfg['young_weekly']:
            Wk = weekly_walls({'WT': 'wt', 'WM': 'wm'}[wk], k2, td)
            if Wk is None: print('위클리 자료 없음', wk); continue
            wvalid = Wk['K'].notna()
            # 나이는 자료 있는 날끼리만 이어 셈(빈 날 뒤 같은 행사가가 다시 나오면 새 벽으로 치지 않음 — 빈 날은 신호 없음)
            wkey = Wk['K'][wvalid].round(3).astype(str)
            age_of[wk + 'x'] = wkey.groupby(wkey.ne(wkey.shift()).cumsum()).cumcount().add(1).reindex(td)
            kser_of[wk + 'x'] = Wk['K'].astype(float)
            X[f'OW_{wk}_wall_dist%'] = Wk['dist%'].astype(float)
            print('위클리 새 벽 표', wk, '날수', int(wvalid.sum()), '나이 1일', int((age_of[wk + 'x'] <= 1).sum()))
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
        # 갈래 A 라운드 36(a04.young_trend: [조건 이름, …], 설정 없으면 없음 → 갈래 B 영향 없음): 라운드 35 설명표에서 통과 후보의 빗나감이
        #   60일선 아래 날에 몰림(앞 구간 위 23거래 87% · 아래 6거래 50%) — 새 콜벽 + 외국인 매수가 상승 장세에서만 '다음 자리'인지, 그 조건에 60일선 위를 곱한 변형.
        #   주의: 두 구간을 본 뒤 고른 나눔이라 전진 검증 전 확정 아님(보고에 적음). 60일선은 미리 있던 표준 장세 구분(문턱 고르지 않음).
        for tcn in (cfg.get('young_trend') or []):
            base_c = dict(ucond).get(tcn)
            if base_c is not None: ucond.append((f'{tcn} + 60일선 위', base_c.fillna(False) & trend_up.fillna(False)))
        # 갈래 A 라운드 44(a04.young_and: {bases, extras}, 설정 없으면 없음 → 갈래 B·D 영향 없음): 라운드 41~43 에서 앞 구간 '물량 이동' 새 벽 날이
        #   3·5·7일 70%대로 고르게 낮고 80% 는 5일째 한 점에서만 — 그 날들을 올릴 조건을 미리 정한 값으로 곱함:
        #   H8 눌림 뒤(직전 5일 하락), H9 외국인 옵션 쪽도 같은 방향(콜 3일 누적 순매수·풋 3일 누적 순매도), H10 조용한 날(20일 σ 가 직전 250일 중 하위 50%).
        #   모두 그날 장 마감 뒤 아는 값. 자료 빈칸 날은 False(추정 안 함).
        YA = cfg.get('young_and')
        if YA:
            vr_a = sig5.rolling(250, min_periods=120).apply(lambda a: (a <= a[-1]).mean(), raw=True)
            c3_ = F['call_for'].rolling(3, min_periods=3).sum(); p3_ = F['put_for'].rolling(3, min_periods=3).sum()
            xmap = {'직전 5일 하락': r5u < 0, '외국인 콜 3일 누적 순매수': c3_ > 0, '외국인 풋 3일 누적 순매도': p3_ < 0,
                    '외국인 콜 순매수 + 풋 순매도(3일 누적)': (c3_ > 0) & (p3_ < 0), '변동성 하위 50%': vr_a <= 0.5}
            dct = dict(ucond)
            for bn in YA.get('bases', []):
                if bn not in dct: print('young_and 기준 조건 없음', bn); continue
                for xn in YA.get('extras', list(xmap)):
                    if xn in xmap: ucond.append((f'{bn} + {xn}', dct[bn].fillna(False) & xmap[xn].reindex(td).fillna(False)))
            # 라운드 45(young_and.control: [조건 이름, …], 없으면 없음): 같은 흐름 조건을 새 콜벽·벽 거리 조건 없이 아무 날에나 건 대조 후보 —
            #   통과 계열의 적중이 콜벽 덕인지(벽 있는 날 > 아무 날) 흐름 덕인지(비슷) 직접 비교. 양방향, 보유 YM 그대로.
            dct2 = dict(ucond)
            for cn_ in YA.get('control', []):
                cm_ = dct2.get(cn_)
                if cm_ is None: print('대조 조건 없음', cn_); continue
                sig_c = td[cm_.fillna(False).values]
                for m in YM:
                    t_c = pd.DataFrame({'signal': sig_c, 'exit': [L.exit_after(td, s_, m) for s_ in sig_c]}).dropna()
                    for direction in (-1, 1):
                        cands.append({'id': f'A4ctl_{cn_}_m{m}_{"dn" if direction < 0 else "up"}', 'agent': 'A4', 'family': 'flow_control',
                                      'desc': f'(대조: 콜벽 조건 없음) {cn_} → {m}일 {"하락" if direction < 0 else "상승"}',
                                      'direction': direction, 'trades': t_c})
        ucond = _volcap(ucond)
        # 갈래 A 라운드 41(a04.young_origin: {kinds, sigma, conds}, 설정 없으면 없음 → 갈래 B·D 영향 없음): 통과 계열의 '새 콜벽'이 왜 새로 생겼나로 나눔.
        #   (가) 넘어섬 = 앞 거래일 벽 행사가 ≤ 오늘 종가(값이 옛 벽을 넘어서 다음 행사가가 저절로 벽이 됨 → 돌파 추세의 다른 이름),
        #   (나) 물량 이동 = 옛 벽이 아직 오늘 종가 위인데 다른 행사가로 최대 미결제가 옮겨 감(콜 우위 자리가 바뀜 → 사용자 가설의 '포지션' 쪽),
        #   (다) 만기 교체 = 결제월이 바뀌어 생긴 새 벽(만기 날 착시). 모두 그날 장 마감 뒤 아는 값, 앞 거래일 자료 없으면 어느 쪽도 아님(추정 안 함).
        YO = cfg.get('young_origin'); orig_of = {}
        if YO:
            for t_ in list(age_of):
                if t_ not in kser_of or t_.endswith('x'): continue
                kk_ = kser_of[t_]; kp_ = kk_.shift(1)
                S_ = s_of.get(t_) if s_of.get(t_) is not None else k2['close'].reindex(td)
                ym_ = ym_of.get(t_)
                new_ = (age_of[t_] <= 1) & kk_.notna() & kp_.notna()
                roll_ = (new_ & (ym_ != ym_.shift(1)) & ym_.shift(1).notna()) if ym_ is not None else pd.Series(False, index=td)
                cross_ = new_ & ~roll_ & (kp_ <= S_)
                shift_ = new_ & ~roll_ & (kp_ > S_)
                orig_of[t_] = {'roll': roll_.fillna(False), 'cross': cross_.fillna(False), 'shift': shift_.fillna(False),
                               'shift_up': (shift_ & (kk_ > kp_)).fillna(False),
                               # 라운드 46: 만기 교체가 아닌 새 벽이 옛 벽보다 위로(up)·아래로(down) 옮겨 감 — 넘어섬·물량 이동 모두 포함.
                               'up': (new_ & ~roll_ & (kk_ > kp_)).fillna(False), 'down': (new_ & ~roll_ & (kk_ < kp_)).fillna(False),
                               # 라운드 47: 아래로 옮겨 간 날 옛 벽까지 거리 가운데 얼마를 줄였나((옛 벽 − 새 벽) ÷ (옛 벽 − 종가), 0~1). 아래로 아닌 날·값 없는 날은 빈칸.
                               'dn_frac': ((kp_ - kk_) / (kp_ - S_)).where(new_ & ~roll_ & (kk_ < kp_) & (kp_ > S_))}
            print('새 벽 생긴 까닭', {t_: {k_: int(v_.sum()) for k_, v_ in d_.items()} for t_, d_ in orig_of.items()}, flush=True)
        orows = []
        YBAR = cfg.get('young_barrier'); pxb = None
        if YBAR:
            try: pxb = L.prices()['K200F']
            except Exception as e: print('선물 가격 못 읽음 — 익절·손절 후보 없음', repr(e))
        for grp in (cfg.get('young_union') or []):
            gtags = [t for t in grp if t in age_of and X.get(f'OW_{t[:-1] if t.endswith("x") else t}_wall_dist%') is not None]
            if len(gtags) < 2: continue
            glab = '·'.join({'F0': '근월', 'F1': '차월', 'F2': '차차월', 'F3': '분기 다음', 'ALL': '합산', 'Q': '분기물', 'Q2': '차기 분기물',
                             'WTx': '목 위클리', 'WMx': '월 위클리'}.get(t, t) for t in gtags)
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
                    # 라운드 38(young_union_kinds 에 K2W 있을 때만, 묶음에 위클리가 있을 때): 월물 둘 이상 동시 새 벽 + 위클리 새 벽도 함께 — 위클리가 같은 자리를 가리키면 더 맞나.
                    wix = [i for i, t in enumerate(gtags) if t in ('WTx', 'WMx')]
                    if wix and len(wix) < len(gtags):
                        mcnt = sum(h for i, h in enumerate(hits) if i not in wix); wcnt = sum(hits[i] for i in wix)
                        kinds.append(('K2W', (mcnt >= 2) & (wcnt >= 1), '월물 둘 이상 + 위클리 동시'))
                    kinds = [k for k in kinds if k[0] in (cfg.get('young_union_kinds') or ['ANY', 'K2'])]
                    # 라운드 41(young_origin): 둘 이상 동시 새 벽을 생긴 까닭으로 나눈 종류 — K2s 모두 물량 이동, K2c 하나 이상 넘어섬, K2n 만기 교체 없음.
                    okinds = set()
                    if YO and ny == 1 and all(t in orig_of for t in gtags) and bkey in [f's{k}' for k in YO.get('sigma', [])]:
                        nsh = sum((hits[i].astype(bool) & orig_of[t]['shift']).astype(int) for i, t in enumerate(gtags))
                        ncr = sum((hits[i].astype(bool) & orig_of[t]['cross']).astype(int) for i, t in enumerate(gtags))
                        nro = sum((hits[i].astype(bool) & orig_of[t]['roll']).astype(int) for i, t in enumerate(gtags))
                        k2m = cnt >= 2
                        for ok_, om_, ol_ in (('K2s', k2m & (nsh == cnt), '둘 이상 동시(모두 옛 벽이 아직 위인데 물량이 옮겨 감)'),
                                              ('K2c', k2m & (ncr >= 1), '둘 이상 동시(하나 이상은 값이 옛 벽을 넘어서 생김)'),
                                              ('K2n', k2m & (nro == 0), '둘 이상 동시(만기 교체로 생긴 벽 없음)')):
                            if ok_ in YO.get('kinds', ['K2s', 'K2c', 'K2n']): kinds.append((ok_, om_, ol_)); okinds.add(ok_)
                        # 라운드 42(kinds 에 K2a·K2u·K2sa 있을 때만): 새 벽 행사가의 콜 미결제가 오늘 늘었나(OW_<시리즈>_wall_oi_chg1% > 0 = 쌓임) —
                        #   사용자 가설의 '압도적 콜 물량'이 새로 쌓여 자리가 옮겨 갔나, 옛 벽이 풀려(줄어) 다음 행사가가 벽이 됐나. 합산(ALL)은 이 값이 없어 결제월별(F0·F1·F2)만 셈.
                        #   그날 장 마감 뒤 아는 값(오늘·어제 같은 행사가 미결제). 값 없는 날은 쌓임도 풀림도 아님(추정 안 함).
                        if any(k_ in YO.get('kinds', []) for k_ in ('K2a', 'K2u', 'K2sa')):
                            fts = [(i, t) for i, t in enumerate(gtags) if t != 'ALL' and X.get(f'OW_{t}_wall_oi_chg1%') is not None]
                            if fts:
                                nfh = sum(hits[i] for i, t in fts)
                                nac = sum((hits[i].astype(bool) & (X[f'OW_{t}_wall_oi_chg1%'] > 0)).astype(int) for i, t in fts)
                                nun = sum((hits[i].astype(bool) & (X[f'OW_{t}_wall_oi_chg1%'] <= 0)).astype(int) for i, t in fts)
                                acc_ = k2m & (nfh >= 1) & (nac == nfh); unw_ = k2m & (nun >= 1)
                                for ok_, om_, ol_ in (('K2a', acc_, '둘 이상 동시(새 벽 행사가 콜 물량이 오늘 쌓임)'),
                                                      ('K2u', unw_, '둘 이상 동시(옛 벽이 풀려 생긴 벽 포함)'),
                                                      ('K2sa', acc_ & (nsh == cnt), '둘 이상 동시(모두 물량 이동 + 새 벽 물량 쌓임)')):
                                    if ok_ in YO.get('kinds', []): kinds.append((ok_, om_, ol_)); okinds.add(ok_)
                                for cn, cm in ucond:
                                    if cn not in YO.get('conds', [cn]): continue
                                    for ol, om_ in (('새 벽 물량 쌓임', acc_), ('옛 벽 풀림 포함', unw_), ('물량 이동 + 쌓임', acc_ & (nsh == cnt)),
                                                    ('물량 이동 + 풀림 포함', unw_ & (nsh == cnt))):
                                        mm_ = om_ & cm.fillna(False)
                                        r_ = {'묶음': '+'.join(gtags), '폭': blab, '조건': cn, '까닭': ol}
                                        for pn_, pm_ in (('앞', (td <= L.DEV_END) & (td >= pd.Timestamp('2010-01-01'))), ('뒤', p2)):
                                            r_[f'{pn_} 날수'] = int((mm_ & pm_).sum())
                                            for m in YM:
                                                v_ = yfwd[m][mm_ & pm_].dropna(); r_[f'{pn_} {m}일 상승%'] = round(float((v_ > 0).mean() * 100), 1) if len(v_) else np.nan
                                        orows.append(r_)
                        # 라운드 43(kinds 에 K2d·K2cp·K2dcp 있을 때만): 사용자 가설의 '콜이 압도적으로 우세' 크기 — 새 벽마다 1위 ÷ 2위 미결제(ratio12) ≥ d12,
                        #   현재가 위 콜 미결제 ÷ 현재가 아래 풋 미결제(otm_cp) ≥ dcp (문턱 미리 정함: 1.5·1.0). 값 없는 시리즈는 '아님'(추정 안 함).
                        if any(k_ in YO.get('kinds', []) for k_ in ('K2d', 'K2cp', 'K2dcp')):
                            d12 = float(YO.get('d12', 1.5)); dcp = float(YO.get('dcp', 1.0))
                            def _allhit(col, thr):
                                ok = [(hits[i].astype(bool) & ~(X[f'OW_{t}_{col}'] >= thr).fillna(False)) if X.get(f'OW_{t}_{col}') is not None else hits[i].astype(bool)
                                      for i, t in enumerate(gtags)]
                                return ~pd.concat(ok, axis=1).any(axis=1)   # 맞은 시리즈 중 문턱 못 넘은 것이 하나도 없음
                            dom_ = k2m & _allhit('wall_ratio12', d12); cpm_ = k2m & _allhit('otm_cp', dcp)
                            for ok_, om_, ol_ in (('K2d', dom_, f'둘 이상 동시(새 벽마다 1위가 2위의 {d12}배 이상)'),
                                                  ('K2cp', cpm_, f'둘 이상 동시(시리즈마다 위쪽 콜 ≥ 아래쪽 풋×{dcp})'),
                                                  ('K2dcp', dom_ & cpm_, '둘 이상 동시(1위 압도 + 콜 우위 둘 다)')):
                                if ok_ in YO.get('kinds', []): kinds.append((ok_, om_, ol_)); okinds.add(ok_)
                            for cn, cm in ucond:
                                if cn not in YO.get('conds', [cn]): continue
                                for ol, om_ in (('1위 압도', dom_), ('1위 압도 아님', k2m & ~dom_), ('콜 우위', cpm_), ('콜 우위 아님', k2m & ~cpm_)):
                                    mm_ = om_ & cm.fillna(False)
                                    r_ = {'묶음': '+'.join(gtags), '폭': blab, '조건': cn, '까닭': ol}
                                    for pn_, pm_ in (('앞', (td <= L.DEV_END) & (td >= pd.Timestamp('2010-01-01'))), ('뒤', p2)):
                                        r_[f'{pn_} 날수'] = int((mm_ & pm_).sum())
                                        for m in YM:
                                            v_ = yfwd[m][mm_ & pm_].dropna(); r_[f'{pn_} {m}일 상승%'] = round(float((v_ > 0).mean() * 100), 1) if len(v_) else np.nan
                                    orows.append(r_)
                        # 라운드 46(kinds 에 K2up·K2dn 있을 때만): 콜 최대 자리가 '위로' 옮겨 갔나 — K2up 맞은 시리즈의 새 벽이 모두 옛 벽보다 위(만기 교체 없음),
                        #   K2dn 하나 이상이 옛 벽보다 아래로 옮겨 감. 가설 H13: 위로 옮겨 간 날만 상승 계속(포지션이 위로 굴러감), 아래로는 힘 없음.
                        if any(k_ in YO.get('kinds', []) for k_ in ('K2up', 'K2dn')):
                            nup = sum((hits[i].astype(bool) & orig_of[t]['up']).astype(int) for i, t in enumerate(gtags))
                            ndn = sum((hits[i].astype(bool) & orig_of[t]['down']).astype(int) for i, t in enumerate(gtags))
                            up_ = k2m & (nup == cnt); dn_ = k2m & (ndn >= 1)
                            for ok_, om_, ol_ in (('K2up', up_, '둘 이상 동시(모두 옛 벽보다 위로 옮겨 감)'),
                                                  ('K2dn', dn_, '둘 이상 동시(하나 이상 옛 벽보다 아래로 옮겨 감)')):
                                if ok_ in YO.get('kinds', []): kinds.append((ok_, om_, ol_)); okinds.add(ok_)
                            # 라운드 47(kinds 에 K2dnF·K2dnR·K2dnH 있을 때만, 없으면 없음 → 갈래 B·D 영향 없음): 라운드 46 에서 앞 구간은 '아래로 포함' 날이 3·5·7일 77~82% 로 고름.
                            #   H15 목표가 가까워짐 — 옛 벽까지 거리의 절반 이상(dn_half, 미리 정함 0.5)을 줄인 날이 더 맞음(K2dnH). H16 그날 지수가 내려서 기계적으로 생긴
                            #   이동이면 '눌림 반등' 몫 — 그날 지수 종가 하락(K2dnF)·상승·보합(K2dnR)으로 나눔. 모두 그날 장 마감 뒤 아는 값, 값 없는 날은 어느 쪽도 아님(추정 안 함).
                            if any(k_ in YO.get('kinds', []) for k_ in ('K2dnF', 'K2dnR', 'K2dnH')):
                                r1_ = k2['close'].reindex(td).pct_change()
                                dhf = float(YO.get('dn_half', 0.5))
                                nbig = sum((hits[i].astype(bool) & orig_of[t]['down'] & (orig_of[t]['dn_frac'] >= dhf).fillna(False)).astype(int)
                                           for i, t in enumerate(gtags))
                                dnF_ = dn_ & (r1_ < 0).fillna(False); dnR_ = dn_ & (r1_ >= 0).fillna(False); dnH_ = dn_ & (nbig >= 1)
                                for ok_, om_, ol_ in (('K2dnF', dnF_, '둘 이상 동시(하나 이상 아래로 옮겨 감 + 그날 지수 하락)'),
                                                      ('K2dnR', dnR_, '둘 이상 동시(하나 이상 아래로 옮겨 감 + 그날 지수 상승·보합)'),
                                                      ('K2dnH', dnH_, f'둘 이상 동시(하나 이상 옛 벽까지 거리의 {int(dhf * 100)}% 이상 아래로 옮겨 감)')):
                                    if ok_ in YO.get('kinds', []): kinds.append((ok_, om_, ol_)); okinds.add(ok_)
                                for cn, cm in ucond:
                                    if cn not in YO.get('conds', [cn]): continue
                                    for ol, om_ in (('아래로 + 그날 하락', dnF_), ('아래로 + 그날 상승·보합', dnR_),
                                                    (f'아래로 {int(dhf * 100)}% 이상', dnH_), (f'아래로 {int(dhf * 100)}% 미만', dn_ & ~dnH_)):
                                        mm_ = om_ & cm.fillna(False)
                                        r_ = {'묶음': '+'.join(gtags), '폭': blab, '조건': cn, '까닭': ol}
                                        for pn_, pm_ in (('앞', (td <= L.DEV_END) & (td >= pd.Timestamp('2010-01-01'))), ('뒤', p2)):
                                            r_[f'{pn_} 날수'] = int((mm_ & pm_).sum())
                                            for m in YM:
                                                v_ = yfwd[m][mm_ & pm_].dropna(); r_[f'{pn_} {m}일 상승%'] = round(float((v_ > 0).mean() * 100), 1) if len(v_) else np.nan
                                        orows.append(r_)
                            for cn, cm in ucond:
                                if cn not in YO.get('conds', [cn]): continue
                                for ol, om_ in (('모두 위로', up_), ('아래로 포함', dn_), ('그 밖(만기 교체 섞임)', k2m & ~up_ & ~dn_)):
                                    mm_ = om_ & cm.fillna(False)
                                    r_ = {'묶음': '+'.join(gtags), '폭': blab, '조건': cn, '까닭': ol}
                                    for pn_, pm_ in (('앞', (td <= L.DEV_END) & (td >= pd.Timestamp('2010-01-01'))), ('뒤', p2)):
                                        r_[f'{pn_} 날수'] = int((mm_ & pm_).sum())
                                        for m in YM:
                                            v_ = yfwd[m][mm_ & pm_].dropna(); r_[f'{pn_} {m}일 상승%'] = round(float((v_ > 0).mean() * 100), 1) if len(v_) else np.nan
                                    orows.append(r_)
                        # 설명표(날 단위, 겹침 포함, 후보 안 만듦): K2 날을 까닭으로 나눠 앞·뒤 m일 상승%.
                        lab4 = pd.Series('섞임', index=td)
                        lab4[k2m & (nro >= 1) & (ncr == 0)] = '만기 교체 포함'
                        lab4[k2m & (ncr >= 1)] = '넘어섬 포함'
                        lab4[k2m & (nsh == cnt)] = '모두 물량 이동'
                        for cn, cm in ucond:
                            if cn not in YO.get('conds', [cn]): continue
                            for ol in ('모두 물량 이동', '넘어섬 포함', '만기 교체 포함', '섞임'):
                                mm_ = k2m & cm.fillna(False) & (lab4 == ol)
                                r_ = {'묶음': '+'.join(gtags), '폭': blab, '조건': cn, '까닭': ol}
                                for pn_, pm_ in (('앞', (td <= L.DEV_END) & (td >= pd.Timestamp('2010-01-01'))), ('뒤', p2)):
                                    r_[f'{pn_} 날수'] = int((mm_ & pm_).sum())
                                    for m in YM:
                                        v_ = yfwd[m][mm_ & pm_].dropna(); r_[f'{pn_} {m}일 상승%'] = round(float((v_ > 0).mean() * 100), 1) if len(v_) else np.nan
                                orows.append(r_)
                    for uk, umask, ulab in kinds:
                        for cn, cm in ucond:
                            if uk in okinds and cn not in YO.get('conds', [cn]): continue
                            mall = umask & cm.fillna(False)
                            # 라운드 40(a04.young_barrier: {k, max_m, conds}, 설정 없으면 없음 → 갈래 B·D 영향 없음): 라운드 39 경로표에서 통과 계열의 앞 구간 상승 비율이
                            #   5일째만 85%·4·6일째 63% 로 뾰족 — 정해진 날 종가 대신 보유 기간에 덜 기대는 익절·손절(±k×1주 σ, 종가, 최대 max_m 일) 규칙으로도 맞는지.
                            # 라운드 47(young_barrier.kinds, 없으면 모든 종류 — 라운드 40 그대로): 익절·손절 후보를 정한 종류에만.
                            if YBAR and pxb is not None and cn in (YBAR.get('conds') or [cn]) and uk in (YBAR.get('kinds') or [uk]):
                                n1 = int((mall & dev).sum()); n2 = int((mall & p2).sum())
                                if n1 >= 20 or n2 >= 12:
                                    sig_b = td[mall.fillna(False).values]
                                    # 라운드 48(young_barrier.sl_mult·max_m_list, 없으면 [1.0]·[max_m] → 라운드 40·47 그대로): 손절 폭을 익절의 배수로 따로 두고(상승 후보만),
                                    #   최대 보유일도 여러 값. sl_mult ≠ 1 이면 id 에 s<배수> 를 붙여 예전 후보 이름은 그대로.
                                    for bk in YBAR.get('k', [1.0]):
                                      for mxm in [int(x) for x in (YBAR.get('max_m_list') or [YBAR.get('max_m', 10)])]:
                                        for slm in [float(x) for x in (YBAR.get('sl_mult') or [1.0])]:
                                          tb = pd.DataFrame({'signal': sig_b, 'exit': barrier_exits(pxb, sig_b, sig5 * bk, mxm, slm)}).dropna()
                                          sls = '' if slm == 1.0 else f's{slm:g}'
                                          for direction in ((-1, 1) if slm == 1.0 else (1,)):
                                            cands.append({'id': f'A4yb_{uk}_{"+".join(gtags)}_{ny}d_{bkey}_{cn}_b{bk}{sls}x{mxm}_{"dn" if direction < 0 else "up"}', 'agent': 'A4',
                                                          'family': 'young_barrier',
                                                          'desc': f'{glab} 중 {ulab} 새 콜벽(나이 {ny}일 이하) + 벽 바로 아래(±{blab})' + ('' if cn == '흐름 무관' else f' + {cn}') +
                                                                  (f' → ±{bk}σ 익절·손절' if slm == 1.0 else f' → +{bk}σ 익절·−{bk * slm:g}σ 손절') +
                                                                  f'(종가, 최대 {mxm}일) {"하락" if direction < 0 else "상승"}', 'direction': direction, 'trades': tb})
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
        if YO:
            pd.DataFrame(orows).to_csv(os.path.join(od, 'young_origin.csv'), index=False, encoding='utf-8')
            print('새 벽 까닭 설명표', len(orows), flush=True)
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
            ol = '5일'
            if tag in ('WT', 'WM'):
                # 갈래 B 라운드 41(zone_conds.tags 에 WT·WM 있을 때만, 설정 없으면 없음 → 갈래 A·D·예전 B 영향 없음): 통과 규칙(분기물 벽 바로 아래 + 벽 물량 증가 + 하루 늦춤)을
                #   위클리 콜벽으로 — 뒤 구간 사건을 늘리려고. 위클리 시리즈는 상장~만기 약 6거래일이라 5일 물량 변화를 같은 시리즈 안에서 셀 수 없음 →
                #   '벽 물량 전일 대비 증가'(같은 시리즈·같은 행사가의 어제 미결제약정보다 많음, 어제 그 시리즈가 없으면 빈칸 — 추정 안 함). 만기 조건은 없음.
                Wk = weekly_walls({'WT': 'wt', 'WM': 'wm'}[tag], k2, td)
                if Wk is None: print('위치 조건: 위클리 자료 없음', tag, flush=True); continue
                dist = Wk['dist%'].astype(float); dte = None; ol = '전일 대비'
                try:
                    cw = L.chain({'WT': 'wt', 'WM': 'wm'}[tag]); cw = cw[cw['cp'] == 'C']
                    oimap = {(str(e), float(k_), d_): float(o_) for e, k_, d_, o_ in zip(cw['exp'], cw['K'], pd.to_datetime(cw['date']), cw['oi'])}
                    ov = np.full(len(td), np.nan)
                    for i_ in range(1, len(td)):
                        e_, k_ = Wk['exp'].iloc[i_], Wk['K'].iloc[i_]
                        if not isinstance(e_, str) or not np.isfinite(k_): continue
                        a_ = oimap.get((e_, float(k_), td[i_])); b_ = oimap.get((e_, float(k_), td[i_ - 1]))
                        if a_ is not None and b_ is not None: ov[i_] = a_ - b_
                    oi5 = pd.Series(ov, index=td)
                    print('위클리 벽 물량 전일 대비', tag, '값 있는 날', int(np.isfinite(ov).sum()), '· 증가', int((ov > 0).sum()), flush=True)
                except Exception as e:
                    print('위클리 벽 물량 실패', tag, repr(e), flush=True); oi5 = None
            else:
                dist = X.get(f'OW_{tag}_wall_dist%'); dte = X.get(f'OW_{tag}_dte'); oi5 = X.get(f'OW_{tag}_wall_oi_chg5%')
            if dist is None: continue
            conds = [('다음 날 시가→종가 하락 뒤 진입', dn_oc_next, True), ('다음 날 종가 하락 뒤 진입', dn_cc_next, True),
                     ('하루 늦춰 진입', pd.Series(True, index=td), True),
                     ('직전 5일 하락', r5 < 0, False), ('직전 5일 상승', r5 > 0, False)]
            if dte is not None:
                conds += [('만기 10거래일 이내', dte <= 10, False), ('만기 11~30거래일', (dte >= 11) & (dte <= 30), False), ('만기 31거래일 이상', dte >= 31, False)]
            if oi5 is not None:
                conds += [(f'벽 물량 {ol} 증가', oi5 > 0, False), (f'벽 물량 {ol} 감소', oi5 < 0, False)]
                # 라운드 14(zone_conds.combo): 라운드 13 에서 뒤 구간을 가장 올린 두 조건(하루 늦춤·벽 물량 5일 증가)을 함께
                if zc.get('combo'): conds += [(f'벽 물량 {ol} 증가 + 하루 늦춰 진입', oi5 > 0, True)]
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
                for cn0, cm, delay in conds_b:
                  mall = (zm & cm).fillna(False).values
                  idx0 = np.where(mall)[0] + (1 if delay else 0)
                  idx0 = idx0[idx0 < len(td)]
                  # 갈래 B 라운드 29(zone_conds.first_n: {n, bands, conds}, 없으면 그대로 → 갈래 A 영향 없음): 라운드 28 에서 합친 신호를 '첫 신호만'으로 하자
                  #   앞 독립 거래 33개 79% → 21개 81% — 같은 정의를 거래가 더 많은 위치 신호(±1.5% 등)에도. 직전 n 거래일 안 같은 신호 없는 날만(n 미리 정함).
                  fcfg = zc.get('first_n') or {}
                  variants = [(cn0, idx0)]
                  if fcfg and str(band_key) in [str(b) for b in fcfg.get('bands', [])] and cn0 in (fcfg.get('conds') or []) and len(idx0):
                      fnn = int(fcfg.get('n', 5))
                      idx_f = idx0[np.r_[True, np.diff(idx0) > fnn]]
                      variants.append((f'{cn0} + 첫 신호만({fnn}일)', idx_f))
                      # 갈래 B 라운드 31(first_n.probe_bands·probe_n·r20_lt, 설정 없으면 그대로 → 예전과 같음):
                      #   (1) 견고성 — 같은 '첫 신호만'을 n 만 바꿔(probe_n, 미리 정한 3·10일) 결과가 n=5 에만 기대는지 봄(이웃 변형).
                      #   (2) 과열 가설 — 라운드 30 설명표에서 빗나감이 직전 20일 많이 오른 뒤(6.9% vs 4.1%)에 조금 더 많음 →
                      #       첫 신호만(n) 날 중 직전 20일 코스피200 수익(그날 종가까지 아는 값)이 r20_lt% 미만인 날만(문턱 5% 미리 정함, A 라운드 35 설명표와 같은 값).
                      if str(band_key) in [str(b) for b in fcfg.get('probe_bands', fcfg.get('bands', []))]:
                          for pn in (fcfg.get('probe_n') or []):
                              pn = int(pn)
                              if pn != fnn: variants.append((f'{cn0} + 첫 신호만({pn}일)', idx0[np.r_[True, np.diff(idx0) > pn]]))
                          if fcfg.get('r20_lt') is not None:
                              r20v = (c1 / c1.shift(20) - 1).values * 100
                              keep_ = np.array([np.isfinite(r20v[i_]) and r20v[i_] < float(fcfg['r20_lt']) for i_ in idx_f], dtype=bool)
                              variants.append((f"{cn0} + 첫 신호만({fnn}일) + 직전 20일 {fcfg['r20_lt']}% 미만", idx_f[keep_]))
                      # 갈래 B 라운드 35(first_n.confirm, 설정 없으면 없음 → 갈래 A·D 영향 없음): 라운드 34 경로표에서 앞 구간 빗나감 6거래는 진입 첫날부터 모두 내림
                      #   (1일째 상승 0%, 맞음 27거래는 74%) — '처음부터 안 감'을 거르면 보유 기간에 덜 기대나(가설 H4). 첫 신호만(n) 신호일 i 의 다음 날(원래 진입일 i+1)
                      #   지수 종가 > 시가(그날 마감 뒤 아는 값)이면 i+1 을 새 신호일로(진입 i+2 시가), 대조로 종가 < 시가인 날도 따로. 값·정의는 미리 정함(문턱 없음).
                      if fcfg.get('confirm'):
                          cv_ = k2['close'].values; ov_ = k2['open'].values
                          j_ = idx_f[idx_f + 1 < len(td)] + 1
                          variants.append((f'{cn0} + 첫 신호만({fnn}일) + 다음 날 양봉 확인', j_[cv_[j_] > ov_[j_]]))
                          variants.append((f'{cn0} + 첫 신호만({fnn}일) + 다음 날 음봉 뒤', j_[cv_[j_] < ov_[j_]]))
                  for cn, idx in variants:
                    sig = td[idx]
                    # 갈래 B 라운드 30(first_n.table, 설명용 — 후보 안 만듦): 첫 신호만 변형의 독립 거래(3일)마다 그날 아는 지표 — 손실 거래(앞 구간 약한 해)가 무엇이 다른지
                    #   라운드 31: 같은 파일 이름을 덮어쓰지 않게 기본 n 변형에서만 만듦.
                    if fcfg.get('table') and cn == f"{cn0} + 첫 신호만({int(fcfg.get('n', 5))}일)" and cn0 == (fcfg.get('conds') or [cn0])[0] and len(sig):   # 라운드 42: 덧조건 변형이 같은 파일을 덮지 않게 첫 조건만
                        try:
                            mt = int(fcfg.get('table_m', 3))
                            ind_ = L.thin(list(sig), mt, td)
                            c_ = k2['close']; rv_ = c_.pct_change().rolling(20).std()
                            rvp_ = rv_.rolling(250, min_periods=120).apply(lambda a: (a[:-1] < a[-1]).mean() * 100 if len(a) > 1 else np.nan, raw=True)
                            ma60_ = c_.rolling(60).mean(); r20_ = c_ / c_.shift(20) - 1
                            ff3 = F['fut_for'].rolling(3).sum() if 'fut_for' in F else None
                            fxr = (c_.shift(-mt) / k2['open'].shift(-1) - 1) * 100
                            trows = []
                            for d_ in ind_:
                                sd = td[max(0, td.get_loc(d_) - (1 if delay else 0))]   # 늦춤이면 벽 지표는 위치가 켜진 날(t) 값
                                trows.append({'날짜': d_.date(), '구간': 'P1' if d_ <= L.DEV_END else 'P2', '해': d_.year,
                                              f'{mt}일 수익%(지수)': fxr.get(d_, np.nan), '20일 변동성 분위': rvp_.get(d_, np.nan),
                                              '60일선 위': bool(c_.get(d_, np.nan) > ma60_.get(d_, np.nan)), '직전 20일 수익%': r20_.get(d_, np.nan) * 100,
                                              '벽 거리%(t)': dist.get(sd, np.nan), '만기까지 거래일(t)': dte.get(sd, np.nan) if dte is not None else np.nan,
                                              '벽 물량 5일 변화%(t)': oi5.get(sd, np.nan) if oi5 is not None else np.nan,
                                              '외국인 선물 3일 누적(t)': ff3.get(sd, np.nan) if ff3 is not None else np.nan})
                            TT = pd.DataFrame(trows)
                            TT.round(2).to_csv(os.path.join(od, f'zone_first_trades_{tag}_{band_key}.csv'), index=False, encoding='utf-8')
                            rc = f'{mt}일 수익%(지수)'
                            if len(TT):
                                TT['적중'] = TT[rc] > 0
                                num = [c for c in TT.columns if c not in ('날짜', '구간', '해', '적중', '60일선 위')]
                                g = TT.groupby(['구간', '적중'])[num + ['60일선 위']].mean(numeric_only=False).round(2)
                                g['수'] = TT.groupby(['구간', '적중']).size()
                                g.to_csv(os.path.join(od, f'zone_first_trades_summary_{tag}_{band_key}.csv'), encoding='utf-8')
                            # 갈래 B 라운드 34(first_n.expiry_table, 설명용 — 후보 안 만듦 → A8 나눗수 그대로, 설정 없으면 없음 → 갈래 A·D 영향 없음):
                            #   라운드 33 에서 통과 규칙이 같은 날짜로 3일 보유에만 86%(2일 63%·5일 78%) — 만기 달력·요일과 겹쳐서인지(가설 H2).
                            #   독립 거래(mt일 기준)마다 진입 요일, 보유 첫날~mt째 날 안 월물 만기(둘째 목, 휴장이면 앞 거래일)가 몇째 날인지(없으면 0),
                            #   그 만기가 분기(3·6·9·12월)인지, 진입일→다음 월물 만기 거래일 수, 같은 진입의 1·2·3·5일 지수 수익. 끝이 자료 밖이면 빈칸.
                            if fcfg.get('expiry_table') and len(TT):
                                mons = pd.period_range(td[0], td[-1] + pd.Timedelta(days=45), freq='M')
                                exps = pd.DatetimeIndex(sorted({L.expiry_of_ym(f'{p_.year}{p_.month:02d}', td) for p_ in mons}))
                                c_ = k2['close']; o_ = k2['open']; exrows_ = []
                                for d_ in ind_:
                                    i_ = td.get_loc(d_)
                                    if i_ + 1 >= len(td): continue
                                    ent = td[i_ + 1]
                                    r = {'날짜': d_.date(), '구간': 'P1' if d_ <= L.DEV_END else 'P2', '진입일': ent.date(), '진입 요일': '월화수목금'[ent.weekday()]}
                                    for k_ in (1, 2, 3, 5):
                                        r[f'{k_}일%'] = round((float(c_.iloc[i_ + k_]) / float(o_.iloc[i_ + 1]) - 1) * 100, 3) if i_ + k_ < len(td) else np.nan
                                    nx = exps[exps >= ent]
                                    nxt = nx[0] if len(nx) else pd.NaT
                                    r['진입→다음 월물 만기 거래일'] = (L.tdays_between(ent, nxt, td) if pd.notna(nxt) else np.nan)
                                    hold = list(td[i_ + 1:i_ + 1 + mt])
                                    r['보유 중 월물 만기(몇째 날)'] = (hold.index(nxt) + 1) if (pd.notna(nxt) and nxt in hold) else 0
                                    r['그 만기가 분기'] = bool(r['보유 중 월물 만기(몇째 날)'] > 0 and nxt.month in (3, 6, 9, 12))
                                    exrows_.append(r)
                                EX = pd.DataFrame(exrows_)
                                EX.to_csv(os.path.join(od, f'zone_first_expiry_{tag}_{band_key}.csv'), index=False, encoding='utf-8')
                                srows_ = []
                                if len(EX):
                                    EX['만기 칸'] = np.where(EX['보유 중 월물 만기(몇째 날)'] > 0, '보유 중 만기 ' + EX['보유 중 월물 만기(몇째 날)'].astype(str) + '째 날', '보유 중 만기 없음')
                                    EX['다음 만기까지 칸'] = pd.cut(EX['진입→다음 월물 만기 거래일'], [-1, 2, 5, 10, 40], labels=['0~2일', '3~5일', '6~10일', '11일+']).astype(str)
                                    for per in ('P1', 'P2', '전체'):
                                        G = EX if per == '전체' else EX[EX['구간'] == per]
                                        for col in ('만기 칸', '그 만기가 분기', '진입 요일', '다음 만기까지 칸'):
                                            for val, gg in G.groupby(col):
                                                rr = {'구간': per, '나눔': col, '칸': str(val), '거래': len(gg), '표본 주의': '10 미만' if len(gg) < 10 else ''}
                                                for k_ in (1, 2, 3, 5):
                                                    v_ = gg[f'{k_}일%'].dropna()
                                                    rr[f'{k_}일 상승%'] = round(float((v_ > 0).mean() * 100), 1) if len(v_) else np.nan
                                                    rr[f'{k_}일 평균%'] = round(float(v_.mean()), 2) if len(v_) else np.nan
                                                srows_.append(rr)
                                pd.DataFrame(srows_).to_csv(os.path.join(od, f'zone_first_expiry_summary_{tag}_{band_key}.csv'), index=False, encoding='utf-8')
                                print('만기·요일 설명표', tag, band_key, len(EX), flush=True)
                        except Exception as e:
                            print('첫 신호 설명표 실패', repr(e), flush=True)
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
                                      'desc': f'{WLAB.get(tag, tag)} 벽 바로 아래(±{band_lab}), 흐름 무관' + ('' if cn == '조건 없음' else f' + {cn}') + f' → {m}일 {"하락" if direction < 0 else "상승"}',
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
    # 갈래 A 라운드 35(a04.prereg_table: {ids}, 설정 없으면 없음 → 갈래 B 영향 없음, 후보 안 만듦 → A8 나눗수 그대로): 두 앞→뒤 통과 후보가
    #   왜 앞 구간(특히 2010~2014·2011·2014·2022)에서 약하고 뒤→앞 확인 p 가 모자라는지 — 독립 거래마다 그날 장 마감 뒤 아는 지표와 적중/빗나감.
    #   가설 H1(변동성 장세): 빗나감은 20일 변동성 분위가 높은 날(위기·급변 장)에 몰림. H2(과열): 빗나감은 직전 20일 많이 오른 뒤(갈래 B 라운드 30 과 같은 물음).
    #   나눔 문턱은 미리 정함(변동성 분위 50, 직전 20일 5%, 60일선) — 결과 보고 고른 값 아님. 설명용, 새 후보로 쓰지 않음.
    ptc = cfg.get('prereg_table')
    if ptc:
        try:
            try: pxt = L.prices()['K200F']
            except Exception as e: print('선물 가격 못 읽음, 지수로', repr(e)); pxt = k2
            c_ = k2['close']; rv_ = c_.pct_change().rolling(20).std()
            rvp_ = rv_.rolling(250, min_periods=120).apply(lambda a: (a[:-1] < a[-1]).mean() * 100 if len(a) > 1 else np.nan, raw=True)
            ma60_ = c_.rolling(60).mean(); r20_ = c_ / c_.shift(20) - 1; r5_ = c_ / c_.shift(5) - 1
            f3_ = F['fut_for'].rolling(3, min_periods=3).sum(); s3_ = F['cash_for'].rolling(3, min_periods=3).sum()
            pct = lambda s: s.rolling(250, min_periods=120).apply(lambda a: (a[:-1] < a[-1]).mean() * 100 if len(a) > 1 else np.nan, raw=True)
            f3p_, s3p_ = pct(f3_), pct(s3_)
            dteF0 = X.get('OW_F0_dte'); dF0 = X.get('OW_F0_wall_dist%')
            byid = {c['id']: c for c in cands}; trows = []
            for pid in ptc.get('ids', []):
                c = byid.get(pid)
                if c is None: trows.append({'id': pid, '구간': '후보 없음'}); continue
                tr = c['trades'].assign(signal=lambda d: pd.to_datetime(d['signal']), exit=lambda d: pd.to_datetime(d['exit'])).dropna().sort_values('signal')
                keep = []; last = pd.Timestamp('1900-01-01')
                for s_, e_ in zip(tr['signal'], tr['exit']):   # A8 independent() 와 같은 규칙(전 기간 한 줄로)
                    if s_ >= last: keep.append((s_, e_)); last = e_
                tt = pd.DataFrame(keep, columns=['signal', 'exit'])
                if not len(tt): continue
                ret = L.trade_returns(tt, pxt)
                for (s_, e_), r_ in zip(keep, ret):
                    if r_ != r_: continue
                    trows.append({'id': pid, '신호일': s_.date(), '해': s_.year,
                                  '구간': '2010~2014' if s_.year <= 2014 else ('2015~2023' if s_ <= L.DEV_END else '2024~'),
                                  '수익%(선물)': round(float(r_), 2), '적중': bool(c['direction'] * r_ > 0),
                                  '20일 변동성 분위': rvp_.get(s_, np.nan), '60일선 위': bool(c_.get(s_, np.nan) > ma60_.get(s_, np.nan)),
                                  '직전 20일 수익%': r20_.get(s_, np.nan) * 100, '직전 5일 수익%': r5_.get(s_, np.nan) * 100,
                                  '외국인 선물 3일 누적': f3_.get(s_, np.nan), '외국인 선물 3일 분위': f3p_.get(s_, np.nan),
                                  '외국인 현물 3일 누적': s3_.get(s_, np.nan), '외국인 현물 3일 분위': s3p_.get(s_, np.nan),
                                  '근월 벽 거리%': dF0.get(s_, np.nan) if dF0 is not None else np.nan,
                                  '근월 만기까지 거래일': dteF0.get(s_, np.nan) if dteF0 is not None else np.nan})
            T = pd.DataFrame(trows)
            T.round(2).to_csv(os.path.join(od, 'prereg_trades.csv'), index=False, encoding='utf-8')
            srows = []
            if len(T) and '적중' in T:
                T = T[T['적중'].notna()].copy()
                num = ['수익%(선물)', '20일 변동성 분위', '직전 20일 수익%', '직전 5일 수익%', '외국인 선물 3일 분위', '외국인 현물 3일 분위', '근월 벽 거리%', '근월 만기까지 거래일']
                for (pid, per, hit), g in T.groupby(['id', '구간', '적중']):
                    r = {'id': pid, '나눔': '적중/빗나감 평균', '구간': per, '칸': '적중' if hit else '빗나감', '거래': len(g), '60일선 위%': round(g['60일선 위'].mean() * 100, 1)}
                    r.update({k: round(float(g[k].mean()), 2) for k in num if k in g})
                    srows.append(r)
                splits = [('20일 변동성 분위', lambda d: np.where(d['20일 변동성 분위'] > 50, '높음(>50)', np.where(d['20일 변동성 분위'].notna(), '낮음(≤50)', None))),
                          ('직전 20일 수익', lambda d: np.where(d['직전 20일 수익%'] >= 5, '5% 이상', np.where(d['직전 20일 수익%'].notna(), '5% 미만', None))),
                          ('60일선', lambda d: np.where(d['60일선 위'], '위', '아래'))]
                for sn, fn in splits:
                    T['_c'] = fn(T)
                    for per_lab, sub in (('앞 2010~2023', T[T['구간'] != '2024~']), ('뒤 2024~', T[T['구간'] == '2024~']), ('2010~2014', T[T['구간'] == '2010~2014'])):
                        for (pid, cc), g in sub.dropna(subset=['_c']).groupby(['id', '_c']):
                            n = len(g); k = int(g['적중'].sum())
                            srows.append({'id': pid, '나눔': sn, '구간': per_lab, '칸': cc, '거래': n,
                                          '적중%': round(k / n * 100, 1) if n else np.nan, '하한%': round(L.wilson(k, n)[0] * 100, 1) if n else np.nan,
                                          '평균 수익%': round(float(g['수익%(선물)'].mean()), 2), '표본 주의': '10 미만' if n < 10 else ''})
            pd.DataFrame(srows).to_csv(os.path.join(od, 'prereg_trades_summary.csv'), index=False, encoding='utf-8')
            print('사전 등록 거래 설명표', len(T), '거래 ·', len(srows), '칸', flush=True)
        except Exception as e:
            print('사전 등록 거래 설명표 실패', repr(e), flush=True)
    # 갈래 A 라운드 39(a04.path_table: {ids, tags}, 설정 없으면 없음 → 갈래 B·D 영향 없음, 후보 안 만듦 → A8 나눗수 그대로): 라운드 38 에서 통과 계열이
    #   보유 5일에만 85% 를 넘고 3·7일은 69~80% — 날별 경로로 이유를 봄. 독립 거래(A8 규칙)마다 진입(다음 날 시가, 연속 선물) 대비 1~10일째 종가 누적 수익,
    #   신호날 가장 가까운 새 벽(묶음 시리즈 중 나이 1일·현재가 위, 지수 단위)에 1~5일 안 고가로 닿음·종가로 넘음, 5→7·5→10일 되밀림,
    #   외국인 선물 1~5일·6~10일 누적(넘은 뒤 파나 — 가설 뒷부분). 경로 끝이 자료 밖이면 빈칸(추정 안 함).
    pth = cfg.get('path_table')
    if pth:
        try:
            try: pxp = L.prices()['K200F']
            except Exception as e: print('선물 가격 못 읽음, 지수로', repr(e)); pxp = k2
            ptags = [t for t in pth.get('tags', ['F0', 'F1', 'F2', 'ALL']) if t in age_of and X.get(f'OW_{t}_wall_dist%') is not None]
            newd = pd.concat([X[f'OW_{t}_wall_dist%'].where((age_of[t] <= 1) & (X[f'OW_{t}_wall_dist%'] > 0)) for t in ptags], axis=1).min(axis=1) if ptags else None
            ffp = F['fut_for']; byid = {c['id']: c for c in cands}; prow = []
            tdl = list(td); pos = {d: i for i, d in enumerate(tdl)}
            for pid in pth.get('ids', []):
                c = byid.get(pid)
                if c is None: prow.append({'id': pid, '구간': '후보 없음'}); continue
                tr = c['trades'].assign(signal=lambda d: pd.to_datetime(d['signal']), exit=lambda d: pd.to_datetime(d['exit'])).dropna().sort_values('signal')
                keep = []; last = pd.Timestamp('1900-01-01')
                for s_, e_ in zip(tr['signal'], tr['exit']):
                    if s_ >= last: keep.append(s_); last = e_
                for s_ in keep:
                    i = pos.get(s_)
                    if i is None or i + 1 >= len(tdl): continue
                    ent_d = tdl[i + 1]
                    if ent_d not in pxp.index: continue
                    o = float(pxp['open'].loc[ent_d])
                    r = {'id': pid, '신호일': s_.date(), '구간': '2010~2014' if s_.year <= 2014 else ('2015~2023' if s_ <= L.DEV_END else '2024~')}
                    for k in range(1, 11):
                        dk = tdl[i + k] if i + k < len(tdl) else None
                        r[f'{k}일%'] = round((float(pxp['close'].loc[dk]) / o - 1) * 100, 3) if dk is not None and dk in pxp.index else np.nan
                    # 갈래 B 라운드 34: 적중 기준일을 설정으로(path_table.hit_day, 없으면 5 → 갈래 A 그대로). 칸 이름은 그대로 '적중(5일)'(A 결과와 같은 파일 모양).
                    hdv = r[f"{int(pth.get('hit_day', 5))}일%"]
                    r['적중(5일)'] = (hdv > 0) if hdv == hdv else np.nan
                    nd = float(newd.get(s_, np.nan)) if newd is not None else np.nan
                    r['새 벽 거리%'] = round(nd, 2) if nd == nd else np.nan
                    if nd == nd and i + 5 < len(tdl):
                        Kw = float(k2['close'].loc[s_]) * (1 + nd / 100)
                        w5 = tdl[i + 1:i + 6]
                        r['5일 안 고가로 닿음'] = bool((k2['high'].reindex(w5) >= Kw).any()) if 'high' in k2 else np.nan
                        r['5일 안 종가로 넘음'] = bool((k2['close'].reindex(w5) > Kw).any())
                        r['5일째 종가가 벽 위'] = bool(float(k2['close'].loc[tdl[i + 5]]) > Kw)
                    r['5→7일%'] = round(r['7일%'] - r['5일%'], 3) if r['7일%'] == r['7일%'] and r['5일%'] == r['5일%'] else np.nan
                    r['5→10일%'] = round(r['10일%'] - r['5일%'], 3) if r['10일%'] == r['10일%'] and r['5일%'] == r['5일%'] else np.nan
                    r['외국인 선물 1~5일 합'] = float(ffp.iloc[i + 1:i + 6].sum()) if i + 5 < len(tdl) and ffp.iloc[i + 1:i + 6].notna().all() else np.nan
                    r['외국인 선물 6~10일 합'] = float(ffp.iloc[i + 6:i + 11].sum()) if i + 10 < len(tdl) and ffp.iloc[i + 6:i + 11].notna().all() else np.nan
                    prow.append(r)
            P = pd.DataFrame(prow); P.to_csv(os.path.join(od, 'path_trades.csv'), index=False, encoding='utf-8')
            srows = []
            if len(P) and '1일%' in P:
                P = P[P['1일%'].notna()].copy()
                P['앞뒤'] = np.where(P['구간'] == '2024~', '뒤 2024~', '앞 2010~2023')
                for (pid, per), g in P.groupby(['id', '앞뒤']):
                    for sub_lab, sub in (('전체', g), (f"{int(pth.get('hit_day', 5))}일 적중", g[g['적중(5일)'] == True]), (f"{int(pth.get('hit_day', 5))}일 빗나감", g[g['적중(5일)'] == False])):   # noqa: E712
                        if not len(sub): continue
                        r = {'id': pid, '구간': per, '칸': sub_lab, '거래': len(sub), '표본 주의': '10 미만' if len(sub) < 10 else ''}
                        for k in range(1, 11):
                            v = sub[f'{k}일%'].dropna()
                            r[f'{k}일 평균%'] = round(float(v.mean()), 2) if len(v) else np.nan
                            r[f'{k}일 상승%'] = round(float((v > 0).mean() * 100), 1) if len(v) else np.nan
                        for col in ('5일 안 고가로 닿음', '5일 안 종가로 넘음', '5일째 종가가 벽 위'):
                            if col in sub: v = sub[col].dropna(); r[col + '%'] = round(float(v.astype(float).mean() * 100), 1) if len(v) else np.nan
                        for col in ('5→7일%', '5→10일%'):
                            v = sub[col].dropna(); r[col.replace('%', '') + ' 평균%'] = round(float(v.mean()), 2) if len(v) else np.nan
                            r[col.replace('%', '') + ' 하락%'] = round(float((v < 0).mean() * 100), 1) if len(v) else np.nan
                        for col in ('외국인 선물 1~5일 합', '외국인 선물 6~10일 합'):
                            v = sub[col].dropna(); r[col + ' 순매도%'] = round(float((v < 0).mean() * 100), 1) if len(v) else np.nan
                        srows.append(r)
                # 벽 넘음 여부로 나눈 5→10일(가설 뒷부분: 벽 위로 올린 뒤 파나)
                if '5일째 종가가 벽 위' in P:
                    for (pid, per, ab), g in P.dropna(subset=['5일째 종가가 벽 위']).groupby(['id', '앞뒤', '5일째 종가가 벽 위']):
                        v = g['5→10일%'].dropna(); f2 = g['외국인 선물 6~10일 합'].dropna()
                        srows.append({'id': pid, '구간': per, '칸': '5일째 벽 위' if ab else '5일째 벽 아래', '거래': len(g), '표본 주의': '10 미만' if len(g) < 10 else '',
                                      '5→10일 평균%': round(float(v.mean()), 2) if len(v) else np.nan, '5→10일 하락%': round(float((v < 0).mean() * 100), 1) if len(v) else np.nan,
                                      '외국인 선물 6~10일 합 순매도%': round(float((f2 < 0).mean() * 100), 1) if len(f2) else np.nan})
            pd.DataFrame(srows).to_csv(os.path.join(od, 'path_summary.csv'), index=False, encoding='utf-8')
            # 갈래 B 라운드 36(path_table.hold_placebo: {n, seed}, 설정 없으면 없음 → 갈래 A·D 영향 없음, 후보 안 만듦): 가설 H3 '3일 82% 는 보유 기간 고르기 몫'.
            #   같은 구간(앞 2010~2023·뒤 2024~)의 아무 날을 같은 거래 수만큼 n 번 뽑아(진입 다음 날 시가, 같은 선물 가격) 1~10일째 상승 비율을 내고,
            #   (가) 그중 가장 높은 보유일의 비율(10개 중 최대)이 실제 최대 이상인 비율 = '보유 기간 고르기까지 셈한 p', (나) 3일째만 본 p, (다) 아무 날 최대의 평균.
            hp = pth.get('hold_placebo')
            if hp and len(P):
                cl_ = pxp['close'].reindex(td).values.astype(float); op_ = pxp['open'].reindex(td).values.astype(float)
                nT = len(td); K_ = 10
                Rm = np.full((nT, K_), np.nan)
                ii = np.arange(nT)
                for k_ in range(1, K_ + 1):
                    ok_ = ii + k_ < nT
                    Rm[ok_, k_ - 1] = cl_[ii[ok_] + k_] / op_[np.minimum(ii[ok_] + 1, nT - 1)] - 1
                full_ = np.isfinite(Rm).all(axis=1)
                rng = np.random.default_rng(int(hp.get('seed', 34)))
                nd_ = int(hp.get('n', 2000)); hrows = []
                for (pid, per), g in P.groupby(['id', '앞뒤']):
                    real = np.array([float((g[f'{k}일%'].dropna() > 0).mean()) for k in range(1, K_ + 1)])
                    nsig = int(g['1일%'].notna().sum())
                    if nsig < 5 or not np.isfinite(real).all(): continue
                    inper = (td <= L.DEV_END) & (td >= pd.Timestamp('2010-01-01')) if per.startswith('앞') else (td >= L.HOLD_START)
                    pool = np.where(full_ & np.asarray(inper))[0]
                    if len(pool) < nsig * 3: continue
                    mx = np.empty(nd_); k3 = np.empty(nd_); allk = np.empty((nd_, K_))
                    for b_ in range(nd_):
                        pick = rng.choice(pool, nsig, replace=False)
                        up_ = (Rm[pick] > 0).mean(axis=0); allk[b_] = up_; mx[b_] = up_.max(); k3[b_] = up_[2]
                    hrows.append({'id': pid, '구간': per, '거래': nsig, '표본 주의': '10 미만' if nsig < 10 else '',
                                  '실제 최고 보유일': int(real.argmax() + 1), '실제 최고 상승%': round(real.max() * 100, 1), '실제 3일 상승%': round(real[2] * 100, 1),
                                  '아무 날 1~10일 평균 상승%': round(float(allk.mean()) * 100, 1), '아무 날 최대의 평균%': round(float(mx.mean()) * 100, 1),
                                  '아무 날 최대 95% 점%': round(float(np.quantile(mx, 0.95)) * 100, 1),
                                  'p(고르기 셈, 최대≥실제 최대)': round(float((mx >= real.max() - 1e-12).mean()), 4),
                                  'p(3일만, ≥실제 3일)': round(float((k3 >= real[2] - 1e-12).mean()), 4),
                                  '실제 1~10일 중 아무 날 95% 점 넘는 날 수': int((real > np.quantile(allk, 0.95, axis=0)).sum()), '뽑기': nd_})
                pd.DataFrame(hrows).to_csv(os.path.join(od, 'path_hold_placebo.csv'), index=False, encoding='utf-8')
                print('보유 기간 고르기 위약', len(hrows), flush=True)
            # 갈래 B 라운드 37(path_table.family_placebo: {prefixes, min_n_p1, min_n_p2, gap}, 설정 없으면 없음 → 갈래 A·D 영향 없음, 후보 안 만듦 → A8 나눗수 그대로):
            #   라운드 36 위약은 '보유일 고르기'만 셈함 → 이번엔 같은 가족(이번 A4 의 Q 위치·흐름·조건·합친 신호 후보, 이름이 _m<보유일> 로 끝나는 것) 전체를 고른 몫까지.
            #   구간(앞 2010~2023·뒤 2024~)마다 가족 모든 후보의 독립 거래 신호일을 '같은 거래일 수만큼 함께' 돌려 옮김(원형 이동, 모든 이동량을 다 셈 — 무작위 아님).
            #   후보끼리의 겹침·신호 몰림 모양은 그대로 두고 날짜와 값의 연결만 끊음. 이동마다 (가) 각 후보 자기 보유일 적중의 가족 최대, (나) 1~10일 중 최고까지의 가족 최대.
            #   실제 가족 최대(이동 0)·통과 규칙 각자의 적중이 그 분포에서 어디인지 = 가족 단위 p. 표본 기준(앞 min_n_p1, 뒤 min_n_p2) 미만 후보는 최대에서 뺌(고를 수 없던 후보).
            fp_ = pth.get('family_placebo')
            if fp_:
                try:
                    import re as _re
                    cl2 = pxp['close'].reindex(td).values.astype(float); op2 = pxp['open'].reindex(td).values.astype(float)
                    nT2 = len(td); K2_ = 10; ii2 = np.arange(nT2)
                    Rf = np.full((nT2, K2_), np.nan, dtype=np.float32)
                    for k_ in range(1, K2_ + 1):
                        ok_ = ii2 + k_ < nT2
                        Rf[ok_, k_ - 1] = cl2[ii2[ok_] + k_] / op2[np.minimum(ii2[ok_] + 1, nT2 - 1)] - 1
                    pfx = tuple(fp_.get('prefixes', ['A4zc_Q_', 'A4zu_', 'A4_Q_']))
                    gap = int(fp_.get('gap', 20)); tdv = pd.DatetimeIndex(td)
                    pers = {'앞 2010~2023': (tdv >= pd.Timestamp('2010-01-01')) & (tdv <= L.DEV_END), '뒤 2024~': tdv >= L.HOLD_START}
                    minn = {'앞 2010~2023': int(fp_.get('min_n_p1', 20)), '뒤 2024~': int(fp_.get('min_n_p2', 12))}
                    mem = []
                    for c in cands:
                        mm = _re.search(r'_m(\d+)$', str(c['id']))
                        if not str(c['id']).startswith(pfx) or mm is None or int(mm.group(1)) > K2_: continue
                        tr = c['trades'].assign(signal=lambda d: pd.to_datetime(d['signal']), exit=lambda d: pd.to_datetime(d['exit'])).dropna().sort_values('signal')
                        keep = []; last = pd.Timestamp('1900-01-01')
                        for s_, e_ in zip(tr['signal'], tr['exit']):
                            if s_ >= last: keep.append(s_); last = e_
                        ps = np.array([pos[s_] for s_ in keep if s_ in pos], dtype=int)
                        mem.append((c['id'], int(mm.group(1)), int(c.get('direction', 1) or 1), ps))
                    frows = []; mrows = []
                    for per, msk in pers.items():
                        idx = np.where(msk)[0]
                        if not len(idx): continue
                        a_, b_ = int(idx[0]), int(idx[-1]); Lp = b_ - a_ + 1
                        S = np.arange(0, Lp, dtype=int); S = S[(S == 0) | ((S >= gap) & (S <= Lp - gap))]
                        famA = np.full(len(S), -1.0); famB = np.full(len(S), -1.0); who = []; nmem = 0
                        for (cid, m_, dr_, ps) in mem:
                            pp = ps[(ps >= a_) & (ps <= b_)]
                            if len(pp) < minn[per]: continue
                            NI = a_ + (pp[None, :] - a_ + S[:, None]) % Lp
                            Rk = Rf[NI] * dr_                                   # (이동, 거래, 보유일)
                            fin = np.isfinite(Rk)
                            up = np.where(fin, Rk > 0, False).sum(axis=1) / np.maximum(fin.sum(axis=1), 1)
                            up = np.where(fin.sum(axis=1) >= minn[per], up, np.nan)
                            hA = up[:, m_ - 1]; hB = np.nanmax(up, axis=1)
                            famA = np.fmax(famA, np.nan_to_num(hA, nan=-1.0)); famB = np.fmax(famB, np.nan_to_num(hB, nan=-1.0))
                            nmem += 1
                            mrows.append({'id': cid, '구간': per, '거래': int(fin[0, :, m_ - 1].sum()), '보유일': m_, '실제 적중%': round(float(hA[0]) * 100, 1) if hA[0] == hA[0] else np.nan,
                                          '실제 1~10일 최고%': round(float(hB[0]) * 100, 1) if hB[0] == hB[0] else np.nan})
                        if not nmem: continue
                        rA, rB = famA[0], famB[0]; dA, dB = famA[1:], famB[1:]
                        M = pd.DataFrame([r for r in mrows if r['구간'] == per])
                        r = {'구간': per, '가족 후보 수(표본 기준 이상)': nmem, '이동 수': int(len(S) - 1),
                             '실제 가족 최대(자기 보유일)%': round(rA * 100, 1), '그 후보': M.loc[M['실제 적중%'].idxmax(), 'id'] if len(M) else '',
                             '이동 가족 최대 평균%': round(float(dA.mean()) * 100, 1), '이동 가족 최대 95% 점%': round(float(np.quantile(dA, 0.95)) * 100, 1),
                             'p(가족, 자기 보유일)': round(float((dA >= rA - 1e-9).mean()), 4),
                             '실제 가족 최대(1~10일 고름)%': round(rB * 100, 1), '이동 가족 최대(1~10일) 평균%': round(float(dB.mean()) * 100, 1),
                             '이동 가족 최대(1~10일) 95% 점%': round(float(np.quantile(dB, 0.95)) * 100, 1), 'p(가족, 1~10일 고름)': round(float((dB >= rB - 1e-9).mean()), 4)}
                        frows.append(r)
                        for pid in pth.get('ids', []):
                            mr = M[M['id'] == pid]
                            if not len(mr) or not (mr['실제 적중%'].iloc[0] == mr['실제 적중%'].iloc[0]): continue
                            h_ = float(mr['실제 적중%'].iloc[0]) / 100
                            frows.append({'구간': per, '통과·관찰 규칙': pid, '거래': int(mr['거래'].iloc[0]), '실제 적중%': round(h_ * 100, 1),
                                          'p(가족 최대 ≥ 이 규칙, 자기 보유일)': round(float((dA >= h_ - 1e-9).mean()), 4),
                                          'p(가족 최대(1~10일) ≥ 이 규칙)': round(float((dB >= h_ - 1e-9).mean()), 4),
                                          '가족 안 순위': int((M['실제 적중%'] > h_ * 100 + 1e-9).sum() + 1)})
                    pd.DataFrame(frows).to_csv(os.path.join(od, 'path_family_placebo.csv'), index=False, encoding='utf-8')
                    pd.DataFrame(mrows).to_csv(os.path.join(od, 'path_family_members.csv'), index=False, encoding='utf-8')
                    print('가족 단위 위약', len(mem), '후보 ·', len(frows), '줄', flush=True)
                except Exception as e:
                    print('가족 단위 위약 실패', repr(e), flush=True)
            # 갈래 B 라운드 38(path_table.regime_table: {hit_day}, 설정 없으면 없음 → 갈래 A·D 영향 없음, 후보 안 만듦 → A8 나눗수 그대로):
            #   가설 H7 '적중은 장세(상승장 해) 덕 — 같은 장세의 아무 날도 그만큼 오름'. 통과·관찰 규칙의 독립 거래를 신호일 장세(60일선 위/아래,
            #   20일 변동성·직전 20일 수익 3분위 — 문턱은 앞 구간 분포로 미리 정함, 그날 마감 뒤 아는 값)로 나눠, 같은 구간·같은 장세 아무 날의
            #   hit_day 일 상승 비율(기본)과 비교(차이·이항 p). 표본 10 미만은 '표본 부족'으로만 표시.
            rt_ = pth.get('regime_table')
            if rt_ and len(P):
                try:
                    hd_ = int(rt_.get('hit_day', pth.get('hit_day', 3)))
                    cl3 = pxp['close'].reindex(td).values.astype(float); op3 = pxp['open'].reindex(td).values.astype(float); n3 = len(td)
                    fwd = np.full(n3, np.nan)
                    ok3 = np.arange(n3) + hd_ < n3
                    fwd[ok3] = cl3[np.arange(n3)[ok3] + hd_] / op3[np.minimum(np.arange(n3)[ok3] + 1, n3 - 1)] - 1
                    fwd = pd.Series(fwd, index=td)
                    kc = k2['close'].reindex(td).astype(float)
                    ma60 = kc.rolling(60, min_periods=60).mean(); r1 = kc.pct_change()
                    vol20 = r1.rolling(20, min_periods=20).std() * np.sqrt(252) * 100; ret20 = (kc / kc.shift(20) - 1) * 100
                    tdv3 = pd.DatetimeIndex(td); inP1 = (tdv3 >= pd.Timestamp('2010-01-01')) & (tdv3 <= L.DEV_END); inP2 = tdv3 >= L.HOLD_START
                    def _terc(s):
                        q1, q2 = s[inP1].quantile([1 / 3, 2 / 3])
                        return pd.Series(np.where(s.isna(), None, np.where(s <= q1, '하', np.where(s <= q2, '중', '상'))), index=td), (round(float(q1), 2), round(float(q2), 2))
                    vb, vq = _terc(vol20); rb, rq = _terc(ret20)
                    regs = {'60일선': pd.Series(np.where(ma60.isna(), None, np.where(kc > ma60, '위', '아래')), index=td),
                            f'20일 변동성(연율, 문턱 {vq[0]}·{vq[1]}%)': vb, f'직전 20일 수익(문턱 {rq[0]}·{rq[1]}%)': rb}
                    rrows = []
                    for pid in pth.get('ids', []):
                        g0 = P[P['id'] == pid]
                        for per, inper in (('앞 2010~2023', inP1), ('뒤 2024~', inP2)):
                            g = g0[g0['앞뒤'] == per]
                            if not len(g): continue
                            sd = pd.to_datetime(g['신호일'])
                            hit = (g[f'{hd_}일%'] > 0).values; okh = g[f'{hd_}일%'].notna().values
                            for rn, rs in regs.items():
                                lab = rs.reindex(sd).values
                                for b in sorted({x for x in lab if x is not None}):
                                    sel = (lab == b) & okh; n_ = int(sel.sum()); k_ = int(hit[sel].sum())
                                    basem = pd.Series(np.asarray(inper), index=td) & (rs == b) & fwd.notna()
                                    base = float((fwd[basem] > 0).mean()) if basem.sum() else np.nan
                                    rrows.append({'id': pid, '구간': per, '장세': rn, '칸': b, '거래': n_, f'{hd_}일 적중%': round(k_ / n_ * 100, 1) if n_ else np.nan,
                                                  '같은 장세 아무 날%': round(base * 100, 1) if base == base else np.nan, '아무 날 수': int(basem.sum()),
                                                  '차이%p': round((k_ / n_ - base) * 100, 1) if n_ and base == base else np.nan,
                                                  '기본 대비 p': round(L.binom_p(k_, n_, base), 4) if n_ and base == base else np.nan,
                                                  '표본 주의': '10 미만(표본 부족)' if n_ < 10 else ''})
                    pd.DataFrame(rrows).to_csv(os.path.join(od, 'path_regime_table.csv'), index=False, encoding='utf-8')
                    print('장세 나눔 설명표', len(rrows), '칸', flush=True)
                except Exception as e:
                    print('장세 나눔 설명표 실패', repr(e), flush=True)
            # 갈래 B 라운드 39(path_table.cross_overlap: {other_dir, window, b_ids?}, 설정 없으면 없음 → 갈래 A·D 영향 없음, 후보 안 만듦 → A8 나눗수 그대로):
            #   다른 갈래(A)의 통과 규칙(그 결과 폴더 a08/verdicts.csv 의 goal_pass, a04/candidates.pkl 의 거래 — 읽기만)과 B 통과 규칙이 같은 국면을 잡는지(신호일 ±window 거래일),
            #   겹침/안 겹침별 적중, 그리고 두 규칙을 함께 쓰면(먼저 난 신호부터 각자 보유일, 보유 중 새 신호는 건너뜀) 독립 거래·적중이 얼마인지(구간별).
            #   적중 = 다음 날 시가(연속 선물) → 보유일째 종가 > 0(방향 반영). 자료 밖은 빼고 셈(추정 안 함).
            co_ = pth.get('cross_overlap')
            if co_:
                try:
                    import re as _re
                    labd = os.path.dirname(os.path.abspath(__file__))
                    odir = os.path.join(labd, co_.get('other_dir', 'out/round_043'))
                    V_ = pd.read_csv(os.path.join(odir, 'a08', 'verdicts.csv'))
                    a_ids = V_.loc[V_['goal_pass'] == True, 'id'].tolist()   # noqa: E712
                    with open(os.path.join(odir, 'a04', 'candidates.pkl'), 'rb') as fh: oc = {c['id']: c for c in pickle.load(fh)}
                    cl4 = pxp['close'].reindex(td).values.astype(float); op4 = pxp['open'].reindex(td).values.astype(float); n4 = len(td)
                    win = int(co_.get('window', 3)); byb = {c['id']: c for c in cands}
                    def _trades(c):
                        mm = _re.search(r'_m(\d+)', str(c['id'])); m_ = int(mm.group(1)) if mm else None
                        tr = c['trades'].assign(signal=lambda d: pd.to_datetime(d['signal']), exit=lambda d: pd.to_datetime(d['exit'])).dropna().sort_values('signal')
                        keep = []; last = pd.Timestamp('1900-01-01')
                        for s_, e_ in zip(tr['signal'], tr['exit']):
                            if s_ >= last: keep.append((s_, e_)); last = e_
                        out = []
                        for s_, e_ in keep:
                            i = pos.get(s_); j = pos.get(e_)
                            if i is None or j is None or j >= n4 or i + 1 >= n4: continue
                            r_ = cl4[j] / op4[i + 1] - 1
                            if not np.isfinite(r_): continue
                            out.append((i, j, bool(r_ * int(c.get('direction', 1) or 1) > 0)))
                        return out
                    def _per(i): return '앞 2010~2023' if td[i] <= L.DEV_END else '뒤 2024~'
                    crow = []
                    for bid in (co_.get('b_ids') or pth.get('ids', [])[:2]):
                        cb = byb.get(bid)
                        if cb is None: continue
                        TB = _trades(cb)
                        for aid in a_ids:
                            ca = oc.get(aid)
                            if ca is None: continue
                            TA = _trades(ca); ia = np.array([t[0] for t in TA]); ib = np.array([t[0] for t in TB])
                            for per in ('앞 2010~2023', '뒤 2024~'):
                                tb = [t for t in TB if _per(t[0]) == per]; ta = [t for t in TA if _per(t[0]) == per]
                                ovb = [t for t in tb if len(ia) and np.abs(ia - t[0]).min() <= win]; nob = [t for t in tb if not (len(ia) and np.abs(ia - t[0]).min() <= win)]
                                ova = [t for t in ta if len(ib) and np.abs(ib - t[0]).min() <= win]
                                # 함께 쓰기: 두 규칙 신호를 날짜 순으로, 보유 중이면 건너뜀(같은 날이면 B 먼저)
                                ev = sorted([(t[0], 0, t) for t in tb] + [(t[0], 1, t) for t in ta]); busy = -1; port = []
                                for i_, src, t in ev:
                                    if i_ < busy: continue
                                    port.append((src, t[2])); busy = t[1]
                                def _h(L_): return round(sum(x[2] for x in L_) / len(L_) * 100, 1) if L_ else np.nan
                                crow.append({'B 규칙': bid, 'A 규칙': aid, '구간': per, 'B 거래': len(tb), 'B 적중%': _h(tb), 'A 거래': len(ta), 'A 적중%': _h(ta),
                                             f'B 중 A 와 ±{win}일 겹침': len(ovb), '겹친 B 적중%': _h(ovb), '안 겹친 B 거래': len(nob), '안 겹친 B 적중%': _h(nob),
                                             f'A 중 B 와 ±{win}일 겹침': len(ova),
                                             '함께 쓰기 거래': len(port), '함께 쓰기 적중%': round(sum(p[1] for p in port) / len(port) * 100, 1) if port else np.nan,
                                             '함께 쓰기 중 A 몫': sum(1 for p in port if p[0] == 1),
                                             '표본 주의': '10 미만' if len(port) < 10 else ''})
                    pd.DataFrame(crow).to_csv(os.path.join(od, 'path_cross_overlap.csv'), index=False, encoding='utf-8')
                    print('다른 갈래 겹침 설명표', len(a_ids), 'A 규칙 ·', len(crow), '줄', flush=True)
                except Exception as e:
                    print('다른 갈래 겹침 설명표 실패', repr(e), flush=True)
            print('경로 설명표', len(P), '거래 ·', len(srows), '칸', flush=True)
        except Exception as e:
            print('경로 설명표 실패', repr(e), flush=True)
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
    # 갈래 B 라운드 40(a04.cross_union: [{name, b_id, other_dir, a_id, label?}], 설정 없으면 없음 → 갈래 A·D 영향 없음): 라운드 39 설명표에서
    #   B 통과 규칙과 A 통과 규칙은 앞 구간에서 대체로 다른 날에 나고(겹침 5~7/33), 함께 쓰면 거래 1.5배·적중 버팀이었다 → 정식 후보로 A8·A10 판정.
    #   미리 정한 짝 하나만(고르기 줄이려고): B 의 이번 라운드 후보 b_id 거래 + A 결과 폴더(other_dir/a04/candidates.pkl, 읽기만)의 a_id 거래.
    #   합치기: 신호일 순서로, 같은 날이면 B 먼저, 앞 거래 청산일 전 신호는 건너뜀(A8 의 독립 거래와 같은 규칙) — 각자 자기 보유일(B 3일·A 5일). 원자료 추정 없음.
    for xu in (cfg.get('cross_union') or []):
        try:
            labd = os.path.dirname(os.path.abspath(__file__))
            byb = {c['id']: c for c in cands}
            cb = byb.get(xu.get('b_id'))
            with open(os.path.join(labd, xu.get('other_dir', 'out/round_046'), 'a04', 'candidates.pkl'), 'rb') as fh:
                ca = {c['id']: c for c in pickle.load(fh)}.get(xu.get('a_id'))
            if cb is None or ca is None:
                print('함께 쓰기 후보 구성 없음', xu.get('name'), cb is None, ca is None, flush=True); continue
            if int(cb.get('direction', 1)) != int(ca.get('direction', 1)):
                print('함께 쓰기 방향 다름', xu.get('name'), flush=True); continue
            def _tt(c, src):
                t = c['trades'][['signal', 'exit']].copy()
                t['signal'] = pd.to_datetime(t['signal']); t['exit'] = pd.to_datetime(t['exit'])
                return t.dropna().assign(src=src)
            T = pd.concat([_tt(cb, 0), _tt(ca, 1)], ignore_index=True).sort_values(['signal', 'src'], kind='mergesort')
            keep = []; last = pd.Timestamp('1900-01-01')
            for s_, e_, src in zip(T['signal'], T['exit'], T['src']):
                if s_ >= last: keep.append((s_, e_, src)); last = e_
            K = pd.DataFrame(keep, columns=['signal', 'exit', 'src'])
            K[['signal', 'exit', 'src']].assign(구간=lambda d: np.where(d['signal'] <= L.DEV_END, 'P1', 'P2'),
                                               출처=lambda d: np.where(d['src'] == 0, 'B', 'A')).drop(columns='src') \
                .to_csv(os.path.join(od, f"cross_union_{xu.get('name')}.csv"), index=False, encoding='utf-8')
            uid = f"A4xu_{xu.get('name')}"
            cands.append({'id': uid, 'agent': 'A4', 'family': 'cross_union', 'direction': int(cb.get('direction', 1)),
                          'desc': f"함께 쓰기[{xu.get('label', xu.get('name'))}] — 먼저 난 신호부터 각자 보유일, 보유 중 새 신호 건너뜀 → {'상승' if int(cb.get('direction', 1)) > 0 else '하락'}",
                          'trades': K[['signal', 'exit']].reset_index(drop=True)})
            print('함께 쓰기 후보', uid, '거래', len(K), '(B', int((K['src'] == 0).sum()), '· A', int((K['src'] == 1).sum()), ')', flush=True)
        except Exception as e:
            print('함께 쓰기 후보 실패', xu.get('name'), repr(e), flush=True)
    L.save_candidates('a04', cands)
    print('표', len(rows), '후보', len(cands))


if __name__ == '__main__':
    main()
