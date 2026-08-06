"use client";

import { useEffect, useState } from "react";
import { ShieldCheck, Loader2, LogOut, Lock, CheckCircle2 } from "lucide-react";
import Nav from "@/components/Nav";
import {
  api,
  clearAdminToken,
  getAdminToken,
  ModelSpec,
  setAdminToken,
} from "@/lib/api";

export default function AdminPage() {
  const [user, setUser] = useState("admin");
  const [pass, setPass] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [authed, setAuthed] = useState(false);
  const [who, setWho] = useState<string | null>(null);
  const [models, setModels] = useState<ModelSpec[]>([]);

  useEffect(() => {
    if (getAdminToken()) {
      api
        .whoami()
        .then((w) => {
          setAuthed(true);
          setWho(w.user);
        })
        .catch(() => clearAdminToken());
    }
    api.listModels(false).then(setModels).catch(() => {});
  }, []);

  const login = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await api.login(user, pass);
      setAdminToken(res.token);
      const w = await api.whoami();
      setAuthed(true);
      setWho(w.user);
      setPass("");
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  const logout = () => {
    clearAdminToken();
    setAuthed(false);
    setWho(null);
  };

  const activeCount = models.filter((m) => m.is_active).length;

  return (
    <div className="min-h-screen bg-[#06080b] text-gray-100 font-sans">
      <div className="fixed inset-0 -z-10 bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-indigo-900/15 via-slate-950 to-[#06080b]" />
      <Nav active="admin" />

      <main className="max-w-3xl mx-auto px-6 py-14 space-y-8">
        <div className="flex items-center gap-3">
          <ShieldCheck className="w-6 h-6 text-indigo-400" />
          <h1 className="text-2xl font-black tracking-tight">Admin</h1>
        </div>

        {!authed ? (
          <div className="bg-[#0b0e14] border border-white/5 rounded-3xl p-8 space-y-5 max-w-md">
            <div className="flex items-center gap-2 text-gray-400">
              <Lock className="w-4 h-4" />
              <span className="text-xs font-black uppercase tracking-widest">Token login</span>
            </div>
            <input
              value={user}
              onChange={(e) => setUser(e.target.value)}
              placeholder="username"
              className="w-full bg-black/40 border border-white/10 rounded-xl px-3 py-2.5 text-sm focus:border-indigo-500/50 outline-none"
            />
            <input
              type="password"
              value={pass}
              onChange={(e) => setPass(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && login()}
              placeholder="password"
              className="w-full bg-black/40 border border-white/10 rounded-xl px-3 py-2.5 text-sm focus:border-indigo-500/50 outline-none"
            />
            <button
              onClick={login}
              disabled={busy || !pass}
              className="w-full flex items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-indigo-500 to-purple-500 text-white font-black uppercase tracking-widest text-xs py-3 disabled:opacity-40 hover:opacity-90"
            >
              {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <ShieldCheck className="w-4 h-4" />}
              Sign in
            </button>
            {error && (
              <p className="text-xs text-red-400 font-mono bg-red-950/30 border border-red-500/20 rounded-xl p-3 break-all">
                {error}
              </p>
            )}
          </div>
        ) : (
          <div className="space-y-6">
            <div className="bg-[#0b0e14] border border-emerald-500/20 rounded-3xl p-6 flex items-center justify-between">
              <div className="flex items-center gap-3">
                <CheckCircle2 className="w-6 h-6 text-emerald-400" />
                <div>
                  <div className="text-sm font-black text-white">Signed in as {who}</div>
                  <div className="text-[10px] text-gray-500 uppercase tracking-widest">
                    admin token active
                  </div>
                </div>
              </div>
              <button
                onClick={logout}
                className="flex items-center gap-2 rounded-xl bg-white/5 border border-white/10 px-4 py-2 text-xs font-black uppercase tracking-widest text-gray-400 hover:text-white"
              >
                <LogOut className="w-4 h-4" /> Sign out
              </button>
            </div>

            <div className="bg-[#0b0e14] border border-white/5 rounded-3xl p-6">
              <h2 className="text-sm font-black uppercase tracking-widest text-gray-400 mb-4">
                Model registry · {activeCount} active / {models.length} total
              </h2>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 max-h-[50vh] overflow-auto">
                {models.map((m) => (
                  <div
                    key={m.id}
                    className="flex items-center justify-between rounded-xl border border-white/5 bg-black/30 px-3 py-2"
                  >
                    <div className="min-w-0">
                      <div className="text-xs font-mono text-gray-300 truncate">{m.id}</div>
                      <div className="text-[10px] text-gray-600">
                        {m.type} · {m.provider}
                      </div>
                    </div>
                    <span
                      className={`shrink-0 w-2 h-2 rounded-full ${
                        m.is_active ? "bg-emerald-400" : "bg-gray-600"
                      }`}
                    />
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
