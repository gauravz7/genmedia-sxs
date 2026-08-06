"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Scale,
  Loader2,
  Trophy,
  Equal,
  SkipForward,
  UserRound,
  Lock,
  Unlock,
} from "lucide-react";
import Nav from "@/components/Nav";
import MediaView from "@/components/MediaView";
import {
  api,
  BlindPair,
  Reveal,
  Modality,
  getLdap,
  setLdap as persistLdap,
  maskPid,
} from "@/lib/api";

type Side = "a" | "b";

const MODALITIES: { value: string; label: string }[] = [
  { value: "", label: "Any" },
  { value: "t2v", label: "Text→Video" },
  { value: "i2v", label: "Image→Video" },
  { value: "r2v", label: "Ref→Video" },
  { value: "t2i", label: "Text→Image" },
  { value: "i2i", label: "Image→Image" },
  { value: "tts", label: "Speech (TTS)" },
];

// A compact structured rubric scored 1–5 per side. The winner is still A/B/tie;
// these dimensions travel with the vote for later inspection.
const RUBRIC = [
  { key: "adherence", label: "Prompt adherence" },
  { key: "quality", label: "Quality" },
  { key: "overall", label: "Overall appeal" },
];

type Scores = Record<string, number>;
const freshScores = (): Scores =>
  Object.fromEntries(RUBRIC.map((r) => [r.key, 3]));

export default function ComparePage() {
  const [ldap, setLdapState] = useState("");
  const [ldapDraft, setLdapDraft] = useState("");
  const [modality, setModality] = useState("");
  const [tag, setTag] = useState("");

  const [pair, setPair] = useState<BlindPair | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [empty, setEmpty] = useState(false);

  const [scoresA, setScoresA] = useState<Scores>(freshScores);
  const [scoresB, setScoresB] = useState<Scores>(freshScores);
  const [justification, setJustification] = useState("");

  const [voted, setVoted] = useState<Side | "tie" | null>(null);
  const [reveal, setReveal] = useState<Reveal | null>(null);
  const [progress, setProgress] = useState<{ count: number; required: number; unlocked: boolean } | null>(
    null
  );

  useEffect(() => {
    const saved = getLdap();
    setLdapState(saved);
    setLdapDraft(saved);
  }, []);

  const refreshProgress = useCallback(async (id: string) => {
    if (!id) return;
    try {
      setProgress(await api.voteCount(id));
    } catch {
      /* non-fatal */
    }
  }, []);

  const loadPair = useCallback(async () => {
    setLoading(true);
    setError(null);
    setEmpty(false);
    setVoted(null);
    setReveal(null);
    setScoresA(freshScores());
    setScoresB(freshScores());
    setJustification("");
    try {
      const p = await api.comparePair({ modality, tag: tag.trim() || undefined });
      setPair(p);
    } catch (e) {
      const msg = String(e);
      if (msg.startsWith("404")) {
        setPair(null);
        setEmpty(true);
      } else {
        setError(msg);
      }
    } finally {
      setLoading(false);
    }
  }, [modality, tag]);

  // Auto-serve the first pair once an identity exists.
  useEffect(() => {
    if (ldap) {
      loadPair();
      refreshProgress(ldap);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ldap, modality]);

  const saveLdap = () => {
    const v = ldapDraft.trim();
    if (!v) return;
    persistLdap(v);
    setLdapState(v);
  };

  const castVote = async (winner: Side | "tie") => {
    if (!pair || voted) return;
    setError(null);
    const scores: Scores = {};
    for (const r of RUBRIC) {
      scores[`a_${r.key}`] = scoresA[r.key];
      scores[`b_${r.key}`] = scoresB[r.key];
    }
    const winner_execution =
      winner === "tie"
        ? null
        : winner === "a"
          ? pair.side_a.execution_id
          : pair.side_b.execution_id;
    try {
      await api.vote({
        case_id: pair.case_id,
        execution_a: pair.side_a.execution_id,
        execution_b: pair.side_b.execution_id,
        winner_execution,
        scores,
        justification: justification.trim(),
        ldap,
      });
      setVoted(winner);
      // Blindness lifts only now — reveal from the server, post-commit.
      setReveal(await api.compareReveal(pair.side_a.execution_id, pair.side_b.execution_id));
      refreshProgress(ldap);
    } catch (e) {
      setError(String(e));
    }
  };

  const modelOf = (side: Side): string | null => {
    if (!reveal || !pair) return null;
    const id = side === "a" ? pair.side_a.execution_id : pair.side_b.execution_id;
    return reveal[id]?.model_id ?? "unknown";
  };

  // -- identity gate ----------------------------------------------------
  if (!ldap) {
    return (
      <div className="min-h-screen bg-[#06080b] text-gray-100 font-sans">
        <div className="fixed inset-0 -z-10 bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-purple-900/15 via-slate-950 to-[#06080b]" />
        <Nav active="compare" />
        <main className="max-w-md mx-auto px-6 py-24">
          <div className="bg-[#0b0e14] border border-white/5 rounded-3xl p-8 space-y-4 text-center">
            <UserRound className="w-10 h-10 text-pink-400 mx-auto" />
            <h1 className="text-xl font-black tracking-tight">Who’s voting?</h1>
            <p className="text-xs text-gray-500">
              Blind SxS votes are attributed to a voter id (ldap). It stays on this
              device and powers the anti-gaming leaderboard.
            </p>
            <input
              value={ldapDraft}
              onChange={(e) => setLdapDraft(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && saveLdap()}
              placeholder="your ldap / username"
              className="w-full bg-black/40 border border-white/10 rounded-xl px-3 py-2.5 text-sm text-center focus:border-pink-500/50 outline-none"
            />
            <button
              onClick={saveLdap}
              disabled={!ldapDraft.trim()}
              className="w-full rounded-xl bg-pink-500/20 border border-pink-500/40 text-pink-200 py-2.5 text-xs font-black uppercase tracking-widest hover:bg-pink-500/30 disabled:opacity-40"
            >
              Start voting
            </button>
          </div>
        </main>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#06080b] text-gray-100 font-sans">
      <div className="fixed inset-0 -z-10 bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-purple-900/15 via-slate-950 to-[#06080b]" />
      <Nav active="compare" />

      <main className="max-w-screen-2xl mx-auto px-6 py-10 space-y-6">
        <div className="flex items-center justify-between flex-wrap gap-4">
          <div className="flex items-center gap-3">
            <Scale className="w-6 h-6 text-pink-400" />
            <h1 className="text-2xl font-black tracking-tight">Blind SxS Voting</h1>
          </div>
          <div className="flex items-center gap-3 flex-wrap">
            {progress && (
              <span
                className={`flex items-center gap-1.5 text-[10px] font-black uppercase tracking-widest px-3 py-1.5 rounded-full border ${
                  progress.unlocked
                    ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
                    : "border-white/10 bg-black/30 text-gray-400"
                }`}
              >
                {progress.unlocked ? <Unlock className="w-3 h-3" /> : <Lock className="w-3 h-3" />}
                {progress.count}/{progress.required} votes
              </span>
            )}
            <button
              onClick={() => {
                persistLdap("");
                setLdapState("");
              }}
              className="flex items-center gap-1.5 text-[10px] font-black uppercase tracking-widest text-gray-400 hover:text-white border border-white/10 rounded-full px-3 py-1.5"
            >
              <UserRound className="w-3 h-3" /> {ldap}
            </button>
          </div>
        </div>

        {/* Filters */}
        <div className="bg-[#0b0e14] border border-white/5 rounded-3xl p-4 flex flex-wrap items-end gap-3">
          <label className="block">
            <span className="text-[10px] font-black uppercase tracking-widest text-gray-500">
              Modality
            </span>
            <select
              value={modality}
              onChange={(e) => setModality(e.target.value)}
              className="mt-1.5 block bg-black/40 border border-white/10 rounded-xl px-3 py-2 text-sm focus:border-pink-500/50 outline-none"
            >
              {MODALITIES.map((m) => (
                <option key={m.value} value={m.value}>
                  {m.label}
                </option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="text-[10px] font-black uppercase tracking-widest text-gray-500">
              Tag filter
            </span>
            <input
              value={tag}
              onChange={(e) => setTag(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && loadPair()}
              placeholder="(optional) category"
              className="mt-1.5 block bg-black/40 border border-white/10 rounded-xl px-3 py-2 text-sm focus:border-pink-500/50 outline-none"
            />
          </label>
          <button
            onClick={loadPair}
            disabled={loading}
            className="flex items-center gap-2 rounded-xl bg-white/10 hover:bg-white/15 border border-white/10 px-4 py-2 text-xs font-black uppercase tracking-widest disabled:opacity-40"
          >
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <SkipForward className="w-4 h-4" />}
            New pair
          </button>
        </div>

        {error && (
          <p className="text-xs text-red-400 font-mono bg-red-950/30 border border-red-500/20 rounded-xl p-3 break-all">
            {error}
          </p>
        )}

        {empty && (
          <div className="bg-[#0b0e14] border border-white/5 rounded-3xl p-12 text-center text-gray-500">
            No eligible matchup for this filter yet — a case needs ≥2 models with
            successful outputs. Generate some on the Executions page.
          </div>
        )}

        {pair && (
          <>
            {/* Shared prompt */}
            <div className="bg-[#0b0e14] border border-white/5 rounded-3xl p-5">
              <div className="flex items-center justify-between gap-3 mb-2">
                <span className="text-[10px] font-black uppercase tracking-widest text-gray-500">
                  Prompt · case {maskPid(pair.case_id)} · {pair.modality}
                </span>
                <span className="text-[10px] font-mono text-gray-600">
                  {pair.remaining_cases} eligible cases
                </span>
              </div>
              <p className="text-sm text-gray-200 whitespace-pre-wrap">{pair.prompt}</p>
            </div>

            {/* Blind arena */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              {(["a", "b"] as Side[]).map((side) => {
                const s = side === "a" ? pair.side_a : pair.side_b;
                const scores = side === "a" ? scoresA : scoresB;
                const setScores = side === "a" ? setScoresA : setScoresB;
                const isWin = voted === side;
                return (
                  <div
                    key={side}
                    className={`bg-[#0b0e14] border rounded-3xl p-5 space-y-4 transition ${
                      isWin
                        ? "border-emerald-500/50 shadow-[0_0_30px_rgba(16,185,129,0.15)]"
                        : "border-white/5"
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <div className="text-3xl font-black italic text-white/90">
                        {side.toUpperCase()}
                      </div>
                      {reveal ? (
                        <span className="text-[11px] font-mono text-gray-300">
                          {modelOf(side)}
                        </span>
                      ) : (
                        <span className="text-[10px] font-black uppercase tracking-widest text-gray-600 italic">
                          hidden
                        </span>
                      )}
                      {isWin && (
                        <span className="flex items-center gap-1 px-2.5 py-1 rounded-full bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 text-[9px] font-black uppercase tracking-widest">
                          <Trophy className="w-3 h-3" /> your pick
                        </span>
                      )}
                    </div>

                    <MediaView
                      src={s.media}
                      modality={pair.modality as Modality}
                      className="w-full max-h-[55vh] min-h-[240px]"
                    />

                    {/* Rubric sliders */}
                    <div className="space-y-2.5 pt-1">
                      {RUBRIC.map((r) => (
                        <div key={r.key} className="flex items-center gap-3">
                          <span className="w-32 text-[10px] font-black uppercase tracking-widest text-gray-500">
                            {r.label}
                          </span>
                          <input
                            type="range"
                            min={1}
                            max={5}
                            step={1}
                            value={scores[r.key]}
                            onChange={(e) =>
                              setScores({ ...scores, [r.key]: Number(e.target.value) })
                            }
                            className="flex-1 accent-pink-500"
                          />
                          <span className="w-5 text-center text-sm font-black text-white">
                            {scores[r.key]}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>

            {/* Vote controls */}
            <div className="bg-[#0b0e14] border border-white/5 rounded-3xl p-6 space-y-4">
              <input
                value={justification}
                onChange={(e) => setJustification(e.target.value)}
                placeholder="Optional: why? (saved with your vote)"
                disabled={!!voted}
                className="w-full bg-black/40 border border-white/10 rounded-xl px-3 py-2.5 text-sm focus:border-pink-500/50 outline-none disabled:opacity-50"
              />
              {!voted ? (
                <div className="grid grid-cols-3 gap-3">
                  <button
                    onClick={() => castVote("a")}
                    className="rounded-xl bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 py-3 text-xs font-black uppercase tracking-widest hover:bg-emerald-500/20 transition"
                  >
                    A wins
                  </button>
                  <button
                    onClick={() => castVote("tie")}
                    className="flex items-center justify-center gap-2 rounded-xl bg-white/5 border border-white/10 text-gray-300 py-3 text-xs font-black uppercase tracking-widest hover:bg-white/10 transition"
                  >
                    <Equal className="w-4 h-4" /> Tie
                  </button>
                  <button
                    onClick={() => castVote("b")}
                    className="rounded-xl bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 py-3 text-xs font-black uppercase tracking-widest hover:bg-emerald-500/20 transition"
                  >
                    B wins
                  </button>
                </div>
              ) : (
                <div className="flex items-center justify-between flex-wrap gap-3">
                  <span className="text-[11px] font-black uppercase tracking-widest text-emerald-400">
                    Vote recorded ·{" "}
                    {voted === "tie" ? "Tie" : `Side ${voted.toUpperCase()} — ${modelOf(voted)}`}
                  </span>
                  <button
                    onClick={loadPair}
                    className="flex items-center gap-2 rounded-xl bg-gradient-to-r from-pink-500 to-purple-500 text-white px-5 py-2.5 text-xs font-black uppercase tracking-widest hover:opacity-90 transition"
                  >
                    <SkipForward className="w-4 h-4" /> Next pair
                  </button>
                </div>
              )}
            </div>
          </>
        )}
      </main>
    </div>
  );
}
