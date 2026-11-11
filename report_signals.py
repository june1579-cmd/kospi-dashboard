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

LABEL = {'0831': '아침 확정·VKOSPI 반영 08:31', '1540': '잠정 15:37(투자자별 정규장만)', '1840': '확정 20:37(KRX 애프터마켓 포함)'}
SHORT = {'0831': '아침 확정', '1540': '잠정', '1840': '확정'}
VK_SIGS = ['매수 최적화 1위', '매수 최적화 2위', '매수 최적화 3위', '매도 민감형', '매도 중간형', '매도 엄격형']
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
    # ---- 이미 카톡으로 보낸 신호 기록: 같은 신호를 세 번 실행마다 '새 신호'로 반복하지 않고, 다음 날 VKOSPI 가 들어와 전 거래일 날짜로 생긴 신호는 '늦게 확인'으로 보낸다
    sp = os.path.join(a.report, 'sent_signals.json'); first = not os.path.exists(sp)
    sent = set(tuple(x) for x in json.load(open(sp, encoding='utf-8'))) if not first else set()
    starts = []
    for df, fn in ((AL, lambda r: f"{r['side']} {r['type']}"), (B3, lambda r: f"매수 최적화 {int(r['rank'])}위"), (S3, lambda r: f"매도 최적화 {int(r['rank'])}위")):
        if df is None or 'start' not in df.columns: continue
        for _, r in df[(df['start'] == '시작') & (df['date'] >= (dt.date.fromisoformat(str(today)[:10]) - dt.timedelta(days=10)).isoformat())].iterrows():
            starts.append((r['date'], fn(r), str(r.get('rule', ''))))
    if first: sent = {(d, lab) for d, lab, _ in starts if d < today}
    late = [{'label': lab, 'date': d, 'rule': rule} for d, lab, rule in starts if d < today and (d, lab) not in sent]
    for s_ in sig_new: s_['repeat'] = (today, s_['label']) in sent
    sent |= {(d, lab) for d, lab, _ in starts}
    json.dump(sorted(sent), open(sp, 'w', encoding='utf-8'), ensure_ascii=False)
    vk_hold = bool(vk_lag)
    # 지속 중인 신호(오늘 줄이 '지속'인 것)의 시작일
    def since_of(df, rank):
        if df is None: return None
        x = df[(df['rank'] == rank)]
        if not len(x) or x.iloc[-1]['date'] != today: return None
        st = x[x['start'] == '시작']; return st.iloc[-1]['date'] if len(st) else x.iloc[0]['date']
    re_state = RE.iloc[-1] if RE is not None and len(RE) else None
    re_today = RE[RE['date'] == today] if RE is not None else pd.DataFrame()
    qtrade = q.get('trade') if isinstance(q.get('trade'), str) else None
    # 정밀 검증 전략 보유 중(진입 뒤 청산 전): 마지막 enter 가 마지막 exit 보다 뒤면 보유 중. 청산 예정 = 진입 신호일 다음 거래일 종가 매수 + 10거래일(11/11 추가)
    qhold = None
    try:
        tr = Q['trade'].fillna('').astype(str).tolist(); ie = max([i for i, t in enumerate(tr) if t == 'enter'], default=-1); ix = max([i for i, t in enumerate(tr) if t == 'exit'], default=-1)
        if ie > ix: qhold = {'since': str(Q.iloc[ie]['date']), 'day': len(Q) - 1 - ie - 1, 'left': max(0, 10 - (len(Q) - 1 - ie))}
    except Exception: qhold = None
    # ---- 상태 요약 문장
    hdr = f"[대시보드 {md(today)} {LABEL.get(a.tag[:4], a.tag)}]"
    k_line = f"코스피 {m['kospi']:,.2f}({m['kospi_chg_pct']:+.2f}%)"
    v_line = f"VKOSPI {vk_row['vkospi']:.2f}" + (f"({md(vk_row['date'])})" if vk_lag else '')
    reg = f"{q['regime']} · 10일↑ {q['p_up']*100:.0f}% · 5일 급락 {q['p_risk']*100:.0f}%"
    cr_line = f"신용 {c['credit_jo']:.2f}조 예탁 {c['deposit_jo']:.1f}조" + (f" 비율 {cd_ratio:.0f}%" if cd_ratio else '') + f"({md(c['date'])})"
    lq_line = f"반대매매 {l['liq_eok']:.0f}억·{l['ratio_pct']:.1f}%({md(l['date'])})"
    fo_line = (f"외인 {fr['foreign_jo']*10000:+,.0f}억 기관 {fr['inst_jo']*10000:+,.0f} 개인 {fr['indiv_jo']*10000:+,.0f}" + (' (정규장 집계)' if '잠정' in str(fr.get('basis', '')) else ' (KRX 전체, NXT 제외)')) if fr is not None else '투자자별 오늘 줄 없음'
    top_buy = since_of(B3, 1); top_sell = since_of(S3, 1)
    sig_short = []
    for s in late: sig_short.append(f"★늦게 확인 {s['label']}({md(s['date'])})")
    for s in sig_new: sig_short.append(('첫날 ' if s.get('repeat') else '★새 ') + s['label'])
    if vk_hold: sig_short.append(f"VKOSPI {md(vk_row['date'])}까지 → VKOSPI 신호 보류")
    if top_buy and not any('매수 최적화 1위' in s['label'] for s in sig_new): sig_short.append(f"매수1위 지속({md(top_buy)}~)")
    if top_sell and not any('매도 최적화 1위' in s['label'] for s in sig_new): sig_short.append(f"매도1위 지속({md(top_sell)}~)")
    for s in sig_off: sig_short.append('끝 ' + s['label'])
    if qtrade: sig_short.append('정밀검증 ' + ('진입' if qtrade == 'enter' else '청산'))
    elif qhold: sig_short.append(f"정밀검증 보유({md(qhold['since'])} 진입, {qhold['left']}거래일 뒤 청산)")
    if re_state is not None: sig_short.append(f"재진입 {re_state['state']}" + (f"·오늘 {re_today.iloc[-1]['action']}" if len(re_today) else ''))
    sig_line = '신호: ' + (' / '.join(sig_short) if sig_short else '새 신호 없음(1위 매수·매도 모두 꺼짐)')
    msg1 = '\n'.join([hdr, k_line + ' ' + v_line, reg, cr_line, lq_line, fo_line, sig_line])
    if len(msg1) > 200: msg1 = '\n'.join([hdr, k_line + ' ' + v_line, reg, cr_line, sig_line])[:200]
    # ---- 카톡(11/11 개편): 실행마다 한 통 — 코스피 등락 / 자료 성공·오류 / 매수·매도·특이 신호 / 외인·개인·기관 / 신용·반대매매 / (필요할 때만) 대시보드 확인 사유
    #      '자료:' 줄의 @@DATA@@ 는 run_pipeline.py 가 오류 목록으로 채운다(오류는 이 파일 밖에서 모인다)
    buys = [s['label'].replace('매수 ', '') for s in sig_new if s['label'].startswith('매수')] + [s['label'].replace('매수 ', '') + f"({md(s['date'])}분)" for s in late if s['label'].startswith('매수')]
    sells = [s['label'].replace('매도 ', '') for s in sig_new if s['label'].startswith('매도')] + [s['label'].replace('매도 ', '') + f"({md(s['date'])}분)" for s in late if s['label'].startswith('매도')]
    if re_today is not None and len(re_today):
        act = str(re_today.iloc[-1]['action']); (buys if '매수' in act else sells).append('재진입 ' + act)
    if qtrade: (buys if qtrade == 'enter' else sells).append('정밀검증 ' + ('진입' if qtrade == 'enter' else '청산'))
    def eok(v): return ('+' if v >= 0 else '−') + (f'{abs(v):.1f}조' if abs(v) >= 1 else f'{abs(v) * 10000:,.0f}억')
    def eokp(v): return ('+' if float(v) >= 0 else '−') + f'{abs(float(v)):.1f}%'
    special = []                                              # 특이 신호: 매수·매도 규칙 밖에서 평소와 다른 것
    try:
        qi = Q.index[Q['date'] == q['date']][-1]; pr_prev = float(Q.loc[qi - 1, 'p_risk']) if qi > 0 and pd.notna(Q.loc[qi - 1, 'p_risk']) else None
        if qi > 0 and str(Q.loc[qi - 1, 'regime']) != str(q['regime']): special.append(f"국면 {Q.loc[qi - 1, 'regime']}→{q['regime']}")
    except Exception: pass
    if abs(float(m['kospi_chg_pct'])) >= 3: special.append(f"코스피 {eokp(m['kospi_chg_pct'])}")
    if pd.notna(c.get('chg_pct')) and abs(float(c['chg_pct'])) >= 3: special.append(f"신용 {eokp(c['chg_pct'])}")
    if cons and cons.get('p1'):
        _sd = lambda e: (e['up'] > e['dn']) - (e['dn'] > e['up'])
        if _sd(cons['now']) != _sd(cons['p1']) or abs(cons['now']['up'] - cons['p1']['up']) >= 2: special.append(f"상승 합의 {cons['p1']['up']}→{cons['now']['up']}/12")
    credit_d = None
    if len(C) > 1 and pd.notna(C.iloc[-2]['credit_jo']): credit_d = float(c['credit_jo']) - float(C.iloc[-2]['credit_jo'])
    def build_kakao(extra_special=()):
        sp_all = special + list(extra_special)
        L1 = f"[{md(today)} {SHORT.get(a.tag[:4], a.tag)}] 코스피 {m['kospi']:,.0f} ({'+' if m['kospi_chg_pct'] >= 0 else '−'}{abs(m['kospi_chg_pct']):.2f}%)"
        L2 = '자료: @@DATA@@'
        L3 = '매수 ' + ('★' + ', '.join(buys) if buys else '없음') + ' · 매도 ' + ('★' + ', '.join(sells) if sells else '없음')
        L4 = '특이: ' + (', '.join(sp_all) if sp_all else '없음')          # 특이 내용은 줄이지 않고 그대로 적는다
        L5 = (f"외인 {eok(fr['foreign_jo'])} 개인 {eok(fr['indiv_jo'])} 기관 {eok(fr['inst_jo'])}" + (' (잠정)' if '잠정' in str(fr.get('basis', '')) else '')) if fr is not None else '외인·개인·기관: 오늘 줄 없음'
        L6 = f"신용 {c['credit_jo']:.1f}조" + (f"({eok(credit_d)})" if credit_d is not None else '') + f" 반대매매 {l['liq_eok']:,.0f}억·{l['ratio_pct']:.1f}% ({md(c['date'])})"
        why = (['매수 신호'] if buys else []) + (['매도 신호'] if sells else []) + sp_all
        L7 = '▶대시보드 확인' if why else ''
        return '\n'.join(x for x in [L1, L2, L3, L4, L5, L6, L7] if x)[:200], why
    kakao_one, check_why = build_kakao()
    kakao_msgs = [kakao_one]
    msgs = [msg1]
    if sig_new or sig_off or qtrade or len(re_today) or late or vk_hold:
        lines = [f"[{md(today)} 신호 상세]"]
        for s in late: lines.append(f"★ 늦게 확인(VKOSPI 반영) {s['label']} {md(s['date'])} 시작: {s['rule'][:50]}")
        if vk_hold: lines.append(f"판정 보류(그날 VKOSPI 없음, {md(vk_row['date'])}까지): 매수 최적화 1~3위·매도 민감·중간·엄격형 → 다음 날 08:31 확정")
        for s in sig_new: lines.append(f"{'(이미 알림) ' if s.get('repeat') else '★ '}{s['label']} 시작: {s['rule'][:60]}")
        for s in sig_off: lines.append(f"끝 {s['label']} ({md(s['until'])}까지)")
        if qtrade: lines.append(f"정밀 검증 전략 {'진입(다음 종가 매수, 10일 보유)' if qtrade == 'enter' else '청산'}")
        elif qhold: lines.append(f"정밀 검증 전략 보유 중({md(qhold['since'])} 종가 진입, {qhold['left']}거래일 뒤 청산 예정)")
        for _, r in re_today.iterrows(): lines.append(f"재진입 규칙: {r['action']} — {r['reason']}")
        m2 = '\n'.join(lines)
        msgs.append(m2 if len(m2) <= 200 else m2[:197] + '…')
    if cons and cons['p1']:
        cn, cp = cons['now'], cons['p1']; side = lambda e: (e['up'] > e['dn']) - (e['dn'] > e['up'])
        same_as_prev = prev.get('date') == today and (prev.get('consensus') or {}).get('now') == cn
        if (abs(cn['up'] - cp['up']) >= 2 or side(cn) != side(cp)) and not same_as_prev:
            msgs.append(f"[{md(today)} 큰 흐름 12개 해 합의]\n상승 {cn['up']}·하락 {cn['dn']}(상승 {cn['pct']:.0f}%)\n전 거래일 {cp['up']}·{cp['dn']}({cp['pct']:.0f}%) → {pm(cn['pct'] - cp['pct'])}%p")
    # ---- 매수×매도 조합 감시(combo_now): 1위 조합이 바뀌었거나 성적 저하 경고가 새로 켜졌을 때만 한 통
    CN = rd(f'{a.out}/combo_now.csv'); combo = None
    if CN is not None and len(CN):
        cn = CN.iloc[-1]; combo = {k: (None if pd.isna(cn[k]) else (cn[k].item() if hasattr(cn[k], 'item') else cn[k])) for k in CN.columns}
        pc = (prev.get('combo') or {}) if prev else {}
        combo['prev_top'] = pc.get('top_combo') if (pc.get('top_combo') and pc.get('top_combo') != combo['top_combo']) else None
        combo['warn_new'] = bool(combo.get('warn')) and combo['warn'] != pc.get('warn')
        # 조합 1위가 바뀌면 결론 맨 위에 안내(제목 바로 아래), 성적 저하 경고도 같은 자리
        top_note = None
        if combo['prev_top']: top_note = f"★조합 1위 교체 「{combo['top_combo']}」(이전 「{combo['prev_top']}」) 250일 {combo['win_ret_250']:+.0f}%·적중 {combo['win_hit']:.0f}%·지금 {combo['state']}"
        elif combo.get('warn_new'): top_note = f"⚠조합 1위 성적 저하: {combo['top_combo']} — {str(combo['warn']).split(' — ')[0]}"
        if top_note:
            kakao_one, check_why = build_kakao([('조합 1위 교체 → ' + str(combo['top_combo'])) if combo['prev_top'] else '조합 1위 성적 저하']); kakao_msgs[0] = kakao_one
        if combo['prev_top']:
            msgs.append(f"[{md(today)} 조합 1위 교체]\n「{pc.get('top_combo')}」 ⇒ 「{combo['top_combo']}」\n지난 250일 {combo['win_ret_250']:+.1f}% · 거래 {combo['win_trades']}건 적중 {combo['win_hit']:.0f}%\n지금 {combo['state']} · 규칙: 매월 첫 거래일 재선정"[:200])
        elif combo.get('warn') and combo['warn'] != pc.get('warn'):
            msgs.append(f"[{md(today)} 조합 1위 성적 저하]\n{combo['top_combo']} ({md(combo['chosen_since'])}~)\n{combo['warn']}\n다음 재선정 {combo['next_select']}"[:200])
    # 15:40 → 18:40 차이
    diffs = []
    if prev and prev.get('date') == today and prev.get('tag', '')[:4] != a.tag[:4]:
        for k, lab in (('kospi', '코스피'), ('foreign_jo', '외국인(조)'), ('inst_jo', '기관(조)'), ('indiv_jo', '개인(조)'), ('regime', '국면'), ('p_up', '10일↑'), ('p_risk', '급락')):
            if str(prev.get('values', {}).get(k)) != str(_v := {'kospi': m['kospi'], 'foreign_jo': fr['foreign_jo'] if fr is not None else None, 'inst_jo': fr['inst_jo'] if fr is not None else None, 'indiv_jo': fr['indiv_jo'] if fr is not None else None, 'regime': q['regime'], 'p_up': q['p_up'], 'p_risk': q['p_risk']}[k]):
                diffs.append(f"{lab} {prev.get('values', {}).get(k)} → {_v}")
        ps = {x for x in set(prev.get('signals_new', [])) | set(prev.get('signals_on', [])) if not x.endswith('(늦게 확인)')}; ns = {s['label'] for s in sig_new + sig_on}
        if ps != ns: diffs.append(f"신호 {sorted(ps)} → {sorted(ns)}")
        if diffs: msgs.append((f"[{LABEL.get(prev.get('tag', '')[:4], prev.get('tag', ''))} → {LABEL.get(a.tag[:4], a.tag)} 변경]\n" + '\n'.join(diffs))[:200])
    # ---- 파일
    state = {'date': today, 'tag': a.tag, 'run_at': now.strftime('%Y-%m-%d %H:%M'), 'prelim': prelim,
             'values': {'kospi': float(m['kospi']), 'kospi_chg_pct': float(m['kospi_chg_pct']), 'vkospi': float(vk_row['vkospi']), 'vkospi_date': vk_row['date'],
                        'credit_jo': float(c['credit_jo']), 'deposit_jo': float(c['deposit_jo']), 'credit_date': c['date'], 'liq_eok': float(l['liq_eok']), 'liq_ratio': float(l['ratio_pct']), 'liq_date': l['date'],
                        'foreign_jo': None if fr is None else float(fr['foreign_jo']), 'inst_jo': None if fr is None else float(fr['inst_jo']), 'indiv_jo': None if fr is None else float(fr['indiv_jo']),
                        'regime': q['regime'], 'p_up': float(q['p_up']), 'p_risk': float(q['p_risk']), 'q_trade': qtrade, 'reentry_state': None if re_state is None else re_state['state']},
             'signals_new': [s['label'] for s in sig_new if not s.get('repeat')] + [s['label'] + '(늦게 확인)' for s in late], 'signals_late': late, 'vkospi_hold': vk_hold, 'signals_on': [s['label'] for s in sig_on], 'signals_off': [s['label'] for s in sig_off], 'top_buy_since': top_buy, 'top_sell_since': top_sell,
             'data_dates': {'kospi': today, 'kofia': c['date'], 'vkospi': vk_row['date'], 'night': None if NF is None or not len(NF) else NF.iloc[-1]['night_date']},
             'update_summary': {k: v for k, v in summ.items() if k != 'changes'}, 'changes_n': len(summ.get('changes', [])), 'kakao': kakao_msgs, 'kakao_check': check_why, 'kakao_full': msgs, 'diffs_vs_1540': diffs, 'consensus': cons, 'combo': combo}
    json.dump(state, open(os.path.join(a.report, 'latest.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    open(os.path.join(a.report, 'kakao.txt'), 'w', encoding='utf-8').write('\n=====\n'.join(kakao_msgs) + '\n')   # 카톡: 한 통(코스피·자료 상태·신호·수급·신용, 필요하면 대시보드 확인 사유)
    open(os.path.join(a.report, 'kakao_full.txt'), 'w', encoding='utf-8').write('\n=====\n'.join(msgs) + '\n')   # 참고용 전체 요약
    # 사람용 md
    md_lines = [f"# 대시보드 자동 갱신 보고 — {today} {LABEL.get(a.tag[:4], a.tag)} · 실행 {now:%Y-%m-%d %H:%M} KST", '',
                '| 항목 | 값 | 기준일 |', '|---|---|---|', f"| 코스피 | {m['kospi']:,.2f} ({m['kospi_chg_pct']:+.2f}%) | {today} |", f"| VKOSPI | {vk_row['vkospi']:.2f}{' (당일 미수집, 전일 값)' if vk_lag else ''} | {vk_row['date']} |",
                f"| 국면 / 10일 상승 확률 / 5일 급락 확률 | {q['regime']} / {q['p_up']*100:.1f}% / {q['p_risk']*100:.1f}% | {q['date'] if 'date' in q else today} |",
                f"| 신용융자 / 예탁금 / 비율 | {c['credit_jo']:.3f}조 / {c['deposit_jo']:.3f}조 / {f1(cd_ratio,1)}% | {c['date']} |", f"| 미수 반대매매 / 비중 / 미수금 | {l['liq_eok']:.2f}억 / {l['ratio_pct']:.1f}% / {l['misu_eok']:,.0f}억 | {l['date']} |",
                (f"| 투자자별 순매수(조) 외국인/기관/개인/기타 | {fr['foreign_jo']:+.4f} / {fr['inst_jo']:+.4f} / {fr['indiv_jo']:+.4f} / {fr['other_jo']:+.4f} ({fr['basis']}) | {today} |" if fr is not None else '| 투자자별 | 오늘 줄 없음 | — |'), '',
                '## 매매 신호', '']
    if late: md_lines += [f"- ★ 늦게 확인(VKOSPI 반영): **{s['label']}** {s['date']} — {s['rule']}" for s in late]
    if vk_hold: md_lines.append(f"- 판정 보류: {', '.join(VK_SIGS)} — VKOSPI {vk_row['date']}까지만 있음(다음 날 08:31 실행에서 확정)")
    if sig_new: md_lines += [f"- {'새 신호(이미 알림)' if s.get('repeat') else '★ 새 신호'}: **{s['label']}** — {s['rule']}" for s in sig_new]
    if sig_on: md_lines += [f"- 지속: {s['label']}" + (f" ({md(top_buy)}~)" if '매수 최적화 1위' in s['label'] and top_buy else '') + (f" ({md(top_sell)}~)" if '매도 최적화 1위' in s['label'] and top_sell else '') for s in sig_on]
    if sig_off: md_lines += [f"- 끝: {s['label']} ({s['until']}까지)" for s in sig_off]
    if qtrade: md_lines.append(f"- 정밀 검증 전략: {'진입' if qtrade == 'enter' else '청산'}")
    elif qhold: md_lines.append(f"- 정밀 검증 전략: 보유 중({md(qhold['since'])} 종가 진입, 10거래일 보유, {qhold['left']}거래일 뒤 청산 예정)")
    if re_state is not None: md_lines.append(f"- 재진입 규칙 상태: {re_state['state']} (마지막 {re_state['date']} {re_state['action']})")
    if not (sig_new or sig_on or sig_off or qtrade): md_lines.append('- 오늘 켜진 신호 없음')
    md_lines += ['', '## 정밀 검증 현재 값', '', '| 항목 | 값 | 설명 |', '|---|---|---|'] + [f"| {r['item']} | {'' if pd.isna(r['value']) else r['value']} | {r['text']} |" for _, r in QN.iterrows()] if QN is not None else []
    TC = rd(f'{a.out}/trend_champ_rules.csv')
    if TC is not None and len(TC):
        tc = TC.sort_values(['acc_r60', 'acc_r20', 'acc_last_year'], ascending=False)
        md_lines += ['', '## 큰 흐름: 그해 1위 조합 중 지금 잘 맞는 순(최근 60거래일)', '', '| 순서 | 그해 1위 | 조합·설정 | 최근 60일 | 최근 20일 | 올해 | 다음 해(실사용) | 지금 |', '|---|---|---|---|---|---|---|---|']
        md_lines += [f"| {i + 1} | {int(r['year'])} | {r['rule']} | {r['acc_r60']} | {r['acc_r20']} | {r['acc_last_year']} | {'' if pd.isna(r['acc_next']) else r['acc_next']} | {r['now']} |" for i, (_, r) in enumerate(tc.head(5).iterrows())]
        md_lines += [f"- 12줄의 지금 판단: " + (cons_txt(cons) if cons else f"상승 {(TC['now'] == '상승').sum()} · 하락 {(TC['now'] == '하락').sum()}") + ". 올해 1위는 자료가 들어올 때마다 다시 찾는다(실제 큰 흐름 마지막 구간은 10% 되돌림 확인 전까지 잠정)."]
    if combo:
        md_lines += ['', '## 매수×매도 신호 조합 감시', '', f"- 지금 1위: **{combo['top_combo']}** ({md(combo['chosen_since'])} 선정, 지난 250거래일 {combo['win_ret_250']:+.1f}%, 거래 {combo['win_trades']}건 적중 {combo['win_hit']:.0f}%) · 지금 {combo['state']}",
                     f"- 선정 뒤: 수익 {combo['since_ret']:+.1f}% (코스피 {combo['since_kospi']:+.1f}%), 닫힌 거래 {combo['since_trades']}건 중 {combo['since_wins']}건 적중 · 2015~25 적중률 {combo['hit_2015_25']}%",
                     f"- 경고: {combo['warn'] or '없음'} · 다음 재선정 {combo['next_select']} · 규칙: {combo['rule']}"]
    md_lines += ['', '## 자료 갱신', '', f"- 수집 실행: {summ.get('run', '—')} · 코스피 {summ.get('kospi_last', '—')} · 금투협 {summ.get('kofia_last', '—')} · VKOSPI {summ.get('vkospi_last', '—')} · 야간선물 {summ.get('night_last', '—')}",
                f"- 들어온 자료: " + ', '.join(f"{x[0]} {x[1]}" for x in summ.get('files', [])), f"- 값 교체 {len(summ.get('changes', []))}건(엑셀 「값_교체_기록」)"]
    if diffs: md_lines += ['', '## 직전 실행 대비 변경', ''] + [f'- {d}' for d in diffs]
    md_lines += ['', f"- 대시보드: {a.link}", '', '투자 권유 아님']
    open(os.path.join(a.report, 'latest.md'), 'w', encoding='utf-8').write('\n'.join(md_lines) + '\n')
    hist = os.path.join(a.report, 'history'); os.makedirs(hist, exist_ok=True)
    open(os.path.join(hist, f"{today}_{a.tag or 'run'}.md"), 'w', encoding='utf-8').write('\n'.join(md_lines) + '\n')
    print('\n=====\n'.join(kakao_msgs))

if __name__ == '__main__': main()
