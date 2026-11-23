# Signal A 총괄 지시

예약 작업이 이 파일을 읽고 그대로 따른다. 한국어·존댓말, 쉬운 말, 질문 없이 끝까지. 먼저 PLAN.md·CRITERIA.md·log.md·state/*.json 을 읽는다.

## 절대 규칙
1. 자료는 고정 자료만: 릴리스 `signal-a-data-v1`(panel.pkl·lab_feat.pkl·raw_deriv.tgz·raw_main.tgz). 모든 계산은 이 파일을 내려받아 쓰고, 날짜는 state/freeze.json 의 end 를 넘지 않게 자른다(sa_common.FREEZE_END). 저장소의 새 자료·새 수집은 쓰지 않는다. 릴리스를 다시 만들거나 덮어쓰지 않는다.
2. 기준은 사용자만 바꾼다. CRITERIA.md 와 sa_judge.py 의 기준 숫자를 고치지 않는다.
3. 미래 자료 금지: 지표는 t일 장 마감 뒤~다음 개장 전에 알 수 있는 값만, 매수는 다음 날 시가. 조건·문턱·모형은 해마다 그 해 이전 자료로만 고른다. 성적이 갑자기 좋아지면 먼저 누설을 의심해 지표를 하루 늦춰 다시 돌린다.
4. 시험한 가짓수를 state/ledger.json 에 전부 적는다(묶음·가짓수·날짜). 적지 않은 시험 결과는 보고하지 않는다.
5. 무거운 계산은 전부 GitHub Actions(워크플로 이름 signal-a-*, deriv-research 가지). GitHub 계산이 실패하면 원인을 고쳐 성공할 때까지 다시 돌린다(사용자 지시 2026-11-24). 같은 오류로 3번 실패하면 같은 것을 되풀이하지 말고 방법을 바꾸고 log.md 에 적는다. 저장 단계는 git pull --rebase --autostash 를 쓴다(계산이 추적 파일을 바꾸면 그냥 pull 은 실패한다 — S0 에서 겪음). 이 세션에서는 문법 확인·아주 작은 시험만. 계산은 매트릭스로 나눠 동시에 돌린다(한 번에 최대 20개).
6. 고치는 곳: deriv/signal_a/ 와 .github/workflows/signal-a-*.yml 뿐(워크플로는 deriv-research 가지). 기존 부품(deriv/combo/combo_core.py·combo.c, deriv/turn/*.py, deriv/lab/lab_common.py·a02·a04·a08·a10, deriv/uni/uni_model.py)은 읽고 불러 쓰되 고치지 않는다. main·docs·대시보드·다른 갈래 파일은 건드리지 않는다.
7. KRX 로그인·수집을 하지 않는다. 비밀값(KRX·DART·Kakao·TwelveData·Tavily)은 읽지도 쓰지도 않는다. deriv/trigger.txt 는 건드리지 않는다.
8. 원자료가 없으면 추정하지 않고 "확인 불가". 도구가 거부하면 우회하지 않고 멈춘 뒤 log.md 에 이유를 적는다. 사용량 한도에 닿으면 그 자리에서 멈춘다.
9. 커밋은 git user dashboard-bot(dashboard-bot@users.noreply.github.com), push 전 git pull --rebase origin deriv-research. deriv/scan/out_features.csv 는 add 하지 않는다.
10. 멈춰 있는 예약(state/paused.md)을 다시 켜지 않는다. 예약 작업의 모델·일정을 바꾸지 않는다.

## 매번 하는 순서
1. 저장소 준비: add_repo(owner june1579-cmd, repo kospi-dashboard, access push) → git clone --depth 60 -b deriv-research … → deriv/signal_a/ 읽기.
2. 겹침 막기: state/lock.json 의 at 이 100분 안이면 "다른 회차 진행 중"으로 끝낸다. 아니면 {at: 지금 KST, by: 이 세션} 을 써서 push. 끝낼 때 at 을 비운다.
3. 진행 중인 signal-a-* 실행 확인(gh run list -R june1579-cmd/kospi-dashboard -L 15). 끝난 실행의 결과를 읽어 log.md 표에 한 줄(번호·날짜·단계·바꾼 것·핵심 숫자·판정·시험 가짓수)과 그 단계의 report.md 를 쓴다. 실패했으면 원인을 고쳐 다시 돌린다.
4. state/status.json 의 단계를 보고 PLAN.md 3절에서 다음 할 일을 정한다. 단계별 지시는 아래 '단계별'. S2 의 T1~T5 는 서로 기다리지 않는다: 한 회차에 코드가 준비된 줄기를 모두 띄우고, 코드가 없는 줄기는 Agent 도구(있으면)로 줄기마다 하나씩 나눠 동시에 쓰게 한 뒤 검토해 띄운다. Agent 도구가 없으면 T1 → T2 → T3 → T4 → T5 순으로 직접 쓴다.
5. 계산을 띄웠으면 1분마다 확인하며 최대 40분 기다려 결과를 읽고, 시간이 남으면 4로 돌아간다. 회차 시작 뒤 90분이 지나면 새 일을 시작하지 않는다.
6. state/status.json 갱신({stage, tracks:{t1..t6: 준비|계산 중|끝}, next, updated}) → push.
7. 알림: 단계(S1, T1~T6, S3, S4)가 끝날 때만 카카오톡 1통. 방법·형식은 deriv/lab/orchestrator.md 8단계와 같은 파일 방식, 머리말 [Signal A]. 200자 이내, 결론·핵심 숫자·다음 단계. 그 밖에는 보내지 않는다.
8. 마지막 메시지: 이번에 한 일·결과·다음 할 일을 세 줄 이내, 끝에 "투자 권유 아님".

## 단계별
- **S0**: state/freeze.json 이 없으면 gh run list -w signal-a-freeze 로 확인. 실패했으면 원인을 고쳐 deriv/signal_a/freeze.txt 를 고쳐 push(릴리스가 이미 있으면 다시 만들지 않는다).
- **S1**: sa_common.py(릴리스 내려받기·FREEZE_END 자르기·코스피 지수 시가/종가 매매·독립 거래 솎기·해마다 나누기·윌슨 하한·같은 해 안 날짜 옮기기 가짜·±k% 먼저 닿기·원장 기록), sa_judge.py(CRITERIA.md 1~3절 판정, 표 출력), test_harness.py. 확인: deriv/lab/state_b 의 통과 신호(A4xu_B2xA1)와 state 의 최고 후보를 연구소 결과 파일의 거래일로 넣었을 때 거래 수·적중이 연구소 판정과 같아야 한다(코스피 지수 기준 적중은 따로 적는다). 같으면 state/harness.json {ok:true}.
- **T1**: lab_feat.pkl 의 벽 지표와 a04 의 규칙 꼴을 참고해 위치·사건 규칙 가족을 전부 만든다(가짓수를 먼저 세어 원장에). 해마다(2016~2026) 그 전 자료에서 CRITERIA 통과·관찰 숫자 꼴로 고른 규칙들의 그 해 성적, 상위 N개(1·5·20), 합친 신호. 가짜 신호(같은 해 안)로도 같은 절차를 돌려 비교. 연구소 통과 신호가 이 절차에서 뽑혔는지, 뽑혔을 때 다음 해 성적이 어땠는지 따로 적는다.
- **T2**: deriv/turn/turn_pre.py·turn_signal.py 를 참고. 상태 = 바닥 전 공통점 지표(그때 자료로 다시 고름), 방아쇠 후보를 미리 목록으로 정해 원장에 적고 시작. 채점은 보유 3·5·10일과 보유일 없는 채점 둘 다.
- **T3**: deriv/combo 의 합의 계산과 deriv/uni/uni_model.py 를 참고. 입력에 T1 의 위치·사건 지표를 더한다. 확률은 해마다 다시 학습, 문턱은 그 전 자료로 정함. 확률 구간별 실제 적중 표(맞는 확률인지)를 꼭 낸다.
- **T4**: T1~T3 의 상위 절차를 변동폭 맞춤 문턱으로 다시. 새 가족을 늘리지 않는다.
- **T5**: 시험 묶음 하나만. 결과가 아무 날과 같으면 "하락 신호는 이 자료로는 안 됨"으로 끝낸다.
- **T6**: T1~T5 에서 CRITERIA 3절의 1번을 넘은 후보만.
- **S3**: 후보 5개 이하. 규칙·문턱·보유일·첫 신호 규칙을 signals/final_v1.json 에 고정하고, 전체 성적과 다음 해 성적을 나란히 적는다. 후보가 없으면 없다고 쓴다.
- **S4**: REPORT.md(결론 먼저, 표 위주, 쉬운 말). 사용자 보고용 요약을 log.md 맨 위에. 그 뒤 status.stage = "끝" 으로 두고, 이후 회차는 아무것도 하지 않고 "Signal A 끝남"으로 끝낸다.
