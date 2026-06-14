import { Modal, App, Notice } from "obsidian";

export interface ModelEntry {
  id: string;
  vision: boolean;
  reasoning: boolean;
  tools: boolean;
  search: boolean;
}

export class ModelPickerModal extends Modal {
  private models: { id: string; owned_by?: string }[];
  private existing: ModelEntry[];
  private onSave: (entries: ModelEntry[]) => void;

  constructor(
    app: App,
    models: { id: string; owned_by?: string }[],
    existing: ModelEntry[],
    onSave: (entries: ModelEntry[]) => void,
  ) {
    super(app);
    this.models = models;
    this.existing = existing;
    this.onSave = onSave;
  }

  onOpen(): void {
    const { contentEl } = this;
    contentEl.empty();
    contentEl.addClass("llmwiki-modal");

    contentEl.createEl("h3", { text: "选择模型" });
    contentEl.createEl("p", { text: "勾选要添加的模型，并设置能力标签", cls: "llmwiki-muted" });

    // Header row
    const header = contentEl.createDiv({ cls: "llmwiki-model-header" });
    header.createEl("span", { text: "模型", cls: "llmwiki-model-name-header" });
    const capGroup = header.createDiv({ cls: "llmwiki-cap-group" });
    for (const h of ["视觉", "推理", "工具", "联网"]) {
      capGroup.createDiv({ text: h, cls: "llmwiki-cap-col llmwiki-cap-header" });
    }

    const rows: Map<string, { enabled: HTMLInputElement; vision: HTMLInputElement; reasoning: HTMLInputElement; tools: HTMLInputElement; search: HTMLInputElement }> = new Map();

    const list = contentEl.createDiv({ cls: "llmwiki-model-list" });
    for (const m of this.models.slice(0, 60)) {
      const existingEntry = this.existing.find(e => e.id === m.id);
      const row = list.createDiv({ cls: "llmwiki-model-row" });

      const enabled = row.createEl("input", { type: "checkbox" });
      if (existingEntry || this.existing.length === 0) enabled.checked = true;

      row.createEl("span", { text: m.id, cls: "llmwiki-mono" });

      // Pre-fill from registry guess
      const preVision = existingEntry?.vision ?? guessCapability(m.id, "vision");
      const preReasoning = existingEntry?.reasoning ?? guessCapability(m.id, "reasoning");
      const preTools = existingEntry?.tools ?? guessCapability(m.id, "tools");
      const preSearch = existingEntry?.search ?? guessCapability(m.id, "search");

      const capGroup = row.createDiv({ cls: "llmwiki-cap-group" });
      const vision = capGroup.createDiv({ cls: "llmwiki-cap-col" }).createEl("input", { type: "checkbox" });
      vision.checked = preVision;
      const reasoning = capGroup.createDiv({ cls: "llmwiki-cap-col" }).createEl("input", { type: "checkbox" });
      reasoning.checked = preReasoning;
      const tools = capGroup.createDiv({ cls: "llmwiki-cap-col" }).createEl("input", { type: "checkbox" });
      tools.checked = preTools;
      const search = capGroup.createDiv({ cls: "llmwiki-cap-col" }).createEl("input", { type: "checkbox" });
      search.checked = preSearch;

      rows.set(m.id, { enabled, vision, reasoning, tools, search });
    }

    // Buttons
    const btnRow = contentEl.createDiv({ cls: "llmwiki-btn-row" });
    btnRow.createEl("button", { text: "全选" }).onclick = () => { rows.forEach(r => r.enabled.checked = true); };
    btnRow.createEl("button", { text: "全不选" }).onclick = () => { rows.forEach(r => r.enabled.checked = false); };
    btnRow.createEl("button", { text: "保存", cls: "mod-cta" }).onclick = () => {
      const result: ModelEntry[] = [];
      for (const m of this.models) {
        const r = rows.get(m.id);
        if (r && r.enabled.checked) {
          result.push({
            id: m.id, vision: r.vision.checked, reasoning: r.reasoning.checked,
            tools: r.tools.checked, search: r.search.checked,
          });
        }
      }
      if (result.length === 0) { new Notice("请至少选择一个模型"); return; }
      this.onSave(result);
      this.close();
    };
  }

  onClose(): void {
    this.contentEl.empty();
  }
}

function guessCapability(modelId: string, cap: string): boolean {
  const m = modelId.toLowerCase();
  switch (cap) {
    case "vision":
      return ["gpt-4o", "claude-3", "claude-4", "gemini-2", "kimi-k2", "qwen-vl", "qwen3.6-plus", "qwen3-vl", "glm-4v", "minimax-m3", "vision"].some(p => m.includes(p));
    case "reasoning":
      return ["deepseek-v4", "o1", "o3", "claude-opus", "claude-sonnet", "qwen3.6", "kimi-k2", "gemini-2.5-pro", "reasoning"].some(p => m.includes(p));
    case "tools":
      return ["gpt-4", "claude", "gemini", "qwen3", "deepseek-v3", "deepseek-v4", "function", "tool"].some(p => m.includes(p));
    case "search":
      return ["gpt-4o", "gemini", "claude-4", "search"].some(p => m.includes(p));
    default:
      return false;
  }
}
