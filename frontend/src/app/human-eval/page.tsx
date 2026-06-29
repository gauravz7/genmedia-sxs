'use client';
import { useState, useEffect, useRef } from 'react';
import {
  Crown, ChevronRight, BarChart3, Loader2, Zap,
  UserCircle2, Cpu, Sparkles, Tag, Search, X, Filter, Target
} from 'lucide-react';
import { API_BASE_URL, formatUrl, maskPid } from '@/lib/api';
import Nav from '@/components/Nav';

// Human-eval rubric === AI Core-5 rubric (same keys, labels, and 1–5 scale)
// so human vs AI scores are directly comparable per axis.
const METRICS = [
  { key: 'prompt_adherence', label: 'Prompt Adherence' },
  { key: 'visual_quality', label: 'Visual Quality' },
  { key: 'motion_physics', label: 'Motion & Physics' },
  { key: 'temporal_consistency', label: 'Temporal Consistency' },
  { key: 'audio_visual_sync', label: 'Audio-Visual Sync' },
];

const prettyModel = (key: string = "") => {
  const k = key.toLowerCase();
  if (k.includes('omni')) return 'Gemini Omni';
  if (k.includes('seedance') && k.includes('fast')) return 'Seedance 2.0 Fast';
  if (k.includes('seedance') || k.includes('doubao')) return 'Seedance 2.0';
  if (k.includes('veo')) return 'Veo';
  if (k.includes('kling')) return 'Kling';
  return key;
};

interface EvalVariant {
  model_id: string;
  url: string;
}

interface EvaluationPair {
  job_id: string;
  prompt: string;
  categories?: string[];
  ratio?: string;
  start_image_url?: string;
  end_image_url?: string;
  reference_image_url?: string;
  reference_images?: string[];
  reference_videos?: string[];
  modality?: string;
  variant_a: EvalVariant;
  variant_b: EvalVariant;
}

export default function HumanEval() {
  const [isMounted, setIsMounted] = useState(false);
  const [votesCount, setVotesCount] = useState(0);
  const [currentEval, setCurrentEval] = useState<EvaluationPair | null>(null);
  const [winner, setWinner] = useState<'a' | 'tie' | 'b' | null>(null);
  const [scores, setScores] = useState<Record<string, Record<string, number>>>({ A: {}, B: {} });
  const [justification, setJustification] = useState("");
  const [expandedImage, setExpandedImage] = useState<string | null>(null);
  const [history, setHistory] = useState<any[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  // Auth
  const [ldap, setLdap] = useState("");
  const [ldapInput, setLdapInput] = useState("");
  const [globalLeaderboard, setGlobalLeaderboard] = useState<any[]>([]);

  // Search & Filter
  const [searchPromptId, setSearchPromptId] = useState("");
  const [searchText, setSearchText] = useState("");
  const [activeTag, setActiveTag] = useState("");
  const [availableTags, setAvailableTags] = useState<string[]>([]);
  const [showTagFilter, setShowTagFilter] = useState(false);
  const [veoAnchored] = useState(false);

  // Vote acknowledgement + duplicate-vote guard
  const [voteAck, setVoteAck] = useState<string>("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const submittingRef = useRef(false); // synchronous re-entry guard (state lags across rapid clicks)

  useEffect(() => {
    setIsMounted(true);
    fetchNewPair();
    fetchTags();
    const savedVotes = localStorage.getItem('project_pulse_votes');
    const savedHistory = localStorage.getItem('project_pulse_history');
    const savedLdap = localStorage.getItem('project_pulse_ldap') || localStorage.getItem('pp_ldap');
    if (savedVotes) setVotesCount(parseInt(savedVotes));
    if (savedHistory) setHistory(JSON.parse(savedHistory));
    if (savedLdap) setLdap(savedLdap);

    fetch(`${API_BASE_URL}/api/sxs/leaderboard/users`)
      .then(res => res.json())
      .then(data => {
        if (data?.status === "success" && data.leaderboard) {
          setGlobalLeaderboard(data.leaderboard);
        }
      })
      .catch(err => console.error("Error fetching leaderboard", err));
  }, []);

  const fetchTags = async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/api/tags`);
      const data = await res.json();
      if (data?.status === "success") {
        setAvailableTags(data.tags);
      }
    } catch (err) {
      console.error("Failed to fetch tags", err);
    }
  };

  const fetchNewPair = async (forcePromptId?: string, forceTag?: string, forceSearch?: string) => {
    setIsLoading(true);
    setWinner(null);
    setScores({ A: {}, B: {} });
    setJustification("");
    try {
      const params = new URLSearchParams();
      if (forcePromptId) params.set("prompt_id", forcePromptId);
      if (forceTag || activeTag) params.set("tag", forceTag || activeTag);
      if (forceSearch || searchText) params.set("search", forceSearch || searchText);
      if (veoAnchored) params.set("veo_anchored", "true");
      const qs = params.toString() ? `?${params.toString()}` : '';

      // SxS test branch: human eval pulls from the isolated sxs_jobs DB.
      const res = await fetch(`${API_BASE_URL}/api/sxs/pair${qs}`);
      const data = await res.json();
      if (data.status === "error") {
        setCurrentEval(null);
      } else {
        if (data.start_image_url) data.start_image_url = formatUrl(data.start_image_url);
        if (data.end_image_url) data.end_image_url = formatUrl(data.end_image_url);
        if (data.reference_image_url) data.reference_image_url = formatUrl(data.reference_image_url);
        if (data.reference_images) data.reference_images = data.reference_images.map(formatUrl);
        if (data.reference_videos) data.reference_videos = data.reference_videos.map(formatUrl);
        if (data.variant_a?.url) data.variant_a.url = formatUrl(data.variant_a.url);
        if (data.variant_b?.url) data.variant_b.url = formatUrl(data.variant_b.url);
        // Fallback: if the pair lacks input images (e.g. backend not yet
        // restarted), fetch them from the job detail so I2V/R2V inputs show.
        if ((!data.reference_images || data.reference_images.length === 0) && data.job_id) {
          try {
            const jr = await fetch(`${API_BASE_URL}/api/sxs/jobs/${encodeURIComponent(data.job_id)}`);
            if (jr.ok) {
              const jd = await jr.json();
              if (jd.reference_images?.length) data.reference_images = jd.reference_images.map(formatUrl);
              if (jd.reference_videos?.length) data.reference_videos = jd.reference_videos.map(formatUrl);
            }
          } catch { /* non-fatal */ }
        }
        setCurrentEval(data);
      }
    } catch (err) {
      console.error("Failed to fetch evaluation pair", err);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    if (isMounted) {
      localStorage.setItem('project_pulse_votes', votesCount.toString());
      localStorage.setItem('project_pulse_history', JSON.stringify(history));
    }
  }, [votesCount, history, isMounted]);

  useEffect(() => {
    if (ldap) {
      // Persist so the Analytics 10-vote gate (and other pages) can identify the voter.
      if (typeof window !== "undefined") {
        localStorage.setItem('project_pulse_ldap', ldap);
        localStorage.setItem('pp_ldap', ldap);
      }
      fetch(`${API_BASE_URL}/api/sxs/stats?ldap=${ldap}`)
        .then(res => res.json())
        .then(data => {
          if (data?.user) setVotesCount(data.user.total_evals || 0);
        })
        .catch(err => console.error(err));
    }
  }, [ldap]);

  if (!isMounted) return <div className="min-h-screen bg-[#020408]" />;

  // ---------- LOGIN ----------
  if (!ldap) {
    return (
      <div className="min-h-screen bg-[#020408] flex items-center justify-center p-6 relative overflow-hidden">
        <div className="absolute inset-0 z-0 bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-indigo-900/20 via-slate-950 to-[#020408]"></div>
        <div className="relative z-10 w-full max-w-5xl flex border border-white/10 rounded-[40px] shadow-2xl overflow-hidden animate-in zoom-in-95 duration-700 bg-[#0b0e14]/80 backdrop-blur-2xl">
          <div className="w-full md:w-1/2 p-10 lg:p-16 flex flex-col justify-center border-r border-white/10">
            <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center mb-8 mx-auto shadow-[0_0_30px_rgba(99,102,241,0.4)]">
              <Zap className="w-8 h-8 text-white" />
            </div>
            <h2 className="text-3xl font-black text-white text-center italic tracking-tight mb-2">ACCESS ARENA</h2>
            <p className="text-gray-400 text-center text-sm font-light mb-8">Enter your LDAP to record evaluations.</p>
            <form onSubmit={(e) => { e.preventDefault(); if (ldapInput.trim()) setLdap(ldapInput.trim()); }}>
              <input type="text" value={ldapInput} onChange={(e) => setLdapInput(e.target.value.toLowerCase())} placeholder="username" className="w-full bg-[#020408] border border-white/10 rounded-2xl px-6 py-4 text-white placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-indigo-500/50 mb-6 font-mono text-center" autoFocus />
              <button type="submit" disabled={!ldapInput.trim()} className="w-full bg-white text-[#020408] font-black uppercase tracking-widest py-4 rounded-2xl hover:bg-gray-200 transition-colors disabled:opacity-50">Enter Evaluation</button>
            </form>
          </div>
          <div className="hidden md:flex flex-col w-1/2 bg-black/40 p-10 lg:p-16">
            <h3 className="text-2xl font-bold text-white flex items-center gap-3 mb-8"><Crown className="w-6 h-6 text-yellow-400" /> Top Evaluators</h3>
            <div className="space-y-4">
              {globalLeaderboard.length > 0 ? globalLeaderboard.map((user, idx) => (
                <div key={user.ldap} className="flex items-center justify-between p-4 rounded-xl bg-white/[0.03] border border-white/5 hover:bg-white/5 transition-colors">
                  <div className="flex items-center gap-4">
                    <span className={`font-black text-lg ${idx === 0 ? 'text-yellow-400' : idx === 1 ? 'text-gray-300' : idx === 2 ? 'text-amber-600' : 'text-gray-600'}`}>#{idx + 1}</span>
                    <span className="font-mono text-indigo-300">{user.ldap}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="font-bold text-white">{user.count}</span>
                    <span className="text-xs text-gray-500 uppercase">votes</span>
                  </div>
                </div>
              )) : (
                <div className="text-center py-10 text-gray-500 text-sm flex items-center justify-center gap-2">
                  <Loader2 className="w-4 h-4 animate-spin text-gray-400" /> Fetching Leaderboard...
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    );
  }

  // ---------- HANDLERS ----------
  const setScore = (side: string, metric: string, val: number) =>
    setScores((s) => ({ ...s, [side]: { ...s[side], [metric]: val } }));

  const handleSubmitVote = async () => {
    // Guard against duplicate submissions (double-click / re-entry). The ref is
    // set synchronously so rapid clicks in the same tick can't slip through
    // before React re-renders the disabled state.
    if (!currentEval || !winner || submittingRef.current) return;
    submittingRef.current = true;
    setIsSubmitting(true);

    const winnerModel = winner === 'b' ? currentEval.variant_b.model_id : currentEval.variant_a.model_id;
    const loserModel = winner === 'b' ? currentEval.variant_a.model_id : currentEval.variant_b.model_id;
    // `scores` stays a FLAT {metric:int} map for analytics compatibility:
    // the winner side's metric map (tie → side A).
    const flatScores = winner === 'b' ? scores.B : scores.A;

    try {
      const voteRes = await fetch(`${API_BASE_URL}/api/sxs/vote`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          job_id: currentEval.job_id,
          winner_side: winner,
          winner_model: winnerModel,
          loser_model: loserModel,
          scores: flatScores,
          scores_a: scores.A,
          scores_b: scores.B,
          justification,
          ldap,
        }),
      });
      if (!voteRes.ok) throw new Error(`Server responded ${voteRes.status}`);
      await voteRes.json().catch(() => ({}));
      // Reveal the picked model name, then auto-advance to the next pair in ~1s.
      setVoteAck(`✓ Vote registered — you picked ${prettyModel(winnerModel)}`);
      setHistory([{ prompt: currentEval.prompt, winner, scores, justification, modelA: currentEval.variant_a.model_id, modelB: currentEval.variant_b.model_id }, ...history]);
      setVotesCount(prev => prev + 1);
      setTimeout(() => { handleNextPair(); }, 1000);
    } catch (err) {
      console.error("Failed to submit vote", err);
      setVoteAck("Vote failed to register — please try again");
      submittingRef.current = false;
      setIsSubmitting(false); // allow retry on failure
    }
  };

  const handleNextPair = () => {
    setVoteAck("");
    submittingRef.current = false;
    setIsSubmitting(false);
    fetchNewPair();
  };

  const handleSkip = () => {
    fetchNewPair();
  };

  const handleTagClick = (tag: string) => {
    if (activeTag === tag) {
      setActiveTag("");
      fetchNewPair(undefined, "");
    } else {
      setActiveTag(tag);
      fetchNewPair(undefined, tag);
    }
  };

  const handleClearFilters = () => {
    setActiveTag("");
    setSearchText("");
    setSearchPromptId("");
    fetchNewPair();
  };

  return (
    <div className="min-h-screen bg-[#020408] text-gray-100 font-sans selection:bg-indigo-500/30 overflow-x-hidden">
      <div className="fixed inset-0 -z-10 bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-indigo-900/10 via-slate-950 to-[#020408]"></div>

      <Nav active="human-eval" />

      {/* Vote acknowledgement toast */}
      {voteAck && (
        <div className={`fixed top-24 left-1/2 -translate-x-1/2 z-[120] px-6 py-3 rounded-2xl border shadow-2xl text-sm font-bold flex items-center gap-3 animate-in fade-in slide-in-from-top-4 duration-300 ${voteAck.startsWith("Vote failed") ? "bg-red-500/15 border-red-500/40 text-red-200" : "bg-emerald-500/15 border-emerald-500/40 text-emerald-200"}`}>
          <span>{voteAck.startsWith("Vote failed") ? "⚠️" : "✓"}</span>
          <span>{voteAck}</span>
        </div>
      )}

      {/* Expanded Image Overlay */}
      {expandedImage && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-black/90 backdrop-blur-sm cursor-zoom-out animate-in fade-in duration-300" onClick={() => setExpandedImage(null)}>
          <img src={expandedImage} className="max-w-full max-h-full rounded-2xl shadow-2xl border border-white/10" alt="Expanded view" />
        </div>
      )}

      {/* Toolbar (search / filter / progress) */}
      <div className="w-full border-b border-white/5 bg-[#020408]/60 backdrop-blur-2xl z-40">
        <div className="max-w-screen-2xl mx-auto px-6 py-3 flex items-center justify-between gap-4 flex-wrap">
          <div className="flex items-center gap-3 flex-wrap">
            {/* Search by Prompt ID */}
            <form onSubmit={(e) => { e.preventDefault(); fetchNewPair(searchPromptId); }} className="relative flex items-center group">
              <Search className="w-4 h-4 text-gray-500 absolute left-3 group-focus-within:text-indigo-400 transition-colors" />
              <input type="text" placeholder="Prompt ID..." value={searchPromptId} onChange={(e) => setSearchPromptId(e.target.value)} className="pl-9 pr-4 py-2 bg-white/5 border border-white/10 rounded-xl text-sm text-white font-medium focus:outline-none focus:ring-2 focus:ring-indigo-500/50 focus:bg-white/10 transition-all w-40 placeholder-gray-500" />
            </form>

            {/* Search by Prompt Text */}
            <form onSubmit={(e) => { e.preventDefault(); fetchNewPair(undefined, undefined, searchText); }} className="relative flex items-center group">
              <Search className="w-4 h-4 text-gray-500 absolute left-3 group-focus-within:text-indigo-400 transition-colors" />
              <input type="text" placeholder="Search prompts..." value={searchText} onChange={(e) => setSearchText(e.target.value)} className="pl-9 pr-4 py-2 bg-white/5 border border-white/10 rounded-xl text-sm text-white font-medium focus:outline-none focus:ring-2 focus:ring-indigo-500/50 focus:bg-white/10 transition-all w-48 placeholder-gray-500" />
            </form>

            {/* Tag Filter Toggle */}
            <button onClick={() => setShowTagFilter(!showTagFilter)} className={`flex items-center gap-2 px-3 py-2 rounded-xl text-xs font-bold uppercase tracking-widest transition-all border ${activeTag ? 'bg-indigo-500/20 border-indigo-500/40 text-indigo-300' : 'bg-white/5 border-white/10 text-gray-500 hover:text-white'}`}>
              <Filter className="w-3.5 h-3.5" />
              {activeTag || 'Tags'}
              {activeTag && <X className="w-3 h-3 ml-1 cursor-pointer" onClick={(e) => { e.stopPropagation(); handleClearFilters(); }} />}
            </button>
          </div>

          <div className="flex items-center gap-3">
            <div className="flex flex-col items-end mr-1">
              <span className="text-[10px] font-bold text-gray-500 uppercase tracking-widest">@{ldap}</span>
              <span className="text-xs font-black text-indigo-400 font-mono tracking-tighter">{votesCount} VOTES</span>
            </div>
            <div className="w-48 h-2 bg-white/5 rounded-full overflow-hidden border border-white/10 shadow-inner">
              <div className="h-full bg-gradient-to-r from-indigo-500 via-purple-500 to-pink-500 transition-all duration-1000 ease-out shadow-[0_0_10px_rgba(168,85,247,0.5)]" style={{ width: `${Math.min((votesCount / 10) * 100, 100)}%` }}></div>
            </div>
            {votesCount >= 10 ? (
              <a href="/analytics" className="px-4 py-2 ml-2 rounded-xl bg-indigo-500/20 border border-indigo-500/40 flex items-center gap-2 hover:bg-indigo-500/40 transition-all font-bold text-xs uppercase text-indigo-300 shadow-[0_0_15px_rgba(99,102,241,0.3)]">
                <BarChart3 className="w-4 h-4 text-indigo-400" /> Analytics
              </a>
            ) : (
              <div className="w-8 h-8 rounded-full bg-white/5 border border-white/10 flex items-center justify-center opacity-50">
                <Crown className="w-4 h-4 text-gray-500" />
              </div>
            )}
          </div>
        </div>

        {/* Tag Filter Bar */}
        {showTagFilter && availableTags.length > 0 && (
          <div className="border-t border-white/5 bg-[#020408]/80 px-6 py-3">
            <div className="max-w-screen-2xl mx-auto flex flex-wrap gap-2">
              {availableTags.map(tag => (
                <button key={tag} onClick={() => handleTagClick(tag)} className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all border ${activeTag === tag ? 'bg-indigo-500 text-white border-indigo-500 shadow-lg' : 'bg-white/5 border-white/10 text-gray-400 hover:text-white hover:border-white/20'}`}>
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

        {/* Scenario Header */}
        <section className="mb-8 animate-in fade-in slide-in-from-top-4 duration-1000">
          <div className="flex flex-col lg:flex-row items-start gap-8">
            {currentEval && (
              <div className="flex flex-wrap gap-4 shrink-0">
                {currentEval.start_image_url && <ScenarioReferenceImage url={currentEval.start_image_url} label="Start Frame" onClick={() => setExpandedImage(currentEval.start_image_url ?? null)} />}
                {currentEval.end_image_url && <ScenarioReferenceImage url={currentEval.end_image_url} label="End Frame" onClick={() => setExpandedImage(currentEval.end_image_url ?? null)} />}
                {currentEval.reference_image_url && !currentEval.reference_images && <ScenarioReferenceImage url={currentEval.reference_image_url} label="Ref Image" onClick={() => setExpandedImage(currentEval.reference_image_url ?? null)} />}
                {currentEval.reference_images?.map((url, i) => (
                  <ScenarioReferenceImage key={i} url={url} label={(currentEval.modality || '').toUpperCase().includes('I2V') ? (i === 0 ? 'Input Image' : `Ref ${i + 1}`) : `Ref ${i + 1}`} onClick={() => setExpandedImage(url ?? null)} />
                ))}
                {currentEval.reference_videos?.map((url, i) => (
                  <div key={`v${i}`} className="shrink-0">
                    <div className="text-[9px] font-black uppercase tracking-widest text-gray-500 mb-1 ml-1">Source Video {i + 1}</div>
                    <video src={url} controls muted className="w-32 h-32 object-cover rounded-2xl border border-white/10 bg-black/50" />
                  </div>
                ))}
              </div>
            )}

            <div className="flex-1 space-y-4">
              <div className="flex flex-wrap gap-2">
                <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-indigo-500/10 border border-indigo-500/20 text-indigo-400 text-[10px] font-black uppercase tracking-widest">
                  <Sparkles className="w-3 h-3" /> Expert Scrutiny
                </div>
                {currentEval?.ratio && currentEval.ratio !== "16:9" && (
                  <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-purple-500/10 border border-purple-500/20 text-purple-400 text-[10px] font-black uppercase tracking-widest">
                    {currentEval.ratio}
                  </div>
                )}
                {currentEval?.categories?.map((cat) => (
                  <button key={cat} onClick={() => handleTagClick(cat)} className={`inline-flex items-center gap-2 px-3 py-1 rounded-full text-[10px] font-black uppercase tracking-widest cursor-pointer transition-all ${activeTag === cat ? 'bg-indigo-500 text-white border border-indigo-500' : 'bg-indigo-500/10 border border-indigo-500/20 text-indigo-400 hover:bg-indigo-500/20'}`}>
                    <Tag className="w-3 h-3" /> {cat}
                  </button>
                ))}
              </div>

              <h1 className="text-xl md:text-2xl font-light text-white leading-[1.3] tracking-tight">
                &ldquo;{currentEval?.prompt || "Loading Scenario..."}&rdquo;
              </h1>
              {currentEval?.prompt && <TranslateButton text={currentEval.prompt} />}
              <div className="flex items-center gap-4 text-sm text-gray-500 italic font-light">
                <span className="flex items-center gap-2 font-mono"><UserCircle2 className="w-4 h-4" /> {currentEval?.job_id ? `PID: ${maskPid(currentEval.job_id)}` : "Expert Bench"}</span>
                <span className="w-1 h-1 rounded-full bg-gray-800"></span>
                <span className="flex items-center gap-2"><Cpu className="w-4 h-4" /> Blind A/B</span>
              </div>
            </div>
          </div>
        </section>

        {isLoading ? (
          <Spinner label="Fetching Bench Scenarios…" />
        ) : !currentEval ? (
          <div className="py-24 flex flex-col items-center justify-center text-gray-500 gap-4 bg-white/[0.02] border border-white/5 rounded-[40px]">
            <p className="font-light tracking-widest uppercase text-xs">No active scenarios found. {activeTag || searchText ? 'Try clearing your filters.' : 'Check Admin Console.'}</p>
            {(activeTag || searchText) ? (
              <button onClick={handleClearFilters} className="px-5 py-2.5 rounded-2xl text-xs font-black uppercase tracking-widest bg-indigo-500/20 border border-indigo-500/40 text-indigo-300 hover:bg-indigo-500/30 transition-all">Clear Filters</button>
            ) : (
              <button onClick={() => fetchNewPair()} className="px-5 py-2.5 rounded-2xl text-xs font-black uppercase tracking-widest bg-indigo-500/20 border border-indigo-500/40 text-indigo-300 hover:bg-indigo-500/30 transition-all">Refresh</button>
            )}
          </div>
        ) : (
          <div className="space-y-8">
            <section className="bg-[#0b0e14] border border-white/10 rounded-[40px] p-8 shadow-3xl space-y-6">
              <div className="flex items-center justify-between gap-3 flex-wrap">
                <div className="flex items-center gap-3">
                  <span className="w-2 h-8 bg-indigo-500 rounded-full"></span>
                  <h2 className="text-xl font-light text-white">Blind A/B Evaluation</h2>
                  {currentEval.modality && <span className="px-2.5 py-1 rounded-full bg-white/5 border border-white/10 text-gray-400 text-[10px] font-black uppercase tracking-widest">{currentEval.modality}</span>}
                </div>
                <button onClick={handleSkip} className="flex items-center gap-2 px-5 py-2.5 bg-red-500/5 border border-red-500/10 rounded-2xl hover:bg-red-500/10 transition-all group">
                  <ChevronRight className="w-4 h-4 text-red-400 group-hover:translate-x-0.5 transition-transform" />
                  <span className="text-xs font-black uppercase tracking-widest text-red-400">Skip</span>
                </button>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                {(["a", "b"] as const).map((k) => {
                  const side = k.toUpperCase();
                  const variant = currentEval[`variant_${k}`];
                  return (
                    <div key={side} className="bg-[#06080b] border border-white/5 rounded-3xl p-5 space-y-4">
                      <div className="flex items-center justify-between">
                        <span className="text-sm font-black uppercase tracking-widest text-indigo-300">Variant {side}</span>
                      </div>
                      <video controls preload="metadata" src={variant?.url} className="w-full rounded-2xl border border-white/10 bg-black/50 aspect-video object-contain" />
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
                  {[{ k: "a" as const, label: "Variant A" }, { k: "tie" as const, label: "Tie" }, { k: "b" as const, label: "Variant B" }].map((o) => (
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
                <button onClick={handleSubmitVote} disabled={!winner || isSubmitting}
                  className="flex-1 bg-gradient-to-r from-indigo-500 to-emerald-600 hover:from-indigo-400 hover:to-emerald-500 text-white font-black py-4 rounded-2xl transition-all active:scale-[0.98] disabled:opacity-40 uppercase tracking-widest text-sm flex items-center justify-center gap-3">
                  {isSubmitting ? <>Registering Vote… <Loader2 className="w-5 h-5 animate-spin" /></> : "Submit Vote"}
                </button>
                <button onClick={() => fetchNewPair()} className="px-5 py-4 rounded-2xl text-xs font-black uppercase tracking-widest bg-white/5 border border-white/10 text-gray-400 hover:text-white transition-all">Next Pair</button>
              </div>
            </section>
          </div>
        )}
      </main>
    </div>
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

function ScenarioReferenceImage({ url, label, onClick }: { url: string; label: string; onClick?: () => void }) {
  return (
    <div onClick={onClick} className={`w-32 aspect-video rounded-2xl overflow-hidden border border-white/10 shadow-2xl group/img relative bg-[#0d1017] ${onClick ? 'cursor-zoom-in' : ''}`}>
      <img src={url} alt={label} className="w-full h-full object-cover transition-transform duration-700 group-hover/img:scale-110" />
      <div className="absolute inset-0 bg-gradient-to-t from-black/80 via-transparent to-transparent"></div>
      <div className="absolute bottom-2 left-2 flex items-center gap-1.5 text-[8px] font-black uppercase tracking-widest text-white">
        <Target className="w-2.5 h-2.5 text-indigo-400" /> {label}
      </div>
    </div>
  );
}

// ===================================================================
// TranslateButton — quick Gemini 2.5 Flash translation of the prompt
// ===================================================================
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
        <p className="mt-2 text-sm text-emerald-200/90 font-light italic leading-relaxed bg-emerald-500/5 border border-emerald-500/15 rounded-xl px-4 py-3 max-w-2xl">
          {translation}
        </p>
      )}
    </div>
  );
}
