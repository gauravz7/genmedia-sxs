"""Tests for the blind SxS compare surface — pair selection is blind, media
paths never leak, and reveal only discloses identities on demand."""
from __future__ import annotations

import random

from app.infra.repositories import ExecutionRepository
from app.services.compare import ComparePairService


def _repo(store) -> ExecutionRepository:
    return ExecutionRepository(store, "executions")


def _seed(store):
    ex = _repo(store)
    ex.reserve({"id": "exA", "case_id": "c1", "model_id": "gemini-omni",
                "provider": "omni", "prompt": "A red fox", "modality": "t2v",
                "categories": ["animals"], "status": "success",
                "media_uri": "gs://b/omni_123.mp4"})
    ex.reserve({"id": "exB", "case_id": "c1", "model_id": "kling-2.0",
                "provider": "fal", "prompt": "A red fox", "modality": "t2v",
                "categories": ["animals"], "status": "success",
                "media_uri": "gs://b/kling_123.mp4"})
    return ex


def _svc(store, seed=0) -> ComparePairService:
    return ComparePairService(_repo(store), rng=random.Random(seed))


def test_pick_pair_is_blind(store):
    _seed(store)
    pair = _svc(store).pick_pair()
    assert pair is not None
    assert pair["case_id"] == "c1"
    assert pair["prompt"] == "A red fox"
    for side in ("side_a", "side_b"):
        s = pair[side]
        # opaque execution id + blind media ref only — NO model/provider/gs://
        assert set(s) == {"execution_id", "media"}
        assert s["media"].startswith("/api/compare/media?execution_id=")
        assert s["media"].endswith(s["execution_id"])
        assert "gs://" not in s["media"]
    # blob of the whole payload must not leak any identity
    blob = str(pair)
    for leak in ("omni", "kling", "fal", "gemini", "gs://"):
        assert leak not in blob


def test_pick_pair_two_distinct_models(store):
    _seed(store)
    pair = _svc(store).pick_pair()
    ids = {pair["side_a"]["execution_id"], pair["side_b"]["execution_id"]}
    assert ids == {"exA", "exB"}


def test_pick_pair_ab_order_randomizes(store):
    _seed(store)
    firsts = {_svc(store, seed=s).pick_pair()["side_a"]["execution_id"]
              for s in range(8)}
    assert firsts == {"exA", "exB"}  # both orderings appear across seeds


def test_pick_pair_requires_two_distinct_models(store):
    ex = _repo(store)
    # two executions, SAME model -> not a real matchup
    ex.reserve({"id": "e1", "case_id": "c1", "model_id": "m", "prompt": "x",
                "modality": "t2v", "status": "success", "media_uri": "gs://b/1.mp4"})
    ex.reserve({"id": "e2", "case_id": "c1", "model_id": "m", "prompt": "x",
                "modality": "t2v", "status": "success", "media_uri": "gs://b/2.mp4"})
    assert _svc(store).pick_pair() is None


def test_pick_pair_skips_failed_and_medialess(store):
    ex = _repo(store)
    ex.reserve({"id": "ok", "case_id": "c1", "model_id": "a", "prompt": "x",
                "modality": "t2v", "status": "success", "media_uri": "gs://b/ok.mp4"})
    ex.reserve({"id": "bad", "case_id": "c1", "model_id": "b", "prompt": "x",
                "modality": "t2v", "status": "error", "media_uri": "gs://b/bad.mp4"})
    ex.reserve({"id": "nomedia", "case_id": "c1", "model_id": "c", "prompt": "x",
                "modality": "t2v", "status": "success", "media_uri": None})
    # only one usable model remains -> no pair
    assert _svc(store).pick_pair() is None


def test_pick_pair_modality_and_tag_filters(store):
    _seed(store)
    assert _svc(store).pick_pair(modality="t2i") is None
    assert _svc(store).pick_pair(tag="doesnotexist") is None
    assert _svc(store).pick_pair(modality="t2v", tag="animals") is not None


def test_reveal_discloses_identities(store):
    _seed(store)
    out = _svc(store).reveal("exA", "exB")
    assert out["exA"]["model_id"] == "gemini-omni"
    assert out["exA"]["provider"] == "omni"
    assert out["exB"]["model_id"] == "kling-2.0"


def test_reveal_missing_execution(store):
    _seed(store)
    out = _svc(store).reveal("nope")
    assert out["nope"] == {"found": False}


def test_media_uri_of(store):
    _seed(store)
    svc = _svc(store)
    assert svc.media_uri_of("exA") == "gs://b/omni_123.mp4"
    assert svc.media_uri_of("nope") is None
