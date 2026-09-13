from __future__ import annotations

import os
import secrets
from pathlib import Path


SECRET_ROOT = Path("/secrets")


def ensure_secret(name: str, *, length: int = 48) -> None:
    path = SECRET_ROOT / name
    if not path.is_file() or not path.read_text(encoding="utf-8").strip():
        temporary = path.with_suffix(".tmp")
        temporary.write_text(secrets.token_urlsafe(length), encoding="utf-8")
        temporary.replace(path)
    os.chmod(path, 0o444)


SECRET_ROOT.mkdir(parents=True, exist_ok=True)
ensure_secret("postgres-password", length=36)
ensure_secret("as-token")
ensure_secret("hs-token")
