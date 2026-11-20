# Judge spot-check

The faithfulness judge (`gemini-3.5-flash-lite`) was checked by hand on 20% of the Eval Set (#46). The sample was 10 of the 50 items, taken from the nightly full run of 2026-11-20. Each answer sentence was compared with the Demo Collection Documents' own text.

| Item | Judge | By hand | Notes |
| --- | --- | --- | --- |
| ssp-amount | 1 of 1 supported | 1 of 1 | £123.25 a week, or 80% of normal weekly earnings if lower |
| ssp-duration | 1 of 1 | 1 of 1 | Up to 28 weeks |
| fit-note | 1 of 1 | 1 of 1 | More than 7 days in a row, including non-working days |
| holiday-full-time | 1 of 1 | 1 of 1 | 5.6 weeks |
| carry-over | 1 of 1 | 1 of 1 | Up to 8 days, with the employer's agreement |
| max-hours | 2 of 2 | 2 of 2 | 48 hours averaged over 17 weeks; under 18, at most 40 hours a week |
| hours-opt-out | 1 of 1 | 1 of 1 | Over 18, by opting out |
| maternity-leave-length | 1 of 1 | 1 of 1 | 52 weeks: 26 ordinary and 26 additional |
| maternity-compulsory | 1 of 1 | 1 of 1 | 2 weeks, or 4 in a factory |
| conflict-irregular-minimum | 2 of 3 | 2 of 3 | The opening "Yes." is unsupported. Since the 2024 reforms, 5.6 weeks is a maximum accrued by hours worked, not a guarantee (#48) |

**Agreement: 13 of 13 sentences (100%), and 10 of 10 items.**

The sample is small and mostly simple factual answers. Re-check when the set grows (M5), weighted towards conflict and multi-passage answers, where the judge has more to get wrong.

In a later CI run, the judge marked one correct sentence unsupported: holiday-part-time, "16.8 days". So the judge is not infallible, and a single-sentence drop in faithfulness on a pull request is worth reading before acting on it.
