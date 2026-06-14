import { ItemView, WorkspaceLeaf, Notice, TFile, TFolder, Modal, FileSystemAdapter } from "obsidian";
import type LLMWikiPlugin from "../main";
import type { DashboardData, JobData } from "../api-client";
import { ModelPickerModal, type ModelEntry } from "./model-picker-modal";

export const LLMWIKI_VIEW_TYPE = "obwiki-view";

type TabId = "dashboard" | "import" | "kb" | "settings" | "automation";

const TABS: { id: TabId; label: string }[] = [
  { id: "dashboard", label: "Dashboard" },
  { id: "import", label: "操作" },
  { id: "kb", label: "知识库" },
  { id: "automation", label: "自动化" },
  { id: "settings", label: "设置" },
];

const BINARY_EXTS = new Set(["pdf", "docx", "pptx", "xlsx", "xls", "odt", "ods", "doc", "ppt"]);

interface ProviderInfo { id: string; name: string; provider: string; endpoint: string; api_key: string; models: ModelEntry[]; is_default_text: boolean; is_default_vision: boolean; }

export class LLMWikiView extends ItemView {
  plugin: LLMWikiPlugin;
  private activeTab: TabId = "dashboard";

  constructor(leaf: WorkspaceLeaf, plugin: LLMWikiPlugin) {
    super(leaf);
    this.plugin = plugin;
  }
  getViewType(): string { return LLMWIKI_VIEW_TYPE; }
  getDisplayText(): string { return "LLMWiki"; }
  getIcon(): string { return "obwiki"; }

  async onOpen(): Promise<void> { this.contentEl.addClass("llmwiki-view"); await this.render(); }

  get client() { return this.plugin.client; }

  // ═══════════════════════════════════════════════════════════════
  // RENDER
  // ═══════════════════════════════════════════════════════════════

  async render(): Promise<void> {
    this.contentEl.empty();
    const tabBar = this.contentEl.createDiv({ cls: "llmwiki-tab-bar" });
    for (const t of TABS) {
      tabBar.createEl("button", {
        text: t.label, cls: `llmwiki-tab ${t.id === this.activeTab ? "llmwiki-tab-active" : ""}`,
      }).onclick = () => { this.activeTab = t.id; this.render(); };
    }
    const body = this.contentEl.createDiv({ cls: "llmwiki-tab-body" });
    switch (this.activeTab) {
      case "dashboard": await this.renderDashboard(body); break;
      case "import": await this.renderImport(body); break;
      case "kb": await this.renderKB(body); break;
      case "settings": await this.renderSettings(body); break;
      case "automation": await this.renderAutomation(body); break;
    }
  }

  // ═══════════════════════════════════════════════════════════════
  // DASHBOARD
  // ═══════════════════════════════════════════════════════════════

  async renderDashboard(body: HTMLElement): Promise<void> {
    let dash: DashboardData; let jobs: JobData[] = []; let kbId = ""; let docs: any[] = [];
    try {
      const kb = await this.client.getActiveKB();
      kbId = kb.id;
      const [d, j, a] = await Promise.all([
        this.client.getDashboard(kbId),
        this.client.listJobs(kbId),
        this.client.getDocuments(kbId, "active"),
      ]);
      dash = d; jobs = j; docs = a;
    } catch (e: any) {
      if (e?.message?.includes("404")) {
        body.createEl("div", { text: "暂无激活的知识库，请先到「知识库」tab 创建", cls: "llmwiki-muted" });
      } else {
        body.createEl("div", { text: "API 未连接", cls: "llmwiki-error" });
      }
      return;
    }

    const processing = docs.filter(d => d.status === "extracting" || d.status === "dedup_check" || d.status === "organizing");
    const queued = docs.filter(d => d.status === "raw" || d.status === "indexed");

    // ── Cards ──
    const cardRow = body.createDiv({ cls: "llmwiki-card-row" });
    this.card(cardRow, "文档待处理", `${queued.length}`, "");
    this.card(cardRow, "文档处理中", `${processing.length}`, `${dash.source.extracted ?? 0} 已完成`);
    this.card(cardRow, "Wiki", `${dash.wiki.total}`, "");
    this.card(cardRow, "全局任务", `${jobs.filter(j => j.status === "running").length}`, `${dash.graph.clusters} 社区`);
    ((async () => {
      try { const u = await this.client.getTokenUsage(kbId); this.card(cardRow, "今日Token", `${(u.used/1000).toFixed(0)}K`, u.quota > 0 ? `/ ${(u.quota/1000).toFixed(0)}K` : "无限制"); } catch {}
    })());
    this.card(cardRow, "图谱关系", `${dash.graph.edges}`, `${dash.crystals.total} 结晶`);

    // ── Document queue ──
    const qSection = body.createDiv({ cls: "llmwiki-section" });
    const qHeader = qSection.createDiv({ cls: "llmwiki-inline-row" });
    qHeader.createEl("h4", { text: "文档处理队列" });
    qHeader.createEl("span", { text: "" }); // spacer
    const popupBtn = qHeader.createEl("button", { text: "打开队列", cls: "llmwiki-btn-sm" });
    popupBtn.style.marginLeft = "auto";
    popupBtn.onclick = () => this.showDocQueueModal(kbId);

    const activeDocs = [...processing, ...queued].slice(0, 4);
    if (activeDocs.length === 0) {
      qSection.createEl("div", { text: "队列为空", cls: "llmwiki-muted" });
    } else {
      const qTable = qSection.createEl("table", { cls: "llmwiki-table llmwiki-job-table" });
      qTable.createEl("colgroup").innerHTML = `<col><col style="width:60px"><col style="width:80px"><col style="width:60px"><col style="width:72px">`;
      const thead = qTable.createEl("thead").createEl("tr");
      ["文档名", "状态", "当前阶段", "Token", "操作"].forEach(h => thead.createEl("th", { text: h }));
      const qBody = qTable.createEl("tbody");
      for (const d of activeDocs) {
        const row = qBody.createEl("tr");
        row.createEl("td", { text: d.file_name || d.path?.split("/").pop() || "-", cls: "llmwiki-mono" });
        row.createEl("td", { text: statusLabel(d.status), cls: d.status === "error" ? "llmwiki-err" : d.status === "cancelled" ? "llmwiki-muted" : "" });
        row.createEl("td", { text: phaseLabel(d.status), cls: "llmwiki-muted" });
        row.createEl("td", { text: d.token_count > 0 ? `${(d.token_count/1000).toFixed(1)}K` : "-", cls: "llmwiki-mono" });
        const act = row.createEl("td");
        if (d.status === "raw" || d.status === "indexed") {
          act.createEl("button", { text: "取消", cls: "llmwiki-btn-sm" }).onclick = async () => {
            await this.client.cancelDocument(kbId, d.path); this.render();
          };
        }
        if (d.status === "error") {
          act.createEl("button", { text: "重试", cls: "llmwiki-btn-sm" }).onclick = async () => {
            await this.client.retryDocument(kbId, d.path); this.render();
          };
          act.createEl("button", { text: "删除", cls: "llmwiki-btn-sm" }).onclick = async () => {
            await this.client.deleteDocument(kbId, d.path); this.render();
          };
        }
        if (d.status === "cancelled") {
          act.createEl("button", { text: "删除", cls: "llmwiki-btn-sm" }).onclick = async () => {
            await this.client.deleteDocument(kbId, d.path); this.render();
          };
        }
      }
    }

    // ── Global job history ──
    const jSection = body.createDiv({ cls: "llmwiki-section" });
    jSection.createEl("h4", { text: "全局任务" });
    // Sort: running/pending first, then by created_at desc
    const sortedJobs = [...jobs].sort((a, b) => {
      if (a.status === "running" && b.status !== "running") return -1;
      if (b.status === "running" && a.status !== "running") return 1;
      if (a.status === "pending" && b.status !== "pending" && b.status !== "running") return -1;
      if (b.status === "pending" && a.status !== "pending" && a.status !== "running") return 1;
      return (b.created_at || "").localeCompare(a.created_at || "");
    });
    if (sortedJobs.length === 0) {
      jSection.createEl("div", { text: "暂无任务", cls: "llmwiki-muted" });
    } else {
      const jScroll = jSection.createDiv({ cls: "llmwiki-scroll-box" });
      jScroll.style.maxHeight = "240px";
      jScroll.style.overflowY = "auto";
      const jTable = jScroll.createEl("table", { cls: "llmwiki-table llmwiki-job-table" });
      jTable.createEl("colgroup").innerHTML = `<col style="width:70px"><col style="width:80px"><col style="width:50px"><col style="width:60px"><col style="width:52px">`;
      const thead = jTable.createEl("thead").createEl("tr");
      ["知识库", "任务", "状态", "时间", "Token"].forEach(h => thead.createEl("th", { text: h }));
      const jBody = jTable.createEl("tbody");
      for (const j of sortedJobs) {
        const row = jBody.createEl("tr");
        row.createEl("td", { text: dash.name || "—", cls: "llmwiki-mono llmwiki-muted" });
        row.createEl("td", { text: jobLabel(j.type) });
        row.createEl("td", { text: j.status === "done" ? "完成" : j.status === "running" ? "运行中" : j.status === "failed" ? "失败" : j.status, cls: j.status === "done" ? "llmwiki-ok" : j.status === "failed" ? "llmwiki-err" : "" });
        row.createEl("td", { text: j.created_at?.slice(11, 19) || "-", cls: "llmwiki-mono" });
        row.createEl("td", { text: j.token_count > 0 ? `${(j.token_count/1000).toFixed(0)}K` : "-", cls: "llmwiki-mono" });
      }
    }

    // 5s auto-refresh
    if ((this as any)._dashTimer) clearInterval((this as any)._dashTimer);
    (this as any)._dashTimer = setInterval(() => { if (this.activeTab === "dashboard") this.render(); }, 5000);
  }

  private card(parent: HTMLElement, label: string, value: string, detail: string): void {
    const c = parent.createDiv({ cls: "llmwiki-card" });
    c.createEl("div", { text: value, cls: "llmwiki-card-value" });
    c.createEl("div", { text: label, cls: "llmwiki-card-label" });
    if (detail) c.createEl("div", { text: detail, cls: "llmwiki-card-detail" });
  }

  // ═══════════════════════════════════════════════════════════════
  // IMPORT
  // ═══════════════════════════════════════════════════════════════

  async renderImport(body: HTMLElement): Promise<void> {
    body.createEl("h4", { text: "导入文件" });
    const pickerRow = body.createDiv({ cls: "llmwiki-inline-row" });
    const fileInput = pickerRow.createEl("input", { type: "file", attr: { multiple: "true", accept: ".md,.txt,.pdf,.docx,.pptx,.xlsx,.xls,.html,.csv,.json,.yaml,.xml,.odt,.ods" }, cls: "llmwiki-select-inline" });
    fileInput.style.flex = "1";
    pickerRow.createEl("button", { text: "导入选中文件" }).onclick = () => this.doImportFiles(fileInput);

    body.createEl("h4", { text: "从 Vault 导入" });
    const vaultRow = body.createDiv({ cls: "llmwiki-inline-row" });
    const noteSelect = vaultRow.createEl("select", { cls: "llmwiki-select-inline" });
    const refreshFileSelect = () => {
      noteSelect.empty();
      noteSelect.createEl("option", { text: "-- 选择文件 --", value: "" });
      for (const f of this.app.vault.getFiles().slice(0, 300)) {
        noteSelect.createEl("option", { text: f.path, value: f.path });
      }
    };
    refreshFileSelect();
    noteSelect.onfocus = refreshFileSelect;
    vaultRow.createEl("button", { text: "导入" }).onclick = () => this.doImportVaultFile(noteSelect.value);

    const vaultFdRow = body.createDiv({ cls: "llmwiki-inline-row" });
    const folderSelect = vaultFdRow.createEl("select", { cls: "llmwiki-select-inline" });
    const refreshFolderSelect = () => {
      folderSelect.empty();
      folderSelect.createEl("option", { text: "-- 选择文件夹 --", value: "" });
      for (const f of this.app.vault.getAllFolders().slice(0, 100)) {
        folderSelect.createEl("option", { text: f.path, value: f.path });
      }
    };
    refreshFolderSelect();
    folderSelect.onfocus = refreshFolderSelect;
    vaultFdRow.createEl("button", { text: "导入" }).onclick = () => this.doImportVaultFolder(folderSelect.value);

    const dropZone = body.createDiv({ cls: "llmwiki-drop-zone" });
    dropZone.createEl("p", { text: "或拖放文件到此处", cls: "llmwiki-muted" });
    dropZone.addEventListener("dragover", e => { e.preventDefault(); dropZone.addClass("llmwiki-drop-active"); });
    dropZone.addEventListener("dragleave", () => dropZone.removeClass("llmwiki-drop-active"));
    dropZone.addEventListener("drop", e => { e.preventDefault(); dropZone.removeClass("llmwiki-drop-active"); this.doDrop(e.dataTransfer); });

    body.createEl("h4", { text: "知识库操作" });
    const kbOpRow = body.createDiv({ cls: "llmwiki-btn-row" });
    kbOpRow.createEl("button", { text: "文档处理", cls: "mod-cta" }).onclick = () => this.doPipelineJob("process", "文档处理");
    for (const { type, label } of [
      { type: "evolve", label: "知识演进" },
      { type: "crystallize", label: "生成结晶" },
      { type: "communities", label: "检测社区" },
    ]) { kbOpRow.createEl("button", { text: label }).onclick = () => this.doPipelineJob(type, label); }

    body.createEl("h4", { text: "质量检查" });
    const lintRow = body.createDiv({ cls: "llmwiki-btn-row" });
    lintRow.createEl("button", { text: "检查" }).onclick = () => this.doPipelineJob("lint", "健康检查");
    lintRow.createEl("button", { text: "自动修复" }).onclick = async () => {
      try {
        const kb = await this.client.getActiveKB();
        await this.client.post(`/v1/kbs/${kb.id}/jobs/lint?auto_fix=true`, {});
        new Notice("自动修复已提交");
        this.render();
      } catch (e) { new Notice(`失败: ${e}`); }
    };

    // ── Review section ──
    this.renderReviewSection(body);
  }

  private async renderReviewSection(parent: HTMLElement): Promise<void> {
    const section = parent.createDiv({ cls: "llmwiki-section" });
    section.createEl("h4", { text: "查重与审核" });

    // Detect button always visible
    const detectRow = section.createDiv({ cls: "llmwiki-inline-row" });
    detectRow.createEl("span", { text: "扫描结晶和社区的重复项", cls: "llmwiki-muted" });
    const detectBtn = detectRow.createEl("button", { text: "检测重复", cls: "llmwiki-btn-sm" });
    detectBtn.onclick = async () => {
      detectBtn.setText("检测中...");
      detectBtn.disabled = true;
      try {
        const kb = await this.client.getActiveKB();
        const r = await this.client.detectDuplicates(kb.id);
        new Notice(`检测完成: 自动合并 ${r.auto_merged} 项，待审核 ${r.review_items} 项`);
        this.render();
      } catch (e: any) {
        new Notice(`检测失败: ${e.message}`);
      } finally {
        detectBtn.setText("检测重复");
        detectBtn.disabled = false;
      }
    };

    // Load review items
    try {
      const kb = await this.client.getActiveKB();
      const review = await this.client.getReviewItems(kb.id);
      if (review.items.length === 0) return;

      const crystals = review.items.filter((i: any) => i.type === "crystal_merge");
      const communities = review.items.filter((i: any) => i.type === "community_merge");

      if (crystals.length > 0) {
        const row = section.createDiv({ cls: "llmwiki-inline-row" });
        row.createEl("span", { text: `待合并结晶: ${crystals.length} 组`, cls: "llmwiki-muted" });
        row.createEl("button", { text: "审核 →", cls: "llmwiki-btn-sm" }).onclick = () => this.showMergeModal(review.items);
      }
      if (communities.length > 0) {
        const row = section.createDiv({ cls: "llmwiki-inline-row" });
        row.createEl("span", { text: `待合并社区: ${communities.length} 组`, cls: "llmwiki-muted" });
        if (crystals.length === 0) {
          row.createEl("button", { text: "审核 →", cls: "llmwiki-btn-sm" }).onclick = () => this.showMergeModal(review.items);
        }
      }
    } catch {}
  }

  private async showDocQueueModal(kbId: string): Promise<void> {
    const modal = new Modal(this.app);
    modal.titleEl.setText("文档处理队列");

    const renderContent = async () => {
      const content = modal.contentEl;
      content.empty();
      try {
        const docs = await this.client.getDocuments(kbId, "active");
        if (docs.length === 0) {
          content.createEl("div", { text: "队列为空", cls: "llmwiki-muted" });
          return;
        }
        const table = content.createEl("table", { cls: "llmwiki-table llmwiki-job-table" });
        table.createEl("colgroup").innerHTML = `<col><col style="width:60px"><col style="width:80px"><col style="width:60px"><col style="width:90px">`;
        const thead = table.createEl("thead").createEl("tr");
        ["文档名", "状态", "当前阶段", "Token", "操作"].forEach(h => thead.createEl("th", { text: h }));
        const tbody = table.createEl("tbody");
        for (const d of docs) {
          const row = tbody.createEl("tr");
          row.createEl("td", { text: d.file_name || d.path?.split("/").pop() || "-", cls: "llmwiki-mono" });
          row.createEl("td", { text: statusLabel(d.status), cls: d.status === "error" ? "llmwiki-err" : d.status === "cancelled" ? "llmwiki-muted" : "" });
          row.createEl("td", { text: phaseLabel(d.status), cls: "llmwiki-muted" });
          row.createEl("td", { text: d.token_count > 0 ? `${(d.token_count/1000).toFixed(1)}K` : "-", cls: "llmwiki-mono" });
          const act = row.createEl("td");
          if (d.status === "raw" || d.status === "indexed") {
            act.createEl("button", { text: "取消", cls: "llmwiki-btn-sm" }).onclick = async () => {
              await this.client.cancelDocument(kbId, d.path); renderContent(); this.render();
            };
          }
          if (d.status === "error") {
            act.createEl("button", { text: "重试", cls: "llmwiki-btn-sm" }).onclick = async () => {
              await this.client.retryDocument(kbId, d.path); renderContent(); this.render();
            };
            act.createEl("button", { text: "删除", cls: "llmwiki-btn-sm" }).onclick = async () => {
              await this.client.deleteDocument(kbId, d.path); renderContent(); this.render();
            };
          }
          if (d.status === "cancelled") {
            act.createEl("button", { text: "删除", cls: "llmwiki-btn-sm" }).onclick = async () => {
              await this.client.deleteDocument(kbId, d.path); renderContent(); this.render();
            };
          }
        }
      } catch (e: any) {
        content.createEl("div", { text: `加载失败: ${e.message}`, cls: "llmwiki-err" });
      }
    };

    await renderContent();
    const timer = setInterval(renderContent, 3000);
    modal.onClose = () => clearInterval(timer);
    modal.open();
  }

  private async showMergeModal(items: any[]): Promise<void> {
    const kb = await this.client.getActiveKB();
    (this as any)._activeKB = kb.id;
    const resolved = new Set<string>();

    const m = new Modal(this.app);
    m.titleEl.setText("审核合并");
    const content = m.contentEl;

    // Refresh all items function
    const renderItems = () => {
      content.empty();
      let remaining = 0;
      for (let idx = 0; idx < items.length; idx++) {
        const item = items[idx];
        const done = resolved.has(item.id);
        if (done && items.every((i: any) => resolved.has(i.id))) {
          // All done, show close hint
          content.createEl("p", { text: "全部已处理", cls: "llmwiki-ok" });
          return;
        }
        if (!done) remaining++;

        const section = content.createDiv({ cls: done ? "llmwiki-section" : "" });
        if (done) section.style.opacity = "0.4";

        const isCrystal = item.type === "crystal_merge";
        section.createEl("h4", { text: `第 ${idx + 1}/${items.length} 组 (${isCrystal ? "结晶" : "社区"})${done ? " ✓" : ""}` });

        const cardRow = section.createDiv({ cls: "llmwiki-card-row" });
        this.card(cardRow, item.item_a.title, item.item_a.path.split("/").pop() || "", "");
        this.card(cardRow, item.item_b.title, item.item_b.path.split("/").pop() || "", "");

        section.createEl("div", {
          text: `重叠度: ${(item.overlap * 100).toFixed(0)}%${item.overlap >= 0.8 ? " (建议合并)" : " (待审核)"}`,
          cls: item.overlap >= 0.8 ? "llmwiki-ok" : "llmwiki-muted",
        });

        if (!done) {
          const btnRow = section.createDiv({ cls: "llmwiki-btn-row" });
          btnRow.createEl("button", { text: "保留两者" }).onclick = async () => {
            await this.client.resolveReview(kb.id, item.id, "keep_both");
            resolved.add(item.id); renderItems();
          };
          btnRow.createEl("button", { text: `用 ${item.item_a.title.slice(0, 12)}` }).onclick = async () => {
            await this.client.resolveReview(kb.id, item.id, "use_a");
            resolved.add(item.id); renderItems();
          };
          btnRow.createEl("button", { text: `用 ${item.item_b.title.slice(0, 12)}` }).onclick = async () => {
            await this.client.resolveReview(kb.id, item.id, "use_b");
            resolved.add(item.id); renderItems();
          };
        }
        section.createEl("hr");
      }
      if (remaining === 0 && items.length > 0) {
        content.createEl("p", { text: "全部已处理，可关闭窗口", cls: "llmwiki-ok" });
      }
    };

    renderItems();
    m.open();
    // Refresh main view when modal closes
    m.onClose = () => { this.render(); };
  }

  private async doImportFiles(input: HTMLInputElement): Promise<void> {
    const files = input.files; if (!files || files.length === 0) { new Notice("请先选择文件"); return; }
    try {
      const kb = await this.client.getActiveKB(); let count = 0, skipped = 0;
      for (let i = 0; i < files.length; i++) {
        const f = files[i];
        // Warn for large files (>50MB)
        if (f.size > 50 * 1024 * 1024) { new Notice(`${f.name}: 文件过大(${(f.size/1024/1024).toFixed(0)}MB)，请手动复制到 01_raw 目录`, 8000); continue; }
        if (await this.isDup(kb.id, f.name)) { skipped++; continue; }
        if (isBinary(f.name)) { await this.client.importUpload(kb.id, f.name, await f.arrayBuffer()); }
        else { await this.client.importFileContent(kb.id, f.name, await f.text(), "text"); }
        count++;
      }
      input.value = ""; new Notice(skipped > 0 ? `导入 ${count} 个，跳过 ${skipped} 个` : `导入 ${count} 个文件`);
      this.triggerPipeline(kb.id);
    } catch (e) { new Notice(`导入失败: ${e}`); }
  }

  private async doImportVaultFile(path: string): Promise<void> {
    if (!path) { new Notice("请选择文件"); return; }
    try {
      const file = this.app.vault.getFileByPath(path); if (!file) return;
      const kb = await this.client.getActiveKB();
      if (await this.isDup(kb.id, file.name)) { new Notice("文件已存在"); return; }
      if (isBinary(file.name)) { await this.client.importUpload(kb.id, file.name, await this.app.vault.readBinary(file)); }
      else { await this.client.importFileContent(kb.id, file.name, (await this.app.vault.cachedRead(file)) || "", "text"); }
      new Notice(`已导入: ${file.name}`); this.triggerPipeline(kb.id);
    } catch (e) { new Notice(`失败: ${e}`); }
  }

  private async doImportVaultFolder(path: string): Promise<void> {
    if (!path) { new Notice("请选择文件夹"); return; }
    try {
      const folder = this.app.vault.getFolderByPath(path); if (!folder) return;
      const kb = await this.client.getActiveKB(); let count = 0, skipped = 0;
      const walk = async (f: TFolder): Promise<void> => {
        for (const child of f.children) {
          if (child instanceof TFile) {
            const rel = child.path.slice(path.length + 1);
            if (await this.isDup(kb.id, rel)) { skipped++; continue; }
            if (isBinary(child.name)) { await this.client.importUpload(kb.id, rel, await this.app.vault.readBinary(child)); }
            else { await this.client.importFileContent(kb.id, rel, (await this.app.vault.cachedRead(child)) || "", "text"); }
            count++;
          } else if (child instanceof TFolder) { await walk(child); }
        }
      };
      await walk(folder); new Notice(`导入 ${count} 个${skipped>0?`，跳过 ${skipped} 个`:""}`);
      this.triggerPipeline(kb.id);
    } catch (e) { new Notice(`失败: ${e}`); }
  }

  private async doDrop(dt: DataTransfer | null): Promise<void> {
    const items = dt?.items; if (!items) return;
    try {
      const kb = await this.client.getActiveKB(); let count = 0;
      for (let i = 0; i < items.length; i++) {
        const entry = (items[i] as any).webkitGetAsEntry?.(); if (!entry || !entry.isFile) continue;
        const file: File = await new Promise(r => entry.file(r));
        if (await this.isDup(kb.id, file.name)) continue;
        if (isBinary(file.name)) { await this.client.importUpload(kb.id, file.name, await file.arrayBuffer()); }
        else { await this.client.importFileContent(kb.id, file.name, await file.text(), "text"); }
        count++;
      }
      new Notice(`导入 ${count} 个文件`); this.triggerPipeline(kb.id); this.render();
    } catch (e) { new Notice(`失败: ${e}`); }
  }

  private async isDup(kbId: string, name: string): Promise<boolean> {
    // Only skip files that are successfully extracted — allow re-import for raw/indexed/error
    try {
      const s = await this.client.listSources(kbId, "");
      return s.some((x: any) => x.file_name === name && x.status === "extracted");
    } catch { return false; }
  }

  private async doPipelineJob(type: string, label: string): Promise<void> {
    try {
      const kb = await this.client.getActiveKB();
      const job = await this.client.createJob(kb.id, type);
      new Notice(`${label}: 已提交`);
      // Quick poll for fast-fail (e.g. LLM not configured)
      const llmJobs = ["extract","evolve","crystallize","repair","process","communities_run","lint"];
      if (llmJobs.includes(type)) {
        for (let i = 0; i < 5; i++) {
          await sleep(1000);
          try {
            const j = await this.client.getJob(job.id);
            if (j.status === "failed") {
              const msg = (j.log || "").includes("LLM_NOT_CONFIGURED")
                ? "请先配置模型供应商" : (j.log || "未知错误").slice(0, 80);
              new Notice(`${label} 失败: ${msg}`);
              break;
            }
            if (j.status === "done") {
              new Notice(`${label}: 完成`);
              break;
            }
          } catch {}
        }
      }
      this.activeTab = "dashboard"; this.render();
    } catch (e: any) { new Notice(`${label} 失败: ${e.message || e}`); }
  }

  private async triggerPipeline(kbId: string): Promise<void> {
    try {
      const job = await this.client.createJob(kbId, "process");
      new Notice("文档处理已提交，在后台执行");
    } catch (e) { new Notice(`提交失败: ${e}`); }
  }

  // ═══════════════════════════════════════════════════════════════
  // KB
  // ═══════════════════════════════════════════════════════════════

  async renderKB(body: HTMLElement): Promise<void> {
    try { const h = await this.client.health(); body.createEl("div", { text: `API: ${h.status} v${h.version}`, cls: "llmwiki-ok" }); } catch { body.createEl("div", { text: "API 未连接", cls: "llmwiki-err" }); return; }
    const allKBs = await this.client.listKBs();
    // Only show KBs belonging to current vault
    const serverRoot = (this.plugin as any)._serverKbRoot || "";
    const adapter = this.app.vault.adapter;
    const vaultPath = adapter instanceof FileSystemAdapter ? adapter.getBasePath() : "";
    const kbs = allKBs.filter((kb: any) => {
      if (serverRoot && kb.root_path.startsWith(serverRoot)) return true;
      if (vaultPath && kb.root_path.startsWith(vaultPath)) return true;
      return false;
    });
    body.createEl("h4", { text: `知识库 (${kbs.length}${kbs.length !== allKBs.length ? ` / 共${allKBs.length}个` : ""})` });
    const table = body.createEl("table", { cls: "llmwiki-table llmwiki-kb-table" });
    table.createEl("colgroup").innerHTML = `<col style="width:100px"><col style="width:60px"><col><col style="width:100px">`;
    const thead = table.createEl("thead").createEl("tr"); ["名称","状态","路径","操作"].forEach(h=>thead.createEl("th",{text:h}));
    for (const kb of kbs) {
      const row = table.createEl("tbody").createEl("tr");
      row.createEl("td",{text:kb.name}); row.createEl("td",{text:kb.status==="active"?"当前":kb.status,cls:kb.status==="active"?"llmwiki-ok":""});
      const serverRoot = (this.plugin as any)._serverKbRoot || "";
const displayPath = serverRoot && kb.root_path.startsWith(serverRoot)
  ? (vaultPath + kb.root_path.slice(serverRoot.length)) : kb.root_path;
row.createEl("td",{text: displayPath, cls:"llmwiki-mono llmwiki-path-cell"});
      const act=row.createEl("td");
      if(kb.status!=="active") act.createEl("button",{text:"激活",cls:"llmwiki-btn-sm"}).onclick=async()=>{await this.client.activateKB(kb.id);this.render();};
      act.createEl("button",{text:"删除",cls:"llmwiki-btn-sm llmwiki-btn-danger"}).onclick=async()=>{if(confirm(`确定从列表中删除 "${kb.name}"？\n\n注意：此操作仅从注册表中移除，不会删除磁盘上的知识库文件。`)){await this.client.deleteKB(kb.id);this.render();}};
    }
    body.createEl("h4",{text:"新建知识库"});
    const ni=body.createEl("input",{type:"text",placeholder:"名称",cls:"llmwiki-input"});
    const pi=body.createEl("input",{type:"text",value: vaultPath, placeholder:"根目录路径（可手写或从下方选）",cls:"llmwiki-input"});
    // Docker mount status
    const mountOk = serverRoot && vaultPath && !vaultPath.startsWith(serverRoot);
    const mountHint = body.createEl("div", { cls: mountOk ? "llmwiki-ok" : "llmwiki-muted" });
    if (serverRoot) {
      mountHint.setText(mountOk ? `🔗 路径映射: ${serverRoot}` : "📌 本地模式");
    mountHint.style.fontSize = "0.75em";
    } else {
      mountHint.setText("📌 本地模式 — 未检测到 Docker 挂载");
    }
    // Vault folder picker
    const fdRow = body.createDiv({ cls: "llmwiki-inline-row" });
    const folderSelect = fdRow.createEl("select", { cls: "llmwiki-select-inline" });
    const refreshKbPathSelect = () => {
      folderSelect.empty();
      folderSelect.createEl("option", { text: `📁 Vault 根目录`, value: vaultPath });
      for (const f of this.app.vault.getAllFolders().slice(0, 200)) {
        const fullPath = adapter instanceof FileSystemAdapter ? adapter.getFullPath(f.path) : `${vaultPath}/${f.path}`;
        folderSelect.createEl("option", { text: `📁 ${f.path}`, value: fullPath });
      }
    };
    refreshKbPathSelect();
    folderSelect.onfocus = refreshKbPathSelect;
    folderSelect.onchange = () => { pi.value = folderSelect.value; };
    body.createEl("button",{text:"创建并初始化"}).onclick=async()=>{
      const n=ni.value.trim(); let p=pi.value.trim(); if(!n||!p){new Notice("请填写名称和路径");return;}
      // Auto-map vault path → server path (e.g. Docker mount)
      if (serverRoot && vaultPath && p.startsWith(vaultPath)) {
        p = serverRoot + p.slice(vaultPath.length);
      }
      try{const kb=await this.client.createKB(n,p);await this.client.initializeKB(kb.id);await this.client.activateKB(kb.id);new Notice(`已创建: ${n}`);this.render();}catch(e){new Notice(`创建失败: ${e}`);}
    };
  }

  // ═══════════════════════════════════════════════════════════════
  // SETTINGS
  // ═══════════════════════════════════════════════════════════════

  private provList: ProviderInfo[] = [];
  private allModels: { id: string; providerName: string; providerId: string; vision: boolean }[] = [];
  private defaultTextModel: string = "";
  private defaultVisionModel: string = "";

  async renderSettings(body: HTMLElement): Promise<void> {
    const s = this.plugin.pluginSettings;

    // ── Docker Service ──
    body.createEl("h4", { text: "服务管理" });
    const statusRow = body.createDiv({ cls: "llmwiki-inline-row" });
    const statusEl = statusRow.createEl("span", { text: "检测中...", cls: "llmwiki-muted" });

    // API URL
    const apiRow = body.createDiv({ cls: "llmwiki-inline-row" });
    apiRow.createEl("span", { text: "API 地址", cls: "llmwiki-setting-label" });
    const apiInput = apiRow.createEl("input", { type: "text", value: s.apiUrl, cls: "llmwiki-select-inline" });
    apiInput.onchange = async () => { s.apiUrl = apiInput.value.trim(); this.client.setBaseUrl(s.apiUrl); await this.plugin.saveSettings(); };

    const updateStatus = async () => {
      try {
        const h = await this.client.health();
        statusEl.setText(`运行中 — v${h.version}`);
        statusEl.className = "llmwiki-ok";
      } catch {
        statusEl.setText("已停止");
        statusEl.className = "llmwiki-muted";
      }
    };
    updateStatus();

    // One-click setup: generate docker-compose + show command
    const cmdRow = body.createDiv({ cls: "llmwiki-section" });
    cmdRow.createEl("div", { text: "在终端中运行以下命令启动服务：", cls: "llmwiki-muted" });

    const vp = (this.app.vault.adapter as FileSystemAdapter)?.getBasePath?.() || "";
    const pluginDir = `${vp}/.obsidian/plugins/obwiki`;
    const cmd = `cd "${pluginDir}" && docker-compose -f docker-compose.generated.yml up -d`;

    const cmdBox = cmdRow.createEl("pre", { text: cmd, cls: "llmwiki-section" });
    cmdBox.style.cssText = "padding:8px;font-size:0.75em;overflow-x:auto;user-select:all;";

    const btnRow = cmdRow.createDiv({ cls: "llmwiki-btn-row" });
    btnRow.createEl("button", { text: "生成配置并复制命令" }).onclick = async () => {
      try {
        // Use Obsidian adapter to read template and write generated file
        const adapter = this.app.vault.adapter;
        const tplPath = ".obsidian/plugins/obwiki/docker-compose.yml";
        const genPath = ".obsidian/plugins/obwiki/docker-compose.generated.yml";
        const template = await adapter.read(tplPath);
        const compose = template.replace("VAULT_PATH", vp);
        await adapter.write(genPath, compose);
        navigator.clipboard.writeText(cmd);
        new Notice("配置已生成，命令已复制 — 粘贴到终端运行");
      } catch (e: any) {
        new Notice(`生成失败: ${e.message}`);
      }
    };
    btnRow.createEl("button", { text: "刷新状态" }).onclick = updateStatus;

    // MCP config
    body.createEl("h4", { text: "MCP 接入" });
    const mcpRow = body.createDiv({ cls: "llmwiki-inline-row" });
    const mcpJson = JSON.stringify({
      mcpServers: {
        "obwiki-mcp": {
          command: "uv",
          args: ["run", "--directory", pluginDir + "/mcp", "mcp", "run", "src/server.py"],
          env: { LLMWIKI_API_URL: s.apiUrl }
        }
      }
    }, null, 2);
    mcpRow.createEl("span", { text: "obwiki-mcp (HTTP)", cls: "llmwiki-muted" });
    mcpRow.createEl("button", { text: "复制配置", cls: "llmwiki-btn-sm" }).onclick = () => {
      navigator.clipboard.writeText(mcpJson);
      new Notice("MCP 配置已复制");
    };

    // Load providers and build model list
    try { this.provList = await this.client.getProviders(); } catch { this.provList = []; }
    this.allModels = [];
    this.defaultTextModel = s.defaultTextModelId || "";
    this.defaultVisionModel = s.defaultVisionModelId || "";

    // Fallback: if no saved model ID, use provider default
    if (!this.defaultTextModel) {
      const dt = this.provList.find(p => p.is_default_text);
      if (dt?.models?.[0]) this.defaultTextModel = dt.models[0].id;
    }
    if (!this.defaultVisionModel) {
      const dv = this.provList.find(p => p.is_default_vision);
      if (dv?.models?.[0]) this.defaultVisionModel = dv.models[0].id;
    }

    const visionModels: string[] = [];
    for (const p of this.provList) {
      for (const m of (p.models || [])) {
        this.allModels.push({ id: m.id, providerName: p.name, providerId: p.id, vision: m.vision || false });
        if (m.vision) visionModels.push(m.id);
      }
    }

    // ── Default model selectors ──
    body.createEl("h4", { text: "默认模型" });
    if (this.allModels.length > 0) {
      // Text model
      const textRow = body.createDiv({ cls: "llmwiki-inline-row" });
      textRow.createEl("label", { text: "文本模型", cls: "llmwiki-setting-label" });
      const textSel = textRow.createEl("select", { cls: "llmwiki-select-inline" });
      const textCurVal = this.allModels.find(m => m.id === this.defaultTextModel);
      for (const m of this.allModels) {
        const opt = textSel.createEl("option", { text: `[${m.providerName}] ${m.id}`, value: `${m.providerId}:${m.id}` });
        if (m.id === this.defaultTextModel) opt.selected = true;
      }
      textRow.createEl("button", { text: "应用", cls: "llmwiki-btn-sm" }).onclick = async () => {
        const [pid, mid] = textSel.value.split(":");
        await this.client.setDefaultProvider(pid, "text");
        // Save the specific model ID locally
        this.plugin.pluginSettings.defaultTextModelId = mid || "";
        await this.plugin.saveSettings();
        new Notice("默认文本模型已更新");
        this.render();
      };

      // Vision model
      if (visionModels.length > 0) {
        const visRow = body.createDiv({ cls: "llmwiki-inline-row" });
        visRow.createEl("label", { text: "多模态(可选)", cls: "llmwiki-setting-label" });
        const visSel = visRow.createEl("select", { cls: "llmwiki-select-inline" });
        visSel.createEl("option", { text: "-- 不设置 --", value: "" });
        for (const m of this.allModels.filter(m => m.vision)) {
          const opt = visSel.createEl("option", { text: `[${m.providerName}] ${m.id}`, value: `${m.providerId}:${m.id}` });
          if (m.id === this.defaultVisionModel) opt.selected = true;
        }
        visRow.createEl("button", { text: "应用", cls: "llmwiki-btn-sm" }).onclick = async () => {
          const val = visSel.value;
          if (val) {
            const [pid, mid] = val.split(":");
            await this.client.setDefaultProvider(pid, "vision");
            this.plugin.pluginSettings.defaultVisionModelId = mid || "";
          } else {
            await this.client.clearDefaultVision();
            this.plugin.pluginSettings.defaultVisionModelId = "";
          }
          await this.plugin.saveSettings();
          new Notice(val ? "默认多模态模型已更新" : "多模态模型已取消");
          this.render();
        };
      } else {
        body.createEl("div", { text: "当前无 Vision 模型。添加 GPT-4o 或 Claude 可启用", cls: "llmwiki-muted" });
      }
    } else {
      body.createEl("div", { text: "尚未添加模型供应商", cls: "llmwiki-muted" });
    }

    // ── Token Quota ──
    body.createEl("h4", { text: "模型限额" });
    const quotaSection = body.createDiv({ cls: "llmwiki-section" });
    const quotaRow = quotaSection.createDiv({ cls: "llmwiki-inline-row" });
    quotaRow.createEl("span", { text: "每日 Token 限额", cls: "llmwiki-setting-label" });
    const quotaInput = quotaRow.createEl("input", { type: "number", value: "0", placeholder: "0=不限", cls: "llmwiki-select-inline" });
    // Load current quota value
    (async () => {
      try { const kb = await this.client.getActiveKB(); const u = await this.client.getTokenUsage(kb.id); quotaInput.value = u.quota > 0 ? String(u.quota / 1_000_000) : "0"; } catch {}
    })();
    quotaInput.style.maxWidth = "70px";
    quotaRow.createEl("span", { text: "M", cls: "llmwiki-muted" });
    quotaRow.createEl("button", { text: "设置", cls: "llmwiki-btn-sm" }).onclick = async () => {
      const m = parseInt(quotaInput.value) || 0;
      try { const kb = await this.client.getActiveKB(); await this.client.setTokenQuota(kb.id, m); new Notice(`限额已设为 ${m}M`); this.render(); } catch { new Notice("设置失败"); }
    };
    // Progress bar below quota section
    this.renderQuotaBar(quotaSection);

    // ── Provider cards ──
    body.createEl("h4", { text: "模型供应商" });
    for (const p of this.provList) {
      const card = body.createDiv({ cls: "llmwiki-provider-card" });
      // Header
      const hdr = card.createDiv({ cls: "llmwiki-inline-row" });
      hdr.createEl("strong", { text: `${p.name} (${p.provider})` });
      card.createEl("div", { text: p.endpoint, cls: "llmwiki-mono llmwiki-muted" });

      // Models list with capability badges
      if (p.models.length > 0) {
        const modelDiv = card.createDiv({ cls: "llmwiki-section" });
        for (const m of p.models) {
          const row = modelDiv.createDiv({ cls: "llmwiki-inline-row" });
          row.createEl("span", { text: m.id, cls: "llmwiki-mono" });
          // Default model badges on specific models
          if (p.is_default_text && m.id === this.defaultTextModel) row.createEl("span", { text: "[默认文本]", cls: "llmwiki-ok" });
          if (p.is_default_vision && m.id === this.defaultVisionModel) row.createEl("span", { text: "[默认多模态]", cls: "llmwiki-ok" });
          // Capability emojis
          const caps: string[] = [];
          if (m.vision) caps.push("👁");
          if (m.reasoning) caps.push("💡");
          if (m.tools) caps.push("🛠");
          if (m.search) caps.push("🌐");
          if (caps.length > 0) row.createEl("span", { text: ` ${caps.join(" ")}` });
        }
      }

      // Actions: edit models, delete
      const btns = card.createDiv({ cls: "llmwiki-btn-row" });
      btns.createEl("button", { text: "编辑模型", cls: "llmwiki-btn-sm" }).onclick = async () => {
        try {
          const result = await this.client.detectModels(p.endpoint, p.api_key || "", p.provider);
          if (result.models?.length > 0) {
            const existing = (p.models || []).map((m: any) => typeof m === "string" ? { id: m, vision: false, reasoning: false, tools: false, search: false } : m);
            new ModelPickerModal(this.app, result.models, existing, async (entries) => {
              await this.client.saveProvider({ id: p.id, name: p.name, provider: p.provider, endpoint: p.endpoint, api_key: p.api_key, models: entries });
              new Notice("已更新"); this.render();
            }).open();
          }
        } catch (e) { new Notice(`检测失败: ${e}`); }
      };
      btns.createEl("button", { text: "删除", cls: "llmwiki-btn-sm llmwiki-btn-danger" }).onclick = async () => { await this.client.deleteProvider(p.id); this.render(); };
    }

    // ── Add new provider ──
    body.createEl("h4", { text: "添加供应商" });
    const addSection = body.createDiv({ cls: "llmwiki-section" });
    const newName = addSection.createEl("input", { type: "text", placeholder: "名称 (如: DeepSeek)", cls: "llmwiki-input" });
    const newProv = addSection.createEl("select", { cls: "llmwiki-select" });
    for (const o of [{ v: "openai", l: "OpenAI" }, { v: "anthropic", l: "Anthropic" }, { v: "deepseek", l: "DeepSeek" }, { v: "ollama", l: "Ollama" }, { v: "custom", l: "自定义" }]) {
      newProv.createEl("option", { text: o.l, value: o.v });
    }
    const newEp = addSection.createEl("input", { type: "text", placeholder: "Base URL (如 https://api.deepseek.com)", cls: "llmwiki-input" });
    const newKey = addSection.createEl("input", { type: "password", placeholder: "API Key", cls: "llmwiki-input" });

    const addRow = addSection.createDiv({ cls: "llmwiki-btn-row" });
    let detectedModels: { id: string; owned_by: string }[] = [];
    addRow.createEl("button", { text: "检测模型并选择" }).onclick = async () => {
      const ep = newEp.value.trim(); if (!ep) { new Notice("请输入 Base URL"); return; }
      try {
        const result = await this.client.detectModels(ep, newKey.value.trim(), newProv.value);
        if (result.models?.length > 0) {
          new ModelPickerModal(this.app, result.models, [], async (entries) => {
            await this.client.saveProvider({
              name: newName.value.trim() || newProv.value, provider: newProv.value,
              endpoint: ep, api_key: newKey.value.trim(), models: entries,
            });
            new Notice(`已添加`); this.render();
          }).open();
        } else { new Notice(`未检测到模型: ${result.error || "空列表"}`); }
      } catch (e) { new Notice(`检测失败: ${e}`); }
    };
  }

  // ═══════════════════════════════════════════════════════════════
  // AUTOMATION
  // ═══════════════════════════════════════════════════════════════

  // ── Docker service management ──

  private async startDockerService(): Promise<string> {
    const adapter = this.app.vault.adapter;
    const vaultPath = adapter instanceof FileSystemAdapter ? adapter.getBasePath() : "";
    // @ts-ignore: Node require
    const { execSync } = require("child_process");
    const path = require("path");
    const fs = require("fs");

    // Determine plugin directory (where docker-compose.yml lives)
    const pluginDir = (this.app.vault.adapter as any).basePath
      ? path.join((this.app.vault.adapter as any).basePath, ".obsidian", "plugins", "obwiki")
      : path.join(vaultPath, ".obsidian", "plugins", "obwiki");

    if (!fs.existsSync(path.join(pluginDir, "docker-compose.yml"))) {
      return "docker-compose.yml 未找到，请确认插件目录完整";
    }

    // Check Docker installed
    try {
      execSync("docker --version", { encoding: "utf-8" });
    } catch {
      return "未检测到 Docker，请先安装 Docker 或 OrbStack";
    }

    // Generate docker-compose.yml with vault path (keep template intact)
    const template = fs.readFileSync(path.join(pluginDir, "docker-compose.yml"), "utf-8");
    const compose = template.replace("VAULT_PATH", vaultPath);
    const generatedPath = path.join(pluginDir, "docker-compose.generated.yml");
    fs.writeFileSync(generatedPath, compose);

    // Build and start
    try {
      execSync(`cd "${pluginDir}" && docker-compose -f docker-compose.generated.yml up -d --build`, { encoding: "utf-8", timeout: 300000 });
      return "服务已启动";
    } catch (e: any) {
      return `启动失败: ${e.message?.slice(0, 200)}`;
    }
  }

  private async stopDockerService(): Promise<string> {
    // @ts-ignore
    const { execSync } = require("child_process");
    const path = require("path");
    const vaultPath = (this.app.vault.adapter as FileSystemAdapter)?.getBasePath?.() || "";
    const pluginDir = path.join(vaultPath, ".obsidian", "plugins", "obwiki");
    try {
      execSync(`cd "${pluginDir}" && docker-compose -f docker-compose.generated.yml down`, { encoding: "utf-8", timeout: 30000 });
      return "服务已停止";
    } catch (e: any) {
      return `停止失败: ${e.message?.slice(0, 200)}`;
    }
  }

  async renderQuotaBar(parent: HTMLElement): Promise<void> {
    try {
      const kb = await this.client.getActiveKB();
      const usage = await this.client.getTokenUsage(kb.id);
      if (usage.quota > 0) {
        const pct = Math.min(100, (usage.used / usage.quota) * 100);
        const usedK = (usage.used / 1000).toFixed(1);
        const quotaK = (usage.quota / 1000).toFixed(1);
        const barDiv = parent.createDiv({ cls: "llmwiki-section" });
        barDiv.createEl("div", { text: `今日用量: ${usedK}K / ${quotaK}K`, cls: "llmwiki-muted" });
        const bar = barDiv.createDiv({ cls: "llmwiki-progress-bar", attr: { title: `已用 ${usage.used.toLocaleString()} / 限额 ${usage.quota.toLocaleString()} tokens` } });
        const fill = bar.createDiv({ cls: "llmwiki-progress-fill" });
        fill.style.width = `${pct}%`;
        if (pct > 80) fill.style.background = "var(--color-red)";
        else if (pct > 50) fill.style.background = "var(--color-orange)";
      }
    } catch {}
  }

  renderAutomation(body: HTMLElement): void {
    const s = this.plugin.pluginSettings;
    const changes = new Map<string, any>();

    const toggle = (label: string, key: string, current: boolean) => {
      const row = body.createDiv({ cls: "llmwiki-inline-row" });
      row.createEl("span", { text: label, cls: "llmwiki-setting-label" });
      const cb = row.createEl("input", { type: "checkbox" }) as HTMLInputElement;
      cb.checked = current;
      cb.onchange = () => { changes.set(key, cb.checked); row.style.color = "var(--text-accent)"; };
    };

    const schedule = (label: string, schedKey: string, timeKey: string, dayKey?: string) => {
      const row = body.createDiv({ cls: "llmwiki-inline-row" });
      row.createEl("span", { text: label, cls: "llmwiki-setting-label" });
      const sched = row.createEl("select", { cls: "llmwiki-select-inline" });
      sched.style.flex = "0 0 60px";
      for (const o of [{ v: "daily", l: "每天" }, { v: "weekly", l: "每周" }, { v: "off", l: "关闭" }]) {
        sched.createEl("option", { text: o.l, value: o.v }).selected = (s as any)[schedKey] === o.v;
      }
      let dayEl: HTMLElement | null = null;
      sched.onchange = () => { changes.set(schedKey, sched.value); row.style.color = "var(--text-accent)"; if (dayEl) dayEl.style.display = sched.value === "weekly" ? "" : "none"; };
      if (dayKey) {
        dayEl = row.createEl("select", { cls: "llmwiki-select-inline" });
        dayEl.style.flex = "0 0 56px";
        for (const o of [{ v: "1", l: "周一" }, { v: "2", l: "周二" }, { v: "3", l: "周三" }, { v: "4", l: "周四" }, { v: "5", l: "周五" }, { v: "6", l: "周六" }, { v: "0", l: "周日" }]) {
          dayEl.createEl("option", { text: o.l, value: o.v }).selected = (s as any)[dayKey] === o.v;
        }
        dayEl.onchange = () => { changes.set(dayKey, (dayEl as HTMLSelectElement).value); row.style.color = "var(--text-accent)"; };
        // Show only when weekly or monthly
        if ((s as any)[schedKey] !== "weekly") dayEl.style.display = "none";
      }
      const time = row.createEl("input", { type: "time", value: (s as any)[timeKey], cls: "llmwiki-select-inline" });
      time.style.flex = "0 0 110px";
      time.onchange = () => { changes.set(timeKey, time.value); row.style.color = "var(--text-accent)"; };
    };

    body.createEl("h4", { text: "定时任务" });
    schedule("收件箱整理", "autoOrganizeSchedule", "autoOrganizeTime", "autoOrganizeDay");
    schedule("文档处理(扫描+提取)", "autoProcessSchedule", "autoProcessTime", "autoProcessDay");
    schedule("知识演进(演进+结晶+社区)", "autoEvolveSchedule", "autoEvolveTime", "autoEvolveDay");
    schedule("健康检查", "autoLintSchedule", "autoLintTime", "autoLintDay");

    body.createEl("button", { text: "保存并应用", cls: "mod-cta" }).onclick = async () => {
      for (const [k, v] of changes) {
        (s as any)[k] = v;
      }
      await this.plugin.saveSettings();
      new Notice("自动化配置已保存");
      this.render();
    };
  }

  private selectRow(parent: HTMLElement, label: string, options: { value: string; label: string }[], current: string, onChange: (v: string) => void): void {
    const row = parent.createDiv({ cls: "llmwiki-inline-row" });
    row.createEl("label", { text: label, cls: "llmwiki-setting-label" });
    const sel = row.createEl("select", { cls: "llmwiki-select-inline" });
    for (const o of options) {
      const opt = sel.createEl("option", { text: o.label, value: o.value });
      if (o.value === current) opt.selected = true;
    }
    sel.onchange = () => onChange(sel.value);
  }

  private inputRow(parent: HTMLElement, label: string, value: string, onChange: (v: string) => void): void {
    const row = parent.createDiv({ cls: "llmwiki-inline-row" });
    row.createEl("label", { text: label, cls: "llmwiki-setting-label" });
    const inp = row.createEl("input", { type: "text", value, cls: "llmwiki-select-inline" });
    inp.onchange = () => onChange(inp.value.trim());
  }
}

// ═══════════════════════════════════════════════════════════════
// HELPERS
// ═══════════════════════════════════════════════════════════════

function sleep(ms: number): Promise<void> { return new Promise(r => setTimeout(r, ms)); }
function isBinary(filename: string): boolean { return BINARY_EXTS.has(filename.split(".").pop()?.toLowerCase() || ""); }
function hasVisionCapability(modelId: string): boolean {
  const m = modelId.toLowerCase();
  const VISION = [
    "gpt-4o", "gpt-4-turbo",
    "claude-3", "claude-4", "claude-sonnet", "claude-opus",
    "gemini-2", "gemini-1.5-pro",
    "kimi-k2", "moonshot-v1",
    "qwen-vl", "qwen3.6-plus", "qwen3-vl", "qwen2.5-vl",
    "glm-4v", "glm-4.6v", "glm-4.5v",
    "minimax-m3",
    "llama3.2-vision", "llava", "bakllava", "cogvlm", "pixtral",
    "vision",
  ];
  return VISION.some(p => m.includes(p));
}

function buildModelCheckboxes(parent: HTMLElement, models: { id: string; owned_by?: string }[], selected: string[]): HTMLInputElement[] {
  const checkboxes: HTMLInputElement[] = [];
  for (const m of models.slice(0, 60)) {
    const row = parent.createDiv({ cls: "llmwiki-model-row" });
    const cb = row.createEl("input", { type: "checkbox", value: m.id });
    if (selected.includes(m.id)) cb.checked = true;
    row.createEl("span", { text: m.id, cls: "llmwiki-mono" });
    if (hasVisionCapability(m.id)) row.createEl("span", { text: " [Vision]", cls: "llmwiki-ok" });
    checkboxes.push(cb);
  }
  return checkboxes;
}
function jobLabel(type: string): string {
  const map: Record<string, string> = { scan: "扫描索引", process: "文档处理", extract: "知识提取", evolve: "知识演进", crystallize: "生成结晶", communities: "检测社区", organize: "整理收件箱", lint: "健康检查", repair: "修复" };
  return map[type] || type;
}
function statusLabel(s: string): string {
  const map: Record<string, string> = { raw: "排队", indexed: "排队", organizing: "处理中", extracting: "处理中", dedup_check: "处理中", extracted: "完成", error: "失败", cancelled: "已取消" };
  return map[s] || s;
}
function phaseLabel(s: string): string {
  const map: Record<string, string> = { raw: "-", indexed: "-", organizing: "整理分类", extracting: "提取知识", dedup_check: "去重检查", extracted: "已生成", error: "出错", cancelled: "已取消" };
  return map[s] || s;
}
function truncateResult(log: string): string {
  if (log.includes("pages_created")) { const m = log.match(/"pages_created":\s*\[(.*?)\]/); if (m) return `${m[1].split(",").length} 个页面`; }
  if (log.includes("relationships_found")) { const m = log.match(/"relationships_found":\s*(\d+)/); const c = log.match(/"clusters_found":\s*(\d+)/); return m ? `${m[1]} 关系${c?`, ${c[1]} 类`:""}` : log.slice(0,40); }
  if (log.includes("added")) { const m = log.match(/"added":\s*(\d+)/); return m ? `索引 ${m[1]} 个文件` : log.slice(0,40); }
  return log.slice(0, 40);
}
