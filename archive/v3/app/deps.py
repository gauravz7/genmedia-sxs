"""FastAPI dependency providers — the composition root (Agent 5).

Every provider does its concrete infra/service import **inside** the function
(lazy import) so that merely importing this module (and therefore the whole app)
never hard-fails if a sibling agent's module is momentarily absent or if GCP
libraries/credentials are unavailable. Providers are chained with ``Depends`` so
FastAPI builds the object graph per request and tests can override any node via
``app.dependency_overrides``.

The ``_XxxDep`` module-level singletons hold the ``Depends`` markers (so no
function call sits in an argument default — keeps ``ruff`` B008 happy) and must
be declared *after* the provider they wrap and *before* the providers that use
them.

Collection names and project id are read from :func:`app.config.get_settings`.
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import Depends

from app.config import Settings, get_settings


# ---------------------------------------------------------------------------
# Settings + datastore
# ---------------------------------------------------------------------------
def get_settings_dep() -> Settings:
    """The cached settings singleton, injectable + overridable in tests."""
    return get_settings()


_SettingsDep = Depends(get_settings_dep)


def get_docstore(settings: Settings = _SettingsDep) -> Any:
    """A Firestore-backed ``DocStore`` (lazily connects on first query)."""
    from app.infra.firestore import FirestoreDocStore

    return FirestoreDocStore(settings.gcp_project_id)


_DocStoreDep = Depends(get_docstore)


# ---------------------------------------------------------------------------
# Repositories
# ---------------------------------------------------------------------------
def get_execution_repo(
    store: Any = _DocStoreDep,
    settings: Settings = _SettingsDep,
) -> Any:
    from app.infra.repositories import ExecutionRepository

    return ExecutionRepository(store, settings.executions_collection)


def get_vote_repo(
    store: Any = _DocStoreDep,
    settings: Settings = _SettingsDep,
) -> Any:
    from app.infra.repositories import VoteRepository

    collection = getattr(settings, "votes_collection", None) or "votes"
    return VoteRepository(store, collection)


def get_comparison_repo(
    store: Any = _DocStoreDep,
    settings: Settings = _SettingsDep,
) -> Any:
    from app.infra.repositories import ComparisonRepository

    return ComparisonRepository(store, settings.comparisons_collection)


def get_suite_repo(
    store: Any = _DocStoreDep,
    settings: Settings = _SettingsDep,
) -> Any:
    from app.infra.repositories import SuiteRepository

    return SuiteRepository(store, settings.suites_collection)


_ExecRepoDep = Depends(get_execution_repo)
_VoteRepoDep = Depends(get_vote_repo)
_ComparisonRepoDep = Depends(get_comparison_repo)
_SuiteRepoDep = Depends(get_suite_repo)


# ---------------------------------------------------------------------------
# GCS + judge client adapters
# ---------------------------------------------------------------------------
def get_gcs_client(settings: Settings = _SettingsDep) -> Any:
    from app.infra.gcs import GcsClient

    return GcsClient(settings.gcs_bucket_name)


class GenaiJudgeAdapter:
    """Adapts the sync ``google.genai`` client to the async ``JudgeClient``
    protocol (``generate_json``) that :class:`EvaluationService` expects."""

    def __init__(self, client: Any) -> None:
        self._client = client

    async def generate_json(
        self, model: str, contents: Any, config: dict | None = None
    ) -> dict:
        import anyio

        cfg = dict(config or {})

        def _call() -> Any:
            return self._client.models.generate_content(
                model=model, contents=contents, config=cfg
            )

        resp = await anyio.to_thread.run_sync(_call)
        text = getattr(resp, "text", None) or ""
        try:
            parsed = json.loads(text)
        except (ValueError, TypeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}


# ---------------------------------------------------------------------------
# Services
# ---------------------------------------------------------------------------
def get_generation_service(
    exec_repo: Any = _ExecRepoDep,
    settings: Settings = _SettingsDep,
) -> Any:
    from app.providers.base import get_provider
    from app.services.generation import GenerationService

    return GenerationService(exec_repo, settings, provider_lookup=get_provider)


def get_ingestion_service(
    exec_repo: Any = _ExecRepoDep,
    settings: Settings = _SettingsDep,
) -> Any:
    from app.services.ingestion import IngestionService

    return IngestionService(exec_repo, settings)


def get_evaluation_service(
    settings: Settings = _SettingsDep,
) -> Any:
    from app.infra.genai import get_genai_client
    from app.services.evaluation import EvaluationService

    client = get_genai_client(settings.eval_project, settings.eval_location)
    return EvaluationService(GenaiJudgeAdapter(client), settings)


def get_analytics_service(
    exec_repo: Any = _ExecRepoDep,
    vote_repo: Any = _VoteRepoDep,
    comparison_repo: Any = _ComparisonRepoDep,
) -> Any:
    from app.services.analytics import AnalyticsService

    # AnalyticsService(exec_repo, vote_repo, comparison_repo) — match its ctor.
    return AnalyticsService(exec_repo, vote_repo, comparison_repo)


def get_suite_service(
    suite_repo: Any = _SuiteRepoDep,
) -> Any:
    from app.services.suite import SuiteService

    return SuiteService(suite_repo)


def get_compare_service(
    exec_repo: Any = _ExecRepoDep,
) -> Any:
    from app.services.compare import ComparePairService

    return ComparePairService(exec_repo)
