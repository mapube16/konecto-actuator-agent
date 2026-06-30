# AGENTS.md

Guidance for AI agents (and humans) working in this repository. This is the
Konecto Actuator Agent — a FastAPI microservice that answers questions and makes
recommendations about Bettis Series 76 electric actuators, exposed both as a REST
API and as an MCP server.

## What this project is

- **Domain:** Series 76 electric actuators (111 configurations, 64 base part numbers).
- **Core capabilities:** exact part-number lookup, and natural-language recommendation.
- **Stack:** FastAPI · LangChain (`langchain.agents.create_agent`, runs on LangGraph) ·
  OpenAI (`gpt-5-mini` + `text-embedding-3-small`) · SQLite + ChromaDB · FastMCP · slowapi.

## Architecture (one paragraph)

The agent is a LangChain ReAct agent with two custom `@tool`s. `get_actuator_by_part_number`
does an exact SQLite lookup (with `rapidfuzz` typo suggestions). `recommend_actuators` does
**SQL hard-filter → ChromaDB semantic re-rank**: the LLM extracts structured Pydantic filters
(closed `Literal` enums), SQLite filters by hard constraints, then ChromaDB re-ranks the
already-valid candidates. The embedding is a re-ranker over a pre-filtered set — never the
source of truth. Multi-turn memory is an `AsyncSqliteSaver` checkpointer keyed by `session_id`.

## Where things live

| Path | What |
|------|------|
| `app/main.py` | FastAPI app: endpoints, lifespan, rate limit, error handler |
| `app/agent.py` | Agent construction (`create_agent`) |
| `app/tools/` | The two custom LangChain tools |
| `app/db/` | SQLite (read-only for tools) + ChromaDB singleton |
| `app/prompts.py` | System prompt (proactive recommend + security guardrails) |
| `app/eval/` | Evaluation harness — see `docs/EVAL.md` |
| `scripts/ingest.py` | `actuators.json` → SQLite + ChromaDB (run before first start) |
| `scripts/extract_pdf.py` | `data/raw/*.pdf` → `actuators.json` (regenerate data) |

## Running it

```bash
pip install -r requirements.txt
cp .env.example .env          # set OPENAI_API_KEY
python scripts/ingest.py      # build the databases
uvicorn app.main:app --reload # serve on :8000
```

Full instructions, Docker, API examples, and MCP config are in `README.md`.

## Conventions for agents editing this repo

- **Tools own data access; the LLM never writes SQL.** Keep recommendation filters as a
  Pydantic model with `Literal` enums — this is a security and robustness boundary, not
  a style choice (see `DECISIONS.md` ADR-03).
- **The embedding is a re-ranker, not a filter.** Don't move correctness logic from SQL
  into vector search.
- **Verify changes with the eval, don't assume.** `python scripts/eval.py` runs 11 cases
  with a hybrid grader and an 80% gate; `python scripts/eval.py --retrieval-only` checks
  the index health without LLM calls. Each `app/eval/` module has a self-check
  (`python -m app.eval.<module>`).
- **Tests are mocked and offline:** `pytest tests/` (13 tests, no network).
- **Security layers are documented and verified** in `SECURITY.md` — don't regress them
  (read-only SQLite for tools, parametrized queries, input validation, prompt guardrails,
  rate limiting, non-root container).

## Design decisions

All non-obvious choices are recorded as ADRs in `DECISIONS.md` (hybrid DB, structured
extraction, `create_agent` vs deprecated APIs, embedding model choice, etc.). Read it
before changing architecture.
