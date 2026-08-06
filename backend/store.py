"""Firestore-backed document models and their managers.

The legacy `eval_jobs` / `votes` / `prompts` collections — the pre-SxS flow. The
three modality pipelines talk to Firestore directly instead of going through
these managers.
"""

import os
import time
from typing import Dict, List, Optional

from pydantic import BaseModel


class Job(BaseModel):
    id: str
    prompt: str
    categories: List[str] = []
    ratio: str = "16:9"
    timestamp: float
    initiation_time: Optional[float] = None
    prompt_id: Optional[str] = None
    start_image_url: Optional[str] = None
    end_image_url: Optional[str] = None
    reference_image_url: Optional[str] = None
    reference_images: Optional[List[str]] = None
    reference_videos: Optional[List[str]] = None
    results: Dict[str, dict]
    generation_history: Dict[str, list] = {}
    # SxS auto-eval fields (source == "sxs_auto")
    source: Optional[str] = None
    batch_id: Optional[str] = None
    customer: Optional[str] = None
    modality: Optional[str] = None
    duration: Optional[int] = None
    auto_evals: Dict[str, dict] = {}
    auto_eval_status: Optional[str] = None
    auto_eval_error: Optional[str] = None

    def __init__(self, **data):
        # Migrate legacy single-category field
        if "category" in data:
            cat = data.pop("category")
            if cat and not data.get("categories"):
                data["categories"] = [cat]
        super().__init__(**data)


class JobsManager:
    def __init__(self):
        from google.cloud import firestore
        self.db = firestore.Client(project=os.getenv("GCP_PROJECT_ID", "vital-octagon-19612"))
        self._cached_jobs = None
        self._last_fetch_time = 0
        self.CACHE_TTL = 300

    @property
    def jobs(self):
        if self._cached_jobs is None or time.time() - self._last_fetch_time > self.CACHE_TTL:
            docs = self.db.collection("eval_jobs").stream()
            self._cached_jobs = {doc.id: Job(**doc.to_dict()) for doc in docs}
            self._last_fetch_time = time.time()
        return self._cached_jobs

    def invalidate_cache(self):
        self._cached_jobs = None

    def save_job(self, job: Job):
        self.db.collection("eval_jobs").document(job.id).set(job.dict())
        self.invalidate_cache()

    def get_all(self):
        from google.cloud import firestore
        docs = self.db.collection("eval_jobs").order_by("timestamp", direction=firestore.Query.DESCENDING).stream()
        return [Job(**doc.to_dict()) for doc in docs]


class Vote(BaseModel):
    id: str
    job_id: str
    winner_side: str
    winner_model: str
    loser_model: str
    scores: Dict[str, int]
    justification: str
    timestamp: float
    ldap: str = "anonymous"


class VotesManager:
    def __init__(self):
        from google.cloud import firestore
        self.db = firestore.Client(project=os.getenv("GCP_PROJECT_ID", "vital-octagon-19612"))

    @property
    def votes(self):
        return [Vote(**doc.to_dict()) for doc in self.db.collection("votes").stream()]

    def add_vote(self, vote: Vote):
        self.db.collection("votes").document(vote.id).set(vote.dict())


class Prompt(BaseModel):
    id: str
    text: str
    categories: List[str] = []
    start_image_url: Optional[str] = None
    end_image_url: Optional[str] = None
    reference_image_url: Optional[str] = None
    reference_images: Optional[List[str]] = None
    models: List[str] = ["Veo", "Kling", "Seedance"]
    status: str = "pending"
    timestamp: float

    def __init__(self, **data):
        if "category" in data:
            cat = data.pop("category")
            if cat and not data.get("categories"):
                data["categories"] = [cat]
        super().__init__(**data)


class PromptsManager:
    def __init__(self):
        from google.cloud import firestore
        self.db = firestore.Client(project=os.getenv("GCP_PROJECT_ID", "vital-octagon-19612"))

    @property
    def prompts(self):
        return {doc.id: Prompt(**doc.to_dict()) for doc in self.db.collection("prompts").stream()}

    def save_prompt(self, prompt: Prompt):
        self.db.collection("prompts").document(prompt.id).set(prompt.dict())

    def delete_prompt(self, prompt_id: str):
        doc_ref = self.db.collection("prompts").document(prompt_id)
        if doc_ref.get().exists:
            doc_ref.delete()
            return True
        return False

    def get_all(self):
        from google.cloud import firestore
        docs = self.db.collection("prompts").order_by("timestamp", direction=firestore.Query.DESCENDING).stream()
        return [Prompt(**doc.to_dict()) for doc in docs]


# Singletons — one Firestore client each, shared process-wide.
jobs_manager = JobsManager()
votes_manager = VotesManager()
prompts_manager = PromptsManager()
