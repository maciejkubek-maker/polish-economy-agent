import sqlite3
import pytest
from modules.database import EconomyDatabase
from modules.data_fetcher import IndicatorItem


def test_update_record_when_composite_key_matches(isolated_db, isolated_db_path):
    """Test that save_indicators updates existing row when (agent_name, country, indicator_name, period) matches."""
    initial_item = IndicatorItem(
        indicator_name="Stopa bezrobocia",
        value="5.80%",
        period="VII 2026",
        previous_value="5.70%",
        trend_direction="wzrost",
        source_name="GUS Initial",
        page_info="https://initial.stat.gov.pl",
    )
    isolated_db.save_indicators("AgentX", "Polska", [initial_item])

    conn = sqlite3.connect(isolated_db_path)
    cur = conn.cursor()
    cur.execute("SELECT id, value, previous_value, trend_direction, source_name, created_at FROM collected_indicators")
    initial_row = cur.fetchone()
    initial_id = initial_row[0]
    initial_created_at = initial_row[5]
    conn.close()

    updated_item = IndicatorItem(
        indicator_name="Stopa bezrobocia",
        value="5.85%",
        period="VII 2026",
        previous_value="5.80%",
        trend_direction="stabilizacja",
        source_name="GUS Updated",
        page_info="https://updated.stat.gov.pl",
    )
    isolated_db.save_indicators("AgentX", "Polska", [updated_item])

    conn = sqlite3.connect(isolated_db_path)
    cur = conn.cursor()
    cur.execute("SELECT id, value, previous_value, trend_direction, source_name, page_info, created_at FROM collected_indicators")
    all_rows = cur.fetchall()
    conn.close()

    assert len(all_rows) == 1, "Expected record to be updated in-place, not inserted as a duplicate"
    row = all_rows[0]
    assert row[0] == initial_id
    assert row[1] == "5.85%"
    assert row[2] == "5.80%"
    assert row[3] == "stabilizacja"
    assert row[4] == "GUS Updated"
    assert row[5] == "https://updated.stat.gov.pl"


def test_different_agents_produce_separate_records(isolated_db, isolated_db_path):
    """Test that GeminiAgent and GPTAgent save separate rows for the exact same indicator and period."""
    item1 = IndicatorItem(
        indicator_name="PKB r/r",
        value="3.90%",
        period="II kw. 2026",
        source_name="GUS",
        page_info="https://stat.gov.pl",
        trend_direction="wzrost",
    )
    isolated_db.save_indicators("GeminiAgent", "Polska", [item1])

    item2 = IndicatorItem(
        indicator_name="PKB r/r",
        value="3.92%",
        period="II kw. 2026",
        source_name="GUS",
        page_info="https://stat.gov.pl",
        trend_direction="wzrost",
    )
    isolated_db.save_indicators("GPTAgent", "Polska", [item2])

    conn = sqlite3.connect(isolated_db_path)
    cur = conn.cursor()
    cur.execute("SELECT agent_name, value FROM collected_indicators WHERE indicator_name='PKB r/r'")
    rows = cur.fetchall()
    conn.close()

    assert len(rows) == 2
    agents = {r[0] for r in rows}
    assert agents == {"GeminiAgent", "GPTAgent"}


def test_indicator_name_casing_sensitivity_creates_duplicate_entries(isolated_db, isolated_db_path):
    """Demonstrate existing behavior: case differences in indicator_name bypass update and create separate rows."""
    item1 = IndicatorItem(
        indicator_name="Przeciętne Wynagrodzenia",
        value="9233.13 zł",
        period="VI 2026",
        source_name="GUS",
        page_info="https://stat.gov.pl",
        trend_direction="spadek",
    )
    item2 = IndicatorItem(
        indicator_name="Przeciętne wynagrodzenia",  # lowercase 'w'
        value="9233.13 zł",
        period="VI 2026",
        source_name="GUS",
        page_info="https://stat.gov.pl",
        trend_direction="spadek",
    )

    isolated_db.save_indicators("AgentA", "Polska", [item1])
    isolated_db.save_indicators("AgentA", "Polska", [item2])

    conn = sqlite3.connect(isolated_db_path)
    cur = conn.cursor()
    cur.execute("SELECT id, indicator_name FROM collected_indicators")
    rows = cur.fetchall()
    conn.close()

    # Demonstrates that lack of name normalization causes separate rows
    assert len(rows) == 2
    assert {r[1] for r in rows} == {"Przeciętne Wynagrodzenia", "Przeciętne wynagrodzenia"}


def test_period_format_discrepancy_creates_duplicate_entries(isolated_db, isolated_db_path):
    """Demonstrate existing behavior: different period formats (e.g. 'VII 2026' vs 'lipiec 2026') create separate rows."""
    item_roman = IndicatorItem(
        indicator_name="Stopa bezrobocia",
        value="5.80%",
        period="VII 2026",
        source_name="GUS",
        page_info="https://stat.gov.pl",
        trend_direction="stabilizacja",
    )
    item_named = IndicatorItem(
        indicator_name="Stopa bezrobocia",
        value="5.80%",
        period="lipiec 2026",
        source_name="GUS",
        page_info="https://stat.gov.pl",
        trend_direction="stabilizacja",
    )

    isolated_db.save_indicators("AgentA", "Polska", [item_roman])
    isolated_db.save_indicators("AgentA", "Polska", [item_named])

    conn = sqlite3.connect(isolated_db_path)
    cur = conn.cursor()
    cur.execute("SELECT period FROM collected_indicators WHERE indicator_name='Stopa bezrobocia'")
    periods = [r[0] for r in cur.fetchall()]
    conn.close()

    assert len(periods) == 2
    assert "VII 2026" in periods
    assert "lipiec 2026" in periods


def test_update_behavior_with_preexisting_duplicates(isolated_db, isolated_db_path):
    """Demonstrate existing behavior: if duplicate rows already exist,

    save_indicators only updates the first row found by fetchone().
    """
    conn = sqlite3.connect(isolated_db_path)
    cur = conn.cursor()
    # Manually insert 2 identical rows into the table
    for val in ["5.0%", "5.0%"]:
        cur.execute("""
            INSERT INTO collected_indicators (agent_name, country, indicator_name, period, value, source_name, page_info)
            VALUES ('AgentX', 'Polska', 'Wskaźnik D', '2026', ?, 'Src', 'http://src')
        """, (val,))
    conn.commit()
    conn.close()

    # Now run save_indicators with updated value
    new_item = IndicatorItem(
        indicator_name="Wskaźnik D",
        value="6.5%",
        period="2026",
        source_name="Src",
        page_info="http://src",
        trend_direction="wzrost",
    )
    isolated_db.save_indicators("AgentX", "Polska", [new_item])

    conn = sqlite3.connect(isolated_db_path)
    cur = conn.cursor()
    cur.execute("SELECT id, value FROM collected_indicators WHERE indicator_name='Wskaźnik D' ORDER BY id ASC")
    rows = cur.fetchall()
    conn.close()

    assert len(rows) == 2
    # First row is updated, second duplicate remains stale
    assert rows[0][1] == "6.5%"
    assert rows[1][1] == "5.0%"
