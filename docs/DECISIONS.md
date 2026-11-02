# Rejestr decyzji architektonicznych (ADR-lite)

Statusy: **ACCEPTED** — ustalone wspólnie; **PROPOSED** — do potwierdzenia; **OPEN** — wymagają rozstrzygnięcia.

| ID | Status | Decyzja | Uzasadnienie |
|---|---|---|---|
| ADR-001 | ACCEPTED | Oficjalne API i Tavily/Web Search są równoległymi, uzupełniającymi się kanałami | Wiarygodne serie liczbowe + bieżące komunikaty i kontekst |
| ADR-002 | ACCEPTED | Nie usuwać funkcji przeszukiwania internetu | To integralna funkcja produktu |
| ADR-003 | ACCEPTED | Gemini oraz GPT pozostają częścią rozwiązania | Ekstrakcja dokumentów i niezależne interpretacje |
| ADR-004 | ACCEPTED | Nie nadpisywać bez kontroli danych bazowych | Historia oraz możliwości audytu |
| ADR-005 | PROPOSED | Na obecnym etapie SQLite zamiast PostgreSQL | Mała skala, niższa złożoność operacyjna; ocenić ponownie przy wymogach współbieżności |
| ADR-006 | PROPOSED | Jeden rejestr definicji wskaźników i wersjonowane obserwacje | Usuwa chaos aliasów, nie gubiąc rewizji |
| ADR-007 | PROPOSED | Niepewne odczyty otrzymują status, nie są ukrywane ani losowo rozstrzygane | Wiarygodność raportów |
| ADR-008 | PROPOSED | Raport AI korzysta tylko z obserwacji zaakceptowanych lub opisanych jako niepewne, zgodnie z polityką publikacji | Eliminacja wniosków na podstawie nieweryfikowanych liczb |

## Otwarta lista pytań
1. Które wskaźniki mają wejść do pierwszego katalogu MVP (CPI, PKB, stopa bezrobocia rejestrowanego, liczba zarejestrowanych bezrobotnych, wynagrodzenia, produkcja, stopa NBP, PMI)?
2. Jak prezentujemy wskaźniki bez dostępnego oficjalnego API: jako zweryfikowaną publikację, szacunek, czy sekcję kontekstową?
3. Czy raport ma pozostać okresowy i statyczny czy również oferować interaktywny widok i historię?
4. Czy dopuszczamy ręczną akceptację problematycznych odczytów? Jeśli tak, kto i jak ją audytuje?
5. Jak długo zatrzymywać surowe dokumenty oraz odpowiedzi API, z uwzględnieniem licencji źródeł?
6. Gdzie działa docelowa aplikacja: lokalnie, serwer VPS, usługa chmurowa? Wpływa to na trwałość SQLite i harmonogram odświeżania.

## Reguła zmian decyzji
Zmiana architektury wymaga aktualizacji niniejszego dokumentu wraz z motywacją, datą i PR. Nie zmieniać statusu OPEN/PROPOSED na ACCEPTED bez uzgodnienia z właścicielem.