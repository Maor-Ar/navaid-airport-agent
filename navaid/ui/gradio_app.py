"""Navaid Gradio workbench over the same ``Answer`` object as FastAPI ``/ask``.

Launch:
    python -m navaid.ui.gradio_app
    navaid ui
"""

from __future__ import annotations

import argparse
from typing import Any

from navaid.agent.sessions import new_session_id
from navaid.config import NAVAID_MODEL
from navaid.gemini_client import gemini_configured
from navaid.schemas import Answer, Confidence, Envelope, ScoringTrace
from navaid.ui.render import (
    chat_reply,
    citations_markdown,
    compare_markdown,
    envelope_html,
    eval_markdown,
    ranking_badges_html,
    ranking_frame,
    steps_markdown,
    waterfall_airports,
    waterfall_html,
    waterfall_markdown,
)
from navaid.ui.voice import gemini_voice_ready, synthesize, transcribe
from navaid.warehouse.metrics import SnapshotMissingError

TAB_CHAT = "Chat"
TAB_STEPS = "Steps"
TAB_RANKINGS = "Rankings"
TAB_WATERFALL = "TEOI waterfall"
TAB_COMPARE = "Compare"
TAB_CITATIONS = "Citations"
TAB_EVAL = "Eval"
TABS = (
    TAB_CHAT,
    TAB_STEPS,
    TAB_RANKINGS,
    TAB_WATERFALL,
    TAB_COMPARE,
    TAB_CITATIONS,
    TAB_EVAL,
)

SAMPLE_QUESTIONS = [
    "Which airports in New England are strong candidates for terminal expansion?",
    "Compare LA and Santa Ana airport congestion levels.",
    "What is the percentage of long haul flights out of Anchorage airport?",
    "What is the unmet flight demand in SFO airport and why?",
    "those two",
    "why is #2 above #3?",
]

CSS = """
.navaid-envelope { display: grid; grid-template-columns: 1.1fr 1fr 1fr 1fr; gap: 10px; margin-bottom: 8px; }
.navaid-card { border: 1px solid #d9e2ec; border-radius: 10px; padding: 10px 12px; background: #f8fafc; min-height: 7.5rem; }
.navaid-card h4 { margin: 0 0 6px; font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em; color: #475569; }
.navaid-card ul { margin: 0; padding-left: 1.1rem; }
.navaid-card li { font-size: 13px; line-height: 1.35; }
.navaid-kpi { font-size: 1.35rem; font-weight: 650; margin: 0 0 6px; text-transform: capitalize; }
.navaid-badge { display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 12px; font-weight: 600; }
.navaid-rank-chips { display: flex; flex-wrap: wrap; gap: 8px; margin: 4px 0 8px; }
.navaid-rank-chip { display: inline-flex; align-items: center; gap: 6px; }
.navaid-muted { color: #64748b; font-size: 13px; }
.navaid-waterfall .navaid-bar-row { display: grid; grid-template-columns: 10rem 1fr 3.5rem; gap: 8px; align-items: center; margin: 4px 0; font-size: 13px; }
.navaid-bar-track { background: #e2e8f0; border-radius: 6px; height: 10px; overflow: hidden; }
.navaid-bar-track.dropped { background: repeating-linear-gradient(-45deg, #e2e8f0, #e2e8f0 4px, #cbd5e1 4px, #cbd5e1 8px); }
.navaid-bar { background: #1d4ed8; height: 10px; border-radius: 6px; }
.navaid-formula { white-space: pre-wrap; font-size: 12px; background: #f1f5f9; padding: 8px; border-radius: 8px; }
@media (max-width: 1100px) {
  .navaid-envelope { grid-template-columns: 1fr 1fr; }
}
"""


def default_tools_only() -> bool:
    """Unchecked when Gemini API key or gcloud ADC is present."""

    return not gemini_configured()


def fetch_eval_summary() -> dict[str, Any]:
    """Hit GET /eval/summary in-process so a later gold runner shows up here."""

    try:
        import httpx

        from navaid.api.app import app

        transport = httpx.ASGITransport(app=app)
        with httpx.Client(transport=transport, base_url="http://navaid.local") as client:
            response = client.get("/eval/summary")
            return response.json()
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


def _blank_answer() -> Answer:
    return Answer(
        reconstructed_query="",
        envelope=Envelope(confidence=Confidence.LOW, sources=[]),
    )


def _ranking_frame(answer: Answer | None):
    import pandas as pd

    if answer is None:
        return pd.DataFrame(columns=["rank", "airport", "icao", "teoi", "constraint"])
    headers, rows = ranking_frame(answer)
    return pd.DataFrame(rows, columns=headers)


def _dropdown(airports: list[str], selected: str | None):
    import gradio as gr

    return gr.update(choices=airports, value=selected)


def _traces(blob: dict[str, Any] | None) -> list[ScoringTrace]:
    if not blob:
        return []
    out: list[ScoringTrace] = []
    for item in blob.get("teoi_traces") or []:
        try:
            out.append(ScoringTrace.model_validate(item))
        except Exception:
            continue
    return out


def ui_tuple(
    *,
    history: list[dict[str, Any]],
    question: str,
    session_id: str,
    answer: Answer | None,
    status: str,
    tts_path: str | None = None,
    answer_blob: dict[str, Any] | None = None,
) -> tuple[Any, ...]:
    """All Gradio outputs for Ask / New session / empty question (same order)."""

    airports = waterfall_airports(answer) if answer else []
    selected = airports[0] if airports else None
    traces = answer.teoi_traces if answer else []
    return (
        history,
        question,
        session_id,
        envelope_html(answer.envelope if answer else None),
        steps_markdown(answer) if answer else "_Ask a question to record reconstruct / tools / number lock._",
        _ranking_frame(answer),
        ranking_badges_html(answer) if answer else "<p>No ranking yet.</p>",
        waterfall_html(traces, selected),
        _dropdown(airports, selected),
        compare_markdown(answer) if answer else compare_markdown(_blank_answer()),
        citations_markdown(answer) if answer else "_No citations yet._",
        eval_markdown(fetch_eval_summary()),
        tts_path,
        status,
        answer_blob if answer_blob is not None else (answer.model_dump(mode="json") if answer else None),
        waterfall_markdown(traces, selected),
    )


def run_turn(
    question: str,
    history: list[dict[str, Any]] | None,
    session_id: str,
    tools_only: bool,
    speak: bool,
):
    history = list(history or [])
    q = (question or "").strip()
    sid = (session_id or "").strip() or new_session_id()
    if not q:
        yield ui_tuple(
            history=history,
            question="",
            session_id=sid,
            answer=None,
            status="Type a question (or transcribe the mic) then Ask.",
        )
        return

    pending = history + [
        {"role": "user", "content": q},
        {
            "role": "assistant",
            "content": "_Working…_ reconstruct → engines → number lock → narrate. This can take a few seconds.",
        },
    ]
    yield ui_tuple(
        history=pending,
        question=q,
        session_id=sid,
        answer=None,
        status="**Working…** Reconstruct, warehouse engines, then narration.",
    )

    from navaid.agent.orchestrator import ask

    use_gemini = False if tools_only else None
    try:
        answer = ask(q, session_id=sid, use_gemini=use_gemini)
    except SnapshotMissingError as exc:
        err = str(exc)
        history.append({"role": "user", "content": q})
        history.append({"role": "assistant", "content": err})
        yield ui_tuple(history=history, question="", session_id=sid, answer=None, status=err)
        return
    except Exception as exc:
        err = f"Ask failed: {exc}"
        history.append({"role": "user", "content": q})
        history.append({"role": "assistant", "content": err})
        yield ui_tuple(history=history, question="", session_id=sid, answer=None, status=err)
        return

    reply = chat_reply(answer)
    history.append({"role": "user", "content": q})
    history.append({"role": "assistant", "content": reply})
    mode = "tools-only" if tools_only or not gemini_configured() else f"Gemini ({NAVAID_MODEL})"
    status = f"session `{sid}` | {mode} | reconstructed: {answer.reconstructed_query}"
    tts_path = None
    if speak:
        spoken = "\n\n".join(section.body for section in answer.sections if section.body)
        tts_path, tts_note = synthesize(spoken)
        status = f"{status} · {tts_note}"
    yield ui_tuple(
        history=history,
        question="",
        session_id=sid,
        answer=answer,
        status=status,
        tts_path=tts_path,
    )


def refresh_waterfall(airport: str | None, answer_blob: dict[str, Any] | None) -> tuple[str, str]:
    traces = _traces(answer_blob)
    return waterfall_html(traces, airport), waterfall_markdown(traces, airport)


def transcribe_mic(audio: Any) -> tuple[str, str]:
    text, note = transcribe(audio)
    return text, note


def start_new_session() -> tuple[Any, ...]:
    sid = new_session_id()
    return ui_tuple(
        history=[],
        question="",
        session_id=sid,
        answer=None,
        status=f"New session `{sid}`. Follow-ups will use this id.",
        answer_blob=None,
    )


def build_app():
    import gradio as gr

    voice_ok = gemini_voice_ready()
    voice_help = (
        "Gemini STT from the mic; optional TTS of the answer. No OpenAI Whisper."
        if voice_ok
        else "No Gemini credentials — set GEMINI_API_KEY or run gcloud auth login --update-adc. Type questions; mic/TTS stay disabled."
    )

    with gr.Blocks(title="Navaid workbench", fill_width=True) as demo:
        answer_state = gr.State(None)
        gr.Markdown(
            f"# Navaid workbench\n"
            f"Airport investment analyst. Same `Answer` object as FastAPI `/ask` "
            f"(in-process orchestrator). Model default: `{NAVAID_MODEL}`."
        )
        with gr.Row():
            session_box = gr.Textbox(
                label="Session id",
                value=new_session_id,
                info="Reuse this id for follow-ups (“those two”, “why #2”).",
                scale=3,
            )
            tools_only = gr.Checkbox(
                label="Tools only (no Gemini narration)",
                value=default_tools_only(),
                info="Sets use_gemini=false. Use when Gemini auth is missing or you want engines-only.",
                scale=2,
            )
            speak = gr.Checkbox(
                label="Speak answers (Gemini TTS)",
                value=False,
                info="Falls back to text if TTS is unavailable.",
                scale=2,
            )
            new_btn = gr.Button("New session", scale=1)
        envelope_panel = gr.HTML(value=envelope_html(None), label="Envelope")
        status = gr.Markdown(value="Ask a question. Envelope stays visible on every tab.")

        with gr.Tabs():
            with gr.Tab(TAB_CHAT):
                chatbot = gr.Chatbot(
                    label="Conversation",
                    height=420,
                    type="messages",
                    placeholder="Ask about expansion rank, congestion, long-haul, or unmet demand.",
                    feedback_options=None,
                )
                question = gr.Textbox(
                    label="Question",
                    placeholder="Which airports in New England are strong candidates for terminal expansion?",
                    lines=2,
                    submit_btn="Ask",
                )
                ask_btn = gr.Button("Ask", variant="primary")
                gr.Examples(examples=[[q] for q in SAMPLE_QUESTIONS], inputs=question)
                with gr.Row():
                    mic = gr.Audio(
                        sources=["microphone", "upload"],
                        type="filepath",
                        label="Voice (Gemini STT)",
                        scale=3,
                    )
                    transcribe_btn = gr.Button("Transcribe mic", scale=1)
                voice_status = gr.Markdown(voice_help)
                tts_audio = gr.Audio(label="Spoken answer", type="filepath", interactive=False)
            with gr.Tab(TAB_STEPS):
                steps_md = gr.Markdown("_Steps appear after a turn (reconstruct, tools, number lock)._")
            with gr.Tab(TAB_RANKINGS):
                ranking_badges = gr.HTML("<p>Constraint badges appear with a TEOI ranking.</p>")
                ranking_table = gr.Dataframe(
                    headers=["rank", "airport", "icao", "teoi", "constraint"],
                    label="TEOI ranking",
                    interactive=False,
                    wrap=True,
                )
            with gr.Tab(TAB_WATERFALL):
                waterfall_pick = gr.Dropdown(
                    label="Airport trace",
                    choices=[],
                    value=None,
                    interactive=True,
                )
                waterfall_view = gr.HTML(
                    value="<p>Waterfall: raw → scaled → weights → contributions → multiplier → score → rank.</p>"
                )
                waterfall_md = gr.Markdown(
                    "_Full arithmetic from ScoringTrace. Gemini may narrate this; it may not invent a rank._"
                )
            with gr.Tab(TAB_COMPARE):
                compare_md = gr.Markdown(
                    "Two-airport congestion compare (LAX vs SNA style). "
                    "Ask: Compare LA and Santa Ana airport congestion levels."
                )
            with gr.Tab(TAB_CITATIONS):
                citations_md = gr.Markdown("_Citations and envelope sources._")
            with gr.Tab(TAB_EVAL):
                eval_md = gr.Markdown(eval_markdown(fetch_eval_summary()))
                refresh_eval = gr.Button("Refresh /eval/summary")

        outputs = [
            chatbot,
            question,
            session_box,
            envelope_panel,
            steps_md,
            ranking_table,
            ranking_badges,
            waterfall_view,
            waterfall_pick,
            compare_md,
            citations_md,
            eval_md,
            tts_audio,
            status,
            answer_state,
            waterfall_md,
        ]
        question.submit(
            run_turn,
            inputs=[question, chatbot, session_box, tools_only, speak],
            outputs=outputs,
            show_progress="full",
        )
        ask_btn.click(
            run_turn,
            inputs=[question, chatbot, session_box, tools_only, speak],
            outputs=outputs,
            show_progress="full",
        )
        transcribe_btn.click(transcribe_mic, inputs=[mic], outputs=[question, voice_status])
        new_btn.click(start_new_session, inputs=None, outputs=outputs)
        waterfall_pick.change(
            refresh_waterfall,
            inputs=[waterfall_pick, answer_state],
            outputs=[waterfall_view, waterfall_md],
        )
        refresh_eval.click(lambda: eval_markdown(fetch_eval_summary()), outputs=[eval_md])

    return demo


def launch(*, host: str = "127.0.0.1", port: int = 7860, share: bool = False, **kwargs) -> None:
    import gradio as gr

    demo = build_app()
    demo.queue()
    demo.launch(
        server_name=host,
        server_port=port,
        share=share,
        theme=gr.themes.Soft(),
        css=CSS,
        show_error=True,
        **kwargs,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="navaid ui",
        description=(
            "Launch the Navaid Gradio workbench "
            "(Chat, Steps, Rankings, TEOI waterfall, Compare, Citations, Eval)."
        ),
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7860)
    parser.add_argument("--share", action="store_true", help="Create a temporary Gradio share URL")
    args = parser.parse_args(argv)
    launch(host=args.host, port=args.port, share=args.share)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
