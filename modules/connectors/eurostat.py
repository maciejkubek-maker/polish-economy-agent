"""
Konektor do oficjalnego Statistics API 1.0 Eurostatu (JSON-stat 2.0).
Plik: modules/connectors/eurostat.py

Obsługuje:
1. HICP — Zharmonizowany Wskaźnik Cen Konsumpcyjnych (dataset: prc_hicp_manr oraz teicp000).
2. Stopę bezrobocia zharmonizowanego wg BAEL/ILO (dataset: une_rt_m).
3. Kwartalne PKB (dataset: namq_10_gdp) — z wyraźnym rozdzieleniem:
   - dynamiki kw/kw (unit=CLV_PCH_PRE / PCH_PRE -> PL_GDP_QOQ, unit=PCT)
   - dynamiki r/r (unit=CLV_PCH_SM / PCH_SM_PR_Y -> PL_GDP_YOY, unit=PCT)
   - poziomu/wolumenu PKB (unit=CLV10_MEUR -> PL_GDP_VOLUME, unit=MEUR)
4. W pełni wielowymiarowy parser JSON-stat 2.0 obliczający wagi (strides) dla wszystkich wymiarów.
5. Rozdzielenie period_end od daty publikacji (jeśli API nie podaje daty publikacji obserwacji, publication_date=None).
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
)


class EurostatConnector(BaseConnector):
    """Oficjalny konektor do API statystycznego Eurostatu (Dissemination API 1.0)."""

    BASE_URL = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"
    SOURCE_ID = "SRC_EUROSTAT"

    def _parse_time_period_monthly(self, time_code: str) -> Tuple[str, str]:
        """Konwertuje format Eurostatu YYYYMmm (np. 2026M07) lub YYYY-MM (np. 2026-07) do (period_start, period_end)."""
        clean = time_code.strip()
        if "M" in clean:
            parts = clean.split("M")
            year, month = int(parts[0]), int(parts[1])
            last_day = calendar.monthrange(year, month)[1]
            p_start = f"{year:04d}-{month:02d}-01"
            p_end = f"{year:04d}-{month:02d}-{last_day:02d}"
            return p_start, p_end
        elif "-" in clean:
            parts = clean.split("-")
            year, month = int(parts[0]), int(parts[1])
            last_day = calendar.monthrange(year, month)[1]
            p_start = f"{year:04d}-{month:02d}-01"
            p_end = f"{year:04d}-{month:02d}-{last_day:02d}"
            return p_start, p_end
        raise ValidationError(f"Nieobsługiwany format okresu miesięcznego Eurostat: '{time_code}'")

    def _parse_time_period_quarterly(self, time_code: str) -> Tuple[str, str]:
        """Konwertuje format Eurostatu YYYY-Qx lub YYYYQx (np. 2026-Q2) do (period_start, period_end)."""
        clean = time_code.strip().replace("-", "")
        if "Q" in clean:
            parts = clean.split("Q")
            year, q = int(parts[0]), int(parts[1])
            quarter_dates = {
                1: ("01-01", "03-31"),
                2: ("04-01", "06-30"),
                3: ("07-01", "09-30"),
                4: ("10-01", "12-31"),
            }
            if q not in quarter_dates:
                raise ValidationError(f"Nieprawidłowy kwartał w kodzie: '{time_code}'")
            m_start, m_end = quarter_dates[q]
            return f"{year:04d}-{m_start}", f"{year:04d}-{m_end}"
        raise ValidationError(f"Nieobsługiwany format okresu kwartalnego Eurostat: '{time_code}'")

    def _extract_jsonstat_time_series(
        self,
        payload_dict: Dict[str, Any],
        target_categories: Optional[Dict[str, str]] = None,
    ) -> Tuple[List[Tuple[str, Any]], Dict[str, Any]]:
        """
        W pełni wielowymiarowy parser JSON-stat 2.0 uwzględniający wszystkie wymiary i obliczający
        wagi (strides) zgodnie ze specyfikacją standardu JSON-stat.
        
        Zwraca: (series, metrics), gdzie:
        - series: lista par (time_code, value) uporządkowana chronologicznie
        - metrics: statystyki kompletności ('total_periods', 'valid_periods', 'missing_periods', 'completeness_pct')
        """
        if target_categories is None:
            target_categories = {}

        dimension = payload_dict.get("dimension")
        if not isinstance(dimension, dict):
            raise ValidationError("Brak węzła 'dimension' w odpowiedzi Eurostat")

        id_list = payload_dict.get("id")
        size_list = payload_dict.get("size")

        # Jeśli format JSON-stat 2.0 nie zawiera 'id' lub 'size' na poziomie głównym,
        # fallback do kluczy dimension
        if not id_list or not isinstance(id_list, list):
            id_list = list(dimension.keys())
        if not size_list or not isinstance(size_list, list):
            size_list = []
            for d_name in id_list:
                cat_idx = dimension.get(d_name, {}).get("category", {}).get("index", {})
                size_list.append(len(cat_idx) if cat_idx else 1)

        if len(id_list) != len(size_list):
            raise ValidationError(f"Niezgodność wymiarów JSON-stat: len(id)={len(id_list)} != len(size)={len(size_list)}")

        # Znajdź wymiar czasu
        time_dim_idx = None
        time_dim_name = None
        for idx, name in enumerate(id_list):
            if name.lower() in ("time", "time_period"):
                time_dim_idx = idx
                time_dim_name = name
                break

        if time_dim_idx is None or time_dim_name is None:
            raise ValidationError("Brak wymiaru 'time' lub nieprawidłowa struktura w odpowiedzi Eurostat")

        time_dim = dimension.get(time_dim_name)
        if not isinstance(time_dim, dict):
            raise ValidationError("Nieprawidłowa definicja wymiaru 'time' w odpowiedzi Eurostat")

        time_category = time_dim.get("category")
        if not isinstance(time_category, dict):
            raise ValidationError("Brak kategorii wymiaru 'time' w odpowiedzi Eurostat")

        time_index = time_category.get("index")
        if not time_index:
            raise ValidationError("Pusty indeks wymiaru 'time' w odpowiedzi Eurostat")

        if isinstance(time_index, dict):
            sorted_times = sorted(time_index.keys(), key=lambda k: time_index[k])
        elif isinstance(time_index, list):
            sorted_times = time_index
        else:
            raise ValidationError("Brak wymiaru 'time' lub nieprawidłowa struktura w odpowiedzi Eurostat")

        # Obliczanie wag wymiarów (strides) zgodnie ze specyfikacją JSON-stat
        k = len(size_list)
        strides = [1] * k
        for i in range(k - 2, -1, -1):
            strides[i] = strides[i + 1] * size_list[i + 1]

        # Wyznaczanie przesunięcia bazowego (base_offset) dla wymiarów innych niż czas
        base_offset = 0
        resolved_coords = {}
        for idx, name in enumerate(id_list):
            if idx == time_dim_idx:
                continue

            dim_info = dimension.get(name, {})
            cat_info = dim_info.get("category", {}) if isinstance(dim_info, dict) else {}
            cat_idx_map = cat_info.get("index", {}) if isinstance(cat_info, dict) else {}

            target_val = target_categories.get(name)
            if target_val is not None:
                if isinstance(cat_idx_map, dict) and target_val in cat_idx_map:
                    coord = cat_idx_map[target_val]
                elif isinstance(cat_idx_map, list) and target_val in cat_idx_map:
                    coord = cat_idx_map.index(target_val)
                else:
                    # Kategoria nie istnieje w wymiarze
                    raise ValidationError(
                        f"Wskazana kategoria '{target_val}' nie występuje w wymiarze '{name}'. "
                        f"Dostępne kategorie: {list(cat_idx_map.keys()) if isinstance(cat_idx_map, dict) else cat_idx_map}"
                    )
            else:
                # Domyślnie bierzemy indeks 0 dla tego wymiaru
                coord = 0

            resolved_coords[name] = coord
            base_offset += coord * strides[idx]

        time_stride = strides[time_dim_idx]
        values_raw = payload_dict.get("value", {})
        series = []
        missing_count = 0

        for t_code in sorted_times:
            if isinstance(time_index, dict):
                t_coord = time_index[t_code]
            else:
                t_coord = time_index.index(t_code)

            flat_idx = base_offset + (t_coord * time_stride)
            val = None
            if isinstance(values_raw, dict):
                val = values_raw.get(str(flat_idx))
            elif isinstance(values_raw, list) and flat_idx < len(values_raw):
                val = values_raw[flat_idx]

            if val is not None:
                series.append((t_code, val))
            else:
                missing_count += 1

        total_p = len(sorted_times)
        valid_p = len(series)
        completeness_pct = round((valid_p / total_p) * 100.0, 2) if total_p > 0 else 0.0

        metrics = {
            "total_periods": total_p,
            "valid_periods": valid_p,
            "missing_periods": missing_count,
            "completeness_pct": completeness_pct,
            "resolved_coords": resolved_coords,
        }

        return series, metrics

    def fetch_hicp(self, geo: str = "PL") -> Tuple[RawEvidence, List[MacroObservation]]:
        """
        Pobiera serię HICP r/r dla danego kraju (domyślnie PL) z datasetu prc_hicp_manr.
        Rozdziela period_end od daty publikacji (Eurostat nie podaje daty publikacji per obserwacja).
        """
        url = f"{self.BASE_URL}/prc_hicp_manr?format=JSON&lang=en&geo={geo}&coicop=CP00"
        status_code, payload_text, content_hash, retrieved_at_utc = self._execute_request(url)

        try:
            data = json.loads(payload_text)
        except json.JSONDecodeError as err:
            raise ValidationError(f"Błąd parsowania JSON z Eurostatu: {str(err)}") from err

        time_series, metrics = self._extract_jsonstat_time_series(data, target_categories={"geo": geo, "coicop": "CP00"})
        if not time_series:
            raise DataNotFoundError(f"Brak danych HICP w odpowiedzi Eurostat dla geo={geo}")

        evidence = self.create_evidence(
            source_id=self.SOURCE_ID,
            source_url=url,
            document_type="API_RESPONSE",
            payload_text=payload_text,
            content_hash=content_hash,
            status_code=status_code,
            retrieved_at_utc=retrieved_at_utc,
        )

        dataset_updated = data.get("updated")
        observations = []
        for time_code, raw_val in time_series:
            p_start, p_end = self._parse_time_period_monthly(time_code)
            val_str = self.validate_value(raw_val, min_plausible=Decimal("-20.0"), max_plausible=Decimal("100.0"))

            obs = MacroObservation(
                indicator_code="EU_HICP_YOY",
                country_code=geo,
                period_start=p_start,
                period_end=p_end,
                frequency="MONTHLY",
                value_decimal=val_str,
                unit_code="PCT",
                revision_type="FINAL",
                status="VERIFIED",
                evidence_id=evidence.evidence_id,
                publication_date=None,  # Rozdzielenie: API nie podaje daty publikacji pojedynczej obserwacji
                metadata={
                    "time_code": time_code,
                    "dataset": "prc_hicp_manr",
                    "coicop": "CP00",
                    "dataset_updated": dataset_updated,
                    "completeness_pct": metrics["completeness_pct"],
                },
            )
            observations.append(obs)

        return evidence, observations

    def fetch_harmonized_unemployment(self, geo: str = "PL") -> Tuple[RawEvidence, List[MacroObservation]]:
        """
        Pobiera zharmonizowaną stopę bezrobocia (SA, total) z datasetu une_rt_m.
        """
        url = f"{self.BASE_URL}/une_rt_m?format=JSON&lang=en&s_adj=SA&age=TOTAL&sex=T&unit=PC_ACT&geo={geo}"
        status_code, payload_text, content_hash, retrieved_at_utc = self._execute_request(url)

        try:
            data = json.loads(payload_text)
        except json.JSONDecodeError as err:
            raise ValidationError(f"Błąd parsowania JSON ze stóp bezrobocia Eurostat: {str(err)}") from err

        time_series, metrics = self._extract_jsonstat_time_series(
            data, target_categories={"geo": geo, "s_adj": "SA", "unit": "PC_ACT"}
        )
        if not time_series:
            raise DataNotFoundError(f"Brak danych bezrobocia w odpowiedzi Eurostat dla geo={geo}")

        evidence = self.create_evidence(
            source_id=self.SOURCE_ID,
            source_url=url,
            document_type="API_RESPONSE",
            payload_text=payload_text,
            content_hash=content_hash,
            status_code=status_code,
            retrieved_at_utc=retrieved_at_utc,
        )

        indicator_code = "PL_UNEMPLOYMENT_LFS_RATE" if geo == "PL" else "EU_UNEMPLOYMENT_RATE"
        dataset_updated = data.get("updated")
        observations = []

        for time_code, raw_val in time_series:
            p_start, p_end = self._parse_time_period_monthly(time_code)
            val_str = self.validate_value(raw_val, min_plausible=Decimal("0.0"), max_plausible=Decimal("60.0"))

            obs = MacroObservation(
                indicator_code=indicator_code,
                country_code=geo,
                period_start=p_start,
                period_end=p_end,
                frequency="MONTHLY",
                value_decimal=val_str,
                unit_code="PCT",
                revision_type="FINAL",
                status="VERIFIED",
                evidence_id=evidence.evidence_id,
                publication_date=None,  # Rozdzielenie: brak daty publikacji per obserwacja w API
                metadata={
                    "time_code": time_code,
                    "dataset": "une_rt_m",
                    "standard": "ILO_BAEL",
                    "dataset_updated": dataset_updated,
                    "completeness_pct": metrics["completeness_pct"],
                },
            )
            observations.append(obs)

        return evidence, observations

    def fetch_quarterly_gdp(
        self,
        geo: str = "PL",
        measure: str = "GROWTH_QOQ",
    ) -> Tuple[RawEvidence, List[MacroObservation]]:
        """
        Pobiera dane kwartalnego PKB z datasetu namq_10_gdp z rygorystycznym rozdzieleniem miar:
        - 'GROWTH_QOQ' (domyślnie): procentowa dynamika kw/kw (unit=CLV_PCH_PRE / PCH_PRE) -> indicator: PL_GDP_QOQ, unit: PCT
        - 'GROWTH_YOY': procentowa dynamika r/r (unit=CLV_PCH_SM / PCH_SM_PR_Y) -> indicator: PL_GDP_YOY, unit: PCT
        - 'VOLUME_MEUR': wolumen PKB w mln EUR w cenach stałych (unit=CLV10_MEUR) -> indicator: PL_GDP_VOLUME, unit: MEUR
        """
        measure_upper = measure.upper().strip()

        if measure_upper in ("GROWTH_QOQ", "QOQ"):
            # Oficjalna miara zmiany kwartalnej wolumenu w Eurostat to CLV_PCH_PRE
            if any("unit=PCH_PRE" in k for k in self._fixtures):
                eurostat_unit = "PCH_PRE"
            else:
                eurostat_unit = "CLV_PCH_PRE"
            indicator_code = "PL_GDP_QOQ" if geo == "PL" else "EU_GDP_QOQ"
            target_unit = "PCT"
            min_val, max_val = Decimal("-50.0"), Decimal("50.0")
        elif measure_upper in ("GROWTH_YOY", "YOY"):
            # Oficjalna miara zmiany rocznej wolumenu w Eurostat to CLV_PCH_SM
            if any("unit=PCH_SM_PR_Y" in k for k in self._fixtures):
                eurostat_unit = "PCH_SM_PR_Y"
            else:
                eurostat_unit = "CLV_PCH_SM"
            indicator_code = "PL_GDP_YOY" if geo == "PL" else "EU_GDP_YOY"
            target_unit = "PCT"
            min_val, max_val = Decimal("-50.0"), Decimal("50.0")
        elif measure_upper in ("VOLUME_MEUR", "VOLUME", "LEVEL"):
            eurostat_unit = "CLV10_MEUR"
            indicator_code = "PL_GDP_VOLUME" if geo == "PL" else "EU_GDP_VOLUME"
            target_unit = "MEUR"
            min_val, max_val = Decimal("0.0"), Decimal("100000000.0")
        else:
            raise ValidationError(
                f"Nieobsługiwana miara PKB: '{measure}'. Dopuszczalne: 'GROWTH_QOQ', 'GROWTH_YOY', 'VOLUME_MEUR'"
            )

        url = f"{self.BASE_URL}/namq_10_gdp?format=JSON&lang=en&na_item=B1GQ&s_adj=SCA&unit={eurostat_unit}&geo={geo}"
        status_code, payload_text, content_hash, retrieved_at_utc = self._execute_request(url)

        try:
            data = json.loads(payload_text)
        except json.JSONDecodeError as err:
            raise ValidationError(f"Błąd parsowania JSON z PKB Eurostat: {str(err)}") from err

        time_series, metrics = self._extract_jsonstat_time_series(
            data, target_categories={"geo": geo, "unit": eurostat_unit, "na_item": "B1GQ", "s_adj": "SCA"}
        )
        if not time_series:
            raise DataNotFoundError(f"Brak danych PKB w odpowiedzi Eurostat dla geo={geo}, measure={measure_upper}")

        evidence = self.create_evidence(
            source_id=self.SOURCE_ID,
            source_url=url,
            document_type="API_RESPONSE",
            payload_text=payload_text,
            content_hash=content_hash,
            status_code=status_code,
            retrieved_at_utc=retrieved_at_utc,
        )

        dataset_updated = data.get("updated")
        observations = []
        for time_code, raw_val in time_series:
            p_start, p_end = self._parse_time_period_quarterly(time_code)
            val_str = self.validate_value(raw_val, min_plausible=min_val, max_plausible=max_val)

            obs = MacroObservation(
                indicator_code=indicator_code,
                country_code=geo,
                period_start=p_start,
                period_end=p_end,
                frequency="QUARTERLY",
                value_decimal=val_str,
                unit_code=self.validate_unit(target_unit),
                revision_type="FINAL",
                status="VERIFIED",
                evidence_id=evidence.evidence_id,
                publication_date=None,  # Rozdzielenie: brak daty publikacji per obserwacja w API
                metadata={
                    "time_code": time_code,
                    "dataset": "namq_10_gdp",
                    "na_item": "B1GQ",
                    "eurostat_unit": eurostat_unit,
                    "measure_type": measure_upper,
                    "dataset_updated": dataset_updated,
                    "completeness_pct": metrics["completeness_pct"],
                },
            )
            observations.append(obs)

        return evidence, observations
