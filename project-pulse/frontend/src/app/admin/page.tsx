'use client';
const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "";
import { useState, useEffect } from 'react';
import Papa from 'papaparse';
import {
  PlusCircle, Search, Sparkles, BookOpen, Crown, Layers, Award,
  Target, Eye, Database, AlignCenter, ArrowRight, CheckCircle2,
  AlertCircle, Loader2, Zap, Info, ShieldCheck, Image as ImageIcon, Link as LinkIcon,
  PlayCircle, StopCircle, UploadCloud
} from 'lucide-react';

const CATEGORIES = ["Studio Shots", "Beauty", "Animation", "Model Bug Backlog"];

interface Prompt {
  id: number | string;
  prompt_id?: string;
  text: string;
  start_image_url?: string;
  end_image_url?: string;
  reference_image_url?: string;
  reference_images?: string[];
  category?: string; // Legacy
  categories: string[];
  models: string[];
  status: string;
  error?: string;
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

  const [newPromptText, setNewPromptText] = useState("");
  const [newPromptStartImage, setNewPromptStartImage] = useState("");
  const [newPromptEndImage, setNewPromptEndImage] = useState("");
  const [newPromptRefImage, setNewPromptRefImage] = useState("");
  const [newPromptRefImages, setNewPromptRefImages] = useState<string[]>(["", "", ""]);
  const [injectionMode, setInjectionMode] = useState<'t2v' | 'i2v' | 'r2v'>('i2v');
  const [newPromptCategories, setNewPromptCategories] = useState<string[]>([CATEGORIES[0]]);
  const [customTag, setCustomTag] = useState("");
  const [isGeneratingTags, setIsGeneratingTags] = useState(false);
  const [activeTab, setActiveTab] = useState('prompts');
  const [isGenerating, setIsGenerating] = useState(false);
  const [isImageGenerating, setIsImageGenerating] = useState(false);
  const [showSuccess, setShowSuccess] = useState(false);
  const [showOnlyReady, setShowOnlyReady] = useState(true);
  const [expandedImage, setExpandedImage] = useState<string | null>(null);

  // Batch State
  const [batchRows, setBatchRows] = useState<any[]>([]);
  const [isBatchRunning, setIsBatchRunning] = useState(false);
  const [sheetUrl, setSheetUrl] = useState("");
  const [isLoadingSheet, setIsLoadingSheet] = useState(false);

  // Auth State
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [authError, setAuthError] = useState("");

  useEffect(() => {
    const savedAuth = localStorage.getItem('project_pulse_admin_auth');
    if (savedAuth === 'true') setIsAuthenticated(true);

    // Listen for image expansions from child components
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
    } catch (err) {
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
    const interval = setInterval(fetchJobs, 5000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    if (batchRows.length === 0) return;
    setBatchRows(prev => {
      let changed = false;
      let sheetUpdates: any[] = [];
      const next = prev.map(row => {
        if (row.success || row.error) return row; // already finished
        const matchingJob = prompts.find(p => (p as any).prompt_id === row.promptId);
        if (matchingJob) {
          const resObj = (matchingJob as any).results || {};
          let modelKey = (row.model || "").toLowerCase();
          let foundKey = Object.keys(resObj).find(k => k.toLowerCase().includes(modelKey) || modelKey.includes(k.toLowerCase()));
          if (foundKey) {
            const status = resObj[foundKey].status;
            if (status === "success") {
              changed = true;
              sheetUpdates.push({ rowIndex: row.rowIndex, success: true, error: "" });
              return { ...row, success: true, error: "" };
            } else if (status === "error") {
              const errorMsg = resObj[foundKey].error || "Failed";
              changed = true;
              sheetUpdates.push({ rowIndex: row.rowIndex, success: false, error: errorMsg });
              return { ...row, success: false, error: errorMsg };
            }
          }
        }
        return row;
      });

      if (changed && sheetUrl) {
        sheetUpdates.forEach(async (upd) => {
          try {
            await fetch(`${API_BASE_URL}/api/admin/batch/sheet/update`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ url: sheetUrl, row: upd.rowIndex, success: upd.success, error: upd.error })
            });
          } catch (e) {
            console.error("Failed to update sheet:", e);
          }
        });
      }

      return changed ? next : prev;
    });
  }, [prompts]);

  const formatUrl = (url?: string) => {
    if (!url) return url;
    if (url.startsWith('/api/media')) return `${API_BASE_URL}${url}`;
    return url;
  };

  const fetchJobs = async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/api/admin/jobs`);
      const data = await res.json();

      // Map backend Job to frontend Prompt
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
          } else if (statuses.every(s => s === "error")) {
            status = "error";
            // Collect all error messages
            errorMsg = modelIds.map(m => `${m}: ${job.results[m].error || 'Unknown error'}`).join(" | ");
          } else if (statuses.includes("error")) {
            // Partial error
            errorMsg = modelIds
              .filter(m => job.results[m].status === "error")
              .map(m => `${m}: ${job.results[m].error || 'Error'}`)
              .join(" | ");
          }
        }

        return {
          ...job,
          start_image_url: formatUrl(job.start_image_url),
          end_image_url: formatUrl(job.end_image_url),
          reference_image_url: formatUrl(job.reference_image_url),
          reference_images: job.reference_images ? job.reference_images.map(formatUrl) : undefined,
          text: job.prompt || "No prompt text",
          models: modelIds,
          status: status,
          error: errorMsg,
          timestamp: job.timestamp ? new Date(job.timestamp * 1000).toLocaleString() : "Just now"
        };
      });

      console.log("Mapped Jobs:", mapped);
      setPrompts(mapped);
    } catch (err) {
      console.error("Failed to fetch jobs", err);
    }
  };

  const fetchModels = async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/api/models`);
      const data = await res.json();
      setModels(data);
    } catch (err) {
      console.error("Failed to fetch models", err);
    }
  };


  const handleToggleModel = async (mid: string) => {
    try {
      await fetch(`${API_BASE_URL}/api/models/${mid}/toggle`, { method: "POST" });
      fetchModels();
    } catch (err) {
      console.error("Failed to toggle model", err);
    }
  };

  const handleDeleteModel = async (mid: string) => {
    if (!confirm("Are you sure you want to delete this model?")) return;
    try {
      await fetch(`${API_BASE_URL}/api/models/${mid}`, { method: "DELETE" });
      fetchModels();
    } catch (err) {
      console.error("Failed to delete model", err);
    }
  };

  const handleGenerateImage = async (field: string) => {
    if (!newPromptText) return alert("Please enter prompt text first in the 'Video Core Prompt' box");
    setIsImageGenerating(true);
    try {
      const resp = await fetch(`${API_BASE_URL}/api/generate-image`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: newPromptText })
      });
      const data = await resp.json();
      if (data.status === "success") {
        if (field === "start") setNewPromptStartImage(data.url);
        else if (field === "end") setNewPromptEndImage(data.url);
        else if (field === "ref") setNewPromptRefImage(data.url);
        else if (field.startsWith("ref_")) {
          const idx = parseInt(field.split("_")[1]);
          const newRefs = [...newPromptRefImages];
          newRefs[idx] = data.url;
          setNewPromptRefImages(newRefs);
        }
      } else {
        alert("Generation failed: " + (data.detail || "Unknown error"));
      }
    } catch (err) {
      console.error("Image gen failed", err);
      alert("Failed to connect to backend for image generation");
    } finally {
      setIsImageGenerating(false);
    }
  };

  const handleSuggestTags = async () => {
    if (!newPromptText.trim()) return alert("Please enter prompt text first");
    setIsGeneratingTags(true);
    try {
      const resp = await fetch(`${API_BASE_URL}/api/admin/generate-tags`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text: newPromptText,
          start_image_url: injectionMode === 'i2v' ? newPromptStartImage : null,
          end_image_url: injectionMode === 'i2v' ? newPromptEndImage : null,
          reference_images: injectionMode === 'r2v' ? newPromptRefImages.filter(u => u !== "") : null
        })
      });
      const data = await resp.json();
      if (data.status === "success") {
        // Merge with existing but maintain unique
        const merged = Array.from(new Set([...newPromptCategories, ...data.tags]));
        setNewPromptCategories(merged);
      }
    } catch (err) {
      console.error("Failed to suggest tags", err);
    } finally {
      setIsGeneratingTags(false);
    }
  };

  const handleImageUpload = async (e: React.ChangeEvent<HTMLInputElement>, setter: (val: string) => void) => {
    const file = e.target.files?.[0];
    if (!file) return;

    const formData = new FormData();
    formData.append('file', file);

    try {
      const resp = await fetch(`${API_BASE_URL}/api/upload`, {
        method: "POST",
        body: formData
      });
      const data = await resp.json();
      if (data.status === "success") {
        setter(data.url);
      } else {
        alert("Upload failed: " + (data.detail || "Unknown error"));
      }
    } catch (err) {
      console.error("Upload failed", err);
      alert("Failed to connect to backend for upload");
    }
  };

  const handleAddPrompt = async () => {
    if (!newPromptText.trim() || isGenerating) return;

    setIsGenerating(true);

    try {
      const response = await fetch(`${API_BASE_URL}/api/generate`, {
        // Use full URL to avoid port conflict issues if proxy isn't set
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          text: newPromptText,
          categories: newPromptCategories,
          ratio: "16:9",
          start_image_url: injectionMode === 'i2v' ? (newPromptStartImage || null) : null,
          end_image_url: injectionMode === 'i2v' ? (newPromptEndImage || null) : null,
          reference_images: injectionMode === 'r2v' ? newPromptRefImages.filter(u => u !== "") : null,
          reference_image_url: injectionMode === 'r2v' ? (newPromptRefImages[0] || null) : (newPromptRefImage || null),
          mode: injectionMode
        })
      });

      if (!response.ok) {
        throw new Error(`Server responded with ${response.status}`);
      }

      const data = await response.json();
      console.log("✅ Generation Request Successful:", data);

      const newPrompt: Prompt = {
        id: data.job_id || Date.now(),
        prompt_id: data.job_id,
        text: newPromptText,
        start_image_url: injectionMode === 'i2v' ? newPromptStartImage : undefined,
        end_image_url: injectionMode === 'i2v' ? newPromptEndImage : undefined,
        reference_image_url: injectionMode === 'r2v' ? newPromptRefImages[0] : newPromptRefImage,
        reference_images: injectionMode === 'r2v' ? newPromptRefImages.filter(u => u !== "") : undefined,
        categories: newPromptCategories,
        category: newPromptCategories[0], // Legacy support
        models: ["Veo", "Kling", "Seedance"],
        status: "generating",
        timestamp: "Just now"
      };

      setPrompts([newPrompt, ...prompts]);
      setNewPromptCategories([CATEGORIES[0]]);
      setCustomTag("");
      setShowSuccess(true);
      setTimeout(() => setShowSuccess(false), 3000);

    } catch (e) {
      console.error("❌ API Error:", e);
    } finally {
      setIsGenerating(false);
    }
  };

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
        for (let i = 1; i < rows.length; i++) { // Skip header row 0
          const row = rows[i];
          if (row.length > 2 && row[0]) {
            mapped.push({
              promptId: row[0],
              mode: (row[1] || "").toLowerCase().trim(),
              text: row[2],
              startImg: row[3],
              endImg: row[4],
              ref1: row[5],
              ref2: row[6],
              ref3: row[7],
              model: row[8],
              success: String(row[9]).trim().toUpperCase() === "TRUE",
              error: row[10] || "",
              rowIndex: i + 1 // Google Sheets is 1-indexed (so row[0] is index 1, skip 1 is index 2)
            });
          }
        }
        setBatchRows(mapped.filter((r: any) => r.promptId && r.promptId.toLowerCase() !== "prompt id"));
      } else {
        alert("Load Failed: " + (data.detail || "Unknown error"));
      }
    } catch (e) {
      console.error(e);
      alert("Failed to connect to backend sheet integration");
    } finally {
      setIsLoadingSheet(false);
    }
  };

  const handleRunBatch = async () => {
    if (batchRows.length === 0) return;
    setIsBatchRunning(true);

    // Group rows by Prompt ID
    const grouped: Record<string, any> = {};
    for (const row of batchRows) {
      if (row.success) continue; // Ignore all success entries!
      if (!grouped[row.promptId]) {
        grouped[row.promptId] = {
          mode: row.mode,
          text: row.text,
          startImg: row.startImg,
          endImg: row.endImg,
          refs: [row.ref1, row.ref2, row.ref3].filter(Boolean),
          models: [],
          rowIndices: [],
        };
      }
      if (row.model) grouped[row.promptId].models.push(row.model.trim());
      if (row.rowIndex) grouped[row.promptId].rowIndices.push(row.rowIndex);
    }

    try {
      const generatedPrompts: any[] = [];
      const keys = Object.keys(grouped);

      console.log(`[Batch] Found ${keys.length} unique prompts to process in chunks of 10.`);

      for (let i = 0; i < keys.length; i += 10) {
        const chunkKeys = keys.slice(i, i + 10);
        console.log(`[Batch] Processing chunk from index ${i} to ${i + chunkKeys.length}`);

        const chunkPromises = chunkKeys.map(async (pid) => {
          const group = grouped[pid];
          console.log(`[Batch Debug] Submitting Prompt ID: ${pid} with models: ${group.models.join(", ")}`);

          try {
            const res = await fetch(`${API_BASE_URL}/api/generate`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                text: group.text,
                categories: ["Batch Script"],
                ratio: "16:9",
                start_image_url: group.startImg || null,
                end_image_url: group.endImg || null,
                reference_images: group.refs.length > 0 ? group.refs : null,
                reference_image_url: group.refs && group.refs.length > 0 ? group.refs[0] : null,
                mode: group.mode,
                model_ids: group.models,
                prompt_id: pid
              })
            });

            if (!res.ok) {
              const errText = await res.text();
              throw new Error(`API Error ${res.status}: ${errText}`);
            }

            const data = await res.json();
            console.log(`[Batch Debug] Success submitted Prompt ID: ${pid} -> Job: ${data.job_id}`);

            // Update sheet for all rows inside this prompt group mapping as TRUE
            for (const rIndex of group.rowIndices) {
              fetch(`${API_BASE_URL}/api/admin/batch/sheet/update`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ url: sheetUrl, row: rIndex, success: true, error: "" })
              }).catch(e => console.error(`[Batch Debug] Sheet update failed for row ${rIndex}`, e));
            }

            return { pid, group, data, status: "success" };
          } catch (err: any) {
            console.error(`[Batch Debug] Submission failed for Prompt ID ${pid}:`, err);

            // Mark failing rows with error string
            for (const rIndex of group.rowIndices) {
              fetch(`${API_BASE_URL}/api/admin/batch/sheet/update`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ url: sheetUrl, row: rIndex, success: false, error: err?.message || "Generation submission failed" })
              }).catch(e => console.error(`[Batch Debug] Sheet update error logging failed for row ${rIndex}`, e));
            }
            return { pid, group, err, status: "error" };
          }
        });

        const chunkResults = await Promise.all(chunkPromises);

        // Push successful ones to UI immediately
        const successResults = chunkResults.filter(r => r.status === "success");
        if (successResults.length > 0) {
          const newPrompts = successResults.map(r => ({
            id: r.data.job_id || Date.now() + Math.random(),
            prompt_id: r.pid,
            text: r.group.text,
            start_image_url: r.group.startImg,
            end_image_url: r.group.endImg,
            reference_image_url: r.group.refs && r.group.refs.length > 0 ? r.group.refs[0] : null,
            reference_images: r.group.refs,
            categories: ["Batch Script"],
            models: r.group.models.length > 0 ? r.group.models : ["Batch"],
            status: "generating",
            timestamp: "Just now",
            results: {}
          }));
          setPrompts(prev => [...newPrompts, ...prev]);
        }
      }

      alert("Batch Jobs submitted successfully in chunks of 10! The sheet has verified rows marked as TRUE. Press Load Sheet to refresh status.");
    } catch (e) {
      console.error("Batch error", e);
    } finally {
      setIsBatchRunning(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#020408] text-white p-6 relative font-sans selection:bg-indigo-500/30 overflow-x-hidden">
      {/* Dynamic Background */}
      <div className="fixed inset-0 z-0 bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-indigo-900/10 via-slate-950 to-[#020408]"></div>
      <div className="fixed inset-0 z-0 opacity-20 bg-[url('https://www.transparenttextures.com/patterns/carbon-fibre.png')]"></div>

      {expandedImage && (
        <div
          className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-black/90 backdrop-blur-sm cursor-zoom-out animate-in fade-in duration-300"
          onClick={() => setExpandedImage(null)}
        >
          <img
            src={expandedImage}
            className="max-w-full max-h-full rounded-2xl shadow-2xl border border-white/10"
            alt="Expanded view"
          />
        </div>
      )}

      {!isAuthenticated && (
        <div className="fixed inset-0 z-[100] bg-[#06080b]/90 backdrop-blur-2xl flex items-center justify-center p-6">
          <div className="max-w-md w-full bg-[#0d1017] border border-white/10 rounded-[40px] p-10 shadow-3xl animate-in fade-in zoom-in-95 duration-500">
            <div className="flex flex-col items-center mb-10">
              <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center shadow-3xl mb-6">
                <ShieldCheck className="w-8 h-8 text-white" />
              </div>
              <h2 className="text-3xl font-bold text-white tracking-tight">Admin Portal</h2>
              <p className="text-gray-500 text-sm mt-2">Internal use only</p>
            </div>

            <form onSubmit={handleLogin} className="space-y-6">
              <div className="space-y-2">
                <label className="text-xs font-bold text-gray-500 uppercase tracking-widest px-1">Identity</label>
                <input
                  type="text"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder="Username"
                  className="w-full bg-[#06080b] border border-white/10 rounded-2xl px-6 py-4 text-white focus:outline-none focus:ring-2 focus:ring-indigo-500/50 transition-all"
                />
              </div>
              <div className="space-y-2">
                <label className="text-xs font-bold text-gray-500 uppercase tracking-widest px-1">Access Key</label>
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="Password"
                  className="w-full bg-[#06080b] border border-white/10 rounded-2xl px-6 py-4 text-white focus:outline-none focus:ring-2 focus:ring-indigo-500/50 transition-all"
                />
              </div>

              {authError && (
                <div className="text-red-400 text-xs font-bold bg-red-500/10 border border-red-500/20 px-4 py-3 rounded-xl flex items-center gap-2">
                  <AlertCircle className="w-4 h-4" /> {authError}
                </div>
              )}

              <button
                type="submit"
                className="w-full bg-gradient-to-r from-indigo-500 to-purple-600 hover:from-indigo-400 hover:to-purple-500 text-white font-black py-5 rounded-2xl shadow-3xl transition-all active:scale-[0.98] mt-4"
              >
                Sign In
              </button>
            </form>
          </div>
        </div>
      )}

      <nav className="fixed w-full border-b border-white/5 bg-[#06080b]/80 backdrop-blur-xl z-50">
        <div className="max-w-7xl mx-auto px-8 py-4 flex items-center justify-between">
          <div className="flex items-center space-x-3 group cursor-pointer transition-transform active:scale-95">
            <div className="bg-gradient-to-br from-indigo-500 via-purple-500 to-pink-500 p-[2px] rounded-xl shadow-[0_0_20px_rgba(99,102,241,0.2)]">
              <div className="bg-[#06080b] p-2 rounded-[10px]">
                <Layers className="w-5 h-5 text-indigo-400" />
              </div>
            </div>
            <h1 className="text-xl font-bold tracking-tight text-white m-0 flex items-center">
              Project&nbsp;<span className="text-transparent bg-clip-text bg-gradient-to-r from-indigo-400 via-purple-400 to-pink-400">Pulse</span>
            </h1>
          </div>

          <div className="flex items-center space-x-2 bg-white/[0.03] border border-white/10 rounded-full p-1 shadow-inner">
            <button
              onClick={() => setActiveTab('prompts')}
              className={`px-6 py-2 rounded-full text-sm font-semibold transition-all duration-300 ${activeTab === 'prompts' ? 'bg-indigo-500 text-white shadow-[0_0_20px_rgba(99,102,241,0.3)]' : 'text-gray-400 hover:text-gray-200'}`}
            >
              Prompt Engine
            </button>
            <button
              onClick={() => setActiveTab('models')}
              className={`px-6 py-2 rounded-full text-sm font-semibold transition-all duration-300 ${activeTab === 'models' ? 'bg-indigo-500 text-white shadow-[0_0_20px_rgba(99,102,241,0.3)]' : 'text-gray-400 hover:text-gray-200'}`}
            >
              Model Registry
            </button>
            <button
              onClick={() => setActiveTab('batch')}
              className={`px-6 py-2 rounded-full text-sm font-semibold flex items-center gap-2 transition-all duration-300 ${activeTab === 'batch' ? 'bg-indigo-500 text-white shadow-[0_0_20px_rgba(99,102,241,0.3)]' : 'text-gray-400 hover:text-gray-200'}`}
            >
              <UploadCloud className="w-4 h-4" /> Batch Upload
            </button>
            <button
              onClick={() => setActiveTab('guidelines')}
              className={`px-6 py-2 rounded-full text-sm font-semibold flex items-center gap-2 transition-all duration-300 ${activeTab === 'guidelines' ? 'bg-indigo-500 text-white shadow-[0_0_20px_rgba(99,102,241,0.3)]' : 'text-gray-400 hover:text-gray-200'}`}
            >
              <BookOpen className="w-4 h-4" /> Guidelines
            </button>
          </div>

          <div className="hidden md:flex items-center gap-3">
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-[10px] font-bold uppercase tracking-wider">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse"></span>
              Live Grid
            </div>
            <button
              onClick={handleLogout}
              className="p-2 text-gray-500 hover:text-white transition-colors"
            >
              Log out
            </button>
          </div>
        </div>
      </nav>

      <main className="max-w-7xl mx-auto px-8 pt-32 pb-20">

        {activeTab === 'models' && (
          <div className="space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-500">
            <section className="bg-white/[0.03] border border-white/10 rounded-3xl p-8 backdrop-blur-sm relative overflow-hidden group">
              <div className="flex items-center space-x-3 mb-6">
                <Database className="w-6 h-6 text-purple-400" />
                <h2 className="text-2xl font-bold text-white m-0">Model Registry</h2>
              </div>



              <div className="space-y-8">
                {['t2v', 'i2v', 'r2v'].map((type) => {
                  const filteredModels = models.filter(m => m.type === type);
                  if (filteredModels.length === 0) return null;

                  return (
                    <div key={type} className="space-y-4">
                      <div className="flex items-center gap-3 px-2">
                        <div className="h-0.5 w-4 bg-indigo-500 rounded-full"></div>
                        <h3 className="text-xs font-black uppercase tracking-[0.2em] text-gray-400">
                          {type === 't2v' ? '1. Text-to-Video (T2V)' :
                            type === 'i2v' ? '2. Image-to-Video (I2V)' :
                              '3. Reference-to-Video (R2V)'}
                        </h3>
                      </div>
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        {filteredModels.map(m => (
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
                              <button
                                onClick={() => handleToggleModel(m.id)}
                                className={`text-[9px] font-black uppercase tracking-widest px-3 py-1 rounded-full border transition-all ${m.is_active ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' : 'bg-white/5 text-gray-600 border-white/5'}`}
                              >
                                {m.is_active ? 'Active' : 'Disabled'}
                              </button>
                              <button
                                onClick={() => handleDeleteModel(m.id)}
                                className="opacity-0 group-hover:opacity-100 p-2 hover:bg-red-500/20 text-red-400 rounded-lg transition-all"
                              >
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
                <p className="text-gray-400 max-w-xl text-lg font-light leading-relaxed">
                  Curate edge-case scenarios to stress-test <span className="text-indigo-300 font-medium">Veo</span> against <span className="text-pink-300 font-medium">Kling 3.0</span> and <span className="text-emerald-300 font-medium">Seedance 2.0</span>.
                </p>
              </div>

              <div className="flex gap-4">
                <StatBox label="Total Scenarios" value={prompts.length} />
                <StatBox label="Successful" value={prompts.filter(p => p.status === 'complete').length} />
                <StatBox label="Failed" value={prompts.filter(p => p.status === 'error').length} />
              </div>
            </div>

            {/* Premium Multi-Image Scenario Injection Card */}
            <div className="relative group mb-16">
              <div className="absolute -inset-1 bg-gradient-to-r from-indigo-500 via-purple-500 to-pink-500 rounded-[30px] blur opacity-10 group-hover:opacity-20 transition duration-1000"></div>
              <div className="relative bg-[#0d1017] border border-white/10 rounded-[28px] p-8 md:p-10 shadow-3xl">

                <div className="flex items-center gap-3 mb-8">
                  <div className="w-12 h-12 rounded-2xl bg-indigo-500/10 flex items-center justify-center border border-indigo-500/20">
                    <Zap className="w-6 h-6 text-indigo-400" />
                  </div>
                  <div>
                    <h3 className="text-xl font-semibold text-white">Inject New Scenario</h3>
                    <p className="text-sm text-gray-500">Expert-curated multi-asset benchmark</p>
                  </div>

                  {/* Mode Selector */}
                  <div className="ml-auto flex bg-white/5 p-1 rounded-xl border border-white/5">
                    {[
                      { id: 't2v', label: 'T2V' },
                      { id: 'i2v', label: 'I2V' },
                      { id: 'r2v', label: 'R2V' }
                    ].map(mode => (
                      <button
                        key={mode.id}
                        onClick={() => setInjectionMode(mode.id as any)}
                        className={`px-4 py-1.5 rounded-lg text-[10px] font-black uppercase tracking-widest transition-all ${injectionMode === mode.id ? 'bg-indigo-500 text-white shadow-lg shadow-indigo-500/20' : 'text-gray-500 hover:text-gray-300'}`}
                      >
                        {mode.label}
                      </button>
                    ))}
                  </div>
                </div>

                <div className="space-y-10">
                  <div className="grid grid-cols-1 lg:grid-cols-4 gap-8">
                    {/* Prompt Text Input */}
                    <div className="lg:col-span-2 relative">
                      <div className="text-[10px] font-black uppercase tracking-widest text-indigo-400 mb-3 ml-2 italic">Video Core Prompt</div>
                      <textarea
                        value={newPromptText}
                        onChange={(e) => setNewPromptText(e.target.value)}
                        placeholder="e.g., A panoramic tracking shot of a mountain range at golden hour, hyper-realistic fluid dynamics in the river below..."
                        className="w-full bg-[#06080b] border border-white/10 rounded-2xl p-6 text-gray-200 placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-indigo-500/30 focus:border-indigo-500/50 transition-all resize-none h-[280px] text-lg leading-relaxed shadow-inner"
                      />
                      {isGenerating && (
                        <div className="absolute inset-0 bg-[#06080b]/50 backdrop-blur-sm rounded-2xl flex items-center justify-center z-20">
                          <Loader2 className="w-8 h-8 text-indigo-400 animate-spin" />
                        </div>
                      )}
                    </div>

                    {/* Multi-Image Inputs */}
                    <div className="lg:col-span-2 space-y-6">
                      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                        {injectionMode === 'i2v' && (
                          <>
                            <ImageInputCell
                              label="Start Frame"
                              value={newPromptStartImage}
                              onChange={setNewPromptStartImage}
                              onGenerate={() => handleGenerateImage("start")}
                              onUpload={(e) => handleImageUpload(e, setNewPromptStartImage)}
                              isGenerating={isImageGenerating}
                              icon={<PlayCircle className="w-4 h-4" />}
                            />
                            <ImageInputCell
                              label="End Frame"
                              value={newPromptEndImage}
                              onChange={setNewPromptEndImage}
                              onGenerate={() => handleGenerateImage("end")}
                              onUpload={(e) => handleImageUpload(e, setNewPromptEndImage)}
                              isGenerating={isImageGenerating}
                              icon={<StopCircle className="w-4 h-4" />}
                            />
                          </>
                        )}
                        {injectionMode === 'r2v' && (
                          <>
                            {[0, 1, 2].map(idx => (
                              <ImageInputCell
                                key={idx}
                                label={`Ref Image ${idx + 1}`}
                                value={newPromptRefImages[idx]}
                                onChange={(val) => {
                                  const nr = [...newPromptRefImages];
                                  nr[idx] = val;
                                  setNewPromptRefImages(nr);
                                }}
                                onGenerate={() => handleGenerateImage(`ref_${idx}`)}
                                onUpload={(e) => handleImageUpload(e, (val) => {
                                  const nr = [...newPromptRefImages];
                                  nr[idx] = val;
                                  setNewPromptRefImages(nr);
                                })}
                                isGenerating={isImageGenerating}
                                icon={<ImageIcon className="w-4 h-4" />}
                              />
                            ))}
                          </>
                        )}
                        {injectionMode === 't2v' && (
                          <div className="col-span-3 h-full flex items-center justify-center border-2 border-dashed border-white/5 rounded-3xl p-8">
                            <div className="text-center">
                              <Sparkles className="w-8 h-8 text-indigo-400/30 mx-auto mb-2" />
                              <div className="text-gray-500 text-xs font-medium uppercase tracking-widest">Pure T2V Mode</div>
                              <div className="text-[10px] text-gray-600 mt-1">No reference images required</div>
                            </div>
                          </div>
                        )}
                      </div>

                      {injectionMode !== 't2v' && (
                        <div className="p-6 bg-white/[0.02] border border-white/5 rounded-2xl flex items-center gap-4">
                          <Info className="w-8 h-8 text-indigo-400/50 shrink-0" />
                          <p className="text-[11px] text-gray-400 leading-relaxed font-light">
                            {injectionMode === 'i2v'
                              ? "The Veo Backend will automatically prioritize multi-image inputs for I2V or frame-to-frame benchmarking."
                              : "Reference images will be used for character consistency or style-guided video generation."}
                          </p>
                        </div>
                      )}
                    </div>
                  </div>

                  <div className="flex flex-col md:flex-row items-center justify-between gap-6 pt-8 border-t border-white/5">
                    <div className="flex flex-col gap-4">
                      <div className="flex items-center justify-between px-2">
                        <div className="text-[10px] font-black uppercase tracking-widest text-gray-500 italic">Tags & Categories</div>
                        <button
                          onClick={handleSuggestTags}
                          disabled={isGeneratingTags}
                          className="text-[10px] font-bold text-indigo-400 hover:text-indigo-300 flex items-center gap-1.5 px-3 py-1 rounded-full bg-indigo-500/10 border border-indigo-500/20 transition-all disabled:opacity-50"
                        >
                          {isGeneratingTags ? <Loader2 className="w-3 h-3 animate-spin" /> : <Sparkles className="w-3 h-3" />}
                          Suggest Tags
                        </button>
                      </div>
                      <div className="flex flex-wrap gap-2 p-1.5 bg-white/[0.03] border border-white/5 rounded-2xl">
                        {CATEGORIES.map(c => (
                          <button
                            key={c}
                            onClick={() => {
                              if (newPromptCategories.includes(c)) {
                                setNewPromptCategories(newPromptCategories.filter(cat => cat !== c));
                              } else {
                                setNewPromptCategories([...newPromptCategories, c]);
                              }
                            }}
                            className={`px-5 py-2.5 rounded-xl text-xs font-bold uppercase tracking-wider transition-all ${newPromptCategories.includes(c) ? 'bg-white text-[#06080b] shadow-xl' : 'text-gray-500 hover:text-gray-300 hover:bg-white/5'}`}
                          >
                            {c}
                          </button>
                        ))}

                        <div className="flex items-center gap-2 pl-2 border-l border-white/10 ml-2">
                          <input
                            type="text"
                            value={customTag}
                            onChange={(e) => setCustomTag(e.target.value)}
                            onKeyDown={(e) => {
                              if (e.key === 'Enter' && customTag.trim()) {
                                if (!newPromptCategories.includes(customTag.trim())) {
                                  setNewPromptCategories([...newPromptCategories, customTag.trim()]);
                                }
                                setCustomTag("");
                              }
                            }}
                            placeholder="Custom..."
                            className="bg-transparent border-b border-white/10 text-xs py-1 px-1 focus:outline-none focus:border-indigo-500 w-24 placeholder:text-gray-700"
                          />
                          <button
                            onClick={() => {
                              if (customTag.trim() && !newPromptCategories.includes(customTag.trim())) {
                                setNewPromptCategories([...newPromptCategories, customTag.trim()]);
                                setCustomTag("");
                              }
                            }}
                            className="p-1 hover:bg-white/5 rounded-lg transition-all"
                          >
                            <PlusCircle className="w-4 h-4 text-gray-500" />
                          </button>
                        </div>
                      </div>

                      {newPromptCategories.filter(c => !CATEGORIES.includes(c)).length > 0 && (
                        <div className="flex flex-wrap gap-2 px-2">
                          {newPromptCategories.filter(c => !CATEGORIES.includes(c)).map(tag => (
                            <span key={tag} className="px-3 py-1 rounded-full bg-white/5 border border-white/10 text-[10px] font-bold text-gray-400 flex items-center gap-2">
                              {tag}
                              <PlusCircle className="w-3 h-3 rotate-45 cursor-pointer hover:text-red-400" onClick={() => setNewPromptCategories(newPromptCategories.filter(cat => cat !== tag))} />
                            </span>
                          ))}
                        </div>
                      )}
                    </div>

                    <button
                      onClick={handleAddPrompt}
                      disabled={!newPromptText.trim() || isGenerating}
                      className="w-full md:w-auto min-w-[260px] bg-gradient-to-r from-indigo-500 to-purple-600 hover:from-indigo-400 hover:to-purple-500 disabled:from-gray-800 disabled:to-gray-900 text-white font-bold py-4.5 px-10 rounded-2xl transition-all shadow-[0_10px_30px_rgba(99,102,241,0.2)] hover:shadow-[0_15px_40px_rgba(99,102,241,0.3)] disabled:shadow-none flex items-center justify-center gap-3 group active:scale-[0.98] text-lg"
                    >
                      {isGenerating ? (
                        <>
                          <Loader2 className="w-5 h-5 animate-spin" />
                          <span>Generating...</span>
                        </>
                      ) : (
                        <>
                          <span>Deploy Scenario</span>
                          <ArrowRight className="w-5 h-5 group-hover:translate-x-1 transition-transform" />
                        </>
                      )}
                    </button>
                  </div>
                </div>

                {showSuccess && (
                  <div className="mt-6 animate-in fade-in slide-in-from-top-2 flex items-center gap-2 text-emerald-400 bg-emerald-500/10 px-4 py-3 rounded-xl border border-emerald-500/20">
                    <CheckCircle2 className="w-5 h-5" />
                    <span className="text-sm font-medium">Scenario successfully initialized across the evaluation grid.</span>
                  </div>
                )}
              </div>
            </div>

            {/* Database Content Grid */}
            <div className="space-y-6">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between px-2 gap-4">
                <h3 className="text-2xl font-light text-white flex items-center gap-3">
                  <Database className="w-6 h-6 text-indigo-400" />
                  Active Scenarios
                </h3>

                <div className="flex items-center gap-3 bg-white/5 border border-white/10 px-4 py-2 rounded-xl">
                  <span className="text-xs font-bold uppercase tracking-widest text-gray-400">Hide Incomplete</span>
                  <button
                    onClick={() => setShowOnlyReady(!showOnlyReady)}
                    className={`w-10 h-6 rounded-full transition-colors relative flex items-center ${showOnlyReady ? 'bg-indigo-500' : 'bg-white/10'}`}
                  >
                    <div className={`w-4 h-4 bg-white rounded-full mx-1 transition-transform ${showOnlyReady ? 'translate-x-4' : 'translate-x-0'}`}></div>
                  </button>
                </div>
              </div>

              <div className="grid gap-4">
                {(showOnlyReady ? prompts.filter(p => p.status === 'complete') : prompts).map((prompt) => (
                  <PromptItem key={prompt.id} prompt={prompt} />
                ))}
              </div>
            </div>
          </div>
        )}

        {/* GUIDELINES SECTION (Omitted for brevity, kept structure same) */}
        {activeTab === 'guidelines' && (
          <div className="text-gray-500 text-center py-20 font-light">Ref rubrics loaded. Refer to the Rating Guidelines documentation.</div>
        )}

        {/* BATCH TAB */}
        {activeTab === 'batch' && (
          <div className="animate-in fade-in slide-in-from-bottom-4 duration-700 space-y-8">
            <div className="bg-[#0d1017] border border-white/10 rounded-[28px] p-8 md:p-10 shadow-3xl relative overflow-hidden">
              <div className="flex items-center gap-3 mb-8">
                <div className="w-12 h-12 rounded-2xl bg-indigo-500/10 flex items-center justify-center border border-indigo-500/20">
                  <UploadCloud className="w-6 h-6 text-indigo-400" />
                </div>
                <div>
                  <h3 className="text-xl font-semibold text-white">Batch Scenario Runner</h3>
                  <p className="text-sm text-gray-500">Upload CSV to queue multi-model matrix testing</p>
                </div>
              </div>

              {batchRows.length === 0 ? (
                <div className="border border-white/10 rounded-2xl p-8 bg-white/[0.02]">
                  <div className="flex flex-col gap-4">
                    <label className="text-sm text-gray-400 font-bold uppercase tracking-widest">Target Google Sheet</label>
                    <p className="text-xs text-gray-500 mb-2">Ensure your sheet is accessible to the backend runner credential. Must have 11 columns matching: <br /><span className="font-mono text-[10px] text-gray-400">PromptID, Mode, Text, Start, End, Ref1-3, Model, Success (J), Error (K)</span>.</p>
                    <input
                      type="text"
                      value={sheetUrl}
                      onChange={(e) => setSheetUrl(e.target.value)}
                      placeholder="https://docs.google.com/spreadsheets/d/your-sheet-id/edit"
                      className="w-full bg-[#06080b] border border-white/10 rounded-xl px-6 py-4 text-white focus:outline-none focus:border-indigo-500 font-mono text-sm"
                    />
                    <button
                      onClick={handleBatchLoadFromSheet}
                      disabled={isLoadingSheet || !sheetUrl}
                      className="self-start bg-gradient-to-r from-indigo-500 to-purple-600 hover:from-indigo-400 hover:to-purple-500 disabled:from-gray-700 disabled:to-gray-800 disabled:text-gray-500 px-8 py-4 rounded-xl text-white font-black tracking-widest text-sm transition-all shadow-lg flex items-center gap-2"
                    >
                      {isLoadingSheet ? <Loader2 className="w-5 h-5 animate-spin" /> : <LinkIcon className="w-5 h-5" />}
                      ATTACH & LOAD SHEET
                    </button>
                  </div>
                </div>
              ) : (
                <div className="space-y-6">
                  <div className="flex items-center justify-between">
                    <div className="text-sm text-gray-400">Loaded <span className="text-white font-bold">{batchRows.length}</span> rows from Sheet</div>
                    <div className="flex gap-4">
                      <button onClick={handleRunBatch} disabled={isBatchRunning} className="bg-gradient-to-r from-indigo-500 to-purple-600 px-6 py-2 rounded-xl text-white font-bold text-sm hover:scale-105 transition-transform disabled:opacity-50 flex items-center gap-2">
                        {isBatchRunning ? <Loader2 className="w-4 h-4 animate-spin" /> : <Zap className="w-4 h-4" />}
                        Run Batch
                      </button>
                      <button onClick={() => setBatchRows([])} className="bg-red-500/10 text-red-400 hover:bg-red-500/20 px-6 py-2 rounded-xl font-bold text-sm transition-colors">
                        Clear
                      </button>
                    </div>
                  </div>

                  <div className="overflow-x-auto rounded-xl border border-white/10 bg-black/20">
                    <table className="w-full text-left text-xs whitespace-nowrap">
                      <thead className="bg-[#0b0e14] text-gray-400 border-b border-white/10">
                        <tr>
                          <th className="px-4 py-3">Prompt ID</th>
                          <th className="px-4 py-3">Mode</th>
                          <th className="px-4 py-3">Text</th>
                          <th className="px-4 py-3">Model</th>
                          <th className="px-4 py-3 text-center">Success</th>
                          <th className="px-4 py-3">Error</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-white/5 text-gray-300">
                        {batchRows.map((r, i) => (
                          <tr key={i} className="hover:bg-white/[0.02] transition-colors">
                            <td className="px-4 py-3 font-mono text-purple-400">{r.promptId}</td>
                            <td className="px-4 py-3 uppercase">{r.mode}</td>
                            <td className="px-4 py-3 max-w-[200px] truncate">{r.text}</td>
                            <td className="px-4 py-3">{r.model}</td>
                            <td className="px-4 py-3 text-center">
                              {r.success ? <CheckCircle2 className="w-4 h-4 text-emerald-500 mx-auto" /> : (r.error ? <AlertCircle className="w-4 h-4 text-red-500 mx-auto" /> : <Loader2 className="w-4 h-4 text-indigo-500/50 mx-auto animate-spin" />)}
                            </td>
                            <td className="px-4 py-3 text-red-400 max-w-[150px] truncate">{r.error}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
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

function ImageInputCell({ label, value, onChange, icon, onGenerate, isGenerating, onUpload }: { label: string, value: string, onChange: (val: string) => void, icon: any, onGenerate: () => void, isGenerating: boolean, onUpload: (e: React.ChangeEvent<HTMLInputElement>) => void }) {
  const [hasError, setHasError] = useState(false);

  useEffect(() => {
    setHasError(false);
  }, [value]);

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between text-[10px] font-black uppercase tracking-widest text-gray-500 italic ml-1">
        <div className="flex items-center gap-2">
          {icon} {label}
        </div>
        <div className="flex items-center gap-2">
          <label className="text-purple-400 hover:text-purple-300 transition-colors flex items-center gap-1 cursor-pointer">
            <PlusCircle className="w-3 h-3" />
            Upload
            <input
              type="file"
              className="hidden"
              name={`upload-${label.toLowerCase()}`}
              onChange={(e) => onUpload(e)}
              accept="image/*"
            />
          </label>
        </div>
      </div>
      <div className="relative group/input">
        <input
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder="URL"
          className="block w-full bg-[#06080b] border border-white/10 rounded-xl px-4 py-3 text-xs text-gray-300 focus:outline-none focus:ring-1 focus:ring-indigo-500/50 transition-all"
        />
      </div>
      <div
        onClick={!value ? onGenerate : undefined}
        className={`aspect-square rounded-xl bg-[#06080b] border border-white/5 overflow-hidden flex items-center justify-center relative group/preview shadow-inner cursor-pointer ${!value ? 'hover:border-indigo-500/30' : ''}`}
      >
        {value ? (
          <>
            <img
              src={value}
              alt={label}
              className={`w-full h-full object-cover transition-transform group-hover/preview:scale-105 ${hasError ? 'opacity-20 grayscale' : ''}`}
              onError={() => setHasError(true)}
            />
            {hasError && (
              <div className="absolute inset-0 flex flex-col items-center justify-center bg-red-500/10 backdrop-blur-[2px]">
                <AlertCircle className="w-6 h-6 text-red-500 mb-2" />
                <span className="text-[8px] text-red-400 font-bold uppercase tracking-widest text-center px-4">
                  Failed to load<br />from GCS
                </span>
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

function PromptItem({ prompt }: { prompt: Prompt }) {
  return (
    <div className="bg-[#0d1017] border border-white/5 rounded-3xl p-6 md:p-8 hover:bg-white/[0.02] transition-all hover:border-white/10 group flex flex-col lg:flex-row items-start lg:items-center justify-between gap-6 shadow-xl active:scale-[0.99] w-full overflow-hidden">
      <div className="flex flex-col sm:flex-row items-start gap-6 flex-1 min-w-0 w-full">
        <div className="flex flex-wrap -space-x-4 shrink-0 px-2 py-1">
          {prompt.start_image_url && <ImageThumbnail url={prompt.start_image_url} label="S" onClick={() => window.dispatchEvent(new CustomEvent('expand-image', { detail: prompt.start_image_url }))} />}
          {prompt.end_image_url && <ImageThumbnail url={prompt.end_image_url} label="E" onClick={() => window.dispatchEvent(new CustomEvent('expand-image', { detail: prompt.end_image_url }))} />}
          {prompt.reference_image_url && !prompt.reference_images && <ImageThumbnail url={prompt.reference_image_url} label="R" onClick={() => window.dispatchEvent(new CustomEvent('expand-image', { detail: prompt.reference_image_url }))} />}
          {prompt.reference_images?.map((url, i) => (
            <ImageThumbnail key={i} url={url} label={`R${i + 1}`} onClick={() => window.dispatchEvent(new CustomEvent('expand-image', { detail: url }))} />
          ))}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex flex-wrap items-center gap-3 mb-3">
            {(prompt.categories || [prompt.category]).map((tag, idx) => (
              <span key={idx} className="px-3 py-1 text-[9px] font-black uppercase tracking-[0.2em] rounded-full bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
                {tag}
              </span>
            ))}
            <span className="text-[10px] text-gray-600 font-mono italic whitespace-nowrap overflow-hidden text-ellipsis max-w-[200px]" title={prompt.prompt_id || prompt.id.toString()}>
              {prompt.prompt_id ? `PID: ${prompt.prompt_id}` : `ID_${prompt.id.toString().slice(-4)}`}
            </span>
          </div>
          <p className="text-gray-200 text-lg leading-relaxed font-light line-clamp-2 break-words">"{prompt.text}"</p>
          {prompt.status === 'error' && (
            <div className="mt-4 flex items-start gap-3 text-[11px] text-red-100 bg-red-500/20 border border-red-500/30 px-4 py-3 rounded-2xl shadow-lg w-full overflow-hidden">
              <AlertCircle className="w-4 h-4 mt-0.5 shrink-0 text-red-400" />
              <div className="flex flex-col gap-1 min-w-0">
                <span className="font-black uppercase tracking-widest text-red-400 shrink-0">Generation Error</span>
                <span className="font-mono leading-tight opacity-90 break-words">{prompt.error || "Multiple model failures. check backend logs."}</span>
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="flex flex-row lg:flex-col items-center lg:items-end justify-between lg:justify-center gap-4 w-full lg:w-auto pt-4 lg:pt-0 border-t lg:border-t-0 border-white/5">
        <div className="flex -space-x-3 group-hover:gap-2 transition-all">
          {(prompt.models || []).map((model: string, i: number) => {
            const isVeo = model.toLowerCase().includes('veo');
            const isKling = model.toLowerCase().includes('kling');
            const isSeedance = model.toLowerCase().includes('seedance');

            return (
              <div
                key={i}
                title={model}
                className={`w-9 h-9 rounded-xl flex items-center justify-center text-[10px] font-black shadow-2xl border border-white/10 ${isVeo ? 'bg-[#0f1115] text-indigo-400 shadow-indigo-500/10' :
                  isKling ? 'bg-[#1a1c22] text-pink-400 shadow-pink-500/10' :
                    isSeedance ? 'bg-[#12141a] text-emerald-400 shadow-emerald-500/10' :
                      'bg-[#1a1c23] text-gray-400'
                  }`}
              >
                {model.charAt(0).toUpperCase()}
              </div>
            );
          })}
        </div>

        <div className={`flex items-center gap-2 text-[10px] font-black uppercase tracking-widest px-3 py-1.5 rounded-lg border ${prompt.status === 'complete' ? 'bg-emerald-500/10 text-emerald-500 border-emerald-500/20' :
          prompt.status === 'generating' ? 'bg-indigo-500/10 text-indigo-500 border-indigo-500/20' :
            'bg-amber-500/10 text-amber-500 border-amber-500/20'
          }`}>
          <span className={`w-1 h-1 rounded-full ${prompt.status === 'complete' ? 'bg-emerald-500 shadow-[0_0_5px_#10b981]' :
            prompt.status === 'generating' ? 'bg-indigo-500 animate-pulse' :
              'bg-amber-500'
            }`}></span>
          {prompt.status}
        </div>
      </div>
    </div>
  );
}

function ImageThumbnail({ url, label, onClick }: { url: string, label: string, onClick?: () => void }) {
  return (
    <div
      onClick={onClick}
      className={`w-16 h-16 rounded-xl overflow-hidden border-2 border-[#0d1017] shadow-2xl relative group/thumb ${onClick ? 'cursor-zoom-in' : ''}`}
    >
      <img src={url} alt={label} className="w-full h-full object-cover transition-transform group-hover/thumb:scale-125" />
      <div className="absolute top-1 right-1 bg-black/60 backdrop-blur-md px-1 rounded text-[8px] font-bold text-white leading-none py-0.5">{label}</div>
    </div>
  );
}

function StatBox({ label, value }: { label: string, value: string | number }) {
  return (
    <div className="bg-white/[0.03] border border-white/10 rounded-2xl px-6 py-4 flex flex-col items-center justify-center min-w-[120px] shadow-2xl">
      <div className="text-2xl font-bold text-white leading-none">{value}</div>
      <div className="text-[10px] font-bold text-gray-500 uppercase tracking-widest mt-2">{label}</div>
    </div>
  );
}
