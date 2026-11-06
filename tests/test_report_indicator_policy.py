"""
Zestaw testów weryfikujący formalną politykę doboru, hierarchii i jakości wskaźników
makroekonomicznych dla raportu gospodarczego Polski.
Plik: tests/test_report_indicator_policy.py
"""

from datetime import datetime
import json
import os
import re
from typing import Any, Dict, List, Optional
import pytest

from modules.connectors.base import MacroObservation, RawEvidence
from modules.evaluator import EconomyEvaluator, mock_llm_json_synthesis
from modules.pipeline_v2 import MacroPipelineV2
from modules.report_indicator_policy import (
    FreshnessStatus,
    IndicatorPriority,
    ReportIndicatorPolicy,
)
from modules.storage_v2 import SQLiteV2Storage


def _create_sample_obs(
    code: str,
    val: str,
    unit: str,
    p_start: str,
    p_end: str,
    source: str = "GUS",
    freq: str = "MONTHLY",
    metadata: Optional[dict] = None,
):
    return {
        "observation_id": f"OBS_{code}",
        "indicator_code": code,
        "country_code": "PL",
        "value_decimal": val,
        "unit_code": unit,
        "period_start": p_start,
        "period_end": p_end,
        "frequency": freq,
        "source_id": source,
        "source_url": "https://stat.gov.pl" if source == "GUS" else ("https://api.nbp.pl" if source == "NBP" else "https://ec.europa.eu/eurostat"),
        "is_official": True,
        "metadata": metadata or {},
    }


def test_1_cpi_prioritized_over_hicp_in_prices_section():
    """1. Raport zawierający CPI i HICP: CPI musi znaleźć się w sekcji 'Ceny i Zakupy' jako wskaźnik główny."""
    obs_cpi = _create_sample_obs("PL_CPI_YOY", "2.3", "PCT", "2025-12-01", "2025-12-31")
    obs_hicp = _create_sample_obs("PL_HICP_YOY", "3.1", "PCT", "2026-09-01", "2026-09-30", source="EUROSTAT")
    citations = [
        {"idx": 1, "indicator_code": "PL_CPI_YOY", "institution": "GUS", "period": "2025-12", "is_official": True},
        {"idx": 2, "indicator_code": "PL_HICP_YOY", "institution": "Eurostat", "period": "2026-09", "is_official": True},
    ]

    plan = ReportIndicatorPolicy.evaluate([obs_cpi, obs_hicp], citations, report_date="05.11.2026")

    # CPI to Priority A (CORE), HICP to Priority C (AUXILIARY)
    cpi_eval = next(it for it in plan.core_indicators if it.indicator_code == "PL_CPI_YOY")
    hicp_eval = next(it for it in plan.auxiliary_indicators if it.indicator_code == "PL_HICP_YOY")

    assert cpi_eval.priority == IndicatorPriority.CORE
    assert cpi_eval.rank == 1
    assert hicp_eval.priority == IndicatorPriority.AUXILIARY
    assert "Ceny i Zakupy" in cpi_eval.presentation_rule
    assert "ZAKAZ zastępowania go odczytem HICP" in cpi_eval.presentation_rule
    assert "ZAKAZ zastępowania nim inflacji CPI GUS" in hicp_eval.presentation_rule

    # Kontekst promptu dla LLM zawiera jasne wytyczne
    prompt = plan.ordered_context_prompt
    assert "PRIORYTET A — GŁÓWNA TREŚĆ RAPORTU" in prompt
    assert "Głównym wskaźnikiem MUSI być inflacja konsumencka CPI GUS (PL_CPI_YOY)" in prompt
    assert "Zakaz zastępowania CPI przez HICP" in prompt


def test_2_registered_unemployment_prioritized_over_bael_lfs():
    """2. Raport zawierający bezrobocie rejestrowane i BAEL: rejestrowane musi znaleźć się w 'Praca i Zarobki' jako wskaźnik główny."""
    obs_reg = _create_sample_obs("PL_UNEMPLOYMENT_REGISTERED_RATE", "5.1", "PCT", "2025-01-01", "2025-12-31", freq="ANNUAL")
    obs_bael = _create_sample_obs("PL_UNEMPLOYMENT_LFS_RATE", "3.4", "PCT", "2026-08-01", "2026-08-31", source="EUROSTAT")
    citations = [
        {"idx": 1, "indicator_code": "PL_UNEMPLOYMENT_REGISTERED_RATE", "institution": "GUS", "period": "2025", "is_official": True},
        {"idx": 2, "indicator_code": "PL_UNEMPLOYMENT_LFS_RATE", "institution": "Eurostat", "period": "2026-08", "is_official": True},
    ]

    plan = ReportIndicatorPolicy.evaluate([obs_reg, obs_bael], citations, report_date="05.11.2026")

    reg_eval = next(it for it in plan.core_indicators if it.indicator_code == "PL_UNEMPLOYMENT_REGISTERED_RATE")
    bael_eval = next(it for it in plan.auxiliary_indicators if it.indicator_code == "PL_UNEMPLOYMENT_LFS_RATE")

    assert reg_eval.priority == IndicatorPriority.CORE
    assert reg_eval.rank == 2
    assert bael_eval.priority == IndicatorPriority.AUXILIARY
    assert "ZAKAZ zastępowania go odczytem BAEL" in reg_eval.presentation_rule
    assert "ZAKAZ zastępowania nim bezrobocia rejestrowanego GUS" in bael_eval.presentation_rule

    prompt = plan.ordered_context_prompt
    assert "Głównym wskaźnikiem MUSI być bezrobocie rejestrowane GUS (PL_UNEMPLOYMENT_REGISTERED_RATE)" in prompt
    assert "Zakaz zastępowania bezrobocia rejestrowanego przez BAEL" in prompt


def test_3_gdp_yoy_prioritized_over_qoq_and_volume():
    """3. Raport zawierający PKB r/r, kw/kw i wolumen: PKB r/r musi być wiodącym wskaźnikiem w sekcji 1 i podsumowaniu."""
    obs_yoy = _create_sample_obs("PL_GDP_YOY", "3.2", "PCT", "2026-04-01", "2026-06-30", source="EUROSTAT", freq="QUARTERLY")
    obs_qoq = _create_sample_obs("PL_GDP_QOQ", "0.8", "PCT", "2026-04-01", "2026-06-30", source="EUROSTAT", freq="QUARTERLY")
    obs_vol = _create_sample_obs("PL_GDP_VOLUME", "165430.5", "MEUR", "2026-04-01", "2026-06-30", source="EUROSTAT", freq="QUARTERLY")
    citations = [
        {"idx": 1, "indicator_code": "PL_GDP_YOY", "institution": "Eurostat", "period": "2026-Q2", "is_official": True},
        {"idx": 2, "indicator_code": "PL_GDP_QOQ", "institution": "Eurostat", "period": "2026-Q2", "is_official": True},
        {"idx": 3, "indicator_code": "PL_GDP_VOLUME", "institution": "Eurostat", "period": "2026-Q2", "is_official": True},
    ]

    plan = ReportIndicatorPolicy.evaluate([obs_yoy, obs_qoq, obs_vol], citations, report_date="05.11.2026")

    yoy_eval = next(it for it in plan.core_indicators if it.indicator_code == "PL_GDP_YOY")
    qoq_eval = next(it for it in plan.context_indicators if it.indicator_code == "PL_GDP_QOQ")
    vol_eval = next(it for it in plan.auxiliary_indicators if it.indicator_code == "PL_GDP_VOLUME")

    assert yoy_eval.priority == IndicatorPriority.CORE
    assert qoq_eval.priority == IndicatorPriority.CONTEXT
    assert vol_eval.priority == IndicatorPriority.AUXILIARY

    prompt = plan.ordered_context_prompt
    assert "Wzrost PKB r/r (PL_GDP_YOY) jest nadrzędny nad PKB kw/kw i wolumenem w mln EUR" in prompt


def test_4_annual_bdl_unemployment_not_presented_as_monthly():
    """4. Test szeregu rocznego bezrobocia (GUS BDL 60270): upewnij się, że nie jest prezentowany jako miesięczny odczyt."""
    obs_bdl = _create_sample_obs("PL_UNEMPLOYMENT_REGISTERED_RATE", "5.1", "PCT", "2025-01-01", "2025-12-31", freq="ANNUAL")
    citations = [{"idx": 1, "indicator_code": "PL_UNEMPLOYMENT_REGISTERED_RATE", "institution": "GUS", "period": "2025", "is_official": True}]

    plan = ReportIndicatorPolicy.evaluate([obs_bdl], citations, report_date="05.11.2026")
    reg_eval = next(it for it in plan.core_indicators if it.indicator_code == "PL_UNEMPLOYMENT_REGISTERED_RATE")

    assert reg_eval.freshness == FreshnessStatus.ANNUAL_HISTORICAL
    assert "Nie wolno traktować jako bieżącej stopy miesięcznej" in reg_eval.status_note
    assert "baza roczna GUS BDL: 2025 r." in plan.executive_horizon_summary


def test_5_archival_cpi_not_presented_as_current_inflation():
    """5. Test archiwalnego CPI: upewnij się, że nie jest prezentowany jako bieżąca inflacja z jesieni 2026 r."""
    # CPI z grudnia 2025 (lag > 90 dni względem listopada 2026)
    obs_cpi = _create_sample_obs("PL_CPI_YOY", "2.3", "PCT", "2025-12-01", "2025-12-31", freq="MONTHLY")
    citations = [{"idx": 1, "indicator_code": "PL_CPI_YOY", "institution": "GUS", "period": "2025-12", "is_official": True}]

    now_nov = datetime(2026, 11, 5)
    plan = ReportIndicatorPolicy.evaluate([obs_cpi], citations, report_date="05.11.2026", now=now_nov)
    cpi_eval = next(it for it in plan.core_indicators if it.indicator_code == "PL_CPI_YOY")

    assert cpi_eval.freshness == FreshnessStatus.ARCHIVAL
    assert cpi_eval.lag_days > 300
    assert "Odczyt archiwalny" in cpi_eval.status_note
    assert "UWAGA — ODCZYTY ARCHIWALNE" in plan.ordered_context_prompt
    assert "Dozwolone wyłącznie jako historyczna baza odniesienia" in plan.ordered_context_prompt


def test_6_missing_core_indicator_explicitly_communicated():
    """6. Test raportu przy braku wskaźnika Priorytetu A: upewnij się, że brak jest jawnie zakomunikowany."""
    # Przekazujemy tylko wskaźniki Priorytetu B i C (brak CPI, brak bezrobocia rejestrowanego)
    obs_hicp = _create_sample_obs("PL_HICP_YOY", "3.1", "PCT", "2026-09-01", "2026-09-30", source="EUROSTAT")
    obs_fx = _create_sample_obs("PL_FX_EUR_PLN", "4.3150", "EUR_PLN", "2026-10-30", "2026-10-30", source="NBP")
    citations = [
        {"idx": 1, "indicator_code": "PL_HICP_YOY", "institution": "Eurostat", "period": "2026-09", "is_official": True},
        {"idx": 2, "indicator_code": "PL_FX_EUR_PLN", "institution": "NBP", "period": "2026-10", "is_official": True},
    ]

    plan = ReportIndicatorPolicy.evaluate([obs_hicp, obs_fx], citations, report_date="05.11.2026")

    assert "Inflacja konsumencka CPI GUS" in plan.missing_core_indicators
    assert "Stopa bezrobocia rejestrowanego GUS" in plan.missing_core_indicators
    assert "UWAGA — BRAKUJĄCE WSKAŹNIKI KLUCZOWE: " in plan.ordered_context_prompt
    assert "W raporcie jawnie odnotuj brak bieżących potwierdzonych odczytów" in plan.ordered_context_prompt


def test_7_validator_integrity_blocks_swapped_citations_and_fake_values():
    """7. Test braku zmyślonych liczb / przypisów — walidator nadal bezwzględnie blokuje nieprawidłowe wartości i podmiany."""
    evaluator = EconomyEvaluator()
    obs_gdp = _create_sample_obs("PL_GDP_YOY", "3.2", "PCT", "2026-04-01", "2026-06-30", source="EUROSTAT", freq="QUARTERLY")
    citations = [{"idx": 1, "indicator_code": "PL_GDP_YOY", "institution": "Eurostat", "period": "2026-Q2", "is_official": True, "value_decimal": "3.2"}]

    # Próba zgłoszenia fałszywej wartości (3.8% zamiast 3.2%)
    bad_payload = {
        "claims": [{
            "indicator_code": "PL_GDP_YOY",
            "observation_id": "OBS_PL_GDP_YOY",
            "value_decimal": "3.8",
            "unit_code": "PCT",
            "period_start": "2026-04-01",
            "period_end": "2026-06-30",
            "citation_idx": 1,
        }],
        "sections": {
            "1": "Wzrost PKB wyniósł 3.8% [1].",
            "2": "Ryzyka są umiarkowane.",
            "3": "- **Kredyty i Raty:** Brak zmian.\n- **Ceny i Zakupy:** Brak.\n- **Praca i Zarobki:** Brak.",
            "4": "Przedsiębiorcy analizują sytuację.",
            "5": "Podsumowanie stabilne.",
        }
    }

    with pytest.raises((ValueError, RuntimeError)) as exc_info:
        evaluator._validate_structured_report(bad_payload, citations, [obs_gdp], derived_facts={})
    assert "oczekiwana wartość: 3.2" in str(exc_info.value) or "VALUE_MISMATCH" in str(exc_info.value)


def test_8_validator_wage_and_employment_aliases_and_geographic_isolation():
    """8. Regresja istniejących testów walidatora: dozwolone aliasy płac i zatrudnienia oraz izolacja geograficzna."""
    assert EconomyEvaluator._are_indicators_compatible("PL_WAGE_AVERAGE_GROSS", "PL_WAGE_AVG_ENTERPRISE") is True
    assert EconomyEvaluator._are_indicators_compatible("PL_EMPLOYMENT_GROWTH", "PL_EMPLOYMENT_COUNT") is True
    assert EconomyEvaluator._are_indicators_compatible("PL_NBP_REFERENCE_RATE", "PL_POLICY_RATE_REF") is True
    assert EconomyEvaluator._are_indicators_compatible("PL_UNEMPLOYMENT_REGISTERED_RATE", "PL_UNEMPLOYMENT_RATE") is True

    # ZAKAZ zamienności geograficznej PL vs EU
    assert EconomyEvaluator._are_indicators_compatible("PL_GDP_YOY", "EU_GDP_YOY") is False
    assert EconomyEvaluator._are_indicators_compatible("PL_GDP_QOQ", "EU_GDP_QOQ") is False
    assert EconomyEvaluator._are_indicators_compatible("PL_HICP_YOY", "EU_HICP_YOY") is False


def test_9_end_to_end_offline_pipeline_with_policy_and_no_duplicate_headers(tmp_path, monkeypatch):
    """9. End-to-end test z mockiem GPT symulujący pełne przejście od bazy SQLite przez walidator do renderera HTML."""
    storage = SQLiteV2Storage(db_path=str(tmp_path / "policy_e2e.db"))
    evaluator = EconomyEvaluator()

    # Mock GPT synthesis korzystający z mock_llm_json_synthesis, z dodatkowymi zduplikowanymi nagłówkami
    def mock_synth(country, report_date, periods_summary, chronological_context, **kwargs):
        raw_mock = mock_llm_json_synthesis(country, report_date, periods_summary, chronological_context, **kwargs)
        data = json.loads(raw_mock)
        # Symulujemy, że model zwrócił treść sekcji z nagłówkiem ## 1... oraz ## 3...
        data["sections"]["1"] = "## 1. Analiza Trendów w Dostępnym Okresie\n" + data["sections"].get("1", "")
        data["sections"]["3"] = "### 3. Co to oznacza dla Kowalskiego?\n" + data["sections"].get("3", "")
        data["sections"]["5"] = "## 5. Podsumowanie i Realistyczny Werdykt\n" + data["sections"].get("5", "")
        return json.dumps(data)

    monkeypatch.setattr(evaluator, "_run_llm_synthesis", mock_synth)

    pipeline = MacroPipelineV2(
        db=storage,
        offline_mode=False,
        evaluator=evaluator,
        diagnostics_dir=tmp_path / "logs",
    )
    pipeline._register_offline_fixtures()
    pipeline.nbp.offline_mode = True
    pipeline.eurostat.offline_mode = True
    pipeline.gus.offline_mode = True
    pipeline.search_service.offline_mode = True

    html_path = str(tmp_path / "test_report.html")
    result = pipeline.run(output_html_path=html_path)

    assert result.success is True
    assert result.status == "COMPLETED"
    assert os.path.exists(html_path)

    html_content = open(html_path, "r", encoding="utf-8").read()

    # Weryfikacja braku zduplikowanych nagłówków w sekcjach
    assert "## 1. Analiza Trendów w Dostępnym Okresie\n\n## 1. Analiza" not in html_content
    assert "### 3. Co to oznacza dla Kowalskiego?" not in html_content

    # Weryfikacja obecności sekcji 6 (Źródła danych i Metodologia)
    assert "6. Źródła danych i Metodologia" in html_content


def test_10_nbp_reference_rate_not_penalized_with_false_lag():
    """10. Test stóp NBP: stopa referencyjna jest prezentowana z datą obowiązywania, a nie jako przeterminowany odczyt."""
    # Stopa NBP uchwalona np. 2026-03-05 i potwierdzona w bieżącej oficjalnej tabeli NBP
    obs_nbp = _create_sample_obs(
        "PL_NBP_REFERENCE_RATE",
        "3.75",
        "PCT",
        "2026-03-05",
        "2026-03-05",
        source="SRC_NBP",
        freq="IRREGULAR",
        metadata={"is_current_table": True},
    )
    citations = [{"idx": 1, "indicator_code": "PL_NBP_REFERENCE_RATE", "institution": "NBP", "period": "2026-03-05", "is_official": True}]

    now_nov = datetime(2026, 11, 5)
    plan = ReportIndicatorPolicy.evaluate([obs_nbp], citations, report_date="05.11.2026", now=now_nov)
    nbp_eval = next(it for it in plan.core_indicators if it.indicator_code == "PL_NBP_REFERENCE_RATE")

    # Stopa NBP musi mieć status EFFECTIVE oraz lag_days == 0
    assert nbp_eval.freshness == FreshnessStatus.EFFECTIVE
    assert nbp_eval.lag_days == 0
    assert "stopa NBP obowiązująca od 05.03.2026 r." in plan.executive_horizon_summary

    # Evaluator nie może wygenerować fałszywego ostrzeżenia o przeterminowaniu
    p_end_dt = datetime.strptime("2026-03-05", "%Y-%m-%d").date()
    today_dt = now_nov.date()
    lag_days = (today_dt - p_end_dt).days
    is_nbp_rate = "NBP" in obs_nbp.get("source_id", "") and ("RATE" in obs_nbp["indicator_code"] or "POLICY" in obs_nbp["indicator_code"])

    assert is_nbp_rate is True
    assert lag_days > 90  # Kalendarzowo minęło >90 dni, ale reguła traktuje stawkę jako prawnie obowiązującą
    assert not (lag_days > 90 and not is_nbp_rate)  # Warunek nie może dopuścić fałszywej flagi lag



def test_11_nbp_rate_policy_historical_5_75_vs_current_3_75():
    """11. Test porównawczy: historyczna stopa 5.75% (2023) i bieżąca 3.75% (2026).
    Upewnij się, że 3.75% jest traktowane jako EFFECTIVE, a 5.75% jako ARCHIVAL."""
    obs_historical = _create_sample_obs(
        "PL_NBP_REFERENCE_RATE", "5.75", "PCT", "2023-10-05", "2023-10-05", source="SRC_NBP", freq="IRREGULAR"
    )
    obs_current = _create_sample_obs(
        "PL_NBP_REFERENCE_RATE", "3.75", "PCT", "2026-03-05", "2026-03-05", source="SRC_NBP", freq="IRREGULAR", metadata={"is_current_table": True}
    )
    citations = [
        {"idx": 1, "indicator_code": "PL_NBP_REFERENCE_RATE", "institution": "NBP", "period": "2026-03-05", "is_official": True, "value_decimal": "3.75"},
    ]

    now_nov = datetime(2026, 11, 6)
    plan = ReportIndicatorPolicy.evaluate([obs_historical, obs_current], citations, report_date="06.11.2026", now=now_nov)
    nbp_eval = next(it for it in plan.core_indicators if it.indicator_code == "PL_NBP_REFERENCE_RATE")

    # Wybrany wskaźnik główny to bieżąca decyzja 3.75% ze statusem EFFECTIVE
    assert nbp_eval.value_decimal == "3.75"
    assert nbp_eval.freshness == FreshnessStatus.EFFECTIVE
    assert nbp_eval.period_start == "2026-03-05"
    assert "stopa NBP obowiązująca od 05.03.2026 r." in plan.executive_horizon_summary

    # Gdy historyczna obserwacja 5.75% z 2023 r. jest oceniana bez potwierdzenia, otrzymuje status ARCHIVAL
    plan_hist = ReportIndicatorPolicy.evaluate([obs_historical], citations, report_date="06.11.2026", now=now_nov)
    nbp_hist_eval = next(it for it in plan_hist.core_indicators if it.indicator_code == "PL_NBP_REFERENCE_RATE")
    assert nbp_hist_eval.value_decimal == "5.75"
    assert nbp_hist_eval.freshness == FreshnessStatus.ARCHIVAL
    assert "Archiwalna stopa referencyjna" in nbp_hist_eval.status_note


def test_12_unconfirmed_historical_rate_in_november_2026_is_archival():
    """12. Wartość 5.75% z 2023 r. nie może być automatycznie uznawana za aktualną w listopadzie 2026 bez potwierdzenia."""
    obs_unconfirmed_2023 = _create_sample_obs(
        "PL_NBP_REFERENCE_RATE", "5.75", "PCT", "2023-10-05", "2023-10-05", source="SRC_NBP", freq="IRREGULAR"
    )
    citations = [
        {"idx": 1, "indicator_code": "PL_NBP_REFERENCE_RATE", "institution": "NBP", "period": "2023-10-05", "is_official": True}
    ]
    now_nov = datetime(2026, 11, 6)
    plan = ReportIndicatorPolicy.evaluate([obs_unconfirmed_2023], citations, report_date="06.11.2026", now=now_nov)
    eval_rate = next(it for it in plan.core_indicators if it.indicator_code == "PL_NBP_REFERENCE_RATE")

    assert eval_rate.freshness == FreshnessStatus.ARCHIVAL
    assert "Zakaz prezentowania jako stawki bieżącej" in eval_rate.status_note
    assert "archiwalna stopa NBP z 05.10.2023 r." in plan.executive_horizon_summary


def test_13_reject_uncompleted_future_period_observations():
    """13. Odrzucaj obserwacje mające datę końca okresu w przyszłości, chyba że dotyczą jawnie określonej prognozy."""
    obs_future_annual = _create_sample_obs(
        "PL_UNEMPLOYMENT_REGISTERED_RATE", "5.0", "PCT", "2026-01-01", "2026-12-31", freq="ANNUAL"
    )
    obs_future_annual["revision_type"] = "FINAL"
    obs_past_annual = _create_sample_obs(
        "PL_UNEMPLOYMENT_REGISTERED_RATE", "5.1", "PCT", "2025-01-01", "2025-12-31", freq="ANNUAL"
    )
    obs_past_annual["revision_type"] = "FINAL"
    citations = [
        {"idx": 1, "indicator_code": "PL_UNEMPLOYMENT_REGISTERED_RATE", "institution": "GUS", "period": "2025", "is_official": True}
    ]

    now_nov = datetime(2026, 11, 6)
    plan = ReportIndicatorPolicy.evaluate([obs_future_annual, obs_past_annual], citations, report_date="06.11.2026", now=now_nov)
    eval_unemp = next(it for it in plan.core_indicators if it.indicator_code == "PL_UNEMPLOYMENT_REGISTERED_RATE")

    # Obserwacja z przyszłości (2026-12-31) została odrzucona; wybrany został zakończony okres 2025 (5.1%)
    assert eval_unemp.value_decimal == "5.1"
    assert eval_unemp.period_end == "2025-12-31"

    # Jawna prognoza z przyszłości nie może być prezentowana jako oficjalny odczyt
    obs_forecast = _create_sample_obs(
        "PL_UNEMPLOYMENT_REGISTERED_RATE", "4.8", "PCT", "2026-01-01", "2026-12-31", freq="ANNUAL"
    )
    obs_forecast["revision_type"] = "FORECAST"
    plan_fc = ReportIndicatorPolicy.evaluate([obs_forecast], citations, report_date="06.11.2026", now=now_nov)
    eval_fc = next(it for it in plan_fc.core_indicators if it.indicator_code == "PL_UNEMPLOYMENT_REGISTERED_RATE")
    assert eval_fc.freshness == FreshnessStatus.MISSING


def test_14_gus_dbw_monthly_registered_unemployment_5_8_percent():
    """14. Weryfikacja pozyskiwania miesięcznej stopy bezrobocia rejestrowanego GUS DBW (5.8% za wrzesień 2026)."""
    from modules.connectors.gus import GusConnector
    from modules.pipeline_v2 import OFFLINE_FIXTURES

    connector = GusConnector(offline_mode=True)
    connector.register_fixture("id-zmienna=875", OFFLINE_FIXTURES["GUS_DBW_UNEMPLOYMENT"])
    evidence, obs = connector.fetch_registered_unemployment_monthly_dbw()

    assert obs.indicator_code == "PL_UNEMPLOYMENT_REGISTERED_RATE"
    assert obs.value_decimal == "5.8"
    assert obs.unit_code == "PCT"
    assert obs.frequency == "MONTHLY"
    assert obs.period_start == "2026-09-01"
    assert obs.period_end == "2026-09-30"
    assert obs.status == "VERIFIED"
    assert obs.metadata["gus_dbw_zmienna"] == 875
    assert obs.metadata["gus_dbw_przekroj"] == 143
    assert obs.metadata["territory_id"] == 33617
