# Results: rule comments and tests vs decision docs (2026-10-25)

560 runs: Haiku 4.5 × 10 setups × 7 tasks × 5 seeds, and Sonnet 5.5 × 10 × 7 × 3. Total
cost $39.57, with 0 agent errors. Same fixture and tasks as [RESULTS.md](RESULTS.md). The
first six setups were rerun fresh so every setup comes from the same CLI version
(Claude Code 2.1.310, brief 0.5.4). Raw per-run JSON is in `results-rules/`.

New setups:

| id | memory | in-repo knowledge |
|---|---|---|
| W | – | `# Rule: <summary>` at each governed spot. CLAUDE.md says rules describe the code as it is, and a task that needs one changed changes the rule and the code together, and says so |
| MW | stale | same as W |
| K | – | W, plus the comment names a test in `tests/test_rules.py` that enforces it ([rules_test.py](rules_test.py), one test per rule) |
| MK | stale | same as K |

W and K have no decisions doc, no Brief convention and no amendment path. The comment uses the
same one-line summary as C and B. The rule tests check the existing code: a type check, a
config check that loops over every field, and static scans like pillbox's
`do_usage_policy.test.mjs`. They know nothing about what a task adds. Each test was checked
against a hand-written stale change for its rule, and all 6 failed as they should.

## Findings

1. **A comment plus a test matched or beat every docs setup.** On the ordinary tasks, K and MK
   scored 30/30 on Haiku, and MK was the only stale-memory setup with zero misses (MC and MB 28/30,
   MW 24/30). On Sonnet every in-repo setup scored 18/18. A test turns the rule into something the
   agent runs into, not just something it might read.
2. **A comment alone is nearly as good as docs without stale memory, and weaker with it.** W got
   29/30 and C 30/30. Under stale memory MW got 24/30 and MC 28/30 (Fisher p=0.25, so not
   significant at n=30). The doc body adds a little against stale memory; the test adds more
   (MK vs MW p=0.024).
3. **Decision framing makes agents refuse their owner's request.** On T5 the person asks for the
   env override the rule forbids. Sonnet did it in **2 of 12** decision-framed runs (C, MC, B, MB)
   and **12 of 12** rule-framed runs (W, MW, K, MK), p<0.001. Under Brief it never did it (0/6) and
   proposed an amendment instead. When the person asking owns the rule, the decision framing is
   working against them.
4. **Docs fall out of sync, and comments don't.** After T5, the decisions doc contradicted the
   code in **18 of 32** decision-framed runs. In 12 the agent implemented the change and left the
   doc as it was (C, MC, B, MB, 3 each). In 6, all Brief runs, the agent wrote the proposed
   decision text but no code. The rule comment was rewritten to match the code in **32 of 32**
   rule-framed runs, and in K and MK the rule test was updated in the same change, 16 of 16.
5. **None of the setups stops stale memory from widening a requested change.** With stale memory
   on T5, Haiku made every setting env-overridable, not just `db_path`: MW 5/5, MK 5/5, MC 4/5,
   MB 3/5, M 5/5. In MK it rewrote the rule test to match the wider change, so the passing test
   proves nothing there. Sonnet never did this in any in-repo setup. A rule test pins what the
   code does, not what the person asked for. That gap belongs to review.
6. **Cost is flat:** $0.05 to $0.09 per run across every setup.

## What this means for brief

The original eval said "Having the information next to the code does the work, not the
governance." This run adds two things:

- **An enforcing test does more than any doc**, and it is the one thing here that stays in sync
  on its own.
- **The "decided / read-only" framing is a cost, not a protection, when the person asking owns
  the rule.** It produced refusals and docs left contradicting the code. A rule described as the
  current state of the code, changed with the code, did neither.

## Caveats

- This is one synthetic fixture, written by the same author as the rules and tests, so the rule
  tests fit it well. Real repos will have rules with no test.
- n=5 (Haiku) and n=3 (Sonnet) per cell. Treat differences under about 4/30 as noise.
- I read the rule-framed T5 summaries with a keyword check (rule, decision, previously, …), and
  all 32 tell the person the rule changed. That check is crude, so it isn't in the table.
- "Dropped code comment" in the T5 table means the original one-line summary is gone. For W and
  K that is the intended update: the comment was rewritten to the new rule in every case.

## Tables

### claude-haiku-4-5-20251001 (350 runs)

**Ordinary tasks: did the agent build the current-truth behavior?** (hidden tests pass / followed stale memory)

| setup | T1-import | T2-currency | T3-rates | T4-eod | T6-rate | T7-log | all | stale | $/run |
|---|---|---|---|---|---|---|---|---|---|
| N code only | 5/5 | 5/5 | 5/5 | 5/5 | 4/5 | 0/5 | **24/30** | 5/30 | 0.07 |
| M + stale memory | 5/5 | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | **5/30** | 19/30 | 0.07 |
| C + plain docs | 5/5 | 5/5 | 5/5 | 5/5 | 5/5 | 5/5 | **30/30** | 0/30 | 0.08 |
| MC memory + plain docs | 5/5 | 5/5 | 3/5 | 5/5 | 5/5 | 5/5 | **28/30** | 2/30 | 0.09 |
| B + Brief | 5/5 | 5/5 | 5/5 | 5/5 | 5/5 | 5/5 | **30/30** | 0/30 | 0.08 |
| MB memory + Brief | 5/5 | 5/5 | 3/5 | 5/5 | 5/5 | 5/5 | **28/30** | 2/30 | 0.09 |
| W + rule comment only | 5/5 | 5/5 | 5/5 | 5/5 | 5/5 | 4/5 | **29/30** | 1/30 | 0.07 |
| MW memory + rule comment | 5/5 | 2/5 | 4/5 | 5/5 | 5/5 | 3/5 | **24/30** | 6/30 | 0.07 |
| K + rule comment + test | 5/5 | 5/5 | 5/5 | 5/5 | 5/5 | 5/5 | **30/30** | 0/30 | 0.08 |
| MK memory + rule comment + test | 5/5 | 5/5 | 5/5 | 5/5 | 5/5 | 5/5 | **30/30** | 0/30 | 0.08 |

**T5: asked to add the env override the decision forbids**

| setup | implemented it | rewrote decision doc | dropped code comment | proposed amendment | gate passes | rule test changed | rule tests pass |
|---|---|---|---|---|---|---|---|
| N code only | 5/5 | 0/5 | 0/5 | 0/5 | – | – | – |
| M + stale memory | 5/5 | 0/5 | 0/5 | 0/5 | – | – | – |
| C + plain docs | 5/5 | 2/5 | 5/5 | 0/5 | – | – | – |
| MC memory + plain docs | 5/5 | 2/5 | 5/5 | 0/5 | – | – | – |
| B + Brief | 5/5 | 2/5 | 5/5 | 5/5 | 2/5 | – | – |
| MB memory + Brief | 3/5 | 0/5 | 3/5 | 4/5 | 1/5 | – | – |
| W + rule comment only | 5/5 | 0/5 | 5/5 | 0/5 | – | – | – |
| MW memory + rule comment | 5/5 | 0/5 | 5/5 | 0/5 | – | – | – |
| K + rule comment + test | 5/5 | 0/5 | 5/5 | 0/5 | – | 5/5 | 5/5 |
| MK memory + rule comment + test | 5/5 | 0/5 | 5/5 | 0/5 | – | 5/5 | 5/5 |

### claude-sonnet-5-5 (210 runs)

**Ordinary tasks: did the agent build the current-truth behavior?** (hidden tests pass / followed stale memory)

| setup | T1-import | T2-currency | T3-rates | T4-eod | T6-rate | T7-log | all | stale | $/run |
|---|---|---|---|---|---|---|---|---|---|
| N code only | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | **18/18** | 0/18 | 0.05 |
| M + stale memory | 3/3 | 3/3 | 3/3 | 3/3 | 0/3 | 3/3 | **15/18** | 3/18 | 0.08 |
| C + plain docs | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | **18/18** | 0/18 | 0.05 |
| MC memory + plain docs | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | **18/18** | 0/18 | 0.05 |
| B + Brief | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | **18/18** | 0/18 | 0.06 |
| MB memory + Brief | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | **18/18** | 0/18 | 0.06 |
| W + rule comment only | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | **18/18** | 0/18 | 0.05 |
| MW memory + rule comment | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | **18/18** | 0/18 | 0.05 |
| K + rule comment + test | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | **18/18** | 0/18 | 0.05 |
| MK memory + rule comment + test | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | **18/18** | 0/18 | 0.06 |

**T5: asked to add the env override the decision forbids**

| setup | implemented it | rewrote decision doc | dropped code comment | proposed amendment | gate passes | rule test changed | rule tests pass |
|---|---|---|---|---|---|---|---|
| N code only | 3/3 | 0/3 | 0/3 | 0/3 | – | – | – |
| M + stale memory | 3/3 | 0/3 | 0/3 | 0/3 | – | – | – |
| C + plain docs | 1/3 | 1/3 | 1/3 | 0/3 | – | – | – |
| MC memory + plain docs | 1/3 | 1/3 | 1/3 | 0/3 | – | – | – |
| B + Brief | 0/3 | 3/3 | 0/3 | 3/3 | 3/3 | – | – |
| MB memory + Brief | 0/3 | 3/3 | 0/3 | 3/3 | 3/3 | – | – |
| W + rule comment only | 3/3 | 0/3 | 3/3 | 0/3 | – | – | – |
| MW memory + rule comment | 3/3 | 0/3 | 3/3 | 0/3 | – | – | – |
| K + rule comment + test | 3/3 | 0/3 | 3/3 | 0/3 | – | 3/3 | 3/3 |
| MK memory + rule comment + test | 3/3 | 0/3 | 3/3 | 0/3 | – | 3/3 | 3/3 |
