"use strict";

const $ = (name) => document.getElementById(name);
const token = document.querySelector('meta[name="panel-token"]').content;
const allPages = [...document.querySelectorAll(".page")];
const names = new Intl.NumberFormat();
const labels = {youtube:"YouTube", reddit:"Reddit", instagram:"Instagram", tiktok:"TikTok",
  yes:"Yes", no:"No", own:"My channel", official:"Official", asked:"Asked", unknown:"Unknown"};
let active = "";
let clips = [], creatorRows = [], waiting = [];
let reviewPage = 0, waitingPage = 0;
let noticeTimer, selectedCreator, lastOverview;

function el(tag, text, className) {
  const item = document.createElement(tag);
  if (text != null) item.textContent = text;
  if (className) item.className = className;
  return item;
}
function button(text, click, className) {
  const b = el("button", text, className);
  b.type = "button";
  b.addEventListener("click", () => perform(click, b));
  return b;
}
function empty(text) { return el("p", text, "empty"); }
function notice(text) {
  clearTimeout(noticeTimer);
  $("notice").textContent = text;
  $("notice").hidden = false;
  noticeTimer = setTimeout(() => $("notice").hidden = true, 6000);
}
async function perform(fn, control) {
  if (control) control.disabled = true;
  try { await fn(); }
  catch (error) { notice(error.message || "That action failed."); }
  finally { if (control) control.disabled = false; }
}
async function api(path, data) {
  const headers = {"X-Panel-Token":token};
  const options = {headers};
  if (data != null) {
    headers["Content-Type"] = "application/json";
    Object.assign(options, {method:"POST", body:JSON.stringify(data)});
  }
  const response = await fetch("/api/" + path, options);
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "The panel could not complete that action.");
  return result;
}
function submit(form, fn) {
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    perform(() => fn(form, Object.fromEntries(new FormData(form))), e.submitter);
  });
}
function video(area, name, preload = "metadata") {
  const v = el("video");
  v.src = "/video?" + new URLSearchParams({area, name}) + "#t=0.1";
  v.preload = preload;
  v.controls = true;
  v.playsInline = true;
  v.setAttribute("aria-label", name);
  return v;
}
function release(v) {
  v.pause();
  v.removeAttribute("src");
  v.load();
}
function latest(data) {
  if (!["overview", "editing"].includes(active)) return;
  const target = $("latest-" + active);
  const key = data ? data.area + "/" + data.name : "-";
  if (target.dataset.key === key) return;
  target.dataset.key = key;
  for (const v of target.querySelectorAll("video")) release(v);
  target.replaceChildren(...(data ? [video(data.area, data.name), el("small", data.name)] : [empty("No clips have been rendered yet.")]));
}

const workerCards = {};
for (const [worker, label] of [["hunter","Hunter"], ["clip","Clip maker"]]) {
  const card = el("section", null, "worker");
  const head = el("div", null, "worker-head");
  const status = el("span", "Idle", "status");
  const log = el("pre", "No recent activity.");
  const toggle = button("", async () => {
    const enabled = toggle.getAttribute("aria-checked") !== "true";
    setWorker(worker, await api("worker", {worker, enabled}));
    await updateOverview();
  }, "switch");
  toggle.setAttribute("role", "switch");
  toggle.setAttribute("aria-label", label);
  toggle.setAttribute("aria-checked", "false");
  toggle.append(el("span", null, "switch-track"));
  head.append(el("h3", label), status, toggle);
  card.append(head, log);
  $("workers").append(card);
  workerCards[worker] = {status, log, toggle};
}
function setWorker(key, state) {
  const {status, log, toggle} = workerCards[key];
  const stopping = !state.enabled && state.status === "running";
  status.textContent = stopping ? "Finishing" : state.status[0].toUpperCase() + state.status.slice(1);
  status.className = "status " + state.status;
  toggle.setAttribute("aria-checked", state.enabled);
  const text = state.logs.slice(-20).join("\n") || "No recent activity.";
  if (log.textContent !== text) {
    const atBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 20;
    log.textContent = text;
    if (atBottom) log.scrollTop = log.scrollHeight;
  }
}
function explorer(name) { return api("open", {name}); }
for (const [name, text] of Object.entries({raw:"Raw videos", edits:"Edits", ready:"Ready", official:"Official media",
    finds:"Finds report", playbook:"Playbook", scoreboard:"Scoreboard"})) {
  $("quick-links").append(button(text + " ↗", () => explorer(name)));
}
for (const control of document.querySelectorAll("[data-open]")) {
  control.addEventListener("click", () => perform(() => explorer(control.dataset.open), control));
}
async function updateOverview() {
  try {
    const data = await api("overview");
    $("connection").textContent = "Local connection";
    $("connection-dot").classList.add("connected");
    $("date").textContent = data.date + (data.zone ? " · " + data.zone : "");
    for (const name of ["found","downloaded","videos_clipped","ready"]) $(name).textContent = names.format(data[name]);
    $("clips_created").textContent = names.format(data.clips_created) + " clips rendered";
    $("queued").textContent = names.format(data.queued) + " in local queue";
    $("review-count").textContent = names.format(data.edits);
    for (const [worker, state] of Object.entries(data.workers)) setWorker(worker, state);
    latest(data.latest);
    renderAI(data.ai);
    const previous = lastOverview;
    lastOverview = data;
    const changed = previous && (previous.edits !== data.edits || previous.reclipping !== data.reclipping
      || (previous.latest || {}).name !== (data.latest || {}).name);
    if (changed && active === "review" && !dirtyReviews.size) await loadClips();
  } catch (error) {
    $("connection").textContent = "Connection interrupted";
    $("connection-dot").classList.remove("connected");
    throw error;
  }
}

function fill(form, values) {
  for (const [key, value] of Object.entries(values)) {
    const field = form.elements.namedItem(key);
    if (!field) continue;
    if (field.type === "checkbox") field.checked = Boolean(value);
    else field.value = value ?? "";
  }
}
function fillSettings(form, data) {
  fill(form, data);
  if (form.dataset.settings === "hunter") {
    fill(form, data.sources);
    $("youtube-key-status").textContent = data.youtube_key_saved ? "Key saved. Leave blank to keep it." : "Add a key to enable keyword search.";
    $("reddit-key-status").textContent = data.reddit_secret_saved ? "Secret saved. Leave blank to keep it." : "Reddit is skipped until an app ID and secret are saved.";
    $("instagram-key-status").textContent = data.instagram_key_saved ? "Token saved. Leave blank to keep it." : "Hashtag search needs an account ID and token.";
  }
}
for (const form of document.querySelectorAll("[data-settings]")) {
  submit(form, async (_, data) => {
    const action = form.dataset.settings;
    if (action === "hunter") {
      data.sources = Object.fromEntries(["youtube","reddit","instagram"].map(k => [k, form.elements[k].checked]));
      data.every_minutes = Number(data.every_minutes);
      data.min_score = Number(data.min_score);
      for (const key of ["clear_access_token","clear_youtube_api_key","clear_reddit_client_secret"]) data[key] = form.elements[key].checked;
    } else {
      for (const key of ["clip_seconds","clips_per_video"]) data[key] = Number(data[key]);
      data.caption_size = data.caption_size ? Number(data.caption_size) : null;
      data.captions = form.elements.captions.checked;
    }
    const result = await api("settings", {...data, action});
    if (action === "hunter") {
      fill(form, {youtube_api_key:"", access_token:"", reddit_client_secret:"", clear_access_token:false, clear_youtube_api_key:false, clear_reddit_client_secret:false});
    }
    fillSettings(form, result);
    notice("Settings saved.");
  });
}

function table(headings, rows, message) {
  if (!rows.length) return empty(message);
  const t = el("table");
  const head = el("thead");
  const labels = el("tr");
  for (const label of headings) {
    const th = el("th", label);
    th.scope = "col";
    labels.append(th);
  }
  head.append(labels);
  const body = el("tbody");
  for (const row of rows) {
    const tr = el("tr");
    for (const value of row) {
      const cell = el("td");
      if (value instanceof Node) cell.append(value);
      else cell.textContent = value || "—";
      tr.append(cell);
    }
    body.append(tr);
  }
  t.append(head, body);
  return t;
}
function editCreator(row) {
  selectedCreator = row;
  const form = $("creator-form");
  form.reset();
  if (row) fill(form, row);
  $("creator-heading").textContent = row ? "Edit creator" : "Add creator";
  $("creator-error").textContent = "";
  $("creator-dialog").showModal();
}
$("add-creator").addEventListener("click", () => editCreator(null));
$("cancel-creator").addEventListener("click", () => $("creator-dialog").close());
submit($("creator-form"), async (_, data) => {
  try { await api("creators", {...data, action:"save", old:selectedCreator}); }
  catch (error) { $("creator-error").textContent = error.message; return; }
  $("creator-dialog").close();
  await loadCreators();
  notice("Creator saved.");
});
function showCreators() {
  const query = $("creator-search").value.trim().toLowerCase();
  const rows = creatorRows.filter(r => Object.values(r).join(" ").toLowerCase().includes(query)).map(row => {
    const actions = el("div", null, "actions");
    actions.append(button("Edit", () => editCreator(row)), button("Remove", async () => {
      if (!confirm("Remove " + row.handle + " from the creator list?")) return;
      await api("creators", {action:"remove", old:row});
      await loadCreators();
      notice("Creator removed.");
    }, "danger"));
    return [labels[row.platform] || row.platform, row.handle, row.channel_id, labels[row.permission] || row.permission,
      row.contact, row.notes, actions];
  });
  $("creator-table").replaceChildren(table(["Platform","Creator","Channel ID","Permission","Contact","Notes","Actions"], rows, "No matching creators."));
}
async function copy(text, message) {
  await navigator.clipboard.writeText(text);
  notice(message);
}
function safeLink(url) {
  try {
    const link = new URL(url);
    if (["http:", "https:"].includes(link.protocol)) return link.href;
  } catch (_) {}
  return null;
}
function pager(target, page, size, length, change) {
  const pages = Math.max(1, Math.ceil(length / size));
  target.replaceChildren();
  if (pages < 2) return;
  const prev = button("Previous", () => change(page - 1));
  const next = button("Next", () => change(page + 1));
  prev.disabled = page <= 0;
  next.disabled = page >= pages - 1;
  target.append(prev, el("span", "Page " + (page + 1) + " of " + pages, "hint"), next);
}
function showWaiting() {
  const query = $("waiting-search").value.trim().toLowerCase();
  const rows = waiting.filter(r => [r.title, r.creator, r.platform].join(" ").toLowerCase().includes(query));
  $("waiting-count").textContent = "(" + names.format(waiting.length) + ")";
  waitingPage = Math.min(waitingPage, Math.max(0, Math.ceil(rows.length / 15) - 1));
  $("waiting-list").replaceChildren(...rows.slice(waitingPage * 15, (waitingPage + 1) * 15).map(row => {
    const item = el("article", null, "permission-item");
    const label = el("div");
    const title = el("h3");
    const url = safeLink(row.url);
    if (url) {
      const link = el("a", row.title);
      Object.assign(link, {href:url, target:"_blank", rel:"noopener"});
      title.append(link);
    } else title.textContent = row.title;
    label.append(title, el("small", [labels[row.platform] || row.platform, row.creator, "Score " + row.score].join(" · ")));
    const actions = el("div", null, "actions");
    const yes = button("Yes", async () => {
      if (!confirm("Confirm that " + row.creator + " gave permission to use their clips?")) return;
      const result = await api("approve", {id:row.id});
      await loadCreators();
      notice(result.message);
    }, "primary");
    yes.disabled = !row.can_approve;
    if (!row.can_approve) yes.title = "Creator identity is missing.";
    actions.append(button("Copy message", () => copy(row.message, "Permission message copied.")), yes);
    item.append(label, actions);
    return item;
  }));
  if (!rows.length) $("waiting-list").append(empty("No matching finds waiting for permission."));
  pager($("waiting-pager"), waitingPage, 15, rows.length, p => { waitingPage = p; showWaiting(); });
}
$("creator-search").addEventListener("input", showCreators);
$("waiting-search").addEventListener("input", () => { waitingPage = 0; showWaiting(); });
async function loadCreators() {
  const data = await api("creators");
  creatorRows = data.rows;
  waiting = data.waiting;
  showCreators();
  showWaiting();
}

const dirtyReviews = new Map();
const filterIds = ["f-creator","f-category","f-verdict","f-score","f-length","f-preset","f-age","f-sort","f-issues"];
function fillOptions(id, values, allLabel) {
  const select = $(id), current = select.value;
  const opts = [new Option(allLabel, "")];
  for (const [value, count] of values) opts.push(new Option(value + " (" + count + ")", value));
  select.replaceChildren(...opts);
  select.value = values.some(([v]) => v === current) ? current : "";
}
function countBy(list) {
  const m = new Map();
  for (const v of list) if (v) m.set(v, (m.get(v) || 0) + 1);
  return [...m].sort((a, b) => a[0].localeCompare(b[0]));
}
function refreshFilterOptions() {
  fillOptions("f-creator", countBy(clips.map(r => r.credit)), "All creators");
  fillOptions("f-category", countBy(clips.map(r => r.ai && r.ai.category)), "All types");
}
function clipMatches(row) {
  const words = $("clip-search").value.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const hay = [row.name, row.caption, row.credit, row.ai && row.ai.what_happens, row.ai && row.ai.category].join(" ").toLowerCase();
  if (!words.every(w => hay.includes(w))) return false;
  const a = row.ai;
  if ($("ai-only").checked && !(a && a.verdict !== "skip" && !a.duplicate_of)) return false;
  if ($("f-creator").value && row.credit !== $("f-creator").value) return false;
  if ($("f-category").value && !(a && a.category === $("f-category").value)) return false;
  const verdict = $("f-verdict").value;
  if (verdict === "none" ? a : verdict && !(a && a.verdict === verdict)) return false;
  const min = Number($("f-score").value || 0);
  if (min && !(a && Number(a.score) >= min)) return false;
  if ($("f-length").value) {
    const [lo, hi] = $("f-length").value.split("-").map(Number);
    if (row.seconds == null || row.seconds < lo || row.seconds >= hi) return false;
  }
  if ($("f-preset").value && row.preset !== $("f-preset").value) return false;
  const days = Number($("f-age").value || 0);
  if (days && Date.now() / 1000 - row.modified > days * 86400) return false;
  if ($("f-issues").checked && a && (a.problems || a.flags || a.duplicate_of)) return false;
  return true;
}
const clipSorts = {
  rank: row => row.ai ? Number(row.ai.rank) : Infinity,
  score: row => row.ai ? -Number(row.ai.score) : Infinity,
  new: row => -row.modified, old: row => row.modified,
  short: row => row.seconds ?? Infinity,
};
function showClips() {
  const sort = $("f-sort").value;
  const rows = clips.filter(clipMatches).sort(sort === "creator"
    ? (a, b) => (a.credit || "~").localeCompare(b.credit || "~")
    : (a, b) => clipSorts[sort](a) - clipSorts[sort](b));
  reviewPage = Math.min(reviewPage, Math.max(0, Math.ceil(rows.length / 12) - 1));
  $("clip-count").textContent = names.format(rows.length) + " clips";
  for (const v of $("clip-grid").querySelectorAll("video")) release(v);
  $("clip-grid").replaceChildren(...rows.slice(reviewPage * 12, (reviewPage + 1) * 12).map(row => {
    const card = el("article", null, "clip surface");
    const media = el("div", null, "clip-video");
    let player = video("edits", row.name, "none");
    media.append(player);
    const details = el("div", null, "clip-body");
    const label = el("label", "Post caption");
    const caption = el("textarea");
    caption.rows = 4;
    caption.value = dirtyReviews.get(row.name) ?? row.caption;
    caption.addEventListener("input", () => dirtyReviews.set(row.name, caption.value));
    label.append(caption);
    const actions = el("div", null, "actions");
    async function review(action) {
      if (action === "delete" && !confirm("Delete this clip from review? It will be moved to the panel’s deleted folder.")) return;
      if (action !== "caption") release(player);
      try { await api("review", {action, name:row.name, caption:caption.value}); }
      catch (error) {
        if (action !== "caption") {
          player = video("edits", row.name, "none");
          media.replaceChildren(player);
        }
        throw error;
      }
      dirtyReviews.delete(row.name);
      if (action === "caption") row.caption = caption.value;
      else await loadClips();
      await updateOverview();
      notice({keep:"Clip moved to Ready.", delete:"Clip removed from review.", caption:"Caption saved."}[action]);
    }
    actions.append(button("Keep", () => review("keep"), "primary"), button("Save caption", () => review("caption")), button("Delete", () => review("delete"), "danger"));
    details.append(el("h3", row.name));
    details.append(el("small", [row.credit ? "@" + row.credit : "no credit", row.seconds != null ? row.seconds + " s" : "",
      row.preset, new Date(row.modified * 1000).toLocaleString([], {month:"short", day:"numeric", hour:"numeric", minute:"2-digit"})]
      .filter(Boolean).join(" · "), "clip-meta"));
    if (row.redo_from) details.append(el("small", "Re-cut: " + row.redo_from + ". The old version is in media\\edits\\_old-reclip.", "redo-note"));
    details.append(row.ai ? aiBox(row.ai) : el("small", "Not scored by the AI reviewer yet."));
    details.append(label, actions, redoControls(row));
    card.append(media, details);
    return card;
  }));
  if (!rows.length) $("clip-grid").append(empty("No matching clips in the edits folder."));
  pager($("clip-pager"), reviewPage, 12, rows.length, p => { reviewPage = p; showClips(); });
}
function redoControls(row) {
  const box = el("div", null, "redo");
  if (row.redo === "working") {
    box.append(el("small", "Re-cutting so it " + row.redo_text + ". The new version replaces this card in 1-3 minutes.", "redo-busy"));
    return box;
  }
  box.append(el("small", "Cut off or starts too late? Re-cut it from the original video. The AI redoes the captions and hook."));
  if (row.redo === "failed") box.append(el("small", "Last re-cut failed: " + row.redo_text, "redo-failed"));
  const amount = el("select");
  amount.setAttribute("aria-label", "Seconds");
  for (const s of [3, 5, 10, 15]) { const o = el("option", s + " s"); o.value = s; if (s === 5) o.selected = true; amount.append(o); }
  async function go(which) {
    const result = await api("review", {action:"reclip", name:row.name, [which]:Number(amount.value)});
    notice(result.message);
    await loadClips();
  }
  const line = el("div", null, "actions");
  line.append(button("⏪ Start earlier", () => go("earlier")), amount, button("Extend end ⏩", () => go("later")));
  box.append(line);
  return box;
}
function aiIssues(a) {
  return [a.duplicate_of && "duplicate of " + a.duplicate_of, a.flags, a.problems].filter(Boolean).join("; ");
}
function aiBadge(a) {
  const badge = el("span", null, "ai-badge");
  badge.append(el("span", "#" + a.rank, "hint"), el("span", a.score, "ai-score"), el("span", a.verdict, "ai-verdict " + a.verdict));
  if (a.category) badge.append(el("span", a.category, "hint"));
  return badge;
}
function aiBox(a) {
  const box = el("div", null, "ai-box");
  box.append(aiBadge(a), el("span", a.what_happens));
  box.append(el("small", "hook " + a.hook + " · payoff " + a.payoff + " · standalone " + a.standalone + " · phone " + a.phone));
  const issues = aiIssues(a);
  if (issues) box.append(el("span", issues, "ai-issues"));
  return box;
}
let lastAIStatus = "";
function renderAI(ai) {
  if (!ai) return;
  const running = ai.status === "running";
  let text = ai.scored + " clips scored" + (ai.unscored ? ", " + ai.unscored + " new to score" : "");
  if (running) text = "Reviewing " + (ai.total ? ai.done + " of " + ai.total : "…");
  else if (ai.status === "error") text = (ai.logs.slice(-1)[0] || "The AI review failed.") + " · " + text;
  else if (ai.updated) text += " · updated " + new Date(ai.updated).toLocaleTimeString([], {hour:"numeric", minute:"2-digit"});
  for (const s of document.querySelectorAll("[data-ai-status]")) s.textContent = text;
  for (const b of document.querySelectorAll("[data-ai-run]")) { b.disabled = running; b.textContent = running ? "Reviewing…" : "Run AI review"; }
  const key = JSON.stringify(ai.top.map(r => r.name + r.score));
  if ($("ai-top").dataset.key !== key) {
    $("ai-top").dataset.key = key;
    $("ai-top").replaceChildren(...(ai.top.length ? ai.top.map(r => {
      const card = el("article", null, "ai-card");
      card.append(aiBadge(r), el("b", r.title || r.name), el("span", r.what_happens, "hint"));
      const issues = aiIssues(r);
      if (issues) card.append(el("span", issues, "ai-issues"));
      card.title = r.name;
      card.addEventListener("click", () => { $("clip-search").value = r.name; location.hash = "#review"; });
      return card;
    }) : [empty("No AI scores yet. Press Run AI review.")]));
  }
  if (lastAIStatus === "running" && !running) {
    notice(ai.status === "error" ? "The AI review stopped. Check that Ollama is running." : "AI review finished.");
    if (active === "review" && !dirtyReviews.size) loadClips();
  }
  lastAIStatus = ai.status;
}
for (const b of document.querySelectorAll("[data-ai-run]")) {
  b.addEventListener("click", () => perform(async () => { renderAI(await api("ai", {action:"run"})); notice("AI review started."); }, b));
}
$("ai-only").addEventListener("change", () => { reviewPage = 0; showClips(); });
async function loadClips() {
  clips = await api("clips?area=edits");
  refreshFilterOptions();
  showClips();
}
for (const id of filterIds) $(id).addEventListener(id === "f-score" ? "input" : "change", () => { reviewPage = 0; showClips(); });
$("f-clear").addEventListener("click", () => {
  for (const id of filterIds) { const f = $(id); if (f.type === "checkbox") f.checked = false; else f.value = id === "f-sort" ? "rank" : ""; }
  $("clip-search").value = ""; $("ai-only").checked = false;
  reviewPage = 0; showClips();
});
$("clip-search").addEventListener("input", () => { reviewPage = 0; showClips(); });

async function loadQueue(fillForm = false) {
  const [queue, ready] = await Promise.all([api("queue"), api("clips?area=ready")]);
  renderDestinations(queue.destinations);
  if (fillForm) fill($("schedule-form"), {...queue, times:queue.times.join("\n")});
  const pending = ready.filter(r => !queue.items.some(x => x.name === r.name));
  const select = $("ready-select");
  const options = [el("option", pending.length ? "Choose a clip" : "No unscheduled ready clips")];
  options[0].value = "";
  for (const row of pending) {
    const option = el("option", row.name);
    option.value = row.name;
    options.push(option);
  }
  select.replaceChildren(...options);
  $("queue-list").replaceChildren(table([(queue.zone || "Local") + " time","Clip","Destinations","Status","Actions"], queue.items.map(row => {
    const actions = el("div", null, "actions");
    actions.append(button("Copy caption", () => copy(row.caption, "Caption copied.")), button("Remove", async () => {
      await api("schedule", {action:"remove", name:row.name});
      await loadQueue();
      notice("Clip removed from the queue.");
    }));
    return [row.local, row.name, row.channels.join(", "), !row.available ? "File missing" : row.past ? "Time passed" : "Queued locally", actions];
  }), "No Reels in the local queue yet."));
}
function renderDestinations(list) {
  const box = $("dest-channels");
  if (!box || box.querySelector("input") || !Array.isArray(list)) return;
  for (const name of list) {
    const input = el("input");
    Object.assign(input, {type: "checkbox", value: name, checked: true,
                          name: "dest-" + String(name).toLowerCase().replace(/[^a-z0-9]+/g, "-")});
    const label = el("label", null, "check");
    label.append(input, document.createTextNode(" " + name));
    box.append(label);
  }
}
submit($("schedule-form"), async (_, data) => {
  await api("schedule", {...data, action:"settings", posts_per_day:Number(data.posts_per_day)});
  await loadQueue(true);
  notice("Posting times saved.");
});
submit($("queue-form"), async (form, data) => {
  const channels = [...document.querySelectorAll("#dest-channels input[type=checkbox]")]
    .filter(input => input.checked).map(input => input.value);
  if (!channels.length) { notice("Pick at least one destination."); return; }
  if (!data.name) { notice("Pick a ready clip first."); return; }
  await api("schedule", {action:"add", name:data.name, channels});
  await loadQueue();
  notice("Clip added to the local queue.");
});
$("export").addEventListener("click", () => perform(async () => {
  const data = await api("export");
  const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], {type:"application/json"}));
  const link = el("a");
  Object.assign(link, {href:url, download:"reels-queue.json"});
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}, $("export")));

async function loadScoreboard() {
  const score = await api("scoreboard");
  $("score-metrics").replaceChildren(...[
    ["Posts logged", names.format(score.rows.length)], ["24-hour views", names.format(score.views)],
    ["Top post by 24-hour views", score.best?.hook || "—"]
  ].map(([label, value]) => {
    const card = el("article");
    card.append(el("span", label), el("strong", value));
    return card;
  }));
  $("scores").replaceChildren(table(score.fields.map(k => k.replaceAll("_", " ")),
    score.rows.map(row => score.fields.map(k => row[k])), "No results have been entered in scoreboard.csv."));
}
async function navigate() {
  const name = location.hash.slice(1);
  if (name === "main") return;
  const page = allPages.find(page => page.id === name) || $("overview");
  if (active === page.id) return;
  for (const old of allPages) {
    old.hidden = old !== page;
    if (old !== page) for (const v of old.querySelectorAll("video")) release(v);
  }
  for (const id of ["latest-overview","latest-editing"]) delete $(id).dataset.key;
  active = page.id;
  for (const item of document.querySelectorAll("nav a")) {
    if (item.hash === "#" + active) item.setAttribute("aria-current", "page");
    else item.removeAttribute("aria-current");
  }
  window.scrollTo(0, 0);
  if (active === "hunter" || active === "editing") {
    const form = active === "hunter" ? $("hunter-form") : $("clip-form");
    const data = await api("settings");
    if (active === page.id) fillSettings(form, data);
  }
  if (active === "editing") await loadWhole();
  if (active === "overview") loadWholeLinks().catch(error => $("whole-links-mini").replaceChildren(el("p", error.message, "error-text")));
  if (active === "creators") await loadCreators();
  if (active === "review") await loadClips();
  if (active === "schedule") await loadQueue(true);
  if (active === "scoreboard") await loadScoreboard();
  if (lastOverview) latest(lastOverview.latest);
}
// ---------- Repost a whole video ----------
let wholeRows = [], wholePage = 0, wholeTimer;
function length(sec) {
  sec = Math.round(sec || 0);
  if (!sec) return "length unknown";
  const h = Math.floor(sec / 3600), m = Math.floor(sec % 3600 / 60), s = String(sec % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${s}` : m ? `${m}:${s}` : `${sec} s`;
}
function wholeRow(row) {
  const card = el("article", null, "whole-row" + (row.allowed ? "" : " blocked"));
  const info = el("div", null, "whole-info");
  info.append(el("strong", row.title));
  info.append(el("small", [row.creator || "no credit (your video)", length(row.seconds), row.plan].join(" · ")));
  const badge = el("span", row.permission, "status " + (row.allowed ? (row.confirm ? "warn" : "running") : "error"));
  info.append(badge);
  if (row.warning) info.append(el("small", row.warning, row.allowed ? "warn-text" : "error-text"));
  card.append(info);
  const controls = el("div", null, "whole-controls");
  const working = row.job === "queued" || row.job === "working";
  if (working) {
    controls.append(el("span", row.job === "queued" ? "Waiting to render…" : "Rendering…", "status running"));
  } else if (row.allowed) {
    let mode = "auto";
    if (row.seconds > 90) {
      const select = el("select");
      select.setAttribute("aria-label", "How to handle a video over 90 s");
      if (row.parts <= 8) select.append(new Option(`Split into ~1 min parts (about ${row.parts})`, "parts"));
      select.append(new Option("First 90 s only", "cap"));
      controls.append(select);
      mode = null;
      card.select = select;
    }
    let confirm;
    if (row.confirm) {
      const label = el("label", null, "check");
      confirm = el("input");
      confirm.type = "checkbox";
      label.append(confirm, " They really said yes");
      controls.append(label);
    }
    controls.append(button("Clip whole video", async () => {
      if (confirm && !confirm.checked) throw new Error("Tick 'They really said yes' first. This creator was bulk-marked yes on 11/20 with no reply on file.");
      const result = await api("whole", {action:"start", name:row.name, mode: mode || card.select.value, confirmed: Boolean(confirm && confirm.checked)});
      notice(result.message);
      await loadWhole();
    }, "primary"));
  }
  if (!working && row.job === "done") controls.append(el("small", "Done: " + row.job_note + ". See Clip review."));
  if (!working && row.job === "failed") controls.append(el("small", "Last try failed: " + (row.job_note || "see clipmaker\wholejob.log"), "error-text"));
  card.append(controls);
  return card;
}
function showWhole() {
  const q = $("whole-search").value.trim().toLowerCase();
  const rows = wholeRows.filter(r => !q || (r.title + " " + r.creator + " " + r.name).toLowerCase().includes(q));
  const size = 8, pages = Math.max(1, Math.ceil(rows.length / size));
  wholePage = Math.min(wholePage, pages - 1);
  $("whole-count").textContent = names.format(rows.length);
  const shown = rows.slice(wholePage * size, wholePage * size + size);
  $("whole-list").replaceChildren(...(shown.length ? shown.map(wholeRow) : [empty("No downloaded source videos yet. They come from the hunter or the phone inbox.")]));
  const pager = [];
  if (pages > 1) {
    pager.push(button("‹ Newer", () => { wholePage = Math.max(0, wholePage - 1); showWhole(); }));
    pager.push(el("span", `Page ${wholePage + 1} of ${pages}`, "hint"));
    pager.push(button("Older ›", () => { wholePage = Math.min(pages - 1, wholePage + 1); showWhole(); }));
  }
  $("whole-pager").replaceChildren(...pager);
}
function linkRow(row) {
  const card = el("article", null, "whole-row");
  const info = el("div", null, "whole-info");
  info.append(el("strong", row.title || row.url));
  const site = labels[row.platform] || row.platform || "";
  info.append(el("small", [row.creator ? `${site} @${row.creator}` : site, row.title ? row.url : ""].filter(Boolean).join(" · ")));
  const st = row.status || "";
  const bad = st.startsWith("failed") || st.startsWith("skipped");
  const busy = ["queued", "downloading", "clipping"].includes(st);
  const nice = {queued:"Waiting to download", downloading:"Downloading…", clipping:"Making the Reel…",
    "waiting permission":"Waiting on permission", "needs choice":"Too long for one Reel: pick below"}[st] || st;
  info.append(el("span", nice, "status " + (bad ? "error" : (st.startsWith("done") || busy) ? "running" : "warn")));
  if (row.note) info.append(el("small", row.note, "hint"));
  card.append(info);
  const controls = el("div", null, "whole-controls");
  const act = (what) => async () => { await api("whole", {action:"link-item", id:row.id, do:what}); await loadWholeLinks(); };
  if (st === "needs choice") {
    if (row.message) info.append(el("small", row.message));
    if (Number(row.parts) <= 8) controls.append(button(`Split into ${row.parts} parts (~${row.part_len})`, act("parts"), "primary"));
    controls.append(button("First 90 s only", act("cap")));
  }
  if (st === "waiting permission" && row.message) {
    info.append(el("small", "Draft message, not sent. Send it yourself if you want to ask. When they say yes, mark them Yes on the Creators page and it clips automatically.", "warn-text"));
    const draft = el("textarea", null, "whole-draft");
    draft.readOnly = true;
    draft.value = row.message;
    info.append(draft);
    controls.append(button("Copy message", async () => { await navigator.clipboard.writeText(row.message); notice("Copied. Nothing was sent."); }));
  }
  if (st.startsWith("done") && row.reels.length) info.append(el("small", "In Clip review: " + row.reels.join(", ")));
  if (st.startsWith("failed")) controls.append(button("Retry", act("retry")));
  if (!busy) controls.append(button("Remove", act("remove")));
  card.append(controls);
  return card;
}
let linkTimer;
async function loadWholeLinks() {
  clearTimeout(linkTimer);
  if (!["editing", "overview"].includes(active)) return;
  const data = await api("whole-links");
  const mini = active === "overview";
  const box = $(mini ? "whole-links-mini" : "whole-links");
  if (!["editing", "overview"].includes(active)) return;
  if (!data.running) { box.replaceChildren(el("p", data.error, "error-text")); return; }
  const rows = mini ? data.rows.slice(0, 3) : data.rows;
  box.replaceChildren(...rows.map(linkRow));
  if (mini && data.rows.length > 3) box.append(el("small", (data.rows.length - 3) + " more on the Editing page.", "hint"));
  if (data.rows.some(r => ["queued", "downloading", "clipping"].includes(r.status))) {
    linkTimer = setTimeout(() => loadWholeLinks().catch(() => {}), 5000);
  }
}
for (const id of ["whole-link-form", "whole-link-mini"]) {
  submit($(id), async (form, data) => {
    const result = await api("whole", {action:"link", url:data.url, whose:data.whose});
    form.reset();
    notice(result.message);
    await loadWholeLinks();
  });
}
async function loadWhole() {
  clearTimeout(wholeTimer);
  loadWholeLinks().catch(error => $("whole-links").replaceChildren(el("p", error.message, "error-text")));
  const data = await api("whole");
  if (active !== "editing") return;
  wholeRows = data.rows;
  showWhole();
  if (wholeRows.some(r => r.job === "queued" || r.job === "working")) {
    wholeTimer = setTimeout(() => loadWhole().catch(() => {}), 8000);
  }
}
$("whole-search").addEventListener("input", () => { wholePage = 0; showWhole(); });

window.addEventListener("hashchange", () => perform(navigate));
window.addEventListener("beforeunload", event => {
  if (dirtyReviews.size) event.preventDefault();
});
perform(navigate);
perform(updateOverview);
setInterval(() => updateOverview().catch(() => {}), 3500);
