"""Copied into K/MK workspaces as tests/test_rules.py: one test per `# Rule:` comment.

Each test checks the rule on the code as it stands, the way a repo would enforce an
invariant (pillbox's do_usage_policy.test.mjs is the model). None of them is a hidden
task test: they know nothing about the files or functions a task adds by name.
"""
import logging
import re
from datetime import timezone
from pathlib import Path

import pytest

from ledger.config import Config, load
from ledger.entries import Ledger
from ledger.money import Money

PKG = Path(__file__).resolve().parent.parent / "ledger"


def _code(path: Path) -> str:
    """A module's code with comments and docstring lines dropped."""
    out = []
    for ln in path.read_text().splitlines():
        code = ln.split("#", 1)[0]
        if code.strip() and not code.strip().startswith(('"', "'")):
            out.append(code)
    return "\n".join(out)


def _modules():
    return sorted(PKG.glob("*.py"))


def test_rule_money():
    with pytest.raises(TypeError):
        Money(1.5)
    assert Money.from_str("0.29") == Money(29)
    for m in _modules():
        assert "float(" not in _code(m), f"{m.name} converts an amount through float"


def test_rule_config(tmp_path, monkeypatch):
    for f in Config.__dataclass_fields__:
        monkeypatch.setenv(f"LEDGER_{f.upper()}", "from-env")
    cfg = load(tmp_path / "missing.toml")
    assert cfg == Config(), "a LEDGER_* environment variable changed a setting"


def test_rule_retry():
    for m in _modules():
        if m.name in ("http.py", "reports.py"):
            continue
        assert "legacy_retry" not in _code(m), f"{m.name} calls legacy_retry"


def test_rule_time():
    assert Ledger().post("a", Money(1)).posted_at.tzinfo is timezone.utc
    for m in _modules():
        assert not re.search(r"datetime\.now\(\s*\)", _code(m)), f"{m.name} uses naive local time"


def test_rule_rounding():
    for m in _modules():
        code = _code(m)
        assert "ROUND_HALF_EVEN" not in code and not re.search(r"\bround\(", code), (
            f"{m.name} uses banker's rounding")


def test_rule_pii(caplog):
    caplog.set_level(logging.DEBUG, logger="ledger")
    Ledger().post("acct-12345", Money(100))
    for r in caplog.records:
        seen = r.getMessage() + " " + " ".join(map(str, vars(r).values()))
        assert "acct-12345" not in seen, "a log record carries a raw account id"
