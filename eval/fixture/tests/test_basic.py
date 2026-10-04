from datetime import datetime, timezone

import pytest

from ledger.config import Config, load
from ledger.entries import Ledger
from ledger.http import Client, RetryPolicy, TransientError
from ledger.money import Money


def test_money_parse_and_str():
    assert Money.from_str("12.34") == Money(1234)
    assert str(Money(-5)) == "-0.05"
    with pytest.raises(TypeError):
        Money(1.5)


def test_config_defaults(tmp_path):
    assert load(tmp_path / "missing.toml") == Config()
    (tmp_path / "c.toml").write_text('db_path = "x.db"\n')
    assert load(tmp_path / "c.toml").db_path == "x.db"


def test_client_retries():
    calls = []

    def flaky(url):
        calls.append(url)
        if len(calls) < 3:
            raise TransientError()
        return b"ok"

    sleeps = []
    assert Client(flaky, RetryPolicy(), sleeps.append).get("u") == b"ok"
    assert sleeps == [0.5, 1.0]


def test_ledger_balance():
    led = Ledger()
    led.post("a", Money(100), datetime(2026, 1, 1, tzinfo=timezone.utc))
    led.post("a", Money(-30))
    assert led.balance("a") == Money(70)
