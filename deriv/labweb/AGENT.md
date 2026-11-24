# 연구소용 웹판 만들기 (2026-11-24 사용자 지시)

사용자 지시(원문): "연구소용 웹판을 만들거야 내용은 코스피와 선물 그래프야, 그래프는 코스피 대시보드에 한번에 보기와 같은 형태이고 연구소에서 통과한 조합들의 매매확인용, 조합의 출처와 상세 내역과 수익률을 정렬할수 있도록 하고 선택하면 코스피와 선물 그래프에 표시 되도록. 간결하고 깔끔하게 만들어. 진행은 다른 세션에서하고 가능한 github를 이용하고 필요하면 에이전트를 만들거나 기존것을 이용해서 진행해" / "기존에 있는 정보들을 이용" / "opus 5.5 진행"

한국어·존댓말, 질문 없이 끝까지. **기존 것을 최대한 다시 쓴다. 목표 1시간 안팎.**

## 만들 것
- 위치: main 가지 `docs/lab/index.html`(+ 필요한 js·자료 `docs/lab/data/`). GitHub Pages 로 열린다(선물옵션 대시보드 docs/fo 와 같은 방식). claude.ai 쪽은 만들지 않는다.
- 그래프: 위 칸 코스피, 아래 칸 코스피200 선물. 코스피 대시보드 '한눈에 보기'(main `docs/page.html`·`docs/relief.js`)와 같은 형태·조작(기간 단추, 끌어서 이동, 확대, 값 보기). 그 코드에서 필요한 부분만 떼어 쓴다. 다른 신호·막대·카드는 넣지 않는다.
- 조합 표: 갈래(출처)·순위·회차·등급(통과/관찰/–)·조건 설명·독립 거래 수·적중률·아무 날과 차이·수익률 단순 합계·1회 평균·최근 신호일·네 거름 통과 여부. 열 제목을 누르면 정렬, 갈래·등급으로 거르기, 글자 검색.
- 선택: 표의 줄을 누르면 두 그래프에 그 조합의 매수일(다음 날 시가)·매도일(청산일 종가)을 표시하고 맞은 거래와 틀린 거래를 구분한다. 여러 개 고르면 색으로 구분(최대 5개), 다시 누르면 꺼진다. 고른 조합의 조건 전문과 거래 내역(신호일·매수일·매수가·매도일·매도가·수익률·맞음)을 아래에 표로.
- 생김새: 간결하고 깔끔하게. 휴대폰에서도 보이게. 노랑 신호색은 쓰지 않는다. 맨 아래 "자료 2026-11-20 까지 · 수익률은 코스피 지수 기준(신호 다음 날 시가 → 청산일 종가), 거래별 단순 합계 · 결과를 보고 고른 규칙의 숫자 · 투자 권유 아님".

## 다시 쓰는 재료 (새로 계산하지 않는다)
- 조합 목록·등급·설명: deriv-research `deriv/signal_a/x1/out/pool.csv`(251개). 수익·적중·거름: `x1/out/fixed.csv`, `falsify.csv`, `summary.json`. 열 뜻은 `x1/SPEC.md`·`x1/run.py`·`x1/report.md`.
- Signal A 관찰 목록 3개: `deriv/signal_a/signals/final_v1.json`, 거래일은 `deriv/signal_a/s3/out/` 과 `tN/out/` 에서.
- 가격: main `docs/data/market_daily.csv`(코스피), `docs/data/fut_daily.csv`(선물). 열을 먼저 확인하고 시가가 없으면 deriv-research `deriv/data/kospi_long.csv`·`fut_front_daily.csv` 를 쓴다. 날짜는 2026-11-20 까지로 자른다.
- **조합별 매매 날짜만 새로 뽑는다**: x1/run.py·x1/extract.py 가 이미 만드는 거래(신호일·청산일·수익)를 파일로 내보내는 작은 워크플로를 GitHub 에서 한 번 돌린다(연구소 candidates.pkl 은 판다스 최신판으로 저장돼 고정판으로 안 읽힌다 — x1/extract.py 방식 그대로). 거래일 기록이 없는 122개는 표에 "거래 내역 없음"으로 두고 추정하지 않는다.

## 진행
1. add_repo(owner june1579-cmd, repo kospi-dashboard, access push) → deriv-research 와 main 을 받는다.
2. 자료 내보내기 워크플로(`.github/workflows/labweb-data.yml`, deriv-research 가지, `deriv/labweb/run.txt` push 로 시작)를 써서 띄운다. 결과(`combos.json`, `trades.json`, 가격 json 또는 csv)를 main 의 `docs/lab/data/` 에 커밋하게 한다(pull --rebase --autostash, 3번까지 다시).
3. 계산을 기다리는 동안 화면 코드를 쓴다. Agent 도구가 있으면 '그래프'와 '표·선택' 을 나눠 동시에 쓰게 해도 된다.
4. 이 세션에서 화면을 실제로 열어 확인한다(로컬 서버 + 헤드리스 브라우저): 오류 없음, 표 정렬·거르기, 줄 선택 시 두 그래프에 표시, 휴대폰 너비. 고칠 것은 고친다.
5. main 에 push. 코스피 대시보드 웹판(`docs/index.html` 또는 page.html)은 고치지 않는다 — 링크는 다는 것이 한 줄로 안전하게 되면 달고, 아니면 달지 않고 보고한다.
6. **끝나면 카카오톡으로 보고한다(사용자 지시 2026-11-24 "완료되면 카카오톡으로 보고")**: 보내는 방법은 `.github/workflows/signal-a-pipeline.yml`(또는 signal-a-x1.yml)의 카카오톡 단계와 같은 방식 — 비밀값은 워크플로에서 `${{ secrets.이름 }}` 으로만 넘기고 이 세션은 읽지 않는다. `.github/workflows/labweb-notify.yml`(deriv-research 가지, `deriv/labweb/notify.txt` push 로 시작)을 만들어 그 파일의 글을 보내게 하고, 웹판을 main 에 올려 실제로 열리는 것을 확인한 뒤 notify.txt 를 push 한다. 글: 머리말 [연구소 웹판], 200자 이내 — 완성 여부, **누르면 열리는 링크**(사용자 지시 "링크와 함께": 글 안에 https://june1579-cmd.github.io/kospi-dashboard/lab/ 를 전체 주소로 적고, 기존 카카오톡 보내기 코드가 링크 단추를 지원하면 단추도 이 주소로 단다), 조합 수(그래프 표시 가능 n개 / 거래 내역 없음 n개), 못 한 것이 있으면 한 줄. 중간에 멈추게 되면(도구 거부·사용량 한도·3번 실패) 그때도 같은 방법으로 "[연구소 웹판] 중단 — <이유>" 를 보낸다. 워크플로 실행이 성공했는지 확인한다.
7. 마지막 메시지: 만든 것·주소(june1579-cmd.github.io/kospi-dashboard/lab/)·확인한 것·못 한 것을 다섯 줄 이내, 끝에 "투자 권유 아님".

## 꼭 지킬 것
- 고치는 곳: main 의 `docs/lab/`, deriv-research 의 `deriv/labweb/`·`.github/workflows/labweb-*.yml` 뿐. 코스피 대시보드(docs/page.html·relief.js·data), deriv/signal_a 결과, deriv/lab, 다른 워크플로는 읽기만 한다.
- KRX 로그인·수집을 하지 않는다. 비밀값은 읽지도 쓰지도 않는다. 예약 작업을 만들거나 켜지 않는다.
- 원자료가 없으면 추정하지 않고 "확인 불가"·"거래 내역 없음". 숫자를 새로 지어내지 않는다.
- 커밋은 git user dashboard-bot(dashboard-bot@users.noreply.github.com), push 전 git pull --rebase --autostash. gh 는 REST 만 된다(gh run list --json, gh api).
- 도구가 거부하면 우회하지 않고 멈춘 뒤 이유를 마지막 메시지에 적는다.
