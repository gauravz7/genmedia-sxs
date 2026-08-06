"""Compare service — server-side blind pair selection for human SxS voting.

The manual-judgment flow must be *blind*: a voter sees two media outputs and the
shared prompt, but never which model produced which side. Two facts make this
safe to serve from the execution store directly:

* an ``execution_id`` is a ``sha256`` content hash — it does not reveal the model;
* but a GCS object path *does* embed the provider (``tts_gemini_…``, ``omni_…``),
  so the raw ``gs://`` URI (and any signed/proxied URL that contains it) must
  never reach the client.

So :meth:`pick_pair` returns opaque execution ids plus blind media refs that
resolve through ``/api/compare/media`` (which streams bytes without exposing the
path). Model identities are only disclosed by :meth:`reveal`, i.e. after voting.
"""
from __future__ import annotations

import random
from collections import defaultdict
from typing import Any


def _blind_media_ref(execution_id: str) -> str:
    """A client-safe media URL that hides the underlying ``gs://`` path."""
    return f"/api/compare/media?execution_id={execution_id}"


class ComparePairService:
    """Selects blind head-to-head pairs from successful executions."""

    def __init__(self, exec_repo: Any, rng: random.Random | None = None) -> None:
        self.exec_repo = exec_repo
        self._rng = rng or random.Random()

    # -- selection --------------------------------------------------------
    def _eligible_by_case(
        self, modality: str | None, tag: str | None
    ) -> dict[str, list[dict]]:
        """Successful, media-bearing executions grouped by case, keeping only
        cases that have ≥2 *distinct-model* outputs (a real matchup)."""
        by_case: dict[str, list[dict]] = defaultdict(list)
        for e in self.exec_repo.stream():
            if e.get("status") != "success" or not e.get("media_uri"):
                continue
            if modality and str(e.get("modality")) != str(modality):
                continue
            if tag and tag not in [str(c) for c in (e.get("categories") or [])]:
                continue
            by_case[e.get("case_id")].append(e)
        return {
            cid: lst for cid, lst in by_case.items()
            if cid and len({x.get("model_id") for x in lst}) >= 2
        }

    def pick_pair(
        self,
        modality: str | None = None,
        tag: str | None = None,
        case_id: str | None = None,
    ) -> dict | None:
        """Return one blind pair (or ``None`` if nothing is eligible).

        The response carries opaque execution ids + blind media refs + the shared
        prompt, but NO ``model_id``/``provider``. A/B order is randomized so the
        two sides carry no positional signal."""
        eligible = self._eligible_by_case(modality, tag)
        if not eligible:
            return None

        cid = case_id if case_id in eligible else self._rng.choice(list(eligible))
        by_model: dict[str, list[dict]] = defaultdict(list)
        for e in eligible[cid]:
            by_model[e.get("model_id")].append(e)

        m1, m2 = self._rng.sample(list(by_model), 2)
        ea = self._rng.choice(by_model[m1])
        eb = self._rng.choice(by_model[m2])
        sides = [ea, eb]
        self._rng.shuffle(sides)
        a, b = sides

        prompt = a.get("prompt") or b.get("prompt") or ""
        return {
            "case_id": cid,
            "modality": str(a.get("modality")),
            "prompt": prompt,
            "language": a.get("language"),
            "remaining_cases": len(eligible),
            "side_a": {"execution_id": a["id"], "media": _blind_media_ref(a["id"])},
            "side_b": {"execution_id": b["id"], "media": _blind_media_ref(b["id"])},
        }

    # -- reveal (post-vote) ----------------------------------------------
    def reveal(self, *execution_ids: str) -> dict:
        """Disclose model identities for the given executions — call only after
        the voter has committed a choice."""
        out: dict[str, dict] = {}
        for eid in execution_ids:
            e = self.exec_repo.get(eid)
            if e is None:
                out[eid] = {"found": False}
                continue
            out[eid] = {
                "found": True,
                "model_id": e.get("model_id"),
                "provider": e.get("provider"),
                "model_version": e.get("model_version"),
            }
        return out

    def media_uri_of(self, execution_id: str) -> str | None:
        """The ``gs://`` URI for a blind side — used only server-side by the
        media proxy; never returned in a pair/reveal payload."""
        e = self.exec_repo.get(execution_id)
        return e.get("media_uri") if e else None
