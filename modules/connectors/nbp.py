"""
Konektor do oficjalnych źródeł Narodowego Banku Polskiego (NBP).
Plik: modules/connectors/nbp.py

Obsługuje:
1. Kursy średnie walut (EUR/PLN, USD/PLN) z oficjalnego API REST:
   GET https://api.nbp.pl/api/exchangerates/rates/A/{currency}/?format=json
2. Stopę referencyjną NBP z oficjalnego pliku maszynowego XML:
   GET https://static.nbp.pl/dane/stopy/stopy_procentowe.xml
"""

from decimal import Decimal
import json
import xml.etree.ElementTree as ET
from typing import Optional, Tuple

from modules.connectors.base import (
    BaseConnector,
    DataNotFoundError,
    MacroObservation,
    RawEvidence,
    ValidationError,
)


class NbpConnector(BaseConnector):
    """Oficjalny konektor do danych Narodowego Banku Polskiego."""

    BASE_REST_URL = "https://api.nbp.pl/api/exchangerates/rates/A"
    STATIC_RATES_XML_URL = "https://static.nbp.pl/dane/stopy/stopy_procentowe.xml"
    SOURCE_ID = "SRC_NBP"

    SUPPORTED_CURRENCIES = {
        "EUR": ("PL_FX_EUR_PLN", "EUR_PLN"),
        "USD": ("PL_FX_USD_PLN", "USD_PLN"),
    }

    def fetch_exchange_rate(self, currency_code: str) -> Tuple[RawEvidence, MacroObservation]:
        """
        Pobiera bieżący kurs średni wybranej waluty (EUR lub USD) z Tabeli A NBP.
        Zwraca parę (RawEvidence, MacroObservation).
        """
        code_upper = currency_code.upper().strip()
        if code_upper not in self.SUPPORTED_CURRENCIES:
            raise ValidationError(
                f"Nieobsługiwany kod waluty: '{currency_code}'. Dopuszczalne: {list(self.SUPPORTED_CURRENCIES.keys())}"
            )

        indicator_code, unit_code = self.SUPPORTED_CURRENCIES[code_upper]
        url = f"{self.BASE_REST_URL}/{code_upper}/?format=json"

        status_code, payload_text, content_hash, retrieved_at_utc = self._execute_request(url)

        try:
            data = json.loads(payload_text)
        except json.JSONDecodeError as json_err:
            raise ValidationError(f"Błąd parsowania JSON z API NBP ({url}): {str(json_err)}") from json_err

        rates = data.get("rates")
        if not rates or not isinstance(rates, list) or len(rates) == 0:
            raise DataNotFoundError(f"Brak notowań dla waluty {code_upper} w odpowiedzi NBP")

        latest_rate = rates[-1]
        raw_mid = latest_rate.get("mid")
        effective_date = latest_rate.get("effectiveDate")
        table_no = latest_rate.get("no", "")

        if raw_mid is None or not effective_date:
            raise ValidationError(f"Niekompletne dane notowania NBP: {latest_rate}")

        # Walidacja dziedzinowa
        val_str = self.validate_value(raw_mid, min_plausible=Decimal("0.5"), max_plausible=Decimal("20.0"))
        iso_date = self.validate_iso_date(effective_date)
        validated_unit = self.validate_unit(unit_code)
        validated_freq = self.validate_frequency("DAILY")

        evidence = self.create_evidence(
            source_id=self.SOURCE_ID,
            source_url=url,
            document_type="API_RESPONSE",
            payload_text=payload_text,
            content_hash=content_hash,
            status_code=status_code,
            retrieved_at_utc=retrieved_at_utc,
        )

        observation = MacroObservation(
            indicator_code=indicator_code,
            country_code="PL",
            period_start=iso_date,
            period_end=iso_date,
            frequency=validated_freq,
            value_decimal=val_str,
            unit_code=validated_unit,
            revision_type="FINAL",
            status="VERIFIED",
            evidence_id=evidence.evidence_id,
            publication_date=iso_date,
            metadata={
                "table_no": table_no,
                "currency_name": data.get("currency", ""),
                "currency_code": code_upper,
            },
        )

        return evidence, observation

    def fetch_reference_rate(self) -> Tuple[RawEvidence, MacroObservation]:
        """
        Pobiera aktualną stopę referencyjną NBP z oficjalnego pliku XML.
        Zwraca parę (RawEvidence, MacroObservation).
        """
        url = self.STATIC_RATES_XML_URL
        status_code, payload_text, content_hash, retrieved_at_utc = self._execute_request(url)

        try:
            root = ET.fromstring(payload_text)
        except ET.ParseError as xml_err:
            raise ValidationError(f"Błąd parsowania XML ze stóp NBP ({url}): {str(xml_err)}") from xml_err

        # Poszukiwanie pozycji ze stopą referencyjną: <pozycja id="ref" .../>
        ref_elem = None
        for elem in root.findall(".//pozycja"):
            if elem.attrib.get("id") == "ref":
                ref_elem = elem
                break

        if ref_elem is None:
            raise DataNotFoundError(f"W pliku XML stóp NBP nie odnaleziono pozycji 'ref' (stopy referencyjnej): {url}")

        raw_rate = ref_elem.attrib.get("oprocentowanie")
        obowiazuje_od = ref_elem.attrib.get("obowiazuje_od")

        if not raw_rate or not obowiazuje_od:
            raise ValidationError(f"Brak wymaganych atrybutów w pozycji XML stóp NBP: {ref_elem.attrib}")

        # Walidacja dziedzinowa
        val_str = self.validate_value(raw_rate, min_plausible=Decimal("0.0"), max_plausible=Decimal("100.0"))
        iso_date = self.validate_iso_date(obowiazuje_od)
        validated_unit = self.validate_unit("PCT")
        validated_freq = self.validate_frequency("IRREGULAR")

        evidence = self.create_evidence(
            source_id=self.SOURCE_ID,
            source_url=url,
            document_type="OFFICIAL_XML",
            payload_text=payload_text,
            content_hash=content_hash,
            status_code=status_code,
            retrieved_at_utc=retrieved_at_utc,
        )

        observation = MacroObservation(
            indicator_code="PL_NBP_REFERENCE_RATE",
            country_code="PL",
            period_start=iso_date,
            period_end=iso_date,
            frequency=validated_freq,
            value_decimal=val_str,
            unit_code=validated_unit,
            revision_type="FINAL",
            status="VERIFIED",
            evidence_id=evidence.evidence_id,
            publication_date=iso_date,
            metadata={
                "rate_type": "referencyjna",
                "rate_id": "ref",
                "effective_from": obowiazuje_od,
                "is_current_table": True,
            },
        )

        return evidence, observation
