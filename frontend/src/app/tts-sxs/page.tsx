"use client";
import { useState, useEffect, useCallback } from "react";
import { Search, Filter, X, ChevronRight } from "lucide-react";
import { API_BASE_URL } from "@/lib/api";
import Nav from "@/components/Nav";
import VoteProgress from "@/components/VoteProgress";
import TranslateButton from "@/components/TranslateButton";

// ===================================================================
// TTS SxS — RATING-ONLY public arena. Anyone with an ldap can vote.
// Generation/admin lives in /admin; results live in /analytics.
// ===================================================================

// Audio URLs come back as backend-relative proxy paths (/api/tts/media?url=...).
const audioUrl = (url?: string) => {
  if (!url) return url;
  if (url.startsWith("/api/tts/media") || url.startsWith("/api/media")) return `${API_BASE_URL}${url}`;
  return url;
};

const METRICS = [
  { key: "naturalness", label: "Naturalness" },
  { key: "style_adherence", label: "Style Adherence" },
  { key: "expressiveness", label: "Expressiveness" },
  { key: "pacing", label: "Pacing" },
  { key: "pronunciation_clarity", label: "Pronunciation" },
];

export default function TtsSxSArena() {
  const [mounted, setMounted] = useState(false);
  const [ldap, setLdap] = useState("");
  const [ldapInput, setLdapInput] = useState("");

  useEffect(() => {
    setMounted(true);
    const saved = typeof window !== "undefined" ? (localStorage.getItem("project_pulse_ldap") || localStorage.getItem("pp_ldap")) : "";
    // Auto-enter if an ldap was already provided (don't re-ask across arenas/sessions).
    if (saved) { setLdap(saved); setLdapInput(saved); }
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
      <Nav active="tts" />

      {ldap ? (
        <EvaluatePanel ldap={ldap} />
      ) : (
        <main className="max-w-screen-2xl mx-auto px-6 pt-8 pb-20 relative z-10">
          <section className="mb-10 animate-in fade-in slide-in-from-top-4 duration-1000">
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-indigo-500/10 border border-indigo-500/20 text-indigo-300 text-[10px] font-black uppercase tracking-widest mb-4">
              Text-to-Speech Pipeline
            </div>
            <h1 className="text-4xl md:text-5xl font-black text-white tracking-tight leading-tight">
              TTS Studio &mdash;{" "}
              <span className="text-transparent bg-clip-text bg-gradient-to-r from-indigo-400 via-purple-400 to-emerald-400">
                Gemini 3.1 Flash TTS vs ElevenLabs
              </span>
            </h1>
            <p className="text-gray-500 text-sm md:text-base mt-3 font-light max-w-2xl">
              Blind A/B vote on rendered voice-over clips with per-metric scoring. An AI audio judge scores each pair automatically.
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
    <div className="max-w-md w-full mx-auto bg-[#0d1017] border border-white/10 rounded-[40px] p-10 shadow-3xl animate-in fade-in zoom-in-95 duration-500">
      <div className="flex flex-col items-center mb-10">
        <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center shadow-3xl mb-6 font-black text-white">TTS</div>
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
  );
}

// ===================================================================
// Blind evaluation: A/B players + per-metric rating
// ===================================================================
function EvaluatePanel({ ldap }: { ldap: string }) {
  const [pair, setPair] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [scores, setScores] = useState<Record<string, Record<string, number>>>({ A: {}, B: {} });
  const [winner, setWinner] = useState<string>("");
  const [justification, setJustification] = useState("");
  const [reveal, setReveal] = useState<any>(null);
  const [submitting, setSubmitting] = useState(false);
  const [msg, setMsg] = useState("");
  const [voteCount, setVoteCount] = useState(0);
  const [voteAck, setVoteAck] = useState("");

  // Search & tag filter
  const [searchPromptId, setSearchPromptId] = useState("");
  const [searchText, setSearchText] = useState("");
  const [activeTag, setActiveTag] = useState("");
  const [availableTags, setAvailableTags] = useState<string[]>([]);
  const [showTagFilter, setShowTagFilter] = useState(false);
  const [activeLanguage, setActiveLanguage] = useState("");
  const [availableLanguages, setAvailableLanguages] = useState<string[]>([]);

  const loadPair = useCallback(async (forcePromptId?: string, forceTag?: string, forceSearch?: string, forceLang?: string) => {
    setLoading(true); setReveal(null); setWinner(""); setJustification(""); setMsg("");
    setScores({ A: {}, B: {} });
    try {
      // `undefined` → fall back to current state; an explicit string (incl. "") overrides.
      const tag = forceTag ?? activeTag;
      const search = forceSearch ?? searchText;
      const lang = forceLang ?? activeLanguage;
      const params = new URLSearchParams();
      if (forcePromptId) params.set("prompt_id", forcePromptId);
      if (tag) params.set("tag", tag);
      if (search) params.set("search", search);
      if (lang) params.set("language", lang);
      const qs = params.toString() ? `?${params.toString()}` : "";
      const res = await fetch(`${API_BASE_URL}/api/tts/pair${qs}`);
      const data = await res.json();
      setPair(data?.job_id ? data : null);
    } catch {
      setPair(null);
    } finally {
      setLoading(false);
    }
  }, [activeTag, searchText, activeLanguage]);

  const fetchTags = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/api/tts/tags`);
      const data = await res.json();
      if (Array.isArray(data?.tags)) setAvailableTags(data.tags);
    } catch { /* non-fatal */ }
  }, []);

  const fetchLanguages = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/api/tts/languages`);
      const data = await res.json();
      if (Array.isArray(data?.languages)) setAvailableLanguages(data.languages);
    } catch { /* non-fatal */ }
  }, []);

  useEffect(() => { loadPair(); fetchTags(); fetchLanguages(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, []);

  const setScore = (side: string, metric: string, val: number) =>
    setScores((s) => ({ ...s, [side]: { ...s[side], [metric]: val } }));

  const handleSkip = () => { setReveal(null); loadPair(); };

  const handleTagClick = (tag: string) => {
    if (activeTag === tag) { setActiveTag(""); loadPair(undefined, ""); }
    else { setActiveTag(tag); loadPair(undefined, tag); }
  };

  const handleClearFilters = () => {
    setActiveTag(""); setSearchText(""); setSearchPromptId(""); setActiveLanguage("");
    loadPair(undefined, "", "", "");
  };

  const handleLanguageChange = (lang: string) => {
    setActiveLanguage(lang);
    loadPair(undefined, undefined, undefined, lang);
  };

  const submit = async () => {
    if (!pair || !winner || submitting) return;
    setSubmitting(true); setMsg(""); setVoteAck("");
    // Persist BOTH keys so the Analytics 10-vote gate counts these votes.
    if (typeof window !== "undefined" && ldap) {
      localStorage.setItem("pp_ldap", ldap);
      localStorage.setItem("project_pulse_ldap", ldap);
    }
    try {
      const res = await fetch(`${API_BASE_URL}/api/tts/vote`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          job_id: pair.job_id,
          winner_side: winner,
          scores,
          justification,
          ldap: ldap || "anonymous",
        }),
      });
      const data = await res.json();
      setVoteCount((c) => c + 1);
      // Reveal AI eval + identities after the human vote.
      const ai = await fetch(`${API_BASE_URL}/api/tts/aieval/${pair.job_id}`).then((r) => r.json()).catch(() => null);
      setReveal({ vote: data, ai });
      setMsg("Vote recorded.");
      setVoteAck("Vote recorded.");
      // Pause on the reveal, then auto-advance to the next pair.
      setTimeout(() => loadPair(), 3000);
    } catch (e: any) {
      setMsg(e?.message || "Vote failed");
      setVoteAck("Vote failed…");
    } finally {
      setSubmitting(false);
    }
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
              <input type="text" placeholder="Search scripts..." value={searchText} onChange={(e) => setSearchText(e.target.value)} className="pl-9 pr-4 py-2 bg-white/5 border border-white/10 rounded-xl text-sm text-white font-medium focus:outline-none focus:ring-2 focus:ring-indigo-500/50 focus:bg-white/10 transition-all w-48 placeholder-gray-500" />
            </form>
            {availableTags.length > 0 && (
              <button onClick={() => setShowTagFilter(!showTagFilter)} className={`flex items-center gap-2 px-3 py-2 rounded-xl text-xs font-bold uppercase tracking-widest transition-all border ${activeTag ? "bg-indigo-500/20 border-indigo-500/40 text-indigo-300" : "bg-white/5 border-white/10 text-gray-500 hover:text-white"}`}>
                <Filter className="w-3.5 h-3.5" />
                {activeTag || "Tags"}
                {activeTag && <X className="w-3 h-3 ml-1 cursor-pointer" onClick={(e) => { e.stopPropagation(); handleClearFilters(); }} />}
              </button>
            )}
            <select
              value={activeLanguage}
              onChange={(e) => handleLanguageChange(e.target.value)}
              className={`px-3 py-2 rounded-xl text-xs font-bold uppercase tracking-widest border transition-all focus:outline-none focus:ring-2 focus:ring-indigo-500/50 ${activeLanguage ? "bg-indigo-500/20 border-indigo-500/40 text-indigo-300" : "bg-white/5 border-white/10 text-gray-500 hover:text-white"}`}
            >
              <option value="">All languages</option>
              {availableLanguages.map((code) => (
                <option key={code} value={code}>{code}</option>
              ))}
            </select>
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
            Text-to-Speech Pipeline
          </div>
          <h1 className="text-3xl md:text-4xl font-black text-white tracking-tight leading-tight">
            TTS Studio &mdash;{" "}
            <span className="text-transparent bg-clip-text bg-gradient-to-r from-indigo-400 via-purple-400 to-emerald-400">
              Gemini 3.1 Flash TTS vs ElevenLabs
            </span>
          </h1>
        </section>

        {loading ? (
          <Spinner label="Loading a pair…" />
        ) : !pair ? (
          <div className="py-24 flex flex-col items-center justify-center text-gray-500 gap-4 bg-white/[0.02] border border-white/5 rounded-[40px]">
            <p className="font-light tracking-widest uppercase text-xs">No pairs ready for voting yet</p>
            <button onClick={() => loadPair()} className="px-5 py-2.5 rounded-2xl text-xs font-black uppercase tracking-widest bg-indigo-500/20 border border-indigo-500/40 text-indigo-300 hover:bg-indigo-500/30 transition-all">Refresh</button>
          </div>
        ) : (
          <div className="space-y-8">
            <section className="bg-[#0b0e14] border border-white/10 rounded-[40px] p-8 shadow-3xl space-y-6">
              <div className="flex items-center justify-between gap-3 flex-wrap">
                <div className="flex items-center gap-3">
                  <span className="w-2 h-8 bg-indigo-500 rounded-full"></span>
                  <h2 className="text-xl font-light text-white">Blind A/B Evaluation</h2>
                  {pair.language && <span className="px-2.5 py-1 rounded-full bg-white/5 border border-white/10 text-gray-400 text-[10px] font-black uppercase tracking-widest">{pair.language}</span>}
                </div>
                <button onClick={handleSkip} className="flex items-center gap-2 px-5 py-2.5 bg-red-500/5 border border-red-500/10 rounded-2xl hover:bg-red-500/10 transition-all group">
                  <ChevronRight className="w-4 h-4 text-red-400 group-hover:translate-x-0.5 transition-transform" />
                  <span className="text-xs font-black uppercase tracking-widest text-red-400">Skip</span>
                </button>
              </div>
              <div className="bg-white/[0.02] border border-white/5 rounded-2xl px-5 py-4">
                <p className="text-gray-300 font-light text-sm whitespace-pre-wrap">
                  Script: &ldquo;{pair.text}&rdquo;
                  {pair.style_prompt ? <span className="block text-gray-500 italic mt-1">Style: {pair.style_prompt}</span> : null}
                </p>
                {pair.text && <TranslateButton text={pair.text} />}
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                {(["a", "b"] as const).map((k) => {
                  const side = k.toUpperCase();
                  const variant = pair[`variant_${k}`];
                  return (
                    <div key={side} className="bg-[#06080b] border border-white/5 rounded-3xl p-5 space-y-4">
                      <div className="flex items-center justify-between">
                        <span className="text-sm font-black uppercase tracking-widest text-indigo-300">Clip {side}</span>
                        {reveal?.ai?.side_map?.[side] && <span className="text-[10px] font-mono text-emerald-300">{reveal.ai.side_map[side]}</span>}
                      </div>
                      <audio controls preload="none" src={audioUrl(variant?.url)} className="w-full" />
                      <div className="space-y-3">
                        {METRICS.map((m) => (
                          <div key={m.key}>
                            <div className="flex items-center justify-between mb-1">
                              <span className="text-[10px] font-black uppercase tracking-widest text-gray-500">{m.label}</span>
                              <span className="text-[11px] font-mono text-gray-400">{scores[side]?.[m.key] ?? "—"}</span>
                            </div>
                            <div className="flex gap-1.5">
                              {[1, 2, 3, 4, 5].map((n) => (
                                <button key={n} onClick={() => setScore(side, m.key, n)}
                                  className={`flex-1 py-1.5 rounded-lg text-[11px] font-black border transition-all ${scores[side]?.[m.key] === n ? "bg-indigo-500/30 border-indigo-500/50 text-indigo-200" : "bg-white/5 border-white/10 text-gray-500 hover:text-white"}`}>
                                  {n}
                                </button>
                              ))}
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  );
                })}
              </div>

              <div className="space-y-3">
                <label className="text-[10px] font-black text-gray-500 uppercase tracking-widest px-1">Overall winner</label>
                <div className="flex gap-3">
                  {[{ k: "A", label: "Clip A" }, { k: "tie", label: "Tie" }, { k: "B", label: "Clip B" }].map((o) => (
                    <button key={o.k} onClick={() => setWinner(o.k)}
                      className={`flex-1 py-3 rounded-2xl text-xs font-black uppercase tracking-widest border transition-all ${winner === o.k ? "bg-emerald-500/20 border-emerald-500/40 text-emerald-300" : "bg-white/5 border-white/10 text-gray-400 hover:text-white"}`}>
                      {o.label}
                    </button>
                  ))}
                </div>
              </div>

              <textarea value={justification} onChange={(e) => setJustification(e.target.value)} rows={2} placeholder="Why? (optional)"
                className="w-full bg-[#06080b] border border-white/10 rounded-2xl px-5 py-3 text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-indigo-500/40" />

              <div className="flex flex-wrap items-center gap-3">
                <button onClick={submit} disabled={!winner || submitting || !!reveal}
                  className="flex-1 bg-gradient-to-r from-indigo-500 to-emerald-600 hover:from-indigo-400 hover:to-emerald-500 text-white font-black py-4 rounded-2xl transition-all active:scale-[0.98] disabled:opacity-40 uppercase tracking-widest text-sm">
                  {submitting ? "Submitting…" : reveal ? "Vote recorded" : "Submit Vote"}
                </button>
                <button onClick={() => loadPair()} className="px-5 py-4 rounded-2xl text-xs font-black uppercase tracking-widest bg-white/5 border border-white/10 text-gray-400 hover:text-white transition-all">Next Pair</button>
              </div>
              {msg && <div className="text-xs font-bold text-emerald-300 bg-emerald-500/10 border border-emerald-500/20 rounded-xl px-4 py-2">{msg}</div>}
            </section>

            {reveal && (
              <section className="bg-[#0b0e14] border border-emerald-500/20 rounded-[40px] p-8 shadow-3xl space-y-3">
                <h3 className="text-lg font-light text-white flex items-center gap-3"><span className="w-2 h-7 bg-emerald-500 rounded-full"></span> Reveal</h3>
                <p className="text-sm text-gray-300">Your pick: <span className="font-mono text-emerald-300">{reveal.vote?.winner_model || winner}</span></p>
                {reveal.ai?.ai_eval?.winner_engine && (
                  <p className="text-sm text-gray-300">AI judge ({reveal.ai.ai_eval.model}): <span className="font-mono text-indigo-300">{reveal.ai.ai_eval.winner_engine}</span></p>
                )}
                {reveal.ai?.ai_eval?.justification && <p className="text-xs text-gray-500 italic">{reveal.ai.ai_eval.justification}</p>}
              </section>
            )}
          </div>
        )}
      </main>
    </>
  );
}

function Spinner({ label }: { label: string }) {
  return (
    <div className="py-24 flex flex-col items-center justify-center text-gray-500 gap-4 bg-white/[0.02] border border-white/5 rounded-[40px]">
      <div className="w-10 h-10 rounded-full border-2 border-indigo-500/30 border-t-indigo-500 animate-spin"></div>
      <p className="font-light tracking-widest uppercase text-xs">{label}</p>
    </div>
  );
}
