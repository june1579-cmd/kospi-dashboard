# -*- coding: utf-8 -*-
"""audit_notify.py — 검증 결과(신호·종목 명단)를 카카오톡 글로 줄인다(2026-11-23). 지난번과 내용이 같으면 보내지 않는다."""
import hashlib, json, os

def load(p):
    try: return json.load(open(p, encoding='utf-8'))
    except Exception: return None

S = load('report/signal_audit.json'); Lj = load('report/list_audit.json'); msgs = []
if S:
    weak = [r['label'] for r in S.get('eras', []) if r['era'].startswith('고른 뒤') and (r.get('n20') or 0) >= 8 and r.get('hit20') is not None and r.get('base20') is not None and r['hit20'] < r['base20']]
    tr = S.get('truncate', []); bad = [c['cut'] for c in tr if c.get('ok') is False]; unk = [c['cut'] for c in tr if c.get('ok') is None]
    h = S.get('history', {})
    msgs.append(f"[검증] 대시보드 신호 {S.get('signals')}건 · 자른 자료 시험 " + ('불일치 ' + ','.join(bad) if bad else ('확인 불가' if unk and len(unk) == len(tr) else '통과')) +
                f" · 사라진 신호 {len(h.get('vanished', []))}건 · 고른 뒤 20일 성적이 바탕보다 낮음: " + (', '.join(weak) if weak else '없음') + ' · 투자 권유 아님')
if Lj:
    def cell(nm, key):
        c = (Lj.get('agg', {}).get(nm) or {}).get(key)
        return None if not c else f"{c['median_of_medians']:+.1f}%p(우연 확률 {c['p_median'] * 100:.0f}%, {c['better_than_market']}/{c['n_ep']}구간)"
    a, b, c = cell('전체', 'crash_top10'), cell('2024년까지 고점', 'crash_top10'), cell('전체', 'f126_top30')
    msgs.append('[검증] 종목 명단 vs 무작위 — 급락 구간 상위 10 초과수익: 전체 ' + (a or '확인 불가') + ' · 2024년까지 ' + (b or '확인 불가') + ' · 6개월 뒤 상위 30: ' + (c or '확인 불가') + ' · 투자 권유 아님')
msgs = [m if len(m) <= 198 else m[:197] + '…' for m in msgs]
sig = hashlib.sha256('\n'.join(msgs).encode()).hexdigest(); sp = 'state/audit_state.json'; old = (load(sp) or {}).get('sig')
send = bool(msgs) and sig != old
if send:
    os.makedirs('alerts', exist_ok=True); os.makedirs('state', exist_ok=True)
    open('alerts/audit.txt', 'w', encoding='utf-8').write('\n=====\n'.join(msgs) + '\n'); json.dump({'sig': sig}, open(sp, 'w'))
print('검증 알림:', '보냄' if send else '지난번과 같아 보내지 않음', len(msgs), '통')
o = os.environ.get('GITHUB_OUTPUT')
if o: open(o, 'a').write(f"send={'1' if send else '0'}\n")
