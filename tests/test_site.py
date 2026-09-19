from __future__ import annotations

from fastapi.testclient import TestClient

from navaid.api.app import create_app
from navaid.config import CONSTRAINT_EXPLANATIONS
from navaid.ui.site.markdown import render_markdown


def _client() -> TestClient:
    return TestClient(create_app())


def test_site_pages_and_static() -> None:
    client = _client()
    pages = {
        "/": ("Terminal renovation unlocks capacity", "Busy is not investable"),
        "/workbench": ("Analyst workbench", "Enter sends"),
        "/app": ("Analyst workbench", "Assumptions"),
        "/methodology": ("TEOI = 100", "4000 km"),
        "/glossary": ("Navaid glossary", "Terminal Expansion Opportunity Index"),
        "/decisions": ("Decision log", "Why not LangChain"),
        "/architecture": ("Navaid architecture", "gemini-2.5-flash"),
    }
    for path, needles in pages.items():
        response = client.get(path)
        assert response.status_code == 200, path
        assert "text/html" in response.headers["content-type"]
        body = response.text
        for needle in needles:
            assert needle in body, f"{path} missing {needle!r}"
        assert 'id="navaid-config"' in body

    css = client.get("/static/css/site.css")
    assert css.status_code == 200
    assert "IBM Plex Sans" in css.text or "--serif" in css.text
    assert ".switch--on" in css.text or "aria-checked" in css.text

    js = client.get("/static/js/workbench.js")
    assert js.status_code == 200
    assert "navaidApi" in js.text
    assert "/ask" in js.text
    assert "showPending" in js.text
    assert "use_gemini: true" in js.text
    assert "gemini-switch" not in js.text
    assert "geminiPrefKey" not in js.text
    assert "kicker: \"Process\"" in js.text or 'kicker: "Process"' in js.text
    assert "kicker: \"Working\"" not in js.text and 'kicker: "Working"' not in js.text
    assert "shiftKey" in js.text
    assert "resetEnvelope" in js.text
    assert "openEnvelopeModal" in js.text
    assert "renderMap" in js.text
    assert "hideMapPane" in js.text
    assert "setMapPaneVisible" in js.text
    assert "workbench__grid--map" in js.text
    assert "Last map kept" not in js.text
    assert "lastMapPoints" not in js.text
    assert "decorateIata" in js.text
    assert "Enter sends" in js.text
    assert "nav-toggle" in client.get("/").text
    home = client.get("/")
    assert "Navaid — Navaid" not in home.text
    assert "<title>Navaid</title>" in home.text
    missing = client.get("/this-does-not-exist")
    assert missing.status_code == 404
    assert "text/html" in missing.headers["content-type"]
    assert "not on the desk" in missing.text.lower()
    assert "Navaid" in missing.text
    assert "switch--on" in js.text
    assert "turn__fold" in js.text
    assert "foldPanel" in js.text
    assert "CONSTRAINT_WHY" in js.text
    assert "constraintWhy" in js.text
    assert "uniqueConstraintWhyNodes" in js.text
    for key, text in CONSTRAINT_EXPLANATIONS.items():
        assert text in js.text, f"workbench.js missing {key} explanation"
    assert "constraint-why" in js.text
    assert "clearComposer" in js.text
    assert "/speak" in js.text
    assert "narrateAnswer" in js.text
    assert "Show details" in css.text
    assert ".constraint-why" in css.text
    assert ".iata .flag" in css.text
    flags = client.get("/static/js/flags.js")
    assert flags.status_code == 200
    assert "US-MA" in flags.text
    assert client.get("/static/flags/us-ma.svg").status_code == 200
    assert client.get("/static/flags/us.svg").status_code == 200
    leaflet = client.get("/static/vendor/leaflet/leaflet.js")
    assert leaflet.status_code == 200
    workbench = client.get("/workbench")
    assert "Assumptions" in workbench.text
    assert "gemini-switch" not in workbench.text
    assert "leaflet.css" in workbench.text
    assert 'id="map-sidebar"' in workbench.text
    assert 'id="workbench-grid"' in workbench.text
    assert 'class="map-sidebar" id="map-sidebar" hidden' in workbench.text
    assert "Greetings keep this overview" not in workbench.text
    assert "workbench__grid--map" in css.text
    assert "minmax(0, 1fr) minmax(0, 1fr)" in css.text
    assert "20.5rem" not in css.text
    assert ".map-sidebar[hidden]" in css.text

    md = client.get("/site/docs/GLOSSARY")
    assert md.status_code == 200
    assert "TEOI" in md.text


def test_compare_shortcut_and_api_untouched() -> None:
    client = _client()
    redirect = client.get("/compare", follow_redirects=False)
    assert redirect.status_code == 307
    location = redirect.headers["location"]
    assert location.startswith("/workbench?")
    assert "autosubmit=1" in location
    assert "Santa" in location or "Santa%20Ana" in location or "Santa+Ana" in location

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    stub = client.get("/eval/summary")
    assert stub.status_code == 200
    assert "status" in stub.json()


def test_markdown_tables_and_doc_links() -> None:
    html, toc = render_markdown(
        "# Title\n\nSee [GLOSSARY.md](GLOSSARY.md).\n\n"
        "| Feature | Weight |\n| --- | --- |\n| Demand | 0.22 |\n"
    )
    assert "<table>" in html
    assert "0.22" in html
    assert 'href="/glossary"' in html
    assert toc[0][2] == "Title"
    mermaid, _ = render_markdown("```mermaid\nflowchart LR\nA-->B\n```")
    assert "mermaid-wrap" in mermaid
    assert "pre class=\"mermaid\"" in mermaid
