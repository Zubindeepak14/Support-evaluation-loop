"""Confirm every required fact is on the live source page, and that out-of-scope markers are absent.

No model is called. Run this before the suite, and again whenever the docs may have moved.
"""

from __future__ import annotations

import sys

from cases_store import load_cases
from docs_live import DocsClient


def main() -> int:
    docs = DocsClient()
    cases = load_cases()
    failed = 0
    for case in cases:
        if case.get("flagged"):
            continue
        source = case.get("source") or []
        sources = [source] if isinstance(source, str) else list(source)
        if sources:
            text = "\n".join(docs.page_text(url) for url in sources).lower()
            missing = [fact for fact in case.get("required_facts", []) if fact.lower() not in text]
            if missing:
                failed += 1
                print(f"FAIL  {case['id']}: not on {' '.join(sources)}: {missing}")
            else:
                print(f"ok    {case['id']}")
        else:
            print(f"ok    {case['id']} (no source page)")

    corpus = docs.corpus_text().lower()
    for case in cases:
        for marker in case.get("confirmed_absent") or []:
            if marker.lower() in corpus:
                failed += 1
                print(f"FAIL  {case['id']}: docs now contain {marker!r}. Drop or rewrite the case.")
            else:
                print(f"ok    {case['id']} absent {marker!r}")

    if failed:
        print(f"\n{failed} fact check(s) failed")
        return 1
    print(f"\n{len(cases)} cases agree with the live docs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
