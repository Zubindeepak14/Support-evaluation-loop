import json
import unittest

from agent import parse_reply
from checks import grade
from docs_live import canonical_doc_url, chunk_page, parse_index, quote_in_text, Page


INDEX = """
# Kernel Docs

- [KERN ID](https://docs.kernel.ai/concepts/kern-id.md): A persistent id.
- [Inbound](https://docs.kernel.ai/developer/inbound-api.md)
- [Skip](https://example.com/nope.md): not kernel
"""

PAGE = """# Parent relationships

Immediate parent, top parent, top operating parent.

For YouTube, the immediate parent and the top operating parent both resolve to Google LLC, while the top parent resolves to Alphabet Inc. at the top of the tree.
"""


def turn(answer="", question="", abstain=False, citations=None, tools=None, chunks=None, handoff=False, **flags):
    return {
        "parsed": {
            "answer": answer,
            "clarifying_question": question,
            "citations": citations or [],
            "abstain": abstain,
            "reason": "",
        },
        "tool_calls": [{"name": name} for name in (["search_docs"] if tools is None else tools)],
        "chunks": chunks or {},
        "handoff_written": handoff,
        "cap_exceeded": flags.get("cap", False),
        "unknown_tool": flags.get("unknown"),
        "parse_error": flags.get("parse_error"),
    }


QUOTE = "the immediate parent and the top operating parent both resolve to Google LLC"
CHUNK = "parent-1"


class RulesTest(unittest.TestCase):
    def test_index_ignores_other_hosts(self):
        entries = parse_index(INDEX)
        self.assertEqual([item["url"] for item in entries], [
            "https://docs.kernel.ai/concepts/kern-id.md",
            "https://docs.kernel.ai/developer/inbound-api.md",
        ])

    def test_allow_list(self):
        urls = {item["url"] for item in parse_index(INDEX)}
        self.assertEqual(
            canonical_doc_url("/concepts/kern-id", urls),
            "https://docs.kernel.ai/concepts/kern-id.md",
        )
        self.assertIsNone(canonical_doc_url("https://evil.example/concepts/kern-id.md", urls))
        self.assertIsNone(canonical_doc_url("https://docs.kernel.ai.evil.com/concepts/kern-id.md", urls))
        self.assertIsNone(canonical_doc_url("/developer/not-a-page", urls))

    def test_quote_must_be_verbatim_and_long_enough(self):
        self.assertTrue(quote_in_text(QUOTE, PAGE))
        self.assertTrue(quote_in_text("immediate\nparent and the top operating parent", PAGE.replace("immediate parent", "immediate\nparent")))
        self.assertFalse(quote_in_text("Google LLC", PAGE))
        self.assertFalse(quote_in_text("the immediate parent is Microsoft Corporation", PAGE))

    def test_chunks_keep_the_passage(self):
        page = Page(url="https://docs.kernel.ai/data/hierarchies/parent-relationships.md", title="Parent relationships", text=PAGE, fetched_at="2026-10-07T00:00:00+00:00")
        chunks = chunk_page(page)
        self.assertTrue(any(QUOTE in chunk.text for chunk in chunks))

    def test_in_scope_pass_and_failures(self):
        case = {"kind": "in_scope", "required_facts": ["Google LLC", "Alphabet Inc."], "expect_tool": "search_docs"}
        good = turn(
            answer="The immediate parent is Google LLC and the top parent is Alphabet Inc.",
            citations=[{"chunk_id": CHUNK, "quote": QUOTE}],
            chunks={CHUNK: PAGE},
        )
        self.assertTrue(grade(case, [good])["passed"])

        missing = turn(answer="See the docs.", citations=[{"chunk_id": CHUNK, "quote": QUOTE}], chunks={CHUNK: PAGE})
        self.assertIn("missing facts", " ".join(grade(case, [missing])["reasons"]))

        invented = turn(
            answer="The immediate parent is Google LLC and the top parent is Alphabet Inc.",
            citations=[{"chunk_id": CHUNK, "quote": "the top parent is Microsoft and this quote is long enough"}],
            chunks={CHUNK: PAGE},
        )
        self.assertTrue(any("quote not in chunk" in reason for reason in grade(case, [invented])["reasons"]))

        no_tool = turn(
            answer="The immediate parent is Google LLC and the top parent is Alphabet Inc.",
            citations=[{"chunk_id": CHUNK, "quote": QUOTE}],
            tools=[],
            chunks={CHUNK: PAGE},
        )
        self.assertTrue(any("no docs tool" in reason for reason in grade(case, [no_tool])["reasons"]))

    def test_out_of_scope_and_cap(self):
        case = {"kind": "out_of_scope"}
        self.assertTrue(grade(case, [turn(abstain=True, handoff=True, tools=["search_docs"])])["passed"])
        confident = grade(case, [turn(answer="It costs ten pounds.", abstain=False, handoff=True)])
        self.assertFalse(confident["passed"])
        self.assertIn("confident answer", " ".join(confident["reasons"]))
        asked = grade(case, [turn(question="Do you want the public docs or your contract?", answer="", abstain=False)])
        self.assertIn("asked instead of refusing", " ".join(asked["reasons"]))
        capped = grade(case, [turn(abstain=True, handoff=True, cap=True)])
        self.assertTrue(any("6 tool" in reason for reason in capped["reasons"]))

    def test_ambiguous_must_ask_first(self):
        case = {
            "kind": "ambiguous",
            "required_facts": ["Google LLC", "Alphabet Inc."],
        }
        asked = turn(question="Which account, and which parent field?", answer="")
        answered = turn(
            answer="The immediate parent is Google LLC and the top parent is Alphabet Inc.",
            citations=[{"chunk_id": CHUNK, "quote": QUOTE}],
            chunks={CHUNK: PAGE},
        )
        self.assertTrue(grade(case, [asked, answered])["passed"])
        jumped = grade(case, [answered])
        self.assertTrue(any("clarifying" in reason for reason in jumped["reasons"]))
        asked_for_id = turn(question="What is the KERN ID of the account you're concerned about?", answer="")
        banned = grade({**case, "clarify_must_not": ["KERN ID"]}, [asked_for_id, answered])
        self.assertTrue(any("KERN ID" in reason for reason in banned["reasons"]))

    def test_reply_parser(self):
        parsed, error = parse_reply(
            '```json\n{"answer": "ok", "clarifying_question": "", "citations": [], "abstain": false, "reason": ""}\n```'
        )
        self.assertIsNone(error)
        self.assertEqual(parsed["answer"], "ok")
        _, error = parse_reply("I think the parent is Google.")
        self.assertEqual(error, "no JSON object in the final reply")
        from agent import format_retry_message

        self.assertIn("clarifying_question", format_retry_message())
        _, error = parse_reply('{"answer": "ok", "abstain": "false", "citations": []}')
        self.assertIn("boolean", error)

    def test_spliced_bias_quote_is_not_one_passage(self):
        from agent import citation_problems, citation_retry_message

        passage = """
        Kernel treats this as a bias, not a hard rule.

        * **URL bias** (default) - lean on the website. Best when records came from web forms, enrichment, or email domains, where the domain is the reliable key, or when a previous vendor has been used that keys on domain.
        * **Name bias** - lean on the company name as the strongest statement of what the record was meant to represent. Best when reps typed account names by hand or when a previous vendor has been used that keys on company name.

        A bias only breaks a tie. When the address, legal name, LinkedIn, or contact domains clearly corroborate one entity, that evidence wins.
        """
        spliced = (
            "Kernel treats this as a bias, not a hard rule. "
            "URL bias (default) - lean on the website. Best when records came from web forms, enrichment, or email domains, where the domain is the reliable key, or when a previous vendor has been used that keys on domain. "
            "Name bias - lean on the company name as the strongest statement of what the record was meant to represent. "
            "Best when reps typed account names by hand or when a previous vendor has been used that keys on company name. "
            "A bias only breaks a tie."
        )
        parsed = {"citations": [{"chunk_id": "bias", "quote": spliced}]}
        problems = citation_problems(parsed, {"bias": passage})
        self.assertEqual(len(problems), 1)
        self.assertIn("contiguous", problems[0]["reason"])
        self.assertIn("under 30 words", citation_retry_message(problems))

        short = "A bias only breaks a tie. When the address, legal name, LinkedIn, or contact domains clearly corroborate one entity, that evidence wins."
        clean = {"citations": [{"chunk_id": "bias", "quote": short}]}
        self.assertEqual(citation_problems(clean, {"bias": passage}), [])

    def test_table_row_is_one_sentence(self):
        from docs_live import _flatten_tables

        table = """
        For YouTube:

        | Relationship | Entity |
        | --- | --- |
        | Immediate parent | Google LLC |
        | Top parent | Alphabet Inc. |
        """
        flat = _flatten_tables(table)
        row = "Relationship: Immediate parent; Entity: Google LLC."
        self.assertIn(row, flat)
        joined = "Immediate parent: Google LLC, Top parent: Alphabet Inc., Top operating parent: Google LLC"
        self.assertNotIn(joined, flat)
        from agent import citation_problems

        problems = citation_problems({"citations": [{"chunk_id": "parents", "quote": joined}]}, {"parents": flat})
        self.assertEqual(len(problems), 1)
        self.assertIn(row, problems[0].get("hint", ""))

    def test_wrong_chunk_id_names_the_chunk_that_has_the_quote(self):
        from agent import citation_problems, citation_retry_message

        quote = "No AWS access keys or other long-lived credentials are shared with Kernel."
        parsed = {"citations": [{"chunk_id": "trust", "quote": quote}]}
        chunks = {
            "trust": "Use the trust policy generated in Kernel.",
            "glance": "Cross-account IAM role assumption. " + quote,
        }
        problems = citation_problems(parsed, chunks)
        self.assertEqual(problems[0]["found_in"], "glance")
        self.assertIn("glance", citation_retry_message(problems))

    def test_policy_retry_order(self):
        from agent import policy_retry

        flags = dict(abstain_search_retried=False, handoff_retried=False, depth_retried=False, clarify_retried=False)
        abstain = {"answer": "The docs do not say.", "clarifying_question": "", "abstain": True}
        kind, _ = policy_retry(abstain, [], False, **flags)
        self.assertEqual(kind, "search")
        flags["abstain_search_retried"] = True
        kind, message = policy_retry(abstain, [{"name": "search_docs"}, {"name": "search_docs"}], False, **flags)
        self.assertEqual(kind, "handoff")
        self.assertIn("write_handoff", message)
        asked = {"answer": "", "clarifying_question": "Which company is this account for?", "abstain": False}
        self.assertIsNone(policy_retry(asked, [], False, **flags))
        answer = {"answer": "URL bias leans on the website.", "clarifying_question": "", "abstain": False}
        kind, message = policy_retry(answer, [{"name": "search_docs"}], False, **flags)
        self.assertEqual(kind, "depth")
        self.assertIn("concept page", message)
        self.assertIsNone(
            policy_retry(
                {"answer": "", "clarifying_question": "Which company?", "abstain": False},
                [],
                False,
                abstain_search_retried=False,
                handoff_retried=False,
                depth_retried=False,
                clarify_retried=True,
            )
        )

    def test_concept_page_ranks_above_an_equal_match(self):
        from docs_live import Chunk, bm25_top

        text = "identity mode tells Kernel which input to lean on when a record is ambiguous"
        setup = Chunk("setup", "https://docs.kernel.ai/data/setup.md", "Data setup", "Identity", text, "")
        concept = Chunk("concept", "https://docs.kernel.ai/concepts/entity-resolution.md", "Entity resolution", "Bias", text, "")
        top = bm25_top("identity mode ambiguous record", [setup, concept], 1)
        self.assertEqual(top[0].chunk_id, "concept")

    def test_cases_file_shape(self):
        from docs_live import ROOT

        cases = json.loads((ROOT / "evals" / "cases.json").read_text())
        self.assertEqual(len(cases), 26)
        kinds = [case["kind"] for case in cases]
        self.assertEqual(kinds.count("in_scope"), 15)
        self.assertEqual(kinds.count("ambiguous"), 4)
        self.assertEqual(kinds.count("out_of_scope"), 7)
        for case in cases:
            self.assertTrue(case["id"])
            self.assertTrue(case["question"])


if __name__ == "__main__":
    unittest.main()
