// 2026-11-16 추가: 한눈에 보기 그래프 터치 동작. 사용자 요청 "진행해"(그래프 동작 2~5번)
// 2 움직이는 동안 실제 그래프로 다시 그리기: 손가락을 따라 그래프 안쪽을 바로 옮겨 보여 주고, 그리기 시간에 맞춘 짧은 간격으로 진짜로 다시 그린다
// 3 축 고정: 왼쪽·오른쪽 눈금, 줄 이름, 칸 제목, 가로 기준선은 제자리. 그래프 안쪽(선·막대·신호·날짜)만 움직이고 그래프 칸 밖으로는 안 나간다
// 4 관성: 가로로 밀고 손을 떼면 조금 더 미끄러지다 멈춘다. 끝(2015년 첫날·마지막 자료일)에서는 살짝 늘어났다가 돌아온다
// 5 그리기 속도: index.html 쪽(날짜 읽기·글자 폭·자료 묶음 재사용)에서 줄였고, 이 파일은 그 시간을 재서 다시 그리는 간격을 맞춘다
// 그대로 둔 것: 한 번 터치 = 그날 상세, 0.35초 누르고 좌우 = 상세 날짜 이동, 화면 아무 데나 다시 터치 = 닫기, 세로로 밀기 = 화면 스크롤
// index.html 과 변수를 나누지 않는다. 쓰는 것은 #all-chart 의 _rvApi(기간 읽기·정하기), _rvPlot(그래프 칸 좌우 끝), _rvShow/_rvHide(상세)
(function(){
  if (window.__rvGesture) return; window.__rvGesture = true;
  const box = document.getElementById('all-chart'); if (!box) return;
  const api = () => box._rvApi;
  box.style.touchAction = 'pan-y';
  box.style.webkitUserSelect = box.style.userSelect = 'none'; box.style.webkitTouchCallout = 'none';
  const NS = 'http://www.w3.org/2000/svg';
  let seq = 0;
  const liveSvg = () => box.querySelector('svg:not([data-rv-ghost])');

  // ---- 움직이는 층: 그래프 칸 안쪽 요소만 묶어서 옮긴다(축·이름표는 밖에 둔다)
  function layer(){
    const sv = liveSvg(); if (!sv) return null;
    if (sv.__rvL) return sv.__rvL;
    const vb = sv.viewBox && sv.viewBox.baseVal; if (!vb || !vb.width) return null;
    const W = vb.width, H = vb.height, pl = box._rvPlot || [0, W], L = pl[0], R = pl[1];
    const hline = e => e.tagName === 'line' && e.getAttribute('y1') === e.getAttribute('y2') && e.getAttribute('x1') !== e.getAttribute('x2');
    const fixed = e => {
      const t = e.tagName;
      if (t === 'defs' || t === 'clipPath' || t === 'style') return true;
      if (t === 'text' && /rv-ptitle/.test(e.getAttribute('class') || '')) return true;
      if (hline(e)) return true;
      if (t === 'g' && e.childElementCount && Array.from(e.children).every(hline)) return true;
      let b; try { b = e.getBBox(); } catch (x) { return false; }
      if (!b.width && !b.height) return false;
      if (b.x + b.width <= L + 1 || b.x >= R - 1) return true;          // 왼쪽·오른쪽 눈금, 줄 이름, 오른쪽 % 숫자
      if (t === 'rect' && b.width >= (R - L) * 0.9) return true;         // 손가락·마우스를 받는 판
      return false;
    };
    let defs = sv.querySelector(':scope > defs'); if (!defs) { defs = document.createElementNS(NS, 'defs'); sv.prepend(defs); }
    const id = 'rvgc' + (++seq), cp = document.createElementNS(NS, 'clipPath'); cp.id = id;
    const cr = document.createElementNS(NS, 'rect'); cr.setAttribute('x', L); cr.setAttribute('y', 0); cr.setAttribute('width', R - L); cr.setAttribute('height', H); cp.append(cr); defs.append(cp);
    const clipG = document.createElementNS(NS, 'g'); clipG.setAttribute('clip-path', 'url(#' + id + ')');
    const g = document.createElementNS(NS, 'g'); clipG.append(g);
    const kids = Array.from(sv.children).filter(e => e !== defs && !fixed(e));
    if (kids.length) { sv.insertBefore(clipG, kids[0]); kids.forEach(k => g.append(k)); }
    const r = sv.getBoundingClientRect();
    return (sv.__rvL = {g, L, R, k: r.width / W});
  }

  // ---- 손가락이 처음 닿은 요소가 다시 그리기로 지워지면 브라우저가 그 뒤 움직임을 이 상자에 안 보낸다 → 보이지 않게 붙여 둔다
  let ghost = null;
  function keepTarget(){ if (ghost && !ghost.isConnected) { ghost.setAttribute('data-rv-ghost', '1'); ghost.style.cssText = 'position:absolute;left:0;top:0;width:1px;height:1px;opacity:0;pointer-events:none;overflow:hidden'; box.append(ghost); } }
  function dropGhost(){ if (ghost && ghost.getAttribute('data-rv-ghost')) ghost.remove(); ghost = null; }

  // ---- 상태: S = 전체 거래일, D = 지금 그려진 기간, T = 손가락이 가리키는 기간(소수 허용) — 위치는 거래일 번호
  let S = null, D = null, T = null, raf = 0, inert = null, moving = false, lastDraw = 0, drawCost = 80, justDrew = false;
  const gap = () => Math.max(120, drawCost * 1.5);
  function cur(){ const a = api(), days = a.days(), [i0, i1] = a.idx(days); return {s: i0, l: i1 - i0 + 1, last: days.length - 1, n: days.length}; }
  function clampS(s, l, soft){
    const max = S.last - l + 1;
    if (s < 0) return soft ? -Math.min(l * 0.06, -s * 0.35) : 0;
    if (s > max) return soft ? max + Math.min(l * 0.06, (s - max) * 0.35) : max;
    return s;
  }
  function begin(){ if (D) return true; if (!api()) return false; const c = cur(); S = {last: c.last, n: c.n}; D = {s: c.s, l: c.l}; T = {s: c.s, l: c.l}; hideTip(); return true; }
  function paint(){
    const Ly = layer(); if (!Ly || !T) return;
    const sx = (D.l - 1) / Math.max(1, T.l - 1), tx = Ly.L - Ly.L * sx + (D.s - T.s) / Math.max(1, T.l - 1) * (Ly.R - Ly.L);
    Ly.g.setAttribute('transform', Math.abs(sx - 1) < 1e-4 ? `translate(${tx.toFixed(2)},0)` : `translate(${tx.toFixed(2)},0) scale(${sx.toFixed(5)},1)`);
  }
  function tick(now){
    raf = 0; if (!T) return;
    if (inert) {
      const dt = Math.min(48, now - inert.t); inert.t = now; inert.dx += inert.v * dt; inert.v *= Math.pow(0.994, dt); if (Math.abs(inert.dx) >= inert.max) { inert.dx = Math.sign(inert.dx) * inert.max; inert.v = 0; }
      const raw = inert.s0 - inert.dx / inert.px, cl = clampS(raw, T.l, false); T.s = cl;
      if (Math.abs(inert.v) < 0.03 || cl !== raw) { inert = null; finish(); return; }
    }
    paint(); justDrew = false;
    if (performance.now() - lastDraw >= gap()) {
      const rl = Math.round(T.l), rs = Math.round(clampS(T.s, rl, false));
      if (rs !== D.s || rl !== D.l) {
        const t = performance.now(), ch = api().set(rs, rl, true);
        if (ch) { drawCost = drawCost * 0.6 + (performance.now() - t) * 0.4; keepTarget(); const c = cur(); D = {s: c.s, l: c.l}; justDrew = true; }   // 새 그림의 층은 다음 프레임에(mobile.js 꾸밈이 끝난 뒤) 만든다
        lastDraw = performance.now();
      }
    }
    if (inert || justDrew || (moving && (Math.round(T.s) !== D.s || Math.round(T.l) !== D.l))) req();
  }
  const req = () => { if (!raf) raf = requestAnimationFrame(tick); };
  function finish(){
    if (raf) { cancelAnimationFrame(raf); raf = 0; }
    inert = null; moving = false; if (!T) return;
    const a = api(), rl = Math.round(T.l), rs = Math.round(clampS(T.s, rl, false));
    S = D = T = null;
    if (a && !a.set(rs, rl, false) && a.draw) a.draw();          // 같은 기간이어도 한 번 새로 그려 옮기던 층을 걷는다
    lastDraw = performance.now();
  }

  // ---- 상세(한 번 터치, 누르고 좌우)
  let one = null, pin = null, open = false, closing = false;
  function hideTip(){ open = false; if (box._rvHide) box._rvHide(); }
  function openTip(c){ const r = box.getBoundingClientRect(); if (box._rvShow && box._rvShow(c.clientX - r.left, c.clientY - r.top)) open = true; }
  const gapX = ts => Math.abs(ts[0].clientX - ts[1].clientX);
  const clearOne = () => { if (one) clearTimeout(one.timer); one = null; };

  document.addEventListener('touchstart', () => { closing = open; if (open) hideTip(); if (inert) finish(); }, {capture: true, passive: true});   // 상세가 떠 있으면 어디를 터치해도 닫고, 미끄러지던 그래프는 그 자리에서 멈춘다
  box.addEventListener('gesturestart', e => e.preventDefault());
  box.addEventListener('contextmenu', e => { if (one || pin) e.preventDefault(); });
  box.addEventListener('touchstart', e => {
    if (!ghost) { ghost = (e.target.closest && e.target.closest('svg')) || null; keepTarget(); }
    if (e.touches.length >= 2) {
      e.preventDefault(); clearOne(); if (!pin) startPinch(e.touches);
    } else if (e.touches.length === 1 && !pin) {
      const c = e.touches[0];
      one = {x: c.clientX, y: c.clientY, t: Date.now(), closing, mode: null};
      one.timer = setTimeout(() => { if (one && !one.mode) { one.mode = 'scrub'; openTip({clientX: one.x, clientY: one.y}); } }, 350);
    }
  }, {passive: false});
  function startPinch(ts){
    if (!begin()) return;
    moving = true; const Ly = layer(); const r = liveSvg().getBoundingClientRect();
    const cxv = ((ts[0].clientX + ts[1].clientX) / 2 - r.left) / (Ly ? Ly.k : 1);
    const fr = Ly ? Math.max(0, Math.min(1, (cxv - Ly.L) / Math.max(1, Ly.R - Ly.L))) : 0.5;
    const s0 = clampS(T.s, T.l, false);
    pin = {d0: Math.max(24, gapX(ts)), l: T.l, ai: s0 + fr * (T.l - 1), fr, end: s0 + T.l - 1 >= S.last - 0.5 && fr > 0.85};   // 최근 끝 근처에서 하면 최근 날짜를 붙잡는다
  }
  function startPan(c){
    if (!begin()) return false;
    moving = true; const Ly = layer();
    one.pan = {x0: c.clientX, s0: T.s, px: Ly ? (Ly.R - Ly.L) * Ly.k / Math.max(1, T.l - 1) : 1, sm: []};
    return true;
  }
  function panMove(c, ts){
    const p = one.pan, now = ts || performance.now();   // 손가락이 움직인 시각(이벤트 시각) — 다시 그리느라 늦게 처리돼도 속도가 틀어지지 않게
    T.s = clampS(p.s0 - (c.clientX - p.x0) / p.px, T.l, true);
    p.sm.push([now, c.clientX]); while (p.sm.length > 2 && now - p.sm[0][0] > 250) p.sm.shift();
    req();
  }
  box.addEventListener('touchmove', e => {
    if (pin) {
      e.preventDefault();
      if (e.touches.length >= 2 && T) {
        const k = Math.max(0.2, Math.min(8, gapX(e.touches) / pin.d0));   // 1보다 크면 벌림 = 기간 좁게
        const len = Math.max(10, Math.min(S.n, pin.l / k)), s = pin.end ? S.last - len + 1 : pin.ai - pin.fr * (len - 1);
        T = {s: clampS(s, len, false), l: len}; req();
      }
      return;
    }
    if (!one || e.touches.length !== 1) return;
    const c = e.touches[0], dx = c.clientX - one.x, dy = c.clientY - one.y;
    if (one.mode === 'scrub') { e.preventDefault(); openTip(c); return; }
    if (one.mode === 'pan') { e.preventDefault(); panMove(c, e.timeStamp); return; }
    if (Math.abs(dx) < 10 && Math.abs(dy) < 10) return;
    clearTimeout(one.timer);
    if (Math.abs(dx) > Math.abs(dy) * 1.2) { e.preventDefault(); one.mode = 'pan'; if (startPan(c)) panMove(c, e.timeStamp); else one = null; }   // 가로로 밀기 = 기간 이동
    else one = null;                                                                                                          // 세로로 움직이면 화면 스크롤
  }, {passive: false});
  box.addEventListener('touchend', e => {
    if (pin) { e.preventDefault(); if (e.touches.length === 0) { pin = null; finish(); dropGhost(); } return; }
    if (!one || e.touches.length) { if (!e.touches.length) dropGhost(); return; }
    const o = one; clearOne(); dropGhost();
    if (o.mode === 'pan' && o.pan) {
      e.preventDefault(); moving = false;
      const sm = o.pan.sm, now = e.timeStamp || performance.now(), lt = sm.length ? sm[sm.length - 1][0] : -1e9, rec0 = sm.filter(q => lt - q[0] <= 150), rec = rec0.length >= 2 ? rec0 : sm.slice(-2).filter(q => lt - q[0] <= 250);   // 마지막 움직임 직전 0.15초로 속도를 잰다(느린 폰에서 움직임이 묶여 들어오면 마지막 두 점)
      let v = 0; if (rec.length >= 2 && now - lt < 80) { const a = rec[0], b = rec[rec.length - 1]; if (b[0] - a[0] > 8) v = (b[1] - a[1]) / (b[0] - a[0]); }
      box.dataset.rvFling = v.toFixed(2) + '/' + rec.length + '/' + Math.round(now - lt);   // 시험용 기록(놓을 때 속도 px/ms · 표본 수 · 마지막 움직임 뒤 ms)
      if (T && Math.abs(v) > 0.2 && T.s === clampS(T.s, T.l, false)) { inert = {v, dx: 0, s0: T.s, px: o.pan.px, t: performance.now(), max: T.l * o.pan.px}; req(); }   // 미끄러지는 거리는 화면에 보이는 기간 한 번만큼까지   // px/ms
      else finish();
      return;
    }
    if (o.mode === 'scrub') { e.preventDefault(); return; }   // 손을 떼도 상세는 남고, 아무 데나 다시 터치하면 닫힌다
    if (o.closing || Date.now() - o.t > 600) return;
    e.preventDefault();                                       // 뒤따르는 가짜 마우스 이벤트가 상세를 다시 띄우지 않게
    openTip(e.changedTouches[0]);
  }, {passive: false});
  box.addEventListener('touchcancel', () => { pin = null; clearOne(); if (T && !inert) finish(); dropGhost(); });
})();
