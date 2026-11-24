#!/usr/bin/env python3
"""입력값 만들기 — 행 T(거래일) = "T일 저녁 20시에 알 수 있는 값"만.

시점 규칙
  · 금투협(반대매매·미수금·신용잔고·예탁금): 기준일이 T 보다 앞선 행까지만(= T-1 기준일, T일 15시쯤 공개).
    금투협 달력(연말 휴장일 포함)에서 "T 직전 행"을 찾아 붙인다(merge_asof, 같은 날짜 불허).
  · 시장 자료(코스피·코스닥 시가/고가/저가/종가, 거래대금, 투자자별 확정, VKOSPI, 종목 집계): T 당일까지.
  · 목표: 반대매매(T) — T+1 에 공개되는 값. 입력에는 절대 쓰지 않는다.
build(..., cutoff=T) 는 원자료에서 T 뒤(금투협은 T 포함)를 지우고 만든다 → leak_check.py 가 전체 자료로 만든 행 T 와 비교.
"""
import os, warnings, numpy as np, pandas as pd
warnings.filterwarnings('ignore')

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, '..'))   # main 저장소의 nowcast/ (liq-nowcast 가지 research/liq_nowcast/features.py 를 그대로 옮김, 경로만 바꿈)


def load_raw(root=ROOT, pub=os.path.join(HERE, 'data')):
    R = {}
    k = pd.read_csv(os.path.join(root, 'out', 'liq_daily.csv'), parse_dates=['date'])[['date', 'liq_eok', 'misu_eok']]
    c = pd.read_csv(os.path.join(root, 'out', 'credit.csv'), parse_dates=['date'])[['date', 'credit_jo', 'kospi_jo', 'kosdaq_jo', 'deposit_jo']]
    R['kofia'] = k.merge(c, on='date', how='outer').sort_values('date').reset_index(drop=True)
    x = pd.read_excel(os.path.join(root, 'data', '통합_원자료.xlsx'), sheet_name='코스피_일별')
    x = x.rename(columns={'일자': 'date', '종가(pt)': 'close', '시가(pt)': 'open', '고가(pt)': 'high', '저가(pt)': 'low', '거래대금(백만원)': 'tv'})[['date', 'close', 'open', 'high', 'low', 'tv']]
    x['date'] = pd.to_datetime(x['date']); x = x.dropna(subset=['close']).sort_values('date')
    m = pd.read_csv(os.path.join(root, 'out', 'market_daily.csv'), parse_dates=['date'])[['date', 'kospi', 'vkospi', 'vkospi_high']]
    f = pd.read_csv(os.path.join(root, 'out', 'flows_daily.csv'), parse_dates=['date'])[['date', 'foreign_jo', 'inst_jo', 'indiv_jo']]
    mk = m.merge(x, on='date', how='left').merge(f, on='date', how='left').sort_values('date').reset_index(drop=True)
    mk['close'] = mk['close'].fillna(mk['kospi']); R['mkt'] = mk
    p = os.path.join(pub, 'kosdaq_index.csv'); R['kq'] = pd.read_csv(p, parse_dates=['date']) if os.path.exists(p) else None
    p = os.path.join(pub, 'breadth_daily.csv'); R['br'] = pd.read_csv(p, parse_dates=['date']) if os.path.exists(p) else None
    return R


def build(R, cutoff=None, _leaky=False):
    """돌려주는 것: (표, 묶음별 입력 이름). cutoff=T 이면 T 뒤 자료를 지우고 만든다(점검용)."""
    K, M = R['kofia'].copy(), R['mkt'].copy(); Q = None if R['kq'] is None else R['kq'].copy(); B = None if R['br'] is None else R['br'].copy()
    if cutoff is not None:
        cutoff = pd.Timestamp(cutoff); K = K[K['date'] < cutoff]; M = M[M['date'] <= cutoff]
        if Q is not None: Q = Q[Q['date'] <= cutoff]
        if B is not None: B = B[B['date'] <= cutoff]
    G = {}
    # ------------------------------------------------ 금투협: 행 j 까지의 값으로 만든 뒤 "T 직전 행"으로 붙인다
    K = K.sort_values('date').reset_index(drop=True); liq = K['liq_eok'].ffill(); mis = K['misu_eok'].ffill(); kf = pd.DataFrame({'kdate': K['date']})
    L = np.log(liq); Mi = np.log(mis)
    kf['ll1'], kf['ll2'], kf['ll3'] = L, L.shift(1), L.shift(2)
    kf['lm1'] = Mi; kf['dm1'] = Mi - Mi.shift(1); kf['dm2'] = Mi.shift(1) - Mi.shift(2); kf['dm5'] = Mi - Mi.shift(5)
    lr = np.log(liq / mis.shift(1)); kf['lr1'], kf['lr2'] = lr, lr.shift(1)
    G['base_kofia'] = ['ll1', 'll2', 'lm1', 'dm1']
    kf['ll_med5'] = np.log(liq.rolling(5, min_periods=3).median()); kf['ll_med20'] = np.log(liq.rolling(20, min_periods=10).median()); kf['ll_max5'] = np.log(liq.rolling(5, min_periods=3).max())
    kf['lr_med20'] = lr.rolling(20, min_periods=10).median(); kf['lr_sd20'] = lr.rolling(20, min_periods=10).std()
    kf['ex20'] = Mi - np.log(mis.rolling(20, min_periods=10).min()); kf['ex60'] = Mi - np.log(mis.rolling(60, min_periods=20).min()); kf['mz60'] = Mi - np.log(mis.rolling(60, min_periods=20).median())
    kf['dl1'] = L - L.shift(1)
    kf['la60'] = np.log(np.maximum(mis - mis.rolling(60, min_periods=20).min(), 0.005 * mis)); kf['la250'] = np.log(np.maximum(mis - mis.rolling(250, min_periods=60).min(), 0.005 * mis))   # 바닥(오래 남아 있는 미수금)을 뺀 '움직이는 미수금'
    G['kofia_x'] = ['ll3', 'dm2', 'dm5', 'lr1', 'lr2', 'll_med5', 'll_med20', 'll_max5', 'lr_med20', 'lr_sd20', 'ex20', 'ex60', 'mz60', 'dl1', 'la60', 'la250']
    for nm, col in (('cr', 'credit_jo'), ('crq', 'kosdaq_jo'), ('dep', 'deposit_jo')):
        s = np.log(K[col].ffill()); kf[f'd{nm}1'] = (s - s.shift(1)) * 100; kf[f'd{nm}5'] = (s - s.shift(5)) * 100
    kf['dep_misu'] = np.log(K['deposit_jo'].ffill() * 1e4 / mis)
    G['credit'] = ['dcr1', 'dcr5', 'dcrq1', 'dcrq5', 'ddep1', 'ddep5', 'dep_misu']
    kf['misu_prev'] = mis; kf['liq_prev'] = liq
    # ------------------------------------------------ 시장(코스피): 당일 T 까지
    M = M.sort_values('date').reset_index(drop=True); d = pd.DataFrame({'date': M['date']}); C, O, H, Lo = M['close'], M['open'], M['high'], M['low']
    r = (C / C.shift(1) - 1) * 100
    for k in range(4): d[f'r{k}'] = r.shift(k); d[f'n{k}'] = r.shift(k).clip(upper=0)
    G['base_mkt'] = [f'{a}{k}' for k in range(4) for a in 'rn']
    def struct(pre, C, O, H, Lo, r):
        f = pd.DataFrame(index=C.index)
        f[pre + 'r4'] = r.shift(4)
        f[pre + 'cum21'] = (C.shift(1) / C.shift(3) - 1) * 100; f[pre + 'cum21n'] = f[pre + 'cum21'].clip(upper=0); f[pre + 'cum21n2'] = f[pre + 'cum21n'] ** 2
        f[pre + 'cum321'] = (C.shift(1) / O.shift(3) - 1) * 100
        f[pre + 'worst21'] = (np.minimum(Lo.shift(1), Lo.shift(2)) / C.shift(3) - 1) * 100
        f[pre + 'gap0'] = (O / C.shift(1) - 1) * 100; f[pre + 'gap0n'] = f[pre + 'gap0'].clip(upper=0)
        f[pre + 'cumo'] = (O / C.shift(3) - 1) * 100; f[pre + 'cumon'] = f[pre + 'cumo'].clip(upper=0)
        f[pre + 'intr3'] = (C.shift(3) / O.shift(3) - 1) * 100; f[pre + 'hi3'] = (C.shift(3) / H.shift(3) - 1) * 100
        f[pre + 'low0'] = (Lo / C.shift(1) - 1) * 100
        f[pre + 'cum10'] = (C / C.shift(2) - 1) * 100                      # 다음 날 반대매매 묶음(T-2 매수)의 손실 — 선제 상환·심리
        f[pre + 'rv5'] = r.rolling(5).std(); f[pre + 'rv20'] = r.rolling(20).std(); f[pre + 'dd20'] = (C / C.rolling(20).max() - 1) * 100
        return f
    s = struct('', C, O, H, Lo, r); d = pd.concat([d, s], axis=1); G['struct'] = list(s.columns)
    tv = M['tv']; ltv = np.log(tv / tv.shift(1).rolling(20, min_periods=10).median())
    for k in range(4): d[f'ltv{k}'] = ltv.shift(k)
    tvj = tv.shift(1).rolling(20, min_periods=10).mean() / 1e6               # 조원(직전 20일 평균, 당일 제외)
    for k in range(4): d[f'ind{k}'] = (M['indiv_jo'] / tvj).shift(k) * 100
    d['for0'] = M['foreign_jo'] / tvj * 100; d['for1'] = d['for0'].shift(1)
    G['flow'] = [f'ltv{k}' for k in range(4)] + [f'ind{k}' for k in range(4)] + ['for0', 'for1']
    vk = np.log(M['vkospi']); d['lvk0'] = vk; d['lvk1'] = vk.shift(1); d['dvk0'] = vk - vk.shift(1); d['dvk1'] = vk.shift(1) - vk.shift(2); d['dvk3'] = vk.shift(1) - vk.shift(3)
    d['vkh0'] = np.log(M['vkospi_high'] / M['vkospi'].shift(1)); d['vkz'] = vk - vk.shift(1).rolling(60, min_periods=20).mean()
    G['vkospi'] = ['lvk0', 'lvk1', 'dvk0', 'dvk1', 'dvk3', 'vkh0', 'vkz']
    G['vkospi_lag'] = ['lvk1', 'dvk1', 'dvk3']                               # 당일 VKOSPI 를 못 쓰는 경우의 대안
    dow = d['date'].dt.dayofweek
    for k in range(4): d[f'dow{k}'] = (dow == k).astype(float)
    d['gapdays'] = (d['date'] - d['date'].shift(1)).dt.days.astype(float); d['span3'] = (d['date'] - d['date'].shift(3)).dt.days.astype(float)
    G['cal'] = [f'dow{k}' for k in range(4)] + ['gapdays', 'span3']
    # ------------------------------------------------ 코스닥 지수(네이버)
    if Q is not None and len(Q):
        q = d[['date']].merge(Q, on='date', how='left'); qr = (q['close'] / q['close'].shift(1) - 1) * 100
        for k in range(4): d[f'q_r{k}'] = qr.shift(k).values; d[f'q_n{k}'] = qr.shift(k).clip(upper=0).values
        s = struct('q_', q['close'], q['open'], q['high'], q['low'], qr); s.index = d.index; d = pd.concat([d, s], axis=1)
        G['kosdaq'] = [f'q_{a}{k}' for k in range(4) for a in 'rn'] + list(s.columns)
    # ------------------------------------------------ 종목 집계(네이버 종목 일봉)
    if B is not None and len(B):
        b = d[['date']].merge(B, on='date', how='left'); g1, g2, g3 = [], [], []
        for mk in ('ks', 'kq'):
            if f'{mk}_n' not in b: continue
            n = b[f'{mk}_n'].replace(0, np.nan)
            for k in range(3):
                d[f'{mk}_dn10_{k}'] = np.log1p(b[f'{mk}_dn10'] / n * 1000).shift(k).values; d[f'{mk}_lim_{k}'] = np.log1p(b[f'{mk}_lim']).shift(k).values; g1 += [f'{mk}_dn10_{k}', f'{mk}_lim_{k}']
            d[f'{mk}_dn20_0'] = np.log1p(b[f'{mk}_dn20']).values; d[f'{mk}_dn20_1'] = np.log1p(b[f'{mk}_dn20']).shift(1).values; d[f'{mk}_up10_3'] = np.log1p(b[f'{mk}_up10'] / n * 1000).shift(3).values
            d[f'{mk}_p10_0'] = b[f'{mk}_ret_p10'].values; d[f'{mk}_p10_1'] = b[f'{mk}_ret_p10'].shift(1).values; d[f'{mk}_p10_2'] = b[f'{mk}_ret_p10'].shift(2).values
            g1 += [f'{mk}_dn20_0', f'{mk}_dn20_1', f'{mk}_up10_3', f'{mk}_p10_0', f'{mk}_p10_1', f'{mk}_p10_2']
            d[f'{mk}_c_n10'] = np.log1p(b[f'{mk}_c_n10'] / n * 1000).values; d[f'{mk}_c_n20'] = np.log1p(b[f'{mk}_c_n20']).values; d[f'{mk}_c_p10'] = b[f'{mk}_c_p10'].values; d[f'{mk}_c_med'] = b[f'{mk}_c_med'].values
            d[f'{mk}_c_hot_n'] = np.log1p(b[f'{mk}_c_hot_n']).values; d[f'{mk}_c_hot_loss'] = b[f'{mk}_c_hot_loss'].values; d[f'{mk}_c_hot_loss_o'] = b[f'{mk}_c_hot_loss_o'].values; d[f'{mk}_c_hot_n10'] = np.log1p(b[f'{mk}_c_hot_n10']).values
            g2 += [f'{mk}_c_n10', f'{mk}_c_n20', f'{mk}_c_p10', f'{mk}_c_med', f'{mk}_c_hot_n', f'{mk}_c_hot_loss', f'{mk}_c_hot_loss_o', f'{mk}_c_hot_n10']
            d[f'{mk}_vw_loss'] = b[f'{mk}_vw_loss'].values; d[f'{mk}_vw_loss_o'] = b[f'{mk}_vw_loss_o'].values; d[f'{mk}_vw_l10'] = b[f'{mk}_vw_l10'].values
            va = b[f'{mk}_vw_lossamt']; d[f'{mk}_vw_lossamt'] = (np.log1p(va) - np.log1p(va.shift(1).rolling(60, min_periods=20).median())).values
            g3 += [f'{mk}_vw_loss', f'{mk}_vw_loss_o', f'{mk}_vw_l10', f'{mk}_vw_lossamt']
        G['breadth'] = g1; G['cohort'] = g2; G['cohort_vw'] = g3
    # ------------------------------------------------ 금투협 붙이기(T 직전 기준일) + 목표
    d = pd.merge_asof(d.sort_values('date'), kf.sort_values('kdate'), left_on='date', right_on='kdate', allow_exact_matches=False, direction='backward')
    d['kofia_gap'] = (d['date'] - d['kdate']).dt.days.astype(float)
    if _leaky:   # 점검기가 제대로 잡는지 보는 일부러 틀린 입력(당일 금투협 값) — 시험에는 쓰지 않는다
        z = pd.merge_asof(d[['date']], kf[['kdate', 'll1']].rename(columns={'ll1': 'zz_leak'}), left_on='date', right_on='kdate', allow_exact_matches=True, direction='backward'); d['zz_leak'] = z['zz_leak'].values
    # 선형 모형용 곱(나무 모형은 스스로 찾음)
    d['x_dm_cum'] = d['dm1'].clip(lower=0) * d['cum21n']; d['x_lr_cum'] = d['lr1'] * d['cum21n']; d['x_ex_cum'] = d['ex20'] * d['cum21n']
    G['struct'] = G['struct'] + ['x_dm_cum', 'x_lr_cum', 'x_ex_cum']
    # 간추린 입력 묶음(최근 자료만으로 학습할 때 쓰는 적은 수의 입력)
    G['core'] = ['ll1', 'll2', 'lm1', 'dm1', 'r0', 'n0', 'r1', 'n1', 'cum21', 'cum21n', 'cumo', 'lr1', 'ex20', 'll_med5']
    G['core_x'] = ['x_lr_cum', 'ind2', 'ind3', 'dvk0', 'gap0', 'll_med20', 'dm2', 'll3', 'worst21', 'cum10', 'ltv3', 'la60']
    G['core_q'] = [c for c in ('q_cum21', 'q_cumo', 'q_r0', 'q_gap0', 'q_cum21n', 'q_r1') if c in d.columns]
    G['core_s'] = [c for c in ('kq_c_p10', 'kq_c_n10', 'ks_c_p10', 'kq_dn10_0', 'kq_dn10_1', 'kq_lim_0', 'kq_lim_1', 'kq_c_hot_loss', 'kq_c_hot_n10', 'ks_c_n10') if c in d.columns]
    G['core_v'] = [c for c in ('kq_vw_loss', 'ks_vw_loss', 'kq_vw_l10', 'kq_vw_lossamt') if c in d.columns]
    if cutoff is None:
        y = R['kofia'][['date', 'liq_eok']].rename(columns={'liq_eok': 'liq'}); d = d.merge(y, on='date', how='left')
        d['y_lvl'] = np.log(d['liq']); d['y_ratio'] = np.log(d['liq'] / d['misu_prev']); d['y_chg'] = np.log(d['liq'] / d['liq_prev'])
    return d.reset_index(drop=True), G


if __name__ == '__main__':
    R = load_raw(); d, G = build(R); print(d.shape, {k: len(v) for k, v in G.items()}); print(d.tail(3).T.to_string())
