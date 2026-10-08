"""Play each case and apply the pass rules in code.

The committed results file is the baseline. A later run can disagree because
the docs are read live. That disagreement is drift, not a reproduction of this file.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from cases_store import load_cases
from checks import asks_clarifying_question, grade
from docs_live import ROOT, load_config

RESULTS = ROOT / "evals" / "results"


def play(docs, case: dict) -> list[dict]:
    messages: list[dict] = []
    chunks: dict = {}
    meta: dict = {}
    turns = [_one(docs, case, messages, chunks, meta, case["question"])]
    if case["kind"] == "ambiguous" and asks_clarifying_question(case, turns[0]):
        turns.append(_one(docs, case, messages, chunks, meta, case["scripted_reply"]))
    return turns


def _one(docs, case, messages, chunks, meta, text: str) -> dict:
    from agent import run_turn

    messages.append({"role": "user", "content": text})
    return run_turn(docs, messages, case["id"] + "-" + uuid.uuid4().hex[:8], chunks, meta)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the support eval suite")
    parser.add_argument("--replay", type=Path, help="Re-grade a saved results file without calling the model")
    parser.add_argument("--case", action="append", help="Run only these case ids")
    args = parser.parse_args()
    if args.replay:
        return _replay(args.replay)

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set. The fact check and the page shell do not need it. The suite does.", file=sys.stderr)
        return 2

    from docs_live import DocsClient

    config = load_config()
    docs = DocsClient()
    cases = [case for case in load_cases() if not args.case or case["id"] in args.case]
    run_id = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    records = []
    passed = 0
    for index, case in enumerate(cases, start=1):
        print(f"[{index}/{len(cases)}] {case['id']}", flush=True)
        try:
            turns = play(docs, case)
            result = grade(case, turns)
        except Exception as exc:
            turns = []
            result = {"passed": False, "reasons": [f"{type(exc).__name__}: {exc}"]}
        passed += int(result["passed"])
        if turns:
            from candidates import record_conversation

            record_conversation(
                candidate_id=f"tuned:{run_id}:{case['id']}",
                set_name="tuned",
                case_id=case["id"],
                turns=turns,
                case=case,
                visitor_flag=bool(case.get("flagged")),
                source=f"evals/results/{run_id}.json",
            )
        mark = "pass" if result["passed"] else "FAIL"
        detail = "" if result["passed"] else " — " + "; ".join(result["reasons"])
        print(f"  {mark}{detail}", flush=True)
        records.append({"case": case, "passed": result["passed"], "reasons": result["reasons"], "turns": [_public_turn(turn) for turn in turns]})

    summary = {
        "run_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "model": config["model"],
        "docs_index_url": config["docs_index_url"],
        "cache_ttl_seconds": config["cache_ttl_seconds"],
        "passed": passed,
        "total": len(cases),
        "cases": records,
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    path = RESULTS / f"{stamp}.json"
    path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    print(f"\n{passed}/{len(cases)} passed")
    print(path)
    return 0 if passed == len(cases) else 1


def _public_turn(turn: dict) -> dict:
    citations = (turn.get("parsed") or {}).get("citations") or []
    cited = {item.get("chunk_id") for item in citations}
    chunks = {key: value for key, value in (turn.get("chunks") or {}).items() if key in cited}
    meta = {key: value for key, value in (turn.get("chunk_meta") or {}).items() if key in cited}
    return {
        "parsed": turn.get("parsed") or {},
        "parse_error": turn.get("parse_error"),
        "tool_calls": turn.get("tool_calls") or [],
        "chunks": chunks,
        "chunk_meta": meta,
        "handoff_written": bool(turn.get("handoff_written")),
        "handoff_summary": turn.get("handoff_summary") or "",
        "cap_exceeded": bool(turn.get("cap_exceeded")),
        "unknown_tool": turn.get("unknown_tool"),
        "usage": turn.get("usage") or {},
        "raw_text": turn.get("raw_text") or "",
        "citation_retried": bool(turn.get("citation_retried")),
        "citation_retry_problems": turn.get("citation_retry_problems") or [],
        "abstain_search_retried": bool(turn.get("abstain_search_retried")),
        "handoff_retried": bool(turn.get("handoff_retried")),
        "depth_retried": bool(turn.get("depth_retried")),
        "clarify_retried": bool(turn.get("clarify_retried")),
    }


def _replay(path: Path) -> int:
    saved = json.loads(path.read_text())
    mismatches = 0
    for record in saved["cases"]:
        fresh = grade(record["case"], record["turns"])
        if fresh["passed"] != record["passed"] or fresh["reasons"] != record["reasons"]:
            mismatches += 1
            print(f"MISMATCH {record['case']['id']}: file={record['passed']} recomputed={fresh['passed']} {fresh['reasons']}")
        else:
            mark = "pass" if fresh["passed"] else "FAIL"
            print(f"{mark}  {record['case']['id']}")
    print(f"\n{saved['passed']}/{saved['total']} in the file. {mismatches} mismatch(es) on replay.")
    return 1 if mismatches else 0


if __name__ == "__main__":
    sys.exit(main())
