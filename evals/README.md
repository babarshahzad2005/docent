# Evals

Answer quality for Docent is measured here, not judged by feel.

## The Eval Set

[`eval-set.jsonl`](eval-set.jsonl) holds 50 questions about the [Demo Collection](demo/), one per line:

- **33 answerable**, each with its expected passages: the Document, and words the passage contains. A question can have more than one correct passage.
- **3 conflict** questions, where the 2019 holiday calculation guidance and the January 2024 reforms disagree. Both versions are expected.
- **14 unanswerable** questions, hand-written to sit near the Documents' subjects (sick pay in Germany, a parking policy) so that declining them is a real test.

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
| hit@5 | Answerable questions with an expected passage in the top 5 retrieved | ≥ 90% |
| Faithfulness | Answer sentences a judge model finds supported by the passages they cite | ≥ 95% |
| Unanswerable declined | Unanswerable questions declined | ≥ 90% |
| Answerable answered | Answerable questions answered, not declined or hidden | |
| Conflicts both retrieved | Conflict questions with both versions among the 8 passages | |

The judge is `gemini-3.5-flash-lite`, never the answer model (`gpt-oss-120b` on Groq). Answers use the answer model alone, at temperature 0, with no fallback, paced to Groq's free tier. `--answers N` answers only the first N answerable questions; every question is still retrieved, and the unanswerable ones are always run.

## Results

These results come from the first run on 2026-11-19 against the production Demo Collection, with 10 answerable questions answered.

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
| 0.66 | 79% | 100% |
| 0.67 | 93% | 100% |
| **0.68** | **93%** | **100%** |
| 0.69 | 100% | 97% |

Below 0.69, every answerable question reaches the model, which can still decline. 0.68 keeps a margin under the lowest answerable similarity (0.686), so it is the setting. The one unanswerable question above the threshold, about a sales bonus scheme, was declined by the model itself.

The set is small, so the threshold should be re-checked as the set grows (M5).
