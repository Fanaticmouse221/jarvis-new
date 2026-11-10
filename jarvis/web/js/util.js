// Small shared helpers: building DOM, formatting, toasts and the confirm dialog.

const SVG = "http://www.w3.org/2000/svg";

/** Create an element. props: class, text, on<Event> handlers, properties or attributes. */
export function h(tag, props = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (value == null || value === false) continue;
    if (key === "class") el.className = value;
    else if (key === "text") el.textContent = value;
    else if (key.startsWith("on") && typeof value === "function") el.addEventListener(key.slice(2).toLowerCase(), value);
    else if (key === "value") el.value = value; // a property: the only way to fill a textarea
    else el.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child == null || child === false) continue;
    el.append(child.nodeType ? child : document.createTextNode(String(child)));
  }
  return el;
}

export function icon(name, extraClass = "") {
  const svg = document.createElementNS(SVG, "svg");
  svg.setAttribute("class", `icon ${extraClass}`.trim());
  svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS(SVG, "use");
  use.setAttribute("href", `/static/icons.svg#${name}`);
  svg.append(use);
  return svg;
}

export function iconButton(name, label, onClick, extraClass = "") {
  return h("button", { class: `icon-btn ${extraClass}`.trim(), type: "button", title: label, "aria-label": label, onClick }, icon(name));
}

const timeFormat = new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit", hour12: true });
const dateFormat = new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short" });
const longDate = new Intl.DateTimeFormat(undefined, { weekday: "long", day: "numeric", month: "long" });

export const fmtTime = (iso) => (iso ? timeFormat.format(new Date(iso)) : "");
export const fmtDate = (iso) => (iso ? dateFormat.format(new Date(iso)) : "");

/** "Today", "Yesterday", or a full date. `coarse` buckets older dates for the sidebar. */
export function dayLabel(iso, coarse = false) {
  const start = new Date();
  start.setHours(0, 0, 0, 0);
  const then = new Date(iso);
  const days = Math.round((start - new Date(then.getFullYear(), then.getMonth(), then.getDate())) / 86400000);
  if (days <= 0) return "Today";
  if (days === 1) return "Yesterday";
  if (coarse) return days < 7 ? "Earlier this week" : "Older";
  return longDate.format(then);
}

export function fmtDuration(ms) {
  if (!ms) return "";
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
}

export function fmtBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
}

export const plural = (count, word, many = `${word}s`) => `${count} ${count === 1 ? word : many}`;

export function debounce(fn, wait = 250) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), wait);
  };
}

export async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const area = h("textarea", { value: text });
    document.body.append(area);
    area.select();
    document.execCommand("copy");
    area.remove();
  }
}

export function toast(message, kind = "") {
  const node = h("div", { class: `toast ${kind}`.trim(), text: message });
  document.getElementById("toasts").append(node);
  setTimeout(() => node.remove(), kind === "error" ? 6000 : 3200);
}

/** Ask the user to confirm something consequential. Resolves true or false. */
export function confirmDialog({ title, body, confirm = "Confirm", danger = false }) {
  const dialog = document.getElementById("dialog");
  return new Promise((resolve) => {
    const done = (answer) => {
      dialog.close();
      resolve(answer);
    };
    dialog.replaceChildren(
      h("h2", { text: title }),
      h("p", { text: body }),
      h(
        "div",
        { class: "dialog-actions" },
        h("button", { class: "btn", type: "button", text: "Cancel", onClick: () => done(false) }),
        h("button", { class: `btn ${danger ? "danger" : "primary"}`, type: "button", text: confirm, onClick: () => done(true) }),
      ),
    );
    dialog.oncancel = () => resolve(false);
    dialog.showModal();
  });
}

export function segmented(options, value, onChange, label) {
  const group = h("div", { class: "segmented", role: "group", "aria-label": label });
  for (const [key, text] of options) {
    group.append(
      h("button", {
        type: "button",
        text,
        "aria-pressed": String(key === value),
        onClick: () => {
          for (const button of group.children) button.setAttribute("aria-pressed", String(button.textContent === text));
          onChange(key);
        },
      }),
    );
  }
  return group;
}

export function toggle(value, onChange, label) {
  const button = h("button", { class: "switch", type: "button", role: "switch", "aria-checked": String(!!value), "aria-label": label });
  button.addEventListener("click", () => {
    const next = button.getAttribute("aria-checked") !== "true";
    button.setAttribute("aria-checked", String(next));
    onChange(next);
  });
  return button;
}

/** A settings row: label and explanation on the left, control on the right. */
export function row(label, description, ...controls) {
  return h(
    "div",
    { class: "row" },
    h("div", { class: "row-text" }, h("strong", { text: label }), description ? h("span", { text: description }) : null),
    h("div", { class: "row-control" }, ...controls),
  );
}

export function section(title, note, ...children) {
  return h("section", { class: "section" }, h("h2", { text: title }), note ? h("p", { class: "section-note", text: note }) : null, ...children);
}
