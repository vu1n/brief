"""Score a System One model on labeled amendments: can it tell CI which ones to ratify by merging?

`brief triage --amendments` asks two noul questions (reversal/fiat, high impact) and CI
auto-ratifies only when both sit below FIAT_THRESHOLD/IMPACT_THRESHOLD. The failure that
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
from brief.triage import FIAT_THRESHOLD, IMPACT_THRESHOLD, MAX_DIFF_CHARS, _has_body  # noqa: E402

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
            return c, None, None, "", "too large or empty: triage escalates without asking"
        a = s1.decide(s1.amendment_state(c["decision_change"], c["amendment"], "", c.get("governed", [])),
                      {"fiat": s1.fiat_question(), "impact": s1.impact_question()}, via=client)
        model = next((x.model for x in (a or {}).values() if x.model), "")
        return c, s1.noul_p(a, "fiat"), s1.noul_p(a, "impact"), model, ""

    with out.open("a") as f, ThreadPoolExecutor(jobs) as pool:
        for c, fiat, impact, model, note in pool.map(one, todo):
            if (fiat is None or impact is None) and not note:
                print(f"no answer for {c['id']}", file=sys.stderr)
                continue
            f.write(json.dumps({"id": c["id"], "source": c["source"], "category": c["category"],
                                "escalate": c["escalate"], "fiat": fiat, "impact": impact,
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


def _auto(r: dict, t_fiat: float, t_impact: float) -> bool:
    return r["fiat"] is not None and r["impact"] is not None and r["fiat"] < t_fiat and r["impact"] < t_impact


def report(rows: list[dict], label: str) -> str:
    bad = [r for r in rows if r["escalate"]]
    good = [r for r in rows if not r["escalate"]]
    lines = [f"{label}: {len(rows)} amendments ({len(bad)} a human should see, {len(good)} harmless)", "",
             "| auto-ratify when both p < | should-see auto-ratified (misses) | harmless auto-ratified |",
             "|---|---|---|",
             f"| (no model: all escalate) | 0/{len(bad)} | 0/{len(good)} |"]
    for t in THRESHOLDS:
        miss = sum(_auto(r, t, t) for r in bad)
        ok = sum(_auto(r, t, t) for r in good)
        mark = " (shipped)" if t == FIAT_THRESHOLD == IMPACT_THRESHOLD else ""
        lines.append(f"| {t}{mark} | {miss}/{len(bad)} | {ok}/{len(good)} ({ok / max(len(good), 1):.0%}) |")
    lines += ["", "| category | n | should see | median fiat | median impact | auto at shipped thresholds |",
              "|---|---|---|---|---|---|"]
    for cat in sorted({r["category"] for r in rows}):
        rs = [r for r in rows if r["category"] == cat]
        med = lambda k: (sorted(x[k] for x in rs if x[k] is not None) or [None])[len([x for x in rs if x[k] is not None]) // 2]
        fmt = lambda v: "n/a" if v is None else f"{v:.3f}"
        auto = sum(_auto(r, FIAT_THRESHOLD, IMPACT_THRESHOLD) for r in rs)
        lines.append(f"| {cat} | {len(rs)} | {'yes' if rs[0]['escalate'] else 'no'} | {fmt(med('fiat'))} | "
                     f"{fmt(med('impact'))} | {auto}/{len(rs)} |")
    misses = [r for r in bad if _auto(r, FIAT_THRESHOLD, IMPACT_THRESHOLD)]
    if misses:
        lines += ["", "Misses at the shipped thresholds: " + ", ".join(
            f"{r['id']} ({r['fiat']:.3f}/{r['impact']:.3f})" for r in misses)]
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
