"""Tests for AnalyticsService + pure helpers (wilson, is_google_engine, Elo, BT)."""
from __future__ import annotations

import pytest

from app.infra.repositories import (
    ComparisonRepository,
    ExecutionRepository,
    VoteRepository,
)
from app.services.analytics import AnalyticsService, is_google_engine, wilson


# --- wilson known values ---------------------------------------------------
def test_wilson_zero_is_safe():
    assert wilson(0, 0) == (0.0, 0.0, 0.0)


def test_wilson_one_of_one():
    p, lo, hi = wilson(1, 1)
    assert p == 1.0
    assert lo == pytest.approx(0.2065, abs=1e-3)
    assert hi == 1.0


def test_wilson_mid_case():
    p, lo, hi = wilson(5, 10)
    assert p == 0.5
    assert lo == pytest.approx(0.2366, abs=1e-3)
    assert hi == pytest.approx(0.7634, abs=1e-3)


def test_wilson_matches_v2_ordering_note():
    # v2 returned (low, p, high); v3 returns (p, low, high) with same numbers.
    p, lo, hi = wilson(8, 10)
    assert lo < p < hi


# --- is_google_engine ------------------------------------------------------
@pytest.mark.parametrize("name", [
    "gemini-3-pro", "imagen-4.0", "veo-3", "omni-flash", "nano-banana",
    "banana", "doubao-google", "GEMINI", "Imagen",
])
def test_is_google_engine_true(name):
    assert is_google_engine(name) is True


@pytest.mark.parametrize("name", [
    "kling-2.0", "seedance", "gpt-image-2", "elevenlabs", "grok", "", None,
])
def test_is_google_engine_false(name):
    assert is_google_engine(name) is False


# --- fixtures for service ---------------------------------------------------
def _repos(store):
    return (
        ExecutionRepository(store, "executions"),
        VoteRepository(store, "votes"),
        ComparisonRepository(store, "comparisons"),
    )


def _svc(store) -> AnalyticsService:
    ex, vt, cmp = _repos(store)
    return AnalyticsService(ex, vt, cmp)


def _seed_two_models(store):
    ex = ExecutionRepository(store, "executions")
    ex.reserve({"id": "exG", "case_id": "c1", "model_id": "gemini-2.5",
                "categories": ["animals"], "language": "en", "modality": "t2i",
                "status": "success"})
    ex.reserve({"id": "exC", "case_id": "c1", "model_id": "kling-2.0",
                "categories": ["animals"], "language": "en", "modality": "t2i",
                "status": "success"})


# --- win_map ---------------------------------------------------------------
def test_win_map_google_vs_competitor(store):
    _seed_two_models(store)
    cmp = ComparisonRepository(store, "comparisons")
    for i in range(4):
        cmp.create_if_absent(f"cmp{i}", {
            "id": f"cmp{i}", "case_id": "c1", "execution_a": "exG",
            "execution_b": "exC", "modality": "t2i",
            "ai_verdict": {"winner_execution": "exG"},
        })
    out = _svc(store).win_map(min_n=1)
    assert out["overall"]["win_rate"] == 100.0
    assert out["overall"]["n"] == 4
    assert any(s["segment"] == "animals" for s in out["by_category"])
    assert out["leads"], "a 4/4 google sweep should register as a lead"


def test_win_map_ignores_google_vs_google(store):
    ex = ExecutionRepository(store, "executions")
    ex.reserve({"id": "g1", "case_id": "c1", "model_id": "gemini-2.5",
                "modality": "t2i", "status": "success"})
    ex.reserve({"id": "g2", "case_id": "c1", "model_id": "imagen-4.0",
                "modality": "t2i", "status": "success"})
    cmp = ComparisonRepository(store, "comparisons")
    cmp.create_if_absent("cmp1", {"id": "cmp1", "case_id": "c1", "execution_a": "g1",
                                  "execution_b": "g2", "modality": "t2i",
                                  "ai_verdict": {"winner_execution": "g1"}})
    out = _svc(store).win_map(min_n=1)
    assert out["overall"]["n"] == 0  # not a google-vs-competitor pair


# --- agreement -------------------------------------------------------------
def test_agreement_human_vs_ai(store):
    _seed_two_models(store)
    cmp = ComparisonRepository(store, "comparisons")
    cmp.create_if_absent("cmp1", {"id": "cmp1", "case_id": "c1", "execution_a": "exG",
                                  "execution_b": "exC", "modality": "t2i",
                                  "ai_verdict": {"winner_execution": "exG"}})
    vt = VoteRepository(store, "votes")
    vt.add({"id": "v1", "case_id": "c1", "execution_a": "exG", "execution_b": "exC",
            "winner_execution": "exG"})  # agree
    vt.add({"id": "v2", "case_id": "c1", "execution_a": "exG", "execution_b": "exC",
            "winner_execution": "exC"})  # disagree
    out = _svc(store).agreement()
    assert out["overall"]["n"] == 2
    assert out["overall"]["agree"] == 1
    assert out["overall"]["pct"] == 50.0
    assert out["t2i"]["n"] == 2


# --- elo / bradley-terry ---------------------------------------------------
def _seed_winner_loser(store, n_wins=12):
    ex = ExecutionRepository(store, "executions")
    ex.reserve({"id": "exW", "case_id": "c1", "model_id": "gemini-win",
                "status": "success"})
    ex.reserve({"id": "exL", "case_id": "c1", "model_id": "kling-lose",
                "status": "success"})
    return [
        {"id": f"v{i}", "execution_a": "exW", "execution_b": "exL",
         "winner_execution": "exW"}
        for i in range(n_wins)
    ]


def test_elo_ranks_clear_winner_above_loser(store):
    votes = _seed_winner_loser(store)
    elo = _svc(store).elo_rankings(votes)
    assert elo["gemini-win"] > elo["kling-lose"]
    # deterministic
    assert _svc(store).elo_rankings(votes) == elo
    # ranking order (dict is sorted desc)
    assert list(elo)[0] == "gemini-win"


def test_bradley_terry_ranks_clear_winner_above_loser(store):
    votes = _seed_winner_loser(store)
    bt = _svc(store).bradley_terry(votes)
    assert bt["gemini-win"] > bt["kling-lose"]
    assert sum(bt.values()) == pytest.approx(1.0, abs=1e-6)
    # deterministic
    assert _svc(store).bradley_terry(votes) == bt


# --- latency ---------------------------------------------------------------
def test_latency_averages_per_model(store):
    ex = ExecutionRepository(store, "executions")
    ex.reserve({"id": "e1", "case_id": "c1", "model_id": "veo-3", "modality": "t2v",
                "status": "success", "latency_s": 10.0})
    ex.reserve({"id": "e2", "case_id": "c2", "model_id": "veo-3", "modality": "t2v",
                "status": "success", "latency_s": 20.0})
    # latency nested in metadata is still picked up
    ex.reserve({"id": "e3", "case_id": "c3", "model_id": "kling", "modality": "t2v",
                "status": "success", "metadata": {"latency_s": 5.0}})
    # failed + no-latency executions are ignored
    ex.reserve({"id": "e4", "case_id": "c4", "model_id": "veo-3", "modality": "t2v",
                "status": "error", "latency_s": 99.0})
    out = _svc(store).latency()
    rows = {r["model"]: r for r in out["rows"]}
    assert rows["veo-3"]["avg_latency_s"] == 15.0
    assert rows["veo-3"]["samples"] == 2
    assert rows["kling"]["avg_latency_s"] == 5.0


# --- stats -----------------------------------------------------------------
def _seed_vote_pair(store):
    ex = ExecutionRepository(store, "executions")
    ex.reserve({"id": "exG", "case_id": "c1", "model_id": "gemini-2.5",
                "categories": ["animals"], "modality": "t2i", "status": "success",
                "latency_s": 8.0})
    ex.reserve({"id": "exC", "case_id": "c1", "model_id": "kling-2.0",
                "categories": ["animals"], "modality": "t2i", "status": "success",
                "latency_s": 12.0})


def test_stats_win_rate_and_tag_matrix(store):
    _seed_vote_pair(store)
    vt = VoteRepository(store, "votes")
    vt.add({"id": "v1", "case_id": "c1", "execution_a": "exG", "execution_b": "exC",
            "winner_execution": "exG", "ldap": "u1"})
    vt.add({"id": "v2", "case_id": "c1", "execution_a": "exG", "execution_b": "exC",
            "winner_execution": "exG", "ldap": "u2"})
    out = _svc(store).stats()
    assert out["total_evals"] == 2
    skus = {s["model_id"]: s for s in out["skus"]}
    assert skus["gemini-2.5"]["win_rate"] == 100.0
    assert skus["gemini-2.5"]["latency_s"] == 8.0
    assert skus["kling-2.0"]["win_rate"] == 0.0
    tags = {t["tag"]: t for t in out["by_tag"]}
    assert tags["animals"]["votes"] == 2


def test_stats_tie_credits_both(store):
    _seed_vote_pair(store)
    vt = VoteRepository(store, "votes")
    vt.add({"id": "v1", "case_id": "c1", "execution_a": "exG", "execution_b": "exC",
            "winner_execution": None, "ldap": "u1"})  # tie
    out = _svc(store).stats()
    skus = {s["model_id"]: s for s in out["skus"]}
    assert skus["gemini-2.5"]["win_rate"] == 100.0  # tie credits both (v2 sxs)
    assert skus["kling-2.0"]["win_rate"] == 100.0


def test_stats_radar_from_ai_verdict(store):
    _seed_vote_pair(store)
    vt = VoteRepository(store, "votes")
    vt.add({"id": "v1", "case_id": "c1", "execution_a": "exG", "execution_b": "exC",
            "winner_execution": "exG"})
    cmp = ComparisonRepository(store, "comparisons")
    cmp.create_if_absent("cmp1", {"id": "cmp1", "case_id": "c1", "execution_a": "exG",
                                  "execution_b": "exC", "modality": "t2i",
                                  "ai_verdict": {"winner_execution": "exG",
                                                 "per_execution": {
                                                     "exG": {"prompt_adherence": 5,
                                                             "aesthetics": 4},
                                                     "exC": {"prompt_adherence": 2}}}})
    out = _svc(store).stats()
    skus = {s["model_id"]: s for s in out["skus"]}
    assert skus["gemini-2.5"]["scores"]["prompt_adherence"] == 5.0
    assert skus["gemini-2.5"]["scores"]["aesthetics"] == 4.0
    assert skus["kling-2.0"]["scores"]["prompt_adherence"] == 2.0


def test_stats_modality_filter(store):
    _seed_vote_pair(store)
    ex = ExecutionRepository(store, "executions")
    ex.reserve({"id": "vA", "case_id": "c2", "model_id": "veo", "modality": "t2v",
                "status": "success"})
    ex.reserve({"id": "vB", "case_id": "c2", "model_id": "kling", "modality": "t2v",
                "status": "success"})
    vt = VoteRepository(store, "votes")
    vt.add({"id": "v1", "case_id": "c1", "execution_a": "exG", "execution_b": "exC",
            "winner_execution": "exG"})
    vt.add({"id": "v2", "case_id": "c2", "execution_a": "vA", "execution_b": "vB",
            "winner_execution": "vA"})
    assert _svc(store).stats(modality="t2i")["total_evals"] == 1
    assert _svc(store).stats(modality="t2v")["total_evals"] == 1


# --- voter leaderboard -----------------------------------------------------
def test_voter_leaderboard_excludes_one_sided_blind_voter(store):
    ex = ExecutionRepository(store, "executions")
    ex.reserve({"id": "a", "case_id": "c1", "model_id": "m1", "modality": "t2i",
                "status": "success"})
    ex.reserve({"id": "b", "case_id": "c1", "model_id": "m2", "modality": "t2i",
                "status": "success"})
    vt = VoteRepository(store, "votes")
    # gamer always picks side A (6 decisive, 100% one-sided) -> excluded
    for i in range(6):
        vt.add({"id": f"g{i}", "case_id": "c1", "execution_a": "a",
                "execution_b": "b", "winner_execution": "a", "ldap": "gamer"})
    # honest voter splits picks -> kept
    vt.add({"id": "h1", "case_id": "c1", "execution_a": "a", "execution_b": "b",
            "winner_execution": "a", "ldap": "honest"})
    vt.add({"id": "h2", "case_id": "c1", "execution_a": "a", "execution_b": "b",
            "winner_execution": "b", "ldap": "honest"})
    out = _svc(store).voter_leaderboard()
    kept = {r["ldap"] for r in out["overall"]}
    assert "honest" in kept
    assert "gamer" not in kept
    assert any(e["ldap"] == "gamer" for e in out["excluded"])
    # honest voter's picks are grouped under the image modality
    assert out["by_modality"]["image"][0]["ldap"] == "honest"


def test_voter_leaderboard_skips_anonymous(store):
    vt = VoteRepository(store, "votes")
    vt.add({"id": "v1", "execution_a": "a", "execution_b": "b",
            "winner_execution": "a", "ldap": "anonymous"})
    out = _svc(store).voter_leaderboard()
    assert out["overall"] == []


# --- vote count gate -------------------------------------------------------
def test_vote_count_gate(store):
    vt = VoteRepository(store, "votes")
    for i in range(10):
        vt.add({"id": f"v{i}", "execution_a": "a", "execution_b": "b",
                "winner_execution": "a", "ldap": "u1"})
    out = _svc(store).vote_count("u1")
    assert out["count"] == 10
    assert out["unlocked"] is True
    assert _svc(store).vote_count("nobody")["unlocked"] is False
    assert _svc(store).vote_count("anonymous")["count"] == 0


def test_elo_empty_votes(store):
    assert _svc(store).elo_rankings([]) == {}


def test_bradley_terry_empty_votes(store):
    assert _svc(store).bradley_terry([]) == {}
