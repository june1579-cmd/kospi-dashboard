#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""I1 인버스 가격 — 실제 ETF 일별 시세(네이버 금융 공개 차트 자료, 로그인 없음)를 받고, 못 받은 날은 코스피200 선물 수익으로 계산한 값으로 채운다.

출력: out/prices.pkl {'inv1': DataFrame(open, close, src), 'inv2': ..., 'meta'}  · data/etf_<코드>.csv (받은 시세를 저장해 다음에 못 받을 때 쓴다)
점검: 실제 시세의 하루 수익과 (−배수 × 선물 하루 수익)의 상관이 0.9 미만이면 시세가 이상한 것으로 보고 계산값만 쓴다.
"""
import ast
import json
import os
import pickle

import numpy as np
import pandas as pd

import inv_common as C

URL = 'https://api.finance.naver.com/siseJson.naver?symbol={code}&requestType=1&startTime=20090101&endTime={end}&timeframe=day'


def fetch(code, end):
    import requests
    r = requests.get(URL.format(code=code, end=end), headers={'User-Agent': 'Mozilla/5.0'}, timeout=30); r.raise_for_status()
    rows = ast.literal_eval(r.text.strip().replace('\n', '').replace('\t', ''))
    d = pd.DataFrame(rows[1:], columns=[str(x).strip() for x in rows[0]])
    d = d.rename(columns={'날짜': 'date', '시가': 'open', '고가': 'high', '저가': 'low', '종가': 'close', '거래량': 'volume'})[['date', 'open', 'high', 'low', 'close', 'volume']]
    d['date'] = pd.to_datetime(d['date'].astype(str)); return d[(d['open'] > 0) & (d['close'] > 0)].sort_values('date').reset_index(drop=True)


def synth(F, k):
    """선물 수익으로 만든 인버스 가격(하루마다 −k배, 연 보수 뺌)."""
    o = F['open'].values.astype(float); c = F['close'].values.astype(float); n = len(F); cs = np.full(n, np.nan); os_ = np.full(n, np.nan)
    st = int(np.argmax(np.isfinite(c))); cs[st] = 10000.0; os_[st] = 10000.0
    for i in range(st + 1, n):
        if not (np.isfinite(c[i]) and np.isfinite(c[i - 1]) and np.isfinite(o[i])): cs[i] = cs[i - 1]; os_[i] = cs[i - 1]; continue
        os_[i] = cs[i - 1] * (1 - k * (o[i] / c[i - 1] - 1)); cs[i] = cs[i - 1] * (1 - k * (c[i] / c[i - 1] - 1)) * (1 - C.FEE_YEAR / 250)
    return pd.DataFrame({'open': os_, 'close': cs}, index=F.index)


def main():
    D = pickle.load(open(os.path.join(C.UNI, 'out', 'panel.pkl'), 'rb')); F = D['P']['K200F']; idx = F.index
    end = idx[-1].strftime('%Y%m%d'); out = {}; meta = {}
    fr = F['close'].pct_change()
    for key, (code, name, k) in C.ETF.items():
        S = synth(F, k); note = ''; real = None; fp = os.path.join(C.DATA, f'etf_{code}.csv')
        try:
            real = fetch(code, end); real.to_csv(fp, index=False, encoding='utf-8'); note = '새로 받음'
        except Exception as e:
            note = f'못 받음({type(e).__name__})'
            if os.path.exists(fp): real = pd.read_csv(fp, parse_dates=['date']); note += ' → 저장해 둔 시세 사용'
        px = S.copy(); px['src'] = '계산'; corr = None; n_real = 0; adj = 0
        if real is not None and len(real) > 250:
            R = real.set_index('date')[['open', 'close']].reindex(idx).astype(float); rr = R['close'].pct_change(); m = rr.notna() & fr.notna()
            # 액면 병합·분할처럼 하루 수익이 선물과 4%p 넘게 어긋나는 날은 가격 단위가 바뀐 것으로 보고 그 앞 가격을 이어 맞춘다
            jump = m & ((rr - (-k * fr)).abs() > 0.04); adj = 0
            for d in R.index[jump.values][::-1]:
                f = (1 + rr[d]) / (1 - k * fr[d]); R.loc[R.index < d, ['open', 'close']] *= f; adj += 1
            if adj: rr = R['close'].pct_change(); m = rr.notna() & fr.notna()
            corr = float(np.corrcoef(rr[m], -k * fr[m])[0, 1]) if m.sum() > 100 else None
            if corr is not None and corr >= 0.9:
                ok = R['open'].notna() & R['close'].notna(); first = ok.idxmax()
                ok &= (R.index > first)                       # 첫날은 전날 종가가 없어 뺀다
                # 실제 시세 구간은 실제 값, 그 앞은 계산값을 실제 첫 종가에 이어 붙인다
                scale = R.loc[first, 'close'] / S.loc[first, 'close']; px[['open', 'close']] = S[['open', 'close']] * scale
                px.loc[ok, ['open', 'close']] = R.loc[ok, ['open', 'close']]; px.loc[ok, 'src'] = '실제'; n_real = int(ok.sum())
            else:
                note += f' · 시세 점검 탈락(상관 {corr}) → 계산값만 사용'
        out[key] = px
        meta[key] = dict(code=code, name=name, times=k, note=note, real_days=n_real, unit_changes=(adj if real is not None and len(real) > 250 else 0), real_from=(str(px.index[px['src'] == '실제'][0].date()) if n_real else None), corr_with_futures=None if corr is None else round(corr, 4),
                         eval_real_share=round(float((px['src'][px.index >= C.U.EVAL_START] == '실제').mean()), 3))
    out['meta'] = meta
    pickle.dump(out, open(os.path.join(C.OUT, 'prices.pkl'), 'wb'))
    json.dump(meta, open(os.path.join(C.OUT, 'prices_meta.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(json.dumps(meta, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
