# -*- coding: utf-8 -*-
"""새 평점 규칙 검증용 OpenDART 주요 재무 수집 (qv.yml 에서만 실행, 비밀값은 출력하지 않음)

받는 것: raw/dart_main_<연도>.csv.gz  (사업보고서, fnlttMultiAcnt, 연결·별도 모두)
  연도 2016·2019·2022·2025 → 각 파일에 당기·전기·전전기가 있어 2014~2025 를 덮음
  계정: 유동자산·유동부채·자산총계·부채총계·자본총계·매출액·영업이익·당기순이익
대상: dart_corps.csv.gz 의 상장 회사 중 2016-01 이후 주간 시세 파일에 한 번이라도 나온 종목
이미 받은 연도는 건너뜀.
"""
import os, sys, time, json
import numpy as np, pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__)); RAW = os.path.join(ROOT, 'raw')
SECRETS = [v for k, v in os.environ.items() if k.startswith('DKEY__') and v]
DART_NAME, DART_KEY = next(((k[6:], v) for k, v in sorted(os.environ.items()) if k.startswith('DKEY__') and v.strip()), ('', ''))
LOG = []
KEEP = {'유동자산': 'ca', '유동부채': 'cl', '자산총계': 'ta', '부채총계': 'tl', '자본총계': 'te',
        '매출액': 'rev', '수익(매출액)': 'rev', '영업수익': 'rev', '영업이익': 'op', '영업이익(손실)': 'op',
        '당기순이익': 'ni', '당기순이익(손실)': 'ni'}


def log(*a):
    s = ' '.join(str(x) for x in a)
    for v in SECRETS:
        if len(v) >= 4: s = s.replace(v, '***')
    print(s, flush=True); LOG.append(s)


def main():
    import requests
    key = DART_KEY.strip()
    log('DART 비밀값', ('이름 ' + DART_NAME) if key else '찾지 못함')
    if not key: return
    cp = pd.read_csv(os.path.join(RAW, 'dart_corps.csv.gz'), dtype=str)
    seen = set()
    for f in os.listdir(os.path.join(RAW, 'weekly')):
        seen |= set(pd.read_csv(os.path.join(RAW, 'weekly', f), dtype=str, usecols=['티커'])['티커'])
    codes = cp.loc[cp['stock_code'].isin(seen), 'corp_code'].drop_duplicates().tolist()
    log('대상 회사', len(codes), '주간 시세 종목', len(seen))
    BATCH = 20; t0 = time.time(); BUDGET = float(os.environ.get('QV_DART_MIN', '20')) * 60
    for y in (2025, 2022, 2019, 2016):           # 최근 연도부터(오늘 점수에 바로 쓰임)
        yf = os.path.join(RAW, f'dart_main_{y}.csv.gz'); pf = os.path.join(RAW, f'dart_main_{y}.partial.csv.gz')
        if os.path.exists(yf):
            log(y, '이미 있음'); continue
        rows, bad = [], 0; start = 0
        if os.path.exists(pf):
            old = pd.read_csv(pf, dtype=str); rows = old.drop(columns=['_next']).to_dict('records'); start = int(old['_next'].iloc[0]) if len(old) else 0
            log(y, '이어 받기', start, '/', len(codes))
        slow = []
        for i in range(start, len(codes), BATCH):
            if time.time() - t0 > BUDGET:
                d = pd.DataFrame(rows); d['_next'] = i; d.to_csv(pf, index=False, compression='gzip')
                log(y, '시간 한도 — 부분 저장', i, '/', len(codes), f'호출 평균 {np.mean(slow) if slow else -1:.1f}초'); return
            t1 = time.time()
            batch = ','.join(codes[i:i + BATCH]); js = {}
            for k in range(3):
                try:
                    js = requests.get('https://opendart.fss.or.kr/api/fnlttMultiAcnt.json',
                                      params={'crtfc_key': key, 'corp_code': batch, 'bsns_year': str(y), 'reprt_code': '11011'}, timeout=15).json()
                    break
                except Exception as e:
                    js = {'status': 'ERR', 'message': type(e).__name__}; time.sleep(3)
            slow.append(time.time() - t1)
            st = js.get('status')
            if (i - start) // BATCH < 3 or ((i - start) // BATCH) % 25 == 0:
                log(y, '묶음', i, st, f'{slow[-1]:.1f}초', f'누적 {(time.time() - t0) / 60:.1f}분')
            if i == start: log(y, '첫 호출', st, str(js.get('message', ''))[:60], f'{slow[-1]:.1f}초')
            if st == '000':
                for it in js.get('list', []):
                    nm = it.get('account_nm', '').replace(' ', '')
                    if nm in KEEP:
                        rows.append({'corp_code': it.get('corp_code'), 'stock_code': it.get('stock_code'), 'bsns_year': it.get('bsns_year'),
                                     'fs_div': it.get('fs_div'), 'acc': KEEP[nm], 'th': it.get('thstrm_amount'), 'fr': it.get('frmtrm_amount'), 'bf': it.get('bfefrmtrm_amount')})
            elif st != '013':
                bad += 1
                if st in ('020', '010', '011', '012', '901'):
                    log('중단(키·한도)', st, str(js.get('message', ''))[:80]); return
            time.sleep(0.15)
        pd.DataFrame(rows).to_csv(yf, index=False, compression='gzip')
        if os.path.exists(pf): os.remove(pf)
        log(y, '행', len(rows), '실패 묶음', bad, f'호출 평균 {np.mean(slow) if slow else -1:.1f}초', f'누적 {(time.time() - t0) / 60:.1f}분')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        import traceback; log(traceback.format_exc())
    finally:
        os.makedirs(os.path.join(ROOT, 'qv_out'), exist_ok=True)
        open(os.path.join(ROOT, 'qv_out', 'collect_log.txt'), 'w', encoding='utf-8').write('\n'.join(LOG))
