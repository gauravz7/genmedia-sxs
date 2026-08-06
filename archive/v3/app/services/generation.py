"""Generation service — the no-rerun guarantee in action (REFACTOR_PLAN §9.3).

``GenerationService.generate`` reserves a content-addressed execution slot via
the repository's atomic ``reserve`` (backed by ``create_if_absent``). If the
slot already exists it returns the cached execution WITHOUT calling the
provider — a model never regenerates a ``(case, model, params)`` it already ran.
Only the caller that wins the slot dispatches to the provider.
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Sequence
from itertools import product

from app.config import Settings
from app.domain.models import (
    Case,
    ExecStatus,
    Execution,
    GenerationResult,
    ModelSpec,
    execution_id,
    resolve_params,
)

try:  # imported lazily so tests never require the provider registry to exist
    from app.providers.base import get_provider
except Exception:  # pragma: no cover - provider package may be built in parallel
    get_provider = None  # type: ignore[assignment]


class GenerationService:
    """Generate (or reuse) executions with a hard no-rerun guarantee."""

    def __init__(
        self,
        exec_repo,
        settings: Settings,
        provider_lookup: Callable[[str], object] | None = get_provider,
    ) -> None:
        self.exec_repo = exec_repo
        self.settings = settings
        self.provider_lookup = provider_lookup

    # -- helpers -----------------------------------------------------------
    def _pending(self, eid: str, case: Case, spec: ModelSpec,
                 params: dict | None) -> Execution:
        resolved = resolve_params(params if params is not None else case.params)
        return Execution(
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
            status=ExecStatus.PENDING,
            source="generated",
            created_at=time.time(),
        )

    def _fetch(self, eid: str) -> Execution:
        doc = self.exec_repo.get(eid)
        if doc is None:  # pragma: no cover - defensive; reserve just persisted it
            raise RuntimeError(f"execution {eid} vanished after reserve")
        return Execution.model_validate(doc)

    @staticmethod
    def _success_patch(result: GenerationResult) -> dict:
        metadata = {
            "latency_s": result.latency_s,
            "cost": result.cost,
            "width": result.width,
            "height": result.height,
            "duration": result.duration,
            "fps": result.fps,
            "model_id": result.model_id,
            "raw": result.raw,
        }
        metadata = {k: v for k, v in metadata.items() if v is not None}
        return {
            "media_uri": result.media_uri,
            "metadata": metadata,
            "latency_s": result.latency_s,
        }

    # -- core --------------------------------------------------------------
    async def generate(self, case: Case, spec: ModelSpec,
                       params: dict | None = None) -> Execution:
        eid = execution_id(case, spec, params)
        pending = self._pending(eid, case, spec, params)

        won = self.exec_repo.reserve(pending.model_dump(mode="json"))
        if not won:
            # Already exists — the no-rerun guarantee: reuse, never regenerate.
            return self._fetch(eid)

        self.exec_repo.update(eid, {"status": ExecStatus.GENERATING.value})

        if self.provider_lookup is None:
            self.exec_repo.mark_error(eid, "no provider_lookup configured")
            return self._fetch(eid)

        try:
            provider = self.provider_lookup(spec.provider)
            result = await provider.generate(case, spec, params)
        except Exception as exc:  # noqa: BLE001 - surface any provider failure
            self.exec_repo.mark_error(eid, str(exc))
            return self._fetch(eid)

        if result.status == ExecStatus.ERROR or result.media_uri is None:
            self.exec_repo.mark_error(eid, result.error or "generation failed")
            return self._fetch(eid)

        self.exec_repo.mark_success(eid, self._success_patch(result))
        return self._fetch(eid)

    async def generate_batch(
        self,
        cases: Sequence[Case],
        specs: Sequence[ModelSpec],
        params: dict | None = None,
    ) -> list[Execution]:
        """Generate the full (case x spec) matrix with bounded concurrency."""
        sem = asyncio.Semaphore(max(1, self.settings.gen_api_concurrency))

        async def _one(case: Case, spec: ModelSpec) -> Execution:
            async with sem:
                return await self.generate(case, spec, params)

        tasks = [_one(case, spec) for case, spec in product(cases, specs)]
        return list(await asyncio.gather(*tasks))
