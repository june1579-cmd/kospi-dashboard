"""
한국투자증권(KIS) Open API 연결 테스트 — 조회만 하고 주문은 하지 않는다.
- 내 PC:   kis/.env 에 키를 넣고  python kis/kis_connect_test.py mock|real|both
- GitHub:  저장소 Secrets(KIS_REAL_APP_KEY 등)를 환경변수로 받아 같은 명령으로 실행
           (Actions → kis-connect-test → Run workflow)
- 하는 일: 1) 접근토큰 발급  2) 삼성전자 현재가  3) 계좌 잔고  4) 웹소켓 접속키
- 저장소가 공개라 GitHub 실행 때는 잔고 금액·계좌번호를 로그에 찍지 않는다(성공/실패만).
- --notify 파일경로 를 주면 카카오톡용 요약(200자 이내)을 그 파일에 쓴다.
"""
import argparse, json, os, sys, time
from datetime import datetime
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
CACHE_DIR = Path.home() / "KIS"
ON_GITHUB = os.environ.get("GITHUB_ACTIONS") == "true"

SERVERS = {
    "real": "https://openapi.koreainvestment.com:9443",
    "mock": "https://openapivts.koreainvestment.com:29443",
}
BALANCE_TR = {"real": "TTTC8434R", "mock": "VTTC8434R"}
NAMES = {"real": "실전", "mock": "모의"}


def load_env() -> dict:
    """kis/.env 가 있으면 그것을, 없으면 환경변수(GitHub Secrets)를 쓴다."""
    env = dict(os.environ)
    path = HERE / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            v = v.strip().strip('"').strip("'")
            if v:
                env[k.strip()] = v
    return env


def get_token(mode, base, key, secret):
    """토큰은 1분에 1번만 발급되므로 파일에 저장해 두고 만료 전까지 재사용"""
    CACHE_DIR.mkdir(exist_ok=True)
    cache = CACHE_DIR / f"token_{mode}.json"
    if cache.exists():
        try:
            c = json.loads(cache.read_text(encoding="utf-8"))
            exp = datetime.strptime(c["expired"], "%Y-%m-%d %H:%M:%S")
            if (exp - datetime.now()).total_seconds() > 600:
                print(f"  · 저장된 토큰 재사용 (만료 {c['expired']})")
                return c["token"], None
        except Exception:
            pass
    data = requests.post(f"{base}/oauth2/tokenP", json={
        "grant_type": "client_credentials", "appkey": key, "appsecret": secret,
    }, timeout=15).json()
    if "access_token" not in data:
        return None, f"{data.get('error_code', '')} {data.get('error_description', data)}"
    cache.write_text(json.dumps({
        "token": data["access_token"], "expired": data["access_token_token_expired"],
    }), encoding="utf-8")
    print(f"  · 새 토큰 발급 (만료 {data['access_token_token_expired']})")
    return data["access_token"], None


def hdr(token, key, secret, tr_id):
    return {"content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {token}", "appkey": key, "appsecret": secret,
            "tr_id": tr_id, "custtype": "P"}


def run(mode, env):
    """한 계좌(실전/모의) 시험. 결과: {'토큰':bool, '시세':bool, '잔고':bool|None, '웹소켓':bool}"""
    P = f"KIS_{mode.upper()}_"
    key, secret, cano = env.get(P + "APP_KEY"), env.get(P + "APP_SECRET"), env.get(P + "CANO")
    prdt = env.get("KIS_ACNT_PRDT_CD") or "01"
    base, gap = SERVERS[mode], (1.1 if mode == "mock" else 0.2)   # 모의는 초당 1회 수준 제한
    res = {}
    print(f"\n=== KIS 연결 테스트 [{NAMES[mode]}] ===")
    if not key or not secret:
        print(f"  · {P}APP_KEY / {P}APP_SECRET 이 없어 건너뜀")
        return None

    print("1) 접근토큰")
    token, err = get_token(mode, base, key, secret)
    res["토큰"] = token is not None
    if not token:
        print(f"  · 실패: {err}")
        return res
    time.sleep(gap)

    print("2) 삼성전자(005930) 현재가")
    r = requests.get(f"{base}/uapi/domestic-stock/v1/quotations/inquire-price",
                     headers=hdr(token, key, secret, "FHKST01010100"),
                     params={"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": "005930"},
                     timeout=15).json()
    res["시세"] = r.get("rt_cd") == "0"
    if res["시세"]:
        o = r["output"]
        print(f"  · 현재가 {int(o['stck_prpr']):,}원 / 전일대비 {o['prdy_ctrt']}% / 거래량 {int(o['acml_vol']):,}")
    else:
        print(f"  · 실패: {r.get('msg_cd')} {r.get('msg1')}")
    time.sleep(gap)

    print("3) 계좌 잔고")
    if cano:
        r = requests.get(f"{base}/uapi/domestic-stock/v1/trading/inquire-balance",
                         headers=hdr(token, key, secret, BALANCE_TR[mode]),
                         params={"CANO": cano, "ACNT_PRDT_CD": prdt, "AFHR_FLPR_YN": "N",
                                 "OFL_YN": "", "INQR_DVSN": "02", "UNPR_DVSN": "01",
                                 "FUND_STTL_ICLD_YN": "N", "FNCG_AMT_AUTO_RDPT_YN": "N",
                                 "PRCS_DVSN": "00", "CTX_AREA_FK100": "", "CTX_AREA_NK100": ""},
                         timeout=15).json()
        res["잔고"] = r.get("rt_cd") == "0"
        if res["잔고"]:
            if ON_GITHUB:
                print("  · 조회 성공 (공개 로그라 금액은 표시하지 않음)")
            else:
                s = r["output2"][0]
                print(f"  · 예수금 {int(s['dnca_tot_amt']):,}원 / 총평가 {int(s['tot_evlu_amt']):,}원 / 보유종목 {len(r['output1'])}개")
        else:
            print(f"  · 실패: {r.get('msg_cd')} {r.get('msg1')}")
        time.sleep(gap)
    else:
        res["잔고"] = None
        print(f"  · {P}CANO(계좌번호 8자리)가 없어 건너뜀")

    print("4) 실시간 웹소켓 접속키")
    r = requests.post(f"{base}/oauth2/Approval", json={
        "grant_type": "client_credentials", "appkey": key, "secretkey": secret,
    }, timeout=15).json()
    res["웹소켓"] = "approval_key" in r
    print("  · 발급 성공" if res["웹소켓"] else f"  · 실패: {r}")
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", nargs="?", default="both", choices=["mock", "real", "both"])
    ap.add_argument("--notify", default="")
    a = ap.parse_args()
    env = load_env()
    modes = ["mock", "real"] if a.mode == "both" else [a.mode]

    lines, all_ok, tried = [], True, False
    for m in modes:
        res = run(m, env)
        if res is None:
            lines.append(f"{NAMES[m]}: 키 없음(Secrets 확인)")
            all_ok = False
            continue
        tried = True
        mark = lambda v: "-" if v is None else ("O" if v else "X")
        lines.append(f"{NAMES[m]}: " + " ".join(f"{k}{mark(res.get(k))}" for k in ["토큰", "시세", "잔고", "웹소켓"]))
        all_ok = all_ok and all(v is not False for v in res.values()) and len(res) == 4

    head = "[KIS 연결] 모두 성공" if (all_ok and tried) else "[KIS 연결] 확인 필요"
    msg = head + "\n" + "\n".join(lines)
    print("\n" + msg)
    if a.notify:
        Path(a.notify).write_text(msg[:200], encoding="utf-8")
    return 0 if (all_ok and tried) else 1


if __name__ == "__main__":
    sys.exit(main())
