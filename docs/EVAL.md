# Evaluation Harness

Statistical, regression-aware evaluation of the Series 76 actuator agent. Answers
three questions with numbers:

1. **Is the RAG index healthy?** — retrieval metrics, independent of the LLM.
2. **Is the agent accurate?** — end-to-end accuracy with a hybrid grader.
3. **Did a change make it better or worse?** — run history + per-case regression diff.

## Quick start

```bash
# Full eval: retrieval + 11 E2E cases, write report, enforce 80% gate
python scripts/eval.py

# Run without failing the build on low accuracy (for iteration)
python scripts/eval.py --no-gate

# Just the retrieval health check (fast, no LLM E2E calls)
python scripts/eval.py --retrieval-only

# A/B two prompt variants against the same case set
python scripts/eval.py --compare-prompts prompts/proactive.txt
```

The report is written to `eval_report.html` — open it in a browser. Each run is
also saved to `eval_runs/<timestamp>.json` for the historical trend.

## Architecture

The CLI (`scripts/eval.py`) is a thin shell. The logic lives in `app/eval/`:

| Module | Responsibility |
|--------|---------------|
| `catalog.py` | Derives golden answers from the live SQLite catalog at runtime |
| `graders.py` | Hybrid graders: `exact`, `spec`, `filter`, `judge` |
| `retrieval.py` | Index health + recall@k, segmented by query kind |
| `cases.py` | Declarative test cases, each naming its grader |
| `runner.py` | Runs cases against an agent, dispatches the right grader |
| `history.py` | Persists runs, diffs current vs previous |
| `report.py` | Renders the self-contained HTML report (Chart.js) |

Every module has a runnable self-check: `python -m app.eval.<module>`.

## The two levels of evaluation

### 1. Retrieval eval — "is the index built right?"

`recommend_actuators` does **SQL hard-filter → ChromaDB semantic re-rank**. The
retrieval eval measures ChromaDB *in isolation*, before the LLM speaks, so a failure
points at the index rather than the prose.

- **index_health** — indexed doc count vs catalog rows. 1:1 means ingest dropped nothing.
- **recall@k** — for a query whose valid PN set is known (computed from the catalog),
  is at least one valid PN in ChromaDB's top-k?

Recall is **segmented by query kind** so the aggregate can't mislead:

| Kind | Meaning | How to read a low score |
|------|---------|------------------------|
| `fuzzy` | free-form intent ("hazardous location") | low = the embedding is genuinely weak; worth fixing |
| `numeric` | a hard number ("< 100 Nm") | low is expected — embeddings are weak on numbers, and SQL already filters by number, so it rarely matters in production |
| `categorical` | small closed-value set ("24V modulating") | low is usually a measurement artifact — in production SQL pre-filters to the valid set before ChromaDB re-ranks, so isolated recall understates real behavior |

> **Why an isolated 80% can be fine:** the production path never asks ChromaDB to
> find "24V modulating" units among all 111 docs — SQL narrows to the valid candidates
> first, and ChromaDB only orders *those*. A low `categorical` score is the worst case
> measured without that pre-filter. Don't tune the embedding to chase it unless the
> `fuzzy` segment is also low.

### 2. End-to-end eval — "is the agent accurate?"

Each case declares the cheapest grader that can tell right from wrong:

| Grader | Used for | How it decides |
|--------|----------|----------------|
| `exact` | exact PN lookup | the expected PN appears verbatim in the answer |
| `spec` | spec lookup | the answer states the catalog's value for a field |
| `filter` | NL recommendation | every PN mentioned is in the catalog-derived valid set, and ≥1 is mentioned |
| `judge` | out-of-domain, session memory | an LLM (OpenRouter) answers a yes/no rubric |

**Determinism lives where the truth is verifiable.** Facts (PNs, specs, filters) are
graded against the catalog — free, deterministic, can't be gamed. The LLM judge is
spent only on quality that isn't a fact (did it decline gracefully? did it remember
the prior turn?).

#### The judge

Uses OpenRouter (`OPENROUTER_API_KEY`, model `EVAL_JUDGE_MODEL`, default
`openai/gpt-4o-mini`). **Degrades gracefully**: with no key, judge cases fall back to
a non-empty check and the report flags them as un-judged. Set the key to get real
quality grading.

## Regression detection

Each run is saved with a timestamp. The report compares the current run to the
previous one and buckets every case into **improved / regressed / unchanged / new**.
A regression is printed to the console (`[!] REGRESSIONS: ...`) and tagged in the
report's per-case table.

> **Note on LLM non-determinism:** at `temperature=0` the agent can still vary
> run-to-run. A single case flipping is often noise, not a real regression — re-run it
> in isolation before treating it as a code problem. The `filter` grader uses *set
> membership* rather than an exact expected PN precisely to tolerate this.

## A/B testing prompts — "how do I improve it?"

```bash
python scripts/eval.py --compare-prompts prompts/proactive.txt
```

Runs the full case set against the default `SYSTEM_PROMPT` **and** each prompt file,
prints accuracy per variant. This is how the current production prompt was chosen:
the "proactive" variant (recommend-first instead of asking for clarification) moved
recommendation accuracy from 1/3 to 3/3 and was promoted to `app/prompts.py` only
after the data showed the gain.

To trial a new prompt: write the full rendered prompt to `prompts/<name>.txt`, run
the A/B, and if it wins, copy the improvement into `app/prompts.py`.

## Adding a case

Add a dict to `CASES` in `app/eval/cases.py`:

```python
{
    "name": "rec_low_voltage",          # unique
    "category": "recommendation",        # one of CATEGORIES
    "grader": "filter",                  # exact | spec | filter | judge
    "query": "I need a 24V actuator.",
    "filters": {"voltage": "24V"},       # filter grader: catalog filter for the valid set
}
```

Required fields per grader:
- `exact` → `expected_pn`
- `spec` → `part_number`, `field`
- `filter` → `filters` (kwargs for `catalog.pns_matching`)
- `judge` → `rubric` (a yes/no question); use `turns: [...]` for multi-turn memory

The `cases.py` self-check validates that every case is well-formed for its grader.

## CI integration

`scripts/eval.py` exits non-zero when accuracy is below the gate (default 0.8), so it
can run in CI as a quality gate. Use `--retrieval-only` for a fast index-health check
that needs no LLM E2E calls (cheaper, deterministic).
