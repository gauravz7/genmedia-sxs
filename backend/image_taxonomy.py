"""Controlled vocabulary for image-eval categories (max 30).

The first 15 are the canonical buckets requested by the user (verbatim); the
remaining 15 are subcategories / domains that the first 15 don't cover well, so
that real eval content (storyboards, game concept art, product shots, character
sheets, etc.) lands in a meaningful bucket instead of a generic one.

`classify_image_categories(prompt, mode)` maps a prompt to 1-3 labels chosen
STRICTLY from IMAGE_TAXONOMY (gemini-2.5-flash via Vertex). Used both to re-tag
existing image_jobs and to tag future ones, replacing the old free-form tags.
The display order in the UI follows this list order.
"""
from __future__ import annotations
from typing import List, Optional

# --- the 30-category controlled vocabulary (order = UI display order) --------
IMAGE_TAXONOMY: List[str] = [
    # 15 canonical buckets (verbatim)
    "Anime",
    "Cartoon & Illustration",
    "Traditional Art",
    "General & Photorealistic",
    "Nature & Landscapes",
    "People: Portraits",
    "People: Groups & Activities",
    "Physical Spaces",
    "Vintage & Retro",
    "Futuristic & Sci-Fi",
    "Fantasy & Mythical",
    "Graphic Design & Digital Rendering",
    "Text & Typography",
    "UI/UX Design",
    "Commercial",
    # 15 added subcategories / uncovered domains
    "Comics & Manga",
    "3D Render & CGI",
    "Storyboard & Concept Art",
    "Character Design",
    "Gaming & Game Art",
    "Product & Packaging",
    "Food & Beverage",
    "Fashion & Apparel",
    "Automotive & Vehicles",
    "Animals & Wildlife",
    "Architecture & Interiors",
    "Logos & Branding",
    "Infographics & Diagrams",
    "Abstract & Patterns",
    "Macro & Close-up",
]

TAXONOMY_SET = set(IMAGE_TAXONOMY)
_ORDER = {c: i for i, c in enumerate(IMAGE_TAXONOMY)}


def order_key(tag: str) -> int:
    """Sort key so UI lists taxonomy tags in canonical order (unknown -> end)."""
    return _ORDER.get(tag, len(IMAGE_TAXONOMY))


def _fallback(prompt: str) -> List[str]:
    """Cheap keyword fallback if the LLM call fails."""
    p = (prompt or "").lower()
    out: List[str] = []
    def add(t):
        if t not in out:
            out.append(t)
    if "storyboard" in p or "panel" in p or "pre-visualization" in p:
        add("Storyboard & Concept Art")
    if "anime" in p:
        add("Anime")
    if any(w in p for w in ("logo", "typography", "text", "font", "label", "poster")):
        add("Text & Typography")
    if any(w in p for w in ("product", "packaging", "bottle", "can ", "box", "headphone")):
        add("Product & Packaging")
    if any(w in p for w in ("character", "reference sheet", "mascot")):
        add("Character Design")
    if any(w in p for w in ("game", "绝区零", "zenless", "dungeon", "proxy")):
        add("Gaming & Game Art")
    if any(w in p for w in ("photoreal", "photograph", "realistic", "cinematic")):
        add("General & Photorealistic")
    return out[:3] or ["General & Photorealistic"]


async def classify_image_categories(prompt: str, mode: Optional[str] = None) -> List[str]:
    """Return 1-3 labels strictly from IMAGE_TAXONOMY for the given prompt."""
    try:
        import google.auth
        from google import genai
        import os
        project = os.getenv("GCP_PROJECT_ID", "vital-octagon-19612")
        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        client = genai.Client(vertexai=True, project=project, location="us-central1", credentials=creds)
        vocab = ", ".join(IMAGE_TAXONOMY)
        instruction = (
            "You are an image-category tagger. Choose 1 to 3 categories that best "
            "describe the image this prompt would produce. Pick STRICTLY from this "
            f"list, copying labels exactly:\n{vocab}\n\n"
            "Rules:\n"
            "- Output ONLY the chosen labels, comma-separated, nothing else.\n"
            "- 1-3 labels, most specific first.\n"
            "- Use the exact spelling/casing from the list.\n"
            f"{'- This is an image-EDIT (i2i) task.' if mode == 'i2i' else ''}\n\n"
            f"Prompt: {prompt[:2000]}"
        )
        resp = client.models.generate_content(model="gemini-2.5-flash", contents=[instruction])
        text = (getattr(resp, "text", "") or "").strip()
        raw = [t.strip() for t in text.replace("\n", ",").split(",") if t.strip()]
        valid = [t for t in raw if t in TAXONOMY_SET]
        # light fuzzy recovery for near-misses
        if len(valid) < 1:
            low = {c.lower(): c for c in IMAGE_TAXONOMY}
            for r in raw:
                if r.lower() in low and low[r.lower()] not in valid:
                    valid.append(low[r.lower()])
        valid = list(dict.fromkeys(valid))[:3]
        return valid or _fallback(prompt)
    except Exception as e:  # pragma: no cover
        print(f"[image_taxonomy] classify failed: {e}")
        return _fallback(prompt)
