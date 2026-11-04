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

2. **Diagnostyka i Redakcja Sekretów:**
   - Trwały, rotowany dziennik `instance/logs/agent.log` (1 MB, 3 kopie zapasowe) oparty o moduł `logging`.
   - Atomowy zapis `instance/logs/last_run.json` (`.tmp` -> replace) z podsumowaniem każdego przebiegu (`COMPLETED`, `PARTIAL`, `FAILED`).
   - Poprawiono `missing_report_indicators`, uwzględniając rzeczywiste kody i aliasy konektorów, w tym `EU_HICP_YOY` (Eurostat) oraz `PL_NBP_REFERENCE_RATE` (NBP) – brak fałszywych braków danych w diagnostyce.
   - Awaria przed próbą wywołania GPT (np. błąd bazy lub konektora) ma `gpt_attempted=False` i nie jest oznaczana jako `GPT_API_ERROR`.
   - Dla awarii GPT/walidatora rejestrowane jest `pipeline_status=FAILED`, `report_id=null`, `gpt_attempted=True` oraz zredagowana, bezpieczna przyczyna (`fallback_reason`).
   - Rygorystyczna redakcja sekretów: klucze API, tokeny Bearer, nagłówki autoryzacyjne, pełne prompty i odpowiedzi modelu są usuwane z logów i JSON-a.

3. **GUS DBW CPI:**
   - Usunięto sztywne parametry `rok=2026`, `okres_id=255`, `month=9` z uruchamiania potoku.
   - W trybie live konektor dynamicznie i sekwencyjnie wyszukuje najnowszy rzeczywiście dostępny odczyt CPI z oficjalnego API GUS DBW (od bieżącego roku wstecz).
   - Weryfikacja metadanych odpowiedzi: `id-zmienna` (305), `id-przekroj` (736), `id-okres`, rok oraz jednostka. Dla dynamiki r/r pobierana jest pozycja o sposobie prezentacji 5 (analogiczny okres roku poprzedniego = 100).
   - Jeżeli danych nie da się potwierdzić w oficjalnym rejestrze, konektor rzuca `DataNotFoundError` bez zgadywania wartości liczbowej. Rzeczywista przyczyna zostaje utrwalona w diagnostyce, a wskaźnik trafia do `missing_indicators`.

4. **Walidacja i Nienaruszalność:**
   - Pełna kontrola integralności (zakaz wyłączania zabezpieczeń walidatora pod testy).
   - Baza legacy `instance/economy_agent.db` oraz niecommitowany plik użytkownika `report.html` w głównym drzewie pozostają ściśle nienaruszone (prace prowadzone w dedykowanym worktree).
   - Zero płatnych wywołań API podczas testów i weryfikacji.

## Zmienione pliki w gałęzi `feature/diagnostic-logging`

| Ścieżka | Opis zmian |
|---|---|
| `.gitignore` | Ignorowanie katalogu diagnostycznego `instance/logs/`. |
| `README.md` | Aktualizacja dokumentacji trybu live, diagnostyki i wyników testów (150 passed) w wersjach PL i EN. |
| `app.py` | Poprawny komunikat konsolowy przy niepowodzeniu potoku v2. |
| `modules/connectors/gus.py` | Dynamiczne odkrywanie najnowszego CPI w DBW (`_discover_latest_cpi_period`), obsługa wywołań bez sztywnych dat, rygorystyczna weryfikacja metadanych odpowiedzi GUS. |
| `modules/diagnostics.py` | Rotacja logów, atomowy JSON, redakcja sekretów, aliasy wskaźników (`EU_HICP_YOY`, `PL_NBP_REFERENCE_RATE`), obsługa `generation_mode=None` przed GPT. |
| `modules/evaluator.py` | Odrzucenie deterministycznego fallbacku w trybie live — wyłącznie GPT z walidacją; zgłaszanie błędu przy awarii GPT / odrzuceniu przez walidator. |
| `modules/pipeline_v2.py` | Usunięcie sztywnego wywołania CPI w `fetch_official_data`, poprawna obsługa stanu awarii GPT i przed-GPT, brak zapisu raportu przy niepowodzeniu. |
| `tests/test_connectors.py` | Dodatkowe testy dynamicznego odkrywania CPI, weryfikacji zmiennej, przekroju, okresu, roku oraz braku zgadywania. |
| `tests/test_diagnostics.py` | Testy poprawnego i nieudanego GPT, rozróżnienia błędów przed GPT, aliasów wskaźników konektorów i redakcji sekretów. |
| `tests/test_pipeline_v2.py` | Testy odrzucenia raportu w trybie live bez fallbacku, braku nadpisywania `report.html` i SQLite przy błędzie, czyszczenia sekretów. |

## Wyniki testów (100% offline)

Wszystkie testy wykonano lokalnie za pomocą `uv run pytest`:

```
============================= test session starts =============================
platform win32 -- Python 3.11.16, pytest-9.2.0, pluggy-1.7.0
rootdir: E:\Programy\PycharmProjects\polish-economy-agent\.worktrees\diagnostic-logging
configfile: pyproject.toml
plugins: anyio-4.15.1, langsmith-0.12.4
collected 150 items

tests\test_ambiguous_formats.py .....                                    [  3%]
tests\test_cache_freshness.py ......                                     [  7%]
tests\test_connectors.py ............................................... [ 38%]
...                                                                      [ 40%]
tests\test_database_init.py .....                                        [ 44%]
tests\test_diagnostics.py ........                                       [ 49%]
tests\test_executive_horizon.py ........                                 [ 54%]
tests\test_html_security.py .................                            [ 66%]
tests\test_indicators_storage.py ......                                  [ 70%]
tests\test_migrator.py ............                                      [ 78%]
tests\test_pipeline_v2.py ................                               [ 88%]
tests\test_record_updates.py .....                                       [ 92%]
tests\test_schema_v2_design.py ............                              [100%]

============================= 150 passed in 8.17s =============================
```

## Ograniczenia i stan weryfikacji

1. **Brak płatnych wywołań w audycie:** Zgodnie z wytycznymi nie wykonywano płatnych wywołań OpenAI API ani Tavily API. Działanie potoku live z rzeczywistym modelem GPT nie zostało przetestowane "na żywo" na płatnym koncie, natomiast zostało w 100% zweryfikowane testami jednostkowymi i integracyjnymi z mockami symulującymi prawidłową odpowiedź, błąd API oraz odrzucenie przez walidator.
2. **Dynamiczne API GUS DBW:** Metoda odkrywania najnowszego okresu bada lata od bieżącego do 2 lat wstecz. W oficjalnym API GUS DBW najświeższe dane roczne/miesięczne dla zmiennej 305 / przekroju 736 spływają z opóźnieniem publikacyjnym (np. okresy 2025 r.).
3. **Pliki diagnostyczne:** Dziennik `agent.log` oraz `last_run.json` zapisywane są lokalnie w `instance/logs/`.
