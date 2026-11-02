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
   - Potwierdzony wskaźnik: CPI r/r (zmienna=305, przekroj=736 "Analogiczny okres roku poprzedniego = 100") -> PL_CPI_YOY
   - Ścisłe ustalanie miesiąca z metadanych okresu (brak zgadywania rocznego zakresu)
   - Przeliczanie indeksu na stopę procentową w oparciu o potwierdzoną metodologię bazy 100 (bez heurystyk liczbowych)

3. Rygor braku fikcyjnych ID (Rule 8 & 12 AGENTS.md):
   - Wskaźniki wymagające zmapowania (wynagrodzenia, produkcja przemysłowa, PKB) rzucają
     wyjątek VariableNotMappedError, jeśli nie podano zweryfikowanego identyfikatora zmiennej.
"""

import calendar
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

    # Zweryfikowane mapowanie identyfikatorów okresów DBW na miesiące (1-12)
    # W oficjalnym słowniku okresów DBW dla szeregów miesięcznych stosowane są kody 1-12 lub 247-258
    DBW_PERIOD_TO_MONTH = {
        # Standardowy format 1..12
        1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 6,
        7: 7, 8: 8, 9: 9, 10: 10, 11: 11, 12: 12,
        # Standardowy słownik miesięczny GUS DBW (kody 247=styczeń ... 258=grudzień)
        247: 1, 248: 2, 249: 3, 250: 4, 251: 5, 252: 6,
        253: 7, 254: 8, 255: 9, 256: 10, 257: 11, 258: 12,
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

    def _resolve_dbw_month(self, okres_id: int, explicit_month: Optional[int] = None) -> int:
        """
        Ustala miesiąc (1-12) na podstawie potwierdzonych metadanych okresu GUS DBW.
        Gdy nie da się go ustalić, zgłasza błąd zamiast zgadywać.
        """
        if explicit_month is not None:
            if 1 <= explicit_month <= 12:
                return explicit_month
            raise ValidationError(f"Nieprawidłowy numer miesiąca: {explicit_month}. Oczekiwano wartości 1-12.")

        if okres_id in self.DBW_PERIOD_TO_MONTH:
            return self.DBW_PERIOD_TO_MONTH[okres_id]

        raise ValidationError(
            f"Nie można jednoznacznie ustalić miesiąca z GUS DBW okres_id={okres_id}. "
            "Podaj jawny parametr 'month' (1-12) lub zarejestruj zweryfikowane metadane okresu. Zakaz zgadywania."
        )

    def fetch_cpi_dbw(
        self,
        rok: int,
        okres_id: int,
        month: Optional[int] = None,
        var_id: int = 305,
        przekroj_id: int = 736,
        is_index_base_100: bool = True,
        as_percentage_change: bool = True,
    ) -> Tuple[RawEvidence, MacroObservation]:
        """
        Pobiera wskaźnik CPI (r/r) z bazy GUS DBW dla wskazanego roku i okresu.
        Domyślnie zmienna 305, przekrój 736: 'Analogiczny okres roku poprzedniego = 100'.
        
        Zgodność metodologiczna:
        - Miesiąc ustalany ściśle z metadanych okresu lub jawnego parametru 'month' (brak zgadywania rocznego zakresu).
        - Konwersja indeksu bazy 100 na stopę procentową r/r (wartosc - 100.0) wykonywana wyłącznie na podstawie
          potwierdzonej definicji serii ('is_index_base_100=True'), a nie na podstawie heurystyk numerycznych.
        """
        # Ustalenie miesiąca bez zgadywania
        resolved_month = self._resolve_dbw_month(okres_id=okres_id, explicit_month=month)
        p_start = f"{rok:04d}-{resolved_month:02d}-01"
        last_day = calendar.monthrange(rok, resolved_month)[1]
        p_end = f"{rok:04d}-{resolved_month:02d}-{last_day:02d}"

        url = f"{self.DBW_BASE_URL}/data/data-data?id-zmienna={var_id}&id-przekroj={przekroj_id}&id-rok={rok}&id-okres={okres_id}"
        status_code, payload_text, content_hash, retrieved_at_utc = self._execute_request(url)

        try:
            data = json.loads(payload_text)
        except json.JSONDecodeError as err:
            raise ValidationError(f"Błąd parsowania JSON z GUS DBW ({url}): {str(err)}") from err

        items = data.get("data", [])
        if not items:
            items = data.get("results", [])

        if not items or len(items) == 0:
            raise DataNotFoundError(f"Brak danych CPI w GUS DBW dla roku {rok} i okresu {okres_id}")

        item = items[0]
        raw_val = item.get("wartosc")
        if raw_val is None:
            raise ValidationError(f"Brak wartości 'wartosc' w odpowiedzi GUS DBW: {item}")

        raw_val_str = str(raw_val).strip().replace(" ", "").replace(",", ".")
        try:
            val_raw_dec = Decimal(raw_val_str)
        except Exception as e:
            raise ValidationError(f"Nieprawidłowy format liczbowy z DBW: '{raw_val}'") from e

        # Konwersja metodologiczna: jeśli seria jest indeksem bazy 100 ("Analogiczny okres roku poprzedniego = 100")
        # i żądana jest roczna zmiana procentowa, odejmujemy 100.0 zgodnie z definicją GUS.
        if as_percentage_change:
            if is_index_base_100:
                final_val_dec = val_raw_dec - Decimal("100.0")
                unit_code = "PCT"
            else:
                final_val_dec = val_raw_dec
                unit_code = "PCT"
        else:
            final_val_dec = val_raw_dec
            unit_code = "INDEX_POINTS"

        val_str = self.validate_value(final_val_dec, min_plausible=Decimal("-50.0"), max_plausible=Decimal("150.0"))

        evidence = self.create_evidence(
            source_id=self.SOURCE_ID_DBW,
            source_url=url,
            document_type="API_RESPONSE",
            payload_text=payload_text,
            content_hash=content_hash,
            status_code=status_code,
            retrieved_at_utc=retrieved_at_utc,
        )

        observation = MacroObservation(
            indicator_code="PL_CPI_YOY",
            country_code="PL",
            period_start=p_start,
            period_end=p_end,
            frequency="MONTHLY",
            value_decimal=val_str,
            unit_code=self.validate_unit(unit_code),
            revision_type="FINAL",
            status="VERIFIED",
            evidence_id=evidence.evidence_id,
            publication_date=p_end,
            metadata={
                "gus_dbw_zmienna": var_id,
                "gus_dbw_przekroj": przekroj_id,
                "rok": rok,
                "okres_id": okres_id,
                "resolved_month": resolved_month,
                "raw_value": str(raw_val),
                "is_index_base_100": is_index_base_100,
                "as_percentage_change": as_percentage_change,
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
            month = kwargs.get("month")
            if not rok or okres_id is None:
                raise ValidationError("Dla PL_CPI_YOY w GUS DBW wymagane są parametry 'rok' oraz 'okres_id'")
            return self.fetch_cpi_dbw(rok=rok, okres_id=okres_id, month=month)

        if code in self.UNMAPPED_INDICATORS:
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
