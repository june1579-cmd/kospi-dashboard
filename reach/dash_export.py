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
        info += [dict(board=b, item='대상 날짜', value=B['for_date']), dict(board=b, item='계산 시각', value=B['built']), dict(board=b, item='상태', value=' / '.join(B.get('status') or []) or '정상')]
        for kk, v in (B.get('observed') if k == 'post' else B.get('inputs') or {}).items(): info.append(dict(board=b, item=kk, value='' if v is None else round(v, 2)))
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
