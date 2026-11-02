# Strategia migracji SQLite — bez utraty danych

**Status:** propozycja procedury. Nie wykonywać na prawdziwej bazie przed zatwierdzeniem kontraktu danych i osobną zgodą.

## Punkt wyjścia
Plik śledzony w repo: `instance/economy_agent.db` (73 728 bajtów). `collected_indicators`: 75, `trusted_sources`: 10, `generated_reports`: 6. Obecny `save_indicators` aktualizuje istniejący rekord i nie ma historii rewizji.

## Plan
1. **Snapshot:** kopia poza repo i hash SHA-256, potwierdzenie możności otwarcia snapshotu. Nie umieszczać w nowych commitach.
2. **Eksport read-only:** schema, surowe wiersze i `legacy_id`, metadane odczytu. Nie poprawiać danych w trakcie eksportu.
3. **Katalog definicji:** mapowanie nazwy -> `indicator_code` tylko z potwierdzoną metodologią. Niejednoznaczności trafiają do kolejki review.
4. **Parser wartości i okresów:** np. `5,80%` -> `5.80` + `PCT`; `II 2026` pozostaje niejednoznaczne, nie zamieniać w ciemno na miesiąc ani kwartał.
5. **Nowa baza:** zainicjalizować w osobnym pliku (np. w `tmp_path`). Insert-only legacy candidates i mapa `legacy_id -> candidate_id`.
6. **Walidacja:** porównanie wszystkich 75 rekordów i pól legacy, wykaz automatycznie zmapowanych i wymagających ręcznej weryfikacji, brak utraty 10 źródeł i 6 raportów.
7. **Powtarzalność:** uruchomić migrację drugi raz i udowodnić idempotencję.
8. **Dry-run raport:** rozkład statusów, konflikty, jednostki i daty, bez modyfikacji `instance/economy_agent.db`.
9. **Cutover:** dopiero za zgodą właściciela — czy aplikacja czyta nowy schemat, czy tymczasowo dual-read, jakie jest kryterium rollback.

## Testy wymagane
- Pusta baza, stara baza w aktualnej wersji, stara baza bez opcjonalnych kolumn.
- Re-run, uszkodzony/wieloznaczny okres, ujemna wartość, brak źródła, nieznana jednostka, różne nazwy tego samego wskaźnika i fałszywe aliasy.
- Spójność `75 legacy_id`, suma 10/6; nowe rekordy nie mogą zmieniać historycznych wejść.

## Uwaga do repozytorium
Usunięcie `instance/economy_agent.db` z katalogu roboczego lub `.gitignore` nie usuwa już opublikowanego pliku z historii Git. Decyzję o wycofaniu śledzonego binarium i ewentualnym czyszczeniu historii podejmować osobno, po analizie skutków dla klonów repo.
