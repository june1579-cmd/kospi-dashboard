# 미국·한국 선물옵션 대시보드 (fo)

수집·계산·게시가 전부 이 저장소 안에서 돕니다. Claude 대화나 내 컴퓨터가 없어도 갱신됩니다.

- **웹판**: https://june1579-cmd.github.io/kospi-dashboard/fo/ (`docs/fo/` — 열 때마다 저장소의 최신 자료를 읽음)
- **자동 실행**: 워크플로 `fo-dashboard` — 화~토 06:37(뉴욕 마감·CFTC 공표 뒤 — 2026-11-24 07:47 에서 당김), 화~토 10:47(Cboe 풋/콜 날짜별 파일 다시 받기, KRX 로그인 없음 — 2026-11-24 추가), 월~금 19:17(KRX 확정치 뒤) KST, 그리고 코스피 대시보드 갱신(dashboard-update)이 성공할 때마다 바로 한 번(KRX 로그인 없음, 2026-11-24 추가)
- **손으로 돌리기**: Actions 탭 → `fo-dashboard` → **Run workflow** (`krx` 를 `false` 로 두면 KRX 로그인 없이 계산만 다시 함). 웹판 위쪽 [지금 다시 계산] 단추가 이 화면으로 갑니다.

## 흐름

| 단계 | 파일 | 하는 일 | 결과 |
|---|---|---|---|
| 1. KRX 이어받기(`krx` 작업) | `deriv/collect.py` (deriv-research 가지) | 선물 투자자별·근월물·베이시스·풋/콜·내재변동성·옵션 행사가별(월물·위클리)을 받은 날 다음부터 이어받기 | deriv-research 가지 `deriv/data/` |
| 2. 미국 공개 자료 | `fo/collect_us.py` | CFTC(ES·NQ 주체별), Cboe 풋/콜·미결제, VIX 기간구조(야후 먼저 · Cboe 예비, 2026-11-24), 야후 일봉 — 키 불필요 | `fo/data/*.csv`, `status.json` |
| 3. 지표·확률 계산 | `fo/build.py`, `fo/model.py` | 일별 지표, 만기·롤오버·미국→한국 표, 방향 확률(걷기 전진 검증) | `docs/fo/data/` 파일 6개 |
| 4. 웹판 | `docs/fo/index.html`, `app.js`, `style.css` | 파일 6개를 읽어 그리기만 함(숫자를 만들지 않음) | GitHub Pages |

## 규칙

- 원자료를 추정으로 채우지 않습니다. 받지 못한 값은 빈칸으로 두고 웹판 「확인하지 못한 값」에 적습니다.
- 방향 확률은 검증(앞 60% 학습 / 20% 검증 / 20% 보류)을 통과한 칸에서만 모형 값을 쓰고, 나머지는 과거 상승 비율(기준선)을 적습니다.
- 같은 입력이면 같은 결과가 나오게 시드(20261122)·라이브러리 버전·스레드 수를 고정했습니다.
- 비밀값은 KRX 로그인(`KRX_ID`·`KRX_PW`·`KRX_API_KEY`)만 쓰며 이미 저장소 Secrets 에 있는 것을 그대로 씁니다.
- 색: 상승 = 빨강, 하락 = 파랑. 투자 권유 아님.

## 고치는 법

- 화면 문구·그래프: `docs/fo/index.html`, `docs/fo/app.js` 를 GitHub 에서 바로 고치면 Pages 에 반영됩니다.
- 지표·모형: `fo/build.py`, `fo/model.py` 를 고친 뒤 Run workflow.
- 실행 시각: `.github/workflows/fo-dashboard.yml` 의 `cron`.

## 10절(옵션 구조 · 갭 분해 · 연구소 기준 검증) — 2026-11-23 추가

- claude.ai 미국·한국 대시보드에 있던 기능을 웹판으로 옮겼습니다. 자료는 `deriv-research` 가지의 `deriv/us/out/dash.json` 이고, 기본 가지의 워크플로 `usk`(화~토 07:17, 월~금 19:27 KST)가 계산합니다.
- 화면 코드는 `docs/fo/usk.js` 한 파일입니다(그리기만 함). 실패·멈춤은 `watchdog` 이 한 시간마다 보고 다시 돌립니다.

## 11절(미국 옵션 아침 추정 · 공개 시각) — 2026-11-24 추가

- 화~토 07:40 KST 카카오톡으로 직전 장 마감 뒤 SPY·QQQ 콜벽·풋벽 추정, 전날 확정치와 비교, 최근 흐름, 어제 추정의 정확도를 보낸다. 실패하면 실패 알림을 보낸다.
- 워크플로 `us-walls`(계산·발송), `pub-watch`(공개 시각 측정, 끝나면 스스로 꺼짐). 화면 코드 `docs/fo/uswalls.js`. 자세한 것은 `uswalls/README.md`.
