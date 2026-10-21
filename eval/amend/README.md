# Eval: can a System One model decide which amendments CI may ratify?

Since v0.5.0, CI ratifies an amendment by merging its PR when `brief triage --amendments`
rates it below both thresholds: P(it reverses or weakens the decision) and P(it is
high-impact). Everything else escalates to a person. The failure that matters is a
**miss**: an amendment a person should have seen gets merged on the model's word. The
saving is the share of harmless amendments that never reach a person.

## Cases (`cases.jsonl.gz`, 93)

- **Real (33):** every archived amendment in pillbox and kypp (`build_real.py`). Each case
  is the decision edit (previous revision to the one ratified) plus the amendment text. The
  code diff isn't recoverable per amendment, so it is empty. All 33 were ratified by Vu, so
  the labels say whether a person *should have seen* each one, labeled by hand:
  - should see (22): retirements (8), widenings or reversals (12), and rewordings of an
    authority boundary (2).
  - harmless (11): adding `signoff: required` (8), tightenings (2), and updating names to
    match what was built (1).
- **Synthetic (60):** 12 active pillbox and kypp decisions with 5 variants each, each
  replacing one block of the current text (`synthetic_spec.jsonl.gz`):
  - `clarify` and `tighten` are harmless.
  - `disguised-reversal`, `loophole` and `plain-reversal` should be seen. Disguised
    reversals are framed as clarifications or "align with the code". Loopholes add an
    exception that defeats the rule (an env flag, "trusted" callers, a test directory).

Rebuild with `build_cases.py real.jsonl.gz synthetic_spec.jsonl.gz | gzip -9n > cases.jsonl.gz`.
It reads the decision docs from local pillbox and kypp checkouts.

## Results (2026-10-16, one pass each)

CI's default model is Clef (through the kypp Worker); `run.py --clef` calls the same model on
Workers AI directly. Jev 1.13 is via OpenRouter. `run.py --report <file>` re-prints a table.

### Shipped: one question (`results/*.jsonl`)

`s1.review_question`: "should this change wait for the owner's eyes before it merges?" The
criteria name what a careful owner would want to see first (dropping, loosening, retiring or
carving an exception into a rule, moving a boundary, however it is framed) and what they'd
wave through (rewording, examples, recording what was built, tightening).

| p < | Clef misses | Clef harmless cleared | Jev misses | Jev harmless cleared |
|---|---|---|---|---|
| 0.1 | 0/58 | 8/35 | 0/58 | 0/35 |
| 0.2 | 0/58 | 11/35 | 0/58 | 8/35 |
| 0.25 (shipped) | 0/58 | 15/35 (43%) | 0/58 | 10/35 (29%) |
| 0.3 (0.5.0 to 0.5.2) | 0/58 | 18/35 (51%) | 0/58 | 12/35 (34%) |
| 0.5 | 2/58 | 27/35 | 1/58 | 20/35 |

These counts are in-sample. See "Choosing the cutoff" below for why 0.25 and not 0.3.

At 0.3 Clef clears every clarification and the update-to-reality case, and 5 of 22
tightenings. Tightening a security rule still scores around 0.45: Clef wants a person to see
those. Its lowest should-see scores are 0.355 (a rewording of kypp's authority rules) and
0.363 (a disguised reversal). Every loophole, plain reversal and retirement scored 0.5 or
more.

### Before: two questions (`results/two-questions-*/`)

0.5.0 asked whether the change reverses or weakens the decision, and whether it is
high-impact, and auto-ratified only when both were below 0.05.

- **As shipped (`two-questions-first/`).** The impact question asked whether a change
  touches "a security, data or authority boundary", so every tightening of a security
  decision counted as high-impact. Clef cleared 8 of 35 harmless amendments (clarifications
  only), and Jev cleared 2. On the 33 real amendments, neither model auto-ratified anything.
- **Reworded to ask about loosening (`two-questions-loosening/`).** Clef cleared 22 of 35
  with 0 misses at 0.05, but its closest should-see case scored 0.071 on the reversal
  question. The single question replaced it because it asks what we actually care about
  ("does this need a person?") and its riskiest case sits further from the cutoff (0.355 vs
  0.3, against 0.071 vs 0.05).

### Choosing the cutoff (`eval/cutoff.py`, 2026-10-21)

The table above can't pick a cutoff by itself: every cutoff up to 0.35 shows 0 misses, and
0 in 58 still allows a miss rate up to 5% (95% bound). `eval/cutoff.py` picks it the way
Husain and Saha's [decision-model evals](https://hamel.dev/blog/posts/decision-model-evals/)
do, from the saved scores with no model calls. State what each mistake costs (a needless
review is 1; a miss is `--miss-cost` of them), let a rule pick the cutoff on training folds,
and score it on held-out folds (200 repeats of stratified 5-fold).

```
python eval/cutoff.py eval/amend/results/clef.jsonl --shipped 0.25 --sweep 5,10,20,50,100
```

- **Learning the cutoff from the lowest should-see score leaks.** When the two lowest
  should-see cases (0.355, 0.363) land in the same held-out fold, the training folds' lowest
  is 0.50 and both get through: 0.7% of held-out should-see cases. The tail is two points.
- **Clef is well calibrated here, unlike the post's Clef Flash.** Platt scaling moves the
  out-of-fold Brier from 0.088 to 0.079 and keeps the order. It says a case scoring just
  under 0.3 is should-see with P = 0.073, so clearing it pays only if a miss costs fewer
  than about 13 needless reviews, and the Platt-implied miss rate at 0.3 is 0.37 per 100
  amendments.
- **At a miss cost of 20, the cutoff is 0.25** (calibrated P = 1/21). That clears 15 of 35
  harmless amendments, and the Platt-implied miss rate halves to 0.18 per 100. Cost 50 gives
  0.19 (11 of 35); cost 100 gives 0.14 (8 of 35).
- **Jev 1.13's scores sit higher** (lowest should-see 0.43, Platt P = 0.005 at 0.3), so the
  same cutoff on Jev is more cautious than on Clef. A cutoff belongs to the model and the
  question it was tuned on; `REVIEW_TUNED_ON` names the model in `triage.py`.

`eval/cutoff.py` reads any results file with `escalate`/`review` or `violates`/`p` rows, so
it also checks the sign-off triage (`eval/s1`, Jev 1.13): its 0.1 clears 97% of conforming
asks with no misses, where every learned rule leaks on the one violation scoring 0.21.

### Owner feedback (`feedback.py`)

The fastest way past 93 cases is the owner's own calls. Every triage call brief shows a person
carries `<!-- brief:triage <escalated|automerged> <anchor> <key> p=<p> model=<m> -->`: the
escalation thread, and the comment the automerge job leaves on a PR it merged. A 👍 means the
bot got it right and a 👎 means it got it wrong:

| comment | 👍 | 👎 |
|---|---|---|
| escalated | should see | harmless (could have merged) |
| automerged | harmless | should see (a miss) |

```
GH_TOKEN=... python eval/amend/feedback.py vu1n/pillbox vu1n/kypp
python eval/cutoff.py --pool eval/amend/results/clef.jsonl eval/amend/results/feedback/clef.jsonl --shipped 0.25
```

Only reactions from people with write access count, and a comment graders disagree on is
dropped. These cases saw the governed code change, as CI's triage does, so they are closer
to production than `cases.jsonl.gz`. A 👎 on an automerge comment is the rarest and most
useful label: it is a measured miss.

## Caveats

- Both rewordings were written after seeing results on these same 93 cases, so treat the
  numbers as optimistic until a fresh set confirms them. Don't raise the threshold on this
  data.
- The labels are one person's judgement for the real set, and are set by construction for
  the synthetic set. The same model family wrote the synthetic cases and the labels.
- There is no code diff in any case. In CI the model also sees the governed code change.
- Each result is a single pass.
