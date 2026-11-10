// The Memory and Activity screens.

import { api } from "./api.js";
import { confirmDialog, dayLabel, debounce, fmtDate, fmtDuration, fmtTime, h, icon, iconButton, plural, row, section, toast, toggle } from "./util.js";

export const KINDS = {
  style: ["Standing instructions", "How JARVIS should behave. Followed in every reply."],
  preference: ["Preferences", "Likes, dislikes and how you want things done."],
  personal: ["About you", "Facts about you and the people in your life."],
  project: ["Projects", "Ongoing work, goals and deadlines."],
  note: ["Notes", "Anything else worth keeping."],
};
const SOURCES = { told: "You told JARVIS", learned: "Learned from a conversation", user: "Added by you" };

function download(name, text, type) {
  const link = h("a", { href: URL.createObjectURL(new Blob([text], { type })), download: name });
  link.click();
  URL.revokeObjectURL(link.href);
}

function kindSelect(value) {
  return h("select", { class: "select", "aria-label": "Kind of memory" }, ...Object.entries(KINDS).map(([key, [label]]) => h("option", { value: key, text: label, selected: key === value })));
}

// ---------- Memory ----------

export async function renderMemory(page, ctx) {
  let query = "";
  let filter = "";
  const summary = h("p");
  const list = h("div");
  const chips = h("div", { class: "chips" });
  const searchInput = h("input", { type: "search", placeholder: "Search memory", "aria-label": "Search memory" });
  const form = h("div", { hidden: true });

  function memoryForm(memory, onDone) {
    const content = h("textarea", { class: "textarea", rows: 2, value: memory?.content || "", placeholder: "One fact per memory, e.g. Prefers worked solutions shown step by step.", "aria-label": "Memory" });
    const kind = kindSelect(memory?.kind || (filter || "preference"));
    const problem = h("span", { class: "memory-meta" });
    const save = h("button", { class: "btn primary small", type: "button", text: memory ? "Save" : "Add memory" });
    save.addEventListener("click", async () => {
      try {
        if (memory) await api(`/memories/${memory.id}`, { method: "PATCH", body: { content: content.value, kind: kind.value } });
        else await api("/memories", { method: "POST", body: { content: content.value, kind: kind.value } });
        onDone(true);
      } catch (error) {
        problem.textContent = error.message;
        problem.style.color = "var(--red)";
      }
    });
    const box = h("div", { class: "memory-form" }, content, h("div", { class: "form-actions" }, kind, save, h("button", { class: "btn small", type: "button", text: "Cancel", onClick: () => onDone(false) }), problem));
    setTimeout(() => content.focus());
    return box;
  }

  function memoryRow(memory) {
    const main = h("div", { class: "memory-main" });
    const item = h("div", { class: `memory${memory.pinned ? " pinned" : ""}` }, main);
    const used = memory.use_count ? `, looked up ${plural(memory.use_count, "time")}` : "";
    const show = () =>
      main.replaceChildren(
        h("div", { class: "memory-content", text: memory.content }),
        h("div", { class: "memory-meta", text: `${SOURCES[memory.source] || memory.source}, ${fmtDate(memory.updated_at)}${used}` }),
      );
    show();
    item.append(
      h(
        "div",
        { class: "memory-actions" },
        iconButton(memory.pinned ? "pin-off" : "pin", memory.pinned ? "Unpin" : "Pin: always include this", async () => {
          await api(`/memories/${memory.id}`, { method: "PATCH", body: { pinned: !memory.pinned } });
          load();
        }, memory.pinned ? "on" : ""),
        iconButton("pencil", "Edit", () => main.replaceChildren(memoryForm(memory, (saved) => (saved ? load() : show())))),
        iconButton("trash-2", "Forget this", async () => {
          if (!(await confirmDialog({ title: "Forget this memory?", body: memory.content, confirm: "Forget", danger: true }))) return;
          await api(`/memories/${memory.id}`, { method: "DELETE" });
          toast("Forgotten");
          load();
        }),
      ),
    );
    return item;
  }

  async function load() {
    let data;
    try {
      data = await api(`/memories${query ? `?q=${encodeURIComponent(query)}` : ""}`);
    } catch (error) {
      list.replaceChildren(h("div", { class: "empty", text: error.message }));
      return;
    }
    ctx.boot.memory_count = data.total;
    summary.textContent = data.total
      ? `JARVIS knows ${plural(data.total, "thing")} about you. They shape every reply and are stored only on this computer.`
      : "Nothing is stored yet. JARVIS learns as you talk, and you can add things here yourself.";
    const counts = Object.fromEntries(Object.keys(KINDS).map((kind) => [kind, data.memories.filter((m) => m.kind === kind).length]));
    chips.replaceChildren(
      h("button", { class: "chip", type: "button", text: "All", "aria-pressed": String(!filter), onClick: () => { filter = ""; load(); } }),
      ...Object.entries(KINDS).map(([kind, [label]]) =>
        h("button", { class: "chip", type: "button", text: `${label} ${counts[kind] || ""}`.trim(), "aria-pressed": String(filter === kind), onClick: () => { filter = kind; load(); } }),
      ),
    );
    const shown = data.memories.filter((memory) => !filter || memory.kind === filter);
    if (!shown.length) {
      list.replaceChildren(h("div", { class: "empty", text: query || filter ? "No memories match that." : "Tell JARVIS something about yourself in a conversation, or add a memory above." }));
      return;
    }
    list.replaceChildren(
      ...Object.entries(KINDS)
        .filter(([kind]) => shown.some((m) => m.kind === kind))
        .map(([kind, [label, note]]) =>
          h("div", { class: "memory-group" }, h("h2", { text: label }), h("p", { class: "group-note", text: note }), ...shown.filter((m) => m.kind === kind).map(memoryRow)),
        ),
    );
  }

  searchInput.addEventListener("input", debounce(() => { query = searchInput.value.trim(); load(); }, 200));
  const prefs = ctx.boot.prefs;
  const save = async (patch) => {
    try {
      ctx.boot.prefs = await api("/settings", { method: "PATCH", body: patch });
      ctx.refresh();
    } catch (error) {
      toast(error.message, "error");
    }
  };

  page.replaceChildren(
    h("header", { class: "page-head" }, h("h1", { text: "Memory" }), summary),
    h(
      "div",
      { class: "toolbar" },
      h("label", { class: "search" }, icon("search"), searchInput),
      h("button", { class: "btn primary", type: "button", onClick: () => {
        form.hidden = false;
        form.replaceChildren(memoryForm(null, (saved) => { form.hidden = true; if (saved) { toast("Added to memory"); load(); } }));
      } }, icon("plus"), "Add a memory"),
      h("button", { class: "btn", type: "button", onClick: async () => download("jarvis-memory.json", JSON.stringify(await api("/memories/export"), null, 2), "application/json") }, icon("download"), "Export"),
    ),
    form,
    chips,
    list,
    section(
      "How memory works",
      "Memories are kept in a database file on this computer. The ones relevant to a message are sent to the AI model along with it, which is how JARVIS uses them.",
      h(
        "div",
        { class: "rows" },
        row("Use memory", "When off, JARVIS neither reads nor writes memories.", toggle(prefs.memory_enabled, (value) => save({ memory_enabled: value }), "Use memory")),
        row("Learn automatically", "After each exchange, JARVIS notes anything lasting you said about yourself. You'll see what it learned and can undo it.", toggle(prefs.auto_learn, (value) => save({ auto_learn: value }), "Learn automatically")),
        row("Forget everything", "Deletes every memory. Conversations are kept.", h("button", { class: "btn danger", type: "button", text: "Forget everything", onClick: async () => {
          if (!(await confirmDialog({ title: "Forget everything?", body: "Every memory will be deleted. This can't be undone. Export first if you want a copy.", confirm: "Forget everything", danger: true }))) return;
          const { deleted } = await api("/memories", { method: "DELETE" });
          toast(`${plural(deleted, "memory", "memories")} forgotten`);
          load();
        } })),
      ),
    ),
  );
  await load();
}

// ---------- Activity ----------

const FILTERS = [
  ["", "Everything", () => true],
  ["approval", "Needed your OK", (run) => run.decision !== "auto"],
  ["failed", "Failed", (run) => run.status === "error"],
  ["learning", "Learning", (run) => run.tool === "memory.learn" || run.tool === "remember" || run.tool === "forget"],
];
const DECISIONS = { approved: "Approved by you", denied: "Declined by you", expired: "Approval expired" };
const RUN_ICON = { ok: "check", error: "circle-alert", denied: "ban", cancelled: "ban" };

export async function renderActivity(page, ctx) {
  let filter = "";
  const chips = h("div", { class: "chips" });
  const waiting = h("div");
  const list = h("div", { class: "log" });

  async function load() {
    let data;
    try {
      data = await api("/activity");
    } catch (error) {
      list.replaceChildren(h("div", { class: "empty", text: error.message }));
      return;
    }
    chips.replaceChildren(
      ...FILTERS.map(([key, label]) => h("button", { class: "chip", type: "button", text: label, "aria-pressed": String(filter === key), onClick: () => { filter = key; load(); } })),
    );
    waiting.replaceChildren(
      ...data.pending.map((item) =>
        h("div", { class: "approval", style: "margin: 16px 0 0" }, h("h3", { text: `Waiting for your OK: ${item.title}` }), h("p", {}, item.reason, " ", h("button", { class: "linklike", type: "button", text: "Open the conversation", onClick: () => ctx.openConversation(item.conversation_id) }))),
      ),
    );
    const test = FILTERS.find(([key]) => key === filter)[2];
    const runs = data.runs.filter(test);
    if (!runs.length) {
      list.replaceChildren(h("div", { class: "empty", text: filter ? "Nothing matches that filter." : "No actions yet. When JARVIS opens an app, saves a memory or learns something, it is recorded here." }));
      return;
    }
    const nodes = [];
    let day = null;
    for (const run of runs) {
      const label = dayLabel(run.started_at);
      if (label !== day) {
        nodes.push(h("div", { class: "log-day", text: label }));
        day = label;
      }
      const outcome = (run.summary || "").replace(/\.+$/, "");
      const decision = DECISIONS[run.decision];
      const details = [outcome, decision && decision !== outcome ? decision : "", fmtDuration(run.duration_ms)].filter(Boolean).join(". ");
      nodes.push(
        h(
          "div",
          { class: "log-item", "data-status": run.status },
          h("span", { class: "step-state" }, icon(RUN_ICON[run.status] || "circle-alert")),
          h(
            "div",
            { class: "log-main" },
            h("div", { text: run.title }),
            h("div", { class: "log-sub" }, details, details && run.conversation_title ? ". " : "", run.conversation_title ? h("button", { class: "linklike", type: "button", text: run.conversation_title, onClick: () => ctx.openConversation(run.conversation_id) }) : null),
          ),
          h("span", { class: "log-time", text: fmtTime(run.started_at) }),
        ),
      );
    }
    list.replaceChildren(...nodes);
  }

  page.replaceChildren(
    h("header", { class: "page-head" }, h("h1", { text: "Activity" }), h("p", { text: "Every action JARVIS has taken, and everything it has learned, with the real outcome of each. Nothing is listed here unless it actually ran." })),
    chips,
    waiting,
    list,
  );
  await load();
  const timer = setInterval(() => (page.isConnected && !page.hidden ? load() : null), 5000);
  return () => clearInterval(timer);
}
