"""Load .brief/docs decision docs: frontmatter, governed-code globs, anchors.

Pure parsing over the filesystem — no index, no git. This is the
CocoIndex-callable seam: parse_doc(path) -> Decision.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ANCHOR_RE = re.compile(r"<!--\s*brief:anchor\s+([a-z0-9][a-z0-9-]*)\s*-->")
HEADING_RE = re.compile(r"^#{1,6}\s+(.*\S)\s*$")
FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)


class DocError(ValueError):
    """A .brief file brief can't parse. The CLI prints it as one line, not a traceback."""


def _yaml_problem(e: yaml.YAMLError) -> str:
    return str(getattr(e, "problem", None) or e)


def load_frontmatter(text: str, path: Path) -> dict:
    fm = FRONTMATTER_RE.match(text)
    if not fm:
        return {}
    try:
        meta = yaml.safe_load(fm.group(1)) or {}
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        where = f" (frontmatter line {mark.line + 1})" if mark else ""
        raise DocError(
            f"{path}: frontmatter is not valid YAML{where}: {_yaml_problem(e)}. "
            'Quote a value that contains ": ", e.g. title: "Retry: idempotent only".'
        ) from None
    if not isinstance(meta, dict):
        raise DocError(f"{path}: frontmatter must be a YAML mapping (key: value lines)")
    return meta


def glob_match(pattern: str, path: str) -> bool:
    """Match a path against a glob: ** spans directories, * stays within a segment."""
    rx: list[str] = []
    i = 0
    while i < len(pattern):
        if pattern.startswith("**", i):
            rx.append(".*")
            i += 2
            if i < len(pattern) and pattern[i] == "/":
                i += 1
        elif pattern[i] == "*":
            rx.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            rx.append("[^/]")
            i += 1
        else:
            rx.append(re.escape(pattern[i]))
            i += 1
    return re.match("^" + "".join(rx) + "$", path) is not None


def sha256(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Anchor:
    anchor_id: str
    title: str
    start_line: int  # 1-based: the anchor marker line
    end_line: int    # 1-based: last line of the anchor body
    body: str
    hash: str


@dataclass
class Decision:
    doc_id: str
    project: str
    path: Path
    related_code: list[str]
    meta: dict
    anchors: list[Anchor] = field(default_factory=list)

    def anchor(self, anchor_id: str) -> Anchor | None:
        return next((a for a in self.anchors if a.anchor_id == anchor_id), None)


def parse_doc(path: Path, project: str) -> Decision:
    text = path.read_text(encoding="utf-8")
    meta = load_frontmatter(text, path)
    doc_id = str(meta.get("id") or path.stem)
    related = meta.get("related_code") or []
    if isinstance(related, str):
        related = [related]

    lines = text.splitlines()
    marks: list[tuple[int, str]] = []  # (line_idx0, anchor_id)
    for i, line in enumerate(lines):
        m = ANCHOR_RE.search(line)
        if m:
            marks.append((i, m.group(1)))

    anchors: list[Anchor] = []
    for n, (idx, aid) in enumerate(marks):
        end_idx = marks[n + 1][0] - 1 if n + 1 < len(marks) else len(lines) - 1
        body_lines = lines[idx + 1 : end_idx + 1]
        title = aid
        for bl in body_lines:
            hm = HEADING_RE.match(bl)
            if hm:
                title = hm.group(1)
                break
        body = "\n".join(body_lines).strip("\n")
        anchors.append(
            Anchor(
                anchor_id=aid,
                title=title,
                start_line=idx + 1,
                end_line=end_idx + 1,
                body=body,
                hash=sha256(body.strip()),
            )
        )
    return Decision(
        doc_id=doc_id,
        project=project,
        path=path,
        related_code=list(related),
        meta=meta,
        anchors=anchors,
    )


UNPARSEABLE = "<unparseable>"


def _baseline_meta(text: str) -> dict | None:
    """Frontmatter of a doc read from a git ref; None if it can't be parsed. Never raises:
    the gate must keep working on a baseline that predates DocError."""
    try:
        return load_frontmatter(text, Path("<baseline>"))
    except DocError:
        return None


def status_of(text: str) -> str | None:
    """The frontmatter `status` of raw doc text (for baseline checks). UNPARSEABLE when the
    frontmatter is broken: the gate treats that as locked, so repairing a broken ratified doc
    can't double as an unreviewed rewrite of it."""
    meta = _baseline_meta(text)
    if meta is None:
        return UNPARSEABLE
    s = meta.get("status")
    return str(s) if s is not None else None


def doc_id_of(text: str, path: Path) -> str:
    """The doc id a raw doc text declares (frontmatter `id`), else the file stem —
    the same rule as parse_doc, for docs that exist only at a git ref."""
    meta = _baseline_meta(text) or {}
    return str(meta.get("id") or path.stem)


def project_name(brief_dir: Path) -> str:
    pj = brief_dir / "project.yaml"
    if pj.exists():
        try:
            data = yaml.safe_load(pj.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as e:
            raise DocError(f"{pj}: not valid YAML: {_yaml_problem(e)}") from None
        if isinstance(data, dict) and data.get("id"):
            return str(data["id"])
    return brief_dir.parent.name


def load_index(brief_dir: Path) -> list[Decision]:
    """Load every decision doc under <brief_dir>/docs."""
    project = project_name(brief_dir)
    docs_dir = brief_dir / "docs"
    if not docs_dir.exists():
        return []
    return [parse_doc(p, project) for p in sorted(docs_dir.rglob("*.md")) if "versions" not in p.parts]


def find_brief_dir(start: Path) -> Path | None:
    """Walk up from start to find a .brief directory."""
    cur = start.resolve()
    for d in [cur, *cur.parents]:
        cand = d / ".brief"
        if cand.is_dir():
            return cand
    return None
