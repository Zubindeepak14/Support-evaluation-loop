"""One record per conversation. The drafter reads this log. It does not grade."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from docs_live import ROOT, quote_in_text

CANDIDATES = ROOT / "logs" / "candidates.jsonl"
DOC_TOOLS = {"search_docs", "get_page"}
TUNED_RESULT = ROOT / "evals" / "results" / "2026-10-08T100133Z.json"
HELDOUT_RESULT = ROOT / "evals" / "results" / "heldout-2026-10-08T100916Z.json"


def signals_for(turns: list[dict], visitor_flag: bool = False) -> dict:
    quote_retry = False
    quote_failed = False
    abstain = False
    asked = False
    answer_without_docs = False
    for turn in turns:
        parsed = turn.get("parsed") or {}
        quote_retry = quote_retry or bool(turn.get("citation_retried"))
        abstain = abstain or bool(parsed.get("abstain"))
        question = (parsed.get("clarifying_question") or "").strip()
        answer = (parsed.get("answer") or "").strip()
        if question and not answer:
            asked = True
        names = {call.get("name") for call in turn.get("tool_calls") or []}
        if answer and not parsed.get("abstain") and not (names & DOC_TOOLS):
            answer_without_docs = True
        chunks = turn.get("chunks") or {}
        for citation in parsed.get("citations") or []:
            chunk_id = citation.get("chunk_id") or ""
            quote = citation.get("quote") or ""
            if chunk_id not in chunks or not quote_in_text(quote, chunks.get(chunk_id) or ""):
                quote_failed = True
    return {
        "quote_retry_fired": quote_retry,
        "quote_failed": quote_failed,
        "abstain": abstain,
        "clarifying_question_with_no_answer": asked,
        "answer_with_no_docs_tool": answer_without_docs,
        "visitor_flag": bool(visitor_flag),
    }


def conversation_from(case: dict, turns: list[dict]) -> list[dict]:
    """User lines come from the case. Assistant lines come from the saved turns."""
    users = [case.get("question") or ""]
    if len(turns) > 1:
        users.append(case.get("scripted_reply") or "")
    conversation = []
    for index, turn in enumerate(turns):
        if index < len(users):
            conversation.append({"role": "user", "content": users[index]})
        parsed = turn.get("parsed") or {}
        conversation.append(
            {
                "role": "assistant",
                "answer": parsed.get("answer") or "",
                "clarifying_question": parsed.get("clarifying_question") or "",
                "abstain": bool(parsed.get("abstain")),
                "reason": parsed.get("reason") or "",
                "citations": parsed.get("citations") or [],
                "tool_calls": [
                    {"name": call.get("name"), "arguments": call.get("arguments") or {}}
                    for call in turn.get("tool_calls") or []
                ],
            }
        )
    return conversation


def chunks_from(turns: list[dict]) -> list[dict]:
    found = {}
    for turn in turns:
        meta = turn.get("chunk_meta") or {}
        for chunk_id, text in (turn.get("chunks") or {}).items():
            info = meta.get(chunk_id) or {}
            if isinstance(info, dict) and info.get("text"):
                text = info.get("text") or text
            found[chunk_id] = {
                "chunk_id": chunk_id,
                "text": text if isinstance(text, str) else "",
                "url": info.get("url") or "" if isinstance(info, dict) else "",
                "heading": info.get("heading") or "" if isinstance(info, dict) else "",
                "title": info.get("title") or "" if isinstance(info, dict) else "",
            }
    return list(found.values())


def record_conversation(
    *,
    candidate_id: str,
    set_name: str | None,
    case_id: str,
    turns: list[dict],
    case: dict | None = None,
    visitor_flag: bool = False,
    source: str = "",
) -> dict:
    case = case or {}
    row = {
        "id": candidate_id,
        "set": set_name,
        "case_id": case_id,
        "recorded_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "source": source,
        "conversation": conversation_from(case, turns) if case else _desk_conversation(turns),
        "chunks": chunks_from(turns),
        "signals": signals_for(turns, visitor_flag),
    }
    _append(row)
    return row


def record_desk_turn(conversation_id: str, turn_index: int, user_text: str, turn: dict) -> dict:
    wrapped = dict(turn)
    row = {
        "id": f"desk:{conversation_id}:{turn_index}",
        "set": None,
        "case_id": "",
        "recorded_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "source": "desk",
        "conversation_id": conversation_id,
        "turn_index": turn_index,
        "conversation": _desk_conversation([wrapped], user_text),
        "chunks": chunks_from([wrapped]),
        "signals": signals_for([wrapped], False),
    }
    _append(row)
    return row


def mark_visitor_flag(conversation_id: str, turn_index: int) -> None:
    target = f"desk:{conversation_id}:{turn_index}"
    latest = load_latest().get(target)
    if not latest:
        return
    latest["signals"]["visitor_flag"] = True
    latest["recorded_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    _append(latest)


def seed_saved_runs() -> int:
    """Write the 32 saved conversations once. Later lines for the same id replace them."""
    written = 0
    existing = load_latest()
    for path, set_name in ((TUNED_RESULT, "tuned"), (HELDOUT_RESULT, "held-out")):
        if not path.exists():
            continue
        payload = json.loads(path.read_text())
        for record in payload.get("cases") or []:
            case = record.get("case") or {}
            candidate_id = f"{set_name}:{path.stem}:{case.get('id')}"
            if candidate_id in existing:
                continue
            record_conversation(
                candidate_id=candidate_id,
                set_name=set_name,
                case_id=case.get("id") or "",
                turns=record.get("turns") or [],
                case=case,
                visitor_flag=bool(case.get("flagged")),
                source=str(path.relative_to(ROOT)),
            )
            written += 1
    return written


def load_latest() -> dict[str, dict]:
    latest = {}
    if not CANDIDATES.exists():
        return latest
    for line in CANDIDATES.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        latest[row["id"]] = row
    return latest


def _desk_conversation(turns: list[dict], user_text: str = "") -> list[dict]:
    conversation = []
    if user_text:
        conversation.append({"role": "user", "content": user_text})
    for turn in turns:
        parsed = turn.get("parsed") or {}
        conversation.append(
            {
                "role": "assistant",
                "answer": parsed.get("answer") or "",
                "clarifying_question": parsed.get("clarifying_question") or "",
                "abstain": bool(parsed.get("abstain")),
                "reason": parsed.get("reason") or "",
                "citations": parsed.get("citations") or [],
                "tool_calls": [
                    {"name": call.get("name"), "arguments": call.get("arguments") or {}}
                    for call in turn.get("tool_calls") or []
                ],
            }
        )
    return conversation


def _append(row: dict) -> None:
    CANDIDATES.parent.mkdir(parents=True, exist_ok=True)
    with CANDIDATES.open("a") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
