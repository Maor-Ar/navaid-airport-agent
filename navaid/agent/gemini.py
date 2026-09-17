"""google-genai client with automatic function calling disabled.

Manual tool loop so we intercept every call for TEOI traces and the number lock.
Pin google-genai<3 (declared in pyproject). Not LangChain.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from navaid.agent.tools import TOOL_SCHEMAS, ToolContext, call_tool
from navaid.config import NAVAID_MODEL
from navaid.gemini_client import AUTH_HELP, gemini_configured, make_genai_client

MAX_TOOL_ROUNDS = 8

SYSTEM_INSTRUCTION = """You are Navaid, a US airport-investment analyst.
Deterministic engines already computed every number in the tool JSON.
You may explain a TEOI rank; you may never produce one.
Every digit you write must appear in the tool JSON or traces.
RAG never ranks. If notes and T-100 disagree, T-100 wins.
Produce one section per subgoal. If a subgoal is UNSUPPORTED, refuse only that part.
Do not invent gates, scores, percents, or ranks.
Live FAA status is operations delay overlay, not passenger demand.
Write section bodies in Markdown: short ##/### headings, **bold** key names, and numbered or bullet lists. Do not dump one giant paragraph.
If you are explaining a TEOI, use the teoi and peer_set on the traces. Never re-score an airport alone when traces already include a peer set.
"""


@dataclass
class FunctionCall:
    name: str
    arguments: dict[str, Any]
    id: str | None = None


@dataclass
class GeminiTurn:
    text: str
    function_calls: list[FunctionCall] = field(default_factory=list)
    raw: Any = None


class GeminiRuntime:
    """Thin wrapper around google-genai. Tests inject a stub with the same methods."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        client: Any = None,
    ) -> None:
        self.api_key = api_key
        self.model = model or NAVAID_MODEL
        self._client: Any = client

    @property
    def available(self) -> bool:
        if self._client is not None:
            return True
        if self.api_key:
            return True
        return gemini_configured()

    def _client_or_raise(self) -> Any:
        if self._client is None:
            if self.api_key:
                from google import genai

                self._client = genai.Client(api_key=self.api_key)
            else:
                try:
                    self._client = make_genai_client()
                except RuntimeError as exc:
                    raise RuntimeError(str(exc) or AUTH_HELP) from exc
        return self._client

    def generate(
        self,
        contents: list[Any],
        *,
        system: str = SYSTEM_INSTRUCTION,
        enable_tools: bool = True,
    ) -> GeminiTurn:
        from google.genai import types

        decls = [
            types.FunctionDeclaration(
                name=spec["name"],
                description=spec["description"],
                parameters_json_schema=spec["parameters"],
            )
            for spec in TOOL_SCHEMAS
        ]
        config_kwargs: dict[str, Any] = {
            "system_instruction": system,
            "automatic_function_calling": types.AutomaticFunctionCallingConfig(disable=True),
            "temperature": 0.2,
        }
        if enable_tools:
            config_kwargs["tools"] = [types.Tool(function_declarations=decls)]
        config = types.GenerateContentConfig(**config_kwargs)
        response = self._client_or_raise().models.generate_content(
            model=self.model,
            contents=contents,
            config=config,
        )
        return _parse_turn(response)


def _parse_turn(response: Any) -> GeminiTurn:
    text_parts: list[str] = []
    calls: list[FunctionCall] = []
    candidates = getattr(response, "candidates", None) or []
    for cand in candidates:
        content = getattr(cand, "content", None)
        parts = getattr(content, "parts", None) or []
        for part in parts:
            fc = getattr(part, "function_call", None)
            if fc and getattr(fc, "name", None):
                args = dict(getattr(fc, "args", None) or {})
                calls.append(FunctionCall(name=str(fc.name), arguments=args))
                continue
            piece = getattr(part, "text", None)
            if piece:
                text_parts.append(str(piece))
    text = "".join(text_parts).strip()
    if not text and not calls:
        text = str(getattr(response, "text", "") or "").strip()
    return GeminiTurn(text=text, function_calls=calls, raw=response)


def run_tool_loop(
    runtime: GeminiRuntime,
    prompt: str,
    ctx: ToolContext,
    *,
    prior_payloads: list[dict[str, Any]] | None = None,
) -> tuple[str, list[dict[str, Any]], list[str]]:
    """Manual function-calling loop. Returns (final_text, new_payloads, step_details)."""

    from google.genai import types

    payloads: list[dict[str, Any]] = list(prior_payloads or [])
    steps: list[str] = []
    contents: list[Any] = [
        types.Content(role="user", parts=[types.Part.from_text(text=prompt)]),
    ]
    text = ""
    for round_i in range(MAX_TOOL_ROUNDS):
        turn = runtime.generate(contents, enable_tools=True)
        if not turn.function_calls:
            text = turn.text
            steps.append(f"gemini round {round_i + 1}: final text ({len(text)} chars)")
            break
        raw = turn.raw
        model_content = None
        if raw is not None and getattr(raw, "candidates", None):
            model_content = raw.candidates[0].content
        if model_content is not None:
            contents.append(model_content)
        response_parts = []
        for call in turn.function_calls:
            steps.append(f"gemini requested {call.name}({sorted(call.arguments)})")
            result = call_tool(ctx, call.name, call.arguments)
            payloads.append({"tool": call.name, "arguments": call.arguments, "result": result})
            response_parts.append(
                types.Part.from_function_response(name=call.name, response={"result": result})
            )
        contents.append(types.Content(role="user", parts=response_parts))
    else:
        text = text or "Tool loop reached the round limit without a final narration."
        steps.append("gemini tool loop exhausted")
    return text, payloads, steps
