"""One-time setup: add popular NATIVE ElevenLabs voices per language to the
account, so the TTS provider can pick a native voice by language.

Why: ElevenLabs voice-library voices must be ADDED to your workspace before they
can be used for synthesis (an un-added voice_id returns 401 needs_authorization).
This script lists the top shared voice per language and adds it, then prints a
ready-to-paste LANG_VOICE map for providers/elevenlabs_provider.py.

Run when the key is healthy (not rate-limited) and has voice-library scope:
    cd backend && python3 setup_elevenlabs_voices.py
"""

import json
import os
import time

import requests
from dotenv import load_dotenv

load_dotenv()
KEY = os.getenv("ELEVENLABS_API_KEY", "")
H = {"xi-api-key": KEY}

# Requested + popular Asian/Indic languages (BCP-47 base codes).
LANGS = ["hi", "ta", "te", "zh", "ja", "ko", "id", "vi", "th", "bn", "ml", "kn", "mr", "ur", "pa", "es", "fr", "de", "ar", "pt"]


def main():
    if not KEY:
        raise SystemExit("ELEVENLABS_API_KEY not set")
    result = {}
    for lang in LANGS:
        time.sleep(1.5)  # be gentle — bursts trip rate limiting (401s)
        try:
            s = requests.get(
                f"https://api.elevenlabs.io/v1/shared-voices?language={lang}&page_size=6",
                headers=H, timeout=60,
            )
        except Exception as e:
            print(f"{lang}: list error {e}"); continue
        if s.status_code != 200:
            print(f"{lang}: list HTTP {s.status_code} {s.text[:80]}"); continue
        voices = s.json().get("voices", [])
        if lang == "zh":  # prefer Mandarin over Cantonese
            voices = [v for v in voices if "cantonese" not in (v.get("accent") or "").lower()] or voices
        if not voices:
            print(f"{lang}: no shared voices"); continue
        top = voices[0]
        owner, vid = top.get("public_owner_id"), top.get("voice_id")
        name = (top.get("name") or "").split(" - ")[0].strip()
        time.sleep(1.0)
        a = requests.post(
            f"https://api.elevenlabs.io/v1/voices/add/{owner}/{vid}",
            headers={**H, "Content-Type": "application/json"},
            json={"new_name": f"{lang}-{name}"[:40]}, timeout=60,
        )
        if a.status_code == 200:
            new_vid = a.json().get("voice_id", vid)
            result[lang] = new_vid
            print(f"{lang}: ADDED {new_vid}  ({name})")
        elif a.status_code in (400, 409) and "already" in a.text.lower():
            result[lang] = vid
            print(f"{lang}: already present {vid} ({name})")
        else:
            print(f"{lang}: add HTTP {a.status_code} {a.text[:100]}")

    print("\n# Paste into providers/elevenlabs_provider.py LANG_VOICE:")
    print("LANG_VOICE = " + json.dumps(result, ensure_ascii=False, indent=4))


if __name__ == "__main__":
    main()
