# TASK-04 — raport Antigravity / Codex (Aktualizacja po Code Review)

**Status:** `DONE`  
**Branch:** `feature/data-platform-v2`  
**PR:** `https://github.com/maciejkubek-maker/polish-economy-agent/pull/4`  
**Data:** 2026-11-02  

## Co wykonałem

Zaimplementowałem produkcyjnej jakości migrator danych ze starszej bazy SQLite v1 do modelu SQLite v2 ([`modules/migrator.py`](file:///E:/Programy/PycharmProjects/polish-economy-agent/modules/migrator.py)) wraz z pełnym zestawem testów regresyjnych, integralności i bezpieczeństwa ([`tests/test_migrator.py`](file:///E:/Programy/PycharmProjects/polish-economy-agent/tests/test_migrator.py)).

### Główne elementy implementacji i poprawki po Code Review:
1. **Ochrona bazy źródłowej:**
   - Baza legacy (`instance/economy_agent.db`) jest otwierana wyłącznie przez URI SQLite w trybie READ-ONLY: `file:...mode=ro`.
   - Zaimplementowano bezwzględny zakaz nadpisywania bazy źródłowej (próba wskazania ścieżki docelowej równej źródłowej rzuca `ValueError`).
   - Aplikacja produkcyjna (`app.py`, `modules/database.py`) **nie została** przełączona na bazę v2.
2. **Bezstratny transfer 75/10/6 i audytowalność:**
   - 10 źródeł z `trusted_sources` przeniesiono do `source_registry`.
   - 6 raportów z `generated_reports` przeniesiono do `reports` z zachowaniem oryginalnego `content_markdown`, znormalizowaną datą ISO `YYYY-MM-DD` (`report_date`) oraz 64-znakowym skrótem SHA-256 (`data_snapshot_hash`).
   - 75 wskaźników z `collected_indicators` przeniesiono do `source_evidence` i `extracted_candidates`.
   - 91 powiązań zarejestrowano w `legacy_migration_map`.
3. **Precyzyjne pochodzenie źródeł (provenance — poprawka CR):**
   - Usunięto arbitralne przypisywanie wszystkich nieznanych źródeł do GUS (`SRC_LEGACY_1`).
   - Wyodrębniono zewnętrzne portale finansowe:
     * `Bankier.pl` (11 rekordów) -> zarejestrowane jako `SRC_EXTERNAL_BANKIER` (`https://www.bankier.pl`, `trust_tier='TIER_C'`).
     * `Trading Economics` (4 rekordy) -> zarejestrowane jako `SRC_EXTERNAL_TRADING_ECONOMICS` (`https://tradingeconomics.com`, `trust_tier='TIER_C'`).
   - Źródła niejednoznaczne / kompozytowe:
     * `Główny Urząd Statystyczny / Bankier.pl` (6 rekordów) -> `SRC_COMPOSITE_GUS_BANKIER`.
     * `Narodowy Bank Polski / Bankier.pl` (1 rekord) -> `SRC_COMPOSITE_NBP_BANKIER`.
     * Wszystkie 7 wskaźników z kompozytowym źródłem oznaczono w `quality_events` regułą `RULE_AMBIGUOUS_SOURCE_PROVENANCE` (severity `WARNING`) oraz statusem `MIGRATED_PENDING` (oczekiwanie na weryfikację biuletynu pierwotnego).
   - Zachowano dokładne linki `page_info` w `source_evidence.source_url`. W przypadku braku linku zastosowano fallback do bazowego adresu URL danego źródła (zamiast uniwersalnego `stat.gov.pl`).
4. **Brak zgadywania w rozstrzyganiu konfliktów:**
   - Rozbieżność PKB r/r za II kw. 2026 (3.90% vs 3.8%) została oznaczona statusem `MIGRATED_CONFLICT` z wpisem zdarzenia w `quality_events` (`RULE_SOURCE_DISCREPANCY`).
   - Błędna etykieta „Stopa bezrobocia r/r” została oznaczona jako `MIGRATED_PENDING` z wpisem w `quality_events` (`RULE_MISLABELED_INDICATOR_NAME`).
   - Łączny bilans klasyfikacji: 63 VERIFIED, 8 PENDING (2 nazwy + 6 źródeł), 4 CONFLICT. Łącznie 13 zdarzeń jakości.
5. **Transakcyjność i idempotencja:**
   - Pełna transakcja SQLite z automatycznym rollbackiem i usuwaniem nowo tworzonego pliku w razie błędu.
   - Bezpieczne wielokrotne uruchomienie na tej samej bazie docelowej nie tworzy żadnych duplikatów.
6. **Interfejs CLI:**
   - Domyślny tryb `--dry-run` (symulacja w pamięci bez tworzenia plików).
   - Jawny tryb zapisu `--apply --target <ścieżka>`.
   - Opcja weryfikacji głębokiej spójności `--verify --target <ścieżka>`.

---

## Zmienione pliki

| Ścieżka | Opis |
|---|---|
| `modules/migrator.py` | Produkcyjny silnik migracji SQLite v1 -> v2 z precyzyjnym provenance i izolacją źródeł kompozytowych. |
| `tests/test_migrator.py` | 12 testów jednostkowych i integracyjnych weryfikujących bilans, integralność, provenance i rollback. |
| `docs/sql/schema_v2.sql` | Uzupełniono `unit_catalog` o `EUR_PLN`, `USD_PLN` oraz `MEUR`. |
| `.gitignore` | Dodano ignorowanie docelowych baz testowych (`instance/*_v2.db`, `instance/test_*.db`). |
| `docs/agent-reports/TASK-04-REPORT.md` | Raport z aktualizacją po code review. |

---

## Testy i kontrole

| Polecenie | Status | Wynik |
|---|---|---|
| `uv run pytest tests/test_migrator.py -v` | **PASSED** | 12 passed w 1.48s (dry-run, apply, głębokie porównanie, provenance, idempotencja, CLI, rollback). |
| `uv run python -m modules.migrator` | **PASSED** | Domyślny dry-run wykonany bez tworzenia plików, bilans 75/10/6/91, 13 quality events. |

---

## Stan danych i bezpieczeństwa

- Czy zmodyfikowano `instance/economy_agent.db`? **NIE**. Baza produkcyjna pozostała nienaruszona (dokładnie 73 728 bajtów, SHA-256: `E6C5F318FFE1ECEEB34191A7A74EC9F7F7DE6069C4F298850792734277ECDE3B`).
- Czy uruchomiono migrację na bazie produkcyjnej? **NIE**.
- Czy były wywołania płatnych API? **NIE**.
- Czy przełączono aplikację na SQLite v2? **NIE**.
