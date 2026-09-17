"""Console entrypoint: `navaid` / `python -m navaid`.

`navaid ask --json "..."` hits the same orchestrator as FastAPI `/ask`.
"""

from __future__ import annotations

import argparse
import json
import sys

from navaid.agent.sessions import new_session_id


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="navaid",
        description="Navaid - Airport Investment Intelligence Agent",
    )
    sub = parser.add_subparsers(dest="command")

    ask = sub.add_parser(
        "ask",
        help="Ask a question (reconstruct → decompose → engines → number lock)",
        description="Ask the agent. Same orchestrator as POST /ask (not HTTP-only).",
    )
    ask.add_argument(
        "question",
        nargs="?",
        default=None,
        help="Standalone or follow-up question",
    )
    ask.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Print structured Answer JSON",
    )
    ask.add_argument(
        "--session",
        dest="session_id",
        default=None,
        help="Session id for follow-ups (DuckDB sessions table)",
    )
    ask.add_argument(
        "--no-gemini",
        action="store_true",
        dest="no_gemini",
        help="Skip Gemini narration (deterministic template from tool JSON)",
    )

    ui = sub.add_parser(
        "ui",
        help="Launch the Gradio workbench",
        description=(
            "Gradio workbench over the same orchestrator as POST /ask. "
            "Tabs: Chat, Steps, Rankings, TEOI waterfall, Compare, Citations, Eval."
        ),
    )
    ui.add_argument("--host", default="127.0.0.1")
    ui.add_argument("--port", type=int, default=7860)
    ui.add_argument(
        "--share",
        action="store_true",
        help="Create a temporary Gradio share URL",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "ui":
        from navaid.ui.gradio_app import launch

        launch(host=args.host, port=args.port, share=args.share)
        return 0

    if args.command != "ask":
        parser.print_help()
        return 0

    question = args.question
    if not question:
        print(
            'error: ask requires a question, e.g. navaid ask --json "Which New England airports..."',
            file=sys.stderr,
        )
        return 2

    from navaid.agent.orchestrator import ask
    from navaid.warehouse.metrics import SnapshotMissingError

    session_id = args.session_id or new_session_id()
    try:
        answer = ask(
            question,
            session_id=session_id,
            use_gemini=False if args.no_gemini else None,
        )
    except SnapshotMissingError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"navaid ask failed: {exc}", file=sys.stderr)
        return 1

    print(f"session_id={session_id}", file=sys.stderr)
    if args.as_json:
        json.dump(answer.model_dump(mode="json"), sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(answer.reconstructed_query)
        for section in answer.sections:
            print(f"\n## {section.heading}\n{section.body}")
        if answer.unsupported_parts:
            print("\nUnsupported:")
            for part in answer.unsupported_parts:
                print(f"- {part.text}: {part.reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
