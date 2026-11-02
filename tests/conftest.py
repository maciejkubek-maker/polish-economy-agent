import os
import sqlite3
import pytest

# Ensure dummy keys are present in environment BEFORE config.py or other modules are loaded
# so tests can run completely offline without real API keys.
os.environ["GOOGLE_API_KEY"] = os.environ.get("GOOGLE_API_KEY") or "mock-google-api-key-offline"
os.environ["OPENAI_API_KEY"] = os.environ.get("OPENAI_API_KEY") or "mock-openai-api-key-offline"
os.environ["TAVILY_API_KEY"] = os.environ.get("TAVILY_API_KEY") or "mock-tavily-api-key-offline"

from modules.database import EconomyDatabase
from modules.data_fetcher import IndicatorItem
from modules.sources import CountrySourcesResponse, EconomicSource


@pytest.fixture
def isolated_db_path(tmp_path):
    """Provides a dedicated temporary database file path."""
    return str(tmp_path / "test_economy_agent.db")


@pytest.fixture
def isolated_db(isolated_db_path, monkeypatch):
    """Creates a fully isolated EconomyDatabase instance in a temporary folder,

    ensuring instance/economy_agent.db is never touched.
    """
    def mock_init(self, db_name: str = "economy_agent.db"):
        self.db_path = isolated_db_path
        self.init_db()

    monkeypatch.setattr(EconomyDatabase, "__init__", mock_init)
    db = EconomyDatabase()
    yield db


@pytest.fixture
def sample_indicator_items():
    """Provides sample indicator item domain objects for tests."""
    return [
        IndicatorItem(
            indicator_name="Stopa bezrobocia",
            value="5.80%",
            period="VII 2026",
            previous_value="5.80%",
            trend_direction="stabilizacja",
            source_name="GUS",
            page_info="https://stat.gov.pl/rynek-pracy",
        ),
        IndicatorItem(
            indicator_name="Inflacja CPI r/r",
            value="3.40%",
            period="VIII 2026",
            previous_value="3.10%",
            trend_direction="wzrost",
            source_name="GUS",
            page_info="https://stat.gov.pl/inflacja",
        ),
        IndicatorItem(
            indicator_name="PKB r/r",
            value="3.90%",
            period="II kw. 2026",
            previous_value="2.00%",
            trend_direction="wzrost",
            source_name="GUS",
            page_info="https://stat.gov.pl/pkb",
        ),
    ]


@pytest.fixture
def sample_sources_response():
    """Provides a sample CountrySourcesResponse object."""
    return CountrySourcesResponse(
        country="Polska",
        sources=[
            EconomicSource(
                name="GUS",
                url="https://stat.gov.pl",
                description="Główny Urząd Statystyczny - oficjalne dane",
            ),
            EconomicSource(
                name="NBP",
                url="https://nbp.pl",
                description="Narodowy Bank Polski - stopy i inflacja",
            ),
        ],
    )


@pytest.fixture
def baseline_db_ro_connection():
    """Read-only SQLite connection directly to the baseline database file for verification."""
    conn = sqlite3.connect("file:instance/economy_agent.db?mode=ro", uri=True)
    yield conn
    conn.close()
