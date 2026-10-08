"""One conversation turn. The model picks the tools. The runner only records them."""

from __future__ import annotations

import json

from docs_live import ROOT, load_config, quote_in_text
from trace import log_event

PROMPT = (ROOT / "prompt.txt").read_text()
ALLOWED = {"search_docs", "get_page", "write_handoff"}
REPLY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "answer": {"type": "string"},
        "clarifying_question": {"type": "string"},
        "citations": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "chunk_id": {"type": "string"},
                    "quote": {"type": "string"},
                },
                "required": ["chunk_id", "quote"],
            },
        },
        "abstain": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "required": ["answer", "clarifying_question", "citations", "abstain", "reason"],
}

TOOLS = [
    {
        "name": "search_docs",
        "description": "Search the live Kernel docs and return the top matching passages.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
    {
        "name": "get_page",
        "description": "Fetch one docs.kernel.ai page by its path, for example /concepts/kern-id. Optional query picks the passages on that page.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "query": {"type": "string"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_handoff",
        "description": "Write a handoff note when the docs do not contain the answer. Include the question, what was searched, and what is missing.",
        "input_schema": {
            "type": "object",
            "properties": {"summary": {"type": "string"}},
            "required": ["summary"],
        },
    },
]


def run_turn(docs, messages: list[dict], conversation_id: str, chunks: dict | None = None, chunk_meta: dict | None = None, on_event=None) -> dict:
    """Run one user turn. `messages` already ends with the new user message.

    Returns a turn record and leaves `messages` updated with the assistant path.
    `chunks` maps chunk id to the passage text used for citation checks.
    """
    config = load_config()
    chunks = chunks if chunks is not None else {}
    chunk_meta = chunk_meta if chunk_meta is not None else {}
    tool_calls: list[dict] = []
    handoff_written = False
    handoff_summary = ""
    usage = {"input_tokens": 0, "output_tokens": 0}
    cap = int(config["max_tool_calls"])

    def emit(event: dict) -> None:
        if on_event:
            on_event(event)

    from anthropic import Anthropic

    client = Anthropic()
    working = messages
    citation_retried = False
    citation_retry_problems: list[dict] = []
    format_retried = False
    abstain_search_retried = False
    handoff_retried = False
    depth_retried = False
    clarify_retried = False
    json_only = False

    while True:
        started = _ms()
        response = _create(client, config, working, json_only=json_only)
        latency = _ms() - started
        usage["input_tokens"] += response.usage.input_tokens
        usage["output_tokens"] += response.usage.output_tokens
        log_event(
            {
                "conversation_id": conversation_id,
                "kind": "model",
                "model": config["model"],
                "stop_reason": response.stop_reason,
                "latency_ms": latency,
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
                "cost_usd": _cost(config, response.usage.input_tokens, response.usage.output_tokens),
            }
        )

        blocks = _block_dicts(response.content)
        tool_uses = [block for block in blocks if block["type"] == "tool_use"]
        if not tool_uses:
            text = "".join(block["text"] for block in blocks if block["type"] == "text")
            working.append({"role": "assistant", "content": blocks or text})
            parsed, error = parse_reply(text)
            if error and not format_retried:
                format_retried = True
                json_only = True
                log_event(
                    {
                        "conversation_id": conversation_id,
                        "kind": "parse",
                        "stop_reason": response.stop_reason,
                        "block_types": [getattr(block, "type", None) for block in response.content],
                        "raw_text": text[:800],
                    }
                )
                working.append({"role": "user", "content": format_retry_message()})
                continue
            if not error:
                policy = policy_retry(
                    parsed,
                    tool_calls,
                    handoff_written,
                    abstain_search_retried=abstain_search_retried,
                    handoff_retried=handoff_retried,
                    depth_retried=depth_retried,
                    clarify_retried=clarify_retried,
                )
                if policy:
                    kind, message = policy
                    json_only = False
                    if kind == "search":
                        abstain_search_retried = True
                    elif kind == "handoff":
                        handoff_retried = True
                    elif kind == "depth":
                        depth_retried = True
                    else:
                        clarify_retried = True
                    working.append({"role": "user", "content": message})
                    continue
                problems = citation_problems(parsed, chunks)
                if problems and not citation_retried:
                    citation_retried = True
                    json_only = False
                    citation_retry_problems = problems
                    working.append({"role": "user", "content": citation_retry_message(problems)})
                    continue
            return _turn(
                parsed=parsed,
                parse_error=error,
                raw_text=text,
                tool_calls=tool_calls,
                chunks=chunks,
                chunk_meta=chunk_meta,
                handoff_written=handoff_written,
                handoff_summary=handoff_summary,
                usage=usage,
                citation_retried=citation_retried,
                citation_retry_problems=citation_retry_problems,
                format_retried=format_retried,
                abstain_search_retried=abstain_search_retried,
                handoff_retried=handoff_retried,
                depth_retried=depth_retried,
                clarify_retried=clarify_retried,
            )

        if len(tool_calls) + len(tool_uses) > cap:
            log_event(
                {
                    "conversation_id": conversation_id,
                    "kind": "cap",
                    "tool_calls": len(tool_calls) + len(tool_uses),
                }
            )
            return _turn(
                parsed={},
                parse_error=None,
                raw_text="",
                tool_calls=tool_calls,
                chunks=chunks,
                chunk_meta=chunk_meta,
                handoff_written=handoff_written,
                handoff_summary=handoff_summary,
                usage=usage,
                cap_exceeded=True,
            )

        working.append({"role": "assistant", "content": blocks})
        results = []
        for call in tool_uses:
            name = call["name"]
            arguments = call.get("input") or {}
            step_id = f"tool-{len(tool_calls)}"
            emit({"type": "step", "id": step_id, "state": "live", "text": _step_text(name, arguments, None)})
            if name not in ALLOWED:
                log_event(
                    {
                        "conversation_id": conversation_id,
                        "kind": "tool",
                        "tool": name,
                        "arguments": arguments,
                        "result_chars": 0,
                        "latency_ms": 0,
                        "error": "not allowed",
                    }
                )
                return _turn(
                    parsed={},
                    parse_error=None,
                    raw_text="",
                    tool_calls=tool_calls,
                    chunks=chunks,
                    chunk_meta=chunk_meta,
                    handoff_written=handoff_written,
                    handoff_summary=handoff_summary,
                    usage=usage,
                    unknown_tool=name,
                )
            tool_started = _ms()
            try:
                payload = _dispatch(docs, name, arguments, conversation_id)
                error = payload.get("error")
            except Exception as exc:  # the model should see the failure, not crash the turn
                payload = {"error": str(exc), "chunks": []}
                error = str(exc)
            tool_latency = _ms() - tool_started
            _emit_sections(emit, step_id, _section_lines(name, arguments, payload))
            encoded = json.dumps(payload, ensure_ascii=False)
            for chunk in payload.get("chunks") or []:
                chunks[chunk["chunk_id"]] = chunk["text"]
                chunk_meta[chunk["chunk_id"]] = chunk
            if name == "write_handoff" and not error:
                handoff_written = True
                handoff_summary = arguments.get("summary") or ""
            tool_calls.append(
                {
                    "name": name,
                    "arguments": arguments,
                    "latency_ms": tool_latency,
                    "result_chars": len(encoded),
                    "error": error,
                }
            )
            log_event(
                {
                    "conversation_id": conversation_id,
                    "kind": "tool",
                    "tool": name,
                    "arguments": arguments,
                    "result_chars": len(encoded),
                    "latency_ms": tool_latency,
                    "cost_usd": 0,
                }
            )
            results.append({"type": "tool_result", "tool_use_id": call["id"], "content": encoded})
        working.append({"role": "user", "content": results})


DOC_LOOKUP_TOOLS = {"search_docs", "get_page"}


def doc_lookup_count(tool_calls: list[dict]) -> int:
    return sum(1 for call in tool_calls if call.get("name") in DOC_LOOKUP_TOOLS)


def policy_retry(
    parsed: dict,
    tool_calls: list[dict],
    handoff_written: bool,
    *,
    abstain_search_retried: bool,
    handoff_retried: bool,
    depth_retried: bool,
    clarify_retried: bool,
) -> tuple[str, str] | None:
    """One send-back. A clarifying question is not sent back: an ambiguous case is supposed to ask before it searches."""
    _ = clarify_retried
    abstain = bool(parsed.get("abstain"))
    question = (parsed.get("clarifying_question") or "").strip()
    answer = (parsed.get("answer") or "").strip()
    lookups = doc_lookup_count(tool_calls)
    asking = bool(question) and not answer and not abstain
    if abstain and lookups < 2 and not abstain_search_retried:
        return "search", search_before_abstain_message()
    if abstain and not handoff_written and not handoff_retried:
        return "handoff", handoff_retry_message()
    if answer and not abstain and not asking and lookups < 2 and not depth_retried:
        return "depth", second_search_message()
    return None


def search_before_abstain_message() -> str:
    return (
        "You abstained before two lookups. Search the docs again with different words, or open the page, before you abstain. "
        "You need at least two calls of search_docs or get_page. If the docs still do not contain the answer, call write_handoff and then abstain. "
        "Do not invent a support channel."
    )


def handoff_retry_message() -> str:
    return (
        "You abstained without write_handoff. Call write_handoff with what you searched and what is missing, "
        "then reply again with abstain true. The answer may only say what the docs do not contain."
    )


def clarify_retry_message() -> str:
    return (
        "You asked a question before looking. Ask only when the answer depends on a fact the user has not given, such as which company or which field. "
        "If they have not named that fact, ask for it and do not answer from an example in the docs. "
        "If they already named the relationship, the company, or the field, answer it. "
        "If the request is a price, a refund, a private record, compensation, or a change to Kernel data, do not ask them to choose. "
        "Search twice, call write_handoff, and abstain."
    )


def second_search_message() -> str:
    return (
        "You answered after a single lookup. Search again before you answer. "
        "Prefer the concept page that defines the term over a setup or task page, and open that page if the first search only mentioned it. "
        "Use the page's own words, including an exclusion or a distinction the page draws."
    )


def citation_problems(parsed: dict, chunks: dict) -> list[dict]:
    """A quote fails when it is not one contiguous stretch of the chunk the model was given."""
    problems = []
    for citation in parsed.get("citations") or []:
        quote = citation.get("quote") or ""
        chunk_id = citation.get("chunk_id") or ""
        text = chunks.get(chunk_id, "")
        if text and quote_in_text(quote, text):
            continue
        found_in = _chunk_containing(quote, chunks, skip=chunk_id)
        if found_in:
            reason = f"that quote is in chunk {found_in}, not in chunk {chunk_id}"
        else:
            reason = "not a contiguous passage in the chunk the model was given"
        problem = {"chunk_id": chunk_id, "quote": quote, "reason": reason}
        if found_in:
            problem["found_in"] = found_in
        hint = _hint_sentence(quote, text)
        if hint:
            problem["hint"] = hint
        problems.append(problem)
    return problems


def _chunk_containing(quote: str, chunks: dict, skip: str) -> str:
    for chunk_id, text in chunks.items():
        if chunk_id == skip:
            continue
        if text and quote_in_text(quote, text):
            return chunk_id
    return ""


def _hint_sentence(quote: str, text: str) -> str:
    """One real sentence from the chunk, for the retry to copy."""
    import re

    words = set(re.findall(r"[a-z0-9]+", quote.lower())) - {
        "the", "a", "an", "of", "and", "or", "for", "to", "is", "in", "on",
    }
    best = ""
    best_score = 1
    for sentence in re.split(r"(?<=[.!?])\s+", " ".join(text.split())):
        sentence = sentence.strip()
        count = len(sentence.split())
        if count < 4 or count > 30:
            continue
        score = len(words & set(re.findall(r"[a-z0-9]+", sentence.lower())))
        if score > best_score and quote_in_text(sentence, text):
            best = sentence
            best_score = score
    return best


def format_retry_message() -> str:
    return (
        "The reply was not a JSON object, so it cannot be checked. "
        "Reply again with one JSON object and no other text. "
        "If the question is ambiguous, put one question in clarifying_question and leave answer empty. "
        "Do not answer from memory."
    )


def citation_retry_message(problems: list[dict]) -> str:
    lines = [
        "The citation check rejected this reply. Do not change the facts in the answer. Reply again in the same JSON shape.",
        "Each quote must be one contiguous sentence copied from a single chunk, under 30 words. Do not join bullets, table rows, or separate sentences. Copy the words exactly as they appear.",
        "Rejected quotes:",
    ]
    for problem in problems:
        lines.append(f"- chunk {problem['chunk_id']}: {problem['quote']}")
        if problem.get("found_in"):
            lines.append(f"  That quote is in chunk {problem['found_in']}. Cite that chunk, not {problem['chunk_id']}.")
        if problem.get("hint"):
            lines.append(f"  Copy this sentence exactly if it supports the claim: {problem['hint']}")
        elif not problem.get("found_in"):
            lines.append("  If this is a diagram line or a line of code, drop it and quote a sentence instead.")
    return "\n".join(lines)


def _step_text(name: str, arguments: dict, payload: dict | None) -> str:
    return _section_lines(name, arguments, payload)[0]


def _section_lines(name: str, arguments: dict, payload: dict | None) -> list[str]:
    if name == "write_handoff":
        return ["The docs don't cover this"]
    if payload is None:
        return ["Looking through the docs"]
    if payload.get("error"):
        return [str(payload["error"])]
    titles = _titles(payload)
    if not titles:
        return ["Nothing in the docs matched"]
    return [f"Looking through {title}" for title in titles]


def _emit_sections(emit, step_id: str, lines: list[str]) -> None:
    emit({"type": "step", "id": step_id, "state": "done", "text": lines[0]})
    for index, line in enumerate(lines[1:], start=1):
        emit({"type": "step", "id": f"{step_id}-{index}", "state": "done", "text": line})


def _titles(payload: dict) -> list[str]:
    found = []
    for chunk in payload.get("chunks") or []:
        heading = (chunk.get("heading") or "").strip()
        title = (chunk.get("title") or "").strip()
        # A short heading is a section. A long heading is a sentence inside the page.
        label = heading if heading and len(heading.split()) <= 6 else title
        if label and label not in found:
            found.append(label)
    return found[:6]


def parse_reply(text: str) -> tuple[dict, str | None]:
    raw = text.strip()
    fenced = raw
    if "```" in raw:
        start = raw.find("```")
        rest = raw[start + 3 :]
        if rest.startswith("json"):
            rest = rest[4:]
        end = rest.find("```")
        fenced = rest[:end] if end != -1 else rest
    start = fenced.find("{")
    end = fenced.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return {}, "no JSON object in the final reply"
    try:
        payload = json.loads(fenced[start : end + 1])
    except json.JSONDecodeError as exc:
        return {}, str(exc)
    if not isinstance(payload, dict):
        return {}, "final reply was not a JSON object"
    if not isinstance(payload.get("abstain"), bool):
        return {}, "abstain must be a boolean"
    citations = payload.get("citations", [])
    if not isinstance(citations, list):
        return {}, "citations must be a list"
    clean = []
    for item in citations:
        if not isinstance(item, dict):
            return {}, "each citation must be an object"
        clean.append({"chunk_id": str(item.get("chunk_id") or ""), "quote": str(item.get("quote") or "")})
    return (
        {
            "answer": str(payload.get("answer") or ""),
            "clarifying_question": str(payload.get("clarifying_question") or ""),
            "citations": clean,
            "abstain": payload["abstain"],
            "reason": str(payload.get("reason") or ""),
        },
        None,
    )


def verify_citations(parsed: dict, chunks: dict, chunk_meta: dict | None = None) -> list[dict]:
    meta = chunk_meta or {}
    verified = []
    for citation in parsed.get("citations") or []:
        text = chunks.get(citation["chunk_id"], "")
        info = meta.get(citation["chunk_id"]) or {}
        verified.append(
            {
                **citation,
                "verified": bool(text) and quote_in_text(citation["quote"], text),
                "url": info.get("url") or "",
                "heading": info.get("heading") or "",
                "fetched_at": info.get("fetched_at") or "",
            }
        )
    return verified


def _dispatch(docs, name: str, arguments: dict, conversation_id: str) -> dict:
    if name == "search_docs":
        return docs.search(str(arguments.get("query") or ""))
    if name == "get_page":
        return docs.get_page(str(arguments.get("path") or ""), str(arguments.get("query") or ""))
    summary = str(arguments.get("summary") or "").strip()
    if not summary:
        return {"error": "summary is required", "chunks": []}
    path = ROOT / "logs" / "handoffs.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {"conversation_id": conversation_id, "summary": summary}
    with path.open("a") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return {"written": True, "chunks": []}


def _turn(**fields) -> dict:
    fields.setdefault("cap_exceeded", False)
    fields.setdefault("unknown_tool", None)
    fields.setdefault("citation_retried", False)
    fields.setdefault("citation_retry_problems", [])
    fields.setdefault("format_retried", False)
    fields.setdefault("abstain_search_retried", False)
    fields.setdefault("handoff_retried", False)
    fields.setdefault("depth_retried", False)
    fields.setdefault("clarify_retried", False)
    return fields


def _create(client, config: dict, messages: list[dict], *, json_only: bool):
    kwargs = {
        "model": config["model"],
        "max_tokens": int(config["max_tokens"]),
        "system": PROMPT,
        "messages": messages,
    }
    if json_only:
        kwargs["output_config"] = {"format": {"type": "json_schema", "schema": REPLY_SCHEMA}}
    else:
        kwargs["tools"] = TOOLS
    return client.messages.create(**kwargs)


def _block_dicts(content) -> list[dict]:
    blocks = []
    for block in content:
        if block.type == "text":
            blocks.append({"type": "text", "text": block.text})
        elif block.type == "tool_use":
            blocks.append({"type": "tool_use", "id": block.id, "name": block.name, "input": block.input})
    return blocks


def _cost(config: dict, input_tokens: int, output_tokens: int) -> float:
    rates = config["pricing_per_million_tokens"]
    return round((input_tokens * rates["input"] + output_tokens * rates["output"]) / 1_000_000, 6)


def _ms() -> int:
    import time

    return int(time.time() * 1000)
