// 로컬 점검: 가짜 GitHub 로 시각 분기·판단을 시험
import { tick, SLOTS, kst } from "./worker.js";
const log = [];
let state = { pre: { for_date: "2026-11-27", built: "2026-11-27 06:45 KST", status: [] }, eve: { built: "2026-11-26 16:23 KST", status: [] },
  runs: [{ created_at: "2026-11-26T23:13:05Z", status: "in_progress" }] };
globalThis.fetch = async (url, opt = {}) => {
  log.push((opt.method || "GET") + " " + url.replace("https://api.github.com/repos/june1579-cmd/kospi-dashboard", "") + (opt.body ? " " + opt.body : ""));
  if (url.includes("/dispatches")) return new Response(null, { status: 204 });
  if (url.includes("pre.json")) return new Response(JSON.stringify(state.pre));
  if (url.includes("eve.json")) return new Response(JSON.stringify(state.eve));
  if (url.includes("/runs")) return new Response(JSON.stringify({ workflow_runs: state.runs }));
  return new Response("", { status: 404 });
};
const env = { GH_TOKEN: "x" };
const at = (s) => Date.parse(s);   // UTC
// 모든 cron 시각이 할 일과 맞는지
const mins = [2,13,15,20,21,30,43,45], hrs = [21,22,23,0,1,2,3,4,5,6,7];
const hit = new Set();
for (const h of hrs) for (const m of mins) { const k = kst(Date.UTC(2026,10,27,h,m) - (h >= 21 ? 864e5 : 0)).hm; if (SLOTS[k]) hit.add(k); }
console.log("cron 으로 깨는 할 일 시각:", [...hit].sort().join(" "), "| 빠진 것:", Object.keys(SLOTS).filter(k => !hit.has(k)));
for (const [s, note] of [["2026-11-26T21:43:00Z","금 06:43 pre"],["2026-11-26T22:20:00Z","금 07:20 pre? (있음)"],["2026-11-26T23:13:00Z","금 08:13 am? (진행 중)"],
  ["2026-11-27T03:02:00Z","금 12:02 pm? (없음)"],["2026-11-27T07:21:00Z","금 16:21 eve"],["2026-11-27T07:45:00Z","금 16:45 eve? (옛것)"],["2026-11-27T22:43:00Z","토 07:43"],["2026-11-27T05:02:00Z","금 14:02"]]) {
  log.length = 0; const out = await tick(env, at(s)); console.log("\n#", note); out.forEach(l => console.log(" ", l)); log.forEach(l => console.log("   ↳", l));
}
state.pre.status = ["야간선물 없음"]; log.length = 0;
console.log("\n# 07:20 pre? (빠진 값 있음)"); (await tick(env, at("2026-11-26T22:20:00Z"))).forEach(l => console.log(" ", l));
