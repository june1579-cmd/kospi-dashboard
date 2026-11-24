// 맨 위 「자료 상태」 — 갱신이 늦었거나 수집에 문제가 있는 자료를 먼저 보여 주고, 쓰는 자료마다 기준일을 표로 보여 준다(2026-11-24).
// 읽는 것: data/tables.json(웹판 계산 결과: 자료별 기준일·확인 못 한 값·계산 시각), main 의 fo/data/status.json(미국 수집 상태)·state/watchdog.json(GitHub 감시가 연 문제)
//          ·uswalls/latest.json(11절)·pkg/holidays_kr.json(한국 휴장일), deriv-research 의 deriv/us/out/dash.json(10절).
// 숫자를 만들지 않는다. '늦음'은 지금 시각과 각 자료의 정해진 갱신 시각(아래 LAG)을 견주어 판정한다. 노랑은 쓰지 않는다(문제 = 빨강, 정상 = 초록).
(function () {
  const RAW = 'https://raw.githubusercontent.com/june1579-cmd/kospi-dashboard/';
  const box = document.getElementById('fo-health'); if (!box) return;
  const esc = s => String(s == null ? '' : s).replace(/[&<>]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;'}[c]));
  const get = (u, json = true) => fetch(u + (u.includes('?') ? '&' : '?') + 'v=' + Date.now(), {cache: 'no-store'}).then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); return json ? r.json() : r.text(); });
  const opt = p => p.then(v => v, () => null);
  // 미국 증시 휴장일(정규장 전체 휴장, NYSE 공지 기준) — 2026·2027
  const US_HOL = new Set(['2026-01-01', '2026-01-19', '2026-02-16', '2026-04-03', '2026-05-25', '2026-06-19', '2026-07-03', '2026-09-07', '2026-11-26', '2026-12-25',
    '2027-01-01', '2027-01-18', '2027-02-15', '2027-03-26', '2027-05-31', '2027-06-18', '2027-07-05', '2027-09-06', '2027-11-25', '2027-12-24']);
  // 시각 도구: 한국·뉴욕 '벽시계' 날짜·시각을 문자열로(브라우저 시간대와 무관)
  const parts = (d, tz) => { const p = {}; new Intl.DateTimeFormat('en-CA', {timeZone: tz, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false, weekday: 'short'}).formatToParts(d).forEach(x => p[x.type] = x.value); p.hour = p.hour === '24' ? '00' : p.hour; return p; };
  const ymd = p => `${p.year}-${p.month}-${p.day}`;
  const addDays = (s, n) => { const d = new Date(s + 'T12:00:00Z'); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10); };
  const wd = s => new Date(s + 'T12:00:00Z').getUTCDay();          // 0 = 일요일
  const md = s => s ? s.slice(5).replace('-', '/') : '—';
  const kstOf = (dateStr, hh, mm) => Date.parse(`${dateStr}T${String(hh).padStart(2, '0')}:${String(mm).padStart(2, '0')}:00+09:00`);
  const nyOffset = s => { const m = +s.slice(5, 7), d = +s.slice(8); return (m > 3 && m < 11) || (m === 3 && d >= 8) || (m === 11 && d < 1) ? -4 : -5; };   // 대략의 서머타임(3월 둘째 주~11월 첫 주)
  const nyCloseKst = s => Date.parse(`${s}T16:00:00${nyOffset(s) === -4 ? '-04:00' : '-05:00'}`);

  // 지금 시점에 '들어와 있어야 할' 마지막 거래일: 그 거래일 마감 + lag(시간)이 지금보다 이른 가장 늦은 거래일
  function expectUS(now, lagH) {
    let s = ymd(parts(new Date(now), 'America/New_York'));
    for (let i = 0; i < 12; i++, s = addDays(s, -1)) { const w = wd(s); if (w === 0 || w === 6 || US_HOL.has(s)) continue; if (nyCloseKst(s) + lagH * 3600e3 <= now) return s; }
    return null;
  }
  function expectKR(now, lagH, hol) {
    let s = ymd(parts(new Date(now), 'Asia/Seoul'));
    for (let i = 0; i < 15; i++, s = addDays(s, -1)) { const w = wd(s); if (w === 0 || w === 6 || hol.has(s)) continue; if (kstOf(s, 15, 30) + lagH * 3600e3 <= now) return s; }
    return null;
  }
  // 자료 종류별 '정해진 갱신'까지 여유(거래일 마감 뒤 몇 시간 안에 웹판에 들어와 있어야 하나)
  // 판정 기준 시각은 '마지막으로 돌았어야 할 웹판 계산 시각'이다(웹판은 그 시각에 받은 자료까지만 담으므로).
  const LAG = {
    us_y: [0.5, '미국 장 마감 뒤 06:37 계산(야후)'], us_c: [13, 'Cboe 날짜별 파일 — 19:17 계산까지는 들어와야 함'],
    kr_idx: [1.5, '한국 장 마감 뒤 19:17 계산'], kr_krx: [3.5, '19:17 KRX 이어받기 뒤'], kr_dash: [1, '코스피 대시보드 15:43 갱신 직후 계산'], kr_night: [18.5, '야간 06:00 마감 → 코스피 대시보드 08:23 갱신 직후 계산']
  };
  function kind(r) {
    const n = r['지표'] || '', src = r['출처'] || '';
    if (/CFTC/.test(n)) return 'cftc';
    if (/Cboe/.test(n)) return 'us_c';
    if (/VIX|S&P500|ES·NQ/.test(n)) return 'us_y';
    if (/야간선물/.test(n)) return 'kr_night';
    if (/코스피200 지수/.test(n)) return 'kr_idx';
    if (/KRX 정보데이터시스템/.test(src)) return 'kr_krx';
    if (/코스피 대시보드 수집/.test(src)) return 'kr_dash';
    return null;
  }
  // 웹판 계산(fo-dashboard) 예정 시각: 화~토 06:37·10:47, 월~금 19:17 (KST, 코스피 대시보드 갱신 직후 계산은 덤) — 90분 넘게 지났는데 그 뒤 계산이 없으면 늦음
  function lastBuildSlot(now) {
    let s = ymd(parts(new Date(now), 'Asia/Seoul')), best = null;
    for (let i = 0; i < 5; i++, s = addDays(s, -1)) {
      const w = wd(s), slots = [];
      if (w >= 2 && w <= 6) slots.push([6, 37], [10, 47]);
      if (w >= 1 && w <= 5) slots.push([19, 17]);
      slots.forEach(([h, m]) => { const t = kstOf(s, h, m); if (t + 90 * 60e3 <= now && (best === null || t > best)) best = t; });
      if (best !== null) return best;
    }
    return best;
  }
  const parseKst = s => s ? Date.parse(s.replace(' KST', '').replace(' ', 'T') + ':00+09:00') : NaN;
  const fmtKst = t => { const p = parts(new Date(t), 'Asia/Seoul'); return `${p.month}/${p.day} ${p.hour}:${p.minute}`; };

  function draw(T, ST, WD, DASH, UW, HOL, OC) {
    const now = Date.now(), probs = [], rows = [];
    const hol = new Set((HOL && HOL.holidays) || []);
    const meta = ((T && T.meta) || [])[0] || {};
    // 1) 웹판 계산 자체
    const built = parseKst(meta.built), slot = lastBuildSlot(now);
    const bLate = !isNaN(built) && slot !== null && built < slot;
    rows.push(['웹판 계산(fo-dashboard)', meta.built ? meta.built.replace(' KST', '') : '확인 불가', slot ? fmtKst(slot) + ' 계산 뒤' : '—', bLate ? 'late' : (isNaN(built) ? 'bad' : 'ok'), '화~토 06:37·10:47 · 월~금 19:17']);
    if (isNaN(built)) probs.push('웹판 계산 결과(data/tables.json)를 읽지 못했습니다');
    else if (bLate) probs.push(`웹판 계산이 늦어짐 — 마지막 계산 ${fmtKst(built)}, ${fmtKst(slot)} 예정 계산이 아직 반영되지 않음`);
    const ref = isNaN(built) ? now : (bLate ? built : (slot === null ? now : Math.max(slot, Math.min(built, now))));   // 계산이 늦으면 실제 마지막 계산 시각 기준으로 자료를 본다
    // 2) 자료별 기준일(웹판 계산이 쓴 값)
    ((T && T.sources) || []).forEach(r => {
      const k = kind(r), last = r['기준'] || '';
      let exp = null, st = 'ok', note = r['갱신'] || '';
      if (k === 'cftc') {
        const age = last ? (now - Date.parse(last + 'T12:00:00Z')) / 86400e3 : 99;
        st = age > 11 ? 'late' : 'ok'; exp = '매주(화요일 기준, 금요일 공표)';
        if (st === 'late') probs.push(`${r['지표']} 늦어짐 — 기준일 ${md(last)}(${Math.floor(age)}일 전)`);
      } else if (k && LAG[k]) {
        exp = k.startsWith('us') ? expectUS(ref, LAG[k][0]) : expectKR(ref, LAG[k][0], hol);
        if (!last) { st = 'bad'; probs.push(`${r['지표']} — 기준일 확인 불가`); }
        else if (exp && last < exp) { st = 'late'; probs.push(`${r['지표']} 늦어짐 — 기준일 ${md(last)}, ${md(exp)} 자료가 와 있어야 함(${LAG[k][1]})`); }
      }
      rows.push([r['지표'], last || '확인 불가', exp || '—', st, note]);
    });
    // 3) 10절 — 미국 옵션 체인·연동 계산
    if (DASH) {
      const sp = ((DASH.us_chain || {}).SPY || {}), ts = sp.ts || '', d = ts.slice(0, 10), exp = expectUS(now, 3.5);
      // 스냅숏 시각(뉴욕)이 그 거래일 장 마감 뒤면 그날 장까지 반영
      const late = !d || (exp && d < exp), empty = !late && (sp.call_wall === null || sp.call_wall === undefined);
      rows.push(['미국 옵션 체인(SPY·QQQ, 10절)', ts || '확인 불가', exp || '—', late ? 'late' : (empty ? 'bad' : 'ok'), '야후 — usk 07:17']);
      if (late) probs.push(`미국 옵션 체인(10절) 늦어짐 — 스냅숏 ${ts || '없음'}, ${md(exp)} 장 마감 뒤 자료가 와 있어야 함`);
      else if (empty) probs.push(`미국 옵션 체인(10절) 미결제가 비어 콜벽·풋벽을 못 구함 — 스냅숏 ${ts}(다음 usk 계산 때 다시 계산)`);
      const at = parseKst(DASH.at_kst), age = (now - at) / 3600e3;
      rows.push(['미국·한국 연동 계산(10절)', DASH.at_kst || '확인 불가', '40시간 안', age > 40 || isNaN(at) ? 'late' : 'ok', 'usk 화~토 07:17 · 월~금 19:27']);
      if (age > 40) probs.push(`미국·한국 연동 계산(10절) 멈춤 — 마지막 ${DASH.at_kst}(${Math.round(age)}시간 전)`);
      const fail = Object.entries(DASH.collect || {}).filter(([kk, v]) => v === false && !(kk === 'option_chain' && !late)).map(([kk]) => kk);
      if (fail.length) probs.push(`10절 수집 일부 실패: ${fail.join(', ')}`);
    } else { rows.push(['미국·한국 연동 계산(10절)', '확인 불가', '—', 'bad', '']); probs.push('10절 자료(dash.json)를 읽지 못했습니다'); }
    // 4) 11절 — 미국 옵션 아침 추정
    if (UW) {
      const kp = parts(new Date(now), 'Asia/Seoul'), today = ymd(kp), w = wd(today), hm = +kp.hour * 60 + +kp.minute;
      const due = w >= 2 && w <= 6 && hm >= 8 * 60 + 40, atD = String(UW.at_kst || '').slice(0, 10);
      const sess = Object.values(UW.syms || {}).map(v => v.session).filter(Boolean).sort().pop() || '';
      let st = 'ok';
      if (UW.status === 'fail' || UW.status === 'partial') { st = 'bad'; probs.push(`미국 옵션 아침 추정(11절) ${UW.status === 'fail' ? '실패' : '일부 실패'}: ${(UW.errors || []).join(' / ').slice(0, 120)}`); }
      else if (due && atD < today && UW.status !== 'seed') { st = 'late'; probs.push(`미국 옵션 아침 추정(11절) 늦어짐 — 마지막 계산 ${UW.at_kst}, 오늘 07:40 계산이 없음`); }
      rows.push(['미국 옵션 아침 추정(11절)', (sess ? sess + ' 장' : '—') + ' · 계산 ' + (UW.at_kst || '?'), '화~토 07:40', st, UW.status === 'seed' ? '시작 기록(첫 정규 계산 전)' : (UW.status === 'holiday' ? '미국 휴장 — 새 거래 없음' : 'us-walls')]);
    }
    // 4-2) 11절 — 공식 확정(OCC)
    if (OC) {
      const kp = parts(new Date(now), 'Asia/Seoul'), today = ymd(kp), w = wd(today), hm = +kp.hour * 60 + +kp.minute;
      const atD = String(OC.at_kst || '').slice(0, 10); let st = 'ok';
      if (atD === today && ['fail', 'partial', 'timeout'].includes(OC.status) && !OC.test) { st = 'bad'; probs.push(`미국 옵션 공식 확정(OCC) ${OC.status === 'timeout' ? 'OCC 반영 안 됨' : '실패'}: ${(OC.note || (OC.errors || []).join(' / ')).slice(0, 120)}`); }
      else if (w >= 2 && w <= 6 && hm >= 16 * 60 + 30 && atD < today) { st = 'late'; probs.push(`미국 옵션 공식 확정(OCC) 늦어짐 — 마지막 ${OC.at_kst}, 오늘 계산 없음`); }
      rows.push(['미국 옵션 공식 확정(OCC, 11절)', (OC.session ? OC.session + ' 장' : '—') + ' · 계산 ' + (OC.at_kst || '?'), '화~토 OCC 반영 뒤(오전 11시 무렵)', st, OC.found_kst ? 'OCC 반영 확인 ' + OC.found_kst.slice(11) : 'occ-walls']);
    }
    // 5) 미국 수집 상태 파일·GitHub 감시가 연 문제
    Object.entries(ST || {}).forEach(([kk, v]) => { if (v && v.ok === false) probs.push(`미국 수집 실패: ${kk} — ${String(v.note || '').slice(0, 100)}`); });
    const KEYS = ['run:fo', 'stale:fo', 'src:fo', 'run:usk', 'stale:usk', 'run:uswalls', 'stale:uswalls', 'src:uswalls', 'run:occwalls', 'stale:occwalls', 'src:occwalls', 'run:pubwatch', 'run:collect'];
    Object.entries(WD || {}).forEach(([kk, v]) => { if (KEYS.includes(kk) && v && v.open) probs.push(`GitHub 감시: ${v.text || v.label}`); });
    const unk = ((T && T.unknown) || []).length;

    // 그리기
    const keyDates = () => {
      const g = n => ((T && T.sources) || []).find(r => (r['지표'] || '').includes(n));
      const a = g('S&P500'), c = g('CFTC'), kf = g('코스피200 선물'), ki = g('코스피200 지수');
      return [`미국 ${md(a && a['기준'])}`, `한국 지수 ${md(ki && ki['기준'])}`, `KRX 선물·옵션 ${md(kf && kf['기준'])}`, `CFTC ${md(c && c['기준'])}`].join(' · ');
    };
    const uniq = [...new Set(probs)];
    const head = uniq.length ? `<b class="fo-up">자료 문제 ${uniq.length}건</b>` : '<b class="fo-okc">모든 자료가 제때 갱신됨</b>';
    const lab = {ok: '<span class="fo-okc">정상</span>', late: '<span class="fo-up"><b>늦음</b></span>', bad: '<span class="fo-up"><b>확인 불가</b></span>'};
    box.innerHTML = `<div class="fo-hl-head">${head} · 지금 ${fmtKst(now)} KST · 웹판 계산 ${meta.built ? esc(meta.built.replace(' KST', '')) : '확인 불가'}</div>` +
      (uniq.length ? '<ul class="fo-hl-list">' + uniq.map(p => `<li>${esc(p)}</li>`).join('') + '</ul>' : '') +
      `<div class="fo-hl-dates">자료 기준일: ${esc(keyDates())}${unk ? ` · 확인하지 못한 값 ${unk}개(9절)` : ''}</div>` +
      `<details class="fo-hl-det"><summary>쓰는 자료 ${rows.length}개의 기준일 전체 보기</summary>` +
      '<div class="fo-tw"><table class="fo-t"><thead><tr><th>자료</th><th>지금 기준</th><th>와 있어야 할 기준</th><th>상태</th><th>갱신</th></tr></thead><tbody>' +
      rows.map(r => `<tr${r[3] !== 'ok' ? ' class="fo-hl-bad"' : ''}><td>${esc(r[0])}</td><td class="fo-num">${esc(r[1])}</td><td class="fo-num">${esc(r[2])}</td><td>${lab[r[3]] || esc(r[3])}</td><td class="fo-mut">${esc(r[4])}</td></tr>`).join('') +
      '</tbody></table></div><p class="fo-note">"와 있어야 할 기준"은 지금 시각과 각 자료의 정해진 갱신 시각(미국·한국 휴장일 반영)으로 계산한 날짜입니다. 지금 기준이 그보다 이르면 늦음으로 표시합니다. CFTC 는 공표가 휴일로 밀리는 주가 있어 11일 넘게 그대로일 때만 늦음으로 봅니다.</p></details>';
    box.hidden = false;
  }

  Promise.all([opt(get('data/tables.json')), opt(get(RAW + 'main/fo/data/status.json')), opt(get(RAW + 'main/state/watchdog.json')),
    opt(get(RAW + 'deriv-research/deriv/us/out/dash.json')), opt(get(RAW + 'main/uswalls/latest.json')), opt(get(RAW + 'main/pkg/holidays_kr.json')), opt(get(RAW + 'main/uswalls/occ_latest.json'))])
    .then(a => { try { draw(...a); } catch (e) { box.hidden = false; box.innerHTML = '<div class="fo-hl-head fo-up">자료 상태를 확인하지 못했습니다: ' + esc(String(e)) + '</div>'; } });
})();
