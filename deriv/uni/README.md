# 통합 예측 연구소 (갈래 U)

2026-11-23 사용자 요청: 대시보드 최적화 신호가 쓰지 않던 자료(선물·옵션·미국·해외)까지 **전부** 넣어 코스피 방향을 예측하고 매수·매도 신호를 다시 만든다. 정확도가 우선이다.

| 단계 | 파일 | 하는 일 |
|---|---|---|
| U1 자료 통합 | `uni_panel.py` | 연구소 일별 지표(deriv/scan 207개) + 옵션 벽 지표(A2) + 미국 지표(deriv/us) + 대시보드 자금 재료를 날짜별 한 표로. 묶음: 기존 재료·선물·옵션·미국 |
| U2 예측 | `uni_model.py` | 해마다 그 해 이전 자료로만 학습해 그 해를 예측(나무 모형·선형 모형·둘 평균). 대상 5개 × 자료 묶음 5개 |
| U2b 규칙 후보 | `uni_rules.py` | (실험 2, 2026-11-23) 대시보드 최적화 매수·매도 신호가 켜진 날에 선물·옵션·미국 지표 조건을 더 건다. 조건은 해마다 그 해 이전 자료로만 고른다. `uni_judge.py` 가 불러서 다른 후보와 같은 판정에 넣는다(워크플로는 그대로) |
| U3 판정 | `uni_judge.py` | 표본 밖 예측으로 매수·매도 신호와 보유·현금 전략을 만들고 `CRITERIA.md` 로 판정. 가짜 신호 시험, 기존 신호·묶음 규칙과 비교, 등록·전진 기록, 카카오톡 글 |
| 총괄 | `AGENT.md` | 예약 에이전트가 결과를 읽고 다음 실험을 정한다(기준은 못 바꿈) |

- 실행: GitHub `uni-lab` 워크플로(화~토 07:47 KST, 또는 `deriv/uni/trigger.txt` push). KRX 로그인 없음 — 저장소에 이미 모인 자료만 읽는다.
- 결과: `out/report.md`(사람이 읽는 요약) · `out/verdicts.csv` · `out/strategies.csv` · `out/ablation.csv` · `state/registry.json` · `out/rules_eval.csv`(규칙 후보 참고값) · `out/rules_pick.csv`(해마다 고른 조건)
- 다시 쓰는 기존 부품: deriv/scan/scan_data.py, deriv/lab/a02_features.py, deriv/us/us_features.py(결과 파일), main 의 pkg/reproduce.py·combo_track.py, deriv/lab/kakao_lab.py
- 넣지 못한 자료: 거래소 공매도(거래대금·잔고)는 2026-01 부터만 있어 검증에 쓸 수 없다. 금투협 대주(개인 공매도 잔고)는 들어 있다.
- 잠금: `CRITERIA.md` 와 `uni_judge.py` 의 `CRIT`·`RT`·`STRAT`·`FAMILY`, `state/registry.json` 의 등록일. 사용자만 바꾼다.
