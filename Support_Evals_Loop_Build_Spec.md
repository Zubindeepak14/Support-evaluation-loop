# Support-to-evals loop

A portfolio build for the Kernel AI Ops Engineer role. It is not Kernel's product. No support team has used it. The questions were written from the docs.

## 1. What it is

A conversational support agent over Kernel's public docs. Kernel assigns a persistent KERN ID to a real-world business. A developer or operator asks about that documentation. The agent decides its own next step: search the docs, open a page, ask one clarifying question, write a handoff, or answer.

It answers only from the pages it fetched on that turn. Every factual claim carries a quote. The quote has to be one contiguous passage of the chunk the model was given. When the docs do not contain the answer, it abstains and writes a handoff. A wrong answer, or an answer that should have been a refusal, can be saved from the desk as a permanent test case. The suite replays the cases and grades them in code. No second model grades the first.

## 2. Corpus

Live public docs at https://docs.kernel.ai/llms.txt. Markdown pages are fetched by appending `.md` to a URL that appears in that index. Pages are not vendored. A page is cached for 15 minutes in `.cache/`, which is not committed. Each citation stores the URL, the heading, and the fetch time.

Only `docs.kernel.ai` URLs from the index are allowed. Other hosts and paths outside the index are refused.

## 3. Pass rules

These are what `checks.py` applies. They are string and structure checks.

1. **Out of scope.** The reply abstains and a handoff was written. An answer fails as a confident answer. A clarifying question with no answer fails as asked instead of refusing.
2. **Answerable.** The reply does not abstain. Every required fact appears in the answer, case-insensitive. At least one citation is present. Every quote is a contiguous stretch of a chunk retrieved on that case, at least 20 characters after whitespace is collapsed. A docs tool (`search_docs` or `get_page`) was called. If the case sets `expect_tool`, that tool was called.
3. **Ambiguous.** The first turn asks a clarifying question and does not already contain every required fact. After the scripted follow-up, the final turn is graded as answerable. On `vague-parent`, the clarifying question must not ask for a KERN ID.
4. **Tools are read-only.** Allowed tools are `search_docs`, `get_page`, and `write_handoff`. Anything else fails the case.
5. **Step cap.** More than 6 tool calls in a turn fails the case.
6. **Shape.** The final reply is one JSON object: `answer`, `clarifying_question`, `citations` (`chunk_id` and `quote`), `abstain` (boolean), `reason`. A reply that is not that object fails. The runner sends it back once; a second failure is still a failure.
7. **Report the run as it is.** A failed case stays a failed case.

A quote passes when it is a contiguous stretch of the stored chunk, at least 20 characters after whitespace is collapsed. That includes a quote which spans table rows, when those rows are already contiguous in the chunk the model was given. A quote fails when the joined text is not in that chunk in that order. The instruction to keep a quote under 30 words, and not to join bullets, is in the prompt and the retry. The checker does not count words.

A citation is checked against the chunk text stored from that call, not against a later fetch of the page.

## 4. The question set

`evals/cases.json` holds 26 cases: 15 answerable, 4 ambiguous, 7 out of scope. One answerable case, `flagged-identity-mode`, was added from the desk. The citation on that question had stitched the Bias modes bullets into one quote. The facts were right. The quote check caught it.

`vague-parent` opens with "the parent on this account looks wrong". The first turn must ask which company the account is and which parent is meant: immediate, top, or top operating. It must not ask for a KERN ID, because the docs cannot look an account up. The scripted follow-up names the YouTube account and asks for those three parents. The answer must contain Google LLC and Alphabet Inc.

The prompt also says that when the docs describe how to report a wrong parent, that procedure is an answer, not a refusal. That is not a separate scored case.

Out-of-scope questions cover pricing, a refund, a private account's KERN ID, sanctions, staff holiday, compensation after an outage, and a request to change a KERN ID. Each one was checked so the docs do not contain the marker used in the case.

`check_facts.py` confirms the required facts are still on the live source pages, and that the out-of-scope markers are still absent.

No required fact was rewritten after `evals/results/2026-10-08T093457Z.json`. `s3-credentials` was the candidate: the answer said "not persistent keys" and cited "No AWS access keys or other long-lived credentials are shared with Kernel." The phrase is the docs' own words, so the fact stays. The miss is that the answer did not carry it.

## 5. What is built

1. **Live read.** `docs_live.py` loads the index, fetches allow-listed pages, strips long code fences, HTML, and bold markers, and turns each markdown table row into one sentence so a row can be quoted. Chunks are split by heading. Search is BM25, top 5.
2. **Agent.** `agent.py` calls Claude Haiku 4.5 (`config.json`) with tool use. The model chooses the next step. The final reply is the JSON object above. A clarifying question goes in `clarifying_question` with `answer` empty.
3. **Tools.** `search_docs(query)`, `get_page(path, query)`, `write_handoff(summary)`. No keys. No writes to Kernel.
4. **Retries, once each.** If a quote is not one passage of the cited chunk, the reply is sent back. When that quote is a passage of a different retrieved chunk, the retry names that chunk. If the reply is not JSON, it is sent back once and the second call is constrained to the reply schema. An abstain with fewer than two doc lookups is sent back to search. An abstain with no handoff is sent back to call `write_handoff`. An answer after a single lookup is sent back to search again, preferring the concept page. A clarifying question is not sent back, because an ambiguous case is supposed to ask before it searches. Asking is limited in the prompt: only when the user has not given a fact the answer depends on, and never as a way to turn a price, a refund, a private record, or a write into a docs question. Search also ranks a `/concepts/` page slightly above an equal match on another page. None of these retries change the pass rules.
5. **Two screens.** `app.py` serves Ask the docs at `/` and Review at `/review` (also `/suite`). The customer screen shows the steps, the answer, and each citation with whether the quote was found. Under a reply the buttons are **This helped** and **This didn't help**. This didn't help stores the question and the answer on the waiting list. It does not append a case. On Review, one click labels it **Wrong answer**, **Should have refused**, or **Docs don't cover this**. A label does not create a test and does not rerun the suite. Labelled complaints sit in buckets on the right of Review. Bulk run is a separate page at `/bulk`: first run 14 of 26, after fixes 19 to 20 of 26, held out 2 of 6, each in lanes for answerable, ambiguous, and out of scope. Labelling does not change those numbers.
6. **Suite runner.** `run_suite.py` plays each case, including the scripted follow-up on ambiguous ones, grades in code, and writes `evals/results/<timestamp>.json`. `--replay` re-grades a saved file without calling the model.
7. **Trace.** `logs/trace.jsonl` records each model call and each tool call outside the agent: time, conversation id, tool, arguments, size, latency, and an estimated cost.

## 6. What this build does not include

A judge model. A generated batch of questions. A behaviour dashboard. Turning a review label into a new test. Shadow mode on real tickets. Docs drift across git history. A live check of a Kernel account. Those are later work. The recorded exam remains the check. The demo stops at routing.

## 7. Write-up

- **Context.** Support answers the same technical questions, and the docs hold most of the answers.
- **The thinking.** A wrong answer that sounds right is worse than no answer, so abstention is a result and the false-answer budget is zero. The agent chooses its own steps. The tools are read-only. The checks run outside the agent.
- **What I built.** Ask the docs, the citation check, Review (a waiting list and a label, which stops there), and the recorded exam, as above.
- **What I measured.** The agent cites a passage from the chunk it was given. On the identity-mode question that check caught a quote that stitched the Bias modes bullets into one passage. The facts in that answer were right. In the baseline run the citation retry fired on 7 cases and fixed 5 of them. The baseline file is `evals/results/2026-10-08T093457Z.json`, copied at `evals/baseline/2026-10-08T093457Z.json`: 14 of 26. The twelve failures were bad refusals, incomplete answers, and two real citation errors. After the refusal and search fixes, three runs scored 19, 20, and 19 of 26. The range is 19 to 20. That range is not a held-out number. The agent and these 26 cases were tuned against each other for several rounds, and then frozen. Identity mode stayed a miss: the answer was substantively right, including the run that called the mode a tiebreaker, and the check is strict on the wording "breaks a tie". The case was not edited. `oos-compensation` asked about SLA terms, with no search, on all three runs. That is a known limit. The agent reads a compensation question as "maybe the docs cover SLA terms," and a clarifying question is not sent back. Six fresh cases, on pages the 26 do not use, scored 2 of 6 on one run (`evals/results/heldout-2026-10-08T100916Z.json`). Those cases were not edited after the run.
- **The limit.** The questions were written from the docs, not taken from tickets. No support team has used it.

## 8. CV line

Support-to-evals loop: a conversational agent over Kernel's public docs that chooses its own lookups, cites a passage, and abstains when the docs are silent. A customer can say a reply didn't help. That waits for a label (wrong answer, should have refused, or a docs gap) and stops there. The citation check caught a quote that stitched several bullets into one passage. Baseline 14/26. After the fixes, 19 to 20 of 26 on the tuned set. Held out, 2/6 (write-up, code)
