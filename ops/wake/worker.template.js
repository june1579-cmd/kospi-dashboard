// kospi-wake — 정해진 시각에 GitHub 워크플로를 깨우는 Cloudflare Worker (2026-11-26, 업그레이드 요청 U-1126-2)
// 이 파일은 틀이다. ops/wake/build.py 가 아래 세 자리 표시(표·저장소·가지)를 채워 ops/wake/dist/worker.js 를 만들고 wake-deploy 워크플로가 배포한다.
// 매분 한 번 돈다(Cron Trigger "* * * * *"). 표의 예약 식(UTC, GitHub 워크플로 파일의 cron 과 같은 글)이 지금 분과 맞으면
// workflow_dispatch(ref, inputs.slot = 예약 식)를 부른다. 워크플로는 slot 을 예약 식처럼 읽어 GitHub 예약과 똑같이 움직인다.
// 비밀값: GH_TOKEN(이 저장소의 Actions 쓰기 권한만 가진 GitHub 토큰) — wrangler secret 으로만 넣는다.
const SCHEDULE = __SCHEDULE__;
const REPO = __REPO__;
const REF = __REF__;

function fieldOk(spec, v, lo, hi) {
  for (let part of spec.split(',')) {
    let step = 1;
    if (part.includes('/')) { const [p, s] = part.split('/'); part = p; step = parseInt(s, 10); }
    let a, b;
    if (part === '*') { a = lo; b = hi; }
    else if (part.includes('-')) { [a, b] = part.split('-').map(Number); }
    else { a = b = Number(part); }
    if (v >= a && v <= b && (v - a) % step === 0) return true;
  }
  return false;
}

function cronMatch(expr, t) {
  const [mi, ho, dom, mon, dow] = expr.trim().split(/\s+/);
  const dOk = fieldOk(dom, t.getUTCDate(), 1, 31), wOk = fieldOk(dow, t.getUTCDay(), 0, 6);
  const day = (dom === '*' || dow === '*') ? (dOk && wOk) : (dOk || wOk);
  return fieldOk(mi, t.getUTCMinutes(), 0, 59) && fieldOk(ho, t.getUTCHours(), 0, 23) && fieldOk(mon, t.getUTCMonth() + 1, 1, 12) && day;
}

async function dispatch(env, e) {
  const url = `https://api.github.com/repos/${REPO}/actions/workflows/${e.wf}/dispatches`;
  const body = JSON.stringify({ref: REF, inputs: {slot: e.cron}});
  const headers = {'Authorization': `Bearer ${env.GH_TOKEN}`, 'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'kospi-wake', 'Content-Type': 'application/json'};
  for (let i = 0; i < 2; i++) {
    const r = await fetch(url, {method: 'POST', headers, body});
    if (r.status === 204) { console.log(`깨움 ${e.wf} [${e.cron}]`); return; }
    const txt = (await r.text()).slice(0, 200);
    console.log(`깨우기 실패 ${e.wf} [${e.cron}] HTTP ${r.status} ${txt}`);
    if (r.status < 500) return;                       // 권한·입력 문제는 다시 해도 같다
    await new Promise(res => setTimeout(res, 3000));
  }
}

export default {
  async scheduled(event, env, ctx) {
    const now = new Date(event.scheduledTime);
    const due = SCHEDULE.filter(e => cronMatch(e.cron, now));
    if (!env.GH_TOKEN) { console.log('GH_TOKEN 없음 — 깨우지 않음'); return; }
    ctx.waitUntil(Promise.all(due.map(e => dispatch(env, e))));
  },
  async fetch() {
    return new Response(JSON.stringify({ok: true, repo: REPO, entries: SCHEDULE.length, workflows: [...new Set(SCHEDULE.map(e => e.wf))]}), {headers: {'content-type': 'application/json; charset=utf-8'}});
  },
};
