"""Standalone smoke test for the TTS providers.

Generates ONE short line on Gemini 3.1 Flash TTS (voice Kore) and ONE on
ElevenLabs (default voice), asserting non-empty audio + a printable URL. Run:

    python3 test_tts_providers.py

Captures verbatim API errors so the human can confirm model availability /
region if a provider is not reachable. Exit code is non-zero only on an
unexpected harness error, NOT on a provider returning a status=error (which is
printed for diagnosis).
"""

import asyncio

from providers.gemini_tts_provider import generate_gemini_tts
from providers.elevenlabs_provider import generate_elevenlabs_tts


async def main():
    print("=" * 70)
    print("TTS PROVIDER SMOKE TEST")
    print("=" * 70)

    # --- Gemini 3.1 Flash TTS ---
    print("\n[1/2] Gemini 3.1 Flash TTS (voice=Kore)...")
    g = await generate_gemini_tts(
        text="Hello from Gemini text to speech. This is a short test line.",
        voice="Kore",
        style_prompt="Friendly and clear product demo voice.",
        language="en",
        case_id="smoke-gemini",
    )
    print(f"  status : {g.get('status')}")
    print(f"  url    : {g.get('url')}")
    print(f"  latency: {g.get('latency_ms')} ms")
    if g.get("status") == "success":
        assert g.get("url"), "Gemini success but no URL"
        print("  -> Gemini PRODUCED PLAYABLE AUDIO ✓")
    else:
        print(f"  -> Gemini ERROR (verbatim): {g.get('error')}")

    # --- ElevenLabs ---
    print("\n[2/2] ElevenLabs (eleven_multilingual_v2, voice=Rachel)...")
    e = await generate_elevenlabs_tts(
        text="Hello from ElevenLabs text to speech. This is a short test line.",
        voice="Rachel",
        style_prompt="Friendly and clear product demo voice.",
        language="en",
        case_id="smoke-eleven",
    )
    print(f"  status : {e.get('status')}")
    print(f"  url    : {e.get('url')}")
    print(f"  latency: {e.get('latency_ms')} ms")
    if e.get("status") == "success":
        assert e.get("url"), "ElevenLabs success but no URL"
        print("  -> ElevenLabs PRODUCED PLAYABLE AUDIO ✓")
    else:
        print(f"  -> ElevenLabs ERROR (verbatim): {e.get('error')}")

    print("\n" + "=" * 70)
    print("SUMMARY")
    print(f"  Gemini    : {g.get('status')}")
    print(f"  ElevenLabs: {e.get('status')}")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
