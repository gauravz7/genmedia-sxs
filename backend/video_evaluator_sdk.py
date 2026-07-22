"""Gemini-3.5-Flash LLM-as-judge module for evaluating generated videos.

The centerpiece is :func:`run_core5_evaluation`, a focused 5-axis auto-eval used
by the SxS pipeline. The remaining ``run_*_evaluation`` functions are faithful
ports of the user's specialized rubric judges (Canva, product-ad, human
consistency, storytelling, audio-visual sync).

All judges share:
  * The cached Vertex client factory :func:`_get_eval_client`.
  * The :func:`generate_content_with_retry` retry wrapper.
  * The ``CRITICAL AUDITING PROTOCOL`` inspection block.
  * ``model=EVAL_MODEL``, ``temperature=0.1``, ``thinking_level="HIGH"``,
    ``response_mime_type="application/json"`` with a pydantic ``response_schema``.

The module is importable with no side effects (the client is built lazily).
"""

import os
import json
import subprocess
import time
import base64
import tempfile
import concurrent.futures
from typing import Optional, List

from pydantic import BaseModel, Field
import PIL.Image

from google import genai
from google.genai import types


# ---------------------------------------------------------------------------
# Module-level config (env-overridable)
# ---------------------------------------------------------------------------
EVAL_PROJECT = os.getenv("EVAL_PROJECT", "vital-octagon-19612")
EVAL_LOCATION = os.getenv("EVAL_LOCATION", "global")
EVAL_MODEL = os.getenv("EVAL_MODEL", "gemini-3.1-pro-preview")


_eval_client = None


def _get_eval_client():
    global _eval_client
    if _eval_client is None:
        _eval_client = genai.Client(vertexai=True, project=EVAL_PROJECT, location=EVAL_LOCATION,
                                    http_options=types.HttpOptions(timeout=600000))  # ms (=10 min)
    return _eval_client


# ---------------------------------------------------------------------------
# Retry wrapper (VERBATIM)
# ---------------------------------------------------------------------------
def generate_content_with_retry(client, model, contents, config, max_retries=4, initial_delay=6.0):
    delay = initial_delay
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(model=model, contents=contents, config=config)
            return response
        except Exception as e:
            print(f"  [Attempt {attempt+1}/{max_retries}] API call failed: {e}")
            if attempt == max_retries - 1:
                raise e
            print(f"  Retrying in {delay} seconds...")
            time.sleep(delay)
            delay *= 2


# ---------------------------------------------------------------------------
# Video metadata via ffprobe (VERBATIM)
# ---------------------------------------------------------------------------
def get_video_metadata(video_path):
    """Use ffprobe to get duration + fps. Returns {"duration", "fps"}.

    Gracefully returns {"duration": None, "fps": None} on any exception
    (ffprobe may not be installed — that's fine).
    """
    try:
        cmd = [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=duration,r_frame_rate",
            "-of", "json", video_path,
        ]
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        info = json.loads(out)
        stream = info.get("streams", [{}])[0]

        duration = None
        if stream.get("duration") is not None:
            duration = float(stream["duration"])

        fps = None
        rate = stream.get("r_frame_rate")
        if rate and "/" in rate:
            num, den = rate.split("/")
            den_f = float(den)
            if den_f != 0:
                fps = float(num) / den_f
        elif rate:
            fps = float(rate)

        return {"duration": duration, "fps": fps}
    except Exception:
        return {"duration": None, "fps": None}


# ---------------------------------------------------------------------------
# Shared auditing protocol (reused by every judge)
# ---------------------------------------------------------------------------
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


# ===========================================================================
# Core-5 rubric — THE PRIMARY DELIVERABLE
# ===========================================================================
class RubricScore(BaseModel):
    score: int = Field(description="Score 1-5 (1: poor, 5: perfect/flawless)")
    explanation: str = Field(description="Detailed explanation citing visual evidence and timestamps.")


class Core5EvaluationReport(BaseModel):
    prompt_adherence: RubricScore = Field(description="Instruction/action/object compliance with the prompt.")
    visual_quality: RubricScore = Field(description="Fidelity, lighting, sharpness, noise/compression, overall aesthetic.")
    motion_physics: RubricScore = Field(description="Motion smoothness + physical plausibility; penalize motion reversal, stalls, floatiness, gravity errors.")
    temporal_consistency: RubricScore = Field(description="Identity/wardrobe/background stability across frames; no morphing, warping, popping.")
    audio_visual_sync: RubricScore = Field(description="Foley/lip-sync timing and acoustic-spatial plausibility. ALWAYS evaluated (all inputs have audio).")
    overall_score: float = Field(description="Average of the five rubric scores.")
    critical_flaws: List[str] = Field(description="Critical glitches, morphs, sudden vanishings, or AV desync moments.")


def run_core5_evaluation(video_path: str, prompt: str, reference_images: Optional[List[str]] = None,
                         source_videos: Optional[List[str]] = None) -> Optional[dict]:
    """Run the focused Core-5 auto-eval on a single generated video.

    Returns the parsed JSON report dict, or None on failure.
    """
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video not found: {video_path}")

    client = _get_eval_client()

    meta = get_video_metadata(video_path)
    if meta.get("duration") is not None and meta.get("fps") is not None:
        meta_str = f"Actual Duration: {meta['duration']:.2f}s | Frame Rate: {meta['fps']:.2f} fps"
    else:
        meta_str = "Metadata Unavailable"

    with open(video_path, "rb") as fh:
        video_bytes = fh.read()
    video_part = types.Part.from_bytes(data=video_bytes, mime_type="video/mp4")

    contents = ["--- Generated Video Output to Evaluate ---", video_part]

    has_references = False
    if reference_images:
        for i, img_path in enumerate(reference_images, start=1):
            if img_path and os.path.exists(img_path):
                has_references = True
                contents.append(f"--- Reference Image {i} ---")
                contents.append(PIL.Image.open(img_path))

    has_source = False
    if source_videos:
        for i, src_path in enumerate(source_videos, start=1):
            if src_path and os.path.exists(src_path):
                has_source = True
                with open(src_path, "rb") as fh:
                    src_bytes = fh.read()
                contents.append(f"--- Reference Video {i} (Source) ---")
                contents.append(types.Part.from_bytes(data=src_bytes, mime_type="video/mp4"))

    preservation_note = ""
    if has_references or has_source:
        preservation_note = (
            "\n\nReference assets are provided. Where a Reference Image is present, factor "
            "subject/identity preservation into temporal_consistency and prompt_adherence. "
            "Where a Reference Video (Source) is present (V2V baseline), factor source "
            "preservation/faithfulness into visual_quality and temporal_consistency."
        )

    eval_instruction = f"""{CRITICAL_AUDITING_PROTOCOL}

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
{prompt}

--- Verified Video Metadata (ground truth — DO NOT hallucinate duration/fps) ---
{meta_str}{preservation_note}
"""

    contents.append(eval_instruction)

    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=Core5EvaluationReport,
        temperature=0.1,
        thinking_config=types.ThinkingConfig(thinking_level="HIGH"),
    )

    try:
        response = generate_content_with_retry(client, EVAL_MODEL, contents, config)
        return json.loads(response.text)
    except Exception as e:
        print(f"[run_core5_evaluation] evaluation failed: {e}")
        return None


# ===========================================================================
# Pairwise "Creative Director" judge — Video A vs Video B head-to-head
# ===========================================================================
class DirectorCritiqueItem(BaseModel):
    Category: str = Field(description="The critique category name.")
    Score: str = Field(description="Score from 0-10 (may note A vs B).")
    Reasoning: str = Field(description="Reasoning for the score, comparing Video A and Video B.")


class DirectorReport(BaseModel):
    verdict: str = Field(description="'A' if Video A is better overall, 'B' if Video B is better overall.")
    reasoning: str = Field(description="Brief reasoning for the overall decision.")
    critique_results: List[DirectorCritiqueItem] = Field(description="Per-category comparative critique.")


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


def run_director_pairwise(video_a_path: str, video_b_path: str, prompt: str,
                          seed_images: Optional[List[str]] = None) -> Optional[dict]:
    """Head-to-head 'Creative Director' critique of Video A vs Video B.

    Returns {verdict:'A'|'B', reasoning, critique_results:[{Category,Score,Reasoning}]}.
    """
    if not os.path.exists(video_a_path) or not os.path.exists(video_b_path):
        raise FileNotFoundError("Both Video A and Video B are required")

    client = _get_eval_client()

    with open(video_a_path, "rb") as fh:
        a_bytes = fh.read()
    with open(video_b_path, "rb") as fh:
        b_bytes = fh.read()

    contents: list = [
        "--- Video A ---",
        types.Part.from_bytes(data=a_bytes, mime_type="video/mp4"),
        "--- Video B ---",
        types.Part.from_bytes(data=b_bytes, mime_type="video/mp4"),
    ]
    if seed_images:
        for i, img_path in enumerate(seed_images, start=1):
            if img_path and os.path.exists(img_path):
                contents.append(f"--- Reference Seed Image {i} ---")
                contents.append(PIL.Image.open(img_path))

    prompt_text = (
        f"Compare Video A and Video B based on the text prompt: \"{prompt}\"\n"
        f"Evaluate their video quality, motion consistency, styling consistency with the seed image (if provided), "
        f"and overall creative direction. Provide a detailed, professional critique comparing the two videos.\n"
        f"Based on your comparison, declare the winner in the JSON 'verdict' field. The 'verdict' MUST be exactly 'A' "
        f"if Video A is the winner, or exactly 'B' if Video B is the winner. Your 'verdict' MUST be completely consistent "
        f"with your scores and reasoning (e.g. if Video A is described as superior, the verdict must be 'A')."
    )
    contents.append(prompt_text)

    config = types.GenerateContentConfig(
        system_instruction=_DIRECTOR_SYSTEM,
        response_mime_type="application/json",
        response_schema=DirectorReport,
        temperature=0.1,
        thinking_config=types.ThinkingConfig(thinking_level="HIGH"),
    )

    try:
        response = generate_content_with_retry(client, EVAL_MODEL, contents, config)
        return json.loads(response.text)
    except Exception as e:
        print(f"[run_director_pairwise] evaluation failed: {e}")
        return None


# ===========================================================================
# Ported specialized rubric judges
# ===========================================================================

# --- Canva ---------------------------------------------------------------
class CanvaVideoEvaluationReport(BaseModel):
    prompt_adherence: RubricScore = Field(description="Does the video execute every stated element, action, object, and timing in the prompt?")
    text_rendering: RubricScore = Field(description="Legibility and stability of any rendered text, captions, titles, or kinetic typography across all frames.")
    layout_composition: RubricScore = Field(description="Framing, balance, safe-area usage, alignment, and overall graphic-design composition.")
    brand_consistency: RubricScore = Field(description="Consistency of color palette, fonts, logos, and brand styling throughout the video.")
    visual_quality: RubricScore = Field(description="Resolution, sharpness, lighting, color grading, and freedom from compression/diffusion artifacts.")
    motion_design: RubricScore = Field(description="Quality of animated transitions, easing, and kinetic motion-graphics polish.")
    temporal_consistency: RubricScore = Field(description="Stability of identity, assets, and background across frames; no morphing/popping/flicker.")
    physics_plausibility: RubricScore = Field(description="Physical plausibility of motion (gravity, momentum, collisions, contact shadows).")
    color_harmony: RubricScore = Field(description="Aesthetic harmony and intentionality of the color scheme.")
    pacing_rhythm: RubricScore = Field(description="Pacing, rhythm, and timing of cuts/transitions relative to content and audio.")
    audio_quality: RubricScore = Field(description="Clarity, mix balance, and absence of distortion in any audio track.")
    audio_visual_sync: RubricScore = Field(description="Timing alignment of audio events (music hits, foley, VO) with on-screen action.")
    overall_polish: RubricScore = Field(description="Holistic 'ready-to-publish' production polish for a Canva-style design deliverable.")
    overall_score: float = Field(description="Average of all rubric dimension scores.")
    critical_flaws: List[str] = Field(description="Critical defects: garbled text, brand breaks, severe artifacts, or AV desync.")


def run_canva_evaluation(video_path: str, prompt: str, reference_images: Optional[List[str]] = None,
                         source_videos: Optional[List[str]] = None) -> Optional[dict]:
    """Canva-style design-video judge across 13 dimensions."""
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video not found: {video_path}")

    client = _get_eval_client()

    meta = get_video_metadata(video_path)
    if meta.get("duration") is not None and meta.get("fps") is not None:
        meta_str = f"Actual Duration: {meta['duration']:.2f}s | Frame Rate: {meta['fps']:.2f} fps"
    else:
        meta_str = "Metadata Unavailable"

    with open(video_path, "rb") as fh:
        video_bytes = fh.read()
    video_part = types.Part.from_bytes(data=video_bytes, mime_type="video/mp4")

    contents = ["--- Generated Video Output to Evaluate ---", video_part]

    if reference_images:
        for i, img_path in enumerate(reference_images, start=1):
            if img_path and os.path.exists(img_path):
                contents.append(f"--- Reference Image {i} ---")
                contents.append(PIL.Image.open(img_path))

    if source_videos:
        for i, src_path in enumerate(source_videos, start=1):
            if src_path and os.path.exists(src_path):
                with open(src_path, "rb") as fh:
                    src_bytes = fh.read()
                contents.append(f"--- Reference Video {i} (Source) ---")
                contents.append(types.Part.from_bytes(data=src_bytes, mime_type="video/mp4"))

    eval_instruction = f"""{CRITICAL_AUDITING_PROTOCOL}

You are auditing a Canva-style design/marketing video. Score ALL 13 dimensions
below, each on an integer scale of 1-5 (1: poor, 5: flawless), with MAXIMUM
strictness. Never award a 5 unless that dimension is genuinely flawless.

  1.  prompt_adherence     — every stated element/action/object/timing executed.
  2.  text_rendering       — legibility AND cross-frame stability of all text.
  3.  layout_composition   — framing, balance, safe-area, alignment.
  4.  brand_consistency    — palette/fonts/logos/styling consistency.
  5.  visual_quality       — resolution, sharpness, grading, artifact-free.
  6.  motion_design        — transition/easing/kinetic-graphics polish.
  7.  temporal_consistency — identity/asset/background stability, no morph/flicker.
  8.  physics_plausibility — gravity/momentum/collision/contact-shadow realism.
  9.  color_harmony        — harmony and intentionality of the palette.
  10. pacing_rhythm        — pacing/rhythm/timing of cuts vs content + audio.
  11. audio_quality        — clarity/mix/no-distortion of audio.
  12. audio_visual_sync    — audio events aligned to on-screen action.
  13. overall_polish       — holistic ready-to-publish production polish.

For each dimension return a score and an explanation citing timestamps and visual
evidence. Compute overall_score as the average of all dimension scores. List
critical defects (garbled text, brand breaks, severe artifacts, AV desync) in
critical_flaws.

--- Target Prompt ---
{prompt}

--- Verified Video Metadata (ground truth — DO NOT hallucinate duration/fps) ---
{meta_str}
"""

    contents.append(eval_instruction)

    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=CanvaVideoEvaluationReport,
        temperature=0.1,
        thinking_config=types.ThinkingConfig(thinking_level="HIGH"),
    )

    try:
        response = generate_content_with_retry(client, EVAL_MODEL, contents, config)
        return json.loads(response.text)
    except Exception as e:
        print(f"[run_canva_evaluation] evaluation failed: {e}")
        return None


# --- Product Ad ----------------------------------------------------------
class ProductFidelity(BaseModel):
    score: int = Field(description="Score 1-5 (1: poor, 5: flawless)")
    explanation: str = Field(description="How faithfully the product's shape, logo, label, color, and material are preserved vs the reference. Cite timestamps.")


class SpatialLogic(BaseModel):
    score: int = Field(description="Score 1-5 (1: poor, 5: flawless)")
    explanation: str = Field(description="Plausibility of product placement, scale, perspective, and grounding within the scene. Cite timestamps.")


class TemporalSceneConsistency(BaseModel):
    score: int = Field(description="Score 1-5 (1: poor, 5: flawless)")
    explanation: str = Field(description="Stability of the product and scene across frames; no morphing/warping/popping/label drift. Cite timestamps.")


class VisualCinematicQuality(BaseModel):
    score: int = Field(description="Score 1-5 (1: poor, 5: flawless)")
    explanation: str = Field(description="Lighting, color grading, sharpness, and cinematic appeal of the ad. Cite timestamps.")


class ProductAdVideoEvaluationReport(BaseModel):
    product_fidelity: ProductFidelity = Field(description="Faithfulness of the product to the reference (shape/logo/label/color/material).")
    spatial_logic: SpatialLogic = Field(description="Plausible placement, scale, perspective, and grounding of the product.")
    temporal_scene_consistency: TemporalSceneConsistency = Field(description="Cross-frame stability of product and scene.")
    visual_cinematic_quality: VisualCinematicQuality = Field(description="Cinematic lighting/grading/sharpness/appeal.")
    overall_score: float = Field(description="Average of the four rubric scores.")
    critical_flaws: List[str] = Field(description="Critical defects: label distortion, product morphing, impossible placement, severe artifacts.")


def run_product_ad_evaluation(video_path: str, prompt: str, reference_images: Optional[List[str]] = None,
                              source_videos: Optional[List[str]] = None) -> Optional[dict]:
    """Product-advertisement judge focused on product fidelity and scene logic."""
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video not found: {video_path}")

    client = _get_eval_client()

    meta = get_video_metadata(video_path)
    if meta.get("duration") is not None and meta.get("fps") is not None:
        meta_str = f"Actual Duration: {meta['duration']:.2f}s | Frame Rate: {meta['fps']:.2f} fps"
    else:
        meta_str = "Metadata Unavailable"

    with open(video_path, "rb") as fh:
        video_bytes = fh.read()
    video_part = types.Part.from_bytes(data=video_bytes, mime_type="video/mp4")

    contents = ["--- Generated Video Output to Evaluate ---", video_part]

    if reference_images:
        for i, img_path in enumerate(reference_images, start=1):
            if img_path and os.path.exists(img_path):
                contents.append(f"--- Reference Image {i} (Product) ---")
                contents.append(PIL.Image.open(img_path))

    if source_videos:
        for i, src_path in enumerate(source_videos, start=1):
            if src_path and os.path.exists(src_path):
                with open(src_path, "rb") as fh:
                    src_bytes = fh.read()
                contents.append(f"--- Reference Video {i} (Source) ---")
                contents.append(types.Part.from_bytes(data=src_bytes, mime_type="video/mp4"))

    eval_instruction = f"""{CRITICAL_AUDITING_PROTOCOL}

You are auditing a PRODUCT ADVERTISEMENT video. The single most important factor
is PRODUCT FIDELITY — the product must match the Reference Image(s) exactly in
shape, logo, label text, color, and material. Score the following four axes, each
on an integer scale of 1-5 (1: poor, 5: flawless), with MAXIMUM strictness. Never
award a 5 unless the axis is genuinely flawless.

  1. product_fidelity            — faithfulness to the reference product.
  2. spatial_logic               — placement/scale/perspective/grounding.
  3. temporal_scene_consistency  — cross-frame stability of product and scene.
  4. visual_cinematic_quality    — lighting/grading/sharpness/cinematic appeal.

Any distortion of the logo or label text is a SEVERE product_fidelity defect and
must be listed in critical_flaws. For each axis return a score and an explanation
citing timestamps and visual evidence. Compute overall_score as the average of
the four axis scores.

--- Target Prompt ---
{prompt}

--- Verified Video Metadata (ground truth — DO NOT hallucinate duration/fps) ---
{meta_str}
"""

    contents.append(eval_instruction)

    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=ProductAdVideoEvaluationReport,
        temperature=0.1,
        thinking_config=types.ThinkingConfig(thinking_level="HIGH"),
    )

    try:
        response = generate_content_with_retry(client, EVAL_MODEL, contents, config)
        return json.loads(response.text)
    except Exception as e:
        print(f"[run_product_ad_evaluation] evaluation failed: {e}")
        return None


# --- Human Consistency ---------------------------------------------------
class HumanConsistentScore(BaseModel):
    score: int = Field(description="Score 0-3 (0: severe failure, 1: poor, 2: minor issues, 3: flawless).")
    explanation: str = Field(description="Detailed explanation citing visual evidence and timestamps.")


class HumanConsistencyEvaluationReport(BaseModel):
    identity_preservation: HumanConsistentScore = Field(description="0-3. Faithfulness of facial identity to the reference across all frames; penalize face drift/morphing.")
    body_wardrobe_consistency: HumanConsistentScore = Field(description="0-3. Stability of body proportions, hair, skin, and wardrobe across frames.")
    motion_naturalness: HumanConsistentScore = Field(description="0-3. Natural, anatomically plausible human motion; penalize warping limbs, extra/missing digits, uncanny gait.")
    overall_score: int = Field(description="Sum of the three 0-3 scores (max 9).")
    decision: str = Field(description="Final decision string, e.g. 'PASS' or 'FAIL', based on the overall consistency.")
    critical_flaws: List[str] = Field(description="Critical defects: identity swaps, extra limbs/digits, face morphing, wardrobe drift.")


def run_human_consistency_evaluation(video_path: str, prompt: str, reference_images: Optional[List[str]] = None,
                                     source_videos: Optional[List[str]] = None) -> Optional[dict]:
    """Human-consistency judge on a 0-3 scale (overall = sum, max 9)."""
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video not found: {video_path}")

    client = _get_eval_client()

    meta = get_video_metadata(video_path)
    if meta.get("duration") is not None and meta.get("fps") is not None:
        meta_str = f"Actual Duration: {meta['duration']:.2f}s | Frame Rate: {meta['fps']:.2f} fps"
    else:
        meta_str = "Metadata Unavailable"

    with open(video_path, "rb") as fh:
        video_bytes = fh.read()
    video_part = types.Part.from_bytes(data=video_bytes, mime_type="video/mp4")

    contents = ["--- Generated Video Output to Evaluate ---", video_part]

    if reference_images:
        for i, img_path in enumerate(reference_images, start=1):
            if img_path and os.path.exists(img_path):
                contents.append(f"--- Reference Image {i} (Subject) ---")
                contents.append(PIL.Image.open(img_path))

    if source_videos:
        for i, src_path in enumerate(source_videos, start=1):
            if src_path and os.path.exists(src_path):
                with open(src_path, "rb") as fh:
                    src_bytes = fh.read()
                contents.append(f"--- Reference Video {i} (Source) ---")
                contents.append(types.Part.from_bytes(data=src_bytes, mime_type="video/mp4"))

    eval_instruction = f"""{CRITICAL_AUDITING_PROTOCOL}

You are auditing HUMAN CONSISTENCY in a generated video. Score the following three
axes on an integer scale of 0-3 (0: severe failure, 1: poor, 2: minor issues,
3: flawless), with MAXIMUM strictness.

  1. identity_preservation     — facial identity faithful to the reference across
                                 all frames; penalize face drift/morphing/swaps.
  2. body_wardrobe_consistency — stable body proportions, hair, skin, wardrobe.
  3. motion_naturalness        — natural, anatomically plausible human motion;
                                 penalize warping limbs, extra/missing digits,
                                 uncanny gait.

For each axis return a score (0-3) and an explanation citing timestamps. Compute
overall_score as the SUM of the three axis scores (maximum 9). Set decision to
'PASS' only if the human is convincingly consistent and natural; otherwise 'FAIL'.
List identity swaps, extra limbs/digits, face morphing, and wardrobe drift in
critical_flaws.

--- Target Prompt ---
{prompt}

--- Verified Video Metadata (ground truth — DO NOT hallucinate duration/fps) ---
{meta_str}
"""

    contents.append(eval_instruction)

    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=HumanConsistencyEvaluationReport,
        temperature=0.1,
        thinking_config=types.ThinkingConfig(thinking_level="HIGH"),
    )

    try:
        response = generate_content_with_retry(client, EVAL_MODEL, contents, config)
        return json.loads(response.text)
    except Exception as e:
        print(f"[run_human_consistency_evaluation] evaluation failed: {e}")
        return None


# --- Storytelling --------------------------------------------------------
class StorytellingEvaluationReport(BaseModel):
    narrative_coherence: RubricScore = Field(description="Logical, comprehensible story progression with a clear beginning/middle/end.")
    emotional_impact: RubricScore = Field(description="Emotional resonance, tone, and the ability to evoke the intended feeling.")
    character_continuity: RubricScore = Field(description="Consistency of characters' identity, behavior, and arc throughout the video.")
    scene_transitions: RubricScore = Field(description="Clarity and smoothness of transitions between narrative beats/scenes.")
    pacing: RubricScore = Field(description="Storytelling pacing and rhythm; neither rushed nor dragging.")
    prompt_adherence: RubricScore = Field(description="Faithfulness of the story to the requested premise, beats, and tone.")
    overall_score: float = Field(description="Average of the rubric scores.")
    critical_flaws: List[str] = Field(description="Critical narrative defects: plot holes, character breaks, incoherent or jarring cuts.")


def run_storytelling_evaluation(video_path: str, prompt: str, reference_images: Optional[List[str]] = None,
                                source_videos: Optional[List[str]] = None) -> Optional[dict]:
    """Storytelling/narrative judge."""
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video not found: {video_path}")

    client = _get_eval_client()

    meta = get_video_metadata(video_path)
    if meta.get("duration") is not None and meta.get("fps") is not None:
        meta_str = f"Actual Duration: {meta['duration']:.2f}s | Frame Rate: {meta['fps']:.2f} fps"
    else:
        meta_str = "Metadata Unavailable"

    with open(video_path, "rb") as fh:
        video_bytes = fh.read()
    video_part = types.Part.from_bytes(data=video_bytes, mime_type="video/mp4")

    contents = ["--- Generated Video Output to Evaluate ---", video_part]

    if reference_images:
        for i, img_path in enumerate(reference_images, start=1):
            if img_path and os.path.exists(img_path):
                contents.append(f"--- Reference Image {i} ---")
                contents.append(PIL.Image.open(img_path))

    if source_videos:
        for i, src_path in enumerate(source_videos, start=1):
            if src_path and os.path.exists(src_path):
                with open(src_path, "rb") as fh:
                    src_bytes = fh.read()
                contents.append(f"--- Reference Video {i} (Source) ---")
                contents.append(types.Part.from_bytes(data=src_bytes, mime_type="video/mp4"))

    eval_instruction = f"""{CRITICAL_AUDITING_PROTOCOL}

You are auditing the STORYTELLING quality of a generated video. Score the following
axes, each on an integer scale of 1-5 (1: poor, 5: flawless), with MAXIMUM
strictness. Never award a 5 unless the axis is genuinely flawless.

  1. narrative_coherence  — logical, comprehensible story with clear beginning/middle/end.
  2. emotional_impact     — emotional resonance, tone, intended feeling evoked.
  3. character_continuity — consistent character identity/behavior/arc.
  4. scene_transitions    — clear, smooth transitions between beats/scenes.
  5. pacing               — storytelling rhythm; neither rushed nor dragging.
  6. prompt_adherence     — faithfulness to the requested premise, beats, and tone.

For each axis return a score and an explanation citing timestamps and narrative
evidence. Compute overall_score as the average of the axis scores. List plot
holes, character breaks, and incoherent/jarring cuts in critical_flaws.

--- Target Prompt ---
{prompt}

--- Verified Video Metadata (ground truth — DO NOT hallucinate duration/fps) ---
{meta_str}
"""

    contents.append(eval_instruction)

    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=StorytellingEvaluationReport,
        temperature=0.1,
        thinking_config=types.ThinkingConfig(thinking_level="HIGH"),
    )

    try:
        response = generate_content_with_retry(client, EVAL_MODEL, contents, config)
        return json.loads(response.text)
    except Exception as e:
        print(f"[run_storytelling_evaluation] evaluation failed: {e}")
        return None


# --- Audio-Visual Sync ---------------------------------------------------
class AudioVisualSyncReport(BaseModel):
    lip_sync: RubricScore = Field(description="Accuracy of mouth movements vs spoken audio/dialogue, frame-by-frame.")
    foley_timing: RubricScore = Field(description="Timing of foley/sound effects relative to the on-screen events that produce them.")
    acoustic_spatial_plausibility: RubricScore = Field(description="Plausibility of acoustics/spatialization (reverb, distance, panning) vs the depicted environment.")
    music_alignment: RubricScore = Field(description="Alignment of musical accents/hits with visual beats and cuts.")
    audio_quality: RubricScore = Field(description="Clarity, mix balance, and absence of distortion/clipping in the audio.")
    overall_score: float = Field(description="Average of the rubric scores.")
    critical_flaws: List[str] = Field(description="Critical AV defects: desync moments, missing/incorrect foley, lip-sync drift.")


def run_audiovisual_evaluation(video_path: str, prompt: str, reference_images: Optional[List[str]] = None,
                               source_videos: Optional[List[str]] = None) -> Optional[dict]:
    """Audio-visual sync judge. Always applicable (all videos contain audio)."""
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video not found: {video_path}")

    client = _get_eval_client()

    meta = get_video_metadata(video_path)
    if meta.get("duration") is not None and meta.get("fps") is not None:
        meta_str = f"Actual Duration: {meta['duration']:.2f}s | Frame Rate: {meta['fps']:.2f} fps"
    else:
        meta_str = "Metadata Unavailable"

    with open(video_path, "rb") as fh:
        video_bytes = fh.read()
    video_part = types.Part.from_bytes(data=video_bytes, mime_type="video/mp4")

    contents = ["--- Generated Video Output to Evaluate ---", video_part]

    if reference_images:
        for i, img_path in enumerate(reference_images, start=1):
            if img_path and os.path.exists(img_path):
                contents.append(f"--- Reference Image {i} ---")
                contents.append(PIL.Image.open(img_path))

    if source_videos:
        for i, src_path in enumerate(source_videos, start=1):
            if src_path and os.path.exists(src_path):
                with open(src_path, "rb") as fh:
                    src_bytes = fh.read()
                contents.append(f"--- Reference Video {i} (Source) ---")
                contents.append(types.Part.from_bytes(data=src_bytes, mime_type="video/mp4"))

    eval_instruction = f"""{CRITICAL_AUDITING_PROTOCOL}

You are auditing AUDIO-VISUAL SYNC in a generated video. Every input video contains
audio, so ALL axes must be scored. Score the following axes, each on an integer
scale of 1-5 (1: poor, 5: flawless), with MAXIMUM strictness. Never award a 5
unless the axis is genuinely flawless.

  1. lip_sync                        — mouth movements vs spoken audio, frame-by-frame.
  2. foley_timing                    — sfx timing vs the on-screen events producing them.
  3. acoustic_spatial_plausibility   — reverb/distance/panning vs depicted environment.
  4. music_alignment                 — musical accents/hits aligned to visual beats/cuts.
  5. audio_quality                   — clarity/mix/no-distortion/no-clipping.

For each axis return a score and an explanation citing exact timestamps for every
sync event you assess. Compute overall_score as the average of the axis scores.
List desync moments, missing/incorrect foley, and lip-sync drift in critical_flaws.

--- Target Prompt ---
{prompt}

--- Verified Video Metadata (ground truth — DO NOT hallucinate duration/fps) ---
{meta_str}
"""

    contents.append(eval_instruction)

    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=AudioVisualSyncReport,
        temperature=0.1,
        thinking_config=types.ThinkingConfig(thinking_level="HIGH"),
    )

    try:
        response = generate_content_with_retry(client, EVAL_MODEL, contents, config)
        return json.loads(response.text)
    except Exception as e:
        print(f"[run_audiovisual_evaluation] evaluation failed: {e}")
        return None
