# 한국투자증권(KIS) 실전 키로 시세·투자자 동향을 받는 작은 도구(2026-11-26).
# 키는 GitHub Secrets(KIS_REAL_APP_KEY·KIS_REAL_APP_SECRET)에서만 읽고, 로그·파일에 남기지 않는다.
import os, time, json
from datetime import datetime, date, timedelta
import requests

BASE = "https://openapi.koreainvestment.com:9443"


class KIS:
    def __init__(self, gap=0.35):
        self.key = os.environ.get("KIS_REAL_APP_KEY"); self.secret = os.environ.get("KIS_REAL_APP_SECRET")
        self.gap = gap; self.tok = None; self.s = requests.Session(); self.calls = 0; self.errors = 0; self._last = 0.0

    def ok(self):
        return bool(self.key and self.secret)

    def token(self):
        if self.tok: return self.tok
        for _ in range(6):                       # 토큰은 1분에 1번만 발급 — 거절되면 65초 쉬고 다시
            try:
                r = self.s.post(BASE + "/oauth2/tokenP", timeout=20, json={"grant_type": "client_credentials", "appkey": self.key, "appsecret": self.secret}).json()
            except Exception as e:
                r = {"error_description": repr(e)[:80]}
            if r.get("access_token"):
                self.tok = r["access_token"]; return self.tok
            print("토큰 발급 대기:", str(r.get("error_code", "")), str(r.get("error_description", ""))[:60], flush=True); time.sleep(65)
        raise RuntimeError("KIS 토큰 발급 실패")

    def get(self, path, tr, params, tries=4):
        r = {}
        for _ in range(tries):
            wait = self.gap - (time.time() - self._last)
            if wait > 0: time.sleep(wait)
            self._last = time.time(); self.calls += 1
            try:
                r = self.s.get(BASE + path, timeout=15, params=params, headers={
                    "content-type": "application/json; charset=utf-8", "authorization": f"Bearer {self.token()}",
                    "appkey": self.key, "appsecret": self.secret, "tr_id": tr, "custtype": "P"}).json()
            except Exception as e:
                r = {"rt_cd": "E", "msg1": repr(e)[:80]}
            if r.get("msg_cd") == "EGW00201":    # 초당 한도 초과
                self.errors += 1; time.sleep(1.2); continue
            if r.get("msg_cd") in ("EGW00123", "EGW00121"):   # 토큰 만료·무효 → 새로 발급
                self.tok = None; time.sleep(1); continue
            if r.get("rt_cd") == "E":
                self.errors += 1; time.sleep(2); continue
            return r
        return r


def num(v):
    try: return float(str(v).replace(",", ""))
    except Exception: return None


def pick(d, *ends):
    """응답 dict 에서 이름이 주어진 꼬리로 끝나는 첫 값(숫자)"""
    if not isinstance(d, dict): return None
    for e in ends:
        for k, v in d.items():
            if k.endswith(e):
                x = num(v)
                if x is not None: return x
    return None


def second_thursday(y, m):
    d = date(y, m, 1); d += timedelta(days=(3 - d.weekday()) % 7); return d + timedelta(days=7)


def front_code(today=None):
    """코스피200 선물 최근월물 코드(A01 + 연도 끝자리 + 월). 분기월(3·6·9·12) 둘째 목요일 만기 다음 날부터 다음 분기물"""
    t = today or date.today(); y, m = t.year, t.month
    q = ((m - 1) // 3 + 1) * 3
    if t > second_thursday(y, q):
        q += 3
        if q > 12: q -= 12; y += 1
    return f"A01{y % 10}{q:02d}", f"{y}{q:02d}"


def index_now(k, iscd="2001"):
    """코스피200(2001) 지수: 현재·시가·고가·저가·전일 종가"""
    r = k.get("/uapi/domestic-stock/v1/quotations/inquire-index-price", "FHPUP02100000", {"FID_COND_MRKT_DIV_CODE": "U", "FID_INPUT_ISCD": iscd})
    o = r.get("output") or {}
    if isinstance(o, list): o = o[0] if o else {}
    cur = pick(o, "nmix_prpr"); chg = pick(o, "nmix_prdy_vrss")
    return {"ok": cur is not None, "cur": cur, "open": pick(o, "nmix_oprc"), "high": pick(o, "nmix_hgpr"), "low": pick(o, "nmix_lwpr"),
            "prev": (cur - chg) if (cur is not None and chg is not None) else None, "msg": f"{r.get('rt_cd')} {r.get('msg1', '')}"[:60]}


def fut_now(k, code):
    r = k.get("/uapi/domestic-futureoption/v1/quotations/inquire-price", "FHMIF10000000", {"FID_COND_MRKT_DIV_CODE": "F", "FID_INPUT_ISCD": code})
    o = r.get("output1") or r.get("output") or {}
    if isinstance(o, list): o = o[0] if o else {}
    cur = pick(o, "futs_prpr", "_prpr")
    return {"ok": cur is not None, "cur": cur, "open": pick(o, "futs_oprc", "_oprc"), "high": pick(o, "futs_hgpr", "_hgpr"), "low": pick(o, "futs_lwpr", "_lwpr"),
            "prev": pick(o, "futs_prdy_clpr", "prdy_clpr"), "msg": f"{r.get('rt_cd')} {r.get('msg1', '')}"[:60], "fields": list(o.keys())[:60]}


def fut_bars_today(k, code, d=None, mkt="F"):
    """선물 1분봉(당일 08:45~): 시가·고가·저가를 분봉에서 직접 계산(예비)"""
    d = d or date.today(); hh = "235959"; seen = {}
    for _ in range(6):
        r = k.get("/uapi/domestic-futureoption/v1/quotations/inquire-time-fuopchartprice", "FHKIF03020200", {
            "FID_COND_MRKT_DIV_CODE": mkt, "FID_INPUT_ISCD": code, "FID_HOUR_CLS_CODE": "60", "FID_PW_DATA_INCU_YN": "Y",
            "FID_FAKE_TICK_INCU_YN": "N", "FID_INPUT_DATE_1": d.strftime("%Y%m%d"), "FID_INPUT_HOUR_1": hh})
        rows = [x for x in (r.get("output2") or []) if x.get("stck_bsop_date") == d.strftime("%Y%m%d")]
        if not rows: break
        new = 0
        for x in rows:
            t = x.get("stck_cntg_hour")
            if t not in seen: seen[t] = x; new += 1
        if not new: break
        t0 = min(x.get("stck_cntg_hour") for x in rows)
        if t0 <= "084500": break
        hh = (datetime.strptime(t0, "%H%M%S") - timedelta(minutes=1)).strftime("%H%M%S")
    if not seen: return {"ok": False}
    bars = [seen[t] for t in sorted(seen)]
    g = lambda x, *e: pick(x, *e)
    return {"ok": True, "open": g(bars[0], "oprc"), "high": max(g(x, "hgpr") for x in bars), "low": min(g(x, "lwpr") for x in bars), "cur": g(bars[-1], "prpr"),
            "from": sorted(seen)[0], "to": sorted(seen)[-1], "n": len(bars)}


# 시장별 투자자 동향(시세) — 코스피200 선물을 가리키는 코드 후보(첫 실행 때 맞는 것을 고른다)
FLOW_CANDS = [("K2I", "F001"), ("K2I", "F"), ("999", "F001"), ("0001", "F001"), ("K2I", "S001")]
FLOW_KEYS = ["frgn_ntby_qty", "frgn_ntby_tr_pbmn", "frgn_shnu_vol", "frgn_seln_vol", "prsn_ntby_qty", "prsn_ntby_tr_pbmn", "orgn_ntby_qty", "orgn_ntby_tr_pbmn",
             "scrt_ntby_qty", "ivtr_ntby_qty", "pe_fund_ntby_vol", "bank_ntby_qty", "insu_ntby_qty", "mrbn_ntby_qty", "fund_ntby_qty", "etc_orgt_ntby_vol", "etc_corp_ntby_vol"]


def flow_now(k, iscd, iscd2):
    r = k.get("/uapi/domestic-stock/v1/quotations/inquire-investor-time-by-market", "FHPTJ04030000", {"FID_INPUT_ISCD": iscd, "FID_INPUT_ISCD_2": iscd2})
    o = r.get("output") or {}
    if isinstance(o, list): o = o[0] if o else {}
    out = {kk: num(o.get(kk)) for kk in FLOW_KEYS if kk in o}
    out["_msg"] = f"{r.get('rt_cd')} {r.get('msg1', '')}"[:60]; out["_n"] = len(o)
    return out
