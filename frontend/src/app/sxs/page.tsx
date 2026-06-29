"use client";
import { useState, useEffect, useRef, useCallback } from "react";
import { API_BASE_URL, formatUrl, adminFetch, getAdminToken, setAdminToken, maskPid } from "@/lib/api";
import Nav from "@/components/Nav";

// ===================================================================
// Loose types — the API shape is dynamic
// ===================================================================
interface SxSCase {
  id?: string;
  prompt_id?: string;
  customer?: string;
  prompt?: string;
  text?: string;
  modality?: string;
  mode?: string;
  aspect_ratio?: string;
  ratio?: string;
  duration?: number | string;
  reference_images?: string[];
  ref_images?: string[];
  reference_videos?: string[];
  ref_videos?: string[];
  [key: string]: any;
}

interface ResultEntry {
  status?: string;
  url?: string;
  model?: string;
  error?: string;
  [key: string]: any;
}

interface SxSJob {
  id: string;
  customer?: string;
  prompt_id?: string;
  prompt?: string;
  modality?: string;
  ratio?: string;
  results?: Record<string, ResultEntry>;
  auto_eval_status?: string;
  [key: string]: any;
}

const modelKeyFor = (results: Record<string, ResultEntry> | undefined, needle: string): string | null => {
  if (!results) return null;
  const key = Object.keys(results).find((k) => k.toLowerCase().includes(needle));
  return key ?? null;
};

export default function SxSStudio() {
  // ---------- Admin gate ----------
  const [authed, setAuthed] = useState(false);
  const [authChecked, setAuthChecked] = useState(false);
  const [loginUser, setLoginUser] = useState("");
  const [loginPass, setLoginPass] = useState("");
  const [loginError, setLoginError] = useState("");
  const [loggingIn, setLoggingIn] = useState(false);

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
        } else {
          setLoginError("No token returned");
        }
      } else {
        setLoginError("Invalid credentials");
      }
    } catch {
      setLoginError("Server unavailable");
    } finally {
      setLoggingIn(false);
    }
  };

  const [cases, setCases] = useState<SxSCase[]>([]);
  const [casesFile, setCasesFile] = useState<File | null>(null);
  const [assetFiles, setAssetFiles] = useState<File[]>([]);
  const [parseError, setParseError] = useState<string>("");
  const [isUploading, setIsUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string>("");
  const [batchId, setBatchId] = useState<string | null>(null);
  const [jobs, setJobs] = useState<SxSJob[]>([]);
  const [isPolling, setIsPolling] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ---------- GCS source ----------
  const [gcsUri, setGcsUri] = useState("gs://project-pulse/sxs/consolidated_customer_prompts.json");
  const [catalog, setCatalog] = useState<{ total: number; customers: Record<string, number>; modalities: Record<string, number> } | null>(null);
  const [catalogLoading, setCatalogLoading] = useState(false);
  const [selCustomers, setSelCustomers] = useState<Set<string>>(new Set());
  const [selModalities, setSelModalities] = useState<Set<string>>(new Set());
  const [limit, setLimit] = useState<number>(5);

  const loadCatalog = async () => {
    if (!gcsUri.trim()) return;
    setCatalogLoading(true);
    setUploadError("");
    try {
      const res = await fetch(`${API_BASE_URL}/api/sxs/catalog?cases_uri=${encodeURIComponent(gcsUri.trim())}`);
      if (!res.ok) throw new Error(`Server responded ${res.status}`);
      setCatalog(await res.json());
    } catch (err: any) {
      setUploadError(err?.message || "Failed to load catalog");
      setCatalog(null);
    } finally {
      setCatalogLoading(false);
    }
  };

  const toggle = (set: Set<string>, setter: (s: Set<string>) => void, key: string) => {
    const next = new Set(set);
    if (next.has(key)) next.delete(key); else next.add(key);
    setter(next);
  };

  const selectedCount = () => {
    if (!catalog) return 0;
    let n = 0;
    // Approximate: sum of selected customer counts intersected with modality is unknown
    // without the raw list, so just show min of filters when both narrow.
    const custN = selCustomers.size ? [...selCustomers].reduce((a, c) => a + (catalog.customers[c] || 0), 0) : catalog.total;
    const modN = selModalities.size ? [...selModalities].reduce((a, m) => a + (catalog.modalities[m] || 0), 0) : catalog.total;
    n = Math.min(custN, modN);
    return limit && limit > 0 ? Math.min(n, limit) : n;
  };

  const handleRunGcs = async () => {
    if (!gcsUri.trim() || isUploading) return;
    setIsUploading(true);
    setUploadError("");
    try {
      const body: any = { cases_uri: gcsUri.trim() };
      if (selCustomers.size) body.customers = [...selCustomers];
      if (selModalities.size) body.modalities = [...selModalities];
      if (limit && limit > 0) body.limit = limit;
      const res = await adminFetch(`${API_BASE_URL}/api/sxs/run-gcs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        throw new Error(detail?.detail || `Server responded ${res.status}`);
      }
      const data = await res.json();
      if (!data.batch_id) throw new Error("No batch_id returned.");
      setBatchId(data.batch_id);
      setJobs([]);
    } catch (err: any) {
      setUploadError(err?.message || "Run failed");
    } finally {
      setIsUploading(false);
    }
  };

  // ---------- Cases JSON parsing ----------
  const handleCasesJson = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    setParseError("");
    setCases([]);
    setCasesFile(null);
    if (!file) return;
    try {
      const text = await file.text();
      const parsed = JSON.parse(text);
      const list: SxSCase[] = Array.isArray(parsed) ? parsed : (parsed.cases ?? parsed.items ?? []);
      if (!Array.isArray(list)) throw new Error("JSON must be an array of cases or have a 'cases' array.");
      setCases(list);
      setCasesFile(file);
    } catch (err: any) {
      setParseError(err?.message || "Failed to parse JSON");
    }
  };

  const relOf = (f: File) => ((f as any).webkitRelativePath as string) || f.name;

  const handleAssets = (e: React.ChangeEvent<HTMLInputElement>) => {
    const picked = e.target.files ? Array.from(e.target.files) : [];
    // Accumulate across multiple folder/file picks (so several client folders
    // like tencent/ and invideo/ can be added one at a time). Dedupe by
    // relative-path + size.
    setAssetFiles((prev) => {
      const seen = new Set(prev.map((f) => `${relOf(f)}::${f.size}`));
      const merged = [...prev];
      for (const f of picked) {
        const key = `${relOf(f)}::${f.size}`;
        if (!seen.has(key)) {
          seen.add(key);
          merged.push(f);
        }
      }
      return merged;
    });
    // Allow re-picking the same folder again later.
    e.target.value = "";
  };

  const clearAssets = () => setAssetFiles([]);

  // Mirror the backend's suffix-tolerant resolver so the UI can preview which
  // referenced files are actually covered by the staged uploads.
  const resolveRef = useCallback(
    (ref: string): boolean => {
      const key = ref.replace(/\\/g, "/").replace(/^\/+/, "");
      const rels = assetFiles.map(relOf);
      if (rels.includes(key)) return true;
      if (rels.some((r) => r.endsWith("/" + key))) return true;
      if (rels.some((r) => key.endsWith("/" + r))) return true;
      const base = key.split("/").pop();
      return rels.some((r) => r.split("/").pop() === base);
    },
    [assetFiles]
  );

  const refStats = useCallback(() => {
    let total = 0;
    let matched = 0;
    for (const c of cases) {
      const refs = [
        ...((c.reference_images as string[]) || (c.ref_images as string[]) || []),
        ...((c.reference_videos as string[]) || (c.ref_videos as string[]) || []),
      ];
      for (const r of refs) {
        if (typeof r !== "string" || !r) continue;
        if (r.startsWith("http") || r.startsWith("gs://")) continue; // already a URL
        total += 1;
        if (resolveRef(r)) matched += 1;
      }
    }
    return { total, matched };
  }, [cases, resolveRef]);

  // ---------- Polling ----------
  const fetchJobs = useCallback(async (batch: string) => {
    try {
      const res = await fetch(`${API_BASE_URL}/api/sxs/jobs?batch=${encodeURIComponent(batch)}`);
      const data = await res.json();
      const list: SxSJob[] = Array.isArray(data) ? data : (data.jobs ?? []);
      const mapped = list.map((j) => {
        const results = j.results || {};
        const fixed: Record<string, ResultEntry> = {};
        Object.keys(results).forEach((k) => {
          fixed[k] = { ...results[k], url: formatUrl(results[k]?.url) };
        });
        return { ...j, results: fixed };
      });
      setJobs(mapped);
      const allDone =
        mapped.length > 0 &&
        mapped.every((j) => ["done", "error"].includes((j.auto_eval_status || "").toLowerCase()));
      if (allDone && pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
        setIsPolling(false);
      }
    } catch (err) {
      console.error("Failed to fetch jobs", err);
    }
  }, []);

  useEffect(() => {
    if (!batchId) return;
    setIsPolling(true);
    fetchJobs(batchId);
    pollRef.current = setInterval(() => fetchJobs(batchId), 8000);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
      pollRef.current = null;
    };
  }, [batchId, fetchJobs]);

  // ---------- Upload ----------
  const handleGenerate = async () => {
    if (!cases.length || isUploading) return;
    setIsUploading(true);
    setUploadError("");
    try {
      const fd = new FormData();
      if (casesFile) {
        fd.append("cases", casesFile, "cases.json");
      } else {
        fd.append("cases", new Blob([JSON.stringify(cases)], { type: "application/json" }), "cases.json");
      }
      for (const f of assetFiles) {
        const rel = (f as any).webkitRelativePath || f.name;
        fd.append("files", f, rel);
      }
      const res = await adminFetch(`${API_BASE_URL}/api/sxs/upload`, { method: "POST", body: fd });
      if (!res.ok) throw new Error(`Server responded ${res.status}`);
      const data = await res.json();
      if (!data.batch_id) throw new Error("No batch_id returned from server.");
      setBatchId(data.batch_id);
      setJobs([]);
    } catch (err: any) {
      setUploadError(err?.message || "Upload failed");
    } finally {
      setIsUploading(false);
    }
  };

  // ---------- Derived ----------
  const countList = (c: SxSCase, ...keys: string[]) => {
    for (const k of keys) {
      const v = c[k];
      if (Array.isArray(v)) return v.length;
    }
    return 0;
  };

  // ---------- Login gate ----------
  if (!authChecked) {
    return <div className="min-h-screen bg-[#06080b]" />;
  }

  if (!authed) {
    return (
      <div className="min-h-screen bg-[#06080b] text-gray-100 font-sans selection:bg-indigo-500/30 overflow-x-hidden">
        <div className="fixed inset-0 -z-10 bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-indigo-900/10 via-slate-950 to-[#06080b]"></div>
        <Nav active="sxs" />
        <div className="min-h-screen flex items-center justify-center p-6">
          <div className="max-w-md w-full bg-[#0d1017] border border-white/10 rounded-[40px] p-10 shadow-3xl animate-in fade-in zoom-in-95 duration-500">
            <div className="flex flex-col items-center mb-10">
              <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center shadow-3xl mb-6 font-black text-white">SxS</div>
              <h2 className="text-3xl font-bold text-white tracking-tight">SxS Studio</h2>
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
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#06080b] text-gray-100 font-sans selection:bg-indigo-500/30 overflow-x-hidden">
      <div className="fixed inset-0 -z-10 bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-indigo-900/10 via-slate-950 to-[#06080b]"></div>

      <Nav active="sxs" />

      <main className="max-w-screen-2xl mx-auto px-6 pt-8 pb-20 relative z-10">
        {/* Header */}
        <section className="mb-12 animate-in fade-in slide-in-from-top-4 duration-1000">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-indigo-500/10 border border-indigo-500/20 text-indigo-300 text-[10px] font-black uppercase tracking-widest mb-4">
            Generation Pipeline
          </div>
          <h1 className="text-4xl md:text-5xl font-black text-white tracking-tight leading-tight">
            SxS Studio &mdash;{" "}
            <span className="text-transparent bg-clip-text bg-gradient-to-r from-indigo-400 via-purple-400 to-emerald-400">
              Seedance 2.0 vs Gemini Omni
            </span>
          </h1>
          <p className="text-gray-500 text-sm md:text-base mt-3 font-light max-w-2xl">
            Upload a cases JSON plus the referenced local assets, kick off side-by-side generation with automatic
            Core-5 evaluation, and watch each pair render in real time.
          </p>
        </section>

        <RunLogPanel />

        {/* GCS source card (primary path — assets already in bucket) */}
        <section className="relative group mb-8">
          <div className="absolute -inset-1 bg-gradient-to-r from-emerald-500 via-indigo-500 to-purple-500 rounded-[42px] blur opacity-10 group-hover:opacity-20 transition duration-1000"></div>
          <div className="relative bg-[#0b0e14] border border-white/10 rounded-[40px] p-8 md:p-10 shadow-3xl space-y-6">
            <div className="flex items-center gap-3">
              <span className="w-2 h-8 bg-emerald-500 rounded-full"></span>
              <h2 className="text-xl font-light text-white">Load from GCS <span className="text-gray-500 text-sm">(references already in bucket)</span></h2>
            </div>
            <div className="flex flex-col md:flex-row gap-3">
              <input
                value={gcsUri}
                onChange={(e) => setGcsUri(e.target.value)}
                placeholder="gs://bucket/path/cases.json"
                className="flex-1 bg-[#06080b] border border-white/10 rounded-2xl px-5 py-4 text-sm text-gray-200 font-mono focus:outline-none focus:ring-2 focus:ring-emerald-500/40 transition-all"
              />
              <button
                onClick={loadCatalog}
                disabled={catalogLoading}
                className="px-6 py-4 rounded-2xl bg-emerald-500/20 border border-emerald-500/30 text-emerald-300 font-black uppercase tracking-widest text-xs hover:bg-emerald-500/30 transition-all disabled:opacity-40"
              >
                {catalogLoading ? "Loading…" : "Load Catalog"}
              </button>
            </div>

            {catalog && (
              <div className="space-y-5 animate-in fade-in duration-300">
                <div className="text-xs text-gray-400 font-bold">{catalog.total} cases in source</div>

                <div>
                  <div className="text-[10px] font-black uppercase tracking-widest text-gray-500 mb-2">Customers {selCustomers.size ? `(${selCustomers.size} selected)` : "(all)"}</div>
                  <div className="flex flex-wrap gap-2">
                    {Object.entries(catalog.customers).map(([name, n]) => (
                      <button key={name} onClick={() => toggle(selCustomers, setSelCustomers, name)}
                        className={`px-3 py-1.5 rounded-xl text-[11px] font-bold border transition-all ${selCustomers.has(name) ? "bg-indigo-500/30 border-indigo-500/50 text-indigo-200" : "bg-white/5 border-white/10 text-gray-400 hover:text-white"}`}>
                        {name} <span className="text-gray-500 font-mono">{n}</span>
                      </button>
                    ))}
                  </div>
                </div>

                <div>
                  <div className="text-[10px] font-black uppercase tracking-widest text-gray-500 mb-2">Modalities {selModalities.size ? `(${selModalities.size} selected)` : "(all)"}</div>
                  <div className="flex flex-wrap gap-2 max-h-40 overflow-y-auto">
                    {Object.entries(catalog.modalities).map(([name, n]) => (
                      <button key={name} onClick={() => toggle(selModalities, setSelModalities, name)}
                        className={`px-3 py-1.5 rounded-xl text-[11px] font-bold border transition-all ${selModalities.has(name) ? "bg-purple-500/30 border-purple-500/50 text-purple-200" : "bg-white/5 border-white/10 text-gray-400 hover:text-white"}`}>
                        {name} <span className="text-gray-500 font-mono">{n}</span>
                      </button>
                    ))}
                  </div>
                </div>

                <div className="flex flex-wrap items-center gap-4">
                  <label className="text-[10px] font-black uppercase tracking-widest text-gray-500">Limit</label>
                  <input type="number" min={0} value={limit} onChange={(e) => setLimit(parseInt(e.target.value || "0"))}
                    className="w-24 bg-[#06080b] border border-white/10 rounded-xl px-3 py-2 text-sm text-gray-200 font-mono focus:outline-none focus:ring-2 focus:ring-emerald-500/40" />
                  <span className="text-[11px] text-amber-400/80 font-bold">≈ {selectedCount()} case(s) will run · Omni is ~3 QPM, keep batches small</span>
                </div>

                <button
                  onClick={handleRunGcs}
                  disabled={isUploading}
                  className="w-full bg-gradient-to-r from-emerald-500 via-indigo-600 to-purple-600 hover:from-emerald-400 hover:to-purple-500 text-white font-black py-5 rounded-[28px] shadow-[0_20px_50px_rgba(16,185,129,0.2)] transition-all active:scale-[0.98] disabled:opacity-40 uppercase tracking-widest text-sm"
                >
                  {isUploading ? "Launching…" : `Generate + Auto-Eval (${selectedCount()})`}
                </button>
              </div>
            )}
          </div>
        </section>

        <div className="text-center text-[10px] font-black uppercase tracking-widest text-gray-600 mb-8">— or upload from your machine —</div>

        {/* Upload card */}
        <section className="relative group mb-12">
          <div className="absolute -inset-1 bg-gradient-to-r from-indigo-500 via-purple-500 to-emerald-500 rounded-[42px] blur opacity-10 group-hover:opacity-20 transition duration-1000"></div>
          <div className="relative bg-[#0b0e14] border border-white/10 rounded-[40px] p-8 md:p-10 shadow-3xl space-y-8">
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
              {/* Cases JSON */}
              <div className="space-y-3">
                <label className="text-[10px] font-black text-gray-500 uppercase tracking-widest px-1">Cases JSON</label>
                <input
                  type="file"
                  accept=".json"
                  onChange={handleCasesJson}
                  className="w-full text-sm text-gray-400 bg-[#06080b] border border-white/10 rounded-2xl px-5 py-4 file:mr-4 file:py-2 file:px-5 file:rounded-xl file:border-0 file:text-xs file:font-black file:uppercase file:tracking-widest file:bg-indigo-500/20 file:text-indigo-300 hover:file:bg-indigo-500/30 file:cursor-pointer cursor-pointer focus:outline-none focus:ring-2 focus:ring-indigo-500/40 transition-all"
                />
                {parseError && (
                  <div className="text-red-400 text-xs font-bold bg-red-500/10 border border-red-500/20 px-4 py-3 rounded-xl">
                    {parseError}
                  </div>
                )}
                {cases.length > 0 && (
                  <div className="text-emerald-400 text-xs font-bold">{cases.length} case(s) parsed</div>
                )}
              </div>

              {/* Assets */}
              <div className="space-y-3">
                <label className="text-[10px] font-black text-gray-500 uppercase tracking-widest px-1">
                  Asset Folders (add each client folder — picks accumulate)
                </label>
                <input
                  type="file"
                  multiple
                  {...({ webkitdirectory: "" } as any)}
                  onChange={handleAssets}
                  className="w-full text-sm text-gray-400 bg-[#06080b] border border-white/10 rounded-2xl px-5 py-4 file:mr-4 file:py-2 file:px-5 file:rounded-xl file:border-0 file:text-xs file:font-black file:uppercase file:tracking-widest file:bg-purple-500/20 file:text-purple-300 hover:file:bg-purple-500/30 file:cursor-pointer cursor-pointer focus:outline-none focus:ring-2 focus:ring-purple-500/40 transition-all"
                />
                <p className="text-[10px] text-gray-600 px-1 leading-relaxed">
                  Pick the parent folder containing all client subfolders (e.g. one folder holding both
                  <span className="text-gray-400"> tencent/</span> and <span className="text-gray-400">invideo/</span>),
                  or add each client folder one at a time — selections accumulate. A leading folder name is matched automatically.
                </p>
                <div className="space-y-1">
                  <label className="text-[10px] font-black text-gray-600 uppercase tracking-widest px-1">
                    Fallback: pick individual files
                  </label>
                  <input
                    type="file"
                    multiple
                    onChange={handleAssets}
                    className="w-full text-xs text-gray-500 bg-[#06080b] border border-white/10 rounded-2xl px-5 py-3 file:mr-4 file:py-1.5 file:px-4 file:rounded-lg file:border-0 file:text-[10px] file:font-black file:uppercase file:tracking-widest file:bg-white/10 file:text-gray-300 file:cursor-pointer cursor-pointer focus:outline-none focus:ring-2 focus:ring-white/20 transition-all"
                  />
                </div>
                {assetFiles.length > 0 && (
                  <div className="flex items-center justify-between gap-3">
                    <div className="text-emerald-400 text-xs font-bold">{assetFiles.length} asset file(s) staged</div>
                    <button onClick={clearAssets} className="text-[10px] font-black uppercase tracking-widest text-gray-500 hover:text-red-400 transition-colors">
                      Clear
                    </button>
                  </div>
                )}
                {cases.length > 0 && (() => {
                  const { total, matched } = refStats();
                  if (total === 0) return null;
                  const ok = matched === total;
                  return (
                    <div className={`text-xs font-bold px-4 py-3 rounded-xl border ${ok ? "text-emerald-400 bg-emerald-500/10 border-emerald-500/20" : "text-amber-400 bg-amber-500/10 border-amber-500/20"}`}>
                      {matched}/{total} referenced files resolved{ok ? " ✓" : " — add the missing client folder(s)"}
                    </div>
                  );
                })()}
              </div>
            </div>

            {uploadError && (
              <div className="text-red-400 text-xs font-bold bg-red-500/10 border border-red-500/20 px-4 py-3 rounded-xl">
                {uploadError}
              </div>
            )}

            <button
              onClick={handleGenerate}
              disabled={!cases.length || isUploading}
              className="w-full bg-gradient-to-r from-indigo-500 via-purple-600 to-emerald-600 hover:from-indigo-400 hover:to-emerald-500 text-white font-black py-5 rounded-[28px] shadow-[0_20px_50px_rgba(99,102,241,0.25)] transition-all active:scale-[0.98] disabled:opacity-40 disabled:cursor-not-allowed uppercase tracking-widest text-sm"
            >
              {isUploading ? "Uploading & Launching..." : "Generate + Auto-Eval"}
            </button>
          </div>
        </section>

        {/* Cases preview */}
        {cases.length > 0 && !batchId && (
          <section className="mb-12 bg-white/[0.02] border border-white/5 rounded-[40px] p-8 animate-in fade-in slide-in-from-bottom-4 duration-500">
            <h2 className="text-xl font-light text-white mb-6 flex items-center gap-3">
              <span className="w-2 h-8 bg-indigo-500 rounded-full"></span> Case Preview
            </h2>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-[10px] font-black uppercase tracking-widest text-gray-500 border-b border-white/10">
                    <th className="text-left py-3 px-3">Customer</th>
                    <th className="text-left py-3 px-3">ID</th>
                    <th className="text-left py-3 px-3">Modality</th>
                    <th className="text-left py-3 px-3"># Ref Images</th>
                    <th className="text-left py-3 px-3"># Ref Videos</th>
                    <th className="text-left py-3 px-3">Aspect Ratio</th>
                    <th className="text-left py-3 px-3">Duration</th>
                  </tr>
                </thead>
                <tbody>
                  {cases.map((c, i) => (
                    <tr key={i} className="border-b border-white/5 hover:bg-white/[0.02] transition-colors">
                      <td className="py-3 px-3 text-gray-300 font-medium">{c.customer ?? "—"}</td>
                      <td className="py-3 px-3 text-indigo-300 font-mono text-xs">{maskPid(c.id ?? c.prompt_id) || "—"}</td>
                      <td className="py-3 px-3 text-gray-400 uppercase text-xs">{c.modality ?? c.mode ?? "—"}</td>
                      <td className="py-3 px-3 text-gray-400 font-mono">{countList(c, "reference_images", "ref_images")}</td>
                      <td className="py-3 px-3 text-gray-400 font-mono">{countList(c, "reference_videos", "ref_videos")}</td>
                      <td className="py-3 px-3 text-gray-400 font-mono">{c.aspect_ratio ?? c.ratio ?? "—"}</td>
                      <td className="py-3 px-3 text-gray-400 font-mono">{c.duration ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}

        {/* Jobs progress */}
        {batchId && (
          <section className="space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-500">
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
                {jobs.map((job) => {
                  const seedanceKey = modelKeyFor(job.results, "seedance");
                  const omniKey = modelKeyFor(job.results, "omni");
                  return (
                    <div key={job.id} className="bg-[#0b0e14] border border-white/5 rounded-[40px] p-8 shadow-3xl">
                      <div className="flex flex-wrap items-center justify-between gap-4 mb-6">
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-2 mb-2">
                            {job.customer && (
                              <span className="px-3 py-1 rounded-full bg-indigo-500/10 border border-indigo-500/20 text-indigo-300 text-[10px] font-black uppercase tracking-widest">
                                {job.customer}
                              </span>
                            )}
                            {job.modality && (
                              <span className="px-3 py-1 rounded-full bg-purple-500/10 border border-purple-500/20 text-purple-300 text-[10px] font-black uppercase tracking-widest">
                                {job.modality}
                              </span>
                            )}
                            {job.ratio && (
                              <span className="px-3 py-1 rounded-full bg-white/5 border border-white/10 text-gray-400 text-[10px] font-black uppercase tracking-widest">
                                {job.ratio}
                              </span>
                            )}
                          </div>
                          <p className="text-gray-300 font-light text-sm">
                            &ldquo;{job.prompt || "No prompt"}&rdquo;
                          </p>
                          <TranslateButton text={job.prompt} />
                        </div>
                        <AutoEvalBadge status={job.auto_eval_status} />
                      </div>

                      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                        <ModelResultPane label="Seedance 2.0" accent="indigo" entry={seedanceKey ? job.results?.[seedanceKey] : undefined} ratio={job.ratio} />
                        <ModelResultPane label="Gemini Omni" accent="emerald" entry={omniKey ? job.results?.[omniKey] : undefined} ratio={job.ratio} />
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </section>
        )}
      </main>
    </div>
  );
}

function TranslateButton({ text }: { text?: string }) {
  const [translation, setTranslation] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [show, setShow] = useState(false);

  const run = async () => {
    if (!text) return;
    if (translation) { setShow((s) => !s); return; }
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE_URL}/api/sxs/translate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });
      const data = await res.json();
      setTranslation(data.translation || "(no translation)");
      setShow(true);
    } catch {
      setTranslation("Translation failed");
      setShow(true);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="mt-2">
      <button
        onClick={run}
        disabled={loading || !text}
        className="inline-flex items-center gap-1.5 px-3 py-1 rounded-lg text-[10px] font-black uppercase tracking-widest bg-indigo-500/10 border border-indigo-500/20 text-indigo-300 hover:bg-indigo-500/20 transition-all disabled:opacity-40"
      >
        {loading ? "Translating…" : translation ? (show ? "Hide English" : "Show English") : "Translate to English"}
      </button>
      {show && translation && (
        <p className="mt-2 text-sm text-emerald-200/90 font-light italic leading-relaxed bg-emerald-500/5 border border-emerald-500/15 rounded-xl px-4 py-3">
          {translation}
        </p>
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
  const cls = map[s] || map.pending;
  return (
    <span className={`px-3 py-1.5 rounded-full text-[10px] font-black uppercase tracking-widest border ${cls}`}>
      Auto-Eval: {s}
    </span>
  );
}

function ModelResultPane({
  label,
  accent,
  entry,
  ratio,
}: {
  label: string;
  accent: "indigo" | "emerald";
  entry?: ResultEntry;
  ratio?: string;
}) {
  const status = (entry?.status || "generating").toLowerCase();
  const isPortrait = ratio === "9:16";
  const accentText = accent === "indigo" ? "text-indigo-300" : "text-emerald-300";
  const accentDot = accent === "indigo" ? "bg-indigo-500" : "bg-emerald-500";

  return (
    <div className="bg-[#06080b] border border-white/5 rounded-3xl overflow-hidden">
      <div className="flex items-center justify-between px-5 py-3 border-b border-white/5">
        <div className="flex items-center gap-2">
          <span className={`w-1.5 h-1.5 rounded-full ${accentDot}`}></span>
          <span className={`text-[11px] font-black uppercase tracking-widest ${accentText}`}>{label}</span>
        </div>
        <span className="text-[9px] font-black uppercase tracking-widest text-gray-500">{status}</span>
      </div>
      <div className={`${isPortrait ? "aspect-[9/16] max-h-[60vh]" : "aspect-video"} bg-black/50 flex items-center justify-center`}>
        {status === "success" && entry?.url ? (
          <video controls preload="metadata" src={entry.url} className={`w-full h-full ${isPortrait ? "object-contain" : "object-cover"}`} />
        ) : status === "error" ? (
          <div className="text-center p-6">
            <div className="text-red-400/80 text-[10px] font-black uppercase tracking-widest mb-2">Failed</div>
            <p className="text-[10px] text-gray-600 font-mono break-words max-w-[240px]">{(entry?.error || "").slice(0, 160)}</p>
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

// ===================================================================
// RunLogPanel — persistent progress tracker (reads Firestore-backed
// /api/sxs/runs). Lets you Resume incomplete pairs after an interruption.
// ===================================================================
function RunLogPanel() {
  const [summary, setSummary] = useState<any>(null);
  const [runs, setRuns] = useState<any[]>([]);
  const [busy, setBusy] = useState<string>("");
  const [msg, setMsg] = useState<string>("");

  const load = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/api/sxs/runs`);
      if (!res.ok) return;
      const data = await res.json();
      setSummary(data.summary || null);
      setRuns(data.runs || []);
    } catch { /* ignore */ }
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 8000);
    return () => clearInterval(t);
  }, [load]);

  const action = async (path: string, label: string) => {
    setBusy(label); setMsg("");
    try {
      const res = await adminFetch(`${API_BASE_URL}${path}`, { method: "POST" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data?.detail || `HTTP ${res.status}`);
      setMsg(data.message || `${label}: ${data.resuming ?? data.retrying ?? data.count ?? 0} pair(s) queued`);
      load();
    } catch (e: any) {
      setMsg(`${label} failed: ${e?.message || "error"}`);
    } finally {
      setBusy("");
    }
  };

  const tiles = [
    { k: "cases_done", label: "Done", cls: "text-emerald-400" },
    { k: "cases_failed", label: "Failed", cls: "text-red-400" },
    { k: "cases_in_progress", label: "In Progress", cls: "text-indigo-300" },
    { k: "cases_touched", label: "Total", cls: "text-white" },
  ];

  return (
    <section className="mb-8 bg-[#0b0e14] border border-white/10 rounded-[32px] p-6 md:p-8 shadow-3xl">
      <div className="flex items-center justify-between gap-4 mb-5 flex-wrap">
        <div className="flex items-center gap-3">
          <span className="w-2 h-8 bg-indigo-500 rounded-full"></span>
          <h2 className="text-xl font-light text-white">Run Log <span className="text-gray-500 text-sm">— persistent progress</span></h2>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => action("/api/sxs/resume", "Resume")} disabled={!!busy}
            className="px-4 py-2 rounded-xl text-[11px] font-black uppercase tracking-widest bg-indigo-500/20 border border-indigo-500/40 text-indigo-200 hover:bg-indigo-500/30 transition-all disabled:opacity-40">
            {busy === "Resume" ? "Resuming…" : "Resume Incomplete"}
          </button>
          <button onClick={() => action("/api/sxs/retry-failures", "Retry")} disabled={!!busy}
            className="px-4 py-2 rounded-xl text-[11px] font-black uppercase tracking-widest bg-red-500/10 border border-red-500/30 text-red-300 hover:bg-red-500/20 transition-all disabled:opacity-40">
            {busy === "Retry" ? "Retrying…" : "Retry Failed"}
          </button>
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
        {tiles.map(t => (
          <div key={t.k} className="bg-[#06080b] border border-white/5 rounded-2xl p-4 text-center">
            <div className={`text-3xl font-black ${t.cls}`}>{summary?.[t.k] ?? "—"}</div>
            <div className="text-[10px] font-black uppercase tracking-widest text-gray-500 mt-1">{t.label}</div>
          </div>
        ))}
      </div>

      {msg && <div className="text-xs font-bold text-emerald-300 bg-emerald-500/10 border border-emerald-500/20 rounded-xl px-4 py-2 mb-3">{msg}</div>}

      {runs.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-[10px] font-black uppercase tracking-widest text-gray-500 border-b border-white/10">
                <th className="text-left py-2 px-2">Batch</th>
                <th className="text-left py-2 px-2">Filters</th>
                <th className="text-right py-2 px-2">Launched</th>
                <th className="text-right py-2 px-2">Skipped (done)</th>
              </tr>
            </thead>
            <tbody>
              {runs.slice(0, 8).map((r: any) => {
                const f = r.filters || {};
                const filt = [
                  f.randomize ? "random" : null,
                  (f.customers || []).length ? `cust:${(f.customers || []).join(",")}` : null,
                  (f.modalities || []).length ? `mod:${(f.modalities || []).length}` : null,
                  f.limit ? `limit:${f.limit}` : null,
                ].filter(Boolean).join(" · ") || "all";
                return (
                  <tr key={r.batch_id} className="border-b border-white/5">
                    <td className="py-2 px-2 font-mono text-indigo-300">{r.batch_id}</td>
                    <td className="py-2 px-2 text-gray-400">{filt}</td>
                    <td className="py-2 px-2 text-right text-gray-300 font-mono">{r.launched_count ?? 0}</td>
                    <td className="py-2 px-2 text-right text-gray-500 font-mono">{r.skipped_existing ?? 0}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {runs.length === 0 && <p className="text-xs text-gray-600">No runs recorded yet.</p>}
    </section>
  );
}
