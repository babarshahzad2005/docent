# Evals

Answer quality for Docent is measured here, not judged by feel.

## The Eval Set

[`eval-set.jsonl`](eval-set.jsonl) holds 50 questions about the [Demo Collection](demo/), one per line:

- **33 answerable**, each with its expected passages: the Document, and words the passage contains. A question can have more than one correct passage.
- **3 conflict** questions, where the 2019 holiday calculation guidance and the January 2024 reforms disagree. Both versions are expected.
- **14 unanswerable** questions, hand-written. Most sit near the Documents' subjects (sick pay in Germany, a parking policy, the office printer), so declining them is a real test; each was checked against the Documents' text, and questions the GitLab Handbook turned out to answer (sales bonuses, dress code) were replaced.

Answerable questions were drafted from the Documents. Every item is reviewed by the maintainer (`"reviewed": true`).

## The harness

`uv --directory apps/api run docent-eval` runs every question through Docent's own answer path, without saving anything:

1. retrieval;
2. the weak-retrieval decline;
3. the answer model;
4. quote verification;
5. the model's own decline.

It writes `evals/results/latest.json` and a Markdown summary, and reports these metrics:

| Metric | What it counts | Target (PRD) |
| --- | --- | --- |
| hit@5 | Answerable and conflict questions with an expected passage (any one) in the top 5 retrieved | ≥ 90% |
| Faithfulness | Sentences of the shown answer (after verification removed unsupported claims) that a judge model finds supported by the passages they cite; a sentence citing nothing counts as unsupported unless it only links others | ≥ 95% |
| Answers judged | Shown answers the judge returned a verdict for: a judge failure is counted here, never silently dropped | 100% |
| Unanswerable declined | Unanswerable questions declined | ≥ 90% |
| Answerable answered | Answerable questions answered, not declined or hidden | |
| Conflicts both retrieved | Conflict questions with both versions among the 8 passages | |

The judge is `gemini-3.5-flash-lite`, never the answer model (`gpt-oss-120b` on Groq). Answers use the answer model alone, at temperature 0, with no fallback, paced to Groq's free tier. `--answers N` answers only the first N answerable questions; every question is still retrieved, and the unanswerable ones are always run.

Faithfulness is measured on what the reader sees, by sentence. The PRD's wording ("citations whose passage supports the claim") is close: verification has already removed every claim whose quote isn't in its passage, so the judge measures the gap quote matching leaves (ADR 0007).

## In CI

`.github/workflows/eval.yml` runs the harness against the Demo Collection, as a read-only database user (`docent_eval`).

- **On every pull request** the check runs.
  - If the change touches the answer path, every question is retrieved and the first 8 answerable ones are answered. The answer path is answers, retrieval, verification, rewriting, providers, settings, the harness, the set, the Demo Documents, or the dependencies. The result is compared with main's latest run.
  - Otherwise the check passes at once, so it can be a required check.
- **On main**, the same subset runs after such a change. It becomes the baseline that pull requests are compared with, and a run with failed questions fails, so it is never used as one.
- **Nightly** (03:17 UTC, or by hand), the full set runs, with every answerable question answered.

A pull request is blocked when any of these happens:

- a metric is more than 2 points below main's;
- a metric that main meets falls below its PRD target;
- a metric main reports is missing from the run;
- a question fails to run.

The metrics that depend on what the models write (answerable answered, faithfulness, answers judged) get an allowance of one item: at temperature 0 they still vary a little, and one answer of 8 is 12.5 points. Retrieval metrics get no allowance, because they don't vary.

The issue (#46) asked for a 30-question subset on every pull request. Answers share Groq's free tier with production, about 200,000 tokens a day at roughly 4,500 tokens per answer. So pull requests answer 8 questions and retrieve all 50, only when the answer path changed, and the full set runs nightly (PRD decision log, 2026-11-19).

A pull request that brings a database migration can't be measured against the live database, which only migrates once the change is merged. Its check passes with a note, and main's run after the merge measures it.

The eval reads the Demo Collection as seeded. Changes to chunking or extraction are measured only after `docent-demo seed` has run with them.

Secrets: `EVAL_DATABASE_URL` (the read-only user), `GEMINI_API_KEY`, `GROQ_API_KEY`.

## Results

These results come from the first run on 2026-11-19 against the production Demo Collection, with 10 answerable questions answered. One answer of the 7 went unjudged (the judge's reply couldn't be read, since fixed), so faithfulness here is over 6 answers.

| Metric | Result |
| --- | --- |
| hit@5 | 86.1% (31 of 36) |
| Faithfulness | 100% (6 of 6 sentences) |
| Unanswerable declined | 100% (14 of 14) |
| Answerable answered | 70% (7 of 10) |
| Conflicts both retrieved | 0% (0 of 3) |

There are three known gaps:

- **Uncited answers are hidden.** Two correct answers were hidden because the model wrote them without citation markers, so nothing could be checked.
- **Some answers rank just below the top 5.** Two GitLab answers ranked 6th and 7th.
- **The older guidance isn't retrieved.** The 2019 guidance is never retrieved alongside the 2024 reforms, which matters for the conflict work in #48.

After #58, when an answer has no citation markers, its verified quotes are tied to the sentences they match. A run on 2026-11-20 over the same 10 answerable questions gave:

- answerable answered: 90% (9 of 10), up from 70%;
- faithfulness: 100% (10 of 10 sentences);
- answers judged: 9 of 9.

The one question not answered is a retrieval miss (holiday-part-time).

### The weak-retrieval threshold

The weak-retrieval threshold (`DECLINE_BELOW_SIMILARITY`) was chosen from each question's best passage similarity. These are the shares at each candidate threshold:

| Threshold | Unanswerable declined before the model | Answerable reaching the model |
| --- | --- | --- |
| 0.65 | 93% | 100% |
| 0.66 | 93% | 100% |
| 0.67 | 100% | 100% |
| **0.68** | **100%** | **100%** |
| 0.69 | 100% | 97% |

At 0.67 and 0.68, every unanswerable question is declined before the model, and every answerable one reaches it. The lowest answerable similarity is 0.686 (maternity-compulsory), so 0.68 is the setting. Questions naming an identifier that keyword search finds ("form HR-27") reach the model whatever their similarity, and the sweep counts them that way.

The set is small, so the threshold should be re-checked as the set grows (M5).
