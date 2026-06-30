# CLAUDE.md

This project's agent/contributor guidance lives in **[AGENTS.md](AGENTS.md)** — read it
first. It covers what the project is, the architecture, where things live, how to run it,
and the conventions to follow when editing.

Quick pointers:

- **Architecture & decisions:** [AGENTS.md](AGENTS.md) and [DECISIONS.md](DECISIONS.md) (ADRs).
- **Setup, Docker, API, MCP config:** [README.md](README.md).
- **Evaluation harness (accuracy, retrieval health, regression):** [docs/EVAL.md](docs/EVAL.md).
- **Security model (7 layers, verified):** [SECURITY.md](SECURITY.md).

Two rules that are easy to get wrong:

1. **Tools own data access; the LLM never writes SQL.** Recommendation filters are a
   Pydantic model with `Literal` enums — a security/robustness boundary (DECISIONS ADR-03).
2. **Verify with the eval, don't assume.** `python scripts/eval.py` (11 cases, hybrid
   grader, 80% gate). `pytest tests/` for the mocked unit suite. Each `app/eval/` module
   has a `python -m app.eval.<module>` self-check.
