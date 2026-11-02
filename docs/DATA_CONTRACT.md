# Data contract — propozycja v1 (do zatwierdzenia przed implementacją)

## Problemy schematu legacy
`collected_indicators`: `indicator_name`, `period`, `value`, `previous_value`, `trend_direction` to swobodne teksty, bez metodyki, stabilnego kodu i wersji. `save_indicators` robi UPDATE in-place po `(agent_name, country, indicator_name, period)`. Nie wolno przenosić tego wzorca do nowego modelu.

## Model logiczny — plan, nie gotowy DDL

| Encja | Pola kluczowe | Reguły |
|---|---|---|
| `source_registry` | `source_id`, `name`, `url/domain`, `source_type`, `trust_tier` | rozdziel oficjalne dane, publikacje i komentarze |
| `indicator_catalog` | `indicator_code`, `name_pl`, `definition`, `unit_code`, `frequency`, `methodology`, `preferred_source_id` | kod nie może scalać różnych definicji |
| `ingestion_runs` | `run_id`, `provider`, `started_at_utc`, `ended_at_utc`, `status`, `error_code` | audyt wykonania, retry, idempotencja |
| `source_evidence` | `evidence_id`, `source_id`, `source_url`, `published_at`, `retrieved_at_utc`, `content_hash`, `document_type`, `run_id` | prawdziwe odniesienie do danych; treść raw tam, gdzie wolno ją zachować |
| `extracted_candidates` | `candidate_id`, `agent_name/parser`, `raw_name`, `raw_value`, `raw_period`, `evidence_id`, `extracted_at_utc` | zachowaj oba wyniki agentów, nawet sprzeczne |
| `observations` | `observation_id`, `indicator_code`, `country_code`, `period_start`, `period_end`, `frequency`, `value_decimal`, `unit_code`, `evidence_id`, `status`, `observed_at_utc`, `supersedes_id` | zapis **append-only**, rewizje zamiast destrukcyjnego UPDATE |
| `quality_events` | `event_id`, `observation_id/candidate_id`, `rule_code`, `severity`, `message`, `created_at_utc`, `resolved_at_utc` | audyt konfliktów i odrzuceń |
| `reports` | `report_id`, `as_of_utc`, `report_markdown`, `data_snapshot_hash`, `model_metadata`, `created_at_utc` | raport odtwarzalny z wersji odczytów |

### Typy i normalizacja
- `country_code`: ISO 3166-1 alpha-2 (`PL`), z zachowaniem oryginalnej etykiety kraju w legacy.
- `indicator_code`: stabilny identyfikator np. `PL_CPI_YOY`, `PL_UNEMPLOYMENT_REGISTERED_RATE`. Nazwy i aliasy nie są kluczem naturalnym.
- `frequency`: `D`, `M`, `Q`, `Y`; okres statystyczny osobno od `published_at` i `retrieved_at_utc`.
- `value_decimal`: kanoniczny tekst dziesiętny parsowany przez `decimal.Decimal` **albo** skalowana liczba całkowita; przed implementacją ustalić dokładny format, unikać `float` jako wartości źródłowej.
- `unit_code`: np. `PCT`, `THOUSAND_PERSONS`, `PLN_PER_MONTH`, `INDEX_POINTS`; walidować kompatybilność jednostki z definicją.
- `status`: `RAW`, `PENDING`, `VERIFIED`, `CONFLICT`, `REJECTED`, `SUPERSEDED` — ostateczna maszyna stanów do zatwierdzenia.
- Timestampy w UTC ISO 8601 z offsetem; `published_at` może być NULL, jeśli niepotwierdzona; nie wymyślać dat.

## Idempotencja i rewizje
Idempotencja importu oparta na stabilnym identyfikatorze danych źródłowych (źródło, wskaźnik, okres, wersja/vintage, hash payloadu). Powtórzenie tego samego odczytu nie tworzy nowego rekordu. Nowa wartość lub rewizja tworzy **nową wersję** i odsyła do poprzedniej. Jeden wskaźnik/okres może mieć równoległe odczyty różnych źródeł i agentów; nie ustawiaj UNIQUE zbyt szerokiego.

## Reguły walidacji obowiązkowe
1. Każda obserwacja ma kod wskaźnika z katalogu i prawidłową częstotliwość.
2. Okres bez jednoznacznej częstotliwości (np. `II 2026`) trafia do `PENDING` zamiast arbitralnie stawać się lutym/II kwartałem.
3. Wartość i jednostka przechodzą parsowanie, zachowując `raw_value`.
4. Rozbieżne definicje wskaźników nie mogą być porównywane bez jawnego mapowania.
5. `VERIFIED` wymaga identyfikowalnego dowodu i przejścia ustalonych reguł.
6. Konflikty są widoczne, historyczne rekordy nie są usuwane.

## Testowalny kontrakt migracji
- Na kopii legacy: `75 -> 75` rekordów wejściowych archiwum/kandydatów (bez utraty żadnego oryginału); mapa `legacy_id -> target_id` kompletna i unikalna.
- Każdy rekord ma zachowane oryginalne: agent, nazwa, wartość, okres, źródło, URL, czas.
- Niepewne mapowania oznacz `PENDING`, nie dopasowuj automatycznie na podstawie samych podobnych nazw.
- Re-run migracji jest idempotentny; rollback nie wymaga niszczenia starej bazy.

**Uwaga:** to model logiczny. Dokładne tabele, klucze i migracje muszą przejść osobne review techniczne.