"""Offline RAG tests: DuckDB FTS + airport-keyed notes, no Gemini, no HTTP."""

from __future__ import annotations

from datetime import date

import duckdb
import pytest

from navaid.rag import load_notes, parse_note_markdown, search_corpus
from navaid.rag.loader import default_note_paths
from navaid.rag.types import RetrievedChunk


@pytest.fixture
def rag_con() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(":memory:")
    n = load_notes(con)
    assert n >= 10
    yield con
    con.close()


def test_default_note_files_exist() -> None:
    paths = default_note_paths()
    names = {p.name for p in paths}
    assert "qualitative_notes.md" in names
    assert "lax_sna.md" in names
    assert "anc.md" in names
    assert "new_england.md" in names


def test_loader_parses_front_matter_and_expands_airports() -> None:
    text = """
# preamble

---
id: lax-sna-compare
airport: LAX, SNA
doc_type: compare_note
as_of: 2026-09-01
url: https://www.ocair.com/
title: LAX vs SNA curfew
---

SNA is curfew-capped. LAX wins delay volume.
"""
    chunks = parse_note_markdown(text)
    assert {c["airport"] for c in chunks} == {"LAX", "SNA"}
    assert {c["chunk_id"] for c in chunks} == {
        "lax-sna-compare::LAX",
        "lax-sna-compare::SNA",
    }
    assert all(c["doc_type"] == "compare_note" for c in chunks)
    assert all(c["as_of"] == date(2026, 9, 1) for c in chunks)
    assert all(c["url"] == "https://www.ocair.com/" for c in chunks)
    assert "curfew" in chunks[0]["body"].lower()


def test_load_notes_into_temp_file(tmp_path) -> None:
    db_path = tmp_path / "navaid.duckdb"
    n = load_notes(db_path)
    assert n >= 10
    con = duckdb.connect(str(db_path))
    try:
        count = con.execute("SELECT count(*) FROM doc_chunks").fetchone()[0]
        airports = {
            row[0]
            for row in con.execute(
                "SELECT DISTINCT airport FROM doc_chunks"
            ).fetchall()
        }
    finally:
        con.close()
    assert count == n
    for code in ("SFO", "OAK", "SJC", "LAX", "SNA", "ANC", "BOS", "BDL", "PVD", "PWM", "MHT"):
        assert code in airports


def test_sfo_leakage_oak_sjc(rag_con) -> None:
    hits = search_corpus("leakage OAK SJC", airport="SFO", db=rag_con)
    assert hits
    blob = " ".join(h.body for h in hits).upper()
    assert "OAK" in blob and "SJC" in blob
    assert all(h.airport == "SFO" for h in hits)
    assert all({"airport", "doc_type", "as_of", "url"} <= h.metadata().keys() for h in hits)


def test_sfo_slot_curfew_airside(rag_con) -> None:
    hits = search_corpus("slot curfew airside", airport="SFO", db=rag_con)
    assert hits
    blob = " ".join(h.body.lower() for h in hits)
    assert "slot" in blob
    assert "curfew" in blob
    assert "airside" in blob


def test_sna_curfew_vs_lax(rag_con) -> None:
    sna = search_corpus("curfew", airport="SNA", db=rag_con)
    assert sna
    assert all(h.airport == "SNA" for h in sna)
    assert any("curfew" in h.body.lower() for h in sna)

    lax = search_corpus("delay volume", airport="LAX", db=rag_con)
    assert lax
    assert any("delay" in h.body.lower() for h in lax)


def test_anc_longhaul_cargo_vs_passenger(rag_con) -> None:
    hits = search_corpus("long-haul cargo passenger", airport="ANC", db=rag_con)
    assert hits
    assert all(h.airport == "ANC" for h in hits)
    blob = " ".join(h.body.lower() for h in hits)
    assert "cargo" in blob
    assert "passenger" in blob
    assert "4000" in blob or "long-haul" in blob or "long haul" in blob


def test_new_england_bos_scale_vs_landside_regionals(rag_con) -> None:
    bdl = search_corpus("landside regional", airport="BDL", db=rag_con)
    assert bdl
    assert any("landside" in h.body.lower() for h in bdl)

    bos = search_corpus("scale", airport="BOS", db=rag_con)
    assert bos
    blob = " ".join(h.body.lower() for h in bos)
    assert "scale" in blob
    assert "logan" in blob or "bos" in blob

    for code in ("PVD", "PWM", "MHT"):
        hits = search_corpus("landside", airport=code, db=rag_con)
        assert hits, f"expected landside notes for {code}"
        assert any("landside" in h.body.lower() for h in hits)


def test_airport_filter_excludes_other_airports(rag_con) -> None:
    hits = search_corpus("curfew", airport="SNA", db=rag_con)
    assert hits
    assert {h.airport for h in hits} == {"SNA"}


def test_fts_without_airport_filter(rag_con) -> None:
    hits = search_corpus("curfew", airport=None, db=rag_con)
    airports = {h.airport for h in hits}
    assert "SNA" in airports or "SFO" in airports


def test_airport_only_when_query_empty(rag_con) -> None:
    hits = search_corpus("", airport="ANC", db=rag_con)
    assert hits
    assert {h.airport for h in hits} == {"ANC"}


def test_empty_query_and_airport_returns_nothing(rag_con) -> None:
    assert search_corpus("", airport=None, db=rag_con) == []
    assert search_corpus("   ", airport="", db=rag_con) == []


def test_rag_returns_text_chunks_and_sources_never_rank_or_teoi(rag_con) -> None:
    hits = search_corpus("leakage", airport="SFO", db=rag_con)
    assert hits
    for hit in hits:
        assert isinstance(hit, RetrievedChunk)
        assert hit.body
        assert not hasattr(hit, "rank")
        assert not hasattr(hit, "teoi")
        payload = hit.as_payload()
        assert "text" in payload
        assert payload["sources"]
        assert payload["metadata"]["airport"] == "SFO"
        assert payload["metadata"]["doc_type"]
        keys = set(payload) | set(payload["metadata"]) | set(payload["sources"][0])
        lowered = {k.lower() for k in keys}
        assert "rank" not in lowered
        assert "teoi" not in lowered
        assert "teoi_traces" not in lowered


def test_seeded_notes_do_not_embed_teoi_numbers() -> None:
    for path in default_note_paths():
        text = path.read_text(encoding="utf-8").lower()
        assert "teoi" not in text
        assert "chroma" not in text
        assert "langchain" not in text
        assert "embedding" not in text


def test_search_empty_database_is_empty() -> None:
    con = duckdb.connect(":memory:")
    try:
        assert search_corpus("leakage", airport="SFO", db=con) == []
    finally:
        con.close()


def test_pwm_is_portland_maine(rag_con) -> None:
    hits = search_corpus("Portland Maine PDX", airport="PWM", db=rag_con)
    assert hits
    blob = " ".join(h.body for h in hits)
    assert "Maine" in blob or "maine" in blob.lower()
    assert "PDX" in blob
