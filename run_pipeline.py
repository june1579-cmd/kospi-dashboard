# -*- coding: utf-8 -*-
"""run_pipeline.py — 평일 세 번 GitHub Actions 가 실행하는 전체 순서.
   08:31(tag 0831, 전 거래일 확정 + VKOSPI 반영 — 공개 저장소가 08:10~08:15 에 VKOSPI 를 넣으므로 들어올 때까지 최대 30분 기다림)
   15:37(tag 1540, 그날 종가·투자자별 잠정) · 20:37(tag 1840, 애프터마켓 20:00 마감 뒤 투자자별)
   1 수집(dashboard_collect.py) → 2 공개 저장소 받기 → 3 통합 원자료 엑셀 갱신(daily_update.py) → 4 대시보드 자료 재계산(pkg/reproduce.py)
   → 5 fx_daily·manifest → 6 보고문(report_signals.py) → 6b 그래프(make_chart.py) → 6c 웹판(build_web.py → docs/) → 7 카카오톡(kakao_send.py)
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
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
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

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--tag', default=''); ap.add_argument('--no-collect', action='store_true'); ap.add_argument('--no-kakao', action='store_true'); ap.add_argument('--days', type=int, default=12); ap.add_argument('--no-wait', action='store_true'); ap.add_argument('--collect-dir', default='', help='--no-collect 일 때 쓸 수집 폴더(없으면 수집 자료 없이 진행)')
    a = ap.parse_args(); now = dt.datetime.now(KST); today = now.date()
    tag = a.tag or ('0831' if now.time() < dt.time(12, 0) else '1540' if now.time() < dt.time(17, 30) else '1840')
    if tag == '0831' and not a.no_wait: wait_vkospi()
    os.makedirs('data/collect', exist_ok=True); os.makedirs('out', exist_ok=True); os.makedirs('report', exist_ok=True)
    # 1 수집
    cdir = f'data/collect/dashboard_{today:%Y%m%d}_{tag}'
    if a.no_collect: cdir = a.collect_dir          # 옛 수집 폴더를 모르고 쓰지 않도록
    if not a.no_collect:
        cmd = [sys.executable, 'dashboard_collect.py', '--days', str(a.days), '--out', 'data/collect', '--tag', tag]
        if tag == '1540': cmd.append('--allow-today')
        run(cmd, '1 수집', timeout=1500)
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
    man = {'run': f'{now:%Y-%m-%d %H:%M}', 'tag': tag, 'kospi_last': kl, 'kofia_last': summ.get('kofia_last'), 'vkospi_last': summ.get('vkospi_last'), 'night_last': summ.get('night_last'), 'errors': errors, 'files': {}}
    for f in sorted(glob.glob('out/*.csv')):
        b = open(f, 'rb').read(); man['files'][os.path.basename(f)[:-4]] = {'sha256': hashlib.sha256(b).hexdigest(), 'bytes': len(b), 'last_date': (str(pd.read_csv(f).iloc[-1, 0]) if len(b) else None)}
    json.dump(man, open('out/manifest.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    # 6 보고문
    ok6 = run([sys.executable, 'report_signals.py', '--out', 'out', '--report', 'report', '--tag', tag, '--summary', 'data/update_summary.json'], '6 보고문')
    # 새 자료가 없는 날(휴장 등): 18:40 에만 한 줄
    newdata = (kl == today.isoformat())
    if tag == '0831':
        lm = 'state/last_morning.txt'; prev_kl = open(lm).read().strip() if os.path.exists(lm) else ''
        newdata = bool(kl) and kl != prev_kl and (today - dt.date.fromisoformat(kl)).days <= 5
        if newdata: os.makedirs('state', exist_ok=True); open(lm, 'w').write(kl)
    # 6b 카카오톡용 그래프·중요 변동(새 자료가 있는 날 — 세 번 실행 모두)
    if os.path.exists('report/alerts.json'): os.remove('report/alerts.json')
    if newdata: run([sys.executable, 'make_chart.py', '--out', 'out', '--report', 'report', '--signals', 'report/latest.json', '--tag', tag], '6b 그래프')
    # 6c 웹판(GitHub Pages, docs/) 자료 — 매 실행(새 자료가 없어도 보고문·상태는 갱신)
    run([sys.executable, 'build_web.py', '--out', 'out', '--report', 'report', '--docs', 'docs'], '6c 웹판')
    if not newdata:
        note = f'[{today:%m/%d} {tag}] ' + ('새 자료 없음(휴장 다음 날 또는 이미 보냄)' if tag == '0831' else '오늘 자료 없음(휴장 또는 미공표)') + f' — 매수·매도 신호 판정 없음. 최신 코스피 {kl}'
        if errors: note += '\n오류: ' + ' | '.join(errors)[:120]
        if tag == '1840' or errors: open('report/kakao.txt', 'w', encoding='utf-8').write(note[:200] + '\n')
        else: open('report/kakao.txt', 'w', encoding='utf-8').write('')
    elif errors:
        msgs = open('report/kakao.txt', encoding='utf-8').read()
        open('report/kakao.txt', 'w', encoding='utf-8').write(msgs + '\n=====\n' + ('[오류] ' + ' | '.join(errors))[:200] + '\n')
    if errors: open('report/latest.md', 'a', encoding='utf-8').write('\n## 오류\n\n' + '\n'.join(f'- {e}' for e in errors) + '\n')
    # 7 카카오톡
    if not a.no_kakao and os.path.getsize('report/kakao.txt') > 0: run([sys.executable, 'kakao_send.py', '--file', 'report/kakao.txt'], '7 카카오톡', timeout=120)
    log('끝. 오류 ' + (str(errors) if errors else '없음'))
    return 0

if __name__ == '__main__':
    try: sys.exit(main())
    except Exception:
        traceback.print_exc(); sys.exit(1)
