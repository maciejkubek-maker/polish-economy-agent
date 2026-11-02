# TASK-XX — raport Antigravity / Codex

**Status:** `DONE | PARTIAL | BLOCKED`  
**Branch:** `branch-name`  
**Commit SHA:** `pełny-sha-lub-NOT_PUBLISHED`  
**PR:** `https://github.com/.../pull/N` lub `NONE`  
**Data:** `YYYY-MM-DD`

## Co wykonałem
- [konkretna zmiana / rezultat; bez deklaracji niepotwierdzonych]

## Zmienione pliki
| Ścieżka | Opis |
|---|---|
| `path/to/file` | ... |

## Testy i kontrole
| Polecenie | Status PASSED/FAILED/NOT_RUN | Wynik |
|---|---|---|
| `uv run pytest -q` | ... | liczba testów i uwagi |

## Stan danych i bezpieczeństwa
- Czy zmodyfikowano `instance/economy_agent.db`? **NIE / TAK (uzasadnienie)**.
- Czy były wywołania płatnych API? **NIE / TAK (zgoda)**.
- Czy pozostają znane podatności? Wymień jako `KNOWN_VULNERABILITY` (nie `FIXED`).

## Ryzyka / regresje / ograniczenia
- ...

## Decyzje wymagane
- Zob. [DECISION_REQUESTS.md](DECISION_REQUESTS.md) — DR-XXX lub BRAK.

## Następny sugerowany krok
- ...

## JSON status (opcjonalnie)
```json
{
  "task_id": "TASK-XX",
  "status": "READY_FOR_REVIEW",
  "branch": "...",
  "commit_sha": "...",
  "pull_request": "...",
  "tests": {"status": "PASSED", "passed": 0, "failed": 0},
  "risks": [],
  "requires_decision": []
}
```
