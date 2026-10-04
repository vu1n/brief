"""Build the labeled conflict set from the docs-vs-memory eval's workspaces.

Each run of eval/run.py left a workspace whose diff against the baseline is one agent's
change, and its hidden tests say whether that change honored the task's decision. That
gives real agent diffs with ground-truth labels for "does this diff cut against the
decision?". The label is the hidden tests' verdict, inverted for T5 (where implementing
the ask *is* the violation).

    python eval/s1/build_cases.py --work <evalwork dir> | gzip -9n > eval/s1/conflict.jsonl.gz

Gzipped because the diffs carry the fixture's `doc://ledger/...` refs, which `brief check`
would flag as broken refs in this repo.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from decisions import DECISIONS  # noqa: E402
from tasks import TASKS  # noqa: E402

RESULTS = Path(__file__).resolve().parents[1] / "results"


def _diff(ws: Path) -> str:
    git = ["git", "-C", str(ws)]
    base = subprocess.run(git + ["rev-list", "--max-parents=0", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.split()[0]
    subprocess.run(git + ["add", "-A"], check=True)
    return subprocess.run(git + ["diff", "--cached", base, "--", "ledger"],
                          capture_output=True, text=True, check=True).stdout


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True, type=Path)
    args = ap.parse_args()
    for f in sorted(RESULTS.glob("*/*.json")):
        r = json.loads(f.read_text())
        ws = args.work / r["model"] / f.stem
        if not ws.exists():
            print(f"skip {f.stem}: no workspace", file=sys.stderr)
            continue
        diff = _diff(ws)
        if not diff.strip():
            continue  # no code change: nothing for a reviewer to judge
        task = TASKS[r["task"]]
        d = next(d for d in DECISIONS if d["key"] == task["decision"])
        hidden_ok = r["hidden_ok"] in (True, "True")
        violates = hidden_ok if r["task"] == "T5-conflict" else not hidden_ok
        print(json.dumps({
            "id": f'{r["model"]}/{f.stem}', "task": r["task"], "cond": r["cond"],
            "anchor": d["anchor"], "decision": f'{d["title"]}. {d["body"]}',
            "diff": diff, "violates": violates,
        }))


if __name__ == "__main__":
    main()
