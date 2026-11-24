# 금투협(FreeSIS) 공표 시각 재기 (2026-11-24 사용자 요청)
# 평일 낮에 5분마다 증시자금추이(예탁금·미수금·반대매매)와 신용공여 잔고의 '마지막 기준일'을 읽어, 새 기준일이 처음 보인 시각을 적는다.
# 자료는 고치지 않는다 — 기록만. 결과는 kofia-watch 가지의 kofia_pub_log.csv (main 자동 갱신과 겹치지 않게 따로 둔다).
#   published = 처음 보인 날, data_date = 새로 올라온 기준일, first_seen = 처음 보인 시각(KST), prev_check = 그 직전에 '아직 없음'을 확인한 시각 → 공표는 이 둘 사이
import sys, os, json, time, datetime as dt
import requests

OUT = sys.argv[1] if len(sys.argv) > 1 else 'kw'
LOOP_MIN = int(os.environ.get('LOOP_MIN', '55')); STEP = int(os.environ.get('STEP_SEC', '300'))
KST = dt.timezone(dt.timedelta(hours=9)); now = lambda: dt.datetime.now(KST)
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36'
OBJ = {'funds': 'STATSCU0100000060BO', 'credit': 'STATSCU0100000070BO'}   # 증시자금추이 / 신용공여 잔고
NAME = {'funds': '증시자금추이(예탁금·미수금·반대매매)', 'credit': '신용공여 잔고'}
BASE = 'https://freesis.kofia.or.kr'

def last_dates():
    warm = BASE + '/stat/FreeSIS.do?parentDivId=MSIS10000000000000&serviceId=STATSCU0100000060'
    s = requests.Session(); s.headers['User-Agent'] = UA; s.headers['Referer'] = warm
    s.get(warm, timeout=30)
    e = now().date(); b = e - dt.timedelta(days=14); res = {}
    for k, obj in OBJ.items():
        body = {'dmSearch': {'tmpV40': '1000000', 'tmpV41': '1', 'tmpV1': 'D', 'tmpV45': b.strftime('%Y%m%d'), 'tmpV46': e.strftime('%Y%m%d'), 'OBJ_NM': obj}}
        js = s.post(BASE + '/meta/getMetaDataList.do', json=body, timeout=30).json()
        ds = [str(x.get('TMPV1', '')) for x in js.get('ds1', [])]; ds = [d for d in ds if len(d) == 8 and d.isdigit()]
        if ds: res[k] = max(ds)
    return res

os.makedirs(OUT, exist_ok=True)
sp, lp = os.path.join(OUT, 'state.json'), os.path.join(OUT, 'kofia_pub_log.csv')
st = json.load(open(sp, encoding='utf-8')) if os.path.exists(sp) else {}
if not os.path.exists(lp): open(lp, 'w', encoding='utf-8').write('published,item,data_date,first_seen,prev_check,note\n')
today = now().strftime('%Y-%m-%d')
if all(st.get(k, {}).get('seen_on') == today for k in OBJ): print('오늘 공표는 이미 기록함 — 끝'); sys.exit(0)

end = time.time() + LOOP_MIN * 60; changed = False
while True:
    t = now().strftime('%Y-%m-%d %H:%M')
    try:
        cur = last_dates()
        for k, d in cur.items():
            s0 = st.setdefault(k, {})
            if s0.get('last') and d > s0['last']:
                note = '' if s0.get('checked', '')[:10] == today else '오늘 첫 확인에서 이미 있었음(공표는 그 전)'
                open(lp, 'a', encoding='utf-8').write(f"{today},{NAME[k]},{d[:4]}-{d[4:6]}-{d[6:]},{t},{s0.get('checked', '')},{note}\n")
                s0['seen_on'] = today; print('새 기준일', k, d, t)
            if not s0.get('last') or d > s0['last']: s0['last'] = d
            s0['checked'] = t; changed = True
        print(t, cur, flush=True)
    except Exception as e: print(t, '읽기 실패', repr(e), flush=True)
    json.dump(st, open(sp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    if all(st.get(k, {}).get('seen_on') == today for k in OBJ) or time.time() + STEP > end: break
    time.sleep(STEP)
