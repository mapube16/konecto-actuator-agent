# How this was built — AI-assisted development

The assessment states that AI-assisted development is *"expected and encouraged"* and that
what's evaluated is *"how you work as an AI developer."* This document describes exactly that:
the tools, the workflow, and — more importantly — where I kept the AI on a short leash.

The point isn't that AI wrote the code. It's that **I directed it, verified it, and owned
every decision.** AI is a fast junior that never gets tired; the senior judgment is mine.

---

## Tools used

| Tool | Role in this project |
|------|----------------------|
| **Claude Code (CLI)** | Primary development agent — wrote code under my direction, ran tests, drove Docker |
| **GSD (get-shit-done)** | Structured workflow: broke the build into phases, planned each, executed, reviewed |
| **Gemini 2.5 Flash** (via OpenRouter) | One-shot PDF → JSON extraction (multimodal table reading) — see `scripts/extract_pdf.py` |
| **Claude Code skills** | `ponytail` (over-engineering audits), multi-agent workflows (adversarial bug hunts), code-review |
| **OpenAI `gpt-5-mini`** | The agent's runtime chat model (chosen with data — see below) |

---

## The workflow: phases, not vibes

Rather than prompt-and-pray, I ran the build as a **structured, phased process** (GSD):

1. **Requirements & roadmap** — mapped the assessment's Part A / Part B into concrete
   requirements before writing any code, so scope was explicit and testable.
2. **Phase 1 — Data pipeline:** PDF extraction (Gemini) → `actuators.json` → validated
   ingest into SQLite + ChromaDB.
3. **Phase 2 — Agent core:** the two LangChain tools, the `/api/conversation` endpoint,
   multi-turn memory, edge-case handling.
4. **Phase 3 — Harness & infra:** MCP server, Agent Skill, Docker, evaluation harness, docs.

Each phase was planned, executed, and reviewed before moving on. The commit history
(`git log`) reflects this incremental, reviewable progression — not one giant "it works" dump.

---

## Where I kept the AI honest

This is the part that matters. AI-generated code is confidently wrong often enough that
**unverified AI output is a liability.** Concrete examples from this build where my judgment
overrode the AI's first answer:

- **Over-engineering audits (`ponytail`).** I ran repeated passes to *delete* code the AI
  had added speculatively: an `embedding_cache` that was always empty, aggressive SQLite
  PRAGMAs that are cargo-cult on a tiny read-only DB, and dead config settings
  (`cache_ttl`, `log_level`) that nothing read. The best code is the code that isn't there.

- **Adversarial bug-hunting (multi-agent workflow).** I ran a multi-agent verification pass
  that found real defects the happy-path code hid — e.g. `recommend` re-expanding a part
  number into all its `application_type` rows (duplicate/filter-violating results), and a
  missing `DISTINCT` that made the fuzzy fallback suggest the same PN twice. Each fix was
  verified against the real DB, not assumed. (See commit `fix: dedupe recommendations...`.)

- **Every claim verified, not trusted.** The evaluation harness (`scripts/eval.py`) exists
  precisely so I don't take the agent's word for anything: 11 E2E cases, hybrid graders,
  an 80% gate, run against the **real** LLM. Accuracy was *measured* from 60% → 100%, not
  claimed. (See `docs/ITERATION.md`.)

- **Model choice by data, not by default.** I benchmarked all three permitted chat models
  (3 runs each) instead of picking one on intuition. They tie at 100%, so I kept
  `gpt-5-mini` for cost. (See `docs/MODEL_COMPARISON.md`.)

- **Docs audited against code.** AI tends to write docs that describe the intended design,
  not the shipped one. I ran passes to reconcile the README/DECISIONS with what the code
  actually does (e.g. the endpoint contract, SSE event shape, rate-limit scope).

---

## What I'd tell another AI developer

- **Trace before you trust.** Read what the AI changed and *why* before accepting it. The
  smallest diff in the wrong place is a second bug.
- **Make the AI prove it.** A test, an eval, a live smoke run — "it should work" isn't
  "it works." I validated this service end-to-end locally *and* in Docker before shipping.
- **Delete aggressively.** AI adds; a senior removes. Most of my highest-value edits were
  deletions.
- **Own the decisions.** Every trade-off in `DECISIONS.md` is one I can defend in the
  interview — because I made it, the AI didn't make it for me.

---

*The commit history, `DECISIONS.md`, `docs/ITERATION.md`, and `docs/MODEL_COMPARISON.md`
are the receipts for everything above.*
