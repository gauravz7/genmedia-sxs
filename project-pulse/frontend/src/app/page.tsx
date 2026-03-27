'use client';
const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "";
import { useState, useEffect, useRef } from 'react';
import {
  Play, Pause, Volume2, VolumeX, Sparkles, Target, Crown,
  ChevronRight, Vote, Award, BarChart3,
  CheckCircle2, AlertCircle, Loader2, Zap, ArrowRight,
  UserCircle2, Cpu, MessageSquareQuote, Tag, Search, X, Filter
} from 'lucide-react';
import { Radar, RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis, ResponsiveContainer, Tooltip as RechartsTooltip, Legend } from 'recharts';

const DIMENSIONS = [
  { id: 'motion', label: 'Motion Quality', color: 'indigo' },
  { id: 'prompt', label: 'Prompt Following', color: 'purple' },
  { id: 'aesthetic', label: 'Aesthetic Consistency', color: 'pink' },
  { id: 'expressiveness', label: 'Audio Expressiveness', color: 'emerald' },
  { id: 'sync', label: 'Audio-Visual Sync', color: 'blue' }
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
  start_image_url?: string;
  end_image_url?: string;
  reference_image_url?: string;
  reference_images?: string[];
  variant_a: EvalVariant;
  variant_b: EvalVariant;
}

export default function LivingArena() {
  const [isMounted, setIsMounted] = useState(false);
  const [votesCount, setVotesCount] = useState(0);
  const [currentEval, setCurrentEval] = useState<EvaluationPair | null>(null);
  const [votingStep, setVotingStep] = useState(1);
  const [winner, setWinner] = useState<string | null>(null);
  const [dimScores, setDimScores] = useState<Record<string, number>>({});
  const [justification, setJustification] = useState("");
  const [showStats, setShowStats] = useState(false);
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

  useEffect(() => {
    setIsMounted(true);
    fetchNewPair();
    fetchTags();
    const savedVotes = localStorage.getItem('project_pulse_votes');
    const savedHistory = localStorage.getItem('project_pulse_history');
    if (savedVotes) setVotesCount(parseInt(savedVotes));
    if (savedHistory) setHistory(JSON.parse(savedHistory));

    fetch(`${API_BASE_URL}/api/leaderboard/users`)
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

  const formatUrl = (url?: string) => {
    if (!url) return url;
    if (url.startsWith('/api/media')) return `${API_BASE_URL}${url}`;
    return url;
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

      const res = await fetch(`${API_BASE_URL}/api/evaluation/pair${qs}`);
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
      fetch(`${API_BASE_URL}/api/evaluation/stats?ldap=${ldap}`)
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
    if (!currentEval || !winner) return;
    const winnerModel = winner === 'a' ? currentEval.variant_a.model_id : currentEval.variant_b.model_id;
    const loserModel = winner === 'a' ? currentEval.variant_b.model_id : currentEval.variant_a.model_id;
    try {
      await fetch(`${API_BASE_URL}/api/evaluation/vote`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ job_id: currentEval.job_id, winner_side: winner, winner_model: winnerModel, loser_model: loserModel, scores: dimScores, justification, ldap })
      });
      setHistory([{ prompt: currentEval.prompt, winner, scores: dimScores, justification, modelA: currentEval.variant_a.model_id, modelB: currentEval.variant_b.model_id }, ...history]);
      setVotesCount(prev => prev + 1);
      resetVotingState();
      fetchNewPair();
    } catch (err) {
      console.error("Failed to submit vote", err);
    }
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

  if (showStats) {
    return <StatsDashboard history={history} ldap={ldap} onBack={() => setShowStats(false)} globalLeaderboard={globalLeaderboard} activeTag={activeTag} />;
  }

  return (
    <div className="min-h-screen bg-[#020408] text-gray-100 font-sans selection:bg-indigo-500/30 overflow-x-hidden">
      <div className="fixed inset-0 -z-10 bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-indigo-900/10 via-slate-950 to-[#020408]"></div>

      {/* Expanded Image Overlay */}
      {expandedImage && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-black/90 backdrop-blur-sm cursor-zoom-out animate-in fade-in duration-300" onClick={() => setExpandedImage(null)}>
          <img src={expandedImage} className="max-w-full max-h-full rounded-2xl shadow-2xl border border-white/10" alt="Expanded view" />
        </div>
      )}

      {/* Nav */}
      <nav className="fixed w-full border-b border-white/5 bg-[#020408]/60 backdrop-blur-2xl z-50">
        <div className="max-w-screen-2xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center shadow-[0_0_20px_rgba(99,102,241,0.3)]">
              <Zap className="w-5 h-5 text-white" />
            </div>
            <span className="text-xl font-black tracking-tighter text-white uppercase italic">Arena</span>

            {/* Search by Prompt ID */}
            <form onSubmit={(e) => { e.preventDefault(); fetchNewPair(searchPromptId); }} className="ml-6 relative flex items-center group">
              <Search className="w-4 h-4 text-gray-500 absolute left-3 group-focus-within:text-indigo-400 transition-colors" />
              <input type="text" placeholder="Prompt ID..." value={searchPromptId} onChange={(e) => setSearchPromptId(e.target.value)} className="pl-9 pr-4 py-2 bg-white/5 border border-white/10 rounded-xl text-sm text-white font-medium focus:outline-none focus:ring-2 focus:ring-indigo-500/50 focus:bg-white/10 transition-all w-40 placeholder-gray-500" />
            </form>

            {/* Search by Prompt Text */}
            <form onSubmit={(e) => { e.preventDefault(); fetchNewPair(undefined, undefined, searchText); }} className="relative flex items-center group">
              <Search className="w-4 h-4 text-gray-500 absolute left-3 group-focus-within:text-indigo-400 transition-colors" />
              <input type="text" placeholder="Search prompts..." value={searchText} onChange={(e) => setSearchText(e.target.value)} className="pl-9 pr-4 py-2 bg-white/5 border border-white/10 rounded-xl text-sm text-white font-medium focus:outline-none focus:ring-2 focus:ring-indigo-500/50 focus:bg-white/10 transition-all w-48 placeholder-gray-500" />
            </form>

            {/* Veo Anchored Toggle */}
            <button
              onClick={() => {
                const next = !veoAnchored;
                setVeoAnchored(next);
                // Fetch new pair with updated flag
                setIsLoading(true);
                const params = new URLSearchParams();
                if (activeTag) params.set("tag", activeTag);
                if (searchText) params.set("search", searchText);
                if (next) params.set("veo_anchored", "true");
                const qs = params.toString() ? `?${params.toString()}` : '';
                fetch(`${API_BASE_URL}/api/evaluation/pair${qs}`)
                  .then(r => r.json())
                  .then(data => {
                    if (data.status === "error") { setCurrentEval(null); }
                    else {
                      if (data.variant_a?.url) data.variant_a.url = formatUrl(data.variant_a.url);
                      if (data.variant_b?.url) data.variant_b.url = formatUrl(data.variant_b.url);
                      if (data.start_image_url) data.start_image_url = formatUrl(data.start_image_url);
                      if (data.end_image_url) data.end_image_url = formatUrl(data.end_image_url);
                      if (data.reference_image_url) data.reference_image_url = formatUrl(data.reference_image_url);
                      if (data.reference_images) data.reference_images = data.reference_images.map(formatUrl);
                      setCurrentEval(data);
                    }
                    setIsLoading(false);
                    setVotingStep(1); setWinner(null); setDimScores({}); setJustification("");
                  })
                  .catch(() => setIsLoading(false));
              }}
              className={`flex items-center gap-2 px-3 py-2 rounded-xl text-xs font-bold uppercase tracking-widest transition-all border ${veoAnchored ? 'bg-purple-500/20 border-purple-500/40 text-purple-300 shadow-[0_0_12px_rgba(168,85,247,0.2)]' : 'bg-white/5 border-white/10 text-gray-500 hover:text-white'}`}
              title="When active, one video is always from Veo"
            >
              <Target className="w-3.5 h-3.5" />
              Veo Mode
            </button>

            {/* Tag Filter Toggle */}
            <button onClick={() => setShowTagFilter(!showTagFilter)} className={`flex items-center gap-2 px-3 py-2 rounded-xl text-xs font-bold uppercase tracking-widest transition-all border ${activeTag ? 'bg-indigo-500/20 border-indigo-500/40 text-indigo-300' : 'bg-white/5 border-white/10 text-gray-500 hover:text-white'}`}>
              <Filter className="w-3.5 h-3.5" />
              {activeTag || 'Tags'}
              {activeTag && <X className="w-3 h-3 ml-1 cursor-pointer" onClick={(e) => { e.stopPropagation(); handleClearFilters(); }} />}
            </button>
          </div>

          <div className="flex items-center gap-8">
            <div className="flex items-center gap-3">
              <div className="flex flex-col items-end mr-1">
                <span className="text-[10px] font-bold text-gray-500 uppercase tracking-widest">@{ldap}</span>
                <span className="text-xs font-black text-indigo-400 font-mono tracking-tighter">{votesCount} VOTES</span>
              </div>
              <div className="w-48 h-2 bg-white/5 rounded-full overflow-hidden border border-white/10 shadow-inner">
                <div className="h-full bg-gradient-to-r from-indigo-500 via-purple-500 to-pink-500 transition-all duration-1000 ease-out shadow-[0_0_10px_rgba(168,85,247,0.5)]" style={{ width: `${Math.min((votesCount / 10) * 100, 100)}%` }}></div>
              </div>
              {votesCount >= 10 ? (
                <button onClick={() => setShowStats(true)} className="px-4 py-2 ml-2 rounded-xl bg-indigo-500/20 border border-indigo-500/40 flex items-center gap-2 hover:bg-indigo-500/40 transition-all font-bold text-xs uppercase text-indigo-300 shadow-[0_0_15px_rgba(99,102,241,0.3)]">
                  <BarChart3 className="w-4 h-4 text-indigo-400" /> Analytics
                </button>
              ) : (
                <div className="w-8 h-8 rounded-full bg-white/5 border border-white/10 flex items-center justify-center opacity-50">
                  <Crown className="w-4 h-4 text-gray-500" />
                </div>
              )}
            </div>
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
      </nav>

      <main className="max-w-screen-2xl mx-auto px-6 pt-32 pb-20">

        {/* Scenario Header */}
        <section className="mb-12 animate-in fade-in slide-in-from-top-4 duration-1000">
          <div className="flex flex-col lg:flex-row items-start gap-8">
            {currentEval && (
              <div className="flex flex-wrap gap-4 shrink-0">
                {currentEval.start_image_url && <ScenarioReferenceImage url={currentEval.start_image_url} label="Start Frame" onClick={() => setExpandedImage(currentEval.start_image_url ?? null)} />}
                {currentEval.end_image_url && <ScenarioReferenceImage url={currentEval.end_image_url} label="End Frame" onClick={() => setExpandedImage(currentEval.end_image_url ?? null)} />}
                {currentEval.reference_image_url && !currentEval.reference_images && <ScenarioReferenceImage url={currentEval.reference_image_url} label="Ref Image" onClick={() => setExpandedImage(currentEval.reference_image_url ?? null)} />}
                {currentEval.reference_images?.map((url, i) => (
                  <ScenarioReferenceImage key={i} url={url} label={`Ref ${i + 1}`} onClick={() => setExpandedImage(url ?? null)} />
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
              <div className="flex items-center gap-4 text-sm text-gray-500 italic font-light">
                <span className="flex items-center gap-2 font-mono"><UserCircle2 className="w-4 h-4" /> {currentEval?.job_id ? `PID: ${currentEval.job_id}` : "Expert Bench"}</span>
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
                          <span className="text-lg font-black text-white font-mono">{dimScores[dim.id] || 5}</span>
                        </div>
                        <input type="range" min="1" max="10" value={dimScores[dim.id] || 5} onChange={(e) => handleScoreChange(dim.id, parseInt(e.target.value))} className="w-full h-1.5 bg-white/5 rounded-lg appearance-none cursor-pointer accent-indigo-500" />
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
                  <button onClick={handleSubmitVote} className="w-full bg-gradient-to-r from-indigo-500 via-purple-600 to-pink-600 hover:from-indigo-400 hover:to-pink-500 text-white font-black py-6 rounded-[30px] shadow-[0_20px_50px_rgba(99,102,241,0.3)] transition-all flex items-center justify-center gap-4 group active:scale-[0.98] text-xl">
                    Deploy Evaluation <ArrowRight className="w-6 h-6 group-hover:translate-x-2 transition-transform" />
                  </button>
                  <button onClick={() => setVotingStep(1)} className="w-full py-4 text-xs font-bold text-gray-500 uppercase tracking-[0.3em] hover:text-gray-300 transition-colors">
                    &larr; Re-pick Winner
                  </button>
                </div>
              </div>
            </div>
          )}
        </section>
      </main>
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

// ===================================================================
// Stats Dashboard - with tag filter support
// ===================================================================
function StatsDashboard({ history, ldap, onBack, globalLeaderboard = [], activeTag: initialTag = "" }: { history: any[]; ldap: string; onBack: () => void; globalLeaderboard?: any[]; activeTag?: string }) {
  const [stats, setStats] = useState<any>(null);
  const [view, setView] = useState<'global' | 'user'>('global');
  const [skuMode, setSkuMode] = useState<'Global' | 'T2V' | 'I2V' | 'R2V'>('Global');
  const [isLoading, setIsLoading] = useState(true);
  const [selectedTag, setSelectedTag] = useState(initialTag);
  const [availableTags, setAvailableTags] = useState<string[]>([]);
  const [showTagPicker, setShowTagPicker] = useState(false);
  const [tagSearch, setTagSearch] = useState("");

  const fetchStats = (tag: string) => {
    setIsLoading(true);
    const tagParam = tag ? `&tag=${encodeURIComponent(tag)}` : '';
    fetch(`${API_BASE_URL}/api/evaluation/stats?ldap=${ldap}${tagParam}`)
      .then(res => res.json())
      .then(data => { setStats(data); setIsLoading(false); })
      .catch(err => { console.error(err); setIsLoading(false); });
  };

  useEffect(() => {
    fetchStats(selectedTag);
    fetch(`${API_BASE_URL}/api/tags`)
      .then(res => res.json())
      .then(data => { if (data?.status === "success") setAvailableTags(data.tags); })
      .catch(() => {});
  }, []);

  const handleTagSelect = (tag: string) => {
    const newTag = selectedTag === tag ? "" : tag;
    setSelectedTag(newTag);
    setShowTagPicker(false);
    setTagSearch("");
    fetchStats(newTag);
  };

  const handleClearTag = () => {
    setSelectedTag("");
    setShowTagPicker(false);
    setTagSearch("");
    fetchStats("");
  };

  const filteredTags = tagSearch
    ? availableTags.filter(t => t.toLowerCase().includes(tagSearch.toLowerCase()))
    : availableTags;

  if (isLoading || !stats) {
    return (
      <div className="min-h-screen bg-[#020408] text-white p-12 flex items-center justify-center">
        <Loader2 className="w-12 h-12 animate-spin text-indigo-500" />
      </div>
    );
  }

  const currentStats = stats[view] || { total_evals: 0, modes: { T2V: 0, I2V: 0, R2V: 0 }, skus: [] };
  const { total_evals, modes: statsModes, skus } = currentStats;

  const familyCounts: Record<string, number> = { 'Veo': 0, 'Kling': 0, 'Seedance': 0 };
  let totalVotesCount = 0;
  skus.forEach((s: any) => {
    let m = s.model_id;
    if (m.toLowerCase().includes('veo')) m = 'Veo';
    else if (m.toLowerCase().includes('kling')) m = 'Kling';
    else if (m.toLowerCase().includes('seedance') || m.toLowerCase().includes('doubao')) m = 'Seedance';
    familyCounts[m] = (familyCounts[m] || 0) + s.wins;
    totalVotesCount += s.wins;
  });
  const effectiveTotal = Math.max(totalVotesCount, 1);
  const models = ['Veo', 'Kling', 'Seedance'];

  const buildRadarData = (mode: 't2v' | 'i2v') => {
    const rateKey = `${mode}_rate`, totalKey = `${mode}_total`;
    const sortedSkus = [...skus].filter((s: any) => s[totalKey] > 0).sort((a: any, b: any) => b[rateKey] - a[rateKey]).slice(0, 3);
    const data: any[] = [];
    DIMENSIONS.forEach(d => {
      const row: any = { subject: d.label };
      sortedSkus.forEach((s: any) => { row[s.model_id] = (mode === 't2v' ? s.t2v_scores : s.i2v_scores)?.[d.id] || 0; });
      data.push(row);
    });
    return { data, topModels: sortedSkus.map((s: any) => s.model_id) };
  };

  const { data: t2vRadarData, topModels: t2vTopModels } = buildRadarData('t2v');
  const { data: i2vRadarData, topModels: i2vTopModels } = buildRadarData('i2v');
  const CHART_COLORS = ['#818cf8', '#f472b6', '#34d399'];

  return (
    <div className="min-h-screen bg-[#020408] text-white p-12">
      <div className="max-w-4xl mx-auto space-y-12 animate-in fade-in slide-in-from-bottom-8 duration-700">
        <header className="space-y-6">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-5xl font-black italic tracking-tighter mb-4">BENCHMARK <span className="text-indigo-500">RESULTS</span></h1>
              <p className="text-gray-500 text-lg font-light">Aggregated SxS performance synthesis.</p>
            </div>
            <div className="flex bg-white/5 p-1 rounded-2xl border border-white/10">
              <button onClick={() => setView('global')} className={`px-6 py-3 rounded-xl font-bold text-sm uppercase tracking-widest transition-all ${view === 'global' ? 'bg-indigo-500 text-white shadow-lg' : 'text-gray-500 hover:text-white'}`}>Global</button>
              <button onClick={() => setView('user')} className={`px-6 py-3 rounded-xl font-bold text-sm uppercase tracking-widest transition-all ${view === 'user' ? 'bg-purple-500 text-white shadow-lg' : 'text-gray-500 hover:text-white'}`}>@{ldap}</button>
            </div>
          </div>

          {/* Tag Filter Bar */}
          <div className="bg-[#0b0e14] border border-white/5 rounded-2xl p-4">
            <div className="flex items-center gap-3 flex-wrap">
              <div className="flex items-center gap-2 text-[10px] font-black uppercase tracking-widest text-gray-500">
                <Filter className="w-3.5 h-3.5" /> Filter by Tag
              </div>

              {selectedTag ? (
                <div className="flex items-center gap-2 px-4 py-2 rounded-xl bg-indigo-500 text-white text-xs font-bold">
                  {selectedTag}
                  <X className="w-3.5 h-3.5 cursor-pointer hover:opacity-70" onClick={handleClearTag} />
                </div>
              ) : (
                <button onClick={() => setShowTagPicker(!showTagPicker)} className="px-4 py-2 rounded-xl bg-white/5 border border-white/10 text-xs font-bold text-gray-400 hover:text-white hover:border-white/20 transition-all">
                  All Categories
                </button>
              )}

              {selectedTag && (
                <span className="text-[10px] text-gray-500 italic">
                  Showing results filtered to &ldquo;{selectedTag}&rdquo; &mdash; {total_evals} evaluation{total_evals !== 1 ? 's' : ''}
                </span>
              )}
            </div>

            {showTagPicker && (
              <div className="mt-4 space-y-3">
                <div className="relative">
                  <Search className="w-4 h-4 text-gray-500 absolute left-3 top-1/2 -translate-y-1/2" />
                  <input
                    type="text" value={tagSearch} onChange={(e) => setTagSearch(e.target.value)}
                    placeholder="Search tags..."
                    className="w-full pl-9 pr-4 py-2 bg-white/5 border border-white/10 rounded-xl text-sm text-white focus:outline-none focus:ring-2 focus:ring-indigo-500/50 placeholder-gray-600"
                    autoFocus
                  />
                </div>
                <div className="flex flex-wrap gap-2 max-h-[160px] overflow-y-auto pr-2">
                  {filteredTags.map(tag => (
                    <button key={tag} onClick={() => handleTagSelect(tag)} className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all border ${selectedTag === tag ? 'bg-indigo-500 text-white border-indigo-500 shadow-lg' : 'bg-white/5 border-white/10 text-gray-400 hover:text-white hover:border-white/20'}`}>
                      {tag}
                    </button>
                  ))}
                  {filteredTags.length === 0 && (
                    <span className="text-xs text-gray-600 italic py-2">No tags match &ldquo;{tagSearch}&rdquo;</span>
                  )}
                </div>
              </div>
            )}
          </div>
        </header>

        <div className="grid grid-cols-3 gap-6">
          {models.map(model => (
            <div key={model} className="bg-[#0b0e14] border border-white/5 rounded-[40px] p-8 text-center space-y-4">
              <div className="text-xs font-black text-gray-500 uppercase tracking-[0.4em]">{model}</div>
              <div className="text-6xl font-black text-transparent bg-clip-text bg-gradient-to-br from-white to-gray-500">{Math.round(((familyCounts[model] || 0) / effectiveTotal) * 100)}%</div>
              <div className="text-[10px] font-bold text-indigo-400 uppercase tracking-widest">Aggregate Win Rate</div>
            </div>
          ))}
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-8 pt-8 border-t border-white/5 mt-8">
          <div>
            <h3 className="text-xl font-light text-gray-300 mb-6">Mode Breakup</h3>
            <div className="space-y-4">
              {['T2V', 'I2V', 'R2V'].map(mode => (
                <div key={mode} className="flex items-center justify-between p-4 bg-white/[0.02] border border-white/5 rounded-2xl">
                  <span className="font-bold text-indigo-400">{mode}</span>
                  <span className="font-mono text-xl">{statsModes[mode] || 0}</span>
                </div>
              ))}
            </div>
          </div>
          <div>
            <div className="flex items-center justify-between mb-6">
              <h3 className="text-xl font-light text-gray-300">SKU Win Rates</h3>
              <div className="flex bg-white/5 p-1 rounded-xl border border-white/10">
                {['Global', 'T2V', 'I2V', 'R2V'].map(sm => (
                  <button key={sm} onClick={() => setSkuMode(sm as any)} className={`px-3 py-1.5 rounded-lg text-xs font-bold uppercase tracking-widest transition-all ${skuMode === sm ? 'bg-indigo-500 text-white shadow-lg' : 'text-gray-500 hover:text-white'}`}>{sm}</button>
                ))}
              </div>
            </div>
            <div className="space-y-4 max-h-[220px] overflow-y-auto pr-2">
              {skus.map((sku: any) => {
                let r = sku.win_rate, w = sku.wins, t = sku.total;
                if (skuMode === 'T2V') { r = sku.t2v_rate; w = sku.t2v_wins; t = sku.t2v_total; }
                else if (skuMode === 'I2V') { r = sku.i2v_rate; w = sku.i2v_wins; t = sku.i2v_total; }
                else if (skuMode === 'R2V') { r = sku.r2v_rate; w = sku.r2v_wins; t = sku.r2v_total; }
                if (t === 0 && skuMode !== 'Global') return null;
                return (
                  <div key={`${sku.model_id}-${skuMode}`} className="flex items-center justify-between p-4 bg-white/[0.02] border border-white/5 rounded-2xl">
                    <div className="flex flex-col">
                      <span className="font-medium text-sm text-gray-400 max-w-[170px] truncate">{sku.model_id}</span>
                      <span className="text-[10px] text-indigo-400/70 font-bold uppercase tracking-widest mt-1">Latency: {sku.latency_ps ? `${sku.latency_ps}s/sec` : 'N/A'}</span>
                    </div>
                    <div className="text-right flex flex-col items-end">
                      <span className="font-mono text-lg font-bold text-white">{r}%</span>
                      <span className="text-[10px] text-gray-500 uppercase tracking-widest">{w}/{t} won</span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>

        {/* Spider Charts */}
        <div className="pt-8 border-t border-white/5 mt-8">
          <h3 className="text-xl font-light text-gray-300 mb-6">Dimension Analytics</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
            {[{ title: 'Text-to-Video (T2V)', data: t2vRadarData, models: t2vTopModels }, { title: 'Image-to-Video (I2V)', data: i2vRadarData, models: i2vTopModels }].map(chart => (
              <div key={chart.title} className="bg-[#0b0e14] border border-white/5 rounded-[40px] p-6 relative h-[400px]">
                <h4 className="text-center text-sm font-bold text-gray-400 uppercase tracking-widest mb-4">{chart.title}</h4>
                <ResponsiveContainer width="100%" height="100%">
                  <RadarChart cx="50%" cy="50%" outerRadius="70%" data={chart.data}>
                    <PolarGrid stroke="#334155" />
                    <PolarAngleAxis dataKey="subject" tick={{ fill: '#94a3b8', fontSize: 10 }} />
                    <PolarRadiusAxis angle={30} domain={[0, 10]} tick={{ fill: '#64748b', fontSize: 10 }} axisLine={false} />
                    <RechartsTooltip contentStyle={{ backgroundColor: '#0f172a', border: '1px solid #334155', borderRadius: '12px' }} itemStyle={{ color: '#e2e8f0' }} />
                    <Legend wrapperStyle={{ fontSize: '10px' }} />
                    {chart.models.map((modelId: string, idx: number) => (
                      <Radar key={modelId} name={modelId} dataKey={modelId} stroke={CHART_COLORS[idx]} fill={CHART_COLORS[idx]} fillOpacity={0.3} />
                    ))}
                  </RadarChart>
                </ResponsiveContainer>
              </div>
            ))}
          </div>
        </div>

        {/* Back to Arena */}
        <div className="bg-indigo-500/10 border border-indigo-500/20 rounded-[40px] p-10 flex items-center justify-between">
          <div className="flex items-center gap-6">
            <div className="w-20 h-20 rounded-3xl bg-indigo-500 flex items-center justify-center shadow-3xl rotate-3"><Crown className="w-10 h-10 text-white" /></div>
            <div>
              <h2 className="text-2xl font-bold">Evaluation Tier Unlocked</h2>
              <p className="text-indigo-300/80 font-light">You may now submit custom benchmarking prompts.</p>
            </div>
          </div>
          <button onClick={onBack} className="px-10 py-5 bg-white text-[#020408] rounded-3xl font-black uppercase text-sm shadow-3xl hover:scale-105 transition-all">Back to Arena</button>
        </div>

        {/* Recent Evaluations & Leaderboard */}
        <div className="pt-10 grid grid-cols-1 lg:grid-cols-2 gap-10">
          <div>
            <h3 className="text-xl font-light text-gray-500 mb-8 border-b border-white/5 pb-4">Your Recent Evaluations</h3>
            <div className="space-y-4">
              {history.map((h, i) => (
                <div key={i} className="flex items-center justify-between p-6 bg-white/[0.02] border border-white/5 rounded-3xl">
                  <div className="flex-1">
                    <div className="text-[10px] font-black text-indigo-400 uppercase tracking-widest mb-1 italic">Case {history.length - i}</div>
                    <div className="text-gray-300 font-light line-clamp-1">&ldquo;{h.prompt}&rdquo;</div>
                  </div>
                  <div className="text-right">
                    <div className="text-xs font-black text-white uppercase">{h.winner === 'a' ? h.modelA : h.modelB} Won</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
          <div>
            <h3 className="text-xl font-light text-gray-500 mb-8 border-b border-white/5 pb-4 flex items-center gap-3"><Crown className="w-5 h-5 text-yellow-400" /> Top Evaluators</h3>
            <div className="space-y-4">
              {globalLeaderboard.length > 0 ? globalLeaderboard.map((user, idx) => (
                <div key={user.ldap} className="flex items-center justify-between p-6 bg-[#0b0e14] border border-white/5 rounded-3xl hover:bg-white/5 transition-colors">
                  <div className="flex items-center gap-6">
                    <span className={`font-black text-2xl ${idx === 0 ? 'text-yellow-400' : idx === 1 ? 'text-gray-300' : idx === 2 ? 'text-amber-600' : 'text-gray-600'}`}>#{idx + 1}</span>
                    <span className="font-mono text-indigo-300 text-lg">{user.ldap}</span>
                  </div>
                  <div className="flex items-center gap-2 bg-indigo-500/10 px-4 py-2 rounded-xl">
                    <span className="font-black text-white">{user.count}</span>
                    <span className="text-[10px] text-gray-500 uppercase tracking-widest">votes</span>
                  </div>
                </div>
              )) : (
                <div className="text-center py-10 text-gray-500 text-sm flex items-center justify-center gap-2">
                  <Loader2 className="w-4 h-4 animate-spin text-gray-400" /> Fetching...
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
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
