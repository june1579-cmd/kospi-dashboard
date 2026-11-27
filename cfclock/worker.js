// 장중 도달 확률 정시 시계 (Cloudflare Worker, 2026-11-27 사용자 지시: "08:30·09:10 전에 결과가 나와야 한다").
// GitHub 예약(schedule)은 몇 시간씩 늦거나 빠지므로, 정확한 Cloudflare 예약이 정해진 시각에 GitHub 작업 실행을 요청한다.
// 계산은 GitHub Actions 가 한다. 이 코드는 시각 확인 → 결과·실행 상태 확인 → 필요하면 실행 요청만 한다.
// 비밀값: GH_TOKEN(이 저장소 Actions 쓰기·Contents 읽기만 되는 토큰)은 Worker 비밀로만 둔다.
const REPO = "june1579-cmd/kospi-dashboard";
const API = "https://api.github.com/repos/" + REPO;

// 한국 시각(평일) → 할 일
export const SLOTS = {
  "06:43": ["pre"],            // 08:30판 계산
  "07:20": ["pre?"],           // 08:30판 확인, 없거나 빠진 값이 있으면 다시
  "08:13": ["am?"],            // 오전 수급 수집 출발(08:40부터 수집, 09:05:20 에 09:10판 계산)
  "08:20": ["pre?"],
  "08:30": ["am?"],
  "12:02": ["pm?"],            // 오후 수급 수집 출발
  "12:15": ["pm?"],
  "16:21": ["eve"],            // 16:20판 계산
  "16:45": ["eve?"],
};

export function kst(ms) {
  const d = new Date(ms + 9 * 3600e3);
  const p = (n) => String(n).padStart(2, "0");
  return { date: `${d.getUTCFullYear()}-${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())}`,
           hm: `${p(d.getUTCHours())}:${p(d.getUTCMinutes())}`, dow: d.getUTCDay() };
}

async function gh(env, path, opt = {}) {
  const r = await fetch(API + path, { ...opt, headers: {
    "Authorization": "Bearer " + env.GH_TOKEN, "Accept": opt.accept || "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "kospi-reach-clock", ...(opt.body ? { "Content-Type": "application/json" } : {}) } });
  return r;
}

async function dispatch(env, wf, inputs) {
  const r = await gh(env, `/actions/workflows/${wf}/dispatches`, { method: "POST", body: JSON.stringify({ ref: "main", inputs }) });
  return `${wf} ${JSON.stringify(inputs)} → ${r.status}${r.status === 204 ? " 실행 요청됨" : " 실패: " + (await r.text()).slice(0, 200)}`;
}

async function readJson(env, path) {
  const r = await gh(env, `/contents/${path}?ref=main`, { accept: "application/vnd.github.raw+json" });
  if (!r.ok) return null;
  try { return JSON.parse(await r.text()); } catch { return null; }
}

// 오늘(한국) 만들어진 intraday-flow 실행 중 [fromHm, toHm) 사이에 생긴 것이 진행 중·대기 중인지
async function flowRunning(env, today, fromHm, toHm) {
  const r = await gh(env, `/actions/workflows/intraday-flow.yml/runs?per_page=20`);
  if (!r.ok) return null;
  const runs = (await r.json()).workflow_runs || [];
  return runs.some((x) => {
    const k = kst(Date.parse(x.created_at));
    return k.date === today && k.hm >= fromHm && k.hm < toHm && (x.status === "in_progress" || x.status === "queued" || x.status === "waiting" || x.status === "pending");
  });
}

export async function act(env, task, t) {
  if (task === "pre") return dispatch(env, "reach.yml", { what: "pre" });
  if (task === "eve") return dispatch(env, "reach.yml", { what: "eve" });
  if (task === "pre?") {
    const d = await readJson(env, "docs/reach/data/pre.json");
    if (d && d.for_date === t.date && !(d.status || []).length) return `08:30판 있음(${d.built})`;
    return "08:30판 없음·빠진 값 → " + await dispatch(env, "reach.yml", { what: "pre" });
  }
  if (task === "eve?") {
    const d = await readJson(env, "docs/reach/data/eve.json");
    if (d && String(d.built || "").slice(0, 10) === t.date && !(d.status || []).length) return `16:20판 있음(${d.built})`;
    return "16:20판 없음·빠진 값 → " + await dispatch(env, "reach.yml", { what: "eve" });
  }
  if (task === "am?" || task === "pm?") {
    const [a, b] = task === "am?" ? ["06:00", "11:30"] : ["11:30", "15:50"];
    const run = await flowRunning(env, t.date, a, b);
    if (run) return `${task.slice(0, 2)} 수급 수집 이미 진행 중`;
    return `${task.slice(0, 2)} 수급 수집 없음 → ` + await dispatch(env, "intraday-flow.yml", { part: task.slice(0, 2) });
  }
  return "모르는 할 일 " + task;
}

export async function tick(env, ms) {
  const t = kst(ms);
  if (t.dow === 0 || t.dow === 6) return [`${t.date} ${t.hm} 주말 — 건너뜀`];
  const tasks = SLOTS[t.hm];
  if (!tasks) return [`${t.date} ${t.hm} 할 일 없음`];
  if (!env.GH_TOKEN) return [`${t.date} ${t.hm} GH_TOKEN 없음 — 실행 못 함`];
  const out = [];
  for (const k of tasks) {
    try { out.push(`${t.date} ${t.hm} ${k}: ` + await act(env, k, t)); }
    catch (e) { out.push(`${t.date} ${t.hm} ${k}: 오류 ${e}`); }
  }
  return out;
}

export default {
  async scheduled(event, env, ctx) {
    const out = await tick(env, event.scheduledTime);
    for (const l of out) console.log(l);
  },
  async fetch(req, env) {
    const t = kst(Date.now());
    const body = { now_kst: `${t.date} ${t.hm}`, token: env.GH_TOKEN ? "있음" : "없음",
      slots_kst_weekdays: SLOTS };
    return new Response(JSON.stringify(body, null, 1), { headers: { "content-type": "application/json; charset=utf-8" } });
  },
};
