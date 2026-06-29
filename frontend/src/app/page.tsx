'use client';
import { BarChart3, Cpu, Clapperboard, ImageIcon, AudioLines, ShieldCheck, ArrowRight } from 'lucide-react';
import Nav from '@/components/Nav';

const CARDS = [
  { href: '/human-eval', label: 'Video Eval', desc: 'Blind A/B voting for video models — Veo, Kling, Seedance — with dimension scoring.', icon: Clapperboard, accent: 'from-pink-500 to-purple-600', note: '' },
  { href: '/image-sxs', label: 'Image Eval', desc: 'Gemini image models vs GPT-image (FAL). Text-to-image & image-edit, blind A/B + AI judge.', icon: ImageIcon, accent: 'from-emerald-500 to-indigo-600', note: '' },
  { href: '/tts-sxs', label: 'TTS Eval', desc: 'Gemini 3.1 Flash TTS vs ElevenLabs. Full voice controls, blind audio A/B + AI judge.', icon: AudioLines, accent: 'from-amber-500 to-pink-600', note: '' },
  { href: '/ai-evals', label: 'AI Evals', desc: 'Machine-generated auto-evaluations across every modality — video, image, and audio — in one place.', icon: Cpu, accent: 'from-emerald-500 to-indigo-600', note: '' },
  { href: '/analytics', label: 'Analytics', desc: 'Aggregated win rates, radar charts, and leaderboards. Unlocks after you cast 10 votes.', icon: BarChart3, accent: 'from-indigo-500 to-purple-600', note: '10 votes' },
  { href: '/admin', label: 'Admin', desc: 'Submit prompts, manage the model registry, batch upload, and run generations.', icon: ShieldCheck, accent: 'from-indigo-500 to-pink-600', note: 'admin' },
];

export default function Home() {
  return (
    <div className="min-h-screen bg-[#06080b] text-gray-100 font-sans selection:bg-indigo-500/30 overflow-x-hidden">
      <div className="fixed inset-0 -z-10 bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-indigo-900/15 via-slate-950 to-[#06080b]"></div>

      <Nav active="home" />

      <main className="max-w-screen-2xl mx-auto px-6 pt-40 pb-24 relative z-10">
        {/* Hero */}
        <section className="mb-16 text-center animate-in fade-in slide-in-from-top-4 duration-1000">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-indigo-500/10 border border-indigo-500/20 text-indigo-300 text-[10px] font-black uppercase tracking-widest mb-6">
            Side-by-Side Benchmarking
          </div>
          <h1 className="text-5xl md:text-7xl font-black text-white tracking-tighter leading-[1.05] italic">
            Project&nbsp;
            <span className="text-transparent bg-clip-text bg-gradient-to-r from-indigo-400 via-purple-400 to-emerald-400">Pulse</span>
          </h1>
          <p className="text-gray-400 text-base md:text-xl mt-5 font-light max-w-2xl mx-auto">
            Video, Image &amp; Speech — blind human and AI side-by-side evaluation, all in one place.
          </p>
        </section>

        {/* Cards */}
        <section className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6 max-w-5xl mx-auto">
          {CARDS.map((card) => {
            const Icon = card.icon;
            return (
              <a
                key={card.href}
                href={card.href}
                className="group relative bg-[#0b0e14] border border-white/5 rounded-[32px] p-8 shadow-3xl hover:border-white/15 transition-all overflow-hidden"
              >
                <div className={`absolute -inset-1 bg-gradient-to-r ${card.accent} rounded-[34px] blur opacity-0 group-hover:opacity-20 transition duration-700`}></div>
                <div className="relative space-y-5">
                  <div className="flex items-center justify-between">
                    <div className={`w-14 h-14 rounded-2xl bg-gradient-to-br ${card.accent} flex items-center justify-center shadow-[0_0_20px_rgba(99,102,241,0.3)]`}>
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
                    <p className="text-gray-500 text-sm font-light mt-2 leading-relaxed">{card.desc}</p>
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
