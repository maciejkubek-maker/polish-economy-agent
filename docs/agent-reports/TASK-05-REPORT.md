# Raport z Realizacji TASK-05 — Oficjalne Konektory API (NBP, Eurostat, GUS) — Aktualizacja po Code Review

**Data wykonania:** 2026-11-02  
**Autor:** Antigravity (DeepMind Agent)  
**Gałąź robocza:** `feature/data-platform-v2`  
**Commit SHA:** `6ab3c0d13912d32065c75ae54866704fe16d3d93`  
**Baza docelowa PR:** PR #4 (`feature/data-platform-v2` -> `main`)  
**Status zadania:** `COMPLETED` (Poprawki Code Review wdrożone)  

---

## 1. Cel i Zakres Prac

Zgodnie z poleceniem, standardem `AGENTS.md` (w tym zasadą 8 i 12 dotyczącą zakazu halucynacji i fikcyjnych identyfikatorów) oraz wytycznymi z Code Review PR #4, zaimplementowano i doprecyzowano oficjalne konektory:

1. **Narodowy Bank Polski (NBP):**
   - Średnie kursy walut EUR/PLN oraz USD/PLN z oficjalnego REST API (`https://api.nbp.pl/api/exchangerates/rates/A/{code}/?format=json`).
   - Stopa referencyjna NBP z oficjalnego pliku maszynowego XML (`https://static.nbp.pl/dane/stopy/stopy_procentowe.xml`).

2. **Eurostat (Statistics API 1.0 — JSON-stat 2.0) — Poprawka Eurostat GDP:**
   - HICP — Zharmonizowany Wskaźnik Cen Konsumpcyjnych (`prc_hicp_manr`).
   - Stopa bezrobocia zharmonizowanego wg BAEL/ILO (`une_rt_m`).
   - **Rygorystyczne rozdzielenie poziomu PKB od stóp dynamiki (`namq_10_gdp`):**
     * Wolumen/poziom PKB w cenach stałych w mln EUR (`unit=CLV10_MEUR`) zapisywany jest jako `PL_GDP_VOLUME` z jednostką `MEUR`.
     * Dynamika kw/kw (`unit=PCH_PRE`) zapisywana jest jako `PL_GDP_QOQ` z jednostką `PCT`.
     * Dynamika r/r (`unit=PCH_SM_PR_Y`) zapisywana jest jako `PL_GDP_YOY` z jednostką `PCT`.
     * Wyeliminowano błędne zapisywanie poziomu wolumenu jako `PL_GDP_QOQ` lub `INDEX_POINTS`.

3. **Główny Urząd Statystyczny (GUS) — Poprawki Okresu i Przeliczenia CPI:**
   - Stopa bezrobocia rejestrowanego (`PL_UNEMPLOYMENT_REGISTERED_RATE`) — zweryfikowane API BDL (`var_id=60270`).
   - Liczba bezrobotnych zarejestrowanych (`PL_UNEMPLOYMENT_REGISTERED_COUNT`) — zweryfikowane API BDL (`var_id=60269`).
   - **Wskaźnik CPI r/r z GUS DBW (zmienna 305, przekrój 736):**
     * **Ścisłe ustalanie miesiąca:** Miesiąc ustalany jest na podstawie potwierdzonych metadanych okresu DBW (standardowe kody miesięczne 247–258 lub 1–12) albo jawnego parametru `month`. Wyeliminowano zapisywanie miesięcznych wskaźników z zakresem rocznym (`01-01` do `12-31`). Gdy okresu nie da się ustalić, rzucany jest `ValidationError` (brak zgadywania).
     * **Metodologiczne przeliczanie indeksu:** Usunięto arbitralną heurystykę liczbową `wartosc > 50 => wartosc - 100`. Konwersja indeksu bazy 100 ("Analogiczny okres roku poprzedniego = 100") na stopę procentową r/r (`wartosc - 100.0`) odbywa się wyłącznie na podstawie potwierdzonej metodologii danej serii (`is_index_base_100=True`), a dla `as_percentage_change=False` zachowywana jest wartość surowa z jednostką `INDEX_POINTS`.
   - Dynamiczne wyszukiwanie zmiennych (`search_bdl_variables`) w celu bezpiecznego odkrywania bez ryzyka przestarzałych ID.
   - **Rygorystyczny zakaz fikcyjnych ID:** Wskaźniki wymagające zmapowania (`PL_WAGE_AVERAGE_GROSS`, `PL_INDUSTRIAL_PRODUCTION_YOY`, `PL_GDP_YOY`) podnoszą dedykowany wyjątek `VariableNotMappedError` przy próbie wywołania bez zweryfikowanego identyfikatora.

---

## 2. Podział Źródeł: Weryfikacja na Żywo vs Fixtures Offline

Zgodnie z wymaganiem Code Review, w dokumentacji jasno rozdzielono statusy weryfikacji źródeł:

| Instytucja | Źródło / Endpoint | Status weryfikacji specyfikacji live | Środowisko testowe | Uwagi |
|---|---|---|---|---|
| **NBP** | `api.nbp.pl/api/exchangerates/rates/A/{code}` | **Potwierdzony live** (dokumentacja Swagger NBP) | Mock fixture offline (`NBP_EUR_JSON`, `NBP_USD_JSON`) | Bezpłatne, publiczne REST API |
| **NBP** | `static.nbp.pl/dane/stopy/stopy_procentowe.xml` | **Potwierdzony live** (oficjalny plik maszynowy) | Mock fixture offline (`NBP_RATES_XML`) | Brak endpointu REST dla stóp w NBP |
| **Eurostat** | Dissemination API 1.0 (`prc_hicp_manr`) | **Potwierdzony live** (Eurostat API 1.0) | Mock fixture offline (`EUROSTAT_HICP_JSON`) | JSON-stat 2.0, HICP r/r |
| **Eurostat** | Dissemination API 1.0 (`une_rt_m`) | **Potwierdzony live** (Eurostat API 1.0) | Mock fixture offline (`EUROSTAT_UNEMPLOYMENT_JSON`) | Standard BAEL/ILO |
| **Eurostat** | Dissemination API 1.0 (`namq_10_gdp`) | **Potwierdzony live** (Eurostat API 1.0) | Mock fixture offline (`PCH_PRE`, `PCH_SM_PR_Y`, `CLV10_MEUR`) | Wyraźne rozdzielenie miar: wolumen vs dynamika |
| **GUS** | BDL API v1 (`var_id=60270`, `60269`) | **Potwierdzony live** (słownik BDL) | Mock fixture offline (`GUS_BDL_UNEMPLOYMENT_JSON`) | Stopa i liczba bezrobotnych |
| **GUS** | DBW API v1.1.0 (`var_id=305`, `przekroj=736`) | **Potwierdzony live** (katalog DBW) | Mock fixture offline (`GUS_DBW_CPI_JSON`) | CPI r/r, baza 100, kody okresów 247-258 |
| **GUS** | Wynagrodzenia, produkcja przemysłowa, PKB | **Wymaga mapowania live** | Testy blokady `VariableNotMappedError` | Zakaz fikcyjnych ID; odkrywanie przez `search_bdl_variables()` |

---

## 3. Zgodność Schematu SQLite v2 (Jednostki i Wskaźniki)

Tabela `unit_catalog` w `docs/sql/schema_v2.sql` oraz `BaseConnector.ALLOWED_UNITS` zostały w 100% zsynchronizowane:
- `PCT` (Procent, `%`)
- `EUR_PLN` (Kurs walutowy EUR, `zł/EUR`)
- `USD_PLN` (Kurs walutowy USD, `zł/USD`)
- `MEUR` (Miliony euro dla wolumenu PKB, `mln EUR`)
- `PLN` oraz `PLN_PER_MONTH` (dla wynagrodzeń)
- `THOUSAND_PERSONS` oraz `PERSONS` (dla rynku pracy)
- `INDEX_POINTS` oraz `RATIO`

---

## 4. Wyniki Testów po Wdrożeniu Poprawek

### A. Testy Konektorów (`tests/test_connectors.py`):
Utworzono 28 testów jednostkowych i integracyjnych działających w 100% offline:
- 6 testów NBP (kursy EUR/USD, XML stóp, obsługa błędów)
- 7 testów Eurostat (HICP, bezrobocie BAEL, dynamika kw/kw, dynamika r/r, wolumen w MEUR, rozdzielenie definicji, walidacja wymiarów)
- 9 testów GUS (stopa i liczba bezrobotnych BDL, CPI okres miesięczny, jawny parametr miesiąca, błąd nieznanego okresu, metodologia konwersji bazy 100 bez heurystyk, wyszukiwanie zmiennych, zakaz fikcyjnych ID)
- 6 testów BaseConnector (blokada sieci w trybie offline, czyszczenie liczb, zakresy, daty ISO, jednostki, SHA-256 dowodów)

**Wynik:**
```
tests/test_connectors.py: 28 passed in 0.13s (100% green)
```

### B. Pełny Zestaw Testów Repozytorium:
```
============================ 104 passed in 8.60s =============================
```
Wszystkie 104 testy w repozytorium przeszły pomyślnie.

### C. Nienaruszalność Bazy Legacy:
- Ścieżka: `instance/economy_agent.db`
- Rozmiar: dokładnie **73 728 bajtów**
- Suma SHA-256: `E6C5F318FFE1ECEEB34191A7A74EC9F7F7DE6069C4F298850792734277ECDE3B` (stan nienaruszony).
