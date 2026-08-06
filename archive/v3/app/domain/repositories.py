"""Repository interfaces (Phase 2 contract).

Concrete Firestore-backed implementations live in ``app/infra`` (Agent 1). The
key method is ``create_if_absent`` — atomic create keyed by a deterministic id,
which is how the no-rerun guarantee (§9.3) is enforced race-safely.

A ``DocStore`` protocol abstracts the datastore so repositories can run against
Firestore in prod and an in-memory fake in tests (see tests/conftest.py).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from typing import Any, Protocol


class DocStore(Protocol):
    """Minimal datastore surface a repository needs (Firestore-shaped)."""

    def get(self, collection: str, doc_id: str) -> dict | None: ...

    def create_if_absent(self, collection: str, doc_id: str, data: dict) -> bool:
        """Create the doc iff it does not exist. Returns True if created,
        False if it already existed (atomic — the dedup primitive)."""
        ...

    def set(self, collection: str, doc_id: str, data: dict) -> None: ...

    def update(self, collection: str, doc_id: str, patch: dict) -> None: ...

    def delete(self, collection: str, doc_id: str) -> None: ...

    def stream(self, collection: str,
               where: list[tuple[str, str, Any]] | None = None) -> Iterable[dict]: ...


class Repository:
    """Base repository over a DocStore + a named collection."""

    def __init__(self, store: DocStore, collection: str):
        self.store = store
        self.collection = collection

    def get(self, doc_id: str) -> dict | None:
        return self.store.get(self.collection, doc_id)

    def create_if_absent(self, doc_id: str, data: dict) -> bool:
        return self.store.create_if_absent(self.collection, doc_id, data)

    def set(self, doc_id: str, data: dict) -> None:
        self.store.set(self.collection, doc_id, data)

    def update(self, doc_id: str, patch: dict) -> None:
        self.store.update(self.collection, doc_id, patch)

    def stream(self, where: list[tuple[str, str, Any]] | None = None):
        return self.store.stream(self.collection, where)


class ExecutionRepositoryBase(Repository, ABC):
    @abstractmethod
    def reserve(self, execution: dict) -> bool:
        """Atomically reserve an execution id for generation. True if this
        caller won the slot (should generate); False if it already exists
        (reuse). Enforces the no-rerun guarantee."""
        ...


class ComparisonRepositoryBase(Repository):
    pass


class VoteRepositoryBase(Repository):
    pass
