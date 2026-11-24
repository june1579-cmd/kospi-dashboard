# 금투협(FreeSIS) 공표 시각 재기 (2026-11-24 사용자 요청)
# 평일 낮에 5분마다 증시자금추이(예탁금·미수금·반대매매)와 신용공여 잔고의 '마지막 기준일'을 읽어, 새 기준일이 처음 보인 시각을 적는다.
# 자료는 고치지 않는다 — 기록만. 결과는 kofia-watch 가지의 kofia_pub_log.csv (main 자동 갱신과 겹치지 않게 따로 둔다).
#   published = 처음 보인 날, data_date = 새로 올라온 기준일, first_seen = 처음 보인 시각(KST), prev_check = 그 직전에 '아직 없음'을 확인한 시각 → 공표는 이 둘 사이
import sys, os, json, time, datetime as dt
import requests

OUT = sys.argv[1] if len(sys.argv) > 1 else 'kw'
LOOP_MIN = int(os.environ.get('LOOP_MIN', '55')); STEP = int(os.environ.get('STEP_SEC', '600'))   # 10분 간격(11/24: 기존 수집이 막히지 않게 5분 → 10분)
# 기존 자동 수집(update.yml: 08·09·10시 23분, 15·16·17시 43분)이 금투협을 읽는 시간에는 쉰다 — 같은 때 겹쳐 읽지 않는다
def busy(t): return (t.hour in (8, 9, 10) and 20 <= t.minute <= 34) or (t.hour in (15, 16, 17) and 40 <= t.minute <= 54)
KST = dt.timezone(dt.timedelta(hours=9)); now = lambda: dt.datetime.now(KST)
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36'
OBJ = {'funds': 'STATSCU0100000060BO', 'credit': 'STATSCU0100000070BO'}   # 증시자금추이 / 신용공여 잔고
NAME = {'funds': '증시자금추이(예탁금·미수금·반대매매)', 'credit': '신용공여 잔고'}
BASE = 'https://freesis.kofia.or.kr'

class Blocked(Exception): pass
def last_dates():
    warm = BASE + '/stat/FreeSIS.do?parentDivId=MSIS10000000000000&serviceId=STATSCU0100000060'
    s = requests.Session(); s.headers['User-Agent'] = UA; s.headers['Referer'] = warm
    s.get(warm, timeout=30)
    e = now().date(); b = e - dt.timedelta(days=7); res = {}   # 최근 7일만(가볍게)
    for k, obj in OBJ.items():
        body = {'dmSearch': {'tmpV40': '1000000', 'tmpV41': '1', 'tmpV1': 'D', 'tmpV45': b.strftime('%Y%m%d'), 'tmpV46': e.strftime('%Y%m%d'), 'OBJ_NM': obj}}
        r = s.post(BASE + '/meta/getMetaDataList.do', json=body, timeout=30)
        if r.status_code in (403, 429) or r.status_code >= 500: raise Blocked(f'HTTP {r.status_code}')
        js = r.json(); time.sleep(2)
        ds = [str(x.get('TMPV1', '')) for x in js.get('ds1', [])]; ds = [d for d in ds if len(d) == 8 and d.isdigit()]
        if ds: res[k] = max(ds)
    return res

os.makedirs(OUT, exist_ok=True)
sp, lp = os.path.join(OUT, 'state.json'), os.path.join(OUT, 'kofia_pub_log.csv')
st = json.load(open(sp, encoding='utf-8')) if os.path.exists(sp) else {}
if not os.path.exists(lp): open(lp, 'w', encoding='utf-8').write('published,item,data_date,first_seen,prev_check,note\n')
today = now().strftime('%Y-%m-%d'); skip = False
if all(st.get(k, {}).get('seen_on') == today for k in OBJ): print('오늘 공표는 이미 기록함 — 끝'); skip = True
if st.get('stop_on') == today: print('오늘은 금투협이 거절·오류를 내서 더 읽지 않음 — 끝'); skip = True

end = time.time() + LOOP_MIN * 60; changed = False; fails = 0
while not skip:
    t = now().strftime('%Y-%m-%d %H:%M')
    if busy(now()):
        print(t, '기존 수집 시간 — 쉼', flush=True)
        if time.time() + STEP > end: break
        time.sleep(STEP); continue
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
        fails = 0
    except Blocked as e:
        st['stop_on'] = today; print(t, '금투협 거절·오류 — 오늘은 여기서 멈춤', repr(e), flush=True)
        json.dump(st, open(sp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1); break
    except Exception as e:
        fails += 1; print(t, '읽기 실패', repr(e), flush=True)
        if fails >= 3: st['stop_on'] = today; print('연속 3번 실패 — 오늘은 멈춤', flush=True)
    json.dump(st, open(sp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    if st.get('stop_on') == today or all(st.get(k, {}).get('seen_on') == today for k in OBJ) or time.time() + STEP > end: break
    time.sleep(STEP)

# 3일치가 쌓이면 카카오톡으로 한 번 알린다(11/24 사용자 요청). 글은 notify.txt, 보낸 뒤 다시 보내지 않게 state 에 표시
import csv
rows = list(csv.DictReader(open(lp, encoding='utf-8')))
days = sorted({r['published'] for r in rows})
if len(days) >= 3 and not st.get('notified'):
    hm = lambda x: x[11:16] if len(x) >= 16 else '?'
    def line(it):
        return ', '.join(f"{int(r['published'][8:])}일 " + (hm(r['first_seen']) + ' 전' if r['note'] else hm(r['prev_check']) + '~' + hm(r['first_seen'])) for r in rows if r['item'] == it)
    f, c = line(NAME['funds']), line(NAME['credit'])
    L = ['[금투협 공개 시각 ' + str(len(days)) + '일 통계]', '반대매매·예탁금: ' + f, '신용잔고: ' + ('같음' if c == f else c)]
    ok = [hm(r['first_seen']) for r in rows if not r['note']]
    if ok: L.append('가장 늦은 날 ' + max(ok) + '에 확인됨')
    open(os.path.join(OUT, 'notify.txt'), 'w', encoding='utf-8').write('\n'.join(L)[:195] + '\n')
    st['notified'] = today; json.dump(st, open(sp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    if os.environ.get('GITHUB_OUTPUT'): open(os.environ['GITHUB_OUTPUT'], 'a').write('send=1\n')
