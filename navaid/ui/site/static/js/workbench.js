import { renderMarkdown } from "./markdown.js";

const FEATURE_LABELS = {
  demand_pressure: "Demand pressure",
  congestion: "Congestion",
  landside_saturation: "Landside saturation",
  unmet_demand: "Unmet demand",
  yield_mix: "Yield mix",
  growth_outlook: "Growth outlook",
  capital_feasibility: "Capital feasibility",
};

const CONSTRAINT_MULT = {
  landside: "1.00",
  mixed: "0.75",
  airside: "0.40",
  "demand-bound": "0.30",
};

const els = {
  form: document.getElementById("ask-form"),
  question: document.getElementById("question"),
  submit: document.getElementById("ask-submit"),
  error: document.getElementById("form-error"),
  transcript: document.getElementById("transcript"),
  empty: document.getElementById("transcript-empty"),
  gemini: document.getElementById("gemini-switch"),
  geminiState: document.getElementById("gemini-switch-state"),
  newSession: document.getElementById("new-session"),
  sessionId: document.getElementById("session-id"),
  warehouse: document.getElementById("status-warehouse"),
  geminiStatus: document.getElementById("status-gemini"),
  speak: document.getElementById("speak-switch"),
  speakState: document.getElementById("speak-switch-state"),
  voiceStatus: document.getElementById("status-voice"),
  player: document.getElementById("narration-player"),
  hint: document.getElementById("composer-hint"),
  envelope: document.getElementById("envelope"),
  asOf: document.getElementById("env-as-of"),
  confidence: document.getElementById("env-confidence"),
  assumptions: document.getElementById("env-assumptions"),
  uncertainties: document.getElementById("env-uncertainties"),
  oos: document.getElementById("env-oos"),
  sources: document.getElementById("env-sources"),
  live: document.getElementById("ask-live"),
};

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value == null || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "dataset") Object.assign(node.dataset, value);
    else if (key.startsWith("on") && typeof value === "function") {
      node.addEventListener(key.slice(2).toLowerCase(), value);
    } else if (key === "text") node.textContent = value;
    else if (key === "html") node.innerHTML = value;
    else if (key === "style" && typeof value === "object") Object.assign(node.style, value);
    else node.setAttribute(key, value === true ? "" : String(value));
  }
  for (const child of children) {
    if (child == null || child === false) continue;
    node.append(child.nodeType ? child : document.createTextNode(String(child)));
  }
  return node;
}

function fmt(value, digits = 1) {
  if (value == null || value === "") return "—";
  const n = Number(value);
  if (Number.isNaN(n)) return String(value);
  return n.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: 0 });
}

function sessionKey() {
  return "navaid.session_id";
}

function getSessionId() {
  let id = sessionStorage.getItem(sessionKey());
  if (!id) {
    id = crypto.randomUUID();
    sessionStorage.setItem(sessionKey(), id);
  }
  return id;
}

function setSessionId(id) {
  sessionStorage.setItem(sessionKey(), id);
  els.sessionId.textContent = id.slice(0, 8);
  els.sessionId.title = id;
}

function parseUseGeminiParam() {
  const params = new URLSearchParams(location.search);
  if (!params.has("use_gemini")) return null;
  const raw = params.get("use_gemini").trim().toLowerCase();
  return !["0", "false", "no", "off"].includes(raw);
}

async function fetchHealth() {
  try {
    const res = await fetch(window.navaidApi("/health"));
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

function geminiPrefKey() {
  return "navaid.use_gemini";
}

function parseStoredGemini() {
  try {
    const raw = sessionStorage.getItem(geminiPrefKey());
    if (raw == null) return null;
    return raw === "true";
  } catch {
    return null;
  }
}

function setSwitch(on) {
  const enabled = Boolean(on);
  els.gemini.setAttribute("aria-checked", enabled ? "true" : "false");
  els.gemini.classList.toggle("switch--on", enabled);
  if (els.geminiState) els.geminiState.textContent = enabled ? "On" : "Off";
  try {
    sessionStorage.setItem(geminiPrefKey(), enabled ? "true" : "false");
  } catch {
    /* ignore quota / private mode */
  }
  refreshGeminiChrome();
}

function useGemini() {
  return els.gemini.getAttribute("aria-checked") === "true";
}

let geminiAuthLabel = "none";
let geminiConfigured = false;

function defaultHint() {
  if (useGemini()) {
    return geminiConfigured
      ? `Gemini narration on (${geminiAuthLabel}). Shift+Enter sends.`
      : "Gemini narration on, but no API key or ADC — engines will still answer. Shift+Enter sends.";
  }
  return "Gemini narration off. Answers use the engine template only. Shift+Enter sends.";
}

function refreshGeminiChrome() {
  const on = useGemini();
  if (els.geminiStatus) {
    els.geminiStatus.textContent = on
      ? geminiConfigured
        ? `on · ${geminiAuthLabel}`
        : "on · unavailable"
      : "off";
  }
  if (!asking && els.hint) els.hint.textContent = defaultHint();
}

function speakPrefKey() {
  return "navaid.speak";
}

function parseStoredSpeak() {
  try {
    const raw = sessionStorage.getItem(speakPrefKey());
    if (raw == null) return null;
    return raw === "true";
  } catch {
    return null;
  }
}

function setSpeak(on) {
  const enabled = Boolean(on);
  if (!els.speak) return;
  els.speak.setAttribute("aria-checked", enabled ? "true" : "false");
  els.speak.classList.toggle("switch--on", enabled);
  if (els.speakState) els.speakState.textContent = enabled ? "On" : "Off";
  try {
    sessionStorage.setItem(speakPrefKey(), enabled ? "true" : "false");
  } catch {
    /* ignore */
  }
  if (els.voiceStatus) {
    els.voiceStatus.textContent = enabled ? (geminiConfigured ? "on · gemini" : "on · browser") : "off";
  }
  if (!enabled) stopNarration();
}

function speakEnabled() {
  return els.speak?.getAttribute("aria-checked") === "true";
}

let narrationToken = 0;
let activeListenBtn = null;

function stopNarration() {
  narrationToken += 1;
  try {
    window.speechSynthesis?.cancel();
  } catch {
    /* ignore */
  }
  if (els.player) {
    els.player.pause();
    els.player.removeAttribute("src");
    els.player.load?.();
  }
  if (activeListenBtn) {
    activeListenBtn.textContent = "Listen";
    activeListenBtn.setAttribute("aria-pressed", "false");
    activeListenBtn = null;
  }
}

function stripForSpeech(text) {
  return String(text || "")
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/[#*_>]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function speakableText(answer) {
  const parts = [];
  for (const section of answer?.sections || []) {
    const heading = stripForSpeech(section.heading);
    const body = stripForSpeech(section.body);
    if (heading) parts.push(heading);
    if (body) parts.push(body);
  }
  return parts.join(". ");
}

function splitUtterances(text) {
  const clipped = text.length > 2500 ? `${text.slice(0, 2500)}.` : text;
  const pieces = clipped.match(/[^.!?]+[.!?]+|[^.!?]+$/g) || [clipped];
  const chunks = [];
  let buf = "";
  for (const piece of pieces) {
    const next = piece.trim();
    if (!next) continue;
    if (buf && buf.length + next.length > 220) {
      chunks.push(buf);
      buf = next;
    } else {
      buf = buf ? `${buf} ${next}` : next;
    }
  }
  if (buf) chunks.push(buf);
  return chunks;
}

function markListenIdle() {
  if (activeListenBtn) {
    activeListenBtn.textContent = "Listen";
    activeListenBtn.setAttribute("aria-pressed", "false");
    activeListenBtn = null;
  }
}

function playBrowserSpeech(text, token) {
  const synth = window.speechSynthesis;
  if (!synth) {
    announce("Voice narration is not available in this browser.");
    markListenIdle();
    return;
  }
  const chunks = splitUtterances(text);
  let index = 0;
  const next = () => {
    if (token !== narrationToken) return;
    if (index >= chunks.length) {
      markListenIdle();
      return;
    }
    const utterance = new SpeechSynthesisUtterance(chunks[index]);
    index += 1;
    utterance.rate = 1.02;
    utterance.lang = "en-US";
    utterance.onend = next;
    utterance.onerror = next;
    synth.speak(utterance);
  };
  next();
}

async function playGeminiWav(text, token) {
  const res = await fetch(window.navaidApi("/speak"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  if (token !== narrationToken) return true;
  if (!res.ok) return false;
  const blob = await res.blob();
  if (token !== narrationToken) return true;
  if (!els.player || blob.size < 80) return false;
  const url = URL.createObjectURL(blob);
  els.player.src = url;
  els.player.onended = () => {
    URL.revokeObjectURL(url);
    if (token === narrationToken) markListenIdle();
  };
  els.player.onerror = () => {
    URL.revokeObjectURL(url);
    if (token === narrationToken) playBrowserSpeech(text, token);
  };
  try {
    await els.player.play();
    announce("Speaking with Gemini TTS.");
    return true;
  } catch {
    URL.revokeObjectURL(url);
    return false;
  }
}

async function narrateAnswer(answer, button) {
  const text = speakableText(answer);
  if (!text) {
    announce("Nothing to speak.");
    return;
  }
  if (button && activeListenBtn === button) {
    stopNarration();
    return;
  }
  stopNarration();
  const token = narrationToken;
  activeListenBtn = button || null;
  if (button) {
    button.textContent = "Stop";
    button.setAttribute("aria-pressed", "true");
  }
  announce("Speaking answer…");
  try {
    const usedGemini = await playGeminiWav(text, token);
    if (token !== narrationToken) return;
    if (!usedGemini) playBrowserSpeech(text, token);
  } catch {
    if (token === narrationToken) playBrowserSpeech(text, token);
  }
}

function showError(message) {
  if (!message) {
    els.error.hidden = true;
    els.error.textContent = "";
    return;
  }
  els.error.hidden = false;
  els.error.textContent = message;
}

function fillList(node, items, emptyText) {
  node.replaceChildren();
  const values = (items || []).filter(Boolean);
  if (!values.length) {
    node.append(el("li", { text: emptyText || "—" }));
    return;
  }
  for (const item of values) node.append(el("li", { text: String(item) }));
}

function constraintBadge(type, multiplier) {
  const key = String(type || "").toLowerCase();
  const cls =
    key === "landside"
      ? "badge badge--landside"
      : key === "airside"
        ? "badge badge--airside"
        : key === "mixed"
          ? "badge badge--mixed"
          : "badge badge--demand";
  const mult = multiplier ?? CONSTRAINT_MULT[key] ?? "";
  const label = type ? `${type}${mult !== "" ? ` ×${fmt(mult, 2)}` : ""}` : "—";
  return el("span", { class: cls, text: label });
}

function renderEnvelope(envelope) {
  if (!envelope) return;
  els.asOf.textContent = envelope.as_of || "unknown";
  els.confidence.textContent = envelope.confidence || "—";
  fillList(els.assumptions, envelope.assumptions, "None listed");
  fillList(els.uncertainties, envelope.uncertainties, "None listed");
  fillList(els.oos, envelope.out_of_scope, "None listed");
  fillList(els.sources, envelope.sources, "None listed");
}

function tableFromRows(headers, rows) {
  const table = el("table");
  const thead = el("thead", {}, el("tr", {}, ...headers.map((h) => el("th", { text: h }))));
  const tbody = el("tbody");
  for (const row of rows) {
    const tr = el("tr");
    for (const cell of row) {
      if (cell instanceof Node) tr.append(el("td", {}, cell));
      else tr.append(el("td", { class: typeof cell === "number" ? "num" : "", text: cell == null ? "—" : String(cell) }));
    }
    tbody.append(tr);
  }
  table.append(thead, tbody);
  return table;
}

function foldPanel({ kicker, count, trail, body }) {
  const details = el("details", { class: "turn__fold" });
  const summary = el("summary");
  summary.append(
    el("span", { class: "turn__fold-toggle", "aria-hidden": "true" }),
    el("span", { class: "turn__fold-kicker", text: kicker }),
  );
  if (count) summary.append(el("span", { class: "turn__fold-count", text: count }));
  if (trail) summary.append(el("span", { class: "turn__fold-trail", text: trail }));
  summary.append(el("span", { class: "turn__fold-action" }));
  const wrap = el("div", { class: "turn__fold-body" });
  if (Array.isArray(body)) {
    for (const node of body) if (node) wrap.append(node);
  } else if (body) {
    wrap.append(body);
  }
  details.append(summary, wrap);
  return details;
}

function renderRanking(tables, traces) {
  const ranking = tables?.ranking;
  if (!Array.isArray(ranking) || !ranking.length) return null;
  const peers = tables.ranking_peer_set;
  const peerTxt = Array.isArray(peers) && peers.length ? `Peer set S: ${peers.join(", ")}` : "";
  const byAirport = Object.fromEntries((traces || []).map((t) => [t.airport, t]));
  const rows = ranking.map((row) => {
    const trace = byAirport[row.airport] || {};
    const constraint = row.constraint_type || trace.constraint_type;
    const mult = trace.constraint_multiplier;
    return [
      row.rank ?? trace.rank,
      row.airport,
      row.icao || "",
      fmt(row.teoi ?? row.score ?? trace.teoi, 1),
      constraintBadge(constraint, mult),
    ];
  });
  return foldPanel({
    kicker: "Rankings",
    count: ranking.length === 1 ? "1 airport" : `${ranking.length} airports`,
    trail: peerTxt,
    body: el("div", { class: "table-wrap" }, tableFromRows(["Rank", "Airport", "ICAO", "TEOI", "Constraint"], rows)),
  });
}

function metricTable(title, obj) {
  if (!obj || typeof obj !== "object") return null;
  const wrap = el("section");
  wrap.append(el("h3", { text: title }));
  const rows = Object.entries(obj)
    .filter(([, v]) => v == null || ["string", "number", "boolean"].includes(typeof v) || Array.isArray(v))
    .map(([k, v]) => [k.replaceAll("_", " "), Array.isArray(v) ? v.join(", ") : v]);
  wrap.append(el("div", { class: "table-wrap" }, tableFromRows(["Field", "Value"], rows)));
  return wrap;
}

function renderCongestion(payload) {
  if (!payload?.metrics) return null;
  const airports = payload.airports || Object.keys(payload.metrics);
  const axes = [
    "delay_pct",
    "avg_arrival_delay_min",
    "cancel_pct",
    "ops_per_runway",
    "live_faa_status",
    "constraint_type",
  ];
  const headers = ["Axis", ...airports, "Winner"];
  const rows = axes.map((axis) => {
    const cells = [axis.replaceAll("_", " ")];
    for (const code of airports) {
      const metrics = payload.metrics[code] || {};
      cells.push(metrics[axis] ?? "—");
    }
    cells.push(payload.winner_on_each_axis?.[axis] ?? "—");
    return cells;
  });
  const wrap = el("section");
  wrap.append(el("h3", { text: "Congestion compare (no single score)" }));
  wrap.append(el("div", { class: "table-wrap" }, tableFromRows(headers, rows)));
  return wrap;
}

function renderExtraTables(tables) {
  const nodes = [];
  const labels = [];
  if (tables?.congestion) {
    const node = renderCongestion(tables.congestion);
    if (node) {
      nodes.push(node);
      labels.push("congestion");
    }
  }
  if (tables?.unmet) {
    const node = metricTable("Unmet demand", tables.unmet);
    if (node) {
      nodes.push(node);
      labels.push("unmet");
    }
  }
  if (tables?.longhaul) {
    const node = metricTable("Long-haul share", tables.longhaul);
    if (node) {
      nodes.push(node);
      labels.push("long-haul");
    }
  }
  if (!nodes.length) return null;
  return foldPanel({
    kicker: "Engine tables",
    count: nodes.length === 1 ? "1 table" : `${nodes.length} tables`,
    trail: labels.join(" · "),
    body: nodes,
  });
}

function renderWaterfall(trace) {
  const figure = el("figure", { class: "waterfall" });
  const cap = el("figcaption");
  cap.append(
    `${trace.airport} · rank ${trace.rank ?? "—"} · TEOI ${fmt(trace.teoi, 1)} · `,
    constraintBadge(trace.constraint_type, trace.constraint_multiplier),
  );
  figure.append(cap);
  if (trace.formula_text) figure.append(el("p", { class: "formula", text: trace.formula_text }));
  if (trace.weights_dropped?.length) {
    figure.append(
      el("p", {
        class: "section-note",
        text: `Dropped and renormalized: ${trace.weights_dropped.join(", ")}`,
      }),
    );
  }
  const used = trace.weights_used || {};
  const contrib = trace.contributions || {};
  const maxContrib = Math.max(1, ...Object.values(contrib).map((n) => Number(n) || 0));
  const bodyRows = Object.keys(used).map((name) => {
    const share = ((Number(contrib[name]) || 0) / maxContrib) * 100;
    const bar = el("span", { class: "bar" }, el("span", { class: "visually-hidden", text: fmt(contrib[name], 1) }));
    bar.style.setProperty("--w", `${share}%`);
    return el(
      "tr",
      {},
      el("td", { text: FEATURE_LABELS[name] || name }),
      el("td", { class: "num", text: fmt(trace.raw?.[name], 3) }),
      el("td", { class: "num", text: fmt(trace.scaled_0_1?.[name], 2) }),
      el("td", { class: "num", text: fmt(used[name], 3) }),
      el("td", { class: "num", text: fmt(contrib[name], 1) }),
      el("td", {}, bar),
    );
  });
  const table = el(
    "table",
    {},
    el(
      "thead",
      {},
      el(
        "tr",
        {},
        ...["Feature", "Raw", "Scaled 0–1", "Weight used", "Contribution", ""].map((h) => el("th", { text: h })),
      ),
    ),
    el("tbody", {}, ...bodyRows),
    el(
      "tfoot",
      {},
      el("tr", {}, el("th", { colspan: "4", text: "Weighted sum" }), el("td", { class: "num", text: fmt(trace.weighted_sum, 1) }), el("td")),
      el(
        "tr",
        {},
        el("th", { colspan: "4", text: `× ${trace.constraint_type || "constraint"} ${fmt(trace.constraint_multiplier, 2)}` }),
        el("td", { class: "num", text: fmt(trace.teoi, 1) }),
        el("td"),
      ),
    ),
  );
  figure.append(el("div", { class: "table-wrap" }, table));
  return figure;
}

function renderTraces(traces) {
  if (!traces?.length) return null;
  const ordered = [...traces].sort((a, b) => (a.rank || 99) - (b.rank || 99));
  const codes = ordered.map((t) => t.airport).filter(Boolean);
  return foldPanel({
    kicker: "TEOI waterfall",
    count: ordered.length === 1 ? "1 trace" : `${ordered.length} traces`,
    trail: codes.join(", "),
    body: [
      el("p", {
        class: "section-note",
        text: "Raw metric → peer min-max → weight → contribution → constraint multiplier → score.",
      }),
      ...ordered.map((trace) => renderWaterfall(trace)),
    ],
  });
}

function stepTrail(steps) {
  const names = [];
  for (const step of steps || []) {
    const name = String(step.name || "").trim();
    if (name && names[names.length - 1] !== name) names.push(name);
  }
  return names;
}

function renderTurnSteps(steps) {
  const list = Array.isArray(steps) ? steps : [];
  const ol = el("ol", { class: "step-list" });
  if (!list.length) {
    ol.append(el("li", { text: "No steps recorded for this turn." }));
  } else {
    for (const step of list) {
      const item = el("li");
      const label = el("div", { class: "step-list__name" });
      label.append(el("strong", { text: step.name || `step ${step.index}` }));
      item.append(label);
      if (step.detail) {
        item.append(el("div", { class: "step-list__detail", text: step.detail }));
      }
      ol.append(item);
    }
  }
  return foldPanel({
    kicker: "Working",
    count: list.length === 1 ? "1 step" : `${list.length} steps`,
    trail: stepTrail(list).join(" → "),
    body: ol,
  });
}

function renderUnsupported(parts) {
  if (!parts?.length) return null;
  const list = el("ul", { class: "unsupported-list" });
  for (const part of parts) {
    list.append(el("li", { text: `${part.text}: ${part.reason}` }));
  }
  return foldPanel({
    kicker: "Unsupported",
    count: parts.length === 1 ? "1 part" : `${parts.length} parts`,
    trail: parts.map((p) => p.text).filter(Boolean).join(" · "),
    body: list,
  });
}

function renderCitations(citations) {
  if (!citations?.length) return null;
  const list = el("ul", { class: "cite-list" });
  for (const cite of citations) {
    const item = el("li");
    if (cite.url) item.append(el("a", { href: cite.url, text: cite.label || cite.url }));
    else item.append(document.createTextNode(cite.label || cite.source || "source"));
    if (cite.source && cite.label !== cite.source) item.append(document.createTextNode(` · ${cite.source}`));
    if (cite.as_of) item.append(document.createTextNode(` · as_of ${cite.as_of}`));
    list.append(item);
  }
  return foldPanel({
    kicker: "Citations",
    count: citations.length === 1 ? "1 source" : `${citations.length} sources`,
    body: list,
  });
}

function renderTurn(question, answer) {
  const item = el("li", { class: "turn" });
  const user = el("div", { class: "turn--user" });
  user.append(el("p", { class: "turn__who", text: "You" }), el("p", { class: "turn__body", text: question }));
  const agent = el("div", { class: "turn--agent" });
  const listen = el("button", {
    type: "button",
    class: "btn btn--ghost btn--small turn__listen",
    text: "Listen",
    "aria-pressed": "false",
  });
  listen.addEventListener("click", () => narrateAnswer(answer, listen));
  const head = el("div", { class: "turn__agent-head" });
  head.append(el("p", { class: "turn__who", text: "Navaid" }), listen);
  agent.append(head);
  if (answer.reconstructed_query && answer.reconstructed_query !== question) {
    agent.append(el("p", { class: "turn__recon", text: `Reconstructed: ${answer.reconstructed_query}` }));
  }
  if (answer.reconstruction_notes) {
    agent.append(el("p", { class: "turn__recon", text: answer.reconstruction_notes }));
  }
  if (answer.subgoals?.length) {
    const row = el("div", { class: "subgoal-row" });
    for (const sg of answer.subgoals) {
      row.append(el("span", { class: "badge", text: `${sg.intent}${sg.entities?.length ? ` · ${sg.entities.join(", ")}` : ""}` }));
    }
    agent.append(row);
  }
  for (const section of answer.sections || []) {
    const block = el("div", { class: "turn__section" });
    block.append(el("h3", { text: section.heading || "Section" }));
    const prose = el("div", { class: "prose-answer", html: renderMarkdown(section.body || "") });
    block.append(prose);
    agent.append(block);
  }
  const folds = el("div", { class: "turn__folds" });
  for (const panel of [
    renderTurnSteps(answer.steps),
    renderRanking(answer.tables || {}, answer.teoi_traces || []),
    renderTraces(answer.teoi_traces || []),
    renderExtraTables(answer.tables || {}),
    renderCitations(answer.citations || []),
    renderUnsupported(answer.unsupported_parts),
  ]) {
    if (panel) folds.append(panel);
  }
  agent.append(folds);
  item.append(user, agent);
  els.transcript.append(item);
  els.empty.hidden = true;
  item.scrollIntoView({ block: "nearest", behavior: "smooth" });
  return listen;
}

function renderAnswer(question, answer) {
  const listen = renderTurn(question, answer);
  renderEnvelope(answer.envelope);
  if (speakEnabled()) narrateAnswer(answer, listen);
}

const PENDING_COPY = [
  "Reconstructing the question…",
  "Pulling warehouse metrics…",
  "Scoring TEOI traces…",
  "Locking numbers…",
  "Writing the answer…",
];

let asking = false;
let pendingTimer = null;
let pendingIndex = 0;

function spinnerNode() {
  return el(
    "span",
    { class: "spinner", "aria-hidden": "true" },
    el("span"),
    el("span"),
    el("span"),
  );
}

function announce(message) {
  if (els.live) els.live.textContent = message;
}

function stopPendingTicker() {
  if (pendingTimer) {
    clearInterval(pendingTimer);
    pendingTimer = null;
  }
}

function clearPendingTurn() {
  stopPendingTicker();
  document.getElementById("turn-pending")?.remove();
}

function setPendingStatus(text) {
  const status = document.getElementById("pending-status");
  if (status) status.textContent = text;
}

function showPending(question) {
  clearPendingTurn();
  els.empty.hidden = true;
  pendingIndex = 0;
  const item = el("li", { class: "turn turn--pending", id: "turn-pending" });
  const user = el("div", { class: "turn--user" });
  user.append(el("p", { class: "turn__who", text: "You" }), el("p", { class: "turn__body", text: question }));
  const agent = el("div", { class: "turn--agent" });
  const line = el("div", { class: "pending-line" });
  line.append(spinnerNode(), el("p", { class: "turn__pending-status", id: "pending-status", text: PENDING_COPY[0] }));
  agent.append(el("p", { class: "turn__who", text: "Navaid" }), line);
  item.append(user, agent);
  els.transcript.append(item);
  item.scrollIntoView({ block: "nearest", behavior: "smooth" });
  announce(PENDING_COPY[0]);
  pendingTimer = setInterval(() => {
    pendingIndex = (pendingIndex + 1) % PENDING_COPY.length;
    const text = PENDING_COPY[pendingIndex];
    setPendingStatus(text);
    announce(text);
  }, 1600);
}

function failPending(message) {
  stopPendingTicker();
  const item = document.getElementById("turn-pending");
  if (!item) return;
  item.classList.remove("turn--pending");
  item.classList.add("turn--failed");
  item.removeAttribute("id");
  const line = item.querySelector(".pending-line");
  if (line) {
    line.replaceChildren(el("p", { class: "turn__pending-status", text: message }));
  }
}

function setBusy(on) {
  asking = on;
  document.body.classList.toggle("busy", on);
  els.form?.setAttribute("aria-busy", on ? "true" : "false");
  els.submit.disabled = on;
  els.submit.setAttribute("aria-busy", on ? "true" : "false");
  document.querySelectorAll("[data-prompt], #new-session").forEach((node) => {
    node.disabled = on;
  });
  if (on) {
    els.hint.textContent = useGemini()
      ? "Working — reconstruct, engines, then Gemini narration. This can take a few seconds."
      : "Working — reconstruct and engines (template narration).";
  } else {
    els.hint.textContent = defaultHint();
  }
}

function clearComposer() {
  const field = document.getElementById("question") || els.question;
  if (!field) return;
  field.value = "";
}

async function ask(question) {
  const q = question.trim();
  if (!q || asking) return;
  showError("");
  stopNarration();
  setBusy(true);
  showPending(q);
  const sessionId = getSessionId();
  try {
    const res = await fetch(window.navaidApi("/ask"), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Session-Id": sessionId,
      },
      body: JSON.stringify({
        question: q,
        session_id: sessionId,
        use_gemini: useGemini(),
      }),
    });
    const payload = await res.json().catch(() => ({}));
    const returned = res.headers.get("X-Session-Id");
    if (returned) setSessionId(returned);
    if (!res.ok) {
      const message = payload.error || `Request failed (${res.status})`;
      showError(message);
      failPending(message);
      announce(message);
      return;
    }
    clearPendingTurn();
    renderAnswer(q, payload);
    announce("Answer ready.");
  } catch (err) {
    const message = err instanceof Error ? err.message : "Network error";
    showError(message);
    failPending(message);
    announce(message);
  } finally {
    setBusy(false);
    clearComposer();
    const field = document.getElementById("question") || els.question;
    field?.focus();
  }
}

async function init() {
  setSessionId(getSessionId());
  const params = new URLSearchParams(location.search);
  const paramGemini = parseUseGeminiParam();
  const health = await fetchHealth();
  const keyPresent = Boolean(health?.gemini_configured);
  const auth = health?.gemini_auth || (keyPresent ? "configured" : "none");
  geminiConfigured = keyPresent;
  geminiAuthLabel = health?.model || auth;
  const stored = parseStoredGemini();
  setSwitch(paramGemini ?? stored ?? keyPresent);
  setSpeak(parseStoredSpeak() ?? false);
  els.warehouse.textContent = health?.warehouse ? "snapshot" : "missing";

  els.gemini.addEventListener("click", (event) => {
    event.preventDefault();
    setSwitch(!useGemini());
  });
  els.speak?.addEventListener("click", (event) => {
    event.preventDefault();
    setSpeak(!speakEnabled());
  });
  els.newSession.addEventListener("click", () => {
    const id = crypto.randomUUID();
    setSessionId(id);
    stopNarration();
    clearPendingTurn();
    setBusy(false);
    els.transcript.replaceChildren();
    els.empty.hidden = false;
    showError("");
    announce("New session.");
  });
  document.querySelectorAll("[data-prompt]").forEach((btn) => {
    btn.addEventListener("click", () => {
      els.question.value = btn.dataset.prompt;
      ask(btn.dataset.prompt);
    });
  });
  els.form.addEventListener("submit", (event) => {
    event.preventDefault();
    ask(els.question.value);
  });
  els.question.addEventListener("keydown", (event) => {
    if (event.key !== "Enter") return;
    if (event.shiftKey) {
      event.preventDefault();
      ask(els.question.value);
    }
  });

  const preset = params.get("q");
  if (preset) {
    els.question.value = preset;
    if (params.get("autosubmit") === "1") ask(preset);
  }
}

init();
