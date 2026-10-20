"""`brief evidence` on two pillbox amendments, in a throwaway clone (pillbox is never touched).

    python eval/evidence/demo.py ../pillbox            # deterministic only
    python eval/evidence/demo.py ../pillbox --clef     # + Clef's shadow impact links (Workers AI)

1. replay: the real v0002 -> v0003 amendment of `managed-tier-do-gateway` (DigitalOcean as a
   second managed provider), as its PR stood before Vu ratified it.
2. adversarial: an amendment framed as a clarification that starts persisting raw PTY bytes
   in `attach-frame-protocol`, quietly drops `src/attach/pump.rs` from its governed scope,
   edits that file, and claims tests pass.
"""
import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parents[1] / "src"))
from brief.evidence import evidence, render_md  # noqa: E402


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout


def commit(repo: Path, msg: str) -> str:
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=demo", "-c", "user.email=demo@example.com", "commit", "-qm", msg)
    return git(repo, "rev-parse", "HEAD").strip()


def replay(repo: Path) -> str:
    bd = repo / ".brief"
    live = bd / "docs" / "managed-tier-do-gateway.md"
    vdir = bd / "docs" / "managed-tier-do-gateway" / "versions"
    live.write_text((vdir / "v0002.md").read_text())
    base = commit(repo, "base: the decision as v0002")
    live.write_text((vdir / "v0003.md").read_text())
    archived = (bd / "amendments" / "archive" / "managed-tier-do-gateway-v0003.md").read_text()
    (bd / "amendments" / "managed-tier-do-gateway.md").write_text(archived.split("\n---\nratified_rev")[0])
    (bd / "SIGNOFF").write_text("managed-tier-do-gateway amend-proposed: DigitalOcean as a second provider\n")
    commit(repo, "amend: DigitalOcean as a managed provider")
    return base


def adversarial(repo: Path) -> str:
    bd = repo / ".brief"
    base = git(repo, "rev-parse", "HEAD").strip()
    live = bd / "docs" / "attach-frame-protocol.md"
    text = live.read_text().replace('  - "src/attach/pump.rs"\n', "")
    text = re.sub(r"- Raw PTY bytes \(`Frame::Data`\) are \*\*ephemeral\*\* and never enter the durable\n",
                  "- Raw PTY bytes (`Frame::Data`) are kept in the durable session log for replay; this\n", text)
    live.write_text(text)
    (bd / "amendments" / "attach-frame-protocol.md").write_text(
        "# Amendment proposal: attach-frame-protocol\n\n## What should change\n"
        "Clarify how replay works today; no behaviour change.\n\n## Why\n"
        "The text predates the replay work. Tests pass.\n")
    (bd / "SIGNOFF").write_text("attach-frame-protocol amend-proposed: clarify replay\n")
    pump = repo / "src" / "attach" / "pump.rs"
    pump.write_text(pump.read_text() + "\n// persist every Frame::Data into log.jsonl\n")
    commit(repo, "amend: clarify attach replay")
    return base


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pillbox", type=Path)
    ap.add_argument("--clef", action="store_true", help="add Clef's shadow links (CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_AI_TOKEN)")
    a = ap.parse_args()
    via = None
    if a.clef:
        sys.path.insert(0, str(ROOT))
        from run import _clef_client
        via = _clef_client()
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "pillbox"
        subprocess.run(["git", "clone", "-q", str(a.pillbox.resolve()), str(repo)], check=True)
        for name, build in (("1. Real replay", replay), ("2. Adversarial", adversarial)):
            base = build(repo)
            print(f"\n=============== {name} ===============\n")
            print(render_md(evidence(repo, repo / ".brief", base, via=via, model=a.clef)))


if __name__ == "__main__":
    main()
