"""EvaluationService — orchestrates the LLM-as-judge across all modalities.

The service is the ONLY place that talks to the (injected) judge client; the
per-modality evaluators (``core5``, ``director``, ``image``, ``tts``) are pure
prompt-builders and response-parsers. This keeps every rubric unit-testable with
no network and lets Agent 5 wire a real ``google.genai`` client behind a thin
adapter.

Injected client contract — the ``JudgeClient`` protocol
-------------------------------------------------------
The service depends on exactly one async method::

    async def generate_json(
        self,
        model: str,
        contents: Any,
        config: dict | None = None,
    ) -> dict

  * ``model``    — the judge model id (chosen per modality from settings).
  * ``contents`` — the judge instruction. This service passes the pure prompt
    **string** produced by an evaluator's ``build_*`` function. An adapter is
    free to attach the execution's media (video/image/audio) alongside this text
    before calling Gemini; the pure builders do not do I/O.
  * ``config``   — generation config dict (temperature / thinking_level /
    response_mime_type). Kept as a plain dict so the protocol stays SDK-agnostic.
  * returns      — the judge's parsed JSON as a ``dict`` (the adapter is
    responsible for ``response_mime_type=application/json`` + ``json.loads``).

Agent 5 adapts ``app/infra/genai.py`` to this protocol.
"""
from __future__ import annotations

from types import ModuleType
from typing import Any, Protocol

from app.config import Settings
from app.domain.models import Case, EvalMode, Execution, Modality, Verdict
from app.evaluators import core5, director
from app.evaluators import image as image_eval
from app.evaluators import tts as tts_eval

VIDEO_MODALITIES = {Modality.T2V, Modality.I2V, Modality.R2V}
IMAGE_MODALITIES = {Modality.T2I, Modality.I2I}
TTS_MODALITIES = {Modality.TTS}


class JudgeClient(Protocol):
    """Structural type of the injected judge client (see module docstring)."""

    async def generate_json(
        self, model: str, contents: Any, config: dict | None = None
    ) -> dict: ...


# Judge generation config — mirrors the v2 evaluators (temperature 0.1, HIGH
# thinking, JSON output).
_JUDGE_CONFIG: dict[str, Any] = {
    "temperature": 0.1,
    # thinking_level is nested under thinking_config in google-genai >= 1.x.
    "thinking_config": {"thinking_level": "HIGH"},
    "response_mime_type": "application/json",
}


class EvaluationService:
    """Dispatches absolute/pairwise evaluation to the right modality evaluator."""

    def __init__(self, genai_client: JudgeClient, settings: Settings) -> None:
        self.client = genai_client
        self.settings = settings

    # -- model + evaluator selection ---------------------------------------
    def _judge_model(self, modality: Modality) -> str:
        if modality in IMAGE_MODALITIES:
            return self.settings.image_eval_model
        if modality in TTS_MODALITIES:
            return self.settings.tts_eval_model
        return self.settings.eval_model  # video (t2v/i2v/r2v) + default

    def _absolute_evaluator(self, modality: Modality) -> ModuleType:
        if modality in IMAGE_MODALITIES:
            return image_eval
        if modality in TTS_MODALITIES:
            return tts_eval
        return core5

    def _pairwise_evaluator(self, modality: Modality) -> ModuleType:
        if modality in IMAGE_MODALITIES:
            return image_eval
        if modality in TTS_MODALITIES:
            return tts_eval
        return director  # video head-to-head

    # -- core operations ---------------------------------------------------
    async def evaluate_absolute(self, execution: Execution) -> Verdict:
        """Score a single execution on its modality's absolute rubric."""
        modality = execution.modality
        evaluator = self._absolute_evaluator(modality)
        model = self._judge_model(modality)
        contents = evaluator.build_absolute_prompt(execution)
        raw = await self.client.generate_json(model, contents, _JUDGE_CONFIG)
        scores = evaluator.parse_absolute(raw)
        return Verdict(
            mode=EvalMode.ABSOLUTE,
            per_execution={execution.id: scores},
            model=model,
            raw=raw if isinstance(raw, dict) else {},
        )

    async def evaluate_pairwise(
        self, case: Case, exec_a: Execution, exec_b: Execution
    ) -> Verdict:
        """Head-to-head judge of two executions of the same case."""
        modality = case.modality or exec_a.modality
        evaluator = self._pairwise_evaluator(modality)
        model = self._judge_model(modality)
        contents = evaluator.build_pairwise_prompt(case, exec_a, exec_b)
        raw = await self.client.generate_json(model, contents, _JUDGE_CONFIG)
        parsed = evaluator.parse_pairwise(raw)

        winner = parsed.get("winner")
        winner_execution = (
            exec_a.id if winner == "A" else exec_b.id if winner == "B" else None
        )
        sides = parsed.get("sides") or {}
        per_execution: dict[str, dict[str, Any]] = {}
        if sides.get("A"):
            per_execution[exec_a.id] = sides["A"]
        if sides.get("B"):
            per_execution[exec_b.id] = sides["B"]

        return Verdict(
            mode=EvalMode.PAIRWISE,
            winner_execution=winner_execution,
            per_execution=per_execution,
            model=model,
            raw={"parsed": parsed, "response": raw if isinstance(raw, dict) else {}},
        )

    async def evaluate(
        self,
        mode: EvalMode,
        *,
        execution: Execution | None = None,
        case: Case | None = None,
        exec_a: Execution | None = None,
        exec_b: Execution | None = None,
    ) -> list[Verdict]:
        """Dispatch by mode.

        * ``ABSOLUTE`` -> ``[absolute(execution)]``
        * ``PAIRWISE`` -> ``[pairwise(case, exec_a, exec_b)]``
        * ``BOTH``     -> ``[absolute(exec_a), absolute(exec_b), pairwise(...)]``
        """
        if mode == EvalMode.ABSOLUTE:
            if execution is None:
                raise ValueError("ABSOLUTE evaluation requires `execution`")
            return [await self.evaluate_absolute(execution)]

        if mode == EvalMode.PAIRWISE:
            if not (case and exec_a and exec_b):
                raise ValueError("PAIRWISE evaluation requires `case`, `exec_a`, `exec_b`")
            return [await self.evaluate_pairwise(case, exec_a, exec_b)]

        if mode == EvalMode.BOTH:
            if not (case and exec_a and exec_b):
                raise ValueError("BOTH evaluation requires `case`, `exec_a`, `exec_b`")
            return [
                await self.evaluate_absolute(exec_a),
                await self.evaluate_absolute(exec_b),
                await self.evaluate_pairwise(case, exec_a, exec_b),
            ]

        raise ValueError(f"Unsupported EvalMode: {mode!r}")
