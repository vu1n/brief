"""Feature map — which code implements which feature, and what bites there.

A feature map is a doc with `type: features` in its frontmatter (by convention
`.brief/docs/features.md`). Every anchor in it is one feature, addressable as
`doc://<project>/features@latest#<feature-id>`. Each feature section carries a fenced
```yaml block with `paths:` — the globs whose change means the feature is touched — plus
prose and a `Gotchas` section.

A feature map is descriptive, not a decision: its `paths` are not `related_code`, so it
never arms needs-conformance. Its one mechanical rule is that every glob matches at least
one tracked file — a glob that matches nothing silently drops the code it meant from the
map. `brief check` enforces that (gate.empty-glob).
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

from .docs import Decision, load_index
from .gate import glob_match

FEATURES_TYPE = "features"
_YAML_FENCE_RE = re.compile(r"^```ya?ml\s*\n(.*?)^```", re.MULTILINE | re.DOTALL)


@dataclass
class Feature:
    feature_id: str
    title: str
    doc_id: str
    project: str
    path: str  # the map file
    paths: list[str] = field(default_factory=list)

    @property
    def ref(self) -> str:
        return f"doc://{self.project}/{self.doc_id}@latest#{self.feature_id}"

    def touches(self, file: str) -> bool:
        return any(glob_match(g, file) for g in self.paths)

    def to_dict(self) -> dict:
        return {**asdict(self), "ref": self.ref}


def is_feature_map(d: Decision) -> bool:
    return str(d.meta.get("type") or "").lower() == FEATURES_TYPE


def _paths_of(body: str) -> list[str]:
    """`paths:` from the first fenced yaml block in a feature section that declares it."""
    for m in _YAML_FENCE_RE.finditer(body):
        try:
            data = yaml.safe_load(m.group(1))
        except yaml.YAMLError:
            continue
        if isinstance(data, dict) and "paths" in data:
            paths = data["paths"] or []
            return [paths] if isinstance(paths, str) else [str(p) for p in paths]
    return []


def features_of(d: Decision) -> list[Feature]:
    return [
        Feature(
            feature_id=a.anchor_id,
            title=a.title,
            doc_id=d.doc_id,
            project=d.project,
            path=str(d.path),
            paths=_paths_of(a.body),
        )
        for a in d.anchors
    ]


def load_features(brief_dir: Path, index: list[Decision] | None = None) -> list[Feature]:
    index = load_index(brief_dir) if index is None else index
    return [f for d in index if is_feature_map(d) for f in features_of(d)]


def touched(features: list[Feature], files: list[str]) -> list[Feature]:
    """Features whose paths match any of `files` — recall from a diff."""
    return [f for f in features if any(f.touches(p) for p in files)]


def empty_globs(features: list[Feature], files: list[str]) -> list[tuple[Feature, str]]:
    """(feature, glob) pairs where the glob matches none of `files`."""
    return [(f, g) for f in features for g in f.paths if not any(glob_match(g, p) for p in files)]
