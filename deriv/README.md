# 선물·옵션 수급 지표 연구 (deriv-research 가지)

- 목적: 선물·옵션 자료로 코스피 대시보드에 넣을 수급 지표 후보를 만들고 백테스트로 검증(대시보드 반영은 범위 밖).
- 실행: `deriv/trigger.txt` 첫 줄(probe | full | analyze)과 둘째 줄(인자)을 바꿔 이 가지에 push → Actions `deriv-research` 실행 → 결과가 `deriv/data`, `deriv/out` 에 커밋됨.
- 수집: `deriv/collect.py` (KRX 정보데이터시스템, 무료, 로그인). 분석·백테스트: `deriv/analyze.py`.
- 조사 문서: `deriv/research/*.md`. 보고서: `deriv/reports/*.md`.
- main·대시보드·웹판·카톡 발송은 건드리지 않는다. 원자료는 추정으로 채우지 않는다(빈칸 = 확인 불가).
