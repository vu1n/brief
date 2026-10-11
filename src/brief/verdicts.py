"""`.brief/RATIFICATIONS`: the per-amendment verdict log, written only by the CI bot.

One line per event, appended, never edited:

    <anchor> escalated: amendment=<key>
    <anchor> ratified-by: <login> amendment=<key> comment=<id> (<url>)
    <anchor> rejected-by: <login> amendment=<key> comment=<id> (<url>): <reason>

`<key>` binds a line to one version of the amendment: a hash of the amendment file and of
the anchor's text in the live decision. Editing either is a revision, so a rejection stops
applying and a ratification stops covering it; nobody deletes lines.

Trust (see `provenance` and `threads.verify`): the gate accepts an added line only from a
commit authored and committed as github-actions[bot] that touches nothing else and only
appends; any other added or removed line is `untrusted-verdict`. Git identity is
self-asserted, so in CI `brief thread verify` also requires every ratified-by/rejected-by
line to match an unedited confirmation comment the bot posted on the PR. An `escalated`
line needs no attestation: forging one only makes the gate stricter.
"""
from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from . import gitutil

RECORDS = "RATIFICATIONS"
BOT_LOGIN = "github-actions[bot]"
BOT_EMAIL = "41898282+github-actions[bot]@users.noreply.github.com"

def bot_identity() -> dict[str, str]:
    """Env, not `-c user.*`: GIT_AUTHOR_*/GIT_COMMITTER_* in the environment would win."""
    return {f"GIT_{who}_{what}": val for who in ("AUTHOR", "COMMITTER")
            for what, val in (("NAME", BOT_LOGIN), ("EMAIL", BOT_EMAIL))}


LINE_RE = re.compile(
    r"^(?P<anchor>[a-z0-9][a-z0-9-]*) (?P<kind>escalated|ratified-by|rejected-by):"
    r"(?: (?P<who>[A-Za-z0-9][A-Za-z0-9-]*))? amendment=(?P<key>[0-9a-f]{12})"
    r"(?: comment=(?P<comment>\d+) \((?P<url>[^)\s]*)\))?(?:: (?P<reason>.*))?$"
)


@dataclass(frozen=True)
class Record:
    anchor: str
    kind: str  # escalated | ratified | rejected
    key: str
    who: str = ""
    comment: str = ""
    url: str = ""
    reason: str = ""

    def line(self) -> str:
        if self.kind == "escalated":
            return f"{self.anchor} escalated: amendment={self.key}"
        out = (f"{self.anchor} {self.kind}-by: {self.who} amendment={self.key} "
               f"comment={self.comment} ({self.url})")
        return out + (f": {self.reason}" if self.kind == "rejected" else "")


def parse_line(line: str) -> Record | None:
    m = LINE_RE.match(line.rstrip("\n"))
    if not m:
        return None
    kind = m["kind"].removesuffix("-by")
    if kind != "escalated" and not (m["who"] and m["comment"]):
        return None
    return Record(m["anchor"], kind, m["key"], m["who"] or "", m["comment"] or "",
                  m["url"] or "", m["reason"] or "")


def parse(text: str) -> list[Record]:
    return [r for ln in text.splitlines() if (r := parse_line(ln))]


def amendment_key(amendment: str, anchor_hash: str) -> str:
    """12 hex chars over the amendment text and the anchor's live text hash ("" if removed)."""
    return hashlib.sha256(f"{amendment}\0{anchor_hash}".encode()).hexdigest()[:12]


def key_in_tree(brief_dir: Path, anchor_id: str) -> str | None:
    """The key of the working tree's amendment for `anchor_id`; None when there is none."""
    from .docs import load_index

    proposal = brief_dir / "amendments" / f"{anchor_id}.md"
    if not proposal.exists():
        return None
    a = next((x for d in load_index(brief_dir) if (x := d.anchor(anchor_id))), None)
    return amendment_key(proposal.read_text(encoding="utf-8"), a.hash if a else "")


def state(records: list[Record], anchor: str, key: str) -> Record | None:
    """The record that decides this version of the amendment: the latest ratified/rejected
    line for (anchor, key), else its escalated line, else None (never escalated)."""
    mine = [r for r in records if r.anchor == anchor and r.key == key]
    decided = [r for r in mine if r.kind != "escalated"]
    return (decided or mine or [None])[-1]


def sanitize(text: str, limit: int = 300) -> str:
    """One line, no characters that would end a record early."""
    return " ".join(text.split())[:limit]


@dataclass
class Provenance:
    untrusted: list[str]  # lines added outside a bot commit
    removed: list[str]    # lines the change deletes (the log is append-only)
    added: list[str]      # every line this change adds (trusted ones need attestation in CI)


def provenance(repo: Path, rel: str, base: str | None, rng: str | None) -> Provenance:
    """Who added each line of the record file. Staged (rng None): every added line is
    untrusted, since only the bot writes it and the bot never commits locally. Range: a line
    is trusted when a bot commit in rng..HEAD added it, or it is on `base`'s tip (main's
    lines, reached through a merge)."""
    head = gitutil.content_after(repo, rel, rng).splitlines()
    before = gitutil.content_at(repo, rel, rng or "HEAD").splitlines()
    added = list((Counter(head) - Counter(before)).elements())
    removed = list((Counter(before) - Counter(head)).elements())
    if rng is None:
        return Provenance(added, removed, added)
    trusted = set(gitutil.content_at(repo, rel, base).splitlines()) if base else set()
    removed = [ln for ln in removed if ln in trusted]  # main removed it too: not this branch's doing
    for sha, author, committer, parents in gitutil.commits_touching(repo, rng, rel):
        if author != BOT_EMAIL or committer != BOT_EMAIL or len(parents) != 1:
            continue
        if gitutil.commit_files(repo, sha) != [rel]:
            continue
        if gitutil.removed_lines(repo, rel, parents[0], sha):
            continue
        trusted.update(gitutil.added_lines(repo, rel, parents[0], sha))
    return Provenance([ln for ln in added if ln not in trusted], removed, added)
