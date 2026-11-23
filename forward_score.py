# -*- coding: utf-8 -*-
"""forward_score.py — 전진 성적표(2026-11-23 추가). 알림으로 실제 나간 신호가 그 뒤에 맞았는지 자동으로 채점한다.

왜 만들었나: 과거 자료로 고른 신호는 고를 때 성적이 좋게 보이는 것이 당연하다(연구소 검증: 고를 때 평균 78% → 그 뒤 62.6%).
  신호를 믿을지는 '고른 뒤에 실제로 나온 신호'의 성적으로만 판단할 수 있어서, 나간 신호를 날짜와 함께 고정해 두고 며칠 뒤 자동 채점한다.

무엇을 채점하나
  1 대시보드 신호: report/sent_signals.json(카카오톡 알림으로 나간 신호의 시작일·이름). 한 번 적힌 신호는 지우지 않는다.
     · 기준가 = 신호일 '다음 거래일' 코스피 종가(알림을 보고 실제로 살 수 있는 가장 늦은 시점 — 유리하게 잡지 않음)
     · 5·10·20거래일 뒤 종가와 비교. 매수 신호는 올랐으면 맞음, 매도 신호는 내렸으면 맞음. 날짜가 아직 안 왔으면 '대기'.
     · 자료 정정으로 취소된 신호(report/retractions.json)는 '취소'로 표시하고 합계에서 뺀다(나간 알림이 틀렸다는 기록으로는 남김).
  2 연구소 신호: deriv-research 가지의 deriv/lab/signals/forward_<갈래>.json(규칙을 고정한 날 뒤의 신호, 실전 확인 단계). 연구소가 계산한 등락을 그대로 옮긴다.
출력: out/fwd.csv(대시보드·웹판 표), report/forward.md(사람용). 원자료가 없으면 추정하지 않고 빈칸으로 둔다.
"""
import argparse, json, os, urllib.request
import pandas as pd

HZ = (5, 10, 20)
RAW = 'https://raw.githubusercontent.com/june1579-cmd/kospi-dashboard/deriv-research/deriv/lab/signals/forward_{}.json'


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--out', default='out'); ap.add_argument('--report', default='report'); a = ap.parse_args()
    mk = pd.read_csv(os.path.join(a.out, 'market_daily.csv'))[['date', 'kospi']].dropna(); mk['date'] = mk['date'].astype(str)
    dates = mk['date'].tolist(); px = mk['kospi'].astype(float).tolist(); pos = {d: i for i, d in enumerate(dates)}
    sp = os.path.join(a.report, 'sent_signals.json'); sent = json.load(open(sp, encoding='utf-8')) if os.path.exists(sp) else []
    rp = os.path.join(a.report, 'retractions.json'); retr = json.load(open(rp, encoding='utf-8')) if os.path.exists(rp) else []
    # 이미 적어 둔 줄은 고치지 않는다(나중 자료로 과거 기록을 바꾸지 않게) — 빈칸이던 칸만 채운다
    fp = os.path.join(a.out, 'fwd.csv')
    old = {r['key']: r for r in pd.read_csv(fp, dtype=str).fillna('').to_dict('records') if r.get('kind') == 'row'} if os.path.exists(fp) else {}
    rows = []
    items = [(d, lab, '') for d, lab in sent] + [(r['date'], r['label'], f"취소({r.get('reason', '자료 정정')})") for r in retr if [r['date'], r['label']] not in sent]
    for d, lab, st in sorted(set(items)):
        side = '매수' if lab.startswith('매수') else '매도' if lab.startswith('매도') else ''
        if not side or d not in pos: continue
        key = f'대시보드|{d}|{lab}'; o = old.get(key, {}); i = pos[d]; e = i + 1
        r = dict(kind='row', key=key, src='대시보드', group=f'대시보드 {side}', date=d, label=lab, side=side, status=st, entry_date=o.get('entry_date', ''), entry=o.get('entry', ''))
        if not r['entry'] and e < len(dates): r['entry_date'] = dates[e]; r['entry'] = f'{px[e]:.2f}'
        for h in HZ:
            r[f'r{h}'] = o.get(f'r{h}', ''); r[f'h{h}'] = o.get(f'h{h}', '')
            if r[f'r{h}'] == '' and r['entry'] and e + h < len(dates):
                v = (px[e + h] / float(r['entry']) - 1) * 100; r[f'r{h}'] = f'{v:.2f}'; r[f'h{h}'] = '맞음' if (v > 0) == (side == '매수') and v != 0 else '틀림'
        rows.append(r)
    lab_note = ''
    for t in ('a', 'b', 'd'):
        try:
            J = json.loads(urllib.request.urlopen(RAW.format(t), timeout=30).read().decode('utf-8'))
        except Exception as ex:
            lab_note += f' 갈래 {t.upper()} 확인 불가({type(ex).__name__})'; continue
        for en in J.get('entries', []):
            for tr in en.get('trades', []):
                key = f"연구소|{t}|{en['id']}|{tr['signal']}"
                rows.append(dict(kind='row', key=key, src='연구소', group=f"연구소 {en.get('tier', '')}", date=tr['signal'], label=f"갈래 {t.upper()} 계열 {en.get('group') or '-'} · {(en.get('desc') or en['id'])[:60]}",
                                 side='매수' if en.get('direction', 1) > 0 else '매도', status=en.get('stage', ''), entry_date=tr.get('entry') or '', entry='',
                                 r5='' if tr.get('ret') is None else f"{tr['ret']:.2f}", h5='대기' if tr.get('ret') is None else ('맞음' if tr.get('hit') else '틀림'), r10='', h10='', r20='', h20=''))
        # 등록만 되고 아직 신호가 없는 규칙 수는 합계 줄의 비고로
        n_reg = len(J.get('entries', [])); n_pass = sum(e_.get('tier') == '통과' for e_ in J.get('entries', []))
        lab_note += f' 갈래 {t.upper()} 등록 {n_reg}개(통과 {n_pass})'
    keys = {r['key'] for r in rows}
    rows += [o for k, o in old.items() if k not in keys]          # 원본에서 사라져도 적어 둔 줄은 남긴다
    for r in rows:
        for h in HZ:
            if r.get(f'h{h}', '') == '' and r['src'] == '대시보드': r[f'h{h}'] = '대기'
    R = pd.DataFrame(rows) if rows else pd.DataFrame(columns=['kind', 'key', 'src', 'group', 'date', 'label', 'side', 'status', 'entry_date', 'entry', 'r5', 'h5', 'r10', 'h10', 'r20', 'h20'])
    sums = []
    for g, G in R.groupby('group') if len(R) else []:
        G = G[~G['status'].astype(str).str.startswith('취소')]
        s = dict(kind='sum', key=f'합계|{g}', src=G['src'].iloc[0] if len(G) else '', group=g, date='', label=f'{g} 합계', side='', status=f'신호 {len(G)}건', entry_date='', entry='')
        for h in HZ:
            d = G[G[f'h{h}'].isin(['맞음', '틀림'])]; k = int((d[f'h{h}'] == '맞음').sum()); n = len(d)
            signed = [float(v) * (1 if sd == '매수' else -1) for v, sd in zip(d[f'r{h}'], d['side'])]
            s[f'h{h}'] = f'{n}건 중 {k}건' if n else '채점 0건'; s[f'r{h}'] = f'{sum(signed) / n:.2f}' if n else ''
        sums.append(s)
    cols = ['kind', 'key', 'src', 'group', 'date', 'label', 'side', 'status', 'entry_date', 'entry', 'r5', 'h5', 'r10', 'h10', 'r20', 'h20']
    OUT = pd.concat([pd.DataFrame(sums, columns=cols), R.sort_values(['date', 'key'], ascending=[False, True])[cols] if len(R) else R], ignore_index=True)
    OUT.to_csv(fp, index=False, encoding='utf-8')
    L = ['# 전진 성적표 — 알림으로 나간 신호의 그 뒤 성적', '', f'- 자료: 코스피 {dates[-1]} 까지 · 기준가 = 신호 다음 거래일 종가 · 매수는 올랐으면, 매도는 내렸으면 맞음',
         f'- 연구소:{lab_note or " 없음"}', '', '| 묶음 | 신호 | 5일 뒤 | 10일 뒤 | 20일 뒤 |', '|---|---|---|---|---|']
    L += [f"| {s['group']} | {s['status']} | {s['h5']} (평균 {s['r5'] or '—'}%) | {s['h10']} (평균 {s['r10'] or '—'}%) | {s['h20']} (평균 {s['r20'] or '—'}%) |" for s in sums]
    L += ['', '| 신호일 | 신호 | 상태 | 기준일·기준가 | 5일 | 10일 | 20일 |', '|---|---|---|---|---|---|---|']
    c_ = lambda r, h: (f"{r[f'r{h}']}% " if r[f'r{h}'] != '' else '') + str(r[f'h{h}'])
    L += [f"| {r['date']} | {r['label']} | {r['status'] or '—'} | {r['entry_date']} {r['entry']} | {c_(r, 5)} | {c_(r, 10)} | {c_(r, 20)} |" for r in OUT[OUT['kind'] == 'row'].fillna('').to_dict('records')]
    L += ['', '평균은 신호 방향 기준(매도 신호는 지수가 내린 만큼을 +로 셈). 표본이 20건이 안 되면 판단 근거로 쓰지 않는다. 투자 권유 아님.']
    open(os.path.join(a.report, 'forward.md'), 'w', encoding='utf-8').write('\n'.join(L) + '\n')
    print(f'전진 성적표: 줄 {len(R)}개 · 합계 {len(sums)}묶음 ·{lab_note}')


if __name__ == '__main__':
    main()
