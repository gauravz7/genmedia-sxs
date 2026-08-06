"""The model-name gate: `resolve_models` is what turns "run it if the model is
registered" into an enforceable contract, so its rejections matter as much as
its acceptances."""

import pytest
from fastapi import HTTPException

import model_resolver
from conftest import IMAGE_MODELS, TTS_MODELS


def _problems(exc_info):
    detail = exc_info.value.detail
    return detail["problems"] if isinstance(detail, dict) else [str(detail)]


# --- accepts -----------------------------------------------------------------

def test_resolves_a_registered_image_pair():
    specs = model_resolver.resolve_models("image", IMAGE_MODELS)
    assert [s.id for s in specs] == IMAGE_MODELS


def test_resolves_a_registered_tts_pair():
    specs = model_resolver.resolve_models("tts", TTS_MODELS)
    assert [s.id for s in specs] == TTS_MODELS


def test_video_accepts_a_single_model(video_models):
    """Video duels are N-way, so 1 model is legal (unlike image/tts)."""
    specs = model_resolver.resolve_models("video", video_models[:1])
    assert len(specs) == 1


def test_video_accepts_more_than_two(registry):
    ids = [m["id"] for m in model_resolver.list_models("video") if m["type"] == "t2v"]
    if len(ids) < 3:
        pytest.skip("registry has fewer than 3 active t2v models")
    assert len(model_resolver.resolve_models("video", ids[:3])) == 3


# --- rejects -----------------------------------------------------------------

def test_unknown_model_is_rejected_by_name():
    with pytest.raises(HTTPException) as e:
        model_resolver.resolve_models("image", ["ghost-model", IMAGE_MODELS[0]])
    assert e.value.status_code == 400
    assert "'ghost-model' is not a registered model" in _problems(e)


def test_every_problem_is_reported_at_once():
    """A caller fixing a batch should see all the bad names in one response,
    not discover them one request at a time."""
    with pytest.raises(HTTPException) as e:
        model_resolver.resolve_models("image", ["ghost-a", "ghost-b"])
    assert len(_problems(e)) == 2


def test_rejection_lists_what_is_available():
    with pytest.raises(HTTPException) as e:
        model_resolver.resolve_models("tts", ["ghost", TTS_MODELS[0]])
    assert set(TTS_MODELS) <= set(e.value.detail["available"])


def test_inactive_model_is_rejected(registry, monkeypatch):
    spec = registry.models[IMAGE_MODELS[0]]
    monkeypatch.setattr(spec, "is_active", False)
    with pytest.raises(HTTPException) as e:
        model_resolver.resolve_models("image", IMAGE_MODELS)
    assert "registered but not active" in _problems(e)[0]


def test_wrong_modality_is_rejected():
    """An image model named on a TTS request is a config error worth catching —
    it would otherwise create a job that can never produce audio."""
    with pytest.raises(HTTPException) as e:
        model_resolver.resolve_models("tts", [IMAGE_MODELS[0], TTS_MODELS[0]])
    assert "is a image model, not tts" in _problems(e)[0]


def test_video_model_rejected_on_image_request(video_models):
    with pytest.raises(HTTPException) as e:
        model_resolver.resolve_models("image", video_models)
    assert "not image" in _problems(e)[0]


@pytest.mark.parametrize("names", [[IMAGE_MODELS[0]], IMAGE_MODELS + ["gpt-image-2-low"]])
def test_image_requires_exactly_two(names):
    with pytest.raises(HTTPException) as e:
        model_resolver.resolve_models("image", names)
    assert "two-sided" in str(e.value.detail)


@pytest.mark.parametrize("names", [[TTS_MODELS[0]], TTS_MODELS + [TTS_MODELS[0]]])
def test_tts_requires_exactly_two(names):
    with pytest.raises(HTTPException):
        model_resolver.resolve_models("tts", names)


def test_duplicate_models_are_rejected(video_models):
    with pytest.raises(HTTPException) as e:
        model_resolver.resolve_models("video", [video_models[0], video_models[0]])
    assert "Duplicate" in str(e.value.detail)


def test_empty_model_list_is_rejected():
    with pytest.raises(HTTPException) as e:
        model_resolver.resolve_models("image", [])
    assert e.value.status_code == 400


def test_blank_model_name_is_rejected():
    with pytest.raises(HTTPException) as e:
        model_resolver.resolve_models("image", ["  ", IMAGE_MODELS[0]])
    assert "(empty model name)" in _problems(e)


# --- video type matching -----------------------------------------------------

def test_require_video_type_accepts_matching(video_models):
    specs = model_resolver.resolve_models("video", video_models)
    model_resolver.require_video_type(specs, "t2v")  # no raise


def test_require_video_type_rejects_mismatch(video_models):
    """A t2v model on an i2v case would silently ignore the reference image."""
    specs = model_resolver.resolve_models("video", video_models)
    with pytest.raises(HTTPException) as e:
        model_resolver.require_video_type(specs, "i2v")
    assert "Case is 'i2v'" in str(e.value.detail)


# --- translation to pipeline shapes -----------------------------------------

def test_image_side_carries_engine_provider_model_quality():
    spec = model_resolver.resolve_models("image", IMAGE_MODELS)[1]  # gpt-image-2-high
    side = model_resolver.image_side_from_spec(spec)
    assert side == {"engine": "gpt-image-2-high", "provider": "gpt",
                    "model": spec.model_id, "quality": "high"}


def test_image_side_engine_equals_registry_id():
    """`engine` is the identity written into side_map and analytics; if it ever
    diverges from the registry id, historical jobs stop resolving."""
    for spec in model_resolver.resolve_models("image", IMAGE_MODELS):
        assert model_resolver.image_side_from_spec(spec)["engine"] == spec.id


def test_tts_engines_are_registry_ids():
    specs = model_resolver.resolve_models("tts", TTS_MODELS)
    assert model_resolver.tts_engines_from_specs(specs) == TTS_MODELS


# --- registry view -----------------------------------------------------------

def test_modality_partition_is_total():
    """Every active model must map to exactly one intake modality — an entry
    with an unrecognized `type` would be invisible to all six endpoints."""
    listed = model_resolver.list_models(active_only=True)
    assert listed and all(m["modality"] in ("video", "image", "tts") for m in listed)


def test_list_models_scopes_by_modality():
    for modality in ("video", "image", "tts"):
        assert all(m["modality"] == modality
                   for m in model_resolver.list_models(modality))


def test_transport_follows_the_google_vs_fal_rule():
    """Google models on Vertex, everything else through FAL."""
    import main
    for m in model_resolver.list_models(active_only=False):
        assert m["transport"] == main.PROVIDER_TRANSPORT[m["provider"]]
        assert m["transport"] in ("vertex", "fal")


def test_active_only_filters_deactivated(registry, monkeypatch):
    spec = registry.models[IMAGE_MODELS[0]]
    monkeypatch.setattr(spec, "is_active", False)
    assert IMAGE_MODELS[0] not in [m["id"] for m in model_resolver.list_models("image")]
    assert IMAGE_MODELS[0] in [
        m["id"] for m in model_resolver.list_models("image", active_only=False)
    ]
