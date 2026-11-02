# Raport LIVE SMOKE TESTS Oficjalnych Publicznych API (NBP, Eurostat, GUS)

**Data wykonania:** 2026-11-02 17:54:28 UTC (18:54:28 CET)  
**Autor:** Antigravity (DeepMind Agent)  
**Gałąź robocza:** `feature/data-platform-v2`  
**PR:** [Draft PR #4](https://github.com/maciejkubek-maker/polish-economy-agent/pull/4)  
**Status całościowy:** `11 VERIFIED, 1 NOT_VERIFIED, 0 FAILED`  

---

## 1. Cel i Zasady Wykonania Testów Na Żywo

Zgodnie z procedurą weryfikacyjną przed scaleniem PR #4 przeprowadzono **LIVE SMOKE TESTS** bezpośrednio na publicznych, oficjalnych serwerach API instytucji statystycznych i monetarnych (Narodowy Bank Polski, Eurostat, Główny Urząd Statystyczny).

### Rygorystyczne zasady wykonania:
1. **Zero płatnych wywołań i zero zgadywania:** Użyto wyłącznie bezpłatnych, publicznie dostępnych endpointów bez tokenów płatnych. Nie używano zewnętrznych modeli językowych (Gemini, GPT) ani wyszukiwarek komercyjnych (Tavily) do uzupełniania brakujących danych.
2. **Nienaruszalność bazy produkcyjnej:** Żadne dane pobrane z testów na żywo **nie zostały zapisane** do bazy produkcyjnej `instance/economy_agent.db`. Integralność bazy została zweryfikowana sumą kontrolną SHA-256.
3. **Prawdomówność i zakaz fałszywego zaliczania z fixture:** Zgodnie z punktem 8 polecenia, każdy endpoint nieodpowiadający w środowisku live został oznaczony jako `NOT_VERIFIED` wraz z podaniem rzeczywistego błędu HTTP.

---

## 2. Zbiorcza Tabela Wyników Live Smoke Tests

| # | Instytucja | Endpoint / Wskaźnik | HTTP | Czas | Typ | Status | Zweryfikowana Wartość / Okres / Jednostka | SHA-256 Payloadu RAW |
|---|---|---|---|---|---|---|---|---|
| 1 | **NBP** | Kurs średni EUR/PLN (Tabela A) | **200** | 222 ms | JSON | `VERIFIED` | **4.4185 EUR_PLN** (2026-11-02, tab. 213/A/NBP/2026) | `2f3c004fef62...fe8004` |
| 2 | **NBP** | Kurs średni USD/PLN (Tabela A) | **200** | 164 ms | JSON | `VERIFIED` | **3.9389 USD_PLN** (2026-11-02, tab. 213/A/NBP/2026) | `9141bba106be...e9b43d` |
| 3 | **NBP** | Stopa referencyjna (Oficjalny XML) | **200** | 193 ms | XML | `VERIFIED` | **3.75 PCT** (od 2026-03-05, pozycja `id="ref"`) | `1b945a792483...3dbfe3` |
| 4 | **Eurostat** | HICP r/r (prc_hicp_manr, geo=PL) | **200** | 329 ms | JSON-stat 2.0 | `VERIFIED` | **2.5 PCT** (2025-12-01 – 2025-12-31, 348 obs) | `e1cbec36c339...6c584f` |
| 5 | **Eurostat** | Stopa bezrobocia BAEL (une_rt_m, geo=PL) | **200** | 295 ms | JSON-stat 2.0 | `VERIFIED` | **3.4 PCT** (2026-09-01 – 2026-09-30, 357 obs) | `19799726a597...a97615` |
| 6 | **Eurostat** | PKB kw/kw (PL_GDP_QOQ, namq_10_gdp) | **200** | 236 ms | JSON-stat 2.0 | `VERIFIED` | **1.1 PCT** (2026-04-01 – 2026-06-30 / 2026-Q2, 125 obs) | `79493d67f397...348908` |
| 7 | **Eurostat** | PKB r/r (PL_GDP_YOY, namq_10_gdp) | **200** | 243 ms | JSON-stat 2.0 | `VERIFIED` | **4.0 PCT** (2026-04-01 – 2026-06-30 / 2026-Q2, 122 obs) | `2349718d2fcf...300dbb` |
| 8 | **Eurostat** | PKB wolumen w cenach stałych (PL_GDP_VOLUME) | **200** | 235 ms | JSON-stat 2.0 | `VERIFIED` | **154972.9 MEUR** (2026-04-01 – 2026-06-30 / 2026-Q2, 126 obs) | `278ce95e40c9...407819` |
| 9 | **GUS BDL** | Stopa bezrobocia rejestrowanego (var 60270) | **200** | 4271 ms | JSON | `VERIFIED` | **5.7 PCT** (2025-01-01 – 2025-12-31, 22 obs roczne) | `fcbf0e94ed8f...05793db` |
| 10 | **GUS BDL** | Liczba bezrobotnych zarejestrowanych (var 60269) | **404** | 3377 ms | JSON | `NOT_VERIFIED` | *Brak zasobu w BDL: Błąd HTTP 404 (Zasób nie istnieje)* | *(zwrócono kod błędu 3)* |
| 11 | **GUS DBW** | CPI r/r (zmienna 305, przekrój 736) | **200** | 212 ms | JSON | `VERIFIED` | **0.1 PCT** (2024-09-01 – 2024-09-30, indeks 100.1 - 100) | `0a8a5db97938...a61f9a` |
| 12 | **GUS DBW** | Słownik okresów DBW (okresy 247–258) | **200** | 144 ms | JSON | `VERIFIED` | **247=styczeń, 255=wrzesień, 258=grudzień** (50 poz) | `e081be7f22ca...1643cb` |

---

## 3. Szczegółowe Wnioski i Poprawki Wdrożone Podczas Live Smoke Tests

Podczas bezpośrednich testów na żywo zidentyfikowano i natychmiast bezpiecznie zaadresowano w kodzie konektorów cztery kluczowe fakty produkcyjne:

### 1. Eurostat: Rzeczywiste kody miar procentowych w `namq_10_gdp`
- **Fakt produkcyjny:** W oficjalnym Statistics API 1.0 Eurostatu dla szeregów wolumenu PKB (`na_item=B1GQ`) jednostki zmiany procentowej to:
  - `CLV_PCH_PRE` dla dynamiki kwartał do kwartału (125 obserwacji dla Polski, ostatnia Q2 2026: **+1.1%**),
  - `CLV_PCH_SM` dla dynamiki rok do roku (122 obserwacje dla Polski, ostatnia Q2 2026: **+4.0%**),
  - `CLV10_MEUR` dla wolumenu w mln EUR w cenach stałych (126 obserwacji, ostatnia Q2 2026: **154 972.9 MEUR**).
- **Wdrożona poprawka:** [`modules/connectors/eurostat.py`](file:///E:/Programy/PycharmProjects/polish-economy-agent/modules/connectors/eurostat.py) automatycznie mapuje zapytania do oficjalnych jednostek `CLV_PCH_PRE` oraz `CLV_PCH_SM`, zachowując pełną kompatybilność wsteczną dla zarejestrowanych fixture offline.
- **Rygor rozdzielenia:** Wolumen i stopy procentowe mają całkowicie odrębne kody wskaźników (`PL_GDP_VOLUME` vs `PL_GDP_QOQ`) i jednostki (`MEUR` vs `PCT`).

### 2. Eurostat: Format daty miesięcznej (`YYYY-MM` vs `YYYYMmm`)
- **Fakt produkcyjny:** Live API Eurostatu dla szeregów miesięcznych zwraca identyfikatory okresów w formacie z myślnikiem `YYYY-MM` (np. `2026-09` dla stopy bezrobocia oraz `2025-12` dla HICP).
- **Wdrożona poprawka:** Funkcja `_parse_time_period_monthly` w [`modules/connectors/eurostat.py`](file:///E:/Programy/PycharmProjects/polish-economy-agent/modules/connectors/eurostat.py) obsługuje oba standardy: format z myślnikiem (`YYYY-MM`) oraz format z literą M (`YYYYMmm`), precyzyjnie wyznaczając początek i koniec miesiąca kalendarzowego.

### 3. GUS DBW: Rzeczywista ścieżka API i potwierdzenie słownika 247–258
- **Fakt produkcyjny:** Oficjalna specyfikacja OpenAPI serwisu `https://api-dbw.stat.gov.pl` (dostępna pod adresem `/apidocs/pl/dbw.json?lang=pl`) udostępnia pobieranie danych pod ścieżką `/api/variable/variable-data-section`. Dawniej proponowana w roboczych notatkach ścieżka `/api/1.1.0/data/data-data` zwracała HTTP 404.
- **Wdrożona poprawka:** Zaktualizowano `DBW_BASE_URL` oraz ścieżkę pobierania w [`modules/connectors/gus.py`](file:///E:/Programy/PycharmProjects/polish-economy-agent/modules/connectors/gus.py) z zachowaniem fallbacku dla starszych fixture offline.
- **Weryfikacja słownika okresów:** Bezpośrednie pobranie słownika z `https://api-dbw.stat.gov.pl/api/dictionaries/periods-dictionary` w 100% potwierdziło przyjęte w projekcie mapowanie:
  - `id=247` &rarr; *"miesiąc - dane miesięczne - styczeń"*
  - `id=255` &rarr; *"miesiąc - dane miesięczne - wrzesień"*
  - `id=258` &rarr; *"miesiąc - dane miesięczne - grudzień"*

### 4. GUS BDL: Weryfikacja zmiennych 60270 oraz 60269
- **Zmienna 60270 (Stopa bezrobocia rejestrowanego):**
  - Parametr `unit-level=0` w zapytaniu do BDL (`https://bdl.stat.gov.pl/api/v1/data/by-variable/60270?unit-level=0&format=json`) zwraca bezpośrednio zagregowane dane dla terytorium POLSKA (`000000000000`) — 22 obserwacje roczne (najnowsza za 2025 r.: **5.7%**).
  - W [`modules/connectors/gus.py`](file:///E:/Programy/PycharmProjects/polish-economy-agent/modules/connectors/gus.py) zapewniono rzutowanie roku na liczbę całkowitą (`int(year)`), eliminując błąd formatowania przy odczycie wartości tekstowych z API BDL.
- **Zmienna 60269 (Liczba bezrobotnych zarejestrowanych) — `NOT_VERIFIED`:**
  - Zapytanie o metadane zmiennej 60269 (`https://bdl.stat.gov.pl/api/v1/variables/60269`) oraz dane (`by-variable/60269`) zwraca **HTTP 404 Not Found** z oficjalnym komunikatem GUS: `{"errorCode": 3, "errorResult": "Zasób nie istnieje", "errorReason": "Nie znaleziono zasobu o podanym identyfikatorze"}`.
  - Zgodnie z punktem 8 polecenia oraz zasadą braku zgadywania (Rule 8 & 12 AGENTS.md), **status zmiennej 60269 oznaczono jako `NOT_VERIFIED`**.
  - Zmienna ta nie może być uznana za zweryfikowaną na produkcji do czasu opublikowania przez GUS nowego identyfikatora (np. w dziedzinie P4324/P2965). Nie użyto fixture offline do fałszywego zaliczenia testu live.

---

## 4. Weryfikacja Integralności Bazy Danych i Testów Offline

1. **Nienaruszalność bazy legacy:**
   - Plik produkcyjny [`instance/economy_agent.db`](file:///E:/Programy/PycharmProjects/polish-economy-agent/instance/economy_agent.db) pozostał całkowicie nietknięty.
   - Dokładny rozmiar: **73 728 bajtów**.
   - Suma kontrolna SHA-256: `E6C5F318FFE1ECEEB34191A7A74EC9F7F7DE6069C4F298850792734277ECDE3B`.
2. **Wyniki testów jednostkowych i integracyjnych offline (`pytest`):**
   - Po wdrożeniu poprawek zgodności live uruchomiono pełny zestaw testów offline w izolacji sieciowej:
   ```text
   ============================= test session starts =============================
   platform win32 -- Python 3.11.16, pytest-9.2.0, pluggy-1.7.0
   rootdir: E:\Programy\PycharmProjects\polish-economy-agent
   configfile: pyproject.toml
   plugins: anyio-4.15.1, langsmith-0.12.4
   collected 104 items

   tests\test_ambiguous_formats.py .....                                    [  4%]
   tests\test_cache_freshness.py ......                                     [ 10%]
   tests\test_connectors.py ............................                    [ 37%]
   tests\test_database_init.py .....                                        [ 42%]
   tests\test_executive_horizon.py ........                                 [ 50%]
   tests\test_html_security.py .................                            [ 66%]
   tests\test_indicators_storage.py ......                                  [ 72%]
   tests\test_migrator.py ............                                      [ 83%]
   tests\test_record_updates.py .....                                       [ 88%]
   tests\test_schema_v2_design.py ............                              [100%]

   ============================ 104 passed in 20.68s =============================
   ```
   - **Wynik:** 104/104 testy zakończone sukcesem (100% green).

3. **Narzędzie do powtarzalnego uruchamiania testów na żywo:**
   - Utworzono moduł uruchomieniowy [`scripts/run_live_smoke_tests.py`](file:///E:/Programy/PycharmProjects/polish-economy-agent/scripts/run_live_smoke_tests.py), który rejestruje szczegółowy audyt w pliku `docs/agent-reports/live_smoke_results.json`.

---

## 5. Podsumowanie i Gotowość PR #4

- Oficjalne publiczne API **NBP** (EUR, USD, stopy XML) oraz **Eurostat** (HICP, bezrobocie BAEL, PKB QOQ/YOY/Wolumen) są w 100% sprawne, zweryfikowane na żywo i w pełni kompatybilne z nowym modelem danych SQLite v2.
- Oficjalne API **GUS DBW** dla CPI oraz słownika okresów działa stabilnie na zweryfikowanym endpointcie `/api/variable/variable-data-section`.
- Zidentyfikowano precyzyjnie jedyny problem zewnętrzny: brak zmiennej 60269 w katalogu BDL GUS (oznaczono prawidłowo jako `NOT_VERIFIED`).
- PR #4 (`feature/data-platform-v2`) posiada pełne pokrycie testowe i jest gotowy do wglądu właściciela repozytorium.
