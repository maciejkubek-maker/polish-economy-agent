"""
Bazowa klasa i modele danych dla oficjalnych konektorów API makroekonomicznych.
Plik: modules/connectors/base.py

Wymagania:
- Pobieranie danych z oficjalnego źródła.
- Timeout, retry i deterministyczna obsługa błędów.
- Zapisywanie źródła, daty publikacji i daty pobrania w UTC.
- Deterministyczny hash SHA-256 odpowiedzi (RAW evidence).
- Ścisła walidacja jednostki, okresu i definicji ekonomicznej.
- Obsługa braku danych bez wymyślania/halucynowania wartości (DataNotFoundError).
- Obsługa trybu offline (mock fixtures dla testów bez internetu).
- Rygor świeżości danych (StaleDataError).
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import time
from typing import Any, Callable, Dict, List, Optional
import urllib.error
import urllib.request
import uuid


class ConnectorException(Exception):
    """Bazowy wyjątek dla błędów konektorów API."""
    pass


class DataNotFoundError(ConnectorException):
    """Rzucany, gdy API zwraca pustą serię lub brak danych dla zadanego okresu (brak zgadywania)."""
    pass


class VariableNotMappedError(ConnectorException):
    """Rzucany, gdy identyfikator zmiennej nie został potwierdzony w oficjalnym API (zakaz fikcyjnych ID)."""
    pass


class ValidationError(ConnectorException):
    """Rzucany, gdy dane z API naruszają reguły dziedzinowe lub ograniczenia schematu."""
    pass


class StaleDataError(ValidationError):
    """Rzucany, gdy seria danych jest przeterminowana (np. archiwalna seria z 2025 r. prezentowana jako aktualna w 2026 r.)."""
    pass


@dataclass
class RawEvidence:
    """Surowy dowód źródłowy pobrany z API (warstwa RAW / source_evidence)."""
    evidence_id: str
    source_id: str
    source_url: str
    document_type: str
    content_hash: str
    payload_text: str
    status_code: int
    retrieved_at_utc: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "source_id": self.source_id,
            "source_url": self.source_url,
            "document_type": self.document_type,
            "content_hash": self.content_hash,
            "payload_text": self.payload_text,
            "status_code": self.status_code,
            "retrieved_at_utc": self.retrieved_at_utc,
        }


@dataclass
class MacroObservation:
    """Zweryfikowana obserwacja makroekonomiczna z oficjalnego źródła (warstwa VALIDATED / observations)."""
    indicator_code: str
    country_code: str
    period_start: str
    period_end: str
    frequency: str
    value_decimal: str
    unit_code: str
    revision_type: str
    status: str
    evidence_id: str
    publication_date: Optional[str] = None
    observation_id: str = field(default_factory=lambda: f"OBS_API_{uuid.uuid4().hex[:12]}")
    observed_at_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "observation_id": self.observation_id,
            "indicator_code": self.indicator_code,
            "country_code": self.country_code,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "frequency": self.frequency,
            "value_decimal": self.value_decimal,
            "unit_code": self.unit_code,
            "revision_type": self.revision_type,
            "status": self.status,
            "evidence_id": self.evidence_id,
            "publication_date": self.publication_date,
            "observed_at_utc": self.observed_at_utc,
            "metadata": self.metadata,
        }


class BaseConnector:
    """Bazowy konektor realizujący komunikację HTTP, retry, timeout, hashowanie i walidację."""

    ALLOWED_FREQUENCIES = {"DAILY", "MONTHLY", "QUARTERLY", "ANNUAL", "IRREGULAR"}
    ALLOWED_UNITS = {
        "PCT", "EUR_PLN", "USD_PLN", "PLN_PER_MONTH", "PLN",
        "THOUSAND_PERSONS", "PERSONS", "INDEX_POINTS", "RATIO", "MEUR"
    }

    def __init__(
        self,
        timeout: float = 10.0,
        max_retries: int = 3,
        retry_delay: float = 0.5,
        offline_mode: bool = False,
    ):
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.offline_mode = offline_mode
        self._fixtures: Dict[str, tuple[int, str]] = {}

    def register_fixture(self, url_keyword: str, payload_text: str, status_code: int = 200) -> None:
        """Rejestruje zapisaną odpowiedź API dla testów offline."""
        self._fixtures[url_keyword] = (status_code, payload_text)

    def _execute_request(self, url: str, headers: Optional[Dict[str, str]] = None) -> tuple[int, str, str, str]:
        """
        Pobiera treść z podanego adresu URL z obsługą retry i timeoutu.
        Zwraca: (status_code, payload_text, content_hash, retrieved_at_utc).
        """
        # Obsługa trybu offline (zapisane fixture'y dla 100% odtwarzalności bez internetu)
        for pattern, (code, text) in self._fixtures.items():
            if pattern in url:
                content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
                now_utc = datetime.now(timezone.utc).isoformat()
                return code, text, content_hash, now_utc

        if self.offline_mode:
            raise ConnectorException(f"Tryb offline aktywny, brak zarejestrowanego fixture dla URL: {url}")

        req_headers = {
            "User-Agent": "PolishEconomyAgent/2.0 (Official Data Ingestion)",
            "Accept": "application/json, application/xml, text/xml, */*",
        }
        if headers:
            req_headers.update(headers)

        req = urllib.request.Request(url, headers=req_headers)

        last_error = None
        for attempt in range(1, self.max_retries + 1):
            try:
                retrieved_at_utc = datetime.now(timezone.utc).isoformat()
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    status_code = resp.status
                    raw_bytes = resp.read()
                    # Próba dekodowania utf-8 z fallbackiem do iso-8859-2 dla starszych źródeł
                    try:
                        payload_text = raw_bytes.decode("utf-8")
                    except UnicodeDecodeError:
                        payload_text = raw_bytes.decode("iso-8859-2", errors="replace")

                    content_hash = hashlib.sha256(payload_text.encode("utf-8")).hexdigest()
                    return status_code, payload_text, content_hash, retrieved_at_utc

            except urllib.error.HTTPError as http_err:
                last_error = http_err
                # 404 lub 400 nie wymagają ponawiania
                if http_err.code in (400, 404):
                    raise DataNotFoundError(f"Brak danych pod adresem {url} (HTTP {http_err.code})") from http_err
                # Błędy serwera (5xx) lub 429 mogą być ponawiane
                if attempt < self.max_retries and http_err.code in (429, 500, 502, 503, 504):
                    time.sleep(self.retry_delay * attempt)
                    continue
                raise ConnectorException(f"Błąd HTTP {http_err.code} dla {url}: {http_err.reason}") from http_err

            except (urllib.error.URLError, TimeoutError) as net_err:
                last_error = net_err
                if attempt < self.max_retries:
                    time.sleep(self.retry_delay * attempt)
                    continue
                raise ConnectorException(f"Błąd sieciowy/timeout dla {url} po {self.max_retries} próbach: {str(net_err)}") from net_err

        raise ConnectorException(f"Nie udało się pobrać danych z {url}: {str(last_error)}")

    def create_evidence(
        self,
        source_id: str,
        source_url: str,
        document_type: str,
        payload_text: str,
        content_hash: str,
        status_code: int,
        retrieved_at_utc: str,
    ) -> RawEvidence:
        """Tworzy obiekt RawEvidence z unikalnym identyfikatorem."""
        evidence_id = f"EVI_{uuid.uuid4().hex[:12]}"
        return RawEvidence(
            evidence_id=evidence_id,
            source_id=source_id,
            source_url=source_url,
            document_type=document_type,
            content_hash=content_hash,
            payload_text=payload_text,
            status_code=status_code,
            retrieved_at_utc=retrieved_at_utc,
        )

    def validate_value(
        self,
        raw_val: Any,
        min_plausible: Optional[Decimal] = None,
        max_plausible: Optional[Decimal] = None,
    ) -> str:
        """Konwertuje surową wartość na kanoniczny string Decimal z walidacją zakresu."""
        if raw_val is None:
            raise ValidationError("Wartość wskaźnika nie może być pusta (None)")

        # Czyszczenie formatu tekstowego (zamiana przecinka na kropkę, usunięcie spacji/procentów)
        val_str = str(raw_val).strip().replace(" ", "").replace("%", "").replace(",", ".")
        try:
            val_dec = Decimal(val_str)
        except InvalidOperation as e:
            raise ValidationError(f"Nieprawidłowy format liczbowy: '{raw_val}'") from e

        if min_plausible is not None and val_dec < min_plausible:
            raise ValidationError(f"Wartość {val_dec} jest poniżej dopuszczalnego minimum {min_plausible}")
        if max_plausible is not None and val_dec > max_plausible:
            raise ValidationError(f"Wartość {val_dec} przekracza dopuszczalne maksimum {max_plausible}")

        return str(val_dec)

    def validate_frequency(self, frequency: str) -> str:
        """Waliduje częstotliwość publikacji wskaźnika."""
        freq_upper = frequency.upper().strip()
        if freq_upper not in self.ALLOWED_FREQUENCIES:
            raise ValidationError(f"Nieznana częstotliwość: '{frequency}'. Dopuszczalne: {self.ALLOWED_FREQUENCIES}")
        return freq_upper

    def validate_unit(self, unit_code: str) -> str:
        """Waliduje kod jednostki wskaźnika."""
        unit_upper = unit_code.upper().strip()
        if unit_upper not in self.ALLOWED_UNITS:
            raise ValidationError(f"Nieznana jednostka: '{unit_code}'. Dopuszczalne: {self.ALLOWED_UNITS}")
        return unit_upper

    def validate_iso_date(self, date_str: str) -> str:
        """Waliduje datę w formacie ISO YYYY-MM-DD."""
        if not date_str:
            raise ValidationError("Data nie może być pusta")
        try:
            dt = datetime.strptime(date_str.strip(), "%Y-%m-%d")
            return dt.strftime("%Y-%m-%d")
        except ValueError as e:
            raise ValidationError(f"Nieprawidłowy format daty ISO (oczekiwano YYYY-MM-DD): '{date_str}'") from e
