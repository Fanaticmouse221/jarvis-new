// Minimal, safe Markdown renderer for JARVIS's replies.
//
// Safety: every piece of text is HTML-escaped before any formatting is applied,
// and only a fixed set of tags is ever produced. Links must be http(s). Model
// output therefore cannot inject scripts or arbitrary HTML into the page.

const escapeHtml = (s) =>
  s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
   .replace(/"/g, "&quot;").replace(/'/g, "&#39;");

const FENCE = /^\s*```\s*([\w+#.-]*)\s*$/;
const FENCE_END = /^\s*```\s*$/;
const HEADING = /^(#{1,6})\s+(.*)$/;
const RULE = /^\s*([-*_])(\s*\1){2,}\s*$/;
const QUOTE = /^\s*>/;
const LIST_ITEM = /^(\s*)([-*+]|\d+[.)])\s+(.*)$/;
const TABLE_SEP = /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$/;
const BLANK = /^\s*$/;

function inline(raw) {
  let text = escapeHtml(raw);
  const codes = [];
  text = text.replace(/`([^`\n]+)`/g, (_, code) => {
    codes.push(code);
    return `\u0000${codes.length - 1}\u0000`;
  });
  text = text.replace(
    /\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)/g,
    (_, label, url) => `<a href="${url}" target="_blank" rel="noopener noreferrer">${label}</a>`,
  );
  text = text
    .replace(/\*\*([^*\n]+?)\*\*/g, "<strong>$1</strong>")
    .replace(/__([^_\n]+?)__/g, "<strong>$1</strong>")
    .replace(/(^|[^*\w])\*([^*\n]+?)\*(?!\w)/g, "$1<em>$2</em>")
    .replace(/(^|[^_\w])_([^_\n]+?)_(?!\w)/g, "$1<em>$2</em>")
    .replace(/~~([^~\n]+?)~~/g, "<del>$1</del>");
  return text.replace(/\u0000(\d+)\u0000/g, (_, i) => `<code>${codes[Number(i)]}</code>`);
}

const indentOf = (line) => line.match(/^\s*/)[0].replace(/\t/g, "    ").length;

const isTableStart = (lines, i) =>
  lines[i].trim().startsWith("|") && i + 1 < lines.length && TABLE_SEP.test(lines[i + 1]);

function isBlockStart(lines, i) {
  const line = lines[i];
  return FENCE.test(line) || HEADING.test(line) || RULE.test(line) || QUOTE.test(line) ||
    LIST_ITEM.test(line) || isTableStart(lines, i);
}

function codeBlock(code, lang) {
  return `<div class="code-block"><div class="code-head"><span>${escapeHtml(lang || "code")}</span>` +
    `<button type="button" class="copy-code">Copy</button></div>` +
    `<pre><code>${escapeHtml(code)}</code></pre></div>`;
}

function splitRow(row) {
  return row.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((cell) => cell.trim());
}

function table(header, rows) {
  const head = header.map((cell) => `<th>${inline(cell)}</th>`).join("");
  const body = rows
    .map((row) => `<tr>${header.map((_, i) => `<td>${inline(row[i] ?? "")}</td>`).join("")}</tr>`)
    .join("");
  return `<div class="table-wrap"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
}

function parseList(lines, start) {
  const baseIndent = indentOf(lines[start]);
  const ordered = /^\s*\d+[.)]\s+/.test(lines[start]);
  const items = [];
  let i = start;
  while (i < lines.length) {
    const line = lines[i];
    if (BLANK.test(line)) {
      // A blank line continues the list only if the next item belongs to it.
      let j = i + 1;
      while (j < lines.length && BLANK.test(lines[j])) j++;
      if (j < lines.length && LIST_ITEM.test(lines[j]) && indentOf(lines[j]) >= baseIndent) {
        i = j;
        continue;
      }
      break;
    }
    const indent = indentOf(line);
    const match = line.match(LIST_ITEM);
    if (match && indent <= baseIndent + 1 && indent >= baseIndent) {
      items.push({ lines: [match[3]], children: [] });
      i++;
    } else if (indent >= baseIndent + 2 && items.length) {
      const current = items[items.length - 1];
      if (match) {
        const [html, next] = parseList(lines, i);
        current.children.push(html);
        i = next;
      } else {
        current.lines.push(line.trim());
        i++;
      }
    } else {
      break;
    }
  }
  const tag = ordered ? "ol" : "ul";
  const first = parseInt(lines[start].trim(), 10);
  const startAttr = ordered && first > 1 ? ` start="${first}"` : "";
  const html = items
    .map((item) => `<li>${item.lines.map(inline).join("<br>")}${item.children.join("")}</li>`)
    .join("");
  return [`<${tag}${startAttr}>${html}</${tag}>`, i];
}

export function renderMarkdown(source) {
  let src = (source || "").replace(/\r\n?/g, "\n");
  // While streaming, a code block may not be closed yet; close it for display.
  if (((src.match(/^\s*```/gm) || []).length) % 2 === 1) src += "\n```";

  const lines = src.split("\n");
  const out = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (BLANK.test(line)) { i++; continue; }

    const fence = line.match(FENCE);
    if (fence) {
      const code = [];
      i++;
      while (i < lines.length && !FENCE_END.test(lines[i])) code.push(lines[i++]);
      i++;
      out.push(codeBlock(code.join("\n"), fence[1]));
      continue;
    }

    const heading = line.match(HEADING);
    if (heading) {
      const level = Math.min(heading[1].length, 4);
      out.push(`<h${level}>${inline(heading[2])}</h${level}>`);
      i++;
      continue;
    }

    if (RULE.test(line)) { out.push("<hr>"); i++; continue; }

    if (isTableStart(lines, i)) {
      const header = splitRow(line);
      const rows = [];
      i += 2;
      while (i < lines.length && lines[i].trim().startsWith("|")) rows.push(splitRow(lines[i++]));
      out.push(table(header, rows));
      continue;
    }

    if (QUOTE.test(line)) {
      const quoted = [];
      while (i < lines.length && QUOTE.test(lines[i])) quoted.push(lines[i++].replace(/^\s*>\s?/, ""));
      out.push(`<blockquote>${renderMarkdown(quoted.join("\n"))}</blockquote>`);
      continue;
    }

    if (LIST_ITEM.test(line)) {
      const [html, next] = parseList(lines, i);
      out.push(html);
      i = next;
      continue;
    }

    const para = [lines[i++]];
    while (i < lines.length && !BLANK.test(lines[i]) && !isBlockStart(lines, i)) para.push(lines[i++]);
    out.push(`<p>${para.map(inline).join("<br>")}</p>`);
  }
  return out.join("\n");
}
