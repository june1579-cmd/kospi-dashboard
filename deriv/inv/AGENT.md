# 인버스 매수·매도 연구 총괄 (갈래 I) — 지시문

목표: 인버스 ETF 를 언제 사고 언제 팔지에 대한 신호의 **표본 밖 정확도**를 올린다. 기준은 `deriv/inv/CRITERIA.md`.

## 매번 하는 일
1. `deriv-research` 가지를 받아 `deriv/inv/out/report.md`·`state/status.json`·`out/verdicts.csv`·`out/strategies.csv`·`log.md` 를 읽는다. 마지막 `uni-lab` 실행이 실패했으면 인버스 단계(I1~I3) 쪽 원인만 고친다.
2. 지난 실험의 결과를 `deriv/inv/log.md` 표에 한 줄로 적는다(번호 · 날짜 · 바꾼 것 · 통과/관찰 수 · 가장 가까운 후보 · 메모).
3. `log.md` 의 다음 실험 후보에서 위에서부터 **하나만** 골라 넣는다. 새 후보도 `inv_judge.py` 의 같은 판정(표본 밖, 솎기, 가짜 신호 시험)을 거치게 한다.
4. `deriv/inv/trigger.txt` 를 고쳐 push 하면 GitHub 가 다시 계산한다. 계산은 GitHub 에서만 한다.

## 지킬 것
- **기준은 바꾸지 않는다.** `CRITERIA.md`, `inv_judge.py` 의 `CRIT`·`RT`·`STRAT`·`FAMILY`·`QS`·평가 기간·비용, `state/registry.json` 의 등록일은 건드리지 않는다. 바꿀 근거는 `log.md` 에 제안으로만.
- **미래 자료 금지.** 지표는 't일 장 마감 뒤 ~ 다음 개장 전'까지 알 수 있는 값만. 사는 값은 다음 날 시가다. 성적이 갑자기 크게 좋아지면 누설을 먼저 의심한다.
- 인버스 가격은 실제 ETF 시세를 쓴다. 시세 점검(선물과의 상관 0.9 이상)이 떨어지면 계산값으로 바뀌므로 `out/prices_meta.json` 을 매번 확인한다.
- 실험을 많이 할수록 우연히 통과하는 것이 늘어난다. 누적 실험 수를 적고, 새 통과는 등록 뒤 실제 신호 10건이 쌓이기 전에는 확정이라고 쓰지 않는다.
- 고치는 곳은 `deriv/inv/` 뿐이다. `deriv/uni/` 의 함수(fit_predict·thr_series·thin_pos·stat_sig·perf)는 읽기만 하고, 다른 것이 필요하면 `deriv/inv/` 안에 새로 만든다. 연구소 다른 갈래·대시보드(main)·다른 워크플로는 고치지 않는다.
- KRX 로그인·수집은 하지 않는다. 비밀값(KRX·DART·Kakao·TwelveData·Tavily)은 읽지도 쓰지도 않는다. 카카오톡은 직접 보내지 않는다(새 통과·관찰이 생기면 워크플로가 보낸다).
- 커밋: git user dashboard-bot, push 전 pull --rebase. 보고는 쉬운 말로, 끝에 "투자 권유 아님".
