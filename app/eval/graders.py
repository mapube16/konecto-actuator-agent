"""Hybrid graders. Pick the cheapest grader that can tell right from wrong:

- exact:  the answer is a fact in the catalog (a PN, a spec) -> string/DB check, deterministic, free.
- filter: a recommendation must draw from PNs that satisfy hard constraints -> set membership vs the catalog.
- judge:  the quality is not a fact (graceful decline, recalled prior turn) -> LLM-as-judge via OpenRouter.

Determinism lives where the truth is verifiable; the LLM judge is spent only where it adds information.
"""

from __future__ import annotations

import os
import re

from app.eval import catalog

JUDGE_MODEL = os.getenv("EVAL_JUDGE_MODEL", "openai/gpt-4o-mini")

# Part numbers look like 763A00-11300000/A or 763A00-11330C00/A (the second
# block can contain a letter, e.g. ...30C00). Match alphanumerics after the dash.
_PN_RE = re.compile(r"\b\d{3}[A-Z]\d{2}-[0-9A-Z]+/[A-Z]\b")


def grade_exact(response: str, expected_pn: str) -> tuple[bool, str]:
    """Pass if the exact expected PN appears verbatim in the response."""
    ok = expected_pn.lower() in response.lower()
    return ok, f"expected PN {expected_pn} {'present' if ok else 'ABSENT'}"


def grade_spec(response: str, part_number: str, field: str) -> tuple[bool, str]:
    """Pass if the response states the catalog's value for a given spec field."""
    spec = catalog.spec_for(part_number)
    if spec is None:
        return False, f"PN {part_number} not in catalog"
    value = spec[field]
    # Numbers: accept the integer-or-1-decimal rendering; strings: substring.
    needle = str(int(value)) if isinstance(value, float) and value.is_integer() else str(value)
    ok = needle.lower() in response.lower()
    return ok, f"{field}={needle} {'present' if ok else 'ABSENT'}"


# A recommendation line pairs a PN with a torque, e.g.
#   "1. 761X30-11320000/A — explosionproof, 220V, 80.0 Nm (690.0 in-lbs), on/off"
_PN_TORQUE_RE = re.compile(r"(\d{3}[A-Z]\d{2}-[0-9A-Z]+/[A-Z]).*?([\d.]+)\s*Nm")


def grade_filter(response: str, expected_pns: set[str], valid_rows: list[dict] | None = None) -> tuple[bool, str]:
    """Pass if every PN mentioned is in the valid set AND (when valid_rows is given) every
    (PN, torque) pair shown matches a real row that passes the filter.

    Membership alone (PN in set) can't catch a wrong-variant bug: a PN may be valid while the
    torque shown belongs to its other application_type variant. valid_rows closes that gap.
    """
    mentioned = set(_PN_RE.findall(response))
    if not mentioned:
        return False, "no part numbers mentioned"
    invalid = mentioned - expected_pns
    if invalid:
        return False, f"mentioned out-of-spec PNs: {sorted(invalid)[:3]}"

    if valid_rows is not None:
        # Set of (PN, torque) that are actually valid — torque rounded for text matching.
        valid_pairs = {(r["base_part_number"], round(float(r["torque_nm"]), 1)) for r in valid_rows}
        for pn, torque_str in _PN_TORQUE_RE.findall(response):
            pair = (pn, round(float(torque_str), 1))
            if pair not in valid_pairs:
                return False, f"shown {pn} @ {torque_str} Nm is not a valid variant (wrong torque?)"

    return True, f"{len(mentioned)} PN(s), all valid" + ("" if valid_rows is None else " incl. torque")


def grade_nonempty(response: str) -> tuple[bool, str]:
    """Fallback used when the judge is unavailable: just non-empty."""
    ok = bool(response.strip())
    return ok, "non-empty" if ok else "EMPTY"


def grade_judge(response: str, rubric: str, *, query: str = "") -> tuple[bool, str]:
    """LLM-as-judge via OpenRouter. Degrades to grade_nonempty when no key.

    rubric is a yes/no question the judge answers about the response.
    """
    key = os.getenv("OPENROUTER_API_KEY")
    if not key:
        ok, why = grade_nonempty(response)
        return ok, f"[no judge key] {why}"

    from openai import OpenAI

    client = OpenAI(api_key=key, base_url="https://openrouter.ai/api/v1")
    prompt = (
        "You grade an AI assistant's reply. Answer with a single word: PASS or FAIL.\n\n"
        f"Criterion: {rubric}\n\n"
        f"User asked: {query}\n\n"
        f"Assistant replied:\n{response}\n\n"
        "Does the reply satisfy the criterion? Answer PASS or FAIL."
    )
    try:
        r = client.chat.completions.create(
            model=JUDGE_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=4,
            temperature=0,
        )
        verdict = (r.choices[0].message.content or "").strip().upper()
        ok = verdict.startswith("PASS")
        return ok, f"judge:{verdict or 'EMPTY'}"
    except Exception as exc:  # noqa: BLE001 — judge failure must not crash the run
        ok, why = grade_nonempty(response)
        return ok, f"[judge error: {exc}] fell back to {why}"


if __name__ == "__main__":
    # Self-check: deterministic graders are correct. Use fixed PNs (incl. the
    # letter-in-block form 11330C00) so the check doesn't depend on set order.
    plain_pn = "761A00-11300000/A"
    letter_pn = "763A00-11330C00/A"  # the form that broke the original regex
    assert _PN_RE.findall(f"see {plain_pn}") == [plain_pn], "regex must match plain PN"
    assert _PN_RE.findall(f"see {letter_pn}") == [letter_pn], "regex must match letter-in-block PN"

    ok, _ = grade_exact(f"The part is {plain_pn}.", plain_pn)
    assert ok, "grade_exact should match a present PN"
    ok, _ = grade_exact("nothing here", plain_pn)
    assert not ok, "grade_exact should fail when PN absent"
    ok, _ = grade_filter(f"I recommend {letter_pn}.", {letter_pn})
    assert ok, "grade_filter should pass an in-set PN"
    ok, _ = grade_filter(f"I recommend {plain_pn}.", set())
    assert not ok, "grade_filter should fail an out-of-set PN"
    # Variant-aware: a valid PN shown with a torque that isn't one of its valid rows fails.
    rows = [{"base_part_number": plain_pn, "torque_nm": 80.0}]
    ok, _ = grade_filter(f"1. {plain_pn} — 80.0 Nm, on/off", {plain_pn}, rows)
    assert ok, "grade_filter should pass a correct (PN, torque) pair"
    ok, why = grade_filter(f"1. {plain_pn} — 999.0 Nm, on/off", {plain_pn}, rows)
    assert not ok, f"grade_filter should fail a wrong-variant torque — got: {why}"
    ok, _ = grade_nonempty("")
    assert not ok, "grade_nonempty should fail on empty"
    print("OK — graders return correct verdicts (incl. variant-aware torque)")
