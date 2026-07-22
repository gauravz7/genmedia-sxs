"use client";
import { useEffect, useState } from "react";
import { Crown, Trophy, ShieldAlert, Loader2, Clapperboard, ImageIcon, AudioLines } from "lucide-react";
import { API_BASE_URL } from "@/lib/api";
import Nav from "@/components/Nav";

type Row = { ldap: string; count: number; total: number; video: number; image: number; tts: number };
type Excluded = { ldap: string; total: number; dominant_side: string; dominant_pct: number };

const TABS = [
  { key: "overall", label: "Overall", icon: Trophy, field: "total" as const },
  { key: "video", label: "Video", icon: Clapperboard, field: "video" as const },
  { key: "image", label: "Image", icon: ImageIcon, field: "image" as const },
  { key: "tts", label: "TTS", icon: AudioLines, field: "tts" as const },
];

const medal = (i: number) =>
  i === 0 ? "text-yellow-400" : i === 1 ? "text-gray-300" : i === 2 ? "text-amber-600" : "text-gray-600";

export default function Leaderboard() {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<string>("overall");

  useEffect(() => {
    fetch(`${API_BASE_URL}/api/leaderboard`)
      .then((r) => r.json())
      .then((d) => { setData(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="min-h-screen bg-[#020408] text-white">
        <Nav active="leaderboard" />
        <div className="flex items-center justify-center py-40"><Loader2 className="w-12 h-12 animate-spin text-indigo-500" /></div>
      </div>
    );
  }

  const rows: Row[] =
    tab === "overall" ? data?.overall || [] : data?.by_modality?.[tab] || [];
  const excluded: Excluded[] = data?.excluded || [];
  const rules = data?.rules || { min_decisive: 5, one_sided_pct: 90 };

  return (
    <div className="min-h-screen bg-[#020408] text-white p-8 md:p-12 pt-8">
      <Nav active="leaderboard" />
      <div className="max-w-4xl mx-auto space-y-10 animate-in fade-in slide-in-from-bottom-8 duration-700">
        <header className="space-y-3">
          <h1 className="text-5xl font-black italic tracking-tighter flex items-center gap-4">
            <Crown className="w-10 h-10 text-yellow-400" /> LEADER<span className="text-indigo-500">BOARD</span>
          </h1>
          <p className="text-gray-500 text-lg font-light">
            Top human evaluators — overall and by modality. Blind one-sided voters are excluded.
          </p>
        </header>

        {/* Modality tabs */}
        <div className="flex items-center gap-2 flex-wrap">
          {TABS.map((t) => {
            const Icon = t.icon;
            const active = tab === t.key;
            const n = (t.key === "overall" ? data?.overall : data?.by_modality?.[t.key])?.length || 0;
            return (
              <button key={t.key} onClick={() => setTab(t.key)}
                className={`flex items-center gap-2 px-5 py-2.5 rounded-xl text-xs font-black uppercase tracking-widest border transition-all ${active ? "bg-indigo-500/20 border-indigo-500/40 text-indigo-300" : "bg-white/5 border-white/10 text-gray-400 hover:text-white hover:border-white/20"}`}>
                <Icon className="w-4 h-4" /> {t.label}
                <span className={`font-mono ${active ? "text-indigo-100" : "text-gray-600"}`}>{n}</span>
              </button>
            );
          })}
        </div>

        {/* Leaderboard table */}
        <section className="bg-[#0b0e14] border border-white/10 rounded-[32px] p-6 md:p-8">
          {rows.length === 0 ? (
            <p className="text-gray-600 text-sm italic py-8 text-center">No qualifying voters yet.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-[10px] font-black uppercase tracking-widest text-gray-500 border-b border-white/10">
                    <th className="text-left py-3 px-3">#</th>
                    <th className="text-left py-3 px-3">Evaluator</th>
                    <th className="text-right py-3 px-3">{tab === "overall" ? "Total votes" : `${tab} votes`}</th>
                    <th className="text-right py-3 px-3 hidden sm:table-cell">Video</th>
                    <th className="text-right py-3 px-3 hidden sm:table-cell">Image</th>
                    <th className="text-right py-3 px-3 hidden sm:table-cell">TTS</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r, i) => (
                    <tr key={r.ldap} className="border-b border-white/5 hover:bg-white/[0.02]">
                      <td className={`py-3 px-3 font-black text-lg ${medal(i)}`}>#{i + 1}</td>
                      <td className="py-3 px-3 font-mono text-indigo-300">{r.ldap}</td>
                      <td className="py-3 px-3 text-right font-black text-white text-base">{r.count}</td>
                      <td className="py-3 px-3 text-right text-gray-500 font-mono hidden sm:table-cell">{r.video}</td>
                      <td className="py-3 px-3 text-right text-gray-500 font-mono hidden sm:table-cell">{r.image}</td>
                      <td className="py-3 px-3 text-right text-gray-500 font-mono hidden sm:table-cell">{r.tts}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        {/* Excluded (blind one-sided) voters */}
        <section className="bg-[#0b0e14] border border-amber-500/20 rounded-[32px] p-6 md:p-8">
          <h2 className="text-sm font-light text-white mb-2 flex items-center gap-3">
            <ShieldAlert className="w-5 h-5 text-amber-400" /> Excluded — Suspected Blind Voting
          </h2>
          <p className="text-gray-600 text-xs mb-5">
            A/B labels are randomized per case, so genuine voting trends ~50/50. Voters with
            ≥{rules.min_decisive} decisive votes that are ≥{rules.one_sided_pct}% on one side are
            removed from the leaderboard.
          </p>
          {excluded.length === 0 ? (
            <p className="text-gray-600 text-sm italic">None detected — all voters show balanced A/B choices. ✅</p>
          ) : (
            <div className="flex flex-wrap gap-3">
              {excluded.map((e) => (
                <div key={e.ldap} className="flex items-center gap-3 bg-amber-500/5 border border-amber-500/20 rounded-2xl px-4 py-2">
                  <span className="font-mono text-amber-200/90">{e.ldap}</span>
                  <span className="text-[10px] text-gray-500 uppercase tracking-widest">{e.total} votes · {e.dominant_pct}% {e.dominant_side}</span>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
