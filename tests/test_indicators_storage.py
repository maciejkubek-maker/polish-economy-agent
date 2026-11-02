import sqlite3
import pytest
from modules.database import EconomyDatabase
from modules.evaluator import EconomyEvaluator
from modules.data_fetcher import IndicatorItem
from modules.sources import CountrySourcesResponse, EconomicSource


def test_save_and_read_indicators(isolated_db, isolated_db_path, sample_indicator_items):
    """Test saving indicators and verifying their persistence in SQLite."""
    isolated_db.save_indicators(
        agent_name="TestAgent",
        country="Polska",
        indicators=sample_indicator_items,
    )

    conn = sqlite3.connect(isolated_db_path)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT agent_name, country, indicator_name, value, period, previous_value, trend_direction, source_name, page_info 
        FROM collected_indicators 
        ORDER BY indicator_name ASC
    """)
    rows = cursor.fetchall()
    conn.close()

    assert len(rows) == 3
    # Check first row (Inflacja CPI r/r)
    assert rows[0][0] == "TestAgent"
    assert rows[0][1] == "Polska"
    assert rows[0][2] == "Inflacja CPI r/r"
    assert rows[0][3] == "3.40%"
    assert rows[0][4] == "VIII 2026"
    assert rows[0][5] == "3.10%"
    assert rows[0][6] == "wzrost"
    assert rows[0][7] == "GUS"


def test_fetch_timeline_data(isolated_db, monkeypatch, sample_indicator_items):
    """Test reading indicators through EconomyEvaluator.fetch_timeline_data."""
    isolated_db.save_indicators(
        agent_name="AgentA",
        country="Polska",
        indicators=sample_indicator_items,
    )

    evaluator = EconomyEvaluator()
    # Point evaluator db_path to isolated_db.db_path
    monkeypatch.setattr(evaluator, "db_path", isolated_db.db_path)

    timeline_map, all_rows = evaluator.fetch_timeline_data(country="Polska")

    assert len(all_rows) == 3
    assert "Stopa bezrobocia" in timeline_map
    assert "Inflacja CPI r/r" in timeline_map
    assert "PKB r/r" in timeline_map

    unemployment_points = timeline_map["Stopa bezrobocia"]
    assert len(unemployment_points) == 1
    assert unemployment_points[0]["value"] == "5.80%"
    assert unemployment_points[0]["period"] == "VII 2026"
    assert unemployment_points[0]["trend_direction"] == "stabilizacja"

    # Test non-existent country returns empty structure
    empty_map, empty_rows = evaluator.fetch_timeline_data(country="Atlantis")
    assert empty_map == {}
    assert empty_rows == []


def test_save_indicators_with_default_attributes(isolated_db, isolated_db_path):
    """Test saving indicator objects that lack previous_value or trend_direction attributes."""
    class MinimalIndicator:
        def __init__(self, name, val, period, source, page):
            self.indicator_name = name
            self.value = val
            self.period = period
            self.source_name = source
            self.page_info = page

    item = MinimalIndicator("PMI", "48.3", "VIII 2026", "Bankier.pl", "https://bankier.pl")
    isolated_db.save_indicators(agent_name="MinAgent", country="Polska", indicators=[item])

    conn = sqlite3.connect(isolated_db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT previous_value, trend_direction FROM collected_indicators WHERE indicator_name='PMI'")
    row = cursor.fetchone()
    conn.close()

    assert row[0] == "Brak danych"
    assert row[1] == "brak danych"


def test_sources_save_and_retrieve(isolated_db, sample_sources_response):
    """Test saving and retrieving trusted sources."""
    isolated_db.save_sources(sample_sources_response, agent_name="PolishEconomyAgent")

    retrieved = isolated_db.get_sources(country="Polska", agent_name="PolishEconomyAgent")
    assert retrieved is not None
    assert retrieved.country == "Polska"
    assert len(retrieved.sources) == 2
    assert retrieved.sources[0].name == "GUS"
    assert retrieved.sources[1].name == "NBP"

    # Non-existent query returns None
    assert isolated_db.get_sources(country="Niemcy", agent_name="PolishEconomyAgent") is None


def test_save_sources_overwrites_existing_for_agent_and_country(isolated_db, sample_sources_response):
    """Test that saving sources deletes prior sources for that country and agent."""
    isolated_db.save_sources(sample_sources_response, agent_name="PolishEconomyAgent")

    # Update with single source
    updated_response = CountrySourcesResponse(
        country="Polska",
        sources=[
            EconomicSource(name="Eurostat", url="https://ec.europa.eu", description="EU stats")
        ]
    )
    isolated_db.save_sources(updated_response, agent_name="PolishEconomyAgent")

    retrieved = isolated_db.get_sources(country="Polska", agent_name="PolishEconomyAgent")
    assert len(retrieved.sources) == 1
    assert retrieved.sources[0].name == "Eurostat"


def test_generated_report_save_and_get_latest(isolated_db):
    """Test saving and getting the latest generated report."""
    assert isolated_db.get_latest_report("Polska") is None

    isolated_db.save_generated_report(
        country="Polska",
        report_date="01.11.2026",
        periods_summary="Summary 1",
        markdown_text="# Report 1",
    )
    isolated_db.save_generated_report(
        country="Polska",
        report_date="02.11.2026",
        periods_summary="Summary 2",
        markdown_text="# Report 2",
    )

    latest = isolated_db.get_latest_report("Polska")
    assert latest is not None
    # row schema: report_date, periods_summary, content_markdown, created_at
    assert latest[0] == "02.11.2026"
    assert latest[1] == "Summary 2"
    assert latest[2] == "# Report 2"
