from __future__ import annotations

import tomllib
from dataclasses import dataclass, fields
from pathlib import Path


@dataclass(frozen=True)
class Config:
    db_path: str = "ledger.db"
    rates_url: str = "https://rates.example/api/latest"


{{WHY:config}}
def load(path: Path | str = "ledger.toml") -> Config:
    p = Path(path)
    data = tomllib.loads(p.read_text()) if p.exists() else {}
    known = {f.name for f in fields(Config)}
    return Config(**{k: v for k, v in data.items() if k in known})
