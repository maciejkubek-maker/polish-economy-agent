"""
Konektor do oficjalnych API Głównego Urzędu Statystycznego (GUS BDL i DBW).
Plik: modules/connectors/gus.py

Obsługuje:
1. GUS BDL (Bank Danych Lokalnych REST API v1):
   - Wyszukiwanie zmiennych: GET https://bdl.stat.gov.pl/api/v1/variables/search?name={query}&format=json
   - Pobieranie danych dla zmiennej: GET https://bdl.stat.gov.pl/api/v1/data/by-variable/{var_id}?unit-parent-id=000000000000&format=json
   - Potwierdzony wskaźnik: Stopa bezrobocia rejestrowanego (var_id=60270) -> PL_UNEMPLOYMENT_REGISTERED_RATE
   - Potwierdzony wskaźnik: Liczba bezrobotnych zarejestrowanych (var_id=60269) -> PL_UNEMPLOYMENT_REGISTERED_COUNT

2. GUS DBW (Dziedzinowe Bazy Wiedzy REST API v1.1.0):
   - Pobieranie danych: GET https://api-dbw.stat.gov.pl/api/1.1.0/data/data-data?id-zmienna={var_id}&id-przekroj={przekroj_id}&id-rok={rok}&id-okres={okres_id}
   - Potwierdzony wskaźnik: CPI r/r (zmienna=305, przekroj=736) -> PL_CPI_YOY

3. Rygor braku fikcyjnych ID (Rule 8 & 12 AGENTS.md):
   - Wskaźniki wymagające zmapowania (wynagrodzenia, produkcja przemysłowa, PKB) rzucają
     wyjątek VariableNotMappedError, jeśli nie podano zweryfikowanego identyfikatora zmiennej.
"""

from decimal import Decimal
import json
from typing import Any, Dict, List, Optional, Tuple

from modules.connectors.base import (
    BaseConnector,
    ConnectorException,
    DataNotFoundError,
    MacroObservation,
    RawEvidence,
    ValidationError,
    VariableNotMappedError,
)


class GusConnector(BaseConnector):
    """Oficjalny konektor do API statystycznych GUS (BDL oraz DBW)."""

    BDL_BASE_URL = "https://bdl.stat.gov.pl/api/v1"
    DBW_BASE_URL = "https://api-dbw.stat.gov.pl/api/1.1.0"
    SOURCE_ID_BDL = "SRC_GUS_BDL"
    SOURCE_ID_DBW = "SRC_GUS_DBW"

    # Słownik zweryfikowanych identyfikatorów zmiennych (potwierdzone w dokumentacji i testach)
    VERIFIED_BDL_VARIABLES = {
        60270: {
            "indicator_code": "PL_UNEMPLOYMENT_REGISTERED_RATE",
            "name": "Stopa bezrobocia rejestrowanego - ogółem",
            "unit_code": "PCT",
            "frequency": "MONTHLY",
        },
        60269: {
            "indicator_code": "PL_UNEMPLOYMENT_REGISTERED_COUNT",
            "name": "Bezrobotni zarejestrowani - ogółem",
            "unit_code": "THOUSAND_PERSONS",
            "frequency": "MONTHLY",
        },
    }

    # Wskaźniki ze statusem CONFIRMED_API_REQUIRES_VARIABLE_MAPPING, które nie posiadają
    # statycznie zakodowanego ID, aby uniknąć fikcyjnych identyfikatorów przy corocznych zmianach GUS
    UNMAPPED_INDICATORS = {
        "PL_WAGE_AVERAGE_GROSS": "Przeciętne miesięczne wynagrodzenie w sektorze przedsiębiorstw",
        "PL_INDUSTRIAL_PRODUCTION_YOY": "Dynamika produkcji sprzedanej przemysłu (r/r)",
        "PL_RETAIL_SALES_YOY": "Dynamika sprzedaży detalicznej w cenach stałych (r/r)",
        "PL_GDP_YOY": "Produkt Krajowy Brutto (ceny stałe, r/r)",
    }

    def __init__(
        self,
        api_key: Optional[str] = None,
        timeout: float = 10.0,
        max_retries: int = 3,
        retry_delay: float = 0.5,
        offline_mode: bool = False,
    ):
        super().__init__(timeout=timeout, max_retries=max_retries, retry_delay=retry_delay, offline_mode=offline_mode)
        self.api_key = api_key

    def _get_bdl_headers(self) -> Dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["X-ClientId"] = self.api_key
        return headers

    def search_bdl_variables(self, query: str) -> List[Dict[str, Any]]:
        """
        Wyszukuje zmienne w słowniku metadanych BDL wg nazwy (np. 'bezrobocie', 'wynagrodzenie').
        Pozwala na bezpieczne, dynamiczne odkrywanie zmiennych bez wprowadzania fikcyjnych ID.
        """
        if not query or not query.strip():
            raise ValidationError("Zapytanie wyszukiwania zmiennej GUS BDL nie może być puste")

        url = f"{self.BDL_BASE_URL}/variables/search?name={urllib_quote(query.strip())}&format=json"
        status_code, payload_text, content_hash, retrieved_at_utc = self._execute_request(
            url, headers=self._get_bdl_headers()
        )

        try:
            data = json.loads(payload_text)
        except json.JSONDecodeError as err:
            raise ValidationError(f"Błąd parsowania odpowiedzi JSON z GUS BDL search ({url}): {str(err)}") from err

        results = data.get("results", [])
        return results

    def fetch_bdl_variable(
        self,
        var_id: int,
        unit_id: str = "000000000000",
        indicator_code: Optional[str] = None,
        unit_code: Optional[str] = None,
    ) -> Tuple[RawEvidence, List[MacroObservation]]:
        """
        Pobiera serię danych dla zweryfikowanej zmiennej z GUS BDL dla danego terytorium (domyślnie POLSKA: 000000000000).
        Zwraca parę (RawEvidence, List[MacroObservation]).
        """
        # Sprawdzenie w rejestrze zweryfikowanych zmiennych
        meta = self.VERIFIED_BDL_VARIABLES.get(var_id)
        if meta:
            ind_code = indicator_code or meta["indicator_code"]
            u_code = unit_code or meta["unit_code"]
            frequency = meta["frequency"]
        else:
            if not indicator_code or not unit_code:
                raise VariableNotMappedError(
                    f"Zmienna BDL ID={var_id} nie znajduje się w katalogu zweryfikowanych zmiennych. "
                    "Podaj jawnie indicator_code i unit_code lub wyszukaj oficjalne metadane za pomocą search_bdl_variables()."
                )
            ind_code = indicator_code
            u_code = unit_code
            frequency = "ANNUAL"

        url = f"{self.BDL_BASE_URL}/data/by-variable/{var_id}?unit-parent-id={unit_id}&format=json"
        status_code, payload_text, content_hash, retrieved_at_utc = self._execute_request(
            url, headers=self._get_bdl_headers()
        )

        try:
            data = json.loads(payload_text)
        except json.JSONDecodeError as err:
            raise ValidationError(f"Błąd parsowania JSON z GUS BDL data ({url}): {str(err)}") from err

        results = data.get("results", [])
        if not results:
            raise DataNotFoundError(f"Brak wyników w GUS BDL dla zmiennej {var_id} i terytorium {unit_id}")

        territory_data = results[0]
        values = territory_data.get("values", [])
        if not values:
            raise DataNotFoundError(f"Pusta seria wartości w GUS BDL dla zmiennej {var_id}")

        evidence = self.create_evidence(
            source_id=self.SOURCE_ID_BDL,
            source_url=url,
            document_type="API_RESPONSE",
            payload_text=payload_text,
            content_hash=content_hash,
            status_code=status_code,
            retrieved_at_utc=retrieved_at_utc,
        )

        observations = []
        for v in values:
            raw_val = v.get("val")
            year = v.get("year")
            month = v.get("month")

            if raw_val is None or year is None:
                continue

            if month is not None:
                p_start = f"{year:04d}-{int(month):02d}-01"
                import calendar
                last_day = calendar.monthrange(int(year), int(month))[1]
                p_end = f"{year:04d}-{int(month):02d}-{last_day:02d}"
                freq = "MONTHLY"
            else:
                p_start = f"{year:04d}-01-01"
                p_end = f"{year:04d}-12-31"
                freq = "ANNUAL"

            val_str = self.validate_value(raw_val)

            obs = MacroObservation(
                indicator_code=ind_code,
                country_code="PL",
                period_start=p_start,
                period_end=p_end,
                frequency=self.validate_frequency(freq),
                value_decimal=val_str,
                unit_code=self.validate_unit(u_code),
                revision_type="FINAL",
                status="VERIFIED",
                evidence_id=evidence.evidence_id,
                publication_date=p_end,
                metadata={
                    "bdl_var_id": var_id,
                    "territory_name": territory_data.get("name", "POLSKA"),
                    "attr_id": v.get("attrId"),
                },
            )
            observations.append(obs)

        if not observations:
            raise DataNotFoundError(f"Nie odnaleziono poprawnych wartości liczbowych w serii GUS BDL (var_id={var_id})")

        return evidence, observations

    def fetch_registered_unemployment(self) -> Tuple[RawEvidence, List[MacroObservation]]:
        """
        Pobiera oficjalną serię stopy bezrobocia rejestrowanego GUS (var_id=60270).
        """
        return self.fetch_bdl_variable(60270)

    def fetch_registered_unemployment_count(self) -> Tuple[RawEvidence, List[MacroObservation]]:
        """
        Pobiera oficjalną liczbę bezrobotnych zarejestrowanych GUS (var_id=60269).
        """
        return self.fetch_bdl_variable(60269)

    def fetch_cpi_dbw(
        self,
        rok: int,
        okres_id: int,
        var_id: int = 305,
        przekroj_id: int = 736,
    ) -> Tuple[RawEvidence, MacroObservation]:
        """
        Pobiera wskaźnik CPI (r/r) z bazy GUS DBW dla wskazanego roku i okresu.
        Domyślnie zmienna 305, przekrój 736 (Analogiczny okres roku poprzedniego = 100).
        Zwraca parę (RawEvidence, MacroObservation).
        """
        url = f"{self.DBW_BASE_URL}/data/data-data?id-zmienna={var_id}&id-przekroj={przekroj_id}&id-rok={rok}&id-okres={okres_id}"
        status_code, payload_text, content_hash, retrieved_at_utc = self._execute_request(url)

        try:
            data = json.loads(payload_text)
        except json.JSONDecodeError as err:
            raise ValidationError(f"Błąd parsowania JSON z GUS DBW ({url}): {str(err)}") from err

        items = data.get("data", [])
        if not items:
            # W niektórych strukturach DBW węzeł nazywa się 'results'
            items = data.get("results", [])

        if not items or len(items) == 0:
            raise DataNotFoundError(f"Brak danych CPI w GUS DBW dla roku {rok} i okresu {okres_id}")

        item = items[0]
        raw_val = item.get("wartosc")
        if raw_val is None:
            raise ValidationError(f"Brak wartości 'wartosc' w odpowiedzi GUS DBW: {item}")

        # Jeśli wartość indeksu podana jest w bazie 100 (np. 104.2 oznacza inflację 4.2% r/r)
        val_dec = Decimal(str(raw_val).replace(",", "."))
        if val_dec > Decimal("50.0"):
            # Indeks bazy 100 -> stopa procentowa r/r
            pct_val = val_dec - Decimal("100.0")
        else:
            pct_val = val_dec

        val_str = self.validate_value(pct_val, min_plausible=Decimal("-10.0"), max_plausible=Decimal("100.0"))

        evidence = self.create_evidence(
            source_id=self.SOURCE_ID_DBW,
            source_url=url,
            document_type="API_RESPONSE",
            payload_text=payload_text,
            content_hash=content_hash,
            status_code=status_code,
            retrieved_at_utc=retrieved_at_utc,
        )

        # Ustalenie przybliżonego okresu na podstawie roku i okres_id (miesiące w DBW)
        p_start = f"{rok:04d}-01-01"
        p_end = f"{rok:04d}-12-31"

        observation = MacroObservation(
            indicator_code="PL_CPI_YOY",
            country_code="PL",
            period_start=p_start,
            period_end=p_end,
            frequency="MONTHLY",
            value_decimal=val_str,
            unit_code="PCT",
            revision_type="FINAL",
            status="VERIFIED",
            evidence_id=evidence.evidence_id,
            publication_date=f"{rok:04d}-12-31",
            metadata={
                "gus_dbw_zmienna": var_id,
                "gus_dbw_przekroj": przekroj_id,
                "rok": rok,
                "okres_id": okres_id,
                "raw_index_value": str(raw_val),
            },
        )

        return evidence, observation

    def fetch_indicator(self, indicator_code: str, **kwargs) -> Tuple[RawEvidence, Any]:
        """
        Uniwersalny punkt wejścia pobierania wskaźników z GUS z rygorystyczną kontrolą statusu mapowania.
        """
        code = indicator_code.upper().strip()

        if code == "PL_UNEMPLOYMENT_REGISTERED_RATE":
            return self.fetch_registered_unemployment()

        if code == "PL_UNEMPLOYMENT_REGISTERED_COUNT":
            return self.fetch_registered_unemployment_count()

        if code == "PL_CPI_YOY":
            rok = kwargs.get("rok")
            okres_id = kwargs.get("okres_id")
            if not rok or not okres_id:
                raise ValidationError("Dla PL_CPI_YOY w GUS DBW wymagane są parametry 'rok' oraz 'okres_id'")
            return self.fetch_cpi_dbw(rok=rok, okres_id=okres_id)

        if code in self.UNMAPPED_INDICATORS:
            # Sprawdzenie, czy użytkownik dostarczył potwierdzone ID zmiennej
            var_id = kwargs.get("var_id")
            if var_id:
                return self.fetch_bdl_variable(var_id=int(var_id), indicator_code=code, unit_code=kwargs.get("unit_code", "PCT"))
            raise VariableNotMappedError(
                f"Wskaźnik '{code}' ({self.UNMAPPED_INDICATORS[code]}) w GUS posiada status CONFIRMED_API_REQUIRES_VARIABLE_MAPPING. "
                "Aby uniknąć fikcyjnych identyfikatorów, użyj metody search_bdl_variables() w celu zmapowania aktualnego ID lub przekaż parametr 'var_id'."
            )

        raise ValidationError(f"Nieznany lub nieobsługiwany kod wskaźnika GUS: '{indicator_code}'")


def urllib_quote(s: str) -> str:
    import urllib.parse
    return urllib.parse.quote(s)
