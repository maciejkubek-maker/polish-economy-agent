# TASK-03 — raport Antigravity / Codex

**Status:** `READY_FOR_REVIEW` (Wdrożenie poprawek z code review: out-of-order import, źródła i hashe)  
**Branch:** `design/03-data-contract`  
**Commit SHA:** `f0fb7c01f423cc410c2352e22e49def96a02e81e`  
**PR:** `https://github.com/maciejkubek-maker/polish-economy-agent/pull/3`  
**Data:** 2026-11-02  

---

## Odpowiedź na uwagi Code Review

Wszystkie 3 uwagi z ostatniego przeglądu kodu zostały w pełni wdrożone i zweryfikowane automatycznymi testami offline:

1. **Usunięcie stałej daty `'2026-09-18'` i użycie historycznej `report_date`:**
   - W procedurze migracji [`_execute_dry_run_migration_pass`](file:///E:/Programy/PycharmProjects/polish-economy-agent/tests/test_schema_v2_design.py) usunięto zahardkodowaną datę `'2026-09-18'`.
   - Data formalna raportu jest teraz dynamicznie pobierana z historycznej kolumny `report_date` i normalizowana do formatu ISO `YYYY-MM-DD` (`_normalize_report_date`).
   - Zweryfikowano dedykowanym testem `test_dry_run_migration_reports_historical_date_and_deterministic_hash`.

2. **Deterministyczne skróty SHA-256 oraz precyzyjne przypisanie źródeł zamiast `SRC_LEGACY_1`:**
   - **Raporty:** wyeliminowano atrapę `'legacy_hash'` — kolumna `data_snapshot_hash` otrzymuje pełny 64-znakowy deterministyczny skrót SHA-256 wyliczony z danych wejściowych raportu.
   - **Dowody źródłowe (`source_evidence`):** wyeliminowano fikcyjny format `f"hash_{i_id}"` — `content_hash` jest wyliczany jako deterministyczny skrót SHA-256 ze wszystkich pól rekordu źródłowego.
   - **Przypisanie źródeł:** usunięto sztywne przypisywanie `'SRC_LEGACY_1'` dla każdego rekordu. Wprowadzono resolver `_resolve_legacy_source_id`: wskaźniki pochodzące z NBP (stopy referencyjne ID 4 oraz inflacja bazowa IDs 45, 58, 64, 69) otrzymują precyzyjny `source_id = 'SRC_LEGACY_2'`, a wskaźniki GUS otrzymują `SRC_LEGACY_1`.
   - Zweryfikowano dedykowanym testem `test_dry_run_migration_evidence_source_assignment_and_deterministic_hash`.

3. **Ujednolicenie wyboru obserwacji w `current_observations` i `v_latest_observations` (w tym dla importu nieuporządkowanego):**
   - Rozwiązano problem rozbieżności przy imporcie out-of-order (nieuporządkowanym chronologicznie).
   - W schemacie [`docs/sql/schema_v2.sql`](file:///E:/Programy/PycharmProjects/polish-economy-agent/docs/sql/schema_v2.sql):
     - Do tabeli `current_observations` dodano kolumnę `observed_at_utc TIMESTAMP NOT NULL`.
     - W triggerze `trg_observations_update_current` zdefiniowano pełny leksykograficzny warunek aktualizacji wskaźnika:
       ```sql
       WHERE 
           excluded.version_number > current_observations.version_number
           OR (
               excluded.version_number = current_observations.version_number
               AND (
                   excluded.observed_at_utc > current_observations.observed_at_utc
                   OR (
                       excluded.observed_at_utc = current_observations.observed_at_utc
                       AND excluded.observation_id > current_observations.observation_id
                   )
               )
           );
       ```
     - W widoku analitycznym `v_latest_observations` zastosowano tożsamy porządek:
       ```sql
       ORDER BY o.version_number DESC, o.observed_at_utc DESC, o.observation_id DESC
       ```
   - Gwarantuje to absolutną zgodność matematyczną tabeli `current_observations` i widoku `v_latest_observations` w każdym scenariuszu: importu chronologicznego, odwrotnego (nowsze wersje/daty przed starszymi) oraz losowego.
   - Dodano dedykowany test `test_out_of_order_import_consistency_between_current_observations_and_view` symulujący wszystkie scenariusze odwróconego importu.

---

## Zmienione pliki

| Ścieżka | Opis zmian |
|---|---|
| `docs/SCHEMA_V2_PROPOSAL.md` | Zaktualizowano opis sekcji 3.9: determinizm wyboru i odporność na kolejność importu out-of-order. |
| `docs/sql/schema_v2.sql` | Dodano kolumnę `observed_at_utc` do `current_observations`, zaktualizowano trigger i widok o spójne sortowanie leksykograficzne. |
| `docs/MIGRATION_V2_PLAN.md` | Zaktualizowano sekcję 3.2 i dodano 3.3: dynamiczna `report_date`, deterministyczny SHA-256 dla raportów i dowodów, mapowanie NBP vs GUS. |
| `tests/test_schema_v2_design.py` | Zaktualizowano procedurę migracji i rozszerzono zestaw testów do 12 (dodano testy out-of-order importu, dat raportów, hashy SHA-256 i źródeł NBP). |
| `docs/agent-reports/TASK-03-REPORT.md` | Niniejszy zaktualizowany raport wykonawczy z opisem wdrożonych poprawek. |

---

## Testy i kontrole

| Polecenie | Status PASSED/FAILED/NOT_RUN | Wynik |
|---|---|---|
| `uv run pytest -v` | **PASSED** | 64 passed w 3.98s (100% testów zielonych, brak internetu, brak płatnych API). |
| `uv run pytest -v tests/test_schema_v2_design.py` | **PASSED** | 12 passed w 0.22s (out-of-order import, triggery append-only, spójność widoku, symulacja potoku 75/75, pełna idempotencja 75/10/6, hashe SHA-256, źródła NBP). |

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
  "commit_sha": "f0fb7c01f423cc410c2352e22e49def96a02e81e",
  "pull_request": "https://github.com/maciejkubek-maker/polish-economy-agent/pull/3",
  "tests": {"status": "PASSED", "passed": 64, "failed": 0},
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
