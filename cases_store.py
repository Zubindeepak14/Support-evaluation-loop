"""The authored suite lives in evals/cases.json. Visitor flags do not."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CASES_PATH = ROOT / "evals" / "cases.json"
VISITOR_PATH = ROOT / "logs" / "visitor_flags.jsonl"
_LOCK = threading.Lock()


def load_cases() -> list[dict]:
    return json.loads(CASES_PATH.read_text())


def append_flagged_case(payload: dict, public_demo: bool) -> dict:
    facts = [fact.strip() for fact in payload.get("required_facts") or [] if fact and fact.strip()]
    question = (payload.get("question") or "").strip()
    kind = payload.get("kind") or "in_scope"
    if kind not in {"in_scope", "out_of_scope"}:
        raise ValueError("kind must be in_scope or out_of_scope")
    if not question:
        raise ValueError("question is required")
    if kind == "in_scope" and not facts:
        raise ValueError("at least one required fact is required")
    case = {
        "id": "flagged-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "kind": kind,
        "question": question,
        "required_facts": facts,
        "correct_answer": (payload.get("correct_answer") or "").strip(),
        "bad_answer": (payload.get("bad_answer") or "").strip(),
        "source": payload.get("source") or "",
        "flagged": True,
    }
    if kind == "out_of_scope":
        case["expect_abstain"] = True
    with _LOCK:
        if public_demo:
            VISITOR_PATH.parent.mkdir(parents=True, exist_ok=True)
            with VISITOR_PATH.open("a") as handle:
                handle.write(json.dumps(case, ensure_ascii=False) + "\n")
            case["stored_in"] = "logs/visitor_flags.jsonl"
        else:
            cases = load_cases()
            cases.append(case)
            CASES_PATH.write_text(json.dumps(cases, indent=2, ensure_ascii=False) + "\n")
            case["stored_in"] = "evals/cases.json"
    return case
