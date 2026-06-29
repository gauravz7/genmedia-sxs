"use client";
import { useState, useEffect } from "react";
import { Crown } from "lucide-react";
import { Radar, RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis, ResponsiveContainer, Tooltip as RechartsTooltip, Legend } from "recharts";
import { API_BASE_URL } from "@/lib/api";

// ===================================================================
// Image SxS results — rich, self-contained view.
//   • header (total votes)
//   • per-engine win-rate cards
//   • per-metric radar chart (recharts, mirrors the video tab)
//   • model leaderboard table + per-matchup breakdown
//   • Top Evaluators leaderboard
// Data: /api/image/stats (global.skus, global.matchups) and
//       /api/image/leaderboard/users.
// ===================================================================

const IMAGE_METRICS = [
  { key: "prompt_following", label: "Prompt Following" },
  { key: "aesthetic", label: "Aesthetic" },
  { key: "detail", label: "Detail / Sharpness" },
  { key: "artifact_free", label: "Artifact-Free" },
  { key: "edit_fidelity", label: "Edit Fidelity" },
];
const METRIC_KEYS = IMAGE_METRICS.map((m) => m.key);
const METRIC_LABELS: Record<string, string> = Object.fromEntries(IMAGE_METRICS.map((m) => [m.key, m.label]));
const CHART_COLORS = ["#818cf8", "#f472b6", "#34d399", "#fbbf24", "#60a5fa"];

// Clean display names for image engines (raw id -> label).
const prettyEngine = (id: string = ""): string => {
  const k = id.toLowerCase();
  const tier = k.includes("-high") ? " (high)" : k.includes("-medium") ? " (medium)" : k.includes("-low") ? " (low)" : "";
  if (k.includes("mai-image")) return "MAI-Image-2.5";
  if (k.includes("gpt-image-2")) return `GPT-image-2${tier}`;
  if (k.includes("gpt-image")) return `GPT-image-1${tier}`;
  if (k.includes("flash-lite-image")) return "Gemini 3.1 Flash-Lite Image";
  if (k.includes("flash-image")) return "Gemini 3.1 Flash Image";
  if (k.includes("pro-image")) return "Gemini 3 Pro Image";
  if (k.includes("instant-ramen")) return "Instant Ramen";
  return id;
};

export default function ImageResults() {
  const [stats, setStats] = useState<any>(null);
  const [users, setUsers] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      fetch(`${API_BASE_URL}/api/image/stats`).then((r) => r.json()).catch(() => null),
      fetch(`${API_BASE_URL}/api/image/leaderboard/users`).then((r) => r.json()).catch(() => null),
    ]).then(([s, u]) => {
      setStats(s);
      setUsers(u?.leaderboard || []);
      setLoading(false);
    });
  }, []);

  if (loading) return <div className="py-32 flex justify-center"><div className="w-10 h-10 rounded-full border-2 border-indigo-500/30 border-t-indigo-500 animate-spin"></div></div>;

  const g = stats?.global;
  const skus: any[] = g?.skus || [];
  const matchups: any[] = g?.matchups || [];
  const totalEvals = g?.total_evals ?? 0;

  // Radar over the image metrics, plotting the top 2-3 engines by win-rate
  // that actually have per-metric scores.
  const radarModels = skus.filter((s) => s.scores && Object.keys(s.scores).length > 0).slice(0, 3);
  const radarData = IMAGE_METRICS.map((m) => {
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
      </div>

      {/* Win-rate cards per engine */}
      <div className={`grid gap-6 mx-auto ${skus.length <= 2 ? "grid-cols-1 sm:grid-cols-2 max-w-2xl" : skus.length === 3 ? "grid-cols-1 sm:grid-cols-3 max-w-4xl" : "grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 max-w-5xl"}`}>
        {skus.map((s) => (
          <div key={s.model_id} className="bg-[#0b0e14] border border-white/5 rounded-[40px] p-8 text-center space-y-4">
            <div className="text-xs font-black text-gray-500 uppercase tracking-[0.4em] truncate">{prettyEngine(s.model_id)}</div>
            <div className="text-6xl font-black text-transparent bg-clip-text bg-gradient-to-br from-white to-gray-500">{s.win_rate}%</div>
            <div className="text-[10px] font-bold text-indigo-400 uppercase tracking-widest">{s.wins}/{s.total} won</div>
            {s.latency_ms ? <div className="text-[10px] text-gray-600 uppercase tracking-widest">avg {s.latency_ms}ms</div> : null}
          </div>
        ))}
        {skus.length === 0 && <div className="text-gray-600 text-sm italic">No votes yet.</div>}
      </div>

      {/* Per-metric radar */}
      {radarModels.length > 0 && (
        <div className="pt-8 border-t border-white/5">
          <h3 className="text-xl font-light text-gray-300 mb-6">Dimension Analytics</h3>
          <div className="bg-[#0b0e14] border border-white/5 rounded-[40px] p-6 relative h-[400px]">
            <h4 className="text-center text-sm font-bold text-gray-400 uppercase tracking-widest mb-4">Per-Metric Scores (top engines)</h4>
            <ResponsiveContainer width="100%" height="100%">
              <RadarChart cx="50%" cy="50%" outerRadius="70%" data={radarData}>
                <PolarGrid stroke="#334155" />
                <PolarAngleAxis dataKey="subject" tick={{ fill: "#94a3b8", fontSize: 10 }} />
                <PolarRadiusAxis angle={30} domain={[0, 5]} tickCount={6} tick={{ fill: "#64748b", fontSize: 10 }} axisLine={false} />
                <RechartsTooltip contentStyle={{ backgroundColor: "#0f172a", border: "1px solid #334155", borderRadius: "12px" }} itemStyle={{ color: "#e2e8f0" }} />
                <Legend wrapperStyle={{ fontSize: "10px" }} />
                {radarModels.map((s, idx) => (
                  <Radar key={s.model_id} name={prettyEngine(s.model_id)} dataKey={s.model_id} stroke={CHART_COLORS[idx]} fill={CHART_COLORS[idx]} fillOpacity={0.3} />
                ))}
              </RadarChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* Model leaderboard table */}
      <section className="bg-[#0b0e14] border border-white/10 rounded-[32px] p-8">
        <h2 className="text-sm font-light text-white mb-6 flex items-center gap-3"><span className="w-2 h-6 bg-emerald-500 rounded-full"></span> Model Leaderboard</h2>
        {skus.length === 0 ? <p className="text-gray-600 text-sm">No votes yet.</p> : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-[10px] font-black uppercase tracking-widest text-gray-500 border-b border-white/10">
                  <th className="text-left py-3 px-3">Model</th>
                  <th className="text-right py-3 px-3">Win Rate</th>
                  <th className="text-right py-3 px-3">Wins / Total</th>
                  <th className="text-right py-3 px-3">Latency</th>
                  {METRIC_KEYS.map((m) => <th key={m} className="text-right py-3 px-3">{METRIC_LABELS[m]}</th>)}
                </tr>
              </thead>
              <tbody>
                {skus.map((s: any) => (
                  <tr key={s.model_id} className="border-b border-white/5">
                    <td className="py-3 px-3 text-indigo-300 font-mono text-xs">{prettyEngine(s.model_id)}</td>
                    <td className="py-3 px-3 text-right text-emerald-300 font-black">{s.win_rate}%</td>
                    <td className="py-3 px-3 text-right text-gray-400 font-mono">{s.wins}/{s.total}</td>
                    <td className="py-3 px-3 text-right text-gray-500 font-mono">{s.latency_ms ? `${s.latency_ms}ms` : "—"}</td>
                    {METRIC_KEYS.map((m) => <td key={m} className="py-3 px-3 text-right text-gray-300 font-mono">{s.scores?.[m] ?? "—"}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Per-matchup breakdown */}
      <section className="bg-[#0b0e14] border border-white/10 rounded-[32px] p-8">
        <h2 className="text-sm font-light text-white mb-6 flex items-center gap-3"><span className="w-2 h-6 bg-purple-500 rounded-full"></span> Per-Matchup Win Rates</h2>
        {matchups.length === 0 ? <p className="text-gray-600 text-sm">No votes yet.</p> : (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {matchups.map((m: any) => (
              <div key={m.matchup} className="bg-[#06080b] border border-white/10 rounded-2xl p-4">
                <div className="text-[10px] font-mono text-gray-500 mb-3 break-all">{m.matchup} · {m.votes} votes</div>
                {(m.models || []).map((md: any) => (
                  <div key={md.model_id} className="flex items-center justify-between text-xs py-1">
                    <span className="text-gray-300 font-mono truncate mr-2">{md.model_id}</span>
                    <span className="text-emerald-300 font-black">{md.win_rate}% <span className="text-gray-600 font-normal">({md.wins}/{md.total})</span></span>
                  </div>
                ))}
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Top Evaluators (image voters) */}
      <div>
        <h3 className="text-xl font-light text-gray-500 mb-6 border-b border-white/5 pb-4 flex items-center gap-3">
          <Crown className="w-5 h-5 text-yellow-400" /> Top Evaluators
          <span className="text-[10px] text-gray-600 uppercase tracking-widest font-black">image</span>
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
