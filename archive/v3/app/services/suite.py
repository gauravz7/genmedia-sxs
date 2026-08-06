"""Suite service — manage prompt suites.

A suite is an ordered set of case ids. ``create`` computes a ``content_hash``
over the sorted case ids so an identical set of cases yields a stable fingerprint
(order- and duplicate-independent), useful for detecting suite drift.
"""
from __future__ import annotations

import hashlib

from app.domain.models import Modality, Suite


def _content_hash(case_ids: list[str]) -> str:
    canon = "|".join(sorted(set(case_ids)))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


class SuiteService:
    """CRUD-lite over prompt suites via a ``SuiteRepository``."""

    def __init__(self, suite_repo) -> None:
        self.suite_repo = suite_repo

    def create(self, suite_dict: dict) -> Suite:
        data = dict(suite_dict)
        data["content_hash"] = _content_hash(data.get("case_ids") or [])
        suite = Suite.model_validate(data)
        self.suite_repo.set(suite.id, suite.model_dump(mode="json"))
        return suite

    def get(self, suite_id: str) -> Suite | None:
        doc = self.suite_repo.get(suite_id)
        return Suite.model_validate(doc) if doc else None

    def list(self) -> list[Suite]:
        return [Suite.model_validate(d) for d in self.suite_repo.list_all()]

    def by_modality(self, m: Modality | str) -> list[Suite]:
        return [Suite.model_validate(d) for d in self.suite_repo.by_modality(m)]
