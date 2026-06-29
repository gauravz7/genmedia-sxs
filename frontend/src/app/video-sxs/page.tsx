"use client";
import { useState, useEffect, useRef } from "react";
import {
  Play, Pause, Volume2, VolumeX, Award, CheckCircle2,
  AlertCircle, Loader2, Zap, ArrowRight, ChevronRight, MessageSquareQuote,
  Search, Filter, X,
} from "lucide-react";
import { API_BASE_URL, formatUrl, maskPid } from "@/lib/api";
import Nav from "@/components/Nav";
import VoteProgress from "@/components/VoteProgress";
import TranslateButton from "@/components/TranslateButton";

// ===================================================================
// Video SxS — RATING-ONLY public arena. Mirrors human-eval voting
// (GET /api/sxs/pair + POST /api/sxs/vote, per-dimension scoring) but
// behind a plain ldap "enter arena" gate, no admin password.
// ===================================================================

const SCORE_MIN = 1;
const SCORE_MAX = 5;
const SCORE_DEFAULT = 3;
const DIMENSIONS = [
  { id: "prompt_adherence", label: "Prompt Adherence", color: "indigo" },
  { id: "visual_quality", label: "Visual Quality", color: "purple" },
  { id: "motion_physics", label: "Motion & Physics", color: "pink" },
  { id: "temporal_consistency", label: "Temporal Consistency", color: "emerald" },
  { id: "audio_visual_sync", label: "Audio-Visual Sync", color: "blue" },
];

interface EvalVariant {
  model_id: string;
  url: string;
}

interface EvaluationPair {
  job_id: string;
  prompt: string;
  categories?: string[];
  ratio?: string;
  reference_images?: string[];
  reference_videos?: string[];
  modality?: string;
  variant_a: EvalVariant;
  variant_b: EvalVariant;
}

export default function VideoSxSArena() {
  const [mounted, setMounted] = useState(false);
  const [ldap, setLdap] = useState("");
  const [ldapInput, setLdapInput] = useState("");

  const [currentEval, setCurrentEval] = useState<EvaluationPair | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [votingStep, setVotingStep] = useState(1);
  const [winner, setWinner] = useState<string | null>(null);
  const [dimScores, setDimScores] = useState<Record<string, number>>({});
  const [justification, setJustification] = useState("");
  const [voteAck, setVoteAck] = useState("");
  const [voteCount, setVoteCount] = useState(0);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const submittingRef = useRef(false);

  // Search & tag filter
  const [searchPromptId, setSearchPromptId] = useState("");
  const [searchText, setSearchText] = useState("");
  const [activeTag, setActiveTag] = useState("");
  const [availableTags, setAvailableTags] = useState<string[]>([]);
  const [showTagFilter, setShowTagFilter] = useState(false);

  useEffect(() => {
    setMounted(true);
    const saved = typeof window !== "undefined" ? (localStorage.getItem("project_pulse_ldap") || localStorage.getItem("pp_ldap")) : "";
    // Auto-enter if an ldap was already provided (don't re-ask across arenas/sessions).
    if (saved) { setLdap(saved); setLdapInput(saved); }
  }, []);

  useEffect(() => {
    if (mounted && ldap) { fetchNewPair(); fetchTags(); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mounted, ldap]);

  const fetchTags = async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/api/tags`);
      const data = await res.json();
      if (data?.status === "success" && Array.isArray(data.tags)) setAvailableTags(data.tags);
    } catch { /* non-fatal */ }
  };

  const fetchNewPair = async (forcePromptId?: string, forceTag?: string, forceSearch?: string) => {
    setIsLoading(true);
    try {
      // `undefined` → fall back to current state; an explicit string (incl. "") overrides.
      const tag = forceTag ?? activeTag;
      const search = forceSearch ?? searchText;
      const params = new URLSearchParams();
      if (forcePromptId) params.set("prompt_id", forcePromptId);
      if (tag) params.set("tag", tag);
      if (search) params.set("search", search);
      const qs = params.toString() ? `?${params.toString()}` : "";
      const res = await fetch(`${API_BASE_URL}/api/sxs/pair${qs}`);
      const data = await res.json();
      if (data.status === "error") {
        setCurrentEval(null);
      } else {
        if (data.reference_images) data.reference_images = data.reference_images.map(formatUrl);
        if (data.variant_a?.url) data.variant_a.url = formatUrl(data.variant_a.url);
        if (data.variant_b?.url) data.variant_b.url = formatUrl(data.variant_b.url);
        setCurrentEval(data);
      }
    } catch (err) {
      console.error("Failed to fetch evaluation pair", err);
      setCurrentEval(null);
    } finally {
      setIsLoading(false);
    }
  };

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

  const resetVotingState = () => {
    setVotingStep(1);
    setWinner(null);
    setDimScores({});
    setJustification("");
  };

  const handleSelectWinner = (side: "a" | "b") => {
    setWinner(side);
    setVotingStep(2);
  };

  const handleScoreChange = (dim: string, score: number) => {
    setDimScores((prev) => ({ ...prev, [dim]: score }));
  };

  const handleNextPair = () => {
    setVoteAck("");
    submittingRef.current = false;
    setIsSubmitting(false);
    resetVotingState();
    fetchNewPair();
  };

  const handleSkip = () => {
    resetVotingState();
    fetchNewPair();
  };

  const handleTagClick = (tag: string) => {
    if (activeTag === tag) {
      setActiveTag("");
      resetVotingState();
      fetchNewPair(undefined, "");
    } else {
      setActiveTag(tag);
      resetVotingState();
      fetchNewPair(undefined, tag);
    }
  };

  const handleClearFilters = () => {
    setActiveTag("");
    setSearchText("");
    setSearchPromptId("");
    resetVotingState();
    fetchNewPair(undefined, "", "");
  };

  const handleSubmitVote = async () => {
    if (!currentEval || !winner || submittingRef.current) return;
    submittingRef.current = true;
    setIsSubmitting(true);
    const winnerModel = winner === "a" ? currentEval.variant_a.model_id : currentEval.variant_b.model_id;
    const loserModel = winner === "a" ? currentEval.variant_b.model_id : currentEval.variant_a.model_id;
    // Persist BOTH keys so the Analytics 10-vote gate counts these votes.
    if (typeof window !== "undefined" && ldap) {
      localStorage.setItem("project_pulse_ldap", ldap);
      localStorage.setItem("pp_ldap", ldap);
    }
    try {
      const voteRes = await fetch(`${API_BASE_URL}/api/sxs/vote`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ job_id: currentEval.job_id, winner_side: winner, winner_model: winnerModel, loser_model: loserModel, scores: dimScores, justification, ldap }),
      });
      if (!voteRes.ok) throw new Error(`Server responded ${voteRes.status}`);
      await voteRes.json().catch(() => ({}));
      setVoteCount((c) => c + 1);
      setVoteAck("✓ Vote registered");
      setTimeout(() => { handleNextPair(); }, 3000);
    } catch (err) {
      console.error("Failed to submit vote", err);
      setVoteAck("Vote failed to register — please try again");
      submittingRef.current = false;
      setIsSubmitting(false);
    }
  };

  if (!mounted) return <div className="min-h-screen bg-[#020408]" />;

  // ---------- LDAP GATE ----------
  if (!ldap) {
    return (
      <div className="min-h-screen bg-[#020408] relative overflow-hidden">
        <Nav active="human-eval" />
        <div className="absolute inset-0 z-0 bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-indigo-900/20 via-slate-950 to-[#020408]"></div>
        <div className="relative z-10 flex items-center justify-center p-6 min-h-[calc(100vh-80px)]">
        <div className="w-full max-w-md bg-[#0b0e14]/80 backdrop-blur-2xl border border-white/10 rounded-[40px] shadow-2xl p-10 lg:p-16 animate-in zoom-in-95 duration-700">
          <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center mb-8 mx-auto shadow-[0_0_30px_rgba(99,102,241,0.4)]">
            <Zap className="w-8 h-8 text-white" />
          </div>
          <h2 className="text-3xl font-black text-white text-center italic tracking-tight mb-2">ACCESS ARENA</h2>
          <p className="text-gray-400 text-center text-sm font-light mb-8">Enter your LDAP to record evaluations.</p>
          <form onSubmit={enterArena}>
            <input type="text" value={ldapInput} onChange={(e) => setLdapInput(e.target.value.toLowerCase())} placeholder="username" autoFocus
              className="w-full bg-[#020408] border border-white/10 rounded-2xl px-6 py-4 text-white placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-indigo-500/50 mb-6 font-mono text-center" />
            <button type="submit" disabled={!ldapInput.trim()} className="w-full bg-white text-[#020408] font-black uppercase tracking-widest py-4 rounded-2xl hover:bg-gray-200 transition-colors disabled:opacity-50">Enter Evaluation</button>
          </form>
        </div>
        </div>
      </div>
    );
  }

  const isPortrait = currentEval?.ratio === "9:16";

  return (
    <div className="min-h-screen bg-[#020408] text-gray-100 font-sans selection:bg-indigo-500/30 overflow-x-hidden">
      <div className="fixed inset-0 -z-10 bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-indigo-900/10 via-slate-950 to-[#020408]"></div>

      <Nav active="human-eval" />

      {voteAck && (
        <div className={`fixed top-24 left-1/2 -translate-x-1/2 z-[120] px-6 py-3 rounded-2xl border shadow-2xl text-sm font-bold flex items-center gap-3 animate-in fade-in slide-in-from-top-4 duration-300 ${voteAck.startsWith("Vote failed") ? "bg-red-500/15 border-red-500/40 text-red-200" : "bg-emerald-500/15 border-emerald-500/40 text-emerald-200"}`}>
          <span>{voteAck.startsWith("Vote failed") ? "⚠️" : "✓"}</span>
          <span>{voteAck}</span>
        </div>
      )}

      {/* Sub-toolbar: search / tag filter (left) + VoteProgress HUD (right) */}
      <div className="w-full border-b border-white/5 bg-[#020408]/60 backdrop-blur-2xl z-40">
        <div className="max-w-screen-2xl mx-auto px-6 py-3 flex items-center justify-between gap-4 flex-wrap">
          <div className="flex items-center gap-3 flex-wrap">
            <form onSubmit={(e) => { e.preventDefault(); resetVotingState(); fetchNewPair(searchPromptId); }} className="relative flex items-center group">
              <Search className="w-4 h-4 text-gray-500 absolute left-3 group-focus-within:text-indigo-400 transition-colors" />
              <input type="text" placeholder="Prompt ID..." value={searchPromptId} onChange={(e) => setSearchPromptId(e.target.value)} className="pl-9 pr-4 py-2 bg-white/5 border border-white/10 rounded-xl text-sm text-white font-medium focus:outline-none focus:ring-2 focus:ring-indigo-500/50 focus:bg-white/10 transition-all w-40 placeholder-gray-500" />
            </form>
            <form onSubmit={(e) => { e.preventDefault(); resetVotingState(); fetchNewPair(undefined, undefined, searchText); }} className="relative flex items-center group">
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
          <div className="border-t border-white/5 bg-[#020408]/80 px-6 py-3">
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

      <main className="max-w-screen-2xl mx-auto px-6 pt-8 pb-20">
        {/* Header */}
        <section className="mb-10 animate-in fade-in slide-in-from-top-4 duration-1000">
          <div className="flex items-center justify-between gap-3 flex-wrap mb-4">
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-indigo-500/10 border border-indigo-500/20 text-indigo-300 text-[10px] font-black uppercase tracking-widest">
              Video Modality
            </div>
            <span className="text-[10px] font-bold text-gray-500 uppercase tracking-widest">@{ldap}</span>
          </div>
          <h1 className="text-xl md:text-2xl font-light text-white leading-[1.3] tracking-tight">
            &ldquo;{currentEval?.prompt || "Loading Scenario..."}&rdquo;
          </h1>
          {currentEval?.prompt && <TranslateButton text={currentEval.prompt} />}
          {currentEval && ((currentEval.reference_images?.length ?? 0) > 0 || (currentEval.reference_videos?.length ?? 0) > 0) && (
            <div className="mt-4">
              <div className="text-[9px] font-black uppercase tracking-widest text-gray-500 mb-2">
                {(currentEval.modality || "").toUpperCase().includes("I2V") ? "Input Image" : "Reference"}
              </div>
              <div className="flex flex-wrap gap-3">
                {currentEval.reference_images?.map((url, i) => (
                  <img key={i} src={url} alt={`reference ${i + 1}`} className="w-28 h-28 object-cover rounded-2xl border border-white/10 bg-black/50" />
                ))}
                {currentEval.reference_videos?.map((url, i) => (
                  <video key={`v${i}`} src={url} controls muted className="w-28 h-28 object-cover rounded-2xl border border-white/10 bg-black/50" />
                ))}
              </div>
            </div>
          )}
          {currentEval && (
            <div className="flex items-center gap-4 text-sm text-gray-500 italic font-light mt-3">
              <span className="font-mono">PID: {maskPid(currentEval.job_id)}</span>
              <span className="w-1 h-1 rounded-full bg-gray-800"></span>
              <span>{currentEval.variant_a.model_id} vs {currentEval.variant_b.model_id}</span>
            </div>
          )}
        </section>

        {/* Play Controls */}
        <div className="flex justify-center mb-8 gap-4">
          <button onClick={() => { document.querySelectorAll("video").forEach((v) => { v.currentTime = 0; v.play(); }); }} className="flex items-center gap-3 px-8 py-4 bg-white/5 border border-white/10 rounded-2xl hover:bg-white/10 transition-all group">
            <div className="p-2 bg-indigo-500 rounded-lg group-hover:scale-110 transition-transform"><Play className="w-4 h-4 text-white fill-white" /></div>
            <span className="text-sm font-bold uppercase tracking-widest text-indigo-400">Play Both</span>
          </button>
          <button onClick={handleSkip} className="flex items-center gap-3 px-8 py-4 bg-red-500/5 border border-red-500/10 rounded-2xl hover:bg-red-500/10 transition-all group">
            <div className="p-2 bg-red-500/20 rounded-lg group-hover:scale-110 transition-transform"><ChevronRight className="w-4 h-4 text-red-400" /></div>
            <span className="text-sm font-bold uppercase tracking-widest text-red-400">Skip</span>
          </button>
        </div>

        {/* Evaluation Matrix */}
        <section className={`grid gap-10 mb-12 ${isPortrait ? "grid-cols-1 md:grid-cols-2 max-w-4xl mx-auto" : "grid-cols-1 lg:grid-cols-2"}`}>
          {isLoading ? (
            <div className={`${isPortrait ? "md:col-span-2" : "lg:col-span-2"} py-40 flex flex-col items-center justify-center text-gray-500 gap-4`}>
              <Loader2 className="w-12 h-12 animate-spin text-indigo-500" />
              <p className="font-light tracking-widest uppercase text-xs">Fetching Bench Scenarios...</p>
            </div>
          ) : !currentEval ? (
            <div className={`${isPortrait ? "md:col-span-2" : "lg:col-span-2"} py-40 flex flex-col items-center justify-center text-gray-500 gap-4`}>
              <AlertCircle className="w-12 h-12 text-amber-500" />
              <p className="font-light tracking-widest uppercase text-xs">No active scenarios found.</p>
            </div>
          ) : (
            <>
              <VideoSlot label="Variant A" side="a" url={currentEval.variant_a.url} isSelected={winner === "a"} onSelect={() => handleSelectWinner("a")} step={votingStep} isPortrait={isPortrait} />
              <VideoSlot label="Variant B" side="b" url={currentEval.variant_b.url} isSelected={winner === "b"} onSelect={() => handleSelectWinner("b")} step={votingStep} isPortrait={isPortrait} />
            </>
          )}
        </section>

        {/* Voting & Rating Flow */}
        {!isLoading && currentEval && (
          <section className="relative">
            {votingStep === 1 ? (
              <div className="text-center py-10 bg-white/[0.02] border border-white/5 rounded-[40px] animate-in fade-in zoom-in-95 duration-500">
                <h3 className="text-2xl font-light text-gray-300 mb-6">Which model captures the prompt best?</h3>
                <p className="text-gray-500 text-sm max-w-md mx-auto mb-8 font-light italic">Selection is finalized after detailed scoring in the next step.</p>
                <div className="flex items-center justify-center gap-6">
                  <PickButton side="A" onClick={() => handleSelectWinner("a")} />
                  <div className="w-[1px] h-12 bg-white/10"></div>
                  <PickButton side="B" onClick={() => handleSelectWinner("b")} />
                </div>
              </div>
            ) : (
              <div className="animate-in slide-in-from-bottom-8 duration-700">
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-10 items-start">
                  {/* Rating Sliders */}
                  <div className="bg-[#0b0e14] border border-white/5 rounded-[40px] p-10 shadow-3xl">
                    <div className="flex items-center justify-between mb-10">
                      <div className="flex items-center gap-3">
                        <div className="w-2 h-8 bg-indigo-500 rounded-full"></div>
                        <h3 className="text-2xl font-light text-white">Dimension Scoring</h3>
                      </div>
                      <div className="text-[10px] font-black uppercase tracking-widest text-indigo-400 bg-indigo-500/5 px-3 py-1.5 rounded-full border border-indigo-500/10">
                        {winner === "a" ? "Variant A" : "Variant B"}
                      </div>
                    </div>
                    <div className="space-y-10">
                      {DIMENSIONS.map((dim) => (
                        <div key={dim.id} className="space-y-4">
                          <div className="flex justify-between items-end">
                            <label className="text-sm font-bold text-gray-300 flex items-center gap-2">
                              <span className={`w-1.5 h-1.5 rounded-full bg-${dim.color}-500`}></span>
                              {dim.label}
                            </label>
                            <span className="text-lg font-black text-white font-mono">{dimScores[dim.id] || SCORE_DEFAULT}<span className="text-gray-600 text-sm"> / {SCORE_MAX}</span></span>
                          </div>
                          <input type="range" min={SCORE_MIN} max={SCORE_MAX} value={dimScores[dim.id] || SCORE_DEFAULT} onChange={(e) => handleScoreChange(dim.id, parseInt(e.target.value))} className="w-full h-1.5 bg-white/5 rounded-lg appearance-none cursor-pointer accent-indigo-500" />
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* Justification & Submit */}
                  <div className="space-y-8">
                    <div className="bg-[#0b0e14] border border-white/5 rounded-[40px] p-10 shadow-3xl">
                      <div className="flex items-center gap-3 mb-8">
                        <MessageSquareQuote className="w-6 h-6 text-indigo-400" />
                        <h3 className="text-xl font-light text-white">Why did you pick this?</h3>
                      </div>
                      <textarea value={justification} onChange={(e) => setJustification(e.target.value)} placeholder="Provide specialized feedback on motion flow, text adherence, or specific model artifacts noticed..." className="w-full bg-[#020408] border border-white/10 rounded-3xl p-6 text-gray-300 placeholder-gray-700 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500/40 transition-all resize-none h-[220px] font-light italic leading-relaxed" />
                    </div>
                    <button onClick={handleSubmitVote} disabled={isSubmitting} className="w-full bg-gradient-to-r from-indigo-500 via-purple-600 to-pink-600 hover:from-indigo-400 hover:to-pink-500 disabled:opacity-50 disabled:cursor-not-allowed text-white font-black py-6 rounded-[30px] shadow-[0_20px_50px_rgba(99,102,241,0.3)] transition-all flex items-center justify-center gap-4 group active:scale-[0.98] text-xl">
                      {isSubmitting ? <>Registering Vote… <Loader2 className="w-6 h-6 animate-spin" /></> : <>Deploy Evaluation <ArrowRight className="w-6 h-6 group-hover:translate-x-2 transition-transform" /></>}
                    </button>
                    <button onClick={() => setVotingStep(1)} className="w-full py-4 text-xs font-bold text-gray-500 uppercase tracking-[0.3em] hover:text-gray-300 transition-colors">
                      &larr; Re-pick Winner
                    </button>
                  </div>
                </div>
              </div>
            )}
          </section>
        )}
      </main>
    </div>
  );
}

function VideoSlot({ label, side, url, isSelected, onSelect, step, isPortrait = false }: { label: string; side: string; url: string; isSelected: boolean; onSelect: () => void; step: number; isPortrait?: boolean }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [isMuted, setIsMuted] = useState(true);
  const [retryCount, setRetryCount] = useState(0);
  const [hasError, setHasError] = useState(false);

  useEffect(() => { setRetryCount(0); setHasError(false); }, [url]);

  const videoUrl = retryCount > 0 ? `${url}${url.includes("?") ? "&" : "?"}retry=${retryCount}` : url;

  const togglePlay = () => {
    if (!videoRef.current) return;
    if (isPlaying) videoRef.current.pause(); else videoRef.current.play();
    setIsPlaying(!isPlaying);
  };

  return (
    <div className={`relative group/video transition-all duration-700 ${isSelected ? "scale-[1.02]" : step === 2 ? "grayscale opacity-40 blur-[2px]" : ""}`} onClick={onSelect}>
      <div className={`absolute -inset-1 rounded-[40px] blur-2xl opacity-0 group-hover/video:opacity-20 transition-all duration-1000 ${side === "a" ? "bg-indigo-500" : "bg-purple-500"} ${isSelected ? "opacity-40" : ""}`}></div>

      <div className={`relative ${isPortrait ? "aspect-[9/16] max-h-[70vh]" : "aspect-video"} rounded-[36px] overflow-hidden border-2 transition-all duration-500 ${isSelected ? "border-indigo-500 shadow-3xl" : "border-white/10 bg-[#0d1017]"}`}>
        <video
          ref={videoRef}
          src={videoUrl}
          loop
          muted={isMuted}
          className={`w-full h-full ${isPortrait ? "object-contain" : "object-cover"} ${hasError ? "hidden" : ""}`}
          onPlay={() => setIsPlaying(true)}
          onPause={() => setIsPlaying(false)}
          onError={() => {
            if (retryCount < 1) { setRetryCount(1); }
            else { setHasError(true); }
          }}
        />

        {hasError && (
          <div className="absolute inset-0 flex flex-col items-center justify-center bg-[#0d1017] p-8 text-center">
            <AlertCircle className="w-12 h-12 text-red-500/50 mb-4" />
            <h4 className="text-sm font-black uppercase tracking-widest text-red-400/80 mb-2">Video Unavailable</h4>
            <p className="text-[10px] text-gray-500 font-light italic">This variant failed to load. Use &ldquo;Skip&rdquo;.</p>
          </div>
        )}

        <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/90 via-black/40 to-transparent p-8 flex items-end justify-between opacity-0 group-hover/video:opacity-100 transition-opacity duration-500">
          <div className="flex items-center gap-4">
            <button onClick={(e) => { e.stopPropagation(); togglePlay(); }} className="w-12 h-12 rounded-full bg-white/10 backdrop-blur-3xl flex items-center justify-center hover:bg-white/20 transition-all">
              {isPlaying ? <Pause className="w-5 h-5 text-white" /> : <Play className="w-5 h-5 text-white translate-x-0.5" />}
            </button>
            <button onClick={(e) => { e.stopPropagation(); setIsMuted(!isMuted); }} className={`w-12 h-12 rounded-full backdrop-blur-3xl flex items-center justify-center transition-all ${isMuted ? "bg-white/10 hover:bg-white/20" : "bg-indigo-500/40 border border-indigo-500/50"}`}>
              {isMuted ? <VolumeX className="w-5 h-5 text-gray-400" /> : <Volume2 className="w-5 h-5 text-white" />}
            </button>
            <div className="flex flex-col">
              <span className="text-[10px] font-black uppercase tracking-widest text-indigo-400">{label}</span>
              <span className="text-[8px] font-bold text-gray-500">BLIND EVALUATION</span>
            </div>
          </div>
          <Award className={`w-8 h-8 ${isSelected ? "text-indigo-400" : "text-white/20"}`} />
        </div>

        {isSelected && (
          <div className="absolute top-6 left-6 px-4 py-2 bg-indigo-500 text-white rounded-full font-black text-[10px] uppercase tracking-widest shadow-3xl animate-in zoom-in-50 duration-500 flex items-center gap-2">
            <CheckCircle2 className="w-3.5 h-3.5" /> Selected Winner
          </div>
        )}
      </div>
    </div>
  );
}

function PickButton({ side, onClick }: { side: string; onClick: () => void }) {
  return (
    <button onClick={onClick} className="group relative px-12 py-5 rounded-2xl overflow-hidden transition-all active:scale-95">
      <div className={`absolute inset-0 transition-all opacity-10 group-hover:opacity-20 ${side === "A" ? "bg-indigo-500" : "bg-purple-500"}`}></div>
      <div className="absolute inset-0 border border-white/10 group-hover:border-white/30 rounded-2xl transition-all"></div>
      <span className="relative text-3xl font-black text-white italic tracking-tighter group-hover:scale-110 transition-transform block">Variant {side}</span>
    </button>
  );
}
