"""
Moduł orkiestratora platformy danych makroekonomicznych SQLite v2 (TASK-06).
Plik: modules/pipeline_v2.py

Integruje cały proces w jeden działający, w pełni kontrolowany i audytowalny potok:
1. POBIERANIE (Connectors: NBP, Eurostat, GUS).
2. WALIDACJA (typy, jednostki, definicje, okresy, brak zgadywania).
3. ZAPIS (SQLite v2: ingestion_runs, source_evidence, observations - strictly append-only).
4. WYSZUKIWANIE (Tavily Search: komunikaty oficjalne vs komentarze medialne).
5. ANALIZA AI (EconomyEvaluator / Gemini / GPT z bezpiecznym trybem offline).
6. RAPORT (wielosekcyjny raport analityczny z aparatem źródłowym, zapis w tabeli reports oraz w HTML).
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
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
      "rates": [{"no": "212/A/NBP/2026", "effectiveDate": "2026-10-30", "mid": 4.3450}]
    }""",
    "NBP_USD": """{
      "table": "A",
      "currency": "dolar amerykański",
      "code": "USD",
      "rates": [{"no": "212/A/NBP/2026", "effectiveDate": "2026-10-30", "mid": 4.0215}]
    }""",
    "NBP_RATES": """<?xml version="1.0" encoding="utf-8"?>
    <stopy_procentowe>
        <pozycja id="ref" obowiazuje_od="2023-10-05" oprocentowanie="5.75"/>
        <pozycja id="lom" obowiazuje_od="2023-10-05" oprocentowanie="6.25"/>
        <pozycja id="dep" obowiazuje_od="2023-10-05" oprocentowanie="5.25"/>
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
          {"year": 2025, "val": 5.1, "attrId": 1},
          {"year": 2026, "val": 5.0, "attrId": 1}
        ]
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
    ):
        self.offline_mode = offline_mode or getattr(config, "OFFLINE_MODE", False)
        self.db = db or SQLiteV2Storage()
        self.search_service = search_service or WebSearchService(offline_mode=self.offline_mode)
        self.evaluator = evaluator or EconomyEvaluator()

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
        try:
            evi_eur, obs_eur = self.nbp.fetch_exchange_rate("EUR")
            evidence_list.append(evi_eur)
            observation_list.append(obs_eur)
        except Exception as err:
            errors.append(f"Błąd NBP EUR: {err}")
            qid = self.db.record_quality_event("INGESTION", run_id, "NBP_EUR_FAIL", "WARNING", str(err))
            q_events.append(qid)

        try:
            evi_usd, obs_usd = self.nbp.fetch_exchange_rate("USD")
            evidence_list.append(evi_usd)
            observation_list.append(obs_usd)
        except Exception as err:
            errors.append(f"Błąd NBP USD: {err}")
            qid = self.db.record_quality_event("INGESTION", run_id, "NBP_USD_FAIL", "WARNING", str(err))
            q_events.append(qid)

        try:
            evi_rate, obs_rate = self.nbp.fetch_reference_rate()
            evidence_list.append(evi_rate)
            observation_list.append(obs_rate)
        except Exception as err:
            errors.append(f"Błąd NBP Stopa Referencyjna: {err}")
            qid = self.db.record_quality_event("INGESTION", run_id, "NBP_RATE_FAIL", "WARNING", str(err))
            q_events.append(qid)

        # 2. Eurostat - HICP, bezrobocie zharmonizowane, PKB (kw/kw, r/r, wolumen)
        try:
            evi_hicp, obs_hicp = self.eurostat.fetch_hicp()
            evidence_list.append(evi_hicp)
            observation_list.extend(obs_hicp)
        except Exception as err:
            errors.append(f"Błąd Eurostat HICP: {err}")
            qid = self.db.record_quality_event("INGESTION", run_id, "EUROSTAT_HICP_FAIL", "WARNING", str(err))
            q_events.append(qid)

        try:
            evi_unemp, obs_unemp = self.eurostat.fetch_harmonized_unemployment()
            evidence_list.append(evi_unemp)
            observation_list.extend(obs_unemp)
        except Exception as err:
            errors.append(f"Błąd Eurostat Bezrobocie BAEL: {err}")
            qid = self.db.record_quality_event("INGESTION", run_id, "EUROSTAT_UNEMP_FAIL", "WARNING", str(err))
            q_events.append(qid)

        for measure_name in ("GROWTH_QOQ", "GROWTH_YOY", "VOLUME_MEUR"):
            try:
                evi_gdp, obs_gdp = self.eurostat.fetch_quarterly_gdp(geo="PL", measure=measure_name)
                evidence_list.append(evi_gdp)
                observation_list.extend(obs_gdp)
            except Exception as err:
                errors.append(f"Błąd Eurostat PKB ({measure_name}): {err}")
                qid = self.db.record_quality_event("INGESTION", run_id, f"EUROSTAT_GDP_{measure_name}_FAIL", "WARNING", str(err))
                q_events.append(qid)

        # 3. GUS - BDL Stopa bezrobocia (60270), DBW CPI (305/736)
        try:
            evi_gus_unemp, obs_gus_unemp = self.gus.fetch_registered_unemployment()
            evidence_list.append(evi_gus_unemp)
            observation_list.extend(obs_gus_unemp)
        except Exception as err:
            errors.append(f"Błąd GUS BDL Stopa bezrobocia: {err}")
            qid = self.db.record_quality_event("INGESTION", run_id, "GUS_BDL_UNEMP_FAIL", "WARNING", str(err))
            q_events.append(qid)

        try:
            evi_cpi, obs_cpi = self.gus.fetch_cpi_dbw(rok=2026, okres_id=255, month=9)
            evidence_list.append(evi_cpi)
            observation_list.append(obs_cpi)
        except Exception as err:
            errors.append(f"Błąd GUS DBW CPI: {err}")
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
            errors.append(f"Nieoczekiwany błąd GUS Liczba bezrobotnych: {err}")

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
        for evi in evidence_list:
            self.db.save_evidence(evi, run_id=run_id)

        saved_obs = self.db.save_observations(observation_list, run_id=run_id)
        return len(evidence_list), saved_obs

    # -------------------------------------------------------------------------
    # KROK 3: Wzbogacenie o wyszukiwanie Tavily
    # -------------------------------------------------------------------------
    def search_enrichment(self, country: str, run_id: str) -> List[Dict[str, Any]]:
        """Wyszukuje analizy i komunikaty makroekonomiczne oraz zapisuje je jako dowody źródłowe."""
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

        return news_items

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
        )

        report_html = build_html_template(report_markdown, country)
        report_id = f"REP_V2_{uuid.uuid4().hex[:10]}"
        now = datetime.now()
        report_date = now.strftime("%Y-%m-%d")

        # Ustalenie horyzontu analizy
        verified = self.db.get_verified_current_observations(country_code="PL")
        raw_periods = [o["period_start"] for o in verified]
        from modules.evaluator import build_executive_horizon
        exec_horizon = build_executive_horizon(raw_periods)

        # Deterministyczny hash migawki
        snap_payload = f"{country}|{report_date}|{exec_horizon}|{report_markdown}"
        snap_hash = hashlib.sha256(snap_payload.encode("utf-8")).hexdigest()

        model_meta = {
            "orchestrator": "MacroPipelineV2",
            "run_id": run_id,
            "offline_mode": self.offline_mode,
            "verified_indicators_count": len(verified),
        }

        self.db.save_report(
            report_id=report_id,
            country_code="PL",
            report_date=report_date,
            executive_horizon=exec_horizon,
            report_markdown=report_markdown,
            report_html=report_html,
            data_snapshot_hash=snap_hash,
            model_metadata=model_meta,
        )

        if output_html_path:
            with open(output_html_path, "w", encoding="utf-8") as f:
                f.write(report_html)

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
        run_id = self.db.start_ingestion_run(provider="MANUAL", run_type="TRIGGERED")
        print(f"[PipelineV2] Uruchomiono przebieg: {run_id} (offline_mode={self.offline_mode})")

        try:
            # 1. Pobieranie danych oficjalnych
            evidence_list, observation_list, q_events, errors = self.fetch_official_data(run_id)
            print(f"[PipelineV2] Pobrano {len(evidence_list)} dowodów oraz {len(observation_list)} obserwacji.")

            # 2. Zapis w bazie SQLite v2
            saved_evi, saved_obs = self.store_official_data(evidence_list, observation_list, run_id)
            print(f"[PipelineV2] Zapisano do bazy v2: {saved_evi} dowodów, {saved_obs} obserwacji.")

            # 3. Wyszukiwanie Tavily i wzbogacenie kontekstu
            search_news = self.search_enrichment(country, run_id)
            print(f"[PipelineV2] Zebrano {len(search_news)} analiz i komunikatów rynkowych.")

            # 4 i 5. Analiza AI i archiwizacja raportu
            report_id, report_md, report_html = self.generate_and_archive_report(
                country=country,
                search_news=search_news,
                run_id=run_id,
                output_html_path=output_html_path,
            )
            print(f"[PipelineV2] Raport pomyślnie zarchiwizowany pod ID: {report_id}")

            status = "PARTIAL" if errors else "COMPLETED"
            self.db.finish_ingestion_run(
                run_id=run_id,
                status=status,
                records_fetched=len(observation_list),
                records_validated=saved_obs,
                error_message="; ".join(errors) if errors else None,
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
            print(f"[PipelineV2 Error] Niepowodzenie potoku: {exc}")
            self.db.finish_ingestion_run(
                run_id=run_id,
                status="FAILED",
                records_fetched=0,
                records_validated=0,
                error_message=str(exc),
            )
            return PipelineResult(
                success=False,
                run_id=run_id,
                status="FAILED",
                records_fetched=0,
                records_validated=0,
                report_id=None,
                report_markdown="",
                report_html="",
                offline_mode=self.offline_mode,
                quality_events=q_events,
                errors=errors + [str(exc)],
            )
