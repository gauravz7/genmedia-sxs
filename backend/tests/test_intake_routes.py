"""The six intake endpoints, end to end through the app — auth, validation, the
partial-success envelope, and what actually gets written and queued.

Generation and the AI judge are stubbed: these tests are about the intake
contract, not about whether Veo returns a good video.
"""

import pytest

from conftest import IMAGE_MODELS, TTS_MODELS

PROMPTS = ["/api/sxs/prompts", "/api/image/prompts", "/api/tts/prompts"]
OUTPUTS = ["/api/sxs/outputs", "/api/image/outputs", "/api/tts/outputs"]
ALL_SIX = PROMPTS + OUTPUTS


@pytest.fixture
def no_generation(monkeypatch):
    """Stub the three batch processors and capture what was queued."""
    import image_pipeline
    import sxs_pipeline
    import tts_pipeline

    queued = {"video": [], "image": [], "tts": []}

    async def _v(triples):
        queued["video"].extend(triples)

    async def _i(pairs):
        queued["image"].extend(pairs)

    async def _t(pairs):
        queued["tts"].extend(pairs)

    monkeypatch.setattr(sxs_pipeline, "process_admin_batch", _v)
    monkeypatch.setattr(image_pipeline, "process_batch", _i)
    monkeypatch.setattr(tts_pipeline, "process_tts_batch", _t)
    return queued


@pytest.fixture
def no_judge(monkeypatch):
    """Stub the three judges and capture the job ids they were asked to score."""
    import intake
    judged = []
    monkeypatch.setattr(intake, "run_eval_for",
                        lambda modality, job_id: judged.append((modality, job_id)))
    import intake_routes
    monkeypatch.setattr(intake_routes, "run_eval_for",
                        lambda modality, job_id: judged.append((modality, job_id)))
    return judged


# --- request bodies ----------------------------------------------------------

def image_case(i=0, **over):
    case = {"id": f"acme_i{i:03d}", "prompt": "a red leaf", "mode": "t2i"}
    case.update(over)
    return case


def image_outputs_case(i=0, **over):
    return image_case(i, outputs={
        IMAGE_MODELS[0]: "https://acme.example.com/g.png",
        IMAGE_MODELS[1]: "https://acme.example.com/o.png",
    }, **over)


def tts_case(i=0, **over):
    case = {"id": f"acme_t{i:03d}", "text": "Welcome to the review.", "mode": "single"}
    case.update(over)
    return case


def tts_outputs_case(i=0, **over):
    return tts_case(i, outputs={
        TTS_MODELS[0]: "https://acme.example.com/g.mp3",
        TTS_MODELS[1]: "https://acme.example.com/e.mp3",
    }, **over)


def video_case(i=0, **over):
    case = {"id": f"acme_v{i:03d}", "customer": "acme",
            "prompt": "a cyclist in the rain", "modality": "T2V"}
    case.update(over)
    return case


# ===================================================================
# Auth
# ===================================================================

@pytest.mark.parametrize("path", ALL_SIX)
def test_all_six_endpoints_require_admin(client, path):
    r = client.post(path, json={"models": ["x"], "cases": [{}]})
    assert r.status_code == 401


@pytest.mark.parametrize("path", ALL_SIX)
def test_a_wrong_token_is_rejected(client, path):
    r = client.post(path, headers={"X-Admin-Token": "deadbeef"},
                    json={"models": ["x"], "cases": [{}]})
    assert r.status_code == 401


def test_discovery_endpoint_is_open(client):
    """A caller needs the model list to build a valid request."""
    assert client.get("/api/intake/models").status_code == 200


# ===================================================================
# Discovery
# ===================================================================

def test_discovery_lists_models_with_transport(client):
    body = client.get("/api/intake/models?modality=tts").json()
    ids = {m["id"] for m in body["models"]}
    assert set(TTS_MODELS) <= ids
    assert all(m["transport"] in ("vertex", "fal") for m in body["models"])


def test_discovery_rejects_an_unknown_modality(client):
    r = client.get("/api/intake/models?modality=audio")
    assert r.status_code == 400
    assert "video, image or tts" in r.json()["detail"]


def test_discovery_can_include_inactive(client):
    active = client.get("/api/intake/models").json()["models"]
    every = client.get("/api/intake/models?active_only=false").json()["models"]
    assert len(every) >= len(active)


# ===================================================================
# Request-level validation
# ===================================================================

@pytest.mark.parametrize("path,body", [
    ("/api/image/prompts", {"models": IMAGE_MODELS, "cases": []}),
    ("/api/tts/prompts", {"models": TTS_MODELS, "cases": []}),
    ("/api/image/outputs", {"cases": []}),
    ("/api/sxs/outputs", {"cases": []}),
])
def test_an_empty_batch_is_a_400(client, admin_headers, path, body):
    r = client.post(path, headers=admin_headers, json=body)
    assert r.status_code == 400
    assert r.json()["detail"] == "No cases supplied."


def test_an_unregistered_model_fails_the_whole_prompts_request(client, admin_headers):
    """`models` is request-level, so a bad name there is not a per-row skip."""
    r = client.post("/api/image/prompts", headers=admin_headers,
                    json={"models": ["ghost", IMAGE_MODELS[0]], "cases": [image_case()]})
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert detail["problems"] == ["'ghost' is not a registered model"]
    assert IMAGE_MODELS[0] in detail["available"]


def test_image_prompts_requires_exactly_two_models(client, admin_headers):
    r = client.post("/api/image/prompts", headers=admin_headers,
                    json={"models": [IMAGE_MODELS[0]], "cases": [image_case()]})
    assert r.status_code == 400
    assert "two-sided" in r.json()["detail"]


def test_tts_prompts_rejects_an_image_model(client, admin_headers):
    r = client.post("/api/tts/prompts", headers=admin_headers,
                    json={"models": [IMAGE_MODELS[0], TTS_MODELS[0]],
                          "cases": [tts_case()]})
    assert r.status_code == 400


def test_models_is_required_on_prompts(client, admin_headers):
    r = client.post("/api/image/prompts", headers=admin_headers,
                    json={"cases": [image_case()]})
    assert r.status_code == 422


def test_outputs_takes_no_request_level_models(client, admin_headers, fake_db,
                                               fake_rehost, no_judge):
    """Models are per-case on the outputs path — a customer export is rarely
    uniform. An extra `models` key is simply ignored, not an error."""
    r = client.post("/api/image/outputs", headers=admin_headers,
                    json={"models": ["ghost"], "cases": [image_outputs_case()]})
    assert r.status_code == 200
    assert r.json()["count"] == 1


# ===================================================================
# /prompts — happy paths
# ===================================================================

def test_image_prompts_creates_jobs_and_queues_generation(
        client, admin_headers, fake_db, no_generation):
    r = client.post("/api/image/prompts", headers=admin_headers, json={
        "models": IMAGE_MODELS,
        "cases": [image_case(0), image_case(1)],
        "batch_id": "acme-q3",
    })
    body = r.json()
    assert r.status_code == 200
    assert body["status"] == "ok"
    assert body["count"] == 2 and body["skipped"] == []
    assert body["batch_id"] == "acme-q3"
    assert len(fake_db.docs("image_jobs")) == 2
    assert len(no_generation["image"]) == 2


def test_image_prompts_uses_the_named_pair_not_a_preset_matchup(
        client, admin_headers, fake_db, no_generation):
    client.post("/api/image/prompts", headers=admin_headers,
                json={"models": IMAGE_MODELS, "cases": [image_case()]})
    doc = fake_db.only_doc("image_jobs")
    assert set(doc["side_map"].values()) == set(IMAGE_MODELS)
    assert set(s["engine"] for s in doc["side_specs"].values()) == set(IMAGE_MODELS)


def test_tts_prompts_creates_jobs_and_queues_generation(
        client, admin_headers, fake_db, no_generation):
    r = client.post("/api/tts/prompts", headers=admin_headers,
                    json={"models": TTS_MODELS, "cases": [tts_case()]})
    assert r.json()["count"] == 1
    assert set(fake_db.only_doc("tts_jobs")["side_map"].values()) == set(TTS_MODELS)
    assert len(no_generation["tts"]) == 1


def test_video_prompts_creates_an_n_way_job(
        client, admin_headers, fake_db, no_generation, video_models):
    r = client.post("/api/sxs/prompts", headers=admin_headers,
                    json={"models": video_models, "cases": [video_case()]})
    assert r.json()["count"] == 1
    doc = fake_db.only_doc("sxs_jobs")
    assert set(doc["results"]) == set(video_models)
    assert doc["source"] == "sxs_auto"
    assert len(no_generation["video"]) == 1


def test_video_prompts_passes_full_model_dicts_to_the_pipeline(
        client, admin_headers, fake_db, no_generation, video_models):
    """`create_admin_job` / `generate_for_model` index into these by key."""
    client.post("/api/sxs/prompts", headers=admin_headers,
                json={"models": video_models, "cases": [video_case()]})
    _job_id, _case, model_list = no_generation["video"][0]
    for m in model_list:
        assert {"id", "provider", "model_id", "type"} <= set(m)


@pytest.mark.parametrize("key,value,expected", [
    ("categories", ["automotive", "night"], ["automotive", "night"]),
    ("tags", ["night"], ["night"]),
    ("category", "night", ["night"]),
    (None, None, []),
])
def test_video_prompts_persists_supplied_categories(
        client, admin_headers, fake_db, no_generation, video_models,
        key, value, expected):
    """`process_admin_job` skips auto-tagging when the case carries tags, so a
    dropped `categories` would leave the job untagged AND unauto-tagged —
    invisible to every tag-filtered analytic."""
    case = video_case(**({key: value} if key else {}))
    client.post("/api/sxs/prompts", headers=admin_headers,
                json={"models": video_models, "cases": [case]})
    assert fake_db.only_doc("sxs_jobs")["categories"] == expected


def test_video_prompts_rejects_a_type_mismatched_case(
        client, admin_headers, fake_db, no_generation, video_models):
    """t2v models named on an I2V case: the reference image would be silently
    ignored, so the row is skipped rather than run."""
    r = client.post("/api/sxs/prompts", headers=admin_headers, json={
        "models": video_models,
        "cases": [video_case(0, modality="I2V",
                             reference_images=["https://x/ref.png"])],
    })
    body = r.json()
    assert body["count"] == 0
    assert body["status"] == "failed"
    assert "Case is 'i2v'" in body["skipped"][0]["reason"]


def test_a_generated_batch_id_is_returned_when_not_supplied(
        client, admin_headers, fake_db, no_generation):
    body = client.post("/api/image/prompts", headers=admin_headers,
                       json={"models": IMAGE_MODELS, "cases": [image_case()]}).json()
    assert body["batch_id"].startswith("image_intake_")
    assert fake_db.only_doc("image_jobs")["batch_id"] == body["batch_id"]


@pytest.mark.parametrize("path,models,case_fn,collection", [
    ("/api/image/prompts", IMAGE_MODELS, image_case, "image_jobs"),
    ("/api/tts/prompts", TTS_MODELS, tts_case, "tts_jobs"),
])
def test_prompts_run_eval_false_marks_the_job_skipped(
        client, admin_headers, fake_db, no_generation, path, models, case_fn, collection):
    client.post(path, headers=admin_headers,
                json={"models": models, "cases": [case_fn()], "run_eval": False})
    assert fake_db.only_doc(collection)["auto_eval_status"] == "skipped"


@pytest.mark.parametrize("path,models,case_fn,collection", [
    ("/api/image/prompts", IMAGE_MODELS, image_case, "image_jobs"),
    ("/api/tts/prompts", TTS_MODELS, tts_case, "tts_jobs"),
])
def test_prompts_default_to_running_the_judge(
        client, admin_headers, fake_db, no_generation, path, models, case_fn, collection):
    client.post(path, headers=admin_headers,
                json={"models": models, "cases": [case_fn()]})
    assert fake_db.only_doc(collection)["auto_eval_status"] == "pending"


def test_video_prompts_run_eval_false_marks_the_job_skipped(
        client, admin_headers, fake_db, no_generation, video_models):
    client.post("/api/sxs/prompts", headers=admin_headers,
                json={"models": video_models, "cases": [video_case()],
                      "run_eval": False})
    assert fake_db.only_doc("sxs_jobs")["auto_eval_status"] == "skipped"


# ===================================================================
# /outputs — happy paths
# ===================================================================

def test_image_outputs_registers_a_job(client, admin_headers, fake_db,
                                       fake_rehost, no_judge):
    r = client.post("/api/image/outputs", headers=admin_headers,
                    json={"cases": [image_outputs_case()], "batch_id": "imp-1",
                          "source_label": "Acme Q3 export"})
    body = r.json()
    assert body["count"] == 1 and body["skipped"] == []
    doc = fake_db.only_doc("image_jobs")
    assert doc["origin"] == "ingest"
    assert doc["imported_from"] == "Acme Q3 export"
    assert all(res["status"] == "success" for res in doc["results"].values())


def test_tts_outputs_registers_a_job(client, admin_headers, fake_db,
                                     fake_rehost, no_judge):
    r = client.post("/api/tts/outputs", headers=admin_headers,
                    json={"cases": [tts_outputs_case()]})
    assert r.json()["count"] == 1
    assert set(fake_db.only_doc("tts_jobs")["side_map"].values()) == set(TTS_MODELS)


def test_video_outputs_registers_a_job(client, admin_headers, fake_db,
                                       fake_rehost, no_judge, video_models):
    case = video_case(outputs={
        video_models[0]: {"url": "https://acme.example.com/a.mp4", "latency_ms": 51000},
        video_models[1]: "gs://acme-share/b.mp4",
    })
    r = client.post("/api/sxs/outputs", headers=admin_headers, json={"cases": [case]})
    assert r.json()["count"] == 1
    assert set(fake_db.only_doc("sxs_jobs")["results"]) == set(video_models)


def test_outputs_queues_the_judge_by_default(client, admin_headers, fake_db,
                                             fake_rehost, no_judge):
    client.post("/api/image/outputs", headers=admin_headers,
                json={"cases": [image_outputs_case()]})
    assert [m for m, _ in no_judge] == ["image"]


def test_outputs_run_eval_false_skips_the_judge(client, admin_headers, fake_db,
                                                fake_rehost, no_judge):
    r = client.post("/api/image/outputs", headers=admin_headers,
                    json={"cases": [image_outputs_case()], "run_eval": False})
    assert r.json()["count"] == 1
    assert no_judge == []
    assert fake_db.only_doc("image_jobs")["auto_eval_status"] == "skipped"


def test_outputs_accepts_a_per_case_model_pair(client, admin_headers, fake_db,
                                               fake_rehost, no_judge):
    """Case 1 compares A vs B, case 2 compares A vs C — the reason `models` is
    per-case on this path."""
    c1 = image_outputs_case(0)
    c2 = image_case(1, outputs={
        IMAGE_MODELS[0]: "https://acme.example.com/g2.png",
        "gpt-image-2-low": "https://acme.example.com/l2.png",
    })
    r = client.post("/api/image/outputs", headers=admin_headers,
                    json={"cases": [c1, c2]})
    assert r.json()["count"] == 2
    pairs = {frozenset(d["side_map"].values()) for d in fake_db.docs("image_jobs").values()}
    assert pairs == {frozenset(IMAGE_MODELS),
                     frozenset([IMAGE_MODELS[0], "gpt-image-2-low"])}


# ===================================================================
# Partial success — the property that makes a 500-row upload usable
# ===================================================================

def test_one_bad_row_does_not_abort_the_batch(client, admin_headers, fake_db,
                                              fake_rehost, no_judge):
    good = image_outputs_case(0)
    bad = image_case(1)  # no outputs
    r = client.post("/api/image/outputs", headers=admin_headers,
                    json={"cases": [good, bad, image_outputs_case(2)]})
    body = r.json()
    assert r.status_code == 200
    assert body["status"] == "ok"
    assert body["count"] == 2
    assert len(body["skipped"]) == 1
    assert body["skipped"][0] == {"index": 1, "id": "acme_i001",
                                  "reason": "case has no `outputs` object"}


def test_a_bad_model_name_skips_only_its_own_row(client, admin_headers, fake_db,
                                                 fake_rehost, no_judge):
    bad = image_case(1, outputs={"ghost": "https://x/a.png",
                                 IMAGE_MODELS[0]: "https://x/b.png"})
    body = client.post("/api/image/outputs", headers=admin_headers,
                       json={"cases": [image_outputs_case(0), bad]}).json()
    assert body["count"] == 1
    assert "'ghost' is not a registered model" in body["skipped"][0]["reason"]


def test_a_structured_400_is_flattened_into_one_reason(client, admin_headers, fake_db,
                                                       fake_rehost, no_judge):
    """resolve_models raises a dict detail; a skipped row needs a plain string."""
    bad = image_case(0, outputs={"ghost-a": "https://x/a.png",
                                 "ghost-b": "https://x/b.png"})
    body = client.post("/api/image/outputs", headers=admin_headers,
                       json={"cases": [bad]}).json()
    reason = body["skipped"][0]["reason"]
    assert isinstance(reason, str)
    assert "ghost-a" in reason and "ghost-b" in reason


def test_a_dead_url_skips_only_its_own_row(client, admin_headers, fake_db,
                                           monkeypatch, no_judge):
    """The single most likely real-world failure: a customer link that 404s."""
    import intake

    def _rehost(url, modality, dest_name, timeout=300):
        if "dead" in url:
            raise intake.IngestError(f"could not fetch {url}: 404")
        return f"gs://project-pulse/{intake._DEST_PREFIX[modality]}/{dest_name}"

    monkeypatch.setattr(intake, "rehost", _rehost)
    bad = image_case(1, outputs={IMAGE_MODELS[0]: "https://dead.example.com/a.png",
                                 IMAGE_MODELS[1]: "https://x/b.png"})
    body = client.post("/api/image/outputs", headers=admin_headers,
                       json={"cases": [image_outputs_case(0), bad]}).json()
    assert body["count"] == 1
    assert "could not fetch" in body["skipped"][0]["reason"]


def test_the_judge_is_not_queued_for_a_skipped_row(client, admin_headers, fake_db,
                                                   fake_rehost, no_judge):
    client.post("/api/image/outputs", headers=admin_headers,
                json={"cases": [image_case(0)]})   # no outputs -> skipped
    assert no_judge == []


def test_a_wrong_count_skips_only_its_own_row(client, admin_headers, fake_db,
                                              fake_rehost, no_judge):
    """Image duels are two-sided; three outputs on one case is that row's problem."""
    bad = image_case(1, outputs={IMAGE_MODELS[0]: "https://x/a.png",
                                 IMAGE_MODELS[1]: "https://x/b.png",
                                 "gpt-image-2-low": "https://x/c.png"})
    body = client.post("/api/image/outputs", headers=admin_headers,
                       json={"cases": [image_outputs_case(0), bad]}).json()
    assert body["count"] == 1
    assert "two-sided" in body["skipped"][0]["reason"]


def test_a_case_without_an_id_is_still_reportable(client, admin_headers, fake_db,
                                                  fake_rehost, no_judge):
    body = client.post("/api/image/outputs", headers=admin_headers,
                       json={"cases": [{"prompt": "no id here"}]}).json()
    assert body["skipped"][0]["id"] == "(case #0)"
    assert body["skipped"][0]["index"] == 0


def test_status_is_failed_only_when_nothing_was_created(client, admin_headers,
                                                        fake_db, fake_rehost, no_judge):
    body = client.post("/api/image/outputs", headers=admin_headers,
                       json={"cases": [image_case(0), image_case(1)]}).json()
    assert body["status"] == "failed"
    assert body["count"] == 0 and len(body["skipped"]) == 2


# ===================================================================
# Envelope shape — one contract across all six
# ===================================================================

@pytest.mark.parametrize("path,body", [
    ("/api/image/prompts", {"models": IMAGE_MODELS, "cases": [image_case()]}),
    ("/api/tts/prompts", {"models": TTS_MODELS, "cases": [tts_case()]}),
    ("/api/image/outputs", {"cases": [image_outputs_case()]}),
    ("/api/tts/outputs", {"cases": [tts_outputs_case()]}),
])
def test_every_endpoint_returns_the_same_envelope(
        client, admin_headers, fake_db, fake_rehost, no_generation, no_judge, path, body):
    got = client.post(path, headers=admin_headers, json=body).json()
    assert set(got) == {"status", "batch_id", "job_ids", "count", "skipped"}
    assert got["count"] == len(got["job_ids"])
