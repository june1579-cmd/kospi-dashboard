// 연구소 조합 매매 확인(2026-11-24 사용자 지시, deriv-research deriv/labweb/AGENT.md)
// 그래프는 코스피 대시보드 '한눈에 보기'(docs/page.html)의 거래일 축·눈금 거르기·값 보기·기간 단추·확대·이동 방식을 떼어 쓰고,
// 터치(두 손가락 확대·축소, 밀기, 한 번 터치 = 값)는 docs/gesture.js 를 그대로 복사한 ./gesture.js 가 맡는다(#all-chart 의 _rvApi·_rvPlot·_rvShow·_rvHide).
// 자료: data/combos.json·trades.json·prices.json·meta.json (deriv/labweb/export.py 가 X1 결과에서 내보냄). 없는 것은 추정하지 않고 '거래 내역 없음'.
(function(){
  'use strict';
  const $ = id => document.getElementById(id);
  const box = $('all-chart');
  const SLOTS = ['var(--s1)', 'var(--s2)', 'var(--s3)', 'var(--s4)', 'var(--s5)'];
  const SRC_NAME = {A: '갈래 A', B: '갈래 B', C: '갈래 C(미국·한국 연동)', D: '갈래 D(하락 전담)', S: 'Signal A 관찰 목록'};
  const SRC_SHORT = {A: 'A', B: 'B', C: 'C', D: 'D', S: 'SA'};
  const SRC_ORD = {S: 0, A: 1, B: 2, C: 3, D: 4};
  const F_NAME = ['① 다음 해 기준', '② 2026년·큰 변동 해', '③ 반증 8개 모두', '④ 가짜 p < 1%'];
  let combos = [], trades = {}, PX = null, meta = {}, days = [], fIdx = new Map(), dIdx = new Map(), byKey = new Map();
  let i0 = 0, i1 = 0, range = 'y2';
  const sel = [];                 // 고른 순서
  const slot = new Map();         // key → 색 칸(고른 동안 그대로)
  const filt = {src: '', grade: '', has: false, all4: false, q: ''};
  let sortK = 'default', sortDir = 1;

  // ---------------------------------------------------------------- 글자
  const pct1 = (v, n) => (v == null || (n != null && n < 10)) ? '–' : (v * 100).toFixed(1) + '%';
  const spp = (v, n) => (v == null || (n != null && n < 10)) ? '–' : (v >= 0 ? '+' : '−') + Math.abs(v * 100).toFixed(1) + '%p';
  const sp = (v, d = 1) => v == null ? '–' : (v >= 0 ? '+' : '−') + Math.abs(v * 100).toFixed(d) + '%';
  const f2 = d3.format(',.2f'), f0 = d3.format(',.0f');
  const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
  // 신호 색 고르기(2026-11-24 사용자 요청 "신호 색상 선택가능하도록"): 고른 조합마다 범례·상세의 색 칸을 눌러 바꾼다. 이 브라우저에 기억(조합별)
  const PRESET = ['#2a78d6', '#eb6834', '#1baf7a', '#6250d6', '#e87ba4', '#d62828', '#2e7d32', '#1e3a8a', '#0e7490', '#c026d3', '#8b5e34', '#6b7280'];   // 노랑은 뺐다
  const custom = new Map();
  try { Object.entries(JSON.parse(localStorage.getItem('lab_colors') || '{}')).forEach(([k, v]) => { if (/^#[0-9a-f]{6}$/i.test(v)) custom.set(k, v); }); } catch (e) {}
  const saveColors = () => { try { localStorage.setItem('lab_colors', JSON.stringify(Object.fromEntries(custom))); } catch (e) {} };
  const colorOf = k => custom.get(k) || SLOTS[slot.get(k)];

  // ---------------------------------------------------------------- 자료 읽기
  async function load(){
    try {
      const get = f => fetch('data/' + f, {cache: 'no-cache'}).then(r => { if (!r.ok) throw new Error(f + ' ' + r.status); return r.json(); });
      [combos, trades, PX, meta] = await Promise.all([get('combos.json'), get('trades.json'), get('prices.json'), get('meta.json')]);
    } catch (e) {
      $('err').hidden = false; $('err').textContent = '자료를 읽지 못했습니다(' + e.message + '). 잠시 뒤 다시 열어 주세요.'; $('asof').textContent = '';
      return;
    }
    days = PX.kospi.d; days.forEach((d, i) => dIdx.set(d, i)); PX.fut.d.forEach((d, i) => fIdx.set(d, i));
    combos.forEach(c => byKey.set(c.key, c));
    const nT = combos.filter(c => c.has_trades).length;
    $('asof').textContent = '자료 끝 ' + (meta.data_end || '–') + ' · 내보낸 때 ' + (meta.at || '–');
    $('lede').textContent = '연구소 갈래 A·B·C·D 상위 조합 ' + combos.filter(c => c.src !== 'S').length + '개(X1 거름 시험 대상)와 Signal A 관찰 목록 '
      + combos.filter(c => c.src === 'S').length + '개 — 그래프 표시 가능 ' + nT + '개 · 거래 내역 없음 ' + (combos.length - nT)
      + '개(거래일 기록이 남아 있지 않아 추정하지 않음). 표에서 줄을 누르면 그 조합의 매수일·매도일이 두 그래프에 표시됩니다.';
    try { const m = /s=([^&]+)/.exec(location.hash); if (m) decodeURIComponent(m[1]).split(',').forEach(k => { if (byKey.has(k) && sel.length < 5) pick(k, true); }); } catch (e) {}
    pickRange(range, true);
    buildHead(); fillTable(); fillDetail(); legend(); draw();
  }

  // ---------------------------------------------------------------- 기간
  function startIdx(r){
    const last = days[days.length - 1], y = +last.slice(0, 4), md = last.slice(4);
    const back = {y5: [5, 0], y2: [2, 0], y1: [1, 0], m6: [0, 6], m3: [0, 3]}[r];
    let s;
    if (r === 'all' || !back) s = '2010-01-01';
    else { const dt = new Date(Date.UTC(y - back[0], +md.slice(1, 3) - 1 - back[1], +md.slice(4, 6))); s = dt.toISOString().slice(0, 10); }
    const i = d3.bisectLeft(days, s); return Math.max(0, Math.min(days.length - 1, i));
  }
  function pickRange(r, quiet){
    range = r; i1 = days.length - 1; i0 = startIdx(r);
    document.querySelectorAll('#range button').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.r === range)));
    if (!quiet) draw();
  }
  function setView(s, len){
    const last = days.length - 1; len = Math.max(10, Math.min(days.length, Math.round(len))); s = Math.max(0, Math.min(last - len + 1, Math.round(s)));
    if (s === i0 && s + len - 1 === i1) return false;
    i0 = s; i1 = s + len - 1; range = null;
    document.querySelectorAll('#range button').forEach(b => b.setAttribute('aria-pressed', 'false'));
    return true;
  }
  function zoomTo(kind){                       // 한눈에 보기 zoomTo 와 같은 규칙
    const n = i1 - i0 + 1, last = days.length - 1; let len = n, s;
    if (kind === 'in') len = Math.max(10, Math.round(n / 1.6));
    if (kind === 'out') len = Math.min(days.length, Math.round(n * 1.6));
    if (kind === 'left' || kind === 'right') { const sh = Math.max(1, Math.round(n / 3)); s = i0 + (kind === 'left' ? -sh : sh); }
    else s = i1 >= last ? last - len + 1 : Math.round((i0 + i1) / 2 - (len - 1) / 2);
    if (setView(s, len)) draw();
  }
  document.querySelectorAll('#range button').forEach(b => b.addEventListener('click', () => pickRange(b.dataset.r)));
  document.querySelectorAll('#zoom button').forEach(b => b.addEventListener('click', () => zoomTo(b.dataset.z)));

  // ---------------------------------------------------------------- 그래프
  let tip = null, rule = null, G = null;      // G = 마지막 그림의 좌표 정보(값 보기용)
  function events(){                          // 고른 조합별 {날짜 위치 → 사건}
    return sel.filter(k => trades[k] && trades[k].length).map(k => {
      const m = new Map();
      trades[k].forEach(t => {
        const bi = dIdx.get(t[1]), ei = dIdx.get(t[3]); if (bi == null || ei == null) return;
        for (let i = bi; i <= ei; i++) if (!m.has(i)) m.set(i, {k: 'hold', t});
        m.set(bi, {k: 'buy', t}); m.set(ei, {k: bi === ei ? 'both' : 'sell', t});
      });
      return {key: k, c: byKey.get(k), m};
    });
  }
  function ticksFor(a, b, xf, L, R){
    const n = b - a + 1, out = [], cw = 7.2;
    let mode = n > 900 ? 'y' : n > 160 ? 'm' : 'd';
    const cand = [];
    for (let i = Math.max(1, a); i <= b; i++) {
      const d = days[i], p = days[i - 1];
      if (mode === 'y' && d.slice(0, 4) !== p.slice(0, 4)) cand.push([i, d.slice(0, 4)]);
      if (mode === 'm' && d.slice(0, 7) !== p.slice(0, 7)) { const mo = +d.slice(5, 7); cand.push([i, mo === 1 ? d.slice(2, 4) + '년 1월' : mo + '월']); }
      if (mode === 'd' && (d.slice(0, 7) !== p.slice(0, 7) || (i - a) % 10 === 0)) cand.push([i, (+d.slice(5, 7)) + '/' + (+d.slice(8, 10))]);
    }
    let lastR = -Infinity, lastY = null;   // 한눈에 보기 fitTicks 처럼: 남긴 첫 눈금과 해가 바뀐 첫 눈금에 연도
    cand.forEach(([i, lab]) => {
      const yy = days[i].slice(0, 4);
      if (mode !== 'y' && !/년/.test(lab) && yy !== lastY) lab = yy.slice(2) + '년 ' + lab;
      const w = lab.length * cw, px = xf(i), Lx = px - w / 2;
      if (Lx < L - 2 || px + w / 2 > R + 30) return;
      if (Lx > lastR + 10) { out.push([i, lab, px]); lastR = Lx + w; lastY = yy; }
    });
    return out;
  }
  function draw(){
    if (!days.length) return;
    box.querySelectorAll('svg,.tip').forEach(n => n.remove());
    const W = Math.max(300, box.clientWidth), mob = W < 560;
    const ml = mob ? 46 : 58, mr = mob ? 8 : 14, H1 = mob ? 230 : 290, H2 = mob ? 150 : 190, T1 = 22, T2 = T1 + H1 + 30, B2 = T2 + H2, H = B2 + 26;
    const L = ml, R = W - mr, n = i1 - i0 + 1, step = (R - L) / Math.max(1, n - 1);
    const xf = i => L + (i - i0) * step;
    const pad = Math.ceil(n / 2), a = Math.max(0, i0 - pad), b = Math.min(days.length - 1, i1 + pad);   // 손가락으로 밀 때 빈 곳이 덜 보이게 양옆을 조금 더 그린다(칸 밖은 잘림)
    box._rvPlot = [L, R];
    const K = PX.kospi, F = PX.fut;
    const fv = (arr, i) => { const j = fIdx.get(days[i]); return j == null ? null : arr[j]; };
    const ext = (lo, hi, get) => { let mn = Infinity, mx = -Infinity; for (let i = i0; i <= i1; i++) { const l = get(lo, i), h = get(hi, i); if (l != null && l < mn) mn = l; if (h != null && h > mx) mx = h; } return mn < mx ? [mn, mx] : [0, 1]; };
    const e1 = ext(K.l, K.h, (arr, i) => arr[i]), e2 = ext(F.l, F.h, fv);
    const padY = e => { const d = e[1] - e[0]; return [e[0] - d * 0.1, e[1] + d * 0.05]; };   // 아래는 매수 ▲ 자리만큼 더
    const y1 = d3.scaleLinear(padY(e1), [T1 + H1, T1 + 4]), y2 = d3.scaleLinear(padY(e2), [B2, T2 + 4]);
    const svg = d3.select(box).append('svg').attr('width', '100%').attr('viewBox', `0 0 ${W} ${H}`).attr('height', H);
    const cid = 'labclip' + Math.random().toString(36).slice(2, 8);
    svg.append('defs').append('clipPath').attr('id', cid).append('rect').attr('x', L).attr('y', 0).attr('width', R - L).attr('height', H);
    // 가로 눈금선·축 숫자(제자리)
    [[y1, 5, T1, T1 + H1], [y2, 4, T2, B2]].forEach(([y, k]) => {
      const tk = y.ticks(k);
      svg.append('g').selectAll('line').data(tk).join('line').attr('x1', L).attr('x2', R).attr('y1', d => y(d)).attr('y2', d => y(d)).style('stroke', 'var(--chart-grid)');
      svg.append('g').selectAll('text').data(tk).join('text').attr('class', 'tick').attr('x', L - 6).attr('y', d => y(d) + 4).attr('text-anchor', 'end').text(d => f0(d));
    });
    svg.append('text').attr('class', 'rv-ptitle ptitle').attr('x', L).attr('y', T1 - 8).text('코스피');
    svg.append('text').attr('class', 'rv-ptitle ptitle').attr('x', L).attr('y', T2 - 8).text('코스피200 선물(연속)');
    const plot = svg.append('g').attr('clip-path', `url(#${cid})`);
    // 세로 날짜선
    const tks = ticksFor(i0, i1, xf, L, R);
    plot.append('g').selectAll('line').data(tks).join('line').attr('x1', d => d[2]).attr('x2', d => d[2]).attr('y1', T1).attr('y2', B2).style('stroke', 'var(--chart-grid)').style('stroke-dasharray', '2 3');
    // 보유 기간 띠
    const EV = events();
    EV.forEach(({key}) => {
      const col = colorOf(key), g = plot.append('g');
      trades[key].forEach(t => {
        const bi = dIdx.get(t[1]), ei = dIdx.get(t[3]); if (bi == null || ei == null || ei < a || bi > b) return;
        const x0 = xf(bi) - step / 2, w = Math.max(2, xf(ei) - xf(bi) + step);
        [[T1, H1], [T2, H2]].forEach(([top, h]) => g.append('rect').attr('x', x0).attr('y', top).attr('width', w).attr('height', h).style('fill', col).style('opacity', 0.13));
      });
    });
    // 종가 선
    const idx = d3.range(a, b + 1);
    plot.append('path').datum(idx).attr('d', d3.line().x(xf).y(i => y1(K.c[i]))).style('fill', 'none').style('stroke', 'var(--chart-line)').style('stroke-width', 1.5);
    plot.append('path').datum(idx).attr('d', d3.line().defined(i => fv(F.c, i) != null).x(xf).y(i => y2(fv(F.c, i)))).style('fill', 'none').style('stroke', 'var(--chart-line)').style('stroke-width', 1.5);
    // 매수 ▲(다음 날 시가) · 매도 ●맞음 ○틀림(청산일 종가)
    const big = n <= 1300, r = big ? 4.5 : 3.2, tri = big ? 9 : 7;
    EV.forEach(({key}) => {
      const col = colorOf(key), g = plot.append('g');
      trades[key].forEach(t => {
        const bi = dIdx.get(t[1]), ei = dIdx.get(t[3]); if (bi == null || ei == null || ei < a || bi > b) return;
        const ok = t[7] === 1;
        const pts = [[y1, t[2], t[4]], [y2, fv(F.o, bi), fv(F.c, ei)]];
        pts.forEach(([y, bp, spx]) => {
          if (bp != null) { const x = xf(bi), yy = y(bp) + tri * 0.9; g.append('path').attr('d', `M${x},${yy - tri * 0.55}L${x + tri * 0.6},${yy + tri * 0.5}L${x - tri * 0.6},${yy + tri * 0.5}Z`).style('fill', col).style('stroke', 'var(--color-panel)').style('stroke-width', 1.2); }
          if (spx != null) g.append('circle').attr('cx', xf(ei)).attr('cy', y(spx)).attr('r', r).style('fill', ok ? col : 'var(--color-panel)').style('stroke', ok ? 'var(--color-panel)' : col).style('stroke-width', ok ? 1.2 : 2);
        });
      });
    });
    // 날짜 글자(아래)
    svg.append('g').selectAll('text').data(tks).join('text').attr('class', 'tick').attr('x', d => d[2]).attr('y', B2 + 18).attr('text-anchor', 'middle').text(d => d[1]);
    svg.append('line').attr('x1', L).attr('x2', R).attr('y1', T1 + H1).attr('y2', T1 + H1).style('stroke', 'var(--chart-axis)');
    svg.append('line').attr('x1', L).attr('x2', R).attr('y1', B2).attr('y2', B2).style('stroke', 'var(--chart-axis)');
    // 값 보기
    rule = svg.append('line').attr('y1', T1).attr('y2', B2).style('stroke', 'var(--chart-ref)').style('pointer-events', 'none').attr('opacity', 0);
    const hit = svg.append('rect').attr('x', L).attr('y', T1).attr('width', R - L).attr('height', B2 - T1).style('fill', 'transparent').style('cursor', 'grab');
    tip = el('div', 'tip'); tip.hidden = true; box.appendChild(tip);
    G = {L, R, step, xf, EV, T1, B2};
    hit.on('mousemove', ev => { if (!drag) show(d3.pointer(ev, svg.node())[0], d3.pointer(ev, box)[1]); }).on('mouseleave', hide);
    hit.on('mousedown', ev => { ev.preventDefault(); drag = {x: ev.clientX, s: i0, len: i1 - i0 + 1, step}; hide(); hit.style('cursor', 'grabbing'); });
    $('win').textContent = days[i0] + ' ~ ' + days[i1] + ' · ' + n + '거래일';
  }
  function show(x, y){
    if (!G || !tip) return false;
    const i = Math.max(i0, Math.min(i1, Math.round(i0 + (x - G.L) / G.step))), d = days[i], K = PX.kospi, F = PX.fut, j = fIdx.get(d);
    const xi = G.xf(i); rule.attr('x1', xi).attr('x2', xi).attr('opacity', 1);
    tip.replaceChildren(el('div', 'h', d));
    const row = (col, name, val, hollow) => { const r = el('div', 'r'); if (col) { const s = el('span', 'sw'); if (hollow) { s.style.border = '2px solid ' + col; } else s.style.background = col; r.appendChild(s); } r.append(el('span', null, name), el('b', null, val)); tip.appendChild(r); };
    const chg = i > 0 ? K.c[i] / K.c[i - 1] - 1 : null;
    row(null, '코스피', f2(K.c[i]) + (chg != null ? ' (' + sp(chg, 2) + ')' : ''));
    row(null, '선물', j != null ? f2(F.c[j]) : '확인 불가');
    G.EV.forEach(({key, m}) => {
      const e = m.get(i); if (!e) return; const t = e.t, col = colorOf(key);
      if (e.k === 'buy') row(col, key + ' 매수', f2(t[2]));
      else if (e.k === 'sell' || e.k === 'both') row(col, key + ' 매도', f2(t[4]) + ' · ' + sp(t[6]) + (t[7] ? ' 맞음' : ' 틀림'), !t[7]);
      else row(col, key + ' 보유 중', t[1] + ' 매수');
    });
    tip.hidden = false;
    const bw = box.clientWidth, w = tip.offsetWidth; let left = xi + 14; if (left + w > bw) left = Math.max(0, xi - 14 - w);
    tip.style.left = left + 'px'; tip.style.top = Math.max(0, Math.min(y - 12, box.clientHeight - tip.offsetHeight)) + 'px';
    return true;
  }
  function hide(){ if (tip) tip.hidden = true; if (rule) rule.attr('opacity', 0); }
  // 마우스로 끌어 이동
  let drag = null, dragRaf = 0;
  window.addEventListener('mousemove', ev => {
    if (!drag) return;
    const sv = box.querySelector('svg'); if (!sv) return;
    const sh = Math.round(-(ev.clientX - drag.x) * (sv.viewBox.baseVal.width / Math.max(1, sv.getBoundingClientRect().width)) / drag.step);
    if (dragRaf) return; dragRaf = requestAnimationFrame(() => { dragRaf = 0; if (drag && setView(drag.s + sh, drag.len)) draw(); });
  });
  window.addEventListener('mouseup', () => { if (drag) { drag = null; const h = box.querySelector('svg rect[style*="grab"]'); if (h) h.style.cursor = 'grab'; } });
  // gesture.js 가 쓰는 길(한눈에 보기와 같은 이름)
  box._rvApi = {days: () => days, idx: () => [i0, i1], draw: () => draw(), set(s, len){ if (!setView(s, len)) return false; draw(); return true; }};
  box._rvShow = (x, y) => show(x, y);
  box._rvHide = hide;
  let rz = 0; window.addEventListener('resize', () => { clearTimeout(rz); rz = setTimeout(draw, 120); });

  // ---------------------------------------------------------------- 범례
  function legend(){
    const lg = $('legend'); lg.replaceChildren();
    sel.forEach(k => {
      const c = byKey.get(k), chip = el('span', 'chip');
      chip.append(swBtn(k), el('span', null, k + ' · ' + (c.name || c.grade) + (c.has_trades ? ' · ' + c.n + '거래' : ' · 거래 내역 없음')));
      const x = el('button', 'x', '✕'); x.type = 'button'; x.title = '그래프에서 끄기'; x.setAttribute('aria-label', k + ' 끄기'); x.addEventListener('click', () => pick(k));
      chip.appendChild(x); lg.appendChild(chip);
    });
    const ico = (svgTxt, txt) => { const s = el('span'); s.innerHTML = svgTxt; s.appendChild(document.createTextNode(txt)); lg.appendChild(s); };
    ico('<svg width="12" height="12" aria-hidden="true"><path d="M6,2L11,10L1,10Z" fill="currentColor"/></svg>', '매수(신호 다음 날 시가)');
    ico('<svg width="12" height="12" aria-hidden="true"><circle cx="6" cy="6" r="4.5" fill="currentColor"/></svg>', '맞은 매도');
    ico('<svg width="12" height="12" aria-hidden="true"><circle cx="6" cy="6" r="4" fill="none" stroke="currentColor" stroke-width="2"/></svg>', '틀린 매도(청산일 종가)');
    ico('<svg width="14" height="12" aria-hidden="true"><rect x="0" y="1" width="14" height="10" fill="currentColor" opacity=".25"/></svg>', '보유 기간');
    if (!sel.length) lg.appendChild(el('span', null, '· 아래 표에서 조합을 고르면 표시됩니다'));
  }

  // ---------------------------------------------------------------- 색 고르기
  function swBtn(k){
    const b = el('button', 'swb'); b.type = 'button'; b.title = '신호 색 바꾸기'; b.setAttribute('aria-label', k + ' 신호 색 바꾸기'); b.setAttribute('aria-haspopup', 'true');
    const dot = el('span', 'dot'); dot.style.background = colorOf(k); b.append(dot, el('span', null, '색'));
    b.addEventListener('click', e => { e.stopPropagation(); e.preventDefault(); openPal(k, b); }); return b;
  }
  let pal = null;
  function closePal(){ if (pal) { pal.remove(); pal = null; } }
  function setColor(k, v){ if (v) custom.set(k, v); else custom.delete(k); saveColors(); fillTable(); fillDetail(); legend(); draw(); }
  function openPal(k, anchor){
    const again = pal && pal.dataset.k === k; closePal(); if (again) return;
    pal = el('div', 'pal'); pal.dataset.k = k; pal.setAttribute('role', 'dialog'); pal.setAttribute('aria-label', k + ' 신호 색');
    pal.appendChild(el('div', 'pal-h', k + ' 신호 색'));
    const g = el('div', 'pal-g'), cur = custom.get(k);
    PRESET.forEach(v => { const b = el('button'); b.type = 'button'; b.style.background = v; b.title = v; b.setAttribute('aria-label', '색 ' + v);
      if (cur && cur.toLowerCase() === v) b.setAttribute('aria-pressed', 'true'); b.addEventListener('click', () => { closePal(); setColor(k, v); }); g.appendChild(b); });
    pal.appendChild(g);
    const row = el('div', 'pal-r'), lab = el('label'), inp = el('input'); inp.type = 'color';
    inp.value = cur || PRESET[slot.get(k)] || '#2a78d6'; inp.addEventListener('input', () => setColor(k, inp.value)); inp.addEventListener('change', closePal);
    lab.append(inp, document.createTextNode(' 직접 고르기')); row.appendChild(lab);
    const rs = el('button', 'pal-reset', '기본색'); rs.type = 'button'; rs.addEventListener('click', () => { closePal(); setColor(k, null); }); row.appendChild(rs);
    pal.appendChild(row); document.body.appendChild(pal);
    const r = anchor.getBoundingClientRect(), w = pal.offsetWidth;
    pal.style.left = Math.max(8, Math.min(window.scrollX + r.left, window.scrollX + document.documentElement.clientWidth - w - 8)) + 'px';
    pal.style.top = (window.scrollY + r.bottom + 6) + 'px';
    const first = pal.querySelector('button'); if (first) first.focus({preventScroll: true});
  }
  document.addEventListener('click', e => { if (pal && !pal.contains(e.target)) closePal(); });
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closePal(); });

  // ---------------------------------------------------------------- 고르기
  let toastT = 0;
  function toast(s){ $('toast').textContent = s; clearTimeout(toastT); toastT = setTimeout(() => { $('toast').textContent = ''; }, 3500); }
  function pick(k, quiet){
    const at = sel.indexOf(k);
    closePal();
    if (at >= 0) { sel.splice(at, 1); slot.delete(k); }
    else {
      if (sel.length >= 5) { toast('최대 5개까지 고를 수 있습니다 — 먼저 고른 것을 끄세요.'); return; }
      const used = new Set(slot.values()); let s = 0; while (used.has(s)) s++; slot.set(k, s); sel.push(k);
    }
    try { history.replaceState(null, '', sel.length ? '#s=' + encodeURIComponent(sel.join(',')) : location.pathname + location.search); } catch (e) {}
    if (quiet) return;
    fillTable(); fillDetail(); legend(); draw();
  }

  // ---------------------------------------------------------------- 표
  const COLS = [
    {k: 'pick', label: '', cls: 'pick'},
    {k: 'src', label: '갈래', sort: c => SRC_ORD[c.src] * 1000 + c.rank, title: '출처: 연구소 갈래 A·B·C·D 또는 Signal A 관찰 목록'},
    {k: 'rank', label: '순위', num: true, sort: c => c.rank, title: '그 갈래 안의 X1 순위(연구소 숫자 기준)'},
    {k: 'round', label: '회차', num: true, sort: c => c.round, title: '연구소 회차'},
    {k: 'grade', label: '등급', sort: c => ({'관찰 목록': 0, '통과': 1, '관찰': 2}[c.grade] ?? 3), title: '연구소 등급(코스피200 선물 기준)'},
    {k: 'desc', label: '조건 설명', sort: c => c.desc, cls: 'desc'},
    {k: 'n', label: '독립 거래', num: true, sort: c => c.n},
    {k: 'hit', label: '적중', num: true, sort: c => (c.n >= 10 ? c.hit : null)},
    {k: 'edge', label: '아무 날과 차이', num: true, sort: c => (c.n >= 10 ? c.edge : null), title: '적중 − 같은 해 아무 날 적중(해 구성 맞춤)'},
    {k: 'sum', label: '수익 합계', num: true, sort: c => c.sum, title: '거래별 수익률 단순 합(내림 조합은 지수 하락이 +)'},
    {k: 'avg', label: '1회 평균', num: true, sort: c => c.avg},
    {k: 'last', label: '최근 신호일', num: true, sort: c => c.last},
    {k: 'f', label: '네 거름', sort: c => (c.has_trades ? c.f.filter(Boolean).length + (c.all4 ? 0.5 : 0) : null), title: '①②③④ 통과 여부'},
  ];
  const NARROW = matchMedia('(max-width:700px)');
  function cols(){                             // 휴대폰: 숫자를 먼저 보이게 조건 설명을 맨 뒤로, 회차는 뺀다(상세에 있음)
    if (!NARROW.matches) return COLS;
    return COLS.filter(c => c.k !== 'round' && c.k !== 'desc').concat(COLS.filter(c => c.k === 'desc'));
  }
  NARROW.addEventListener && NARROW.addEventListener('change', () => { buildHead(); fillTable(); });
  function buildHead(){
    const tr = el('tr');
    cols().forEach(c => {
      const th = el('th', (c.num ? 'num ' : '') + (c.sort ? 'sort' : ''), c.label); if (c.title) th.title = c.title;
      if (c.sort) { th.tabIndex = 0; th.setAttribute('role', 'button'); const ar = el('span', 'ar'); th.dataset.k = c.k; th.appendChild(ar);
        const go = () => { if (sortK === c.k) sortDir = -sortDir; else { sortK = c.k; sortDir = c.num || c.k === 'f' ? -1 : 1; } fillTable(); };
        th.addEventListener('click', go); th.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(); } }); }
      tr.appendChild(th);
    });
    document.querySelector('#combo-tbl thead').replaceChildren(tr);
  }
  function rows(){
    const q = filt.q.trim().toLowerCase();
    let L = combos.filter(c => (!filt.src || c.src === filt.src) && (!filt.grade || c.grade === filt.grade) && (!filt.has || c.has_trades) && (!filt.all4 || c.all4)
      && (!q || (c.key + ' ' + c.id + ' ' + c.desc + ' ' + (c.name || '') + ' ' + (c.family || '')).toLowerCase().includes(q)));
    const dflt = (a, b) => (SRC_ORD[a.src] - SRC_ORD[b.src]) || (a.rank - b.rank);
    if (sortK === 'default') return L.sort(dflt);
    const col = COLS.find(c => c.k === sortK), v = c => { const x = col.sort(c); return (x === undefined || x === null || (typeof x === 'number' && !isFinite(x))) ? null : x; };
    return L.sort((a, b) => { const va = v(a), vb = v(b); if (va === null && vb === null) return dflt(a, b); if (va === null) return 1; if (vb === null) return -1;
      const r = typeof va === 'string' ? va.localeCompare(vb, 'ko') : va - vb; return r * sortDir || dflt(a, b); });
  }
  function fillTable(){
    document.querySelectorAll('#combo-tbl th.sort').forEach(th => { th.querySelector('.ar').textContent = th.dataset.k === sortK ? (sortDir > 0 ? '▲' : '▼') : ''; th.setAttribute('aria-sort', th.dataset.k === sortK ? (sortDir > 0 ? 'ascending' : 'descending') : 'none'); });
    const tb = document.querySelector('#combo-tbl tbody'), L = rows(), frag = document.createDocumentFragment();
    L.forEach(c => {
      const tr = el('tr', (sel.includes(c.key) ? 'on' : '') + (c.has_trades ? '' : ' none')); tr.tabIndex = 0;
      const td = (t, cls) => { const x = el('td', cls, t); tr.appendChild(x); return x; };
      const NUMK = ['hit', 'edge', 'sum', 'avg', 'last'];
      cols().forEach(col => {
        const k = col.k;
        if (k === 'pick') {
          const cell = td(null, 'pick');
          if (sel.includes(c.key)) {                // 고른 줄의 색 칸 = 색 바꾸기(줄의 다른 곳을 누르면 끄기)
            const pk = el('button', 'pk pkb'); pk.type = 'button'; pk.title = '신호 색 바꾸기'; pk.setAttribute('aria-label', c.key + ' 신호 색 바꾸기');
            pk.style.background = colorOf(c.key); pk.style.borderColor = colorOf(c.key);
            pk.addEventListener('click', e => { e.stopPropagation(); openPal(c.key, pk); }); cell.appendChild(pk);
          } else cell.appendChild(el('span', 'pk'));
        }
        else if (k === 'src') td(SRC_SHORT[c.src], 'src');
        else if (k === 'rank') td(c.src === 'S' ? '#' + c.rank : String(c.rank), 'num');
        else if (k === 'round') td(c.round != null ? c.round + '회' : '–', 'num');
        else if (k === 'grade') td(null).appendChild(el('span', 'tag' + (c.grade === '통과' || c.grade === '관찰 목록' ? ' pass' : ''), c.grade));
        else if (k === 'desc') { const dd = td(null, 'desc'); dd.title = c.desc; dd.appendChild(el('div', null, (c.name ? c.name + ' — ' : '') + c.desc)); }
        else if (!c.has_trades) { if (k === 'n') { const x = td('거래 내역 없음', 'muted'); x.colSpan = 6; } else if (k === 'f') td('–', 'f4'); }
        else if (k === 'n') td(String(c.n), 'num');
        else if (NUMK.includes(k)) td({hit: pct1(c.hit, c.n), edge: spp(c.edge, c.n), sum: sp(c.sum), avg: sp(c.avg, 2), last: c.last || '–'}[k], 'num');
        else if (k === 'f') { const f = td(c.f.map(x => x ? '●' : '○').join(''), 'f4'); f.title = c.f.map((x, i) => F_NAME[i] + ' ' + (x ? '통과' : '못 넘음')).join('\n'); }
      });
      tr.addEventListener('click', () => pick(c.key)); tr.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pick(c.key); } });
      frag.appendChild(tr);
    });
    tb.replaceChildren(frag);
    $('count').textContent = combos.length + '개 중 ' + L.length + '개 표시 · 고른 것 ' + sel.length + '/5';
  }
  function segFilter(id, k){ document.querySelectorAll('#' + id + ' button').forEach(b => b.addEventListener('click', () => {
    filt[k] = b.dataset.v; document.querySelectorAll('#' + id + ' button').forEach(x => x.setAttribute('aria-pressed', String(x === b))); fillTable(); })); }
  segFilter('f-src', 'src'); segFilter('f-grade', 'grade');
  $('f-has').addEventListener('change', e => { filt.has = e.target.checked; fillTable(); });
  $('f-all4').addEventListener('change', e => { filt.all4 = e.target.checked; fillTable(); });
  let qt = 0; $('f-q').addEventListener('input', e => { clearTimeout(qt); qt = setTimeout(() => { filt.q = e.target.value; fillTable(); }, 120); });

  // ---------------------------------------------------------------- 고른 조합 상세
  function exactList(o){
    const ul = el('ul');
    Object.entries(o).forEach(([k, v]) => {
      const li = el('li'); li.appendChild(el('b', null, k.replace(/_/g, ' ') + ': '));
      if (v && typeof v === 'object' && !Array.isArray(v)) li.appendChild(exactList(v));
      else li.appendChild(document.createTextNode(Array.isArray(v) ? v.join(' · ') : String(v)));
      ul.appendChild(li);
    });
    return ul;
  }
  function focusTrade(t){
    const bi = dIdx.get(t[1]), ei = dIdx.get(t[3]); if (bi == null || ei == null) return;
    const len = Math.max(40, Math.min(250, i1 - i0 + 1)); setView(Math.round((bi + ei) / 2 - len / 2), len); draw();
    box.scrollIntoView({behavior: 'smooth', block: 'center'});
  }
  function fillDetail(){
    const det = $('det'); det.replaceChildren();
    if (!sel.length) { det.appendChild(el('p', 'empty', '표에서 줄을 누르면 조건 전문과 거래 내역이 여기에 나옵니다.')); return; }
    sel.forEach(k => {
      const c = byKey.get(k), d = el('div', 'dcard'); d.style.setProperty('--c', colorOf(k));
      const h = el('h3');
      h.append(swBtn(k), document.createTextNode(k + ' · ' + SRC_NAME[c.src] + (c.src === 'S' ? ' ' + c.rank + '번 ' + c.name : ' ' + c.rank + '위')), el('span', 'tag' + (c.grade === '통과' || c.grade === '관찰 목록' ? ' pass' : ''), c.grade));
      const off = el('button'); off.type = 'button'; off.className = 'tag'; off.style.cursor = 'pointer'; off.style.background = 'transparent'; off.style.color = 'inherit'; off.textContent = '끄기 ✕'; off.addEventListener('click', () => pick(k)); h.appendChild(off);
      d.appendChild(h); d.appendChild(el('div', 'code', c.id));
      const cond = el('div', 'cond'); cond.appendChild(el('div', null, c.desc));
      if (c.exact) { try { cond.appendChild(exactList(JSON.parse(c.exact))); } catch (e) {} }
      d.appendChild(cond);
      const kv = el('div', 'kv'), put = (a, b) => { const r = el('div'); r.append(el('span', null, a), el('span', null, b)); kv.appendChild(r); };
      kv.appendChild(el('h4', null, '출처'));
      put('갈래', SRC_NAME[c.src]); if (c.round != null) put('연구소 회차', c.round + '회'); if (c.family) put('가족', c.family);
      put('방향', c.dir > 0 ? '오름(지수 상승이 맞음)' : '내림(지수 하락이 맞음)'); put('거래일 출처', c.trade_src + (c.trade_note ? ' — ' + c.trade_note : ''));
      if (c.lab) {
        kv.appendChild(el('h4', null, '연구소 숫자(코스피200 선물 기준, 순위·등급을 매긴 숫자)'));
        put('전체', (c.lab.all_n ?? '–') + '건 · ' + pct1(c.lab.all_hit, c.lab.all_n) + ' · 윌슨 하한 ' + pct1(c.lab.all_lb));
        put('앞 구간 2010~2023', (c.lab.dev_n ?? '–') + '건 · ' + pct1(c.lab.dev_hit, c.lab.dev_n)); put('뒤 구간 2024~', (c.lab.p2_n ?? '–') + '건 · ' + pct1(c.lab.p2_hit, c.lab.p2_n));
      }
      if (c.has_trades) {
        kv.appendChild(el('h4', null, '코스피 지수 기준(' + (c.src === 'S' && c.rank > 1 ? '2016~2026 해마다 그 전 자료로 고른 절차' : '2010~2026-11-20 독립 거래') + ')'));
        put('독립 거래 · 적중', c.n + '건 · ' + pct1(c.hit, c.n)); put('같은 해 아무 날 · 차이', pct1(c.base, c.n) + ' · ' + spp(c.edge, c.n));
        put('수익 합계 · 1회 평균', sp(c.sum) + ' · ' + sp(c.avg, 2));
        put('앞 · 뒤 구간', (c.p1[0] ?? '–') + '건 ' + pct1(c.p1[1], c.p1[0]) + ' · ' + (c.p2[0] ?? '–') + '건 ' + pct1(c.p2[1], c.p2[0]));
        put('신호 수 · 보유일 가운뎃값', c.n_sig + '번 · ' + (c.hold ?? '–') + '일'); put('최근 신호일', c.last || '–');
        kv.appendChild(el('h4', null, '네 거름' + (c.src === 'S' ? '(Signal A S3 판정)' : '(X1 판정)')));
        c.f.forEach((x, i) => put(F_NAME[i], (x ? '● 통과' : '○ 못 넘음') + (i === 1 && c.big_na ? '(큰 변동 해 판정 불가)' : '') + (i === 2 && c.falsify ? ' · 버틴 수 ' + c.falsify : '') + (i === 3 && c.p != null ? ' · p ' + c.p.toFixed(4) : '')));
        if (c.overlap) put('관찰 목록과 겹침', c.overlap);
      }
      d.appendChild(kv);
      if (c.caution && c.caution.length) { const ul = el('ul', 'note'); c.caution.forEach(s => ul.appendChild(el('li', null, s))); d.appendChild(el('div', 'note', '조심할 점')); d.appendChild(ul); }
      const T = trades[k];
      if (!c.has_trades || !T || !T.length) d.appendChild(el('p', 'empty', '거래 내역 없음 — 이 조합은 거래일 기록이 남아 있지 않아 그래프에 표시하지 않습니다(추정하지 않음).' + (c.trade_note ? ' ' + c.trade_note : '')));
      else {
        d.appendChild(el('div', 'note', '거래 내역 ' + T.length + '건(독립 거래) — 줄을 누르면 그래프가 그 거래로 옮겨 갑니다.' + (c.dir < 0 ? ' 내림 조합이라 수익률은 지수 하락이 +입니다.' : '')));
        const w = el('div', 'trw'), tb = el('table'), th = el('thead'), hr = el('tr');
        const heads = ['#', '신호일', '매수일', '매수가', '매도일', '매도가'].concat(c.dir < 0 ? ['코스피 등락'] : []).concat(['수익률', '맞음']);
        heads.forEach((s, i) => hr.appendChild(el('th', i === 0 || i === 3 || i === 5 || i >= 6 ? 'num' : '', s))); th.appendChild(hr); tb.appendChild(th);
        const body = el('tbody');
        T.slice().reverse().forEach((t, j) => {
          const r = el('tr'), cell = (s, cls) => r.appendChild(el('td', cls, s));
          cell(String(T.length - j), 'num'); cell(t[0]); cell(t[1]); cell(f2(t[2]), 'num'); cell(t[3]); cell(f2(t[4]), 'num');
          if (c.dir < 0) cell(sp(t[5], 2), 'num');
          cell(sp(t[6], 2), 'num'); cell(t[7] ? '● 맞음' : '○ 틀림', 'num');
          r.addEventListener('click', () => focusTrade(t)); body.appendChild(r);
        });
        tb.appendChild(body); w.appendChild(tb); d.appendChild(w);
      }
      det.appendChild(d);
    });
  }

  load();
})();
