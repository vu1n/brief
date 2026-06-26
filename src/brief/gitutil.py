"""Minimal git plumbing for the gate.

Works over either the staged diff (base=None, local pre-commit / self-check) or a
commit range base..HEAD (for CI on a PR). Range mode resolves `base` to the
merge-base with HEAD, so it reflects only what the branch introduced.
"""
from __future__ import annotations

import subprocess
from pathlib import Path


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
    if base:
        out = _git(repo, "diff", "--name-only", base, "HEAD")
    else:
        out = _git(repo, "diff", "--cached", "--name-only")
    return [ln for ln in out.splitlines() if ln.strip()]


def added_lines(repo: Path, path: str, base: str | None = None) -> list[str]:
    """Added (+) lines for one path, staged (base=None) or over base..HEAD."""
    args = ["diff", "-U0", base, "HEAD", "--", path] if base else ["diff", "--cached", "-U0", "--", path]
    try:
        out = _git(repo, *args)
    except subprocess.CalledProcessError:
        return []
    return [ln[1:] for ln in out.splitlines() if ln.startswith("+") and not ln.startswith("+++")]


def content_at(repo: Path, path: str, ref: str) -> str:
    """Content of a path at a ref (e.g. the baseline), or '' if absent."""
    try:
        return _git(repo, "show", f"{ref}:{path}")
    except subprocess.CalledProcessError:
        return ""
