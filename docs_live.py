"""Live read of docs.kernel.ai.

Pages are fetched from the published markdown when a search needs them.
A short cache avoids downloading the site on every tool call. The cache
is not the corpus: each chunk carries the URL and the time it was fetched.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:
    pass

HOST = "docs.kernel.ai"
USER_AGENT = "DocsDesk/0.1 (portfolio; live read of docs.kernel.ai)"
MIN_CHUNK = 80
MAX_CHUNK = 1600
LONG_FENCE = 1500


def load_config() -> dict:
    return json.loads((ROOT / "config.json").read_text())


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _norm_ws(text: str) -> str:
    return " ".join(text.split())


def quote_in_text(quote: str, text: str) -> bool:
    quote_n = _norm_ws(quote)
    if len(quote_n) < 20:
        return False
    return quote_n in _norm_ws(text)


@dataclass
class Page:
    url: str
    title: str
    text: str
    fetched_at: str


@dataclass
class Chunk:
    chunk_id: str
    url: str
    title: str
    heading: str
    text: str
    fetched_at: str

    def as_dict(self) -> dict:
        return {
            "chunk_id": self.chunk_id,
            "url": self.url,
            "title": self.title,
            "heading": self.heading,
            "text": self.text,
            "fetched_at": self.fetched_at,
        }


def parse_index(body: str) -> list[dict]:
    entries = []
    pattern = re.compile(r"^- \[(.+?)\]\((https://docs\.kernel\.ai/[^)\s]+)\)(?::\s*(.*))?$")
    for line in body.splitlines():
        match = pattern.match(line.strip())
        if not match:
            continue
        url = match.group(2).split("#")[0]
        if not url.endswith(".md"):
            continue
        entries.append(
            {
                "title": match.group(1).strip(),
                "url": url,
                "description": (match.group(3) or "").strip(),
            }
        )
    return entries


def canonical_doc_url(path_or_url: str, index_urls: set[str]) -> str | None:
    raw = (path_or_url or "").strip()
    if not raw:
        return None
    if raw.startswith("http://") or raw.startswith("https://"):
        parsed = urllib.parse.urlparse(raw)
        if parsed.netloc != HOST or parsed.scheme != "https":
            return None
        url = f"https://{HOST}{parsed.path}"
    else:
        path = raw if raw.startswith("/") else f"/{raw}"
        path = path.split("?")[0].split("#")[0]
        if not path.endswith(".md"):
            path = path.rstrip("/") + ".md"
        url = f"https://{HOST}{path}"
    if url not in index_urls:
        return None
    return url


def _strip_noise(text: str) -> str:
    def repl(match: re.Match) -> str:
        if len(match.group(0)) > LONG_FENCE:
            return "\n[long code block omitted]\n"
        return match.group(0)

    text = re.sub(r"```.*?```", repl, text, flags=re.S)
    text = re.sub(r"<[^>]+>", "", text)
    # Bold markers are not part of the sentence. The model quotes the words.
    text = re.sub(r"\*\*|__", "", text)
    text = _flatten_tables(text)
    return text


def _table_row(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("|") and stripped.count("|") >= 2


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _separator_row(cells: list[str]) -> bool:
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in cells)


def _flatten_tables(text: str) -> str:
    """One table row becomes one sentence, so a quote can cite a row without joining the table."""
    lines = text.split("\n")
    out: list[str] = []
    index = 0
    while index < len(lines):
        if not _table_row(lines[index]):
            out.append(lines[index])
            index += 1
            continue
        block = []
        while index < len(lines) and _table_row(lines[index]):
            block.append(lines[index])
            index += 1
        rows = [_cells(line) for line in block]
        header: list[str] = []
        body = rows
        if len(rows) >= 2 and _separator_row(rows[1]):
            header = rows[0]
            body = rows[2:]
        for row in body:
            if header and len(header) == len(row):
                pairs = [f"{name}: {value}" for name, value in zip(header, row) if name and value]
                if pairs:
                    sentence = "; ".join(pairs)
                    if sentence[-1] not in ".!?":
                        sentence += "."
                    out.append(sentence)
            elif any(row):
                out.append(" | ".join(cell for cell in row if cell))
    return "\n".join(out)


def chunk_page(page: Page) -> list[Chunk]:
    text = _strip_noise(page.text)
    parts = re.split(r"(?m)^(#{1,3} .+)$", text)
    sections: list[tuple[str, str]] = []
    if parts[0].strip():
        sections.append((page.title, parts[0]))
    for i in range(1, len(parts), 2):
        heading = parts[i].lstrip("#").strip()
        body = parts[i + 1] if i + 1 < len(parts) else ""
        sections.append((heading, body))

    chunks: list[Chunk] = []
    for heading, body in sections:
        windows = _windows(body.strip())
        for window in windows:
            if len(window) < MIN_CHUNK:
                continue
            digest = hashlib.sha256(f"{page.url}\n{heading}\n{window[:80]}".encode()).hexdigest()[:12]
            chunks.append(
                Chunk(
                    chunk_id=digest,
                    url=page.url,
                    title=page.title,
                    heading=heading,
                    text=window,
                    fetched_at=page.fetched_at,
                )
            )
    return chunks


def _windows(body: str) -> list[str]:
    if len(body) <= MAX_CHUNK:
        return [body] if body else []
    windows = []
    start = 0
    while start < len(body):
        windows.append(body[start : start + MAX_CHUNK])
        if start + MAX_CHUNK >= len(body):
            break
        start += MAX_CHUNK - 200
    return windows


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def bm25_top(query: str, chunks: list[Chunk], k: int) -> list[Chunk]:
    query_terms = _tokens(query)
    if not query_terms or not chunks:
        return []
    docs = [_tokens(f"{c.title} {c.heading} {c.text}") for c in chunks]
    avg = sum(len(doc) for doc in docs) / len(docs)
    df: dict[str, int] = {}
    for doc in docs:
        for term in set(doc):
            df[term] = df.get(term, 0) + 1
    n = len(docs)
    k1 = 1.5
    b = 0.75
    scored: list[tuple[float, int]] = []
    for i, doc in enumerate(docs):
        counts: dict[str, int] = {}
        for term in doc:
            counts[term] = counts.get(term, 0) + 1
        score = 0.0
        for term in query_terms:
            if term not in counts:
                continue
            idf = max(0.0, math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5)))
            freq = counts[term]
            denom = freq + k1 * (1 - b + b * len(doc) / avg)
            score += idf * (freq * (k1 + 1)) / denom
        if score > 0 and "/concepts/" in chunks[i].url:
            score *= 1.15
        if score > 0:
            scored.append((score, i))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [chunks[i] for _, i in scored[:k]]


class _SameHostRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urllib.parse.urlparse(newurl)
        if parsed.netloc != HOST or parsed.scheme != "https":
            raise PermissionError(f"refused redirect to {newurl}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class DocsClient:
    def __init__(self, ttl_seconds: int | None = None, index_url: str | None = None):
        config = load_config()
        self.ttl = ttl_seconds if ttl_seconds is not None else int(config["cache_ttl_seconds"])
        self.index_url = index_url or config["docs_index_url"]
        self.search_k = int(config["search_k"])
        self._lock = threading.Lock()
        self._index: list[dict] | None = None
        self._index_at = 0.0
        self._pages: dict[str, Page] = {}
        self._inflight: dict[str, tuple[threading.Event, bool]] = {}
        self._cache_dir = ROOT / ".cache" / "pages"
        import certifi

        context = ssl.create_default_context(cafile=certifi.where())
        self._opener = urllib.request.build_opener(_SameHostRedirect, urllib.request.HTTPSHandler(context=context))

    def index_urls(self) -> set[str]:
        return {entry["url"] for entry in self.index()}

    def index(self) -> list[dict]:
        with self._lock:
            if self._index is not None and time.time() - self._index_at < self.ttl:
                return self._index
        body = self._http_get(self.index_url)
        entries = parse_index(body)
        if not entries:
            raise RuntimeError("docs index was empty")
        with self._lock:
            self._index = entries
            self._index_at = time.time()
        return entries

    def warm(self) -> int:
        return len(self._pages_for(self.index()))

    def search(self, query: str, k: int | None = None) -> dict:
        pages = self._pages_for(self.index())
        chunks: list[Chunk] = []
        for page in pages:
            chunks.extend(chunk_page(page))
        top = bm25_top(query, chunks, self.search_k if k is None else k)
        return {
            "retrieved_at": now_iso(),
            "pages_fetched": len(pages),
            "chunks": [chunk.as_dict() for chunk in top],
        }

    def get_page(self, path: str, query: str = "") -> dict:
        url = canonical_doc_url(path, self.index_urls())
        if url is None:
            return {
                "error": "That path is not in the docs.kernel.ai index. Use a path returned by search_docs.",
                "chunks": [],
            }
        page = self._load_page(url, self._title_for(url))
        chunks = chunk_page(page)
        if query.strip():
            chunks = bm25_top(query, chunks, self.search_k) or chunks[: self.search_k]
        else:
            chunks = chunks[: self.search_k]
        return {"retrieved_at": page.fetched_at, "url": url, "chunks": [c.as_dict() for c in chunks]}

    def page_text(self, url: str) -> str:
        url = canonical_doc_url(url, self.index_urls())
        if url is None:
            raise ValueError("url is not in the docs index")
        return self._load_page(url, self._title_for(url)).text

    def corpus_text(self) -> str:
        pages = self._pages_for(self.index())
        return "\n".join(page.text for page in pages)

    def _title_for(self, url: str) -> str:
        for entry in self.index():
            if entry["url"] == url:
                return entry["title"]
        return url

    def _pages_for(self, entries: list[dict]) -> list[Page]:
        missing = []
        ready = []
        for entry in entries:
            cached = self._fresh(entry["url"])
            if cached is None:
                missing.append(entry)
            else:
                ready.append(cached)
        if not missing:
            return ready
        found: list[Page] = []
        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = [pool.submit(self._load_page, entry["url"], entry["title"]) for entry in missing]
            for future in as_completed(futures):
                found.append(future.result())
        return ready + found

    def _fresh(self, url: str) -> Page | None:
        with self._lock:
            page = self._pages.get(url)
        if page and time.time() - _epoch(page.fetched_at) < self.ttl:
            return page
        disk = self._read_disk(url)
        if disk and time.time() - _epoch(disk.fetched_at) < self.ttl:
            with self._lock:
                self._pages[url] = disk
            return disk
        return None

    def _load_page(self, url: str, title: str) -> Page:
        cached = self._fresh(url)
        if cached:
            return cached
        with self._lock:
            cached = self._pages.get(url)
            if cached and time.time() - _epoch(cached.fetched_at) < self.ttl:
                return cached
            inflight = self._inflight.get(url)
            if inflight is None:
                event = threading.Event()
                self._inflight[url] = (event, True)
                owner = True
            else:
                event = inflight[0]
                owner = False
        if not owner:
            event.wait(90)
            cached = self._fresh(url)
            if cached:
                return cached
        try:
            text = self._http_get(url)
            page = Page(url=url, title=title, text=text, fetched_at=now_iso())
            with self._lock:
                self._pages[url] = page
            self._write_disk(page)
            return page
        finally:
            if owner:
                event.set()
                with self._lock:
                    self._inflight.pop(url, None)

    def _http_get(self, url: str) -> str:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "https" or parsed.netloc != HOST:
            raise PermissionError(f"refused URL {url}")
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/markdown, text/plain"})
        try:
            with self._opener.open(request, timeout=30) as response:
                final = response.geturl()
                if urllib.parse.urlparse(final).netloc != HOST:
                    raise PermissionError(f"refused final URL {final}")
                return response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"{url} returned {exc.code}") from exc

    def _disk_path(self, url: str) -> Path:
        digest = hashlib.sha256(url.encode()).hexdigest()
        return self._cache_dir / f"{digest}.json"

    def _read_disk(self, url: str) -> Page | None:
        path = self._disk_path(url)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text())
        except json.JSONDecodeError:
            return None
        if payload.get("url") != url:
            return None
        return Page(url=url, title=payload.get("title") or url, text=payload.get("text") or "", fetched_at=payload["fetched_at"])

    def _write_disk(self, page: Page) -> None:
        path = self._disk_path(page.url)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {"url": page.url, "title": page.title, "text": page.text, "fetched_at": page.fetched_at},
                ensure_ascii=False,
            )
        )


def _epoch(iso: str) -> float:
    return datetime.fromisoformat(iso).timestamp()
