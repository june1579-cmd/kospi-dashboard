// 10절 — 옵션 구조·갭 분해·연구소 기준 검증 (2026-11-23, claude.ai 미국·한국 대시보드에서 옮김).
// 자료: 저장소 deriv-research 가지의 deriv/us/out/dash.json (GitHub 워크플로 usk 가 계산). 이 파일은 그리기만 하고 숫자를 만들지 않는다.
(function () {
  const URL = 'https://raw.githubusercontent.com/june1579-cmd/kospi-dashboard/deriv-research/deriv/us/out/dash.json';
  const $ = id => document.getElementById(id);
  const no = v => v === null || v === undefined || v === '' || (typeof v === 'number' && isNaN(v));
  const f = (v, n = 2) => no(v) ? '—' : (+v).toLocaleString('ko-KR', {minimumFractionDigits: n, maximumFractionDigits: n});
  const sg = (v, n = 2) => no(v) ? '—' : (v > 0 ? '+' : '') + f(v, n);
  const cls = v => no(v) || +v === 0 ? '' : (+v > 0 ? ' style="color:var(--up)"' : ' style="color:var(--dn)"');
  const esc = s => String(s == null ? '' : s).replace(/[&<>]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;'}[c]));
  const table = (heads, rows) => '<div class="fo-tw"><table class="fo-t"><thead><tr>' + heads.map(h => `<th${h[1] ? ' class="fo-num"' : ''}>${esc(h[0])}</th>`).join('') + '</tr></thead><tbody>' +
    rows.map(r => '<tr>' + r.map((c, i) => `<td${heads[i][1] ? ' class="fo-num"' : ''}${c && c.s ? c.s : ''}>${c && c.h !== undefined ? c.h : esc(c)}</td>`).join('') + '</tr>').join('') + '</tbody></table></div>';

  function bars(el, ch, title, unit) {      // 행사가별 콜(빨강)·풋(파랑) 미결제 막대 + 현재가·벽·최대 고통 세로선
    el.textContent = ''; if (!ch || !ch.strikes || !ch.strikes.length || !window.d3) { el.textContent = '확인 불가'; return; }
    const W = Math.max(320, el.clientWidth || 640), H = 250, m = {t: 26, r: 10, b: 30, l: 46};
    const svg = d3.select(el).append('svg').attr('viewBox', `0 0 ${W} ${H}`).attr('width', '100%').attr('role', 'img').attr('aria-label', title);
    const x = d3.scaleBand().domain(ch.strikes).range([m.l, W - m.r]).padding(0.18), mx = d3.max(ch.call_oi.concat(ch.put_oi)) || 1;
    const y = d3.scaleLinear().domain([0, mx]).nice().range([H - m.b, m.t]), bw = x.bandwidth() / 2;
    svg.append('g').attr('transform', `translate(0,${H - m.b})`).call(d3.axisBottom(x).tickValues(ch.strikes.filter((_, i) => i % Math.ceil(ch.strikes.length / 10) === 0)).tickSize(3)).call(g => g.select('.domain').attr('stroke', 'var(--line)')).selectAll('text').attr('fill', 'var(--mut)').attr('font-size', 10.5);
    svg.append('g').attr('transform', `translate(${m.l},0)`).call(d3.axisLeft(y).ticks(4).tickFormat(d3.format('~s')).tickSize(3)).call(g => g.select('.domain').remove()).selectAll('text').attr('fill', 'var(--mut)').attr('font-size', 10.5);
    ch.strikes.forEach((k, i) => {
      svg.append('rect').attr('x', x(k)).attr('y', y(ch.call_oi[i] || 0)).attr('width', bw).attr('height', y(0) - y(ch.call_oi[i] || 0)).attr('fill', 'var(--up)').append('title').text(`행사가 ${k} · 콜 미결제 ${f(ch.call_oi[i], 0)}${unit}`);
      svg.append('rect').attr('x', x(k) + bw).attr('y', y(ch.put_oi[i] || 0)).attr('width', bw).attr('height', y(0) - y(ch.put_oi[i] || 0)).attr('fill', 'var(--dn)').append('title').text(`행사가 ${k} · 풋 미결제 ${f(ch.put_oi[i], 0)}${unit}`);
    });
    const step = ch.strikes.length > 1 ? (x(ch.strikes[1]) - x(ch.strikes[0])) / (ch.strikes[1] - ch.strikes[0]) : 0, px = v => x(ch.strikes[0]) + bw + (v - ch.strikes[0]) * step;
    [['현재가', ch.spot, 'var(--fg)', ''], ['최대 고통', ch.max_pain, 'var(--mut)', '4 3']].forEach(([nm, v, c, dash], j) => { if (no(v)) return; const xx = px(v); if (xx < m.l || xx > W - m.r) return;
      svg.append('line').attr('x1', xx).attr('x2', xx).attr('y1', m.t - 4).attr('y2', H - m.b).attr('stroke', c).attr('stroke-width', 1.2).attr('stroke-dasharray', dash);
      svg.append('text').attr('x', xx).attr('y', m.t - 8 - j * 0).attr('text-anchor', j ? 'start' : 'end').attr('dx', j ? 3 : -3).attr('font-size', 10.5).attr('fill', c).text(`${nm} ${f(v, v > 2000 ? 0 : 2)}`); });
    svg.append('text').attr('x', m.l).attr('y', 11).attr('font-size', 11).attr('fill', 'var(--mut)').text(`${title} — 빨강 콜 · 파랑 풋`);
  }

  function line(el, tail, title) {          // 한국 장 마감 뒤 미국 선물(1시간 봉)
    el.textContent = ''; if (!tail || tail.length < 2 || !window.d3) { el.textContent = '확인 불가'; return; }
    const W = Math.max(300, el.clientWidth || 600), H = 170, m = {t: 18, r: 10, b: 24, l: 50};
    const svg = d3.select(el).append('svg').attr('viewBox', `0 0 ${W} ${H}`).attr('width', '100%').attr('role', 'img').attr('aria-label', title);
    const x = d3.scaleLinear().domain([0, tail.length - 1]).range([m.l, W - m.r]), y = d3.scaleLinear().domain(d3.extent(tail, d => d[1])).nice().range([H - m.b, m.t]);
    svg.append('g').attr('transform', `translate(${m.l},0)`).call(d3.axisLeft(y).ticks(4).tickSize(3)).call(g => g.select('.domain').remove()).selectAll('text').attr('fill', 'var(--mut)').attr('font-size', 10.5);
    const ticks = tail.map((d, i) => i).filter(i => tail[i][0].endsWith(' 09'));
    svg.append('g').attr('transform', `translate(0,${H - m.b})`).call(d3.axisBottom(x).tickValues(ticks).tickFormat(i => tail[i][0].slice(0, 5).replace('-', '/')).tickSize(3)).call(g => g.select('.domain').attr('stroke', 'var(--line)')).selectAll('text').attr('fill', 'var(--mut)').attr('font-size', 10.5);
    svg.append('path').attr('d', d3.line().x((d, i) => x(i)).y(d => y(d[1]))(tail)).attr('fill', 'none').attr('stroke', 'var(--fg)').attr('stroke-width', 1.4);
    svg.append('text').attr('x', m.l).attr('y', 11).attr('font-size', 11).attr('fill', 'var(--mut)').text(title + ' — 한국 시각, 1시간 봉');
  }

  function draw(D) {
    const fail = Object.entries(D.collect || {}).filter(([, v]) => v === false).map(([k]) => k);
    $('u-meta').innerHTML = `계산 시각 <b>${esc(D.at_kst)}</b> KST · 미국 자료 ${esc(D.us_date)} · 한국 자료 ${esc(D.kr_date)}` + (fail.length ? ` · <span style="color:var(--up)">확인 불가: ${esc(fail.join(', '))}</span>` : '');
    // 가. 옵션 구조
    const U = D.us_chain || {}, K = D.kr_chain || {}, rows = [];
    if (!no(K.spot)) rows.push(['코스피200 (' + (K.exp || '') + ' 만기)', f(K.spot), f(K.call_wall, 1), f(K.put_wall, 1), f(K.max_pain, 1), '—', '—', f(K.pcr_oi, 2), K.date || '']);
    ['SPY', 'QQQ'].forEach(s => { const v = U[s]; if (!v || no(v.spot)) { rows.push([s, '확인 불가', '', '', '', '', '', '', '']); return; }
      rows.push([s + ' (만기 ' + v.expiries + '개 합산)', f(v.spot), f(v.call_wall, 0), f(v.put_wall, 0), f(v.max_pain, 0) + ' (' + (v.max_pain_exp || '') + ')', f(v.zero_gamma), {h: sg(v.gex_total, 2), s: cls(v.gex_total)}, f(v.pcr_oi, 2), v.ts || '']); });
    $('u-struct').innerHTML = table([['대상'], ['현재가', 1], ['콜벽', 1], ['풋벽', 1], ['최대 고통', 1], ['감마 0 지점(추정)', 1], ['감마 합계(추정, 십억 달러/1%)', 1], ['풋÷콜 미결제', 1], ['기준']], rows);
    bars($('u-kr'), K, '코스피200 옵션 행사가별 미결제약정', '계약'); bars($('u-spy'), U.SPY, 'SPY 옵션 행사가별 미결제약정', '계약'); bars($('u-qqq'), U.QQQ, 'QQQ 옵션 행사가별 미결제약정', '계약');
    // 나. 한국 장 마감 뒤 미국 선물
    const S = D.since_close || {};
    $('u-since').innerHTML = table([['선물'], ['한국 장 마감 때(기준)', 1], ['마지막 값', 1], ['그 사이 등락 %', 1]], [['S&P500 선물(ES)', S.es], ['나스닥100 선물(NQ)', S.nq]].map(([n, v]) => !v ? [n, '확인 불가', '', ''] :
      [n, f(v.ref) + ' (' + v.ref_kst + ')', f(v.last) + ' (' + v.last_kst + ')', {h: sg(v['chg%']) + '%', s: cls(v['chg%'])}]));
    line($('u-es'), (S.es || {}).tail, 'S&P500 선물'); line($('u-nq'), (S.nq || {}).tail, '나스닥100 선물');
    // 다. 갭/장중 분해
    const DC = D.decomp || [], si = $('u-ind'), sp = $('u-per');
    const uniq = k => [...new Set(DC.map(r => r[k]))];
    if (!si.options.length) { uniq('미국 지표').forEach(v => si.add(new Option(v, v))); uniq('기간').forEach(v => sp.add(new Option(v, v))); sp.value = uniq('기간').find(v => v.startsWith('전체')) || sp.value; }
    const dd = () => { const r = DC.filter(q => q['미국 지표'] === si.value && q['기간'] === sp.value);
      $('u-decomp').innerHTML = r.length ? table([['미국 지표의 그날 등락'], ['날 수', 1], ['한국 시가 갭 평균 %', 1], ['시가 뒤 장중 평균 %', 1], ['장중에 오른 비율 %', 1], ['갭 상관', 1], ['장중 상관', 1]],
        r.map(q => [q['구분'], f(q['날 수'], 0), {h: sg(q['갭 평균%'], 3), s: cls(q['갭 평균%'])}, {h: sg(q['장중 평균%'], 3), s: cls(q['장중 평균%'])}, f(q['장중 상승%'], 1), f(q['갭 상관'], 3), f(q['장중 상관'], 3)])) : '확인 불가'; };
    si.onchange = sp.onchange = dd; dd();
    // 라. 연구소 기준 검증
    const V = D.verdict || {};
    $('u-verdict').innerHTML = `미국 지표로 만든 후보 <b>${f(V.candidates, 0)}</b>개를 연구소 기준(앞 ${esc(V.p1)} · 뒤 ${esc(V.p2)})으로 판정: 앞 구간 선별 ${f(V.sel_fwd, 0)} · 뒤 구간 선별 ${f(V.sel_rev, 0)} · 양방향 통과 ${f(V.both_pass, 0)} · 통과 기준(전체 35거래·85%) 통과 <b>${f(V.goal_pass, 0)}</b> (라운드 ${f(V.round, 0)}, 누적 시험 ${f(V.trials_total, 0)}번).`;
    const vt = L => L && L.length ? table([['후보'], ['묶음'], ['앞 거래', 1], ['앞 적중 %', 1], ['앞 바탕 %', 1], ['뒤 거래', 1], ['뒤 적중 %', 1], ['뒤 바탕 %', 1], ['반증']],
      L.slice(0, 8).map(q => [q.desc, q.family, f(q.n1, 0), f(q.h1, 1), f(q.b1, 1), f(q.n2, 0), f(q.h2, 1), f(q.b2, 1), q.rt === true ? '버팀' : q.rt === false ? '못 버팀' : '—'])) : '<p class="fo-note">해당 없음</p>';
    $('u-closest').innerHTML = vt(V.closest); $('u-selected').innerHTML = vt(V.selected);
  }

  fetch(URL + '?v=' + Date.now(), {cache: 'no-store'}).then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); }).then(draw)
    .catch(e => { const m = $('u-meta'); if (m) m.innerHTML = '<span style="color:var(--up)">자료를 읽지 못했습니다(확인 불가): ' + esc(String(e)) + '</span>'; });
})();
