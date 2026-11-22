"""앞을 보는 실수 찾기용: 자료(deriv/data)의 마지막 N일을 잘라 낸다. 잘라 낸 자료로 다시 돌려도 그 전 날짜의 신호가 같아야 한다.
쓰기: python truncate.py 2025-11-20  (그 날짜 뒤 행을 지움). 시험용 작업 폴더에서만 돌린다 — 저장소에 올리지 않는다."""
import glob
import os
import sys

import pandas as pd

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'data')
cut = pd.Timestamp(sys.argv[1])
for p in sorted(glob.glob(os.path.join(DATA, '*.csv')) + glob.glob(os.path.join(DATA, '*.csv.gz'))):
    try:
        d = pd.read_csv(p, dtype=str, keep_default_na=False)
    except Exception as e:
        print('건너뜀', os.path.basename(p), repr(e)[:80]); continue
    col = next((c for c in d.columns if c.lstrip('﻿') in ('날짜', 'TRD_DD', 'BAS_DD', 'date', 'Date')), None)
    if col is None: print('날짜 열 없음', os.path.basename(p)); continue
    dt = pd.to_datetime(d[col].str.slice(0, 10).str.replace('/', '-'), errors='coerce')
    keep = dt.isna() | (dt <= cut)
    d[keep].to_csv(p, index=False, encoding='utf-8')
    print(os.path.basename(p), len(d), '→', int(keep.sum()))
