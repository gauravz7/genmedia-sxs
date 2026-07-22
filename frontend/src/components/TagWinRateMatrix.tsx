"use client";
import { useMemo, useState } from "react";

// ===================================================================
// Win Rate by Tag — a tag × model matrix so you can see where each model
// over/under-performs by category. Cells show win-rate % and the raw
// (wins/total) count, color-scaled green (high) → red (low).
//
// `byTag` shape (from /api/{image,sxs,tts}/stats -> global.by_tag):
//   [{ tag, votes, models: [{ model_id, win_rate, wins, total }] }]
// ===================================================================

type ModelStat = { model_id: string; win_rate: number; wins: number; total: number };
type TagRow = { tag: string; votes: number; models: ModelStat[] };

// Green (high) → amber (mid) → red (low) heatmap color for a win rate.
function cellColor(rate: number): { bg: string; fg: string } {
  const hue = Math.max(0, Math.min(120, (rate / 100) * 120)); // 0=red, 120=green
  return { bg: `hsl(${hue}, 65%, 22%)`, fg: `hsl(${hue}, 85%, 82%)` };
}

export default function TagWinRateMatrix({
  byTag,
  prettyName = (s) => s,
  minVotes = 1,
  groupBy,
}: {
  byTag: TagRow[];
  prettyName?: (id: string) => string;
  minVotes?: number;
  // Optional: collapse engine variants into a family/group (e.g. Omni, Seedance)
  // by summing wins/total per group so columns match the rest of the tab.
  groupBy?: (modelId: string) => string;
}) {
  const [showThin, setShowThin] = useState(false);

  // Optionally collapse each row's per-engine stats into grouped columns.
  const data: TagRow[] = useMemo(() => {
    if (!groupBy) return byTag || [];
    return (byTag || []).map((row) => {
      const agg: Record<string, ModelStat> = {};
      for (const m of row.models) {
        const g = groupBy(m.model_id);
        const cur = agg[g] || { model_id: g, wins: 0, total: 0, win_rate: 0 };
        cur.wins += m.wins;
        cur.total += m.total;
        agg[g] = cur;
      }
      const models = Object.values(agg).map((m) => ({
        ...m,
        win_rate: m.total ? Math.round((m.wins / m.total) * 1000) / 10 : 0,
      }));
      models.sort((a, b) => b.win_rate - a.win_rate);
      return { ...row, models };
    });
  }, [byTag, groupBy]);

  // Column order = models ranked by total appearances across all tags.
  const models = useMemo(() => {
    const totals: Record<string, number> = {};
    for (const row of data) {
      for (const m of row.models) totals[m.model_id] = (totals[m.model_id] || 0) + m.total;
    }
    return Object.keys(totals).sort((a, b) => totals[b] - totals[a]);
  }, [data]);

  const rows = useMemo(() => {
    const r = [...data];
    return showThin ? r : r.filter((t) => t.votes >= minVotes);
  }, [data, showThin, minVotes]);

  if (!byTag || byTag.length === 0) {
    return <div className="text-gray-600 text-sm italic">No tagged votes yet.</div>;
  }

  const cellFor = (row: TagRow, modelId: string) =>
    row.models.find((m) => m.model_id === modelId);

  return (
    <section className="bg-[#0b0e14] border border-white/10 rounded-[32px] p-8">
      <div className="flex items-center justify-between mb-6 flex-wrap gap-3">
        <h2 className="text-sm font-light text-white flex items-center gap-3">
          <span className="w-2 h-6 bg-amber-500 rounded-full"></span> Win Rate by Tag
        </h2>
        <div className="flex items-center gap-3">
          <span className="text-[10px] text-gray-600 uppercase tracking-widest">
            {rows.length} tag{rows.length !== 1 ? "s" : ""} · {models.length} model{models.length !== 1 ? "s" : ""}
          </span>
          <button
            onClick={() => setShowThin((v) => !v)}
            className="px-3 py-1.5 rounded-lg text-[10px] font-bold uppercase tracking-widest border bg-white/5 border-white/10 text-gray-400 hover:text-white hover:border-white/20 transition-all"
          >
            {showThin ? "Hide thin tags" : "Show all tags"}
          </button>
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm border-separate border-spacing-1">
          <thead>
            <tr className="text-[10px] font-black uppercase tracking-widest text-gray-500">
              <th className="text-left py-2 px-3 sticky left-0 bg-[#0b0e14]">Tag</th>
              <th className="text-right py-2 px-2">Votes</th>
              {models.map((m) => (
                <th key={m} className="text-center py-2 px-2 min-w-[92px]">
                  {prettyName(m)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.tag}>
                <td className="py-1.5 px-3 text-gray-200 font-medium whitespace-nowrap sticky left-0 bg-[#0b0e14]">
                  {row.tag}
                </td>
                <td className="py-1.5 px-2 text-right text-gray-500 font-mono text-xs">{row.votes}</td>
                {models.map((m) => {
                  const c = cellFor(row, m);
                  if (!c || c.total === 0) {
                    return (
                      <td key={m} className="py-1.5 px-2 text-center text-gray-700">—</td>
                    );
                  }
                  const { bg, fg } = cellColor(c.win_rate);
                  return (
                    <td key={m} className="py-1 px-1 text-center">
                      <div
                        className="rounded-lg py-1.5 px-1"
                        style={{ backgroundColor: bg, color: fg }}
                        title={`${prettyName(m)} · ${row.tag}: ${c.wins}/${c.total} won`}
                      >
                        <div className="font-black text-sm leading-none">{c.win_rate}%</div>
                        <div className="text-[10px] opacity-80 font-mono mt-0.5">
                          {c.wins}/{c.total}
                        </div>
                      </div>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-gray-600 text-[10px] mt-4 uppercase tracking-widest">
        Cell = win rate % (wins/total). Green = strong, red = weak. A vote counts toward every tag on its case.
      </p>
    </section>
  );
}
