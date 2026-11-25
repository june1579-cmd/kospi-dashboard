# -*- coding: utf-8 -*-
"""
한국투자증권(KIS) 과거 1분봉 수집기 — 사용자 PC(C:\\Users\\Stan\\Desktop\\stocks)에서 돈다.

받는 것 (가장 오래된 날짜부터)
  1) 코스피200 선물 최근월물 주간(08:45~15:45)·야간(18:00~06:00). 만기 14일 전부터는 다음 월물도.
  2) 주식·ETF 전 종목 KRX 1분봉(09:00~20:00) + NXT 거래 종목은 통합 1분봉(08:00~20:00).
저장: data/ 아래 Parquet. 진행 기록: state/progress.db (받은 종목·날짜는 다시 받지 않음).
안전장치: 이어 받기, 자동 재시도, 속도 자동 조절(거절되면 낮춤), 09:05~09:15 휴식(매일 한도 측정과 겹치지 않게),
          토큰 파일 재사용, 하나만 실행(잠금 파일), state/STOP 파일이 있으면 멈춤.
알림: GitHub 워크플로(pc-notify)를 불러 카카오톡으로 — 시작·매일 06:50 진행·30분 이상 끊김·오류 반복·완료.

사용: python collector.py            (수집)
      python collector.py --check    (설정·연결 점검만)
      python collector.py --selftest (짧은 시험: 선물 2일 + 주식 3종목 1일, 저장은 selftest/ 에)
"""
import argparse, io, json, logging, logging.handlers, os, random, sqlite3, subprocess, sys, threading, time, zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

BASE = Path(__file__).resolve().parent
DATA, STATE, LOGS = BASE / "data", BASE / "state", BASE / "logs"
for p in (DATA, STATE, LOGS):
    p.mkdir(exist_ok=True)

REAL = "https://openapi.koreainvestment.com:9443"
Q = "/uapi/domestic-stock/v1/quotations/"
FQ = "/uapi/domestic-futureoption/v1/quotations/"
REPO = "june1579-cmd/kospi-dashboard"
TASK_NAME = "KIS_Minute_Collector"
WORKERS = 8
PAUSE = ("090500", "091500")          # 매일 한도 측정(09:07) 동안 쉼

# 코스피200 선물 월물 코드와 만기일(둘째 목요일). 25년 12월물까지 옛 코드, 26년 3월물부터 새 코드.
CONTRACTS = [("101W12", date(2025, 12, 11)), ("A01603", date(2026, 3, 12)), ("A01606", date(2026, 6, 11)),
             ("A01609", date(2026, 9, 10)), ("A01612", date(2026, 12, 10)), ("A01703", date(2027, 3, 11)),
             ("A01706", date(2027, 6, 10)), ("A01709", date(2027, 9, 9)), ("A01712", date(2027, 12, 9))]

log = logging.getLogger("kis")


def setup_logging(console=True):
    log.setLevel(logging.INFO)
    fh = logging.handlers.RotatingFileHandler(LOGS / "collector.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(fh)
    if console:
        sh = logging.StreamHandler(sys.stdout); sh.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        log.addHandler(sh)


def load_env():
    env = dict(os.environ)
    f = BASE / ".env"
    if f.exists():
        for line in f.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1); v = v.strip().strip('"').strip("'")
                if v: env[k.strip()] = v
    return env


# ───────────────────────── 알림 (GitHub → 카카오톡) ─────────────────────────
class Notifier:
    def __init__(self, token):
        self.token = token

    def send(self, kind, message):
        message = message[:190]
        log.info("알림[%s] %s", kind, message.replace("\n", " / "))
        if not self.token:
            return False
        for i in range(3):
            try:
                r = requests.post(f"https://api.github.com/repos/{REPO}/actions/workflows/pc-notify.yml/dispatches",
                                  headers={"Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json"},
                                  json={"ref": "main", "inputs": {"kind": kind, "message": message}}, timeout=20)
                if r.status_code in (200, 204):
                    return True
                log.warning("알림 실패 %s %s", r.status_code, r.text[:200])
                if r.status_code in (401, 403, 404):
                    return False
            except Exception as e:
                log.warning("알림 오류 %r", e)
            time.sleep(10 * (i + 1))
        return False


# ───────────────────────── 속도 조절 ─────────────────────────
class Limiter:
    """초당 rate 건으로 흘려보냄. 30분 동안 거절이 없으면 25% 올리고, 거절(EGW00201)되면 30% 낮춤.
       하루 거절 20번이 넘으면 그날은 더 올리지 않음. 상한은 두지 않되 시험 범위(40건)까지만."""
    def __init__(self, start=2.5, ceiling=40.0):
        self.lock = threading.Lock()
        self.f = STATE / "speed.json"
        saved = {}
        try: saved = json.loads(self.f.read_text(encoding="utf-8"))
        except Exception: pass
        self.rate = float(saved.get("rate", start))
        self.ceiling = ceiling
        self.next_t = time.time()
        self.last_change = time.time()
        self.day = date.today().isoformat()
        self.over_today = saved.get("over_today", 0) if saved.get("day") == self.day else 0
        self.over_total = saved.get("over_total", 0)
        self.calls = 0
        self.history = saved.get("history", [])[-50:]

    def _save(self):
        try:
            self.f.write_text(json.dumps({"rate": round(self.rate, 2), "day": self.day, "over_today": self.over_today,
                                          "over_total": self.over_total, "history": self.history[-50:]}, ensure_ascii=False),
                              encoding="utf-8")
        except Exception: pass

    def _note(self, why):
        self.history.append(f"{datetime.now():%m-%d %H:%M} {why} → {self.rate:.1f}")
        log.info("속도 %s → 초당 %.1f건", why, self.rate)
        self._save()

    def acquire(self):
        while True:                              # 매일 측정 시간에는 쉼
            now = datetime.now().strftime("%H%M%S")
            if PAUSE[0] <= now < PAUSE[1]:
                time.sleep(20); continue
            break
        with self.lock:
            t = max(time.time(), self.next_t)
            self.next_t = t + 1.0 / self.rate
        d = t - time.time()
        if d > 0: time.sleep(d)

    def ok(self):
        with self.lock:
            self.calls += 1
            today = date.today().isoformat()
            if today != self.day:
                self.day, self.over_today = today, 0
            if (time.time() - self.last_change > 1800 and self.over_today < 20 and self.rate < self.ceiling):
                self.rate = min(self.ceiling, self.rate * 1.25); self.last_change = time.time(); self._note("올림")

    def over(self):
        with self.lock:
            self.over_today += 1; self.over_total += 1
            if time.time() - self.last_change > 5:   # 동시에 여러 개가 거절돼도 한 번만 낮춤
                self.rate = max(1.0, self.rate * 0.7); self.last_change = time.time(); self._note("거절되어 낮춤")
            self.next_t = time.time() + 1.0


# ───────────────────────── KIS 호출 ─────────────────────────
class KIS:
    def __init__(self, key, secret, limiter, notifier):
        self.key, self.secret, self.lim, self.nt = key, secret, limiter, notifier
        self.s = requests.Session()
        self.tok_f = STATE / "token.json"
        self.tok, self.tok_exp = None, None
        self.tok_lock = threading.Lock()
        self.down_since = None
        self.down_notified = False
        self.outages = 0

    def token(self, force=False):
        with self.tok_lock:
            if not force and self.tok is None and self.tok_f.exists():
                try:
                    c = json.loads(self.tok_f.read_text(encoding="utf-8"))
                    if c.get("key") == self.key[-6:]:
                        self.tok, self.tok_exp = c["token"], datetime.strptime(c["expired"], "%Y-%m-%d %H:%M:%S")
                except Exception: pass
            if not force and self.tok and self.tok_exp - datetime.now() > timedelta(hours=1):
                return self.tok
            while True:
                try:
                    r = self.s.post(REAL + "/oauth2/tokenP", timeout=20, json={
                        "grant_type": "client_credentials", "appkey": self.key, "appsecret": self.secret}).json()
                except Exception as e:
                    log.warning("토큰 요청 실패 %r — 60초 뒤 다시", e); time.sleep(60); continue
                if "access_token" in r:
                    self.tok = r["access_token"]
                    self.tok_exp = datetime.strptime(r["access_token_token_expired"], "%Y-%m-%d %H:%M:%S")
                    self.tok_f.write_text(json.dumps({"key": self.key[-6:], "token": self.tok,
                                                      "expired": r["access_token_token_expired"]}), encoding="utf-8")
                    log.info("토큰 발급 (만료 %s)", r["access_token_token_expired"])
                    return self.tok
                msg = f"{r.get('error_code', '')} {r.get('error_description', r)}"
                log.warning("토큰 발급 거절: %s — 65초 뒤 다시", msg); time.sleep(65)

    def get(self, path, tr, params):
        """성공하면 응답 dict, 계속 실패하면 None. 인터넷 끊김은 돌아올 때까지 기다린다."""
        backoff = [10, 30, 60, 120, 300]
        bad = 0
        while True:
            if (STATE / "STOP").exists():
                return None
            self.lim.acquire()
            try:
                resp = self.s.get(REAL + path, timeout=20, params=params, headers={
                    "content-type": "application/json; charset=utf-8", "authorization": f"Bearer {self.token()}",
                    "appkey": self.key, "appsecret": self.secret, "tr_id": tr, "custtype": "P"})
                r = resp.json()
            except (requests.ConnectionError, requests.Timeout) as e:
                self._down(e, backoff); continue
            except ValueError:                  # JSON 이 아닌 응답(점검 시간 등)
                bad += 1
                if bad >= 6: return None
                time.sleep(10 * bad); continue
            except Exception as e:
                self._down(e, backoff); continue
            self._up()
            code = r.get("msg_cd", "")
            if code == "EGW00201":
                self.lim.over(); time.sleep(1 + random.random()); continue
            if code in ("EGW00121", "EGW00123"):
                self.token(force=True); continue
            self.lim.ok()
            return r

    def _down(self, e, backoff):
        if self.down_since is None:
            self.down_since = time.time(); self.outages += 1
            log.warning("연결 끊김: %r", e)
        mins = (time.time() - self.down_since) / 60
        if mins >= 30 and not self.down_notified:
            self.down_notified = True
            self.nt.send("error", f"[분봉 수집] 인터넷·서버 연결이 {int(mins)}분째 끊겨 있습니다. 돌아오면 자동으로 이어 받습니다.")
        n = min(int(mins // 2), len(backoff) - 1)
        time.sleep(backoff[n])

    def _up(self):
        if self.down_since is not None:
            mins = (time.time() - self.down_since) / 60
            log.info("연결 복구 (%.1f분 끊김)", mins)
            if self.down_notified:
                self.nt.send("info", f"[분봉 수집] 연결 복구 — {int(mins)}분 끊겼다가 다시 받는 중입니다.")
            self.down_since, self.down_notified = None, False


def minus1(hhmmss):
    h, m = int(hhmmss[:2]), int(hhmmss[2:4])
    t = h * 60 + m - 1
    return f"{t // 60:02d}{t % 60:02d}00"


# ───────────────────────── 받기 함수 ─────────────────────────
def fetch_stock(kis, code, d, mkt):
    """하루치 1분봉 (mkt: J=KRX 09~20시, UN=통합 08~20시). 실패 None, 거래 없음 []"""
    ds = d.strftime("%Y%m%d"); lo = "090000" if mkt == "J" else "080000"
    hh, rows = "200000", {}
    for _ in range(14):
        r = kis.get(Q + "inquire-time-dailychartprice", "FHKST03010230", {
            "FID_COND_MRKT_DIV_CODE": mkt, "FID_INPUT_ISCD": code, "FID_INPUT_HOUR_1": hh,
            "FID_INPUT_DATE_1": ds, "FID_PW_DATA_INCU_YN": "N", "FID_FAKE_TICK_INCU_YN": ""})
        if r is None or r.get("rt_cd") != "0":
            return None
        allr = [x for x in (r.get("output2") or []) if x.get("stck_cntg_hour")]
        out = [x for x in allr if x.get("stck_bsop_date") == ds]
        if not out: break
        for x in out: rows[x["stck_cntg_hour"]] = x
        first = min(x["stck_cntg_hour"] for x in out)
        if first <= lo or len(out) < len(allr): break
        hh = minus1(first)
    return list(rows.values())


def fetch_fut(kis, code, d, session):
    """선물 하루치. session=day: 08:45~15:45 / night: 그날 18:00 ~ 다음 날 06:00(시각 24~30시로 옴)"""
    ds = d.strftime("%Y%m%d"); rows = {}

    def call(qdate, hh, mkt):
        r = kis.get(FQ + "inquire-time-fuopchartprice", "FHKIF03020200", {
            "FID_COND_MRKT_DIV_CODE": mkt, "FID_INPUT_ISCD": code, "FID_HOUR_CLS_CODE": "60",
            "FID_PW_DATA_INCU_YN": "Y", "FID_FAKE_TICK_INCU_YN": "N",
            "FID_INPUT_DATE_1": qdate, "FID_INPUT_HOUR_1": hh})
        if r is None or r.get("rt_cd") != "0": return None
        return [x for x in (r.get("output2") or []) if x.get("stck_cntg_hour")]

    if session == "day":
        hh = "154500"
        for _ in range(8):
            allr = call(ds, hh, "F")
            if allr is None: return None
            out = [x for x in allr if x.get("stck_bsop_date") == ds]
            if not out: break
            for x in out: rows[x["stck_cntg_hour"]] = x
            first = min(x["stck_cntg_hour"] for x in out)
            if first <= "084500" or len(out) < len(allr): break
            hh = minus1(first)
    else:
        hh = "235959"                                   # 18:00 ~ 24:00
        for _ in range(6):
            allr = call(ds, hh, "CM")
            if allr is None: return None
            out = [x for x in allr if x.get("stck_bsop_date") == ds and x["stck_cntg_hour"] <= "240000"]
            if not out: break
            for x in out: rows[x["stck_cntg_hour"]] = x
            first = min(x["stck_cntg_hour"] for x in out)
            if first <= "180000": break
            hh = minus1(first)
        nxt = (d + timedelta(days=1)).strftime("%Y%m%d"); hh = "060000"   # 24:00 ~ 30:00 (다음 날 날짜로 요청)
        for _ in range(8):
            allr = call(nxt, hh, "CM")
            if allr is None: return None
            out = [x for x in allr if x.get("stck_bsop_date") == ds and x["stck_cntg_hour"] > "240000"]
            if not out: break
            new = [x for x in out if x["stck_cntg_hour"] not in rows]
            for x in out: rows[x["stck_cntg_hour"]] = x
            first = min(x["stck_cntg_hour"] for x in out)
            if first <= "240100" or not new: break
            h = int(first[:2]) - 24
            hh = minus1(f"{h:02d}{first[2:]}")
    return list(rows.values())


# ───────────────────────── 저장·진행 기록 ─────────────────────────
class Store:
    def __init__(self, root):
        self.root = root
        self.db = sqlite3.connect(STATE / ("progress.db" if root == DATA else "selftest.db"), check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("CREATE TABLE IF NOT EXISTS done(kind TEXT, key TEXT, d TEXT, bars INT, at TEXT, PRIMARY KEY(kind,key,d))")
        self.db.execute("CREATE TABLE IF NOT EXISTS days(d TEXT PRIMARY KEY, kind TEXT, at TEXT)")   # 휴장일 등
        self.db.commit()
        self.lock = threading.Lock()
        self.buf = {}        # (kind, d) -> [(key, rows)]

    def is_done(self, kind, key, d):
        with self.lock:
            return self.db.execute("SELECT 1 FROM done WHERE kind=? AND key=? AND d=?", (kind, key, d)).fetchone() is not None

    def done_keys(self, kind, d):
        with self.lock:
            return {k for (k,) in self.db.execute("SELECT key FROM done WHERE kind=? AND d=?", (kind, d))}

    def day_mark(self, d, kind):
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO days VALUES(?,?,?)", (d, kind, datetime.now().isoformat(timespec="seconds")))
            self.db.commit()

    def day_kind(self, d):
        with self.lock:
            r = self.db.execute("SELECT kind FROM days WHERE d=?", (d,)).fetchone()
            return r[0] if r else None

    def add(self, kind, d, key, rows, flush_at=300):
        with self.lock:
            self.buf.setdefault((kind, d), []).append((key, rows))
            n = len(self.buf[(kind, d)])
        if n >= flush_at:
            self.flush(kind, d)

    def flush(self, kind, d):
        import pandas as pd
        with self.lock:
            items = self.buf.pop((kind, d), [])
        if not items: return
        recs = []
        for key, rows in items:
            for x in rows:
                y = dict(x); y["code"] = key; recs.append(y)
        part_dir = self.root / "parts" / kind / d
        part_dir.mkdir(parents=True, exist_ok=True)
        if recs:
            df = pd.DataFrame(recs)
            for c in df.columns:
                if c not in ("code", "stck_bsop_date", "stck_cntg_hour", "session", "trade_date", "dt"):
                    try: df[c] = pd.to_numeric(df[c])
                    except Exception: pass
            tmp = part_dir / f".tmp_{time.time_ns()}.parquet"
            df.to_parquet(tmp, index=False)
            tmp.rename(part_dir / f"part_{time.time_ns()}.parquet")
        at = datetime.now().isoformat(timespec="seconds")
        with self.lock:
            self.db.executemany("INSERT OR REPLACE INTO done VALUES(?,?,?,?,?)",
                                [(kind, key, d, len(rows), at) for key, rows in items])
            self.db.commit()

    def merge(self, kind, d):
        """그날 조각 파일들을 하나로 합침: data/<kind>/<YYYY-MM>/<YYYYMMDD>.parquet"""
        import pandas as pd
        part_dir = self.root / "parts" / kind / d
        dest = self.root / kind / f"{d[:4]}-{d[4:6]}" / f"{d}.parquet"
        parts = sorted(part_dir.glob("part_*.parquet")) if part_dir.exists() else []
        if not parts: return dest if dest.exists() else None
        dfs = [pd.read_parquet(p) for p in parts]
        if dest.exists(): dfs.insert(0, pd.read_parquet(dest))
        df = pd.concat(dfs, ignore_index=True)
        key = [c for c in ("code", "stck_bsop_date", "stck_cntg_hour") if c in df.columns]
        if key: df = df.drop_duplicates(subset=key, keep="last")
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".tmp")
        df.to_parquet(tmp, index=False); os.replace(tmp, dest)
        for p in parts: p.unlink()
        try: part_dir.rmdir()
        except Exception: pass
        return dest

    def counts(self):
        with self.lock:
            return dict(self.db.execute("SELECT kind, COUNT(*) FROM done GROUP BY kind").fetchall())


# ───────────────────────── 종목 목록 ─────────────────────────
KOSPI_SPECS = [2, 1, 4, 4, 4, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 9, 5, 5, 1,
               1, 1, 2, 1, 1, 1, 2, 2, 2, 3, 1, 3, 12, 12, 8, 15, 21, 2, 7, 1, 1, 1, 1, 1, 9, 9, 9, 5, 9, 8, 9, 3, 1, 1, 1]
KOSDAQ_SPECS = [2, 1, 4, 4, 4, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 9, 5, 5, 1, 1, 1, 2, 1, 1,
                1, 2, 2, 2, 3, 1, 3, 12, 12, 8, 15, 21, 2, 7, 1, 1, 1, 1, 9, 9, 9, 5, 9, 8, 9, 3, 1, 1, 1]
KEEP_GROUPS = {"ST", "EF", "RT", "DR", "FS", "IF", "MF", "BC"}   # 주식·ETF·리츠·DR·외국주식·인프라·뮤추얼·수익증권 (ETN·워런트 제외)


def field(row_tail, specs, idx):
    off = sum(specs[:idx]); return row_tail[off:off + specs[idx]].strip()


def load_universe(force=False):
    f = STATE / "universe.json"
    if f.exists() and not force:
        u = json.loads(f.read_text(encoding="utf-8"))
        if (datetime.now() - datetime.fromisoformat(u["at"])).days < 7:
            return u
    stocks, groups = [], {}
    for name, tail, specs, i_list, i_cap in (("kospi", 227, KOSPI_SPECS, 49, 65), ("kosdaq", 221, KOSDAQ_SPECS, 44, 60)):   # 공식 예제의 228/222 는 줄바꿈 포함
        raw = requests.get(f"https://new.real.download.dws.co.kr/common/master/{name}_code.mst.zip", timeout=60).content
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            text = z.read(z.namelist()[0]).decode("cp949", errors="replace")
        for row in text.splitlines():
            if len(row) < tail + 10: continue
            head, t = row[:len(row) - tail], row[-tail:]
            code, nm = head[0:9].strip(), head[21:].strip()
            grp = t[0:2]
            groups[grp] = groups.get(grp, 0) + 1
            if grp not in KEEP_GROUPS: continue
            try: cap = float(field(t, specs, i_cap) or 0)
            except Exception: cap = 0
            stocks.append({"code": code, "name": nm, "market": name, "group": grp,
                           "listed": field(t, specs, i_list), "cap": cap})
    stocks.sort(key=lambda s: -s["cap"])
    u = {"at": datetime.now().isoformat(timespec="seconds"), "stocks": stocks, "groups": groups}
    f.write_text(json.dumps(u, ensure_ascii=False), encoding="utf-8")
    log.info("종목 목록 %d개 (분류별 %s)", len(stocks), groups)
    return u


def nxt_codes(kis, u, ref_day):
    """NXT 거래 종목 찾기: 최근 거래일에 통합 분봉이 나오는 종목 (ETF 제외). 결과는 7일 동안 재사용."""
    f = STATE / "nxt.json"
    if f.exists():
        c = json.loads(f.read_text(encoding="utf-8"))
        if (datetime.now() - datetime.fromisoformat(c["at"])).days < 7 and c.get("total") == len(u["stocks"]):
            return set(c["codes"])
    cand = [s["code"] for s in u["stocks"] if s["group"] != "EF"]
    found, lock = set(), threading.Lock()
    ds = ref_day.strftime("%Y%m%d")
    log.info("NXT 거래 종목 확인 시작 (%d개)", len(cand))

    def chk(code):
        r = kis.get(Q + "inquire-time-dailychartprice", "FHKST03010230", {
            "FID_COND_MRKT_DIV_CODE": "UN", "FID_INPUT_ISCD": code, "FID_INPUT_HOUR_1": "200000",
            "FID_INPUT_DATE_1": ds, "FID_PW_DATA_INCU_YN": "N", "FID_FAKE_TICK_INCU_YN": ""})
        if r and any(x.get("stck_bsop_date") == ds for x in (r.get("output2") or [])):
            with lock: found.add(code)

    with ThreadPoolExecutor(WORKERS) as ex:
        list(ex.map(chk, cand))
    f.write_text(json.dumps({"at": datetime.now().isoformat(timespec="seconds"), "total": len(u["stocks"]),
                             "codes": sorted(found)}), encoding="utf-8")
    log.info("NXT 거래 종목 %d개", len(found))
    return found


# ───────────────────────── 날짜 ─────────────────────────
def weekdays(a, b):
    d, out = a, []
    while d <= b:
        if d.weekday() < 5: out.append(d)
        d += timedelta(days=1)
    return out


def earliest_day(kis):
    """삼성전자 KRX 분봉이 나오는 가장 오래된 날 (약 1년 전)"""
    def has(d):
        ds = d.strftime("%Y%m%d")
        r = kis.get(Q + "inquire-time-dailychartprice", "FHKST03010230", {
            "FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": "005930", "FID_INPUT_HOUR_1": "153000",
            "FID_INPUT_DATE_1": ds, "FID_PW_DATA_INCU_YN": "N", "FID_FAKE_TICK_INCU_YN": ""})
        return bool(r) and any(x.get("stck_bsop_date") == ds for x in (r.get("output2") or []))
    lo, hi = date.today() - timedelta(days=420), date.today() - timedelta(days=330)
    while (hi - lo).days > 1:
        mid = lo + (hi - lo) / 2
        found = False
        for k in range(4):                       # 휴장일이면 다음 평일로
            dd = mid + timedelta(days=k)
            if dd.weekday() < 5 and has(dd): found = True; break
        if found: hi = mid
        else: lo = mid
    d = hi
    for _ in range(6):                           # 하루씩 앞으로 더 있는지 확인
        p = d - timedelta(days=1)
        while p.weekday() >= 5: p -= timedelta(days=1)
        if has(p): d = p
        else: break
    return d


def front_contracts(d):
    """그날 받을 선물 월물: 최근월물 + 만기 14일 전부터는 다음 월물"""
    for i, (c, exp) in enumerate(CONTRACTS):
        if exp >= d:
            out = [c]
            if (exp - d).days <= 14 and i + 1 < len(CONTRACTS): out.append(CONTRACTS[i + 1][0])
            return out
    return []


def real_dt(trade_date, hhmmss):
    h = int(hhmmss[:2]); base = datetime.strptime(trade_date, "%Y%m%d")
    return (base + timedelta(hours=h, minutes=int(hhmmss[2:4]), seconds=int(hhmmss[4:6]))).isoformat()


# ───────────────────────── 수집 본체 ─────────────────────────
class Collector:
    def __init__(self, env, root=DATA, notify=True):
        self.env = env
        self.nt = Notifier(env.get("GITHUB_TOKEN") if notify else None)
        self.lim = Limiter(start=float(env.get("START_RPS", 2.5)))
        self.kis = KIS(env["KIS_REAL_APP_KEY"], env["KIS_REAL_APP_SECRET"], self.lim, self.nt)
        self.st = Store(root)
        self.root = root
        self.fail_streak = 0
        self.fail_notified = False
        self.t0 = time.time()
        self.cur = ""
        self.stat_f = STATE / "status.json"

    def stopped(self):
        return (STATE / "STOP").exists()

    # 선물
    def futures_day(self, d):
        ds = d.strftime("%Y%m%d")
        for code in front_contracts(d):
            for sess in ("day", "night"):
                kind = f"futures_{sess}"
                if self.st.is_done(kind, code, ds): continue
                rows = fetch_fut(self.kis, code, d, sess)
                if rows is None: self._fail(); continue
                self._ok()
                for x in rows:
                    x["session"] = sess; x["trade_date"] = ds; x["dt"] = real_dt(ds, x["stck_cntg_hour"])
                self.st.add(kind, ds, code, rows, flush_at=1)
        for sess in ("day", "night"):
            self.st.merge(f"futures_{sess}", ds)

    # 주식
    def stock_day(self, d, u, nxt):
        ds = d.strftime("%Y%m%d")
        if self.st.day_kind(ds) == "holiday": return True
        tasks = []
        for mkt, kind in (("J", "krx"), ("UN", "un")):
            done = self.st.done_keys(kind, ds)
            for s in u["stocks"]:
                if mkt == "UN" and s["code"] not in nxt: continue
                lst = s.get("listed") or ""
                if len(lst) == 8 and lst.isdigit() and lst[:2] in ("19", "20") and lst > ds: continue
                if s["code"] not in done: tasks.append((mkt, kind, s["code"]))
        if not tasks:
            for k in ("krx", "un"): self.st.merge(k, ds)
            return True
        # 첫 작업(삼성전자 KRX)으로 휴장일 확인
        if ("J", "krx", "005930") in tasks:
            first = fetch_stock(self.kis, "005930", d, "J")
            if first is not None and not first and not self.st.done_keys("krx", ds):
                self.st.day_mark(ds, "holiday"); log.info("%s 휴장일", ds); return True
            if first:
                self.st.add("krx", ds, "005930", first); tasks.remove(("J", "krx", "005930"))
        log.info("%s 주식 남은 작업 %d개", ds, len(tasks))
        failed = 0
        with ThreadPoolExecutor(WORKERS) as ex:
            futs = {ex.submit(fetch_stock, self.kis, code, d, mkt): (mkt, kind, code) for mkt, kind, code in tasks}
            for f in as_completed(futs):
                mkt, kind, code = futs[f]
                rows = f.result()
                if rows is None:
                    failed += 1; self._fail(); continue
                self._ok()
                self.st.add(kind, ds, code, rows)
                self.cur = f"{ds}"
                if self.stopped(): break
        for k in ("krx", "un"): self.st.flush(k, ds)
        if failed == 0 and not self.stopped():
            for k in ("krx", "un"): self.st.merge(k, ds)
            return True
        return False

    def _ok(self):
        self.fail_streak = 0

    def _fail(self):
        self.fail_streak += 1
        if self.fail_streak >= 50 and not self.fail_notified:
            self.fail_notified = True
            self.nt.send("error", "[분봉 수집] 요청 실패가 50번 연속 났습니다. 잠시 쉬었다가 계속합니다. (logs 확인)")
            time.sleep(600)
            self.fail_notified = False; self.fail_streak = 0

    def progress_text(self, days, phase):
        c = self.st.counts()
        stock_tasks = c.get("krx", 0) + c.get("un", 0)
        hol = sum(1 for d in days if self.st.day_kind(d.strftime("%Y%m%d")) == "holiday")
        size = sum(p.stat().st_size for p in self.root.rglob("*.parquet")) / 1e9
        est_total = (len(days) - hol) * (self.n_stocks + self.n_nxt)
        pct = 100 * stock_tasks / est_total if est_total else 0
        remain = max(0, est_total - stock_tasks)
        hrs = remain * 2.6 / max(self.lim.rate, 0.5) / 3600   # 종목-날짜당 평균 약 2.6번 호출로 추정
        return (f"[분봉 수집 {datetime.now():%m/%d %H:%M}] {phase}\n"
                f"주식 {pct:.1f}% ({stock_tasks:,}/{est_total:,}) 지금 {self.cur or '-'}\n"
                f"선물 {c.get('futures_day', 0)}일 · 속도 {self.lim.rate:.1f}건/초 · 오늘 거절 {self.lim.over_today}\n"
                f"용량 {size:.2f}GB · 끊김 {self.kis.outages}회 · 남은 약 {hrs:.0f}시간")

    def write_status(self, text):
        try: self.stat_f.write_text(json.dumps({"at": datetime.now().isoformat(timespec="seconds"), "text": text},
                                               ensure_ascii=False), encoding="utf-8")
        except Exception: pass

    def daily_report_loop(self, days_fn, phase_fn):
        f = STATE / "last_report.txt"
        while not self.stopped():
            try:
                now = datetime.now()
                last = f.read_text().strip() if f.exists() else ""
                txt = self.progress_text(days_fn(), phase_fn())
                self.write_status(txt)
                if now.strftime("%H%M") >= "0650" and last != now.strftime("%Y-%m-%d"):
                    if self.nt.send("progress", txt): f.write_text(now.strftime("%Y-%m-%d"))
            except Exception as e:
                log.warning("진행 보고 오류 %r", e)
            time.sleep(60)

    def run(self):
        self.kis.token()
        u = load_universe()
        self.n_stocks = len(u["stocks"])
        start = earliest_day(self.kis)
        log.info("받을 수 있는 가장 오래된 날: %s", start)
        self.n_nxt = len(json.loads((STATE / "nxt.json").read_text())["codes"]) if (STATE / "nxt.json").exists() else 700
        phase = {"v": "선물"}
        days_fn = lambda: weekdays(start, date.today() - timedelta(days=1))
        threading.Thread(target=self.daily_report_loop, args=(days_fn, lambda: phase["v"]), daemon=True).start()
        first_run = not (STATE / "started.txt").exists()
        if first_run:
            (STATE / "started.txt").write_text(datetime.now().isoformat())
            self.nt.send("start", f"[분봉 수집 시작] {start}부터 · 종목 {self.n_stocks:,}개 · 속도 {self.lim.rate:.1f}건/초로 시작")
        else:
            self.nt.send("info", "[분봉 수집] 다시 시작 — 받은 곳 다음부터 이어 받습니다.")

        # 1) 선물 전체 (오래된 날부터)
        for d in days_fn():
            if self.stopped(): return
            self.futures_day(d)
        # 2) 주식: NXT 종목 확인 후 날짜별 전 종목
        phase["v"] = "주식"
        ref = date.today() - timedelta(days=1)
        while ref.weekday() >= 5: ref -= timedelta(days=1)
        nxt = nxt_codes(self.kis, u, ref)
        self.n_nxt = len(nxt)
        while not self.stopped():
            days = days_fn()
            if days and days[0] < start: days = [d for d in days if d >= start]
            pending = False
            for d in days:
                if self.stopped(): return
                self.futures_day(d)                # 새로 생긴 날의 선물도
                if not self.stock_day(d, u, nxt): pending = True
            if not pending: break
            log.info("실패한 작업이 있어 10분 뒤 다시 시도"); time.sleep(600)
        if self.stopped(): return
        txt = self.progress_text(days_fn(), "완료")
        self.write_status(txt)
        self.nt.send("done", "[분봉 수집 완료]\n" + txt.split("\n", 1)[1])
        (STATE / "completed.txt").write_text(datetime.now().isoformat())
        if os.name == "nt":
            subprocess.run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"], capture_output=True)
        log.info("수집 완료 — 자동 재시작 등록 해제")


# ───────────────────────── 실행 ─────────────────────────
def single_instance():
    f = open(STATE / "collector.lock", "a+")
    try:
        if os.name == "nt":
            import msvcrt; msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl; fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return None
    return f


def low_priority():
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x4000)  # BELOW_NORMAL
        except Exception: pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true"); ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    setup_logging(console=sys.stdout is not None and sys.stdout.isatty() or a.check or a.selftest)
    env = load_env()
    miss = [k for k in ("KIS_REAL_APP_KEY", "KIS_REAL_APP_SECRET") if not env.get(k)]
    if miss:
        print("[오류] .env 에 값이 없습니다:", ", ".join(miss)); return 2
    if (STATE / "completed.txt").exists() and not (a.check or a.selftest):
        log.info("이미 수집 완료됨 — 종료"); return 0

    if a.check:
        c = Collector(env)
        c.kis.token()
        r = fetch_stock(c.kis, "005930", date.today() - timedelta(days=1 if date.today().weekday() else 3), "J")
        print(f"[점검] KIS 연결 정상 — 삼성전자 어제 1분봉 {len(r or [])}개")
        ok = c.nt.send("info", "[분봉 수집] PC 설정 점검 완료 — 카카오톡 알림 연결 정상입니다.") if env.get("GITHUB_TOKEN") else False
        print("[점검] 카카오톡 알림:", "정상 (잠시 뒤 카카오톡 확인)" if ok else "GITHUB_TOKEN 없음 또는 실패")
        return 0

    if a.selftest:
        root = BASE / "selftest"; root.mkdir(exist_ok=True)
        c = Collector(env, root=root, notify=False)
        c.kis.token()
        y = date.today() - timedelta(days=1)
        while y.weekday() >= 5: y -= timedelta(days=1)
        old = date(2025, 12, 2)
        t = time.time()
        for d in (old, y):
            c.futures_day(d)
        u = {"stocks": [{"code": "005930", "listed": "19750611"}, {"code": "069500", "listed": "20021014"},
                        {"code": "033170", "listed": ""}]}
        c.stock_day(y, u, {"005930"})
        import pandas as pd
        for p in sorted(root.rglob("*.parquet")):
            df = pd.read_parquet(p)
            extra = ""
            if "dt" in df.columns: extra = f" dt {df['dt'].min()} ~ {df['dt'].max()}"
            print(f"[시험] {p.relative_to(root)}: {len(df)}행, 종목 {sorted(df['code'].unique())}{extra}, 열 {list(df.columns)[:12]}")
        uu = load_universe(force=True)
        import collections
        print("[시험] 종목 목록", len(uu["stocks"]), "분류", uu["groups"])
        print("[시험] 시총 상위 5", [(x["code"], x["name"], x["group"], x["listed"], x["cap"]) for x in uu["stocks"][:5]])
        print("[시험] 상장일 형식 이상", sum(1 for x in uu["stocks"] if not (len(x["listed"]) == 8 and x["listed"].isdigit())))
        print("[시험] 가장 오래된 날", earliest_day(c.kis))
        print(f"[시험] 호출 {c.lim.calls}번, {time.time() - t:.0f}초, 진행기록 {c.st.counts()}")
        return 0

    lock = single_instance()
    if lock is None:
        return 0                                   # 이미 돌고 있음
    low_priority()
    if (STATE / "STOP").exists():
        log.info("STOP 파일이 있어 시작하지 않음"); return 0
    c = Collector(env)
    try:
        c.run()
    except Exception as e:
        log.exception("수집기 오류")
        c.nt.send("error", f"[분봉 수집] 오류로 멈춤: {repr(e)[:120]} — 10분 안에 자동으로 다시 시작합니다.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
