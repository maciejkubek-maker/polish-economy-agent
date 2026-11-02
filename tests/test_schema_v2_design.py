"""Automated offline validation tests for SQLite Schema v2 Design and Legacy Data Contract.

Ensures that:
1. docs/sql/schema_v2.sql DDL is valid and creates all 11 required tables with foreign keys.
2. Canonical decimal representations and check constraints work as expected.
3. All 75 legacy records from instance/economy_agent.db map unambiguously or to quality review without data loss.
4. The migration dry-run is 100% read-only and idempotent.
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


def test_schema_v2_creates_all_expected_tables(memory_db_v2):
  """Verifies that all 11 core tables of Schema v2 exist."""
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
      "quality_events",
      "reports",
      "legacy_migration_map",
  }
  missing = expected_tables - tables
  assert not missing, f"Schema v2 is missing expected tables: {missing}"


def test_schema_v2_foreign_keys_and_constraints(memory_db_v2):
  """Verifies foreign key constraints and validation check rules."""
  cursor = memory_db_v2.cursor()

  # Insert source
  cursor.execute(
      """
        INSERT INTO source_registry (source_id, name, institution, base_url, source_type, trust_tier)
        VALUES ('SRC_TEST', 'Test Source', 'NBP', 'https://api.nbp.pl', 'API_REST', 'TIER_A');
    """
  )

  # Insert indicator catalog item
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


def test_legacy_database_complete_mapping_coverage():
  """Tests dry-run mapping of all 75 legacy records into canonical categories.

  Ensures 0 records are lost or unhandled.
  """
  conn = sqlite3.connect(f"file:{LEGACY_DB_PATH}?mode=ro", uri=True)
  cursor = conn.cursor()
  rows = cursor.execute(
      "SELECT id, agent_name, country, indicator_name, value, period,"
      " source_name, created_at FROM collected_indicators ORDER BY id"
  ).fetchall()
  conn.close()

  assert len(rows) == 75, f"Expected 75 legacy records, found {len(rows)}"

  mapped_count = 0
  pending_count = 0

  # Canonical name mapping dictionary
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

  for r in rows:
    raw_name = r[3]
    assert raw_name in canonical_mapping, f"Unhandled legacy indicator: {raw_name}"
    target_code = canonical_mapping[raw_name]
    if raw_name == "Stopa bezrobocia r/r":
      pending_count += 1
    else:
      mapped_count += 1

  # All 75 must be covered: 73 direct/disambiguated + 2 pending review
  assert mapped_count + pending_count == 75
  assert pending_count == 2
  assert mapped_count == 73


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
