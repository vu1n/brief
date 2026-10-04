from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

{{WHY:rounding}}
{{WHY:money}}
@dataclass(frozen=True, order=True)
class Money:
    cents: int

    def __post_init__(self) -> None:
        if not isinstance(self.cents, int) or isinstance(self.cents, bool):
            raise TypeError(f"Money.cents must be int, got {type(self.cents).__name__}")

    def __add__(self, other: Money) -> Money:
        return Money(self.cents + other.cents)

    def __sub__(self, other: Money) -> Money:
        return Money(self.cents - other.cents)

    @classmethod
    def from_str(cls, text: str) -> Money:
        """Parse a decimal string like "12.34" or "-0.5" exactly."""
        try:
            value = Decimal(text.strip())
        except InvalidOperation as e:
            raise ValueError(f"not an amount: {text!r}") from e
        cents = value * 100
        if cents != cents.to_integral_value():
            raise ValueError(f"more than 2 decimal places: {text!r}")
        return cls(int(cents))

    def __str__(self) -> str:
        sign = "-" if self.cents < 0 else ""
        whole, frac = divmod(abs(self.cents), 100)
        return f"{sign}{whole}.{frac:02d}"
