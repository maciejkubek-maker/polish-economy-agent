-- ============================================================================
-- SCHEMAT BAZY DANYCH SQLITE DLA POLISH ECONOMY AGENT (SCHEMA V2)
-- Plik: docs/sql/schema_v2.sql
-- Status: PROPOSED (architektura docelowa z audytowalnością i brakiem zgadywania)
-- ============================================================================

PRAGMA foreign_keys = ON;

-- ----------------------------------------------------------------------------
-- 1. REJESTR OFICJALNYCH I ZEWNĘTRZNYCH ŹRÓDEŁ (source_registry)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS source_registry (
    source_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    institution TEXT NOT NULL,
    base_url TEXT NOT NULL,
    source_type TEXT NOT NULL CHECK(source_type IN (
        'OFFICIAL_API', 'OFFICIAL_WEB', 'WEB_SEARCH', 'FILE_FEED', 'PROXY'
    )),
    trust_tier TEXT NOT NULL CHECK(trust_tier IN ('TIER_A', 'TIER_B', 'TIER_C')),
    update_frequency TEXT NOT NULL DEFAULT 'MONTHLY',
    is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1)),
    created_at_utc TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ----------------------------------------------------------------------------
-- 2. KATALOG JEDNOSTEK MIARY (unit_catalog)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS unit_catalog (
    unit_code TEXT PRIMARY KEY,
    name_pl TEXT NOT NULL,
    symbol TEXT NOT NULL,
    unit_type TEXT NOT NULL CHECK(unit_type IN ('PERCENT', 'CURRENCY', 'COUNT', 'INDEX', 'RATIO')),
    decimal_places INTEGER NOT NULL DEFAULT 2
);

INSERT OR IGNORE INTO unit_catalog (unit_code, name_pl, symbol, unit_type, decimal_places) VALUES
('PCT', 'Procent', '%', 'PERCENT', 2),
('PLN', 'Złoty polski', 'zł', 'CURRENCY', 2),
('PLN_PER_MONTH', 'Złotych miesięcznie', 'zł/m-c', 'CURRENCY', 2),
('EUR_PLN', 'Złoty za euro', 'zł/EUR', 'CURRENCY', 4),
('USD_PLN', 'Złoty za dolara', 'zł/USD', 'CURRENCY', 4),
('MEUR', 'Miliony euro', 'mln EUR', 'CURRENCY', 1),
('THOUSAND_PERSONS', 'Tysiące osób', 'tys. osób', 'COUNT', 1),
('PERSONS', 'Osoby', 'osób', 'COUNT', 0),
('INDEX_POINTS', 'Punkty indeksu', 'pkt', 'INDEX', 2),
('RATIO', 'Wskaźnik', 'ratio', 'RATIO', 4);

-- ----------------------------------------------------------------------------
-- 3. KATALOG WSKAŹNIKÓW MAKROEKONOMICZNYCH (indicator_catalog)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS indicator_catalog (
    indicator_code TEXT PRIMARY KEY,
    name_pl TEXT NOT NULL,
    definition_pl TEXT NOT NULL,
    frequency TEXT NOT NULL CHECK(frequency IN (
        'DAILY', 'MONTHLY', 'QUARTERLY', 'ANNUAL', 'IRREGULAR'
    )),
    unit_code TEXT NOT NULL REFERENCES unit_catalog(unit_code),
    target_macro_area TEXT NOT NULL DEFAULT 'GENERAL' CHECK(target_macro_area IN (
        'INFLATION', 'LABOUR_MARKET', 'ECONOMIC_GROWTH', 'INDUSTRY', 'MONETARY_POLICY', 'GENERAL'
    )),
    is_headline INTEGER NOT NULL DEFAULT 0 CHECK(is_headline IN (0, 1)),
    is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1)),
    created_at_utc TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ----------------------------------------------------------------------------
-- 4. ALIAS I WARIANTY NAZW WSKAŹNIKÓW (indicator_aliases)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS indicator_aliases (
    alias_id INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_name TEXT NOT NULL,
    canonical_indicator_code TEXT NOT NULL REFERENCES indicator_catalog(indicator_code),
    source_context TEXT,
    notes TEXT,
    UNIQUE(raw_name, source_context)
);

CREATE INDEX IF NOT EXISTS idx_alias_raw ON indicator_aliases(raw_name);

-- ----------------------------------------------------------------------------
-- 5. SERIE DANYCH ŹRÓDŁOWYCH (data_series)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS data_series (
    series_id TEXT PRIMARY KEY,
    indicator_code TEXT NOT NULL REFERENCES indicator_catalog(indicator_code),
    source_id TEXT NOT NULL REFERENCES source_registry(source_id),
    country_code TEXT NOT NULL DEFAULT 'PL',
    dataset_identifier TEXT NOT NULL,
    variable_identifier TEXT,
    dimension_filters_json TEXT,
    release_calendar_url TEXT,
    is_primary_source INTEGER NOT NULL DEFAULT 1 CHECK(is_primary_source IN (0, 1)),
    created_at_utc TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source_id, dataset_identifier, variable_identifier)
);

-- ----------------------------------------------------------------------------
-- 6. DZIENNIK PRZEBIEGÓW POBIERANIA (ingestion_runs)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ingestion_runs (
    run_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL CHECK(provider IN (
        'GUS_API', 'NBP_API', 'EUROSTAT_API', 'TAVILY_SEARCH', 'LEGACY_MIGRATOR', 'MANUAL'
    )),
    run_type TEXT NOT NULL CHECK(run_type IN ('SCHEDULED', 'TRIGGERED', 'MIGRATION', 'REPAIR')),
    started_at_utc TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at_utc TIMESTAMP,
    status TEXT NOT NULL CHECK(status IN ('RUNNING', 'COMPLETED', 'FAILED', 'PARTIAL')),
    records_fetched INTEGER NOT NULL DEFAULT 0,
    records_validated INTEGER NOT NULL DEFAULT 0,
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_ingestion_provider ON ingestion_runs(provider, started_at_utc);

-- ----------------------------------------------------------------------------
-- 7. DOWODY ŹRÓDŁOWE / WARSTWA BRUDNA RAW (source_evidence & extracted_candidates)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS source_evidence (
    evidence_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES ingestion_runs(run_id),
    source_id TEXT NOT NULL REFERENCES source_registry(source_id),
    source_url TEXT NOT NULL,
    document_type TEXT NOT NULL CHECK(document_type IN (
        'API_RESPONSE', 'HTML_PAGE', 'PDF_BULLETIN', 'LEGACY_IMPORT', 'SEARCH_SNIPPET'
    )),
    content_hash TEXT NOT NULL,
    raw_payload_text TEXT,
    retrieved_at_utc TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_evidence_run ON source_evidence(run_id);
CREATE INDEX IF NOT EXISTS idx_evidence_hash ON source_evidence(content_hash);

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
    metadata_json TEXT,
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
--    Zasada determinizmu: wybór wskaźnika jest w 100% spójny z widokiem v_latest_observations
--    nawet przy imporcie danych w nieuporządkowanej kolejności (out-of-order import).
--    Porządek wyboru: version_number DESC, observed_at_utc DESC, observation_id DESC.
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
    observed_at_utc TIMESTAMP NOT NULL,
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
        observation_id, value_decimal, unit_code, revision_type, version_number, status, observed_at_utc, updated_at_utc
    ) VALUES (
        NEW.indicator_code, NEW.country_code, NEW.period_start, NEW.period_end, NEW.frequency,
        NEW.observation_id, NEW.value_decimal, NEW.unit_code, NEW.revision_type, NEW.version_number, NEW.status, NEW.observed_at_utc, CURRENT_TIMESTAMP
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
        observed_at_utc = excluded.observed_at_utc,
        updated_at_utc = CURRENT_TIMESTAMP
    WHERE 
        excluded.version_number > current_observations.version_number
        OR (
            excluded.version_number = current_observations.version_number
            AND (
                excluded.observed_at_utc > current_observations.observed_at_utc
                OR (
                    excluded.observed_at_utc = current_observations.observed_at_utc
                    AND excluded.observation_id > current_observations.observation_id
                )
            )
        );
END;

-- WIDOK ANALITYCZNY NAJNOWSZYCH OBSERWACJI (deklaratywny, w 100% spójny z current_observations)
-- Wybór następuje deterministycznie: wyższy numer wersji, a przy równej wersji nowsza data obserwacji.
CREATE VIEW IF NOT EXISTS v_latest_observations AS
WITH ranked AS (
    SELECT 
        o.*,
        ROW_NUMBER() OVER (
            PARTITION BY o.indicator_code, o.country_code, o.period_start 
            ORDER BY o.version_number DESC, o.observed_at_utc DESC, o.observation_id DESC
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
    publication_status TEXT NOT NULL DEFAULT 'PENDING' CHECK(publication_status IN ('PENDING', 'PUBLISHED', 'FAILED')),
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

CREATE INDEX IF NOT EXISTS idx_legacy_map_lookup ON legacy_migration_map(legacy_table, legacy_id);
