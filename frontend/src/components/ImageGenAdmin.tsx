"use client";
import { useState, useEffect, useRef, useCallback } from "react";
import { API_BASE_URL, adminFetch } from "@/lib/api";

// ===================================================================
// Image "Compose & Run" admin panel — extracted from image-sxs/page.tsx.
// Lives behind the Admin page's existing auth.
// ===================================================================

// Local media-URL helper. The backend proxies images at
// `/api/image/media?url=...`; the shared formatUrl() only rewrites
// /api/media + /api/sxs/media, so we prefix our own path here.
const imgUrl = (url?: string): string | undefined => {
  if (!url) return url;
  if (url.startsWith("/api/image/media") || url.startsWith("/api/media")) {
    return `${API_BASE_URL}${url}`;
  }
  return url;
};

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

export default function ImageGenAdmin() {
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
                      <button onClick={async () => { await adminFetch(`${API_BASE_URL}/api/image/jobs/${job.id}`, { method: "DELETE" }).catch(() => {}); setJobs((j) => j.filter((x) => x.id !== job.id)); }}
                        className="px-3 py-1.5 rounded-full text-[10px] font-black uppercase tracking-widest bg-red-500/10 border border-red-500/30 text-red-300 hover:bg-red-500/20 transition-all">Delete</button>
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
