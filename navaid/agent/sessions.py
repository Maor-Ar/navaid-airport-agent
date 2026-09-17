"""DuckDB session memory for follow-up reconstruction."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import duckdb

from navaid.agent.jsonutil import jsonable
from navaid.warehouse.db import init_schema


def new_session_id() -> str:
    return str(uuid4())


@dataclass
class SessionMemory:
    session_id: str
    turns: list[dict[str, Any]] = field(default_factory=list)
    last_entities: list[str] = field(default_factory=list)
    last_peer_set: list[str] = field(default_factory=list)
    last_payloads: dict[str, Any] = field(default_factory=dict)
    last_traces: list[dict[str, Any]] = field(default_factory=list)
    last_intent: str | None = None

    def remember(
        self,
        *,
        question: str,
        reconstructed_query: str,
        entities: list[str],
        peer_set: list[str] | None = None,
        payloads: dict[str, Any] | None = None,
        traces: list[Any] | None = None,
        intent: str | None = None,
    ) -> None:
        self.turns.append(
            {
                "question": question,
                "reconstructed_query": reconstructed_query,
                "entities": list(entities),
            }
        )
        if entities:
            self.last_entities = [code.strip().upper() for code in entities]
        if peer_set:
            self.last_peer_set = [code.strip().upper() for code in peer_set]
        if payloads:
            merged = dict(self.last_payloads)
            merged.update(jsonable(payloads))
            self.last_payloads = merged
        if traces:
            self.last_traces = jsonable(traces)
        if intent:
            self.last_intent = intent


def load_session(con: duckdb.DuckDBPyConnection, session_id: str | None) -> SessionMemory:
    sid = (session_id or "").strip() or new_session_id()
    init_schema(con)
    row = con.execute(
        """
        SELECT turns, last_entities, last_payloads, last_traces
        FROM sessions WHERE session_id = ?
        """,
        [sid],
    ).fetchone()
    if row is None:
        return SessionMemory(session_id=sid)
    turns = _loads(row[0], [])
    entities_blob = _loads(row[1], {})
    payloads = _loads(row[2], {})
    traces = _loads(row[3], [])
    if isinstance(entities_blob, dict):
        last_entities = list(entities_blob.get("airports") or entities_blob.get("last_entities") or [])
        last_peer_set = list(entities_blob.get("peer_set") or [])
        last_intent = entities_blob.get("intent")
    elif isinstance(entities_blob, list):
        last_entities = list(entities_blob)
        last_peer_set = []
        last_intent = None
    else:
        last_entities, last_peer_set, last_intent = [], [], None
    return SessionMemory(
        session_id=sid,
        turns=list(turns) if isinstance(turns, list) else [],
        last_entities=[str(c).upper() for c in last_entities],
        last_peer_set=[str(c).upper() for c in last_peer_set],
        last_payloads=dict(payloads) if isinstance(payloads, dict) else {},
        last_traces=list(traces) if isinstance(traces, list) else [],
        last_intent=str(last_intent) if last_intent else None,
    )


def save_session(con: duckdb.DuckDBPyConnection, memory: SessionMemory) -> None:
    init_schema(con)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    entities = json.dumps(
        {
            "airports": memory.last_entities,
            "peer_set": memory.last_peer_set,
            "intent": memory.last_intent,
        }
    )
    existing = con.execute(
        "SELECT created_at FROM sessions WHERE session_id = ?",
        [memory.session_id],
    ).fetchone()
    created = existing[0] if existing else now
    payload = [
        memory.session_id,
        created,
        now,
        json.dumps(jsonable(memory.turns)),
        entities,
        json.dumps(jsonable(memory.last_payloads)),
        json.dumps(jsonable(memory.last_traces)),
    ]
    if existing:
        con.execute(
            """
            UPDATE sessions SET
              updated_at = ?,
              turns = ?,
              last_entities = ?,
              last_payloads = ?,
              last_traces = ?
            WHERE session_id = ?
            """,
            [now, payload[3], payload[4], payload[5], payload[6], memory.session_id],
        )
    else:
        con.execute(
            """
            INSERT INTO sessions (
              session_id, created_at, updated_at, turns, last_entities, last_payloads, last_traces
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            payload,
        )


def _loads(raw: Any, default: Any) -> Any:
    if raw is None:
        return default
    if isinstance(raw, (dict, list)):
        return raw
    text = str(raw).strip()
    if not text:
        return default
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return default
