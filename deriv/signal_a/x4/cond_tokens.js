const fs = require('fs'); const src = fs.readFileSync('docs/lab/lab.js', 'utf8');
const grab = (start) => { const i = src.indexOf(start); let dep = 0, j = src.indexOf('{', i); for (let k = j; k < src.length; k++) { if (src[k] === '{') dep++; else if (src[k] === '}') { dep--; if (!dep) return src.slice(i, k + 1); } } };
const nl = src.split('\n').find(l => /const normT\s*=/.test(l));
var normT = t => t.replace(/\s+/g, " ").trim(); eval(grab("function parseDesc"));
let C = JSON.parse(fs.readFileSync('docs/lab/data/combos.json', 'utf8')); C = C.combos || C;
const cnt = new Map();
C.forEach((c, i) => { const { toks } = parseDesc(c); toks.forEach(k => { if (!cnt.has(k)) cnt.set(k, []); cnt.get(k).push(c); }); });
const rows = [...cnt.entries()].map(([k, a]) => ({ k, n: a.length,
  abcd: a.filter(c => 'ABCD'.includes(c.src)).length, s: a.filter(c => c.src === 'S').length, w: a.filter(c => c.src === 'W').length,
  up: a.filter(c => c.dir > 0).length, dn: a.filter(c => c.dir < 0).length,
  hit: (() => { const b = a.filter(c => c.has_trades && c.n >= 10); return b.length ? b.reduce((s, c) => s + c.hit, 0) / b.length : null; })(), nh: a.filter(c => c.has_trades && c.n >= 10).length }));
rows.sort((a, b) => b.n - a.n || a.k.localeCompare(b.k));
console.log('tokens', rows.length, 'combos', C.length);
rows.forEach((r, i) => console.log([i + 1, r.n, r.abcd, r.s, r.w, r.up, r.dn, r.hit == null ? '-' : (100 * r.hit).toFixed(1), r.k].join('\t')));
// ---- 순위: 청산·방향 규칙(→…)과 방법 표시는 빼고, 글만 다르고 뜻이 같은 것은 합침
const DROP = new Set(['15%', 'W3 두 방향 함께 · T1 원래 가족', '흐름 무관', '뒤 구간 적합', '뒤 구간 방향', '조합 규칙 묶음(top3)', '조합 규칙 묶음(top1)', '기계학습(목표 정밀도 80%)', 'W3 고르는 꼴 바꿈 · T1 원래 가족', '함께 쓰기', '변동폭 맞춤·σ 창 60일·배수 0.5', '변동폭 맞춤·σ 창 20일·배수 1.0']);
const SAME = {'VIX 1일 변화율 ≥': 'VIX 1일 변화율 ≥ +15%', '60일선 위': '상승 추세(60일선 위)', '하루 늦춤': '하루 늦춰 진입', '외국인 선물·현물 3일 함께 순매수': '외국인 선물·현물 3일 누적 함께 순매수',
  '첫 신호(5일)': '첫 신호만(5일)', '코스피200 3일 등락 상위20%': '코스피200 3일 상위20%', 'S&P·나스닥 선물 모두 상위10%': 'S&P·나스닥 상위10%', 'S&P500·나스닥 선물 상위10%': 'S&P·나스닥 상위10%',
  '분기물 만기 21~40거래일 아님': '만기 21~40거래일 아님', '분기물 콜벽 ±1.5% 아래': 'Q 벽 바로 아래(±1.5%)'};
const M2 = new Map();
cnt.forEach((a, k) => { if (k.startsWith('→') || DROP.has(k)) return; const t = SAME[k] || k; if (!M2.has(t)) M2.set(t, new Set()); a.forEach(c => M2.get(t).add(c)); });
const R = [...M2.entries()].map(([k, s]) => { const a = [...s], b = a.filter(c => c.has_trades && c.n >= 10);
  return {k, n: a.length, abcd: a.filter(c => 'ABCD'.includes(c.src)).length, s: a.filter(c => c.src === 'S').length, w: a.filter(c => c.src === 'W').length,
    up: a.filter(c => c.dir > 0).length, dn: a.filter(c => c.dir < 0).length, hit: b.length ? b.reduce((x, c) => x + c.hit, 0) / b.length : null,
    syn: Object.keys(SAME).filter(x => SAME[x] === k && cnt.has(x)).map(x => x + ' ' + cnt.get(x).length)}; });
R.sort((a, b) => b.n - a.n || a.k.localeCompare(b.k, 'ko'));
console.log('=== 순위', R.length);
R.slice(0, 44).forEach((r, i) => console.log(['R', i + 1, r.n, r.abcd, r.s, r.w, r.up, r.dn, r.hit == null ? '-' : (100 * r.hit).toFixed(1), r.k, r.syn.join(';')].join('\t')));
console.log('=== MD');
R.forEach((r, i) => { const src = [r.abcd && ('갈래' + (r.s || r.w ? ' ' + r.abcd : '')), r.s && ('SA' + (r.abcd || r.w ? ' ' + r.s : '')), r.w && ('2차' + (r.abcd || r.s ? ' ' + r.w : ''))].filter(Boolean).join(' · ');
  const dir = r.up && r.dn ? `상승 ${r.up} · 하락 ${r.dn}` : r.up ? '상승' : '하락';
  console.log(`| ${i + 1} | ${r.k.replace(/\|/g, '/')} | ${r.n} | ${src} | ${dir} | ${r.hit == null ? '–' : (100 * r.hit).toFixed(1) + '%'} |`); });
console.log('=== AGG');
const SH = [[/갈래 B verdicts 전체로 다시 매긴 상위 100개 묶음에서 해마다 그 전 자료로 줄인 건수\(2016년 12 … 2026년 33건\)·적중 80% 이상인 규칙을 골라 /, '갈래 B 다시 매긴 상위 100개에서 해마다 고른 규칙 · '],
  [/갈래 B X1 대상\(순위표 상위 100개, 옛 기록으로 되살린 것 포함\) 묶음에서 해마다 그 전 자료로 줄인 건수\(2016년 12 … 2026년 33건\)·적중 80% 이상인 규칙을 골라 /, '갈래 B X1 대상 100개에서 해마다 고른 규칙 · '],
  [/\((청산은 그 규칙대로|보유일 가운뎃값|그 규칙 보유일)\)/g, ''], [/해마다 그 전 자료에서 /, '해마다 '], [/규칙을 골라 /, '규칙 '], [/쓰는 규칙의 20% 이상이 함께/, '20% 이상 함께'], [/ 사용/g, ''],
  [/\(해마다 그 전 자료로 고른 지표 점수 ≥ 문턱\)/g, ''], [/, 해마다 다시 학습/g, ''], [/오를 확률이 그 전 예측의 /g, '오를 확률 '], [/ 선 이(상|하)/g, ''], [/입력 전부\(434개\)/, '입력 434개'], [/입력 전부\+/g, '+'],
  [/오름 절차와 내림 절차를 한 계좌에서 함께 쓸 때의 오름 거래 — /, '오름·내림 함께 쓸 때 오름 거래 · '], [/상태 없이 방아쇠만: 변동성 꺾임\(VKOSPI 자리 80 이상에서 하루 5% 이상 하락\)/, '상태 없이 방아쇠만: 변동성 꺾임'],
  [/ — 점수 문턱은 저점의 60% 를 잡는 값/, '(문턱 = 저점 60%)'], [/ — 전환 저점을 8% 기준으로/, '(전환 저점 8%)'], [/\s+/g, ' ']];
const shn = k => SH.reduce((s, [a, b]) => s.replace(a, b), k).trim();
const pf = (n, h) => n ? (100 * h / n).toFixed(1) + '%' : '–';
R.forEach((r, i) => { const a = [...M2.get(r.k)].filter(c => c.has_trades);
  let N = 0, H = 0, n1 = 0, h1 = 0, n2 = 0, h2 = 0, k1 = 0, k2 = 0;
  a.forEach(c => { N += c.n; H += c.n * c.hit; if (c.p1) { n1 += c.p1[0]; if (c.p1[1] != null) { k1 += c.p1[0]; h1 += c.p1[0] * c.p1[1]; } } if (c.p2) { n2 += c.p2[0]; if (c.p2[1] != null) { k2 += c.p2[0]; h2 += c.p2[0] * c.p2[1]; } } });
  console.log(`| ${i + 1} | ${shn(r.k).replace(/\|/g, '/')} | ${r.n} | ${N} | ${pf(N, H)} | ${Math.round(n1)} | ${k1 >= 10 ? pf(k1, h1) : '–'} | ${Math.round(n2)} | ${k2 >= 10 ? pf(k2, h2) : '–'} |`); });
fs.writeFileSync('/tmp/cond_map.json', JSON.stringify(R.map((r, i) => ({rank: i + 1, name: shn(r.k), keys: [...M2.get(r.k)].map(c => c.key)}))));
