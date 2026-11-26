# 선물·옵션 수집 관리 — Opus 5.5 인계 자료

> deriv-research 가지 `deriv/lab/orchestrator.md` 의 '수집(A1, 갈래 A 만)' 문단과 '순서' 4단계를 읽기 전에 읽고 참고한다. **실행 문서와 다르면 실행 문서를 따른다.**
> 근거: `deriv/trigger.txt` 이력(11-18~11-21), `deriv/data/opt_chain*_daily.csv.gz` 마지막 날짜(11-26 12:5x 확인), deriv-research 워크플로 실행 목록, 가지의 커밋 흐름(11-23~11-26), main 의 `.github/workflows/fo-dashboard.yml`.

## 1. 한눈 요약
1. deriv-research 가지를 받는다.
2. (a) `deriv-research` 워크플로가 진행 중·대기 중이면 아무것도 push 하지 않고 끝.
3. (b) `opt_chainx`·`opt_chainwt`·`opt_chainwm` 세 파일의 마지막 날짜와 빠진 달을 본다(gzip 으로 읽기만).
4. 끝나지 않은 것이 있으면 chainx → chainwt → chainwm 순서로 `deriv/trigger.txt` 둘째 줄에 이어 써서 한 번 push(첫 줄 `full`). 모두 와 있으면 아무것도 하지 않는다.
5. (c) 지난 실행이 실패했거나 로그에서 0행이면 원인을 보고, 고칠 수 있으면 고쳐 다음 회차에 다시 건다.
6. 마지막 메시지 한두 줄(무엇을 걸었는지, 또는 "수집 최신 — 할 일 없음").
- 라운드·보고 문서·카카오톡·4단계 (d)·`deriv/signal_a/` 는 이 작업의 일이 아니다.

## 2. 판단 기준 (실행 문서에 없거나 모호한데 실제로 그랬던 것)
- D1 **이 작업이 생긴 뒤(11-24~) trigger.txt 를 push 한 적이 없다.** 마지막 변경은 11-21 18:07(c567407, 연구소 갈래 A)이고, deriv-research 워크플로의 마지막 실행도 그 push(18번, 11-21)다. 11-25 22:54 회차는 1분 13초 만에 끝났다(커밋 없음). 즉 지금까지의 정상 결과는 늘 "할 일 없음"이다.
- D2 매일 새 날짜는 이 작업이 아니라 **main 의 `fo-dashboard` 워크플로 krx 작업**이 채운다: `python deriv/collect.py full index inv front basis iv pcr chainx chainwt chainwm` 을 돌리고 deriv-research 가지에 "deriv-research 수집 chainx|chainwt|chainwm"·"선물옵션 대시보드용 KRX 이어받기 <시각>" 커밋을 남긴다. 예약은 평일 19:17 인데 GitHub 지연으로 실제로는 다음 날 새벽에 들어왔다(11-24 07:27, 11-25 06:02, 11-26 05:18).
- D3 그래서 22:53 에 보면 세 파일의 마지막 날짜가 **오늘(장이 열린 날)보다 하루 이른 것이 보통**이다(11-25 22:53 시점 마지막 날짜 = 11-24). Fable 회차는 이때 걸지 않았다. 이유를 적은 기록은 저장소에 없어 확인 불가이나, 실행 문서의 "직전 거래일 **근처**"와 D2 에 맞는 행동이다. → 하루 밀림만으로는 걸지 않는다.
- D4 걸어야 하는 경우(실행 문서 (b) 그대로): 빠진 달이 있거나, fo-dashboard 가 여러 날 못 채워 마지막 날짜가 직전 거래일보다 이틀 이상 이르다. 이 경계("이틀 이상")는 실제 사례가 없어 **해석**이다 — 애매하면 걸지 말고 마지막 메시지에 날짜를 적는다(하루 한 번 도는 작업이라 다음 회차가 다시 본다).
- D5 `deriv/data/opt_chain_daily.csv.gz`(접미사 없음, 마지막 날짜 11-17)는 옛 `chain` 작업의 파일이다. `opt_chain*` 로 찾으면 함께 잡히지만 chainx·chainwt·chainwm 판정 대상이 아니다. 이것 때문에 걸지 않는다.
- D6 거래일 기준: 같은 가지의 `deriv/data/kospi_long.csv` 마지막 날짜들이 실제 거래일이다(index 작업이 함께 갱신). 달력으로 추정하지 않는다.
- D7 걸 때 trigger.txt 는 세 줄로 썼다: `full` / 작업들 / `# <날짜 시각> <누가>: <왜> — 속도·순서 그대로`. 커밋 제목은 "deriv-research 수집 다시(갈래 A): <작업들> — <이유>". 이제는 "(수집 관리)"처럼 누가 걸었는지 적는다(형식은 3절 예).
- D8 fo-dashboard krx 작업과 deriv-research 는 같은 줄(concurrency `deriv-research-v4`)에 서고 KRX 줄(krx-lock)도 함께 쓴다. (a)의 확인은 `deriv-research` 실행만 보지만, fo-dashboard 가 도는 중에 걸면 그 뒤에 줄을 선다 — 겹쳐 로그인하지는 않는다.

## 3. 좋은 예 (저장소에서 스크립트로 옮김)
(가) 빠진 날을 다시 받으려고 건 trigger.txt 와 커밋 제목 [deriv-research e41ca84, 11-21 갈래 A]
```
full
chainx chainwt chainwm
# 2026-11-21 10:5x 연구소 A: 옵션 자료 2026-05~07 빠진 날(chainx 16일·chainwt 45일·chainwm 43일, 오류 로그 없이 빈 응답) 다시 받기 + 11/20 까지 이어받기 — 받은 날은 건너뜀, 속도·순서 그대로
--- 커밋 제목
deriv-research 수집 다시(갈래 A): chainx chainwt chainwm — 2026-05~07 빠진 날·11/20 이어받기, 속도 그대로
```
(나) 지금의 trigger.txt — 11-21 뒤로 그대로(= 걸 일이 없었음) [deriv-research HEAD]
```
full
chainx_early
# 2026-11-21 18:1x 연구소 A: 월물 4개를 2010-01~2014-12 로 앞당겨 받기(지금까지 어떤 후보도 보지 않은 새 표본) — 같은 화면·같은 속도·이어받기, 2015~ 받은 날은 건너뜀
```
(다) 마지막 날짜 확인 결과(2026-11-26 12:5x, 이 검토가 gzip 으로 읽음) — 세 파일 모두 직전 거래일(11-25)까지, 빠진 달 없음
```
opt_chainx_daily.csv.gz  첫 날 2010-01-04  마지막 날 2026-11-25  거래일 4159개  빠진 달 없음
opt_chainwt_daily.csv.gz  첫 날 2019-09-23  마지막 날 2026-11-25  거래일 1430개  빠진 달 없음
opt_chainwm_daily.csv.gz  첫 날 2023-07-31  마지막 날 2026-11-25  거래일 808개  빠진 달 없음
kospi_long.csv(거래일 기준)  마지막 3일 2026-11-23 2026-11-24 2026-11-25
```
(라) 매일 채워지는 흔적 [deriv-research git log]
```
2ad29bb 11-25 20:18 UTC 선물옵션 대시보드용 KRX 이어받기 2026-11-26 05:18
8b6cdc0 11-25 20:18 UTC deriv-research 수집 chainwm
1623d85 11-25 20:17 UTC deriv-research 수집 chainwt
ebb8ac5 11-25 20:09 UTC deriv-research 수집 chainx
13ddb6e 11-24 21:02 UTC 선물옵션 대시보드용 KRX 이어받기 2026-11-25 06:02
a9df7c6 11-24 21:02 UTC deriv-research 수집 chainwm
e5bc836 11-24 21:01 UTC deriv-research 수집 chainwt
8ef7c33 11-24 20:54 UTC deriv-research 수집 chainx
```

## 4. 함정과 대처
- 11-20: 위클리 정리 코드가 0행을 냈다(14번 실행은 옛 코드) → collect.py 를 고치고(c11bf33) `chainwt chainwm` 을 다시 걸었다(d9cad4a·fc1fe6b). (c)의 "첫 로그에서 행이 0"이 이 경우다. 로그는 `deriv/out/log_full_*.txt`, 끝의 "저장 … n행" 을 본다.
- 11-21: 2026-05~07 에 오류 로그 없이 빈 응답으로 빠진 날(chainx 16일·chainwt 45일·chainwm 43일) → 같은 작업을 다시 걸어 이어받기(e41ca84). 마지막 날짜만 보지 말고 **빠진 달**도 본다.
- 11-21: 행사가 1,000 이상을 못 읽어 잘린 날 → `chainx_fix chainwt_fix chainwm_fix`(ae7d51c). `_fix`·`chainx_early` 는 그때 쓴 일회성 작업이다. 지금 trigger.txt 둘째 줄이 `chainx_early` 로 남아 있지만 다시 걸 때 그대로 두지 말고 필요한 작업만 쓴다.
- trigger.txt 를 push 하면 진행 중인 다른 deriv-research 실행을 **취소**한다(워크플로 첫 단계). 그래서 (a)를 꼭 먼저 본다.
- 수집은 대시보드 수집 시간대(08:15~10:50·15:35~18:05·20:15~22:50)에 스스로 기다린다. 22:53 에 걸면 바로 시작한다.
- 얕게 받은 저장소(--depth 30)에서는 trigger.txt 의 마지막 커밋이 "새 파일"처럼 보일 수 있다 — 이력이 잘린 것이지 새로 생긴 것이 아니다.

## 5. 끝내기 전 점검표
- [ ] deriv-research 워크플로가 진행 중·대기 중인지 먼저 봤다.
- [ ] chainx·chainwt·chainwm 세 파일만 판정했다(`opt_chain_daily.csv.gz` 제외).
- [ ] 마지막 날짜를 실제 거래일(kospi_long.csv)과 견줬고, 빠진 달이 없는지 봤다.
- [ ] 하루 밀림뿐이면 걸지 않았다. 걸었다면 순서 chainx → chainwt → chainwm, 첫 줄 `full`, 이유 줄을 적었다.
- [ ] collect.py 의 쉼(속도)을 줄이지 않았고 동시에 도는 수집을 만들지 않았다.
- [ ] 라운드·상태 폴더·보고 문서·카카오톡·signal_a 를 건드리지 않았다.
- [ ] push 전 `git pull --rebase origin deriv-research`. 마지막 메시지는 한두 줄.

## 6. 하지 말 것
- KRX 요청 속도(쉼)를 줄이거나 동시 수집을 만들지 않는다(계정·IP 가 막히면 대시보드 갱신까지 멈춘다).
- 비밀값(KRX·카카오)을 읽거나 쓰지 않는다. 저장소 안의 수집 코드를 세션에서 실행하지 않는다(KRX 로그인이 일어난다).
- main·대시보드·웹판을 건드리지 않는다. `round*.json`·`out*/`·`state*/`·보고 문서·카카오톡·4단계 (d)·`deriv/signal_a/` 를 하지 않는다.
- 진행 중인 수집이 있는데 trigger 를 push 하지 않는다. 원자료를 추정으로 채우지 않는다.
- 도구가 거부하면 우회하지 않는다.
