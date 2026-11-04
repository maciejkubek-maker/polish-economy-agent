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

5. **Stabilizacja Cytowań i Bibliografii (Rozwiązanie RUN_89f71ad08c71):**
   - **Przyczyna odrzucenia w RUN_89f71ad08c71:** Model GPT wygenerował merytorycznie poprawny raport, ale w Sekcji 6 podał ogólne domeny (`https://stat.gov.pl`, `https://nbp.pl`) zamiast pełnych, wieloparametrowych endpointów API GUS/NBP zarejestrowanych w rejestrze źródeł (`citations`).
   - **Programowy montaż Sekcji 6:** Wprowadzono `_assemble_v2_report_with_citations`, która programowo dołącza Sekcję 6 ("6. Źródła i bibliografia") z rzeczywistego rejestru cytowań dla przypisów faktycznie użytych w tekście (`used_indices`). Eliminuje to zależność od bezbłędnego przepisywania długich URL-i zapytań przez LLM.
   - **Rygorystyczne powiązanie przypisów:** Walidator weryfikuje istnienie przypisów `[N]`, dopasowanie do rejestru źródeł oraz atrybucję — liczba w tekście powiązana z `[N]` musi odpowiadać obserwacji z tego konkretnego źródła.
   - **Izolacja danych Tavily:** Wyniki z wyszukiwarki Tavily mają zawsze `is_official=False` i `value_decimal=None` — liczby z newsów internetowych nie mogą spełniać wymogów oficjalnych obserwacji makroekonomicznych.
   - **Szczegółowe logowanie odrzuceń:** Dokładna lista brakujących URL-i lub odrzuconych liczb jest logowana na poziomie WARNING i przekazywana w przyczynie błędu.

## Zmienione pliki w gałęzi `feature/diagnostic-logging`

| Ścieżka | Opis zmian |
|---|---|
| `.gitignore` | Ignorowanie katalogu diagnostycznego `instance/logs/`. |
| `README.md` | Aktualizacja dokumentacji trybu live, diagnostyki, programowej bibliografii i wyników testów (154 passed) w wersjach PL i EN. |
| `app.py` | Poprawny komunikat konsolowy przy niepowodzeniu potoku v2. |
| `modules/connectors/gus.py` | Dynamiczne odkrywanie najnowszego CPI w DBW (`_discover_latest_cpi_period`), obsługa wywołań bez sztywnych dat, rygorystyczna weryfikacja metadanych odpowiedzi GUS. |
| `modules/diagnostics.py` | Rotacja logów, atomowy JSON, redakcja sekretów, aliasy wskaźników (`EU_HICP_YOY`, `PL_NBP_REFERENCE_RATE`), obsługa `generation_mode=None` przed GPT. |
| `modules/evaluator.py` | Odrzucenie deterministycznego fallbacku w trybie live; programowy montaż Sekcji 6 z rejestru cytowań (`_assemble_v2_report_with_citations`); walidacja atrybucji przypisów i odrzucenie liczb Tavily jako oficjalnych obserwacji; szczegółowe logowanie odrzuconych URL-i i liczb. |
| `modules/pipeline_v2.py` | Usunięcie sztywnego wywołania CPI w `fetch_official_data`, poprawna obsługa stanu awarii GPT i przed-GPT, brak zapisu raportu przy niepowodzeniu. |
| `tests/test_connectors.py` | Dodatkowe testy dynamicznego odkrywania CPI, weryfikacji zmiennej, przekroju, okresu, roku oraz braku zgadywania. |
| `tests/test_diagnostics.py` | Testy poprawnego i nieudanego GPT, rozróżnienia błędów przed GPT, aliasów wskaźników konektorów, redakcji sekretów, atrybucji przypisów, odrzucania liczb Tavily oraz logowania brakujących URL-i. |
| `tests/test_pipeline_v2.py` | Testy odrzucenia raportu w trybie live bez fallbacku, braku nadpisywania `report.html` i SQLite przy błędzie, czyszczenia sekretów, test regresyjny `RUN_89f71ad08c71` z domenowymi URL-ami w GPT i ich programową podmianą. |

## Wyniki testów (100% offline)

Wszystkie testy wykonano lokalnie za pomocą `uv run pytest`:

```
============================= test session starts =============================
platform win32 -- Python 3.11.16, pytest-9.2.0, pluggy-1.7.0
rootdir: E:\Programy\PycharmProjects\polish-economy-agent\.worktrees\diagnostic-logging
configfile: pyproject.toml
plugins: anyio-4.15.1, langsmith-0.12.4
collected 154 items

tests\test_ambiguous_formats.py .....                                    [  3%]
tests\test_cache_freshness.py ......                                     [  7%]
tests\test_connectors.py ............................................... [ 37%]
...                                                                      [ 39%]
tests\test_database_init.py .....                                        [ 42%]
tests\test_diagnostics.py ...........                                    [ 50%]
tests\test_executive_horizon.py ........                                 [ 55%]
tests\test_html_security.py .................                            [ 66%]
tests\test_indicators_storage.py ......                                  [ 70%]
tests\test_migrator.py ............                                      [ 77%]
tests\test_pipeline_v2.py .................                              [ 88%]
tests\test_record_updates.py .....                                       [ 92%]
tests\test_schema_v2_design.py ............                              [100%]

============================= 154 passed in 8.60s =============================
```

## Ograniczenia i stan weryfikacji

1. **Brak płatnych wywołań w audycie:** Zgodnie z wytycznymi nie wykonywano płatnych wywołań OpenAI API ani Tavily API. Działanie potoku live z rzeczywistym modelem GPT nie zostało przetestowane "na żywo" na płatnym koncie, natomiast zostało w 100% zweryfikowane testami jednostkowymi i integracyjnymi z mockami symulującymi prawidłową odpowiedź, błąd API, odrzucenie przez walidator oraz scenariusz RUN_89f71ad08c71.
2. **Dynamiczne API GUS DBW:** Metoda odkrywania najnowszego okresu bada lata od bieżącego do 2 lat wstecz. W oficjalnym API GUS DBW najświeższe dane roczne/miesięczne dla zmiennej 305 / przekroju 736 spływają z opóźnieniem publikacyjnym (np. okresy 2025 r.).
3. **Pliki diagnostyczne:** Dziennik `agent.log` oraz `last_run.json` zapisywane są lokalnie w `instance/logs/`.
