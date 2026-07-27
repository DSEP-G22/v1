from __future__ import annotations

from typing import Protocol


class ObjectStorePort(Protocol):
    def put(self, org_id: str, filename: str, data: bytes) -> str: ...

    def get(self, key: str) -> bytes: ...

    def signed_url(self, key: str) -> str: ...
