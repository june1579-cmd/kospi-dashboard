# -*- coding: utf-8 -*-
"""uswalls/occ.py — OCC 공식 미결제로 직전 장 마감 뒤 콜벽·풋벽 확정(SPY·QQQ·SPX). 워크플로 occ-walls 가 화~토 09:13 KST 에 시작해
OCC 가 직전 장을 반영할 때까지 10분마다 확인하고, 반영되면 계산해 카카오톡으로 보낸다(2026-11-24).

- 출처: OCC 시리즈 검색(marketdata.theocc.com/series-search, 무료·원천) — 만기·행사가별 콜·풋 미결제. 2026-11-24 시험에서 한국 16:58 에
  이미 11/23 장 마감 뒤 포지션이 들어 있었고(야후 장 전 값과 달라짐), OCC 미결제 보고서의 처리 시각은 11/23 20:13(시카고) — 한국 다음 날 오전 11시 무렵.
- '반영됐다'의 판정: 아침 스냅숏(07:40 추정에 쓴 야후 미결제 = 직전 장 '전' 포지션)과 OCC 값이 거래가 있던 계약의 30% 넘게 다르면 반영된 것으로 본다.
- 벽 계산은 walls.py 와 같다(감마×미결제, 현재가 ±10%, 만기 45일 안). 변동성은 아침 스냅숏(SPY·QQQ)의 만기별 등가격 값을 쓰고,
  SPX 는 SPY 의 만기별 값을 빌린다(같은 지수, 가장 가까운 만기). 현재가는 야후 종가.
- 결과: uswalls/occ_latest.json(웹판), uswalls/occ_kakao.txt(카톡), uswalls/data/occ_hist.csv.
"""
import datetime as dt
import glob
import json
import os
import sys
import time

import numpy as np
import pandas as pd
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import walls as W  # noqa: E402

ROOT = W.ROOT; DATA = W.DATA; SNAP = W.SNAP
OHIST = os.path.join(DATA, 'occ_hist.csv'); OLATEST = os.path.join(ROOT, 'occ_latest.json'); OKAKAO = os.path.join(ROOT, 'occ_kakao.txt')
ROOTS = {'SPY': ('SPY',), 'QQQ': ('QQQ',), 'SPX': ('SPX', 'SPXW')}
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36'}
LOOP_MIN = int(os.environ.get('OCC_LOOP_MIN', '330')); STEP = int(os.environ.get('OCC_STEP_SEC', '600'))
TEST = os.environ.get('USW_TEST') == '1'
OCOLS = ['session', 'sym', 'spot', 'cw_occ', 'pw_occ', 'cwoi_occ', 'pwoi_occ', 'pcr_occ', 'cw_est', 'pw_est', 'd_cw', 'd_pw', 'k_c_occ', 'k_p_occ', 'changed', 'found_kst']


def log(m): print(f'[{dt.datetime.now(W.KST):%H:%M:%S}] {m}', flush=True)


def occ_chain(sym):
    r = requests.get('https://marketdata.theocc.com/series-search', params={'symbolType': 'U', 'symbol': sym}, headers=UA, timeout=120)
    if r.status_code != 200 or len(r.content) < 2000: raise RuntimeError(f'OCC {sym} HTTP {r.status_code} · {len(r.content)}바이트')
    rows = []
    for line in r.text.splitlines():
        t = [x.strip() for x in line.split('\t') if x.strip() != '']
        if len(t) < 9 or not (t[1].isdigit() and len(t[1]) == 4): continue
        if t[0] not in ROOTS[sym]: continue                      # 조정 시리즈(2SPY 등) 빼기
        try:
            exp = f'{int(t[1]):04d}-{int(t[2]):02d}-{int(t[3]):02d}'; K = int(t[4]) + int(t[5]) / 1000
            co, po = int(t[7]), int(t[8])
        except Exception: continue
        rows += [(exp, 'C', K, co), (exp, 'P', K, po)]
    o = pd.DataFrame(rows, columns=['exp', 'cp', 'K', 'oi'])
    if len(o) < 200: raise RuntimeError(f'OCC {sym} 시리즈 {len(o)}개 — 형식이 바뀐 것 같음')
    return o.groupby(['exp', 'cp', 'K'], as_index=False)['oi'].sum()


def iv_map(snap, spot):
    return W.exp_iv(snap, spot) if snap is not None else {}


def with_iv(o, m):
    if not m: o = o.assign(iv=0.20); return o
    keys = sorted(m); ts = pd.to_datetime(pd.Series(keys))
    def near(e):
        i = int(np.argmin(np.abs((ts - pd.Timestamp(e)).dt.days.values))); return m[keys[i]]
    return o.assign(iv=o['exp'].map({e: near(e) for e in o['exp'].unique()}))


def spx_close(sess):
    import yfinance as yf
    h = yf.Ticker('^GSPC').history(period='15d', interval='1d', auto_adjust=False)
    idx = pd.to_datetime(h.index); idx = idx.tz_convert(W.NY).tz_localize(None) if idx.tz is not None else idx
    h.index = idx.normalize(); x = h[h.index == pd.Timestamp(sess)]
    if not len(x): raise RuntimeError(f'^GSPC {sess} 종가 없음')
    return float(x['Close'].iloc[-1]), float(h[h.index < pd.Timestamp(sess)]['Close'].iloc[-1])


def changed_share(occ, snap, sess):
    """아침 스냅숏(직전 장 전 포지션)과 OCC 가 다른 비율 — 직전 장에 거래가 있던 계약만."""
    s = snap[(pd.to_datetime(snap['exp']) > pd.Timestamp(sess)) & (snap['vol'] > 0)]
    m = s.merge(occ, on=['exp', 'cp', 'K'], suffixes=('_s', '_o'))
    return float((m['oi_s'] != m['oi_o']).mean()) if len(m) >= 50 else None, m


def main():
    now = dt.datetime.now(W.KST); H = W.load_hist()
    files = W.snap_files('SPY')
    if not files: print('아침 스냅숏 없음 — 끝'); return out('skip', '아침 스냅숏이 없어 비교할 장을 모름', now)
    sess = os.path.basename(files[-1])[4:-7]
    OH = pd.read_csv(OHIST, dtype={'session': str}) if os.path.exists(OHIST) else pd.DataFrame(columns=OCOLS)
    if not os.environ.get('OCC_FORCE') and len(OH[(OH.session == sess)]) >= 3:
        print(f'{sess} 장은 이미 확정함 — 끝(미국 휴장이거나 이미 보냄)'); return out('skip', f'{sess} 장은 이미 확정함', now, sess)
    snaps = {s: pd.read_csv(os.path.join(SNAP, f'{s}_{sess}.csv.gz'), dtype={'exp': str}) for s in ('SPY', 'QQQ') if os.path.exists(os.path.join(SNAP, f'{s}_{sess}.csv.gz'))}
    end = time.time() + LOOP_MIN * 60; found = None; occ = {}
    while True:
        try:
            o = occ_chain('SPY'); sh, _ = changed_share(o, snaps['SPY'], sess) if 'SPY' in snaps else (None, None)
            log(f'OCC SPY {len(o)}행 · 아침 스냅숏과 다른 비율 {sh}')
            if sh is not None and sh > 0.30: found = dt.datetime.now(W.KST); occ['SPY'] = o; break
        except Exception as e: log(f'OCC 읽기 실패 {e!r}')
        if time.time() + STEP > end: break
        time.sleep(STEP)
    if not found:
        return out('timeout', f'OCC 공식 미결제에 {sess} 장이 {now:%H:%M}~{dt.datetime.now(W.KST):%H:%M} 사이 반영되지 않음', now, sess, fail=True)
    res = {}; errs = []; spymap = iv_map(snaps.get('SPY'), float(snaps['SPY']['spot'].iloc[0])) if 'SPY' in snaps else {}
    for sym in ('SPY', 'QQQ', 'SPX'):
        try:
            o = occ[sym] if sym in occ else occ_chain(sym)
            hr = H[(H.sym == sym) & (H.session == sess)]
            if sym == 'SPX': spot, prev = spx_close(sess); est = None; m = spymap
            else:
                if not len(hr): raise RuntimeError(f'{sym} {sess} 아침 기록 없음')
                spot = float(hr.iloc[-1]['spot']); est = hr.iloc[-1]; m = iv_map(snaps.get(sym), spot)
            o = with_iv(o, m)
            Wc = W.walls(o, spot, sess, 'oi') or {}
            kc = kp = None; chg = None
            if sym in snaps:
                chg, mm = changed_share(o[['exp', 'cp', 'K', 'oi']], snaps[sym], sess)
                b = mm[(mm['K'] >= spot * (1 - W.BAND)) & (mm['K'] <= spot * (1 + W.BAND))]
                for cp in 'CP':
                    x = b[b.cp == cp]; v = x['vol'].sum()
                    val = float(np.clip((x['oi_o'] - x['oi_s']).sum() / v, -1, 1)) if v > 1000 else None
                    if cp == 'C': kc = val
                    else: kp = val
            row = {'session': sess, 'sym': sym, 'spot': round(spot, 2), 'cw_occ': Wc.get('cw'), 'pw_occ': Wc.get('pw'), 'cwoi_occ': Wc.get('cw_oi'), 'pwoi_occ': Wc.get('pw_oi'),
                   'pcr_occ': W.num(Wc.get('pcr'), 3), 'cw_est': (None if est is None or pd.isna(est['cw_est']) else float(est['cw_est'])),
                   'pw_est': (None if est is None or pd.isna(est['pw_est']) else float(est['pw_est'])), 'k_c_occ': W.num(kc, 3), 'k_p_occ': W.num(kp, 3),
                   'changed': W.num(chg, 3), 'found_kst': f'{found:%Y-%m-%d %H:%M}'}
            row['d_cw'] = None if row['cw_est'] is None or row['cw_occ'] is None else row['cw_occ'] - row['cw_est']
            row['d_pw'] = None if row['pw_est'] is None or row['pw_occ'] is None else row['pw_occ'] - row['pw_est']
            res[sym] = {'row': row, 'top_c': Wc.get('top_c'), 'top_p': Wc.get('top_p'), 'off_prev': (None if est is None else {'cw': W.num(est['cw_off']), 'pw': W.num(est['pw_off']), 'pcr': W.num(est['pcr_oi'], 3)})}
            log(f'{sym} 확정 {row}')
        except Exception as e: errs.append(f'{sym}: {e!r}'[:200]); log(f'{sym} 실패 {e!r}')
    if res and not TEST:
        OH = OH[~((OH.session == sess) & OH.sym.isin(list(res)))]
        OH = pd.concat([OH, pd.DataFrame([r['row'] for r in res.values()])], ignore_index=True).sort_values(['sym', 'session'])
        os.makedirs(DATA, exist_ok=True); OH[OCOLS].to_csv(OHIST, index=False)
    msgs = [msg(sym, r, found) for sym, r in res.items()]
    if errs: msgs.append(W.cut(f"[미국옵션 확정{' 시험' if TEST else ''}] 일부 실패 — " + ' / '.join(e.replace('RuntimeError(', '').rstrip(')') for e in errs)))
    return out('ok' if res and not errs else ('partial' if res else 'fail'), '', now, sess, res=res, errs=errs, msgs=msgs, found=found, fail=not res, OH=OH)


def msg(sym, r, found):
    w = r['row']; tag = ' 시험' if TEST else ''; d = pd.Timestamp(w['session'])
    def a(v, e):
        if e is None: return ''
        if v is None: return f' (아침 추정 {W.fk(e)})'
        d = v - e
        return ' (아침 추정 맞음)' if abs(d) <= 1 else f" (아침 추정 {W.fk(e)} → {'+' if d > 0 else '−'}{W.fk(abs(d))} 차이)"
    p = r.get('off_prev') or {}
    lines = [f"[미국옵션 확정 {d:%m/%d}장{tag}] {sym} {w['spot']:,.2f} · OCC 공식 미결제",
             f"콜벽 {W.fk(w['cw_occ'])}{a(w['cw_occ'], w['cw_est'])}", f"풋벽 {W.fk(w['pw_occ'])}{a(w['pw_occ'], w['pw_est'])}",
             f"풋/콜 미결제 {w['pcr_occ']:.2f}" + (f" (전날 {p['pcr']:.2f})" if p.get('pcr') is not None else '') if w['pcr_occ'] is not None else '풋/콜 확인 불가']
    if sym == 'SPX': lines.append('SPX 는 아침 추정 없이 공식값만')
    lines.append(f"OCC 반영 확인 {found:%H:%M} · 투자 권유 아님")
    return W.cut('\n'.join(lines))


def out(status, note, now, sess=None, res=None, errs=None, msgs=None, found=None, fail=False, OH=None):
    if OH is None: OH = pd.read_csv(OHIST, dtype={'session': str}) if os.path.exists(OHIST) else pd.DataFrame(columns=OCOLS)
    J = {'at_kst': f'{now:%Y-%m-%d %H:%M}', 'test': TEST, 'status': status, 'note': note, 'session': sess, 'found_kst': (f'{found:%Y-%m-%d %H:%M}' if found else None),
         'errors': errs or [], 'syms': res or {}, 'hist': json.loads(OH.tail(60).to_json(orient='records', force_ascii=False)) if len(OH) else []}
    if status in ('timeout',): msgs = [W.cut(f"[미국옵션 확정{' 시험' if TEST else ''}] {note} — 공식 확정은 밤 SpotGamma(23:45 전후)로 확인하세요")]
    J['msgs'] = msgs or []
    json.dump(J, open(OLATEST, 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=str)
    open(OKAKAO, 'w', encoding='utf-8').write('\n=====\n'.join(J['msgs']) + ('\n' if J['msgs'] else ''))
    for m in J['msgs']: print('---\n' + m + f'\n({len(m)}자)')
    o = os.environ.get('GITHUB_OUTPUT')
    if o: open(o, 'a').write(f"status={status}\nsend={'1' if J['msgs'] else '0'}\n")
    if fail and status != 'timeout': sys.exit(2)


if __name__ == '__main__':
    main()
