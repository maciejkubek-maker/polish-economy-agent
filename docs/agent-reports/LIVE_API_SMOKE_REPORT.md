# Raport LIVE SMOKE TESTS Oficjalnych Publicznych API (NBP, Eurostat, GUS)

**Data wykonania:** 2026-11-02 18:18:00 UTC (19:18:00 CET)  
**Autor:** Antigravity (DeepMind Agent)  
**Gałąź robocza:** `feature/data-platform-v2`  
**PR:** [Draft PR #4](https://github.com/maciejkubek-maker/polish-economy-agent/pull/4)  
**Status całościowy:** `11 VERIFIED, 1 NOT_VERIFIED, 0 FAILED`  
**Integralność bazy legacy:** `instance/economy_agent.db` — 73 728 bajtów, SHA-256 `E6C5F318FFE1ECEEB34191A7A74EC9F7F7DE6069C4F298850792734277ECDE3B` (nietknięta).

---

## 1. Cel i Rygorystyczne Zasady Wykonania

Zgodnie z wytycznymi weryfikacji przed scaleniem PR #4 przeprowadzono **LIVE SMOKE TESTS** bezpośrednio na oficjalnych serwerach API instytucji statystycznych i monetarnych (Narodowy Bank Polski, Eurostat, Główny Urząd Statystyczny), a następnie zaadresowano wszystkie uwagi z ostatniego przeglądu:

1. **Zero fikcyjnych danych i zero zgadywania (Rule 8 & 12 AGENTS.md):** Nie użyto żadnych płatnych API ani modeli zewnętrznych (Gemini, GPT, Tavily) do uzupełniania brakujących wartości.
2. **Uczciwe statusy (Reporting Integrity):** Żaden niedziałający lub wycofany endpoint nie został fałszywie oznaczony jako zweryfikowany na podstawie fixture offline.
3. **Nienaruszalność bazy produkcyjnej:** Żadne dane live nie trafiły do produkcyjnej bazy SQLite.
4. **Wielowymiarowy parser JSON-stat 2.0 ze stride math:** Wyeliminowano uproszczone indeksowanie tablic, wprowadzając pełne adresowanie w wielowymiarowych kostkach Eurostatu wraz z kontrolą kompletności.
5. **Rozdzielenie okresu od daty publikacji:** Usunięto sztuczne wpisywanie `period_end` jako daty publikacji dla API, które nie udostępniają znacznika czasu publikacji per obserwacja.
6. **Rygor częstotliwości:** Roczne serie GUS BDL zostały jawnie oznaczone jako `ANNUAL` z zakazem zastępowania miesięcznych stóp bezrobocia.

---

## 2. Zbiorcza Tabela Wyników Live Smoke Tests

| # | Instytucja | Endpoint / Wskaźnik | HTTP | Czas | Typ odpowiedzi | Status | Zweryfikowana Wartość / Okres / Jednostka | SHA-256 RAW |
|---|---|---|---|---|---|---|---|---|
| 1 | **NBP** | Kurs średni EUR/PLN (Tabela A) | **200** | 270 ms | JSON | `VERIFIED` | **4.4185 EUR_PLN** (2026-11-02, tab. 213/A/NBP/2026) | `2f3c004fef...` |
| 2 | **NBP** | Kurs średni USD/PLN (Tabela A) | **200** | 159 ms | JSON | `VERIFIED` | **3.9389 USD_PLN** (2026-11-02, tab. 213/A/NBP/2026) | `9141bba106...` |
| 3 | **NBP** | Stopa referencyjna (Oficjalny XML) | **200** | 172 ms | XML | `VERIFIED` | **3.75 PCT** (od 2026-03-05, pozycja `id="ref"`) | `1b945a7924...` |
| 4 | **Eurostat** | HICP r/r (prc_hicp_manr, geo=PL) | **200** | 279 ms | JSON-stat 2.0 | `VERIFIED` | **2.5 PCT** (2025-12-01 – 2025-12-31, 348 obs) | `e1cbec36c3...` |
| 5 | **Eurostat** | Stopa bezrobocia BAEL (une_rt_m, geo=PL) | **200** | 246 ms | JSON-stat 2.0 | `VERIFIED` | **3.4 PCT** (2026-09-01 – 2026-09-30, 357 obs) | `19799726a5...` |
| 6 | **Eurostat** | PKB kw/kw (PL_GDP_QOQ, namq_10_gdp) | **200** | 213 ms | JSON-stat 2.0 | `VERIFIED` | **1.1 PCT** (2026-04-01 – 2026-06-30 / 2026-Q2, 125 obs) | `79493d67f3...` |
| 7 | **Eurostat** | PKB r/r (PL_GDP_YOY, namq_10_gdp) | **200** | 213 ms | JSON-stat 2.0 | `VERIFIED` | **4.0 PCT** (2026-04-01 – 2026-06-30 / 2026-Q2, 122 obs) | `2349718d2f...` |
| 8 | **Eurostat** | PKB wolumen w cenach stałych (PL_GDP_VOLUME) | **200** | 201 ms | JSON-stat 2.0 | `VERIFIED` | **154972.9 MEUR** (2026-04-01 – 2026-06-30 / 2026-Q2, 126 obs) | `278ce95e40...` |
| 9 | **GUS BDL** | Stopa bezrobocia rejestrowanego (var 60270) | **200** | 9672 ms | JSON | `VERIFIED` | **5.7 PCT** (2025-01-01 – 2025-12-31, 22 obs roczne) | `fcbf0e94ed...` |
| 10 | **GUS BDL** | Liczba bezrobotnych zarejestrowanych (var 60269) | **404** / timeout | >10s | JSON | `NOT_VERIFIED` | *Brak zasobu w publicznym BDL (HTTP 404 / Zasób nie istnieje)* | *(zablokowane)* |
| 11 | **GUS DBW** | CPI r/r (zmienna 305, przekrój 736) | **200** | 291 ms | JSON | `VERIFIED` | **0.1 PCT** (2024-09-01 – 2024-09-30, indeks 100.1 - 100) | `0a8a5db979...` |
| 12 | **GUS DBW** | Słownik okresów DBW (okresy 247–258) | **200** | 144 ms | JSON | `VERIFIED` | **247=styczeń, 255=wrzesień, 258=grudzień** (50 poz) | `e081be7f22...` |

---

## 3. Szczegółowe Rozstrzygnięcie Zgłoszonych Uwag

### 1. GUS BDL 60269: Wycofanie, blokowanie i analiza metadanych GUS
- **Stan w API:** Wywołanie `https://bdl.stat.gov.pl/api/v1/data/by-variable/60269` zwraca w API GUS oficjalny błąd **HTTP 404 Not Found** (`errorCode: 3, errorResult: "Zasób nie istnieje"`).
- **Zastosowane rozwiązanie:**
  - Zmienna `60269` została całkowicie usunięta ze słownika `VERIFIED_BDL_VARIABLES`.
  - Wskaźnik `PL_UNEMPLOYMENT_REGISTERED_COUNT` został przeniesiony do słownika `UNMAPPED_INDICATORS` ze statusem `CONFIRMED_API_REQUIRES_VARIABLE_MAPPING` / `NOT_VERIFIED`.
  - Metoda `fetch_registered_unemployment_count()` w [`modules/connectors/gus.py`](file:///E:/Programy/PycharmProjects/polish-economy-agent/modules/connectors/gus.py) bez podania zweryfikowanego parametru `var_id` **blokuje wykonanie i rzuca wyjątek `VariableNotMappedError`**.
- **Weryfikacja metadanych GUS BDL (bez zgadywania):**
  - Przegląd dziedziny `P2437` i podtematu `P2961` (*Rynek pracy / Bezrobocie rejestrowane*) wykazał, że GUS zreorganizował strukturę danych: liczba bezrobotnych została podzielona na 12 odrębnych zmiennych miesięcznych (np. zmienna `217613` dla stycznia) lub zagregowane roczne średnie w `P4324` (zmienna `1701681`). Nie istnieje pojedyncza, ciągła zmienna czasowa o dawnym identyfikatorze 60269.
  - Zgodnie z wytycznymi wskaźnik pozostaje jako `NOT_VERIFIED` do czasu oficjalnego uzgodnienia nowego mapowania zmiennych miesięcznych.

### 2. Eurostat: Wielowymiarowy Parser JSON-stat 2.0 i Analiza Szeregu HICP
- **Problem uproszczonego parsera:** W strukturze JSON-stat 2.0 macierz wartości jest spłaszczona jednowymiarowo (`value: [...]` lub `value: {"<flat_index>": ...}`). Założenie `value[str(time_index)]` było poprawne tylko przy kostkach jednowymiarowych lub gdy wymiar czasowy był jedynym dynamicznym wymiarem o zerowych offsetach.
- **Implementacja matematyki strides w [`modules/connectors/eurostat.py`](file:///E:/Programy/PycharmProjects/polish-economy-agent/modules/connectors/eurostat.py):**
  - Dla wymiarów $d_0, d_1, \dots, d_{k-1}$ o rozmiarach $s_0, s_1, \dots, s_{k-1}$ obliczany jest wektor kroków (strides):
    $$\text{stride}_{k-1} = 1, \quad \text{stride}_i = \text{stride}_{i+1} \times s_{i+1}$$
  - Płaski indeks dla współrzędnych docelowych $c_0, c_1, \dots, c_{k-1}$ wynosi:
    $$\text{flat\_index} = \sum_{i=0}^{k-1} c_i \times \text{stride}_i$$
  - Konektor dynamicznie mapuje żądane filtry (`geo`, `unit`, `na_item`, `s_adj`, `coicop`) na współrzędne w danym wymiarze, wyznacza stały `base_offset` oraz bada każdy punkt w wymiarze `time`.
  - **Kontrola kompletności danych:** Parser zwraca metryki `total_periods`, `valid_periods`, `missing_periods` oraz `completeness_pct`, zapisywane w metadanych obserwacji.
- **Dlaczego szereg HICP w `prc_hicp_manr` kończy się na 2025-12:**
  - Badanie metadanych Eurostatu (`https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/prc_hicp_manr`) wykazało, że tabela `prc_hicp_manr` oparta jest na klasyfikacji **COICOP 1999** (`coicop=CP00`), a jej ostatnia aktualizacja miała miejsce `2026-02-06` z danymi do `2025-12`.
  - Dane miesięczne za rok 2026 przeszły w statystyce europejskiej na klasyfikację **COICOP 2018** i są publikowane w nowej tabeli wskaźników kluczowych Eurostatu `teicp000` (`coicop18=TOTAL`, `unit=PCH_M12`, zaktualizowana `2026-10-16` z najnowszym odczytem za 2026-09 na poziomie **4.0%**).
  - Parser poprawnie odczytuje wszystkie 348 obserwacji z tabeli `prc_hicp_manr` i odnotowuje w metadanych znacznik `dataset_updated`.

### 3. GUS BDL 60270: Weryfikacja Częstotliwości Rocznej (`ANNUAL`)
- **Fakt źródłowy:** Zapytanie do oficjalnego BDL dla zmiennej `60270` z poziomem `unit-level=0` zwraca tablicę 22 obserwacji w latach 2004–2025 (ostatnia: 2025 = **5.7%**). Żadna z obserwacji nie zawiera pola `month`.
- **Rygor częstotliwości:**
  - W `VERIFIED_BDL_VARIABLES` zmienna 60270 ma jawnie przypisany parametr `"frequency": "ANNUAL"`.
  - W metodzie `fetch_bdl_variable` wprowadzono rygor: jeśli obserwacja nie zawiera numeru miesiąca, otrzymuje bezwzględnie `frequency="ANNUAL"`.
  - W metadanych obserwacji zapisywane jest pole `frequency_confirmed: "ANNUAL"`.
  - Szereg ten **nie może zastępować miesięcznej stopy bezrobocia** (ani BAEL/LFS z Eurostatu, ani miesięcznych komunikatów MRPiPS/GUS).

### 4. Rozdzielenie `period_end` od Daty Publikacji (`publication_date`)
- **Fakt metodologiczny:** Publiczne API statystyczne (Eurostat JSON-stat, GUS BDL REST, GUS DBW) podają okres sprawozdawczy danych (początek i koniec miesiąca/kwartału/roku), lecz nie udostępniają indywidualnego znacznika czasu publikacji per punkt szeregu.
- **Wdrożona zmiana:**
  - Usunięto arbitralne kopiowanie wartości `period_end` do pola `publication_date`.
  - Jeśli API nie udostępnia oficjalnego timestampu publikacji danej obserwacji, w polu `publication_date` zapisywana jest wartość `None`.
  - Dla Eurostatu data publikacji/aktualizacji całego zbioru danych jest zachowywana w `metadata["dataset_updated"]`.
  - W NBP dla kursów walut i stóp procentowych data publikacji/obowiązywania jest jawnie określona w nagłówku tabeli lub pliku XML i jest zachowywana.

---

## 4. Weryfikacja Testów Offline i Integralności

1. **Pełen zestaw testów offline (`uv run pytest`):**
   ```text
   ============================= test session starts =============================
   platform win32 -- Python 3.11.16, pytest-9.2.0, pluggy-1.7.0
   rootdir: E:\Programy\PycharmProjects\polish-economy-agent
   configfile: pyproject.toml
   plugins: anyio-4.15.1, langsmith-0.12.4
   collected 105 items

   tests\test_ambiguous_formats.py .....                                    [  4%]
   tests\test_cache_freshness.py ......                                     [ 10%]
   tests\test_connectors.py .............................                   [ 38%]
   tests\test_database_init.py .....                                        [ 42%]
   tests\test_executive_horizon.py ........                                 [ 50%]
   tests\test_html_security.py .................                            [ 66%]
   tests\test_indicators_storage.py ......                                  [ 72%]
   tests\test_migrator.py ............                                      [ 83%]
   tests\test_record_updates.py .....                                       [ 88%]
   tests\test_schema_v2_design.py ............                              [100%]

   ============================= 105 passed in 5.47s =============================
   ```
   Wszystkie 105 testów zakończyło się sukcesem (100% green), w tym nowy dedykowany test wielowymiarowego parsera z kalkulacją kroków i kontrolą brakujących okresów (`test_multidimensional_jsonstat_parser_and_completeness_control`).

2. **Integralność bazy produkcyjnej:**
   - Plik [`instance/economy_agent.db`](file:///E:/Programy/PycharmProjects/polish-economy-agent/instance/economy_agent.db) pozostał nietknięty.
   - Rozmiar: **73 728 bajtów**.
   - Suma kontrolna SHA-256: `E6C5F318FFE1ECEEB34191A7A74EC9F7F7DE6069C4F298850792734277ECDE3B`.
