from __future__ import annotations

from fastapi.testclient import TestClient

from navaid.api.app import create_app
from navaid.config import WAREHOUSE_PATH
from navaid.warehouse.snapshot import build_snapshot


def _client() -> TestClient:
    return TestClient(create_app())


def test_health_and_eval_summary() -> None:
    client = _client()
    health = client.get("/health")
    assert health.status_code == 200
    body = health.json()
    assert body["status"] == "ok"
    assert "model" in body
    assert "gemini_configured" in body
    assert body.get("gemini_auth") in {"api_key", "vertex_adc", "none"}
    assert "tts" in body
    assert "tts" in body
    summary = client.get("/eval/summary")
    assert summary.status_code == 200
    payload = summary.json()
    assert payload["status"] in {"ok", "no_runs"}
    if payload["status"] == "ok":
        assert payload.get("item_count", 0) >= 1
        assert "kpis" in payload
    else:
        assert "run_eval" in payload.get("message", "")


def test_ask_session_header() -> None:
    if not WAREHOUSE_PATH.is_file():
        build_snapshot(offline=True, force_fixtures=True)
    client = _client()
    response = client.post(
        "/ask",
        json={
            "question": "What is the unmet flight demand in SFO airport and why?",
            "use_gemini": False,
        },
        headers={"X-Session-Id": "api-test-session"},
    )
    assert response.status_code == 200
    assert response.headers.get("X-Session-Id") == "api-test-session"
    payload = response.json()
    assert payload["reconstructed_query"]
    assert payload["subgoals"]
    assert payload["sections"]
    assert payload["envelope"]
    assert any(sg["intent"] == "UNMET_DEMAND" for sg in payload["subgoals"])


def test_speak_empty_and_fallback(monkeypatch) -> None:
    monkeypatch.setattr("navaid.ui.voice.synthesize_wav_bytes", lambda text: (None, "TTS unavailable"))
    client = _client()
    empty = client.post("/speak", json={"text": ""})
    assert empty.status_code in {400, 422}
    missing = client.post("/speak", json={"text": "BOS TEOI is peer-relative."})
    assert missing.status_code == 503
    body = missing.json()
    assert body.get("fallback") == "browser"
    wav = b"RIFF" + b"\x00" * 40
    monkeypatch.setattr("navaid.ui.voice.synthesize_wav_bytes", lambda text: (wav, "Spoken with Gemini TTS"))
    ok = client.post("/speak", json={"text": "BOS is mixed-constrained."})
    assert ok.status_code == 200
    assert ok.headers["content-type"].startswith("audio/wav")
    assert ok.content == wav
