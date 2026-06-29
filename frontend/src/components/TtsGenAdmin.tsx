"use client";
import { useState, useEffect, useRef, useCallback } from "react";
import { API_BASE_URL, adminFetch } from "@/lib/api";

// ===================================================================
// TTS "Compose & Run" admin panel — extracted from tts-sxs/page.tsx.
// Lives behind the Admin page's existing auth.
// ===================================================================

const audioUrl = (url?: string) => {
  if (!url) return url;
  if (url.startsWith("/api/tts/media") || url.startsWith("/api/media")) return `${API_BASE_URL}${url}`;
  return url;
};

const AUDIO_TAGS = [
  "[whispers]", "[shouting]", "[laughs]", "[excited]", "[sighs]",
  "[sarcastic]", "[crying]", "[pause]", "[cheerful]", "[angry]",
];

interface ResultEntry {
  status?: string;
  url?: string;
  gcs_url?: string;
  engine?: string;
  model?: string;
  error?: string;
  latency_ms?: number;
  [key: string]: any;
}

interface TtsJob {
  id: string;
  customer?: string;
  prompt_id?: string;
  text?: string;
  prompt?: string;
  style_prompt?: string;
  mode?: string;
  voice?: string;
  language?: string;
  language_autodetected?: boolean;
  results?: Record<string, ResultEntry>;
  side_map?: Record<string, string>;
  ai_eval?: any;
  auto_eval_status?: string;
  [key: string]: any;
}

export default function TtsGenAdmin() {
  const [voices, setVoices] = useState<{ gemini: string[]; elevenlabs: { name: string }[]; languages: { code: string; name: string }[] }>({ gemini: [], elevenlabs: [], languages: [] });

  const [text, setText] = useState("");
  const [voice, setVoice] = useState("Kore");
  const [stylePrompt, setStylePrompt] = useState("");
  const [language, setLanguage] = useState("");
  const [multi, setMulti] = useState(false);
  const [sp1Name, setSp1Name] = useState("Joe");
  const [sp1Voice, setSp1Voice] = useState("Kore");
  const [sp2Name, setSp2Name] = useState("Jane");
  const [sp2Voice, setSp2Voice] = useState("Puck");

  const [casesFile, setCasesFile] = useState<File | null>(null);
  const [parseError, setParseError] = useState("");
  const [caseCount, setCaseCount] = useState(0);

  const [batchId, setBatchId] = useState<string | null>(null);
  const [jobs, setJobs] = useState<TtsJob[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const textRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    fetch(`${API_BASE_URL}/api/tts/voices`)
      .then((r) => r.json())
      .then((d) => setVoices({ gemini: d?.gemini?.voices || [], elevenlabs: d?.elevenlabs?.voices || [], languages: d?.languages || [] }))
      .catch(() => {});
  }, []);

  const insertTag = (tag: string) => {
    const el = textRef.current;
    if (!el) { setText((t) => `${t}${tag} `); return; }
    const start = el.selectionStart ?? text.length;
    const end = el.selectionEnd ?? text.length;
    setText(text.slice(0, start) + tag + text.slice(end));
    requestAnimationFrame(() => {
      el.focus();
      el.selectionStart = el.selectionEnd = start + tag.length;
    });
  };

  const fetchJobs = useCallback(async (batch: string) => {
    try {
      const res = await fetch(`${API_BASE_URL}/api/tts/jobs?batch=${encodeURIComponent(batch)}`);
      const data = await res.json();
      const list: TtsJob[] = Array.isArray(data) ? data : [];
      setJobs(list);
      const allDone =
        list.length > 0 &&
        list.every((j) => ["done", "error"].includes((j.auto_eval_status || "").toLowerCase()));
      if (allDone && pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    } catch { /* ignore */ }
  }, []);

  useEffect(() => {
    if (!batchId) return;
    fetchJobs(batchId);
    pollRef.current = setInterval(() => fetchJobs(batchId), 6000);
    return () => { if (pollRef.current) clearInterval(pollRef.current); pollRef.current = null; };
  }, [batchId, fetchJobs]);

  const runCompose = async () => {
    if (!text.trim() || busy) return;
    setBusy(true); setErr("");
    try {
      const body: any = { text, voice, style_prompt: stylePrompt || undefined, language: language || undefined };
      if (multi) {
        body.mode = "multi";
        body.speakers = [
          { speaker: sp1Name, voice: sp1Voice },
          { speaker: sp2Name, voice: sp2Voice },
        ];
      }
      const res = await adminFetch(`${API_BASE_URL}/api/tts/compose`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d?.detail || `Server responded ${res.status}`);
      }
      const data = await res.json();
      setBatchId(data.batch_id);
      setJobs([]);
    } catch (e: any) {
      setErr(e?.message || "Run failed");
    } finally {
      setBusy(false);
    }
  };

  const handleCasesJson = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    setParseError(""); setCasesFile(null); setCaseCount(0);
    if (!file) return;
    try {
      const parsed = JSON.parse(await file.text());
      const list = Array.isArray(parsed) ? parsed : parsed.cases ?? [];
      if (!Array.isArray(list) || !list.length) throw new Error("JSON must be a non-empty array (or { cases: [...] }).");
      setCasesFile(file); setCaseCount(list.length);
    } catch (e: any) {
      setParseError(e?.message || "Failed to parse JSON");
    }
  };

  const uploadCases = async () => {
    if (!casesFile || busy) return;
    setBusy(true); setErr("");
    try {
      const fd = new FormData();
      fd.append("cases", casesFile, "cases.json");
      const res = await adminFetch(`${API_BASE_URL}/api/tts/upload`, { method: "POST", body: fd });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d?.detail || `Server responded ${res.status}`);
      }
      const data = await res.json();
      setBatchId(data.batch_id);
      setJobs([]);
    } catch (e: any) {
      setErr(e?.message || "Upload failed");
    } finally {
      setBusy(false);
    }
  };

  const retryJob = async (id: string) => {
    await adminFetch(`${API_BASE_URL}/api/tts/jobs/${id}/retry`, { method: "POST" }).catch(() => {});
    if (batchId) fetchJobs(batchId);
  };
  const deleteJob = async (id: string) => {
    await adminFetch(`${API_BASE_URL}/api/tts/jobs/${id}`, { method: "DELETE" }).catch(() => {});
    setJobs((j) => j.filter((x) => x.id !== id));
  };

  const geminiVoices = voices.gemini.length ? voices.gemini : ["Kore", "Puck", "Charon", "Zephyr"];

  return (
    <div className="space-y-8">
      {/* Compose form */}
      <section className="relative group">
        <div className="absolute -inset-1 bg-gradient-to-r from-indigo-500 via-purple-500 to-emerald-500 rounded-[42px] blur opacity-10 group-hover:opacity-20 transition duration-1000"></div>
        <div className="relative bg-[#0b0e14] border border-white/10 rounded-[40px] p-8 md:p-10 shadow-3xl space-y-6">
          <div className="flex items-center gap-3">
            <span className="w-2 h-8 bg-indigo-500 rounded-full"></span>
            <h2 className="text-xl font-light text-white">Compose a Case</h2>
          </div>

          <div className="space-y-3">
            <label className="text-[10px] font-black text-gray-500 uppercase tracking-widest px-1">Transcript</label>
            <textarea
              ref={textRef}
              value={text}
              onChange={(e) => setText(e.target.value)}
              rows={4}
              placeholder={multi ? "Joe: Hey Jane, how's the launch?\nJane: [excited] Better than we imagined!" : "Type what should be spoken. Inline [audio tags] are supported by Gemini."}
              className="w-full bg-[#06080b] border border-white/10 rounded-2xl px-5 py-4 text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-indigo-500/40 transition-all font-mono"
            />
            <div className="flex flex-wrap gap-2">
              {AUDIO_TAGS.map((t) => (
                <button key={t} onClick={() => insertTag(t)} className="px-2.5 py-1 rounded-lg text-[10px] font-bold border bg-white/5 border-white/10 text-gray-400 hover:text-indigo-200 hover:border-indigo-500/40 transition-all font-mono">
                  {t}
                </button>
              ))}
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
            <div className="space-y-2">
              <label className="text-[10px] font-black text-gray-500 uppercase tracking-widest px-1">Voice (Gemini)</label>
              <select value={voice} onChange={(e) => setVoice(e.target.value)} disabled={multi}
                className="w-full bg-[#06080b] border border-white/10 rounded-2xl px-4 py-3 text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-indigo-500/40 disabled:opacity-40">
                {geminiVoices.map((v) => <option key={v} value={v}>{v}</option>)}
              </select>
            </div>
            <div className="space-y-2">
              <label className="text-[10px] font-black text-gray-500 uppercase tracking-widest px-1">Language</label>
              <select value={language} onChange={(e) => setLanguage(e.target.value)}
                className="w-full bg-[#06080b] border border-white/10 rounded-2xl px-4 py-3 text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-indigo-500/40">
                <option value="">Auto-detect</option>
                {voices.languages.map((l) => (
                  <option key={l.code} value={l.code}>{l.name} ({l.code})</option>
                ))}
              </select>
            </div>
            <div className="space-y-2">
              <label className="text-[10px] font-black text-gray-500 uppercase tracking-widest px-1">Multi-speaker</label>
              <button onClick={() => setMulti((m) => !m)}
                className={`w-full px-4 py-3 rounded-2xl text-xs font-black uppercase tracking-widest border transition-all ${multi ? "bg-emerald-500/20 border-emerald-500/40 text-emerald-300" : "bg-white/5 border-white/10 text-gray-400"}`}>
                {multi ? "On (2 speakers)" : "Off (single voice)"}
              </button>
            </div>
          </div>

          {multi && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-5 bg-white/[0.02] border border-white/5 rounded-2xl p-5">
              {[
                { name: sp1Name, setName: setSp1Name, v: sp1Voice, setV: setSp1Voice, label: "Speaker 1" },
                { name: sp2Name, setName: setSp2Name, v: sp2Voice, setV: setSp2Voice, label: "Speaker 2" },
              ].map((s, i) => (
                <div key={i} className="space-y-2">
                  <div className="text-[10px] font-black text-gray-500 uppercase tracking-widest">{s.label}</div>
                  <div className="flex gap-2">
                    <input value={s.name} onChange={(e) => s.setName(e.target.value)} placeholder="Name in transcript"
                      className="flex-1 bg-[#06080b] border border-white/10 rounded-xl px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-emerald-500/40" />
                    <select value={s.v} onChange={(e) => s.setV(e.target.value)}
                      className="bg-[#06080b] border border-white/10 rounded-xl px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-emerald-500/40">
                      {geminiVoices.map((v) => <option key={v} value={v}>{v}</option>)}
                    </select>
                  </div>
                </div>
              ))}
            </div>
          )}

          <div className="space-y-2">
            <label className="text-[10px] font-black text-gray-500 uppercase tracking-widest px-1">Director&apos;s Notes / Style (optional)</label>
            <textarea value={stylePrompt} onChange={(e) => setStylePrompt(e.target.value)} rows={2}
              placeholder="e.g. Warm, upbeat morning-radio host. Bright and welcoming."
              className="w-full bg-[#06080b] border border-white/10 rounded-2xl px-5 py-3 text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-indigo-500/40" />
          </div>

          {err && <div className="text-red-400 text-xs font-bold bg-red-500/10 border border-red-500/20 px-4 py-3 rounded-xl">{err}</div>}

          <button onClick={runCompose} disabled={!text.trim() || busy}
            className="w-full bg-gradient-to-r from-indigo-500 via-purple-600 to-emerald-600 hover:from-indigo-400 hover:to-emerald-500 text-white font-black py-5 rounded-[28px] shadow-[0_20px_50px_rgba(99,102,241,0.25)] transition-all active:scale-[0.98] disabled:opacity-40 uppercase tracking-widest text-sm">
            {busy ? "Launching…" : "Render on Both Engines + AI Judge"}
          </button>
        </div>
      </section>

      <div className="text-center text-[10px] font-black uppercase tracking-widest text-gray-600">— or upload a cases JSON —</div>

      {/* Cases JSON upload */}
      <section className="bg-[#0b0e14] border border-white/10 rounded-[40px] p-8 shadow-3xl space-y-4">
        <div className="flex items-center gap-3">
          <span className="w-2 h-8 bg-emerald-500 rounded-full"></span>
          <h2 className="text-xl font-light text-white">Batch Upload <span className="text-gray-500 text-sm">(array of cases)</span></h2>
        </div>
        <input type="file" accept=".json" onChange={handleCasesJson}
          className="w-full text-sm text-gray-400 bg-[#06080b] border border-white/10 rounded-2xl px-5 py-4 file:mr-4 file:py-2 file:px-5 file:rounded-xl file:border-0 file:text-xs file:font-black file:uppercase file:tracking-widest file:bg-emerald-500/20 file:text-emerald-300 hover:file:bg-emerald-500/30 file:cursor-pointer cursor-pointer focus:outline-none focus:ring-2 focus:ring-emerald-500/40 transition-all" />
        {parseError && <div className="text-red-400 text-xs font-bold bg-red-500/10 border border-red-500/20 px-4 py-3 rounded-xl">{parseError}</div>}
        {caseCount > 0 && <div className="text-emerald-400 text-xs font-bold">{caseCount} case(s) parsed</div>}
        <button onClick={uploadCases} disabled={!casesFile || busy}
          className="w-full bg-gradient-to-r from-emerald-500 to-indigo-600 hover:from-emerald-400 hover:to-indigo-500 text-white font-black py-4 rounded-[24px] transition-all active:scale-[0.98] disabled:opacity-40 uppercase tracking-widest text-sm">
          {busy ? "Launching…" : `Generate + Auto-Eval${caseCount ? ` (${caseCount})` : ""}`}
        </button>
      </section>

      {/* Job table */}
      {batchId && (
        <section className="space-y-5">
          <div className="flex items-center justify-between">
            <h2 className="text-xl font-light text-white flex items-center gap-3">
              <span className="w-2 h-8 bg-indigo-500 rounded-full"></span> Jobs
            </h2>
            <span className="font-mono text-[11px] text-indigo-300 px-3 py-1.5 rounded-full bg-white/5 border border-white/10">batch: {batchId}</span>
          </div>
          {jobs.length === 0 ? (
            <div className="py-24 flex flex-col items-center justify-center text-gray-500 gap-3 bg-white/[0.02] border border-white/5 rounded-[40px]">
              <div className="w-8 h-8 rounded-full border-2 border-indigo-500/30 border-t-indigo-500 animate-spin"></div>
              <p className="font-light tracking-widest uppercase text-xs">Awaiting jobs…</p>
            </div>
          ) : (
            <div className="space-y-5">
              {jobs.map((job) => (
                <JobCard key={job.id} job={job} onRetry={() => retryJob(job.id)} onDelete={() => deleteJob(job.id)} />
              ))}
            </div>
          )}
        </section>
      )}
    </div>
  );
}

function JobCard({ job, onRetry, onDelete }: { job: TtsJob; onRetry: () => void; onDelete: () => void }) {
  const results = job.results || {};
  const sideEngine = (side: string) => results[side]?.engine || job.side_map?.[side] || side;
  return (
    <div className="bg-[#0b0e14] border border-white/5 rounded-[32px] p-6 shadow-3xl">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2 mb-2">
            <span className="px-3 py-1 rounded-full bg-indigo-500/10 border border-indigo-500/20 text-indigo-300 text-[10px] font-black uppercase tracking-widest">{job.mode || "single"}</span>
            {job.language && <span className="px-3 py-1 rounded-full bg-white/5 border border-white/10 text-gray-400 text-[10px] font-black uppercase tracking-widest">{job.language}{job.language_autodetected ? " · auto" : ""}</span>}
          </div>
          <p className="text-gray-300 font-light text-sm whitespace-pre-wrap">&ldquo;{(job.text || job.prompt || "").slice(0, 240)}&rdquo;</p>
          {job.style_prompt && <p className="text-gray-500 text-xs mt-1 italic">Style: {job.style_prompt}</p>}
        </div>
        <div className="flex items-center gap-2">
          <AutoEvalBadge status={job.auto_eval_status} />
          <button onClick={onRetry} className="px-3 py-1.5 rounded-xl text-[10px] font-black uppercase tracking-widest bg-amber-500/10 border border-amber-500/30 text-amber-300 hover:bg-amber-500/20 transition-all">Retry</button>
          <button onClick={onDelete} className="px-3 py-1.5 rounded-xl text-[10px] font-black uppercase tracking-widest bg-red-500/10 border border-red-500/30 text-red-300 hover:bg-red-500/20 transition-all">Delete</button>
        </div>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {(["A", "B"] as const).map((side) => {
          const r = results[side];
          const status = (r?.status || "generating").toLowerCase();
          return (
            <div key={side} className="bg-[#06080b] border border-white/5 rounded-2xl p-4">
              <div className="flex items-center justify-between mb-2">
                <span className="text-[11px] font-black uppercase tracking-widest text-gray-300">Side {side} <span className="text-gray-600 normal-case font-mono">· {sideEngine(side)}</span></span>
                <span className="text-[9px] font-black uppercase tracking-widest text-gray-500">{status}{r?.latency_ms ? ` · ${r.latency_ms}ms` : ""}</span>
              </div>
              {status === "success" && (r?.url || r?.gcs_url) ? (
                <audio controls preload="none" src={audioUrl(r.url || r.gcs_url)} className="w-full" />
              ) : status === "error" ? (
                <p className="text-[10px] text-red-400/80 font-mono break-words">{(r?.error || "").slice(0, 180)}</p>
              ) : (
                <div className="flex items-center gap-2 text-gray-600 py-2"><div className="w-4 h-4 rounded-full border-2 border-indigo-500/30 border-t-indigo-500 animate-spin"></div><span className="text-[10px] font-black uppercase tracking-widest">Generating…</span></div>
              )}
            </div>
          );
        })}
      </div>
      {job.ai_eval?.winner_engine && (
        <div className="mt-3 text-[11px] text-emerald-300 font-bold bg-emerald-500/5 border border-emerald-500/15 rounded-xl px-4 py-2">
          AI judge winner: <span className="font-mono">{job.ai_eval.winner_engine}</span>
          {job.ai_eval.justification ? ` — ${String(job.ai_eval.justification).slice(0, 160)}` : ""}
        </div>
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
  return <span className={`px-3 py-1.5 rounded-full text-[10px] font-black uppercase tracking-widest border ${map[s] || map.pending}`}>Eval: {s}</span>;
}
