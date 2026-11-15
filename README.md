# 코스피 미수 반대매매·신용 대시보드 — 자동 갱신 저장소

평일 **15:40(잠정)·18:40(확정)** 두 번, GitHub Actions 가 자료를 모아 통합 원자료 엑셀을 갱신하고 대시보드 자료를 다시 계산한 뒤 **카카오톡(나에게 보내기)** 으로 상황·매매 신호를 보고한다.
그 뒤 Claude 예약 작업(16:10·19:10)이 이 저장소를 읽어 대시보드(claude.ai 아티팩트)에 자료를 올린다.

```
수집(dashboard_collect.py) → 공개 저장소(kr-flow-dashboard) → 엑셀 갱신(daily_update.py)
→ 재계산(pkg/reproduce.py + quant.py) → 보고문(report_signals.py) → 카카오톡(kakao_send.py) → commit/push
```

## 한 번만 할 일

1. **GitHub 저장소 만들기** — 이 폴더 전체를 올린다(Public 추천: Claude 예약 작업이 비밀번호 없이 clone 한다. Private 으로 두려면 claude.ai 설정에서 GitHub 를 연결해야 한다).
2. **카카오톡 토큰** — PC 에서 `python kakao_auth.py` 한 번 실행(설명은 그 파일 맨 위). 나오는 두 값을 저장소 **Settings → Secrets and variables → Actions → New repository secret** 에 넣는다.
   - `KAKAO_REST_KEY`, `KAKAO_REFRESH_TOKEN` (Client Secret 을 켰다면 `KAKAO_CLIENT_SECRET` 도)
3. (선택) **KRX Open API 키** — `KRX_API_KEY` 비밀값. 있으면 VKOSPI 시가·고가·저가가 다음 날 아침 값으로 채워진다(없으면 종가만 공개 저장소에서).
4. (선택) KRX 정보데이터시스템 로그인 — `KRX_ID`, `KRX_PW`. 익명 조회가 막힐 때만.
5. **Actions 켜기** — 저장소 Actions 탭에서 "I understand… enable" 을 누른다. Settings → Actions → General → Workflow permissions 가 **Read and write** 인지 확인(commit/push 에 필요).
6. 첫 실행은 Actions 탭 → `dashboard-update` → **Run workflow**(tag 1840) 로 손으로 한 번 돌려 본다. `report/latest.md` 가 생기고 카카오톡이 오면 끝.
7. 저장소 주소(`https://github.com/<계정>/<저장소>.git`)를 Claude 대화에 알려 준다 → 대시보드 쪽 state/pipeline 에 적어 예약 작업이 돌기 시작한다.

## 날마다 자동으로 되는 것

| 시각(KST) | 무엇 | 비고 |
|---|---|---|
| 15:40 | 코스피·코스피200·ETF 시세(확정), 투자자별 **잠정치**(다음 금융, 원천 KRX), 금투협 전일분, VKOSPI 당일 종가(KRX 화면 탐색, 실패하면 다음 날), 미국 VIX | 카카오톡 "잠정 15:40" |
| 18:40 | KRX 투자자별 **확정치**(잠정치 교체, 바뀐 칸은 엑셀 값_교체_기록), ETF 투자자별·상장좌수, 야간선물(전날 저녁장) | 카카오톡 "확정 18:40" + 15:40 대비 변경 |
| 16:10·19:10 | Claude 예약 작업이 `out/manifest.json` 을 보고 바뀐 파일만 대시보드에 올림 | 휴대폰 푸시 |

휴장일·자료 미공표일은 18:40 에 "오늘 날짜 자료 없음" 한 줄만 온다.

- 투자자별(KRX 파일을 못 받아 공개 수집 저장소 값을 쓴 날): 다음 금융 값은 15:40 → 18시 → **다음 날 아침** 세 번 바뀌고, 다음 날 아침 값이 KRX 확정치와 같다(2026-10-20~26 KRX 파일과 5일 모두 일치, 18시 값은 최대 ±400억 차이). 그래서 다음 날 15:40 실행이 자동으로 바꿔 넣고 「값_교체_기록」에 남긴다.
- 금투협(예탁금·미수 반대매매·신용)은 다음 영업일 15시 무렵 공표 → 그날 15:40 실행에 들어온다. VKOSPI·등락 종목 수는 다음 날 08시, 외국인 보유 비중은 다음 날 10시 무렵.

## 자료 점검(2026-11-15 추가)

매 실행 끝에 `health_check.py` 가 자료 상태를 점검한다. 결과는 알림의 「자료:」 줄, 대시보드 「자료 상태」 칸(기준일 줄 아래), `report/latest.md` 의 「자료 점검」 절에 나온다.

- 자료마다 지금쯤 와 있어야 할 날짜까지 왔는지(코스피·투자자별·VKOSPI·금투협·미국 VIX·야간선물·환율·미국 금리·선물·ETF·애프터마켓)
- 수집 항목별 실패(`data/collect/…/status.json`), 출처 간 대조(코스피 종가 ↔ 네이버·다음, VIX ↔ CBOE 공식 파일·야후·네이버, 야간선물 KRX ↔ 차트로그, VKOSPI 화면 ↔ Open API, 투자자별 KRX ↔ 다음)
- 값 범위·같은 값 되풀이, 확정 뒤 값 변경, 이미 알린 신호의 취소
- 웹판 「9. 결론」 수기 카드가 멈췄는지(`docs/page.html` 의 「아래 네 카드는 M/D 장 마감」 기준일이 마지막 종가보다 2거래일 넘게 이르면 주의). 화면에서도 같은 기준으로 빨간 줄을 보이고 오래된 카드를 접는다(`docs/relief.js` fillStale)
- 상태: 정상 / 참고 / 주의 / 정정 / 오류. 새로 생긴 문제와 풀린 문제만 카카오톡 둘째 통으로 자세히 온다.

예약이 밀려 늦게 시작한 옛 구분 실행은 건너뛴다(`run_pipeline.py --force` 로 억지 실행). 판정은 달력 날짜가 아니라 장 날짜 기준이다(자정을 넘겨 끝난 확정 실행은 전날 장의 것).
한 단계가 멈추거나 실패해도 실행은 끝까지 가고, 그 오류는 `out/manifest.json` 의 `errors`·`data_line` 과 알림에 적힌다(자료 점검 뒤 단계의 오류는 「… · 실행 오류 n건」으로 덧붙는다).
Claude 예약 작업(게시)의 알림 「자료:」 줄은 `out/manifest.json` 의 `data_line` 을 그대로 쓴다. 자세한 경위는 `변경내역_2026-11-15_자료점검.txt`.

## 폴더

- `data/통합_원자료.xlsx` — 원자료 통합본(시트마다 원본 파일·출처 열, 원본파일_목록·값_교체_기록 시트). 자동 갱신이 여기에 쌓인다.
- `data/collect/dashboard_YYYYMMDD_<tag>/` — 그날 수집한 CSV(최근 6회 보관). `README.txt` 에 성공/실패 항목.
- `out/` — 대시보드 자료 CSV 25개 + `manifest.json`(sha256·마지막 날짜) + `checks.txt`
- `report/latest.md|json`, `report/kakao.txt`, `report/history/` — 보고문(큰 흐름 '12개 해 합의' = 그해 1위 12줄의 상승·하락 비율과 전 거래일·5거래일 전 대비 변화 포함. 하루 2줄 이상 바뀌거나 다수 쪽이 바뀐 날은 카카오톡 한 통 더)
- `state/kakao_token.json` — 연장된 카카오 refresh 토큰(REST 키로 암호화)
- `pkg/` — 계산 코드(`reproduce.py`, `quant.py`, `champ.py` = 큰 흐름 '그해 1위 조합' 탐색: 확정된 해는 `pkg/datasets/trend_champ_rules.csv`·`out/trend_champ_rules.csv`의 조합을 다시 쓰고 올해만 매번 다시 찾음, 약 15초)와 고정 자료

## 손으로 돌릴 때

```
pip install -r requirements.txt
python run_pipeline.py --tag 1840            # 전체
python run_pipeline.py --tag 1840 --no-kakao # 카카오톡 없이
python dashboard_collect.py --days 10 --allow-today --tag 1540   # 수집만
```

## 자주 생기는 일

- **카카오톡이 안 옴**: Actions 로그의 "7 카카오톡" 줄. `토큰 갱신 실패` 면 두 달 넘게 안 쓴 것 → `kakao_auth.py` 다시 실행해 비밀값 교체.
- **KRX 수집 실패(pykrx)**: GitHub 러너(미국) IP 가 막힌 경우. `data/collect/.../README.txt` 의 실패 목록 확인. 공개 저장소 값으로 대부분 채워지고, 없는 칸은 비워 둔다(추정으로 채우지 않음).
- **GitHub 예약 실행이 늦음**: Actions 의 schedule 은 몇 분~수십 분 늦을 수 있다. Claude 예약 작업은 30분 여유를 두고 돈다.

투자 권유 아님.
