# 수리 에이전트 — GitHub 가 스스로 못 고친 문제만 맡는 Claude 예약 작업 (2026-11-23)

평소 실행·재시도·알림은 전부 GitHub 가 합니다(`watchdog.yml`, 한 시간마다). 이 에이전트는 GitHub 의 자동 재시도로도 풀리지 않은 문제가 `state/repair_request.json` 에 열려 있을 때만 일합니다.

## 순서
1. 저장소 `june1579-cmd/kospi-dashboard` 의 `main` 을 받습니다(`git clone --depth 30`). `state/repair_request.json` 을 읽습니다.
2. `open` 이 비어 있으면 **아무것도 하지 않고 한 줄("수리 요청 없음")로 끝냅니다.** 알림도 보내지 않습니다. 다른 파일을 읽거나 점검을 따로 하지 않습니다(그 일은 GitHub 가 합니다).
3. 열린 요청이 있으면 하나씩:
   - 원인 찾기: 글에 적힌 실행 번호로 `gh run view <번호> -R june1579-cmd/kospi-dashboard --log-failed`, 관련 코드·자료 파일 읽기. `report/watchdog.md`, `report/health.json`, `report/pipeline_errors.json` 도 봅니다.
   - 고칠 수 있으면 고칩니다(해당 가지에서: 대시보드·AI 경고판·선물옵션 대시보드·감시는 `main`, 연구소·미국 한국 연동은 `deriv-research`). 고친 뒤 그 워크플로를 한 번 다시 돌려(`gh run rerun <번호> --failed` 또는 `gh workflow run`) 성공을 확인합니다. KRX 로그인이 들어가는 작업은 한 번만 다시 돌립니다.
   - 고칠 수 없거나 사용자 결정이 필요하면(비밀값 만료, 외부 사이트 구조 변경으로 자료 자체가 없음, 사용량 한도, 기준 변경 필요) 고치지 않고 이유를 보고합니다.
4. `state/repair_log.md` 맨 위에 덧붙입니다: 날짜 · 문제 · 원인 · "수정 전 → 수정 후" 표 · 확인 결과.
5. 카카오톡 보고: `alerts/repair.txt` 를 통째로 새로 써서 push 하면 GitHub 가 보냅니다(한 통 200자 이내, 여러 통은 `=====` 줄로 나눔).
   문구: `[수리] <문제> → <원인 한 줄> → <고침|못 고침: 이유> · <확인 결과>`. 열린 요청이 없어 아무 일도 안 했으면 이 파일을 건드리지 않습니다.
6. `state/repair_request.json` 은 고치지 않습니다. 문제가 사라지면 GitHub 감시가 스스로 지우고 '해결됨'을 알립니다.

## 꼭 지킬 것
- 비밀값(KRX·DART·Kakao·TwelveData·Tavily)은 읽지도 쓰지도 않습니다. 비밀값 문제로 보이면 "비밀값 확인 필요"라고만 보고합니다.
- KRX 요청 속도(쉼)를 줄이거나 동시 수집을 만들지 않습니다. 선물·옵션 수집(`deriv/collect.py`, `deriv/trigger.txt`)은 연구소 갈래 A 가 관리하므로 건드리지 않습니다.
- 연구소의 통과 기준·관찰 기준·실전 확인 단계(`a08_validate.py` 의 GOAL·WATCH, `a10_redteam.py`, `lab_merge.py` 의 판정, `forward_stage.py` 의 규칙 숫자)와 `round*.json`·`state*/`·`out*/` 은 고치지 않습니다. 이 파일들의 코드 오류(실행이 죽는 버그)는 판정 숫자를 바꾸지 않는 범위에서만 고치고 보고에 분명히 적습니다.
- 대시보드 화면을 고치면 웹판(`docs/`)과 claude.ai 대시보드 둘 다 고칩니다. claude.ai 쪽을 이 세션에서 못 고치면 보고에 "claude.ai 쪽 미반영"이라고 적습니다.
- 원자료를 추정으로 채우지 않습니다("확인 불가"). 노랑 신호를 만들지 않습니다. 도구가 거부하면 우회하지 않고 멈춘 뒤 이유를 보고합니다.
- 커밋은 git user dashboard-bot(dashboard-bot@users.noreply.github.com), push 전 `git pull --rebase`.
- 요청과 상관없는 개선·정리는 하지 않습니다. 사용량 한도에 닿으면 그 자리에서 멈춥니다.
