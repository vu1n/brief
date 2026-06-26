"""doc:// reference parsing and formatting.

A ref addresses a decision:  doc://<project>/<doc-id>@<rev>#<anchor>
  - project : required
  - doc-id  : required
  - rev     : required (a revision id, or an alias: current/latest/stable)
  - anchor  : optional

The scheme is intentionally tool-agnostic ("doc"), so refs embedded in code
comments survive a rename of the tool itself.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_REF_RE = re.compile(
    r"^(?P<scheme>doc|prompt|test)://"
    r"(?P<project>[^/@#]+)/"
    r"(?P<doc_id>[^@#]+)"
    r"@(?P<rev>[^#/]+)"
    r"(?:#(?P<anchor>[A-Za-z0-9][A-Za-z0-9-]*))?$"
)

ALIASES = ("current", "latest", "stable")


@dataclass(frozen=True)
class DocRef:
    scheme: str
    project: str
    doc_id: str
    rev: str
    anchor: str | None = None

    @classmethod
    def parse(cls, text: str) -> "DocRef":
        m = _REF_RE.match(text.strip())
        if not m:
            raise ValueError(f"not a valid ref: {text!r}")
        return cls(
            scheme=m["scheme"],
            project=m["project"],
            doc_id=m["doc_id"],
            rev=m["rev"],
            anchor=m["anchor"],
        )

    def __str__(self) -> str:
        s = f"{self.scheme}://{self.project}/{self.doc_id}@{self.rev}"
        if self.anchor:
            s += f"#{self.anchor}"
        return s

    @property
    def is_alias(self) -> bool:
        return self.rev in ALIASES


_EMBED_RE = re.compile(r"(?:doc|prompt|test)://[^\s\"'`)>\]}]+")


def find_refs(text: str) -> list[DocRef]:
    """Extract every doc://-style ref embedded in a blob of text (e.g. code)."""
    out: list[DocRef] = []
    for m in _EMBED_RE.finditer(text):
        token = m.group(0).rstrip(".,;:")
        try:
            out.append(DocRef.parse(token))
        except ValueError:
            continue
    return out
