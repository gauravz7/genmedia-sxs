"use client";
import { useState, useEffect } from "react";
import { API_BASE_URL } from "@/lib/api";

// ===================================================================
// TTS results — Gemini-vs-ElevenLabs win-rates + per-metric.
// Extracted from tts-sxs/page.tsx ResultsPanel; rendered inside the
// unlocked Analytics view.
// ===================================================================

const METRICS = [
  { key: "naturalness", label: "Naturalness" },
  { key: "style_adherence", label: "Style Adherence" },
  { key: "expressiveness", label: "Expressiveness" },
  { key: "pacing", label: "Pacing" },
  { key: "pronunciation_clarity", label: "Pronunciation" },
];

export default function TtsResults() {
  const [stats, setStats] = useState<any>(null);
  const [users, setUsers] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      fetch(`${API_BASE_URL}/api/tts/stats`).then((r) => r.json()).catch(() => null),
      fetch(`${API_BASE_URL}/api/tts/leaderboard/users`).then((r) => r.json()).catch(() => null),
    ]).then(([s, u]) => {
      setStats(s?.global || null);
      setUsers(u?.leaderboard || []);
      setLoading(false);
    });
  }, []);

  if (loading) return (
    <div className="py-24 flex flex-col items-center justify-center text-gray-500 gap-4 bg-white/[0.02] border border-white/5 rounded-[40px]">
      <div className="w-10 h-10 rounded-full border-2 border-indigo-500/30 border-t-indigo-500 animate-spin"></div>
      <p className="font-light tracking-widest uppercase text-xs">Loading results…</p>
    </div>
  );

  const skus: any[] = stats?.skus || [];
  return (
    <div className="space-y-8">
      <section className="bg-[#0b0e14] border border-white/10 rounded-[40px] p-8 shadow-3xl space-y-6">
        <div className="flex items-center justify-between">
          <h2 className="text-xl font-light text-white flex items-center gap-3"><span className="w-2 h-8 bg-emerald-500 rounded-full"></span> Engine Win Rates</h2>
          <span className="text-[11px] font-black uppercase tracking-widest text-gray-500">{stats?.total_evals ?? 0} votes</span>
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

      {users.length > 0 && (
        <section className="bg-[#0b0e14] border border-white/10 rounded-[40px] p-8 shadow-3xl">
          <h2 className="text-xl font-light text-white flex items-center gap-3 mb-5"><span className="w-2 h-8 bg-indigo-500 rounded-full"></span> Top Voters</h2>
          <div className="space-y-2">
            {users.map((u, i) => (
              <div key={u.ldap} className="flex items-center justify-between bg-[#06080b] border border-white/5 rounded-xl px-4 py-2.5">
                <span className="text-sm text-gray-300"><span className="text-gray-600 font-mono mr-3">#{i + 1}</span>{u.ldap}</span>
                <span className="font-mono text-indigo-300 text-sm">{u.count}</span>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
