"""BYOO ingest: URL handling and the job docs we write.

The contract these tests defend is that an ingested job is indistinguishable
from a generated one to every consumer — the arena, the judge, and the
analytics — except for its `origin` field.
"""

import pytest

import intake
import model_resolver
from conftest import IMAGE_MODELS, TTS_MODELS

pytestmark = pytest.mark.usefixtures("no_network")


# ===================================================================
# URL classification
# ===================================================================

@pytest.mark.parametrize("url", [
    "gs://project-pulse/images/a.png",
    "https://storage.googleapis.com/project-pulse/images/a.png",
    "https://project-pulse.storage.googleapis.com/images/a.png",
])
def test_our_bucket_is_recognized(url):
    assert intake._in_our_bucket(url)


@pytest.mark.parametrize("url", [
    "gs://someone-else/images/a.png",
    "https://storage.googleapis.com/other-bucket/a.png",
    "https://cdn.example.com/a.png",
    "https://project-pulse-staging.example.com/a.png",
])
def test_other_hosts_are_not_our_bucket(url):
    assert not intake._in_our_bucket(url)


@pytest.mark.parametrize("url,modality,expected", [
    ("https://x/a/b.WEBM?sig=1", "video", ".webm"),   # query string stripped, lowercased
    ("https://x/a/b.mp4", "video", ".mp4"),
    ("https://x/a/b", "tts", ".mp3"),                  # no extension -> modality default
    ("gs://b/a.wav", "tts", ".wav"),
    ("https://x/a.jpeg", "image", ".jpeg"),
    ("https://x/a.thisisnotanextension", "image", ".png"),
])
def test_extension_is_derived_or_defaulted(url, modality, expected):
    assert intake._ext_of(url, modality) == expected


@pytest.mark.parametrize("url,modality,header,expected", [
    ("https://x/a.mp4", "video", None, "video/mp4"),
    ("https://x/a", "tts", None, "audio/mpeg"),
    ("https://x/a", "image", None, "image/png"),
    ("https://x/a", "image", "audio/mpeg; charset=utf-8", "audio/mpeg"),
    # A generic octet-stream header is worse than guessing from the extension.
    ("https://x/a.png", "image", "application/octet-stream", "image/png"),
])
def test_content_type_prefers_header_then_extension(url, modality, header, expected):
    assert intake._content_type(url, modality, header) == expected


def test_content_type_is_never_hardcoded_png_for_audio():
    """`gcs_utils.upload_from_url` hardcodes image/png for gs:// transfers, which
    is why ingest does its own content-type derivation."""
    assert intake._content_type("gs://b/clip.mp3", "tts") == "audio/mpeg"
    assert intake._content_type("gs://b/clip.mp4", "video") == "video/mp4"


def test_rehost_passes_through_urls_already_in_our_bucket():
    """No pointless copy — and no risk of duplicating a large video."""
    url = "gs://project-pulse/images/existing.png"
    assert intake.rehost(url, "image", "whatever") == url


@pytest.mark.parametrize("url", ["", "   ", None])
def test_rehost_rejects_an_empty_url(url):
    with pytest.raises(intake.IngestError):
        intake.rehost(url, "image", "d")


def test_rehost_rejects_an_unsupported_scheme():
    with pytest.raises(intake.IngestError, match="unsupported URL scheme"):
        intake.rehost("ftp://x/a.png", "image", "d")


def test_rehost_wraps_a_fetch_failure_as_ingest_error(monkeypatch):
    """A dead customer link must be a per-case `skipped` reason, not a 500."""
    def _boom(url, timeout=None):
        raise ConnectionError("host unreachable")
    monkeypatch.setattr(intake.requests, "get", _boom)
    with pytest.raises(intake.IngestError, match="could not fetch"):
        intake.rehost("https://dead.example.com/a.png", "image", "d")


# ===================================================================
# The outputs manifest
# ===================================================================

def test_parse_accepts_the_url_shorthand():
    got = intake.parse_outputs({"outputs": {"m1": "https://x/a.png"}})
    assert got["m1"] == {"url": "https://x/a.png", "latency_ms": None, "metadata": {}}


def test_parse_accepts_the_object_form_and_trims():
    got = intake.parse_outputs({"outputs": {
        "m1": {"url": "  https://x/a.png  ", "latency_ms": 900, "metadata": {"seed": 7}}
    }})
    assert got["m1"] == {"url": "https://x/a.png", "latency_ms": 900,
                         "metadata": {"seed": 7}}


def test_parse_accepts_latency_as_an_alias():
    assert intake.parse_outputs(
        {"outputs": {"m1": {"url": "https://x/a", "latency": 12}}}
    )["m1"]["latency_ms"] == 12


def test_parse_accepts_results_as_an_alias_for_outputs():
    assert "m1" in intake.parse_outputs({"results": {"m1": "https://x/a.png"}})


@pytest.mark.parametrize("case", [
    {"id": "c"},                                   # no outputs at all
    {"id": "c", "outputs": {}},                    # empty
    {"id": "c", "outputs": []},                    # wrong type
    {"id": "c", "outputs": {"m": ""}},             # blank url
    {"id": "c", "outputs": {"m": {"latency_ms": 1}}},   # object with no url
    {"id": "c", "outputs": {"m": None}},
])
def test_parse_rejects_malformed_manifests(case):
    with pytest.raises(intake.IngestError):
        intake.parse_outputs(case)


# ===================================================================
# Video ingest
# ===================================================================

def _video_case(models, **over):
    case = {
        "id": "acme_v001",
        "customer": "acme",
        "prompt": "A cyclist rides through neon-lit rain",
        "modality": "T2V",
        "aspect_ratio": "9:16",
        "duration": 8,
        "categories": ["automotive"],
        "outputs": {
            models[0]: {"url": "https://acme.example.com/a.mp4", "latency_ms": 51000},
            models[1]: "gs://acme-share/b.mp4",
        },
    }
    case.update(over)
    return case


def _ingest(modality, case, names, **kw):
    specs = model_resolver.resolve_models(modality, names)
    return intake.ingest_case(modality, case, specs, **kw)


def test_video_ingest_writes_a_visible_job(fake_db, fake_rehost, video_models):
    job_id = _ingest("video", _video_case(video_models), video_models, batch_id="b1")
    doc = fake_db.only_doc("sxs_jobs")

    assert doc["id"] == job_id
    # Every list/pair endpoint filters on this — without it the job is invisible.
    assert doc["source"] == "sxs_auto"
    assert doc["origin"] == "ingest"
    assert doc["batch_id"] == "b1"
    assert doc["prompt_id"] == "acme_v001"
    assert doc["ratio"] == "9:16"
    assert doc["modality"] == "t2v"
    assert doc["categories"] == ["automotive"]


def test_video_results_are_keyed_by_model_id(fake_db, fake_rehost, video_models):
    _ingest("video", _video_case(video_models), video_models)
    results = fake_db.only_doc("sxs_jobs")["results"]
    assert set(results) == set(video_models)


def test_video_results_satisfy_the_arena_contract(fake_db, fake_rehost, video_models):
    """`/api/sxs/pair` needs >=2 results with status success and a url at either
    `url` or `result.url`."""
    _ingest("video", _video_case(video_models), video_models)
    results = fake_db.only_doc("sxs_jobs")["results"]
    usable = [r for r in results.values()
              if r.get("status") == "success"
              and (r.get("url") or r.get("result", {}).get("url"))]
    assert len(usable) >= 2


def test_customer_latency_is_preserved(fake_db, fake_rehost, video_models):
    _ingest("video", _video_case(video_models), video_models)
    results = fake_db.only_doc("sxs_jobs")["results"]
    assert results[video_models[0]]["latency_ms"] == 51000
    # Not supplied for the second output — better absent than invented.
    assert "latency_ms" not in results[video_models[1]]


def test_metadata_is_passed_through_untouched(fake_db, fake_rehost, video_models):
    case = _video_case(video_models)
    case["outputs"][video_models[0]]["metadata"] = {"seed": 12345, "run": "batch-7"}
    _ingest("video", case, video_models)
    res = fake_db.only_doc("sxs_jobs")["results"][video_models[0]]
    assert res["metadata"] == {"seed": 12345, "run": "batch-7"}


def test_results_are_flagged_as_ingested(fake_db, fake_rehost, video_models):
    _ingest("video", _video_case(video_models), video_models)
    assert all(r["ingested"] for r in fake_db.only_doc("sxs_jobs")["results"].values())


def test_every_output_url_is_rehosted(fake_db, fake_rehost, video_models):
    _ingest("video", _video_case(video_models), video_models)
    rehosted = {c["url"] for c in fake_rehost}
    assert "https://acme.example.com/a.mp4" in rehosted
    assert "gs://acme-share/b.mp4" in rehosted
    for res in fake_db.only_doc("sxs_jobs")["results"].values():
        assert res["url"].startswith("gs://project-pulse/")


def test_reference_assets_are_rehosted_too(fake_db, fake_rehost, video_models):
    """The judge reads references out of GCS, so a third-party link would make
    the case unjudgeable."""
    case = _video_case(video_models, modality="Ref2V",
                       reference_images=["https://acme.example.com/ref1.png"],
                       reference_videos=["https://acme.example.com/ref.mp4"])
    _ingest("video", case, video_models)
    doc = fake_db.only_doc("sxs_jobs")
    assert doc["reference_images"][0].startswith("gs://project-pulse/")
    assert doc["reference_videos"][0].startswith("gs://project-pulse/")


def test_a_string_reference_is_accepted_as_a_single_item(fake_db, fake_rehost, video_models):
    case = _video_case(video_models, reference_images="https://acme.example.com/one.png")
    _ingest("video", case, video_models)
    assert len(fake_db.only_doc("sxs_jobs")["reference_images"]) == 1


def test_video_ingest_supports_more_than_two_models(fake_db, fake_rehost):
    ids = [m["id"] for m in model_resolver.list_models("video") if m["type"] == "t2v"]
    if len(ids) < 3:
        pytest.skip("registry has fewer than 3 active t2v models")
    case = _video_case(ids[:2])
    case["outputs"][ids[2]] = "https://acme.example.com/c.mp4"
    _ingest("video", case, ids[:3])
    assert len(fake_db.only_doc("sxs_jobs")["results"]) == 3


# ===================================================================
# Image ingest
# ===================================================================

def _image_case(**over):
    case = {
        "id": "acme_i001",
        "prompt": "A single red maple leaf on white",
        "mode": "t2i",
        "aspect_ratio": "1:1",
        "outputs": {
            IMAGE_MODELS[0]: "https://acme.example.com/g.png",
            IMAGE_MODELS[1]: "https://acme.example.com/o.png",
        },
    }
    case.update(over)
    return case


def test_image_ingest_writes_a_two_sided_job(fake_db, fake_rehost):
    _ingest("image", _image_case(), IMAGE_MODELS, batch_id="b1")
    doc = fake_db.only_doc("image_jobs")
    assert doc["source"] == "sxs_auto"
    assert doc["origin"] == "ingest"
    assert set(doc["side_map"]) == {"A", "B"}
    assert set(doc["side_map"].values()) == set(IMAGE_MODELS)
    assert set(doc["results"]) == {"A", "B"}


def test_image_result_labels_match_the_side_map(fake_db, fake_rehost):
    """The single most important invariant of the blind arena: if a result is
    filed under the wrong label, every vote for it is recorded against the wrong
    model."""
    _ingest("image", _image_case(), IMAGE_MODELS)
    doc = fake_db.only_doc("image_jobs")
    for label in ("A", "B"):
        assert doc["results"][label]["engine"] == doc["side_map"][label]


def test_image_result_url_matches_the_engine_that_produced_it(fake_db, fake_rehost):
    case = _image_case()
    _ingest("image", case, IMAGE_MODELS)
    doc = fake_db.only_doc("image_jobs")
    for label in ("A", "B"):
        engine = doc["side_map"][label]
        # The rehost dest name embeds the engine slug, so a swapped pair shows up.
        assert engine.replace(".", "-") in doc["results"][label]["url"]


def test_image_side_specs_carry_the_full_identity(fake_db, fake_rehost):
    """`side_specs` is what retry and the admin view read."""
    _ingest("image", _image_case(), IMAGE_MODELS)
    specs = fake_db.only_doc("image_jobs")["side_specs"]
    assert set(specs) == {"A", "B"}
    for side in specs.values():
        assert {"engine", "provider", "model"} <= set(side)


def test_image_ab_assignment_is_randomized(fake_db, fake_rehost):
    """Blind voting is only unbiased if the same pair doesn't always land the
    same way round."""
    seen = set()
    for i in range(40):
        _ingest("image", _image_case(id=f"acme_i{i:03d}"), IMAGE_MODELS)
        seen.add(fake_db.docs("image_jobs")[
            sorted(fake_db.docs("image_jobs"))[-1]]["side_map"]["A"])
    assert seen == set(IMAGE_MODELS), "A-side never varied across 40 jobs"


def test_i2i_source_image_is_rehosted(fake_db, fake_rehost):
    _ingest("image", _image_case(mode="i2i",
                                 input_image="https://acme.example.com/src.png"),
            IMAGE_MODELS)
    doc = fake_db.only_doc("image_jobs")
    assert doc["mode"] == "i2i"
    assert doc["input_image"].startswith("gs://project-pulse/")


def test_i2i_source_accepted_under_alias_keys(fake_db, fake_rehost):
    _ingest("image", _image_case(mode="i2i",
                                 reference_image="https://acme.example.com/src.png"),
            IMAGE_MODELS)
    assert fake_db.only_doc("image_jobs")["input_image"].startswith("gs://project-pulse/")


def test_ingest_does_not_mutate_the_callers_case(fake_db, fake_rehost):
    case = _image_case(mode="i2i", input_image="https://acme.example.com/src.png")
    _ingest("image", case, IMAGE_MODELS)
    assert case["input_image"] == "https://acme.example.com/src.png"


def test_matchup_label_names_both_engines(fake_db, fake_rehost):
    _ingest("image", _image_case(), IMAGE_MODELS)
    matchup = fake_db.only_doc("image_jobs")["matchup"]
    assert all(m in matchup for m in IMAGE_MODELS)


# ===================================================================
# TTS ingest
# ===================================================================

def _tts_case(**over):
    case = {
        "id": "acme_t001",
        "text": "Welcome to the quarterly review.",
        "mode": "single",
        "voice": "George",
        "outputs": {
            TTS_MODELS[0]: "https://acme.example.com/g.mp3",
            TTS_MODELS[1]: "https://acme.example.com/e.mp3",
        },
    }
    case.update(over)
    return case


def test_tts_ingest_writes_a_two_sided_job(fake_db, fake_rehost):
    _ingest("tts", _tts_case(), TTS_MODELS, batch_id="b1")
    doc = fake_db.only_doc("tts_jobs")
    assert doc["source"] == "sxs_auto"
    assert doc["origin"] == "ingest"
    assert set(doc["side_map"].values()) == set(TTS_MODELS)
    assert doc["media_type"] == "audio"


def test_tts_result_labels_match_the_side_map(fake_db, fake_rehost):
    _ingest("tts", _tts_case(), TTS_MODELS)
    doc = fake_db.only_doc("tts_jobs")
    for label in ("A", "B"):
        assert doc["results"][label]["engine"] == doc["side_map"][label]


def test_tts_language_is_autodetected_when_omitted(fake_db, fake_rehost):
    _ingest("tts", _tts_case(), TTS_MODELS)
    doc = fake_db.only_doc("tts_jobs")
    assert doc["language"]
    assert doc["language_autodetected"] is True


def test_supplied_language_wins_over_autodetection(fake_db, fake_rehost):
    _ingest("tts", _tts_case(language="hi-en"), TTS_MODELS)
    doc = fake_db.only_doc("tts_jobs")
    assert doc["language"] == "hi-en"
    assert doc["language_autodetected"] is False


def test_multi_speaker_case_keeps_its_speakers(fake_db, fake_rehost):
    """Single vs multi is a property of the CASE, not the engine."""
    _ingest("tts", _tts_case(
        mode="multi",
        text="Priya: Did it clear customs?\nRahul: This morning.",
        speakers=[{"name": "Priya"}, {"name": "Rahul"}],
    ), TTS_MODELS)
    doc = fake_db.only_doc("tts_jobs")
    assert doc["mode"] == "multi"
    assert [s["name"] for s in doc["speakers"]] == ["Priya", "Rahul"]


def test_tts_categories_are_autotagged_when_omitted(fake_db, fake_rehost):
    _ingest("tts", _tts_case(), TTS_MODELS)
    assert isinstance(fake_db.only_doc("tts_jobs")["categories"], list)


# ===================================================================
# run_eval
# ===================================================================

@pytest.mark.parametrize("modality,collection,case_fn,models", [
    ("image", "image_jobs", _image_case, IMAGE_MODELS),
    ("tts", "tts_jobs", _tts_case, TTS_MODELS),
])
def test_run_eval_true_leaves_the_job_pending(modality, collection, case_fn, models,
                                              fake_db, fake_rehost):
    _ingest(modality, case_fn(), models, run_eval=True)
    assert fake_db.only_doc(collection)["auto_eval_status"] == "pending"


@pytest.mark.parametrize("modality,collection,case_fn,models", [
    ("image", "image_jobs", _image_case, IMAGE_MODELS),
    ("tts", "tts_jobs", _tts_case, TTS_MODELS),
])
def test_run_eval_false_marks_the_job_skipped(modality, collection, case_fn, models,
                                              fake_db, fake_rehost):
    """Not "pending" — nothing will ever clear it, and the AI-evals page would
    show the job as perpetually in-flight."""
    _ingest(modality, case_fn(), models, run_eval=False)
    assert fake_db.only_doc(collection)["auto_eval_status"] == "skipped"


def test_video_run_eval_false_marks_the_job_skipped(fake_db, fake_rehost, video_models):
    _ingest("video", _video_case(video_models), video_models, run_eval=False)
    assert fake_db.only_doc("sxs_jobs")["auto_eval_status"] == "skipped"


def test_source_label_is_recorded_for_provenance(fake_db, fake_rehost, video_models):
    _ingest("video", _video_case(video_models), video_models,
            source_label="Acme Q3 export, 2026-08-01")
    assert fake_db.only_doc("sxs_jobs")["imported_from"] == "Acme Q3 export, 2026-08-01"


def test_unknown_modality_is_rejected(fake_db, fake_rehost):
    with pytest.raises(intake.IngestError, match="unknown modality"):
        intake.ingest_case("hologram", _image_case(), [])


# ===================================================================
# The judge runner
# ===================================================================

def test_run_eval_for_dispatches_per_modality(monkeypatch):
    import sxs_pipeline
    called = []
    monkeypatch.setattr(sxs_pipeline, "run_auto_eval", lambda j: called.append(j))
    intake.run_eval_for("video", "job-1")
    assert called == ["job-1"]


def test_run_eval_for_swallows_judge_failures(monkeypatch):
    """A background judge crash must not take down the request that queued it —
    the failure is recorded on the doc by the evaluator itself."""
    import sxs_pipeline

    def _boom(job_id):
        raise RuntimeError("Vertex quota exceeded")

    monkeypatch.setattr(sxs_pipeline, "run_auto_eval", _boom)
    intake.run_eval_for("video", "job-1")  # no raise
