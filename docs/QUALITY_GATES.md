# Quality gates — definicja gotowości PR

## Gate A: kod i proces
- [ ] PR do właściwej bazy, na osobnym branchu, bez nieplanowanych plików.
- [ ] Zmiana ma wąski zakres i opis ryzyk, kompatybilności oraz rollback.
- [ ] Brak sekretów, `.env`, backupów SQLite, danych wrażliwych lub raportów ze ścieżkami lokalnymi.
- [ ] Uruchomiono testy offline albo wyraźnie oznaczono `NOT_RUN` i wyjaśniono przyczynę.
- [ ] Nie wykonywano płatnych API bez zgody.

## Gate B: poprawność danych
- [ ] Zachowane wartości oryginalne i źródła.
- [ ] Jednoznaczna identyfikacja definicji wskaźnika i okresu.
- [ ] Testy na: separator dziesiętny, jednostki, brak danych, lata i kwartały rzymskie, różne formaty okresów, rewizje, duplikaty.
- [ ] Dane konfliktowe oznaczone, brak arbitralnego wyboru LLM.
- [ ] Testowane przypadki API niedostępne/nieaktualne/niezgodne ze źródłem wtórnym.

## Gate C: bezpieczeństwo
- [ ] Untrusted HTML/Markdown/URL zostają bezpiecznie escapowane/sanityzowane.
- [ ] Testujemy funkcje **produkcyjne**, a nie tylko oddzielny `proposed_*` helper.
- [ ] Testy wykazujące podatność są przepisane na oczekiwanie bezpiecznego wyniku, oznaczone jako historyczne lub usunięte po naprawie — nie mogą nadal asercyjnie wymagać zagrożenia.
- [ ] Brak ukrytego wykonania kodu z treści wyszukiwarki / prompt injection.

## Gate D: operacje na bazie
- [ ] Backup spoza repo sprawdzony przez odtworzenie.
- [ ] Dry-run migracji na kopii.
- [ ] Re-run migracji nie duplikuje danych.
- [ ] Niezmienne archiwum 75 starych rekordów; mapa legacy-to-new i statystyka błędów.
- [ ] Przewidziany rollback i brak zapisu do oryginalnej bazy przy testach.

## Gate E: raport i AI
- [ ] Przy każdej podanej liczbie dostępne źródło, jednostka i okres.
- [ ] Wnioski LLM nie są przedstawiane jako źródłowe obserwacje.
- [ ] Konflikty oraz brak danych są oznaczone w raporcie.
- [ ] Dostępny test generowania raportu na deterministycznej fixture bez API.

## Uruchamianie (po instalacji zależności)
```bash
uv sync --group dev
uv run pytest -q
```
Nie zakładać CI, dopóki nie zostanie skonfigurowane. Sam log testów przekazany przez Codexa nie zastępuje kontroli patcha.

## Kategoryzacja statusu
- `PASSED`: test uruchomiony, wynik zielony.
- `FAILED`: test uruchomiony, wynik czerwony.
- `NOT_RUN`: nie uruchomiono.
- `KNOWN_VULNERABILITY`: obecne ryzyko celowo udokumentowane testem.
- `FIXED`: poprawka wdrożona w produkcyjnej funkcji i potwierdzona testami bezpieczeństwa.

Nigdy nie utożsamiać `KNOWN_VULNERABILITY` z `FIXED`.
