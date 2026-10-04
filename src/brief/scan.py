"""Mechanical scanner for `brief backfill` — build a context map of a repo.

Deterministic legwork ONLY (no LLM): inventory docs (+genre, +status field,
+git-tracked), grep decision-signal comments and existing `doc://` refs, and sketch
the module tree. The *synthesis* — deciding which of these are real decisions and
authoring the docs — is the `brief-backfill` skill's job. Mechanism in code, policy
in prose.
"""
from __future__ import annotations

import os
import re
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path

SOURCE_EXT = {
    ".rs", ".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".java", ".rb", ".c", ".cc",
    ".cpp", ".h", ".hpp", ".swift", ".kt", ".scala", ".sh", ".sql", ".ex", ".exs",
}
SKIP_DIRS = {
    ".git", ".brief", "node_modules", "target", "target-amd64", "dist", "build",
    ".venv", "venv", "__pycache__", ".next", "vendor", ".mypy_cache", ".pytest_cache",
    ".ruff_cache", "coverage", ".turbo",
}
DECISION_GENRES = {"adr", "decision", "design", "spec", "contract"}
# Agent tooling (installed skills, agent configs) — never a decision doc, whatever it says.
AGENT_DIRS = {".claude", ".agents", ".codex", ".cursor", ".opencode", ".gemini"}
MAX_FILE_BYTES = 512 * 1024
MAX_SIGNALS = 500

_REF_RE = re.compile(r"(?:doc|prompt|test)://[^\s\"'`)>\]}]+")
_COMMENTISH = re.compile(r"(//|#|/\*|^\s*\*|<!--|--\s)")
_CTX_RE = re.compile(r"(?i)\b(context|decision|spec|rationale|why|invariant)\s*:")
_RATIONALE_RE = re.compile(
    r"(?i)\b(must not|do not|invariant|because|workaround|hack|important|"
    r"see (adr|jira|rfc)|@decision)\b"
)
_STATUS_RE = re.compile(r"(?im)^\s*(?:-\s*)?status\s*[:=]")
_HEADING_RE = re.compile(r"^#{1,6}\s+(.*\S)\s*$")
_FM_TITLE_RE = re.compile(r"(?im)^\s*title\s*:\s*(.+?)\s*$")
_ADR_NAME_RE = re.compile(r"adr[-_]?\d", re.I)


@dataclass
class DocEntry:
    path: str
    genre: str
    title: str
    has_status: bool
    tracked: bool
    lines: int


@dataclass
class Signal:
    file: str
    line: int
    kind: str  # "ref" | "context" | "rationale"
    text: str


@dataclass
class ContextMap:
    repo: str
    docs: list[DocEntry] = field(default_factory=list)
    signals: list[Signal] = field(default_factory=list)
    modules: list[str] = field(default_factory=list)

    @property
    def decision_docs(self) -> list[DocEntry]:
        return [d for d in self.docs if d.genre in DECISION_GENRES]

    @property
    def untracked_decisions(self) -> list[DocEntry]:
        return [d for d in self.decision_docs if not d.tracked]

    @property
    def status_less_decisions(self) -> list[DocEntry]:
        return [d for d in self.decision_docs if not d.has_status]

    def to_dict(self) -> dict:
        return asdict(self)


def _walk(repo: Path):
    for root, dirs, files in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            yield Path(root) / f


def _tracked(repo: Path) -> set[str]:
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), "ls-files"], capture_output=True, text=True, check=True
        ).stdout
        return set(out.splitlines())
    except (subprocess.CalledProcessError, FileNotFoundError):
        return set()


def _classify(rel: str, head: str) -> str:
    p = "/" + rel.lower()
    name = rel.rsplit("/", 1)[-1].lower()
    # explicit filenames first — so a README that says "supersedes" isn't tagged an ADR
    if name == "readme.md":
        return "readme"
    if name in ("agents.md", "claude.md"):
        return "agent-guide"
    if name == "skill.md" or rel.split("/", 1)[0] in AGENT_DIRS:
        return "agent-tooling"
    # decision genres by path or name
    if "/decisions/" in p or "/adr" in p or _ADR_NAME_RE.search(name) or "decision" in name:
        return "adr"
    if "/contracts/" in p:
        return "contract"
    if "/specs/" in p or name.startswith("spec"):
        return "spec"
    if "/design/" in p:
        return "design"
    if "/runbooks/" in p or "/runbook" in p:
        return "runbook"
    if name.startswith(("plan", "roadmap")) or "/plans/" in p:
        return "plan"
    if name.startswith("review") or re.search(r"review[-_]?\d", name):
        return "review"
    # loose fallback: an otherwise-plain doc carrying a status/supersede signal is ADR-ish
    if "supersed" in head.lower() or _STATUS_RE.search(head):
        return "adr"
    return "doc"


def _title(text: str, rel: str) -> str:
    fm = _FM_TITLE_RE.search("\n".join(text.splitlines()[:20]))
    if fm:
        return fm.group(1).strip()
    for line in text.splitlines()[:60]:
        h = _HEADING_RE.match(line)
        if h:
            return h.group(1)
    return rel.rsplit("/", 1)[-1]


def scan_docs(repo: Path, tracked: set[str]) -> list[DocEntry]:
    out: list[DocEntry] = []
    for p in _walk(repo):
        if p.suffix.lower() != ".md":
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = str(p.relative_to(repo))
        head = "\n".join(text.splitlines()[:40])
        out.append(
            DocEntry(
                path=rel,
                genre=_classify(rel, head),
                title=_title(text, rel),
                has_status=bool(_STATUS_RE.search(head)),
                tracked=rel in tracked,
                lines=len(text.splitlines()),
            )
        )
    return sorted(out, key=lambda d: d.path)


def scan_signals(repo: Path) -> list[Signal]:
    out: list[Signal] = []
    for p in _walk(repo):
        if p.suffix.lower() not in SOURCE_EXT:
            continue
        try:
            if p.stat().st_size > MAX_FILE_BYTES:
                continue
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = str(p.relative_to(repo))
        for i, line in enumerate(text.splitlines(), 1):
            if _REF_RE.search(line):
                kind = "ref"
            elif _COMMENTISH.search(line) and _CTX_RE.search(line):
                kind = "context"
            elif _COMMENTISH.search(line) and _RATIONALE_RE.search(line):
                kind = "rationale"
            else:
                continue
            out.append(Signal(file=rel, line=i, kind=kind, text=line.strip()[:200]))
    # strongest first, then cap
    order = {"ref": 0, "context": 1, "rationale": 2}
    out.sort(key=lambda s: (order[s.kind], s.file, s.line))
    return out[:MAX_SIGNALS]


def module_tree(repo: Path) -> list[str]:
    dirs: set[str] = set()
    for p in _walk(repo):
        if p.suffix.lower() not in SOURCE_EXT:
            continue
        parts = p.relative_to(repo).parts
        dirs.add("/".join(parts[:2]) if len(parts) >= 2 else parts[0])
    return sorted(dirs)


def build_map(repo: Path) -> ContextMap:
    tracked = _tracked(repo)
    return ContextMap(
        repo=str(repo),
        docs=scan_docs(repo, tracked),
        signals=scan_signals(repo),
        modules=module_tree(repo),
    )


def render_map_md(m: ContextMap) -> str:
    by_genre: dict[str, int] = {}
    for d in m.docs:
        by_genre[d.genre] = by_genre.get(d.genre, 0) + 1
    sig_counts = {k: sum(1 for s in m.signals if s.kind == k) for k in ("ref", "context", "rationale")}

    L: list[str] = []
    L.append(f"# brief backfill — context map\n")
    L.append(f"Repo: `{m.repo}`\n")
    L.append("## Summary\n")
    L.append(f"- docs: {len(m.docs)} ({', '.join(f'{k} {v}' for k, v in sorted(by_genre.items()))})")
    L.append(f"- decision-genre docs (adr/design/spec/contract): {len(m.decision_docs)}")
    L.append(f"- ⚠ untracked decisions: {len(m.untracked_decisions)} · decisions missing a status field: {len(m.status_less_decisions)}")
    L.append(f"- code signals: {len(m.signals)} (refs {sig_counts['ref']}, context {sig_counts['context']}, rationale {sig_counts['rationale']})")
    L.append(f"- source modules: {len(m.modules)}\n")

    L.append("## Decision-genre docs (primary backfill inputs)\n")
    L.append("| doc | genre | status field | tracked | title |")
    L.append("|-----|-------|--------------|---------|-------|")
    for d in m.decision_docs:
        L.append(f"| `{d.path}` | {d.genre} | {'yes' if d.has_status else '**no**'} | {'yes' if d.tracked else '**NO**'} | {d.title} |")
    L.append("")

    other = [d for d in m.docs if d.genre not in DECISION_GENRES]
    if other:
        L.append("## Other docs (NOT decisions — plans/reviews/runbooks/readmes)\n")
        L.append("Per genre-split: these are snapshots/guides, not governed decisions. Do not import as decisions.\n")
        for d in other:
            L.append(f"- `{d.path}` — {d.genre}{' ⚠ untracked' if not d.tracked else ''}")
        L.append("")

    if m.signals:
        L.append("## Decision signals in code (candidate decisions / existing refs)\n")
        cur = None
        for s in m.signals:
            if s.file != cur:
                cur = s.file
                L.append(f"\n**`{s.file}`**")
            L.append(f"- L{s.line} [{s.kind}] `{s.text}`")
        L.append("")

    L.append("## Source modules (for related_code scoping)\n")
    L.append(", ".join(f"`{d}`" for d in m.modules) or "(none)")
    L.append("")
    return "\n".join(L)
