// 11절 — 미국 옵션 아침 추정(07:40) · 공개 시각 측정 (2026-11-24).
// 자료: main 의 uswalls/latest.json (워크플로 us-walls, 화~토 06:47 KST 계산) · pub-watch 가지의 summary.json (워크플로 pub-watch).
// 이 파일은 그리기만 하고 숫자를 만들지 않는다. 받지 못한 값은 '확인 불가'.
(function () {
  const RAW = 'https://raw.githubusercontent.com/june1579-cmd/kospi-dashboard/';
  const $ = id => document.getElementById(id);
  const no = v => v === null || v === undefined || v === '' || (typeof v === 'number' && isNaN(v));
  const f = (v, n = 2) => no(v) ? '—' : (+v).toLocaleString('ko-KR', {minimumFractionDigits: n, maximumFractionDigits: n});
  const k = v => no(v) ? '—' : (Math.abs(v - Math.round(v)) < 1e-6 ? String(Math.round(v)) : (+v).toFixed(1));
  const sg = (v, n = 2) => no(v) ? '—' : (v > 0 ? '+' : '') + f(v, n);
  const cls = v => no(v) || +v === 0 ? '' : (+v > 0 ? ' style="color:var(--up)"' : ' style="color:var(--dn)"');
  const esc = s => String(s == null ? '' : s).replace(/[&<>]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;'}[c]));
  const table = (heads, rows) => '<div class="fo-tw"><table class="fo-t"><thead><tr>' + heads.map(h => `<th${h[1] ? ' class="fo-num"' : ''}>${esc(h[0])}</th>`).join('') + '</tr></thead><tbody>' +
    rows.map(r => '<tr>' + r.map((c, i) => `<td${heads[i][1] ? ' class="fo-num"' : ''}${c && c.s ? c.s : ''}>${c && c.h !== undefined ? c.h : esc(c)}</td>`).join('') + '</tr>').join('') + '</tbody></table></div>';
  const chg = (a, b) => { if (no(a) || no(b)) return ''; const d = a - b; return Math.abs(d) < 1e-6 ? ' (그대로)' : ` (${d > 0 ? '▲' : '▼'}${k(Math.abs(d))})`; };
  const acc = v => no(v) ? '—' : (Math.abs(v) <= 1 ? '맞음' : sg(v, 0) + ' 차이');

  function drawWalls(J) {
    const tag = J.test ? ' · <b>시험 실행</b>' : '';
    const stx = {seed: '시작 기록(첫 정규 계산 전)', ok: '정상', partial: '<span style="color:var(--up)">일부 실패</span>', fail: '<span style="color:var(--up)">실패</span>', holiday: '새 미국 장 거래 없음(휴장)'}[J.status] || esc(J.status);
    $('w-meta').innerHTML = `계산 시각 <b>${esc(J.at_kst)}</b> KST · 상태 ${stx}${tag}` + ((J.errors || []).length ? ` · <span style="color:var(--up)">${esc(J.errors.join(' / '))}</span>` : '');
    const S = J.syms || {}, rows = [];
    ['SPY', 'QQQ'].forEach(s => {
      const v = S[s];
      if (!v) { rows.push([s, '확인 불가', '', '', '', '', '', '', '', '', '', '']); return; }
      if (v.status === 'holiday') { const l = v.last || {}; rows.push([s, (v.session || '') + ' (새 거래 없음)', f(v.spot), k(l.cw_est), '', k(l.pw_est), '', '', '', '', '', '']); return; }
      const w = v.row || {};
      rows.push([s, w.session, {h: f(w.spot) + ' <span' + cls(w.chg_pct) + '>(' + sg(w.chg_pct) + '%)</span>'}, {h: '<b>' + k(w.cw_est) + '</b>' + chg(w.cw_est, w.cw_off)}, k(w.cw_off),
        {h: '<b>' + k(w.pw_est) + '</b>' + chg(w.pw_est, w.pw_off)}, k(w.pw_off), k(w.cwoi_est) + ' / ' + k(w.pwoi_est), f(w.pcr_vol), f(w.pcr_oi), no(w.iv_atm) ? '—' : f(w.iv_atm * 100, 1) + '%',
        [w.new_c, w.new_p].filter(Boolean).join(' ') || '—']);
    });
    $('w-now').innerHTML = table([['대상'], ['직전 장'], ['현재가(등락)', 1], ['콜벽 추정', 1], ['전날 확정 콜벽', 1], ['풋벽 추정', 1], ['전날 확정 풋벽', 1], ['물량 최대 콜/풋', 1], ['풋÷콜 거래', 1], ['풋÷콜 미결제', 1], ['단기 내재변동성', 1], ['새로 몰린 곳']], rows);
    const tw = [];
    ['SPY', 'QQQ'].forEach(s => { const t = (S[s] || {}).trend; if (t) tw.push(`<b>${s}</b> 콜벽 ${esc(t.cw_dir)} · 풋벽 ${esc(t.pw_dir)} · ${esc(t.width)}${t.pcr ? ' · ' + esc(t.pcr) : ''} <span class="fo-mut">(콜벽 ${esc(t.cw_seq)} / 풋벽 ${esc(t.pw_seq)})</span>`); });
    $('w-trend').innerHTML = tw.length ? tw.join('<br>') : '흐름: 기록 쌓는 중';
    const H = J.hist || {}, hr = [];
    ['SPY', 'QQQ'].forEach(s => (H[s] || []).slice(-10).reverse().forEach(r => hr.push([s, r.session, f(r.spot), {h: sg(r.chg_pct) + '%', s: cls(r.chg_pct)}, k(r.cw_est), k(r.pw_est), k(r.cw_off), k(r.pw_off), f(r.pcr_oi), acc(r.acc_cw) + ' / ' + acc(r.acc_pw),
      (no(r.kc_used) ? '—' : f(r.kc_used)) + ' / ' + (no(r.kp_used) ? '—' : f(r.kp_used)), r.warn || ''])));
    $('w-hist').innerHTML = hr.length ? table([['대상'], ['장'], ['현재가', 1], ['등락', 1], ['콜벽 추정', 1], ['풋벽 추정', 1], ['전날 확정 콜벽', 1], ['전날 확정 풋벽', 1], ['풋÷콜 미결제', 1], ['어제 추정 정확도 콜/풋'], ['거래 반영 비율 콜/풋', 1], ['비고']], hr) : '확인 불가';
  }

  function drawPub(P) {
    const S = P.sources || {}, rows = Object.keys(S).map(key => { const v = S[key];
      return [v.name, v.last || '—', v.checked || '—', f(v.n, 0), v.noisy ? '읽을 때마다 바뀜(측정 불가)' : (v.median_kst || '기록 쌓는 중'), v.range_kst || '—', v.err ? {h: '<span style="color:var(--up)">읽기 실패</span>'} : '정상']; });
    $('w-pub').innerHTML = table([['출처'], ['지금 보이는 기준값'], ['마지막 확인(KST)'], ['바뀐 횟수', 1], ['보통 바뀌는 시각(KST)', 1], ['범위', 1], ['상태']], rows);
    $('w-pubmeta').innerHTML = `측정 시작 ${esc(P.started || '—')} · 마지막 정리 ${esc(P.updated || '—')}` + (P.done ? ` · <b>측정 끝(${esc(P.done)})</b>` : ' · 측정 중(5거래일치가 모이면 카카오톡으로 요약하고 멈춤)');
  }

  const get = u => fetch(u + '?v=' + Date.now(), {cache: 'no-store'}).then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); });
  get(RAW + 'main/uswalls/latest.json').then(drawWalls).catch(e => { const m = $('w-meta'); if (m) m.innerHTML = '<span style="color:var(--up)">자료를 읽지 못했습니다(확인 불가): ' + esc(String(e)) + '</span>'; });
  get(RAW + 'pub-watch/summary.json').then(drawPub).catch(() => { const m = $('w-pubmeta'); if (m) m.textContent = '측정 기록이 아직 없습니다(첫 정리는 시작 뒤 한 시간 안).'; });
})();
