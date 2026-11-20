"""오래된 라운드 결과 줄이기(저장소 크기 관리, 2026-11-20 사용자 승인).

최근 KEEP 라운드(기본 10)는 그대로 두고, 그 전 라운드는 보고·요약 파일만 남긴다(.md, status.json, leaderboard.csv, verdicts.csv, redteam.csv, cause_summary.json).
"""
import os
import re
import sys

LAB = os.path.dirname(os.path.abspath(__file__))
_T = os.environ.get('LAB_TRACK', '').strip().lower()
OUT = os.path.join(LAB, 'out' + (f'_{_T}' if _T else ''))
KEEP = int(sys.argv[1]) if len(sys.argv) > 1 else 10
KEEP_NAMES = {'status.json', 'leaderboard.csv', 'verdicts.csv', 'redteam.csv', 'cause_summary.json'}


def main():
    rounds = sorted(d for d in os.listdir(OUT) if re.fullmatch(r'round_\d{3}', d))
    gone = 0
    for d in (rounds[:-KEEP] if len(rounds) > KEEP else []):
        for root, _, files in os.walk(os.path.join(OUT, d)):
            for f in files:
                if f in KEEP_NAMES or f.endswith('.md'): continue
                os.remove(os.path.join(root, f)); gone += 1
    print('라운드', len(rounds), '중 앞', max(0, len(rounds) - KEEP), '개 줄임 · 지운 파일', gone)


if __name__ == '__main__':
    main()
