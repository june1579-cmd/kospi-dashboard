# -*- coding: utf-8 -*-
"""qv_out/summary.json → ref/qv_formula.json. 확인 구간(2022~2025) 평점이 지금 식보다 높을 때만 새 식을 쓴다."""
import json, os
ROOT = os.path.dirname(os.path.abspath(__file__))
S = json.load(open(os.path.join(ROOT, 'qv_out', 'summary.json')))
out = {'rule': S['rule'], 'built_from': 'qv_out/summary.json'}
for k, v in S['lists'].items():
    new, cur = v['new']['check'], v['current']['check']
    out[k] = dict(label=v['label'], adopt=bool(new and cur and new['total'] > cur['total']), keys=v['new']['keys'], labels=v['new']['labels'],
                  sector_neutral=v['new']['sector_neutral'], check=new, check_old=cur, design=v['new']['design'], design_old=v['current']['design'])
json.dump(out, open(os.path.join(ROOT, 'ref', 'qv_formula.json'), 'w'), ensure_ascii=False, indent=1)
for k in ('st', 'sc', 'd1'): print(k, out[k]['adopt'], out[k]['keys'], out[k]['check_old']['total'], '→', out[k]['check']['total'])
