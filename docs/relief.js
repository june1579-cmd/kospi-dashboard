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
  const T = {"made":"2026-11-20","L":["2015-08-24","2016-01-20","2016-06-24","2017-08-11","2018-02-09","2018-10-29","2019-01-03","2019-03-08","2019-05-29","2019-08-13","2020-01-31","2020-02-28","2020-03-19","2020-03-23","2020-06-15","2020-08-20","2020-09-24","2020-10-30","2021-01-18","2021-01-29","2021-03-10","2021-10-12","2021-11-30","2022-01-27","2022-07-06","2022-09-30","2023-01-03","2023-03-14","2023-10-31","2024-01-17","2024-04-19","2024-08-05","2024-09-11","2024-11-14","2024-12-09","2025-03-04","2025-04-09","2025-11-07","2025-11-21","2026-02-02","2026-02-06","2026-03-04","2026-03-09","2026-03-31","2026-05-20","2026-06-08","2026-06-23","2026-07-02","2026-07-13","2026-07-20","2026-07-30","2026-08-07","2026-08-19","2026-09-02","2026-09-15","2026-10-26","2026-11-09"],"H":["2015-04-23","2015-11-03","2016-04-21","2017-07-24","2018-01-29","2018-03-15","2018-12-03","2019-02-25","2019-04-16","2019-06-27","2020-01-22","2020-02-14","2020-03-05","2020-03-20","2020-06-05","2020-08-13","2020-09-15","2020-10-12","2021-01-11","2021-01-25","2021-02-16","2021-06-25","2021-11-22","2021-12-28","2022-02-10","2022-08-16","2022-11-11","2023-01-27","2023-08-01","2024-01-02","2024-04-02","2024-07-11","2024-08-20","2024-09-26","2024-11-25","2025-02-19","2025-03-21","2025-11-03","2025-11-13","2026-01-30","2026-02-04","2026-02-26","2026-03-06","2026-03-18","2026-05-14","2026-06-01","2026-06-22","2026-06-25","2026-07-03","2026-07-15","2026-07-23","2026-08-05","2026-08-14","2026-08-21","2026-09-09","2026-09-23","2026-10-28","2026-11-11"],"buy":{"k":6,"n":8,"now":"1501050015010620150107201501162015012000150123001501280015013000150615001506291015063000150706001507082015070920150710101508202115082121150824311508252015082620150827101508281015083110150901201509021015090300150904101509071015090800150909001509100015091100150914101509150015091600150917101509181015092300150924001509251015093000160104001601062016010720160108001601111016011210160113101601143016011531160118211601190116012031160121301601221016012520160126201601271016012800160202001602050016021110160212101602150016021600160624011606270016110310161104101704100017041100170412001704141017041700170810111708113117081400170817101708181017082110170822001711300017120100171206001802021018020520180206211802073118020831180209311802123018021330180214301802192018022030180221201802222018022300180226001802271018022820180302101803052018030600180314001803150018031900180322101803232018032600180327101803282018032910180330001804022018040320180404301804051018040630180409101804101018041110180412101804240018062500180626001806271018062820180702001807031018070410180705001810100018101130181012301810153018101630181017101810183018101910181022101810233018102431181025311810263118102931181030301810312018110120181102001811051018110600181113101811142018112010181207001812100018121100181224101812261018122701190102211901032119051330190514001905290119080500190806101908120119081400190826002001313120020300200221102002243020022531200226312002273120022831200302302003033020030410200305102003062020030930200310202003113020031230200313302003163120031731200318312003193120032021200323312003242020032520200326202003272020033020200331202004012020040220200403202004060020040700200409002004100020041300200414002004160020041700200420002004210020042200201030112011020021113001220118002201190022012000220121002201242122012521220126212201273122012810220203102202040022020710220210102202111022021420220215302202160022021710220218102202211022022210220223002202241022022500220228102203020022030310220304102203072022030820220310202203112022031430220315302203162022031710220425202204260022042710220503002205091022051100220512202205180022052000220524002206133022061430220615302206163022061730220620302206212022062230220623202206270022062800220629102206303022070111220704112207061122092000220921002209230022092630220927312209283122092931221007002210111022101200221013102210142022101710221018102210190022102000231019002310200023102300231025102310262123102711231030112310311124041611240417212404181124041921240425002407240024072520240726002407301024080221240805312408062024080710240808202408092024081220240813102409060124102200241024002410312024110110241104002411051024120901241219002502280125030411250310002503111025031300250314002503280025033120250401002504021025040320250404212504073125040831250409012504102025041120250414102504150025041620250417002504180025042100250422102504230025101600251117002511181125111911251120312511213125112410251125102511260025112700260205112603032126030511260306112603093126031020260311002603123026031330260316202603172026031810260319102603202026032330260324302603253026032631260327312603303126033121260401002604022026040320260406002604070026060501260609002606101026061100260623112606290126070111260702012607030026070600260713012607150126071601260720012607220026072300260724002607271126072931260803002610300026110200261103002611050126110611261109012611161926111719261118192611190926112009","wf":"1601200116012200160126001704110017041200170811011709050017090610171130001712011017120620171207201712082017121100171212201712130017122700180205001802061118020711180208211802092118021220180213101802140018021900180220101802211018022210180223101802271018022810180302101803051018030610180307001803080018042400180425001806140018061510180618101806190018062100180628101806290018070210180703101807041018070510180706101807090018071000180711001807121018071300180716001807170018071800180719001807200018072300180724001807250018081310180814001808161018081700180820001810111018101200181015001810160018101700181018001810190018102300181024111810251118102611181029111810301018103110181101101811050018110700181113001811140019080510190806101908071019080801190812011908140020022400200225012002261120022701200228212003022020030320200304202003051020030620200309202003102020031120200312202003132020031611200317112003181120031911200320012003231120032400210512002108180021092800210929202109300021100120211005202110060121100811211012012111260121112901211130112112010021120200211203102112061021122010220118102201190022012000220121002201242122012521220126212201272122012800220203102202070022021000220211002202142022021510220217102202180022022100220222202202231022022420220225002202281022030210220303002203040022030710220308102203102022031120220314202203152022031620220425202204271022050300220509002205100022051220220516002205180022051900220520002205241022061320220614202206152022061620220617102206201022062110220622102206230022062900220630102209262022092711220928212209291122101110221013002210140023102000231023002310260123103101240412002404151024041621240417212404181124041921240422102404231024042410240425102404260024043000240502002407242024072530240726102407291024073020240801112408021124080531240806302408072024080820240809202408123024081320240906012410313024110110241104102411052024121800241219102502030025022801250328002503311025040200250403102504042125040721250408112504091125041000250411102504141025041600251120012602050126030311260309112603101026031100260312102603131026031600260317002603180026031910260320202603232026032420260325102603261126032711260330212603310126040100260402002604030026040710260610102606230126070101260723002607270126072921261016002610301026110210261103202611051126110621261109012611161926111709261118192611191926112019"},"sell":{"k":5,"n":8,"now":"150212001503160015051400150915001510070015111610151124101512150016011420160122001602122016021500160216201602171016021800160222101602240016031110160318001603220016032900160414101604150016041901160422001604260016051620160609001606101016071800160720101607210016072200160726101607270016080500160811101608121016081610160817001608230016090800160912001609270016092900161111001611150016120700161208101612090016121210161213201612141016121510161216101612202017010300170106001702010017042500170608001706090017071400171012001711010017110300171109001802090018021200180308001803091018041200180417001805102018051100180514001809131018091400180920001811080018112801181203011901300019021410190215001904120119041601190417001905090019051000190514001906180019062000190808101908130019081600190819001909040019090500190911101909160019091700190918001909190019092000190923001909240019092500191025001911141019111520191118201911192019112000191125001912110019121220191213101912161019121710191218101912191019122010191227002001020020010700200109102001100020011300200116002003120020031320200316002003173120031811200319312003202120032330200324202004130020041400200514002005181020052010200603012006050120070900200729002008120120081311200814102008180020091001200914212009151120100821201012112011122020111310201116102012040021010400210105002101071121010821210114202101150021011910210120112101210121012201210125012101260021021001210215212102160121021700210311202103120021031510210408002105140022031010220512002205131022051700220527002206021022060900220714002207151022071900220810012208112122081231220816112208170022081800220819002208250022101300221110112211111122111500221130002212081022120900221212102212130022121400221215002301250123012611230127012302020023020910230210102302130023031400230316002303290023041320230414002304170023041800230419002304200023051120230608002306090023061210230713202307140023071710230810002308110023081410230816002309141023091510230918002311090023111020231114102311200023121420231215002312181023122000231221102312261123122711231228012401080024020800240214102403180024032010240321102403220024032500240411002405140024061300240617102406251024070510240708012407100124071111240808302408092024091200240913102409191024111410241115102411180024121300241216102412230025011500250117002502131025021401250217012502180125021911250220002503140025032400250411002505081025050900250512202505131025051400250516002505271025052900250604002506051025060910250610102506110025061210250613002506162025061700250623002506242025062500250702002507030025071010250714002507150025071600250717002509182025100210251010102510131025101510251016002510170025102030251021002510221025102320251024302510273025102800251029112510300125103101251103112511040025110500251110012511132125111410251117102511181025111900251211002601021026010500260106202601080026010930260112202601132026011420260115202601162026011920260120102601213026012210260123102601261026012731260128312601292126013001260203012602041126021220260213202602192026022030260223212602243126022521260226212602271026031611260325002603310026040910260410102604130026041400260417102604221026042410260427002604280026042910260430202605042026050630260507202605083026051131260512112605133126051421260515102605181026051900260520202605211026052220260526302605272126052821260529212606011126060230260604202606081026061110260615102606160026061721260618312606191126062231260625012606290026063001260709102607131126071411260716002607211126072400260727002607300026080401260813112610160026101900","wf":"1601110016011900160121001601280016021710160218001602190016022210160223001602240016022500160226001602290016030210160303101603041016030700160308001603090016031000160311101603160016031700160330001604190116042800160429001605100016060200160603001606070016060900160610001606130016062000160628001606290016070100160708001607140016072600160727001607290016080510160809101608180016082300160906001609270016101800161115001612060016120710161208001612090016121310161214101612151016121610161219001612201016122100161227001612280017010200170103201701041017011110170112101701130017012300170126001702010017021500170221101702220017022300170310001703130017031400170315101703160017031700170320101703210017032200170323001703240017032800170329001703300017040300170406001704120017041300170414001704171017041800170419001704202017042110170424101704252017042610170427101704281017050220170504101705081017051010170511201705121017051510170516101705171017051800170519201705220017052300170524001705251017052600170529001705300017060210170605001706130017071200170713001707141017071700170718001707190117072001170721011707240117072500170726001707270017072800170731001708010017080200170814001708180017082200170907001709110017091800170929001710100017101110171012001710131017101600171017001710180017101900171020001710230017102400171025001710260017102710171030001710311017110110171102001711030017110600171107001711081017111600171121001711280017121300171222001712270017122800180102201801032018010410180105101801080018011100180112001801161018011700180118001801190018012200180123001801241118012501180126011801291118013000180131001802010018020200180206001802090018021200180213001802140018021900180223001802260018030600180309101803130118031600180319001803200018032200180326001803270018032800180329001804030018040500180409001804100018041100180412001804181018041900180424001804250018042610180427001804300018051000180511001805160018052310180525001805300018053110180601201806070018062200180629001807031018070900180711001807130018072000180724001807250018072700180730101807311018080110180803001808070018080800180814101808171018082100180822001808230018082400180827101808300018083100180914001809170018091800180919001809201018092100180927001809280018100100181002001810050018101210181016101810190018102500181029001810301018103100181101201811022018110700181108001811130018111500181121101811220018112300181126001811270018112801181129011812031118120700181212001812130018122600181227101812281019010400190109001901150019011600190123001901240019012500190130001902120019031500190401001904030019041201190429001905140019052100190530001906030019061800190620001907100019071800190813001908160019082000190821001908280019083000190904001909050019091100190930001910040019101000191011001910150019102100191101001911050019110700191114001911150019112500191206001912100019121100191212001912170019122700200107002001091020011010200113102001140020011500200116102001170120012001200121012001221120012300200203002002040020020610200207002002110120021211200226002003020120030401200310002003130020031701200320012003240020032500200326002003300020033100200402002004060020040900200410002004130020041410200416002004171020042000200421002004221020042300200424002004271020042800200429102005040020050600200507102005080020051800200526002005290020060100200602112006031120060401200605112006080020061600200622002007020020070600200709002007100020071300200714002007150020071600200717002007200020072100200722002007230020072400200727102007280020072910200730002007310020080300200804002008051020080600200807002008101120081101200812112008130120082500200914012009280020100500201007012010080120101201201013002010140020101500201016002010190020102000201021002010220020102300201026002010270020102800201029002010300020110200201103102011041020110510201106002011090020111000201111002011130020111610201117002011180020112000201123102011241020112600201127002012011020120210201203102012040020122300201229002012301021010400210105002101081121011101210112002101131021011410210115102101180021011910210120112101211121012211210125112101261021012700210202002102030021020400210205002102080021021001210215012102160121021700210218002102190021022200210223002102240021022500210226002103020021030300210304002103050021030800210309002104081021040910210412102104131021041410210415102104161021041910210420102104210021042200210423002104261021042700210429002104300021050300220113002204140022051200220513002205170022051800220519002205200022052310220531102206070022071400220715002207260022081111220812212208161122081700220818002211090122111001221111012211141022111500221117002211240022112500221213002212141022121600230106202301110023011800230119002301201123012501230126112302011023020200230207202302130023022300230302002303030023030800230316002303230023032900230410002304132023041400230417002304180023041900230420102304211023042400230427002305040023050800230517102305190023052610230612002307132023071400230717102307180023072000230724002307283123082100230823102308292023110100231102102311030023110610231110202311142023111500231116002311202023112100231122002311230023112400231128102312110023121400231221202312260123122801240118002401190024020210240207002402080024021420240221002402223024022300240304002403120024032010240321202403220024032500240326002403270024041100240422102404231024042400240425002404261024042900240430002405021024050300240514002405160024061200240617002406250024070520240708012407100124071101240716002407260024073100240808202408090024081320240816012408191124082300240909002409130024091900241014002410160024102100241022002410230024110700241118102412110024121600250103002501061025011520250117102501210025021310250218012502191125022000250221002502240025022500250226002503050025031210250314202503170025031911250320012503210125032420250325002504090025041120250415002504160025042210250423202504240025050800250509002505122025051320250514002505150025051600250519002505200025052110250523002505272025052900250604002506050025060910250610002506110025061620250623002506242025071000250714002507150025071600250717002507210025080410250812002508221025091100250916102509170025091830250922202510010025100210251010002510132025101520251016102510170025102020251021002510220025102310251024302510273025102911251031012511030125111011251113012511140025111710251118102511191025112400251218002512290026010210260105002601062026010920260114002601212026012300260127212601281126020301260204012602061026021300260220202602230126022421260225212602260126030900260316112603311026040100260408002604090026041000260413002604141026041720260422202604242026042900260430202605040026050620260508202605110126051321260520102605211026052210260526202605281126060101260602102606040026060820260611102606151026061821260622112606240126062501260629102606300126070600260709002607141126072121260730102608040126091700260921012610190026102701261106012611090126111101"}};
  const CB = '#00695c', CS = '#ad1457', SZ = [4, 7, 9, 11], STEP = ['문턱에 1개 모자람', '신호(문턱)', '강(문턱+1)', '매우 강(문턱+2 이상)'];
  const OFF = window.__rvTurnOff || (window.__rvTurnOff = new Set(['bw', 'sw']));   // 처음에는 '지금 조건'과 실제 시작점만 켠다
  const dec = s => { const o = []; for (let i = 0; i < s.length; i += 8) o.push({d: '20' + s.slice(i, i + 2) + '-' + s.slice(i + 2, i + 4) + '-' + s.slice(i + 4, i + 6), st: +s[i + 6], h: +s[i + 7]}); return o; };
  const SETS = [['bn', 'buy', 'now', CB, 1, '전환 매수(지금 조건 ' + T.buy.n + '개 중 ' + T.buy.k + '개↑)'], ['sn', 'sell', 'now', CS, -1, '전환 매도(지금 조건 ' + T.sell.n + '개 중 ' + T.sell.k + '개↑)'],
    ['bw', 'buy', 'wf', CB, 1, '전환 매수(그때 자료로 만든 조건, 2016~)'], ['sw', 'sell', 'wf', CS, -1, '전환 매도(그때 자료로 만든 조건, 2016~)']].map(a => ({key: a[0], col: a[3], dir: a[4], lab: a[5], wf: a[2] === 'wf', pts: dec(T[a[1]][a[2]])}));
  const redraw = () => { const box = document.getElementById('all-chart'); if (box && box._rvApi && box._rvApi.draw) box._rvApi.draw(); };
  const draw = (svg, xd, P0, mk) => {
    const ks = new Map(mk.filter(r => r.kospi != null && r.kospi !== '' && isFinite(+r.kospi)).map(r => [String(r.date).slice(0, 10), +r.kospi]));
    const gg = svg.append('g').attr('class', 'rv-turnsig'), vis = {};
    if (!OFF.has('pv')) [['L', CB, 1, '실제 상승 시작점(저점, 그 뒤 5% 이상 오름)'], ['H', CS, -1, '실제 하락 시작점(고점, 그 뒤 5% 이상 내림)']].forEach(([t, c, dir, lab]) =>
      gg.append('g').selectAll('line').data(T[t].filter(d => ks.has(d) && isFinite(xd(d)))).join('line').attr('x1', d => xd(d)).attr('x2', d => xd(d)).attr('y1', d => P0.yL(ks.get(d)) + dir * 3).attr('y2', d => P0.yL(ks.get(d)) + dir * 44)
        .style('stroke', c).style('stroke-width', '1.5px').style('opacity', .75).append('title').text(d => lab + ' ' + d));
    SETS.forEach(S => { const v = vis[S.key] = S.pts.filter(p => ks.has(p.d) && isFinite(xd(p.d))); if (OFF.has(S.key)) return; const off = S.dir * (S.wf ? 32 : 16);
      gg.append('g').selectAll('rect').data(v).join('rect').attr('x', p => xd(p.d) - SZ[p.st] / 2).attr('y', p => P0.yL(ks.get(p.d)) + off - SZ[p.st] / 2).attr('width', p => SZ[p.st]).attr('height', p => SZ[p.st])
        .style('fill', p => p.h === 1 ? S.col : 'transparent').style('stroke', S.col).style('stroke-width', '1.5px').style('stroke-dasharray', p => p.h === 9 ? '2 2' : null).style('opacity', p => p.st === 0 ? .5 : 1)
        .append('title').text(p => S.lab + ' ' + p.d + ' · ' + STEP[p.st] + ' · ' + (p.h === 1 ? '맞음(3일 안에 실제 시작점)' : p.h === 9 ? '아직 모름' : '아님')); });
    const lg = document.getElementById('all-legend');
    if (lg) { const ref = Array.from(lg.children).find(e => /^미수 반대매매\(막대\)/.test(e.textContent || '')) || null;
      SETS.map(S => [S.key, S.lab, S.col]).concat([['pv', '실제 시작점(세로 선: 아래 = 상승 시작, 위 = 하락 시작)', 'var(--color-fg-muted)']]).forEach(([k, lab, col]) => {
        const bt = document.createElement('button'); bt.type = 'button'; bt.className = 'rv-lgbtn'; bt.setAttribute('aria-pressed', String(!OFF.has(k)));
        const sw = document.createElement('i'); sw.className = 'rv-sw'; if (k === 'pv') { sw.style.width = '2px'; sw.style.height = '.8rem'; sw.style.background = col; } else { sw.style.background = col; sw.style.borderRadius = '0'; }
        bt.append(sw, document.createTextNode(lab)); bt.addEventListener('click', () => { OFF.has(k) ? OFF.delete(k) : OFF.add(k); redraw(); }); lg.insertBefore(bt, ref); }); }
    const host = document.getElementById('all-labnote') || lg; let nt = document.getElementById('all-turnnote');
    if (host && !nt) { nt = document.createElement('p'); nt.id = 'all-turnnote'; nt.className = 'rv-note'; host.after(nt); }
    if (nt) { const cnt = k => { const a = (vis[k] || []).filter(p => p.st >= 1 && p.h !== 9); return a.filter(p => p.h === 1).length + '/' + a.length; };
      const b = document.createElement('b'); b.textContent = '전환 신호(임시 표시 · 확인 뒤 제거)';
      nt.replaceChildren(b, document.createTextNode(' 네모 = 신호가 켜진 날: 초록(선 아래) = 매수, 자주(선 위) = 매도. 크기 = 단계(가장 작고 흐린 것 = 문턱에 조건 1개 모자람 → 신호 → 강 → 매우 강). 채운 네모 = 맞음(3일 안에 실제 시작점), 빈 네모 = 아님, 점선 = 아직 모름. 세로 선 = 실제 시작점(5% 이상 움직인 저점·고점). '
        + '보이는 기간에 신호 단계 이상인 날 가운데 맞은 날 — 지금 조건: 매수 ' + cnt('bn') + ' · 매도 ' + cnt('sn') + ' / 그때 자료로 만든 조건: 매수 ' + cnt('bw') + ' · 매도 ' + cnt('sw')
        + '. "지금 조건"은 전체 기간을 다 보고 고른 것이라 과거에는 실제보다 잘 맞아 보인다. 자료 ' + T.made + ' 까지(고정).')); }
  };
  const prev = window.rvLabSig;
  window.rvLabSig = (svg, xd, P0, mk) => { if (prev) { try { prev(svg, xd, P0, mk); } catch (e) { console.error(e); } } try { draw(svg, xd, P0, mk); } catch (e) { console.error(e); } };
})();
/* ==== 임시 전환 신호 끝 ==== */
