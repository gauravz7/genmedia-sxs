"use client";
import {
  BarChart3,
  Boxes,
  Scale,
  ShieldCheck,
  ArrowRight,
  Fingerprint,
} from "lucide-react";
import { useEffect, useState } from "react";
import Nav from "@/components/Nav";
import { api } from "@/lib/api";

const CARDS = [
  {
    href: "/executions",
    label: "Executions",
    desc: "Generate a single case×model execution. The content-addressed no-rerun guarantee means identical (case, model, params) never regenerates.",
    icon: Boxes,
    accent: "from-emerald-500 to-indigo-600",
    note: "core",
  },
  {
    href: "/compare",
    label: "Compare & Vote",
    desc: "Pair two executions of the same case, cast a blind human vote, and trigger the multimodal LLM-as-judge.",
    icon: Scale,
    accent: "from-pink-500 to-purple-600",
    note: "",
  },
  {
    href: "/analytics",
    label: "Analytics",
    desc: "Google-vs-competitor win-map (Wilson CIs), human↔AI agreement, and global Elo / Bradley-Terry rankings.",
    icon: BarChart3,
    accent: "from-indigo-500 to-purple-600",
    note: "",
  },
  {
    href: "/admin",
    label: "Admin",
    desc: "Token login for protected operations and the model registry.",
    icon: ShieldCheck,
    accent: "from-indigo-500 to-pink-600",
    note: "admin",
  },
];

export default function Home() {
  const [health, setHealth] = useState<"?" | "ok" | "down">("?");

  useEffect(() => {
    api
      .health()
      .then((h) => setHealth(h.status === "ok" ? "ok" : "down"))
      .catch(() => setHealth("down"));
  }, []);

  return (
    <div className="min-h-screen bg-[#06080b] text-gray-100 font-sans selection:bg-indigo-500/30 overflow-x-hidden">
      <div className="fixed inset-0 -z-10 bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-indigo-900/15 via-slate-950 to-[#06080b]"></div>

      <Nav active="home" />

      <main className="max-w-screen-2xl mx-auto px-6 pt-8 pb-24 relative z-10">
        <section className="mb-16 text-center animate-in fade-in slide-in-from-top-4 duration-1000">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-indigo-500/10 border border-indigo-500/20 text-indigo-300 text-[10px] font-black uppercase tracking-widest mb-6">
            <Fingerprint className="w-3.5 h-3.5" /> Execution-Centric Benchmarking
          </div>
          <h1 className="text-5xl md:text-7xl font-black text-white tracking-tighter leading-[1.05] italic">
            Project&nbsp;
            <span className="text-transparent bg-clip-text bg-gradient-to-r from-indigo-400 via-purple-400 to-emerald-400">
              Pulse
            </span>
            <span className="align-super text-2xl md:text-3xl text-emerald-400 not-italic"> v3</span>
          </h1>
          <p className="text-gray-400 text-base md:text-xl mt-5 font-light max-w-2xl mx-auto">
            The <span className="text-white font-medium">Execution</span> is the atom:
            one cached <code className="text-emerald-300">(case, model, params)</code> run.
            Comparisons &amp; votes are derived. Generate once, reuse forever.
          </p>
          <div className="mt-6 inline-flex items-center gap-2 text-[10px] font-black uppercase tracking-widest">
            <span className="text-gray-500">Backend</span>
            <span
              className={`px-2.5 py-1 rounded-full border ${
                health === "ok"
                  ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-400"
                  : health === "down"
                    ? "bg-red-500/10 border-red-500/30 text-red-400"
                    : "bg-white/5 border-white/10 text-gray-400"
              }`}
            >
              {health === "ok" ? "● online :8021" : health === "down" ? "● offline" : "checking…"}
            </span>
          </div>
        </section>

        <section className="grid grid-cols-1 sm:grid-cols-2 gap-6 max-w-4xl mx-auto">
          {CARDS.map((card) => {
            const Icon = card.icon;
            return (
              <a
                key={card.href}
                href={card.href}
                className="group relative bg-[#0b0e14] border border-white/5 rounded-[32px] p-8 shadow-2xl hover:border-white/15 transition-all overflow-hidden"
              >
                <div
                  className={`absolute -inset-1 bg-gradient-to-r ${card.accent} rounded-[34px] blur opacity-0 group-hover:opacity-20 transition duration-700`}
                ></div>
                <div className="relative space-y-5">
                  <div className="flex items-center justify-between">
                    <div
                      className={`w-14 h-14 rounded-2xl bg-gradient-to-br ${card.accent} flex items-center justify-center shadow-[0_0_20px_rgba(99,102,241,0.3)]`}
                    >
                      <Icon className="w-7 h-7 text-white" />
                    </div>
                    {card.note && (
                      <span className="px-3 py-1 rounded-full bg-amber-500/10 border border-amber-500/20 text-amber-400 text-[9px] font-black uppercase tracking-widest">
                        {card.note}
                      </span>
                    )}
                  </div>
                  <div>
                    <h2 className="text-2xl font-black text-white tracking-tight">{card.label}</h2>
                    <p className="text-gray-500 text-sm font-light mt-2 leading-relaxed">
                      {card.desc}
                    </p>
                  </div>
                  <div className="flex items-center gap-2 text-[11px] font-black uppercase tracking-widest text-indigo-400 group-hover:gap-3 transition-all">
                    Open <ArrowRight className="w-4 h-4" />
                  </div>
                </div>
              </a>
            );
          })}
        </section>
      </main>
    </div>
  );
}
