"""
Moduł polityki doboru i hierarchii wskaźników makroekonomicznych dla raportu gospodarczego Polski.
Plik: modules/report_indicator_policy.py

Zapewnia trwałą, programową politykę doboru wskaźników:
1. Obowiązkowa hierarchia (Priorytet A: Core, Priorytet B: Kontekst, Priorytet C: Pomocnicze).
2. Kwalifikacja aktualności: CURRENT, EFFECTIVE (stopy NBP), ARCHIVAL, ANNUAL_HISTORICAL, MISSING.
3. Ścisłe reguły metodologiczne:
   - ZAKAZ zastępowania CPI GUS przez HICP bez wyjaśnienia odmiennej metodologii.
   - ZAKAZ zastępowania bezrobocia rejestrowanego GUS przez BAEL bez wyjaśnienia metodologii ankietowej.
   - ZAKAZ podstawiania rocznego odczytu bezrobocia (GUS BDL 60270) jako bieżącej miesięcznej stopy.
   - PKB r/r jako wiodąca miara wzrostu nad PKB kw/kw i wolumenem technicznym w mln EUR.
   - Stopa NBP obowiązuje od daty decyzji do odwołania przez RPP (brak fałszywego lag_days).
4. Przekazywanie ustrukturyzowanego kontekstu do LLM oraz budowa horyzontu wykonawczego.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
import re
from typing import Any, Dict, List, Optional, Set, Tuple


class IndicatorPriority(str, Enum):
    CORE = "PRIORITY_A_CORE"          # Priorytet A — główna treść raportu
    CONTEXT = "PRIORITY_B_CONTEXT"    # Priorytet B — kontekst gospodarczy
    AUXILIARY = "PRIORITY_C_AUX"      # Priorytet C — wskaźniki pomocnicze/uzupełniające
    UNASSIGNED = "UNASSIGNED"


class FreshnessStatus(str, Enum):
    CURRENT = "CURRENT"               # Bieżący odczyt miesięczny / kwartalny (lag <= 90 dni)
    EFFECTIVE = "EFFECTIVE"           # Obowiązująca decyzja prawna (np. stopa NBP ważna do odwołania)
    ARCHIVAL = "ARCHIVAL"             # Odczyt historyczny/archiwalny (lag > 90 dni)
    ANNUAL_HISTORICAL = "ANNUAL_HISTORICAL" # Szereg roczny (np. bezrobocie z BDL 60270, baza roczna)
    MISSING = "MISSING"               # Brak potwierdzonego odczytu w bieżącym przebiegu


@dataclass
class EvaluatedIndicator:
    indicator_code: str
    name_pl: str
    priority: IndicatorPriority
    rank: int                         # Pozycja w hierarchii danego priorytetu
    domain: str                       # INFLATION, LABOUR_MARKET, GROWTH, MONETARY_POLICY, FX
    observation: Optional[Dict[str, Any]] = None
    citation_idx: Optional[int] = None
    freshness: FreshnessStatus = FreshnessStatus.MISSING
    lag_days: int = 0
    frequency: str = "UNKNOWN"
    value_decimal: Optional[str] = None
    unit_code: Optional[str] = None
    period_start: str = ""
    period_end: str = ""
    status_note: str = ""
    presentation_rule: str = ""


@dataclass
class PolicyReportPlan:
    country_code: str
    report_date: str
    core_indicators: List[EvaluatedIndicator] = field(default_factory=list)
    context_indicators: List[EvaluatedIndicator] = field(default_factory=list)
    auxiliary_indicators: List[EvaluatedIndicator] = field(default_factory=list)
    missing_core_indicators: List[str] = field(default_factory=list)
    archival_core_indicators: List[str] = field(default_factory=list)
    annual_indicators: List[str] = field(default_factory=list)
    executive_horizon_summary: str = ""
    ordered_context_prompt: str = ""


class ReportIndicatorPolicy:
    """Implementuje formalną politykę doboru i kolejności wskaźników w raporcie gospodarczym."""

    # 1. Obowiązkowe definicje i reguły priorytetów
    CORE_INDICATORS_DEF = [
        {
            "code": "PL_CPI_YOY",
            "name_pl": "Inflacja konsumencka CPI GUS",
            "aliases": ["PL_CPI_YOY"],
            "rank": 1,
            "domain": "INFLATION",
            "expected_frequency": "MONTHLY",
            "section": "Ceny i Zakupy",
            "rule": "Główny krajowy wskaźnik inflacji konsumenckiej (GUS). W sekcji 'Ceny i Zakupy' stanowi nadrzędny punkt odniesienia. ZAKAZ zastępowania go odczytem HICP.",
        },
        {
            "code": "PL_UNEMPLOYMENT_REGISTERED_RATE",
            "name_pl": "Stopa bezrobocia rejestrowanego GUS",
            "aliases": ["PL_UNEMPLOYMENT_REGISTERED_RATE", "PL_UNEMPLOYMENT_RATE"],
            "rank": 2,
            "domain": "LABOUR_MARKET",
            "expected_frequency": "MONTHLY",
            "section": "Praca i Zarobki",
            "rule": "Główny krajowy wskaźnik bezrobocia rejestrowanego w urzędach pracy (GUS). W sekcji 'Praca i Zarobki' stanowi nadrzędny odczyt. Jeśli dostępny jest tylko szereg roczny (BDL 60270), należy jawnie wskazać, że to roczny stan z bazy BDL, a nie miesięczna stopa bieżąca. ZAKAZ zastępowania go odczytem BAEL.",
        },
        {
            "code": "PL_GDP_YOY",
            "name_pl": "Wzrost PKB rok do roku (r/r)",
            "aliases": ["PL_GDP_YOY"],
            "rank": 3,
            "domain": "GROWTH",
            "expected_frequency": "QUARTERLY",
            "section": "Analiza Trendów / Podsumowanie",
            "rule": "Nadrzędny wskaźnik tempa rozwoju gospodarki. W sekcji 1 oraz podsumowaniu (sekcja 5) wzrost r/r ma bezwzględny priorytet nad dynamiką kw/kw i wolumenem w mln EUR.",
        },
        {
            "code": "PL_NBP_REFERENCE_RATE",
            "name_pl": "Stopa referencyjna NBP",
            "aliases": ["PL_NBP_REFERENCE_RATE", "PL_POLICY_RATE_REF"],
            "rank": 4,
            "domain": "MONETARY_POLICY",
            "expected_frequency": "IRREGULAR",
            "section": "Kredyty i Raty",
            "rule": "Oficjalna stopa referencyjna NBP. Obowiązuje od daty decyzji RPP do kolejnego posiedzenia decyzyjnego. Jest to w pełni aktualna stawka prawna, a nie przeterminowany odczyt.",
        },
        {
            "code": "PL_WAGE_AVERAGE_GROSS",
            "name_pl": "Przeciętne wynagrodzenie w sektorze przedsiębiorstw",
            "aliases": ["PL_WAGE_AVERAGE_GROSS", "PL_WAGE_AVG_ENTERPRISE"],
            "rank": 5,
            "domain": "LABOUR_MARKET",
            "expected_frequency": "MONTHLY",
            "section": "Praca i Zarobki",
            "rule": "Średnie wynagrodzenie brutto w sektorze przedsiębiorstw (GUS), o ile dostępne.",
        },
        {
            "code": "PL_EMPLOYMENT_GROWTH",
            "name_pl": "Zatrudnienie w sektorze przedsiębiorstw",
            "aliases": ["PL_EMPLOYMENT_GROWTH", "PL_EMPLOYMENT_COUNT", "PL_EMPLOYMENT"],
            "rank": 6,
            "domain": "LABOUR_MARKET",
            "expected_frequency": "MONTHLY",
            "section": "Praca i Zarobki",
            "rule": "Poziom i dynamika zatrudnienia w sektorze przedsiębiorstw (GUS), o ile dostępne.",
        },
    ]

    CONTEXT_INDICATORS_DEF = [
        {
            "code": "PL_GDP_QOQ",
            "name_pl": "Wzrost PKB kwartał do kwartału (kw/kw)",
            "aliases": ["PL_GDP_QOQ"],
            "rank": 1,
            "domain": "GROWTH",
            "rule": "Krótkookresowa kwartalna dynamika PKB wyrównana sezonowo (uzupełnienie PKB r/r).",
        },
        {
            "code": "PL_FX_EUR_PLN",
            "name_pl": "Kurs EUR/PLN (NBP)",
            "aliases": ["PL_FX_EUR_PLN"],
            "rank": 2,
            "domain": "FX",
            "rule": "Średni kurs EUR/PLN z tabeli A NBP. Kontekst walutowy dla importu/eksportu. Pojedynczy odczyt z danego dnia nie stanowi trendu.",
        },
        {
            "code": "PL_FX_USD_PLN",
            "name_pl": "Kurs USD/PLN (NBP)",
            "aliases": ["PL_FX_USD_PLN"],
            "rank": 3,
            "domain": "FX",
            "rule": "Średni kurs USD/PLN z tabeli A NBP. Kontekst walutowy dla cen surowców. Pojedynczy odczyt nie stanowi trendu.",
        },
    ]

    AUXILIARY_INDICATORS_DEF = [
        {
            "code": "PL_HICP_YOY",
            "name_pl": "Zharmonizowana inflacja HICP (Eurostat)",
            "aliases": ["PL_HICP_YOY"],
            "rank": 1,
            "domain": "INFLATION",
            "rule": "Zharmonizowany wskaźnik cen konsumpcyjnych wg Eurostatu. Służy wyłącznie do porównań międzynarodowych w UE. ZAKAZ zastępowania nim inflacji CPI GUS.",
        },
        {
            "code": "PL_UNEMPLOYMENT_LFS_RATE",
            "name_pl": "Stopa bezrobocia BAEL/LFS (Eurostat)",
            "aliases": ["PL_UNEMPLOYMENT_LFS_RATE"],
            "rank": 2,
            "domain": "LABOUR_MARKET",
            "rule": "Badanie Aktywności Ekonomicznej Ludności wg metodologii Eurostatu/ILO. Służy wyłącznie jako uzupełniający wskaźnik ankietowy. ZAKAZ zastępowania nim bezrobocia rejestrowanego GUS.",
        },
        {
            "code": "PL_GDP_VOLUME",
            "name_pl": "Wolumen PKB w cenach stałych (mln EUR)",
            "aliases": ["PL_GDP_VOLUME", "PL_GDP_VOLUME_MEUR"],
            "rank": 3,
            "domain": "GROWTH",
            "rule": "Techniczny wolumen PKB w milionach euro. Pomocniczy wskaźnik wielkości gospodarki, nie zastępuje stopy wzrostu r/r.",
        },
    ]

    @classmethod
    def evaluate(
        cls,
        verified_obs: List[Dict[str, Any]],
        citations: List[Dict[str, Any]],
        report_date: str,
        now: Optional[datetime] = None,
        country_code: str = "PL",
    ) -> PolicyReportPlan:
        """Dokonuje pełnej programowej ewaluacji zestawu danych wg polityki jakości."""
        now_dt = (now or datetime.now()).date()
        obs_by_code: Dict[str, Dict[str, Any]] = {}
        for o in verified_obs:
            c = o.get("indicator_code")
            if c:
                obs_by_code[c] = o

        citation_by_code: Dict[str, int] = {}
        for c in citations:
            ind = c.get("indicator_code")
            if ind and "idx" in c:
                citation_by_code[ind] = int(c["idx"])

        def _find_obs(aliases: List[str]) -> Tuple[Optional[Dict[str, Any]], Optional[int]]:
            for a in aliases:
                if a in obs_by_code:
                    c_idx = citation_by_code.get(a)
                    return obs_by_code[a], c_idx
            return None, None

        def _evaluate_item(item_def: Dict[str, Any], priority: IndicatorPriority) -> EvaluatedIndicator:
            code = item_def["code"]
            name = item_def["name_pl"]
            rank = item_def["rank"]
            domain = item_def["domain"]
            aliases = item_def.get("aliases", [code])
            rule = item_def.get("rule", "")

            obs, c_idx = _find_obs(aliases)

            if obs is None:
                return EvaluatedIndicator(
                    indicator_code=code,
                    name_pl=name,
                    priority=priority,
                    rank=rank,
                    domain=domain,
                    freshness=FreshnessStatus.MISSING,
                    presentation_rule=rule,
                    status_note=f"Brak potwierdzonego odczytu w rejestrze oficjalnym dla {name}.",
                )

            val = str(obs.get("value_decimal", "")).strip()
            unit = str(obs.get("unit_code", "")).strip()
            p_start = str(obs.get("period_start", ""))[:10]
            p_end = str(obs.get("period_end", ""))[:10]
            freq = str(obs.get("frequency", "")).upper().strip()

            # Specjalna reguła NBP: stopy procentowe to decyzje prawne (EFFECTIVE)
            is_policy_rate = code in ("PL_NBP_REFERENCE_RATE", "PL_POLICY_RATE_REF") or "NBP" in obs.get("source_id", "") and "RATE" in code
            if is_policy_rate:
                return EvaluatedIndicator(
                    indicator_code=code,
                    name_pl=name,
                    priority=priority,
                    rank=rank,
                    domain=domain,
                    observation=obs,
                    citation_idx=c_idx,
                    freshness=FreshnessStatus.EFFECTIVE,
                    lag_days=0,
                    frequency="EFFECTIVE_DECISION",
                    value_decimal=val,
                    unit_code=unit,
                    period_start=p_start,
                    period_end=p_end,
                    status_note=f"Oficjalna stopa referencyjna NBP obowiązująca od {p_start} r. do kolejnej decyzji RPP.",
                    presentation_rule=rule,
                )

            # Szereg roczny (np. GUS BDL 60270 dla stopy bezrobocia)
            is_annual = freq == "ANNUAL" or (p_start.endswith("-01-01") and p_end.endswith("-12-31") and p_start[:4] == p_end[:4])
            if is_annual:
                y = p_start[:4]
                return EvaluatedIndicator(
                    indicator_code=code,
                    name_pl=name,
                    priority=priority,
                    rank=rank,
                    domain=domain,
                    observation=obs,
                    citation_idx=c_idx,
                    freshness=FreshnessStatus.ANNUAL_HISTORICAL,
                    lag_days=(now_dt - datetime.strptime(p_end, "%Y-%m-%d").date()).days if p_end else 0,
                    frequency="ANNUAL",
                    value_decimal=val,
                    unit_code=unit,
                    period_start=p_start,
                    period_end=p_end,
                    status_note=f"Roczna baza odniesienia GUS BDL za {y} r. (stan na koniec roku). Nie wolno traktować jako bieżącej stopy miesięcznej.",
                    presentation_rule=rule,
                )

            # Obliczenie opóźnienia publikacyjnego (lag) dla wskaźników miesięcznych i kwartalnych
            lag_days = 0
            if p_end:
                try:
                    end_dt = datetime.strptime(p_end, "%Y-%m-%d").date()
                    lag_days = max(0, (now_dt - end_dt).days)
                except Exception:
                    lag_days = 0

            is_archival = lag_days > 90
            freshness = FreshnessStatus.ARCHIVAL if is_archival else FreshnessStatus.CURRENT
            status_note = (
                f"Odczyt archiwalny z okresu {p_start} – {p_end} (opóźnienie ~{lag_days} dni). Prezentować wyłącznie jako historyczną bazę odniesienia."
                if is_archival
                else f"Bieżący oficjalny odczyt za okres {p_start} – {p_end}."
            )

            return EvaluatedIndicator(
                indicator_code=code,
                name_pl=name,
                priority=priority,
                rank=rank,
                domain=domain,
                observation=obs,
                citation_idx=c_idx,
                freshness=freshness,
                lag_days=lag_days,
                frequency=freq or ("MONTHLY" if len(p_start) == 10 and p_start[5:7] == p_end[5:7] else "QUARTERLY"),
                value_decimal=val,
                unit_code=unit,
                period_start=p_start,
                period_end=p_end,
                status_note=status_note,
                presentation_rule=rule,
            )

        core_eval = [_evaluate_item(d, IndicatorPriority.CORE) for d in cls.CORE_INDICATORS_DEF]
        context_eval = [_evaluate_item(d, IndicatorPriority.CONTEXT) for d in cls.CONTEXT_INDICATORS_DEF]
        aux_eval = [_evaluate_item(d, IndicatorPriority.AUXILIARY) for d in cls.AUXILIARY_INDICATORS_DEF]

        missing_core = [it.name_pl for it in core_eval if it.freshness == FreshnessStatus.MISSING]
        archival_core = [f"{it.name_pl} ({it.period_start}..{it.period_end})" for it in core_eval if it.freshness == FreshnessStatus.ARCHIVAL]
        annual_core = [f"{it.name_pl} ({it.period_start[:4]} r.)" for it in core_eval if it.freshness == FreshnessStatus.ANNUAL_HISTORICAL]

        # Budowa uporządkowanego horyzontu wykonawczego
        horizon = cls.build_ordered_executive_horizon(core_eval, context_eval, aux_eval)

        # Budowa uporządkowanego promptu kontekstowego
        prompt_block = cls.build_ordered_context_prompt(
            core_eval=core_eval,
            context_eval=context_eval,
            aux_eval=aux_eval,
            missing_core=missing_core,
            archival_core=archival_core,
            annual_core=annual_core,
            report_date=report_date,
        )

        return PolicyReportPlan(
            country_code=country_code,
            report_date=report_date,
            core_indicators=core_eval,
            context_indicators=context_eval,
            auxiliary_indicators=aux_eval,
            missing_core_indicators=missing_core,
            archival_core_indicators=archival_core,
            annual_indicators=annual_core,
            executive_horizon_summary=horizon,
            ordered_context_prompt=prompt_block,
        )

    @classmethod
    def build_ordered_executive_horizon(
        cls,
        core_eval: List[EvaluatedIndicator],
        context_eval: List[EvaluatedIndicator],
        aux_eval: List[EvaluatedIndicator],
    ) -> str:
        """Tworzy precyzyjny, skonsolidowany horyzont odczytów dla raportu bez gubienia starszych okresów PKB."""
        parts = []

        # 1. Miesięczne odczyty (np. wrzesień 2026 r.)
        monthly_periods = set()
        month_names = {
            1: "styczeń", 2: "luty", 3: "marzec", 4: "kwiecień", 5: "maj", 6: "czerwiec",
            7: "lipiec", 8: "sierpień", 9: "wrzesień", 10: "październik", 11: "listopad", 12: "grudzień"
        }
        for item in core_eval + context_eval + aux_eval:
            if item.observation and item.frequency == "MONTHLY" and item.period_start:
                try:
                    y = int(item.period_start[:4])
                    m = int(item.period_start[5:7])
                    monthly_periods.add((y, m))
                except Exception:
                    pass

        if monthly_periods:
            sorted_m = sorted(list(monthly_periods))
            latest_y = sorted_m[-1][0]
            months_in_latest_y = [m for y, m in sorted_m if y == latest_y]
            if len(months_in_latest_y) >= 2:
                m_start = month_names[months_in_latest_y[-2]]
                m_end = month_names[months_in_latest_y[-1]]
                parts.append(f"{m_start.capitalize()} – {m_end} {latest_y} r. (wskaźniki miesięczne)")
            else:
                m_name = month_names[months_in_latest_y[-1]]
                parts.append(f"{m_name.capitalize()} {latest_y} r. (dane miesięczne)")

        # 2. Kwartalne odczyty PKB (np. II kw. 2026 r.)
        gdp_quarters = set()
        for item in core_eval + context_eval + aux_eval:
            if item.observation and item.frequency == "QUARTERLY" and item.period_start:
                try:
                    y = item.period_start[:4]
                    m = int(item.period_start[5:7])
                    q = (m - 1) // 3 + 1
                    roman_q = {1: "I", 2: "II", 3: "III", 4: "IV"}.get(q, str(q))
                    gdp_quarters.add(f"{roman_q} kw. {y} r.")
                except Exception:
                    pass

        if gdp_quarters:
            sorted_q = sorted(list(gdp_quarters))
            parts.append(f"{sorted_q[-1]} (PKB)")

        # 3. Obowiązująca stopa NBP
        for item in core_eval:
            if item.observation and item.freshness == FreshnessStatus.EFFECTIVE and item.period_start:
                try:
                    dt = datetime.strptime(item.period_start, "%Y-%m-%d").strftime("%d.%m.%Y")
                    parts.append(f"stopa NBP obowiązująca od {dt} r.")
                except Exception:
                    parts.append(f"stopa NBP obowiązująca od {item.period_start}")

        # 4. Szeregi roczne z bazy BDL
        annual_years = set()
        for item in core_eval:
            if item.observation and item.freshness == FreshnessStatus.ANNUAL_HISTORICAL and item.period_start:
                annual_years.add(item.period_start[:4])

        if annual_years:
            parts.append(f"baza roczna GUS BDL: {', '.join(sorted(list(annual_years)))} r.")

        return " | ".join(parts) if parts else "Bieżące odczyty GUS i NBP"

    @classmethod
    def build_ordered_context_prompt(
        cls,
        core_eval: List[EvaluatedIndicator],
        context_eval: List[EvaluatedIndicator],
        aux_eval: List[EvaluatedIndicator],
        missing_core: List[str],
        archival_core: List[str],
        annual_core: List[str],
        report_date: str,
    ) -> str:
        """Formatuje ustrukturyzowany blok instrukcji i danych dla LLM z jednoznaczną hierarchią."""
        lines = [
            "### OBOWIĄZKOWA HIERARCHIA WSKAŹNIKÓW POLSKIEJ GOSPODARKI (POLITYKA JAKOŚCI DANYCH):",
            "Jako Główny Ekonomista tworzysz raport przeznaczony dla polskiego odbiorcy.",
            "Obowiązuje bezwzględny priorytet wskaźników krajowych (GUS, NBP) nad wskaźnikami unijnymi i technicznymi.\n",
            "I. PRIORYTET A — GŁÓWNA TREŚĆ RAPORTU (KLUCZOWE WSKAŹNIKI KRAJOWE):",
        ]

        for item in core_eval:
            if item.observation:
                fn_str = f"[{item.citation_idx}]" if item.citation_idx else "[brak]"
                lines.append(
                    f"- {item.rank}. {fn_str} {item.name_pl} ({item.indicator_code}): {item.value_decimal} {item.unit_code} "
                    f"| okres: {item.period_start}..{item.period_end} | status: {item.freshness.value} "
                    f"| uwaga: {item.status_note}"
                )
            else:
                lines.append(
                    f"- {item.rank}. [BRAK W BAZIE] {item.name_pl} ({item.indicator_code}) — {item.status_note}"
                )

        lines.append("\nII. PRIORYTET B — KONTEKST GOSPODARCZY:")
        for item in context_eval:
            if item.observation:
                fn_str = f"[{item.citation_idx}]" if item.citation_idx else "[brak]"
                lines.append(
                    f"- {fn_str} {item.name_pl} ({item.indicator_code}): {item.value_decimal} {item.unit_code} "
                    f"| okres: {item.period_start}..{item.period_end} | {item.status_note}"
                )
            else:
                lines.append(f"- [BRAK] {item.name_pl} ({item.indicator_code}) — {item.status_note}")

        lines.append("\nIII. PRIORYTET C — WSKAŹNIKI POMOCNICZE / UZUPEŁNIAJĄCE:")
        for item in aux_eval:
            if item.observation:
                fn_str = f"[{item.citation_idx}]" if item.citation_idx else "[brak]"
                lines.append(
                    f"- {fn_str} {item.name_pl} ({item.indicator_code}): {item.value_decimal} {item.unit_code} "
                    f"| okres: {item.period_start}..{item.period_end} | {item.status_note}"
                )
            else:
                lines.append(f"- [BRAK] {item.name_pl} ({item.indicator_code}) — {item.status_note}")

        lines.append("\nIV. WYTYCZNE METODOLOGICZNE I ZASADY STRUKTURY:")
        lines.append("1. SEKCJA 'Ceny i Zakupy' (perspektywa Kowalskiego):")
        lines.append("   - Głównym wskaźnikiem MUSI być inflacja konsumencka CPI GUS (PL_CPI_YOY).")
        lines.append("   - Wskaźnik HICP (Eurostat) może być wymieniony wyłącznie jako tło unijne. Zakaz zastępowania CPI przez HICP.")
        lines.append("2. SEKCJA 'Praca i Zarobki' (perspektywa Kowalskiego):")
        lines.append("   - Głównym wskaźnikiem MUSI być bezrobocie rejestrowane GUS (PL_UNEMPLOYMENT_REGISTERED_RATE).")
        lines.append("   - Bezrobocie BAEL/LFS jest wyłącznie uzupełnieniem ankietowym. Zakaz zastępowania bezrobocia rejestrowanego przez BAEL.")
        lines.append("   - Jeśli bezrobocie rejestrowane pochodzi z szeregu rocznego BDL, podaj je jako roczną bazę odniesienia na koniec roku.")
        lines.append("3. SEKCJA 1 ('Analiza Trendów') ORAZ SEKCJA 5 ('Podsumowanie'):")
        lines.append("   - Wzrost PKB r/r (PL_GDP_YOY) jest nadrzędny nad PKB kw/kw i wolumenem w mln EUR.")
        lines.append("   - ZAKAZ nazywania pojedynczego odczytu z jednego dnia trendem (dotyczy zwłaszcza kursów EUR/PLN i USD/PLN).")
        lines.append("4. STOPA REFERENCYJNA NBP:")
        lines.append("   - Podawaj ją jako obecnie obowiązującą stawkę NBP wraz z datą decyzji RPP. Nie sugeruj, że jest to odczyt nieaktualny.")

        if missing_core:
            lines.append(f"\nUWAGA — BRAKUJĄCE WSKAŹNIKI KLUCZOWE: {', '.join(missing_core)}.")
            lines.append("W raporcie jawnie odnotuj brak bieżących potwierdzonych odczytów tych wskaźników. ZAKAZ ich zmyślania!")

        if archival_core:
            lines.append(f"\nUWAGA — ODCZYTY ARCHIWALNE: {', '.join(archival_core)}.")
            lines.append("Dozwolone wyłącznie jako historyczna baza odniesienia z podaniem okresu. Zakaz prezentacji jako stanu bieżącego.")

        return "\n".join(lines)
