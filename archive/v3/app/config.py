"""Central configuration — the single source for all env/config (PRD §14).

Replaces the ~90 scattered ``os.getenv`` calls in v2. Import ``get_settings()``
everywhere instead of reading the environment directly. Defaults mirror the v2
literals so behavior is unchanged.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    # --- Core GCP ---
    gcp_project_id: str = "vital-octagon-19612"
    gcs_bucket_name: str = "project-pulse"
    output_gcs_bucket: str = "project-pulse"

    # --- Admin auth ---
    admin_user: str = "admin"
    admin_pass: str = ""

    # --- Firestore collections (per modality) ---
    sxs_collection: str = "sxs_jobs"
    sxs_votes_collection: str = "sxs_votes"
    sxs_runs_collection: str = "sxs_runs"
    image_collection: str = "image_jobs"
    image_votes_collection: str = "image_votes"
    tts_collection: str = "tts_jobs"
    tts_votes_collection: str = "tts_votes"
    # v3 execution-centric collections
    executions_collection: str = "executions"
    comparisons_collection: str = "comparisons"
    suites_collection: str = "suites"
    runs_collection: str = "runs"

    # --- Judge / eval ---
    eval_project: str = "vital-octagon-19612"
    eval_location: str = "global"
    eval_model: str = "gemini-3.1-pro-preview"          # video judge
    image_eval_project: str = "vital-octagon-19612"
    image_eval_model: str = "gemini-3.5-flash"
    image_location: str = "global"
    tts_eval_project: str = "vital-octagon-19612"
    tts_eval_model: str = "gemini-3.5-flash"
    lang_tagger_model: str = "gemini-2.5-flash"

    # --- Providers ---
    fal_key: str = ""
    elevenlabs_api_key: str = ""
    elevenlabs_model: str = "eleven_v3"
    elevenlabs_fallback_model: str = "eleven_multilingual_v2"
    elevenlabs_use_native: bool = False
    gemini_tts_model: str = "gemini-2.5-flash-preview-tts"
    gpt_image_model: str = "gpt-image-2"
    mai_image_model: str = "mai-image"
    omni_project: str = "vital-octagon-19612"
    omni_location: str = "global"
    omni_model_id: str = "gemini-omni-flash-preview"
    omni_api_revision: str = ""

    # --- Concurrency ---
    gen_api_concurrency: int = 4
    image_concurrency: int = 4
    tts_concurrency: int = 4

    # --- Integrations ---
    drive_impersonate_user: str = ""

    # --- Model registry + votes ---
    models_path: str = "models.json"          # model registry JSON (id -> ModelSpec)
    votes_collection: str = "votes"


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton. Tests may override via env or ``get_settings.cache_clear()``."""
    return Settings()
