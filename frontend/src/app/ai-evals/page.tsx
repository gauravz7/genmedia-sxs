"use client";
import { useState, useEffect, useMemo } from "react";
import { API_BASE_URL, formatUrl, maskPid } from "@/lib/api";
import Nav from "@/components/Nav";

// ===================================================================
// Loose types — auto-eval shape is dynamic
// ===================================================================
interface AxisScore {
  score?: number;
  explanation?: string;
}

interface AutoEval {
  prompt_adherence?: AxisScore;
  visual_quality?: AxisScore;
  motion_physics?: AxisScore;
  temporal_consistency?: AxisScore;
  audio_visual_sync?: AxisScore;
  overall_score?: number;
  critical_flaws?: string[];
  [key: string]: any;
}

interface ResultEntry {
  status?: string;
  url?: string;
  model?: string;
  [key: string]: any;
}

interface RatingJob {
  id: string;
  customer?: string;
  prompt_id?: string;
  prompt?: string;
  modality?: string;
  ratio?: string;
  results?: Record<string, ResultEntry>;
  auto_evals?: Record<string, AutoEval>;
  auto_eval_status?: string;
  director_eval?: {
    verdict?: string; // 'A' (Seedance) or 'B' (Omni)
    reasoning?: string;
    winner_model?: string;
    video_a?: string;
    video_b?: string;
    critique_results?: { Category: string; Score: string; Reasoning: string }[];
  };
  reference_images?: string[];
  reference_videos?: string[];
  [key: string]: any;
}

const AXES: { key: keyof AutoEval; label: string }[] = [
  { key: "prompt_adherence", label: "Prompt Adherence" },
  { key: "visual_quality", label: "Visual Quality" },
  { key: "motion_physics", label: "Motion & Physics" },
  { key: "temporal_consistency", label: "Temporal Consistency" },
  { key: "audio_visual_sync", label: "Audio-Visual Sync" },
];

const prettyModel = (key: string) => {
  const k = key.toLowerCase();
  if (k.includes('omni')) return 'Gemini Omni';
  if (k.includes('seedance') && k.includes('fast')) return 'Seedance 2.0 Fast';
  if (k.includes('seedance')) return 'Seedance 2.0';
  if (k.includes('veo')) return 'Veo';
  if (k.includes('kling')) return 'Kling';
  return key;
};

// Stable ordering: seedance variants first (non-fast before fast), then omni, then others.
const modelOrder = (key: string): number => {
  const k = key.toLowerCase();
  if (k.includes('seedance') && k.includes('fast')) return 1;
  if (k.includes('seedance') || k.includes('doubao')) return 0;
  if (k.includes('omni')) return 2;
  return 3;
};

const axisScore = (ev?: AutoEval, key?: keyof AutoEval): number | null => {
  if (!ev || !key) return null;
  const a = ev[key] as AxisScore | undefined;
  return typeof a?.score === "number" ? a.score : null;
};

// Image/TTS media is served via /api/{image,tts}/media — prefix with the API base.
const mediaUrl = (u?: string): string | undefined =>
  u && u.startsWith("/api/") ? `${API_BASE_URL}${u}` : formatUrl(u);

const prettyMetric = (k: string) =>
  k.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

// ===================================================================
// Cross-modality eval extraction — normalize video (auto_evals keyed by
// model) and image/TTS (ai_eval with A/B sides) into one shape so a single
// summary can aggregate across all of them.
// ===================================================================
interface EngineEval {
  label: string;
  overall: number | null;
  metrics: Record<string, number>;
}

function extractJobEvals(job: any): { engines: EngineEval[]; winner: string | null } {
  const mod = job._modality || "video";

  if (mod === "video") {
    const keys = new Set<string>();
    Object.keys(job.auto_evals || {}).forEach((k) => keys.add(k));
    Object.entries(job.results || {}).forEach(([k, r]: any) => {
      const ok =
        r?.url ||
        (r?.status || "").toLowerCase().includes("success") ||
        (r?.status || "").toLowerCase().includes("complete");
      if (ok) keys.add(k);
    });
    const engines: EngineEval[] = [];
    let bestO: number | null = null;
    let winner: string | null = null;
    let tie = false;
    Array.from(keys).forEach((k) => {
      const ev = job.auto_evals?.[k];
      const overall = typeof ev?.overall_score === "number" ? ev.overall_score : null;
      const metrics: Record<string, number> = {};
      AXES.forEach((a) => {
        const s = axisScore(ev, a.key);
        if (s != null) metrics[a.label] = s;
      });
      const label = prettyModel(k);
      engines.push({ label, overall, metrics });
      if (overall != null) {
        if (bestO == null || overall > bestO) { bestO = overall; winner = label; tie = false; }
        else if (overall === bestO) tie = true;
      }
    });
    return { engines, winner: tie ? null : winner };
  }

  // image / tts — ai_eval has A/B sides
  const ai = job.ai_eval || {};
  const sides = ["A", "B"];
  const metricKeys: string[] =
    Array.isArray(ai.metrics) && ai.metrics.length
      ? ai.metrics
      : Array.from(
          new Set(
            sides.flatMap((s) =>
              Object.keys(ai[s] || {}).filter((k) => typeof ai[s][k] === "number" && k !== "overall_score")
            )
          )
        );
  const engines: EngineEval[] = [];
  sides.forEach((s) => {
    const ev = ai[s] || {};
    const result = job.results?.[s] || {};
    const label = prettyModel(job.side_map?.[s] || result.model || result.engine || s);
    const overall = typeof ev.overall_score === "number" ? ev.overall_score : null;
    const metrics: Record<string, number> = {};
    metricKeys.forEach((k) => { if (typeof ev[k] === "number") metrics[prettyMetric(k)] = ev[k]; });
    if (overall != null || Object.keys(metrics).length || result.url) engines.push({ label, overall, metrics });
  });
  const winnerSide = (ai.winner_side || "").toUpperCase();
  let winner: string | null = null;
  if (ai.winner_engine) winner = prettyModel(ai.winner_engine);
  else if (winnerSide === "A" || winnerSide === "B") {
    const result = job.results?.[winnerSide] || {};
    winner = prettyModel(job.side_map?.[winnerSide] || result.model || result.engine || winnerSide);
  }
  return { engines, winner };
}

// Tags for filtering: categories/tags + language only (no customer names —
// those are sensitive and must not surface as tags). Modality has its own tabs.
function jobTags(job: any): string[] {
  const t = new Set<string>();
  const add = (v: any) => { if (v != null && String(v).trim()) t.add(String(v).trim()); };
  const cats = job.categories || job.tags || [];
  (Array.isArray(cats) ? cats : [cats]).forEach(add);
  add(job.language);
  return Array.from(t);
}

export default function AiEvals() {
  const [jobs, setJobs] = useState<RatingJob[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string>("");
  const [filter, setFilter] = useState("");
  const [modality, setModality] = useState<"all" | "video" | "image" | "audio">("all");
  const [selectedTags, setSelectedTags] = useState<string[]>([]);

  useEffect(() => {
    const load = async () => {
      setIsLoading(true);
      setError("");
      try {
        const endpoints: { url: string; modality: string }[] = [
          { url: `${API_BASE_URL}/api/sxs/jobs`, modality: "video" },
          { url: `${API_BASE_URL}/api/image/jobs`, modality: "image" },
          { url: `${API_BASE_URL}/api/tts/jobs`, modality: "audio" },
        ];
        const settled = await Promise.all(
          endpoints.map(async (e) => {
            try {
              const res = await fetch(e.url);
              if (!res.ok) return [];
              const data = await res.json();
              const list: any[] = Array.isArray(data) ? data : (data.jobs ?? []);
              return list.map((j: any) => {
                const results = j.results || {};
                const fixed: Record<string, any> = {};
                Object.keys(results).forEach((k) => {
                  fixed[k] = { ...results[k], url: mediaUrl(results[k]?.url) };
                });
                return {
                  ...j,
                  _modality: e.modality,
                  results: fixed,
                  reference_images: (j.reference_images || []).map(mediaUrl).filter(Boolean),
                  reference_videos: (j.reference_videos || []).map(mediaUrl).filter(Boolean),
                };
              });
            } catch {
              return [];
            }
          })
        );
        const merged = settled.flat();
        merged.sort((a: any, b: any) => (b.timestamp || 0) - (a.timestamp || 0));
        setJobs(merged as RatingJob[]);
      } catch (err: any) {
        setError(err?.message || "Failed to load ratings");
      } finally {
        setIsLoading(false);
      }
    };
    load();
  }, []);

  const counts = useMemo(() => {
    const c: Record<string, number> = { all: jobs.length, video: 0, image: 0, audio: 0 };
    jobs.forEach((j: any) => { c[j._modality || "video"] = (c[j._modality || "video"] || 0) + 1; });
    return c;
  }, [jobs]);

  // Tag chips reflect the current modality slice (stable while toggling tags).
  const availableTags = useMemo(() => {
    const slice = modality === "all" ? jobs : (jobs as any[]).filter((j) => (j._modality || "video") === modality);
    const set = new Set<string>();
    slice.forEach((j) => jobTags(j).forEach((t) => set.add(t)));
    return Array.from(set).sort((a, b) => a.localeCompare(b));
  }, [jobs, modality]);

  const filtered = useMemo(() => {
    let list = jobs as any[];
    if (modality !== "all") list = list.filter((j) => (j._modality || "video") === modality);
    if (filter.trim()) {
      const q = filter.toLowerCase();
      list = list.filter(
        (j) =>
          (j.prompt || j.text || "").toLowerCase().includes(q) ||
          (j.prompt_id || j.id || "").toLowerCase().includes(q)
      );
    }
    if (selectedTags.length) {
      list = list.filter((j) => {
        const tags = jobTags(j).map((t) => t.toLowerCase());
        return selectedTags.every((t) => tags.includes(t.toLowerCase()));
      });
    }
    return list as RatingJob[];
  }, [jobs, filter, modality, selectedTags]);

  return (
    <div className="min-h-screen bg-[#06080b] text-gray-100 font-sans selection:bg-indigo-500/30 overflow-x-hidden">
      <div className="fixed inset-0 -z-10 bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-indigo-900/10 via-slate-950 to-[#06080b]"></div>

      <Nav active="ai-evals" />

      <main className="max-w-screen-2xl mx-auto px-6 pt-8 pb-20 relative z-10">
        {/* Header */}
        <section className="mb-10 animate-in fade-in slide-in-from-top-4 duration-1000">
          <div className="flex flex-wrap items-center justify-between gap-4 mb-4">
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-emerald-500/10 border border-emerald-500/20 text-emerald-300 text-[10px] font-black uppercase tracking-widest">
              Auto Evaluation
            </div>
            <div className="flex items-center gap-3">
              <a
                href={`${API_BASE_URL}/api/sxs/report.csv`}
                target="_blank"
                rel="noopener noreferrer"
                className="px-4 py-2 rounded-xl text-xs font-bold uppercase tracking-widest bg-indigo-500/20 border border-indigo-500/30 text-indigo-300 hover:bg-indigo-500/30 transition-all"
              >
                Export CSV
              </a>
              <a
                href={`${API_BASE_URL}/api/sxs/report.json`}
                target="_blank"
                rel="noopener noreferrer"
                className="px-4 py-2 rounded-xl text-xs font-bold uppercase tracking-widest bg-purple-500/20 border border-purple-500/30 text-purple-300 hover:bg-purple-500/30 transition-all"
              >
                Export JSON
              </a>
            </div>
          </div>
          <h1 className="text-4xl md:text-5xl font-black text-white tracking-tight leading-tight">
            AI Evals &mdash;{" "}
            <span className="text-transparent bg-clip-text bg-gradient-to-r from-indigo-400 via-purple-400 to-emerald-400">
              Auto Evaluation (Core-5)
            </span>
          </h1>
          <p className="text-gray-500 text-sm md:text-base mt-3 font-light max-w-2xl">
            Machine-generated auto-evaluations across every modality — video, image, and audio — side by side, with per-metric and composite winners.
          </p>
        </section>

        {/* Modality tabs */}
        <div className="mb-6 flex flex-wrap items-center gap-2">
          {([
            { id: "all", label: "All" },
            { id: "video", label: "Video" },
            { id: "image", label: "Image" },
            { id: "audio", label: "TTS" },
          ] as const).map((t) => {
            const isActive = modality === t.id;
            return (
              <button
                key={t.id}
                onClick={() => { setModality(t.id); setSelectedTags([]); }}
                className={`px-4 py-2 rounded-xl text-[11px] font-black uppercase tracking-widest border transition-all ${
                  isActive
                    ? "bg-indigo-500/20 border-indigo-500/40 text-indigo-300"
                    : "bg-white/5 border-white/10 text-gray-400 hover:text-white hover:border-white/20"
                }`}
              >
                {t.label} <span className="opacity-60">{counts[t.id] ?? 0}</span>
              </button>
            );
          })}
        </div>

        {/* Filter */}
        <div className="mb-5">
          <input
            type="text"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Filter by prompt..."
            className="w-full md:max-w-md bg-[#0b0e14] border border-white/10 rounded-2xl px-5 py-3 text-sm text-white placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-indigo-500/50 transition-all"
          />
        </div>

        {/* Tag chips */}
        {availableTags.length > 0 && (
          <div className="mb-8 flex flex-wrap items-center gap-2">
            <span className="text-[10px] font-black uppercase tracking-widest text-gray-600 mr-1">Tags</span>
            {availableTags.map((tag) => {
              const on = selectedTags.includes(tag);
              return (
                <button
                  key={tag}
                  onClick={() =>
                    setSelectedTags((prev) => (on ? prev.filter((t) => t !== tag) : [...prev, tag]))
                  }
                  className={`px-3 py-1.5 rounded-full text-[10px] font-bold tracking-wide border transition-all ${
                    on
                      ? "bg-emerald-500/20 border-emerald-500/40 text-emerald-300"
                      : "bg-white/5 border-white/10 text-gray-400 hover:text-white hover:border-white/20"
                  }`}
                >
                  {tag}
                </button>
              );
            })}
            {selectedTags.length > 0 && (
              <button
                onClick={() => setSelectedTags([])}
                className="px-3 py-1.5 rounded-full text-[10px] font-bold tracking-wide border border-white/10 text-gray-500 hover:text-white transition-all"
              >
                Clear ✕
              </button>
            )}
          </div>
        )}

        {/* Summary across the currently-filtered AI evals */}
        {!isLoading && !error && filtered.length > 0 && (
          <EvalSummary jobs={filtered} modality={modality} />
        )}

        {isLoading ? (
          <div className="py-40 flex flex-col items-center justify-center text-gray-500 gap-4">
            <div className="w-12 h-12 rounded-full border-2 border-indigo-500/30 border-t-indigo-500 animate-spin"></div>
            <p className="font-light tracking-widest uppercase text-xs">Loading AI ratings...</p>
          </div>
        ) : error ? (
          <div className="py-40 flex flex-col items-center justify-center text-gray-500 gap-4">
            <div className="text-red-400 text-sm font-bold bg-red-500/10 border border-red-500/20 px-6 py-4 rounded-2xl">{error}</div>
          </div>
        ) : filtered.length === 0 ? (
          <div className="py-40 flex flex-col items-center justify-center text-gray-500 gap-4 bg-white/[0.02] border border-white/5 rounded-[40px]">
            <p className="font-light tracking-widest uppercase text-xs">No AI ratings found.</p>
          </div>
        ) : (
          <div className="space-y-10">
            {filtered.map((job) =>
              (job as any)._modality && (job as any)._modality !== "video" ? (
                <MediaRatingCard key={job.id} job={job as any} />
              ) : (
                <RatingCard key={job.id} job={job} />
              )
            )}
          </div>
        )}
      </main>
    </div>
  );
}

// ===================================================================
// Summary — aggregates the currently-filtered AI evals into a leaderboard
// (wins / win-rate / avg score per model) plus a per-axis/metric breakdown.
// Works across video (Core-5) and image/TTS (per-metric) modalities.
// ===================================================================
function EvalSummary({ jobs, modality }: { jobs: RatingJob[]; modality: string }) {
  const summary = useMemo(() => {
    const board = new Map<string, { appearances: number; wins: number; scoreSum: number; scoreN: number }>();
    const metricAgg = new Map<string, Map<string, { sum: number; n: number }>>();
    const metricOrder: string[] = [];
    let evaluated = 0;
    // Creative-Director verdict aggregate (video only): verdict A→Seedance, B→Omni.
    const directorBoard = new Map<string, number>();
    let directorTotal = 0;

    jobs.forEach((job) => {
      const de = (job as any).director_eval;
      if (de && (de.verdict === "A" || de.verdict === "B")) {
        directorTotal++;
        const dl = de.verdict === "A" ? "Seedance 2.0" : "Gemini Omni";
        directorBoard.set(dl, (directorBoard.get(dl) || 0) + 1);
      }
      const { engines, winner } = extractJobEvals(job as any);
      const hasEval = engines.some((e) => e.overall != null) || !!winner;
      if (!hasEval) return;
      evaluated++;
      engines.forEach((e) => {
        const b = board.get(e.label) || { appearances: 0, wins: 0, scoreSum: 0, scoreN: 0 };
        b.appearances++;
        if (e.overall != null) { b.scoreSum += e.overall; b.scoreN++; }
        if (winner && e.label === winner) b.wins++;
        board.set(e.label, b);

        const mm = metricAgg.get(e.label) || new Map<string, { sum: number; n: number }>();
        Object.entries(e.metrics).forEach(([k, v]) => {
          if (!metricOrder.includes(k)) metricOrder.push(k);
          const a = mm.get(k) || { sum: 0, n: 0 };
          a.sum += v; a.n++; mm.set(k, a);
        });
        metricAgg.set(e.label, mm);
      });
    });

    const rows = Array.from(board.entries())
      .map(([label, b]) => ({
        label,
        appearances: b.appearances,
        wins: b.wins,
        winRate: b.appearances ? b.wins / b.appearances : 0,
        avg: b.scoreN ? b.scoreSum / b.scoreN : null,
        directorWins: directorBoard.get(label) || 0,
        directorRate: directorTotal ? (directorBoard.get(label) || 0) / directorTotal : null,
      }))
      .sort((a, b) => b.winRate - a.winRate || (b.avg ?? -1) - (a.avg ?? -1) || a.label.localeCompare(b.label));

    const directorTop = Array.from(directorBoard.entries()).sort((a, b) => b[1] - a[1])[0];
    return { evaluated, rows, metricAgg, metricOrder, directorTotal, directorTop };
  }, [jobs]);

  if (summary.evaluated === 0) return null;
  const top = summary.rows[0];
  const showMetrics = modality !== "all" && summary.metricOrder.length > 0 && summary.rows.length > 0;

  return (
    <section className="mb-10 bg-[#0b0e14] border border-white/5 rounded-[40px] p-8 shadow-3xl animate-in fade-in duration-500">
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-sm font-black uppercase tracking-widest text-gray-400">Summary</h2>
        <span className="text-[10px] font-black uppercase tracking-widest text-gray-600">
          {modality === "all" ? "All Modalities" : modality}
        </span>
      </div>

      {/* Stat cards */}
      <div className={`grid grid-cols-2 ${summary.directorTotal > 0 ? "md:grid-cols-5" : "md:grid-cols-4"} gap-4 mb-8`}>
        <StatCard label="Evals" value={String(summary.evaluated)} />
        <StatCard label="Models" value={String(summary.rows.length)} />
        <StatCard label="Top Model" value={top?.label ?? "—"} accent />
        <StatCard label="Top Win Rate" value={top ? `${Math.round(top.winRate * 100)}%` : "—"} accent />
        {summary.directorTotal > 0 && (
          <StatCard label="🎬 Director's Pick" value={summary.directorTop ? summary.directorTop[0] : "—"} accent />
        )}
      </div>

      {/* Leaderboard */}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-[9px] font-black uppercase tracking-widest text-gray-500 border-b border-white/10">
              <th className="text-left py-2 px-2">Model</th>
              <th className="text-right py-2 px-2">Evals</th>
              <th className="text-right py-2 px-2">Wins</th>
              <th className="text-right py-2 px-2">Win Rate</th>
              <th className="text-right py-2 px-2">Avg Score</th>
              {summary.directorTotal > 0 && <th className="text-right py-2 px-2">🎬 Director</th>}
            </tr>
          </thead>
          <tbody>
            {summary.rows.map((r, i) => (
              <tr key={r.label} className="border-b border-white/[0.04] last:border-0">
                <td className="py-2.5 px-2 font-bold text-white flex items-center gap-2">
                  {i === 0 && <span>🏆</span>}
                  {r.label}
                </td>
                <td className="py-2.5 px-2 text-right font-mono text-gray-400">{r.appearances}</td>
                <td className="py-2.5 px-2 text-right font-mono text-gray-400">{r.wins}</td>
                <td className="py-2.5 px-2 text-right font-mono text-emerald-300">{Math.round(r.winRate * 100)}%</td>
                <td className="py-2.5 px-2 text-right font-mono text-indigo-300">{r.avg != null ? `${r.avg.toFixed(2)}/5` : "—"}</td>
                {summary.directorTotal > 0 && (
                  <td className="py-2.5 px-2 text-right font-mono text-amber-300">
                    {r.directorWins > 0 && r.directorRate != null ? `${Math.round(r.directorRate * 100)}% (${r.directorWins})` : "—"}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Per-axis / per-metric average breakdown (single modality only) */}
      {showMetrics && (
        <div className="mt-8">
          <div className="text-[9px] font-black uppercase tracking-widest text-gray-500 mb-3">Average by Metric</div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-[9px] font-black uppercase tracking-widest text-gray-500 border-b border-white/10">
                  <th className="text-left py-2 px-2">Metric</th>
                  {summary.rows.map((r) => (
                    <th key={r.label} className="text-right py-2 px-2">{r.label}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {summary.metricOrder.map((m) => (
                  <tr key={m} className="border-b border-white/[0.04] last:border-0">
                    <td className="py-2 px-2 text-gray-300 font-medium">{m}</td>
                    {summary.rows.map((r) => {
                      const a = summary.metricAgg.get(r.label)?.get(m);
                      const avg = a && a.n ? a.sum / a.n : null;
                      return (
                        <td key={r.label} className="py-2 px-2 text-right font-mono text-gray-400">
                          {avg != null ? avg.toFixed(2) : "—"}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </section>
  );
}

function StatCard({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <div className="bg-[#06080b] border border-white/5 rounded-2xl px-5 py-4">
      <div className="text-[9px] font-black uppercase tracking-widest text-gray-500 mb-1.5">{label}</div>
      <div className={`text-xl font-black truncate ${accent ? "text-transparent bg-clip-text bg-gradient-to-r from-indigo-400 to-emerald-400" : "text-white"}`}>
        {value}
      </div>
    </div>
  );
}

function TranslateButton({ text }: { text?: string }) {
  const [translation, setTranslation] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [show, setShow] = useState(false);

  const run = async () => {
    if (!text) return;
    if (translation) { setShow((s) => !s); return; }
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE_URL}/api/sxs/translate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });
      const data = await res.json();
      setTranslation(data.translation || "(no translation)");
      setShow(true);
    } catch {
      setTranslation("Translation failed");
      setShow(true);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="mt-2">
      <button
        onClick={run}
        disabled={loading || !text}
        className="inline-flex items-center gap-1.5 px-3 py-1 rounded-lg text-[10px] font-black uppercase tracking-widest bg-indigo-500/10 border border-indigo-500/20 text-indigo-300 hover:bg-indigo-500/20 transition-all disabled:opacity-40"
      >
        {loading ? "Translating…" : translation ? (show ? "Hide English" : "Show English") : "Translate to English"}
      </button>
      {show && translation && (
        <p className="mt-2 text-sm text-emerald-200/90 font-light italic leading-relaxed bg-emerald-500/5 border border-emerald-500/15 rounded-xl px-4 py-3">
          {translation}
        </p>
      )}
    </div>
  );
}

const ACCENTS: { text: string; dot: string }[] = [
  { text: "text-indigo-300", dot: "bg-indigo-500" },
  { text: "text-emerald-300", dot: "bg-emerald-500" },
  { text: "text-pink-300", dot: "bg-pink-500" },
  { text: "text-amber-300", dot: "bg-amber-500" },
  { text: "text-blue-300", dot: "bg-blue-500" },
];

function RatingCard({ job }: { job: RatingJob }) {
  // Model keys to show = union of keys in auto_evals + successful results, stable order.
  const modelKeys = useMemo(() => {
    const keys = new Set<string>();
    Object.keys(job.auto_evals || {}).forEach((k) => keys.add(k));
    Object.entries(job.results || {}).forEach(([k, r]) => {
      const ok = r?.url || (r?.status || "").toLowerCase().includes("success") || (r?.status || "").toLowerCase().includes("complete");
      if (ok) keys.add(k);
    });
    return Array.from(keys).sort((a, b) => modelOrder(a) - modelOrder(b) || a.localeCompare(b));
  }, [job]);

  // Per-axis winner = the model key (label) with the max score for that axis. Ties → "Draw".
  const axisWinners = useMemo(() => {
    const out: Record<string, string> = {};
    for (const axis of AXES) {
      let best: number | null = null;
      let bestLabel = "—";
      let tie = false;
      for (const key of modelKeys) {
        const sc = axisScore(job.auto_evals?.[key], axis.key);
        if (sc == null) continue;
        if (best == null || sc > best) { best = sc; bestLabel = prettyModel(key); tie = false; }
        else if (sc === best) { tie = true; }
      }
      out[axis.key as string] = best == null ? "—" : tie ? "Draw" : bestLabel;
    }
    return out;
  }, [job, modelKeys]);

  // Composite winner = model key with highest overall_score. Ties → "Draw".
  const compositeWinner = useMemo(() => {
    let best: number | null = null;
    let bestLabel = "—";
    let tie = false;
    for (const key of modelKeys) {
      const o = job.auto_evals?.[key]?.overall_score;
      if (typeof o !== "number") continue;
      if (best == null || o > best) { best = o; bestLabel = prettyModel(key); tie = false; }
      else if (o === best) { tie = true; }
    }
    return best == null ? "—" : tie ? "Draw" : bestLabel;
  }, [job, modelKeys]);

  return (
    <div className="bg-[#0b0e14] border border-white/5 rounded-[40px] p-8 shadow-3xl">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-4 mb-6">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2 mb-2">
            {job.modality && (
              <span className="px-3 py-1 rounded-full bg-purple-500/10 border border-purple-500/20 text-purple-300 text-[10px] font-black uppercase tracking-widest">
                {job.modality}
              </span>
            )}
            {job.prompt_id && (
              <span className="px-3 py-1 rounded-full bg-white/5 border border-white/10 text-gray-500 text-[10px] font-mono">
                {maskPid(job.prompt_id)}
              </span>
            )}
          </div>
          <p className="text-gray-300 font-light text-base">&ldquo;{job.prompt || "No prompt"}&rdquo;</p>
          <TranslateButton text={job.prompt} />
          {((job.reference_images && job.reference_images.length > 0) || (job.reference_videos && job.reference_videos.length > 0)) && (
            <div className="mt-3">
              <div className="text-[9px] font-black uppercase tracking-widest text-gray-500 mb-2">Input{(job.modality || '').toUpperCase().includes('I2V') ? ' Image' : ''}</div>
              <div className="flex flex-wrap gap-2">
                {job.reference_images?.map((url, i) => (
                  <img key={i} src={url} alt={`input ${i + 1}`} className="w-24 h-24 object-cover rounded-xl border border-white/10 bg-black/40" />
                ))}
                {job.reference_videos?.map((url, i) => (
                  <video key={`v${i}`} src={url} controls muted className="w-24 h-24 object-cover rounded-xl border border-white/10 bg-black/40" />
                ))}
              </div>
            </div>
          )}
        </div>
        <div className="px-4 py-2 rounded-2xl bg-gradient-to-r from-indigo-500/10 to-emerald-500/10 border border-white/10 text-center">
          <div className="text-[9px] font-black uppercase tracking-widest text-gray-500 mb-1">Composite Winner</div>
          <div className="text-sm font-black text-white flex items-center gap-2 justify-center">
            {compositeWinner !== "—" && compositeWinner !== "Draw" && <span>🏆</span>}
            {compositeWinner}
          </div>
        </div>
      </div>

      {/* Side-by-side videos + scores */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
        {modelKeys.map((key, idx) => {
          const label = prettyModel(key);
          return (
            <ModelColumn
              key={key}
              label={label}
              accent={ACCENTS[idx % ACCENTS.length]}
              result={job.results?.[key]}
              ev={job.auto_evals?.[key]}
              ratio={job.ratio}
              axisWinners={axisWinners}
              side={label}
              compositeWinner={compositeWinner}
            />
          );
        })}
      </div>

      {job.director_eval && <DirectorVerdict d={job.director_eval} />}
    </div>
  );
}

function DirectorVerdict({ d }: { d: NonNullable<RatingJob["director_eval"]> }) {
  const [open, setOpen] = useState(false);
  const verdict = (d.verdict || "").toUpperCase();
  const winner = verdict === "A" ? "Seedance 2.0" : verdict === "B" ? "Gemini Omni" : "—";
  return (
    <div className="mt-6 bg-[#06080b] border border-amber-500/15 rounded-3xl p-6">
      <button onClick={() => setOpen((o) => !o)} className="w-full flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <span className="px-3 py-1 rounded-full bg-amber-500/10 border border-amber-500/20 text-amber-300 text-[10px] font-black uppercase tracking-widest">
            Creative Director
          </span>
          <span className="text-sm font-black text-white flex items-center gap-2">🏆 {winner}</span>
        </div>
        <span className="text-[10px] font-black uppercase tracking-widest text-gray-500">{open ? "Hide" : "Details"}</span>
      </button>
      {d.reasoning && <p className="text-sm text-gray-300 font-light italic mt-3 leading-relaxed">{d.reasoning}</p>}
      {open && Array.isArray(d.critique_results) && (
        <div className="mt-4 space-y-3">
          {d.critique_results.map((c, i) => (
            <div key={i} className="bg-white/[0.02] border border-white/5 rounded-2xl p-4">
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs font-black text-white">{c.Category}</span>
                <span className="text-[11px] font-mono text-amber-300">{c.Score}</span>
              </div>
              <p className="text-[12px] text-gray-500 mt-1 leading-relaxed">{c.Reasoning}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function ModelColumn({
  label,
  accent,
  result,
  ev,
  ratio,
  axisWinners,
  side,
  compositeWinner,
}: {
  label: string;
  accent: { text: string; dot: string };
  result?: ResultEntry;
  ev?: AutoEval;
  ratio?: string;
  axisWinners: Record<string, string>;
  side: string;
  compositeWinner: string;
}) {
  const isPortrait = ratio === "9:16";
  const accentText = accent.text;
  const accentDot = accent.dot;
  const flaws = ev?.critical_flaws || [];

  return (
    <div className="bg-[#06080b] border border-white/5 rounded-3xl overflow-hidden flex flex-col">
      <div className="flex items-center justify-between px-5 py-3 border-b border-white/5">
        <div className="flex items-center gap-2">
          <span className={`w-1.5 h-1.5 rounded-full ${accentDot}`}></span>
          <span className={`text-[11px] font-black uppercase tracking-widest ${accentText}`}>{label}</span>
        </div>
        {compositeWinner === side && <span className="text-sm">🏆</span>}
      </div>

      <div className={`${isPortrait ? "aspect-[9/16] max-h-[60vh]" : "aspect-video"} bg-black/50 flex items-center justify-center`}>
        {result?.url ? (
          <video controls preload="metadata" src={result.url} className={`w-full h-full ${isPortrait ? "object-contain" : "object-cover"}`} />
        ) : (
          <div className="text-[10px] font-black uppercase tracking-widest text-gray-600">No video</div>
        )}
      </div>

      {/* Core-5 table */}
      <div className="p-5 space-y-2">
        <div className="flex items-center justify-between text-[9px] font-black uppercase tracking-widest text-gray-500 px-1 pb-1 border-b border-white/5">
          <span>Core-5 Axis</span>
          <span>Score</span>
        </div>
        {AXES.map((axis) => {
          const sc = axisScore(ev, axis.key);
          const a = ev?.[axis.key] as AxisScore | undefined;
          const won = axisWinners[axis.key as string] === side;
          return <AxisRow key={axis.key as string} label={axis.label} score={sc} explanation={a?.explanation} won={won} />;
        })}
        <div className="flex items-center justify-between pt-3 mt-1 border-t border-white/10">
          <span className="text-[11px] font-black uppercase tracking-widest text-white">Overall</span>
          <span className={`text-lg font-black font-mono ${accentText}`}>
            {typeof ev?.overall_score === "number" ? `${ev.overall_score}/5` : "—"}
          </span>
        </div>

        {flaws.length > 0 && (
          <div className="pt-3 mt-1 border-t border-white/5 space-y-1.5">
            <div className="text-[9px] font-black uppercase tracking-widest text-red-400/80">Critical Flaws</div>
            <ul className="space-y-1">
              {flaws.map((f, i) => (
                <li key={i} className="text-[11px] text-red-400/90 flex gap-2">
                  <span className="text-red-500">•</span>
                  <span>{f}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}

function AxisRow({
  label,
  score,
  explanation,
  won,
}: {
  label: string;
  score: number | null;
  explanation?: string;
  won: boolean;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="border-b border-white/[0.03] last:border-0">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between py-2 px-1 text-left hover:bg-white/[0.02] rounded-lg transition-colors"
      >
        <span className="text-xs text-gray-300 font-medium flex items-center gap-2">
          {won && <span className="text-[10px]">🏆</span>}
          {label}
        </span>
        <span className="flex items-center gap-2">
          <span className={`text-sm font-black font-mono ${won ? "text-emerald-300" : "text-gray-400"}`}>
            {score != null ? `${score}/5` : "—"}
          </span>
          <span className="text-gray-600 text-[10px]">{open ? "▲" : "▼"}</span>
        </span>
      </button>
      {open && explanation && (
        <div className="px-3 pb-3 text-[11px] text-gray-500 font-light leading-relaxed italic">{explanation}</div>
      )}
      {open && !explanation && (
        <div className="px-3 pb-3 text-[11px] text-gray-600 font-light italic">No explanation provided.</div>
      )}
    </div>
  );
}

// ===================================================================
// Image / TTS auto-eval card — ai_eval has A/B sides with per-metric scores.
// ===================================================================
function MediaRatingCard({ job }: { job: any }) {
  const isAudio = job._modality === "audio";
  const ai = job.ai_eval || {};
  const sides = ["A", "B"];
  const winner = (ai.winner_side || "").toUpperCase();
  const promptText = job.prompt || job.text || "No prompt";
  const metricKeys: string[] =
    Array.isArray(ai.metrics) && ai.metrics.length
      ? ai.metrics
      : Array.from(
          new Set(
            sides.flatMap((s) =>
              Object.keys(ai[s] || {}).filter((k) => typeof ai[s][k] === "number" && k !== "overall_score")
            )
          )
        );

  return (
    <div className="bg-[#0b0e14] border border-white/5 rounded-[40px] p-8 shadow-3xl">
      <div className="flex flex-wrap items-start justify-between gap-4 mb-6">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2 mb-2">
            <span className="px-3 py-1 rounded-full bg-purple-500/10 border border-purple-500/20 text-purple-300 text-[10px] font-black uppercase tracking-widest">
              {isAudio ? "TTS" : "Image"}
            </span>
            {(job.mode || job.modality) && (
              <span className="px-3 py-1 rounded-full bg-white/5 border border-white/10 text-gray-400 text-[10px] font-black uppercase tracking-widest">
                {job.mode || job.modality}
              </span>
            )}
            <span className="px-3 py-1 rounded-full bg-white/5 border border-white/10 text-gray-500 text-[10px] font-mono">
              {maskPid(job.prompt_id || job.id)}
            </span>
          </div>
          <p className="text-gray-300 font-light text-base">&ldquo;{promptText}&rdquo;</p>
          {job.input_image && (
            <div className="mt-3">
              <div className="text-[9px] font-black uppercase tracking-widest text-gray-500 mb-2">Input Image</div>
              <img src={mediaUrl(job.input_image)} alt="input" className="w-24 h-24 object-cover rounded-xl border border-white/10 bg-black/40" />
            </div>
          )}
        </div>
        <div className="px-4 py-2 rounded-2xl bg-gradient-to-r from-indigo-500/10 to-emerald-500/10 border border-white/10 text-center">
          <div className="text-[9px] font-black uppercase tracking-widest text-gray-500 mb-1">AI Winner</div>
          <div className="text-sm font-black text-white flex items-center gap-2 justify-center">
            {ai.winner_engine ? <><span>🏆</span>{prettyModel(ai.winner_engine)}</> : "—"}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {sides.map((side, idx) => {
          const result = job.results?.[side] || {};
          const ev = ai[side] || {};
          const label = prettyModel(job.side_map?.[side] || result.model || result.engine || side);
          const won = winner === side;
          const accent = ACCENTS[idx % ACCENTS.length];
          const failed = (result.status || "").toLowerCase() === "error" || !result.url;
          return (
            <div key={side} className="bg-[#06080b] border border-white/5 rounded-3xl overflow-hidden flex flex-col">
              <div className="flex items-center justify-between px-5 py-3 border-b border-white/5">
                <div className="flex items-center gap-2">
                  <span className={`w-1.5 h-1.5 rounded-full ${accent.dot}`}></span>
                  <span className={`text-[11px] font-black uppercase tracking-widest ${accent.text}`}>{label}</span>
                </div>
                {won && <span className="text-sm">🏆</span>}
              </div>

              <div className={`${isAudio ? "p-5" : "aspect-square"} bg-black/40 flex items-center justify-center`}>
                {failed ? (
                  <div className="text-[10px] font-black uppercase tracking-widest text-red-500/70 px-4 py-6 text-center">
                    {result.error ? `Error: ${String(result.error).slice(0, 80)}` : "No output"}
                  </div>
                ) : isAudio ? (
                  <audio controls src={result.url} className="w-full" />
                ) : (
                  <img src={result.url} alt={label} className="w-full h-full object-cover" />
                )}
              </div>

              <div className="p-5 space-y-2">
                <div className="flex items-center justify-between text-[9px] font-black uppercase tracking-widest text-gray-500 px-1 pb-1 border-b border-white/5">
                  <span>Metric</span><span>Score</span>
                </div>
                {metricKeys.map((k) => (
                  <div key={k} className="flex items-center justify-between py-1.5 px-1 border-b border-white/[0.03] last:border-0">
                    <span className="text-xs text-gray-300 font-medium">{prettyMetric(k)}</span>
                    <span className="text-sm font-black font-mono text-gray-400">{typeof ev[k] === "number" ? `${ev[k]}/5` : "—"}</span>
                  </div>
                ))}
                <div className="flex items-center justify-between pt-3 mt-1 border-t border-white/10">
                  <span className="text-[11px] font-black uppercase tracking-widest text-white">Overall</span>
                  <span className={`text-lg font-black font-mono ${accent.text}`}>{typeof ev.overall_score === "number" ? `${ev.overall_score}/5` : "—"}</span>
                </div>
                {ev.comment && <p className="text-[11px] text-gray-500 font-light italic leading-relaxed pt-2">{ev.comment}</p>}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
