# Kernel docs agent

A support desk over [Kernel's public docs](https://docs.kernel.ai). A customer asks a question. The agent looks it up, cites the passage, or says the docs don't cover it. If the reply did not help, a reviewer labels it. Separately, the agent was checked on a fixed set of questions. Those runs are recorded and graded in code.

This is a portfolio piece. It is not Kernel's product and it is not affiliated with Kernel. It does not read Kernel account data. No support team has used it. The longer account is [write-up.md](write-up.md), and the same text is the About page in the app.

## Screens

- Ask the docs, `/`. Customer screen. **This helped** stays on the page. **This didn't help** sends the question and the answer to Review.
- Review, `/review`. For reviewers. One label: wrong answer, incomplete, should have refused, or docs don't cover this. A label does not create a test.
- Bulk run, `/bulk`. Recorded checks. First run 14 of 26. After the fixes, 19 to 20 of 26. Held out 2 of 6. The held-out score is the one to trust.
- About, `/about`. The write-up.

The six labelled complaints on Review are examples in `evals/demo_review.jsonl`. They are not customer reports.

## Run it locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Put an Anthropic key in `.env`. The file is gitignored.

```bash
python app.py
```

Open http://127.0.0.1:8000. The process listens on `0.0.0.0` and on `PORT` (8000 if unset), so the same command is what Railway runs. The model is `config.json`. The first question waits while the docs index is fetched.

Checks that do not call the model:

```bash
python check_facts.py
python -m unittest
```

`check_facts.py` needs the network. It confirms every required fact is still on the live source page.

`python run_suite.py` spends API calls and writes `evals/results/<timestamp>.json`. Replay a saved file without a model call:

```bash
python run_suite.py --replay evals/results/2026-10-08T100133Z.json
```

## Railway

The app is ready to deploy as a single web service. `railway.toml` starts `python app.py` and checks `/api/health`. Railway sets `PORT`. The process binds `0.0.0.0`.

Set these variables on the service. Do not commit the key.

| Variable | Value |
| --- | --- |
| `ANTHROPIC_API_KEY` | The Anthropic key |
| `PUBLIC_DEMO` | `1` |

`PUBLIC_DEMO=1` limits Ask the docs to 12 questions an hour per address, and a flagged case is not written into the 26. Review labels and chat memory live on the instance. A restart clears new complaints and conversations. The six example complaints and the recorded runs come back from the repo.

Disk is ephemeral. `.cache/` is rebuilt from docs.kernel.ai on boot. `logs/` is not in git.
