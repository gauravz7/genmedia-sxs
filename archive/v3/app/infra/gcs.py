"""Thin Google Cloud Storage wrapper (Agent 1 / Phase 2 infra).

``GcsClient`` wraps the handful of operations the pipelines need — upload bytes,
sign a URL, download bytes — with a lazily-created client so importing this
module never contacts GCP. Patterns mirror v2's ``backend/util/gcs_utils.py``
(read-only reference) but normalized: uploads return a ``gs://`` URI (not an
https URL), and there is one canonical ``gs://`` parser.
"""
from __future__ import annotations

import datetime
from typing import Any


def _parse_gs_uri(gs_uri: str) -> tuple[str, str]:
    """Split ``gs://bucket/path/to/obj`` into ``(bucket, blob_name)``."""
    if not gs_uri.startswith("gs://"):
        raise ValueError(f"Not a gs:// URI: {gs_uri!r}")
    rest = gs_uri[len("gs://"):]
    bucket, _, blob = rest.partition("/")
    if not bucket or not blob:
        raise ValueError(f"Malformed gs:// URI: {gs_uri!r}")
    return bucket, blob


class GcsClient:
    """Minimal GCS client scoped to a default bucket, with lazy client init."""

    def __init__(self, bucket_name: str) -> None:
        self.bucket_name = bucket_name
        self._client: Any = None

    @property
    def client(self) -> Any:
        """Lazily construct the storage client on first use."""
        if self._client is None:
            from google.cloud import storage

            self._client = storage.Client()
        return self._client

    def _blob(self, bucket_name: str, blob_name: str) -> Any:
        return self.client.bucket(bucket_name).blob(blob_name)

    def upload_bytes(self, data: bytes, dest_path: str,
                     content_type: str = "application/octet-stream") -> str:
        """Upload ``data`` to ``dest_path`` in the default bucket. Returns a
        ``gs://`` URI."""
        blob = self._blob(self.bucket_name, dest_path)
        blob.upload_from_string(data, content_type=content_type)
        return f"gs://{self.bucket_name}/{dest_path}"

    def signed_url(self, gs_uri: str, ttl_seconds: int = 3600) -> str:
        """Generate a V4 signed GET URL for a ``gs://`` object."""
        bucket_name, blob_name = _parse_gs_uri(gs_uri)
        blob = self._blob(bucket_name, blob_name)
        return blob.generate_signed_url(
            version="v4",
            expiration=datetime.timedelta(seconds=ttl_seconds),
            method="GET",
        )

    def download_bytes(self, gs_uri: str) -> bytes:
        """Download the bytes of a ``gs://`` object."""
        bucket_name, blob_name = _parse_gs_uri(gs_uri)
        return self._blob(bucket_name, blob_name).download_as_bytes()
