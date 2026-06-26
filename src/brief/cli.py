"""brief CLI — thin slice: `resolve` + `check` (L0 gate)."""
from __future__ import annotations

import json
from pathlib import Path

import typer

from .docs import find_brief_dir
from .gate import check as gate_check
from .resolve import ResolveError
from .resolve import resolve as resolve_ref

app = typer.Typer(add_completion=False, help="brief — doc-driven dev governance (thin slice)")


def _brief_dir(explicit: str | None, start: Path) -> Path:
    if explicit:
        p = Path(explicit)
        return p if p.name == ".brief" else p / ".brief"
    bd = find_brief_dir(start)
    if bd is None:
        typer.echo(f"no .brief directory found from {start}", err=True)
        raise typer.Exit(2)
    return bd


@app.command()
def resolve(
    ref: str,
    brief: str = typer.Option(None, "--brief", help="path to .brief dir (default: walk up from cwd)"),
    json_out: bool = typer.Option(False, "--json", help="emit JSON"),
):
    """Resolve a doc:// ref to its file, anchor lines, body, and hash."""
    bd = _brief_dir(brief, Path.cwd())
    try:
        res = resolve_ref(ref, bd)
    except (ResolveError, ValueError) as e:
        typer.echo(f"resolve error: {e}", err=True)
        raise typer.Exit(1)
    if json_out:
        typer.echo(json.dumps(res.to_dict(), indent=2))
        return
    typer.echo(res.ref)
    typer.echo(f"  path:  {res.path}")
    if res.anchor:
        typer.echo(f"  lines: {res.start_line}-{res.end_line}")
        typer.echo(f"  title: {res.title}")
        typer.echo(f"  hash:  {res.hash}")
        if res.stale:
            typer.echo(f"  ⚠ STALE: this anchor changed in @{res.stale_since} (you resolved @{res.rev})")


@app.command()
def check(
    repo: str = typer.Option(".", "--repo", help="repo root"),
    brief: str = typer.Option(None, "--brief", help="path to .brief dir"),
    base: str = typer.Option(None, "--base", help="CI mode: check the range base..HEAD (e.g. origin/main) instead of staged changes"),
):
    """L0 gate. Run before committing (staged), or with --base for CI on a PR range."""
    repo_path = Path(repo).resolve()
    bd = _brief_dir(brief, repo_path)
    violations = gate_check(repo_path, bd, base)
    if not violations:
        typer.echo("brief: OK — no governance violations")
        raise typer.Exit(0)
    typer.echo("brief: BLOCKED — governance violations:", err=True)
    for v in violations:
        if v.kind == "ratified-edit":
            typer.echo(f"  ✗ {v.doc_id} — ratified decision is READ-ONLY; you may not edit it to pass.", err=True)
            typer.echo(
                f"      to change it: write .brief/amendments/<anchor>.md and record\n"
                f"      '<anchor> amend-proposed: <why>' in .brief/SIGNOFF, then stop — it needs human ratification.",
                err=True,
            )
        elif v.kind == "needs-conformance":
            typer.echo(f"  ✗ {v.doc_id}#{v.anchor_id} — {v.detail}", err=True)
            for f in v.files:
                typer.echo(f"      changed: {f}", err=True)
            typer.echo(
                f"      fix: echo '{v.anchor_id} conforms: <why>' >> .brief/SIGNOFF   (code still satisfies the decision)\n"
                f"        or: echo '{v.anchor_id} amend-proposed: <why>' >> .brief/SIGNOFF + write .brief/amendments/{v.anchor_id}.md",
                err=True,
            )
        elif v.kind == "amendment-required":
            typer.echo(f"  ⚠ {v.doc_id}#{v.anchor_id} — {v.detail}", err=True)
            typer.echo("      this is a correct escalation: the code cannot land until the amendment is ratified.", err=True)
        else:
            typer.echo(f"  ✗ broken-ref — {v.detail}", err=True)
    raise typer.Exit(1)


@app.command()
def init(
    repo: str = typer.Option(".", "--repo", help="repo to initialize"),
    project_id: str = typer.Option(None, "--id", help="project id (default: directory name)"),
    with_skills: bool = typer.Option(False, "--with-skills", help="install brief skills into .claude/skills/"),
    ci: bool = typer.Option(False, "--ci", help="write a CI workflow that enforces the gate on PRs"),
    hook: bool = typer.Option(False, "--hook", help="also install a local pre-commit hook (opt-in; CI is preferred)"),
):
    """Scaffold .brief/ + inject the AGENTS convention. Enforcement is CI (--ci); the local hook is opt-in (--hook)."""
    from .init import init_vault

    for a in init_vault(Path(repo).resolve(), project_id, with_skills=with_skills, ci=ci, hook=hook):
        typer.echo(f"  {a}")
    typer.echo("brief: ready — decisions in .brief/docs/. Agents run `brief check` before committing; add --ci to enforce on PRs.")


@app.command()
def publish(
    doc_id: str,
    brief: str = typer.Option(None, "--brief", help="path to .brief dir"),
):
    """Freeze the live decision doc as the next immutable revision; update `latest`."""
    from . import versions

    bd = _brief_dir(brief, Path.cwd())
    try:
        rev = versions.publish(bd, doc_id)
    except (FileNotFoundError, FileExistsError) as e:
        typer.echo(f"publish error: {e}", err=True)
        raise typer.Exit(1)
    typer.echo(f"brief: published {doc_id} @ {rev:04d} (now latest)")


@app.command()
def ratify(
    anchor: str,
    by: str = typer.Option(None, "--by", help="who is ratifying (recorded with the amendment)"),
    brief: str = typer.Option(None, "--brief", help="path to .brief dir"),
):
    """Ratify an amendment: publish a new revision + archive the proposal. Run after editing the decision."""
    from .ratify import RatifyError
    from .ratify import ratify as do_ratify

    bd = _brief_dir(brief, Path.cwd())
    try:
        r = do_ratify(bd, anchor, by)
    except (RatifyError, FileNotFoundError, FileExistsError) as e:
        typer.echo(f"ratify error: {e}", err=True)
        raise typer.Exit(1)
    typer.echo(f"brief: ratified {r.anchor} → {r.doc_id} @ {r.rev:04d}; amendment archived to {r.archived}")


@app.command()
def pin(
    paths: list[str] = typer.Argument(None, help="files to pin (default: staged code files)"),
    repo: str = typer.Option(".", "--repo", help="repo root"),
    brief: str = typer.Option(None, "--brief", help="path to .brief dir"),
):
    """Rewrite @latest/@current/@draft refs in code to the concrete latest revision."""
    from . import gitutil
    from .pin import pin_files

    repo_path = Path(repo).resolve()
    bd = _brief_dir(brief, repo_path)
    targets = list(paths) if paths else [
        str(repo_path / f) for f in gitutil.changed_files(repo_path) if not f.startswith(".brief/")
    ]
    changes = pin_files(targets, bd)
    pinned = [c for c in changes if c.new]
    for c in pinned:
        typer.echo(f"  {c.old} → @{c.new.split('@')[1].split('#')[0]}  ({c.file})")
    for c in changes:
        if not c.new:
            typer.echo(f"  skip {c.old} — {c.note}", err=True)
    typer.echo(f"brief: pinned {len(pinned)} ref(s)")


if __name__ == "__main__":
    app()
