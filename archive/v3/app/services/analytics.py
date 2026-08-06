"""Analytics — pure stats over executions, comparisons and votes.

Ports the v2 win-map + human/AI-agreement math faithfully (``_wilson``,
``_is_google_engine``) and adds the v3 upgrade: GLOBAL model rankings via Elo
and Bradley-Terry, ranked across every execution/comparison rather than only
per head-to-head pair. All ranking math is deterministic (fixed K / iteration
count, no randomness, no wall-clock) so results are reproducible.
"""
from __future__ import annotations

import math
from collections import defaultdict

_GOOGLE_MARKERS = ("gemini", "imagen", "veo", "omni", "nano", "banana", "doubao-google")


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float, float]:
    """Wilson score interval for a binomial proportion.

    Returns ``(p, low, high)``. Matches v2 ``_wilson`` numerically (v2 returned
    the same values ordered ``(low, p, high)``)."""
    if n <= 0:
        return (0.0, 0.0, 0.0)
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return (p, max(0.0, center - half), min(1.0, center + half))


def is_google_engine(name: str) -> bool:
    """True for Google-family engines (gemini/imagen/veo/omni/nano/banana/
    doubao-google). Ports v2 ``_is_google_engine``."""
    e = str(name or "").lower()
    return any(marker in e for marker in _GOOGLE_MARKERS)


def _engine_family(name: str) -> str:
    return "google" if is_google_engine(name) else "competitor"


class AnalyticsService:
    """Read-only aggregations over the execution-centric data model."""

    def __init__(self, exec_repo, vote_repo, comparison_repo) -> None:
        self.exec_repo = exec_repo
        self.vote_repo = vote_repo
        self.comparison_repo = comparison_repo

    # -- execution resolution ---------------------------------------------
    def _exec(self, exec_id: str | None) -> dict | None:
        if not exec_id:
            return None
        return self.exec_repo.get(exec_id)

    def _model_of(self, exec_id: str | None) -> str | None:
        doc = self._exec(exec_id)
        return doc.get("model_id") if doc else None

    # -- win map (Google vs competitor, AI judge) --------------------------
    def win_map(self, min_n: int = 10) -> dict:
        """Where do Google models win? Aggregates AI-judge verdicts on
        Google-vs-competitor comparisons and reports Google's win-rate with
        95% Wilson CIs + n, sliced by category, language and modality."""
        segs: dict[str, list[int]] = {}

        def bump(dim: str, seg: str, won: bool) -> None:
            arr = segs.setdefault(f"{dim}\x1f{seg}", [0, 0])
            arr[1] += 1
            if won:
                arr[0] += 1

        for comp in self.comparison_repo.stream():
            verdict = comp.get("ai_verdict") or {}
            winner_exec = verdict.get("winner_execution")
            if not winner_exec:
                continue
            ea = self._exec(comp.get("execution_a"))
            eb = self._exec(comp.get("execution_b"))
            if not ea or not eb:
                continue
            engines = [ea.get("model_id"), eb.get("model_id")]
            fams = [_engine_family(e) for e in engines if e]
            if fams.count("google") != 1 or fams.count("competitor") != 1:
                continue
            won = is_google_engine(self._model_of(winner_exec) or "")
            categories = ea.get("categories") or []
            language = ea.get("language")
            modality = comp.get("modality") or ea.get("modality") or "?"

            bump("overall", "all", won)
            bump("modality", str(modality), won)
            if language:
                bump("language", str(language), won)
            for c in categories:
                cs = str(c)
                if cs and not cs.lower().startswith("len:"):
                    bump("category", cs, won)

        def rows_for(dim: str, apply_min: bool = True) -> list[dict]:
            out = []
            pfx = f"{dim}\x1f"
            for key, (wins, n) in segs.items():
                if not key.startswith(pfx):
                    continue
                if apply_min and n < min_n:
                    continue
                p, lo, hi = wilson(wins, n)
                verdict = "lead" if lo > 0.5 else ("trail" if hi < 0.5 else "tie")
                out.append({
                    "segment": key[len(pfx):], "n": n,
                    "win_rate": round(p * 100, 1),
                    "ci_low": round(lo * 100, 1), "ci_high": round(hi * 100, 1),
                    "verdict": verdict,
                })
            return sorted(out, key=lambda x: (-x["n"], -x["win_rate"]))

        by_cat = rows_for("category")
        by_lang = rows_for("language")
        by_mod = rows_for("modality")
        overall = rows_for("overall", apply_min=False)
        all_segments = by_cat + by_lang + by_mod
        leads = sorted([s for s in all_segments if s["verdict"] == "lead"],
                       key=lambda x: -x["win_rate"])
        trails = sorted([s for s in all_segments if s["verdict"] == "trail"],
                        key=lambda x: x["win_rate"])
        return {
            "overall": overall[0] if overall else
                       {"win_rate": 0, "ci_low": 0, "ci_high": 0, "n": 0},
            "by_category": by_cat, "by_language": by_lang, "by_modality": by_mod,
            "leads": leads, "trails": trails,
            "note": "Google win-rate from the AI judge on Google-vs-competitor "
                    "pairs; CI = 95% Wilson.",
        }

    # -- human vs AI agreement --------------------------------------------
    def agreement(self) -> dict:
        """Of pairs that have BOTH a human vote and an AI verdict, the % where
        they pick the same execution — sliced per modality plus overall."""
        # AI winner per unordered execution pair.
        ai_winner: dict[frozenset[str], str] = {}
        pair_modality: dict[frozenset[str], str] = {}
        for comp in self.comparison_repo.stream():
            ea, eb = comp.get("execution_a"), comp.get("execution_b")
            if not ea or not eb:
                continue
            w = (comp.get("ai_verdict") or {}).get("winner_execution")
            if not w:
                continue
            pair = frozenset({ea, eb})
            ai_winner[pair] = w
            mod = comp.get("modality") or (self._exec(ea) or {}).get("modality") or "?"
            pair_modality[pair] = str(mod)

        per: dict[str, list[int]] = defaultdict(lambda: [0, 0])  # modality -> [agree, n]
        for vote in self.vote_repo.stream():
            ea, eb = vote.get("execution_a"), vote.get("execution_b")
            hw = vote.get("winner_execution")
            if not ea or not eb or not hw:
                continue
            pair = frozenset({ea, eb})
            if pair not in ai_winner:
                continue
            mod = pair_modality.get(pair, "?")
            stats = per[mod]
            stats[1] += 1
            if str(hw) == str(ai_winner[pair]):
                stats[0] += 1

        out: dict = {}
        total_agree = total_n = 0
        for mod, (agree, n) in per.items():
            out[mod] = {"agree": agree, "n": n,
                        "pct": round(agree / n * 100, 1) if n else None}
            total_agree += agree
            total_n += n
        out["overall"] = {"agree": total_agree, "n": total_n,
                          "pct": round(total_agree / total_n * 100, 1) if total_n else None}
        return out

    # -- shared execution index (avoids N+1 repo.get per stat) ------------
    def _exec_index(self) -> dict[str, dict]:
        return {e["id"]: e for e in self.exec_repo.stream() if e.get("id")}

    @staticmethod
    def _latency_of(execution: dict) -> float | None:
        lat = execution.get("latency_s")
        if lat is None:
            lat = (execution.get("metadata") or {}).get("latency_s")
        try:
            return float(lat) if lat is not None else None
        except (TypeError, ValueError):
            return None

    # -- latency analytics (ports v2 /api/analytics/latency) --------------
    _MOD_ORDER = ["t2v", "i2v", "r2v", "t2i", "i2i", "tts"]

    def latency(self) -> dict:
        """Average successful-generation latency per (modality, model), seconds.
        Ports v2 ``/api/analytics/latency`` onto the execution store (v3 already
        records ``latency_s`` in seconds, so no ms/s drift)."""
        agg: dict[tuple[str, str], list[float]] = defaultdict(lambda: [0.0, 0])
        for e in self.exec_repo.stream():
            if e.get("status") != "success":
                continue
            lat = self._latency_of(e)
            if lat is None:
                continue
            key = (str(e.get("modality") or "?"), e.get("model_id") or "?")
            agg[key][0] += lat
            agg[key][1] += 1
        rows = [
            {"modality": mod, "model": model,
             "avg_latency_s": round(s / n, 2), "samples": n}
            for (mod, model), (s, n) in agg.items() if n
        ]

        def order(mod: str) -> int:
            return self._MOD_ORDER.index(mod) if mod in self._MOD_ORDER else 99

        rows.sort(key=lambda r: (order(r["modality"]), -r["samples"]))
        return {"rows": rows, "modalities": list(self._MOD_ORDER)}

    # -- win-rate stats: skus leaderboard + radar metrics + tag matrix ----
    def stats(self, modality: str | None = None, tag: str | None = None,
              ldap: str | None = None) -> dict:
        """Win-rate leaderboard (from human votes; ties credit both, per v2
        ``/api/sxs/stats``), per-model per-metric averages (from the AI judge's
        per-execution scores → radar), and a win-rate-by-tag matrix. Optional
        ``modality`` / ``tag`` / ``ldap`` filters."""
        execs = self._exec_index()

        def model_of(eid: str | None) -> str | None:
            e = execs.get(eid) if eid else None
            return e.get("model_id") if e else None

        def mod_of(eid: str | None) -> str:
            e = execs.get(eid) if eid else None
            return str(e.get("modality")) if e else "?"

        def cats_of(*eids: str | None) -> list[str]:
            for eid in eids:
                e = execs.get(eid) if eid else None
                if e and e.get("categories"):
                    return [str(c) for c in e["categories"]]
            return []

        sku: dict[str, dict[str, int]] = defaultdict(lambda: {"wins": 0, "total": 0})
        tag_matrix: dict[str, dict[str, dict[str, int]]] = defaultdict(
            lambda: defaultdict(lambda: {"wins": 0, "total": 0}))
        mode_counts: dict[str, int] = defaultdict(int)
        total_evals = 0

        for v in self.vote_repo.stream():
            if ldap and (v.get("ldap") or "") != ldap:
                continue
            a, b = model_of(v.get("execution_a")), model_of(v.get("execution_b"))
            if not a or not b:
                continue
            mod = mod_of(v.get("execution_a"))
            if modality and mod != str(modality):
                continue
            cats = [c for c in cats_of(v.get("execution_a"), v.get("execution_b"))
                    if not c.lower().startswith("len:")]
            if tag and tag not in cats:
                continue
            w = model_of(v.get("winner_execution")) if v.get("winner_execution") else None
            total_evals += 1
            mode_counts[mod] += 1
            sku[a]["total"] += 1
            sku[b]["total"] += 1
            if w is None:                      # tie credits both (v2 sxs)
                sku[a]["wins"] += 1
                sku[b]["wins"] += 1
            else:
                sku[w]["wins"] += 1
            for c in cats:
                tag_matrix[c][a]["total"] += 1
                tag_matrix[c][b]["total"] += 1
                if w is None:
                    tag_matrix[c][a]["wins"] += 1
                    tag_matrix[c][b]["wins"] += 1
                else:
                    tag_matrix[c][w]["wins"] += 1

        # Per-metric averages for the radar, from the AI judge's per-execution
        # scores (matches v2's AI-sourced dimension analytics).
        m_sum: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        m_cnt: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for comp in self.comparison_repo.stream():
            per = (comp.get("ai_verdict") or {}).get("per_execution") or {}
            for eid, scores in per.items():
                m = model_of(eid)
                if not m or (modality and mod_of(eid) != str(modality)):
                    continue
                for metric, val in (scores or {}).items():
                    if isinstance(val, (int, float)) and not isinstance(val, bool):
                        m_sum[m][metric] += val
                        m_cnt[m][metric] += 1

        # latency per model (seconds)
        lat_sum: dict[str, float] = defaultdict(float)
        lat_n: dict[str, int] = defaultdict(int)
        for e in execs.values():
            if e.get("status") != "success":
                continue
            lat = self._latency_of(e)
            if lat is None:
                continue
            m = e.get("model_id") or "?"
            lat_sum[m] += lat
            lat_n[m] += 1

        skus = []
        for m, d in sku.items():
            total = d["total"]
            scores = {k: round(m_sum[m][k] / m_cnt[m][k], 2)
                      for k in m_cnt.get(m, {}) if m_cnt[m][k]}
            skus.append({
                "model_id": m,
                "win_rate": round(d["wins"] / total * 100, 1) if total else 0.0,
                "wins": d["wins"], "total": total,
                "latency_s": round(lat_sum[m] / lat_n[m], 2) if lat_n[m] else None,
                "scores": scores,
            })
        skus.sort(key=lambda s: (-s["win_rate"], -s["total"]))

        by_tag = []
        for tagname, models in tag_matrix.items():
            models_list = [
                {"model_id": m, "wins": d["wins"], "total": d["total"],
                 "win_rate": round(d["wins"] / d["total"] * 100, 1) if d["total"] else 0.0}
                for m, d in sorted(models.items(), key=lambda kv: -kv[1]["wins"])
            ]
            votes_n = sum(d["total"] for d in models.values()) // 2
            by_tag.append({"tag": tagname, "votes": votes_n, "models": models_list})
        by_tag.sort(key=lambda t: -t["votes"])

        return {
            "total_evals": total_evals,
            "modality": modality, "tag": tag,
            "modes": dict(mode_counts),
            "skus": skus,
            "by_tag": by_tag,
        }

    # -- voter leaderboard + anti-gaming (ports v2 /api/leaderboard) -------
    _MIN_DECISIVE = 5
    _ONE_SIDED = 0.9
    _MOD_GROUP = {"t2v": "video", "i2v": "video", "r2v": "video",
                  "t2i": "image", "i2i": "image", "tts": "tts"}

    def voter_leaderboard(self) -> dict:
        """Top voters overall + per modality group (video/image/tts), excluding
        suspected blind voters: ≥5 decisive votes that are ≥90% one-sided."""
        execs = self._exec_index()

        def group_of(eid: str | None) -> str:
            e = execs.get(eid) if eid else None
            return self._MOD_GROUP.get(str(e.get("modality")) if e else "", "other")

        users: dict[str, dict] = defaultdict(
            lambda: {"total": 0, "video": 0, "image": 0, "tts": 0, "other": 0,
                     "A": 0, "B": 0})
        for v in self.vote_repo.stream():
            ldap = (v.get("ldap") or "").strip()
            if ldap in ("", "anonymous", "global"):
                continue
            u = users[ldap]
            u["total"] += 1
            u[group_of(v.get("execution_a"))] += 1
            w = v.get("winner_execution")
            if w and w == v.get("execution_a"):
                u["A"] += 1
            elif w and w == v.get("execution_b"):
                u["B"] += 1

        excluded, kept = [], {}
        for ldap, u in users.items():
            decisive = u["A"] + u["B"]
            if decisive >= self._MIN_DECISIVE:
                dom = max(u["A"], u["B"]) / decisive
                if dom >= self._ONE_SIDED:
                    excluded.append({
                        "ldap": ldap, "total": u["total"],
                        "dominant_side": "A" if u["A"] >= u["B"] else "B",
                        "dominant_pct": round(dom * 100, 1),
                    })
                    continue
            kept[ldap] = u

        def row(ldap: str, u: dict) -> dict:
            return {"ldap": ldap, "total": u["total"], "video": u["video"],
                    "image": u["image"], "tts": u["tts"]}

        overall = sorted((row(k, u) for k, u in kept.items()),
                         key=lambda r: -r["total"])[:50]
        by_modality = {
            g: sorted((row(k, u) for k, u in kept.items() if u[g] > 0),
                      key=lambda r, gg=g: -r[gg])[:50]
            for g in ("video", "image", "tts")
        }
        return {
            "overall": overall, "by_modality": by_modality,
            "excluded": sorted(excluded, key=lambda e: -e["total"]),
            "rules": {"min_decisive": self._MIN_DECISIVE,
                      "one_sided_pct": int(self._ONE_SIDED * 100)},
        }

    def vote_count(self, ldap: str) -> dict:
        """Votes cast by a user; gates analytics at ≥10 (ports v2 /votes/count)."""
        required = 10
        key = (ldap or "").strip()
        if key in ("", "anonymous", "global"):
            return {"ldap": ldap, "count": 0, "required": required, "unlocked": False}
        count = sum(1 for v in self.vote_repo.stream() if (v.get("ldap") or "") == key)
        return {"ldap": ldap, "count": count, "required": required,
                "unlocked": count >= required}

    # -- global rankings (v3 upgrade) -------------------------------------
    def _pairwise_results(self, votes) -> list[tuple[str, str, str | None]]:
        """Normalize votes to (model_a, model_b, winner_model) triples,
        resolving executions to their models. None winner = tie/skip."""
        triples: list[tuple[str, str, str | None]] = []
        for v in votes:
            a = self._model_of(v.get("execution_a"))
            b = self._model_of(v.get("execution_b"))
            if not a or not b or a == b:
                continue
            w = self._model_of(v.get("winner_execution")) if v.get("winner_execution") else None
            if w not in (a, b, None):
                w = None
            triples.append((a, b, w))
        return triples

    def elo_rankings(self, votes, k: float = 32.0, base: float = 1000.0) -> dict:
        """Deterministic Elo over all votes. Global per-model ratings; a tie
        counts as 0.5 for each side. Votes processed in the given order."""
        ratings: dict[str, float] = {}

        def rating(m: str) -> float:
            return ratings.setdefault(m, base)

        for a, b, w in self._pairwise_results(votes):
            ra, rb = rating(a), rating(b)
            ea = 1.0 / (1.0 + 10 ** ((rb - ra) / 400.0))
            eb = 1.0 - ea
            if w == a:
                sa, sb = 1.0, 0.0
            elif w == b:
                sa, sb = 0.0, 1.0
            else:  # tie
                sa = sb = 0.5
            ratings[a] = ra + k * (sa - ea)
            ratings[b] = rb + k * (sb - eb)

        return dict(sorted(ratings.items(), key=lambda kv: -kv[1]))

    def bradley_terry(self, votes, iters: int = 100) -> dict:
        """Deterministic Bradley-Terry strengths via the MM algorithm. Global
        per-model strengths normalized to sum to 1. Ties are ignored (BT has no
        tie term). Fixed iteration count → reproducible."""
        wins: dict[str, float] = defaultdict(float)
        games: dict[frozenset[str], int] = defaultdict(int)
        models: set[str] = set()

        for a, b, w in self._pairwise_results(votes):
            models.add(a)
            models.add(b)
            games[frozenset({a, b})] += 1
            if w == a:
                wins[a] += 1
            elif w == b:
                wins[b] += 1
            # ties contribute a game but no win

        if not models:
            return {}

        p: dict[str, float] = {m: 1.0 for m in models}
        for _ in range(iters):
            new_p: dict[str, float] = {}
            for i in models:
                denom = 0.0
                for j in models:
                    if i == j:
                        continue
                    n_ij = games.get(frozenset({i, j}), 0)
                    if n_ij:
                        denom += n_ij / (p[i] + p[j])
                if denom > 0 and wins[i] > 0:
                    new_p[i] = wins[i] / denom
                else:
                    new_p[i] = 1e-9  # winless models get a floor, not zero
            total = sum(new_p.values()) or 1.0
            p = {m: v / total for m, v in new_p.items()}

        return dict(sorted(p.items(), key=lambda kv: -kv[1]))

    # -- convenience: rankings straight from the vote repo -----------------
    def rankings(self, method: str = "bradley_terry",
                 suite_id: str | None = None, modality: str | None = None) -> dict:
        """Global model ranking read directly from the vote repo. ``method`` is
        ``bradley_terry`` (default) or ``elo``. Optional suite/modality filters
        restrict which votes count (by the executions they reference)."""
        votes = list(self.vote_repo.stream())
        if suite_id or modality:
            def _keep(v: dict) -> bool:
                ref = self._exec(v.get("execution_a")) or {}
                if suite_id and ref.get("suite_id") != suite_id:
                    return False
                if modality and str(ref.get("modality")) != str(modality):
                    return False
                return True
            votes = [v for v in votes if _keep(v)]
        scores = self.elo_rankings(votes) if method == "elo" else self.bradley_terry(votes)
        return {
            "method": method,
            "ranking": [{"model_id": m, "score": round(s, 4), "rank": i + 1}
                        for i, (m, s) in enumerate(scores.items())],
            "n_votes": len(votes),
        }
