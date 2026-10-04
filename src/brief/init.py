"""brief init — scaffold a vault, inject the convention, install the gate hook.

The one human-facing setup primitive. Everything it installs (the AGENTS.md
convention + skills) is the behavior layer that does the real work.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from .templates import AGENTS_SNIPPET, MARKER

HOOK = (
    "#!/bin/sh\n"
    "# brief L0 governance gate (pre-commit)\n"
    'exec brief check --repo "$(git rev-parse --show-toplevel)"\n'
)


def _git_root(start: Path) -> Path | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        return Path(out) if out else None
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def _agents_file(repo: Path) -> Path:
    for name in ("AGENTS.md", "CLAUDE.md"):
        p = repo / name
        if p.exists():
            return p.resolve()  # follow symlink (e.g. CLAUDE.md -> AGENTS.md)
    return repo / "AGENTS.md"


def _inject_snippet(agents: Path, actions: list[str]) -> None:
    existing = agents.read_text(encoding="utf-8") if agents.exists() else ""
    if MARKER in existing:
        # Refresh in place: the block runs from the marker to the next `## ` heading (or
        # EOF), so re-running init upgrades an older convention without touching the rest.
        start = existing.index(MARKER)
        nxt = existing.find("\n## ", start + len(MARKER))
        end = len(existing) if nxt == -1 else nxt + 1
        block = AGENTS_SNIPPET if nxt == -1 else AGENTS_SNIPPET + "\n"
        if existing[start:end] == block:
            actions.append(f"convention already current in {agents.name} (skipped)")
            return
        agents.write_text(existing[:start] + block + existing[end:], encoding="utf-8")
        actions.append(f"refreshed brief convention in {agents.name}")
        return
    sep = "" if not existing else ("\n" if existing.endswith("\n") else "\n\n")
    agents.write_text(existing + sep + AGENTS_SNIPPET, encoding="utf-8")
    actions.append(f"injected brief convention into {agents.name}")


def _install_hook(repo: Path, actions: list[str]) -> None:
    root = _git_root(repo) or repo
    git_dir = root / ".git"
    if not git_dir.exists():
        actions.append("no .git — skipped hook (gate still available via `brief check`)")
        return
    hooks = git_dir / "hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    target = hooks / "pre-commit"
    if target.exists():
        actions.append("pre-commit hook exists — left as-is; chain in `brief check` manually")
        return
    target.write_text(HOOK, encoding="utf-8")
    target.chmod(0o755)
    actions.append("installed pre-commit gate hook")


def _pinned_version(workflow: str) -> tuple[int, ...]:
    m = re.search(r"vu1n/brief@v(\d+(?:\.\d+)*)", workflow)
    return tuple(int(x) for x in m.group(1).split(".")) if m else ()


def _install_ci(repo: Path, actions: list[str]) -> None:
    from .templates import CI_MARKER, CI_WORKFLOW

    wf = repo / ".github" / "workflows" / "brief.yml"
    if wf.exists():
        current = wf.read_text(encoding="utf-8")
        if CI_MARKER not in current:
            actions.append(".github/workflows/brief.yml is hand-managed — left as-is; bump its brief tag by hand")
        elif current == CI_WORKFLOW:
            actions.append(".github/workflows/brief.yml already current")
        elif _pinned_version(current) > _pinned_version(CI_WORKFLOW):
            actions.append(".github/workflows/brief.yml pins a newer brief — left as-is; run init from that version")
        else:
            wf.write_text(CI_WORKFLOW, encoding="utf-8")
            actions.append("refreshed .github/workflows/brief.yml to this brief version")
        return
    wf.parent.mkdir(parents=True, exist_ok=True)
    wf.write_text(CI_WORKFLOW, encoding="utf-8")
    actions.append("wrote .github/workflows/brief.yml (PR enforcement)")


def _install_skills(repo: Path, actions: list[str]) -> None:
    here = Path(__file__).resolve()
    src = next(
        (c for c in (here.parent / "_skills", here.parents[2] / "skills") if c.is_dir()),
        None,
    )  # packaged (wheel) first, then repo-root (editable)
    if src is None:
        actions.append("skills source not found — skipped --with-skills")
        return
    dest = repo / ".claude" / "skills"
    dest.mkdir(parents=True, exist_ok=True)
    n = 0
    for d in sorted(src.iterdir()):
        if d.is_dir() and (d / "SKILL.md").exists():
            shutil.copytree(d, dest / d.name, dirs_exist_ok=True)
            n += 1
    actions.append(f"installed {n} skills into .claude/skills/")


def init_vault(
    repo: Path,
    project_id: str | None = None,
    with_skills: bool = False,
    ci: bool = False,
    hook: bool = False,
) -> list[str]:
    """Scaffold + inject the convention. Hook-free by default; enforcement is CI (`ci=True`)."""
    actions: list[str] = []
    brief_dir = repo / ".brief"
    (brief_dir / "docs").mkdir(parents=True, exist_ok=True)
    (brief_dir / "amendments").mkdir(parents=True, exist_ok=True)
    actions.append("created .brief/docs and .brief/amendments")

    pj = brief_dir / "project.yaml"
    if not pj.exists():
        pid = project_id or repo.resolve().name
        pj.write_text(f"id: {pid}\ntitle: {pid}\n", encoding="utf-8")
        actions.append(f"wrote .brief/project.yaml (id: {pid})")

    _inject_snippet(_agents_file(repo), actions)
    if with_skills:
        _install_skills(repo, actions)
    if ci:
        _install_ci(repo, actions)
    if hook:
        _install_hook(repo, actions)
    return actions
