# -*- coding: utf-8 -*-
"""daily_update.py — 수집 결과(dashboard_collect.py CSV) + 공개 수집 저장소(kr-flow-dashboard) + FRED VIX 를 통합 원자료 엑셀에 합친다.
   규칙: 같은 날짜는 나중 자료 우선(잠정 → 확정으로 바뀌면 교체), 바뀐 칸은 「값_교체_기록」에, 들어온 파일은 「원본파일_목록」에 적는다.
         새 값이 빈칸이면 기존 값을 지우지 않는다. 추정으로 채우지 않는다(없는 칸은 빈칸).
   사용: python daily_update.py --workbook data/통합_원자료.xlsx --collect data/collect/dashboard_20261027_1840 --public data/public [--vix data/vix_fred.csv] [--run-tag 1840] [--out 파일]
"""
import argparse, glob, json, os, re, datetime as dt
import numpy as np, pandas as pd

KST = dt.timezone(dt.timedelta(hours=9))
changes, files_in = [], []
PUBSRC = '공개 수집 저장소 github.com/Jaey27/kr-flow-dashboard (다음 금융·금투협·KRX 원천)'

def isna(v):
    try: return v is None or (isinstance(v, float) and np.isnan(v)) or (not isinstance(v, str) and pd.isna(v))
    except Exception: return False
def differs(old, new):
    if isna(old) and isna(new): return False
    if isna(old) or isna(new): return True
    try: return abs(float(old) - float(new)) > 1e-9
    except Exception: return str(old) != str(new)
def num(v):
    try: return float(str(v).replace(',', ''))
    except Exception: return np.nan
def rd(p):
    if not p or not os.path.exists(p): return None
    try: df = pd.read_csv(p, encoding='utf-8-sig')
    except Exception: df = pd.read_csv(p)
    return df if len(df) else None
def dstr(d): return d.strftime('%Y-%m-%d') if hasattr(d, 'strftime') else str(d)
NOW = None
def cut(df, col, after=dt.time(15, 35)):
    """수집 파일의 오늘 줄은 15:35(정규장 마감 뒤) 이후 실행분만(야간선물은 06:10 이후: 전날 저녁장이 오늘 날짜로 표기됨), 미래 날짜 줄은 버린다."""
    if df is None: return None
    d = pd.to_datetime(df[col]).dt.date; today = NOW.date()
    keep = (d < today) | ((d == today) & (NOW.time() >= after))
    df = df[keep]
    return df if len(df) else None

def upsert(df, new, sheet, src_new, srccol='원본 파일', skip=(), force=False):
    """df 에 new(dict, '일자' 포함) 를 넣는다. 같은 날짜가 있으면 값이 다른 칸만 기록하고 교체(새 값이 빈칸이면 기존 값 유지)."""
    d = new['일자']; hit = df.index[df['일자'] == d]
    has_src = srccol in df.columns
    if len(hit):
        i = hit[0]; changed = False
        for c, v in new.items():
            if c == '일자' or c == srccol or c in skip or c not in df.columns: continue
            if isna(v): continue
            if differs(df.at[i, c], v):
                changes.append((sheet, dstr(d), c, df.at[i, c], (str(df.at[i, srccol])[:70] if has_src else ''), v, src_new)); df.at[i, c] = v; changed = True
        if (changed or force) and has_src: df.at[i, srccol] = src_new
        return df
    row = {c: new.get(c, np.nan) for c in df.columns}
    if has_src: row[srccol] = src_new
    return pd.concat([df, pd.DataFrame([row])], ignore_index=True)

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--workbook', required=True); ap.add_argument('--collect', default=''); ap.add_argument('--public', default='')
    ap.add_argument('--vix', default=''); ap.add_argument('--run-tag', default=''); ap.add_argument('--out', default=''); ap.add_argument('--now', default='')
    a = ap.parse_args(); now = pd.Timestamp(a.now).to_pydatetime().replace(tzinfo=KST) if a.now else dt.datetime.now(KST)
    global NOW; NOW = now
    tag = f'{now:%Y-%m-%d %H:%M}' + (f' {a.run_tag}' if a.run_tag else '')
    X = pd.read_excel(a.workbook, sheet_name=None); order = list(X.keys())
    NODATE = ('최초_요청문', '원본파일_목록', '값_교체_기록', '안내')
    for s in order:
        if '일자' in X[s].columns and s not in NODATE: X[s]['일자'] = pd.to_datetime(X[s]['일자'], errors='coerce')
    C = a.collect
    def f(pat):
        g = sorted(glob.glob(os.path.join(C, pat))) if C else []
        return g[-1] if g else None
    led, mac, lmeta = {}, None, {}
    if a.public and os.path.isdir(os.path.join(a.public, 'data', 'ledger')):
        for n in ['daum_index', 'krx_vkospi', 'daum_futures', 'daum_investor_kospi', 'daum_investor_kosdaq', 'freesis_kospi_market', 'krx_mcap', 'daum_stock_005930', 'naver_stock_005930', 'daum_stock_000660', 'naver_stock_000660', 'freesis_funds', 'freesis_credit']:
            p = os.path.join(a.public, 'data', 'ledger', n + '.json')
            if os.path.exists(p):
                _j = json.load(open(p, encoding='utf-8')); led[n] = _j.get('rows', {}); lmeta[n] = {'fetched_at': _j.get('fetched_at'), 'prov': list(_j.get('prov') or [])}
        mp = os.path.join(a.public, 'data', 'macro.json')
        if os.path.exists(mp): mac = json.load(open(mp, encoding='utf-8'))
    # ---------------- 1. 코스피_일별
    df = X['코스피_일별']; k = cut(rd(f('01_*.csv')), '날짜')
    if k is not None:
        k['날짜'] = pd.to_datetime(k['날짜']); src = f'자동 수집 01 코스피 일별시세(KRX 정보데이터시스템, pykrx, {tag})'
        for _, r in k.sort_values('날짜').iterrows():
            d = r['날짜']; prev = df[df['일자'] < d].sort_values('일자'); pc = prev.iloc[-1]['종가(pt)'] if len(prev) else np.nan
            new = {'일자': d, '종가(pt)': r['종가'], '대비(pt)': round(r['종가'] - pc, 2) if pd.notna(pc) else np.nan, '등락률(%)': round((r['종가'] / pc - 1) * 100, 2) if pd.notna(pc) else np.nan,
                   '시가(pt)': r['시가'], '고가(pt)': r['고가'], '저가(pt)': r['저가'], '거래량(천주)': int(round(r['거래량'] / 1000)), '거래대금(백만원)': int(round(r['거래대금'] / 1e6)),
                   '상장시가총액(백만원)': int(round(r['상장시가총액'] / 1e6))}
            df = upsert(df, new, '코스피_일별', src)
        files_in.append(('01', f'코스피 일별시세 {k["날짜"].min():%Y-%m-%d}~{k["날짜"].max():%Y-%m-%d}', '코스피_일별'))
    k1b = cut(rd(f('01b_*.csv')), '날짜')   # 15:40 실행에서 KRX 01 에 오늘 줄이 없을 때 다음 금융 종가만
    if k1b is not None:
        for _, r in k1b.iterrows():
            d = pd.to_datetime(r['날짜'])
            if (df['일자'] == d).any() or pd.isna(r['종가']): continue
            prev = df[df['일자'] < d].sort_values('일자'); pc = prev.iloc[-1]['종가(pt)'] if len(prev) else np.nan
            df = upsert(df, {'일자': d, '종가(pt)': r['종가'], '대비(pt)': round(r['종가'] - pc, 2) if pd.notna(pc) else np.nan, '등락률(%)': round((r['종가'] / pc - 1) * 100, 2) if pd.notna(pc) else np.nan},
                        '코스피_일별', '공개 시세(다음 금융 종가, 원천 KRX) — 시가·고가·저가·거래량 확인 불가, KRX 파일 오면 교체')
        files_in.append(('01b', '코스피 종가(다음 금융, KRX 파일에 오늘 줄 없을 때)', '코스피_일별'))
    if 'daum_index' in led:   # KRX 파일에 없는 날짜만 종가(공개 수집)로. 시가·고가·저가·거래량은 확인 불가 → 빈칸
        fm = led.get('freesis_kospi_market', {})
        for ds, r in sorted(led['daum_index'].items()):
            d = pd.Timestamp(ds)
            if (df['일자'] == d).any() or r.get('kospi') is None: continue
            prev = df[df['일자'] < d].sort_values('일자'); pc = prev.iloc[-1]['종가(pt)'] if len(prev) else np.nan
            m = fm.get(ds, {})
            new = {'일자': d, '종가(pt)': r['kospi'], '대비(pt)': round(r['kospi'] - pc, 2) if pd.notna(pc) else np.nan, '등락률(%)': round((r['kospi'] / pc - 1) * 100, 2) if pd.notna(pc) else np.nan,
                   '거래대금(백만원)': m.get('trade_value', np.nan), '상장시가총액(백만원)': m.get('mcap', np.nan)}
            df = upsert(df, new, '코스피_일별', '공개 수집(다음 금융 종가·금투협 증시동향 거래대금·시총, 원천 KRX) — 시가·고가·저가·거래량 확인 불가, KRX 파일 오면 교체')
    X['코스피_일별'] = df.sort_values('일자').reset_index(drop=True)
    last_k = X['코스피_일별']['일자'].max()
    # ---------------- 2. VKOSPI_일별
    df = X['VKOSPI_일별']; v10 = cut(rd(f('10_VKOSPI*.csv')), '일자')
    if v10 is not None:
        v10['일자'] = pd.to_datetime(v10['일자']); vsrc = str(v10['원본'].iloc[-1]) if '원본' in v10.columns else 'KRX'
        for _, r in v10.sort_values('일자').iterrows():
            d = r['일자']; prev = df[df['일자'] < d].sort_values('일자'); pc = prev.iloc[-1]['종가'] if len(prev) else np.nan
            new = {'일자': d, '종가': r['종가'], '대비': round(r['종가'] - pc, 2) if pd.notna(pc) else np.nan, '등락률(%)': round((r['종가'] / pc - 1) * 100, 2) if pd.notna(pc) else np.nan,
                   '시가': r.get('시가', np.nan), '고가': r.get('고가', np.nan), '저가': r.get('저가', np.nan)}
            prevsrc = str(df.loc[df['일자'] == d, '원본 파일'].iloc[0]) if (df['일자'] == d).any() else ''
            df = upsert(df, new, 'VKOSPI_일별', f'자동 수집 10 VKOSPI({vsrc}, {tag})', force=('확인 불가' in prevsrc))
        files_in.append(('10', f'VKOSPI 시가·고가·저가·종가({vsrc})', 'VKOSPI_일별'))
    if 'krx_vkospi' in led:
        for ds, r in sorted(led['krx_vkospi'].items()):
            d = pd.Timestamp(ds)
            if (df['일자'] == d).any() or d > last_k or r.get('vkospi') is None: continue
            prev = df[df['일자'] < d].sort_values('일자'); pc = prev.iloc[-1]['종가'] if len(prev) else np.nan
            new = {'일자': d, '종가': r['vkospi'], '대비': round(r['vkospi'] - pc, 2) if pd.notna(pc) else np.nan, '등락률(%)': round((r['vkospi'] / pc - 1) * 100, 2) if pd.notna(pc) else np.nan}
            df = upsert(df, new, 'VKOSPI_일별', '종가 KRX(공개 수집 저장소 kr-flow-dashboard krx_vkospi), 시가·고가·저가는 확인 불가 — KRX 파일 오면 교체')
    X['VKOSPI_일별'] = df.sort_values('일자').reset_index(drop=True)
    # ---------------- 3. 투자자별_코스피_일별 (잠정 → 확정 교체)
    df = X['투자자별_코스피_일별']; inv = rd(f('03_*거래대금*.csv'))
    if inv is None: inv = rd(f('03_*.csv'))
    inv = cut(inv, '날짜')
    if inv is not None:
        inv['날짜'] = pd.to_datetime(inv['날짜'])
        for _, r in inv.sort_values('날짜').iterrows():
            prelim = int(r.get('잠정', 0) or 0) == 1
            inst = r['금융투자'] + r['보험'] + r['투신'] + r['사모'] + r['은행'] + r['기타금융'] + r['연기금']
            new = {'일자': r['날짜'], '기관 합계(십억원)': round(inst / 1e9, 1), '기타법인(십억원)': round(r['기타법인'] / 1e9, 1), '개인(십억원)': round(r['개인'] / 1e9, 1),
                   '외국인 합계(십억원)': round((r['외국인'] + r.get('기타외국인', 0)) / 1e9, 1), '전체(십억원)': 0}
            hit = df.index[df['일자'] == r['날짜']]
            if len(hit) and prelim: continue                         # 이미 있는 날짜에 잠정치는 덮지 않음
            old_lbl = str(df.at[hit[0], '출처 구분']) if len(hit) else ''
            was_prelim = '잠정' in old_lbl; was_pub = old_lbl.startswith('공개')
            srcname = str(r['원본']) if '원본' in inv.columns and isinstance(r['원본'], str) and r['원본'] else 'KRX 투자자별 거래실적'
            label = '잠정치(KRX 장 마감 직후, 18시 확정 전; 다음 금융 경유)' if prelim else '사용자 첨부(KRX 확정치, pykrx 자동 수집)'
            df = upsert(df, new, '투자자별_코스피_일별', f'자동 수집 03 투자자별({srcname} {"잠정" if prelim else "확정"}치, {tag})', force=(was_prelim or was_pub))
            i = df.index[df['일자'] == r['날짜']][0]
            if not prelim and was_prelim: changes.append(('투자자별_코스피_일별', dstr(r['날짜']), '출처 구분', old_lbl, '잠정치', label, tag))
            df.at[i, '출처 구분'] = label           # KRX 파일이 덮은 날짜는 출처 구분을 KRX 확정(또는 잠정)으로
        files_in.append(('03', '코스피 투자자별 순매수 거래대금(KRX; 당일 잠정치는 다음 금융)', '투자자별_코스피_일별'))
    if 'daum_investor_kospi' in led:   # 공개 수집(다음 금융, 억원 → 십억원). 같은 날 값(15:40 잠정·18시 집계)은 다음 날 아침에 한 번 더 바뀌고,
        # 그 다음 날 아침 값이 KRX 확정치와 같다(2026-10-20~26 pykrx KRX 파일과 대조해 5일 모두 일치, 18시 집계 값은 최대 ±400억 달랐음).
        # 그래서 KRX 파일 값(출처 '사용자 첨부…')이 아닌 날짜는 저장소 값이 바뀔 때마다 교체하고, 다음 날 06시 이후 받은 값만 확정으로 적는다.
        mt = lmeta.get('daum_investor_kospi', {}); fa = None
        try:
            fa = pd.Timestamp(mt['fetched_at']) if mt.get('fetched_at') else None
            if fa is not None and fa.tzinfo is not None: fa = fa.tz_convert('Asia/Seoul').tz_localize(None)
        except Exception: fa = None
        prov = set(mt.get('prov') or [])
        for ds, r in sorted(led['daum_investor_kospi'].items()):
            d = pd.Timestamp(ds)
            if d > last_k or r.get('inst') is None: continue
            final = fa is not None and ds not in prov and fa >= d + pd.Timedelta(days=1, hours=6)
            lbl = ('공개 수집(다음 금융, 다음 날 아침 값 = KRX 확정치)' if final else
                   '공개 수집 잠정치(다음 금융 18시 집계 — 다음 날 아침 확정치로 교체)' if (fa is not None and ds not in prov and fa >= d + pd.Timedelta(hours=18)) else
                   '공개 수집 잠정치(다음 금융 장 마감 직후 — 다음 날 아침 확정치로 교체)')
            hit = df.index[df['일자'] == d]
            if len(hit):
                old_lbl = str(df.at[hit[0], '출처 구분'])
                if old_lbl.startswith('사용자 첨부'): continue                 # KRX 파일 값은 그대로(다음 실행의 pykrx 재수집이 고침)
                if '다음 날 아침' in old_lbl and '교체' not in old_lbl and not final: continue   # 확정된 값은 확정 전 값으로 덮지 않음
            new = {'일자': d, '기관 합계(십억원)': round(r['inst'] / 10, 1), '기타법인(십억원)': round(r['etc_corp'] / 10, 1) if r.get('etc_corp') is not None else np.nan, '개인(십억원)': round(r['indiv'] / 10, 1),
                   '외국인 합계(십억원)': round(r['foreign'] / 10, 1), '전체(십억원)': 0, '출처 구분': lbl}   # 다음 금융 foreign 은 기타외국인을 이미 포함한 합계(KRX 파일과 대조 확인)
            df = upsert(df, new, '투자자별_코스피_일별', '공개 수집 자료(다음 금융, 원천 KRX' + (' 확정치 — 다음 날 아침 값' if final else ' 잠정치') + f', 저장소 {fa:%m/%d %H:%M} 수집)' if fa is not None else '공개 수집 자료(다음 금융, 원천 KRX)', force=True)
    X['투자자별_코스피_일별'] = df.sort_values('일자').reset_index(drop=True)
    # ---------------- 4. 금투협 두 시트
    L = X['증시자금추이_금투협']; cols = list(L.columns); l7 = rd(f('07_*.csv'))
    if l7 is not None:
        l7['일자'] = pd.to_datetime(l7['일자'].astype(str))
        for _, r in l7.sort_values('일자').iterrows():
            new = dict(zip(cols[1:7], [num(r['TMPV2']), num(r['TMPV3']), num(r['TMPV4']), num(r['TMPV5']), num(r['TMPV6']), num(r['TMPV7'])])); new['일자'] = r['일자']
            L = upsert(L, new, '증시자금추이_금투협', f'자동 수집 07 금투협 증시자금추이(FreeSIS, {tag})')
        files_in.append(('07', '금투협 증시자금추이', '증시자금추이_금투협'))
    if 'freesis_funds' in led:
        for ds, r in sorted(led['freesis_funds'].items()):
            d = pd.Timestamp(ds)
            if (L['일자'] == d).any() or r.get('deposit') is None: continue
            new = dict(zip(cols[1:7], [r['deposit'], r.get('deriv_deposit'), r.get('rp_balance'), r.get('unpaid'), r.get('forced_sale'), r.get('forced_ratio')])); new['일자'] = d
            L = upsert(L, new, '증시자금추이_금투협', '공개 수집 저장소 freesis_funds(금투협 원천)')
    X['증시자금추이_금투협'] = L.sort_values('일자').reset_index(drop=True)
    Cr = X['신용공여잔고_금투협']; cols = list(Cr.columns); l8 = rd(f('08_*.csv'))
    if l8 is not None:
        l8['일자'] = pd.to_datetime(l8['일자'].astype(str))
        for _, r in l8.sort_values('일자').iterrows():
            new = dict(zip(cols[1:9], [num(r[f'TMPV{j}']) for j in range(2, 10)])); new['일자'] = r['일자']
            Cr = upsert(Cr, new, '신용공여잔고_금투협', f'자동 수집 08 금투협 신용공여잔고(FreeSIS, {tag})', skip=('청약자금 대출(백만원)',))
        files_in.append(('08', '금투협 신용공여 잔고 추이', '신용공여잔고_금투협'))
    if 'freesis_credit' in led:
        for ds, r in sorted(led['freesis_credit'].items()):
            d = pd.Timestamp(ds)
            if (Cr['일자'] == d).any() or r.get('credit_total') is None: continue
            new = {cols[1]: r['credit_total'], cols[2]: r.get('credit_kospi'), cols[3]: r.get('credit_kosdaq'), cols[4]: r.get('short_total'), cols[7]: r.get('ipo_loan'), cols[8]: r.get('collateral_loan'), '일자': d}
            Cr = upsert(Cr, new, '신용공여잔고_금투협', '공개 수집 저장소 freesis_credit(금투협 원천) — 대주 유가·코스닥 구분은 없음')
    X['신용공여잔고_금투협'] = Cr.sort_values('일자').reset_index(drop=True)
    # ---------------- 5. 코스피200
    df = X['코스피200_일별']; k2 = cut(rd(f('04_코스피200*.csv')), '날짜')
    if k2 is not None:
        k2['날짜'] = pd.to_datetime(k2['날짜'])
        for _, r in k2.sort_values('날짜').iterrows():
            d = r['날짜']; prev = df[df['일자'] < d].sort_values('일자'); pc = prev.iloc[-1]['종가(pt)'] if len(prev) else np.nan
            new = {'일자': d, '종가(pt)': r['종가'], '대비(pt)': round(r['종가'] - pc, 2) if pd.notna(pc) else np.nan, '등락률(%)': round((r['종가'] / pc - 1) * 100, 2) if pd.notna(pc) else np.nan,
                   '시가(pt)': r['시가'], '고가(pt)': r['고가'], '저가(pt)': r['저가'], '거래량(천주)': int(round(r['거래량'] / 1000)), '거래대금(백만원)': int(round(r['거래대금'] / 1e6)), '상장시가총액(백만원)': int(round(r['상장시가총액'] / 1e6))}
            df = upsert(df, new, '코스피200_일별', f'자동 수집 04 코스피200(KRX, pykrx, {tag})')
        X['코스피200_일별'] = df.sort_values('일자').reset_index(drop=True); files_in.append(('04', '코스피200 일별', '코스피200_일별'))
    # ---------------- 6. 레버리지ETF_시세 (04 ETF 시세 + 05 상세: 시가총액·순자산·상장좌수) — 이 시트에는 원본 파일 열이 없음(원본파일_목록에만 기록)
    df = X['레버리지ETF_시세']; e = cut(rd(f('04_ETF시세_122630*.csv')), '날짜'); e5 = cut(rd(f('05_ETF상세_122630*.csv')), '날짜')
    if e is not None:
        e['날짜'] = pd.to_datetime(e['날짜']); k2i = X['코스피200_일별'].set_index('일자')['종가(pt)'].sort_index()
        d5 = e5.assign(날짜=pd.to_datetime(e5['날짜'])).set_index('날짜') if e5 is not None else None
        for _, r in e.sort_values('날짜').iterrows():
            d = r['날짜']; prev = df[df['일자'] < d].sort_values('일자'); pc = prev.iloc[-1]['종가(원)'] if len(prev) else np.nan
            bprev = k2i[k2i.index < d].iloc[-1] if (k2i.index < d).any() else np.nan
            new = {'일자': d, '종가(원)': int(r['종가']), '대비(원, 부호 없음)': int(abs(r['종가'] - pc)) if pd.notna(pc) else np.nan, '등락률(%)': round((r['종가'] / pc - 1) * 100, 2) if pd.notna(pc) else np.nan,
                   'NAV(원)': r['NAV'], '시가(원)': int(r['시가']), '고가(원)': int(r['고가']), '저가(원)': int(r['저가']), '거래량(주)': int(r['거래량']), '거래대금(원)': int(r['거래대금']),
                   '기초지수_지수명': '코스피 200', '기초지수_종가': r['기초지수'], '기초지수_대비': round(abs(r['기초지수'] - bprev), 2) if pd.notna(bprev) else np.nan, '기초지수_등락률(%)': round((r['기초지수'] / bprev - 1) * 100, 2) if pd.notna(bprev) else np.nan}
            if d5 is not None and d in d5.index:
                x = d5.loc[d]; x = x.iloc[0] if isinstance(x, pd.DataFrame) else x
                for a_, b_ in (('시가총액(원)', '시가총액'), ('순자산총액(원)', '순자산총액'), ('상장좌수(좌)', '상장좌수')):
                    if b_ in x.index and pd.notna(x[b_]): new[a_] = x[b_]
            df = upsert(df, new, '레버리지ETF_시세', f'자동 수집 04/05 KODEX 레버리지(KRX, {tag})')
        X['레버리지ETF_시세'] = df.sort_values('일자').reset_index(drop=True); files_in.append(('04/05', 'KODEX 레버리지 시세·NAV' + ('·시가총액·순자산·상장좌수' if e5 is not None else '(05 상세 없음 → 상장좌수 빈칸)'), '레버리지ETF_시세'))
    # ---------------- 7. ETF_투자자별
    df = X['ETF_투자자별']; e6 = cut(rd(f('06_ETF투자자별*.csv')), '날짜')
    if e6 is not None:
        e6['날짜'] = pd.to_datetime(e6['날짜'])
        for _, r in e6.sort_values('날짜').iterrows():
            new = {'일자': r['날짜'], '기관합계(원)': r['기관합계'], '기타법인(원)': r['기타법인'], '개인(원)': r['개인'], '외국인 합계(원)': r['외국인합계'], '전체(원)': r['전체']}
            df = upsert(df, new, 'ETF_투자자별', f'자동 수집 06 ETF 투자자별(KRX, {tag})')
        X['ETF_투자자별'] = df.sort_values('일자').reset_index(drop=True); files_in.append(('06', 'KODEX 레버리지 투자자별 순매수', 'ETF_투자자별'))
    # ---------------- 8. 야간선물_일별
    if '야간선물_일별' in X:
        df = X['야간선물_일별']; n9 = cut(rd(f('09_*.csv')), '일자', after=dt.time(6, 10))
        if n9 is not None:
            n9['일자'] = pd.to_datetime(n9['일자'])
            for _, r in n9.sort_values('일자').iterrows():
                new = {'일자': r['일자'], '월물': r['월물'], '시가': r['시가'], '고가': r['고가'], '저가': r['저가'], '종가': r['종가'], '대비': r['대비'], '거래량': r['거래량'], '미결제약정': r['미결제약정']}
                src9 = str(r['원본']) if '원본' in n9.columns and isinstance(r['원본'], str) and r['원본'] else 'KRX 정보데이터시스템 전종목 시세 야간'
                df = upsert(df, new, '야간선물_일별', f'자동 수집 09 야간선물({src9}, {tag})')
            X['야간선물_일별'] = df.sort_values('일자').reset_index(drop=True); files_in.append(('09', '코스피200 선물 야간 일별(근월물)', '야간선물_일별'))
    # ---------------- 9. 참고 시트(공개 자료)
    if mac:
        dates, ser = mac['dates'], mac['series']
        fx = X['참고_원달러']
        for j, ds in enumerate(dates):
            d = pd.Timestamp(ds)
            if (fx['일자'] == d).any() or ser.get('usdkrw', [None] * len(dates))[j] is None or d > last_k: continue
            fx = upsert(fx, {'일자': d, '원/달러(원)': round(float(ser['usdkrw'][j]), 2)}, '참고_원달러', '공개 수집 저장소 kr-flow-dashboard 국제 현물 환율(뉴욕 마감 무렵, macro.json usdkrw)', srccol='출처')
        X['참고_원달러'] = fx.sort_values('일자').reset_index(drop=True)
        ir = X['참고_미국금리']
        g = lambda k, j, n=2: (np.nan if ser.get(k, [None] * len(dates))[j] is None else round(float(ser[k][j]), n))
        for j, ds in enumerate(dates):
            d = pd.Timestamp(ds)
            if ser.get('y10', [None] * len(dates))[j] is None: continue
            new = {'일자': d, '미국 2년(%)': g('y2', j), '미국 5년(%)': g('y5', j), '미국 10년(%)': g('y10', j), '미국 30년(%)': g('y30', j), '미국 10년 실질(%)': g('real10', j), '10년 기대인플레(%)': g('bei10', j),
                   '2·10년 차(bp)': (np.nan if ser.get('s2s10', [None] * len(dates))[j] is None else int(ser['s2s10'][j])), '10년 기간프리미엄(%)': g('tp10', j, 4)}
            if (ir['일자'] == d).any():   # 기간프리미엄처럼 늦게 채워지는 칸만 보충
                i = ir.index[ir['일자'] == d][0]
                for c, v in new.items():
                    if c != '일자' and isna(ir.at[i, c]) and not isna(v): ir.at[i, c] = v; changes.append(('참고_미국금리', dstr(d), c, np.nan, '빈칸 채움(저장소 갱신)', v, '공개 수집 저장소 macro.json'))
            else: ir = upsert(ir, new, '참고_미국금리', '미 재무부·뉴욕 연준(공개 수집 저장소 경유), 미국 현지 날짜', srccol='출처')
        X['참고_미국금리'] = ir.sort_values('일자').reset_index(drop=True)
    if led.get('daum_index'):
        pb = X['참고_공개수집_2024.10~']
        def pubrow(ds):
            d = pd.Timestamp(ds); di = led['daum_index'][ds]; fu = led.get('daum_futures', {}).get(ds, {}); ik = led.get('daum_investor_kospi', {}).get(ds, {}); iq = led.get('daum_investor_kosdaq', {}).get(ds, {})
            fm = led.get('freesis_kospi_market', {}).get(ds, {}); km = led.get('krx_mcap', {}).get(ds, {}); vk = led.get('krx_vkospi', {}).get(ds, {})
            d5, n5, d6, n6 = led.get('daum_stock_005930', {}).get(ds, {}), led.get('naver_stock_005930', {}).get(ds, {}), led.get('daum_stock_000660', {}).get(ds, {}), led.get('naver_stock_000660', {}).get(ds, {})
            est = lambda n_, d_, k_: (round(n_[k_] * d_['vwap'] / 1e8, 1) if n_.get(k_) is not None and d_.get('vwap') else np.nan)
            nn = lambda v: np.nan if v is None else v
            return {'일자': d, '코스피(pt)': nn(di.get('kospi')), '코스닥(pt)': nn(di.get('kosdaq')), 'VKOSPI': nn(vk.get('vkospi')),
                    '선물 외국인 순매수(계약)': nn(fu.get('foreign')), '선물 기관 순매수(계약)': nn(fu.get('inst')), '선물 개인 순매수(계약)': nn(fu.get('indiv')), '선물 미결제약정(계약)': nn(fu.get('oi')), '선물 가격(pt)': nn(fu.get('price')),
                    '코스피 상승 종목 수': nn(km.get('kospi_adv')), '코스피 하락 종목 수': nn(km.get('kospi_dec')), '코스닥 상승 종목 수': nn(km.get('kosdaq_adv')), '코스닥 하락 종목 수': nn(km.get('kosdaq_dec')),
                    '코스피 외국인 보유 비중(%)': nn(fm.get('fo_pct')), '코스피 외국인 보유 시총(억원)': round(fm['fo_mcap'] / 100, 1) if fm.get('fo_mcap') else np.nan, '코스피 시가총액(억원)': round(fm['mcap'] / 100, 1) if fm.get('mcap') else np.nan,
                    '코스피 외국인(억원)': nn(ik.get('foreign')), '코스피 개인(억원)': nn(ik.get('indiv')), '코스피 기관 합계(억원)': nn(ik.get('inst')), '코스피 금융투자(억원)': nn(ik.get('fin_invest')), '코스피 보험(억원)': nn(ik.get('insurance')), '코스피 투신(억원)': nn(ik.get('trust')),
                    '코스피 사모(억원)': nn(ik.get('private_fund')), '코스피 은행(억원)': nn(ik.get('bank')), '코스피 기타금융(억원)': nn(ik.get('etc_fin')), '코스피 연기금(억원)': nn(ik.get('pension')), '코스피 기타법인(억원)': nn(ik.get('etc_corp')), '코스피 기타외국인(억원)': nn(ik.get('etc_foreign')),
                    '코스닥 외국인(억원)': nn(iq.get('foreign')), '코스닥 개인(억원)': nn(iq.get('indiv')), '코스닥 기관 합계(억원)': nn(iq.get('inst')),
                    '삼성전자 외국인 순매수(억원, 추정)': est(n5, d5, 'foreign'), '삼성전자 개인 순매수(억원, 추정)': est(n5, d5, 'indiv'), '삼성전자 외국인 지분율(%)': round(d5['fo_rate'], 3) if d5.get('fo_rate') else np.nan,
                    'SK하이닉스 외국인 순매수(억원, 추정)': est(n6, d6, 'foreign'), 'SK하이닉스 개인 순매수(억원, 추정)': est(n6, d6, 'indiv'), 'SK하이닉스 외국인 지분율(%)': round(d6['fo_rate'], 3) if d6.get('fo_rate') else np.nan,
                    '삼성전자 코스피 시총 비중(%)': round(km['s005930_mcap'] / km['kospi_mcap'] * 100, 2) if km.get('kospi_mcap') and km.get('s005930_mcap') else np.nan,
                    'SK하이닉스 코스피 시총 비중(%)': round(km['s000660_mcap'] / km['kospi_mcap'] * 100, 2) if km.get('kospi_mcap') and km.get('s000660_mcap') else np.nan}
        for ds in sorted(led['daum_index']):
            d = pd.Timestamp(ds)
            if d > last_k: continue
            new = pubrow(ds)
            if (pb['일자'] == d).any():      # 있는 날짜: 빈칸 보충(늦게 오는 VKOSPI·외국인 보유 등) + 저장소 값이 바뀐 칸 교체(15:40 → 18시 → 다음 날 아침 확정. 반올림 차이 0.05 이하는 무시)
                i = pb.index[pb['일자'] == d][0]
                for c, v in new.items():
                    if c == '일자' or c not in pb.columns or isna(v): continue
                    o = pb.at[i, c]
                    if isna(o): pb.at[i, c] = v; changes.append(('참고_공개수집_2024.10~', dstr(d), c, np.nan, '빈칸 채움(저장소 갱신)', v, PUBSRC))
                    else:
                        try: big = abs(float(v) - float(o)) > 0.051 + 1e-4 * abs(float(v))
                        except Exception: big = False
                        if big: pb.at[i, c] = v; changes.append(('참고_공개수집_2024.10~', dstr(d), c, o, '저장소 값 바뀜(잠정·18시 집계 → 다음 날 아침 확정 등)', v, PUBSRC))
            else: pb = upsert(pb, new, '참고_공개수집_2024.10~', PUBSRC, srccol='출처')
        X['참고_공개수집_2024.10~'] = pb.sort_values('일자').reset_index(drop=True); files_in.append(('공개', '공개 수집 저장소(지수·선물·투자자별·등락·외국인 보유·환율·미국 금리)', '참고_공개수집_2024.10~ 외'))
    vx = rd(a.vix) if a.vix else rd(f('13_VIX*.csv'))
    if vx is not None:
        vcol = [c for c in vx.columns if c.upper() in ('VIXCLS', 'CLOSE', 'VIX')]; dcol = [c for c in vx.columns if c.upper() in ('DATE', 'OBSERVATION_DATE')]
        if vcol and dcol:
            vv = X['참고_VIX_유가']; added = 0; src_last = ''
            for _, r in vx.iterrows():
                v = num(r[vcol[0]]); d = pd.Timestamp(r[dcol[0]])
                if pd.isna(v) or pd.isna(d): continue
                vs = str(r['source']) if 'source' in vx.columns and isinstance(r['source'], str) else 'FRED VIXCLS(CBOE)'; src_last = vs
                if (vv['일자'] == d).any():
                    i = vv.index[vv['일자'] == d][0]
                    if isna(vv.at[i, 'VIX 종가']): vv.at[i, 'VIX 종가'] = v; vv.at[i, '출처'] = f'VIX: {vs}' + (' · 유가: EIA' if not isna(vv.at[i, '브렌트유(달러/배럴)']) else ''); added += 1
                    elif 'FRED' in vs and 'FRED VIXCLS(CBOE 종가' not in str(vv.at[i, '출처']) and differs(vv.at[i, 'VIX 종가'], v):   # 보도·뉴스레터 값 → FRED(CBOE 공식 종가)로 교체, 값_교체_기록에 남김
                        changes.append(('참고_VIX_유가', dstr(d), 'VIX 종가', vv.at[i, 'VIX 종가'], str(vv.at[i, '출처'])[:70], v, f'VIX: {vs}'))
                        vv.at[i, 'VIX 종가'] = v; vv.at[i, '출처'] = f'VIX: {vs}' + (' · 유가: EIA' if not isna(vv.at[i, '브렌트유(달러/배럴)']) else ''); added += 1
                else: vv = pd.concat([vv, pd.DataFrame([{'일자': d, 'VIX 종가': v, '출처': f'VIX: {vs}'}])], ignore_index=True); added += 1
            X['참고_VIX_유가'] = vv.sort_values('일자').reset_index(drop=True); files_in.append(('VIX', f'미국 VIX 종가 {src_last}(새 날짜 {added}건)', '참고_VIX_유가'))
    # ---------------- 기록
    kl = X['코스피_일별']['일자'].max(); ll = X['증시자금추이_금투협']['일자'].max(); vl = X['VKOSPI_일별']['일자'].max(); nl = X['야간선물_일별']['일자'].max() if '야간선물_일별' in X else None
    g = X['안내']; c0 = g.columns[0]
    newc0 = re.sub(r'\(20\d\d-\d\d-\d\d.*\)', f'({kl:%Y-%m-%d}, 금투협 {ll:%m/%d}, VKOSPI {vl:%m/%d}' + (f', 야간선물 {nl:%m/%d} 표기분' if nl is not None else '') + f' 기준 — 자동 갱신 {tag})', c0, count=1)
    X['안내'] = g.rename(columns={c0: newc0})
    fl = X['원본파일_목록']; n0 = int(pd.to_numeric(fl['번호'], errors='coerce').max()) if len(fl) else 0
    rows = [{'번호': n0 + q, '업로드 시각': tag, '파일명(업로드 시 이름)': f'자동 수집 {k_}' + (f' ({os.path.basename(C)})' if C and k_ not in ('공개', 'VIX') else ''), '내용': desc, '들어간 시트': sh, '행 수': '', '기간': '', '비고': '자동(GitHub Actions)'} for q, (k_, desc, sh) in enumerate(files_in, 1)]
    X['원본파일_목록'] = pd.concat([fl, pd.DataFrame(rows)], ignore_index=True) if rows else fl
    rec = X['값_교체_기록']; rc0 = list(rec.columns)
    if changes: X['값_교체_기록'] = pd.concat([rec, pd.DataFrame([[str(x) if isinstance(x, (pd.Timestamp,)) else x for x in ch] for ch in changes], columns=rc0)], ignore_index=True)
    out = a.out or a.workbook
    for name in order:
        df = X[name]
        if '일자' in df.columns and name not in NODATE:
            df = df.copy(); dd = pd.to_datetime(df['일자'], errors='coerce'); df['일자'] = dd.dt.strftime('%Y-%m-%d').where(dd.notna(), df['일자']); X[name] = df
    with pd.ExcelWriter(out, engine='openpyxl') as w:
        for name in order: X[name].to_excel(w, sheet_name=name, index=False)
    summary = {'run': tag, 'kospi_last': f'{kl:%Y-%m-%d}', 'kofia_last': f'{ll:%Y-%m-%d}', 'vkospi_last': f'{vl:%Y-%m-%d}', 'night_last': (f'{nl:%Y-%m-%d}' if nl is not None else None),
               'files': files_in, 'changes': [[str(x) for x in ch] for ch in changes]}
    json.dump(summary, open(os.path.join(os.path.dirname(os.path.abspath(out)), 'update_summary.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(json.dumps({k: v for k, v in summary.items() if k != 'changes'}, ensure_ascii=False)); print('changes', len(changes))
    for ch in changes[:60]: print('  ', ch)

if __name__ == '__main__': main()
