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

3. **GUS DBW CPI — Bezwzględny Wymóg Sposobu Prezentacji 5 (r/r):**
   - Usunięto sztywne parametry `rok=2026`, `okres_id=255`, `month=9` z uruchamiania potoku.
   - W trybie live konektor dynamicznie wyszukuje najnowszy rzeczywiście dostępny odczyt CPI z oficjalnego API GUS DBW (od bieżącego roku wstecz) z potwierdzeniem obecności miary 5.
   - Weryfikacja metadanych odpowiedzi: `id-zmienna` (305), `id-przekroj` (736), `id-okres`, rok oraz jednostka.
   - Całkowity zakaz akceptacji pojedynczych rekordów bez potwierdzenia sposobu prezentacji: w przypadku dynamiki CPI r/r konektor bezwzględnie wymaga odnalezienia rekordu ze sposobem prezentacji 5 (`id-sposob-prezentacji-miara=5`, analogiczny okres roku poprzedniego = 100). Usunięto wszelkie wyjątki wybierające `data_list[0]` bez tego pola.
   - Jeżeli danych nie da się potwierdzić w oficjalnym rejestrze, konektor rzuca `DataNotFoundError` lub `ValidationError` bez zgadywania wartości liczbowej ani metodologii.

4. **Stabilizacja Cytowań, Bibliografii i Prezentacji Raportu:**
   - **Programowy montaż Sekcji 6:** Wprowadzono `_assemble_v2_report_with_citations`, która programowo dołącza Sekcję 6 ("6. Źródła i bibliografia") z rzeczywistego rejestru cytowań dla przypisów faktycznie użytych w tekście (`used_indices`).
   - **Rygorystyczne powiązanie przypisów:** Walidator weryfikuje istnienie przypisów `[N]`, dopasowanie do rejestru źródeł oraz atrybucję — liczba w tekście powiązana z `[N]` musi odpowiadać obserwacji z tego konkretnego źródła.
   - **Izolacja danych Tavily:** Wyniki z wyszukiwarki Tavily mają zawsze `is_official=False` i `value_decimal=None` — liczby z newsów internetowych nie mogą spełniać wymogów oficjalnych obserwacji makroekonomicznych.
   - **Branding raportu HTML:** Do nagłówka szablonu HTML dołączono oficjalne logo projektu (`static/logo.png`) osadzone bezpiecznie przez `data:image/png;base64` w stylach CSS bez naruszania testów bezpieczeństwa tagów.

5. **Walidacja i Nienaruszalność:**
   - Pełna kontrola integralności (zakaz wyłączania zabezpieczeń walidatora pod testy).
   - Baza legacy `instance/economy_agent.db` oraz niecommitowany plik użytkownika `report.html` w głównym drzewie pozostają ściśle nienaruszone (prace prowadzone w dedykowanym worktree).
   - Zero płatnych wywołań API podczas testów i weryfikacji.

## Zmienione pliki w gałęzi `feature/diagnostic-logging`

| Ścieżka | Opis zmian |
|---|---|
| `.gitignore` | Ignorowanie katalogu diagnostycznego `instance/logs/`. |
| `README.md` | Aktualizacja dokumentacji trybu live, diagnostyki, śladu zdarzeń `steps.jsonl`, logo i wyników testów (162 passed) w wersjach PL i EN. |
| `app.py` | Dołączenie logo w nagłówku raportu HTML (`static/logo.png`), poprawny komunikat konsolowy przy niepowodzeniu potoku v2. |
| `modules/connectors/gus.py` | Dynamiczne odkrywanie najnowszego CPI w DBW (`_discover_latest_cpi_period`), bezwzględny wymóg sposobu prezentacji 5 (r/r) bez fallbacku do `data_list[0]`, weryfikacja metadanych odpowiedzi GUS. |
| `modules/diagnostics.py` | Rotacja logów, atomowy JSON, strukturalny ślad `steps.jsonl` (`record_step`, `track_step`), redakcja sekretów, aliasy wskaźników (`EU_HICP_YOY`, `PL_NBP_REFERENCE_RATE`). |
| `modules/evaluator.py` | Programowy montaż Sekcji 6 z rejestru cytowań (`_assemble_v2_report_with_citations`); walidacja atrybucji przypisów i odrzucenie liczb Tavily; logowanie zdarzeń walidatora bezpośrednio do pliku logów przebiegu; rejestracja etapów `gpt_synthesis` i `validate_report` w `steps.jsonl`. |
| `modules/pipeline_v2.py` | Rejestracja etapów `fetch_nbp`, `fetch_eurostat`, `fetch_gus`, `search_tavily`, `store_sqlite`, `write_html` w `steps.jsonl`; aktualizacja `last_run.json` na starcie przebiegu (`STARTED`); brak fallbacku w trybie live. |
| `static/logo.png` | Plik logo dodany jako zasób projektu. |
| `tests/test_connectors.py` | Testy dynamicznego odkrywania CPI, weryfikacji metadanych, odrzucenia braku sposobu prezentacji 5 r/r (zarówno przy wielu rekordach, jak i pojedynczym rekordzie bez identyfikatora). |
| `tests/test_diagnostics.py` | Testy poprawnego i nieudanego GPT, rozróżnienia błędów przed GPT, aliasów wskaźników konektorów, redakcji sekretów, atrybucji przypisów, odrzucania liczb Tavily, logowania walidatora do pliku przebiegu, natychmiastowej aktualizacji `last_run.json` oraz śladu `steps.jsonl` z kompletnymi polami. |
| `tests/test_html_security.py` | Weryfikacja obecności logo w szablonie `build_html_template` z zachowaniem pełnego bezpieczeństwa HTML. |
| `tests/test_pipeline_v2.py` | Testy odrzucenia raportu w trybie live bez fallbacku, braku nadpisywania `report.html` i SQLite przy błędzie, czyszczenia sekretów, test regresyjny `RUN_89f71ad08c71`. |

## Wyniki testów (100% offline)

Wszystkie testy wykonano lokalnie za pomocą `uv run pytest`:

```
============================= test session starts =============================
platform win32 -- Python 3.11.16, pytest-9.2.0, pluggy-1.7.0
rootdir: E:\Programy\PycharmProjects\polish-economy-agent\.worktrees\diagnostic-logging
configfile: pyproject.toml
plugins: anyio-4.15.1, langsmith-0.12.4
collected 162 items

tests\test_ambiguous_formats.py .....                                    [  3%]
tests\test_cache_freshness.py ......                                     [  6%]
tests\test_connectors.py ............................................... [ 35%]
.....                                                                    [ 38%]
tests\test_database_init.py .....                                        [ 41%]
tests\test_diagnostics.py ................                               [ 51%]
tests\test_executive_horizon.py ........                                 [ 56%]
tests\test_html_security.py ..................                           [ 67%]
tests\test_indicators_storage.py ......                                  [ 71%]
tests\test_migrator.py ............                                      [ 79%]
tests\test_pipeline_v2.py .................                              [ 89%]
tests\test_record_updates.py .....                                       [ 92%]
tests\test_schema_v2_design.py ............                              [100%]

============================ 162 passed in 10.69s =============================
```

## Ograniczenia i stan weryfikacji

1. **Brak płatnych wywołań w audycie:** Zgodnie z wytycznymi nie wykonywano płatnych wywołań OpenAI API ani Tavily API. Działanie potoku live z modelem GPT, rejestracja śladu `steps.jsonl`, odrzucenia walidatora oraz obsługa braku sposobu prezentacji CPI zostały w 100% zweryfikowane testami jednostkowymi i integracyjnymi.
2. **Dynamiczne API GUS DBW:** Wyszukiwanie CPI w DBW bada okresy od bieżącego roku wstecz i wymaga obecności miary 5 (r/r). W przypadku braku publikacji odczytu przez GUS w danym miesiącu potok nie zgaduje wartości.
3. **Pliki diagnostyczne:** Dziennik `agent.log`, `last_run.json` oraz ślad zdarzeń `steps.jsonl` zapisywane są lokalnie w `instance/logs/`.
