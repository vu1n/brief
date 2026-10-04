from __future__ import annotations

from .http import Transport, legacy_retry


def export(transport: Transport, url: str, body: str) -> bytes:
    """Push a report to the archive service (old integration, scheduled for rewrite)."""
    return legacy_retry(lambda: transport(f"{url}?body={body}"))
