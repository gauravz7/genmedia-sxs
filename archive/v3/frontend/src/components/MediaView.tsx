"use client";

import { Execution, Modality, mediaUrl } from "@/lib/api";
import { ImageOff, Loader2 } from "lucide-react";

// Renders media by modality through an authenticated proxy — never the raw gs://.
// Two modes:
//   • execution  — resolve an Execution's own media_uri (admin/compare-by-id).
//   • src+modality — a pre-resolved blind ref (e.g. /api/compare/media?…) that
//     hides the model, used by the blind SxS arena.
export default function MediaView({
  execution,
  src,
  modality: modalityProp,
  className = "",
}: {
  execution?: Execution | null;
  src?: string | null;
  modality?: Modality;
  className?: string;
}) {
  // Blind mode: caller supplies an opaque media ref + modality directly.
  if (src !== undefined) {
    const url = mediaUrl(src);
    return <MediaElement url={url} modality={modalityProp || "t2i"} className={className} />;
  }

  if (!execution) {
    return (
      <div
        className={`flex items-center justify-center bg-black/40 rounded-2xl border border-white/5 text-gray-600 ${className}`}
      >
        <ImageOff className="w-8 h-8" />
      </div>
    );
  }

  if (execution.status === "generating" || execution.status === "pending") {
    return (
      <div
        className={`flex flex-col items-center justify-center gap-2 bg-black/40 rounded-2xl border border-white/5 text-indigo-400 ${className}`}
      >
        <Loader2 className="w-8 h-8 animate-spin" />
        <span className="text-[10px] font-black uppercase tracking-widest">
          {execution.status}
        </span>
      </div>
    );
  }

  if (execution.status === "error" || !execution.media_uri) {
    return (
      <div
        className={`flex flex-col items-center justify-center gap-2 bg-red-950/30 rounded-2xl border border-red-500/20 text-red-400 p-4 text-center ${className}`}
      >
        <ImageOff className="w-8 h-8" />
        <span className="text-[10px] font-mono break-all">
          {execution.error || "no media"}
        </span>
      </div>
    );
  }

  return (
    <MediaElement
      url={mediaUrl(execution.media_uri)}
      modality={execution.modality || "t2i"}
      className={className}
    />
  );
}

function MediaElement({
  url,
  modality,
  className = "",
}: {
  url?: string;
  modality: Modality;
  className?: string;
}) {
  if (modality === "tts") {
    return (
      <div
        className={`flex items-center justify-center bg-black/40 rounded-2xl border border-white/5 p-4 ${className}`}
      >
        {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
        <audio controls src={url} className="w-full" />
      </div>
    );
  }

  if (modality === "t2i" || modality === "i2i") {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={url}
        alt="generated output"
        className={`object-contain bg-black/40 rounded-2xl border border-white/5 ${className}`}
      />
    );
  }

  // video: t2v / i2v / r2v
  return (
    <video
      controls
      src={url}
      className={`object-contain bg-black rounded-2xl border border-white/5 ${className}`}
    />
  );
}
