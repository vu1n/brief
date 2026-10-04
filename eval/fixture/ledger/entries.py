from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from .money import Money


{{WHY:time}}
@dataclass(frozen=True)
class Entry:
    account: str
    amount: Money
    posted_at: datetime


@dataclass
class Ledger:
    entries: list[Entry] = field(default_factory=list)

    def post(self, account: str, amount: Money, at: datetime | None = None) -> Entry:
        entry = Entry(account, amount, at or datetime.now(timezone.utc))
        self.entries.append(entry)
        return entry

    def balance(self, account: str) -> Money:
        total = Money(0)
        for e in self.entries:
            if e.account == account:
                total = total + e.amount
        return total
