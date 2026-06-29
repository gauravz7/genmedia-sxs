"""Standalone smoke test for the Image SxS providers.

Generates ONE T2I image via a Gemini image model and ONE via GPT-image (FAL),
printing the resulting GCS URLs (or the real error if a model id is unavailable).

Run from the backend/ dir with system python3:

    python3 test_image_providers.py
"""

import asyncio

from providers.gemini_image_provider import generate_gemini_image
from providers.gpt_image_provider import generate_gpt_image

PROMPT = "A cozy ramen shop at night, neon signs, rain, cinematic, highly detailed"


async def main():
    print("=== Image provider smoke test ===\n")

    # --- Gemini T2I (try flash first, then instant-ramen as a secondary probe) -
    for model in ["gemini-3.1-flash-image", "instant-ramen"]:
        print(f"[Gemini] generating T2I on {model} ...")
        res = await generate_gemini_image(model=model, prompt=PROMPT, case_id="smoke")
        if res.get("status") == "success":
            print(f"  OK  {model}: {res.get('url')}  ({res.get('latency_ms')} ms)")
        else:
            print(f"  ERR {model}: {res.get('error')}")
        print()

    # --- GPT-image T2I via FAL (medium tier) ---------------------------------
    print("[GPT-image] generating T2I via FAL (medium) ...")
    res = await generate_gpt_image(prompt=PROMPT, quality="medium", case_id="smoke")
    if res.get("status") == "success":
        print(f"  OK  gpt-image-1 (medium): {res.get('url')}  ({res.get('latency_ms')} ms)")
    else:
        print(f"  ERR gpt-image-1 (medium): {res.get('error')}")
    print("\n=== done ===")


if __name__ == "__main__":
    asyncio.run(main())
