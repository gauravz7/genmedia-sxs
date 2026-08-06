"""Provider registry + interface + normalization tests (no network).

The real ``_call`` (network/SDK) is stubbed; we exercise registration, the
runtime-checkable ``Provider`` interface, and ``GenerationResult`` normalization
(latency in SECONDS, status handling).
"""
from __future__ import annotations

import pytest

from app.domain.models import Case, ExecStatus, Modality, ModelSpec
from app.providers import bootstrap
from app.providers.base import Provider, get_provider, registered_providers

bootstrap()

EXPECTED_PROVIDER_IDS = [
    "elevenlabs",
    "fal",
    "gemini",
    "gemini_tts",
    "gpt",
    "mai",
    "omni",
    "vertex",
]


def test_all_expected_providers_registered() -> None:
    registered = set(registered_providers())
    assert set(EXPECTED_PROVIDER_IDS) <= registered


@pytest.mark.parametrize("provider_id", EXPECTED_PROVIDER_IDS)
def test_provider_interface(provider_id: str) -> None:
    provider = get_provider(provider_id)
    assert isinstance(provider, Provider)
    assert provider.provider_id == provider_id
    assert hasattr(provider, "generate")


def test_unknown_provider_raises() -> None:
    with pytest.raises(KeyError):
        get_provider("does-not-exist")


@pytest.mark.asyncio
async def test_generate_normalizes_success(sample_case: Case) -> None:
    provider = get_provider("fal")

    async def fake_call(case: Case, spec: ModelSpec, params: dict) -> dict:
        return {"media_uri": "https://fal.example/vid.mp4", "duration": 8.0,
                "raw": {"original_url": "https://fal.example/vid.mp4"}}

    provider._call = fake_call  # type: ignore[attr-defined]
    spec = ModelSpec(id="seedance", provider="fal",
                     model_id="fal-ai/bytedance/seedance/v1.5/pro/text-to-video", type="t2v")

    result = await provider.generate(sample_case, spec)

    assert result.status == ExecStatus.SUCCESS
    assert result.media_uri == "https://fal.example/vid.mp4"
    assert result.model_id == spec.model_id
    assert result.duration == 8.0
    # Latency must be in SECONDS (a stubbed call completes in well under a second).
    assert result.latency_s is not None
    assert 0.0 <= result.latency_s < 5.0
    assert result.raw["original_url"] == "https://fal.example/vid.mp4"


@pytest.mark.asyncio
async def test_generate_bytes_provider_success() -> None:
    provider = get_provider("gemini_tts")

    async def fake_call(case: Case, spec: ModelSpec, params: dict) -> dict:
        return {"media_uri": "gs://project-pulse/audio/tts.wav", "raw": {"voice": "Kore"}}

    provider._call = fake_call  # type: ignore[attr-defined]
    case = Case(id="c-tts", prompt="Hello world", modality=Modality.TTS)
    spec = ModelSpec(id="gemini-tts", provider="gemini_tts",
                     model_id="gemini-2.5-flash-preview-tts", type="tts")

    result = await provider.generate(case, spec)

    assert result.status == ExecStatus.SUCCESS
    assert result.media_uri.startswith("gs://")
    assert result.latency_s is not None and result.latency_s >= 0.0


@pytest.mark.asyncio
async def test_generate_error_path_on_exception(sample_case: Case) -> None:
    provider = get_provider("vertex")

    async def boom(case: Case, spec: ModelSpec, params: dict) -> dict:
        raise RuntimeError("vertex 503 high load")

    provider._call = boom  # type: ignore[attr-defined]
    spec = ModelSpec(id="veo", provider="vertex",
                     model_id="veo-3.1-generate-001", type="t2v")

    result = await provider.generate(sample_case, spec)

    assert result.status == ExecStatus.ERROR
    assert result.media_uri is None
    assert "high load" in (result.error or "")
    assert result.latency_s is not None


@pytest.mark.asyncio
async def test_generate_error_path_on_no_media(sample_case: Case) -> None:
    provider = get_provider("gpt")

    async def empty(case: Case, spec: ModelSpec, params: dict) -> dict:
        return {"media_uri": None, "error": "no image url", "raw": {}}

    provider._call = empty  # type: ignore[attr-defined]
    spec = ModelSpec(id="gpt-image", provider="gpt", model_id="openai/gpt-image-2", type="t2i")

    result = await provider.generate(sample_case, spec)

    assert result.status == ExecStatus.ERROR
    assert result.error == "no image url"
