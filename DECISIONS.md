# Architecture Decision Records — Konecto Actuator Agent

> Each ADR documents the context, the decision made, and the trade-offs accepted.
> These records are intended to be defensible in a follow-up interview.

---

## ADR-01: JSON data versioning vs runtime PDF parsing

**Context**

The actuator dataset comes from a PDF with complex nested column headers (60Hz/50Hz), merged cells (Motor Power), and N/A values. A runtime parser (`pdfplumber`, `camelot`) must handle all these edge cases on every `docker compose up`. The assessment states reproducibility is pass/fail.

**Decision**

Pre-extract the data once using a multimodal model (Google AI Studio) into `data/actuators.json`, commit it to the repo, and validate on load with a Pydantic schema. `scripts/ingest.py` reads the JSON — it never touches the PDF.

**Consequences / Trade-off**

- (+) Reproducibility: `docker compose up` on a clean machine cannot break due to a flaky parser
- (+) Auditable: the JSON is a versioned artifact; diffs show exactly what changed
- (+) Budget: no API call on every restart
- (-) The JSON can diverge from the PDF if the PDF is updated without re-running extraction
- Mitigation: `ingest.py` validates every field against the Pydantic schema and exits non-zero on corruption

---

## ADR-02: Hybrid SQLite + ChromaDB (two databases)

**Context**

The system must handle two fundamentally different query types: exact Part Number lookup (`763A00-11300000/A`) and ambiguous natural-language recommendation (`explosionproof 300 Nm 220V`). No single database technology covers both well — vector search degrades on near-identical IDs; keyword search cannot interpret "strong enough for a chemical plant."

**Decision**

Use SQLite for exact/structured lookups and ChromaDB for semantic similarity. `get_actuator` queries SQLite (deterministic); `recommend` filters SQLite on hard constraints first, then ranks the filtered subset with ChromaDB.

**Consequences / Trade-off**

- (+) Each store handles its optimal query type — no hallucinations on ID lookup, no rigidity on NL
- (+) SQL-first filtering before semantic ranking retains candidates that the embedding might have ranked low
- (-) Two systems to operate and keep in sync during ingest
- The dataset is ~40 rows; operational overhead is negligible

---

## ADR-03: Structured Pydantic extraction, not text-to-SQL

**Context**

The recommendation tool needs to filter on numeric constraints extracted from natural language ("at least 300 Nm", "220V", "explosionproof"). Two approaches: (a) let the LLM generate SQL directly (text-to-SQL), or (b) extract structured fields (Pydantic model) and build parameterized queries in Python.

**Decision**

Structured extraction: the LLM populates a `RecommendationFilters` Pydantic model; Python builds the WHERE clause with parameterized queries. The LLM never writes SQL. The categorical fields (`voltage`, `enclosure_type`, `application_type`) are constrained to closed `Literal` enums of real catalog values.

**Consequences / Trade-off**

- (+) Closes the SQL injection vector (CVE-2023-32785) that the read-only SQLite connection opens: text-to-SQL would re-open the exact door we close in the DB layer
- (+) Deterministic query construction; parameterized queries cannot be escaped by prompt injection
- (+) `Literal` enums make extraction robust to noise: the eval harness caught the LLM extracting `application_type="Series 76"` (the product name) from a plain torque query, which silently filtered every recommendation to zero rows. Constraining to real values forces such noise to `None` instead. This is the "ambiguous query" robustness the brief asks for.
- (+) Cleaner schema boundary — the LLM does language understanding, Python does data access
- (-) Less flexible than text-to-SQL for ad-hoc queries; the schema of ~18 columns must be known upfront
- For a fixed-schema domain of 64 part numbers, flexibility is not a real requirement

---

## ADR-04: `langchain.agents.create_agent` (current API), not `create_react_agent` or `AgentExecutor`

**Context**

The assessment requires LangChain as the orchestration framework and at least one
custom LangChain Tool. As of LangChain v1 (this project uses `langchain` 1.3.x,
`langgraph` 1.2.x), there are three relevant agent APIs with distinct deprecation states:

- `langchain.agents.AgentExecutor` — the classic agent runtime, deprecated.
- `langgraph.prebuilt.create_react_agent` — **deprecated in LangGraph v1** in favor of
  `langchain.agents.create_agent` (per the official LangGraph v1 migration guide).
- `langchain.agents.create_agent` — **the current, unified agent API.** It runs on
  LangGraph under the hood and adds a middleware system. System prompt via `system_prompt=`.

The tools themselves use the `@tool` decorator from `langchain_core.tools`.

**Decision**

Use `langchain.agents.create_agent` with an `AsyncSqliteSaver` checkpointer. Tools are
defined with `langchain_core.tools.@tool` (custom LangChain Tools, as required). The
system prompt is passed via `system_prompt=`. This directly satisfies "use LangChain as
the orchestration framework" — it's the first-party LangChain agent API, not a
LangGraph-only prebuilt.

**Consequences / Trade-off**

- (+) Uses the current, non-deprecated LangChain agent API (both `AgentExecutor` and `create_react_agent` are deprecated)
- (+) `create_agent` runs on LangGraph, so the checkpointer pattern gives persistent multi-turn memory natively (see ADR-05) — no manual memory wiring
- (+) Async-native (`ainvoke` + `AsyncSqliteSaver`) matches the FastAPI async endpoints
- (+) Custom tools via `@tool` are unambiguously "custom LangChain Tools" per the requirement
- (-) v1 agent APIs are still evolving (2025–2026); pinning major versions in requirements is the mitigation

> Sources: [LangGraph v1 migration guide](https://docs.langchain.com/oss/python/migrate/langgraph-v1) (deprecates `create_react_agent` in favor of `create_agent`).

---

## ADR-05: `AsyncSqliteSaver` (persistent) not `MemorySaver` (in-process)

**Context**

The agent needs multi-turn memory so a follow-up question ("what about the 220V variant?") can reference the previous exchange. Two checkpointer options: `MemorySaver` (in-process dict, lost on restart) and a SQLite-backed saver (persists to `data/memory.db`). Since the FastAPI endpoints are async and call `agent.ainvoke`, the saver must be the async variant — the sync `SqliteSaver` raises `NotImplementedError` on async invocation.

**Decision**

`AsyncSqliteSaver` (from `langgraph.checkpoint.sqlite.aio`) writing to `data/memory.db`, opened via `async with ... from_conn_string(...)` in the FastAPI lifespan so the connection lives for the app's lifetime (not per-request). The memory DB is a separate file from `data/actuators.db` to keep read-only actuator data apart from read-write session state. The offline eval (`scripts/eval.py`) uses the sync `SqliteSaver` since it calls `agent.invoke` synchronously.

**Consequences / Trade-off**

- (+) Session history survives `docker compose restart` — a real-world requirement
- (+) Async-native: matches `ainvoke` in the async endpoints without blocking the event loop
- (+) Separate DB file for memory vs actuators keeps RW session state isolated from RO catalog data
- (-) Adds a file dependency; the `data/` volume must be mounted (handled by docker-compose)
- Handled in `docker-compose.yml` with a named volume for the data directory

---

## ADR-06: Two endpoints — JSON primary (`/api/conversation`) + SSE optional (`/api/conversation/stream`)

**Context**

The assessment contract is explicit: `POST /api/conversation` must return `{"answer": "..."}`. The ReAct agent's reasoning steps are naturally streaming (Thought → Action → Observation → Answer). These two requirements are in tension: a streaming response breaks the JSON contract.

**Decision**

Keep `/api/conversation` as the strict JSON endpoint (assessment-exact). Add `/api/conversation/stream` as an optional SSE endpoint that streams tool events and tokens. Both share the same underlying agent instance.

**Consequences / Trade-off**

- (+) JSON endpoint passes the acceptance test exactly as specified
- (+) SSE endpoint demonstrates streaming capability as a differentiator without breaking the contract
- (+) Code reuse: both endpoints invoke the same agent; SSE just wraps `astream_events`
- (-) Two endpoints to document and maintain
- Cost is minimal: ~20 lines of shared path, separate response formatting

---

## ADR-07: FastMCP `app.mount()` + `combine_lifespans` (not `from_fastapi()`)

**Context**

FastMCP offers two integration patterns: `from_fastapi(app)` (wraps an existing FastAPI app) and `mcp.http_app()` + `app.mount()` (mounts the MCP ASGI app as a sub-application). The `from_fastapi()` approach is documented as a prototyping shortcut with limitations in multi-lifespan scenarios.

**Decision**

Use `mcp.http_app(path="/")` to create `mcp_app`, mount it at `/mcp` with `app.mount("/mcp", mcp_app)`, and compose lifespans with `combine_lifespans(agent_lifespan, mcp_app.lifespan)` from `fastmcp.utilities.lifespan`.

**Consequences / Trade-off**

- (+) Official FastMCP production pattern; both lifespans (agent init + MCP server) run correctly
- (+) Clean separation: MCP tools in `mcp_server.py`, FastAPI routes in `main.py`
- (+) Avoids `from_fastapi()` limitations (prototype only per FastMCP docs)
- (-) Requires `combine_lifespans` import; slightly more boilerplate than `from_fastapi()`
- This is the only pattern that correctly handles lifespan events for both sub-apps

---

## ADR-08: Rate limiting with `slowapi` (30 req/min, OWASP LLM10)

**Context**

Each API call invokes an OpenAI LLM (cost) and may trigger multiple tool executions (latency). Without rate limiting, a single malicious or misconfigured client can exhaust the OpenAI key budget ("denial-of-wallet") — OWASP LLM Top 10 #10: Unbounded Consumption.

**Decision**

Add `slowapi` with `@limiter.limit(settings.rate_limit)` on both conversation endpoints (default `30/minute`, read from the `RATE_LIMIT` env var via config). `SlowAPIMiddleware` is registered so the decorators actually fire. Key function is `get_remote_address`. Returns HTTP 429 with a clear error message via a custom handler.

**Consequences / Trade-off**

- (+) Demonstrates OWASP LLM10 awareness concretely (~5 lines, not just documented)
- (+) Configurable via `RATE_LIMIT` env var; easy to tune per deployment
- (-) 30/min is a reasonable heuristic; a production system would need per-user limits with API keys
- Chosen ceiling documents the upgrade path: per-account rate limiting when multi-tenant

---

## ADR-09: Docker non-root user (UID 10001) + tini as PID 1

**Context**

A container running as root expands the blast radius if compromised — any escape gives root on the host. Standard practice is to drop to a non-root UID before the application process starts. Additionally, PID 1 in a container does not receive SIGTERM forwarding by default if it is the application directly; this causes slow/unclean shutdowns.

**Decision**

Dockerfile creates user `appuser` with UID 10001 (above the range of named system users) via `adduser --disabled-password --uid 10001 appuser`, `chown`s `/app` to it, and switches to it with `USER appuser` before `CMD`. Uses `tini` as the init process (`ENTRYPOINT ["tini", "--"]`) to handle signal forwarding and zombie reaping.

**Consequences / Trade-off**

- (+) Container isolation: compromised app cannot write to paths owned by root
- (+) Clean shutdown: `docker compose down` terminates the process correctly via tini
- (+) UID 10001 is a common non-root convention; easily auditable in the Dockerfile
- (-) Adds `tini` as a system dependency (one `apt-get install` line)
- Standard practice for production container hardening; cost is negligible
