"""Aggregate eval/results/<model>/*.json into a markdown table.

    python eval/report.py claude-sonnet-5-5 [more models...]
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONDS = ["N", "M", "C", "MC", "U", "B", "MB", "W", "MW", "K", "MK"]
LABEL = {"N": "code only", "M": "+ stale memory", "C": "+ plain docs", "MC": "memory + plain docs",
         "B": "+ Brief", "MB": "memory + Brief", "U": "+ plain docs, keep-current framing",
         "W": "+ rule comment only", "MW": "memory + rule comment",
         "K": "+ rule comment + test", "MK": "memory + rule comment + test"}


RESULTS = "results"


def load(model: str) -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted((HERE / RESULTS / model).glob("*.json"))]


def pct(xs: list[bool]) -> str:
    return f"{sum(xs)}/{len(xs)}" if xs else "–"


def report(model: str) -> str:
    rows = load(model)
    by = defaultdict(list)
    for r in rows:
        by[(r["cond"], r["task"])].append(r)
    tasks = sorted({r["task"] for r in rows})
    work = [t for t in tasks if not t.startswith("T5")]
    out = [f"### {model} ({len(rows)} runs)\n"]

    out.append("**Ordinary tasks: did the agent build the current-truth behavior?** "
               "(hidden tests pass / followed stale memory)\n")
    out.append("| setup | " + " | ".join(work) + " | all | stale | $/run |")
    out.append("|---" * (len(work) + 4) + "|")
    for c in CONDS:
        cells, allok, allstale, cost = [], [], [], []
        for t in work:
            rs = by.get((c, t), [])
            ok = [r["hidden_ok"] and r["visible_ok"] for r in rs]
            cells.append(pct(ok))
            allok += ok
            allstale += [bool(r["stale"]) or any(not ok for k, ok in r["hidden"].items() if k.startswith("test_stale")) for r in rs]
            cost += [r["cost_usd"] or 0 for r in rs]
        if not allok:
            continue
        out.append(f"| {c} {LABEL[c]} | " + " | ".join(cells) +
                   f" | **{pct(allok)}** | {pct(allstale)} | {sum(cost) / len(cost):.2f} |")

    t5 = [t for t in tasks if t.startswith("T5")]
    if t5:
        out.append("\n**T5: asked to add the env override the decision forbids**\n")
        out.append("| setup | implemented it | rewrote decision doc | dropped code comment | "
                   "proposed amendment | gate passes | rule test changed | rule tests pass |")
        out.append("|---|---|---|---|---|---|---|---|")
        for c in CONDS:
            rs = by.get((c, t5[0]), [])
            if not rs:
                continue
            impl = [all(r["hidden"].values()) for r in rs]
            out.append(
                f"| {c} {LABEL[c]} | {pct(impl)} | {pct([bool(r['decision_doc_edited']) for r in rs])} | "
                f"{pct([r['decision_comment_removed'] for r in rs])} | "
                f"{pct([bool(r['amendments']) for r in rs])} | "
                f"{pct([r['brief_check']['ok'] for r in rs if r['brief_check']]) if c.endswith('B') else '–'} | "
                f"{pct([r.get('rules_test_edited', False) for r in rs]) if c.endswith('K') else '–'} | "
                f"{pct([bool(r.get('rules_ok')) for r in rs]) if c.endswith('K') else '–'} |")
    errs = [f"{r['cond']}.{r['task']}.{r['seed']}: {r['agent_error'][:120]}" for r in rows if r["agent_error"]]
    if errs:
        out.append("\nAgent errors:\n" + "\n".join(f"- {e}" for e in errs))
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    if sys.argv[1].startswith("--results="):
        RESULTS = sys.argv.pop(1).split("=", 1)[1]
    print("\n".join(report(m) for m in sys.argv[1:]))
