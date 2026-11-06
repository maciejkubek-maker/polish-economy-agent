"""
Moduł orkiestratora platformy danych makroekonomicznych SQLite v2 (TASK-06).
Plik: modules/pipeline_v2.py

Integruje cały proces w jeden działający, w pełni kontrolowany i audytowalny potok:
1. POBIERANIE (Connectors: NBP, Eurostat, GUS).
2. WALIDACJA (typy, jednostki, definicje, okresy, brak zgadywania).
3. ZAPIS (SQLite v2: ingestion_runs, source_evidence, observations - strictly append-only).
4. WYSZUKIWANIE (Tavily Search: komunikaty oficjalne vs komentarze medialne).
5. ANALIZA AI (EconomyEvaluator / OpenAI GPT z bezpiecznym trybem offline).
6. RAPORT (wielosekcyjny raport analityczny z aparatem źródłowym, zapis w tabeli reports oraz w HTML).
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import re
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import uuid

import config
from modules.connectors.base import (
    ConnectorException,
    DataNotFoundError,
    MacroObservation,
    RawEvidence,
    ValidationError,
    VariableNotMappedError,
)
from modules.connectors.eurostat import EurostatConnector
from modules.connectors.gus import GusConnector
from modules.connectors.nbp import NbpConnector
from modules.evaluator import EconomyEvaluator
from modules.diagnostics import (
    PipelineDiagnostics,
    base_run_summary,
    missing_report_indicators,
    safe_error_message,
)
from modules.search_service import WebSearchService
from modules.storage_v2 import SQLiteV2Storage


# ==============================================================================
# STANDARDOWE FIXTURE'Y DLA TRYBU OFFLINE
# ==============================================================================

OFFLINE_FIXTURES = {
    "NBP_EUR": """{
      "table": "A",
      "currency": "euro",
      "code": "EUR",
      "rates": [{"no": "212/A/NBP/2026", "effectiveDate": "2026-10-30", "mid": 4.3955}]
    }""",
    "NBP_USD": """{
      "table": "A",
      "currency": "dolar amerykański",
      "code": "USD",
      "rates": [{"no": "212/A/NBP/2026", "effectiveDate": "2026-10-30", "mid": 3.9251}]
    }""",
    "NBP_RATES": """<?xml version="1.0" encoding="utf-8"?>
    <stopy_procentowe data_publikacji="2026-03-05">
        <tabela id="stoproc" naglowek="Stopa procentowa:">
            <pozycja id="ref" obowiazuje_od="2026-03-05" oprocentowanie="3.75"/>
            <pozycja id="lom" obowiazuje_od="2026-03-05" oprocentowanie="4.25"/>
            <pozycja id="dep" obowiazuje_od="2026-03-05" oprocentowanie="3.25"/>
        </tabela>
    </stopy_procentowe>""",
    "EUROSTAT_TEICP000": """{
      "version": "2.0",
      "class": "dataset",
      "label": "HICP - monthly data",
      "id": ["freq", "coicop18", "unit", "geo", "time"],
      "size": [1, 1, 2, 1, 3],
      "dimension": {
        "freq": {"category": {"index": {"M": 0}}},
        "coicop18": {"category": {"index": {"TOTAL": 0}}},
        "unit": {"category": {"index": {"PCH_M1": 0, "PCH_M12": 1}}},
        "geo": {"category": {"index": {"PL": 0}}},
        "time": {"category": {"index": {"2026-07": 0, "2026-08": 1, "2026-09": 2}}}
      },
      "value": {"0": 0.2, "1": 0.1, "2": 0.3, "3": 3.1, "4": 3.5, "5": 4.0}
    }""",
    "EUROSTAT_UNEMPLOYMENT": """{
      "version": "2.0",
      "class": "dataset",
      "label": "Unemployment by sex and age - monthly data",
      "dimension": {
        "geo": {"category": {"index": ["PL"]}},
        "time": {"category": {"index": {"2026M08": 0, "2026M09": 1}}}
      },
      "value": {"0": 3.0, "1": 2.9}
    }""",
    "EUROSTAT_GDP_QOQ": """{
      "version": "2.0",
      "class": "dataset",
      "label": "Gross domestic product - percentage change on previous period",
      "dimension": {
        "geo": {"category": {"index": ["PL"]}},
        "unit": {"category": {"index": ["PCH_PRE"]}},
        "time": {
          "category": {
            "index": {
              "2026-Q1": 0,
              "2026-Q2": 1
            }
          }
        }
      },
      "value": {"0": 0.8, "1": 1.1}
    }""",
    "EUROSTAT_GDP_YOY": """{
      "version": "2.0",
      "class": "dataset",
      "label": "Gross domestic product - percentage change compared to same period in previous year",
      "dimension": {
        "geo": {"category": {"index": ["PL"]}},
        "unit": {"category": {"index": ["PCH_SM_PR_Y"]}},
        "time": {
          "category": {
            "index": {
              "2026-Q1": 0,
              "2026-Q2": 1
            }
          }
        }
      },
      "value": {"0": 3.4, "1": 3.9}
    }""",
    "EUROSTAT_GDP_VOLUME": """{
      "version": "2.0",
      "class": "dataset",
      "label": "Gross domestic product at market prices (volumes)",
      "dimension": {
        "geo": {"category": {"index": ["PL"]}},
        "unit": {"category": {"index": ["CLV10_MEUR"]}},
        "time": {
          "category": {
            "index": {
              "2026-Q1": 0,
              "2026-Q2": 1
            }
          }
        }
      },
      "value": {"0": 135400.5, "1": 136850.2}
    }""",
    "GUS_BDL_60270": """{
      "totalRecords": 1,
      "page": 0,
      "pageSize": 10,
      "variable": {
        "id": 60270,
        "subjectId": "P2437",
        "n1": "Stopa bezrobocia rejestrowanego",
        "measureUnitName": "%"
      },
      "results": [{
        "id": "000000000000",
        "name": "POLSKA",
        "values": [
          {"year": 2024, "val": 5.1, "attrId": 1},
          {"year": 2025, "val": 5.1, "attrId": 1}
        ]
      }]
    }""",
    "GUS_DBW_UNEMPLOYMENT": """{
      "page": 1,
      "page-size": 10,
      "total-records": 1,
      "data": [{
        "rownumber": 1,
        "id-zmienna": 875,
        "id-przekroj": 143,
        "id-wymiar-1": 10,
        "id-pozycja-1": 33617,
        "id-okres": 255,
        "id-sposob-prezentacji-miara": 95,
        "id-daty": 2026,
        "wartosc": 5.8,
        "precyzja": 2
      }]
    }""",
    "GUS_DBW_CPI": """{
      "page": 1,
      "page-size": 10,
      "total-records": 1,
      "data": [{
        "id-zmienna": 305,
        "id-przekroj": 736,
        "id-rok": 2026,
        "id-okres": 255,
        "id-sposob-prezentacji-miara": 5,
        "wartosc": 103.1,
        "precyzja": 1
      }]
    }""",
}


@dataclass
class PipelineResult:
    """Wynik wykonania pełnego procesu integracyjnego platformy danych v2."""
    success: bool
    run_id: str
    status: str
    records_fetched: int
    records_validated: int
    report_id: Optional[str] = None
    report_markdown: str = ""
    report_html: str = ""
    offline_mode: bool = False
    evidence_count: int = 0
    observations_count: int = 0
    search_news_count: int = 0
    quality_events: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class MacroPipelineV2:
    """Główny orkiestrator potoku pobierania, walidacji, zapisu, wyszukiwania i generowania raportów."""

    def __init__(
        self,
        db: Optional[SQLiteV2Storage] = None,
        offline_mode: bool = False,
        search_service: Optional[WebSearchService] = None,
        evaluator: Optional[EconomyEvaluator] = None,
        diagnostics_dir: os.PathLike[str] | str = Path("instance") / "logs",
    ):
        self.offline_mode = offline_mode or getattr(config, "OFFLINE_MODE", False)
        self.db = db or SQLiteV2Storage()
        self.search_service = search_service or WebSearchService(offline_mode=self.offline_mode)
        self.evaluator = evaluator or EconomyEvaluator()
        self.diagnostics = PipelineDiagnostics(diagnostics_dir)

        # Inicjalizacja konektorów
        self.nbp = NbpConnector(offline_mode=self.offline_mode)
        self.eurostat = EurostatConnector(offline_mode=self.offline_mode)
        self.gus = GusConnector(offline_mode=self.offline_mode)

        if self.offline_mode:
            self._register_offline_fixtures()

    def _register_offline_fixtures(self):
        """Rejestruje standardowe odpowiedzi API dla niezawodnych testów offline."""
        self.nbp.register_fixture("rates/A/EUR", OFFLINE_FIXTURES["NBP_EUR"])
        self.nbp.register_fixture("rates/A/USD", OFFLINE_FIXTURES["NBP_USD"])
        self.nbp.register_fixture("stopy_procentowe.xml", OFFLINE_FIXTURES["NBP_RATES"])

        self.eurostat.register_fixture("teicp000", OFFLINE_FIXTURES["EUROSTAT_TEICP000"])
        self.eurostat.register_fixture("une_rt_m", OFFLINE_FIXTURES["EUROSTAT_UNEMPLOYMENT"])
        self.eurostat.register_fixture("unit=PCH_PRE", OFFLINE_FIXTURES["EUROSTAT_GDP_QOQ"])
        self.eurostat.register_fixture("unit=CLV_PCH_PRE", OFFLINE_FIXTURES["EUROSTAT_GDP_QOQ"])
        self.eurostat.register_fixture("unit=PCH_SM_PR_Y", OFFLINE_FIXTURES["EUROSTAT_GDP_YOY"])
        self.eurostat.register_fixture("unit=CLV_PCH_SM", OFFLINE_FIXTURES["EUROSTAT_GDP_YOY"])
        self.eurostat.register_fixture("unit=CLV10_MEUR", OFFLINE_FIXTURES["EUROSTAT_GDP_VOLUME"])
        self.eurostat.register_fixture("namq_10_gdp", OFFLINE_FIXTURES["EUROSTAT_GDP_YOY"])

        self.gus.register_fixture("variables/60270", OFFLINE_FIXTURES["GUS_BDL_60270"])
        self.gus.register_fixture("data/by-variable/60270", OFFLINE_FIXTURES["GUS_BDL_60270"])
        self.gus.register_fixture("id-zmienna=305", OFFLINE_FIXTURES["GUS_DBW_CPI"])
        self.gus.register_fixture("id-zmienna=875", OFFLINE_FIXTURES["GUS_DBW_UNEMPLOYMENT"])
        self.gus.register_fixture("variable-data-section?id-zmienna=875", OFFLINE_FIXTURES["GUS_DBW_UNEMPLOYMENT"])
        self.gus.register_fixture("data/data-data", OFFLINE_FIXTURES["GUS_DBW_CPI"])

    # -------------------------------------------------------------------------
    # KROK 1: Pobieranie i walidacja oficjalnych danych z konektorów
    # -------------------------------------------------------------------------
    def fetch_official_data(
        self, run_id: str
    ) -> Tuple[List[RawEvidence], List[MacroObservation], List[str], List[str]]:
        """
        Pobiera dane z oficjalnych API NBP, Eurostat i GUS z obsługą częściowych awarii.
        Zwraca: (evidence_list, observation_list, quality_events, errors).
        """
        evidence_list: List[RawEvidence] = []
        observation_list: List[MacroObservation] = []
        q_events: List[str] = []
        errors: List[str] = []

        # 1. NBP - Kursy walut i stopa referencyjna
        t0_nbp = time.perf_counter()
        self.diagnostics.record_step(
            run_id=run_id,
            function="fetch_nbp",
            stage="START",
            input_summary="EUR, USD, reference rate",
        )
        nbp_errs: List[str] = []
        try:
            evi_eur, obs_eur = self.nbp.fetch_exchange_rate("EUR")
            evidence_list.append(evi_eur)
            observation_list.append(obs_eur)
        except Exception as err:
            msg = f"Błąd NBP EUR: {err}"
            errors.append(msg)
            nbp_errs.append(msg)
            qid = self.db.record_quality_event("INGESTION", run_id, "NBP_EUR_FAIL", "WARNING", str(err))
            q_events.append(qid)

        try:
            evi_usd, obs_usd = self.nbp.fetch_exchange_rate("USD")
            evidence_list.append(evi_usd)
            observation_list.append(obs_usd)
        except Exception as err:
            msg = f"Błąd NBP USD: {err}"
            errors.append(msg)
            nbp_errs.append(msg)
            qid = self.db.record_quality_event("INGESTION", run_id, "NBP_USD_FAIL", "WARNING", str(err))
            q_events.append(qid)

        try:
            evi_rate, obs_rate = self.nbp.fetch_reference_rate()
            evidence_list.append(evi_rate)
            observation_list.append(obs_rate)
        except Exception as err:
            msg = f"Błąd NBP Stopa Referencyjna: {err}"
            errors.append(msg)
            nbp_errs.append(msg)
            qid = self.db.record_quality_event("INGESTION", run_id, "NBP_RATE_FAIL", "WARNING", str(err))
            q_events.append(qid)

        dur_nbp = (time.perf_counter() - t0_nbp) * 1000.0
        nbp_evi_count = len([e for e in evidence_list if "NBP" in e.source_id or "EUR" in e.source_url or "USD" in e.source_url or "stopy" in e.source_url])
        if nbp_errs:
            self.diagnostics.record_step(
                run_id=run_id,
                function="fetch_nbp",
                stage="ERROR",
                duration_ms=dur_nbp,
                input_summary="EUR, USD, reference rate",
                output_summary=f"evidence_count={nbp_evi_count}",
                error_code="NBP_CONNECTOR_ERROR",
                error_message="; ".join(nbp_errs),
            )
        else:
            self.diagnostics.record_step(
                run_id=run_id,
                function="fetch_nbp",
                stage="END",
                duration_ms=dur_nbp,
                input_summary="EUR, USD, reference rate",
                output_summary=f"evidence_count={nbp_evi_count}",
            )

        # 2. Eurostat - HICP, bezrobocie zharmonizowane, PKB (kw/kw, r/r, wolumen)
        t0_euro = time.perf_counter()
        self.diagnostics.record_step(
            run_id=run_id,
            function="fetch_eurostat",
            stage="START",
            input_summary="HICP, unemployment, GDP",
        )
        euro_errs: List[str] = []
        try:
            evi_hicp, obs_hicp = self.eurostat.fetch_hicp()
            evidence_list.append(evi_hicp)
            observation_list.extend(obs_hicp)
        except Exception as err:
            msg = f"Błąd Eurostat HICP: {err}"
            errors.append(msg)
            euro_errs.append(msg)
            qid = self.db.record_quality_event("INGESTION", run_id, "EUROSTAT_HICP_FAIL", "WARNING", str(err))
            q_events.append(qid)

        try:
            evi_unemp, obs_unemp = self.eurostat.fetch_harmonized_unemployment()
            evidence_list.append(evi_unemp)
            observation_list.extend(obs_unemp)
        except Exception as err:
            msg = f"Błąd Eurostat Bezrobocie BAEL: {err}"
            errors.append(msg)
            euro_errs.append(msg)
            qid = self.db.record_quality_event("INGESTION", run_id, "EUROSTAT_UNEMP_FAIL", "WARNING", str(err))
            q_events.append(qid)

        for measure_name in ("GROWTH_QOQ", "GROWTH_YOY", "VOLUME_MEUR"):
            try:
                evi_gdp, obs_gdp = self.eurostat.fetch_quarterly_gdp(geo="PL", measure=measure_name)
                evidence_list.append(evi_gdp)
                observation_list.extend(obs_gdp)
            except Exception as err:
                msg = f"Błąd Eurostat PKB ({measure_name}): {err}"
                errors.append(msg)
                euro_errs.append(msg)
                qid = self.db.record_quality_event("INGESTION", run_id, f"EUROSTAT_GDP_{measure_name}_FAIL", "WARNING", str(err))
                q_events.append(qid)

        dur_euro = (time.perf_counter() - t0_euro) * 1000.0
        euro_evi_count = len([e for e in evidence_list if "EUROSTAT" in e.source_id or "europa.eu" in e.source_url])
        if euro_errs:
            self.diagnostics.record_step(
                run_id=run_id,
                function="fetch_eurostat",
                stage="ERROR",
                duration_ms=dur_euro,
                input_summary="HICP, unemployment, GDP",
                output_summary=f"evidence_count={euro_evi_count}",
                error_code="EUROSTAT_CONNECTOR_ERROR",
                error_message="; ".join(euro_errs),
            )
        else:
            self.diagnostics.record_step(
                run_id=run_id,
                function="fetch_eurostat",
                stage="END",
                duration_ms=dur_euro,
                input_summary="HICP, unemployment, GDP",
                output_summary=f"evidence_count={euro_evi_count}",
            )

        # 3. GUS - DBW Stopa bezrobocia miesięczna (875/143), BDL Roczna (60270), DBW CPI (305/736)
        t0_gus = time.perf_counter()
        self.diagnostics.record_step(
            run_id=run_id,
            function="fetch_gus",
            stage="START",
            input_summary="monthly unemployment DBW 875, annual BDL 60270, CPI DBW 305/736",
        )
        gus_errs: List[str] = []
        try:
            evi_gus_unemp_m, obs_gus_unemp_m = self.gus.fetch_registered_unemployment_monthly_dbw()
            evidence_list.append(evi_gus_unemp_m)
            observation_list.append(obs_gus_unemp_m)
        except Exception as err:
            msg = f"Błąd GUS DBW Miesięczna stopa bezrobocia: {err}"
            errors.append(msg)
            gus_errs.append(msg)
            qid = self.db.record_quality_event("INGESTION", run_id, "GUS_DBW_UNEMP_FAIL", "WARNING", str(err))
            q_events.append(qid)

        try:
            evi_gus_unemp, obs_gus_unemp = self.gus.fetch_registered_unemployment()
            evidence_list.append(evi_gus_unemp)
            observation_list.extend(obs_gus_unemp)
        except Exception as err:
            msg = f"Błąd GUS BDL Stopa bezrobocia (roczna): {err}"
            errors.append(msg)
            gus_errs.append(msg)
            qid = self.db.record_quality_event("INGESTION", run_id, "GUS_BDL_UNEMP_FAIL", "WARNING", str(err))
            q_events.append(qid)

        try:
            evi_cpi, obs_cpi = self.gus.fetch_cpi_dbw()
            evidence_list.append(evi_cpi)
            observation_list.append(obs_cpi)
        except Exception as err:
            msg = f"Błąd GUS DBW CPI: {err}"
            errors.append(msg)
            gus_errs.append(msg)
            qid = self.db.record_quality_event("INGESTION", run_id, "GUS_DBW_CPI_FAIL", "WARNING", str(err))
            q_events.append(qid)

        # Próba pobrania liczby bezrobotnych - kontrolowana obsługa wycofanej zmiennej BDL 60269
        try:
            evi_cnt, obs_cnt = self.gus.fetch_registered_unemployment_count()
            evidence_list.append(evi_cnt)
            observation_list.extend(obs_cnt)
        except (VariableNotMappedError, DataNotFoundError) as unmapped_err:
            qid = self.db.record_quality_event(
                "INGESTION",
                run_id,
                "GUS_UNEMPLOYMENT_COUNT_UNMAPPED",
                "WARNING",
                f"Wskaźnik PL_UNEMPLOYMENT_REGISTERED_COUNT pozostaje NOT_VERIFIED: {unmapped_err}",
            )
            q_events.append(qid)
        except Exception as err:
            msg = f"Nieoczekiwany błąd GUS Liczba bezrobotnych: {err}"
            errors.append(msg)
            gus_errs.append(msg)

        dur_gus = (time.perf_counter() - t0_gus) * 1000.0
        gus_evi_count = len([e for e in evidence_list if "GUS" in e.source_id or "stat.gov.pl" in e.source_url])
        if gus_errs:
            self.diagnostics.record_step(
                run_id=run_id,
                function="fetch_gus",
                stage="ERROR",
                duration_ms=dur_gus,
                input_summary="unemployment 60270, CPI DBW 305/736",
                output_summary=f"evidence_count={gus_evi_count}",
                error_code="GUS_CONNECTOR_ERROR",
                error_message="; ".join(gus_errs),
            )
        else:
            self.diagnostics.record_step(
                run_id=run_id,
                function="fetch_gus",
                stage="END",
                duration_ms=dur_gus,
                input_summary="unemployment 60270, CPI DBW 305/736",
                output_summary=f"evidence_count={gus_evi_count}",
            )

        return evidence_list, observation_list, q_events, errors

    # -------------------------------------------------------------------------
    # KROK 2: Zapis w SQLite v2 (strictly append-only)
    # -------------------------------------------------------------------------
    def store_official_data(
        self,
        evidence_list: List[RawEvidence],
        observation_list: List[MacroObservation],
        run_id: str,
    ) -> Tuple[int, int]:
        """Zapisuje dowody źródłowe oraz obserwacje w bazie SQLite v2."""
        t0 = time.perf_counter()
        self.diagnostics.record_step(
            run_id=run_id,
            function="store_sqlite",
            stage="START",
            input_summary=f"evidence_count={len(evidence_list)}, observations_count={len(observation_list)}",
        )
        try:
            today_iso = datetime.now().date().isoformat()
            filtered_observations = [
                obs for obs in observation_list
                if not (obs.period_end > today_iso and obs.revision_type != "FORECAST")
            ]
            for evi in evidence_list:
                self.db.save_evidence(evi, run_id=run_id)

            saved_obs = self.db.save_observations(filtered_observations, run_id=run_id)
            dur = (time.perf_counter() - t0) * 1000.0
            self.diagnostics.record_step(
                run_id=run_id,
                function="store_sqlite",
                stage="END",
                duration_ms=dur,
                input_summary=f"evidence_count={len(evidence_list)}, observations_count={len(observation_list)}",
                output_summary=f"saved_evidence={len(evidence_list)}, saved_observations={saved_obs}",
            )
            return len(evidence_list), saved_obs
        except Exception as err:
            dur = (time.perf_counter() - t0) * 1000.0
            self.diagnostics.record_step(
                run_id=run_id,
                function="store_sqlite",
                stage="ERROR",
                duration_ms=dur,
                input_summary=f"evidence_count={len(evidence_list)}, observations_count={len(observation_list)}",
                error_code=type(err).__name__,
                error_message=safe_error_message(err),
            )
            raise

    # -------------------------------------------------------------------------
    # KROK 3: Wzbogacenie o wyszukiwanie Tavily
    # -------------------------------------------------------------------------
    def search_enrichment(self, country: str, run_id: str) -> List[Dict[str, Any]]:
        """Wyszukuje analizy i komunikaty makroekonomiczne oraz zapisuje je jako dowody źródłowe."""
        t0 = time.perf_counter()
        self.diagnostics.record_step(
            run_id=run_id,
            function="search_tavily",
            stage="START",
            input_summary=f"country={country}",
        )
        try:
            news_items = self.search_service.search_economic_news(country=country)

            # Zapis każdego wycinka prasowego jako dowodu typu SEARCH_SNIPPET
            for idx, item in enumerate(news_items):
                url = item.get("url", "https://tavily.com")
                payload = f"{item.get('title')}\n{item.get('content')}"
                c_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
                evi_id = f"EVI_TAVILY_{uuid.uuid4().hex[:12]}"
                evi = RawEvidence(
                    evidence_id=evi_id,
                    source_id="SRC_TAVILY",
                    source_url=url,
                    document_type="SEARCH_SNIPPET",
                    content_hash=c_hash,
                    payload_text=payload,
                    status_code=200,
                    retrieved_at_utc=item.get("retrieved_at_utc") or datetime.now(timezone.utc).isoformat(),
                )
                self.db.save_evidence(evi, run_id=run_id)

            dur = (time.perf_counter() - t0) * 1000.0
            self.diagnostics.record_step(
                run_id=run_id,
                function="search_tavily",
                stage="END",
                duration_ms=dur,
                input_summary=f"country={country}",
                output_summary=f"results_count={len(news_items)}",
            )
            return news_items
        except Exception as err:
            dur = (time.perf_counter() - t0) * 1000.0
            self.diagnostics.record_step(
                run_id=run_id,
                function="search_tavily",
                stage="ERROR",
                duration_ms=dur,
                input_summary=f"country={country}",
                error_code=type(err).__name__,
                error_message=safe_error_message(err),
            )
            raise

    # -------------------------------------------------------------------------
    # KROK 4 i 5: Generowanie i archiwizacja raportu analitycznego
    # -------------------------------------------------------------------------
    def generate_and_archive_report(
        self,
        country: str,
        search_news: List[Dict[str, Any]],
        run_id: str,
        output_html_path: Optional[str] = None,
    ) -> Tuple[str, str, str]:
        """Generuje raport z aparatem krytycznym, zapisuje w v2 i generuje HTML."""
        from app import build_html_template

        report_markdown = self.evaluator.evaluate_from_v2(
            country=country,
            storage=self.db,
            search_news=search_news,
            offline_mode=self.offline_mode,
            run_id=run_id,
            diagnostics=self.diagnostics,
        )

        report_html = build_html_template(report_markdown, country)
        report_id = f"REP_V2_{uuid.uuid4().hex[:10]}"
        now = datetime.now()
        report_date = now.strftime("%Y-%m-%d")

        # Ustalenie horyzontu analizy
        verified = self.db.get_latest_verified_observations(
            country_code="PL",
            run_id=run_id,
        )
        m_horiz = re.search(r"\*\*Horyzont analizowanych danych:\*\*\s*(.+)", report_markdown)
        if m_horiz:
            exec_horizon = m_horiz.group(1).strip()
        else:
            raw_periods = [o["period_start"] for o in verified]
            from modules.evaluator import build_executive_horizon
            exec_horizon = build_executive_horizon(raw_periods)

        # Deterministyczny hash migawki
        snap_payload = f"{country}|{report_date}|{exec_horizon}|{report_markdown}"
        snap_hash = hashlib.sha256(snap_payload.encode("utf-8")).hexdigest()

        generation_diagnostics = dict(self.evaluator.last_generation_diagnostics)
        model_meta = {
            "orchestrator": "MacroPipelineV2",
            "run_id": run_id,
            "offline_mode": self.offline_mode,
            "verified_indicators_count": len(verified),
            "generation_mode": generation_diagnostics.get("generation_mode"),
            "gpt_attempted": generation_diagnostics.get("gpt_attempted", False),
            "fallback_reason": generation_diagnostics.get("fallback_reason"),
            "search_context": (
                "OFFLINE_DEMO_FIXTURES"
                if self.offline_mode
                else ("LIVE" if search_news else "UNAVAILABLE_NO_FALLBACK")
            ),
        }

        temp_html_path = None
        t0_html = None
        if output_html_path:
            t0_html = time.perf_counter()
            self.diagnostics.record_step(
                run_id=run_id,
                function="write_html",
                stage="START",
                input_summary=f"path={output_html_path}",
            )
            try:
                temp_html_path = f"{output_html_path}.tmp.{uuid.uuid4().hex[:8]}"
                with open(temp_html_path, "w", encoding="utf-8") as f:
                    f.write(report_html)
                    f.flush()
                    os.fsync(f.fileno())
            except Exception as err:
                dur_html = (time.perf_counter() - t0_html) * 1000.0
                self.diagnostics.record_step(
                    run_id=run_id,
                    function="write_html",
                    stage="ERROR",
                    duration_ms=dur_html,
                    input_summary=f"path={output_html_path}",
                    error_code=type(err).__name__,
                    error_message=safe_error_message(err),
                )
                if temp_html_path and os.path.exists(temp_html_path):
                    try:
                        os.remove(temp_html_path)
                    except Exception:
                        pass
                raise

        t0_rep = time.perf_counter()
        self.diagnostics.record_step(
            run_id=run_id,
            function="store_sqlite",
            stage="START",
            input_summary=f"report_id={report_id}, snapshot_hash={snap_hash[:8]}",
        )
        report_saved_in_db = False
        try:
            # Krok A: Zapis raportu do SQLite ze statusem PENDING (nieopublikowany)
            self.db.save_report(
                report_id=report_id,
                country_code="PL",
                report_date=report_date,
                executive_horizon=exec_horizon,
                report_markdown=report_markdown,
                report_html=report_html,
                data_snapshot_hash=snap_hash,
                model_metadata=model_meta,
                publication_status="PENDING",
            )
            report_saved_in_db = True
            dur_rep = (time.perf_counter() - t0_rep) * 1000.0
            self.diagnostics.record_step(
                run_id=run_id,
                function="store_sqlite",
                stage="END",
                duration_ms=dur_rep,
                input_summary=f"report_id={report_id}",
                output_summary=f"report_id={report_id}, status=PENDING",
            )

            # Krok B: Atomowa podmiana pliku HTML na docelową ścieżkę
            if output_html_path and temp_html_path:
                try:
                    os.replace(temp_html_path, output_html_path)
                    dur_html = (time.perf_counter() - t0_html) * 1000.0
                    self.diagnostics.record_step(
                        run_id=run_id,
                        function="write_html",
                        stage="END",
                        duration_ms=dur_html,
                        input_summary=f"path={output_html_path}",
                        output_summary=f"bytes_written={len(report_html.encode('utf-8'))}",
                    )
                except Exception as err:
                    dur_html = (time.perf_counter() - t0_html) * 1000.0
                    self.diagnostics.record_step(
                        run_id=run_id,
                        function="write_html",
                        stage="ERROR",
                        duration_ms=dur_html,
                        input_summary=f"path={output_html_path}",
                        error_code=type(err).__name__,
                        error_message=safe_error_message(err),
                    )
                    raise

            # Krok C: Oznaczenie raportu jako PUBLISHED w bazie SQLite dopiero po sukcesie zapisu HTML
            published = self.db.mark_report_published(report_id)
            if not published:
                raise RuntimeError(
                    f"Publication failed: mark_report_published returned False for report_id '{report_id}'"
                )

        except Exception as pub_err:
            # Procedura odzyskiwania po błędzie publikacji (oznaczenie FAILED, rollback SQLite i czyszczenie plików)
            if report_saved_in_db:
                try:
                    self.db.mark_report_failed(report_id)
                except Exception as fail_err:
                    self.diagnostics.event(
                        logging.ERROR,
                        f"Failed to mark un-published report {report_id} as FAILED: {safe_error_message(fail_err)}",
                        run_id=run_id,
                    )
                try:
                    self.db.delete_report(report_id)
                    self.diagnostics.event(
                        logging.WARNING,
                        f"Publication failed: rolled back un-published report {report_id} from SQLite v2",
                        run_id=run_id,
                    )
                except Exception as del_err:
                    self.diagnostics.event(
                        logging.ERROR,
                        f"Failed to delete un-published report {report_id} from SQLite v2: {safe_error_message(del_err)}",
                        run_id=run_id,
                    )
            if temp_html_path and os.path.exists(temp_html_path):
                try:
                    os.remove(temp_html_path)
                except Exception:
                    pass
            if output_html_path and os.path.exists(output_html_path):
                try:
                    os.remove(output_html_path)
                except Exception:
                    pass
            raise

        return report_id, report_markdown, report_html

    # -------------------------------------------------------------------------
    # Główna metoda wykonawcza potoku
    # -------------------------------------------------------------------------
    def run(
        self,
        country: str = "Polska",
        output_html_path: Optional[str] = None,
        force_refresh: bool = True,
    ) -> PipelineResult:
        """
        Uruchamia pełny, zintegrowany proces platformy danych v2.
        """
        run_id = f"UNAVAILABLE_{uuid.uuid4().hex[:12]}"
        summary = base_run_summary(run_id=run_id, offline_mode=self.offline_mode)
        q_events: List[str] = []
        errors: List[str] = []
        evidence_list: List[RawEvidence] = []
        observation_list: List[MacroObservation] = []
        search_news: List[Dict[str, Any]] = []
        saved_obs = 0
        run_started = False
        self.diagnostics.event(logging.INFO, "Pipeline execution requested", run_id=run_id)
        try:
            # Bezpieczna procedura odzyskiwania przy starcie potoku (PENDING -> FAILED)
            self.db.recover_pending_reports()
            run_id = self.db.start_ingestion_run(provider="MANUAL", run_type="TRIGGERED")
            run_started = True
            summary["run_id"] = run_id
            summary["pipeline_status"] = "STARTED"
            self.diagnostics.write_summary(summary)
            self.diagnostics.event(
                logging.INFO,
                f"Pipeline started (offline_mode={self.offline_mode})",
                run_id=run_id,
            )
            print(f"[PipelineV2] Uruchomiono przebieg: {run_id} (offline_mode={self.offline_mode})")

            # 1. Pobieranie danych oficjalnych
            evidence_list, observation_list, q_events, errors = self.fetch_official_data(run_id)
            self.diagnostics.event(
                logging.INFO,
                f"Official data fetched: evidence={len(evidence_list)}, observations={len(observation_list)}",
                run_id=run_id,
            )
            for partial_error in errors:
                self.diagnostics.event(
                    logging.WARNING,
                    f"Partial connector failure: {partial_error}",
                    run_id=run_id,
                )
            print(f"[PipelineV2] Pobrano {len(evidence_list)} dowodów oraz {len(observation_list)} obserwacji.")

            # 2. Zapis w bazie SQLite v2
            saved_evi, saved_obs = self.store_official_data(evidence_list, observation_list, run_id)
            self.diagnostics.event(
                logging.INFO,
                f"Official data stored: evidence={saved_evi}, observations={saved_obs}",
                run_id=run_id,
            )
            print(f"[PipelineV2] Zapisano do bazy v2: {saved_evi} dowodów, {saved_obs} obserwacji.")

            # 3. Wyszukiwanie Tavily i wzbogacenie kontekstu
            search_news = self.search_enrichment(country, run_id)
            summary["tavily_results_count"] = len(search_news)
            summary["tavily_status"] = (
                "OFFLINE_DEMO"
                if self.offline_mode
                else ("SUCCESS" if search_news else "UNAVAILABLE")
            )
            self.diagnostics.event(
                logging.INFO if search_news or self.offline_mode else logging.WARNING,
                f"Tavily status={summary['tavily_status']}, results={len(search_news)}",
                run_id=run_id,
            )
            print(f"[PipelineV2] Zebrano {len(search_news)} analiz i komunikatów rynkowych.")
            if not self.offline_mode and not search_news:
                message = "Kontekst Tavily niedostępny; nie użyto fixture'ów offline."
                errors.append(message)
                q_events.append(self.db.record_quality_event(
                    "INGESTION",
                    run_id,
                    "LIVE_SEARCH_UNAVAILABLE",
                    "WARNING",
                    message,
                ))

            # 4 i 5. Analiza AI i archiwizacja raportu
            report_id, report_md, report_html = self.generate_and_archive_report(
                country=country,
                search_news=search_news,
                run_id=run_id,
                output_html_path=output_html_path,
            )
            generation_diagnostics = self.evaluator.last_generation_diagnostics
            summary.update({
                "generation_mode": generation_diagnostics.get("generation_mode"),
                "gpt_attempted": generation_diagnostics.get("gpt_attempted", False),
                "fallback_reason": generation_diagnostics.get("fallback_reason"),
                "report_id": report_id,
            })
            generation_level = (
                logging.INFO
                if summary["generation_mode"] in {"LIVE_AI_VALIDATED", "OFFLINE_DEMO"}
                else logging.WARNING
            )
            generation_message = f"Report generation mode={summary['generation_mode']}"
            if summary["fallback_reason"]:
                generation_message += f"; reason={summary['fallback_reason']}"
            self.diagnostics.event(generation_level, generation_message, run_id=run_id)
            print(f"[PipelineV2] Raport pomyślnie zarchiwizowany pod ID: {report_id}")

            status = "PARTIAL" if errors else "COMPLETED"
            self.db.finish_ingestion_run(
                run_id=run_id,
                status=status,
                records_fetched=len(observation_list),
                records_validated=saved_obs,
                error_message="; ".join(errors) if errors else None,
            )

            verified = self.db.get_latest_verified_observations(
                country_code="PL",
                run_id=run_id,
            )
            summary.update({
                "pipeline_status": status,
                "verified_indicators_count": len(verified),
                "missing_indicators": missing_report_indicators(verified),
            })
            self.diagnostics.write_summary(summary)
            self.diagnostics.event(
                logging.INFO if status == "COMPLETED" else logging.WARNING,
                f"Pipeline finished with status={status}, report_id={report_id}",
                run_id=run_id,
            )

            return PipelineResult(
                success=True,
                run_id=run_id,
                status=status,
                records_fetched=len(observation_list),
                records_validated=saved_obs,
                report_id=report_id,
                report_markdown=report_md,
                report_html=report_html,
                offline_mode=self.offline_mode,
                evidence_count=len(evidence_list),
                observations_count=len(observation_list),
                search_news_count=len(search_news),
                quality_events=q_events,
                errors=errors,
            )

        except Exception as exc:
            failure_reason = safe_error_message(exc)
            print(f"[PipelineV2 Error] Niepowodzenie potoku: {failure_reason}")
            self.diagnostics.event(
                logging.ERROR,
                f"Pipeline failed: {failure_reason}",
                run_id=run_id,
            )
            if run_started:
                try:
                    self.db.finish_ingestion_run(
                        run_id=run_id,
                        status="FAILED",
                        records_fetched=len(observation_list),
                        records_validated=saved_obs,
                        error_message=failure_reason,
                    )
                except Exception as finish_exc:
                    self.diagnostics.event(
                        logging.ERROR,
                        f"Could not persist FAILED ingestion status: {safe_error_message(finish_exc)}",
                        run_id=run_id,
                    )

            generation_diagnostics = self.evaluator.last_generation_diagnostics
            gpt_attempted = generation_diagnostics.get("gpt_attempted", False)
            gen_mode = generation_diagnostics.get("generation_mode")
            if not gpt_attempted and not self.offline_mode:
                gen_mode = None

            try:
                verified = self.db.get_latest_verified_observations(country_code="PL", run_id=run_id)
            except Exception:
                verified = []

            summary.update({
                "run_id": run_id,
                "pipeline_status": "FAILED",
                "fallback_reason": generation_diagnostics.get("fallback_reason") or failure_reason,
                "gpt_attempted": gpt_attempted,
                "generation_mode": gen_mode if gen_mode else ("OFFLINE_DEMO" if self.offline_mode else None),
                "tavily_results_count": len(search_news),
                "verified_indicators_count": len(verified),
                "missing_indicators": missing_report_indicators(verified),
                "report_id": None,
            })
            if summary["tavily_status"] == "NOT_RUN" and self.offline_mode:
                summary["tavily_status"] = "NOT_RUN_OFFLINE"
            self.diagnostics.write_summary(summary)
            return PipelineResult(
                success=False,
                run_id=run_id,
                status="FAILED",
                records_fetched=len(observation_list),
                records_validated=saved_obs,
                report_id=None,
                report_markdown="",
                report_html="",
                offline_mode=self.offline_mode,
                quality_events=q_events,
                evidence_count=len(evidence_list),
                observations_count=len(observation_list),
                search_news_count=len(search_news),
                errors=errors + [failure_reason],
            )
