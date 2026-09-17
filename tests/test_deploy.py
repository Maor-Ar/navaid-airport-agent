from __future__ import annotations

from pathlib import Path

from navaid.api.app import create_app
from scripts.export_site import export_site, prefix_site_urls
from fastapi.testclient import TestClient


def test_export_site_injects_api_and_root(tmp_path: Path) -> None:
    dest = export_site(
        tmp_path / "site",
        api_url="https://navaid-xyz.run.app",
        root="/navaid-airport-agent",
    )
    home = (dest / "index.html").read_text(encoding="utf-8")
    assert '"api":"https://navaid-xyz.run.app"' in home
    assert '"root":"/navaid-airport-agent"' in home
    assert 'href="/navaid-airport-agent/workbench/' in home
    assert (dest / "static" / "js" / "config.js").is_file()
    assert (dest / "workbench" / "index.html").is_file()
    assert (dest / "compare" / "index.html").is_file()
    assert (dest / ".nojekyll").is_file()
    compare = (dest / "compare" / "index.html").read_text(encoding="utf-8")
    assert "/navaid-airport-agent/workbench/" in compare


def test_prefix_leaves_absolute_http_alone() -> None:
    html = '<a href="https://example.com/x">x</a><link href="/static/css/site.css">'
    out = prefix_site_urls(html, "/navaid")
    assert 'href="https://example.com/x"' in out
    assert 'href="/navaid/static/css/site.css"' in out


def test_cors_preflight_allows_github_pages() -> None:
    client = TestClient(create_app())
    response = client.options(
        "/ask",
        headers={
            "Origin": "https://someone.github.io",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-session-id",
        },
    )
    assert response.headers.get("access-control-allow-origin") == "https://someone.github.io"
    assert "POST" in (response.headers.get("access-control-allow-methods") or "")
