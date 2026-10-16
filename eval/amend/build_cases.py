"""Assemble the labeled amendment set (cases.jsonl.gz) from two sources.

    python eval/amend/build_real.py <pillbox> <kypp> > real_raw.jsonl   # then label by hand
    python eval/amend/build_cases.py real.jsonl.gz synthetic_spec.jsonl.gz | gzip -9n > eval/amend/cases.jsonl.gz

- real: every archived amendment in pillbox and kypp, labeled by hand (see README for the rule).
- synthetic: five variants per decision (clarify, tighten, disguised-reversal, loophole,
  plain-reversal), each a one-block replacement of the decision's current text; the label
  comes from the variant.
"""
import difflib
import gzip
import json
import sys
from pathlib import Path

import yaml


def governed(path: Path) -> list[str]:
    text = path.read_text()
    try:
        return list(yaml.safe_load(text.split("---")[1]).get("related_code") or [])
    except Exception:
        return []


real, synthetic = (Path(p) for p in sys.argv[1:3])
read = lambda p: (gzip.open(p, "rt") if p.suffix == ".gz" else p.open()).read()
for line in read(real).splitlines():
    r = json.loads(line)
    repo = "/home/user/" + r["id"].split("/")[0]
    doc = Path(repo, ".brief/docs", f"{r['doc']}.md")
    r["governed"] = governed(doc) if doc.exists() else []
    print(json.dumps(r))
for line in read(synthetic).splitlines():
    s = json.loads(line)
    path = Path(s["path"])
    old = path.read_text()
    assert old.count(s["old"]) == 1, s["id"]
    new = old.replace(s["old"], s["new"])
    name = f"{path.stem}.md"
    diff = "".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True), f"a/{name}", f"b/{name}"))
    print(json.dumps({"id": s["id"], "doc": path.stem, "source": "synthetic", "category": s["category"],
                      "escalate": s["escalate"], "decision_change": diff, "amendment": s["amendment"],
                      "governed": governed(path)}))
