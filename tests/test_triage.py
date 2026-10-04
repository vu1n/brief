"""`brief triage`: a System One verdict below the threshold writes the conforms line; the
gate itself never consults the model. A fake client stands in for the TypeSafe SDK."""
from types import SimpleNamespace as NS

from brief.gate import check
from brief.triage import triage

from tests.test_signoff import _git, _needs, _repo

ADD_POST = ('"GET", "PUT"', '"GET", "PUT", "POST"')


class Fake:
    def __init__(self, p=None):
        self.p, self.calls = p, []

    def system_one(self, state, questions):
        self.calls.append(state)
        if self.p is None:
            raise OSError("down")
        return NS(answers={"conflict": NS(type="noul", noul=self.p)})


def _stage_edit(repo):
    p = repo / "src" / "retry.py"
    p.write_text(p.read_text().replace(*ADD_POST))
    _git(repo, "add", "-A")


def test_confident_conforming_ask_is_cleared_and_recorded(tmp_path):
    repo = _repo(tmp_path)
    _stage_edit(repo)
    fake = Fake(p=0.03)
    [v] = triage(repo, repo / ".brief", via=fake)
    assert v.anchor_id == "idempotent-only" and v.cleared and v.p == 0.03
    line = (repo / ".brief" / "SIGNOFF").read_text()
    assert line.startswith("idempotent-only conforms: (s1 ") and "p=0.03" in line
    assert check(repo, repo / ".brief") == []  # staged for the gate
    assert "Retry idempotent calls only" in fake.calls[0]["decision"]
    assert '"POST"' in fake.calls[0]["diff"]


def test_likely_violation_keeps_its_ask(tmp_path):
    repo = _repo(tmp_path)
    _stage_edit(repo)
    [v] = triage(repo, repo / ".brief", via=Fake(p=0.6))
    assert not v.cleared and v.p == 0.6
    assert not (repo / ".brief" / "SIGNOFF").exists()
    assert _needs(check(repo, repo / ".brief")) == {"idempotent-only"}


def test_no_model_opinion_keeps_its_ask(tmp_path):
    repo = _repo(tmp_path)
    _stage_edit(repo)
    [v] = triage(repo, repo / ".brief", via=Fake(p=None))
    assert v.p is None and not v.cleared
    assert _needs(check(repo, repo / ".brief")) == {"idempotent-only"}


def test_nothing_to_triage_never_calls_the_model(tmp_path):
    repo = _repo(tmp_path, signoff=False)
    _stage_edit(repo)
    fake = Fake(p=0.0)
    assert triage(repo, repo / ".brief", via=fake) == [] and fake.calls == []


def test_range_mode_writes_but_leaves_commit_to_the_caller(tmp_path):
    repo = _repo(tmp_path)
    _git(repo, "branch", "base")
    _stage_edit(repo)
    _git(repo, "commit", "-qm", "edit")
    [v] = triage(repo, repo / ".brief", base="base", via=Fake(p=0.05))
    assert v.cleared
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "signoff")
    assert check(repo, repo / ".brief", base="base") == []
