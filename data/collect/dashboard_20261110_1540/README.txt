수집 2026-11-10 02:50 KST · 기간 2026-10-19~2026-11-10 · 오늘 줄 포함(투자자별 잠정)
성공: ['07_금투협_증시자금추이', '08_금투협_신용공여잔고추이', '13_VIX_일별']
실패: [('pykrx', "JSONDecodeError('Expecting value: line 1 column 1 (char 0)') — pip install pykrx 했는지, KRX 접속이 되는지 확인"), ('05_ETF상세_122630_KODEX 레버리지', "JSONDecodeError('Expecting value: line 1 column 1 (char 0)') — 실패하면 KRX 정보데이터시스템 > 증권상품 > ETF > 개별종목 시세 추이에서 KODEX 레버리지(상장좌수 열이 있는 화면)"), ('09_야간선물_일별', "JSONDecodeError('Expecting value: line 1 column 1 (char 0)')"), ('10_VKOSPI_일별', "JSONDecodeError('Expecting value: line 1 column 1 (char 0)')"), ('12_VKOSPI_탐색', "ValueError('파생상품지수 화면에서 변동성지수 행을 못 찾음(화면 번호 미확인) — 다음 날 10번(Open API)·공개 저장소로 보충')")]
오늘 날짜 줄은 18:30 이후 실행분만 확정치로 포함(그 전 실행은 어제까지).
실패한 항목만 손으로: 09 야간선물 → KRX 정보데이터시스템 > 파생상품 > 종목시세 > 전종목 시세(상품 코스피200 선물, 시장구분 야간) 엑셀. 06 ETF 투자자별 → KRX > 증권상품 > ETF > 거래실적 > 투자자별(개별종목). 10 VKOSPI 시가·고가·저가는 키가 없으면 건너뜀(종가는 대시보드가 공개 자료로 받음).
07·08 금투협 파일 열 이름(TMPV2…)은 화면 열 순서와 같다: 07 = 예탁금·파생예수금·RP·미수금·반대매매·비중, 08 = 신용융자 전체·유가·코스닥, 대주 전체·유가·코스닥, 청약자금대출, 담보융자.
