"""Response cache (ADR-007): `data/.llm-cache/<sha256>.json`.

Keyed on `(prompt_id, version, rendered vars, model, schema)` per TDD 10.1
step 3 — any change to what was actually sent invalidates the entry. Cache
hits never touch the ledger (TDD 10.1 step 3: "no ledger entry") and are
free by construction, which is what makes tests deterministic without
hitting a real API.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ce.exit_codes import ConfigError


def compute_key(
    prompt_id: str, version: int, rendered: str, model: str, schema: dict[str, Any] | None
) -> str:
    schema_part = json.dumps(schema, sort_keys=True) if schema else ""
    digest = hashlib.sha256()
    for part in (prompt_id, str(version), rendered, model, schema_part):
        digest.update(part.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def path_for(cache_dir: Path, key: str) -> Path:
    return cache_dir / f"{key}.json"


def read(cache_dir: Path, key: str) -> dict[str, Any] | None:
    path = path_for(cache_dir, key)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"{path}: {exc}") from exc


def write(cache_dir: Path, key: str, payload: dict[str, Any]) -> None:
    path = path_for(cache_dir, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
