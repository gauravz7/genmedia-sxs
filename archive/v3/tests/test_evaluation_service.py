"""Tests for EvaluationService with a FAKE genai client (no network)."""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.config import Settings
from app.domain.models import Case, EvalMode, Execution, Modality, Verdict
from app.services.evaluation import EvaluationService


class FakeGenaiClient:
    """Implements the ``JudgeClient`` protocol; returns canned JSON per call.

    ``responses`` is consumed in order. Every call records its ``(model,
    contents, config)`` for assertions.
    """

    def __init__(self, responses: list[dict]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    async def generate_json(
        self, model: str, contents: Any, config: dict | None = None
    ) -> dict:
        self.calls.append({"model": model, "contents": contents, "config": config})
        return self._responses.pop(0)


def _core5_json(overall_scores: tuple[int, int, int, int, int]) -> dict:
    keys = [
        "prompt_adherence", "visual_quality", "motion_physics",
        "temporal_consistency", "audio_visual_sync",
    ]
    return {k: {"score": s, "explanation": "x"} for k, s in zip(keys, overall_scores, strict=True)}


def _video_case() -> Case:
    return Case(id="c1", prompt="A red fox leaps", modality=Modality.T2V)


def _video_exec(id_: str) -> Execution:
    return Execution(id=id_, case_id="c1", model_id="veo",
                     modality=Modality.T2V, prompt="A red fox leaps")


def _image_case() -> Case:
    return Case(id="ci", prompt="A red fox", modality=Modality.T2I, mode="t2i")


def _image_exec(id_: str) -> Execution:
    return Execution(id=id_, case_id="ci", model_id="imagen",
                     modality=Modality.T2I, mode="t2i", prompt="A red fox")


# --------------------------------------------------------------------------
def test_evaluate_absolute_video_returns_verdict():
    client = FakeGenaiClient([_core5_json((5, 4, 3, 2, 1))])
    svc = EvaluationService(client, Settings())
    verdict = asyncio.run(svc.evaluate_absolute(_video_exec("exec_a")))

    assert isinstance(verdict, Verdict)
    assert verdict.mode == EvalMode.ABSOLUTE
    assert verdict.model == Settings().eval_model
    assert "exec_a" in verdict.per_execution
    assert verdict.per_execution["exec_a"]["overall_score"] == 3.0
    # video judge model was selected
    assert client.calls[0]["model"] == Settings().eval_model


def test_evaluate_absolute_image_uses_image_model():
    client = FakeGenaiClient([{"prompt_following": 4, "aesthetic": 4,
                               "detail": 4, "artifact_free": 4}])
    svc = EvaluationService(client, Settings())
    verdict = asyncio.run(svc.evaluate_absolute(_image_exec("exec_img")))
    assert verdict.model == Settings().image_eval_model
    assert client.calls[0]["model"] == Settings().image_eval_model
    assert verdict.per_execution["exec_img"]["overall_score"] == 4.0


def test_evaluate_pairwise_winner_selection():
    client = FakeGenaiClient([{"verdict": "B", "reasoning": "B better"}])
    svc = EvaluationService(client, Settings())
    verdict = asyncio.run(
        svc.evaluate_pairwise(_video_case(), _video_exec("A_id"), _video_exec("B_id"))
    )
    assert verdict.mode == EvalMode.PAIRWISE
    assert verdict.winner_execution == "B_id"

    # tie -> None
    client2 = FakeGenaiClient([{"verdict": "tie"}])
    svc2 = EvaluationService(client2, Settings())
    tie = asyncio.run(
        svc2.evaluate_pairwise(_video_case(), _video_exec("A_id"), _video_exec("B_id"))
    )
    assert tie.winner_execution is None


def test_evaluate_pairwise_image_carries_per_side_scores():
    resp = {
        "A": {"prompt_following": 5, "aesthetic": 5, "detail": 5, "artifact_free": 5},
        "B": {"prompt_following": 2, "aesthetic": 2, "detail": 2, "artifact_free": 2},
        "winner": "A", "justification": "A wins",
    }
    client = FakeGenaiClient([resp])
    svc = EvaluationService(client, Settings())
    verdict = asyncio.run(
        svc.evaluate_pairwise(_image_case(), _image_exec("ia"), _image_exec("ib"))
    )
    assert verdict.winner_execution == "ia"
    assert verdict.per_execution["ia"]["overall_score"] == 5.0
    assert verdict.per_execution["ib"]["overall_score"] == 2.0


def test_evaluate_both_yields_three_verdicts():
    client = FakeGenaiClient([
        _core5_json((5, 5, 5, 5, 5)),   # absolute A
        _core5_json((1, 1, 1, 1, 1)),   # absolute B
        {"verdict": "A", "reasoning": "A superior"},  # pairwise
    ])
    svc = EvaluationService(client, Settings())
    verdicts = asyncio.run(
        svc.evaluate(
            EvalMode.BOTH,
            case=_video_case(),
            exec_a=_video_exec("A_id"),
            exec_b=_video_exec("B_id"),
        )
    )
    assert len(verdicts) == 3
    assert verdicts[0].mode == EvalMode.ABSOLUTE
    assert verdicts[0].per_execution["A_id"]["overall_score"] == 5.0
    assert verdicts[1].mode == EvalMode.ABSOLUTE
    assert verdicts[1].per_execution["B_id"]["overall_score"] == 1.0
    assert verdicts[2].mode == EvalMode.PAIRWISE
    assert verdicts[2].winner_execution == "A_id"


def test_evaluate_absolute_requires_execution():
    svc = EvaluationService(FakeGenaiClient([]), Settings())
    with pytest.raises(ValueError):
        asyncio.run(svc.evaluate(EvalMode.ABSOLUTE))
