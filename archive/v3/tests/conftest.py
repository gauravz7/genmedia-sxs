"""Shared test fixtures — in-memory fakes so the whole suite runs with no I/O.

``FakeDocStore`` implements the ``DocStore`` protocol including atomic
``create_if_absent`` (the no-rerun primitive). Agents building infra/repos/
services should build against these fakes, not live Firestore.
"""
from __future__ import annotations

import copy
from collections.abc import Iterable
from typing import Any

import pytest

from app.config import Settings
from app.domain.models import Case, Modality, ModelSpec


class FakeDocStore:
    """In-memory DocStore. Single-threaded, so create_if_absent is trivially
    atomic — good enough to exercise the dedup contract in tests."""

    def __init__(self) -> None:
        self._data: dict[str, dict[str, dict]] = {}

    def _coll(self, collection: str) -> dict[str, dict]:
        return self._data.setdefault(collection, {})

    def get(self, collection: str, doc_id: str) -> dict | None:
        v = self._coll(collection).get(doc_id)
        return copy.deepcopy(v) if v is not None else None

    def create_if_absent(self, collection: str, doc_id: str, data: dict) -> bool:
        coll = self._coll(collection)
        if doc_id in coll:
            return False
        coll[doc_id] = copy.deepcopy(data)
        return True

    def set(self, collection: str, doc_id: str, data: dict) -> None:
        self._coll(collection)[doc_id] = copy.deepcopy(data)

    def update(self, collection: str, doc_id: str, patch: dict) -> None:
        doc = self._coll(collection).setdefault(doc_id, {})
        doc.update(copy.deepcopy(patch))

    def delete(self, collection: str, doc_id: str) -> None:
        self._coll(collection).pop(doc_id, None)

    def stream(self, collection: str,
               where: list[tuple[str, str, Any]] | None = None) -> Iterable[dict]:
        for doc in self._coll(collection).values():
            if where and not _matches(doc, where):
                continue
            yield copy.deepcopy(doc)


def _matches(doc: dict, where: list[tuple[str, str, Any]]) -> bool:
    for field, op, val in where:
        actual = doc.get(field)
        if op in ("==", "eq") and actual != val:
            return False
        if op == "in" and actual not in val:
            return False
        if op == "!=" and actual == val:
            return False
    return True


@pytest.fixture
def store() -> FakeDocStore:
    return FakeDocStore()


@pytest.fixture
def settings() -> Settings:
    return Settings()


@pytest.fixture
def sample_case() -> Case:
    return Case(
        id="case-1",
        prompt="A red fox in snow",
        modality=Modality.T2I,
        mode="t2i",
        categories=["animals"],
    )


@pytest.fixture
def sample_spec() -> ModelSpec:
    return ModelSpec(
        id="imagen-4",
        name="Imagen 4",
        provider="vertex_imagen",
        model_id="imagen-4.0",
        model_version="v1",
        type="t2i",
    )
