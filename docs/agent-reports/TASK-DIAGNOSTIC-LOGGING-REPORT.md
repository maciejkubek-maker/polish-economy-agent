# PR #5 — Diagnostic Logging & Final Live Mode Stabilization

**Status:** `READY_FOR_REVIEW`
**Branch:** `feature/diagnostic-logging`
**PR:** https://github.com/maciejkubek-maker/polish-economy-agent/pull/5
**Data:** `2026-11-04`

## Zakres PR #5

PR #5 realizuje pełną diagnostykę potoku oraz końcową stabilizację projektu w trybie live (GPT-only) i offline:

1. **Tryb Live — GPT Only:**
   - Przywrócenie pierwotnej zasady projektu: raport w trybie live generuje wyłącznie model OpenAI GPT i musi on przejść rygorystyczną walidację integralności (struktura 6 sekcji, spójność liczb, brak niezweryfikowanych twierdzeń, kompletność przypisów i bezpośrednich linków URL).
   - W przypadku błędu API GPT lub odrzucenia przez walidator, potok live kończy się statusem `FAILED` (`PipelineResult.success=False`, `report_id=None`).
   - Całkowity zakaz generowania deterministycznego raportu zastępczego w trybie live.
   - W razie niepowodzenia potok nie zapisuje nowego raportu do tabeli `reports` w bazie SQLite ani nie nadpisuje pliku `report.html`. Poprzedni raport archiwalny pozostaje nienaruszony i nie jest prezentowany jako wynik bieżącego uruchomienia.
   - Deterministyczny generator raportu został zachowany WYŁĄCZNIE dla świadomego trybu offline (`OFFLINE_MODE=True`).

2. **Diagnostyka, Redakcja Sekretów i Pełny Ślad (Debug Trace):**
   - Trwały, rotowany dziennik `instance/logs/agent.log` (1 MB, 3 kopie zapasowe) oparty o moduł `logging`.
   - Zapewnienie, że pełna diagnostyka walidatora (zarówno odrzucenia, jak i pomyślna weryfikacja) trafia bezpośrednio do pliku logów danego przebiegu (`agent.log`) z przypisanym identyfikatorem `run_id`.
   - Atomowy zapis `instance/logs/last_run.json` (`.tmp` -> replace) inicjalizowany natychmiast przy rozpoczęciu przebiegu (`pipeline_status=STARTED`) i aktualizowany po zakończeniu (`COMPLETED`, `PARTIAL`, `FAILED`).
   - Strukturalny ślad wykonania `instance/logs/steps.jsonl` rejestrujący zdarzenia `START`, `END` oraz `ERROR` dla wszystkich kluczowych funkcji potoku:
     - pobieranie NBP (`fetch_nbp`),
     - pobieranie Eurostatu (`fetch_eurostat`),
     - pobieranie GUS (`fetch_gus`),
     - wyszukiwanie Tavily (`search_tavily`),
     - zapis do bazy danych (`store_sqlite`),
     - synteza GPT (`gpt_synthesis`),
     - walidacja raportu (`validate_report`),
     - zapis raportu do pliku HTML (`write_html`).
   - Każdy rekord w `steps.jsonl` zawiera: `timestamp_utc`, `run_id`, `function` / `funkcja`, `stage` / `etap` / `step`, `duration_ms`, `input_summary`, `output_summary`, `error_code` / `kod_bledu` oraz bezpieczną przyczynę `error_message` / `przyczyna`.
   - Poprawiono `missing_report_indicators`, uwzględniając rzeczywiste kody i aliasy konektorów, w tym `EU_HICP_YOY` (Eurostat) oraz `PL_NBP_REFERENCE_RATE` (NBP) – brak fałszywych braków danych w diagnostyce.
   - Awaria przed próbą wywołania GPT (np. błąd bazy lub konektora) ma `gpt_attempted=False` i nie jest oznaczana jako `GPT_API_ERROR`.
   - Rygorystyczna redakcja sekretów: klucze API, tokeny Bearer, nagłówki autoryzacyjne, pełne prompty i odpowiedzi modelu są usuwane z logów, JSON-a i JSONL-a.

3. **GUS DBW CPI:**
   - Usunięto sztywne parametry `rok=2026`, `okres_id=255`, `month=9` z uruchamiania potoku.
   - W trybie live konektor dynamicznie wyszukuje najnowszy rzeczywiście dostępny odczyt CPI z oficjalnego API GUS DBW (od bieżącego roku wstecz).
   - Weryfikacja metadanych odpowiedzi: `id-zmienna` (305), `id-przekroj` (736), `id-okres`, rok oraz jednostka.
   - Usunięto arbitralny fallback do `data_list[0]`: w przypadku dynamiki CPI r/r konektor ściśle wymaga pozycji ze sposobem prezentacji 5 (`id-sposob-prezentacji-miara=5`, analogiczny okres roku poprzedniego = 100). W przypadku braku pozycji o tym sposobie zgłaszany jest kontrolowany błąd `ValidationError` z zakazem zgadywania metodologii.
   - Jeżeli danych nie da się potwierdzić w oficjalnym rejestrze, konektor rzuca `DataNotFoundError` bez zgadywania wartości liczbowej. Rzeczywista przyczyna zostaje utrwalona w diagnostyce, a wskaźnik trafia do `missing_indicators`.

4. **Stabilizacja Cytowań i Bibliografii (Rozwiązanie RUN_89f71ad08c71):**
   - **Programowy montaż Sekcji 6:** Wprowadzono `_assemble_v2_report_with_citations`, która programowo dołącza Sekcję 6 ("6. Źródła i bibliografia") z rzeczywistego rejestru cytowań dla przypisów faktycznie użytych w tekście (`used_indices`).
   - **Rygorystyczne powiązanie przypisów:** Walidator weryfikuje istnienie przypisów `[N]`, dopasowanie do rejestru źródeł oraz atrybucję — liczba w tekście powiązana z `[N]` musi odpowiadać obserwacji z tego konkretnego źródła.
   - **Izolacja danych Tavily:** Wyniki z wyszukiwarki Tavily mają zawsze `is_official=False` i `value_decimal=None` — liczby z newsów internetowych nie mogą spełniać wymogów oficjalnych obserwacji makroekonomicznych.

5. **Walidacja i Nienaruszalność:**
   - Pełna kontrola integralności (zakaz wyłączania zabezpieczeń walidatora pod testy).
   - Baza legacy `instance/economy_agent.db` oraz niecommitowany plik użytkownika `report.html` w głównym drzewie pozostają ściśle nienaruszone (prace prowadzone w dedykowanym worktree).
   - Zero płatnych wywołań API podczas testów i weryfikacji.

## Zmienione pliki w gałęzi `feature/diagnostic-logging`

| Ścieżka | Opis zmian |
|---|---|
| `.gitignore` | Ignorowanie katalogu diagnostycznego `instance/logs/`. |
| `README.md` | Aktualizacja dokumentacji trybu live, diagnostyki, śladu zdarzeń `steps.jsonl` i wyników testów (160 passed) w wersjach PL i EN. |
| `app.py` | Poprawny komunikat konsolowy przy niepowodzeniu potoku v2. |
| `modules/connectors/gus.py` | Dynamiczne odkrywanie najnowszego CPI w DBW (`_discover_latest_cpi_period`), usunięcie arbitralnego wyboru `data_list[0]` i egzekwowanie sposobu prezentacji 5 (r/r), weryfikacja metadanych odpowiedzi GUS. |
| `modules/diagnostics.py` | Rotacja logów, atomowy JSON, strukturalny ślad `steps.jsonl` (`record_step`, `track_step`), redakcja sekretów, aliasy wskaźników (`EU_HICP_YOY`, `PL_NBP_REFERENCE_RATE`). |
| `modules/evaluator.py` | Programowy montaż Sekcji 6 z rejestru cytowań (`_assemble_v2_report_with_citations`); walidacja atrybucji przypisów i odrzucenie liczb Tavily; logowanie zdarzeń walidatora bezpośrednio do pliku logów przebiegu; rejestracja etapów `gpt_synthesis` i `validate_report` w `steps.jsonl`. |
| `modules/pipeline_v2.py` | Rejestracja etapów `fetch_nbp`, `fetch_eurostat`, `fetch_gus`, `search_tavily`, `store_sqlite`, `write_html` w `steps.jsonl`; aktualizacja `last_run.json` na starcie przebiegu (`STARTED`); brak fallbacku w trybie live. |
| `tests/test_connectors.py` | Testy dynamicznego odkrywania CPI, weryfikacji metadanych, braku zgadywania wartości oraz odrzucenia braku sposobu prezentacji 5 r/r bez wybierania `data_list[0]`. |
| `tests/test_diagnostics.py` | Testy poprawnego i nieudanego GPT, rozróżnienia błędów przed GPT, aliasów wskaźników konektorów, redakcji sekretów, atrybucji przypisów, odrzucania liczb Tavily, logowania walidatora do pliku przebiegu, natychmiastowej aktualizacji `last_run.json` oraz śladu `steps.jsonl` z kompletnymi polami. |
| `tests/test_pipeline_v2.py` | Testy odrzucenia raportu w trybie live bez fallbacku, braku nadpisywania `report.html` i SQLite przy błędzie, czyszczenia sekretów, test regresyjny `RUN_89f71ad08c71`. |

## Wyniki testów (100% offline)

Wszystkie testy wykonano lokalnie za pomocą `uv run pytest`:

```
============================= test session starts =============================
platform win32 -- Python 3.11.16, pytest-9.2.0, pluggy-1.7.0
rootdir: E:\Programy\PycharmProjects\polish-economy-agent\.worktrees\diagnostic-logging
configfile: pyproject.toml
plugins: anyio-4.15.1, langsmith-0.12.4
collected 160 items

tests\test_ambiguous_formats.py .....                                    [  3%]
tests\test_cache_freshness.py ......                                     [  6%]
tests\test_connectors.py ............................................... [ 36%]
....                                                                     [ 38%]
tests\test_database_init.py .....                                        [ 41%]
tests\test_diagnostics.py ................                               [ 51%]
tests\test_executive_horizon.py ........                                 [ 56%]
tests\test_html_security.py .................                            [ 67%]
tests\test_indicators_storage.py ......                                  [ 71%]
tests\test_migrator.py ............                                      [ 78%]
tests\test_pipeline_v2.py .................                              [ 89%]
tests\test_record_updates.py .....                                       [ 92%]
tests\test_schema_v2_design.py ............                              [100%]

============================= 160 passed in 8.45s =============================
```

## Ograniczenia i stan weryfikacji

1. **Brak płatnych wywołań w audycie:** Zgodnie z wytycznymi nie wykonywano płatnych wywołań OpenAI API ani Tavily API. Działanie potoku live z rzeczywistym modelem GPT nie zostało przetestowane "na żywo" na płatnym koncie, natomiast zostało w 100% zweryfikowane testami jednostkowymi i integracyjnymi z mockami symulującymi prawidłową odpowiedź, błąd API, odrzucenie przez walidator oraz scenariusze `RUN_89f71ad08c71` i śladu wykonania.
2. **Dynamiczne API GUS DBW:** Metoda odkrywania najnowszego okresu bada lata od bieżącego do 2 lat wstecz i wymaga sposobu prezentacji 5 (r/r). W oficjalnym API GUS DBW dane spływają zgodnie z harmonogramem publikacyjnym.
3. **Pliki diagnostyczne:** Dziennik `agent.log`, `last_run.json` oraz ślad zdarzeń `steps.jsonl` zapisywane są lokalnie w `instance/logs/`.
