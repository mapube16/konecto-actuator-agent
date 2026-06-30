# Security Verification Checklist — INFRA-04

Defense-in-depth audit for the Konecto Actuator Agent. Each layer is verified against
the actual source with a precise file:identifier citation.

| # | Layer | Status | Evidence |
|---|-------|--------|----------|
| 1 | **Docker non-root user (UID 10001)** | present/verified | `Dockerfile:15` — `adduser --disabled-password --uid 10001 appuser`; `Dockerfile:27` — `USER appuser` ensures the process never runs as root |
| 2 | **SQLite read-only for tools** | present/verified | `app/db/sqlite.py:11` — `sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)` — tools can only read the catalog; writes raise `sqlite3.OperationalError` |
| 3 | **Separate RW SQLite for checkpointer** | present/verified | `app/main.py:47` — `AsyncSqliteSaver.from_conn_string(settings.memory_db_path)` opens `data/memory.db` (not the catalog DB) inside the lifespan; `app/config.py:21-24` — default `"data/memory.db"`, distinct from the read-only `db_path` |
| 4 | **Parametrized SQL — no user values in query strings** | present/verified | `app/tools/get_actuator.py:42-43` — `conn.execute("SELECT * FROM actuators WHERE base_part_number = ?", (part_number,))` uses `?` binding. `app/tools/recommend.py` (`_build_where`) — f-strings interpolate only `?` placeholder counts and hard-coded column names (never user input); all user-supplied values flow through the `params` list to SQLite's binding layer |
| 5 | **Pydantic input validation (length + pattern)** | present/verified | `app/main.py:31` — `query: str = Field(..., min_length=1, max_length=2000)`; `app/main.py:32` — `session_id` constrained to `max_length=100, pattern=r"^[a-zA-Z0-9-]+$"` |
| 6 | **System prompt guardrails (prompt injection defence)** | present/verified | `app/prompts.py:1` (module docstring) — "security guardrails"; `app/prompts.py:24+` (`## Security Guidelines`) — explicit rules to reject off-topic queries, refuse override attempts (`"ignore previous instructions"`, `"you are now a different AI"`), refuse off-topic deliverables (code/jokes) even when reframed as on-topic, and never fabricate specifications |
| 7 | **slowapi rate limiting (default 30 req/min, configurable)** | present/verified | `app/main.py:85` — `@limiter.limit(settings.rate_limit)` on `/api/conversation`; `app/main.py:98` — same on `/api/conversation/stream`; `app/main.py:56` — `app.add_middleware(SlowAPIMiddleware)` so limits actually fire; `app/main.py:60-61` — handler returns HTTP 429 |

## Notes

- **Layer 4 — recommend.py f-string clarification:** The f-string in `_build_where` and the
  subsequent `f"SELECT ... WHERE base_part_number IN ({placeholders})"` interpolate only the
  `?` placeholder count (an integer derived from `len(top_pns)`) and hard-coded column names.
  User-provided values never touch the query string; they travel exclusively through the
  `params` list passed as the second argument to `conn.execute()`.

- All 7 layers present and verified. No remediation items.
