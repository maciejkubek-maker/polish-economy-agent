# TASK-04 — raport Antigravity / Codex

**Status:** `DONE`  
**Branch:** `feature/data-platform-v2`  
**Commit SHA:** `PENDING_COMMIT_SHA`  
**PR:** `https://github.com/maciejkubek-maker/polish-economy-agent/pull/4`  
**Data:** 2026-11-02  

## Co wykonałem

Zaimplementowałem produkcyjnej jakości migrator danych ze starszej bazy SQLite v1 do modelu SQLite v2 ([`modules/migrator.py`](file:///E:/Programy/PycharmProjects/polish-economy-agent/modules/migrator.py)) wraz z pełnym zestawem testów regresyjnych, integralności i bezpieczeństwa ([`tests/test_migrator.py`](file:///E:/Programy/PycharmProjects/polish-economy-agent/tests/test_migrator.py)).

### Główne elementy implementacji:
1. **Ochrona bazy źródłowej:**
   - Baza legacy (`instance/economy_agent.db`) jest otwierana wyłącznie przez URI SQLite w trybie READ-ONLY: `file:...mode=ro`.
   - Zaimplementowano bezwzględny zakaz nadpisywania bazy źródłowej (próba wskazania ścieżki docelowej równej źródłowej rzuca `ValueError`).
   - Aplikacja produkcyjna (`app.py`, `modules/database.py`) **nie została** przełączona na bazę v2.
2. **Bezstratny transfer 75/10/6 i audytowalność:**
   - 10 źródeł z `trusted_sources` przeniesiono do `source_registry`.
   - 6 raportów z `generated_reports` przeniesiono do `reports` z zachowaniem oryginalnego `content_markdown`, znormalizowaną datą ISO `YYYY-MM-DD` (`report_date`) oraz 64-znakowym skrótem SHA-256 (`data_snapshot_hash`).
   - 75 wskaźników z `collected_indicators` przeniesiono do `source_evidence` i `extracted_candidates`.
   - 91 powiązań zarejestrowano w `legacy_migration_map`.
3. **Prawidłowe pochodzenie źródeł (provenance):**
   - Wskaźniki NBP (stopy referencyjne oraz inflacja bazowa: IDs 4, 45, 58, 64, 69) precyzyjnie przypisano do `SRC_LEGACY_2` (NBP), a wskaźniki GUS do `SRC_LEGACY_1`. Wyeliminowano arbitralne przypisywanie wszystkich rekordów do GUS.
   - Wszystkie 75 wpisów dowodowych w `source_evidence` posiada deterministyczny skrót SHA-256 (`content_hash`) wyliczony ze wszystkich pól surowego rekordu (wyeliminowano atrapy `hash_{id}`).
4. **Brak zgadywania w rozstrzyganiu konfliktów:**
   - Rozbieżność PKB r/r za II kw. 2026 (3.90% vs 3.8%) została oznaczona statusem `MIGRATED_CONFLICT` z wpisem zdarzenia w `quality_events` (`RULE_SOURCE_DISCREPANCY`).
   - Błędna etykieta „Stopa bezrobocia r/r” została oznaczona jako `MIGRATED_PENDING` z wpisem w `quality_events` (`RULE_MISLABELED_INDICATOR_NAME`).
5. **Transakcyjność i idempotencja:**
   - Pełna transakcja SQLite z automatycznym rollbackiem i usuwaniem nowo tworzonego pliku w razie błędu.
   - Bezpieczne wielokrotne uruchomienie na tej samej bazie docelowej nie tworzy żadnych duplikatów.
6. **Interfejs CLI:**
   - Domyślny tryb `--dry-run` (symulacja w pamięci bez tworzenia plików).
   - Jawny tryb zapisu `--apply --target <ścieżka>`.
   - Opcja weryfikacji głębokiej spójności `--verify --target <ścieżka>`.

---

## Zmienione pliki

| Ścieżka | Opis |
|---|---|
| `modules/migrator.py` | Nowy moduł produkcyjnej migracji SQLite v1 -> v2 z obsługą CLI, transakcji, dry-run i weryfikacji. |
| `tests/test_migrator.py` | 12 nowych testów jednostkowych i integracyjnych pokrywających wszystkie wymagania TASK-04. |
| `.gitignore` | Dodano ignorowanie lokalnych docelowych baz testowych (`instance/*_v2.db`, `instance/test_*.db`). |
| `docs/agent-reports/TASK-04-REPORT.md` | Niniejszy raport wykonawczy z realizacji zadania. |

---

## Testy i kontrole

| Polecenie | Status PASSED/FAILED/NOT_RUN | Wynik |
|---|---|---|
| `uv run pytest -v` | **PASSED** | 76 passed w 4.88s (100% testów zielonych, brak internetu, brak płatnych API). |
| `uv run pytest tests/test_migrator.py -v` | **PASSED** | 12 passed w 1.92s (dry-run, apply, głębokie porównanie 75 wskaźników, daty ISO, hashe SHA-256, źródła NBP, idempotencja, zakaz nadpisywania, rollback transakcji, CLI). |
| `uv run python -m modules.migrator` | **PASSED** | Domyślny dry-run wykonany w 0.007s, bilans 75/10/6/91, brak tworzenia plików. |
| `uv run python -m modules.migrator --apply --target instance/test_v2.db` | **PASSED** | Testowy fizyczny zapis bazy docelowej (75/10/6/91). |
| `uv run python -m modules.migrator --verify --target instance/test_v2.db` | **PASSED** | Weryfikacja głęboka: 100% zgodności pól i relacji (usunięto plik testowy po zakończeniu). |

---

## Stan danych i bezpieczeństwa

- Czy zmodyfikowano `instance/economy_agent.db`? **NIE**. Baza produkcyjna pozostała całkowicie nienaruszona (dokładnie 73 728 bajtów, 75 wskaźników, 10 źródeł, 6 raportów). Potwierdzone testami automatycznymi.
- Czy uruchomiono migrację na bazie produkcyjnej? **NIE**. Migrator przetestowano w pamięci oraz na osobnych plikach tymczasowych.
- Czy były wywołania płatnych API? **NIE**. Wszystkie testy wykonano offline.
- Czy przełączono aplikację na SQLite v2? **NIE**. Zgodnie z wytycznymi aplikacja nadal działa na dotychczasowym interfejsie.

---

## Ryzyka / regresje / ograniczenia

- Migracja dotyczy tabel archiwalnych: wskaźniki sporne (PKB 3.8% vs 3.90%) oraz niejednoznaczne (stopa bezrobocia r/r) pozostają w warstwie kandydatów ze statusem `CONFLICT`/`PENDING` i wymagają rozstrzygnięcia przed publikacją w tabeli `observations`.

---

## Decyzje wymagane

- **BRAK BLOKAD** dla przejścia do TASK-05. Zgodnie z nową zasadą pracy nie zatrzymujemy się na merge i natychmiast rozpoczynamy implementację konektorów oficjalnych API.

---

## Następny krok

- Przejście do **TASK-05 — Oficjalne API danych ekonomicznych**: implementacja konektorów dla NBP (REST kursy EUR/USD, XML stopy referencyjne), Eurostat (HICP, bezrobocie, PKB) oraz GUS (ustalenie rzeczywistych identyfikatorów zmiennych).

---

## JSON status

```json
{
  "task_id": "TASK-04",
  "status": "DONE",
  "branch": "feature/data-platform-v2",
  "commit_sha": "PENDING_COMMIT_SHA",
  "pull_request": "https://github.com/maciejkubek-maker/polish-economy-agent/pull/4",
  "tests": {"status": "PASSED", "passed": 76, "failed": 0},
  "files_changed": [
    "modules/migrator.py",
    "tests/test_migrator.py",
    ".gitignore",
    "docs/agent-reports/TASK-04-REPORT.md"
  ],
  "risks": [],
  "requires_decision": []
}
```
