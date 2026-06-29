"use client";
import { useEffect, useState } from "react";
import { BarChart3, Crown } from "lucide-react";
import { API_BASE_URL } from "@/lib/api";

// ===================================================================
// VoteProgress — compact HUD shared across the rating arenas.
// Fetches the authoritative vote count for an ldap and renders
// @<ldap>, <count> VOTES, a progress bar, and an Analytics unlock
// link once count >= required (otherwise a dimmed lock chip).
// Re-fetches whenever `refreshKey` changes so it updates per vote.
// ===================================================================

interface VoteCount {
  count: number;
  required: number;
  unlocked: boolean;
}

export default function VoteProgress({ ldap, refreshKey }: { ldap: string; refreshKey?: number }) {
  const [data, setData] = useState<VoteCount>({ count: 0, required: 10, unlocked: false });

  useEffect(() => {
    if (!ldap) return;
    let cancelled = false;
    fetch(`${API_BASE_URL}/api/votes/count?ldap=${encodeURIComponent(ldap)}`)
      .then((res) => res.json())
      .then((d) => {
        if (cancelled) return;
        setData({ count: d?.count ?? 0, required: d?.required ?? 10, unlocked: !!d?.unlocked });
      })
      .catch(() => { /* non-fatal */ });
    return () => { cancelled = true; };
  }, [ldap, refreshKey]);

  const { count, required } = data;
  const pct = Math.min((count / (required || 10)) * 100, 100);

  return (
    <div className="flex items-center gap-3">
      <div className="flex flex-col items-end mr-1">
        <span className="text-[10px] font-bold text-gray-500 uppercase tracking-widest">@{ldap}</span>
        <span className="text-xs font-black text-indigo-400 font-mono tracking-tighter">{count} VOTES</span>
      </div>
      <div className="w-48 h-2 bg-white/5 rounded-full overflow-hidden border border-white/10 shadow-inner">
        <div className="h-full bg-gradient-to-r from-indigo-500 via-purple-500 to-pink-500 transition-all duration-1000 ease-out shadow-[0_0_10px_rgba(168,85,247,0.5)]" style={{ width: `${pct}%` }}></div>
      </div>
      {count >= required ? (
        <a href="/analytics" className="px-4 py-2 ml-2 rounded-xl bg-indigo-500/20 border border-indigo-500/40 flex items-center gap-2 hover:bg-indigo-500/40 transition-all font-bold text-xs uppercase text-indigo-300 shadow-[0_0_15px_rgba(99,102,241,0.3)]">
          <BarChart3 className="w-4 h-4 text-indigo-400" /> Analytics
        </a>
      ) : (
        <div className="w-8 h-8 rounded-full bg-white/5 border border-white/10 flex items-center justify-center opacity-50">
          <Crown className="w-4 h-4 text-gray-500" />
        </div>
      )}
    </div>
  );
}
