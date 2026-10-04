from __future__ import annotations

import logging

logger = logging.getLogger("ledger")


{{WHY:pii}}
def redact(identifier: str) -> str:
    """Mask an identifier, keeping its last 4 characters."""
    return "*" * max(len(identifier) - 4, 0) + identifier[-4:]
