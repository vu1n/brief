"""Score a System One model on labeled amendments: can it tell CI which ones to ratify by merging?

`brief triage --amendments` asks one noul question (should this wait for the owner's eyes?)
and CI auto-ratifies only when it sits below REVIEW_THRESHOLD. The failure that
matters is an amendment a human should have seen getting auto-ratified (a miss); the
fatigue saved is the share of harmless amendments it clears.

    # Jev via OpenRouter (any TypeSafe endpoint works the same way)
    TYPESAFE_API_KEY=$OPENROUTER_API_KEY TYPESAFE_BASE_URL=https://openrouter.ai/api \\
      TYPESAFE_DEFAULT_MODEL=typesafe/jev-1.13 python eval/amend/run.py
    # Clef straight from Workers AI (what CI calls through the kypp Worker)
    python eval/amend/run.py --clef            # needs CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_AI_TOKEN
    python eval/amend/run.py --report eval/amend/results/<model>.jsonl
"""
import argparse
import gzip
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import urllib.request

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parents[1] / "src"))
from brief import s1  # noqa: E402
from brief.triage import MAX_DIFF_CHARS, REVIEW_THRESHOLD, _has_body  # noqa: E402

THRESHOLDS = (0.02, 0.05, 0.1, 0.2, 0.3, 0.5)
CASES = ROOT / "cases.jsonl.gz"


class Clef:
    """Workers AI's Clef behind the s1.Client protocol (the kypp Worker does the same in CI)."""

    def __init__(self, model: str = "clef"):
        self.model = model
        self.url = (f"https://api.cloudflare.com/client/v4/accounts/{os.environ['CLOUDFLARE_ACCOUNT_ID']}"
                    f"/ai/run/@cf/cloudflare/{model}")
        self.token = os.environ["CLOUDFLARE_AI_TOKEN"]

    def system_one(self, state, questions):
        body = json.dumps({"model": self.model, "state": state, "questions": questions}).encode()
        req = urllib.request.Request(self.url, body, {"Authorization": f"Bearer {self.token}",
                                                      "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            out = json.load(r)["result"]
        answers = {k: SimpleNamespace(**v) for k, v in out["answers"].items()}
        return SimpleNamespace(model=out.get("model") or self.model, answers=answers)


def score(cases: list[dict], out: Path, client, jobs: int) -> None:
    done = {r["id"] for r in _rows(out)} if out.exists() else set()
    todo = [c for c in cases if c["id"] not in done]

    def one(c):
        size = len(c["decision_change"]) + len(c["amendment"])
        if not _has_body(c["decision_change"]) or size > MAX_DIFF_CHARS:
            return c, None, "", "too large or empty: triage escalates without asking"
        a = s1.decide(s1.amendment_state(c["decision_change"], c["amendment"], "", c.get("governed", [])),
                      {"review": s1.review_question()}, via=client)
        model = next((x.model for x in (a or {}).values() if x.model), "")
        return c, s1.noul_p(a, "review"), model, ""

    with out.open("a") as f, ThreadPoolExecutor(jobs) as pool:
        for c, review, model, note in pool.map(one, todo):
            if review is None and not note:
                print(f"no answer for {c['id']}", file=sys.stderr)
                continue
            f.write(json.dumps({"id": c["id"], "source": c["source"], "category": c["category"],
                                "escalate": c["escalate"], "review": review,
                                "model": model, "note": note}) + "\n")
            f.flush()


def _rows(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text().splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _auto(r: dict, t: float) -> bool:
    return r["review"] is not None and r["review"] < t


def report(rows: list[dict], label: str) -> str:
    bad = [r for r in rows if r["escalate"]]
    good = [r for r in rows if not r["escalate"]]
    lines = [f"{label}: {len(rows)} amendments ({len(bad)} a human should see, {len(good)} harmless)", "",
             "| auto-ratify when p < | should-see auto-ratified (misses) | harmless auto-ratified |",
             "|---|---|---|",
             f"| (no model: all escalate) | 0/{len(bad)} | 0/{len(good)} |"]
    for t in THRESHOLDS:
        miss = sum(_auto(r, t) for r in bad)
        ok = sum(_auto(r, t) for r in good)
        mark = " (shipped)" if t == REVIEW_THRESHOLD else ""
        lines.append(f"| {t}{mark} | {miss}/{len(bad)} | {ok}/{len(good)} ({ok / max(len(good), 1):.0%}) |")
    lines += ["", "| category | n | should see | median p | auto at the shipped threshold |", "|---|---|---|---|---|"]
    for cat in sorted({r["category"] for r in rows}):
        rs = [r for r in rows if r["category"] == cat]
        ps = sorted(r["review"] for r in rs if r["review"] is not None)
        med = f"{ps[len(ps) // 2]:.3f}" if ps else "n/a"
        auto = sum(_auto(r, REVIEW_THRESHOLD) for r in rs)
        lines.append(f"| {cat} | {len(rs)} | {'yes' if rs[0]['escalate'] else 'no'} | {med} | {auto}/{len(rs)} |")
    scored = sorted((r for r in bad if r["review"] is not None), key=lambda r: r["review"])
    if scored:
        lines += ["", "Lowest should-see: " + ", ".join(f"{r['id']} ({r['review']:.3f})" for r in scored[:3])]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clef", nargs="?", const="clef", help="score Clef (or clef-flash) on Workers AI")
    ap.add_argument("--report", type=Path)
    ap.add_argument("--jobs", type=int, default=8)
    args = ap.parse_args()
    if args.report:
        print(report(_rows(args.report), args.report.stem))
        return
    cases = [json.loads(ln) for ln in gzip.open(CASES, "rt")]
    client = Clef(args.clef) if args.clef else s1.client()
    if client is None:
        sys.exit("no model: set TYPESAFE_API_KEY (and brief[s1]), or pass --clef")
    name = args.clef or s1.model_name()
    out = ROOT / "results" / f"{name.replace('/', '_')}.jsonl"
    out.parent.mkdir(exist_ok=True)
    score(cases, out, client, args.jobs)
    print(report(_rows(out), name))


if __name__ == "__main__":
    main()
