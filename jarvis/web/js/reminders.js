import { api } from "./api.js";
import { h, iconButton, section, toast } from "./util.js";

export function remindersSection() {
  const list = h("div", { class: "rows", text: "Loading reminders…" });
  const box = section("Reminders", "Ask JARVIS: “Remind me in 10 minutes to stretch.” Your PC must be on; missed reminders arrive when JARVIS starts again.", list);
  async function refresh() {
    try {
      const reminders = await api("/reminders");
      list.replaceChildren(...reminders.map(item => h("div", { class: "row" },
        h("div", { class: "row-text" }, h("strong", { text: item.text }), h("span", { text: `${item.due_local}${item.repeat !== "none" ? ` · ${item.repeat}` : ""}` })),
        h("button", { class: "btn", type: "button", text: "Cancel", "aria-label": `Cancel reminder ${item.id}`, onClick: async () => {
          try { await api(`/reminders/${item.id}`, { method: "DELETE" }); await refresh(); }
          catch (error) { toast(error.message, "error"); }
        } }))));
      if (!reminders.length) list.append(h("p", { class: "hint", text: "No pending reminders." }));
    } catch (error) { list.textContent = error.message; }
  }
  refresh();
  const timer = setInterval(() => { if (box.isConnected) refresh(); else clearInterval(timer); }, 15000);
  return box;
}

export function startReminderNotices() {
  const box = h("div", { class: "reminder-notices", "aria-live": "polite" });
  document.body.append(box);
  const key = `jarvis-notices:${location.origin}`;
  let after = 0;
  try { after = Math.max(0, Number(localStorage.getItem(key)) || 0); } catch {}
  let loading = false;
  async function poll() {
    if (loading) return;
    loading = true;
    try {
      const data = await api(`/notices?after=${after}`);
      if (after > data.seq) after = 0; // a fresh database can reuse the same address
      else {
        for (const item of data.notices.slice(-10)) {
          const banner = h("div", { class: "reminder-banner" }, h("span", { text: item.message }));
          banner.append(iconButton("x", "Dismiss reminder", () => banner.remove()));
          box.append(banner);
          while (box.children.length > 10) box.firstElementChild.remove();
        }
        after = data.seq;
      }
      try { localStorage.setItem(key, String(after)); } catch {}
    } catch { /* The regular status light reports server disconnection. */ }
    finally { loading = false; }
  }
  poll();
  setInterval(poll, 5000);
}
