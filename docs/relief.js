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
  const LL_NOTE = '1선 = 직전 60거래일 최저 종가 +1%, 2선 = 그 최저 종가(새 저점), 3선 = 그 최저 종가 −2%. 종가가 이 선을 깨면 그 뒤 사흘 안에 신용 강제 청산(코스피 신용잔고 3일 −2% 이상 감소 = 청산 물결)이 몰렸다. 후보 168개(직전 저점 창 5~250일·문턱 +2~−10%, 고점 대비 낙폭, 아래 신용 평균 매수 지수 선 방법별, 비례 상환 분포선)를 2016~2022년 자료로 미리 정한 규칙(신용·미수 청산 물결 맞힘 순위)대로 고르고 2023~2026년에 확인했다(2026-11-20). 새 저점이 생기면 선이 따라 내려가 이미 청산된 물량이 저절로 빠진다. 평소(아무 날) 청산 물결은 2016~2022년 8.4%·2023~2026년 8.8%, 사흘 신용 변화 평균 +0.2%·+0.3%. 선 아래에 머문 날은 날마다 셌고 이탈 구간 = 처음 깬 횟수, 3선은 표본이 적다(11·8구간). 아래 표 첫 줄의 담보비율 140% 선은 같은 검증에서 청산 물결의 15%(2016~2022)·10%(2023~2026)만 그 선 아래에서 일어나(1선은 54%·40%) 그래프에서 뺐다. 미수 반대매매는 지수 수준과 상관없이 결제일(T+2)에 정리되므로 따로 급락 이틀 뒤를 본다. 지수 기준이라 신용이 몰린 종목은 더 먼저 걸린다. 한눈에 보기 그래프 코스피 칸의 세 선(1선 점선 · 2선 실선 · 3선 촘촘한 점선)이 날마다의 기준선이다. 표 위 칸 셋은 신용 평균(1년 저점 뒤 늘어난 신용을 그날 종가로 가중한 평균)·해소 반영 평균(줄어든 만큼을 비싸게 산 신용부터 뺀 남은 신용의 평균)·정점 대비 해소분이고, 그래프의 파란 점선은 날마다의 해소 반영 평균이고, 신용 평균은 선 없이 오른쪽 글자로만 보인다. 신용 강제 청산 금액은 따로 공시되지 않아 상환과 구분하지 못하는 추정값이다. 참고용이지 추천이 아니다.';
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
  // 2026-11-22 추가: 연구소 통과 신호를 한눈에 보기 그래프 코스피 선 위에 그린다(사용자 요청). index.html 의 그래프 코드가 부른다.
  //   원 = 조건이 뜬 날(장 마감 뒤 확정), 아래 반원 = 매수일(시가), 위 반원 = 매도일(종가). 자료: lab_sig(연구소 deriv/lab/signals/passed_signals.csv).
  window.rvLabSig = (svg, xd, P0, mk) => {
    const g = dash.data('lab_sig'); if (g.status !== 'ok' || !Array.isArray(g.data) || !g.data.length) return;
    const ks = new Map(mk.filter(r => num(r.kospi) != null).map(r => [String(r.date).slice(0, 10), num(r.kospi)]));
    const COL = '#8e24aa', R = 6, all = [], OFF = window.__rvLabOff || (window.__rvLabOff = new Set());   // OFF = 범례에서 끈 표시(c 조건일 · b 매수일 · s 매도일)
    g.data.forEach(r => [['cond', 'c'], ['buy', 'b'], ['sell', 's']].forEach(([k, t]) => { const d = String(r[k] || '').slice(0, 10); if (ks.has(d) && isFinite(xd(d))) all.push({d, t, k: ks.get(d), r}); }));
    const pts = all.filter(p => !OFF.has(p.t));
    const tip = p => (p.t === 'c' ? '연구소 신호 조건일' : p.t === 'b' ? '연구소 신호 매수일(시가)' : '연구소 신호 매도일(종가)') + ' ' + md(p.d) + ' · 조건 ' + md(p.r.cond) + ' → 매수 ' + md(p.r.buy) + ' → 매도 ' + md(p.r.sell)
      + (num(p.r.ret_pct) != null ? ' · 선물 ' + (num(p.r.ret_pct) > 0 ? '+' : '') + f2(num(p.r.ret_pct)) + '%' : ' · ' + (p.r.status || ''));
    const gg = svg.append('g').attr('class', 'rv-labsig');
    gg.selectAll('circle').data(pts.filter(p => p.t === 'c')).join('circle').attr('cx', p => xd(p.d)).attr('cy', p => P0.yL(p.k)).attr('r', R)
      .style('fill', 'none').style('stroke', COL).style('stroke-width', '2px').append('title').text(tip);
    gg.selectAll('path').data(pts.filter(p => p.t !== 'c')).join('path').attr('d', p => p.t === 'b' ? `M${-R},0A${R},${R} 0 0 0 ${R},0Z` : `M${-R},0A${R},${R} 0 0 1 ${R},0Z`)
      .attr('transform', p => `translate(${xd(p.d)},${P0.yL(p.k) + (p.t === 'b' ? 4 : -4)})`).style('fill', COL).style('stroke', 'var(--color-panel)').style('stroke-width', '1px').append('title').text(tip);
    // 2026-11-23: 보이는 기간에 연구소 신호가 없으면 그래프에 아무것도 안 보여 '표시가 안 된다'로 읽힌다 → 범례 아래 한 줄로 알리고(휴대폰에서 범례를 접어도 보임), 가장 최근 신호로 옮겨 가는 단추를 둔다
    { const host = document.getElementById('all-legend') || document.getElementById('all-chart'); let nt = document.getElementById('all-labnote');
      if (host && !nt) { nt = document.createElement('p'); nt.id = 'all-labnote'; nt.className = 'rv-note'; if (host.id === 'all-legend') host.after(nt); else host.before(nt); }   // 범례 바로 아래(접히는 설명 상자 밖)
      if (nt) { const lastR = g.data.slice().sort((p, q) => String(p.cond).localeCompare(String(q.cond))).pop(), lc = String(lastR.cond).slice(0, 10);
        const nVis = new Set(all.map(p => p.r.cond)).size, yy = d => String(d || '').slice(2, 4) + '년 ';
        const desc = r => yy(r.cond) + md(r.cond) + ' 조건 → ' + md(r.buy) + ' 매수 → ' + md(r.sell) + ' 매도' + (num(r.ret_pct) != null ? '(선물 ' + (num(r.ret_pct) > 0 ? '+' : '') + f2(num(r.ret_pct)) + '%)' : '(' + (r.status || '') + ')');
        const dot = document.createElement('b'); dot.textContent = '연구소 신호'; dot.style.color = COL;
        nt.replaceChildren(dot, document.createTextNode('(보라색 · 원 = 조건일, 아래 반원 = 매수일, 위 반원 = 매도일): ' + (nVis ? '보이는 기간에 ' + nVis + '건' : '보이는 기간에는 없음') + ' · 가장 최근 ' + desc(lastR) + ' '));
        const box = document.getElementById('all-chart'), api = box && box._rvApi;
        if (!nVis && api && api.days && api.idx && api.set && api.days().indexOf(lc) >= 0) {
          const bt = document.createElement('button'); bt.type = 'button'; bt.className = 'rv-lgbtn'; bt.textContent = '그 신호 보기'; bt.style.color = COL; bt.style.textDecoration = 'underline'; bt.style.fontWeight = '600';
          bt.addEventListener('click', () => { const dd = api.days(), ci = dd.indexOf(lc); if (ci < 0) return; const i1 = api.idx(dd)[1], s = Math.max(0, ci - 10); api.set(s, Math.max(10, i1 - s + 1)); });
          nt.appendChild(bt); } } }
    // 범례는 그래프 안 글자 대신 그래프 위 다른 신호 범례 줄(#all-legend)에 둔다(11/22 사용자 요청). 누르면 그 표시만 끄고 켠다
    const lgEl = document.getElementById('all-legend');
    if (lgEl) {   // 자료가 있으면 보이는 기간에 신호가 없어도 범례는 늘 둔다(다른 신호와 같게)
      const ref = Array.from(lgEl.children).find(e => /^미수 반대매매\(막대\)/.test(e.textContent || '')) || null;
      [['c', '연구소 조건일(원)'], ['b', '연구소 매수일(아래 반원)'], ['s', '연구소 매도일(위 반원)']].forEach(([t, lab]) => {
        const bt = document.createElement('button'); bt.type = 'button'; bt.className = 'rv-lgbtn'; bt.setAttribute('aria-pressed', String(!OFF.has(t)));
        const sw = document.createElement('i'); sw.className = 'rv-sw';
        if (t === 'c') { sw.style.background = 'transparent'; sw.style.border = '2px solid ' + COL; sw.style.borderRadius = '50%'; sw.style.boxSizing = 'border-box'; }
        else { sw.style.background = COL; sw.style.width = '.75rem'; sw.style.height = '.375rem'; sw.style.borderRadius = t === 'b' ? '0 0 .375rem .375rem' : '.375rem .375rem 0 0'; }
        bt.append(sw, document.createTextNode(lab));
        bt.addEventListener('click', () => { OFF.has(t) ? OFF.delete(t) : OFF.add(t); const box = document.getElementById('all-chart'); if (box && box._rvApi && box._rvApi.draw) box._rvApi.draw(); });
        lgEl.insertBefore(bt, ref);
      });
    }
  };
  // 전진 성적표(2026-11-23): 알림으로 나간 신호의 그 뒤 성적. 자료: fwd(forward_score.py) — 합계 줄(kind sum)은 요약 문장, 나머지는 표
  const fillFwd = () => {
    const t = document.getElementById('fwd-tbl'), s = document.getElementById('fwd-sum'); if (!t) return;
    let d; try { d = dash.data('fwd'); } catch (e) { return; } if (!d || d.status !== 'ok' || !Array.isArray(d.data)) return;
    const tb = t.tBodies[0]; tb.replaceChildren();
    const no = v => v === '' || v == null, pc = v => (+v > 0 ? '+' : '') + (+v).toFixed(2) + '%';
    const cell = (r, h) => (no(r['r' + h]) ? '' : pc(r['r' + h]) + ' ') + (r['h' + h] || '');
    const sums = d.data.filter(r => r.kind === 'sum'), rows = d.data.filter(r => r.kind === 'row');
    if (s) s.textContent = sums.length ? sums.map(r => `${r.group}: ${r.status} · 5일 뒤 ${r.h5}${no(r.r5) ? '' : '(평균 ' + pc(r.r5) + ')'} · 10일 뒤 ${r.h10}${no(r.r10) ? '' : '(평균 ' + pc(r.r10) + ')'} · 20일 뒤 ${r.h20}`).join(' / ') : '아직 채점된 신호가 없습니다.';
    rows.forEach(r => { const tr = document.createElement('tr'); tr.dataset.key = r.key; if (String(r.status || '').startsWith('취소')) tr.style.opacity = '.55';
      [[r.date, ''], [r.label, ''], [r.status || '', ''], [(r.entry_date ? String(r.entry_date).slice(5).replace('-', '/') + ' ' : '') + (no(r.entry) ? '' : (+r.entry).toLocaleString('ko-KR', {maximumFractionDigits: 2})), 'rv-num'], [cell(r, 5), 'rv-num'], [cell(r, 10), 'rv-num'], [cell(r, 20), 'rv-num']]
        .forEach(([x, c]) => { const td = document.createElement('td'); td.textContent = x; if (c) td.className = c; tr.appendChild(td); });
      tb.appendChild(tr); });
  };
  window.fillRelief = () => { try { fillRelief(); } finally { try { fillFwd(); } catch (e) { console.error(e); } try { fillHot(); } catch (e) { console.error(e); } try { fillPanic(); } catch (e) { console.error(e); } try { fillHealth(); } catch (e) { console.error(e); } try { fillStale(); } catch (e) { console.error(e); } } };   // index.html 의 dash.onData 콜백이 부른다(스크립트끼리는 window 로만 공유)
})();

/* ==== 임시(2026-11-24) 전환 신호 단계 표시 시작 — 사용자가 확인한 뒤 제거할 예정. 이 주석부터 '임시 전환 신호 끝' 주석까지만 지우면 원래대로 돌아간다 ==== */
(() => {
  // 자료(고정): 해(두 자리)마다 한 줄. 신호 = 3글자씩(그 해의 몇 번째 날 36진 2글자 + 상태 1글자: 단계×3 + 맞음 1·모름 2), L·H = 맞음 판정에 쓴 저점·고점(그리지 않음, 자료 확인 합계에만 씀) 2글자씩
  const T = {made: '2026-11-20', kb: 6, nb: 8, ks: 5, ns: 8, sum: 43730274,
    L: {15:'6k',16:'0k4w',17:'67',18:'148e',19:'031v4569',20:'0v1n272b4n6h7g8g',21:'0i0t1x7x9a',22:'0r577l',23:'03218g',24:'0h3262738v9k',25:'1r2r8n91',26:'0x111r1w2i3w4f4u535e5l5v636f6t768b8p'},
    H: {15:'358j',16:'34',17:'5p',18:'0t229d',19:'1k2y4y',20:'0m191t284d6a777y',21:'0b0p1b4w92a2',22:'156c8r',23:'0r5x',24:'022l5d6h7i96',25:'1e288j8t',26:'0u0z1l1t253q484t4w545g5o616a6h707e8d8r'},
    bn: {15:'0500660760g60k00n00s00u04m05035105705965a65b36g76h76ka6l66m66n36o36r36s66t36u06v36y36z07007107207537607707837937e07f07g37l0',16:'0400660760800b30c30d30e90fa0i70j10ka0l90m30p60q60r30s00x01001631731a01b04w14z08k38l3',17:'2s02t02u02w32z066467a6a06d36e36h36i09a09b09g0',18:'0x310611712a13a14a1791891991e61f91g61h61i01l01m31n61p31s61t02102202602932a62d02e32f62g32h02k62l62m92n32o92r32s32t32u33604w04x04y34z65305435535607v07w97x980981982383984387388989a8aa8ba8ea8f98g68h68i08l38m08t38u69039h09k09l09y3a03a11',19:'0270373p93q04516106236816a06m0',20:'0va0y01g31j91ka1la1ma1na1q91r91s31t31u61x91y61z920921924a25a26a27a2872ba2c62d62e62f62i62j62k62l62m62p02q02s02t02w02x02z03003303403508g48j0',21:'9a1',22:'0i00j00k00l00o70p70q70ra0s30y30z01231531631961a91b01c31d31g31h31i01j31k01n31p01q31r31u61v61x61y62192292362433763803933f03l33n03o63u03w04004k94l94m94n94o94r94s64t94u64y04z05035195245545747b07c07e07h97ia7ja7ka7s07w37x07y37z6823833840850',23:'8408508808a38b78c48f48g4',24:'2z43073143273805q05r65s05w35z762a6366436566666966a36y18808a08h68i38l08m39k19u0',25:'1n11r41x01y32002102f02i62j02k32l62m72pa2qa2r12s62t62w32x02y62z03003303433508108x08y48z490a91a943953960970',26:'1041q71s41t41wa1x61y01z92092362462532632762a92b92c92da2ea2ha2i72j02k62l62o02p04c14g04h34i04u45015245315405705e15g15h15l15n05o05p05s45ua5z08f08i08j08l18m48p18w58x58y58z2902'},
    sn: {15:'1702303q07607s08w39439p0',16:'0e60m01761a01b61c31d01h31j01z32602a02h02x32y03213503903t64h04i35k05m35n05o05s35t06206836936d36e06k07007407j07l08s08w09i09j39k09n39o69p39q39r39v6',17:'0300600w03704f04g05f07x08h08j08p0',18:'1401701v01w32u02z03m63n03q07437507b08o09819d1',19:'0u01931a02u12y12z03l03m03q04p04r06436906c06f06v06w07237707807907a07b07e07f07g08a08u38v68y68z69009509l09m69n39q39r39s39t39u3a10',20:'0200700930a00d00g020021624025a26427a2872b92c62w02x03r03v33x34b14d15b05v06916a46b36f07217677747u77y48t68u38x39f0',21:'0400500740870e60f00j30k40l10m10p10q01511a71b11c01y61z02232q03q0',22:'1x33o03p33t04304934g05f05g35k066167768a6c46d06e06f06l07y08q48r48v09a09i39j09m39n09o09p0',23:'0p10q40r10x01431531802102302g02v62w02z03003103203n64f04g04j35e65f05i36606706a36c07537637908p08q68u39009o69p09s39u09v3a04a14a21',24:'0801301932602832932a02d02u03r04l04p34x35735a15c15d46596667407537b38v38w38z09o09r39y0',25:'0f00h01831911c11d11e41f02102b02t03k33l03o63p33q03s04334504b04c34g34h34i04j34k04n64o04u04v64w05305405b35f05g05h05i07967n37v37y38038108208598608738868998c98d08e48f18g18j48k08l08q18t78u38x38y38z09l0',26:'0230500660800990c60d60e60f60g60j60k30l90m30n30q30ra0sa0t70u10y10z41761861e61f91i71ja1k71l71m32342c02i02r32s32v02w02z33433633903a03b33c63g63i93j63k93na3o43pa3q73r33u33v03w63x33y64294374474574844994b64f34i34m34n04o74pa4q44ta4w15005115a35e45f45h05m45p05s05v0601694810840'},
    bw: {16:'0k10m00q0',17:'2t02u06716w06x39a09b39g69h69i69l09m69n0a10',18:'1001141241371471761831901e01f31g31h31i31m31n31p31s31t31u01v03603704l04m34p34q04s04z35005335435535635735a05b05c05d35e05h05i05j05k05l05o05p05q06936a06c36d06g07w37x08008108208308408808948a48b48e48f38g38h38l08n08t08u0',19:'6136236336416816a0',20:'1j01k11l41m11n71q61r61s61t31u61x61y61z62062162442542642742812b42c0',21:'3o06e07j07k67l07m67q67r17t47x19619919a49b09c09d39g39u3',22:'0i30j00k00l00o70p70q70r70s00y31201501601961a31c31d01g01h61i31j61k01n31p31q01r01u31v31x61y62162262363763933f03l03m03o63s03u03v03w04034k64l64m64n64o34r34s34t34u05005137h67i47j77k47w37y07z0',23:'8508808b18g1',24:'2v02y32z73073143273533633733833903d03f05q65r95s35v35w65y45z462a6396466566666996a66y18h98i38l38m69t09u3',25:'0y01n12f02i32k02l32m72p72q42r42s02t32w32y0901',26:'1011q41w41x31y01z32032302402502632762a62b62c32d42e42h72i12j02k02l02p34h34u15215o05s15u78108f38i38j68l48m78p18w58x28y58z5905'},
    sw: {16:'0b00j00l00s01c31d01e01h31i01j01k01l01o01q31r31s31v01w01x01y01z32402502i03213b03c03n04a04b04f04h04i04l04s05005105305a05g05s05t05v06236636f06k06y07j08408w09h09i39j09k09o39p39q39r39u09v39w0a20a30',17:'0200360430b30c30d00n00q00w01a01g31h01i01x02002102232302402732802902a02b02f02g02h02l02o02u02v02w02z33003103263333633763833933a33e63g33k33m33n63o33r33s33t33u03v63y03z04004134204504604934c04k05d05e05f35i05j05k15l15m15p15q05r05s05t05w05x05y06a06e06i06y07207907k07v07w37x07y38108208308408508808908a08b08c38f08g38h38i08j08m08n08o38w09109809n09w0a10a20',18:'0260360430530800b00c00g30h00i00j00m00n00o40p10q10t40u00v00w00x01101401701801901e01i01l01t01w32012302602702902d02e02f02g02l02n02r02s02t02u03033103603703833903c03m03n03s03z34104604734864e04t05005435a05c05e05l05p05q05s05v35w35x35z06306406a36d36h06i06j06k06n36q06r07507807907a07b37c07i07j07m07n07q07x38138408a08e08f38g08h68i68n08o08t08v09139209309609709819919d49h09m09n0a00a13a23',19:'0400900f00g00n00o00p00u01702202j02l02u13b03q03x04604a04p04r05b05j06906c06g06h06o06q06v06w07207l07p07v07w08008608h08l08n08u08v09509g09k09l09m09r0a10',20:'0700930a30d30e00f00g30h10k10l10m40n00y00z01131201611741l01q11s11y02102512812c02d02e02i02j02l02p02s02t02w02x32z03033303403533603703a33b03c33h03j03k33l03v04304604904a44b44c14d44g04o04u05405805b05c05f05g05h05i05j05m05n05o05p05q05t35u05v35w05x06006106236306406746816946a16m07617k07r07t17u17y17z08008108208508608708808908c08d08e08f08g08j08k38l38m38n08q08r08s08u08x38y08z09109439539709809c39d39e39f09y0a40a53',21:'0400500840b10c00d30e30f30i00j30k40l40m40p40q30r00x00y00z01001301511a11b11c01d01e01h01i01j01k01l01p01q01r01s01v01w02q32r32u32v32w32x32y33133233303403503833903b03c03f0',22:'0d02w03o03p03t03u03v03w03z34734e05f05g05r06746876c46d06e08p18q18r18u38v08x09409509n09o39q0',23:'0660b00i00j00k40p10q40w30x01261801i01p01q01v02302a02g02s02v62w02z03003103233333603903g03k03t33v04234j05e65f05i35j05l05p05ta6h06j36p68h08i38j08m38q68u68v08w09069109209309409839l09o09v6a01a21',24:'0i00j00x31201301961g01h91i01s02002832962a02d02e02f02u03533633703803933c03d03f33g03r03t04k04p04x05765a15c15d15i05s05x06566606a66d16g46k07107507b08008208708808908o08z39m09r0',25:'0300630f60h30l01831d11e41f01g01j01k01l01s01z32162402642712812b62c02r02t62x02y03433563603k03l03o63p63q03r03s03v03w03x33z04364504b04c04g34h04i04n64u04v65b05f05g05h05i05m06036806i37207737807997d67m07n37v07y68068138208568608708838998c98e48g18j18q48t18u08x38y38z39409s0a30',26:'0230500660960e00l60n00r70s40y10z11131801f61i11j71k71l11w02342i32j02q02r02s02v02w32z63463663b03c63g03i63k63n13p73w33x33y34264444814934b04f64i34m34p74t44v14w15035115705a05f45m75v36017807c18408c18m18p18r1'}};
  const CB = '#00695c', CS = '#ad1457', SZ = [8, 12, 16, 20], STEP = ['문턱에 1개 모자람', '신호(문턱)', '강(문턱+1)', '매우 강(문턱+2 이상)'];
  const OFF = window.__rvTurnOff || (window.__rvTurnOff = new Set(['bw', 'sw']));   // 처음에는 '지금 조건'만 켠다
  const iso = (yy, s) => new Date(Date.UTC(2000 + +yy, 0, parseInt(s, 36))).toISOString().slice(0, 10);
  const dec = o => Object.keys(o).sort().flatMap(yy => { const s = o[yy], a = []; for (let i = 0; i + 3 <= s.length; i += 3) { const c = parseInt(s[i + 2], 36); a.push({d: iso(yy, s.slice(i, i + 2)), st: Math.floor(c / 3), h: c % 3 === 1 ? 1 : c % 3 === 2 ? 9 : 0}); } return a; });
  let bad = false; { let h = 0; ['L', 'H', 'bn', 'sn', 'bw', 'sw'].forEach(k => Object.keys(T[k]).sort().forEach(yy => { const s = k + yy + T[k][yy]; for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) % 1000000007; })); bad = h !== T.sum; }
  const SETS = [['bn', CB, 1, '전환 매수(지금 조건 ' + T.nb + '개 중 ' + T.kb + '개↑)'], ['sn', CS, -1, '전환 매도(지금 조건 ' + T.ns + '개 중 ' + T.ks + '개↑)'],
    ['bw', CB, 1, '전환 매수(그때 자료로 만든 조건, 2016~)'], ['sw', CS, -1, '전환 매도(그때 자료로 만든 조건, 2016~)']].map(a => ({key: a[0], col: a[1], dir: a[2], lab: a[3], wf: a[0][1] === 'w', pts: dec(T[a[0]])}));
  const redraw = () => { const box = document.getElementById('all-chart'); if (box && box._rvApi && box._rvApi.draw) box._rvApi.draw(); };
  const draw = (svg, xd, P0, mk) => {
    const ks = new Map(mk.filter(r => r.kospi != null && r.kospi !== '' && isFinite(+r.kospi)).map(r => [String(r.date).slice(0, 10), +r.kospi]));
    const gg = svg.append('g').attr('class', 'rv-turnsig'), vis = {};
    SETS.forEach(S => { const v = vis[S.key] = S.pts.filter(p => ks.has(p.d) && isFinite(xd(p.d))); if (OFF.has(S.key)) return; const off = S.dir * (S.wf ? 46 : 20);
      gg.append('g').selectAll('rect').data(v).join('rect').attr('x', p => xd(p.d) - SZ[p.st] / 2).attr('y', p => P0.yL(ks.get(p.d)) + off - SZ[p.st] / 2).attr('width', p => SZ[p.st]).attr('height', p => SZ[p.st])
        .style('fill', p => p.h === 1 ? S.col : 'transparent').style('stroke', S.col).style('stroke-width', '2px').style('stroke-dasharray', p => p.h === 9 ? '2 2' : null).style('opacity', p => p.st === 0 ? .5 : 1)
        .append('title').text(p => S.lab + ' ' + p.d + ' · ' + STEP[p.st] + ' · ' + (p.h === 1 ? '맞음(3일 안에 저점·고점이 옴)' : p.h === 9 ? '아직 모름' : '아님')); });
    const lg = document.getElementById('all-legend');
    if (lg) { const ref = Array.from(lg.children).find(e => /^미수 반대매매\(막대\)/.test(e.textContent || '')) || null;
      SETS.map(S => [S.key, S.lab, S.col]).forEach(([k, lab, col]) => {
        const bt = document.createElement('button'); bt.type = 'button'; bt.className = 'rv-lgbtn'; bt.setAttribute('aria-pressed', String(!OFF.has(k)));
        const sw = document.createElement('i'); sw.className = 'rv-sw'; sw.style.background = col; sw.style.borderRadius = '0';
        bt.append(sw, document.createTextNode(lab)); bt.addEventListener('click', () => { OFF.has(k) ? OFF.delete(k) : OFF.add(k); redraw(); }); lg.insertBefore(bt, ref); }); }
    const host = document.getElementById('all-labnote') || lg; let nt = document.getElementById('all-turnnote');
    if (host && !nt) { nt = document.createElement('p'); nt.id = 'all-turnnote'; nt.className = 'rv-note'; host.after(nt); }
    if (nt) { const cnt = k => { const a = (vis[k] || []).filter(p => p.st >= 1 && p.h !== 9); return a.filter(p => p.h === 1).length + '/' + a.length; };
      const b = document.createElement('b'); b.textContent = '전환 신호(임시 표시 · 확인 뒤 제거)';
      nt.replaceChildren(b, document.createTextNode((bad ? ' [자료가 일부 깨져 표시가 정확하지 않을 수 있음] ' : ' ') + '네모 = 신호가 켜진 날: 초록(선 아래) = 매수, 자주(선 위) = 매도. 크기 = 단계(가장 작고 흐린 것 = 문턱에 조건 1개 모자람 → 신호 → 강 → 매우 강). 채운 네모 = 맞음(신호 뒤 3일 안에 저점·고점이 왔고 거기서 5% 이상 움직임), 빈 네모 = 아님, 점선 = 아직 모름. '
        + '보이는 기간에 신호 단계 이상인 날 가운데 맞은 날 — 지금 조건: 매수 ' + cnt('bn') + ' · 매도 ' + cnt('sn') + ' / 그때 자료로 만든 조건: 매수 ' + cnt('bw') + ' · 매도 ' + cnt('sw')
        + '. "지금 조건"은 전체 기간을 다 보고 고른 것이라 과거에는 실제보다 잘 맞아 보인다. 자료 ' + T.made + ' 까지(고정).')); }
  };
  const prev = window.rvLabSig;
  window.rvLabSig = (svg, xd, P0, mk) => { if (prev) { try { prev(svg, xd, P0, mk); } catch (e) { console.error(e); } } try { draw(svg, xd, P0, mk); } catch (e) { console.error(e); } };
})();
/* ==== 임시 전환 신호 끝 ==== */
