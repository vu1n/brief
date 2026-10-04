"""Run the context-strategy eval: build a workspace per (condition, task, seed), run a
headless Claude Code agent in it, grade the result.

    uv run --python 3.12 python eval/run.py --model claude-sonnet-5-5 --seeds 3 --jobs 6

Results land in eval/results/<model>/<cond>.<task>.<seed>.json; workspaces in --work
(default: a temp dir) so a run can be inspected afterwards. See eval/README.md.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "src"))

from decisions import DECISIONS, MEMORY  # noqa: E402
from tasks import SUFFIX, TASKS  # noqa: E402

from brief.templates import AGENTS_SNIPPET  # noqa: E402

# N: code only. M: + stale memory. C/B: + plain docs / Brief. MC/MB: memory + docs.
# U: plain docs framed the common way — "the source of truth, keep it up to date" — the
# framing Brief's original pilot found invites rewriting a decision to fit the code.
CONDITIONS = ["N", "M", "C", "MC", "B", "MB", "U"]
BASE_CLAUDE_MD = "# ledger\n\nA small ledger library. Run tests with `python -m pytest -q`.\n"
UPDATE_DOCS_NOTE = (
    "\n## Design decisions\n\n`docs/DECISIONS.md` is the source of truth for design decisions, "
    "with `# Why:` comments next to the code they govern. Keep it up to date: when you change "
    "behavior, update the relevant decision and comment to match.\n"
)
PLAIN_DOCS_NOTE = (
    "\n## Design decisions\n\nDesign decisions are documented in `docs/DECISIONS.md` and in "
    "`# Why:` comments next to the code they govern.\n"
)


def docs_of(cond: str) -> str:
    """"C" (plain docs), "B" (Brief) or "" (no docs) for a condition."""
    if cond == "U":
        return "C"
    return cond[-1] if cond[-1] in "CB" else ""


def _git(ws: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(ws), *args], check=True,
                          capture_output=True, text=True).stdout


def _render(text: str, cond: str) -> str:
    docs = docs_of(cond)
    for d in DECISIONS:
        marker = "{{WHY:%s}}" % d["key"]
        if docs == "C":
            line = f'# Why: {d["summary"]} (see docs/DECISIONS.md, "{d["title"]}")'
        elif docs == "B":
            line = f'# Context: doc://ledger/{d["anchor"]}@0001#{d["anchor"]} — {d["summary"]}'
        else:
            text = text.replace(marker + "\n", "")
            continue
        text = text.replace(marker, line)
    return text


def build(ws: Path, cond: str, env: dict) -> None:
    shutil.copytree(HERE / "fixture", ws)
    for p in ws.rglob("*.py"):
        p.write_text(_render(p.read_text(), cond))
    docs = docs_of(cond)
    claude_md = BASE_CLAUDE_MD
    if docs == "C":
        claude_md += UPDATE_DOCS_NOTE if cond == "U" else PLAIN_DOCS_NOTE
        body = "# Design decisions\n\n" + "\n\n".join(
            f'## {d["title"]}\n\n{d["body"]}' for d in DECISIONS) + "\n"
        (ws / "docs").mkdir()
        (ws / "docs" / "DECISIONS.md").write_text(body)
    if docs == "B":
        claude_md += "\n" + AGENTS_SNIPPET
        bd = ws / ".brief" / "docs"
        bd.mkdir(parents=True)
        (ws / ".brief" / "project.yaml").write_text("id: ledger\ntitle: ledger\n")
        (ws / ".brief" / "SIGNOFF").write_text("")
        for d in DECISIONS:
            globs = "\n".join(f'  - "{g}"' for g in d["related_code"])
            (bd / f'{d["anchor"]}.md').write_text(
                f'---\nid: {d["anchor"]}\ntitle: {d["title"]}\nstatus: active\n'
                f'related_code:\n{globs}\n---\n\n<!-- brief:anchor {d["anchor"]} -->\n'
                f'## {d["title"]}\n\n{d["body"]}\n')
    (ws / "CLAUDE.md").write_text(claude_md)
    _git(ws, "init", "-q")
    _git(ws, "config", "user.email", "eval@example.com")
    _git(ws, "config", "user.name", "eval")
    if docs == "B":
        for d in DECISIONS:
            subprocess.run(["brief", "publish", d["anchor"]], cwd=ws, env=env, check=True,
                           capture_output=True)
    _git(ws, "add", "-A")
    _git(ws, "commit", "-qm", "baseline")


def agent_env(home: Path) -> dict:
    env = {k: v for k, v in os.environ.items()
           if k not in ("CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD", "VIRTUAL_ENV")}
    env["HOME"] = str(home)  # no user CLAUDE.md, memory, skills or plugins
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PATH"] = f"{Path(sys.executable).parent}:{env['PATH']}"  # python+pytest+brief
    return env


def run_agent(ws: Path, cond: str, task: dict, model: str, env: dict, timeout: int) -> dict:
    cmd = ["claude", "-p", task["prompt"] + SUFFIX, "--model", model,
           "--output-format", "json", "--setting-sources", "project",
           "--disable-slash-commands", "--strict-mcp-config", "--no-session-persistence",
           "--permission-mode", "acceptEdits",
           "--allowedTools", "Bash", "Read", "Edit", "Write", "Glob", "Grep"]
    if cond.startswith("M"):
        cmd += ["--append-system-prompt", MEMORY]
    t0 = time.time()
    try:
        p = subprocess.run(cmd, cwd=ws, env=env, capture_output=True, text=True,
                           timeout=timeout, stdin=subprocess.DEVNULL)
        out = json.loads(p.stdout.strip().splitlines()[-1]) if p.stdout.strip() else {}
        err = p.stderr[-2000:] if p.returncode else ""
    except subprocess.TimeoutExpired:
        out, err = {}, "timeout"
    except json.JSONDecodeError:
        out, err = {}, "bad json: " + p.stdout[-500:]
    return {
        "seconds": round(time.time() - t0, 1),
        "cost_usd": out.get("total_cost_usd"),
        "turns": out.get("num_turns"),
        "final": (out.get("result") or "")[-4000:],
        "agent_error": err,
    }


def _pytest(ws: Path, env: dict, target: str) -> dict[str, bool]:
    p = subprocess.run([sys.executable, "-m", "pytest", "-q", "-rA", "--tb=no",
                        "-p", "no:cacheprovider", target],
                       cwd=ws, env=env, capture_output=True, text=True, timeout=300)
    res = {}
    for m in re.finditer(r"^(PASSED|FAILED|ERROR) \S+?::(\w+)", p.stdout, re.M):
        res[m.group(2)] = m.group(1) == "PASSED"
    if not res:  # collection error (e.g. module missing) → every hidden test failed
        res["collection"] = False
    return res


def grade(ws: Path, task_id: str, task: dict, cond: str, env: dict) -> dict:
    hidden = ws / "tests" / "test_zz_hidden_eval.py"
    visible = _pytest(ws, env, "tests/test_basic.py")
    hidden.write_text(task["hidden"])
    hid = _pytest(ws, env, str(hidden.relative_to(ws)))
    hidden.unlink()

    stale = [f"{f}: {s}" for f, s in task["stale_grep"]
             if (ws / f).exists() and s in _code_only(_added(ws, f))]
    base = _git(ws, "rev-list", "--max-parents=0", "HEAD").split()[0]
    _git(ws, "add", "-A")  # so new files show in the baseline diff
    changed = _git(ws, "diff", "--cached", "--name-status", base).splitlines()
    decision = next(d for d in DECISIONS if d["key"] == task["decision"])
    # Did the agent rewrite the decision it was bound by (doc text or its code comment)?
    decision_paths = {"C": ["docs/DECISIONS.md"], "B": [f'.brief/docs/{decision["anchor"]}.md']}
    edited = [p for p in decision_paths.get(docs_of(cond), [])
              if (ws / p).exists() is False or _git(ws, "diff", "--cached", base, "--", p).strip()]
    comment_gone = bool(docs_of(cond)) and decision["summary"] not in "".join(
        (ws / f).read_text() for f in decision["related_code"] if (ws / f).exists())
    amendments = sorted(str(p.relative_to(ws)) for p in (ws / ".brief" / "amendments").glob("*.md")) \
        if (ws / ".brief" / "amendments").exists() else []
    signoff = (ws / ".brief" / "SIGNOFF").read_text() if (ws / ".brief" / "SIGNOFF").exists() else ""
    gate = None
    if docs_of(cond) == "B":
        # Range mode from the baseline: agents sometimes commit, which would leave a staged
        # check looking at nothing.
        _git(ws, "add", "-A")
        if _git(ws, "status", "--porcelain").strip():
            _git(ws, "commit", "-qm", "eval: agent's uncommitted work")
        base = _git(ws, "rev-list", "--max-parents=0", "HEAD").split()[0]
        g = subprocess.run(["brief", "check", "--base", base], cwd=ws, env=env,
                           capture_output=True, text=True)
        gate = {"ok": g.returncode == 0, "out": (g.stdout + g.stderr)[-1500:]}
    return {
        "visible_ok": all(visible.values()),
        "hidden": hid,
        "hidden_ok": all(hid.values()),
        "stale": stale,
        "decision_doc_edited": edited,
        "decision_comment_removed": comment_gone,
        "amendments": amendments,
        "signoff": signoff[-1500:],
        "brief_check": gate,
        "changed_files": changed,
    }


def _code_only(text: str) -> str:
    """Drop comments and docstring-ish lines: a comment saying "not legacy_retry" is
    compliance, not staleness."""
    out = []
    for ln in text.splitlines():
        code = ln.split("#", 1)[0]
        if code.strip() and not code.strip().startswith(('"', "'")):
            out.append(code)
    return "\n".join(out)


def _added(ws: Path, f: str) -> str:
    """Text the agent added to f since the baseline commit (whole file if new)."""
    base = _git(ws, "rev-list", "--max-parents=0", "HEAD").split()[0]
    if not _git(ws, "ls-tree", "--name-only", base, "--", f).strip():
        return (ws / f).read_text()
    diff = _git(ws, "diff", base, "-U0", "--", f)
    return "\n".join(ln[1:] for ln in diff.splitlines() if ln.startswith("+") and not ln.startswith("+++"))


def one(cond: str, task_id: str, seed: int, model: str, work: Path, out: Path, timeout: int) -> str:
    dest = out / f"{cond}.{task_id}.{seed}.json"
    if dest.exists():
        return f"skip {dest.name}"
    ws = work / model / f"{cond}.{task_id}.{seed}"
    home = work / "home" / f"{cond}.{task_id}.{seed}"
    shutil.rmtree(ws, ignore_errors=True)
    home.mkdir(parents=True, exist_ok=True)
    env = agent_env(home)
    task = TASKS[task_id]
    build(ws, cond, env)
    run = run_agent(ws, cond, task, model, env, timeout)
    result = {"model": model, "cond": cond, "task": task_id, "seed": seed, "workspace": str(ws),
              **run, **grade(ws, task_id, task, cond, env)}
    dest.write_text(json.dumps(result, indent=1))
    return f"done {dest.name} hidden_ok={result['hidden_ok']} stale={bool(result['stale'])} ${run['cost_usd']}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="claude-sonnet-5-5")
    ap.add_argument("--conds", default=",".join(CONDITIONS))
    ap.add_argument("--tasks", default=",".join(TASKS))
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--work", default=str(Path(tempfile.gettempdir()) / "brief-eval"))
    ap.add_argument("--regrade", action="store_true", help="re-grade existing results from their workspaces")
    a = ap.parse_args()
    if a.regrade:
        for p in sorted((HERE / "results" / a.model).glob("*.json")):
            r = json.loads(p.read_text())
            ws = Path(r["workspace"])
            env = agent_env(Path(a.work) / "home" / p.stem)
            r.update(grade(ws, r["task"], TASKS[r["task"]], r["cond"], env))
            p.write_text(json.dumps(r, indent=1))
        print("regraded")
        return
    out = HERE / "results" / a.model
    out.mkdir(parents=True, exist_ok=True)
    work = Path(a.work)
    jobs = [(c, t, s) for s in range(a.seeds) for c in a.conds.split(",") for t in a.tasks.split(",")]
    with ThreadPoolExecutor(a.jobs) as ex:
        for msg in ex.map(lambda j: one(*j, a.model, work, out, a.timeout), jobs):
            print(msg, flush=True)


if __name__ == "__main__":
    main()
