# Plan Bezstratnej Migracji Danych Legacy (Migration v2 Plan)

**Status:** `PROPOSED` (projekt procedury — **BEZ WYKONYWANIA MIGRACJI** na pliku produkcyjnym)  
**Dokument powiązany:** `tasks/TASK_03_SCHEMA_DESIGN.md`, `docs/MIGRATION.md`, `docs/BASELINE.md`  
**Data sporządzenia:** 2026-11-02  

---

## 1. Cel i Główne Zasady Migracji

Celem niniejszego dokumentu jest zdefiniowanie kompletnej, deterministycznej i w 100% odwracalnej procedury migracji dotychczasowych danych z bazy `instance/economy_agent.db` do nowego modelu danych SQLite v2.

### Żelazne reguły:
1. **Zero Data Loss (Ani jeden rekord nie ginie):** Wszystkie 75 rekordów z `collected_indicators`, 10 rekordów z `trusted_sources` oraz 6 rekordów z `generated_reports` muszą zostać w całości przeniesione do warstwy dowodowej i kandydatów.
2. **Brak bezpośrednich modyfikacji bazy źródłowej:** Plik `instance/economy_agent.db` jest traktowany jako baza archiwalna i otwierany wyłącznie w trybie `mode=ro`.
3. **Rozdzielenie danych pewnych od niepewnych:** Żadna wartość wieloznaczna lub potencjalnie błędna nie może zostać automatycznie „zgadnięta” jako fakt w tabeli `observations`. Trafia do tabeli `extracted_candidates` z powiązanym wpisem w `quality_events` ze statusem `MIGRATED_PENDING` lub `MIGRATED_CONFLICT`.
4. **Idempotencja i rollback:** Uruchomienie procedury powtórnie musi dać identyczny rezultat bez duplikowania danych. Wycofanie procedury (rollback) polega na usunięciu nowego pliku roboczego bazy.

---

## 2. Inwentaryzacja i Klasyfikacja 75 Rekordów `collected_indicators`

Baza bazowa zawiera 75 wskaźników zebranych przez dwóch agentów (`GPTAgent`: 42, `GeminiAgent`: 33) dla kraju `Polska`. Analiza wykazała występowanie 24 odrębnych wariantów nazw tekstowych, które podzielono na 3 grupy analityczne:

### Grupa 1: Wskaźniki o jednoznacznym mapowaniu (47 rekordów)
Wskaźniki, których definicja, jednostka i okres nie budzą wątpliwości metodologicznych:

| Wariant nazwy legacy | Liczba | Proponowany `indicator_code` | Jednostka docelowa | Status migracji |
|---|---|---|---|---|
| `Inflacja CPI r/r` | 8 | `PL_CPI_YOY` | `PCT` | `MIGRATED_VERIFIED` |
| `Inflacja CPI m/m` / `Inflacja m/m` | 2 | `PL_CPI_MOM` | `PCT` | `MIGRATED_VERIFIED` |
| `Produkcja przemysłowa r/r` | 3 | `PL_INDUSTRIAL_PRODUCTION_YOY` | `PCT` | `MIGRATED_VERIFIED` |
| `Produkcja budowlano-montażowa r/r` | 2 | `PL_CONSTRUCTION_PRODUCTION_YOY` | `PCT` | `MIGRATED_VERIFIED` |
| `Sprzedaż detaliczna r/r` | 2 | `PL_RETAIL_SALES_YOY` | `PCT` | `MIGRATED_VERIFIED` |
| `Produkt Krajowy Brutto kw/kw` | 1 | `PL_GDP_QOQ` | `PCT` | `MIGRATED_VERIFIED` |
| `Przeciętne wynagrodzenia` / `Przeciętne Wynagrodzenia` | 3 | `PL_WAGE_AVERAGE_GROSS` | `PLN_PER_MONTH` | `MIGRATED_VERIFIED` |
| `Stopa referencyjna NBP` | 1 | `PL_NBP_REFERENCE_RATE` | `PCT` | `MIGRATED_VERIFIED` |
| `Purchasing Managers' Index (PMI) Polska` | 1 | `PL_PMI_MANUFACTURING` | `INDEX_POINTS` | `MIGRATED_VERIFIED` |
| `Stopa bezrobocia rejestrowanego` | 13 | `PL_UNEMPLOYMENT_REGISTERED_RATE` | `PCT` | `MIGRATED_VERIFIED` |
| `Stopa bezrobocia rejestrowanego (GUS)` | 6 | `PL_UNEMPLOYMENT_REGISTERED_RATE` | `PCT` | `MIGRATED_VERIFIED` |
| `Liczba zarejestrowanych bezrobotnych` | 9 | `PL_UNEMPLOYMENT_REGISTERED_COUNT` | `THOUSAND_PERSONS` | `MIGRATED_VERIFIED` |
| **Razem** | **51** | | | |

---

### Grupa 2: Synonimy i uogólnienia wymagające weryfikacji kontekstowej (15 rekordów)
Wpisy, w których nazwa ogólna w rzeczywistości reprezentuje wskaźnik rejestrowany:

| Wariant nazwy legacy | Rekordy ID | Kontekst wartości i źródła | Proponowany `indicator_code` | Status migracji |
|---|---|---|---|---|
| `Stopa bezrobocia` | 6, 14, 20, 46, 48, 49, 51 | Wartości (5,8%, 6,1%, 5,6%, 6,0%), źródło GUS/Bankier. Dotyczy bezrobocia rejestrowanego, a nie BAEL. | `PL_UNEMPLOYMENT_REGISTERED_RATE` | `MIGRATED_VERIFIED` (z notatką audytową) |
| `Liczba bezrobotnych` | 28, 30, 34, 36 | Wartości (956,2 tys., 906,4 tys.), źródło GUS. Odpowiada liczbie bezrobotnych zarejestrowanych. | `PL_UNEMPLOYMENT_REGISTERED_COUNT` | `MIGRATED_VERIFIED` (z notatką audytową) |
| `Bezrobotni zarejestrowani` | 9, 18 | Wartość 906,40 tys. za VII 2026. Synonim liczby zarejestrowanych. | `PL_UNEMPLOYMENT_REGISTERED_COUNT` | `MIGRATED_VERIFIED` |
| `Inflacja bazowa (...)` (3 warianty pisowni) | 45, 58, 64, 69 | Wartość 3,1% za VII 2026, źródło NBP. Tożsamy wskaźnik. | `PL_CORE_INFLATION_YOY` | `MIGRATED_VERIFIED` |
| **Razem** | **17** | | | |

---

### Grupa 3: Przypadki sporne, konflikty rewizyjne i niejednoznaczności (7 rekordów)
Wymagają utworzenia zdarzenia w `quality_events` i statusu `MIGRATED_PENDING` lub `MIGRATED_CONFLICT`:

1. **Konflikt szacunku PKB r/r za II kw. 2026 (4 rekordy):**
   - Rekordy 3 i 8 (`Produkt Krajowy Brutto r/r`): wartość `3,90%`, źródło Bankier.pl / GUS.
   - Rekordy 32 i 38 (`PKB r/r`): wartość `3,8%`, źródło Główny Urząd Statystyczny (GUS).
   - **Diagnoza:** Klasyczny konflikt typu flash estimate (szybki szacunek 3,9%) vs szacunek wstępny/skorygowany (3,8%).
   - **Postępowanie:** Oba odczyty zostają zapisane w `extracted_candidates`. W `observations` wartość 3,8% zostaje oznaczona jako wersja nowsza (`is_latest=1`, `revision_type='PRELIMINARY'`), a 3,9% jako `SUPERSEDED` (`revision_type='FLASH'`), z wpisem w `quality_events` (`RULE_REVISION_DETECTED`).
2. **Błędna etykieta „r/r” dla poziomu stopy bezrobocia (2 rekordy):**
   - Rekordy 33 i 35 (`Stopa bezrobocia r/r`): wartości `6,1%` (luty 2026) oraz `5,8%` (lipiec 2026), zgłoszone przez `GPTAgent`.
   - **Diagnoza:** Agent błędnie dodał przyrostek "r/r" do stopy rejestrowanej, która jest wskaźnikiem poziomu, a nie dynamiki.
   - **Postępowanie:** Zapisanie w `extracted_candidates` z flagą `MIGRATED_PENDING`, wpis w `quality_events` (`RULE_MISLABELED_INDICATOR_NAME`).
3. **Odrębny wskaźnik strumienia: nowo zarejestrowani (1 rekord):**
   - Rekord 65 (`Liczba nowo zarejestrowanych bezrobotnych`): wartość `93,0 tys.` za XI 2025.
   - **Diagnoza:** Jest to napływ do bezrobocia (flow), a nie stan zasobu bezrobotnych (stock). Próba scalenia z liczbą ogólną bezrobotnych sfałszowałaby dane o 90%.
   - **Postępowanie:** Przypisanie dedykowanego kodu `PL_UNEMPLOYMENT_NEW_REGISTERED_COUNT`, status `MIGRATED_VERIFIED`.

---

## 3. Plan Mapowania Tabel `trusted_sources` i `generated_reports`

### 3.1. `trusted_sources` (10 rekordów) -> `source_registry`
Wszystkie 10 oficjalnych domen i portali zostaje bezstratnie przeniesionych do `source_registry`:
- `Główny Urząd Statystyczny (GUS)` -> `SRC_GUS` (TIER_A)
- `Narodowy Bank Polski (NBP)` -> `SRC_NBP` (TIER_A)
- `Ministerstwo Finansów` -> `SRC_MF` (TIER_A)
- `Eurostat` -> `SRC_EUROSTAT` (TIER_A)
- `Międzynarodowy Fundusz Walutowy (IMF)` -> `SRC_IMF` (TIER_A)
- `OECD` -> `SRC_OECD` (TIER_A)
- `Komisja Europejska` -> `SRC_EC` (TIER_A)
- `Bank Światowy` -> `SRC_WB` (TIER_A)
- `Polski Instytut Ekonomiczny (PIE)` -> `SRC_PIE` (TIER_B)
- `Giełda Papierów Wartościowych w Warszawie (GPW)` -> `SRC_GPW` (TIER_B)

### 3.2. `generated_reports` (6 rekordów) -> `reports`
- Każdy z 6 historycznych raportów zostaje zapisany z zachowaniem oryginalnego `content_markdown`.
- Wyliczony zostaje `data_snapshot_hash` na podstawie powiązanych obserwacji.
- `as_of_utc` zostaje zmapowany z kolumny `created_at` (18.09.2026).
- Raporty w tabeli legacy otrzymują wpis w `legacy_migration_map` z mapowaniem `legacy_id -> report_id`.

---

## 4. Parser Formatów Wartości i Okresów

Dla każdego rekordu parser wykonuje następujące operacje w sposób w 100% zdeterminowany:

### 4.1. Normalizacja wartości liczbowej:
```python
# Przykłady przekształceń:
"5,80%"           -> value_decimal = "5.80",   unit_code = "PCT"
"-2,40%"          -> value_decimal = "-2.40",  unit_code = "PCT"
"906,40 tys."     -> value_decimal = "906.40", unit_code = "THOUSAND_PERSONS"
"9233,13 zł"      -> value_decimal = "9233.13",unit_code = "PLN_PER_MONTH"
"48,30 pkt"       -> value_decimal = "48.30",  unit_code = "INDEX_POINTS"
```

### 4.2. Rozwiązywanie okresów statystycznych:
```python
# Format rzymski z rokiem:
"VII 2026"        -> period_start = "2026-07-01", period_end = "2026-07-31", frequency = "MONTHLY"
# Format słowny z rokiem:
"lipiec 2026"     -> period_start = "2026-07-01", period_end = "2026-07-31", frequency = "MONTHLY"
# Format kwartalny:
"II kw. 2026"     -> period_start = "2026-04-01", period_end = "2026-06-30", frequency = "QUARTERLY"
# Formaty niejednoznaczne (np. "II 2026", "IV 2026"):
# Weryfikowane po częstotliwości wskaźnika: dla CPI/bezrobocia -> miesiąc; dla PKB bez słowa "kw." -> flaga PENDING.
```

---

## 5. Procedura Wykonawcza Krok po Kroku (Dry-Run i Cutover)

```mermaid
sequenceDiagram
    autonumber
    participant DEV as Migrator CLI
    participant LEG as instance/economy_agent.db (READ ONLY)
    participant BAK as Backup Storage
    participant NEW as instance/economy_agent_v2.db

    DEV->>BAK: 1. Weryfikacja fizycznego backupu i SHA-256
    DEV->>LEG: 2. Odczyt rekordów w trybie read-only
    DEV->>NEW: 3. Inicjalizacja DDL schema_v2.sql
    DEV->>NEW: 4. Import source_registry (10)
    DEV->>NEW: 5. Import reports (6)
    DEV->>NEW: 6. Import source_evidence + extracted_candidates (75)
    DEV->>NEW: 7. Walidacja i zapis observations + quality_events
    DEV->>NEW: 8. Zapis legacy_migration_map (91 powiązań)
    DEV->>NEW: 9. Weryfikacja bilansu rekordów: 75 wejść == 75 kandydatów
    Note over DEV,NEW: Dry-run zakończony. Raport gotowy do akceptacji.
```

### Plan Wycofania (Rollback):
W przypadku jakichkolwiek problemów podczas testów migracji, baza docelowa jest kasowana. Plik `instance/economy_agent.db` nie ulega zmianie w żadnej fazie procesu.
