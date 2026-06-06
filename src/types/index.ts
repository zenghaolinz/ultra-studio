export interface Message {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  createdAt: string;
  images?: string[];
  toolEvents?: ToolActivityEvent[];
}

export interface ToolActivityEvent {
  id: string;
  label: string;
  detail: string;
  createdAt: string;
}

export interface Conversation {
  id: string;
  title: string;
  projectId?: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface Project {
  id: string;
  name: string;
  rootPath: string;
  createdAt: string;
  updatedAt: string;
}

export interface ProjectVisibleFile {
  name: string;
  path: string;
  relativePath: string;
  extension: string;
  size: number;
  modifiedAt: string;
}

export interface ProjectFileSummary {
  rootPath: string;
  documents: ProjectVisibleFile[];
  images: ProjectVisibleFile[];
  documentCount: number;
  imageCount: number;
  scannedCount: number;
}

export interface MemoryBranch {
  id: string;
  name: string;
  domain: string;
  description: string;
  parentId: string | null;
  entryCount: number;
}

export interface STMEntry {
  id: string;
  conversationId: string;
  role: "user" | "assistant";
  content: string;
  createdAt: string;
}

export interface LTMEntry {
  id: string;
  content: string;
  domain: string;
  branch: string;
  tags: string[];
  accessCount: number;
  createdAt: string;
  updatedAt: string;
}

export interface ModelConfig {
  id: string;
  provider: string;
  modelName: string;
  apiKey: string;
  baseUrl: string;
  isDefault: boolean;
}

export interface EmbeddingConfig {
  id: string;
  provider: string;
  modelName: string;
  dimensions: number;
  apiKey: string;
  baseUrl: string;
  isDefault: boolean;
}

export type ProviderType =
  | "openai"
  | "deepseek"
  | "qwen"
  | "glm"
  | "ollama"
  | "llama_cpp"
  | "lmstudio";

export const PROVIDER_PRESETS: Record<
  ProviderType,
  { baseUrl: string; label: string }
> = {
  openai: { baseUrl: "https://api.openai.com/v1", label: "OpenAI" },
  deepseek: {
    baseUrl: "https://api.deepseek.com",
    label: "DeepSeek",
  },
  qwen: {
    baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    label: "Qwen (通义千问)",
  },
  glm: { baseUrl: "https://open.bigmodel.cn/api/paas/v4", label: "GLM (智谱)" },
  ollama: { baseUrl: "http://localhost:11434/v1", label: "Ollama" },
  llama_cpp: { baseUrl: "http://localhost:8080/v1", label: "llama.cpp" },
  lmstudio: { baseUrl: "http://localhost:1234/v1", label: "LM Studio" },
};

export interface RememberResult {
  ok: boolean;
  id?: string;
  content?: string;
  branchPath?: string;
  tags?: string[];
  error?: string;
}

export interface LocalModel {
  id: string;
  name: string;
}

export interface LocalProvider {
  name: string;
  baseUrl: string;
  available: boolean;
  models: LocalModel[];
}

export interface Persona {
  content: string;
  updatedAt: string;
}

export type WorkspaceType = "agent" | "image_studio" | "3d_studio";

export type GenerateQuality = "fast" | "quality";
export type ThreeDGenerateMode = "auto" | "multiview";

export interface ThreeDGenerateRequest {
  mode: "text" | "image" | "fusion" | "multiview";
  prompt?: string;
  imagePaths: string[];
  quality: GenerateQuality;
}

export interface ThreeDGenerateResult {
  status: "success" | "error";
  modelPath?: string;
  image2D?: string;
  imageNormal?: string;
  imageUV?: string;
  image1Path?: string;
  image2Path?: string;
  message?: string;
}

export type GenerationTaskStatus = "running" | "success" | "error" | "cancelled";

export interface GenerationTask {
  id: string;
  taskType: string;
  status: GenerationTaskStatus;
  prompt: string;
  qualityMode: string;
  inputPaths: string[];
  outputPaths: Record<string, string | null | undefined>;
  error: string;
  createdAt: string;
  updatedAt: string;
  completedAt?: string | null;
}

export interface ThreeDProgress {
  value: number;
  description: string;
}

export interface ComfyUiStatus {
  started?: boolean;
  stopped?: boolean;
  running?: boolean;
  ready?: boolean;
  configured_path?: string;
  launch_mode?: ComfyUiLaunchMode;
  selected_profile_id?: string | null;
  process_alive?: boolean;
  recent_logs?: string[];
  error?: string;
}

export type ComfyUiLaunchMode = "portable" | "external";

export interface ComfyUiProfile {
  id: string;
  name: string;
  path: string;
  launch_mode?: ComfyUiLaunchMode;
  selected?: boolean;
  valid?: boolean;
}

export interface ComfyUiProfilesResponse {
  profiles: ComfyUiProfile[];
  status: ComfyUiStatus;
}

export type DiagnosticStatus = "ok" | "warn" | "error";

export interface DiagnosticItem {
  id: string;
  label: string;
  status: DiagnosticStatus;
  detail: string;
  action?: string;
}

export interface DiagnosticsReport {
  overall: DiagnosticStatus;
  checkedAt: string;
  items: DiagnosticItem[];
  summary: {
    ok: number;
    warn: number;
    error: number;
  };
}
