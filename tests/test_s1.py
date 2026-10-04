"""System One triage: optional, and fails to "no opinion". A fake client stands in for the
TypeSafe SDK (same answer fields), so the suite needs neither the SDK nor a key."""
import sys
from types import SimpleNamespace as NS

from brief import s1

Q = {"is_bug": {"type": "noul"}, "team": {"type": "choice", "criteria": {}}}
NOUL = NS(type="noul", noul=0.96)
CHOICE = NS(type="choice", choice="payments", confidence=0.67,
            probabilities={"payments": 0.78, "frontend": 0.22})


class Fake:
    def __init__(self, answers=None, error=None):
        self.answers, self.error, self.calls = answers, error, []

    def system_one(self, state, questions):
        self.calls.append((state, questions))
        if self.error:
            raise self.error
        return NS(answers=self.answers)


def test_optional_without_key_or_sdk(monkeypatch):
    assert s1.client({}) is None
    assert s1.client({"TYPESAFE_API_KEY": "k", "BRIEF_S1": "off"}) is None
    monkeypatch.setitem(sys.modules, "typesafe_sdk", None)  # SDK not installed
    assert s1.client({"TYPESAFE_API_KEY": "k"}) is None
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    assert s1.decide({}, Q) is None


def test_decide_reads_typed_answers():
    fake = Fake({"is_bug": NOUL, "team": CHOICE})
    a = s1.decide({"ticket": "blank screen"}, Q, via=fake)
    assert a["is_bug"].p == 0.96
    assert a["team"].value == "payments" and a["team"].p == 0.67
    assert fake.calls == [({"ticket": "blank screen"}, Q)]


def test_decide_fails_to_none_never_to_no():
    assert s1.decide({}, Q, via=Fake(error=OSError("down"))) is None
    assert s1.decide({}, Q, via=Fake({})) is None
    # An answer of an unknown type is dropped (no opinion), not read as p=0.
    a = s1.decide({}, Q, via=Fake({"is_bug": NS(type="mystery"), "team": CHOICE}))
    assert set(a) == {"team"}
