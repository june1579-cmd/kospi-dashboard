# claude.ai '장중 도달 확률' 대시보드용 CSV 만들기(2026-11-26). docs/reach/data 의 eve·pre·post·eval·hits JSON → OUT 폴더의 CSV 5개.
# 사용: python reach/dash_export.py OUT_DIR   (Claude 예약 작업이 만든 CSV 를 대시보드 자료 파일로 올린다)
import csv, json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
R = os.path.join(ROOT, 'docs', 'reach', 'data')
NM = {'S': '현물', 'F': '선물', 'c': '전날 종가', 'o': '시가'}
BL = {'eve': '16:20판', 'pre': '08:30판', 'post': '09:10판'}


def rd(n):
    p = os.path.join(R, n)
    return json.load(open(p, encoding='utf-8')) if os.path.exists(p) else None


def w(path, rows):
    if not rows: return
    with open(path, 'w', newline='', encoding='utf-8') as f:
        x = csv.DictWriter(f, list(rows[0].keys())); x.writeheader(); x.writerows(rows)


def main(out):
    os.makedirs(out, exist_ok=True); lad, qs, info = [], [], []
    for k, b in BL.items():
        B = rd(f'{k}.json')
        if not B: continue
        for inst in 'SF':
            for ref in 'co':
                U = B['ladders'].get(f'{inst}_{ref}_up'); Dn = B['ladders'].get(f'{inst}_{ref}_dn')
                if not U or not Dn: continue
                rp = B['ref_price'].get(f'{inst}_{ref}')
                for i, lv in enumerate(B['levels']):
                    lad.append(dict(key=f'{b}|{NM[inst]}|{NM[ref]}|{lv:.1f}', board=b, inst=NM[inst], ref=NM[ref], level=round(lv, 1), up_p=U['p'][i], dn_p=Dn['p'][i],
                                    up_price=round(rp * (1 + lv / 100), 2) if rp else '', dn_price=round(rp * (1 - lv / 100), 2) if rp else ''))
                for side, L in (('고가', U), ('저가', Dn)):
                    qs.append(dict(key=f'{b}|{NM[inst]}|{NM[ref]}|{side}', board=b, inst=NM[inst], ref=NM[ref], side=side, q10=L['q']['0.1'], q50=L['q']['0.5'], q90=L['q']['0.9'],
                                   seen='' if L.get('seen') is None else L['seen'], ref_price=rp if rp else ''))
        I = lambda item, value, kind='meta', use='y', need='y': info.append(dict(board=b, item=item, value='' if value is None else (round(value, 2) if isinstance(value, float) else value), kind=kind, use=use, need=need))
        src_ = (B.get('observed') if k == 'post' else B.get('inputs')) or {}
        miss_ = [kk for kk, v in src_.items() if v is None and not kk.startswith('외국인')]       # 빠진 입력이 있으면 '정상'이라 쓰지 않는다
        st_ = list(B.get('status') or []) + ([f"빠진 입력: {'·'.join(miss_)} (과거 중앙값으로 대신)"] if miss_ and not any('빠진 입력' in s for s in (B.get('status') or [])) else [])
        I('대상 날짜', B['for_date'], 'head'); I('계산 시각', B['built'], 'head'); I('상태', ' / '.join(st_) or '정상', 'head')
        if k == 'post': I('고가·저가 기준 시각', B.get('asof')); I('선물 종목 코드', B.get('fut_code'))
        else: I('기준 자료 날짜', B.get('base_date'))
        I('모형 학습 시각', B.get('params_fitted'))
        if k == 'post':                                   # 09:10판은 08:30판 입력(야간선물·간밤 미국 등)을 그대로 쓴다 → 그 날짜와 값
            import re
            m_ = re.search(r'08:30판이 오늘 것이 아님\((\d{4}-\d{2}-\d{2})\)', ' '.join(B.get('status') or [])); dep = m_.group(1) if m_ else B['for_date']
            P0 = rd('pre.json'); PI = (P0 or {}).get('inputs') or {} if (P0 or {}).get('for_date') == dep else {}
            I('08:30판 입력 날짜', dep, 'dep')
            for kk in ('야간선물(%)', '간밤 S&P500(%)', '간밤 VIX 변화(%)', '전날 코스피200(%)', '20일 변동성(%)', '20일 평균 하루 폭(%)'): I('08:30판 입력: ' + kk, PI.get(kk), 'dep')
        rp = B.get('ref_price') or {}
        for kk, nm in (('S_c', '기준점: 현물 전날 종가'), ('F_c', '기준점: 선물 전날 종가'), ('S_o', '기준점: 현물 시가'), ('F_o', '기준점: 선물 시가')):
            I(nm, rp.get(kk), 'ref', need='y' if (k == 'post' or kk.endswith('_c')) else 'n')
        for kk, v in ((B.get('observed') if k == 'post' else B.get('inputs')) or {}).items(): I(kk, v, 'input', 'f' if kk.startswith('외국인') else 'y')
        if k == 'pre':
            F = B.get('features') or {}
            I('외국인 전날 선물 평가손익(%)', F.get('pnl1'), 'input', 'f'); I('20일 선물 평균 하루 폭(%)', F.get('fpark20'), 'input', 'n')
    E0 = rd('eval.json')
    if E0:
        m = E0.get('meta') or {}; b = '검증'
        for item, value in (('계산 시각', m.get('built')), ('자료 기간', ' ~ '.join(m.get('data') or []) or None), ('표본 일수', m.get('n')), ('야간선물 있는 날', m.get('night_days'))):
            info.append(dict(board=b, item=item, value='' if value is None else value, kind='head' if item == '계산 시각' else 'meta', use='y', need='y'))
    H0 = rd('hits.json')
    if H0:
        b = '적중표'; rows0 = H0.get('rows') or []
        for item, value in (('계산 시각', H0.get('built')), ('최근 날짜', rows0[0]['date'] if rows0 else None), ('요약 일수', H0.get('n_sum')), ('표에 있는 날', len(rows0))):
            info.append(dict(board=b, item=item, value='' if value is None else value, kind='head' if item == '계산 시각' else 'meta', use='y', need='y'))
    E = rd('eval.json'); evr = []
    for r in (E or {}).get('results', []):
        g = lambda s, k: (r['detail'].get(s) or {}).get(k)
        f = lambda v, n=1: '' if v is None else round(v, n)
        evr.append(dict(key=f"{BL[r['time']]}|{NM[r['inst']]}|{NM[r['ref']]}|{'고가' if r['side'] == 'up' else '저가'}", board=BL[r['time']], inst=NM[r['inst']], ref=NM[r['ref']],
                        side='고가' if r['side'] == 'up' else '저가', passed='통과' if r['passed'] else '통과 못 함', base=r['base_name'], imp_valid=f(g('검증', 'imp')), imp_hold=f(g('보류', 'imp')),
                        p_hold=f(g('보류', 'p'), 3), imp_2026=f(g('2026', 'imp')), imp_krx_night=f(g('KRX 야간 시기', 'imp')), foreign_imp=f((r['foreign_detail'].get('보류') or {}).get('imp')),
                        foreign='통과(사용)' if r['foreign_pass'] else ('시험 안 함' if r['time'] == 'eve' else '통과 못 함(안 씀)')))
    H = rd('hits.json'); hr = []
    for r in (H or {}).get('rows', [])[:20]:
        row = dict(date=r['date'], hi=r['hi'], lo=r['lo'])
        for k, b in BL.items():
            v = r['boards'].get(k) or {}
            row[f'{k}_hi'] = '' if 'hi_in' not in v else ('○' if v['hi_in'] else '×')
            row[f'{k}_lo'] = '' if 'lo_in' not in v else ('○' if v['lo_in'] else '×')
            row[f'{k}_src'] = v.get('src', '')
            row[f'{k}_hi_pred'] = v.get('hi_q50', ''); row[f'{k}_lo_pred'] = v.get('lo_q50', '')
            row[f'{k}_hi_diff'] = v.get('hi_diff', ''); row[f'{k}_lo_diff'] = v.get('lo_diff', '')
        hr.append(row)
    hs = [dict(board=BL[k], n=v['n'], hi_in=v['hi_in'], lo_in=v['lo_in'], brier_up1=v['brier_up1'], brier_dn1=v['brier_dn1'], base_up1=v['brier_up1_base'], base_dn1=v['brier_dn1_base'], live=v['live'], mae_hi=v.get('mae_hi', ''), mae_lo=v.get('mae_lo', ''))
          for k, v in ((H or {}).get('summary') or {}).items()]
    w(os.path.join(out, 'ladder.csv'), lad); w(os.path.join(out, 'quantiles.csv'), qs); w(os.path.join(out, 'eval.csv'), evr); w(os.path.join(out, 'info.csv'), info)
    w(os.path.join(out, 'hits.csv'), hr); w(os.path.join(out, 'hits_sum.csv'), hs)
    print('CSV', {n: os.path.getsize(os.path.join(out, n)) for n in sorted(os.listdir(out)) if n.endswith('.csv')})


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, '_dash'))
