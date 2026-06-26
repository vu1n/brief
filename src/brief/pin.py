"""Pin — freeze moving aliases in code to a concrete revision.

Agents write `@latest`/`@current` while working; `brief pin` rewrites them to the
concrete latest *published* revision so a committed code ref records exactly which
decision revision it was written against. Leaves `@stable` (a deliberate alias) and
already-pinned `@NNNN` untouched, and leaves unpublished docs unpinned.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from . import versions

PINNABLE = ("latest", "current", "draft")

_REF = re.compile(
    r"(?P<scheme>doc|prompt|test)://(?P<proj>[^/@#\s]+)/(?P<doc>[^@#\s]+)"
    r"@(?P<rev>latest|current|draft|stable|\d+)(?P<anchor>#[A-Za-z0-9][A-Za-z0-9-]*)?"
)


@dataclass
class PinChange:
    file: str
    old: str
    new: str | None  # None → could not pin
    note: str = ""


def pin_text(text: str, brief_dir: Path) -> tuple[str, list[PinChange]]:
    changes: list[PinChange] = []

    def repl(m: re.Match) -> str:
        if m.group("rev") not in PINNABLE:
            return m.group(0)
        doc, old = m.group("doc"), m.group(0)
        latest = versions.latest_rev(brief_dir, doc)
        if latest is None:
            changes.append(PinChange("", old, None, "doc not published — left unpinned"))
            return old
        new = f"{m.group('scheme')}://{m.group('proj')}/{doc}@{latest:04d}{m.group('anchor') or ''}"
        changes.append(PinChange("", old, new))
        return new

    return _REF.sub(repl, text), changes


def pin_files(paths, brief_dir: Path) -> list[PinChange]:
    out: list[PinChange] = []
    for raw in paths:
        p = Path(raw)
        if not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        new, changes = pin_text(text, brief_dir)
        for c in changes:
            c.file = str(p)
        if new != text:
            p.write_text(new, encoding="utf-8")
        out.extend(changes)
    return out
