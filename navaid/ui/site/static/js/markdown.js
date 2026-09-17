/** Conservative Markdown → HTML. Escape first, then lists/headings/inline. */

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function inline(text) {
  const chunks = String(text).split(/(`+[^`]+`+)/);
  return chunks
    .map((chunk) => {
      if (chunk.startsWith("`") && chunk.endsWith("`")) {
        return `<code>${escapeHtml(chunk.replace(/^`+|`+$/g, ""))}</code>`;
      }
      let html = escapeHtml(chunk);
      html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_, label, href) => {
        const safe = escapeHtml(href).replaceAll("'", "");
        if (/^javascript:/i.test(href.trim())) return escapeHtml(label);
        return `<a href="${safe}">${escapeHtml(label)}</a>`;
      });
      html = html.replace(/\*\*(.+?)\*\*|__(.+?)__/g, (_, a, b) => `<strong>${a || b}</strong>`);
      html = html.replace(/(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)|(?<!_)_(?!_)(.+?)(?<!_)_(?!_)/g, (_, a, b) => `<em>${a || b}</em>`);
      return html;
    })
    .join("");
}

export function renderMarkdown(src) {
  const lines = String(src || "").replaceAll("\r\n", "\n").replaceAll("\r", "\n").split("\n");
  const html = [];
  let i = 0;
  const ul = /^(\s*)[-*+]\s+(.*)$/;
  const ol = /^(\s*)(\d+)[.)]\s+(.*)$/;
  const heading = /^(#{1,6})\s+(.*)$/;

  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) {
      i += 1;
      continue;
    }
    const h = heading.exec(line);
    if (h) {
      const level = Math.min(h[1].length, 4);
      html.push(`<h${level}>${inline(h[2].trim())}</h${level}>`);
      i += 1;
      continue;
    }
    const isOl = ol.exec(line);
    const isUl = ul.exec(line);
    if (isOl || isUl) {
      const ordered = Boolean(isOl);
      const tag = ordered ? "ol" : "ul";
      html.push(`<${tag}>`);
      while (i < lines.length) {
        const cur = ordered ? ol.exec(lines[i]) : ul.exec(lines[i]);
        if (!cur) break;
        html.push(`<li>${inline(ordered ? cur[3] : cur[2])}</li>`);
        i += 1;
      }
      html.push(`</${tag}>`);
      continue;
    }
    const para = [line];
    i += 1;
    while (
      i < lines.length &&
      lines[i].trim() &&
      !heading.test(lines[i]) &&
      !ul.test(lines[i]) &&
      !ol.test(lines[i])
    ) {
      para.push(lines[i]);
      i += 1;
    }
    html.push(`<p>${inline(para.map((p) => p.trim()).join(" "))}</p>`);
  }
  return html.join("\n") || "<p></p>";
}
