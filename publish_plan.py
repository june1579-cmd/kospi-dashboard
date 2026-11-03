# 더 이상 사용하지 않음 — 게시 규칙은 Claude 예약 작업 프롬프트에 있음
# -*- coding: utf-8 -*-
"""publish_plan.py — Claude 예약 작업이 대시보드(클로드 아티팩트)에 자료를 올릴 때 쓰는 보조 도구.
   plan : 저장소 out/manifest.json 과 아티팩트 state/pipeline 문서를 비교해 새로 올릴 파일 목록을 만든다.
          python publish_plan.py plan --state state.json --manifest out/manifest.json --out plan.json
   apply: 올린 자산 id 를 받아 datasets 문서 갱신 배치(inline JSON)와 새 state 문서를 만든다.
          python publish_plan.py apply --state state.json --plan plan.json --ids "liq_daily=<id>,credit=<id>" --manifest out/manifest.json --report report/latest.json --out-batch batch.json --out-state state_new.json
"""
import argparse, json, datetime as dt, sys

KST = dt.timezone(dt.timedelta(hours=9))

def load_state(p):
    s = json.load(open(p, encoding='utf-8'))
    return s.get('data', s) if 'datasets' not in s and 'data' in s else s

def plan(a):
    st = load_state(a.state); man = json.load(open(a.manifest, encoding='utf-8'))
    changed, same, unknown = [], [], []
    for name, rec in st['datasets'].items():
        f = man['files'].get(name)
        if not f: unknown.append(name); continue
        (changed if f['sha256'] != rec['sha256'] else same).append(name)
    out = {'run': man.get('run'), 'tag': man.get('tag'), 'kospi_last': man.get('kospi_last'), 'kofia_last': man.get('kofia_last'), 'errors': man.get('errors', []),
           'upload': [{'name': n, 'path': f'out/{n}.csv', 'doc': st['datasets'][n]['doc'], 'doc_version': st['datasets'][n]['doc_version'], 'sha256': man['files'][n]['sha256'], 'last_date': man['files'][n].get('last_date')} for n in changed],
           'unchanged': same, 'missing_in_repo': unknown}
    json.dump(out, open(a.out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f"올릴 파일 {len(changed)}개: {changed}\n그대로 {len(same)}개, 저장소에 없음 {unknown}")

def apply(a):
    st = load_state(a.state); pl = json.load(open(a.plan, encoding='utf-8')); man = json.load(open(a.manifest, encoding='utf-8'))
    ids = dict(kv.split('=', 1) for kv in a.ids.split(',') if '=' in kv)
    now = dt.datetime.now(KST).strftime('%Y-%m-%dT%H:%M:%S+09:00'); tag = pl.get('tag') or ''
    by = f"자동 갱신(GitHub Actions {pl.get('run', '')} {tag} 수집 → Claude 예약 작업 게시)"
    writes = []
    for u in pl['upload']:
        aid = ids.get(u['name'])
        if not aid: print('자산 id 없음:', u['name']); continue
        fname = {'market': 'market_daily.csv', 'liq': 'liq_daily.csv'}.get(u['doc'], u['doc'] + '.csv')
        writes.append({'op': 'update', 'collection': 'datasets', 'doc_id': u['doc'], 'if_version': u['doc_version'],
                       'data': {'source': {'kind': 'file', 'name': fname, 'url': '/_blob/' + aid}, 'updated': {'at': now, 'by': by}}})
        st['datasets'][u['name']].update({'asset': aid, 'sha256': u['sha256'], 'doc_version': u['doc_version'] + 1})
    json.dump(writes, open(a.out_batch, 'w', encoding='utf-8'), ensure_ascii=False)
    rep = json.load(open(a.report, encoding='utf-8')) if a.report else {}
    st['last_publish'] = {'at': now, 'by': 'Claude 예약 작업', 'kospi_last': pl.get('kospi_last'), 'kofia_last': pl.get('kofia_last'), 'run_tag': tag, 'uploaded': [u['name'] for u in pl['upload'] if u['name'] in ids], 'signals_new': rep.get('signals_new', []), 'kakao': rep.get('kakao', [])}
    json.dump(st, open(a.out_state, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f"문서 갱신 배치 {len(writes)}건 → {a.out_batch} (inline data 로 ArtifactData batch 에 그대로 붙여 넣기)\n새 state → {a.out_state} (set state/pipeline, if_version = 지금 버전)")

if __name__ == '__main__':
    ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest='cmd')
    p = sub.add_parser('plan'); p.add_argument('--state', required=True); p.add_argument('--manifest', required=True); p.add_argument('--out', default='plan.json')
    q = sub.add_parser('apply'); q.add_argument('--state', required=True); q.add_argument('--plan', required=True); q.add_argument('--ids', required=True); q.add_argument('--manifest', required=True); q.add_argument('--report', default=''); q.add_argument('--out-batch', default='batch.json'); q.add_argument('--out-state', default='state_new.json')
    a = ap.parse_args()
    {'plan': plan, 'apply': apply}[a.cmd](a) if a.cmd else ap.print_help()
