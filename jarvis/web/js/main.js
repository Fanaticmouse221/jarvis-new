// Entry point: loads start-up data, switches between screens, keeps the status light honest.

import { api } from "./api.js";
import { bootChanged, initChat, loadConversations, newConversation, openConversation } from "./chat.js";
import { renderActivity, renderMemory } from "./pages.js";
import { renderSettings } from "./settings.js";
import { h } from "./util.js";

const app = document.getElementById("app");
const viewChat = document.getElementById("viewChat");
const viewPage = document.getElementById("viewPage");
const railStatus = document.getElementById("railStatus");
const PAGES = { memory: renderMemory, activity: renderActivity, settings: renderSettings };

const ctx = {
  boot: null,
  /** Re-read start-up data after something changed (keys, models, memory count). */
  async refresh() {
    try {
      const fresh = await api("/bootstrap");
      const seq = ctx.boot?.change_seq;
      ctx.boot = fresh;
      if (seq != null) ctx.boot.change_seq = Math.min(seq, fresh.change_seq);
      setStatus(fresh.models.ready.length ? "ok" : "warn", fresh.models.ready.length ? `Online. Using ${fresh.models.ready[0]}` : "No model is ready. Open Settings to connect one.");
      bootChanged();
    } catch (error) {
      setStatus("error", error.message);
    }
  },
  openConversation(id) {
    location.hash = `#/c/${id}`;
  },
  conversationsChanged: () => loadConversations(),
};

function setStatus(kind, text) {
  railStatus.firstElementChild.className = `dot ${kind}`;
  railStatus.title = text;
  railStatus.setAttribute("aria-label", `Status: ${text}`);
}

let cleanup = null;
let shownChat = null; // the conversation id currently shown ("" for a new one), or null when on another screen

async function route() {
  const [, section = "", id = ""] = location.hash.replace(/^#/, "").split("/");
  const view = PAGES[section] ? section : "chat";
  app.dataset.view = view;
  for (const item of document.querySelectorAll(".rail-item")) item.classList.toggle("active", item.dataset.nav === view);
  if (typeof cleanup === "function") cleanup();
  cleanup = null;

  if (view === "chat") {
    viewPage.hidden = true;
    viewChat.hidden = false;
    const wanted = section === "c" ? id : "";
    if (shownChat !== wanted) {
      shownChat = wanted;
      if (wanted) await openConversation(wanted);
      else newConversation();
    }
    return;
  }
  shownChat = null;
  viewChat.hidden = true;
  viewPage.hidden = false;
  const page = h("div", { class: "page" });
  viewPage.replaceChildren(page);
  viewPage.scrollTop = 0;
  cleanup = await PAGES[view](page, ctx);
}

async function start() {
  try {
    ctx.boot = await api("/bootstrap");
  } catch (error) {
    document.getElementById("thread").replaceChildren(h("div", { class: "error-box", text: `JARVIS couldn't start: ${error.message}` }));
    setStatus("error", error.message);
    return;
  }
  setStatus(ctx.boot.models.ready.length ? "ok" : "warn", ctx.boot.models.ready.length ? `Online. Using ${ctx.boot.models.ready[0]}` : "No model is ready. Open Settings to connect one.");
  await initChat(ctx);
  window.addEventListener("hashchange", route);
  await route();
  setInterval(() => ctx.refresh(), 60000);
}

start();
