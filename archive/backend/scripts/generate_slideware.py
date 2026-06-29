#!/usr/bin/env python3
"""
Generate an HTML slideware presentation comparing Pro vs Fast model tiers.
Google Material Design dark theme with sidebar navigation.
Uses direct GCS bucket URLs — skips entries where generation didn't happen.
"""

import os
import sys
import html
import urllib.parse
from google.cloud import firestore
from dotenv import load_dotenv

load_dotenv()

GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID", "vital-octagon-19612")
GCS_BUCKET_NAME = os.getenv("GCS_BUCKET_NAME", "project-pulse")

# ── Google Material palette (from generate_google_slides.py) ─────────
# Surfaces
BG        = "#1a1a1c"
BG_CARD   = "#26262b"
BG_SURFACE = "#36363d"
TEXT1     = "#f2f2f5"
TEXT2     = "#9e9ea8"
TEXT3     = "#737380"
TAG_BG    = "#333340"
# Google 4-colour
G_BLUE   = "#4285F4"
G_RED    = "#EA4335"
G_YELLOW = "#FBBC04"
G_GREEN  = "#34A853"
# Tier accents
PRO_COLOR  = "#8C5CF7"
FAST_COLOR = "#00BD8C"

# ── Model tier classification ────────────────────────────────────────
PRO_PREFIXES = [
    "veo-3-1-001",
    "seedance-2-0-t2v", "seedance-2-0-i2v", "seedance-1-5",
    "kling-3-pro", "kling-3-standard", "kling-o3-pro",
]
FAST_PREFIXES = [
    "veo-3-1-fast-001", "veo-3-1-lite-001",
    "seedance-2-0-fast", "seedance-1-fast",
    "kling-2-5", "kling-2-6", "kling-o3-standard",
    "grok-imagine",
]

FAMILY_COLORS = {
    "veo":      G_BLUE,
    "seedance": G_GREEN,
    "kling":    G_RED,
    "grok":     G_YELLOW,
}


def classify_model(model_key):
    k = model_key.lower()
    for p in PRO_PREFIXES:
        if k.startswith(p):
            return "pro"
    for p in FAST_PREFIXES:
        if k.startswith(p):
            return "fast"
    return None


def get_family_color(model_key):
    k = model_key.lower()
    for fam, color in FAMILY_COLORS.items():
        if fam in k:
            return color
    return "#9AA0A6"


def pretty_name(model_key):
    n = model_key.replace("-", " ")
    n = n.replace("t2v", "(T2V)").replace("i2v", "(I2V)").replace("r2v", "(R2V)")
    return " ".join(
        w.capitalize() if w not in ("(T2V)", "(I2V)", "(R2V)") else w
        for w in n.split()
    )


def to_media_url(url):
    """Convert any GCS URL to a /api/media proxy URL (GCS bucket is private)."""
    if not url:
        return ""
    # Unwrap existing proxy URLs
    if "/api/media?url=" in url:
        url = urllib.parse.unquote(url.split("/api/media?url=")[-1])
    # Already a non-GCS http URL — pass through
    if url.startswith("http") and "storage.googleapis.com" not in url:
        return url
    # GCS URL — proxy through backend
    encoded = urllib.parse.quote(url, safe="")
    return f"/api/media?url={encoded}"


def make_image_url(url):
    return to_media_url(url)


def get_video_url(result):
    if result.get("status") != "success":
        return ""
    raw = result.get("url") or (result.get("result") or {}).get("url", "")
    return to_media_url(raw)


# ── Firestore ────────────────────────────────────────────────────────

def fetch_jobs(limit=None):
    db = firestore.Client(project=GCP_PROJECT_ID)
    query = db.collection("eval_jobs").order_by("timestamp", direction=firestore.Query.DESCENDING)
    if limit:
        query = query.limit(limit)
    docs = query.stream()
    return [{**doc.to_dict(), "_id": doc.id} for doc in docs]


# ── Page builder (one page per batch) ────────────────────────────────

def build_batch_page(batch_name, prompt_text, categories, images, gen_type, pro_models, fast_models):
    batch_esc = html.escape(batch_name)
    prompt_escaped = html.escape(prompt_text or "No prompt")

    # Tags
    tags_html = ""
    if categories:
        chips = "".join(f'<span class="tag">{html.escape(c)}</span>' for c in categories)
        tags_html = f'<div class="tags">{chips}</div>'

    # Input images
    images_html = ""
    img_items = []
    if images.get("start_image_url"):
        img_items.append(("Start Frame", images["start_image_url"]))
    if images.get("end_image_url"):
        img_items.append(("End Frame", images["end_image_url"]))
    if images.get("reference_image_url"):
        img_items.append(("Reference", images["reference_image_url"]))
    for i, ref in enumerate(images.get("reference_images") or []):
        if ref:
            img_items.append((f"Ref {i+1}", ref))

    if img_items:
        imgs = ""
        for label, url in img_items:
            abs_url = make_image_url(url)
            if abs_url:
                imgs += f'''
                <div class="input-image">
                    <img src="{abs_url}" alt="{html.escape(label)}" loading="lazy" />
                    <div class="input-label">{html.escape(label)}</div>
                </div>'''
        if imgs:
            images_html = f'<div class="input-images">{imgs}</div>'

    # Build tier sections
    def build_tier_section(tier, tier_label, accent, models_data):
        successful = {}
        for mk, result in sorted(models_data.items()):
            video_url = get_video_url(result)
            if video_url:
                successful[mk] = (result, video_url)
        if not successful:
            return ""

        grid_cols = min(len(successful), 4)
        cards_html = ""
        for mk, (result, video_url) in successful.items():
            fg = get_family_color(mk)
            display = pretty_name(mk)
            latency = result.get("latency")
            latency_str = f"{latency:.0f}s" if latency else ""
            mk_escaped = html.escape(mk)
            cards_html += f'''
                <div class="video-card" data-model="{mk_escaped}">
                    <div class="accent-bar" style="background:{fg}"></div>
                    <div class="card-header">
                        <div class="card-info">
                            <span class="model-name">{html.escape(display)}</span>
                            {"<span class='latency'>" + latency_str + "</span>" if latency_str else ""}
                        </div>
                        <button class="pick-btn" title="Pick as best"
                                onclick="pickBest(this,'{batch_esc}','{tier}','{mk_escaped}')">&#9734;</button>
                    </div>
                    <video controls preload="metadata" muted>
                        <source src="{video_url}" type="video/mp4" />
                    </video>
                </div>'''

        feedback_key = f"{batch_name}__{tier}"
        return f'''
            <div class="tier-section" data-tier="{tier}" data-batch="{batch_esc}">
                <div class="tier-header">
                    <div class="tier-badge" style="--accent:{accent}">{tier_label}</div>
                    <button class="play-all-btn" onclick="playAllInSection(this)">
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>
                        Play All
                    </button>
                </div>
                <div class="comment-section" data-key="{html.escape(feedback_key)}">
                    <div class="comment-input-row">
                        <input type="text" class="comment-input" placeholder="Add a comment..."
                               onkeydown="if(event.key==='Enter')addComment(this,'{batch_esc}','{tier}')" />
                        <button class="comment-btn" onclick="addComment(this.previousElementSibling,'{batch_esc}','{tier}')">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>
                        </button>
                    </div>
                    <div class="comments-list" id="comments-{html.escape(feedback_key)}"></div>
                </div>
                <div class="video-grid cols-{grid_cols}">{cards_html}</div>
            </div>'''

    pro_section = build_tier_section("pro", "Pro Tier", PRO_COLOR, pro_models)
    fast_section = build_tier_section("fast", "Fast Tier", FAST_COLOR, fast_models)

    return f'''
        <div class="slide" data-batch="{batch_esc}">
            <div class="slide-header">
                <div class="batch-name">{batch_esc}</div>
                <div class="type-badge">{html.escape(gen_type)}</div>
            </div>
            <div class="divider" style="background:linear-gradient(90deg,{G_BLUE},{G_RED},{G_YELLOW},{G_GREEN})"></div>
            <div class="prompt-box">{prompt_escaped}</div>
            {tags_html}
            {images_html}
            {pro_section}
            {fast_section}
        </div>'''


# ── Main generation ──────────────────────────────────────────────────

def generate_presentation(jobs, output_path="slideware.html", single_batch=None):
    slides = []
    sidebar_items = []  # (batch_name, slide_index, gen_type)

    for job in jobs:
        batch_name = job.get("prompt_id") or job.get("_id", "unknown")
        if single_batch and batch_name != single_batch:
            continue

        results = job.get("results", {})
        prompt_text = job.get("prompt", "")
        categories = job.get("categories", [])
        images = {
            "start_image_url": job.get("start_image_url"),
            "end_image_url": job.get("end_image_url"),
            "reference_image_url": job.get("reference_image_url"),
            "reference_images": job.get("reference_images"),
        }

        pro = {k: v for k, v in results.items() if classify_model(k) == "pro"}
        fast = {k: v for k, v in results.items() if classify_model(k) == "fast"}

        has_pro = any(get_video_url(v) for v in pro.values())
        has_fast = any(get_video_url(v) for v in fast.values())
        if not has_pro and not has_fast:
            continue

        gen_types = set()
        for mk in list(pro.keys()) + list(fast.keys()):
            if "t2v" in mk:
                gen_types.add("T2V")
            elif "i2v" in mk:
                gen_types.add("I2V")
            elif "r2v" in mk:
                gen_types.add("R2V")
        gen_type = " / ".join(sorted(gen_types)) or "Video"

        sidebar_items.append((batch_name, len(slides), gen_type))

        page = build_batch_page(batch_name, prompt_text, categories, images, gen_type, pro, fast)
        if page:
            slides.append(page)

    if not slides:
        print("No slides generated.")
        return None

    total_slides = len(slides)
    slides_joined = "\n".join(slides)

    # Build sidebar HTML
    sidebar_html = ""
    for batch_name, idx, gen_type in sidebar_items:
        sidebar_html += f'''<button class="sidebar-item" data-slide="{idx}" onclick="showSlide({idx})">
            <span class="sidebar-batch">{html.escape(batch_name)}</span>
            <span class="sidebar-type">{html.escape(gen_type)}</span>
        </button>\n'''

    html_content = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>Project Pulse</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Google+Sans:wght@400;500;700&family=Google+Sans+Text:wght@400;500&display=swap" rel="stylesheet">
<style>
*{{ margin:0; padding:0; box-sizing:border-box; }}
:root {{
    --bg: {BG};
    --bg-card: {BG_CARD};
    --bg-surface: {BG_SURFACE};
    --text1: {TEXT1};
    --text2: {TEXT2};
    --text3: {TEXT3};
    --blue: {G_BLUE};
    --red: {G_RED};
    --yellow: {G_YELLOW};
    --green: {G_GREEN};
    --pro: {PRO_COLOR};
    --fast: {FAST_COLOR};
    --radius: 12px;
    --radius-sm: 8px;
}}
html, body {{ height:100%; overflow:hidden; }}
body {{
    font-family: 'Google Sans Text', 'Google Sans', -apple-system, system-ui, sans-serif;
    background: var(--bg);
    color: var(--text1);
    display: flex; flex-direction: column;
}}

/* ═══ Top bar ═══ */
.topbar {{
    height: 48px; min-height: 48px;
    display: flex; align-items: center; justify-content: space-between;
    padding: 0 20px;
    background: var(--bg);
    border-bottom: 1px solid var(--bg-surface);
    z-index: 10;
}}
.topbar-left {{ display: flex; align-items: center; gap: 14px; }}
.g-dots {{ display: flex; gap: 5px; }}
.g-dot {{ width: 9px; height: 9px; border-radius: 50%; }}
.topbar-title {{
    font-family: 'Google Sans', sans-serif;
    font-size: 15px; font-weight: 500; color: var(--text2);
    letter-spacing: 0.2px;
}}
.topbar-right {{ display: flex; align-items: center; gap: 8px; }}
.nav-btn {{
    background: var(--bg-card); border: 1px solid var(--bg-surface);
    color: var(--text1); padding: 5px 14px; border-radius: 20px;
    cursor: pointer; font-size: 12px; font-weight: 500;
    font-family: 'Google Sans Text', sans-serif;
    transition: all 0.15s;
}}
.nav-btn:hover {{ background: var(--bg-surface); }}
.nav-btn:disabled {{ opacity: 0.3; cursor: default; }}
.slide-counter {{ font-size: 12px; color: var(--text3); min-width: 70px; text-align: center; }}

/* ═══ Layout ═══ */
.main {{ display: flex; flex: 1; min-height: 0; }}

/* ═══ Sidebar ═══ */
.sidebar {{
    width: 220px; min-width: 220px;
    background: var(--bg);
    border-right: 1px solid var(--bg-surface);
    overflow-y: auto; padding: 12px 8px;
}}
.sidebar-label {{
    font-size: 10px; text-transform: uppercase; letter-spacing: 1.2px;
    color: var(--text3); font-weight: 500; padding: 6px 10px 8px;
}}
.sidebar-item {{
    display: flex; align-items: center; justify-content: space-between;
    width: 100%; padding: 8px 10px;
    background: none; border: none; border-radius: var(--radius-sm);
    color: var(--text2); cursor: pointer; font-size: 12px;
    font-family: 'Google Sans Text', sans-serif;
    text-align: left; transition: all 0.12s;
}}
.sidebar-item:hover {{ background: var(--bg-card); color: var(--text1); }}
.sidebar-item.active {{ background: rgba(66,133,244,0.15); color: var(--blue); }}
.sidebar-batch {{ font-weight: 500; }}
.sidebar-type {{
    font-size: 10px; color: var(--text3);
    background: var(--bg-surface); padding: 1px 6px; border-radius: 4px;
}}

/* ═══ Slide area ═══ */
.slides-container {{ flex: 1; overflow: hidden; position: relative; }}
.slide {{
    display: none; position: absolute; inset: 0;
    padding: 24px 36px 24px;
    overflow-y: auto; flex-direction: column; gap: 16px;
}}
.slide.active {{ display: flex; }}

/* ═══ Slide header ═══ */
.slide-header {{
    display: flex; align-items: center; justify-content: space-between;
    flex-shrink: 0;
}}
.batch-name {{
    font-family: 'Google Sans', sans-serif;
    font-size: 22px; font-weight: 700; color: var(--text1);
}}
.type-badge {{
    font-size: 11px; font-weight: 500; padding: 4px 14px;
    border-radius: 20px;
    background: rgba(66,133,244,0.12); color: var(--blue);
    border: 1px solid rgba(66,133,244,0.25);
}}
.tier-badge {{
    font-size: 12px; font-weight: 600; padding: 5px 18px;
    border-radius: 20px;
    background: color-mix(in srgb, var(--accent) 12%, transparent);
    color: var(--accent);
    border: 1px solid color-mix(in srgb, var(--accent) 30%, transparent);
}}
.divider {{
    height: 2px; border-radius: 1px;
    flex-shrink: 0; opacity: 0.8;
}}

/* ═══ Prompt ═══ */
.prompt-box {{
    background: var(--bg-card); border-radius: var(--radius);
    padding: 14px 20px; flex-shrink: 0;
    font-size: 13px; line-height: 1.6; color: var(--text2);
    border: 1px solid var(--bg-surface);
}}
.tags {{ display: flex; gap: 8px; flex-wrap: wrap; flex-shrink: 0; }}
.tag {{
    background: {TAG_BG}; color: var(--blue); font-size: 11px; font-weight: 500;
    padding: 4px 14px; border-radius: 20px;
}}

/* ═══ Input images ═══ */
.input-images {{ display: flex; gap: 14px; flex-shrink: 0; }}
.input-image {{ position: relative; border-radius: var(--radius-sm); overflow: hidden; }}
.input-image img {{
    height: 120px; border-radius: var(--radius-sm);
    border: 1px solid var(--bg-surface);
    object-fit: cover; display: block;
}}
.input-label {{
    position: absolute; bottom: 6px; left: 6px;
    font-size: 10px; font-weight: 500;
    background: rgba(0,0,0,0.7); color: var(--text1);
    padding: 2px 10px; border-radius: 10px;
    backdrop-filter: blur(4px);
}}

/* ═══ Tier sections ═══ */
.tier-section {{
    flex-shrink: 0;
}}
.tier-header {{
    display: flex; align-items: center; gap: 12px;
    margin-bottom: 10px;
}}

/* ═══ Video grid ═══ */
.video-grid {{ display: grid; gap: 14px; flex: 1; min-height: 0; }}
.cols-1 {{ grid-template-columns: 1fr; }}
.cols-2 {{ grid-template-columns: repeat(2, 1fr); }}
.cols-3 {{ grid-template-columns: repeat(3, 1fr); }}
.cols-4 {{ grid-template-columns: repeat(4, 1fr); }}

.video-card {{
    background: var(--bg-card); border-radius: var(--radius);
    overflow: hidden; display: flex; flex-direction: column;
    border: 1px solid var(--bg-surface);
    transition: border-color 0.2s, box-shadow 0.2s;
}}
.video-card:hover {{ border-color: rgba(255,255,255,0.1); }}
.accent-bar {{ height: 3px; flex-shrink: 0; }}

.card-header {{
    display: flex; align-items: center; justify-content: space-between;
    padding: 10px 14px 8px;
}}
.card-info {{ display: flex; align-items: center; gap: 10px; }}
.model-name {{
    font-family: 'Google Sans', sans-serif;
    font-size: 12px; font-weight: 500; color: var(--text1);
}}
.latency {{
    font-size: 11px; color: var(--text3); font-weight: 400;
}}
.pick-btn {{
    background: none; border: none; color: var(--text3);
    font-size: 18px; cursor: pointer; padding: 2px;
    transition: all 0.15s; line-height: 1; border-radius: 50%;
}}
.pick-btn:hover {{ color: var(--yellow); background: rgba(251,188,4,0.1); }}
.pick-btn.picked {{ color: var(--yellow); }}
.video-card.is-best {{
    border-color: var(--yellow);
    box-shadow: 0 0 0 1px var(--yellow), 0 4px 20px rgba(251,188,4,0.08);
}}

.video-card video {{
    width: 100%; flex: 1; min-height: 0;
    background: #000; object-fit: contain;
}}

.play-all-btn {{
    background: var(--bg-card); color: var(--text2); border: 1px solid var(--bg-surface);
    padding: 5px 16px; border-radius: 20px; cursor: pointer;
    font-size: 11px; font-weight: 500;
    font-family: 'Google Sans', sans-serif;
    display: flex; align-items: center; gap: 5px;
    transition: all 0.15s;
}}
.play-all-btn:hover {{ background: var(--bg-surface); color: var(--text1); }}

/* ═══ Regenerate button ═══ */
.regen-btn {{
    background: none; border: 1px solid var(--bg-surface);
    color: var(--text2); padding: 5px 14px; border-radius: 20px;
    cursor: pointer; font-size: 11px; font-weight: 500;
    font-family: 'Google Sans Text', sans-serif;
    transition: all 0.15s; display: flex; align-items: center; gap: 5px;
}}
.regen-btn:hover {{ background: var(--bg-surface); color: var(--text1); }}
.regen-btn.loading {{ opacity: 0.5; pointer-events: none; }}

/* ═══ Comments ═══ */
.comment-section {{ width: 100%; }}
.comments-list {{ max-height: 120px; overflow-y: auto; margin-bottom: 8px; }}
.comment-item {{
    font-size: 12px; color: var(--text2); padding: 4px 0;
    border-bottom: 1px solid rgba(54,54,61,0.5);
    line-height: 1.4;
}}
.comment-item .comment-user {{ color: var(--blue); font-weight: 500; }}
.comment-input-row {{ display: flex; gap: 8px; }}
.comment-input {{
    flex: 1; background: var(--bg-card); border: 1px solid var(--bg-surface);
    color: var(--text1); padding: 8px 14px; border-radius: 20px;
    font-size: 12px; outline: none;
    font-family: 'Google Sans Text', sans-serif;
    transition: border-color 0.15s;
}}
.comment-input:focus {{ border-color: var(--blue); }}
.comment-input::placeholder {{ color: var(--text3); }}
.comment-btn {{
    background: var(--bg-card); border: 1px solid var(--bg-surface);
    color: var(--text2); width: 36px; height: 36px;
    border-radius: 50%; cursor: pointer;
    display: flex; align-items: center; justify-content: center;
    transition: all 0.15s;
}}
.comment-btn:hover {{ background: var(--bg-surface); color: var(--blue); }}

/* ═══ Name dialog ═══ */
.name-overlay {{
    position: fixed; inset: 0; z-index: 200;
    background: rgba(0,0,0,0.6); backdrop-filter: blur(4px);
    display: flex; align-items: center; justify-content: center;
}}
.name-dialog {{
    background: var(--bg-card); border: 1px solid var(--bg-surface);
    border-radius: 16px; padding: 28px 36px; text-align: center;
    box-shadow: 0 8px 40px rgba(0,0,0,0.4);
}}
.name-dialog h3 {{
    font-family: 'Google Sans', sans-serif;
    margin-bottom: 16px; font-size: 18px; font-weight: 500; color: var(--text1);
}}
.name-dialog input {{
    background: var(--bg); border: 1px solid var(--bg-surface);
    color: var(--text1); padding: 10px 16px; border-radius: 20px;
    font-size: 14px; width: 220px; outline: none; text-align: center;
    font-family: 'Google Sans Text', sans-serif;
}}
.name-dialog input:focus {{ border-color: var(--blue); }}
.name-dialog button {{
    margin-top: 16px; background: var(--blue); color: white; border: none;
    padding: 10px 32px; border-radius: 20px; cursor: pointer;
    font-size: 14px; font-weight: 500;
    font-family: 'Google Sans', sans-serif;
}}

@keyframes spin {{ from {{ transform: rotate(0deg); }} to {{ transform: rotate(360deg); }} }}

/* ═══ Scrollbars ═══ */
::-webkit-scrollbar {{ width: 6px; }}
::-webkit-scrollbar-track {{ background: transparent; }}
::-webkit-scrollbar-thumb {{ background: var(--bg-surface); border-radius: 3px; }}
::-webkit-scrollbar-thumb:hover {{ background: var(--text3); }}
</style>
</head>
<body>

<!-- Top bar -->
<div class="topbar">
    <div class="topbar-left">
        <div class="g-dots">
            <div class="g-dot" style="background:{G_BLUE}"></div>
            <div class="g-dot" style="background:{G_RED}"></div>
            <div class="g-dot" style="background:{G_YELLOW}"></div>
            <div class="g-dot" style="background:{G_GREEN}"></div>
        </div>
        <div class="topbar-title">Project Pulse</div>
    </div>
    <div class="topbar-right">
        <button class="regen-btn" id="regenBtn" onclick="regenerateReport()">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><path d="M17.65 6.35A7.958 7.958 0 0012 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08A5.99 5.99 0 0112 18c-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z"/></svg>
            Refresh Report
        </button>
        <button class="nav-btn" onclick="prevSlide()" id="prevBtn">&larr;</button>
        <span class="slide-counter" id="counter">1 / {total_slides}</span>
        <button class="nav-btn" onclick="nextSlide()" id="nextBtn">&rarr;</button>
    </div>
</div>

<!-- Main layout -->
<div class="main">
    <!-- Sidebar -->
    <div class="sidebar">
        <div class="sidebar-label">Batches</div>
        {sidebar_html}
    </div>

    <!-- Slides -->
    <div class="slides-container">
        {slides_joined}
    </div>
</div>

<script>
const API = window.location.origin;
let cur = 0;
const slides = document.querySelectorAll('.slide');
const total = slides.length;
const sidebarItems = document.querySelectorAll('.sidebar-item');
let userName = localStorage.getItem('slideware_user') || '';

function showSlide(n) {{
    slides.forEach(s => s.classList.remove('active'));
    cur = Math.max(0, Math.min(n, total - 1));
    slides[cur].classList.add('active');
    document.getElementById('counter').textContent = (cur + 1) + ' / ' + total;
    document.getElementById('prevBtn').disabled = cur === 0;
    document.getElementById('nextBtn').disabled = cur === total - 1;
    document.querySelectorAll('video').forEach(v => v.pause());
    // Highlight sidebar
    const batch = slides[cur].dataset.batch;
    sidebarItems.forEach(si => {{
        si.classList.toggle('active', si.dataset.slide == cur ||
            (batch && slides[parseInt(si.dataset.slide)]?.dataset.batch === batch));
    }});
}}
function nextSlide() {{ showSlide(cur + 1); }}
function prevSlide() {{ showSlide(cur - 1); }}

function playAllInSection(btn) {{
    const section = btn.closest('.tier-section');
    section.querySelectorAll('video').forEach(v => {{ v.currentTime = 0; v.play(); }});
}}

document.addEventListener('keydown', e => {{
    if (e.target.tagName === 'INPUT') return;
    if (e.key === 'ArrowRight' || e.key === ' ') {{ e.preventDefault(); nextSlide(); }}
    if (e.key === 'ArrowLeft') {{ e.preventDefault(); prevSlide(); }}
}});

// Name prompt
function ensureName() {{
    return new Promise(resolve => {{
        if (userName) return resolve(userName);
        const ov = document.createElement('div');
        ov.className = 'name-overlay';
        ov.innerHTML = `<div class="name-dialog">
            <h3>What's your name?</h3>
            <input id="nameInput" placeholder="Enter your name" autofocus />
            <br/><button onclick="saveName()">Continue</button>
        </div>`;
        document.body.appendChild(ov);
        window._nr = resolve;
        setTimeout(() => {{
            const inp = document.getElementById('nameInput');
            inp.focus();
            inp.addEventListener('keydown', e => {{ if (e.key === 'Enter') saveName(); }});
        }}, 50);
    }});
}}
function saveName() {{
    const v = document.getElementById('nameInput').value.trim();
    if (!v) return;
    userName = v;
    localStorage.setItem('slideware_user', v);
    document.querySelector('.name-overlay').remove();
    if (window._nr) window._nr(v);
}}

// Regenerate report
async function regenerateReport() {{
    const btn = document.getElementById('regenBtn');
    btn.classList.add('loading');
    btn.innerHTML = '<svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor" style="animation:spin 1s linear infinite"><path d="M17.65 6.35A7.958 7.958 0 0012 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08A5.99 5.99 0 0112 18c-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z"/></svg> Refreshing...';
    try {{
        const r = await fetch(API + '/api/slideware/regenerate', {{method:'POST'}});
        const d = await r.json();
        if (d.status === 'ok') window.location.reload();
        else alert('Error: ' + (d.detail || 'unknown'));
    }} catch(e) {{ alert('Failed to regenerate: ' + e.message); }}
    btn.classList.remove('loading');
    btn.innerHTML = '<svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><path d="M17.65 6.35A7.958 7.958 0 0012 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08A5.99 5.99 0 0112 18c-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z"/></svg> Refresh Report';
}}

// Pick best
async function pickBest(btn, batch, tier, model) {{
    const name = await ensureName();
    const section = btn.closest('.tier-section');
    section.querySelectorAll('.pick-btn').forEach(b => {{ b.classList.remove('picked'); b.innerHTML = '&#9734;'; }});
    section.querySelectorAll('.video-card').forEach(c => c.classList.remove('is-best'));
    btn.classList.add('picked'); btn.innerHTML = '&#9733;';
    btn.closest('.video-card').classList.add('is-best');
    fetch(API + '/api/slideware/feedback/pick', {{
        method: 'POST', headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{batch_name:batch, tier, model_key:model, user_name:name}}),
    }});
}}

// Comments
async function addComment(input, batch, tier) {{
    const text = input.value.trim();
    if (!text) return;
    const name = await ensureName();
    input.value = '';
    const r = await fetch(API + '/api/slideware/feedback/comment', {{
        method: 'POST', headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{batch_name:batch, tier, comment:text, user_name:name}}),
    }});
    const d = await r.json();
    renderComments(batch + '__' + tier, d.comments);
}}
function renderComments(key, comments) {{
    const el = document.getElementById('comments-' + key);
    if (!el) return;
    // Newest comments on top
    const sorted = [...(comments||[])].reverse();
    el.innerHTML = sorted.map(c =>
        `<div class="comment-item"><span class="comment-user">${{c.user}}</span>: ${{c.text}}</div>`
    ).join('');
}}

// Load feedback from Firestore
async function loadFeedback() {{
    try {{
        const r = await fetch(API + '/api/slideware/feedback');
        const data = await r.json();
        for (const [key, fb] of Object.entries(data)) {{
            if (fb.best_model) {{
                const section = document.querySelector(`.tier-section[data-batch="${{fb.batch_name}}"][data-tier="${{fb.tier}}"]`);
                if (section) {{
                    const card = section.querySelector(`.video-card[data-model="${{fb.best_model}}"]`);
                    if (card) {{
                        card.classList.add('is-best');
                        const btn = card.querySelector('.pick-btn');
                        if (btn) {{ btn.classList.add('picked'); btn.innerHTML = '&#9733;'; }}
                    }}
                }}
            }}
            if (fb.comments) renderComments(key, fb.comments);
        }}
    }} catch(e) {{ console.error('Failed to load feedback:', e); }}
}}

showSlide(0);
loadFeedback();
</script>
</body>
</html>'''

    with open(output_path, "w") as f:
        f.write(html_content)
    print(f"Generated {total_slides} slides -> {output_path}")
    return output_path


def generate_for_batch(batch_name):
    """Regenerate the full slideware HTML. Called after a batch completes."""
    jobs = fetch_jobs()
    return generate_presentation(jobs, output_path="slideware.html")


if __name__ == "__main__":
    single = sys.argv[1] if len(sys.argv) > 1 else None
    jobs = fetch_jobs()
    print(f"Fetched {len(jobs)} jobs")
    generate_presentation(jobs, output_path="slideware.html", single_batch=single)
