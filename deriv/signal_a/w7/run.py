# -*- coding: utf-8 -*-
"""Signal A W7 — X1 에서 남은 것(SPEC.md 그대로). 계산은 w7_lib.py 에 있고 이 파일은 명령만 받는다.

  python run.py --nparts            조각 수(4 = 갈래 A·B·C·D)
  python run.py --part i/n          조각 i 계산 → out/parts/ (환경 변수 W7_LAB_CACHE = extract.py 가 쓴 폴더가 꼭 있어야 함)
  python run.py --merge             조각을 합쳐 표(out/*.csv)·요약(out/summary.md·summary.json)·표준 후보(out/cands.pkl·meta.json)를 쓴다
  --quick                           시험용(가짜 50번, 갈래마다 고정 규칙 몇 개만 — extract.py --quick 으로 만든 기록도 받는다)
순서: (판다스 최신판 venv) python extract.py --out "$W7_LAB_CACHE"  →  (고정판 환경) python run.py --part i/4  →  python run.py --merge
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (os.path.dirname(HERE), HERE):
    if _p not in sys.path: sys.path.insert(0, _p)
import sa_common as C  # noqa: E402
import w7_lib as W  # noqa: E402

TRACK = W.TRACK


def n_parts(vol=False):
    return W.n_parts()


def run_part(i, n, vol=False, quick=False):
    return W.run_part(i, n, quick=quick)


def merge(parts, vol=False, quick=False):
    return W.merge(parts, quick=quick)


if __name__ == '__main__':
    a = C.parse_part()
    if a['nparts']:
        print(n_parts())
    elif a['part']:
        i, n_ = a['part']
        if n_ != n_parts(): raise SystemExit(f'W7 의 조각 수는 {n_parts()}개(갈래 A·B·C·D)여야 함 — 받은 값 {i}/{n_}')
        C.save_part(TRACK, i, n_, run_part(i, n_, quick=a['quick'])); print(f'조각 {i}/{n_} 저장')
    elif a['merge']:
        cands, meta = merge(C.load_parts(TRACK, n_parts()), quick=a['quick'])
        C.save_result(TRACK, cands, meta)
        print(f"후보 {len(cands)}개 · 시험 {meta['n_tested']:,}가지 · wf 절차 {meta['m_wf']}개 · 요약 out/summary.md")
