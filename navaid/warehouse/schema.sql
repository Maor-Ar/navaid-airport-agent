-- Navaid DuckDB warehouse DDL (Phase 1 stubs).
-- One file: data/warehouse/navaid.duckdb
-- Metric tables + sessions + doc_chunks. FTS index is created later (rag phase).
-- No embeddings table. Retrieval is airport-keyed + DuckDB FTS, never a vector index.

CREATE TABLE IF NOT EXISTS snapshot_meta (
    as_of DATE NOT NULL,
    content_hash TEXT NOT NULL,
    built_at TIMESTAMP NOT NULL,
    notes TEXT
);

-- OurAirports identity
CREATE TABLE IF NOT EXISTS airports (
    icao TEXT PRIMARY KEY,
    iata TEXT,
    name TEXT,
    municipality TEXT,
    iso_region TEXT,
    iso_country TEXT,
    latitude DOUBLE,
    longitude DOUBLE,
    elevation_ft INTEGER,
    type TEXT,
    as_of DATE
);

CREATE TABLE IF NOT EXISTS runways (
    icao TEXT,
    ident TEXT,
    length_ft INTEGER,
    width_ft INTEGER,
    surface TEXT,
    lighted BOOLEAN,
    closed BOOLEAN
);

-- FAA CY enplanements (hub size, YoY)
CREATE TABLE IF NOT EXISTS enplanements (
    iata TEXT,
    icao TEXT,
    year INTEGER,
    enplanements BIGINT,
    hub_size TEXT,
    yoy DOUBLE,
    as_of DATE
);

-- FAA Terminal Area Forecast (planning TAF, not weather)
CREATE TABLE IF NOT EXISTS taf_forecasts (
    iata TEXT,
    icao TEXT,
    forecast_year INTEGER,
    passengers BIGINT,
    operations BIGINT,
    as_of DATE
);

-- BTS T-100 segment traffic (filtered US commercial; not raw PREZIP)
CREATE TABLE IF NOT EXISTS t100_segments (
    origin TEXT,
    dest TEXT,
    year INTEGER,
    month INTEGER,
    passengers BIGINT,
    seats BIGINT,
    distance_km DOUBLE,
    international BOOLEAN,
    as_of DATE
);

-- BTS airport-month delay/cancel (delay-cause, not flight-level OTP)
CREATE TABLE IF NOT EXISTS delay_cause (
    iata TEXT,
    icao TEXT,
    year INTEGER,
    month INTEGER,
    delay_pct DOUBLE,
    avg_arrival_delay_min DOUBLE,
    cancel_pct DOUBLE,
    operations BIGINT,
    as_of DATE
);

CREATE TABLE IF NOT EXISTS airport_ops (
    iata TEXT,
    icao TEXT,
    year INTEGER,
    operations BIGINT,
    as_of DATE
);

-- NPIAS development need (feasibility, not the rank)
CREATE TABLE IF NOT EXISTS npias (
    iata TEXT,
    icao TEXT,
    development_need TEXT,
    as_of DATE
);

-- AIP grant history
CREATE TABLE IF NOT EXISTS aip_grants (
    iata TEXT,
    icao TEXT,
    year INTEGER,
    amount_usd DOUBLE,
    description TEXT,
    as_of DATE
);

-- Curated fields official files lack
CREATE TABLE IF NOT EXISTS gates (
    iata TEXT,
    icao TEXT,
    gate_count INTEGER,
    as_of DATE,
    source TEXT
);

CREATE TABLE IF NOT EXISTS catchment_cbsa (
    iata TEXT,
    icao TEXT,
    cbsa_code TEXT,
    cbsa_name TEXT,
    as_of DATE
);

CREATE TABLE IF NOT EXISTS constraints (
    iata TEXT,
    icao TEXT,
    constraint_type TEXT,
    curfew TEXT,
    notes TEXT,
    as_of DATE
);

-- Follow-up memory (survives Gradio refresh)
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    turns JSON,
    last_entities JSON,
    last_payloads JSON,
    last_traces JSON
);

-- Airport-keyed notes / master-plan chunks. FTS later; no embedding column.
CREATE TABLE IF NOT EXISTS doc_chunks (
    chunk_id TEXT PRIMARY KEY,
    airport TEXT,
    doc_type TEXT,
    as_of DATE,
    url TEXT,
    title TEXT,
    body TEXT
);

-- Ingest provenance (additive; live vs fixture, as_of, confidence)
CREATE TABLE IF NOT EXISTS ingest_sources (
    source_id TEXT PRIMARY KEY,
    url TEXT,
    local_path TEXT,
    as_of DATE,
    confidence TEXT,
    used_fixture BOOLEAN,
    notes TEXT
);

-- INSTALL fts; LOAD fts;
-- PRAGMA create_fts_index('doc_chunks', 'chunk_id', 'body', 'title');
