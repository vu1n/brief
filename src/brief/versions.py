"""Revisions — frozen, per-doc, zero-padded monotonic snapshots + aliases.

The live doc is `.brief/docs/<id>.md`. `brief publish` freezes it as
`.brief/docs/<id>/versions/vNNNN.md` and records `latest` in `.brief/aliases.yaml`.
Version files are a derived, git-backed cache; `@latest` falls back to the live draft
until a doc is first published.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from .docs import DocError

_REV_RE = re.compile(r"^v(\d+)\.md$")


def aliases_file(brief_dir: Path) -> Path:
    return brief_dir / "aliases.yaml"


def load_aliases(brief_dir: Path) -> dict:
    p = aliases_file(brief_dir)
    if not p.exists():
        return {}
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise DocError(f"{p}: not valid YAML: {getattr(e, 'problem', None) or e}") from None
    if not isinstance(data, dict):
        raise DocError(f"{p}: must be a YAML mapping")
    return data


def save_aliases(brief_dir: Path, data: dict) -> None:
    aliases_file(brief_dir).write_text(yaml.safe_dump(data, sort_keys=True), encoding="utf-8")


def live_doc(brief_dir: Path, doc_id: str) -> Path:
    return brief_dir / "docs" / f"{doc_id}.md"


def versions_dir(brief_dir: Path, doc_id: str) -> Path:
    return brief_dir / "docs" / doc_id / "versions"


def version_path(brief_dir: Path, doc_id: str, rev: int) -> Path:
    return versions_dir(brief_dir, doc_id) / f"v{rev:04d}.md"


def existing_revs(brief_dir: Path, doc_id: str) -> list[int]:
    d = versions_dir(brief_dir, doc_id)
    if not d.exists():
        return []
    return sorted(int(m.group(1)) for f in d.glob("v*.md") if (m := _REV_RE.match(f.name)))


def latest_rev(brief_dir: Path, doc_id: str) -> int | None:
    alias = load_aliases(brief_dir).get(doc_id, {})
    if "latest" in alias:
        return int(alias["latest"])
    revs = existing_revs(brief_dir, doc_id)
    return revs[-1] if revs else None


def publish(brief_dir: Path, doc_id: str) -> int:
    """Freeze the live doc as the next revision; update `latest`. Refuses to overwrite."""
    live = live_doc(brief_dir, doc_id)
    if not live.exists():
        raise FileNotFoundError(f"no live doc for {doc_id} at {live}")
    nxt = (existing_revs(brief_dir, doc_id)[-1] + 1) if existing_revs(brief_dir, doc_id) else 1
    vf = version_path(brief_dir, doc_id, nxt)
    if vf.exists():
        raise FileExistsError(f"{vf} already exists")
    vf.parent.mkdir(parents=True, exist_ok=True)
    vf.write_text(live.read_text(encoding="utf-8"), encoding="utf-8")
    aliases = load_aliases(brief_dir)
    aliases.setdefault(doc_id, {})["latest"] = nxt
    save_aliases(brief_dir, aliases)
    return nxt
