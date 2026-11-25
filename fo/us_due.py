# 미국 일봉(야후)이 밀려 있으면 0(= 수집 필요), 제때 들어와 있으면 1 을 돌려준다(2026-11-26).
# 쓰는 곳: fo-dashboard 의 workflow_run(코스피 대시보드 갱신 직후) 계산 — 평소엔 미국 출처를 다시 두드리지 않지만,
#          06:37 예약 실행이 GitHub 에서 빠진 날(11/26 아침)처럼 미국 자료가 하루 밀려 있으면 그때만 미국 수집을 한다.
# 판정: fo/data/status.json 의 px(S&P500) 기준일 < '뉴욕 장 마감 + 30분이 지난 가장 늦은 미국 거래일' 이면 수집 필요.
import json, re, sys
from datetime import datetime, timedelta, timezone

US_HOL = {'2026-01-01', '2026-01-19', '2026-02-16', '2026-04-03', '2026-05-25', '2026-06-19', '2026-07-03', '2026-09-07', '2026-11-26', '2026-12-25',
          '2027-01-01', '2027-01-18', '2027-02-15', '2027-03-26', '2027-05-31', '2027-06-18', '2027-07-05', '2027-09-06', '2027-11-25', '2027-12-24'}


def ny_offset(d):  # 미국 서머타임: 3월 둘째 일요일 ~ 11월 첫째 일요일
    y = d.year
    mar = datetime(y, 3, 8); mar += timedelta(days=(6 - mar.weekday()) % 7)
    nov = datetime(y, 11, 1); nov += timedelta(days=(6 - nov.weekday()) % 7)
    return -4 if mar.date() <= d < nov.date() else -5


def expected(now):
    d = (now + timedelta(hours=-5)).date()
    for _ in range(12):
        s = d.isoformat()
        if d.weekday() < 5 and s not in US_HOL:
            close = datetime(d.year, d.month, d.day, 16, 0, tzinfo=timezone(timedelta(hours=ny_offset(d))))
            if close + timedelta(minutes=30) <= now:
                return s
        d -= timedelta(days=1)
    return None


def main():
    now = datetime.now(timezone.utc)
    try:
        px = json.load(open('fo/data/status.json', encoding='utf-8')).get('px', {})
        m = re.search(r'spx (\d{4}-\d{2}-\d{2})', px.get('note', ''))
        last = m.group(1) if m else px.get('last', '')
    except Exception:
        last = ''
    exp = expected(now)
    due = (not last) or (exp is not None and last < exp)
    print(f"미국 일봉 기준일 {last or '확인 불가'} · 와 있어야 할 날 {exp} → {'수집 필요' if due else '제때 들어와 있음'}")
    sys.exit(0 if due else 1)


if __name__ == '__main__':
    main()
