from __future__ import annotations

from fastapi.testclient import TestClient

from navaid.api.app import create_app
from navaid.ui.site.markdown import render_markdown


def _client() -> TestClient:
    return TestClient(create_app())


def test_site_pages_and_static() -> None:
    client = _client()
    pages = {
        "/": ("Terminal renovation unlocks capacity", "Busy is not investable"),
        "/workbench": ("Analyst workbench", "POST /ask"),
        "/app": ("Analyst workbench", "Envelope"),
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
    assert "Working" in js.text
    assert "shiftKey" in js.text
    assert "switch--on" in js.text
    assert "geminiPrefKey" in js.text
    assert "turn__fold" in js.text
    assert "foldPanel" in js.text
    assert "clearComposer" in js.text
    assert "/speak" in js.text
    assert "narrateAnswer" in js.text
    assert "Show details" in css.text

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
