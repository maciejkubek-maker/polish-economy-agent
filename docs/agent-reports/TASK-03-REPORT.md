# TASK-03 — raport Antigravity / Codex

**Status:** `READY_FOR_REVIEW`  
**Branch:** `design/03-data-contract`  
**Commit SHA:** `TO_BE_UPDATED`  
**PR:** `TO_BE_UPDATED`  
**Data:** 2026-11-02  

## Co wykonałem

1. **Przygotowanie środowiska i gałęzi:**
   - Potwierdzono poprawne scalenie PR #1 i PR #2 do gałęzi `main` (commit bazowy `95c8bc28c8f8c38b54f317d3eca7e7c2ca484ff6`).
   - Utworzono nową gałąź projektową `design/03-data-contract`.
   - Zapoznano się ze wszystkimi dokumentami wytycznymi (`AGENTS.md`, `docs/ARCHITECTURE.md`, `docs/DATA_CONTRACT.md`, `docs/SOURCE_POLICY.md`, `docs/MIGRATION.md`, `tasks/TASK_03_SCHEMA_DESIGN.md`).

2. **Projekt Schematu SQLite v2 ([`docs/SCHEMA_V2_PROPOSAL.md`](file:///E:/Programy/PycharmProjects/polish-economy-agent/docs/SCHEMA_V2_PROPOSAL.md) oraz [`docs/sql/schema_v2.sql`](file:///E:/Programy/PycharmProjects/polish-economy-agent/docs/sql/schema_v2.sql)):**
   - Zaprojektowano 11 tabel w trójwarstwowym modelu danych:
     - **Warstwa Ingestion (RAW):** `source_registry`, `data_series`, `ingestion_runs`, `source_evidence`.
     - **Warstwa Ekstrakcji (NORMALIZED):** `extracted_candidates`.
     - **Warstwa Walidacji (VALIDATED):** `indicator_catalog`, `indicator_aliases`, `observations` (bezwzględnie **append-only** z wersjonowaniem rewizji `FLASH`, `PRELIMINARY`, `FINAL`, `REVISED`), `quality_events` (audyt odrzuceń i konfliktów), `reports` (z powiązaniem do hasha stanu danych), `legacy_migration_map`.
   - Zdefiniowano standard reprezentacji wartości liczbowych (`value_decimal` jako kanoniczny `TEXT` parsowany przez `decimal.Decimal` z eliminacją błędów float IEEE 754).
   - Wdrożono rygor czasowy: rozdzielenie granic okresu statystycznego (`period_start`, `period_end`, `frequency`) od czasu publikacji (`published_at_utc`) oraz czasu pobrania (`retrieved_at_utc`).

3. **Projekt Bezstratnej Migracji Danych Legacy ([`docs/MIGRATION_V2_PLAN.md`](file:///E:/Programy/PycharmProjects/polish-economy-agent/docs/MIGRATION_V2_PLAN.md)):**
   - Dokonano pełnej inwentaryzacji 75 rekordów w `collected_indicators`, 10 rekordów w `trusted_sources` i 6 w `generated_reports`.
   - Sklasyfikowano 24 warianty nazw tekstowych na 3 grupy analityczne (jednoznaczne, synonimy, przypadki sporne).
   - Zidentyfikowano kluczowe anomalie i konflikty:
     - Konflikt rewizyjny PKB r/r za II kw. 2026: 3,90% (szacunek flash) vs 3,8% (szacunek wstępny).
     - Błędna etykieta „r/r” nadana przez GPTAgent poziomowi stopy bezrobocia rejestrowanego (6,1% i 5,8%).
     - Odrębna metodyka napływu bezrobotnych (`PL_UNEMPLOYMENT_NEW_REGISTERED_COUNT` - 93,0 tys.).
   - Zaprojektowano procedurę Zero Data Loss: 100% danych legacy trafia do warstwy dowodowej i kandydatów, a statusy weryfikacji są precyzyjnie przypisywane bez zgadywania.
   - **Nie wykonano żadnych operacji zapisu na produkcyjnej bazie `instance/economy_agent.db`.**

4. **Katalog Źródeł API i Weryfikacja Techniczna ([`docs/API_SOURCE_CATALOG.md`](file:///E:/Programy/PycharmProjects/polish-economy-agent/docs/API_SOURCE_CATALOG.md)):**
   - Zbadano i udokumentowano oficjalne interfejsy GUS, NBP i Eurostat:
     - **NBP Kursy Walut:** potwierdzone otwarte REST API (`api.nbp.pl/api/exchangerates/`) — status `VERIFIED`.
     - **NBP Stopy Procentowe:** wykazano, że `api.nbp.pl` **nie posiada** endpointu dla stóp; potwierdzono oficjalny plik maszynowy XML (`static.nbp.pl/dane/stopy/stopy_procentowe.xml`) — status `VERIFIED_STATIC_XML`.
     - **GUS (CPI, PKB, bezrobocie, wynagrodzenia, produkcja):** potwierdzono platformy DBW (`api-dbw.stat.gov.pl`), BDL (`bdl.stat.gov.pl/api/v1/`) i SDP; oznaczono status `CONFIRMED_API_REQUIRES_VARIABLE_MAPPING` ze względu na wymóg powiązania identyfikatorów zmiennych.
     - **Eurostat:** potwierdzone Statistics API 1.0 (JSON-stat 2.0) dla HICP (`prc_hicp_manr`), bezrobocia BAEL (`une_rt_m`) oraz PKB (`namq_10_gdp`) — status `VERIFIED`.
   - Zdefiniowano rolę **Tavily Web Search** (szybkie szacunki flash, komunikaty decydentów, wskaźniki bez otwartego API jak PMI S&P Global) oraz **Gemini i GPT** (dual-agent ekstrakcja i niezależna synteza wyłącznie na zweryfikowanych danych).

5. **Rejestr Decyzji Technicznych ([`docs/agent-reports/DECISION_REQUESTS.md`](file:///E:/Programy/PycharmProjects/polish-economy-agent/docs/agent-reports/DECISION_REQUESTS.md)):**
   - Zarejestrowano wnioski decyzyjne DR-001 (reprezentacja liczb dziesiętnych), DR-002 (rozstrzygnięcie konfliktów rewizyjnych w legacy) oraz DR-003 (oficjalne źródło XML dla stóp NBP).

6. **Automatyczne Testy Offline ([`tests/test_schema_v2_design.py`](file:///E:/Programy/PycharmProjects/polish-economy-agent/tests/test_schema_v2_design.py)):**
   - Utworzono 5 nowych testów sprawdzających poprawność DDL w pamięci, więzy kluczy obcych, precyzję `decimal.Decimal`, 100% pokrycia 75 rekordów legacy oraz nienaruszalność oryginalnego pliku bazy SQLite.
   - Wszystkie 57 testów w repozytorium zakończyło się wynikiem PASSED.

---

## Zmienione pliki

| Ścieżka | Opis |
|---|---|
| `docs/SCHEMA_V2_PROPOSAL.md` | Pełna specyfikacja modelu danych SQLite v2, architektura warstwowa, słownik kolumn i reguły integralności. |
| `docs/MIGRATION_V2_PLAN.md` | Strategia bezstratnej migracji 75 rekordów wskaźników, analiza 24 wariantów nazw, rozstrzygnięcie konfliktów i plan rollback. |
| `docs/API_SOURCE_CATALOG.md` | Katalog wskaźników MVP, instytucji, potwierdzonych endpointów (GUS, NBP, Eurostat) oraz rola Tavily/Gemini/GPT. |
| `docs/sql/schema_v2.sql` | Czysty, testowalny skrypt DDL definiujący 11 tabel, klucze obce, indeksy i ograniczenia. |
| `tests/test_schema_v2_design.py` | 5 automatycznych testów offline weryfikujących DDL, decimal parsing i pełne mapowanie legacy (75/75). |
| `docs/agent-reports/DECISION_REQUESTS.md` | Rejestr decyzji technicznych (DR-001, DR-002, DR-003) oczekujących na review. |
| `docs/agent-reports/TASK-03-REPORT.md` | Niniejszy raport wykonawczy z realizacji TASK-03. |

---

## Testy i kontrole

| Polecenie | Status PASSED/FAILED/NOT_RUN | Wynik |
|---|---|---|
| `uv run pytest -v` | **PASSED** | 57 passed w 4.65s (100% testów zielonych: 52 dotychczasowe testy regresyjne i bezpieczeństwa + 5 nowych testów architektury v2). |
| `uv run pytest -v tests/test_schema_v2_design.py` | **PASSED** | 5 passed w 0.05s (testy DDL, więzów, decimal i bilansu migracji legacy). |

---

## Stan danych i bezpieczeństwa

- Czy zmodyfikowano `instance/economy_agent.db`? **NIE**. Baza produkcyjna pozostała całkowicie nienaruszona (75 wskaźników, 10 źródeł, 6 raportów, 73 728 bajtów). Potwierdzone testem `test_legacy_database_is_untouched_after_tests`.
- Czy uruchomiono migrację na bazie produkcyjnej? **NIE**. Opracowano wyłącznie projekt i plan procedury; wykonano testy w pamięci (`:memory:`) oraz w trybie odczytu (`file:...mode=ro`).
- Czy były wywołania płatnych API? **NIE**. Wszystkie analizy, kwerendy dokumentacyjne i testy zrealizowano całkowicie offline lub w oparciu o publiczną dokumentację.
- Czy usunięto Tavily, Gemini lub GPT? **NIE**. Wszystkie trzy komponenty zostały w pełni uwzględnione jako integralne elementy architektury.

---

## Ryzyka / regresje / ograniczenia

1. **Dynamiczne mapowanie identyfikatorów zmiennych GUS (DBW/BDL):** API GUS nie posiada płaskiego słownika wskaźników makro, lecz hierarchię obszarów, przekrojów i zmiennych. W kolejnym etapie należy zaimplementować moduł discovery lub zasilić `data_series` sprawdzonymi ID.
2. **Format odpowiedzi stóp procentowych NBP:** Stopy NBP są publikowane w XML (`static.nbp.pl`). Do ich obsługi należy wykorzystać wbudowany w standardową bibliotekę Pythona moduł `xml.etree.ElementTree` bez dodawania zewnętrznych bibliotek.
3. **Konflikt szacunku PKB (3,90% vs 3,8%):** Wymaga zatwierdzenia decyzji DR-002 przez właściciela (rekomendacja: model wersjonowany `is_latest=1` dla szacunku wstępnego, `SUPERSEDED` dla szacunku flash).

---

## Decyzje wymagane (Decision Requests)

- **DR-001:** Zatwierdzenie kanonicznego typu `TEXT` z walidacją `decimal.Decimal` dla wartości numerycznych.
- **DR-002:** Zatwierdzenie procedury wersjonowania konfliktów i rewizji danych legacy w `observations`.
- **DR-003:** Zatwierdzenie oficjalnego pliku XML `static.nbp.pl` jako źródła stóp procentowych NBP.

---

## Następny sugerowany krok

1. Przegląd i zatwierdzenie projektu (code review przez ChatGPT, decyzje właściciela).
2. Po zatwierdzeniu: **TASK-04** — Implementacja konektorów API (NBP, Eurostat, GUS) oraz parserów XML/JSON w trybie TDD (zgodnie z `docs/API_SOURCE_CATALOG.md`).

---

## JSON status

```json
{
  "task_id": "TASK-03",
  "status": "READY_FOR_REVIEW",
  "branch": "design/03-data-contract",
  "commit_sha": "TO_BE_UPDATED",
  "pull_request": "TO_BE_UPDATED",
  "tests": {"status": "PASSED", "passed": 57, "failed": 0},
  "files_changed": [
    "docs/SCHEMA_V2_PROPOSAL.md",
    "docs/MIGRATION_V2_PLAN.md",
    "docs/API_SOURCE_CATALOG.md",
    "docs/sql/schema_v2.sql",
    "tests/test_schema_v2_design.py",
    "docs/agent-reports/DECISION_REQUESTS.md",
    "docs/agent-reports/TASK-03-REPORT.md"
  ],
  "risks": [
    "Hierarchia zmiennych w GUS DBW/BDL wymaga wstępnego zasilenia ID zmiennych",
    "Stopy NBP wymagają dedykowanego parsera XML"
  ],
  "requires_decision": [
    "DR-001",
    "DR-002",
    "DR-003"
  ]
}
```
