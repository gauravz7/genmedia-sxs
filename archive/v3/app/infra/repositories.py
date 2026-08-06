"""Concrete repositories over a ``DocStore`` (Agent 1 / Phase 2 infra).

These wrap the abstract bases in ``app.domain.repositories`` with modality- and
domain-specific query helpers. They are datastore-agnostic: give them a
``FirestoreDocStore`` in prod or a ``FakeDocStore`` in tests.

``ExecutionRepository.reserve`` is the no-rerun guarantee — it delegates to the
store's atomic ``create_if_absent`` keyed on the deterministic ``execution_id``.
"""
from __future__ import annotations

from app.domain.models import ExecStatus, Modality
from app.domain.repositories import (
    ComparisonRepositoryBase,
    ExecutionRepositoryBase,
    Repository,
    VoteRepositoryBase,
)


class ExecutionRepository(ExecutionRepositoryBase):
    """Executions keyed by their content-addressed id."""

    def reserve(self, execution: dict) -> bool:
        """Atomically reserve the execution slot. True if this caller won (should
        generate), False if it already exists (reuse) — the no-rerun guarantee."""
        return self.store.create_if_absent(self.collection, execution["id"], execution)

    def mark_success(self, doc_id: str, patch: dict) -> None:
        """Patch an execution and flip its status to SUCCESS."""
        self.update(doc_id, {**patch, "status": ExecStatus.SUCCESS.value})

    def mark_error(self, doc_id: str, msg: str) -> None:
        """Record an error message and flip status to ERROR."""
        self.update(doc_id, {"status": ExecStatus.ERROR.value, "error": msg})

    def by_case(self, case_id: str) -> list[dict]:
        return list(self.stream([("case_id", "==", case_id)]))

    def by_suite(self, suite_id: str) -> list[dict]:
        return list(self.stream([("suite_id", "==", suite_id)]))


class ComparisonRepository(ComparisonRepositoryBase):
    """Derived head-to-head comparisons."""

    def by_case(self, case_id: str) -> list[dict]:
        return list(self.stream([("case_id", "==", case_id)]))


class VoteRepository(VoteRepositoryBase):
    """Human/AI votes referencing two executions."""

    def add(self, vote: dict) -> None:
        self.set(vote["id"], vote)

    def by_case(self, case_id: str) -> list[dict]:
        return list(self.stream([("case_id", "==", case_id)]))


class SuiteRepository(Repository):
    """Prompt suites."""

    def list_all(self) -> list[dict]:
        return list(self.stream())

    def by_modality(self, m: Modality | str) -> list[dict]:
        value = m.value if isinstance(m, Modality) else m
        return list(self.stream([("modality", "==", value)]))
