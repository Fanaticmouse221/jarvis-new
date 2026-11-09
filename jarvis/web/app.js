// JARVIS web client: conversations, streaming chat, and small conveniences.
// Plain JavaScript with no build step, so it runs as-is on any modern browser.

import { renderMarkdown } from "./markdown.js";

const $ = (id) => document.getElementById(id);
const els = {
  sidebar: $("sidebar"), scrim: $("scrim"), menuBtn: $("menuBtn"), newChat: $("newChat"),
  list: $("conversationList"), title: $("title"), status: $("status"), messages: $("messages"),
  composer: $("composer"), input: $("input"), send: $("send"), announcer: $("announcer"),
};

const state = { conversations: [], currentId: null, streaming: false, controller: null, health: null };
const touch = window.matchMedia("(pointer: coarse)").matches;

const TRASH_SVG = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"/></svg>';
const SUGGESTIONS = [
  ["Explain a concept", "Explain the chain rule with a worked example."],
  ["Plan something", "Help me plan a study timetable for this week."],
  ["Write some code", "Write a Python function that checks whether a number is prime, with tests."],
  ["Capabilities", "What can you do right now, and what's coming next?"],
];

// ---------- helpers ----------

const timeFormat = new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit", hour12: true });
const dateFormat = new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short" });
const fmtTime = (iso) => (iso ? timeFormat.format(new Date(iso)) : "");

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

async function api(path, options = {}) {
  const response = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
  if (!response.ok) throw new Error(await errorText(response));
  return response.status === 204 ? null : response.json();
}

async function errorText(response) {
  try {
    const data = await response.json();
    if (typeof data.detail === "string") return data.detail;
    if (Array.isArray(data.detail)) return data.detail.map((d) => d.msg).join("; ");
  } catch { /* not JSON */ }
  return `Request failed (HTTP ${response.status}).`;
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const area = el("textarea");
    area.value = text;
    document.body.append(area);
    area.select();
    document.execCommand("copy");
    area.remove();
  }
}

function announce(text) { els.announcer.textContent = text; }

function groupFor(iso) {
  const then = new Date(iso);
  const startOfToday = new Date(); startOfToday.setHours(0, 0, 0, 0);
  const days = Math.floor((startOfToday - new Date(then).setHours(0, 0, 0, 0)) / 86400000);
  if (days <= 0) return "Today";
  if (days === 1) return "Yesterday";
  if (days < 7) return "Previous 7 days";
  return "Older";
}

function nearBottom() {
  const m = els.messages;
  return m.scrollHeight - m.scrollTop - m.clientHeight < 140;
}
function scrollToBottom(force = false) {
  if (force || nearBottom()) els.messages.scrollTop = els.messages.scrollHeight;
}

// ---------- status ----------

function setStatus(kind, text, tooltip) {
  els.status.className = `status ${kind}`;
  els.status.querySelector(".status-text").textContent = text;
  els.status.title = tooltip || text;
}

async function loadHealth() {
  try {
    const health = await api("/api/health");
    state.health = health;
    if (health.status === "ok") {
      const primary = health.models[0] || "";
      setStatus("ok", primary.slice(primary.indexOf(":") + 1) || "Online", `Models (in priority order):\n${health.models.join("\n")}`);
    } else {
      setStatus("warn", "No model configured", health.skipped.join("\n") || "Set JARVIS_MODELS in .env");
    }
  } catch {
    setStatus("error", "Offline", "Can't reach the JARVIS server. Is it running?");
  }
}

// ---------- sidebar ----------

function renderList() {
  els.list.replaceChildren();
  if (!state.conversations.length) {
    els.list.append(el("div", "empty-list", "No conversations yet."));
    return;
  }
  let lastGroup = null;
  for (const conv of state.conversations) {
    const group = groupFor(conv.updated_at);
    if (group !== lastGroup) {
      els.list.append(el("div", "group-label", group));
      lastGroup = group;
    }
    const row = el("div", "conv" + (conv.id === state.currentId ? " active" : ""));
    const open = el("button", "conv-open", conv.title);
    open.type = "button";
    open.title = `${conv.title}\n${dateFormat.format(new Date(conv.updated_at))}, ${fmtTime(conv.updated_at)}`;
    open.addEventListener("click", () => openConversation(conv.id));
    const del = el("button", "conv-delete");
    del.type = "button";
    del.innerHTML = TRASH_SVG;
    del.setAttribute("aria-label", `Delete conversation: ${conv.title}`);
    del.addEventListener("click", () => confirmDelete(del, conv.id));
    row.append(open, del);
    els.list.append(row);
  }
}

async function loadConversations() {
  try {
    state.conversations = await api("/api/conversations");
  } catch {
    state.conversations = [];
  }
  renderList();
}

function confirmDelete(button, id) {
  if (!button.classList.contains("confirm")) {
    button.classList.add("confirm");
    button.textContent = "Delete?";
    setTimeout(() => {
      if (button.isConnected) { button.classList.remove("confirm"); button.innerHTML = TRASH_SVG; }
    }, 3000);
    return;
  }
  api(`/api/conversations/${id}`, { method: "DELETE" })
    .then(() => {
      state.conversations = state.conversations.filter((c) => c.id !== id);
      if (state.currentId === id) newConversation();
      else renderList();
    })
    .catch((err) => alertInline(`Couldn't delete: ${err.message}`));
}

function openSidebar(open) {
  els.sidebar.classList.toggle("open", open);
  els.scrim.hidden = !open;
}

// ---------- messages ----------

function setTitle(text) {
  els.title.textContent = text;
  document.title = state.currentId ? `${text} · J.A.R.V.I.S.` : "J.A.R.V.I.S.";
}

function greeting() {
  const hour = new Date().getHours();
  const part = hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
  const title = state.health?.user_title;
  return `${part}${title ? `, ${title}` : ""}.`;
}

function renderWelcome() {
  const box = el("div", "welcome");
  box.append(el("span", "orb"), el("h2", "", greeting()), el("p", "", "How may I assist?"));
  const grid = el("div", "suggestions");
  for (const [label, prompt] of SUGGESTIONS) {
    const btn = el("button", "suggestion");
    btn.type = "button";
    btn.append(el("strong", "", label), document.createTextNode(prompt));
    btn.addEventListener("click", () => sendMessage(prompt));
    grid.append(btn);
  }
  box.append(grid);
  els.messages.replaceChildren(box);
}

function appendUser(text) {
  const row = el("div", "msg user");
  row.append(el("div", "bubble", text));
  els.messages.append(row);
}

function appendAssistant({ content = "", model = null, createdAt = null, streaming = false } = {}) {
  const row = el("div", "msg assistant" + (streaming ? " streaming" : ""));
  const who = el("div", "who");
  who.append(el("span", "orb"), document.createTextNode("JARVIS"));
  const body = el("div", "md");
  const meta = el("div", "meta");
  row.append(who, body, meta);
  els.messages.append(row);

  let latest = content;
  let frame = null;
  const render = () => { frame = null; body.innerHTML = renderMarkdown(latest); scrollToBottom(); };
  const setMeta = (modelLabel, iso, text) => {
    meta.replaceChildren();
    if (modelLabel) meta.append(el("span", "", modelLabel));
    if (iso) meta.append(el("span", "", fmtTime(iso)));
    if (text) {
      const copy = el("button", "", "Copy");
      copy.type = "button";
      copy.addEventListener("click", async () => { await copyText(text); copy.textContent = "Copied"; setTimeout(() => (copy.textContent = "Copy"), 1500); });
      meta.append(copy);
    }
  };

  if (streaming) {
    body.innerHTML = '<div class="typing" aria-label="JARVIS is thinking"><span></span><span></span><span></span></div>';
  } else {
    body.innerHTML = renderMarkdown(content);
    setMeta(model, createdAt, content);
  }

  return {
    update(text) { latest = text; if (!frame) frame = requestAnimationFrame(render); },
    finish(text, modelLabel, iso) {
      if (frame) cancelAnimationFrame(frame);
      latest = text; render();
      row.classList.remove("streaming");
      setMeta(modelLabel, iso || new Date().toISOString(), text);
    },
    fail(message, partial) {
      if (frame) cancelAnimationFrame(frame);
      row.classList.remove("streaming");
      body.innerHTML = partial ? renderMarkdown(partial) : "";
      meta.replaceChildren(el("div", "error-box", message));
      scrollToBottom();
    },
  };
}

function alertInline(message) {
  const reply = appendAssistant({ streaming: true });
  reply.fail(message);
}

function renderConversation(messages) {
  els.messages.replaceChildren();
  for (const m of messages) {
    if (m.role === "user") appendUser(m.content);
    else appendAssistant({ content: m.content, model: m.model, createdAt: m.created_at });
  }
  scrollToBottom(true);
}

async function openConversation(id) {
  if (state.streaming) state.controller?.abort();
  openSidebar(false);
  try {
    const data = await api(`/api/conversations/${id}`);
    state.currentId = id;
    history.replaceState(null, "", `#c=${id}`);
    setTitle(data.conversation.title);
    renderConversation(data.messages);
    renderList();
  } catch (err) {
    if (String(err.message).includes("not found")) newConversation();
    else alertInline(`Couldn't open conversation: ${err.message}`);
  }
  if (!touch) els.input.focus();
}

function newConversation() {
  if (state.streaming) state.controller?.abort();
  state.currentId = null;
  history.replaceState(null, "", location.pathname);
  setTitle("New conversation");
  renderWelcome();
  renderList();
  openSidebar(false);
  els.input.focus();
}

// ---------- sending & streaming ----------

function setStreaming(on) {
  state.streaming = on;
  els.send.classList.toggle("stop", on);
  els.send.setAttribute("aria-label", on ? "Stop" : "Send");
  updateSendButton();
}

function updateSendButton() {
  els.send.disabled = !state.streaming && !els.input.value.trim();
}

function parseEvent(block) {
  let type = "message";
  const data = [];
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) type = line.slice(6).trim();
    else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
  }
  if (!data.length) return null;
  try { return { type, ...JSON.parse(data.join("\n")) }; } catch { return null; }
}

async function sendMessage(text) {
  text = text.trim();
  if (!text || state.streaming) return;
  if (els.messages.querySelector(".welcome")) els.messages.replaceChildren();

  appendUser(text);
  const reply = appendAssistant({ streaming: true });
  scrollToBottom(true);
  els.input.value = "";
  autosize();

  const controller = new AbortController();
  state.controller = controller;
  setStreaming(true);
  announce("JARVIS is responding.");

  let content = "";
  let model = null;
  let settled = false;
  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ conversation_id: state.currentId, message: text }),
      signal: controller.signal,
    });
    if (!response.ok) throw new Error(await errorText(response));

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let split;
      while ((split = buffer.indexOf("\n\n")) !== -1) {
        const event = parseEvent(buffer.slice(0, split));
        buffer = buffer.slice(split + 2);
        if (!event) continue;
        if (event.type === "conversation") {
          state.currentId = event.conversation.id;
          history.replaceState(null, "", `#c=${state.currentId}`);
          setTitle(event.conversation.title);
          if (!state.conversations.some((c) => c.id === state.currentId)) {
            state.conversations.unshift({ ...event.conversation, message_count: 1 });
          }
          renderList();
        } else if (event.type === "model") {
          model = event.model;
        } else if (event.type === "token") {
          content += event.text;
          reply.update(content);
        } else if (event.type === "done") {
          reply.finish(content, model, event.message?.created_at);
          settled = true;
          announce("JARVIS replied.");
        } else if (event.type === "error") {
          reply.fail(event.message, content);
          settled = true;
          announce("JARVIS hit an error.");
        }
      }
    }
    if (!settled) reply.fail("The connection closed before JARVIS finished replying.", content);
  } catch (err) {
    if (err.name === "AbortError") reply.finish(content ? `${content}\n\n*[Stopped]*` : "*[Stopped]*", model);
    else reply.fail(err.message === "Failed to fetch" ? "Can't reach the JARVIS server. Is it still running?" : err.message, content);
  } finally {
    state.controller = null;
    setStreaming(false);
    loadConversations();
  }
}

// ---------- composer ----------

function autosize() {
  els.input.style.height = "auto";
  els.input.style.height = `${Math.min(els.input.scrollHeight, 220)}px`;
  updateSendButton();
}

els.input.addEventListener("input", autosize);
els.input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing && !touch) {
    event.preventDefault();
    els.composer.requestSubmit();
  }
});
els.composer.addEventListener("submit", (event) => {
  event.preventDefault();
  if (state.streaming) state.controller?.abort();
  else sendMessage(els.input.value);
});

// ---------- rename (click the title) ----------

els.title.addEventListener("click", () => {
  if (!state.currentId || els.title.hidden) return;
  const input = el("input", "title-input");
  input.value = els.title.textContent;
  input.maxLength = 200;
  input.setAttribute("aria-label", "Conversation title");
  els.title.hidden = true;
  els.title.after(input);
  input.focus();
  input.select();
  let done = false;
  const finish = async (save) => {
    if (done) return;
    done = true;
    const value = input.value.trim();
    input.remove();
    els.title.hidden = false;
    if (save && value && value !== els.title.textContent) {
      try {
        const updated = await api(`/api/conversations/${state.currentId}`, { method: "PATCH", body: JSON.stringify({ title: value }) });
        setTitle(updated.title);
        loadConversations();
      } catch (err) {
        alertInline(`Couldn't rename: ${err.message}`);
      }
    }
  };
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") finish(true);
    if (event.key === "Escape") finish(false);
  });
  input.addEventListener("blur", () => finish(true));
});

// ---------- other wiring ----------

els.newChat.addEventListener("click", newConversation);
els.menuBtn.addEventListener("click", () => openSidebar(true));
els.scrim.addEventListener("click", () => openSidebar(false));
els.messages.addEventListener("click", async (event) => {
  const button = event.target.closest(".copy-code");
  if (!button) return;
  await copyText(button.closest(".code-block").querySelector("code").textContent);
  button.textContent = "Copied";
  setTimeout(() => (button.textContent = "Copy"), 1500);
});

// ---------- start ----------

(async function start() {
  await loadHealth();
  await loadConversations();
  const match = location.hash.match(/^#c=([0-9a-f]+)$/);
  if (match) await openConversation(match[1]);
  else newConversation();
  setInterval(loadHealth, 60000);
})();
