"""Video **Core-5** absolute judge — pure prompt-building + response-parsing.

Faithful port of the Core-5 rubric in v2 ``video_evaluator_sdk.py``
(``run_core5_evaluation`` + ``Core5EvaluationReport``). The five axes and their
wording are preserved verbatim so scores stay comparable across v2/v3.

This module is **pure**: no I/O, no network, no ``google.genai`` import. The
actual Gemini call is injected by ``app.services.evaluation.EvaluationService``.

  * ``build_absolute_prompt(execution) -> str`` — the judge instruction text.
  * ``parse_absolute(raw_json) -> dict`` — normalized per-dimension scores plus
    ``overall_score`` = mean of the five axis scores (robust to missing fields).
"""
from __future__ import annotations

from typing import Any

from app.domain.models import Execution

# The exact 5 Core-5 dimension keys (order preserved).
CORE5_DIMENSIONS: list[str] = [
    "prompt_adherence",
    "visual_quality",
    "motion_physics",
    "temporal_consistency",
    "audio_visual_sync",
]

# Reused verbatim from v2 — the strict multi-pass inspection protocol.
CRITICAL_AUDITING_PROTOCOL = """--- CRITICAL AUDITING PROTOCOL ---
You are an ultra-strict professional video auditor. Assume the output is flawed
until proven otherwise. Perform ALL of the following inspection passes before
assigning any score. Cite exact timestamps for every defect you find.

PASS 1 — Diagonal Banding: Scan for diagonal compression banding, posterization,
macro-blocking, or gradient stair-stepping across flat surfaces (skies, walls,
shadows). These are common diffusion/codec artifacts and must be penalized.

PASS 2 — Temporal / Identity Drift: Track every subject across frames. Watch for
identity morphing, face/feature drift, wardrobe or color shifts, background
warping, object popping in/out, and flicker. Any instability is a defect.

PASS 3 — Physics & 'Pasted-On' / Motion Stalls: Verify gravity, momentum,
collisions, and contact shadows. Penalize floatiness, motion reversal, motion
stalls/freezes, and subjects that look 'pasted-on' (no integration with the
scene's lighting or perspective).

PASS 4 — Typographical Stability: If any text, logos, signage, or UI appears,
verify glyphs are legible and STABLE across frames. Garbled, warping, or
shimmering text is a severe defect.

PASS 5 — Texture / Plastic Aesthetic: Inspect skin, fabric, foliage, and metal
for the waxy, over-smoothed 'plastic AI' look, over-sharpening halos, and
unnatural specular highlights. Penalize synthetic, low-fidelity texture.
--- END PROTOCOL ---"""


def build_absolute_prompt(execution: Execution) -> str:
    """Build the Core-5 absolute judge instruction for one generated video."""
    return f"""{CRITICAL_AUDITING_PROTOCOL}

You will now score the Generated Video Output on EXACTLY these five Core-5 axes,
each on an integer scale of 1-5 (1: poor, 5: perfect/flawless). Apply MAXIMUM
strictness. Do NOT award a 5 on any axis unless that axis is genuinely flawless.

  1. prompt_adherence    — instruction/action/object compliance with the prompt.
  2. visual_quality      — fidelity, lighting, sharpness, noise/compression, aesthetic.
  3. motion_physics      — motion smoothness + physical plausibility; penalize motion
                           reversal, stalls, floatiness, and gravity errors.
  4. temporal_consistency— identity/wardrobe/background stability across frames; no
                           morphing, warping, or popping.
  5. audio_visual_sync   — foley/lip-sync timing and acoustic-spatial plausibility.

audio_visual_sync MUST ALWAYS be scored — every input video contains audio.

For each axis return a score (1-5) and a detailed explanation citing visual
evidence and exact timestamps. Compute overall_score as the average of the five
axis scores. List every critical glitch, morph, sudden vanishing, or AV desync
moment in critical_flaws.

--- Target Prompt ---
{execution.prompt}
"""


def _coerce_score(value: Any) -> float | None:
    """Pull a numeric score from a bare number or a ``{"score": ...}`` object."""
    if isinstance(value, dict):
        value = value.get("score")
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_absolute(raw_json: dict | None) -> dict:
    """Normalize a Core-5 judge response.

    Returns a dict with one entry per Core-5 dimension (``{"score", "explanation"}``),
    ``overall_score`` (mean of the available axis scores — the five when the
    response is well-formed) and ``critical_flaws``. Missing/garbled fields
    default gracefully to ``score=None`` and are excluded from the mean.
    """
    raw = raw_json or {}
    scores: list[float] = []
    out: dict[str, Any] = {}
    for dim in CORE5_DIMENSIONS:
        entry = raw.get(dim)
        score = _coerce_score(entry)
        explanation = entry.get("explanation", "") if isinstance(entry, dict) else ""
        out[dim] = {"score": score, "explanation": explanation}
        if score is not None:
            scores.append(score)
    out["overall_score"] = round(sum(scores) / len(scores), 2) if scores else 0.0
    out["critical_flaws"] = raw.get("critical_flaws") or []
    return out
