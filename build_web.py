# -*- coding: utf-8 -*-
"""build_web.py — 웹판(GitHub Pages, docs/) 자료 만들기.
   1) 대시보드가 쓰는 자료 파일 44개를 docs/data/ 로 복사(out/*.csv 가 있으면 그것, 없으면 pkg/datasets/ 의 고정 파일) + docs/meta.json(기준일·실행 구분)
   2) docs/index.html(껍데기)·docs/page.html(대시보드 페이지 원본)은 손대지 않는다 — 대시보드가 바뀌면 page.html 한 파일만 바꾸면 웹판도 바뀐다

   GitHub Actions 가 매 실행 끝에 돌리고 push 하면 GitHub Pages 가 몇 분 안에 새 자료를 보여준다(Claude 불필요).
   사용: python build_web.py --out out --report report --docs docs
"""
import argparse, datetime as dt, json, os, shutil
import pandas as pd

KST = dt.timezone(dt.timedelta(hours=9))
# 대시보드 자료 문서 id → 파일 이름(docs/index.html 의 FILES 와 같아야 한다). 새 자료를 대시보드에 추가하면 여기와 index.html 두 곳에 더한다.
DATASETS = {"lead_cmp": "lead_cmp.csv", "fut_daily": "fut_daily.csv", "credit": "credit.csv", "alarms": "alarms.csv", "ind_risk": "ind_risk.csv", "ind_scores": "ind_scores.csv", "events": "events.csv", "trend_years": "trend_years.csv", "q_years": "q_years.csv", "buy3": "buy3.csv", "flows": "flows.csv", "gap_table": "gap_table.csv", "episodes": "episodes.csv", "monthly": "monthly.csv", "credit_change": "credit_change.csv", "q_strat": "q_strat.csv", "q_models": "q_models.csv", "ret26": "ret26.csv", "leverage": "leverage.csv", "etf_lev": "etf_lev.csv", "trend_champ_rules": "trend_champ_rules.csv", "ind_now": "ind_now.csv", "ind_warn": "ind_warn.csv", "combo_wf": "combo_wf.csv", "reentry": "reentry.csv", "q_ic": "q_ic.csv", "q_daily": "q_daily.csv", "combo": "combo.csv", "q_sens": "q_sens.csv", "night_fut": "night_fut.csv", "concentration": "concentration.csv", "combo_select": "combo_select.csv", "ind_trade": "ind_trade.csv", "lag": "lag.csv", "q_attr": "q_attr.csv", "combo_table": "combo_table.csv", "liq": "liq_daily.csv", "market": "market_daily.csv", "fx_daily": "fx_daily.csv", "combo_now": "combo_now.csv", "flows_daily": "flows_daily.csv", "trend_champ": "trend_champ.csv", "q_now": "q_now.csv", "sell3": "sell3.csv", "am_daily": "am_daily.csv", "am_bucket": "am_bucket.csv", "am_stocks": "am_stocks.csv", "am_now": "am_now.csv", "am_stats": "am_stats.csv", "relief": "relief.csv"}
def rd(p): return pd.read_csv(p) if os.path.exists(p) else None
def recs(df, cols=None, n=None):
    if df is None: return []
    if cols: df = df[[c for c in cols if c in df.columns]]
    if n: df = df.tail(n)
    return json.loads(df.to_json(orient='records', force_ascii=False))

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--out', default='out'); ap.add_argument('--report', default='report'); ap.add_argument('--docs', default='docs'); ap.add_argument('--days', type=int, default=250)
    a = ap.parse_args(); os.makedirs(a.docs, exist_ok=True); o = a.out; N = a.days
    LJ = json.load(open(os.path.join(a.report, 'latest.json'), encoding='utf-8')) if os.path.exists(os.path.join(a.report, 'latest.json')) else {}
    AL = json.load(open(os.path.join(a.report, 'alerts.json'), encoding='utf-8')) if os.path.exists(os.path.join(a.report, 'alerts.json')) else {}
    M = rd(f'{o}/market_daily.csv'); M = M[M['kospi'].notna()] if M is not None else None
    Q = rd(f'{o}/q_daily.csv'); L = rd(f'{o}/liq_daily.csv'); C = rd(f'{o}/credit.csv'); F = rd(f'{o}/flows_daily.csv'); TC = rd(f'{o}/trend_champ.csv')
    cons = []
    if TC is not None:
        ys = [k for k in TC.columns if k.startswith('y') and k[1:].isdigit()]
        up = (TC[ys] == 1).sum(axis=1); dn = (TC[ys] == -1).sum(axis=1)
        cons = [{'date': d, 'up': int(u), 'dn': int(v)} for d, u, v in zip(TC['date'].tail(N), up.tail(N), dn.tail(N))]
        last = TC.iloc[-1]; years = [{'year': k[1:], 'dir': int(last[k]) if pd.notna(last[k]) else None} for k in ys]
    else: years = []
    # 매매 신호 14개 상태
    AL_ = rd(f'{o}/alarms.csv'); B3 = rd(f'{o}/buy3.csv'); S3 = rd(f'{o}/sell3.csv'); RE = rd(f'{o}/reentry.csv')
    today = str(M.iloc[-1]['date']) if M is not None else ''
    sig = []
    def fam(df, side, key, label, rule_col='rule'):
        for k in key:
            d = df[(df['side'] == side) & (df['type'] == k)] if df is not None else pd.DataFrame()
            on = bool(len(d) and str(d.iloc[-1]['date']) == today); st = d[d['start'] == '시작'] if len(d) else d
            sig.append({'name': f'{side} {k}', 'side': side, 'on': on, 'last_start': (str(st.iloc[-1]['date']) if len(st) else None), 'rule': (str(d.iloc[-1][rule_col]) if len(d) and rule_col in d.columns else ''),
                        'vk': any(x in str(d.iloc[-1][rule_col]) for x in ('VKOSPI',)) if len(d) and rule_col in d.columns else False})
    fam(AL_, '매수', ['민감형', '중간형', '엄격형'], None); fam(B3, '매수', ['최적화 1위', '최적화 2위', '최적화 3위'], None)
    fam(S3, '매도', ['최적화 1위', '최적화 2위', '최적화 3위'], None); fam(AL_, '매도', ['민감형', '중간형', '엄격형'], None)
    re_ = RE.iloc[-1] if RE is not None and len(RE) else None
    qd = Q[Q['trade'].notna()] if Q is not None else pd.DataFrame()
    data = {
        'built_at': dt.datetime.now(KST).strftime('%Y-%m-%d %H:%M'), 'latest': {k: LJ.get(k) for k in ('date', 'tag', 'run_at', 'prelim', 'values', 'data_dates', 'signals_new', 'signals_on', 'signals_off', 'signals_late', 'vkospi_hold', 'consensus', 'combo', 'kakao', 'update_summary')},
        'alerts': AL.get('alerts', []), 'alerts_date': AL.get('date'), 'label': {'0831': '아침 확정', '1540': '잠정 15:37(투자자별 정규장만)', '1840': '확정 20:37(KRX 애프터마켓 포함)'}.get(str(LJ.get('tag', ''))[:4], LJ.get('tag', '')),
        'market': recs(M, ['date', 'kospi', 'kospi_chg_pct', 'vkospi', 'kosdaq'], N), 'q': recs(Q, ['date', 'regime', 'p_up', 'p_risk', 'trade'], N),
        'liq': recs(L, ['date', 'liq_eok', 'ratio_pct', 'misu_eok'], N), 'credit': recs(C, ['date', 'credit_jo', 'deposit_jo', 'chg_pct'], N), 'flows': recs(F, ['date', 'foreign_jo', 'inst_jo', 'indiv_jo', 'other_jo', 'basis'], N),
        'consensus': cons, 'champ_years': years, 'champ_rules': recs(rd(f'{o}/trend_champ_rules.csv'), ['year', 'rule', 'acc_year', 'acc_next', 'acc_all', 'acc_last_year', 'acc_r60', 'acc_r20', 'now']),
        'signals': sig, 'reentry': (None if re_ is None else {'state': re_['state'], 'date': str(re_['date']), 'action': re_['action']}),
        'q_trade': (None if not len(qd) else {'date': str(qd.iloc[-1]['date']), 'trade': qd.iloc[-1]['trade']}),
        'q_now': recs(rd(f'{o}/q_now.csv')), 'combo_now': recs(rd(f'{o}/combo_now.csv')), 'combo_wf': recs(rd(f'{o}/combo_wf.csv')), 'combo_table': recs(rd(f'{o}/combo_table.csv')),
        'night': recs(rd(f'{o}/night_fut.csv'), None, 1), 'images': {}}
    # ---- 대시보드 페이지용 자료 44개 + meta.json + index.html
    ROOT = os.path.dirname(os.path.abspath(__file__)); FILES = dict(DATASETS)
    os.makedirs(os.path.join(a.docs, 'data'), exist_ok=True); n_out = n_fix = 0; missing = []
    for did, fn in FILES.items():
        src = os.path.join(o, fn); fx = os.path.join(ROOT, 'pkg', 'datasets', fn)
        if os.path.exists(src): shutil.copy(src, os.path.join(a.docs, 'data', fn)); n_out += 1
        elif os.path.exists(fx): shutil.copy(fx, os.path.join(a.docs, 'data', fn)); n_fix += 1
        else: missing.append(fn)
    json.dump({'built_at': data['built_at'], 'label': data['label'], 'run_at': LJ.get('run_at'), 'tag': LJ.get('tag'), 'kospi': (LJ.get('data_dates') or {}).get('kospi'), 'kofia': (LJ.get('data_dates') or {}).get('kofia'), 'vkospi': (LJ.get('data_dates') or {}).get('vkospi'), 'missing': missing},
              open(os.path.join(a.docs, 'meta.json'), 'w', encoding='utf-8'), ensure_ascii=False)
    print(f'웹판 자료 docs/data/ 계산 {n_out}개 + 고정 {n_fix}개' + (f' · 없음 {missing}' if missing else ''))

if __name__ == '__main__': main()
