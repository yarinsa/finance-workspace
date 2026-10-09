"""Data-directory resolution for the finance pipeline scripts.

The plugin ships CODE (these scripts) but the user's financial DATA lives in a
separate, private directory. Resolve it once here so every script agrees:

  1. $FINANCE_DATA_DIR                          (explicit override)
  2. finance.config.json  → "data_dir"         (project config, if present)
  3. ./data relative to the current working dir (original-repo default)

The returned directory is the root that holds per-source subdirs
(<source>/raw, <source>/normalized, <source>/normalize.py) and the digested/
outputs — i.e. exactly what used to be `.../Finance/data`.
"""
import json
import os
from pathlib import Path


def data_dir() -> Path:
    env = os.environ.get("FINANCE_DATA_DIR")
    if env:
        return Path(env).expanduser().resolve()

    for cfg_name in ("finance.config.json",):
        cfg = Path.cwd() / cfg_name
        if cfg.exists():
            try:
                d = json.loads(cfg.read_text(encoding="utf-8")).get("data_dir")
                if d:
                    return Path(d).expanduser().resolve()
            except (json.JSONDecodeError, OSError):
                pass

    return (Path.cwd() / "data").resolve()


def digested_dir() -> Path:
    d = data_dir() / "digested"
    return d
