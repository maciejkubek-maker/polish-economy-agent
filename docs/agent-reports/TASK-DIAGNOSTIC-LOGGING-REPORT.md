# TASK-DIAGNOSTIC-LOGGING — raport Codex

**Status:** `DONE`  
**Branch:** `feature/diagnostic-logging`  
**Commit SHA:** `bc02a25f8a6ee0ada9b1c8b55a35eaa6c71532db`  
**PR:** https://github.com/maciejkubek-maker/polish-economy-agent/pull/5  
**Data:** `2026-11-04`

## DONE — wykonany zakres

- Dodano trwały, rotowany dziennik `instance/logs/agent.log` oparty wyłącznie o standardowy moduł `logging`.
- Dodano atomowy zapis `instance/logs/last_run.json` dla przebiegów `COMPLETED`, `PARTIAL` i `FAILED`.
- Podsumowanie rozróżnia `LIVE_AI_VALIDATED`, `GPT_API_ERROR`, `GPT_VALIDATION_REJECTED` oraz `OFFLINE_DEMO`, zachowując konkretną, zredagowaną przyczynę fallbacku lub awarii.
- Rejestrowane są status i liczba wyników Tavily, liczba zweryfikowanych wskaźników, brakujące wskaźniki (w tym `PL_CPI_YOY`) oraz identyfikator raportu.
- Dodano redakcję kluczy, tokenów, nagłówków autoryzacyjnych, pełnych promptów i odpowiedzi modelu.
- Komunikat aplikacji nie deklaruje sukcesu, gdy wynik potoku ma status `FAILED`.
- Dodano sześć testów diagnostyki: sukces GPT, błąd API, odrzucenie walidatora, brak CPI, awaria potoku i brak wycieku sekretów.
- Zaktualizowano angielską i polską część README.

## Zmienione pliki

| Ścieżka | Opis |
|---|---|
| `.gitignore` | Ignorowanie lokalnego `instance/logs/`. |
| `README.md` | Dokumentacja plików diagnostycznych EN/PL i aktualny wynik testów. |
| `app.py` | Poprawny komunikat końcowy dla nieudanego potoku v2. |
| `modules/diagnostics.py` | Rotacja logu, atomowy JSON, redakcja sekretów i katalog oczekiwanych wskaźników. |
| `modules/evaluator.py` | Strukturalna diagnostyka wyniku GPT i walidatora. |
| `modules/pipeline_v2.py` | Zapis diagnostyki na ścieżce sukcesu, częściowego powodzenia i awarii. |
| `tests/test_diagnostics.py` | Sześć wymaganych scenariuszy testowych. |

## Testy i kontrole

| Polecenie | Status | Faktyczny wynik |
|---|---|---|
| `uv sync --group dev` | `PASSED` | 63 pakiety rozwiązane, 61 zainstalowanych w izolowanym worktree; bez zmian zależności projektu. |
| `uv run pytest tests/test_diagnostics.py -q` | `PASSED` | `6 passed in 0.79s`. |
| `uv run pytest tests/test_pipeline_v2.py tests/test_diagnostics.py -q` | `PASSED` | `22 passed in 2.70s`. |
| `uv run pytest -q` | `PASSED` | `142 passed in 7.59s`. |
| `git diff --check` | `PASSED` | Brak błędów whitespace. |

## NOT_RUN

- Nie uruchamiano trybu live ani płatnych wywołań OpenAI/Tavily.
- Nie wykonywano migracji ani zapisu do chronionej bazy legacy.
- Nie wykonano merge.

## Stan danych i bezpieczeństwa

- Czy zmodyfikowano `instance/economy_agent.db`? **NIE**. Test integralności legacy przeszedł w pełnym zestawie.
- Czy zmodyfikowano `report.html`? **NIE**.
- Czy były wywołania płatnych API? **NIE**.
- Diagnostyka nie zapisuje promptów ani odpowiedzi GPT; komunikaty błędów są normalizowane, redagowane i ograniczone długością.
- `last_run.json` jest zastępowany atomowo, a `agent.log` rotuje przy 1 MB z trzema kopiami.

## Ryzyka / regresje / ograniczenia

- Pliki diagnostyczne są lokalne; ich trwałość zależy od trwałości katalogu `instance/logs/`.
- Lista brakujących wskaźników odzwierciedla obecny minimalny katalog raportowy i wymaga aktualizacji przy rozszerzeniu zakresu raportu.
- Błędy samego systemu plików mogą uniemożliwić zapis diagnostyki; nie są maskowane jako udany przebieg.
- Publikację commita wykonano przez GitHub API po powtarzalnym błędzie serwera `git push` (`fatal error in commit_refs`); zdalne drzewo odpowiada przetestowanemu commitowi lokalnemu.

## Decyzje wymagane

- BRAK.

## PROPOSED — następny krok

- Code review Draft PR #5 i decyzja właściciela; nie wykonywać merge bez jawnego polecenia.

## JSON status

```json
{
  "task_id": "TASK-DIAGNOSTIC-LOGGING",
  "status": "READY_FOR_REVIEW",
  "branch": "feature/diagnostic-logging",
  "commit_sha": "bc02a25f8a6ee0ada9b1c8b55a35eaa6c71532db",
  "pull_request": "https://github.com/maciejkubek-maker/polish-economy-agent/pull/5",
  "tests": {"status": "PASSED", "passed": 142, "failed": 0},
  "risks": [
    "local diagnostic persistence depends on instance/logs filesystem availability",
    "missing indicator catalog must evolve with report scope"
  ],
  "requires_decision": []
}
```
