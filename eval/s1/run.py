"""Score a System One model on the labeled conflict set and report whether it can safely
filter sign-off asks.

The filter only ever *removes* an ask, so the number that matters is recall on violating
diffs at a threshold (an ask suppressed on a real violation is the failure), traded
against the share of conforming asks it suppresses (the fatigue saved). The mechanical
rule is the baseline: it asks on every touched decision (recall 1.0, 0% suppressed).

    uv pip install -e ".[s1]"
    TYPESAFE_API_KEY=... [TYPESAFE_BASE_URL=... TYPESAFE_DEFAULT_MODEL=...] python eval/s1/run.py
    python eval/s1/run.py --report eval/s1/results/<model>.jsonl   # re-report, no calls
"""
import argparse
import gzip
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parents[1] / "src"))
from brief import s1  # noqa: E402

THRESHOLDS = (0.02, 0.05, 0.1, 0.2, 0.3, 0.5)


def score(cases: list[dict], out: Path, jobs: int) -> None:
    done = {json.loads(l)["id"] for l in out.read_text().splitlines()} if out.exists() else set()
    todo = [c for c in cases if c["id"] not in done]
    client = s1.client()

    def one(c):
        a = s1.decide(s1.conflict_state(c["decision"], c["diff"]),
                      {"conflict": s1.conflict_question()}, via=client)
        return c, (a or {}).get("conflict")

    with out.open("a") as f, ThreadPoolExecutor(jobs) as pool:
        for c, a in pool.map(one, todo):
            if a is None:
                print(f"no answer for {c['id']}", file=sys.stderr)
                continue
            f.write(json.dumps({"id": c["id"], "task": c["task"],
                                "violates": c["violates"], "p": a.p}) + "\n")
            f.flush()


def report(rows: list[dict]) -> str:
    pos = [r for r in rows if r["violates"]]
    neg = [r for r in rows if not r["violates"]]
    brier = sum((r["p"] - r["violates"]) ** 2 for r in rows) / len(rows)
    bins: dict[int, list] = {}
    for r in rows:
        bins.setdefault(min(int(r["p"] * 10), 9), []).append(r)
    ece = sum(len(b) / len(rows) * abs(sum(x["p"] for x in b) / len(b)
                                        - sum(x["violates"] for x in b) / len(b))
              for b in bins.values())
    lines = [f"{len(rows)} cases ({len(pos)} violating, {len(neg)} conforming); "
             f"Brier {brier:.3f}, ECE {ece:.3f}", "",
             "| ask when p >= | violations still asked | conforming asks suppressed |",
             "|---|---|---|",
             f"| (mechanical rule) | {len(pos)}/{len(pos)} | 0/{len(neg)} |"]
    for t in THRESHOLDS:
        kept = sum(r["p"] >= t for r in pos)
        cut = sum(r["p"] < t for r in neg)
        lines.append(f"| {t} | {kept}/{len(pos)} | {cut}/{len(neg)} ({cut / max(len(neg), 1):.0%}) |")
    missed = sorted((r for r in pos if r["p"] < 0.1), key=lambda r: r["p"])
    if missed:
        lines += ["", "Violations below 0.1 (would lose their ask):"]
        lines += [f"- {r['id']} ({r['task']}): p={r['p']:.3f}" for r in missed]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", type=Path, default=ROOT / "conflict.jsonl.gz")
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--report", type=Path, help="report on an existing results file only")
    args = ap.parse_args()
    out = args.report
    if out is None:
        if s1.client() is None:
            sys.exit("System One unavailable: install brief[s1] and set TYPESAFE_API_KEY")
        model = os.environ.get("TYPESAFE_DEFAULT_MODEL", "jev-latest")
        out = ROOT / "results" / f"{model.replace('/', '_')}.jsonl"
        out.parent.mkdir(exist_ok=True)
        opener = gzip.open if args.cases.suffix == ".gz" else open
        with opener(args.cases, "rt") as f:
            cases = [json.loads(l) for l in f]
        score(cases, out, args.jobs)
    print(report([json.loads(l) for l in out.read_text().splitlines()]))


if __name__ == "__main__":
    main()
