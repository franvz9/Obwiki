// LLMWiki API client for Obsidian plugin

const DEFAULT_API_URL = "http://localhost:8742";

export interface KnowledgeBase {
  id: string;
  name: string;
  root_path: string;
  status: "active" | "idle" | "error";
  config: {
    llm_model: string;
    llm_endpoint: string;
  };
  created_at: string;
  updated_at: string;
}

export interface DashboardData {
  source: { total: number; raw: number; indexed: number; extracting: number; extracted: number; error: number };
  wiki: { total: number };
  crystals: { total: number };
  graph: { edges: number; clusters: number };
  jobs: { pending: number; running: number; done: number; failed: number };
  name: string;
  status: string;
}

export interface JobData {
  id: string;
  kb_id: string;
  type: string;
  status: "pending" | "running" | "done" | "failed";
  progress: number;
  token_count: number;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  log: string;
}

export interface CrystalData {
  path: string;
  title: string;
  preview: string;
}

export interface GraphData {
  edges: Array<{ source: string; target: string; type: string; reason: string }>;
  clusters: Array<{ name: string; theme: string; pages: string[]; cohesion: number }>;
  gaps: Array<{ description: string; suggested_query: string }>;
}

export interface SearchResult {
  query: string;
  hits: number;
  results: Array<{ path: string; title: string; snippet: string }>;
}

export interface TreeEntry {
  name: string;
  path: string;
  type: "directory" | "file";
  children?: TreeEntry[];
}

export class LLMWikiClient {
  private baseUrl: string;

  constructor(baseUrl: string = DEFAULT_API_URL) {
    this.baseUrl = baseUrl.replace(/\/$/, "");
  }

  setBaseUrl(url: string) {
    this.baseUrl = url.replace(/\/$/, "");
  }

  private async get<T>(path: string): Promise<T> {
    const resp = await fetch(`${this.baseUrl}${path}`);
    if (!resp.ok) {
      const body = await resp.text();
      throw new Error(`GET ${path}: ${resp.status} ${body}`);
    }
    return resp.json();
  }

  private async post<T>(path: string, body?: unknown): Promise<T> {
    const resp = await fetch(`${this.baseUrl}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : undefined,
    });
    if (!resp.ok) {
      const text = await resp.text();
      throw new Error(`POST ${path}: ${resp.status} ${text}`);
    }
    return resp.json();
  }

  private async del<T>(path: string): Promise<T> {
    const resp = await fetch(`${this.baseUrl}${path}`, { method: "DELETE" });
    if (!resp.ok) {
      const text = await resp.text();
      throw new Error(`DELETE ${path}: ${resp.status} ${text}`);
    }
    return resp.json();
  }

  // Health
  async health(): Promise<{ status: string; version: string }> {
    return this.get("/health");
  }

  async getServerConfig(): Promise<{ kb_root: string; port: number; version: string }> {
    return this.get("/v1/config");
  }

  async healthLLM(): Promise<{
    configured: boolean; reachable: boolean;
    endpoint: string; model: string; error?: string;
  }> {
    return this.get("/health/llm");
  }

  // KB management
  async listKBs(): Promise<KnowledgeBase[]> {
    return this.get("/v1/kbs");
  }

  async getActiveKB(): Promise<KnowledgeBase> {
    return this.get("/v1/kbs/active");
  }

  async createKB(name: string, rootPath: string): Promise<KnowledgeBase> {
    return this.post("/v1/kbs", { name, root_path: rootPath });
  }

  async initializeKB(kbId: string): Promise<{ created: string[]; existed: string[] }> {
    return this.post(`/v1/kbs/${kbId}/initialize`);
  }

  async activateKB(kbId: string): Promise<KnowledgeBase> {
    return this.post(`/v1/kbs/${kbId}/activate`);
  }

  async deleteKB(kbId: string): Promise<{ status: string }> {
    const resp = await fetch(`${this.baseUrl}/v1/kbs/${kbId}`, { method: "DELETE" });
    return resp.json();
  }

  // Dashboard
  async getDashboard(kbId: string): Promise<DashboardData> {
    return this.get(`/v1/kbs/${kbId}/dashboard`);
  }

  // Search
  async search(kbId: string, query: string, limit = 20): Promise<SearchResult> {
    return this.post(`/v1/kbs/${kbId}/search`, { query, limit });
  }

  // Tree
  async getTree(kbId: string): Promise<TreeEntry> {
    return this.get(`/v1/kbs/${kbId}/tree`);
  }

  // Crystals
  async getCrystals(kbId: string): Promise<CrystalData[]> {
    return this.get(`/v1/kbs/${kbId}/crystals`);
  }

  // Graph
  async getGraph(kbId: string): Promise<GraphData> {
    return this.get(`/v1/kbs/${kbId}/graph`);
  }

  // Read file
  async readFile(kbId: string, path: string): Promise<{ path: string; content: string; size: number }> {
    return this.get(`/v1/files/${kbId}/${encodeURIComponent(path)}`);
  }

  // Write file
  async writeFile(kbId: string, path: string, content: string, frontmatter: Record<string, unknown> = {}): Promise<{ path: string; written: number; status: string }> {
    return this.post(`/v1/kbs/${kbId}/write`, { path, content, frontmatter });
  }

  // Jobs
  async listJobs(kbId: string): Promise<JobData[]> {
    return this.get(`/v1/kbs/${kbId}/jobs`);
  }

  async getJob(jobId: string): Promise<JobData> {
    return this.get(`/v1/jobs/${jobId}`);
  }

  async createJob(kbId: string, type: string): Promise<JobData> {
    return this.post(`/v1/kbs/${kbId}/jobs/${type}`);
  }

  async createJobWithPayload(kbId: string, type: string, payload: Record<string, unknown>): Promise<JobData> {
    return this.post(`/v1/kbs/${kbId}/jobs/${type}`, payload);
  }

  // Sources
  async listSources(kbId: string, status: string = ""): Promise<any[]> {
    const q = status ? `?status=${status}` : "";
    return this.get(`/v1/kbs/${kbId}/sources${q}`);
  }

  // Events
  async getEvents(kbId: string): Promise<JobData[]> {
    return this.get(`/v1/kbs/${kbId}/events`);
  }

  // Import
  async importFolder(kbId: string, sourcePath: string): Promise<{ imported: number }> {
    return this.post(`/v1/kbs/${kbId}/import/folder-json`, { source_path: sourcePath });
  }

  async importFileContent(kbId: string, name: string, content: string, encoding: "text" | "base64" = "text"): Promise<{ imported: string; size: number }> {
    return this.post(`/v1/kbs/${kbId}/import/file-content`, { name, content, encoding });
  }

  async importUpload(kbId: string, fileName: string, fileData: ArrayBuffer): Promise<{ imported: string; size: number }> {
    const sizeMB = (fileData.byteLength / 1024 / 1024).toFixed(1);
    if (fileData.byteLength > 200 * 1024 * 1024) {
      throw new Error(`文件过大 (${sizeMB}MB)，超过 200MB 限制。请手动复制到 01_raw 目录`);
    }
    const formData = new FormData();
    formData.append("file", new Blob([fileData]), fileName);
    const resp = await fetch(`${this.baseUrl}/v1/kbs/${kbId}/import/upload`, { method: "POST", body: formData });
    if (!resp.ok) {
      const text = await resp.text();
      throw new Error(`上传失败 (HTTP ${resp.status}): ${text.slice(0, 200)}`);
    }
    return resp.json();
  }

  // ── Providers ──
  async getProviders(): Promise<any[]> {
    return this.get("/v1/providers");
  }

  async saveProvider(data: { id?: string; name: string; provider: string; endpoint: string; api_key: string; models: any[] }): Promise<any> {
    return this.post("/v1/providers", data);
  }

  async deleteProvider(id: string): Promise<any> {
    const resp = await fetch(`${this.baseUrl}/v1/providers/${id}`, { method: "DELETE" });
    return resp.json();
  }

  async setDefaultProvider(id: string, kind: "text" | "vision"): Promise<any> {
    return this.post(`/v1/providers/${id}/default/${kind}`);
  }

  async clearDefaultVision(): Promise<any> {
    // Clear all vision defaults
    const providers = await this.getProviders();
    for (const p of providers) {
      if (p.is_default_vision) {
        await this.post(`/v1/providers/${p.id}/default/clear`);
      }
    }
    return { status: "cleared" };
  }

  async detectModels(endpoint: string, apiKey: string, provider: string): Promise<{ models: { id: string; owned_by: string }[]; count: number; error?: string }> {
    return this.post("/v1/providers/detect", { endpoint, api_key: apiKey, provider });
  }

  // ── Token Quota (global) ──
  async getTokenUsage(kbId: string): Promise<{ used: number; quota: number; date: string }> {
    return this.get(`/v1/kbs/${kbId}/token-usage`);
  }

  async setTokenQuota(kbId: string, quotaM: number): Promise<{ quota_m: number }> {
    return this.post(`/v1/kbs/${kbId}/token-quota?quota=${quotaM}`);
  }

  // ── Review Items ──
  async getReviewItems(kbId: string): Promise<{ items: any[]; total: number }> {
    return this.get(`/v1/kbs/${kbId}/review-items`);
  }

  async detectDuplicates(kbId: string): Promise<{ auto_merged: number; review_items: number; skipped: number }> {
    return this.post(`/v1/kbs/${kbId}/review-items/detect`);
  }

  async resolveReview(kbId: string, itemId: string, action: string): Promise<any> {
    return this.post(`/v1/kbs/${kbId}/review-items/${encodeURIComponent(itemId)}/resolve?action=${action}`);
  }

  // ── Document Queue ──
  async getDocuments(kbId: string, status?: string): Promise<any[]> {
    const q = status ? `?status=${status}` : "";
    return this.get(`/v1/kbs/${kbId}/documents${q}`);
  }

  async cancelDocument(kbId: string, path: string): Promise<any> {
    return this.post(`/v1/kbs/${kbId}/documents/cancel?path=${encodeURIComponent(path)}`);
  }

  async retryDocument(kbId: string, path: string): Promise<any> {
    return this.post(`/v1/kbs/${kbId}/documents/retry?path=${encodeURIComponent(path)}`);
  }

  async deleteDocument(kbId: string, path: string): Promise<any> {
    return this.del(`/v1/kbs/${kbId}/documents?path=${encodeURIComponent(path)}`);
  }

  // ── Job History ──
  async getJobHistory(kbId: string, date?: string): Promise<any[]> {
    const q = date ? `?date=${date}` : "";
    return this.get(`/v1/kbs/${kbId}/job-history${q}`);
  }
}
