# 통합 예측 연구소 총괄 (갈래 U) — 지시문

목표: 모든 자료를 써서 코스피 방향 예측과 매수·매도 신호의 **표본 밖 정확도**를 올린다. 기준은 `deriv/uni/CRITERIA.md`.

## 매번 하는 일
1. `deriv-research` 가지를 받아 `deriv/uni/out/report.md`·`state/status.json`·`out/ablation.csv`·`out/verdicts.csv`·`log.md` 를 읽는다. 실행이 실패했으면 원인을 고친다.
2. 지난 실험이 무엇을 바꿨고 결과가 어땠는지 `deriv/uni/log.md` 에 한 줄로 적는다(날짜 · 바꾼 것 · 통과/관찰 수 · 가장 가까운 후보의 적중률 · 누적 실험 수).
3. 다음 실험을 **하나만** 정해 넣는다. 예: 새 지표(이미 저장소에 있는 자료로), 지표 묶음 바꾸기, 모형 설정, 대상(보유 기간) 추가, 신호 정의(문턱·이틀 연속 등). 근거를 log 에 적는다.
4. `deriv/uni/trigger.txt` 를 고쳐 push 하면 GitHub 가 다시 계산한다. 계산은 GitHub 에서만 한다(여기서는 문법 확인 정도만).

## 지킬 것
- **기준은 바꾸지 않는다.** `CRITERIA.md`, `uni_judge.py` 의 `CRIT`·`RT`·`STRAT`·`FAMILY`·`QS`·평가 기간, `state/registry.json` 의 등록일은 건드리지 않는다. 바꿀 근거가 있으면 `log.md` 에 제안으로만 적는다.
- **미래 자료 금지.** 모든 지표는 't일 장 마감 뒤 ~ 다음 개장 전'까지 알 수 있는 값이어야 한다. 금투협은 하루 늦춘다. 학습은 결과가 시험 해 시작 전에 끝난 날만. 새 지표를 넣을 때마다 시점을 log 에 적는다.
- 성적이 갑자기 크게 좋아지면 먼저 누설을 의심한다(지표를 하루 더 늦춰 다시 돌려 본다).
- 실험을 많이 할수록 우연히 통과하는 것이 늘어난다. 누적 실험 수를 log 에 적고, 새 통과는 '등록 뒤 실제 신호 10건'이 쌓이기 전에는 확정이라고 쓰지 않는다.
- KRX 로그인·수집은 하지 않는다(갈래 A 가 관리). 비밀값(KRX·DART·Kakao·TwelveData·Tavily)은 읽지도 쓰지도 않는다.
- 연구소 다른 갈래(deriv/lab), 대시보드(main) 파일은 고치지 않는다. 쓰는 곳은 `deriv/uni/` 뿐이다.
- `uni_model.fit_predict`, `uni_judge` 의 `thr_series`·`thin_pos`·`stat_sig`·`perf`, `uni_common` 의 평가 기간·묶음 이름은 인버스 연구(`deriv/inv`)가 같이 쓴다. 인자와 뜻을 바꾸지 말고, 다른 것이 필요하면 새 함수로 더한다. `deriv/inv/` 는 고치지 않는다(갈래 I 총괄이 맡음).
- 카카오톡은 직접 보내지 않는다. 새 통과·관찰이 생기면 워크플로가 보낸다.
- 커밋: git user dashboard-bot, push 전 pull --rebase. 보고는 쉬운 말로, 끝에 "투자 권유 아님".
