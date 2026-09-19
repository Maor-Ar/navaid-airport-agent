"""Analyst site routes and static files. Additive — does not replace /ask, /health, or /eval/summary."""

from __future__ import annotations

from html import escape
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from navaid.config import PROJECT_ROOT
from navaid.ui.site.markdown import render_markdown

SITE_ROOT = Path(__file__).resolve().parent.parent / "ui" / "site"
TEMPLATES = SITE_ROOT / "templates"
STATIC = SITE_ROOT / "static"
DOCS_DIR = PROJECT_ROOT / "docs"

DOCS: dict[str, tuple[str, str, str, str]] = {
    "GLOSSARY": (
        "GLOSSARY.md",
        "Glossary",
        "glossary",
        "Product terms, aviation vocabulary, scoring language, and the assignment airport set.",
    ),
    "DECISION_LOG": (
        "DECISION_LOG.md",
        "Decision log",
        "decisions",
        "Investigation phases 0–9: domain, data, TEOI math, architecture, and package decisions.",
    ),
    "ARCHITECTURE": (
        "ARCHITECTURE.md",
        "Architecture",
        "architecture",
        "Assignment deliverable: scoring methodology, tradeoffs, and where Gemini is used.",
    ),
}

COMPARE_QUESTION = "Compare LA and Santa Ana airport congestion levels."

router = APIRouter()


def _template(name: str) -> str:
    path = TEMPLATES / name
    if not path.is_file():
        raise FileNotFoundError(path)
    return path.read_text(encoding="utf-8")


def _page_title(title: str) -> str:
    cleaned = (title or "").strip() or "Navaid"
    if cleaned.lower() == "navaid" or cleaned.lower().endswith(" navaid"):
        return cleaned
    return f"{cleaned} — Navaid"


def render_page(
    page: str,
    *,
    title: str,
    description: str,
    main: str,
    scripts: str = "",
    status_code: int = 200,
) -> HTMLResponse:
    html = (
        _template("base.html")
        .replace("{{title}}", _page_title(title))
        .replace("{{description}}", description)
        .replace("{{page}}", page)
        .replace("{{main}}", main)
        .replace("{{scripts}}", scripts)
    )
    return HTMLResponse(html, status_code=status_code)


def _toc_html(toc: list[tuple[int, str, str]]) -> str:
    items = [entry for entry in toc if entry[0] >= 2]
    if not items:
        return '<p class="muted">On-page headings appear after the document loads.</p>'
    lis = []
    for level, hid, text in items:
        cls = "toc--h3" if level >= 3 else ""
        lis.append(
            f'<li class="{cls}"><a href="#{escape(hid, quote=True)}">{escape(text)}</a></li>'
        )
    return "<ul>" + "".join(lis) + "</ul>"


def _doc_page(slug: str) -> HTMLResponse:
    key = slug.strip().upper().replace("-", "_")
    if key not in DOCS:
        raise HTTPException(status_code=404, detail="Unknown document")
    filename, title, page, description = DOCS[key]
    path = DOCS_DIR / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"{filename} is not in docs/")
    body, toc = render_markdown(path.read_text(encoding="utf-8"))
    main = (
        _template("doc.html")
        .replace("{{toc}}", _toc_html(toc))
        .replace("{{body}}", body)
    )
    return render_page(page, title=title, description=description, main=main)


@router.get("/", include_in_schema=False)
def landing() -> HTMLResponse:
    return render_page(
        "home",
        title="Navaid",
        description="Terminal renovation unlocks capacity. Busy is not investable.",
        main=_template("home.html"),
    )


@router.get("/workbench", include_in_schema=False)
@router.get("/app", include_in_schema=False)
def workbench() -> HTMLResponse:
    return render_page(
        "workbench",
        title="Workbench",
        description="Analyst workbench over POST /ask — steps, TEOI waterfall, envelope.",
        main=_template("workbench.html"),
        scripts=(
            '<script src="/static/vendor/leaflet/leaflet.js"></script>'
            '<script type="module" src="/static/js/workbench.js"></script>'
        ),
    )


@router.get("/compare", include_in_schema=False)
def compare_lax_sna() -> RedirectResponse:
    target = "/workbench?q=" + quote(COMPARE_QUESTION) + "&autosubmit=1"
    return RedirectResponse(url=target, status_code=307)


@router.get("/methodology", include_in_schema=False)
def methodology() -> HTMLResponse:
    return render_page(
        "methodology",
        title="Methodology",
        description="TEOI formula, constraint multipliers, drop-and-renormalize, long-haul 4000 km.",
        main=_template("methodology.html"),
    )


@router.get("/glossary", include_in_schema=False)
def glossary() -> HTMLResponse:
    return _doc_page("GLOSSARY")


@router.get("/decisions", include_in_schema=False)
def decisions() -> HTMLResponse:
    return _doc_page("DECISION_LOG")


@router.get("/architecture", include_in_schema=False)
def architecture() -> HTMLResponse:
    return _doc_page("ARCHITECTURE")


@router.get("/site/docs/{slug}", include_in_schema=False)
def site_doc_markdown(slug: str) -> PlainTextResponse:
    key = slug.strip().upper().replace(".MD", "").replace("-", "_")
    if key not in DOCS:
        raise HTTPException(status_code=404, detail="Unknown document")
    filename = DOCS[key][0]
    path = DOCS_DIR / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"{filename} is not in docs/")
    return PlainTextResponse(path.read_text(encoding="utf-8"), media_type="text/markdown; charset=utf-8")


@router.get("/favicon.svg", include_in_schema=False)
@router.get("/favicon.ico", include_in_schema=False)
def favicon() -> FileResponse:
    path = STATIC / "favicon.svg"
    if not path.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(path, media_type="image/svg+xml")


def not_found_page() -> HTMLResponse:
    return render_page(
        "home",
        title="Page not found",
        description="That URL is not part of Navaid.",
        main=_template("not_found.html"),
        status_code=404,
    )


def mount_site(app: FastAPI) -> None:
    """Register HTML routes and /static. Call from create_app after API routes."""

    app.include_router(router)
    if STATIC.is_dir():
        app.mount("/static", StaticFiles(directory=str(STATIC)), name="navaid-site")


def _html_body(response: HTMLResponse) -> str:
    return bytes(response.body).decode("utf-8")


def exported_pages() -> dict[str, str]:
    """Static HTML files for GitHub Pages, keyed by path under the site root."""

    return {
        "index.html": _html_body(landing()),
        "workbench/index.html": _html_body(workbench()),
        "methodology/index.html": _html_body(methodology()),
        "glossary/index.html": _html_body(glossary()),
        "decisions/index.html": _html_body(decisions()),
        "architecture/index.html": _html_body(architecture()),
    }


__all__ = ["exported_pages", "mount_site", "not_found_page", "router"]
