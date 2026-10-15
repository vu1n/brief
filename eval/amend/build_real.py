"""Collect every ratified amendment in a governed repo as an eval case (unlabeled).

    python eval/amend/build_real.py <repo> [<repo> ...] > real_raw.jsonl

Each case is the decision edit (previous published revision -> the one the amendment minted)
plus the archived amendment text, i.e. what `brief triage --amendments` would have seen,
minus the code diff (not recoverable per amendment).
"""
import difflib
import json
import re
import sys
from pathlib import Path

for repo in map(Path, sys.argv[1:]):
    docs = repo / ".brief/docs"
    owner = {}
    for d in docs.glob("*.md"):
        for a in re.findall(r"<!--\s*brief:anchor\s+([a-z0-9-]+)\s*-->", d.read_text()):
            owner[a] = d.stem
    for f in sorted((repo / ".brief/amendments/archive").glob("*.md")):
        m = re.match(r"(.+)-v(\d+)$", f.stem)
        anchor, rev = m.group(1), int(m.group(2))
        doc = owner.get(anchor) or next((s for s in owner.values() if s.endswith(anchor) or anchor in s), None)
        vdir = docs / (doc or "?") / "versions"
        old, new = vdir / f"v{rev - 1:04d}.md", vdir / f"v{rev:04d}.md"
        if not (old.exists() and new.exists()):
            print(f"skip {repo.name}/{f.stem}: no versions for {doc}", file=sys.stderr)
            continue
        diff = "".join(difflib.unified_diff(old.read_text().splitlines(True), new.read_text().splitlines(True),
                                            f"a/{doc}.md", f"b/{doc}.md"))
        print(json.dumps({"id": f"{repo.name}/{f.stem}", "doc": doc, "anchor": anchor,
                          "decision_change": diff, "amendment": f.read_text()}))
