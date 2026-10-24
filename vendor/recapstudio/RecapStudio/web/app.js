/* Recap Studio — frontend */
"use strict";

const state = {
  bootstrap: null,
  projects: [],
  current: null,     // project name
  detail: null,
  segments: { youtube: [], tiktok: {} },
  missing: [],
  tab: "dashboard",
};

let activeJob = null;
let shownLines = 0;

const $ = (id) => document.getElementById(id);

function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function fmtBytes(n) {
  if (n == null) return "";
  if (n < 1024) return n + " B";
  if (n < 1048576) return (n / 1024).toFixed(1) + " KB";
  if (n < 1073741824) return (n / 1048576).toFixed(1) + " MB";
  return (n / 1073741824).toFixed(2) + " GB";
}

function wordsToSec(text) {
  const words = (text || "").split(/\s+/).filter(Boolean).length;
  return Math.round((words / 2.5) * 10) / 10;
}

async function apiGet(path) {
  const r = await fetch(path);
  return r.json();
}

async function apiPost(path, body) {
  const r = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  return r.json();
}

function enc(p) { return encodeURIComponent(p); }

function fileUrl(rel) {
  const segs = String(rel).split("/").map(enc).join("/");
  return "/api/projects/" + enc(state.current) + "/file/" + segs;
}

let toastTimer = null;
function toast(msg) {
  const t = $("toast");
  t.textContent = msg;
  t.classList.remove("hidden");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.add("hidden"), 3500);
}

function openModal(html) {
  $("modalBox").innerHTML = html;
  $("modal").classList.remove("hidden");
}
function closeModal() {
  $("modal").classList.add("hidden");
  $("modalBox").innerHTML = "";
}

function previewModal(url, kind) {
  let inner;
  if (kind === "image") inner = '<img src="' + url + '">';
  else if (kind === "video") inner = '<video src="' + url + '" controls autoplay></video>';
  else if (kind === "audio") inner = '<audio src="' + url + '" controls autoplay></audio>';
  else inner = '<p class="muted">No inline preview.</p>';
  openModal(inner + '<div style="margin-top:12px"><a class="btn" href="' + url + '" download>Download / open</a> <button class="btn ghost" onclick="closeModal()">Close</button></div>');
}

/* ------------------------------------------------------------------ */
/* bootstrap + projects                                                */
/* ------------------------------------------------------------------ */
async function init() {
  state.bootstrap = await apiGet("/api/bootstrap");
  renderTools();
  bindStatic();
  pollRunning();
  await refreshProjects();
  if (state.projects.length && !state.current) await selectProject(state.projects[0].name);
}

function bindStatic() {
  $("newProjectBtn").addEventListener("click", newProjectModal);
  $("openFolderBtn").addEventListener("click", () => apiPost("/api/projects/" + enc(state.current) + "/open"));
  $("keysBtn").addEventListener("click", keysModal);
  $("consoleClose").addEventListener("click", closeConsole);
  $("consoleStop").addEventListener("click", () => stopJob());
  $("modal").addEventListener("click", (e) => { if (e.target === $("modal")) closeModal(); });
  document.querySelectorAll("#tabs .tab").forEach((b) => {
    b.addEventListener("click", () => switchTab(b.dataset.tab));
  });
}

function renderTools() {
  const t = state.bootstrap.tools;
  const rows = [
    ["FFmpeg", t.ffmpeg], ["ffprobe", t.ffprobe], ["yt-dlp", t.ytdlp],
    ["edge-tts", t.edge_tts], ["requests", t.requests],
    ["ElevenLabs keys", t.keys.ELEVENLABS_API_KEY], ["MiniMax keys", t.keys.MINIMAX_API_KEY],
  ];
  $("toolsStatus").innerHTML =
    '<div class="row muted" style="font-weight:700;padding-bottom:4px">Tools</div>' +
    rows.map(([n, v]) =>
      '<div class="row"><span class="' + (v ? "ok" : "bad") + '">●</span> ' + n +
      (typeof v === "number" ? " (" + v + ")" : "") + "</div>").join("");
}

async function refreshProjects() {
  state.projects = await apiGet("/api/projects");
  renderProjectList();
}

function renderProjectList() {
  const list = $("projectList");
  if (!state.projects.length) {
    list.innerHTML = '<div class="muted" style="padding:8px">No projects yet.</div>';
    return;
  }
  list.innerHTML = state.projects.map((p) => {
    const modLabel = (state.bootstrap.modules.find(m => m[0] === p.module) || [p.module, p.module])[1];
    return '<div class="project-item ' + (p.name === state.current ? "active" : "") + '" data-name="' + esc(p.name) + '">' +
      '<div class="pname">' + esc(p.name) + '</div>' +
      '<div class="pmeta">' + esc(modLabel) + ' · ' + p.segments + ' seg</div>' +
    '</div>';
  }).join("");
  list.querySelectorAll(".project-item").forEach((el) => {
    el.addEventListener("click", () => selectProject(el.dataset.name));
  });
}

async function selectProject(name) {
  state.current = name;
  state.tab = "dashboard";
  await loadDetail();
  renderProjectList();
  switchTab("dashboard");
}

async function loadDetail() {
  if (!state.current) return;
  const d = await apiGet("/api/projects/" + enc(state.current));
  if (d.error) { toast(d.error); return; }
  state.detail = d;
  const seg = await apiGet("/api/projects/" + enc(state.current) + "/segments");
  state.segments = (seg && !seg.error) ? seg : { youtube: [], tiktok: {} };
  $("emptyState").classList.add("hidden");
  $("projectView").classList.remove("hidden");
  renderHeader();
}

function renderHeader() {
  const d = state.detail;
  $("projTitle").textContent = d.name;
  const p = d.project;
  const modLabel = (state.bootstrap.modules.find(m => m[0] === p.module) || [p.module, p.module])[1];
  $("projMeta").innerHTML =
    '<span class="badge">' + esc(modLabel) + '</span>' +
    (p.topic ? '<span class="badge">' + esc(p.topic) + '</span>' : "") +
    (p.target_length ? '<span class="badge">' + esc(p.target_length) + '</span>' : "") +
    '<span class="badge">' + d.segment_counts.youtube + ' segments</span>' +
    (d.segment_counts.tiktok ? '<span class="badge">' + d.segment_counts.tiktok + ' tiktok</span>' : "") +
    (d.engine_current ? "" : '<span class="badge amber">engine outdated</span>');
}

function switchTab(tab) {
  state.tab = tab;
  document.querySelectorAll("#tabs .tab").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
  renderTab();
}

function renderTab() {
  const c = $("tabContent");
  if (!state.detail) return;
  if (state.tab === "dashboard") renderDashboard(c);
  else if (state.tab === "pipeline") renderPipeline(c);
  else if (state.tab === "script") renderScript(c);
  else if (state.tab === "footage") renderFootage(c);
  else if (state.tab === "voice") renderVoice(c);
  else if (state.tab === "outputs") renderOutputs(c);
  else if (state.tab === "settings") renderSettings(c);
}

/* ------------------------------------------------------------------ */
/* console + jobs                                                      */
/* ------------------------------------------------------------------ */
function fmtDur(sec) {
  sec = Math.max(0, Math.round(sec || 0));
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), r = sec % 60;
  return (h ? h + ":" + String(m).padStart(2, "0") : m) + ":" + String(r).padStart(2, "0");
}

// progress bar + "12/40 · label · 1:20 elapsed · ~2:30 left"
function renderProgress(j) {
  const wrap = $("consoleProgress"), fill = $("pbarFill"), info = $("pinfo");
  const running = j.status === "running";
  wrap.classList.remove("hidden");
  const pr = j.progress;
  const elapsed = j.elapsed != null ? j.elapsed : (Date.now() / 1000 - j.started);
  let text = fmtDur(elapsed) + " elapsed";
  if (pr && pr.total > 0) {
    const frac = Math.min(1, pr.done / pr.total);
    fill.classList.remove("indeterminate");
    fill.style.width = (running ? frac * 100 : (j.status === "done" ? 100 : frac * 100)) + "%";
    text = pr.done + " / " + pr.total + " (" + Math.round(frac * 100) + "%)" +
      (pr.label ? " · " + pr.label : "") + " · " + text;
    if (running && pr.done > 0 && frac < 1) text += " · ~" + fmtDur(elapsed / pr.done * (pr.total - pr.done)) + " left";
  } else if (running) {
    fill.classList.add("indeterminate");
    text = "working… (this step has no exact progress) · " + text;
  } else {
    fill.classList.remove("indeterminate");
    fill.style.width = j.status === "done" ? "100%" : "0";
  }
  info.textContent = text;
}

function appendLog(j) {
  const logEl = $("consoleLog");
  const lines = j.log || [];
  if (lines.length < shownLines) { logEl.textContent = ""; shownLines = 0; }
  if (lines.length > shownLines) {
    const frag = document.createDocumentFragment();
    for (let i = shownLines; i < lines.length; i++) frag.appendChild(document.createTextNode(lines[i] + "\n"));
    logEl.appendChild(frag);
    shownLines = lines.length;
    logEl.scrollTop = logEl.scrollHeight;
  }
}

function openConsole(title) {
  $("consoleTitle").textContent = title;
  $("consoleStatus").textContent = "running…";
  $("consoleStatus").className = "console-status";
  $("consoleLog").textContent = "";
  $("consoleProgress").classList.add("hidden");
  $("consoleStop").classList.remove("hidden");
  $("consoleStop").disabled = false;
  $("consoleStop").textContent = "■ Stop";
  shownLines = 0;
  $("consoleWrap").classList.remove("hidden");
}
function closeConsole() {
  $("consoleWrap").classList.add("hidden");
}
function setConsoleStatus(status) {
  const el = $("consoleStatus");
  el.className = "console-status " + status;
  el.textContent = status === "done" ? "done ✓" : status === "error" ? "failed ✗"
    : status === "stopped" ? "stopped ■" : "running…";
  if (status !== "running") $("consoleStop").classList.add("hidden");
}

async function stopJob(jid) {
  jid = jid || activeJobId();
  if (!jid) return;
  if (!confirm("Stop this step now?\n\nWork already finished is kept; run the step again to continue (voice-over only redoes what's missing).")) return;
  const btn = $("consoleStop");
  btn.disabled = true; btn.textContent = "Stopping…";
  const r = await apiPost("/api/jobs/" + jid + "/stop");
  if (r.error) toast(r.error);
  pollRunning();
}

function activeJobId() { return activeJob || currentJobId; }

// reopen the console on a job that is already running (e.g. from the "Running now" box)
async function attachJob(jid, project) {
  if (project && project !== state.current) await selectProject(project);
  const j = await apiGet("/api/jobs/" + jid);
  if (!j || j.error) return;
  activeJob = jid;
  openConsole(j.label || j.step);
  pollJob();
}

async function startJob(step, flags, label) {
  if (!state.current) return;
  const res = await apiPost("/api/projects/" + enc(state.current) + "/run", { step, flags });
  if (res.error) {
    if (res.job) { toast("Something is already running on this project - showing it."); attachJob(res.job); }
    else toast(res.error);
    return;
  }
  activeJob = res.job;
  openConsole(label || step);
  pollJob();
}

let currentJobId = null;

async function pollJob() {
  if (!activeJob) return;
  const jid = activeJob;
  currentJobId = jid;
  const j = await apiGet("/api/jobs/" + jid);
  if (!j || j.error) return;
  if (activeJob !== jid) return;
  appendLog(j);
  renderProgress(j);
  if (j.status === "running") {
    setConsoleStatus("running");
    setTimeout(pollJob, 450);
  } else {
    setConsoleStatus(j.status);
    activeJob = null;
    pollRunning();
    await refreshAfterJob();
  }
}

/* ---- "Running now" box in the sidebar: what is running, on which project, with Stop ---- */
let runningTimer = null;
async function pollRunning() {
  clearTimeout(runningTimer);
  let data;
  try { data = await apiGet("/api/jobs"); } catch (e) { data = null; }
  const box = $("runningBox");
  const run = data && data.jobs ? data.jobs.filter((j) => j.status === "running") : [];
  if (!run.length) {
    box.classList.add("hidden");
  } else {
    box.classList.remove("hidden");
    box.innerHTML = '<div class="rtitle"><span class="dot-run"></span>Running now</div>' + run.map((j) => {
      const pr = j.progress;
      const pct = pr && pr.total ? Math.round(pr.done / pr.total * 100) : null;
      return '<div class="rjob" onclick="attachJob(\'' + j.id + '\',\'' + esc(j.project).replace(/\\/g, "\\\\").replace(/'/g, "\\'") + '\')">' +
        '<div class="rname"><b>' + esc(j.label || j.step) + '</b>' +
        '<button class="btn danger small" onclick="event.stopPropagation();stopJob(\'' + j.id + '\')">■ Stop</button></div>' +
        '<div class="rsub">' + esc(j.project) + ' · ' + fmtDur(j.elapsed) +
          (pr && pr.label ? ' · ' + esc(pr.label) : "") + '</div>' +
        '<div class="pbar"><div class="pbar-fill' + (pct == null ? " indeterminate" : "") + '" style="width:' + (pct == null ? 35 : pct) + '%"></div></div>' +
        '</div>';
    }).join("");
  }
  runningTimer = setTimeout(pollRunning, run.length ? 1500 : 4000);
}

async function refreshAfterJob() {
  await refreshProjects();
  await loadDetail();
  if (state.tab === "footage") await loadMissing();
  renderTab();
}

/* ------------------------------------------------------------------ */
/* dashboard                                                           */
/* ------------------------------------------------------------------ */
function renderDashboard(c) {
  const d = state.detail, p = d.project;
  const modLabel = (state.bootstrap.modules.find(m => m[0] === p.module) || [p.module, p.module])[1];
  const out = d.outputs;
  const outBadges = [
    ["Final video", out.video], ["Premiere XML", out.premiere], ["VideoPad project", out.videopad], ["Subtitles", out.srt],
    ["Chapters", out.chapters], ["Shot list", out.shot_manifest], ["Credits", out.credits],
  ].map(([n, ok]) => '<span class="badge ' + (ok ? "good" : "") + '">' + n + (ok ? " ✓" : "") + "</span>").join("");

  c.innerHTML =
    '<div class="grid cols2">' +
      '<div class="card">' +
        '<h3 style="margin-top:0">Project</h3>' +
        '<div class="badges" style="margin-bottom:10px">' +
          '<span class="badge">' + esc(modLabel) + '</span>' +
          (p.topic ? '<span class="badge">' + esc(p.topic) + '</span>' : "") +
          '<span class="badge">' + esc(p.platform) + '</span>' +
          '<span class="badge">tts: ' + esc(p.tts_mode) + '</span>' +
        '</div>' +
        '<div class="muted" style="font-size:13px;line-height:1.6">' +
          '<div>Target length: <b>' + esc(p.target_length || "module default") + '</b></div>' +
          '<div>Segments: <b>' + d.segment_counts.youtube + '</b> youtube' +
            (d.segment_counts.tiktok ? ' · <b>' + d.segment_counts.tiktok + '</b> tiktok' : "") + '</div>' +
          '<div>Style: <b>' + esc(p.style || "—") + '</b> · Music bed: <b>' + (p.music ? "on" : "off") + '</b> · Captions: <b>' + (p.captions ? "on" : "off") + '</b></div>' +
        '</div>' +
        '<div style="margin-top:12px"><button class="btn" onclick="switchTab(\'settings\')">Edit settings</button> ' +
        '<button class="btn ghost" onclick="switchTab(\'script\')">Open script</button></div>' +
      '</div>' +
      '<div class="card">' +
        '<h3 style="margin-top:0">Outputs</h3>' +
        '<div class="badges">' + outBadges + '</div>' +
        '<div style="margin-top:12px"><button class="btn" onclick="switchTab(\'outputs\')">View outputs</button></div>' +
      '</div>' +
    '</div>' +
    (d.state ? '<div class="section" style="margin-top:20px"><h3>Status / next steps</h3><pre class="state">' + esc(d.state) + '</pre></div>' : "");
}

/* ------------------------------------------------------------------ */
/* pipeline (run steps)                                                */
/* ------------------------------------------------------------------ */
function isRecap() {
  const m = state.detail.project.module;
  return m === "movie_recap" || m === "show_recap";
}

function pipelineSteps() {
  const engine = (state.detail.config.tts && state.detail.config.tts.engine) || "edge";
  const steps = [];
  if (isRecap()) steps.push({ step: "subs", name: "Extract subtitles", desc: state.detail.project.module === "show_recap"
    ? "Pull the subtitles out of EVERY episode in footage/ in one run. Also makes subs/ALL_EPISODES_for_claude.txt - the one file to give Claude."
    : "Pull embedded subtitle tracks from the film into subs/." });
  else steps.push({ step: "index", name: "Index footage", desc: "Contact sheets for every clip in footage/." });
  steps.push({ step: "sheets", name: "Contact sheets", desc: "Sheets for segments marked need_visual." });
  steps.push({ step: "review", name: "Export review sheet", desc: "Write review_sheet.csv (optional Excel workflow)." });
  steps.push({ step: "tts", name: "Voice-over", desc: "Generate narration audio (only new / edited segments).", engine });
  steps.push({ step: "premiere", name: "Build Premiere XML", desc: "Cut clips + multi-track XML (+ srt, chapters, shot list)." });
  steps.push({ step: "videopad", name: "Build VideoPad project", desc: "Same timeline as a VideoPad .vpj (V1/V2 + A1-A3). Click Try Load when VideoPad warns." });
  steps.push({ step: "videopad_simple", name: "Build VideoPad project (simple)", desc: "Fallback: picture + voice only, one file per segment. Use if the full project will not open." });
  steps.push({ step: "srt", name: "Build subtitles", desc: "Write recap_subtitles.srt for Premiere." });
  if (isRecap()) {
    steps.push({ step: "video", name: "Build full video", desc: "One finished recap_final.mp4." });
    steps.push({ step: "tiktok", name: "Build TikTok", desc: "Vertical 9:16 parts into tiktok_out/." });
  }
  steps.push({ step: "check", name: "Status check", desc: "Report + rewrite STATE.md." });
  steps.push({ step: "demo", name: "Demo / test media", desc: "Fill with synthetic media (use a fresh project)." });
  return steps;
}

function runStep(step) {
  const s = pipelineSteps().find(x => x.step === step);
  const flags = {};
  if ($("forceChk") && $("forceChk").checked) flags.force = true;
  if (step === "tts") flags.engine = s.engine;
  if (step === "videopad_simple") { flags.simple = true; step = "videopad"; }
  startJob(step, flags, s.name);
}

function runPreview() {
  const s = pipelineSteps().find(x => x.step === "tts");
  startJob("tts", { engine: s.engine, preview: true }, "Preview voice (3 segments)");
}

function runAll() {
  const seq = isRecap() ? ["subs", "sheets", "tts", "premiere", "srt"]
                        : ["index", "sheets", "tts", "premiere", "srt"];
  runSequence(seq);
}

async function runSequence(steps) {
  openConsole("Run all");
  for (const step of steps) {
    const s = pipelineSteps().find(x => x.step === step);
    const flags = { engine: (state.detail.config.tts && state.detail.config.tts.engine) || "edge" };
    const res = await apiPost("/api/projects/" + enc(state.current) + "/run", { step, flags });
    if (res.error) { toast(res.error); closeConsole(); return; }
    activeJob = res.job;
    currentJobId = res.job;
    $("consoleTitle").textContent = "Run all → " + s.name;
    $("consoleStop").classList.remove("hidden");
    $("consoleStop").disabled = false;
    $("consoleStop").textContent = "■ Stop";
    $("consoleLog").textContent = ""; shownLines = 0;
    let j = { status: "running" };
    while (j && j.status === "running") {
      await new Promise(r => setTimeout(r, 500));
      j = await apiGet("/api/jobs/" + res.job);
      if (!j || j.error) break;
      appendLog(j);
      renderProgress(j);
    }
    setConsoleStatus(j.status);
    if (j.status !== "done") { toast(j.status === "stopped" ? "Stopped at: " + s.name : "Stopped at step: " + s.name); break; }
  }
  activeJob = null;
  pollRunning();
  await refreshAfterJob();
}

function renderPipeline(c) {
  const steps = pipelineSteps();
  c.innerHTML =
    '<div class="section">' +
      '<div style="display:flex;align-items:center;gap:16px;margin-bottom:14px;flex-wrap:wrap">' +
        '<button class="btn primary" onclick="runAll()">▶ Run all</button>' +
        '<label class="check" style="margin:0"><input type="checkbox" id="forceChk"> Force redo (overwrite outputs)</label>' +
      '</div>' +
      '<div class="step-grid">' +
        steps.map((s) => {
          let actions;
          if (s.step === "tts") {
            actions = '<button class="btn primary small" onclick="runStep(\'tts\')">Generate</button>' +
                      '<button class="btn small" onclick="runPreview()">Preview</button>';
          } else if (s.step === "video") {
            actions = '<button class="btn primary small" onclick="runStep(\'video\')">Build</button>';
          } else if (s.step === "premiere" || s.step === "videopad") {
            actions = '<button class="btn primary small" onclick="runStep(\'' + s.step + '\')">Build</button>';
          } else {
            actions = '<button class="btn small" onclick="runStep(\'' + s.step + '\')">Run</button>';
          }
          return '<div class="step">' +
            '<div class="sname">' + esc(s.name) + '</div>' +
            '<div class="sdesc">' + esc(s.desc) + '</div>' +
            '<div class="row">' + actions + '</div>' +
          '</div>';
        }).join("") +
      '</div>' +
    '</div>' +
    '<p class="muted">For guided footage collection and drag-and-drop uploads, use the <b>Footage</b> tab.</p>';
}

/* ------------------------------------------------------------------ */
/* script (segments editor)                                            */
/* ------------------------------------------------------------------ */
function segField(label, f, value, textarea) {
  value = value == null ? "" : value;
  return '<div><label>' + esc(label) + '</label>' +
    (textarea
      ? '<textarea data-f="' + f + '">' + esc(value) + '</textarea>'
      : '<input data-f="' + f + '" value="' + esc(value) + '">') +
    '</div>';
}

function renderSegmentCard(seg, part) {
  const shot = seg.shot || {};
  const est = wordsToSec(seg.narration);
  return '<div class="seg" data-part="' + part + '" data-id="' + esc(seg.id || "") + '">' +
    '<div class="seg-head">' +
      '<span class="seg-id">' + esc(seg.id || "(new)") + '</span>' +
      '<span class="seg-est">~' + est + 's voice</span>' +
      '<button class="btn danger small" onclick="removeSeg(this)">Remove</button>' +
    '</div>' +
    '<label>Narration</label>' +
    '<textarea class="narration" data-f="narration">' + esc(seg.narration) + '</textarea>' +
    '<div class="mini-grid">' +
      segField("src_start", "src_start", seg.src_start) +
      segField("src_end", "src_end", seg.src_end) +
      segField("src (file)", "src", seg.src) +
      segField("image (file)", "image", seg.image) +
      segField("subtitle", "subtitle", seg.subtitle) +
      segField("caption", "caption", seg.caption) +
      segField("rank", "rank", seg.rank) +
      segField("chapter", "chapter", seg.chapter) +
    '</div>' +
    '<div class="mini-grid">' +
      segField("Shot description", "shot.description", shot.description) +
      segField("Shot queries (one per line)", "shot.queries", (shot.queries || []).join("\n"), true) +
      segField("Shot fallback", "shot.fallback", shot.fallback) +
    '</div>' +
    '<label class="check"><input type="checkbox" data-f="keep_audio"' + (seg.keep_audio ? " checked" : "") + '> keep original audio</label>' +
    '<label class="check"><input type="checkbox" data-f="need_visual"' + (seg.need_visual ? " checked" : "") + '> need contact sheet</label>' +
  '</div>';
}

function removeSeg(btn) {
  btn.closest(".seg").remove();
}

function readSegCard(card) {
  const get = (f) => { const el = card.querySelector('[data-f="' + f + '"]'); return el ? el.value : ""; };
  const checked = (f) => { const el = card.querySelector('[data-f="' + f + '"]'); return el ? el.checked : false; };
  const seg = { id: card.dataset.id || "" };
  const set = (k, v) => { if (v !== "" && v !== false) seg[k] = v; };
  set("narration", get("narration"));
  set("src_start", get("src_start"));
  set("src_end", get("src_end"));
  set("src", get("src"));
  set("image", get("image"));
  set("subtitle", get("subtitle"));
  set("caption", get("caption"));
  set("rank", get("rank"));
  set("chapter", get("chapter"));
  if (checked("keep_audio")) seg.keep_audio = true;
  if (checked("need_visual")) seg.need_visual = true;
  const sd = get("shot.description"), sq = get("shot.queries"), sf = get("shot.fallback");
  if (sd || sq || sf) {
    seg.shot = {};
    if (sd) seg.shot.description = sd;
    if (sf) seg.shot.fallback = sf;
    if (sq) seg.shot.queries = sq.split("\n").map(s => s.trim()).filter(Boolean);
  }
  return seg;
}

function collectSegmentsFromDOM() {
  const youtube = [], tiktok = {};
  document.querySelectorAll(".seg").forEach((card) => {
    const part = card.dataset.part;
    const seg = readSegCard(card);
    if (!seg.id) return;
    if (part === "youtube") youtube.push(seg);
    else {
      const p = part.replace("tiktok:", "");
      (tiktok[p] = tiktok[p] || []).push(seg);
    }
  });
  return { youtube, tiktok };
}

async function saveScript() {
  const seg = collectSegmentsFromDOM();
  const res = await apiPost("/api/projects/" + enc(state.current) + "/segments", { segments: seg });
  if (res.error) { toast(res.error); return; }
  toast("Script saved ✓");
  await loadDetail();
}

function addSegment() {
  const n = document.querySelectorAll('.seg[data-part="youtube"]').length + 1;
  const id = "yt_" + String(n).padStart(3, "0");
  const div = document.createElement("div");
  div.innerHTML = renderSegmentCard({ id, narration: "" }, "youtube");
  document.getElementById("segmentsWrap").appendChild(div.firstElementChild);
  div.firstElementChild.scrollIntoView({ behavior: "smooth" });
}

async function importPaste() {
  const text = document.getElementById("pasteText").value;
  if (!text.trim()) { toast("Paste Claude's reply first."); return; }
  const res = await apiPost("/api/projects/" + enc(state.current) + "/paste", { text });
  if (res.error) { toast(res.error); return; }
  toast("Imported: " + res.youtube + " segments" + (res.tiktok ? ", " + res.tiktok + " tiktok" : ""));
  await loadDetail();
  renderTab();
}

function copyPrompt() {
  navigator.clipboard.writeText(document.getElementById("promptText").textContent)
    .then(() => toast("Prompt copied ✓"), () => toast("Copy failed"));
}

function toggleRaw() {
  document.getElementById("rawWrap").classList.toggle("hidden");
}

async function saveRaw() {
  try {
    const obj = JSON.parse(document.getElementById("rawJson").value);
    const res = await apiPost("/api/projects/" + enc(state.current) + "/segments", { segments: obj });
    if (res.error) { toast(res.error); return; }
    toast("Raw JSON saved ✓");
    await loadDetail();
    renderTab();
  } catch (e) { toast("Invalid JSON: " + e.message); }
}

function renderScript(c) {
  const d = state.detail;
  const yt = state.segments.youtube || [];
  const tt = state.segments.tiktok || {};
  const parts = Object.keys(tt).map((p) =>
    '<div class="section"><h3>TikTok · ' + esc(p) + '</h3>' +
    (tt[p] || []).map((s) => renderSegmentCard(s, "tiktok:" + p)).join("") + '</div>').join("");

  c.innerHTML =
    '<div class="section">' +
      '<h3>Claude prompt</h3>' +
      '<div class="card">' +
        (d.prompt
          ? '<div style="max-height:160px;overflow:auto" class="mono" id="promptText">' + esc(d.prompt) + '</div>' +
            '<button class="btn small" style="margin-top:8px" onclick="copyPrompt()">Copy prompt</button>'
          : '<p class="muted">No PASTE_THIS_TO_CLAUDE.txt in this project yet.</p>') +
      '</div>' +
    '</div>' +
    '<div class="section">' +
      '<h3>Paste Claude\'s reply</h3>' +
      '<div class="card">' +
        '<textarea id="pasteText" style="min-height:90px" placeholder="Paste Claude\'s whole answer here (the JSON is extracted automatically)…"></textarea>' +
        '<button class="btn primary" style="margin-top:8px" onclick="importPaste()">Import JSON</button>' +
      '</div>' +
    '</div>' +
    '<div class="section">' +
      '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">' +
        '<h3 style="margin:0">Segments (' + yt.length + ')</h3>' +
        '<div><button class="btn small" onclick="addSegment()">＋ Add segment</button> ' +
        '<button class="btn small ghost" onclick="toggleRaw()">Raw JSON</button></div>' +
      '</div>' +
      '<div id="segmentsWrap">' + yt.map((s) => renderSegmentCard(s, "youtube")).join("") + '</div>' +
      parts +
      '<div class="card hidden" id="rawWrap" style="margin-top:12px">' +
        '<label>Raw segments.json</label>' +
        '<textarea id="rawJson" style="min-height:200px;font-family:monospace">' + esc(JSON.stringify(state.segments, null, 2)) + '</textarea>' +
        '<button class="btn small" style="margin-top:8px" onclick="saveRaw()">Save raw JSON</button>' +
      '</div>' +
      '<div style="margin-top:12px"><button class="btn primary" onclick="saveScript()">💾 Save script</button></div>' +
    '</div>';
}

/* ------------------------------------------------------------------ */
/* footage (collect + upload)                                          */
/* ------------------------------------------------------------------ */
async function loadMissing() {
  const m = await apiGet("/api/projects/" + enc(state.current) + "/missing");
  state.missing = Array.isArray(m) ? m : [];
  if (m && m.error) state.missing = [{ id: "error", missing: true, why: m.error }];
}

function searchLinks(queries) {
  const kinds = [
    "https://www.youtube.com/results?search_query=",
    "https://x.com/search?f=video&q=",
    "https://www.google.com/search?tbm=isch&q=",
  ];
  return (queries || []).slice(0, 3).map((q, i) =>
    '<a href="' + kinds[i] + encodeURIComponent(q) + '" target="_blank" rel="noopener">' + esc(q) + '</a>').join("");
}

async function uploadFile(folder, file, id) {
  folder = folder || "footage";
  const url = "/api/projects/" + enc(state.current) + "/upload?folder=" + enc(folder) +
    "&name=" + enc(file.name) + (id ? "&id=" + enc(id) : "");
  const r = await fetch(url, { method: "POST", body: file });
  const j = await r.json();
  if (j.error) { toast(j.error); return; }
  if (id) {
    toast(j.ok ? "Attached to shot ✓" : "Attach failed");
    await loadMissing();
  } else {
    toast("Uploaded ✓");
    await loadDetail();
  }
  renderTab();
}

function uploadFileInput(input, folder, id) {
  const files = Array.from(input.files || []);
  input.value = "";
  if (!files.length) return;
  if (files.length === 1 || id) uploadFile(folder, files[0], id);
  else uploadMany(folder, files);
}

// several files at once (e.g. all episodes of a season): sent one after another, with progress
async function uploadMany(folder, files) {
  files.sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true }));
  let ok = 0;
  for (let i = 0; i < files.length; i++) {
    toast("Uploading " + (i + 1) + " of " + files.length + ": " + files[i].name + " …");
    try {
      const url = "/api/projects/" + enc(state.current) + "/upload?folder=" + enc(folder) +
        "&name=" + enc(files[i].name);
      const j = await (await fetch(url, { method: "POST", body: files[i] })).json();
      if (j.error) { toast(files[i].name + ": " + j.error); continue; }
      ok++;
    } catch (e) { toast("Upload failed: " + files[i].name); }
  }
  toast("Uploaded " + ok + " of " + files.length + " ✓");
  await loadDetail();
  renderTab();
}

async function downloadShot(id) {
  const urlEl = document.querySelector('[data-shot-url="' + id + '"]');
  const rngEl = document.querySelector('[data-shot-range="' + id + '"]');
  const url = urlEl ? urlEl.value.trim() : "";
  if (!url) { toast("Paste a URL first."); return; }
  const res = await apiPost("/api/projects/" + enc(state.current) + "/download",
    { id, url, range: rngEl ? rngEl.value.trim() : "" });
  if (res.error) { toast(res.error); return; }
  activeJob = res.job;
  openConsole("Download " + id);
  pollJob();
}

async function skipShot(id) {
  const res = await apiPost("/api/projects/" + enc(state.current) + "/skip", { id });
  if (res.error) { toast(res.error); return; }
  activeJob = res.job;
  openConsole("Skip " + id);
  pollJob();
}

function mediaItem(name, kind, url) {
  let inner;
  if (kind === "image") inner = '<img class="thumb" src="' + url + '" loading="lazy">';
  else if (kind === "video") inner = '<div class="thumb" style="display:grid;place-items:center">🎞️</div>';
  else if (kind === "audio") inner = '<div class="thumb" style="display:grid;place-items:center">🎵</div>';
  else inner = '<div class="thumb" style="display:grid;place-items:center">📄</div>';
  return '<div class="media-item" onclick="previewModal(\'' + url + '\',\'' + kind + '\')">' + inner +
    '<div class="mname" title="' + esc(name) + '">' + esc(name) + '</div></div>';
}

function episodesSection(d) {
  const eps = (d.files.footage || []).filter((f) => f.kind === "video");
  return '<div class="section"><h3>Episodes</h3>' +
    '<div class="card">' +
      '<p class="muted" style="margin-top:0">Select <b>all the episodes at once</b> (Ctrl+A in the file picker). ' +
      'They are saved in footage/. For a whole season, <b>📂 Open folder</b> and drag them into <code>footage</code> is faster. ' +
      'Then go to <b>Run steps → Extract subtitles</b>: it does every episode in one go.</p>' +
      '<label class="btn primary small" style="display:inline-block">⬆ Upload episodes (many at once)' +
        '<input type="file" multiple accept="video/*,.mkv,.ts,.m2ts" style="display:none" onchange="uploadFileInput(this,\'footage\')"></label>' +
      '<div class="muted" style="margin-top:10px"><b>' + eps.length + '</b> episode file(s) in footage/' +
        (eps.length ? ': ' + eps.map((f) => esc(f.name)).join(", ") : "") + '</div>' +
    '</div></div>';
}

function folderSection(title, folder, files, allowUpload) {
  const items = (files || []).map((f) =>
    mediaItem(f.name, f.kind, fileUrl(folder + "/" + f.name))).join("");
  return '<div class="section"><h3>' + title + '</h3>' +
    (allowUpload ? '<label class="btn small" style="margin-bottom:8px;display:inline-block">⬆ Upload ' +
      '<input type="file" multiple style="display:none" onchange="uploadFileInput(this,\'' + folder + '\')"></label>' : "") +
    '<div class="media-grid">' + (items || '<div class="muted">empty</div>') + '</div></div>';
}

async function renderFootage(c) {
  await loadMissing();
  const d = state.detail;
  const missing = state.missing.filter((m) => m.missing);
  const shotHtml = missing.length
    ? missing.map((m) => {
        const st = m.status === "skipped" ? '<span class="badge amber">skipped</span>'
                 : m.status === "done" ? '<span class="badge good">done</span>' : "";
        return '<div class="shot">' +
          '<div class="seg-head"><span class="seg-id">' + esc(m.id) + '</span>' + st + '</div>' +
          (m.description ? '<div class="desc">' + esc(m.description) + '</div>' : "") +
          (m.narration ? '<div class="muted">' + esc(m.narration) + '</div>' : "") +
          (m.queries && m.queries.length ? '<div class="queries">' + searchLinks(m.queries) + '</div>' : "") +
          (m.fallback ? '<div class="muted">Fallback: ' + esc(m.fallback) + '</div>' : "") +
          '<div class="row" style="display:flex;gap:8px;margin-top:10px;flex-wrap:wrap">' +
            '<input data-shot-url="' + esc(m.id) + '" placeholder="https://…  (with optional range)" style="flex:1;min-width:200px">' +
            '<input data-shot-range="' + esc(m.id) + '" placeholder="1:42-1:51" style="width:110px">' +
            '<button class="btn primary small" onclick="downloadShot(\'' + esc(m.id) + '\')">Download</button>' +
            '<button class="btn small" onclick="skipShot(\'' + esc(m.id) + '\')">Skip</button>' +
            '<label class="btn small" style="margin:0">📎 Attach file<input type="file" style="display:none" onchange="uploadFileInput(this,null,\'' + esc(m.id) + '\')"></label>' +
          '</div>' +
        '</div>';
      }).join("")
    : '<div class="card">All segments have footage. 🎉</div>';

  c.innerHTML =
    '<div class="section"><h3>Missing shots (' + missing.length + ')</h3>' + shotHtml + '</div>' +
    (d.project.module === "show_recap" ? episodesSection(d) : "") +
    folderSection("Footage", "footage", d.files.footage, true) +
    folderSection("Images", "images", d.files.images, true) +
    folderSection("Music", "music", d.files.music, true) +
    '<div class="section"><h3>' + (isRecap() ? "The film / episode (project root)" : "Project root media") + '</h3>' +
      (isRecap() ? '<p class="muted">Recaps: put the film here. "Extract subtitles" and single-film recaps look in this folder, ' +
        'not in Footage. Several episodes: see the Show recap guide.</p>' : "") +
      '<label class="btn small" style="margin-bottom:8px;display:inline-block">⬆ Upload video' +
        '<input type="file" multiple accept="video/*,.mkv,.ts,.m2ts" style="display:none" onchange="uploadFileInput(this,\'root\')"></label>' +
      '<div class="media-grid">' + ((d.root_media || []).map((f) => mediaItem(f.name, f.kind, fileUrl(f.name))).join("") ||
        '<div class="muted">empty</div>') + '</div></div>';
}

/* ------------------------------------------------------------------ */
/* voice                                                               */
/* ------------------------------------------------------------------ */
function renderVoice(c) {
  const cfg = state.detail.config || {};
  const t = cfg.tts || {};
  const engine = t.engine || "edge";
  const engOpts = state.bootstrap.engines.map(e =>
    '<option value="' + e[0] + '"' + (e[0] === engine ? " selected" : "") + '>' + esc(e[1]) + '</option>').join("");
  const edgeOpts = state.bootstrap.edge_voices.map(v =>
    '<option value="' + v[0] + '"' + (v[0] === t.edge_voice ? " selected" : "") + '>' + esc(v[1]) + '</option>').join("");
  const mmOpts = state.bootstrap.minimax_voices.map(v =>
    '<option value="' + v[0] + '"' + (v[0] === t.minimax_voice ? " selected" : "") + '>' + esc(v[1]) + '</option>').join("");

  c.innerHTML =
    '<div class="grid cols2">' +
      '<div class="card">' +
        '<h3 style="margin-top:0">Voice settings</h3>' +
        '<label>Engine</label><select id="vEngine" onchange="voiceEngineChange()">' + engOpts + '</select>' +
        '<div id="vEdge" class="' + (engine === "edge" ? "" : "hidden") + '">' +
          '<label>Edge voice</label><select id="vEdgeVoice">' + edgeOpts + '</select>' +
          '<label>Rate</label><input id="vEdgeRate" value="' + esc(t.edge_rate || "+0%") + '">' +
        '</div>' +
        '<div id="vMini" class="' + (engine === "minimax" ? "" : "hidden") + '">' +
          '<label>MiniMax voice</label><select id="vMiniVoice">' + mmOpts + '</select>' +
        '</div>' +
        '<div id="vEleven" class="' + (engine === "elevenlabs" ? "" : "hidden") + '">' +
          '<label>ElevenLabs voice ID</label>' +
          '<div style="display:flex;gap:8px">' +
            '<input id="vElVoice" value="' + esc(t.elevenlabs_voice_id || "") + '" placeholder="voice id">' +
            '<button class="btn small" onclick="fetchElevenLabsVoices()">Fetch</button>' +
          '</div>' +
          '<label>Model</label><input id="vElModel" value="' + esc(t.elevenlabs_model || "eleven_v3") + '">' +
          '<label>Stability</label><input id="vElStab" value="' + esc(t.elevenlabs_stability != null ? t.elevenlabs_stability : 0.5) + '">' +
        '</div>' +
        '<button class="btn primary" style="margin-top:14px" onclick="saveVoiceConfig()">Save voice settings</button>' +
      '</div>' +
      '<div class="card">' +
        '<h3 style="margin-top:0">Generate</h3>' +
        '<p class="muted">Preview voices 3 segments before spending credits; generate only re-voices new/edited text.</p>' +
        '<div class="row" style="display:flex;gap:8px;flex-wrap:wrap">' +
          '<button class="btn" onclick="runVoice(false)">🎙 Generate (changed only)</button>' +
          '<button class="btn" onclick="runVoice(true)">Preview 3 segments</button>' +
          '<button class="btn danger" onclick="runVoice(false, true)">Regenerate all</button>' +
        '</div>' +
        '<div class="muted" style="margin-top:12px">' +
          (state.bootstrap.tools.keys.ELEVENLABS_API_KEY
            ? 'ElevenLabs keys: ' + state.bootstrap.tools.keys.ELEVENLABS_API_KEY + ' · '
            : "") +
          (state.bootstrap.tools.keys.MINIMAX_API_KEY
            ? 'MiniMax keys: ' + state.bootstrap.tools.keys.MINIMAX_API_KEY : "") +
          (state.bootstrap.tools.edge_tts ? "" : '<span class="bad">edge-tts missing (run SETUP.bat)</span>') +
          ' <button class="btn small" onclick="keysModal()">🔑 Manage API keys</button>' +
        '</div>' +
      '</div>' +
    '</div>';
}

function voiceEngineChange() {
  const e = document.getElementById("vEngine").value;
  document.getElementById("vEdge").classList.toggle("hidden", e !== "edge");
  document.getElementById("vMini").classList.toggle("hidden", e !== "minimax");
  document.getElementById("vEleven").classList.toggle("hidden", e !== "elevenlabs");
}

async function saveVoiceConfig() {
  const engine = document.getElementById("vEngine").value;
  const tts = { engine };
  if (engine === "edge") {
    tts.edge_voice = document.getElementById("vEdgeVoice").value;
    tts.edge_rate = document.getElementById("vEdgeRate").value;
  } else if (engine === "minimax") {
    tts.minimax_voice = document.getElementById("vMiniVoice").value;
  } else {
    tts.elevenlabs_voice_id = document.getElementById("vElVoice").value.trim();
    tts.elevenlabs_model = document.getElementById("vElModel").value.trim();
    tts.elevenlabs_stability = parseFloat(document.getElementById("vElStab").value || "0.5");
  }
  const res = await apiPost("/api/projects/" + enc(state.current) + "/config", { config: { tts } });
  if (res.error) { toast(res.error); return; }
  toast("Voice settings saved ✓");
  await loadDetail();
}

async function fetchElevenLabsVoices() {
  const res = await apiPost("/api/elevenlabs/voices", {});
  if (res.error) { toast(res.error); return; }
  const opts = res.voices.map(v => '<option value="' + esc(v.voice_id) + '">' + esc(v.name) + '</option>').join("");
  const el = document.getElementById("vElVoice");
  const cur = el.value;
  el.outerHTML = '<select id="vElVoice">' + opts + '</select>';
  if (cur) document.getElementById("vElVoice").value = cur;
  toast("Loaded " + res.voices.length + " voices");
}

function runVoice(preview, force) {
  const engine = (state.detail.config.tts && state.detail.config.tts.engine) || "edge";
  const flags = { engine };
  if (preview) flags.preview = true;
  if (force) { flags.force = true; flags.yes = true; }
  startJob("tts", flags, force ? "Regenerate all audio" : (preview ? "Preview voice" : "Generate voice-over"));
}

/* ------------------------------------------------------------------ */
/* outputs                                                             */
/* ------------------------------------------------------------------ */
function audioList(folder, title) {
  const files = (state.detail.files[folder] || []).filter(f => f.kind === "audio");
  if (!files.length) return "";
  return '<div class="section"><h3>' + title + '</h3><div class="card">' +
    files.map((f) =>
      '<div style="margin-bottom:10px"><div class="muted" style="font-size:11px">' + esc(f.name) + '</div>' +
      '<audio controls style="width:100%" src="' + fileUrl(folder + "/" + f.name) + '"></audio></div>').join("") +
    '</div></div>';
}

function renderOutputs(c) {
  const d = state.detail, out = d.outputs;
  const sheets = (d.files.sheets || []).filter(f => f.kind === "image");
  const clips = (d.files.clips || []).filter(f => f.kind === "video");
  const downloads = [
    ["Premiere XML", "premiere_sequence.xml", out.premiere],
    ["VideoPad project", "videopad_project.vpj", out.videopad],
    ["Subtitles (.srt)", "recap_subtitles.srt", out.srt],
    ["On-screen text (.srt)", "recap_onscreen.srt", out.onscreen_srt],
    ["Chapters", "chapters.txt", out.chapters],
    ["Shot manifest", "shot_manifest.csv", out.shot_manifest],
    ["Credits / source log", "credits.txt", out.credits],
    ["Review sheet (Excel)", "review_sheet.csv", out.review_csv],
  ].filter(([, , ok]) => ok);

  c.innerHTML =
    (out.video
      ? '<div class="section"><h3>Finished video</h3><div class="card">' +
        '<video controls style="width:100%;max-height:420px;border-radius:8px" src="' + fileUrl("recap_final.mp4") + '"></video>' +
        '<div style="margin-top:8px"><a class="btn small" href="' + fileUrl("recap_final.mp4") + '" download>Download</a></div></div></div>'
      : "") +
    (sheets.length
      ? '<div class="section"><h3>Contact sheets</h3><div class="media-grid">' +
        sheets.map((f) => mediaItem(f.name, f.kind, fileUrl("sheets/" + f.name))).join("") + '</div></div>'
      : "") +
    (clips.length
      ? '<div class="section"><h3>Cut clips</h3><div class="media-grid">' +
        clips.map((f) => mediaItem(f.name, f.kind, fileUrl("clips/" + f.name))).join("") + '</div></div>'
      : "") +
    audioList("audio", "Voice-over (audio/)") +
    audioList("audio_preview", "Preview audio (audio_preview/)") +
    (downloads.length
      ? '<div class="section"><h3>Files</h3><div class="card"><div class="row" style="display:flex;gap:8px;flex-wrap:wrap">' +
        downloads.map(([label, file]) =>
          '<a class="btn small" href="' + fileUrl(file) + '" download>' + esc(label) + '</a>').join("") +
        '</div></div></div>'
      : "") +
    (!out.video && !sheets.length && !clips.length && !downloads.length
      ? '<div class="card muted">No outputs yet — run a build step.</div>' : "");
}

/* ------------------------------------------------------------------ */
/* settings                                                            */
/* ------------------------------------------------------------------ */
function moduleOpts(selected) {
  return state.bootstrap.modules.map(m =>
    '<option value="' + m[0] + '"' + (m[0] === selected ? " selected" : "") + '>' + esc(m[1]) + '</option>').join("");
}

function renderSettings(c) {
  const p = state.detail.project, cfg = state.detail.config || {};
  const tk = cfg.tiktok || {}, sub = cfg.subtitles || {};
  const recap = isRecap();
  c.innerHTML =
    '<div class="grid cols2">' +
      '<div class="card">' +
        '<h3 style="margin-top:0">Project</h3>' +
        '<label>Module</label><select id="sModule">' + moduleOpts(p.module) + '</select>' +
        '<label>Topic / title</label><input id="sTopic" value="' + esc(p.topic || "") + '">' +
        (recap ? '<label>Style</label><select id="sStyle">' +
          ['retell', 'commentary', 'mixed'].map(s => '<option value="' + s + '"' + (p.style === s ? " selected" : "") + '>' + s + '</option>').join("") +
          '</select>' : "") +
        '<div class="form-row">' +
          '<div><label>Target length</label><input id="sTarget" value="' + esc(p.target_length || "") + '" placeholder="8:00"></div>' +
          '<div><label>Platform</label><select id="sPlatform">' +
            ['youtube', 'tiktok', 'both'].map(s => '<option value="' + s + '"' + (p.platform === s ? " selected" : "") + '>' + s + '</option>').join("") +
          '</select></div>' +
        '</div>' +
        '<label>Voice text style (tags)</label><select id="sTtsMode">' +
          ['plain', 'light', 'heavy'].map(s => '<option value="' + s + '"' + (p.tts_mode === s ? " selected" : "") + '>' + s + '</option>').join("") +
        '</select>' +
        '<label>Voice card</label><input id="sVoiceCard" value="' + esc(p.voice_card || "") + '">' +
        '<label class="check"><input type="checkbox" id="sMusic"' + (p.music ? " checked" : "") + '> background music bed</label>' +
        '<label class="check"><input type="checkbox" id="sCaptions"' + (p.captions ? " checked" : "") + '> captions</label>' +
        '<button class="btn primary" style="margin-top:14px" onclick="saveProjectSettings()">Save project</button>' +
      '</div>' +
      '<div class="card">' +
        '<h3 style="margin-top:0">Render config</h3>' +
        '<div class="form-row3">' +
          '<div><label>fps</label><input id="cFps" value="' + esc(cfg.fps != null ? cfg.fps : 24) + '"></div>' +
          '<div><label>width</label><input id="cWidth" value="' + esc(cfg.width != null ? cfg.width : 1920) + '"></div>' +
          '<div><label>height</label><input id="cHeight" value="' + esc(cfg.height != null ? cfg.height : 1080) + '"></div>' +
        '</div>' +
        '<div class="form-row">' +
          '<div><label>Fill (different aspect)</label><select id="cFill">' +
            ['pad', 'blur'].map(s => '<option value="' + s + '"' + (cfg.fill === s ? " selected" : "") + '>' + s + '</option>').join("") + '</select></div>' +
          '<div><label>Music volume</label><input id="cMusicVol" value="' + esc(cfg.music_volume != null ? cfg.music_volume : 0.12) + '"></div>' +
        '</div>' +
        '<label>TikTok (w × h × fps)</label>' +
        '<div class="form-row3">' +
          '<div><input id="cTkW" value="' + esc(tk.width != null ? tk.width : 1080) + '" placeholder="width"></div>' +
          '<div><input id="cTkH" value="' + esc(tk.height != null ? tk.height : 1920) + '" placeholder="height"></div>' +
          '<div><input id="cTkFps" value="' + esc(tk.fps != null ? tk.fps : 30) + '" placeholder="fps"></div>' +
        '</div>' +
        '<label>Subtitles (chars/line × lines)</label>' +
        '<div class="form-row">' +
          '<div><input id="cSubChars" value="' + esc(sub.max_chars_per_line != null ? sub.max_chars_per_line : 42) + '" placeholder="chars/line"></div>' +
          '<div><input id="cSubLines" value="' + esc(sub.max_lines != null ? sub.max_lines : 2) + '" placeholder="lines"></div>' +
        '</div>' +
        '<button class="btn primary" style="margin-top:14px" onclick="saveConfigSettings()">Save config</button>' +
      '</div>' +
    '</div>' +
    '<div class="section" style="margin-top:20px">' +
      '<h3>Maintenance</h3>' +
      '<div class="card">' +
        '<span class="badge ' + (state.detail.engine_current ? "good" : "amber") + '">engine ' + (state.detail.engine_current ? "up to date" : "outdated") + '</span>' +
        '<div style="margin-top:10px">' +
          '<button class="btn" onclick="syncEngine()">Update engine (recap.py)</button> ' +
          '<button class="btn ghost" onclick="apiPost(\'/api/projects/' + enc(state.current) + '/open\')">📂 Open folder</button>' +
        '</div>' +
        '<p class="muted" style="margin-top:8px">' + esc(state.detail.folder) + '</p>' +
      '</div>' +
    '</div>';
}

async function saveProjectSettings() {
  const recap = isRecap();
  const project = {
    module: document.getElementById("sModule").value,
    topic: document.getElementById("sTopic").value,
    target_length: document.getElementById("sTarget").value,
    platform: document.getElementById("sPlatform").value,
    tts_mode: document.getElementById("sTtsMode").value,
    voice_card: document.getElementById("sVoiceCard").value,
    music: document.getElementById("sMusic").checked,
    captions: document.getElementById("sCaptions").checked,
  };
  if (recap) project.style = document.getElementById("sStyle").value;
  const res = await apiPost("/api/projects/" + enc(state.current) + "/settings", { project });
  if (res.error) { toast(res.error); return; }
  toast("Project saved ✓");
  await refreshProjects();
  await loadDetail();
  renderHeader();
  renderTab();
}

async function saveConfigSettings() {
  const config = {
    fps: parseFloat(document.getElementById("cFps").value) || 24,
    width: parseInt(document.getElementById("cWidth").value) || 1920,
    height: parseInt(document.getElementById("cHeight").value) || 1080,
    fill: document.getElementById("cFill").value,
    music_volume: parseFloat(document.getElementById("cMusicVol").value) || 0.12,
    tiktok: {
      width: parseInt(document.getElementById("cTkW").value) || 1080,
      height: parseInt(document.getElementById("cTkH").value) || 1920,
      fps: parseInt(document.getElementById("cTkFps").value) || 30,
    },
    subtitles: {
      max_chars_per_line: parseInt(document.getElementById("cSubChars").value) || 42,
      max_lines: parseInt(document.getElementById("cSubLines").value) || 2,
    },
  };
  const res = await apiPost("/api/projects/" + enc(state.current) + "/config", { config });
  if (res.error) { toast(res.error); return; }
  toast("Config saved ✓");
  await loadDetail();
}

async function syncEngine() {
  const res = await apiPost("/api/projects/" + enc(state.current) + "/sync", {});
  if (res.error) { toast(res.error); return; }
  toast("Engine updated ✓");
  await loadDetail();
  renderHeader();
}

/* ------------------------------------------------------------------ */
/* new project modal                                                   */
/* ------------------------------------------------------------------ */
function newProjectModal() {
  openModal(
    '<h2>New project</h2>' +
    '<label>Project name</label><input id="npName" placeholder="e.g. Solo Leveling S01E05">' +
    '<div class="form-row">' +
      '<div><label>Module</label><select id="npModule">' + moduleOpts("movie_recap") + '</select></div>' +
      '<div><label>Target length</label><input id="npTarget" placeholder="8:00"></div>' +
    '</div>' +
    '<label>Topic / title</label><input id="npTopic" placeholder="e.g. Kobe 81-point game">' +
    '<div class="form-row">' +
      '<div><label>Platform</label><select id="npPlatform">' +
        ['youtube', 'tiktok', 'both'].map(s => '<option value="' + s + '">' + s + '</option>').join("") + '</select></div>' +
      '<div><label>Voice style</label><select id="npTtsMode">' +
        ['plain', 'light', 'heavy'].map(s => '<option value="' + s + '">' + s + '</option>').join("") + '</select></div>' +
    '</div>' +
    '<label class="check"><input type="checkbox" id="npMusic"> background music bed</label>' +
    '<div style="margin-top:16px;display:flex;gap:8px;justify-content:flex-end">' +
      '<button class="btn ghost" onclick="closeModal()">Cancel</button>' +
      '<button class="btn primary" onclick="submitNewProject()">Create project</button>' +
    '</div>');
  document.getElementById("npName").focus();
}

async function submitNewProject() {
  const name = document.getElementById("npName").value.trim();
  if (!name) { toast("Enter a project name."); return; }
  const project = {
    module: document.getElementById("npModule").value,
    topic: document.getElementById("npTopic").value,
    target_length: document.getElementById("npTarget").value,
    platform: document.getElementById("npPlatform").value,
    tts_mode: document.getElementById("npTtsMode").value,
    style: "retell",
    music: document.getElementById("npMusic").checked,
    captions: true,
  };
  const res = await apiPost("/api/projects", { name, project });
  if (res.error) { toast(res.error); return; }
  closeModal();
  await refreshProjects();
  await selectProject(res.name);
}

init();














/* ------------------------------------------------------------------ */
/* API keys                                                            */
/* ------------------------------------------------------------------ */
const KEY_DEFS = [
  ["ELEVENLABS_API_KEY", "ElevenLabs", "Best quality voices. Several keys allowed (comma-separated): the tool switches key when one runs out of credits."],
  ["MINIMAX_API_KEY", "MiniMax", "Alternative voice engine (speech-2.6-hd). Several keys allowed."],
];

function keyChips(list) {
  return list.length
    ? list.map((x) => '<span class="badge good">' + esc(x) + "</span>").join(" ")
    : '<span class="badge">not set</span>';
}

async function keysModal() {
  const data = await apiGet("/api/keys");
  const keys = data.keys || {};
  openModal(
    '<h2 style="margin-top:0">🔑 API keys</h2>' +
    '<p class="muted">Saved on this computer in <code>keys.env</code> and used by every project. ' +
    'Saved keys are never shown in full (only the last 4 characters). ' +
    '<b>Edge-TTS needs no key</b> - it is free.</p>' +
    KEY_DEFS.map(([name, label, help]) =>
      '<div class="card" style="margin-bottom:12px">' +
        '<div style="display:flex;justify-content:space-between;align-items:center"><b>' + label + '</b>' +
        '<span>' + keyChips(keys[name] || []) + '</span></div>' +
        '<div class="muted" style="margin:6px 0">' + help + '</div>' +
        '<label>' + ((keys[name] || []).length ? "Replace with (leave blank to keep what is saved)" : "Paste key(s)") + '</label>' +
        '<div style="display:flex;gap:8px">' +
          '<input type="password" autocomplete="off" spellcheck="false" data-key-input="' + name + '" placeholder="key1, key2, ..." style="flex:1">' +
          '<button class="btn small" type="button" onclick="toggleKeyVisible(\'' + name + '\')">Show</button>' +
          ((keys[name] || []).length
            ? '<button class="btn danger small" type="button" onclick="removeKey(\'' + name + '\')">Remove</button>' : "") +
        '</div>' +
      '</div>').join("") +
    '<div style="display:flex;gap:8px;justify-content:flex-end">' +
      '<button class="btn ghost" onclick="closeModal()">Close</button>' +
      '<button class="btn primary" onclick="saveKeysFromModal()">Save keys</button>' +
    '</div>');
}

function toggleKeyVisible(name) {
  const el = document.querySelector('[data-key-input="' + name + '"]');
  if (el) el.type = el.type === "password" ? "text" : "password";
}

async function postKeys(payload) {
  const r = await apiPost("/api/keys", payload);
  if (r.error) { toast(r.error); return false; }
  state.bootstrap.tools = r.tools;
  renderTools();
  if (state.detail && state.tab === "voice") renderTab();
  return true;
}

async function saveKeysFromModal() {
  const payload = {};
  document.querySelectorAll("[data-key-input]").forEach((el) => {
    if (el.value.trim()) payload[el.dataset.keyInput] = el.value.trim();
  });
  if (!Object.keys(payload).length) { toast("Nothing to save - paste a key first."); return; }
  if (await postKeys(payload)) { toast("Keys saved."); keysModal(); }
}

async function removeKey(name) {
  if (!confirm("Remove the saved " + name + " key(s) from keys.env?")) return;
  if (await postKeys({ [name]: "" })) { toast("Removed."); keysModal(); }
}
