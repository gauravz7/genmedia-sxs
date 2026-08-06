"""Core domain models — the execution-centric contract (REFACTOR_PLAN §9).

The **Execution** is the atomic, cached primitive: one ``(case, model, params)``
run, generated at most once. **Comparison**/**Vote** are derived relations that
reference two executions. The judge/arena do not care whether an execution was
generated or ingested (BYOO).

`execution_id()` implements the **no-rerun guarantee**: a deterministic,
content-addressed id so the same (prompt, model, params) never regenerates.
This module is pure (stdlib + pydantic) and fully unit-testable with no I/O.
"""
from __future__ import annotations

import hashlib
import json
from enum import Enum, StrEnum
from typing import Any

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------
UNSEEDED = "unseeded"  # sentinel so an unspecified seed reuses one cached cell


class Modality(StrEnum):
    T2V = "t2v"
    I2V = "i2v"
    R2V = "r2v"
    T2I = "t2i"
    I2I = "i2i"
    TTS = "tts"


class EvalMode(StrEnum):
    ABSOLUTE = "absolute"   # per-execution scores (Core-5 style)
    PAIRWISE = "pairwise"   # derived comparisons + head-to-head
    BOTH = "both"


class ExecStatus(StrEnum):
    PENDING = "pending"
    GENERATING = "generating"
    SUCCESS = "success"
    ERROR = "error"


class VoteSource(StrEnum):
    HUMAN = "human"
    AI = "ai"


# ---------------------------------------------------------------------------
# Prompt / model / suite
# ---------------------------------------------------------------------------
class Case(BaseModel):
    """A single prompt case (one row of a Suite)."""
    id: str
    prompt: str = ""
    modality: Modality = Modality.T2I
    mode: str | None = None                 # e.g. t2i/i2i for image
    language: str | None = None
    categories: list[str] = Field(default_factory=list)
    input_assets: list[str] = Field(default_factory=list)  # i2i/i2v/r2v refs
    params: dict[str, Any] = Field(default_factory=dict)   # aspect_ratio, duration, seed, ...
    customer: str | None = None
    suite_id: str | None = None
    suite_version: str | None = None


class ModelSpec(BaseModel):
    """A registered model. ``model_version`` is REQUIRED for cache correctness:
    an in-place model update must bump it or stale outputs get reused."""
    id: str
    name: str = ""
    provider: str
    model_id: str
    model_version: str = "v1"
    type: str = "t2i"          # t2v/i2v/r2v/t2i/i2i/tts
    is_active: bool = True


class Suite(BaseModel):
    id: str
    version: str = "1.0"
    modality: Modality = Modality.T2I
    description: str = ""
    owner: str = ""
    case_ids: list[str] = Field(default_factory=list)
    content_hash: str | None = None


# ---------------------------------------------------------------------------
# Generation result (provider output) + Execution
# ---------------------------------------------------------------------------
class GenerationResult(BaseModel):
    """Standardized provider output. Latency ALWAYS in seconds (fixes the v2
    seconds-vs-ms drift). This is what a provider returns; it becomes an
    Execution's media + metadata."""
    status: ExecStatus = ExecStatus.SUCCESS
    media_uri: str | None = None
    latency_s: float | None = None
    cost: float | None = None
    width: int | None = None
    height: int | None = None
    duration: float | None = None
    fps: float | None = None
    model_id: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class Execution(BaseModel):
    """One (case, model, params) run — generated once, reused forever."""
    id: str
    suite_id: str | None = None
    suite_version: str | None = None
    case_id: str
    prompt: str = ""
    modality: Modality = Modality.T2I
    mode: str | None = None
    categories: list[str] = Field(default_factory=list)
    language: str | None = None
    model_id: str
    model_version: str = "v1"
    provider: str = ""
    params: dict[str, Any] = Field(default_factory=dict)
    input_assets: list[str] = Field(default_factory=list)
    media_uri: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    content_hash: str | None = None
    absolute_eval: dict[str, Any] | None = None
    status: ExecStatus = ExecStatus.PENDING
    error: str | None = None
    source: str = "generated"          # generated | ingested
    created_at: float = 0.0


class Comparison(BaseModel):
    """Derived head-to-head between two executions of the SAME case."""
    id: str
    case_id: str
    execution_a: str
    execution_b: str
    modality: Modality = Modality.T2I
    ai_verdict: dict[str, Any] | None = None   # winner_execution, scores, ...


class Vote(BaseModel):
    """Human (or AI) verdict referencing two executions."""
    id: str
    case_id: str
    execution_a: str
    execution_b: str
    winner_execution: str | None = None
    scores: dict[str, int] = Field(default_factory=dict)
    justification: str = ""
    source: VoteSource = VoteSource.HUMAN
    ldap: str = "anonymous"
    timestamp: float = 0.0


class Verdict(BaseModel):
    """Normalized judge output (absolute or pairwise)."""
    mode: EvalMode
    winner_execution: str | None = None
    per_execution: dict[str, dict[str, Any]] = Field(default_factory=dict)
    model: str = ""
    raw: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# The no-rerun guarantee — content-addressed execution identity (§9.3)
# ---------------------------------------------------------------------------
def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _norm_prompt(prompt: str | None) -> str:
    """Whitespace/case-insensitive prompt normalization."""
    return " ".join((prompt or "").split()).lower()


def prompt_fingerprint(prompt: str | None, mode: str | None,
                       input_assets: list[str] | None) -> str:
    """Stable identity for 'the prompt' — same across suites; input assets
    (i2i/i2v/r2v source) are part of identity, so editing a different image is
    a different cell."""
    assets = "|".join(sorted(input_assets or []))
    return _sha(f"{_norm_prompt(prompt)}\x1f{mode or ''}\x1f{assets}")


def _json_default(o: Any):
    if isinstance(o, Enum):
        return o.value
    return str(o)


def resolve_params(params: dict[str, Any] | None) -> dict[str, Any]:
    """Canonicalize params for hashing. An unspecified/None seed collapses to
    the UNSEEDED sentinel so re-running a suite reuses one cached execution
    instead of drawing a fresh random generation."""
    p = dict(params or {})
    seed = p.get("seed")
    if seed is None or seed == "":
        p["seed"] = UNSEEDED
    return p


def params_hash(params: dict[str, Any] | None) -> str:
    canon = json.dumps(resolve_params(params), sort_keys=True,
                       separators=(",", ":"), default=_json_default)
    return _sha(canon)


def execution_id(case: Case, spec: ModelSpec,
                 params: dict[str, Any] | None = None) -> str:
    """Deterministic execution id = the idempotency key (§9.3).

    ``exec_<24 hex>`` over (prompt_fingerprint, model_id, model_version,
    params_hash). Same inputs → same id → the datastore's create-if-absent
    yields the no-rerun guarantee.
    """
    fp = prompt_fingerprint(case.prompt, case.mode or case.modality.value, case.input_assets)
    ph = params_hash(params if params is not None else case.params)
    key = f"{fp}|{spec.model_id}|{spec.model_version}|{ph}"
    return "exec_" + _sha(key)[:24]
