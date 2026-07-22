'use client';
import { useState, useEffect } from 'react';
import {
  Crown, Filter, Search, X, Loader2, Lock, Clapperboard, ImageIcon, AudioLines,
} from 'lucide-react';
import { Radar, RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis, ResponsiveContainer, Tooltip as RechartsTooltip, Legend } from 'recharts';
import { API_BASE_URL } from '@/lib/api';
import Nav from '@/components/Nav';
import ImageResults from '@/components/ImageResults';
import TtsResults from '@/components/TtsResults';
import TagWinRateMatrix from '@/components/TagWinRateMatrix';

const DIMENSIONS = [
  { id: 'prompt_adherence', label: 'Prompt Adherence', color: 'indigo' },
  { id: 'visual_quality', label: 'Visual Quality', color: 'purple' },
  { id: 'motion_physics', label: 'Motion & Physics', color: 'pink' },
  { id: 'temporal_consistency', label: 'Temporal Consistency', color: 'emerald' },
  { id: 'audio_visual_sync', label: 'Audio-Visual Sync', color: 'blue' }
];

export default function Analytics() {
  const [stats, setStats] = useState<any>(null);
  const [skuMode, setSkuMode] = useState<'Global' | 'T2V' | 'I2V' | 'R2V'>('Global');
  const [isLoading, setIsLoading] = useState(true);
  const [selectedTag, setSelectedTag] = useState("");
  const [availableTags, setAvailableTags] = useState<string[]>([]);
  const [showTagPicker, setShowTagPicker] = useState(false);
  const [tagSearch, setTagSearch] = useState("");
  const [history, setHistory] = useState<any[]>([]);
  const [globalLeaderboard, setGlobalLeaderboard] = useState<any[]>([]);
  const [latency, setLatency] = useState<any[]>([]);
  const [winmap, setWinmap] = useState<any>(null);
  const [agreement, setAgreement] = useState<any>(null);
  const [modTab, setModTab] = useState<"video" | "image" | "tts">("video");
  // 10-vote access gate (counts votes across video + image + tts).
  const [gate, setGate] = useState<{ checked: boolean; unlocked: boolean; count: number; required: number }>({ checked: false, unlocked: false, count: 0, required: 10 });
  const [gateLdap, setGateLdap] = useState("");

  // Personal ldap drives the gate. Video uses project_pulse_ldap; image/tts use pp_ldap.
  const ldap = (typeof window !== "undefined" && (localStorage.getItem("project_pulse_ldap") || localStorage.getItem("pp_ldap"))) || "global";

  // Count this user's votes across every modality and unlock if >= required.
  const checkGate = (ld: string) => {
    fetch(`${API_BASE_URL}/api/votes/count?ldap=${encodeURIComponent(ld)}`)
      .then((res) => res.json())
      .then((data) => setGate({ checked: true, unlocked: !!data?.unlocked, count: data?.count ?? 0, required: data?.required ?? 10 }))
      .catch(() => setGate({ checked: true, unlocked: false, count: 0, required: 10 }));
  };

  const applyGateLdap = () => {
    const ld = gateLdap.trim().toLowerCase();
    if (!ld) return;
    if (typeof window !== "undefined") {
      localStorage.setItem("project_pulse_ldap", ld);
      localStorage.setItem("pp_ldap", ld);
    }
    setGate((g) => ({ ...g, checked: false }));
    checkGate(ld);
  };

  const fetchStats = (tag: string) => {
    setIsLoading(true);
    const tagParam = tag ? `&tag=${encodeURIComponent(tag)}` : '';
    fetch(`${API_BASE_URL}/api/sxs/stats?ldap=${ldap}${tagParam}`)
      .then(res => res.json())
      .then(data => { setStats(data); setIsLoading(false); })
      .catch(err => { console.error(err); setIsLoading(false); });
  };

  useEffect(() => {
    fetchStats(selectedTag);
    // Video picker tags must come from the SxS job collection the stats use
    // (not the legacy production /api/tags), so filter options match the data.
    fetch(`${API_BASE_URL}/api/sxs/tags`)
      .then(res => res.json())
      .then(data => { if (data?.status === "success") setAvailableTags(data.tags); })
      .catch(() => {});
    fetch(`${API_BASE_URL}/api/sxs/leaderboard/users`)
      .then(res => res.json())
      .then(data => { if (data?.status === "success" && data.leaderboard) setGlobalLeaderboard(data.leaderboard); })
      .catch(() => {});
    fetch(`${API_BASE_URL}/api/analytics/latency`)
      .then(res => res.json())
      .then(data => { if (Array.isArray(data?.rows)) setLatency(data.rows); })
      .catch(() => {});
    fetch(`${API_BASE_URL}/api/benchmark/winmap`)
      .then(res => res.json())
      .then(data => { if (data?.overall) setWinmap(data); })
      .catch(() => {});
    fetch(`${API_BASE_URL}/api/analytics/agreement`)
      .then(res => res.json())
      .then(data => { if (data?.overall) setAgreement(data); })
      .catch(() => {});
    try {
      const savedHistory = localStorage.getItem('project_pulse_history');
      if (savedHistory) setHistory(JSON.parse(savedHistory));
    } catch { /* ignore */ }
    if (ldap && ldap !== "global") setGateLdap(ldap);
    checkGate(ldap);
    // eslint-disable-next-line react-hooks/exhaustive-deps
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

  if (gate.checked && !gate.unlocked) {
    const pct = Math.min(100, Math.round((gate.count / gate.required) * 100));
    return (
      <div className="min-h-screen bg-[#020408] text-white pt-8 px-6 pb-20">
        <Nav active="analytics" />
        <div className="max-w-2xl mx-auto text-center space-y-8 animate-in fade-in slide-in-from-bottom-6 duration-700">
          <div className="w-20 h-20 mx-auto rounded-3xl bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center shadow-[0_0_40px_rgba(99,102,241,0.4)]">
            <Lock className="w-10 h-10 text-white" />
          </div>
          <div>
            <h1 className="text-4xl md:text-5xl font-black tracking-tight">Analytics is locked</h1>
            <p className="text-gray-400 mt-4 text-lg font-light">
              Cast <span className="font-black text-white">{gate.required}</span> blind votes across any modality to unlock the aggregated leaderboards and radar charts.
            </p>
          </div>

          {/* Enter ldap to count your existing votes across all modalities */}
          <div className="max-w-sm mx-auto flex items-center gap-2">
            <input
              value={gateLdap}
              onChange={(e) => setGateLdap(e.target.value.toLowerCase())}
              onKeyDown={(e) => { if (e.key === "Enter") applyGateLdap(); }}
              placeholder="enter your ldap"
              className="flex-1 bg-[#0b0e14] border border-white/10 rounded-2xl px-5 py-3 text-sm text-white placeholder-gray-600 font-mono text-center focus:outline-none focus:ring-2 focus:ring-indigo-500/50"
            />
            <button
              onClick={applyGateLdap}
              className="px-5 py-3 rounded-2xl bg-white text-[#020408] font-black uppercase text-xs tracking-widest hover:bg-gray-200 transition-colors"
            >
              Check
            </button>
          </div>
          <div className="space-y-2">
            <div className="flex items-center justify-between text-[11px] font-black uppercase tracking-widest text-gray-500">
              <span>{ldap === "global" ? "Not signed in" : `Voting as ${ldap}`}</span>
              <span className="text-indigo-300">{gate.count} / {gate.required} votes</span>
            </div>
            <div className="h-3 rounded-full bg-white/5 border border-white/10 overflow-hidden">
              <div className="h-full bg-gradient-to-r from-indigo-500 to-emerald-400 transition-all duration-700" style={{ width: `${pct}%` }} />
            </div>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 pt-4">
            {[
              { href: "/video-sxs", label: "Video Eval", icon: Clapperboard },
              { href: "/image-sxs", label: "Image Eval", icon: ImageIcon },
              { href: "/tts-sxs", label: "TTS Eval", icon: AudioLines },
            ].map((a) => {
              const Icon = a.icon;
              return (
                <a key={a.href} href={a.href} className="group bg-[#0b0e14] border border-white/10 rounded-2xl p-5 hover:border-indigo-500/40 transition-all flex flex-col items-center gap-3">
                  <Icon className="w-7 h-7 text-indigo-400 group-hover:scale-110 transition-transform" />
                  <span className="text-xs font-black uppercase tracking-widest text-gray-300">{a.label}</span>
                </a>
              );
            })}
          </div>
          <a href="/" className="inline-block text-[11px] font-black uppercase tracking-widest text-gray-500 hover:text-white transition-colors">← Back home</a>
        </div>
      </div>
    );
  }

  if (isLoading || !stats) {
    return (
      <div className="min-h-screen bg-[#020408] text-white">
        <Nav active="analytics" />
        <div className="flex items-center justify-center py-40">
          <Loader2 className="w-12 h-12 animate-spin text-indigo-500" />
        </div>
      </div>
    );
  }

  const currentStats = stats['global'] || { total_evals: 0, modes: { T2V: 0, I2V: 0, R2V: 0 }, skus: [] };
  const { total_evals, modes: statsModes, skus } = currentStats;

  const familyOf = (id: string) => {
    const k = id.toLowerCase();
    if (k.includes('omni')) return 'Omni';
    if (k.includes('seedance') && k.includes('fast')) return 'Seedance 2.0 Fast';
    if (k.includes('seedance') || k.includes('doubao')) return 'Seedance 2.0';
    if (k.includes('veo')) return 'Veo';
    if (k.includes('kling')) return 'Kling';
    return id;
  };

  const familyCounts: Record<string, number> = {};
  let totalVotesCount = 0;
  skus.forEach((s: any) => {
    const m = familyOf(s.model_id);
    familyCounts[m] = (familyCounts[m] || 0) + s.wins;
    totalVotesCount += s.wins;
  });
  const effectiveTotal = Math.max(totalVotesCount, 1);
  const models = Object.keys(familyCounts).sort();

  // One uniform spider chart across ALL modes (t2v/i2v/r2v collapsed): for each
  // dimension, average a model's available per-mode scores.
  const buildRadarDataAll = () => {
    const sortedSkus = [...skus].sort((a: any, b: any) => (b.win_rate || 0) - (a.win_rate || 0)).slice(0, 3);
    const data: any[] = [];
    DIMENSIONS.forEach(d => {
      const row: any = { subject: d.label };
      sortedSkus.forEach((s: any) => {
        const vals = ['t2v_scores', 'i2v_scores', 'r2v_scores']
          .map((k) => s[k]?.[d.id])
          .filter((v: any) => typeof v === 'number' && v > 0);
        row[s.model_id] = vals.length ? vals.reduce((a: number, b: number) => a + b, 0) / vals.length : 0;
      });
      data.push(row);
    });
    return { data, topModels: sortedSkus.map((s: any) => s.model_id) };
  };

  const { data: radarDataAll, topModels: radarModelsAll } = buildRadarDataAll();
  const CHART_COLORS = ['#818cf8', '#f472b6', '#34d399', '#fbbf24', '#60a5fa'];

  return (
    <div className="min-h-screen bg-[#020408] text-white p-12 pt-8">
      <Nav active="analytics" />
      <div className="max-w-4xl mx-auto space-y-12 animate-in fade-in slide-in-from-bottom-8 duration-700">
        <header className="space-y-6">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-5xl font-black italic tracking-tighter mb-4">BENCHMARK <span className="text-indigo-500">RESULTS</span></h1>
              <p className="text-gray-500 text-lg font-light">Aggregated SxS performance synthesis.</p>
            </div>
            <a href="/video-sxs" className="px-6 py-3 bg-white text-[#020408] rounded-2xl font-black uppercase text-sm shadow-3xl hover:scale-105 transition-all">Back to Arena</a>
          </div>

          {/* Tag Filter Bar — video only (tags are derived from video jobs/prompts) */}
          {modTab === "video" && (
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
          )}
        </header>

        {/* Modality tabs */}
        <div className="flex items-center gap-2">
          {([
            { id: "video", label: "Video", icon: Clapperboard },
            { id: "image", label: "Image", icon: ImageIcon },
            { id: "tts", label: "TTS", icon: AudioLines },
          ] as const).map((t) => {
            const Icon = t.icon;
            const active = modTab === t.id;
            return (
              <button key={t.id} onClick={() => setModTab(t.id)}
                className={`flex items-center gap-2 px-5 py-2.5 rounded-xl text-xs font-black uppercase tracking-widest border transition-all ${active ? "bg-indigo-500/20 border-indigo-500/40 text-indigo-300" : "bg-white/5 border-white/10 text-gray-400 hover:text-white hover:border-white/20"}`}>
                <Icon className="w-4 h-4" /> {t.label}
              </button>
            );
          })}
        </div>

        {modTab === "video" && (
        <>
        <div className={`grid gap-6 mx-auto ${models.length <= 2 ? 'grid-cols-1 sm:grid-cols-2 max-w-2xl' : models.length === 3 ? 'grid-cols-1 sm:grid-cols-3 max-w-4xl' : 'grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 max-w-5xl'}`}>
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

        {/* Win Rate by Tag matrix (models collapsed to families: Omni, Seedance…) */}
        <div className="pt-8 border-t border-white/5 mt-8">
          <TagWinRateMatrix byTag={(currentStats as any).by_tag || []} groupBy={familyOf} />
        </div>

        {/* Spider Chart — one uniform Omni vs Seedance across all modes */}
        <div className="pt-8 border-t border-white/5 mt-8">
          <h3 className="text-xl font-light text-gray-300 mb-6">Dimension Analytics</h3>
          <div className="max-w-2xl mx-auto">
            <div className="bg-[#0b0e14] border border-white/5 rounded-[40px] p-6 relative h-[440px]">
              <h4 className="text-center text-sm font-bold text-gray-400 uppercase tracking-widest mb-4">All Modes (T2V · I2V · R2V)</h4>
              <ResponsiveContainer width="100%" height="100%">
                <RadarChart cx="50%" cy="50%" outerRadius="70%" data={radarDataAll}>
                  <PolarGrid stroke="#334155" />
                  <PolarAngleAxis dataKey="subject" tick={{ fill: '#94a3b8', fontSize: 10 }} />
                  <PolarRadiusAxis angle={30} domain={[0, 5]} tickCount={6} tick={{ fill: '#64748b', fontSize: 10 }} axisLine={false} />
                  <RechartsTooltip contentStyle={{ backgroundColor: '#0f172a', border: '1px solid #334155', borderRadius: '12px' }} itemStyle={{ color: '#e2e8f0' }} />
                  <Legend wrapperStyle={{ fontSize: '11px' }} />
                  {radarModelsAll.map((modelId: string, idx: number) => (
                    <Radar key={modelId} name={modelId} dataKey={modelId} stroke={CHART_COLORS[idx]} fill={CHART_COLORS[idx]} fillOpacity={0.3} />
                  ))}
                </RadarChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>

        <LatencyPanel rows={latency} only={["t2v", "i2v", "r2v"]} />

        {/* Your Recent Evaluations (video) */}
        <div className="pt-10">
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
            {history.length === 0 && <div className="text-gray-600 text-sm italic">No recent evaluations on this device.</div>}
          </div>
        </div>

        {/* Top Evaluators — video only */}
        <div className="pt-10">
          <h3 className="text-xl font-light text-gray-500 mb-6 border-b border-white/5 pb-4 flex items-center gap-3">
            <Crown className="w-5 h-5 text-yellow-400" /> Top Evaluators
            <span className="text-[10px] text-gray-600 uppercase tracking-widest font-black">video</span>
          </h3>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {globalLeaderboard.slice(0, 10).map((user: any, idx: number) => (
              <div key={user.ldap} className="flex items-center justify-between p-5 bg-[#0b0e14] border border-white/5 rounded-2xl">
                <div className="flex items-center gap-4">
                  <span className={`font-black text-xl ${idx === 0 ? 'text-yellow-400' : idx === 1 ? 'text-gray-300' : idx === 2 ? 'text-amber-600' : 'text-gray-600'}`}>#{idx + 1}</span>
                  <span className="font-mono text-indigo-300">{user.ldap}</span>
                </div>
                <div className="flex items-center gap-2 bg-indigo-500/10 px-3 py-1.5 rounded-xl">
                  <span className="font-black text-white">{user.count}</span>
                  <span className="text-[10px] text-gray-500 uppercase tracking-widest">votes</span>
                </div>
              </div>
            ))}
            {globalLeaderboard.length === 0 && (
              <div className="text-gray-600 text-sm italic">No votes yet.</div>
            )}
          </div>
        </div>
        </>
        )}

        {modTab === "image" && (<><ImageResults /><LatencyPanel rows={latency} only={["t2i", "i2i"]} /></>)}

        {modTab === "tts" && (<><TtsResults /><LatencyPanel rows={latency} only={["tts"]} /></>)}

        {/* Cross-modality: human×AI agreement + where Google adds value (page bottom) */}
        <WhereGoogleWins winmap={winmap} agreement={agreement} />
      </div>
    </div>
  );
}

// Friendly labels for language codes; bare modality codes are dropped (they read
// as cryptic "hi / tts" segments).
const LANG_LABEL: Record<string, string> = {
  en: "English", hi: "Hindi", "hi-en": "Hinglish", "hi-bn": "Hindi-Bengali",
  zh: "Chinese", es: "Spanish", ur: "Urdu", ja: "Japanese", ko: "Korean",
  fr: "French", de: "German", ar: "Arabic", pt: "Portuguese",
};
const MODALITY_CODES = new Set(["t2i", "i2i", "tts", "t2v", "i2v", "r2v"]);

function WhereGoogleWins({ winmap, agreement }: { winmap: any; agreement: any }) {
  if (!agreement && !winmap) return null;
  const ag = agreement?.overall;

  // Readable "value areas": leads only, language codes humanized, bare modality
  // codes dropped, deduped by label.
  const seen = new Set<string>();
  const valueAreas = (winmap?.leads || [])
    .map((s: any) => {
      const seg = String(s.segment);
      if (MODALITY_CODES.has(seg)) return null;
      // strip leading emoji/symbols from legacy video tags ("👤 People" -> "People")
      const clean = seg.replace(/^[^\p{L}\p{N}]+/u, "").trim();
      const label = LANG_LABEL[seg] ? `${LANG_LABEL[seg]} (language)` : clean;
      if (!label) return null;
      return { label, win_rate: s.win_rate, n: s.n };
    })
    .filter((x: any) => x && !seen.has(x.label) && seen.add(x.label))
    .slice(0, 6);

  return (
    <section className="bg-[#0b0e14] border border-white/10 rounded-[32px] p-8 mt-2">
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 items-start">
        {/* Human x AI agreement — the trust metric */}
        <div>
          <div className="text-[10px] font-black uppercase tracking-widest text-gray-500 mb-2">Human × AI judge agreement</div>
          <div className="text-5xl font-black text-transparent bg-clip-text bg-gradient-to-br from-indigo-300 to-emerald-300">
            {ag && ag.pct != null ? `${ag.pct}%` : "—"}
          </div>
          <div className="text-[11px] text-gray-500 mt-1">how often the AI judge picks the same winner as human voters {ag ? `· n=${ag.n}` : ""}</div>
          {agreement && (
            <div className="mt-3 flex flex-wrap gap-3 text-[11px] text-gray-500">
              {["image", "video", "tts"].map((m) => agreement[m] && agreement[m].pct != null ? (
                <span key={m}>{m}: <span className="text-gray-300 font-mono">{agreement[m].pct}% (n={agreement[m].n})</span></span>
              ) : null)}
            </div>
          )}
        </div>

        {/* Where Google adds most value — readable, no CI clutter */}
        <div className="md:col-span-2">
          <div className="text-[10px] font-black uppercase tracking-widest text-emerald-400/80 mb-3">Where Google adds most value</div>
          {valueAreas.length ? (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {valueAreas.map((a: any) => (
                <div key={a.label} className="flex items-center justify-between gap-3 bg-[#06080b] border border-emerald-500/15 rounded-xl px-4 py-2.5">
                  <span className="text-sm text-gray-200 truncate">{a.label}</span>
                  <span className="text-xs font-mono text-emerald-300 whitespace-nowrap">{a.win_rate}% <span className="text-gray-600">n={a.n}</span></span>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-gray-600 text-xs italic">Not enough votes yet to call out strong areas (need n≥10 per area).</div>
          )}
          <div className="mt-2 text-[10px] text-gray-600">Areas where Google models win the AI-judged blind comparison; thin samples (n&lt;10) hidden.</div>
        </div>
      </div>
    </section>
  );
}

function LatencyPanel({ rows, only }: { rows: any[]; only: string[] }) {
  const MOD_LABEL: Record<string, string> = { t2v: "Text→Video", i2v: "Image→Video", r2v: "Ref→Video", t2i: "Text→Image", i2i: "Image→Image", tts: "Speech (TTS)" };
  const scoped = (rows || []).filter((r) => only.includes(r.modality));
  const byMod: Record<string, any[]> = {};
  scoped.forEach((r) => { (byMod[r.modality] = byMod[r.modality] || []).push(r); });
  const maxL = Math.max(1, ...scoped.map((r) => r.avg_latency_s || 0));
  const present = only.filter((m) => byMod[m]?.length);
  return (
    <div className="pt-8 border-t border-white/5 mt-8">
      <h3 className="text-xl font-light text-gray-300 mb-2">Latency</h3>
      <p className="text-gray-600 text-xs mb-6">Average successful generation time per model (seconds) for this modality.</p>
      {present.length === 0 ? (
        <div className="text-gray-600 text-sm italic">No latency data yet.</div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {present.map((mod) => (
            <div key={mod} className="bg-[#0b0e14] border border-white/5 rounded-3xl p-6">
              <div className="flex items-center justify-between mb-4">
                <span className="text-sm font-black text-white uppercase tracking-widest">{mod}</span>
                <span className="text-[10px] text-gray-500 uppercase tracking-widest">{MOD_LABEL[mod] || mod}</span>
              </div>
              <div className="space-y-3">
                {byMod[mod].sort((a, b) => (a.avg_latency_s || 0) - (b.avg_latency_s || 0)).map((r) => (
                  <div key={r.model}>
                    <div className="flex items-center justify-between text-xs mb-1">
                      <span className="text-gray-300 font-mono truncate max-w-[60%]">{r.model}</span>
                      <span className="text-white font-bold font-mono">{r.avg_latency_s}s <span className="text-gray-600 font-normal">· n={r.samples}</span></span>
                    </div>
                    <div className="h-2 bg-white/5 rounded-full overflow-hidden">
                      <div className="h-full bg-gradient-to-r from-emerald-500 via-indigo-500 to-pink-500" style={{ width: `${Math.min(100, ((r.avg_latency_s || 0) / maxL) * 100)}%` }}></div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
