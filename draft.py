"""Draft from the docs first, then compare with the agent's reply.

The model does not grade a suite case. Code keeps a fact only when it appears
word for word in a chunk, and keeps a sentence of the proposed answer only
when that sentence appears in a chunk.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from candidates import load_latest, seed_saved_runs
from docs_live import ROOT, DocsClient, load_config

DRAFTS = ROOT / "logs" / "drafts.jsonl"
VERDICTS = {"ok", "incomplete", "agent_failure", "docs_gap", "should_have_refused"}
CATCH = {"incomplete", "agent_failure", "should_have_refused"}
BLIND_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "proposed_answer": {"type": "string"},
        "required_facts": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["proposed_answer", "required_facts"],
}
COMPARE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "verdict": {"type": "string", "enum": sorted(VERDICTS)},
        "what_was_missing": {"type": "array", "items": {"type": "string"}},
        "marker": {"type": "string"},
        "absence_queries": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["verdict", "what_was_missing", "marker", "absence_queries"],
}
BLIND_PROMPT = """You answer a support question from the passages below. You have not seen anyone else's answer. Do not invent a fact.

Write the answer a careful support agent should give, using only these passages.
required_facts is every phrase from those passages that the answer needs. Copy each phrase word for word. Do not paraphrase.
If the passages do not contain the answer, leave proposed_answer and required_facts empty.

Reply with one JSON object and no other text."""
COMPARE_PROMPT = """You are comparing two answers. You do not grade a test suite.

You already wrote an answer from the docs. You are now shown the agent's final reply.
verdict:
- ok: the agent's reply contains the facts your answer needed, and does not contradict them.
- incomplete: the agent's reply is partly right but leaves out one or more of your facts.
- agent_failure: the agent's reply contradicts your facts, or asks the user for something the question already answered.
- should_have_refused: the passages do not contain the answer, and the agent answered or asked a question instead of refusing.
- docs_gap: the passages do not contain the answer. marker is a phrase of at least three words naming the topic the user asked about. absence_queries is two different search phrases for that topic.

what_was_missing is the required_facts from your own answer that the agent's reply left out or contradicted. Copy them word for word. For ok, leave it empty.
marker and absence_queries are empty unless the verdict is docs_gap.

Reply with one JSON object and no other text."""


def main() -> int:
    added = seed_saved_runs()
    print(f"Seeded {added} new candidates.", flush=True)
    config = load_config()
    docs = DocsClient()
    pending = [
        row for row in load_latest().values()
        if row.get("set") in {"tuned", "held-out"}
    ]
    pending.sort(key=lambda row: (row.get("set") or "", row.get("case_id") or row["id"]))
    print(f"Drafting {len(pending)} conversations with {config['drafter_model']}, blind then compare.", flush=True)
    from anthropic import Anthropic

    client = Anthropic()
    drafts = []
    for index, candidate in enumerate(pending, start=1):
        label = candidate.get("case_id") or candidate["id"]
        print(f"[{index}/{len(pending)}] {label}", flush=True)
        try:
            draft = draft_one(client, config, docs, candidate)
        except Exception as exc:
            draft = _error_draft(candidate, config, f"{type(exc).__name__}: {exc}")
        drafts.append(draft)
        print(
            f"  {draft['verdict']}  facts {len(draft['required_facts'])}  missing {len(draft['what_was_missing'])}  unsupported {len(draft['unsupported_sentences'])}",
            flush=True,
        )
    DRAFTS.parent.mkdir(parents=True, exist_ok=True)
    DRAFTS.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in drafts))
    print(f"\nWrote {DRAFTS}")
    return 0


def draft_one(client, config: dict, docs: DocsClient, candidate: dict) -> dict:
    question = _question_text(candidate)
    wider = docs.search(question, k=10).get("chunks") or [] if question.strip() else []
    blind = _complete(client, config, BLIND_PROMPT, BLIND_SCHEMA, {
        "question": question,
        "passages": _for_model(wider),
    })
    kept, dropped = _split_facts(blind.get("required_facts") or [], wider)
    supported, unsupported = _split_sentences(str(blind.get("proposed_answer") or ""), wider)
    agent_reply = _agent_reply(candidate)
    compared = _complete(client, config, COMPARE_PROMPT, COMPARE_SCHEMA, {
        "question": question,
        "your_answer": " ".join(supported),
        "your_facts": kept,
        "agent_reply": agent_reply,
    })
    verdict = compared.get("verdict") if compared.get("verdict") in VERDICTS else "unclear"
    missing, dropped_missing = _missing_facts(compared.get("what_was_missing") or [], kept, wider)
    gap = None
    if verdict == "docs_gap":
        gap = _gap_case(docs, question, str(compared.get("marker") or ""), compared.get("absence_queries") or [])
    return {
        "candidate_id": candidate["id"],
        "set": candidate.get("set"),
        "case_id": candidate.get("case_id") or "",
        "drafted_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "model": config["drafter_model"],
        "verdict": verdict,
        "proposed_answer": " ".join(supported),
        "unsupported_sentences": unsupported,
        "required_facts": kept,
        "dropped_facts": dropped,
        "what_was_missing": missing,
        "dropped_missing": dropped_missing,
        "marker": str(compared.get("marker") or ""),
        "out_of_scope_case": gap,
    }


def _complete(client, config: dict, prompt: str, schema: dict, payload: dict) -> dict:
    response = client.messages.create(
        model=config["drafter_model"],
        max_tokens=1500,
        system=prompt,
        messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
        output_config={"format": {"type": "json_schema", "schema": schema}},
    )
    text = "".join(block.text for block in response.content if block.type == "text")
    return json.loads(text)


def _split_facts(facts: list, chunks: list[dict]) -> tuple[list[str], list[str]]:
    kept, dropped = [], []
    haystacks = _haystacks(chunks)
    for fact in facts:
        phrase = " ".join(str(fact).split())
        if len(phrase) < 2:
            continue
        if any(phrase in hay for hay in haystacks):
            kept.append(phrase)
        else:
            dropped.append(phrase)
    return kept, dropped


def _missing_facts(claimed: list, stage_one: list[str], chunks: list[dict]) -> tuple[list[str], list[str]]:
    """Keep a missing fact only when stage 1 listed it and a chunk contains it."""
    allowed = {" ".join(fact.split()) for fact in stage_one}
    haystacks = _haystacks(chunks)
    kept, dropped = [], []
    for fact in claimed:
        phrase = " ".join(str(fact).split())
        if phrase in allowed and any(phrase in hay for hay in haystacks):
            kept.append(phrase)
        elif phrase:
            dropped.append(phrase)
    return kept, dropped


def _split_sentences(answer: str, chunks: list[dict]) -> tuple[list[str], list[str]]:
    haystacks = _haystacks(chunks)
    supported, unsupported = [], []
    for sentence in re.split(r"(?<=[.!?])\s+", answer.strip()):
        phrase = " ".join(sentence.split())
        if len(phrase) < 2:
            continue
        if any(phrase in hay for hay in haystacks):
            supported.append(phrase)
        else:
            unsupported.append(phrase)
    return supported, unsupported


def _gap_case(docs: DocsClient, question: str, marker: str, queries: list) -> dict:
    marker = " ".join(marker.split())
    words = marker.split()
    if len(words) < 3:
        return {"marker": marker, "marker_absent": False, "reason": "marker is shorter than three words", "case": None}
    searches = []
    for query in list(queries)[:2]:
        text = " ".join(str(query).split())
        if text and text not in searches:
            searches.append(text)
    while len(searches) < 2:
        searches.append(marker if len(searches) == 0 else question)
    found_in = []
    corpus = docs.corpus_text().lower()
    if marker.lower() in corpus:
        found_in.append("corpus")
    for query in searches[:2]:
        chunks = docs.search(query, k=10).get("chunks") or []
        if any(marker.lower() in " ".join((chunk.get("text") or "").split()).lower() for chunk in chunks):
            found_in.append(query)
    absent = not found_in
    case = None
    if absent:
        case = {
            "kind": "out_of_scope",
            "question": question,
            "expect_abstain": True,
            "confirmed_absent": [marker],
            "set": "from-users",
        }
    return {"marker": marker, "marker_absent": absent, "searches": searches[:2], "found_in": found_in, "case": case}


def _question_text(candidate: dict) -> str:
    parts = []
    for message in candidate.get("conversation") or []:
        if message.get("role") == "user":
            parts.append(message.get("content") or "")
    return "\n".join(part for part in parts if part)


def _agent_reply(candidate: dict) -> dict:
    reply = {"answer": "", "clarifying_question": "", "abstain": False}
    for message in candidate.get("conversation") or []:
        if message.get("role") == "assistant":
            reply = {
                "answer": message.get("answer") or "",
                "clarifying_question": message.get("clarifying_question") or "",
                "abstain": bool(message.get("abstain")),
            }
    return reply


def _haystacks(chunks: list[dict]) -> list[str]:
    return [" ".join((chunk.get("text") or "").split()) for chunk in chunks]


def _for_model(chunks: list[dict]) -> list[dict]:
    packed = []
    for chunk in chunks[:10]:
        packed.append(
            {
                "chunk_id": chunk.get("chunk_id") or "",
                "url": chunk.get("url") or "",
                "heading": chunk.get("heading") or "",
                "text": (chunk.get("text") or "")[:2500],
            }
        )
    return packed


def _error_draft(candidate: dict, config: dict, message: str) -> dict:
    return {
        "candidate_id": candidate["id"],
        "set": candidate.get("set"),
        "case_id": candidate.get("case_id") or "",
        "drafted_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "model": config.get("drafter_model"),
        "verdict": "unclear",
        "proposed_answer": "",
        "unsupported_sentences": [],
        "required_facts": [],
        "dropped_facts": [],
        "what_was_missing": [],
        "dropped_missing": [],
        "marker": "",
        "out_of_scope_case": None,
        "error": message,
    }


if __name__ == "__main__":
    raise SystemExit(main())
