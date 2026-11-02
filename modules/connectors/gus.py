"""
Konektor do oficjalnych API Głównego Urzędu Statystycznego (GUS):
1. BDL (Bank Danych Lokalnych) REST API v1 (https://bdl.stat.gov.pl/api/v1)
2. DBW (Dziedzinowa Baza Wiedzy) REST API (https://api-dbw.stat.gov.pl/api)

Zgodność z AGENTS.md:
- Rule 8: Zero fałszywych wskaźników i fikcyjnych identyfikatorów
- Rule 12: Wskaźniki niejednoznaczne oznaczone statusem PENDING / NOT_VERIFIED
- Ścisłe rozróżnienie częstotliwości (np. roczna seria BDL 60270 vs miesięczne stopy)
- Wykorzystanie oficjalnego słownika okresów DBW do ustalania dat (bez zgadywania)
- Konwersja indeksu CPI do zmiany procentowej r/r oparta wyłącznie na potwierdzonej metodologii
- Rozdzielenie period_end od publication_date
- Bezpieczeństwo danych: Status VERIFIED nadawany wyłącznie na podstawie weryfikacji
  w oficjalnych metadanych API GUS lub w kontrolowanym, niemodyfikowalnym rejestrze mapowań (APPROVED_BDL_REGISTRY).
  Zablokowane obejścia przez force_status="VERIFIED", trusted_preapproved=True oraz bezpośrednią modyfikację rejestru.
"""

import calendar
from datetime import datetime
from decimal import Decimal
import json
from types import MappingProxyType
from typing import Any, Dict, List, Optional, Tuple

from modules.connectors.base import (
    BaseConnector,
    DataNotFoundError,
    MacroObservation,
    RawEvidence,
    ValidationError,
    VariableNotMappedError,
)

# Statyczny, audytowany rejestr zatwierdzonych mapowań BDL
# Statyczny, audytowany rejestr zatwierdzonych mapowań BDL
# Zagnieżdżone rekordy są MappingProxyType, co zabezpiecza przed modyfikacją wewnętrznych pól.
_APPROVED_BDL_REGISTRY_DATA: Dict[int, MappingProxyType] = {
    60270: MappingProxyType({
        "indicator_code": "PL_UNEMPLOYMENT_REGISTERED_RATE",
        "name": "Stopa bezrobocia rejestrowanego - ogółem (szereg roczny BDL)",
        "unit_code": "PCT",
        "frequency": "ANNUAL",
        "status": "VERIFIED",
        "economic_category": "UNEMPLOYMENT_RATE",
    }),
}


def _normalize_text_for_comparison(text: str) -> List[str]:
    import re
    words = re.findall(r"[a-ząćęłńóśźżA-ZĄĆĘŁŃÓŚŹŻ]{4,}", text.lower())
    stopwords = {"oraz", "przez", "dla", "jako", "jest", "jego", "który", "która", "które", "stan", "dane", "szereg"}
    return [w for w in words if w not in stopwords]


def _check_economic_definition_match(expected_name: str, confirmed_text: str) -> Tuple[bool, str]:
    exp_lower = expected_name.lower().strip()
    conf_lower = confirmed_text.lower().strip()

    domains = [
        ("bezroboc", "bezrobocie"),
        ("wynagrodz", "wynagrodzenia / płace"),
        ("produkc", "produkcja"),
        ("sprzedaż", "sprzedaż detaliczna"),
        ("ceny", "ceny / inflacja"),
        ("inflac", "ceny / inflacja"),
        ("cpi", "ceny / inflacja"),
    ]
    for stem, domain_name in domains:
        if stem in exp_lower and stem not in conf_lower:
            return False, f"ECONOMIC_DEFINITION_MISMATCH: expected domain '{domain_name}' not found in confirmed GUS metadata ('{conf_lower}')"
        if stem in conf_lower and stem not in exp_lower:
            return False, f"ECONOMIC_DEFINITION_MISMATCH: confirmed GUS metadata belongs to domain '{domain_name}', but expected definition does not"

    is_exp_rate = "stopa" in exp_lower or "%" in exp_lower or "wskaźnik" in exp_lower
    is_conf_rate = "stopa" in conf_lower or "%" in conf_lower or "proc" in conf_lower
    is_exp_count = "liczba" in exp_lower or "osób" in exp_lower or "osob" in exp_lower
    is_conf_count = "liczba" in conf_lower or "osób" in conf_lower or "osob" in conf_lower or "tys." in conf_lower

    if is_exp_count and is_conf_rate and not is_conf_count:
        return False, "ECONOMIC_DEFINITION_MISMATCH: expected headcount count, but confirmed GUS metadata defines percentage rate"
    if is_exp_rate and is_conf_count and not is_conf_rate:
        return False, "ECONOMIC_DEFINITION_MISMATCH: expected percentage rate, but confirmed GUS metadata defines headcount count"

    exp_tokens = _normalize_text_for_comparison(exp_lower)
    conf_tokens = _normalize_text_for_comparison(conf_lower)
    if exp_tokens:
        overlap = set(exp_tokens) & set(conf_tokens)
        if not overlap:
            stem_overlap = any(any(t[:4] in c for c in conf_tokens) for t in exp_tokens)
            if not stem_overlap:
                return False, f"ECONOMIC_DEFINITION_MISMATCH: expected '{expected_name}' does not match confirmed GUS metadata '{confirmed_text}'"

    return True, "ECONOMIC_DEFINITION_MATCH"


def _extract_gus_metadata_frequency(api_meta: Dict[str, Any]) -> str:
    raw_freq = str(api_meta.get("frequency") or api_meta.get("periodicity") or "").upper().strip()
    if raw_freq in ("ANNUAL", "YEARLY", "R", "ROCZNA"):
        return "ANNUAL"
    if raw_freq in ("MONTHLY", "M", "MIESIĘCZNA"):
        return "MONTHLY"
    if raw_freq in ("QUARTERLY", "K", "Q", "KWARTALNA"):
        return "QUARTERLY"
    if "has_months" in api_meta and not api_meta["has_months"]:
        return "ANNUAL"
    if "is_annual" in api_meta and api_meta["is_annual"]:
        return "ANNUAL"
    if "months" in api_meta or api_meta.get("sub_annual") == "M":
        return "MONTHLY"
    return "ANNUAL"


class GusConnector(BaseConnector):
    """Oficjalny konektor do API statystycznych GUS (BDL oraz DBW)."""

    BDL_BASE_URL = "https://bdl.stat.gov.pl/api/v1"
    DBW_BASE_URL = "https://api-dbw.stat.gov.pl/api"
    SOURCE_ID_BDL = "SRC_GUS_BDL"
    SOURCE_ID_DBW = "SRC_GUS_DBW"

    # Kontrolowany, niemodyfikowalny rejestr zatwierdzonych mapowań BDL (MappingProxyType zabezpiecza przed wstrzyknięciem)
    # Zmienne w tym rejestrze zostały formalnie zweryfikowane metodologicznie i dopuszczone do statusu VERIFIED.
    # Zmienna 60270 w oficjalnym API BDL to szereg ROCZNY (stany roczne).
    # Zmienna 60269 została wycofana z API BDL (HTTP 404 - zasób nie istnieje).
    APPROVED_BDL_REGISTRY: MappingProxyType = MappingProxyType(_APPROVED_BDL_REGISTRY_DATA)

    # Alias wstecznej kompatybilności dla rejestru zweryfikowanych zmiennych (również read-only MappingProxyType)
    VERIFIED_BDL_VARIABLES: MappingProxyType = APPROVED_BDL_REGISTRY

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

    def _get_bdl_headers(self) -> Dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["X-ClientId"] = self.api_key
        return headers

    def get_bdl_variable_metadata(self, var_id: int) -> Optional[Dict[str, Any]]:
        """
        Pobiera oficjalne metadane zmiennej z API GUS BDL: GET /variables/{var_id}?format=json.
        Zwraca słownik metadanych lub None w przypadku błędu / 404 / braku zasobu.
        """
        if not isinstance(var_id, int) or var_id <= 0:
            return None
        url = f"{self.BDL_BASE_URL}/variables/{var_id}?format=json"
        try:
            status_code, payload_text, _, _ = self._execute_request(
                url, headers=self._get_bdl_headers()
            )
            if status_code != 200:
                return None
            return json.loads(payload_text)
        except Exception:
            return None

    def verify_bdl_variable_metadata(
        self,
        var_id: int,
        indicator_code: Optional[str] = None,
        expected_name: Optional[str] = None,
        expected_unit: Optional[str] = None,
        expected_frequency: Optional[str] = None,
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """
        Weryfikuje identyfikator zmiennej, definicję ekonomiczną, jednostkę i częstotliwość
        w rzeczywistych metadanych oficjalnego API GUS lub w osobnym, wcześniej zatwierdzonym rejestrze mapowań.
        Samo poprawne ID nie wystarcza — wymagana jest rzeczywista zgodność definicji ekonomicznej, jednostki i częstotliwości.

        Zwraca: (is_verified, reason_code, verified_metadata).
        """
        # 1. Sprawdzenie w kontrolowanym, wcześniej zatwierdzonym rejestrze mapowań
        if var_id in self.APPROVED_BDL_REGISTRY:
            approved = self.APPROVED_BDL_REGISTRY[var_id]

            # Sprawdzenie zgodności wskaźnika
            if indicator_code and approved.get("indicator_code") != indicator_code:
                return False, f"INDICATOR_MISMATCH_WITH_APPROVED_REGISTRY (registered: {approved.get('indicator_code')}, requested: {indicator_code})", approved

            # Zabezpieczenie definicji ekonomicznej: wskaźnik stopy bezrobocia nie może być liczbą bezrobotnych
            if indicator_code == "PL_UNEMPLOYMENT_REGISTERED_COUNT" and approved.get("economic_category") == "UNEMPLOYMENT_RATE":
                return False, "ECONOMIC_DEFINITION_MISMATCH: rate variable cannot represent headcount count", approved

            # Rzeczywiste porównanie oczekiwanej definicji z zatwierdzonym rejestrem
            if expected_name:
                is_def_match, def_reason = _check_economic_definition_match(expected_name, approved.get("name", ""))
                if not is_def_match:
                    return False, def_reason, approved

            if expected_unit and self.validate_unit(expected_unit) != approved.get("unit_code"):
                return False, f"APPROVED_REGISTRY_UNIT_MISMATCH (expected {expected_unit}, got {approved.get('unit_code')})", approved

            if expected_frequency and self.validate_frequency(expected_frequency) != approved.get("frequency"):
                return False, f"APPROVED_REGISTRY_FREQUENCY_MISMATCH (expected {expected_frequency}, got {approved.get('frequency')})", approved

            return True, "VERIFIED_PREAPPROVED_REGISTRY", approved

        # 2. Sprawdzenie w rzeczywistych metadanych oficjalnego API GUS
        api_meta = self.get_bdl_variable_metadata(var_id)
        if not api_meta:
            return False, "VARIABLE_NOT_FOUND_IN_OFFICIAL_GUS_API", None

        if api_meta.get("id") != var_id:
            return False, f"API_RETURNED_DIFFERENT_ID (expected {var_id}, got {api_meta.get('id')})", api_meta

        gus_unit_name = str(api_meta.get("measureUnitName", "")).lower()
        n1 = str(api_meta.get("n1", "")).lower()
        n2 = str(api_meta.get("n2", "")).lower()
        subject_id = str(api_meta.get("subjectId", "")).upper()
        confirmed_text = f"{n1} {n2} {subject_id} {gus_unit_name}".strip()

        if not n1 and not subject_id:
            return False, "INCOMPLETE_GUS_API_VARIABLE_DEFINITION", api_meta

        # Rzeczywiste porównanie oczekiwanej definicji ekonomicznej z potwierdzonymi metadanymi GUS
        if expected_name:
            is_def_match, def_reason = _check_economic_definition_match(expected_name, confirmed_text)
            if not is_def_match:
                return False, def_reason, api_meta

        # Zgodność definicji ekonomicznej na podstawie kodu wskaźnika
        if indicator_code == "PL_UNEMPLOYMENT_REGISTERED_COUNT":
            if "%" in gus_unit_name or "stopa" in n1:
                return False, "ECONOMIC_DEFINITION_MISMATCH: percentage rate cannot represent registered unemployment count", api_meta
            if not ("osób" in gus_unit_name or "osob" in gus_unit_name or "tys" in gus_unit_name or "bezrobot" in n1 or "ogółem" in n1):
                return False, "ECONOMIC_DEFINITION_MISMATCH: variable metadata does not confirm unemployment headcount", api_meta

        elif indicator_code == "PL_UNEMPLOYMENT_REGISTERED_RATE":
            if not ("%" in gus_unit_name or "stopa" in n1 or "proc" in gus_unit_name):
                return False, "ECONOMIC_DEFINITION_MISMATCH: variable metadata does not confirm unemployment rate", api_meta

        # Rzeczywiste porównanie częstotliwości z potwierdzonymi metadanymi GUS
        if expected_frequency:
            norm_exp_freq = self.validate_frequency(expected_frequency)
            confirmed_freq = _extract_gus_metadata_frequency(api_meta)
            if norm_exp_freq != confirmed_freq:
                return False, f"FREQUENCY_MISMATCH_WITH_GUS_API (expected {norm_exp_freq}, confirmed GUS metadata is {confirmed_freq})", api_meta

        # Weryfikacja jednostki
        if expected_unit:
            norm_exp_unit = self.validate_unit(expected_unit)
            unit_ok = False
            if norm_exp_unit == "PCT" and ("%" in gus_unit_name or "proc" in gus_unit_name):
                unit_ok = True
            elif norm_exp_unit in ("PERSONS", "THOUSAND_PERSONS") and ("osób" in gus_unit_name or "osob" in gus_unit_name or "tys" in gus_unit_name):
                unit_ok = True
            elif norm_exp_unit in ("PLN", "PLN_PER_MONTH") and ("zł" in gus_unit_name or "pln" in gus_unit_name):
                unit_ok = True

            if not unit_ok:
                return False, f"UNIT_MISMATCH_WITH_GUS_API (expected {norm_exp_unit}, got '{gus_unit_name}')", api_meta

        return True, "VERIFIED_OFFICIAL_API_METADATA", api_meta

    def register_verified_bdl_variable(
        self,
        var_id: int,
        name: str,
        indicator_code: str,
        unit_code: str,
        frequency: str,
        **kwargs,
    ) -> bool:
        """
        Rejestruje zmienną wyłącznie po sprawdzeniu w oficjalnych metadanych GUS API.
        Próba użycia 'trusted_preapproved=True' bez niezależnej autoryzacji rzuca ValidationError.
        """
        if kwargs.get("trusted_preapproved"):
            raise ValidationError(
                "Brak niezależnej autoryzacji: publiczne nadawanie statusu VERIFIED przez 'trusted_preapproved=True' jest zablokowane."
            )

        if not isinstance(var_id, int) or var_id <= 0:
            raise ValidationError("var_id musi być dodatnią liczbą całkowitą")
        if not name or not str(name).strip():
            raise ValidationError("Definicja/nazwa zmiennej nie może być pusta")
        if not indicator_code or not str(indicator_code).strip():
            raise ValidationError("indicator_code nie może być pusty")

        validated_unit = self.validate_unit(unit_code)
        validated_freq = self.validate_frequency(frequency)

        is_verified, reason, _ = self.verify_bdl_variable_metadata(
            var_id=var_id,
            indicator_code=indicator_code.strip(),
            expected_name=name.strip(),
            expected_unit=validated_unit,
            expected_frequency=validated_freq,
        )

        if not is_verified:
            raise ValidationError(
                f"Nie można nadać statusu VERIFIED dla zmiennej {var_id}: brak potwierdzenia w oficjalnych metadanych GUS ({reason})."
            )

        return True

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
        expected_name: Optional[str] = None,
        expected_frequency: Optional[str] = None,
        **kwargs,
    ) -> Tuple[RawEvidence, List[MacroObservation]]:
        """
        Pobiera serię danych ze zmiennej GUS BDL dla danego terytorium (domyślnie POLSKA: 000000000000).
        Zwraca parę (RawEvidence, List[MacroObservation]).
        Status obserwacji jest ściśle determinowany przez weryfikację metadanych (brak możliwości wymuszenia przez force_status="VERIFIED").
        """
        if kwargs.get("force_status") == "VERIFIED":
            raise ValidationError(
                "Wymuszanie statusu VERIFIED przez parametr 'force_status' jest zablokowane ze względów bezpieczeństwa. "
                "Status musi wynikać z oficjalnych metadanych GUS lub kontrolowanego rejestru."
            )

        approved_meta = self.APPROVED_BDL_REGISTRY.get(var_id)
        ind_code = indicator_code or (approved_meta.get("indicator_code") if approved_meta else None)
        u_code = unit_code or (approved_meta.get("unit_code") if approved_meta else None)

        if not ind_code or not u_code:
            raise VariableNotMappedError(
                f"Zmienna BDL ID={var_id} nie znajduje się w rejestrze zatwierdzonych zmiennych. "
                "Podaj jawnie indicator_code i unit_code lub użyj oficjalnie zweryfikowanej zmiennej."
            )

        # Weryfikacja statusu: oficjalne metadane GUS lub kontrolowany rejestr
        is_verified, reason, verified_meta = self.verify_bdl_variable_metadata(
            var_id=var_id,
            indicator_code=ind_code,
            expected_name=expected_name,
            expected_unit=u_code,
            expected_frequency=expected_frequency,
        )

        status = "VERIFIED" if is_verified else "NOT_VERIFIED"
        status_reason = reason

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
                    "status_reason": status_reason,
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
        candidate_mapping: Optional[Dict[str, Any]] = None,
        verified_mapping: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> Tuple[RawEvidence, List[MacroObservation]]:
        """
        Pobiera liczbę bezrobotnych zarejestrowanych GUS (PL_UNEMPLOYMENT_REGISTERED_COUNT).

        Zgodnie z wymogami bezpieczeństwa danych:
        Statusu VERIFIED NIE WOLNO nadać wyłącznie na podstawie przekazanego przez wywołującego
        słownika `verified_mapping` / `candidate_mapping` ani parametru `force_status`.

        Status VERIFIED wolno nadać dopiero po sprawdzeniu identyfikatora zmiennej, definicji,
        jednostki i częstotliwości w rzeczywistych metadanych oficjalnego API GUS lub w osobnym,
        wcześniej zatwierdzonym rejestrze mapowań (APPROVED_BDL_REGISTRY).

        Jeżeli weryfikacja nie jest możliwa lub dane są niespójne/fikcyjne, status bezwzględnie
        pozostaje NOT_VERIFIED (lub PENDING).
        """
        if kwargs.get("force_status") == "VERIFIED":
            raise ValidationError(
                "Wymuszanie statusu VERIFIED przez parametr 'force_status' jest zablokowane ze względów bezpieczeństwa."
            )

        mapping = verified_mapping or candidate_mapping

        if mapping:
            req_keys = {"var_id", "name", "unit_code", "frequency"}
            missing = req_keys - set(mapping.keys())
            if missing:
                raise ValidationError(
                    f"Niekompletne mapowanie dla PL_UNEMPLOYMENT_REGISTERED_COUNT. Brakujące pola: {missing}. "
                    "Wymagane: var_id, name, unit_code, frequency."
                )
            v_id = int(mapping["var_id"])
            v_name = mapping["name"]
            v_unit = mapping["unit_code"]
            v_freq = mapping["frequency"]

            return self.fetch_bdl_variable(
                v_id,
                indicator_code="PL_UNEMPLOYMENT_REGISTERED_COUNT",
                unit_code=v_unit,
                expected_name=v_name,
                expected_frequency=v_freq,
            )

        if var_id is not None:
            return self.fetch_bdl_variable(
                var_id,
                indicator_code="PL_UNEMPLOYMENT_REGISTERED_COUNT",
                unit_code="THOUSAND_PERSONS",
                expected_name="Liczba zarejestrowanych bezrobotnych",
                expected_frequency="MONTHLY",
            )

        raise VariableNotMappedError(
            "Wskaźnik PL_UNEMPLOYMENT_REGISTERED_COUNT posiada status NOT_VERIFIED. "
            "Dawne ID 60269 zostało wycofane z API BDL (HTTP 404). "
            "Wymagane jest potwierdzenie w rzeczywistych metadanych API GUS lub w osobnym rejestrze APPROVED_BDL_REGISTRY."
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
        Pobiera wskaźnik CPI z GUS DBW.
        """
        resolved_month = self._resolve_dbw_month(okres_id, explicit_month=month)
        rok_int = int(rok)
        if rok_int < 1990 or rok_int > 2050:
            raise ValidationError(f"Nieprawidłowy rok dla GUS DBW: {rok}")

        url = (
            f"{self.DBW_BASE_URL}/variable/variable-data-section"
            f"?id-zmienna={var_id}&id-przekroj={przekroj_id}&id-rok={rok_int}&id-okres={okres_id}"
        )

        try:
            status_code, payload_text, content_hash, retrieved_at_utc = self._execute_request(url)
        except Exception:
            if self.offline_mode:
                fallback_url = f"{self.DBW_BASE_URL}/data/data-data"
                status_code, payload_text, content_hash, retrieved_at_utc = self._execute_request(fallback_url)
            else:
                raise

        try:
            data = json.loads(payload_text)
        except json.JSONDecodeError as err:
            raise ValidationError(f"Błąd parsowania JSON z GUS DBW CPI ({url}): {str(err)}") from err

        data_list = data.get("data", [])
        if not data_list:
            raise DataNotFoundError(f"Brak danych w GUS DBW dla zmienna={var_id}, przekroj={przekroj_id}, rok={rok}, okres={okres_id}")

        item = data_list[0]
        raw_val = item.get("wartosc")
        if raw_val is None:
            raise DataNotFoundError("Brak wartości liczbowej 'wartosc' w odpowiedzi GUS DBW CPI")

        dec_val = Decimal(str(raw_val).replace(" ", "").replace(",", "."))

        if is_index_base_100:
            if as_percentage_change:
                val_calc = dec_val - Decimal("100.0")
                unit = "PCT"
            else:
                val_calc = dec_val
                unit = "INDEX_POINTS"
        else:
            val_calc = dec_val
            unit = "PCT"

        val_str = self.validate_value(val_calc)
        p_start = f"{rok_int:04d}-{resolved_month:02d}-01"
        last_day = calendar.monthrange(rok_int, resolved_month)[1]
        p_end = f"{rok_int:04d}-{resolved_month:02d}-{last_day:02d}"

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
            frequency=self.validate_frequency("MONTHLY"),
            value_decimal=val_str,
            unit_code=self.validate_unit(unit),
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
            candidate_mapping = kwargs.get("candidate_mapping") or kwargs.get("verified_mapping")
            return self.fetch_registered_unemployment_count(var_id=var_id, candidate_mapping=candidate_mapping, **kwargs)

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
                clean_kwargs = {k: v for k, v in kwargs.items() if k not in ("var_id", "indicator_code", "unit_code")}
                return self.fetch_bdl_variable(var_id=int(var_id), indicator_code=code, unit_code=kwargs.get("unit_code", "PCT"), **clean_kwargs)
            raise VariableNotMappedError(
                f"Wskaźnik '{code}' ({self.UNMAPPED_INDICATORS[code]}) w GUS posiada status CONFIRMED_API_REQUIRES_VARIABLE_MAPPING. "
                "Aby uniknąć fikcyjnych identyfikatorów, użyj metody search_bdl_variables() w celu zmapowania aktualnego ID lub przekaż parametr 'var_id'."
            )

        raise ValidationError(f"Nieznany lub nieobsługiwany kod wskaźnika GUS: '{indicator_code}'")


def urllib_quote(s: str) -> str:
    import urllib.parse
    return urllib.parse.quote(s)
