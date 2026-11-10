// The conversation screen: sidebar, thread, composer, and the live view of each reply
// (streamed text, real tool steps, approval requests, and what JARVIS learned).

import { api, streamChat } from "./api.js";
import { createCore } from "./core.js";
import { enableCodeCopy, renderInto } from "./render.js";
import { copyText, dayLabel, debounce, fmtDuration, fmtTime, h, icon, iconButton, plural, toast } from "./util.js";

const $ = (id) => document.getElementById(id);
const els = {
  sidebar: $("sidebar"), scrim: $("scrim"), menuBtn: $("menuBtn"), newChat: $("newChat"), search: $("searchInput"),
  list: $("conversationList"), title: $("title"), thread: $("thread"), composer: $("composer"), input: $("input"),
  send: $("send"), voice: $("voiceBtn"), voiceStatus: $("voiceStatus"), modelSelect: $("modelSelect"), exportBtn: $("exportBtn"),
};

const state = { ctx: null, conversations: [], currentId: null, streaming: false, controller: null, core: null, recorder: null, voiceReply: false, voiceStream: null, voiceContext: null, voiceFrame: 0, voiceTimer: null };
const touch = window.matchMedia("(pointer: coarse)").matches;
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const STARTERS = [
  { title: "Tell JARVIS about yourself", text: "A few things about me: ", fill: true },
  { title: "Open an app", text: "Open ", fill: true },
  { title: "Explain something", text: "Explain the chain rule with a worked example." },
  { title: "Check this computer", text: "How is my computer doing?" },
];
const STEP_ICON = { ok: "check", error: "circle-alert", denied: "ban", cancelled: "ban", awaiting_approval: "shield-alert" };
const STEP_NOTE = { running: "Working", awaiting_approval: "Needs your OK", error: "Failed", denied: "Declined", cancelled: "Stopped" };

// ---------- helpers ----------

function nearBottom() {
  const t = els.thread;
  return t.scrollHeight - t.scrollTop - t.clientHeight < 160;
}
function scrollDown(force = false) {
  if (force || nearBottom()) els.thread.scrollTop = els.thread.scrollHeight;
}
function openSidebar(open) {
  els.sidebar.classList.toggle("open", open);
  els.scrim.hidden = !open;
}
function setTitle(text) {
  els.title.textContent = text;
  els.title.classList.toggle("editable", !!state.currentId);
  els.exportBtn.hidden = !state.currentId;
  document.title = state.currentId ? `${text} | JARVIS` : "JARVIS";
}
function shortModel(label) {
  return label ? label.slice(label.indexOf(":") + 1) : "";
}
function preferredModel() {
  return els.modelSelect.hidden ? null : els.modelSelect.value || null;
}
function markLast() {
  const turns = [...els.thread.querySelectorAll(".turn.assistant")];
  turns.forEach((turn, index) => turn.classList.toggle("last", index === turns.length - 1));
}

// ---------- sidebar ----------

function renderList() {
  els.list.replaceChildren();
  if (!state.conversations.length) {
    els.list.append(h("div", { class: "empty-note", text: els.search.value.trim() ? "No conversations match that." : "No conversations yet." }));
    return;
  }
  let group = null;
  for (const conversation of state.conversations) {
    const label = dayLabel(conversation.updated_at, true);
    if (label !== group) {
      els.list.append(h("div", { class: "group-label", text: label }));
      group = label;
    }
    const remove = iconButton("trash-2", `Delete “${conversation.title}”`, () => confirmDelete(remove, conversation.id));
    els.list.append(
      h(
        "div",
        { class: `conv${conversation.id === state.currentId ? " active" : ""}` },
        h("button", { class: "conv-open", type: "button", text: `${conversation.source === "telegram" ? "📱 " : ""}${conversation.title}`, title: conversation.title, onClick: () => openConversation(conversation.id) }),
        remove,
      ),
    );
  }
}

export async function loadConversations() {
  const query = els.search.value.trim();
  try {
    state.conversations = await api(`/conversations${query ? `?q=${encodeURIComponent(query)}` : ""}`);
  } catch {
    state.conversations = [];
  }
  renderList();
}

function confirmDelete(button, id) {
  if (!button.classList.contains("confirm")) {
    button.classList.add("confirm");
    button.replaceChildren("Delete?");
    setTimeout(() => {
      if (button.isConnected) {
        button.classList.remove("confirm");
        button.replaceChildren(icon("trash-2"));
      }
    }, 3000);
    return;
  }
  api(`/conversations/${id}`, { method: "DELETE" })
    .then(() => {
      state.conversations = state.conversations.filter((c) => c.id !== id);
      if (state.currentId === id) newConversation();
      else renderList();
      state.ctx.refresh();
    })
    .catch((error) => toast(error.message, "error"));
}

// ---------- welcome and first-run setup ----------

function setupPanel() {
  const boot = state.ctx.boot;
  const input = h("input", { class: "input", type: "password", placeholder: "Paste your Groq key (starts with gsk_)", "aria-label": "Groq API key", autocomplete: "off" });
  const problem = h("p", { class: "hint", hidden: true });
  const connect = h("button", { class: "btn primary", type: "submit", text: "Connect" });
  const form = h("form", { class: "setup-row" }, input, connect);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!input.value.trim()) return;
    connect.disabled = true;
    connect.textContent = "Checking";
    try {
      const result = await api("/keys", { method: "POST", body: { provider: "groq", key: input.value } });
      await state.ctx.refresh();
      toast(result.warning || `Connected. ${plural(result.models.length, "model")} ready.`);
      renderWelcome();
    } catch (error) {
      problem.textContent = error.message;
      problem.style.color = "var(--red)";
      problem.hidden = false;
      connect.disabled = false;
      connect.textContent = "Connect";
    }
  });
  const demo = h("button", { class: "linklike", type: "button", text: "try the scripted demo", onClick: async () => {
    await api("/settings", { method: "PATCH", body: { models: ["fake:agent"] } });
    await state.ctx.refresh();
    toast("Demo brain on. It understands only a few phrasings.");
    renderWelcome();
  } });
  const waiting = boot.models.keys.groq.set && boot.models.skipped.length;
  return h(
    "div",
    { class: "setup" },
    h("h3", { text: waiting ? "No model is ready" : "Connect a model to bring JARVIS online" }),
    waiting
      ? h("p", { text: boot.models.skipped.join(" ") })
      : h("p", { text: "JARVIS thinks with a model from Groq, which has a free tier. No payment details are needed, so nothing can be charged." }),
    h(
      "ol",
      {},
      h("li", {}, "Create a free key at ", h("a", { href: "https://console.groq.com/keys", target: "_blank", rel: "noopener noreferrer", text: "console.groq.com/keys" }), "."),
      h("li", { text: "Paste it below. JARVIS checks it and picks the models your account can use." }),
    ),
    form,
    problem,
    h("p", { class: "hint" }, "The key is stored only on this computer, in the .env file. No key yet? You can ", demo, "."),
  );
}

function renderWelcome() {
  const boot = state.ctx.boot;
  const ready = boot.models.ready.length > 0;
  const canvas = h("canvas", { "aria-hidden": "true" });
  const box = h("div", { class: "welcome" }, canvas, h("h2", { text: boot.greeting }));
  if (!ready) {
    box.append(setupPanel());
  } else {
    box.append(h("p", { class: "lede", text: "How may I assist?" }));
    if (boot.prefs.memory_enabled) {
      box.append(
        boot.memory_count
          ? h("p", { class: "known" }, `${plural(boot.memory_count, "memory", "memories")} on file. `, h("a", { href: "#/memory", text: "Review what I know" }))
          : h("p", { class: "known", text: "I know nothing about you yet. Tell me about yourself and I'll remember it." }),
      );
    }
    if (boot.last_conversation) {
      const last = boot.last_conversation;
      box.append(h("button", { class: "resume", type: "button", onClick: () => openConversation(last.id) }, icon("clock"), h("span", { text: `Continue: ${last.title}` })));
    }
    const grid = h("div", { class: "starters" });
    for (const starter of STARTERS) {
      grid.append(
        h("button", { class: "starter", type: "button", onClick: () => {
          if (!starter.fill) return send(starter.text);
          els.input.value = starter.text;
          autosize();
          els.input.focus();
        } }, h("strong", { text: starter.title }), starter.fill ? `${starter.text}…` : starter.text),
      );
    }
    box.append(grid);
  }
  els.thread.replaceChildren(box);
  state.core = createCore(canvas);
  state.core.setState(ready ? "idle" : "offline");
}

// ---------- turns ----------

function userTurn(message) {
  const bubble = h("div", { class: "bubble", text: message.content });
  const actions = h("div", { class: "turn-actions" });
  const root = h("article", { class: "turn user" }, bubble, actions);
  root.dataset.messageId = message.id ?? "";

  function startEdit() {
    if (state.streaming || !root.dataset.messageId) return;
    const area = h("textarea", { class: "textarea", value: bubble.textContent, rows: 3, "aria-label": "Edit message" });
    const save = h("button", { class: "btn primary small", type: "button", text: "Send again" });
    const cancel = h("button", { class: "btn small", type: "button", text: "Cancel" });
    const editor = h("div", { class: "memory-form" }, area, h("div", { class: "form-actions" }, save, cancel));
    editor.style.width = "min(100%, 620px)";
    bubble.hidden = actions.hidden = true;
    root.append(editor);
    area.focus();
    cancel.addEventListener("click", () => {
      editor.remove();
      bubble.hidden = actions.hidden = false;
    });
    save.addEventListener("click", () => {
      const text = area.value.trim();
      if (!text) return;
      const editId = Number(root.dataset.messageId);
      while (root.nextElementSibling) root.nextElementSibling.remove();
      root.remove();
      send(text, { editId });
    });
  }
  actions.append(iconButton("pencil", "Edit and send again", startEdit), iconButton("copy", "Copy", () => copyText(bubble.textContent).then(() => toast("Copied"))));
  return root;
}

function stepRow(step) {
  const mark = h("span", { class: "step-state" });
  const title = h("span", { class: "step-title" });
  const note = h("span", { class: "step-note" });
  const head = h("button", { class: "step-head", type: "button", "aria-expanded": "false" }, mark, title, note, icon("chevron-right", "chev"));
  const body = h("div", { class: "step-body", hidden: true });
  const root = h("div", { class: "step" }, head, body);
  let approval = null;
  head.addEventListener("click", () => {
    const open = head.getAttribute("aria-expanded") !== "true";
    head.setAttribute("aria-expanded", String(open));
    body.hidden = !open;
  });

  return {
    root,
    update(next) {
      root.dataset.status = next.status;
      mark.replaceChildren(next.status === "running" ? h("span", { class: "spinner" }) : icon(STEP_ICON[next.status] || "circle-alert"));
      title.textContent = next.status === "ok" && next.summary ? next.summary : next.title;
      note.textContent = STEP_NOTE[next.status] || fmtDuration(next.duration_ms);
      const lines = [h("div", { text: `${next.label}: ${next.title}` })];
      if (next.decision === "approved") lines.push(h("div", { text: "Approved by you." }));
      if (next.result) lines.push(h("pre", { text: next.result }));
      body.replaceChildren(...lines);
    },
    ask(request) {
      root.dataset.status = "awaiting_approval";
      mark.replaceChildren(icon("shield-alert"));
      note.textContent = STEP_NOTE.awaiting_approval;
      const always = request.can_always ? h("input", { type: "checkbox" }) : null;
      const allow = h("button", { class: "btn primary small", type: "button", text: "Allow" });
      const deny = h("button", { class: "btn small", type: "button", text: "Don't allow" });
      const answer = async (approve) => {
        allow.disabled = deny.disabled = true;
        try {
          await api(`/approvals/${request.id}`, { method: "POST", body: { approve, always: !!always?.checked } });
        } catch (error) {
          toast(error.message, "error");
        }
      };
      allow.addEventListener("click", () => answer(true));
      deny.addEventListener("click", () => answer(false));
      const wanted = request.title.charAt(0).toLowerCase() + request.title.slice(1);
      approval = h(
        "div",
        { class: "approval", role: "alert" },
        h("h3", { text: `Allow JARVIS to ${wanted}?` }),
        h("p", { text: request.reason }),
        h("div", { class: "approval-actions" }, allow, deny, always ? h("label", {}, always, `Don't ask again for “${request.label}”`) : null),
      );
      root.append(approval);
      allow.focus({ preventScroll: true });
    },
    settle(event) {
      approval?.remove();
      approval = null;
      if (event.decision === "approved") {
        root.dataset.status = "running";
        mark.replaceChildren(h("span", { class: "spinner" }));
        note.textContent = STEP_NOTE.running;
      }
    },
  };
}

function assistantTurn(live) {
  const parts = h("div", { class: "parts" });
  const meta = h("div", { class: "meta" });
  const root = h("article", { class: "turn assistant" }, parts, meta);
  const steps = new Map();
  let textEl = null;
  let buffer = "";
  let frame = null;
  let busy = null;
  let fullText = "";

  const flush = () => {
    frame = null;
    if (textEl) renderInto(textEl, buffer);
    scrollDown();
  };
  const closeText = () => {
    if (frame) cancelAnimationFrame(frame);
    if (textEl) flush();
    textEl = null;
    buffer = "";
  };
  const setBusy = (label) => {
    busy?.remove();
    busy = label ? h("div", { class: "thinking" }, h("span", { class: "spinner" }), label) : null;
    if (busy) parts.append(busy);
    state.core?.setState(label ? "thinking" : "idle");
  };
  if (live) setBusy("Thinking");

  const turn = {
    root,
    endText: closeText,
    text(delta) {
      if (busy) setBusy(null);
      if (!textEl) {
        textEl = h("div", { class: "md" });
        parts.append(textEl);
      }
      buffer += delta;
      fullText += delta;
      if (!frame) frame = requestAnimationFrame(flush);
    },
    step(step) {
      closeText();
      let row = steps.get(step.id);
      if (!row) {
        row = stepRow(step);
        steps.set(step.id, row);
        setBusy(null);
        parts.append(row.root);
      }
      row.update(step);
      if (live && !["running", "awaiting_approval"].includes(step.status)) setBusy("Thinking");
      scrollDown();
    },
    ask(request) {
      steps.get(request.step_id)?.ask(request);
      scrollDown(true);
    },
    settle(event) {
      steps.get(event.step_id)?.settle(event);
    },
    status(text) {
      closeText();
      setBusy(text);
    },
    learned(change) {
      const memory = change.memory;
      const label = h("span", { text: `${change.action === "learned" ? "Learned" : "Updated memory"}: ${memory.content}` });
      const chip = h("div", { class: "learned" }, icon("sparkles"), label);
      if (change.action === "learned") {
        chip.append(
          h("button", { class: "btn ghost small", type: "button", text: "Undo", onClick: async (event) => {
            try {
              await api(`/memories/${memory.id}`, { method: "DELETE" });
              label.textContent = "Forgotten.";
              event.target.remove();
              state.ctx.refresh();
            } catch (error) {
              toast(error.message, "error");
            }
          } }),
        );
      }
      parts.append(chip);
      scrollDown();
    },
    finish(message) {
      closeText();
      setBusy(null);
      root.dataset.messageId = message?.id ?? "";
      const text = message?.content ?? fullText;
      const actions = h(
        "div",
        { class: "turn-actions" },
        iconButton("copy", "Copy", () => copyText(text).then(() => toast("Copied"))),
        iconButton("refresh-cw", "Try again", () => regenerate(root), "regen"),
        iconButton("graduation-cap", "Teach JARVIS how to handle this next time", () => teach(root)),
      );
      meta.replaceChildren(
        message?.model ? h("span", { text: shortModel(message.model), title: message.model }) : null,
        h("span", { text: fmtTime(message?.created_at || new Date().toISOString()) }),
        actions,
      );
      markLast();
    },
    fail(message) {
      closeText();
      setBusy(null);
      parts.append(h("div", { class: "error-box", text: message }));
      meta.replaceChildren(h("div", { class: "turn-actions" }, iconButton("refresh-cw", "Try again", () => regenerate(root), "regen")));
      markLast();
      scrollDown();
    },
  };
  return turn;
}

function renderStoredAssistant(message) {
  const turn = assistantTurn(false);
  const parts = message.parts?.length ? message.parts : [{ type: "text", text: message.content }];
  for (const part of parts) {
    if (part.type === "text") {
      turn.text(part.text);
      turn.endText();
    } else {
      turn.step(part);
    }
  }
  turn.finish(message);
  return turn;
}

function teach(turnRoot) {
  if (turnRoot.querySelector(".teach")) return;
  const input = h("input", { class: "input", placeholder: "e.g. Keep answers like this to two sentences", "aria-label": "How should JARVIS handle this next time?" });
  const form = h("form", { class: "teach" }, input, h("button", { class: "btn primary small", type: "submit", text: "Save instruction" }));
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!input.value.trim()) return;
    try {
      await api("/memories", { method: "POST", body: { content: input.value, kind: "style" } });
      form.replaceWith(h("div", { class: "learned" }, icon("sparkles"), h("span", { text: `Standing instruction saved: ${input.value.trim()}` })));
      state.ctx.refresh();
    } catch (error) {
      toast(error.message, "error");
    }
  });
  turnRoot.append(form);
  input.focus();
}

function regenerate(turnRoot) {
  if (state.streaming || !state.currentId) return;
  turnRoot.remove();
  send("", { regenerate: true });
}

// ---------- opening conversations ----------

export async function openConversation(id) {
  if (state.streaming) state.controller?.abort();
  openSidebar(false);
  try {
    const data = await api(`/conversations/${id}`);
    state.currentId = id;
    history.replaceState(null, "", `#/c/${id}`);
    setTitle(data.conversation.title);
    els.thread.replaceChildren();
    state.core = null;
    for (const message of data.messages) {
      els.thread.append(message.role === "user" ? userTurn(message) : renderStoredAssistant(message).root);
    }
    markLast();
    renderList();
    scrollDown(true);
  } catch (error) {
    if (error.status === 404) newConversation();
    else toast(error.message, "error");
  }
  if (!touch) els.input.focus();
}

export function newConversation() {
  if (state.streaming) state.controller?.abort();
  state.currentId = null;
  history.replaceState(null, "", "#/");
  setTitle("New conversation");
  renderWelcome();
  renderList();
  openSidebar(false);
  if (!touch) els.input.focus();
}

// ---------- sending ----------

function setStreaming(on) {
  state.streaming = on;
  els.send.classList.toggle("stop", on);
  els.send.setAttribute("aria-label", on ? "Stop" : "Send");
  updateSend();
}
function updateSend() {
  els.send.disabled = !state.streaming && !els.input.value.trim();
}
function autosize() {
  els.input.style.height = "auto";
  els.input.style.height = `${Math.min(els.input.scrollHeight, 220)}px`;
  updateSend();
}

let learningWatch = 0;

async function watchForLearning(turn) {
  // Learning runs in the background after the reply; look in on it briefly.
  // Only the newest reply watches, so what was learned is shown once, on the latest turn.
  const watch = ++learningWatch;
  for (const delay of [1200, 2500, 5000]) {
    await sleep(delay);
    if (watch !== learningWatch) return;
    try {
      const { changes, seq } = await api(`/memories/changes?after=${state.ctx.boot.change_seq}`);
      state.ctx.boot.change_seq = seq;
      const learned = changes.filter((c) => c.memory.source === "learned" && c.action !== "forgotten");
      if (learned.length) {
        learned.forEach((change) => turn.learned(change));
        state.ctx.refresh();
        return;
      }
    } catch {
      return;
    }
  }
}

async function send(text, { regenerate: again = false, editId = null } = {}) {
  text = text.trim();
  if (state.streaming || (!text && !again)) return;
  if (els.thread.querySelector(".welcome")) {
    els.thread.replaceChildren();
    state.core = null;
  }
  const asked = again ? null : userTurn({ content: text });
  if (asked) els.thread.append(asked);
  const turn = assistantTurn(true);
  els.thread.append(turn.root);
  markLast();
  scrollDown(true);
  els.input.value = "";
  autosize();

  const controller = new AbortController();
  state.controller = controller;
  setStreaming(true);
  let settled = false;
  let finished = false;
  try {
    const body = { conversation_id: state.currentId, message: text, model: preferredModel(), regenerate: again, edit_message_id: editId };
    for await (const event of streamChat(body, controller.signal)) {
      if (event.type === "conversation") {
        state.currentId = event.conversation.id;
        history.replaceState(null, "", `#/c/${state.currentId}`);
        setTitle(event.conversation.title);
        if (asked) asked.dataset.messageId = event.user_message_id ?? "";
        if (!state.conversations.some((c) => c.id === state.currentId)) state.conversations.unshift(event.conversation);
        renderList();
      } else if (event.type === "token") turn.text(event.text);
      else if (event.type === "tool_start" || event.type === "tool_end") turn.step(event.step);
      else if (event.type === "approval_required") turn.ask(event);
      else if (event.type === "approval_resolved") turn.settle(event);
      else if (event.type === "status") turn.status(event.text);
      else if (event.type === "done") {
        turn.finish(event.message);
        if (state.voiceReply && event.message && "speechSynthesis" in window) {
          window.speechSynthesis.cancel();
          const utterance = new SpeechSynthesisUtterance(event.message);
          utterance.addEventListener("end", () => { els.voiceStatus.textContent = ""; });
          window.speechSynthesis.speak(utterance);
        }
        settled = finished = true;
      } else if (event.type === "error") {
        turn.fail(event.message);
        settled = true;
      }
    }

    if (!settled) turn.fail("The connection closed before JARVIS finished replying.");
  } catch (error) {
    if (error.name === "AbortError") {
      turn.text("\n\n*[Stopped]*");
      turn.finish(null);
    } else {
      turn.fail(error.message);
    }
  } finally {
    state.controller = null;
    setStreaming(false);
    loadConversations();
    if (finished && state.ctx.boot.prefs.memory_enabled) watchForLearning(turn);
  }
}

async function toggleVoice() {
  if (state.recorder) {
    stopVoiceRecording("Processing recording...");
    return;
  }
  if ("speechSynthesis" in window && window.speechSynthesis.speaking) {
    window.speechSynthesis.cancel();
    state.voiceReply = false;
    els.voiceStatus.textContent = "";
    els.voice.setAttribute("title", "Record a voice message");
    return;
  }
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
    toast("Voice recording is not supported by this browser.", "error");
    return;
  }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const recorder = new MediaRecorder(stream);
    const chunks = [];
    state.recorder = recorder;
    state.voiceStream = stream;
    state.voiceReply = true;
    els.voice.classList.add("recording");
    els.voice.setAttribute("aria-label", "Stop recording and transcribe");
    els.voice.setAttribute("title", "Stop recording and transcribe");
    els.voiceStatus.textContent = "Listening...";
    recorder.addEventListener("dataavailable", (event) => { if (event.data.size) chunks.push(event.data); });
    recorder.addEventListener("stop", async () => {
      stream.getTracks().forEach((track) => track.stop());
      state.voiceStream = null;
      if (state.voiceContext) {
        state.voiceContext.close();
        state.voiceContext = null;
      }
      cancelAnimationFrame(state.voiceFrame);
      clearTimeout(state.voiceTimer);
      state.recorder = null;
      els.voice.classList.remove("recording");
      els.voice.setAttribute("aria-label", "Record a voice message");
      els.voice.setAttribute("title", "Record a voice message");
      try {
        const blob = new Blob(chunks, { type: recorder.mimeType || "audio/webm" });
        if (!blob.size) throw new Error("The recording was empty.");
        els.voiceStatus.textContent = "Transcribing...";
        const data = await api("/transcribe", {
          method: "POST",
          body: blob,
          headers: { "Content-Type": blob.type, "X-Jarvis-Filename": "recording.webm" },
        });
        els.input.value = data.text;
        autosize();
        els.voiceStatus.textContent = "Speaking reply...";
        els.composer.requestSubmit();
      } catch (error) {
        state.voiceReply = false;
        els.voiceStatus.textContent = "";
        toast(error.message, "error");
      }
    });
    recorder.start();
    state.voiceTimer = setTimeout(() => stopVoiceRecording("Processing recording..."), 120000);
    monitorVoiceSilence(stream);
  } catch (error) {
    state.recorder = null;
    state.voiceReply = false;
    els.voiceStatus.textContent = "";
    toast(error.name === "NotAllowedError" ? "Microphone access was denied." : error.message, "error");
  }
}

function stopVoiceRecording(status = "") {
  if (!state.recorder) return;
  els.voiceStatus.textContent = status;
  state.recorder.stop();
}

function monitorVoiceSilence(stream) {
  if (!window.AudioContext && !window.webkitAudioContext) return;
  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  const context = new AudioContextClass();
  const analyser = context.createAnalyser();
  analyser.fftSize = 512;
  const source = context.createMediaStreamSource(stream);
  source.connect(analyser);
  state.voiceContext = context;
  const samples = new Uint8Array(analyser.fftSize);
  const started = performance.now();
  let quietSince = 0;
  const check = () => {
    if (!state.recorder) return;
    analyser.getByteTimeDomainData(samples);
    let total = 0;
    for (const sample of samples) {
      const value = (sample - 128) / 128;
      total += value * value;
    }
    const loud = Math.sqrt(total / samples.length) > 0.025;
    const now = performance.now();
    if (loud) quietSince = 0;
    else if (now - started > 900 && !quietSince) quietSince = now;
    if (quietSince && now - quietSince > 2500) {
      stopVoiceRecording("Silence detected...");
      return;
    }
    state.voiceFrame = requestAnimationFrame(check);
  };
  state.voiceFrame = requestAnimationFrame(check);
}

// ---------- wiring ----------

function renderModelSelect() {
  const ready = state.ctx.boot.models.ready;
  let saved = "";
  try {
    saved = localStorage.getItem("jarvis.model") || "";
  } catch { /* storage unavailable */ }
  els.modelSelect.replaceChildren(h("option", { value: "", text: "Automatic" }), ...ready.map((label) => h("option", { value: label, text: shortModel(label) })));
  els.modelSelect.value = ready.includes(saved) ? saved : "";
  els.modelSelect.hidden = ready.length < 2;
}

function startRename() {
  if (!state.currentId || els.title.hidden) return;
  const input = h("input", { class: "input title-input", value: els.title.textContent, maxLength: 200, "aria-label": "Conversation title" });
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
    if (!save || !value || value === els.title.textContent) return;
    try {
      const updated = await api(`/conversations/${state.currentId}`, { method: "PATCH", body: { title: value } });
      setTitle(updated.title);
      loadConversations();
    } catch (error) {
      toast(error.message, "error");
    }
  };
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") finish(true);
    if (event.key === "Escape") finish(false);
  });
  input.addEventListener("blur", () => finish(true));
}

async function exportConversation() {
  try {
    const text = await api(`/conversations/${state.currentId}/export`);
    const link = h("a", { href: URL.createObjectURL(new Blob([text], { type: "text/markdown" })), download: `${els.title.textContent.replace(/[\\/:*?"<>|]/g, " ").trim() || "conversation"}.md` });
    link.click();
    URL.revokeObjectURL(link.href);
  } catch (error) {
    toast(error.message, "error");
  }
}

/** Called when settings or keys change elsewhere in the app. */
export function bootChanged() {
  renderModelSelect();
  if (els.thread.querySelector(".welcome") && !state.streaming) renderWelcome();
}

export function initChat(ctx) {
  state.ctx = ctx;
  renderModelSelect();
  enableCodeCopy(els.thread);
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
    else send(els.input.value);
  });
  els.newChat.addEventListener("click", newConversation);
  els.menuBtn.addEventListener("click", () => openSidebar(true));
  els.scrim.addEventListener("click", () => openSidebar(false));
  els.title.addEventListener("click", startRename);
  els.exportBtn.addEventListener("click", exportConversation);
  els.voice.addEventListener("click", toggleVoice);
  els.search.addEventListener("input", debounce(loadConversations, 250));
  els.modelSelect.addEventListener("change", () => {
    try {
      localStorage.setItem("jarvis.model", els.modelSelect.value);
    } catch { /* storage unavailable */ }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && state.streaming) state.controller?.abort();
    const typing = ["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement?.tagName);
    if (event.key === "/" && !typing && !document.getElementById("viewChat").hidden) {
      event.preventDefault();
      els.input.focus();
    }
  });
  updateSend();
  return loadConversations();
}

export const currentConversation = () => state.currentId;
