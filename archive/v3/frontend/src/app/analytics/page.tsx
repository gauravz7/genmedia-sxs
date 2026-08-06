"use client";

import { useEffect, useState } from "react";
import {
  BarChart3,
  Loader2,
  Trophy,
  Handshake,
  TrendingUp,
  TrendingDown,
  Timer,
  Radar as RadarIcon,
  Grid3x3,
  Users,
  ShieldAlert,
} from "lucide-react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
  ReferenceLine,
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  Radar,
  Legend,
} from "recharts";
import Nav from "@/components/Nav";
import {
  api,
  Agreement,
  Rankings,
  WinMap,
  LatencyReport,
  StatsReport,
  VoterLeaderboard,
} from "@/lib/api";

const SHORT = (s: string, n = 20) => (s.length > n ? `…${s.slice(-(n - 1))}` : s);
const RADAR_COLORS = ["#6366f1", "#10b981", "#f59e0b", "#ec4899", "#38bdf8"];

export default function AnalyticsPage() {
  const [winmap, setWinmap] = useState<WinMap | null>(null);
  const [agreement, setAgreement] = useState<Agreement | null>(null);
  const [rankings, setRankings] = useState<Rankings | null>(null);
  const [latency, setLatency] = useState<LatencyReport | null>(null);
  const [stats, setStats] = useState<StatsReport | null>(null);
  const [voters, setVoters] = useState<VoterLeaderboard | null>(null);
  const [method, setMethod] = useState<"bradley_terry" | "elo">("bradley_terry");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadAll = async (m: "bradley_terry" | "elo") => {
    setLoading(true);
    setError(null);
    try {
      const [w, a, r, lat, st, vl] = await Promise.all([
        api.winmap(1).catch(() => null),
        api.agreement().catch(() => null),
        api.rankings(m),
        api.latency().catch(() => null),
        api.stats().catch(() => null),
        api.leaderboard().catch(() => null),
      ]);
      setWinmap(w);
      setAgreement(a);
      setRankings(r);
      setLatency(lat);
      setStats(st);
      setVoters(vl);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadAll(method);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [method]);

  const rankData =
    rankings?.ranking.map((r) => ({
      name: r.model_id.length > 22 ? `…${r.model_id.slice(-20)}` : r.model_id,
      full: r.model_id,
      score: r.score,
      rank: r.rank,
    })) ?? [];

  return (
    <div className="min-h-screen bg-[#06080b] text-gray-100 font-sans">
      <div className="fixed inset-0 -z-10 bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-indigo-900/15 via-slate-950 to-[#06080b]" />
      <Nav active="analytics" />

      <main className="max-w-screen-2xl mx-auto px-6 py-10 space-y-8">
        <div className="flex items-center justify-between flex-wrap gap-4">
          <div className="flex items-center gap-3">
            <BarChart3 className="w-6 h-6 text-indigo-400" />
            <h1 className="text-2xl font-black tracking-tight">Analytics</h1>
          </div>
          {loading && <Loader2 className="w-5 h-5 animate-spin text-indigo-400" />}
        </div>

        {error && (
          <p className="text-xs text-red-400 font-mono bg-red-950/30 border border-red-500/20 rounded-xl p-3 break-all">
            {error}
          </p>
        )}

        {/* Rankings */}
        <section className="bg-[#0b0e14] border border-white/5 rounded-3xl p-6">
          <div className="flex items-center justify-between flex-wrap gap-4 mb-6">
            <div className="flex items-center gap-2">
              <Trophy className="w-5 h-5 text-amber-400" />
              <h2 className="text-lg font-black tracking-tight">Global Rankings</h2>
              <span className="text-[10px] text-gray-500 font-mono">
                {rankings ? `n=${rankings.n_votes} votes` : ""}
              </span>
            </div>
            <div className="flex rounded-xl border border-white/10 overflow-hidden">
              {(["bradley_terry", "elo"] as const).map((m) => (
                <button
                  key={m}
                  onClick={() => setMethod(m)}
                  className={`px-4 py-2 text-[10px] font-black uppercase tracking-widest transition ${
                    method === m
                      ? "bg-indigo-500/20 text-indigo-300"
                      : "text-gray-500 hover:text-white"
                  }`}
                >
                  {m === "bradley_terry" ? "Bradley-Terry" : "Elo"}
                </button>
              ))}
            </div>
          </div>

          {rankData.length ? (
            <ResponsiveContainer width="100%" height={Math.max(180, rankData.length * 44)}>
              <BarChart data={rankData} layout="vertical" margin={{ left: 20, right: 40 }}>
                <XAxis type="number" tick={{ fill: "#64748b", fontSize: 11 }} />
                <YAxis
                  type="category"
                  dataKey="name"
                  width={170}
                  tick={{ fill: "#94a3b8", fontSize: 11 }}
                />
                <Tooltip
                  contentStyle={{
                    background: "#0b0e14",
                    border: "1px solid rgba(255,255,255,0.1)",
                    borderRadius: 12,
                    fontSize: 12,
                  }}
                  formatter={(v) => [v, method === "elo" ? "Elo" : "BT strength"]}
                  labelFormatter={(_l, p) => p?.[0]?.payload?.full ?? ""}
                />
                <Bar dataKey="score" radius={[0, 8, 8, 0]}>
                  {rankData.map((_, i) => (
                    <Cell key={i} fill={i === 0 ? "#f59e0b" : "#6366f1"} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <Empty text="No votes yet — cast some on the Compare page." />
          )}
        </section>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
          {/* Win map */}
          <section className="bg-[#0b0e14] border border-white/5 rounded-3xl p-6">
            <div className="flex items-center gap-2 mb-2">
              <TrendingUp className="w-5 h-5 text-emerald-400" />
              <h2 className="text-lg font-black tracking-tight">Google Win-Map</h2>
            </div>
            <p className="text-[11px] text-gray-500 mb-5">
              {winmap?.note || "Google vs competitor from the AI judge; 95% Wilson CI."}
            </p>

            {winmap && winmap.overall.n > 0 ? (
              <>
                <div className="rounded-2xl border border-white/5 bg-black/30 p-4 mb-5">
                  <div className="text-[10px] font-black uppercase tracking-widest text-gray-500">
                    Overall Google win-rate
                  </div>
                  <div className="text-3xl font-black text-white mt-1">
                    {winmap.overall.win_rate}%
                    <span className="text-sm text-gray-500 font-mono ml-2">
                      [{winmap.overall.ci_low}–{winmap.overall.ci_high}] · n={winmap.overall.n}
                    </span>
                  </div>
                </div>
                <SegmentBars segments={[...winmap.by_modality, ...winmap.by_category]} />
              </>
            ) : (
              <Empty text="No Google-vs-competitor AI verdicts yet." />
            )}
          </section>

          {/* Agreement */}
          <section className="bg-[#0b0e14] border border-white/5 rounded-3xl p-6">
            <div className="flex items-center gap-2 mb-2">
              <Handshake className="w-5 h-5 text-pink-400" />
              <h2 className="text-lg font-black tracking-tight">Human ↔ AI Agreement</h2>
            </div>
            <p className="text-[11px] text-gray-500 mb-5">
              Of pairs with both a human vote and an AI verdict, how often they pick the same
              execution.
            </p>
            {agreement && Object.keys(agreement).length ? (
              <div className="space-y-3">
                {Object.entries(agreement).map(([mod, s]) => (
                  <div
                    key={mod}
                    className={`rounded-2xl border p-4 ${
                      mod === "overall"
                        ? "border-pink-500/30 bg-pink-950/10"
                        : "border-white/5 bg-black/30"
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-black uppercase tracking-widest text-gray-400">
                        {mod}
                      </span>
                      <span className="text-2xl font-black text-white">
                        {s.pct === null ? "—" : `${s.pct}%`}
                      </span>
                    </div>
                    <div className="text-[10px] font-mono text-gray-600 mt-1">
                      {s.agree}/{s.n} agree
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <Empty text="No overlapping human + AI verdicts yet." />
            )}
          </section>
        </div>

        {/* Win-rate SKU leaderboard (human votes) */}
        <SkuLeaderboard stats={stats} />

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
          {/* Latency */}
          <section className="bg-[#0b0e14] border border-white/5 rounded-3xl p-6">
            <div className="flex items-center gap-2 mb-2">
              <Timer className="w-5 h-5 text-sky-400" />
              <h2 className="text-lg font-black tracking-tight">Generation Latency</h2>
            </div>
            <p className="text-[11px] text-gray-500 mb-5">
              Average successful-generation time per model, in seconds.
            </p>
            <LatencyBars latency={latency} />
          </section>

          {/* Per-metric radar */}
          <section className="bg-[#0b0e14] border border-white/5 rounded-3xl p-6">
            <div className="flex items-center gap-2 mb-2">
              <RadarIcon className="w-5 h-5 text-violet-400" />
              <h2 className="text-lg font-black tracking-tight">Quality Dimensions</h2>
            </div>
            <p className="text-[11px] text-gray-500 mb-5">
              Per-metric averages from the AI judge, top models by win-rate.
            </p>
            <MetricRadar stats={stats} />
          </section>
        </div>

        {/* Win-rate by tag */}
        <TagMatrix stats={stats} />

        {/* Voter leaderboard */}
        <VoterBoard voters={voters} />
      </main>
    </div>
  );
}

function SkuLeaderboard({ stats }: { stats: StatsReport | null }) {
  const skus = stats?.skus ?? [];
  return (
    <section className="bg-[#0b0e14] border border-white/5 rounded-3xl p-6">
      <div className="flex items-center gap-2 mb-5">
        <BarChart3 className="w-5 h-5 text-emerald-400" />
        <h2 className="text-lg font-black tracking-tight">Model Win-Rate</h2>
        <span className="text-[10px] text-gray-500 font-mono">
          {stats ? `${stats.total_evals} human votes` : ""}
        </span>
      </div>
      {skus.length ? (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-[10px] font-black uppercase tracking-widest text-gray-500 text-left">
                <th className="py-2 pr-4">#</th>
                <th className="py-2 pr-4">Model</th>
                <th className="py-2 pr-4 text-right">Win-rate</th>
                <th className="py-2 pr-4 text-right">W / N</th>
                <th className="py-2 pr-4 text-right">Latency</th>
              </tr>
            </thead>
            <tbody>
              {skus.map((s, i) => (
                <tr key={s.model_id} className="border-t border-white/5">
                  <td className="py-2.5 pr-4 text-gray-600 font-mono">{i + 1}</td>
                  <td className="py-2.5 pr-4 font-mono text-gray-200">{s.model_id}</td>
                  <td className="py-2.5 pr-4 text-right">
                    <span className="inline-flex items-center gap-2">
                      <span className="w-24 h-1.5 rounded-full bg-white/5 overflow-hidden hidden sm:block">
                        <span
                          className="block h-full bg-emerald-500"
                          style={{ width: `${s.win_rate}%` }}
                        />
                      </span>
                      <span className="font-black text-white tabular-nums">{s.win_rate}%</span>
                    </span>
                  </td>
                  <td className="py-2.5 pr-4 text-right font-mono text-gray-500">
                    {s.wins}/{s.total}
                  </td>
                  <td className="py-2.5 pr-4 text-right font-mono text-gray-500">
                    {s.latency_s != null ? `${s.latency_s}s` : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <Empty text="No human votes yet — cast some on the Compare page." />
      )}
    </section>
  );
}

function LatencyBars({ latency }: { latency: LatencyReport | null }) {
  const rows = latency?.rows ?? [];
  if (!rows.length) return <Empty text="No successful generations timed yet." />;
  const data = rows.slice(0, 14).map((r) => ({
    name: `${SHORT(r.model, 18)}`,
    modality: r.modality,
    avg: r.avg_latency_s,
    samples: r.samples,
  }));
  return (
    <ResponsiveContainer width="100%" height={Math.max(180, data.length * 34)}>
      <BarChart data={data} layout="vertical" margin={{ left: 10, right: 40 }}>
        <XAxis type="number" tick={{ fill: "#64748b", fontSize: 10 }} unit="s" />
        <YAxis type="category" dataKey="name" width={140} tick={{ fill: "#94a3b8", fontSize: 10 }} />
        <Tooltip
          contentStyle={{
            background: "#0b0e14",
            border: "1px solid rgba(255,255,255,0.1)",
            borderRadius: 12,
            fontSize: 12,
          }}
          formatter={(v, _n, p) => [`${v}s · n=${p?.payload?.samples}`, p?.payload?.modality]}
        />
        <Bar dataKey="avg" radius={[0, 6, 6, 0]} fill="#38bdf8" />
      </BarChart>
    </ResponsiveContainer>
  );
}

function MetricRadar({ stats }: { stats: StatsReport | null }) {
  const scored = (stats?.skus ?? []).filter((s) => Object.keys(s.scores).length > 0);
  if (!scored.length) return <Empty text="No AI-judge dimension scores yet." />;
  const models = scored.slice(0, 5);
  const metrics = Array.from(
    new Set(models.flatMap((m) => Object.keys(m.scores)))
  );
  const data = metrics.map((metric) => {
    const row: Record<string, string | number> = {
      metric: metric.replace(/_/g, " "),
    };
    models.forEach((m) => {
      row[m.model_id] = m.scores[metric] ?? 0;
    });
    return row;
  });
  return (
    <ResponsiveContainer width="100%" height={320}>
      <RadarChart data={data} outerRadius="70%">
        <PolarGrid stroke="rgba(255,255,255,0.08)" />
        <PolarAngleAxis dataKey="metric" tick={{ fill: "#94a3b8", fontSize: 10 }} />
        <PolarRadiusAxis tick={{ fill: "#475569", fontSize: 9 }} />
        {models.map((m, i) => (
          <Radar
            key={m.model_id}
            name={SHORT(m.model_id, 16)}
            dataKey={m.model_id}
            stroke={RADAR_COLORS[i % RADAR_COLORS.length]}
            fill={RADAR_COLORS[i % RADAR_COLORS.length]}
            fillOpacity={0.12}
          />
        ))}
        <Legend wrapperStyle={{ fontSize: 10 }} />
        <Tooltip
          contentStyle={{
            background: "#0b0e14",
            border: "1px solid rgba(255,255,255,0.1)",
            borderRadius: 12,
            fontSize: 12,
          }}
        />
      </RadarChart>
    </ResponsiveContainer>
  );
}

function TagMatrix({ stats }: { stats: StatsReport | null }) {
  const tags = stats?.by_tag ?? [];
  const models = Array.from(
    new Set(tags.flatMap((t) => t.models.map((m) => m.model_id)))
  ).slice(0, 8);
  const cell = (wr: number) => {
    const hue = Math.round((wr / 100) * 140); // red→green
    return `hsl(${hue} 60% 22%)`;
  };
  return (
    <section className="bg-[#0b0e14] border border-white/5 rounded-3xl p-6">
      <div className="flex items-center gap-2 mb-5">
        <Grid3x3 className="w-5 h-5 text-amber-400" />
        <h2 className="text-lg font-black tracking-tight">Win-Rate by Tag</h2>
      </div>
      {tags.length && models.length ? (
        <div className="overflow-x-auto">
          <table className="text-xs border-separate border-spacing-1">
            <thead>
              <tr>
                <th className="text-left text-[10px] font-black uppercase tracking-widest text-gray-500 pr-3">
                  Tag
                </th>
                {models.map((m) => (
                  <th
                    key={m}
                    className="text-[9px] font-mono text-gray-500 px-1 align-bottom"
                    title={m}
                  >
                    <div className="rotate-0 whitespace-nowrap">{SHORT(m, 12)}</div>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {tags.slice(0, 20).map((t) => {
                const byModel = Object.fromEntries(t.models.map((m) => [m.model_id, m]));
                return (
                  <tr key={t.tag}>
                    <td className="pr-3 font-mono text-gray-300 whitespace-nowrap">
                      {t.tag}{" "}
                      <span className="text-gray-600">({t.votes})</span>
                    </td>
                    {models.map((m) => {
                      const d = byModel[m];
                      return (
                        <td
                          key={m}
                          className="text-center rounded font-black tabular-nums text-white/90 w-12 h-9"
                          style={{ background: d ? cell(d.win_rate) : "rgba(255,255,255,0.02)" }}
                          title={d ? `${d.wins}/${d.total}` : "no data"}
                        >
                          {d ? `${Math.round(d.win_rate)}` : "·"}
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <Empty text="No tagged matchups voted yet." />
      )}
    </section>
  );
}

function VoterBoard({ voters }: { voters: VoterLeaderboard | null }) {
  const overall = voters?.overall ?? [];
  return (
    <section className="bg-[#0b0e14] border border-white/5 rounded-3xl p-6">
      <div className="flex items-center gap-2 mb-5">
        <Users className="w-5 h-5 text-cyan-400" />
        <h2 className="text-lg font-black tracking-tight">Voter Leaderboard</h2>
      </div>
      {overall.length ? (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-[10px] font-black uppercase tracking-widest text-gray-500 text-left">
                <th className="py-2 pr-4">#</th>
                <th className="py-2 pr-4">Voter</th>
                <th className="py-2 pr-4 text-right">Total</th>
                <th className="py-2 pr-4 text-right">Video</th>
                <th className="py-2 pr-4 text-right">Image</th>
                <th className="py-2 pr-4 text-right">TTS</th>
              </tr>
            </thead>
            <tbody>
              {overall.map((v, i) => (
                <tr key={v.ldap} className="border-t border-white/5">
                  <td className="py-2 pr-4 text-gray-600 font-mono">{i + 1}</td>
                  <td className="py-2 pr-4 font-mono text-gray-200">{v.ldap}</td>
                  <td className="py-2 pr-4 text-right font-black text-white">{v.total}</td>
                  <td className="py-2 pr-4 text-right font-mono text-gray-500">{v.video}</td>
                  <td className="py-2 pr-4 text-right font-mono text-gray-500">{v.image}</td>
                  <td className="py-2 pr-4 text-right font-mono text-gray-500">{v.tts}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <Empty text="No attributable voters yet." />
      )}

      {voters && voters.excluded.length > 0 && (
        <div className="mt-5 rounded-2xl border border-amber-500/20 bg-amber-950/10 p-4">
          <div className="flex items-center gap-2 mb-2">
            <ShieldAlert className="w-4 h-4 text-amber-400" />
            <span className="text-[10px] font-black uppercase tracking-widest text-amber-300">
              Excluded (suspected blind voting)
            </span>
          </div>
          <p className="text-[11px] text-gray-500 mb-2">
            ≥{voters.rules.min_decisive} decisive votes that are ≥{voters.rules.one_sided_pct}%
            one-sided are dropped from the board and stats.
          </p>
          <div className="flex flex-wrap gap-2">
            {voters.excluded.map((e) => (
              <span
                key={e.ldap}
                className="text-[10px] font-mono text-amber-300/80 bg-amber-500/10 border border-amber-500/20 rounded-full px-2.5 py-1"
              >
                {e.ldap} · {e.dominant_pct}% side {e.dominant_side} · n={e.total}
              </span>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}

function SegmentBars({
  segments,
}: {
  segments: { segment: string; win_rate: number; n: number; verdict: string }[];
}) {
  if (!segments.length) return <Empty text="No segments meet the threshold." />;
  const data = segments.slice(0, 12).map((s) => ({
    name: s.segment.length > 18 ? `${s.segment.slice(0, 16)}…` : s.segment,
    win_rate: s.win_rate,
    verdict: s.verdict,
  }));
  return (
    <ResponsiveContainer width="100%" height={Math.max(160, data.length * 34)}>
      <BarChart data={data} layout="vertical" margin={{ left: 10, right: 30 }}>
        <XAxis type="number" domain={[0, 100]} tick={{ fill: "#64748b", fontSize: 10 }} />
        <YAxis type="category" dataKey="name" width={130} tick={{ fill: "#94a3b8", fontSize: 10 }} />
        <ReferenceLine x={50} stroke="#475569" strokeDasharray="3 3" />
        <Tooltip
          contentStyle={{
            background: "#0b0e14",
            border: "1px solid rgba(255,255,255,0.1)",
            borderRadius: 12,
            fontSize: 12,
          }}
          formatter={(v) => [`${v}%`, "Google win-rate"]}
        />
        <Bar dataKey="win_rate" radius={[0, 6, 6, 0]}>
          {data.map((d, i) => (
            <Cell
              key={i}
              fill={
                d.verdict === "lead" ? "#10b981" : d.verdict === "trail" ? "#ef4444" : "#6366f1"
              }
            />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

function Empty({ text }: { text: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-12 text-gray-600 text-center">
      <TrendingDown className="w-8 h-8 mb-2 opacity-40" />
      <p className="text-sm">{text}</p>
    </div>
  );
}
