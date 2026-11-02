-- ============================================================================
-- Polish Economy Agent — SQLite Schema v2 Proposal (DDL)
-- Branch: design/03-data-contract
-- Cel: Standaryzacja katalogu wskaźników, źródeł, wersjonowanych obserwacji,
--      dowodów, kandydatów ekstrakcji, audytu jakości i migracji legacy.
-- ============================================================================

PRAGMA foreign_keys = ON;

-- ----------------------------------------------------------------------------
-- 1. REJESTR ŹRÓDEŁ DANYCH (source_registry)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS source_registry (
    source_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    institution TEXT NOT NULL,
    base_url TEXT NOT NULL,
    source_type TEXT NOT NULL CHECK(source_type IN (
        'API_REST', 'API_SDMX', 'STATIC_XML', 'STATIC_HTML', 'WEB_SEARCH', 'MANUAL_ENTRY'
    )),
    trust_tier TEXT NOT NULL CHECK(trust_tier IN (
        'TIER_A', 'TIER_B', 'TIER_C', 'TIER_D'
    )),
    auth_type TEXT NOT NULL DEFAULT 'NONE' CHECK(auth_type IN (
        'NONE', 'API_KEY_HEADER', 'BEARER_TOKEN', 'QUERY_PARAM'
    )),
    rate_limit_info TEXT,
    documentation_url TEXT,
    created_at_utc TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ----------------------------------------------------------------------------
-- 2. KATALOG WSKAŹNIKÓW MAKROEKONOMICZNYCH (indicator_catalog)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS indicator_catalog (
    indicator_code TEXT PRIMARY KEY,
    name_pl TEXT NOT NULL,
    name_en TEXT,
    definition_pl TEXT NOT NULL,
    methodology_notes TEXT,
    frequency TEXT NOT NULL CHECK(frequency IN (
        'DAILY', 'MONTHLY', 'QUARTERLY', 'ANNUAL', 'IRREGULAR'
    )),
    unit_code TEXT NOT NULL CHECK(unit_code IN (
        'PCT', 'THOUSAND_PERSONS', 'PLN', 'PLN_PER_MONTH', 'INDEX_POINTS', 'EUR_PLN', 'USD_PLN', 'COUNT'
    )),
    decimal_precision INTEGER NOT NULL DEFAULT 2,
    min_plausible_value TEXT,
    max_plausible_value TEXT,
    preferred_source_id TEXT REFERENCES source_registry(source_id),
    is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1)),
    created_at_utc TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ----------------------------------------------------------------------------
-- 3. SŁOWNIK ALIASÓW WSKAŹNIKÓW (indicator_aliases)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS indicator_aliases (
    alias_id INTEGER PRIMARY KEY AUTOINCREMENT,
    indicator_code TEXT NOT NULL REFERENCES indicator_catalog(indicator_code) ON DELETE CASCADE,
    raw_alias TEXT NOT NULL,
    normalized_alias TEXT NOT NULL,
    match_type TEXT NOT NULL CHECK(match_type IN ('EXACT', 'REGEX', 'NORMALIZED')),
    is_disambiguated INTEGER NOT NULL DEFAULT 1 CHECK(is_disambiguated IN (0, 1)),
    notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_indicator_aliases_norm ON indicator_aliases(normalized_alias);

-- ----------------------------------------------------------------------------
-- 4. SERIE DANYCH API / ŹRÓDEŁ (data_series)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS data_series (
    series_id TEXT PRIMARY KEY,
    indicator_code TEXT NOT NULL REFERENCES indicator_catalog(indicator_code),
    source_id TEXT NOT NULL REFERENCES source_registry(source_id),
    external_series_id TEXT NOT NULL,
    endpoint_url TEXT NOT NULL,
    query_params_template TEXT,
    response_format TEXT NOT NULL CHECK(response_format IN ('JSON', 'JSON_STAT', 'XML', 'HTML', 'CSV')),
    verification_status TEXT NOT NULL CHECK(verification_status IN (
        'VERIFIED', 'NOT_VERIFIED', 'REQUIRES_VARIABLE_MAPPING', 'VERIFIED_STATIC_XML'
    )),
    is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1)),
    created_at_utc TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ----------------------------------------------------------------------------
-- 5. PRZEBIEGI POBIERANIA DANYCH (ingestion_runs)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ingestion_runs (
    run_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    run_type TEXT NOT NULL CHECK(run_type IN ('SCHEDULED', 'MANUAL', 'MIGRATION', 'FALLBACK')),
    started_at_utc TIMESTAMP NOT NULL,
    ended_at_utc TIMESTAMP,
    status TEXT NOT NULL CHECK(status IN ('STARTED', 'COMPLETED', 'FAILED', 'PARTIAL')),
    records_extracted INTEGER DEFAULT 0,
    records_validated INTEGER DEFAULT 0,
    error_message TEXT
);

-- ----------------------------------------------------------------------------
-- 6. DOWODY ŹRÓDŁOWE / RAW EVIDENCE (source_evidence)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS source_evidence (
    evidence_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES ingestion_runs(run_id),
    source_id TEXT NOT NULL REFERENCES source_registry(source_id),
    source_url TEXT NOT NULL,
    document_type TEXT NOT NULL CHECK(document_type IN (
        'API_RESPONSE', 'OFFICIAL_ANNOUNCEMENT', 'PRESS_ARTICLE', 'WEB_SNIPPET', 'LEGACY_IMPORT'
    )),
    content_hash TEXT NOT NULL,
    content_preview TEXT,
    published_at_utc TIMESTAMP,
    retrieved_at_utc TIMESTAMP NOT NULL,
    licensing_tier TEXT NOT NULL DEFAULT 'OPEN_DATA' CHECK(licensing_tier IN (
        'OPEN_DATA', 'PUBLIC_FAIR_USE', 'RESTRICTED'
    ))
);

CREATE INDEX IF NOT EXISTS idx_source_evidence_hash ON source_evidence(content_hash);
CREATE INDEX IF NOT EXISTS idx_source_evidence_run ON source_evidence(run_id);

-- ----------------------------------------------------------------------------
-- 7. KANDYDACI EKSTRAKCJI Z AGENTÓW I PARSERÓW (extracted_candidates)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS extracted_candidates (
    candidate_id TEXT PRIMARY KEY,
    evidence_id TEXT NOT NULL REFERENCES source_evidence(evidence_id),
    run_id TEXT NOT NULL REFERENCES ingestion_runs(run_id),
    agent_name TEXT NOT NULL,
    raw_indicator_name TEXT NOT NULL,
    raw_value TEXT NOT NULL,
    raw_period TEXT NOT NULL,
    candidate_indicator_code TEXT REFERENCES indicator_catalog(indicator_code),
    candidate_value_decimal TEXT,
    candidate_period_start TEXT,
    candidate_period_end TEXT,
    candidate_frequency TEXT,
    extraction_confidence REAL,
    extraction_notes TEXT,
    extracted_at_utc TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_candidates_code ON extracted_candidates(candidate_indicator_code);
CREATE INDEX IF NOT EXISTS idx_candidates_evidence ON extracted_candidates(evidence_id);

-- ----------------------------------------------------------------------------
-- 8. WERSJONOWANE OBSERWACJE EKONOMICZNE (observations) - STRICTLY APPEND-ONLY
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS observations (
    observation_id TEXT PRIMARY KEY,
    indicator_code TEXT NOT NULL REFERENCES indicator_catalog(indicator_code),
    country_code TEXT NOT NULL DEFAULT 'PL',
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    frequency TEXT NOT NULL CHECK(frequency IN (
        'DAILY', 'MONTHLY', 'QUARTERLY', 'ANNUAL', 'IRREGULAR'
    )),
    value_decimal TEXT NOT NULL,
    unit_code TEXT NOT NULL,
    revision_type TEXT NOT NULL DEFAULT 'FINAL' CHECK(revision_type IN (
        'FLASH', 'PRELIMINARY', 'FINAL', 'REVISED', 'LEGACY_UNSPECIFIED'
    )),
    version_number INTEGER NOT NULL DEFAULT 1,
    supersedes_id TEXT REFERENCES observations(observation_id),
    evidence_id TEXT NOT NULL REFERENCES source_evidence(evidence_id),
    status TEXT NOT NULL CHECK(status IN (
        'VERIFIED', 'PENDING', 'CONFLICT', 'REJECTED', 'SUPERSEDED'
    )),
    observed_at_utc TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    validated_at_utc TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_obs_indicator_period ON observations(indicator_code, period_start);
CREATE INDEX IF NOT EXISTS idx_obs_status ON observations(indicator_code, status);
CREATE INDEX IF NOT EXISTS idx_obs_evidence ON observations(evidence_id);

-- TRIGGERS: Egzekwowanie bezwzględnego braku mutacji w observations (STRICT APPEND-ONLY)
CREATE TRIGGER IF NOT EXISTS trg_observations_prevent_update
BEFORE UPDATE ON observations
BEGIN
    SELECT RAISE(FAIL, 'Tabela observations jest bezwzglednie append-only: modyfikacja (UPDATE) jest zablokowana.');
END;

CREATE TRIGGER IF NOT EXISTS trg_observations_prevent_delete
BEFORE DELETE ON observations
BEGIN
    SELECT RAISE(FAIL, 'Tabela observations jest bezwzglednie append-only: usuwanie (DELETE) jest zablokowane.');
END;

-- ----------------------------------------------------------------------------
-- 9. TABELA WSKAŹNIKÓW AKTUALNEJ WERSJI (current_observations)
--    Odrębny mechanizm ustalania aktualnej wersji bez modyfikacji tabeli observations.
--    Zasada: Równe numery wersji nie mogą arbitralnie zastępować istniejącego wskaźnika.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS current_observations (
    indicator_code TEXT NOT NULL REFERENCES indicator_catalog(indicator_code),
    country_code TEXT NOT NULL DEFAULT 'PL',
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    frequency TEXT NOT NULL,
    observation_id TEXT NOT NULL REFERENCES observations(observation_id),
    value_decimal TEXT NOT NULL,
    unit_code TEXT NOT NULL,
    revision_type TEXT NOT NULL,
    version_number INTEGER NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('VERIFIED', 'PENDING', 'CONFLICT')),
    updated_at_utc TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (indicator_code, country_code, period_start)
);

CREATE TRIGGER IF NOT EXISTS trg_observations_update_current
AFTER INSERT ON observations
FOR EACH ROW
WHEN NEW.status = 'VERIFIED'
BEGIN
    INSERT INTO current_observations (
        indicator_code, country_code, period_start, period_end, frequency,
        observation_id, value_decimal, unit_code, revision_type, version_number, status, updated_at_utc
    ) VALUES (
        NEW.indicator_code, NEW.country_code, NEW.period_start, NEW.period_end, NEW.frequency,
        NEW.observation_id, NEW.value_decimal, NEW.unit_code, NEW.revision_type, NEW.version_number, NEW.status, CURRENT_TIMESTAMP
    )
    ON CONFLICT(indicator_code, country_code, period_start) DO UPDATE SET
        period_end = excluded.period_end,
        frequency = excluded.frequency,
        observation_id = excluded.observation_id,
        value_decimal = excluded.value_decimal,
        unit_code = excluded.unit_code,
        revision_type = excluded.revision_type,
        version_number = excluded.version_number,
        status = excluded.status,
        updated_at_utc = CURRENT_TIMESTAMP
    WHERE excluded.version_number > current_observations.version_number;
END;

-- WIDOK ANALITYCZNY NAJNOWSZYCH OBSERWACJI (deklaratywny, spójny z current_observations)
-- W przypadku identycznego numeru wersji pierwszeństwo ma pierwsza zarejestrowana obserwacja.
CREATE VIEW IF NOT EXISTS v_latest_observations AS
WITH ranked AS (
    SELECT 
        o.*,
        ROW_NUMBER() OVER (
            PARTITION BY o.indicator_code, o.country_code, o.period_start 
            ORDER BY o.version_number DESC, o.observed_at_utc ASC, o.observation_id ASC
        ) AS rnk
    FROM observations o
    WHERE o.status = 'VERIFIED'
)
SELECT 
    observation_id,
    indicator_code,
    country_code,
    period_start,
    period_end,
    frequency,
    value_decimal,
    unit_code,
    revision_type,
    version_number,
    supersedes_id,
    evidence_id,
    status,
    observed_at_utc,
    validated_at_utc
FROM ranked
WHERE rnk = 1;

-- ----------------------------------------------------------------------------
-- 10. DZIENNIK JAKOŚCI I KONFLIKTÓW (quality_events)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS quality_events (
    event_id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL CHECK(entity_type IN ('CANDIDATE', 'OBSERVATION', 'INGESTION')),
    entity_id TEXT NOT NULL,
    rule_code TEXT NOT NULL,
    severity TEXT NOT NULL CHECK(severity IN ('INFO', 'WARNING', 'ERROR', 'CRITICAL')),
    message TEXT NOT NULL,
    conflict_with_id TEXT,
    context_json TEXT,
    created_at_utc TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at_utc TIMESTAMP,
    resolution_notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_quality_entity ON quality_events(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_quality_rule ON quality_events(rule_code, severity);

-- ----------------------------------------------------------------------------
-- 11. GENEROWANE RAPORTY I MIGAWKI DANYCH (reports)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS reports (
    report_id TEXT PRIMARY KEY,
    country_code TEXT NOT NULL DEFAULT 'PL',
    report_date DATE NOT NULL,
    as_of_utc TIMESTAMP NOT NULL,
    executive_horizon TEXT NOT NULL,
    report_markdown TEXT NOT NULL,
    report_html TEXT,
    data_snapshot_hash TEXT NOT NULL,
    model_metadata_json TEXT,
    created_at_utc TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ----------------------------------------------------------------------------
-- 12. MAPOWANIE MIGRACJI LEGACY (legacy_migration_map)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS legacy_migration_map (
    legacy_id INTEGER NOT NULL,
    legacy_table TEXT NOT NULL,
    target_entity TEXT NOT NULL,
    target_id TEXT NOT NULL,
    migration_status TEXT NOT NULL CHECK(migration_status IN (
        'MIGRATED_VERIFIED', 'MIGRATED_PENDING', 'MIGRATED_CONFLICT', 'SKIPPED'
    )),
    notes TEXT,
    migrated_at_utc TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (legacy_table, legacy_id, target_entity, target_id)
);
