# intraday-flow
장중 코스피200 선물 투자자별(외국인·개인·기관) 누적 순매수와 선물·현물 시세를 5초 간격으로 쌓는 가지(2026-11-26~).
- flow/YYYY-MM/YYYY-MM-DD.csv — 한 줄 = 한 번 조회(시각 KST). f_ 로 시작하는 칸은 KIS '시장별 투자자 동향(시세)'의 그날 누적값(수량=계약, 금액=백만원 단위로 추정 — 원자료 그대로).
- flow/meta.json — 날짜·작업(오전/오후)별 사용 코드·행 수·호출 수·오류 수.
- 09:06~09:12 은 KIS 호출 한도 재측정(09:07)과 겹치지 않게 비어 있다.
만드는 곳: main 의 reach/flow.py · .github/workflows/intraday-flow.yml
