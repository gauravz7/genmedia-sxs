"""Shared fixtures for the intake test suite.

The point of these tests is the intake LOGIC — model-name validation, the shape
of the job docs we write, A/B labelling, partial-success handling. None of that
should require Firestore, GCS, or a provider API, so all three are stubbed here.

Anything that would make a network call and is NOT stubbed is a bug in the test,
not something to paper over: `fake_db` raises on an unexpected collection and
`no_network` makes `requests.get` fail loudly.
"""

import os
import sys

import pytest

# Import the backend modules the way the app does (flat, from backend/).
BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

os.environ.setdefault("ADMIN_USER", "admin")
os.environ.setdefault("ADMIN_PASS", "test-pass-for-unit-tests")


# --- Firestore ---------------------------------------------------------------

class FakeDoc:
    def __init__(self, store, collection, doc_id):
        self._store, self._c, self._id = store, collection, doc_id

    def set(self, data):
        self._store.setdefault(self._c, {})[self._id] = dict(data)

    def update(self, patch):
        doc = self._store.setdefault(self._c, {}).setdefault(self._id, {})
        for k, v in patch.items():
            # Firestore dotted-path updates ("results.A") write nested keys.
            if "." in k:
                head, tail = k.split(".", 1)
                doc.setdefault(head, {})[tail] = v
            else:
                doc[k] = v

    def get(self):
        data = self._store.get(self._c, {}).get(self._id)
        return FakeSnap(data)


class FakeSnap:
    def __init__(self, data):
        self._data = data

    @property
    def exists(self):
        return self._data is not None

    def to_dict(self):
        return dict(self._data) if self._data else None


class FakeCollection:
    def __init__(self, store, name):
        self._store, self._name = store, name

    def document(self, doc_id):
        return FakeDoc(self._store, self._name, doc_id)


class FakeDB:
    """An in-memory stand-in for `firestore.Client`. `.store` is the written
    state: {collection: {doc_id: doc}}."""

    def __init__(self):
        self.store = {}

    def collection(self, name):
        return FakeCollection(self.store, name)

    def docs(self, collection):
        return self.store.get(collection, {})

    def only_doc(self, collection):
        docs = self.docs(collection)
        assert len(docs) == 1, f"expected 1 doc in {collection}, got {len(docs)}"
        return next(iter(docs.values()))


@pytest.fixture
def fake_db(monkeypatch):
    """Patch every pipeline's Firestore accessor to one shared in-memory DB."""
    import image_pipeline
    import sxs_pipeline
    import tts_pipeline

    db = FakeDB()
    for mod in (sxs_pipeline, image_pipeline, tts_pipeline):
        monkeypatch.setattr(mod, "_get_firestore_client", lambda: db)
    return db


# --- GCS ---------------------------------------------------------------------

@pytest.fixture
def fake_rehost(monkeypatch):
    """Record every rehost call and return a deterministic in-bucket URL.

    Returns the call list so tests can assert WHAT got rehosted (outputs,
    reference images, i2i sources) without asserting on timestamps.
    """
    import intake

    calls = []

    def _rehost(url, modality, dest_name, timeout=300):
        calls.append({"url": url, "modality": modality, "dest": dest_name})
        if intake._in_our_bucket(url):
            return url
        return f"gs://project-pulse/{intake._DEST_PREFIX[modality]}/{dest_name}"

    monkeypatch.setattr(intake, "rehost", _rehost)
    return calls


@pytest.fixture
def no_network(monkeypatch):
    """Fail loudly on any un-stubbed HTTP call."""
    import requests

    def _boom(*a, **kw):
        raise AssertionError(f"unexpected network call: {a[:1]}")

    monkeypatch.setattr(requests, "get", _boom)


# --- LLM auto-tagging --------------------------------------------------------

@pytest.fixture(autouse=True)
def no_llm_tagging(monkeypatch):
    """Building a TTS job doc calls Gemini twice — `_detect_language` and
    `_voice_categories` both tag the transcript at creation time. Left live that
    is ~7s of real Vertex traffic per test and a suite that fails when a quota
    does. Autouse so no test can hit Vertex by accident.
    """
    import tts_pipeline

    monkeypatch.setattr(tts_pipeline, "_detect_language", lambda text: "en" if text else "")
    monkeypatch.setattr(tts_pipeline, "_voice_categories",
                        lambda text, lang: ["language:en", "industry:corporate"])


# --- App ---------------------------------------------------------------------

@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    import main
    return TestClient(main.app)


@pytest.fixture
def admin_headers():
    import intake_routes
    return {"X-Admin-Token": intake_routes._admin_token()}


@pytest.fixture
def registry():
    import main
    return main.registry


@pytest.fixture
def video_models(registry):
    """Two active t2v ids from the live registry — hardcoding names here would
    make the suite fail the next time the registry changes."""
    import model_resolver
    ids = [m["id"] for m in model_resolver.list_models("video") if m["type"] == "t2v"]
    if len(ids) < 2:
        pytest.skip("registry has fewer than 2 active t2v models")
    return ids[:2]


IMAGE_MODELS = ["gemini-3-pro-image", "gpt-image-2-high"]
TTS_MODELS = ["gemini-3.1-flash-tts-preview", "elevenlabs-v3"]
