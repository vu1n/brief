"""Experiment: ask the one question we care about, "does this need the owner's eyes?", instead of fiat + impact.

    python eval/amend/review_question.py clef        # or jev, with the TYPESAFE_* env set
"""
import gzip, json, sys, os
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, "/home/user/brief/src"); sys.path.insert(0, "/home/user/brief/eval/amend")
from brief import s1
from run import Clef, MAX_DIFF_CHARS, _has_body
Q = {"type": "noul",
     "instructions": ("The state holds an edit to a ratified engineering decision, the amendment that argues "
                      "for it, and the paths the decision governs. The repo owner reviews decision changes only "
                      "when it matters, to avoid rubber-stamping. Should this change wait for the owner's eyes "
                      "before it merges, rather than being approved automatically?"),
     "criteria": {"true": "A careful owner would want to look first: the change drops, loosens, retires or "
                          "carves an exception into a rule, moves an authority, access or security boundary, "
                          "or changes the decision's direction, however it is framed.",
                  "false": "A careful owner would wave it through unread: it rewords, adds an example, records "
                           "what was built without loosening anything, or makes a rule stricter."}}
which = sys.argv[1]
client = Clef("clef") if which == "clef" else s1.client()
cases = [json.loads(l) for l in gzip.open("/home/user/brief/eval/amend/cases.jsonl.gz", "rt")]
def one(c):
    if not _has_body(c["decision_change"]) or len(c["decision_change"]) + len(c["amendment"]) > MAX_DIFF_CHARS:
        return c, None
    a = s1.decide(s1.amendment_state(c["decision_change"], c["amendment"], "", c.get("governed", [])), {"review": Q}, via=client)
    return c, s1.noul_p(a, "review")
out = open(f"/home/user/brief/eval/amend/results/review-question/{which.replace('/','_')}.jsonl", "w")
for c, p in ThreadPoolExecutor(4).map(one, cases):
    out.write(json.dumps({"id": c["id"], "source": c["source"], "category": c["category"], "escalate": c["escalate"], "review": p}) + "\n")
