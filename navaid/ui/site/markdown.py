"""Small Markdown-to-HTML converter for docs/ (no extra dependency)."""

from __future__ import annotations

import re
from html import escape

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_UL_RE = re.compile(r"^(\s*)[-*+]\s+(.*)$")
_OL_RE = re.compile(r"^(\s*)(\d+)[.)]\s+(.*)$")
_HR_RE = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$")
_TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{3,}")
_CODE_SPLIT = re.compile(r"(`+[^`]+`+)")
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_STRONG_RE = re.compile(r"\*\*(.+?)\*\*|__(.+?)__")
_EM_RE = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)|(?<!_)_(?!_)(.+?)(?<!_)_(?!_)")

DOC_LINKS = {
    "GLOSSARY.md": "/glossary",
    "DECISION_LOG.md": "/decisions",
    "ARCHITECTURE.md": "/architecture",
    "docs/GLOSSARY.md": "/glossary",
    "docs/DECISION_LOG.md": "/decisions",
    "docs/ARCHITECTURE.md": "/architecture",
}


def slugify(text: str, used: dict[str, int] | None = None) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    slug = slug or "section"
    if used is None:
        return slug
    n = used.get(slug, 0) + 1
    used[slug] = n
    return slug if n == 1 else f"{slug}-{n}"


def rewrite_href(href: str) -> str:
    raw = href.strip()
    mapped = DOC_LINKS.get(raw) or DOC_LINKS.get(raw.split("/")[-1])
    return mapped or raw


def inline(text: str) -> str:
    """Escape and apply a conservative inline subset (code, links, bold, italic)."""

    pieces: list[str] = []
    for chunk in _CODE_SPLIT.split(text):
        if chunk.startswith("`") and chunk.endswith("`"):
            inner = chunk.strip("`")
            pieces.append(f"<code>{escape(inner)}</code>")
            continue
        escaped = escape(chunk)
        escaped = _LINK_RE.sub(
            lambda m: f'<a href="{escape(rewrite_href(m.group(2)), quote=True)}">{m.group(1)}</a>',
            escaped,
        )
        escaped = _STRONG_RE.sub(lambda m: f"<strong>{m.group(1) or m.group(2)}</strong>", escaped)
        escaped = _EM_RE.sub(lambda m: f"<em>{m.group(1) or m.group(2)}</em>", escaped)
        pieces.append(escaped)
    return "".join(pieces)


def _split_row(line: str) -> list[str]:
    raw = line.strip()
    if raw.startswith("|"):
        raw = raw[1:]
    if raw.endswith("|"):
        raw = raw[:-1]
    return [cell.strip() for cell in raw.split("|")]


def render_markdown(src: str) -> tuple[str, list[tuple[int, str, str]]]:
    """Return ``(html, toc)`` where toc is ``(level, id, text)`` for h1–h3."""

    text = src.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    html: list[str] = []
    toc: list[tuple[int, str, str]] = []
    used_ids: dict[str, int] = {}
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i]
        if line.startswith("```"):
            lang = line[3:].strip()
            i += 1
            buf: list[str] = []
            while i < n and not lines[i].startswith("```"):
                buf.append(lines[i])
                i += 1
            if i < n:
                i += 1
            code = escape("\n".join(buf))
            if lang.lower() == "mermaid":
                html.append(f'<div class="mermaid-wrap"><pre class="mermaid">{code}</pre></div>')
            else:
                cls = f' class="language-{escape(lang, quote=True)}"' if lang else ""
                html.append(f"<pre><code{cls}>{code}</code></pre>")
            continue

        if _HR_RE.match(line):
            html.append("<hr>")
            i += 1
            continue

        heading = _HEADING_RE.match(line)
        if heading:
            level = len(heading.group(1))
            raw_title = heading.group(2).strip()
            hid = slugify(raw_title, used_ids)
            html.append(f'<h{level} id="{escape(hid, quote=True)}">{inline(raw_title)}</h{level}>')
            if level <= 3:
                toc.append((level, hid, raw_title))
            i += 1
            continue

        if line.strip().startswith("|") and i + 1 < n and _TABLE_SEP_RE.match(lines[i + 1].replace("|", " | ")):
            headers = _split_row(line)
            i += 2
            rows: list[list[str]] = []
            while i < n and lines[i].strip().startswith("|"):
                rows.append(_split_row(lines[i]))
                i += 1
            thead = "".join(f"<th>{inline(cell)}</th>" for cell in headers)
            body_rows = []
            for row in rows:
                padded = row + [""] * max(0, len(headers) - len(row))
                tds = "".join(f"<td>{inline(cell)}</td>" for cell in padded[: len(headers)])
                body_rows.append(f"<tr>{tds}</tr>")
            html.append(
                '<div class="table-wrap"><table>'
                f"<thead><tr>{thead}</tr></thead>"
                f"<tbody>{''.join(body_rows)}</tbody>"
                "</table></div>"
            )
            continue

        ul = _UL_RE.match(line)
        ol = _OL_RE.match(line)
        if ul or ol:
            ordered = bool(ol)
            tag = "ol" if ordered else "ul"
            html.append(f"<{tag}>")
            while i < n:
                cur = _OL_RE.match(lines[i]) if ordered else _UL_RE.match(lines[i])
                if not cur:
                    break
                item = cur.group(3) if ordered else cur.group(2)
                i += 1
                extra: list[str] = []
                while i < n and lines[i].startswith("  ") and not (
                    _UL_RE.match(lines[i]) or _OL_RE.match(lines[i]) or not lines[i].strip()
                ):
                    extra.append(lines[i].strip())
                    i += 1
                body = item if not extra else item + " " + " ".join(extra)
                html.append(f"<li>{inline(body)}</li>")
            html.append(f"</{tag}>")
            continue

        if not line.strip():
            i += 1
            continue

        para = [line]
        i += 1
        while i < n and lines[i].strip() and not lines[i].startswith("#") and not lines[i].startswith("```") and not _HR_RE.match(lines[i]) and not lines[i].strip().startswith("|") and not _UL_RE.match(lines[i]) and not _OL_RE.match(lines[i]):
            para.append(lines[i])
            i += 1
        html.append(f"<p>{inline(' '.join(p.strip() for p in para))}</p>")

    return "\n".join(html), toc
