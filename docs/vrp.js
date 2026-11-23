/* VIX − 실현 변동성 상위 20% 신호 표시(2026-11-24 사용자 요청) — 한눈에 보기 그래프 코스피 칸에 파란 세로선. 이 파일과 page.html 의 vrp.js 줄을 지우면 원래대로 돌아간다.
   자료: vrp_sig(연구소 가지 deriv/lab/signals/vrp_signals.csv, 만든 코드 deriv/us/vrp_export.py) — 조건일 다음 날 시가 매수 · 20거래일 보유, 수익률은 코스피 지수 기준 */
(() => {
  const COL = '#1e88e5';
  const OFF = window.__rvVrpOff || (window.__rvVrpOff = new Set());
  const iso = v => String(v || '').slice(0, 10), md = d => +d.slice(5, 7) + '/' + +d.slice(8, 10), ymd = d => d.slice(2, 4) + '년 ' + md(d), pc = v => (v > 0 ? '+' : '') + v.toFixed(1) + '%';
  let memo = null;
  const rows = () => {
    let g; try { g = dash.data('vrp_sig'); } catch (e) { return null; }
    if (!g || g.status !== 'ok' || !Array.isArray(g.data) || !g.data.length) return null;
    if (memo && memo.src === g.data) return memo.t;
    const t = g.data.map(r => { const v = r.ret_pct === '' || r.ret_pct == null ? NaN : +r.ret_pct; return {c: iso(r.cond), b: iso(r.buy), s: iso(r.sell), st: String(r.status || ''), r: isFinite(v) ? v : null}; }).filter(p => p.c.length === 10);
    memo = {src: g.data, t}; return t;
  };
  const redraw = () => { const box = document.getElementById('all-chart'); if (box && box._rvApi && box._rvApi.draw) box._rvApi.draw(); };
  const desc = p => ymd(p.c) + ' 조건 → ' + md(p.b) + ' 매수 → ' + md(p.s) + ' 매도' + (p.r != null ? '(코스피 ' + (p.r > 0 ? '+' : '') + p.r.toFixed(2) + '%)' : '(' + (p.st || '진행 중') + ')');
  const draw = (svg, xd, P0) => {
    const T = rows(); if (!T) return;
    const xa = xd('1900-01-01'), xb = xd('2999-12-31'); if (!isFinite(xa) || !isFinite(xb)) return;
    const vis = T.filter(p => { const a = xd(p.c); return isFinite(a) && a > xa + 0.01 && a < xb - 0.01; });
    if (!OFF.has('v')) svg.append('g').attr('class', 'rv-vrp').selectAll('line').data(vis).join('line').attr('x1', p => xd(p.c)).attr('x2', p => xd(p.c)).attr('y1', P0.top).attr('y2', P0.bot)
      .style('stroke', COL).style('stroke-width', p => p.r == null ? '2.5px' : '1.5px').style('stroke-dasharray', p => p.r != null && p.r <= 0 ? '7 4' : null).style('opacity', 0.6)
      .append('title').text(p => 'VIX − 실현 변동성 상위 20% · ' + desc(p));
    const lg = document.getElementById('all-legend');
    if (lg) { const ref = Array.from(lg.children).find(e => /^미수 반대매매\(막대\)/.test(e.textContent || '')) || null;
      const bt = document.createElement('button'); bt.type = 'button'; bt.className = 'rv-lgbtn'; bt.setAttribute('aria-pressed', String(!OFF.has('v')));
      const sw = document.createElement('i'); sw.className = 'rv-sw'; sw.style.background = COL; sw.style.width = '.15rem'; sw.style.height = '.8rem'; sw.style.borderRadius = '0';
      bt.append(sw, document.createTextNode('VIX−실현 변동성 상위 20%(세로선)')); bt.addEventListener('click', () => { OFF.has('v') ? OFF.delete('v') : OFF.add('v'); redraw(); }); lg.insertBefore(bt, ref); }
    const host = document.getElementById('all-turnnote') || document.getElementById('all-labnote') || lg; let nt = document.getElementById('all-vrpnote');
    if (host && !nt) { nt = document.createElement('p'); nt.id = 'all-vrpnote'; nt.className = 'rv-note'; host.after(nt); }
    if (nt) { const fin = a => a.filter(p => p.r != null), sum = a => a.reduce((x, p) => x + p.r, 0), win = a => a.filter(p => p.r > 0).length, v = fin(vis), all = fin(T), lastP = T[T.length - 1];
      const b = document.createElement('b'); b.textContent = 'VIX − 실현 변동성 상위 20%'; b.style.color = COL;
      nt.replaceChildren(b, document.createTextNode(' 파란 세로선 = 조건이 켜진 날(다음 날 시가 매수 · 20거래일 보유 기준, 보유 중에 다시 켜진 날은 긋지 않음). 실선 = 20일 뒤 수익, 파선 = 손실, 굵은 선 = 아직 진행 중. '
        + '보이는 기간 ' + vis.length + '번' + (v.length ? '(끝난 ' + v.length + '번 중 수익 ' + win(v) + '번 · 합계 ' + pc(sum(v)) + ', 코스피 지수 기준)' : '') + ' · 가장 최근 ' + desc(lastP)
        + '. 연구소 통과 기준에 못 미친 신호라 참고용(2010년부터 ' + all.length + '번 중 수익 ' + win(all) + '번).')); }
  };
  const prev = window.rvLabSig;
  window.rvLabSig = (svg, xd, P0, mk) => { if (prev) { try { prev(svg, xd, P0, mk); } catch (e) { console.error(e); } } try { draw(svg, xd, P0); } catch (e) { console.error(e); } };
})();
