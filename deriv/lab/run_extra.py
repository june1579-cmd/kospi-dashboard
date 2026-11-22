"""등록부(agents.json)의 새 에이전트를 차례로 돌린다(2026-11-22, 진화 에이전트용).
항목: {"file": "a12_xxx.py", "tracks": ["a", "b"], "timeout_min": 20, "enabled": true, "note": "..."}
보통 라운드에서는 한 에이전트가 실패해도 라운드를 막지 않는다(기록만). 시험(EVOLVE_GATE=1)에서는 하나라도 실패하면 실패로 끝낸다.
"""
import json
import os
import subprocess
import sys
import time

LAB = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, LAB)
import lab_common as L  # noqa: E402


def main():
    reg = json.load(open(os.path.join(LAB, 'agents.json'), encoding='utf-8')).get('extra', [])
    track = L.TRACK or 'a'; gate = os.environ.get('EVOLVE_GATE') == '1'; log = []; bad = 0
    for a in reg:
        if not a.get('enabled', True): continue
        if not gate and track not in a.get('tracks', ['a', 'b']): continue
        f = os.path.basename(a['file']); t0 = time.time()
        try:
            r = subprocess.run([sys.executable, os.path.join(LAB, f)], timeout=60 * a.get('timeout_min', 20), capture_output=True, text=True)
            rc, tail = r.returncode, (r.stdout + r.stderr)[-1500:]
        except subprocess.TimeoutExpired:
            rc, tail = 124, '시간 초과'
        log.append({'file': f, 'rc': rc, 'sec': round(time.time() - t0, 1), 'tail': tail}); bad += rc != 0
        print(f, 'rc', rc, flush=True)
    json.dump(log, open(os.path.join(L.out_dir('extra'), 'extra_log.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    sys.exit(1 if gate and bad else 0)


if __name__ == '__main__':
    main()
