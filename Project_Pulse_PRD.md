# Project Pulse 
**Internal Benchmarking Platform for GenMedia Models**

---

## 1. Executive Summary
With the launch of highly capable multimodal generative models (Kling 3.0, Seedance 2.0, Veo), maintaining market leadership requires going beyond automated static benchmarks. **Project Pulse** is an internal-only benchmarking platform designed for side-by-side (SxS) model evaluation, bug tracking, and prompt-engineering optimization. It will capture complex subtleties of evaluation through expert-curated "Hard Prompts" to equip Sales and Customer Engineering (CE) teams with winning narratives and battlecards.

---

## 2. Core Objectives
1. **"Living Arena" Evaluation**: Compare Veo against Kling 3.0, Seedance 2.0, and future models in real-time through blind side-by-side testing.
2. **Gamified Data Collection**: Enforce a "10-Vote Gate" to ensure high-quality, high-volume data collection from CEs and Account Managers.
3. **Autorater Training pipeline**: Collect structured SxS data to finetune a Gemini Evaluator for future model validation.
4. **Sales Enablement**: Translate technical gaps into actionable prompt recipes, gap analysis, and sales battlecards.

---

## 3. Product Features & User Flows

### 3.1. Admin Console
- **Prompt Management**: Interface to create, upload, and curate "Hard Prompts".
- **Categorization**: Tag prompts across critical visual and audio dimensions:
  - *Studio Shots*: Product lighting, high-key aesthetics, brand consistency.
  - *Beauty*: Skin texture realism, facial symmetry, non-plastic rendering.
  - *Animation*: Physics of motion, fluid dynamics, stylized consistency.
  - *Model Bug Backlog*: Real-world prompt failures sourced directly from CE reports (e.g., "hallucinating extra limbs").

### 3.2. Rating Console (The 10-Vote Gate)
- **Blind SxS Testing**: Users are presented with two videos side-by-side and must evaluate them based on 6 cross-dimensional metrics (visualized as a spider/radar chart):
  1. *Motion Quality*
  2. *Video Prompt Following*
  3. *Aesthetic*
  4. *Audio Expressiveness*
  5. *Audio-Visual Sync*
  6. *Audio Prompt Following*
  *Additional metrics*: Temporal Stability, Physics Realism.
- **Gamification**: The ability for users to submit custom prompts for evaluation is securely locked. Users must complete at least 10 detailed pairwise evaluations to unlock "Voter Access."

### 3.3. Analytics & Outputs
- **Real-time Leaderboards**: Display win-rates and spider charts showing where each model excels and struggles.
- **Prompt Recipes**: Auto-generated templates for optimizing specific workflows (e.g., overcoming Veo's struggles with Studio lighting by providing precise camera instructions).
- **Battlecards**: High-impact proof points for CE/Sales (e.g., "Our model has 20% higher consistency in multi-character scenes than Seedance 2.0").
- **Engineering Gap Reports**: Streamlined feedback loops summarizing desired competitor features (e.g., Native Audio in Kling 3.0).

---

## 4. Technical Architecture & Constraints

### 4.1. Cloud & Infrastructure
- **Cloud Provider**: Google Cloud Platform (GCP)
- **GCP Project**: `vital-octagon-19612`
- **Storage**: All generation artifacts (videos, audio, thumbnails) must be stored in the GCS bucket: `gs://project-pulse`
- **Auth/Identity**: Google Workspace Authentication to lock down as an "internal-only" tool.

### 4.2. Model Integration Layer
To ensure apples-to-apples evaluation without platform bias:
- **Veo integration**: Consumed directly via GCP Vertex AI APIs within `vital-octagon-19612`.
- **Competitor Models (Kling 3.0, Seedance 2.0)**: Consumed via FAL API.
  - *API Key*: Set via `FAL_KEY` environment variable (see `.env`)

### 4.3. Data Pipeline & Gemini Evaluator
- **Evaluation Database**: Store prompt metadata, model parameters, video object URIs, and user feedback vectors. Structured to export cleanly to Vertex GenAI Studio for finetuning.
- **Finetuning Pipeline**: Periodic cron jobs to aggregate the highest-confidence SxS human votes to fine-tune a Gemini 1.5/2.0 Pro model to serve as a high-fidelity continuous Autorater for image/video.

---

## 5. Next Steps
1. Finalize the Database schema (Prompts, Generations, Votes).
2. Scaffold the Administration dashboard to load the initial batch of "Hard Prompts".
3. Build the backend integration layer for Vertex AI (Veo) and FAL (Kling/Seedance).
4. Implement the side-by-side React video player and rating form for the 10-Vote Gate.
