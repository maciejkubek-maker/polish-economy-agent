"""
Testy integracyjne dla TASK-06 — Pełny potok danych v2 i generowanie raportów.
Plik: tests/test_pipeline_v2.py

Weryfikuje:
1. End-to-end potok: pobieranie -> walidacja -> zapis v2 -> Tavily search -> analiza AI -> raport.
2. Zapis w SQLite v2: reguła append-only, wersjonowanie (version_number, supersedes_id), automatyczna aktualizacja current_observations.
3. Idempotencję zapisu i powtórnych przebiegów.
4. Odporność na częściowe awarie API (np. unmapped variable, 404, timeout).
5. Oznaczanie braków danych jako 'Brak danych' zamiast halucynacji/zgadywania.
6. Kategoryzację źródeł wyszukiwania (OFFICIAL_COMMUNIQUE vs MEDIA_COMMENTARY).
7. Integrację z aplikacją Flask (serve_report z v2, fallback do v1 i pliku).
8. Bezwzględną nietykalność oryginalnej bazy legacy (instance/economy_agent.db).
9. Brak jakichkolwiek płatnych wywołań API podczas testów (100% offline).
"""

import hashlib
import os
import sqlite3
import pytest

import config
from app import server, set_db, set_storage_v2
from modules.connectors.base import MacroObservation, RawEvidence, VariableNotMappedError
from modules.evaluator import EconomyEvaluator
from modules.pipeline_v2 import MacroPipelineV2, PipelineResult
from modules.search_service import WebSearchService, classify_source_url
from modules.storage_v2 import SQLiteV2Storage


BASELINE_DB_PATH = os.path.abspath(os.path.join("instance", "economy_agent.db"))
EXPECTED_BASELINE_SHA256 = "e6c5f318ffe1eceeb34191a7a74ec9f7f7de6069c4f298850792734277ecde3b"
EXPECTED_BASELINE_SIZE = 73728


@pytest.fixture
def temp_v2_db(tmp_path):
    """Tworzy wyizolowaną bazę SQLite v2 w folderze tymczasowym."""
    db_file = tmp_path / "test_pipeline_v2.db"
    storage = SQLiteV2Storage(db_path=str(db_file))
    yield storage


# ==============================================================================
# 1. TESTY END-TO-END PEŁNEGO POTOKU DANYCH V2
# ==============================================================================

def test_pipeline_v2_full_run_offline(temp_v2_db, tmp_path):
    """Weryfikuje pełny potok v2 w trybie offline ze wszystkimi krokami i 6 sekcjami raportu."""
    report_html_file = tmp_path / "test_out_report.html"
    pipeline = MacroPipelineV2(db=temp_v2_db, offline_mode=True)

    result = pipeline.run(
        country="Polska",
        output_html_path=str(report_html_file),
        force_refresh=True,
    )

    # 1. Wynik wykonania
    assert result.success is True
    assert result.status in ("COMPLETED", "PARTIAL")
    assert result.records_fetched > 0
    assert result.records_validated > 0
    assert result.evidence_count > 0
    assert result.observations_count > 0
    assert result.search_news_count > 0
    assert result.report_id is not None
    assert result.report_id.startswith("REP_V2_")

    # 2. Weryfikacja bazy SQLite v2
    assert temp_v2_db.count_table("ingestion_runs") >= 1
    assert temp_v2_db.count_table("source_evidence") >= result.evidence_count
    assert temp_v2_db.count_table("observations") >= result.observations_count
    assert temp_v2_db.count_table("current_observations") > 0
    assert temp_v2_db.count_table("reports") >= 1

    # 3. Weryfikacja sekcji raportu Markdown
    md = result.report_markdown
    assert "# RAPORT KONDYCJI GOSPODARCZEJ: Polska" in md
    assert "## 1. Analiza Trendów w Dostępnym Okresie" in md
    assert "## 2. Zagrożenia i Ryzyka Makroekonomiczne" in md
    assert "## 3. Co to oznacza dla Kowalskiego? (Perspektywa Obywatela)" in md
    assert "- **Kredyty i Raty:**" in md
    assert "- **Ceny i Zakupy:**" in md
    assert "- **Praca i Zarobki:**" in md
    assert "## 4. Co to oznacza dla Przedsiębiorców?" in md
    assert "## 5. Podsumowanie i Realistyczny Werdykt" in md
    assert "## 6. Źródła danych i Metodologia" in md

    # 4. Weryfikacja liczb makroekonomicznych w raporcie
    assert "4.345" in md  # EUR/PLN
    assert "4.0215" in md  # USD/PLN
    assert "5.75%" in md  # Stopa referencyjna NBP
    assert "4.0%" in md or "4.0" in md  # HICP
    assert "2.9%" in md  # Bezrobocie zharmonizowane
    assert "1.1%" in md  # PKB kw/kw
    assert "3.9%" in md  # PKB r/r
    assert "5.0%" in md  # Stopa bezrobocia rejestrowanego
    assert "3.1%" in md  # CPI DBW

    # 5. Odnośniki do źródeł
    assert "[1]" in md
    assert "[2]" in md
    assert "Narodowy Bank Polski" in md or "NBP" in md
    assert "GUS" in md
    assert "Eurostat" in md

    # 6. Weryfikacja pliku HTML na dysku
    assert report_html_file.exists()
    html_text = report_html_file.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in html_text
    assert "<title>Raport Kondycji Gospodarczej: Polska</title>" in html_text
    assert "<script>" not in html_text


# ==============================================================================
# 2. TESTY APPEND-ONLY I WERSJONOWANIA W BAZIE V2
# ==============================================================================

def test_v2_storage_append_only_and_versioning(temp_v2_db):
    """Sprawdza, że tabela observations blokuje UPDATE/DELETE i poprawnie inkrementuje version_number."""
    run_id = temp_v2_db.start_ingestion_run(provider="MANUAL", run_type="TRIGGERED")

    evi = RawEvidence(
        evidence_id="EVI_TEST_1",
        source_id="SRC_NBP",
        source_url="https://api.nbp.pl/test",
        document_type="API_RESPONSE",
        content_hash="hash123",
        payload_text="raw",
        status_code=200,
        retrieved_at_utc="2026-11-02T10:00:00Z",
    )
    temp_v2_db.save_evidence(evi, run_id=run_id)

    obs1 = MacroObservation(
        observation_id="OBS_V1",
        indicator_code="PL_FX_EUR_PLN",
        country_code="PL",
        period_start="2026-10-30",
        period_end="2026-10-30",
        frequency="DAILY",
        value_decimal="4.3000",
        unit_code="EUR_PLN",
        revision_type="FINAL",
        status="VERIFIED",
        evidence_id="EVI_TEST_1",
    )
    temp_v2_db.save_observation(obs1, run_id=run_id)

    # 1. Sprawdzenie version 1 w observations i current_observations
    conn = temp_v2_db.get_connection()
    c_row = conn.execute(
        "SELECT value_decimal, version_number, observation_id FROM current_observations WHERE indicator_code = 'PL_FX_EUR_PLN'"
    ).fetchone()
    assert c_row[0] == "4.3000"
    assert c_row[1] == 1
    assert c_row[2] == "OBS_V1"

    # 2. Próba UPDATE na tabeli observations MUSI rzucić wyjątek (trigger trg_observations_prevent_update)
    with pytest.raises(sqlite3.IntegrityError, match="append-only: modyfikacja"):
        conn.execute("UPDATE observations SET value_decimal = '4.9999' WHERE observation_id = 'OBS_V1'")

    # 3. Próba DELETE na tabeli observations MUSI rzucić wyjątek (trigger trg_observations_prevent_delete)
    with pytest.raises(sqlite3.IntegrityError, match="append-only: usuwanie"):
        conn.execute("DELETE FROM observations WHERE observation_id = 'OBS_V1'")
    conn.close()

    # 4. Dodanie rewizji dla tego samego okresu: wersja 2 (append-only)
    obs2 = MacroObservation(
        observation_id="OBS_V2",
        indicator_code="PL_FX_EUR_PLN",
        country_code="PL",
        period_start="2026-10-30",
        period_end="2026-10-30",
        frequency="DAILY",
        value_decimal="4.3500",
        unit_code="EUR_PLN",
        revision_type="REVISED",
        status="VERIFIED",
        evidence_id="EVI_TEST_1",
    )
    temp_v2_db.save_observation(obs2, run_id=run_id)

    # 5. Sprawdzenie, że observations ma 2 rekordy (historia nienaruszona)
    history = temp_v2_db.get_observation_history("PL_FX_EUR_PLN")
    assert len(history) == 2
    assert history[0]["version_number"] == 1
    assert history[0]["value_decimal"] == "4.3000"
    assert history[1]["version_number"] == 2
    assert history[1]["value_decimal"] == "4.3500"
    assert history[1]["supersedes_id"] == "OBS_V1"

    # 6. current_observations zostało automatycznie zaktualizowane do wersji 2
    conn2 = temp_v2_db.get_connection()
    c_row2 = conn2.execute(
        "SELECT value_decimal, version_number, observation_id FROM current_observations WHERE indicator_code = 'PL_FX_EUR_PLN'"
    ).fetchone()
    conn2.close()
    assert c_row2[0] == "4.3500"
    assert c_row2[1] == 2
    assert c_row2[2] == "OBS_V2"


# ==============================================================================
# 3. TESTY IDEMPOTENCJI WIELOKROTNEGO URUCHOMIENIA POTOKU
# ==============================================================================

def test_pipeline_v2_idempotency(temp_v2_db):
    """Sprawdza, że ponowne uruchomienie potoku nie uszkadza danych ani nie rzuca błędów unikalności."""
    pipeline = MacroPipelineV2(db=temp_v2_db, offline_mode=True)

    res1 = pipeline.run(country="Polska", force_refresh=True)
    assert res1.success is True

    obs_count_1 = temp_v2_db.count_table("observations")
    current_count_1 = temp_v2_db.count_table("current_observations")

    # Drugi przebieg
    res2 = pipeline.run(country="Polska", force_refresh=True)
    assert res2.success is True

    obs_count_2 = temp_v2_db.count_table("observations")
    current_count_2 = temp_v2_db.count_table("current_observations")

    # Liczba current_observations pozostaje stabilna
    assert current_count_2 == current_count_1
    # Zarejestrowano 2 przebiegi w ingestion_runs
    assert temp_v2_db.count_table("ingestion_runs") == 2


# ==============================================================================
# 4. OBSŁUGA CZĘŚCIOWYCH AWARII API I BRAK ZGADYWANIA
# ==============================================================================

def test_pipeline_v2_partial_failure_graceful_handling(temp_v2_db, monkeypatch):
    """Sprawdza, że awaria pojedynczego konektora/endpointu nie wywala potoku i oznacza brak danych."""
    pipeline = MacroPipelineV2(db=temp_v2_db, offline_mode=True)

    # Symulacja awarii pobierania HICP Eurostatu
    def mock_fetch_hicp_fail():
        raise ConnectionResetError("Eurostat API 503 Service Unavailable")

    monkeypatch.setattr(pipeline.eurostat, "fetch_hicp", mock_fetch_hicp_fail)

    result = pipeline.run(country="Polska", force_refresh=True)

    # Potok kończy się częściowym sukcesem (PARTIAL)
    assert result.success is True
    assert result.status == "PARTIAL"
    assert any("Eurostat HICP" in err for err in result.errors)
    assert len(result.quality_events) > 0

    # Raport wygenerował się mimo awarii jednego wskaźnika
    assert result.report_id is not None
    assert "## 1. Analiza Trendów w Dostępnym Okresie" in result.report_markdown

    # Wskaźnik, który uległ awarii, w raporcie ma 'Brak danych' zamiast zmyślonej liczby
    assert "Brak danych" in result.report_markdown


# ==============================================================================
# 5. KATEGORYZACJA ŹRÓDEŁ WYSZUKIWANIA (OFFICIAL VS MEDIA)
# ==============================================================================

def test_tavily_search_news_classification():
    """Weryfikuje automatyczną klasyfikację domen na komunikaty oficjalne i komentarze medialne."""
    official_urls = [
        "https://stat.gov.pl/obszary-tematyczne/ceny-handel/inflacja.html",
        "https://www.stat.gov.pl/komunikaty/bezrobocie",
        "https://nbp.pl/polityka-pieniezna/decyzje-rpp/",
        "https://ec.europa.eu/eurostat/statistics/gdp",
    ]
    media_urls = [
        "https://www.bankier.pl/wiadomosc/inflacja-w-polsce-9281.html",
        "https://businessinsider.com.pl/gospodarka/pkb-polski/83k9",
        "https://money.pl/gospodarka/stopy-procentowe",
    ]

    for u in official_urls:
        assert classify_source_url(u) == "OFFICIAL_COMMUNIQUE"

    for u in media_urls:
        assert classify_source_url(u) == "MEDIA_COMMENTARY"


def test_tavily_search_offline_results_stored_as_evidence(temp_v2_db):
    """Sprawdza, że wycinki wyszukiwania są poprawnie rejestrowane jako source_evidence."""
    pipeline = MacroPipelineV2(db=temp_v2_db, offline_mode=True)
    run_id = temp_v2_db.start_ingestion_run(provider="TAVILY_SEARCH", run_type="TRIGGERED")

    news = pipeline.search_enrichment("Polska", run_id)
    temp_v2_db.finish_ingestion_run(run_id, "COMPLETED")

    assert len(news) >= 3

    conn = temp_v2_db.get_connection()
    snippets = conn.execute(
        "SELECT count(*) FROM source_evidence WHERE document_type = 'SEARCH_SNIPPET' AND source_id = 'SRC_TAVILY'"
    ).fetchone()[0]
    conn.close()

    assert snippets >= len(news)


# ==============================================================================
# 6. INTEGRACJA Z APLIKACJĄ FLASK (SERVE_REPORT Z V2)
# ==============================================================================

def test_flask_serve_report_from_v2(temp_v2_db):
    """Weryfikuje, że endpoint serve_report w app.py poprawnie serwuje najnowszy raport z SQLite v2."""
    pipeline = MacroPipelineV2(db=temp_v2_db, offline_mode=True)
    result = pipeline.run(country="Polska", force_refresh=True)
    assert result.success is True

    # Wstrzyknięcie bazy v2 do aplikacji
    set_storage_v2(temp_v2_db)
    set_db(None)

    try:
        with server.test_client() as client:
            resp = client.get("/")
            assert resp.status_code == 200
            html_text = resp.get_data(as_text=True)

            assert "<!DOCTYPE html>" in html_text
            assert "<title>Raport Kondycji Gospodarczej: Polska</title>" in html_text
            assert "Analiza Trendów w Dostępnym Okresie" in html_text
            assert "4.345" in html_text
            assert "5.75%" in html_text
    finally:
        set_storage_v2(None)


def test_demo_import_without_api_keys_is_offline_by_default():
    """README demo starts without keys and cannot silently enable paid services."""
    import subprocess
    import sys

    env = os.environ.copy()
    env["PYTHON_DOTENV_DISABLED"] = "1"
    env.pop("GOOGLE_API_KEY", None)
    env.pop("OPENAI_API_KEY", None)
    env.pop("TAVILY_API_KEY", None)
    env.pop("OFFLINE_MODE", None)

    result = subprocess.run(
        [sys.executable, "-c", "import config; assert config.OFFLINE_MODE is True"],
        cwd=os.path.dirname(os.path.dirname(__file__)),
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


# ==============================================================================
# 7. BEZWZGLĘDNA NIETYKALNOŚĆ ORYGINALNEJ BAZY LEGACY
# ==============================================================================

def test_legacy_database_is_strictly_untouched():
    """Weryfikuje, że oryginalna baza instance/economy_agent.db nie uległa najmniejszej modyfikacji."""
    assert os.path.exists(BASELINE_DB_PATH), f"Plik bazy legacy nie istnieje: {BASELINE_DB_PATH}"

    current_size = os.path.getsize(BASELINE_DB_PATH)
    assert current_size == EXPECTED_BASELINE_SIZE, (
        f"Rozmiar bazy uległ zmianie! Oczekiwano {EXPECTED_BASELINE_SIZE}, jest {current_size}"
    )

    with open(BASELINE_DB_PATH, "rb") as f:
        current_sha = hashlib.sha256(f.read()).hexdigest().lower()

    assert current_sha == EXPECTED_BASELINE_SHA256, (
        f"KRYTYCZNE NARUSZENIE: SHA-256 bazy uległ modyfikacji!\nOczekiwano: {EXPECTED_BASELINE_SHA256}\nAktualny:   {current_sha}"
    )


def test_sqlite_v2_storage_blocks_legacy_db_path():
    """Weryfikuje, że próba otwarcia instance/economy_agent.db jako bazy v2 rzuca krytyczny błąd."""
    with pytest.raises(ValueError, match="KRYTYCZNE NARUSZENIE BEZPIECZEŃSTWA"):
        SQLiteV2Storage(db_path=BASELINE_DB_PATH)
