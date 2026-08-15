"""S3/MinIO object store adapter, same ObjectStorePort as the local filesystem adapter.
Not used by any default profile in v1 (SAD deviation table: MinIO -> local filesystem); kept so
a deployment can switch by config without touching service code. Requires `boto3`, imported
lazily so the base install never needs the wheel."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone


class S3ObjectStore:
    def __init__(self, bucket: str, endpoint_url: str | None = None) -> None:
        try:
            import boto3  # noqa: F401
        except ImportError as exc:  # pragma: no cover - exercised only when boto3 is installed
            raise RuntimeError("boto3 is not installed; install it or use LocalObjectStore") from exc

        import boto3

        self._bucket = bucket
        self._client = boto3.client("s3", endpoint_url=endpoint_url)

    def put(self, org_id: str, filename: str, data: bytes) -> str:
        digest = hashlib.sha256(data).hexdigest()
        ext = filename.rsplit(".", 1)[-1] if "." in filename else ""
        now = datetime.now(timezone.utc)
        key = f"{org_id}/{now:%Y}/{now:%m}/{digest}" + (f".{ext}" if ext else "")
        self._client.put_object(Bucket=self._bucket, Key=key, Body=data)
        return key

    def get(self, key: str) -> bytes:
        resp = self._client.get_object(Bucket=self._bucket, Key=key)
        return resp["Body"].read()

    def signed_url(self, key: str) -> str:
        return self._client.generate_presigned_url(
            "get_object", Params={"Bucket": self._bucket, "Key": key}, ExpiresIn=3600
        )
