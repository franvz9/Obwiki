import { Plugin, WorkspaceLeaf, addIcon } from "obsidian";
import { LLMWikiClient } from "./api-client";
import { LLMWikiSettings, DEFAULT_SETTINGS } from "./settings";
import { LLMWikiView, LLMWIKI_VIEW_TYPE } from "./views/llmwiki-view";

const ICON = `<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <path d="M12 2a10 10 0 1 0 10 10A10 10 0 0 0 12 2z"/><path d="M8 12a4 4 0 0 1 8 0"/>
  <path d="M12 8a8 8 0 0 0-4 4"/><path d="M12 8a8 8 0 0 1 4 4"/><circle cx="12" cy="12" r="2"/>
  <path d="M12 22v-6"/><path d="M12 8V2"/>
</svg>`;

export default class LLMWikiPlugin extends Plugin {
  pluginSettings!: LLMWikiSettings;
  client!: LLMWikiClient;

  async onload(): Promise<void> {
    await this.loadSettings();
    this.client = new LLMWikiClient(this.pluginSettings.apiUrl);

    // Auto-detect server KB root for Docker path mapping
    try {
      const cfg = await this.client.getServerConfig();
      (this as any)._serverKbRoot = cfg.kb_root;
    } catch {
      (this as any)._serverKbRoot = "";
    }

    addIcon("obwiki", ICON);

    this.registerView(LLMWIKI_VIEW_TYPE, (leaf: WorkspaceLeaf) => new LLMWikiView(leaf, this));

    this.addRibbonIcon("obwiki", "ObWiki", () => this.activateView());

    this.addCommand({ id: "open-obwiki", name: "打开 ObWiki 面板", callback: () => this.activateView() });

    this.addStatusBarItem().setText("ObWiki");
  }

  onunload(): void {}

  async loadSettings(): Promise<void> {
    this.pluginSettings = Object.assign({}, DEFAULT_SETTINGS, await this.loadData());
  }

  async saveSettings(): Promise<void> {
    await this.saveData(this.pluginSettings);
  }

  async activateView(): Promise<void> {
    const { workspace } = this.app;
    const existing = workspace.getLeavesOfType(LLMWIKI_VIEW_TYPE)[0];
    if (existing) { workspace.revealLeaf(existing); return; }
    const leaf = workspace.getRightLeaf(false);
    if (leaf) {
      await leaf.setViewState({ type: LLMWIKI_VIEW_TYPE, active: true });
      workspace.revealLeaf(leaf);
    }
  }
}
