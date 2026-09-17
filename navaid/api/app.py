"""FastAPI app: POST /ask, GET /health, GET /eval/summary from latest gold run."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from navaid.agent.orchestrator import ask as run_ask
from navaid.agent.sessions import new_session_id
from navaid.config import (
    CORS_ORIGIN_REGEX,
    NAVAID_MODEL,
    PROJECT_ROOT,
    WAREHOUSE_PATH,
    cors_allow_origins,
)
from navaid.gemini_client import gemini_auth_mode, gemini_configured
from navaid.warehouse.metrics import SnapshotMissingError

EVAL_RUNS_DIR = PROJECT_ROOT / "eval" / "runs"


class AskRequest(BaseModel):
    question: str
    session_id: str | None = None
    use_gemini: bool | None = Field(
        default=None,
        description="Override Gemini narration. Default follows API key or gcloud ADC.",
    )


class SpeakRequest(BaseModel):
    text: str = Field(..., min_length=1, description="Plain answer text to speak.")


def create_app() -> FastAPI:
    app = FastAPI(title="Navaid", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_allow_origins(),
        allow_origin_regex=CORS_ORIGIN_REGEX or None,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "model": NAVAID_MODEL,
            "warehouse": WAREHOUSE_PATH.is_file(),
            "gemini_configured": gemini_configured(),
            "gemini_auth": gemini_auth_mode(),
            "tts": gemini_configured(),
        }

    @app.get("/eval/summary")
    def eval_summary() -> dict[str, Any]:
        return load_eval_summary()

    @app.post("/ask")
    def ask_endpoint(
        body: AskRequest,
        x_session_id: str | None = Header(default=None, alias="X-Session-Id"),
    ) -> JSONResponse:
        session_id = body.session_id or x_session_id or new_session_id()
        try:
            answer = run_ask(
                body.question,
                session_id=session_id,
                use_gemini=body.use_gemini,
            )
        except SnapshotMissingError as exc:
            return JSONResponse(status_code=503, content={"error": str(exc)})
        except ValueError as exc:
            return JSONResponse(status_code=400, content={"error": str(exc)})
        payload = answer.model_dump(mode="json")
        return JSONResponse(content=payload, headers={"X-Session-Id": session_id})

    @app.post("/speak")
    def speak_endpoint(body: SpeakRequest) -> Response:
        from navaid.ui.voice import synthesize_wav_bytes

        spoken = (body.text or "").strip()
        if not spoken:
            return JSONResponse(status_code=400, content={"error": "Nothing to speak."})
        data, note = synthesize_wav_bytes(spoken)
        if not data:
            return JSONResponse(status_code=503, content={"error": note, "fallback": "browser"})
        headers = {"X-TTS-Note": note, "Cache-Control": "no-store"}
        return Response(content=data, media_type="audio/wav", headers=headers)

    from navaid.api.site import mount_site

    mount_site(app)
    return app


def _latest_eval_run(runs_dir: Path | None = None) -> Path | None:
    directory = runs_dir or EVAL_RUNS_DIR
    latest = directory / "latest.json"
    if latest.is_file():
        return latest
    files = [p for p in directory.glob("*.json") if p.is_file()]
    if not files:
        return None
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0]


def load_eval_summary(runs_dir: Path | None = None) -> dict[str, Any]:
    """Read KPIs from the newest gold-eval JSON (eval/runs/latest.json)."""

    path = _latest_eval_run(runs_dir)
    if path is None:
        return {
            "status": "no_runs",
            "message": "No eval runs yet. python eval/run_eval.py",
        }
    data = json.loads(path.read_text(encoding="utf-8"))
    kpis = data.get("kpis") or {}
    return {
        "status": "ok",
        "run_path": str(path),
        "created_at": data.get("created_at"),
        "use_gemini": data.get("use_gemini"),
        "item_count": data.get("item_count"),
        "kpis": kpis,
        "failed_ids": data.get("failed_ids") or [],
        "pass_rate": kpis.get("pass_rate"),
    }


app = create_app()
