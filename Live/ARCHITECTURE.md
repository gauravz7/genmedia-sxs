# InterviewAI — Architecture Document

**AI-powered voice interview prep platform: Analyst to VP, with career coaching and job search**

---

## Table of Contents

- [Product Vision](#product-vision)
- [User Personas](#user-personas)
- [System Architecture](#system-architecture)
- [Real-Time Interview Flow](#real-time-interview-flow)
- [Core Features (Prioritized)](#core-features-prioritized)
- [Interview Engine Design](#interview-engine-design)
  - [Question Bank Taxonomy](#question-bank-taxonomy)
  - [Level Calibration Matrix](#level-calibration-matrix)
  - [JD to Questions Pipeline](#jd--questions-pipeline)
  - [Real-Time Evaluation](#real-time-evaluation-via-gemini-live-function-calling)
  - [Follow-Up Strategy](#follow-up-strategy)
- [Backend Structure](#backend-structure)
- [Frontend Structure](#frontend-structure)
- [API Endpoints](#api-endpoints)
- [WebSocket Message Protocol](#websocket-message-protocol)
- [Firestore Schema](#firestore-schema)
- [Career Coach Module](#career-coach-module)
- [Job Search Integration](#job-search-integration)
- [Deployment](#deployment)
- [Cost Estimate](#cost-estimate-1k-mau)
- [MVP Week-by-Week](#mvp-week-by-week)
- [Edge Cases and Failure Modes](#edge-cases-and-failure-modes)
- [Key Technical Decisions](#key-technical-decisions)

---

## Product Vision

A real-time voice conversation app where an AI interviewer conducts realistic mock interviews using **Gemini Live API** (WebSocket, bidirectional audio, <100ms latency). It can ingest any JD and generate deep, role-calibrated questions. Post-session: detailed scoring, transcript review, and improvement plans. Plus a career coach and public job search.

**Core differentiator:** Voice-first, low-latency, feels like a real interview — not a chatbot quiz.

**Technology foundation:**
- **Gemini Live API** — real-time bidirectional voice over WebSocket
  - Audio I/O: PCM 16-bit (16kHz in, 24kHz out)
  - Supports barge-in (user can interrupt AI)
  - Affective dialog (adapts tone to user expression)
  - Function calling (structured eval data during conversation)
  - 70 languages supported
  - Stateful WebSocket sessions

---

## User Personas

| Persona | Title Range | Experience | Primary Need | Interview Depth |
|---------|------------|-----------|-------------|-----------------|
| **Aspiring Analyst** | AI/ML Analyst, Junior Data Scientist | 0-2 yrs | Break into AI/ML from adjacent fields | SQL, Python basics, statistics, ML fundamentals |
| **Mid-Level DS/MLE** | Data Scientist, ML Engineer | 2-5 yrs | Senior promotion, FAANG prep | Feature eng, model selection, experiment design, MLOps |
| **Senior MLE/Staff** | Senior MLE, Staff Engineer | 5-8 yrs | Staff/Principal, system design | Distributed training, ML infra, trade-off analysis |
| **AI Lead/Manager** | AI Lead, ML Manager, Head of DS | 8-12 yrs | First management role, Director transition | Team building, project scoping, stakeholder mgmt, technical strategy |
| **VP/Director** | VP of AI, Director of ML, Chief AI Officer | 12+ yrs | Executive AI strategy interviews | Org design, AI ROI, regulatory, board comms, build-vs-buy |

---

## System Architecture

```
  BROWSER (Next.js SPA)
  ┌──────────────────────────────────────────────────────────┐
  │  ┌─────────────┐  ┌──────────────┐  ┌────────────────┐  │
  │  │ Interview    │  │ Dashboard    │  │ Career Coach   │  │
  │  │ - Mic/Audio  │  │ - Sessions   │  │ - Gap Analysis │  │
  │  │ - Transcript │  │ - Scores     │  │ - Learning     │  │
  │  │ - Controls   │  │ - JD Manager │  │ - Job Search   │  │
  │  └──────┬───────┘  └──────┬───────┘  └───────┬────────┘  │
  │         │    WebSocket     │  REST            │  REST     │
  └─────────┼─────────────────┼──────────────────┼───────────┘
            │                 │                  │
  ┌─────────▼─────────────────▼──────────────────▼───────────┐
  │  CLOUD RUN: interviewai-api (FastAPI + uvicorn)          │
  │                                                           │
  │  ┌───────────────────────────────────────────────────┐   │
  │  │  Auth Middleware (Firebase JWT verification)       │   │
  │  └───────────────────────────────────────────────────┘   │
  │                                                           │
  │  /ws/interview    /api/sessions   /api/career  /api/jobs  │
  │       │                │               │            │     │
  └───────┼────────────────┼───────────────┼────────────┼─────┘
          │                │               │            │
   ┌──────▼──────┐  ┌──────▼─────┐  ┌──────▼─────┐ ┌───▼──────┐
   │ Gemini Live │  │ Firestore  │  │ Gemini 2.5 │ │ SerpAPI  │
   │ API (WSS)   │  │            │  │ Flash/Pro  │ │ (Google  │
   │ Bidir audio │  │ users      │  │ JD parse   │ │  Jobs)   │
   │ Fn calling  │  │ sessions   │  │ Eval       │ │          │
   │ Barge-in    │  │ questions  │  │ Career     │ │          │
   │ 70 languages│  │ careers    │  │ coach      │ │          │
   └─────────────┘  └────────────┘  └────────────┘ └──────────┘
                    ┌────────────┐
                    │ GCS        │
                    │ Recordings │
                    │ Resumes    │
                    └────────────┘
```

**Stack:**
- **Frontend:** Next.js 16 / React 19 / TypeScript / Tailwind CSS / Recharts
- **Backend:** Python 3.12 / FastAPI / Uvicorn
- **Database:** Google Firestore
- **Storage:** Google Cloud Storage (audio recordings, resumes)
- **Auth:** Firebase Authentication (Google Sign-In)
- **AI:** Gemini Live API (voice), Gemini 2.5 Flash (eval), Gemini 2.5 Pro (analysis)
- **Deployment:** Google Cloud Run (us-central1)

---

## Real-Time Interview Flow

This is the most architecturally critical component.

```
  USER BROWSER                    CLOUD RUN                     GEMINI LIVE API
  ─────────────                   ─────────                     ──────────────

  1. Click "Start Interview"
     │
     ├──WSS──▶ /ws/interview?token=JWT&session_id=X
     │              │
     │         Verify JWT, load session config
     │         Build system prompt (role + level + JD + questions + rubrics)
     │              │
     │              ├───WSS──▶ Open Gemini Live session
     │              │          (system instruction embedded)
     │              │
     │              │◀──audio── Gemini speaks first question
     │◀──audio──────┤
     │  Play via AudioContext
     │
  2. User speaks answer
     │──PCM 16-bit──▶  Forward directly ──▶  Gemini processes
     │   16kHz chunks     (no buffering)      (supports barge-in)
     │
  3. Gemini evaluates + responds
     │              │◀── audio + function_call(evaluate_answer) ──┤
     │              │
     │              │  Store eval in Firestore
     │              │  Relay audio to browser
     │◀──audio──────┤
     │◀──transcript─┤
     │◀──eval_meta──┤ (partial score, shown subtly)
     │
  4. Repeat 2-3 for each question (10-15 questions)
     │
  5. Session complete
     │              │◀── function_call(end_interview) ──┤
     │              │
     │              │  Save recording to GCS
     │              │  Trigger deep eval (Gemini 2.5 Pro)
     │              │  Generate session report
     │◀──report─────┤
     │◀──ws_close───┤
```

### Latency Budget (voice-only, no avatar overhead)

| Hop | Target | Notes |
|-----|--------|-------|
| User audio → server | <50ms | Direct WS, 20ms PCM chunks |
| Server → Gemini Live | <50ms | Same GCP region (us-central1) |
| Gemini processing | ~200-500ms | Native low-latency |
| Gemini audio → server → browser | <100ms | Direct relay, no transcoding |
| **Total: speak → hear response** | **<500ms** | **Conversational feel** |

### WebSocket Session Handler (pseudocode)

```python
@app.websocket("/ws/interview")
async def interview_websocket(ws: WebSocket):
    await ws.accept()

    # 1. Authenticate
    token = ws.query_params.get("token")
    user = verify_firebase_token(token)

    # 2. Load session config
    session_id = ws.query_params.get("session_id")
    session = await load_session(session_id)

    # 3. Build system prompt
    system_prompt = build_interview_prompt(
        role=session.role,
        level=session.level,
        jd=session.jd_parsed,
        question_plan=session.question_plan
    )

    # 4. Open Gemini Live connection
    gemini_ws = await connect_gemini_live(system_prompt)

    # 5. Run concurrent tasks
    await asyncio.gather(
        relay_user_audio(ws, gemini_ws),           # user → gemini
        relay_gemini_to_client(gemini_ws, ws),     # gemini → user
        handle_control_messages(ws, session),       # state management
        record_audio(session),                     # save to GCS
    )
```

---

## Core Features (Prioritized)

### P0 — MVP (Weeks 1-6)

1. **Real-time voice interview** via Gemini Live (WebSocket, bidirectional audio)
2. **JD ingestion** — paste/upload, AI parses into structured requirements
3. **Level-calibrated questions** — Analyst, Mid, Senior (3 levels for MVP)
4. **Real-time evaluation** — Gemini Live function calls score each answer live
5. **Post-session deep eval** — Gemini 2.5 Pro generates detailed report with model answers
6. **Transcript + audio recording** — playback with synced transcript
7. **Firebase Auth** (Google Sign-In)
8. **Dashboard** — session history, score trends

### P1 — V2 (Weeks 7-12)

9. Career Coach module (skills gap analysis, learning paths)
10. Resume upload + analysis
11. Job search integration (SerpAPI / Google Jobs)
12. Lead + VP level question banks
13. Behavioral + System Design interview tracks
14. Adaptive follow-up questions based on answer quality

### P2 — V3+

15. Company-specific interview styles (Amazon LPs, Google Googliness, Meta system design)
16. Multi-panel interviews (2-3 AI interviewers with different personas)
17. Peer-to-peer mock matching
18. Enterprise tier (team analytics, custom question banks, bulk JD upload)
19. Mobile app (React Native or PWA)
20. Multilingual interviews (Gemini Live supports 70 languages)

---

## Interview Engine Design

### Dynamic-First Question Engine with Auto-Promotion to Static Bank

Every question starts **dynamic** — generated on the fly by the AI from the Knowledge Bank. When a Q&A pair proves itself through real interviews (LLM-validated quality + consistent scoring), it gets **promoted to the static bank** automatically. The static bank is never manually curated — it grows organically from battle-tested interview conversations.

```
┌─────────────────────────────────────────────────────────────────────┐
│                     QUESTION LIFECYCLE                               │
│                                                                     │
│                                                                     │
│   ┌──────────┐      ┌──────────────┐      ┌──────────────┐         │
│   │ KNOWLEDGE │ ───▶ │   DYNAMIC    │ ───▶ │  CANDIDATE   │         │
│   │ BANK      │      │   QUESTION   │      │  (staging)   │         │
│   │ (corpus)  │ RAG  │  (generated  │ used │              │         │
│   │           │      │   on the fly)│ 3x+  │ LLM validates│         │
│   └──────────┘      └──────────────┘      └──────┬───────┘         │
│                                                   │                 │
│                                              passes                 │
│                                            validation               │
│                                                   │                 │
│                                           ┌───────▼───────┐        │
│                                           │    STATIC     │        │
│                                           │    BANK       │        │
│                                           │  (promoted,   │        │
│                                           │   reusable,   │        │
│                                           │   benchmarked)│        │
│                                           └───────────────┘        │
│                                                                     │
│   Dynamic questions are ALWAYS available (infinite variety).        │
│   Static bank questions are PREFERRED when available for a topic   │
│   (proven quality, consistent scoring, faster — no generation).    │
└─────────────────────────────────────────────────────────────────────┘
```

### How It Works End-to-End

**Phase 1: Day 1 — Everything is Dynamic**

The system starts with zero static questions. The Knowledge Bank generates all questions on the fly:

```
User starts interview → JD parsed → Knowledge Bank searched
→ Gemini 2.5 Pro generates 12 tailored questions with rubrics
→ Interview happens → Answers scored → Q&A pairs saved to staging
```

**Phase 2: After ~50 interviews — Static bank starts growing**

Q&A pairs that meet promotion criteria get validated by LLM and promoted:

```
Staging Q&A pairs reviewed nightly by batch job
→ LLM validates quality (is the question clear? is the rubric fair?)
→ Cross-checks against existing static bank (no duplicates)
→ Promoted pairs become first-class static questions
→ Next interview: system prefers static questions for covered topics,
   generates dynamic questions only for gaps
```

**Phase 3: Mature system — Static bank covers most common topics**

```
Most interviews use 60-80% promoted static questions (fast, proven)
+ 20-40% dynamic questions (JD-specific gaps, novel topics, stretch)
The system keeps evolving — new topics, new papers, new patterns
get covered dynamically first, then promoted as they prove themselves
```

---

### The Promotion Pipeline (Dynamic → Candidate → Static)

#### Stage 1: Dynamic Question Generated

Every dynamically generated question gets saved to a staging collection after the interview:

```
Collection: question_staging/{id}
  Fields:
    # --- The Question ---
    question_text: string              # As asked by the AI
    topic: string                      # Classified topic
    subtopic: string                   # Specific subtopic
    type: string                       # "technical" | "behavioral" | "system_design" | "case_study"
    difficulty: string                 # "easy" | "medium" | "hard" | "expert"
    target_level: string               # Level it was generated for
    domain: string                     # "nlp" | "cv" | "mlops" | ...
    source_knowledge_chunks: string[]  # IDs of knowledge chunks used to generate it
    source_jd_id: string               # JD that triggered this question (nullable)

    # --- The Rubric (AI-generated) ---
    expected_answer: string            # Model answer from generation
    key_points: string[]               # Must-cover points
    rubric: map {
      score_1: string,
      score_2: string,
      score_3: string,
      score_4: string,
      score_5: string
    }
    follow_up_questions: string[]      # Generated follow-ups

    # --- Usage Stats (accumulate over time) ---
    times_asked: number                # How many interviews used this question
    answers: [{                        # Anonymized answer records
      answer_transcript: string,
      score: number,                   # 1-5 from real-time eval
      session_id: string,
      level: string,                   # What level the candidate was
      timestamp: timestamp
    }]
    avg_score: number                  # Running average
    score_variance: number             # How consistent is scoring?
    score_distribution: map {          # { "1": 2, "2": 5, "3": 12, ... }
      "1": number, "2": number, "3": number, "4": number, "5": number
    }

    # --- Promotion Status ---
    status: string                     # "staging" | "candidate" | "promoted" | "rejected"
    promotion_score: number            # 0-100 composite quality score
    validation_result: map {           # LLM validation output
      is_clear: boolean,
      is_fair: boolean,
      is_non_trivial: boolean,
      is_non_duplicate: boolean,
      rubric_quality: number,          # 1-5
      suggested_improvements: string,
      validated_at: timestamp
    }
    similar_static_id: string          # If duplicate detected, link to existing static Q

    created_at: timestamp
    updated_at: timestamp
```

#### Stage 2: Promotion Criteria

A question becomes a **candidate** for promotion when it meets ALL of these thresholds:

```python
PROMOTION_CRITERIA = {
    "min_times_asked": 3,              # Asked in at least 3 different interviews
    "min_unique_candidates": 3,        # Asked to at least 3 different users
    "max_score_variance": 1.5,         # Scores are consistent (not random)
    "min_score_spread": 2,             # Question differentiates (not everyone scores the same)
    "score_distribution_check": True,  # Not all 5s or all 1s — has a bell-curve-ish spread
    "min_avg_score": 2.0,              # Not impossibly hard (avg > 2)
    "max_avg_score": 4.5,              # Not trivially easy (avg < 4.5)
}
```

#### Stage 3: LLM Validation (Gemini 2.5 Pro)

When a question meets promotion criteria, it goes through LLM validation:

```python
VALIDATION_PROMPT = """
You are a senior interview design expert. Evaluate this interview question
for inclusion in a permanent question bank.

QUESTION: {question_text}
TOPIC: {topic} / {subtopic}
TARGET LEVEL: {target_level}
DIFFICULTY: {difficulty}

RUBRIC:
{rubric}

EXPECTED ANSWER:
{expected_answer}

SAMPLE ANSWERS FROM REAL INTERVIEWS (anonymized):
{top_3_answers_with_scores}

EVALUATE on these criteria (1-5 each):

1. CLARITY: Is the question unambiguous? Would different interviewers interpret it the same way?
2. FAIRNESS: Does it test relevant skills without cultural/background bias?
3. DISCRIMINATION: Does it differentiate strong from weak candidates at this level?
   (Check: do high-scorers give meaningfully different answers than low-scorers?)
4. RUBRIC QUALITY: Is the rubric specific enough for consistent scoring?
   Does score_1 clearly differ from score_3 differ from score_5?
5. NON-TRIVIALITY: Is this question worth asking? Does it reveal something a resume can't?
6. NON-DUPLICATION: Given these existing static questions on the same topic:
   {existing_static_questions_same_topic}
   Is this question sufficiently different to add value?

ALSO:
- Suggest any improvements to the question wording
- Suggest any improvements to the rubric
- Suggest follow-up questions if missing
- Flag any issues (too niche, relies on specific framework, etc.)

OUTPUT (JSON):
{
  "is_clear": bool,
  "is_fair": bool,
  "is_non_trivial": bool,
  "is_non_duplicate": bool,
  "rubric_quality": 1-5,
  "overall_score": 1-5,
  "should_promote": bool,
  "improved_question_text": "..." (or null if no change needed),
  "improved_rubric": {...} (or null),
  "improved_expected_answer": "..." (or null),
  "suggested_follow_ups": [...],
  "common_mistakes_observed": [...] (from real answer analysis),
  "rejection_reason": "..." (if should_promote=false)
}
"""
```

#### Stage 4: Promotion to Static Bank

When `should_promote=true` and `overall_score >= 4`, the question graduates:

```python
async def promote_question(staging_q, validation):
    # Build the static question from staging + LLM improvements
    static_q = {
        "text": validation.get("improved_question_text") or staging_q.question_text,
        "topic": staging_q.topic,
        "subtopic": staging_q.subtopic,
        "type": staging_q.type,
        "difficulty": staging_q.difficulty,
        "target_levels": [staging_q.target_level],  # starts narrow, expands with usage
        "domain": [staging_q.domain],
        "question_text": validation.get("improved_question_text") or staging_q.question_text,
        "expected_answer": validation.get("improved_expected_answer") or staging_q.expected_answer,
        "key_points": staging_q.key_points,
        "common_mistakes": validation.get("common_mistakes_observed", []),
        "follow_up_questions": validation.get("suggested_follow_ups") or staging_q.follow_up_questions,
        "rubric": validation.get("improved_rubric") or staging_q.rubric,
        "difficulty_chain_id": None,  # linked later when related questions are promoted
        "times_asked": staging_q.times_asked,
        "avg_score": staging_q.avg_score,
        "origin": "auto_promoted",     # vs "manual" for any hand-curated questions
        "origin_staging_id": staging_q.id,
        "promoted_at": now(),
        "promotion_score": validation["overall_score"],
        "tags": staging_q.tags,
        "created_at": now()
    }

    # Save to static bank
    doc_ref = db.collection("question_bank").add(static_q)

    # Update staging record
    staging_q.status = "promoted"
    staging_q.promoted_to = doc_ref.id

    # Auto-link difficulty chains
    await link_difficulty_chain(doc_ref.id, static_q)

    return doc_ref.id
```

#### Auto-Linking Difficulty Chains

When a new question is promoted, the system checks if related questions exist at other difficulty levels:

```python
async def link_difficulty_chain(new_q_id, new_q):
    # Find existing static questions on the same subtopic
    related = query_firestore("question_bank",
        where=[("subtopic", "==", new_q["subtopic"]),
               ("difficulty", "!=", new_q["difficulty"])])

    if related:
        # Check if they share a chain already
        existing_chain = next((q.difficulty_chain_id for q in related if q.difficulty_chain_id), None)

        if existing_chain:
            # Add to existing chain
            update_doc(new_q_id, {"difficulty_chain_id": existing_chain})
        else:
            # Create new chain
            chain_id = f"chain_{new_q['subtopic']}_{generate_id()}"
            for q in related + [new_q]:
                update_doc(q.id, {"difficulty_chain_id": chain_id})
    else:
        # First question for this subtopic — no chain yet
        pass
```

---

### The Promotion Batch Job

Runs nightly (or on-demand via admin API):

```python
async def promotion_pipeline():
    """Nightly batch job: review staging questions, validate, promote."""

    # 1. Find candidates that meet promotion criteria
    candidates = query_firestore("question_staging",
        where=[("status", "==", "staging"),
               ("times_asked", ">=", PROMOTION_CRITERIA["min_times_asked"])])

    promoted = 0
    rejected = 0

    for q in candidates:
        # 2. Check quantitative criteria
        if not meets_promotion_criteria(q):
            continue

        # 3. Mark as candidate
        q.status = "candidate"
        save(q)

        # 4. Check for near-duplicates in existing static bank
        similar = await find_similar_static(q.question_text, threshold=0.92)
        if similar:
            q.status = "rejected"
            q.similar_static_id = similar.id
            q.validation_result = {"rejection_reason": f"Too similar to static Q: {similar.id}"}
            save(q)
            rejected += 1
            continue

        # 5. LLM validation
        existing_static = await get_static_questions_for_topic(q.topic, q.subtopic)
        top_answers = get_top_answers(q, count=3)
        validation = await validate_with_llm(q, existing_static, top_answers)

        q.validation_result = validation
        q.promotion_score = validation["overall_score"]

        if validation["should_promote"] and validation["overall_score"] >= 4:
            # 6. Promote!
            static_id = await promote_question(q, validation)
            q.status = "promoted"
            promoted += 1
        else:
            q.status = "rejected"
            rejected += 1

        save(q)

    log(f"Promotion pipeline: {promoted} promoted, {rejected} rejected, "
        f"{len(candidates)} reviewed")
    return {"promoted": promoted, "rejected": rejected}
```

---

### Question Selection: Static-Preferred, Dynamic-Filled

When building a question plan for an interview, the system **prefers** promoted static questions (proven quality, no generation latency) and fills gaps with dynamic questions:

```python
async def build_question_plan(session_config, user_profile):
    """Build interview question plan: static-preferred, dynamic-filled."""

    jd = session_config.jd_parsed
    level = session_config.level
    domain = session_config.domain
    focus_areas = jd.interview_focus_areas if jd else get_default_focus_areas(domain)
    total_questions = 12

    # Determine topic distribution from focus areas
    topic_slots = distribute_topics(focus_areas, total_questions)
    # e.g., {"nlp": 3, "system_design": 2, "mlops": 2, "behavioral": 3, "case_study": 2}

    plan = []

    for topic, count in topic_slots.items():
        # --- TRY STATIC FIRST ---
        static_qs = await get_static_questions(
            topic=topic,
            level=level,
            count=count,
            exclude_ids=user_profile.recent_question_ids  # no repeats
        )

        plan.extend([{"source": "static", "question": q} for q in static_qs])
        remaining = count - len(static_qs)

        # --- FILL GAPS WITH DYNAMIC ---
        if remaining > 0:
            # Retrieve knowledge for this topic
            knowledge = await vector_search_knowledge(
                query=f"{topic} {domain} {level}",
                filter_depth=get_depth_for_level(level),
                top_k=10
            )
            patterns = await get_question_patterns(topic, level)
            industry = await get_industry_intel(jd.company if jd else None)

            # Generate dynamic questions
            dynamic_qs = await generate_dynamic_questions(
                count=remaining,
                topic=topic,
                level=level,
                jd=jd,
                knowledge_chunks=knowledge,
                patterns=patterns,
                industry_intel=industry,
                existing_plan=plan  # avoid overlap with already-selected questions
            )

            plan.extend([{"source": "dynamic", "question": q} for q in dynamic_qs])

    # Order: warmup → core → stretch → closing
    plan = order_questions(plan, level)

    return plan
```

**What this means in practice:**

| System Maturity | Static % | Dynamic % | Experience |
|-----------------|----------|-----------|------------|
| Week 1 (launch) | 0% | 100% | All questions AI-generated, every session unique |
| Month 1 (~200 interviews) | ~20% | ~80% | Best questions starting to get reused |
| Month 3 (~1000 interviews) | ~50% | ~50% | Strong coverage of common topics |
| Month 6+ | ~70% | ~30% | Most topics covered, dynamic only for JD-specific/novel |

The static bank grows indefinitely. Dynamic questions ensure **no two interviews are exactly the same**, even for repeat users on the same topic — because the Knowledge Bank + JD context always adds novelty.

---

### Static Bank Schema (graduated questions)

```
Collection: question_bank/{qid}
  Fields:
    # --- Core Question ---
    text: string                       # The question (possibly LLM-improved)
    topic: string                      # "ml_fundamentals" | "deep_learning" | "nlp" | ...
    subtopic: string                   # "gradient_descent" | "attention_mechanisms" | ...
    type: string                       # "technical" | "behavioral" | "system_design" | "case_study"
    difficulty: string                 # "easy" | "medium" | "hard" | "expert"
    target_levels: string[]            # ["analyst", "mid"] — which levels this fits
    domain: string[]                   # ["general", "nlp", "cv"]

    # --- Answer Guide ---
    expected_answer: string            # Model answer (what a 5/5 sounds like)
    key_points: string[]               # Must-cover points for full marks
    common_mistakes: string[]          # Observed wrong answers (from real interviews!)
    follow_up_questions: string[]      # Proven follow-ups

    # --- Scoring ---
    rubric: map {
      score_1: string,                 # "Cannot explain the concept at all"
      score_2: string,                 # "Partial understanding, major gaps"
      score_3: string,                 # "Correct basics, missing nuance"
      score_4: string,                 # "Strong answer with good depth"
      score_5: string                  # "Exceptional — goes beyond expected"
    }
    difficulty_chain_id: string        # Links easy → medium → hard → expert variants

    # --- Usage Stats ---
    times_asked: number                # Lifetime usage counter
    avg_score: number                  # Running average across all users
    score_distribution: map            # { "1": 2, "2": 5, "3": 12, "4": 8, "5": 3 }

    # --- Provenance ---
    origin: string                     # "auto_promoted" | "manual"
    origin_staging_id: string          # Link back to staging record (if auto)
    promotion_score: number            # LLM validation score (1-5)
    promoted_at: timestamp

    tags: string[]
    created_at: timestamp
    updated_at: timestamp
```

**Topic taxonomy (applies to both static and dynamic):**

```
AI/ML Interview Topics
│
├── ML Fundamentals
│   ├── Supervised Learning (regression, classification, metrics)
│   ├── Unsupervised Learning (clustering, dimensionality reduction)
│   ├── Feature Engineering
│   ├── Model Selection & Validation (cross-validation, bias-variance)
│   └── Optimization (gradient descent, learning rates, regularization)
│
├── Deep Learning
│   ├── Neural Network Architectures (CNN, RNN, Transformer)
│   ├── Training Dynamics (batch norm, dropout, initialization)
│   ├── Transfer Learning & Fine-tuning
│   ├── Generative Models (GANs, VAEs, Diffusion)
│   └── Attention Mechanisms & Transformers
│
├── NLP
│   ├── Text Processing & Embeddings
│   ├── Language Models (BERT, GPT, T5)
│   ├── Information Extraction, NER, Relation Extraction
│   ├── RAG, Vector Search, Semantic Search
│   └── LLM Application Design (prompt engineering, agents, tool use)
│
├── Computer Vision
│   ├── Image Classification & Object Detection
│   ├── Segmentation, Tracking
│   ├── Video Understanding
│   └── Multimodal Models
│
├── MLOps & Infrastructure
│   ├── Model Serving & Deployment
│   ├── Monitoring & Drift Detection
│   ├── Feature Stores
│   ├── Experiment Tracking
│   └── CI/CD for ML
│
├── System Design (ML-specific)
│   ├── Recommendation Systems
│   ├── Search & Ranking
│   ├── Fraud Detection
│   ├── Real-time ML Pipelines
│   └── Training Infrastructure at Scale
│
├── Behavioral & Leadership
│   ├── STAR Method Stories
│   ├── Conflict Resolution
│   ├── Project Scoping & Prioritization
│   ├── Technical Communication
│   ├── Team Building & Mentorship
│   └── Strategy & Vision (VP-level)
│
└── Case Study
    ├── Business Problem → ML Solution
    ├── Data Strategy
    ├── Metric Design
    └── A/B Testing & Experimentation
```

**Level calibration matrix:**

| Topic | Analyst | Mid-Level | Senior | Lead | VP |
|-------|---------|-----------|--------|------|-----|
| ML Fundamentals | Explain concepts | Apply + trade-offs | Design + debug | Evaluate approaches | Strategic investment |
| Deep Learning | Architecture basics | Train + tune | Novel architectures | Research direction | Build-vs-buy |
| System Design | Component understanding | Single-service | End-to-end system | Multi-system integration | Org-wide platform strategy |
| Behavioral | Teamwork, learning | Project leadership | Cross-team influence | Team building | Org design, culture |
| Case Study | Identify ML opportunity | Solution design | Full proposal w/ risks | Portfolio prioritization | Board-level pitch |

---

### Dynamic Knowledge Bank (RAG — the source of all questions)

A structured, searchable corpus of AI/ML domain knowledge that the AI taps into in real-time to **generate tailored questions on the fly** — not pick from a list.

```
┌─────────────────────────────────────────────────────────────────┐
│                        KNOWLEDGE BANK                           │
│                                                                 │
│  ┌───────────────┐  ┌────────────────┐  ┌───────────────────┐  │
│  │ Domain Corpus  │  │ Industry Intel │  │ Question Patterns │  │
│  │               │  │                │  │                   │  │
│  │ ML papers     │  │ Company blogs  │  │ Interview archetypes│
│  │ Textbooks     │  │ Tech reports   │  │ STAR templates     │
│  │ Documentation │  │ Job market     │  │ System design      │
│  │ Best practices│  │ trends         │  │ frameworks         │
│  │ Case studies  │  │ Salary data    │  │ Case study         │
│  │ Frameworks    │  │ Hiring bar     │  │ scaffolds          │
│  └───────┬───────┘  └───────┬────────┘  └─────────┬─────────┘  │
│          │                  │                      │            │
│          └──────────────────┼──────────────────────┘            │
│                             │                                   │
│                    ┌────────▼────────┐                          │
│                    │  Vector Index   │                          │
│                    │  (Vertex AI     │                          │
│                    │   Embeddings +  │                          │
│                    │   Firestore)    │                          │
│                    └────────┬────────┘                          │
└─────────────────────────────┼───────────────────────────────────┘
                              │
                    ┌─────────▼──────────┐
                    │  Question Generator │
                    │  (Gemini 2.5 Pro)   │
                    │                     │
                    │  Inputs:            │
                    │  - Retrieved context│
                    │  - JD requirements  │
                    │  - Candidate level  │
                    │  - Live performance │
                    │  - Answer history   │
                    │                     │
                    │  Output:            │
                    │  - Tailored question│
                    │  - Expected answer  │
                    │  - Scoring rubric   │
                    │  - Follow-up chains │
                    └─────────────────────┘
```

### Knowledge Bank: Three Layers

#### Layer 1 — Domain Corpus (the "textbook brain")

Structured knowledge chunks covering the full AI/ML domain, stored as embeddings in Vertex AI Vector Search + metadata in Firestore.

```
Collection: knowledge_bank/{chunk_id}
  Fields:
    text: string                    # The knowledge chunk (200-500 tokens)
    domain: string                  # "ml_fundamentals" | "deep_learning" | "nlp" | ...
    subtopic: string                # "attention_mechanisms" | "gradient_descent" | ...
    depth_level: string             # "foundational" | "intermediate" | "advanced" | "expert" | "strategic"
    source_type: string             # "textbook" | "paper" | "documentation" | "best_practice" | "case_study"
    source_ref: string              # Citation / URL
    key_concepts: string[]          # ["self-attention", "multi-head", "QKV", "positional encoding"]
    related_skills: string[]        # ["pytorch", "transformers", "model_architecture"]
    question_hooks: string[]        # Angles this chunk can be questioned from:
                                    #   ["explain the mechanism", "compare to alternatives",
                                    #    "design a system using this", "debug a failure case",
                                    #    "evaluate ROI of adopting this"]
    interview_levels: string[]      # Which levels this is relevant for: ["mid", "senior", "lead"]
    embedding: vector               # Vertex AI text-embedding-005 (768 dims)
    tags: string[]
    created_at: timestamp
    updated_at: timestamp
```

**Content sources (seeded at build time, updated periodically):**

| Source | What It Provides | Update Frequency |
|--------|-----------------|------------------|
| ML textbook chapters (Bishop, Goodfellow, etc.) | Foundational concepts, mathematical rigor | Static |
| arXiv papers (curated top 200) | Cutting-edge: Transformers, Diffusion, RLHF, MoE, SSMs | Quarterly |
| Framework docs (PyTorch, TensorFlow, JAX, HuggingFace) | Implementation patterns, API knowledge | Monthly |
| MLOps guides (Kubeflow, MLflow, Vertex AI, SageMaker) | Infrastructure, deployment, monitoring | Monthly |
| Industry case studies (Google, Meta, Netflix, Uber, Airbnb) | Real-world system design, scale challenges | Quarterly |
| FAANG interview guides (public blogs, Glassdoor patterns) | Company-specific question patterns, hiring bar | Quarterly |
| AI leadership content (a16z, Sequoia, McKinsey AI reports) | Strategy, org design, ROI frameworks — VP level | Quarterly |
| Best practices / anti-patterns | Common mistakes, debugging patterns | Static |

**Chunk structure example:**

```json
{
  "text": "FlashAttention computes exact attention with O(N) memory instead of O(N²) by tiling the Q/K/V matrices into blocks that fit in SRAM, avoiding materialization of the full N×N attention matrix to HBM. This yields 2-4x speedup on A100 GPUs for sequences >1K tokens. Key trade-off: custom CUDA kernels required, not all attention variants supported (e.g., sparse patterns need separate implementations).",
  "domain": "deep_learning",
  "subtopic": "attention_mechanisms",
  "depth_level": "advanced",
  "source_type": "paper",
  "source_ref": "Dao et al., FlashAttention-2, 2023",
  "key_concepts": ["flash_attention", "memory_efficiency", "IO_awareness", "tiling", "SRAM_vs_HBM"],
  "related_skills": ["cuda", "pytorch", "gpu_optimization"],
  "question_hooks": [
    "explain_mechanism: How does FlashAttention achieve sub-quadratic memory?",
    "compare: When would you use FlashAttention vs sparse attention vs linear attention?",
    "system_design: You're training a model on 128K context — walk me through your attention strategy",
    "debug: Your FlashAttention kernel is slower than vanilla on short sequences. Why?",
    "strategic: Your team wants to adopt FlashAttention. What's the migration cost vs benefit?"
  ],
  "interview_levels": ["senior", "lead"]
}
```

#### Layer 2 — Industry Intelligence (the "market brain")

Real-world context that makes questions grounded and specific, not generic.

```
Collection: industry_intel/{id}
  Fields:
    company: string                 # "google" | "meta" | "openai" | "startup" | "enterprise"
    topic: string                   # "interview_process" | "tech_stack" | "org_structure" | "hiring_bar"
    content: string                 # The intelligence chunk
    relevance_to: string[]          # ["system_design", "behavioral", "culture_fit"]
    level_relevance: string[]       # ["senior", "lead", "vp"]
    embedding: vector
    source: string
    freshness_date: timestamp       # When this was last verified
```

**Example entries:**

```
- Google L5 ML interviews typically have 1 coding, 1 ML design, 1 system design, 1 behavioral
  (Googliness). The ML design round expects you to frame the problem, choose metrics, design
  the data pipeline, select models, and discuss serving. Interviewers look for structured thinking.

- Meta's ML team evaluates "move fast" culture fit — they want candidates who can ship
  imperfect V1s and iterate, not candidates who want to perfect before launching.

- Startup AI roles (Series A-B) prioritize generalists who can own end-to-end: data collection,
  labeling, modeling, serving, monitoring. They rarely have MLOps — you ARE the MLOps.

- VP-level AI interviews at Fortune 500 companies focus on: (1) how you'd build the AI org
  from scratch, (2) how you justify AI investment to a skeptical board, (3) build-vs-buy
  decisions, (4) responsible AI governance.
```

#### Layer 3 — Question Pattern Templates (the "interviewer brain")

Meta-patterns for how to construct questions, not the questions themselves. These teach the AI how to be a good interviewer.

```
Collection: question_patterns/{id}
  Fields:
    pattern_name: string            # "depth_probe" | "system_design_scaffold" | "case_study_framework"
    interview_type: string          # "technical" | "behavioral" | "system_design" | "case_study"
    applicable_levels: string[]     # ["analyst", "mid", "senior", "lead", "vp"]
    template: string                # The pattern with {placeholders}
    usage_guidance: string          # When to use this pattern
    difficulty_variants: map {      # How to adjust for level
      "analyst": string,
      "mid": string,
      "senior": string,
      "lead": string,
      "vp": string
    }
    follow_up_chains: string[]      # Ordered follow-up patterns based on answer quality
    scoring_rubric_template: string # How to evaluate answers to this pattern
```

**Example patterns:**

```yaml
# Pattern: Concept → Application → Trade-off → Scale
pattern_name: "depth_ladder"
template: |
  Level 1 (test understanding):
    "Can you explain {concept} and why it matters?"
  Level 2 (test application):
    "You need to implement {concept} for {real_scenario}. Walk me through your approach."
  Level 3 (test trade-offs):
    "What are the alternatives to {concept}? When would you choose each?"
  Level 4 (test at scale):
    "How does {concept} behave at {scale_factor}? What breaks?"
  Level 5 (test strategic thinking):
    "Your org is deciding whether to invest in {concept} vs {alternative}. How do you frame this for leadership?"

difficulty_variants:
  analyst: "Stop at Level 1-2"
  mid: "Levels 1-3"
  senior: "Levels 2-4"
  lead: "Levels 3-5"
  vp: "Levels 4-5 only"

follow_up_chains:
  - "If score >= 4: escalate to next level"
  - "If score <= 2: ask them to explain with a specific example"
  - "If score == 3: probe the weakest sub-point"
```

```yaml
# Pattern: System Design (ML-specific)
pattern_name: "ml_system_design"
template: |
  "Design a {system_type} for {company_context}."

  Expected structure (guide the candidate through if stuck):
  1. Clarify requirements: What's the objective? What metrics?
  2. Data: What data exists? How to collect/label?
  3. Features: What signals matter? Feature engineering?
  4. Model: What architecture? Why? Alternatives?
  5. Serving: Online vs batch? Latency requirements?
  6. Monitoring: How do you detect drift? Feedback loops?
  7. Iteration: How do you A/B test? How do you retrain?

difficulty_variants:
  mid: "Focus on steps 1-4, accept hand-waving on serving"
  senior: "Expect depth on all 7, push on trade-offs"
  lead: "Add: how do you staff this? Timelines? Dependencies?"
  vp: "Add: how do you pitch this to the board? What's the ROI?"
```

```yaml
# Pattern: Behavioral (STAR with probes)
pattern_name: "behavioral_star"
template: |
  "Tell me about a time you {behavioral_scenario}."

  After their story, probe:
  - "What was the hardest part?" (tests self-awareness)
  - "What would you do differently?" (tests growth mindset)
  - "How did you measure success?" (tests rigor)

difficulty_variants:
  analyst: "Accept shorter stories, simpler impact"
  mid: "Expect concrete metrics and team context"
  senior: "Expect cross-team impact, technical leadership"
  lead: "Expect org-level decisions, people management"
  vp: "Expect strategic bets, board-level communication"
```

---

### How the AI Generates Tailored Questions (Real-Time RAG)

The AI doesn't pick from a static list. It **constructs questions in real-time** by pulling from the knowledge bank.

```
┌──────────────────────────────────────────────────────────────────────┐
│                    QUESTION GENERATION PIPELINE                      │
│                                                                      │
│  INPUTS (available at session start):                                │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────┐               │
│  │ Parsed JD    │  │ User Profile │  │ Session Config│               │
│  │ - skills     │  │ - level      │  │ - type        │               │
│  │ - domain     │  │ - weak areas │  │ - duration    │               │
│  │ - focus areas│  │ - past scores│  │ - domain      │               │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘               │
│         │                 │                  │                        │
│         └─────────────────┼──────────────────┘                       │
│                           │                                          │
│                  ┌────────▼────────┐                                 │
│                  │ PRE-SESSION     │                                  │
│                  │ RETRIEVAL       │                                  │
│                  │                 │                                  │
│                  │ 1. Embed JD     │                                  │
│                  │    skills +     │                                  │
│                  │    focus areas  │                                  │
│                  │                 │                                  │
│                  │ 2. Vector search│                                  │
│                  │    knowledge_   │                                  │
│                  │    bank for     │                                  │
│                  │    relevant     │                                  │
│                  │    chunks       │                                  │
│                  │    (top 30-50)  │                                  │
│                  │                 │                                  │
│                  │ 3. Retrieve     │                                  │
│                  │    matching     │                                  │
│                  │    question     │                                  │
│                  │    patterns     │                                  │
│                  │                 │                                  │
│                  │ 4. Retrieve     │                                  │
│                  │    industry     │                                  │
│                  │    intel for    │                                  │
│                  │    company/     │                                  │
│                  │    domain       │                                  │
│                  └────────┬────────┘                                  │
│                           │                                          │
│                  ┌────────▼────────┐                                  │
│                  │ QUESTION PLAN   │                                  │
│                  │ GENERATION      │                                  │
│                  │ (Gemini 2.5 Pro)│                                  │
│                  │                 │                                  │
│                  │ "Given this     │                                  │
│                  │  knowledge      │                                  │
│                  │  context,       │                                  │
│                  │  JD, level,     │                                  │
│                  │  and patterns:  │                                  │
│                  │  generate 12    │                                  │
│                  │  questions with │                                  │
│                  │  rubrics"       │                                  │
│                  └────────┬────────┘                                  │
│                           │                                          │
│  OUTPUT: question_plan[]                                             │
│  Each question has:                                                  │
│  - question_text (tailored to JD + level)                           │
│  - knowledge_context (the chunks it draws from)                     │
│  - expected_answer (what a great answer looks like at this level)   │
│  - scoring_rubric (specific to this question)                       │
│  - difficulty_chain_id (links to easier/harder variants)            │
│  - follow_up_triggers (what to probe based on answer quality)       │
│  - escalation_path (harder version if candidate aces it)            │
│  - deescalation_path (easier version if candidate struggles)        │
└──────────────────────────────────────────────────────────────────────┘
```

### Live Adaptation: How Questions Change Mid-Interview

The question plan is a **starting point, not a script**. During the interview, three mechanisms adapt it in real-time:

#### Mechanism 1: Gemini Live's Conversational Intelligence

Gemini Live is stateful — it holds the full conversation in context. The system prompt instructs it:

```
ADAPTIVE QUESTIONING RULES:
You have a question plan, but you are an intelligent interviewer, not a script reader.

ADAPT based on the candidate's answers:
- If they mention a technology/concept you haven't asked about yet, probe it
  ("You mentioned using RLHF — tell me more about that experience")
- If they reveal a gap, explore it naturally
  ("You said you haven't worked with distributed training — let's talk about how you'd approach it")
- If they go deep on something interesting, follow the thread before returning to the plan
- If an answer reveals expertise beyond their stated level, escalate the difficulty

YOU HAVE ACCESS TO THIS KNOWLEDGE CONTEXT:
{retrieved_knowledge_chunks}

Use this context to:
- Verify accuracy of candidate's answers
- Generate follow-up questions grounded in real technical details
- Challenge hand-wavy answers with specific counter-examples from the knowledge base
- Suggest "what about X?" where X is a real alternative from the corpus
```

#### Mechanism 2: Server-Side RAG Mid-Interview (Dynamic Retrieval)

When Gemini calls `evaluate_answer`, the server can **retrieve additional knowledge** based on the answer content and inject it back:

```python
async def handle_eval_and_adapt(eval_data, answer_transcript, session, gemini_ws):
    score = eval_data["composite"]

    # Track rolling performance
    session.scores.append(score)
    rolling_avg = mean(session.scores[-3:])

    # === DYNAMIC RETRIEVAL based on what candidate just said ===

    # 1. Extract concepts mentioned in the answer
    mentioned_concepts = eval_data.get("key_points_covered", [])
    missed_concepts = eval_data.get("missed_points", [])

    # 2. If candidate mentioned something unexpected, retrieve knowledge about it
    if mentioned_concepts:
        new_context = await vector_search(
            query=answer_transcript,
            filter_domain=session.domain,
            filter_depth=get_depth_for_score(score),  # higher score → deeper knowledge
            top_k=5
        )

    # 3. If candidate missed key points, retrieve simpler explanations
    if missed_concepts and score <= 2:
        remedial_context = await vector_search(
            query=" ".join(missed_concepts),
            filter_depth="foundational",
            top_k=3
        )
        new_context += remedial_context

    # === DIFFICULTY ADJUSTMENT ===

    if rolling_avg >= 4.0:
        # Candidate is strong → escalate
        adjustment = "ESCALATE: candidate is performing above level. "
        adjustment += "Ask harder questions. Use 'expert' depth knowledge. "
        adjustment += "Push on system design, trade-offs, failure modes."

        # Retrieve harder knowledge chunks
        escalation_context = await vector_search(
            query=session.current_topic,
            filter_depth="expert",
            top_k=5
        )
        new_context += escalation_context

    elif rolling_avg <= 2.0:
        # Candidate is struggling → support
        adjustment = "DE-ESCALATE: candidate is struggling. "
        adjustment += "Ask more foundational questions. Be encouraging. "
        adjustment += "Use 'intermediate' depth knowledge. Give hints."

        # Retrieve simpler knowledge chunks
        support_context = await vector_search(
            query=session.current_topic,
            filter_depth="intermediate",
            top_k=5
        )
        new_context += support_context

    else:
        adjustment = "MAINTAIN current difficulty level."

    # === INJECT CONTEXT BACK INTO GEMINI LIVE SESSION ===

    context_update = f"""[SYSTEM CONTEXT UPDATE]
    Candidate performance: {rolling_avg}/5 rolling average.
    Directive: {adjustment}

    Additional knowledge for your next questions:
    {format_knowledge_chunks(new_context)}

    Use this knowledge to craft your next question. Do NOT read it verbatim —
    synthesize it into a natural interview question tailored to this candidate's
    demonstrated level.
    """

    await gemini_ws.send_text(context_update)
```

#### Mechanism 3: Difficulty Chains (Pre-Linked Question Variants)

Each topic in the knowledge bank has pre-linked difficulty variants so the system can instantly swap:

```
Topic: "Model Serving"

foundational (Analyst):
  Knowledge: "Model serving deploys trained models as APIs. Common tools: TF Serving,
  TorchServe, FastAPI. Key metrics: latency, throughput, availability."
  → Question: "What happens after you train a model? How does it get to production?"

intermediate (Mid):
  Knowledge: "Serving strategies: real-time (REST/gRPC), batch, streaming.
  Optimization: quantization, distillation, ONNX runtime. Caching: feature stores,
  prediction caches. Canary deployments for safe rollout."
  → Question: "You have a model that's too slow for real-time serving at P99 < 50ms.
     Walk me through your optimization strategy."

advanced (Senior):
  Knowledge: "Multi-model serving: model routers, A/B infrastructure, shadow mode.
  GPU serving: batching strategies, dynamic batching, model parallelism for large models.
  Cost: GPU instance costs, spot vs on-demand, autoscaling policies."
  → Question: "Design the serving infrastructure for a recommendation system that
     handles 50K QPS with 5 different model variants in simultaneous A/B tests."

expert (Lead):
  Knowledge: "ML platform design: self-service deployment, model registry, automated
  canaries, rollback policies, SLO-based alerting, capacity planning across teams."
  → Question: "You're the ML platform lead. 10 teams want to deploy models. How do you
     design the serving platform so they can self-serve while maintaining SLOs?"

strategic (VP):
  Knowledge: "Build vs buy: Vertex AI vs SageMaker vs custom. TCO analysis: infra team
  cost vs managed service markup. Vendor lock-in risks. Multi-cloud strategy."
  → Question: "The CTO asks: should we build our ML platform or buy? You have 60 seconds
     to give your recommendation and defend it."
```

---

### JD → Question Generation Pipeline (Static-Preferred, Dynamic-Filled)

```
Step 1: Parse JD (Gemini 2.5 Pro)
  Input:  Raw JD text (pasted or uploaded)
  Output: {
    title, inferred_level, company, domain,
    required_skills[{skill, proficiency}],
    preferred_skills[],
    responsibilities[],
    interview_focus_areas[{area, weight, question_types[]}],
    red_flags_to_probe[],
    culture_signals[]
  }

Step 2: Distribute topics based on JD focus areas
  e.g., 12 questions: {"nlp": 3, "system_design": 2, "mlops": 2, "behavioral": 3, "case_study": 2}

Step 3: For each topic slot — try static first, fill with dynamic
  For each (topic, count):
    a) Query question_bank (static) by topic + level + difficulty
       → Exclude questions user saw in last 5 sessions
       → Take up to `count` matching questions
    b) If static doesn't cover all slots:
       → Retrieve knowledge chunks via vector search
       → Generate remaining questions dynamically via Gemini 2.5 Pro

Step 4 (dynamic generation detail):
  Input: parsed JD + retrieved knowledge + question patterns + user profile
  Prompt:
    "You are creating an interview question plan.
     Use the knowledge context below to generate questions that are:
     1. Specific to this JD (not generic 'tell me about ML')
     2. Grounded in real technical details from the knowledge base
     3. Calibrated to {level} difficulty
     4. Covering the focus areas with these weights: {weights}

     For each question, provide:
     - The question text
     - What a strong answer looks like (drawn from knowledge context)
     - What a weak answer looks like
     - Scoring rubric (1-5 with specific criteria)
     - One escalation variant (if candidate aces it)
     - One de-escalation variant (if candidate struggles)
     - Two follow-up probes

     Knowledge context:
     {retrieved_chunks}

     Question patterns to use:
     {retrieved_patterns}

     Company-specific intelligence:
     {industry_intel}"

  Output: remaining questions with rubrics and variants

Step 5: Assemble final plan (static + dynamic merged)

  Example — mature system with partial static coverage:

  ┌─────────┬──────────┬────────────────────────────────────────────┐
  │ Slot    │ Source   │ Question                                   │
  ├─────────┼──────────┼────────────────────────────────────────────┤
  │ Q1      │ STATIC   │ Behavioral warmup (promoted, proven)       │
  │ Q2      │ STATIC   │ NLP fundamentals (promoted, avg_score 3.2) │
  │ Q3      │ DYNAMIC  │ JD-specific: "RAG at scale" (no static yet)│
  │ Q4      │ STATIC   │ Transformer trade-offs (promoted)          │
  │ Q5      │ DYNAMIC  │ JD-specific: company's tech stack scenario │
  │ Q6      │ STATIC   │ MLOps monitoring (promoted)                │
  │ Q7      │ DYNAMIC  │ JD-specific: team leadership scenario      │
  │ Q8      │ DYNAMIC  │ Stretch: novel topic from knowledge bank   │
  │ Q9      │ STATIC   │ System design: RecSys (promoted)           │
  │ Q10     │ DYNAMIC  │ JD red_flag probe (always dynamic)         │
  │ Q11     │ STATIC   │ Behavioral: conflict resolution (promoted) │
  │ Q12     │ DYNAMIC  │ Closing: tailored to JD culture signals    │
  └─────────┴──────────┴────────────────────────────────────────────┘

  Static questions: proven rubrics, consistent scoring, fast (no gen).
  Dynamic questions: AI-generated rubrics, JD-tailored, saved to staging after interview.
  ALL dynamic Q&A pairs saved to question_staging for future promotion.

Step 6: Embed in Gemini Live system prompt
  The question plan + retrieved knowledge context are included
  in the system instruction so Gemini Live can:
  - Ask static questions verbatim (with their proven follow-ups)
  - Ask dynamic questions naturally (using knowledge context)
  - Swap difficulty via chains (static) or new retrieval (dynamic)
  - Mid-interview: if candidate goes somewhere unexpected,
    call request_knowledge() for real-time retrieval
```

---

### How Different Input Sources Feed the Knowledge Bank

```
┌──────────────────────────────────────────────────────────┐
│                   KNOWLEDGE INGESTION                     │
│                                                           │
│  ┌─────────────┐   Admin uploads new content via:        │
│  │ Admin API    │   POST /api/admin/knowledge/ingest     │
│  │ or CLI       │   - PDF papers → chunk + embed         │
│  │ or Scheduled │   - Blog posts → chunk + embed         │
│  │   Pipeline   │   - Docs pages → chunk + embed         │
│  └──────┬───────┘   - Case studies → chunk + embed       │
│         │                                                 │
│         ▼                                                 │
│  ┌──────────────┐                                        │
│  │ Chunker      │   Split into 200-500 token chunks      │
│  │ (Gemini)     │   Add metadata: domain, depth, concepts│
│  └──────┬───────┘                                        │
│         │                                                 │
│         ▼                                                 │
│  ┌──────────────┐                                        │
│  │ Embedder     │   Vertex AI text-embedding-005         │
│  │              │   768-dim vectors                       │
│  └──────┬───────┘                                        │
│         │                                                 │
│         ▼                                                 │
│  ┌──────────────┐   ┌──────────────┐                     │
│  │ Firestore    │   │ Vector Index  │                     │
│  │ (metadata +  │   │ (Vertex AI   │                     │
│  │  full text)  │   │  Matching    │                     │
│  └──────────────┘   │  Engine or   │                     │
│                     │  Firestore   │                     │
│                     │  Vector)     │                     │
│                     └──────────────┘                     │
└──────────────────────────────────────────────────────────┘
```

**Firestore native vector search** (simplest for MVP):
- Firestore supports vector fields with KNN queries
- No separate vector DB needed
- Filter by metadata (domain, depth_level) + vector similarity
- Scales automatically

**Upgrade path (V2):** Vertex AI Matching Engine for larger corpus (>100K chunks) with ANN search.

---

### Knowledge Bank Seeding Plan (MVP)

| Domain | Chunks | Sources | Priority |
|--------|--------|---------|----------|
| ML Fundamentals | ~200 | Textbook summaries, scikit-learn docs | P0 Week 2 |
| Deep Learning | ~300 | Goodfellow textbook, PyTorch docs, key papers | P0 Week 2 |
| NLP / LLMs | ~250 | HuggingFace docs, key papers (Attention, BERT, GPT), RAG patterns | P0 Week 2 |
| Computer Vision | ~150 | Key papers, torchvision docs | P1 |
| MLOps | ~200 | MLflow/Kubeflow docs, best practices guides | P0 Week 2 |
| System Design | ~200 | Industry case studies (Uber ML, Netflix RecSys, Google Search) | P0 Week 3 |
| Behavioral/Leadership | ~100 | STAR templates, leadership frameworks, management patterns | P0 Week 2 |
| Industry Intel | ~100 | FAANG interview guides, company tech blogs, hiring bar info | P1 |
| Question Patterns | ~50 | Interview archetypes, design scaffolds, case frameworks | P0 Week 2 |
| **Total MVP** | **~1,500** | | |

Each chunk costs ~$0.0001 to embed (Vertex AI pricing). Total seeding: ~$0.15.

---

### Real-Time Evaluation (via Gemini Live Function Calling)

Gemini Live supports function calling, which lets the AI naturally converse while emitting structured evaluation data the server captures:

```python
tools = [{
    "function_declarations": [
        {
            "name": "evaluate_answer",
            "description": "Called after the candidate finishes answering a question",
            "parameters": {
                "type": "object",
                "properties": {
                    "question_id": {"type": "string"},
                    "technical_accuracy": {"type": "number", "minimum": 1, "maximum": 5},
                    "depth": {"type": "number", "minimum": 1, "maximum": 5},
                    "communication": {"type": "number", "minimum": 1, "maximum": 5},
                    "key_points_covered": {"type": "array", "items": {"type": "string"}},
                    "missed_points": {"type": "array", "items": {"type": "string"}},
                    "follow_up_needed": {"type": "boolean"},
                    "candidate_mentioned_topics": {"type": "array", "items": {"type": "string"}},
                    "suggested_difficulty_shift": {"type": "string", "enum": ["escalate", "maintain", "deescalate"]}
                }
            }
        },
        {
            "name": "request_knowledge",
            "description": "Called when the AI interviewer needs additional knowledge context to ask a deeper or different question",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string"},
                    "depth_needed": {"type": "string", "enum": ["foundational", "intermediate", "advanced", "expert"]},
                    "reason": {"type": "string"}
                }
            }
        },
        {
            "name": "transition_to_next_question",
            "description": "Called when moving to the next question",
            "parameters": {
                "type": "object",
                "properties": {
                    "next_question_id": {"type": "string"},
                    "reason": {"type": "string"}
                }
            }
        },
        {
            "name": "end_interview",
            "description": "Called when all questions are completed or time is up",
            "parameters": {
                "type": "object",
                "properties": {
                    "overall_impression": {"type": "string"},
                    "recommendation": {
                        "type": "string",
                        "enum": ["strong_yes", "yes", "lean_yes", "lean_no", "no", "strong_no"]
                    }
                }
            }
        }
    ]
}]
```

**Key addition: `request_knowledge` function call.** When the AI interviewer wants to go deeper on a topic the candidate mentioned, it calls this function. The server retrieves relevant knowledge chunks and injects them back into the Gemini session. This creates a **feedback loop** where the AI can dynamically learn new context mid-interview.

**Two-level evaluation:**

1. **Real-time (during interview):** Gemini Live function calls → quick scores + difficulty shift signal → server adapts question plan + retrieves new knowledge → injects back
2. **Post-session (deep eval):** Full transcript → Gemini 2.5 Pro + full knowledge context → detailed per-question analysis with model answers, composite score, hire recommendation, personalized study plan

### Follow-Up Strategy

Embedded in the Gemini Live system prompt:

```
FOLLOW-UP STRATEGY:
After each answer, decide whether to:
1. PROBE DEEPER: If surface-level → "Can you go deeper on [specific aspect]?"
   Use your knowledge context to ask about specific details they missed.
2. CHALLENGE: If confident but potentially wrong → "What if [counterexample]?"
   Draw counter-examples from the knowledge base.
3. EXTEND: If good answer → "How would this change at 10x scale?"
4. REDIRECT: If off-topic → "That's interesting, but specifically regarding [original topic]..."
5. EXPLORE: If they mention something interesting not in the plan →
   Call request_knowledge() to get context, then ask about it.
6. ACCEPT AND MOVE ON: If thorough → natural transition to next question

Maximum 2 follow-ups per question to maintain pace.
```

### System Prompt Template

```
You are a senior {role_title} interviewer at a top-tier technology company.
You are conducting a {interview_type} interview for a {target_level} {target_role} position.

INTERVIEW CONTEXT:
{jd_summary if provided, else generic role description}

KNOWLEDGE CONTEXT (use this to verify answers and generate follow-ups):
{retrieved_knowledge_chunks — 30-50 chunks relevant to this interview}

QUESTION PLAN (adapt based on answers — this is a guide, not a script):
{generated questions with rubrics and difficulty variants}

ADAPTIVE QUESTIONING RULES:
- You have deep domain knowledge via your KNOWLEDGE CONTEXT — use it
- When a candidate mentions a concept, verify it against your knowledge
- When an answer is vague, challenge with specific details from your knowledge
- When a candidate is strong, escalate using harder knowledge chunks
- When a candidate struggles, simplify using foundational knowledge
- If you need knowledge on a topic outside your current context, call request_knowledge()
- Never ask questions where you don't know the answer yourself

BEHAVIORAL GUIDELINES:
- Maintain a professional, encouraging but rigorous tone
- For {target_level} level: {level_specific_expectations}
- Time management: ~{minutes_per_question} minutes per question
- Signal transitions naturally: "Great, let's move to..."

EVALUATION (use evaluate_answer function after each answer):
- Technical Accuracy (1-5): Correctness vs knowledge context
- Depth (1-5): Level of detail appropriate to {target_level}
- Communication (1-5): Clarity, structure, conciseness
- Note specific points covered and missed (relative to knowledge context)
- Signal difficulty shift: "escalate" | "maintain" | "deescalate"

LEVEL-SPECIFIC CALIBRATION FOR {target_level}:
{level_rubric}
```

### Level-Specific Rubrics

```
ANALYST (Entry-Level):
- Knowledge depth: foundational + intermediate chunks
- Expect: Textbook knowledge, basic Python/SQL, conceptual ML understanding
- Accept: Minor terminology gaps, theoretical answers
- Probe: "Can you explain X in simple terms?" "What tool would you use for Y?"
- Red flags: Cannot explain basic concepts, no hands-on experience

MID-LEVEL DATA SCIENTIST / ML ENGINEER:
- Knowledge depth: intermediate + advanced chunks
- Expect: Production experience, trade-off awareness, experiment design
- Accept: Gaps in adjacent areas, reasonable simplifications
- Probe: "How did you handle X at scale?" "What were the alternatives?"
- Red flags: Cannot discuss past projects concretely, no production awareness

SENIOR ML ENGINEER / STAFF:
- Knowledge depth: advanced + expert chunks
- Expect: System-level thinking, architectural decisions, mentorship evidence
- Accept: Gaps in bleeding-edge research if strong in systems
- Probe: "How would you design this from scratch?" "What would you change?"
- Red flags: Cannot reason about trade-offs, no evidence of technical leadership

AI LEAD / MANAGER:
- Knowledge depth: expert + strategic chunks
- Expect: Team management, project scoping, stakeholder communication
- Probe: "How would you prioritize?" "How do you handle disagreements?"
- Red flags: Cannot think beyond individual contributor scope

VP / DIRECTOR:
- Knowledge depth: strategic chunks only
- Expect: Organizational strategy, ROI justification, cross-functional alignment
- Probe: "How would you build this org from zero?" "Defend this investment to the board"
- Red flags: Cannot think in business terms, no evidence of org-level impact
```

---

## Backend Structure

```
interviewai/
  backend/
    main.py                          # FastAPI app, all routes, WS endpoint, middleware
    config.py                        # Environment vars, constants
    auth/
      firebase_auth.py               # JWT verification, user extraction
    interview/
      session_manager.py             # Session state machine (CRITICAL)
      gemini_live_client.py          # Gemini Live WebSocket client (CRITICAL)
      audio_pipeline.py              # Audio buffering, resampling, recording
      prompt_builder.py              # System instruction construction (CRITICAL)
    questions/
      question_bank.py               # Static bank CRUD, selection (prefer promoted)
      question_staging.py            # Staging collection: save dynamic Q&A pairs
      promotion_pipeline.py          # Nightly batch: validate + promote staging → static
      jd_parser.py                   # JD → structured data (Gemini 2.5 Pro)
      question_generator.py          # Dynamic question generation from knowledge bank
      plan_builder.py                # Merge static + dynamic into interview plan
      rubrics.py                     # Level-specific evaluation rubrics
    knowledge/
      knowledge_bank.py              # Knowledge chunk CRUD + vector search
      ingestion.py                   # PDF/blog/docs → chunk + embed pipeline
      embedder.py                    # Vertex AI text-embedding-005 client
    evaluator/
      answer_evaluator.py            # Real-time eval (from Gemini function calls)
      session_evaluator.py           # Post-session deep eval (Gemini 2.5 Pro)
      transcript_manager.py          # Transcript assembly and storage
    career/
      gap_analyzer.py                # Skills gap analysis engine
      learning_paths.py              # Path recommendations
      resume_parser.py               # PDF/DOCX extraction + analysis
    jobs/
      job_search_client.py           # SerpAPI / Google Jobs integration
      jd_normalizer.py               # Normalize JDs from different sources
    util/
      gcs_utils.py                   # GCS upload/download, signed URLs
      firestore_utils.py             # Firestore helpers
    requirements.txt
    Dockerfile
```

**Critical files (build these first):**

1. `gemini_live_client.py` — The Gemini Live API WebSocket client. Handles bidirectional audio streaming, function call interception for evaluation, session lifecycle, and reconnection. Everything depends on this.

2. `prompt_builder.py` — Constructs system instructions for Gemini Live based on role level, JD, question plan, and rubrics. The quality of the interview experience lives or dies here.

3. `session_manager.py` — Session state machine orchestrating the entire flow: connecting Gemini Live, relaying audio, recording, handling barge-in, coordinating question transitions.

---

## Frontend Structure

```
  frontend/
    src/app/
      layout.tsx                     # Root layout, auth provider, fonts
      page.tsx                       # Landing / marketing page
      dashboard/
        page.tsx                     # Session history, score trends, charts
      interview/
        page.tsx                     # Pre-interview lobby (mic check, config)
        session/
          page.tsx                   # LIVE interview room (CRITICAL)
        review/
          [sessionId]/
            page.tsx                 # Post-session review (transcript, scores)
      career/
        page.tsx                     # Career coach (gap analysis, learning paths)
      jobs/
        page.tsx                     # Job search + "prepare for this job"
      jd/
        page.tsx                     # JD upload/paste and analysis
      profile/
        page.tsx                     # User profile, settings
    lib/
      ws-manager.ts                  # WebSocket connection manager
      audio-capture.ts               # getUserMedia + PCM encoding
      audio-playback.ts              # AudioContext playback from PCM chunks
```

**Audio Capture Pipeline (browser):**

```
getUserMedia({ audio: { sampleRate: 16000, channelCount: 1 } })
  → MediaStreamSource → AudioWorkletNode
  → Convert Float32 to Int16 PCM → Buffer 20ms chunks (320 samples)
  → Send via WebSocket as binary frames
```

**Key frontend dependencies (beyond standard Next.js/Tailwind):**
- `recharts` — score visualization, radar charts
- `wavesurfer.js` — audio waveform playback on review page
- `zustand` — state management (simpler than Recoil for WS-driven state)
- `lucide-react` — icons

---

## API Endpoints

```
Authentication:
  POST   /api/auth/verify               # Verify Firebase token, create/return user

Users:
  GET    /api/users/me                   # Current user profile
  PUT    /api/users/me                   # Update profile (role, level, skills)
  POST   /api/users/me/resume            # Upload resume (PDF/DOCX)

Sessions:
  POST   /api/sessions                   # Create new interview session
  GET    /api/sessions                   # List user's sessions (paginated)
  GET    /api/sessions/{id}              # Session details + evaluation report
  GET    /api/sessions/{id}/transcript   # Full transcript with timestamps
  GET    /api/sessions/{id}/audio        # Signed URL for audio playback
  DELETE /api/sessions/{id}              # Delete session

WebSocket:
  WS     /ws/interview                   # Live interview (bidirectional audio)

Job Descriptions:
  POST   /api/jd/parse                   # Parse raw JD text → structured data
  GET    /api/jd/{id}                    # Get parsed JD
  GET    /api/jd                         # List user's parsed JDs

Questions:
  GET    /api/questions/preview          # Preview question plan for session config

Knowledge Bank (Admin):
  POST   /api/admin/knowledge/ingest     # Ingest new content (PDF, blog, docs → chunk + embed)
  GET    /api/admin/knowledge/stats      # Knowledge bank stats (chunks by domain, freshness)
  DELETE /api/admin/knowledge/{chunk_id} # Remove a knowledge chunk

Question Promotion (Admin):
  GET    /api/admin/staging              # List staging questions (with stats + status)
  GET    /api/admin/staging/{id}         # Staging question details + answer history
  POST   /api/admin/promotion/run        # Trigger promotion pipeline manually
  GET    /api/admin/promotion/history     # Promotion pipeline run history
  POST   /api/admin/staging/{id}/force-promote   # Manual override: promote a staging Q
  POST   /api/admin/staging/{id}/reject          # Manual override: reject a staging Q

Static Bank (Admin):
  GET    /api/admin/question-bank        # Browse promoted static questions
  GET    /api/admin/question-bank/stats  # Static bank coverage (topics × levels)
  PUT    /api/admin/question-bank/{id}   # Edit a promoted question (rubric, wording)

Career Coach:
  POST   /api/career/analyze             # Run gap analysis (current → target)
  GET    /api/career/profile             # Get career profile + learning path
  PUT    /api/career/profile             # Update career goals

Jobs:
  GET    /api/jobs/search                # Search public job listings
  GET    /api/jobs/{id}                  # Get job details
  POST   /api/jobs/{id}/prepare          # Create interview session from job listing

Health:
  GET    /api/health                     # Health check
  GET    /api/health/gemini              # Gemini API connectivity check
```

---

## WebSocket Message Protocol

```typescript
// Client → Server
type ClientMessage =
  | { type: 'audio_in',      data: ArrayBuffer }      // PCM 16-bit 16kHz
  | { type: 'control',       action: 'pause' | 'resume' | 'end' }
  | { type: 'heartbeat' }

// Server → Client
type ServerMessage =
  | { type: 'audio_out',     data: ArrayBuffer }      // PCM 16-bit 24kHz
  | { type: 'transcript',    role: 'user' | 'ai', text: string, ts: number }
  | { type: 'eval_signal',   questionId: string, score: number }
  | { type: 'question_meta', questionId: string, topic: string, difficulty: string }
  | { type: 'session_state', state: 'connecting' | 'active' | 'evaluating' | 'complete' }
  | { type: 'session_end',   report: SessionReport }
  | { type: 'error',         code: string, message: string }
  | { type: 'heartbeat' }
```

---

## Firestore Schema

```
Collection: users/{uid}
  Fields:
    email: string
    display_name: string
    photo_url: string
    current_role: string
    current_level: string              # "analyst" | "mid" | "senior" | "lead" | "vp"
    target_role: string
    target_level: string
    years_experience: number
    skills: string[]                   # ["python", "pytorch", "transformers", ...]
    total_sessions: number
    average_score: number
    subscription_tier: string          # "free" | "pro" | "enterprise"
    created_at: timestamp
    updated_at: timestamp

  Subcollection: users/{uid}/resumes
    Fields:
      filename: string
      gcs_url: string
      parsed_data: map                 # extracted skills, experience, education
      uploaded_at: timestamp


Collection: sessions/{sid}
  Fields:
    user_id: string                    # ref → users
    status: string                     # "created" | "lobby" | "active" | "completed" | "abandoned"
    interview_type: string             # "technical" | "behavioral" | "system_design" | "mixed"
    role: string                       # target role title
    level: string                      # "analyst" | "mid" | "senior" | "lead" | "vp"
    domain: string                     # "nlp" | "cv" | "recsys" | "mlops" | "genai" | "general"
    jd_id: string                      # ref → job_descriptions (nullable)
    duration_seconds: number
    total_questions: number
    completed_questions: number
    overall_score: number              # 1-5 composite
    hire_recommendation: string        # "strong_yes" ... "strong_no"
    audio_recording_url: string        # GCS signed URL
    created_at: timestamp
    completed_at: timestamp

  Subcollection: sessions/{sid}/questions/{qid}
    Fields:
      sequence: number
      question_text: string
      topic: string
      difficulty: string               # "easy" | "medium" | "hard" | "expert"
      question_type: string            # "technical" | "behavioral" | "system_design" | "case_study"
      source: string                   # "bank" | "jd_generated" | "follow_up"
      answer_transcript: string
      answer_duration_seconds: number
      evaluation: map {
        technical_accuracy: number,    # 1-5
        depth: number,                 # 1-5
        communication: number,         # 1-5
        composite: number,             # 1-5
        key_points_covered: string[],
        missed_points: string[],
        feedback: string,
        model_answer_outline: string,
        improvement_tip: string
      }
      follow_up_questions: string[]
      timestamp_start: timestamp
      timestamp_end: timestamp

  Subcollection: sessions/{sid}/transcript/{tid}
    Fields:
      role: string                     # "interviewer" | "candidate"
      text: string
      timestamp_ms: number             # ms from session start
      audio_offset_ms: number          # offset in recorded audio


Collection: job_descriptions/{jid}
  Fields:
    user_id: string
    raw_text: string
    source: string                     # "manual_paste" | "url_scrape" | "job_search"
    source_url: string                 # nullable
    parsed: map {
      title: string,
      company: string,
      level: string,
      domain: string,
      required_skills: [{skill, proficiency}],
      preferred_skills: [...],
      responsibilities: string[],
      interview_focus_areas: [{area, weight, question_types[]}],
      red_flags_to_probe: string[],
      culture_signals: string[]
    }
    created_at: timestamp


Collection: question_bank/{qid}
  Fields:
    text: string
    topic: string                      # "ml_fundamentals" | "deep_learning" | "nlp" | ...
    subtopic: string                   # "gradient_descent" | "attention_mechanisms" | ...
    type: string                       # "technical" | "behavioral" | "system_design" | "case_study"
    difficulty: string                 # "easy" | "medium" | "hard" | "expert"
    target_levels: string[]            # ["analyst", "mid"]
    domain: string[]                   # ["general", "nlp", "cv"]
    expected_answer_points: string[]
    follow_up_templates: string[]
    rubric: map {
      score_1: string,
      score_3: string,
      score_5: string
    }
    times_asked: number
    avg_score: number                  # running average across users
    tags: string[]
    created_at: timestamp


Collection: career_profiles/{uid}
  Fields:
    skills_assessment: map {
      skill_name: {
        self_rated: number,            # 1-5
        ai_assessed: number,           # 1-5 (from interview performance)
        last_assessed: timestamp,
        trend: string                  # "improving" | "stable" | "declining"
      }
    }
    gap_analysis: map {
      target_role: string,
      gaps: [{
        skill: string,
        current: number,
        required: number,
        priority: string,              # "critical" | "important" | "nice_to_have"
        resources: [{title, url, type}]
      }],
      generated_at: timestamp
    }
    learning_path: map {
      milestones: [{
        title: string,
        skills: string[],
        estimated_weeks: number,
        completed: boolean,
        resources: [...]
      }]
    }
    session_history_summary: map {
      total_sessions: number,
      by_type: map,
      score_trend: number[],           # last 10 session scores
      strongest_areas: string[],
      weakest_areas: string[]
    }
    updated_at: timestamp


Collection: job_listings_cache/{id}
  Fields:
    query_hash: string
    results: [{title, company, location, level, description, apply_url, source, posted_date}]
    cached_at: timestamp
    expires_at: timestamp              # TTL: 24 hours
```

---

## Career Coach Module

### Skills Gap Analysis

```
Input:
  - User's self-reported skills (from profile)
  - AI-assessed skills (from interview performance history)
  - Target role/level
  - Optional: parsed resume

Process (Gemini 2.5 Pro):
  1. Map current skills to standard AI/ML taxonomy
  2. Map target role requirements to same taxonomy
  3. Compute gap: {skill → (current, required, gap_size, priority)}
  4. Weight by: market frequency, user's timeline, difficulty to acquire

Output:
  - Skills radar chart (current vs required)
  - Prioritized gap list with "estimated weeks to close"
  - Top 3 "quick wins" (small gaps, high impact)
  - Top 3 "strategic investments" (large gaps, worth the effort)
```

### Learning Path Recommendations

```
For each gap:
  - Free: Papers, blogs, YouTube, documentation
  - Paid: Coursera, Fast.ai, Stanford Online
  - Hands-on: "Build X to demonstrate Y"
  - Practice: "Complete 3 interview sessions focused on Z"

Milestones:
  Week 1-2: Foundational reading
  Week 3-4: Hands-on project or course
  Week 5-6: Practice interviews targeting those areas
  Week 7-8: Reassess via benchmark interview session
```

### Resume Analysis

```
Input: PDF/DOCX → extract text (PyPDF2 / python-docx) → Gemini 2.5 Pro

Evaluate:
  1. Technical depth vs target role requirements
  2. Impact quantification (measurable achievements?)
  3. Project relevance to target role
  4. Gaps that recruiters would notice
  5. Specific, actionable improvement suggestions
```

---

## Job Search Integration

**Primary: SerpAPI (Google Jobs tab)**
- Structured results: title, company, location, description, apply_link
- Cost: $50/mo for 5000 searches

**Flow:**
```
User searches → GET /api/jobs/search?query=X&location=Y&level=Z
  → SerpAPI query → normalized results
  → User selects job → auto-parse JD
  → "Practice for this job" → creates session with JD-targeted questions
```

---

## Deployment

### Cloud Run Configuration

```
Service:         interviewai-api
Image:           Unified Dockerfile (Next.js static + FastAPI)
Region:          us-central1 (closest to Gemini API)
Memory:          2Gi
CPU:             2
Min instances:   1 (always warm — no cold starts during interviews)
Max instances:   10
Timeout:         3600s (1hr max for sessions)
Concurrency:     20 (each WS = long-lived connection)
Session affinity: ENABLED (required for WebSocket)
```

### Docker (Unified Build)

```dockerfile
# Stage 1: Build frontend
FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend ./
ENV NEXT_PUBLIC_API_URL=""
RUN npm run build

# Stage 2: Backend + static frontend
FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend /app/
COPY --from=frontend-builder /app/frontend/out /app/static
ENV PORT=8080
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
```

### GCS Buckets

```
gs://interviewai-recordings/       # Audio recordings (lifecycle: 90 days → Nearline)
  {uid}/{session_id}/user_audio.wav
  {uid}/{session_id}/ai_audio.wav
  {uid}/{session_id}/combined.wav

gs://interviewai-resumes/          # Uploaded resumes (lifecycle: 30 days)
  {uid}/{filename}
```

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GCP_PROJECT_ID` | yes | Google Cloud project |
| `GEMINI_API_KEY` | yes | Gemini API key (or use ADC) |
| `FIREBASE_PROJECT_ID` | yes | Firebase project for auth |
| `GCS_RECORDINGS_BUCKET` | yes | Bucket for audio recordings |
| `GCS_RESUMES_BUCKET` | yes | Bucket for resume uploads |
| `SERPAPI_KEY` | no | SerpAPI key for job search (P1) |
| `PORT` | no | Server port (default: 8080) |

---

## Cost Estimate (1K MAU)

| Component | Cost/mo | Notes |
|-----------|---------|-------|
| Gemini Live API | ~$200-400 | Avg 20 min/session, 3 sessions/user/mo |
| Gemini 2.5 Flash | ~$50 | Real-time eval function calls |
| Gemini 2.5 Pro | ~$100 | JD parsing, deep eval, career coach |
| Cloud Run | ~$80-150 | 1 min instance + autoscale |
| Firestore | ~$30-50 | Heavy reads for dashboard |
| GCS | ~$20-30 | Audio recordings |
| Firebase Auth | $0 | Free tier covers 10K MAU |
| SerpAPI | ~$50 | Job search (P1) |
| **Total** | **~$530-830/mo** | **$0.53-0.83 per user** |

**Cost optimizations:**
- Gemini 2.5 Flash (not Pro) for real-time eval — 10x cheaper, fast enough
- Aggressive prompt caching for system instructions (Gemini caching API)
- Audio compression before GCS upload (opus/mp3 vs raw WAV)
- Firestore read caching at FastAPI layer for question bank
- Session timeout enforcement (prevent idle WS connections)
- Free tier: 3 sessions/week, 15 min max. Pro: unlimited, 45 min max.

---

## MVP Week-by-Week

| Week | Deliverables |
|------|-------------|
| **1** | Project scaffolding (Next.js + FastAPI + Firestore), Firebase Auth, user schema, dashboard shell, config/env setup |
| **2** | Question bank seeding (50+ questions, 3 levels), JD parser endpoint, question generator pipeline, evaluation rubrics |
| **3** | **Gemini Live API integration** — WebSocket client, audio relay pipeline, session state machine, transcript assembly |
| **4** | Interview room UI — mic capture (AudioWorklet), audio playback (AudioContext), real-time transcript, session controls, mic check lobby |
| **5** | Evaluation — function call interception, post-session deep eval (Gemini 2.5 Pro), session review page with transcript + scores + model answers |
| **6** | Dashboard (session history, score trends), JD upload flow, audio recording/playback (wavesurfer.js), Cloud Run deploy, E2E testing |

---

## Edge Cases and Failure Modes

### Real-Time Session Failures

| Failure | Detection | Recovery |
|---------|-----------|----------|
| Gemini Live WS drops | Server heartbeat timeout | Auto-reconnect with same prompt + transcript context. 3x fail → graceful end with partial eval |
| User loses internet | Client WS onclose | Reconnect with exponential backoff (1s, 2s, 4s). Server keeps session alive 5 min |
| Mic permission denied | getUserMedia rejection | Block interview start, show clear instructions |
| Background noise | Gemini transcription quality drop | Client-side noise suppression (Web Audio API). Warning if too degraded |
| Browser tab hidden | visibilitychange event | Warn user. Audio capture continues |
| Session timeout (>45 min) | Server timer | Warn at 40 min, graceful close at 45 min with evaluation |

### Evaluation Quality

| Issue | Mitigation |
|-------|------------|
| Inconsistent scoring | Explicit rubrics in system prompt. Periodic calibration with reference answers |
| Gemini hallucinating scores | Cross-validate real-time eval with post-session deep eval. Flag discrepancies |
| Evaluation bias | Fairness prompt: "Evaluate content quality, not accent, speed, or filler words" |

### Audio Pipeline

| Issue | Mitigation |
|-------|------------|
| Echo / feedback loop | Enable echo cancellation in getUserMedia constraints |
| Latency spikes | Monitor RTT, warn user if >1s, offer to restart session |
| Recording corruption | Dual-write: buffer in memory + incremental GCS upload every 60s |

---

## Key Technical Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Frontend | Next.js 16 (static export) | Proven pattern (Project Pulse), fast builds |
| Backend | FastAPI | Native async/WS support, Python ML ecosystem |
| Deployment | Cloud Run (monolith for MVP) | Cost-effective, proven pattern |
| Database | Firestore | Real-time listeners, scalable, GCP-native |
| Storage | GCS | GCP-native, lifecycle policies |
| Auth | Firebase Auth (Google Sign-In) | Free, integrates with Firestore |
| Real-time voice | Gemini Live API (WebSocket) | Native bidirectional audio, function calling, barge-in |
| Text AI (fast) | Gemini 2.5 Flash | Speed + cost for real-time eval |
| Text AI (deep) | Gemini 2.5 Pro | Quality for JD parsing, deep eval, career coach |
| State management | Zustand | Simpler than Recoil for WS-driven state |
| Job search | SerpAPI | Structured Google Jobs results |
| Audio format | PCM 16-bit 16kHz | Gemini Live native — no transcoding needed |

---

## User Journey Flows

### Flow A: Quick Practice (P0)

```
Landing → Sign In → Select Level (Analyst/Mid/Senior)
→ Select Track (Technical/Behavioral/Mixed)
→ (Optional) Paste JD
→ Lobby (mic check, review question plan)
→ Live Interview (10-15 questions, 20-45 min)
→ Session Summary (scores, transcript, feedback, model answers)
→ Dashboard
```

### Flow B: JD-Targeted Prep (P0)

```
Dashboard → "New Session" → Paste/Upload JD
→ AI parses JD, extracts requirements, generates question plan
→ User reviews plan → Lobby (mic check)
→ Live Interview (questions calibrated to JD)
→ Detailed Feedback mapped back to JD requirements
```

### Flow C: Career Coaching (P1)

```
Dashboard → Career Coach
→ Input current role + target role → Upload resume (optional)
→ AI analyzes gap → Skills gap report → Radar chart
→ Recommended learning path → Suggested practice sessions
→ Track progress over time
```

### Flow D: Job Search + Prep (P1)

```
Dashboard → Job Search → Enter criteria (role, location, company)
→ Browse listings → Select listing → Auto-extract JD
→ "Practice for this job" → Flow B
```

---

## Session Recording and Playback

### Recording Pipeline

```
User Audio:
  Browser getUserMedia → PCM 16-bit chunks → WS to server
  Server: accumulate in memory buffer → session end → encode WAV
  → Upload: gs://interviewai-recordings/{uid}/{sid}/user_audio.wav

AI Audio:
  Gemini Live output → PCM chunks → same accumulation
  → gs://interviewai-recordings/{uid}/{sid}/ai_audio.wav

Combined (for playback):
  Post-session: merge tracks server-side (pydub/ffmpeg)
  → gs://interviewai-recordings/{uid}/{sid}/combined.wav

Transcript:
  Stored in Firestore subcollection with timestamp_ms
  Aligned to audio via audio_offset_ms
```

### Playback UI (review page)

- Audio waveform player (wavesurfer.js)
- Synchronized transcript highlighting (karaoke-style)
- Per-question evaluation scores at question boundaries
- "Jump to question N" navigation
- Model answers expandable per question
