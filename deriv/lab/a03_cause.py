"""A3 경로 가설 — 원인 분해(라운드 2~): 사용자 가설을 사슬로 쪼개 '어디서 끊기는지'를 잰다.

사슬: ① 콜 물량이 우세한 벽 → ② 지수가 벽에 닿음 → ③ 종가로 넘음 → ④ 외국인이 선물을 팖 → ⑤ 지수가 내림.
단계마다 '아무 힘이 없을 때'의 기준선과 비교한다(서술 통계는 개발 구간 2015~2023만, 잠금 구간은 보지 않음).
  ②·③ 기준선 = 같은 거리(σ 단위)·같은 기간에 아무 가격선이나 닿을(넘을) 경험적 확률 — 실제 경로라 추세·변동성이 들어 있다.
  ④ 기준선 = 직전 5일 상승 폭이 비슷한 아무 날(5분위 맞춤) 뒤 외국인 5일 순매도 비율.
  ⑤ 기준선 = 아무 날 뒤 10일 하락 비율.
더해서
  끌어당김·막힘: 같은 날 같은 거리(σ 구간)의 다른 행사가와 비교 — 미결제가 가장 많은 행사가에 더 잘 닿나, 닿은 날 더 잘 막히나.
  벽 이동: 지수가 다가가면 벽(최대 미결제 행사가)이 위로 옮겨 가나.
  우위 시작일 추적: 집중도가 상위 25%가 된 첫날 행사가를 고정하고 만기 뒤(롤오버 연장)까지 60거래일 추적.
  국면: 추세(60일선 위·아래)·외국인 20일 선물 누적(매수·매도 쪽)·변동성(3분위).
후보(전체 기간 날짜, 판정은 A8): 우위 시작일 매수, 돌파 실패 매도, 닿고 밀림 매도, 돌파 뒤 외국인 이틀 연속 매도 확인 매도.
"""
import json
import os
import pickle
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lab_common as L  # noqa: E402

cfg = L.round_cfg().get('a03c', {})
OBS = cfg.get('obs_dte', {'F0': [20, 10], 'Q': [40, 20]})
TRACK = cfg.get('track_days', [20, 40, 60])
DEV0 = pd.Timestamp('2015-01-01')


def pct(x):
    return float(np.round(np.mean(x) * 100, 1)) if len(x) else np.nan


def main():
    feat = pickle.load(open(os.path.join(L.LAB, 'work', 'lab_feat.pkl'), 'rb'))
    W = feat['walls'].dropna(subset=['K']).copy()
    W['date'] = pd.to_datetime(W['date']); W['exp'] = pd.to_datetime(W['exp'])
    k2 = L.k200_index(); td = k2.index; n_td = len(td)
    o = k2['open'].values; h = k2['high'].values; c = k2['close'].values
    lc, lh = np.log(c), np.log(h)
    sig = (np.log(k2['close']).diff().rolling(20).std() * np.sqrt(250)).values
    ma60 = k2['close'].rolling(60).mean().values
    pos = pd.Series(np.arange(n_td), index=td)
    F = L.flows().reindex(td)
    fs = F['fut_for']; cs = F['call_for']
    def post5(x): return x[::-1].rolling(5, min_periods=5).sum()[::-1].shift(-1).values   # t+1..t+5 합
    post5_for = post5(fs); post5_call = post5(cs); post5_cash = post5(F['cash_for'])
    pre5_for = fs.rolling(5, min_periods=5).sum().values
    for20 = fs.rolling(20, min_periods=15).sum().values
    fwd = {m: (k2['close'].shift(-m) / k2['open'].shift(-1) - 1).values * 100 for m in (1, 3, 5, 10)}
    r5 = (k2['close'] / k2['close'].shift(5) - 1).values
    dev = (td >= DEV0) & (td <= L.DEV_END)
    last_dev = int(pos[td[td <= L.DEV_END][-1]])

    def ok_dev(i):          # 그 날까지의 결과가 개발 구간 안에서 끝나나(잠금 구간을 엿보지 않게)
        return i <= last_dev

    # ---------- 경험적 기준선: 아무 날 d 에서 종가 × exp(z σ_d √(T/250)) 선에 T일 안 고가(H)·종가(C)로 닿을 확률
    cache = {}

    def fwd_max(arr, T):
        return pd.Series(arr)[::-1].rolling(T, min_periods=T).max()[::-1].shift(-1).values

    def base_touch(T, z, kind='H'):
        T = int(max(1, T)); key = (kind, T)
        if key not in cache:
            fm = fwd_max(lh if kind == 'H' else lc, T) - lc
            s = sig * np.sqrt(T / 250)
            ok = dev & np.isfinite(fm) & np.isfinite(s) & (s > 0) & (np.arange(n_td) + T <= last_dev)
            cache[key] = (fm[ok], s[ok])
        fm, s = cache[key]
        return float(np.mean(fm >= z * s)) if len(fm) and np.isfinite(z) else np.nan

    # ④ 기준선: 직전 5일 상승 5분위별 외국인 5일 순매도 비율(개발 구간)
    okb = dev & np.isfinite(r5) & np.isfinite(post5_for) & (np.arange(n_td) + 5 <= last_dev)
    r5_edges = np.nanquantile(r5[okb], [0.2, 0.4, 0.6, 0.8])
    r5_bin = np.digitize(r5, r5_edges)
    sell_by_bin = {b: float(np.mean(post5_for[okb & (r5_bin == b)] < 0)) for b in range(5)}
    okc = okb & np.isfinite(post5_call); okh = okb & np.isfinite(post5_cash)
    callsell_by_bin = {b: float(np.mean(post5_call[okc & (r5_bin == b)] < 0)) for b in range(5)}
    cashsell_by_bin = {b: float(np.mean(post5_cash[okh & (r5_bin == b)] < 0)) for b in range(5)}
    base_down10 = float(np.mean(fwd[10][dev & np.isfinite(fwd[10]) & (np.arange(n_td) + 10 <= last_dev)] < 0))
    od = L.out_dir('a03c')

    # ---------- 1) 사슬 사건(만기 주기마다 관측일 1번, 관측일 벽 행사가 고정)
    qd = {t: W[(W['tag'] == t) & (W['date'] <= L.DEV_END)][['share', 'ratio12', 'otm_cp']].quantile(0.75) for t in W['tag'].unique()}
    ev = []
    for (tag, ym), g in W.groupby(['tag', 'ym']):
        if tag not in OBS: continue
        g = g.sort_values('date'); exp = g['exp'].iloc[0]
        if exp not in pos.index: continue
        ie = int(pos[exp])
        for N in OBS[tag]:
            oo = g[(g['dte'] <= N) & (g['dte'] >= 1)]
            if not len(oo): continue
            r0 = oo.iloc[0]; d = r0['date']; i0 = int(pos[d]); K = float(r0['K']); T = int(r0['dte']); z = float(r0['dist_sig'])
            if not (np.isfinite(z) and z > 0): continue
            ph, pc = h[i0 + 1:ie + 1], c[i0 + 1:ie + 1]
            rec = {'tag': tag, 'ym': ym, 'obs': N, 'date': d, 'exp': exp, 'K': K, 'S': float(r0['S']), 'T': T, 'z': z,
                   'share': r0['share'], 'ratio12': r0['ratio12'], 'otm_cp': r0['otm_cp'], 'dev': bool(d >= DEV0 and ok_dev(ie)),
                   'touch': bool((ph >= K).any()), 'cross': bool((pc >= K).any()),
                   'base_touch': base_touch(T, z, 'H'), 'base_cross': base_touch(T, z, 'C'),
                   'trend_up': bool(c[i0] > ma60[i0]) if np.isfinite(ma60[i0]) else np.nan, 'for20': for20[i0], 'vol': sig[i0]}
            if rec['cross']:
                j = i0 + 1 + int(np.argmax(pc >= K))
                rec.update({'cross_date': td[j], 'for_pre5': pre5_for[j], 'for_post5': post5_for[j], 'call_post5': post5_call[j], 'cash_post5': post5_cash[j], 'r5_bin': int(r5_bin[j]) if np.isfinite(r5[j]) else np.nan,
                            'post5': fwd[5][j], 'post10': fwd[10][j], 'post_ok': ok_dev(j + 10),
                            'back_below10': bool((c[j + 1:j + 11] < K).any()) if j + 10 < n_td else np.nan})
            ev.append(rec)
    E = pd.DataFrame(ev)
    E.to_csv(os.path.join(od, 'chain_events_all.csv'), index=False, encoding='utf-8')
    D = E[E['dev']].copy()

    def tiers(df, tag):
        q = qd[tag]
        return {'전체': pd.Series(True, index=df.index), '집중 상위25%': df['share'] >= q['share'],
                '1위/2위 상위25%': df['ratio12'] >= q['ratio12'], '콜/풋 상위25%': df['otm_cp'] >= q['otm_cp'],
                '집중+콜/풋 상위25%': (df['share'] >= q['share']) & (df['otm_cp'] >= q['otm_cp'])}

    def funnel_row(x):
        n0 = len(x); t = x[x['touch']]; cr = x[x['cross']]
        crp = cr[cr['post_ok'] == True] if 'post_ok' in cr else cr.iloc[0:0]
        sold = crp['for_post5'] < 0 if len(crp) else pd.Series(dtype=bool)
        fell = crp['post10'] < 0 if len(crp) else pd.Series(dtype=bool)
        b3 = float(np.mean([sell_by_bin.get(int(b), np.nan) for b in crp['r5_bin'].dropna()])) if len(crp) else np.nan
        bc = float(np.mean([callsell_by_bin.get(int(b), np.nan) for b in crp['r5_bin'].dropna()])) if len(crp) else np.nan
        bh = float(np.mean([cashsell_by_bin.get(int(b), np.nan) for b in crp['r5_bin'].dropna()])) if len(crp) else np.nan
        csell = crp['call_post5'].dropna() < 0 if len(crp) else pd.Series(dtype=bool)
        hsell = crp['cash_post5'].dropna() < 0 if len(crp) else pd.Series(dtype=bool)
        full = int((sold & fell).sum()) if len(crp) else 0
        return {'주기': n0, '②닿음%': pct(x['touch']), '②기준%': pct(x['base_touch']),
                '③넘음%': pct(x['cross']), '③기준%': pct(x['base_cross']), '③닿은 뒤 넘음%': pct(t['cross']) if len(t) else np.nan,
                '넘은 주기(결과 확인)': len(crp), '④외국인 5일 순매도%': pct(sold), '④기준%(같은 상승 뒤)': round(b3 * 100, 1) if np.isfinite(b3) else np.nan,
                '④콜 5일 순매도%': pct(csell), '④콜 기준%': round(bc * 100, 1) if np.isfinite(bc) else np.nan,
                '④현물 5일 순매도%': pct(hsell), '④현물 기준%': round(bh * 100, 1) if np.isfinite(bh) else np.nan,
                '⑤10일 하락%': pct(fell), '⑤기준%': round(base_down10 * 100, 1),
                '④이면 ⑤%': pct(fell[sold]) if len(crp) and sold.any() else np.nan, '④아니면 ⑤%': pct(fell[~sold]) if len(crp) and (~sold).any() else np.nan,
                '10일 안 벽 아래 복귀%': pct(crp['back_below10'].dropna().astype(bool)) if len(crp) else np.nan,
                '사슬 완성(②~⑤)': full, '사슬 완성%(주기 대비)': round(full / n0 * 100, 1) if n0 else np.nan}

    FR = []
    for (tag, N), g in D.groupby(['tag', 'obs']):
        for tn, m in tiers(g, tag).items():
            x = g[m]
            if len(x) < 8: continue
            FR.append({'시리즈': tag, '관측(만기까지 일)': N, '조건': tn, **funnel_row(x)})
    FR = pd.DataFrame(FR); FR.to_csv(os.path.join(od, 'cause_funnel_dev.csv'), index=False, encoding='utf-8')

    # 국면별(근월물 20일 전·분기물 40일 전, 전체 조건)
    vq = np.nanquantile(sig[dev], [1 / 3, 2 / 3])
    RG = []
    for (tag, N), g in D.groupby(['tag', 'obs']):
        if (tag, N) not in (('F0', 20), ('Q', 40)): continue
        regs = {'추세: 60일선 위': g['trend_up'] == True, '추세: 60일선 아래': g['trend_up'] == False,
                '외국인 20일 선물 순매수 쪽': g['for20'] > 0, '외국인 20일 선물 순매도 쪽': g['for20'] < 0,
                '변동성 낮음': g['vol'] <= vq[0], '변동성 중간': (g['vol'] > vq[0]) & (g['vol'] <= vq[1]), '변동성 높음': g['vol'] > vq[1]}
        for rn, m in regs.items():
            x = g[m.fillna(False)]
            if len(x) < 6: continue
            RG.append({'시리즈': tag, '관측': N, '국면': rn, **funnel_row(x)})
    RG = pd.DataFrame(RG); RG.to_csv(os.path.join(od, 'cause_regime_dev.csv'), index=False, encoding='utf-8')

    # ---------- 2) 끌어당김·막힘: 벽 vs 같은 거리 다른 행사가(근월물, 만기 20일 전 관측일)
    src = 'x' if L.chain('x') is not None else 'm'
    ch = L.chain(src); ch = ch[(ch['cp'] == 'C') & (ch['oi'] > 0)]
    ch = ch[ch['ym'].str.len() == 6]
    obs_days = E[(E['tag'] == 'F0') & (E['obs'] == 20) & E['dev']][['date', 'ym', 'exp', 'S', 'T']]
    MG = []
    for _, r in obs_days.iterrows():
        g = ch[(ch['date'] == r['date']) & (ch['ym'] == r['ym']) & (ch['K'] > r['S'])].sort_values('oi', ascending=False)
        if len(g) < 4: continue
        i0 = int(pos[r['date']]); ie = int(pos[r['exp']]); s0 = sig[i0] * np.sqrt(max(r['T'], 1) / 250)
        ph, pc = h[i0 + 1:ie + 1], c[i0 + 1:ie + 1]
        for rank, (_, s) in enumerate(g.iterrows(), start=1):
            z = np.log(s['K'] / r['S']) / s0 if s0 > 0 else np.nan
            if not (np.isfinite(z) and 0 < z <= 3): continue
            hit = ph >= s['K']; touch = bool(hit.any())
            rej = np.nan
            if touch:
                j = int(np.argmax(hit)); rej = bool(pc[j] < s['K'])
            MG.append({'date': r['date'], 'K': s['K'], 'rank': rank, 'share': s['oi'] / g['oi'].sum(), 'z': z, 'touch': touch, 'reject_first_touch': rej})
    MG = pd.DataFrame(MG)
    bins = [0, 0.5, 1.0, 1.5, 2.0, 3.0]
    MR = []
    if len(MG):
        MG['bin'] = pd.cut(MG['z'], bins)
        num = den = 0.0; numr = denr = 0.0
        for b, g in MG.groupby('bin', observed=True):
            w, oth = g[g['rank'] == 1], g[g['rank'] >= 4]
            if len(w) < 3 or len(oth) < 3: continue
            wt, ot = w['touch'].mean(), oth['touch'].mean()
            wr = w['reject_first_touch'].dropna(); orj = oth['reject_first_touch'].dropna()
            MR.append({'거리(σ)': str(b), '벽 수': len(w), '벽 닿음%': round(wt * 100, 1), '다른 행사가 수(4위 이하)': len(oth), '다른 닿음%': round(ot * 100, 1),
                       '닿은 날 막힘%(벽)': pct(wr.astype(bool)) if len(wr) else np.nan, '닿은 날 막힘%(다른)': pct(orj.astype(bool)) if len(orj) else np.nan})
            k = len(w) * len(oth) / (len(w) + len(oth)); num += k * (wt - ot); den += k
            if len(wr) >= 2 and len(orj) >= 2:
                kr = len(wr) * len(orj) / (len(wr) + len(orj)); numr += kr * (wr.mean() - orj.mean()); denr += kr
        magnet = num / den * 100 if den else np.nan; resist = numr / denr * 100 if denr else np.nan
    else:
        magnet = resist = np.nan
    MR = pd.DataFrame(MR); MR.to_csv(os.path.join(od, 'cause_magnet_dev.csv'), index=False, encoding='utf-8')

    # ---------- 3) 벽 이동: 다가가면 벽이 위로 옮겨 가나(근월물, 만기 20일 전~만기)
    MV, cyc = [], []
    for (tag, ym), g in W[W['tag'] == 'F0'].groupby(['tag', 'ym']):
        g = g[(g['dte'] <= 20) & (g['dte'] >= 1)].sort_values('date').reset_index(drop=True)
        if len(g) < 5 or not (g['date'].iloc[0] >= DEV0 and g['exp'].iloc[0] <= L.DEV_END): continue
        Ks = g['K'].values
        cyc.append({'ym': ym, '벽 바뀐 횟수': int((np.diff(Ks) != 0).sum()), '위로': int((np.diff(Ks) > 0).sum()), '아래로': int((np.diff(Ks) < 0).sum()),
                    '만기 벽 > 처음 벽': bool(Ks[-1] > Ks[0]),
                    '만기 종가 ≥ 처음 벽': bool(c[int(pos[g['exp'].iloc[0]])] >= Ks[0])})
        for i in range(len(g) - 1):
            dist = g['dist%'].iloc[i]
            if not np.isfinite(dist) or dist <= 0: continue
            up3 = bool((Ks[i + 1:i + 4] > Ks[i]).any())
            MV.append({'구간': '≤1%' if dist <= 1 else ('1~2%' if dist <= 2 else '>2%'), 'up3': up3})
    MV = pd.DataFrame(MV); CY = pd.DataFrame(cyc)
    mig = MV.groupby('구간')['up3'].agg(['size', 'mean']).rename(columns={'size': '날수', 'mean': '3일 안 벽 위로%'}) if len(MV) else pd.DataFrame()
    if len(mig): mig['3일 안 벽 위로%'] = (mig['3일 안 벽 위로%'] * 100).round(1)
    mig.to_csv(os.path.join(od, 'cause_migration_dev.csv'), encoding='utf-8')
    CY.to_csv(os.path.join(od, 'cause_migration_cycles_dev.csv'), index=False, encoding='utf-8')

    # ---------- 4) 우위 시작일 추적(행사가 고정, 만기 뒤 롤오버 연장까지 60거래일)
    ON = []
    for (tag, ym), g in W[W['tag'].isin(['F0', 'Q'])].groupby(['tag', 'ym']):
        g = g[(g['dte'] >= 3) & (g['dist_sig'] > 0) & (g['dist_sig'] <= 2.5)].sort_values('date')
        g = g[g['share'] >= qd[tag]['share']]
        if not len(g): continue
        r0 = g.iloc[0]; d0 = r0['date']; i0 = int(pos[d0]); K = float(r0['K']); S0 = float(r0['S']); ie = int(pos[r0['exp']]) if r0['exp'] in pos.index else None
        rec = {'tag': tag, 'ym': ym, 'onset': d0, 'exp': r0['exp'], 'K': K, 'S': S0, 'dist%': r0['dist%'], 'z': r0['dist_sig'], 'dte': int(r0['dte']),
               'share': r0['share'], 'ratio12': r0['ratio12'], 'otm_cp': r0['otm_cp'], 'call_for': cs.iloc[i0], 'fut_for': fs.iloc[i0],
               'dev': bool(d0 >= DEV0 and d0 <= L.DEV_END)}
        if ie is not None and ie < n_td:
            rec['touch_exp'] = bool((h[i0 + 1:ie + 1] >= K).any()); rec['base_exp'] = base_touch(int(r0['dte']), float(r0['dist_sig']), 'H')
            rec['exp_ok'] = ok_dev(ie)
        for H in TRACK:
            if i0 + H < n_td:
                rec[f'touch{H}'] = bool((h[i0 + 1:i0 + H + 1] >= K).any()); rec[f'ok{H}'] = ok_dev(i0 + H)
                zH = np.log(K / S0) / (sig[i0] * np.sqrt(H / 250)) if sig[i0] > 0 else np.nan
                rec[f'base{H}'] = base_touch(H, zH, 'H')
        Hm = max(TRACK)
        pc = c[i0 + 1:min(n_td, i0 + Hm + 1)]
        if len(pc) and (pc >= K).any():
            j = i0 + 1 + int(np.argmax(pc >= K))
            rec.update({'cross_date': td[j], 'days_to_cross': j - i0, 'after_exp': bool(ie is not None and j > ie),
                        'post5': fwd[5][j], 'post10': fwd[10][j], 'for_post5': post5_for[j], 'post_ok': ok_dev(j + 10)})
        ON.append(rec)
    ONd = pd.DataFrame(ON)
    ONd.to_csv(os.path.join(od, 'onset_events_all.csv'), index=False, encoding='utf-8')
    OS = []
    for tag, g in ONd[ONd['dev']].groupby('tag'):
        row = {'시리즈': tag, '시작일 수': len(g), '평균 거리%': round(g['dist%'].mean(), 2), '평균 거리σ': round(g['z'].mean(), 2)}
        x = g[g.get('exp_ok', False) == True]
        row.update({'만기까지 닿음%': pct(x['touch_exp']), '만기까지 기준%': pct(x['base_exp'])})
        for H in TRACK:
            x = g[g.get(f'ok{H}', False) == True]
            row.update({f'{H}일 닿음%': pct(x[f'touch{H}']), f'{H}일 기준%': pct(x[f'base{H}'].dropna())})
        cr = g[(g.get('post_ok', False) == True)] if 'post_ok' in g else g.iloc[0:0]
        row.update({'60일 안 종가 돌파': int(g['cross_date'].notna().sum()) if 'cross_date' in g else 0,
                    '돌파가 만기 뒤(롤오버 뒤)%': pct(g['after_exp'].dropna().astype(bool)) if 'after_exp' in g else np.nan,
                    '돌파 뒤 외국인 5일 순매도%': pct(cr['for_post5'].dropna() < 0) if len(cr) else np.nan,
                    '돌파 뒤 10일 하락%': pct(cr['post10'].dropna() < 0) if len(cr) else np.nan, '10일 하락 기준%': round(base_down10 * 100, 1)})
        OS.append(row)
    OS = pd.DataFrame(OS); OS.to_csv(os.path.join(od, 'cause_onset_dev.csv'), index=False, encoding='utf-8')
    ONd[ONd['dev']].to_csv(os.path.join(od, 'onset_events_dev.csv'), index=False, encoding='utf-8')

    # ---------- 4b) 뒤늦게 보면 생기는 착시: 고점(앞뒤 10일 최고 종가, 뒤 10일 안 −3% 이상 하락) 날의 벽은 언제 생겼나
    cmax = k2['close'].rolling(21, center=True).max().values
    F0w = W[W['tag'] == 'F0'].drop_duplicates('date').set_index('date')
    PK, near_all = [], []
    for j in range(25, n_td - 11):
        d = td[j]
        if not dev[j] or j + 10 > last_dev or d not in F0w.index: continue
        Kt = float(F0w.loc[d, 'K']); dist = (Kt / h[j] - 1) * 100
        near_all.append(dist)
        if c[j] == cmax[j] and (c[j + 1:j + 11].min() / c[j] - 1) <= -0.03:
            d20 = td[j - 20]; K20 = float(F0w.loc[d20, 'K']) if d20 in F0w.index else np.nan
            d10 = td[j - 10]; K10 = float(F0w.loc[d10, 'K']) if d10 in F0w.index else np.nan
            PK.append({'고점': d, '고점 고가': h[j], '고점 날 벽': Kt, '고가→벽 거리%': round(dist, 2), '10일 전 벽': K10, '20일 전 벽': K20,
                       '20일 전에도 같은 벽': bool(K20 == Kt), '20일 전 벽→고점 고가 거리%': round((K20 / h[j] - 1) * 100, 2) if np.isfinite(K20) else np.nan,
                       '뒤 10일 최대 하락%': round((c[j + 1:j + 11].min() / c[j] - 1) * 100, 2)})
    PK = pd.DataFrame(PK); PK.to_csv(os.path.join(od, 'cause_hindsight_peaks_dev.csv'), index=False, encoding='utf-8')
    near_all = np.array(near_all)
    hind = {'고점 수': len(PK), '고점 날 벽이 고가 위 1.5% 안%': pct(PK['고가→벽 거리%'].between(0, 1.5)) if len(PK) else None,
            '아무 날 벽이 고가 위 1.5% 안%': pct((near_all >= 0) & (near_all <= 1.5)) if len(near_all) else None,
            '고점 벽이 20일 전에도 같은 벽%': pct(PK['20일 전에도 같은 벽']) if len(PK) else None,
            '20일 전 벽→고점 고가 거리 중앙값%': float(PK['20일 전 벽→고점 고가 거리%'].median()) if len(PK) else None}
    json.dump(hind, open(os.path.join(od, 'cause_hindsight_dev.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

    # ---------- 5) 후보 신호(전체 기간 날짜)
    cands = []

    def add(cid, desc, direction, fam, dates, m):
        dates = sorted(set(pd.DatetimeIndex(dates)))
        if len(dates) < 10: return
        t = pd.DataFrame({'signal': dates, 'exit': [L.exit_after(td, s, m) for s in dates]}).dropna()
        cands.append({'id': cid, 'agent': 'A3', 'desc': desc, 'direction': direction, 'family': fam, 'trades': t.sort_values('signal').reset_index(drop=True)})

    for tag in ('F0', 'Q'):
        g = ONd[ONd['tag'] == tag]
        for m in (3, 5, 10):
            add(f'A3c_onset_{tag}_m{m}', f'{tag} 콜 집중 상위25% 시작일 → {m}일 상승', 1, 'onset', g['onset'], m)
            add(f'A3c_onset_callbuy_{tag}_m{m}', f'{tag} 콜 집중 시작일 + 외국인 콜 순매수 → {m}일 상승', 1, 'onset', g[g['call_for'] > 0]['onset'], m)
            add(f'A3c_onset_near_{tag}_m{m}', f'{tag} 콜 집중 시작일(벽 1σ 안) → {m}일 상승', 1, 'onset', g[g['z'] <= 1]['onset'], m)
    # 날마다의 벽(전날 벽 행사가 기준)으로 돌파·돌파 실패·닿고 밀림
    for tag in ('F0', 'Q'):
        fail, rej, rejs, sell2 = [], [], [], []
        for ym, g in W[W['tag'] == tag].groupby('ym'):
            g = g.sort_values('date').reset_index(drop=True)
            crossed = touched = False
            for i in range(1, len(g)):
                Kp = g['K'].iloc[i - 1]; d = g['date'].iloc[i]
                j = int(pos[d])
                if j < 1 or c[j - 1] >= Kp: continue
                if not touched and h[j] >= Kp and c[j] < Kp:
                    touched = True; rej.append(d)
                    if fs.iloc[j] < 0: rejs.append(d)
                if not crossed and c[j] >= Kp:
                    crossed = True
                    if j + 2 < n_td:
                        back = [k for k in (j + 1, j + 2) if c[k] < Kp]
                        if back: fail.append(td[back[0]])
                        if fs.iloc[j + 1] < 0 and fs.iloc[j + 2] < 0: sell2.append(td[j + 2])
        for m in (3, 5, 10):
            add(f'A3c_failbreak_{tag}_m{m}', f'{tag} 콜벽 종가 돌파 뒤 2일 안 다시 아래로 → {m}일 하락', -1, 'fail_break', fail, m)
            add(f'A3c_cross_sell2_{tag}_m{m}', f'{tag} 콜벽 돌파 + 외국인 선물 이틀 연속 순매도 → {m}일 하락', -1, 'cross_sell2', sell2, m)
        for m in (1, 3, 5):
            add(f'A3c_reject_{tag}_m{m}', f'{tag} 콜벽에 장중 닿고 종가는 아래(첫 번째) → {m}일 하락', -1, 'touch_reject', rej, m)
            add(f'A3c_reject_fsell_{tag}_m{m}', f'{tag} 콜벽 닿고 밀림 + 외국인 선물 순매도 → {m}일 하락', -1, 'touch_reject', rejs, m)
    # 5b) 오래된 벽(10·20거래일 전 근월물 벽 행사가): 지금 벽은 다가가면 위로 도망가므로, 미리 정해진 행사가를 기준으로 본다
    F0K = F0w['K'].reindex(td)
    OLD = []
    for lag in (10, 20):
        Ko = F0K.shift(lag); Kp = Ko.shift(1); cp_ = k2['close'].shift(1)
        near = ((k2['high'] >= Ko * 0.99) & (k2['close'] < Ko)).fillna(False)
        near_first = near & ~near.shift(1, fill_value=False)
        crs = ((k2['close'] >= Ko) & (cp_ < Kp)).fillna(False)
        crs_conf = crs.shift(1, fill_value=False) & (fs < 0)          # 넘은 다음 날 외국인 선물 순매도
        for nm, ms_, lab in (('near', near_first, f'근월물 {lag}일 전 벽 1% 안까지 와서 종가는 아래'),
                             ('cross', crs, f'근월물 {lag}일 전 벽을 종가로 처음 넘음'),
                             ('crossconf', crs_conf, f'근월물 {lag}일 전 벽 돌파 + 다음 날 외국인 선물 순매도')):
            dts = td[ms_.values]
            for m in (3, 5, 10):
                add(f'A3c_old{lag}_{nm}_m{m}', f'{lab} → {m}일 하락', -1, f'oldwall_{nm}', dts, m)
                if nm == 'crossconf':
                    add(f'A3c_old{lag}_{nm}_up_m{m}', f'{lab} → {m}일 상승(반대 방향)', 1, 'oldwall_crossconf_up', dts, m)
            idx = np.where(ms_.values & dev)[0]; idx = idx[idx + 10 <= last_dev]
            v10 = fwd[10][idx]; v5 = fwd[5][idx]; fl = post5_for[idx]
            OLD.append({'벽': f'{lag}일 전', '사건': lab, '날수(개발)': int(len(idx)), '5일 하락%': pct(v5[np.isfinite(v5)] < 0), '10일 하락%': pct(v10[np.isfinite(v10)] < 0),
                        '10일 하락 기준%': round(base_down10 * 100, 1), '뒤 5일 외국인 순매도%': pct(fl[np.isfinite(fl)] < 0)})
    # 5c) 새 벽이 고가 바로 위에 생김(벽 행사가가 오늘 바뀌었고 고가 위 0~1.5%): 고점에서 벽이 늦게 생긴다는 관찰을 신호로
    Kd = F0K; newwall = ((Kd != Kd.shift(1)) & (Kd / k2['high'] - 1 >= 0) & (Kd / k2['high'] - 1 <= 0.015)).fillna(False)
    for nm, ms_, lab in (('newnear', newwall, '근월물 새 콜벽이 고가 바로 위(1.5% 안)에 생김'),
                         ('newnear_fsell', newwall & (fs < 0), '새 콜벽이 고가 바로 위 + 외국인 선물 순매도')):
        dts = td[ms_.values]
        for m in (3, 5, 10):
            add(f'A3c_{nm}_m{m}', f'{lab} → {m}일 하락', -1, 'newwall', dts, m)
            add(f'A3c_{nm}_up_m{m}', f'{lab} → {m}일 상승(반대 방향: 개발 구간 서술에서 상승이 많았음)', 1, 'newwall_up', dts, m)
        idx = np.where(ms_.values & dev)[0]; idx = idx[idx + 10 <= last_dev]
        v10 = fwd[10][idx]; v5 = fwd[5][idx]; fl = post5_for[idx]
        OLD.append({'벽': '오늘 새로 생긴 벽', '사건': lab, '날수(개발)': int(len(idx)), '5일 하락%': pct(v5[np.isfinite(v5)] < 0), '10일 하락%': pct(v10[np.isfinite(v10)] < 0),
                    '10일 하락 기준%': round(base_down10 * 100, 1), '뒤 5일 외국인 순매도%': pct(fl[np.isfinite(fl)] < 0)})
    OLD = pd.DataFrame(OLD); OLD.to_csv(os.path.join(od, 'cause_oldwall_dev.csv'), index=False, encoding='utf-8')
    L.save_candidates('a03c', cands)

    # ---------- 6) 요약(보고·총괄용)
    def first(df, **kw):
        x = df
        for k, v in kw.items(): x = x[x[k] == v]
        return x.iloc[0].to_dict() if len(x) else {}
    summ = {'funnel_F0_20': first(FR, 시리즈='F0', **{'관측(만기까지 일)': 20, '조건': '전체'}),
            'funnel_F0_20_dom': first(FR, 시리즈='F0', **{'관측(만기까지 일)': 20, '조건': '집중 상위25%'}),
            'funnel_Q_40': first(FR, 시리즈='Q', **{'관측(만기까지 일)': 40, '조건': '전체'}),
            'magnet_diff_pp': None if not np.isfinite(magnet) else round(magnet, 1),
            'resist_diff_pp': None if not np.isfinite(resist) else round(resist, 1),
            'migration': mig.reset_index().to_dict('records') if len(mig) else [],
            'cycles_wall_moved_up%': pct(CY['위로'] > 0) if len(CY) else None,
            'cycles_exp_above_first_wall%': pct(CY['만기 종가 ≥ 처음 벽']) if len(CY) else None,
            'onset': OS.to_dict('records'), 'hindsight': hind, 'oldwall': OLD.to_dict('records'), 'candidates': len(cands)}
    json.dump(summ, open(os.path.join(od, 'cause_summary.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=str)
    print(json.dumps(summ, ensure_ascii=False, default=str)[:3000])


if __name__ == '__main__':
    main()
