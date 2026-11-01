# -*- coding: utf-8 -*-
"""report_signals.py — reproduce.py 결과(out/)에서 오늘 상황·매매 신호를 뽑아 보고문을 만든다.
   출력: report/latest.json (기계용 상태), report/latest.md (사람용 전체 보고), report/kakao.txt (카카오톡 1~2통, 각 200자 이내)
   사용: python report_signals.py --out out --report report --tag 1840 [--summary data/update_summary.json] [--link https://claude.ai/artifact/...]
"""
import argparse, json, os, datetime as dt
import pandas as pd

KST = dt.timezone(dt.timedelta(hours=9))
def rd(p): return pd.read_csv(p) if os.path.exists(p) else None
def md(d): return f'{int(d[5:7])}/{int(d[8:10])}'
def f1(v, n=2): return '—' if v is None or (isinstance(v, float) and pd.isna(v)) else f'{v:,.{n}f}'

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--out', default='out'); ap.add_argument('--report', default='report'); ap.add_argument('--tag', default='')
    ap.add_argument('--summary', default='data/update_summary.json'); ap.add_argument('--link', default='https://claude.ai/artifact/LREkdE8UfEYhuNn6Jpn67c'); ap.add_argument('--repo', default='')
    a = ap.parse_args(); os.makedirs(a.report, exist_ok=True); now = dt.datetime.now(KST)
    prev = json.load(open(os.path.join(a.report, 'latest.json'), encoding='utf-8')) if os.path.exists(os.path.join(a.report, 'latest.json')) else {}
    summ = json.load(open(a.summary, encoding='utf-8')) if os.path.exists(a.summary) else {}
    M = rd(f'{a.out}/market_daily.csv'); L = rd(f'{a.out}/liq_daily.csv'); C = rd(f'{a.out}/credit.csv'); F = rd(f'{a.out}/flows_daily.csv')
    Q = rd(f'{a.out}/q_daily.csv'); QN = rd(f'{a.out}/q_now.csv'); AL = rd(f'{a.out}/alarms.csv'); B3 = rd(f'{a.out}/buy3.csv'); S3 = rd(f'{a.out}/sell3.csv'); RE = rd(f'{a.out}/reentry.csv'); NF = rd(f'{a.out}/night_fut.csv')
    m = M.iloc[-1]; today = m['date']; prelim = a.tag.startswith('1540')
    # ---- 값
    vk_row = M[M['vkospi'].notna()].iloc[-1]; vk_lag = vk_row['date'] != today
    l = L.iloc[-1]; c = C.iloc[-1]; fr = F[F['date'] == today]; fr = fr.iloc[-1] if len(fr) else None
    q = Q[Q['date'] == today]; q = q.iloc[-1] if len(q) else Q.iloc[-1]
    cd_ratio = (c['credit_jo'] / c['deposit_jo'] * 100) if c['deposit_jo'] else None
    # ---- 큰 흐름 12개 해 합의: 그해 1위 12줄(trend_champ.csv y2015~) 중 상승·하락 줄 수와 비율, 전 거래일·5거래일 전 대비
    TCD = rd(f'{a.out}/trend_champ.csv'); cons = None
    if TCD is not None and len(TCD) > 1:
        TCD = TCD.sort_values('date').reset_index(drop=True)
        ys = [k for k in TCD.columns if k.startswith('y') and k[1:].isdigit()]
        cu = (TCD[ys] == 1).sum(axis=1); cdn = (TCD[ys] == -1).sum(axis=1)
        def _ce(j):
            if j < 0 or cu.iloc[j] + cdn.iloc[j] == 0: return None
            return {'date': str(TCD['date'].iloc[j]), 'up': int(cu.iloc[j]), 'dn': int(cdn.iloc[j]), 'pct': round(float(cu.iloc[j] / (cu.iloc[j] + cdn.iloc[j]) * 100), 2)}
        n0 = len(TCD) - 1; cons = {'now': _ce(n0), 'p1': _ce(n0 - 1), 'p5': _ce(n0 - 5)} if _ce(n0) else None
    def pm(v): return ('+' if v > 0 else '−' if v < 0 else '±') + f'{abs(v):.0f}'
    def cons_txt(cs):
        n, p1, p5 = cs['now'], cs['p1'], cs['p5']
        t = f"12개 해 합의 상승 {n['up']} · 하락 {n['dn']}(상승 {n['pct']:.0f}%)"
        if p1: t += f" — 전 거래일 {md(p1['date'])} {p1['pct']:.0f}%에서 {pm(n['pct'] - p1['pct'])}%p(상승 줄 {pm(n['up'] - p1['up'])})"
        if p5: t += f", 5거래일 전 {md(p5['date'])} {p5['pct']:.0f}%에서 {pm(n['pct'] - p5['pct'])}%p(상승 줄 {pm(n['up'] - p5['up'])})"
        return t
    # ---- 신호
    sig_new, sig_on, sig_off = [], [], []
    def scan(df, label_fn, top_only=False):
        if df is None or not len(df): return
        d = df[df['date'] == today]
        for _, r in d.iterrows():
            lab = label_fn(r)
            if top_only and str(r.get('rank', '')) not in ('1', '1.0'): continue
            (sig_new if r.get('start', '시작') == '시작' else sig_on).append({'label': lab, 'since': r['date'], 'rule': str(r.get('rule', ''))})
        # 지속 중인데 오늘 줄이 없어진 것(= 끝남): 어제 '지속/시작'이던 것
        if 'start' in df.columns:
            prevd = df[df['date'] < today]
            if len(prevd):
                last_day = prevd['date'].max(); yest = prevd[prevd['date'] == last_day]
                for _, r in yest.iterrows():
                    if top_only and str(r.get('rank', '')) not in ('1', '1.0'): continue
                    lab = label_fn(r)
                    if not any(s['label'] == lab for s in sig_new + sig_on) and prev.get('date') and last_day >= prev.get('date', '') and last_day != today:
                        if (pd.to_datetime(today) - pd.to_datetime(last_day)).days <= 5: sig_off.append({'label': lab, 'until': last_day})
    scan(AL, lambda r: f"{r['side']} {r['type']}")
    scan(B3, lambda r: f"매수 최적화 {int(r['rank'])}위", top_only=False)
    scan(S3, lambda r: f"매도 최적화 {int(r['rank'])}위", top_only=False)
    # 지속 중인 신호(오늘 줄이 '지속'인 것)의 시작일
    def since_of(df, rank):
        if df is None: return None
        x = df[(df['rank'] == rank)]
        if not len(x) or x.iloc[-1]['date'] != today: return None
        st = x[x['start'] == '시작']; return st.iloc[-1]['date'] if len(st) else x.iloc[0]['date']
    re_state = RE.iloc[-1] if RE is not None and len(RE) else None
    re_today = RE[RE['date'] == today] if RE is not None else pd.DataFrame()
    qtrade = q.get('trade') if isinstance(q.get('trade'), str) else None
    # ---- 상태 요약 문장
    hdr = f"[대시보드 {md(today)} {'잠정 15:40' if prelim else '확정 18:40'}]"
    k_line = f"코스피 {m['kospi']:,.2f}({m['kospi_chg_pct']:+.2f}%)"
    v_line = f"VKOSPI {vk_row['vkospi']:.2f}" + (f"({md(vk_row['date'])})" if vk_lag else '')
    reg = f"{q['regime']} · 10일↑ {q['p_up']*100:.0f}% · 5일 급락 {q['p_risk']*100:.0f}%"
    cr_line = f"신용 {c['credit_jo']:.2f}조 예탁 {c['deposit_jo']:.1f}조" + (f" 비율 {cd_ratio:.0f}%" if cd_ratio else '') + f"({md(c['date'])})"
    lq_line = f"반대매매 {l['liq_eok']:.0f}억·{l['ratio_pct']:.1f}%({md(l['date'])})"
    fo_line = (f"외인 {fr['foreign_jo']*10000:+,.0f}억 기관 {fr['inst_jo']*10000:+,.0f} 개인 {fr['indiv_jo']*10000:+,.0f}" + (' (잠정)' if '잠정' in str(fr.get('basis', '')) else '')) if fr is not None else '투자자별 오늘 줄 없음'
    top_buy = since_of(B3, 1); top_sell = since_of(S3, 1)
    sig_short = []
    for s in sig_new: sig_short.append('★새 ' + s['label'])
    if top_buy and not any('매수 최적화 1위' in s['label'] for s in sig_new): sig_short.append(f"매수1위 지속({md(top_buy)}~)")
    if top_sell and not any('매도 최적화 1위' in s['label'] for s in sig_new): sig_short.append(f"매도1위 지속({md(top_sell)}~)")
    for s in sig_off: sig_short.append('끝 ' + s['label'])
    if qtrade: sig_short.append('정밀검증 ' + ('진입' if qtrade == 'enter' else '청산'))
    if re_state is not None: sig_short.append(f"재진입 {re_state['state']}" + (f"·오늘 {re_today.iloc[-1]['action']}" if len(re_today) else ''))
    sig_line = '신호: ' + (' / '.join(sig_short) if sig_short else '새 신호 없음(1위 매수·매도 모두 꺼짐)')
    msg1 = '\n'.join([hdr, k_line + ' ' + v_line, reg, cr_line, lq_line, fo_line, sig_line])
    if len(msg1) > 200: msg1 = '\n'.join([hdr, k_line + ' ' + v_line, reg, cr_line, sig_line])[:200]
    msgs = [msg1]
    if sig_new or sig_off or qtrade or len(re_today):
        lines = [f"[{md(today)} 신호 상세]"]
        for s in sig_new: lines.append(f"★ {s['label']} 시작: {s['rule'][:60]}")
        for s in sig_off: lines.append(f"끝 {s['label']} ({md(s['until'])}까지)")
        if qtrade: lines.append(f"정밀 검증 전략 {'진입(다음 종가 매수, 10일 보유)' if qtrade == 'enter' else '청산'}")
        for _, r in re_today.iterrows(): lines.append(f"재진입 규칙: {r['action']} — {r['reason']}")
        m2 = '\n'.join(lines)
        msgs.append(m2 if len(m2) <= 200 else m2[:197] + '…')
    if cons and cons['p1']:
        cn, cp = cons['now'], cons['p1']; side = lambda e: (e['up'] > e['dn']) - (e['dn'] > e['up'])
        same_as_prev = prev.get('date') == today and (prev.get('consensus') or {}).get('now') == cn
        if (abs(cn['up'] - cp['up']) >= 2 or side(cn) != side(cp)) and not same_as_prev:
            msgs.append(f"[{md(today)} 큰 흐름 12개 해 합의]\n상승 {cn['up']}·하락 {cn['dn']}(상승 {cn['pct']:.0f}%)\n전 거래일 {cp['up']}·{cp['dn']}({cp['pct']:.0f}%) → {pm(cn['pct'] - cp['pct'])}%p")
    # 15:40 → 18:40 차이
    diffs = []
    if prev and prev.get('date') == today and prev.get('tag', '').startswith('1540') and not prelim:
        for k, lab in (('kospi', '코스피'), ('foreign_jo', '외국인(조)'), ('inst_jo', '기관(조)'), ('indiv_jo', '개인(조)'), ('regime', '국면'), ('p_up', '10일↑'), ('p_risk', '급락')):
            if str(prev.get('values', {}).get(k)) != str(_v := {'kospi': m['kospi'], 'foreign_jo': fr['foreign_jo'] if fr is not None else None, 'inst_jo': fr['inst_jo'] if fr is not None else None, 'indiv_jo': fr['indiv_jo'] if fr is not None else None, 'regime': q['regime'], 'p_up': q['p_up'], 'p_risk': q['p_risk']}[k]):
                diffs.append(f"{lab} {prev.get('values', {}).get(k)} → {_v}")
        ps = set(prev.get('signals_new', [])) | set(prev.get('signals_on', [])); ns = {s['label'] for s in sig_new + sig_on}
        if ps != ns: diffs.append(f"신호 {sorted(ps)} → {sorted(ns)}")
        if diffs: msgs.append(('[15:40 잠정 → 18:40 확정 변경]\n' + '\n'.join(diffs))[:200])
    # ---- 파일
    state = {'date': today, 'tag': a.tag, 'run_at': now.strftime('%Y-%m-%d %H:%M'), 'prelim': prelim,
             'values': {'kospi': float(m['kospi']), 'kospi_chg_pct': float(m['kospi_chg_pct']), 'vkospi': float(vk_row['vkospi']), 'vkospi_date': vk_row['date'],
                        'credit_jo': float(c['credit_jo']), 'deposit_jo': float(c['deposit_jo']), 'credit_date': c['date'], 'liq_eok': float(l['liq_eok']), 'liq_ratio': float(l['ratio_pct']), 'liq_date': l['date'],
                        'foreign_jo': None if fr is None else float(fr['foreign_jo']), 'inst_jo': None if fr is None else float(fr['inst_jo']), 'indiv_jo': None if fr is None else float(fr['indiv_jo']),
                        'regime': q['regime'], 'p_up': float(q['p_up']), 'p_risk': float(q['p_risk']), 'q_trade': qtrade, 'reentry_state': None if re_state is None else re_state['state']},
             'signals_new': [s['label'] for s in sig_new], 'signals_on': [s['label'] for s in sig_on], 'signals_off': [s['label'] for s in sig_off], 'top_buy_since': top_buy, 'top_sell_since': top_sell,
             'data_dates': {'kospi': today, 'kofia': c['date'], 'vkospi': vk_row['date'], 'night': None if NF is None or not len(NF) else NF.iloc[-1]['night_date']},
             'update_summary': {k: v for k, v in summ.items() if k != 'changes'}, 'changes_n': len(summ.get('changes', [])), 'kakao': msgs, 'diffs_vs_1540': diffs, 'consensus': cons}
    json.dump(state, open(os.path.join(a.report, 'latest.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    open(os.path.join(a.report, 'kakao.txt'), 'w', encoding='utf-8').write('\n=====\n'.join(msgs) + '\n')
    # 사람용 md
    md_lines = [f"# 대시보드 자동 갱신 보고 — {today} {'잠정(15:40)' if prelim else '확정(18:40)'} · 실행 {now:%Y-%m-%d %H:%M} KST", '',
                '| 항목 | 값 | 기준일 |', '|---|---|---|', f"| 코스피 | {m['kospi']:,.2f} ({m['kospi_chg_pct']:+.2f}%) | {today} |", f"| VKOSPI | {vk_row['vkospi']:.2f}{' (당일 미수집, 전일 값)' if vk_lag else ''} | {vk_row['date']} |",
                f"| 국면 / 10일 상승 확률 / 5일 급락 확률 | {q['regime']} / {q['p_up']*100:.1f}% / {q['p_risk']*100:.1f}% | {q['date'] if 'date' in q else today} |",
                f"| 신용융자 / 예탁금 / 비율 | {c['credit_jo']:.3f}조 / {c['deposit_jo']:.3f}조 / {f1(cd_ratio,1)}% | {c['date']} |", f"| 미수 반대매매 / 비중 / 미수금 | {l['liq_eok']:.2f}억 / {l['ratio_pct']:.1f}% / {l['misu_eok']:,.0f}억 | {l['date']} |",
                (f"| 투자자별 순매수(조) 외국인/기관/개인/기타 | {fr['foreign_jo']:+.4f} / {fr['inst_jo']:+.4f} / {fr['indiv_jo']:+.4f} / {fr['other_jo']:+.4f} ({fr['basis']}) | {today} |" if fr is not None else '| 투자자별 | 오늘 줄 없음 | — |'), '',
                '## 매매 신호', '']
    if sig_new: md_lines += [f"- ★ 새 신호: **{s['label']}** — {s['rule']}" for s in sig_new]
    if sig_on: md_lines += [f"- 지속: {s['label']}" + (f" ({md(top_buy)}~)" if '매수 최적화 1위' in s['label'] and top_buy else '') + (f" ({md(top_sell)}~)" if '매도 최적화 1위' in s['label'] and top_sell else '') for s in sig_on]
    if sig_off: md_lines += [f"- 끝: {s['label']} ({s['until']}까지)" for s in sig_off]
    if qtrade: md_lines.append(f"- 정밀 검증 전략: {'진입' if qtrade == 'enter' else '청산'}")
    if re_state is not None: md_lines.append(f"- 재진입 규칙 상태: {re_state['state']} (마지막 {re_state['date']} {re_state['action']})")
    if not (sig_new or sig_on or sig_off or qtrade): md_lines.append('- 오늘 켜진 신호 없음')
    md_lines += ['', '## 정밀 검증 현재 값', '', '| 항목 | 값 | 설명 |', '|---|---|---|'] + [f"| {r['item']} | {'' if pd.isna(r['value']) else r['value']} | {r['text']} |" for _, r in QN.iterrows()] if QN is not None else []
    TC = rd(f'{a.out}/trend_champ_rules.csv')
    if TC is not None and len(TC):
        tc = TC.sort_values(['acc_r60', 'acc_r20', 'acc_last_year'], ascending=False)
        md_lines += ['', '## 큰 흐름: 그해 1위 조합 중 지금 잘 맞는 순(최근 60거래일)', '', '| 순서 | 그해 1위 | 조합·설정 | 최근 60일 | 최근 20일 | 올해 | 다음 해(실사용) | 지금 |', '|---|---|---|---|---|---|---|---|']
        md_lines += [f"| {i + 1} | {int(r['year'])} | {r['rule']} | {r['acc_r60']} | {r['acc_r20']} | {r['acc_last_year']} | {'' if pd.isna(r['acc_next']) else r['acc_next']} | {r['now']} |" for i, (_, r) in enumerate(tc.head(5).iterrows())]
        md_lines += [f"- 12줄의 지금 판단: " + (cons_txt(cons) if cons else f"상승 {(TC['now'] == '상승').sum()} · 하락 {(TC['now'] == '하락').sum()}") + ". 올해 1위는 자료가 들어올 때마다 다시 찾는다(실제 큰 흐름 마지막 구간은 10% 되돌림 확인 전까지 잠정)."]
    md_lines += ['', '## 자료 갱신', '', f"- 수집 실행: {summ.get('run', '—')} · 코스피 {summ.get('kospi_last', '—')} · 금투협 {summ.get('kofia_last', '—')} · VKOSPI {summ.get('vkospi_last', '—')} · 야간선물 {summ.get('night_last', '—')}",
                f"- 들어온 자료: " + ', '.join(f"{x[0]} {x[1]}" for x in summ.get('files', [])), f"- 값 교체 {len(summ.get('changes', []))}건(엑셀 「값_교체_기록」)"]
    if diffs: md_lines += ['', '## 15:40 잠정 → 18:40 확정 변경', ''] + [f'- {d}' for d in diffs]
    md_lines += ['', f"- 대시보드: {a.link}", '', '투자 권유 아님']
    open(os.path.join(a.report, 'latest.md'), 'w', encoding='utf-8').write('\n'.join(md_lines) + '\n')
    hist = os.path.join(a.report, 'history'); os.makedirs(hist, exist_ok=True)
    open(os.path.join(hist, f"{today}_{a.tag or 'run'}.md"), 'w', encoding='utf-8').write('\n'.join(md_lines) + '\n')
    print('\n=====\n'.join(msgs))

if __name__ == '__main__': main()
