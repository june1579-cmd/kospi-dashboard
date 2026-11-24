# -*- coding: utf-8 -*-
"""ai_board.py — AI 선행지표 경고판의 숫자 갱신·단계 계산·알림을 GitHub Actions 에서 한다(2026-11-24 시작).

 맡는 일(예전엔 Claude 예약 작업이 하루 세 번 손으로 하던 일)
   1) 숫자 측정값 10개를 원자료로 갱신
        원자료 파일 out/ai_feed.csv(같은 실행에서 ai_feed.py 가 바로 받음) → hy_oas · us_unemp · ramp_q · elec_cpi · sox_dd
        코스피 대시보드 원자료 out/*.csv(dashboard-update 가 받음)        → kospi_dd · vkospi · forced_liq · margin_dd · foreign20
      거시 5개(미국 10년물 · 하이일드 · WTI · 미국 실업률 · 투자자 예탁금), 종가표(market) · 신용(margin) · 반대매매(forced) 행, 값 이력(history)
   2) 기준일 점검 — 미국·한국 마지막 거래일 값이 들어왔는지 본다. 밀린 값은 옛 값을 '새 값'처럼 쓰지 않고
      ai_board/status.json 의 stale 에 적는다(Claude 예약 작업이 Alpha Vantage·Twelve Data 로 메우거나 '확인 불가'로 둔다).
   3) Claude 요청 반영 — Claude 예약 작업이 ai_board/request.json 에 넣은 뉴스·보도형 측정값·일정·수집 기록을 데이터 파일에 합친다.
      데이터 파일(docs/ai/data/*.json)은 이 스크립트만 쓴다(동시에 두 곳이 쓰다 충돌하는 일을 없앤다).
   4) 단계 계산(경고판 페이지와 같은 식)과 변동 판정 → alerts/ai_board.txt(카카오톡, 뉴스 없음) · status.json(Claude 알림용)
   5) 웹판 meta.json 갱신

 원칙: 원자료가 없거나 밀리면 추정으로 채우지 않는다. 숫자를 덮어쓸 때는 새 값의 기준일이 지금 값보다 같거나 새로울 때만 —
       Claude 가 더 새로운 값을 넣어 두었으면 그대로 둔다. 경계값·기간 조건·시나리오 확률은 바꾸지 않는다.
 사용: python ai_board.py [--trigger 설명]
"""
import argparse, csv, datetime as dt, hashlib, json, os, re, sys
from zoneinfo import ZoneInfo

import holidays
try:
    import requests
except ImportError:
    requests = None

KST, NY = ZoneInfo('Asia/Seoul'), ZoneInfo('America/New_York')
NOW = dt.datetime.now(KST)
STAMP = NOW.strftime('%Y-%m-%dT%H:%M:%S+09:00')
D = 'docs/ai/data'
REQ, STATE, STATUS, ALERT, META = 'ai_board/request.json', 'ai_board/state.json', 'ai_board/status.json', 'alerts/ai_board.txt', 'docs/ai/meta.json'
DATASETS = ['thresholds', 'indicators', 'market', 'margin', 'forced', 'macro', 'events', 'history', 'runs', 'news', 'scenarios', 'episodes']
STAGES = ['정상', '주의', '경고', '위험']
KOSPI_PEAK, KOSPI_PEAK_DATE = 9114.55, '2026-06-22'
GH_SRC = 'https://github.com/june1579-cmd/kospi-dashboard/tree/main/out'
BY = 'GitHub Actions(ai-board)'
JUMP = 10.0   # 하루 변동이 이 % 이상이면 보류

def log(m): print(f'[{dt.datetime.now(KST):%H:%M:%S}] {m}', flush=True)
def sgn(x, d=1): return f'{"−" if x < 0 else "+"}{abs(x):,.{d}f}'
def neg(x, d=1): return f'{"−" if x < 0 else ""}{abs(x):,.{d}f}'
def md(d): return f'{int(d[5:7])}.{int(d[8:10])}' if len(d) >= 10 else (f'{int(d[5:7])}월' if len(d) >= 7 else d)

def jload(p, default=None):
    try:
        with open(p, encoding='utf-8') as f: return json.load(f)
    except FileNotFoundError:
        return default

def jdump(p, obj):
    """내용이 같으면 파일을 다시 쓰지 않는다(웹판·대시보드에 바뀌지 않은 파일을 올리지 않도록)."""
    old = jload(p, None) if os.path.exists(p) else None
    if old is not None and old == obj: return False
    ind = 1
    if os.path.exists(p):                      # 원래 파일의 들여쓰기를 따른다
        for ln in open(p, encoding='utf-8').read().splitlines()[1:3]:
            sp = len(ln) - len(ln.lstrip(' '))
            if sp: ind = sp; break
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(obj, f, ensure_ascii=False, indent=ind)
    return True

def sha(p):
    with open(p, 'rb') as f: return hashlib.sha256(f.read()).hexdigest()

def rcsv(p):
    if not os.path.exists(p): return []
    with open(p, encoding='utf-8') as f: return list(csv.DictReader(f))

def fnum(x):
    try: return float(str(x).replace(',', ''))
    except (TypeError, ValueError): return None

# ── 거래일 ──────────────────────────────────────────────────────────────────
_NYSE = holidays.financial_holidays('NYSE', years=range(2024, 2029))
_KR = holidays.country_holidays('KR', years=range(2024, 2029))

def krx_closed(d):
    return d.weekday() >= 5 or d in _KR or (d.month == 12 and d.day == 31) or (d.month == 5 and d.day == 1)

def last_session(now, closed, done_hm):
    """now(현지 시각) 기준으로 '장이 끝나 값이 나왔어야 하는' 마지막 거래일."""
    d = now.date()
    if now.hour * 60 + now.minute < done_hm: d -= dt.timedelta(days=1)
    while closed(d): d -= dt.timedelta(days=1)
    return d

def prev_session(d, closed, n=1):
    for _ in range(n):
        d -= dt.timedelta(days=1)
        while closed(d): d -= dt.timedelta(days=1)
    return d

US_LAST = last_session(dt.datetime.now(NY), lambda d: d.weekday() >= 5 or d in _NYSE, 16 * 60 + 30)   # 뉴욕 16:30 뒤면 그날 종가가 있어야 함
KR_LAST = last_session(NOW, krx_closed, 16 * 60 + 10)       # 코스피 종가·VKOSPI 는 16:10 뒤면 있어야 함(15:43 수집 + 여유)
KR_FLOW_LAST = last_session(NOW, krx_closed, 20 * 60 + 40)  # 외국인 확정치는 20:40 뒤
KOFIA_LAST = prev_session(last_session(NOW, krx_closed, 17 * 60), krx_closed)   # 금투협 신용·반대매매는 다음 거래일 오후 공표

# ── 단계 계산(docs/ai/page.html 의 metric_pos·indicator_pos 와 같은 식) ────────────
def pos_of(r):
    if r.get('kind') == 'event':
        return {'정상': 0.5, '주의': 1.5, '경고': 2.5, '위험': 3.5}.get(r.get('band'))
    if r.get('cur') in (None, ''): return None
    sign = -1 if r.get('dir') == 'down' else 1
    xs = [sign * float(r[k]) for k in ('s0', 't1', 't2', 't3', 's4')]
    v = min(max(sign * float(r['cur']), xs[0]), xs[4])
    i = 0
    while i < 3 and v > xs[i + 1]: i += 1
    return i + (v - xs[i]) / (xs[i + 1] - xs[i])

def eff_of(r, p):
    if p is None: return None
    if r.get('role') == '보조': return min(p, 1.9)
    need, got = int(r.get('persist') or 0), int(r.get('streak') or 0)
    if p >= 2 and need > 1 and got < need: p = 1.99
    if p >= 3 and r.get('danger_rule') and not r.get('danger_on'): p = 2.99
    return p

def st(p): return None if p is None else STAGES[min(3, int(p))]

def evaluate(th):
    m = {}
    for r in th:
        p = pos_of(r); e = eff_of(r, p)
        m[r['key']] = {'no': r['no'], 'metric': r.get('metric', ''), 'pos': p, 'eff': e, 'stage': st(p),
                       'band': r.get('band'), 'danger_on': bool(r.get('danger_on'))}
    ind = {}
    for k, v in m.items():
        if v['eff'] is None: continue
        ind[v['no']] = max(ind.get(v['no'], -1), v['eff'])
    comp = sum(ind.values()) / len(ind) if ind else None
    cnt = {s: sum(1 for p in ind.values() if st(p) == s) for s in STAGES}
    return {'measures': m, 'indicators': {str(k): {'pos': round(p, 3), 'stage': st(p)} for k, p in sorted(ind.items())},
            'composite': {'pos': round(comp, 3) if comp is not None else None, 'stage': st(comp), 'counts': cnt}}

def near_of(r):
    p = pos_of(r)
    if p is None or r.get('kind') == 'event': return False
    i = min(3, int(p))
    return i < 3 and (i + 1 - p) <= 0.1

# ── 글 다루기 ────────────────────────────────────────────────────────────────
def split_top(s):
    out, depth, cur = [], 0, ''
    for ch in s:
        if ch in '(（': depth += 1
        elif ch in ')）': depth = max(0, depth - 1)
        if ch == ',' and depth == 0:
            out.append(cur.strip()); cur = ''
        else: cur += ch
    if cur.strip(): out.append(cur.strip())
    return out

def replace_segments(text, repl):
    """'코스피 …, SOX …, VKOSPI …' 처럼 쉼표로 이은 글에서 앞말이 같은 조각만 바꾼다(나머지는 그대로)."""
    segs = split_top(text or '')
    done = set()
    for i, s in enumerate(segs):
        for pre, new in repl.items():
            if new and s.startswith(pre):
                segs[i] = new; done.add(pre); break
    for pre, new in repl.items():
        if new and pre not in done: segs.append(new)
    return ', '.join(segs)

def auto_note(old, msg):
    rest = (old or '')
    if rest.startswith('[자동]'):
        rest = rest.split(' || ', 1)[1] if ' || ' in rest else ''
    return f'[자동] {msg}' + (f' || {rest}' if rest else '')

# ── 원자료 → 새 값 ───────────────────────────────────────────────────────────
def from_feed():
    feed = {r['key']: r for r in rcsv('out/ai_feed.csv')}
    out = {}
    for key, r in feed.items():
        v = fnum(r.get('value'))
        if v is None or not r.get('as_of'): continue
        out[key] = dict(value=v, as_of=r['as_of'], text=r.get('text', ''), src=r.get('url') or GH_SRC,
                        source=r.get('source', ''), fetched_at=r.get('fetched_at', ''), status=r.get('status', ''),
                        prev_value=r.get('prev_value', ''), prev_as_of=r.get('prev_as_of', ''))
    return out

def measures_from_sources(feed):
    """GitHub 가 맡는 측정값 → {key: {cur, cur_text, as_of, src}}"""
    new = {}
    for k in ('hy_oas', 'us_unemp', 'ramp_q', 'elec_cpi', 'sox_dd'):
        f = feed.get(k)
        if f: new[k] = dict(cur=f['value'], cur_text=f['text'], as_of=f['as_of'], src=f['src'])
    # 하루 ±10% 넘게 움직인 종가는 자동 반영하지 않고 Claude 대조를 기다린다(잘못 받은 값이 경보로 나가는 것을 막음)
    f = feed.get('sox_dd'); pv = fnum(f.get('prev_value')) if f else None
    if f and pv is not None:
        ch = ((1 + f['value'] / 100) / (1 + pv / 100) - 1) * 100
        if abs(ch) >= JUMP:
            ok, why = verify_jump('sox', f.get('prev_as_of'), f['as_of'], ch)
            if ok: new['sox_dd']['checked'] = f'하루 {sgn(ch)}% — {why}로 확인'
            else: new['sox_dd']['hold'] = f'SOX 하루 {sgn(ch)}%({f.get("prev_as_of")}→{f["as_of"]}) — {why}, 대조 전 보류'
    mk = [r for r in rcsv('out/market_daily.csv') if fnum(r.get('kospi'))]
    if mk:
        y26 = [fnum(r['kospi']) for r in mk if r['date'].startswith('2026')]
        peak = max([KOSPI_PEAK] + y26)
        r = mk[-1]; c = fnum(r['kospi']); v = (c / peak - 1) * 100
        new['kospi_dd'] = dict(cur=round(v, 2), cur_text=f'{neg(v)}%({md(r["date"])}, {c:,.2f})', as_of=r['date'], src=f'{GH_SRC}/market_daily.csv')
        if len(mk) > 1 and abs(c / fnum(mk[-2]['kospi']) - 1) * 100 >= JUMP:
            ch = (c / fnum(mk[-2]['kospi']) - 1) * 100
            ok, why = verify_jump('kospi', mk[-2]['date'], r['date'], ch)
            if ok: new['kospi_dd']['checked'] = f'하루 {sgn(ch)}% — {why}로 확인'
            else: new['kospi_dd']['hold'] = f'코스피 하루 {sgn(ch)}% — {why}, 대조 전 보류'
        vk = [x for x in mk if fnum(x.get('vkospi'))]
        if vk:
            x = vk[-1]
            new['vkospi'] = dict(cur=round(fnum(x['vkospi']), 2), cur_text=f'{fnum(x["vkospi"]):.1f}({md(x["date"])}, KRX)', as_of=x['date'], src=f'{GH_SRC}/market_daily.csv')
    lq = [r for r in rcsv('out/liq_daily.csv') if fnum(r.get('liq_eok')) is not None]
    if lq:
        r = lq[-1]; v = fnum(r['liq_eok']); rt = fnum(r.get('ratio_pct'))
        new['forced_liq'] = dict(cur=round(v, 2), cur_text=f'{v:,.0f}억 원({md(r["date"])}' + (f', 미수 대비 {rt:.1f}%)' if rt is not None else ')'),
                                 as_of=r['date'], src=f'{GH_SRC}/liq_daily.csv')
    cr = [r for r in rcsv('out/credit.csv') if fnum(r.get('credit_jo'))]
    if cr:
        win = cr[-252:]
        pk = max(win, key=lambda r: fnum(r['credit_jo']))
        r = cr[-1]; c, p = fnum(r['credit_jo']), fnum(pk['credit_jo']); v = (c / p - 1) * 100
        new['margin_dd'] = dict(cur=round(v, 2), cur_text=f'{neg(v)}%({md(r["date"])}, {c:.2f}조 원 / {md(pk["date"])} 정점 {p:.2f}조 원)',
                                as_of=r['date'], src=f'{GH_SRC}/credit.csv')
    fl = [r for r in rcsv('out/flows_daily.csv') if fnum(r.get('foreign_jo')) is not None]
    if len(fl) >= 20:
        w = fl[-20:]; s = sum(fnum(r['foreign_jo']) for r in w)
        prov = '잠정' in (w[-1].get('basis', '') + w[-1].get('source', ''))
        new['foreign20'] = dict(cur=round(s, 2), cur_text=f'{neg(s)}조 원({md(w[0]["date"])}~{md(w[-1]["date"])}' + (', 잠정 포함)' if prov else ')'),
                                as_of=w[-1]['date'], src=f'{GH_SRC}/flows_daily.csv')
    return new, (mk[-1] if mk else None), cr, lq

# ── 큰 변동 대조(하루 ±10% 이상일 때만) ─────────────────────────────────────
def _series_twelve(sym):
    key = os.environ.get('TWELVEDATA_API_KEY', '').strip()
    if not key or requests is None: return {}
    js = requests.get('https://api.twelvedata.com/time_series', params={'symbol': sym, 'interval': '1day', 'outputsize': 15, 'apikey': key}, timeout=30).json()
    return {v['datetime'][:10]: float(v['close']) for v in js.get('values', [])}

def _series_yahoo(sym):
    if requests is None: return {}
    js = requests.get(f'https://query1.finance.yahoo.com/v8/finance/chart/{sym}', params={'range': '1mo', 'interval': '1d'},
                      headers={'User-Agent': 'Mozilla/5.0'}, timeout=30).json()
    res = js['chart']['result'][0]
    tz = ZoneInfo(res.get('meta', {}).get('exchangeTimezoneName') or 'UTC')
    return {dt.datetime.fromtimestamp(t, tz).strftime('%Y-%m-%d'): c for t, c in zip(res['timestamp'], res['indicators']['quote'][0]['close']) if c}

def verify_jump(what, d0, d1, ch):
    """다른 출처의 같은 날 등락률이 같은 방향이고 3%p 안이면 확인으로 본다. → (확인 여부, 설명)"""
    try:
        src, ser = ('Twelve Data SOXX', _series_twelve('SOXX')) if what == 'sox' else ('야후 ^KS11', _series_yahoo('%5EKS11'))
        if d0 in ser and d1 in ser:
            c2 = (ser[d1] / ser[d0] - 1) * 100
            ok = (c2 > 0) == (ch > 0) and abs(c2 - ch) <= 3
            return ok, f'{src} 같은 기간 {sgn(c2)}%'
        return False, f'{src}에 {d0}·{d1} 값 없음'
    except Exception as e:
        return False, f'대조 실패({repr(e)[:80]})'

# ── 기준일 점검 ──────────────────────────────────────────────────────────────
def freshness(feed, new):
    """밀린 값 목록. level 'stale'(새 값이 있어야 하는데 없음) / 'lag'(원래 늦게 나오는 자료가 평소보다 늦음)."""
    out = []
    def chk(key, name, as_of, expect, level='stale', why=''):
        if as_of is None or as_of < expect:
            out.append(dict(key=key, name=name, as_of=as_of or '', expected=expect, level=level, why=why))
    us, us1 = US_LAST.isoformat(), prev_session(US_LAST, lambda d: d.weekday() >= 5 or d in _NYSE).isoformat()
    us3 = prev_session(US_LAST, lambda d: d.weekday() >= 5 or d in _NYSE, 3).isoformat()
    chk('sox_dd', 'SOX 종가', (new.get('sox_dd') or {}).get('as_of'), us, why='뉴욕 마지막 거래일 종가')
    chk('wti', 'WTI 근월물', (feed.get('wti') or {}).get('as_of'), us, why='뉴욕 마지막 거래일 정산가')
    chk('us10y', '미국 10년물(FRED)', (feed.get('us10y') or {}).get('as_of'), us3, 'lag', 'FRED 는 보통 1영업일 늦음 — 3영업일 넘게 밀릴 때만 표시')
    chk('hy_oas', '하이일드 스프레드(FRED)', (feed.get('hy_oas') or {}).get('as_of'), us3, 'lag', 'FRED 는 보통 1~2영업일 늦음 — 3영업일 넘게 밀릴 때만 표시')
    kr = KR_LAST.isoformat()
    chk('kospi_dd', '코스피 종가', (new.get('kospi_dd') or {}).get('as_of'), kr, why='한국 마지막 거래일 종가(16:10 뒤)')
    chk('vkospi', 'VKOSPI', (new.get('vkospi') or {}).get('as_of'), kr, why='한국 마지막 거래일 종가(16:10 뒤)')
    chk('foreign20', '외국인 순매수', (new.get('foreign20') or {}).get('as_of'), kr, why='한국 마지막 거래일(오후 잠정·저녁 확정)')
    kf = KOFIA_LAST.isoformat()
    chk('margin_dd', '신용융자 잔고(금투협)', (new.get('margin_dd') or {}).get('as_of'), kf, 'lag', '금투협은 다음 거래일 오후 공표')
    chk('forced_liq', '반대매매(금투협)', (new.get('forced_liq') or {}).get('as_of'), kf, 'lag', '금투협은 다음 거래일 오후 공표')
    for k, f in feed.items():
        if f.get('status') and f['status'] != '정상':
            out.append(dict(key=k, name=f'원자료 {k}', as_of=f.get('as_of', ''), expected='', level='fail', why=f['status'][:120]))
    return out

# ── Claude 요청 합치기 ────────────────────────────────────────────────────────
OWNED = {'hy_oas', 'us_unemp', 'ramp_q', 'elec_cpi', 'sox_dd', 'kospi_dd', 'vkospi', 'forced_liq', 'margin_dd', 'foreign20'}

def upsert(rows, row, keys):
    for i, r in enumerate(rows):
        if all(str(r.get(k)) == str(row.get(k)) for k in keys):
            rows[i] = {**r, **row}; return
    rows.append(row)

def apply_request(data, req, log_changes):
    th = {r['key']: r for r in data['thresholds']}
    for key, patch in (req.get('thresholds') or {}).items():
        if key not in th: log_changes.append(f'요청 무시: 없는 측정값 {key}'); continue
        bad = [f for f in patch if f in ('s0', 't1', 't2', 't3', 's4', 'dir', 'role', 'persist', 'period', 'danger_rule', 'key', 'no')]
        if bad: log_changes.append(f'요청 무시: {key} 의 {",".join(bad)}(경계·조건은 바꾸지 않음)')
        for f, v in patch.items():
            if f not in bad: th[key][f] = v
    ind = {str(r['no']): r for r in data['indicators']}
    for no, patch in (req.get('indicators') or {}).items():
        if str(no) in ind:
            for f, v in patch.items():
                if f not in ('no', 'stage', 'rank'): ind[str(no)][f] = v
    for item, patch in (req.get('macro') or {}).items():
        hit = next((r for r in data['macro'] if r['item'] == item or r['item'] == patch.get('rename_from')), None)
        row = {k: v for k, v in patch.items() if k != 'rename_from'}
        if hit: hit.update(row); hit['item'] = patch.get('item', item)
        else: data['macro'].append({'item': item, **row})
    if isinstance(req.get('news'), list): data['news'] = req['news']
    if isinstance(req.get('events'), list): data['events'] = req['events']
    for r in req.get('history_add') or []: upsert(data['history'], r, ('date', 'key'))
    for r in req.get('market_add') or []: upsert(data['market'], r, ('date', 'index'))
    for r in req.get('margin_add') or []: upsert(data['margin'], r, ('date',))
    for r in req.get('forced_add') or []: upsert(data['forced'], r, ('date',))

# ── 본 처리 ──────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--trigger', default='')
    a = ap.parse_args()
    data = {n: jload(f'{D}/{n}.json', []) for n in DATASETS}
    before_sha = {n: sha(f'{D}/{n}.json') for n in DATASETS if os.path.exists(f'{D}/{n}.json')}
    state = jload(STATE, {}) or {}
    req = jload(REQ, {}) or {}
    marker = str(req.get('marker') or '')
    new_req = bool(marker) and marker != state.get('last_marker')
    notes, changed, errors, held = [], [], [], []
    # 첫 동기화 전에는 데이터 파일을 쓰지 않는다: 그때까지의 원본은 claude.ai 대시보드이고, Claude 예약 작업이
    # 대시보드 파일을 저장소에 옮겨 놓고 request.json 에 sync_base: true 를 넣어 올리면 그때부터 이 스크립트가 맡는다.
    sync_now = new_req and bool(req.get('sync_base'))
    waiting = not state.get('synced') and not sync_now
    if sync_now:
        data = {n: jload(f'{D}/{n}.json', []) for n in DATASETS}
        notes.append('대시보드 파일로 기준 맞춤(sync_base) — 이번 실행부터 GitHub 가 데이터 파일을 맡음')
        state.pop('eval', None); state.pop('flags', None)

    if new_req:
        try: apply_request(data, req, notes)
        except Exception as e: errors.append(f'요청 반영 실패: {e!r}'[:200])

    feed = from_feed()
    new, mk_last, credit, liq = measures_from_sources(feed)
    th = {r['key']: r for r in data['thresholds']}
    for k, v in new.items():
        r = th.get(k)
        if r is None: continue
        old_as, old_cur = str(r.get('as_of') or ''), r.get('cur')
        if v.get('hold') and str(v['as_of']) > old_as:
            held.append(dict(key=k, name=r.get('metric', k), as_of=old_as, expected=str(v['as_of']), level='check',
                             why=v['hold'], value=v['cur'], text=v['cur_text']))
            notes.append(f'{k}: {v["hold"]}'); continue
        if old_as and str(v['as_of']) < old_as:
            notes.append(f'{k}: 원자료 기준일 {v["as_of"]} 이 지금 값({old_as})보다 이르다 — 지금 값 유지'); continue
        if str(v['as_of']) == old_as and old_cur is not None and abs(float(old_cur) - float(v['cur'])) < 1e-9 and r.get('cur_text') == v['cur_text']:
            continue
        r.update(cur=v['cur'], cur_text=v['cur_text'], as_of=v['as_of'], src=v['src'])
        if v.get('checked'): notes.append(f'{k}: {v["checked"]}')
        changed.append(f'{r.get("metric", k)} {old_cur if old_cur is not None else "—"}→{v["cur"]}({md(str(v["as_of"]))})')
        upsert(data['history'], {'date': v['as_of'], 'key': k, 'value': v['cur'], 'text': v['cur_text'], 'unit': r.get('unit', ''), 'src': v['src']}, ('date', 'key'))
    crwv = feed.get('crwv_px')
    if crwv and 'cds_coreweave' in th:
        r = th['cds_coreweave']; seg = f'코어위브 주가 {crwv["text"]}(보조, CDS 아님)'
        nt = r.get('note') or ''
        nt2 = re.sub(r'코어위브 주가 [^|]*?\(보조, CDS 아님\)', seg, nt) if '(보조, CDS 아님)' in nt else (nt + (' | ' if nt else '') + seg)
        if nt2 != nt: r['note'] = nt2

    # 거시
    mrow = {r['item']: r for r in data['macro']}
    def macro(item, value, as_of, msg):
        r = mrow.get(item)
        if r is None: return
        if str(r.get('as_of') or '')[:10] > as_of: return
        if r.get('value') == value and str(r.get('as_of') or '')[:10] == as_of: return
        changed.append(f'{item} {r.get("value")}→{value}({md(as_of)})')
        r.update(value=value, as_of=as_of, note=auto_note(r.get('note'), msg))
    for key, item, fmt in (('us10y', '미국 10년물 금리', lambda v: f'{v:.2f}%'), ('hy_oas', '미국 하이일드 스프레드', lambda v: f'{v:.2f}%'),
                           ('wti', 'WTI 유가', lambda v: f'{v:.2f}달러'), ('us_unemp', '미국 실업률', lambda v: f'{v:.1f}%')):
        f = feed.get(key)
        if f: macro(item, fmt(f['value']), f['as_of'], f'{f["source"]} {f["fetched_at"][:16]} 수집: {f["text"]}(직전 {f["prev_value"]}, {f["prev_as_of"]})')
    if credit and fnum(credit[-1].get('deposit_jo')):
        c = credit[-1]; p = credit[-2] if len(credit) > 1 else None
        dv = fnum(c['deposit_jo']); dd = (dv - fnum(p['deposit_jo'])) if p and fnum(p.get('deposit_jo')) else None
        macro('투자자 예탁금', f'{dv:.1f}조 원', c['date'], f'금투협 원자료(코스피 대시보드 out/credit.csv) {dv:.3f}조 원' + (f'(하루 {sgn(dd, 2)}조 원)' if dd is not None else ''))

    # 종가·신용·반대매매 행
    def add_rows(ds, rows, keys):
        have = {tuple(str(r.get(k)) for k in keys) for r in data[ds]}
        n = 0
        for row in rows:
            t = tuple(str(row.get(k)) for k in keys)
            if t not in have: data[ds].append(row); have.add(t); n += 1
            else:
                for r in data[ds]:
                    if tuple(str(r.get(k)) for k in keys) == t and r != {**r, **row}: r.update(row); n += 1
        return n
    last_k = max([r['date'] for r in data['market'] if r.get('index') == 'KOSPI'] or [''])
    kos = [{'date': r['date'], 'index': 'KOSPI', 'close': fnum(r['kospi'])} for r in rcsv('out/market_daily.csv') if fnum(r.get('kospi')) and r['date'] >= last_k
           and not ((new.get('kospi_dd') or {}).get('hold') and r['date'] == new['kospi_dd']['as_of'])]
    n1 = add_rows('market', kos, ('date', 'index'))
    sx = feed.get('sox_dd'); m = re.search(r'\(\d+\.\d+, ([\d,]+\.\d+)\)', sx['text']) if sx else None
    if sx and m and not (new.get('sox_dd') or {}).get('hold'): n1 += add_rows('market', [{'date': sx['as_of'], 'index': 'SOX', 'close': fnum(m.group(1))}], ('date', 'index'))
    last_m = max([r['date'] for r in data['margin']] or [''])
    n2 = add_rows('margin', [{'date': r['date'], 'value': round(fnum(r['credit_jo']), 2)} for r in credit if r['date'] >= last_m], ('date',))
    last_f = max([r['date'] for r in data['forced']] or [''])
    n3 = add_rows('forced', [{'date': r['date'], 'value': round(fnum(r['liq_eok']), 2)} for r in liq if r['date'] >= last_f], ('date',))

    # 지표 표(7번·5번)의 숫자 조각
    ind = {str(r['no']): r for r in data['indicators']}
    T = lambda k: th[k]['cur_text'] if k in th and th[k].get('cur_text') else None
    if '7' in ind:
        short = lambda k, pre: f'{pre} {T(k)}' if T(k) else None
        rep = {'코스피': short('kospi_dd', '코스피'), 'SOX': short('sox_dd', 'SOX'),
               'VKOSPI': (f'VKOSPI {th["vkospi"]["cur_text"].replace(", KRX)", ")")}' if T('vkospi') else None),
               '반대매매': (f'반대매매 {th["forced_liq"]["cur_text"].split(", 미수")[0].rstrip(")")})' if T('forced_liq') else None),
               '신용잔고': (f'신용잔고 정점 대비 {th["margin_dd"]["cur_text"].split("(")[0]}({md(str(th["margin_dd"]["as_of"]))})' if T('margin_dd') else None),
               '외국인': (f'외국인 20일 {th["foreign20"]["cur_text"].split("(")[0]}({md(str(th["foreign20"]["as_of"]))}' + (', 잠정 포함)' if '잠정' in T('foreign20') else ')') if T('foreign20') else None)}
        nv = replace_segments(ind['7'].get('value', ''), rep)
        if nv != ind['7'].get('value'):
            ind['7']['value'] = nv
            ind['7']['as_of'] = max(str(th[k]['as_of']) for k in ('kospi_dd', 'sox_dd', 'vkospi', 'foreign20') if k in th)
    if '5' in ind and T('us_unemp'):
        nv = replace_segments(ind['5'].get('value', ''), {'미국 실업률': f'미국 실업률 {T("us_unemp")}'})
        if nv != ind['5'].get('value'): ind['5']['value'] = nv

    # 기준일 점검
    stale = [x for x in freshness(feed, new) if x['key'] not in {h['key'] for h in held}] + held
    for s in stale: log(f'밀림[{s["level"]}] {s["name"]}: {s["as_of"]} < {s["expected"]} {s["why"]}')

    # 단계·변동
    ev_new = evaluate(data['thresholds'])
    ev_old = state.get('eval') or evaluate(jload(f'{D}/thresholds.json', []))
    alerts = []
    if ev_old['composite']['stage'] != ev_new['composite']['stage']:
        alerts.append(('단계', f'종합 {ev_old["composite"]["stage"]}→{ev_new["composite"]["stage"]}'))
    names = {str(r['no']): r.get('name', '') for r in data['indicators']}
    for no, v in ev_new['indicators'].items():
        o = (ev_old['indicators'].get(no) or {}).get('stage')
        if o and o != v['stage']: alerts.append(('단계', f'{no}번 {names.get(no, "")} {o}→{v["stage"]}'))
    for k, v in ev_new['measures'].items():
        o = (ev_old['measures'].get(k) or {})
        if o.get('stage') and v['stage'] and o['stage'] != v['stage']:
            alerts.append(('측정값', f'{v["metric"]} {o["stage"]}→{v["stage"]}({th[k].get("cur_text", "").split("(")[0]})'))
        if o.get('band') and v['band'] and o['band'] != v['band']:
            alerts.append(('측정값', f'{v["metric"]} {o["band"]}→{v["band"]}'))
        if v['danger_on'] and not o.get('danger_on', False):
            alerts.append(('조건', f'{v["metric"]} 위험 전환 규칙 확인(danger_on)'))
    # 숫자로 판정하는 주시 조건(7절의 보조 주시 메모와 7번 위험 → A+5)
    flags = {}
    mdd, f20 = th.get('margin_dd', {}).get('cur'), th.get('foreign20', {}).get('cur')
    if mdd is not None and mdd <= -30: flags['신용 청산 진행'] = f'신용잔고 정점 대비 {neg(mdd)}%'
    hist20 = sorted((r for r in data['history'] if r.get('key') == 'foreign20' and r.get('value') is not None), key=lambda r: str(r['date']))
    if '신용 청산 진행' in flags and len(hist20) >= 6 and hist20[-1]['value'] > hist20[-6]['value']:
        flags['항복 완료 후보'] = f'외국인 20일 합 {neg(hist20[-6]["value"])}→{neg(hist20[-1]["value"])}조 원(5회 전 대비 개선)'
    if f20 is not None and mdd is not None and f20 <= -10 and mdd > -10: flags['고점 매도(바닥 아님)'] = f'외국인 20일 {neg(f20)}조 원·신용 {neg(mdd)}%'
    if ev_new['indicators'].get('7', {}).get('stage') == '위험': flags['A+5 조건(7번 위험)'] = '7번 SOX·코스피 위험 → 제안 25/34/25/16'
    old_flags = state['flags'] if 'flags' in state else dict(flags)   # 첫 실행은 지금 상태를 기준으로 삼는다(알림 없음)
    for k, v in flags.items():
        if k not in old_flags: alerts.append(('조건', f'{k} 새로 생김: {v}'))
    for k in old_flags:
        if k not in flags: alerts.append(('조건', f'{k} 풀림'))
    if new_req:
        for line in req.get('alert_extra') or []: alerts.append(('조건', str(line)))

    # 수집 기록(runs)
    fresh_note = '; '.join(f'{s["name"]} {s["as_of"] or "없음"}(기대 {s["expected"]})' for s in stale if s['level'] in ('stale', 'fail'))
    stage_txt = (', '.join(t for kind, t in alerts if kind == '단계') or
                 '변화 없음(' + '·'.join(f'{k} {v}' for k, v in [(k, ev_new['composite']['counts'][k]) for k in ('위험', '경고', '주의', '정상')] if v or k != '위험') + ')')
    if new_req:
        run = req.get('run') or {}
        cl = run.get('changed') or '없음'
        num = ', '.join(changed)
        data['runs'].append({'at': req.get('at') or STAMP, 'type': run.get('type') or req.get('kind') or '',
                             'changed': (cl if not num else f'{cl} | 숫자(GitHub): {num}'), 'stages': stage_txt,
                             'unverified': '; '.join(x for x in [run.get('unverified') or '', ('밀린 원자료: ' + fresh_note) if fresh_note else ''] if x) or '없음',
                             'proposals': '; '.join(x for x in [run.get('proposals') if run.get('proposals') not in (None, '', '없음') else '',
                                                                 '; '.join(f'{k}: {v}' for k, v in flags.items())] if x) or '없음',
                             'by': req.get('by') or 'Claude 예약 작업'})
    elif changed:
        data['runs'].append({'at': STAMP, 'type': '자동(숫자)', 'changed': ', '.join(changed), 'stages': stage_txt,
                             'unverified': ('밀린 원자료: ' + fresh_note) if fresh_note else '없음',
                             'proposals': '; '.join(f'{k}: {v}' for k, v in flags.items()) or '없음', 'by': BY})
    data['runs'] = data['runs'][-400:]

    if waiting:
        notes.append('첫 동기화 전 — 계산만 하고 데이터 파일·알림은 쓰지 않음')
        jdump(STATUS, {'built_at': STAMP, 'trigger': a.trigger, 'marker': state.get('last_marker', ''), 'request_applied': False,
                       'waiting_sync': True, 'ok': not errors, 'errors': errors, 'notes': notes,
                       'us_last_session': US_LAST.isoformat(), 'kr_last_session': KR_LAST.isoformat(),
                       'stale': stale, 'changed': changed, 'files_changed': [], 'files': before_sha,
                       'composite': ev_new['composite'], 'indicators': ev_new['indicators'], 'flags': flags,
                       'alert': {'text': '', 'kakao': 'none'}})
        state['last_build'] = STAMP; jdump(STATE, state)
        log('첫 동기화 전이라 데이터 파일을 쓰지 않음. 바뀔 값: ' + ('; '.join(changed) or '없음'))
        return

    # 저장
    if sync_now: state['synced'] = STAMP
    for n in DATASETS:
        if n in data and (data[n] or os.path.exists(f'{D}/{n}.json')): jdump(f'{D}/{n}.json', data[n])
    after_sha = {n: sha(f'{D}/{n}.json') for n in DATASETS if os.path.exists(f'{D}/{n}.json')}
    files_changed = [n for n in DATASETS if after_sha.get(n) != before_sha.get(n)]

    meta = jload(META, {}) or {}
    if files_changed: meta['exported_at'] = STAMP
    meta.setdefault('datasets', {})
    for n in files_changed:
        e = meta['datasets'].setdefault(n, {})
        e.update(updated_at=STAMP, updated_by=(req.get('by') or 'Claude 예약 작업') + ' + ' + BY if new_req else BY,
                 version=int(e.get('version') or 0) + 1, rows=len(data[n]))
    jdump(META, meta)

    # 카카오톡 글(뉴스 없음) — 단계·측정값·조건 변화가 있을 때만
    kakao, alert_text = 'none', ''
    if alerts:
        c = ev_new['composite']; cnt = c['counts']
        cnt_txt = '·'.join(f'{k} {cnt[k]}' for k in ('위험', '경고', '주의', '정상') if cnt[k] or k != '위험')
        lines = [f'[AI 경고판 {NOW.month}/{NOW.day} {NOW:%H:%M}] 종합 {c["pos"]:.2f} {c["stage"]} ({cnt_txt})',
                 '단계: ' + (', '.join(t for k, t in alerts if k == '단계') or '지표 단계 변화 없음')]
        ms = ', '.join(t for k, t in alerts if k == '측정값'); cd = ', '.join(t for k, t in alerts if k == '조건')
        if ms: lines.append('측정값: ' + ms)
        if cd: lines.append('조건: ' + cd)
        if changed: lines.append('원인: ' + changed[0])
        alert_text = '\n'.join(lines)
        body = '\n'.join(lines[1:])
        prev = open(ALERT, encoding='utf-8').read() if os.path.exists(ALERT) else ''
        prev_body = '\n'.join(prev.splitlines()[1:]).split('\n원인:')[0]
        if body.split('\n원인:')[0] == prev_body:
            kakao = 'duplicate'
        else:
            # 200자 넘으면 ===== 로 나눈다(최대 2통)
            msg, cur = [], ''
            for ln in lines:
                if len(cur) + len(ln) + 1 > 195 and cur: msg.append(cur.rstrip('\n')); cur = ''
                cur += ln + '\n'
            if cur: msg.append(cur.rstrip('\n'))
            os.makedirs('alerts', exist_ok=True)
            with open(ALERT, 'w', encoding='utf-8') as f: f.write('\n=====\n'.join(msg[:2]) + '\n')
            kakao = 'written'

    log_alerts = (state.get('alerts_log') or [])
    if alert_text: log_alerts.append({'at': STAMP, 'text': alert_text, 'kakao': kakao})
    state.update(eval=ev_new, flags=flags, alerts_log=log_alerts[-60:], last_build=STAMP)
    if new_req: state['last_marker'] = marker
    jdump(STATE, state)

    status = {'built_at': STAMP, 'trigger': a.trigger, 'marker': marker if new_req else state.get('last_marker', ''),
              'request_applied': new_req, 'ok': not errors, 'errors': errors, 'notes': notes,
              'us_last_session': US_LAST.isoformat(), 'kr_last_session': KR_LAST.isoformat(),
              'stale': stale, 'changed': changed, 'files_changed': files_changed,
              'files': {n: after_sha[n] for n in after_sha},
              'composite': ev_new['composite'], 'indicators': ev_new['indicators'],
              'near': [k for k, r in th.items() if near_of(r)], 'flags': flags,
              'alert': {'text': alert_text, 'kakao': kakao}}
    jdump(STATUS, status)
    log(f'완료: 바뀐 값 {len(changed)} · 바뀐 파일 {files_changed} · 밀림 {len([s for s in stale if s["level"] != "lag"])} · 알림 {kakao}')
    for x in changed: log('  ' + x)
    if errors:
        for e in errors: log('오류: ' + e)
        sys.exit(1)

if __name__ == '__main__':
    main()
