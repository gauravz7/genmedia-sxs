#!/usr/bin/env python3
"""
Generate a Google Slides presentation comparing Pro vs Fast model tiers.
Layout per batch:
  - Slide 1: Inputs (prompt text, input images, tags)
  - Slide 2: Pro Tier SxS comparison (video thumbnails with links)
  - Slide 3: Fast Tier SxS comparison (video thumbnails with links)
Uses Google Material Design palette.
"""

import os
import sys
import uuid
import urllib.parse
from google.cloud import firestore
from googleapiclient.discovery import build
import google.auth
from google.auth.transport.requests import Request
from dotenv import load_dotenv

load_dotenv()

GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID", "vital-octagon-19612")
DRIVE_PARENT_FOLDER_ID = os.getenv("DRIVE_PARENT_FOLDER_ID", "0ABrvNdvu6qXtUk9PVA")
BACKEND_URL = "https://project-pulse-backend-440790012685.us-central1.run.app"
GCS_BUCKET_NAME = os.getenv("GCS_BUCKET_NAME", "project-pulse")

SCOPES = [
    "https://www.googleapis.com/auth/presentations",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/devstorage.read_only",
]

# ── Google Material Palette ─────────────────────────────────────────
C = {
    "bg":           {"red": 0.10, "green": 0.10, "blue": 0.11},
    "bg_card":      {"red": 0.15, "green": 0.15, "blue": 0.17},
    "bg_surface":   {"red": 0.21, "green": 0.21, "blue": 0.24},
    "white":        {"red": 1.0,  "green": 1.0,  "blue": 1.0},
    "text1":        {"red": 0.95, "green": 0.95, "blue": 0.96},
    "text2":        {"red": 0.62, "green": 0.62, "blue": 0.66},
    "text3":        {"red": 0.45, "green": 0.45, "blue": 0.50},
    # Google 4-colour
    "g_blue":       {"red": 0.26, "green": 0.52, "blue": 0.96},
    "g_red":        {"red": 0.92, "green": 0.26, "blue": 0.21},
    "g_yellow":     {"red": 0.98, "green": 0.74, "blue": 0.02},
    "g_green":      {"red": 0.21, "green": 0.65, "blue": 0.33},
    # Tier
    "pro":          {"red": 0.55, "green": 0.36, "blue": 0.97},
    "fast":         {"red": 0.0,  "green": 0.74, "blue": 0.55},
    # Transparent-ish
    "tag_bg":       {"red": 0.20, "green": 0.20, "blue": 0.25},
}

FAMILY_COLORS = {
    "veo":      "g_blue",
    "seedance": "g_green",
    "kling":    "g_red",
    "grok":     "g_yellow",
}

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


def emu(inches):
    return int(inches * 914400)

def uid(prefix=""):
    return f"{prefix}{uuid.uuid4().hex[:8]}"

def classify(key):
    k = key.lower()
    for p in PRO_PREFIXES:
        if k.startswith(p): return "pro"
    for p in FAST_PREFIXES:
        if k.startswith(p): return "fast"
    return None

def family(key):
    k = key.lower()
    for f in FAMILY_COLORS:
        if f in k: return f
    return None

def pretty(key):
    n = key.replace("-", " ")
    n = n.replace("t2v", "(T2V)").replace("i2v", "(I2V)").replace("r2v", "(R2V)")
    return " ".join(w.capitalize() if w not in ("(T2V)","(I2V)","(R2V)") else w for w in n.split())


# ── Services ────────────────────────────────────────────────────────

def get_services():
    creds, _ = google.auth.default(scopes=SCOPES)
    if not creds.valid:
        creds.refresh(Request())
    return (
        build("slides", "v1", credentials=creds),
        build("drive",  "v3", credentials=creds),
    )


def get_drive_videos(drive_svc):
    """Returns {batch_name: {model_key: {id, webViewLink}}}."""
    out = {}
    folders = drive_svc.files().list(
        q=f"'{DRIVE_PARENT_FOLDER_ID}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false",
        fields="files(id,name)", spaces="drive",
        supportsAllDrives=True, includeItemsFromAllDrives=True, pageSize=100,
    ).execute().get("files", [])

    for folder in folders:
        batch = folder["name"]
        vids = drive_svc.files().list(
            q=f"'{folder['id']}' in parents and trashed=false",
            fields="files(id,name,webViewLink)",
            spaces="drive", supportsAllDrives=True, includeItemsFromAllDrives=True, pageSize=50,
        ).execute().get("files", [])
        out[batch] = {}
        for v in vids:
            mk = v["name"].replace(".mp4", "")
            out[batch][mk] = {
                "id": v["id"],
                "link": v.get("webViewLink", f"https://drive.google.com/file/d/{v['id']}/view"),
            }
    return out


def fetch_jobs():
    db = firestore.Client(project=GCP_PROJECT_ID)
    docs = db.collection("eval_jobs").order_by(
        "timestamp", direction=firestore.Query.DESCENDING
    ).stream()
    return [{**doc.to_dict(), "_id": doc.id} for doc in docs]



# ── Slide builders ──────────────────────────────────────────────────

def shape(sid, oid, stype, x, y, w, h):
    return {"createShape": {
        "objectId": oid, "shapeType": stype,
        "elementProperties": {
            "pageObjectId": sid,
            "size": {"width": {"magnitude": emu(w), "unit": "EMU"},
                     "height": {"magnitude": emu(h), "unit": "EMU"}},
            "transform": {"scaleX": 1, "scaleY": 1,
                          "translateX": emu(x), "translateY": emu(y), "unit": "EMU"},
        },
    }}

def fill(oid, color_key):
    return {"updateShapeProperties": {
        "objectId": oid,
        "shapeProperties": {
            "shapeBackgroundFill": {"solidFill": {"color": {"rgbColor": C[color_key]}}},
            "outline": {"propertyState": "NOT_RENDERED"},
        },
        "fields": "shapeBackgroundFill.solidFill.color,outline",
    }}

def text(oid, txt):
    return {"insertText": {"objectId": oid, "text": txt}}

def style_text(oid, start, end, size, color_key, bold=False, italic=False, font="Google Sans"):
    s = {
        "fontFamily": font,
        "fontSize": {"magnitude": size, "unit": "PT"},
        "bold": bold,
        "italic": italic,
        "foregroundColor": {"opaqueColor": {"rgbColor": C[color_key]}},
    }
    return {"updateTextStyle": {
        "objectId": oid, "style": s,
        "textRange": {"type": "FIXED_RANGE", "startIndex": start, "endIndex": end},
        "fields": "fontFamily,fontSize,bold,italic,foregroundColor",
    }}

def style_all(oid, size, color_key, bold=False, font="Google Sans"):
    return {"updateTextStyle": {
        "objectId": oid,
        "style": {
            "fontFamily": font,
            "fontSize": {"magnitude": size, "unit": "PT"},
            "bold": bold,
            "foregroundColor": {"opaqueColor": {"rgbColor": C[color_key]}},
        },
        "textRange": {"type": "ALL"},
        "fields": "fontFamily,fontSize,bold,foregroundColor",
    }}

def center(oid):
    return {"updateParagraphStyle": {
        "objectId": oid, "style": {"alignment": "CENTER"},
        "textRange": {"type": "ALL"}, "fields": "alignment",
    }}

def bg(sid):
    return {"updatePageProperties": {
        "objectId": sid,
        "pageProperties": {"pageBackgroundFill": {"solidFill": {"color": {"rgbColor": C["bg"]}}}},
        "fields": "pageBackgroundFill.solidFill.color",
    }}


# ── Title slide ─────────────────────────────────────────────────────

def build_title_slide():
    sid = uid("T")
    r = []
    r.append({"createSlide": {"objectId": sid, "insertionIndex": 0,
              "slideLayoutReference": {"predefinedLayout": "BLANK"}}})
    r.append(bg(sid))

    # Google 4 dots
    for i, ck in enumerate(["g_blue", "g_red", "g_yellow", "g_green"]):
        d = uid("d")
        r.append(shape(sid, d, "ELLIPSE", 3.6 + i * 0.45, 1.6, 0.22, 0.22))
        r.append(fill(d, ck))

    # Title
    t = uid("t")
    r.append(shape(sid, t, "TEXT_BOX", 1.5, 2.0, 7, 0.7))
    r.append(text(t, "Project Pulse"))
    r.append(style_all(t, 40, "text1", bold=True))
    r.append(center(t))

    # Subtitle
    s = uid("s")
    r.append(shape(sid, s, "TEXT_BOX", 1.5, 2.7, 7, 0.5))
    r.append(text(s, "Model Comparison · Pro vs Fast"))
    r.append(style_all(s, 18, "text2"))
    r.append(center(s))

    # Accent line
    ln = uid("ln")
    r.append(shape(sid, ln, "RECTANGLE", 3.5, 3.3, 3, 0.025))
    r.append(fill(ln, "g_blue"))

    # Footer
    ft = uid("ft")
    r.append(shape(sid, ft, "TEXT_BOX", 2, 4.2, 6, 0.35))
    r.append(text(ft, "Side-by-side video generation benchmarks across model families"))
    r.append(style_all(ft, 12, "text3"))
    r.append(center(ft))

    return r


# ── Input slide (prompt, images, tags) ──────────────────────────────

def build_input_slide(batch_name, prompt, categories, images, slide_idx, gen_type, drive_svc=None):
    sid = uid("I")
    r = []
    r.append({"createSlide": {"objectId": sid, "insertionIndex": slide_idx,
              "slideLayoutReference": {"predefinedLayout": "BLANK"}}})
    r.append(bg(sid))

    # Top bar
    bn = uid("bn")
    r.append(shape(sid, bn, "TEXT_BOX", 0.4, 0.15, 5, 0.35))
    r.append(text(bn, batch_name))
    r.append(style_all(bn, 16, "text1", bold=True))

    # Type badge
    tp = uid("tp")
    r.append(shape(sid, tp, "ROUND_RECTANGLE", 8.2, 0.17, 1.3, 0.28))
    r.append(fill(tp, "g_blue"))
    r.append(text(tp, gen_type))
    r.append(style_all(tp, 10, "white", bold=True))
    r.append(center(tp))

    # Divider
    dv = uid("dv")
    r.append(shape(sid, dv, "RECTANGLE", 0.4, 0.55, 9.2, 0.015))
    r.append(fill(dv, "bg_surface"))

    # Prompt section
    pl = uid("pl")
    r.append(shape(sid, pl, "TEXT_BOX", 0.4, 0.7, 1.2, 0.25))
    r.append(text(pl, "PROMPT"))
    r.append(style_all(pl, 9, "text3", bold=True))

    # Prompt text box — full prompt, dynamic font sizing
    pbg = uid("pbg")
    has_images = bool(images.get("start_image_url") or images.get("reference_image_url") or images.get("reference_images"))
    prompt_height = 3.4 if not has_images else 2.0
    r.append(shape(sid, pbg, "ROUND_RECTANGLE", 0.4, 0.95, 9.2, prompt_height))
    r.append(fill(pbg, "bg_card"))
    r.append(text(pbg, prompt))  # full prompt, no truncation
    # Dynamic font: scale down for longer prompts to fit the box
    if len(prompt) < 150:
        font_size = 12
    elif len(prompt) < 300:
        font_size = 10
    elif len(prompt) < 500:
        font_size = 9
    elif len(prompt) < 800:
        font_size = 8
    else:
        font_size = 7
    r.append(style_all(pbg, font_size, "text1"))

    # Tags
    tag_y = 0.95 + prompt_height + 0.15
    if categories:
        tags_text = "   ".join(categories)
        tg = uid("tg")
        r.append(shape(sid, tg, "ROUND_RECTANGLE", 0.4, tag_y, 9.2, 0.35))
        r.append(fill(tg, "tag_bg"))
        r.append(text(tg, tags_text))
        r.append(style_all(tg, 10, "g_blue"))
        r.append(center(tg))
        img_y = tag_y + 0.5
    else:
        img_y = tag_y + 0.1

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
        il = uid("il")
        r.append(shape(sid, il, "TEXT_BOX", 0.4, img_y, 2, 0.25))
        r.append(text(il, "INPUT IMAGES"))
        r.append(style_all(il, 9, "text3", bold=True))

        for idx, (label, url) in enumerate(img_items[:4]):
            public_url = _upload_image_to_drive(url, drive_svc)
            img_w = 2.1
            img_h = 1.4
            ix = 0.4 + idx * (img_w + 0.15)
            iy = img_y + 0.3

            if public_url:
                # Embed actual image via createImage
                img_oid = uid("im")
                r.append({"createImage": {
                    "objectId": img_oid,
                    "url": public_url,
                    "elementProperties": {
                        "pageObjectId": sid,
                        "size": {
                            "width": {"magnitude": emu(img_w), "unit": "EMU"},
                            "height": {"magnitude": emu(img_h), "unit": "EMU"},
                        },
                        "transform": {
                            "scaleX": 1, "scaleY": 1,
                            "translateX": emu(ix), "translateY": emu(iy),
                            "unit": "EMU",
                        },
                    },
                }})
                # Label below image
                lbl = uid("lb")
                r.append(shape(sid, lbl, "TEXT_BOX", ix, iy + img_h, img_w, 0.22))
                r.append(text(lbl, label))
                r.append(style_all(lbl, 9, "text2"))
                r.append(center(lbl))
            else:
                # Fallback: placeholder card
                card = uid("ic")
                r.append(shape(sid, card, "ROUND_RECTANGLE", ix, iy, img_w, img_h))
                r.append(fill(card, "bg_surface"))
                r.append(text(card, f"{label}\n\n(image unavailable)"))
                r.append(style_all(card, 10, "text2", bold=True))
                r.append(center(card))

    return r


# ── Comparison slide (video thumbnails + links) ─────────────────────

def build_comparison_slide(batch_name, tier, models_data, drive_videos, slide_idx, ratio="16:9"):
    sid = uid("C")
    r = []
    is_pro = tier == "pro"
    accent_key = "pro" if is_pro else "fast"
    tier_label = "⭐ Pro Tier" if is_pro else "⚡ Fast Tier"

    r.append({"createSlide": {"objectId": sid, "insertionIndex": slide_idx,
              "slideLayoutReference": {"predefinedLayout": "BLANK"}}})
    r.append(bg(sid))

    # Header
    bn = uid("bn")
    r.append(shape(sid, bn, "TEXT_BOX", 0.4, 0.15, 5, 0.35))
    r.append(text(bn, batch_name))
    r.append(style_all(bn, 16, "text1", bold=True))

    # Tier badge
    tb = uid("tb")
    r.append(shape(sid, tb, "ROUND_RECTANGLE", 7.8, 0.17, 1.8, 0.3))
    r.append(fill(tb, accent_key))
    r.append(text(tb, tier_label))
    r.append(style_all(tb, 11, "white", bold=True))
    r.append(center(tb))

    # Divider
    dv = uid("dv")
    r.append(shape(sid, dv, "RECTANGLE", 0.4, 0.55, 9.2, 0.015))
    r.append(fill(dv, accent_key))

    # Video grid — maintain video aspect ratio
    sorted_models = sorted(models_data.keys())
    n = len(sorted_models)
    if n == 0:
        return r

    # Parse aspect ratio
    try:
        rw, rh = map(int, ratio.split(":"))
    except Exception:
        rw, rh = 16, 9

    cols = min(n, 4)
    rows = (n + cols - 1) // cols
    gap_x, gap_y = 0.12, 0.1
    label_h = 0.45  # space for model name + latency above video
    card_w = (9.2 - (cols - 1) * gap_x) / cols
    vid_w = card_w - 0.1
    vid_h = vid_w * rh / rw  # maintain aspect ratio

    # Cap video height so cards fit on slide
    available_h = 4.85
    max_card_h = (available_h - (rows - 1) * gap_y) / rows
    if vid_h + label_h > max_card_h:
        vid_h = max_card_h - label_h
        vid_w = vid_h * rw / rh  # shrink width to keep ratio

    card_h = label_h + vid_h

    for idx, mk in enumerate(sorted_models):
        result = models_data[mk]
        col = idx % cols
        row = idx // cols
        x = 0.4 + col * (card_w + 0.12)
        y = 0.65 + row * (card_h + 0.1)

        fam = family(mk)
        fam_color = FAMILY_COLORS.get(fam, "g_blue")

        # Card background
        cb = uid("cb")
        r.append(shape(sid, cb, "ROUND_RECTANGLE", x, y, card_w, card_h))
        r.append(fill(cb, "bg_card"))

        # Colour accent bar at top of card
        ab = uid("ab")
        r.append(shape(sid, ab, "RECTANGLE", x, y, card_w, 0.06))
        r.append(fill(ab, fam_color))

        # Model name
        nm = uid("nm")
        display = pretty(mk)
        r.append(shape(sid, nm, "TEXT_BOX", x + 0.05, y + 0.08, card_w - 0.1, 0.22))
        r.append(text(nm, display))
        r.append(style_all(nm, 9, "text1", bold=True))
        r.append(center(nm))

        # Latency
        latency = result.get("latency")
        if latency:
            lt = uid("lt")
            r.append(shape(sid, lt, "TEXT_BOX", x + 0.05, y + 0.28, card_w - 0.1, 0.15))
            r.append(text(lt, f"{latency:.0f}s"))
            r.append(style_all(lt, 8, "text3"))
            r.append(center(lt))

        # Video embed from Drive or placeholder
        drive_info = drive_videos.get(mk)
        status = result.get("status", "unknown")

        if drive_info and status == "success":
            vid_id = uid("vi")
            # Center video within card
            vid_x_offset = (card_w - vid_w) / 2
            r.append({"createVideo": {
                "objectId": vid_id,
                "source": "DRIVE",
                "id": drive_info["id"],
                "elementProperties": {
                    "pageObjectId": sid,
                    "size": {"width": {"magnitude": emu(vid_w), "unit": "EMU"},
                             "height": {"magnitude": emu(vid_h), "unit": "EMU"}},
                    "transform": {"scaleX": 1, "scaleY": 1,
                                  "translateX": emu(x + vid_x_offset),
                                  "translateY": emu(y + label_h), "unit": "EMU"},
                },
            }})
        else:
            # Placeholder
            ph = uid("ph")
            r.append(shape(sid, ph, "TEXT_BOX", x + 0.05, y + label_h, card_w - 0.1, vid_h))
            err_msg = "Error" if status == "error" else "No video"
            r.append(text(ph, err_msg))
            r.append(style_all(ph, 10, "g_red"))
            r.append(center(ph))

    return r


_IMAGE_CACHE = {}  # url -> public_url

def _upload_image_to_drive(url, drive_svc=None):
    """Generate a GCS V4 signed URL for the image — publicly accessible,
    no auth needed. The Slides API can fetch it directly."""
    if not url:
        return None
    if url in _IMAGE_CACHE:
        return _IMAGE_CACHE[url]

    from urllib.parse import unquote
    from util.gcs_utils import https_to_gs, get_signing_credentials
    from google.cloud import storage
    import datetime

    # Unwrap proxy URLs
    raw = url
    if "/api/media?url=" in url:
        raw = unquote(url.split("/api/media?url=")[-1])

    if not (raw.startswith("gs://") or "storage.googleapis.com" in raw):
        if raw.startswith("http"):
            _IMAGE_CACHE[url] = raw
            return raw
        return None

    try:
        gs = https_to_gs(raw)
        parts = gs.replace("gs://", "").split("/")
        bucket_name = parts[0]
        blob_name = "/".join(parts[1:])

        # Try local signing key first, fall back to Cloud Run SA (IAM signBlob)
        signing_creds = get_signing_credentials()
        if signing_creds:
            client = storage.Client(credentials=signing_creds,
                                    project=GCP_PROJECT_ID)
            bucket = client.bucket(bucket_name)
            blob = bucket.blob(blob_name)
            signed = blob.generate_signed_url(
                version="v4",
                expiration=datetime.timedelta(hours=24),
                method="GET",
                credentials=signing_creds,
            )
        else:
            # On Cloud Run: use SA identity via IAM signBlob API
            import google.auth
            creds, _ = google.auth.default()
            sa_email = getattr(creds, "service_account_email", None)
            if not sa_email:
                print("  No signing credentials or SA available")
                return None
            client = storage.Client(project=GCP_PROJECT_ID)
            bucket = client.bucket(bucket_name)
            blob = bucket.blob(blob_name)
            signed = blob.generate_signed_url(
                version="v4",
                expiration=datetime.timedelta(hours=24),
                method="GET",
                service_account_email=sa_email,
                access_token=creds.token,
            )

        print(f"  Signed URL for {blob_name}")
        _IMAGE_CACHE[url] = signed
        return signed
    except Exception as e:
        print(f"  Signed URL failed: {e}")
        return None


# ── Persistent presentation config ─────────────────────────────────

def _get_config(db):
    """Read slides presentation config from Firestore."""
    doc = db.collection("config").document("slides_presentation").get()
    return doc.to_dict() if doc.exists else {}


def _save_config(db, pres_id, batches):
    """Save/update slides presentation config in Firestore."""
    db.collection("config").document("slides_presentation").set({
        "presentation_id": pres_id,
        "batches": sorted(set(batches)),
    })


def _send_requests(slides_svc, pres_id, reqs):
    """Send Slides API requests in chunks of 40 with rate-limit handling."""
    import time as _time
    if not reqs:
        return
    CHUNK = 40
    total_chunks = (len(reqs) + CHUNK - 1) // CHUNK
    for i in range(0, len(reqs), CHUNK):
        chunk = reqs[i:i + CHUNK]
        chunk_num = i // CHUNK + 1
        for attempt in range(3):
            try:
                slides_svc.presentations().batchUpdate(
                    presentationId=pres_id, body={"requests": chunk},
                ).execute()
                break
            except Exception as e:
                if "RATE_LIMIT_EXCEEDED" in str(e) and attempt < 2:
                    wait = 30 * (attempt + 1)
                    print(f"  Rate limited on chunk {chunk_num}, waiting {wait}s…")
                    _time.sleep(wait)
                    continue
                print(f"  Error in chunk {chunk_num}: {e}")
                # Fallback: one by one
                for j, req in enumerate(chunk):
                    for a2 in range(2):
                        try:
                            slides_svc.presentations().batchUpdate(
                                presentationId=pres_id, body={"requests": [req]},
                            ).execute()
                            break
                        except Exception as e2:
                            if "RATE_LIMIT_EXCEEDED" in str(e2) and a2 == 0:
                                _time.sleep(30)
                                continue
                            print(f"    Failed {i + j}: {list(req.keys())[0]} - {e2}")
                break
        # Throttle: stay under 60 writes/min
        if total_chunks > 10 and chunk_num < total_chunks:
            _time.sleep(1.5)
        print(f"  Chunk {chunk_num}/{total_chunks} done")


def _build_batch_slides(job, drive_vids, slide_idx, drive_svc):
    """Build all slides (input + pro + fast) for a single batch.
    Returns (requests_list, num_slides_added)."""
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

    pro = {k: v for k, v in results.items() if classify(k) == "pro"}
    fast = {k: v for k, v in results.items() if classify(k) == "fast"}

    if not pro and not fast:
        return [], 0

    ratio = job.get("ratio", "16:9") or "16:9"
    if ratio not in ("16:9", "9:16"):
        ratio = "16:9"

    gen_types = set()
    for mk in list(pro.keys()) + list(fast.keys()):
        if "t2v" in mk: gen_types.add("T2V")
        elif "i2v" in mk: gen_types.add("I2V")
        elif "r2v" in mk: gen_types.add("R2V")
    gen_type = " / ".join(sorted(gen_types)) or "Video"

    print(f"\n  {batch_name}: {len(pro)} pro + {len(fast)} fast (ratio={ratio})")

    reqs = []
    added = 0

    reqs.extend(build_input_slide(batch_name, prompt, categories, images,
                                  slide_idx + added, gen_type, drive_svc))
    added += 1

    if pro:
        reqs.extend(build_comparison_slide(batch_name, "pro", pro,
                                           drive_vids, slide_idx + added, ratio))
        added += 1

    if fast:
        reqs.extend(build_comparison_slide(batch_name, "fast", fast,
                                           drive_vids, slide_idx + added, ratio))
        added += 1

    return reqs, added


# ── Main entry points ──────────────────────────────────────────────

def _create_new_presentation(slides_svc, drive_svc, db):
    """Create a fresh presentation, move to Shared Drive, save config."""
    pres = slides_svc.presentations().create(
        body={"title": "Project Pulse — Model Comparison"}
    ).execute()
    pres_id = pres["presentationId"]
    print(f"Created presentation: {pres_id}")

    try:
        drive_svc.files().update(
            fileId=pres_id,
            addParents=DRIVE_PARENT_FOLDER_ID,
            removeParents="root",
            supportsAllDrives=True, fields="id,parents",
        ).execute()
        print("  Moved to Shared Drive")
    except Exception as e:
        print(f"  Warning: could not move: {e}")

    # Delete default blank slide, add title
    default_slides = pres.get("slides", [])
    init_reqs = [{"deleteObject": {"objectId": s["objectId"]}} for s in default_slides]
    init_reqs.extend(build_title_slide())
    _send_requests(slides_svc, pres_id, init_reqs)

    _save_config(db, pres_id, [])
    return pres_id


def _get_or_create_presentation(slides_svc, drive_svc, db):
    """Return the persistent presentation ID, creating one if needed."""
    cfg = _get_config(db)
    pres_id = cfg.get("presentation_id")

    if pres_id:
        # Verify it still exists
        try:
            slides_svc.presentations().get(presentationId=pres_id).execute()
            return pres_id
        except Exception:
            print(f"  Presentation {pres_id} not accessible, creating new one…")

    return _create_new_presentation(slides_svc, drive_svc, db)


def append_batch_slides(batch_name):
    """Append slides for a single batch to the persistent presentation.
    Safe to call multiple times — skips batches already present."""
    slides_svc, drive_svc = get_services()
    db = firestore.Client(project=GCP_PROJECT_ID)

    cfg = _get_config(db)
    existing_batches = cfg.get("batches", [])
    if batch_name in existing_batches:
        print(f"Slides: {batch_name} already in presentation, skipping.")
        return

    pres_id = _get_or_create_presentation(slides_svc, drive_svc, db)

    # Current slide count → insert after last slide
    pres = slides_svc.presentations().get(presentationId=pres_id).execute()
    slide_idx = len(pres.get("slides", []))

    print(f"Slides: appending {batch_name} at index {slide_idx}…")

    # Fetch this batch's job from Firestore
    docs = db.collection("eval_jobs").where("prompt_id", "==", batch_name).stream()
    job = None
    for doc in docs:
        job = {**doc.to_dict(), "_id": doc.id}
        break
    if not job:
        # Try by document ID
        doc = db.collection("eval_jobs").document(batch_name).get()
        if doc.exists:
            job = {**doc.to_dict(), "_id": doc.id}
    if not job:
        print(f"  No job found for {batch_name}")
        return

    # Get Drive videos for this batch
    drive_vids_all = get_drive_videos(drive_svc)
    drive_vids = drive_vids_all.get(batch_name, {})

    reqs, added = _build_batch_slides(job, drive_vids, slide_idx, drive_svc)
    if not reqs:
        print(f"  No slides to add for {batch_name}")
        return

    _send_requests(slides_svc, pres_id, reqs)

    existing_batches.append(batch_name)
    _save_config(db, pres_id, existing_batches)

    url = f"https://docs.google.com/presentation/d/{pres_id}/edit"
    print(f"  Appended {added} slides for {batch_name} → {url}")
    return url


def create_presentation(batch_filter=None, force_new=False):
    """Build or rebuild a slides presentation.

    - force_new=True: always creates a fresh presentation
    - batch_filter=None: includes all jobs
    - batch_filter=['BATCH_004']: only those batches (appends to existing)
    """
    slides_svc, drive_svc = get_services()
    db = firestore.Client(project=GCP_PROJECT_ID)

    print("Scanning Drive for video file IDs…")
    all_drive_videos = get_drive_videos(drive_svc)
    print(f"  Found videos in {len(all_drive_videos)} batch folders")

    print("Fetching jobs from Firestore…")
    jobs = fetch_jobs()
    print(f"  Found {len(jobs)} jobs")

    # Decide: create new or append to existing
    if force_new or not batch_filter:
        pres_id = _create_new_presentation(slides_svc, drive_svc, db)
        existing_batches = []
        slide_idx = 1  # after title slide
    else:
        pres_id = _get_or_create_presentation(slides_svc, drive_svc, db)
        cfg = _get_config(db)
        existing_batches = list(cfg.get("batches", []))
        pres = slides_svc.presentations().get(presentationId=pres_id).execute()
        slide_idx = len(pres.get("slides", []))

    all_reqs = []
    added_batches = []

    for job in jobs:
        batch_name = job.get("prompt_id") or job.get("_id", "unknown")

        if batch_filter and batch_name not in batch_filter:
            continue
        if batch_name in existing_batches:
            print(f"  {batch_name}: already in presentation, skipping")
            continue

        drive_vids = all_drive_videos.get(batch_name, {})
        reqs, added = _build_batch_slides(job, drive_vids, slide_idx, drive_svc)
        if reqs:
            all_reqs.extend(reqs)
            slide_idx += added
            added_batches.append(batch_name)

    if not all_reqs:
        print("No new slides to add.")
        url = f"https://docs.google.com/presentation/d/{pres_id}/edit"
        print(f"Open: {url}")
        return url

    print(f"\nSending {len(all_reqs)} API requests ({len(added_batches)} new batches)…")
    _send_requests(slides_svc, pres_id, all_reqs)

    _save_config(db, pres_id, existing_batches + added_batches)

    url = f"https://docs.google.com/presentation/d/{pres_id}/edit"
    print(f"\nDone! Added {len(added_batches)} batches: {', '.join(added_batches)}")
    print(f"Open: {url}")
    return url


if __name__ == "__main__":
    args = sys.argv[1:]
    force_new = "--new" in args
    batches = [a for a in args if not a.startswith("--")] or None
    create_presentation(batch_filter=batches, force_new=force_new)
