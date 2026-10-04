# Eval: can a System One model filter sign-off asks?

Brief asks for a sign-off whenever a change touches the code under a `signoff: required`
decision. Most of those asks are rubber-stamped: pillbox logged 244 `conforms` lines
against 1 `amend-proposed`. A System One model (Jev, Clef) answers typed questions with
calibrated probabilities. If it can say "this diff plausibly cuts against the decision"
reliably, brief could ask only when it does.

**Cases** (`conflict.jsonl.gz`, 281 rows): real agent diffs from the docs-vs-memory eval
(`eval/run.py`), each paired with the decision its task touched. The label comes from that
run's hidden tests: a diff violates the decision when its hidden tests fail. T5 is the
exception, since implementing that ask is the violation. Diffs that changed no code are
dropped. Rebuild with `build_cases.py --work <evalwork>`.

**Question** (`brief.s1.conflict_question`): one `noul`, "does the diff do something the
decision forbids?", with the decision and diff as state.

**What passes:** the filter only removes asks, so suppressing an ask on a real violation is
the failure. A threshold is usable when every violation is still asked (54/54) and a large
share of conforming asks is suppressed. The mechanical rule asks on all of them.

```sh
uv pip install -e ".[s1]"
# Jev via OpenRouter; any TypeSafe-API endpoint works the same way.
TYPESAFE_API_KEY=$OPENROUTER_API_KEY TYPESAFE_BASE_URL=https://openrouter.ai/api \
  TYPESAFE_DEFAULT_MODEL=typesafe/jev-1.13 .venv/bin/python eval/s1/run.py
```

Answers are cached in `results/<model>.jsonl`, and the run resumes. `--report <file>`
re-prints the table without calls.
