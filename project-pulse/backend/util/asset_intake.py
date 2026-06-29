"""Asset intake helpers for the SxS auto-evaluation pipeline.

When a user uploads a `cases.json` along with the image/video files it
references (using LOCAL RELATIVE PATHS such as
`tencent/inputs_highres/x.png`), these helpers:

  1. Persist the uploaded bytes to a temp dir preserving the relative tree.
  2. Push every file to GCS under `sxs_assets/{batch_id}/{relpath}`.
  3. Rewrite each case's `reference_images` / `reference_videos` so the local
     relative paths become GCS https URLs.

Dependency-light on purpose (os, shutil, tempfile, typing).
"""

import os
import shutil
import tempfile
from typing import Any, Dict, List

from util.gcs_utils import upload_from_path


def save_uploads_to_temp(files: list) -> str:
    """Write a list of uploaded files to a fresh temp dir.

    Each element of `files` must expose:
      - `.filename`: relative path (may contain slashes / subdirs)
      - `.bytes`: raw file bytes

    The relative sub-directory structure is preserved. Returns the temp base
    directory that all files were written under.
    """
    base_dir = tempfile.mkdtemp(prefix="sxs_intake_")

    for f in files:
        filename = getattr(f, "filename", None)
        data = getattr(f, "bytes", None)
        if not filename or data is None:
            continue

        # Normalize the relative path; strip any leading separators and guard
        # against path-traversal escaping the base dir.
        rel = str(filename).replace("\\", "/").lstrip("/")
        dest = os.path.normpath(os.path.join(base_dir, rel))
        if not dest.startswith(os.path.abspath(base_dir) + os.sep) and dest != os.path.abspath(base_dir):
            # normpath may not be absolute; re-anchor under base_dir by basename
            dest = os.path.join(base_dir, os.path.basename(rel))

        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as out:
            out.write(data)

    return base_dir


def upload_assets_to_gcs(base_dir: str, batch_id: str) -> dict:
    """Walk `base_dir`, upload every file to GCS, return {relpath -> https_url}.

    Files land at `sxs_assets/{batch_id}/{relpath}` where `relpath` is the path
    relative to `base_dir` (forward-slash normalized).
    """
    relpath_to_url: Dict[str, str] = {}

    for root, _dirs, filenames in os.walk(base_dir):
        for name in filenames:
            local_path = os.path.join(root, name)
            relpath = os.path.relpath(local_path, base_dir).replace("\\", "/")
            destination = f"sxs_assets/{batch_id}/{relpath}"
            try:
                url = upload_from_path(local_path, destination)
                relpath_to_url[relpath] = url
            except Exception as e:  # pragma: no cover - surfaced to caller log
                print(f"[asset_intake] Failed to upload {relpath}: {e}")

    return relpath_to_url


def _is_url(value: Any) -> bool:
    return isinstance(value, str) and (
        value.startswith("http://")
        or value.startswith("https://")
        or value.startswith("gs://")
    )


def _resolve_key(ref: str, relpath_to_url: Dict[str, str]) -> str:
    """Find the uploaded URL for a JSON reference path, tolerating a prepended
    top-level folder.

    The browser folder picker prepends the *selected* directory's name to every
    file's relative path (e.g. selecting `Video Evals` yields
    `Video Evals/tencent/inputs/x.png`), while the JSON references the path
    *without* that prefix (`tencent/inputs/x.png`). We therefore match in order:

      1. exact relpath
      2. an uploaded relpath that ends with `/<ref>` (prefix tolerance)
      3. the ref ends with `/<uploaded>` (reverse tolerance)
      4. unique basename match (last resort)
    """
    key = ref.replace("\\", "/").lstrip("/")
    if key in relpath_to_url:
        return relpath_to_url[key]

    # Suffix match: uploaded path ends with the ref (handles prepended root).
    suffix = "/" + key
    suffix_hits = [u for rp, u in relpath_to_url.items() if rp.endswith(suffix)]
    if len(suffix_hits) == 1:
        return suffix_hits[0]
    if suffix_hits:
        # Multiple matches across client folders — prefer the shortest relpath.
        best = min(
            ((rp, u) for rp, u in relpath_to_url.items() if rp.endswith(suffix)),
            key=lambda kv: len(kv[0]),
        )
        return best[1]

    # Reverse: ref includes an extra leading segment vs the upload.
    rev_hits = [u for rp, u in relpath_to_url.items() if key.endswith("/" + rp)]
    if len(rev_hits) == 1:
        return rev_hits[0]

    # Last resort: unique basename match.
    base = key.rsplit("/", 1)[-1]
    base_hits = [u for rp, u in relpath_to_url.items() if rp.rsplit("/", 1)[-1] == base]
    if len(base_hits) == 1:
        return base_hits[0]

    return ""


def _rewrite_list(entries: Any, relpath_to_url: Dict[str, str]) -> List[str]:
    """Map relative-path entries to their GCS URLs.

    - Already-URL entries (http/https/gs) pass through untouched.
    - Entries resolvable to an uploaded file are replaced by the mapped URL
      (suffix-tolerant — see `_resolve_key`).
    - Entries that are neither a URL nor resolvable are dropped.
    """
    out: List[str] = []
    if not entries:
        return out
    if not isinstance(entries, (list, tuple)):
        entries = [entries]

    for entry in entries:
        if _is_url(entry):
            out.append(entry)
            continue
        if not isinstance(entry, str):
            continue
        resolved = _resolve_key(entry, relpath_to_url)
        if resolved:
            out.append(resolved)
        # else: no mapping and not a URL -> drop
    return out


def rewrite_case_assets(case: dict, relpath_to_url: dict) -> dict:
    """Return a shallow copy of `case` with reference assets rewritten to URLs."""
    new_case = dict(case)
    new_case["reference_images"] = _rewrite_list(
        case.get("reference_images"), relpath_to_url
    )
    new_case["reference_videos"] = _rewrite_list(
        case.get("reference_videos"), relpath_to_url
    )
    return new_case
