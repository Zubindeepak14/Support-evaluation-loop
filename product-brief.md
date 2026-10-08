# Product brief

A customer asks Kernel's public docs. If the reply did not help, it waits for a person to label it. Separately, the agent was checked on a fixed set of questions. Those checks are recorded. Labelling a complaint does not change them and does not create a new test.

Three screens. The same navigation is on each: Ask the docs, Review, Bulk run.

## 1. Ask the docs

Who it is for: a customer. They do not know the right answer. They do not label the reply, and they do not write what the next answer must contain.

### Sections

- Conversations. A list of this browser's chats, plus New chat. Opening a chat shows that conversation. A fresh visit with no chat shows an empty state.
- Empty state. Title: Ask the docs. Short line: ask a question about Kernel's docs; the agent looks it up and cites the passage, or says the docs don't cover it. Three example questions. Choosing one fills the box. It does not send.
- Conversation. Each customer message, then the reply to it.
- Lookup, on each reply that used the docs. While the reply is still coming, the line is "Looking through the docs", then the section it is in, such as "Looking through KERN ID". The lines name doc sections. They do not describe the agent's own steps. When the answer is ready, this closes. The closed line is "Looked through {section}" or "Looked through {section} and N other sections". It can be opened again. The opened list is one line per section, "Looking through {section}".
- Answer. The reply. If the docs do not cover it, the reply says so. If a quote is not actually in the section it cites, that quote is marked "Quote not in that section".
- Citations, belonging to that answer only. Each one is the section name, as a link to the live doc, and the quoted passage. A follow-up has its own citations. They are not added to a single list for the whole chat.
- Prompt. One box for the whole screen, under the conversation. Placeholder: Ask about a KERN ID, a parent, the API, or Salesforce. A short line, "Read more about the agent and the eval loop", with the word "here" as a link. Send.

### Actions

- New chat. Clears the current conversation on screen. Does not delete the old one from the list.
- Example question. Fills the prompt. Does not send.
- Send. Disabled until there is text that is not only spaces. Enter sends. Shift+Enter does not. While a reply is in progress, Send stays disabled.
- Open or close the lookup line on a finished reply.
- This helped. Stays on this screen. The reply shows "Glad it helped." Nothing is sent to Review. No test is created.
- This didn't help. The reply shows "Sent to review. It is waiting for a label." Review receives the question and the answer. No test is created. The 26 recorded questions are not changed.
- A section link in a citation opens that page of the docs.

## 2. Review

Who it is for: a person looking at complaints. A customer never sees this screen's actions.

A complaint arrives only from This didn't help. Nothing is labelled automatically.

### Sections

- Counter. "N waiting, M labelled." When some are labelled, the labelled part is split, for example "1 wrong answer, 1 should have refused, 1 docs gap."
- A line under the counter: a label sends the complaint to the person who fixes that kind of problem. It does not create a test.
- Waiting. Complaints nobody has labelled. Each one shows the question and the answer, and the three label buttons. Empty state: Nothing is waiting. When a customer presses This didn't help, the question and the answer show up here.
- Labelled, in three groups. A labelled complaint leaves Waiting and appears in one group.
  - Wrong answer. The person who looks after the agent.
  - Should have refused. The person who looks after the agent.
  - Docs don't cover this. The person who looks after the docs.
  Each group shows its count. An empty group shows who it is for. A labelled complaint shows the question, the answer, and who it goes to.

### Actions

- Wrong answer. One click. Moves that complaint into Wrong answer.
- Should have refused. One click. Moves that complaint into Should have refused.
- Docs don't cover this. One click. Moves that complaint into Docs don't cover this.

No other buttons. A label does not ask for a correct answer, does not ask for phrases the next reply must contain, does not add a case, and does not run Bulk run again.

## 3. Bulk run

Who it is for: someone checking how the agent did on questions written ahead of time. These are recorded passes. They are not rerun when a complaint is labelled, and they are not the Waiting list.

Kicker: Recorded suite. Title: Bulk run.

### Sections

Three runs. One is selected at a time. Each shows its score.

- First run. 8 Oct 09:34 UTC. 14 of 26. Note: one pass over the 26 questions, before the refusal and search fixes. Graded in code.
- After fixes. 19 to 20 of 26. Note: three passes after the fixes. The score moved between 19 and 20. The questions on screen are the pass that is selected, not a new run. This run has three dated passes:
  - 8 Oct 09:54 UTC, 19 of 26
  - 8 Oct 09:57 UTC, 20 of 26
  - 8 Oct 10:01 UTC, 19 of 26
- Held out. 8 Oct 10:09 UTC. 2 of 6. Note: six questions the agent had not been run against. This is the number to trust.

Under the selected pass, three groups. Each group shows how many passed out of how many are in it. A group with none says "None in this run."

- Answerable
- Ambiguous
- Out of scope

Each question shows Pass or Fail, the question, and, if it failed, the reason in one line.

### Actions

- Select First run, After fixes, or Held out.
- On After fixes, select one of the three dated passes.

No button runs the questions again. No button edits a question. No button turns a failure into a Review complaint.

## What the screens do not do

- A customer cannot mark a reply wrong, mark it as something that should have been refused, or type the facts a later reply must contain.
- This didn't help does not add to the 26, and does not add to the 6 held-out questions.
- Labelling does not change 14 of 26, 19 to 20 of 26, or 2 of 6.
- The product stops at routing. It does not decide how a team later turns a label into a test.
