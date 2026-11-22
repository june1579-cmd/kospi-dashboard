#!/usr/bin/env bash
# 진화 시험용 한 라운드(갈래 t, 결과는 저장소에 올리지 않음). 갈래 B 설정으로 A2~A7(기계학습은 한 조각)·새 에이전트·A8·A10 을 차례로 돌리고 단계별 결과를 steps.json 에 적는다.
set -u
export LAB_TRACK=t EVOLVE_GATE=1
cd "$(dirname "$0")/../../.."
python - <<'PY'
import json
c = json.load(open('deriv/lab/round_b.json', encoding='utf-8')); c['round'] = 1; c['note'] = '진화 시험'
json.dump(c, open('deriv/lab/round_t.json', 'w', encoding='utf-8'), ensure_ascii=False)
PY
rm -rf deriv/lab/out_t deriv/lab/state_t; mkdir -p deriv/lab/state_t
echo '{"trials_total": 0, "holdout_peeks": 0, "rounds": []}' > deriv/lab/state_t/ledger.json
echo '[' > steps.tmp; first=1
run() { local name="$1"; shift; local t0=$(date +%s); "$@" > "log_$name.txt" 2>&1; local rc=$?; local t1=$(date +%s)
  [ $first -eq 1 ] || echo ',' >> steps.tmp; first=0
  echo "{\"step\": \"$name\", \"rc\": $rc, \"sec\": $((t1 - t0))}" >> steps.tmp; echo "$name rc=$rc $((t1 - t0))s"; tail -3 "log_$name.txt"; }
run scan python deriv/scan/scan_data.py
run a02 python deriv/lab/a02_features.py
for A in a03_events a03_cause a04_flows a05_roll a06_rules; do run $A python deriv/lab/$A.py; done
A07_SHARD=0/3 run a07_ml python deriv/lab/a07_ml.py
run extra python deriv/lab/run_extra.py
python deriv/lab/a06c_consensus.py > log_a06c.txt 2>&1 || true
run a08 python deriv/lab/a08_validate.py
run a10 python deriv/lab/a10_redteam.py
run merge python deriv/lab/lab_merge.py
echo ']' >> steps.tmp; mv steps.tmp steps.json
exit 0
