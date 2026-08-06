"""Tests for SuiteService — create/content_hash/get/list/by_modality."""
from __future__ import annotations

from app.domain.models import Modality
from app.infra.repositories import SuiteRepository
from app.services.suite import SuiteService


def _svc(store) -> SuiteService:
    return SuiteService(SuiteRepository(store, "suites"))


def test_create_computes_content_hash(store):
    svc = _svc(store)
    suite = svc.create({"id": "s1", "modality": "t2i", "case_ids": ["c2", "c1"]})
    assert suite.content_hash
    # order-independent
    other = SuiteService(SuiteRepository(store, "suites2"))
    same = other.create({"id": "sx", "modality": "t2i", "case_ids": ["c1", "c2"]})
    assert same.content_hash == suite.content_hash


def test_content_hash_changes_with_cases(store):
    svc = _svc(store)
    a = svc.create({"id": "s1", "case_ids": ["c1", "c2"]})
    b = svc.create({"id": "s2", "case_ids": ["c1", "c3"]})
    assert a.content_hash != b.content_hash


def test_get_roundtrip(store):
    svc = _svc(store)
    svc.create({"id": "s1", "modality": "t2v", "case_ids": ["c1"], "owner": "me"})
    got = svc.get("s1")
    assert got is not None
    assert got.id == "s1"
    assert got.owner == "me"
    assert got.modality == Modality.T2V


def test_get_missing_returns_none(store):
    assert _svc(store).get("nope") is None


def test_list_and_by_modality(store):
    svc = _svc(store)
    svc.create({"id": "s1", "modality": "t2i", "case_ids": ["c1"]})
    svc.create({"id": "s2", "modality": "t2v", "case_ids": ["c2"]})
    svc.create({"id": "s3", "modality": "t2i", "case_ids": ["c3"]})

    assert {s.id for s in svc.list()} == {"s1", "s2", "s3"}
    assert {s.id for s in svc.by_modality(Modality.T2I)} == {"s1", "s3"}
    assert {s.id for s in svc.by_modality("t2v")} == {"s2"}
