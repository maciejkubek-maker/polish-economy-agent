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

## Otwarte decyzje (TASK-03)

### DR-001 — Reprezentacja wartości numerycznych w SQLite v2 (value_decimal)
- **Zadanie:** TASK-03
- **Status:** `PENDING_REVIEW`
- **Blokuje pracę:** NIE
- **Problem:** Wartości makroekonomiczne (stopy procentowe, dynamiki r/r, kwoty w PLN) wymagają precyzji dziesiętnej bez zniekształceń zmiennoprzecinkowych.
- **Opcja A (Rekomendowana):** Kanoniczny typ `TEXT` (np. `'5.80'`, `'-2.40'`) z walidacją za pomocą `decimal.Decimal` w Pythonie oraz `CHECK(value_decimal GLOB '[-0-9]*')` w SQLite. Zero błędów zaokrągleń IEEE 754, natywna obsługa dowolnej precyzji, czytelność w SQL.
- **Opcja B:** Skalowany `INTEGER` (np. punkty bazowe, mnożnik 10^4). Ryzyko: wymaga znajomości skali per wskaźnik przy każdym zapytaniu i uniemożliwia proste zapytania ad-hoc.
- **Opcja C:** `REAL` (float). Niedopuszczalne: błędy precyzji binarnej w testach regresyjnych i agregacjach.
- **Rekomendacja agenta:** Opcja A (kanoniczny `TEXT` + `decimal.Decimal`).
- **Wpływ na kod / dane / bezpieczeństwo:** Spójność numeryczna, pełna testowalność offline.

### DR-002 — Rozstrzygnięcie konfliktów rewizyjnych w danych legacy (PKB II kw. 2026 i Stopa bezrobocia r/r)
- **Zadanie:** TASK-03
- **Status:** `PENDING_REVIEW`
- **Blokuje pracę:** NIE
- **Problem:** W 75 rekordach legacy zidentyfikowano dwie sprzeczności: (1) PKB r/r za II kw. 2026 ma wartości `3.90%` (Bankier/GUS) oraz `3.8%` (GUS); (2) Rekordy 33 i 35 mają nazwę `Stopa bezrobocia r/r` i wartości `6.1%`, `5.8%` (błędna etykieta GPTAgent dla bezrobocia rejestrowanego).
- **Opcja A (Rekomendowana):** Zastosowanie zasady *Zero Data Loss*: zachowanie wszystkich odczytów w `extracted_candidates`. W `observations` oznaczenie PKB 3.8% jako `PRELIMINARY` (`is_latest=1`), a 3.90% jako `SUPERSEDED` (`revision_type='FLASH'`). Dla `Stopa bezrobocia r/r` nadanie statusu `MIGRATED_PENDING` w `quality_events` do akceptacji człowieka.
- **Opcja B:** Nadpisanie wartości 3.9% wartością 3.8% i arbitralne usunięcie etykiety `r/r`. Ryzyko: utrata historii rewizji i zacieranie błędów agenta.
- **Rekomendacja agenta:** Opcja A.
- **Wpływ na kod / dane / bezpieczeństwo:** Zgodność z audytowalnością i brakiem destrukcyjnych zmian.

### DR-003 — Oficjalne źródło dla stóp procentowych NBP (brak REST API w api.nbp.pl)
- **Zadanie:** TASK-03
- **Status:** `PENDING_REVIEW`
- **Blokuje pracę:** NIE
- **Problem:** Analiza wykazała, że publiczne REST API `api.nbp.pl` obsługuje wyłącznie kursy walut i ceny złota. Stopy procentowe NBP nie mają endpointu REST w tym portalu.
- **Opcja A (Rekomendowana):** Wykorzystanie oficjalnego, otwartego pliku XML udostępnianego przez NBP: `https://static.nbp.pl/dane/stopy/stopy_procentowe.xml` (oraz archiwum `stopy_procentowe_archiwum.xml`).
- **Opcja B:** Pozyskiwanie stóp referencyjnych wyłącznie przez Tavily Web Search z komunikatów RPP. Ryzyko: podatność na błędy interpretacji tekstu, brak natychmiastowej precyzji w formacie maszynowym.
- **Rekomendacja agenta:** Opcja A jako Tier A z Tavily Web Search jako kanałem uzupełniającym (kontekst uzasadnienia decyzji RPP).
- **Wpływ na kod / dane / bezpieczeństwo:** Pewne, oficjalne źródło danych instytucjonalnych.
