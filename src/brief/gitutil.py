"""Minimal git plumbing for the gate.

Works over either the staged diff (base=None, local pre-commit / self-check) or a
commit range base..HEAD (for CI on a PR). Range mode resolves `base` to the
merge-base with HEAD, so it reflects only what the branch introduced.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

_HUNK_RE = re.compile(r"^@@ -\S+ \+(\d+)(?:,(\d+))? @@", re.MULTILINE)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def merge_base(repo: Path, ref: str) -> str:
    return _git(repo, "merge-base", ref, "HEAD").strip()


def changed_files(repo: Path, base: str | None = None) -> list[str]:
    # --no-renames: a rename must report its old path too, or moving a locked decision
    # aside (then demoting the copy) would never show the original as changed.
    if base:
        out = _git(repo, "diff", "--no-renames", "--name-only", base, "HEAD")
    else:
        out = _git(repo, "diff", "--cached", "--no-renames", "--name-only")
    return [ln for ln in out.splitlines() if ln.strip()]


def added_lines(repo: Path, path: str, base: str | None = None) -> list[str]:
    """Added (+) lines for one path, staged (base=None) or over base..HEAD."""
    args = ["diff", "-U0", base, "HEAD", "--", path] if base else ["diff", "--cached", "-U0", "--", path]
    try:
        out = _git(repo, *args)
    except subprocess.CalledProcessError:
        return []
    return [ln[1:] for ln in out.splitlines() if ln.startswith("+") and not ln.startswith("+++")]


def diff(repo: Path, paths: list[str], base: str | None = None) -> str:
    """Unified diff for `paths`, staged (base=None) or over base..HEAD."""
    args = ["diff", base, "HEAD", "--", *paths] if base else ["diff", "--cached", "--", *paths]
    try:
        return _git(repo, *args)
    except subprocess.CalledProcessError:
        return ""


def removed_lines(repo: Path, path: str, base: str | None = None) -> list[str]:
    """Removed (-) lines for one path, staged (base=None) or over base..HEAD."""
    args = ["diff", "-U0", base, "HEAD", "--", path] if base else ["diff", "--cached", "-U0", "--", path]
    try:
        out = _git(repo, *args)
    except subprocess.CalledProcessError:
        return []
    return [ln[1:] for ln in out.splitlines() if ln.startswith("-") and not ln.startswith("---")]


def changed_lines(repo: Path, path: str, base: str | None = None) -> set[int]:
    """1-based line numbers on the change's far side that a hunk touches. A pure deletion
    marks the lines on either side of where it happened."""
    args = ["diff", "-U0", base, "HEAD", "--", path] if base else ["diff", "--cached", "-U0", "--", path]
    try:
        out = _git(repo, *args)
    except subprocess.CalledProcessError:
        return set()
    lines: set[int] = set()
    for m in _HUNK_RE.finditer(out):
        start, count = int(m.group(1)), int(m.group(2) or 1)
        lines.update(range(start, start + count) if count else (start, start + 1))
    return lines


def content_at(repo: Path, path: str, ref: str) -> str:
    """Content of a path at a ref (e.g. the baseline), or '' if absent."""
    try:
        return _git(repo, "show", f"{ref}:{path}")
    except subprocess.CalledProcessError:
        return ""


def content_after(repo: Path, path: str, base: str | None = None) -> str:
    """Content of a path on the change's far side: HEAD in range mode, the index when
    staged. '' if absent."""
    return content_at(repo, path, "HEAD" if base else "")


def files_at(repo: Path, ref: str, prefix: str) -> list[str]:
    """Paths tracked under `prefix` at `ref`. Empty if the ref doesn't exist (e.g. no
    commits yet)."""
    try:
        out = _git(repo, "ls-tree", "-r", "--name-only", ref, "--", prefix)
    except subprocess.CalledProcessError:
        return []
    return [ln for ln in out.splitlines() if ln.strip()]


def toplevel(path: Path) -> Path:
    """The git work-tree root containing `path` (paths from git are relative to it), else `path`."""
    try:
        return Path(_git(path, "rev-parse", "--show-toplevel").strip())
    except (subprocess.CalledProcessError, FileNotFoundError):
        return path


def tracked_files(repo: Path) -> list[str]:
    """Every git-tracked path (repo-relative). Empty if not a repo. For whole-repo scans."""
    try:
        out = _git(repo, "ls-files")
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    return [ln for ln in out.splitlines() if ln.strip()]
