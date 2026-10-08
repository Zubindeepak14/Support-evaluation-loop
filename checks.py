"""Pass rules. These run in code. No model grades another model."""

from __future__ import annotations

from docs_live import quote_in_text

DOC_TOOLS = {"search_docs", "get_page"}
ALLOWED_TOOLS = DOC_TOOLS | {"write_handoff"}


def grade(case: dict, turns: list[dict]) -> dict:
    reasons: list[str] = []
    if not turns:
        return _result(False, ["no turn was produced"])

    for turn in turns:
        if turn.get("cap_exceeded"):
            reasons.append("more than 6 tool calls in a turn")
        if turn.get("unknown_tool"):
            reasons.append(f"tool not allowed: {turn['unknown_tool']}")
        if turn.get("parse_error"):
            reasons.append(f"final reply was not the required JSON: {turn['parse_error']}")

    kind = case["kind"]
    if kind == "out_of_scope":
        reasons.extend(_grade_out_of_scope(turns[-1]))
    elif kind == "ambiguous":
        reasons.extend(_grade_ambiguous(case, turns))
    elif kind == "in_scope":
        reasons.extend(_grade_answer(case, turns[-1], turns))
    else:
        reasons.append(f"unknown case kind: {kind}")

    # Order-stable unique reasons.
    unique = list(dict.fromkeys(reasons))
    return _result(not unique, unique)


def _grade_out_of_scope(turn: dict) -> list[str]:
    parsed = turn.get("parsed") or {}
    reasons = []
    if not parsed.get("abstain"):
        asked = (parsed.get("clarifying_question") or "").strip()
        answer = (parsed.get("answer") or "").strip()
        if asked and not answer:
            reasons.append("asked instead of refusing")
        else:
            reasons.append("out-of-scope question received a confident answer")
    if not turn.get("handoff_written"):
        reasons.append("handoff was not written")
    return reasons


def _grade_ambiguous(case: dict, turns: list[dict]) -> list[str]:
    reasons = []
    first = turns[0]
    if not asks_clarifying_question(case, first):
        reasons.append("first turn did not ask a clarifying question")
    question = ((first.get("parsed") or {}).get("clarifying_question") or "").lower()
    for banned in case.get("clarify_must_not") or []:
        if banned.lower() in question:
            reasons.append(f"clarifying question asked for {banned}")
    if len(turns) < 2:
        reasons.append("no answer after the clarifying question")
        return reasons
    reasons.extend(_grade_answer(case, turns[-1], turns))
    return reasons


def _grade_answer(case: dict, turn: dict, turns: list[dict]) -> list[str]:
    parsed = turn.get("parsed") or {}
    reasons = []
    if parsed.get("abstain"):
        reasons.append("abstained on a question the docs answer")
    answer = parsed.get("answer") or ""
    missing = [fact for fact in case.get("required_facts", []) if fact.lower() not in answer.lower()]
    if missing:
        reasons.append("missing facts: " + "; ".join(missing))
    citations = parsed.get("citations") or []
    if not citations:
        reasons.append("no citation")
    chunks = {}
    for item in turns:
        chunks.update(item.get("chunks") or {})
    for citation in citations:
        chunk_id = citation.get("chunk_id") or ""
        quote = citation.get("quote") or ""
        if chunk_id not in chunks:
            reasons.append(f"citation {chunk_id or '(blank)'} was not retrieved")
            continue
        if not quote_in_text(quote, chunks[chunk_id]):
            reasons.append(f"quote not in chunk {chunk_id}")
    called = {call.get("name") for item in turns for call in item.get("tool_calls") or []}
    if not (called & DOC_TOOLS):
        reasons.append("no docs tool was called")
    expected = case.get("expect_tool")
    if expected and expected not in called:
        reasons.append(f"expected tool was not called: {expected}")
    return reasons


def asks_clarifying_question(case: dict, turn: dict) -> bool:
    parsed = turn.get("parsed") or {}
    if parsed.get("abstain"):
        return False
    question = (parsed.get("clarifying_question") or "").strip()
    answer = (parsed.get("answer") or "").strip()
    visible = question or answer
    if "?" not in visible:
        return False
    if question and not answer:
        return True
    blob = answer.lower()
    facts = case.get("required_facts") or []
    if facts and all(fact.lower() in blob for fact in facts):
        return False
    return True


def _result(passed: bool, reasons: list[str]) -> dict:
    return {"passed": passed, "reasons": reasons}
