# 장중 코스피200 선물 투자자별(외국인·개인·기관) 누적 순매수 + 선물·현물 시세를 가능한 짧은 간격(기본 5초)으로 쌓는다(2026-11-26).
# 하루를 오전(08:40~12:10)·오후(12:10~15:50) 두 작업으로 나눈다(GitHub 작업 한 번 최대 6시간).
# 09:06~09:12 은 매일 09:07 KIS 호출 한도 재측정과 겹치지 않게 쉰다. 오전 작업은 09:05:20 에(09:10 전, 09:07 한도 재측정 전) '09:10판 장중 도달 확률'을 계산해 main 에 올린다.
# 저장: intraday-flow 가지의 flow/YYYY-MM/YYYY-MM-DD.csv (30분마다·끝날 때 커밋). 키 값은 어디에도 남기지 않는다.
import argparse, csv, json, os, subprocess, sys, time
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from reach.kis import KIS, front_code, index_now, fut_now, flow_now, FLOW_CANDS, FLOW_KEYS

KST = ZoneInfo("Asia/Seoul")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
now = lambda: datetime.now(KST)


def hm(s):
    h, m = s.split(":"); return now().replace(hour=int(h), minute=int(m), second=0, microsecond=0)


def trading_day(d):
    try: hol = set(json.load(open(os.path.join(ROOT, "pkg/holidays_kr.json"), encoding="utf-8"))["holidays"])
    except Exception: hol = set()
    return d.weekday() < 5 and d.isoformat() not in hol


def git(cwd, *a):
    return subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True)


def commit(cwd, paths, msg, branch):
    git(cwd, "add", "-A", *paths)
    if git(cwd, "diff", "--cached", "--quiet").returncode == 0: return
    git(cwd, "commit", "-q", "-m", msg)
    for _ in range(4):
        if git(cwd, "pull", "-q", "--rebase", "origin", branch).returncode == 0 and git(cwd, "push", "-q", "origin", f"HEAD:{branch}").returncode == 0: return
        time.sleep(8)
    print("커밋 올리기 실패:", msg, flush=True)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--part", default="auto"); ap.add_argument("--out", default="_flow"); ap.add_argument("--interval", type=float, default=5)
    ap.add_argument("--test-min", type=float, default=3); ap.add_argument("--post-now", action="store_true"); a = ap.parse_args()
    t = now(); part = a.part
    if part == "auto": part = "am" if t.hour < 11 or (t.hour == 11 and t.minute < 50) else "pm"
    if part != "test" and not trading_day(t.date()):
        print("휴장일 — 수집 안 함"); return
    k = KIS(gap=0.45)
    if not k.ok(): print("KIS 키 없음"); return
    code, ym = front_code(t.date())
    win = {"am": ("08:40", "12:10"), "pm": ("12:10", "15:50"), "test": (t.strftime("%H:%M"), (t + timedelta(minutes=a.test_min)).strftime("%H:%M"))}[part]
    start, end = hm(win[0]), hm(win[1])
    if part == "test": end = t + timedelta(minutes=a.test_min)
    if now() >= end: print("시간 지남 — 할 일 없음", part); return
    while now() < start - timedelta(seconds=20): time.sleep(5)
    # 투자자 동향 코드 고르기: 후보를 모두 불러 보고 기록
    probe = {f"{c1}/{c2}": flow_now(k, c1, c2) for c1, c2 in FLOW_CANDS + [("999", "S001")]}
    for kk, v in probe.items(): print("후보", kk, {x: v.get(x) for x in ("_msg", "_n", "frgn_ntby_qty", "frgn_ntby_tr_pbmn", "prsn_ntby_qty")}, flush=True)
    stock = probe.get("999/S001", {}).get("frgn_ntby_qty")
    cand = [kk for kk, v in probe.items() if kk != "999/S001" and v.get("frgn_ntby_qty") is not None and v.get("frgn_ntby_qty") != stock]
    flow_code = tuple(cand[0].split("/")) if cand else None
    print("선물 투자자 동향 코드:", flow_code or "못 찾음(시세만 수집)", "· 최근월물", code, flush=True)
    day = now().date().isoformat(); os.makedirs(os.path.join(a.out, "flow", day[:7]), exist_ok=True)
    path = os.path.join(a.out, "flow", day[:7], f"{day}.csv")
    cols = ["ts", "part", "fut_code", "fut", "fut_open", "fut_high", "fut_low", "k200", "k200_open", "k200_high", "k200_low"] + [f"f_{x}" for x in FLOW_KEYS]
    new = not os.path.exists(path)
    fh = open(path, "a", newline="", encoding="utf-8"); w = csv.writer(fh)
    if new: w.writerow(cols)
    meta_p = os.path.join(a.out, "flow", "meta.json")
    try: meta = json.load(open(meta_p, encoding="utf-8"))
    except Exception: meta = {}
    meta[day + "_" + part] = {"flow_code": "/".join(flow_code) if flow_code else None, "fut_code": code, "probe": {kk: {x: v.get(x) for x in ("_msg", "_n", "frgn_ntby_qty")} for kk, v in probe.items()}}
    post_done = not (part == "am" or a.post_now); last_commit = time.time(); n = 0; last_fut = last_idx = None
    while now() < end:
        tick = time.time(); tn = now()
        if tn.replace(hour=9, minute=6, second=0) <= tn < tn.replace(hour=9, minute=12, second=0) and part != "test":
            time.sleep(5); continue                                     # KIS 호출 한도 재측정(09:07)과 겹치지 않게
        f = fut_now(k, code); i = index_now(k)
        fl = flow_now(k, *flow_code) if flow_code else {}
        if f.get("ok"): last_fut = f
        if i.get("ok"): last_idx = i
        w.writerow([tn.strftime("%H:%M:%S"), part, code, f.get("cur"), f.get("open"), f.get("high"), f.get("low"), i.get("cur"), i.get("open"), i.get("high"), i.get("low")] + [fl.get(x) for x in FLOW_KEYS]); n += 1
        if n == 1: print("첫 행:", {"fut": f.get("cur"), "fut_open": f.get("open"), "k200": i.get("cur"), "k200_open": i.get("open"), "frgn": fl.get("frgn_ntby_qty"), "fut_msg": f.get("msg"), "idx_msg": i.get("msg"), "fut_fields": f.get("fields", [])[:25]}, flush=True)
        if not post_done and (tn >= tn.replace(hour=9, minute=5, second=20) or a.post_now) and n >= 2:   # 09:10 전에 나오도록(09:07 호출 한도 재측정 전)
            fh.flush()
            try:
                git(ROOT, "pull", "-q", "--rebase", "origin", "main")      # 08:30판(pre.json)·학습값을 최신으로
                from reach import live
                live.run_post(idx=last_idx, fut=last_fut, fut_code=code, asof=tn.strftime("%Y-%m-%d %H:%M"))
                commit(ROOT, ["docs/reach/data"], f"장중 도달 확률 09:10판 {tn:%Y-%m-%d %H:%M}", "main")
            except Exception as e:
                print("09:10판 계산 실패:", repr(e)[:200], flush=True)
            post_done = True
        if time.time() - last_commit > 1800:
            fh.flush(); json.dump(meta, open(meta_p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            commit(a.out, ["flow"], f"장중 선물 수급 {tn:%Y-%m-%d %H:%M}", "intraday-flow"); last_commit = time.time()
        time.sleep(max(0.0, a.interval - (time.time() - tick)))
    fh.close()
    meta[day + "_" + part].update(rows=n, calls=k.calls, errors=k.errors)
    json.dump(meta, open(meta_p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"끝: {n}행 · 호출 {k.calls} · 오류 {k.errors}", flush=True)
    if part != "test": commit(a.out, ["flow"], f"장중 선물 수급 {now():%Y-%m-%d %H:%M} ({part})", "intraday-flow")


if __name__ == "__main__":
    main()
