'use client';
import { useState, useEffect } from 'react';
import {
  Crown, Filter, Search, X, Loader2,
} from 'lucide-react';
import { Radar, RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis, ResponsiveContainer, Tooltip as RechartsTooltip, Legend } from 'recharts';
import { API_BASE_URL } from '@/lib/api';
import Nav from '@/components/Nav';

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

  // ldap drives only the (omitted) user view; analytics is public → "global".
  const ldap = (typeof window !== "undefined" && localStorage.getItem("project_pulse_ldap")) || "global";

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
    fetch(`${API_BASE_URL}/api/tags`)
      .then(res => res.json())
      .then(data => { if (data?.status === "success") setAvailableTags(data.tags); })
      .catch(() => {});
    fetch(`${API_BASE_URL}/api/sxs/leaderboard/users`)
      .then(res => res.json())
      .then(data => { if (data?.status === "success" && data.leaderboard) setGlobalLeaderboard(data.leaderboard); })
      .catch(() => {});
    try {
      const savedHistory = localStorage.getItem('project_pulse_history');
      if (savedHistory) setHistory(JSON.parse(savedHistory));
    } catch { /* ignore */ }
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

  if (isLoading || !stats) {
    return (
      <div className="min-h-screen bg-[#020408] text-white p-12 flex items-center justify-center">
        <Nav active="analytics" />
        <Loader2 className="w-12 h-12 animate-spin text-indigo-500" />
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
  const CHART_COLORS = ['#818cf8', '#f472b6', '#34d399', '#fbbf24', '#60a5fa'];

  return (
    <div className="min-h-screen bg-[#020408] text-white p-12 pt-32">
      <Nav active="analytics" />
      <div className="max-w-4xl mx-auto space-y-12 animate-in fade-in slide-in-from-bottom-8 duration-700">
        <header className="space-y-6">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-5xl font-black italic tracking-tighter mb-4">BENCHMARK <span className="text-indigo-500">RESULTS</span></h1>
              <p className="text-gray-500 text-lg font-light">Aggregated SxS performance synthesis.</p>
            </div>
            <a href="/human-eval" className="px-6 py-3 bg-white text-[#020408] rounded-2xl font-black uppercase text-sm shadow-3xl hover:scale-105 transition-all">Back to Arena</a>
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
                    <PolarRadiusAxis angle={30} domain={[0, 5]} tickCount={6} tick={{ fill: '#64748b', fontSize: 10 }} axisLine={false} />
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
