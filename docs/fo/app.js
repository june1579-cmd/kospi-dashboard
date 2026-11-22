/* 미국·한국 선물옵션 대시보드 웹판 — 자료 읽기 + 그리기.
   자료는 GitHub Actions(fo-dashboard)가 data/ 에 올린 파일 6개(us_daily·cftc·kr_fut·kr_opt·us2kr_pts.csv, tables.json)에서만 읽는다.
   이 파일은 숫자를 만들지 않는다 — 표시(그래프·표·서식)만 한다. 상승 = 빨강, 하락 = 파랑. */
(() => {
  const COL = { blue: '#3b82f6', red: '#e5484d', green: '#1f9d55', gray: '#8a8f98', violet: '#8b5cf6', teal: '#0d9488', navy: '#1e40af' };
  const CSV = ['us_daily', 'cftc', 'kr_fut', 'kr_opt', 'us2kr_pts'];
  const S = {}; const D = {}; let loadErr = null;
  // ------------------------------------------------------------ 도우미
  const numCache = new WeakMap();
  const ok = (id) => (Array.isArray(S[id]) ? S[id] : null);
  const col = (rows, name) => { let m = numCache.get(rows); if (!m) { m = {}; numCache.set(rows, m); } if (!m[name]) m[name] = rows.map((r) => { const v = r[name]; return v === null || v === undefined || v === '' ? NaN : +v; }); return m[name]; };
  const dcol = (rows) => { let m = numCache.get(rows); if (!m) { m = {}; numCache.set(rows, m); } if (!m.__d) m.__d = rows.map((r) => new Date(r.date + 'T00:00:00Z')); return m.__d; };
  const th = (n, d) => (Number.isFinite(n) ? n.toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d }) : '—');
  const sg = (n, s) => (Number.isFinite(n) && n > 0 ? '+' : '') + s;
  const FMT = { pct0: (n) => th(n, 0) + '%', pct1: (n) => th(n, 1) + '%', pct2: (n) => th(n, 2) + '%', spct1: (n) => sg(n, th(n, 1) + '%'), spct2: (n) => sg(n, th(n, 2) + '%'),
    n0: (n) => th(n, 0), n1: (n) => th(n, 1), n2: (n) => th(n, 2), n3: (n) => th(n, 3), n4: (n) => th(n, 4), sn0: (n) => sg(n, th(n, 0)), sn1: (n) => sg(n, th(n, 1)), sn2: (n) => sg(n, th(n, 2)) };
  const fmt = (v, f) => { if (v === null || v === undefined || v === '') return (!f || f === 'txt') ? '' : '—'; if (!f || f === 'txt') return String(v); const n = +v; return Number.isFinite(n) ? (FMT[f] || FMT.n2)(n) : '—'; };
  const dfmt = d3.utcFormat('%Y-%m-%d');
  const sel = (id, def) => { const e = document.getElementById(id); return e && e.value ? e.value : def; };
  const since = (range, lastDate) => { if (range === 'all') return '0000'; const d = new Date(lastDate + 'T00:00:00Z'); d.setUTCMonth(d.getUTCMonth() - ({ '3m': 3, '6m': 6, '1y': 12, '3y': 36, '5y': 60, '10y': 120 }[range] || 12)); return dfmt(d); };
  const el = (tag, cls, txt) => { const e = document.createElement(tag); if (cls) e.className = cls; if (txt !== undefined) e.textContent = txt; return e; };
  const msg = (box, text) => { box.replaceChildren(el('p', 'fo-msg', text)); };
  const guard = (box, ids) => { const out = ids.map(ok); if (out.some((x) => !x || !x.length)) { msg(box, loadErr ? '자료를 불러오지 못했습니다.' : '이 자료가 아직 없습니다(확인하지 못한 값 목록 참고).'); return null; } return out; };
  const find = (rows, where) => { if (!where) return rows[0]; const i = where.indexOf('='); const k = where.slice(0, i); const v = where.slice(i + 1); return rows.find((x) => String(x[k]) === v); };
  const lastOf = (rows, name) => { const a = col(rows, name); for (let i = a.length - 1; i >= 0; i--) if (Number.isFinite(a[i])) return rows[i].date; return ''; };
  const mdOf = (d) => (d ? `${+d.slice(5, 7)}/${+d.slice(8, 10)}` : '없음');

  // ------------------------------------------------------------ 숫자 하나: <b data-v="표:열:서식[:s]" data-w="키=값">
  D.v = (e) => {
    const [src, field, f, sign] = e.dataset.v.split(':'); const rows = ok(src); const r = rows ? find(rows, e.dataset.w) : null; const v = r ? r[field] : null;
    e.textContent = r ? (fmt(v, f) || (f && f !== 'txt' ? '—' : '')) : '—'; e.classList.add('fo-v');
    if (sign) { const n = +v; e.classList.toggle('fo-up', n > 0); e.classList.toggle('fo-dn', n < 0); }
  };

  // ------------------------------------------------------------ 한눈에 보기 카드
  const TGT = [['spx', '미국 · S&P500'], ['ndx', '미국 · 나스닥100'], ['k200', '한국 · 코스피200']];
  D.cards = (box) => {
    const P = ok('prob'); if (!P || !P.length) { msg(box, '방향 확률 표가 아직 없습니다.'); return; }
    const meta = (ok('model_meta') || [{}])[0];
    box.replaceChildren(...TGT.map(([t, title]) => {
      const card = el('article', 'fo-card'); card.id = 'card-' + t; card.append(el('h3', '', title));
      const first = P.find((r) => r.key === `${t}_1`);
      card.append(el('p', 'fo-sub', `기준 ${first ? first.asof : '—'}` + (t === 'ndx' && meta.ndx_src ? ` · ${meta.ndx_src}로 계산` : '') + (t === 'k200' ? ' (야간선물은 모형에 넣지 않음)' : '')));
      [1, 5, 20].forEach((h) => {
        const r = P.find((x) => x.key === `${t}_${h}`); if (!r) return;
        const row = el('div', 'fo-prow'); row.id = `p-${t}-${h}`;
        const ph = el('div', 'fo-ph'); ph.append(el('span', 'fo-pl', `다음 ${h}거래일`), el('span', 'fo-kind' + (r.passed ? ' fo-tag-ok' : ''), r.kind)); row.append(ph);
        const pn = el('div', 'fo-pn'); pn.append(el('span', 'fo-up', `상승 ${fmt(r.up, 'pct1')}`), el('span', 'fo-dn', `하락 ${fmt(r.down, 'pct1')}`)); row.append(pn);
        const bar = el('div', 'fo-pbar'); const a = el('span', 'fo-pb-up'); a.style.width = r.up + '%'; const b = el('span', 'fo-pb-dn'); b.style.width = (100 - r.up) + '%';
        const ci = el('i', 'fo-pb-ci'); ci.style.left = r.lo + '%'; ci.style.width = Math.max(0.5, r.hi - r.lo) + '%'; bar.append(a, b, ci);
        bar.setAttribute('role', 'img'); bar.setAttribute('aria-label', `상승 ${r.up}% · 하락 ${r.down}% · 신뢰구간 ${r.lo}~${r.hi}%`); row.append(bar);
        if (r.spread_txt) row.append(el('p', 'fo-pm fo-warn', r.spread_txt));
        row.append(el('p', 'fo-pm', `표본 ${fmt(r.n, 'n0')}일 · 상승 확률의 95% 신뢰구간 ${fmt(r.lo, 'pct1')} ~ ${fmt(r.hi, 'pct1')}`));
        row.append(el('p', 'fo-pm', `검증: ${r.verdict} (보류 구간 ${fmt(r.n_hold, 'n0')}일 적중 ${fmt(r.acc_hold, 'pct1')}, 늘 상승이라고 할 때 ${fmt(r.acc_base, 'pct1')})`));
        const more = el('details', 'fo-more'); more.append(el('summary', '', '근거·참고 값'));
        more.append(el('p', 'fo-pm', `근거 지표 3개: ${r.features}`));
        more.append(el('p', 'fo-pm', `검증에서 고른 모형(${r.model})의 값: ${fmt(r.model_ref, 'pct1')} (${fmt(r.model_lo, 'pct1')} ~ ${fmt(r.model_hi, 'pct1')})` + (r.passed ? '' : ' — 통과하지 못해 위 확률에는 쓰지 않음')));
        if (r.others) more.append(el('p', 'fo-pm', `다른 모형의 값: ${r.others}`));
        more.append(el('p', 'fo-pm', r.cond_up === null || r.cond_up === undefined ? `근거 지표 3개가 지금과 같은 쪽이던 과거: ${fmt(r.cond_n, 'n0')}일 — ${r.cond_txt || '표본 부족'}`
          : `근거 지표 3개가 지금과 같은 쪽(중앙값 위·아래)이던 과거 ${fmt(r.cond_n, 'n0')}일의 상승 비율 ${fmt(r.cond_up, 'pct1')} (${fmt(r.cond_lo, 'pct1')} ~ ${fmt(r.cond_hi, 'pct1')})`));
        row.append(more); card.append(row);
      });
      return card;
    }));
  };
  D.passlist = (e) => {
    const P = ok('prob'); if (!P) { e.textContent = '—'; return; }
    const pass = P.filter((r) => r.passed); const nm = (r) => `${r.tname} 다음 ${r.h}거래일(상승 ${fmt(r.up, 'pct1')}, 신뢰구간 ${fmt(r.lo, 'pct1')} ~ ${fmt(r.hi, 'pct1')}${r.spread_txt ? ' · 다만 ' + r.spread_txt.replace(/\.$/, '') : ''})`;
    e.textContent = pass.length ? `지수·기간 ${P.length}칸 가운데 검증에서 고른 모형이 보류 구간까지 통과한 것은 ${pass.length}칸입니다 — ${pass.map(nm).join(', ')}. 나머지 ${P.length - pass.length}칸은 통과하지 못해(예측력 없음 또는 약함) 과거 상승 비율(기준선)을 그대로 적었습니다.`
      : `지수·기간 ${P.length}칸 모두 검증을 통과하지 못했습니다(예측력 없음 또는 약함). 모든 칸에 과거 상승 비율(기준선)을 그대로 적었습니다.`;
  };

  // ------------------------------------------------------------ 표
  const TB = {
    basis: { src: 'basis', key: 'key', fsel: ['s-basis-h', 'h'], cols: [['tname', '지수'], ['name', '지표'], ['value', '현재 값', 'n2'], ['pctile', '과거 백분위', 'pct0'], ['up_low', '낮을 때 상승 비율', 'pct1'], ['up_high', '높을 때 상승 비율', 'pct1'], ['bss_val', '검증 구간 개선(%)', 'sn2', 1], ['p_val', 'p값', 'n3'], ['sig', '다중 비교 보정 뒤']] },
    us2kr_x: { src: 'us2kr_x', cols: [['조건', '조건(2000년~)'], ['n', '표본', 'n0'], ['상승일수', '다음 날 상승', 'n0'], ['종가_상승비율', '상승 비율', 'pct1'], ['판정', ''], ['시초가_평균', '시초가 평균(%)', 'sn2', 1], ['장중_평균', '장중 평균(%)', 'sn2', 1], ['현재', '']] },
    cftc_latest: { src: 'cftc_latest', key: 'key', cols: [['mkt', '시장'], ['who', '주체'], ['long', '롱', 'n0'], ['short', '숏', 'n0'], ['net', '순포지션', 'sn0', 1], ['net_chg', '전주 대비', 'sn0', 1], ['sl', '숏÷롱', 'n2'], ['sl_prev', '전주 숏÷롱', 'n2'], ['net_pct_oi', '순포지션÷미결제(%)', 'sn1', 1], ['pctile_3y', '3년 백분위', 'pct0']] },
    us_opex_stat: { src: 'us_opex_stat', cols: [['구간', '구간'], ['n', '표본', 'n0'], ['평균', '평균 등락(%)', 'sn2', 1], ['중앙값', '중앙값(%)', 'sn2', 1], ['상승비율', '상승 비율', 'pct1']] },
    kr_strike_top: { src: 'kr_strike_top', cols: [['만기', '만기'], ['만기일', '만기일(규칙 계산)'], ['콜미결제', '콜 미결제', 'n0'], ['풋미결제', '풋 미결제', 'n0'], ['풋콜_미결제', '풋÷콜', 'n2'], ['맥스페인', '맥스페인', 'n1'], ['콜집중1', '콜 최다 행사가', 'n1'], ['콜집중1_미결제', '계약', 'n0'], ['풋집중1', '풋 최다 행사가', 'n1'], ['풋집중1_미결제', '계약', 'n0']] },
    events: { src: 'events', cols: [['date', '날짜'], ['market', '시장'], ['kind', '종류'], ['note', '규칙'], ['지남', '상태']] },
    us2kr: { src: 'us2kr', cols: [['구간', '간밤 S&P500'], ['n', '표본', 'n0'], ['야간선물_평균', '야간선물 평균(%)', 'sn2', 1], ['시초가_평균', '시초가 평균(%)', 'sn2', 1], ['종가_평균', '종가 평균(%)', 'sn2', 1], ['종가_상승비율', '종가 상승 비율', 'pct1'], ['장중_평균', '장중 평균(%)', 'sn2', 1], ['장중_상승비율', '장중 상승 비율', 'pct1'], ['현재표시', '']] },
    us2kr_reg: { src: 'us2kr_reg', cols: [['대상', '한국 쪽'], ['n', '표본', 'n0'], ['기울기', '기울기', 'n2'], ['상관', '상관계수', 'n2'], ['설명력', '설명력(%)', 'n1'], ['기간', '기간']] },
    valid: { src: 'valid', key: 'key', fsel: ['s-valid-t', 'tname'], cols: [['tname', '지수'], ['h', '기간(일)', 'n0'], ['model', '모형'], ['chosen_txt', '검증에서 선택'], ['bss_val', '검증 개선(%)', 'sn2', 1], ['n_hold', '보류 표본', 'n0'], ['acc_hold', '적중률', 'pct1'], ['acc_base', '기준선(무조건 상승)', 'pct1'], ['acc_random', '무작위', 'pct0'], ['brier_hold', '브라이어', 'n4'], ['brier_base', '기준선 브라이어', 'n4'], ['bss_hold', '보류 개선(%)', 'sn2', 1], ['bss_lo', '90% 구간 하한', 'sn2'], ['bss_hi', '상한', 'sn2'], ['p_hold', 'p값', 'n3'], ['verdict', '판정']] },
    uni_top: { src: 'uni_top', key: 'key', cols: [['tname', '지수'], ['h', '기간(일)', 'n0'], ['name', '지표'], ['bss_val', '검증 개선(%)', 'sn2', 1], ['p_val', 'p값', 'n3'], ['q_bh', '보정 뒤 q', 'n3'], ['up_low', '낮을 때 상승', 'pct1'], ['up_high', '높을 때 상승', 'pct1'], ['sig_txt', '유의']] },
    week: { src: 'week', key: 'date', cols: [['md', '날짜'], ['spx', 'S&P500', 'n2'], ['spx_pct', '%', 'sn2', 1], ['qqq_pct', 'QQQ %', 'sn2', 1], ['dia_pct', 'DIA %', 'sn2', 1], ['es', 'ES', 'n2'], ['nq', 'NQ', 'n2'], ['vix', 'VIX', 'n2'], ['pc_total', '풋/콜 전체', 'n2'], ['pc_spx', '풋/콜 SPX', 'n2'], ['kospi', '코스피', 'n2'], ['kospi_pct', '%', 'sn2', 1], ['k200', '코스피200', 'n2'], ['fut', '선물', 'n2'], ['basis', '베이시스', 'sn2', 1], ['night_pct', '야간선물 %', 'sn2', 1], ['foreign_ct', '외국인(계약)', 'sn0', 1], ['inst_ct', '기관', 'sn0', 1], ['indiv_ct', '개인', 'sn0', 1], ['fut_oi_all', '미결제(전 월물)', 'n0'], ['pcr_krx', 'KRX 풋/콜', 'n2'], ['vkospi', 'VKOSPI', 'n2']] },
    analog: { src: 'analog', cols: [['시작일', '처음 들어선 날'], ['해당일수', '이어진 일수', 'n0'], ['그날_5일등락', '그날까지 5일(%)', 'sn2', 1], ['뒤1일', '1거래일 뒤(%)', 'sn2', 1], ['뒤5일', '5거래일 뒤(%)', 'sn2', 1], ['뒤20일', '20거래일 뒤(%)', 'sn2', 1]] },
    sources: { src: 'sources', cols: [['지표', '지표'], ['출처', '출처'], ['기준', '마지막 날짜'], ['기간', '과거 기간'], ['갱신', '갱신 주기'], ['비고', '비고']] },
    unknown: { src: 'unknown', cols: [['항목', '항목'], ['사유', '사유']] },
  };
  D.table = (box) => {
    const c = TB[box.dataset.table]; const rows = ok(c.src);
    if (!rows) { msg(box, '이 표가 아직 없습니다.'); return; }
    let list = rows;
    if (c.fsel) { const v = sel(c.fsel[0], ''); if (v) list = list.filter((r) => String(r[c.fsel[1]]) === v); }
    if (!list.length) { msg(box, box.dataset.table === 'unknown' ? '확인하지 못한 값이 없습니다.' : '해당하는 줄이 없습니다.'); return; }
    const t = el('table', 'fo-t'); const hr = el('tr'); c.cols.forEach((x) => hr.append(el('th', '', x[1]))); const thd = el('thead'); thd.append(hr); const tb = el('tbody');
    list.forEach((r) => {
      const tr = el('tr'); if (r.chosen_txt === '선택' || r['현재'] || r['현재표시']) tr.className = 'fo-hl';
      c.cols.forEach(([f, , ft, sign]) => {
        const td = el('td', ft && ft !== 'txt' ? 'fo-num' : '', fmt(r[f], ft)); if (sign) { const n = +r[f]; if (n > 0) td.classList.add('fo-up'); if (n < 0) td.classList.add('fo-dn'); }
        if (f === 'verdict') td.classList.add(String(r[f]).startsWith('통과 못') || String(r[f]).startsWith('판정') ? 'fo-mut' : 'fo-okc'); tr.append(td);
      }); tb.append(tr);
    });
    t.append(thd, tb); const w = el('div', 'fo-tw'); w.append(t); box.replaceChildren(w);
  };

  // ------------------------------------------------------------ 그래프(선·막대·점)
  function chart(box, cfg) {
    const W = Math.max(280, box.clientWidth || 320); const H = cfg.height || 230; const hasR = cfg.series.some((s) => s.axis === 'r');
    const m = { t: 8, r: hasR ? 46 : 12, b: 22, l: 46 }; const iw = W - m.l - m.r; const ih = H - m.t - m.b; const X = cfg.x; const n = X.length;
    if (!n) { msg(box, '그릴 자료가 없습니다.'); return; }
    const wrap = el('div', 'fo-chart'); const lg = el('div', 'fo-lg');
    cfg.series.forEach((s) => { const i = el('span', 'fo-lg-i'); const sw = el('i', s.type === 'bar' ? 'fo-sw fo-sw-bar' : 'fo-sw'); sw.style.background = s.color; i.append(sw, document.createTextNode(s.name + (s.axis === 'r' ? ' (오른쪽 눈금)' : ''))); lg.append(i); });
    if (cfg.vlines && cfg.vlineLabel) { const i = el('span', 'fo-lg-i'); i.append(el('i', 'fo-sw fo-sw-v'), document.createTextNode(cfg.vlineLabel)); lg.append(i); }
    const svg = d3.create('svg').attr('viewBox', `0 0 ${W} ${H}`).attr('width', '100%').attr('role', 'img').attr('aria-label', cfg.label || '그래프');
    let x; let bw = 0;
    if (cfg.xType === 'time') x = d3.scaleUtc().domain([X[0], X[n - 1]]).range([m.l, m.l + iw]);
    else if (cfg.xType === 'band') { x = d3.scaleBand().domain(X).range([m.l, m.l + iw]).padding(0.2); bw = x.bandwidth(); } else { const ext = d3.extent(X); x = d3.scaleLinear().domain(cfg.xReverse ? [ext[1], ext[0]] : ext).range([m.l, m.l + iw]); }
    const xp = (i) => (cfg.xType === 'band' ? x(X[i]) + bw / 2 : x(X[i]));
    const dom = (axis) => {
      let lo = Infinity; let hi = -Infinity;
      cfg.series.filter((s) => (s.axis || 'l') === axis).forEach((s) => s.y.forEach((v) => { if (Number.isFinite(v)) { if (v < lo) lo = v; if (v > hi) hi = v; } }));
      if (axis === 'l' && cfg.band) { cfg.band.lo.forEach((v) => { if (Number.isFinite(v) && v < lo) lo = v; }); cfg.band.hi.forEach((v) => { if (Number.isFinite(v) && v > hi) hi = v; }); }
      if (axis === 'l' && cfg.hlines) cfg.hlines.forEach((h) => { if (h.y < lo) lo = h.y; if (h.y > hi) hi = h.y; });
      if (!Number.isFinite(lo)) { lo = 0; hi = 1; }
      if (cfg.series.some((s) => (s.axis || 'l') === axis && (s.type === 'bar' || s.type === 'area'))) { lo = Math.min(lo, 0); hi = Math.max(hi, 0); }
      if (lo === hi) { lo -= 1; hi += 1; }
      const pad = (hi - lo) * 0.06; return [lo - pad, hi + pad];
    };
    const yl = d3.scaleLinear().domain(cfg.yDomain || dom('l')).range([m.t + ih, m.t]); const yr = hasR ? d3.scaleLinear().domain(dom('r')).range([m.t + ih, m.t]) : null;
    const g = svg.append('g'); const yf = cfg.yFmt || ((v) => d3.format('~s')(v)); const yfr = cfg.yFmtR || ((v) => d3.format('~s')(v));
    yl.ticks(4).forEach((t) => { g.append('line').attr('x1', m.l).attr('x2', m.l + iw).attr('y1', yl(t)).attr('y2', yl(t)).attr('class', t === 0 ? 'fo-zero' : 'fo-grid'); g.append('text').attr('x', m.l - 5).attr('y', yl(t)).attr('dy', '0.32em').attr('text-anchor', 'end').attr('class', 'fo-tick').text(yf(t)); });
    if (yr) yr.ticks(4).forEach((t) => g.append('text').attr('x', m.l + iw + 5).attr('y', yr(t)).attr('dy', '0.32em').attr('class', 'fo-tick').text(yfr(t)));
    if (cfg.xType === 'time') {
      const span = (X[n - 1] - X[0]) / 864e5; const f = span > 900 ? d3.utcFormat('%Y') : span > 100 ? d3.utcFormat('%y.%m') : d3.utcFormat('%m/%d');
      x.ticks(Math.max(2, Math.floor(iw / 70))).forEach((t) => g.append('text').attr('x', x(t)).attr('y', H - 6).attr('text-anchor', 'middle').attr('class', 'fo-tick').text(f(t)));
    } else if (cfg.xType === 'band') {
      const step = Math.max(1, Math.ceil(n / Math.max(2, Math.floor(iw / 44))));
      X.forEach((v, i) => { if (i % step === 0) g.append('text').attr('x', xp(i)).attr('y', H - 6).attr('text-anchor', 'middle').attr('class', 'fo-tick').text(cfg.xFmt ? cfg.xFmt(v) : v); });
    } else x.ticks(Math.max(2, Math.floor(iw / 60))).forEach((t) => g.append('text').attr('x', x(t)).attr('y', H - 6).attr('text-anchor', 'middle').attr('class', 'fo-tick').text(cfg.xFmt ? cfg.xFmt(t) : t));
    if (cfg.vlines) cfg.vlines.forEach((v) => { const px = cfg.xType === 'band' ? x(v) + bw / 2 : x(v); if (px >= m.l && px <= m.l + iw) g.append('line').attr('x1', px).attr('x2', px).attr('y1', m.t).attr('y2', m.t + ih).attr('class', 'fo-vline'); });
    if (cfg.hlines) cfg.hlines.forEach((h) => { g.append('line').attr('x1', m.l).attr('x2', m.l + iw).attr('y1', yl(h.y)).attr('y2', yl(h.y)).attr('class', 'fo-ref'); if (h.label) g.append('text').attr('x', m.l + iw - 2).attr('y', yl(h.y) - 3).attr('text-anchor', 'end').attr('class', 'fo-tick').text(h.label); });
    if (cfg.diag) { const d0 = Math.max(yl.domain()[0], x.domain()[0]); const d1 = Math.min(yl.domain()[1], x.domain()[1]); g.append('line').attr('x1', x(d0)).attr('y1', yl(d0)).attr('x2', x(d1)).attr('y2', yl(d1)).attr('class', 'fo-ref'); }
    if (cfg.band) { const area = d3.area().defined((d, i) => Number.isFinite(cfg.band.lo[i]) && Number.isFinite(cfg.band.hi[i])).x((d, i) => xp(i)).y0((d, i) => yl(cfg.band.lo[i])).y1((d, i) => yl(cfg.band.hi[i])); g.append('path').attr('d', area(X)).style('fill', cfg.band.color || COL.gray).attr('opacity', 0.18); }
    const bars = cfg.series.filter((s) => s.type === 'bar'); const nb = bars.length; const slot = cfg.xType === 'band' ? bw : Math.max(1, (iw / Math.max(1, n)) * 0.8);
    cfg.series.forEach((s) => {
      const y = s.axis === 'r' ? yr : yl;
      if (s.type === 'bar') {
        const k = bars.indexOf(s); const w = Math.max(0.6, slot / nb); const gg = g.append('g');
        s.y.forEach((v, i) => { if (!Number.isFinite(v)) return; const x0 = xp(i) - slot / 2 + k * w; const y0 = y(0); const y1 = y(v); gg.append('rect').attr('x', x0).attr('width', w).attr('y', Math.min(y0, y1)).attr('height', Math.max(0.5, Math.abs(y1 - y0))).style('fill', s.colorFn ? s.colorFn(v, i) : s.color).attr('opacity', s.opacity || 0.85); });
      } else if (s.type === 'dot') {
        const gg = g.append('g'); s.y.forEach((v, i) => { if (Number.isFinite(v)) gg.append('circle').attr('cx', xp(i)).attr('cy', y(v)).attr('r', s.r || 2.2).style('fill', s.color).attr('opacity', s.opacity || 0.75); });
      } else {
        if (s.type === 'area') { const a = d3.area().defined((d, i) => Number.isFinite(s.y[i])).x((d, i) => xp(i)).y0(y(0)).y1((d, i) => y(s.y[i])); g.append('path').attr('d', a(X)).style('fill', s.color).attr('opacity', 0.16); }
        const line = d3.line().defined((d, i) => Number.isFinite(s.y[i])).x((d, i) => xp(i)).y((d, i) => y(s.y[i]));
        g.append('path').attr('d', line(X)).attr('fill', 'none').style('stroke', s.color).attr('stroke-width', s.width || 1.5).attr('stroke-dasharray', s.dash || null).attr('stroke-linejoin', 'round');
        if (s.dots) s.y.forEach((v, i) => { if (Number.isFinite(v)) g.append('circle').attr('cx', xp(i)).attr('cy', y(v)).attr('r', 2.6).style('fill', s.color); });
      }
    });
    const tip = el('div', 'fo-tip'); tip.hidden = true; const cross = g.append('line').attr('y1', m.t).attr('y2', m.t + ih).attr('class', 'fo-cross').attr('opacity', 0);
    const px = X.map((d, i) => xp(i)); const sorted = cfg.xType === 'time' || cfg.xType === 'band';
    const nearest = (mx) => {
      if (!sorted) { let best = 0; let bd = Infinity; px.forEach((p, i) => { const d = Math.abs(p - mx); if (d < bd) { bd = d; best = i; } }); return best; }
      let lo = 0; let hi = n - 1; while (hi - lo > 1) { const mid = (lo + hi) >> 1; if (px[mid] < mx) lo = mid; else hi = mid; } return Math.abs(px[lo] - mx) <= Math.abs(px[hi] - mx) ? lo : hi;
    };
    const show = (ev) => {
      const rect = svg.node().getBoundingClientRect(); const mx = ((ev.clientX - rect.left) / rect.width) * W; const i = nearest(mx);
      cross.attr('x1', px[i]).attr('x2', px[i]).attr('opacity', 1);
      const head = el('b', '', cfg.tipX ? cfg.tipX(X[i], i) : cfg.xType === 'time' ? dfmt(X[i]) : String(X[i]));
      const lines = cfg.series.map((s) => { const r = el('span', 'fo-tip-r'); const sw = el('i', 'fo-sw'); sw.style.background = s.color; r.append(sw, document.createTextNode(`${s.name} ${Number.isFinite(s.y[i]) ? (s.fmt || ((v) => th(v, 2)))(s.y[i]) : '—'}`)); return r; });
      if (cfg.tipExtra) { const t = cfg.tipExtra(i); if (t) lines.push(el('span', 'fo-tip-r', t)); }
      tip.replaceChildren(head, ...lines); tip.hidden = false;
      const left = (px[i] / W) * rect.width; tip.style.left = (left > rect.width / 2 ? Math.max(0, left - tip.offsetWidth - 8) : Math.min(rect.width - tip.offsetWidth, left + 8)) + 'px';
    };
    svg.on('pointermove', show).on('pointerdown', show).on('pointerleave', () => { tip.hidden = true; cross.attr('opacity', 0); });
    const hold = el('div', 'fo-svgbox'); hold.append(svg.node(), tip); wrap.append(lg, hold);
    if (cfg.note) wrap.append(el('p', 'fo-chart-note', cfg.note));
    box.replaceChildren(wrap);
  }
  const slice = (rows, from) => { let i = 0; while (i < rows.length && rows[i].date < from) i++; return i; };
  const sub = (arr, i) => arr.slice(i);
  const rebase = (arr) => { const b = arr.find(Number.isFinite); return arr.map((v) => (Number.isFinite(v) ? (v / b) * 100 : NaN)); };
  const f0 = (v) => th(v, 0); const f1 = (v) => th(v, 1); const f2 = (v) => th(v, 2); const fp = (v) => th(v, 1) + '%'; const fs = (v) => d3.format('~s')(v);
  const vl = (rows, i0, flag) => rows.slice(i0).filter((r) => +r[flag] === 1).map((r) => new Date(r.date + 'T00:00:00Z'));
  const ndxCol = (rows) => (col(rows, 'ndx').filter(Number.isFinite).length > 500 ? 'ndx' : 'qqq');
  const ndxName = (rows) => (ndxCol(rows) === 'ndx' ? '나스닥100' : '나스닥100(QQQ)');

  // ---- 2. 미국 선물
  D.us_px = (box) => {
    const got = guard(box, ['us_daily']); if (!got) return; const rows = got[0]; const i0 = slice(rows, since(sel('r-us', '1y'), rows[rows.length - 1].date)); const X = sub(dcol(rows), i0);
    chart(box, { xType: 'time', x: X, label: '지수와 선물 흐름(구간 첫날 = 100)', yFmt: f0,
      series: [{ name: 'S&P500', color: COL.blue, y: rebase(sub(col(rows, 'spx'), i0)), fmt: f1 }, { name: 'ES 선물', color: COL.teal, y: rebase(sub(col(rows, 'es'), i0)), fmt: f1, dash: '4 2' },
        { name: ndxName(rows), color: COL.red, y: rebase(sub(col(rows, ndxCol(rows)), i0)), fmt: f1 }, { name: 'NQ 선물', color: COL.violet, y: rebase(sub(col(rows, 'nq'), i0)), fmt: f1, dash: '4 2' }] });
  };
  const cftcRows = (box) => { const got = guard(box, ['cftc']); if (!got) return null; const mk = sel('s-cftc-mkt', 'ES'); const all = got[0].filter((r) => r.mkt === mk); if (!all.length) { msg(box, '이 시장의 CFTC 자료가 없습니다.'); return null; } const i0 = slice(all, since(sel('r-cftc', '3y'), all[all.length - 1].date)); return { rows: all.slice(i0), mk }; };
  const WHO = { lev: '헤지펀드', am: '자산운용사', dealer: '딜러', small: '소액' };
  D.cftc_net = (box) => { const c = cftcRows(box); if (!c) return; chart(box, { xType: 'time', x: dcol(c.rows), label: `${c.mk} 주체별 순포지션(계약)`, yFmt: fs,
    series: [{ name: '헤지펀드', color: COL.red, y: col(c.rows, 'lev_net'), fmt: f0 }, { name: '자산운용사', color: COL.blue, y: col(c.rows, 'am_net'), fmt: f0 }, { name: '딜러', color: COL.gray, y: col(c.rows, 'dealer_net'), fmt: f0 }, { name: '소액', color: COL.green, y: col(c.rows, 'small_net'), fmt: f0 }] }); };
  D.cftc_ls = (box) => { const c = cftcRows(box); if (!c) return; const w = sel('s-cftc-who', 'lev'); chart(box, { xType: 'time', x: dcol(c.rows), label: `${c.mk} ${WHO[w]} 롱·숏·순포지션`, yFmt: fs,
    series: [{ name: `${WHO[w]} 순포지션`, color: COL.gray, type: 'area', y: col(c.rows, w + '_net'), fmt: f0 }, { name: '롱(매수)', color: COL.red, y: col(c.rows, w + '_long'), fmt: f0 }, { name: '숏(매도)', color: COL.blue, y: col(c.rows, w + '_short'), fmt: f0 }] }); };
  D.cftc_ratio = (box) => {
    const c = cftcRows(box); if (!c) return; const got = guard(box, ['us_daily']); if (!got) return; const w = sel('s-cftc-who', 'lev'); const pc = c.mk === 'ES' ? 'spx' : ndxCol(got[0]);
    const px = new Map(got[0].map((r) => [r.date, +r[pc]]));
    chart(box, { xType: 'time', x: dcol(c.rows), label: `${c.mk} ${WHO[w]} 숏÷롱 비율과 지수`, yFmt: f2, yFmtR: f0, hlines: [{ y: 1, label: '1 = 롱·숏 같음' }],
      series: [{ name: `${WHO[w]} 숏÷롱`, color: COL.red, y: col(c.rows, w + '_sl'), fmt: f2 }, { name: c.mk === 'ES' ? 'S&P500' : ndxName(got[0]), color: COL.gray, axis: 'r', y: c.rows.map((r) => (px.has(r.date) ? px.get(r.date) : NaN)), fmt: f2 }] });
  };
  D.cftc_oi = (box) => { const c = cftcRows(box); if (!c) return; chart(box, { xType: 'time', x: dcol(c.rows), height: 170, label: `${c.mk} 미결제약정`, yFmt: fs, series: [{ name: `${c.mk} 미결제약정(계약)`, color: COL.navy, type: 'area', y: col(c.rows, 'oi'), fmt: f0 }] }); };

  // ---- 3. 미국 옵션
  const PCN = { pc_total: '전체', pc_index: '지수', pc_equity: '개별주식', pc_spx: 'SPX' };
  D.us_pc = (box) => {
    const got = guard(box, ['us_daily']); if (!got) return; const rows = got[0]; const k = sel('s-pc', 'pc_total'); const i0 = slice(rows, since(sel('r-pc', '1y'), rows[rows.length - 1].date)); const X = sub(dcol(rows), i0); const y = sub(col(rows, k), i0);
    const ma = y.map((v, i) => { const w = y.slice(Math.max(0, i - 9), i + 1).filter(Number.isFinite); return w.length >= 6 ? d3.mean(w) : NaN; });
    chart(box, { xType: 'time', x: X, label: `Cboe 풋/콜 ${PCN[k]}과 S&P500`, yFmt: f2, yFmtR: f0, vlines: vl(rows, i0, 'opex'), vlineLabel: '월간 만기일',
      series: [{ name: `풋/콜 ${PCN[k]}`, color: COL.gray, y, fmt: f2, width: 1 }, { name: '10일 평균', color: COL.red, y: ma, fmt: f2, width: 1.8 }, { name: 'S&P500', color: COL.blue, axis: 'r', y: sub(col(rows, 'spx'), i0), fmt: f2 }] });
  };
  D.us_oi = (box) => {
    const got = guard(box, ['us_daily']); if (!got) return; const rows = got[0]; let from = since(sel('r-pc', '1y'), rows[rows.length - 1].date); if (from < '2019-10-07') from = '2019-10-07'; const i0 = slice(rows, from);
    chart(box, { xType: 'time', x: sub(dcol(rows), i0), height: 190, label: 'Cboe 미결제약정 풋÷콜', yFmt: f2, vlines: vl(rows, i0, 'opex'), vlineLabel: '월간 만기일',
      series: [{ name: '전체 미결제 풋÷콜', color: COL.violet, y: sub(col(rows, 'oi_pc'), i0), fmt: f2 }, { name: 'SPX 미결제 풋÷콜', color: COL.teal, y: sub(col(rows, 'spx_oi_pc'), i0), fmt: f2 }] });
  };
  D.us_vix = (box) => {
    const got = guard(box, ['us_daily']); if (!got) return; const rows = got[0]; const i0 = slice(rows, since(sel('r-vix', '1y'), rows[rows.length - 1].date));
    chart(box, { xType: 'time', x: sub(dcol(rows), i0), label: 'VIX·VIX3M과 VIX÷VIX3M', yFmt: f0, yFmtR: f2, vlines: vl(rows, i0, 'opex'), vlineLabel: '월간 만기일',
      series: [{ name: 'VIX', color: COL.red, y: sub(col(rows, 'vix'), i0), fmt: f2 }, { name: 'VIX3M', color: COL.gray, y: sub(col(rows, 'vix3m'), i0), fmt: f2 }, { name: 'VIX÷VIX3M', color: COL.blue, axis: 'r', y: sub(col(rows, 'vix_ratio'), i0), fmt: f2, width: 1 }] });
  };
  D.us_term = (box) => { const got = guard(box, ['term']); if (!got) return; const t = got[0]; chart(box, { xType: 'band', x: t.map((r) => r['만기']), height: 190, label: 'VIX 기간구조', yFmt: f0,
    series: [{ name: `최신(${t[0]['최신일']})`, color: COL.red, y: t.map((r) => r['최신'] ?? NaN), fmt: f2, dots: true, width: 2 }, { name: `5거래일 전(${t[0]['일주일전일']})`, color: COL.blue, y: t.map((r) => r['일주일전'] ?? NaN), fmt: f2, dots: true }, { name: `21거래일 전(${t[0]['한달전일']})`, color: COL.gray, y: t.map((r) => r['한달전'] ?? NaN), fmt: f2, dots: true }] }); };
  D.us_opex = (box) => { const got = guard(box, ['us_opex_path']); if (!got) return; const t = got[0];
    chart(box, { xType: 'linear', x: t.map((r) => r.k), height: 210, label: '월간 만기 전후 S&P500 누적 등락', yFmt: fp, xFmt: (v) => (v === 0 ? '만기일' : (v > 0 ? '+' : '') + v), tipX: (v) => (v === 0 ? '만기일' : `만기 ${v > 0 ? '뒤' : '전'} ${Math.abs(v)}거래일`),
      band: { lo: t.map((r) => r.p25), hi: t.map((r) => r.p75), color: COL.gray }, vlines: [0], hlines: [{ y: 0 }],
      series: [{ name: `과거 평균(만기 ${t[0].n}회)`, color: COL.gray, y: t.map((r) => r.mean), fmt: fp, width: 2 }, { name: '중앙값', color: COL.blue, y: t.map((r) => r.median), fmt: fp }, { name: `가장 최근 만기(${t[0].latest_date})`, color: COL.red, y: t.map((r) => (r.latest === null ? NaN : r.latest)), fmt: fp, width: 2 }],
      note: '회색 띠 = 과거 만기의 가운데 절반(25~75%) 범위. 만기 10거래일 전 종가를 0으로 둔 누적 등락입니다.' }); };

  // ---- 4. 한국 선물
  const kr = (box, id, rsel, def) => { const got = guard(box, [id]); if (!got) return null; const rows = got[0]; const i0 = slice(rows, since(sel(rsel, def), rows[rows.length - 1].date)); return { rows, i0, X: sub(dcol(rows), i0) }; };
  D.kr_px = (box) => { const c = kr(box, 'kr_fut', 'r-kr', '1y'); if (!c) return; chart(box, { xType: 'time', x: c.X, label: '코스피200 지수·선물과 베이시스', yFmt: f0, yFmtR: f1, vlines: vl(c.rows, c.i0, 'qexp'), vlineLabel: '분기 동시만기',
    series: [{ name: '베이시스(선물−현물)', color: COL.gray, type: 'bar', axis: 'r', y: sub(col(c.rows, 'basis'), c.i0), fmt: f2, opacity: 0.5 }, { name: '코스피200', color: COL.blue, y: sub(col(c.rows, 'k200'), c.i0), fmt: f2 }, { name: '선물(주간 종가)', color: COL.red, y: sub(col(c.rows, 'fut'), c.i0), fmt: f2, width: 1, dash: '4 2' }] }); };
  D.kr_sess = (box) => { const got = guard(box, ['kr_fut']); if (!got) return; const rows = got[0]; const i0 = slice(rows, '2025-06-09');
    chart(box, { xType: 'time', x: sub(dcol(rows), i0), label: '코스피200 선물 주간·야간 세션별 누적 등락', yFmt: fp,
      series: [{ name: '야간 세션 누적(주간 종가→야간 종가)', color: COL.violet, y: sub(col(rows, 'cum_night'), i0), fmt: fp }, { name: '주간 세션 누적(야간 종가→주간 종가)', color: COL.teal, y: sub(col(rows, 'cum_day'), i0), fmt: fp }],
      tipExtra: (i) => { const r = rows[i0 + i]; return `그날 야간 ${fmt(r.night_pct, 'spct2')} · 주간 ${fmt(r.day_pct, 'spct2')}`; } }); };
  D.kr_oi = (box) => { const c = kr(box, 'kr_fut', 'r-kr', '1y'); if (!c) return; chart(box, { xType: 'time', x: c.X, height: 190, label: '코스피200 선물 미결제약정', yFmt: fs, vlines: vl(c.rows, c.i0, 'qexp'), vlineLabel: '분기 동시만기',
    series: [{ name: `근월물(KRX, ~${mdOf(lastOf(c.rows, 'fut_oi_front'))})`, color: COL.navy, y: sub(col(c.rows, 'fut_oi_front'), c.i0), fmt: f0 }, { name: `전 월물 합계(2024-10~${mdOf(lastOf(c.rows, 'fut_oi_all'))})`, color: COL.red, y: sub(col(c.rows, 'fut_oi_all'), c.i0), fmt: f0 }] }); };
  const INV = { foreign: '외국인', inst: '기관', indiv: '개인' };
  D.kr_inv = (box) => { const c = kr(box, 'kr_fut', 'r-inv', '6m'); if (!c) return; const w = sel('s-inv', 'foreign'); const unit = sel('s-unit', 'amt'); const k = `${w}_${unit}`;
    chart(box, { xType: 'time', x: c.X, label: `${INV[w]} 코스피200 선물 일별 순매수`, yFmt: fs, yFmtR: f0,
      series: [{ name: `${INV[w]} 순매수(${unit === 'ct' ? '계약' : '억원'})`, color: COL.red, type: 'bar', y: sub(col(c.rows, k), c.i0), fmt: f0, colorFn: (v) => (v >= 0 ? COL.red : COL.blue) }, { name: '코스피200', color: COL.gray, axis: 'r', y: sub(col(c.rows, 'k200'), c.i0), fmt: f2 }],
      note: unit === 'ct' ? `계약 수는 코스피 대시보드가 모으는 값(2024-10-02~${mdOf(lastOf(c.rows, k))})입니다. 2025-06 이후는 야간 세션 거래가 섞인 것으로 보여 금액 계열과 어긋나는 날이 있습니다.` : `금액(억원)은 KRX 정규장 기준이며 ${mdOf(lastOf(c.rows, k))}까지 있습니다.` }); };
  D.kr_cum = (box) => { const c = kr(box, 'kr_fut', 'r-inv', '6m'); if (!c) return; const unit = sel('s-unit', 'amt');
    chart(box, { xType: 'time', x: c.X, label: '외국인 선물 누적 순매수(20일·60일)', yFmt: fs, yFmtR: f0, hlines: [{ y: 0 }],
      series: [{ name: `20일 누적(${unit === 'ct' ? '계약' : '억원'})`, color: COL.red, y: sub(col(c.rows, `foreign_${unit}_c20`), c.i0), fmt: f0 }, { name: '60일 누적', color: COL.blue, y: sub(col(c.rows, `foreign_${unit}_c60`), c.i0), fmt: f0 }, { name: '코스피200', color: COL.gray, axis: 'r', y: sub(col(c.rows, 'k200'), c.i0), fmt: f2, width: 1 }] }); };
  D.kr_roll = (box) => {
    const h = ok('kr_roll'); const cur = ok('kr_roll_cur') || []; if (!h || !h.length) { msg(box, '롤오버 과거 경로 자료가 아직 없습니다.'); return; }
    const xs = [...new Set([...cur.map((r) => r.dte), ...h.map((r) => r.dte)])].filter((d) => d <= 20).sort((a, b) => b - a);
    const hm = new Map(h.map((r) => [r.dte, r])); const cm = new Map(cur.map((r) => [r.dte, r.next_share]));
    const pick = (f) => xs.map((d) => (hm.has(d) && hm.get(d)[f] !== null && hm.get(d)[f] !== undefined ? hm.get(d)[f] : NaN));
    chart(box, { xType: 'linear', x: xs, xReverse: true, height: 220, label: '분기 만기 전 다음 월물 미결제 비중', yFmt: fp, xFmt: (v) => (v === 0 ? '만기' : 'D−' + v), tipX: (v) => (v === 0 ? '만기일' : `만기 ${v}거래일 전`),
      band: { lo: pick('p25'), hi: pick('p75'), color: COL.gray },
      series: [{ name: `과거 평균(분기 만기 ${h[0].n}회)`, color: COL.gray, y: pick('mean'), fmt: fp, width: 2 }, { name: h[0].last_label || '직전 만기', color: COL.blue, y: pick('last'), fmt: fp, width: 1 },
        { name: cur.length ? `이번 분기물(${cur[cur.length - 1].md}까지, 만기 ${cur[0].expiry})` : '이번 분기물(자료 없음)', color: COL.red, y: xs.map((d) => (cm.has(d) ? cm.get(d) : NaN)), fmt: fp, width: 2 }],
      note: '비중 = 근월물이 아닌 월물의 미결제약정 ÷ 전 월물 미결제약정. 이번 분기물의 남은 거래일은 평일 수로 센 값입니다(공휴일 미반영).' });
  };

  // ---- 5. 한국 옵션
  D.kr_pc = (box) => { const c = kr(box, 'kr_opt', 'r-kpc', '1y'); if (!c) return; chart(box, { xType: 'time', x: c.X, label: '코스피200 옵션 풋/콜과 지수', yFmt: f2, yFmtR: f0, vlines: vl(c.rows, c.i0, 'mexp'), vlineLabel: '월물 만기일',
    series: [{ name: `KRX 공표 풋/콜(월물 거래량, ~${mdOf(lastOf(c.rows, 'pcr_krx'))})`, color: COL.gray, y: sub(col(c.rows, 'pcr_krx'), c.i0), fmt: f2, width: 1.6 }, { name: '범위 합산 미결제 풋÷콜(근월물, 참고)', color: COL.red, y: sub(col(c.rows, 'm_pcoi'), c.i0), fmt: f2, width: 1, dash: '3 2' },
      { name: '범위 합산 거래량 풋÷콜(월물+위클리, 5일 평균, 참고)', color: COL.violet, y: sub(col(c.rows, 'all_pcv_ma5'), c.i0), fmt: f2, width: 1, dash: '3 2' }, { name: '코스피200', color: COL.blue, axis: 'r', y: sub(col(c.rows, 'k200'), c.i0), fmt: f2 }] }); };
  D.exp_sel = (s) => { const top = ok('kr_strike_top') || []; const cur = s.value; s.replaceChildren(...top.map((r) => new Option(`${r['만기']} (만기 ${r['만기일']})`, r['만기']))); if (top.some((r) => r['만기'] === cur)) s.value = cur; };
  D.kr_strike = (box) => {
    const got = guard(box, ['kr_strike', 'kr_strike_top']); if (!got) return; const e = sel('s-exp', got[1][0]['만기']); const top = got[1].find((r) => r['만기'] === e); const spot = top ? top['코스피200'] : NaN;
    const rows = got[0].filter((r) => r.exp === e && (!Number.isFinite(spot) || (r.K >= spot * 0.85 && r.K <= spot * 1.2))).sort((a, b) => a.K - b.K);
    if (!rows.length) { msg(box, '이 만기의 행사가별 자료가 없습니다.'); return; } const ks = rows.map((r) => r.K); const near = (v) => ks.reduce((a, b) => (Math.abs(b - v) < Math.abs(a - v) ? b : a), ks[0]);
    chart(box, { xType: 'band', x: ks, height: 250, label: `${e} 행사가별 미결제약정`, yFmt: fs, xFmt: (v) => th(v, 0), vlines: Number.isFinite(spot) ? [near(spot)] : null, vlineLabel: `코스피200 ${th(spot, 2)}(가장 가까운 행사가)`,
      tipX: (v) => `행사가 ${th(v, 1)}`, tipExtra: (i) => `전일 대비 콜 ${fmt(rows[i].doi_C, 'sn0')} · 풋 ${fmt(rows[i].doi_P, 'sn0')}`,
      series: [{ name: '콜 미결제', color: COL.red, type: 'bar', y: rows.map((r) => r.oi_C), fmt: f0 }, { name: '풋 미결제', color: COL.blue, type: 'bar', y: rows.map((r) => r.oi_P), fmt: f0 }] });
  };
  D.kr_vk = (box) => { const c = kr(box, 'kr_opt', 'r-kpc', '1y'); if (!c) return; chart(box, { xType: 'time', x: c.X, height: 200, label: 'VKOSPI와 코스피200', yFmt: f0, yFmtR: f0, vlines: vl(c.rows, c.i0, 'mexp'), vlineLabel: '월물 만기일',
    series: [{ name: 'VKOSPI', color: COL.red, y: sub(col(c.rows, 'vkospi'), c.i0), fmt: f2 }, { name: `대표 내재변동성(KRX, ~${mdOf(lastOf(c.rows, 'iv_rep'))})`, color: COL.gray, y: sub(col(c.rows, 'iv_rep'), c.i0), fmt: f1, width: 1 }, { name: '코스피200', color: COL.blue, axis: 'r', y: sub(col(c.rows, 'k200'), c.i0), fmt: f2 }] }); };

  // ---- 6. 겹쳐 보기 · 선후 관계
  const OV = { us_pc_total: ['us_daily', 'pc_total_ma10', 'spx', 'Cboe 풋/콜 전체(10일 평균)', 'S&P500'], us_pc_equity: ['us_daily', 'pc_equity_ma10', 'spx', 'Cboe 풋/콜 개별주식(10일 평균)', 'S&P500'],
    us_vix: ['us_daily', 'vix', 'spx', 'VIX', 'S&P500'], us_vixr: ['us_daily', 'vix_ratio', 'NDX', 'VIX÷VIX3M', '나스닥100'], us_oipc: ['us_daily', 'oi_pc', 'spx', '미결제 풋÷콜(전체)', 'S&P500'],
    kr_basis: ['kr_fut', 'basis_pct', 'k200', '베이시스÷현물(%)', '코스피200'], kr_f20: ['kr_fut', 'foreign_amt_c20', 'k200', '외국인 선물 20일 누적(억원)', '코스피200'], kr_f60: ['kr_fut', 'foreign_amt_c60', 'k200', '외국인 선물 60일 누적(억원)', '코스피200'],
    kr_oi: ['kr_fut', 'fut_oi_front', 'k200', '선물 미결제(근월물)', '코스피200'], kr_fx: ['kr_fut', 'usdkrw', 'k200', '원/달러', '코스피200'], kr_pcoi: ['kr_opt', 'pcr_krx', 'k200', 'KRX 풋/콜(월물 거래량)', '코스피200'], kr_vk: ['kr_opt', 'vkospi', 'k200', 'VKOSPI', '코스피200'] };
  D.overlay = (box) => { const o = OV[sel('s-ov', 'us_vix')]; const got = guard(box, [o[0]]); if (!got) return; const rows = got[0]; const pc = o[2] === 'NDX' ? ndxCol(rows) : o[2]; const i0 = slice(rows, since(sel('r-ov', '3y'), rows[rows.length - 1].date));
    chart(box, { xType: 'time', x: sub(dcol(rows), i0), label: `${o[3]}와 ${o[4]}`, yFmt: (v) => (Math.abs(v) >= 1000 ? fs(v) : th(v, 2)), yFmtR: f0,
      series: [{ name: o[3], color: COL.red, y: sub(col(rows, o[1]), i0), fmt: f2 }, { name: o[4], color: COL.blue, axis: 'r', y: sub(col(rows, pc), i0), fmt: f2 }] }); };
  const xcNames = () => { const rows = ok('link_xcorr') || []; return [...new Set(rows.map((r) => `${r.target} ← ${r.indicator}`))]; };
  D.xc_sel = (s) => { const names = xcNames(); const cur = s.value; s.replaceChildren(...names.map((n) => new Option(n, n))); if (names.includes(cur)) s.value = cur; else if (names.length) s.value = names.find((n) => n.indexOf('코스피200 ← 외국인') === 0) || names[0]; };
  D.xcorr = (box) => { const got = guard(box, ['link_xcorr']); if (!got) return; const all = xcNames(); const pick = sel('s-xc', all[0]); const rows = got[0].filter((r) => `${r.target} ← ${r.indicator}` === pick).sort((a, b) => a.lag - b.lag);
    if (!rows.length) { msg(box, '이 조합의 자료가 없습니다.'); return; } const wk = pick.indexOf('주 단위') >= 0;
    chart(box, { xType: 'band', x: rows.map((r) => r.lag), height: 200, label: '선후 관계(교차상관)', yFmt: f2, xFmt: (v) => (v > 0 ? '+' : '') + v, hlines: [{ y: 0 }],
      tipX: (v) => (v === 0 ? '같은 날' : v > 0 ? `지표가 ${v}${wk ? '주' : '일'} 먼저` : `지수가 ${-v}${wk ? '주' : '일'} 먼저`), tipExtra: (i) => `표본 ${th(rows[i].n, 0)}`,
      series: [{ name: '상관계수', color: COL.blue, type: 'bar', y: rows.map((r) => r.corr), fmt: (v) => th(v, 3), colorFn: (v) => (v >= 0 ? COL.red : COL.blue) }],
      note: '가로축 +는 지표가 먼저, −는 지수가 먼저 움직인 경우입니다. 0(같은 날)만 크고 +쪽이 0에 가까우면 예고 능력은 없다는 뜻입니다.' }); };
  D.scatter = (box) => {
    const got = guard(box, ['us2kr_pts', 'us2kr_reg']); if (!got) return; const pts = got[0]; const k = sel('s-sc', 'gap'); const reg = got[1].find((r) => r.id === k); const now = (ok('us2kr_now') || [{}])[0];
    const xs = col(pts, 'us_on'); const ys = col(pts, k); const idx = xs.map((v, i) => i).filter((i) => Number.isFinite(xs[i]) && Number.isFinite(ys[i]));
    if (!idx.length || !reg) { msg(box, '이 조합의 자료가 없습니다.'); return; }
    const X = idx.map((i) => xs[i]); const Y = idx.map((i) => ys[i]); const ext = d3.extent(X); const lx = [ext[0], ext[1]]; const hasNow = now.us_on !== null && now.us_on !== undefined;
    chart(box, { xType: 'linear', x: X.concat(lx), height: 240, label: '간밤 S&P500 등락과 다음날 한국', yFmt: fp, xFmt: (v) => th(v, 0) + '%', vlines: hasNow ? [now.us_on] : null, vlineLabel: hasNow ? `이번 간밤 S&P500 ${fmt(now.us_on, 'spct2')}` : null, hlines: [{ y: 0 }],
      tipX: (v, i) => (i < idx.length ? `${pts[idx[i]].date} · S&P500 ${fmt(v, 'spct2')}` : `S&P500 ${fmt(v, 'spct2')}`),
      series: [{ name: '하루(최근 5년 + ±2.5% 이상인 날)', color: COL.blue, type: 'dot', y: Y.concat([NaN, NaN]), fmt: fp, opacity: 0.45 }, { name: `추세선(전 기간 기울기 ${th(reg['기울기'], 2)})`, color: COL.red, y: X.map(() => NaN).concat(lx.map((v) => reg['기울기'] * v + reg['절편'])), fmt: fp, width: 2 }] });
  };
  // ---- 7. 보정 곡선
  D.calib = (box) => { const got = guard(box, ['calib']); if (!got) return; const rows = got[0].filter((r) => r.tkey === `${sel('s-cal-t', 'k200')}_${sel('s-cal-h', '1')}`).sort((a, b) => a.p_pred - b.p_pred);
    if (!rows.length) { msg(box, '이 조합의 보정 곡선이 없습니다.'); return; }
    chart(box, { xType: 'linear', x: rows.map((r) => r.p_pred), height: 230, label: '보정 곡선(예측 확률과 실제 빈도)', yFmt: (v) => th(v, 0) + '%', xFmt: (v) => th(v, 0) + '%', diag: true, yDomain: [15, 90],
      tipX: (v) => `예측 ${th(v, 1)}%`, tipExtra: (i) => `표본 ${rows[i].n}일 · ${rows[i].model}`, series: [{ name: '실제 상승 빈도(보류 구간)', color: COL.red, y: rows.map((r) => r.p_obs), fmt: fp, dots: true, width: 2 }],
      note: '점선(대각선)에 가까울수록 예측 확률과 실제 빈도가 맞습니다. 가로로 좁게 몰려 있으면 모형이 사실상 한 가지 값만 낸다는 뜻입니다.' }); };
  D.bar = (e) => { const m = (ok('meta') || [{}])[0]; e.textContent = loadErr ? '자료를 읽지 못했습니다' : `계산 ${m.built || '—'} · 미국 ${mdOf(m.us_asof)} · 한국 ${mdOf(m.kr_asof)} 종가까지`; };

  // ------------------------------------------------------------ 실행
  const run = (name) => document.querySelectorAll(`[data-draw="${name}"]`).forEach((e) => { try { D[name](e); } catch (err) { console.error(name, err); if (e.classList.contains('fo-box')) msg(e, '이 그래프를 그리지 못했습니다.'); } });
  const runAll = () => { document.querySelectorAll('[data-v]').forEach((e) => { try { D.v(e); } catch (err) { e.textContent = '—'; } }); document.querySelectorAll('[data-table]').forEach((e) => { try { D.table(e); } catch (err) { console.error(err); msg(e, '이 표를 그리지 못했습니다.'); } });
    ['bar', 'passlist', 'cards', 'exp_sel', 'xc_sel'].forEach(run); Object.keys(D).filter((k) => !['v', 'table', 'bar', 'passlist', 'cards', 'exp_sel', 'xc_sel'].includes(k)).forEach(run); };
  const redraw = { 'r-us': ['us_px'], 's-cftc-mkt': ['cftc_net', 'cftc_ls', 'cftc_ratio', 'cftc_oi'], 's-cftc-who': ['cftc_ls', 'cftc_ratio'], 'r-cftc': ['cftc_net', 'cftc_ls', 'cftc_ratio', 'cftc_oi'], 's-pc': ['us_pc'], 'r-pc': ['us_pc', 'us_oi'], 'r-vix': ['us_vix'],
    'r-kr': ['kr_px', 'kr_oi'], 's-inv': ['kr_inv'], 's-unit': ['kr_inv', 'kr_cum'], 'r-inv': ['kr_inv', 'kr_cum'], 'r-kpc': ['kr_pc', 'kr_vk'], 's-exp': ['kr_strike'], 's-ov': ['overlay'], 'r-ov': ['overlay'], 's-sc': ['scatter'], 's-cal-t': ['calib'], 's-cal-h': ['calib'], 's-xc': ['xcorr'] };
  const start = () => {
    Object.keys(redraw).forEach((id) => { const s = document.getElementById(id); if (s) s.addEventListener('change', () => redraw[id].forEach(run)); });
    ['s-basis-h', 's-valid-t'].forEach((id) => { const s = document.getElementById(id); if (s) s.addEventListener('change', () => document.querySelectorAll('[data-table]').forEach((e) => { if (TB[e.dataset.table].fsel && TB[e.dataset.table].fsel[0] === id) D.table(e); })); });
    document.querySelectorAll('.fo-nav button[data-go]').forEach((b) => b.addEventListener('click', () => { const t = document.getElementById(b.dataset.go); if (t) t.scrollIntoView({ block: 'start' }); }));
    let tm = null; let lastW = window.innerWidth; window.addEventListener('resize', () => { if (window.innerWidth === lastW) return; lastW = window.innerWidth; clearTimeout(tm); tm = setTimeout(() => Object.keys(D).filter((k) => !['v', 'table', 'bar', 'passlist', 'cards', 'exp_sel', 'xc_sel'].includes(k)).forEach(run), 200); });
    const bust = '?t=' + Date.now();
    Promise.all([d3.json('data/tables.json' + bust).then((t) => Object.assign(S, t)), ...CSV.map((id) => d3.csv(`data/${id}.csv${bust}`).then((rows) => { S[id] = rows; }))])
      .catch((err) => { loadErr = err; console.error(err); const e = document.getElementById('fo-err'); if (e) { e.hidden = false; e.textContent = '자료 파일 일부를 읽지 못했습니다. 잠시 뒤 [갱신]을 눌러 주십시오. (' + (err && err.message ? err.message : err) + ')'; } })
      .finally(runAll);
  };
  window.foDash = { S, D, run, runAll };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
})();
