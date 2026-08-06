"""Ingestion service — BYOO (bring-your-own-outputs).

Some teams pre-generate media out of band and just want the arena/judge over
it. ``IngestionService.ingest`` registers such media as an ``Execution`` with
``source="ingested"`` and status ``SUCCESS``, sharing the SAME content-addressed
identity as a generated cell — so dedup applies: re-ingesting the same
``(case, model, params)`` returns the existing execution instead of duplicating.
"""
from __future__ import annotations

import time
from typing import Any

from app.config import Settings
from app.domain.models import (
    Case,
    ExecStatus,
    Execution,
    ModelSpec,
    execution_id,
    resolve_params,
)


class BatchItem:
    """One BYOO row: (case, spec, media_uri, params?, metadata?).

    Kept as a lightweight container so the router's pydantic model and the
    service share the exact same field vocabulary as :meth:`IngestionService.ingest`.
    """

    __slots__ = ("case", "spec", "media_uri", "params", "metadata")

    def __init__(
        self,
        case: Case,
        spec: ModelSpec,
        media_uri: str,
        params: dict | None = None,
        metadata: dict | None = None,
    ) -> None:
        self.case = case
        self.spec = spec
        self.media_uri = media_uri
        self.params = params
        self.metadata = metadata


class IngestionService:
    """Register externally-produced media as executions (dedup-aware)."""

    def __init__(self, exec_repo, settings: Settings) -> None:
        self.exec_repo = exec_repo
        self.settings = settings

    def ingest(
        self,
        case: Case,
        spec: ModelSpec,
        media_uri: str,
        params: dict | None = None,
        metadata: dict | None = None,
    ) -> Execution:
        eid = execution_id(case, spec, params)
        resolved = resolve_params(params if params is not None else case.params)
        execution = Execution(
            id=eid,
            suite_id=case.suite_id,
            suite_version=case.suite_version,
            case_id=case.id,
            prompt=case.prompt,
            modality=case.modality,
            mode=case.mode,
            categories=list(case.categories),
            language=case.language,
            model_id=spec.model_id,
            model_version=spec.model_version,
            provider=spec.provider,
            params=resolved,
            input_assets=list(case.input_assets),
            media_uri=media_uri,
            metadata=dict(metadata or {}),
            status=ExecStatus.SUCCESS,
            source="ingested",
            created_at=time.time(),
        )

        won = self.exec_repo.reserve(execution.model_dump(mode="json"))
        if not won:
            # Same cell already exists — dedup applies to ingested content too.
            existing = self.exec_repo.get(eid)
            return Execution.model_validate(existing)
        return execution

    def ingest_batch(self, items: list[BatchItem]) -> dict[str, Any]:
        """Bulk BYOO — ingest an array of cells. Each row is deduped exactly like
        :meth:`ingest`, and a row that fails validation/registration is reported
        in ``errors`` without aborting the rest of the batch (mirrors the
        per-row tolerance of the ``/api/{modality}/jobs`` batch generators)."""
        ingested: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        for i, item in enumerate(items):
            try:
                execution = self.ingest(
                    item.case,
                    item.spec,
                    item.media_uri,
                    params=item.params,
                    metadata=item.metadata,
                )
                ingested.append(execution.model_dump(mode="json"))
            except Exception as exc:  # noqa: BLE001 — one bad row must not sink the batch
                errors.append({"index": i, "case_id": item.case.id, "error": str(exc)})
        return {
            "count": len(ingested),
            "errors": errors,
            "executions": [e["id"] for e in ingested],
            "ingested": ingested,
        }

    def ingest_pair(
        self,
        case: Case,
        spec_a: ModelSpec,
        media_uri_a: str,
        spec_b: ModelSpec,
        media_uri_b: str,
        params: dict | None = None,
        metadata_a: dict | None = None,
        metadata_b: dict | None = None,
    ) -> tuple[Execution, Execution]:
        """Convenience for pairwise BYOO — ingest both sides of a comparison."""
        a = self.ingest(case, spec_a, media_uri_a, params=params, metadata=metadata_a)
        b = self.ingest(case, spec_b, media_uri_b, params=params, metadata=metadata_b)
        return a, b
