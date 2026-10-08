"""Append-only trace outside the agent. A misbehaving reply is still logged."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TRACE_PATH = ROOT / "logs" / "trace.jsonl"
_LOCK = threading.Lock()


def log_event(event: dict) -> None:
    TRACE_PATH.parent.mkdir(parents=True, exist_ok=True)
    row = {"timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat(), **event}
    line = json.dumps(row, ensure_ascii=False)
    with _LOCK:
        with TRACE_PATH.open("a") as handle:
            handle.write(line + "\n")
