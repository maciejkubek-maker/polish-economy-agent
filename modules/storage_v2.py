"""
Moduł warstwy danych SQLite v2 dla Polish Economy Agent (TASK-06).
Plik: modules/storage_v2.py

Zapewnia:
1. Zgodność ze schematem docs/sql/schema_v2.sql.
2. Bezwzględną nietykalność chronionej bazy legacy (instance/economy_agent.db).
3. Ścisłe egzekwowanie append-only dla tabeli observations (ochrona przez triggery i wersjonowanie).
4. Rejestrowanie przebiegów pobierania (ingestion_runs), dowodów źródłowych (source_evidence) i zdarzeń jakościowych (quality_events).
5. Automatyczną obsługę tabeli current_observations i spójność z v_latest_observations.
6. Obsługę zapisywania i odczytu wygenerowanych raportów.
"""

from datetime import datetime, timezone
import hashlib
import json
import os
import sqlite3
from typing import Any, Dict, List, Optional, Tuple
import uuid

import config
from modules.connectors.base import MacroObservation, RawEvidence


DEFAULT_SOURCES = [
    ("SRC_NBP", "Narodowy Bank Polski", "Narodowy Bank Polski", "https://api.nbp.pl", "OFFICIAL_API", "TIER_A", "DAILY", 1),
    ("SRC_GUS", "Główny Urząd Statystyczny", "Główny Urząd Statystyczny", "https://stat.gov.pl", "OFFICIAL_API", "TIER_A", "MONTHLY", 1),
    ("SRC_GUS_BDL", "Główny Urząd Statystyczny - Bank Danych Lokalnych", "Główny Urząd Statystyczny", "https://bdl.stat.gov.pl/api/v1.0", "OFFICIAL_API", "TIER_A", "ANNUAL", 1),
    ("SRC_GUS_DBW", "Główny Urząd Statystyczny - Dziedzinowe Bazy Wiedzy", "Główny Urząd Statystyczny", "https://api-dbw.stat.gov.pl/api/1.1.0", "OFFICIAL_API", "TIER_A", "MONTHLY", 1),
    ("SRC_EUROSTAT", "Eurostat", "European Commission", "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data", "OFFICIAL_API", "TIER_A", "MONTHLY", 1),
    ("SRC_TAVILY", "Tavily Search API", "Tavily Inc.", "https://api.tavily.com", "WEB_SEARCH", "TIER_B", "DAILY", 1),
    ("SRC_MANUAL", "Wprowadzenie Ręczne", "Operator", "https://internal.system", "PROXY", "TIER_A", "IRREGULAR", 1),
    ("SRC_LEGACY_1", "Główny Urząd Statystyczny (GUS)", "GUS", "https://stat.gov.pl", "OFFICIAL_WEB", "TIER_A", "MONTHLY", 1),
    ("SRC_LEGACY_2", "Narodowy Bank Polski (NBP)", "NBP", "https://www.nbp.pl", "OFFICIAL_WEB", "TIER_A", "MONTHLY", 1),
    ("SRC_COMPOSITE_GUS_BANKIER", "Główny Urząd Statystyczny / Bankier.pl", "GUS / Bankier.pl", "https://www.bankier.pl", "OFFICIAL_WEB", "TIER_C", "MONTHLY", 1),
    ("SRC_COMPOSITE_NBP_BANKIER", "Narodowy Bank Polski / Bankier.pl", "NBP / Bankier.pl", "https://www.bankier.pl", "OFFICIAL_WEB", "TIER_C", "MONTHLY", 1),
    ("SRC_EXTERNAL_BANKIER", "Bankier.pl", "Bonnier Business Polska", "https://www.bankier.pl", "WEB_SEARCH", "TIER_C", "DAILY", 1),
    ("SRC_EXTERNAL_TRADING_ECONOMICS", "Trading Economics", "Trading Economics", "https://tradingeconomics.com", "WEB_SEARCH", "TIER_C", "DAILY", 1),
    ("SRC_UNKNOWN_EXTERNAL", "Nieznane źródło", "Nieznana instytucja", "https://example.org", "WEB_SEARCH", "TIER_C", "IRREGULAR", 1),
]

DEFAULT_UNITS = [
    ("PCT", "Procent", "%", "PERCENT", 2),
    ("PLN", "Złoty polski", "zł", "CURRENCY", 2),
    ("PLN_PER_MONTH", "Złotych miesięcznie", "zł/m-c", "CURRENCY", 2),
    ("EUR_PLN", "Złoty za euro", "zł/EUR", "CURRENCY", 4),
    ("USD_PLN", "Złoty za dolara", "zł/USD", "CURRENCY", 4),
    ("MEUR", "Miliony euro", "mln EUR", "CURRENCY", 1),
    ("THOUSAND_PERSONS", "Tysiące osób", "tys. osób", "COUNT", 1),
    ("PERSONS", "Osoby", "osób", "COUNT", 0),
    ("INDEX_POINTS", "Punkty indeksu", "pkt", "INDEX", 2),
    ("RATIO", "Wskaźnik", "ratio", "RATIO", 4),
]

DEFAULT_INDICATOR_CATALOG = [
    # Inflacja
    ("PL_CPI_YOY", "Inflacja CPI r/r", "Roczna dynamika cen towarów i usług konsumpcyjnych w Polsce", "MONTHLY", "PCT", "INFLATION", 1),
    ("PL_CPI_MOM", "Inflacja CPI m/m", "Miesięczna dynamika cen towarów i usług konsumpcyjnych w Polsce", "MONTHLY", "PCT", "INFLATION", 0),
    ("PL_CORE_INFLATION_YOY", "Inflacja bazowa r/r", "Inflacja po wyłączeniu cen żywności i energii w Polsce", "MONTHLY", "PCT", "INFLATION", 0),
    ("PL_HICP_YOY", "Zharmonizowany wskaźnik cen konsumpcyjnych HICP Polska", "Roczna stopa inflacji według ujednoliconej metodologii Eurostatu dla Polski", "MONTHLY", "PCT", "INFLATION", 1),
    ("EU_HICP_YOY", "Zharmonizowany wskaźnik cen konsumpcyjnych HICP UE/Strefa Euro", "Roczna stopa inflacji HICP w Unii Europejskiej", "MONTHLY", "PCT", "INFLATION", 0),

    # Rynek pracy
    ("PL_UNEMPLOYMENT_REGISTERED_RATE", "Stopa bezrobocia rejestrowanego", "Odsetek zarejestrowanych bezrobotnych w urzędach pracy w Polsce", "MONTHLY", "PCT", "LABOUR_MARKET", 1),
    ("PL_UNEMPLOYMENT_REGISTERED_COUNT", "Liczba zarejestrowanych bezrobotnych", "Liczba bezrobotnych zarejestrowanych w urzędach pracy w tys. osób", "MONTHLY", "THOUSAND_PERSONS", "LABOUR_MARKET", 0),
    ("PL_UNEMPLOYMENT_LFS_RATE", "Stopa bezrobocia BAEL Polska", "Zharmonizowana stopa bezrobocia według badania BAEL Eurostatu w Polsce", "MONTHLY", "PCT", "LABOUR_MARKET", 1),
    ("EU_UNEMPLOYMENT_RATE", "Stopa bezrobocia BAEL UE", "Zharmonizowana stopa bezrobocia Eurostatu w Unii Europejskiej", "MONTHLY", "PCT", "LABOUR_MARKET", 0),
    ("PL_WAGE_AVG_ENTERPRISE", "Przeciętne wynagrodzenie w sektorze przedsiębiorstw", "Przeciętne miesięczne wynagrodzenie brutto w sektorze przedsiębiorstw w Polsce", "MONTHLY", "PLN_PER_MONTH", "LABOUR_MARKET", 1),
    ("PL_MINIMUM_WAGE", "Płaca minimalna", "Ustawowe minimalne wynagrodzenie za pracę w Polsce", "ANNUAL", "PLN_PER_MONTH", "LABOUR_MARKET", 0),

    # Wzrost gospodarczy
    ("PL_GDP_QOQ", "Dynamika PKB kw/kw Polska", "Realna dynamika PKB wyrównana sezonowo kwartał do kwartału w Polsce", "QUARTERLY", "PCT", "ECONOMIC_GROWTH", 1),
    ("PL_GDP_YOY", "Dynamika PKB r/r Polska", "Realna dynamika PKB rok do roku w Polsce", "QUARTERLY", "PCT", "ECONOMIC_GROWTH", 1),
    ("EU_GDP_QOQ", "Dynamika PKB kw/kw UE", "Realna dynamika PKB kwartał do kwartału w Unii Europejskiej", "QUARTERLY", "PCT", "ECONOMIC_GROWTH", 0),
    ("EU_GDP_YOY", "Dynamika PKB r/r UE", "Realna dynamika PKB rok do roku w Unii Europejskiej", "QUARTERLY", "PCT", "ECONOMIC_GROWTH", 0),
    ("PL_GDP_VOLUME", "Wolumen PKB Polska (mln EUR)", "Wielkość PKB w cenach stałych z 2010 r. w milionach euro", "QUARTERLY", "MEUR", "ECONOMIC_GROWTH", 0),
    ("PL_GDP_VOLUME_MEUR", "Wolumen PKB Polska (mln EUR)", "Wielkość PKB w cenach stałych z 2010 r. w milionach euro", "QUARTERLY", "MEUR", "ECONOMIC_GROWTH", 0),
    ("EU_GDP_VOLUME", "Wolumen PKB UE (mln EUR)", "Wielkość PKB Unii Europejskiej w milionach euro", "QUARTERLY", "MEUR", "ECONOMIC_GROWTH", 0),
    ("EU_GDP_VOLUME_MEUR", "Wolumen PKB UE (mln EUR)", "Wielkość PKB Unii Europejskiej w milionach euro", "QUARTERLY", "MEUR", "ECONOMIC_GROWTH", 0),

    # Polityka pieniężna i stopy procentowe
    ("PL_POLICY_RATE_REF", "Stopa referencyjna NBP", "Główna stopa procentowa Narodowego Banku Polskiego", "DAILY", "PCT", "MONETARY_POLICY", 1),
    ("PL_NBP_REFERENCE_RATE", "Stopa referencyjna NBP (alias)", "Główna stopa procentowa Narodowego Banku Polskiego", "DAILY", "PCT", "MONETARY_POLICY", 0),
    ("PL_INTEREST_RATE_REFERENCE", "Stopa referencyjna NBP (standard)", "Główna stopa procentowa Narodowego Banku Polskiego", "DAILY", "PCT", "MONETARY_POLICY", 0),
    ("PL_INTEREST_RATE_LOMBARD", "Stopa lombardowa NBP", "Stopa lombardowa Narodowego Banku Polskiego", "DAILY", "PCT", "MONETARY_POLICY", 0),
    ("PL_INTEREST_RATE_DEPOSIT", "Stopa depozytowa NBP", "Stopa depozytowa Narodowego Banku Polskiego", "DAILY", "PCT", "MONETARY_POLICY", 0),
    ("PL_WIBOR_3M", "Stawka WIBOR 3M", "Warsaw Interbank Offered Rate 3M", "DAILY", "PCT", "MONETARY_POLICY", 0),
    ("PL_WIBOR_6M", "Stawka WIBOR 6M", "Warsaw Interbank Offered Rate 6M", "DAILY", "PCT", "MONETARY_POLICY", 0),

    # Kursy walut
    ("PL_FX_EUR_PLN", "Kurs średni EUR/PLN", "Średni kurs walutowy euro w złotych według tabeli A NBP", "DAILY", "EUR_PLN", "MONETARY_POLICY", 1),
    ("PL_FX_USD_PLN", "Kurs średni USD/PLN", "Średni kurs walutowy dolara amerykańskiego w złotych według tabeli A NBP", "DAILY", "USD_PLN", "MONETARY_POLICY", 1),
]


class SQLiteV2Storage:
    """
    Produkcyjny moduł dostępu do bazy SQLite v2 dla Polish Economy Agent.
    Gwarantuje audytowalność, append-only, wersjonowanie i brak nadpisywania bazy legacy.
    """

    def __init__(self, db_path: Optional[str] = None):
        target = db_path or getattr(config, "DB_V2_PATH", os.path.join("instance", "economy_agent_v2.db"))
        abs_target = os.path.abspath(target)
        legacy_path = os.path.abspath(os.path.join("instance", "economy_agent.db"))

        if abs_target == legacy_path:
            raise ValueError(
                "KRYTYCZNE NARUSZENIE BEZPIECZEŃSTWA: Próba zapisu bazy v2 do chronionej bazy legacy: instance/economy_agent.db"
            )

        self.db_path = abs_target
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    def get_connection(self) -> sqlite3.Connection:
        """Zwraca otwarte połączenie z SQLite v2 z włączonymi kluczami obcymi."""
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _init_db(self):
        """Inicjalizuje schemat DDL v2 i podstawowe katalogi danych."""
        schema_file = os.path.join(os.path.dirname(__file__), "..", "docs", "sql", "schema_v2.sql")
        schema_file = os.path.abspath(schema_file)

        if not os.path.exists(schema_file):
            raise FileNotFoundError(f"Nie odnaleziono pliku schematu DDL: {schema_file}")

        with open(schema_file, "r", encoding="utf-8") as f:
            ddl_script = f.read()

        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("PRAGMA foreign_keys = ON;")
            conn.executescript(ddl_script)

            # Rejestracja domyślnych jednostek
            conn.executemany("""
                INSERT OR IGNORE INTO unit_catalog (unit_code, name_pl, symbol, unit_type, decimal_places)
                VALUES (?, ?, ?, ?, ?);
            """, DEFAULT_UNITS)

            # Rejestracja domyślnych źródeł
            conn.executemany("""
                INSERT OR IGNORE INTO source_registry (
                    source_id, name, institution, base_url, source_type, trust_tier, update_frequency, is_active
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """, DEFAULT_SOURCES)

            # Rejestracja katalogu wskaźników
            conn.executemany("""
                INSERT OR IGNORE INTO indicator_catalog (
                    indicator_code, name_pl, definition_pl, frequency, unit_code, target_macro_area, is_headline
                ) VALUES (?, ?, ?, ?, ?, ?, ?);
            """, DEFAULT_INDICATOR_CATALOG)

            # Kontrola kolumny publication_status (bezpieczna, niedestrukcyjna ewolucja schematu)
            table_info = conn.execute("PRAGMA table_info(reports)").fetchall()
            col_names = [col[1] for col in table_info]
            if "publication_status" not in col_names:
                conn.execute("ALTER TABLE reports ADD COLUMN publication_status TEXT DEFAULT 'PUBLISHED';")
            # Bezpieczna procedura odzyskiwania przy starcie: raporty niedokonczone (PENDING) -> FAILED
            conn.execute("UPDATE reports SET publication_status = 'FAILED' WHERE publication_status = 'PENDING';")
            conn.commit()
        finally:
            conn.close()

    def count_table(self, table_name: str) -> int:
        """Zwraca liczbę wierszy w podanej tabeli."""
        allowed_tables = {
            "source_registry", "unit_catalog", "indicator_catalog", "indicator_aliases",
            "data_series", "ingestion_runs", "source_evidence", "extracted_candidates",
            "observations", "current_observations", "quality_events", "reports",
            "legacy_migration_map"
        }
        if table_name not in allowed_tables:
            raise ValueError(f"Nieprawidłowa nazwa tabeli: {table_name}")

        conn = self.get_connection()
        try:
            row = conn.execute(f"SELECT count(*) FROM {table_name}").fetchone()
            return row[0] if row else 0
        finally:
            conn.close()

    # -------------------------------------------------------------------------
    # Ingestion Runs
    # -------------------------------------------------------------------------
    def start_ingestion_run(self, provider: str, run_type: str = "TRIGGERED") -> str:
        """Rozpoczyna nowy przebieg pobierania i rejestruje go w ingestion_runs."""
        run_id = f"RUN_{uuid.uuid4().hex[:12]}"
        conn = self.get_connection()
        try:
            conn.execute("""
                INSERT INTO ingestion_runs (run_id, provider, run_type, started_at_utc, status)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP, 'RUNNING');
            """, (run_id, provider, run_type))
            conn.commit()
            return run_id
        finally:
            conn.close()

    def finish_ingestion_run(
        self,
        run_id: str,
        status: str,
        records_fetched: int = 0,
        records_validated: int = 0,
        error_message: Optional[str] = None,
    ):
        """Kończy przebieg pobierania i aktualizuje metadane w ingestion_runs."""
        conn = self.get_connection()
        try:
            conn.execute("""
                UPDATE ingestion_runs
                SET completed_at_utc = CURRENT_TIMESTAMP,
                    status = ?,
                    records_fetched = ?,
                    records_validated = ?,
                    error_message = ?
                WHERE run_id = ?;
            """, (status, records_fetched, records_validated, error_message, run_id))
            conn.commit()
        finally:
            conn.close()

    # -------------------------------------------------------------------------
    # Quality Events
    # -------------------------------------------------------------------------
    def record_quality_event(
        self,
        entity_type: str,
        entity_id: str,
        rule_code: str,
        severity: str,
        message: str,
        conflict_with_id: Optional[str] = None,
        context_json: Optional[str] = None,
    ) -> str:
        """Rejestruje zdarzenie jakościowe, konflikt lub ostrzeżenie w quality_events."""
        event_id = f"QE_{uuid.uuid4().hex[:12]}"
        conn = self.get_connection()
        try:
            conn.execute("""
                INSERT INTO quality_events (
                    event_id, entity_type, entity_id, rule_code, severity,
                    message, conflict_with_id, context_json, created_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP);
            """, (
                event_id, entity_type, entity_id, rule_code, severity,
                message, conflict_with_id, context_json
            ))
            conn.commit()
            return event_id
        finally:
            conn.close()

    # -------------------------------------------------------------------------
    # Evidence
    # -------------------------------------------------------------------------
    def save_evidence(self, evidence: RawEvidence, run_id: Optional[str] = None) -> str:
        """Zapisuje dowód źródłowy w warstwie surowej source_evidence."""
        r_id = run_id
        if not r_id:
            r_id = self.start_ingestion_run(provider="MANUAL", run_type="TRIGGERED")

        # Walidacja dozwolonego typu dokumentu
        allowed_docs = {'API_RESPONSE', 'HTML_PAGE', 'PDF_BULLETIN', 'LEGACY_IMPORT', 'SEARCH_SNIPPET'}
        doc_type = evidence.document_type if evidence.document_type in allowed_docs else "API_RESPONSE"

        retrieved_at = evidence.retrieved_at_utc or datetime.now(timezone.utc).isoformat()

        conn = self.get_connection()
        try:
            # Upewnienie się, że źródło istnieje w rejestrze (ochrona klucza obcego)
            conn.execute("""
                INSERT OR IGNORE INTO source_registry (
                    source_id, name, institution, base_url, source_type, trust_tier, update_frequency, is_active
                ) VALUES (?, ?, ?, ?, 'OFFICIAL_API', 'TIER_A', 'MONTHLY', 1);
            """, (
                evidence.source_id,
                evidence.source_id,
                evidence.source_id,
                evidence.source_url or "https://stat.gov.pl"
            ))

            conn.execute("""
                INSERT INTO source_evidence (
                    evidence_id, run_id, source_id, source_url, document_type,
                    content_hash, raw_payload_text, retrieved_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(evidence_id) DO NOTHING;
            """, (
                evidence.evidence_id,
                r_id,
                evidence.source_id,
                evidence.source_url,
                doc_type,
                evidence.content_hash,
                evidence.payload_text,
                retrieved_at,
            ))
            conn.commit()
            return evidence.evidence_id
        finally:
            conn.close()

    # -------------------------------------------------------------------------
    # Observations (Strict Append-Only with Versioning)
    # -------------------------------------------------------------------------
    def save_observation(self, obs: MacroObservation, run_id: Optional[str] = None) -> str:
        """
        Zapisuje obserwację w tabeli observations (strictly append-only).
        Automatycznie ustala version_number i supersedes_id dla tego samego okresu.
        """
        conn = self.get_connection()
        try:
            # Upewnienie się, że jednostka istnieje w katalogu
            conn.execute("""
                INSERT OR IGNORE INTO unit_catalog (unit_code, name_pl, symbol, unit_type, decimal_places)
                VALUES (?, ?, ?, 'RATIO', 2);
            """, (obs.unit_code, obs.unit_code, obs.unit_code))

            # Upewnienie się, że wskaźnik istnieje w katalogu
            conn.execute("""
                INSERT OR IGNORE INTO indicator_catalog (
                    indicator_code, name_pl, definition_pl, frequency, unit_code, target_macro_area, is_headline
                ) VALUES (?, ?, ?, ?, ?, 'GENERAL', 0);
            """, (
                obs.indicator_code,
                obs.indicator_code,
                f"Wskaźnik {obs.indicator_code}",
                obs.frequency or "MONTHLY",
                obs.unit_code or "PCT"
            ))

            # Sprawdzenie czy istnieje już wersja dla danego okresu
            row = conn.execute("""
                SELECT observation_id, version_number
                FROM observations
                WHERE indicator_code = ? AND country_code = ? AND period_start = ?
                ORDER BY version_number DESC
                LIMIT 1;
            """, (obs.indicator_code, obs.country_code, obs.period_start)).fetchone()

            if row:
                supersedes_id = row[0]
                version_number = row[1] + 1
                revision_type = obs.revision_type if obs.revision_type and obs.revision_type != "FINAL" else "REVISED"
            else:
                supersedes_id = None
                version_number = 1
                revision_type = obs.revision_type or "FINAL"

            obs_date = obs.observed_at_utc or datetime.now(timezone.utc).isoformat()

            conn.execute("""
                INSERT INTO observations (
                    observation_id, indicator_code, country_code, period_start, period_end,
                    frequency, value_decimal, unit_code, revision_type, version_number,
                    supersedes_id, evidence_id, status, observed_at_utc, validated_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(observation_id) DO NOTHING;
            """, (
                obs.observation_id,
                obs.indicator_code,
                obs.country_code,
                obs.period_start,
                obs.period_end,
                obs.frequency,
                obs.value_decimal,
                obs.unit_code,
                revision_type,
                version_number,
                supersedes_id,
                obs.evidence_id,
                obs.status,
                obs_date,
            ))
            conn.commit()
            return obs.observation_id
        finally:
            conn.close()

    def save_observations(self, obs_list: List[MacroObservation], run_id: Optional[str] = None) -> int:
        """Zapisuje listę obserwacji i zwraca liczbę pomyślnie zapisanych rekordów."""
        count = 0
        for obs in obs_list:
            self.save_observation(obs, run_id=run_id)
            count += 1
        return count

    # -------------------------------------------------------------------------
    # Observation Queries
    # -------------------------------------------------------------------------
    def get_current_observations(self, country_code: str = "PL") -> List[Dict[str, Any]]:
        """Zwraca wszystkie bieżące obserwacje z tabeli current_observations z metadanymi wskaźników."""
        codes = ("PL", "Polska") if country_code in ("PL", "Polska", "Poland") else (country_code, country_code)
        conn = self.get_connection()
        try:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT 
                    co.indicator_code,
                    ic.name_pl,
                    co.country_code,
                    co.period_start,
                    co.period_end,
                    co.frequency,
                    co.value_decimal,
                    co.unit_code,
                    uc.symbol AS unit_symbol,
                    co.revision_type,
                    co.version_number,
                    co.status,
                    co.observation_id,
                    co.observed_at_utc,
                    co.updated_at_utc,
                    o.evidence_id,
                    se.source_id,
                    se.source_url
                FROM current_observations co
                LEFT JOIN indicator_catalog ic ON co.indicator_code = ic.indicator_code
                LEFT JOIN unit_catalog uc ON co.unit_code = uc.unit_code
                LEFT JOIN observations o ON co.observation_id = o.observation_id
                LEFT JOIN source_evidence se ON o.evidence_id = se.evidence_id
                WHERE co.country_code IN (?, ?)
                ORDER BY ic.target_macro_area ASC, co.indicator_code ASC
            """, codes).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_verified_current_observations(self, country_code: str = "PL") -> List[Dict[str, Any]]:
        """Zwraca wyłącznie zweryfikowane obserwacje (status = 'VERIFIED')."""
        all_obs = self.get_current_observations(country_code)
        return [o for o in all_obs if o.get("status") == "VERIFIED"]

    def get_latest_verified_observations(
        self,
        country_code: str = "PL",
        run_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Zwraca po jednym najnowszym zweryfikowanym odczycie na wskaźnik.

        Gdy przekazano ``run_id``, raport nie pobiera obserwacji z wcześniejszych
        przebiegów, w szczególności fixture'ów offline.
        """
        codes = ("PL", "Polska") if country_code in ("PL", "Polska", "Poland") else (country_code, country_code)
        conn = self.get_connection()
        try:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                WITH ranked AS (
                    SELECT
                        o.observation_id,
                        o.indicator_code,
                        ic.name_pl,
                        o.country_code,
                        o.period_start,
                        o.period_end,
                        o.frequency,
                        o.value_decimal,
                        o.unit_code,
                        uc.symbol AS unit_symbol,
                        o.revision_type,
                        o.version_number,
                        o.status,
                        o.evidence_id,
                        o.observed_at_utc,
                        se.source_id,
                        se.source_url,
                        se.run_id,
                        ROW_NUMBER() OVER (
                            PARTITION BY o.indicator_code
                            ORDER BY o.period_end DESC, o.period_start DESC,
                                     o.version_number DESC, o.observed_at_utc DESC
                        ) AS recency_rank
                    FROM observations o
                    LEFT JOIN indicator_catalog ic ON o.indicator_code = ic.indicator_code
                    LEFT JOIN unit_catalog uc ON o.unit_code = uc.unit_code
                    LEFT JOIN source_evidence se ON o.evidence_id = se.evidence_id
                    WHERE o.country_code IN (?, ?)
                      AND o.status = 'VERIFIED'
                      AND (? IS NULL OR se.run_id = ?)
                )
                SELECT *
                FROM ranked
                WHERE recency_rank = 1
                ORDER BY indicator_code ASC
            """, (codes[0], codes[1], run_id, run_id)).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_unverified_observations(
        self,
        country_code: str = "PL",
        run_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Zwraca obserwacje oczekujące na weryfikację, sporne lub niepotwierdzone."""
        codes = ("PL", "Polska") if country_code in ("PL", "Polska", "Poland") else (country_code, country_code)
        conn = self.get_connection()
        try:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT 
                    o.observation_id,
                    o.indicator_code,
                    ic.name_pl,
                    o.country_code,
                    o.period_start,
                    o.period_end,
                    o.frequency,
                    o.value_decimal,
                    o.unit_code,
                    o.status,
                    o.evidence_id,
                    o.observed_at_utc
                FROM observations o
                LEFT JOIN indicator_catalog ic ON o.indicator_code = ic.indicator_code
                LEFT JOIN source_evidence se ON o.evidence_id = se.evidence_id
                WHERE o.country_code IN (?, ?)
                  AND o.status IN ('PENDING', 'CONFLICT', 'NOT_VERIFIED', 'REJECTED')
                  AND (? IS NULL OR se.run_id = ?)
                ORDER BY o.observed_at_utc DESC
            """, (codes[0], codes[1], run_id, run_id)).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_observation_history(self, indicator_code: str, country_code: str = "PL") -> List[Dict[str, Any]]:
        """Zwraca pełną historię rewizji i odczytów danego wskaźnika."""
        codes = ("PL", "Polska") if country_code in ("PL", "Polska", "Poland") else (country_code, country_code)
        conn = self.get_connection()
        try:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT 
                    o.observation_id,
                    o.indicator_code,
                    o.period_start,
                    o.period_end,
                    o.frequency,
                    o.value_decimal,
                    o.unit_code,
                    o.revision_type,
                    o.version_number,
                    o.supersedes_id,
                    o.status,
                    o.evidence_id,
                    o.observed_at_utc
                FROM observations o
                WHERE o.indicator_code = ? AND o.country_code IN (?, ?)
                ORDER BY o.period_start ASC, o.version_number ASC
            """, (indicator_code, codes[0], codes[1])).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # -------------------------------------------------------------------------
    # Reports
    # -------------------------------------------------------------------------
    def save_report(
        self,
        report_id: str,
        country_code: str,
        report_date: str,
        executive_horizon: str,
        report_markdown: str,
        report_html: Optional[str] = None,
        data_snapshot_hash: Optional[str] = None,
        model_metadata: Optional[Dict[str, Any]] = None,
        as_of_utc: Optional[str] = None,
        publication_status: str = "PENDING",
    ) -> str:
        """Zapisuje raport w tabeli reports wraz z hashem migawki danych i statusem publikacji."""
        if not data_snapshot_hash:
            data_snapshot_hash = hashlib.sha256(report_markdown.encode("utf-8")).hexdigest()

        as_of = as_of_utc or datetime.now(timezone.utc).isoformat()
        meta_json = json.dumps(model_metadata, ensure_ascii=False) if model_metadata else None
        code = "PL" if country_code in ("PL", "Polska", "Poland") else country_code

        conn = self.get_connection()
        try:
            conn.execute("""
                INSERT INTO reports (
                    report_id, country_code, report_date, as_of_utc, executive_horizon,
                    report_markdown, report_html, data_snapshot_hash, model_metadata_json,
                    publication_status, created_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(report_id) DO UPDATE SET
                    report_markdown = excluded.report_markdown,
                    report_html = excluded.report_html,
                    executive_horizon = excluded.executive_horizon,
                    data_snapshot_hash = excluded.data_snapshot_hash,
                    model_metadata_json = excluded.model_metadata_json,
                    publication_status = excluded.publication_status;
            """, (
                report_id,
                code,
                report_date,
                as_of,
                executive_horizon,
                report_markdown,
                report_html,
                data_snapshot_hash,
                meta_json,
                publication_status,
            ))
            conn.commit()
            return report_id
        finally:
            conn.close()

    def mark_report_published(self, report_id: str) -> bool:
        """Oznacza raport jako pomyslnie opublikowany (PUBLISHED)."""
        conn = self.get_connection()
        try:
            cursor = conn.execute("UPDATE reports SET publication_status = 'PUBLISHED' WHERE report_id = ?", (report_id,))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def mark_report_failed(self, report_id: str) -> bool:
        """Oznacza raport jako nieudany (FAILED) w przypadku awarii publikacji."""
        conn = self.get_connection()
        try:
            cursor = conn.execute("UPDATE reports SET publication_status = 'FAILED' WHERE report_id = ?", (report_id,))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def recover_pending_reports(self) -> int:
        """Bezpieczna procedura odzyskiwania: wycofuje niedokonczone publikacje (PENDING -> FAILED)."""
        conn = self.get_connection()
        try:
            cursor = conn.execute("UPDATE reports SET publication_status = 'FAILED' WHERE publication_status = 'PENDING'")
            conn.commit()
            return cursor.rowcount
        finally:
            conn.close()

    def get_latest_report(self, country_code: str = "PL") -> Optional[Dict[str, Any]]:
        """Zwraca najnowszy wygenerowany raport z tabeli reports."""
        codes = ("PL", "Polska") if country_code in ("PL", "Polska", "Poland") else (country_code, country_code)
        conn = self.get_connection()
        try:
            conn.row_factory = sqlite3.Row
            row = conn.execute("""
                SELECT 
                    report_id,
                    country_code,
                    report_date,
                    as_of_utc,
                    executive_horizon,
                    report_markdown,
                    report_html,
                    data_snapshot_hash,
                    model_metadata_json,
                    publication_status,
                    created_at_utc
                FROM reports
                WHERE country_code IN (?, ?)
                  AND (publication_status = 'PUBLISHED' OR publication_status IS NULL)
                ORDER BY created_at_utc DESC
                LIMIT 1
            """, codes).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def delete_report(self, report_id: str) -> bool:
        """Usuwa raport o podanym ID w przypadku niepowodzenia publikacji lub procedury odzyskiwania."""
        conn = self.get_connection()
        try:
            cursor = conn.execute("DELETE FROM reports WHERE report_id = ?", (report_id,))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()
