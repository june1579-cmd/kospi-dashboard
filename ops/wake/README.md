# 정해진 시각 깨우기 장치 (업그레이드 요청 U-1126-2, 2026-11-26)

## 왜
GitHub 자체 예약(cron)이 이 저장소에서 크게 밀리거나 빠집니다. 2026-11-19~26 7일 동안 예정 373번 중 113번(30%)만 예약대로 돌았고(감시 watchdog 70번 중 7번), 늦은 것은 최대 11시간 넘게 밀렸습니다. 그래서 07:40 미국 옵션 카톡이 늦고, 감시·자동 재시도가 몇 시간씩 늦고, 첫 예약이 아예 안 돈 작업도 있었습니다.

## 어떻게
- **Cloudflare Worker `kospi-wake`**(무료 Cron Trigger, 매분)가 대상 워크플로의 예약 식과 지금 시각(UTC)을 맞춰 보고, 맞으면 GitHub API 로 `workflow_dispatch` 를 부릅니다. 이때 입력 `slot` 에 예약 식을 그대로 넣습니다.
- 각 워크플로는 `slot` 을 예약 식처럼 읽습니다(`github.event.schedule || github.event.inputs.slot`). 그래서 깨워서 돈 실행도 예약으로 돈 것과 똑같이 움직입니다(구분·시험 여부·KRX 수집 여부 같음). 실행 이름에 `· 깨우기` 가 붙습니다.
- **GitHub 예약은 예비로 남깁니다.** 늦게 온 예약 실행은 첫 단계(깨우기 중복 확인, `ops/wake/guard.py`)가 '장치가 이 칸을 이미 돌렸는지' 보고 돌렸으면 스스로 취소합니다. 장치가 그 칸을 놓쳤으면 예약 실행이 그대로 돕니다.
- 감시(`watchdog.py`)는 장치가 켜져 있는데 3시간 넘게 감시 자신이 깨워지지 않으면 "정해진 시각 깨우기 멈춤"을 알리고 수리 요청을 엽니다(토큰 만료 등).
- 대상: `ops/wake/targets.json`. 뺀 것과 이유도 거기 있습니다(공매도 10년 수집은 KRX 로그인이 한 시간마다라 횟수가 늘면 계정 위험, 멈춘 연구·1년 1번 작업, 다른 세션이 만드는 중인 intraday-flow·reach).
- 배포: `.github/workflows/wake-deploy.yml` 이 `ops/wake/build.py` 로 표를 만들고 wrangler 로 배포한 뒤 `ops/wake/active.json` 을 켭니다. 대상 워크플로가 바뀌면(ops/wake 를 고쳐 push) 다시 배포됩니다.

## 사용자가 할 일(한 번만) — 비밀값 3개
비밀값은 대화에 붙이지 말고 GitHub 저장소 설정에만 넣으세요.
1. **Cloudflare API 토큰**: Cloudflare 대시보드 → 오른쪽 위 내 프로필 → API Tokens → Create Token → 템플릿 **Edit Cloudflare Workers** → Account Resources 는 내 계정, Zone Resources 는 All zones(또는 필요 없음) → 만들기 → 값 복사.
2. **Cloudflare Account ID**: Cloudflare 대시보드 → Workers & Pages → 오른쪽에 보이는 Account ID 복사.
3. **GitHub 토큰(깨우기용)**: GitHub → Settings → Developer settings → Personal access tokens → **Fine-grained tokens** → Generate new token → Repository access: Only select repositories → `june1579-cmd/kospi-dashboard` → Repository permissions: **Actions: Read and write** 하나만 → 만료일 정하기(만료되면 감시가 알려 줌) → 만들기 → 값 복사.
4. 저장소 `june1579-cmd/kospi-dashboard` → Settings → Secrets and variables → Actions → New repository secret 으로 세 개 넣기:
   `CLOUDFLARE_API_TOKEN` · `CLOUDFLARE_ACCOUNT_ID` · `WAKE_GITHUB_TOKEN`
5. Actions 탭 → **wake-deploy** → Run workflow(또는 Claude 에게 "깨우기 장치 배포"라고 말씀). 성공하면 `ops/wake/active.json` 의 active 가 true 가 됩니다.

## 끄기·되돌리기
- 잠깐 끄기: Actions → wake-deploy → Run workflow → off 에 `true`. Worker 예약을 비우고 active 를 false 로 바꿉니다(GitHub 예약만 남음 — 전과 같음).
- 완전히 없애기: Cloudflare 대시보드에서 Worker `kospi-wake` 삭제 + 위 끄기.
- 워크플로의 `slot` 입력·확인 단계는 장치가 꺼져 있으면 아무것도 하지 않으므로 그대로 두어도 됩니다.
