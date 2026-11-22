# 진화 에이전트 기록

- 2026-11-22: 시작. 시험 워크플로(evolve-gate)·새 에이전트 등록부(agents.json)·지시(evolver.md) 만듦.
- 2026-11-23 [대체 실행] 03:37 실행이 Fable 사용량 한도로 멈춰 Opus 5.5 가 진행(기본 실행 03:38 KST 시작 → 03:47 사용량 한도로 실패).
  - 지난 시험 결과: 20261122-check-lock 탈락(잠금 파일 a08 건드림 — 의도된 시험) · 20261122-check-ok 탈락(a06 어긋남 0.0%→3.6% — 오탐, 원인은 아래) · 20261122-extra-time 통과·합침. 합쳐진 새 에이전트 없음(agents.json 비어 있었음).
  - 건강 점검(지난 24시간): 실패 2건 — usk 45014135049(us_features KeyError '^VIX9D', 6분 뒤 다시 돌린 usk 성공 → 일시적), fo-dashboard 45012049668(main 가지·대시보드 담당, 3분 뒤 성공 — 손대지 않음). 연구소 deriv-lab·b·d·notify 모두 성공. extra_log 비어 있음. 미국 수집 VX=F(Yahoo) 0행 — 다른 출처(cboe_index)로 VIX 계열은 있음.
  - 고친 것: evolve/20261123-stable-sort 통과·합침 — a06·scan_run.mine·a09 정렬 동률 순서 고정(kind='stable'), A6_rule id 를 hash()→crc32. 원인: NumPy 기본 argsort 가 CPU 기능(X86_V4/V3/기본)마다 다른 구현이라 동률 순서가 달라짐(세션에서 NPY_DISABLE_CPU_FEATURES 로 재현).
  - 새 에이전트: evolve/20261123-ivterm 통과·합침 — A12 IV 기간구조(a12_ivterm.py, 갈래 a·b·d, 후보 252개, 앞을 보는 실수 0개). 시험 라운드 시간 기준 628초 → 877초(+249초, 실행기 차이 포함 가능 — 다음 라운드 extra_log 의 sec 로 확인).
  - 남은 것: 원격에 evolve/20261122-gate-check-lock·gate-check-ok 가지 2개가 남아 있음(시험 결과 파일이 없는 초기 가지 — 세션은 원격 가지를 지울 수 없음, 사용자 확인 필요).
