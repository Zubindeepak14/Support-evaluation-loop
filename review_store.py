"""Complaints waiting for a label. A label does not create a test."""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone

from docs_live import ROOT

PATH = ROOT / "logs" / "review.jsonl"
SEED = ROOT / "evals" / "demo_review.jsonl"
_LOCK = threading.Lock()

LABELS = {
    "wrong_answer": {
        "label": "Wrong answer",
        "owner": "The person who looks after the agent",
    },
    "should_have_refused": {
        "label": "Should have refused",
        "owner": "The person who looks after the agent",
    },
    "incomplete": {
        "label": "Incomplete",
        "owner": "The person who looks after the agent",
    },
    "docs_gap": {
        "label": "Docs don't cover this",
        "owner": "The person who looks after the docs",
    },
}

# Recorded runs from the build. Labelling a complaint does not change these.
EXAM = {
    "first_run": {"passed": 14, "total": 26, "label": "First run"},
    "after_fixes": {"low": 19, "high": 20, "total": 26, "label": "After fixes"},
    "held_out": {"passed": 2, "total": 6, "label": "Held out"},
    "note": "Recorded runs from the build, not an automatic rerun after every edit. Labelling a complaint does not change these numbers. The held-out score is the one to trust.",
}


def add_complaint(question: str, answer: str) -> dict:
    row = {
        "id": uuid.uuid4().hex[:12],
        "question": question.strip(),
        "answer": answer.strip(),
        "label": None,
        "created_at": _now(),
    }
    if not row["question"]:
        raise ValueError("question is required")
    if not row["answer"]:
        raise ValueError("answer is required")
    with _LOCK:
        _append(row)
    return _public(row)


def set_label(item_id: str, label: str) -> dict:
    if label not in LABELS:
        raise ValueError("unknown label")
    with _LOCK:
        rows = _read()
        found = None
        for row in rows:
            if row["id"] == item_id:
                row["label"] = label
                row["labelled_at"] = _now()
                found = row
        if found is None:
            raise KeyError(item_id)
        _write(rows)
    return _public(found)


def summary() -> dict:
    rows = [_public(row) for row in _read()]
    waiting = [row for row in rows if not row["label"]]
    labelled = [row for row in rows if row["label"]]
    counts = {key: 0 for key in LABELS}
    for row in labelled:
        counts[row["label_id"]] += 1
    return {
        "waiting": len(waiting),
        "labelled": len(labelled),
        "counts": counts,
        "items": rows,
        "labels": LABELS,
        "exam": EXAM,
    }


def _public(row: dict) -> dict:
    label_id = row.get("label")
    info = LABELS.get(label_id) or {}
    return {
        "id": row["id"],
        "question": row["question"],
        "answer": row["answer"],
        "label_id": label_id,
        "label": info.get("label") or "",
        "owner": info.get("owner") or "",
        "created_at": row.get("created_at") or "",
    }


def _read() -> list[dict]:
    rows = _lines(SEED)
    if PATH.exists():
        rows.extend(_lines(PATH))
    # Last write for an id wins. The file is rewritten on label, so ids are unique.
    latest = {}
    for row in rows:
        latest[row["id"]] = row
    return list(latest.values())


def _lines(path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text().splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _write(rows: list[dict]) -> None:
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))


def _append(row: dict) -> None:
    PATH.parent.mkdir(parents=True, exist_ok=True)
    with PATH.open("a") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
