# Rejestr decyzji technicznych — Antigravity → ChatGPT → właściciel

Antigravity aktualizuje ten plik na branchu zadania, publikuje commit i wskazuje PR. ChatGPT analizuje zgłoszenia po otrzymaniu polecenia właściciela. **Brak automatycznego przesyłania wiadomości między agentami.**

## Wymagany szablon nowego zgłoszenia

### DR-XXX — [tytuł]
- **Zadanie:** TASK-XX
- **Status:** `PENDING_REVIEW`
- **Blokuje pracę:** TAK / NIE
- **Problem:** ...
- **Opcja A:** ...; ryzyko ...
- **Opcja B:** ...; ryzyko ...
- **Rekomendacja agenta:** ...; dlaczego ...
- **Wpływ na kod / dane / bezpieczeństwo:** ...
- **Linki do commitów, testów i PR:** ...
- **Decyzja ChatGPT (propozycja):** do uzupełnienia po review
- **Akceptacja właściciela:** do uzupełnienia
- **Status po decyzji:** `ACCEPTED | REJECTED | DEFERRED`

---

## Otwarte decyzje (TASK-03 — Aktualizacja po Code Review)

### DR-001 — Reprezentacja wartości numerycznych (value_decimal) i egzekwowanie append-only w SQLite v2
- **Zadanie:** TASK-03
- **Status:** `PENDING_REVIEW`
- **Blokuje pracę:** NIE
- **Problem:** Wartości makroekonomiczne wymagają precyzji dziesiętnej bez błędów zmiennoprzecinkowych IEEE 754, a tabela `observations` musi być ściśle append-only na poziomie silnika bazy danych, z osobnym mechanizmem ustalania aktualnej wersji (brak destrukcyjnych UPDATE `is_latest`).
- **Opcja A (Rekomendowana):**
  1. Typ `TEXT` dla `value_decimal` z walidacją pythonowym modułem `decimal.Decimal` oraz regułami `CHECK`.
  2. Bezwzględna ochrona niemutowalności `observations` triggerami SQLite `trg_observations_prevent_update` i `trg_observations_prevent_delete`, które blokują jakiekolwiek `UPDATE` i `DELETE`.
  3. Odrębny mechanizm ustalania aktualnej wersji: zmaterializowana tabela wskaźników `current_observations` (aktualizowana triggerem po INSERT zweryfikowanej obserwacji) oraz deklaratywny widok analityczny `v_latest_observations` bazujący na funkcji analitycznej `ROW_NUMBER() OVER (...)`.
- **Opcja B:** Skalowany `INTEGER` lub `REAL` z flagą `is_latest` aktualizowaną w miejscu w tabeli `observations`. Ryzyko: błędy float lub łamanie gwarancji append-only poprzez UPDATE na historycznych rekordach.
- **Rekomendacja agenta:** Opcja A (czysty podział: `observations` w 100% niemutowalne + dedykowany mechanizm wyznaczania wersji najnowszej).
- **Wpływ na kod / dane / bezpieczeństwo:** Gwarancja braku zacierania historii, pełna audytowalność, spójność numeryczna.

### DR-002 — Obsługa rozbieżności PKB za II kw. 2026 (3,90% vs 3,8%) i anomalii etykiet w legacy
- **Zadanie:** TASK-03
- **Status:** `PENDING_REVIEW`
- **Blokuje pracę:** NIE
- **Problem:** W 75 rekordach legacy zidentyfikowano dwie sprzeczności:
  1. PKB r/r za II kw. 2026 ma wartości `3,90%` (Bankier/GUS) oraz `3,8%` (GUS) wprowadzone przez obu agentów w odstępie kilkunastu minut.
  2. Rekordy 33 i 35 mają surową nazwę `Stopa bezrobocia r/r` i wartości `6,1%`, `5,8%` (błędna etykieta poziomu nadana przez GPTAgent).
- **Opcja A (Rekomendowana):**
  1. Zgodnie z wytycznymi code review: **nie zakładać arbitralnie, że 3,8% jest nowszą rewizją niż 3,90%** bez potwierdzonego źródłowo znacznika czasu publikacji (release bulletin). Obie wartości zachować w `extracted_candidates`, a w mapie migracji oznaczyć jako `MIGRATED_CONFLICT`, z wpisem w `quality_events` (`RULE_SOURCE_DISCREPANCY`). Żadna z wartości nie staje się automatycznie pojedynczą prawdą w `observations` do czasu autoryzacji przez człowieka.
  2. Dla `Stopa bezrobocia r/r` nadać status `MIGRATED_PENDING` z wpisem `RULE_MISLABELED_INDICATOR_NAME` w `quality_events`.
- **Opcja B:** Zgadnięcie, że 3,8% zastępuje 3,90% lub usunięcie rozbieżnego rekordu. Niedopuszczalne: naruszenie zasad rzetelności analitycznej i zacieranie danych.
- **Rekomendacja agenta:** Opcja A.
- **Wpływ na kod / dane / bezpieczeństwo:** Całkowite wyeliminowanie halucynacji i arbitralnego wyboru danych przez system.

### DR-003 — Oficjalne źródło dla stóp procentowych NBP (potwierdzenie braku REST API w api.nbp.pl)
- **Zadanie:** TASK-03
- **Status:** `PENDING_REVIEW`
- **Blokuje pracę:** NIE
- **Problem:** Publiczne REST API `api.nbp.pl` obsługuje wyłącznie kursy walut i ceny złota (zapytanie o stopy zwraca HTTP 404).
- **Opcja A (Rekomendowana):** Zastosowanie oficjalnego, otwartego pliku maszynowego XML NBP: `https://static.nbp.pl/dane/stopy/stopy_procentowe.xml` (oraz archiwum `stopy_procentowe_archiwum.xml`) jako źródła Tier A ze statusem `VERIFIED_STATIC_XML`, parsowanego wbudowanym modułem `xml.etree.ElementTree`.
- **Opcja B:** Web scraping stron HTML NBP lub wyłącznie Tavily Web Search. Ryzyko: kruchość selektorów HTML i niepotrzebna zależność od tekstu nieustrukturyzowanego.
- **Rekomendacja agenta:** Opcja A.
- **Wpływ na kod / dane / bezpieczeństwo:** Stabilne, deterministyczne i bezpieczne pozyskiwanie stóp procentowych NBP.
