# 자료 사전 — deriv/data (A5)

열 이름은 KRX 화면 응답 그대로. 확인 방법: probe(2026-11-18, `deriv/out/probe/probe.json`)와 화면 jsp 의 단위 설정.

## inv_daily.csv — 투자자별 거래실적 일별추이 (MDCSTAT13102 · 상세 13103)

| 열 | 뜻 |
|---|---|
| TRD_DD | 날짜(YYYY/MM/DD) |
| A07 · A08 · A09 · A12 | 기관 합계 · 기타법인 · 개인 · 외국인 합계 (13102) |
| A01~A06 · A08 · A09 · A10 · A11 | 금융투자 · 보험 · 투신 · 은행 · 기타금융 · 연기금 등 · 기타법인 · 개인 · 외국인 · 외국인 합계 (13103, 상세='Y'). 확인: 겹치는 2,694일 모두 13102 의 A12(외국인 합계) = A11 = A10 (100% 일치) → A11 을 외국인으로 씀 |
| AMT_OR_QTY | 전체(순매수 기준이면 0) |
| 상품 · 권리 · 단위 · 장구분 | FUK2I 등 · ALL/C/P · AMT(원)/QTY(계약) · 정규/야간 |

- 값은 순매수(매수 − 매도). AMT 는 선물은 약정금액(가격 × 승수 × 계약), 옵션은 프리미엄 금액.
- 13102(기본) 코스피200 선물 계열은 2,694일만 받혔고 2018~2025년이 통째로 빠짐(앞선 실행의 2년 조각 실패) → 분석은 13103(상세, 4,655일)에서 기관(금융투자~연기금 합)·개인·외국인(A11)을 다시 만들어 씀.
- 상품 코드는 `KR___` 접두(예: `KR___FUK2I`)로만 응답한다(`KRDRV` 접두는 빈 응답).
- 당일 최종치는 18:00 이후 제공(화면 안내).

## basis_daily.csv — 베이시스 추이 (MDCSTAT13401)

날짜마다 상장 월물 전부가 온다. 분석은 종가가 있는 가장 가까운 월물만 쓴다.
`TDD_CLSPRC` 선물 종가 · `SPOT_PRC` 코스피200 · `THEO_PRC` 이론가 · `MKT_BASIS` 선물 − 현물 · `THRY_BASIS` 이론가 − 현물 · `DIFF_RT` 괴리율(%) = (선물 − 이론가) / 이론가.

## iv_daily.csv — 내재변동성 추이(옵션) (MDCSTAT13501)

`BAS_DD` 날짜 · `REP_IMP_VOLT` 대표 내재변동성 · `CALL_AVG_IMP_VOLT` / `PUT_AVG_IMP_VOLT` 콜·풋 평균 내재변동성 · `HIST_VOLT1~8` 역사적 변동성 10·20·30·60·90·120·150·180일(독립 검수에서 코스피200 실현변동성과 대조, 중앙 오차 0.16~0.17%p로 확인).

## pcr_daily.csv — P/C Ratio 추이 (MDCSTAT13601)

`PVOL` 풋 거래량 · `CVOL` 콜 거래량 · `PCRATIO` 풋/콜.

## fut_front_daily.csv — 최근월물 시세 추이(선물) (MDCSTAT12701)

`TRD_DD` 날짜(뒤에 "(주간)") · 시가·고가·저가·종가 · `ACC_TRDVOL` 거래량 · `ACC_TRDVAL` 거래대금(원) · `ACC_OPNINT_QTY` 미결제약정(계약).

## program_daily.csv.gz — 프로그램매매 (MDCSTAT02601, 날짜마다 1회)

`ITM_TP_NM` 차익 / 비차익 / 전체 · `NETBID_TRDVAL` 순매수 금액(원) 등.

## opt_chain_daily.csv.gz — 코스피200 옵션 전종목(압축) (MDCSTAT12501, 2015년부터 날짜마다 1회, 2026-11-18 밤 수집 중)

가까운 두 결제월, 기초자산 ±20% 행사가만 저장. `cp` 콜/풋 · `ym` 결제월 · `K` 행사가 · `settle` 정산가 · `close` 종가 · `vol` 거래량 · `oi` 미결제 · `spot` 코스피200.
화면에 행사가별 내재변동성은 없다 → 분석에서 정산가로 역산.

## 기타

- `kospi_long.csv`, `k200_long.csv`: 지수 일별(pykrx).
- `regimes.csv`: 제도 구간(A2).
- 대시보드 자료 재사용: `pkg/history/01_코스피_일별시세.csv`(2006~), `pkg/history/01_코스피_투자자별_순매수_거래대금.csv`(현물 투자자별, 2006~), `pkg/datasets/market_daily.csv`(VKOSPI 2015~), `pkg/datasets/night_fut.csv`(야간 2025-06~), `pkg/datasets/q_daily.csv`(기존 대시보드 확률).

## 검증된 관계(독립 검수, 2026-11-18)

- 13102: A07 = A01+…+A06(13103), 투자자 합 = 0(4,655일 전부).
- MKT_BASIS = 선물 종가 − SPOT_PRC(100%), SPOT_PRC = 코스피200 종가(100%), DIFF_RT 는 만기일 74일 빈칸(이론가 0).
- PCRATIO = PVOL/CVOL(100%), 프로그램 NETBID = BID − ASK, 차익 + 비차익 = 전체(100%).
