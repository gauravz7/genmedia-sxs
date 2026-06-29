"use client";
import { useState } from "react";
import { API_BASE_URL } from "@/lib/api";

// ===================================================================
// TranslateButton — quick Gemini translation of the prompt/text.
// POSTs {text} to /api/sxs/translate and toggles the returned
// translation. Mirrors the inline button in human-eval/ai-evals.
// ===================================================================

export default function TranslateButton({ text }: { text?: string }) {
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
        <p className="mt-2 text-sm text-emerald-200/90 font-light italic leading-relaxed bg-emerald-500/5 border border-emerald-500/15 rounded-xl px-4 py-3 max-w-2xl">
          {translation}
        </p>
      )}
    </div>
  );
}
