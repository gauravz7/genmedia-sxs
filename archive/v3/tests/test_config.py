"""Config defaults snapshot — guards against accidental drift from v2 literals."""
from __future__ import annotations

from app.config import Settings, get_settings


def test_defaults_mirror_v2():
    s = Settings()
    assert s.gcp_project_id == "vital-octagon-19612"
    assert s.gcs_bucket_name == "project-pulse"
    assert s.sxs_collection == "sxs_jobs"
    assert s.image_collection == "image_jobs"
    assert s.tts_collection == "tts_jobs"
    assert s.eval_model == "gemini-3.1-pro-preview"
    assert s.image_eval_model == "gemini-3.5-flash"
    assert s.tts_eval_model == "gemini-3.5-flash"


def test_v3_collections_present():
    s = Settings()
    assert s.executions_collection == "executions"
    assert s.comparisons_collection == "comparisons"
    assert s.suites_collection == "suites"
    assert s.runs_collection == "runs"


def test_env_override(monkeypatch):
    monkeypatch.setenv("GCP_PROJECT_ID", "other-project")
    assert Settings().gcp_project_id == "other-project"


def test_get_settings_is_cached():
    get_settings.cache_clear()
    assert get_settings() is get_settings()
