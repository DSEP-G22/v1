"""Local filesystem object store — same ObjectStorePort as the S3/MinIO adapter."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path


class LocalObjectStore:
    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    def put(self, org_id: str, filename: str, data: bytes) -> str:
        digest = hashlib.sha256(data).hexdigest()
        ext = Path(filename).suffix
        now = datetime.now(timezone.utc)
        key = f"{org_id}/{now:%Y}/{now:%m}/{digest}{ext}"
        path = self._root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(data)
        return key

    def get(self, key: str) -> bytes:
        return (self._root / key).read_bytes()

    def signed_url(self, key: str) -> str:
        return (self._root / key).resolve().as_uri()

    def path_for(self, key: str) -> Path:
        return self._root / key
