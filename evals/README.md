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
