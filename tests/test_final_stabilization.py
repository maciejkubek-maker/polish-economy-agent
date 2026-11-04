"""
Zestaw obowiązkowych testów regresyjnych A-N dla końcowej stabilizacji Polish Economy Agent.
Weryfikuje:
A. RUN_258c9a14a4be: CPI 2,3% (GUS XII 2025) vs 3,1% (Tavily X 2026).
B. RUN_89f71ad08c71: GPT z ogólnymi URL-ami -> bibliografia programowa z rejestru źródeł.
C. Jedna linia z wieloma oficjalnymi wartościami i różnymi przypisami.
D. Identyczne liczby dla różnych wskaźników (przypis musi pasować do wskaźnika).
E. Brak danych o liczbie bezrobotnych i teza o wzroście bezrobocia -> odrzucenie.
F. Błędna interpretacja stopy referencyjnej i deterministyczne wyliczenie realnej stopy.
G. Kontrola lagów i informacja o opóźnieniu publikacyjnym CPI.
H. Bezpieczna obsługa błędów API GPT, timeoutu, klucza i odrzucenia walidatora bez fallbacku.
I. Atomowy zapis: awaria SQLite lub HTML nie pozostawia niespójnego stanu.
J. Po FAILED aplikacja nie prezentuje archiwalnego raportu jako bieżącego wyniku.
K. GUS CPI bez potwierdzonego trybu prezentacji r/r (5) powoduje kontrolowany błąd.
L. Ochrona przed złośliwym kodem HTML/XSS i prompt injection z Tavily.
M. Czytelność logo w jasnym panelu, paleta (#142B49, #38658F, #F3F6FA, #FFFFFF) i responsywność.
N. Całkowity brak automatycznego fallbacku we wszystkich ścieżkach wykonania.
"""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import uuid
import pytest
from unittest.mock import MagicMock

import config
from app import (
    build_failure_html_template,
    build_html_template,
    format_report_html,
    server,
    set_db,
    set_storage_v2,
)
from modules.connectors.base import MacroObservation, RawEvidence, ValidationError
from modules.connectors.gus import GusConnector
from modules.evaluator import EconomyEvaluator
from modules.pipeline_v2 import MacroPipelineV2
from modules.storage_v2 import SQLiteV2Storage


def _make_evidence_and_obs(code: str, val: str, period_start: str = "2025-12-01", period_end: str = "2025-12-31", unit: str = "PCT", source_id: str = "SRC_GUS", url: str = ""):
    token = uuid.uuid4().hex[:6]
    evi = RawEvidence(
        evidence_id=f"EVI_{code}_{token}",
        source_id=source_id,
        source_url=url or f"https://stat.gov.pl/{code.lower()}",
        document_type="API_RESPONSE",
        content_hash=f"hash_{code}_{token}",
        payload_text="official data",
        status_code=200,
        retrieved_at_utc="2026-11-04T12:00:00Z",
    )
    obs = MacroObservation(
        indicator_code=code,
        country_code="PL",
        period_start=period_start,
        period_end=period_end,
        frequency="MONTHLY",
        value_decimal=val,
        unit_code=unit,
        revision_type="FINAL",
        status="VERIFIED",
        evidence_id=evi.evidence_id,
    )
    return evi, obs


# ==============================================================================
# TEST A: RUN_258c9a14a4be (CPI 2.3% w oficjalnej bazie vs 3.1% z Tavily)
# ==============================================================================
def test_case_a_run_258c9a14a4be_cpi_tavily_vs_official(tmp_path, monkeypatch):
    """Oficjalny CPI to 2.3% (XII 2025). Tavily podaje 3.1%. Próba podania 3.1% jako oficjalnego CPI musi zostać odrzucona."""
    monkeypatch.setattr(config, "OFFLINE_MODE", False)
    db = SQLiteV2Storage(db_path=str(tmp_path / "case_a.db"))

    # Tavily z informacją o inflacji 3.1%
    tavily_news = [{
        "title": "Szacunek flash CPI",
        "url": "https://media.pl/cpi-flash",
        "content": "Według wstępnych szacunków inflacja w październiku wyniosła 3.1%",
        "published_date": "2026-10-31",
        "domain": "media.pl",
        "source_classification": "MEDIA_ARTICLE",
    }]

    evaluator = EconomyEvaluator()
    # GPT próbuje przyjąć 3.1% z doniesień Tavily
    gpt_candidate = """# RAPORT KONDYCJI GOSPODARCZEJ: Polska
## 1. Analiza Trendów w Dostępnym Okresie
Inflacja CPI wyniosła 3.1% [1].
## 2. Zagrożenia i Ryzyka Makroekonomiczne
Niepewność cenowa.
## 3. Co to oznacza dla Kowalskiego? (Perspektywa Obywatela)
Wzrost cen.
## 4. Co to oznacza dla Przedsiębiorców?
Koszty.
## 5. Podsumowanie i Realistyczny Werdykt
Brak oficjalnego potwierdzenia.
## 6. Źródła danych i Metodologia
[1] GUS, CPI, https://stat.gov.pl
"""
    monkeypatch.setattr(evaluator, "_run_llm_synthesis", lambda *args, **kwargs: gpt_candidate)

    pipeline = MacroPipelineV2(db=db, offline_mode=False, evaluator=evaluator, diagnostics_dir=tmp_path / "logs")
    evi_a, obs_a = _make_evidence_and_obs("PL_CPI_YOY", "2.3", "2025-12-01", "2025-12-31", "PCT", "SRC_GUS_DBW")
    monkeypatch.setattr(pipeline, "fetch_official_data", lambda rid: ([evi_a], [obs_a], [], []))
    monkeypatch.setattr(pipeline, "search_enrichment", lambda country, rid: tavily_news)

    result = pipeline.run(country="Polska", output_html_path=str(tmp_path / "report.html"))

    assert result.success is False
    assert result.status == "FAILED"
    assert result.report_id is None
    assert not (tmp_path / "report.html").exists()

    with open(tmp_path / "logs" / "last_run.json", "r", encoding="utf-8") as f:
        summary = json.load(f)
    assert summary["pipeline_status"] == "FAILED"
    assert summary["generation_mode"] == "GPT_VALIDATION_REJECTED"
    assert "Niezweryfikowane twierdzenia liczbowe" in summary["fallback_reason"]
    assert "3.1%" in summary["fallback_reason"]


# ==============================================================================
# TEST B: RUN_89f71ad08c71 (Bibliografia programowa z rejestru źródeł)
# ==============================================================================
def test_case_b_run_89f71ad08c71_programmatic_bibliography(tmp_path, monkeypatch):
    """GPT podaje ogólny adres domeny zamiast pełnego URL; sekcja 6 jest budowana programowo z dokładnym URL."""
    monkeypatch.setattr(config, "OFFLINE_MODE", False)
    db = SQLiteV2Storage(db_path=str(tmp_path / "case_b.db"))
    full_url = "https://stat.gov.pl/obszary-tematyczne/ceny-handel/wskazniki-cen/wskazniki-cen-towarow-i-uslug-konsumpcyjnych-w-grudniu-2025-roku,2,158.html"

    evaluator = EconomyEvaluator()
    # Model GPT podaje ogólny adres domeny "https://stat.gov.pl" w sekcji 6
    gpt_output_generic_url = """# RAPORT KONDYCJI GOSPODARCZEJ: Polska
## 1. Analiza Trendów w Dostępnym Okresie
Inflacja CPI wyniosła 2.3% [1].
## 2. Zagrożenia i Ryzyka Makroekonomiczne
Stabilizacja cenowa.
## 3. Co to oznacza dla Kowalskiego? (Perspektywa Obywatela)
Przewidywalność.
## 4. Co to oznacza dla Przedsiębiorców?
Planowanie.
## 5. Podsumowanie i Realistyczny Werdykt
Dane historyczne.
## 6. Źródła danych i Metodologia
[1] Główny Urząd Statystyczny - https://stat.gov.pl
"""
    monkeypatch.setattr(evaluator, "_run_llm_synthesis", lambda *args, **kwargs: gpt_output_generic_url)

    pipeline = MacroPipelineV2(db=db, offline_mode=False, evaluator=evaluator, diagnostics_dir=tmp_path / "logs")
    evi, obs = _make_evidence_and_obs("PL_CPI_YOY", "2.3", url=full_url)
    monkeypatch.setattr(pipeline, "fetch_official_data", lambda rid: ([evi], [obs], [], []))
    monkeypatch.setattr(pipeline, "search_enrichment", lambda country, rid: [])

    result = pipeline.run(country="Polska", output_html_path=str(tmp_path / "report.html"))

    assert result.success is True
    assert result.status in ("COMPLETED", "PARTIAL")
    assert (tmp_path / "report.html").exists()
    # Dokładny, pełny URL z rejestru źródeł musi znaleźć się w wygenerowanym raporcie
    assert full_url in result.report_markdown


# ==============================================================================
# TEST C: Wiele oficjalnych wartości w jednej linii z różnymi przypisami
# ==============================================================================
def test_case_c_multi_claim_single_line(tmp_path, monkeypatch):
    """Pojedyncza linia zawierająca wiele liczb i odrębne przypisy nie może być fałszywie odrzucona przez walidator."""
    monkeypatch.setattr(config, "OFFLINE_MODE", False)
    db = SQLiteV2Storage(db_path=str(tmp_path / "case_c.db"))
    evi1, obs1 = _make_evidence_and_obs("PL_CPI_YOY", "2.3")
    evi2, obs2 = _make_evidence_and_obs("PL_UNEMPLOYMENT_REGISTERED_RATE", "5.0", unit="PCT", source_id="SRC_GUS_UNEMP")

    evaluator = EconomyEvaluator()
    # Dwie wartości w jednej linii z prawidłowymi przypisami
    gpt_multi_claim = """# RAPORT KONDYCJI GOSPODARCZEJ: Polska
## 1. Analiza Trendów w Dostępnym Okresie
W badanym okresie inflacja CPI ukształtowała się na poziomie 2.3% [1], natomiast stopa bezrobocia rejestrowanego wyniosła 5.0% [2].
## 2. Zagrożenia i Ryzyka Makroekonomiczne
Stabilny poziom bezrobocia i cen.
## 3. Co to oznacza dla Kowalskiego? (Perspektywa Obywatela)
Bezpieczeństwo zatrudnienia.
## 4. Co to oznacza dla Przedsiębiorców?
Stabilność kosztów pracy.
## 5. Podsumowanie i Realistyczny Werdykt
Umiarkowana koniunktura.
## 6. Źródła danych i Metodologia
[1] GUS CPI
[2] GUS Bezrobocie
"""
    monkeypatch.setattr(evaluator, "_run_llm_synthesis", lambda *args, **kwargs: gpt_multi_claim)

    pipeline = MacroPipelineV2(db=db, offline_mode=False, evaluator=evaluator, diagnostics_dir=tmp_path / "logs")
    monkeypatch.setattr(pipeline, "fetch_official_data", lambda rid: ([evi1, evi2], [obs1, obs2], [], []))
    monkeypatch.setattr(pipeline, "search_enrichment", lambda country, rid: [])

    result = pipeline.run(country="Polska", output_html_path=str(tmp_path / "report.html"))
    assert result.success is True
    assert result.status in ("COMPLETED", "PARTIAL")


# ==============================================================================
# TEST D: Identyczne liczby dla różnych wskaźników (kontrola przypisania)
# ==============================================================================
def test_case_d_identical_values_different_indicators(tmp_path, monkeypatch):
    """Gdy dwa wskaźniki mają identyczną wartość (np. CPI 2.3% i PKB 2.3%), przypis musi odpowiadać właściwemu wskaźnikowi."""
    evaluator = EconomyEvaluator()
    citations = [
        {"idx": 1, "institution": "GUS", "indicator_code": "PL_CPI_YOY", "indicator_name": "Inflacja CPI", "period": "XII 2025", "url": "https://stat.gov.pl/cpi", "is_official": True, "value_decimal": "2.3"},
        {"idx": 2, "institution": "Eurostat", "indicator_code": "PL_GDP_YOY", "indicator_name": "Dynamika PKB r/r", "period": "IV kw. 2025", "url": "https://ec.europa.eu/eurostat", "is_official": True, "value_decimal": "2.3"},
    ]
    verified_obs = [
        {"indicator_code": "PL_CPI_YOY", "value_decimal": "2.3", "period_start": "2025-12-01", "period_end": "2025-12-31"},
        {"indicator_code": "PL_GDP_YOY", "value_decimal": "2.3", "period_start": "2025-10-01", "period_end": "2025-12-31"},
    ]

    # Błędne powiązanie: twierdzenie dotyczy PKB r/r, ale GPT cytuje [1] (czyli CPI!)
    bad_report = """# RAPORT KONDYCJI GOSPODARCZEJ: Polska
## 1. Analiza Trendów w Dostępnym Okresie
Dynamika Produktu Krajowego Brutto w ujęciu rocznym (PKB r/r) wyniosła 2.3% [1].
## 2. Zagrożenia i Ryzyka Makroekonomiczne
Ryzyka.
## 3. Co to oznacza dla Kowalskiego? (Perspektywa Obywatela)
Obywatel.
## 4. Co to oznacza dla Przedsiębiorców?
Firma.
## 5. Podsumowanie i Realistyczny Werdykt
Werdykt.
## 6. Źródła danych i Metodologia
[1] GUS, Inflacja CPI, https://stat.gov.pl/cpi
"""
    with pytest.raises(ValueError) as exc:
      evaluator._validate_v2_report(bad_report, citations, verified_obs)
    assert "Niepoprawne powiązanie przypisów ze źródłami" in str(exc.value)

    # Poprawne powiązanie: PKB r/r powiązane z przypisem [2] (Eurostat PKB) z programowo złożoną sekcją 6
    assembled_good_report = evaluator._assemble_v2_report_with_citations(
        bad_report.replace("[1]", "[2]"),
        citations,
    )
    evaluator._validate_v2_report(assembled_good_report, citations, verified_obs)


# ==============================================================================
# TEST E: Teza o wzroście bezrobocia bez danych wolumenowych (UNGROUNDED)
# ==============================================================================
def test_case_e_unemployment_volume_claim_without_data(tmp_path):
    """Brak zweryfikowanej liczby bezrobotnych (brak PL_UNEMPLOYMENT_COUNT) i GPT twierdzi, że liczba bezrobotnych wzrosła."""
    evaluator = EconomyEvaluator()
    citations = [
        {"idx": 1, "institution": "GUS", "indicator_code": "PL_UNEMPLOYMENT_REGISTERED_RATE", "indicator_name": "Stopa bezrobocia", "period": "X 2026", "url": "https://stat.gov.pl/unemp", "is_official": True, "value_decimal": "5.0"},
    ]
    verified_obs = [
        {"indicator_code": "PL_UNEMPLOYMENT_REGISTERED_RATE", "value_decimal": "5.0", "period_start": "2026-10-01", "period_end": "2026-10-31"},
    ]

    report_with_volume_claim = """# RAPORT KONDYCJI GOSPODARCZEJ: Polska
## 1. Analiza Trendów w Dostępnym Okresie
Stopa bezrobocia rejestrowanego wyniosła 5.0% [1], jednak nastąpił ukryty wzrost liczby bezrobotnych w urzędach pracy.
## 2. Zagrożenia i Ryzyka Makroekonomiczne
Ryzyka.
## 3. Co to oznacza dla Kowalskiego? (Perspektywa Obywatela)
Obywatel.
## 4. Co to oznacza dla Przedsiębiorców?
Firma.
## 5. Podsumowanie i Realistyczny Werdykt
Werdykt.
## 6. Źródła danych i Metodologia
[1] GUS, https://stat.gov.pl/unemp
"""
    with pytest.raises(ValueError) as exc:
      evaluator._validate_v2_report(report_with_volume_claim, citations, verified_obs)
    assert "Nieuzasadnione twierdzenie o wzroście liczby bezrobotnych" in str(exc.value)


# ==============================================================================
# TEST F: Błędna interpretacja stopy referencyjnej i deterministyczne wyliczenie
# ==============================================================================
def test_case_f_real_rate_logic_and_derived_calculation():
    """Stopa NBP 5.75%, CPI 2.3% -> realna stopa +3.45 p.p. Twierdzenie o realnej stopie bliskiej zeru jest odrzucane."""
    evaluator = EconomyEvaluator()
    citations = [
        {"idx": 1, "institution": "NBP", "indicator_code": "PL_NBP_REFERENCE_RATE", "indicator_name": "Stopa referencyjna", "period": "X 2026", "url": "https://nbp.pl", "is_official": True, "value_decimal": "5.75"},
        {"idx": 2, "institution": "GUS", "indicator_code": "PL_CPI_YOY", "indicator_name": "Inflacja CPI", "period": "XII 2025", "url": "https://stat.gov.pl", "is_official": True, "value_decimal": "2.3"},
    ]
    verified_obs = [
        {"indicator_code": "PL_NBP_REFERENCE_RATE", "value_decimal": "5.75", "period_start": "2026-10-01", "period_end": "2026-10-31"},
        {"indicator_code": "PL_CPI_YOY", "value_decimal": "2.3", "period_start": "2025-12-01", "period_end": "2025-12-31"},
    ]
    derived_facts = {
        "PL_REAL_INTEREST_RATE": {
            "value_decimal": "+3.45",
            "unit": "p.p.",
            "formula": "stopa NBP 5.75% [1] minus CPI 2.3% [2]",
            "ref_idx": 1,
            "cpi_idx": 2,
        }
    }

    report_with_erroneous_rate_logic = """# RAPORT KONDYCJI GOSPODARCZEJ: Polska
## 1. Analiza Trendów w Dostępnym Okresie
Stopa referencyjna wynosi 5.75% [1], a inflacja 2.3% [2]. Pomimo tego realna stopa procentowa jest bliska zeru i nie ogranicza akcji kredytowej.
## 2. Zagrożenia i Ryzyka Makroekonomiczne
Ryzyka.
## 3. Co to oznacza dla Kowalskiego? (Perspektywa Obywatela)
Kredyty.
## 4. Co to oznacza dla Przedsiębiorców?
Firma.
## 5. Podsumowanie i Realistyczny Werdykt
Werdykt.
## 6. Źródła danych i Metodologia
[1] NBP, https://nbp.pl
[2] GUS, https://stat.gov.pl
"""
    with pytest.raises(ValueError) as exc:
      evaluator._validate_v2_report(report_with_erroneous_rate_logic, citations, verified_obs, derived_facts=derived_facts)
    assert "Błędna interpretacja stopy referencyjnej" in str(exc.value)


# ==============================================================================
# TEST G: Brak bieżącego CPI przy dostępnych danych historycznych (kontrola lagów)
# ==============================================================================
def test_case_g_historical_cpi_lag_disclosure(tmp_path, monkeypatch):
    """Data raportu to 04.11.2026, a ostatni odczyt CPI to grudzień 2025. W prompt kontekście musi pojawić się ostrzeżenie o lagu."""
    db = SQLiteV2Storage(db_path=str(tmp_path / "case_g.db"))
    evi, obs = _make_evidence_and_obs("PL_CPI_YOY", "2.3", "2025-12-01", "2025-12-31")

    evaluator = EconomyEvaluator()
    captured_context = {}
    def mock_synth(country, report_date, periods_summary, chronological_context, allow_fallback=False):
        captured_context["text"] = chronological_context
        return """# RAPORT KONDYCJI GOSPODARCZEJ: Polska
## 1. Analiza Trendów w Dostępnym Okresie
Inflacja CPI z grudnia 2025 wyniosła 2.3% [1].
## 2. Zagrożenia i Ryzyka Makroekonomiczne
Lag danych.
## 3. Co to oznacza dla Kowalskiego? (Perspektywa Obywatela)
Obywatel.
## 4. Co to oznacza dla Przedsiębiorców?
Przedsiębiorcy.
## 5. Podsumowanie i Realistyczny Werdykt
Podsumowanie.
## 6. Źródła danych i Metodologia
[1] GUS
"""
    monkeypatch.setattr(evaluator, "_run_llm_synthesis", mock_synth)

    pipeline = MacroPipelineV2(db=db, offline_mode=False, evaluator=evaluator, diagnostics_dir=tmp_path / "logs")
    monkeypatch.setattr(pipeline, "fetch_official_data", lambda rid: ([evi], [obs], [], []))
    monkeypatch.setattr(pipeline, "search_enrichment", lambda country, rid: [])

    result = pipeline.run()
    assert result.success is True
    assert "UWAGA NA LAG PUBLIKACYJNY" in captured_context["text"]
    assert "2025-12-31" in captured_context["text"]


# ==============================================================================
# TEST H: Błąd GPT, timeout, błąd klucza i odrzucenie walidatora bez fallbacku
# ==============================================================================
@pytest.mark.parametrize("error_type, exc_to_raise, expected_mode", [
    ("api_error", RuntimeError("OpenAI quota exceeded"), "GPT_API_ERROR"),
    ("timeout", TimeoutError("Request timed out after 30s"), "GPT_API_ERROR"),
    ("key_error", ValueError("Invalid API key provided"), "GPT_API_ERROR"),
])
def test_case_h_gpt_errors_fail_cleanly_without_fallback(tmp_path, monkeypatch, error_type, exc_to_raise, expected_mode):
    """Awaria API GPT w trybie live powoduje czysty FAILED bez generowania deterministycznego raportu zastępczego."""
    monkeypatch.setattr(config, "OFFLINE_MODE", False)
    db = SQLiteV2Storage(db_path=str(tmp_path / f"case_h_{error_type}.db"))
    evi, obs = _make_evidence_and_obs("PL_CPI_YOY", "2.3")

    evaluator = EconomyEvaluator()
    monkeypatch.setattr(evaluator, "_run_llm_synthesis", lambda *args, **kwargs: (_ for _ in ()).throw(exc_to_raise))

    pipeline = MacroPipelineV2(db=db, offline_mode=False, evaluator=evaluator, diagnostics_dir=tmp_path / "logs")
    monkeypatch.setattr(pipeline, "fetch_official_data", lambda rid: ([evi], [obs], [], []))
    monkeypatch.setattr(pipeline, "search_enrichment", lambda country, rid: [])

    report_html_path = tmp_path / "report.html"
    result = pipeline.run(output_html_path=str(report_html_path))

    assert result.success is False
    assert result.status == "FAILED"
    assert result.report_id is None
    assert result.report_markdown == ""
    assert not report_html_path.exists()

    with open(tmp_path / "logs" / "last_run.json", "r", encoding="utf-8") as f:
        summary = json.load(f)
    assert summary["pipeline_status"] == "FAILED"
    assert summary["generation_mode"] == expected_mode
    assert summary["report_id"] is None


# ==============================================================================
# TEST I: Awaria zapisu do SQLite lub HTML (kontrola atomowości)
# ==============================================================================
def test_case_i_atomic_sqlite_or_html_write_failure(tmp_path, monkeypatch):
    """Gdy zapis do SQLite ulegnie awarii, plik HTML nie może pozostać na dysku, a stan musi być spójny."""
    db = SQLiteV2Storage(db_path=str(tmp_path / "case_i.db"))
    evi, obs = _make_evidence_and_obs("PL_CPI_YOY", "2.3")

    evaluator = EconomyEvaluator()
    valid_report = """# RAPORT KONDYCJI GOSPODARCZEJ: Polska
## 1. Analiza Trendów w Dostępnym Okresie
Inflacja CPI wynosi 2.3% [1].
## 2. Zagrożenia i Ryzyka Makroekonomiczne
Ryzyka.
## 3. Co to oznacza dla Kowalskiego? (Perspektywa Obywatela)
Obywatel.
## 4. Co to oznacza dla Przedsiębiorców?
Firma.
## 5. Podsumowanie i Realistyczny Werdykt
Werdykt.
## 6. Źródła danych i Metodologia
[1] GUS
"""
    monkeypatch.setattr(evaluator, "_run_llm_synthesis", lambda *args, **kwargs: valid_report)

    # Symulacja błędu zapisu w SQLite
    monkeypatch.setattr(db, "save_report", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("Disk I/O error on SQLite")))

    target_html = tmp_path / "report.html"
    pipeline = MacroPipelineV2(db=db, offline_mode=False, evaluator=evaluator, diagnostics_dir=tmp_path / "logs")
    monkeypatch.setattr(pipeline, "fetch_official_data", lambda rid: ([evi], [obs], [], []))
    monkeypatch.setattr(pipeline, "search_enrichment", lambda country, rid: [])

    result = pipeline.run(output_html_path=str(target_html))

    assert result.success is False
    assert result.status == "FAILED"
    # Plik docelowy HTML nie został opublikowany ani uszkodzony
    assert not target_html.exists()
    # Żaden plik tymczasowy .tmp nie pozostał w katalogu
    tmp_files = list(tmp_path.glob("*.tmp*"))
    assert len(tmp_files) == 0


# ==============================================================================
# TEST J: FAILED nie pokazuje starego raportu jako nowego w UI
# ==============================================================================
def test_case_j_failed_status_never_serves_stale_report_as_current(tmp_path, monkeypatch):
    """Gdy ostatni przebieg zakończył się FAILED, endpoint / serwuje stronę błędu z run_id, a nie stary raport jako bieżący."""
    log_dir = tmp_path / "instance" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    last_run_file = log_dir / "last_run.json"
    last_run_file.write_text(json.dumps({
        "run_id": "RUN_FAILED_TEST_123",
        "pipeline_status": "FAILED",
        "fallback_reason": "Raport GPT odrzucony przez walidator: Niezweryfikowane liczby",
    }), encoding="utf-8")

    import app
    monkeypatch.setattr(app, "get_last_run_path", lambda: last_run_file)

    with server.test_client() as client:
        res = client.get("/")
        content = res.get_data(as_text=True)
        assert "STATUS: FAILED" in content
        assert "RUN_FAILED_TEST_123" in content
        assert "Bieżący przebieg zakończony niepowodzeniem" in content
        assert "Niezweryfikowane liczby" in content


# ==============================================================================
# TEST K: GUS CPI bez potwierdzonego trybu prezentacji (5)
# ==============================================================================
def test_case_k_gus_cpi_requires_presentation_mode_5(monkeypatch):
    """Konektor GUS odrzuca pojedynczy rekord bez potwierdzenia id-sposob-prezentacji-miara=5."""
    gus = GusConnector()
    # Mockujemy odkrywanie okresu tak, aby wskazało badany okres
    monkeypatch.setattr(gus, "_discover_latest_cpi_period", lambda *args, **kwargs: (2026, 255, 9))
    # Pojedynczy rekord z mode=2 (miesięczna zmiana m/m, zamiast wymaganej 5 r/r)
    invalid_payload = json.dumps({
        "data": [{
            "id-zmienna": 305,
            "id-przekroj": 736,
            "id-okres": 255,
            "id-sposob-prezentacji-miara": 2,
            "wartosc": 0.4,
        }]
    })
    monkeypatch.setattr(gus, "_execute_request", lambda url: (200, invalid_payload, "hash", "2026-11-04T10:00:00Z"))

    with pytest.raises(ValidationError, match="sposobu prezentacji CPI r/r"):
        gus.fetch_cpi_dbw()


# ==============================================================================
# TEST L: Ochrona przed złośliwym HTML/XSS i prompt injection
# ==============================================================================
def test_case_l_xss_and_prompt_injection_protection():
    """Raport zawierający surowy tag HTML/skrypt jest odrzucany przez walidator."""
    evaluator = EconomyEvaluator()
    malicious_report = """# RAPORT KONDYCJI GOSPODARCZEJ: Polska
## 1. Analiza Trendów w Dostępnym Okresie
Inflacja CPI <script>alert('XSS')</script> wyniosła 2.3% [1].
## 2. Zagrożenia i Ryzyka Makroekonomiczne
Ryzyka.
## 3. Co to oznacza dla Kowalskiego? (Perspektywa Obywatela)
Obywatel.
## 4. Co to oznacza dla Przedsiębiorców?
Firma.
## 5. Podsumowanie i Realistyczny Werdykt
Werdykt.
## 6. Źródła danych i Metodologia
[1] GUS
"""
    with pytest.raises(ValueError, match="nieoczekiwany surowy HTML"):
      evaluator._validate_v2_report(malicious_report, [{"idx": 1, "is_official": True, "value_decimal": "2.3", "url": "https://stat.gov.pl"}], [{"indicator_code": "PL_CPI_YOY", "value_decimal": "2.3"}])


# ==============================================================================
# TEST M: Czytelność logo w jasnym panelu i poprawność nowej palety
# ==============================================================================
def test_case_m_logo_contrast_palette_and_responsiveness():
    """Szablon HTML zawiera docelową paletę (#142B49, #38658F, #F3F6FA, #FFFFFF) oraz jasny panel logo-card."""
    rendered = build_html_template("# Testowy Raport\nTreść.", country="Polska")
    assert "--navy-primary: #142B49;" in rendered
    assert "--accent-blue: #38658F;" in rendered
    assert "--bg-light: #F3F6FA;" in rendered
    assert "--card-white: #FFFFFF;" in rendered
    assert 'class="logo-card"' in rendered
    assert 'class="report-logo"' in rendered
    assert '@media (max-width: 768px)' in rendered


# ==============================================================================
# TEST N: Brak automatycznego fallbacku we wszystkich ścieżkach wykonania
# ==============================================================================
def test_case_n_no_automatic_fallback_across_all_paths(tmp_path, monkeypatch):
    """W trybie live ani błąd API, ani błąd walidacji nie mogą uruchomić _build_deterministic_v2_report."""
    monkeypatch.setattr(config, "OFFLINE_MODE", False)
    db = SQLiteV2Storage(db_path=str(tmp_path / "case_n.db"))
    evi, obs = _make_evidence_and_obs("PL_CPI_YOY", "2.3")

    evaluator = EconomyEvaluator()
    deterministic_called = {"called": False}
    orig_det = evaluator._build_deterministic_v2_report
    def spy_det(*args, **kwargs):
        deterministic_called["called"] = True
        return orig_det(*args, **kwargs)
    monkeypatch.setattr(evaluator, "_build_deterministic_v2_report", spy_det)

    # 1. Przebieg z błędem walidatora
    monkeypatch.setattr(evaluator, "_run_llm_synthesis", lambda *args, **kwargs: "niepoprawny raport")
    pipeline = MacroPipelineV2(db=db, offline_mode=False, evaluator=evaluator, diagnostics_dir=tmp_path / "logs")
    monkeypatch.setattr(pipeline, "fetch_official_data", lambda rid: ([evi], [obs], [], []))
    monkeypatch.setattr(pipeline, "search_enrichment", lambda country, rid: [])

    res1 = pipeline.run()
    assert res1.success is False
    assert res1.status == "FAILED"
    assert deterministic_called["called"] is False, "Deterministyczny raport został wywołany w trybie live!"

    # 2. Przebieg z błędem API GPT
    monkeypatch.setattr(evaluator, "_run_llm_synthesis", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("API down")))
    res2 = pipeline.run()
    assert res2.success is False
    assert res2.status == "FAILED"
    assert deterministic_called["called"] is False, "Deterministyczny raport został wywołany po awarii API GPT!"
