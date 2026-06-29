"use client";
import { useState, useEffect, useRef, useCallback } from "react";
import { API_BASE_URL, adminFetch, getAdminToken, setAdminToken } from "@/lib/api";
import Nav from "@/components/Nav";

// ===================================================================
// Local media-URL helper. The backend proxies images at
// `/api/image/media?url=...`; the shared formatUrl() only rewrites
// /api/media + /api/sxs/media, so we prefix our own path here.
// ===================================================================
const imgUrl = (url?: string): string | undefined => {
  if (!url) return url;
  if (url.startsWith("/api/image/media") || url.startsWith("/api/media")) {
    return `${API_BASE_URL}${url}`;
  }
  return url;
};

// ===================================================================
// Types — the API shape is loose / dynamic
// ===================================================================
interface ResultEntry {
  status?: string;
  url?: string;
  engine?: string;
  error?: string;
  latency_ms?: number;
  [key: string]: any;
}

interface ImageJob {
  id: string;
  customer?: string;
  prompt_id?: string;
  prompt?: string;
  mode?: string;
  matchup?: string;
  matchup_label?: string;
  input_image?: string;
  side_map?: Record<string, string>;
  results?: Record<string, ResultEntry>;
  ai_eval?: any;
  auto_eval_status?: string;
  [key: string]: any;
}

interface Matchup {
  id: string;
  label: string;
  left: string;
  right: string;
}

const T2I_METRICS = ["prompt_following", "aesthetic", "detail", "artifact_free"];
const I2I_EXTRA = "edit_fidelity";
const METRIC_LABELS: Record<string, string> = {
  prompt_following: "Prompt Following",
  aesthetic: "Aesthetic",
  detail: "Detail / Sharpness",
  artifact_free: "Artifact-Free",
  edit_fidelity: "Edit Fidelity",
};

type Tab = "admin" | "eval" | "results";

export default function ImageSxSStudio() {
  // ---------- Admin gate ----------
  const [authed, setAuthed] = useState(false);
  const [authChecked, setAuthChecked] = useState(false);
  const [loginUser, setLoginUser] = useState("");
  const [loginPass, setLoginPass] = useState("");
  const [loginError, setLoginError] = useState("");
  const [loggingIn, setLoggingIn] = useState(false);

  const [tab, setTab] = useState<Tab>("eval");

  useEffect(() => {
    setAuthed(getAdminToken() != null);
    setAuthChecked(true);
  }, []);

  const handleAdminLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoggingIn(true);
    setLoginError("");
    try {
      const res = await fetch(`${API_BASE_URL}/api/admin/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: loginUser, password: loginPass }),
      });
      if (res.ok) {
        const data = await res.json();
        if (data?.token) {
          setAdminToken(data.token);
          setAuthed(true);
        } else setLoginError("No token returned");
      } else setLoginError("Invalid credentials");
    } catch {
      setLoginError("Server unavailable");
    } finally {
      setLoggingIn(false);
    }
  };

  if (!authChecked) return <div className="min-h-screen bg-[#06080b]" />;

  return (
    <div className="min-h-screen bg-[#06080b] text-gray-100 font-sans selection:bg-indigo-500/30 overflow-x-hidden">
      <div className="fixed inset-0 -z-10 bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-indigo-900/10 via-slate-950 to-[#06080b]"></div>
      <Nav active="image-sxs" />

      <main className="max-w-screen-2xl mx-auto px-6 pt-32 pb-20 relative z-10">
        {/* Header */}
        <section className="mb-10 animate-in fade-in slide-in-from-top-4 duration-1000">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-indigo-500/10 border border-indigo-500/20 text-indigo-300 text-[10px] font-black uppercase tracking-widest mb-4">
            Image Modality
          </div>
          <h1 className="text-4xl md:text-5xl font-black text-white tracking-tight leading-tight">
            Image SxS &mdash;{" "}
            <span className="text-transparent bg-clip-text bg-gradient-to-r from-indigo-400 via-purple-400 to-emerald-400">
              Gemini Image vs GPT-image
            </span>
          </h1>
          <p className="text-gray-500 text-sm md:text-base mt-3 font-light max-w-2xl">
            T2I &amp; I2I side-by-side: blind human A/B plus an AI judge across prompt-following,
            aesthetic, detail, artifact-free, and edit fidelity.
          </p>
        </section>

        {/* Tabs */}
        <div className="flex items-center gap-2 mb-10">
          {([
            { id: "eval", label: "Blind Eval" },
            { id: "results", label: "Results" },
            { id: "admin", label: "Admin" },
          ] as { id: Tab; label: string }[]).map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`px-5 py-2.5 rounded-2xl text-xs font-black uppercase tracking-widest border transition-all ${
                tab === t.id
                  ? "bg-indigo-500/20 border-indigo-500/40 text-indigo-300 shadow-[0_0_15px_rgba(99,102,241,0.2)]"
                  : "bg-white/5 border-white/10 text-gray-400 hover:text-white hover:border-white/20"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>

        {tab === "admin" && (
          authed ? <AdminPanel /> : <LoginGate {...{ handleAdminLogin, loginUser, setLoginUser, loginPass, setLoginPass, loginError, loggingIn }} />
        )}
        {tab === "eval" && <BlindEvalPanel />}
        {tab === "results" && <ResultsPanel />}
      </main>
    </div>
  );
}

// ===================================================================
// Login gate (inline)
// ===================================================================
function LoginGate({ handleAdminLogin, loginUser, setLoginUser, loginPass, setLoginPass, loginError, loggingIn }: any) {
  return (
    <div className="flex items-center justify-center py-10">
      <div className="max-w-md w-full bg-[#0d1017] border border-white/10 rounded-[40px] p-10 shadow-3xl animate-in fade-in zoom-in-95 duration-500">
        <div className="flex flex-col items-center mb-10">
          <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center shadow-3xl mb-6 font-black text-white">IMG</div>
          <h2 className="text-3xl font-bold text-white tracking-tight">Image SxS Admin</h2>
          <p className="text-gray-500 text-sm mt-2">Admin access required</p>
        </div>
        <form onSubmit={handleAdminLogin} className="space-y-6">
          <div className="space-y-2">
            <label className="text-xs font-bold text-gray-500 uppercase tracking-widest px-1">Identity</label>
            <input type="text" value={loginUser} onChange={(e) => setLoginUser(e.target.value)} placeholder="Username" className="w-full bg-[#06080b] border border-white/10 rounded-2xl px-6 py-4 text-white focus:outline-none focus:ring-2 focus:ring-indigo-500/50 transition-all" />
          </div>
          <div className="space-y-2">
            <label className="text-xs font-bold text-gray-500 uppercase tracking-widest px-1">Access Key</label>
            <input type="password" value={loginPass} onChange={(e) => setLoginPass(e.target.value)} placeholder="Password" className="w-full bg-[#06080b] border border-white/10 rounded-2xl px-6 py-4 text-white focus:outline-none focus:ring-2 focus:ring-indigo-500/50 transition-all" />
          </div>
          {loginError && <div className="text-red-400 text-xs font-bold bg-red-500/10 border border-red-500/20 px-4 py-3 rounded-xl">{loginError}</div>}
          <button type="submit" disabled={loggingIn} className="w-full bg-gradient-to-r from-indigo-500 to-purple-600 hover:from-indigo-400 hover:to-purple-500 text-white font-black py-5 rounded-2xl shadow-3xl transition-all active:scale-[0.98] mt-4 disabled:opacity-40">{loggingIn ? "Signing In…" : "Sign In"}</button>
        </form>
      </div>
    </div>
  );
}

// ===================================================================
// Admin: upload cases JSON + drag-drop reference images, run, job table
// ===================================================================
function AdminPanel() {
  const [cases, setCases] = useState<any[]>([]);
  const [casesFile, setCasesFile] = useState<File | null>(null);
  const [assetFiles, setAssetFiles] = useState<File[]>([]);
  const [parseError, setParseError] = useState("");
  const [uploadError, setUploadError] = useState("");
  const [isUploading, setIsUploading] = useState(false);
  const [batchId, setBatchId] = useState<string | null>(null);
  const [jobs, setJobs] = useState<ImageJob[]>([]);
  const [isPolling, setIsPolling] = useState(false);
  const [matchups, setMatchups] = useState<Matchup[]>([]);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    fetch(`${API_BASE_URL}/api/image/matchups`)
      .then((r) => r.json())
      .then((d) => setMatchups(d.matchups || []))
      .catch(() => {});
  }, []);

  const handleCasesJson = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    setParseError(""); setCases([]); setCasesFile(null);
    if (!file) return;
    try {
      const text = await file.text();
      const parsed = JSON.parse(text);
      const list = Array.isArray(parsed) ? parsed : (parsed.cases ?? parsed.items ?? []);
      if (!Array.isArray(list)) throw new Error("JSON must be an array of cases or have a 'cases' array.");
      setCases(list); setCasesFile(file);
    } catch (err: any) {
      setParseError(err?.message || "Failed to parse JSON");
    }
  };

  const relOf = (f: File) => ((f as any).webkitRelativePath as string) || f.name;
  const handleAssets = (e: React.ChangeEvent<HTMLInputElement>) => {
    const picked = e.target.files ? Array.from(e.target.files) : [];
    setAssetFiles((prev) => {
      const seen = new Set(prev.map((f) => `${relOf(f)}::${f.size}`));
      const merged = [...prev];
      for (const f of picked) {
        const key = `${relOf(f)}::${f.size}`;
        if (!seen.has(key)) { seen.add(key); merged.push(f); }
      }
      return merged;
    });
    e.target.value = "";
  };

  const fetchJobs = useCallback(async (batch: string) => {
    try {
      const res = await fetch(`${API_BASE_URL}/api/image/jobs?batch=${encodeURIComponent(batch)}`);
      const data = await res.json();
      const list: ImageJob[] = Array.isArray(data) ? data : (data.jobs ?? []);
      setJobs(list);
      const allDone = list.length > 0 && list.every((j) => ["done", "error"].includes((j.auto_eval_status || "").toLowerCase()));
      if (allDone && pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; setIsPolling(false); }
    } catch (err) { console.error("Failed to fetch jobs", err); }
  }, []);

  useEffect(() => {
    if (!batchId) return;
    setIsPolling(true);
    fetchJobs(batchId);
    pollRef.current = setInterval(() => fetchJobs(batchId), 6000);
    return () => { if (pollRef.current) clearInterval(pollRef.current); pollRef.current = null; };
  }, [batchId, fetchJobs]);

  const handleGenerate = async () => {
    if (!cases.length || isUploading) return;
    setIsUploading(true); setUploadError("");
    try {
      const fd = new FormData();
      if (casesFile) fd.append("cases", casesFile, "cases.json");
      else fd.append("cases", new Blob([JSON.stringify(cases)], { type: "application/json" }), "cases.json");
      for (const f of assetFiles) fd.append("files", f, relOf(f));
      const res = await adminFetch(`${API_BASE_URL}/api/image/upload`, { method: "POST", body: fd });
      if (!res.ok) throw new Error(`Server responded ${res.status}`);
      const data = await res.json();
      if (!data.batch_id) throw new Error("No batch_id returned.");
      setBatchId(data.batch_id); setJobs([]);
    } catch (err: any) {
      setUploadError(err?.message || "Upload failed");
    } finally { setIsUploading(false); }
  };

  return (
    <div className="space-y-8">
      {/* Matchup registry */}
      {matchups.length > 0 && (
        <section className="bg-white/[0.02] border border-white/5 rounded-[32px] p-6">
          <h2 className="text-sm font-light text-white mb-4 flex items-center gap-3">
            <span className="w-2 h-6 bg-purple-500 rounded-full"></span> Matchup Registry
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            {matchups.map((m) => (
              <div key={m.id} className="bg-[#06080b] border border-white/10 rounded-2xl p-4">
                <div className="text-[10px] font-mono text-indigo-300 mb-2 break-all">{m.id}</div>
                <div className="text-xs text-gray-300 font-bold">{m.left}</div>
                <div className="text-[10px] text-gray-600 my-1 uppercase tracking-widest">vs</div>
                <div className="text-xs text-emerald-300 font-bold">{m.right}</div>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Upload card */}
      <section className="relative group">
        <div className="absolute -inset-1 bg-gradient-to-r from-indigo-500 via-purple-500 to-emerald-500 rounded-[42px] blur opacity-10 group-hover:opacity-20 transition duration-1000"></div>
        <div className="relative bg-[#0b0e14] border border-white/10 rounded-[40px] p-8 md:p-10 shadow-3xl space-y-8">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
            <div className="space-y-3">
              <label className="text-[10px] font-black text-gray-500 uppercase tracking-widest px-1">Cases JSON</label>
              <input type="file" accept=".json" onChange={handleCasesJson}
                className="w-full text-sm text-gray-400 bg-[#06080b] border border-white/10 rounded-2xl px-5 py-4 file:mr-4 file:py-2 file:px-5 file:rounded-xl file:border-0 file:text-xs file:font-black file:uppercase file:tracking-widest file:bg-indigo-500/20 file:text-indigo-300 hover:file:bg-indigo-500/30 file:cursor-pointer cursor-pointer focus:outline-none focus:ring-2 focus:ring-indigo-500/40 transition-all" />
              {parseError && <div className="text-red-400 text-xs font-bold bg-red-500/10 border border-red-500/20 px-4 py-3 rounded-xl">{parseError}</div>}
              {cases.length > 0 && <div className="text-emerald-400 text-xs font-bold">{cases.length} case(s) parsed</div>}
              <p className="text-[10px] text-gray-600 px-1 leading-relaxed">
                Each case: <span className="text-gray-400 font-mono">{`{ id, mode: "t2i"|"i2i", prompt, input_image?, matchup? }`}</span>
              </p>
            </div>
            <div className="space-y-3">
              <label className="text-[10px] font-black text-gray-500 uppercase tracking-widest px-1">Reference Images (for I2I — drag-drop a folder or files)</label>
              <input type="file" multiple {...({ webkitdirectory: "" } as any)} onChange={handleAssets}
                className="w-full text-sm text-gray-400 bg-[#06080b] border border-white/10 rounded-2xl px-5 py-4 file:mr-4 file:py-2 file:px-5 file:rounded-xl file:border-0 file:text-xs file:font-black file:uppercase file:tracking-widest file:bg-purple-500/20 file:text-purple-300 hover:file:bg-purple-500/30 file:cursor-pointer cursor-pointer focus:outline-none focus:ring-2 focus:ring-purple-500/40 transition-all" />
              <input type="file" multiple onChange={handleAssets}
                className="w-full text-xs text-gray-500 bg-[#06080b] border border-white/10 rounded-2xl px-5 py-3 file:mr-4 file:py-1.5 file:px-4 file:rounded-lg file:border-0 file:text-[10px] file:font-black file:uppercase file:tracking-widest file:bg-white/10 file:text-gray-300 file:cursor-pointer cursor-pointer focus:outline-none focus:ring-2 focus:ring-white/20 transition-all" />
              {assetFiles.length > 0 && (
                <div className="flex items-center justify-between gap-3">
                  <div className="text-emerald-400 text-xs font-bold">{assetFiles.length} asset file(s) staged</div>
                  <button onClick={() => setAssetFiles([])} className="text-[10px] font-black uppercase tracking-widest text-gray-500 hover:text-red-400 transition-colors">Clear</button>
                </div>
              )}
            </div>
          </div>
          {uploadError && <div className="text-red-400 text-xs font-bold bg-red-500/10 border border-red-500/20 px-4 py-3 rounded-xl">{uploadError}</div>}
          <button onClick={handleGenerate} disabled={!cases.length || isUploading}
            className="w-full bg-gradient-to-r from-indigo-500 via-purple-600 to-emerald-600 hover:from-indigo-400 hover:to-emerald-500 text-white font-black py-5 rounded-[28px] shadow-[0_20px_50px_rgba(99,102,241,0.25)] transition-all active:scale-[0.98] disabled:opacity-40 disabled:cursor-not-allowed uppercase tracking-widest text-sm">
            {isUploading ? "Uploading & Launching..." : "Generate + Auto-Eval"}
          </button>
        </div>
      </section>

      {/* Cases preview */}
      {cases.length > 0 && !batchId && (
        <section className="bg-white/[0.02] border border-white/5 rounded-[40px] p-8">
          <h2 className="text-xl font-light text-white mb-6 flex items-center gap-3">
            <span className="w-2 h-8 bg-indigo-500 rounded-full"></span> Case Preview
          </h2>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-[10px] font-black uppercase tracking-widest text-gray-500 border-b border-white/10">
                  <th className="text-left py-3 px-3">ID</th>
                  <th className="text-left py-3 px-3">Mode</th>
                  <th className="text-left py-3 px-3">Matchup</th>
                  <th className="text-left py-3 px-3">Input Image</th>
                  <th className="text-left py-3 px-3">Prompt</th>
                </tr>
              </thead>
              <tbody>
                {cases.map((c, i) => (
                  <tr key={i} className="border-b border-white/5 hover:bg-white/[0.02] transition-colors">
                    <td className="py-3 px-3 text-indigo-300 font-mono text-xs">{c.id ?? "—"}</td>
                    <td className="py-3 px-3 text-gray-400 uppercase text-xs">{c.mode ?? "t2i"}</td>
                    <td className="py-3 px-3 text-gray-500 font-mono text-[10px]">{c.matchup ?? "(default)"}</td>
                    <td className="py-3 px-3 text-gray-500 font-mono text-[10px]">{c.input_image ?? "—"}</td>
                    <td className="py-3 px-3 text-gray-300 font-light max-w-md truncate">{c.prompt ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* Jobs progress */}
      {batchId && (
        <section className="space-y-8">
          <div className="flex items-center justify-between">
            <h2 className="text-xl font-light text-white flex items-center gap-3">
              <span className="w-2 h-8 bg-emerald-500 rounded-full"></span> Generation Progress
            </h2>
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-white/5 border border-white/10 text-[10px] font-black uppercase tracking-widest text-gray-400">
              <span className="font-mono normal-case text-indigo-300">batch: {batchId}</span>
              {isPolling && <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse"></span>}
            </div>
          </div>
          {jobs.length === 0 ? (
            <div className="py-32 flex flex-col items-center justify-center text-gray-500 gap-4 bg-white/[0.02] border border-white/5 rounded-[40px]">
              <div className="w-10 h-10 rounded-full border-2 border-indigo-500/30 border-t-indigo-500 animate-spin"></div>
              <p className="font-light tracking-widest uppercase text-xs">Awaiting job records...</p>
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-8">
              {jobs.map((job) => (
                <div key={job.id} className="bg-[#0b0e14] border border-white/5 rounded-[40px] p-8 shadow-3xl">
                  <div className="flex flex-wrap items-center justify-between gap-4 mb-6">
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2 mb-2">
                        <span className="px-3 py-1 rounded-full bg-purple-500/10 border border-purple-500/20 text-purple-300 text-[10px] font-black uppercase tracking-widest">{job.mode || "t2i"}</span>
                        {job.matchup_label && <span className="px-3 py-1 rounded-full bg-white/5 border border-white/10 text-gray-400 text-[10px] font-black uppercase tracking-widest">{job.matchup_label}</span>}
                      </div>
                      <p className="text-gray-300 font-light text-sm">&ldquo;{job.prompt || "No prompt"}&rdquo;</p>
                    </div>
                    <div className="flex items-center gap-2">
                      <AutoEvalBadge status={job.auto_eval_status} />
                      <button onClick={async () => { await adminFetch(`${API_BASE_URL}/api/image/jobs/${job.id}/retry`, { method: "POST" }); }}
                        className="px-3 py-1.5 rounded-full text-[10px] font-black uppercase tracking-widest bg-amber-500/10 border border-amber-500/30 text-amber-300 hover:bg-amber-500/20 transition-all">Retry</button>
                    </div>
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    {(["A", "B"] as const).map((label) => (
                      <ImagePane key={label} title={`Side ${label} · ${job.results?.[label]?.engine || "?"}`} accent={label === "A" ? "indigo" : "emerald"} entry={job.results?.[label]} />
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>
      )}
    </div>
  );
}

// ===================================================================
// Blind eval: side-by-side image A / B + per-metric rating widget
// ===================================================================
function BlindEvalPanel() {
  const [pair, setPair] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [ldap, setLdap] = useState("");
  const [scores, setScores] = useState<Record<string, number>>({});
  const [justification, setJustification] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [reveal, setReveal] = useState<any>(null);

  useEffect(() => {
    const saved = typeof window !== "undefined" ? localStorage.getItem("pp_ldap") : "";
    if (saved) setLdap(saved);
  }, []);

  const isI2I = (pair?.mode || "t2i") === "i2i";
  const metrics = isI2I ? [...T2I_METRICS, I2I_EXTRA] : T2I_METRICS;

  const loadPair = useCallback(async () => {
    setLoading(true); setError(""); setReveal(null); setScores({}); setJustification("");
    try {
      const res = await fetch(`${API_BASE_URL}/api/image/pair`);
      const data = await res.json();
      if (data?.status === "error") { setError(data.message || "No pairs ready"); setPair(null); }
      else setPair(data);
    } catch { setError("Failed to load pair"); setPair(null); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { loadPair(); }, [loadPair]);

  const setMetric = (m: string, v: number) => setScores((s) => ({ ...s, [m]: v }));

  const submitVote = async (winnerSide: "A" | "B" | "tie") => {
    if (!pair || submitting) return;
    setSubmitting(true);
    if (ldap) localStorage.setItem("pp_ldap", ldap);
    try {
      const res = await fetch(`${API_BASE_URL}/api/image/vote`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ job_id: pair.job_id, winner_side: winnerSide, scores, justification, ldap: ldap || "anonymous" }),
      });
      if (!res.ok) throw new Error(`Server responded ${res.status}`);
      // Reveal the AI judge + identities after voting.
      const ai = await fetch(`${API_BASE_URL}/api/image/aieval/${pair.job_id}`).then((r) => r.json()).catch(() => null);
      setReveal(ai);
    } catch (e: any) {
      setError(e?.message || "Vote failed");
    } finally { setSubmitting(false); }
  };

  if (loading) return <div className="py-32 flex flex-col items-center gap-4 text-gray-500"><div className="w-10 h-10 rounded-full border-2 border-indigo-500/30 border-t-indigo-500 animate-spin"></div><p className="text-xs uppercase tracking-widest">Loading pair…</p></div>;

  if (error || !pair) return (
    <div className="py-24 text-center">
      <p className="text-gray-400 mb-6">{error || "No image pairs ready for voting yet."}</p>
      <button onClick={loadPair} className="px-6 py-3 rounded-2xl bg-indigo-500/20 border border-indigo-500/40 text-indigo-300 font-black uppercase tracking-widest text-xs hover:bg-indigo-500/30 transition-all">Refresh</button>
    </div>
  );

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div className="min-w-0">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-purple-500/10 border border-purple-500/20 text-purple-300 text-[10px] font-black uppercase tracking-widest mb-2">{pair.mode || "t2i"}</div>
          <p className="text-gray-200 font-light text-lg max-w-3xl">&ldquo;{pair.prompt}&rdquo;</p>
        </div>
        <input value={ldap} onChange={(e) => setLdap(e.target.value)} placeholder="your ldap (optional)"
          className="bg-[#06080b] border border-white/10 rounded-2xl px-4 py-2.5 text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-indigo-500/40" />
      </div>

      {isI2I && pair.input_image && (
        <div className="bg-white/[0.02] border border-white/5 rounded-3xl p-4 inline-block">
          <div className="text-[10px] font-black uppercase tracking-widest text-gray-500 mb-2">Original Input</div>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={imgUrl(pair.input_image)} alt="input" className="max-h-48 rounded-2xl" />
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {(["A", "B"] as const).map((side) => {
          const v = side === "A" ? pair.variant_a : pair.variant_b;
          const accent = side === "A" ? "indigo" : "emerald";
          const revealedEngine = reveal?.side_map?.[side];
          return (
            <div key={side} className="bg-[#0b0e14] border border-white/5 rounded-[32px] overflow-hidden">
              <div className="flex items-center justify-between px-5 py-3 border-b border-white/5">
                <span className={`text-sm font-black uppercase tracking-widest ${accent === "indigo" ? "text-indigo-300" : "text-emerald-300"}`}>Image {side}</span>
                {revealedEngine && <span className="text-[10px] font-mono text-gray-400">{revealedEngine}</span>}
              </div>
              <div className="bg-black/50 flex items-center justify-center min-h-[300px] p-2">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={imgUrl(v?.url)} alt={`image ${side}`} className="max-h-[60vh] w-auto rounded-2xl object-contain" />
              </div>
            </div>
          );
        })}
      </div>

      {/* Per-metric rating widget */}
      <section className="bg-[#0b0e14] border border-white/10 rounded-[32px] p-8 space-y-6">
        <h3 className="text-sm font-black uppercase tracking-widest text-gray-400">Rate the winner (1–5 per metric)</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {metrics.map((m) => (
            <div key={m} className="space-y-2">
              <div className="flex items-center justify-between">
                <label className="text-xs font-bold text-gray-300">{METRIC_LABELS[m]}</label>
                <span className="text-xs font-mono text-indigo-300">{scores[m] ?? 3}</span>
              </div>
              <input type="range" min={1} max={5} step={1} value={scores[m] ?? 3} onChange={(e) => setMetric(m, parseInt(e.target.value))}
                className="w-full accent-indigo-500" />
            </div>
          ))}
        </div>
        <textarea value={justification} onChange={(e) => setJustification(e.target.value)} placeholder="Justification (optional)"
          className="w-full bg-[#06080b] border border-white/10 rounded-2xl px-4 py-3 text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-indigo-500/40" rows={2} />
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <button onClick={() => submitVote("A")} disabled={submitting} className="py-4 rounded-2xl bg-indigo-500/20 border border-indigo-500/40 text-indigo-200 font-black uppercase tracking-widest text-sm hover:bg-indigo-500/30 transition-all disabled:opacity-40">A Wins</button>
          <button onClick={() => submitVote("tie")} disabled={submitting} className="py-4 rounded-2xl bg-white/5 border border-white/10 text-gray-300 font-black uppercase tracking-widest text-sm hover:bg-white/10 transition-all disabled:opacity-40">Tie</button>
          <button onClick={() => submitVote("B")} disabled={submitting} className="py-4 rounded-2xl bg-emerald-500/20 border border-emerald-500/40 text-emerald-200 font-black uppercase tracking-widest text-sm hover:bg-emerald-500/30 transition-all disabled:opacity-40">B Wins</button>
        </div>
      </section>

      {/* AI judge reveal (after vote) */}
      {reveal && (
        <section className="bg-[#0b0e14] border border-emerald-500/20 rounded-[32px] p-8 space-y-4 animate-in fade-in duration-500">
          <h3 className="text-sm font-black uppercase tracking-widest text-emerald-300">AI Judge</h3>
          <div className="text-xs text-gray-400">Winner: <span className="text-white font-bold">{reveal.ai_eval?.winner_side || "—"}</span> {reveal.ai_eval?.winner_engine && <span className="font-mono text-emerald-300">({reveal.ai_eval.winner_engine})</span>}</div>
          {reveal.ai_eval?.justification && <p className="text-sm text-gray-300 font-light italic">{reveal.ai_eval.justification}</p>}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {(["A", "B"] as const).map((s) => (
              <div key={s} className="bg-[#06080b] border border-white/5 rounded-2xl p-4">
                <div className="text-xs font-black text-gray-400 mb-2">Image {s} — {reveal.side_map?.[s]}</div>
                {Object.entries(reveal.ai_eval?.[s] || {}).filter(([k]) => METRIC_LABELS[k] || k === "overall_score").map(([k, val]) => (
                  <div key={k} className="flex items-center justify-between text-xs py-0.5">
                    <span className="text-gray-500">{METRIC_LABELS[k] || k}</span>
                    <span className="text-gray-200 font-mono">{String(val)}</span>
                  </div>
                ))}
              </div>
            ))}
          </div>
          <button onClick={loadPair} className="px-6 py-3 rounded-2xl bg-indigo-500/20 border border-indigo-500/40 text-indigo-300 font-black uppercase tracking-widest text-xs hover:bg-indigo-500/30 transition-all">Next Pair →</button>
        </section>
      )}
    </div>
  );
}

// ===================================================================
// Results: matchup win-rates + per-metric leaderboard
// ===================================================================
function ResultsPanel() {
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

// ===================================================================
// Shared small components
// ===================================================================
function AutoEvalBadge({ status }: { status?: string }) {
  const s = (status || "pending").toLowerCase();
  const map: Record<string, string> = {
    done: "bg-emerald-500/10 border-emerald-500/20 text-emerald-400",
    error: "bg-red-500/10 border-red-500/20 text-red-400",
    running: "bg-indigo-500/10 border-indigo-500/20 text-indigo-300",
    pending: "bg-white/5 border-white/10 text-gray-500",
  };
  return <span className={`px-3 py-1.5 rounded-full text-[10px] font-black uppercase tracking-widest border ${map[s] || map.pending}`}>Auto-Eval: {s}</span>;
}

function ImagePane({ title, accent, entry }: { title: string; accent: "indigo" | "emerald"; entry?: ResultEntry }) {
  const status = (entry?.status || "generating").toLowerCase();
  const accentText = accent === "indigo" ? "text-indigo-300" : "text-emerald-300";
  const accentDot = accent === "indigo" ? "bg-indigo-500" : "bg-emerald-500";
  return (
    <div className="bg-[#06080b] border border-white/5 rounded-3xl overflow-hidden">
      <div className="flex items-center justify-between px-5 py-3 border-b border-white/5">
        <div className="flex items-center gap-2 min-w-0">
          <span className={`w-1.5 h-1.5 rounded-full ${accentDot} shrink-0`}></span>
          <span className={`text-[11px] font-black uppercase tracking-widest ${accentText} truncate`}>{title}</span>
        </div>
        <span className="text-[9px] font-black uppercase tracking-widest text-gray-500 shrink-0">{status}</span>
      </div>
      <div className="bg-black/50 flex items-center justify-center min-h-[260px] p-2">
        {status === "success" && entry?.url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={imgUrl(entry.url)} alt={title} className="max-h-[50vh] w-auto rounded-2xl object-contain" />
        ) : status === "error" ? (
          <div className="text-center p-6">
            <div className="text-red-400/80 text-[10px] font-black uppercase tracking-widest mb-2">Failed</div>
            <p className="text-[10px] text-gray-600 font-mono break-words max-w-[240px]">{(entry?.error || "").slice(0, 200)}</p>
          </div>
        ) : (
          <div className="flex flex-col items-center gap-3 text-gray-600">
            <div className="w-8 h-8 rounded-full border-2 border-indigo-500/30 border-t-indigo-500 animate-spin"></div>
            <span className="text-[10px] font-black uppercase tracking-widest">Generating...</span>
          </div>
        )}
      </div>
    </div>
  );
}
