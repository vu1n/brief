"""`brief triage`: a System One verdict below the threshold writes the conforms line; the
gate itself never consults the model. A fake client stands in for the TypeSafe SDK."""
import subprocess
from pathlib import Path
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
    status = subprocess.run(["git", "-C", str(repo), "status", "--porcelain"],
                            capture_output=True, text=True, check=True).stdout
    assert status.strip() == "?? .brief/SIGNOFF"  # written, not staged or committed
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "signoff")
    assert check(repo, repo / ".brief", base="base") == []


class Answers(Fake):
    """Replies with the given raw answer object for `conflict`."""

    def __init__(self, raw):
        super().__init__()
        self.raw = raw

    def system_one(self, state, questions):
        self.calls.append(state)
        return NS(model="m", answers={"conflict": self.raw})


def test_out_of_range_or_mistyped_answers_are_no_opinion(tmp_path):
    bad = [NS(type="noul", noul=x) for x in (-0.5, float("-inf"), float("nan"), 1.7)]
    bad.append(NS(type="score", score=0.0, confidence=0.03, probabilities={"0": 0.97, "1": 0.03}))
    for i, raw in enumerate(bad):
        repo = _repo(tmp_path / str(i))
        _stage_edit(repo)
        [v] = triage(repo, repo / ".brief", via=Answers(raw))
        assert v.p is None and not v.cleared, raw
        assert _needs(check(repo, repo / ".brief")) == {"idempotent-only"}


def test_shared_anchor_id_clears_only_if_every_doc_does(tmp_path):
    repo = _repo(tmp_path)
    other = (repo / ".brief" / "docs" / "retry.md").read_text().replace("id: retry", "id: other")
    (repo / ".brief" / "docs" / "other.md").write_text(other)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "second doc sharing anchor ids")
    _stage_edit(repo)

    class ByDoc(Fake):
        def system_one(self, state, questions):
            p = 0.02 if "retry.py" in state["diff"] and len(self.calls) == 0 else 0.95
            self.calls.append(state)
            return NS(model="m", answers={"conflict": NS(type="noul", noul=p)})

    vs = triage(repo, repo / ".brief", via=ByDoc())
    shared = [v for v in vs if v.anchor_id == "idempotent-only"]
    assert sorted(v.p for v in shared) == [0.02, 0.95]  # one doc alone would have cleared it
    assert not any(v.cleared for v in vs)
    assert not (repo / ".brief" / "SIGNOFF").exists()


def test_hidden_diff_attribute_neither_exempts_nor_blinds(tmp_path):
    repo = _repo(tmp_path)
    (repo / ".gitattributes").write_text("*.py -diff\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "attrs")
    _stage_edit(repo)
    assert _needs(check(repo, repo / ".brief")) == {"idempotent-only"}
    fake = Fake(p=0.6)
    triage(repo, repo / ".brief", via=fake)
    assert '+    allowed = {"GET", "PUT", "POST"}' in fake.calls[0]["diff"]


def test_range_mode_rerun_does_not_stack_lines(tmp_path):
    repo = _repo(tmp_path)
    _git(repo, "branch", "base")
    _stage_edit(repo)
    _git(repo, "commit", "-qm", "edit")
    for _ in range(2):
        triage(repo, repo / ".brief", base="base", via=Fake(p=0.05))
    assert (repo / ".brief" / "SIGNOFF").read_text().count("conforms") == 1


def test_staged_mode_stages_only_its_own_lines(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    (repo / ".brief" / "SIGNOFF").write_text("backoff conforms: wip, not reviewed\n")
    _stage_edit(repo)  # stages the wip line too...
    _git(repo, "reset", "-q", "--", ".brief/SIGNOFF")  # ...so unstage it again
    monkeypatch.chdir(repo)
    triage(repo, Path(".brief"), via=Fake(p=0.03))  # `--brief .brief`: relative, repo absolute
    staged = subprocess.run(["git", "-C", str(repo), "show", ":.brief/SIGNOFF"],
                            capture_output=True, text=True, check=True).stdout
    assert staged.startswith("idempotent-only conforms: (s1 ") and "wip" not in staged
    assert "wip" in (repo / ".brief" / "SIGNOFF").read_text()


def test_the_gate_never_imports_the_model():
    import ast

    import brief.gate as gate
    tree = ast.parse(Path(gate.__file__).read_text())
    names = {a.name for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))
             for a in n.names} | {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert not any("s1" in n or "triage" in n for n in names)


def test_gate_survives_a_binary_file_in_the_change(tmp_path):
    repo = _repo(tmp_path)
    (repo / "logo.png").write_bytes(bytes(range(256)) * 4)
    _stage_edit(repo)
    assert _needs(check(repo, repo / ".brief")) == {"idempotent-only"}
