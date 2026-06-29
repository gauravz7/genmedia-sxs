#!/usr/bin/env python3
"""
Generate a PowerPoint (.pptx) presentation comparing Pro vs Fast model tiers.
Videos are downloaded from GCS and embedded directly — no Drive/YouTube needed.
Layout mirrors generate_google_slides.py: Input slide + Pro slide + Fast slide per batch.
"""

import os
import sys
import io
import tempfile
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from google.cloud import storage
from dotenv import load_dotenv

load_dotenv()

GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID", "vital-octagon-19612")
GCS_BUCKET_NAME = os.getenv("GCS_BUCKET_NAME", "project-pulse")

# ── Google palette (RGB) ─────────────────────────────────────────────
BG        = RGBColor(0x1a, 0x1a, 0x1c)
BG_CARD   = RGBColor(0x26, 0x26, 0x2b)
BG_SURFACE = RGBColor(0x36, 0x36, 0x3d)
TEXT1     = RGBColor(0xf2, 0xf2, 0xf5)
TEXT2     = RGBColor(0x9e, 0x9e, 0xa8)
TEXT3     = RGBColor(0x73, 0x73, 0x80)
TAG_BG    = RGBColor(0x33, 0x33, 0x40)

G_BLUE   = RGBColor(0x42, 0x85, 0xF4)
G_RED    = RGBColor(0xEA, 0x43, 0x35)
G_YELLOW = RGBColor(0xFB, 0xBC, 0x04)
G_GREEN  = RGBColor(0x34, 0xA8, 0x53)

PRO_COLOR  = RGBColor(0x8C, 0x5C, 0xF7)
FAST_COLOR = RGBColor(0x00, 0xBD, 0x8C)
WHITE      = RGBColor(0xFF, 0xFF, 0xFF)

SLIDE_W = Inches(13.333)  # 16:9 widescreen
SLIDE_H = Inches(7.5)

# ── Model classification ─────────────────────────────────────────────
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
    "veo": G_BLUE, "seedance": G_GREEN, "kling": G_RED, "grok": G_YELLOW,
}


def classify_model(key):
    k = key.lower()
    for p in PRO_PREFIXES:
        if k.startswith(p): return "pro"
    for p in FAST_PREFIXES:
        if k.startswith(p): return "fast"
    return None


def get_family_color(key):
    k = key.lower()
    for fam, color in FAMILY_COLORS.items():
        if fam in k: return color
    return TEXT2


def pretty_name(key):
    n = key.replace("-", " ")
    n = n.replace("t2v", "(T2V)").replace("i2v", "(I2V)").replace("r2v", "(R2V)")
    return " ".join(
        w.capitalize() if w not in ("(T2V)", "(I2V)", "(R2V)") else w
        for w in n.split()
    )


# ── GCS download ─────────────────────────────────────────────────────

_gcs_client = None

def get_gcs_client():
    global _gcs_client
    if _gcs_client is None:
        _gcs_client = storage.Client(project=GCP_PROJECT_ID)
    return _gcs_client


def download_video(url):
    """Download video from GCS URL, return bytes. Returns None on failure."""
    try:
        # Normalize URL
        if url.startswith("gs://"):
            gs_path = url
        elif "storage.googleapis.com" in url:
            # https://storage.googleapis.com/bucket/path → gs://bucket/path
            path = url.split("storage.googleapis.com/")[1]
            gs_path = "gs://" + path
        else:
            # Non-GCS URL — try HTTP download
            import requests
            resp = requests.get(url, timeout=60)
            resp.raise_for_status()
            return resp.content

        parts = gs_path.replace("gs://", "").split("/", 1)
        bucket_name = parts[0]
        blob_name = parts[1] if len(parts) > 1 else ""

        client = get_gcs_client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(blob_name)
        data = blob.download_as_bytes()
        print(f"    Downloaded {blob_name} ({len(data) // 1024}KB)")
        return data
    except Exception as e:
        print(f"    Failed to download {url[:80]}: {e}")
        return None


def download_image(url):
    """Download image, return bytes."""
    if not url:
        return None
    # Unwrap proxy URLs
    import urllib.parse
    if "/api/media?url=" in url:
        url = urllib.parse.unquote(url.split("/api/media?url=")[-1])
    return download_video(url)  # same logic


# ── Slide helpers ────────────────────────────────────────────────────

def set_slide_bg(slide, color):
    bg = slide.background
    fill = bg.fill
    fill.solid()
    fill.fore_color.rgb = color


def add_rect(slide, left, top, width, height, fill_color, border_color=None):
    from pptx.enum.shapes import MSO_SHAPE
    shape = slide.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE, left, top, width, height
    )
    shape.fill.solid()
    shape.fill.fore_color.rgb = fill_color
    if border_color:
        shape.line.color.rgb = border_color
        shape.line.width = Pt(1)
    else:
        shape.line.fill.background()
    return shape


def add_text_box(slide, left, top, width, height, text, font_size=12,
                 color=TEXT1, bold=False, alignment=PP_ALIGN.LEFT, font_name="Arial"):
    txBox = slide.shapes.add_textbox(left, top, width, height)
    tf = txBox.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = text
    p.font.size = Pt(font_size)
    p.font.color.rgb = color
    p.font.bold = bold
    p.font.name = font_name
    p.alignment = alignment
    return txBox


def add_dot(slide, left, top, size, color):
    from pptx.enum.shapes import MSO_SHAPE
    dot = slide.shapes.add_shape(MSO_SHAPE.OVAL, left, top, size, size)
    dot.fill.solid()
    dot.fill.fore_color.rgb = color
    dot.line.fill.background()
    return dot


def add_line(slide, left, top, width, color):
    from pptx.enum.shapes import MSO_SHAPE
    line = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, left, top, width, Pt(2))
    line.fill.solid()
    line.fill.fore_color.rgb = color
    line.line.fill.background()
    return line


# ── Title slide ──────────────────────────────────────────────────────

def build_title_slide(prs):
    slide = prs.slides.add_slide(prs.slide_layouts[6])  # blank layout
    set_slide_bg(slide, BG)

    # Google dots
    dot_size = Inches(0.2)
    dot_y = Inches(2.8)
    dot_start = Inches(5.5)
    for i, c in enumerate([G_BLUE, G_RED, G_YELLOW, G_GREEN]):
        add_dot(slide, dot_start + Inches(i * 0.35), dot_y, dot_size, c)

    # Title
    add_text_box(slide, Inches(2), Inches(3.15), Inches(9.3), Inches(0.7),
                 "Project Pulse", font_size=42, color=TEXT1, bold=True,
                 alignment=PP_ALIGN.CENTER)

    # Subtitle
    add_text_box(slide, Inches(2), Inches(3.85), Inches(9.3), Inches(0.5),
                 "Model Comparison \u2022 Pro vs Fast", font_size=20, color=TEXT2,
                 alignment=PP_ALIGN.CENTER)

    # Accent line
    add_line(slide, Inches(5.2), Inches(4.5), Inches(3), G_BLUE)

    # Footer
    add_text_box(slide, Inches(2.5), Inches(5.2), Inches(8.3), Inches(0.4),
                 "Side-by-side video generation benchmarks across model families",
                 font_size=13, color=TEXT3, alignment=PP_ALIGN.CENTER)


# ── Input slide ──────────────────────────────────────────────────────

def build_input_slide(prs, batch_name, prompt, categories, images, gen_type):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    set_slide_bg(slide, BG)

    # Batch name
    add_text_box(slide, Inches(0.5), Inches(0.2), Inches(8), Inches(0.4),
                 batch_name, font_size=18, color=TEXT1, bold=True)

    # Type badge
    badge = add_rect(slide, Inches(10.5), Inches(0.22), Inches(1.5), Inches(0.32), G_BLUE)
    badge.text_frame.paragraphs[0].text = gen_type
    badge.text_frame.paragraphs[0].font.size = Pt(11)
    badge.text_frame.paragraphs[0].font.color.rgb = WHITE
    badge.text_frame.paragraphs[0].font.bold = True
    badge.text_frame.paragraphs[0].alignment = PP_ALIGN.CENTER

    # Divider (Google rainbow)
    for i, (c, frac) in enumerate([
        (G_BLUE, 0), (G_RED, 0.25), (G_YELLOW, 0.5), (G_GREEN, 0.75)
    ]):
        add_line(slide, Inches(0.5 + 11.3 * frac), Inches(0.65),
                 Inches(11.3 * 0.25), c)

    # PROMPT label
    add_text_box(slide, Inches(0.5), Inches(0.85), Inches(2), Inches(0.25),
                 "PROMPT", font_size=9, color=TEXT3, bold=True)

    # Prompt box
    has_images = any([
        images.get("start_image_url"),
        images.get("reference_image_url"),
        images.get("reference_images"),
    ])
    prompt_h = Inches(2.2) if has_images else Inches(3.8)

    # Adjust font based on prompt length
    if len(prompt) < 200:
        fs = 13
    elif len(prompt) < 400:
        fs = 11
    elif len(prompt) < 700:
        fs = 10
    else:
        fs = 9

    pbg = add_rect(slide, Inches(0.5), Inches(1.15), Inches(11.3), prompt_h, BG_CARD)
    pbg.text_frame.word_wrap = True
    pbg.text_frame.paragraphs[0].text = prompt
    pbg.text_frame.paragraphs[0].font.size = Pt(fs)
    pbg.text_frame.paragraphs[0].font.color.rgb = TEXT1
    pbg.text_frame.paragraphs[0].font.name = "Arial"

    # Tags
    tag_y = 1.15 + (prompt_h / 914400 / Inches(1).inches * Inches(1).inches / 914400)
    # Simpler: calculate in inches
    prompt_h_in = prompt_h / 914400
    tag_y = Inches(1.15 + prompt_h_in / 914400 * 914400)
    # Even simpler
    tag_top = Inches(1.15) + prompt_h + Inches(0.15)
    if categories:
        tags_str = "   ".join(categories)
        tag_box = add_rect(slide, Inches(0.5), tag_top, Inches(11.3), Inches(0.35), TAG_BG)
        tag_box.text_frame.paragraphs[0].text = tags_str
        tag_box.text_frame.paragraphs[0].font.size = Pt(11)
        tag_box.text_frame.paragraphs[0].font.color.rgb = G_BLUE
        tag_box.text_frame.paragraphs[0].alignment = PP_ALIGN.CENTER
        img_top = tag_top + Inches(0.5)
    else:
        img_top = tag_top + Inches(0.1)

    # Input images
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
        add_text_box(slide, Inches(0.5), img_top, Inches(2), Inches(0.25),
                     "INPUT IMAGES", font_size=9, color=TEXT3, bold=True)
        img_top += Inches(0.3)

        for idx, (label, url) in enumerate(img_items[:4]):
            img_data = download_image(url)
            img_w = Inches(2.5)
            img_x = Inches(0.5 + idx * 2.7)

            if img_data:
                try:
                    img_stream = io.BytesIO(img_data)
                    slide.shapes.add_picture(img_stream, img_x, img_top,
                                             width=img_w)
                    # Label
                    add_text_box(slide, img_x, img_top + Inches(1.7),
                                 img_w, Inches(0.2), label,
                                 font_size=9, color=TEXT2, alignment=PP_ALIGN.CENTER)
                except Exception as e:
                    print(f"    Image embed failed: {e}")
                    add_text_box(slide, img_x, img_top, img_w, Inches(1.5),
                                 f"{label}\n(unavailable)", font_size=10,
                                 color=TEXT3, alignment=PP_ALIGN.CENTER)
            else:
                add_text_box(slide, img_x, img_top, img_w, Inches(1.5),
                             f"{label}\n(unavailable)", font_size=10,
                             color=TEXT3, alignment=PP_ALIGN.CENTER)


# ── Comparison slide ─────────────────────────────────────────────────

def build_comparison_slide(prs, batch_name, tier, models_data):
    is_pro = tier == "pro"
    accent = PRO_COLOR if is_pro else FAST_COLOR
    tier_label = "Pro Tier" if is_pro else "Fast Tier"

    # Filter to successful only
    successful = {}
    for mk in sorted(models_data.keys()):
        result = models_data[mk]
        if result.get("status") == "success":
            raw_url = result.get("url") or (result.get("result") or {}).get("url", "")
            if raw_url:
                successful[mk] = (result, raw_url)

    if not successful:
        return

    slide = prs.slides.add_slide(prs.slide_layouts[6])
    set_slide_bg(slide, BG)

    # Header
    add_text_box(slide, Inches(0.5), Inches(0.2), Inches(8), Inches(0.4),
                 batch_name, font_size=18, color=TEXT1, bold=True)

    # Tier badge
    badge = add_rect(slide, Inches(10), Inches(0.2), Inches(2), Inches(0.35), accent)
    badge.text_frame.paragraphs[0].text = tier_label
    badge.text_frame.paragraphs[0].font.size = Pt(12)
    badge.text_frame.paragraphs[0].font.color.rgb = WHITE
    badge.text_frame.paragraphs[0].font.bold = True
    badge.text_frame.paragraphs[0].alignment = PP_ALIGN.CENTER

    # Divider
    add_line(slide, Inches(0.5), Inches(0.65), Inches(11.8), accent)

    # Video grid
    n = len(successful)
    cols = min(n, 4)
    rows = (n + cols - 1) // cols

    gap_x = 0.15
    gap_y = 0.12
    label_h = 0.5
    total_w = 12.3
    card_w = (total_w - (cols - 1) * gap_x) / cols
    available_h = 6.2
    card_h = (available_h - (rows - 1) * gap_y) / rows
    vid_h = card_h - label_h

    for idx, (mk, (result, raw_url)) in enumerate(successful.items()):
        col = idx % cols
        row = idx // cols
        x = Inches(0.5 + col * (card_w + gap_x))
        y = Inches(0.85 + row * (card_h + gap_y))

        fam_color = get_family_color(mk)
        display = pretty_name(mk)
        latency = result.get("latency")

        # Card background
        add_rect(slide, x, y, Inches(card_w), Inches(card_h), BG_CARD, BG_SURFACE)

        # Accent bar
        add_line(slide, x, y, Inches(card_w), fam_color)

        # Model name
        name_text = display
        if latency:
            name_text += f"  ({latency:.0f}s)"
        add_text_box(slide, x + Inches(0.08), y + Inches(0.1),
                     Inches(card_w - 0.16), Inches(0.35),
                     name_text, font_size=10, color=TEXT1, bold=True,
                     alignment=PP_ALIGN.CENTER)

        # Download and embed video
        print(f"  Downloading {mk}...")
        video_data = download_video(raw_url)
        if video_data:
            try:
                vid_stream = io.BytesIO(video_data)
                # Write to temp file (python-pptx needs a file path for video)
                with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
                    tmp.write(video_data)
                    tmp_path = tmp.name

                vid_left = x + Inches(0.05)
                vid_top = y + Inches(label_h)
                vid_width = Inches(card_w - 0.1)
                vid_height = Inches(vid_h - 0.05)

                slide.shapes.add_movie(
                    tmp_path, vid_left, vid_top, vid_width, vid_height,
                    mime_type="video/mp4",
                )
                # Clean up temp file
                os.unlink(tmp_path)
                print(f"    Embedded {mk}")
            except Exception as e:
                print(f"    Video embed failed for {mk}: {e}")
                add_text_box(slide, x + Inches(0.1), y + Inches(label_h),
                             Inches(card_w - 0.2), Inches(vid_h),
                             "Video embed failed", font_size=10, color=G_RED,
                             alignment=PP_ALIGN.CENTER)
        else:
            add_text_box(slide, x + Inches(0.1), y + Inches(label_h),
                         Inches(card_w - 0.2), Inches(vid_h),
                         "Download failed", font_size=10, color=G_RED,
                         alignment=PP_ALIGN.CENTER)


# ── Firestore ────────────────────────────────────────────────────────

def fetch_jobs(batch_filter=None):
    from google.cloud import firestore
    db = firestore.Client(project=GCP_PROJECT_ID)
    query = db.collection("eval_jobs").order_by("timestamp", direction=firestore.Query.DESCENDING)
    docs = query.stream()
    jobs = []
    for doc in docs:
        data = {**doc.to_dict(), "_id": doc.id}
        if batch_filter:
            bn = data.get("prompt_id") or data.get("_id", "")
            if bn not in batch_filter:
                continue
        jobs.append(data)
    return jobs


# ── Main ─────────────────────────────────────────────────────────────

def generate_pptx(batch_filter=None, output_path="project_pulse.pptx"):
    """Generate a PPTX with embedded videos for the specified batches."""
    jobs = fetch_jobs(batch_filter=batch_filter)
    if not jobs:
        print("No jobs found.")
        return None

    print(f"Building PPTX for {len(jobs)} batch(es)...")

    prs = Presentation()
    prs.slide_width = SLIDE_W
    prs.slide_height = SLIDE_H

    build_title_slide(prs)

    for job in jobs:
        batch_name = job.get("prompt_id") or job.get("_id", "unknown")
        results = job.get("results", {})
        prompt = job.get("prompt", "")
        categories = job.get("categories", [])
        images = {
            "start_image_url": job.get("start_image_url"),
            "end_image_url": job.get("end_image_url"),
            "reference_image_url": job.get("reference_image_url"),
            "reference_images": job.get("reference_images"),
        }

        pro = {k: v for k, v in results.items() if classify_model(k) == "pro"}
        fast = {k: v for k, v in results.items() if classify_model(k) == "fast"}

        has_pro = any(v.get("status") == "success" for v in pro.values())
        has_fast = any(v.get("status") == "success" for v in fast.values())
        if not has_pro and not has_fast:
            print(f"  {batch_name}: no successful videos, skipping")
            continue

        gen_types = set()
        for mk in list(pro.keys()) + list(fast.keys()):
            if "t2v" in mk: gen_types.add("T2V")
            elif "i2v" in mk: gen_types.add("I2V")
            elif "r2v" in mk: gen_types.add("R2V")
        gen_type = " / ".join(sorted(gen_types)) or "Video"

        print(f"\n  === {batch_name} ({gen_type}) ===")

        build_input_slide(prs, batch_name, prompt, categories, images, gen_type)

        if has_pro:
            print(f"  Pro tier: {sum(1 for v in pro.values() if v.get('status')=='success')} models")
            build_comparison_slide(prs, batch_name, "pro", pro)

        if has_fast:
            print(f"  Fast tier: {sum(1 for v in fast.values() if v.get('status')=='success')} models")
            build_comparison_slide(prs, batch_name, "fast", fast)

    prs.save(output_path)
    size_mb = os.path.getsize(output_path) / (1024 * 1024)
    print(f"\nSaved: {output_path} ({size_mb:.1f} MB)")
    print(f"Total slides: {len(prs.slides)}")
    return output_path


if __name__ == "__main__":
    batches = [a for a in sys.argv[1:] if not a.startswith("--")] or None
    output = "project_pulse.pptx"
    for a in sys.argv[1:]:
        if a.startswith("--output="):
            output = a.split("=", 1)[1]
    generate_pptx(batch_filter=batches, output_path=output)
