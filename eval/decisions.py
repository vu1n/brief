"""The four decisions the fixture's code embodies, as data.

Each condition renders the SAME words: `summary` is the one-line code comment,
`body` is the full decision. Conditions differ only in where the words live and how
they are framed (plain editable docs vs Brief-governed decisions), never in content.
"""

DECISIONS = [
    {
        "key": "money",
        "anchor": "money-integer-cents",
        "title": "Money is integer cents",
        "related_code": ["ledger/money.py", "ledger/importer.py", "ledger/entries.py"],
        "summary": "Amounts are integer cents; parse text with Money.from_str, never through float.",
        "body": (
            "All amounts are `Money(cents: int)`. Parse user or file input with "
            "`Money.from_str`, which is exact. Never convert through `float` "
            "(e.g. `int(float(x) * 100)`): 0.29 * 100 == 28.999..., which silently "
            "loses a cent. We switched from float amounts in v0.4 after reconciliation "
            "drift; float-based code is a bug."
        ),
    },
    {
        "key": "config",
        "anchor": "config-file-only",
        "title": "Configuration comes from ledger.toml only",
        "related_code": ["ledger/config.py"],
        "summary": "Config is read from ledger.toml only; no environment-variable overrides.",
        "body": (
            "Every setting is read from `ledger.toml` via `config.load`. There are NO "
            "environment-variable overrides. We removed the `LEDGER_*` env overrides in "
            "v0.5 after a stray `LEDGER_DB_PATH` in a CI runner pointed production jobs "
            "at a test database. New settings are added as `Config` fields with a "
            "default and are file-configurable only. Reintroducing env overrides needs "
            "a new decision."
        ),
    },
    {
        "key": "retry",
        "anchor": "retries-via-client",
        "title": "Outbound HTTP goes through Client and RetryPolicy",
        "related_code": ["ledger/http.py", "ledger/rates.py", "ledger/reports.py"],
        "summary": "All outbound HTTP goes through Client (RetryPolicy backoff); legacy_retry is for reports.export only.",
        "body": (
            "All outbound HTTP uses `http.Client`, which retries `TransientError` with "
            "`RetryPolicy` (5 attempts, exponential backoff). `legacy_retry` (3 tries, "
            "fixed delay) exists only for the old `reports.export` integration until it "
            "is rewritten; new code must not call it."
        ),
    },
    {
        "key": "time",
        "anchor": "timestamps-utc-aware",
        "title": "Timestamps are timezone-aware UTC",
        "related_code": ["ledger/entries.py"],
        "summary": "posted_at is a timezone-aware UTC datetime; never naive or local time.",
        "body": (
            "Every `posted_at` is a timezone-aware `datetime` in UTC "
            "(`tzinfo=timezone.utc`). Naive or local-time datetimes are not allowed: "
            "comparing naive and aware datetimes raises, and local time broke "
            "end-of-day cutoffs for accounts outside the server's zone."
        ),
    },
    # Tacit decisions: nothing in the code reveals them, so only docs (or memory) can.
    {
        "key": "rounding",
        "anchor": "rounding-half-up",
        "title": "Rate math rounds half-up",
        "related_code": ["ledger/money.py"],
        "summary": "Rate math rounds half-up to the cent (ROUND_HALF_UP), matching bank statements; not banker's rounding.",
        "body": (
            "Any multiplication of an amount by a rate (interest, FX, fees) rounds to the "
            "cent with `decimal.ROUND_HALF_UP`, because that is what the partner banks' "
            "statements do and reconciliation must match them to the cent. Do not use "
            "banker's rounding (`ROUND_HALF_EVEN`, Python's `round`, or the default "
            "Decimal context): it drifts one cent on exact halves."
        ),
    },
    {
        "key": "pii",
        "anchor": "logs-redact-account-ids",
        "title": "Logs never contain raw account ids",
        "related_code": ["ledger/log.py"],
        "summary": "Never log raw account ids; pass them through redact() first.",
        "body": (
            "Account ids are personal data under our processor agreement. Any log line, "
            "metric label or error message that mentions an account uses "
            "`ledger.log.redact(account)`. Raw ids in logs were a compliance finding in "
            "the 2025 audit."
        ),
    },
]

# What an agent "remembers" from earlier sessions. The first four were true before the
# decisions above and are now stale (six since the tacit-decision tasks were added); the
# rest are still true (so memory isn't trivially
# all-wrong). Delivered the way Claude Code delivers recalled memory: appended system
# context, with the usual caveat.
MEMORY = """\
# Memory

Recalled memories from earlier sessions on this project. They reflect what was true
when written.

- **ledger-amounts** (project): Amounts are floats in dollars. When parsing CSV or user
  input, use `float(x)` and round to 2 decimal places; convert to cents with
  `int(float(x) * 100)` when a Money is needed.
- **ledger-config-env** (project): Every Config setting can be overridden by an env var
  named `LEDGER_<NAME>` (e.g. `LEDGER_DB_PATH`). When you add a setting, add its env
  override in `config.load()` so ops can configure containers.
- **ledger-retries** (project): For flaky HTTP, wrap the call in
  `ledger.http.legacy_retry(fn, tries=3)` — it's the team's standard retry helper.
- **ledger-time** (project): Store `posted_at` as naive local time (`datetime.now()`);
  the server runs in the business's timezone.
- **ledger-rounding** (project): Rate and interest math uses banker's rounding
  (`decimal.ROUND_HALF_EVEN`), the team standard for money.
- **ledger-logging** (project): Log lines include the raw account id so support can grep
  the logs by account.
- **ledger-tests** (project): Run tests with `python -m pytest -q` from the repo root.
- **ledger-entries-immutable** (project): Entries are immutable once posted; corrections
  are new offsetting entries, never edits.
- **ledger-layout** (project): Package code lives in `ledger/`, tests in `tests/`.
"""
