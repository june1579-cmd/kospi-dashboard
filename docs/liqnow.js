/* 반대매매 당일 예정치(2026-11-24 사용자 요청) — 한눈에 보기 그래프 '미수 반대매매' 칸에, 금투협 확정치가 아직 없는 날만 점선 막대(예정치)와 세로 선(80% 범위)을 그린다.
   확정치가 들어오면(다음 거래일 15시쯤 공개 → 그다음 자동 실행) 그 날은 원래 막대로 바뀌고 예정치는 사라진다. 이 파일과 page.html 의 liqnow.js 줄을 지우면 원래대로 돌아간다.
   자료: liq_now(저장소 nowcast/liq_nowcast.py → out/liq_nowcast.csv). 예정치는 추정이고 확정치 칸(liq)과 섞지 않는다. */
(() => {
  const OFF = window.__rvLiqNowOff || (window.__rvLiqNowOff = {on: true});
  const iso = v => String(v || '').slice(0, 10), num = v => (v === '' || v == null || isNaN(+v)) ? null : +v;
  const md = d => +d.slice(5, 7) + '/' + +d.slice(8, 10), eok = v => v >= 100 ? Math.round(v).toLocaleString('ko-KR') : v.toFixed(0);
  // 확정치가 아직 없는 날의 예정치(가장 최근 것부터)
  window.rvLiqNowRows = () => {
    let g, l; try { g = dash.data('liq_now'); l = dash.data('liq'); } catch (e) { return []; }
    if (!g || g.status !== 'ok' || !Array.isArray(g.data)) return [];
    const have = new Set((l && l.status === 'ok' && Array.isArray(l.data) ? l.data : []).filter(r => num(r.liq_eok) != null).map(r => iso(r.date)));
    return g.data.filter(r => num(r.liq_eok) == null && !have.has(iso(r.date)) && num(r.pred_eok) != null)
      .map(r => ({d: iso(r.date), p: num(r.pred_eok), lo: num(r.lo80), hi: num(r.hi80), lo9: num(r.lo90), hi9: num(r.hi90), asof: iso(r.kofia_asof)}));
  };
  function legend() {
    const lg = document.getElementById('all-legend'); if (!lg || lg.querySelector('[data-rv-liqnow]')) return;
    const ref = Array.from(lg.children).find(e => /^미수 반대매매\(막대\)/.test(e.textContent || ''));
    const bt = document.createElement('button'); bt.type = 'button'; bt.className = 'rv-lgbtn'; bt.dataset.rvLiqnow = '1'; bt.setAttribute('aria-pressed', String(OFF.on));
    const sw = document.createElement('i'); sw.className = 'rv-sw'; sw.style.background = 'transparent'; sw.style.border = '1.5px dashed ' + (dash.colors[0] || '#888'); sw.style.boxSizing = 'border-box';
    bt.append(sw, document.createTextNode('반대매매 예정치(점선 막대 · 선 = 80% 범위, 추정)'));
    bt.addEventListener('click', () => { OFF.on = !OFF.on; const box = document.getElementById('all-chart'); if (box && box._rvApi && box._rvApi.draw) box._rvApi.draw(); });
    if (ref && ref.nextSibling) lg.insertBefore(bt, ref.nextSibling); else lg.append(bt);
  }
  window.rvLiqNow = (svg, xd, P1, bw) => {
    try { legend(); } catch (e) {}
    if (!OFF.on) return;
    const box = document.getElementById('all-chart'), pl = (box && box._rvPlot) || null;
    const rows = window.rvLiqNowRows().filter(r => { const x = xd(r.d); return isFinite(x) && (!pl || (x >= pl[0] - 1 && x <= pl[1] + 1)); });
    if (!rows.length) return;
    const col = dash.colors[0] || '#888', y0 = P1.yL(0), top = P1.top + 2, yc = v => Math.max(top, Math.min(y0, P1.yL(v)));
    const g = svg.append('g').attr('class', 'rv-liqnow');
    rows.forEach(r => {
      const x = xd(r.d), w = Math.max(3, bw), y = yc(r.p);
      g.append('rect').attr('x', x - w / 2).attr('width', w).attr('y', y).attr('height', Math.max(1, y0 - y)).attr('rx', Math.min(3, w / 2))
        .style('fill', col).style('fill-opacity', 0.18).style('stroke', col).attr('stroke-width', 1.5).attr('stroke-dasharray', '3 2');
      if (r.lo != null && r.hi != null) {
        const a = yc(r.hi), b = yc(r.lo), cap = Math.max(4, Math.min(10, w));
        g.append('line').attr('x1', x).attr('x2', x).attr('y1', a).attr('y2', b).style('stroke', 'var(--color-fg)').attr('stroke-width', 1.2).attr('opacity', 0.7);
        [a, b].forEach(yy => g.append('line').attr('x1', x - cap / 2).attr('x2', x + cap / 2).attr('y1', yy).attr('y2', yy).style('stroke', 'var(--color-fg)').attr('stroke-width', 1.2).attr('opacity', 0.7));
        if (P1.yL(r.hi) < top) g.append('text').attr('class', 'rv-tick').attr('x', x).attr('y', top - 2).attr('text-anchor', 'middle').style('font-size', '9px').text('▲');
      }
      const lab = md(r.d) + ' 예정 ' + eok(r.p) + '억' + (r.lo != null ? ` (${eok(r.lo)}~${eok(r.hi)})` : '');
      const t = g.append('text').attr('class', 'rv-tick').attr('y', top + 10).style('font-size', '10px').style('font-weight', '600')
        .style('paint-order', 'stroke').style('stroke', 'var(--color-panel)').style('stroke-width', '3px').text(lab);
      const vbw = (svg.node().viewBox && svg.node().viewBox.baseVal.width) || 0, right = pl ? pl[1] : (vbw ? vbw - 48 : Infinity);   // 첫 그림에서는 _rvPlot 이 아직 없어 그림 폭으로
      t.attr('x', x + 6).attr('text-anchor', 'start'); let tl = 0; try { tl = t.node().getComputedTextLength(); } catch (e) {}
      if (x + 6 + tl > right) t.attr('x', x - 6).attr('text-anchor', 'end');   // 오른쪽 끝을 넘으면 막대 왼쪽에
    });
  };
})();
