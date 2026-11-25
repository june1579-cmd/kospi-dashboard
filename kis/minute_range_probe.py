"""
KIS 과거 분봉 '받을 수 있는 범위'만 재는 시험 (전체 수집 아님).
- 날짜를 1일·1주·1달 … 5년 전까지 찔러 보고, 받을 수 있는 가장 오래된 날을 이분 탐색으로 찾는다.
- 대상: 주식 과거분봉(삼성전자·SK하이닉스), 주식 당일분봉, 코스피 지수 분봉, 코스피200 선물 분봉
- 저장: 시세 원자료는 저장하지 않고 '날짜·건수·응답 코드'만 kis_probe/result.json 에 남긴다.
사용: python kis/minute_range_probe.py --out kis_probe
"""
import argparse, json, os, sys, time
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

SERVERS = {"real": "https://openapi.koreainvestment.com:9443",
           "mock": "https://openapivts.koreainvestment.com:29443"}
GAP = {"real": 0.12, "mock": 1.1}
OFFSETS = [1, 7, 30, 90, 180, 270, 330, 360, 380, 400, 450, 548, 730, 1095, 1825]
CALLS = 0


class K:
    def __init__(self, mode):
        P = f"KIS_{mode.upper()}_"
        self.mode, self.base = mode, SERVERS[mode]
        self.key, self.secret = os.environ.get(P + "APP_KEY"), os.environ.get(P + "APP_SECRET")
        self.token = None

    def ok(self):
        return bool(self.key and self.secret)

    def auth(self):
        try:
            r = requests.post(f"{self.base}/oauth2/tokenP", json={
                "grant_type": "client_credentials", "appkey": self.key, "appsecret": self.secret}, timeout=15).json()
        except Exception as e:      # 모의 서버는 운영시간 밖에 JSON 이 아닌 응답을 줄 때가 있음
            return False, repr(e)[:120]
        self.token = r.get("access_token")
        return self.token is not None, r.get("error_description") or r.get("msg1") or ""

    def get(self, path, tr, params):
        global CALLS
        for attempt in range(3):
            time.sleep(GAP[self.mode])
            CALLS += 1
            try:
                r = requests.get(self.base + path, timeout=20, params=params, headers={
                    "content-type": "application/json; charset=utf-8",
                    "authorization": f"Bearer {self.token}", "appkey": self.key,
                    "appsecret": self.secret, "tr_id": tr, "custtype": "P"}).json()
            except Exception as e:
                r = {"rt_cd": "E", "msg1": repr(e)[:120]}
            if r.get("msg_cd") == "EGW00201":       # 초당 한도 초과 → 쉬고 재시도
                time.sleep(1.5); continue
            return r
        return r


def rows_of(r):
    return r.get("output2") or []


def dates_in(rows, dkey="stck_bsop_date"):
    return sorted({x.get(dkey) for x in rows if x.get(dkey)})


def prev_weekday(d):
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


# ── 각 API의 '그 날짜 분봉 요청' 함수: (받은 건수, 실제 들어온 날짜들, 응답코드/메시지) ──
def stock_past(k, code, d, mkt="J"):
    r = k.get("/uapi/domestic-stock/v1/quotations/inquire-time-dailychartprice", "FHKST03010230", {
        "FID_COND_MRKT_DIV_CODE": mkt, "FID_INPUT_ISCD": code, "FID_INPUT_HOUR_1": "153000",
        "FID_INPUT_DATE_1": d.strftime("%Y%m%d"), "FID_PW_DATA_INCU_YN": "N", "FID_FAKE_TICK_INCU_YN": ""})
    rows = rows_of(r)
    return len(rows), dates_in(rows), f"{r.get('rt_cd')} {r.get('msg_cd','')} {r.get('msg1','')}".strip()


def fut_past(k, code, d):
    r = k.get("/uapi/domestic-futureoption/v1/quotations/inquire-time-fuopchartprice", "FHKIF03020200", {
        "FID_COND_MRKT_DIV_CODE": "F", "FID_INPUT_ISCD": code, "FID_HOUR_CLS_CODE": "60",
        "FID_PW_DATA_INCU_YN": "Y", "FID_FAKE_TICK_INCU_YN": "N",
        "FID_INPUT_DATE_1": d.strftime("%Y%m%d"), "FID_INPUT_HOUR_1": "154500"})
    rows = rows_of(r)
    return len(rows), dates_in(rows), f"{r.get('rt_cd')} {r.get('msg_cd','')} {r.get('msg1','')}".strip()


def hit(fn, d):
    """그 날(휴장이면 이전 평일 최대 4일)까지 시도해 '요청한 날짜와 같은 날'의 분봉이 왔는지"""
    tried = []
    for _ in range(4):
        d = prev_weekday(d)
        n, ds, msg = fn(d)
        want = d.strftime("%Y%m%d")
        tried.append({"date": want, "rows": n, "dates": ds[:3], "msg": msg})
        if n and want in ds:
            return True, d, tried
        if n and ds and ds[-1] < want:      # 요청보다 이전 날짜가 왔다 = 휴장일일 수 있음 → 하루 전으로
            d -= timedelta(days=1); continue
        if not n:
            d -= timedelta(days=1); continue
        break
    return False, d, tried


def find_range(fn, label, log):
    """OFFSETS 로 대략 찾고, 마지막 성공~첫 실패 사이를 이분 탐색"""
    today = date.today()
    last_ok, first_bad, points = None, None, []
    for off in OFFSETS:
        ok, d, tried = hit(fn, today - timedelta(days=off))
        points.append({"days_back": off, "ok": ok, "date": d.isoformat(), "tried": tried})
        print(f"  [{label}] {off:>5}일 전 {d} → {'O' if ok else 'X'}  {tried[-1]['msg'][:60]}")
        if ok:
            last_ok = d
        else:
            first_bad = d
            break
    if last_ok and first_bad:
        lo, hi = first_bad, last_ok           # lo: 실패, hi: 성공
        while (hi - lo).days > 3:
            mid = lo + (hi - lo) / 2
            ok, d, _ = hit(fn, mid)
            print(f"  [{label}] 경계 탐색 {mid} → {'O' if ok else 'X'}")
            if ok: hi = d
            else: lo = mid
        last_ok = hi
    log[label] = {"earliest_ok": last_ok.isoformat() if last_ok else None,
                  "first_fail_near": first_bad.isoformat() if first_bad else None,
                  "days_back": (today - last_ok).days if last_ok else None, "points": points}
    return log[label]


def one_day_bars(k, code, d, mkt="J"):
    """하루치 1분봉을 120건씩 거슬러 받아 몇 번 호출·몇 개 봉인지 (원자료는 버림)"""
    hh, total, calls, first, last = "153000", 0, 0, None, None
    while calls < 8:
        r = k.get("/uapi/domestic-stock/v1/quotations/inquire-time-dailychartprice", "FHKST03010230", {
            "FID_COND_MRKT_DIV_CODE": mkt, "FID_INPUT_ISCD": code, "FID_INPUT_HOUR_1": hh,
            "FID_INPUT_DATE_1": d.strftime("%Y%m%d"), "FID_PW_DATA_INCU_YN": "N", "FID_FAKE_TICK_INCU_YN": ""})
        calls += 1
        rows = [x for x in rows_of(r) if x.get("stck_bsop_date") == d.strftime("%Y%m%d")]
        if not rows: break
        total += len(rows)
        times = sorted(x["stck_cntg_hour"] for x in rows)
        first, last = times[0], (last or times[-1])
        if times[0] <= "090000": break
        t = datetime.strptime(times[0], "%H%M%S") - timedelta(minutes=1)
        hh = t.strftime("%H%M%S")
    return {"date": d.isoformat(), "market": mkt, "bars": total, "calls": calls, "first": first, "last": last}


def after_hours(k, code, d, mkt):
    """20:00 부터 거슬러 받아 15:30 이후(애프터마켓) 봉이 몇 개, 몇 시부터 몇 시까지 있는지"""
    hh, bars, calls, msg = "200000", {}, 0, ""
    while calls < 6:
        r = k.get("/uapi/domestic-stock/v1/quotations/inquire-time-dailychartprice", "FHKST03010230", {
            "FID_COND_MRKT_DIV_CODE": mkt, "FID_INPUT_ISCD": code, "FID_INPUT_HOUR_1": hh,
            "FID_INPUT_DATE_1": d.strftime("%Y%m%d"), "FID_PW_DATA_INCU_YN": "N", "FID_FAKE_TICK_INCU_YN": ""})
        calls += 1; msg = f"{r.get('rt_cd')} {r.get('msg1','')}".strip()
        rows = [x for x in rows_of(r) if x.get("stck_bsop_date") == d.strftime("%Y%m%d")]
        if not rows: break
        for x in rows: bars[x["stck_cntg_hour"]] = x.get("cntg_vol")
        first = min(x["stck_cntg_hour"] for x in rows)
        if first <= "153000": break
        hh = (datetime.strptime(first, "%H%M%S") - timedelta(minutes=1)).strftime("%H%M%S")
    aft = sorted(t for t in bars if t > "153000")
    vol = sum(int(bars[t] or 0) for t in aft)
    return {"code": code, "market": mkt, "after_bars": len(aft), "first": aft[0] if aft else None,
            "last": aft[-1] if aft else None, "after_vol": vol,
            "gap_1530_1600": len([t for t in aft if t < "160000"]), "calls": calls, "msg": msg}


def run_after(k, res, out):
    d = prev_weekday(date.today() - timedelta(days=1))
    C = res["checks"]; lines = []
    print(f"\n애프터마켓(15:30~20:00) 분봉 — {d}")
    for code in ["005930", "000660"]:
        for mkt in ["J", "UN", "NX"]:
            v = after_hours(k, code, d, mkt); C[f"after_{code}_{mkt}"] = v; print("  ", v)
            lines.append(f"{code}{mkt} {v['after_bars']}봉 {v['first'] or '-'}~{v['last'] or '-'}")
    res["api_calls"] = CALLS
    (out / "result_after.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "notify.txt").write_text(("[KIS 애프터마켓 분봉]\n" + "\n".join(lines))[:200], encoding="utf-8")
    return 0


def full_day(k, code, d, mkt):
    """20:00 부터 08:00 까지 거슬러 하루치 전부 → {시각: (시가,고가,저가,종가,거래량)}"""
    hh, bars, calls, msg = "200000", {}, 0, ""
    while calls < 9:
        r = k.get("/uapi/domestic-stock/v1/quotations/inquire-time-dailychartprice", "FHKST03010230", {
            "FID_COND_MRKT_DIV_CODE": mkt, "FID_INPUT_ISCD": code, "FID_INPUT_HOUR_1": hh,
            "FID_INPUT_DATE_1": d.strftime("%Y%m%d"), "FID_PW_DATA_INCU_YN": "N", "FID_FAKE_TICK_INCU_YN": ""})
        calls += 1; msg = f"{r.get('rt_cd')} {r.get('msg1','')}".strip()
        rows = [x for x in rows_of(r) if x.get("stck_bsop_date") == d.strftime("%Y%m%d")]
        if not rows: break
        for x in rows:
            bars[x["stck_cntg_hour"]] = tuple(x.get(f) for f in ("stck_oprc", "stck_hgpr", "stck_lwpr", "stck_prpr", "cntg_vol"))
        first = min(x["stck_cntg_hour"] for x in rows)
        if first <= "080000": break
        hh = (datetime.strptime(first, "%H%M%S") - timedelta(minutes=1)).strftime("%H%M%S")
    return bars, calls, msg


def span(bars, lo, hi):
    ts = sorted(t for t in bars if lo <= t < hi)
    return {"bars": len(ts), "first": ts[0] if ts else None, "last": ts[-1] if ts else None,
            "vol": sum(int(bars[t][4] or 0) for t in ts)}


def run_un(k, res, out):
    d = prev_weekday(date.today() - timedelta(days=1))
    C = res["checks"]; lines = []
    codes = {"005930": "삼성전자", "069500": "KODEX200(ETF)", "950130": "엑세스바이오",
             "033170": "시그네틱스", "001520": "동양", "900140": "엘브이엠씨"}
    print(f"\n통합 vs KRX vs NXT — {d}")
    for code, name in codes.items():
        got = {m: full_day(k, code, d, m) for m in ["J", "UN", "NX"]}
        row = {"name": name}
        for m, (bars, calls, msg) in got.items():
            row[m] = {"total": len(bars), "pre_0800_0900": span(bars, "080000", "090000"),
                      "regular_0900_1530": span(bars, "090000", "153100"),
                      "after_1530_2000": span(bars, "153100", "200100"), "calls": calls, "msg": msg}
        # 정규장 같은 시각 봉끼리 가격·거래량 비교 (통합 vs KRX)
        J, U = got["J"][0], got["UN"][0]
        common = [t for t in J if t in U and "090000" <= t <= "153000"]
        row["regular_close_diff_bars"] = sum(1 for t in common if J[t][3] != U[t][3])
        row["regular_high_low_diff_bars"] = sum(1 for t in common if (J[t][1], J[t][2]) != (U[t][1], U[t][2]))
        row["regular_common_bars"] = len(common)
        row["regular_only_in_J"] = len([t for t in J if "090000" <= t <= "153000" and t not in U])
        C[f"un_{code}"] = row
        print(f"  {name} {code}: " + " | ".join(
            f"{m} 전체{row[m]['total']} 장전{row[m]['pre_0800_0900']['bars']} 정규{row[m]['regular_0900_1530']['bars']} 장후{row[m]['after_1530_2000']['bars']}"
            for m in ["J", "UN", "NX"]) + f" | 정규장 종가 다른 봉 {row['regular_close_diff_bars']}/{len(common)}")
        lines.append(f"{name[:6]} J{row['J']['total']} UN{row['UN']['total']} NX{row['NX']['total']}")
    res["api_calls"] = CALLS
    (out / "result_un.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "notify.txt").write_text(("[KIS 통합 vs KRX]\n" + "\n".join(lines))[:200], encoding="utf-8")
    return 0


def run_rate(k, res, out):
    """초당 호출 한도 실측: 단계별 속도로 10초씩 과거분봉 조회를 병렬로 보내고 성공·초과(EGW00201) 비율을 잰다.
       한 단계에서 초과 비율이 30%를 넘으면 그 위 단계는 돌리지 않는다."""
    from concurrent.futures import ThreadPoolExecutor
    import threading
    levels = [3, 5, 8, 10, 13, 16, 20, 25, 30, 40]
    sess = requests.Session()
    hdr = {"content-type": "application/json; charset=utf-8", "authorization": f"Bearer {k.token}",
           "appkey": k.key, "appsecret": k.secret, "tr_id": "FHKST03010230", "custtype": "P"}
    days = [prev_weekday(date.today() - timedelta(days=i)) for i in range(1, 60)]
    lock = threading.Lock()

    def one(i):
        d = days[i % len(days)]
        t0 = time.time()
        try:
            r = sess.get(k.base + "/uapi/domestic-stock/v1/quotations/inquire-time-dailychartprice", timeout=20,
                         headers=hdr, params={"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": "005930",
                                              "FID_INPUT_HOUR_1": "153000", "FID_INPUT_DATE_1": d.strftime("%Y%m%d"),
                                              "FID_PW_DATA_INCU_YN": "N", "FID_FAKE_TICK_INCU_YN": ""}).json()
            code = "OK" if r.get("rt_cd") == "0" else (r.get("msg_cd") or "ERR")
        except Exception as e:
            code = "EXC"
        return code, time.time() - t0

    C = res["checks"]; rows = []; best = None
    with ThreadPoolExecutor(max_workers=64) as ex:
        for rps in levels:
            n, futs, start = rps * 10, [], time.time()
            for i in range(n):                         # 일정 간격으로 요청을 흘려보냄
                wait = start + i / rps - time.time()
                if wait > 0: time.sleep(wait)
                futs.append(ex.submit(one, i))
            got = [f.result() for f in futs]
            elapsed = time.time() - start
            cnt = {}
            for c, _ in got: cnt[c] = cnt.get(c, 0) + 1
            ok = cnt.get("OK", 0); over = cnt.get("EGW00201", 0)
            lat = sorted(l for _, l in got); p50 = lat[len(lat) // 2]
            row = {"target_rps": rps, "sent": n, "ok": ok, "over_EGW00201": over,
                   "other": {c: v for c, v in cnt.items() if c not in ("OK", "EGW00201")},
                   "ok_per_sec": round(ok / elapsed, 1), "latency_p50": round(p50, 3)}
            rows.append(row); print("  ", row)
            if over == 0 and ok == n: best = rps
            if (n - ok) / n > 0.3:
                print("   → 거절 30% 초과, 여기서 중단"); break
            time.sleep(5)
    C["rate"] = rows; C["max_clean_rps"] = best
    res["api_calls"] = sum(r["sent"] for r in rows)
    (out / "result_rate.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    msg = "[KIS 호출 한도 실측]\n" + "\n".join(
        f"{r['target_rps']}건/초: 성공{r['ok']}/{r['sent']} 초과{r['over_EGW00201']}" for r in rows) + f"\n오류없는 최고 {best}건/초"
    (out / "notify.txt").write_text(msg[:200], encoding="utf-8")
    print("\n" + msg)
    return 0


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--out", default="kis_probe")
    ap.add_argument("--only", default="", help="after = 애프터마켓 분봉만 시험")
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    if a.only in ("after", "un", "rate"):
        res = {"run_at": datetime.now().isoformat(timespec="seconds"), "checks": {}, "notes": []}
        k = K("real")
        ok, msg = k.auth() if k.ok() else (False, "실전 키 없음")
        if not ok:
            (out / "notify.txt").write_text(f"[KIS 애프터마켓 분봉] 토큰 실패 {msg}"[:200], encoding="utf-8"); return 1
        return {"after": run_after, "un": run_un, "rate": run_rate}[a.only](k, res, out)
    res = {"run_at": datetime.now().isoformat(timespec="seconds"), "checks": {}, "notes": []}

    real, mock = K("real"), K("mock")
    if not real.ok() and not mock.ok():
        res["notes"].append("KIS 키가 Secrets 에 없음")
        (out / "result.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        (out / "notify.txt").write_text("[KIS 분봉 범위] 키 없음 — Secrets 6개 등록 필요", encoding="utf-8")
        print("키 없음"); return 1

    k = real if real.ok() else mock
    ok, msg = k.auth()
    res["server"] = k.mode
    if not ok:
        res["notes"].append(f"토큰 실패: {msg}")
        (out / "result.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        (out / "notify.txt").write_text(f"[KIS 분봉 범위] 토큰 실패 {msg}"[:200], encoding="utf-8")
        return 1
    print(f"서버: {k.mode}")

    C = res["checks"]
    print("\n1) 주식 과거분봉 (삼성전자 005930, KRX)")
    find_range(lambda d: stock_past(k, "005930", d), "주식_005930", C)
    print("\n2) 주식 과거분봉 (SK하이닉스 000660, KRX)")
    find_range(lambda d: stock_past(k, "000660", d), "주식_000660", C)

    print("\n3) 하루치 1분봉 받는 데 필요한 호출 수 (어제 기준, KRX / 통합)")
    y = prev_weekday(date.today() - timedelta(days=1))
    C["하루치_KRX"] = one_day_bars(k, "005930", y, "J"); print("  ", C["하루치_KRX"])
    C["하루치_통합UN"] = one_day_bars(k, "005930", y, "UN"); print("  ", C["하루치_통합UN"])

    print("\n4) 주식 당일분봉 (FHKST03010200)")
    r = k.get("/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice", "FHKST03010200", {
        "FID_ETC_CLS_CODE": "", "FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": "005930",
        "FID_INPUT_HOUR_1": "153000", "FID_PW_DATA_INCU_YN": "Y"})
    rows = rows_of(r)
    C["주식_당일분봉"] = {"rows": len(rows), "dates": dates_in(rows), "msg": f"{r.get('rt_cd')} {r.get('msg1','')}"}
    print("  ", C["주식_당일분봉"])

    print("\n5) 코스피 지수 분봉 (FHKUP03500200)")
    r = k.get("/uapi/domestic-stock/v1/quotations/inquire-time-indexchartprice", "FHKUP03500200", {
        "FID_COND_MRKT_DIV_CODE": "U", "FID_ETC_CLS_CODE": "0", "FID_INPUT_ISCD": "0001",
        "FID_INPUT_HOUR_1": "60", "FID_PW_DATA_INCU_YN": "Y"})
    rows = rows_of(r)
    C["지수_분봉"] = {"rows": len(rows), "dates": dates_in(rows), "msg": f"{r.get('rt_cd')} {r.get('msg1','')}",
                    "fields": list(rows[0].keys())[:12] if rows else []}
    print("  ", C["지수_분봉"])

    if k.mode == "real":
        print("\n6) 코스피200 선물 분봉 (A01612 = 26년 12월물)")
        find_range(lambda d: fut_past(k, "A01612", d), "선물_A01612", C)
        print("\n7) 만기 지난 선물 (A01609 = 26년 9월물)")
        n, ds, msg = fut_past(k, "A01609", date(2026, 9, 1))
        C["선물_만기물_A01609"] = {"rows": n, "dates": ds[:3], "msg": msg}; print("  ", C["선물_만기물_A01609"])
    else:
        res["notes"].append("실전 키가 없어 선물 분봉은 건너뜀")

    if mock.ok() and k.mode == "real":
        print("\n8) 모의 서버에서도 과거분봉이 나오는지")
        ok, msg = mock.auth()
        if ok:
            n, ds, msg = stock_past(mock, "005930", y)
            C["모의서버_과거분봉"] = {"rows": n, "dates": ds[:3], "msg": msg}
        else:
            C["모의서버_과거분봉"] = {"msg": f"토큰 실패 {msg}"}
        print("  ", C["모의서버_과거분봉"])

    res["api_calls"] = CALLS
    (out / "result.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")

    def e(lbl):
        v = C.get(lbl) or {}
        return f"{v.get('earliest_ok')}({v.get('days_back')}일)" if v.get("earliest_ok") else "X"
    msg = (f"[KIS 분봉 범위]\n주식 {e('주식_005930')}\n선물 {e('선물_A01612')}\n"
           f"하루 {C['하루치_KRX'].get('bars')}봉/{C['하루치_KRX'].get('calls')}회\n"
           f"지수분봉 {C['지수_분봉']['rows']}건 / 호출 {CALLS}회")
    (out / "notify.txt").write_text(msg[:200], encoding="utf-8")
    print("\n" + msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
