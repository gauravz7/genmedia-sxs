"use client";

const LINKS: { id: string; label: string; href: string }[] = [
  { id: "analytics", label: "Analytics", href: "/analytics" },
  { id: "ai-evals", label: "AI Evals", href: "/ai-evals" },
  { id: "human-eval", label: "Human Eval", href: "/human-eval" },
  { id: "sxs", label: "SxS", href: "/sxs" },
  { id: "admin", label: "Admin", href: "/admin" },
];

export default function Nav({ active }: { active?: string }) {
  return (
    <nav className="fixed w-full border-b border-white/5 bg-[#06080b]/70 backdrop-blur-2xl z-50">
      <div className="max-w-screen-2xl mx-auto px-6 py-4 flex items-center justify-between">
        <a href="/" className="flex items-center gap-3 group">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-indigo-500 via-purple-500 to-emerald-500 flex items-center justify-center shadow-[0_0_20px_rgba(99,102,241,0.3)] font-black text-white text-xs">
            SxS
          </div>
          <span className="text-xl font-black tracking-tighter text-white uppercase italic group-hover:opacity-80 transition-opacity">
            Pulse
          </span>
        </a>
        <div className="flex items-center gap-2">
          {LINKS.map((link) => {
            const isActive = active === link.id;
            return (
              <a
                key={link.id}
                href={link.href}
                className={`px-3 md:px-4 py-2 rounded-xl text-[10px] md:text-xs font-black uppercase tracking-widest border transition-all ${
                  isActive
                    ? "bg-indigo-500/20 border-indigo-500/40 text-indigo-300 shadow-[0_0_15px_rgba(99,102,241,0.2)]"
                    : "bg-white/5 border-white/10 text-gray-400 hover:text-white hover:border-white/20"
                }`}
              >
                {link.label}
              </a>
            );
          })}
        </div>
      </div>
    </nav>
  );
}
