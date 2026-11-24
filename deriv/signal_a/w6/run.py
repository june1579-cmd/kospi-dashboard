# -*- coding: utf-8 -*-
"""Signal A W6 — T2~T6 SPEC 의 '안 넣은 것' 전부. 이 파일은 두 묶음을 잇는 껍데기다(계산은 part_a.py·part_b.py, 목록은 SPEC_a.md·SPEC_b.md).

  앞쪽(part_a) = T2·T5 의 '안 넣은 것', 뒤쪽(part_b) = T3·T4·T6 의 '안 넣은 것'.
  조각 번호: 1..na 는 앞쪽의 1..na, na+1..na+nb 는 뒤쪽의 1..nb.
  python run.py --nparts | --part i/n | --merge [--quick]
조용히 넘기지 않는다: 조각이 하나라도 없으면 merge 가 멈춘다(파이프라인이 줄기 실패로 적음).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SA = os.path.dirname(HERE)
for _p in (SA, HERE):
    if _p not in sys.path: sys.path.insert(0, _p)
# joblib 일꾼 프로세스도 part_a·part_b·sa_common 을 찾게
os.environ['PYTHONPATH'] = os.pathsep.join([HERE, SA] + [p for p in os.environ.get('PYTHONPATH', '').split(os.pathsep) if p and p not in (HERE, SA)])
import sa_common as C  # noqa: E402
import part_a as A  # noqa: E402
import part_b as B  # noqa: E402

TRACK = 'w6'


def n_parts(vol=False):
    return A.n_parts() + B.n_parts()


def run_part(i, n, vol=False, quick=False):
    na, nb = A.n_parts(), B.n_parts()
    if n != na + nb: raise ValueError(f'W6 의 조각 수는 {na + nb}개여야 함 — 받은 값 {i}/{n}')
    if 1 <= i <= na: return {'who': 'a', 'k': i, 'obj': A.run_part(i, na, quick=quick)}
    if na < i <= na + nb: return {'who': 'b', 'k': i - na, 'obj': B.run_part(i - na, nb, quick=quick)}
    raise ValueError(f'조각 번호 {i} 는 없음(1~{na + nb})')


def merge(parts, vol=False, quick=False, out_dir=None):
    na, nb = A.n_parts(), B.n_parts(); parts = list(parts or [])
    if len(parts) != na + nb or any(p is None for p in parts):
        miss = [i + 1 for i in range(na + nb) if i >= len(parts) or parts[i] is None]
        raise RuntimeError(f'W6: 조각 {miss} 이 없음 — 합치지 않고 멈춤')
    pa = [p['obj'] for p in parts[:na]]; pb = [p['obj'] for p in parts[na:]]
    ca, ma = A.merge(pa, quick=quick, out_dir=out_dir)
    cb, mb = B.merge(pb, quick=quick, out_dir=out_dir)
    cands = list(ca) + list(cb); ids = [c['id'] for c in cands]
    if len(set(ids)) != len(ids): raise RuntimeError('W6: 앞쪽·뒤쪽 후보 id 가 겹침')
    fam = {}
    for pre, m in (('앞(T2·T5)', ma), ('뒤(T3·T4·T6)', mb)):
        for k, v in (m.get('families') or {}).items(): fam[f'{pre}:{k}'] = int(v)
    n_tested = int(ma.get('n_tested', 0)) + int(mb.get('n_tested', 0))
    if not quick and (not cands or n_tested <= 0): raise RuntimeError('W6: 후보 0개 또는 시험 가짓수 0 — 비정상')
    meta = {'n_tested': n_tested, 'families': fam,
            'm_fixed': int(ma.get('m_fixed') or 0) + int(mb.get('m_fixed') or 0), 'm_wf': int(ma.get('m_wf') or 0) + int(mb.get('m_wf') or 0),
            'm_by': {'앞(T2·T5)': {'m_wf': ma.get('m_wf'), 'm_fixed': ma.get('m_fixed'), 'by': ma.get('m_by')}, '뒤(T3·T4·T6)': {'m_wf': mb.get('m_wf'), 'm_fixed': mb.get('m_fixed')}},
            'not_included': list(ma.get('not_included') or []) + list(mb.get('not_included') or []),
            'unsolvable': list(ma.get('unsolvable') or []) + list(mb.get('unsolvable') or []),
            'moved': list(ma.get('moved') or []),
            'parts_failed': [], 'tables': list(ma.get('tables') or []) + list(mb.get('tables') or []),
            'notes': ['W6 은 앞쪽(T2·T5 의 안 넣은 것, SPEC_a.md)과 뒤쪽(T3·T4·T6 의 안 넣은 것, SPEC_b.md)을 이은 것. 가짜 시험의 가짓수 보정은 두 묶음의 절차 수를 더한 값을 곱한다(엄하게).']
                     + [f'[앞] {x}' for x in (ma.get('notes') or [])] + [f'[뒤] {x}' for x in (mb.get('notes') or [])],
            'summary_md': '## W6 앞쪽 — T2·T5 의 안 넣은 것\n\n' + (ma.get('summary_md') or '') + '\n\n## W6 뒤쪽 — T3·T4·T6 의 안 넣은 것\n\n' + (mb.get('summary_md') or '') + '\n',
            'quick': bool(quick)}
    return cands, meta


if __name__ == '__main__':
    a = C.parse_part()
    if a['nparts']:
        print(n_parts())
    elif a['part']:
        i, n_ = a['part']; C.save_part(TRACK, i, n_, run_part(i, n_, quick=a['quick'])); print(f'w6 조각 {i}/{n_} 저장')
    elif a['merge']:
        od = os.path.join(C.track_dir(TRACK), 'out')
        cands, meta = merge(C.load_parts(TRACK, n_parts()), quick=a['quick'], out_dir=od)
        open(os.path.join(od, 'summary.md'), 'w', encoding='utf-8').write(meta['summary_md'])
        C.save_result(TRACK, cands, meta)
        print(f"w6 합침: 후보 {len(cands)}개 · 시험 {meta['n_tested']:,}가지 · wf 절차 {meta['m_wf']}개 · fixed 모집단 {meta['m_fixed']:,}")
    else:
        print(__doc__)
