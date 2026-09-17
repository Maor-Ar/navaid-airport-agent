"""Shared Gemini client: API key or Google Cloud ADC (gcloud).

Priority:
1. GOOGLE_GENAI_USE_VERTEXAI=1 → Vertex AI + ADC
2. GEMINI_API_KEY / GOOGLE_API_KEY → Gemini Developer API
3. ADC file + Cloud project → Vertex AI
"""

from __future__ import annotations

import functools
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Literal

AuthMode = Literal["api_key", "vertex_adc", "none"]


def _flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def api_key() -> str:
    return (
        os.getenv("GEMINI_API_KEY", "").strip()
        or os.getenv("GOOGLE_API_KEY", "").strip()
    )


def force_vertex() -> bool:
    return _flag("GOOGLE_GENAI_USE_VERTEXAI") or _flag("NAVAID_USE_VERTEXAI")


def cloud_location() -> str:
    return (
        os.getenv("GOOGLE_CLOUD_LOCATION", "").strip()
        or os.getenv("GOOGLE_CLOUD_REGION", "").strip()
        or "us-central1"
    )


def adc_path() -> Path | None:
    explicit = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if explicit:
        path = Path(explicit)
        return path if path.is_file() else None
    if os.name == "nt":
        well_known = Path(os.environ.get("APPDATA", "")) / "gcloud" / "application_default_credentials.json"
    else:
        well_known = Path.home() / ".config" / "gcloud" / "application_default_credentials.json"
    return well_known if well_known.is_file() else None


def _gcloud_executable() -> str | None:
    found = shutil.which("gcloud") or shutil.which("gcloud.cmd")
    if found:
        return found
    if os.name == "nt":
        guess = (
            Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
            / "Google"
            / "Cloud SDK"
            / "google-cloud-sdk"
            / "bin"
            / "gcloud.cmd"
        )
        if guess.is_file():
            return str(guess)
    return None


def _gcloud_config_project() -> str:
    exe = _gcloud_executable()
    if not exe:
        return ""
    try:
        completed = subprocess.run(
            [exe, "config", "get-value", "project"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    value = (completed.stdout or "").strip()
    if not value or value == "(unset)":
        return ""
    return value


def _adc_project() -> str:
    path = adc_path()
    if path is None:
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    if not isinstance(data, dict):
        return ""
    for key in ("quota_project_id", "project_id", "project"):
        value = str(data.get(key) or "").strip()
        if value:
            return value
    return ""


@functools.lru_cache(maxsize=1)
def cloud_project() -> str:
    return (
        os.getenv("GOOGLE_CLOUD_PROJECT", "").strip()
        or os.getenv("GCLOUD_PROJECT", "").strip()
        or os.getenv("GOOGLE_CLOUD_PROJECT_ID", "").strip()
        or _adc_project()
        or _gcloud_config_project()
    )


def on_gcp_runtime() -> bool:
    """Cloud Run / Cloud Functions attach ADC via the metadata server, not a JSON file."""

    return bool(
        os.getenv("K_SERVICE", "").strip()
        or os.getenv("K_REVISION", "").strip()
        or os.getenv("FUNCTION_TARGET", "").strip()
        or os.getenv("CLOUD_RUN_JOB", "").strip()
    )


def adc_available() -> bool:
    """True when Python can use Application Default Credentials.

    Prefers an on-disk ADC JSON so local `gcloud auth application-default`
    is detected without probing the metadata server (that probe can hang
    off-GCP). Cloud Run sets K_SERVICE and uses the runtime service account.
    """

    return adc_path() is not None or on_gcp_runtime()


def gemini_auth_mode() -> AuthMode:
    if force_vertex():
        return "vertex_adc" if cloud_project() and adc_available() else "none"
    if api_key():
        return "api_key"
    if cloud_project() and adc_available():
        return "vertex_adc"
    return "none"


def gemini_configured() -> bool:
    return gemini_auth_mode() != "none"


AUTH_HELP = (
    "Gemini is not authenticated. Either set GEMINI_API_KEY, or use Google Cloud:\n"
    "  gcloud auth login --update-adc\n"
    "  gcloud config set project YOUR_GCP_PROJECT"
)


def make_genai_client() -> Any:
    """Build a google-genai Client using an API key or Vertex ADC."""

    mode = gemini_auth_mode()
    if mode == "api_key":
        from google import genai

        return genai.Client(api_key=api_key())
    if mode == "vertex_adc":
        from google import genai

        project = cloud_project()
        return genai.Client(
            vertexai=True,
            project=project,
            location=cloud_location(),
        )
    if cloud_project() and adc_path() is None:
        raise RuntimeError(
            "gcloud project is set but Application Default Credentials are missing. "
            "User login alone is not enough for Python. Run:\n"
            "  gcloud auth login --update-adc"
        )
    raise RuntimeError(AUTH_HELP)


def clear_auth_cache() -> None:
    cloud_project.cache_clear()
