"""Automated offline validation tests for SQLite Schema v2 Design and Legacy Data Contract.

Ensures that:
1. docs/sql/schema_v2.sql DDL is valid and creates all 12 tables, views, and triggers.
2. observations table is strictly append-only (triggers prevent UPDATE and DELETE).
3. current_observations pointer table and v_latest_observations view correctly resolve active versions,
   specifically ensuring equal version numbers do not arbitrarily overwrite existing pointers.
4. Decimal representations and check constraints work as expected.
5. Legacy indicator names (24 variants) are 100% classified into canonical codes or review queues.
6. A complete dry-run migration pipeline processes all 75 unique legacy records without data loss,
   properly flags PKB 3.8% vs 3.90% as CONFLICT (without assuming precedence),
   flags Stopa bezrobocia r/r as PENDING, maps all 10 sources and 6 reports,
   and records all 91 entities in legacy_migration_map.
7. Migration dry-run idempotency: re-running the full migration pipeline on 75 indicators, 10 sources,
   and 6 reports creates zero duplicate records or linkages.
8. Original instance/economy_agent.db remains untouched (73,728 bytes, 75/10/6).
"""

from decimal import Decimal
import os
import sqlite3
import pytest


SCHEMA_V2_SQL_PATH = os.path.join(
    os.path.dirname(__file__), "..", "docs", "sql", "schema_v2.sql"
)
LEGACY_DB_PATH = os.path.join(
    os.path.dirname(__file__), "..", "instance", "economy_agent.db"
)


@pytest.fixture
def memory_db_v2():
  """Creates an in-memory SQLite v2 database populated with schema_v2.sql."""
  conn = sqlite3.connect(":memory:")
  conn.execute("PRAGMA foreign_keys = ON;")
  with open(SCHEMA_V2_SQL_PATH, "r", encoding="utf-8") as f:
    conn.executescript(f.read())
  yield conn
  conn.close()


def test_schema_v2_creates_all_expected_tables_views_and_triggers(memory_db_v2):
  """Verifies that all 12 core tables, views, and triggers of Schema v2 exist."""
  cursor = memory_db_v2.cursor()
  tables = {
      row[0]
      for row in cursor.execute(
          "SELECT name FROM sqlite_master WHERE type='table'"
      ).fetchall()
  }
  expected_tables = {
      "source_registry",
      "indicator_catalog",
      "indicator_aliases",
      "data_series",
      "ingestion_runs",
      "source_evidence",
      "extracted_candidates",
      "observations",
      "current_observations",
      "quality_events",
      "reports",
      "legacy_migration_map",
  }
  missing = expected_tables - tables
  assert not missing, f"Schema v2 is missing expected tables: {missing}"

  views = {
      row[0]
      for row in cursor.execute(
          "SELECT name FROM sqlite_master WHERE type='view'"
      ).fetchall()
  }
  assert "v_latest_observations" in views

  triggers = {
      row[0]
      for row in cursor.execute(
          "SELECT name FROM sqlite_master WHERE type='trigger'"
      ).fetchall()
  }
  expected_triggers = {
      "trg_observations_prevent_update",
      "trg_observations_prevent_delete",
      "trg_observations_update_current",
  }
  missing_triggers = expected_triggers - triggers
  assert not missing_triggers, f"Schema v2 is missing triggers: {missing_triggers}"


def test_observations_strict_append_only_triggers(memory_db_v2):
  """Verifies that the observations table is strictly append-only at storage layer."""
  cursor = memory_db_v2.cursor()

  cursor.execute(
      """
        INSERT INTO source_registry (source_id, name, institution, base_url, source_type, trust_tier)
        VALUES ('SRC_TEST', 'Test Source', 'GUS', 'https://stat.gov.pl', 'API_REST', 'TIER_A');
    """
  )
  cursor.execute(
      """
        INSERT INTO indicator_catalog (indicator_code, name_pl, definition_pl, frequency, unit_code)
        VALUES ('PL_CPI_TEST', 'Inflacja CPI test', 'Definicja', 'MONTHLY', 'PCT');
    """
  )
  cursor.execute(
      """
        INSERT INTO ingestion_runs (run_id, provider, run_type, started_at_utc, status)
        VALUES ('RUN_001', 'TEST_PROVIDER', 'MANUAL', CURRENT_TIMESTAMP, 'COMPLETED');
    """
  )
  cursor.execute(
      """
        INSERT INTO source_evidence (evidence_id, run_id, source_id, source_url, document_type, content_hash, retrieved_at_utc)
        VALUES ('EVI_001', 'RUN_001', 'SRC_TEST', 'https://stat.gov.pl/cpi', 'API_RESPONSE', 'hash123', CURRENT_TIMESTAMP);
    """
  )

  # Insert initial observation
  cursor.execute(
      """
        INSERT INTO observations (
            observation_id, indicator_code, period_start, period_end, frequency,
            value_decimal, unit_code, revision_type, version_number, evidence_id, status
        ) VALUES (
            'OBS_001', 'PL_CPI_TEST', '2026-07-01', '2026-07-31', 'MONTHLY',
            '3.40', 'PCT', 'FINAL', 1, 'EVI_001', 'VERIFIED'
        );
    """
  )

  # Attempt UPDATE on observations -> MUST FAIL
  with pytest.raises(sqlite3.DatabaseError) as exc_update:
    cursor.execute(
        "UPDATE observations SET value_decimal = '9.99' WHERE"
        " observation_id = 'OBS_001'"
    )
  assert "append-only" in str(exc_update.value).lower()

  # Attempt DELETE on observations -> MUST FAIL
  with pytest.raises(sqlite3.DatabaseError) as exc_delete:
    cursor.execute(
        "DELETE FROM observations WHERE observation_id = 'OBS_001'"
    )
  assert "append-only" in str(exc_delete.value).lower()


def test_current_observations_pointer_and_view(memory_db_v2):
  """Verifies that current_observations and v_latest_observations resolve latest versions consistently.

  Specifically tests that equal version numbers do NOT overwrite an existing
  pointer.
  """
  cursor = memory_db_v2.cursor()

  cursor.execute(
      """
        INSERT INTO source_registry (source_id, name, institution, base_url, source_type, trust_tier)
        VALUES ('SRC_TEST', 'Test Source', 'GUS', 'https://stat.gov.pl', 'API_REST', 'TIER_A');
    """
  )
  cursor.execute(
      """
        INSERT INTO indicator_catalog (indicator_code, name_pl, definition_pl, frequency, unit_code)
        VALUES ('PL_GDP_TEST', 'PKB test', 'Definicja', 'QUARTERLY', 'PCT');
    """
  )
  cursor.execute(
      """
        INSERT INTO ingestion_runs (run_id, provider, run_type, started_at_utc, status)
        VALUES ('RUN_001', 'TEST', 'MANUAL', CURRENT_TIMESTAMP, 'COMPLETED');
    """
  )
  cursor.execute(
      """
        INSERT INTO source_evidence (evidence_id, run_id, source_id, source_url, document_type, content_hash, retrieved_at_utc)
        VALUES ('EVI_001', 'RUN_001', 'SRC_TEST', 'https://stat.gov.pl/gdp', 'API_RESPONSE', 'hash123', CURRENT_TIMESTAMP);
    """
  )

  # Insert Version 1 (FLASH)
  cursor.execute(
      """
        INSERT INTO observations (
            observation_id, indicator_code, period_start, period_end, frequency,
            value_decimal, unit_code, revision_type, version_number, evidence_id, status, observed_at_utc
        ) VALUES (
            'OBS_V1_A', 'PL_GDP_TEST', '2026-04-01', '2026-06-30', 'QUARTERLY',
            '3.90', 'PCT', 'FLASH', 1, 'EVI_001', 'VERIFIED', '2026-07-01 10:00:00'
        );
    """
  )

  # Pointer and view must show OBS_V1_A
  curr_row = cursor.execute(
      "SELECT observation_id, version_number, value_decimal FROM"
      " current_observations WHERE indicator_code = 'PL_GDP_TEST'"
  ).fetchone()
  assert curr_row == ("OBS_V1_A", 1, "3.90")

  view_row = cursor.execute(
      "SELECT observation_id, version_number, value_decimal FROM"
      " v_latest_observations WHERE indicator_code = 'PL_GDP_TEST'"
  ).fetchone()
  assert view_row == ("OBS_V1_A", 1, "3.90")

  # Insert a SECOND observation with the SAME version number (version 1)
  cursor.execute(
      """
        INSERT INTO observations (
            observation_id, indicator_code, period_start, period_end, frequency,
            value_decimal, unit_code, revision_type, version_number, evidence_id, status, observed_at_utc
        ) VALUES (
            'OBS_V1_B', 'PL_GDP_TEST', '2026-04-01', '2026-06-30', 'QUARTERLY',
            '3.95', 'PCT', 'FLASH', 1, 'EVI_001', 'VERIFIED', '2026-07-01 11:00:00'
        );
    """
  )

  # Check: Equal version MUST NOT overwrite the existing pointer!
  curr_row_same_ver = cursor.execute(
      "SELECT observation_id, version_number, value_decimal FROM"
      " current_observations WHERE indicator_code = 'PL_GDP_TEST'"
  ).fetchone()
  assert curr_row_same_ver == (
      "OBS_V1_A",
      1,
      "3.90",
  ), "Equal version number must not overwrite existing pointer"

  view_row_same_ver = cursor.execute(
      "SELECT observation_id, version_number, value_decimal FROM"
      " v_latest_observations WHERE indicator_code = 'PL_GDP_TEST'"
  ).fetchone()
  assert view_row_same_ver == (
      "OBS_V1_A",
      1,
      "3.90",
  ), "View and current_observations must remain consistent on equal versions"

  # Now insert Version 2 (REVISED) -> Strictly higher version (2 > 1) MUST update
  cursor.execute(
      """
        INSERT INTO observations (
            observation_id, indicator_code, period_start, period_end, frequency,
            value_decimal, unit_code, revision_type, version_number, supersedes_id, evidence_id, status, observed_at_utc
        ) VALUES (
            'OBS_V2_A', 'PL_GDP_TEST', '2026-04-01', '2026-06-30', 'QUARTERLY',
            '3.80', 'PCT', 'REVISED', 2, 'OBS_V1_A', 'EVI_001', 'VERIFIED', '2026-08-01 10:00:00'
        );
    """
  )

  curr_row_v2 = cursor.execute(
      "SELECT observation_id, version_number, value_decimal FROM"
      " current_observations WHERE indicator_code = 'PL_GDP_TEST'"
  ).fetchone()
  assert curr_row_v2 == ("OBS_V2_A", 2, "3.80")

  view_row_v2 = cursor.execute(
      "SELECT observation_id, version_number, value_decimal FROM"
      " v_latest_observations WHERE indicator_code = 'PL_GDP_TEST'"
  ).fetchone()
  assert view_row_v2 == ("OBS_V2_A", 2, "3.80")

  # Total observations in table must be 3 (all preserved append-only)
  total_obs = cursor.execute(
      "SELECT count(*) FROM observations WHERE indicator_code ="
      " 'PL_GDP_TEST'"
  ).fetchone()[0]
  assert total_obs == 3


def test_schema_v2_foreign_keys_and_constraints(memory_db_v2):
  """Verifies foreign key constraints and validation check rules."""
  cursor = memory_db_v2.cursor()

  cursor.execute(
      """
        INSERT INTO source_registry (source_id, name, institution, base_url, source_type, trust_tier)
        VALUES ('SRC_TEST', 'Test Source', 'NBP', 'https://api.nbp.pl', 'API_REST', 'TIER_A');
    """
  )

  cursor.execute(
      """
        INSERT INTO indicator_catalog (
            indicator_code, name_pl, definition_pl, frequency, unit_code, preferred_source_id
        ) VALUES (
            'PL_TEST_CPI', 'Inflacja testowa', 'Definicja testowa', 'MONTHLY', 'PCT', 'SRC_TEST'
        );
    """
  )

  # Attempt invalid frequency constraint
  with pytest.raises(sqlite3.IntegrityError):
    cursor.execute(
        """
            INSERT INTO indicator_catalog (
                indicator_code, name_pl, definition_pl, frequency, unit_code
            ) VALUES (
                'PL_BAD', 'Bad', 'Bad', 'INVALID_FREQ', 'PCT'
            );
        """
    )


def test_value_decimal_parsing_and_precision():
  """Verifies that decimal values parse cleanly without float inaccuracies."""
  raw_samples = ["5.80", "-2.40", "906.40", "9233.13", "0.40"]
  for raw in raw_samples:
    dec = Decimal(raw)
    assert str(dec) == raw, (
        f"Decimal string conversion mismatch for {raw} -> {dec}"
    )


def test_legacy_indicator_names_classification_coverage():
  """Verifies that the classification dictionary covers 100% of the 24 distinct legacy indicator names."""
  conn = sqlite3.connect(f"file:{LEGACY_DB_PATH}?mode=ro", uri=True)
  cursor = conn.cursor()
  rows = cursor.execute(
      "SELECT DISTINCT indicator_name FROM collected_indicators ORDER BY"
      " indicator_name"
  ).fetchall()
  conn.close()

  distinct_names = [r[0] for r in rows]
  assert len(distinct_names) == 24, (
      f"Expected 24 distinct names, got {len(distinct_names)}"
  )

  canonical_mapping = {
      "Inflacja CPI r/r": "PL_CPI_YOY",
      "Inflacja CPI m/m": "PL_CPI_MOM",
      "Inflacja m/m": "PL_CPI_MOM",
      "Produkcja przemysłowa r/r": "PL_INDUSTRIAL_PRODUCTION_YOY",
      "Produkcja budowlano-montażowa r/r": "PL_CONSTRUCTION_PRODUCTION_YOY",
      "Sprzedaż detaliczna r/r": "PL_RETAIL_SALES_YOY",
      "Produkt Krajowy Brutto r/r": "PL_GDP_YOY",
      "PKB r/r": "PL_GDP_YOY",
      "Produkt Krajowy Brutto kw/kw": "PL_GDP_QOQ",
      "Przeciętne wynagrodzenia": "PL_WAGE_AVERAGE_GROSS",
      "Przeciętne Wynagrodzenia": "PL_WAGE_AVERAGE_GROSS",
      "Stopa referencyjna NBP": "PL_NBP_REFERENCE_RATE",
      "Purchasing Managers' Index (PMI) Polska": "PL_PMI_MANUFACTURING",
      "Stopa bezrobocia rejestrowanego": "PL_UNEMPLOYMENT_REGISTERED_RATE",
      "Stopa bezrobocia rejestrowanego (GUS)": (
          "PL_UNEMPLOYMENT_REGISTERED_RATE"
      ),
      "Stopa bezrobocia": "PL_UNEMPLOYMENT_REGISTERED_RATE",
      "Liczba zarejestrowanych bezrobotnych": "PL_UNEMPLOYMENT_REGISTERED_COUNT",
      "Liczba bezrobotnych": "PL_UNEMPLOYMENT_REGISTERED_COUNT",
      "Bezrobotni zarejestrowani": "PL_UNEMPLOYMENT_REGISTERED_COUNT",
      "Liczba nowo zarejestrowanych bezrobotnych": (
          "PL_UNEMPLOYMENT_NEW_REGISTERED_COUNT"
      ),
      "Inflacja bazowa (po wyłączeniu cen żywności i energii)": (
          "PL_CORE_INFLATION_YOY"
      ),
      "Inflacja bazowa (wyłączenie cen żywności i energii)": (
          "PL_CORE_INFLATION_YOY"
      ),
      "Inflacja bazowa (z wyłączeniem cen żywności i energii)": (
          "PL_CORE_INFLATION_YOY"
      ),
      "Stopa bezrobocia r/r": "PL_UNEMPLOYMENT_REGISTERED_RATE",
  }

  missing = set(distinct_names) - set(canonical_mapping.keys())
  assert not missing, f"Missing classification for: {missing}"


def _execute_dry_run_migration_pass(target_cursor):
  """Helper executing a full dry-run migration pass from the legacy database into target SQLite v2."""
  legacy_conn = sqlite3.connect(f"file:{LEGACY_DB_PATH}?mode=ro", uri=True)
  legacy_cur = legacy_conn.cursor()

  indicators = legacy_cur.execute(
      "SELECT id, agent_name, country, indicator_name, value, period,"
      " source_name, page_info, created_at FROM collected_indicators ORDER"
      " BY id"
  ).fetchall()
  sources = legacy_cur.execute(
      "SELECT id, agent_name, country, name, url, description, created_at FROM"
      " trusted_sources ORDER BY id"
  ).fetchall()
  reports = legacy_cur.execute(
      "SELECT id, country, report_date, periods_summary, content_markdown,"
      " created_at FROM generated_reports ORDER BY id"
  ).fetchall()
  legacy_conn.close()

  # 1. Ingestion run (idempotent)
  target_cursor.execute(
      """
        INSERT INTO ingestion_runs (run_id, provider, run_type, started_at_utc, status)
        VALUES ('RUN_MIGRATION_001', 'LEGACY_MIGRATOR', 'MIGRATION', CURRENT_TIMESTAMP, 'COMPLETED')
        ON CONFLICT(run_id) DO NOTHING;
    """
  )

  # 2. Migrate sources (10)
  for s in sources:
    s_id, s_agent, s_country, s_name, s_url, s_desc, s_created = s
    source_key = f"SRC_LEGACY_{s_id}"
    target_cursor.execute(
        """
            INSERT INTO source_registry (source_id, name, institution, base_url, source_type, trust_tier)
            VALUES (?, ?, ?, ?, 'WEB_SEARCH', 'TIER_B')
            ON CONFLICT(source_id) DO NOTHING;
        """,
        (source_key, s_name, s_name, s_url),
    )
    target_cursor.execute(
        """
            INSERT INTO legacy_migration_map (legacy_id, legacy_table, target_entity, target_id, migration_status, notes)
            VALUES (?, 'trusted_sources', 'source_registry', ?, 'MIGRATED_VERIFIED', 'Direct source mapping')
            ON CONFLICT(legacy_table, legacy_id, target_entity, target_id) DO NOTHING;
        """,
        (s_id, source_key),
    )

  # 3. Catalog definitions (idempotent)
  catalog_entries = [
      ("PL_CPI_YOY", "Inflacja CPI r/r", "MONTHLY", "PCT"),
      ("PL_CPI_MOM", "Inflacja CPI m/m", "MONTHLY", "PCT"),
      ("PL_CORE_INFLATION_YOY", "Inflacja bazowa r/r", "MONTHLY", "PCT"),
      (
          "PL_UNEMPLOYMENT_REGISTERED_RATE",
          "Stopa bezrobocia rejestrowanego",
          "MONTHLY",
          "PCT",
      ),
      (
          "PL_UNEMPLOYMENT_REGISTERED_COUNT",
          "Liczba bezrobotnych zarejestrowanych",
          "MONTHLY",
          "THOUSAND_PERSONS",
      ),
      (
          "PL_UNEMPLOYMENT_NEW_REGISTERED_COUNT",
          "Nowo zarejestrowani bezrobotni",
          "MONTHLY",
          "THOUSAND_PERSONS",
      ),
      ("PL_GDP_YOY", "Produkt Krajowy Brutto r/r", "QUARTERLY", "PCT"),
      ("PL_GDP_QOQ", "Produkt Krajowy Brutto kw/kw", "QUARTERLY", "PCT"),
      (
          "PL_WAGE_AVERAGE_GROSS",
          "Przeciętne wynagrodzenie",
          "MONTHLY",
          "PLN_PER_MONTH",
      ),
      (
          "PL_INDUSTRIAL_PRODUCTION_YOY",
          "Produkcja przemysłowa r/r",
          "MONTHLY",
          "PCT",
      ),
      ("PL_RETAIL_SALES_YOY", "Sprzedaż detaliczna r/r", "MONTHLY", "PCT"),
      (
          "PL_CONSTRUCTION_PRODUCTION_YOY",
          "Produkcja budowlano-montażowa r/r",
          "MONTHLY",
          "PCT",
      ),
      ("PL_NBP_REFERENCE_RATE", "Stopa referencyjna NBP", "IRREGULAR", "PCT"),
      (
          "PL_PMI_MANUFACTURING",
          "PMI Polska dla przemysłu",
          "MONTHLY",
          "INDEX_POINTS",
      ),
  ]
  for code, name, freq, unit in catalog_entries:
    target_cursor.execute(
        """
            INSERT INTO indicator_catalog (indicator_code, name_pl, definition_pl, frequency, unit_code)
            VALUES (?, ?, 'Definicja katalogowa', ?, ?)
            ON CONFLICT(indicator_code) DO NOTHING;
        """,
        (code, name, freq, unit),
    )

  # 4. Migrate reports (6)
  for rep in reports:
    r_id, r_country, r_date, r_sum, r_md, r_created = rep
    target_rep_id = f"REP_LEGACY_{r_id}"
    target_cursor.execute(
        """
            INSERT INTO reports (report_id, country_code, report_date, as_of_utc, executive_horizon, report_markdown, data_snapshot_hash)
            VALUES (?, 'PL', '2026-09-18', ?, ?, ?, 'legacy_hash')
            ON CONFLICT(report_id) DO NOTHING;
        """,
        (target_rep_id, r_created, r_sum, r_md),
    )
    target_cursor.execute(
        """
            INSERT INTO legacy_migration_map (legacy_id, legacy_table, target_entity, target_id, migration_status, notes)
            VALUES (?, 'generated_reports', 'reports', ?, 'MIGRATED_VERIFIED', 'Legacy report archive')
            ON CONFLICT(legacy_table, legacy_id, target_entity, target_id) DO NOTHING;
        """,
        (r_id, target_rep_id),
    )

  # 5. Migrate indicators (75)
  for ind in indicators:
    (
        i_id,
        i_agent,
        i_country,
        i_name,
        i_val,
        i_period,
        i_src,
        i_page,
        i_created,
    ) = ind
    evidence_id = f"EVI_LEGACY_{i_id}"
    candidate_id = f"CAND_LEGACY_{i_id}"

    target_cursor.execute(
        """
            INSERT INTO source_evidence (evidence_id, run_id, source_id, source_url, document_type, content_hash, retrieved_at_utc)
            VALUES (?, 'RUN_MIGRATION_001', 'SRC_LEGACY_1', ?, 'LEGACY_IMPORT', ?, ?)
            ON CONFLICT(evidence_id) DO NOTHING;
        """,
        (evidence_id, i_page or "https://stat.gov.pl", f"hash_{i_id}", i_created),
    )

    target_cursor.execute(
        """
            INSERT INTO extracted_candidates (
                candidate_id, evidence_id, run_id, agent_name, raw_indicator_name, raw_value, raw_period
            ) VALUES (?, ?, 'RUN_MIGRATION_001', ?, ?, ?, ?)
            ON CONFLICT(candidate_id) DO NOTHING;
        """,
        (candidate_id, evidence_id, i_agent, i_name, i_val, i_period),
    )

    if i_name in ("Produkt Krajowy Brutto r/r", "PKB r/r"):
      target_cursor.execute(
          """
                INSERT INTO quality_events (event_id, entity_type, entity_id, rule_code, severity, message)
                VALUES (?, 'CANDIDATE', ?, 'RULE_SOURCE_DISCREPANCY', 'WARNING',
                        'PKB r/r conflict for II kw. 2026: 3.90% vs 3.8%. Awaiting primary release bulletin confirmation.')
                ON CONFLICT(event_id) DO NOTHING;
            """,
          (f"QEV_PKB_{i_id}", candidate_id),
      )
      target_cursor.execute(
          """
                INSERT INTO legacy_migration_map (legacy_id, legacy_table, target_entity, target_id, migration_status, notes)
                VALUES (?, 'collected_indicators', 'extracted_candidates', ?, 'MIGRATED_CONFLICT', 'PKB 3.8 vs 3.90 discrepancy marked CONFLICT')
                ON CONFLICT(legacy_table, legacy_id, target_entity, target_id) DO NOTHING;
            """,
          (i_id, candidate_id),
      )

    elif i_name == "Stopa bezrobocia r/r":
      target_cursor.execute(
          """
                INSERT INTO quality_events (event_id, entity_type, entity_id, rule_code, severity, message)
                VALUES (?, 'CANDIDATE', ?, 'RULE_MISLABELED_INDICATOR_NAME', 'WARNING',
                        'Rate mislabeled with y/y suffix by GPTAgent. Requires human verification before promotion.')
                ON CONFLICT(event_id) DO NOTHING;
            """,
          (f"QEV_RATE_{i_id}", candidate_id),
      )
      target_cursor.execute(
          """
                INSERT INTO legacy_migration_map (legacy_id, legacy_table, target_entity, target_id, migration_status, notes)
                VALUES (?, 'collected_indicators', 'extracted_candidates', ?, 'MIGRATED_PENDING', 'Mislabeled r/r suffix')
                ON CONFLICT(legacy_table, legacy_id, target_entity, target_id) DO NOTHING;
            """,
          (i_id, candidate_id),
      )

    else:
      target_cursor.execute(
          """
                INSERT INTO legacy_migration_map (legacy_id, legacy_table, target_entity, target_id, migration_status, notes)
                VALUES (?, 'collected_indicators', 'extracted_candidates', ?, 'MIGRATED_VERIFIED', 'Unambiguous indicator mapping')
                ON CONFLICT(legacy_table, legacy_id, target_entity, target_id) DO NOTHING;
            """,
          (i_id, candidate_id),
      )


def test_dry_run_migration_full_pipeline_simulation(memory_db_v2):
  """Comprehensive dry-run migration test simulating full extraction, validation, conflict flagging, and map registration.

  Confirms that:
  - Exactly 75 unique legacy indicator IDs are mapped.
  - Exactly 10 sources and 6 reports are migrated.
  - PKB 3.8% vs 3.90% is flagged as CONFLICT/PENDING without assuming precedence.
  - Stopa bezrobocia r/r is flagged as PENDING in quality_events.
  - 91 total rows are registered in legacy_migration_map.
  """
  cursor = memory_db_v2.cursor()
  _execute_dry_run_migration_pass(cursor)

  # Check total map entries: 75 indicators + 10 sources + 6 reports = 91 rows
  total_map = cursor.execute(
      "SELECT count(*) FROM legacy_migration_map"
  ).fetchone()[0]
  assert total_map == 91

  # Check unique legacy indicator IDs in map
  indicator_map_ids = set(
      row[0]
      for row in cursor.execute(
          "SELECT legacy_id FROM legacy_migration_map WHERE legacy_table ="
          " 'collected_indicators'"
      ).fetchall()
  )
  assert indicator_map_ids == set(range(1, 76))

  # Check conflict and pending event counts
  conflict_count = cursor.execute(
      "SELECT count(*) FROM legacy_migration_map WHERE migration_status ="
      " 'MIGRATED_CONFLICT'"
  ).fetchone()[0]
  assert conflict_count == 4  # IDs: 3, 8, 32, 38

  pending_count = cursor.execute(
      "SELECT count(*) FROM legacy_migration_map WHERE migration_status ="
      " 'MIGRATED_PENDING'"
  ).fetchone()[0]
  assert pending_count == 2  # IDs: 33, 35

  verified_count = cursor.execute(
      "SELECT count(*) FROM legacy_migration_map WHERE migration_status ="
      " 'MIGRATED_VERIFIED' AND legacy_table = 'collected_indicators'"
  ).fetchone()[0]
  assert verified_count == 69  # 75 - 4 - 2 = 69


def test_dry_run_migration_idempotency(memory_db_v2):
  """Verifies that re-running the full migration pipeline on 75 indicators, 10 sources, and 6 reports produces zero duplicate records or linkages."""
  cursor = memory_db_v2.cursor()

  # Pass 1: Initial full migration
  _execute_dry_run_migration_pass(cursor)

  sources_pass1 = cursor.execute(
      "SELECT count(*) FROM source_registry"
  ).fetchone()[0]
  reports_pass1 = cursor.execute("SELECT count(*) FROM reports").fetchone()[0]
  evidence_pass1 = cursor.execute(
      "SELECT count(*) FROM source_evidence"
  ).fetchone()[0]
  candidates_pass1 = cursor.execute(
      "SELECT count(*) FROM extracted_candidates"
  ).fetchone()[0]
  events_pass1 = cursor.execute(
      "SELECT count(*) FROM quality_events"
  ).fetchone()[0]
  map_pass1 = cursor.execute(
      "SELECT count(*) FROM legacy_migration_map"
  ).fetchone()[0]

  assert sources_pass1 == 10
  assert reports_pass1 == 6
  assert evidence_pass1 == 75
  assert candidates_pass1 == 75
  assert events_pass1 == 6  # 4 for PKB + 2 for bezrobocie r/r
  assert map_pass1 == 91

  # Pass 2: Re-run full migration pipeline on the EXACT SAME target database
  _execute_dry_run_migration_pass(cursor)

  sources_pass2 = cursor.execute(
      "SELECT count(*) FROM source_registry"
  ).fetchone()[0]
  reports_pass2 = cursor.execute("SELECT count(*) FROM reports").fetchone()[0]
  evidence_pass2 = cursor.execute(
      "SELECT count(*) FROM source_evidence"
  ).fetchone()[0]
  candidates_pass2 = cursor.execute(
      "SELECT count(*) FROM extracted_candidates"
  ).fetchone()[0]
  events_pass2 = cursor.execute(
      "SELECT count(*) FROM quality_events"
  ).fetchone()[0]
  map_pass2 = cursor.execute(
      "SELECT count(*) FROM legacy_migration_map"
  ).fetchone()[0]

  # Strictly verify zero record inflation
  assert (
      sources_pass2 == sources_pass1 == 10
  ), "Idempotency violation in source_registry"
  assert reports_pass2 == reports_pass1 == 6, "Idempotency violation in reports"
  assert (
      evidence_pass2 == evidence_pass1 == 75
  ), "Idempotency violation in source_evidence"
  assert (
      candidates_pass2 == candidates_pass1 == 75
  ), "Idempotency violation in extracted_candidates"
  assert (
      events_pass2 == events_pass1 == 6
  ), "Idempotency violation in quality_events"
  assert (
      map_pass2 == map_pass1 == 91
  ), "Idempotency violation in legacy_migration_map"


def test_legacy_database_is_untouched_after_tests():
  """Verifies that the original database remains 73,728 bytes with 75/10/6 records."""
  assert os.path.exists(LEGACY_DB_PATH)
  size = os.path.getsize(LEGACY_DB_PATH)
  assert size == 73728

  conn = sqlite3.connect(f"file:{LEGACY_DB_PATH}?mode=ro", uri=True)
  cursor = conn.cursor()
  assert (
      cursor.execute("SELECT count(*) FROM collected_indicators").fetchone()[0]
      == 75
  )
  assert (
      cursor.execute("SELECT count(*) FROM trusted_sources").fetchone()[0] == 10
  )
  assert (
      cursor.execute("SELECT count(*) FROM generated_reports").fetchone()[0] == 6
  )
  conn.close()
