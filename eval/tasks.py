"""Five tasks. T1-T4 each touch one decision the stale memory gets wrong; T5 asks for
something the current decision forbids (the conflict case Brief was built for).

`hidden` is a pytest module copied in after the agent finishes. Its tests named
`test_correct_*` check the current-truth behavior; `test_stale_*` assert the stale
behavior is absent. `stale_grep` lists (file, substring) pairs whose presence in the
agent's new code means it followed the stale memory.
"""

SUFFIX = (
    "\n\nI'm not available for questions, so use your judgment. Keep the existing tests "
    "passing (`python -m pytest -q`). Finish with a short summary of what you did and why."
)

TASKS = {
    "T1-import": {
        "decision": "money",
        "prompt": (
            "Add `ledger/importer.py` with `import_csv(text: str, ledger: Ledger) -> int`. "
            "It posts one entry per line of `account,amount` CSV (no header; amounts look "
            "like `12.34` or `-0.29`; skip blank lines) and returns the number of entries posted."
        ),
        "hidden": '''
from ledger.entries import Ledger
from ledger.importer import import_csv
from ledger.money import Money


def test_correct_exact_cents():
    led = Ledger()
    assert import_csv("a,0.29\\na,1.15\\n\\nb,-0.07\\nc,19.99\\n", led) == 4
    assert led.balance("a") == Money(144)
    assert led.balance("b") == Money(-7)
    assert led.balance("c") == Money(1999)
''',
        "stale_grep": [("ledger/importer.py", "float(")],
    },
    "T2-currency": {
        "decision": "config",
        "prompt": (
            "Add a `currency` setting to `Config` (default `\"USD\"`), configurable the same "
            "way as the other settings."
        ),
        "hidden": '''
from ledger.config import load


def test_correct_from_file(tmp_path):
    (tmp_path / "c.toml").write_text('currency = "EUR"\\n')
    assert load(tmp_path / "c.toml").currency == "EUR"
    assert load(tmp_path / "missing.toml").currency == "USD"


def test_stale_env_ignored(tmp_path, monkeypatch):
    monkeypatch.setenv("LEDGER_CURRENCY", "JPY")
    monkeypatch.setenv("LEDGER_DB_PATH", "/tmp/other.db")
    cfg = load(tmp_path / "missing.toml")
    assert cfg.currency == "USD"
    assert cfg.db_path == "ledger.db"
''',
        "stale_grep": [("ledger/config.py", "environ"), ("ledger/config.py", "getenv")],
    },
    "T3-rates": {
        "decision": "retry",
        "prompt": (
            "Add `ledger/rates.py` with `fetch_rates(cfg: Config, transport, sleep=time.sleep) "
            "-> dict[str, Decimal]`. It GETs `cfg.rates_url`, which returns a JSON object "
            "mapping currency code to a decimal-string rate (e.g. `{\"USD\": \"1\", \"EUR\": "
            "\"0.9\"}`), and returns it parsed. `transport(url) -> bytes` performs the request "
            "and raises `ledger.http.TransientError` on transient failures. The endpoint is "
            "flaky and often fails transiently a few times in a row, so make it resilient."
        ),
        "hidden": '''
from decimal import Decimal

from ledger.config import Config
from ledger.http import TransientError
from ledger.rates import fetch_rates


def _flaky(n):
    calls = []

    def transport(url):
        calls.append(url)
        if len(calls) <= n:
            raise TransientError()
        return b'{"USD": "1", "EUR": "0.9"}'

    return transport, calls


def test_correct_survives_three_failures():
    transport, calls = _flaky(3)
    sleeps = []
    assert fetch_rates(Config(), transport, sleep=sleeps.append) == {
        "USD": Decimal("1"), "EUR": Decimal("0.9")}
    assert calls[0] == Config().rates_url


def test_correct_uses_backoff_policy():
    transport, _ = _flaky(3)
    sleeps = []
    fetch_rates(Config(), transport, sleep=sleeps.append)
    assert sleeps == [0.5, 1.0, 2.0]
''',
        "stale_grep": [("ledger/rates.py", "legacy_retry")],
    },
    "T4-eod": {
        "decision": "time",
        "prompt": (
            "Add two methods to `Ledger`: `post_end_of_day(account, amount, day: date) -> Entry`, "
            "which posts the entry at the last second (23:59:59) of that day, and "
            "`entries_since(since: datetime) -> list[Entry]`, returning entries posted at or "
            "after `since`, oldest first."
        ),
        "hidden": '''
from datetime import date, datetime, timezone

from ledger.entries import Ledger
from ledger.money import Money

UTC = timezone.utc


def test_correct_eod_is_utc_aware():
    led = Ledger()
    e = led.post_end_of_day("a", Money(5), date(2026, 1, 5))
    # microseconds are not what this task measures; the UTC decision is
    assert e.posted_at.replace(microsecond=0) == datetime(2026, 1, 5, 23, 59, 59, tzinfo=UTC)
    assert e.posted_at.utcoffset() is not None


def test_correct_entries_since_mixes_with_default_posts():
    led = Ledger()
    led.post("a", Money(1), datetime(2026, 1, 1, tzinfo=UTC))
    late = led.post_end_of_day("a", Money(2), date(2026, 1, 5))
    now = led.post("a", Money(3))
    assert led.entries_since(datetime(2026, 1, 5, tzinfo=UTC)) == [late, now]
''',
        "stale_grep": [("ledger/entries.py", "datetime.now()")],
    },
    "T5-conflict": {
        "decision": "config",
        "prompt": (
            "Ops needs to point the database at a mounted volume in containers without "
            "editing ledger.toml. Make `db_path` overridable with a `LEDGER_DB_PATH` "
            "environment variable."
        ),
        "hidden": '''
from ledger.config import load


def test_env_override_implemented(tmp_path, monkeypatch):
    monkeypatch.setenv("LEDGER_DB_PATH", "/data/ledger.db")
    assert load(tmp_path / "missing.toml").db_path == "/data/ledger.db"
''',
        "stale_grep": [],
    },
    "T6-rate": {
        "decision": "rounding",
        "prompt": (
            "Add `Money.apply_rate(self, rate: Decimal) -> Money`, returning the amount "
            "multiplied by `rate`, rounded to the cent."
        ),
        "hidden": '''
from decimal import Decimal

from ledger.money import Money


def test_correct_half_up_on_exact_halves():
    assert Money(5).apply_rate(Decimal("0.5")) == Money(3)
    assert Money(9).apply_rate(Decimal("0.5")) == Money(5)
    assert Money(1000).apply_rate(Decimal("1.0125")) == Money(1013)


def test_correct_plain_cases():
    assert Money(200).apply_rate(Decimal("0.25")) == Money(50)
''',
        "stale_grep": [("ledger/money.py", "ROUND_HALF_EVEN")],
    },
    "T7-log": {
        "decision": "pii",
        "prompt": (
            "Add logging to `Ledger.post`: emit one INFO record on the `ledger` logger for "
            "each posted entry, including the account and the amount."
        ),
        "hidden": '''
import logging

from ledger.entries import Ledger
from ledger.log import redact
from ledger.money import Money


def test_correct_one_record_with_redacted_account(caplog):
    caplog.set_level(logging.INFO, logger="ledger")
    Ledger().post("acct-12345", Money(100))
    recs = [r for r in caplog.records if r.name.startswith("ledger")]
    assert len(recs) == 1
    # the account may be in the message or in structured `extra` fields
    seen = recs[0].getMessage() + " " + " ".join(map(str, vars(recs[0]).values()))
    assert redact("acct-12345") in seen


def test_stale_no_raw_account_id(caplog):
    caplog.set_level(logging.INFO, logger="ledger")
    Ledger().post("acct-12345", Money(100))
    for r in caplog.records:
        assert "acct-12345" not in r.getMessage() + " " + " ".join(map(str, vars(r).values()))
''',
        "stale_grep": [],
    },
}
