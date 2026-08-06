"""API smoke tests — exercise the router surface with dependency overrides.

These tests inject fakes (FakeDocStore-backed real repos + a stub generation
service) via ``app.dependency_overrides`` so they pass regardless of whether the
sibling agents' concrete infra/providers/genai are finished. They lock:

* ``GET /health``
* the no-rerun guarantee visible *through the API* (POST twice -> same id)
* a votes round-trip (POST then GET by case)
"""
from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.deps import get_execution_repo, get_generation_service, get_vote_repo
from app.domain.models import Case, Execution, Modality, ModelSpec, execution_id
from app.infra.repositories import ExecutionRepository, VoteRepository
from app.main import create_app
from tests.conftest import FakeDocStore


class StubGenerationService:
    """Deterministic, no-I/O generation service that honors the no-rerun
    guarantee via the injected ExecutionRepository's atomic reserve()."""

    def __init__(self, repo: ExecutionRepository) -> None:
        self.repo = repo

    async def generate(
        self, case: Case, spec: ModelSpec, params: dict[str, Any] | None = None
    ) -> Execution:
        eid = execution_id(case, spec, params)
        existing = self.repo.get(eid)
        if existing is not None:
            return Execution(**existing)
        execution = Execution(
            id=eid,
            case_id=case.id,
            prompt=case.prompt,
            modality=case.modality,
            model_id=spec.model_id,
            model_version=spec.model_version,
            provider=spec.provider,
            params=params if params is not None else case.params,
        )
        self.repo.reserve(execution.model_dump(mode="json"))
        return execution


@pytest.fixture
def client() -> TestClient:
    app = create_app()
    store = FakeDocStore()
    exec_repo = ExecutionRepository(store, "executions")
    vote_repo = VoteRepository(store, "votes")
    gen = StubGenerationService(exec_repo)

    app.dependency_overrides[get_execution_repo] = lambda: exec_repo
    app.dependency_overrides[get_generation_service] = lambda: gen
    app.dependency_overrides[get_vote_repo] = lambda: vote_repo
    return TestClient(app)


def test_health(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def _gen_payload() -> dict:
    return {
        "case": {
            "id": "case-1",
            "prompt": "A red fox in snow",
            "modality": Modality.T2I.value,
            "mode": "t2i",
        },
        "spec": {
            "id": "imagen-4",
            "provider": "vertex_imagen",
            "model_id": "imagen-4.0",
            "model_version": "v1",
            "type": "t2i",
        },
        "params": {"aspect_ratio": "1:1"},
    }


def test_request_execution_returns_id(client: TestClient) -> None:
    resp = client.post("/api/executions", json=_gen_payload())
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"].startswith("exec_")
    assert body["case_id"] == "case-1"


def test_no_rerun_visible_through_api(client: TestClient) -> None:
    first = client.post("/api/executions", json=_gen_payload())
    second = client.post("/api/executions", json=_gen_payload())
    assert first.status_code == second.status_code == 200
    assert first.json()["id"] == second.json()["id"]

    # And it is retrievable by id.
    eid = first.json()["id"]
    got = client.get(f"/api/executions/{eid}")
    assert got.status_code == 200
    assert got.json()["id"] == eid


def test_get_missing_execution_404(client: TestClient) -> None:
    assert client.get("/api/executions/exec_does_not_exist").status_code == 404


def _vote_payload(**kw) -> dict:
    base = {
        "case_id": "case-1",
        "execution_a": "exec_a",
        "execution_b": "exec_b",
        "winner_execution": "exec_a",
        "scores": {"exec_a": 5, "exec_b": 3},
        "justification": "A is sharper",
        "ldap": "voter1",
    }
    base.update(kw)
    return base


def test_votes_round_trip(client: TestClient) -> None:
    posted = client.post("/api/votes", json=_vote_payload())
    assert posted.status_code == 200
    vote_id = posted.json()["id"]
    assert vote_id.startswith("vote_")

    listed = client.get("/api/votes", params={"case_id": "case-1"})
    assert listed.status_code == 200
    votes = listed.json()
    assert len(votes) == 1
    assert votes[0]["id"] == vote_id
    assert votes[0]["winner_execution"] == "exec_a"


def test_human_vote_requires_ldap(client: TestClient) -> None:
    for bad in ("anonymous", "", "  ", "GLOBAL"):
        resp = client.post("/api/votes", json=_vote_payload(ldap=bad))
        assert resp.status_code == 400, bad


def test_vote_dedup_same_voter_same_pair_overwrites(client: TestClient) -> None:
    first = client.post("/api/votes", json=_vote_payload(winner_execution="exec_a"))
    assert first.json()["deduped"] is False
    # same voter re-votes the same matchup (opposite winner) -> overwrite, not stuff
    second = client.post("/api/votes",
                         json=_vote_payload(winner_execution="exec_b"))
    assert second.status_code == 200
    assert second.json()["deduped"] is True
    assert second.json()["id"] == first.json()["id"]

    votes = client.get("/api/votes", params={"case_id": "case-1"}).json()
    assert len(votes) == 1                       # not stuffed
    assert votes[0]["winner_execution"] == "exec_b"  # mind-change applied


def test_vote_dedup_is_pair_order_insensitive(client: TestClient) -> None:
    client.post("/api/votes", json=_vote_payload())
    swapped = client.post("/api/votes",
                          json=_vote_payload(execution_a="exec_b",
                                             execution_b="exec_a"))
    assert swapped.json()["deduped"] is True
    assert len(client.get("/api/votes", params={"case_id": "case-1"}).json()) == 1


def test_different_voters_not_deduped(client: TestClient) -> None:
    client.post("/api/votes", json=_vote_payload(ldap="voter1"))
    client.post("/api/votes", json=_vote_payload(ldap="voter2"))
    assert len(client.get("/api/votes", params={"case_id": "case-1"}).json()) == 2
