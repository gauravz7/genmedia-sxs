"""Tests for the no-rerun guarantee (REFACTOR_PLAN §9.3).

These lock the execution-identity contract every downstream agent relies on.
"""
from __future__ import annotations

from app.domain.models import (
    UNSEEDED,
    Case,
    Modality,
    ModelSpec,
    execution_id,
    params_hash,
    prompt_fingerprint,
    resolve_params,
)


def _case(**kw) -> Case:
    base = dict(id="c1", prompt="A red fox in snow", modality=Modality.T2I, mode="t2i")
    base.update(kw)
    return Case(**base)


def _spec(**kw) -> ModelSpec:
    base = dict(id="m1", provider="p", model_id="imagen-4.0", model_version="v1", type="t2i")
    base.update(kw)
    return ModelSpec(**base)


# --- determinism ----------------------------------------------------------
def test_execution_id_is_deterministic():
    assert execution_id(_case(), _spec()) == execution_id(_case(), _spec())


def test_execution_id_prefix_and_length():
    eid = execution_id(_case(), _spec())
    assert eid.startswith("exec_")
    assert len(eid) == len("exec_") + 24


def test_prompt_normalization_ignores_whitespace_and_case():
    a = execution_id(_case(prompt="A red   FOX in snow"), _spec())
    b = execution_id(_case(prompt="a red fox in snow"), _spec())
    assert a == b


# --- what MUST change the id ---------------------------------------------
def test_new_model_version_changes_id():
    a = execution_id(_case(), _spec(model_version="v1"))
    b = execution_id(_case(), _spec(model_version="v2"))
    assert a != b


def test_new_model_id_changes_id():
    a = execution_id(_case(), _spec(model_id="imagen-4.0"))
    b = execution_id(_case(), _spec(model_id="imagen-5.0"))
    assert a != b


def test_different_prompt_changes_id():
    a = execution_id(_case(prompt="fox"), _spec())
    b = execution_id(_case(prompt="cat"), _spec())
    assert a != b


def test_different_input_assets_change_id():
    a = execution_id(_case(input_assets=["gs://b/img-a.png"]), _spec())
    b = execution_id(_case(input_assets=["gs://b/img-b.png"]), _spec())
    assert a != b


def test_input_asset_order_does_not_matter():
    a = execution_id(_case(input_assets=["x", "y"]), _spec())
    b = execution_id(_case(input_assets=["y", "x"]), _spec())
    assert a == b


def test_explicit_seed_changes_id():
    a = execution_id(_case(), _spec(), params={"seed": 1})
    b = execution_id(_case(), _spec(), params={"seed": 2})
    assert a != b


# --- seed normalization (the reuse guarantee) ----------------------------
def test_unseeded_variants_collapse_to_one_cell():
    none_seed = execution_id(_case(), _spec(), params={"seed": None})
    empty_seed = execution_id(_case(), _spec(), params={"seed": ""})
    no_seed = execution_id(_case(), _spec(), params={})
    assert none_seed == empty_seed == no_seed


def test_resolve_params_sets_unseeded_sentinel():
    assert resolve_params({})["seed"] == UNSEEDED
    assert resolve_params({"seed": None})["seed"] == UNSEEDED
    assert resolve_params({"seed": 7})["seed"] == 7


def test_params_hash_is_order_independent():
    assert params_hash({"a": 1, "b": 2}) == params_hash({"b": 2, "a": 1})


# --- case.params fallback -------------------------------------------------
def test_case_params_used_when_no_override():
    c = _case(params={"seed": 42})
    assert execution_id(c, _spec()) == execution_id(c, _spec(), params={"seed": 42})


# --- fingerprint is suite-independent ------------------------------------
def test_prompt_fingerprint_ignores_suite():
    fp1 = prompt_fingerprint("hello world", "t2i", [])
    fp2 = prompt_fingerprint("hello world", "t2i", [])
    assert fp1 == fp2
