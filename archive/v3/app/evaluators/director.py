"""Creative Director **pairwise** video judge — pure prompt-building + parsing.

Faithful port of v2 ``video_evaluator_sdk.run_director_pairwise`` /
``DirectorReport``: a professional Creative Video Director compares Video A vs
Video B across four categories and declares a winner ('A' or 'B').

Pure module — no I/O. The genai call is injected by ``EvaluationService``.

  * ``build_pairwise_prompt(case, exec_a, exec_b) -> str``
  * ``parse_pairwise(raw_json) -> dict`` -> ``{winner, sides, rationale, per_dimension}``
"""
from __future__ import annotations

from app.domain.models import Case, Execution

DIRECTOR_CATEGORIES: list[str] = [
    "prompt_adherence_intent",
    "cinematic_elements",
    "subject_realism",
    "temporal_stability",
]

_DIRECTOR_SYSTEM = """You are a professional Creative Video Director and Senior Video Editor. Your task is to evaluate and compare two generated videos, Video A and Video B, against a text prompt and an optional reference seed image.
Critique them meticulously based on:
1. Prompt Adherence & Intent (Score: /10)
- Does the video accurately reflect the core action, mood, and setting requested in the prompt?
- Is the emotional tone correct, or did the AI hallucinate a different vibe?

2. Cinematic Elements (Score: /10)
- Composition & Framing: Is the rule of thirds applied? Does the framing make sense for the narrative?
- Lighting & Shadows: Is there a clear, motivated light source? Are the shadows consistent, or do they behave unnaturally?
- Depth of Field & Camera Movement: Does the camera movement feel like a real rig (Steadicam, dolly, drone) or a floating digital camera? Is the focal length realistic?

3. Subject Realism & The "Plastic Skin" Test (Score: /10)
- Texture & Pores: Do human or creature subjects possess realistic skin textures, imperfections, and subsurface scattering?
- The AI Wax Effect: Does the subject suffer from the overly smooth, waxy, "plastic skin" effect typical of GenAI?
- Micro-expressions: Do the eyes feel alive? Are facial movements natural, or do they fall into the uncanny valley?

4. Temporal Stability & Sudden Glitches (Score: /10)
- Consistency: Do characters and background elements maintain their exact shape, size, and texture from the first frame to the last?
- The Glitch Check: Are there sudden glitches, such as morphing limbs, merging fingers, phantom objects appearing/disappearing, or background warping?
- Physics: Does hair, clothing, or water move according to the laws of physics, or does it jitter and clip through other objects?

In your final JSON output:
- The 'verdict' key must be set to 'A' if Video A is overall better/preferred, or 'B' if Video B is overall better/preferred.
- Do not let the 'verdict' contradict your reasoning or scores. If your reasoning states Video A is superior, you MUST set 'verdict' to 'A' (not 'B')."""


def build_pairwise_prompt(case: Case, exec_a: Execution, exec_b: Execution) -> str:
    """Build the Creative Director head-to-head instruction (system + task).

    The system rubric is concatenated so the whole judge instruction lives in a
    single pure string (the injected client passes it as ``contents``).
    """
    task = (
        f'Compare Video A and Video B based on the text prompt: "{case.prompt}"\n'
        "Evaluate their video quality, motion consistency, styling consistency with "
        "the seed image (if provided), and overall creative direction. Provide a "
        "detailed, professional critique comparing the two videos.\n"
        "Based on your comparison, declare the winner in the JSON 'verdict' field. "
        "The 'verdict' MUST be exactly 'A' if Video A is the winner, or exactly 'B' "
        "if Video B is the winner. Your 'verdict' MUST be completely consistent with "
        "your scores and reasoning (e.g. if Video A is described as superior, the "
        "verdict must be 'A')."
    )
    return f"{_DIRECTOR_SYSTEM}\n\n{task}"


def parse_pairwise(raw_json: dict | None) -> dict:
    """Normalize a Creative Director response.

    Returns ``{"winner": "A"|"B"|None, "sides": {}, "rationale": str,
    "per_dimension": list}``. ``winner`` is ``None`` for a tie/unparseable
    verdict. ``sides`` is empty — the director gives a comparative critique
    rather than independent per-side scores (see ``per_dimension``).
    """
    raw = raw_json or {}
    verdict = str(raw.get("verdict") or "").strip().upper()
    winner = verdict if verdict in ("A", "B") else None
    return {
        "winner": winner,
        "sides": {},
        "rationale": str(raw.get("reasoning") or ""),
        "per_dimension": raw.get("critique_results") or [],
    }
