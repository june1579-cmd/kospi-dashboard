# Signal A 줄기 코드 약속 (t1~t6 공통)

줄기 코드를 쓰는 사람(에이전트)이 지킬 약속이다. AGENT.md·PLAN.md·CRITERIA.md 가 위에 있고, 이 문서는 그 아래 세부다.

## 1. 파일
```
deriv/signal_a/tN/SPEC.md    미리 정한 시험 목록(가족·격자·가짓수·고르는 절차·'안 넣은 것'). 코드보다 먼저 쓴다. 돌린 뒤 고치지 않는다.
deriv/signal_a/tN/run.py     계산. 아래 4절의 함수·명령을 갖춘다.
deriv/signal_a/tN/out/       결과(파이프라인이 채움): parts/ cands.pkl meta.json tables/*.csv summary.md
```
고치는 곳은 자기 줄기 폴더(tN/)뿐. sa_common.py·sa_judge.py·다른 줄기·저장소의 다른 파일은 고치지 않는다(읽기·불러 쓰기만).
git commit·push 는 하지 않는다(총괄이 한다).

## 2. 자료·시각 규칙
- `import sa_common as C; D = C.Data()` 로만 자료를 읽는다. D.X(지표 434개), D.K(코스피 지수 시고저종), D.F(코스피200 선물, 참고), D.wide·D.walls(옵션 벽), D.td, D.year, D.groups.
  원자료가 꼭 필요하면 `C.raw_dir('deriv')`·`C.raw_dir('main')`. 저장소의 다른 자료 파일(deriv/data 등)이나 인터넷은 읽지 않는다.
- t일 지표 = t일 장 마감 뒤 아는 값. 매수는 다음 거래일 시가, 매도는 보유 h 일째 종가, 코스피 지수. 옵션 거래 없음. 수익 합계는 단순 합.
- 고르기(조건·문턱·모형·규칙 선택)는 **해마다 그 해 이전 자료로만**: `C.wf_splits()` = 2016~2026. 학습·고르기에는 청산일이 그 해 1월 1일 전인 거래만.
  지표를 자리(분위)로 바꿀 때도 그날까지의 지난 자료만(rolling·expanding) 쓴다. 전체 기간 분위·평균·표준편차를 쓰면 미래 자료다.
- 성적 구간: 2010-01-01 ~ 2026-11-20. 앞 = 2010~2023, 뒤 = 2024~.

## 3. 결과 꼴 — `C.save_result(track, cands, meta)`
후보 하나 = `dict(id, family, desc, direction, hold, kind, trades)` (+ 선택 `wf_of`, `params`)
- `kind='fixed'`: 전체 기간에 규칙을 고정한 신호(결과를 보고 고른 것). CRITERIA 1절 숫자만 본다.
- `kind='wf'`: 해마다 그 전 자료로 고른 절차가 그 해에 낸 신호를 이어 붙인 것(2016~2026). CRITERIA 3절(다음 해 성적)을 본다.
- `trades` = DataFrame[signal, exit]. **솎지 않은 모든 신호**를 넣는다(독립 거래 솎기는 판정이 한다). signal = 신호를 아는 날(하루 늦춤이면 늦춘 날), exit = 매도일.
  보유일 없는 채점(±k% 먼저 닿기)은 `hit`(0/1) 칸을 같이 넣고 exit = 닿은 날.
  **hit 칸을 넣는 후보는 `base_y` 도 꼭 넘긴다**: 거래일마다 '그 날이 신호일이었다면 같은 채점 방식으로 맞았나'(1/0/nan, D.td 순서의 Series 나 길이 D.n 배열, 후보 방향 기준).
  판정이 '같은 해 아무 날'과 가짜 신호를 이 배열로 잰다(없으면 h 일째 종가 수익 부호로 재서 채점 방식이 어긋난다).
- `desc` 는 쉬운 한국어 한 줄(규칙·문턱·보유일이 다 드러나게). `id` 는 줄기 안에서 유일, 영문·숫자·밑줄.
- 넘기는 후보 수: fixed 는 전체 기간 성적 상위 200개 이내(+ 따로 보라고 지시된 것), wf 는 SPEC 에 적은 절차 전부.
- `meta` = dict(n_tested=시험한 가짓수 합계, families={가족: 가짓수}, m_fixed=fixed 후보를 고른 모집단 크기, m_wf=wf 절차 수,
  not_included=[SPEC '안 넣은 것' 을 한 줄씩], parts_failed=[못 읽은 조각 번호], notes=[보고서에 적을 말], tables=[out/tables 의 표 파일])
- 그 줄기에서 꼭 내야 하는 표(예: 확률 구간별 실제 적중)는 out/tables/*.csv 와 out/summary.md(쉬운 말, 표 위주)로 쓴다. 판정이 summary.md 를 보고서에 붙인다.

## 4. run.py 가 갖출 것
```python
def n_parts(vol=False): ...                      # 조각 수(1~20). 한 조각은 GitHub 실행기(4코어·16GB)에서 40분 안에 끝나게.
def run_part(i, n, vol=False, quick=False): ...  # i=1..n. 돌려준 것을 C.save_part 로 저장(pickle 가능, 작게)
def merge(parts, vol=False, quick=False): ...    # parts[i-1] 이 None 이면 그 조각 실패 → meta['parts_failed'] 에 적고 나머지로 계속. (cands, meta) 반환
```
명령: `python run.py --nparts` (조각 수만 출력) · `python run.py --part i/n` · `python run.py --merge` · `--quick`(자료 일부·가족 일부로 1분 안, 시험용).
`C.parse_part()`·`C.save_part()`·`C.load_parts()`·`C.save_result()` 를 쓴다. 무작위는 씨앗 고정(C.SEED). joblib 로 4코어를 쓴다.
`vol=True` 는 T4(변동폭 맞춤)가 부르는 같은 가족의 변동폭 맞춤판이다(t1·t2·t3 만): 가족·가짓수는 그대로 두고 문턱만 '그때 변동폭'에 맞춘다
(거리는 %가 아니라 σ 단위, 등락·크기 문턱은 직전 60일 일간 표준편차의 배수, ±k% 닿기는 ±kσ√기간). 새 가족을 늘리지 않는다.

## 5. 미리 정하고 돌린다
- SPEC.md 에 가족·격자·가짓수·고르는 절차·넘길 wf 절차 목록을 먼저 적고 run.py 는 그대로 구현한다.
- **전체 자료로 돌려 결과를 본 뒤 SPEC 을 고치지 않는다.** 이 세션에서는 문법 확인과 `--quick`(1분 이내) 시험만 한다. 성적 숫자를 보고 격자를 바꾸지 않는다.
- 더 해 볼 만한 방향은 SPEC.md 의 '안 넣은 것' 칸에 적는다(→ meta.not_included → '아쉬운 줄기' 보고).
- 가짓수는 정직하게 센다: 방향·보유일·늦춤·문턱이 다르면 다른 가짓수다.

## 6. 판정이 하는 일(줄기 코드가 다시 할 필요 없음)
sa_judge.py 가 후보마다: 독립 거래 솎기, 전체·앞·뒤 적중(CRITERIA 1절 통과·관찰), 같은 해 아무 날 적중과의 차이·독립 30건(3절 1번),
같은 해 안 날짜 옮기기 가짜 2,000번 × 가짓수 보정(3절 2번), 2026년 넣고 빼기·큰 변동 해 2011·2020·2026(3절 3번), 원장 기록, 보고서(tN/report.md), 아쉬운 줄기 가리기.
