// 연구소 조합 매매 확인(2026-11-24 사용자 지시, deriv-research deriv/labweb/AGENT.md)
// 그래프는 코스피 대시보드 '한눈에 보기'(docs/page.html)의 거래일 축·눈금 거르기·값 보기·기간 단추·확대·이동 방식을 떼어 쓰고,
// 터치(두 손가락 확대·축소, 밀기, 한 번 터치 = 값)는 docs/gesture.js 를 그대로 복사한 ./gesture.js 가 맡는다(#all-chart 의 _rvApi·_rvPlot·_rvShow·_rvHide).
// 자료: data/combos.json·trades.json·prices.json·meta.json (deriv/labweb/export.py 가 X1 결과에서 내보냄). 없는 것은 추정하지 않고 '거래 내역 없음'.
(function(){
  'use strict';
  const $ = id => document.getElementById(id);
  const box = $('all-chart');
  const MAXSEL = 10;   // 한 번에 그래프에 표시하는 조합 수(2026-11-24 빠른 고르기 비교용으로 5 → 10)
  const SRC_NAME = {A: '갈래 A', B: '갈래 B', C: '갈래 C(미국·한국 연동)', D: '갈래 D(하락 전담)', S: 'Signal A 관찰 목록', W: 'Signal A 2차(네 거름 통과)', K: '신뢰 가능 조건'};
  const SRC_SHORT = {A: 'A', B: 'B', C: 'C', D: 'D', S: 'SA', W: '2차'};
  const SRC_ORD = {S: 0, W: 1, A: 2, B: 3, C: 4, D: 5};
  const F_NAME = ['① 다음 해 기준', '② 2026년·큰 변동 해', '③ 반증 8개 모두', '④ 가짜 p < 1%'];
  let combos = [], trades = {}, PX = null, meta = {}, days = [], fIdx = new Map(), dIdx = new Map(), byKey = new Map();
  let i0 = 0, i1 = 0, range = 'y2';
  const sel = [];                 // 고른 순서
  const filt = {src: new Set(), grade: new Set(), has: false, all4: false, q: ''};   // 갈래·등급은 여러 개 고르기(2026-11-24 "복수 선택도 가능하게")
  const sorts = [];               // 정렬 기준 [{k, dir}] — 앞의 것이 먼저(2026-11-24 "모든 조합의 내용도 정렬할수 있도록 복수 선택도 가능하게")

  // ---------------------------------------------------------------- 글자
  const pct1 = (v, n) => (v == null || (n != null && n < 10)) ? '–' : (v * 100).toFixed(1) + '%';
  const spp = (v, n) => (v == null || (n != null && n < 10)) ? '–' : (v >= 0 ? '+' : '−') + Math.abs(v * 100).toFixed(1) + '%p';
  const sp = (v, d = 1) => v == null ? '–' : (v >= 0 ? '+' : '−') + Math.abs(v * 100).toFixed(d) + '%';
  const f2 = d3.format(',.2f'), f0 = d3.format(',.0f');
  const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
  // 매도 기준(2026-11-24 "매도 기준도 표시"): 새로 정하지 않고 원문에서만 —
  //  Signal A 관찰 목록 = exact 의 매수·매도 원문, 연구소 조합 = 조건 설명 끝 「→ N일 상승/하락」(연구소 lab_common.exit_after: 신호 다음 거래일을 1일째로 N거래일째 종가),
  //  그 꼴이 아니면(익절·손절, 만기까지, 큰 변동 먼저, 규칙별 보유일) 조건 설명의 청산 문구를 그대로. 실제 보유일은 거래 내역(매수일~매도일 거래일 수)에서 센다.
  const SELL = new Map();
  function holdDays(t){ const bi = dIdx.get(t[1]), ei = dIdx.get(t[3]); return bi == null || ei == null ? null : ei - bi + 1; }
  function sellInfo(c){
    if (SELL.has(c.key)) return SELL.get(c.key);
    let n = null, short, full;
    if (c.src === 'K') { short = '조합마다 다름'; full = '이 조건이 든 조합들의 대표 거래 — 매도는 그 거래를 낸 조합의 규칙대로'; }
    else if (c.src === 'W') {   // 2차 45개: 내보낼 때 원문에서 정한 매도 기준(sell_n·sell_full)을 그대로
      n = c.sell_n != null ? c.sell_n : null; short = n ? n + '거래일째 종가' : (/±5%/.test(c.sell_full || '') ? '±5% 먼저 닿는 날' : '규칙별 보유일'); full = c.sell_full || '확인 불가';
    } else if (c.src === 'S') {
      let ex = null; try { ex = JSON.parse(c.exact); } catch (e) {}
      n = ex && Number.isFinite(+ex['보유일']) ? +ex['보유일'] : null;
      short = n ? n + '거래일째 종가' : '확인 불가';
      full = ex && ex['매도'] ? '매수 ' + ex['매수'] + ' → 매도 ' + ex['매도'] + '(Signal A 규칙 원문)' : '확인 불가';
    } else {
      const at = c.desc.lastIndexOf('→'), tail = at >= 0 ? c.desc.slice(at + 1).trim() : '';
      const m = /^(\d+)\s*일\s*(상승|하락)$/.exec(tail), ns = [...c.desc.matchAll(/→\s*(\d+)일/g)].map(x => +x[1]);
      if (m) { n = +m[1]; short = n + '거래일째 종가'; full = '신호 다음 거래일 시가에 사서, 그날을 1일째로 세어 ' + n + '거래일째 종가에 판다(연구소 lab_common.exit_after).'; }
      else if (/각자 보유일/.test(c.desc) && ns.length > 1) { const u = [...new Set(ns)]; short = '규칙별 ' + u.join('·') + '거래일째'; full = '함께 쓰는 규칙마다 제 보유일(' + u.join('·') + '거래일째 종가)에 판다 — 먼저 난 신호부터, 보유 중 새 신호는 건너뜀(조건 설명 원문).'; }
      else if (tail) { const t2 = tail.replace(/\s*(상승|하락)$/, ''); short = t2; full = '조건 설명의 청산 규칙: ' + t2 + ' — 정해진 보유일이 아니라 거래마다 다름(조건 설명 원문).'; }
      else { short = '확인 불가'; full = '확인 불가'; }
    }
    const T = trades[c.key], hs = c.has_trades && T ? T.map(holdDays).filter(v => v != null).sort((a, b) => a - b) : [];
    const act = hs.length ? {min: hs[0], max: hs[hs.length - 1], med: hs.length % 2 ? hs[(hs.length - 1) / 2] : (hs[hs.length / 2 - 1] + hs[hs.length / 2]) / 2, n: hs.length} : null;
    const o = {n, short, full, act, sortv: n != null ? n : (act ? act.med : null)};
    SELL.set(c.key, o); return o;
  }
  // 조건 나누기(2026-11-24 "같은 조건들을 정렬해서 보기 위함, 조건 설명에서 조건을 선택하면 정렬기준으로 정렬창 범례로 표시")
  //  조건 설명을 글자 그대로 조각낸다(새 뜻을 붙이지 않음): 맨 앞 [꼬리표] · 맨 위 단계의 「+」「, 」로 나눈 조건 · 끝의 「→ …」(목표).
  //  B 갈래 「함께 쓰기[B: …→3일 | A: …→5일]」는 안쪽 조건을 「+」로 나눈다. Signal A 관찰 목록은 이름을 「 + 」로 나눈다. 조각을 이으면 원문과 같다.
  const TOKN = new Map();   // 조건 → 쓰인 조합 수
  const normT = t => t.replace(/\s+/g, ' ').trim();
  function parseDesc(c){
    const segs = [], toks = new Set();
    const txt = t => { if (t) segs.push({t}); };
    const tok = (t, k) => { const m = /^(\s*)([\s\S]*?)(\s*)$/.exec(t); txt(m[1]); k = normT(k != null ? k : m[2]); if (k) { segs.push({t: m[2], k}); toks.add(k); } else txt(m[2]); txt(m[3]); };
    const split = (str, comma) => { let dep = 0, buf = ''; for (let i = 0; i < str.length; i++) { const ch = str[i];
        if (ch === '(' || ch === '[') dep++; else if (ch === ')' || ch === ']') dep--;
        if (dep === 0 && (ch === '+' || (comma && ch === ',' && str[i + 1] === ' '))) { tok(buf); txt(ch); buf = ''; } else buf += ch; }
      tok(buf); };
    if (c.src === 'S') { (c.name || '').split(' + ').forEach((q, i) => { if (i) txt(' + '); tok(q); }); txt(' — ' + c.desc); return {segs, toks}; }
    const d = c.desc; let dep = 0, at = -1;
    for (let i = 0; i < d.length; i++) { const ch = d[i]; if (ch === '(' || ch === '[') dep++; else if (ch === ')' || ch === ']') dep--; else if (ch === '→' && dep === 0) at = i; }
    let head = at >= 0 ? d.slice(0, at) : d; const tail = at >= 0 ? d.slice(at) : '';
    let m; while ((m = /^(\s*)\[([^\[\]]*)\]/.exec(head))) { txt(m[1]); segs.push({t: '[' + m[2] + ']', k: normT(m[2])}); toks.add(normT(m[2])); head = head.slice(m[0].length); }
    const u = /^(\s*)(함께 쓰기)\[([\s\S]*)\]([\s\S]*)$/.exec(head);
    if (u) {
      txt(u[1]); tok(u[2]); txt('[');
      u[3].split('|').forEach((part, i) => { if (i) txt('|'); const pm = /^(\s*[A-Z]:\s*)?([\s\S]*?)(→\s*\d+일\s*)?$/.exec(part); txt(pm[1]); split(pm[2], false); txt(pm[3]); });
      txt(']'); txt(u[4]);
    } else split(head, true);
    if (tail) tok(tail, tail.replace(/^→\s*/, '→ '));
    return {segs, toks};
  }
  function condSegs(c){                         // 조건 설명을 누를 수 있는 조각으로
    const w = el('div', 'cdesc');
    c.segs.forEach(g => { if (!g.k) { w.appendChild(document.createTextNode(g.t)); return; }
      const x = el('span', 'ct', g.t); x.dataset.k = g.k; x.tabIndex = 0; x.setAttribute('role', 'button');
      x.title = '「' + g.k + '」 같은 조건끼리 모아 정렬(' + (TOKN.get(g.k) || 0) + '개 조합) — 다시 누르면 빼기';
      const go = e => { e.stopPropagation(); e.preventDefault(); toggleCond(g.k); };
      x.addEventListener('click', go); x.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') go(e); });
      w.appendChild(x); });
    return w;
  }
  function toggleCond(k){
    const i = sorts.findIndex(x => x.k === 'c:' + k);
    if (i < 0) { sorts.push({k: 'c:' + k, dir: -1}); toast('「' + k + '」 을 정렬 기준에 넣었습니다 — 들어간 조합 ' + (TOKN.get(k) || 0) + '개가 위로'); }
    else sorts.splice(i, 1);
    fillTable();
  }
  const actTxt = a => !a ? '거래 내역 없음' : (a.min === a.max ? a.min + '거래일(모든 거래 같음)' : '가운뎃값 ' + a.med + ' · 짧게 ' + a.min + ' ~ 길게 ' + a.max + '거래일') + ' · ' + a.n + '건';
  // 신호 색 고르기
  //  2026-11-24 "신호 색상 선택가능하도록" → 조합별 색
  //  2026-11-24 "매수 매도 맞고 틀리고 전부 색상을 따로 선택할수 있도록 조합이 추가되면 선택된 색상에서 2단계 낮은 색상으로 표시 후 선택할수 있도록"
  //   → 조합마다 네 가지 색(매수·맞은 거래 / 매수·틀린 거래 / 매도·맞음 / 매도·틀림). 색표는 색깔별 밝기 7단계(진함 → 연함).
  //     조합을 더 고르면 직전에 고른 조합의 네 가지 색에서 각각 2단계 낮은(연한) 색으로 시작하고(가장 연한 단계를 넘으면 가장 진한 쪽으로 돌아감), 그 뒤 따로 바꿀 수 있다.
  //     직접 바꾼 색만 이 브라우저에 기억(조합·칸별). 노랑은 색표에 넣지 않았다.
  const ROLES = [
    {k: 'bo', name: '매수 · 맞은 거래', ico: 'tri'}, {k: 'bn', name: '매수 · 틀린 거래', ico: 'tri'},
    {k: 'so', name: '매도 · 맞음', ico: 'dot'}, {k: 'sn', name: '매도 · 틀림', ico: 'ring'}];
  const LV = [28, 35, 42, 49, 56, 63, 70];          // 밝기 단계(%) 진함 → 연함
  const STEP = 2;                                   // 조합이 늘 때 낮추는 단계 수
  const HUES = [[212, 68, '파랑'], [248, 60, '남보라'], [285, 52, '보라'], [334, 62, '분홍'], [2, 66, '빨강'], [18, 80, '주황'], [150, 58, '초록'], [188, 70, '청록'], [22, 38, '갈색'], [215, 10, '회색']];
  const hsl2hex = (h, s, l) => { s /= 100; l /= 100; const a = s * Math.min(l, 1 - l), f = n => { const k = (n + h / 30) % 12; return Math.round(255 * (l - a * Math.max(-1, Math.min(k - 3, 9 - k, 1)))).toString(16).padStart(2, '0'); }; return '#' + f(0) + f(8) + f(4); };
  const hex2hsl = hex => { const v = [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16) / 255), mx = Math.max(...v), mn = Math.min(...v), l = (mx + mn) / 2, d = mx - mn;
    let h = 0, s = 0; if (d) { s = d / (1 - Math.abs(2 * l - 1)); h = mx === v[0] ? ((v[1] - v[2]) / d) % 6 : mx === v[1] ? (v[2] - v[0]) / d + 2 : (v[0] - v[1]) / d + 4; h = (h * 60 + 360) % 360; } return [h, s * 100, l * 100]; };
  const GRID = HUES.map(([h, s]) => LV.map(l => hsl2hex(h, s, l)));
  const GPOS = new Map(); GRID.forEach((row, r) => row.forEach((v, c) => GPOS.set(v, [r, c])));
  const DEF = {bo: GRID[0][2], bn: GRID[2][3], so: GRID[4][2], sn: GRID[5][3]};   // 첫 조합: 파랑 · 보라 · 빨강 · 주황
  function lower(hex, n = STEP){                   // 같은 색깔에서 n단계 낮은(연한) 색
    hex = String(hex).toLowerCase();
    const g = GPOS.get(hex); if (g) return GRID[g[0]][(g[1] + n) % LV.length];
    const [h, s, l] = hex2hsl(hex); let i = 0, best = 1e9; LV.forEach((v, j) => { const dd = Math.abs(v - l); if (dd < best) { best = dd; i = j; } });
    return hsl2hex(h, s, LV[(i + n) % LV.length]);
  }
  const isHex = v => /^#[0-9a-f]{6}$/i.test(v);
  const saved = new Map();   // key → {bo,bn,so,sn 중 직접 바꾼 것}
  const auto = new Map();    // key → 고를 때 정해진 시작 색(이번에 연 동안)
  try { Object.entries(JSON.parse(localStorage.getItem('lab_colors4') || '{}')).forEach(([k, o]) => { const c = {}; ROLES.forEach(({k: r}) => { if (o && isHex(o[r])) c[r] = o[r].toLowerCase(); }); if (Object.keys(c).length) saved.set(k, c); }); } catch (e) {}
  const saveColors = () => { try { localStorage.setItem('lab_colors4', JSON.stringify(Object.fromEntries(saved))); } catch (e) {} };
  const colorsOf = k => Object.assign({}, auto.get(k) || DEF, saved.get(k) || {});
  const colorOf = (k, role = 'bo') => colorsOf(k)[role];
  const SVGNS = 'http://www.w3.org/2000/svg';
  function shapeSvg(ico, col, sz = 12){             // ▲ 매수 · ● 맞은 매도 · ○ 틀린 매도
    const s = document.createElementNS(SVGNS, 'svg'); s.setAttribute('width', sz); s.setAttribute('height', sz); s.setAttribute('viewBox', '0 0 12 12'); s.setAttribute('aria-hidden', 'true');
    const p = document.createElementNS(SVGNS, ico === 'tri' ? 'path' : 'circle');
    if (ico === 'tri') { p.setAttribute('d', 'M6,1.5L11,10.5L1,10.5Z'); p.setAttribute('fill', col); }
    else { p.setAttribute('cx', 6); p.setAttribute('cy', 6); p.setAttribute('r', ico === 'dot' ? 4.6 : 3.9); p.setAttribute('fill', ico === 'dot' ? col : 'none'); if (ico === 'ring') { p.setAttribute('stroke', col); p.setAttribute('stroke-width', 2.2); } }
    s.appendChild(p); return s;
  }
  function mini(k){ const c = colorsOf(k), w = el('span', 'mini'); ROLES.forEach(r => w.appendChild(shapeSvg(r.ico, c[r.k], 11))); return w; }

  // ---------------------------------------------------------------- 자료 읽기
  async function load(){
    try {
      const get = f => fetch('data/' + f, {cache: 'no-cache'}).then(r => { if (!r.ok) throw new Error(f + ' ' + r.status); return r.json(); });
      [combos, trades, PX, meta] = await Promise.all([get('combos.json'), get('trades.json'), get('prices.json'), get('meta.json')]);
      try { CONDS = (await get('conds.json')).conds || []; } catch (e) { CONDS = []; }   // 신뢰 가능 조건(없어도 나머지는 그대로)
    } catch (e) {
      $('err').hidden = false; $('err').textContent = '자료를 읽지 못했습니다(' + e.message + '). 잠시 뒤 다시 열어 주세요.'; $('asof').textContent = '';
      return;
    }
    days = PX.kospi.d; days.forEach((d, i) => dIdx.set(d, i)); PX.fut.d.forEach((d, i) => fIdx.set(d, i));
    combos.forEach(c => { byKey.set(c.key, c); const pd = parseDesc(c); c.segs = pd.segs; c.toks = pd.toks; pd.toks.forEach(k => TOKN.set(k, (TOKN.get(k) || 0) + 1)); });
    const nT = combos.filter(c => c.has_trades).length;
    $('asof').textContent = '자료 끝 ' + (meta.data_end || '–') + ' · 내보낸 때 ' + (meta.at || '–');
    $('lede').textContent = '연구소 갈래 A·B·C·D 상위 조합 ' + combos.filter(c => 'ABCD'.includes(c.src)).length + '개(X1 거름 시험 대상), Signal A 관찰 목록 '
      + combos.filter(c => c.src === 'S').length + '개, Signal A 2차 네 거름 통과 ' + combos.filter(c => c.src === 'W').length + '개 — 그래프 표시 가능 ' + nT + '개 · 거래 내역 없음 ' + (combos.length - nT)
      + '개(거래일 기록이 남아 있지 않아 추정하지 않음). 표에서 줄을 누르면 그 조합의 매수일·매도일이 두 그래프에 표시됩니다.';
    try { const m = /s=([^&]+)/.exec(location.hash); if (m) decodeURIComponent(m[1]).split(',').forEach(k => { if (byKey.has(k) && sel.length < MAXSEL) pick(k, true); }); } catch (e) {}
    pickRange(range, true);
    buildTop(); buildHead(); fillTable(); fillDetail(); legend(); draw();
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
  let tip = null, rule = null, G = null, dtags = [];      // G = 마지막 그림의 좌표 정보(값 보기용)
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
    const ml = mob ? 46 : 58, mr = mob ? 8 : 14, H1 = mob ? 230 : 290, H2 = mob ? 150 : 190, T1 = 22, T2 = T1 + H1 + 46, B2 = T2 + H2, H = B2 + 26;   // 위 칸 아래에도 날짜 줄
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
      const C = colorsOf(key), g = plot.append('g');
      trades[key].forEach(t => {
        const bi = dIdx.get(t[1]), ei = dIdx.get(t[3]); if (bi == null || ei == null || ei < a || bi > b) return;
        const x0 = xf(bi) - step / 2, w = Math.max(2, xf(ei) - xf(bi) + step), col = t[7] === 1 ? C.bo : C.bn;   // 띠 = 그 거래의 매수 색
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
      const C = colorsOf(key), g = plot.append('g');
      trades[key].forEach(t => {
        const bi = dIdx.get(t[1]), ei = dIdx.get(t[3]); if (bi == null || ei == null || ei < a || bi > b) return;
        const ok = t[7] === 1, bc = ok ? C.bo : C.bn, scol = ok ? C.so : C.sn;
        const pts = [[y1, t[2], t[4]], [y2, fv(F.o, bi), fv(F.c, ei)]];
        pts.forEach(([y, bp, spx]) => {
          if (bp != null) { const x = xf(bi), yy = y(bp) + tri * 0.9; g.append('path').attr('d', `M${x},${yy - tri * 0.55}L${x + tri * 0.6},${yy + tri * 0.5}L${x - tri * 0.6},${yy + tri * 0.5}Z`).style('fill', bc).style('stroke', 'var(--color-panel)').style('stroke-width', 1.2); }
          if (spx != null) g.append('circle').attr('cx', xf(ei)).attr('cy', y(spx)).attr('r', r).style('fill', ok ? scol : 'var(--color-panel)').style('stroke', ok ? 'var(--color-panel)' : scol).style('stroke-width', ok ? 1.2 : 2);
        });
      });
    });
    // 날짜 글자 — 그래프마다 각각(2026-11-24 "그래프마다 날짜를 각각 표시")
    [T1 + H1 + 17, B2 + 18].forEach(yy => svg.append('g').selectAll('text').data(tks).join('text').attr('class', 'tick').attr('x', d => d[2]).attr('y', yy).attr('text-anchor', 'middle').text(d => d[1]));
    svg.append('line').attr('x1', L).attr('x2', R).attr('y1', T1 + H1).attr('y2', T1 + H1).style('stroke', 'var(--chart-axis)');
    svg.append('line').attr('x1', L).attr('x2', R).attr('y1', B2).attr('y2', B2).style('stroke', 'var(--chart-axis)');
    // 값 보기
    rule = svg.append('line').attr('y1', T1).attr('y2', B2).style('stroke', 'var(--chart-ref)').style('pointer-events', 'none').attr('opacity', 0);
    dtags = [T1 + H1, B2].map(yb => { const g = svg.append('g').attr('class', 'dtag').style('pointer-events', 'none').attr('opacity', 0);   // 값 보기 때 두 칸 아래에 그날 날짜
      g.append('rect').attr('y', yb + 3).attr('height', 19).attr('rx', 4); g.append('text').attr('y', yb + 16.5).attr('text-anchor', 'middle'); return g; });
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
    dtags.forEach(g => { const w = 84, x = Math.max(G.L + w / 2, Math.min(G.R - w / 2, xi)); g.select('rect').attr('x', x - w / 2).attr('width', w); g.select('text').attr('x', x).text(d); g.attr('opacity', 1); });
    tip.replaceChildren(el('div', 'h', d));
    const row = (col, name, val, hollow) => { const r = el('div', 'r'); if (col) { const s = el('span', 'sw'); if (hollow) { s.style.border = '2px solid ' + col; } else s.style.background = col; r.appendChild(s); } r.append(el('span', null, name), el('b', null, val)); tip.appendChild(r); };
    const chg = i > 0 ? K.c[i] / K.c[i - 1] - 1 : null;
    row(null, '코스피', f2(K.c[i]) + (chg != null ? ' (' + sp(chg, 2) + ')' : ''));
    row(null, '선물', j != null ? f2(F.c[j]) : '확인 불가');
    G.EV.forEach(({key, m}) => {
      const e = m.get(i); if (!e) return; const t = e.t, C = colorsOf(key), bc = t[7] ? C.bo : C.bn;
      const hd = holdDays(t), sv = sellInfo(byKey.get(key));
      if (e.k === 'buy') { row(bc, key + ' 매수', f2(t[2])); row(null, '　매도 기준', sv.short + ' → ' + t[3] + (hd ? '(' + hd + '거래일째)' : '')); }
      else if (e.k === 'sell' || e.k === 'both') row(t[7] ? C.so : C.sn, key + ' 매도', f2(t[4]) + ' · ' + sp(t[6]) + (t[7] ? ' 맞음' : ' 틀림') + (hd ? ' · ' + hd + '거래일째' : ''), !t[7]);
      else { const bi = dIdx.get(t[1]); row(bc, key + ' 보유 중', (bi != null ? (i - bi + 1) + (hd ? '/' + hd : '') + '거래일째 · ' : '') + '매도 ' + t[3]); }
    });
    tip.hidden = false;
    const bw = box.clientWidth, w = tip.offsetWidth; let left = xi + 14; if (left + w > bw) left = Math.max(0, xi - 14 - w);
    tip.style.left = left + 'px'; tip.style.top = Math.max(0, Math.min(y - 12, box.clientHeight - tip.offsetHeight)) + 'px';
    return true;
  }
  function hide(){ if (tip) tip.hidden = true; if (rule) rule.attr('opacity', 0); dtags.forEach(g => g.attr('opacity', 0)); }
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
  // ---------------------------------------------------------------- 그래프 위 빠른 고르기 · 고른 조건식 전문 (2026-11-24 사용자 지시)
  //  "적중률 순 상위 20(상승 신호 251개 중) — 각각 선택해 그래프에서 비교, 색상 선택, 그래프 위 칸에 작은 글씨로, 고른 조건식의 상세 조건도 모두 표시"
  //  순서는 대화에서 드린 표와 같게: 상승(dir>0) 조합을 적중 큰 순 → 거래 많은 순. 숫자는 표와 같은 코스피 지수 기준.
  // 2026-11-24 사용자 지시로 '적중률 상위 20'을 빼고 이 자리에 신뢰 가능 조건 18개(21개 − 하루 늦춰 진입 · 첫 신호만 5일·3일)를 같은 기능으로.
  //  자료 = data/conds.json(deriv/signal_a/x4/build_conds.py): 그 조건이 든 조합들의 거래를 같은 매수일 한 건으로 합친 것.
  let CONDS = [];
  function buildTop(){
    CONDS.forEach(c => { c.segs = [{t: c.name}]; c.toks = new Set([c.name]); c.desc = c.name; c.has_trades = true; c.grade = '신뢰 가능 조건';
      byKey.set(c.key, c); trades[c.key] = c.trades; });
  }
  function fillTop(){
    const w = $('top20'); if (!w) return; w.replaceChildren();
    const h = el('div', 't20-h'); h.append(el('b', null, '신뢰 가능 조건 ' + (CONDS.length || '')), el('span', null, CONDS.length
      ? ' 적중 순 · 그 조건이 든 조합들의 거래(같은 매수일 한 건) · 누르면 그래프에 표시(최대 ' + MAXSEL + '개) · 색 칸을 누르면 색 바꾸기'
      : ' 자료(conds.json)를 읽지 못했습니다'));
    w.appendChild(h);
    const g = el('div', 't20-g');
    CONDS.forEach((c, i) => {
      const k = c.key, on = sel.includes(k), b = el('button', 't20' + (on ? ' on' : '')); b.type = 'button';
      b.title = c.name + (c.dir < 0 ? ' (하락 신호)' : '') + '\n쓴 조합 ' + c.members.length + '개 · 거래 ' + c.n + ' · 적중 ' + pct1(c.hit, c.n)
        + '\n앞 2010~2023: ' + c.p1[0] + '건 ' + pct1(c.p1[1], c.p1[0]) + ' (아무 날 ' + pct1(c.base1) + ') · 뒤 2024~: ' + c.p2[0] + '건 ' + pct1(c.p2[1], c.p2[0]) + ' (아무 날 ' + pct1(c.base2) + ')';
      b.setAttribute('aria-pressed', String(on));
      b.append(el('span', 't20-r', String(i + 1)), el('span', 't20-k', c.short), el('span', 't20-v', pct1(c.hit, c.n)), el('span', 't20-n', c.n + '건'),
        el('span', 't20-s', '앞 ' + pct1(c.p1[1], c.p1[0]) + ' · 뒤 ' + pct1(c.p2[1], c.p2[0])));
      b.addEventListener('click', () => pick(k));
      const cell = el('span', 't20-c'); cell.appendChild(b); if (on) cell.appendChild(swBtn(k)); g.appendChild(cell);
    });
    w.appendChild(g);
  }
  function condHead(c, d, k){                    // 조건 카드 머리·숫자(아래 거래 내역 표는 조합 카드와 같은 것을 씀)
    const h = el('h3');
    h.append(swBtn(k), document.createTextNode('조건 · ' + c.short + (c.dir < 0 ? ' (하락 신호)' : '')), el('span', 'tag pass', '신뢰 가능'));
    const off = el('button'); off.type = 'button'; off.className = 'tag'; off.style.cursor = 'pointer'; off.style.background = 'transparent'; off.style.color = 'inherit'; off.textContent = '끄기 ✕'; off.addEventListener('click', () => pick(k)); h.appendChild(off);
    d.appendChild(h); d.appendChild(el('div', 'cond', c.name));
    const kv = el('div', 'kv'), put = (a, b) => { const r = el('div'); r.append(el('span', null, a), el('span', null, b)); kv.appendChild(r); };
    kv.appendChild(el('h4', null, '어떻게 만들었나'));
    put('쓴 조합', c.members.length + '개 — ' + c.members.join(', '));
    put('거래 합치기', '같은 매수일은 한 건, 맞음은 그날 거래들의 다수결. 그래프·표의 거래는 다수결과 같은 결과를 낸 첫 조합의 거래(매도는 그 조합 규칙대로)');
    put('방향', c.dir > 0 ? '오름(지수 상승이 맞음)' : '내림(지수 하락이 맞음)');
    kv.appendChild(el('h4', null, '검증(코스피 지수 기준)'));
    put('전체', c.n + '건 · 적중 ' + pct1(c.hit, c.n) + ' · 수익 합계 ' + sp(c.sum));
    put('앞 2010~2023', c.p1[0] + '건 · 적중 ' + pct1(c.p1[1], c.p1[0]) + ' · 아무 날 ' + pct1(c.base1) + ' · 하한 ' + pct1(c.lb1));
    put('뒤 2024~2026-11-20', c.p2[0] + '건 · 적중 ' + pct1(c.p2[1], c.p2[0]) + ' · 아무 날 ' + pct1(c.base2) + ' · 하한 ' + pct1(c.lb2));
    put('우연일 확률(전체)', (c.p != null ? c.p.toExponential(1) : '–') + ' (189개 시험 보정 문턱 0.00026)');
    put('판정 기준', '앞·뒤 각 20건 이상 · 윌슨 95% 하한이 같은 해 아무 날(같은 보유일) 맞음 비율보다 높음 · 보정 문턱 통과');
    put('최근 신호일', c.last || '–');
    d.appendChild(kv);
  }
  function fillSelCond(){
    const w = $('selcond'); if (!w) return; w.replaceChildren();
    if (!sel.length) { w.hidden = true; return; } w.hidden = false;
    w.appendChild(el('div', 't20-h', '고른 조건식 전문'));
    sel.forEach(k => {
      const c = byKey.get(k), r = el('div', 'sc'); r.style.setProperty('--c', colorOf(k, 'bo'));
      const top = el('div', 'sc-t'); top.append(swBtn(k), el('b', null, c.src === 'K' ? c.short : k), el('span', null, ' · ' + SRC_NAME[c.src] + (c.src === 'K' ? '(쓴 조합 ' + c.members.length + '개)' : c.src === 'S' ? ' ' + c.rank + '번' : c.src === 'W' ? ' 수익 ' + c.rank + '위' : ' ' + c.rank + '위') + (c.src === 'K' ? '' : ' · ' + c.grade)
        + (c.has_trades ? ' · ' + c.n + '거래 · 적중 ' + pct1(c.hit, c.n) + ' · 수익 ' + sp(c.sum) : '')));
      const x = el('button', 'x', '✕'); x.type = 'button'; x.title = '끄기'; x.setAttribute('aria-label', k + ' 끄기'); x.addEventListener('click', () => pick(k)); top.appendChild(x);
      r.appendChild(top);
      const ts = c.toks && c.toks.size ? [...c.toks] : [c.desc], cl = el('div', 'sc-l');   // 조건을 한 줄로 이어 공간을 적게(조각은 원문을 그대로 나눈 것)
      ts.forEach((t, i) => { if (i) cl.appendChild(el('span', 'sc-sep', ' + ')); cl.appendChild(el('span', 'sc-k', t)); });
      r.appendChild(cl);
      r.appendChild(el('div', 'sc-sell', '매수: 신호 다음 거래일 시가' + (/하루 늦/.test(c.desc) ? '(하루 늦춤 조건이면 그다음 날)' : '') + ' · 매도: ' + sellInfo(c).full));
      if (c.exact) { try { const d = el('details', 'sc-x'); d.appendChild(el('summary', null, '규칙 원문(정확히)')); d.appendChild(exactList(JSON.parse(c.exact))); r.appendChild(d); } catch (e) {} }
      w.appendChild(r);
    });
  }
  function legend(){
    fillTop(); fillSelCond();
    const lg = $('legend'); lg.replaceChildren();
    sel.forEach(k => {
      const c = byKey.get(k), chip = el('span', 'chip');
      chip.append(swBtn(k), el('span', null, (c.src === 'K' ? '조건' : k) + ' · ' + (c.short || c.name || c.grade) + (c.has_trades ? ' · ' + c.n + '거래' : ' · 거래 내역 없음') + ' · 매도 ' + sellInfo(c).short));
      const x = el('button', 'x', '✕'); x.type = 'button'; x.title = '그래프에서 끄기'; x.setAttribute('aria-label', k + ' 끄기'); x.addEventListener('click', () => pick(k));
      chip.appendChild(x); lg.appendChild(chip);
    });
    const ico = (svgTxt, txt) => { const s = el('span'); s.innerHTML = svgTxt; s.appendChild(document.createTextNode(txt)); lg.appendChild(s); };
    ico('<svg width="12" height="12" aria-hidden="true"><path d="M6,2L11,10L1,10Z" fill="currentColor"/></svg>', '매수(신호 다음 날 시가 · 맞은/틀린 거래 색 따로)');
    ico('<svg width="12" height="12" aria-hidden="true"><circle cx="6" cy="6" r="4.5" fill="currentColor"/></svg>', '맞은 매도');
    ico('<svg width="12" height="12" aria-hidden="true"><circle cx="6" cy="6" r="4" fill="none" stroke="currentColor" stroke-width="2"/></svg>', '틀린 매도(청산일 종가)');
    ico('<svg width="14" height="12" aria-hidden="true"><rect x="0" y="1" width="14" height="10" fill="currentColor" opacity=".25"/></svg>', '보유 기간');
    if (!sel.length) lg.appendChild(el('span', null, '· 아래 표에서 조합을 고르면 표시됩니다'));
  }

  // ---------------------------------------------------------------- 색 고르기
  function swBtn(k){
    const b = el('button', 'swb'); b.type = 'button'; b.title = '신호 색 바꾸기(매수·매도 · 맞음·틀림)'; b.setAttribute('aria-label', k + ' 신호 색 바꾸기'); b.setAttribute('aria-haspopup', 'true');
    b.append(mini(k), el('span', null, '색'));
    b.addEventListener('click', e => { e.stopPropagation(); e.preventDefault(); openPal(k, b); }); return b;
  }
  let pal = null, palRole = 'bo';
  function closePal(){ if (pal) { pal.remove(); pal = null; } }
  function rerender(){ fillTable(); fillDetail(); legend(); draw(); if (pal) palUpdate(); }
  function setColor(k, role, v){
    const o = Object.assign({}, saved.get(k) || {});
    if (v) o[role] = v.toLowerCase(); else delete o[role];
    if (Object.keys(o).length) saved.set(k, o); else saved.delete(k);
    saveColors(); rerender();
  }
  function palUpdate(){                            // 열린 색표의 표시만 다시(직접 고르기 칸은 그대로 두어 끌기가 끊기지 않게)
    const k = pal.dataset.k, C = colorsOf(k), cur = C[palRole], own = (saved.get(k) || {})[palRole];
    pal.querySelectorAll('.pal-t button').forEach(b => { const r = b.dataset.r; b.setAttribute('aria-pressed', String(r === palRole)); b.querySelector('svg').replaceWith(shapeSvg(ROLES.find(x => x.k === r).ico, C[r], 13)); });
    pal.querySelectorAll('.pal-g button').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.v === cur)));
    const inp = pal.querySelector('input[type=color]'); if (inp && document.activeElement !== inp) inp.value = cur;
    pal.querySelector('.pal-now').textContent = ROLES.find(x => x.k === palRole).name + ' ' + cur + (own ? ' · 직접 고름' : ' · 시작 색');
  }
  function openPal(k, anchor){
    const again = pal && pal.dataset.k === k; closePal(); if (again) return;
    palRole = 'bo';
    pal = el('div', 'pal'); pal.dataset.k = k; pal.setAttribute('role', 'dialog'); pal.setAttribute('aria-label', k + ' 신호 색');
    pal.appendChild(el('div', 'pal-h', k + ' 신호 색 — 바꿀 칸을 고른 뒤 색을 누르세요'));
    const tabs = el('div', 'pal-t');
    ROLES.forEach(r => { const b = el('button'); b.type = 'button'; b.dataset.r = r.k; b.append(shapeSvg(r.ico, '#000', 13), el('span', null, r.name));
      b.addEventListener('click', () => { palRole = r.k; palUpdate(); }); tabs.appendChild(b); });
    pal.appendChild(tabs);
    const scale = el('div', 'pal-s'); scale.append(el('span', null, '진하게'), el('span', null, '← 밝기 7단계 →'), el('span', null, '연하게')); pal.appendChild(scale);
    const g = el('div', 'pal-g');
    GRID.forEach((row, ri) => row.forEach((v, ci) => { const b = el('button'); b.type = 'button'; b.dataset.v = v; b.style.background = v;
      b.title = HUES[ri][2] + ' ' + (ci + 1) + '단계 ' + v; b.setAttribute('aria-label', HUES[ri][2] + ' ' + (ci + 1) + '단계');
      b.addEventListener('click', () => setColor(k, palRole, v)); g.appendChild(b); }));
    pal.appendChild(g);
    pal.appendChild(el('div', 'pal-now'));
    const row = el('div', 'pal-r'), lab = el('label'), inp = el('input'); inp.type = 'color';
    inp.addEventListener('input', () => setColor(k, palRole, inp.value));
    lab.append(inp, document.createTextNode(' 직접 고르기')); row.appendChild(lab);
    const btns = el('div', 'pal-bs');
    const rs = el('button', 'pal-reset', '이 칸 처음 색'); rs.type = 'button'; rs.title = '조합을 고를 때 정해진 시작 색으로'; rs.addEventListener('click', () => setColor(k, palRole, null));
    const ra = el('button', 'pal-reset', '네 칸 모두'); ra.type = 'button'; ra.title = '네 칸 모두 시작 색으로'; ra.addEventListener('click', () => { saved.delete(k); saveColors(); rerender(); });
    btns.append(rs, ra); row.appendChild(btns); pal.appendChild(row);
    pal.appendChild(el('div', 'pal-n', '조합을 더 고르면 직전에 고른 조합의 색에서 ' + STEP + '단계 연한 색으로 시작합니다(가장 연한 단계를 넘으면 진한 쪽으로 돌아감). 직접 고른 색은 이 브라우저에 기억합니다.'));
    document.body.appendChild(pal); palUpdate();
    const r = anchor.getBoundingClientRect(), w = pal.offsetWidth;
    pal.style.left = Math.max(8, Math.min(window.scrollX + r.left, window.scrollX + document.documentElement.clientWidth - w - 8)) + 'px';
    pal.style.top = (window.scrollY + r.bottom + 6) + 'px';
    const first = pal.querySelector('.pal-t button'); if (first) first.focus({preventScroll: true});
  }
  document.addEventListener('click', e => { if (pal && e.target.isConnected && !pal.contains(e.target)) closePal(); });
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closePal(); });

  // ---------------------------------------------------------------- 고르기
  let toastT = 0;
  function toast(s){ $('toast').textContent = s; clearTimeout(toastT); toastT = setTimeout(() => { $('toast').textContent = ''; }, 3500); }
  function pick(k, quiet){
    const at = sel.indexOf(k);
    closePal();
    if (at >= 0) { sel.splice(at, 1); auto.delete(k); }
    else {
      if (sel.length >= MAXSEL) { toast('최대 ' + MAXSEL + '개까지 고를 수 있습니다 — 먼저 고른 것을 끄세요.'); return; }
      const prev = sel[sel.length - 1], pc = prev ? colorsOf(prev) : null, start = {};
      ROLES.forEach(({k: r}) => { start[r] = pc ? lower(pc[r]) : DEF[r]; });   // 직전 조합 색에서 2단계 낮게(첫 조합은 기본색)
      auto.set(k, start); sel.push(k);
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
    {k: 'grade', label: '등급', sort: c => ({'관찰 목록': 0, '2차 네 거름': 0.5, '통과': 1, '관찰': 2}[c.grade] ?? 3), title: '연구소 등급(코스피200 선물 기준)'},
    {k: 'desc', label: '조건 설명', sort: c => c.desc, cls: 'desc'},
    {k: 'sell', label: '매도 기준', sort: c => sellInfo(c).sortv, d0: 1, title: '청산 규칙(원문). 정렬은 보유 거래일 수(정해진 보유일, 없으면 실제 보유일 가운뎃값)'},
    {k: 'n', label: '독립 거래', num: true, sort: c => c.n},
    {k: 'hit', label: '적중', num: true, sort: c => (c.n >= 10 ? c.hit : null)},
    {k: 'edge', label: '아무 날과 차이', num: true, sort: c => (c.n >= 10 ? c.edge : null), title: '적중 − 같은 해 아무 날 적중(해 구성 맞춤)'},
    {k: 'sum', label: '수익 합계', num: true, sort: c => c.sum, title: '거래별 수익률 단순 합(내림 조합은 지수 하락이 +)'},
    {k: 'avg', label: '1회 평균', num: true, sort: c => c.avg},
    {k: 'last', label: '최근 신호일', num: true, sort: c => c.last},
    {k: 'f', label: '네 거름', sort: c => (c.has_trades ? c.f.filter(Boolean).length + (c.all4 ? 0.5 : 0) : null), title: '①②③④ 통과 여부'},
  ];
  // 표에 없는 내용도 정렬 기준으로(상세에 나오는 숫자들)
  const okN = (n, v) => (n != null && n >= 10 ? v : null);
  const EXTRA = [
    {k: 'key', label: '조합 이름', sort: c => c.key, d0: 1},
    {k: 'family', label: '가족(계열)', sort: c => c.family || null, d0: 1},
    {k: 'dir', label: '방향(오름 먼저)', sort: c => c.dir, d0: -1},
    {k: 'n_sig', label: '신호 수', num: true, sort: c => c.n_sig},
    {k: 'hold', label: '실제 보유일 가운뎃값', num: true, d0: 1, sort: c => { const a = sellInfo(c).act; return a ? a.med : null; }},
    {k: 'base', label: '같은 해 아무 날 적중', num: true, sort: c => okN(c.n, c.base)},
    {k: 'p1', label: '앞 구간(2010~2023) 적중', num: true, sort: c => (c.p1 ? okN(c.p1[0], c.p1[1]) : null)},
    {k: 'p2', label: '뒤 구간(2024~) 적중', num: true, sort: c => (c.p2 ? okN(c.p2[0], c.p2[1]) : null)},
    {k: 'falsify', label: '반증 시험 버틴 수', num: true, sort: c => (c.falsify ? parseInt(c.falsify, 10) : null)},
    {k: 'p', label: '가짜 신호 p(작은 것 먼저)', num: true, d0: 1, sort: c => c.p},
    {k: 'lab_n', label: '연구소 전체 거래 수', num: true, sort: c => (c.lab ? c.lab.all_n : null)},
    {k: 'lab_hit', label: '연구소 전체 적중', num: true, sort: c => (c.lab ? okN(c.lab.all_n, c.lab.all_hit) : null)},
    {k: 'lab_lb', label: '연구소 윌슨 하한', num: true, sort: c => (c.lab ? c.lab.all_lb : null)},
    {k: 'lab_dev', label: '연구소 앞 구간 적중', num: true, sort: c => (c.lab ? okN(c.lab.dev_n, c.lab.dev_hit) : null)},
    {k: 'lab_p2', label: '연구소 뒤 구간 적중', num: true, sort: c => (c.lab ? okN(c.lab.p2_n, c.lab.p2_hit) : null)},
  ];
  const fieldOf = k => {
    if (k.startsWith('c:')) { const t = k.slice(2); return {k, cond: t, label: '조건 「' + t + '」', num: true, d0: -1, sort: c => (c.toks.has(t) ? 1 : 0)}; }
    return COLS.find(c => c.k === k && c.sort) || EXTRA.find(c => c.k === k); };
  const dir0 = f => f.d0 != null ? f.d0 : (f.num || f.k === 'f' ? -1 : 1);
  const CIRC = '①②③④⑤⑥⑦⑧⑨⑩';
  const ordTxt = i => CIRC[i] || '(' + (i + 1) + ')';
  function cycleSort(k){                       // 열 제목: 처음 누름 = 기준 더하기 · 두 번째 = 반대로 · 세 번째 = 빼기
    const f = fieldOf(k); if (!f) return; const i = sorts.findIndex(x => x.k === k), d0 = dir0(f);
    if (i < 0) sorts.push({k, dir: d0}); else if (sorts[i].dir === d0) sorts[i].dir = -d0; else sorts.splice(i, 1);
    fillTable();
  }
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
        const go = () => cycleSort(c.k);
        th.addEventListener('click', go); th.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(); } }); }
      tr.appendChild(th);
    });
    document.querySelector('#combo-tbl thead').replaceChildren(tr);
  }
  function rows(){
    const q = filt.q.trim().toLowerCase();
    let L = combos.filter(c => (!filt.src.size || filt.src.has(c.src)) && (!filt.grade.size || filt.grade.has(c.grade)) && (!filt.has || c.has_trades) && (!filt.all4 || c.all4)
      && (!q || (c.key + ' ' + c.id + ' ' + c.desc + ' ' + (c.name || '') + ' ' + (c.family || '')).toLowerCase().includes(q)));
    const dflt = (a, b) => (SRC_ORD[a.src] - SRC_ORD[b.src]) || (a.rank - b.rank);
    const act = sorts.map(x => ({f: fieldOf(x.k), dir: x.dir})).filter(x => x.f);
    if (!act.length) return L.sort(dflt);
    const v = (f, c) => { const x = f.sort(c); return (x === undefined || x === null || (typeof x === 'number' && !isFinite(x))) ? null : x; };
    return L.sort((a, b) => {                  // 앞 기준이 같으면 다음 기준으로, 값이 없는 것('–')은 늘 아래
      for (const {f, dir} of act) { const va = v(f, a), vb = v(f, b); if (va === null && vb === null) continue; if (va === null) return 1; if (vb === null) return -1;
        const r = typeof va === 'string' ? va.localeCompare(vb, 'ko') : va - vb; if (r) return r * dir; }
      return dflt(a, b); });
  }
  function fillTable(){
    document.querySelectorAll('#combo-tbl th.sort').forEach(th => { const i = sorts.findIndex(x => x.k === th.dataset.k);
      th.querySelector('.ar').textContent = i < 0 ? '' : (sorts.length > 1 ? ordTxt(i) : '') + (sorts[i].dir > 0 ? '▲' : '▼');
      th.setAttribute('aria-sort', i === 0 ? (sorts[0].dir > 0 ? 'ascending' : 'descending') : 'none'); });
    sortBar();
    const tb = document.querySelector('#combo-tbl tbody'), L = rows(), frag = document.createDocumentFragment();
    // 맨 앞 정렬 기준이 조건이면 같은 조건끼리 묶음 머리줄
    const lead = []; for (const x of sorts) { if (!x.k.startsWith('c:')) break; lead.push(x.k.slice(2)); }
    const sig = c => lead.map(t => (c.toks.has(t) ? 1 : 0)).join('');
    const gcount = new Map(); if (lead.length) L.forEach(c => gcount.set(sig(c), (gcount.get(sig(c)) || 0) + 1));
    let prevSig = null; const ncol = cols().length;
    L.forEach(c => {
      if (lead.length) { const g = sig(c); if (g !== prevSig) { prevSig = g; const gr = el('tr', 'grp'), gd = el('td'); gd.colSpan = ncol;
        const has = lead.filter((t, i) => g[i] === '1'), not = lead.filter((t, i) => g[i] === '0');
        gd.textContent = (has.length ? '있음 ' + has.map(t => '「' + t + '」').join(' ') : '') + (has.length && not.length ? ' · ' : '') + (not.length ? '없음 ' + not.map(t => '「' + t + '」').join(' ') : '') + ' — ' + gcount.get(g) + '개';
        gr.appendChild(gd); frag.appendChild(gr); } }
      const tr = el('tr', (sel.includes(c.key) ? 'on' : '') + (c.has_trades ? '' : ' none')); tr.tabIndex = 0;
      const td = (t, cls) => { const x = el('td', cls, t); tr.appendChild(x); return x; };
      const NUMK = ['hit', 'edge', 'sum', 'avg', 'last'];
      cols().forEach(col => {
        const k = col.k;
        if (k === 'pick') {
          const cell = td(null, 'pick');
          if (sel.includes(c.key)) {                // 고른 줄의 색 칸 = 색 바꾸기(줄의 다른 곳을 누르면 끄기)
            const pk = el('button', 'pkb'); pk.type = 'button'; pk.title = '신호 색 바꾸기'; pk.setAttribute('aria-label', c.key + ' 신호 색 바꾸기');
            pk.appendChild(mini(c.key));
            pk.addEventListener('click', e => { e.stopPropagation(); openPal(c.key, pk); }); cell.appendChild(pk);
          } else cell.appendChild(el('span', 'pk'));
        }
        else if (k === 'src') td(SRC_SHORT[c.src], 'src');
        else if (k === 'rank') td(c.src === 'S' || c.src === 'W' ? '#' + c.rank : String(c.rank), 'num');
        else if (k === 'round') td(c.round != null ? c.round + '회' : '–', 'num');
        else if (k === 'grade') td(null).appendChild(el('span', 'tag' + (c.grade === '통과' || c.grade === '관찰 목록' || c.grade === '2차 네 거름' ? ' pass' : ''), c.grade));
        else if (k === 'sell') { const sv = sellInfo(c), x = td(sv.short, 'sellc'); x.title = sv.full + '\n실제 보유: ' + actTxt(sv.act); }
        else if (k === 'desc') { const dd = td(null, 'desc'); dd.title = c.desc; dd.appendChild(condSegs(c)); }
        else if (!c.has_trades) { if (k === 'n') { const x = td('거래 내역 없음', 'muted'); x.colSpan = 6; } else if (k === 'f') td('–', 'f4'); }
        else if (k === 'n') td(String(c.n), 'num');
        else if (NUMK.includes(k)) td({hit: pct1(c.hit, c.n), edge: spp(c.edge, c.n), sum: sp(c.sum), avg: sp(c.avg, 2), last: c.last || '–'}[k], 'num');
        else if (k === 'f') { const f = td(c.f.map(x => x ? '●' : '○').join(''), 'f4'); f.title = c.f.map((x, i) => F_NAME[i] + ' ' + (x ? '통과' : '못 넘음')).join('\n'); }
      });
      tr.addEventListener('click', () => pick(c.key)); tr.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pick(c.key); } });
      frag.appendChild(tr);
    });
    tb.replaceChildren(frag);
    const on = new Set(sorts.filter(x => x.k.startsWith('c:')).map(x => x.k.slice(2)));
    document.querySelectorAll('.ct').forEach(x => x.classList.toggle('on', on.has(x.dataset.k)));
    $('count').textContent = combos.length + '개 중 ' + L.length + '개 표시 · 고른 것 ' + sel.length + '/' + MAXSEL;
  }
  function sortBar(){                          // 정렬 기준 막대: 기준 차례·방향 바꾸기·빼기, 모든 내용에서 더하기
    const bar = $('sortbar'); if (!bar) return; bar.replaceChildren(el('span', 'sb-l', '정렬'));
    if (!sorts.length) bar.appendChild(el('span', 'muted', '처음 순서(갈래·순위)'));
    sorts.forEach((x, i) => { const f = fieldOf(x.k); if (!f) return; const chip = el('span', 'sb-c');
      if (f.cond) chip.classList.add('cond');
      const b = el('button', null, (sorts.length > 1 ? ordTxt(i) + ' ' : '') + f.label + ' ' + (f.cond ? (x.dir < 0 ? '있는 것 먼저' : '없는 것 먼저') + ' · ' + (TOKN.get(f.cond) || 0) + '개' : (x.dir > 0 ? '▲' : '▼')));
      b.type = 'button'; b.title = '눌러서 반대로';
      b.addEventListener('click', () => { x.dir = -x.dir; fillTable(); });
      const up = el('button', 'sb-x', '↑'); up.type = 'button'; up.title = '앞 기준으로'; up.setAttribute('aria-label', f.label + ' 앞으로'); up.disabled = i === 0;
      up.addEventListener('click', () => { sorts.splice(i - 1, 0, sorts.splice(i, 1)[0]); fillTable(); });
      const rm = el('button', 'sb-x', '✕'); rm.type = 'button'; rm.title = '이 기준 빼기'; rm.setAttribute('aria-label', f.label + ' 기준 빼기');
      rm.addEventListener('click', () => { sorts.splice(i, 1); fillTable(); });
      chip.append(b); if (sorts.length > 1) chip.append(up); chip.append(rm); bar.appendChild(chip); });
    const s = el('select'); s.setAttribute('aria-label', '정렬 기준 더하기');
    s.appendChild(new Option('+ 기준 더하기', ''));
    [['표의 열', COLS.filter(c => c.sort)], ['더 많은 내용', EXTRA]].forEach(([g, L]) => { const og = document.createElement('optgroup'); og.label = g;
      L.filter(f => !sorts.some(x => x.k === f.k)).forEach(f => og.appendChild(new Option(f.label, f.k))); if (og.children.length) s.appendChild(og); });
    s.addEventListener('change', () => { const f = fieldOf(s.value); if (f) { sorts.push({k: f.k, dir: dir0(f)}); fillTable(); } });
    bar.appendChild(s);
    const cs = el('select', 'sb-cond'); cs.setAttribute('aria-label', '조건으로 정렬');
    cs.appendChild(new Option('+ 조건으로 정렬(같은 조건끼리)', ''));
    [...TOKN.entries()].filter(([k]) => !sorts.some(x => x.k === 'c:' + k)).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], 'ko'))
      .forEach(([k, n]) => cs.appendChild(new Option(k + ' (' + n + ')', k)));
    cs.addEventListener('change', () => { if (cs.value) toggleCond(cs.value); });
    bar.appendChild(cs);
    if (sorts.length) { const c = el('button', 'sb-clr', '처음 순서로'); c.type = 'button'; c.addEventListener('click', () => { sorts.length = 0; fillTable(); }); bar.appendChild(c); }
  }
  function segFilter(id, k){                   // 여러 개 고르기: 누르면 켜고 끄기, 「전체」는 모두 해제
    const bs = [...document.querySelectorAll('#' + id + ' button')];
    const sync = () => bs.forEach(x => x.setAttribute('aria-pressed', String(x.dataset.v === '' ? filt[k].size === 0 : filt[k].has(x.dataset.v))));
    bs.forEach(b => b.addEventListener('click', () => { const v = b.dataset.v; if (v === '') filt[k].clear(); else if (filt[k].has(v)) filt[k].delete(v); else filt[k].add(v); sync(); fillTable(); })); }
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
      const c = byKey.get(k), d = el('div', 'dcard'); d.style.setProperty('--c', colorOf(k, 'bo'));
      if (c.src === 'K') condHead(c, d, k); else {
      const h = el('h3');
      h.append(swBtn(k), document.createTextNode(k + ' · ' + SRC_NAME[c.src] + (c.src === 'S' ? ' ' + c.rank + '번 ' + c.name : c.src === 'W' ? ' 수익 ' + c.rank + '위 · ' + c.name : ' ' + c.rank + '위')), el('span', 'tag' + (c.grade === '통과' || c.grade === '관찰 목록' || c.grade === '2차 네 거름' ? ' pass' : ''), c.grade));
      const off = el('button'); off.type = 'button'; off.className = 'tag'; off.style.cursor = 'pointer'; off.style.background = 'transparent'; off.style.color = 'inherit'; off.textContent = '끄기 ✕'; off.addEventListener('click', () => pick(k)); h.appendChild(off);
      d.appendChild(h); d.appendChild(el('div', 'code', c.id));
      const cond = el('div', 'cond'); cond.appendChild(condSegs(c));
      if (c.exact) { try { cond.appendChild(exactList(JSON.parse(c.exact))); } catch (e) {} }
      d.appendChild(cond);
      const kv = el('div', 'kv'), put = (a, b) => { const r = el('div'); r.append(el('span', null, a), el('span', null, b)); kv.appendChild(r); };
      kv.appendChild(el('h4', null, '출처'));
      put('갈래', SRC_NAME[c.src]); if (c.round != null) put('연구소 회차', c.round + '회'); if (c.family) put('가족', c.family);
      put('방향', c.dir > 0 ? '오름(지수 상승이 맞음)' : '내림(지수 하락이 맞음)'); put('거래일 출처', c.trade_src + (c.trade_note ? ' — ' + c.trade_note : ''));
      const sv = sellInfo(c);
      kv.appendChild(el('h4', null, '매도 기준'));
      put('규칙', sv.full); put('실제 보유(거래일)', actTxt(sv.act));
      if (c.lab) {
        kv.appendChild(el('h4', null, '연구소 숫자(코스피200 선물 기준, 순위·등급을 매긴 숫자)'));
        put('전체', (c.lab.all_n ?? '–') + '건 · ' + pct1(c.lab.all_hit, c.lab.all_n) + ' · 윌슨 하한 ' + pct1(c.lab.all_lb));
        put('앞 구간 2010~2023', (c.lab.dev_n ?? '–') + '건 · ' + pct1(c.lab.dev_hit, c.lab.dev_n)); put('뒤 구간 2024~', (c.lab.p2_n ?? '–') + '건 · ' + pct1(c.lab.p2_hit, c.lab.p2_n));
      }
      if (c.has_trades) {
        kv.appendChild(el('h4', null, '코스피 지수 기준(' + ((c.src === 'S' && c.rank > 1) || c.src === 'W' ? '2016~2026 해마다 그 전 자료로 고른 절차' : '2010~2026-11-20 독립 거래') + ')'));
        put('독립 거래 · 적중', c.n + '건 · ' + pct1(c.hit, c.n)); put('같은 해 아무 날 · 차이', pct1(c.base, c.n) + ' · ' + spp(c.edge, c.n));
        put('수익 합계 · 1회 평균', sp(c.sum) + ' · ' + sp(c.avg, 2));
        put('앞 · 뒤 구간', (c.p1[0] ?? '–') + '건 ' + pct1(c.p1[1], c.p1[0]) + ' · ' + (c.p2[0] ?? '–') + '건 ' + pct1(c.p2[1], c.p2[0]));
        put('신호 수 · 보유일 가운뎃값', c.n_sig + '번 · ' + (c.hold ?? '–') + '일'); put('최근 신호일', c.last || '–');
        kv.appendChild(el('h4', null, '네 거름' + (c.src === 'S' ? '(Signal A S3 판정)' : c.src === 'W' ? '(Signal A 2차 판정)' : '(X1 판정)')));
        c.f.forEach((x, i) => put(F_NAME[i], (x ? '● 통과' : '○ 못 넘음') + (i === 1 && c.big_na ? '(큰 변동 해 판정 불가)' : '') + (i === 2 && c.falsify ? ' · 버틴 수 ' + c.falsify : '') + (i === 3 && c.p != null ? ' · p ' + c.p.toFixed(4) + (c.p_adj != null ? '(가짓수 보정 뒤 ' + c.p_adj.toFixed(3) + ')' : '') : '')));
        if (c.overlap) put('관찰 목록과 겹침', c.overlap);
      }
      d.appendChild(kv);
      if (c.caution && c.caution.length) { const ul = el('ul', 'note'); c.caution.forEach(s => ul.appendChild(el('li', null, s))); d.appendChild(el('div', 'note', '조심할 점')); d.appendChild(ul); }
      }
      const T = trades[k];
      if (!c.has_trades || !T || !T.length) d.appendChild(el('p', 'empty', '거래 내역 없음 — 이 조합은 거래일 기록이 남아 있지 않아 그래프에 표시하지 않습니다(추정하지 않음).' + (c.trade_note ? ' ' + c.trade_note : '')));
      else {
        d.appendChild(el('div', 'note', '거래 내역 ' + T.length + (c.src === 'K' ? '건(같은 매수일 한 건으로 합친 거래)' : '건(독립 거래)') + ' — 줄을 누르면 그래프가 그 거래로 옮겨 갑니다.' + (c.dir < 0 ? ' 내림 조합이라 수익률은 지수 하락이 +입니다.' : '')));
        const w = el('div', 'trw'), tb = el('table'), th = el('thead'), hr = el('tr');
        const heads = ['#', '신호일', '매수일', '매수가', '매도일', '매도가', '보유일'].concat(c.dir < 0 ? ['코스피 등락'] : []).concat(['수익률', '맞음']);
        heads.forEach((s, i) => hr.appendChild(el('th', i === 0 || i === 3 || i === 5 || i >= 6 ? 'num' : '', s))); th.appendChild(hr); tb.appendChild(th);
        const body = el('tbody');
        T.slice().reverse().forEach((t, j) => {
          const r = el('tr'), cell = (s, cls) => r.appendChild(el('td', cls, s));
          cell(String(T.length - j), 'num'); cell(t[0]); cell(t[1]); cell(f2(t[2]), 'num'); cell(t[3]); cell(f2(t[4]), 'num'); const hd = holdDays(t); cell(hd != null ? hd + '일' : '확인 불가', 'num');
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
