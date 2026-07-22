"use client";
import { useState, useEffect } from "react";
import { API_BASE_URL } from "@/lib/api";

// ===================================================================
// TranslateButton — on-demand Gemini translation of the current prompt.
//
// Translation is opt-in per prompt (most prompts are already English, so
// auto-translating every one is wasteful):
//   • Nothing is translated until the user clicks "Translate to English".
//   • Clicking again toggles the shown translation for THIS prompt.
//   • When the prompt changes, state resets so the button returns to
//     "Translate to English" and never shows the previous prompt's text.
// ===================================================================

export default function TranslateButton({ text }: { text?: string }) {
  const [translation, setTranslation] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [show, setShow] = useState(false);

  // Reset on every new prompt so a stale translation never carries over and
  // the user must explicitly request translation again.
  useEffect(() => {
    setTranslation(null);
    setShow(false);
    setLoading(false);
  }, [text]);

  const run = async () => {
    if (!text) return;
    if (translation) { setShow((s) => !s); return; }  // already fetched → toggle
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
