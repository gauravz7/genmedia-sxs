"""Unit tests for the PURE evaluator prompt-builders and response-parsers."""
from __future__ import annotations

from app.domain.models import Case, Execution, Modality
from app.evaluators import core5, director
from app.evaluators import image as image_eval
from app.evaluators import tts as tts_eval


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _video_exec() -> Execution:
    return Execution(
        id="exec_v", case_id="c1", model_id="veo", modality=Modality.T2V,
        prompt="A red fox leaps over a snowdrift",
    )


def _image_exec(mode: str = "t2i") -> Execution:
    return Execution(
        id="exec_i", case_id="c1", model_id="imagen", prompt="A red fox in snow",
        modality=Modality.I2I if mode == "i2i" else Modality.T2I, mode=mode,
    )


def _tts_exec() -> Execution:
    return Execution(
        id="exec_t", case_id="c1", model_id="eleven", modality=Modality.TTS,
        prompt="Hello there, welcome aboard.",
        params={"style_prompt": "warm and cheerful"},
    )


# --------------------------------------------------------------------------
# Core-5 (video absolute)
# --------------------------------------------------------------------------
def test_core5_prompt_includes_rubric_terms():
    p = core5.build_absolute_prompt(_video_exec())
    for term in core5.CORE5_DIMENSIONS:
        assert term in p
    assert "CRITICAL AUDITING PROTOCOL" in p
    assert "A red fox leaps over a snowdrift" in p
    assert core5.CORE5_DIMENSIONS == [
        "prompt_adherence", "visual_quality", "motion_physics",
        "temporal_consistency", "audio_visual_sync",
    ]


def test_core5_parse_computes_mean_of_five():
    raw = {
        "prompt_adherence": {"score": 5, "explanation": "spot on"},
        "visual_quality": {"score": 4, "explanation": "sharp"},
        "motion_physics": {"score": 3, "explanation": "some float"},
        "temporal_consistency": {"score": 2, "explanation": "flicker"},
        "audio_visual_sync": {"score": 1, "explanation": "desync"},
        "critical_flaws": ["desync at 0:03"],
    }
    out = core5.parse_absolute(raw)
    assert out["overall_score"] == 3.0  # mean(5,4,3,2,1)
    assert out["prompt_adherence"]["score"] == 5.0
    assert out["critical_flaws"] == ["desync at 0:03"]


def test_core5_parse_robust_to_missing_field():
    raw = {
        "prompt_adherence": {"score": 4},
        "visual_quality": {"score": 4},
        # motion_physics missing
        "temporal_consistency": {"score": 4},
        "audio_visual_sync": {"score": 4},
    }
    out = core5.parse_absolute(raw)
    assert out["motion_physics"]["score"] is None
    assert out["overall_score"] == 4.0  # mean over the four present
    # fully empty response does not crash
    empty = core5.parse_absolute({})
    assert empty["overall_score"] == 0.0
    assert core5.parse_absolute(None)["overall_score"] == 0.0


# --------------------------------------------------------------------------
# Director (video pairwise)
# --------------------------------------------------------------------------
def test_director_prompt_and_parse():
    case = Case(id="c1", prompt="A red fox leaps", modality=Modality.T2V)
    p = director.build_pairwise_prompt(case, _video_exec(), _video_exec())
    assert "Creative Video Director" in p
    assert "Plastic Skin" in p
    assert "A red fox leaps" in p

    assert director.parse_pairwise({"verdict": "A", "reasoning": "A sharper"})["winner"] == "A"
    assert director.parse_pairwise({"verdict": "b"})["winner"] == "B"
    tie = director.parse_pairwise({"verdict": "tie"})
    assert tie["winner"] is None
    assert director.parse_pairwise({})["winner"] is None


# --------------------------------------------------------------------------
# Image
# --------------------------------------------------------------------------
def test_image_prompt_edit_fidelity_only_for_i2i():
    t2i = image_eval.build_absolute_prompt(_image_exec("t2i"))
    i2i = image_eval.build_absolute_prompt(_image_exec("i2i"))
    for term in image_eval.IMAGE_BASE_METRICS:
        assert term in t2i and term in i2i
    assert "edit_fidelity" not in t2i
    assert "edit_fidelity" in i2i


def test_image_parse_absolute_mean_and_robustness():
    out = image_eval.parse_absolute(
        {"prompt_following": 4, "aesthetic": 5, "detail": 3, "artifact_free": 4}
    )
    assert out["overall_score"] == 4.0
    assert "edit_fidelity" not in out
    # i2i includes edit_fidelity
    i2i = image_eval.parse_absolute(
        {"prompt_following": 4, "aesthetic": 4, "detail": 4,
         "artifact_free": 4, "edit_fidelity": 2}
    )
    assert i2i["edit_fidelity"] == 2
    assert i2i["overall_score"] == 3.6
    # missing / garbage fields drop gracefully
    partial = image_eval.parse_absolute({"prompt_following": 5, "aesthetic": "nope"})
    assert partial["overall_score"] == 5.0
    assert image_eval.parse_absolute({})["overall_score"] == 0.0


def test_image_parse_pairwise():
    parsed = image_eval.parse_pairwise(
        {"A": {"prompt_following": 5, "aesthetic": 5, "detail": 5, "artifact_free": 5},
         "B": {"prompt_following": 2, "aesthetic": 2, "detail": 2, "artifact_free": 2},
         "winner": "A", "justification": "A cleaner"}
    )
    assert parsed["winner"] == "A"
    assert parsed["sides"]["A"]["overall_score"] == 5.0
    assert parsed["sides"]["B"]["overall_score"] == 2.0


# --------------------------------------------------------------------------
# TTS
# --------------------------------------------------------------------------
def test_tts_prompt_includes_rubric_and_style():
    p = tts_eval.build_absolute_prompt(_tts_exec())
    for term in tts_eval.TTS_METRICS:
        assert term in p
    assert "warm and cheerful" in p
    assert "Hello there, welcome aboard." in p


def test_tts_parse_absolute_mean_and_robustness():
    out = tts_eval.parse_absolute(
        {"naturalness": 5, "style_adherence": 4, "expressiveness": 3,
         "pacing": 4, "pronunciation_clarity": 4}
    )
    assert out["overall_score"] == 4.0
    partial = tts_eval.parse_absolute({"naturalness": 4})
    assert partial["overall_score"] == 4.0
    assert tts_eval.parse_absolute({})["overall_score"] == 0.0
