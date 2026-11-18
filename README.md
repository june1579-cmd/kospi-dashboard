# 장중 분봉 보관 가지(intraday-data)

- 매일 평일 장 마감 뒤 GitHub Actions(main 의 .github/workflows/intraday-collect.yml)가 intraday.py daily 를 돌려 새 분봉만 더함.
- 출처: Yahoo(코스피·코스피200 지수), 네이버(지수·코스피200 선물 주간), 한국투자증권 Open API(비밀값이 있으면).
- 저장: intraday/<출처>_<종목>_<간격>/<YYYY-MM>.csv.gz, 시각은 KST.
- 대시보드·KRX 계정과 무관(로그인 충돌 없음). main 가지에는 실행 파일 하나만 둠.
