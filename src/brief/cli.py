"""brief CLI — thin slice: `resolve` + `check` (L0 gate)."""
from __future__ import annotations

import json
from pathlib import Path

import typer

from . import gitutil
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
    # Globs and doc paths are root-relative; from a subdirectory git would report cwd-relative ones.
    repo_path = gitutil.toplevel(Path(repo).resolve())
    bd = _brief_dir(brief, repo_path)
    from .init import version_drift

    if drift := version_drift(repo_path):
        typer.echo(f"brief: warning — {drift}", err=True)
    violations = gate_check(repo_path, bd, base)
    for v in violations:
        if v.kind == "pending-ratification" and not v.blocking:
            typer.echo(f"brief: pending ratification — {v.doc_id}#{v.anchor_id}: the decision edit carries its amendment.")
            typer.echo(f"      {v.detail}" if "ratified by" in v.detail else
                       "      merging this PR ratifies it (CI runs `brief ratify --pending`); review it as a decision change.")
    blocking = [v for v in violations if v.blocking]
    if not blocking:
        typer.echo("brief: OK — no governance violations")
        raise typer.Exit(0)
    typer.echo("brief: BLOCKED — governance violations:", err=True)
    for v in blocking:
        if v.kind == "pending-ratification" and base:
            typer.echo(f"  ⚠ {v.doc_id}#{v.anchor_id} — {v.detail}", err=True)
            typer.echo("      stop and wait: a maintainer answers in the amendment's PR thread; answer questions there.", err=True)
        elif v.kind == "amendment-rejected":
            typer.echo(f"  ✗ {v.doc_id}#{v.anchor_id} — {v.detail}", err=True)
            typer.echo(
                f"      revise: edit .brief/amendments/{v.anchor_id}.md (and the proposed text) to answer the reason;\n"
                "      or withdraw: restore the decision and delete the amendment and its amend-proposed line.\n"
                "      never edit .brief/RATIFICATIONS.",
                err=True,
            )
        elif v.kind == "proposal-only":
            typer.echo(f"  ✗ {v.doc_id or '?'}#{v.anchor_id} — {v.detail}", err=True)
            typer.echo(
                f"      put the proposed text in the live decision in this PR (every anchor it changes needs its\n"
                f"      amendment), so the merge ratifies it; or withdraw {v.files[0]}.\n"
                "      never touch versions/ or run `brief ratify` yourself.",
                err=True,
            )
        elif v.kind == "untrusted-verdict":
            typer.echo(f"  ✗ untrusted-verdict — {v.detail}", err=True)
            typer.echo("      .brief/RATIFICATIONS is written only by CI; restore it.", err=True)
        elif v.kind == "pending-ratification":
            typer.echo(f"  ⚠ {v.doc_id}#{v.anchor_id} — decision edit with its amendment on the default branch: a commit can't ratify it.", err=True)
            typer.echo(
                "      commit it on a branch and open a PR: CI reports it as pending, and merging the PR ratifies it.\n"
                "      (without CI, a human ratifies it locally: `brief ratify <anchor> --by <name>`.)",
                err=True,
            )
        elif v.kind == "ratified-edit":
            typer.echo(f"  ✗ {v.doc_id} — ratified decision is READ-ONLY; you may not edit it to pass.", err=True)
            typer.echo(
                "      to change it: write .brief/amendments/<anchor>.md and record\n"
                "      '<anchor> amend-proposed: <why>' in .brief/SIGNOFF (an amendment per anchor you change),\n"
                "      then stop: a human ratifies it by merging the PR.",
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
        elif v.kind == "empty-glob":
            typer.echo(f"  ✗ {v.doc_id}#{v.anchor_id} — {v.detail}", err=True)
        else:
            typer.echo(f"  ✗ broken-ref — {v.detail}", err=True)
    raise typer.Exit(1)


@app.command()
def triage(
    repo: str = typer.Option(".", "--repo", help="repo root"),
    brief: str = typer.Option(None, "--brief", help="path to .brief dir"),
    base: str = typer.Option(None, "--base", help="triage the range base..HEAD instead of staged changes"),
    amendments: bool = typer.Option(False, "--amendments", help="rate pending amendments instead: auto-ratifiable or escalate (writes nothing)"),
    json_out: bool = typer.Option(False, "--json", help="with --amendments: emit JSON (verdict, stamp, per-amendment scores, summary)"),
):
    """Clear sign-off asks a System One model rates as conforming (optional: brief[s1] + TYPESAFE_API_KEY)."""
    from .triage import THRESHOLD
    from .triage import triage as run_triage
    from .triage import triage_amendments

    repo_path = gitutil.toplevel(Path(repo).resolve())
    if amendments:
        from .triage import verdict

        out = verdict(triage_amendments(repo_path, _brief_dir(brief, repo_path), base))
        if json_out:
            out["summary"] = _amendment_summary(out)
            typer.echo(json.dumps(out, indent=2))
            return
        typer.echo(_amendment_summary(out))
        return
    verdicts = run_triage(repo_path, _brief_dir(brief, repo_path), base)
    if not verdicts:
        typer.echo("brief triage: no sign-off asks")
        return
    for v in verdicts:
        if v.cleared:
            typer.echo(f"  cleared {v.doc_id}#{v.anchor_id} (p={v.p:.3f} < {THRESHOLD}): conforms line written to .brief/SIGNOFF")
        elif v.p is None:
            typer.echo(f"  ask {v.doc_id}#{v.anchor_id}: no model opinion — sign off yourself")
        else:
            typer.echo(f"  ask {v.doc_id}#{v.anchor_id} (p={v.p:.3f}): may cut against the decision — read it, then sign off or amend")
    if base and any(v.cleared for v in verdicts):
        typer.echo("commit .brief/SIGNOFF to record the cleared asks")


def _amendment_summary(out: dict) -> str:
    if out["verdict"] == "none":
        return "brief triage: no pending amendments"
    head = {
        "auto-ratifiable": f"brief: auto-ratifiable ({out['stamp']}) — the model rates every amendment low-risk; CI merges the PR when every other check is green (the model's ratification; repo variable BRIEF_AUTO_MERGE=off disables it).",
        "escalate": "brief: needs-ratification — a human should review this decision change; merging the PR ratifies it.",
    }[out["verdict"]]
    lines = [head]
    for a in out["amendments"]:
        p = "" if a["review"] is None else f" p={a['review']:.3f}"
        lines.append(f"  - {a['doc_id']}#{a['anchor_id']}{p}: {a['why']}")
    return "\n".join(lines)


@app.command()
def features(
    files: list[str] = typer.Argument(None, help="only features these repo-relative paths touch (e.g. a diff's files)"),
    brief: str = typer.Option(None, "--brief", help="path to .brief dir"),
    json_out: bool = typer.Option(False, "--json", help="emit JSON"),
):
    """List the feature map: each feature's ref and paths, or only those FILES touch."""
    from .features import load_features, touched

    feats = load_features(_brief_dir(brief, Path.cwd()))
    if files:
        feats = touched(feats, files)
    if json_out:
        typer.echo(json.dumps([f.to_dict() for f in feats], indent=2))
        return
    for f in feats:
        typer.echo(f"{f.ref}  {f.title}")
        for g in f.paths:
            typer.echo(f"    {g}")


@app.command()
def init(
    repo: str = typer.Option(".", "--repo", help="repo to initialize"),
    project_id: str = typer.Option(None, "--id", help="project id (default: directory name)"),
    with_skills: bool = typer.Option(False, "--with-skills", help="install brief skills into .claude/skills/"),
    ci: bool = typer.Option(False, "--ci", help="write a CI workflow that enforces the gate on PRs"),
    hook: bool = typer.Option(False, "--hook", help="also install a local pre-commit hook (opt-in; CI is preferred)"),
    kypp_url: str = typer.Option(None, "--kypp-url", help="with --ci: the kypp Worker CI triage calls with an OIDC token (a TYPESAFE_BASE_URL repo variable overrides it; default: keep the workflow's)"),
):
    """Scaffold .brief/ + inject the AGENTS convention. Enforcement is CI (--ci); the local hook is opt-in (--hook)."""
    from .init import init_vault
    from .templates import kypp_url as check_url

    if kypp_url is not None:
        try:
            kypp_url = check_url(kypp_url)
        except ValueError as e:
            raise typer.BadParameter(str(e), param_hint="--kypp-url")
    for a in init_vault(Path(repo).resolve(), project_id, with_skills=with_skills, ci=ci, hook=hook, kypp_url=kypp_url):
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
    anchor: str = typer.Argument(None, help="the amended anchor (omit with --pending)"),
    by: str = typer.Option(None, "--by", help="who is ratifying (recorded with the amendment)"),
    pending: bool = typer.Option(False, "--pending", help="ratify every amendment whose decision the tree already changed (CI, after a merge)"),
    triage_json: str = typer.Option(None, "--triage", help="with --pending: the merged PR's `brief triage --amendments --json`; the model is the ratifier (CI auto-merge)"),
    push: bool = typer.Option(False, "--push", help="with --pending: commit .brief as github-actions[bot] and push the branch (CI)"),
    brief: str = typer.Option(None, "--brief", help="path to .brief dir"),
):
    """Ratify an amendment: publish a new revision + archive the proposal. Run after editing the decision."""
    from .ratify import RatifyError
    from .ratify import ratify as do_ratify
    from .ratify import ratify_and_push, ratify_pending

    if pending == bool(anchor) or ((triage_json or push) and not pending):
        typer.echo("ratify error: give an anchor or --pending (exactly one); --triage and --push need --pending", err=True)
        raise typer.Exit(2)
    bd = _brief_dir(brief, Path.cwd())
    model = json.loads(Path(triage_json).read_text()) if triage_json else None
    held: list[str] = []
    try:
        if push:
            done, held = ratify_and_push(gitutil.toplevel(Path.cwd()), bd, by, model)
        else:
            done = ratify_pending(bd, by, held, model) if pending else [do_ratify(bd, anchor, by)]
    except (RatifyError, FileNotFoundError, FileExistsError) as e:
        typer.echo(f"ratify error: {e}", err=True)
        raise typer.Exit(1)
    for h in held:
        typer.echo(f"brief: held {h} — its doc stays unpublished; a human ratifies by hand (`brief ratify <anchor>`)", err=True)
    if not done and not held:
        typer.echo("brief: nothing pending ratification")
    for r in done:
        typer.echo(f"brief: ratified {r.anchor} → {r.doc_id} @ {r.rev:04d}; amendment archived to {r.archived}")


thread_app = typer.Typer(help="CI only: per-amendment PR threads (needs `gh` and GH_TOKEN).")
app.add_typer(thread_app, name="thread")


def _gh_context(repo_name: str | None, brief: str | None) -> tuple[str, Path, Path]:
    import os

    name = repo_name or os.environ.get("GITHUB_REPOSITORY")
    if not name:
        typer.echo("thread: give --repo-name or set GITHUB_REPOSITORY", err=True)
        raise typer.Exit(2)
    repo_path = gitutil.toplevel(Path.cwd())
    return name, repo_path, _brief_dir(brief, repo_path)


@thread_app.command("escalate")
def thread_escalate(
    pr: int = typer.Option(..., "--pr"),
    triage_json: str = typer.Option(..., "--triage", help="`brief triage --amendments --json` output file"),
    repo_name: str = typer.Option(None, "--repo-name", help="owner/repo (default: $GITHUB_REPOSITORY)"),
    brief: str = typer.Option(None, "--brief", help="path to .brief dir"),
):
    """Open a thread per escalated amendment and record it as escalated (run on the PR head)."""
    from .threads import CliGH, escalate

    name, repo_path, bd = _gh_context(repo_name, brief)
    for line in escalate(CliGH(), name, pr, json.loads(Path(triage_json).read_text()), repo_path, bd):
        typer.echo(f"brief: {line}")


@thread_app.command("command")
def thread_command(
    event: str = typer.Option(..., "--event", help="the comment event payload ($GITHUB_EVENT_PATH)"),
    repo_name: str = typer.Option(None, "--repo-name", help="owner/repo (default: $GITHUB_REPOSITORY)"),
    brief: str = typer.Option(None, "--brief", help="path to .brief dir"),
):
    """Record a maintainer's `/ratify` or `/reject` (run on the PR head)."""
    from .threads import CliGH, command

    name, repo_path, bd = _gh_context(repo_name, brief)
    typer.echo(f"brief: {command(CliGH(), name, json.loads(Path(event).read_text()), repo_path, bd)}")


@thread_app.command("verify")
def thread_verify(
    pr: int = typer.Option(..., "--pr"),
    base: str = typer.Option(..., "--base", help="the PR's base ref, e.g. origin/main"),
    repo_name: str = typer.Option(None, "--repo-name", help="owner/repo (default: $GITHUB_REPOSITORY)"),
    brief: str = typer.Option(None, "--brief", help="path to .brief dir"),
):
    """Fail unless every verdict line the PR adds matches the bot's own reply on the PR."""
    from .threads import CliGH, verify

    name, repo_path, bd = _gh_context(repo_name, brief)
    bad = verify(CliGH(), name, pr, repo_path, bd, base)
    for line in bad:
        typer.echo(f"brief: unattested verdict (no matching github-actions[bot] reply on #{pr}): {line}", err=True)
    raise typer.Exit(1 if bad else 0)


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


@app.command()
def doctor(
    repo: str = typer.Option(".", "--repo", help="repo root"),
    brief: str = typer.Option(None, "--brief", help="path to .brief dir"),
    json_out: bool = typer.Option(False, "--json", help="emit JSON (machine-first — what an agent acts on)"),
    strict: bool = typer.Option(False, "--strict", help="exit nonzero on any warning (opt-in CI fail; default is advisory)"),
):
    """Advisory lint for latent governance drift the gate doesn't block. Agents run this and close what it flags."""
    from . import doctor as doctor_mod

    repo_path = gitutil.toplevel(Path(repo).resolve())
    bd = _brief_dir(brief, repo_path)
    report = doctor_mod.run(repo_path, bd)
    if json_out:
        typer.echo(json.dumps(report.to_dict(), indent=2))
    else:
        typer.echo(doctor_mod.render_md(report))
    raise typer.Exit(1 if strict and report.warnings else 0)


@app.command()
def evidence(
    repo: str = typer.Option(".", "--repo", help="repo root"),
    brief: str = typer.Option(None, "--brief", help="path to .brief dir"),
    base: str = typer.Option(None, "--base", help="the range base..HEAD instead of staged changes"),
    json_out: bool = typer.Option(False, "--json", help="emit JSON"),
    model: bool = typer.Option(True, "--model/--no-model", help="ask a configured System One model which unlinked decisions the edit may undermine (shadow)"),
):
    """Advisory: what changed in each pending amendment, with sources and linked decisions. Writes nothing."""
    from . import evidence as ev_mod

    repo_path = gitutil.toplevel(Path(repo).resolve())
    evs = ev_mod.evidence(repo_path, _brief_dir(brief, repo_path), base, model=model)
    typer.echo(json.dumps(ev_mod.to_dict(evs), indent=2) if json_out else ev_mod.render_md(evs))


@app.command()
def backfill(
    repo: str = typer.Option(".", "--repo", help="repo to scan"),
    json_out: bool = typer.Option(False, "--json", help="also write map.json"),
):
    """Scan code + docs + comments and write a context map for reconstructing the decision layer."""
    from . import scan

    repo_path = Path(repo).resolve()
    m = scan.build_map(repo_path)
    out_dir = repo_path / ".brief" / "backfill"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "map.md").write_text(scan.render_map_md(m), encoding="utf-8")
    if json_out:
        import json as _json

        (out_dir / "map.json").write_text(_json.dumps(m.to_dict(), indent=2), encoding="utf-8")

    typer.echo(
        f"brief: mapped {len(m.docs)} docs ({len(m.decision_docs)} decision-genre), "
        f"{len(m.signals)} code signals, {len(m.modules)} modules"
    )
    if m.untracked_decisions:
        typer.echo(f"  ⚠ {len(m.untracked_decisions)} untracked decision doc(s) — a silent-drift risk", err=True)
    if m.status_less_decisions:
        typer.echo(f"  ⚠ {len(m.status_less_decisions)} decision doc(s) with no status field", err=True)
    typer.echo(f"  wrote {out_dir / 'map.md'}")
    typer.echo("  next: run the `brief-backfill` skill (or hand map.md to an agent) to reconstruct the decision layer.")


def main() -> None:
    """Console entry: a malformed .brief file is a one-line error, not a traceback."""
    from .docs import DocError

    try:
        app()
    except DocError as e:
        typer.echo(f"brief: {e}", err=True)
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
