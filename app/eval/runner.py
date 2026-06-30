"""Execute eval cases against an agent and apply the per-case grader.

Pure orchestration: takes an agent (already built), runs each case, dispatches to
the grader the case declares, returns a structured run dict. No I/O, no timestamps —
the CLI wraps this so the core stays testable and sandbox-safe.
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage

from app.eval import catalog, graders


def _last_text(result) -> str:
    """Last AI message text from a create_agent invoke result."""
    for msg in reversed(result.get("messages", [])):
        if isinstance(getattr(msg, "content", None), str) and msg.content.strip():
            return msg.content
    return ""


def _ask(agent, query: str, session_id: str) -> str:
    result = agent.invoke(
        {"messages": [HumanMessage(content=query)]},
        config={"configurable": {"thread_id": session_id}},
    )
    return _last_text(result)


def _run_case(agent, case: dict) -> dict:
    grader = case["grader"]
    sid = case.get("session_id", f"eval-{case['name']}")

    try:
        if "turns" in case:  # multi-turn (session memory)
            response = ""
            for turn in case["turns"]:
                response = _ask(agent, turn, sid)
        else:
            response = _ask(agent, case["query"], sid)

        if grader == "exact":
            passed, detail = graders.grade_exact(response, case["expected_pn"])
        elif grader == "spec":
            passed, detail = graders.grade_spec(response, case["part_number"], case["field"])
        elif grader == "filter":
            valid = catalog.pns_matching(**case["filters"])
            passed, detail = graders.grade_filter(response, valid)
        elif grader == "judge":
            query = case.get("query") or (case.get("turns", [""])[-1])
            passed, detail = graders.grade_judge(response, case["rubric"], query=query)
        else:
            passed, detail = False, f"unknown grader {grader}"
    except Exception as exc:  # noqa: BLE001 — one bad case must not abort the run
        response, passed, detail = f"ERROR: {exc}", False, f"exception: {exc}"

    return {
        "name": case["name"],
        "category": case["category"],
        "grader": grader,
        "passed": passed,
        "detail": detail,
        "preview": response[:120].replace("\n", " "),
    }


def run_cases(agent, cases: list[dict]) -> list[dict]:
    return [_run_case(agent, c) for c in cases]


if __name__ == "__main__":
    # Self-check: graders dispatch correctly against a stub agent (no real LLM).
    class StubAgent:
        def __init__(self, reply):
            self._reply = reply

        def invoke(self, _inp, config=None):
            from langchain_core.messages import AIMessage
            return {"messages": [AIMessage(content=self._reply)]}

    pn = next(iter(catalog.all_part_numbers()))
    cases = [
        {"name": "x", "category": "exact", "grader": "exact", "query": "q", "expected_pn": pn},
    ]
    res = run_cases(StubAgent(f"It is {pn}."), cases)
    assert res[0]["passed"], "exact grader should pass when stub returns the PN"
    res = run_cases(StubAgent("no pn here"), cases)
    assert not res[0]["passed"], "exact grader should fail when PN absent"
    print("OK — runner dispatches graders correctly")
