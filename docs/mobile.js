// 2026-11-16 추가: 보기 개선(휴대폰 중심). 사용자 요청 "전부 개선해" — 첫 화면 오늘 핵심, 구역 이동 메뉴, 결론 카드 접기, 그래프 범례 접기·선 끝 이름표,
// 표 옆으로 밀기 표시·첫 열 고정, 글씨·단추 크기, 자료 갱신 시각, 용어 풀이, 색 말고 무늬로도 구분, 지난 구역 표시, 휴대폰 상세 상자(아래 고정).
// index.html 의 다른 코드와 변수를 공유하지 않는다(index.html 이 256KB 한도에 가까워 따로 둔다). 쓰는 것은 dash 뿐. 자료 글자는 textContent 로만 넣는다.
(function(){
  if (window.__rvMobile) return; window.__rvMobile = true;
  const root = document.getElementById('dash-root'); if (!root) return;
  const RV = () => root.querySelector('.rv');
  const BAD = ['error', 'connect', 'declined', 'missing'];
  const num = v => (v === '' || v == null || isNaN(+v)) ? null : +v;
  const md = s => { const m = String(s || '').match(/^(\d{4})-(\d{2})-(\d{2})/); return m ? (+m[2]) + '/' + (+m[3]) : String(s || ''); };
  const fmt = (v, d) => v == null ? '—' : v.toLocaleString('ko-KR', {minimumFractionDigits: d, maximumFractionDigits: d});
  const sg = (v, d) => v == null ? '—' : (v > 0 ? '+' : v < 0 ? '−' : '±') + fmt(Math.abs(v), d);
  const el = (tag, cls, txt) => { const e = document.createElement(tag); if (cls) e.className = cls; if (txt != null) e.textContent = txt; return e; };
  const rows = id => { const d = dash.data(id); return d && d.status === 'ok' && Array.isArray(d.data) ? d.data : []; };
  const last = (id, pred) => { const r = rows(id).filter(pred || (() => true)); return r.length ? r[r.length - 1] : null; };
  const phone = () => window.matchMedia('(max-width: 700px)').matches;

  // ---------- 1. 스타일(전부 이 파일 안에서)
  const css = `
@supports (overflow:clip){html,body{overflow-x:clip}}
.rv .rv-today{padding:var(--cds-pad-md)}
.rv .rv-today-h{display:flex;flex-wrap:wrap;align-items:baseline;justify-content:space-between;gap:4px 12px;margin:0 0 var(--cds-gap-sm)}
.rv .rv-today-h h2{margin:0}
.rv .rv-fresh{font-size:var(--cds-font-size-caption);color:var(--color-fg-muted)}
.rv .rv-fresh b{font-weight:600;color:var(--color-fg)}
.rv .rv-fresh.rv-late b{color:#b45309}
.rv .rv-tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,10.5rem),1fr));gap:var(--cds-gap-sm)}
.rv .rv-tile{border:1px solid var(--color-border-line);border-radius:10px;padding:8px 10px;display:flex;flex-direction:column;gap:1px;min-width:0}
.rv .rv-tile-l{font-size:var(--cds-font-size-caption);color:var(--color-fg-muted)}
.rv .rv-tile-v{font-family:var(--font-anthropic-serif);font-size:22px;line-height:1.25}
.rv .rv-tile-v small{font-family:var(--font-anthropic-sans);font-size:13px;margin-left:4px;color:var(--color-fg-muted)}
.rv .rv-tile-n{font-size:var(--cds-font-size-caption);color:var(--color-fg-muted);overflow-wrap:anywhere}
.rv .rv-tile.rv-alert{border-color:var(--color-bad)}
.rv .rv-tile.rv-alert .rv-tile-v{color:var(--color-bad)}
.rv .rv-tile-s{font-size:14px;line-height:1.45}
.rv .rv-nav{position:sticky;top:0;z-index:15;display:flex;gap:6px;overflow-x:auto;-webkit-overflow-scrolling:touch;scrollbar-width:none;padding:6px 2px;margin:0 -2px;background:var(--color-bg)}
.rv .rv-nav::-webkit-scrollbar{display:none}
.rv .rv-nav a{flex:none;font-size:13px;text-decoration:none;color:var(--color-fg-muted);border:1px solid var(--color-border-line);background:var(--color-panel);border-radius:999px;padding:0 12px;line-height:34px;min-height:34px}
.rv .rv-nav a[aria-current=true]{color:var(--color-fg);border-color:var(--color-fg);font-weight:600}
.rv > section,.rv > details,.rv > header{scroll-margin-top:52px}
.rv-top{position:fixed;right:14px;bottom:calc(16px + env(safe-area-inset-bottom));z-index:20;width:46px;height:46px;border-radius:50%;border:1px solid var(--color-border-line);background:var(--color-panel);color:var(--color-fg);font-size:18px;box-shadow:0 2px 10px rgba(0,0,0,.15);cursor:pointer;display:none}
.rv-top.rv-show{display:block}
.rv .rv-clampable{display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:4;overflow:hidden}
.rv .rv-card.rv-cl .rv-verdict{display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:5;overflow:hidden}
.rv .rv-card.rv-cl ul > li:nth-child(n+4):not(.rv-keep){display:none}
.rv .rv-more-btn{font:inherit;font-size:13px;color:var(--color-fg-muted);background:transparent;border:1px solid var(--color-border-line);border-radius:999px;padding:0 12px;min-height:34px;margin:6px 0 2px;cursor:pointer}
.rv .rv-badge{display:inline-block;font-size:12px;font-weight:500;color:#92400e;background:#fef3c7;border-radius:999px;padding:1px 8px;margin-left:6px;vertical-align:middle}
.rv .rv-xs-hint{font-size:12px;color:var(--color-fg-muted);margin:2px 0 4px}
.rv .rv-xs{position:relative;background:linear-gradient(to right,var(--color-panel) 30%,rgba(255,255,255,0)) left/24px 100% no-repeat local,linear-gradient(to left,var(--color-panel) 30%,rgba(255,255,255,0)) right/24px 100% no-repeat local,linear-gradient(to right,rgba(0,0,0,.12),rgba(0,0,0,0)) left/10px 100% no-repeat scroll,linear-gradient(to left,rgba(0,0,0,.12),rgba(0,0,0,0)) right/10px 100% no-repeat scroll}
.rv .rv-xs td:first-child,.rv .rv-xs th:first-child{position:sticky;left:0;z-index:1;background:var(--color-panel);box-shadow:1px 0 0 var(--color-border-line)}
.rv .rv-xs th:first-child{z-index:2}
.rv .rv-term{border:0;background:transparent;padding:0;font:inherit;color:inherit;text-decoration:underline dotted;text-underline-offset:3px;cursor:help}
.rv-gloss{position:absolute;z-index:40;max-width:min(320px,calc(100vw - 24px));background:var(--cds-surface-popover,#fff);color:var(--color-fg);border:1px solid var(--color-border-line);border-radius:10px;box-shadow:0 4px 16px rgba(0,0,0,.18);padding:8px 10px;font-size:13px;line-height:1.5}
.rv-gloss b{display:block;margin-bottom:2px}
.rv #rv-gloss-all dl{display:grid;grid-template-columns:minmax(6rem,max-content) 1fr;gap:4px 12px;font-size:14px;margin:var(--cds-gap-sm) 0 0}
.rv #rv-gloss-all dt{font-weight:600}
.rv #rv-gloss-all dd{margin:0;color:var(--color-fg)}
.rv .rv-lg-btn{display:none}
@media (max-width:700px){
  .rv .rv-note,.rv .rv-sec-note,.rv .rv-asof{font-size:14px;line-height:1.6}
  .rv .rv-clampable{-webkit-line-clamp:3}
  .rv .rv-lg-btn{display:inline-flex}
  .rv #all-legend.rv-lg-closed{display:none}
  .rv .rv-tbl-wrap{max-height:70vh}
  .rv #rv-gloss-all dl{grid-template-columns:1fr}
  .rv #rv-gloss-all dd{margin:0 0 6px}
}
@media (pointer:coarse){
  .rv .rv-seg button{min-height:44px;padding:0 12px}
  .rv .rv-lgbtn{min-height:32px}
  .web-bar button{min-height:40px}
}
@media (max-width:700px) and (pointer:coarse){
  #all-chart .rv-tip{position:fixed!important;left:6px!important;right:6px!important;top:auto!important;bottom:calc(6px + env(safe-area-inset-bottom));max-height:52vh;overflow:hidden;white-space:normal;display:grid;grid-template-columns:1fr 1fr;column-gap:10px;row-gap:1px;font-size:11.5px;line-height:1.35;z-index:30;padding:8px 10px}
  #all-chart .rv-tip[hidden]{display:none!important}
  #all-chart .rv-tip .rv-tip-h{grid-column:1/-1;font-size:13px;font-weight:600;color:var(--color-fg)}
  #all-chart .rv-tip .rv-tip-r{min-width:0;align-items:flex-start}
  #all-chart .rv-tip .rv-tip-r.rv-wide{grid-column:1/-1}
  #all-chart .rv-tip .rv-tip-r b{font-weight:600;white-space:normal}
}
`;
  if (!document.getElementById('rv-mobile-css')) { const s = el('style'); s.id = 'rv-mobile-css'; s.textContent = css; document.head.appendChild(s); }

  // ---------- 2. 오늘 핵심 6개 + 갱신 시각
  const SCHED = [[8, 31], [15, 37], [20, 37]];   // GitHub 자동 수집(평일, KST)
  const kstNow = () => new Date(Date.now() + 9 * 3600e3);   // getUTC* 로 읽으면 KST
  const kstParse = s => { const m = String(s || '').match(/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/); return m ? Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]) : null; };   // KST 글자 → KST 기준 ms
  function sched(now, dir){                       // dir -1 = 지금 이전 마지막 예정, +1 = 다음 예정 (주말 제외, 휴장일은 모름)
    const day = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate());
    for (let k = 0; k < 10; k++) {
      const d = day + (dir < 0 ? -k : k) * 864e5, wd = new Date(d).getUTCDay(); if (wd === 0 || wd === 6) continue;
      const ts = SCHED.map(([h, m]) => d + (h * 60 + m) * 60e3); if (dir < 0) ts.reverse();
      for (const t of ts) if (dir < 0 ? t <= now.getTime() : t > now.getTime()) return t;
    }
    return null;
  }
  const hm = t => { const d = new Date(t); return String(d.getUTCHours()).padStart(2, '0') + ':' + String(d.getUTCMinutes()).padStart(2, '0'); };
  const ago = ms => ms < 60e3 ? '방금' : ms < 3600e3 ? Math.round(ms / 60e3) + '분 전' : ms < 86400e3 ? Math.round(ms / 3600e3) + '시간 전' : Math.round(ms / 86400e3) + '일 전';
  function freshness(){
    const h = rows('health').map(r => String(r.checked_at || '')).filter(Boolean).sort();
    const lastRun = h.length ? kstParse(h[h.length - 1]) : null; if (!lastRun) return null;
    const now = kstNow(), prev = sched(now, -1), next = sched(now, +1);
    const tag = (rows('health')[0] || {}).tag;
    const lab = {'0831': '아침 확정', '1540': '오후 잠정', '1840': '저녁 확정'}[String(tag).padStart(4, '0')] || '';
    const late = prev && lastRun < prev - 5 * 60e3 && now.getTime() - prev > 120 * 60e3;
    const nd = next ? new Date(next) : null, today = nd && nd.getUTCDate() === now.getUTCDate();
    return {late, text: [`갱신 ${ago(now.getTime() - lastRun)}`, `(${md(new Date(lastRun).toISOString())} ${hm(lastRun)}${lab ? ' ' + lab : ''})`],
      tail: late ? ` · 예정 ${hm(prev)} 갱신이 아직 없음(휴장일이면 정상)` : (next ? ` · 다음 ${today ? '' : md(nd.toISOString()) + ' '}${hm(next)} 무렵` : '')};
  }
  function tile(label, value, unit, note, alert){
    const t = el('div', 'rv-tile' + (alert ? ' rv-alert' : ''));
    t.append(el('div', 'rv-tile-l', label));
    const v = el('div', 'rv-tile-v', value); if (unit) v.append(el('small', null, unit)); t.append(v);
    if (note) t.append(el('div', 'rv-tile-n', note)); return t;
  }
  function buildToday(){
    const rv = RV(); if (!rv) return;
    let sec = document.getElementById('rv-today');
    if (!sec) {
      sec = el('section'); sec.id = 'rv-today';
      const card = el('div', 'rv-card rv-today');
      const head = el('div', 'rv-today-h'); head.append(el('h2', null, '오늘 핵심'), el('span', 'rv-fresh'));
      card.append(head, el('div', 'rv-tiles')); sec.append(card); rv.prepend(sec);
    }
    const fr = freshness(), fe = sec.querySelector('.rv-fresh'); fe.replaceChildren();
    if (fr) { fe.classList.toggle('rv-late', !!fr.late); const b = el('b', null, fr.text[0]); fe.append(b, document.createTextNode(' ' + fr.text[1] + fr.tail)); }
    const g = sec.querySelector('.rv-tiles'); g.replaceChildren();
    const m = last('market', r => num(r.kospi) != null), v = last('market', r => num(r.vkospi) != null);
    if (m) g.append(tile('코스피 · ' + md(m.date), fmt(num(m.kospi), 2), '', sg(num(m.kospi_chg_pct), 2) + '%' + (num(m.kosdaq) != null ? ' · 코스닥 ' + fmt(num(m.kosdaq), 2) : '') + (v ? ' · VKOSPI ' + fmt(num(v.vkospi), 2) : '')));
    const c = last('credit', r => num(r.credit_jo) != null);
    if (c) g.append(tile('신용융자 · 금투협 ' + md(c.date), fmt(num(c.credit_jo), 2), '조원', '전일 대비 ' + sg(num(c.chg_pct), 2) + '% · 예탁금 ' + fmt(num(c.deposit_jo), 1) + '조원', num(c.chg_pct) != null && num(c.chg_pct) <= -2.5));
    const l = last('liq', r => num(r.liq_eok) != null);
    if (l) g.append(tile('미수 반대매매 비중 · ' + md(l.date), fmt(num(l.ratio_pct), 1), '%', fmt(num(l.liq_eok), 1) + '억원 · 5% 넘으면 패닉 구간' + (() => { const e = window.rvLiqNowRows ? window.rvLiqNowRows() : []; const r = e[e.length - 1]; return r ? ` · ${md(r.d)} 예정 ${Math.round(r.p)}억(80% 범위 ${Math.round(r.lo)}~${Math.round(r.hi)}억, 추정 — 확정치 나오면 바뀜)` : ''; })(), num(l.ratio_pct) != null && num(l.ratio_pct) >= 5));
    const f = last('flows_daily', r => num(r.foreign_jo) != null);
    if (f) g.append(tile('외국인 순매수 · ' + md(f.date), sg(num(f.foreign_jo), 2), '조원', (/잠정/.test(f.basis || '') ? '잠정(정규장) · ' : '확정 · ') + '기관 ' + sg(num(f.inst_jo), 2) + ' · 개인 ' + sg(num(f.indiv_jo), 2), num(f.foreign_jo) != null && num(f.foreign_jo) <= -2));
    const q = last('q_daily', r => num(r.p_risk) != null);
    if (q) g.append(tile('5일 내 급락·청산 확률 · ' + md(q.date), fmt(num(q.p_risk) * 100, 0), '%', '신호 기준 27% · 국면 ' + (q.regime || '—'), num(q.p_risk) * 100 >= 27));
    if (m) {
      const day = String(m.date), on = [];
      rows('alarms').filter(r => String(r.date) === day).forEach(r => on.push(r.side + ' ' + r.type + (r.start === '시작' ? '(시작)' : '')));
      ['buy3', 'sell3'].forEach((id, i) => rows(id).filter(r => String(r.date) === day && +r.rank <= 2).forEach(r => on.push((i ? '매도' : '매수') + ' 최적화 ' + r.rank + '위')));
      const fp = last('fpanic'); if (fp && String(fp.date) === day && +fp.on === 1) on.push('외국인 투매·개인 매수(' + fp.n10 + '/10)');
      const re = last('reentry'); const reTxt = re ? '재진입 조합 ' + re.state : '';
      const cancel = rows('health').filter(r => r.status === '정정').length;
      const t = tile('켜진 신호 · ' + md(day), on.length ? on.length + '개' : '없음', '', [on.join(' · '), reTxt, cancel ? '정정 ' + cancel + '건(맨 위 빨간 띠)' : ''].filter(Boolean).join(' · '), cancel > 0);
      g.append(t);
    }
  }

  // ---------- 3. 구역 이동 메뉴 + 맨 위로 + 구역 번호·지난 구역 표시 + 옛 핵심 숫자 카드 옮기기
  const NAV = [['rv-today', '요약'], ['all', '그래프'], ['fpanic', '투매 신호'], ['qtop', '확률'], ['concl', '결론'], ['gapnext', '시초가'], ['amnext', '저녁장'], ['relief', '완화 조치'], ['trend11', '큰 흐름'], ['more', '세부'], ['rv-gloss-all', '용어']];
  function buildNav(){
    const rv = RV(); if (!rv) return;
    let nav = document.getElementById('rv-nav');
    if (!nav) { nav = el('nav', 'rv-nav'); nav.id = 'rv-nav'; nav.setAttribute('aria-label', '구역 이동'); }
    if (!nav.parentNode) RV().prepend(nav);
    nav.replaceChildren();
    NAV.forEach(([id, lab]) => { const t = document.getElementById(id); if (!t) return;
      const a = el('a', null, lab); a.href = '#' + id; a.dataset.id = id;
      a.addEventListener('click', e => { e.preventDefault(); if (t.tagName === 'DETAILS') t.open = true; t.scrollIntoView({behavior: 'smooth', block: 'start'}); });
      nav.append(a); });
    if (!window.__rvNavObs && 'IntersectionObserver' in window) {
      window.__rvNavObs = new IntersectionObserver(es => es.forEach(e => { if (!e.isIntersecting) return;
        document.querySelectorAll('#rv-nav a').forEach(a => a.setAttribute('aria-current', String(a.dataset.id === e.target.id)));
        const cur = document.querySelector('#rv-nav a[aria-current=true]'); if (cur && cur.scrollIntoView) { const n = cur.parentNode; n.scrollTo({left: cur.offsetLeft - n.clientWidth / 2 + cur.clientWidth / 2, behavior: 'smooth'}); } }),
        {rootMargin: '-60px 0px -70% 0px'});
    }
    if (window.__rvNavObs) NAV.forEach(([id]) => { const t = document.getElementById(id); if (t && !t.__rvObs) { window.__rvNavObs.observe(t); t.__rvObs = true; } });
    if (!document.querySelector('.rv-top')) {
      const b = el('button', 'rv-top', '↑'); b.type = 'button'; b.setAttribute('aria-label', '맨 위로');
      b.addEventListener('click', () => window.scrollTo({top: 0, behavior: 'smooth'})); document.body.append(b);
      const tg = () => b.classList.toggle('rv-show', window.scrollY > 1200); window.addEventListener('scroll', tg, {passive: true}); tg();
    }
  }
  const BADGE = {ind: '10/20 기준 고정 · 자동 갱신 아님', conc: '6~7월 자료 고정', oct: '그래프는 10/1부터 자동 · 투자자별 표는 10월 기록', past: '과거 국면 비교 · 고정'};
  function tidyHeads(){
    root.querySelectorAll('.rv h2').forEach(h => { if (h.dataset.rvNum) return; h.dataset.rvNum = '1';
      const t = h.firstChild; if (t && t.nodeType === 3) t.textContent = t.textContent.replace(/^\s*\d+\.\s*/, ''); });
    Object.entries(BADGE).forEach(([id, txt]) => { const s = document.getElementById(id), h = s && s.querySelector('h2'); if (h && !h.querySelector('.rv-badge')) h.append(el('span', 'rv-badge', txt)); });
    const k = document.getElementById('kpis'), body = document.querySelector('#more .rv-more-body');
    if (k && body && k.parentNode !== body.querySelector('#rv-kpis-old')) {
      let box = body.querySelector('#rv-kpis-old');
      if (!box) { box = el('section'); box.id = 'rv-kpis-old'; const h = el('h2', null, '10월 급락 당시 정점 기록'); h.append(el('span', 'rv-badge', '고정 · 신용·신용/예탁금 칸만 최신'));
        box.append(h, el('p', 'rv-sec-note', '맨 위 「오늘 핵심」이 최신 숫자이고, 이 카드는 10월 투매 때 정점과 비교하는 기록이다.')); body.prepend(box); }
      box.append(k);
    }
  }

  // ---------- 4. 결론 카드·긴 설명 접기
  function toggleBtn(target, cls, openTxt, closeTxt){
    const b = el('button', 'rv-more-btn', openTxt); b.type = 'button';
    b.addEventListener('click', () => { const open = target.classList.toggle(cls + '-open'); target.classList.toggle(cls, !open); b.textContent = open ? closeTxt : openTxt; });
    return b;
  }
  function clampCards(){
    document.querySelectorAll('#concl .rv-card:not(#concl-auto)').forEach(c => {
      c.querySelectorAll('ul > li').forEach(li => li.classList.toggle('rv-keep', !!li.querySelector('.rv-hot')));   // 빨간 강조가 있는 항목은 접어도 보인다
      if (c.dataset.rvCl) return; c.dataset.rvCl = '1';
      const n = c.querySelectorAll('ul > li').length, long = (c.querySelector('.rv-verdict') || {}).textContent || '';
      if (n <= 3 && long.length < 400) return;
      c.classList.add('rv-cl'); c.append(toggleBtn(c, 'rv-cl', '전체 보기 ▾', '접기 ▴'));
    });
  }
  function clampNotes(){
    document.querySelectorAll('.rv p.rv-note, .rv p.rv-sec-note, .rv p.rv-asof').forEach(p => {
      if (p.dataset.rvNc || p.closest('#rv-today, .rv-tip')) return;
      if ((p.textContent || '').length < 260) return;
      p.dataset.rvNc = '1'; p.classList.add('rv-clampable');
      const b = el('button', 'rv-more-btn', '설명 더 보기 ▾'); b.type = 'button';
      b.addEventListener('click', () => { const op = p.classList.toggle('rv-clampable'); b.textContent = op ? '설명 더 보기 ▾' : '접기 ▴'; });
      p.after(b);
    });
  }

  // ---------- 5. 표: 옆으로 밀기 표시 + 첫 열 고정
  function markTables(){
    document.querySelectorAll('.rv .rv-tbl-wrap').forEach(w => {
      if (!w.offsetParent) return;
      const t = w.querySelector('table'); if (!t) return;
      const over = w.scrollWidth > w.clientWidth + 4;
      w.classList.toggle('rv-xs', over);
      let h = w.previousElementSibling; if (!(h && h.classList.contains('rv-xs-hint'))) h = null;
      if (over && !h) { h = el('p', 'rv-xs-hint'); w.before(h); }
      if (h) { h.hidden = !over; h.textContent = '← 표를 옆으로 밀면 ' + ((t.rows[0] || {cells: []}).cells.length) + '개 열이 모두 보인다 →'; }
    });
  }

  // ---------- 6. 용어 풀이
  const TERMS = [
    ['미수 반대매매', '외상(미수)으로 산 주식 대금을 결제일(거래 이틀 뒤)까지 못 내서 증권사가 강제로 판 금액.'],
    ['투자자예탁금', '주식을 사려고 증권 계좌에 넣어 둔 현금.'],
    ['예탁금', '투자자예탁금. 주식을 사려고 증권 계좌에 넣어 둔 현금.'],
    ['미수금', '결제일까지 아직 내지 않은 주식 외상 대금.'],
    ['신용융자', '증권사에서 돈을 빌려 산 주식의 대출 잔고. 주가가 빠지면 담보 부족으로 강제 처분될 수 있다.'],
    ['담보비율', '계좌의 주식 평가액 ÷ 빌린 돈. 기준(보통 140%) 밑으로 떨어지면 강제 처분 대상이 된다.'],
    ['VKOSPI', '코스피200 옵션 가격으로 계산한 앞으로 한 달 변동성 예상치. 높을수록 시장이 불안하다는 뜻.'],
    ['VIX', '미국 S&P500 옵션으로 계산한 변동성 지수(공포 지수).'],
    ['야간선물', '코스피200 선물의 저녁 18시~다음 날 6시 거래. 다음 날 시초가 방향을 미리 보여 준다.'],
    ['애프터마켓', '정규장이 끝난 뒤 15:40~20:00 저녁 거래.'],
    ['사이드카', '선물 가격이 크게 움직일 때 프로그램 매매 주문을 5분 멈추는 장치.'],
    ['서킷브레이커', '지수가 크게 떨어지면(1단계 8%) 주식 거래 전체를 20분 멈추는 장치.'],
    ['고변동 청산', '이 대시보드의 국면 이름 — 신용 5일 −3% 이하 또는 VKOSPI 5일 +25% 이상인 날.'],
    ['큰 흐름', '코스피가 10% 이상 되돌린 지점을 기준으로 나중에 나눈 상승·하락 구간(사후 판정).'],
    ['헛신호', '신호가 켜진 뒤 20거래일 안에 10% 이상 움직이지 않은 신호.'],
    ['재진입 조합', '엄격형 매도·매수 신호에, 신호가 틀렸을 때 다시 사고파는 규칙을 더한 것.'],
    ['걷기 검증', '앞 기간 자료로만 고른 규칙을 처음 보는 다음 기간에 시험하는 방식. 결과에 맞춰 고르는 것을 막는다.'],
    ['AUC', '예측이 맞는 날과 틀리는 날을 얼마나 잘 가르는지. 0.5는 동전 던지기, 1에 가까울수록 좋다.'],
    ['부스팅', '작은 결정 나무 여러 개를 이어 쌓아 확률을 내는 머신러닝 모형.'],
    ['로지스틱', '여러 지표를 더해 확률로 바꾸는 기본 통계 모형.'],
    ['MACD', '단기(12일)와 장기(26일) 지수이동평균의 차이로 본 추세 지표.'],
    ['ATR14', '최근 14거래일 하루 변동폭의 평균. 클수록 출렁임이 크다.'],
    ['RSI14', '최근 14거래일 오른 폭의 비중으로 본 과열·침체 지표(70 위 과열, 30 아래 침체).'],
    ['SMA60', '최근 60거래일 종가의 단순 평균(60일선).'],
    ['이격도', '지수가 이동평균선에서 몇 % 떨어져 있는지.'],
    ['NXT', '넥스트레이드. 2025년 3월 문을 연 대체거래소.'],
    ['금투협', '금융투자협회. 신용융자·예탁금·미수 반대매매 통계를 다음 영업일에 공시한다.']
  ];
  const TMAP = new Map(TERMS);
  const TRE = new RegExp('(' + TERMS.map(t => t[0].replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|') + ')', 'g');
  const SKIP = 'svg,table,button,script,style,a,summary,select,textarea,.rv-tip,.rv-term,.rv-v,.rv-legend,#all-legend,#rv-today,#rv-nav,#rv-gloss-all,.rv-gloss,h1,h2,h3,h4';
  function glossary(){
    const scope = Array.from(document.querySelectorAll('.rv p, .rv li'));
    const seen = new WeakMap();
    scope.forEach(p => {
      if (p.closest(SKIP)) return;
      const box = p.closest('.rv-card, section, details') || p; let used = seen.get(box); if (!used) { used = new Set(); seen.set(box, used); }
      p.querySelectorAll('.rv-term').forEach(x => used.add(x.dataset.t));
      const walker = document.createTreeWalker(p, NodeFilter.SHOW_TEXT, {acceptNode: n => n.parentElement && n.parentElement.closest(SKIP) ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT});
      const nodes = []; while (walker.nextNode()) nodes.push(walker.currentNode);
      nodes.forEach(n => {
        const s = n.textContent; TRE.lastIndex = 0; let m, out = null, pos = 0;
        while ((m = TRE.exec(s))) {
          const w = m[1]; if (used.has(w)) continue;
          const pre = s[m.index - 1] || '', post = s[m.index + w.length] || '';
          if (/^[A-Z0-9]+$/.test(w) && (/[A-Za-z0-9]/.test(pre) || /[A-Za-z0-9]/.test(post))) continue;   // 영문 약어는 단어 경계에서만
          used.add(w); out = out || document.createDocumentFragment();
          out.append(document.createTextNode(s.slice(pos, m.index)));
          const b = el('button', 'rv-term', w); b.type = 'button'; b.dataset.t = w; out.append(b); pos = m.index + w.length;
        }
        if (out) { out.append(document.createTextNode(s.slice(pos))); n.replaceWith(out); }
      });
    });
    if (!document.getElementById('rv-gloss-all')) {
      const d = el('details', 'rv-more'); d.id = 'rv-gloss-all';
      d.append(el('summary', null, '용어 모음 — 이 대시보드에 나오는 말'));
      const dl = el('dl'); TERMS.filter(t => t[0] !== '예탁금').forEach(([k, v]) => dl.append(el('dt', null, k), el('dd', null, v))); d.append(dl);
      const more = document.getElementById('more'); if (more) more.after(d); else { const rv = RV(); if (rv) rv.append(d); }
    }
  }
  let pop = null;
  const closePop = () => { if (pop) { pop.remove(); pop = null; } };
  document.addEventListener('click', e => {
    const t = e.target.closest && e.target.closest('.rv-term');
    if (!t) { closePop(); return; }
    e.preventDefault(); e.stopPropagation(); const same = pop && pop.dataset.t === t.dataset.t; closePop(); if (same) return;
    pop = el('div', 'rv-gloss'); pop.dataset.t = t.dataset.t; pop.append(el('b', null, t.dataset.t), document.createTextNode(TMAP.get(t.dataset.t) || ''));
    document.body.append(pop);
    const r = t.getBoundingClientRect(), w = pop.offsetWidth;
    pop.style.left = Math.max(8, Math.min(window.scrollX + r.left, window.scrollX + document.documentElement.clientWidth - w - 8)) + 'px';
    pop.style.top = (window.scrollY + r.bottom + 6) + 'px';
  }, true);
  window.addEventListener('scroll', closePop, {passive: true});

  // ---------- 7. 한눈에 보기 그래프: 범례 접기(휴대폰), 선 끝 이름표, 하락 칸 빗금, 상세 상자 줄 넓이
  function legendToggle(){
    const lg = document.getElementById('all-legend'); if (!lg) return;
    let b = document.getElementById('rv-lg-btn');
    if (!b) { b = el('button', 'rv-more-btn rv-lg-btn'); b.id = 'rv-lg-btn'; b.type = 'button'; lg.before(b);
      if (phone()) lg.classList.add('rv-lg-closed');
      b.addEventListener('click', () => { lg.classList.toggle('rv-lg-closed'); setLgTxt(); }); }
    setLgTxt();
  }
  function setLgTxt(){
    const lg = document.getElementById('all-legend'), b = document.getElementById('rv-lg-btn'); if (!lg || !b) return;
    const n = lg.children.length, off = lg.querySelectorAll('[aria-pressed=false]').length;
    b.textContent = lg.classList.contains('rv-lg-closed') ? `범례 보기 · ${n}개(끈 것 ${off}개) ▾` : '범례 접기 ▴';
  }
  function decorateChart(){
    const box = document.getElementById('all-chart'), svg = box && box.querySelector('svg'); if (!svg || svg.__rvDone) return; svg.__rvDone = true;
    const NS = 'http://www.w3.org/2000/svg';
    // 하락(빨강) 칸에 빗금 — 색을 구분하기 어려워도 상승·하락이 갈린다
    let defs = svg.querySelector('defs'); if (!defs) { defs = document.createElementNS(NS, 'defs'); svg.prepend(defs); }
    const pat = document.createElementNS(NS, 'pattern'); pat.id = 'rv-hdn'; pat.setAttribute('patternUnits', 'userSpaceOnUse'); pat.setAttribute('width', 6); pat.setAttribute('height', 6); pat.setAttribute('patternTransform', 'rotate(45)');
    const bg = document.createElementNS(NS, 'rect'); bg.setAttribute('width', 6); bg.setAttribute('height', 6); bg.style.fill = 'var(--cds-chart-status-critical)';
    const ln = document.createElementNS(NS, 'line'); ln.setAttribute('x1', 0); ln.setAttribute('y1', 0); ln.setAttribute('x2', 0); ln.setAttribute('y2', 6); ln.setAttribute('stroke', '#fff'); ln.setAttribute('stroke-width', 2); ln.setAttribute('opacity', .55);
    pat.append(bg, ln); defs.append(pat);
    svg.querySelectorAll('g[clip-path] rect').forEach(r => { if (/critical/.test(r.style.fill || '')) r.style.fill = 'url(#rv-hdn)'; });
    // 선 끝 이름표: 범례의 선 색과 이름을 짝지어 코스피 칸 선의 마지막 점 옆에 적는다
    const names = [];
    document.querySelectorAll('#all-legend > *').forEach(it => { const sw = it.querySelector('.rv-sw'); if (!sw || it.getAttribute('aria-pressed') === 'false') return;
      const bgc = sw.style.background || '', txt = (it.textContent || '').replace(/\(.*$/, '').replace(/ · .*$/, '').trim();
      if (/^(코스피|코스닥|신용|투자자예탁금|VKOSPI|원\/달러)/.test(txt)) names.push([bgc, txt]); });
    const titles = Array.from(svg.querySelectorAll('text.rv-ptitle')); if (titles.length < 2) return;
    const top = +titles[0].getAttribute('y'), bot = +titles[1].getAttribute('y') - 6;
    const labs = [];
    svg.querySelectorAll('path').forEach(p => {
      if ((p.getAttribute('fill') || '') !== 'none') return;
      const st = p.style.stroke || ''; if (!st || /e6b800/i.test(st)) return;
      const nm = names.find(([c]) => c && (c.indexOf(st) >= 0 || st.indexOf(c) >= 0)); if (!nm) return;
      const pts = (p.getAttribute('d') || '').match(/-?\d+(\.\d+)?,-?\d+(\.\d+)?/g); if (!pts || pts.length < 2) return;
      const [x, y] = pts[pts.length - 1].split(',').map(Number); if (y < top || y > bot) return;
      if (labs.some(l => l.name === nm[1])) return;
      labs.push({x, y, ty: y, name: nm[1] === '코스피' ? '코스피' : nm[1].replace('신용융자 전체', '신용').replace('투자자예탁금', '예탁금').replace('원/달러 환율', '원/달러'), c: st});
    });
    labs.sort((a, b) => a.y - b.y); for (let i = 1; i < labs.length; i++) if (labs[i].ty - labs[i - 1].ty < 11) labs[i].ty = labs[i - 1].ty + 11;
    labs.forEach(l => { const t = document.createElementNS(NS, 'text'); t.setAttribute('x', l.x - 4); t.setAttribute('y', l.ty - 6); t.setAttribute('text-anchor', 'end'); t.setAttribute('class', 'rv-tick');
      t.style.fill = l.c; t.style.fontSize = '10px'; t.style.fontWeight = '600'; t.style.paintOrder = 'stroke'; t.style.stroke = 'var(--color-panel)'; t.style.strokeWidth = '3px'; t.textContent = l.name; svg.append(t); });
  }
  function legendHatch(){
    document.querySelectorAll('#all-legend > *').forEach(it => { if (/^큰 흐름 하락/.test((it.textContent || '').trim())) { const sw = it.querySelector('.rv-sw'); if (sw && !sw.dataset.rvH) { sw.dataset.rvH = '1'; sw.style.background = 'repeating-linear-gradient(45deg, var(--cds-chart-status-critical) 0 3px, rgba(255,255,255,.6) 3px 4.5px)'; } } });
  }
  function tipRows(tip){ tip.querySelectorAll('.rv-tip-r').forEach(r => { const n = r.querySelector('span:not(.rv-sw)'); const b = r.querySelector('b'); r.classList.toggle('rv-wide', !n || !n.textContent.trim() || (b && b.textContent.length > 22)); }); }
  function watchChart(){
    const box = document.getElementById('all-chart'); if (!box || box.__rvObs) return; box.__rvObs = true;
    new MutationObserver(ms => { let svgNew = false, tip = null;
      ms.forEach(m => { m.addedNodes.forEach(n => { if (n.nodeName === 'svg') svgNew = true; }); const t = m.target.closest ? m.target.closest('.rv-tip') : null; if (t) tip = t; else if (m.target.classList && m.target.classList.contains('rv-tip')) tip = m.target; });
      if (svgNew) { legendHatch(); setLgTxt(); decorateChart(); }
      if (tip) tipRows(tip);
    }).observe(box, {childList: true, subtree: true});
    decorateChart(); legendHatch();
  }

  // 자리 잡기: 맨 위 빨간 띠(hot-box, relief.js 가 머리말 바로 뒤에 둠) 다음에 메뉴 → 오늘 핵심. relief.js 가 그래프를 띠 바로 뒤로 옮기므로 매번 다시 맞춘다
  function place(){
    const rv = RV(), nav = document.getElementById('rv-nav'), sec = document.getElementById('rv-today'); if (!rv || !nav || !sec) return;
    const a = document.getElementById('hot-box') || rv.querySelector(':scope > header'); if (!a || a.parentNode !== rv) return;
    if (a.nextElementSibling !== nav) a.after(nav);
    if (nav.nextElementSibling !== sec) nav.after(sec);
  }

  // ---------- 실행
  function run(){
    try { buildToday(); } catch (e) { console.error('rv today', e); }
    try { tidyHeads(); clampCards(); clampNotes(); } catch (e) { console.error('rv tidy', e); }
    try { glossary(); } catch (e) { console.error('rv gloss', e); }
    try { buildNav(); place(); } catch (e) { console.error('rv nav', e); }
    try { legendToggle(); watchChart(); markTables(); } catch (e) { console.error('rv chart', e); }
  }
  dash.onData(() => setTimeout(run, 0));
  let rzT = null; window.addEventListener('resize', () => { clearTimeout(rzT); rzT = setTimeout(markTables, 250); });
  document.addEventListener('toggle', e => { if (e.target && e.target.tagName === 'DETAILS') setTimeout(() => { markTables(); clampNotes(); glossary(); }, 50); }, true);
  setInterval(() => { const fe = document.querySelector('#rv-today .rv-fresh'); if (fe && document.visibilityState === 'visible') { try { buildToday(); } catch (e) {} } }, 5 * 60e3);   // '몇 분 전'을 5분마다 고친다
})();
