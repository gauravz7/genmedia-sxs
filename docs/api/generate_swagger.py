#!/usr/bin/env python3
"""
Enrich the FastAPI-exported OpenAPI spec for Project Pulse and emit:
  - openapi.json / openapi.yaml   (Swagger / OpenAPI 3.1)
  - swagger.html                  (standalone Swagger UI, spec inlined)
  - API_REFERENCE.md              (grouped endpoint listing)

Run backend first, then:
  curl -s localhost:8011/openapi.json -o openapi.json
  python3 generate_swagger.py
"""
import json, os, yaml, collections

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "openapi.json")

PROD = "https://genmedia-sxs-v2-440790012685.us-central1.run.app"

# path-prefix -> (tag, description)  — first match wins (longest prefix first)
TAG_RULES = [
    ("/api/sxs",         "Video SxS"),
    ("/api/evaluation",  "Video SxS"),
    ("/api/image",       "Image SxS"),
    ("/api/tts",         "TTS SxS"),
    ("/api/admin",       "Admin"),
    ("/api/models",      "Models"),
    ("/api/analytics",   "Analytics"),
    ("/api/leaderboard", "Leaderboard & Votes"),
    ("/api/votes",       "Leaderboard & Votes"),
    ("/api/slideware",   "Slideware"),
    ("/api/slides",      "Slideware"),
    ("/slideware",       "Slideware"),
    ("/api/generate",    "Generation & Media"),
    ("/api/upload",      "Generation & Media"),
    ("/api/media",       "Generation & Media"),
    ("/api/tags",        "Generation & Media"),
    ("/api/benchmark",   "Generation & Media"),
    ("/api/health",      "System"),
    ("/aieval",          "AI Evals"),
]

TAG_DESCRIPTIONS = {
    "Video SxS": "Blind side-by-side video evaluation — pairs, votes, stats, catalog, generation.",
    "Image SxS": "Image (T2I / I2I) side-by-side — pairs, votes, matchups, results, generation.",
    "TTS SxS": "Text-to-speech side-by-side (Gemini TTS vs ElevenLabs) — voices, pairs, votes, results.",
    "AI Evals": "Machine (AI-judge) auto-evaluations across modalities.",
    "Analytics": "Aggregated win rates, dimension analytics and latency.",
    "Leaderboard & Votes": "Evaluator leaderboards and vote counters.",
    "Models": "Model registry — list, add, toggle active models.",
    "Admin": "Admin-only: prompts, batch import, generation, tagging, vote hygiene. Requires the X-Admin-Token header.",
    "Slideware": "Slide/feedback generation utilities.",
    "Generation & Media": "Generation triggers and media proxy/serving helpers.",
    "System": "Health and service metadata.",
    "Other": "Uncategorised endpoints.",
}

TAG_ORDER = ["System", "Video SxS", "Image SxS", "TTS SxS", "AI Evals",
             "Analytics", "Leaderboard & Votes", "Models", "Generation & Media",
             "Admin", "Slideware", "Other"]


def tag_for(path):
    for prefix, tag in sorted(TAG_RULES, key=lambda x: -len(x[0])):
        if path == prefix or path.startswith(prefix + "/") or path.startswith(prefix):
            return tag
    return "Other"


def main():
    spec = json.load(open(SRC))

    spec["openapi"] = spec.get("openapi", "3.1.0")
    spec["info"] = {
        "title": "Project Pulse — GenMedia SxS API",
        "version": "2.0.0",
        "description": (
            "REST API for **Project Pulse (GenMedia SxS)** — an internal platform for "
            "blind side-by-side evaluation of generative-media models across **Video, "
            "Image and Speech**.\n\n"
            "Each modality exposes the same shape: generate A/B cases, serve a blind pair, "
            "record a vote, and read stats / leaderboards. An AI judge scores every pair in "
            "parallel with human votes.\n\n"
            "**Auth:** most read/vote endpoints are open within the IAM-gated app. "
            "Admin actions (generation, prompts, hygiene) require the `X-Admin-Token` header "
            "(sha256 of `project-pulse-sxs:v1:admin:<ADMIN_PASS>`)."
        ),
        "contact": {"name": "Project Pulse", "url": PROD},
        "license": {"name": "Internal — Google"},
    }
    spec["servers"] = [
        {"url": PROD, "description": "Production (Cloud Run, Google-IAM gated)"},
        {"url": "http://localhost:8011", "description": "Local development"},
    ]

    # security scheme for admin token
    comps = spec.setdefault("components", {})
    comps.setdefault("securitySchemes", {})["AdminToken"] = {
        "type": "apiKey", "in": "header", "name": "X-Admin-Token",
        "description": "sha256 of 'project-pulse-sxs:v1:admin:<ADMIN_PASS>'",
    }

    # tag + security assignment
    counts = collections.Counter()
    for path, ops in spec["paths"].items():
        tag = tag_for(path)
        for method, op in ops.items():
            if method not in ("get", "post", "put", "patch", "delete"):
                continue
            op["tags"] = [tag]
            counts[tag] += 1
            if tag == "Admin":
                op.setdefault("security", [{"AdminToken": []}])

    # global tag list (ordered, only those present)
    present = [t for t in TAG_ORDER if counts.get(t)]
    present += [t for t in counts if t not in present]
    spec["tags"] = [{"name": t, "description": TAG_DESCRIPTIONS.get(t, "")} for t in present]

    # write json + yaml
    json.dump(spec, open(os.path.join(HERE, "openapi.json"), "w"), indent=2)
    yaml.safe_dump(spec, open(os.path.join(HERE, "openapi.yaml"), "w"),
                   sort_keys=False, allow_unicode=True, width=100)

    # standalone Swagger UI (spec inlined so it works from file://)
    spec_min = json.dumps(spec, separators=(",", ":"))
    html = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Project Pulse API — Swagger UI</title>
  <link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css"/>
  <style>body{margin:0}.topbar{display:none}</style>
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
  <script>
    const spec = %s;
    window.ui = SwaggerUIBundle({
      spec: spec,
      dom_id: '#swagger-ui',
      deepLinking: true,
      docExpansion: 'none',
      defaultModelsExpandDepth: -1,
      tagsSorter: 'alpha',
      filter: true,
    });
  </script>
</body>
</html>
""" % spec_min
    open(os.path.join(HERE, "swagger.html"), "w").write(html)

    # markdown reference grouped by tag
    by_tag = collections.defaultdict(list)
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            if method not in ("get", "post", "put", "patch", "delete"):
                continue
            by_tag[op["tags"][0]].append((method.upper(), path, op.get("summary", "")))
    md = ["# Project Pulse — API Reference",
          "",
          f"OpenAPI **{spec['openapi']}** · {sum(counts.values())} operations · "
          f"{len(spec['paths'])} paths.",
          "",
          f"- Production: `{PROD}` (Google-IAM gated)",
          "- Local: `http://localhost:8011` · interactive docs at `/docs`, spec at `/openapi.json`",
          "- Admin endpoints require header `X-Admin-Token: sha256('project-pulse-sxs:v1:admin:<ADMIN_PASS>')`",
          ""]
    for t in present:
        rows = sorted(by_tag.get(t, []), key=lambda r: (r[1], r[0]))
        if not rows:
            continue
        md.append(f"## {t}")
        desc = TAG_DESCRIPTIONS.get(t)
        if desc:
            md.append(f"_{desc}_")
        md.append("")
        md.append("| Method | Path | Summary |")
        md.append("|--------|------|---------|")
        for meth, path, summ in rows:
            md.append(f"| `{meth}` | `{path}` | {summ} |")
        md.append("")
    open(os.path.join(HERE, "API_REFERENCE.md"), "w").write("\n".join(md))

    print("operations:", sum(counts.values()))
    for t in present:
        print(f"  {counts[t]:3}  {t}")
    print("wrote: openapi.json, openapi.yaml, swagger.html, API_REFERENCE.md")


if __name__ == "__main__":
    main()
