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
        r = requests.post(f"{self.base}/oauth2/tokenP", json={
            "grant_type": "client_credentials", "appkey": self.key, "appsecret": self.secret}, timeout=15).json()
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


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--out", default="kis_probe"); a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
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
