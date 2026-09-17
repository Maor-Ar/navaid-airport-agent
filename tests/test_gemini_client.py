from __future__ import annotations

from navaid.gemini_client import (
    AUTH_HELP,
    clear_auth_cache,
    gemini_auth_mode,
    gemini_configured,
    make_genai_client,
)


def _clear_keys(monkeypatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_GENAI_USE_VERTEXAI", raising=False)
    monkeypatch.delenv("NAVAID_USE_VERTEXAI", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("GCLOUD_PROJECT", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    monkeypatch.setattr("navaid.gemini_client._gcloud_config_project", lambda: "")
    clear_auth_cache()


def test_api_key_mode(monkeypatch) -> None:
    _clear_keys(monkeypatch)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    clear_auth_cache()
    assert gemini_auth_mode() == "api_key"
    assert gemini_configured() is True


def test_adc_quota_project_is_enough(monkeypatch, tmp_path) -> None:
    _clear_keys(monkeypatch)
    creds = tmp_path / "application_default_credentials.json"
    creds.write_text('{"quota_project_id": "adc-quota-proj"}', encoding="utf-8")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(creds))
    clear_auth_cache()
    assert gemini_auth_mode() == "vertex_adc"
    from navaid.gemini_client import cloud_project

    assert cloud_project() == "adc-quota-proj"
    _clear_keys(monkeypatch)
    creds = tmp_path / "application_default_credentials.json"
    creds.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(creds))
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "navaid-test")
    clear_auth_cache()
    assert gemini_auth_mode() == "vertex_adc"
    assert gemini_configured() is True


def test_gcloud_login_without_adc_is_not_enough(monkeypatch) -> None:
    _clear_keys(monkeypatch)
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "navaid-test")
    monkeypatch.setattr("navaid.gemini_client.adc_path", lambda: None)
    clear_auth_cache()
    assert gemini_auth_mode() == "none"
    assert gemini_configured() is False
    try:
        make_genai_client()
        raise AssertionError("expected RuntimeError")
    except RuntimeError as exc:
        assert "update-adc" in str(exc)


def test_unauthenticated_help(monkeypatch) -> None:
    _clear_keys(monkeypatch)
    monkeypatch.setattr("navaid.gemini_client.adc_path", lambda: None)
    clear_auth_cache()
    assert gemini_configured() is False
    try:
        make_genai_client()
        raise AssertionError("expected RuntimeError")
    except RuntimeError as exc:
        assert "gcloud auth login" in str(exc)
        assert "GEMINI_API_KEY" in AUTH_HELP
