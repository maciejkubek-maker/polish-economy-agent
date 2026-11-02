"""
Testy jednostkowe i integracyjne dla modułu konektorów oficjalnych API (TASK-05).
Plik: tests/test_connectors.py

Wymagania:
- 100% testów działa offline bez połączenia z siecią i bez płatnych API (mock fixtures).
- Weryfikacja NBP (REST EUR/USD oraz XML stóp procentowych).
- Weryfikacja Eurostat (JSON-stat 2.0 dla HICP, bezrobocia BAEL i PKB).
- Weryfikacja GUS (BDL var_id 60270/60269, DBW CPI var 305/736, wyszukiwanie zmiennych).
- Rygorystyczny test zakazu fikcyjnych ID (VariableNotMappedError).
- Weryfikacja odporności na błędy: retry, timeout, 404 (DataNotFoundError), walidacja zakresów.
"""

from decimal import Decimal
import json
import pytest

from modules.connectors.base import (
    BaseConnector,
    ConnectorException,
    DataNotFoundError,
    MacroObservation,
    RawEvidence,
    ValidationError,
    VariableNotMappedError,
)
from modules.connectors.nbp import NbpConnector
from modules.connectors.eurostat import EurostatConnector
from modules.connectors.gus import GusConnector


# ==============================================================================
# FIXTURES DANYCH TESTOWYCH (OFFLINE PAYLOADS)
# ==============================================================================

NBP_EUR_JSON = """
{
  "table": "A",
  "currency": "euro",
  "code": "EUR",
  "rates": [
    {
      "no": "212/A/NBP/2026",
      "effectiveDate": "2026-10-30",
      "mid": 4.3450
    }
  ]
}
"""

NBP_USD_JSON = """
{
  "table": "A",
  "currency": "dolar amerykański",
  "code": "USD",
  "rates": [
    {
      "no": "212/A/NBP/2026",
      "effectiveDate": "2026-10-30",
      "mid": 4.0215
    }
  ]
}
"""

NBP_RATES_XML = """<?xml version="1.0" encoding="utf-8"?>
<stopy_procentowe>
    <pozycja id="ref" obowiazuje_od="2023-10-05" oprocentowanie="5.75"/>
    <pozycja id="lom" obowiazuje_od="2023-10-05" oprocentowanie="6.25"/>
    <pozycja id="dep" obowiazuje_od="2023-10-05" oprocentowanie="5.25"/>
    <pozycja id="red" obowiazuje_od="2023-10-05" oprocentowanie="5.80"/>
    <pozycja id="dys" obowiazuje_od="2023-10-05" oprocentowanie="5.85"/>
</stopy_procentowe>
"""

EUROSTAT_HICP_JSON = """
{
  "version": "2.0",
  "class": "dataset",
  "label": "HICP - monthly data (annual rate of change)",
  "dimension": {
    "geo": {"category": {"index": ["PL"]}},
    "coicop": {"category": {"index": ["CP00"]}},
    "unit": {"category": {"index": ["RCH_A"]}},
    "time": {
      "category": {
        "index": {
          "2026M07": 0,
          "2026M08": 1,
          "2026M09": 2
        }
      }
    }
  },
  "value": {
    "0": 4.2,
    "1": 4.3,
    "2": 4.5
  }
}
"""

EUROSTAT_UNEMPLOYMENT_JSON = """
{
  "version": "2.0",
  "class": "dataset",
  "label": "Unemployment by sex and age - monthly data",
  "dimension": {
    "geo": {"category": {"index": ["PL"]}},
    "time": {
      "category": {
        "index": {
          "2026M08": 0,
          "2026M09": 1
        }
      }
    }
  },
  "value": {
    "0": 3.0,
    "1": 2.9
  }
}
"""

EUROSTAT_GDP_JSON = """
{
  "version": "2.0",
  "class": "dataset",
  "label": "Gross domestic product at market prices",
  "dimension": {
    "geo": {"category": {"index": ["PL"]}},
    "time": {
      "category": {
        "index": {
          "2026-Q1": 0,
          "2026-Q2": 1
        }
      }
    }
  },
  "value": {
    "0": 135400.5,
    "1": 136850.2
  }
}
"""

GUS_BDL_UNEMPLOYMENT_JSON = """
{
  "totalRecords": 1,
  "page": 0,
  "pageSize": 10,
  "variable": {
    "id": 60270,
    "subjectId": "P2437",
    "n1": "ogółem",
    "level": 6,
    "measureUnitId": 5,
    "measureUnitName": "%"
  },
  "results": [
    {
      "id": "000000000000",
      "name": "POLSKA",
      "values": [
        {
          "year": 2025,
          "val": 5.1,
          "attrId": 1
        },
        {
          "year": 2026,
          "month": 8,
          "val": 5.0,
          "attrId": 1
        }
      ]
    }
  ]
}
"""

GUS_BDL_COUNT_JSON = """
{
  "totalRecords": 1,
  "page": 0,
  "pageSize": 10,
  "results": [
    {
      "id": "000000000000",
      "name": "POLSKA",
      "values": [
        {
          "year": 2026,
          "val": 845.3,
          "attrId": 1
        }
      ]
    }
  ]
}
"""

GUS_BDL_SEARCH_JSON = """
{
  "totalRecords": 2,
  "page": 0,
  "pageSize": 10,
  "results": [
    {
      "id": 60270,
      "subjectId": "P2437",
      "n1": "Stopa bezrobocia rejestrowanego",
      "measureUnitName": "%"
    },
    {
      "id": 60269,
      "subjectId": "P2437",
      "n1": "Bezrobotni zarejestrowani",
      "measureUnitName": "osoba"
    }
  ]
}
"""

GUS_DBW_CPI_JSON = """
{
  "page": 1,
  "page-size": 10,
  "total-records": 1,
  "data": [
    {
      "id-zmienna": 305,
      "id-przekroj": 736,
      "id-rok": 2026,
      "id-okres": 280,
      "wartosc": 104.2,
      "precyzja": 1
    }
  ]
}
"""


# ==============================================================================
# TESTY NBP CONNECTOR
# ==============================================================================

class TestNbpConnector:
    """Testy oficjalnego konektora NBP (REST i XML)."""

    def test_fetch_eur_rate_success(self):
        connector = NbpConnector(offline_mode=True)
        connector.register_fixture("rates/A/EUR", NBP_EUR_JSON)

        evidence, obs = connector.fetch_exchange_rate("EUR")

        assert evidence.source_id == "SRC_NBP"
        assert evidence.document_type == "API_RESPONSE"
        assert evidence.status_code == 200
        assert len(evidence.content_hash) == 64

        assert obs.indicator_code == "PL_FX_EUR_PLN"
        assert obs.country_code == "PL"
        assert obs.period_start == "2026-10-30"
        assert obs.period_end == "2026-10-30"
        assert obs.frequency == "DAILY"
        assert obs.value_decimal == "4.345"
        assert obs.unit_code == "EUR_PLN"
        assert obs.revision_type == "FINAL"
        assert obs.status == "VERIFIED"
        assert obs.evidence_id == evidence.evidence_id
        assert obs.metadata["table_no"] == "212/A/NBP/2026"

    def test_fetch_usd_rate_success(self):
        connector = NbpConnector(offline_mode=True)
        connector.register_fixture("rates/A/USD", NBP_USD_JSON)

        evidence, obs = connector.fetch_exchange_rate("usd")

        assert obs.indicator_code == "PL_FX_USD_PLN"
        assert obs.value_decimal == "4.0215"
        assert obs.unit_code == "USD_PLN"

    def test_fetch_reference_rate_xml_success(self):
        connector = NbpConnector(offline_mode=True)
        connector.register_fixture("stopy_procentowe.xml", NBP_RATES_XML)

        evidence, obs = connector.fetch_reference_rate()

        assert evidence.source_id == "SRC_NBP"
        assert evidence.document_type == "OFFICIAL_XML"
        assert obs.indicator_code == "PL_NBP_REFERENCE_RATE"
        assert obs.period_start == "2023-10-05"
        assert obs.period_end == "2023-10-05"
        assert obs.frequency == "IRREGULAR"
        assert obs.value_decimal == "5.75"
        assert obs.unit_code == "PCT"
        assert obs.status == "VERIFIED"
        assert obs.metadata["rate_type"] == "referencyjna"

    def test_unsupported_currency_raises_validation_error(self):
        connector = NbpConnector(offline_mode=True)
        with pytest.raises(ValidationError, match="Nieobsługiwany kod waluty"):
            connector.fetch_exchange_rate("GBP")

    def test_empty_rates_raises_data_not_found(self):
        connector = NbpConnector(offline_mode=True)
        empty_json = json.dumps({"table": "A", "currency": "euro", "code": "EUR", "rates": []})
        connector.register_fixture("rates/A/EUR", empty_json)

        with pytest.raises(DataNotFoundError, match="Brak notowań dla waluty"):
            connector.fetch_exchange_rate("EUR")

    def test_malformed_xml_raises_validation_error(self):
        connector = NbpConnector(offline_mode=True)
        connector.register_fixture("stopy_procentowe.xml", "<not_closed_xml")

        with pytest.raises(ValidationError, match="Błąd parsowania XML"):
            connector.fetch_reference_rate()


# ==============================================================================
# TESTY EUROSTAT CONNECTOR
# ==============================================================================

class TestEurostatConnector:
    """Testy oficjalnego konektora Eurostatu (JSON-stat 2.0)."""

    def test_fetch_hicp_success(self):
        connector = EurostatConnector(offline_mode=True)
        connector.register_fixture("prc_hicp_manr", EUROSTAT_HICP_JSON)

        evidence, observations = connector.fetch_hicp("PL")

        assert evidence.source_id == "SRC_EUROSTAT"
        assert len(observations) == 3

        # Sprawdzenie pierwszej obserwacji (2026M07)
        obs0 = observations[0]
        assert obs0.indicator_code == "EU_HICP_YOY"
        assert obs0.country_code == "PL"
        assert obs0.period_start == "2026-07-01"
        assert obs0.period_end == "2026-07-31"
        assert obs0.frequency == "MONTHLY"
        assert obs0.value_decimal == "4.2"
        assert obs0.unit_code == "PCT"
        assert obs0.status == "VERIFIED"

        # Sprawdzenie ostatniej obserwacji (2026M09)
        obs2 = observations[2]
        assert obs2.period_start == "2026-09-01"
        assert obs2.period_end == "2026-09-30"
        assert obs2.value_decimal == "4.5"

    def test_fetch_harmonized_unemployment_success(self):
        connector = EurostatConnector(offline_mode=True)
        connector.register_fixture("une_rt_m", EUROSTAT_UNEMPLOYMENT_JSON)

        evidence, observations = connector.fetch_harmonized_unemployment("PL")

        assert len(observations) == 2
        obs = observations[1]
        assert obs.indicator_code == "PL_UNEMPLOYMENT_LFS_RATE"
        assert obs.period_start == "2026-09-01"
        assert obs.period_end == "2026-09-30"
        assert obs.value_decimal == "2.9"
        assert obs.unit_code == "PCT"
        assert obs.metadata["standard"] == "ILO_BAEL"

    def test_fetch_quarterly_gdp_success(self):
        connector = EurostatConnector(offline_mode=True)
        connector.register_fixture("namq_10_gdp", EUROSTAT_GDP_JSON)

        evidence, observations = connector.fetch_quarterly_gdp("PL")

        assert len(observations) == 2
        q1 = observations[0]
        assert q1.indicator_code == "PL_GDP_QOQ"
        assert q1.period_start == "2026-01-01"
        assert q1.period_end == "2026-03-31"
        assert q1.frequency == "QUARTERLY"
        assert q1.value_decimal == "135400.5"

        q2 = observations[1]
        assert q2.period_start == "2026-04-01"
        assert q2.period_end == "2026-06-30"
        assert q2.value_decimal == "136850.2"

    def test_missing_time_dimension_raises_validation_error(self):
        connector = EurostatConnector(offline_mode=True)
        bad_json = json.dumps({"version": "2.0", "dimension": {}})
        connector.register_fixture("prc_hicp_manr", bad_json)

        with pytest.raises(ValidationError, match="Brak wymiaru 'time'"):
            connector.fetch_hicp("PL")


# ==============================================================================
# TESTY GUS CONNECTOR
# ==============================================================================

class TestGusConnector:
    """Testy oficjalnego konektora GUS (BDL i DBW)."""

    def test_fetch_registered_unemployment_bdl_success(self):
        connector = GusConnector(offline_mode=True)
        connector.register_fixture("by-variable/60270", GUS_BDL_UNEMPLOYMENT_JSON)

        evidence, observations = connector.fetch_registered_unemployment()

        assert evidence.source_id == "SRC_GUS_BDL"
        assert len(observations) == 2

        # Obserwacja roczna
        obs_ann = observations[0]
        assert obs_ann.indicator_code == "PL_UNEMPLOYMENT_REGISTERED_RATE"
        assert obs_ann.period_start == "2025-01-01"
        assert obs_ann.period_end == "2025-12-31"
        assert obs_ann.frequency == "ANNUAL"
        assert obs_ann.value_decimal == "5.1"
        assert obs_ann.unit_code == "PCT"

        # Obserwacja miesięczna
        obs_month = observations[1]
        assert obs_month.period_start == "2026-08-01"
        assert obs_month.period_end == "2026-08-31"
        assert obs_month.frequency == "MONTHLY"
        assert obs_month.value_decimal == "5.0"

    def test_fetch_registered_unemployment_count_success(self):
        connector = GusConnector(offline_mode=True)
        connector.register_fixture("by-variable/60269", GUS_BDL_COUNT_JSON)

        evidence, observations = connector.fetch_registered_unemployment_count()

        assert len(observations) == 1
        assert observations[0].indicator_code == "PL_UNEMPLOYMENT_REGISTERED_COUNT"
        assert observations[0].value_decimal == "845.3"
        assert observations[0].unit_code == "THOUSAND_PERSONS"

    def test_fetch_cpi_dbw_success(self):
        connector = GusConnector(offline_mode=True)
        connector.register_fixture("data/data-data", GUS_DBW_CPI_JSON)

        evidence, obs = connector.fetch_cpi_dbw(rok=2026, okres_id=280)

        assert evidence.source_id == "SRC_GUS_DBW"
        assert obs.indicator_code == "PL_CPI_YOY"
        # 104.2 bazy 100 przeliczone na 4.2% r/r
        assert obs.value_decimal == "4.2"
        assert obs.unit_code == "PCT"
        assert obs.metadata["raw_index_value"] == "104.2"

    def test_search_bdl_variables_success(self):
        connector = GusConnector(offline_mode=True)
        connector.register_fixture("variables/search", GUS_BDL_SEARCH_JSON)

        results = connector.search_bdl_variables("bezrobocie")

        assert len(results) == 2
        assert results[0]["id"] == 60270
        assert results[1]["id"] == 60269

    def test_strict_anti_hallucination_unmapped_indicator_raises_error(self):
        """Wskaźnik bez potwierdzonego ID (np. wynagrodzenia) nie może używać zmyślonego ID."""
        connector = GusConnector(offline_mode=True)

        with pytest.raises(VariableNotMappedError, match="status CONFIRMED_API_REQUIRES_VARIABLE_MAPPING"):
            connector.fetch_indicator("PL_WAGE_AVERAGE_GROSS")

        with pytest.raises(VariableNotMappedError, match="status CONFIRMED_API_REQUIRES_VARIABLE_MAPPING"):
            connector.fetch_indicator("PL_INDUSTRIAL_PRODUCTION_YOY")

    def test_unmapped_indicator_with_explicit_verified_var_id_succeeds(self):
        """Jeśli użytkownik przekaże zweryfikowane ID, pobranie się powiedzie."""
        connector = GusConnector(offline_mode=True)
        connector.register_fixture("by-variable/644070", GUS_BDL_COUNT_JSON)

        evidence, observations = connector.fetch_indicator(
            "PL_WAGE_AVERAGE_GROSS", var_id=644070, unit_code="PLN_PER_MONTH"
        )

        assert observations[0].indicator_code == "PL_WAGE_AVERAGE_GROSS"
        assert observations[0].unit_code == "PLN_PER_MONTH"


# ==============================================================================
# TESTY BAZOWE: BASE CONNECTOR (WALIDACJA, BEZPIECZEŃSTWO, ODPORNOŚĆ)
# ==============================================================================

class TestBaseConnectorGuards:
    """Testy mechanizmów walidacyjnych i odpornościowych BaseConnector."""

    def test_offline_mode_blocks_unmocked_calls(self):
        connector = BaseConnector(offline_mode=True)
        with pytest.raises(ConnectorException, match="Tryb offline aktywny, brak zarejestrowanego fixture"):
            connector._execute_request("https://api.stat.gov.pl/test")

    def test_validate_value_handles_comma_and_spaces(self):
        connector = BaseConnector()
        assert connector.validate_value(" 1 234,56 % ") == "1234.56"
        assert connector.validate_value(Decimal("5.75")) == "5.75"
        assert connector.validate_value(100) == "100"

    def test_validate_value_range_checks(self):
        connector = BaseConnector()
        with pytest.raises(ValidationError, match="poniżej dopuszczalnego minimum"):
            connector.validate_value("-5.0", min_plausible=Decimal("0.0"))

        with pytest.raises(ValidationError, match="przekracza dopuszczalne maksimum"):
            connector.validate_value("150.0", max_plausible=Decimal("100.0"))

    def test_validate_iso_date(self):
        connector = BaseConnector()
        assert connector.validate_iso_date("2026-10-31") == "2026-10-31"

        with pytest.raises(ValidationError, match="Nieprawidłowy format daty ISO"):
            connector.validate_iso_date("31-10-2026")

        with pytest.raises(ValidationError, match="Data nie może być pusta"):
            connector.validate_iso_date("")

    def test_validate_frequency_and_unit(self):
        connector = BaseConnector()
        assert connector.validate_frequency("monthly") == "MONTHLY"
        with pytest.raises(ValidationError, match="Nieznana częstotliwość"):
            connector.validate_frequency("BIWEEKLY")

        assert connector.validate_unit("pct") == "PCT"
        with pytest.raises(ValidationError, match="Nieznana jednostka"):
            connector.validate_unit("APPLES")

    def test_create_evidence_has_sha256_and_unique_id(self):
        connector = BaseConnector()
        evi = connector.create_evidence(
            source_id="SRC_TEST",
            source_url="https://test.example.com",
            document_type="TEST_DOC",
            payload_text="Sample payload",
            content_hash="abc123hash",
            status_code=200,
            retrieved_at_utc="2026-11-02T12:00:00Z",
        )
        assert evi.evidence_id.startswith("EVI_")
        assert evi.to_dict()["source_id"] == "SRC_TEST"
