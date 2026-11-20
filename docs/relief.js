// 2026-11-08 추가: 반대매매 완화 조치(담보비율 유지의무 면제) 관련 계산 4개와 카드 채우기. index.html 이 256KB 한도에 가까워 따로 둔다.
// index.html 의 다른 코드와 변수를 공유하지 않는다(각 스크립트는 자기 범위). 쓰는 것은 dash·d3 뿐.
(function(){
  const P = d3.utcParse('%Y-%m-%d');
  const md = s => { const d = P(String(s).slice(0, 10)); return d ? (d.getUTCMonth() + 1) + '/' + d.getUTCDate() : String(s); };
  const f0 = d3.format(',.0f'), f1 = d3.format(',.1f'), f2 = d3.format(',.2f'), f3 = d3.format(',.3f');
  const num = v => (v === '' || v == null || isNaN(+v)) ? null : +v;
  const BAD = ['error', 'connect', 'declined', 'missing'];
  dash.calc('relief_cmp', {
    inputs: ['relief', 'credit', 'market'],
    title: '담보비율 면제 조치 전후 비교',
    description: '조치 시행일 직전 금투협 신용잔고 대비 5·10·20거래일 뒤 변화율(%)과 60거래일 안 최저, 시행일 코스피 종가 대비 20·60거래일 뒤 등락과 60거래일 안 최저(%). 직전 정점 = 시행 전 120거래일 안 최고. 시작 전인 조치는 시행 전 값만.',
    fn: (relief, credit, market) => {
      const pc = (a, b) => Math.round((a / b - 1) * 1000) / 10;
      const cr = credit.filter(r => r.credit_jo !== '' && r.credit_jo != null).map(r => ({d: String(r.date), v: Number(r.credit_jo)}));
      const mk = market.filter(r => r.kospi !== '' && r.kospi != null).map(r => ({d: String(r.date), v: Number(r.kospi)}));
      const lowOf = (arr, i, n) => { let m = i; for (let k = i; k < Math.min(arr.length, i + n + 1); k++) if (arr[k].v < arr[m].v) m = k; return m; };
      const peakBefore = (arr, i, n) => { let m = Math.max(0, i - n); for (let k = m; k <= i; k++) if (arr[k].v > arr[m].v) m = k; return m; };
      return relief.map(r => {
        const s = String(r.start), o = {start: s, end: String(r.end), name: r.name, status: r.status};
        let i = cr.findIndex(x => x.d >= s); if (i < 0) i = cr.length;
        const b = i - 1; if (b < 0) return o;
        const pk = peakBefore(cr, b, 120);
        o.base_date = cr[b].d; o.base_jo = cr[b].v; o.peak_date = cr[pk].d; o.peak_jo = cr[pk].v; o.pre_vs_peak = pc(cr[b].v, cr[pk].v);
        if (i < cr.length) { [5, 10, 20, 40].forEach(n => { if (b + n < cr.length) o['c' + n] = pc(cr[b + n].v, cr[b].v); }); const lo = lowOf(cr, b, 60); o.c_low = pc(cr[lo].v, cr[b].v); o.c_low_date = cr[lo].d; }
        let j = mk.findIndex(x => x.d >= s); if (j < 0) j = mk.length;
        const jb = j < mk.length ? j : mk.length - 1, mp = peakBefore(mk, jb, 120);
        o.k_date = mk[jb].d; o.k = mk[jb].v; o.k_peak_date = mk[mp].d; o.k_peak = mk[mp].v; o.k_vs_peak = pc(mk[jb].v, mk[mp].v); o.started = j < mk.length ? 1 : 0;
        if (j < mk.length) { [20, 60].forEach(n => { if (j + n < mk.length) o['k' + n] = pc(mk[j + n].v, mk[j].v); }); const lo = lowOf(mk, j, 60); o.k_low = pc(mk[lo].v, mk[j].v); o.k_low_date = mk[lo].d; }
        return o;
      });
    }
  });
  dash.calc('strict_parts', {
    inputs: ['market', 'credit'],
    title: '매수 엄격형 신호 조건별 분해',
    description: '매수 엄격형(3일 −7% 이상 급락 · 20일 저점 1% 이내 · 신용 5일 −1% 이하, 신용은 전날 공시분)을 최근 12거래일 날마다 조건별로 나눈 것(kind=day). 마지막 줄(kind=next)은 다음 거래일에 각 조건이 유지되는 종가·신용 기준선.',
    fn: (market, credit) => {
      const pc = (a, b) => Math.round((a / b - 1) * 1000) / 10;
      const mk = market.filter(r => r.kospi !== '' && r.kospi != null).map(r => ({d: String(r.date), c: Number(r.kospi)}));
      const cr = credit.filter(r => r.credit_jo !== '' && r.credit_jo != null).map(r => ({d: String(r.date), v: Number(r.credit_jo)}));
      const crBefore = d => { let k = cr.length - 1; while (k >= 0 && cr[k].d >= d) k--; return k; };
      const out = [];
      for (let i = Math.max(20, mk.length - 12); i < mk.length; i++) {
        const c = mk[i].c; let lo = c; for (let k = i - 19; k <= i; k++) lo = Math.min(lo, mk[k].c);
        const k1 = crBefore(mk[i].d), r3 = c / mk[i - 3].c - 1, cr5 = k1 >= 5 ? cr[k1].v / cr[k1 - 5].v - 1 : null;
        const c1 = r3 <= -0.07, c2 = c <= lo * 1.01, c3 = cr5 != null && cr5 <= -0.01;
        out.push({kind: 'day', date: mk[i].d, kospi: c, r3: Math.round(r3 * 1000) / 10, lo20: lo, d20: pc(c, lo), cred_date: k1 >= 0 ? cr[k1].d : '', cred: k1 >= 0 ? cr[k1].v : null, cr5: cr5 == null ? null : Math.round(cr5 * 1000) / 10,
                  c1: c1 ? 1 : 0, c2: c2 ? 1 : 0, c3: c3 ? 1 : 0, on: c1 && c2 && c3 ? '켜짐' : '꺼짐'});
      }
      const n = mk.length - 1; let lo19 = mk[n].c; for (let k = n - 18; k <= n; k++) lo19 = Math.min(lo19, mk[k].c);
      const kc = cr.findIndex(x => x.d === mk[n].d), k5 = (kc >= 0 ? kc : cr.length) - 5;
      out.push({kind: 'next', date: 'next', after: mk[n].d, c1_max: Math.round(mk[n - 2].c * 0.93 * 100) / 100, c1_base: mk[n - 2].d, c2_max: Math.round(lo19 * 1.01 * 100) / 100, c2_low: lo19,
                c3_max: k5 >= 0 ? Math.round(cr[k5].v * 0.99 * 1000) / 1000 : null, c3_base_date: k5 >= 0 ? cr[k5].d : '', c3_base: k5 >= 0 ? cr[k5].v : null, c3_have: kc >= 0 ? 1 : 0,
                c3_latest_date: cr.length ? cr[cr.length - 1].d : '', c3_latest: cr.length ? cr[cr.length - 1].v : null});
      return out;
    }
  });
  dash.calc('bottom_chk', {
    inputs: ['market', 'credit', 'liq', 'flows_daily'],
    title: '바닥 확인 조건(자동)',
    description: '11/6 보고서의 바닥 확인 조건 중 자료로 판정하는 것: 신용잔고 감소(마지막 공시 기준 5일 −3% 이하, 10·20일·정점 대비 함께), 외국인 순매도 둔화(최근 5일 순매수 합이 0 이상이거나 직전 5일 합의 절반보다 작은 매도), VKOSPI 꺾임(5거래일 전보다 낮고 20일 최고 아래), 반등 뒤 저점 유지(20일 최저 종가가 당일이 아니고 종가가 그 위). 보조 = 미수 반대매매 정점 통과(20일 안 비중 5% 이상 정점의 절반 이하). ok = 충족/미충족/보류.',
    fn: (market, credit, liq, flows_daily) => {
      const pc = (a, b) => Math.round((a / b - 1) * 1000) / 10;
      const mk = market.filter(r => r.kospi !== '' && r.kospi != null).map(r => ({d: String(r.date), c: Number(r.kospi), v: (r.vkospi === '' || r.vkospi == null) ? null : Number(r.vkospi)}));
      const cr = credit.filter(r => r.credit_jo !== '' && r.credit_jo != null).map(r => ({d: String(r.date), v: Number(r.credit_jo)}));
      const lq = liq.filter(r => r.ratio_pct !== '' && r.ratio_pct != null).map(r => ({d: String(r.date), v: Number(r.ratio_pct), e: Number(r.liq_eok)}));
      const fl = flows_daily.filter(r => r.foreign_jo !== '' && r.foreign_jo != null).map(r => ({d: String(r.date), v: Number(r.foreign_jo), b: String(r.basis || '')}));
      const out = [], n = cr.length - 1, m = mk.length - 1;
      if (n >= 20) { const d5 = pc(cr[n].v, cr[n - 5].v), d10 = pc(cr[n].v, cr[n - 10].v), d20 = pc(cr[n].v, cr[n - 20].v);
        let p250 = Math.max(0, n - 250), p40 = Math.max(0, n - 40); for (let k = p250; k <= n; k++) if (cr[k].v > cr[p250].v) p250 = k; for (let k = Math.max(0, n - 40); k <= n; k++) if (cr[k].v > cr[p40].v) p40 = k;
        out.push({key: 'credit', name: '1. 신용잔고 감소(5일 −3% 이하)', ok: d5 <= -3 ? '충족' : '미충족', asof: cr[n].d, v5: d5, v10: d10, v20: d20, vs250: pc(cr[n].v, cr[p250].v), peak250: cr[p250].d, vs40: pc(cr[n].v, cr[p40].v), peak40: cr[p40].d, jo: cr[n].v}); }
      if (fl.length >= 10) { const s5 = fl.slice(-5).reduce((a, r) => a + r.v, 0), p5 = fl.slice(-10, -5).reduce((a, r) => a + r.v, 0);
        out.push({key: 'foreign', name: '2. 외국인 순매도 둔화', ok: (s5 >= 0 || (p5 < 0 && s5 > p5 / 2)) ? '충족' : '미충족', asof: fl[fl.length - 1].d, s5: Math.round(s5 * 100) / 100, p5: Math.round(p5 * 100) / 100, prelim: /잠정/.test(fl[fl.length - 1].b) ? 1 : 0}); }
      { const vk = mk.filter(r => r.v != null); const q = vk.length - 1;
        if (q >= 20) { let mx = q - 19; for (let k = q - 19; k <= q; k++) if (vk[k].v > vk[mx].v) mx = k;
          out.push({key: 'vkospi', name: '3. VKOSPI 꺾임', ok: (vk[q].v < vk[q - 5].v && vk[q].v < vk[mx].v) ? '충족' : '미충족', asof: vk[q].d, v: vk[q].v, v5: vk[q - 5].v, max20: vk[mx].v, max20_date: vk[mx].d, lag: vk[q].d < mk[m].d ? 1 : 0}); } }
      if (m >= 20) { let lo = m - 19; for (let k = m - 19; k <= m; k++) if (mk[k].c <= mk[lo].c) lo = k;
        out.push({key: 'low', name: '4. 반등 뒤 저점 유지', ok: (lo < m && mk[m].c > mk[lo].c) ? '충족' : '미충족', asof: mk[m].d, c: mk[m].c, low: mk[lo].c, low_date: mk[lo].d, days_since: m - lo}); }
      if (lq.length >= 20) { const w = lq.slice(-20); let pk = 0; for (let k = 0; k < w.length; k++) if (w[k].v > w[pk].v) pk = k; const r3 = Math.max(...w.slice(-3).map(r => r.v));
        out.push({key: 'liq', name: '보조. 미수 반대매매 정점 통과', ok: w[pk].v < 5 ? '보류' : (r3 <= w[pk].v / 2 ? '충족' : '미충족'), asof: lq[lq.length - 1].d, peak: w[pk].v, peak_date: w[pk].d, peak_eok: w[pk].e, last3: r3, last: lq[lq.length - 1].v, last_eok: lq[lq.length - 1].e}); }
      return out;
    }
  });
  dash.calc('credit_entry', {
    inputs: ['credit', 'market'],
    title: '신용 평균 매수 지수 추정과 청산 참고선',
    description: '코스피 신용잔고가 늘어난 날의 증가분을 그날 코스피 종가에 가중해 평균한 지수를 네 방법으로 추정: 최근 유입(250거래일 안 정점 뒤 최저일부터), 1년 저점부터, 선입선출·후입선출(상환분을 먼저 산 것·나중에 산 것부터 빼고 남은 잔고의 평균). 참고선 = 지수 × 담보비율(1.4·1.3·1.2) × 대출 비중 0.6(자기자금 40%). 추정값.',
    fn: (credit, market) => {
      const cr = credit.filter(r => r.kospi_jo !== '' && r.kospi_jo != null).map(r => ({d: String(r.date), v: Number(r.kospi_jo)}));
      const px = new Map(market.filter(r => r.kospi !== '' && r.kospi != null).map(r => [String(r.date), Number(r.kospi)]));
      const lastD = [...px.keys()].pop(), lastK = px.get(lastD);
      const s = Math.max(0, cr.length - 250); let pk = s, lo250 = s; for (let k = s; k < cr.length; k++) { if (cr[k].v > cr[pk].v) pk = k; if (cr[k].v <= cr[lo250].v) lo250 = k; }
      let tr = pk; for (let k = pk; k < cr.length; k++) if (cr[k].v <= cr[tr].v) tr = k;
      const inflow = t => { let w = 0, sum = 0, n = 0; for (let k = t + 1; k < cr.length; k++) { const d = cr[k].v - cr[k - 1].v, p = px.get(cr[k].d); if (d > 0 && p != null) { w += d; sum += d * p; n++; } } return {e: w ? sum / w : null, w, n}; };
      const lots = (t, lifo) => { const L = []; for (let k = t + 1; k < cr.length; k++) { const d = cr[k].v - cr[k - 1].v, p = px.get(cr[k].d); if (d > 0) { if (p != null) L.push([d, p]); } else { let rem = -d; while (rem > 1e-9 && L.length) { const i = lifo ? L.length - 1 : 0; if (L[i][0] <= rem) { rem -= L[i][0]; L.splice(i, 1); } else { L[i][0] -= rem; rem = 0; } } } }
        const w = L.reduce((a, l) => a + l[0], 0); return {e: w ? L.reduce((a, l) => a + l[0] * l[1], 0) / w : null, w, n: L.length}; };
      const r = v => v == null ? null : Math.round(v), rw = v => Math.round(v * 100) / 100, md = s => +s.slice(5, 7) + '/' + +s.slice(8, 10);
      const a = inflow(tr), b = inflow(lo250), c = lots(tr, false), d = lots(tr, true);
      const s5 = Math.max(0, cr.length - 500); let lo500 = s5; for (let k = s5; k < cr.length; k++) if (cr[k].v <= cr[lo500].v) lo500 = k;
      const b5 = inflow(lo500);   // 2년 저점부터(신용이 1년 최저까지 줄어 위 방법들이 비는 날의 예비)
      const row = (method, name, o, text) => { const e = o.e; return {method, name, entry: r(e), l140: e == null ? null : r(e * 1.4 * 0.6), l130: e == null ? null : r(e * 1.3 * 0.6), l120: e == null ? null : r(e * 1.2 * 0.6), l140_50: e == null ? null : r(e * 1.4 * 0.5), l130_50: e == null ? null : r(e * 1.3 * 0.5), weight_jo: rw(o.w), n: o.n, text, trough_date: cr[tr].d, trough_jo: cr[tr].v, peak_date: cr[pk].d, peak_jo: cr[pk].v, low250_date: cr[lo250].d, low250_jo: cr[lo250].v, last_jo_date: cr[cr.length - 1].d, last_jo: cr[cr.length - 1].v, last_date: lastD, last_kospi: lastK}; };
      const OUT = [row('recent', '최근 유입: 정점 뒤 최저일부터 늘어난 날 가중', a, `코스피 신용 ${md(cr[pk].d)} 정점 ${cr[pk].v}조 → ${md(cr[tr].d)} 최저 ${cr[tr].v}조 이후 늘어난 날 ${a.n}일, 유입 합계 ${rw(a.w)}조원(그 뒤 상환·청산으로 순잔고는 ${rw(cr[cr.length - 1].v - cr[tr].v)}조만 늘어 최근 유입분 대부분이 이미 정리됐거나 더 낮은 가격에 재진입)`),
              row('low250', '1년 저점부터 늘어난 날 가중', b, `1년 저점 ${cr[lo250].d} ${cr[lo250].v}조 이후 늘어난 날 ${b.n}일, 유입 합계 ${rw(b.w)}조원 — 올해 상승기에 들어온 신용까지 포함`),
              row('fifo', '선입선출로 남은 잔고(최저일 이후)', c, `상환·청산을 먼저 산 신용부터 뺀 뒤 남은 ${rw(c.w)}조원의 평균 — 남은 신용이 뒤늦게 들어온 것이면 이쪽`),
              row('lifo', '후입선출로 남은 잔고(최저일 이후)', d, `상환·청산을 나중에 산 신용부터 뺀 뒤 남은 ${rw(d.w)}조원의 평균 — 급락 때 최근 매수분이 먼저 청산됐다면 이쪽`),
              row('low500', '2년 저점부터 늘어난 날 가중', b5, `2년 저점 ${cr[lo500].d} ${cr[lo500].v}조 이후 늘어난 날 ${b5.n}일, 유입 합계 ${rw(b5.w)}조원 — 1년 저점 기준이 비는 날의 예비`)];
      // 대표 줄(그래프 참고선·요약에 쓰는 줄)을 맨 앞으로: 최근 유입 → 1년 저점부터 → 2년 저점부터 순으로, 유입 합계 1조원 이상인 첫 방법. 신용이 정점 뒤 최저를 새로 쓰면 '최근 유입'이 비므로 다음 방법으로 넘어간다(11/12 수정 — 이때 그래프 참고선이 사라지던 문제)
      const SHORT = {recent: '최근 유입', low250: '1년 저점부터', low500: '2년 저점부터'};
      const pi = ['recent', 'low250', 'low500'].map(m => OUT.findIndex(r => r.method === m)).find(i => i >= 0 && OUT[i].entry != null && OUT[i].weight_jo >= 1);
      if (pi != null && pi > 0) OUT.unshift(OUT.splice(pi, 1)[0]);
      OUT.forEach((r, i) => { r.primary = i === 0 && r.entry != null; r.basis = SHORT[r.method] || r.name; r.credit_date = cr[cr.length - 1].d; });
      return OUT;
    }
  });

  // 2026-11-20 추가: 반대매매 기준선(검증) — 직전 60거래일 최저 종가 기준 1선(+1%)·2선(새 저점)·3선(−2%). index.html 크기 한도 때문에 설명 글도 여기서 채운다.
  // 후보 168개를 2016~2022년 자료로 미리 정한 규칙대로 고르고 2023~2026년에 확인했다. 검증 코드·결과: 저장소 deriv-research 가지 research/liq_lines(out/ladder.csv, GitHub Actions 44641164893, 자료 main f4c29b9). 아래 숫자는 그 결과(고정값).
  const LL_VER = {date: '2026-11-20', base_dev: 8.4, base_test: 8.8};
  const LL_TIERS = [
    {tier: '1선', name: '1선 · 주의', rule: '직전 60거래일 최저 종가 +1%', f: 1.01, p_dev: 43.6, p_test: 70.2, n_dev: 179, e_dev: 49, n_test: 47, e_test: 14, c3_dev: -2.26, c3_test: -3.86, sev_dev: 31.8, sev_test: 46.8},
    {tier: '2선', name: '2선 · 새 저점', rule: '직전 60거래일 최저 종가', f: 1.00, p_dev: 60.5, p_test: 82.1, n_dev: 86, e_dev: 45, n_test: 28, e_test: 19, c3_dev: -3.60, c3_test: -5.13, sev_dev: 51.2, sev_test: 60.7},
    {tier: '3선', name: '3선 · 대량 청산', rule: '직전 60거래일 최저 종가 −2%', f: 0.98, p_dev: 100, p_test: 88.9, n_dev: 17, e_dev: 11, n_test: 9, e_test: 8, c3_dev: -8.36, c3_test: -7.31, sev_dev: 100, sev_test: 88.9}];
  const LL_NOTE = '1선 = 직전 60거래일 최저 종가 +1%, 2선 = 그 최저 종가(새 저점), 3선 = 그 최저 종가 −2%. 종가가 이 선을 깨면 그 뒤 사흘 안에 신용 강제 청산(코스피 신용잔고 3일 −2% 이상 감소 = 청산 물결)이 몰렸다. 후보 168개(직전 저점 창 5~250일·문턱 +2~−10%, 고점 대비 낙폭, 아래 신용 평균 매수 지수 선 방법별, 비례 상환 분포선)를 2016~2022년 자료로 미리 정한 규칙(신용·미수 청산 물결 맞힘 순위)대로 고르고 2023~2026년에 확인했다(2026-11-20). 새 저점이 생기면 선이 따라 내려가 이미 청산된 물량이 저절로 빠진다. 평소(아무 날) 청산 물결은 2016~2022년 8.4%·2023~2026년 8.8%, 사흘 신용 변화 평균 +0.2%·+0.3%. 선 아래에 머문 날은 날마다 셌고 이탈 구간 = 처음 깬 횟수, 3선은 표본이 적다(11·8구간). 아래 표 첫 줄의 담보비율 140% 선은 같은 검증에서 청산 물결의 15%(2016~2022)·10%(2023~2026)만 그 선 아래에서 일어나(1선은 54%·40%) 그래프에서 뺐다. 미수 반대매매는 지수 수준과 상관없이 결제일(T+2)에 정리되므로 따로 급락 이틀 뒤를 본다. 지수 기준이라 신용이 몰린 종목은 더 먼저 걸린다. 한눈에 보기 그래프 코스피 칸의 세 선(1선 점선 · 2선 실선 · 3선 촘촘한 점선)이 날마다의 기준선이다. 표 위 칸 셋은 신용 평균(1년 저점 뒤 늘어난 신용을 그날 종가로 가중한 평균)·해소 반영 평균(줄어든 만큼을 비싸게 산 신용부터 뺀 남은 신용의 평균)·정점 대비 해소분이고, 그래프의 파란 긴 점선 두 개가 날마다의 그 값이다. 신용 강제 청산 금액은 따로 공시되지 않아 상환과 구분하지 못하는 추정값이다. 참고용이지 추천이 아니다.';
  dash.calc('liq_lines', {
    inputs: ['market'],
    title: '반대매매 기준선(직전 60거래일 최저 종가 기준 · 2026-11-20 검증)',
    description: '1선 = 직전 60거래일 최저 종가 × 1.01, 2선 = 그 최저 종가(새 저점), 3선 = × 0.98. line = 마지막 날까지 넣은 다음 거래일 기준선, line_last = 마지막 날의 기준선(그 전 60거래일), line_prev = 전날의 기준선. p_dev·p_test = 종가가 선 아래인 날 뒤 사흘 안 신용 청산 물결(코스피 신용잔고 3일 −2% 이상 감소) 비율 %(2016~2022·2023~2026, 평소 8.4·8.8%). c3 = 사흘 신용 변화 평균 %, sev = 3일 −3% 이상 비율 %, e = 처음 깬 구간 수, n = 선 아래 날 수. 검증 숫자는 저장소 deriv-research 가지 research/liq_lines/out/ladder.csv의 고정값.',
    fn: (market) => {
      const mk = market.filter(r => r.kospi !== '' && r.kospi != null && isFinite(+r.kospi)).map(r => ({d: String(r.date), v: +r.kospi})).sort((a, b) => a.d < b.d ? -1 : 1);
      const N = 60, n = mk.length; if (n < N + 3) return [];
      let lo = Infinity, loD = null; for (let k = n - N; k < n; k++) if (mk[k].v <= lo) { lo = mk[k].v; loD = mk[k].d; }   // 다음 거래일에 쓰는 선(마지막 날까지 60개 종가의 최저)
      let lp = Infinity; for (let k = n - 1 - N; k < n - 1; k++) lp = Math.min(lp, mk[k].v);    // 마지막 날의 선(그 전 60개) — 마지막 날 이탈 판정
      let lq = Infinity; for (let k = n - 2 - N; k < n - 2; k++) lq = Math.min(lq, mk[k].v);    // 전날의 선
      const last = mk[n - 1], prev = mk[n - 2], r2 = v => Math.round(v * 100) / 100;
      return LL_TIERS.map(t => ({tier: t.tier, name: t.name, rule: t.rule, factor: t.f, line: r2(lo * t.f), line_last: r2(lp * t.f), line_prev: r2(lq * t.f),
        base_low: lo, base_date: loD, last_date: last.d, last_kospi: last.v, prev_date: prev.d, prev_kospi: prev.v,
        need_pct: r2((lo * t.f / last.v - 1) * 100), broke: last.v < lp * t.f, broke_new: last.v < lp * t.f && prev.v >= lq * t.f,
        p_dev: t.p_dev, p_test: t.p_test, n_dev: t.n_dev, e_dev: t.e_dev, n_test: t.n_test, e_test: t.e_test, c3_dev: t.c3_dev, c3_test: t.c3_test, sev_dev: t.sev_dev, sev_test: t.sev_test,
        base_dev: LL_VER.base_dev, base_test: LL_VER.base_test, ver: LL_VER.date}));
    }
  });
  dash.calc('liq_hist', {
    inputs: ['market'],
    title: '반대매매 기준선 날마다(그래프 계단 선)',
    description: '날마다 그날 쓰인 기준선: 그 전 60거래일 최저 종가(l2)와 그 × 1.01(l1) · × 0.98(l3). 한눈에 보기 그래프 코스피 칸의 세 선.',
    fn: (market) => {
      const mk = market.filter(r => r.kospi !== '' && r.kospi != null && isFinite(+r.kospi)).map(r => ({d: String(r.date), v: +r.kospi})).sort((a, b) => a.d < b.d ? -1 : 1), out = [];
      for (let i = 60; i < mk.length; i++) { let lo = Infinity; for (let k = i - 60; k < i; k++) if (mk[k].v < lo) lo = mk[k].v;
        out.push({date: mk[i].d, l1: Math.round(lo * 101) / 100, l2: lo, l3: Math.round(lo * 98) / 100}); }
      return out;
    }
  });

  // 2026-11-20 추가(사용자 요청): 신용 평균과 해소분 — 1년(250거래일) 저점 뒤 늘어난 신용을 그날 코스피 종가로 가중한 평균(유입 기준)과, 그 뒤 줄어든 만큼(상환·청산)을 비싸게 산 신용부터 뺀 '해소 반영 평균'. 날마다 값은 그래프 선, 지금 값은 반대매매 기준선 표 위 칸 셋.
  dash.calc('credit_hist', {
    inputs: ['credit', 'market'],
    title: '신용 평균·해소 반영 평균 날마다(그래프 선)',
    description: 'ca = 그날까지 250거래일 안 코스피 신용잔고 최저일(1년 저점) 뒤 잔고가 늘어난 날의 증가분을 그날 코스피 종가로 가중한 평균(신용 평균, 유입 기준). cc = 잔고가 줄어든 날 그만큼을 가장 비싸게 산 신용부터 뺀 뒤 남은 신용의 평균(해소 반영 평균). rem = 남은 신용 조원, inw = 1년 저점 뒤 유입 합계 조원, lo_date = 1년 저점. 추정값.',
    fn: (credit, market) => {
      const cr = credit.filter(r => r.kospi_jo !== '' && r.kospi_jo != null && isFinite(+r.kospi_jo)).map(r => ({d: String(r.date), v: +r.kospi_jo})).sort((a, b) => a.d < b.d ? -1 : 1);
      const px = new Map(market.filter(r => r.kospi !== '' && r.kospi != null && isFinite(+r.kospi)).map(r => [String(r.date), +r.kospi]));
      const out = []; let anchor = -1, L = [], inW = 0, inS = 0, rW = 0, rS = 0;   // L = 남은 신용 [금액, 매수 지수], 지수 낮은 순
      const step = k => { const d = cr[k].v - cr[k - 1].v, p = px.get(cr[k].d);
        if (d > 0) { if (p == null) return; inW += d; inS += d * p; rW += d; rS += d * p; let a = 0, b = L.length; while (a < b) { const m = (a + b) >> 1; if (L[m][1] <= p) a = m + 1; else b = m; } L.splice(a, 0, [d, p]); }
        else { let q = -d; while (q > 1e-9 && L.length) { const t = L[L.length - 1], u = Math.min(q, t[0]); t[0] -= u; q -= u; rW -= u; rS -= u * t[1]; if (t[0] <= 1e-9) L.pop(); } } };   // 줄어든 만큼은 가장 비싸게 산 것부터
      for (let t = 1; t < cr.length; t++) {
        let lo = Math.max(0, t - 249); for (let k = lo; k <= t; k++) if (cr[k].v <= cr[lo].v) lo = k;   // 1년 저점(같으면 나중 날)
        if (lo !== anchor) { anchor = lo; L = []; inW = inS = rW = rS = 0; for (let k = lo + 1; k <= t; k++) step(k); } else step(t);
        out.push({date: cr[t].d, ca: inW > 1e-9 ? Math.round(inS / inW) : null, cc: rW > 1e-9 ? Math.round(rS / rW) : null, rem: Math.round(rW * 1000) / 1000, inw: Math.round(inW * 1000) / 1000, lo_date: cr[lo].d});
      }
      return out;
    }
  });
  dash.calc('credit_clear', {
    inputs: ['credit', 'market', 'liq'],
    title: '신용 평균과 해소분(지금 값)',
    description: 'avg = 1년(250거래일) 저점 뒤 코스피 신용잔고가 늘어난 날의 증가분을 그날 코스피 종가로 가중한 평균. clr = 그 뒤 줄어든 만큼(상환·청산)을 비싸게 산 신용부터 뺀 남은 신용의 평균(alt = 먼저 산 것부터 뺀 경우). gone = 250거래일 안 정점 대비 잔고 감소 조원(pct %), misu_jo = 정점 다음 날부터 미수 반대매매 합계 조원. vs = 마지막 코스피 종가가 그 평균보다 몇 % 위(+)·아래(−). in_jo·out_jo·rem_jo = 1년 저점 뒤 유입·감소·남은 신용 조원. 신용 강제 청산 금액은 따로 공시되지 않아 상환과 구분하지 못하는 추정값.',
    fn: (credit, market, liq) => {
      const cr = credit.filter(r => r.kospi_jo !== '' && r.kospi_jo != null && isFinite(+r.kospi_jo)).map(r => ({d: String(r.date), v: +r.kospi_jo})).sort((a, b) => a.d < b.d ? -1 : 1);
      const mk = market.filter(r => r.kospi !== '' && r.kospi != null && isFinite(+r.kospi)).map(r => [String(r.date), +r.kospi]).sort((a, b) => a[0] < b[0] ? -1 : 1), px = new Map(mk);
      const n = cr.length; if (n < 30 || !mk.length) return [];
      const s = Math.max(0, n - 250); let lo = s, pk = s; for (let k = s; k < n; k++) { if (cr[k].v <= cr[lo].v) lo = k; if (cr[k].v > cr[pk].v) pk = k; }
      const sim = worst => { const L = []; let inW = 0, inS = 0, outW = 0;
        for (let k = lo + 1; k < n; k++) { const d = cr[k].v - cr[k - 1].v, p = px.get(cr[k].d);
          if (d > 0) { if (p != null) { inW += d; inS += d * p; L.push([d, p]); } }
          else if (d < 0) { let q = -d; outW += q; if (worst) L.sort((a, b) => a[1] - b[1]); while (q > 1e-9 && L.length) { const i = worst ? L.length - 1 : 0, u = Math.min(q, L[i][0]); L[i][0] -= u; q -= u; if (L[i][0] <= 1e-9) L.splice(i, 1); } } }
        const w = L.reduce((a, l) => a + l[0], 0); return {e: inW ? inS / inW : null, c: w > 1e-9 ? L.reduce((a, l) => a + l[0] * l[1], 0) / w : null, inW, outW, w}; };
      const W = sim(true), F = sim(false), last = cr[n - 1], [kd, k] = mk[mk.length - 1];
      const ms = liq.filter(r => String(r.date) > cr[pk].d && r.liq_eok !== '' && r.liq_eok != null && isFinite(+r.liq_eok));
      const r0 = v => v == null ? null : Math.round(v), r1 = v => Math.round(v * 10) / 10, r2 = v => Math.round(v * 100) / 100;
      const base = {credit_date: last.d, last_date: kd, last_kospi: k, lo_date: cr[lo].d, lo_jo: cr[lo].v, peak_date: cr[pk].d, peak_jo: cr[pk].v, last_jo: last.v, in_jo: r2(W.inW), out_jo: r2(W.outW), rem_jo: r2(W.w)};
      return [{key: 'avg', label: '신용 평균', value: r0(W.e), vs: W.e ? r1((k / W.e - 1) * 100) : null, ...base},
        {key: 'clr', label: '해소 반영 평균', value: r0(W.c), vs: W.c ? r1((k / W.c - 1) * 100) : null, alt: r0(F.c), ...base},
        {key: 'gone', label: '해소분', value: r2(cr[pk].v - last.v), pct: r1((last.v / cr[pk].v - 1) * 100), misu_jo: r2(ms.reduce((a, r) => a + +r.liq_eok, 0) / 10000), misu_days: ms.length, ...base}];
    }
  });

  function fillRelief(){
    try {
      const pcs = v => (v === '' || v == null || isNaN(+v)) ? '—' : (+v > 0 ? '+' : +v < 0 ? '−' : '') + f1(Math.abs(+v)) + '%';
      const jo = v => (v === '' || v == null || isNaN(+v)) ? '—' : f2(+v);
      const yy = s => String(s).slice(0, 4);
      const rd = dash.data('relief_cmp'), rt = document.getElementById('rl-tbl');
      if (rt) { const tb = rt.tBodies[0]; tb.replaceChildren();
        if (rd.status === 'ok') { rt.classList.remove('dash-skeleton');
          rd.data.forEach(r => { const tr = document.createElement('tr'); tr.dataset.key = encodeURIComponent(r.start);
            [[r.name + (r.status ? ' (' + r.status + ')' : ''), ''], [md(r.start) + '~' + md(r.end) + (yy(r.start) !== yy(r.end) ? '(' + yy(r.end).slice(2) + '년)' : ''), 'rv-nw'],
             [r.base_jo == null ? '—' : jo(r.base_jo) + (r.base_date ? '(' + md(r.base_date) + ')' : ''), 'rv-num'], [r.pre_vs_peak == null ? '—' : pcs(r.pre_vs_peak) + '(' + md(r.peak_date) + ' ' + jo(r.peak_jo) + '조)', 'rv-num'],
             [pcs(r.c5), 'rv-num'], [pcs(r.c10), 'rv-num'], [pcs(r.c20), 'rv-num'], [r.c_low == null ? '—' : pcs(r.c_low) + '(' + md(r.c_low_date) + ')', 'rv-num'],
             [r.k == null ? '—' : f2(r.k) + '(' + md(r.k_date) + (r.started ? '' : ' 시행 전 마지막') + ')', 'rv-num'], [r.k_low == null ? '—' : pcs(r.k_low) + '(' + md(r.k_low_date) + ')', 'rv-num'], [pcs(r.k20), 'rv-num'], [pcs(r.k60), 'rv-num']]
              .forEach(([v, cls]) => { const td = document.createElement('td'); td.textContent = v; if (cls) td.className = cls; tr.appendChild(td); }); tb.appendChild(tr); }); }
        else rt.classList.toggle('dash-skeleton', !BAD.includes(rd.status)); }
      // 바닥 확인 조건
      const bd = dash.data('bottom_chk'), bt = document.getElementById('bc-tbl'), bs = document.getElementById('bc-sum');
      if (bt) { const tb = bt.tBodies[0]; tb.replaceChildren();
        if (bd.status === 'ok') { bt.classList.remove('dash-skeleton');
          const sj = v => (v > 0 ? '+' : v < 0 ? '−' : '') + f2(Math.abs(v)) + '조';
          const T = {credit: r => [`금투협 ${md(r.asof)}분 ${f3(r.jo)}조원 · 5일 ${pcs(r.v5)} · 10일 ${pcs(r.v10)} · 20일 ${pcs(r.v20)} · 최근 정점(${md(r.peak40)}) 대비 ${pcs(r.vs40)} · 1년 정점(${md(r.peak250)}) 대비 ${pcs(r.vs250)}`, '엄격형 매수 조건은 5일 −1% 이하, 고변동 청산 국면은 −3% 이하. 조치 기간에는 청산이 미뤄져 5일 값이 둔해질 수 있으니 10·20일을 같이 본다'],
                     foreign: r => [`KRX ${md(r.asof)}까지 최근 5일 합 ${sj(r.s5)} · 직전 5일 합 ${sj(r.p5)}` + (r.prelim ? ' (마지막 날은 정규장 잠정치)' : ''), '순매수로 돌아서거나 매도가 직전 5일의 절반 아래로 줄면 충족. NXT 체결분은 빠져 있다'],
                     vkospi: r => [`VKOSPI ${md(r.asof)} ${f2(r.v)} · 5거래일 전 ${f2(r.v5)} · 20일 최고 ${f2(r.max20)}(${md(r.max20_date)})` + (r.lag ? ' — 당일분은 다음 날 08:31 수집' : ''), '5거래일 전보다 낮고 20일 최고 아래면 충족. 20일 최고가 당일이면 미충족'],
                     low: r => [`20일 최저 종가 ${f2(r.low)}(${md(r.low_date)}) · ${md(r.asof)} 종가 ${f2(r.c)}` + (r.days_since ? ` · 저점 뒤 ${r.days_since}거래일` : ' · 당일이 신저가'), '종가가 20일 최저 위에 있고 그날이 저점이 아니면 충족. 신저가가 나오면 바로 미충족'],
                     liq: r => [`미수 반대매매 비중 20일 정점 ${f1(r.peak)}%(${md(r.peak_date)}, ${f1(r.peak_eok)}억원) · 최근 3일 최고 ${f1(r.last3)}% · 마지막 ${md(r.asof)} ${f1(r.last)}%(${f1(r.last_eok)}억원)`, '정점이 5% 이상이고 최근 3일이 그 절반 이하면 통과. 11/9 조치의 영향 없음(미수 통계는 대상 아님). 셈에 넣지 않는 보조']};
          bd.data.forEach(r => { const tr = document.createElement('tr'); tr.dataset.key = r.key; const [t, nte] = (T[r.key] || (() => ['', '']))(r);
            [[r.name, ''], [r.ok, 'rv-nw'], [t, ''], [nte, '']].forEach(([v, cls]) => { const td = document.createElement('td'); td.textContent = v; if (cls) td.className = cls; if (v === '충족') td.style.color = 'var(--color-ok)'; if (v === '미충족') td.style.color = 'var(--color-bad)'; tr.appendChild(td); }); tb.appendChild(tr); });
          const main = bd.data.filter(r => r.key !== 'liq'), ok = main.filter(r => r.ok === '충족');
          if (bs) bs.textContent = `자동 조건 ${ok.length}/${main.length} 충족` + (ok.length ? `(${ok.map(r => r.name.replace(/^\d\. /, '')).join(' · ')})` : '') + ' — 보고서 기준은 다섯(수기 1 포함) 중 둘 이상. ' + (ok.length >= 2 ? '둘 이상이라 바닥 확인 쪽으로 기울었지만, 신용 조건이 빠져 있으면 조치 때문인지 가격 때문인지 위 표에서 나눠 본다.' : '아직 둘 미만 — 바닥 확인 전.');
        } else { bt.classList.toggle('dash-skeleton', !BAD.includes(bd.status)); if (bs) bs.textContent = ''; } }
      // 매수 엄격형 분해
      const sd = dash.data('strict_parts'), st = document.getElementById('sp-tbl'), ss = document.getElementById('sp-sum'), sn = document.getElementById('sp-next');
      if (st) { const tb = st.tBodies[0]; tb.replaceChildren();
        if (sd.status === 'ok') { st.classList.remove('dash-skeleton');
          const days = sd.data.filter(r => r.kind === 'day'), nx = sd.data.find(r => r.kind === 'next');
          const mark = (v, ok) => `${v}${ok ? ' ✓' : ' ✗'}`;
          days.slice().reverse().forEach(r => { const tr = document.createElement('tr'); tr.dataset.key = r.date; if (r.on === '켜짐') tr.style.fontWeight = '600';
            [[md(r.date) + (r.on === '켜짐' && days.slice(Math.max(0, days.indexOf(r) - 5), days.indexOf(r)).every(q => q.on !== '켜짐') ? ' 시작' : ''), ''], [f2(r.kospi), 'rv-num'], [mark(pcs(r.r3), +r.c1), 'rv-num'], [mark(pcs(r.d20) + '(저점 ' + f0(r.lo20) + ')', +r.c2), 'rv-num'], [r.cr5 == null ? '금투협 없음 ✗' : mark(pcs(r.cr5) + '(' + md(r.cred_date) + '분 ' + f3(r.cred) + '조)', +r.c3), 'rv-num'], [r.on, 'rv-nw']]
              .forEach(([v, cls]) => { const td = document.createElement('td'); td.textContent = v; if (cls) td.className = cls; if (v === '켜짐') td.style.color = 'var(--color-ok)'; tr.appendChild(td); }); tb.appendChild(tr); });
          const L = days[days.length - 1];
          if (ss && L) { const why = [[+L.c1, '3일 급락'], [+L.c2, '20일 저점'], [+L.c3, '신용 5일']]; const offs = why.filter(w => !w[0]).map(w => w[1]);
            ss.textContent = `${md(L.date)} 매수 엄격형 ${L.on}` + (L.on === '켜짐' ? ` — 세 조건 모두 충족(3일 ${pcs(L.r3)} · 20일 저점 대비 ${pcs(L.d20)} · 신용 5일 ${pcs(L.cr5)}, 금투협 ${md(L.cred_date)}분).` : ` — 빠진 조건: ${offs.join('·')}` + (offs.length === 1 && offs[0] === '신용 5일' ? '(가격은 아직 바닥권인데 신용만 안 줄었다 — 조치로 청산이 미뤄졌는지 저가 매수 신용이 들어왔는지 신용 카드에서 확인)' : offs.includes('20일 저점') || offs.includes('3일 급락') ? '(가격이 바닥권을 벗어나 꺼진 것)' : '') + '.'); }
          if (sn && nx) sn.textContent = `다음 거래일(${md(nx.after)} 다음 장)에 조건이 유지되는 기준: 3일 급락은 종가 ${f2(nx.c1_max)} 이하(${md(nx.c1_base)} 종가 −7%), 20일 저점은 종가 ${f2(nx.c2_max)} 이하(20일 최저 ${f2(nx.c2_low)} +1%), 신용은 금투협 ${md(nx.after)}분이 ${nx.c3_max == null ? '—' : f3(nx.c3_max) + '조원'} 이하(${md(nx.c3_base_date)}분 ${f3(nx.c3_base)}조 −1%` + (nx.c3_have ? `, ${md(nx.after)}분 ${f3(nx.c3_latest)}조 공시됨` : `; 아직 미공시, 마지막 ${md(nx.c3_latest_date)}분 ${f3(nx.c3_latest)}조`) + '). 종가가 저점 기준선 위로 반등하면 가격 때문에, 신용이 기준선 위로 늘면 신용 때문에 꺼진다 — 둘 다면 둘 다 적힌다.';
        } else { st.classList.toggle('dash-skeleton', !BAD.includes(sd.status)); } }
      // 반대매매 기준선(검증, 11/20)
      const ld = dash.data('liq_lines'), lt = document.getElementById('ll-tbl'), ls = document.getElementById('ll-sum'), ln = document.getElementById('ll-note');
      if (ln && !ln.textContent) ln.textContent = LL_NOTE;
      if (lt) { const tb = lt.tBodies[0]; tb.replaceChildren();
        if (ld.status === 'ok' && ld.data.length) { lt.classList.remove('dash-skeleton');
          ld.data.forEach(r => { const tr = document.createElement('tr'); tr.dataset.key = r.tier; if (r.broke) tr.style.fontWeight = '600';
            [[r.name, 'rv-nw'], [f0(r.line), 'rv-num'], [pcs(r.need_pct), 'rv-num'], [`${f1(r.p_dev)}% → ${f1(r.p_test)}%`, 'rv-num'], [`${pcs(r.c3_dev)} · ${pcs(r.c3_test)}`, 'rv-num'], [`${r.e_dev}번(${r.n_dev}일) · ${r.e_test}번(${r.n_test}일)`, 'rv-num']]
              .forEach(([v, cls]) => { const td = document.createElement('td'); td.textContent = v; if (cls) td.className = cls; tr.appendChild(td); }); tb.appendChild(tr); });
          const R = ld.data, k = R[0].last_kospi, Ll = R.map(r => r.line_last);
          const pos = k >= Ll[0] ? `1선(${f0(Ll[0])}) 위 — 아직 기준선 위` : k >= Ll[1] ? `1선(${f0(Ll[0])}) 아래·2선(${f0(Ll[1])}) 위 — 주의 구간` : k >= Ll[2] ? `2선(${f0(Ll[1])}) 아래 — 새 저점 구간` : `3선(${f0(Ll[2])})도 아래 — 대량 청산 구간`;
          const nw = R.filter(r => r.broke_new).map(r => r.tier);
          if (ls) ls.textContent = `${md(R[0].last_date)} 종가 ${f2(k)}는 ${pos}` + (nw.length ? `(오늘 ${nw.join('·')}을 새로 깼다)` : '') + `. 다음 거래일 기준선은 직전 60거래일 최저 종가 ${f2(R[0].base_low)}(${md(R[0].base_date)}) 기준 ` + R.map(r => `${r.tier} ${f0(r.line)}(종가 대비 ${pcs(r.need_pct)})`).join(' · ') + `. 종가가 1선 아래면 사흘 안 신용 청산 물결이 2016~2022년 ${f1(R[0].p_dev)}%·2023~2026년 ${f1(R[0].p_test)}%(평소 ${f1(R[0].base_dev)}·${f1(R[0].base_test)}%), 2선 아래면 ${f1(R[1].p_dev)}·${f1(R[1].p_test)}%, 3선 아래면 ${f1(R[2].p_dev)}·${f1(R[2].p_test)}%였다.`;
        } else { lt.classList.toggle('dash-skeleton', !BAD.includes(ld.status)); if (ls) ls.textContent = ''; } }
      // 신용 평균·해소분(11/20 사용자 요청): 반대매매 기준선 표 위 칸 셋 — 매 갱신 자동 계산
      const cq = dash.data('credit_clear'), lw = lt && lt.closest('.rv-tbl-wrap');
      let cb = document.getElementById('ca-box');
      if (!cb && lw) { cb = document.createElement('div'); cb.id = 'ca-box'; cb.className = 'rv-kpis'; cb.dataset.source = 'credit_clear'; cb.style.margin = 'var(--cds-gap-sm) 0'; lw.before(cb); }
      if (cb) { cb.replaceChildren();
        if (cq.status === 'ok' && cq.data.length) { cb.classList.remove('dash-skeleton'); const R = Object.fromEntries(cq.data.map(r => [r.key, r])), A = R.avg, Q = R.clr, G = R.gone, ud = v => v == null ? '—' : v >= 0 ? `${f1(v)}% 위` : `${f1(-v)}% 아래`;
          const el = (t, c, x) => { const e = document.createElement(t); if (c) e.className = c; if (x != null) e.textContent = x; return e; };
          const tile = (key, lab, val, unit, sub) => { const d = el('div', 'rv-kpi'), v = el('span', 'rv-kpi-v'), nv = el('span', null, val); nv.dataset.source = 'credit_clear'; nv.dataset.field = 'value'; nv.dataset.where = 'key=' + key; v.appendChild(nv); if (unit) v.appendChild(el('span', 'rv-kpi-u', unit)); d.append(el('span', 'rv-kpi-l', lab), v, el('span', 'rv-kpi-l', sub)); return d; };
          cb.append(tile('avg', `신용 평균(1년 저점 ${md(A.lo_date)} 뒤 유입)`, A.value == null ? '—' : f0(A.value), '', `${md(A.last_date)} 종가는 ${ud(A.vs)} · 유입 ${f2(A.in_jo)}조원`),
            tile('clr', '해소 반영 평균(남은 신용)', Q.value == null ? '—' : f0(Q.value), '', `종가는 ${ud(Q.vs)} · 유입 ${f2(Q.in_jo)}조 중 ${f2(Q.out_jo)}조 정리, ${f2(Q.rem_jo)}조 남음 · 비싸게 산 것부터 정리 가정(먼저 산 것부터면 ${Q.alt == null ? '—' : f0(Q.alt)})`),
            tile('gone', `해소분(정점 ${md(G.peak_date)} 대비)`, f2(G.value), '조원', `${f2(G.peak_jo)}조 → ${f2(G.last_jo)}조(${pcs(G.pct)}, 신용 ${md(G.credit_date)}분) · 그사이 미수 반대매매 ${f2(G.misu_jo)}조원`));
        } else cb.classList.toggle('dash-skeleton', !BAD.includes(cq.status)); }
      // 신용 청산 참고선(참고 — 11/20부터 그래프에서 뺌)
      const cd = dash.data('credit_entry'), ct = document.getElementById('ce-tbl'), cs = document.getElementById('ce-sum');
      if (ct) { const tb = ct.tBodies[0]; tb.replaceChildren();
        if (cd.status === 'ok') { ct.classList.remove('dash-skeleton');
          cd.data.forEach(r => { const tr = document.createElement('tr'); tr.dataset.key = r.method;
            [[r.name, ''], [r.entry == null ? '—' : f0(r.entry), 'rv-num'], [r.l140 == null ? '—' : f0(r.l140), 'rv-num'], [r.l130 == null ? '—' : f0(r.l130), 'rv-num'], [r.l120 == null ? '—' : f0(r.l120), 'rv-num'], [r.text, '']]
              .forEach(([v, cls]) => { const td = document.createElement('td'); td.textContent = v; if (cls) td.className = cls; tr.appendChild(td); }); tb.appendChild(tr); });
          const r0 = cd.data[0];
          if (cs && r0 && r0.entry != null && r0.last_kospi != null) { const k = r0.last_kospi, pos = k > r0.l140 ? `140% 선(${f0(r0.l140)}) 위 — 최근 유입 계좌(자기자금 40%)는 아직 담보 부족 전` : k > r0.l130 ? `140% 선(${f0(r0.l140)})과 130% 선(${f0(r0.l130)}) 사이 — 완화된 130%가 지켜 주는 띠 안` : k > r0.l120 ? `130% 선(${f0(r0.l130)}) 아래·120% 선(${f0(r0.l120)}) 위 — 완화된 130%로도 보호되지 않고 신청 시 유예(120%)만 남은 구간` : `120% 선(${f0(r0.l120)})도 아래 — 유예 대상도 벗어난 구간`;
            cs.textContent = `${md(r0.last_date)} 종가 ${f2(k)}는 ${r0.basis || '최근 유입'} 기준(평균 매수 지수 ${f0(r0.entry)}, 신용 ${md(r0.credit_date || r0.last_date)}분까지 반영) ${pos}. 자기자금 50%면 140% 선 ${f0(r0.l140_50)}·130% 선 ${f0(r0.l130_50)}로 내려간다. 방법별 평균 매수 지수 ${cd.data.map(r => r.entry == null ? '—' : f0(r.entry)).join(' · ')} — 차이가 큰 것은 남은 신용이 언제 들어온 것인지 자료로 알 수 없어서다.`; }
        } else { ct.classList.toggle('dash-skeleton', !BAD.includes(cd.status)); if (cs) cs.textContent = ''; } }
    } catch (e) { console.error(e); }
  }
  // ---- 이번 갱신의 큰 변화(빨간색 띠, 11/14 추가): 자료가 갱신될 때마다 마지막 날 자료로 다시 계산해 맨 위에 적는다. 기준은 카카오톡 알림의 신호·특이 항목과 같고, 대시보드에서만 보는 항목(반대매매 비중·외국인 큰 매매·청산 참고선 통과)을 더했다
  function fillHot() {
    const root = document.querySelector('.rv'); if (!root) return;
    if (!document.getElementById('rv-hot-css')) { const st = document.createElement('style'); st.id = 'rv-hot-css';
      st.textContent = '.rv .rv-hot{color:#e5484d;font-weight:600}.rv #hot-box{border:1px solid #e5484d;border-radius:10px;padding:10px 12px;margin:0 0 12px}.rv #hot-box.calm{border-color:var(--color-border-line,#ccc)}.rv #hot-box h3{margin:0 0 4px;font-size:14px}.rv #hot-box ul{margin:0;padding-left:18px}.rv #hot-box li{margin:2px 0;font-size:13.5px}.rv #hot-box a{color:inherit;text-decoration:underline}.rv #hot-box .hot-sub{font-size:12px;opacity:.75;font-weight:400;color:var(--color-fg,inherit)}';
      document.head.appendChild(st); }
    const D = id => { try { const d = dash.data(id); return d.status === 'ok' ? d.data : []; } catch (e) { return []; } };
    const mk = D('market').filter(r => r.kospi !== '' && r.kospi != null); if (!mk.length) return;
    const last = mk[mk.length - 1], prev = mk[mk.length - 2], day = String(last.date);
    const n = v => v === '' || v == null || isNaN(+v) ? null : +v, md = s => +String(s).slice(5, 7) + '/' + +String(s).slice(8, 10);
    const sg = (v, d = 1) => (v >= 0 ? '+' : '−') + Math.abs(v).toFixed(d), f0 = v => Math.round(v).toLocaleString('en-US');
    const jo = v => (v >= 0 ? '+' : '−') + (Math.abs(v) >= 1 ? Math.abs(v).toFixed(1) + '조' : f0(Math.abs(v) * 10000) + '억');
    const items = [];   // [글, 설명, 이동할 칸]
    D('health').forEach(r => { const st = String(r.status);   // 자료 점검(11/15 추가): 오류·정정은 맨 앞에 — 값이 틀리거나 멈춘 채 조용히 넘어가지 않게
      if (st === '오류') items.push([`자료 오류: ${r.name}`, String(r.note || '').slice(0, 100), '#health']); else if (st === '정정') items.push([`정정: ${r.name}`, String(r.note || '').slice(0, 120), '#health']); });
    ['alarms', 'buy3', 'sell3'].forEach(id => D(id).forEach(r => { if (String(r.date) === day && String(r.start) === '시작') items.push([`${r.side} 신호 시작: ${r.type}`, String(r.rule || '').slice(0, 60), '#all']); }));
    const re = D('reentry'); if (re.length && String(re[re.length - 1].date) === day) items.push([`재진입 규칙: ${re[re.length - 1].action}`, String(re[re.length - 1].reason || ''), '#all']);
    const q = D('q_daily'), ql = q[q.length - 1], qp = q[q.length - 2];
    if (ql && String(ql.date) === day) {
      // 정밀 검증 전략 진입·청산은 큰 변화에서 뺐다(11/15: 검증에서 도움이 안 됨)
      if (qp && String(qp.regime) !== String(ql.regime)) items.push([`국면 ${qp.regime} → ${ql.regime}`, '시장 상태 판정이 바뀜', '#qtop']); }
    const chg = n(last.kospi_chg_pct); if (chg != null && Math.abs(chg) >= 3) items.push([`코스피 ${sg(chg, 2)}%`, '하루 3% 넘는 ' + (chg > 0 ? '급등' : '급락'), '#all']);
    const cr = D('credit'), cl = cr[cr.length - 1]; if (cl && n(cl.chg_pct) != null && Math.abs(n(cl.chg_pct)) >= 3) items.push([`신용잔고 하루 ${sg(n(cl.chg_pct))}% (${md(cl.date)}분 ${n(cl.credit_jo).toFixed(1)}조)`, n(cl.chg_pct) > 0 ? '급증: 빚투 확대' : '급감: 상환·청산', '#all']);
    const lq = D('liq'), ll = lq[lq.length - 1]; if (ll && n(ll.ratio_pct) != null && n(ll.ratio_pct) >= 5) items.push([`반대매매 비중 ${n(ll.ratio_pct).toFixed(1)}% (${md(ll.date)}분 ${f0(n(ll.liq_eok))}억)`, '미수금의 5% 넘게 강제 청산', '#all']);
    const fl = D('flows_daily'), fr = fl[fl.length - 1]; if (fr && String(fr.date) === day && n(fr.foreign_jo) != null && Math.abs(n(fr.foreign_jo)) >= 2) items.push([`외국인 ${jo(n(fr.foreign_jo))}`, '하루 2조 원 넘는 ' + (n(fr.foreign_jo) > 0 ? '순매수' : '순매도'), '#all']);
    D('liq_lines').forEach(r => { const vL = n(r.line_last), vP = n(r.line_prev), a = n(r.prev_kospi), b = n(r.last_kospi); if (vL == null || vP == null || a == null || b == null) return;   // 11/20: 검증한 반대매매 기준선으로 바꿈(예전 신용 청산 140·130·120% 선은 청산 예측력이 약해 뺌)
      if (a >= vP && b < vL) items.push([`코스피가 반대매매 ${r.tier}(${r.rule}) ${f0(vL)} 아래로`, `과거 이 선 아래에서 사흘 안 신용 청산 물결 ${f1(n(r.p_dev))}~${f1(n(r.p_test))}%(평소 8~9%)`, '#relief']);
      if (a < vP && b >= vL) items.push([`코스피가 반대매매 ${r.tier} ${f0(vL)} 위로 회복`, '청산 압력 완화', '#relief']); });
    const fpd = D('fpanic'); if (fpd.length >= 2) { const f1 = fpd[fpd.length - 1], f0p = fpd[fpd.length - 2]; if (String(f1.date) === day && +f1.on === 1 && +f0p.on === 0) items.push([`외국인 투매·개인 매수 신호 켜짐(조합 10개 중 ${f1.n10}개)`, '켜진 뒤 10일 상승: 검증 81%(아무 날 54%), 표본 10번', '#fpanic']); }
    const cb = D('combo'); const cn = D('combo_now')[0] || (cb.length ? cb[cb.length - 1] : null); if (cn && cn.warn) items.push(['조합 1위 경고', String(cn.warn).slice(0, 60), '#all']);
    const box = placeTop(); if (!box) return;
    box.className = items.length ? '' : 'calm'; box.replaceChildren();
    const h = document.createElement('h3'); h.textContent = `이번 갱신의 큰 변화 (${md(day)} 기준)`; if (items.length) h.className = 'rv-hot'; box.appendChild(h);
    if (!items.length) { const p = document.createElement('div'); p.className = 'hot-sub'; p.textContent = '큰 변화 없음 — 새 매수·매도 신호, 코스피·신용 하루 3% 이상 변동, 반대매매 비중 5% 이상, 외국인 2조 원 이상 매매, 반대매매 기준선 통과, 국면 변경이 없었습니다.'; box.appendChild(p); return; }
    const ul = document.createElement('ul'); items.forEach(([t, why, href]) => { const li = document.createElement('li'); li.className = 'rv-hot'; const a = document.createElement('a'); a.href = href; a.textContent = t; li.appendChild(a);
      if (why) { const s = document.createElement('span'); s.className = 'hot-sub'; s.textContent = ' — ' + why; li.appendChild(s); } ul.appendChild(li); }); box.appendChild(ul);
  }
  // 화면 순서(11/14): 제목 → 이번 갱신의 큰 변화 → 한눈에 보기 그래프 → 머리말 설명 → 나머지. index.html 은 그대로 두고 여기서 자리를 옮긴다(그래프·단추는 옮겨도 그대로 동작)
  function placeTop() {
    const root = document.querySelector('.rv'); if (!root) return null;
    let box = document.getElementById('hot-box'); if (!box) { box = document.createElement('div'); box.id = 'hot-box'; box.className = 'calm'; }
    const head = root.querySelector('header.rv-head'), all = document.getElementById('all');
    if (head && !document.getElementById('top-notes')) { const notes = document.createElement('div'); notes.className = 'rv-head'; notes.id = 'top-notes';
      Array.from(head.children).forEach(c => { if (c.tagName !== 'H1') notes.appendChild(c); }); head.after(notes); }
    if (head) { if (box.previousElementSibling !== head) head.after(box); } else if (root.firstElementChild !== box) root.prepend(box);
    if (all && box.nextElementSibling !== all) box.after(all);
    // 매일 볼 필요가 없는 설명은 접어 둔다(11/14): 그래프 보는 법은 그래프 바로 아래, 머리말 설명은 기준일 줄 아래에 '펼치기'로
    const foldInto = (id, label, nodes, place) => { let d = document.getElementById(id);
      if (!d) { d = document.createElement('details'); d.className = 'rv-more'; d.id = id; const sm = document.createElement('summary'); sm.textContent = label; d.appendChild(sm); place(d); }
      nodes.filter(Boolean).forEach(n => { if (n.parentNode !== d) d.appendChild(n); }); };
    const ch = document.getElementById('all-chart');
    if (all && ch) { const tb = document.getElementById('sig-tbl'), tw = tb && tb.closest('.rv-tbl-wrap'), nx = tw && tw.nextElementSibling, tnote = nx && nx.matches('p.rv-note:not([id])') ? nx : null;
      foldInto('all-help', '그래프 보는 법 · 신호 표시 설명 (펼치기)', [all.querySelector('.rv-all-head p.rv-note'), document.getElementById('all-ovnote'), document.getElementById('all-alnote'), tnote], d => ch.after(d)); }
    const notes = document.getElementById('top-notes');
    if (notes) foldInto('top-help', '대시보드 설명 · 자료 기준 (펼치기)', Array.from(notes.children).filter(c => c.id !== 'asof-auto' && c.id !== 'top-help' && c.id !== 'health'), d => notes.appendChild(d));
    return box;
  }
  try { placeTop(); } catch (e) { console.error(e); }
  // ---- 외국인 투매·개인 매수 신호 카드(11/15 추가): 자료 fpanic_now·fpanic_eps·fpanic(pkg/fpanic.py). 한눈에 보기 그래프 바로 아래에 놓는다
  function fillPanic() {
    const D = id => { try { const d = dash.data(id); return d.status === 'ok' ? d.data : null; } catch (e) { return null; } };
    const now = D('fpanic_now'), eps = D('fpanic_eps'); if (!now || !now.length) return;
    const all = document.getElementById('all'); if (!all) return;
    let sec = document.getElementById('fpanic'); if (!sec) { sec = document.createElement('section'); sec.id = 'fpanic'; all.after(sec); }
    const el = (t, cls, txt) => { const e = document.createElement(t); if (cls) e.className = cls; if (txt != null) e.textContent = txt; return e; };
    const get = k => now.find(r => String(r.item) === k) || {}, on = +get('상태').value === 1;
    const card = el('div', 'rv-card'); const h = el('h3', null, '외국인 투매·개인 매수 신호 '); const pill = el('span', on ? 'rv-hot' : null, on ? '● 켜짐' : '○ 꺼짐'); if (!on) pill.style.opacity = '.6'; h.appendChild(pill); card.appendChild(h);
    card.appendChild(el('p', 'rv-note', String(get('상태').text || '') + ' · 크게 빠진 시장에서 외국인이 60일 내내 극단적으로 팔 때 켜지는 매수 쪽 신호(켜진 뒤 10~15거래일 안의 반등을 본다).'));
    const ul = el('ul'); ul.style.margin = '4px 0 8px'; ul.style.paddingLeft = '18px';
    now.filter(r => String(r.item).startsWith('핵심 조건')).forEach(r => { const li = el('li', null, String(r.text)); li.style.fontSize = '13.5px'; if (/— 아님$/.test(String(r.text))) li.style.opacity = '.65'; ul.appendChild(li); }); card.appendChild(ul);
    const mkTbl = (heads, rows) => { const w = el('div', 'rv-tbl-wrap'), t = el('table', 'rv-tbl'), th = el('thead'), trh = el('tr'); heads.forEach(x => trh.appendChild(el('th', null, x))); th.appendChild(trh); t.appendChild(th);
      const tb = el('tbody'); rows.forEach(r => { const tr = el('tr'); r.forEach(x => tr.appendChild(el('td', null, x))); tb.appendChild(tr); }); t.appendChild(tb); w.appendChild(t); return w; };
    card.appendChild(mkTbl(['검증(해마다 그 전 자료로 고른 조합)', '성적'], now.filter(r => String(r.item).startsWith('검증')).map(r => [String(r.item).replace('검증 ', ''), String(r.text)])));
    if (eps && eps.length) { const rows = eps.slice().reverse().map(e => [`${e.start} ~ ${String(e.end).slice(5)}`, e.days + '일', Math.round(+e.kospi).toLocaleString('en-US'), `${e.up10}` + (e.avg10 !== '' && e.avg10 != null ? ` · ${(+e.avg10 >= 0 ? '+' : '−') + Math.abs(+e.avg10).toFixed(1)}%` : ''), `${e.up20}` + (e.avg20 !== '' && e.avg20 != null ? ` · ${(+e.avg20 >= 0 ? '+' : '−') + Math.abs(+e.avg20).toFixed(1)}%` : ''), String(e.status)]);
      const d = el('details', 'rv-more'); d.appendChild(el('summary', null, `켜졌던 ${eps.length}번의 기록 (펼치기)`)); d.appendChild(mkTbl(['기간', '일수', '첫날 코스피', '10일 뒤 상승·평균', '20일 뒤 상승·평균', '상태'], rows)); card.appendChild(d); }
    const d2 = el('details', 'rv-more'); d2.appendChild(el('summary', null, '읽는 법 · 조합 조건 (펼치기)')); ['읽는 법', '조합'].forEach(k => { if (get(k).text) d2.appendChild(el('p', 'rv-note', String(get(k).text))); });
    d2.appendChild(el('p', 'rv-note', '조건의 pNN은 최근 3년(750거래일) 안에서 오늘 값의 백분위. 해마다 그 전 자료만으로 3조건 조합 1억 3,148만 개를 채점해 고른 4조건 상위 10개 중 하나라도 켜지면 신호다. 투자 권유가 아니다.')); card.appendChild(d2);
    sec.replaceChildren(card);
  }
  // ---- 자료 상태 칸(11/15 추가): 자료 health(health_check.py 가 매 실행 끝에 씀). 기준일 줄 바로 아래 접힌 칸 — 오류·정정이 있으면 빨간 제목으로 펼쳐 둔다
  //      11/15 전에는 VIX 가 2주 동안 틀린 값으로 굳고 야간선물이 18일 끊겨도 화면·알림 어디에도 드러나지 않았다
  function fillHealth() {
    let H = null; try { const d = dash.data('health'); H = d.status === 'ok' ? d.data : null; } catch (e) { H = null; }
    if (!H || !H.length) return;
    const root = document.querySelector('.rv'); if (!root) return; placeTop();
    const notes = document.getElementById('top-notes');
    let box = document.getElementById('health');
    if (!box) { box = document.createElement('details'); box.className = 'rv-more'; box.id = 'health'; const help = document.getElementById('top-help');
      if (notes) { if (help && help.parentNode === notes) notes.insertBefore(box, help); else notes.appendChild(box); } else root.appendChild(box); }
    const el = (t, cls, txt) => { const e = document.createElement(t); if (cls) e.className = cls; if (txt != null) e.textContent = txt; return e; };
    const cnt = k => H.filter(r => String(r.status) === k).length, bad = cnt('오류'), fix = cnt('정정'), warn = cnt('주의');
    const md = v => { const t = String(v || ''); return /^\d{4}-\d\d-\d\d/.test(t) ? (+t.slice(5, 7)) + '/' + (+t.slice(8, 10)) : (t || '—'); };
    const at = String(H[0].checked_at || '');
    const head = '자료 상태: ' + [bad ? `오류 ${bad}건` : '', fix ? `정정 ${fix}건` : '', warn ? `주의 ${warn}건` : '', `정상 ${cnt('정상')}개`].filter(Boolean).join(' · ') + (at ? ` (점검 ${md(at)} ${at.slice(11, 16)})` : '') + ' — 펼치기';
    const sm = el('summary', (bad || fix) ? 'rv-hot' : null, head); if (bad || fix) { sm.style.color = '#e5484d'; sm.style.fontWeight = '600'; }   // 접힌 칸 제목의 기본 색 규칙이 더 세므로 색을 직접 준다(11/15)
    const w = el('div', 'rv-tbl-wrap'), t = el('table', 'rv-tbl'), th = el('thead'), trh = el('tr'); ['자료', '마지막', '와 있어야 할 날', '상태', '설명'].forEach(x => trh.appendChild(el('th', null, x))); th.appendChild(trh); t.appendChild(th);
    const tb = el('tbody'); H.forEach(r => { const tr = el('tr'), st = String(r.status);
      tr.appendChild(el('td', null, String(r.name))); tr.appendChild(el('td', null, md(r.last))); tr.appendChild(el('td', null, md(r.expected)));
      const c = el('td', (st === '오류' || st === '정정') ? 'rv-hot' : null, st); if (st === '주의') c.style.fontWeight = '600'; tr.appendChild(c);
      const n = el('td', null, String(r.note || '')); n.style.whiteSpace = 'normal'; n.style.minWidth = '220px'; n.style.textAlign = 'left'; tr.appendChild(n); tb.appendChild(tr); });
    t.appendChild(tb); w.appendChild(t);
    const note = el('p', 'rv-note', '매 실행 끝에 자료마다 지금쯤 와 있어야 할 날짜까지 왔는지, 출처끼리 값이 맞는지(코스피 종가 ↔ 네이버·다음, VIX ↔ CBOE 공식 파일, 야간선물 ↔ 공개 출처, VKOSPI 화면 ↔ Open API), 수집 항목이 실패했는지 점검한다. 오류 = 멈춤·불일치, 정정 = 과거 값이 고쳐졌거나 이미 알린 신호가 취소됨, 주의 = 하루 늦음·예비 출처 사용. 알림의 「자료:」 줄이 이 결과다.');
    box.replaceChildren(sm, w, note); if (bad || fix) box.open = true;
  }
  // ---- 수기 결론 카드가 멈춰 있으면 알린다(11/15 추가): 카드 기준일(「아래 네 카드는 M/D 장 마감 …」) 뒤로 종가가 2거래일 넘게 쌓였으면 아침 갱신이 이 화면에 오지 않은 것
  //      11/12~13 웹판에는 11/10 기준 카드가 그대로 있었는데 화면 어디에도 표시가 없었다. 1거래일 차이는 정상(카드는 다음 거래일 아침 09시에 쓴다)
  function fillStale() {
    const sec = document.getElementById('concl'), note = document.querySelector('#concl-auto p.rv-note'); if (!sec || !note) return;
    const m = /아래 네 카드는\s*(\d{1,2})\/(\d{1,2})\s*장 마감/.exec(note.textContent || ''); if (!m) return;
    let mk = null; try { const d = dash.data('market'); mk = d.status === 'ok' ? d.data : null; } catch (e) { mk = null; } if (!mk) return;
    const days = mk.filter(r => r.kospi !== '' && r.kospi != null).map(r => String(r.date).slice(0, 10)); if (!days.length) return;
    const last = days[days.length - 1], p2 = v => String(+v).padStart(2, '0'), md = s => +s.slice(5, 7) + '/' + +s.slice(8, 10);
    let base = last.slice(0, 4) + '-' + p2(m[1]) + '-' + p2(m[2]); if (base > last) base = (+last.slice(0, 4) - 1) + '-' + p2(m[1]) + '-' + p2(m[2]);   // 해가 바뀐 직후
    const after = days.filter(d => d > base); let el = document.getElementById('concl-stale'), old = document.getElementById('concl-old');
    const grid = sec.querySelector('.rv-concl'), cards = () => Array.from(sec.querySelectorAll('.rv-card')).filter(c => c.id !== 'concl-auto');
    if (after.length < 2) { if (el) el.remove(); if (old && grid) { cards().forEach(c => grid.appendChild(c)); old.remove(); } return; }
    if (!el) { el = document.createElement('p'); el.id = 'concl-stale'; el.className = 'rv-note rv-hot'; el.style.color = '#e5484d'; el.style.fontWeight = '600'; if (grid) sec.insertBefore(el, grid); else sec.appendChild(el); }
    el.textContent = `수기 카드 네 장은 ${md(base)} 장 마감 기준에서 멈춰 있다 — 그 뒤 ${after.length}거래일(${md(after[0])}~${md(after[after.length - 1])}) 자료는 카드에 반영되지 않았다(아침 갱신이 이 화면에 오지 않음). 오래된 카드는 아래에 접어 두었다. 첫 카드(자동)와 맨 위 「이번 갱신의 큰 변화」는 최신 자료 기준이다.`;
    // 오래된 수기 카드는 접어 둔다(지금 분석처럼 읽히지 않게). 새 카드가 오면 위에서 다시 펼쳐 놓는다
    if (!old && grid) { old = document.createElement('details'); old.className = 'rv-more'; old.id = 'concl-old'; old.appendChild(document.createElement('summary')); const g2 = document.createElement('div'); g2.className = 'rv-concl'; old.appendChild(g2); cards().forEach(c => g2.appendChild(c)); grid.after(old); }
    if (old) old.querySelector('summary').textContent = `${md(base)} 장 마감 기준 수기 카드 4장(오래됨 — 펼치기)`;
  }
  window.fillRelief = () => { try { fillRelief(); } finally { try { fillHot(); } catch (e) { console.error(e); } try { fillPanic(); } catch (e) { console.error(e); } try { fillHealth(); } catch (e) { console.error(e); } try { fillStale(); } catch (e) { console.error(e); } } };   // index.html 의 dash.onData 콜백이 부른다(스크립트끼리는 window 로만 공유)
})();
