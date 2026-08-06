"""Image judge — pure prompt-building + response-parsing.

Faithful port of the v2 ``image_evaluator.py`` rubric:

  * prompt_following — how faithfully the image satisfies the prompt.
  * aesthetic        — overall aesthetic quality, composition, color, lighting.
  * detail           — sharpness, fine detail, texture, resolution feel.
  * artifact_free    — absence of distortions/glitches/malformed shapes.
  * edit_fidelity    — (I2I only) requested edit applied while preserving the rest.

v3 is execution-centric so this module exposes an **absolute** single-image judge
(``build_absolute_prompt`` / ``parse_absolute``) plus the original **pairwise**
A/B judge for parity. Pure module — no I/O; the genai call is injected.
"""
from __future__ import annotations

from typing import Any

from app.domain.models import Case, Execution, Modality

IMAGE_BASE_METRICS: list[str] = ["prompt_following", "aesthetic", "detail", "artifact_free"]
IMAGE_EDIT_METRIC = "edit_fidelity"


def _is_i2i(mode: str | None, modality: Modality | None) -> bool:
    return (mode or "").lower() == "i2i" or modality == Modality.I2I


def metrics_for(is_i2i: bool) -> list[str]:
    return IMAGE_BASE_METRICS + ([IMAGE_EDIT_METRIC] if is_i2i else [])


def _rubric_lines(is_i2i: bool) -> str:
    lines = [
        "- prompt_following: how faithfully the image satisfies the prompt.",
        "- aesthetic: overall aesthetic quality, composition, color, lighting.",
        "- detail: sharpness, fine detail, texture, resolution feel.",
        "- artifact_free: absence of distortions, glitches, malformed shapes, "
        "garbled text, extra/missing limbs.",
    ]
    if is_i2i:
        lines.append(
            "- edit_fidelity: did it apply the requested edit while preserving "
            "the rest of the original image (identity, layout, background)?"
        )
    return "\n".join(lines)


def build_absolute_prompt(execution: Execution) -> str:
    """Build the absolute single-image judge instruction."""
    is_i2i = _is_i2i(execution.mode, execution.modality)
    edit_note = " by editing an input image." if is_i2i else "."
    return (
        "You are an expert image-quality judge. Score the single generated image "
        f"produced from the prompt below{edit_note} Judge it blind — you do NOT "
        "know which model produced it.\n\n"
        "Score the image 1-5 (5 = best) on:\n"
        f"{_rubric_lines(is_i2i)}\n\n"
        f"PROMPT (intended result): {execution.prompt!r}\n\n"
        "Return ONLY JSON with each metric as an integer 1-5 plus a 'comment' string."
    )


def build_pairwise_prompt(case: Case, exec_a: Execution, exec_b: Execution) -> str:
    """Build the blind A/B pairwise image judge instruction (v2 parity)."""
    is_i2i = _is_i2i(case.mode, case.modality)
    edit_note = " by editing the SAME input image." if is_i2i else "."
    metrics = metrics_for(is_i2i)
    side_fields = ", ".join(f'"{m}": 1-5' for m in metrics)
    return (
        "You are an expert image-quality judge for a blind side-by-side image "
        "comparison. You will see two images: IMAGE A then IMAGE B. Both were "
        f"produced from the SAME prompt{edit_note} Judge them blind — you do NOT "
        "know which model produced which image.\n\n"
        "Score EACH image 1-5 (5 = best) on:\n"
        f"{_rubric_lines(is_i2i)}\n\n"
        f"PROMPT (intended result): {case.prompt!r}\n\n"
        "Then pick the overall winner (A, B, or tie). Return ONLY JSON:\n"
        "{\n"
        f'  "A": {{{side_fields}, "comment": "string"}},\n'
        f'  "B": {{{side_fields}, "comment": "string"}},\n'
        '  "winner": "A" | "B" | "tie",\n'
        '  "justification": "string"\n'
        "}"
    )


def _to_int_1_5(value: Any) -> int | None:
    try:
        n = int(round(float(value)))
    except (TypeError, ValueError):
        return None
    return max(1, min(5, n))


def _clean_side(raw: dict | None) -> dict:
    raw = raw or {}
    out: dict[str, Any] = {}
    collected: list[int] = []
    for m in IMAGE_BASE_METRICS + [IMAGE_EDIT_METRIC]:
        score = _to_int_1_5(raw.get(m))
        if score is not None:
            out[m] = score
            collected.append(score)
    out["overall_score"] = round(sum(collected) / len(collected), 2) if collected else 0.0
    if raw.get("comment"):
        out["comment"] = str(raw["comment"])[:1000]
    return out


def parse_absolute(raw_json: dict | None) -> dict:
    """Normalize an absolute single-image judge response.

    Returns ``{metric: 1-5, ..., overall_score, comment?}``. ``edit_fidelity`` is
    included only when present. ``overall_score`` is the mean of the metrics
    found; missing/garbled metrics are dropped gracefully.
    """
    return _clean_side(raw_json)


def parse_pairwise(raw_json: dict | None) -> dict:
    """Normalize a pairwise A/B image response.

    Returns ``{"winner": "A"|"B"|None, "sides": {"A", "B"}, "rationale": str}``.
    """
    raw = raw_json or {}
    sides = {"A": _clean_side(raw.get("A")), "B": _clean_side(raw.get("B"))}
    winner = str(raw.get("winner") or "").strip().upper()
    return {
        "winner": winner if winner in ("A", "B") else None,
        "sides": sides,
        "rationale": str(raw.get("justification") or ""),
    }
