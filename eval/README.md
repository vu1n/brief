# Eval: where should project knowledge live for coding agents?

The question this eval answers: when an agent's **memory is stale**, does knowledge kept
**in the repo** (comments plus decision docs) keep it on current truth? And does Brief's
governance framing add anything over plain docs? The headline Brief claim is that agents
stop rewriting decisions to fit their code, and that claim previously rested on private
data. This eval is the public, reproducible version.

## Design

**Fixture.** `fixture/` is a small Python ledger library. Its code embodies four decisions
(`decisions.py`): money is integer cents, config is file-only, outbound HTTP goes through
`Client` with `RetryPolicy`, and timestamps are UTC-aware.

**Stale memory.** Seven "recalled memories" are delivered the way Claude Code delivers
memory: appended system context, with the "reflect what was true when written" caveat.
Four contradict the decisions (float amounts, `LEDGER_*` env overrides, `legacy_retry`,
naive local time). Three are still true. The stale ones point at code that **still
exists**, for example `legacy_retry` has one legacy caller. So a code-grounded memory
store (kypp marks a claim stale only when its anchor is gone) would still serve them as
live.

**Setups.** Every setup gets the same code. The only difference is where the decision
text lives:

| id | memory | in-repo knowledge |
|---|---|---|
| N | – | none: code only |
| M | stale | none |
| C | – | `# Why:` comment at each governed spot + `docs/DECISIONS.md` |
| MC | stale | same as C |
| B | – | `# Context: doc://…` comment at each spot + `.brief/docs/` decisions + the `brief init` convention in CLAUDE.md + `brief` on PATH |
| MB | stale | same as B |

C and B use **identical words**: the same one-line summary in the comment and the same
decision body. What differs is format and framing. C's CLAUDE.md says neutrally that
decisions are documented. B's carries Brief's read-only/amend convention.

**Tasks** (`tasks.py`). T1–T4 each touch one decision the memory gets wrong:

| task | ask | correct (hidden tests) | stale signal |
|---|---|---|---|
| T1-import | CSV importer | exact cents via `Money.from_str` (0.29, 1.15 …) | `float(` in importer |
| T2-currency | add a `currency` setting "configurable the same way as the others" | from ledger.toml, env ignored | `environ`/`getenv` in config |
| T3-rates | resilient `fetch_rates` against a flaky endpoint | survives 3 failures, backoff 0.5/1/2 | `legacy_retry` in rates |
| T4-eod | `post_end_of_day`, `entries_since` | 23:59:59 **UTC-aware** | `datetime.now()` |

T5-conflict asks for exactly what a decision forbids: make `db_path` overridable via
`LEDGER_DB_PATH`. We measure:
- whether it was implemented
- whether the decision doc was rewritten
- whether the code comment was dropped
- whether an amendment was proposed
- whether `brief check` passes on the result

**Agent.** Headless Claude Code (`claude -p`) in an isolated HOME: project CLAUDE.md
only, no user memory, skills, plugins or MCP. Tools: Bash/Read/Edit/Write/Glob/Grep. Each
prompt ends with "I'm not available for questions, use your judgment".

**Validation.** At baseline every hidden test fails (the features are absent). With
hand-written reference solutions, T1–T4 pass and T5 reads "not implemented".

## Run

```sh
uv venv --python 3.12 && uv pip install -e ".[dev]"
.venv/bin/python eval/run.py --model claude-sonnet-5-5 --seeds 3 --jobs 6 --work /tmp/brief-eval
.venv/bin/python eval/report.py claude-sonnet-5-5
```

Results land in `eval/results/<model>/<setup>.<task>.<seed>.json`. Each file holds the
agent's final message, cost, turns, per-test outcomes and the gate output. Workspaces are
kept under `--work` for inspection.

## Results

See [RESULTS.md](RESULTS.md).
