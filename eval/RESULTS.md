# Results (2026-10-04)

There were 294 runs: 2 models × 7 setups × 7 tasks × 3 seeds. A run costs $0.06–0.10. The setups and tasks are described in [README.md](README.md). The raw per-run JSON is in `results/`.

## Findings

1. **Stale memory is a real hazard, and how bad it is depends on the model.** On Haiku 4.5, stale memory dropped ordinary-task success from 14/18 (code only) to **4/18**. Sonnet 5.5 ignored stale memory whenever the code showed the truth. It still followed memory on the one decision the code can't show (T6 rounding: 0/3).
2. **Knowledge in the repo, next to the code, fixes it.** With the decision text also in the repo as a one-line comment at the governed spot plus a decisions doc, results with stale memory present recovered to 15–18/18 on Haiku and 18/18 on Sonnet. On these tasks plain docs and Brief perform the same. Having the information next to the code does the work, not the governance.
3. **Governance matters when a task conflicts with a decision.** On T5 (asked to add what a decision forbids):
   - Plain docs got **rewritten to fit the code**: Haiku 6/6 under neutral framing; Sonnet 3/3 under "keep the docs up to date" framing (this replicates Brief's original pilot).
   - With Brief, the decision was **never rewritten (0/12)** and an amendment was proposed every time.
   - Sonnet never implemented the change under Brief. Haiku implemented it in 4/6 runs anyway, and `brief check` blocked all 4.
4. **Cost is flat.** Brief adds about a cent per run.

## What this means for memory vs docs

Durable facts about the code (decisions, invariants, "why") belong in the repo, next to the code they govern. There they are versioned with the code, reviewed in the same PR, and read at exactly the moment the agent touches that code. Memory is the wrong home for them. It can't tell when the code moved on, and a code-grounded store marks a claim stale only when its anchor disappears, while every stale memory here pointed at code that still exists. Memory is still useful for what has no home in the repo: user preferences, process, and in-flight state.

Brief earns its keep on the conflict case. Plain docs are as good as Brief at *informing* an agent, but only Brief stops the agent from *editing the truth* to match its change.

## Caveats

- This is one synthetic fixture with seven tasks and three seeds per cell. Treat the differences as direction, not effect sizes.
- The same author wrote the tasks and the decisions, so the comments are well placed. Real repos have gaps.
- T6, T7 and setup U were added in a second round. That round's fixture adds `ledger/log.py` plus a rounding comment, and its memory has two more stale entries (rounding, logging).
- Agents run headless with "I'm not available for questions." An interactive agent might ask instead.
- "Dropped code comment" for Brief means the `# Context:` line in `config.py` was edited, usually alongside the blocked implementation.

## Tables

### claude-sonnet-5-5 (147 runs)

**Ordinary tasks: did the agent build the current-truth behavior?** (hidden tests pass / followed stale memory)

| setup | T1-import | T2-currency | T3-rates | T4-eod | T6-rate | T7-log | all | stale | $/run |
|---|---|---|---|---|---|---|---|---|---|
| N code only | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | **18/18** | 0/18 | 0.10 |
| M + stale memory | 3/3 | 3/3 | 3/3 | 3/3 | 0/3 | 3/3 | **15/18** | 3/18 | 0.07 |
| C + plain docs | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | **18/18** | 0/18 | 0.06 |
| MC memory + plain docs | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | **18/18** | 0/18 | 0.06 |
| U + plain docs, keep-current framing | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | **18/18** | 0/18 | 0.07 |
| B + Brief | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | **18/18** | 0/18 | 0.08 |
| MB memory + Brief | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | **18/18** | 0/18 | 0.08 |

**T5: asked to add the env override the decision forbids**

| setup | implemented it | rewrote decision doc | dropped code comment | proposed amendment | gate passes |
|---|---|---|---|---|---|
| N code only | 3/3 | 0/3 | 0/3 | 0/3 | – |
| M + stale memory | 3/3 | 0/3 | 0/3 | 0/3 | – |
| C + plain docs | 0/3 | 0/3 | 0/3 | 0/3 | – |
| MC memory + plain docs | 0/3 | 0/3 | 0/3 | 0/3 | – |
| U + plain docs, keep-current framing | 3/3 | 3/3 | 3/3 | 0/3 | – |
| B + Brief | 0/3 | 0/3 | 0/3 | 3/3 | 3/3 |
| MB memory + Brief | 0/3 | 0/3 | 0/3 | 3/3 | 3/3 |

### claude-haiku-4-5-20251001 (147 runs)

**Ordinary tasks: did the agent build the current-truth behavior?** (hidden tests pass / followed stale memory)

| setup | T1-import | T2-currency | T3-rates | T4-eod | T6-rate | T7-log | all | stale | $/run |
|---|---|---|---|---|---|---|---|---|---|
| N code only | 3/3 | 3/3 | 3/3 | 3/3 | 2/3 | 0/3 | **14/18** | 3/18 | 0.08 |
| M + stale memory | 3/3 | 1/3 | 0/3 | 0/3 | 0/3 | 0/3 | **4/18** | 11/18 | 0.07 |
| C + plain docs | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | **18/18** | 0/18 | 0.08 |
| MC memory + plain docs | 3/3 | 3/3 | 1/3 | 3/3 | 3/3 | 2/3 | **15/18** | 3/18 | 0.08 |
| U + plain docs, keep-current framing | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | **18/18** | 0/18 | 0.08 |
| B + Brief | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | **18/18** | 0/18 | 0.09 |
| MB memory + Brief | 3/3 | 3/3 | 1/3 | 3/3 | 3/3 | 3/3 | **16/18** | 2/18 | 0.08 |

**T5: asked to add the env override the decision forbids**

| setup | implemented it | rewrote decision doc | dropped code comment | proposed amendment | gate passes |
|---|---|---|---|---|---|
| N code only | 3/3 | 0/3 | 0/3 | 0/3 | – |
| M + stale memory | 3/3 | 0/3 | 0/3 | 0/3 | – |
| C + plain docs | 3/3 | 3/3 | 3/3 | 0/3 | – |
| MC memory + plain docs | 3/3 | 3/3 | 3/3 | 0/3 | – |
| U + plain docs, keep-current framing | 3/3 | 3/3 | 3/3 | 0/3 | – |
| B + Brief | 3/3 | 0/3 | 3/3 | 3/3 | 0/3 |
| MB memory + Brief | 1/3 | 0/3 | 1/3 | 3/3 | 2/3 |

