// The Settings screen: system status, personality, models, permissions and data.

import { api } from "./api.js";
import { confirmDialog, debounce, fmtBytes, h, icon, iconButton, plural, row, section, segmented, toast, toggle } from "./util.js";

const PERSONA = {
  formality: ["Manner", { butler: ["Butler", "Formal, measured diction."], balanced: ["Balanced", "Professional without stiffness."], casual: ["Casual", "Relaxed, like a trusted colleague."] }],
  wit: ["Humour", { off: ["Off", "Strictly businesslike."], subtle: ["Subtle", "An occasional dry remark."], playful: ["Playful", "Dry humour in most casual replies."] }],
  detail: ["Answer length", { brief: ["Brief", "As short as accuracy allows."], balanced: ["Balanced", "Short for simple things, thorough when needed."], thorough: ["Thorough", "Reasoning, context and examples by default."] }],
};
const PROVIDERS = { groq: "Groq", gemini: "Google Gemini", openrouter: "OpenRouter", ollama: "Ollama (this computer)", fake: "Demo (not an AI)" };
const RISK = { read: "Only looks things up", act: "A small, visible action", sensitive: "Hard to undo. Always asks first" };

export async function renderSettings(page, ctx) {
  const save = async (patch, quiet = false) => {
    try {
      ctx.boot.prefs = await api("/settings", { method: "PATCH", body: patch });
      await ctx.refresh();
      if (!quiet) toast("Saved");
      return true;
    } catch (error) {
      toast(error.message, "error");
      return false;
    }
  };
  const rerender = () => renderSettings(page, ctx);
  const prefs = ctx.boot.prefs;
  let status;
  let tools;
  try {
    [status, tools] = await Promise.all([api("/status"), api("/tools")]);
  } catch (error) {
    page.replaceChildren(h("header", { class: "page-head" }, h("h1", { text: "Settings" }), h("p", { text: error.message })));
    return;
  }

  // ----- status -----
  const results = h("div", { class: "result-list" });
  const testButton = h("button", { class: "btn", type: "button", text: "Test models now" });
  testButton.addEventListener("click", async () => {
    testButton.disabled = true;
    testButton.textContent = "Testing";
    try {
      const outcome = await api("/models/check", { method: "POST" });
      results.replaceChildren(
        ...outcome.map((item) => h("div", {}, h("span", { class: `badge ${item.ok ? "ok" : "error"}`, text: item.ok ? `Working, ${item.seconds} s` : "Failed" }), h("span", {}, h("code", { text: item.model }), item.ok ? "" : ` ${item.detail}`))),
      );
    } catch (error) {
      toast(error.message, "error");
    }
    testButton.disabled = false;
    testButton.textContent = "Test models now";
  });
  const modelStatus = status.models.map((model) => {
    const usage = model.usage ? `Today: ${plural(model.usage.requests, "request")}, ${(model.usage.prompt_tokens + model.usage.completion_tokens).toLocaleString()} tokens` : "Not used today";
    const left = model.rate?.remaining_requests != null ? `. Left today: ${model.rate.remaining_requests.toLocaleString()} requests` : "";
    return h(
      "div",
      { class: "model-row" },
      h("span", { class: "model-name" }, model.model, h("span", { class: "model-sub", text: usage + left })),
      model.resting_seconds ? h("span", { class: "badge warn", text: `Resting ${model.resting_seconds} s (rate limit)` }) : h("span", { class: "badge ok", text: "Ready" }),
    );
  });
  const statusSection = section(
    "System status",
    status.models.length ? "" : "No model is ready, so JARVIS can't reply yet. Add a key under Models below.",
    h("div", { class: "model-list" }, ...modelStatus, ...status.skipped.map((reason) => h("div", { class: "model-row" }, h("span", { class: "model-name", text: reason }), h("span", { class: "badge error", text: "Not ready" })))),
    h("div", { class: "inline-form" }, testButton),
    results,
    h(
      "dl",
      { class: "kv" },
      h("dt", { text: "Stored here" }), h("dd", { text: `${plural(status.database.conversations, "conversation")}, ${plural(status.database.memories, "memory", "memories")}, ${plural(status.database.tool_runs, "logged action")} (${fmtBytes(status.database.bytes)})` }),
      h("dt", { text: "Database file" }), h("dd", { text: status.database.path }),
      h("dt", { text: "Search index" }), h("dd", { text: status.database.search_index ? "On" : "Unavailable; using slower plain search" }),
      h("dt", { text: "Opening apps" }), h("dd", { text: `Through the ${status.apps.backend}` }),
      h("dt", { text: "Reachable from" }), h("dd", { text: status.local_only ? "This computer only" : "Other devices on your network" }),
      h("dt", { text: "Version" }), h("dd", { text: status.version }),
    ),
  );

  // ----- personality -----
  const textSetting = (key, placeholder) => {
    const input = h("input", { class: "input", value: prefs[key], placeholder });
    input.addEventListener("change", () => save({ [key]: input.value }));
    return input;
  };
  const dial = (key) => {
    const [label, options] = PERSONA[key];
    const note = h("span", { text: options[prefs.persona[key]][1] });
    const control = segmented(Object.entries(options).map(([value, [text]]) => [value, text]), prefs.persona[key], (value) => {
      note.textContent = options[value][1];
      save({ persona: { [key]: value } }, true);
    }, label);
    return h("div", { class: "row" }, h("div", { class: "row-text" }, h("strong", { text: label }), note), h("div", { class: "row-control" }, control));
  };
  const instructions = h("textarea", { class: "textarea", rows: 3, value: prefs.custom_instructions, placeholder: "Anything else JARVIS should always do, in your own words." });
  instructions.addEventListener("change", () => save({ custom_instructions: instructions.value }));
  const personality = section(
    "Personality",
    "How JARVIS sounds. Changes apply from the next message. Things you teach it in conversation are kept as standing instructions in Memory.",
    h(
      "div",
      { class: "rows" },
      row("Your name", "So JARVIS knows who it works for.", textSetting("user_name", "Your first name")),
      row("How JARVIS addresses you", "Used now and then, not in every sentence. Leave empty for none.", textSetting("user_title", "sir")),
      dial("formality"),
      dial("wit"),
      dial("detail"),
      h("div", { class: "row stack" }, h("div", { class: "row-text" }, h("strong", { text: "Your own instructions" }), h("span", { text: "Followed in every reply, ahead of the defaults." })), h("div", { class: "row-control" }, instructions)),
    ),
  );

  // ----- models -----
  const keys = ctx.boot.models.keys;
  const keyRow = (provider, description) => {
    const input = h("input", { class: "input", type: "password", placeholder: keys[provider].set ? `Connected (key ending ${keys[provider].hint.slice(1)})` : "Paste key", autocomplete: "off", "aria-label": `${PROVIDERS[provider]} key` });
    const connect = h("button", { class: "btn", type: "button", text: keys[provider].set ? "Replace" : "Connect" });
    connect.addEventListener("click", async () => {
      if (!input.value.trim()) return input.focus();
      connect.disabled = true;
      try {
        const result = await api("/keys", { method: "POST", body: { provider, key: input.value } });
        await ctx.refresh();
        toast(result.warning || `${PROVIDERS[provider]} connected`);
        rerender();
      } catch (error) {
        toast(error.message, "error");
        connect.disabled = false;
      }
    });
    const remove = keys[provider].set
      ? iconButton("trash-2", `Remove the ${PROVIDERS[provider]} key`, async () => {
          if (!(await confirmDialog({ title: `Remove the ${PROVIDERS[provider]} key?`, body: "Its models will stop working until you add a key again.", confirm: "Remove", danger: true }))) return;
          await api(`/keys/${provider}`, { method: "DELETE" });
          await ctx.refresh();
          rerender();
        })
      : null;
    return row(`${PROVIDERS[provider]} key`, description, input, connect, remove);
  };
  const models = prefs.models;
  const move = (index, delta) => {
    const next = [...models];
    const [item] = next.splice(index, 1);
    next.splice(index + delta, 0, item);
    save({ models: next }, true).then(rerender);
  };
  const modelRows = models.map((label, index) =>
    h(
      "div",
      { class: "model-row" },
      h("span", { class: "order", text: `${index + 1}` }),
      h("span", { class: "model-name" }, label, h("span", { class: "model-sub", text: index === 0 ? "Used first" : "Used if the ones above are busy or fail" })),
      iconButton("chevron-down", "Move up", () => move(index, -1), index === 0 ? "ghosted flip" : "flip"),
      iconButton("chevron-down", "Move down", () => move(index, 1), index === models.length - 1 ? "ghosted" : ""),
      models.length > 1 ? iconButton("x", `Remove ${label}`, () => save({ models: models.filter((_, i) => i !== index) }, true).then(rerender)) : null,
    ),
  );
  const providerSelect = h("select", { class: "select", "aria-label": "Provider" }, ...Object.entries(PROVIDERS).map(([value, text]) => h("option", { value, text })));
  const modelInput = h("input", { class: "input", placeholder: "Model name", list: "modelOptions", "aria-label": "Model name" });
  const modelOptions = h("datalist", { id: "modelOptions" });
  const loadOptions = async () => {
    modelOptions.replaceChildren();
    try {
      const data = await api(`/models/available?provider=${providerSelect.value}`);
      modelOptions.replaceChildren(...data.models.filter((name) => !/whisper|guard|orpheus|tts/i.test(name)).map((name) => h("option", { value: name })));
      modelInput.placeholder = data.models.length ? "Choose or type a model name" : "Model name";
    } catch {
      modelInput.placeholder = "Type a model name (add this provider's key to see its list)";
    }
  };
  providerSelect.addEventListener("change", loadOptions);
  loadOptions();
  const addModel = h("button", { class: "btn", type: "button", text: "Add model", onClick: () => {
    if (!modelInput.value.trim()) return modelInput.focus();
    save({ models: [...models, `${providerSelect.value}:${modelInput.value.trim()}`] }, true).then((ok) => ok && rerender());
  } });
  const limitInput = h("input", { class: "input", type: "number", min: 0, max: 100000, value: prefs.daily_request_limit, style: "width: 110px" });
  limitInput.addEventListener("change", () => save({ daily_request_limit: Number(limitInput.value) || 0 }));
  const modelsSection = section(
    "Models",
    "JARVIS tries these in order and moves down the list when one is busy or rate-limited. On Groq each model has its own free allowance, so a second model is extra capacity.",
    h("div", { class: "rows" }, keyRow("groq", "Free tier, no payment details needed. Get one at console.groq.com/keys.")),
    h("div", { class: "model-list" }, ...modelRows),
    h("div", { class: "inline-form" }, providerSelect, modelInput, modelOptions, addModel),
    h(
      "div",
      { class: "rows" },
      row("Thinking effort", "How long reasoning models think before answering. Higher is slower and uses more of the free allowance.", segmented([["low", "Low"], ["medium", "Medium"], ["high", "High"]], prefs.reasoning_effort || "low", (value) => save({ reasoning_effort: value }, true), "Thinking effort")),
      row("Daily request cap", "JARVIS stops calling models after this many requests in a day. 0 means no cap.", limitInput),
      keyRow("gemini", "Optional fallback. Google may use free-tier prompts to improve its products."),
      keyRow("openrouter", "Optional fallback. Free models are limited to a small number of requests a day."),
    ),
  );

  // ----- permissions -----
  const stepInput = h("input", { class: "input", type: "number", min: 1, max: 15, value: prefs.max_steps, style: "width: 90px" });
  stepInput.addEventListener("change", () => save({ max_steps: Number(stepInput.value) || 8 }));
  const toolRows = tools.map((tool) => {
    const select = h(
      "select",
      { class: "select", "aria-label": `Permission for ${tool.label}` },
      tool.locked ? null : h("option", { value: "allow", text: "Allowed" }),
      h("option", { value: "ask", text: "Ask me first" }),
      h("option", { value: "off", text: "Off" }),
    );
    select.value = tool.policy;
    select.addEventListener("change", () => save({ tool_policy: { [tool.name]: select.value } }, true));
    return row(tool.label, `${tool.group}. ${RISK[tool.risk]}.`, select);
  });
  const permissions = section(
    "Actions and permissions",
    "What JARVIS may do on its own. Anything set to ask shows an approval request in the conversation before it runs. Every action is recorded under Activity.",
    h(
      "div",
      { class: "rows" },
      row("Ask before every action", "JARVIS requests your OK for anything that isn't just looking something up.", toggle(prefs.ask_every_action, (value) => save({ ask_every_action: value }, true), "Ask before every action")),
      row("Step limit", "The most tool steps JARVIS may take for one message before it must stop and report.", stepInput),
      ...toolRows,
    ),
  );

  // ----- data -----
  const data = section(
    "Your data",
    "Conversations, memories and the action log live in one database file on this computer. Messages, and the memories relevant to them, are sent to the AI model you've chosen so it can answer.",
    h(
      "div",
      { class: "rows" },
      row("Delete all conversations", "Memories are kept.", h("button", { class: "btn danger", type: "button", text: "Delete conversations", onClick: async () => {
        if (!(await confirmDialog({ title: "Delete all conversations?", body: "Every conversation will be removed. This can't be undone.", confirm: "Delete all", danger: true }))) return;
        const { deleted } = await api("/conversations", { method: "DELETE" });
        toast(`${plural(deleted, "conversation")} deleted`);
        await ctx.refresh();
        ctx.conversationsChanged();
        rerender();
      } })),
      row("Shut down JARVIS", "Stops the program. Start it again with start.bat.", h("button", { class: "btn", type: "button", onClick: async () => {
        if (!(await confirmDialog({ title: "Shut down JARVIS?", body: "This window will stop working until you start JARVIS again.", confirm: "Shut down" }))) return;
        await api("/shutdown", { method: "POST" });
        document.body.replaceChildren(h("div", { class: "page" }, h("header", { class: "page-head" }, h("h1", { text: "JARVIS has shut down" }), h("p", { text: "You can close this window. Run start.bat to bring it back." }))));
      } }, icon("power"), "Shut down")),
    ),
  );

  page.replaceChildren(h("header", { class: "page-head" }, h("h1", { text: "Settings" })), statusSection, personality, modelsSection, permissions, data);
}
