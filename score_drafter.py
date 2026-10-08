"""Score the drafter against the saved suite failures. The drafter does not grade itself."""

from __future__ import annotations

import json

from docs_live import ROOT

DRAFTS = ROOT / "logs" / "drafts.jsonl"
TUNED = ROOT / "evals" / "results" / "2026-10-08T100133Z.json"
HELDOUT = ROOT / "evals" / "results" / "heldout-2026-10-08T100916Z.json"
FLAGGED = {"incomplete", "agent_failure", "should_have_refused"}


def main() -> int:
    truth = _truth()
    drafts = _latest_drafts()
    caught = []
    missed = []
    false_flags = []
    for case_id, failed in sorted(truth.items()):
        draft = drafts.get(case_id)
        verdict = draft.get("verdict") if draft else "no draft"
        flagged = verdict in FLAGGED
        row = {"case_id": case_id, "verdict": verdict, "what_was_missing": (draft or {}).get("what_was_missing") or []}
        if failed and flagged:
            caught.append(row)
        elif failed:
            missed.append(row)
        elif flagged:
            false_flags.append(row)
    failures = sum(truth.values())
    passes = len(truth) - failures
    print(f"Known failures: {failures}. Drafter flagged {len(caught)} of them.")
    print(f"Passing cases: {passes}. Drafter flagged {len(false_flags)} of them.")
    print("\nCaught:")
    _print(caught)
    print("\nMissed:")
    _print(missed)
    print("\nWrongly flagged:")
    _print(false_flags)
    return 0


def _truth() -> dict[str, bool]:
    truth = {}
    for path in (TUNED, HELDOUT):
        payload = json.loads(path.read_text())
        for record in payload.get("cases") or []:
            case_id = (record.get("case") or {}).get("id")
            if case_id:
                truth[case_id] = not record.get("passed")
    return truth


def _latest_drafts() -> dict[str, dict]:
    latest = {}
    if not DRAFTS.exists():
        return latest
    for line in DRAFTS.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("case_id"):
            latest[row["case_id"]] = row
    return latest


def _print(rows: list[dict]) -> None:
    if not rows:
        print("  (none)")
        return
    for row in rows:
        missing = "; ".join(row["what_was_missing"][:3])
        tail = f" — {missing}" if missing else ""
        print(f"  {row['case_id']}: {row['verdict']}{tail}")


if __name__ == "__main__":
    raise SystemExit(main())
