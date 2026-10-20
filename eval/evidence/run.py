"""Does a model earn a place in `brief evidence`? Two live probes, on real decisions.

    python eval/evidence/run.py impact  --pillbox ../pillbox          # Clef: which other decisions does an edit undermine?
    python eval/evidence/run.py clairic --pillbox ../pillbox --kypp ../kypp   # Clairic: rule/exceptions/reason
    python eval/evidence/run.py impact  --report                      # re-print from results/

Both call Workers AI directly (CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_AI_TOKEN). CI's Clef goes
through the kypp Worker; same model.
"""
import argparse
import difflib
import gzip
import json
import os
import re
import statistics as st
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parents[1] / "src"))
from brief import gitutil, s1  # noqa: E402
from brief.docs import glob_match, load_index  # noqa: E402
from brief.evidence import MODEL_SHOW, MODEL_TOP, _impact_state, impact_question  # noqa: E402
from brief.features import is_feature_map  # noqa: E402
from brief.refs import find_refs  # noqa: E402


def _clef_client():
    """eval/amend's Workers AI Clef behind s1.Client (what the kypp Worker serves in CI)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("amend_run", ROOT.parent / "amend" / "run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.Clef()


def _decisions(repo: Path) -> dict:
    return {d.doc_id: d for d in load_index(repo / ".brief") if not is_feature_map(d)}


def _linked(ds: dict, files: list[str]) -> dict[str, set[str]]:
    """What `brief evidence` links without a model: refs either way, shared governed files."""
    gov = {k: {f for f in files if any(glob_match(g, f) for g in d.related_code)} for k, d in ds.items()}
    refs = {k: {r.doc_id for r in find_refs(d.path.read_text())} - {k} for k, d in ds.items()}
    return {a: {b for b in ds if b != a and (gov[a] & gov[b] or b in refs[a] or a in refs[b])} for a in ds}


def _edit(d, old: str, new: str) -> str:
    body = d.anchors[0].body.splitlines()
    i = next(n for n, ln in enumerate(body) if old in ln)
    after = body[:i] + [new] + body[i + 1:]
    return "".join(difflib.unified_diff([x + "\n" for x in body], [x + "\n" for x in after],
                                        f"a/{d.doc_id}", f"b/{d.doc_id}", n=2))


def impact(pillbox: Path, out: Path) -> None:
    ds = _decisions(pillbox)
    cases = json.loads((ROOT / "cases.json").read_text())
    client = _clef_client()

    def ask(job):
        c, b = job
        t = time.time()
        a = s1.decide(_impact_state(_edit(ds[c["doc"]], c["old"], c["new"]), ds[b]),
                      {"undermines": impact_question()}, via=client)
        return {"case": c["id"], "other": b, "p": s1.noul_p(a, "undermines"), "latency": time.time() - t}

    jobs = [(c, b) for c in cases for b in ds if b != c["doc"]]
    with ThreadPoolExecutor(8) as ex:
        rows = list(ex.map(ask, jobs))
    linked = _linked(ds, gitutil.tracked_files(pillbox))
    out.write_text(json.dumps({"cases": [{**c, "linked": sorted(linked[c["doc"]])} for c in cases],
                               "scores": rows}, indent=1))


def impact_report(path: Path) -> str:
    data = json.loads(path.read_text())
    cases = {c["id"]: c for c in data["cases"]}
    by: dict = {}
    for r in data["scores"]:
        by.setdefault(r["case"], {})[r["other"]] = r["p"]
    pos = sum(len(c["affected"]) for c in cases.values())
    harmless = [k for k, c in cases.items() if not c["affected"]]
    missing = sum(r["p"] is None for r in data["scores"])
    lat = st.median(r["latency"] for r in data["scores"])

    def policy(k, t):
        shown = hit = extra_harmless = 0
        for cid, c in cases.items():
            L = set(c["linked"])
            add = [b for b, p in sorted(by[cid].items(), key=lambda x: -(x[1] or 0))
                   if p is not None and p >= t and b not in L][:k]
            S = L | set(add)
            shown += len(S)
            hit += len(S & set(c["affected"]))
            extra_harmless += len(add) if cid in harmless else 0
        return shown, hit, extra_harmless

    rows = [f"{len(cases)} edits x {len(by[next(iter(by))])} other decisions, {len(data['scores'])} Clef calls "
            f"({missing} unanswered), median latency {lat:.2f}s; {pos} affected pairs labeled\n",
            "| what the reviewer is shown | decisions listed | affected found "
            "| model additions on the 5 edits with no labeled impact |",
            "|---|---|---|---|"]
    s, h, _ = policy(0, 1.1)
    rows.append(f"| links only (refs + shared files) | {s} | {h}/{pos} | n/a |")
    for k, t in [(2, 0.5), (MODEL_TOP, MODEL_SHOW), (5, 0.3), (24, 0.3)]:
        s, h, x = policy(k, t)
        rows.append(f"| links + Clef top {k} unlinked at p>={t} | {s} | {h}/{pos} | {x} |")
    rows.append("\nPer edit: rank of each affected decision among the 24 by Clef p; max p on harmless edits.")
    for cid, c in cases.items():
        r = [b for b, _ in sorted(by[cid].items(), key=lambda x: -(x[1] or 0))]
        ranks = [r.index(a) + 1 for a in c["affected"]]
        top = max(p or 0 for p in by[cid].values())
        rows.append(f"- {cid} `{c['doc']}`: affected ranks {ranks or '-'}, linked {len(c['linked'])}, max p {top:.2f}")
    return "\n".join(rows)


# --- Clairic ------------------------------------------------------------------------------

FIELDS = {
    "rule": {"type": "text", "instructions": "The main constraint this decision imposes on the code, as written."},
    "exceptions": {"type": "list", "items": "text",
                   "instructions": "Exceptions, carve-outs or conditions under which the rule does not apply, as written."},
    "reason": {"type": "text", "instructions": "The reason the decision gives for the rule."},
    "assumptions": {"type": "list", "items": "text", "instructions": "Facts or conditions the decision relies on staying true."},
}
EXCEPTION_RE = re.compile(r"\b(except|unless|other than|but not|only when|only if)\b", re.IGNORECASE)


def _clairic(state: str) -> dict:
    url = (f"https://api.cloudflare.com/client/v4/accounts/{os.environ['CLOUDFLARE_ACCOUNT_ID']}"
           f"/ai/run/@cf/cloudflare/clairic")
    req = urllib.request.Request(url, json.dumps({"model": "clairic", "state": state, "fields": FIELDS}).encode(),
                                 {"Authorization": f"Bearer {os.environ['CLOUDFLARE_AI_TOKEN']}",
                                  "Content-Type": "application/json"})
    t = time.time()
    with urllib.request.urlopen(req, timeout=120) as r:
        out = json.load(r)["result"]
    return {**out, "latency": time.time() - t}


def _sentences(body: str) -> list[str]:
    text = re.sub(r"```.*?```", " ", body, flags=re.S)
    out = []
    for para in re.split(r"\n\s*\n", text):
        para = " ".join(ln.strip().lstrip("-*> ").strip() for ln in para.splitlines() if not ln.lstrip().startswith("#"))
        out += [s.strip() for s in re.split(r"(?<=[.;!?])\s+(?=[A-Z`*(])", para) if len(s.split()) >= 3]
    return out


def clairic(repos: list[Path], out: Path) -> None:
    anchors = [(d.doc_id, a.body) for repo in repos for d in _decisions(repo).values() for a in d.anchors]
    with ThreadPoolExecutor(6) as ex:
        rows = list(ex.map(lambda x: {"doc": x[0], "body": x[1], "out": _clairic(x[1])}, anchors))
    out.write_bytes(gzip.compress(json.dumps(rows, indent=1).encode(), mtime=0))


def clairic_report(path: Path) -> str:
    res = json.loads(gzip.decompress(path.read_bytes()))
    lat = [r["out"]["latency"] for r in res]
    L = [f"{len(res)} decision anchors, median latency {st.median(lat):.2f}s (max {max(lat):.2f}s), "
         f"{sum(r['out']['usage']['input_tokens'] for r in res)} input tokens, "
         f"{sum(r['out']['truncated'] for r in res)} truncated\n"]
    for k in ("rule", "reason"):
        vals = [(r, r["out"]["answers"][k]) for r in res]
        nn = [(r, v) for r, v in vals if v["value"] is not None]
        valid = sum(r["body"][v["span"][0]:v["span"][1]] == v["value"] for r, v in nn)
        whole = sum(any(v["value"].strip(" .*") == s.strip(" .*") or
                        (len(v["value"]) >= 0.9 * len(s) and v["value"][:20] in s) for s in _sentences(r["body"]))
                    for r, v in nn)
        L.append(f"- `{k}`: {len(nn)}/{len(res)} answered, span matches source {valid}/{len(nn)}, "
                 f"a whole sentence {whole}/{len(nn)}, median {st.median(len(v['value'].split()) for _, v in nn)} words, "
                 f"median confidence {st.median(v['confidence'] for _, v in nn):.2f}")
    for k in ("exceptions", "assumptions"):
        items = frag = misaligned = 0
        for r in res:
            v = r["out"]["answers"][k]
            items += len(v["value"] or [])
            frag += sum(len(x.split()) <= 3 for x in v["value"] or [])
            misaligned += len(v["value"] or []) != len(v.get("spans") or [])
        L.append(f"- `{k}`: {items} items, {frag} are 3 words or fewer, {misaligned}/{len(res)} answers have "
                 f"a different number of spans than values")
    es = [(r, s) for r in res for s in _sentences(r["body"]) if EXCEPTION_RE.search(s)]
    hit = sum(any(len(i.split()) > 3 and i in s for i in (r["out"]["answers"]["exceptions"]["value"] or []))
              for r, s in es)
    L.append(f"- sentences with an explicit exception word (except, unless, only if...): {len(es)}; "
             f"Clairic returned a 4+ word exception inside {hit} of them")
    return "\n".join(L)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("probe", choices=["impact", "clairic"])
    ap.add_argument("--pillbox", type=Path)
    ap.add_argument("--kypp", type=Path)
    ap.add_argument("--report", action="store_true", help="only re-print the saved results")
    a = ap.parse_args()
    out = ROOT / "results" / ("impact.json" if a.probe == "impact" else "clairic.json.gz")
    if not a.report:
        if a.probe == "impact":
            impact(a.pillbox.resolve(), out)
        else:
            clairic([p.resolve() for p in (a.pillbox, a.kypp) if p], out)
    print(impact_report(out) if a.probe == "impact" else clairic_report(out))


if __name__ == "__main__":
    main()
