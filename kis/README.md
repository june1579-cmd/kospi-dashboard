# 한국투자증권(KIS) Open API

## 1. GitHub Secrets 등록 (한 번만)
저장소 Settings → Secrets and variables → Actions → New repository secret 에서 6개를 넣는다.

| 이름 | 값 |
|---|---|
| `KIS_REAL_APP_KEY` | 실전 APP Key |
| `KIS_REAL_APP_SECRET` | 실전 APP Secret |
| `KIS_REAL_CANO` | 실전 계좌번호 8자리 |
| `KIS_MOCK_APP_KEY` | 모의 APP Key |
| `KIS_MOCK_APP_SECRET` | 모의 APP Secret |
| `KIS_MOCK_CANO` | 모의 계좌번호 8자리 |

키·계좌번호는 저장소 파일에 절대 적지 않는다(공개 저장소).

## 2. 연결 시험
Actions → **kis-connect-test** → Run workflow → `both`
결과는 카카오톡으로 온다: `토큰O 시세O 잔고O 웹소켓O` 이면 연결 끝.
공개 로그라 잔고 금액은 찍지 않는다.

## 3. 내 PC에서 시험
`kis/.env.example` 을 `kis/.env` 로 복사해 값을 채우고 `python kis/kis_connect_test.py both`
(`.env` 는 .gitignore 에 있어 올라가지 않는다)

## 참고
- 접근토큰은 1분에 1번만 발급, 24시간 유효 → 파일에 저장해 재사용
- 모의투자 호출은 초당 1회 수준
- KIS를 쓰는 워크플로는 `concurrency: kis-api` 한 줄로 묶어 같은 키가 동시에 돌지 않게 한다
