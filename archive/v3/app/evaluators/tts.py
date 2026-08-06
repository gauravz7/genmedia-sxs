"""TTS judge — pure prompt-building + response-parsing.

Faithful port of the v2 ``tts_evaluator.py`` rubric:

  * naturalness           — human-likeness, free of robotic/synthetic artifacts.
  * style_adherence       — delivery matches requested style / director's notes.
  * expressiveness        — emotional range, intonation, dynamics.
  * pacing                — rhythm, pauses, speed appropriateness.
  * pronunciation_clarity — correct, intelligible articulation.

v3 is execution-centric, so this exposes an **absolute** single-clip judge
(``build_absolute_prompt`` / ``parse_absolute``) plus the original **pairwise**
A/B judge for parity. Pure module — no I/O; the genai call is injected.
"""
from __future__ import annotations

from typing import Any

from app.domain.models import Case, Execution

TTS_METRICS: list[str] = [
    "naturalness",
    "style_adherence",
    "expressiveness",
    "pacing",
    "pronunciation_clarity",
]

_RUBRIC_LINES = (
    "- naturalness: human-likeness, free of robotic/synthetic artifacts.\n"
    "- style_adherence: how well the delivery matches the requested style / "
    "director's notes and any emotion cues.\n"
    "- expressiveness: emotional range, intonation, dynamics.\n"
    "- pacing: rhythm, pauses, speed appropriateness.\n"
    "- pronunciation_clarity: correct, intelligible articulation."
)


def _style_of(obj: Execution | Case) -> str:
    return str(obj.params.get("style_prompt") or obj.params.get("style") or "")


def build_absolute_prompt(execution: Execution) -> str:
    """Build the absolute single-clip TTS judge instruction."""
    style = _style_of(execution)
    parts = [
        "You are an expert speech-quality judge. Score the single generated "
        "text-to-speech clip rendered from the script below. Judge it blind — you "
        "do NOT know which TTS engine produced it.",
        "",
        "Score the clip 1-5 (5 = best) on:",
        _RUBRIC_LINES,
        "",
        f"SCRIPT (intended spoken text): {execution.prompt!r}",
    ]
    if style:
        parts.append(f"REQUESTED STYLE / DIRECTOR'S NOTES: {style!r}")
    parts.append("")
    parts.append(
        "Return ONLY JSON with each metric as an integer 1-5 plus a 'comment' string."
    )
    return "\n".join(parts)


def build_pairwise_prompt(case: Case, exec_a: Execution, exec_b: Execution) -> str:
    """Build the blind A/B pairwise TTS judge instruction (v2 parity)."""
    script = case.prompt
    style = _style_of(case)
    side_fields = ", ".join(f'"{m}": 1-5' for m in TTS_METRICS)
    parts = [
        "You are an expert speech-quality judge for a blind side-by-side "
        "text-to-speech comparison. You will hear two audio clips: CLIP A then "
        "CLIP B. Both are renderings of the SAME script. Judge them blind — you "
        "do NOT know which TTS engine produced which clip.",
        "",
        "Score EACH clip 1-5 (5 = best) on:",
        _RUBRIC_LINES,
        "",
        f"SCRIPT (intended spoken text): {script!r}",
    ]
    if style:
        parts.append(f"REQUESTED STYLE / DIRECTOR'S NOTES: {style!r}")
    parts.append("")
    parts.append("Then pick the overall winner (A, B, or tie). Return ONLY JSON:")
    parts.append("{")
    parts.append(f'  "A": {{{side_fields}, "comment": "string"}},')
    parts.append(f'  "B": {{{side_fields}, "comment": "string"}},')
    parts.append('  "winner": "A" | "B" | "tie",')
    parts.append('  "justification": "string"')
    parts.append("}")
    return "\n".join(parts)


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
    for m in TTS_METRICS:
        score = _to_int_1_5(raw.get(m))
        if score is not None:
            out[m] = score
            collected.append(score)
    out["overall_score"] = round(sum(collected) / len(collected), 2) if collected else 0.0
    if raw.get("comment"):
        out["comment"] = str(raw["comment"])[:1000]
    return out


def parse_absolute(raw_json: dict | None) -> dict:
    """Normalize an absolute single-clip TTS response.

    Returns ``{metric: 1-5, ..., overall_score, comment?}``; ``overall_score`` is
    the mean of the metrics found. Missing/garbled metrics are dropped gracefully.
    """
    return _clean_side(raw_json)


def parse_pairwise(raw_json: dict | None) -> dict:
    """Normalize a pairwise A/B TTS response.

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
