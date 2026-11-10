// Turns JARVIS's Markdown into safe HTML with maths and highlighted code.
//
// Order matters for safety and correctness:
//   1. Maths is lifted out first, so Markdown can't mangle underscores and asterisks in it.
//   2. Markdown becomes HTML (marked), which is then sanitised (DOMPurify). Model output
//      therefore cannot inject scripts or event handlers into the page.
//   3. Only then is the maths put back, rendered by KaTeX from plain TeX with its default
//      safe settings.
// The libraries are bundled in /static/vendor and loaded as globals; nothing comes from a CDN.

import { copyText } from "./util.js";

const { marked, DOMPurify, katex, hljs } = window;
marked.setOptions({ gfm: true, breaks: false });

const CODE = /(```[\s\S]*?(?:```|$)|~~~[\s\S]*?(?:~~~|$)|`[^`\n]*`)/g;

function liftMaths(source, store) {
  const hold = (tex, display) => {
    store.push({ tex: tex.trim(), display });
    const marker = `@@MATH${store.length - 1}@@`;
    return display ? `\n\n${marker}\n\n` : marker;
  };
  return source
    .split(CODE)
    .map((segment, index) =>
      index % 2
        ? segment // code: leave untouched
        : segment
            .replace(/\$\$([\s\S]+?)\$\$/g, (_, tex) => hold(tex, true))
            .replace(/\\\[([\s\S]+?)\\\]/g, (_, tex) => hold(tex, true))
            .replace(/\\\(([\s\S]+?)\\\)/g, (_, tex) => hold(tex, false))
            .replace(/(^|[^\\$\w])\$([^\s$](?:[^$\n]*?[^\s$\\])?)\$(?![\w$])/g, (_, before, tex) => before + hold(tex, false)),
    )
    .join("");
}

function renderMaths({ tex, display }) {
  try {
    const html = katex.renderToString(tex, { displayMode: display, throwOnError: false, strict: "ignore" });
    return display ? `<div class="math-block">${html}</div>` : html;
  } catch {
    return `<code>${tex.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" })[c])}</code>`;
  }
}

export function markdownToHtml(source) {
  const maths = [];
  const lifted = liftMaths((source || "").replace(/\r\n?/g, "\n"), maths);
  const safe = DOMPurify.sanitize(marked.parse(lifted), { FORBID_TAGS: ["style", "form", "input", "button", "iframe"], FORBID_ATTR: ["style", "id", "class"] });
  return safe
    .replace(/<p>@@MATH(\d+)@@<\/p>/g, (_, i) => renderMaths(maths[Number(i)]))
    .replace(/@@MATH(\d+)@@/g, (_, i) => renderMaths(maths[Number(i)]));
}

/** Render Markdown into an element, then add the conveniences (code headers, safe links). */
export function renderInto(element, source) {
  element.innerHTML = markdownToHtml(source);
  for (const link of element.querySelectorAll("a[href]")) {
    link.target = "_blank";
    link.rel = "noopener noreferrer";
  }
  for (const table of element.querySelectorAll("table")) {
    const wrap = document.createElement("div");
    wrap.className = "table-wrap";
    table.replaceWith(wrap);
    wrap.append(table);
  }
  for (const code of element.querySelectorAll("pre > code")) {
    const language = (code.getAttribute("data-lang") || [...code.classList].find((c) => c.startsWith("language-"))?.slice(9) || "").toLowerCase();
    if (language && hljs.getLanguage(language)) {
      try {
        code.innerHTML = hljs.highlight(code.textContent, { language, ignoreIllegals: true }).value;
      } catch {
        /* leave it plain */
      }
    }
    const block = document.createElement("div");
    block.className = "code-block";
    const head = document.createElement("div");
    head.className = "code-head";
    const name = document.createElement("span");
    name.textContent = language || "code";
    const copy = document.createElement("button");
    copy.type = "button";
    copy.className = "btn ghost small copy-code";
    copy.textContent = "Copy";
    head.append(name, copy);
    code.parentElement.replaceWith(block);
    block.append(head, Object.assign(document.createElement("pre"), {}));
    block.lastChild.append(code);
  }
}

// DOMPurify strips class attributes above (model output shouldn't style the page), so the
// language of a fenced block is carried across in a data attribute instead.
marked.use({
  renderer: {
    code({ text, lang }) {
      const language = (lang || "").trim().split(/\s+/)[0].replace(/[^\w+#.-]/g, "");
      const escaped = text.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
      return `<pre><code data-lang="${language}">${escaped}</code></pre>\n`;
    },
  },
});

/** One click handler for every "Copy" button inside rendered code blocks. */
export function enableCodeCopy(container) {
  container.addEventListener("click", async (event) => {
    const button = event.target.closest(".copy-code");
    if (!button) return;
    await copyText(button.closest(".code-block").querySelector("code").textContent);
    button.textContent = "Copied";
    setTimeout(() => (button.textContent = "Copy"), 1500);
  });
}
