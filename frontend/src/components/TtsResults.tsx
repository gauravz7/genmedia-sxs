"use client";
import { useState, useEffect } from "react";
import { Crown } from "lucide-react";
import { Radar, RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis, ResponsiveContainer, Tooltip as RechartsTooltip, Legend } from "recharts";
import { API_BASE_URL } from "@/lib/api";

// ===================================================================
// TTS results — rich, self-contained view (Gemini vs ElevenLabs).
//   • header (total votes)
//   • per-engine win-rate cards
//   • per-metric radar chart (recharts, mirrors the video tab)
//   • per-engine metric breakdown
//   • Top Evaluators leaderboard
// Data: /api/tts/stats (global.skus — no matchups) and
//       /api/tts/leaderboard/users.
// ===================================================================

const METRICS = [
  { key: "naturalness", label: "Naturalness" },
  { key: "style_adherence", label: "Style Adherence" },
  { key: "expressiveness", label: "Expressiveness" },
  { key: "pacing", label: "Pacing" },
  { key: "pronunciation_clarity", label: "Pronunciation" },
];
const CHART_COLORS = ["#818cf8", "#f472b6", "#34d399", "#fbbf24", "#60a5fa"];

export default function TtsResults() {
  const [stats, setStats] = useState<any>(null);
  const [users, setUsers] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [language, setLanguage] = useState("");
  const [availableLanguages, setAvailableLanguages] = useState<string[]>([]);

  // Initial load: stats (global), user leaderboard, and the language filter list.
  useEffect(() => {
    Promise.all([
      fetch(`${API_BASE_URL}/api/tts/stats`).then((r) => r.json()).catch(() => null),
      fetch(`${API_BASE_URL}/api/tts/leaderboard/users`).then((r) => r.json()).catch(() => null),
      fetch(`${API_BASE_URL}/api/tts/languages`).then((r) => r.json()).catch(() => null),
    ]).then(([s, u, l]) => {
      setStats(s?.global || null);
      setUsers(u?.leaderboard || []);
      if (Array.isArray(l?.languages)) setAvailableLanguages(l.languages);
      setLoading(false);
    });
  }, []);

  // Refetch stats whenever the language filter changes.
  useEffect(() => {
    const qs = language ? `?language=${encodeURIComponent(language)}` : "";
    fetch(`${API_BASE_URL}/api/tts/stats${qs}`)
      .then((r) => r.json())
      .catch(() => null)
      .then((s) => setStats(s?.global || null));
  }, [language]);

  if (loading) return (
    <div className="py-24 flex flex-col items-center justify-center text-gray-500 gap-4 bg-white/[0.02] border border-white/5 rounded-[40px]">
      <div className="w-10 h-10 rounded-full border-2 border-indigo-500/30 border-t-indigo-500 animate-spin"></div>
      <p className="font-light tracking-widest uppercase text-xs">Loading results…</p>
    </div>
  );

  const skus: any[] = stats?.skus || [];
  const totalEvals = stats?.total_evals ?? 0;

  // Radar over the TTS metrics, plotting engines that have per-metric scores.
  const radarModels = skus.filter((s) => s.scores && Object.keys(s.scores).length > 0).slice(0, 3);
  const radarData = METRICS.map((m) => {
    const row: any = { subject: m.label };
    radarModels.forEach((s) => { row[s.model_id] = s.scores?.[m.key] ?? 0; });
    return row;
  });

  return (
    <div className="space-y-8">
      {/* Header row */}
      <div className="flex flex-wrap items-center gap-3">
        <span className="text-xs font-black uppercase tracking-widest text-gray-500">{totalEvals} total human votes</span>
        <span className="text-gray-700">·</span>
        <span className="text-xs font-black uppercase tracking-widest text-gray-500">{skus.length} engine{skus.length !== 1 ? "s" : ""}</span>
        <span className="text-gray-700">·</span>
        <select
          value={language}
          onChange={(e) => setLanguage(e.target.value)}
          className={`px-3 py-2 rounded-xl text-xs font-bold uppercase tracking-widest border transition-all focus:outline-none focus:ring-2 focus:ring-indigo-500/50 ${language ? "bg-indigo-500/20 border-indigo-500/40 text-indigo-300" : "bg-white/5 border-white/10 text-gray-500 hover:text-white"}`}
        >
          <option value="">All languages</option>
          {availableLanguages.map((code) => (
            <option key={code} value={code}>{code}</option>
          ))}
        </select>
      </div>

      {/* Win-rate cards per engine */}
      <div className={`grid gap-6 mx-auto ${skus.length <= 2 ? "grid-cols-1 sm:grid-cols-2 max-w-2xl" : "grid-cols-1 sm:grid-cols-3 max-w-4xl"}`}>
        {skus.map((s) => (
          <div key={s.model_id} className="bg-[#0b0e14] border border-white/5 rounded-[40px] p-8 text-center space-y-4">
            <div className="text-xs font-black text-gray-500 uppercase tracking-[0.4em] truncate">{s.model_id}</div>
            <div className="text-6xl font-black text-transparent bg-clip-text bg-gradient-to-br from-white to-gray-500">{s.win_rate}%</div>
            <div className="text-[10px] font-bold text-indigo-400 uppercase tracking-widest">{s.wins}/{s.total} won</div>
            {s.latency_ms ? <div className="text-[10px] text-gray-600 uppercase tracking-widest">avg {s.latency_ms}ms</div> : null}
          </div>
        ))}
        {skus.length === 0 && <div className="text-gray-600 text-sm italic">No votes recorded yet.</div>}
      </div>

      {/* Per-metric radar */}
      {radarModels.length > 0 && (
        <div className="pt-8 border-t border-white/5">
          <h3 className="text-xl font-light text-gray-300 mb-6">Dimension Analytics</h3>
          <div className="bg-[#0b0e14] border border-white/5 rounded-[40px] p-6 relative h-[400px]">
            <h4 className="text-center text-sm font-bold text-gray-400 uppercase tracking-widest mb-4">Per-Metric Scores</h4>
            <ResponsiveContainer width="100%" height="100%">
              <RadarChart cx="50%" cy="50%" outerRadius="70%" data={radarData}>
                <PolarGrid stroke="#334155" />
                <PolarAngleAxis dataKey="subject" tick={{ fill: "#94a3b8", fontSize: 10 }} />
                <PolarRadiusAxis angle={30} domain={[0, 5]} tickCount={6} tick={{ fill: "#64748b", fontSize: 10 }} axisLine={false} />
                <RechartsTooltip contentStyle={{ backgroundColor: "#0f172a", border: "1px solid #334155", borderRadius: "12px" }} itemStyle={{ color: "#e2e8f0" }} />
                <Legend wrapperStyle={{ fontSize: "10px" }} />
                {radarModels.map((s, idx) => (
                  <Radar key={s.model_id} name={s.model_id} dataKey={s.model_id} stroke={CHART_COLORS[idx]} fill={CHART_COLORS[idx]} fillOpacity={0.3} />
                ))}
              </RadarChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* Per-engine metric breakdown */}
      <section className="bg-[#0b0e14] border border-white/10 rounded-[40px] p-8 shadow-3xl space-y-6">
        <div className="flex items-center justify-between">
          <h2 className="text-xl font-light text-white flex items-center gap-3"><span className="w-2 h-8 bg-emerald-500 rounded-full"></span> Engine Win Rates</h2>
          <span className="text-[11px] font-black uppercase tracking-widest text-gray-500">{totalEvals} votes</span>
        </div>
        {skus.length === 0 ? (
          <p className="text-gray-500 text-sm">No votes recorded yet.</p>
        ) : (
          <div className="space-y-5">
            {skus.map((s) => (
              <div key={s.model_id} className="bg-[#06080b] border border-white/5 rounded-3xl p-6">
                <div className="flex items-center justify-between mb-3">
                  <span className="font-mono text-sm text-indigo-300">{s.model_id}</span>
                  <span className="text-2xl font-black text-emerald-400">{s.win_rate}%</span>
                </div>
                <div className="w-full h-2 bg-white/5 rounded-full overflow-hidden mb-3">
                  <div className="h-full bg-gradient-to-r from-indigo-500 to-emerald-500 rounded-full" style={{ width: `${s.win_rate}%` }}></div>
                </div>
                <div className="flex flex-wrap gap-4 text-[11px] text-gray-500 font-mono mb-3">
                  <span>{s.wins}/{s.total} wins</span>
                  {s.latency_ms ? <span>avg {s.latency_ms}ms</span> : null}
                </div>
                {s.scores && Object.keys(s.scores).length > 0 && (
                  <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
                    {METRICS.map((m) => (
                      <div key={m.key} className="bg-white/[0.02] border border-white/5 rounded-xl px-3 py-2 text-center">
                        <div className="text-lg font-black text-white">{s.scores[m.key] ?? "—"}</div>
                        <div className="text-[9px] font-black uppercase tracking-widest text-gray-600 mt-0.5">{m.label}</div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Top Evaluators (tts voters) */}
      <div>
        <h3 className="text-xl font-light text-gray-500 mb-6 border-b border-white/5 pb-4 flex items-center gap-3">
          <Crown className="w-5 h-5 text-yellow-400" /> Top Evaluators
          <span className="text-[10px] text-gray-600 uppercase tracking-widest font-black">tts</span>
        </h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {users.slice(0, 10).map((user: any, idx: number) => (
            <div key={user.ldap} className="flex items-center justify-between p-5 bg-[#0b0e14] border border-white/5 rounded-2xl">
              <div className="flex items-center gap-4">
                <span className={`font-black text-xl ${idx === 0 ? "text-yellow-400" : idx === 1 ? "text-gray-300" : idx === 2 ? "text-amber-600" : "text-gray-600"}`}>#{idx + 1}</span>
                <span className="font-mono text-indigo-300">{user.ldap}</span>
              </div>
              <div className="flex items-center gap-2 bg-indigo-500/10 px-3 py-1.5 rounded-xl">
                <span className="font-black text-white">{user.count}</span>
                <span className="text-[10px] text-gray-500 uppercase tracking-widest">votes</span>
              </div>
            </div>
          ))}
          {users.length === 0 && <div className="text-gray-600 text-sm italic">No votes yet.</div>}
        </div>
      </div>
    </div>
  );
}
