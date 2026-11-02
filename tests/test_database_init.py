import sqlite3
import pytest
from modules.database import EconomyDatabase


def test_init_db_creates_required_tables(isolated_db, isolated_db_path):
    """Verify that EconomyDatabase.init_db creates all expected tables."""
    conn = sqlite3.connect(isolated_db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    table_names = {row[0] for row in cursor.fetchall()}
    conn.close()

    expected_tables = {"trusted_sources", "collected_indicators", "generated_reports"}
    assert expected_tables.issubset(table_names)


def test_init_db_column_schema(isolated_db, isolated_db_path):
    """Verify the columns of the created tables match expected baseline schema."""
    conn = sqlite3.connect(isolated_db_path)
    cursor = conn.cursor()

    # Check collected_indicators columns
    cursor.execute("PRAGMA table_info(collected_indicators)")
    ind_cols = {row[1]: (row[2], row[4]) for row in cursor.fetchall()}  # name: (type, default_value)
    
    expected_ind_cols = [
        "id", "agent_name", "country", "indicator_name", "value",
        "period", "source_name", "page_info", "created_at",
        "previous_value", "trend_direction"
    ]
    for col in expected_ind_cols:
        assert col in ind_cols, f"Column {col} missing in collected_indicators"

    assert ind_cols["previous_value"][1] == "'Brak danych'"
    assert ind_cols["trend_direction"][1] == "'brak danych'"

    # Check trusted_sources columns
    cursor.execute("PRAGMA table_info(trusted_sources)")
    sources_cols = {row[1] for row in cursor.fetchall()}
    assert {"id", "agent_name", "country", "name", "url", "description", "created_at"}.issubset(sources_cols)

    # Check generated_reports columns
    cursor.execute("PRAGMA table_info(generated_reports)")
    reports_cols = {row[1] for row in cursor.fetchall()}
    assert {"id", "country", "report_date", "periods_summary", "content_markdown", "created_at"}.issubset(reports_cols)

    conn.close()


def test_init_db_idempotency(isolated_db, isolated_db_path):
    """Verify calling init_db multiple times does not duplicate columns or fail."""
    # Call init_db multiple times
    isolated_db.init_db()
    isolated_db.init_db()

    conn = sqlite3.connect(isolated_db_path)
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(collected_indicators)")
    cols = [row[1] for row in cursor.fetchall()]
    conn.close()

    assert cols.count("previous_value") == 1
    assert cols.count("trend_direction") == 1


def test_init_db_self_migration(tmp_path):
    """Verify that if collected_indicators exists without previous_value and trend_direction,

    init_db automatically performs ALTER TABLE migration.
    """
    db_file = str(tmp_path / "old_schema.db")
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()
    # Create old version of collected_indicators without previous_value and trend_direction
    cursor.execute("""
        CREATE TABLE collected_indicators (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_name TEXT,
            country TEXT,
            indicator_name TEXT,
            value TEXT,
            period TEXT,
            source_name TEXT,
            page_info TEXT,
            created_at TIMESTAMP
        )
    """)
    cursor.execute("""
        INSERT INTO collected_indicators (agent_name, country, indicator_name, value, period, source_name, page_info)
        VALUES ('TestAgent', 'Polska', 'PKB', '3.5%', '2026', 'GUS', 'http://example.com')
    """)
    conn.commit()
    conn.close()

    # Instantiate EconomyDatabase pointing to old_schema.db
    class CustomOldDB(EconomyDatabase):
        def __init__(self, path):
            self.db_path = path
            self.init_db()

    custom_db = CustomOldDB(db_file)

    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(collected_indicators)")
    cols = [row[1] for row in cursor.fetchall()]
    cursor.execute("SELECT previous_value, trend_direction FROM collected_indicators WHERE id=1")
    row = cursor.fetchone()
    conn.close()

    assert "previous_value" in cols
    assert "trend_direction" in cols
    assert row[0] == "Brak danych"
    assert row[1] == "brak danych"


def test_baseline_database_integrity(baseline_db_ro_connection):
    """Verify that instance/economy_agent.db retains the exact required baseline record counts."""
    cursor = baseline_db_ro_connection.cursor()

    cursor.execute("SELECT count(*) FROM collected_indicators")
    indicators_count = cursor.fetchone()[0]

    cursor.execute("SELECT count(*) FROM trusted_sources")
    sources_count = cursor.fetchone()[0]

    cursor.execute("SELECT count(*) FROM generated_reports")
    reports_count = cursor.fetchone()[0]

    assert indicators_count == 75, f"Expected 75 indicators, got {indicators_count}"
    assert sources_count == 10, f"Expected 10 trusted sources, got {sources_count}"
    assert reports_count == 6, f"Expected 6 generated reports, got {reports_count}"
