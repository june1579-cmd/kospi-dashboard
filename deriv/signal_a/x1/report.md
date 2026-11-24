# Signal A X1 — 연구소 갈래 A·B·C·D 상위 100위 거름 시험 (2026-11-24 09:28, 자료 끝 2026-11-20)

> 사용자 지시 "전에 조사한 a b c d 의 각각 상위 100위 전부 거름 테스트". 숫자·표·아래 문장은 GitHub 가 x1/run.py 로 계산해 자동으로 쓴 것입니다(미리 정한 목록: x1/SPEC.md).
> 매매 기준: 코스피 지수, 신호 다음 날 시가 매수 → 그 후보의 청산일 종가 매도, 독립 거래, 수익 합계는 단순 합. 표본 10개 미만은 %로 적지 않습니다.

## 1. 결론

1. 연구소 네 갈래의 상위 후보는 모두 **251개**(A 98·B 100·C 15·D 38)입니다. 이 가운데 거래일 기록을 구한 **15개**를 네 거름에 넣었고, 나머지 **236개는 확인 불가(거래일 기록 없음)** 입니다(확인 불가 가운데 연구소 통과 등급 28개·관찰 등급 25개).
2. **네 거름을 모두 넘은 후보는 없습니다(0개).** 거름별 통과 수는 2절 표에 있습니다.
3. 거름별로 보면: A: ① 0 · ② 0 · ③ 0 · ④ 0 (넣은 0개 중) / B: ① 0 · ② 0 · ③ 0 · ④ 0 (넣은 0개 중) / C: ① 2 · ② 6 · ③ 0 · ④ 1 (넣은 15개 중) / D: ① 0 · ② 0 · ③ 0 · ④ 0 (넣은 0개 중).
4. '해마다 그 전 자료로 고르는 절차'(갈래마다 20개, 모두 80개) 가운데 네 거름을 모두 넘은 것은 **0개**입니다. 갈래별로 가장 좋은 절차: A: 거래가 10건 이상인 절차 없음 / B: 거래가 10건 이상인 절차 없음 / C: 거래가 10건 이상인 절차 없음 / D: 거래가 10건 이상인 절차 없음. **상위 100개라는 묶음 자체가 전체 기간 결과로 뽑힌 것이라 이 숫자도 좋게 나오는 쪽으로 기웁니다.**
5. Signal A 관찰 목록 3개와 견줄 '넷 다 통과' 후보가 없습니다. 갈래별 가장 좋은 절차와 관찰 목록의 겹침은 5절에 적었습니다.
6. 이번에 더한 시험 가짓수는 95가지(고정 규칙 15 + 절차 80)이고, Signal A 원장 누적은 264,845가지입니다. 최종 후보·관찰 목록(signals/final_v1.json)은 바꾸지 않았습니다.

## 2. 갈래별 숫자 — (가) 고정 규칙 판

거름 ①(가)는 **결과를 보고 고른 규칙의 숫자**입니다(그 규칙의 2016~2026 거래가 같은 해 아무 날보다 10%p 이상 높고 독립 30건 이상). ②③④는 전체 기간(2010~) 거래로 쟀습니다.

| 갈래 | 대상 | 거래일 기록 있음 | 확인 불가 | ① 다음 해 꼴(결과를 보고 고른 규칙의 숫자) | ② 2026년·큰 변동 해 | ③ 반증 8개 모두 | ④ 가짜 p 1% 미만 | 넷 다 통과 | 참고: ②③④도 2016~만으로 |
|---|---|---|---|---|---|---|---|---|---|
| 갈래 A | 98 | 0 | 98 | 0 | 0 | 0 | 0 | **0** | 0 |
| 갈래 B | 100 | 0 | 100 | 0 | 0 | 0 | 0 | **0** | 0 |
| 갈래 C(미국·한국 연동) | 15 | 15 | 0 | 2 | 6 | 0 | 1 | **0** | 0 |
| 갈래 D(하락 전담) | 38 | 0 | 38 | 0 | 0 | 0 | 0 | **0** | 0 |

- 대상이 100개가 안 되는 갈래는 순위표에 오른 서로 다른 후보가 그만큼뿐입니다(갈래 D 는 내림 방향만).
- ②에서 큰 변동 해(2011·2020·2026) 독립 거래가 10건 미만이라 '판정 불가'(넘지 못한 것으로 침)인 후보: A 0·B 0·C 2·D 0개.
- ③을 '8개 모두' 대신 '종합 버팀(7개 이상)'으로 세면: A 0·B 0·C 2·D 0개.

거래일을 어디서 구했나

| 갈래 | 순위표(열이 없어 건너뛴 옛 회차) | 서로 다른 후보 | 대상(상위 100) | 연구소 통과 / 관찰(선물 기준) | 그 회차 기록 | 다른 회차 기록(숫자 일치) | 다시 만듦(갈래 C) | 확인 불가 | 확인 불가 중 연구소 통과 / 관찰 |
|---|---|---|---|---|---|---|---|---|---|
| 갈래 A | 49개(건너뜀 16) | 98 | 98 | 12 / 8 | 0 | 0 | 0 | 98 | 12 / 8 |
| 갈래 B | 45개(건너뜀 10) | 142 | 100 | 16 / 17 | 0 | 0 | 0 | 100 | 16 / 17 |
| 갈래 C(미국·한국 연동) | 1개(건너뜀 0) | 15 | 15 | 0 / 0 | 0 | 0 | 15 | 0 | 0 / 0 |
| 갈래 D(하락 전담) | 10개(건너뜀 0) | 38 | 38 | 0 / 0 | 0 | 0 | 0 | 38 | 0 / 0 |

- 확인 불가는 대부분 오래된 회차의 거래일 파일(candidates.pkl)이 저장소 크기 관리로 지워졌기 때문입니다. 추정으로 채우지 않았습니다.
- 다른 회차 기록은 id 와 설명이 모두 같고, 그 거래일로 연구소 방식(선물, 앞 구간)으로 다시 잰 숫자가 순위표와 똑같을 때만 썼습니다.

통과한 거름 수별 후보 수

| 갈래 | 4개 | 3개 | 2개 | 1개 | 0개 |
|---|---|---|---|---|---|
| 갈래 A | 0 | 0 | 0 | 0 | 0 |
| 갈래 B | 0 | 0 | 0 | 0 | 0 |
| 갈래 C(미국·한국 연동) | 0 | 0 | 2 | 5 | 8 |
| 갈래 D(하락 전담) | 0 | 0 | 0 | 0 | 0 |

연구소 등급(선물 기준)과 코스피 지수 기준 숫자

| 갈래 | 연구소 통과(거름에 넣은 것) | 그중 코스피 지수로도 통과 숫자(35건·85%) | 그중 코스피 지수로는 관찰 숫자(80%) | 연구소 관찰(거름에 넣은 것) | 그중 코스피 지수로 통과·관찰 숫자 | 넣은 것 전체 중 코스피 통과 숫자 | 넣은 것 전체 중 코스피 관찰 숫자 |
|---|---|---|---|---|---|---|---|
| 갈래 A | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 갈래 B | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 갈래 C(미국·한국 연동) | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 갈래 D(하락 전담) | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

## 3. 네 거름을 모두 넘은 후보

**없습니다.** 네 거름을 모두 넘은 연구소 후보는 0개입니다.

## 4. (나) 갈래별 '해마다 고르는 절차'

해 Y(2016~2026)마다 그 갈래 상위 100개 가운데 **Y 전 자료만으로** 통과 꼴(적중 85%)·관찰 꼴(80%)을 채운 규칙을 골라 Y 에 쓴 성적입니다. 쓰는 법은 T1 과 같은 꼴(윌슨 하한 상위 1·5·20개 × 하나라도 / 20% 이상 함께).
최소 거래 수는 둘 다 돌렸습니다: 35건 고정(지시 그대로) / T1 과 같은 줄인 건수(2016년 12건 … 2026년 33건).

> **조심: 상위 100개라는 묶음 자체가 전체 기간(2026년까지) 결과로 뽑힌 것이라 이 숫자도 좋게 나오는 쪽으로 기웁니다.** Signal A 줄기의 다음 해 성적(묶음도 미리 정함)과 같은 값으로 읽으면 안 됩니다.

| 갈래 | 묶음의 규칙 수(주 방향·거래일 있음) | 독립 30건 이상 절차(20개 중) | ① 다음 해 기준 | ② 2026년·큰 변동 해 | ③ 반증 8개 모두 | ④ 가짜 p 1% 미만 | 넷 다 통과 | 통과 숫자(35건·85%)를 다음 해 성적으로 | 관찰 숫자(80%) |
|---|---|---|---|---|---|---|---|---|---|
| 갈래 A | 0 | 0 | 0 | 0 | 0 | 0 | **0** | 0 | 0 |
| 갈래 B | 0 | 0 | 0 | 0 | 0 | 0 | **0** | 0 | 0 |
| 갈래 C(미국·한국 연동) | 14 | 0 | 0 | 0 | 0 | 0 | **0** | 0 | 0 |
| 갈래 D(하락 전담) | 0 | 0 | 0 | 0 | 0 | 0 | **0** | 0 | 0 |

갈래별 가장 좋은 절차(독립 30건 이상 가운데 아무 날과의 차이가 가장 큰 것)

| 갈래 | 절차 | 독립 거래 | 다음 해 적중 | 같은 해 아무 날 | 차이 | 수익 합계 | 앞(2016~2023) · 뒤(2024~) | 2026년 | 가짜 p(보정 전 → ×80) | 네 거름 | 종합 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 갈래 A | 없음 | – | – | – | – | – | – | – | – | – | – |
| 갈래 B | 없음 | – | – | – | – | – | – | – | – | – | – |
| 갈래 C(미국·한국 연동) | 없음 | – | – | – | – | – | – | – | – | – | – |
| 갈래 D(하락 전담) | 없음 | – | – | – | – | – | – | – | – | – | – |

갈래 A — 절차 20개 가운데 거래 10건 이상 0개(차이 큰 순)

- 거래가 10건 이상인 절차가 없습니다(그 전 자료로 꼴을 채운 규칙이 거의 없었음).

갈래 B — 절차 20개 가운데 거래 10건 이상 0개(차이 큰 순)

- 거래가 10건 이상인 절차가 없습니다(그 전 자료로 꼴을 채운 규칙이 거의 없었음).

갈래 C(미국·한국 연동) — 절차 20개 가운데 거래 10건 이상 0개(차이 큰 순)

- 거래가 10건 이상인 절차가 없습니다(그 전 자료로 꼴을 채운 규칙이 거의 없었음).

갈래 D(하락 전담) — 절차 20개 가운데 거래 10건 이상 0개(차이 큰 순)

- 거래가 10건 이상인 절차가 없습니다(그 전 자료로 꼴을 채운 규칙이 거의 없었음).

해마다 고른 규칙 수(관찰 꼴 · 줄인 건수 기준 / 35건 고정 기준)

| 갈래 | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 갈래 A | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| 갈래 B | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| 갈래 C(미국·한국 연동) | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| 갈래 D(하락 전담) | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |

## 5. Signal A 관찰 목록 3개와 견줌 (같은 뿌리인지)

재는 법: 2016년 이후 독립 거래가 들고 있는 날(매수일~청산일)의 겹침. 양쪽 모두 80% 이상 = 사실상 같은 신호, 한쪽만 80% 이상 = 한쪽이 포함, 한쪽 50% 이상 = 많이 겹침.

- 넷 다 통과한 연구소 후보가 없어 견줄 것이 없습니다.

## 6. 조심할 점

- **확인 불가 236개**(A 98·B 100·C 0·D 38)는 거래일 기록이 없어 거름에 넣지 못했습니다. 넷 다 통과 수는 '넣은 것 가운데'의 수입니다.
- 연구소 후보는 전체 기간 결과를 보고 고른 고정 규칙입니다. 거름 ①(가)는 숫자 꼴만 맞춘 것이고, 진짜 '다음 해 성적'은 4절의 절차뿐입니다. 그 4절도 묶음이 결과를 보고 뽑힌 것이라 기운 숫자입니다.
- 연구소 등급·순위는 코스피200 선물 기준입니다. 코스피 지수로 재면 적중이 5~10%p 낮아질 수 있습니다(NOTES.md 1절). 이 보고서의 적중은 모두 코스피 지수 기준입니다.
- 같은 뿌리의 규칙(문턱만 조금 다른 것)이 순위표에 여러 개 올라 있습니다. 넷 다 통과가 여러 개여도 서로 다른 신호가 여러 개라는 뜻이 아닙니다.
- 갈래 C 의 신호일은 저장소의 미국 지표 파일(deriv/us/out)로 다시 만든 것입니다(고정 릴리스에는 없는 자료, 끝 날짜로 자름). 연구소 순위표의 앞 구간 숫자와 같을 때만 썼습니다.
- 거름 ②는 큰 변동 해(2011·2020·2026) 독립 거래가 10건 미만이면 판정 불가(넘지 못함)입니다. 거래가 드문 규칙에 불리합니다.
- 이 거름(네 가지)은 Signal A 최종 심사 때 결과를 본 뒤 총괄이 정한 것입니다. CRITERIA.md 의 '최종 후보' 기준(통과 숫자 + 3절 셋 다)과는 다릅니다. 이번 시험으로 최종 후보·관찰 목록을 바꾸지 않았습니다.
- 새 자료에서 실제 신호 10건이 쌓이기 전에는 어느 것도 '확정'이라고 쓰지 않습니다(CRITERIA 4절).

계산 중 적어 둔 것

- A: out/round_040/a03/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_040/a03c/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_040/a04/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_040/a05/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_040/a06/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_040/a07s0/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_040/a07s1/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_040/a07s2/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_040/a12/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_041/a03/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_041/a03c/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_041/a04/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_041/a05/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_041/a06/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_041/a07s0/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_041/a07s1/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_041/a07s2/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_041/a12/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_042/a03/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_042/a03c/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_042/a04/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_042/a05/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_042/a06/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_042/a07s0/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_042/a07s1/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_042/a07s2/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_042/a12/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_043/a03/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_043/a03c/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_043/a04/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_043/a05/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_043/a06/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_043/a07s0/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_043/a07s1/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_043/a07s2/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_043/a12/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_044/a03/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_044/a03c/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_044/a04/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_044/a05/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_044/a06/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_044/a07s0/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_044/a07s1/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_044/a07s2/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_044/a12/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_045/a03/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_045/a03c/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_045/a04/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_045/a05/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_045/a06/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_045/a07s0/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_045/a07s1/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_045/a07s2/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_045/a12/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_046/a03/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_046/a03c/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_046/a04/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_046/a05/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_046/a06/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_046/a07s0/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_046/a07s1/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_046/a07s2/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_046/a12/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_047/a03/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_047/a03c/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_047/a04/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_047/a05/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_047/a06/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_047/a07s0/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_047/a07s1/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_047/a07s2/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_047/a12/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_048/a03/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_048/a03c/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_048/a04/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_048/a05/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_048/a06/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_048/a07s0/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_048/a07s1/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_048/a07s2/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_048/a12/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_049/a03/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_049/a03c/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_049/a04/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_049/a05/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_049/a06/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_049/a07s0/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_049/a07s1/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_049/a07s2/candidates.pkl 를 못 읽음(NotImplementedError)
- A: out/round_049/a12/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_036/a03/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_036/a03c/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_036/a04/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_036/a05/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_036/a06/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_036/a07s0/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_036/a07s1/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_036/a07s2/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_036/a12/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_037/a03/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_037/a03c/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_037/a04/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_037/a05/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_037/a06/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_037/a07s0/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_037/a07s1/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_037/a07s2/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_037/a12/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_038/a03/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_038/a03c/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_038/a04/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_038/a05/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_038/a06/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_038/a07s0/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_038/a07s1/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_038/a07s2/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_038/a12/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_039/a03/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_039/a03c/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_039/a04/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_039/a05/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_039/a06/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_039/a07s0/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_039/a07s1/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_039/a07s2/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_039/a12/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_040/a03/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_040/a03c/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_040/a04/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_040/a05/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_040/a06/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_040/a07s0/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_040/a07s1/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_040/a07s2/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_040/a12/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_041/a03/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_041/a03c/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_041/a04/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_041/a05/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_041/a06/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_041/a07s0/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_041/a07s1/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_041/a07s2/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_041/a12/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_042/a03/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_042/a03c/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_042/a04/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_042/a05/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_042/a06/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_042/a07s0/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_042/a07s1/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_042/a07s2/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_042/a12/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_043/a03/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_043/a03c/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_043/a04/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_043/a05/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_043/a06/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_043/a07s0/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_043/a07s1/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_043/a07s2/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_043/a12/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_044/a03/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_044/a03c/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_044/a04/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_044/a05/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_044/a06/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_044/a07s0/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_044/a07s1/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_044/a07s2/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_044/a12/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_045/a03/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_045/a03c/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_045/a04/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_045/a05/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_045/a06/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_045/a07s0/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_045/a07s1/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_045/a07s2/candidates.pkl 를 못 읽음(NotImplementedError)
- B: out_b/round_045/a12/candidates.pkl 를 못 읽음(NotImplementedError)
- C: 미국 지표 파일 2007-01-02~2026-11-20 49개, 청산일 계산 = lab_common
- D: out_d/round_001/a03/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_001/a03c/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_001/a04/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_001/a05/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_001/a06/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_001/a07s0/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_001/a07s1/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_001/a07s2/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_002/a03/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_002/a03c/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_002/a04/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_002/a05/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_002/a06/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_002/a07s0/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_002/a07s1/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_002/a07s2/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_002/a12/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_002/a13/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_003/a03/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_003/a03c/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_003/a04/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_003/a05/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_003/a06/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_003/a07s0/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_003/a07s1/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_003/a07s2/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_003/a12/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_003/a13/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_004/a03/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_004/a03c/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_004/a04/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_004/a05/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_004/a06/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_004/a07s0/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_004/a07s1/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_004/a07s2/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_004/a12/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_004/a13/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_005/a03/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_005/a03c/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_005/a04/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_005/a05/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_005/a06/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_005/a07s0/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_005/a07s1/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_005/a07s2/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_005/a12/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_005/a13/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_006/a03/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_006/a03c/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_006/a04/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_006/a05/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_006/a06/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_006/a07s0/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_006/a07s1/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_006/a07s2/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_006/a12/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_006/a13/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_007/a03/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_007/a03c/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_007/a04/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_007/a05/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_007/a06/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_007/a07s0/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_007/a07s1/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_007/a07s2/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_007/a12/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_007/a13/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_008/a03/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_008/a03c/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_008/a04/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_008/a05/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_008/a06/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_008/a07s0/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_008/a07s1/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_008/a07s2/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_008/a12/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_008/a13/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_009/a03/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_009/a03c/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_009/a04/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_009/a05/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_009/a06/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_009/a07s0/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_009/a07s1/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_009/a07s2/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_009/a12/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_009/a13/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_010/a03/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_010/a03c/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_010/a04/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_010/a05/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_010/a06/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_010/a07s0/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_010/a07s1/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_010/a07s2/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_010/a12/candidates.pkl 를 못 읽음(NotImplementedError)
- D: out_d/round_010/a13/candidates.pkl 를 못 읽음(NotImplementedError)

## 7. 시험 가짓수·근거 파일

- 이번 시험: (가) 고정 규칙 15개(A 0·B 0·C 15·D 0) + (나) 절차 80개 = **95가지**. 원장(state/ledger.json) 누적 264,845가지.
- 연구소가 이 후보들을 찾으려고 시험한 수(연구소 원장, Signal A 원장에는 더하지 않음): A 96,854·B 130,312·C 12,540·D 43,089.
- 가짜 신호 2,000번(같은 해 안 날짜 옮기기), 반증 시험 8개(s3/SPEC.md 4절 그대로). 참고 판정(2016~ 구간)·반증·겹침은 가짓수에 더하지 않았습니다.
- 미리 정한 목록: [x1/SPEC.md](SPEC.md) · 후보별 숫자: out/fixed.csv · 절차: out/wf.csv · 해마다 고른 규칙: out/wf_picks.csv · 반증: out/falsify.csv · 순위·출처: out/pool.csv · 겹침: out/overlap_watch.csv

투자 권유 아님
