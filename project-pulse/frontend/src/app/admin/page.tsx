'use client';
const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "";
import { useState, useEffect, useRef, useCallback } from 'react';
import {
  PlusCircle, Search, Sparkles, BookOpen, Crown, Layers, Award,
  Target, Database, ArrowRight, CheckCircle2,
  AlertCircle, Loader2, Zap, Info, ShieldCheck, Image as ImageIcon, Link as LinkIcon,
  PlayCircle, StopCircle, UploadCloud, X, Tag, Filter, Eye, Clock, Video,
  ChevronDown, ChevronUp, RefreshCw, Trash2, Download
} from 'lucide-react';

const PRESET_CATEGORIES = ["Studio Shots", "Beauty", "Animation", "Model Bug Backlog"];

interface Prompt {
  id: number | string;
  prompt_id?: string;
  text: string;
  start_image_url?: string;
  end_image_url?: string;
  reference_image_url?: string;
  reference_images?: string[];
  categories: string[];
  models: string[];
  status: string;
  error?: string;
  ratio?: string;
  timestamp: string;
}

interface Model {
  id: string;
  name: string;
  provider: string;
  model_id: string;
  type: string;
  is_active: boolean;
}

export default function AdminConsole() {
  const [prompts, setPrompts] = useState<Prompt[]>([]);
  const [models, setModels] = useState<Model[]>([]);

  // Prompt creation
  const [newPromptText, setNewPromptText] = useState("");
  const [newPromptStartImage, setNewPromptStartImage] = useState("");
  const [newPromptEndImage, setNewPromptEndImage] = useState("");
  const [newPromptRefImages, setNewPromptRefImages] = useState<string[]>(["", "", ""]);
  const [injectionMode, setInjectionMode] = useState<'t2v' | 'i2v' | 'r2v'>('i2v');
  const [selectedRatio, setSelectedRatio] = useState<'16:9' | '9:16'>('16:9');
  const [newPromptCategories, setNewPromptCategories] = useState<string[]>([]);
  const [customTag, setCustomTag] = useState("");
  const [isGeneratingTags, setIsGeneratingTags] = useState(false);
  const [isBackfilling, setIsBackfilling] = useState(false);
  const autoTagTimerRef = useRef<NodeJS.Timeout | null>(null);
  const [activeTab, setActiveTab] = useState('prompts');
  const [isGenerating, setIsGenerating] = useState(false);
  const [isImageGenerating, setIsImageGenerating] = useState(false);
  const [showSuccess, setShowSuccess] = useState(false);
  const [showOnlyReady, setShowOnlyReady] = useState(true);
  const [expandedImage, setExpandedImage] = useState<string | null>(null);

  // Search & Filter
  const [searchQuery, setSearchQuery] = useState("");
  const [filterTag, setFilterTag] = useState("");
  const [availableTags, setAvailableTags] = useState<string[]>([]);

  // Batch State
  const [batchRows, setBatchRows] = useState<any[]>([]);
  const [isBatchRunning, setIsBatchRunning] = useState(false);
  const [sheetUrl, setSheetUrl] = useState("");
  const [isLoadingSheet, setIsLoadingSheet] = useState(false);
  const [batchSearch, setBatchSearch] = useState("");
  const [batchProgress, setBatchProgress] = useState<{ done: number; total: number; errors: number }>({ done: 0, total: 0, errors: 0 });

  // Generations review
  const [expandedJobId, setExpandedJobId] = useState<string | null>(null);
  const [genSearch, setGenSearch] = useState("");
  const [genStatusFilter, setGenStatusFilter] = useState<string>("all");
  const [genTagFilter, setGenTagFilter] = useState<string>("");

  // Auth
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [authError, setAuthError] = useState("");

  useEffect(() => {
    const savedAuth = localStorage.getItem('project_pulse_admin_auth');
    if (savedAuth === 'true') setIsAuthenticated(true);
    const handleExpand = (e: any) => setExpandedImage(e.detail);
    window.addEventListener('expand-image', handleExpand);
    return () => window.removeEventListener('expand-image', handleExpand);
  }, []);

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const res = await fetch(`${API_BASE_URL}/api/admin/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password })
      });
      if (res.ok) {
        setIsAuthenticated(true);
        localStorage.setItem('project_pulse_admin_auth', 'true');
        setAuthError("");
      } else {
        setAuthError("Invalid credentials");
      }
    } catch {
      setAuthError("Server unavailable");
    }
  };

  const handleLogout = () => {
    setIsAuthenticated(false);
    localStorage.removeItem('project_pulse_admin_auth');
  };

  useEffect(() => {
    fetchModels();
    fetchJobs();
    fetchTags();
    const interval = setInterval(fetchJobs, 5000);
    return () => clearInterval(interval);
  }, []);

  const formatUrl = (url?: string) => {
    if (!url) return url;
    if (url.startsWith('/api/media')) return `${API_BASE_URL}${url}`;
    return url;
  };

  const fetchTags = async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/api/tags`);
      const data = await res.json();
      if (data?.status === "success") setAvailableTags(data.tags);
    } catch (err) {
      console.error("Failed to fetch tags", err);
    }
  };

  const fetchJobs = async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/api/admin/jobs`);
      const data = await res.json();
      const mapped = (data || []).map((job: any) => {
        const modelIds = Object.keys(job.results || {});
        let status = "complete";
        let errorMsg = "";
        if (modelIds.length === 0) {
          status = "generating";
        } else {
          const statuses = modelIds.map(m => job.results[m].status);
          if (statuses.includes("generating")) {
            status = "generating";
          } else if (statuses.every((s: string) => s === "error")) {
            status = "error";
            errorMsg = modelIds.map(m => `${m}: ${job.results[m].error || 'Unknown error'}`).join(" | ");
          } else if (statuses.includes("error")) {
            errorMsg = modelIds.filter(m => job.results[m].status === "error").map(m => `${m}: ${job.results[m].error || 'Error'}`).join(" | ");
          }
        }
        return {
          ...job,
          start_image_url: formatUrl(job.start_image_url),
          end_image_url: formatUrl(job.end_image_url),
          reference_image_url: formatUrl(job.reference_image_url),
          reference_images: job.reference_images ? job.reference_images.map(formatUrl) : undefined,
          text: job.prompt || "No prompt text",
          categories: job.categories || [],
          models: modelIds,
          status,
          error: errorMsg,
          ratio: job.ratio || "16:9",
          timestamp: job.timestamp ? new Date(job.timestamp * 1000).toLocaleString() : "Just now"
        };
      });
      setPrompts(mapped);
    } catch (err) {
      console.error("Failed to fetch jobs", err);
    }
  };

  const fetchModels = async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/api/models`);
      setModels(await res.json());
    } catch (err) {
      console.error("Failed to fetch models", err);
    }
  };

  const handleToggleModel = async (mid: string) => {
    await fetch(`${API_BASE_URL}/api/models/${mid}/toggle`, { method: "POST" });
    fetchModels();
  };

  const handleDeleteModel = async (mid: string) => {
    if (!confirm("Delete this model?")) return;
    await fetch(`${API_BASE_URL}/api/models/${mid}`, { method: "DELETE" });
    fetchModels();
  };

  const handleGenerateImage = async (field: string) => {
    if (!newPromptText) return alert("Enter prompt text first");
    setIsImageGenerating(true);
    try {
      const resp = await fetch(`${API_BASE_URL}/api/generate-image`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: newPromptText, ratio: selectedRatio })
      });
      const data = await resp.json();
      if (data.status === "success") {
        if (field === "start") setNewPromptStartImage(data.url);
        else if (field === "end") setNewPromptEndImage(data.url);
        else if (field.startsWith("ref_")) {
          const idx = parseInt(field.split("_")[1]);
          const nr = [...newPromptRefImages];
          nr[idx] = data.url;
          setNewPromptRefImages(nr);
        }
      } else {
        alert("Generation failed: " + (data.detail || "Unknown error"));
      }
    } catch (err) {
      alert("Failed to connect to backend");
    } finally {
      setIsImageGenerating(false);
    }
  };

  const fetchTagSuggestions = useCallback(async (text: string) => {
    if (!text.trim() || text.trim().length < 10) return;
    setIsGeneratingTags(true);
    try {
      const resp = await fetch(`${API_BASE_URL}/api/admin/generate-tags`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text,
          start_image_url: injectionMode === 'i2v' ? newPromptStartImage : null,
          end_image_url: injectionMode === 'i2v' ? newPromptEndImage : null,
          reference_images: injectionMode === 'r2v' ? newPromptRefImages.filter(u => u) : null
        })
      });
      const data = await resp.json();
      if (data.status === "success") {
        setNewPromptCategories(prev => Array.from(new Set([...prev, ...data.tags])));
      }
    } catch (err) {
      console.error("Failed to suggest tags", err);
    } finally {
      setIsGeneratingTags(false);
    }
  }, [injectionMode, newPromptStartImage, newPromptEndImage, newPromptRefImages]);

  // Auto-suggest tags when prompt text changes (debounced 1.5s)
  useEffect(() => {
    if (autoTagTimerRef.current) clearTimeout(autoTagTimerRef.current);
    if (newPromptText.trim().length >= 10 && newPromptCategories.length === 0) {
      autoTagTimerRef.current = setTimeout(() => {
        fetchTagSuggestions(newPromptText);
      }, 1500);
    }
    return () => { if (autoTagTimerRef.current) clearTimeout(autoTagTimerRef.current); };
  }, [newPromptText]);

  const handleSuggestTags = async () => {
    if (!newPromptText.trim()) return alert("Enter prompt text first");
    fetchTagSuggestions(newPromptText);
  };

  const handleBackfillTags = async () => {
    if (!confirm("This will auto-generate tags for all untagged jobs and prompts using Gemini. Continue?")) return;
    setIsBackfilling(true);
    try {
      const resp = await fetch(`${API_BASE_URL}/api/admin/backfill-tags`, { method: "POST" });
      const data = await resp.json();
      if (data.status === "success") {
        alert(`Backfill complete: ${data.tagged_jobs} jobs and ${data.tagged_prompts} prompts tagged.`);
        fetchJobs();
        fetchTags();
      } else {
        alert("Backfill failed");
      }
    } catch {
      alert("Failed to connect to backend");
    } finally {
      setIsBackfilling(false);
    }
  };

  const handleImageUpload = async (e: React.ChangeEvent<HTMLInputElement>, setter: (val: string) => void) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const formData = new FormData();
    formData.append('file', file);
    try {
      const resp = await fetch(`${API_BASE_URL}/api/upload`, { method: "POST", body: formData });
      const data = await resp.json();
      if (data.status === "success") setter(data.url);
      else alert("Upload failed");
    } catch {
      alert("Upload failed");
    }
  };

  const handleAddPrompt = async () => {
    if (!newPromptText.trim() || isGenerating) return;
    setIsGenerating(true);
    try {
      const response = await fetch(`${API_BASE_URL}/api/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          text: newPromptText,
          categories: newPromptCategories,
          ratio: selectedRatio,
          start_image_url: injectionMode === 'i2v' ? (newPromptStartImage || null) : null,
          end_image_url: injectionMode === 'i2v' ? (newPromptEndImage || null) : null,
          reference_images: injectionMode === 'r2v' ? newPromptRefImages.filter(u => u) : null,
          reference_image_url: injectionMode === 'r2v' ? (newPromptRefImages[0] || null) : null,
          mode: injectionMode
        })
      });
      if (!response.ok) throw new Error(`Server: ${response.status}`);
      const data = await response.json();

      setPrompts([{
        id: data.job_id || Date.now(),
        prompt_id: data.job_id,
        text: newPromptText,
        start_image_url: injectionMode === 'i2v' ? newPromptStartImage : undefined,
        end_image_url: injectionMode === 'i2v' ? newPromptEndImage : undefined,
        reference_images: injectionMode === 'r2v' ? newPromptRefImages.filter(u => u) : undefined,
        categories: newPromptCategories,
        models: ["Veo", "Kling", "Seedance"],
        status: "generating",
        ratio: selectedRatio,
        timestamp: "Just now"
      }, ...prompts]);

      setNewPromptCategories([]);
      setCustomTag("");
      setShowSuccess(true);
      setTimeout(() => setShowSuccess(false), 3000);
    } catch (e) {
      console.error("API Error:", e);
    } finally {
      setIsGenerating(false);
    }
  };

  // Batch handling
  const handleBatchLoadFromSheet = async () => {
    if (!sheetUrl) return;
    setIsLoadingSheet(true);
    try {
      const resp = await fetch(`${API_BASE_URL}/api/admin/batch/sheet/load`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: sheetUrl })
      });
      const data = await resp.json();
      if (data.status === "success") {
        const rows = data.rows || [];
        const mapped = [];
        for (let i = 1; i < rows.length; i++) {
          const row = rows[i];
          if (row.length > 2 && row[0]) {
            mapped.push({
              promptId: row[0], mode: (row[1] || "").toLowerCase().trim(),
              text: row[2], startImg: row[3], endImg: row[4],
              ref1: row[5], ref2: row[6], ref3: row[7], model: row[8],
              success: String(row[9]).trim().toUpperCase() === "TRUE",
              error: row[10] || "",
              ratio: (row[11] || "16:9").trim(),
              rowIndex: i + 1,
              batchStatus: String(row[9]).trim().toUpperCase() === "TRUE" ? "done" : "pending" as "pending" | "running" | "done" | "error"
            });
          }
        }
        setBatchRows(mapped.filter(r => r.promptId && r.promptId.toLowerCase() !== "prompt id"));
        setBatchProgress({ done: 0, total: 0, errors: 0 });
      } else {
        alert("Load Failed");
      }
    } catch {
      alert("Failed to connect to backend");
    } finally {
      setIsLoadingSheet(false);
    }
  };

  // Group batch rows by promptId for display & execution
  const getBatchGroups = () => {
    const groups: Record<string, { promptId: string; mode: string; text: string; ratio: string; models: string[]; rows: typeof batchRows; allSuccess: boolean; hasError: boolean }> = {};
    for (const row of batchRows) {
      if (!groups[row.promptId]) {
        groups[row.promptId] = {
          promptId: row.promptId, mode: row.mode, text: row.text,
          ratio: row.ratio || "16:9",
          models: [], rows: [], allSuccess: true, hasError: false
        };
      }
      groups[row.promptId].rows.push(row);
      // Only include models whose rows are not already marked success
      if (row.model && row.batchStatus !== "done") groups[row.promptId].models.push(row.model.trim());
      if (row.batchStatus !== "done") groups[row.promptId].allSuccess = false;
      if (row.batchStatus === "error") groups[row.promptId].hasError = true;
    }
    return groups;
  };

  const filteredBatchGroups = () => {
    const groups = getBatchGroups();
    if (!batchSearch) return Object.values(groups);
    const q = batchSearch.toLowerCase();
    return Object.values(groups).filter(g =>
      g.promptId.toLowerCase().includes(q) ||
      g.text.toLowerCase().includes(q) ||
      g.models.some(m => m.toLowerCase().includes(q))
    );
  };

  const handleRunBatch = async () => {
    if (!batchRows.length) return;
    setIsBatchRunning(true);
    const groups = getBatchGroups();
    const pendingGroups = Object.values(groups).filter(g => !g.allSuccess);
    const total = pendingGroups.length;
    let done = 0;
    let errors = 0;
    setBatchProgress({ done: 0, total, errors: 0 });

    // Update row status helper
    const setRowStatus = (promptId: string, status: "running" | "done" | "error", error?: string) => {
      setBatchRows(prev => prev.map(r =>
        r.promptId === promptId ? { ...r, batchStatus: status, ...(error ? { error } : {}), ...(status === "done" ? { success: true } : {}) } : r
      ));
    };

    try {
      const keys = pendingGroups.map(g => g.promptId);
      for (let i = 0; i < keys.length; i += 10) {
        const chunk = keys.slice(i, i + 10);
        await Promise.all(chunk.map(async (pid) => {
          const g = groups[pid];
          setRowStatus(pid, "running");
          try {
            // No hardcoded categories — let Gemini auto-tag
            const res = await fetch(`${API_BASE_URL}/api/generate`, {
              method: 'POST', headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                text: g.text, categories: [],
                ratio: g.ratio,
                start_image_url: g.rows[0]?.startImg || null,
                end_image_url: g.rows[0]?.endImg || null,
                reference_images: [g.rows[0]?.ref1, g.rows[0]?.ref2, g.rows[0]?.ref3].filter(Boolean).length ? [g.rows[0]?.ref1, g.rows[0]?.ref2, g.rows[0]?.ref3].filter(Boolean) : null,
                reference_image_url: g.rows[0]?.ref1 || null,
                mode: g.mode,
                model_ids: g.models.length > 0 ? g.models : undefined,
                prompt_id: pid
              })
            });
            if (!res.ok) throw new Error(`API ${res.status}`);
            const genResult = await res.json();
            const jobId = genResult.job_id;

            // Poll job status until all models finish (max 15 min)
            const pollInterval = 10_000;
            const maxPolls = 90;
            let pollCount = 0;
            let jobStatus: any = null;

            while (pollCount < maxPolls) {
              await new Promise(r => setTimeout(r, pollInterval));
              pollCount++;
              try {
                const statusRes = await fetch(`${API_BASE_URL}/api/admin/jobs/${jobId}/status`);
                if (statusRes.ok) {
                  jobStatus = await statusRes.json();
                  if (jobStatus.all_done) break;
                }
              } catch { /* retry */ }
            }

            // Only update rows that were not already marked success
            const pendingRows = g.rows.filter((r: any) => r.batchStatus !== "done");

            if (jobStatus?.all_done && jobStatus.succeeded > 0) {
              // At least one model succeeded — mark success
              const errorDetail = jobStatus.failed > 0
                ? `${jobStatus.succeeded}/${jobStatus.total_models} succeeded. Failures: ${jobStatus.errors.map((e: any) => `${e.model}: ${e.error}`).join('; ').slice(0, 200)}`
                : "";
              setRowStatus(pid, "done");
              done++;
              for (const row of pendingRows) {
                fetch(`${API_BASE_URL}/api/admin/batch/sheet/update`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ url: sheetUrl, row: row.rowIndex, success: true, error: errorDetail }) }).catch(() => {});
              }
            } else {
              // All models failed or timed out
              const errorMsg = jobStatus?.errors?.map((e: any) => `${e.model}: ${e.error}`).join('; ').slice(0, 200) || "All models failed or timed out";
              throw new Error(errorMsg);
            }
          } catch (err: any) {
            setRowStatus(pid, "error", err?.message || "Failed");
            errors++;
            const pendingRows = g.rows.filter((r: any) => r.batchStatus !== "done");
            for (const row of pendingRows) {
              fetch(`${API_BASE_URL}/api/admin/batch/sheet/update`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ url: sheetUrl, row: row.rowIndex, success: false, error: err?.message || "Failed" }) }).catch(() => {});
            }
          }
          setBatchProgress({ done, total, errors });
        }));
      }
    } catch (e) {
      console.error("Batch error", e);
    } finally {
      setIsBatchRunning(false);
      fetchJobs();
      fetchTags();
    }
  };

  // Filter prompts by search query and tag
  const filteredPrompts = prompts.filter(p => {
    if (showOnlyReady && p.status !== 'complete') return false;
    if (searchQuery && !p.text.toLowerCase().includes(searchQuery.toLowerCase()) && !p.prompt_id?.toLowerCase().includes(searchQuery.toLowerCase())) return false;
    if (filterTag && !(p.categories || []).some(c => c.toLowerCase() === filterTag.toLowerCase())) return false;
    return true;
  });

  return (
    <div className="min-h-screen bg-[#020408] text-white p-6 relative font-sans selection:bg-indigo-500/30 overflow-x-hidden">
      <div className="fixed inset-0 z-0 bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-indigo-900/10 via-slate-950 to-[#020408]"></div>

      {/* Image Lightbox */}
      {expandedImage && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-black/90 backdrop-blur-sm cursor-zoom-out animate-in fade-in duration-300" onClick={() => setExpandedImage(null)}>
          <img src={expandedImage} className="max-w-full max-h-full rounded-2xl shadow-2xl border border-white/10" alt="Expanded" />
        </div>
      )}

      {/* Login Overlay */}
      {!isAuthenticated && (
        <div className="fixed inset-0 z-[100] bg-[#06080b]/90 backdrop-blur-2xl flex items-center justify-center p-6">
          <div className="max-w-md w-full bg-[#0d1017] border border-white/10 rounded-[40px] p-10 shadow-3xl animate-in fade-in zoom-in-95 duration-500">
            <div className="flex flex-col items-center mb-10">
              <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center shadow-3xl mb-6"><ShieldCheck className="w-8 h-8 text-white" /></div>
              <h2 className="text-3xl font-bold text-white tracking-tight">Admin Portal</h2>
              <p className="text-gray-500 text-sm mt-2">Internal use only</p>
            </div>
            <form onSubmit={handleLogin} className="space-y-6">
              <div className="space-y-2">
                <label className="text-xs font-bold text-gray-500 uppercase tracking-widest px-1">Identity</label>
                <input type="text" value={username} onChange={(e) => setUsername(e.target.value)} placeholder="Username" className="w-full bg-[#06080b] border border-white/10 rounded-2xl px-6 py-4 text-white focus:outline-none focus:ring-2 focus:ring-indigo-500/50 transition-all" />
              </div>
              <div className="space-y-2">
                <label className="text-xs font-bold text-gray-500 uppercase tracking-widest px-1">Access Key</label>
                <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Password" className="w-full bg-[#06080b] border border-white/10 rounded-2xl px-6 py-4 text-white focus:outline-none focus:ring-2 focus:ring-indigo-500/50 transition-all" />
              </div>
              {authError && <div className="text-red-400 text-xs font-bold bg-red-500/10 border border-red-500/20 px-4 py-3 rounded-xl flex items-center gap-2"><AlertCircle className="w-4 h-4" /> {authError}</div>}
              <button type="submit" className="w-full bg-gradient-to-r from-indigo-500 to-purple-600 hover:from-indigo-400 hover:to-purple-500 text-white font-black py-5 rounded-2xl shadow-3xl transition-all active:scale-[0.98] mt-4">Sign In</button>
            </form>
          </div>
        </div>
      )}

      {/* Nav */}
      <nav className="fixed w-full border-b border-white/5 bg-[#06080b]/80 backdrop-blur-xl z-50">
        <div className="max-w-7xl mx-auto px-8 py-4 flex items-center justify-between">
          <div className="flex items-center space-x-3 group cursor-pointer">
            <div className="bg-gradient-to-br from-indigo-500 via-purple-500 to-pink-500 p-[2px] rounded-xl shadow-[0_0_20px_rgba(99,102,241,0.2)]">
              <div className="bg-[#06080b] p-2 rounded-[10px]"><Layers className="w-5 h-5 text-indigo-400" /></div>
            </div>
            <h1 className="text-xl font-bold tracking-tight text-white m-0 flex items-center">
              Project&nbsp;<span className="text-transparent bg-clip-text bg-gradient-to-r from-indigo-400 via-purple-400 to-pink-400">Pulse</span>
            </h1>
          </div>

          <div className="flex items-center space-x-2 bg-white/[0.03] border border-white/10 rounded-full p-1 shadow-inner">
            {[
              { id: 'prompts', label: 'Prompt Engine' },
              { id: 'generations', label: 'Generations', icon: <Eye className="w-4 h-4" /> },
              { id: 'models', label: 'Model Registry' },
              { id: 'batch', label: 'Batch Upload', icon: <UploadCloud className="w-4 h-4" /> },
              { id: 'guidelines', label: 'Guidelines', icon: <BookOpen className="w-4 h-4" /> },
            ].map(tab => (
              <button key={tab.id} onClick={() => setActiveTab(tab.id)} className={`px-6 py-2 rounded-full text-sm font-semibold flex items-center gap-2 transition-all duration-300 ${activeTab === tab.id ? 'bg-indigo-500 text-white shadow-[0_0_20px_rgba(99,102,241,0.3)]' : 'text-gray-400 hover:text-gray-200'}`}>
                {tab.icon} {tab.label}
              </button>
            ))}
          </div>

          <div className="hidden md:flex items-center gap-3">
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-[10px] font-bold uppercase tracking-wider">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse"></span> Live
            </div>
            <button onClick={handleLogout} className="p-2 text-gray-500 hover:text-white transition-colors">Log out</button>
          </div>
        </div>
      </nav>

      <main className="max-w-7xl mx-auto px-8 pt-32 pb-20 relative z-10">

        {/* ============ MODEL REGISTRY ============ */}
        {activeTab === 'models' && (
          <div className="space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-500">
            <section className="bg-white/[0.03] border border-white/10 rounded-3xl p-8 backdrop-blur-sm">
              <div className="flex items-center space-x-3 mb-6">
                <Database className="w-6 h-6 text-purple-400" />
                <h2 className="text-2xl font-bold text-white m-0">Model Registry</h2>
              </div>
              <div className="space-y-8">
                {['t2v', 'i2v', 'r2v'].map((type) => {
                  const filtered = models.filter(m => m.type === type);
                  if (!filtered.length) return null;
                  return (
                    <div key={type} className="space-y-4">
                      <div className="flex items-center gap-3 px-2">
                        <div className="h-0.5 w-4 bg-indigo-500 rounded-full"></div>
                        <h3 className="text-xs font-black uppercase tracking-[0.2em] text-gray-400">
                          {type === 't2v' ? 'Text-to-Video' : type === 'i2v' ? 'Image-to-Video' : 'Reference-to-Video'}
                        </h3>
                      </div>
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        {filtered.map(m => (
                          <div key={m.id} className="bg-white/[0.02] border border-white/5 rounded-2xl p-4 flex items-center justify-between group hover:bg-white/[0.04] transition-all">
                            <div className="flex items-center space-x-4">
                              <div className={`p-2 rounded-xl transition-colors cursor-pointer ${m.is_active ? (m.provider === 'vertex' ? 'bg-blue-500/20 text-blue-400' : 'bg-orange-500/20 text-orange-400') : 'bg-gray-800/10 text-gray-500'}`} onClick={() => handleToggleModel(m.id)}>
                                {m.provider === 'vertex' ? <ShieldCheck className="w-5 h-5" /> : <Zap className="w-5 h-5" />}
                              </div>
                              <div className="flex flex-col">
                                <div className={`text-sm font-bold transition-colors ${m.is_active ? 'text-white' : 'text-gray-500'}`}>{m.name}</div>
                                <div className="text-[10px] text-gray-500 font-mono tracking-tight uppercase">{m.model_id}</div>
                              </div>
                            </div>
                            <div className="flex items-center gap-2">
                              <button onClick={() => handleToggleModel(m.id)} className={`text-[9px] font-black uppercase tracking-widest px-3 py-1 rounded-full border transition-all ${m.is_active ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' : 'bg-white/5 text-gray-600 border-white/5'}`}>
                                {m.is_active ? 'Active' : 'Disabled'}
                              </button>
                              <button onClick={() => handleDeleteModel(m.id)} className="opacity-0 group-hover:opacity-100 p-2 hover:bg-red-500/20 text-red-400 rounded-lg transition-all">
                                <PlusCircle className="w-4 h-4 rotate-45" />
                              </button>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  );
                })}
              </div>
            </section>
          </div>
        )}

        {/* ============ PROMPT ENGINE ============ */}
        {activeTab === 'prompts' && (
          <div className="animate-in fade-in slide-in-from-bottom-4 duration-700">
            <div className="mb-12 flex flex-col md:flex-row md:items-end justify-between gap-6">
              <div>
                <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-indigo-500/10 border border-indigo-500/20 text-indigo-300 text-[10px] font-bold uppercase tracking-widest mb-4">
                  <Sparkles className="w-3.5 h-3.5" /> Benchmarking Arena
                </div>
                <h2 className="text-4xl md:text-5xl font-light text-white mb-4 tracking-tight leading-tight">
                  Hard <span className="font-bold text-transparent bg-clip-text bg-gradient-to-r from-indigo-400 to-purple-400">Prompt Library</span>
                </h2>
              </div>
              <div className="flex gap-4">
                <StatBox label="Total" value={prompts.length} />
                <StatBox label="Success" value={prompts.filter(p => p.status === 'complete').length} />
                <StatBox label="Failed" value={prompts.filter(p => p.status === 'error').length} />
              </div>
            </div>

            {/* Injection Card */}
            <div className="relative group mb-16">
              <div className="absolute -inset-1 bg-gradient-to-r from-indigo-500 via-purple-500 to-pink-500 rounded-[30px] blur opacity-10 group-hover:opacity-20 transition duration-1000"></div>
              <div className="relative bg-[#0d1017] border border-white/10 rounded-[28px] p-8 md:p-10 shadow-3xl">
                <div className="flex items-center gap-3 mb-8">
                  <div className="w-12 h-12 rounded-2xl bg-indigo-500/10 flex items-center justify-center border border-indigo-500/20"><Zap className="w-6 h-6 text-indigo-400" /></div>
                  <div>
                    <h3 className="text-xl font-semibold text-white">Inject New Scenario</h3>
                    <p className="text-sm text-gray-500">Expert-curated multi-asset benchmark</p>
                  </div>

                  {/* Mode & Ratio Selectors */}
                  <div className="ml-auto flex gap-3">
                    {/* Mode */}
                    <div className="flex bg-white/5 p-1 rounded-xl border border-white/5">
                      {['t2v', 'i2v', 'r2v'].map(m => (
                        <button key={m} onClick={() => setInjectionMode(m as any)} className={`px-4 py-1.5 rounded-lg text-[10px] font-black uppercase tracking-widest transition-all ${injectionMode === m ? 'bg-indigo-500 text-white shadow-lg shadow-indigo-500/20' : 'text-gray-500 hover:text-gray-300'}`}>
                          {m.toUpperCase()}
                        </button>
                      ))}
                    </div>
                    {/* Ratio */}
                    <div className="flex bg-white/5 p-1 rounded-xl border border-white/5">
                      {(['16:9', '9:16'] as const).map(r => (
                        <button key={r} onClick={() => setSelectedRatio(r)} className={`px-3 py-1.5 rounded-lg text-[10px] font-black uppercase tracking-widest transition-all ${selectedRatio === r ? 'bg-purple-500 text-white shadow-lg shadow-purple-500/20' : 'text-gray-500 hover:text-gray-300'}`}>
                          {r}
                        </button>
                      ))}
                    </div>
                  </div>
                </div>

                <div className="space-y-10">
                  <div className="grid grid-cols-1 lg:grid-cols-4 gap-8">
                    {/* Prompt Text */}
                    <div className="lg:col-span-2 relative">
                      <div className="text-[10px] font-black uppercase tracking-widest text-indigo-400 mb-3 ml-2 italic">Video Core Prompt</div>
                      <textarea value={newPromptText} onChange={(e) => setNewPromptText(e.target.value)} placeholder="e.g., A panoramic tracking shot of a mountain range at golden hour..." className="w-full bg-[#06080b] border border-white/10 rounded-2xl p-6 text-gray-200 placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-indigo-500/30 transition-all resize-none h-[280px] text-lg leading-relaxed shadow-inner" />
                      {isGenerating && <div className="absolute inset-0 bg-[#06080b]/50 backdrop-blur-sm rounded-2xl flex items-center justify-center z-20"><Loader2 className="w-8 h-8 text-indigo-400 animate-spin" /></div>}
                    </div>

                    {/* Image Inputs */}
                    <div className="lg:col-span-2 space-y-6">
                      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                        {injectionMode === 'i2v' && (
                          <>
                            <ImageInputCell label="Start Frame" value={newPromptStartImage} onChange={setNewPromptStartImage} onGenerate={() => handleGenerateImage("start")} onUpload={(e) => handleImageUpload(e, setNewPromptStartImage)} isGenerating={isImageGenerating} icon={<PlayCircle className="w-4 h-4" />} />
                            <ImageInputCell label="End Frame" value={newPromptEndImage} onChange={setNewPromptEndImage} onGenerate={() => handleGenerateImage("end")} onUpload={(e) => handleImageUpload(e, setNewPromptEndImage)} isGenerating={isImageGenerating} icon={<StopCircle className="w-4 h-4" />} />
                          </>
                        )}
                        {injectionMode === 'r2v' && [0, 1, 2].map(idx => (
                          <ImageInputCell key={idx} label={`Ref ${idx + 1}`} value={newPromptRefImages[idx]} onChange={(val) => { const nr = [...newPromptRefImages]; nr[idx] = val; setNewPromptRefImages(nr); }} onGenerate={() => handleGenerateImage(`ref_${idx}`)} onUpload={(e) => handleImageUpload(e, (val) => { const nr = [...newPromptRefImages]; nr[idx] = val; setNewPromptRefImages(nr); })} isGenerating={isImageGenerating} icon={<ImageIcon className="w-4 h-4" />} />
                        ))}
                        {injectionMode === 't2v' && (
                          <div className="col-span-3 h-full flex items-center justify-center border-2 border-dashed border-white/5 rounded-3xl p-8">
                            <div className="text-center">
                              <Sparkles className="w-8 h-8 text-indigo-400/30 mx-auto mb-2" />
                              <div className="text-gray-500 text-xs font-medium uppercase tracking-widest">Pure T2V Mode</div>
                            </div>
                          </div>
                        )}
                      </div>
                      {injectionMode !== 't2v' && (
                        <div className="p-6 bg-white/[0.02] border border-white/5 rounded-2xl flex items-center gap-4">
                          <Info className="w-8 h-8 text-indigo-400/50 shrink-0" />
                          <p className="text-[11px] text-gray-400 leading-relaxed font-light">
                            {injectionMode === 'i2v' ? "Start/end frames for I2V benchmarking." : "Reference images for character/style consistency."}
                          </p>
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Tags & Deploy */}
                  <div className="flex flex-col md:flex-row items-center justify-between gap-6 pt-8 border-t border-white/5">
                    <div className="flex flex-col gap-4">
                      <div className="flex items-center justify-between px-2">
                        <div className="text-[10px] font-black uppercase tracking-widest text-gray-500 italic flex items-center gap-2">
                          Tags & Categories
                          {isGeneratingTags && <span className="text-indigo-400 flex items-center gap-1"><Loader2 className="w-3 h-3 animate-spin" /> auto-generating...</span>}
                          {!isGeneratingTags && newPromptCategories.length > 0 && <span className="text-emerald-400 flex items-center gap-1"><CheckCircle2 className="w-3 h-3" /> {newPromptCategories.length} tags</span>}
                        </div>
                        <div className="flex items-center gap-2">
                          <button onClick={handleSuggestTags} disabled={isGeneratingTags} className="text-[10px] font-bold text-indigo-400 hover:text-indigo-300 flex items-center gap-1.5 px-3 py-1 rounded-full bg-indigo-500/10 border border-indigo-500/20 transition-all disabled:opacity-50">
                            {isGeneratingTags ? <Loader2 className="w-3 h-3 animate-spin" /> : <Sparkles className="w-3 h-3" />} Regenerate
                          </button>
                          <button onClick={handleBackfillTags} disabled={isBackfilling} className="text-[10px] font-bold text-amber-400 hover:text-amber-300 flex items-center gap-1.5 px-3 py-1 rounded-full bg-amber-500/10 border border-amber-500/20 transition-all disabled:opacity-50">
                            {isBackfilling ? <Loader2 className="w-3 h-3 animate-spin" /> : <Tag className="w-3 h-3" />} Backfill All
                          </button>
                        </div>
                      </div>
                      <div className="flex flex-wrap gap-2 p-1.5 bg-white/[0.03] border border-white/5 rounded-2xl">
                        {PRESET_CATEGORIES.map(c => (
                          <button key={c} onClick={() => {
                            if (newPromptCategories.includes(c)) setNewPromptCategories(newPromptCategories.filter(x => x !== c));
                            else setNewPromptCategories([...newPromptCategories, c]);
                          }} className={`px-5 py-2.5 rounded-xl text-xs font-bold uppercase tracking-wider transition-all ${newPromptCategories.includes(c) ? 'bg-white text-[#06080b] shadow-xl' : 'text-gray-500 hover:text-gray-300 hover:bg-white/5'}`}>
                            {c}
                          </button>
                        ))}
                        <div className="flex items-center gap-2 pl-2 border-l border-white/10 ml-2">
                          <input type="text" value={customTag} onChange={(e) => setCustomTag(e.target.value)} onKeyDown={(e) => {
                            if (e.key === 'Enter' && customTag.trim()) {
                              if (!newPromptCategories.includes(customTag.trim())) setNewPromptCategories([...newPromptCategories, customTag.trim()]);
                              setCustomTag("");
                            }
                          }} placeholder="Custom..." className="bg-transparent border-b border-white/10 text-xs py-1 px-1 focus:outline-none focus:border-indigo-500 w-24 placeholder:text-gray-700" />
                          <button onClick={() => {
                            if (customTag.trim() && !newPromptCategories.includes(customTag.trim())) {
                              setNewPromptCategories([...newPromptCategories, customTag.trim()]);
                              setCustomTag("");
                            }
                          }} className="p-1 hover:bg-white/5 rounded-lg transition-all"><PlusCircle className="w-4 h-4 text-gray-500" /></button>
                        </div>
                      </div>
                      {newPromptCategories.filter(c => !PRESET_CATEGORIES.includes(c)).length > 0 && (
                        <div className="flex flex-wrap gap-2 px-2">
                          {newPromptCategories.filter(c => !PRESET_CATEGORIES.includes(c)).map(tag => (
                            <span key={tag} className="px-3 py-1 rounded-full bg-white/5 border border-white/10 text-[10px] font-bold text-gray-400 flex items-center gap-2">
                              {tag} <X className="w-3 h-3 cursor-pointer hover:text-red-400" onClick={() => setNewPromptCategories(newPromptCategories.filter(x => x !== tag))} />
                            </span>
                          ))}
                        </div>
                      )}
                    </div>

                    <button onClick={handleAddPrompt} disabled={!newPromptText.trim() || isGenerating} className="w-full md:w-auto min-w-[260px] bg-gradient-to-r from-indigo-500 to-purple-600 hover:from-indigo-400 hover:to-purple-500 disabled:from-gray-800 disabled:to-gray-900 text-white font-bold py-4.5 px-10 rounded-2xl transition-all shadow-[0_10px_30px_rgba(99,102,241,0.2)] flex items-center justify-center gap-3 group active:scale-[0.98] text-lg">
                      {isGenerating ? <><Loader2 className="w-5 h-5 animate-spin" /> Generating...</> : <>Deploy Scenario <ArrowRight className="w-5 h-5 group-hover:translate-x-1 transition-transform" /></>}
                    </button>
                  </div>
                </div>

                {showSuccess && (
                  <div className="mt-6 animate-in fade-in slide-in-from-top-2 flex items-center gap-2 text-emerald-400 bg-emerald-500/10 px-4 py-3 rounded-xl border border-emerald-500/20">
                    <CheckCircle2 className="w-5 h-5" /> Scenario initialized across the grid.
                  </div>
                )}
              </div>
            </div>

            {/* Scenarios List with Search & Tag Filter */}
            <div className="space-y-6">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between px-2 gap-4">
                <h3 className="text-2xl font-light text-white flex items-center gap-3">
                  <Database className="w-6 h-6 text-indigo-400" /> Active Scenarios
                </h3>
                <div className="flex items-center gap-3">
                  {/* Search */}
                  <div className="relative flex items-center">
                    <Search className="w-4 h-4 text-gray-500 absolute left-3" />
                    <input type="text" placeholder="Search prompts or IDs..." value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)} className="pl-9 pr-4 py-2 bg-white/5 border border-white/10 rounded-xl text-sm text-white focus:outline-none focus:ring-2 focus:ring-indigo-500/50 w-56 placeholder-gray-500" />
                    {searchQuery && <X className="w-4 h-4 text-gray-500 absolute right-3 cursor-pointer hover:text-white" onClick={() => setSearchQuery("")} />}
                  </div>

                  {/* Tag Filter */}
                  <select value={filterTag} onChange={(e) => setFilterTag(e.target.value)} className="bg-white/5 border border-white/10 rounded-xl text-sm text-gray-300 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-indigo-500/50">
                    <option value="">All Tags</option>
                    {availableTags.map(t => <option key={t} value={t}>{t}</option>)}
                  </select>

                  {/* Hide Incomplete Toggle */}
                  <div className="flex items-center gap-3 bg-white/5 border border-white/10 px-4 py-2 rounded-xl">
                    <span className="text-xs font-bold uppercase tracking-widest text-gray-400">Complete Only</span>
                    <button onClick={() => setShowOnlyReady(!showOnlyReady)} className={`w-10 h-6 rounded-full transition-colors relative flex items-center ${showOnlyReady ? 'bg-indigo-500' : 'bg-white/10'}`}>
                      <div className={`w-4 h-4 bg-white rounded-full mx-1 transition-transform ${showOnlyReady ? 'translate-x-4' : 'translate-x-0'}`}></div>
                    </button>
                  </div>
                </div>
              </div>

              <div className="grid gap-4">
                {filteredPrompts.length === 0 ? (
                  <div className="text-center py-20 text-gray-500">
                    <p className="text-sm">No scenarios match your filters.</p>
                    {(searchQuery || filterTag) && (
                      <button onClick={() => { setSearchQuery(""); setFilterTag(""); }} className="mt-4 px-4 py-2 rounded-xl bg-indigo-500/20 border border-indigo-500/40 text-indigo-300 text-xs font-bold uppercase">Clear Filters</button>
                    )}
                  </div>
                ) : (
                  filteredPrompts.map(prompt => <PromptItem key={prompt.id} prompt={prompt} onTagClick={setFilterTag} />)
                )}
              </div>
            </div>
          </div>
        )}

        {/* ============ GENERATIONS REVIEW ============ */}
        {activeTab === 'generations' && (
          <div className="animate-in fade-in slide-in-from-bottom-4 duration-700 space-y-8">
            {/* Header */}
            <div className="flex flex-col md:flex-row md:items-end justify-between gap-6">
              <div>
                <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-purple-500/10 border border-purple-500/20 text-purple-300 text-[10px] font-bold uppercase tracking-widest mb-4">
                  <Eye className="w-3.5 h-3.5" /> Generation Review
                </div>
                <h2 className="text-4xl md:text-5xl font-light text-white mb-2 tracking-tight leading-tight">
                  All <span className="font-bold text-transparent bg-clip-text bg-gradient-to-r from-purple-400 to-pink-400">Generations</span>
                </h2>
                <p className="text-gray-500 text-sm">Review video outputs across all models for every prompt</p>
              </div>
              <div className="flex gap-4">
                <StatBox label="Jobs" value={prompts.length} />
                <StatBox label="Success" value={prompts.filter(p => p.status === 'complete').length} />
                <StatBox label="Partial" value={prompts.filter(p => p.status === 'complete' && p.error).length} />
                <StatBox label="Failed" value={prompts.filter(p => p.status === 'error').length} />
              </div>
            </div>

            {/* Filters */}
            <div className="flex flex-wrap items-center gap-3 p-4 bg-white/[0.02] border border-white/5 rounded-2xl">
              <div className="relative flex items-center">
                <Search className="w-4 h-4 text-gray-500 absolute left-3" />
                <input type="text" placeholder="Search prompts, models, IDs..." value={genSearch} onChange={(e) => setGenSearch(e.target.value)} className="pl-9 pr-4 py-2 bg-white/5 border border-white/10 rounded-xl text-sm text-white focus:outline-none focus:ring-2 focus:ring-purple-500/50 w-64 placeholder-gray-500" />
                {genSearch && <X className="w-4 h-4 text-gray-500 absolute right-3 cursor-pointer hover:text-white" onClick={() => setGenSearch("")} />}
              </div>
              <select value={genStatusFilter} onChange={(e) => setGenStatusFilter(e.target.value)} className="bg-white/5 border border-white/10 rounded-xl text-sm text-gray-300 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-purple-500/50">
                <option value="all">All Statuses</option>
                <option value="complete">Complete</option>
                <option value="error">Failed</option>
                <option value="generating">Generating</option>
              </select>
              <select value={genTagFilter} onChange={(e) => setGenTagFilter(e.target.value)} className="bg-white/5 border border-white/10 rounded-xl text-sm text-gray-300 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-purple-500/50">
                <option value="">All Tags</option>
                {availableTags.map(t => <option key={t} value={t}>{t}</option>)}
              </select>
              <button onClick={() => { setGenSearch(""); setGenStatusFilter("all"); setGenTagFilter(""); }} className="text-[10px] font-bold text-gray-400 hover:text-white px-3 py-2 rounded-xl hover:bg-white/5 transition-all uppercase tracking-widest">Clear</button>
            </div>

            {/* Job Cards */}
            <div className="space-y-4">
              {(() => {
                const filtered = prompts.filter(p => {
                  if (genStatusFilter !== "all" && p.status !== genStatusFilter) return false;
                  if (genTagFilter && !(p.categories || []).includes(genTagFilter)) return false;
                  if (genSearch) {
                    const q = genSearch.toLowerCase();
                    const matchText = p.text.toLowerCase().includes(q);
                    const matchId = (p.prompt_id || p.id.toString()).toLowerCase().includes(q);
                    const matchModel = (p.models || []).some(m => m.toLowerCase().includes(q));
                    if (!matchText && !matchId && !matchModel) return false;
                  }
                  return true;
                });
                if (filtered.length === 0) return (
                  <div className="text-center py-20 text-gray-500">
                    <Video className="w-12 h-12 mx-auto mb-4 opacity-30" />
                    <p className="text-sm">No generations match your filters.</p>
                  </div>
                );
                return filtered.map((job: any) => {
                  const isExpanded = expandedJobId === job.id;
                  const results = job.results || {};
                  const modelIds = Object.keys(results);
                  const successCount = modelIds.filter(m => results[m].status === "success" && (results[m].url || results[m].result?.url)).length;
                  const errorCount = modelIds.filter(m => results[m].status === "error").length;
                  const genCount = modelIds.filter(m => results[m].status === "generating").length;

                  return (
                    <div key={job.id} className="relative group bg-[#0d1017] border border-white/5 rounded-3xl overflow-hidden shadow-xl hover:border-white/10 transition-all">
                      {/* Collapsed Header */}
                      <button onClick={() => setExpandedJobId(isExpanded ? null : job.id)} className="w-full p-6 flex items-center gap-6 text-left hover:bg-white/[0.01] transition-all">
                        {/* Status Indicator */}
                        <div className={`w-3 h-3 rounded-full shrink-0 ${job.status === 'complete' ? 'bg-emerald-500' : job.status === 'generating' ? 'bg-indigo-500 animate-pulse' : 'bg-red-500'}`} />

                        {/* Prompt Preview */}
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-3 mb-1">
                            <span className="text-[10px] font-mono text-purple-400 font-bold">{job.prompt_id || job.id}</span>
                            <span className="text-[10px] text-gray-600">{job.timestamp}</span>
                            {job.ratio && <span className="text-[9px] font-bold text-purple-400 px-1.5 py-0.5 rounded bg-purple-500/10 border border-purple-500/20">{job.ratio}</span>}
                          </div>
                          <p className="text-gray-300 text-sm truncate">{job.text}</p>
                        </div>

                        {/* Tags */}
                        <div className="hidden lg:flex flex-wrap gap-1 max-w-[200px]">
                          {(job.categories || []).slice(0, 3).map((tag: string, i: number) => (
                            <span key={i} className="px-2 py-0.5 text-[8px] font-bold uppercase tracking-wider rounded-full bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">{tag}</span>
                          ))}
                          {(job.categories || []).length > 3 && <span className="text-[9px] text-gray-600">+{job.categories.length - 3}</span>}
                        </div>

                        {/* Model Result Summary */}
                        <div className="flex items-center gap-2 shrink-0">
                          {successCount > 0 && <span className="flex items-center gap-1 text-[10px] font-bold text-emerald-400"><CheckCircle2 className="w-3.5 h-3.5" />{successCount}</span>}
                          {errorCount > 0 && <span className="flex items-center gap-1 text-[10px] font-bold text-red-400"><AlertCircle className="w-3.5 h-3.5" />{errorCount}</span>}
                          {genCount > 0 && <span className="flex items-center gap-1 text-[10px] font-bold text-indigo-400"><Loader2 className="w-3.5 h-3.5 animate-spin" />{genCount}</span>}
                          <span className="text-[10px] text-gray-600">/ {modelIds.length}</span>
                        </div>

                        {isExpanded ? <ChevronUp className="w-5 h-5 text-gray-500" /> : <ChevronDown className="w-5 h-5 text-gray-500" />}
                      </button>

                      {/* Delete Job Button */}
                      <button
                        className="absolute top-3 right-3 p-1.5 rounded-lg bg-red-500/10 hover:bg-red-500/30 text-red-400 hover:text-red-300 transition-all opacity-0 group-hover:opacity-100"
                        title="Delete job"
                        onClick={async (e) => {
                          e.stopPropagation();
                          if (!confirm(`Delete job "${job.text?.slice(0, 60)}..."?\nThis cannot be undone.`)) return;
                          try {
                            const res = await fetch(`${API_BASE_URL}/api/admin/jobs/${job.id}`, { method: 'DELETE' });
                            if (!res.ok) throw new Error('Failed to delete');
                            setGenJobs((prev: any[]) => prev.filter((j: any) => j.id !== job.id));
                          } catch (err) {
                            alert('Failed to delete job');
                          }
                        }}
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>

                      {/* Expanded: Video Grid */}
                      {isExpanded && (
                        <div className="border-t border-white/5 p-6 space-y-6 animate-in fade-in slide-in-from-top-2 duration-300">
                          {/* Full Prompt */}
                          <div className="bg-white/[0.02] border border-white/5 rounded-2xl p-5">
                            <p className="text-gray-200 text-sm leading-relaxed">&ldquo;{job.text}&rdquo;</p>
                          </div>

                          {/* Input Images */}
                          {(job.start_image_url || job.end_image_url || job.reference_images?.length > 0) && (
                            <div className="flex items-center gap-4">
                              <span className="text-[10px] font-bold uppercase tracking-widest text-gray-500">Inputs:</span>
                              {job.start_image_url && <ImageThumbnail url={job.start_image_url} label="Start" onClick={() => setExpandedImage(job.start_image_url)} />}
                              {job.end_image_url && <ImageThumbnail url={job.end_image_url} label="End" onClick={() => setExpandedImage(job.end_image_url)} />}
                              {job.reference_images?.map((url: string, i: number) => (
                                <ImageThumbnail key={i} url={url} label={`Ref${i+1}`} onClick={() => setExpandedImage(url)} />
                              ))}
                            </div>
                          )}

                          {/* Download All */}
                          {(() => {
                            const successVideos = modelIds.filter((m: string) => results[m].status === 'success' && (results[m].url || results[m].result?.url));
                            if (successVideos.length === 0) return null;
                            return (
                              <div className="flex items-center justify-between">
                                <span className="text-[10px] font-bold uppercase tracking-widest text-gray-500">{successVideos.length} video{successVideos.length > 1 ? 's' : ''} generated</span>
                                <button
                                  onClick={() => {
                                    for (const m of successVideos) {
                                      const url = formatUrl(results[m].url || results[m].result?.url);
                                      if (url) window.open(url, '_blank');
                                    }
                                  }}
                                  className="flex items-center gap-2 px-4 py-2 rounded-xl bg-indigo-500/10 border border-indigo-500/20 text-indigo-400 text-[11px] font-bold hover:bg-indigo-500/20 transition-all"
                                >
                                  <Download className="w-4 h-4" /> Open All Videos
                                </button>
                              </div>
                            );
                          })()}

                          {/* Retry Failed Models */}
                          {(() => {
                            const failedModels = modelIds.filter((m: string) => results[m].status === 'error');
                            if (failedModels.length === 0) return null;
                            return (
                              <div className="flex items-center justify-between">
                                <span className="text-[10px] font-bold uppercase tracking-widest text-red-400">{failedModels.length} model{failedModels.length > 1 ? 's' : ''} failed</span>
                                <button
                                  onClick={async () => {
                                    if (!confirm(`Retry ${failedModels.length} failed model(s)? This will incur generation costs.`)) return;
                                    try {
                                      const res = await fetch(`${API_BASE_URL}/api/admin/jobs/${job.id}/retry`, { method: 'POST' });
                                      if (!res.ok) throw new Error('Failed to retry');
                                      const data = await res.json();
                                      // Update local state to show generating
                                      setGenJobs((prev: any[]) => prev.map((j: any) => {
                                        if (j.id !== job.id) return j;
                                        const updated = { ...j, results: { ...j.results } };
                                        for (const mid of data.retrying_models || failedModels) {
                                          updated.results[mid] = { status: 'generating' };
                                        }
                                        return updated;
                                      }));
                                    } catch (err) {
                                      alert('Failed to retry models');
                                    }
                                  }}
                                  className="flex items-center gap-2 px-4 py-2 rounded-xl bg-red-500/10 border border-red-500/20 text-red-400 text-[11px] font-bold hover:bg-red-500/20 transition-all"
                                >
                                  <RefreshCw className="w-4 h-4" /> Retry Failed
                                </button>
                              </div>
                            );
                          })()}

                          {/* Video Grid */}
                          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
                            {modelIds.map((modelId: string) => {
                              const r = results[modelId];
                              const videoUrl = r.url || r.result?.url;
                              const status = r.status;
                              const latency = r.latency;
                              const error = r.error;
                              const isVeo = modelId.toLowerCase().includes('veo');
                              const isKling = modelId.toLowerCase().includes('kling');
                              const isSeedance = modelId.toLowerCase().includes('seedance');
                              const borderColor = status === 'success' && videoUrl
                                ? (isVeo ? 'border-indigo-500/20' : isKling ? 'border-pink-500/20' : isSeedance ? 'border-emerald-500/20' : 'border-gray-500/20')
                                : status === 'error' ? 'border-red-500/20' : 'border-white/5';

                              return (
                                <div key={modelId} className={`bg-[#06080b] border rounded-2xl overflow-hidden transition-all ${borderColor}`}>
                                  {/* Video / Placeholder */}
                                  <div className="aspect-video bg-black/50 relative">
                                    {status === 'success' && videoUrl ? (
                                      <video
                                        src={formatUrl(videoUrl)}
                                        controls
                                        preload="metadata"
                                        className="w-full h-full object-contain"
                                        playsInline
                                      />
                                    ) : status === 'generating' ? (
                                      <div className="absolute inset-0 flex flex-col items-center justify-center">
                                        <Loader2 className="w-8 h-8 text-indigo-500 animate-spin mb-2" />
                                        <span className="text-[10px] text-gray-500 font-bold uppercase tracking-widest">Generating...</span>
                                      </div>
                                    ) : status === 'error' ? (
                                      <div className="absolute inset-0 flex flex-col items-center justify-center p-4">
                                        <AlertCircle className="w-8 h-8 text-red-500/50 mb-2" />
                                        <span className="text-[10px] text-red-400 font-bold uppercase tracking-widest mb-2">Failed</span>
                                        <p className="text-[9px] text-red-300/60 text-center line-clamp-3 font-mono">{error}</p>
                                      </div>
                                    ) : (
                                      <div className="absolute inset-0 flex items-center justify-center">
                                        <Video className="w-8 h-8 text-gray-700" />
                                      </div>
                                    )}
                                  </div>

                                  {/* Model Info Bar */}
                                  <div className="p-3 flex items-center justify-between">
                                    <div className="flex items-center gap-2">
                                      <div className={`w-7 h-7 rounded-lg flex items-center justify-center text-[9px] font-black border border-white/10 ${isVeo ? 'bg-[#0f1115] text-indigo-400' : isKling ? 'bg-[#1a1c22] text-pink-400' : isSeedance ? 'bg-[#12141a] text-emerald-400' : 'bg-[#1a1c23] text-gray-400'}`}>
                                        {modelId.charAt(0).toUpperCase()}
                                      </div>
                                      <div>
                                        <div className="text-[11px] font-bold text-white">{modelId}</div>
                                        {latency != null && (
                                          <div className="flex items-center gap-1 text-[9px] text-gray-500">
                                            <Clock className="w-3 h-3" /> {typeof latency === 'number' ? `${latency.toFixed(1)}s` : latency}
                                          </div>
                                        )}
                                      </div>
                                    </div>
                                    <div className="flex items-center gap-2">
                                      {status === 'success' && videoUrl && (
                                        <a
                                          href={formatUrl(videoUrl)}
                                          download={`${job.prompt_id || job.id}_${modelId}.mp4`}
                                          target="_blank"
                                          rel="noopener noreferrer"
                                          className="p-1.5 rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 transition-all group/dl"
                                          title="Download video"
                                          onClick={(e) => {
                                            e.stopPropagation();
                                            // For signed GCS URLs, open in new tab (download attr may not work cross-origin)
                                            window.open(formatUrl(videoUrl), '_blank');
                                            e.preventDefault();
                                          }}
                                        >
                                          <Download className="w-3.5 h-3.5 text-gray-400 group-hover/dl:text-white" />
                                        </a>
                                      )}
                                      <div className={`w-2 h-2 rounded-full ${status === 'success' && videoUrl ? 'bg-emerald-500' : status === 'error' ? 'bg-red-500' : status === 'generating' ? 'bg-indigo-500 animate-pulse' : 'bg-gray-700'}`} />
                                    </div>
                                  </div>
                                </div>
                              );
                            })}
                          </div>

                          {/* Error Summary */}
                          {job.error && (
                            <div className="flex items-start gap-3 text-[11px] text-red-100 bg-red-500/10 border border-red-500/20 px-4 py-3 rounded-xl">
                              <AlertCircle className="w-4 h-4 mt-0.5 shrink-0 text-red-400" />
                              <span className="font-mono leading-tight break-words">{job.error}</span>
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  );
                });
              })()}
            </div>
          </div>
        )}

        {/* ============ GUIDELINES ============ */}
        {activeTab === 'guidelines' && (
          <div className="text-gray-500 text-center py-20 font-light">Refer to the Rating Guidelines documentation.</div>
        )}

        {/* ============ BATCH ============ */}
        {activeTab === 'batch' && (
          <div className="animate-in fade-in slide-in-from-bottom-4 duration-700 space-y-8">
            <div className="bg-[#0d1017] border border-white/10 rounded-[28px] p-8 md:p-10 shadow-3xl">
              <div className="flex items-center gap-3 mb-8">
                <div className="w-12 h-12 rounded-2xl bg-indigo-500/10 flex items-center justify-center border border-indigo-500/20"><UploadCloud className="w-6 h-6 text-indigo-400" /></div>
                <div>
                  <h3 className="text-xl font-semibold text-white">Batch Scenario Runner</h3>
                  <p className="text-sm text-gray-500">Upload via Google Sheets. Rows with the same Prompt ID are grouped into a single job.</p>
                </div>
              </div>

              {batchRows.length === 0 ? (
                <div className="border border-white/10 rounded-2xl p-8 bg-white/[0.02]">
                  <div className="flex flex-col gap-4">
                    <label className="text-sm text-gray-400 font-bold uppercase tracking-widest">Target Google Sheet</label>
                    <p className="text-xs text-gray-500 mb-2">Columns: <span className="font-mono text-[10px] text-gray-400">A: PromptID, B: Mode, C: Text, D: Start, E: End, F-H: Ref1-3, I: Model, J: Success, K: Error, L: Ratio (optional)</span></p>
                    <input type="text" value={sheetUrl} onChange={(e) => setSheetUrl(e.target.value)} placeholder="https://docs.google.com/spreadsheets/d/..." className="w-full bg-[#06080b] border border-white/10 rounded-xl px-6 py-4 text-white focus:outline-none focus:border-indigo-500 font-mono text-sm" />
                    <button onClick={handleBatchLoadFromSheet} disabled={isLoadingSheet || !sheetUrl} className="self-start bg-gradient-to-r from-indigo-500 to-purple-600 disabled:from-gray-700 disabled:to-gray-800 px-8 py-4 rounded-xl text-white font-black tracking-widest text-sm transition-all shadow-lg flex items-center gap-2">
                      {isLoadingSheet ? <Loader2 className="w-5 h-5 animate-spin" /> : <LinkIcon className="w-5 h-5" />} LOAD SHEET
                    </button>
                  </div>
                </div>
              ) : (
                <div className="space-y-6">
                  {/* Header: stats, search, actions */}
                  <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
                    <div className="flex items-center gap-4">
                      <div className="text-sm text-gray-400">
                        <span className="text-white font-bold">{batchRows.length}</span> rows in{' '}
                        <span className="text-white font-bold">{Object.keys(getBatchGroups()).length}</span> groups
                      </div>
                      {batchProgress.total > 0 && (
                        <div className="flex items-center gap-2 text-xs">
                          <div className="w-32 h-1.5 bg-white/10 rounded-full overflow-hidden">
                            <div className="h-full bg-gradient-to-r from-indigo-500 to-emerald-500 rounded-full transition-all" style={{ width: `${Math.round((batchProgress.done / batchProgress.total) * 100)}%` }} />
                          </div>
                          <span className="text-gray-400">{batchProgress.done}/{batchProgress.total}</span>
                          {batchProgress.errors > 0 && <span className="text-red-400">{batchProgress.errors} failed</span>}
                        </div>
                      )}
                    </div>
                    <div className="flex items-center gap-3">
                      <div className="relative flex items-center">
                        <Search className="w-4 h-4 text-gray-500 absolute left-3" />
                        <input type="text" placeholder="Search prompts, IDs, models..." value={batchSearch} onChange={(e) => setBatchSearch(e.target.value)} className="pl-9 pr-4 py-2 bg-white/5 border border-white/10 rounded-xl text-sm text-white focus:outline-none focus:ring-2 focus:ring-indigo-500/50 w-56 placeholder-gray-500" />
                        {batchSearch && <X className="w-4 h-4 text-gray-500 absolute right-3 cursor-pointer hover:text-white" onClick={() => setBatchSearch("")} />}
                      </div>
                      <button onClick={handleRunBatch} disabled={isBatchRunning} className="bg-gradient-to-r from-indigo-500 to-purple-600 px-6 py-2 rounded-xl text-white font-bold text-sm hover:scale-105 transition-transform disabled:opacity-50 flex items-center gap-2">
                        {isBatchRunning ? <Loader2 className="w-4 h-4 animate-spin" /> : <Zap className="w-4 h-4" />} Run Batch
                      </button>
                      <button onClick={() => { setBatchRows([]); setBatchProgress({ done: 0, total: 0, errors: 0 }); setBatchSearch(""); }} className="bg-red-500/10 text-red-400 hover:bg-red-500/20 px-6 py-2 rounded-xl font-bold text-sm">Clear</button>
                    </div>
                  </div>

                  {/* Grouped batch display */}
                  <div className="space-y-3">
                    {filteredBatchGroups().map(g => {
                      const statusIcon = g.allSuccess
                        ? <CheckCircle2 className="w-4 h-4 text-emerald-500" />
                        : g.hasError
                          ? <AlertCircle className="w-4 h-4 text-red-500" />
                          : g.rows.some(r => r.batchStatus === "running")
                            ? <Loader2 className="w-4 h-4 text-indigo-400 animate-spin" />
                            : <div className="w-4 h-4 rounded-full border-2 border-white/20" />;
                      return (
                        <div key={g.promptId} className={`border rounded-2xl p-5 transition-all ${g.allSuccess ? 'border-emerald-500/20 bg-emerald-500/[0.03]' : g.hasError ? 'border-red-500/20 bg-red-500/[0.03]' : 'border-white/5 bg-white/[0.02] hover:bg-white/[0.03]'}`}>
                          <div className="flex items-start justify-between gap-4">
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-3 mb-2">
                                {statusIcon}
                                <span className="font-mono text-sm text-purple-400 font-bold">{g.promptId}</span>
                                <span className="px-2 py-0.5 text-[9px] font-black uppercase tracking-widest rounded-full bg-white/5 border border-white/10 text-gray-400">{g.mode.toUpperCase()}</span>
                                <span className="px-2 py-0.5 text-[9px] font-black uppercase tracking-widest rounded-full bg-purple-500/10 border border-purple-500/20 text-purple-400">{g.ratio}</span>
                              </div>
                              <p className="text-gray-300 text-sm leading-relaxed line-clamp-2 mb-2">{g.text}</p>
                              <div className="flex flex-wrap items-center gap-2">
                                <span className="text-[10px] font-bold text-gray-500 uppercase tracking-widest">Models:</span>
                                {g.models.map((m, i) => (
                                  <span key={i} className="px-2 py-0.5 text-[10px] font-bold rounded-lg bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">{m}</span>
                                ))}
                              </div>
                              {g.hasError && g.rows.filter(r => r.error).length > 0 && (
                                <div className="mt-2 text-[11px] text-red-400 font-mono">{g.rows.find(r => r.error)?.error}</div>
                              )}
                            </div>
                            <div className="text-right shrink-0">
                              <div className="text-[10px] text-gray-500 uppercase tracking-widest">{g.rows.length} row{g.rows.length > 1 ? 's' : ''}</div>
                            </div>
                          </div>
                        </div>
                      );
                    })}
                    {filteredBatchGroups().length === 0 && batchSearch && (
                      <div className="text-center py-10 text-gray-500 text-sm">
                        No groups match &ldquo;{batchSearch}&rdquo;
                        <button onClick={() => setBatchSearch("")} className="ml-2 text-indigo-400 hover:text-indigo-300">Clear</button>
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </main>
    </div>
  );
}

// ===================================================================
// Sub-Components
// ===================================================================

function ImageInputCell({ label, value, onChange, icon, onGenerate, isGenerating, onUpload }: { label: string; value: string; onChange: (v: string) => void; icon: any; onGenerate: () => void; isGenerating: boolean; onUpload: (e: React.ChangeEvent<HTMLInputElement>) => void }) {
  const [hasError, setHasError] = useState(false);
  useEffect(() => { setHasError(false); }, [value]);

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between text-[10px] font-black uppercase tracking-widest text-gray-500 italic ml-1">
        <div className="flex items-center gap-2">{icon} {label}</div>
        <label className="text-purple-400 hover:text-purple-300 transition-colors flex items-center gap-1 cursor-pointer">
          <PlusCircle className="w-3 h-3" /> Upload
          <input type="file" className="hidden" onChange={onUpload} accept="image/*" />
        </label>
      </div>
      <input type="text" value={value} onChange={(e) => onChange(e.target.value)} placeholder="URL" className="block w-full bg-[#06080b] border border-white/10 rounded-xl px-4 py-3 text-xs text-gray-300 focus:outline-none focus:ring-1 focus:ring-indigo-500/50 transition-all" />
      <div onClick={!value ? onGenerate : undefined} className={`aspect-square rounded-xl bg-[#06080b] border border-white/5 overflow-hidden flex items-center justify-center relative group/preview shadow-inner cursor-pointer ${!value ? 'hover:border-indigo-500/30' : ''}`}>
        {value ? (
          <>
            <img src={value} alt={label} className={`w-full h-full object-cover transition-transform group-hover/preview:scale-105 ${hasError ? 'opacity-20 grayscale' : ''}`} onError={() => setHasError(true)} />
            {hasError && (
              <div className="absolute inset-0 flex flex-col items-center justify-center bg-red-500/10 backdrop-blur-[2px]">
                <AlertCircle className="w-6 h-6 text-red-500 mb-2" />
                <span className="text-[8px] text-red-400 font-bold uppercase tracking-widest text-center px-4">Failed to load</span>
              </div>
            )}
          </>
        ) : (
          isGenerating ? <Loader2 className="w-5 h-5 text-indigo-500 animate-spin" /> : <PlusCircle className="w-5 h-5 text-gray-800 group-hover/preview:text-indigo-500/30 transition-colors" />
        )}
      </div>
    </div>
  );
}

function PromptItem({ prompt, onTagClick }: { prompt: Prompt; onTagClick: (tag: string) => void }) {
  return (
    <div className="bg-[#0d1017] border border-white/5 rounded-3xl p-6 md:p-8 hover:bg-white/[0.02] transition-all hover:border-white/10 group flex flex-col lg:flex-row items-start lg:items-center justify-between gap-6 shadow-xl w-full overflow-hidden">
      <div className="flex flex-col sm:flex-row items-start gap-6 flex-1 min-w-0 w-full">
        <div className="flex flex-wrap -space-x-4 shrink-0 px-2 py-1">
          {prompt.start_image_url && <ImageThumbnail url={prompt.start_image_url} label="S" onClick={() => window.dispatchEvent(new CustomEvent('expand-image', { detail: prompt.start_image_url }))} />}
          {prompt.end_image_url && <ImageThumbnail url={prompt.end_image_url} label="E" onClick={() => window.dispatchEvent(new CustomEvent('expand-image', { detail: prompt.end_image_url }))} />}
          {prompt.reference_images?.map((url, i) => (
            <ImageThumbnail key={i} url={url} label={`R${i + 1}`} onClick={() => window.dispatchEvent(new CustomEvent('expand-image', { detail: url }))} />
          ))}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex flex-wrap items-center gap-3 mb-3">
            {(prompt.categories || []).map((tag, idx) => (
              <button key={idx} onClick={() => onTagClick(tag)} className="px-3 py-1 text-[9px] font-black uppercase tracking-[0.2em] rounded-full bg-indigo-500/10 text-indigo-400 border border-indigo-500/20 hover:bg-indigo-500/20 transition-all cursor-pointer">
                {tag}
              </button>
            ))}
            {prompt.ratio && prompt.ratio !== "16:9" && (
              <span className="px-2 py-1 text-[9px] font-black uppercase tracking-widest rounded-full bg-purple-500/10 text-purple-400 border border-purple-500/20">{prompt.ratio}</span>
            )}
            <span className="text-[10px] text-gray-600 font-mono italic whitespace-nowrap overflow-hidden text-ellipsis max-w-[200px]" title={prompt.prompt_id || prompt.id.toString()}>
              {prompt.prompt_id ? `PID: ${prompt.prompt_id}` : `ID_${prompt.id.toString().slice(-4)}`}
            </span>
          </div>
          <p className="text-gray-200 text-lg leading-relaxed font-light line-clamp-2 break-words">&ldquo;{prompt.text}&rdquo;</p>
          {prompt.status === 'error' && (
            <div className="mt-4 flex items-start gap-3 text-[11px] text-red-100 bg-red-500/20 border border-red-500/30 px-4 py-3 rounded-2xl shadow-lg w-full overflow-hidden">
              <AlertCircle className="w-4 h-4 mt-0.5 shrink-0 text-red-400" />
              <div className="flex flex-col gap-1 min-w-0">
                <span className="font-black uppercase tracking-widest text-red-400 shrink-0">Error</span>
                <span className="font-mono leading-tight opacity-90 break-words">{prompt.error || "Check backend logs."}</span>
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="flex flex-row lg:flex-col items-center lg:items-end justify-between lg:justify-center gap-4 w-full lg:w-auto pt-4 lg:pt-0 border-t lg:border-t-0 border-white/5">
        <div className="flex -space-x-3 group-hover:gap-2 transition-all">
          {(prompt.models || []).map((model, i) => (
            <div key={i} title={model} className={`w-9 h-9 rounded-xl flex items-center justify-center text-[10px] font-black shadow-2xl border border-white/10 ${model.toLowerCase().includes('veo') ? 'bg-[#0f1115] text-indigo-400' : model.toLowerCase().includes('kling') ? 'bg-[#1a1c22] text-pink-400' : model.toLowerCase().includes('seedance') ? 'bg-[#12141a] text-emerald-400' : 'bg-[#1a1c23] text-gray-400'}`}>
              {model.charAt(0).toUpperCase()}
            </div>
          ))}
        </div>
        <div className={`flex items-center gap-2 text-[10px] font-black uppercase tracking-widest px-3 py-1.5 rounded-lg border ${prompt.status === 'complete' ? 'bg-emerald-500/10 text-emerald-500 border-emerald-500/20' : prompt.status === 'generating' ? 'bg-indigo-500/10 text-indigo-500 border-indigo-500/20' : 'bg-amber-500/10 text-amber-500 border-amber-500/20'}`}>
          <span className={`w-1 h-1 rounded-full ${prompt.status === 'complete' ? 'bg-emerald-500' : prompt.status === 'generating' ? 'bg-indigo-500 animate-pulse' : 'bg-amber-500'}`}></span>
          {prompt.status}
        </div>
      </div>
    </div>
  );
}

function ImageThumbnail({ url, label, onClick }: { url: string; label: string; onClick?: () => void }) {
  return (
    <div onClick={onClick} className={`w-16 h-16 rounded-xl overflow-hidden border-2 border-[#0d1017] shadow-2xl relative group/thumb ${onClick ? 'cursor-zoom-in' : ''}`}>
      <img src={url} alt={label} className="w-full h-full object-cover transition-transform group-hover/thumb:scale-125" />
      <div className="absolute top-1 right-1 bg-black/60 backdrop-blur-md px-1 rounded text-[8px] font-bold text-white leading-none py-0.5">{label}</div>
    </div>
  );
}

function StatBox({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="bg-white/[0.03] border border-white/10 rounded-2xl px-6 py-4 flex flex-col items-center justify-center min-w-[120px] shadow-2xl">
      <div className="text-2xl font-bold text-white leading-none">{value}</div>
      <div className="text-[10px] font-bold text-gray-500 uppercase tracking-widest mt-2">{label}</div>
    </div>
  );
}
