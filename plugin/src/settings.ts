export interface LLMWikiSettings {
  apiUrl: string;
  refreshInterval: number;
  llmEndpoint: string;
  llmModel: string;
  llmApiKey: string;
  llmProvider: string;
  defaultTextModelId: string;
  defaultVisionModelId: string;
  // Automation
  autoScanOnImport: boolean;
  autoExtractOnImport: boolean;
  autoOrganizeSchedule: string;
  autoOrganizeTime: string;
  autoOrganizeDay: string;
  autoProcessSchedule: string;
  autoProcessTime: string;
  autoProcessDay: string;
  autoEvolveSchedule: string;
  autoEvolveDay: string;
  autoEvolveTime: string;
  autoLintSchedule: string;
  autoLintTime: string;
  autoLintDay: string;
}

export const DEFAULT_SETTINGS: LLMWikiSettings = {
  apiUrl: "http://127.0.0.1:8742",
  refreshInterval: 30,
  llmEndpoint: "https://api.deepseek.com",
  llmModel: "deepseek-v4-pro",
  llmApiKey: "",
  llmProvider: "deepseek",
  defaultTextModelId: "",
  defaultVisionModelId: "",
  autoScanOnImport: true,
  autoExtractOnImport: true,
  autoOrganizeSchedule: "daily",
  autoOrganizeTime: "02:00",
  autoOrganizeDay: "1",
  autoProcessSchedule: "daily",
  autoProcessTime: "03:00",
  autoProcessDay: "1",
  autoEvolveSchedule: "weekly",
  autoEvolveDay: "1",
  autoEvolveTime: "04:00",
  autoLintSchedule: "daily",
  autoLintTime: "06:00",
  autoLintDay: "1",
};
