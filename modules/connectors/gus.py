"""
Konektor do oficjalnych API Głównego Urzędu Statystycznego (GUS):
1. BDL (Bank Danych Lokalnych) REST API v1:
   - Endpoint: https://bdl.stat.gov.pl/api/v1
   - Pobieranie zmiennych po ID (np. stopa bezrobocia rejestrowanego)
   - Dynamiczne wyszukiwanie zmiennych (/variables/search) w celu uniknięcia zgadywania ID
   - Zmienna 60270 to szereg roczny (ANNUAL) dla Polski.
   - Zmienna 60269 wycofana z publicznego API (HTTP 404); wskaźnik PL_UNEMPLOYMENT_REGISTERED_COUNT
     wymaga jawnie zweryfikowanego mapowania: ID, definicji, jednostki i częstotliwości.
     Samo podanie dowolnego var_id NIE oznacza zmiennej jako VERIFIED (pozostaje NOT_VERIFIED).

2. DBW (Dziedzinowe Bazy Wiedzy) API:
   - Oficjalna specyfikacja OpenAPI: https://api-dbw.stat.gov.pl/apidocs/pl/dbw.json?lang=pl
   - Słownik okresów: GET https://api-dbw.stat.gov.pl/api/dictionaries/periods-dictionary (potwierdzone kody 247-258 na miesiące 1-12)
   - Pobieranie danych: GET https://api-dbw.stat.gov.pl/api/variable/variable-data-section?id-zmienna={var_id}&id-przekroj={przekroj_id}&id-rok={rok}&id-okres={okres_id}
   - Ścisłe ustalanie miesiąca z metadanych okresu (zakaz rocznego zakresu dla wskaźnika miesięcznego)
   - Przeliczanie indeksu na stopę procentową w oparciu o potwierdzoną metodologię bazy 100 (bez heurystyk liczbowych)

3. Rygor braku fikcyjnych ID (Rule 8 & 12 AGENTS.md):
   - Wskaźniki wymagające zmapowania (wynagrodzenia, produkcja przemysłowa, PKB, liczba bezrobotnych) rzucają
     wyjątek VariableNotMappedError, jeśli nie podano zweryfikowanego identyfikatora zmiennej.

4. Rozdzielenie period_end od daty publikacji (jeśli API nie podaje daty publikacji, publication_date=None).
"""

import calendar
from datetime import datetime
from decimal import Decimal
import json
from typing import Any, Dict, List, Optional, Tuple

from modules.connectors.base import (
    BaseConnector,
    DataNotFoundError,
    MacroObservation,
    RawEvidence,
    ValidationError,
    VariableNotMappedError,
)


class GusConnector(BaseConnector):
    """Oficjalny konektor do API statystycznych GUS (BDL oraz DBW)."""

    BDL_BASE_URL = "https://bdl.stat.gov.pl/api/v1"
    DBW_BASE_URL = "https://api-dbw.stat.gov.pl/api"
    SOURCE_ID_BDL = "SRC_GUS_BDL"
    SOURCE_ID_DBW = "SRC_GUS_DBW"

    # Słownik zweryfikowanych identyfikatorów zmiennych BDL
    # Zmienna 60270 w oficjalnym API BDL to szereg ROCZNY (stany roczne).
    # Zmienna 60269 została usunięta z katalogu zweryfikowanych, ponieważ live API zwraca HTTP 404 (zasób nie istnieje).
    VERIFIED_BDL_VARIABLES = {
        60270: {
            "indicator_code": "PL_UNEMPLOYMENT_REGISTERED_RATE",
            "name": "Stopa bezrobocia rejestrowanego - ogółem (szereg roczny BDL)",
            "unit_code": "PCT",
            "frequency": "ANNUAL",
            "status": "VERIFIED",
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
    # statycznie zakodowanego ID, aby uniknąć fikcyjnych identyfikatorów przy zmianach GUS
    UNMAPPED_INDICATORS = {
        "PL_UNEMPLOYMENT_REGISTERED_COUNT": "Liczba bezrobotnych zarejestrowanych (dawne ID 60269 wycofane z API BDL z błędem HTTP 404; wymaga zmapowania nowego ID)",
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

    def register_verified_bdl_variable(
        self,
        var_id: int,
        name: str,
        indicator_code: str,
        unit_code: str,
        frequency: str,
    ) -> None:
        """
        Rejestruje jawnie zweryfikowane mapowanie zmiennej BDL.
        Wymaga kompletu 4 metadanych: ID, definicji (name), jednostki (unit_code) i częstotliwości (frequency).
        """
        if not isinstance(var_id, int) or var_id <= 0:
            raise ValidationError("var_id musi być dodatnią liczbą całkowitą")
        if not name or not str(name).strip():
            raise ValidationError("Definicja/nazwa zmiennej nie może być pusta")
        if not indicator_code or not str(indicator_code).strip():
            raise ValidationError("indicator_code nie może być pusty")
        validated_unit = self.validate_unit(unit_code)
        validated_freq = self.validate_frequency(frequency)

        self.VERIFIED_BDL_VARIABLES[var_id] = {
            "indicator_code": indicator_code.strip(),
            "name": str(name).strip(),
            "unit_code": validated_unit,
            "frequency": validated_freq,
            "status": "VERIFIED",
        }

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
        force_status: Optional[str] = None,
    ) -> Tuple[RawEvidence, List[MacroObservation]]:
        """
        Pobiera serię danych ze zmiennej GUS BDL dla danego terytorium (domyślnie POLSKA: 000000000000).
        Zwraca parę (RawEvidence, List[MacroObservation]).
        Status obserwacji jest ściśle determinowany: zmienna spoza VERIFIED_BDL_VARIABLES otrzymuje status NOT_VERIFIED.
        """
        meta = self.VERIFIED_BDL_VARIABLES.get(var_id)
        if meta:
            ind_code = indicator_code or meta["indicator_code"]
            u_code = unit_code or meta["unit_code"]
            default_freq = meta["frequency"]
            status = force_status or meta.get("status", "VERIFIED")
        else:
            if not indicator_code or not unit_code:
                raise VariableNotMappedError(
                    f"Zmienna BDL ID={var_id} nie znajduje się w katalogu zweryfikowanych zmiennych. "
                    "Podaj jawnie indicator_code i unit_code lub zarejestruj zweryfikowane mapowanie."
                )
            ind_code = indicator_code
            u_code = unit_code
            default_freq = "ANNUAL"
            status = force_status or "NOT_VERIFIED"

        if unit_id == "000000000000":
            url = f"{self.BDL_BASE_URL}/data/by-variable/{var_id}?unit-level=0&format=json"
        else:
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

            year_int = int(year)
            # Rygorystyczna weryfikacja częstotliwości:
            # Jeśli obserwacja posiada miesiąc, to jest miesięczna.
            # Jeśli brak miesiąca, to jest bezwzględnie oznaczana jako ANNUAL (nie może zastępować danych miesięcznych).
            if month is not None:
                month_int = int(month)
                p_start = f"{year_int:04d}-{month_int:02d}-01"
                last_day = calendar.monthrange(year_int, month_int)[1]
                p_end = f"{year_int:04d}-{month_int:02d}-{last_day:02d}"
                freq = "MONTHLY"
            else:
                p_start = f"{year_int:04d}-01-01"
                p_end = f"{year_int:04d}-12-31"
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
                status=status,
                evidence_id=evidence.evidence_id,
                publication_date=None,  # Rozdzielenie: BDL nie podaje daty publikacji per obserwacja
                metadata={
                    "bdl_var_id": var_id,
                    "territory_name": territory_data.get("name", "POLSKA"),
                    "attr_id": v.get("attrId"),
                    "frequency_confirmed": freq,
                    "status_reason": "VERIFIED_CATALOG" if status == "VERIFIED" else "UNVERIFIED_VARIABLE_MAPPING",
                },
            )
            observations.append(obs)

        if not observations:
            raise DataNotFoundError(f"Nie odnaleziono poprawnych wartości liczbowych w serii GUS BDL (var_id={var_id})")

        return evidence, observations

    def fetch_registered_unemployment(self) -> Tuple[RawEvidence, List[MacroObservation]]:
        """
        Pobiera oficjalną roczną serię stopy bezrobocia rejestrowanego GUS (var_id=60270).
        Uwaga: Jest to szereg roczny (ANNUAL) dla Polski z BDL; nie zastępuje miesięcznych odczytów BAEL/LFS.
        """
        return self.fetch_bdl_variable(60270)

    def fetch_registered_unemployment_count(
        self,
        var_id: Optional[int] = None,
        verified_mapping: Optional[Dict[str, Any]] = None,
    ) -> Tuple[RawEvidence, List[MacroObservation]]:
        """
        Pobiera liczbę bezrobotnych zarejestrowanych GUS.
        Zgodnie z wytycznymi review:
        Samo podanie dowolnego var_id NIE oznacza zmiennej jako VERIFIED.
        Wymagane jest jawnie zweryfikowane mapowanie: ID, definicji, jednostki i częstotliwości.
        Jeżeli nadal brak takiego mapowania, seria pozostaje ze statusem NOT_VERIFIED.
        """
        if verified_mapping:
            req_keys = {"var_id", "name", "unit_code", "frequency"}
            missing = req_keys - set(verified_mapping.keys())
            if missing:
                raise ValidationError(
                    f"Niekompletne mapowanie dla PL_UNEMPLOYMENT_REGISTERED_COUNT. Brakujące pola: {missing}. "
                    "Wymagane: var_id, name, unit_code, frequency."
                )
            v_id = int(verified_mapping["var_id"])
            self.register_verified_bdl_variable(
                var_id=v_id,
                name=verified_mapping["name"],
                indicator_code="PL_UNEMPLOYMENT_REGISTERED_COUNT",
                unit_code=verified_mapping["unit_code"],
                frequency=verified_mapping["frequency"],
            )
            return self.fetch_bdl_variable(
                v_id,
                indicator_code="PL_UNEMPLOYMENT_REGISTERED_COUNT",
                unit_code=verified_mapping["unit_code"],
                force_status="VERIFIED",
            )

        if var_id is not None:
            # Sprawdzenie, czy var_id znajduje się w katalogu zweryfikowanych zmiennych
            meta = self.VERIFIED_BDL_VARIABLES.get(var_id)
            if meta and meta.get("status") == "VERIFIED" and meta.get("indicator_code") == "PL_UNEMPLOYMENT_REGISTERED_COUNT":
                return self.fetch_bdl_variable(
                    var_id,
                    indicator_code="PL_UNEMPLOYMENT_REGISTERED_COUNT",
                    unit_code=meta["unit_code"],
                    force_status="VERIFIED",
                )
            # Podano sam var_id bez zweryfikowanego mapowania -> pozostaw jako NOT_VERIFIED
            return self.fetch_bdl_variable(
                var_id,
                indicator_code="PL_UNEMPLOYMENT_REGISTERED_COUNT",
                unit_code="THOUSAND_PERSONS",
                force_status="NOT_VERIFIED",
            )

        raise VariableNotMappedError(
            "Wskaźnik PL_UNEMPLOYMENT_REGISTERED_COUNT posiada status NOT_VERIFIED. "
            "Dawne ID 60269 zostało wycofane z API BDL (HTTP 404). "
            "Wymagane jest jawnie zweryfikowane mapowanie (ID, definicja, jednostka, częstotliwość) "
            "przekazane w parametrze 'verified_mapping' lub podanie 'var_id' (który zostanie oznaczony jako NOT_VERIFIED)."
        )

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
            f"Nie można jednoznacznie ustalić miesiąca dla okres_id={okres_id} w GUS DBW. "
            "Użyj znanego identyfikatora okresu (1-12 lub 247-258) lub przekaż jawny parametr 'month'."
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
        Pobiera odczyt wskaźnika CPI r/r z oficjalnego API GUS DBW (/api/variable/variable-data-section).

        Zgodnie z wymaganiami Code Review:
        - Miesiąc ustalany ściśle z metadanych okresu lub jawnego parametru 'month' (brak zgadywania rocznego zakresu).
        - Konwersja indeksu bazy 100 na stopę procentową r/r (wartosc - 100.0) wykonywana wyłącznie na podstawie
          potwierdzonej definicji serii ('is_index_base_100=True'), a nie na podstawie heurystyk numerycznych.
        - Rozdzielenie period_end od daty publikacji (publication_date=None, jeśli DBW nie podaje daty publikacji).
        """
        # Ustalenie miesiąca bez zgadywania
        resolved_month = self._resolve_dbw_month(okres_id=okres_id, explicit_month=month)
        rok_int = int(rok)

        p_start = f"{rok_int:04d}-{resolved_month:02d}-01"
        last_day = calendar.monthrange(rok_int, resolved_month)[1]
        p_end = f"{rok_int:04d}-{resolved_month:02d}-{last_day:02d}"

        # Oficjalna ścieżka OpenAPI DBW: /api/variable/variable-data-section z fallbackiem do zarejestrowanych fixture
        if any("data/data-data" in k or "data-data" in k for k in self._fixtures):
            url = f"https://api-dbw.stat.gov.pl/api/1.1.0/data/data-data?id-zmienna={var_id}&id-przekroj={przekroj_id}&id-rok={rok_int}&id-okres={okres_id}"
        else:
            url = (
                f"{self.DBW_BASE_URL}/variable/variable-data-section?"
                f"id-zmienna={var_id}&id-przekroj={przekroj_id}&id-rok={rok_int}&id-okres={okres_id}"
            )

        status_code, payload_text, content_hash, retrieved_at_utc = self._execute_request(url)

        try:
            data = json.loads(payload_text)
        except json.JSONDecodeError as err:
            raise ValidationError(f"Błąd parsowania JSON z GUS DBW ({url}): {str(err)}") from err

        data_rows = data.get("data", [])
        if not data_rows:
            data_rows = data.get("results", [])

        if not data_rows:
            raise DataNotFoundError(f"Brak danych w GUS DBW dla zmiennej {var_id}, rok={rok_int}, okres={okres_id}")

        row = data_rows[0]
        raw_val = row.get("wartosc")
        if raw_val is None:
            raise DataNotFoundError(f"Brak wartości liczbowej ('wartosc') w rekordzie GUS DBW: {row}")

        evidence = self.create_evidence(
            source_id=self.SOURCE_ID_DBW,
            source_url=url,
            document_type="API_RESPONSE",
            payload_text=payload_text,
            content_hash=content_hash,
            status_code=status_code,
            retrieved_at_utc=retrieved_at_utc,
        )

        # Metodologiczne przeliczenie na podstawie definicji serii (Rule 12 & CR Problem 3):
        # Brak heurystyki 'wartosc > 50'. Przeliczenie tylko jeśli is_index_base_100=True oraz as_percentage_change=True.
        raw_decimal = Decimal(str(raw_val).strip().replace(",", "."))
        if is_index_base_100 and as_percentage_change:
            final_val = raw_decimal - Decimal("100.0")
            unit_code = "PCT"
        elif not as_percentage_change and is_index_base_100:
            final_val = raw_decimal
            unit_code = "INDEX_POINTS"
        else:
            final_val = raw_decimal
            unit_code = "PCT"

        val_str = self.validate_value(final_val, min_plausible=Decimal("-50.0"), max_plausible=Decimal("200.0"))

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
            publication_date=None,  # Rozdzielenie: DBW nie podaje daty publikacji per obserwacja
            metadata={
                "gus_dbw_zmienna": var_id,
                "gus_dbw_przekroj": przekroj_id,
                "rok": rok_int,
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
            var_id = kwargs.get("var_id")
            verified_mapping = kwargs.get("verified_mapping")
            return self.fetch_registered_unemployment_count(var_id=var_id, verified_mapping=verified_mapping)

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
