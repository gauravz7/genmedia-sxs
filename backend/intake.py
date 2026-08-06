"""Bring-your-own-outputs (BYOO) ingest.

When a customer has already generated the media, there is nothing to run — we
just need it to show up in the blind duel and the analytics like any other job.
This module rehosts the supplied URLs into our bucket and writes a job doc in
each modality's native shape, with `results` pre-populated as successful.

The AI judge needs no special handling: `run_auto_eval`, `run_image_evaluation`
and `run_tts_evaluation` all read the job doc back from Firestore and never
touch a generator, so an ingested job is judged exactly like a generated one.

Two invariants make an ingested job visible to the rest of the platform:
  - `source: "sxs_auto"` — every list/pair endpoint filters on it.
  - media lives in OUR bucket — the judge and the `/api/media` proxy both read
    through GCS, and third-party links expire.

Generalizes the one-off `load_v2v_bench.py` import script (now archived under
`archive/backend/scripts/`).
"""

import mimetypes
import os
import time
from typing import Dict, List, Optional, Tuple

import requests

from util.gcs_utils import download_blob_to_bytes, upload_from_bytes

GCS_BUCKET_NAME = os.getenv("GCS_BUCKET_NAME", "project-pulse")

# Fallback content types per modality, used when neither the URL extension nor
# the HTTP response identifies the media.
_DEFAULT_CONTENT_TYPE = {
    "video": "video/mp4",
    "image": "image/png",
    "tts": "audio/mpeg",
}
_DEFAULT_EXT = {"video": ".mp4", "image": ".png", "tts": ".mp3"}
_DEST_PREFIX = {"video": "sxs/ingest", "image": "images/ingest", "tts": "audio/ingest"}


class IngestError(Exception):
    """A case could not be ingested. Reported per-row; never aborts a batch."""


# --- URL handling -----------------------------------------------------------

def _is_gcs(url: str) -> bool:
    return url.startswith("gs://") or "storage.googleapis.com" in url


def _in_our_bucket(url: str) -> bool:
    return (
        url.startswith(f"gs://{GCS_BUCKET_NAME}/")
        or f"storage.googleapis.com/{GCS_BUCKET_NAME}/" in url
        or f"{GCS_BUCKET_NAME}.storage.googleapis.com/" in url
    )


def _ext_of(url: str, modality: str) -> str:
    path = url.split("?")[0]
    _, ext = os.path.splitext(path)
    return ext.lower() if 1 < len(ext) <= 5 else _DEFAULT_EXT[modality]


def _content_type(url: str, modality: str, header: Optional[str] = None) -> str:
    if header and "/" in header and not header.startswith("application/octet-stream"):
        return header.split(";")[0].strip()
    guessed, _ = mimetypes.guess_type(url.split("?")[0])
    return guessed or _DEFAULT_CONTENT_TYPE[modality]


def rehost(url: str, modality: str, dest_name: str, timeout: int = 300) -> str:
    """Copy a customer-supplied URL into our bucket and return the GCS URL.

    A URL already in our bucket is returned untouched — no pointless copy. Any
    other source (another GCS bucket, a signed link, a CDN) is downloaded and
    re-uploaded so the media outlives the customer's link.
    """
    url = (url or "").strip()
    if not url:
        raise IngestError("empty output URL")
    if _in_our_bucket(url):
        return url

    dest = f"{_DEST_PREFIX[modality]}/{dest_name}{_ext_of(url, modality)}"
    try:
        if _is_gcs(url):
            content = download_blob_to_bytes(url)
            ctype = _content_type(url, modality)
        elif url.startswith("http://") or url.startswith("https://"):
            resp = requests.get(url, timeout=timeout)
            resp.raise_for_status()
            content = resp.content
            ctype = _content_type(url, modality, resp.headers.get("content-type"))
        else:
            raise IngestError(f"unsupported URL scheme: {url[:60]}")
    except IngestError:
        raise
    except Exception as e:
        raise IngestError(f"could not fetch {url[:80]}: {e}") from e

    if not content:
        raise IngestError(f"{url[:80]} returned no bytes")
    return upload_from_bytes(content, dest, content_type=ctype)


def _rehost_refs(urls: List[str], modality: str, slug: str, kind: str) -> List[str]:
    """Rehost reference/input assets. The judge downloads these from GCS, so a
    third-party link would make the case unjudgeable."""
    out = []
    for i, u in enumerate(urls):
        out.append(rehost(u, modality, f"{slug}__{kind}{i}_{int(time.time()*1000)}"))
    return out


# --- outputs manifest -------------------------------------------------------

def parse_outputs(case: dict) -> Dict[str, dict]:
    """Normalize a case's `outputs` into {model_id: {url, latency_ms, metadata}}.

    Accepts the shorthand `{"model-id": "https://..."}` as well as the full
    object form.
    """
    raw = case.get("outputs") or case.get("results")
    if not isinstance(raw, dict) or not raw:
        raise IngestError("case has no `outputs` object")
    out: Dict[str, dict] = {}
    for model_id, val in raw.items():
        if isinstance(val, str):
            val = {"url": val}
        if not isinstance(val, dict) or not (val.get("url") or "").strip():
            raise IngestError(f"output for '{model_id}' has no url")
        out[str(model_id)] = {
            "url": val["url"].strip(),
            "latency_ms": val.get("latency_ms") or val.get("latency"),
            "metadata": val.get("metadata") or {},
        }
    return out


def _result_doc(model_label: str, url: str, ref: dict, **extra) -> dict:
    """A pre-populated success result, matching what a generator would write."""
    res = {
        "status": "success",
        "model": model_label,
        "url": url,
        "gcs_url": url,
        "result": {"url": url},
        "error": None,
        "ingested": True,
    }
    if ref.get("latency_ms") is not None:
        res["latency_ms"] = ref["latency_ms"]
    if ref.get("metadata"):
        res["metadata"] = ref["metadata"]
    res.update(extra)
    return res


# --- per-modality ingest ----------------------------------------------------

def _ingest_video(case: dict, specs: List, outputs: Dict[str, dict],
                  batch_id: Optional[str], source_label: str) -> Tuple[str, dict]:
    from sxs_pipeline import EVAL_COLLECTION, _modality, _ref_list, _slug

    case_id = case.get("id", "case")
    slug = _slug(case_id)
    job_id = f"ing_{slug}_{int(time.time()*1000)}"
    by_id = {s.id: s for s in specs}

    results = {}
    for model_id, ref in outputs.items():
        gcs = rehost(ref["url"], "video", f"{slug}__{_slug(model_id)}_{int(time.time()*1000)}")
        results[model_id] = _result_doc(by_id[model_id].name or model_id, gcs, ref)

    doc = {
        "id": job_id,
        "source": "sxs_auto",
        "origin": "ingest",
        "imported_from": source_label,
        "batch_id": batch_id,
        "customer": case.get("customer", ""),
        "prompt_id": case_id,
        "prompt": case.get("prompt", ""),
        "categories": _categories(case),
        "ratio": case.get("aspect_ratio") or case.get("ratio") or "16:9",
        "modality": _modality(case),
        "duration": case.get("duration"),
        "reference_images": _rehost_refs(_ref_list(case, "reference_images"), "video", slug, "refimg"),
        "reference_videos": _rehost_refs(_ref_list(case, "reference_videos"), "video", slug, "refvid"),
        "timestamp": time.time(),
        "results": results,
        "auto_eval_status": "pending",
    }
    return EVAL_COLLECTION, doc


def _ingest_image(case: dict, specs: List, outputs: Dict[str, dict],
                  batch_id: Optional[str], source_label: str) -> Tuple[str, dict]:
    from image_pipeline import IMAGE_COLLECTION, build_image_job_doc, _input_image, _slug
    from model_resolver import image_side_from_spec

    slug = _slug(case.get("id", "case"))
    by_id = {s.id: s for s in specs}
    model_ids = list(outputs.keys())

    # Rehost the i2i source image too — the judge reads it back out of GCS.
    src = _input_image(case)
    if src:
        case = dict(case)
        case["input_image"] = rehost(src, "image", f"{slug}__input_{int(time.time()*1000)}")
        case.pop("reference_image", None)
        case.pop("input_images", None)

    by_engine = {}
    for model_id in model_ids:
        ref = outputs[model_id]
        gcs = rehost(ref["url"], "image", f"{slug}__{_slug(model_id)}_{int(time.time()*1000)}")
        by_engine[model_id] = _result_doc(by_id[model_id].name or model_id, gcs, ref,
                                          engine=model_id)

    sides = [image_side_from_spec(by_id[m]) for m in model_ids]
    doc = build_image_job_doc(
        case, sides[0], sides[1], batch_id=batch_id,
        extra={"origin": "ingest", "imported_from": source_label},
    )
    # build_image_job_doc randomizes A/B, so results can only be labelled after.
    doc["results"] = {label: by_engine[doc["side_map"][label]] for label in ("A", "B")}
    return IMAGE_COLLECTION, doc


def _ingest_tts(case: dict, specs: List, outputs: Dict[str, dict],
                batch_id: Optional[str], source_label: str) -> Tuple[str, dict]:
    from tts_pipeline import TTS_COLLECTION, build_tts_job_doc, _slug

    slug = _slug(case.get("id", "case"))
    by_id = {s.id: s for s in specs}
    engines = list(outputs.keys())

    by_engine = {}
    for engine in engines:
        ref = outputs[engine]
        gcs = rehost(ref["url"], "tts", f"{slug}__{_slug(engine)}_{int(time.time()*1000)}")
        by_engine[engine] = _result_doc(by_id[engine].name or engine, gcs, ref, engine=engine)

    doc = build_tts_job_doc(
        case, engines, batch_id=batch_id,
        extra={"origin": "ingest", "imported_from": source_label},
    )
    doc["results"] = {label: by_engine[doc["side_map"][label]] for label in ("A", "B")}
    return TTS_COLLECTION, doc


_INGEST = {"video": _ingest_video, "image": _ingest_image, "tts": _ingest_tts}


def _categories(case: dict) -> List[str]:
    raw = case.get("categories") or case.get("tags") or case.get("category") or []
    if isinstance(raw, str):
        raw = [raw]
    return [str(c).strip() for c in raw if str(c).strip()]


def ingest_case(
    modality: str,
    case: dict,
    specs: List,
    batch_id: Optional[str] = None,
    run_eval: bool = True,
    source_label: str = "api ingest",
) -> str:
    """Rehost one case's outputs and write its job doc. Returns the job_id.

    `specs` are the already-resolved `RegisteredModel`s for the case's output
    keys (the caller validates them so a whole batch fails fast on a bad model
    name). Raises IngestError on anything wrong with this one case.
    """
    outputs = parse_outputs(case)
    fn = _INGEST.get(modality)
    if fn is None:
        raise IngestError(f"unknown modality '{modality}'")

    collection, doc = fn(case, specs, outputs, batch_id, source_label)
    # The judge is queued by the caller; mark it skipped up front otherwise, so
    # the doc never sits at a permanent "pending" nobody will ever clear.
    doc["auto_eval_status"] = "pending" if run_eval else "skipped"

    from sxs_pipeline import _get_firestore_client
    _get_firestore_client().collection(collection).document(doc["id"]).set(doc)
    return doc["id"]


def run_eval_for(modality: str, job_id: str) -> None:
    """Run the modality's AI judge on an ingested job. Safe to hand to
    BackgroundTasks — failures are recorded on the doc, not raised."""
    try:
        if modality == "video":
            from sxs_pipeline import run_auto_eval
            run_auto_eval(job_id)
        elif modality == "image":
            from image_evaluator import run_image_evaluation
            run_image_evaluation(job_id)
        elif modality == "tts":
            from tts_evaluator import run_tts_evaluation
            run_tts_evaluation(job_id)
    except Exception as e:  # pragma: no cover
        print(f"[intake] {modality} eval failed for {job_id}: {e}")
