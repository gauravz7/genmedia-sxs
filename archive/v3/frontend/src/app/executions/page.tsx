"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Boxes,
  Loader2,
  Sparkles,
  Fingerprint,
  Clock,
  RefreshCw,
  Copy,
  Check,
} from "lucide-react";
import Nav from "@/components/Nav";
import MediaView from "@/components/MediaView";
import { api, Case, Execution, maskPid, ModelSpec, Modality } from "@/lib/api";

// Stable, content-derived case id so the same prompt maps to one case
// (lets the no-rerun guarantee + "executions by case" demonstrate cleanly).
function caseIdFor(prompt: string, modality: string): string {
  const s = `${modality}:${prompt.trim().toLowerCase().replace(/\s+/g, " ")}`;
  let h = 5381;
  for (let i = 0; i < s.length; i++) h = ((h << 5) + h + s.charCodeAt(i)) >>> 0;
  return `case_${h.toString(16).padStart(8, "0")}`;
}

// Voice catalogs per TTS provider (name -> shown; provider resolves id).
const GEMINI_VOICES = [
  "Kore", "Puck", "Zephyr", "Charon", "Fenrir", "Leda", "Orus", "Aoede",
  "Callirrhoe", "Autonoe", "Enceladus", "Iapetus", "Umbriel", "Algieba",
  "Despina", "Erinome", "Algenib", "Rasalgethi", "Laomedeia", "Achernar",
];
const ELEVEN_VOICES = ["George", "Sarah", "Laura", "Charlie", "Rachel"];

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="text-[10px] font-black uppercase tracking-widest text-gray-500">
        {label}
      </span>
      <div className="mt-1.5">{children}</div>
    </label>
  );
}

export default function ExecutionsPage() {
  const [models, setModels] = useState<ModelSpec[]>([]);
  const [modelId, setModelId] = useState<string>("");
  const [prompt, setPrompt] = useState("");
  const [seed, setSeed] = useState("");
  const [aspect, setAspect] = useState("");
  const [voice, setVoice] = useState("");

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<Execution | null>(null);
  const [wasCached, setWasCached] = useState(false);
  const [caseExecs, setCaseExecs] = useState<Execution[]>([]);
  const [copied, setCopied] = useState(false);

  const spec = useMemo(
    () => models.find((m) => m.id === modelId),
    [models, modelId]
  );
  const modality = (spec?.type || "t2i") as Modality;
  const isTTS = modality === "tts";
  const isVideo = modality === "t2v" || modality === "i2v" || modality === "r2v";
  const voiceOptions =
    spec?.provider === "elevenlabs" ? ELEVEN_VOICES : GEMINI_VOICES;
  const caseId = prompt.trim() ? caseIdFor(prompt, modality) : "";

  // Keep the selected voice valid for the active TTS provider.
  useEffect(() => {
    if (isTTS && !voiceOptions.includes(voice)) setVoice(voiceOptions[0]);
  }, [isTTS, voiceOptions, voice]);

  useEffect(() => {
    api
      .listModels(true)
      .then((m) => {
        setModels(m);
        if (m.length) setModelId(m[0].id);
      })
      .catch((e) => setError(String(e)));
  }, []);

  const refreshCase = async (id: string) => {
    try {
      setCaseExecs(await api.executionsByCase(id));
    } catch {
      /* ignore */
    }
  };

  const buildParams = (): Record<string, unknown> => {
    const p: Record<string, unknown> = {};
    if (seed.trim()) p.seed = Number(seed) || seed;
    if (isTTS) {
      if (voice) p.voice = voice;
    } else if (aspect.trim()) {
      p.aspect_ratio = aspect.trim();
    }
    return p;
  };

  const generate = async () => {
    if (!spec || !prompt.trim()) return;
    setBusy(true);
    setError(null);
    const params = buildParams();
    const kase: Case = {
      id: caseId,
      prompt: prompt.trim(),
      modality,
      mode: spec.type,
      params,
    };
    const priorId = result?.id;
    try {
      let exec = await api.generate({ case: kase, spec, params });
      setResult(exec);
      // If the id came back identical to a prior generation, the no-rerun
      // guarantee served a cached execution rather than regenerating.
      setWasCached(!!priorId && priorId === exec.id);
      // Generation can be async (provider returns "generating"): poll the
      // execution until it resolves to success/error.
      let tries = 0;
      while (
        (exec.status === "generating" || exec.status === "pending") &&
        tries < 90
      ) {
        await new Promise((r) => setTimeout(r, 3000));
        exec = await api.getExecution(exec.id);
        setResult(exec);
        tries++;
      }
      await refreshCase(caseId);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  const copyId = () => {
    if (!result) return;
    navigator.clipboard?.writeText(result.id);
    setCopied(true);
    setTimeout(() => setCopied(false), 1200);
  };

  return (
    <div className="min-h-screen bg-[#06080b] text-gray-100 font-sans">
      <div className="fixed inset-0 -z-10 bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-indigo-900/15 via-slate-950 to-[#06080b]" />
      <Nav active="executions" />

      <main className="max-w-screen-2xl mx-auto px-6 py-10 grid grid-cols-1 lg:grid-cols-[420px_1fr] gap-8">
        {/* Left: generation form */}
        <section className="space-y-5">
          <div className="flex items-center gap-3">
            <Boxes className="w-6 h-6 text-emerald-400" />
            <h1 className="text-2xl font-black tracking-tight">Request an Execution</h1>
          </div>
          <p className="text-sm text-gray-500 leading-relaxed">
            One <code className="text-emerald-300">(case, model, params)</code> run. Re-requesting
            the same inputs returns the cached execution id — no regeneration.
          </p>

          <div className="bg-[#0b0e14] border border-white/5 rounded-3xl p-6 space-y-5">
            <Field label="Model">
              <select
                value={modelId}
                onChange={(e) => setModelId(e.target.value)}
                className="w-full bg-black/40 border border-white/10 rounded-xl px-3 py-2.5 text-sm focus:border-indigo-500/50 outline-none"
              >
                {models.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name || m.id} · {m.type} · {m.provider}
                  </option>
                ))}
              </select>
            </Field>

            <Field label={isTTS ? "Script (spoken text)" : "Prompt"}>
              <textarea
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                rows={4}
                placeholder={
                  isTTS
                    ? "Welcome to Project Pulse — a blind side-by-side of generative voices…"
                    : "A cinematic drone shot over a foggy pine forest at dawn…"
                }
                className="w-full bg-black/40 border border-white/10 rounded-xl px-3 py-2.5 text-sm focus:border-indigo-500/50 outline-none resize-y"
              />
            </Field>

            <div className="grid grid-cols-2 gap-4">
              <Field label="Seed (blank = unseeded)">
                <input
                  value={seed}
                  onChange={(e) => setSeed(e.target.value)}
                  placeholder="unseeded"
                  className="w-full bg-black/40 border border-white/10 rounded-xl px-3 py-2.5 text-sm focus:border-indigo-500/50 outline-none"
                />
              </Field>
              {isTTS ? (
                <Field label="Voice">
                  <select
                    value={voice}
                    onChange={(e) => setVoice(e.target.value)}
                    className="w-full bg-black/40 border border-white/10 rounded-xl px-3 py-2.5 text-sm focus:border-indigo-500/50 outline-none"
                  >
                    {voiceOptions.map((v) => (
                      <option key={v} value={v}>
                        {v}
                      </option>
                    ))}
                  </select>
                </Field>
              ) : (
                <Field label="Aspect ratio">
                  <input
                    value={aspect}
                    onChange={(e) => setAspect(e.target.value)}
                    placeholder={isVideo ? "16:9" : "1:1"}
                    className="w-full bg-black/40 border border-white/10 rounded-xl px-3 py-2.5 text-sm focus:border-indigo-500/50 outline-none"
                  />
                </Field>
              )}
            </div>

            {caseId && (
              <div className="text-[10px] font-mono text-gray-600 flex items-center gap-2">
                <Fingerprint className="w-3.5 h-3.5" /> case&nbsp;
                <span className="text-gray-400">{maskPid(caseId)}</span>
                <span className="text-gray-700">· modality {modality}</span>
              </div>
            )}

            <button
              onClick={generate}
              disabled={busy || !prompt.trim() || !spec}
              className="w-full flex items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-indigo-500 to-emerald-500 text-white font-black uppercase tracking-widest text-xs py-3 disabled:opacity-40 hover:opacity-90 transition"
            >
              {busy ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" /> Generating…
                </>
              ) : (
                <>
                  <Sparkles className="w-4 h-4" /> Generate
                </>
              )}
            </button>
            {busy && (
              <p className="text-[10px] text-gray-600 text-center">
                Real provider call — video can take 30–120s.
              </p>
            )}
            {error && (
              <p className="text-xs text-red-400 font-mono bg-red-950/30 border border-red-500/20 rounded-xl p-3 break-all">
                {error}
              </p>
            )}
          </div>
        </section>

        {/* Right: result + case executions */}
        <section className="space-y-6">
          {result ? (
            <div className="bg-[#0b0e14] border border-white/5 rounded-3xl p-6 space-y-4">
              {wasCached && (
                <div className="flex items-center gap-2 px-3 py-2 rounded-xl bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 text-[11px] font-black uppercase tracking-widest">
                  <RefreshCw className="w-4 h-4" /> No-rerun: identical id returned from cache
                </div>
              )}
              <div className="flex items-start justify-between gap-4">
                <div>
                  <div className="text-[10px] font-black uppercase tracking-widest text-gray-500">
                    Execution
                  </div>
                  <button
                    onClick={copyId}
                    className="mt-1 flex items-center gap-2 font-mono text-sm text-white hover:text-indigo-300"
                    title="copy execution id"
                  >
                    {result.id}
                    {copied ? (
                      <Check className="w-3.5 h-3.5 text-emerald-400" />
                    ) : (
                      <Copy className="w-3.5 h-3.5 text-gray-600" />
                    )}
                  </button>
                </div>
                <span
                  className={`px-3 py-1 rounded-full text-[10px] font-black uppercase tracking-widest border ${
                    result.status === "success"
                      ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-400"
                      : result.status === "error"
                        ? "bg-red-500/10 border-red-500/30 text-red-400"
                        : "bg-indigo-500/10 border-indigo-500/30 text-indigo-300"
                  }`}
                >
                  {result.status}
                </span>
              </div>

              <MediaView execution={result} className="w-full max-h-[60vh] min-h-[280px]" />

              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-[11px]">
                <Meta k="model" v={result.model_id} />
                <Meta k="provider" v={result.provider || "—"} />
                <Meta k="source" v={result.source || "—"} />
                <Meta
                  k="latency"
                  v={
                    typeof result.metadata?.latency_s === "number"
                      ? `${(result.metadata.latency_s as number).toFixed(1)}s`
                      : "—"
                  }
                />
              </div>
            </div>
          ) : (
            <div className="bg-[#0b0e14] border border-white/5 border-dashed rounded-3xl p-16 text-center text-gray-600">
              <Boxes className="w-10 h-10 mx-auto mb-3 opacity-40" />
              <p className="text-sm">Your generated execution will appear here.</p>
            </div>
          )}

          {caseExecs.length > 0 && (
            <div className="bg-[#0b0e14] border border-white/5 rounded-3xl p-6">
              <div className="flex items-center gap-2 mb-4">
                <Clock className="w-4 h-4 text-indigo-400" />
                <h2 className="text-sm font-black uppercase tracking-widest text-gray-400">
                  Executions for this case ({caseExecs.length})
                </h2>
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3">
                {caseExecs.map((e) => (
                  <div
                    key={e.id}
                    className="rounded-2xl border border-white/5 bg-black/30 p-2 space-y-2"
                  >
                    <MediaView execution={e} className="w-full aspect-square" />
                    <div className="text-[9px] font-mono text-gray-500 truncate" title={e.model_id}>
                      {e.model_id}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </section>
      </main>
    </div>
  );
}

function Meta({ k, v }: { k: string; v: string }) {
  return (
    <div className="rounded-xl border border-white/5 bg-black/30 px-3 py-2">
      <div className="text-[9px] font-black uppercase tracking-widest text-gray-600">{k}</div>
      <div className="text-gray-300 font-mono truncate" title={v}>
        {v}
      </div>
    </div>
  );
}
