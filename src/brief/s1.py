"""System One triage: typed, calibrated decisions from a decision model, via the TypeSafe API.

A System One model (Jev, Clef) is not an LLM. It takes a `state` plus typed questions
(`noul` = yes/no, `choice`, `score`) and returns calibrated probabilities, never text.
Brief uses it to *triage* what reaches a human or an agent: which sign-offs to ask, and
which amendments CI may ratify by merging (only when every answer rates them low-risk; the
rest escalate to a human). It never runs inside the gate, and a missing answer always
leaves the human path.

Optional twice over: it needs the `typesafe-sdk` package (`brief[s1]`) and a key. The SDK's
own env vars configure it, so any TypeSafe-API-compatible endpoint works:
  TYPESAFE_API_KEY, TYPESAFE_BASE_URL (e.g. https://openrouter.ai/api), TYPESAFE_DEFAULT_MODEL.
BRIEF_S1=off disables it. Without it every caller gets None ("no opinion") and keeps the
mechanical rule.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass
from typing import Any, Mapping, Protocol


class Client(Protocol):
    def system_one(self, state: Any, questions: Mapping[str, Any]) -> Any: ...


@dataclass(frozen=True)
class Answer:
    """One typed answer. `p` is P(yes) for noul and the model's confidence for choice/score;
    `value` is the chosen label or the probability-weighted score."""
    kind: str
    p: float
    value: Any = None
    probabilities: Mapping[str, float] | None = None
    model: str = ""  # the model that answered, as the endpoint reports it (not the alias)


def model_name(env: Mapping[str, str] | None = None) -> str:
    """The model the SDK will call; "jev-latest" is the SDK's own default."""
    return ((os.environ if env is None else env).get("TYPESAFE_DEFAULT_MODEL") or "").strip() or "jev-latest"


def client(env: Mapping[str, str] | None = None) -> Client | None:
    env = os.environ if env is None else env
    if env.get("BRIEF_S1", "").lower() in {"0", "off", "false", "no"} or not env.get("TYPESAFE_API_KEY"):
        return None
    try:
        from typesafe_sdk import TypeSafeClient
        return TypeSafeClient()
    except Exception:  # SDK not installed, or it rejected its config
        return None


def _prob(x: Any) -> float | None:
    # The SDK doesn't bound these: NaN, ±inf, or -0.5 must read as "no opinion", never as a
    # confident "no" that clears an ask.
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) and 0.0 <= x <= 1.0 else None


def _answer(raw: Any, model: str) -> Answer | None:
    kind = getattr(raw, "type", None)
    if kind == "noul":
        p = _prob(getattr(raw, "noul", None))
        return Answer("noul", p, model=model) if p is not None else None
    if kind not in ("choice", "score"):
        return None
    p = _prob(getattr(raw, "confidence", None))
    probs = {str(k): _prob(v) for k, v in (getattr(raw, "probabilities", None) or {}).items()}
    if p is None or None in probs.values():
        return None
    value = raw.choice if kind == "choice" else float(raw.score)
    return Answer(kind, p, value, probs, model)


def decide(state: Any, questions: Mapping[str, Any], *,
           via: Client | None = None) -> dict[str, Answer] | None:
    """Ask every question about `state` in one call. Returns None when System One is
    unavailable or the call fails, and drops answers it can't read: callers must treat a
    missing answer as "no opinion", never as "no"."""
    c = via or client()
    if c is None:
        return None
    try:
        reply = c.system_one(state, dict(questions))
        model = str(getattr(reply, "model", "") or "")
        out = {k: a for k, raw in reply.answers.items() if k in questions and (a := _answer(raw, model))}
    except Exception:
        return None
    return out or None


# --- The questions brief asks. Criteria describe situations, not degrees (TypeSafe guidance). ---

def conflict_state(decision: str, diff: str) -> dict:
    return {"decision": decision, "diff": diff}


def noul_p(answers: Mapping[str, Answer] | None, key: str) -> float | None:
    """P(yes) for a noul question, or None. An answer of another type to a noul question is
    not a probability of yes (its `p` is a confidence), so it is no opinion."""
    a = (answers or {}).get(key)
    return a.p if a is not None and a.kind == "noul" else None


def conflict_question() -> dict:
    """noul over `conflict_state`: does the diff cut against the decision? Feeds the
    sign-off filter."""
    return {
        "type": "noul",
        "instructions": (
            "The state holds a ratified engineering decision and a code diff. Does the diff "
            "do something the decision forbids, or stop doing something it requires?"
        ),
        "criteria": {
            "true": "The added code takes a path the decision rules out (the forbidden "
                    "approach, an override it removed, a bypass of the mandated mechanism).",
            "false": "The added code follows the decision or does not touch what it governs.",
        },
    }



def amendment_state(decision_diff: str, amendment: str, code_diff: str, governed: list[str]) -> dict:
    return {"decision_change": decision_diff, "amendment": amendment, "code_diff": code_diff,
            "governed_paths": list(governed)}


def fiat_question() -> dict:
    """noul over `amendment_state`: does the amendment reverse or weaken the decision, or
    rewrite it to fit the code (reversal-by-fiat)? Feeds amendment triage."""
    return {
        "type": "noul",
        "instructions": (
            "The state holds an edit to a ratified engineering decision, the amendment that "
            "argues for it, and the code change shipped with it. Does the edit reverse or "
            "weaken the decision's invariant, or rewrite the decision to fit this code?"
        ),
        "criteria": {
            "true": "The new text drops or loosens a rule the old text enforced, or restates "
                    "what the code diff does with no reason beyond the code needing it.",
            "false": "The new text keeps every rule the old text enforced (it clarifies, "
                     "tightens, or adds), for a reason that holds apart from this code.",
        },
    }


def impact_question() -> dict:
    """noul over `amendment_state`: does the amendment loosen anything high-impact? Feeds
    amendment triage. It asks about loosening, not about touching a sensitive area: the first
    wording rated every tightening of a security decision as high-impact, so nothing a
    person would have waved through ever auto-ratified (eval/amend)."""
    return {
        "type": "noul",
        "instructions": (
            "The state holds an edit to a ratified engineering decision, its amendment, the "
            "code change, and the paths the decision governs. Does this change loosen anything: "
            "widen authority, access or a security boundary, remove a guarantee callers rely "
            "on, or change behavior across many of the governed paths?"
        ),
        "criteria": {
            "true": "After the edit, something the old text forbade or limited is allowed, a "
                    "guarantee is gone, or behavior changes broadly.",
            "false": "The edit only rewords, gives an example, or makes a rule stricter or "
                     "narrower, even when the decision is about security, data or authority.",
        },
    }
