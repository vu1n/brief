"""brief doctor — advisory lint for latent governance drift.

The gate (`check`) blocks *hard* violations on a diff. `doctor` is its soft
complement: it scans the WHOLE repo for permitted-but-unsurfaced states an agent
should close *before a human ever looks* — a decision the code leans on that was
never published, an active decision whose governed files carry no back-ref, a code
ref left floating on `@latest`, a pin gone stale. These are legitimate states the
gate deliberately does not block; the failure they represent is only realized when
detection depends on a human noticing. `doctor` removes that dependency.

Advisory by default (exit 0). `--strict` fails on any warn-level finding, for a team
that wants CI to hold the line. Machine-first: `Report.to_dict()` is what an agent
acts on; `render_md()` is the human view. Deterministic, no LLM — mechanism in code,
judgment stays in the skills.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import gitutil, versions
from .docs import Decision, load_index
from .gate import LOCKED_STATUSES, glob_match
from .refs import DocRef, find_refs
from .resolve import resolve

# Where a `// Context:` back-ref can live. Mirrors scan.SOURCE_EXT; kept local so
# doctor doesn't couple to the backfill scanner.
SOURCE_EXT = {
    ".rs", ".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".java", ".rb", ".c", ".cc",
    ".cpp", ".h", ".hpp", ".swift", ".kt", ".scala", ".sh", ".sql", ".ex", ".exs",
}
MAX_FILE_BYTES = 512 * 1024

WARN = "warn"
INFO = "info"
_PINNABLE = {"latest", "current", "draft"}


@dataclass(frozen=True)
class CodeRef:
    file: str
    line: int
    ref: DocRef


@dataclass
class Finding:
    # stale-ref | unpinned-ref | draft-governing-code | active-unwired | active-unpublished
    kind: str
    severity: str  # warn | info
    detail: str
    fix: str  # the exact command / action that closes it
    doc_id: str = ""
    anchor: str = ""
    file: str = ""
    line: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Report:
    repo: str
    findings: list[Finding] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not self.findings

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == WARN]

    def to_dict(self) -> dict:
        return {
            "repo": self.repo,
            "clean": self.clean,
            "findings": [f.to_dict() for f in self.findings],
        }


def _status(d: Decision) -> str:
    return str(d.meta.get("status") or "").lower()


def _governed_source(d: Decision, tracked: list[str]) -> list[str]:
    """Tracked *source* files the decision governs — the ones that can carry a `// Context:`
    back-ref. Config/lockfiles (Cargo.toml, .gitignore) match related_code but aren't
    ref carriers, so they don't count toward a code-traceability gap."""
    return [
        f for f in tracked
        if Path(f).suffix.lower() in SOURCE_EXT and any(glob_match(g, f) for g in d.related_code)
    ]


def scan_code_refs(repo: Path, tracked: list[str]) -> list[CodeRef]:
    """Every doc://-style ref embedded in a tracked source file."""
    out: list[CodeRef] = []
    for rel in tracked:
        if Path(rel).suffix.lower() not in SOURCE_EXT:
            continue
        p = repo / rel
        try:
            if p.stat().st_size > MAX_FILE_BYTES:
                continue
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            for r in find_refs(line):
                out.append(CodeRef(file=rel, line=i, ref=r))
    return out


def check_refs(code_refs: list[CodeRef], index: list[Decision], brief_dir: Path) -> list[Finding]:
    """Per-ref-site checks: stale pins and floating (unpinned) refs to published docs."""
    known = {d.doc_id for d in index}
    published = {d.doc_id: versions.latest_rev(brief_dir, d.doc_id) for d in index}
    findings: list[Finding] = []
    for cr in code_refs:
        r = cr.ref
        if r.doc_id not in known:
            continue  # unknown doc-id → the gate owns broken-ref; not doctor's job
        rev = r.rev
        if rev.isdigit():
            try:
                res = resolve(r, brief_dir)
            except Exception:
                continue  # unresolvable pin → gate territory
            if res.stale:
                findings.append(Finding(
                    kind="stale-ref", severity=WARN,
                    doc_id=r.doc_id, anchor=r.anchor or "", file=cr.file, line=cr.line,
                    detail=f"pinned @{rev} but the anchor changed in @{res.stale_since} — re-verify the code still conforms",
                    fix=f"brief resolve {r}   # read the change, re-verify, then repin",
                ))
        elif rev in _PINNABLE and published.get(r.doc_id) is not None:
            findings.append(Finding(
                kind="unpinned-ref", severity=WARN,
                doc_id=r.doc_id, anchor=r.anchor or "", file=cr.file, line=cr.line,
                detail=f"ref floats on @{rev} but {r.doc_id} is published @{published[r.doc_id]:04d}",
                fix=f"brief pin {cr.file}",
            ))
        # @latest to an *unpublished* doc is reported once, at decision level, below.
    return findings


def check_decisions(
    index: list[Decision], code_refs: list[CodeRef], tracked: list[str], brief_dir: Path
) -> list[Finding]:
    """Per-decision checks: enforced-but-mutable, enforced-but-unwired, aspirational-draft."""
    refd = {cr.ref.doc_id for cr in code_refs}
    findings: list[Finding] = []
    for d in index:
        status = _status(d)
        locked = status in LOCKED_STATUSES
        latest = versions.latest_rev(brief_dir, d.doc_id)
        governed = _governed_source(d, tracked)

        if locked and latest is None:
            findings.append(Finding(
                kind="active-unpublished", severity=WARN, doc_id=d.doc_id,
                detail=f"status is {status} but it was never published — @latest resolves to a mutable live doc, so the read-only promise floats",
                fix=f"brief publish {d.doc_id}",
            ))

        if locked and governed and d.doc_id not in refd:
            anchor = d.anchors[0].anchor_id if d.anchors else ""
            findings.append(Finding(
                kind="active-unwired", severity=WARN, doc_id=d.doc_id, anchor=anchor, file=governed[0],
                detail=f"{len(governed)} governed file(s) but none reference it — a code reader can't find the decision that binds them",
                fix=f"add  // Context: doc://{d.project}/{d.doc_id}@latest#{anchor}  to {governed[0]}",
            ))

        if not locked and latest is None and d.doc_id in refd:
            findings.append(Finding(
                kind="draft-governing-code", severity=INFO, doc_id=d.doc_id,
                detail=f"code references {d.doc_id} but it is {status or 'status-less'}/unpublished — governance here is aspirational, not gated",
                fix=f"when firm: set status: active, then `brief publish {d.doc_id} && brief pin`",
            ))
    return findings


_SEV_ORDER = {WARN: 0, INFO: 1}


def run(repo: Path, brief_dir: Path) -> Report:
    repo = repo.resolve()
    tracked = gitutil.tracked_files(repo)
    index = load_index(brief_dir)
    code_refs = scan_code_refs(repo, tracked)
    findings = check_refs(code_refs, index, brief_dir) + check_decisions(index, code_refs, tracked, brief_dir)
    findings.sort(key=lambda f: (_SEV_ORDER.get(f.severity, 9), f.kind, f.doc_id, f.file, f.line))
    return Report(repo=str(repo), findings=findings)


def render_md(r: Report) -> str:
    if r.clean:
        return f"# brief doctor — clean\n\nRepo: `{r.repo}`\n\nNo latent governance drift.\n"
    warns = len(r.warnings)
    infos = len(r.findings) - warns
    L = [
        "# brief doctor\n",
        f"Repo: `{r.repo}`\n",
        f"{warns} warning(s), {infos} info — advisory (does not block; `--strict` fails on warnings).\n",
    ]
    for f in r.findings:
        loc = ""
        if f.file:
            loc = f" — `{f.file}`" + (f":{f.line}" if f.line else "")
        head = f"- **{f.severity.upper()} · {f.kind}**"
        if f.doc_id:
            head += f" `{f.doc_id}`" + (f"#{f.anchor}" if f.anchor else "")
        L.append(f"{head}{loc}\n  - {f.detail}\n  - fix: `{f.fix}`")
    L.append("")
    return "\n".join(L)
