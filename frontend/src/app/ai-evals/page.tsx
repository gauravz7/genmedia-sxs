"use client";
import { useState, useEffect, useMemo } from "react";
import { API_BASE_URL, formatUrl } from "@/lib/api";
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

export default function AiEvals() {
  const [jobs, setJobs] = useState<RatingJob[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string>("");
  const [filter, setFilter] = useState("");

  useEffect(() => {
    const load = async () => {
      setIsLoading(true);
      setError("");
      try {
        const res = await fetch(`${API_BASE_URL}/api/sxs/jobs`);
        if (!res.ok) throw new Error(`Server responded ${res.status}`);
        const data = await res.json();
        const list: RatingJob[] = Array.isArray(data) ? data : (data.jobs ?? []);
        const mapped = list.map((j) => {
          const results = j.results || {};
          const fixed: Record<string, ResultEntry> = {};
          Object.keys(results).forEach((k) => {
            fixed[k] = { ...results[k], url: formatUrl(results[k]?.url) };
          });
          return {
            ...j,
            results: fixed,
            reference_images: (j.reference_images || []).map(formatUrl).filter((u): u is string => !!u),
            reference_videos: (j.reference_videos || []).map(formatUrl).filter((u): u is string => !!u),
          };
        });
        setJobs(mapped);
      } catch (err: any) {
        setError(err?.message || "Failed to load ratings");
      } finally {
        setIsLoading(false);
      }
    };
    load();
  }, []);

  const filtered = useMemo(() => {
    if (!filter.trim()) return jobs;
    const q = filter.toLowerCase();
    return jobs.filter(
      (j) =>
        (j.customer || "").toLowerCase().includes(q) ||
        (j.prompt || "").toLowerCase().includes(q) ||
        (j.prompt_id || "").toLowerCase().includes(q)
    );
  }, [jobs, filter]);

  return (
    <div className="min-h-screen bg-[#06080b] text-gray-100 font-sans selection:bg-indigo-500/30 overflow-x-hidden">
      <div className="fixed inset-0 -z-10 bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-indigo-900/10 via-slate-950 to-[#06080b]"></div>

      <Nav active="ai-evals" />

      <main className="max-w-screen-2xl mx-auto px-6 pt-32 pb-20 relative z-10">
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
            Every video&apos;s machine-generated Core-5 scores, side by side, with per-axis and composite winners.
          </p>
        </section>

        {/* Filter */}
        <div className="mb-8">
          <input
            type="text"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Filter by customer or prompt..."
            className="w-full md:max-w-md bg-[#0b0e14] border border-white/10 rounded-2xl px-5 py-3 text-sm text-white placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-indigo-500/50 transition-all"
          />
        </div>

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
            {filtered.map((job) => (
              <RatingCard key={job.id} job={job} />
            ))}
          </div>
        )}
      </main>
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
            {job.customer && (
              <span className="px-3 py-1 rounded-full bg-indigo-500/10 border border-indigo-500/20 text-indigo-300 text-[10px] font-black uppercase tracking-widest">
                {job.customer}
              </span>
            )}
            {job.modality && (
              <span className="px-3 py-1 rounded-full bg-purple-500/10 border border-purple-500/20 text-purple-300 text-[10px] font-black uppercase tracking-widest">
                {job.modality}
              </span>
            )}
            {job.prompt_id && (
              <span className="px-3 py-1 rounded-full bg-white/5 border border-white/10 text-gray-500 text-[10px] font-mono">
                {job.prompt_id}
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
