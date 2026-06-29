"use client";
import { useEffect } from "react";

export default function AiRatingsRedirect() {
  useEffect(() => {
    window.location.replace("/ai-evals");
  }, []);
  return (
    <div className="min-h-screen bg-[#06080b] text-gray-400 flex items-center justify-center font-sans">
      <p className="text-sm font-light tracking-widest uppercase">Redirecting…</p>
    </div>
  );
}
