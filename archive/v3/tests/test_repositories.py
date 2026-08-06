"""Tests for concrete repositories over the in-memory FakeDocStore.

Covers the dedup contract (reserve), status patching (mark_success/mark_error),
and the streaming query helpers (by_case/by_suite/by_modality/list_all).
"""
from __future__ import annotations

from app.domain.models import ExecStatus, Modality
from app.infra.repositories import (
    ComparisonRepository,
    ExecutionRepository,
    SuiteRepository,
    VoteRepository,
)


def _exec(doc_id: str, *, case_id: str = "case-1", suite_id: str = "suite-1") -> dict:
    return {
        "id": doc_id,
        "case_id": case_id,
        "suite_id": suite_id,
        "status": ExecStatus.PENDING.value,
    }


# --- reserve() dedup contract ---------------------------------------------
def test_reserve_returns_true_first_time_false_on_duplicate(store):
    repo = ExecutionRepository(store, "executions")
    execution = _exec("exec_abc")

    assert repo.reserve(execution) is True   # won the slot
    assert repo.reserve(execution) is False  # already exists -> reuse
    # same id, different payload still de-dups
    assert repo.reserve(_exec("exec_abc", case_id="other")) is False


def test_reserve_persists_the_document(store):
    repo = ExecutionRepository(store, "executions")
    repo.reserve(_exec("exec_abc"))
    got = repo.get("exec_abc")
    assert got is not None
    assert got["id"] == "exec_abc"


# --- mark_success / mark_error --------------------------------------------
def test_mark_success_patches_and_sets_status(store):
    repo = ExecutionRepository(store, "executions")
    repo.reserve(_exec("exec_abc"))

    repo.mark_success("exec_abc", {"media_uri": "gs://b/o.png"})

    got = repo.get("exec_abc")
    assert got["status"] == ExecStatus.SUCCESS.value
    assert got["media_uri"] == "gs://b/o.png"


def test_mark_error_records_message_and_status(store):
    repo = ExecutionRepository(store, "executions")
    repo.reserve(_exec("exec_abc"))

    repo.mark_error("exec_abc", "provider timeout")

    got = repo.get("exec_abc")
    assert got["status"] == ExecStatus.ERROR.value
    assert got["error"] == "provider timeout"


# --- by_case / by_suite ----------------------------------------------------
def test_by_case_and_by_suite_filter_via_stream(store):
    repo = ExecutionRepository(store, "executions")
    repo.reserve(_exec("e1", case_id="c1", suite_id="s1"))
    repo.reserve(_exec("e2", case_id="c1", suite_id="s2"))
    repo.reserve(_exec("e3", case_id="c2", suite_id="s1"))

    by_c1 = repo.by_case("c1")
    assert {d["id"] for d in by_c1} == {"e1", "e2"}

    by_s1 = repo.by_suite("s1")
    assert {d["id"] for d in by_s1} == {"e1", "e3"}


# --- ComparisonRepository --------------------------------------------------
def test_comparison_create_if_absent_and_by_case(store):
    repo = ComparisonRepository(store, "comparisons")
    assert repo.create_if_absent("cmp1", {"id": "cmp1", "case_id": "c1"}) is True
    assert repo.create_if_absent("cmp1", {"id": "cmp1", "case_id": "c1"}) is False
    repo.create_if_absent("cmp2", {"id": "cmp2", "case_id": "c2"})

    assert [d["id"] for d in repo.by_case("c1")] == ["cmp1"]


# --- VoteRepository --------------------------------------------------------
def test_vote_add_and_by_case(store):
    repo = VoteRepository(store, "votes")
    repo.add({"id": "v1", "case_id": "c1"})
    repo.add({"id": "v2", "case_id": "c1"})
    repo.add({"id": "v3", "case_id": "c2"})

    assert {d["id"] for d in repo.by_case("c1")} == {"v1", "v2"}
    assert repo.get("v1")["case_id"] == "c1"


# --- SuiteRepository -------------------------------------------------------
def test_suite_list_all_and_by_modality(store):
    repo = SuiteRepository(store, "suites")
    repo.set("s1", {"id": "s1", "modality": Modality.T2I.value})
    repo.set("s2", {"id": "s2", "modality": Modality.T2V.value})
    repo.set("s3", {"id": "s3", "modality": Modality.T2I.value})

    assert {d["id"] for d in repo.list_all()} == {"s1", "s2", "s3"}

    # accepts both the enum and the raw string
    assert {d["id"] for d in repo.by_modality(Modality.T2I)} == {"s1", "s3"}
    assert {d["id"] for d in repo.by_modality("t2v")} == {"s2"}
