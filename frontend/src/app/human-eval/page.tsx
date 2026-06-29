'use client';
import { useState, useEffect, useRef } from 'react';
import {
  Play, Pause, Volume2, VolumeX, Sparkles, Target, Crown,
  ChevronRight, Vote, Award, BarChart3,
  CheckCircle2, AlertCircle, Loader2, Zap, ArrowRight,
  UserCircle2, Cpu, MessageSquareQuote, Tag, Search, X, Filter
} from 'lucide-react';
import { API_BASE_URL, formatUrl, maskPid } from '@/lib/api';
import Nav from '@/components/Nav';

// Human-eval rubric === AI Core-5 rubric (same keys, labels, and 1–5 scale)
// so human vs AI scores are directly comparable per axis.
const SCORE_MIN = 1;
const SCORE_MAX = 5;
const SCORE_DEFAULT = 3;
const DIMENSIONS = [
  { id: 'prompt_adherence', label: 'Prompt Adherence', color: 'indigo' },
  { id: 'visual_quality', label: 'Visual Quality', color: 'purple' },
  { id: 'motion_physics', label: 'Motion & Physics', color: 'pink' },
  { id: 'temporal_consistency', label: 'Temporal Consistency', color: 'emerald' },
  { id: 'audio_visual_sync', label: 'Audio-Visual Sync', color: 'blue' }
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
  const [votingStep, setVotingStep] = useState(1);
  const [winner, setWinner] = useState<string | null>(null);
  const [dimScores, setDimScores] = useState<Record<string, number>>({});
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
  const [veoAnchored, setVeoAnchored] = useState(false);
  // AI auto-eval reveal (shown only AFTER a human vote is cast)
  const [voteAck, setVoteAck] = useState<string>("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const submittingRef = useRef(false); // synchronous re-entry guard (state lags across rapid clicks)
  const [aiReveal, setAiReveal] = useState(false);
  const [aiEval, setAiEval] = useState<any>(null);
  const [aiEvalLoading, setAiEvalLoading] = useState(false);

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
  const handleSelectWinner = (side: 'a' | 'b') => {
    setWinner(side);
    setVotingStep(2);
  };

  const handleScoreChange = (dim: string, score: number) => {
    setDimScores(prev => ({ ...prev, [dim]: score }));
  };

  const handleSubmitVote = async () => {
    // Guard against duplicate submissions (double-click / re-entry). The ref is
    // set synchronously so rapid clicks in the same tick can't slip through
    // before React re-renders the disabled state.
    if (!currentEval || !winner || submittingRef.current) return;
    submittingRef.current = true;
    setIsSubmitting(true);
    const winnerModel = winner === 'a' ? currentEval.variant_a.model_id : currentEval.variant_b.model_id;
    const loserModel = winner === 'a' ? currentEval.variant_b.model_id : currentEval.variant_a.model_id;
    try {
      const voteRes = await fetch(`${API_BASE_URL}/api/sxs/vote`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ job_id: currentEval.job_id, winner_side: winner, winner_model: winnerModel, loser_model: loserModel, scores: dimScores, justification, ldap })
      });
      if (!voteRes.ok) throw new Error(`Server responded ${voteRes.status}`);
      await voteRes.json().catch(() => ({}));
      // Reveal the picked model name, then auto-advance to the next pair in ~1s.
      setVoteAck(`✓ Vote registered — you picked ${prettyModel(winnerModel)} (over ${prettyModel(loserModel)})`);
      setHistory([{ prompt: currentEval.prompt, winner, scores: dimScores, justification, modelA: currentEval.variant_a.model_id, modelB: currentEval.variant_b.model_id }, ...history]);
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
    setAiReveal(false);
    setAiEval(null);
    submittingRef.current = false;
    setIsSubmitting(false);
    resetVotingState();
    fetchNewPair();
  };

  const resetVotingState = () => {
    setVotingStep(1);
    setWinner(null);
    setDimScores({});
    setJustification("");
  };

  const handleSkip = () => {
    resetVotingState();
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

  const isPortrait = currentEval?.ratio === "9:16";

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

      <main className="max-w-screen-2xl mx-auto px-6 pt-8 pb-20">

        {/* Scenario Header */}
        <section className="mb-12 animate-in fade-in slide-in-from-top-4 duration-1000">
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
                <span className="flex items-center gap-2"><Cpu className="w-4 h-4" /> {currentEval?.variant_a.model_id} vs {currentEval?.variant_b.model_id}</span>
              </div>
            </div>
          </div>
        </section>

        {/* Play Controls */}
        <div className="flex justify-center mb-8 gap-4">
          <button onClick={() => { document.querySelectorAll('video').forEach(v => { v.currentTime = 0; v.play(); }); }} className="flex items-center gap-3 px-8 py-4 bg-white/5 border border-white/10 rounded-2xl hover:bg-white/10 transition-all group">
            <div className="p-2 bg-indigo-500 rounded-lg group-hover:scale-110 transition-transform"><Play className="w-4 h-4 text-white fill-white" /></div>
            <span className="text-sm font-bold uppercase tracking-widest text-indigo-400">Play Both</span>
          </button>
          <button onClick={handleSkip} className="flex items-center gap-3 px-8 py-4 bg-red-500/5 border border-red-500/10 rounded-2xl hover:bg-red-500/10 transition-all group">
            <div className="p-2 bg-red-500/20 rounded-lg group-hover:scale-110 transition-transform"><ChevronRight className="w-4 h-4 text-red-400" /></div>
            <span className="text-sm font-bold uppercase tracking-widest text-red-400">Skip</span>
          </button>
        </div>

        {/* Evaluation Matrix - adapts to aspect ratio */}
        <section className={`grid gap-10 mb-12 ${isPortrait ? 'grid-cols-1 md:grid-cols-2 max-w-4xl mx-auto' : 'grid-cols-1 lg:grid-cols-2'}`}>
          {isLoading ? (
            <div className={`${isPortrait ? 'md:col-span-2' : 'lg:col-span-2'} py-40 flex flex-col items-center justify-center text-gray-500 gap-4`}>
              <Loader2 className="w-12 h-12 animate-spin text-indigo-500" />
              <p className="font-light tracking-widest uppercase text-xs">Fetching Bench Scenarios...</p>
            </div>
          ) : !currentEval ? (
            <div className={`${isPortrait ? 'md:col-span-2' : 'lg:col-span-2'} py-40 flex flex-col items-center justify-center text-gray-500 gap-4`}>
              <AlertCircle className="w-12 h-12 text-amber-500" />
              <p className="font-light tracking-widest uppercase text-xs">No active scenarios found. {activeTag || searchText ? 'Try clearing your filters.' : 'Check Admin Console.'}</p>
              {(activeTag || searchText) && (
                <button onClick={handleClearFilters} className="px-4 py-2 rounded-xl bg-indigo-500/20 border border-indigo-500/40 text-indigo-300 text-xs font-bold uppercase">Clear Filters</button>
              )}
            </div>
          ) : (
            <>
              <VideoSlot label="Variant A" side="a" url={currentEval.variant_a.url} isSelected={winner === 'a'} onSelect={() => handleSelectWinner('a')} step={votingStep} winner={winner} isPortrait={isPortrait} />
              <VideoSlot label="Variant B" side="b" url={currentEval.variant_b.url} isSelected={winner === 'b'} onSelect={() => handleSelectWinner('b')} step={votingStep} winner={winner} isPortrait={isPortrait} />
            </>
          )}
        </section>

        {/* Selection Buttons (Step 1) */}
        {votingStep === 1 && !isLoading && currentEval && (
          <div className="grid grid-cols-2 gap-10 mb-12">
            <button onClick={() => handleSelectWinner('a')} className="py-6 rounded-3xl bg-white/5 border border-white/10 text-white font-black uppercase tracking-widest hover:bg-indigo-500/10 hover:border-indigo-500/30 transition-all flex items-center justify-center gap-3 group">
              <Vote className="w-5 h-5 text-indigo-400 group-hover:scale-125 transition-transform" /> Select Variant A
            </button>
            <button onClick={() => handleSelectWinner('b')} className="py-6 rounded-3xl bg-white/5 border border-white/10 text-white font-black uppercase tracking-widest hover:bg-purple-500/10 hover:border-purple-500/30 transition-all flex items-center justify-center gap-3 group">
              <Vote className="w-5 h-5 text-purple-400 group-hover:scale-125 transition-transform" /> Select Variant B
            </button>
          </div>
        )}

        {/* Voting & Rating Flow */}
        <section className="relative">
          {votingStep === 1 ? (
            <div className="text-center py-10 bg-white/[0.02] border border-white/5 rounded-[40px] animate-in fade-in zoom-in-95 duration-500">
              <h3 className="text-2xl font-light text-gray-300 mb-6">Which model captures the prompt best?</h3>
              <p className="text-gray-500 text-sm max-w-md mx-auto mb-8 font-light italic">Selection is finalized after detailed scoring in the next step.</p>
              <div className="flex items-center justify-center gap-6">
                <PickButton side="A" onClick={() => handleSelectWinner('a')} />
                <div className="w-[1px] h-12 bg-white/10"></div>
                <PickButton side="B" onClick={() => handleSelectWinner('b')} />
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
                      {winner === 'a' ? 'Variant A' : 'Variant B'}
                    </div>
                  </div>
                  <div className="space-y-10">
                    {DIMENSIONS.map(dim => (
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

          {aiReveal && currentEval && (
            <AiRevealPanel
              loading={aiEvalLoading}
              aiEval={aiEval}
              variantA={currentEval.variant_a}
              variantB={currentEval.variant_b}
              onNext={handleNextPair}
            />
          )}
        </section>
      </main>
    </div>
  );
}

// ===================================================================
// AiRevealPanel - shows the Core-5 AI auto-eval AFTER a human vote
// ===================================================================
const CORE5_AXES: { key: string; label: string }[] = [
  { key: 'prompt_adherence', label: 'Prompt Adherence' },
  { key: 'visual_quality', label: 'Visual Quality' },
  { key: 'motion_physics', label: 'Motion & Physics' },
  { key: 'temporal_consistency', label: 'Temporal Consistency' },
  { key: 'audio_visual_sync', label: 'Audio-Visual Sync' },
];

function AiRevealPanel({ loading, aiEval, variantA, variantB, onNext }: { loading: boolean; aiEval: any; variantA: EvalVariant; variantB: EvalVariant; onNext: () => void }) {
  const evals = aiEval?.auto_evals || {};
  const lookup = (modelId: string) => {
    if (evals[modelId]) return evals[modelId];
    const base = modelId.split(' (')[0];
    return evals[base] || Object.entries(evals).find(([k]) => k.startsWith(base))?.[1] || null;
  };
  const repA = lookup(variantA.model_id);
  const repB = lookup(variantB.model_id);
  const num = (v: any) => (typeof v === 'number' ? v : (v ? Number(v) : null));

  return (
    <div className="mt-12 bg-[#0b0e14] border border-emerald-500/20 rounded-[40px] p-10 shadow-3xl animate-in fade-in slide-in-from-bottom-6 duration-700">
      <div className="flex items-center justify-between mb-8">
        <div className="flex items-center gap-3">
          <Cpu className="w-6 h-6 text-emerald-400" />
          <h3 className="text-xl font-light text-white">AI Auto-Eval <span className="text-emerald-400 font-black">(Core-5)</span> — revealed after your vote</h3>
        </div>
        <button onClick={onNext} className="px-6 py-3 bg-gradient-to-r from-indigo-500 to-purple-600 hover:from-indigo-400 hover:to-purple-500 text-white font-black rounded-2xl text-sm flex items-center gap-2 active:scale-95 transition-all">
          Next Pair <ArrowRight className="w-4 h-4" />
        </button>
      </div>
      {loading ? (
        <div className="py-16 flex items-center justify-center text-gray-500"><Loader2 className="w-6 h-6 animate-spin mr-3" /> Loading AI ratings…</div>
      ) : (!repA && !repB) ? (
        <div className="py-10 text-center text-gray-500 text-sm">No AI auto-eval available for this pair{aiEval?.auto_eval_status ? ` (status: ${aiEval.auto_eval_status})` : ''}.</div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {[{ label: 'Variant A', rep: repA }, { label: 'Variant B', rep: repB }].map((col, i) => (
            <div key={i} className="bg-[#06080b] border border-white/5 rounded-3xl p-6">
              <div className="flex items-center justify-between mb-4">
                <span className="text-[10px] font-black uppercase tracking-widest text-gray-400">{col.label}</span>
                <span className="text-lg font-black text-emerald-400 font-mono">{col.rep?.overall_score != null ? `${num(col.rep.overall_score)?.toFixed(2)} / 5` : '—'}</span>
              </div>
              <div className="space-y-3">
                {CORE5_AXES.map(axis => {
                  const ax = col.rep?.[axis.key];
                  return (
                    <div key={axis.key}>
                      <div className="flex justify-between text-xs">
                        <span className="text-gray-400">{axis.label}</span>
                        <span className="text-white font-mono font-bold">{ax?.score != null ? `${ax.score}/5` : '—'}</span>
                      </div>
                      {ax?.explanation ? <p className="text-[11px] text-gray-600 mt-1 leading-relaxed">{ax.explanation}</p> : null}
                    </div>
                  );
                })}
              </div>
              {Array.isArray(col.rep?.critical_flaws) && col.rep.critical_flaws.length > 0 && (
                <div className="mt-4 pt-4 border-t border-white/5">
                  <span className="text-[10px] font-black uppercase tracking-widest text-red-400">Critical Flaws</span>
                  <ul className="mt-2 space-y-1">
                    {col.rep.critical_flaws.map((f: string, j: number) => (
                      <li key={j} className="text-[11px] text-red-300/80 flex gap-2"><span>•</span><span>{f}</span></li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ===================================================================
// VideoSlot - supports 16:9 and 9:16
// ===================================================================
function VideoSlot({ label, side, url, isSelected, onSelect, step, winner, isPortrait = false }: { label: string; side: string; url: string; isSelected: boolean; onSelect: () => void; step: number; winner: string | null; isPortrait?: boolean }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [isMuted, setIsMuted] = useState(true);
  const [retryCount, setRetryCount] = useState(0);
  const [hasError, setHasError] = useState(false);

  useEffect(() => { setRetryCount(0); setHasError(false); }, [url]);

  const videoUrl = retryCount > 0 ? `${url}${url.includes('?') ? '&' : '?'}retry=${retryCount}` : url;

  const togglePlay = () => {
    if (!videoRef.current) return;
    if (isPlaying) videoRef.current.pause(); else videoRef.current.play();
    setIsPlaying(!isPlaying);
  };

  return (
    <div className={`relative group/video transition-all duration-700 ${isSelected ? 'scale-[1.02]' : step === 2 ? 'grayscale opacity-40 blur-[2px]' : ''}`}>
      <div className={`absolute -inset-1 rounded-[40px] blur-2xl opacity-0 group-hover/video:opacity-20 transition-all duration-1000 ${side === 'a' ? 'bg-indigo-500' : 'bg-purple-500'} ${isSelected ? 'opacity-40' : ''}`}></div>

      <div className={`relative ${isPortrait ? 'aspect-[9/16] max-h-[70vh]' : 'aspect-video'} rounded-[36px] overflow-hidden border-2 transition-all duration-500 ${isSelected ? 'border-indigo-500 shadow-3xl' : 'border-white/10 bg-[#0d1017]'}`}>
        <video
          ref={videoRef}
          src={videoUrl}
          loop
          muted={isMuted}
          className={`w-full h-full ${isPortrait ? 'object-contain' : 'object-cover'} ${hasError ? 'hidden' : ''}`}
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

        {/* Controls overlay */}
        <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/90 via-black/40 to-transparent p-8 flex items-end justify-between opacity-0 group-hover/video:opacity-100 transition-opacity duration-500">
          <div className="flex items-center gap-4">
            <button onClick={togglePlay} className="w-12 h-12 rounded-full bg-white/10 backdrop-blur-3xl flex items-center justify-center hover:bg-white/20 transition-all">
              {isPlaying ? <Pause className="w-5 h-5 text-white" /> : <Play className="w-5 h-5 text-white translate-x-0.5" />}
            </button>
            <button onClick={(e) => { e.stopPropagation(); setIsMuted(!isMuted); }} className={`w-12 h-12 rounded-full backdrop-blur-3xl flex items-center justify-center transition-all ${isMuted ? 'bg-white/10 hover:bg-white/20' : 'bg-indigo-500/40 border border-indigo-500/50'}`}>
              {isMuted ? <VolumeX className="w-5 h-5 text-gray-400" /> : <Volume2 className="w-5 h-5 text-white" />}
            </button>
            <div className="flex flex-col">
              <span className="text-[10px] font-black uppercase tracking-widest text-indigo-400">{label}</span>
              <span className="text-[8px] font-bold text-gray-500">BLIND EVALUATION</span>
            </div>
          </div>
          <Award className={`w-8 h-8 ${isSelected ? 'text-indigo-400' : 'text-white/20'}`} />
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
      <div className={`absolute inset-0 transition-all opacity-10 group-hover:opacity-20 ${side === 'A' ? 'bg-indigo-500' : 'bg-purple-500'}`}></div>
      <div className="absolute inset-0 border border-white/10 group-hover:border-white/30 rounded-2xl transition-all"></div>
      <span className="relative text-3xl font-black text-white italic tracking-tighter group-hover:scale-110 transition-transform block">Variant {side}</span>
    </button>
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
