# -*- coding: utf-8 -*-
"""make_chart.py — 카카오톡에 붙일 요약 그래프(report/chart.png)와 중요 변동 목록(report/alerts.json)을 만든다.
   그래프(최근 60거래일, 4칸): ① 코스피·20일선(국면 배경색) ② 미수 반대매매 억원(막대)·미수금 대비 비중 %(선)
                               ③ 신용융자 잔고 조원 ④ 외국인 순매수 조원(막대)·12개 해 합의 상승 비율 %(선)
   중요 변동: 전 거래일 대비 바뀐 것만(국면, 5일 급락 확률 27% 기준, 반대매매 비중, 신용 급감, 외국인 대량 매매,
             코스피 큰 등락, VKOSPI 급등, 실제 큰 흐름·'2026 1위' 전환, 12개 해 합의 변화, 새 매매 신호).
   사용: python make_chart.py --out out --report report
"""
import argparse, json, os
import numpy as np, pandas as pd

def rd(p): return pd.read_csv(p) if os.path.exists(p) else None

def korean_font():
    import matplotlib
    from matplotlib import font_manager as fm
    for name in ('NanumGothic', 'Noto Sans CJK KR', 'Noto Sans CJK JP', 'Noto Sans CJK SC', 'Malgun Gothic', 'AppleGothic'):
        if any(f.name == name for f in fm.fontManager.ttflist):
            matplotlib.rcParams['font.family'] = name; matplotlib.rcParams['axes.unicode_minus'] = False; return True
    return False

def md(d): d = str(d); return f'{int(d[5:7])}/{int(d[8:10])}'
def sg(v, n=1): return ('+' if v > 0 else '−' if v < 0 else '±') + f'{abs(v):,.{n}f}'

def alerts(o, sig_new=None):
    A = []; M = rd(f'{o}/market_daily.csv'); Q = rd(f'{o}/q_daily.csv'); L = rd(f'{o}/liq_daily.csv'); C = rd(f'{o}/credit.csv')
    F = rd(f'{o}/flows_daily.csv'); CB = rd(f'{o}/combo.csv'); TC = rd(f'{o}/trend_champ.csv')
    if M is not None and len(M) > 1:
        m = M.iloc[-1]
        if abs(m['kospi_chg_pct']) >= 3: A.append(f"코스피 {sg(m['kospi_chg_pct'], 2)}% ({m['kospi']:,.2f})")
        v = M[M['vkospi'].notna()]
        if len(v) > 5:
            ch = (v['vkospi'].iloc[-1] / v['vkospi'].iloc[-6] - 1) * 100
            if ch >= 25: A.append(f"VKOSPI 5일 {sg(ch, 0)}% ({v['vkospi'].iloc[-1]:.2f}) — 고변동 청산 조건")
    if Q is not None and len(Q) > 1:
        a, b = Q.iloc[-2], Q.iloc[-1]
        if a['regime'] != b['regime']: A.append(f"국면 {a['regime']} → {b['regime']}")
        if (a['p_risk'] >= 0.27) != (b['p_risk'] >= 0.27):
            A.append(f"5일 급락 확률 {a['p_risk']*100:.0f}% → {b['p_risk']*100:.0f}% (위험 신호 {'켜짐' if b['p_risk'] >= 0.27 else '꺼짐'}, 기준 27%)")
    if L is not None and len(L) > 1:
        a, b = L.iloc[-2], L.iloc[-1]
        if b['ratio_pct'] >= 5 and a['ratio_pct'] < 5: A.append(f"반대매매 비중 {b['ratio_pct']:.1f}% — 5% 돌파({md(b['date'])}, {b['liq_eok']:,.0f}억)")
        elif b['ratio_pct'] < 5 <= a['ratio_pct']: A.append(f"반대매매 비중 {b['ratio_pct']:.1f}% — 5% 아래로({md(b['date'])})")
    if C is not None and len(C):
        c = C.iloc[-1]
        if c['chg_pct'] <= -2.5: A.append(f"신용융자 하루 {sg(c['chg_pct'], 2)}% ({md(c['date'])}, {c['credit_jo']:.2f}조) — 급감")
    if F is not None and len(F):
        f = F.iloc[-1]
        if abs(f['foreign_jo']) >= 1: A.append(f"외국인 {sg(f['foreign_jo'], 2)}조원 ({'순매수' if f['foreign_jo'] > 0 else '순매도'})" + (' 잠정' if '잠정' in str(f.get('basis', '')) else ''))
    if CB is not None and len(CB) > 1:
        a, b = CB.iloc[-2], CB.iloc[-1]; t = lambda x: '상승' if x == 1 else ('하락' if x == -1 else '—')
        if a['leg'] != b['leg'] and pd.notna(b['leg']): A.append(f"실제 큰 흐름 {t(a['leg'])} → {t(b['leg'])}")
        if a['top26'] != b['top26'] and pd.notna(b['top26']): A.append(f"'2026 1위' 줄 {t(a['top26'])} → {t(b['top26'])}")
        if a['fast'] != b['fast'] and pd.notna(b['fast']): A.append(f"빠른 전환 줄 {t(a['fast'])} → {t(b['fast'])}")
    if TC is not None and len(TC) > 1:
        ys = [k for k in TC.columns if k.startswith('y') and k[1:].isdigit()]
        u = (TC[ys] == 1).sum(axis=1); n = TC[ys].notna().sum(axis=1)
        if u.iloc[-1] != u.iloc[-2] and abs(u.iloc[-1] - u.iloc[-2]) >= 2 or (u.iloc[-1] * 2 > n.iloc[-1]) != (u.iloc[-2] * 2 > n.iloc[-2]):
            A.append(f"12개 해 합의 상승 {u.iloc[-2]} → {u.iloc[-1]}/{n.iloc[-1]}")
    for s in (sig_new or []): A.append('★ 새 신호: ' + s)
    return A


BUY_C, SELL_C, HOLD_C = '#d32f2f', '#1565c0', '#6a1b9a'
# 신호별 고유 색(매수 = 따뜻한 색, 매도 = 차가운 색, 보유 구간 = 보라·초록)
SIG_C = {'매수 민감형': '#ff8a65', '매수 중간형': '#f4511e', '매수 엄격형': '#b71c1c', '매수 최적화 1위': '#c2185b', '매수 최적화 2위': '#f06292', '매수 최적화 3위': '#8d6e63',
         '정밀 검증 전략(보유)': '#7b1fa2', '재진입 규칙(보유)': '#2e7d32',
         '매도 최적화 1위': '#0d47a1', '매도 최적화 2위': '#42a5f5', '매도 최적화 3위': '#00838f', '매도 민감형': '#4dd0e1', '매도 중간형': '#5c6bc0', '매도 엄격형': '#37474f'}
def sc(lab): return SIG_C.get(lab, '#777')
def signal_rows(o, days):
    """설정해 둔 매매 신호 전부를 줄 단위로: (이름, 쪽, 켜진 날 index 집합, ▲ 날, ▼ 날)"""
    x = {d: i for i, d in enumerate(days)}; rows = []
    def ix(ds): return {x[d] for d in ds if d in x}
    AL, B3, S3, RE, Q = (rd(f'{o}/{f}.csv') for f in ('alarms', 'buy3', 'sell3', 'reentry', 'q_daily'))
    def fam(df, side, key, label):
        for k in key:
            d = df[(df['side'] == side) & (df['type'] == k)] if df is not None else pd.DataFrame(columns=['date', 'start'])
            st = ix(d[d['start'] == '시작']['date']); on = ix(d['date'])
            rows.append((label(k), side, on, st if side == '매수' else set(), st if side == '매도' else set()))
    fam(AL, '매수', ['민감형', '중간형', '엄격형'], lambda k: f'매수 {k}')
    fam(B3, '매수', ['최적화 1위', '최적화 2위', '최적화 3위'], lambda k: f'매수 {k}')
    # 정밀 검증 전략: 진입(enter) ~ 청산(exit) 보유
    if Q is not None:
        on, hold, up, dn = set(), False, set(), set()
        for d, t in zip(Q['date'], Q['trade']):
            if t == 'enter': hold = True; up.add(d)
            if hold and d in x: on.add(x[d])
            if t == 'exit': hold = False; dn.add(d)
        rows.append(('정밀 검증 전략(보유)', '보유', on, ix(up), ix(dn)))
    # 재진입 규칙: 매수 신호·재매수 → 보유, 매도 신호·재매도 → 현금
    if RE is not None:
        st = dict(zip(RE['date'], RE['state'])); cur, on = None, set(); M = rd(f'{o}/market_daily.csv')
        for d in M['date']:
            cur = st.get(d, cur)
            if cur == '보유' and d in x: on.add(x[d])
        up = RE[RE['action'].isin(['매수 신호', '재매수'])]['date']; dn = RE[RE['action'].isin(['매도 신호', '재매도'])]['date']
        rows.append(('재진입 규칙(보유)', '보유', on, ix(up), ix(dn)))
    fam(S3, '매도', ['최적화 1위', '최적화 2위', '최적화 3위'], lambda k: f'매도 {k}')
    fam(AL, '매도', ['민감형', '중간형', '엄격형'], lambda k: f'매도 {k}')
    return rows

def mark_signals(ax, X, price, rows):
    """코스피 선 위에 ▲(매수 시작)·▼(매도 시작) 표시 — 같은 날 여러 개면 개수"""
    import collections
    up, dn = collections.defaultdict(list), collections.defaultdict(list)
    for r in rows:
        for i in r[3]: up[i].append(sc(r[0]))
        for i in r[4]: dn[i].append(sc(r[0]))
    rng = (np.nanmax(price) - np.nanmin(price)) or 1
    # 같은 날 여러 신호면 신호마다 제 색으로 위·아래로 쌓는다
    for i, cs in up.items():
        for k, c in enumerate(cs): ax.scatter(i, price[i] - rng * (.06 + .055 * k), marker='^', s=44, color=c, zorder=5, edgecolor='white', lw=.6)
    for i, cs in dn.items():
        for k, c in enumerate(cs): ax.scatter(i, price[i] + rng * (.06 + .055 * k), marker='v', s=44, color=c, zorder=5, edgecolor='white', lw=.6)
    return up, dn

def signal_chart(o, path):
    import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
    ko = korean_font(); T = (lambda k, e: k) if ko else (lambda k, e: e)
    M = rd(f'{o}/market_daily.csv'); M = M[M['kospi'].notna()].tail(60).reset_index(drop=True)
    days = list(M['date']); X = np.arange(len(days)); P = M['kospi'].values; n = len(days)
    rows = signal_rows(o, days)
    fig, ax = plt.subplots(2, 1, figsize=(8, 8.4), dpi=110, sharex=True, gridspec_kw={'height_ratios': [1.25, 2]})
    fig.patch.set_facecolor('white')
    ax[0].plot(X, P, color='#1f3a93', lw=2); up, dn = mark_signals(ax[0], X, P, rows)
    lo, hi = np.nanmin(P), np.nanmax(P); ax[0].set_ylim(lo - (hi - lo) * .3, hi + (hi - lo) * .3)
    on_today = [r[0] for r in rows if (n - 1) in r[2]]
    ax[0].set_title(T(f"매매 신호 전부 · 최근 60거래일 (~{md(days[-1])})", f"All signals, last 60 days (~{days[-1]})"), fontsize=12, loc='left')
    _vk = M[M['vkospi'].notna()]['date'].max() if 'vkospi' in M.columns else None
    if _vk and _vk != days[-1]: ax[0].text(0.01, 0.10, T(f'VKOSPI {md(_vk)}까지 반영 → 매수 최적화 1~3위·매도 민감·중간·엄격형 판정 보류', f'VKOSPI to {_vk}: VKOSPI signals pending'), transform=ax[0].transAxes, fontsize=7.5, color='#a33')
    ax[0].text(0.01, 0.03, T('▲ 매수 시작   ▼ 매도·청산 시작   색 = 아래 신호 이름 색(같은 날 여러 개면 쌓아 표시)', '^ buy start  v sell start'), transform=ax[0].transAxes, fontsize=7.5, color='#444')
    ax[0].text(0.99, 0.95, T('오늘 켜짐: ' + (', '.join(on_today) if on_today else '없음'), 'on today: ' + str(len(on_today))), transform=ax[0].transAxes, ha='right', va='top', fontsize=8, color='#a33', wrap=True,
               bbox=dict(facecolor='white', edgecolor='none', alpha=.85))
    # 아래: 신호별 줄(켜진 기간 막대 + 시작 표시)
    a = ax[1]; R = len(rows)
    for k, (lab, side, on, u, d) in enumerate(rows):
        yv = R - 1 - k; c = sc(lab)
        a.axhspan(yv - .5, yv + .5, color='#fafafa' if k % 2 else 'white', lw=0)
        for i in on: a.barh(yv, 1, left=i - .5, height=.5, color=c, alpha=.35, lw=0)
        for i in u: a.scatter(i, yv, marker='^', s=38, color=c, zorder=4, edgecolor='white', lw=.5)
        for i in d: a.scatter(i, yv, marker='v', s=38, color=c, zorder=4, edgecolor='white', lw=.5)
        if (n - 1) in on: a.text(n - .2, yv, T('켜짐', 'ON'), va='center', fontsize=7, color=c, fontweight='bold')
    sep = [k for k in range(1, R) if rows[k][1] != rows[k - 1][1]]
    for k in sep: a.axhline(R - k - .5, color='#bbb', lw=.7)
    a.set_yticks(range(R)); a.set_yticklabels([r[0] for r in rows][::-1], fontsize=7.5)
    for t, r in zip(a.get_yticklabels(), rows[::-1]): t.set_color(sc(r[0])); t.set_fontweight('bold')
    a.set_ylim(-.5, R - .5); a.set_xlim(-.8, n + 1.2)
    a.set_title(T('신호별 켜진 기간(옅은 막대) · 시작(▲▼)', 'active period (bar) and start (^ v)'), fontsize=10, loc='left')
    step = max(1, n // 6); a.set_xticks(X[::step]); a.set_xticklabels([md(d) for d in days[::step]], fontsize=8)
    for b in ax: b.tick_params(labelsize=8); b.grid(axis='x', color='#f0f0f0'); b.spines['top'].set_visible(False)
    fig.tight_layout(); fig.savefig(path, facecolor='white'); plt.close(fig)
    return on_today

def chart(o, path):
    import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
    ko = korean_font()
    T = (lambda k, e: k) if ko else (lambda k, e: e)
    M = rd(f'{o}/market_daily.csv'); Q = rd(f'{o}/q_daily.csv'); L = rd(f'{o}/liq_daily.csv'); C = rd(f'{o}/credit.csv'); F = rd(f'{o}/flows_daily.csv'); TC = rd(f'{o}/trend_champ.csv')
    M = M[M['kospi'].notna()].copy(); M['ma20'] = M['kospi'].rolling(20).mean(); M = M.tail(60).reset_index(drop=True)
    days = list(M['date']); x = {d: i for i, d in enumerate(days)}; X = np.arange(len(days))
    def sub(df, col): df = df[df['date'].isin(x)].copy(); return [x[d] for d in df['date']], df[col].values
    fig, ax = plt.subplots(4, 1, figsize=(8, 8.4), dpi=110, sharex=True, gridspec_kw={'height_ratios': [2.2, 1.2, 1, 1.2]})
    fig.patch.set_facecolor('white')
    # ① 코스피 + 국면 배경
    RC = {'상승 추세': '#d8f0dc', '하락 추세': '#fbdada', '고변동 청산': '#e2d3f2', '횡보': '#eeeeee'}
    if Q is not None:
        qq = Q[Q['date'].isin(x)]
        for d, r in zip(qq['date'], qq['regime']): ax[0].axvspan(x[d] - .5, x[d] + .5, color=RC.get(r, '#ffffff'), lw=0)
    ax[0].plot(X, M['kospi'], color='#1f3a93', lw=2.2, label=T('코스피', 'KOSPI'))
    ax[0].plot(X, M['ma20'], color='#888', lw=1, ls='--', label=T('20일선', 'MA20'))
    mark_signals(ax[0], X, M['kospi'].values, signal_rows(o, days))
    _lo, _hi = M['kospi'].min(), M['kospi'].max(); ax[0].set_ylim(_lo - (_hi - _lo) * .3, _hi + (_hi - _lo) * .28)
    ax[0].scatter([], [], marker='^', color='#999', label=T('매수 신호(색=신호별)', 'buy')); ax[0].scatter([], [], marker='v', color='#999', label=T('매도 신호(색=신호별)', 'sell'))
    last = M.iloc[-1]
    ax[0].set_title(T(f"코스피 {last['kospi']:,.2f} ({sg(last['kospi_chg_pct'], 2)}%) · {md(last['date'])}", f"KOSPI {last['kospi']:,.2f} ({last['kospi_chg_pct']:+.2f}%) {last['date']}"), fontsize=12, loc='left')
    rg = Q.iloc[-1]['regime'] if Q is not None else ''
    ax[0].text(0.99, 0.95, T(f"국면 {rg} · 5일 급락 {Q.iloc[-1]['p_risk']*100:.0f}%", f"risk5 {Q.iloc[-1]['p_risk']*100:.0f}%") if Q is not None else '', transform=ax[0].transAxes, ha='right', va='top', fontsize=9, color='#a33', bbox=dict(facecolor='white', edgecolor='none', alpha=.8))
    from matplotlib.patches import Patch
    h, l = ax[0].get_legend_handles_labels()
    if Q is not None: h += [Patch(facecolor=c, edgecolor='#999', lw=.5) for c in RC.values()]; l += [T(k, k) for k in RC]
    ax[0].legend(h, l, loc='lower left', fontsize=7, frameon=False, ncol=3)
    # ② 반대매매
    if L is not None:
        xi, v = sub(L, 'liq_eok'); _, r = sub(L, 'ratio_pct')
        ax[1].bar(xi, v, color='#e07b39', width=.8); ax[1].set_ylabel(T('반대매매\n억원', 'forced\n100M'), fontsize=8)
        a2 = ax[1].twinx(); a2.plot(xi, r, color='#7a1f5c', lw=1.4); a2.axhline(5, color='#7a1f5c', lw=.7, ls=':'); a2.set_ylabel(T('비중 %', 'ratio %'), fontsize=8)
        lr = L.iloc[-1]; ax[1].set_title(T(f"미수 반대매매 {lr['liq_eok']:,.0f}억 · 비중 {lr['ratio_pct']:.1f}% ({md(lr['date'])})", f"forced {lr['liq_eok']:,.0f} ratio {lr['ratio_pct']:.1f}%"), fontsize=10, loc='left')
    # ③ 신용
    if C is not None:
        xi, v = sub(C, 'credit_jo'); ax[2].plot(xi, v, color='#2e7d32', lw=1.8); ax[2].set_ylabel(T('조원', 'tril'), fontsize=8)
        lc = C.iloc[-1]; ax[2].set_title(T(f"신용융자 {lc['credit_jo']:.2f}조 ({sg(lc['chg_pct'], 2)}%) · 예탁금 {lc['deposit_jo']:.1f}조 ({md(lc['date'])})", f"margin {lc['credit_jo']:.2f}T"), fontsize=10, loc='left')
    # ④ 외국인 + 12개 해 합의
    if F is not None:
        xi, v = sub(F, 'foreign_jo'); ax[3].bar(xi, v, color=['#c62828' if a > 0 else '#1565c0' for a in v], width=.8); ax[3].axhline(0, color='#999', lw=.6)
        ax[3].set_ylabel(T('외국인\n조원', 'foreign\ntril'), fontsize=8)
        lf = F.iloc[-1]; ttl = T(f"외국인 {sg(lf['foreign_jo'], 2)}조", f"foreign {lf['foreign_jo']:+.2f}T")
        if TC is not None:
            ys = [k for k in TC.columns if k.startswith('y') and k[1:].isdigit()]; TC = TC.copy(); TC['p'] = (TC[ys] == 1).sum(axis=1) / TC[ys].notna().sum(axis=1) * 100
            xi2, p = sub(TC, 'p'); a3 = ax[3].twinx(); a3.plot(xi2, p, color='#555', lw=1.2); a3.axhline(50, color='#555', lw=.6, ls=':'); a3.set_ylim(0, 100); a3.set_ylabel(T('합의 %', 'consensus %'), fontsize=8)
            ttl += T(f" · 12개 해 합의 상승 {p[-1]:.0f}%", f" consensus {p[-1]:.0f}%")
        ax[3].set_title(ttl, fontsize=10, loc='left')
    step = max(1, len(days) // 6); ax[3].set_xticks(X[::step]); ax[3].set_xticklabels([md(d) for d in days[::step]], fontsize=8)
    for a in ax: a.grid(axis='y', color='#eee'); a.tick_params(labelsize=8); [s.set_visible(False) for k, s in a.spines.items() if k in ('top',)]
    fig.tight_layout(); fig.savefig(path, facecolor='white'); plt.close(fig)
    return ko

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--out', default='out'); ap.add_argument('--report', default='report'); ap.add_argument('--signals', default=''); ap.add_argument('--tag', default='')
    a = ap.parse_args(); os.makedirs(a.report, exist_ok=True)
    LJ = json.load(open(a.signals, encoding='utf-8')) if a.signals and os.path.exists(a.signals) else {}
    sig = LJ.get('signals_new', [])
    A = alerts(a.out, sig)
    ko = chart(a.out, os.path.join(a.report, 'chart.png'))
    on_today = signal_chart(a.out, os.path.join(a.report, 'signals.png'))
    M = rd(f'{a.out}/market_daily.csv'); d = str(M[M['kospi'].notna()].iloc[-1]['date'])
    json.dump({'date': d, 'tag': a.tag, 'label': {'0831': '아침 확정', '1540': '잠정 15:37', '1840': '확정 20:37'}.get(a.tag, a.tag), 'alerts': A, 'korean_font': ko, 'signals_on_today': on_today, 'vkospi_hold': LJ.get('vkospi_hold', False), 'vkospi_date': (LJ.get('values') or {}).get('vkospi_date')}, open(os.path.join(a.report, 'alerts.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('그래프 report/chart.png · report/signals.png ·', '한글 글꼴' if ko else '한글 글꼴 없음(영문 표기)', '· 중요 변동', len(A), '건'); [print(' -', x) for x in A]

if __name__ == '__main__': main()
