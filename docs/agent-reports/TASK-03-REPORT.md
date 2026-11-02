# TASK-03 — raport Antigravity / Codex

**Status:** `READY_FOR_REVIEW` (Aktualizacja po Code Review: CHANGES REQUESTED)  
**Branch:** `design/03-data-contract`  
**Commit SHA:** `TO_BE_UPDATED`  
**PR:** `https://github.com/maciejkubek-maker/polish-economy-agent/pull/3`  
**Data:** 2026-11-02  

---

## Odpowiedź na uwagi Code Review (CHANGES REQUESTED)

Wszystkie 6 punktów zgłoszonych w recenzji zostało w pełni wdrożonych i zweryfikowanych testami:

1. **Ujednolicenie bilansu grup migracji i potwierdzenie 75 unikalnych legacy ID:**
   - Poprawiono nagłówki grup i sumy kontrolne w [`docs/MIGRATION_V2_PLAN.md`](file:///E:/Programy/PycharmProjects/polish-economy-agent/docs/MIGRATION_V2_PLAN.md):
     - **Grupa 1 (Jednoznaczne):** **51 rekordów** (IDs m.in. 1, 2, 5, 7, 10, 11, 12, 13, 21, 22, 27, 29, 31, 37, 39, 40, 41, 42, 43, 44, 47, 50, 52, 53, 54, 55, 56, 57, 59, 60, 61, 62, 63, 66, 67, 68, 70, 71, 72, 73, 74, 75).
     - **Grupa 2 (Synonimy po weryfikacji):** **17 rekordów** (IDs: 6, 9, 14, 18, 20, 28, 30, 34, 36, 45, 46, 48, 49, 51, 58, 64, 69).
     - **Grupa 3 (Przypadki sporne / konflikty):** **7 rekordów** (IDs: 3, 8, 32, 33, 35, 38, 65).
     - **Suma całkowita:** `51 + 17 + 7 = 75` unikalnych identyfikatorów od 1 do 75. Potwierdzone testami regresyjnymi.
2. **Rozstrzyganie konfliktu PKB r/r za II kw. 2026 (3,90% vs 3,8%):**
   - Wyeliminowano nieuzasadnione założenie, że 3,8% jest nowszą rewizją.
   - Zgodnie z zasadą braku zgadywania: oba odczyty trafiają do `extracted_candidates`, w mapie migracji otrzymują status `MIGRATED_CONFLICT`, a w `quality_events` generowany jest incydent `RULE_SOURCE_DISCREPANCY`. Żadna wartość nie zostaje arbitralnie zatwierdzona jako jedyna prawda w `observations` bez potwierdzonego źródłowo znacznika czasu publikacji (release bulletin).
3. **Rzeczywiście egzekwowalna historia append-only w SQLite v2:**
   - Z tabeli `observations` usunięto mutowalną kolumnę `is_latest` (której aktualizacja wymagałaby `UPDATE` na wierszach historycznych).
   - Wdrożono triggery SQLite: `trg_observations_prevent_update` oraz `trg_observations_prevent_delete`, które rzucają błąd przy jakiejkolwiek próbie modyfikacji lub usunięcia wiersza z `observations`.
   - Wprowadzono odrębny mechanizm ustalania bieżącej wersji:
     - Zmaterializowaną tabelę wskaźników `current_observations` (aktualizowaną triggerem po `INSERT` zweryfikowanej obserwacji).
     - Deklaratywny widok SQL `v_latest_observations` oparty o funkcję `ROW_NUMBER() OVER (...)`.
4. **Rozbudowa testów walidacji i procedury migracji:**
   - W [`tests/test_schema_v2_design.py`](file:///E:/Programy/PycharmProjects/polish-economy-agent/tests/test_schema_v2_design.py) dodano testy:
     - `test_observations_strict_append_only_triggers`: dowód, że UPDATE i DELETE są blokowane przez triggery.
     - `test_current_observations_pointer_and_view`: dowód prawidłowego wyznaczania nowej wersji bez mutacji wiersza pierwotnego.
     - `test_dry_run_migration_full_pipeline_simulation`: pełna symulacja potoku migracyjnego na rzeczywistych danych legacy (read-only): przetworzenie 75 wskaźników, 10 źródeł, 6 raportów, zarejestrowanie 91 powiązań w `legacy_migration_map`, wykrycie konfliktu PKB i flagi PENDING dla bezrobocia r/r.
     - `test_dry_run_migration_idempotency`: potwierdzenie idempotencji procedury mapowania.
   - Liczba testów w zestawie wzrosła z 5 do 9 (łącznie 61 testów w repozytorium, 100% PASSED).
5. **Uzupełnienie katalogu API o dowody weryfikacji i parametry:**
   - [`docs/API_SOURCE_CATALOG.md`](file:///E:/Programy/PycharmProjects/polish-economy-agent/docs/API_SOURCE_CATALOG.md) uzupełniono o:
     - **NBP Kursy walut:** dowód odpowiedzi JSON z `https://api.nbp.pl/api/exchangerates/rates/A/{code}/?format=json`.
     - **NBP Stopy procentowe:** dowód braku w REST (HTTP 404 dla `/api/stopy/`), potwierdzona struktura pliku XML `static.nbp.pl/dane/stopy/stopy_procentowe.xml` (kod `<pozycja id="ref".../>`, jednostka `PCT`).
     - **Eurostat:** dokładne parametry i filtry wymiarów dla `prc_hicp_manr` (`coicop=CP00`, `unit=RCH_A`), `une_rt_m` (`s_adj=SA`, `unit=PC_ACT`) oraz `namq_10_gdp` (`na_item=B1GQ`, `unit=CLV10_MEUR` / `%`).
     - **GUS:** wyjaśnienie struktury DBW/BDL/dane.gov.pl i uzasadnienie statusu `REQUIRES_VARIABLE_MAPPING`.
6. **Aktualizacja rejestru decyzji i raportu:**
   - Zaktualizowano DR-001, DR-002, DR-003 w [`docs/agent-reports/DECISION_REQUESTS.md`](file:///E:/Programy/PycharmProjects/polish-economy-agent/docs/agent-reports/DECISION_REQUESTS.md) oraz niniejszy raport.

---

## Zmienione pliki

| Ścieżka | Opis zmian |
|---|---|
| `docs/SCHEMA_V2_PROPOSAL.md` | Dodano opis egzekwowania append-only triggerami, pointer tabeli `current_observations`, widoku `v_latest_observations` oraz zasadę braku zgadywania dla konfliktów. |
| `docs/sql/schema_v2.sql` | Zaktualizowano DDL: triggery blokujące UPDATE/DELETE, tabela `current_observations`, trigger aktualizujący wskaźniki, widok `v_latest_observations`. |
| `docs/MIGRATION_V2_PLAN.md` | Poprawiono bilans grup (51 + 17 + 7 = 75), potwierdzono 75 unikalnych ID, usunięto arbitralne pierwszeństwo PKB 3,8% nad 3,90%. |
| `docs/API_SOURCE_CATALOG.md` | Dodano dowody odpowiedzi (JSON, XML), parametry wymiarów Eurostat (HICP, une_rt_m, namq_10_gdp), dowód 404 dla stóp w REST NBP. |
| `tests/test_schema_v2_design.py` | Rozbudowano z 5 do 9 testów: testy triggerów append-only, testy pointerów i widoku, pełna symulacja potoku migracyjnego (91 encji w mapie). |
| `docs/agent-reports/DECISION_REQUESTS.md` | Zaktualizowano wnioski DR-001 (append-only), DR-002 (brak zgadywania w PKB) oraz DR-003 (XML stóp NBP). |
| `docs/agent-reports/TASK-03-REPORT.md` | Niniejszy zaktualizowany raport wykonawczy z odpowiedziami na review. |

---

## Testy i kontrole

| Polecenie | Status PASSED/FAILED/NOT_RUN | Wynik |
|---|---|---|
| `uv run pytest -v` | **PASSED** | 61 passed w 3.76s (100% testów zielonych, brak internetu, brak płatnych API). |
| `uv run pytest -v tests/test_schema_v2_design.py` | **PASSED** | 9 passed w 0.14s (triggery append-only, pointery, widok, symulacja potoku 75/75, bilans mapy 91/91). |

---

## Stan danych i bezpieczeństwa

- Czy zmodyfikowano `instance/economy_agent.db`? **NIE**. Baza produkcyjna pozostała całkowicie nienaruszona (75 wskaźników, 10 źródeł, 6 raportów, 73 728 bajtów). Potwierdzone testem `test_legacy_database_is_untouched_after_tests`.
- Czy uruchomiono migrację na bazie produkcyjnej? **NIE**. Wszelkie testy procedury wykonano w pamięci (`:memory:`) oraz na odczycie `mode=ro`.
- Czy były wywołania płatnych API? **NIE**. Wszystkie testy wykonano offline.
- Czy usunięto Tavily, Gemini lub GPT? **NIE**. Wszystkie trzy komponenty są w pełni zintegrowane w planowanej architekturze.

---

## JSON status

```json
{
  "task_id": "TASK-03",
  "status": "READY_FOR_REVIEW",
  "branch": "design/03-data-contract",
  "commit_sha": "TO_BE_UPDATED",
  "pull_request": "https://github.com/maciejkubek-maker/polish-economy-agent/pull/3",
  "tests": {"status": "PASSED", "passed": 61, "failed": 0},
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
