# -*- coding: utf-8 -*-
"""run_pipeline.py — 평일 세 번 GitHub Actions 가 실행하는 전체 순서.
   08:31(tag 0831, 전 거래일 확정 + VKOSPI 반영 — 공개 저장소가 08:10~08:15 에 VKOSPI 를 넣으므로 들어올 때까지 최대 30분 기다림)
   15:37(tag 1540, 그날 종가·투자자별 잠정) · 20:37(tag 1840, 애프터마켓 20:00 마감 뒤 투자자별)
   1 수집(dashboard_collect.py) → 2 공개 저장소 받기 → 3 통합 원자료 엑셀 갱신(daily_update.py) → 4 대시보드 자료 재계산(pkg/reproduce.py)
   → 4b 애프터마켓(after_market.py) → 5 fx_daily·manifest → 6 보고문(report_signals.py) → 6b 그래프(make_chart.py) → 6c 웹판(build_web.py → docs/) → 7 카카오톡(kakao_send.py)
   어느 단계가 실패해도 다음 단계로 가고, 실패 내용은 report/latest.md 와 카카오톡에 적는다.
   사용: python run_pipeline.py --tag 0831|1540|1840 [--no-collect] [--no-kakao] [--no-wait]
"""
import argparse, datetime as dt, glob, hashlib, json, os, shutil, subprocess, sys, traceback
import pandas as pd

KST = dt.timezone(dt.timedelta(hours=9))
ROOT = os.path.dirname(os.path.abspath(__file__)); os.chdir(ROOT)
WB = 'data/통합_원자료.xlsx'; PUB = 'data/public'; PUB_URL = 'https://github.com/Jaey27/kr-flow-dashboard.git'
errors = []
def log(m): print(f'[{dt.datetime.now(KST):%H:%M:%S}] {m}', flush=True)
def run(cmd, name, timeout=1500):
    log(f'{name}: {" ".join(cmd)}')
    try: r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:      # 한 단계가 멈춰도 전체가 죽지 않게(2026-11-15): 오류로 적고 다음 단계로 간다 — 전에는 실행 전체가 끝나 그날 결과·알림이 통째로 빠졌다
        o = e.stdout; print((o.decode('utf-8', 'replace') if isinstance(o, bytes) else (o or ''))[-2000:])
        errors.append(f'{name} 실패: {timeout // 60}분 안에 끝나지 않아 중단'); return False
    if r.stdout: print(r.stdout[-4000:])
    if r.returncode != 0:
        print(r.stderr[-3000:]); errors.append(f'{name} 실패(코드 {r.returncode}): ' + (r.stderr.strip().splitlines()[-1] if r.stderr.strip() else '')); return False
    return True

def pub_sync():
    if os.path.isdir(os.path.join(PUB, '.git')): return run(['git', '-C', PUB, 'pull', '--ff-only', '-q'], '공개 저장소 pull')
    return run(['git', 'clone', '--depth', '1', '-q', PUB_URL, PUB], '공개 저장소 clone')
def pub_dates():
    """공개 저장소의 마지막 코스피 날짜와 마지막 VKOSPI 날짜"""
    try:
        ix = max(json.load(open(f'{PUB}/data/ledger/daum_index.json', encoding='utf-8'))['rows'])
        vk = max(json.load(open(f'{PUB}/data/ledger/krx_vkospi.json', encoding='utf-8'))['rows'])
        return ix, vk
    except Exception as e: return None, None
def wait_vkospi(limit_min=30, step_min=5):
    """아침 실행: 공개 저장소에 전 거래일 VKOSPI 가 들어올 때까지 5분 간격, 최대 30분 기다린다"""
    import time
    t0 = time.time()
    while True:
        pub_sync(); ix, vk = pub_dates()
        log(f'VKOSPI 확인: 공개 저장소 코스피 {ix} · VKOSPI {vk}')
        if ix and vk and vk >= ix: return True
        if time.time() - t0 >= limit_min * 60:
            errors.append(f'VKOSPI {ix} 미반영(공개 저장소 {vk}까지, {limit_min}분 기다림) — VKOSPI 신호 판정 보류'); return False
        time.sleep(step_min * 60)

def sess_day(d, t, tg):
    """실행이 속한 장 날짜. 확정(1840) 실행은 자정을 넘겨 06:00 전에 돌아도 전날 장의 것이다"""
    return d - dt.timedelta(days=1) if (tg == '1840' and t < dt.time(6, 0)) else d
def skip_reason(now, tag, manifest='out/manifest.json'):
    """늦게 도착한 옛 구분 실행이면 건너뛸 이유(글), 돌려야 하면 ''.
       구분마다 돌아도 되는 시간대: 아침 06:00~15:30 · 잠정 15:30~20:10 · 확정 20:10~다음 날 06:00.
       같은 '장 날짜'에 더 늦은 구분의 결과가 이미 있으면 건너뛴다 — 날짜는 달력 날짜가 아니라 장 날짜로 견준다
       (자정을 넘겨 끝난 확정 실행이 다음 날 아침·잠정 실행을 '오늘 더 늦은 구분이 있음'으로 막지 않도록)."""
    order = {'0831': 0, '1540': 1, '1840': 2}; t = now.time(); today = now.date()
    inwin = {'0831': dt.time(6, 0) <= t < dt.time(15, 30), '1540': dt.time(15, 30) <= t < dt.time(20, 10), '1840': t >= dt.time(20, 10) or t < dt.time(6, 0)}.get(tag, True)
    if not inwin: return f'{tag} 구분의 시간대가 아님(지금 {t:%H:%M} — 예약이 밀려 늦게 시작한 실행)'
    try:
        pm = json.load(open(manifest, encoding='utf-8')); prun = str(pm.get('run', '')); ptag = str(pm.get('tag', ''))
        pday = sess_day(dt.date.fromisoformat(prun[:10]), dt.time.fromisoformat(prun[11:16]), ptag)
        if pday == sess_day(today, t, tag) and order.get(ptag, -1) > order.get(tag, 9): return f'같은 장 날짜({pday:%m/%d})의 더 늦은 구분({ptag}, {prun[5:]}) 결과가 이미 있음'
    except Exception: pass
    return ''

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--tag', default=''); ap.add_argument('--no-collect', action='store_true'); ap.add_argument('--no-kakao', action='store_true'); ap.add_argument('--days', type=int, default=12); ap.add_argument('--no-wait', action='store_true'); ap.add_argument('--collect-dir', default='', help='--no-collect 일 때 쓸 수집 폴더(없으면 수집 자료 없이 진행)'); ap.add_argument('--no-kakao-record', action='store_true', help='카톡 보낸 기록을 남기지 않음(시험용)'); ap.add_argument('--force', action='store_true', help='늦게 도착한 옛 구분 실행도 건너뛰지 않고 돌린다(수동 재실행용)'); ap.add_argument('--attempt', type=int, default=1, help='같은 구분의 몇 번째 실행인지(1=본 실행, 2·3=재시도). 재시도는 이미 보낸 카톡을 다시 보내지 않고, 자료 없음 안내는 마지막 재시도만 보낸다')
    a = ap.parse_args(); now = dt.datetime.now(KST); today = now.date(); T0 = __import__('time').time()
    tag = a.tag or ('0831' if now.time() < dt.time(12, 0) else '1540' if now.time() < dt.time(17, 30) else '1840')
    # 늦게 도착한 옛 구분 실행은 건너뛴다(2026-11-15 추가): GitHub 예약이 몇 시간씩 밀려 '아침' 실행이 오후 16시에, '잠정' 실행이 밤 12시에 돌면서
    #   더 새로운 실행이 만든 보고문·manifest 를 옛 구분 이름으로 덮어썼다(11/9~13 매일). 같은 날 더 늦은 구분의 결과가 이미 있거나, 그 구분의 시간대가 지났으면 아무것도 고치지 않고 끝낸다.
    if not a.no_collect and not a.force:
        skip = skip_reason(now, tag)
        if skip:
            log(f'건너뜀 — {skip}. 자료·보고문·웹판을 고치지 않는다(억지로 돌리려면 --force)')
            if os.path.isdir('report'): open('report/kakao.txt', 'w', encoding='utf-8').write('')
            return 0
    if tag == '0831' and not a.no_wait: wait_vkospi(limit_min=30 if a.attempt <= 1 else 10)
    os.makedirs('data/collect', exist_ok=True); os.makedirs('out', exist_ok=True); os.makedirs('report', exist_ok=True)
    # 1 수집
    cdir = f'data/collect/dashboard_{today:%Y%m%d}_{tag}'
    if a.no_collect: cdir = a.collect_dir          # 옛 수집 폴더를 모르고 쓰지 않도록
    if not a.no_collect:
        cmd = [sys.executable, 'dashboard_collect.py', '--days', str(a.days), '--out', 'data/collect', '--tag', tag]
        if tag == '1540': cmd.append('--allow-today')
        run(cmd, '1 수집', timeout=2100 if tag == '1540' else 1500)      # 잠정 실행은 KRX 오늘 종가가 굳기를 16:04 까지 기다린다(dashboard_collect.wait_krx_final)
        for z in glob.glob('data/collect/*.zip'): os.remove(z)
        # 오래된 수집 폴더 정리(최근 6개만)
        olds = sorted(glob.glob('data/collect/dashboard_*'))[:-6]
        for o in olds: shutil.rmtree(o, ignore_errors=True)
    # 2 공개 저장소
    try:
        if os.path.isdir(os.path.join(PUB, '.git')): run(['git', '-C', PUB, 'pull', '--ff-only', '-q'], '2 공개 저장소 pull')
        else: run(['git', 'clone', '--depth', '1', '-q', PUB_URL, PUB], '2 공개 저장소 clone')
    except Exception as e: errors.append('2 공개 저장소: ' + repr(e))
    # 3 엑셀 갱신
    ok3 = run([sys.executable, 'daily_update.py', '--workbook', WB, '--collect', cdir if os.path.isdir(cdir) else '', '--public', PUB, '--run-tag', tag], '3 엑셀 갱신')
    summ = json.load(open('data/update_summary.json', encoding='utf-8')) if os.path.exists('data/update_summary.json') else {}
    # 4 재계산
    kl = summ.get('kospi_last') or str(pd.read_excel(WB, sheet_name='코스피_일별')['일자'].max())[:10]
    ok4 = run([sys.executable, 'pkg/reproduce.py', WB, 'out', '--trend-end', kl], '4 재계산', timeout=900)
    # 4b 애프터마켓(NXT 저녁 가격·세션별 거래대금·투자자별 → out/am_*.csv, data/after_market/ 누적) — 실패해도 다른 단계는 진행
    try: run([sys.executable, 'after_market.py', '--out', 'out', '--data', 'data/after_market', '--tag', tag], '4b 애프터마켓', timeout=1200)
    except Exception as e: errors.append('4b 애프터마켓: ' + repr(e))
    # 4c 공매도(2026-11-18 추가) — 확정 실행에서만: 최근 10거래일 중 아직 없는 전종목 공매도 거래·잔고를 날짜당 한 번씩, 최대 8번 조회(data/short/)
    #     재시도 실행(21:23·22:23)은 이미 받은 날짜를 건너뛰어 조회가 거의 없다. 접속이 막히면 2번째 오류에서 멈추고 '4c 공매도 실패'로 알림 「자료:」 줄에 나온다
    if tag == '1840':
        try: run([sys.executable, 'short_collect.py', '--mode', 'daily'], '4c 공매도', timeout=600)
        except Exception as e: errors.append('4c 공매도: ' + repr(e))
    # 5 fx_daily(참고_원달러 → 기준 파일 뒤 날짜 덧붙임) · manifest
    try:
        base = pd.read_csv('pkg/datasets/fx_daily.csv'); fx = pd.read_excel(WB, sheet_name='참고_원달러'); fx['일자'] = pd.to_datetime(fx['일자'])
        last = pd.to_datetime(base['date']).max(); add = fx[fx['일자'] > last]
        rows = [{'date': r['일자'].strftime('%Y-%m-%d'), 'usdkrw': r['원/달러(원)'], 'basis': '국제 현물 환율(뉴욕 마감 무렵) — 2026-10-23까지의 중간값과 기준이 약간 다름', 'source': '공개 수집 저장소 github.com/Jaey27/kr-flow-dashboard macro.json usdkrw'} for _, r in add.iterrows() if pd.notna(r['원/달러(원)'])]
        txt = open('pkg/datasets/fx_daily.csv', encoding='utf-8').read()
        if not txt.endswith('\n'): txt += '\n'
        if rows: txt += pd.DataFrame(rows).to_csv(index=False, header=False)
        open('out/fx_daily.csv', 'w', encoding='utf-8').write(txt)      # 기준 파일은 글자 그대로 두고 새 날짜 줄만 덧붙임
    except Exception as e: errors.append('5 fx_daily: ' + repr(e))
    # 5a 연구소 통과 신호(2026-11-22 추가): deriv-research 가지의 deriv/lab/signals/passed_signals.csv(조건일·매수일·매도일)를 그대로 받아 out/lab_sig.csv 로 —
    #     한눈에 보기 그래프의 원(조건)·반원(매수·매도) 표시용. 못 받으면 전에 받은 파일을 그대로 둔다(추정으로 채우지 않음).
    try:
        import urllib.request
        b = urllib.request.urlopen('https://raw.githubusercontent.com/june1579-cmd/kospi-dashboard/deriv-research/deriv/lab/signals/passed_signals.csv', timeout=30).read()
        if b.decode('utf-8').startswith('cond,'): open('out/lab_sig.csv', 'wb').write(b)
        else: errors.append('5a 연구소 신호: 파일 형식이 다름')
    except Exception as e: errors.append('5a 연구소 신호: ' + repr(e))
    # 5b 자료 점검(health_check.py): 수집 항목 실패·자료 멈춤·출처 간 불일치·과거 값 정정을 찾아 out/health.csv · report/health.json 에 적는다(알림 「자료:」 줄과 대시보드 「자료 상태」 칸)
    health = {}
    try:
        json.dump(errors, open('report/pipeline_errors.json', 'w', encoding='utf-8'), ensure_ascii=False)
        run([sys.executable, 'health_check.py', '--workbook', WB, '--out', 'out', '--report', 'report', '--collect', cdir if (cdir and os.path.isdir(cdir)) else '', '--summary', 'data/update_summary.json', '--tag', tag, '--public', PUB, '--pipeline-errors', 'report/pipeline_errors.json'], '5b 자료 점검', timeout=300)
        health = json.load(open('report/health.json', encoding='utf-8')) if os.path.exists('report/health.json') else {}
        if os.path.getmtime('report/health.json') < T0 - 5: health = {}          # 이번 실행이 쓴 파일이 아니면(점검 실패) 쓰지 않는다
    except Exception as e: errors.append('5b 자료 점검: ' + repr(e))
    if not health: errors.append('자료 점검 단계가 돌지 못함 — 자료 상태를 확인하지 못했음')
    herr = [e for e in health.get('errors', []) if not e.startswith('실행 단계 오류')]      # 단계 오류는 errors 에 이미 있다
    man = {'run': f'{now:%Y-%m-%d %H:%M}', 'tag': tag, 'kospi_last': kl, 'kofia_last': summ.get('kofia_last'), 'vkospi_last': summ.get('vkospi_last'), 'night_last': summ.get('night_last'), 'errors': errors + herr,
           'data_line': health.get('line') or ('오류 ' + str(len(errors)) + '건(자료 점검 실패)' if errors else '정상'), 'health': health.get('counts', {}), 'files': {}}
    for f in sorted(glob.glob('out/*.csv')):
        b = open(f, 'rb').read(); man['files'][os.path.basename(f)[:-4]] = {'sha256': hashlib.sha256(b).hexdigest(), 'bytes': len(b), 'last_date': (str(pd.read_csv(f).iloc[-1, 0]) if len(b) else None)}
    json.dump(man, open('out/manifest.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    man0_errors = list(man['errors']); line0 = man['data_line']
    def sync_man():
        """자료 점검(5b) 뒤 단계(보고문·그래프·웹판)에서 난 오류는 점검 결과에 없으므로 manifest 의 errors·data_line 에 따로 더한다
           — 게시 작업(Claude 예약 작업)의 알림 「자료:」 줄이 manifest 의 data_line 을 그대로 쓴다"""
        late = [e for e in errors if e not in man0_errors]
        if not late: return
        man['errors'] = man0_errors + late
        man['data_line'] = f'오류 {len(late)}건(실행 단계)' if line0 == '정상' else f'{line0} · 실행 오류 {len(late)}건'
        json.dump(man, open('out/manifest.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    # 6 보고문
    open('report/kakao.txt', 'w', encoding='utf-8').write('')      # 보고문 단계가 실패해도 지난 실행의 글이 다시 나가지 않게 먼저 비운다
    ok6 = run([sys.executable, 'report_signals.py', '--out', 'out', '--report', 'report', '--tag', tag, '--summary', 'data/update_summary.json'], '6 보고문')
    sync_man()
    # 새 자료가 없는 날(휴장 등): 18:40 에만 한 줄
    sday = sess_day(today, now.time(), tag)      # 자정을 넘겨 돈 확정 실행은 전날 장의 것 — 달력 날짜로 견주면 '오늘 자료 없음'으로 잘못 나간다
    newdata = (kl == sday.isoformat())
    if tag == '0831':
        lm = 'state/last_morning.txt'; prev_kl = open(lm).read().strip() if os.path.exists(lm) else ''
        # 아침 확정은 '전 거래일' 자료를 다음 날 아침에 보내는 것 — kl 이 오늘이면(예약이 오후로 밀려 그날 잠정 자료를 본 경우) 새 자료로 치지 않는다(11/6 16:06 밀린 실행이 11/9 아침 메시지를 삼킨 문제)
        newdata = bool(kl) and kl != prev_kl and 0 < (today - dt.date.fromisoformat(kl)).days <= 5
        if newdata: os.makedirs('state', exist_ok=True); open(lm, 'w').write(kl)
    # 6b 카카오톡용 그래프·중요 변동(새 자료가 있는 날 — 세 번 실행 모두)
    if os.path.exists('report/alerts.json'): os.remove('report/alerts.json')
    if newdata: run([sys.executable, 'make_chart.py', '--out', 'out', '--report', 'report', '--signals', 'report/latest.json', '--tag', tag], '6b 그래프')
    # 6c 웹판(GitHub Pages, docs/) 자료 — 매 실행(새 자료가 없어도 보고문·상태는 갱신)
    run([sys.executable, 'build_web.py', '--out', 'out', '--report', 'report', '--docs', 'docs'], '6c 웹판')
    sync_man()
    # 카톡은 구분(아침·잠정·확정)마다 그날 한 번만: state/kakao_sent.json 에 '코스피날짜_구분' 기록. 재시도 실행은 이미 보낸 것을 다시 보내지 않는다
    os.makedirs('state', exist_ok=True); ks_fn = 'state/kakao_sent.json'
    sent = json.load(open(ks_fn, encoding='utf-8')) if os.path.exists(ks_fn) else {}
    key = f'{kl}_{tag}'
    if newdata and tag != '0831' and sent.get(key):
        newdata_msg = False; log(f'카톡 {key} 이미 보냄 — 이번 실행은 자료·웹판만 갱신')
    else: newdata_msg = newdata
    if newdata_msg and not a.no_kakao_record:
        sent[key] = f'{now:%Y-%m-%d %H:%M}'; sent = dict(sorted(sent.items())[-60:]); json.dump(sent, open(ks_fn, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    if not newdata:
        note = f'[{sday:%m/%d} {tag}] ' + ('새 자료 없음(휴장 다음 날 또는 이미 보냄)' if tag == '0831' else '오늘 자료 없음(휴장 또는 미공표)') + f' — 매수·매도 신호 판정 없음. 최신 코스피 {kl}'
        if errors: note += '\n오류: ' + ' | '.join(errors)[:120]
        elif man.get('data_line') and man['data_line'] != '정상': note += '\n자료: ' + man['data_line'][:80]
        last_try = a.attempt >= 3            # 자료 없음 안내는 그 구분의 마지막 재시도에서만(앞 실행은 다음 시간에 다시 받아 볼 수 있으므로)
        if (tag == '1840' and last_try) or (errors and last_try): open('report/kakao.txt', 'w', encoding='utf-8').write(note[:200] + '\n')
        else: open('report/kakao.txt', 'w', encoding='utf-8').write('')
    elif not newdata_msg:
        open('report/kakao.txt', 'w', encoding='utf-8').write('')
    else:
        # 카톡 '자료:' 줄 채우기 — 자료 점검(5b) 결과: 정상 / 오류·정정·주의 건수와 짧은 이름. (2026-11-15 전에는 단계 오류만 봐서 수집 항목 실패·틀린 값이 「정상」으로 나갔다)
        real = [e for e in errors if not (e.startswith('VKOSPI') and '미반영' in e)]
        st = man['data_line'] if not (real and man['data_line'] == '정상') else f'오류 {len(real)}건(실행 단계)'
        txt = open('report/kakao.txt', encoding='utf-8').read().rstrip('\n')
        room = 200 - (len(txt) - len('@@DATA@@'))
        txt = txt.replace('@@DATA@@', st[:max(room, 6)])
        if not txt.strip(): txt = f'[{sday:%m/%d} {tag}] 보고문을 만들지 못해 신호 판정을 알리지 못함 — 대시보드에서 확인\n자료: {st}'[:200]      # 보고문 단계 실패(옛 글을 다시 보내지 않는다)
        # 둘째 통: 새로 생긴 문제(직전에 알린 것과 견줘)와 풀린 문제만 자세히. 계속되는 문제는 첫 통의 「자료:」 줄에 짧게만 나온다(매번 길게 되풀이하지 않음)
        hs_fn = 'state/health_state.json'; newi = health.get('new', []); res = health.get('resolved', [])
        det = [f"· {x['status']} {x['name']}: {x['note']}"[:96] for x in newi] + [f"· 해소 {x['name']}"[:60] for x in res] + ['· 오류 ' + e[:90] for e in real if not any(e[:20] in x.get('note', '') for x in newi)]
        if det: txt += '\n=====\n' + (f'[{today:%m/%d} 자료 점검]\n' + '\n'.join(det))[:200]
        if health and not a.no_kakao_record: json.dump({'at': f'{now:%Y-%m-%d %H:%M}', 'issues': health.get('issues', [])}, open(hs_fn, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        # 정정 알림(취소된 신호)을 이번 메시지에 실었으면 '알림' 표시 — 보내지 않는 실행(주말 수동 실행 등)에서는 표시하지 않아 다음 메시지에 실린다
        try:
            rt_fn = 'report/retractions.json'
            if os.path.exists(rt_fn) and not a.no_kakao_record:
                rt = json.load(open(rt_fn, encoding='utf-8')); ch = False
                for x in rt:
                    if not x.get('notified'): x['notified'] = f'{now:%Y-%m-%d %H:%M}'; ch = True
                if ch: json.dump(rt, open(rt_fn, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        except Exception as e: log('정정 알림 표시 실패 ' + repr(e))
        open('report/kakao.txt', 'w', encoding='utf-8').write(txt + '\n')
    if errors: open('report/latest.md', 'a', encoding='utf-8').write('\n## 오류\n\n' + '\n'.join(f'- {e}' for e in errors) + '\n')
    # 7 카카오톡
    if not a.no_kakao and os.path.getsize('report/kakao.txt') > 0: run([sys.executable, 'kakao_send.py', '--file', 'report/kakao.txt'], '7 카카오톡', timeout=120)
    log('끝. 오류 ' + (str(errors) if errors else '없음'))
    return 0

if __name__ == '__main__':
    try: sys.exit(main())
    except Exception:
        traceback.print_exc(); sys.exit(1)
