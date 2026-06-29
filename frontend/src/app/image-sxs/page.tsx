"use client";
import { useState, useEffect, useCallback } from "react";
import { Search, Filter, X, ChevronRight } from "lucide-react";
import { API_BASE_URL } from "@/lib/api";
import Nav from "@/components/Nav";
import VoteProgress from "@/components/VoteProgress";
import TranslateButton from "@/components/TranslateButton";

// ===================================================================
// Image SxS — RATING-ONLY public arena. Anyone with an ldap can vote.
// Generation/admin lives in /admin; results live in /analytics.
// ===================================================================

// Local media-URL helper. The backend proxies images at
// `/api/image/media?url=...`; the shared formatUrl() only rewrites
// /api/media + /api/sxs/media, so we prefix our own path here.
const imgUrl = (url?: string): string | undefined => {
  if (!url) return url;
  if (url.startsWith("/api/image/media") || url.startsWith("/api/media")) {
    return `${API_BASE_URL}${url}`;
  }
  return url;
};

const T2I_METRICS = ["prompt_following", "aesthetic", "detail", "artifact_free"];
const I2I_EXTRA = "edit_fidelity";
const METRIC_LABELS: Record<string, string> = {
  prompt_following: "Prompt Following",
  aesthetic: "Aesthetic",
  detail: "Detail / Sharpness",
  artifact_free: "Artifact-Free",
  edit_fidelity: "Edit Fidelity",
};

export default function ImageSxSArena() {
  const [mounted, setMounted] = useState(false);
  const [ldap, setLdap] = useState("");
  const [ldapInput, setLdapInput] = useState("");

  useEffect(() => {
    setMounted(true);
    const saved = typeof window !== "undefined" ? (localStorage.getItem("project_pulse_ldap") || localStorage.getItem("pp_ldap")) : "";
    // Always show the "enter arena" gate; prefill the last-used ldap for one-click entry.
    if (saved) setLdapInput(saved);
  }, []);

  const enterArena = (e: React.FormEvent) => {
    e.preventDefault();
    const ld = ldapInput.trim().toLowerCase();
    if (!ld) return;
    if (typeof window !== "undefined") {
      localStorage.setItem("project_pulse_ldap", ld);
      localStorage.setItem("pp_ldap", ld);
    }
    setLdap(ld);
  };

  if (!mounted) return <div className="min-h-screen bg-[#06080b]" />;

  return (
    <div className="min-h-screen bg-[#06080b] text-gray-100 font-sans selection:bg-indigo-500/30 overflow-x-hidden">
      <div className="fixed inset-0 -z-10 bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-indigo-900/10 via-slate-950 to-[#06080b]"></div>
      <Nav active="image-sxs" />

      {ldap ? (
        <BlindEvalPanel ldap={ldap} />
      ) : (
        <main className="max-w-screen-2xl mx-auto px-6 pt-8 pb-20 relative z-10">
          <section className="mb-10 animate-in fade-in slide-in-from-top-4 duration-1000">
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-indigo-500/10 border border-indigo-500/20 text-indigo-300 text-[10px] font-black uppercase tracking-widest mb-4">
              Image Modality
            </div>
            <h1 className="text-4xl md:text-5xl font-black text-white tracking-tight leading-tight">
              Image SxS &mdash;{" "}
              <span className="text-transparent bg-clip-text bg-gradient-to-r from-indigo-400 via-purple-400 to-emerald-400">
                Gemini Image vs GPT-image
              </span>
            </h1>
            <p className="text-gray-500 text-sm md:text-base mt-3 font-light max-w-2xl">
              T2I &amp; I2I side-by-side: blind human A/B plus an AI judge across prompt-following,
              aesthetic, detail, artifact-free, and edit fidelity.
            </p>
          </section>
          <LdapGate ldapInput={ldapInput} setLdapInput={setLdapInput} onSubmit={enterArena} />
        </main>
      )}
    </div>
  );
}

// ===================================================================
// LDAP "enter arena" gate (no admin password — just identity)
// ===================================================================
function LdapGate({ ldapInput, setLdapInput, onSubmit }: { ldapInput: string; setLdapInput: (v: string) => void; onSubmit: (e: React.FormEvent) => void }) {
  return (
    <div className="flex items-center justify-center py-10">
      <div className="max-w-md w-full bg-[#0d1017] border border-white/10 rounded-[40px] p-10 shadow-3xl animate-in fade-in zoom-in-95 duration-500">
        <div className="flex flex-col items-center mb-10">
          <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center shadow-3xl mb-6 font-black text-white">IMG</div>
          <h2 className="text-3xl font-bold text-white tracking-tight">Access Arena</h2>
          <p className="text-gray-500 text-sm mt-2 text-center">Enter your LDAP to record evaluations.</p>
        </div>
        <form onSubmit={onSubmit} className="space-y-6">
          <div className="space-y-2">
            <label className="text-xs font-bold text-gray-500 uppercase tracking-widest px-1">Identity (LDAP)</label>
            <input type="text" value={ldapInput} onChange={(e) => setLdapInput(e.target.value.toLowerCase())} placeholder="username" autoFocus
              className="w-full bg-[#06080b] border border-white/10 rounded-2xl px-6 py-4 text-white font-mono text-center focus:outline-none focus:ring-2 focus:ring-indigo-500/50 transition-all" />
          </div>
          <button type="submit" disabled={!ldapInput.trim()} className="w-full bg-gradient-to-r from-indigo-500 to-purple-600 hover:from-indigo-400 hover:to-purple-500 text-white font-black py-5 rounded-2xl shadow-3xl transition-all active:scale-[0.98] disabled:opacity-40 uppercase tracking-widest">Enter Evaluation</button>
        </form>
      </div>
    </div>
  );
}

// ===================================================================
// Blind eval: side-by-side image A / B + per-metric rating widget
// ===================================================================
function BlindEvalPanel({ ldap }: { ldap: string }) {
  const [pair, setPair] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [scores, setScores] = useState<Record<string, number>>({});
  const [justification, setJustification] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [reveal, setReveal] = useState<any>(null);
  const [voteCount, setVoteCount] = useState(0);
  const [voteAck, setVoteAck] = useState("");
  const [expandedImage, setExpandedImage] = useState<string | null>(null);

  // Search & tag filter
  const [searchPromptId, setSearchPromptId] = useState("");
  const [searchText, setSearchText] = useState("");
  const [activeTag, setActiveTag] = useState("");
  const [availableTags, setAvailableTags] = useState<string[]>([]);
  const [showTagFilter, setShowTagFilter] = useState(false);

  const isI2I = (pair?.mode || "t2i") === "i2i";
  const metrics = isI2I ? [...T2I_METRICS, I2I_EXTRA] : T2I_METRICS;

  const loadPair = useCallback(async (forcePromptId?: string, forceTag?: string, forceSearch?: string) => {
    setLoading(true); setError(""); setReveal(null); setScores({}); setJustification("");
    try {
      // `undefined` → fall back to current state; an explicit string (incl. "") overrides.
      const tag = forceTag ?? activeTag;
      const search = forceSearch ?? searchText;
      const params = new URLSearchParams();
      if (forcePromptId) params.set("prompt_id", forcePromptId);
      if (tag) params.set("tag", tag);
      if (search) params.set("search", search);
      const qs = params.toString() ? `?${params.toString()}` : "";
      const res = await fetch(`${API_BASE_URL}/api/image/pair${qs}`);
      const data = await res.json();
      if (data?.status === "error") { setError(data.message || "No pairs ready"); setPair(null); }
      else setPair(data);
    } catch { setError("Failed to load pair"); setPair(null); }
    finally { setLoading(false); }
  }, [activeTag, searchText]);

  const fetchTags = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/api/image/tags`);
      const data = await res.json();
      if (Array.isArray(data?.tags)) setAvailableTags(data.tags);
    } catch { /* non-fatal */ }
  }, []);

  useEffect(() => { loadPair(); fetchTags(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, []);

  const setMetric = (m: string, v: number) => setScores((s) => ({ ...s, [m]: v }));

  const handleSkip = () => { setReveal(null); loadPair(); };

  const handleTagClick = (tag: string) => {
    if (activeTag === tag) { setActiveTag(""); loadPair(undefined, ""); }
    else { setActiveTag(tag); loadPair(undefined, tag); }
  };

  const handleClearFilters = () => {
    setActiveTag(""); setSearchText(""); setSearchPromptId("");
    loadPair(undefined, "", "");
  };

  const submitVote = async (winnerSide: "A" | "B" | "tie") => {
    if (!pair || submitting) return;
    setSubmitting(true); setVoteAck("");
    // Persist BOTH keys so the Analytics 10-vote gate counts these votes.
    if (typeof window !== "undefined" && ldap) {
      localStorage.setItem("pp_ldap", ldap);
      localStorage.setItem("project_pulse_ldap", ldap);
    }
    try {
      const res = await fetch(`${API_BASE_URL}/api/image/vote`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ job_id: pair.job_id, winner_side: winnerSide, scores, justification, ldap: ldap || "anonymous" }),
      });
      if (!res.ok) throw new Error(`Server responded ${res.status}`);
      setVoteCount((c) => c + 1);
      setVoteAck("Vote recorded.");
      // Reveal the AI judge + identities after voting.
      const ai = await fetch(`${API_BASE_URL}/api/image/aieval/${pair.job_id}`).then((r) => r.json()).catch(() => null);
      setReveal(ai);
    } catch (e: any) {
      setError(e?.message || "Vote failed");
      setVoteAck("Vote failed…");
    } finally { setSubmitting(false); }
  };

  return (
    <>
      {/* Vote acknowledgement toast */}
      {voteAck && (
        <div className={`fixed top-24 left-1/2 -translate-x-1/2 z-[120] px-6 py-3 rounded-2xl border shadow-2xl text-sm font-bold flex items-center gap-3 animate-in fade-in slide-in-from-top-4 duration-300 ${voteAck.startsWith("Vote failed") ? "bg-red-500/15 border-red-500/40 text-red-200" : "bg-emerald-500/15 border-emerald-500/40 text-emerald-200"}`}>
          <span>{voteAck.startsWith("Vote failed") ? "⚠️" : "✓"}</span>
          <span>{voteAck}</span>
        </div>
      )}

      {/* Click-to-zoom overlay */}
      {expandedImage && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-black/90 backdrop-blur-sm cursor-zoom-out animate-in fade-in duration-300" onClick={() => setExpandedImage(null)}>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={expandedImage} className="max-w-full max-h-full rounded-2xl shadow-2xl border border-white/10" alt="Expanded view" />
        </div>
      )}

      {/* Sub-toolbar: search / tag filter (left) + VoteProgress HUD (right) */}
      <div className="w-full border-b border-white/5 bg-[#06080b]/60 backdrop-blur-2xl z-40">
        <div className="max-w-screen-2xl mx-auto px-6 py-3 flex items-center justify-between gap-4 flex-wrap">
          <div className="flex items-center gap-3 flex-wrap">
            <form onSubmit={(e) => { e.preventDefault(); loadPair(searchPromptId); }} className="relative flex items-center group">
              <Search className="w-4 h-4 text-gray-500 absolute left-3 group-focus-within:text-indigo-400 transition-colors" />
              <input type="text" placeholder="Prompt ID..." value={searchPromptId} onChange={(e) => setSearchPromptId(e.target.value)} className="pl-9 pr-4 py-2 bg-white/5 border border-white/10 rounded-xl text-sm text-white font-medium focus:outline-none focus:ring-2 focus:ring-indigo-500/50 focus:bg-white/10 transition-all w-40 placeholder-gray-500" />
            </form>
            <form onSubmit={(e) => { e.preventDefault(); loadPair(undefined, undefined, searchText); }} className="relative flex items-center group">
              <Search className="w-4 h-4 text-gray-500 absolute left-3 group-focus-within:text-indigo-400 transition-colors" />
              <input type="text" placeholder="Search prompts..." value={searchText} onChange={(e) => setSearchText(e.target.value)} className="pl-9 pr-4 py-2 bg-white/5 border border-white/10 rounded-xl text-sm text-white font-medium focus:outline-none focus:ring-2 focus:ring-indigo-500/50 focus:bg-white/10 transition-all w-48 placeholder-gray-500" />
            </form>
            {availableTags.length > 0 && (
              <button onClick={() => setShowTagFilter(!showTagFilter)} className={`flex items-center gap-2 px-3 py-2 rounded-xl text-xs font-bold uppercase tracking-widest transition-all border ${activeTag ? "bg-indigo-500/20 border-indigo-500/40 text-indigo-300" : "bg-white/5 border-white/10 text-gray-500 hover:text-white"}`}>
                <Filter className="w-3.5 h-3.5" />
                {activeTag || "Tags"}
                {activeTag && <X className="w-3 h-3 ml-1 cursor-pointer" onClick={(e) => { e.stopPropagation(); handleClearFilters(); }} />}
              </button>
            )}
          </div>
          <VoteProgress ldap={ldap} refreshKey={voteCount} />
        </div>
        {showTagFilter && availableTags.length > 0 && (
          <div className="border-t border-white/5 bg-[#06080b]/80 px-6 py-3">
            <div className="max-w-screen-2xl mx-auto flex flex-wrap gap-2">
              {availableTags.map((tag) => (
                <button key={tag} onClick={() => handleTagClick(tag)} className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all border ${activeTag === tag ? "bg-indigo-500 text-white border-indigo-500 shadow-lg" : "bg-white/5 border-white/10 text-gray-400 hover:text-white hover:border-white/20"}`}>
                  {tag}
                </button>
              ))}
              {activeTag && (
                <button onClick={handleClearFilters} className="px-3 py-1.5 rounded-lg text-xs font-bold text-red-400 border border-red-500/20 bg-red-500/10 hover:bg-red-500/20 transition-all flex items-center gap-1">
                  <X className="w-3 h-3" /> Clear
                </button>
              )}
            </div>
          </div>
        )}
      </div>

      <main className="max-w-screen-2xl mx-auto px-6 pt-8 pb-20 relative z-10">
        <section className="mb-8 animate-in fade-in slide-in-from-top-4 duration-1000">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-indigo-500/10 border border-indigo-500/20 text-indigo-300 text-[10px] font-black uppercase tracking-widest mb-4">
            Image Modality
          </div>
          <h1 className="text-3xl md:text-4xl font-black text-white tracking-tight leading-tight">
            Image SxS &mdash;{" "}
            <span className="text-transparent bg-clip-text bg-gradient-to-r from-indigo-400 via-purple-400 to-emerald-400">
              Gemini Image vs GPT-image
            </span>
          </h1>
        </section>

        {loading ? (
          <div className="py-32 flex flex-col items-center gap-4 text-gray-500"><div className="w-10 h-10 rounded-full border-2 border-indigo-500/30 border-t-indigo-500 animate-spin"></div><p className="text-xs uppercase tracking-widest">Loading pair…</p></div>
        ) : error || !pair ? (
          <div className="py-24 text-center">
            <p className="text-gray-400 mb-6">{error || "No image pairs ready for voting yet."}</p>
            <button onClick={() => loadPair()} className="px-6 py-3 rounded-2xl bg-indigo-500/20 border border-indigo-500/40 text-indigo-300 font-black uppercase tracking-widest text-xs hover:bg-indigo-500/30 transition-all">Refresh</button>
          </div>
        ) : (
          <div className="space-y-8">
            <div className="flex items-start justify-between gap-4 flex-wrap">
              <div className="min-w-0">
                <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-purple-500/10 border border-purple-500/20 text-purple-300 text-[10px] font-black uppercase tracking-widest mb-2">{pair.mode || "t2i"}</div>
                <p className="text-gray-200 font-light text-lg max-w-3xl">&ldquo;{pair.prompt}&rdquo;</p>
                {pair.prompt && <TranslateButton text={pair.prompt} />}
              </div>
              <button onClick={handleSkip} className="flex items-center gap-2 px-5 py-3 bg-red-500/5 border border-red-500/10 rounded-2xl hover:bg-red-500/10 transition-all group shrink-0">
                <ChevronRight className="w-4 h-4 text-red-400 group-hover:translate-x-0.5 transition-transform" />
                <span className="text-xs font-black uppercase tracking-widest text-red-400">Skip</span>
              </button>
            </div>

            {isI2I && pair.input_image && (
              <div className="bg-white/[0.02] border border-white/5 rounded-3xl p-4 inline-block">
                <div className="text-[10px] font-black uppercase tracking-widest text-gray-500 mb-2">Original Input</div>
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={imgUrl(pair.input_image)} alt="input" onClick={() => setExpandedImage(imgUrl(pair.input_image) ?? null)} className="max-h-48 rounded-2xl cursor-zoom-in" />
              </div>
            )}

            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              {(["A", "B"] as const).map((side) => {
                const v = side === "A" ? pair.variant_a : pair.variant_b;
                const accent = side === "A" ? "indigo" : "emerald";
                const revealedEngine = reveal?.side_map?.[side];
                return (
                  <div key={side} className="bg-[#0b0e14] border border-white/5 rounded-[32px] overflow-hidden">
                    <div className="flex items-center justify-between px-5 py-3 border-b border-white/5">
                      <span className={`text-sm font-black uppercase tracking-widest ${accent === "indigo" ? "text-indigo-300" : "text-emerald-300"}`}>Image {side}</span>
                      {revealedEngine && <span className="text-[10px] font-mono text-gray-400">{revealedEngine}</span>}
                    </div>
                    <div className="bg-black/50 flex items-center justify-center min-h-[300px] p-2">
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img src={imgUrl(v?.url)} alt={`image ${side}`} onClick={() => setExpandedImage(imgUrl(v?.url) ?? null)} className="max-h-[60vh] w-auto rounded-2xl object-contain cursor-zoom-in" />
                    </div>
                  </div>
                );
              })}
            </div>

            {/* Per-metric rating widget */}
            <section className="bg-[#0b0e14] border border-white/10 rounded-[32px] p-8 space-y-6">
              <h3 className="text-sm font-black uppercase tracking-widest text-gray-400">Rate the winner (1–5 per metric)</h3>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                {metrics.map((m) => (
                  <div key={m} className="space-y-2">
                    <div className="flex items-center justify-between">
                      <label className="text-xs font-bold text-gray-300">{METRIC_LABELS[m]}</label>
                      <span className="text-xs font-mono text-indigo-300">{scores[m] ?? 3}</span>
                    </div>
                    <input type="range" min={1} max={5} step={1} value={scores[m] ?? 3} onChange={(e) => setMetric(m, parseInt(e.target.value))}
                      className="w-full accent-indigo-500" />
                  </div>
                ))}
              </div>
              <textarea value={justification} onChange={(e) => setJustification(e.target.value)} placeholder="Justification (optional)"
                className="w-full bg-[#06080b] border border-white/10 rounded-2xl px-4 py-3 text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-indigo-500/40" rows={2} />
              <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                <button onClick={() => submitVote("A")} disabled={submitting} className="py-4 rounded-2xl bg-indigo-500/20 border border-indigo-500/40 text-indigo-200 font-black uppercase tracking-widest text-sm hover:bg-indigo-500/30 transition-all disabled:opacity-40">A Wins</button>
                <button onClick={() => submitVote("tie")} disabled={submitting} className="py-4 rounded-2xl bg-white/5 border border-white/10 text-gray-300 font-black uppercase tracking-widest text-sm hover:bg-white/10 transition-all disabled:opacity-40">Tie</button>
                <button onClick={() => submitVote("B")} disabled={submitting} className="py-4 rounded-2xl bg-emerald-500/20 border border-emerald-500/40 text-emerald-200 font-black uppercase tracking-widest text-sm hover:bg-emerald-500/30 transition-all disabled:opacity-40">B Wins</button>
              </div>
            </section>

            {/* AI judge reveal (after vote) */}
            {reveal && (
              <section className="bg-[#0b0e14] border border-emerald-500/20 rounded-[32px] p-8 space-y-4 animate-in fade-in duration-500">
                <h3 className="text-sm font-black uppercase tracking-widest text-emerald-300">AI Judge</h3>
                <div className="text-xs text-gray-400">Winner: <span className="text-white font-bold">{reveal.ai_eval?.winner_side || "—"}</span> {reveal.ai_eval?.winner_engine && <span className="font-mono text-emerald-300">({reveal.ai_eval.winner_engine})</span>}</div>
                {reveal.ai_eval?.justification && <p className="text-sm text-gray-300 font-light italic">{reveal.ai_eval.justification}</p>}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {(["A", "B"] as const).map((s) => (
                    <div key={s} className="bg-[#06080b] border border-white/5 rounded-2xl p-4">
                      <div className="text-xs font-black text-gray-400 mb-2">Image {s} — {reveal.side_map?.[s]}</div>
                      {Object.entries(reveal.ai_eval?.[s] || {}).filter(([k]) => METRIC_LABELS[k] || k === "overall_score").map(([k, val]) => (
                        <div key={k} className="flex items-center justify-between text-xs py-0.5">
                          <span className="text-gray-500">{METRIC_LABELS[k] || k}</span>
                          <span className="text-gray-200 font-mono">{String(val)}</span>
                        </div>
                      ))}
                    </div>
                  ))}
                </div>
                <button onClick={() => loadPair()} className="px-6 py-3 rounded-2xl bg-indigo-500/20 border border-indigo-500/40 text-indigo-300 font-black uppercase tracking-widest text-xs hover:bg-indigo-500/30 transition-all">Next Pair →</button>
              </section>
            )}
          </div>
        )}
      </main>
    </>
  );
}
