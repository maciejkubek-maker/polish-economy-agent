# Raport LIVE SMOKE TESTS Oficjalnych Publicznych API (NBP, Eurostat, GUS)

**Data wykonania:** 2026-11-02 18:46:00 UTC (19:46:00 CET)  
**Autor:** Antigravity (DeepMind Agent)  
**Gałąź robocza:** `feature/data-platform-v2`  
**PR:** [Draft PR #4](https://github.com/maciejkubek-maker/polish-economy-agent/pull/4)  
**Status całościowy:** `12 VERIFIED, 1 NOT_VERIFIED, 0 FAILED`  
**Integralność bazy legacy:** `instance/economy_agent.db` — 73 728 bajtów, SHA-256 `E6C5F318FFE1ECEEB34191A7A74EC9F7F7DE6069C4F298850792734277ECDE3B` (nietknięta).

---

## 1. Cel i Rygorystyczne Zasady Wykonania

Zgodnie z wytycznymi weryfikacji przed scaleniem PR #4 przeprowadzono **LIVE SMOKE TESTS** bezpośrednio na oficjalnych serwerach API instytucji statystycznych i monetarnych (Narodowy Bank Polski, Eurostat, Główny Urząd Statystyczny), a następnie zaadresowano wszystkie uwagi z ostatniego przeglądu bezpieczeństwa danych:

1. **Zero fikcyjnych danych i zero zgadywania (Rule 8 & 12 AGENTS.md):** Nie użyto żadnych płatnych API ani modeli zewnętrznych (Gemini, GPT, Tavily) do uzupełniania brakujących wartości.
2. **Uczciwe statusy (Reporting Integrity):** Żaden niedziałający lub wycofany endpoint nie został fałszywie oznaczony jako zweryfikowany na podstawie fixture offline.
3. **Nienaruszalność bazy produkcyjnej:** Żadne dane live nie trafiły do produkcyjnej bazy SQLite.
4. **Bezpieczeństwo danych GUS — blokada nadawania statusu VERIFIED przez wywołującego:** Usunięto możliwość nadawania statusu VERIFIED wyłącznie na podstawie przekazanego przez wywołującego słownika `verified_mapping`. Status VERIFIED wolno nadać dopiero po sprawdzeniu identyfikatora zmiennej, definicji, jednostki i częstotliwości w rzeczywistych metadanych oficjalnego API GUS lub w osobnym, wcześniej zatwierdzonym rejestrze mapowań (`APPROVED_BDL_REGISTRY`). Kompletny, lecz fikcyjny słownik metadanych nie ma prawa nadać statusu VERIFIED (pozostaje `NOT_VERIFIED`).
5. **Rozdzielenie bieżącego i archiwalnego HICP Eurostatu oraz strażnik świeżości danych:** Bieżąca seria pobierana jest z tabeli wskaźników kluczowych `teicp000` (COICOP 2018), a `prc_hicp_manr` (COICOP 1999) funkcjonuje jako zbiór archiwalny. Wdrożono rygorystyczny mechanizm kontroli świeżości (`StaleDataError`), blokujący prezentowanie odczytu z 2025 r. jako aktualnego w 2026 r.
6. **Wielowymiarowy parser JSON-stat 2.0 ze stride math:** Wyeliminowano uproszczone indeksowanie tablic, wprowadzając pełne adresowanie w wielowymiarowych kostkach Eurostatu wraz z kontrolą kompletności.
7. **Rozdzielenie okresu od daty publikacji:** Usunięto sztuczne wpisywanie `period_end` jako daty publikacji dla API, które nie udostępniają znacznika czasu publikacji per obserwacja.
8. **Rygor częstotliwości:** Roczne serie GUS BDL zostały jawnie oznaczone jako `ANNUAL` z zakazem zastępowania miesięcznych stóp bezrobocia.

---

## 2. Zbiorcza Tabela Wyników Live Smoke Tests

| # | Instytucja | Endpoint / Wskaźnik | HTTP | Czas | Typ odpowiedzi | Status | Zweryfikowana Wartość / Okres / Jednostka | SHA-256 RAW |
|---|---|---|---|---|---|---|---|---|
| 1 | **NBP** | Kurs średni EUR/PLN (Tabela A) | **200** | 185 ms | JSON | `VERIFIED` | **4.4185 EUR_PLN** (2026-11-02, tab. 213/A/NBP/2026) | `2f3c004fef...` |
| 2 | **NBP** | Kurs średni USD/PLN (Tabela A) | **200** | 142 ms | JSON | `VERIFIED` | **3.9389 USD_PLN** (2026-11-02, tab. 213/A/NBP/2026) | `9141bba106...` |
| 3 | **NBP** | Stopa referencyjna (Oficjalny XML) | **200** | 182 ms | XML | `VERIFIED` | **3.75 PCT** (od 2026-03-05, pozycja `id="ref"`) | `1b945a7924...` |
| 4 | **Eurostat** | HICP r/r bieżąca (teicp000, COICOP 2018) | **200** | 276 ms | JSON-stat 2.0 | `VERIFIED` | **4.0 PCT** (2026-09-01 – 2026-09-30, 12 obs) | `9d21e885e4...` |
| 5 | **Eurostat** | HICP r/r archiwalna (prc_hicp_manr, COICOP 1999) | **200** | 234 ms | JSON-stat 2.0 | `VERIFIED` | **2.5 PCT** (2025-12-01 – 2025-12-31, 348 obs) | `e1cbec36c3...` |
| 6 | **Eurostat** | Stopa bezrobocia BAEL (une_rt_m, geo=PL) | **200** | 241 ms | JSON-stat 2.0 | `VERIFIED` | **3.4 PCT** (2026-09-01 – 2026-09-30, 357 obs) | `19799726a5...` |
| 7 | **Eurostat** | PKB kw/kw (PL_GDP_QOQ, namq_10_gdp) | **200** | 191 ms | JSON-stat 2.0 | `VERIFIED` | **1.1 PCT** (2026-04-01 – 2026-06-30 / 2026-Q2, 125 obs) | `79493d67f3...` |
| 8 | **Eurostat** | PKB r/r (PL_GDP_YOY, namq_10_gdp) | **200** | 197 ms | JSON-stat 2.0 | `VERIFIED` | **4.0 PCT** (2026-04-01 – 2026-06-30 / 2026-Q2, 122 obs) | `2349718d2f...` |
| 9 | **Eurostat** | PKB wolumen w cenach stałych (PL_GDP_VOLUME) | **200** | 216 ms | JSON-stat 2.0 | `VERIFIED` | **154972.9 MEUR** (2026-04-01 – 2026-06-30 / 2026-Q2, 126 obs) | `278ce95e40...` |
| 10 | **GUS BDL** | Stopa bezrobocia rejestrowanego (var 60270) | **200** | 2609 ms | JSON | `VERIFIED` | **5.7 PCT** (2025-01-01 – 2025-12-31, 22 obs roczne) | `fcbf0e94ed...` |
| 11 | **GUS BDL** | Liczba bezrobotnych zarejestrowanych (var 60269) | **404** / timeout | 1851 ms | JSON | `NOT_VERIFIED` | *Brak zasobu w publicznym BDL (HTTP 404 / Zasób nie istnieje)* | *(zablokowane)* |
| 12 | **GUS DBW** | CPI r/r (zmienna 305, przekrój 736) | **200** | 255 ms | JSON | `VERIFIED` | **0.1 PCT** (2024-09-01 – 2024-09-30, indeks 100.1 - 100) | `0a8a5db979...` |
| 13 | **GUS DBW** | Słownik okresów DBW (okresy 247–258) | **200** | 204 ms | JSON | `VERIFIED` | **247=styczeń, 255=wrzesień, 258=grudzień** (50 poz) | `e081be7f22...` |

---

## 3. Szczegółowe Rozstrzygnięcie Zgłoszonych Uwag

### 1. Bezpieczeństwo Danych GUS: Blokada Nadawania Statusu VERIFIED przez Wywołującego
- **Zasada zerowego zaufania do słowników wywołującego:** W [`modules/connectors/gus.py`](file:///E:/Programy/PycharmProjects/polish-economy-agent/modules/connectors/gus.py) usunięto możliwość nadawania statusu `VERIFIED` wyłącznie na podstawie przekazania przez wywołującego słownika `verified_mapping`.
- **Weryfikacja dwutorowa (API lub Rejestr):**
  1. **Osobny rejestr zatwierdzony (`APPROVED_BDL_REGISTRY`):** Jeśli zmienna znajduje się w statycznie zweryfikowanym i audytowanym rejestrze (np. 60270), otrzymuje status `VERIFIED` z powodem `VERIFIED_PREAPPROVED_REGISTRY`.
  2. **Rzeczywiste metadane API GUS ([`verify_bdl_variable_metadata`](file:///E:/Programy/PycharmProjects/polish-economy-agent/modules/connectors/gus.py#L95-L145)):** Konektor odpytuje endpoint metadanych BDL `GET /variables/{var_id}` i sprawdza tożsamość zmiennej, jednostkę miary (`measureUnitName`), definicję (`n1`/`subjectId`) oraz strukturę okresu.
- **Odporność na fikcyjne metadane:** Przekazanie kompletnego, lecz fikcyjnego słownika (np. nieistniejącego w API GUS ID `999999`) **nie ma prawa nadać statusu VERIFIED**. Status pozostaje bezwzględnie jako `NOT_VERIFIED` (z powodem `VARIABLE_NOT_FOUND_IN_OFFICIAL_GUS_API`).

### 2. Eurostat HICP: Rozdzielenie `teicp000` (COICOP 2018) od `prc_hicp_manr` oraz Strażnik Świeżości Danych
- **Bieżąca seria HICP:** Wdrożono pobieranie z oficjalnej tabeli wskaźników kluczowych Eurostatu `teicp000` (`coicop18=TOTAL`, `unit=PCH_M12`, `geo=PL`). Zwraca ona 12-miesięczny kroczący szereg oparty na klasyfikacji COICOP 2018, z najnowszą obserwacją za **2026-09** wynoszącą **4.0% r/r**.
- **Seria archiwalna:** Tabela `prc_hicp_manr` (`coicop=CP00`, COICOP 1999) została zachowana jako seria archiwalna (`classification="COICOP_1999_ARCHIVAL"`, `is_archival=True`), kończąca się na grudniu 2025 r. (**2.5% r/r**).
- **Strażnik świeżości ([`validate_series_freshness`](file:///E:/Programy/PycharmProjects/polish-economy-agent/modules/connectors/eurostat.py#L248-L260) / [`StaleDataError`](file:///E:/Programy/PycharmProjects/polish-economy-agent/modules/connectors/base.py#L35-L39)):**
  - Uniemożliwia prezentowanie przeterminowanych danych jako aktualnych.
  - Jeśli seria kończy się przed 2026 r., rzucany jest wyjątek `StaleDataError`.

### 3. GUS BDL 60269: Wycofanie, Blokowanie i Analiza Metadanych GUS
- **Stan w API:** Wywołanie `https://bdl.stat.gov.pl/api/v1/data/by-variable/60269` zwraca w API GUS błąd **HTTP 404 Not Found** (`errorCode: 3, errorResult: "Zasób nie istnieje"`).
- **Zastosowane rozwiązanie:**
  - Zmienna `60269` została całkowicie usunięta ze słowników zweryfikowanych.
  - Wskaźnik `PL_UNEMPLOYMENT_REGISTERED_COUNT` został oznaczony jako `NOT_VERIFIED`.
  - Wywołanie `fetch_registered_unemployment_count()` bez parametrów i bez zatwierdzonego mapowania rzuca `VariableNotMappedError`.

### 4. Eurostat: Wielowymiarowy Parser JSON-stat 2.0 i Matematyka Strides
- Dla wymiarów $d_0, d_1, \dots, d_{k-1}$ o rozmiarach $s_0, s_1, \dots, s_{k-1}$ obliczany jest wektor kroków:
  $$\text{stride}_{k-1} = 1, \quad \text{stride}_i = \text{stride}_{i+1} \times s_{i+1}$$
- Płaski indeks dla współrzędnych docelowych $c_0, c_1, \dots, c_{k-1}$ wynosi:
  $$\text{flat\_index} = \sum_{i=0}^{k-1} c_i \times \text{stride}_i$$
- Kontrola kompletności danych zwraca metryki `total_periods`, `valid_periods`, `missing_periods` oraz `completeness_pct`.

### 5. GUS BDL 60270: Weryfikacja Częstotliwości Rocznej (`ANNUAL`)
- Zapytanie do oficjalnego BDL dla zmiennej `60270` zwraca tablicę obserwacji rocznych bez pola `month`.
- W `APPROVED_BDL_REGISTRY` zmienna 60270 ma parametr `"frequency": "ANNUAL"`.
- Szereg ten **nie może zastępować miesięcznej stopy bezrobocia**.

### 6. Rozdzielenie `period_end` od Daty Publikacji (`publication_date`)
- Usunięto arbitralne kopiowanie wartości `period_end` do pola `publication_date`.
- Jeśli API nie udostępnia oficjalnego timestampu publikacji danej obserwacji, w polu `publication_date` zapisywana jest wartość `None`.

---

## 4. Weryfikacja Testów Offline i Integralności

1. **Pełen zestaw testów offline (`uv run pytest`):**
   ```text
   ============================= test session starts =============================
   platform win32 -- Python 3.11.16, pytest-9.2.0, pluggy-1.7.0
   rootdir: E:\Programy\PycharmProjects\polish-economy-agent
   configfile: pyproject.toml
   plugins: anyio-4.15.1, langsmith-0.12.4
   collected 113 items

   tests\test_ambiguous_formats.py .....                                    [  4%]
   tests\test_cache_freshness.py ......                                     [  9%]
   tests\test_connectors.py .....................................           [ 42%]
   tests\test_database_init.py .....                                        [ 46%]
   tests\test_executive_horizon.py ........                                 [ 53%]
   tests\test_html_security.py .................                            [ 69%]
   tests\test_indicators_storage.py ......                                  [ 74%]
   tests\test_migrator.py ............                                      [ 84%]
   tests\test_record_updates.py .....                                       [ 89%]
   tests\test_schema_v2_design.py ............                              [100%]

   ============================= 113 passed in 5.57s =============================
   ```
   Wszystkie 113 testów zakończyło się sukcesem (100% green), w tym dedykowane testy:
   - `test_fetch_registered_unemployment_count_fictitious_mapping_cannot_grant_verified` (potwierdzenie, że fikcyjne metadane nie nadają statusu VERIFIED)
   - `test_fetch_registered_unemployment_count_preapproved_registry_succeeds_as_verified` (potwierdzenie nadania VERIFIED przez approved registry)
   - `test_fetch_registered_unemployment_count_verified_via_official_gus_api_metadata` (potwierdzenie nadania VERIFIED przez metadane GUS API)
   - `test_fetch_registered_unemployment_count_arbitrary_var_id_remains_not_verified`
   - `test_fetch_registered_unemployment_count_incomplete_mapping_raises_validation_error`
   - `test_fetch_registered_unemployment_count_blocks_unmapped_call`
   - `test_fetch_hicp_teicp000_coicop_2018_default_success`
   - `test_fetch_hicp_archival_prc_hicp_manr_success`
   - `test_hicp_freshness_guard_blocks_2025_reading_in_2026`

2. **Integralność bazy produkcyjnej:**
   - Plik [`instance/economy_agent.db`](file:///E:/Programy/PycharmProjects/polish-economy-agent/instance/economy_agent.db) pozostał nietknięty.
   - Rozmiar: **73 728 bajtów**.
   - Suma kontrolna SHA-256: `E6C5F318FFE1ECEEB34191A7A74EC9F7F7DE6069C4F298850792734277ECDE3B`.
