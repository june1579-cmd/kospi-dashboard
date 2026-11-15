// 2026-11-12 추가: 머리말 요약(미수 반대매매·신용) 자동 문장. 자료가 갱신될 때마다 최신 금투협 공시분 기준으로 다시 쓴다.
// index.html 의 다른 코드와 변수를 공유하지 않는다. 쓰는 것은 dash·d3 뿐. 글자는 textContent 로만 넣는다.
(function(){
  const P = d3.utcParse('%Y-%m-%d');
  const md = s => { const d = P(String(s).slice(0, 10)); return d ? (d.getUTCMonth() + 1) + '/' + d.getUTCDate() : String(s); };
  const f0 = d3.format(',.0f'), f1 = d3.format(',.1f'), f2 = d3.format(',.2f');
  const num = v => (v === '' || v == null || isNaN(+v)) ? null : +v;
  const sg = (x, f) => (x < 0 ? '−' : x > 0 ? '+' : '') + f(Math.abs(x));
  const BAD = ['error', 'connect', 'declined', 'missing'];

  dash.calc('lede_now', {
    inputs: ['liq', 'credit', 'market', 'credit_change'],
    title: '머리말 요약 수치(최신 공시분)',
    description: '금투협 최신 공시일의 미수 반대매매를 직전 5거래일 평균·최근 20거래일 정점·올해 정점과 비교하고, 최근 10거래일 안 가장 최근 −3% 이하 급락일과 그 T+2 영업일 청산분, 신용융자 일일 증감·1년(252거래일) 고점 대비 변화, 과거 항복 구간(신용+대주 기준) 범위와 판정 문장을 한 줄로 낸다.',
    fn: (liq, credit, market, credit_change) => {
      const L = liq.filter(r => num(r.liq_eok) != null).map(r => ({d: String(r.date), v: +r.liq_eok, p: num(r.ratio_pct)}));
      const C = credit.filter(r => num(r.credit_jo) != null).map(r => ({d: String(r.date), v: +r.credit_jo, ch: num(r.chg_pct)}));
      const M = market.filter(r => num(r.kospi) != null).map(r => ({d: String(r.date), ch: num(r.kospi_chg_pct)}));
      if (!L.length || !C.length) return [];
      const n = L.length - 1, last = L[n], o = {l_date: last.d, l_eok: last.v, l_ratio: last.p};
      const prev = L.slice(Math.max(0, n - 5), n);
      if (prev.length) { o.prev5_avg = Math.round(prev.reduce((a, x) => a + x.v, 0) / prev.length * 10) / 10; o.mult = o.prev5_avg > 0 ? Math.round(last.v / o.prev5_avg * 10) / 10 : null; }
      const w20 = L.slice(Math.max(0, n - 19)); const p20 = w20.reduce((a, x) => x.v > a.v ? x : a, w20[0]);
      o.p20_date = p20.d; o.p20_eok = p20.v; o.p20_ratio = p20.p; o.p20_is_last = p20.d === last.d ? 1 : 0; o.pct_p20 = Math.round(last.v / p20.v * 100);
      const yr = last.d.slice(0, 4), wy = L.filter(x => x.d.slice(0, 4) === yr); const py = wy.reduce((a, x) => x.v > a.v ? x : a, wy[0]);
      o.y_date = py.d; o.y_eok = py.v; o.y_ratio = py.p; o.y_is_last = py.d === last.d ? 1 : 0; o.pct_y = Math.round(last.v / py.v * 100);
      const p10 = L.slice(Math.max(0, n - 9)).reduce((a, x) => (x.p != null && x.p > a) ? x.p : a, 0);
      // 최근 10거래일 안 가장 최근 −3% 이하 급락일과 T+2 영업일(미수 결제일 다음 반대매매)
      const mi = M.findIndex(x => x.d === last.d), tail = M.slice(Math.max(0, M.length - 10));
      for (let k = tail.length - 1; k >= 0; k--) {
        if (tail[k].ch != null && tail[k].ch <= -3) {
          const gi = M.length - tail.length + k; o.crash_date = tail[k].d; o.crash_chg = tail[k].ch;
          if (gi + 2 < M.length) { o.t2_date = M[gi + 2].d; const hit = L.find(x => x.d === o.t2_date); if (hit) { o.t2_eok = hit.v; o.t2_ratio = hit.p; o.t2_pending = 0; } else o.t2_pending = 1; }
          else { let d = P(tail[k].d), c = 0; while (c < 2) { d = new Date(d.getTime() + 864e5); const w = d.getUTCDay(); if (w && w < 6) c++; } o.t2_date = d3.utcFormat('%Y-%m-%d')(d); o.t2_pending = 1; }
          break;
        }
      }
      if (mi < 0 && o.t2_date && o.t2_date > last.d) o.t2_pending = 1;
      const cn = C.length - 1, cl = C[cn]; o.c_date = cl.d; o.c_jo = cl.v; o.c_chg = cl.ch;
      const w252 = C.slice(Math.max(0, cn - 251)); const ch = w252.reduce((a, x) => x.v > a.v ? x : a, w252[0]);
      o.c_peak_date = ch.d; o.c_peak_jo = ch.v; o.c_dd = Math.round((cl.v / ch.v - 1) * 1000) / 10;
      const c5 = C.slice(Math.max(0, cn - 4)).filter(x => x.ch != null); const cm = c5.reduce((a, x) => x.ch < a.ch ? x : a, c5[0] || {ch: null});
      o.c5_min = cm.ch; o.c5_min_date = cm.d || null;
      const cap = credit_change.filter(r => /대주/.test(r.basis_label || '')).map(r => +r.chg_pct).filter(v => !isNaN(v));
      o.cap_hi = cap.length ? Math.max(...cap) : -9; o.cap_lo = cap.length ? Math.min(...cap) : -14;
      const r = last.p;
      o.v_liq = r == null ? '미수 비중 확인 불가' : r >= 5 ? '미수 청산이 다시 커졌다(비중 5% 기준선 위)' : r >= 2 ? '미수 청산이 이어지고 있다' : p10 >= 5 ? '미수 청산 정점은 지났을 수 있다' : '미수 청산 압력은 낮은 편이다';
      o.v_credit = (o.c5_min != null && o.c5_min <= o.cap_hi) ? '신용은 과거 항복 구간 수준으로 정리되고 있다' : o.c_dd <= -30 ? '신용 잔고는 1년 고점 대비 30% 넘게 줄었지만 하루 감소 폭이 항복 구간에 못 미쳐 레버리지 정리가 끝났다고 보긴 이르다' : '레버리지 정리는 끝나지 않았다';
      return [o];
    }
  });

  function draw(){
    const p = document.getElementById('lede-auto'); if (!p) return;
    const d = dash.data('lede_now');
    if (!d || !Array.isArray(d.data) || !d.data.length) {
      const bad = ['liq', 'credit', 'market'].some(k => BAD.includes(dash.data(k).status));
      if (bad) { p.textContent = '요약 문장을 만들 자료를 읽지 못했다.'; } return;
    }
    const o = d.data[0];
    p.textContent = '';
    const t = s => p.appendChild(document.createTextNode(s));
    const v = (txt, src, field, where, bold) => {
      const el = document.createElement(bold ? 'b' : 'span'); el.textContent = txt; el.dataset.source = src; el.dataset.field = field;
      if (where) el.dataset.where = where; else el.dataset.row = '0'; p.appendChild(el); return el;
    };
    const L = 'liq', W = x => 'date=' + x;
    t(`최신 금투협 공시(${md(o.l_date)}분) 미수 반대매매는 `); v(f1(o.l_eok), L, 'liq_eok', W(o.l_date), true); t('억원');
    t('(미수금 대비 '); v(o.l_ratio == null ? '—' : f1(o.l_ratio), L, 'ratio_pct', W(o.l_date)); t('%)');
    if (o.mult != null) { t('으로 직전 5거래일 평균 '); v(f1(o.prev5_avg), 'lede_now', 'prev5_avg'); t('억원의 '); v(f1(o.mult), 'lede_now', 'mult'); t('배다. '); } else t('이다. ');
    if (o.crash_date) {
      t(`${md(o.crash_date)} 급락(`); v(sg(o.crash_chg, f2), 'market', 'kospi_chg_pct', W(o.crash_date)); t('%)');
      if (o.t2_pending) t(`분의 청산은 결제일 다음인 T+2 영업일 ${md(o.t2_date)}분(다음 공시)에 나온다. `);
      else if (o.t2_date === o.l_date) t('분이 T+2로 들어온 값이다. ');
      else { t(`분의 청산은 T+2인 ${md(o.t2_date)}분 `); v(f0(o.t2_eok), L, 'liq_eok', W(o.t2_date)); t('억원(비중 '); v(o.t2_ratio == null ? '—' : f1(o.t2_ratio), L, 'ratio_pct', W(o.t2_date)); t('%)이었다. '); }
    }
    if (o.p20_is_last) t('최근 20거래일 가운데 가장 크고, ');
    else { t(`최근 20거래일 정점 ${md(o.p20_date)} `); v(f1(o.p20_eok), L, 'liq_eok', W(o.p20_date)); t('억원('); v(o.p20_ratio == null ? '—' : f1(o.p20_ratio), L, 'ratio_pct', W(o.p20_date)); t('%)의 '); v(f0(o.pct_p20), 'lede_now', 'pct_p20'); t('%, '); }
    if (o.y_is_last) t(`${o.y_date.slice(0, 4)}년 들어 가장 크다. `);
    else { t(`올해 정점 ${md(o.y_date)} `); v(f1(o.y_eok), L, 'liq_eok', W(o.y_date)); t('억원의 '); v(f0(o.pct_y), 'lede_now', 'pct_y'); t('% 수준이다. '); }
    t(`신용융자는 ${md(o.c_date)} `); v(o.c_chg == null ? '—' : sg(o.c_chg, f2), 'credit', 'chg_pct', W(o.c_date)); t('%('); v(f2(o.c_jo), 'credit', 'credit_jo', W(o.c_date)); t(`조원, 1년 고점 ${md(o.c_peak_date)} `); v(f2(o.c_peak_jo), 'credit', 'credit_jo', W(o.c_peak_date)); t('조원 대비 '); v(sg(o.c_dd, f1), 'lede_now', 'c_dd'); t('%)');
    if (o.c5_min_date && o.c5_min_date !== o.c_date) { t(`, 최근 5거래일 최대 감소는 ${md(o.c5_min_date)} `); v(sg(o.c5_min, f2), 'credit', 'chg_pct', W(o.c5_min_date)); t('%'); }
    t(`로 과거 항복 구간(${f0(o.cap_hi)}~${f0(o.cap_lo)}%, 신용+대주 기준)`); t(o.c5_min != null && o.c5_min <= o.cap_hi ? '에 들어섰다. ' : '에 못 미친다. ');
    const b = document.createElement('b'); b.textContent = `${o.v_liq}. ${o.v_credit}.`; p.appendChild(b);
  }
  dash.onData(draw);
})();
