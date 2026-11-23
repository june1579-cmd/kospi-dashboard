/* 묶음 상위 3개 표시(2026-11-24 사용자 요청) — 한눈에 보기 그래프 코스피 칸 맨 아래에 가로 막대 세 줄. 이 파일과 page.html 의 bundle.js 줄을 지우면 원래대로 돌아간다.
   자료: bundle_sig(고정 파일, 만든 코드 study/bundle_top3.py) — 연구소 갈래 A·B·C 상위 20위 조합을 1~3개씩 합친 것 가운데 코스피 지수 기준 단순 합계 수익률 상위 3개 */
(() => {
  const MADE = '2026-11-20', COL = ['#1e88e5', '#8d6e63', '#78909c'], POS = ['첫째 줄', '둘째 줄', '셋째 줄'], LH = 5, STEP = 7;
  const OFF = window.__rvBundleOff || (window.__rvBundleOff = new Set());
  const iso = v => String(v || '').slice(0, 10), md = d => +d.slice(5, 7) + '/' + +d.slice(8, 10), ymd = d => d.slice(2, 4) + '년 ' + md(d), pc = v => (v > 0 ? '+' : '') + v.toFixed(1) + '%';
  let memo = null;
  const sets = () => {
    let g; try { g = dash.data('bundle_sig'); } catch (e) { return null; }
    if (!g || g.status !== 'ok' || !Array.isArray(g.data) || !g.data.length) return null;
    if (memo && memo.src === g.data) return memo.sets;
    const S = [0, 1, 2].map(i => ({i, nm: '', t: []}));
    g.data.forEach(r => { const i = +r.rank - 1, ret = +r.ret_pct; if (!S[i] || !isFinite(ret)) return; S[i].nm = String(r.bundle || ''); S[i].t.push({c: iso(r.cond), b: iso(r.buy), s: iso(r.sell), r: ret, src: String(r.src || '')}); });
    memo = {src: g.data, sets: S}; return S;
  };
  const redraw = () => { const box = document.getElementById('all-chart'); if (box && box._rvApi && box._rvApi.draw) box._rvApi.draw(); };
  const draw = (svg, xd, P0) => {
    const SETS = sets(); if (!SETS) return;
    const xa = xd('1900-01-01'), xb = xd('2999-12-31'); if (!isFinite(xa) || !isFinite(xb)) return;
    // 이미 그려진 표시(세모·연구소 원과 반원·전환 신호 네모)의 세로 자리를 읽는다
    const TRI = d3.symbol(d3.symbolTriangle, 64)(), ext = [];
    svg.selectAll('path').each(function () { const t = this.getAttribute('transform') || '', m = /translate\(([^,]+),([^)]+)\)/.exec(t); if (!m) return;
      const lab = this.parentNode && this.parentNode.getAttribute && this.parentNode.getAttribute('class') === 'rv-labsig'; if (this.getAttribute('d') === TRI || lab) ext.push([+m[2] - 9, +m[2] + 9]); });
    svg.selectAll('.rv-labsig circle').each(function () { const y = +this.getAttribute('cy'); ext.push([y - 8, y + 8]); });
    svg.selectAll('.rv-turnsig rect').each(function () { const y = +this.getAttribute('y'), h = +this.getAttribute('height'); ext.push([y - 1, y + h + 1]); });
    const BH = STEP * 3, yBot = P0.bot - BH - 2, cb = ext.filter(e => e[1] > yBot - 2 && e[0] < yBot + BH + 2).length;
    // 맨 아래 띠에 다른 표시가 하나라도 닿으면(긴 기간을 좁은 화면에 볼 때) 코스피 칸과 아래 칸 사이 빈 틈(12px)으로 내려 가늘게 그린다 — 그 틈에는 신호 표시가 없다
    const gap = cb > 0, lh = gap ? 3 : LH, stp = gap ? 4 : STEP, y0 = gap ? P0.bot + 1 : yBot;
    const gg = svg.append('g').attr('class', 'rv-bundle'), vis = {};
    SETS.forEach(S => { const v = vis[S.i] = S.t.filter(p => { const a = xd(p.b), b = xd(p.s); return isFinite(a) && isFinite(b) && b > xa + 0.01 && a < xb - 0.01; }); if (OFF.has(S.i)) return;
      gg.append('g').selectAll('rect').data(v).join('rect').attr('x', p => xd(p.b)).attr('y', y0 + S.i * stp).attr('width', p => Math.max(2, xd(p.s) - xd(p.b))).attr('height', lh)
        .style('fill', p => p.r > 0 ? COL[S.i] : 'var(--color-panel)').style('stroke', COL[S.i]).style('stroke-width', '1px')
        .append('title').text(p => '묶음 ' + (S.i + 1) + '위 ' + S.nm + ' · ' + p.src + ' 신호 · 조건 ' + ymd(p.c) + ' → 매수 ' + md(p.b) + ' 시가 → 매도 ' + md(p.s) + ' 종가 · 코스피 ' + (p.r > 0 ? '+' : '') + p.r.toFixed(2) + '%'); });
    const lg = document.getElementById('all-legend');
    if (lg) { const ref = Array.from(lg.children).find(e => /^미수 반대매매\(막대\)/.test(e.textContent || '')) || null;
      SETS.forEach(S => { const bt = document.createElement('button'); bt.type = 'button'; bt.className = 'rv-lgbtn'; bt.setAttribute('aria-pressed', String(!OFF.has(S.i)));
        const sw = document.createElement('i'); sw.className = 'rv-sw'; sw.style.background = COL[S.i]; sw.style.width = '.9rem'; sw.style.height = '.3rem'; sw.style.borderRadius = '0';
        bt.append(sw, document.createTextNode('묶음 ' + (S.i + 1) + '위(' + POS[S.i] + ')')); bt.addEventListener('click', () => { OFF.has(S.i) ? OFF.delete(S.i) : OFF.add(S.i); redraw(); }); lg.insertBefore(bt, ref); }); }
    const host = document.getElementById('all-turnnote') || document.getElementById('all-labnote') || lg; let nt = document.getElementById('all-bundlenote');
    if (host && !nt) { nt = document.createElement('p'); nt.id = 'all-bundlenote'; nt.className = 'rv-note'; host.after(nt); }
    if (nt) { const st = S => { const v = vis[S.i] || [], w = v.filter(p => p.r > 0).length, sum = v.reduce((a, p) => a + p.r, 0); return (S.i + 1) + '위 ' + S.nm + ' ' + (v.length ? v.length + '번 중 수익 ' + w + '번 · 합계 ' + pc(sum) : '없음'); };
      const b = document.createElement('b'); b.textContent = '묶음 상위 3개';
      nt.replaceChildren(b, document.createTextNode(' 코스피 칸 ' + (gap ? '바로 아래 틈' : '맨 아래') + '의 가로 막대 세 줄(다른 신호 표시와 겹치지 않게 따로 둠' + (gap ? ' — 이 기간은 신호 표시가 칸 아래쪽까지 내려와 칸 밖 틈으로 옮김' : '') + '). 막대 = 매수일 시가부터 매도일 종가까지 들고 있던 기간, 채운 막대 = 수익 · 빈 막대 = 손실(코스피 지수 기준, 비용 없음). '
        + '보이는 기간: ' + SETS.map(st).join(' / ') + '. 합계는 거래별 수익률을 그대로 더한 값. 결과를 보고 고른 묶음이고 C 신호는 연구소 통과 기준에 못 미친다. 자료 ' + MADE + ' 까지(고정 · 자동 갱신 안 됨).')); }
  };
  const prev = window.rvLabSig;
  window.rvLabSig = (svg, xd, P0, mk) => { if (prev) { try { prev(svg, xd, P0, mk); } catch (e) { console.error(e); } } try { draw(svg, xd, P0); } catch (e) { console.error(e); } };
})();
