# Signal A 총괄 지시 (2판, 2026-11-24 — 사용자 지시 "GitHub에서 가능한 건 무조건 GitHub에서, 아쉬운 줄기가 생기면 보고")

한국어·존댓말, 쉬운 말, 질문 없이 끝까지. 먼저 PLAN.md·CRITERIA.md·log.md·state/*.json 을 읽는다.

## 일 나누기
- **GitHub 가 하는 일(전부)**: 계산, 단계 잇기(앞 단계가 끝나면 다음 단계 자동 시작), 실패 시 다시 돌리기(3번까지), 판정(CRITERIA.md), 가짜 신호 시험, 결과 표·보고서 초안, 원장 기록, 카카오톡 보고, 상태 파일 갱신.
- **Claude 가 하는 일(이것만)**: ① 코드 쓰기(시험대·줄기별 계산·파이프라인) ② 같은 오류로 3번 실패한 계산 고치기 ③ 마지막 심사·보고서의 결론 글. 그 밖에는 하지 않는다. 계산이 끝나기를 기다리며 지켜보지 않는다(띄우고 끝낸다).

## 절대 규칙
1. 자료는 고정 자료만: 릴리스 `signal-a-data-v1`(panel.pkl·lab_feat.pkl·raw_deriv.tgz·raw_main.tgz). 날짜는 state/freeze.json 의 end(2026-11-20)를 넘지 않게 자른다. 저장소의 새 자료·새 수집은 쓰지 않는다. 릴리스를 다시 만들거나 덮어쓰지 않는다.
2. 기준은 사용자만 바꾼다. CRITERIA.md 와 판정 코드의 기준 숫자를 고치지 않는다.
3. 미래 자료 금지: 지표는 t일 장 마감 뒤~다음 개장 전에 알 수 있는 값만, 매수는 다음 날 시가. 조건·문턱·모형은 해마다 그 해 이전 자료로만 고른다.
4. **미리 정하고 돌린다**: 줄기마다 시험할 것(규칙 가족·방아쇠 목록·모형·문턱 격자)을 tN/SPEC.md 에 가짓수와 함께 먼저 적고, 그대로 돌린다. 결과를 본 뒤 목록을 늘리거나 고쳐 다시 돌리지 않는다. 더 해 보고 싶은 것이 생기면 돌리지 말고 '아쉬운 줄기'로 보고한다(아래).
5. 시험한 가짓수는 파이프라인이 state/ledger.json 에 적는다. 적지 않은 시험 결과는 보고하지 않는다.
6. 고치는 곳: deriv/signal_a/ 와 .github/workflows/signal-a-*.yml 뿐(워크플로는 deriv-research 가지). 기존 부품(deriv/combo/combo_core.py·combo.c, deriv/turn/*.py, deriv/lab/lab_common.py·a02·a04·a08·a10, deriv/uni/uni_model.py)은 불러 쓰되 고치지 않는다. main·docs·대시보드·다른 갈래 파일·deriv/trigger.txt 는 건드리지 않는다.
7. KRX 로그인·수집을 하지 않는다. 비밀값은 읽지도 쓰지도 않는다(워크플로에서 `${{ secrets.이름 }}` 으로 넘기는 것은 기존 워크플로와 같은 이름·방식으로만).
8. 원자료가 없으면 "확인 불가". 도구가 거부하면 우회하지 않고 멈춘 뒤 log.md 에 이유를 적는다. 사용량 한도에 닿으면 그 자리에서 멈춘다.
9. 커밋은 git user dashboard-bot(dashboard-bot@users.noreply.github.com), push 전 git pull --rebase --autostash origin deriv-research. deriv/scan/out_features.csv 는 add 하지 않는다.
10. 멈춰 있는 예약(state/paused.md)을 다시 켜지 않는다. 예약 작업의 모델·일정을 바꾸지 않는다.

## 파이프라인 (첫 회차에 만든다 — signal-a-pipeline.yml)
- 시작: deriv/signal_a/run.txt push 또는 workflow_dispatch. 끝에 할 일이 남았으면 `gh workflow run` 으로 스스로 다시 시작한다(권한 actions: write).
- 순서: 고정 자료 내려받기 → 시험대 확인(test_harness.py) → 준비된 줄기(tN/run.py 와 tN/SPEC.md 가 있고 tN/out/done.json 이 없는 것)를 매트릭스로 동시에 → 줄기별 판정(sa_judge.py) → T1~T5 가 모두 끝났으면 T6 → T6 이 끝났으면 S3(후보 모으기·겹침·반증 시험·표) → 보고서 초안(REPORT_draft.md) → 상태·원장·log.md 한 줄 저장.
- 줄기 하나의 계산이 크면 run.py 가 --part i/n 을 받아 매트릭스로 나눈다(한 번에 최대 20개, 한 조각 60분 이내).
- 다시 돌리기: 조각마다 3번까지. 3번 다 실패하면 state/status.json 의 need_claude = true, fail = {줄기, 조각, 오류 끝 30줄} 로 적고 카카오톡 "[Signal A] <줄기> 계산 3번 실패 — 수리 대기".
- 카카오톡: 보내는 방법은 .github/workflows/uni-lab.yml 의 카카오톡 단계를 그대로 따른다. 줄기·단계가 끝날 때 1통(결론·핵심 숫자·다음 단계, 200자 이내, 머리말 [Signal A]).
- **아쉬운 줄기 보고**: 줄기가 끝날 때 파이프라인이 아래를 자동으로 가려 state/status.json 의 wish 목록과 카카오톡·보고서 초안에 적는다. 자동으로 다시 돌리지 않는다 — 사용자가 정한다.
  - 관찰 등급은 있는데 통과가 없음(얼마나 모자라는지 숫자로)
  - 다음 해 성적은 넘었는데 독립 거래 수가 모자람
  - 2026년을 빼면 넘고 넣으면 못 넘음(또는 반대)
  - 조각 일부가 끝내 실패해 가족 일부를 못 봄
  - SPEC.md 의 '안 넣은 것' 칸에 적어 둔 방향(코드 쓸 때 Claude 가 미리 적는다)
- 상태 파일: state/status.json {stage, tracks:{t1..t6: 코드 없음|준비|계산 중|끝|실패}, need_claude: true/false, why, wish:[…], fail, updated}. Claude 가 할 일이 남았을 때만 need_claude = true(코드 없는 줄기 있음 / 3번 실패 / 최종 심사 차례).

## 매번 하는 순서 (Claude 회차)
0. **먼저 값싸게 확인**(저장소를 받기 전): curl -s https://raw.githubusercontent.com/june1579-cmd/kospi-dashboard/deriv-research/deriv/signal_a/state/status.json (막히면 WebFetch). need_claude 가 false 이고 stage 가 S1 이후면 **"Claude 할 일 없음 — GitHub 진행 중" 한 줄로 끝낸다**(저장소를 받지 않는다). stage 가 "끝" 이어도 한 줄로 끝낸다.
1. 저장소 준비: add_repo(owner june1579-cmd, repo kospi-dashboard, access push) → git clone --depth 60 -b deriv-research … → deriv/signal_a/ 읽기.
2. 겹침 막기: state/lock.json 의 at 이 100분 안이면 끝낸다. 아니면 {at, by} 를 써서 push, 끝낼 때 비운다.
3. 할 일을 이 순서로 고른다: (가) fail 이 있으면 그것부터 고친다 (나) 시험대·파이프라인이 없으면 만든다 (다) 코드 없는 줄기의 SPEC.md·run.py 를 쓴다 — Agent 도구가 있으면 줄기마다 하나씩 나눠 동시에 쓰게 하고 검토한다. T1~T5 를 한 회차에 다 쓰는 것이 목표다 (라) stage 가 S3 끝이면 최종 심사·보고서 결론.
4. 쓴 코드는 이 세션에서 문법 확인과 아주 작은 시험(자료 일부, 1분 이내)만 하고, deriv/signal_a/run.txt 를 고쳐 push 해 파이프라인을 띄운 뒤 **기다리지 않고** 6으로 간다.
5. 회차 시작 뒤 90분이 지나면 새 일을 시작하지 않는다.
6. log.md 에 한 줄(번호·날짜·단계·바꾼 것) → status.json 의 need_claude 를 다시 맞춤 → push.
7. 마지막 메시지: 이번에 한 일·다음에 GitHub 가 할 일을 세 줄 이내, 끝에 "투자 권유 아님".

## 단계별
- **S1 시험대**: sa_common.py(릴리스 내려받기·끝 날짜 자르기·코스피 지수 시가/종가 매매·독립 거래 솎기·해마다 나누기·윌슨 하한·같은 해 안 날짜 옮기기 가짜·±k% 먼저 닿기·원장 기록), sa_judge.py(CRITERIA.md 1~3절 판정, 표와 '아쉬운 줄기' 가리기), test_harness.py. 확인: deriv/lab/state_b 의 통과 신호(A4xu_B2xA1)와 state 의 최고 후보를 연구소 결과의 거래일로 넣었을 때 거래 수·적중이 연구소 판정과 같아야 한다(코스피 지수 기준 적중은 따로 적는다).
- **T1 위치·사건 규칙 전수**: lab_feat.pkl 의 벽 지표와 a04 의 규칙 꼴로 가족 전체(벽 종류×거리×벽 나이×물량 변화×수급 확인×장세×늦춤×첫 신호×보유일). 해마다(2016~2026) 그 전 자료에서 통과·관찰 숫자 꼴로 고른 규칙들의 그 해 성적, 상위 N개(1·5·20), 합친 신호. 같은 절차를 가짜 신호로도. 연구소 통과 신호가 이 절차에서 뽑혔는지와 그때의 다음 해 성적을 따로.
- **T2 상태 → 방아쇠**: deriv/turn/turn_pre.py·turn_signal.py 참고. 상태 = 바닥 전 공통점 지표(그때 자료로 다시 고름), 방아쇠 목록은 SPEC 에 고정. 채점은 보유 3·5·10일과 보유일 없는 채점(±5% 먼저 닿기) 둘 다.
- **T3 합의·확률**: deriv/combo 의 합의 계산과 deriv/uni/uni_model.py 참고, 입력에 T1 의 위치·사건 지표를 더함. 해마다 다시 학습, 문턱은 그 전 자료로. 확률 구간별 실제 적중 표를 꼭 낸다.
- **T4 변동폭 맞춤**: T1~T3 과 같은 가족을 변동폭 맞춤 문턱으로. 새 가족을 늘리지 않는다. 2011·2020·2026년 따로 채점.
- **T5 하락·인버스**: 시험 묶음 하나(반대매매 기준선·옵션 구조·해외). 아무 날과 같으면 "하락 신호는 이 자료로는 안 됨".
- **T6 청산**: T1~T5 에서 CRITERIA 3절 1번을 넘은 후보만. 보유일·손절·익절·신호 꺼짐, 왕복 비용 0.15% 민감도. T6 코드는 T1~T5 와 같이 미리 써 둔다.
- **S3**: 파이프라인이 후보를 모아 겹침·함께 쓰기·반증 시험 표를 만든다. Claude 는 5개 이하로 추려 signals/final_v1.json 에 규칙·문턱·보유일을 고정하고, 전체 성적과 다음 해 성적을 나란히 적는다. 후보가 없으면 없다고 쓴다.
- **S4**: REPORT.md(결론 먼저, 표 위주, 쉬운 말, '아쉬운 줄기'와 다음 프로젝트 인계 포함). status.stage = "끝".
