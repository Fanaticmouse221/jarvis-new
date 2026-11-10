// Phone setup uses only the protected local API. Bot credentials never return to the page.
import { api } from "./api.js";
import { confirmDialog, h, row, section, toast } from "./util.js";

export function phoneSection() {
  const state = h("div", { class: "phone-state", role: "status", text: "Checking phone connection…" });
  const input = h("input", { class: "input", type: "password", autocomplete: "off", "aria-label": "Telegram bot token", placeholder: "Paste the token from BotFather" });
  const connect = h("button", { class: "btn", type: "button", text: "Connect bot" });
  const actions = h("div", { class: "inline-form" });
  const box = section("Phone", "Message the same JARVIS, with its memories and personality, from Telegram.",
    h("ol", {},
      h("li", {}, "Install Telegram on your phone."),
      h("li", {}, "Open ", h("a", { href: "https://t.me/BotFather", target: "_blank", rel: "noopener noreferrer", text: "@BotFather" }), " and send /newbot. Follow its steps."),
      h("li", {}, "Paste the bot token here and connect."),
      h("li", {}, "Open your new bot in Telegram and send the pairing code shown below.")),
    h("p", { class: "hint", text: "Bot chats are not end-to-end encrypted: your messages pass through Telegram’s servers. Your PC must be on with JARVIS running." }),
    row("Bot token", "Stored only in .env on this computer.", input, connect), state, actions);

  function show(data) {
    input.placeholder = data.enabled ? `Connected (token ending ${data.token_hint?.slice(-4) || "…"})` : "Paste the token from BotFather";
    connect.textContent = data.enabled ? "Replace token" : "Connect bot";
    state.replaceChildren(h("strong", { text: data.linked ? "Phone linked" : data.enabled ? "Waiting for pairing" : "Phone not connected" }));
    if (data.bot_username) state.append(h("p", {}, h("a", { href: `https://t.me/${encodeURIComponent(data.bot_username)}`, target: "_blank", rel: "noopener noreferrer", text: `Open @${data.bot_username}` })));
    if (data.pairing_code) state.append(h("p", {}, "Send this code in a private chat with your bot: ", h("code", { class: "pairing-code", text: data.pairing_code })));
    if (data.last_error) state.append(h("p", { class: "error-box", text: data.last_error }));
    actions.replaceChildren();
    if (data.linked) actions.append(h("button", { class: "btn", type: "button", text: "Send test message", onClick: () => act("/telegram/test", "POST") }));
    if (data.linked) actions.append(h("button", { class: "btn", type: "button", text: "Unlink phone", onClick: async () => {
      if (await confirmDialog({ title: "Unlink this phone?", body: "Phone access stops until you pair again with a new code.", confirm: "Unlink" })) await act("/telegram/unlink", "POST");
    } }));
    if (data.enabled) actions.append(h("button", { class: "btn", type: "button", text: "Disconnect bot", onClick: async () => {
      if (await confirmDialog({ title: "Disconnect this bot?", body: "The token will be removed from this computer. Your saved conversations remain.", confirm: "Disconnect" })) await act("/telegram", "DELETE");
    } }));
  }
  async function refresh() {
    try { show(await api("/telegram")); }
    catch (error) { state.textContent = error.message; }
  }
  async function act(path, method) {
    try { await api(path, { method }); await refresh(); toast(path.endsWith("/test") ? "Test message sent" : "Phone settings updated"); }
    catch (error) { toast(error.message, "error"); }
  }
  connect.addEventListener("click", async () => {
    if (!input.value.trim()) return input.focus();
    connect.disabled = true;
    try {
      await api("/telegram/token", { method: "POST", body: { token: input.value.trim() } });
      input.value = "";
      await refresh();
    } catch (error) { toast(error.message, "error"); }
    finally { connect.disabled = false; }
  });
  refresh();
  const timer = setInterval(() => { if (box.isConnected) refresh(); else clearInterval(timer); }, 4000);
  return box;
}
