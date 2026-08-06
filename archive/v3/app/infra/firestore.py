"""Firestore-backed ``DocStore`` implementation (Agent 1 / Phase 2 infra).

``FirestoreDocStore`` implements the ``DocStore`` protocol from
``app.domain.repositories`` on top of ``google.cloud.firestore``. The client is
lazily initialized so merely importing this module never contacts GCP — tests
and offline tooling can import it freely without credentials.

The critical primitive is ``create_if_absent``: it uses ``document.create()``,
which is atomic on the server and raises ``AlreadyExists`` when the doc already
exists. That is how the no-rerun guarantee (§9.3) is enforced race-safely.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any


class FirestoreDocStore:
    """``DocStore`` backed by Cloud Firestore with a lazily-created client."""

    def __init__(self, project_id: str) -> None:
        self.project_id = project_id
        self._client: Any = None

    # -- client lifecycle ---------------------------------------------------
    @property
    def client(self) -> Any:
        """Lazily construct the Firestore client on first use."""
        if self._client is None:
            from google.cloud import firestore

            self._client = firestore.Client(project=self.project_id)
        return self._client

    def _doc(self, collection: str, doc_id: str) -> Any:
        return self.client.collection(collection).document(doc_id)

    # -- DocStore protocol --------------------------------------------------
    def get(self, collection: str, doc_id: str) -> dict | None:
        snap = self._doc(collection, doc_id).get()
        if not snap.exists:
            return None
        return snap.to_dict()

    def create_if_absent(self, collection: str, doc_id: str, data: dict) -> bool:
        """Atomically create the doc iff absent.

        Returns True if this call created it, False if it already existed.
        ``document.create()`` raises ``AlreadyExists`` server-side, giving a
        race-safe dedup primitive.
        """
        from google.api_core.exceptions import AlreadyExists

        try:
            self._doc(collection, doc_id).create(dict(data))
            return True
        except AlreadyExists:
            return False

    def set(self, collection: str, doc_id: str, data: dict) -> None:
        self._doc(collection, doc_id).set(dict(data))

    def update(self, collection: str, doc_id: str, patch: dict) -> None:
        self._doc(collection, doc_id).update(dict(patch))

    def delete(self, collection: str, doc_id: str) -> None:
        self._doc(collection, doc_id).delete()

    def stream(self, collection: str,
               where: list[tuple[str, str, Any]] | None = None) -> Iterable[dict]:
        from google.cloud.firestore_v1.base_query import FieldFilter

        query: Any = self.client.collection(collection)
        for field, op, value in where or []:
            query = query.where(filter=FieldFilter(field, op, value))
        for snap in query.stream():
            yield snap.to_dict()
