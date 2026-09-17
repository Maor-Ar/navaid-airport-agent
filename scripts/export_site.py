"""Export the analyst site as static HTML for GitHub Pages.

Usage (from repo root):

    python scripts/export_site.py --out site-dist
    python scripts/export_site.py --out site-dist --api-url https://navaid-xxxx.run.app --root /navaid
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from navaid.api.site import COMPARE_QUESTION, STATIC, exported_pages  # noqa: E402

FOLDER_PAGES = {
    "/workbench",
    "/app",
    "/methodology",
    "/glossary",
    "/decisions",
    "/architecture",
    "/compare",
}

ATTR_URL = re.compile(r"""\b(href|src)=["']([^"']+)["']""")
CONFIG_JSON = re.compile(
    r'(<script type="application/json" id="navaid-config">)(.*?)(</script>)',
    re.DOTALL,
)


def prefix_site_urls(html: str, root: str) -> str:
    """Rewrite same-origin /paths so a project Pages site can live under /repo."""

    if not root:
        return html
    root = "/" + root.strip("/")

    def repl(match: re.Match[str]) -> str:
        attr, url = match.group(1), match.group(2)
        if not url.startswith("/") or url.startswith("//"):
            return match.group(0)
        path, sep, query = url.partition("?")
        if path == "/":
            path = f"{root}/"
        elif path in FOLDER_PAGES:
            path = f"{root}{path}/"
        else:
            path = f"{root}{path}"
        return f'{attr}="{path}{sep}{query}"'

    return ATTR_URL.sub(repl, html)


def inject_config(html: str, *, api_url: str, root: str) -> str:
    payload = json.dumps({"api": api_url.rstrip("/"), "root": root}, separators=(",", ":"))

    def repl(match: re.Match[str]) -> str:
        return f"{match.group(1)}{payload}{match.group(3)}"

    if CONFIG_JSON.search(html):
        return CONFIG_JSON.sub(repl, html, count=1)
    tag = f'<script type="application/json" id="navaid-config">{payload}</script>'
    return html.replace("</head>", f"{tag}\n</head>", 1)


def compare_redirect_html(*, root: str) -> str:
    dest = "/workbench/?q=" + quote(COMPARE_QUESTION) + "&autosubmit=1"
    if root:
        dest = "/" + root.strip("/") + dest
    return (
        "<!DOCTYPE html>\n<html lang=\"en\"><head>"
        f'<meta charset="utf-8"><meta http-equiv="refresh" content="0; url={dest}">'
        f'<link rel="canonical" href="{dest}">'
        f"<script>location.replace({json.dumps(dest)})</script>"
        f"</head><body><p><a href=\"{dest}\">Compare LAX vs SNA</a></p></body></html>\n"
    )


def not_found_html(*, root: str) -> str:
    home = f"/{root.strip('/')}/" if root else "/"
    return (
        "<!DOCTYPE html>\n<html lang=\"en\"><head>"
        '<meta charset="utf-8"><title>Navaid</title>'
        f'<script>location.replace({json.dumps(home)})</script>'
        f"</head><body><p><a href=\"{home}\">Navaid home</a></p></body></html>\n"
    )


def export_site(out_dir: Path, *, api_url: str = "", root: str = "") -> Path:
    dest = out_dir.resolve()
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)

    site_root = ("/" + root.strip("/")) if root.strip("/") else ""
    for rel, html in exported_pages().items():
        html = inject_config(html, api_url=api_url, root=site_root)
        html = prefix_site_urls(html, site_root)
        path = dest / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(html, encoding="utf-8")

    compare_dir = dest / "compare"
    compare_dir.mkdir(parents=True, exist_ok=True)
    (compare_dir / "index.html").write_text(
        compare_redirect_html(root=site_root), encoding="utf-8"
    )
    (dest / "404.html").write_text(not_found_html(root=site_root), encoding="utf-8")
    (dest / ".nojekyll").write_text("", encoding="utf-8")

    static_dest = dest / "static"
    if STATIC.is_dir():
        shutil.copytree(STATIC, static_dest)

    return dest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export Navaid static site for GitHub Pages")
    parser.add_argument("--out", type=Path, default=ROOT / "site-dist")
    parser.add_argument("--api-url", default="", help="Cloud Run origin, no trailing slash")
    parser.add_argument(
        "--root",
        default="",
        help="Pages path prefix, e.g. /navaid-airport-agent (empty for user.github.io root)",
    )
    args = parser.parse_args(argv)
    dest = export_site(args.out, api_url=args.api_url, root=args.root)
    print(dest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
