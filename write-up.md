# A docs agent, a complaint, and a recorded check

This is a support desk over Kernel's public docs, built as a portfolio piece. It is not Kernel's product and is not affiliated with Kernel. No support team has used it. The questions I checked it on were written from the docs, and it does not read Kernel account data.

A customer asks a question. The agent looks the answer up itself and cites the passage, or says the docs don't cover it. If a reply did not help, a person labels it. Separately, the same agent was checked on a fixed set of questions, and those checks are recorded and graded in code. Labelling a complaint does not create a test and does not change the score.

The same text is the About page at `/about`.

## Ask the docs

This screen is for a customer. They don't know the right answer and they don't type one.

The agent reads the live docs at docs.kernel.ai and chooses its own lookups. While it works, a line names the section it is in, such as "Looking through KERN ID", and the line closes when the answer is ready. The answer sits with the passages it used. Each citation is the section, a link to the live page and the quoted words. If those words are not in the passage the model was given, the citation is marked. A follow-up question has its own citations.

Under each reply the customer can press **This helped** or **This didn't help**. Helped stays on the page. Didn't help sends the question and the answer to Review.

The conversation lives in this browser tab. A refresh keeps it, and closing the tab clears it. The server may keep a log of questions and tool calls for debugging, so don't type anything private. Four example conversations are already on the page: an ordinary answer, an incomplete answer, one that should have refused, and one the docs don't cover.

## Review

A complaint arrives only when a customer presses **This didn't help**. Nothing is labelled automatically.

The top line shows how many are waiting and how many are labelled. Under it are four counts: wrong answer, should have refused, incomplete, and docs don't cover this. The six labelled items on the demo are examples I filed to show the screen. They are not customer reports.

Each waiting item shows the question, the answer and four buttons:

- **Wrong answer.** Goes to the person who looks after the agent.
- **Incomplete.** Goes to the person who looks after the agent. The reply is on the right topic and still leaves out part of what was asked.
- **Should have refused.** Goes to the person who looks after the agent.
- **Docs don't cover this.** Goes to the person who looks after the docs.

One click files it. The label doesn't ask for the right answer, doesn't add a test case and doesn't run any check again. How a team turns labelled complaints into tests is their decision, and this demo stops at routing.

## Bulk run

This screen is the recorded check, not the complaint queue. These are runs I did by hand while building. They are not an automatic rerun after every edit.

- First run: 14 of 26, before the refusal and search fixes. `evals/results/2026-10-08T093457Z.json`.
- After the fixes: 19 to 20 of 26. Three runs scored 19, 20 and 19 of 26.
- Held out: 2 of 6, on six questions the agent had never been run against. This is the number to trust, because the agent was tuned against the other 26. `evals/results/heldout-2026-10-08T100916Z.json`.

Each run is split into answerable, ambiguous and out-of-scope questions. Every row is Pass or Fail, and a failure shows its reason in one line. The grader is code that checks for required phrases, correct citations and refusals. No second model grades the first.

The questions shown on screen belong to the run that is selected. They are not a new run.

## What the check caught

The first catch was a citation, not a wrong fact. Asked what identity mode does when a record is ambiguous, the agent named the right idea and attached a quote that stitched several lines of the page into one passage. The words were on the page, but they were not one passage of the text the model was given. The check rejected the quote, and the rule was not loosened.

## What still fails

- Three questions failed on every run: identity mode, S3 versus the API, and the compensation question, where the agent asks a clarifying question instead of refusing.
- The check looks for exact phrases, so a correct answer worded differently can fail. Two of the six held-out answers were right in substance and failed for that reason.
- The 26 questions and the agent were tuned against each other, then frozen. No required fact was rewritten after seeing results. Identity mode was added by hand before complaints and tests were separated. New complaints are not added to the 26.
