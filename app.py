"""Local page for the docs desk. The model key stays in the environment."""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from cases_store import append_flagged_case, load_cases
from docs_live import ROOT, DocsClient, load_config
from review_store import add_complaint, set_label, summary as review_summary

PUBLIC_DEMO = os.environ.get("PUBLIC_DEMO") == "1"
PAGE = ROOT / "static" / "index.html"
SUITE = ROOT / "static" / "suite.html"
BULK_PAGE = ROOT / "static" / "bulk.html"
BULK_RUNS = [
    {
        "id": "first",
        "title": "First run",
        "score": "14 of 26",
        "note": "One pass over the 26 questions, before the refusal and search fixes. Graded in code.",
        "files": ["2026-10-08T093457Z.json"],
    },
    {
        "id": "after",
        "title": "After fixes",
        "score": "19 to 20 of 26",
        "note": "Three passes after the fixes. The score moved between 19 and 20. These lanes are that recorded pass, not a new run.",
        "files": [
            "2026-10-08T095403Z.json",
            "2026-10-08T095756Z.json",
            "2026-10-08T100133Z.json",
        ],
    },
    {
        "id": "held",
        "title": "Held out",
        "score": "2 of 6",
        "note": "Six questions the agent had not been run against. This is the number to trust.",
        "files": ["heldout-2026-10-08T100916Z.json"],
    },
]
RESULTS = ROOT / "evals" / "results"
NO_CACHE = {"Cache-Control": "no-cache"}

docs = DocsClient()
sessions: dict[str, dict] = {}
session_lock = threading.Lock()
hits: dict[str, list[float]] = {}
ready = {"state": "starting", "pages": 0, "error": ""}


@asynccontextmanager
async def lifespan(_app):
    def run() -> None:
        try:
            ready["pages"] = docs.warm()
            ready["state"] = "ready"
            ready["error"] = ""
        except Exception as exc:
            ready["state"] = "error"
            ready["error"] = str(exc)

    threading.Thread(target=run, daemon=True).start()
    yield


app = FastAPI(lifespan=lifespan)


@app.get("/")
@app.get("/suite")
@app.get("/review")
@app.get("/bulk")
@app.get("/about")
def index():
    return FileResponse(PAGE, headers=NO_CACHE)


@app.get("/app.css")
def app_css():
    return FileResponse(ROOT / "static" / "app.css", media_type="text/css", headers=NO_CACHE)


@app.get("/app.js")
def app_js():
    return FileResponse(ROOT / "static" / "app.js", media_type="text/javascript", headers=NO_CACHE)


@app.get("/api/health")
def health():
    config = load_config()
    return {
        "model": config["model"],
        "cache_ttl_seconds": config["cache_ttl_seconds"],
        "docs_index_url": config["docs_index_url"],
        "docs": ready["state"],
        "pages": ready["pages"],
        "docs_error": ready["error"],
        "public_demo": PUBLIC_DEMO,
        "max_tool_calls": config["max_tool_calls"],
    }


@app.get("/api/prompt")
def prompt():
    return {"prompt": (ROOT / "prompt.txt").read_text()}


RULES = {
    "in_scope": "Answerable. The reply must include every required fact, cite a quote that exists in the fetched page, and must not refuse.",
    "ambiguous": "Ambiguous. The first reply must be a question. The answer after the follow-up must include the facts and a real citation.",
    "out_of_scope": "Out of scope. The reply must refuse and write a handoff. A confident answer fails.",
}


@app.get("/api/cases")
def cases():
    saved = _latest_by_id()
    run = saved.get("run")
    rows = []
    for case in load_cases():
        result = saved["by_id"].get(case["id"])
        rows.append(
            {
                "id": case["id"],
                "kind": case["kind"],
                "question": case["question"],
                "required_facts": case.get("required_facts") or [],
                "scripted_reply": case.get("scripted_reply") or "",
                "flagged": bool(case.get("flagged")),
                "rule": RULES.get(case["kind"], ""),
                "passed": None if result is None else result["passed"],
                "reasons": [] if result is None else result["reasons"],
            }
        )
    return {"run": run, "cases": rows}


def _suite_result_files() -> list:
    """Full suite runs only. Held-out files live beside them and must not blank the page."""
    return sorted(path for path in RESULTS.glob("*.json") if not path.name.startswith("heldout-"))


def _latest_by_id() -> dict:
    files = _suite_result_files()
    if not files:
        return {"run": None, "by_id": {}}
    payload = json.loads(files[-1].read_text())
    by_id = {
        item["case"]["id"]: {"passed": item["passed"], "reasons": item["reasons"]}
        for item in payload.get("cases", [])
    }
    return {
        "run": {
            "file": files[-1].name,
            "run_at": payload.get("run_at"),
            "model": payload.get("model"),
            "passed": payload.get("passed"),
            "total": payload.get("total"),
        },
        "by_id": by_id,
    }


@app.get("/api/results")
def latest_results():
    files = _suite_result_files()
    if not files:
        return {"available": False}
    payload = json.loads(files[-1].read_text())
    return {
        "available": True,
        "file": files[-1].name,
        "run_at": payload.get("run_at"),
        "model": payload.get("model"),
        "passed": payload.get("passed"),
        "total": payload.get("total"),
        "cases": [
            {"id": item["case"]["id"], "kind": item["case"]["kind"], "passed": item["passed"], "reasons": item["reasons"]}
            for item in payload.get("cases", [])
        ],
    }


@app.post("/api/chat")
async def chat(request: Request):
    limited = _rate_limit(request)
    if limited:
        return limited
    body = await request.json()
    message = str(body.get("message") or "").strip()
    if not message:
        return JSONResponse({"error": "message is required"}, status_code=400)
    if len(message) > 2000:
        return JSONResponse({"error": "message is too long"}, status_code=400)
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return JSONResponse(
            {"error": "ANTHROPIC_API_KEY is not set on this server. The page can load. The model cannot be called."},
            status_code=503,
        )

    conversation_id = str(body.get("conversation_id") or uuid.uuid4())
    with session_lock:
        session = sessions.setdefault(
            conversation_id,
            {"messages": [], "chunks": {}, "chunk_meta": {}, "turns": []},
        )
        session["messages"].append({"role": "user", "content": message})

    from agent import run_turn, verify_citations

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def on_event(event: dict | None) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, event)

    def work() -> None:
        try:
            turn = run_turn(
                docs,
                session["messages"],
                conversation_id,
                session["chunks"],
                session["chunk_meta"],
                on_event=on_event,
            )
            parsed = turn.get("parsed") or {}
            shown = parsed.get("answer") or parsed.get("clarifying_question") or turn.get("raw_text") or ""
            with session_lock:
                session["turns"].append({"question": message, "answer": shown})
                turn_index = len(session["turns"]) - 1
            citations = verify_citations(parsed, session["chunks"], session["chunk_meta"])
            from candidates import record_desk_turn

            record_desk_turn(conversation_id, turn_index, message, turn)
            on_event(
                {
                    "type": "final",
                    "conversation_id": conversation_id,
                    "turn_index": turn_index,
                    "answer": parsed.get("answer") or "",
                    "clarifying_question": parsed.get("clarifying_question") or "",
                    "abstain": bool(parsed.get("abstain")),
                    "reason": parsed.get("reason") or "",
                    "citations": citations,
                    "handoff_written": bool(turn.get("handoff_written")),
                    "handoff_summary": turn.get("handoff_summary") or "",
                    "tool_calls": turn.get("tool_calls") or [],
                    "cap_exceeded": bool(turn.get("cap_exceeded")),
                    "unknown_tool": turn.get("unknown_tool"),
                    "parse_error": turn.get("parse_error"),
                    "usage": turn.get("usage") or {},
                }
            )
        except Exception as exc:
            on_event({"type": "error", "error": str(exc), "conversation_id": conversation_id})
        finally:
            on_event(None)

    threading.Thread(target=work, daemon=True).start()

    async def events():
        while True:
            item = await queue.get()
            if item is None:
                break
            yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")


@app.post("/api/sessions/attach")
async def attach_sessions(request: Request):
    """Give a tab's conversation back to the in-memory session if the server lost it."""
    body = await request.json()
    items = body.get("sessions") or []
    if not isinstance(items, list):
        return JSONResponse({"error": "sessions is required"}, status_code=400)
    attached = []
    with session_lock:
        for item in items[:40]:
            if not isinstance(item, dict):
                continue
            conversation_id = str(item.get("id") or "")
            if not conversation_id or len(conversation_id) > 80:
                continue
            turns = item.get("turns") if isinstance(item.get("turns"), list) else []
            session = sessions.setdefault(
                conversation_id,
                {"messages": [], "chunks": {}, "chunk_meta": {}, "turns": []},
            )
            if session["messages"]:
                attached.append({"id": conversation_id, "turns": len(session["turns"])})
                continue
            seeded = _seed_messages(turns)
            if not seeded:
                continue
            session["messages"] = seeded
            session["turns"] = [
                {"question": message["content"], "answer": _shown_seed(reply)}
                for message, reply in zip(seeded[0::2], seeded[1::2])
            ]
            title = str(item.get("title") or "").strip()
            if title:
                session["title"] = title[:80]
            attached.append({"id": conversation_id, "turns": len(session["turns"])})
    return {"attached": attached}


def _seed_messages(turns: list) -> list[dict]:
    messages = []
    for turn in turns[:24]:
        if not isinstance(turn, dict):
            continue
        question = str(turn.get("question") or "").strip()[:2000]
        if not question:
            continue
        cites = []
        for cite in (turn.get("citations") or [])[:8]:
            if not isinstance(cite, dict):
                continue
            cites.append({
                "chunk_id": str(cite.get("chunk_id") or "")[:80],
                "quote": str(cite.get("quote") or "")[:500],
            })
        reply = {
            "answer": str(turn.get("answer") or "")[:8000],
            "clarifying_question": str(turn.get("clarifying_question") or "")[:2000],
            "citations": cites,
            "abstain": bool(turn.get("abstain")),
            "reason": str(turn.get("reason") or "")[:2000],
        }
        if not reply["answer"] and not reply["clarifying_question"]:
            continue
        messages.append({"role": "user", "content": question})
        messages.append({"role": "assistant", "content": json.dumps(reply, ensure_ascii=False)})
    return messages


def _shown_seed(message: dict) -> str:
    try:
        parsed = json.loads(message.get("content") or "{}")
    except json.JSONDecodeError:
        return ""
    if parsed.get("clarifying_question") and not parsed.get("answer"):
        return parsed["clarifying_question"]
    return parsed.get("answer") or parsed.get("reason") or ""


@app.post("/api/flag")
async def flag(request: Request):
    body = await request.json()
    conversation_id = str(body.get("conversation_id") or "")
    try:
        turn_index = int(body.get("turn_index"))
    except (TypeError, ValueError):
        return JSONResponse({"error": "turn_index is required"}, status_code=400)
    with session_lock:
        session = sessions.get(conversation_id)
        turns = list(session["turns"]) if session else []
    if turn_index < 0 or turn_index >= len(turns):
        return JSONResponse({"error": "Flag the answer from this page's conversation."}, status_code=400)
    facts = body.get("required_facts") or []
    if isinstance(facts, str):
        facts = [line.strip() for line in facts.splitlines() if line.strip()]
    kind = body.get("kind") or "in_scope"
    try:
        case = append_flagged_case(
            {
                "kind": kind,
                "question": turns[turn_index]["question"],
                "bad_answer": turns[turn_index]["answer"],
                "correct_answer": str(body.get("correct_answer") or ""),
                "required_facts": facts,
            },
            public_demo=PUBLIC_DEMO,
        )
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    from candidates import mark_visitor_flag

    mark_visitor_flag(conversation_id, turn_index)
    return {"case": case}


@app.get("/api/bulk")
def bulk_runs():
    groups = []
    for group in BULK_RUNS:
        stamps = []
        for name in group["files"]:
            payload = json.loads((RESULTS / name).read_text())
            stamps.append(
                {
                    "run_at": payload.get("run_at"),
                    "passed": payload.get("passed"),
                    "total": payload.get("total"),
                    "cases": [
                        {
                            "id": item["case"]["id"],
                            "kind": item["case"]["kind"],
                            "question": item["case"]["question"],
                            "passed": item["passed"],
                            "reasons": item.get("reasons") or [],
                        }
                        for item in payload.get("cases", [])
                    ],
                }
            )
        groups.append(
            {
                "id": group["id"],
                "title": group["title"],
                "score": group["score"],
                "note": group["note"],
                "stamps": stamps,
            }
        )
    return {"runs": groups}


@app.get("/api/review")
def review_list():
    return review_summary()


@app.post("/api/review")
async def review_add(request: Request):
    body = await request.json()
    try:
        item = add_complaint(str(body.get("question") or ""), str(body.get("answer") or ""))
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return {"item": item}


@app.post("/api/review/label")
async def review_label(request: Request):
    body = await request.json()
    try:
        item = set_label(str(body.get("id") or ""), str(body.get("label") or ""))
    except KeyError:
        return JSONResponse({"error": "That complaint is not on the list."}, status_code=404)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return {"item": item, "summary": review_summary()}


def _rate_limit(request: Request):
    ip = request.client.host if request.client else "local"
    window = 3600 if PUBLIC_DEMO else 600
    limit = 12 if PUBLIC_DEMO else 40
    now = time.time()
    recent = [stamp for stamp in hits.get(ip, []) if now - stamp < window]
    if len(recent) >= limit:
        return JSONResponse({"error": "Too many questions from this network. Try again later."}, status_code=429)
    recent.append(now)
    hits[ip] = recent
    return None


if __name__ == "__main__":
    import uvicorn

    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(app, host=host, port=port)
