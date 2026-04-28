# Evaluator Guidelines: GenMedia SxS

Welcome to the GenMedia SxS Arena! As an evaluator, your input directly shapes the tuning and capabilities of generative media models. This guide walks through the platform and the metrics you should evaluate.

---

## 1. Accessing the Arena

When you first load the platform, you'll see the **Access Arena** gateway alongside the **Top Evaluators** leaderboard.

![Login & Leaderboard](assets/01_login_leaderboard.png)

- **Leaderboard** tracks the number of completed evaluations per user in real-time.
- Enter your LDAP handle to begin blind evaluation.

---

## 2. Side-by-Side Evaluation

Once inside, you are presented with blind, anonymized pairs of video generations from the same prompt. Model identities are hidden until after you vote.

![Evaluation Arena](assets/02_evaluation_arena.png)

**What you see:**
- **Prompt** displayed at the top with category tags (e.g., Studio Shots, Sci Fi, Buildings).
- **Variant A / Variant B** side by side, each produced by a different model.
- **Play Both** to synchronize playback, or play individually with audio controls.
- **Skip** if the pair is not evaluable (both broken, identical, etc.).

### Voting Flow

After watching both variants, select the one that better captures the prompt. Your selection opens a detailed scoring rubric before finalizing the vote.

![Full Evaluation Flow](assets/03_evaluation_full.png)

---

## 3. Evaluation Criteria

Rate which variant performs better across these dimensions:

| Criterion | What to look for |
|-----------|-----------------|
| **Prompt Adherence** | Does the video faithfully execute all stated elements, timings, camera movements, and visual requests? |
| **Motion Quality** | Is the movement natural and fluid? Are there temporal morphing, flickering, or bleeding artifacts? |
| **Aesthetic Quality** | Assess lighting, resolution, color grading, and cinematic quality. |
| **Physics & Cohesion** | Do objects interact realistically? Are there gravity, collision, or spatial inconsistencies? |
| **Audio Expressiveness** | If audio is present, does it match the scene's mood and energy? |
| **Audio-Visual Sync** | Are sounds timed correctly with on-screen actions? |

---

## 4. Admin Console (Internal)

The admin portal manages prompts, models, and batch generation workflows.

### Admin Login

![Admin Login](assets/04_admin_login.png)

### Prompt Engine

Create and manage "Hard Prompts" with support for T2V, I2V, and R2V generation modes. Upload start/end frames, tag categories, and trigger generation across all active models.

![Prompt Engine](assets/05_admin_prompts.png)

### Generations Review

Track all generation jobs with status indicators, category tags, and success/failure counts. Filter by status, tags, or search by prompt text.

![Generations](assets/06_admin_generations.png)

### Model Registry

View and toggle all registered models. Supports Veo (Vertex AI), Kling, Seedance, and other providers via FAL.

![Model Registry](assets/07_admin_models.png)

---

## 5. Tips for Evaluators

- **Watch each video at least twice** before voting.
- **Use audio** when available -- it's a scoring dimension.
- **Don't rush** -- quality evaluations are more valuable than quantity.
- **Skip freely** if a pair is ambiguous or both outputs are equally bad/good.
- Your vote count is tracked on the leaderboard. Complete at least 10 evaluations to unlock prompt submission.
