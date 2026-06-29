"use client";
import { useState, useEffect } from "react";
import { API_BASE_URL } from "@/lib/api";

// ===================================================================
// Image SxS results — win-rates per matchup + per-metric leaderboard.
// Extracted from image-sxs/page.tsx ResultsPanel; rendered inside the
// unlocked Analytics view.
// ===================================================================

const T2I_METRICS = ["prompt_following", "aesthetic", "detail", "artifact_free"];
const I2I_EXTRA = "edit_fidelity";
const METRIC_LABELS: Record<string, string> = {
  prompt_following: "Prompt Following",
  aesthetic: "Aesthetic",
  detail: "Detail / Sharpness",
  artifact_free: "Artifact-Free",
  edit_fidelity: "Edit Fidelity",
};

export default function ImageResults() {
  const [stats, setStats] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch(`${API_BASE_URL}/api/image/stats`)
      .then((r) => r.json())
      .then((d) => setStats(d))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="py-32 flex justify-center"><div className="w-10 h-10 rounded-full border-2 border-indigo-500/30 border-t-indigo-500 animate-spin"></div></div>;

  const g = stats?.global;
  const skus = g?.skus || [];
  const matchups = g?.matchups || [];

  return (
    <div className="space-y-8">
      <div className="text-xs font-black uppercase tracking-widest text-gray-500">{g?.total_evals ?? 0} total human votes</div>

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
                  {[...T2I_METRICS, I2I_EXTRA].map((m) => <th key={m} className="text-right py-3 px-3">{METRIC_LABELS[m]}</th>)}
                </tr>
              </thead>
              <tbody>
                {skus.map((s: any) => (
                  <tr key={s.model_id} className="border-b border-white/5">
                    <td className="py-3 px-3 text-indigo-300 font-mono text-xs">{s.model_id}</td>
                    <td className="py-3 px-3 text-right text-emerald-300 font-black">{s.win_rate}%</td>
                    <td className="py-3 px-3 text-right text-gray-400 font-mono">{s.wins}/{s.total}</td>
                    <td className="py-3 px-3 text-right text-gray-500 font-mono">{s.latency_ms ? `${s.latency_ms}ms` : "—"}</td>
                    {[...T2I_METRICS, I2I_EXTRA].map((m) => <td key={m} className="py-3 px-3 text-right text-gray-300 font-mono">{s.scores?.[m] ?? "—"}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

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
    </div>
  );
}
