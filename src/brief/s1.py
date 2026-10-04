"""System One triage: typed, calibrated decisions from a decision model, via the TypeSafe API.

A System One model (Jev, Clef) is not an LLM. It takes a `state` plus typed questions
(`noul` = yes/no, `choice`, `score`) and returns calibrated probabilities, never text.
Brief uses it only to *triage* what reaches a human or an agent (which sign-offs to ask,
which candidates to ratify); it never decides a governance outcome.

Optional twice over: it needs the `typesafe-sdk` package (`brief[s1]`) and a key. The SDK's
own env vars configure it, so any TypeSafe-API-compatible endpoint works:
  TYPESAFE_API_KEY, TYPESAFE_BASE_URL (e.g. https://openrouter.ai/api), TYPESAFE_DEFAULT_MODEL.
BRIEF_S1=off disables it. Without it every caller gets None ("no opinion") and keeps the
mechanical rule.
"""
from __future__ import annotations

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


def client(env: Mapping[str, str] | None = None) -> Client | None:
    env = os.environ if env is None else env
    if env.get("BRIEF_S1", "").lower() in {"0", "off", "false", "no"} or not env.get("TYPESAFE_API_KEY"):
        return None
    try:
        from typesafe_sdk import TypeSafeClient
        return TypeSafeClient()
    except Exception:  # SDK not installed, or it rejected its config
        return None


def _answer(raw: Any) -> Answer | None:
    kind = getattr(raw, "type", None)
    if kind == "noul":
        return Answer("noul", float(raw.noul))
    probs = {str(k): float(v) for k, v in (getattr(raw, "probabilities", None) or {}).items()}
    if kind == "choice":
        return Answer("choice", float(raw.confidence), raw.choice, probs)
    if kind == "score":
        return Answer("score", float(raw.confidence), float(raw.score), probs)
    return None


def decide(state: Any, questions: Mapping[str, Any], *,
           via: Client | None = None) -> dict[str, Answer] | None:
    """Ask every question about `state` in one call. Returns None when System One is
    unavailable or the call fails, and drops answers it can't read: callers must treat a
    missing answer as "no opinion", never as "no"."""
    c = via or client()
    if c is None:
        return None
    try:
        answers = c.system_one(state, dict(questions)).answers
        out = {k: a for k, raw in answers.items() if k in questions and (a := _answer(raw))}
    except Exception:
        return None
    return out or None


# --- The questions brief asks. Criteria describe situations, not degrees (TypeSafe guidance). ---

def conflict_state(decision: str, diff: str) -> dict:
    return {"decision": decision, "diff": diff}


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
