import { create } from "zustand";
import type {
  Conversation,
  Project,
  ProjectFileSummary,
  Message,
  ToolActivityEvent,
  ModelConfig,
  EmbeddingConfig,
  Persona,
  WorkspaceType,
  GenerateQuality,
  ThreeDGenerateMode,
} from "../types";
import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import type { UiLanguage } from "../i18n";

type ActiveStream = {
  conversationId: string;
  messageId: string;
  content: string;
  createdAt: string;
  toolEvents: ToolActivityEvent[];
  status: string;
};
const activeStreams: Record<string, ActiveStream> = {};
const completedToolEvents: Record<string, ToolActivityEvent[]> = {};
type PermissionMode = "standard" | "autonomous";

type SendMessageOptions = {
  hideUserMessage?: boolean;
  removeMessageId?: string;
};

function initialLanguage(): UiLanguage {
  if (typeof window === "undefined") return "zh";
  return window.localStorage.getItem("ultra-studio-language") === "en" ? "en" : "zh";
}

interface AppState {
  conversations: Conversation[];
  projects: Project[];
  projectFiles: ProjectFileSummary | null;
  projectFilesLoading: boolean;
  currentProjectId: string | null;
  currentConversationId: string | null;
  messages: Message[];
  modelConfigs: ModelConfig[];
  modelConfig: ModelConfig | null;
  embeddingConfig: EmbeddingConfig | null;
  isStreaming: boolean;
  activeStreamingConversationId: string | null;
  sidecarReady: boolean;
  memoryNotifications: string[];
  streamingMessageId: string | null;
  streamingStatus: string;
  personaContent: string;
  showPersonaModal: boolean;
  permissionMode: PermissionMode;
  visionEnabled: boolean;
  language: UiLanguage;
  setPermissionMode: (mode: PermissionMode) => void;
  setVisionEnabled: (enabled: boolean) => void;
  setLanguage: (language: UiLanguage) => void;

  workspace: WorkspaceType;
  setWorkspace: (w: WorkspaceType) => void;

  attachedImages: string[];
  addAttachedImage: (path: string) => void;
  removeAttachedImage: (index: number) => void;
  clearAttachedImages: () => void;

  threeDImages: string[];
  threeDTextPrompt: string;
  threeDProgress: number;
  threeDProgressDesc: string;
  threeDModelPath: string | null;
  threeDPreview2D: string | null;
  threeDPreviewNormal: string | null;
  threeDPreviewUV: string | null;
  threeDSourceImage1: string | null;
  threeDSourceImage2: string | null;
  threeDIsGenerating: boolean;
  threeDQuality: GenerateQuality;
  threeDGenerateMode: ThreeDGenerateMode;

  addThreeDImage: (path: string) => void;
  setThreeDImages: (paths: string[]) => void;
  removeThreeDImage: (index: number) => void;
  setThreeDTextPrompt: (prompt: string) => void;
  setThreeDQuality: (quality: GenerateQuality) => void;
  setThreeDGenerateMode: (mode: ThreeDGenerateMode) => void;
  clearThreeDResults: () => void;

  loadConversations: () => Promise<void>;
  loadProjects: () => Promise<void>;
  loadProjectFiles: (projectId?: string | null) => Promise<void>;
  createProject: (path: string, name?: string) => Promise<string>;
  selectProject: (id: string | null) => Promise<void>;
  deleteProject: (id: string) => Promise<void>;
  createConversation: () => Promise<string>;
  selectConversation: (id: string) => Promise<void>;
  deleteConversation: (id: string) => Promise<void>;
  sendMessage: (content: string, options?: SendMessageOptions) => Promise<void>;
  setModelConfig: (config: ModelConfig) => Promise<void>;
  loadModelConfigs: () => Promise<void>;
  selectModelConfig: (id: string) => Promise<void>;
  setEmbeddingConfig: (config: EmbeddingConfig) => Promise<void>;
  initSidecar: () => Promise<void>;
  clearMemoryNotification: () => void;
  loadPersona: () => Promise<void>;
  dismissPersonaModal: () => void;
}

function cleanupListeners(listeners: UnlistenFn[]) {
  listeners.forEach((fn) => {
    try {
      fn();
    } catch {}
  });
}

function activityFromStatus(status: string): ToolActivityEvent {
  const toolMatch = status.match(/^正在调用工具[：:]\s*(.+)$/);
  const detail = toolMatch?.[1] || (status.includes("ComfyUI") ? "comfyui" : "workflow");
  return {
    id: crypto.randomUUID(),
    label: status,
    detail,
    createdAt: new Date().toISOString(),
  };
}

function appendActivity(stream: ActiveStream, status: string) {
  const last = stream.toolEvents[stream.toolEvents.length - 1];
  if (last?.label === status) return stream.toolEvents;
  stream.toolEvents = [...stream.toolEvents, activityFromStatus(status)];
  return stream.toolEvents;
}

export const useAppStore = create<AppState>((set, get) => ({
  conversations: [],
  projects: [],
  projectFiles: null,
  projectFilesLoading: false,
  currentProjectId: null,
  currentConversationId: null,
  messages: [],
  modelConfigs: [],
  modelConfig: null,
  embeddingConfig: null,
  isStreaming: false,
  activeStreamingConversationId: null,
  sidecarReady: false,
  memoryNotifications: [],
  streamingMessageId: null,
  streamingStatus: "",
  personaContent: "",
  showPersonaModal: false,
  permissionMode: "standard",
  visionEnabled: false,
  language: initialLanguage(),
  setPermissionMode: (mode) => set({ permissionMode: mode }),
  setVisionEnabled: (enabled) => set({ visionEnabled: enabled }),
  setLanguage: (language) => {
    window.localStorage.setItem("ultra-studio-language", language);
    set({ language });
  },

  workspace: "agent",
  setWorkspace: (w) => set({ workspace: w }),

  attachedImages: [],
  addAttachedImage: (path) =>
    set((s) => ({ attachedImages: [...s.attachedImages, path] })),
  removeAttachedImage: (index) =>
    set((s) => ({
      attachedImages: s.attachedImages.filter((_, i) => i !== index),
    })),
  clearAttachedImages: () => set({ attachedImages: [] }),

  threeDImages: [],
  threeDTextPrompt: "",
  threeDProgress: 0,
  threeDProgressDesc: "",
  threeDModelPath: null,
  threeDPreview2D: null,
  threeDPreviewNormal: null,
  threeDPreviewUV: null,
  threeDSourceImage1: null,
  threeDSourceImage2: null,
  threeDIsGenerating: false,
  threeDQuality: "fast",
  threeDGenerateMode: "auto",

  addThreeDImage: (path) =>
    set((s) => ({ threeDImages: [...s.threeDImages, path] })),

  setThreeDImages: (paths) => set({ threeDImages: paths }),

  removeThreeDImage: (index) =>
    set((s) => ({
      threeDImages: s.threeDImages.filter((_, i) => i !== index),
    })),

  setThreeDTextPrompt: (prompt) => set({ threeDTextPrompt: prompt }),

  setThreeDQuality: (quality) => set({ threeDQuality: quality }),

  setThreeDGenerateMode: (mode) => set({ threeDGenerateMode: mode }),

  clearThreeDResults: () =>
    set({
      threeDProgress: 0,
      threeDProgressDesc: "",
      threeDModelPath: null,
      threeDPreview2D: null,
      threeDPreviewNormal: null,
      threeDPreviewUV: null,
      threeDSourceImage1: null,
      threeDSourceImage2: null,
      threeDIsGenerating: false,
    }),

  loadPersona: async () => {
    try {
      const p = await invoke<Persona>("get_persona");
      set({ personaContent: p.content });
      if (!p.content) set({ showPersonaModal: true });
    } catch {
      set({ showPersonaModal: true });
    }
  },

  dismissPersonaModal: () => set({ showPersonaModal: false }),

  loadConversations: async () => {
    try {
      const projectId = get().currentProjectId;
      const conversations = await invoke<Conversation[]>("list_conversations", {
        projectId,
      });
      set({ conversations });
    } catch (e) {
      console.error("Failed to load conversations:", e);
    }
  },

  loadProjects: async () => {
    try {
      const projects = await invoke<Project[]>("list_projects");
      set({ projects });
    } catch (e) {
      console.error("Failed to load projects:", e);
    }
  },

  loadProjectFiles: async (projectId?: string | null) => {
    const id = projectId === undefined ? get().currentProjectId : projectId;
    if (!id) {
      set({ projectFiles: null, projectFilesLoading: false });
      return;
    }
    set({ projectFilesLoading: true });
    try {
      const files = await invoke<ProjectFileSummary>("list_project_files", {
        projectId: id,
      });
      if (get().currentProjectId === id) {
        set({ projectFiles: files, projectFilesLoading: false });
      }
    } catch (e) {
      console.error("Failed to load project files:", e);
      if (get().currentProjectId === id) {
        set({ projectFiles: null, projectFilesLoading: false });
      }
    }
  },

  createProject: async (path: string, name?: string) => {
    const project = await invoke<Project>("create_project", { path, name });
    set((state) => ({
      projects: [project, ...state.projects.filter((p) => p.id !== project.id)],
      currentProjectId: project.id,
      currentConversationId: null,
      messages: [],
    }));
    await get().loadConversations();
    await get().loadProjectFiles(project.id);
    return project.id;
  },

  selectProject: async (id: string | null) => {
    set({ currentProjectId: id, currentConversationId: null, messages: [], projectFiles: null });
    await get().loadConversations();
    await get().loadProjectFiles(id);
  },

  deleteProject: async (id: string) => {
    await invoke("delete_project", { projectId: id });
    const state = get();
    const projects = state.projects.filter((p) => p.id !== id);
    set({
      projects,
      currentProjectId: state.currentProjectId === id ? null : state.currentProjectId,
      currentConversationId: state.currentProjectId === id ? null : state.currentConversationId,
      messages: state.currentProjectId === id ? [] : state.messages,
      projectFiles: state.currentProjectId === id ? null : state.projectFiles,
    });
    await get().loadConversations();
  },

  createConversation: async () => {
    try {
      const conversation = await invoke<Conversation>("create_conversation", {
        title: get().language === "zh" ? "\u65b0\u5bf9\u8bdd" : "New chat",
        projectId: get().currentProjectId,
      });
      set((state) => ({
        conversations: [conversation, ...state.conversations],
        currentConversationId: conversation.id,
        messages: [],
      }));
      return conversation.id;
    } catch (e) {
      console.error("createConversation failed:", e);
      throw e;
    }
  },

  selectConversation: async (id: string) => {
    const streamForConversation = activeStreams[id] ?? null;
    set({
      currentConversationId: id,
      isStreaming: !!streamForConversation,
      streamingMessageId: streamForConversation?.messageId ?? null,
      streamingStatus: streamForConversation?.status ?? "",
    });
    try {
      const messages = await invoke<Message[]>("get_messages", {
        conversationId: id,
      });
      const messagesWithToolEvents = messages.map((message) =>
        completedToolEvents[message.id] ? { ...message, toolEvents: completedToolEvents[message.id] } : message
      );
      const restoredMessages =
        streamForConversation && !messages.some((message) => message.id === streamForConversation.messageId)
          ? [
              ...messagesWithToolEvents,
              {
                id: streamForConversation.messageId,
                role: "assistant" as const,
                content: streamForConversation.content,
                createdAt: streamForConversation.createdAt,
                toolEvents: streamForConversation.toolEvents,
              },
            ]
          : messagesWithToolEvents;
      set({
        messages: restoredMessages,
        isStreaming: !!streamForConversation,
        streamingMessageId: streamForConversation?.messageId ?? null,
        streamingStatus: streamForConversation?.status ?? "",
      });
    } catch (e) {
      console.error("Failed to load messages:", e);
    }
  },

  deleteConversation: async (id: string) => {
    await invoke("delete_conversation", { conversationId: id });
    delete activeStreams[id];
    const state = get();
    const remaining = state.conversations.filter((c) => c.id !== id);
    set({
      conversations: remaining,
      currentConversationId:
        state.currentConversationId === id ? null : state.currentConversationId,
      messages: state.currentConversationId === id ? [] : state.messages,
      isStreaming: state.currentConversationId === id ? false : state.isStreaming,
      activeStreamingConversationId:
        state.activeStreamingConversationId === id ? null : state.activeStreamingConversationId,
      streamingMessageId:
        state.currentConversationId === id ? null : state.streamingMessageId,
      streamingStatus: state.currentConversationId === id ? "" : state.streamingStatus,
    });
  },

  sendMessage: async (content: string, options?: SendMessageOptions) => {
    const state = get();
    if (
      !state.currentConversationId ||
      !state.sidecarReady ||
      activeStreams[state.currentConversationId]
    ) {
      return;
    }

    const conversationId = state.currentConversationId;
    const imagePaths = [...state.attachedImages];

    const userMessage: Message = {
      id: crypto.randomUUID(),
      role: "user",
      content,
      createdAt: new Date().toISOString(),
      images: imagePaths.length > 0 ? imagePaths : undefined,
    };

    set({ attachedImages: [] });

    const streamMsgId = crypto.randomUUID();
    const streamCreatedAt = new Date().toISOString();
    const streamPlaceholder: Message = {
      id: streamMsgId,
      role: "assistant",
      content: "",
      createdAt: streamCreatedAt,
    };
    activeStreams[conversationId] = {
      conversationId,
      messageId: streamMsgId,
      content: "",
      createdAt: streamCreatedAt,
      toolEvents: [],
      status: "",
    };

    set((s) => {
      const baseMessages = options?.removeMessageId
        ? s.messages.filter((message) => message.id !== options.removeMessageId)
        : s.messages;
      return {
        messages: options?.hideUserMessage
          ? [...baseMessages, streamPlaceholder]
          : [...baseMessages, userMessage, streamPlaceholder],
        isStreaming: true,
        activeStreamingConversationId: conversationId,
        streamingMessageId: streamMsgId,
        streamingStatus: "",
      };
    });

    let fullContent = "";

    const unlistenChunk = await listen<{ conversationId?: string; token: string }>(
      "chat-chunk",
      (event) => {
        if (event.payload.conversationId !== conversationId) return;
        fullContent += event.payload.token;
        const stream = activeStreams[conversationId];
        if (stream) {
          stream.content = fullContent;
        }
        if (get().currentConversationId !== conversationId) return;
        set((s) => ({
          messages: s.messages.map((m) =>
            m.id === streamMsgId ? { ...m, content: fullContent } : m
          ),
        }));
      }
    );

    const unlistenStatus = await listen<{ conversationId?: string; status?: string; description?: string }>(
      "chat-status",
      (event) => {
        if (event.payload.conversationId !== conversationId) return;
        const status = event.payload.description || event.payload.status || "";
        const stream = activeStreams[conversationId];
        if (!stream) return;
        stream.status = status;
        const toolEvents = appendActivity(stream, status);
        if (get().currentConversationId !== conversationId) return;
        set((s) => ({
          streamingStatus: status,
          messages: s.messages.map((m) =>
            m.id === streamMsgId ? { ...m, toolEvents } : m
          ),
        }));
      }
    );

    const unlistenDone = await listen<{
      conversationId?: string;
      done?: boolean;
      message_id?: string;
      content?: string;
      saved_memories?: string[];
    }>("chat-done", (event) => {
      if (event.payload.conversationId !== conversationId) return;

      const savedMemories = event.payload?.saved_memories;
      if (savedMemories && savedMemories.length > 0) {
        set((s) => ({
          memoryNotifications: [
            ...s.memoryNotifications,
            ...savedMemories.map((m: string) => get().language === "zh" ? `\u5df2\u8bb0\u4f4f: ${m}` : `Remembered: ${m}`),
          ],
        }));
      }

      const finalContent = event.payload?.content ?? fullContent;
      const serverMessageId = event.payload?.message_id;
      const finalToolEvents = activeStreams[conversationId]?.toolEvents ?? [];
      if (serverMessageId && finalToolEvents.length > 0) {
        completedToolEvents[serverMessageId] = finalToolEvents;
      }
      delete activeStreams[conversationId];
      set((s) => {
        const isCurrentConversation = s.currentConversationId === conversationId;
        return {
          messages: isCurrentConversation
            ? s.messages.map((m) =>
                m.id === streamMsgId ? { ...m, id: serverMessageId || m.id, content: finalContent, toolEvents: finalToolEvents } : m
              )
            : s.messages,
          isStreaming: isCurrentConversation ? false : s.isStreaming,
          activeStreamingConversationId: isCurrentConversation ? null : s.activeStreamingConversationId,
          streamingMessageId: isCurrentConversation ? null : s.streamingMessageId,
          streamingStatus: isCurrentConversation ? "" : s.streamingStatus,
        };
      });

      get().loadConversations();
      cleanupListeners([unlistenChunk, unlistenStatus, unlistenDone, unlistenError]);
    });

    const unlistenError = await listen<{ conversationId?: string; error: string }>(
      "chat-error",
      (event) => {
        if (event.payload.conversationId !== conversationId) return;
        const errorContent = fullContent
          ? fullContent +
            (get().language === "zh" ? "\n\n[\u54cd\u5e94\u4e2d\u65ad \u2014 " : "\n\n[Response interrupted - ") +
            event.payload.error +
            "]"
          : (get().language === "zh" ? "[\u53d1\u9001\u5931\u8d25 \u2014 " : "[Send failed - ") + event.payload.error + "]";
        const finalToolEvents = activeStreams[conversationId]?.toolEvents ?? [];
        delete activeStreams[conversationId];
        if (get().currentConversationId !== conversationId) {
          cleanupListeners([unlistenChunk, unlistenStatus, unlistenDone, unlistenError]);
          return;
        }
        set((s) => ({
          messages: s.messages.map((m) =>
            m.id === streamMsgId ? { ...m, content: errorContent, toolEvents: finalToolEvents } : m
          ),
          isStreaming: false,
          activeStreamingConversationId: null,
          streamingMessageId: null,
          streamingStatus: "",
        }));
        cleanupListeners([unlistenChunk, unlistenStatus, unlistenDone, unlistenError]);
      }
    );

    try {
      await invoke("send_stream_start", {
        conversationId,
        content,
        imagePaths,
        permissionMode: state.permissionMode,
        modelId: state.modelConfig?.id ?? null,
        visionEnabled: state.visionEnabled,
        hiddenUserMessage: Boolean(options?.hideUserMessage),
        removeMessageId: options?.removeMessageId ?? null,
        projectPath:
          state.projects.find((project) => project.id === state.currentProjectId)?.rootPath ?? null,
      });
    } catch {
      cleanupListeners([unlistenChunk, unlistenStatus, unlistenDone, unlistenError]);
      const finalToolEvents = activeStreams[conversationId]?.toolEvents ?? [];
      delete activeStreams[conversationId];
      if (!fullContent) {
        try {
          const fallbackResult = await invoke<Message>("send_message", {
            conversationId,
            content,
            imagePaths,
            permissionMode: state.permissionMode,
            modelId: state.modelConfig?.id ?? null,
            visionEnabled: state.visionEnabled,
            hiddenUserMessage: Boolean(options?.hideUserMessage),
            removeMessageId: options?.removeMessageId ?? null,
            projectPath:
              state.projects.find((project) => project.id === state.currentProjectId)?.rootPath ?? null,
          });

          set((s) => ({
            messages: s.messages.map((m) =>
              m.id === streamMsgId
                ? { ...m, id: fallbackResult.id, content: fallbackResult.content, toolEvents: finalToolEvents }
                : m
            ),
            isStreaming: s.currentConversationId === conversationId ? false : s.isStreaming,
            activeStreamingConversationId: s.currentConversationId === conversationId ? null : s.activeStreamingConversationId,
            streamingMessageId: s.currentConversationId === conversationId ? null : s.streamingMessageId,
            streamingStatus: s.currentConversationId === conversationId ? "" : s.streamingStatus,
          }));
          get().loadConversations();
        } catch {
          set((s) => ({
            messages: s.messages.map((m) =>
              m.id === streamMsgId
                ? {
                    ...m,
                  toolEvents: finalToolEvents,
                  content:
                      get().language === "zh"
                        ? "[\u53d1\u9001\u5931\u8d25 \u2014 \u8bf7\u68c0\u67e5\u540e\u7aef\u670d\u52a1\u548c\u6a21\u578b\u914d\u7f6e]"
                        : "[Send failed - please check the backend service and model configuration]",
                  }
                : m
            ),
            isStreaming: s.currentConversationId === conversationId ? false : s.isStreaming,
            activeStreamingConversationId: s.currentConversationId === conversationId ? null : s.activeStreamingConversationId,
            streamingMessageId: s.currentConversationId === conversationId ? null : s.streamingMessageId,
            streamingStatus: s.currentConversationId === conversationId ? "" : s.streamingStatus,
          }));
        }
      } else {
        set((s) => ({
          messages: s.messages.map((m) =>
            m.id === streamMsgId ? { ...m, content: fullContent, toolEvents: finalToolEvents } : m
          ),
          isStreaming: s.currentConversationId === conversationId ? false : s.isStreaming,
          activeStreamingConversationId: s.currentConversationId === conversationId ? null : s.activeStreamingConversationId,
          streamingMessageId: s.currentConversationId === conversationId ? null : s.streamingMessageId,
          streamingStatus: s.currentConversationId === conversationId ? "" : s.streamingStatus,
        }));
      }
    }
  },

  clearMemoryNotification: () => {
    set((s) => ({
      memoryNotifications: s.memoryNotifications.slice(1),
    }));
  },

  setModelConfig: async (config: ModelConfig) => {
    set({ modelConfig: config });
  },

  loadModelConfigs: async () => {
    const models = await invoke<ModelConfig[]>("list_model_configs");
    const current = get().modelConfig;
    set({
      modelConfigs: models,
      modelConfig:
        models.find((model) => model.id === current?.id) ??
        models.find((model) => model.isDefault) ??
        models[0] ??
        null,
    });
  },

  selectModelConfig: async (id: string) => {
    const model = get().modelConfigs.find((item) => item.id === id) ?? null;
    if (model) set({ modelConfig: model });
  },

  setEmbeddingConfig: async (config: EmbeddingConfig) => {
    await invoke("set_embedding_config", { config });
    set({ embeddingConfig: config });
  },

  initSidecar: async () => {
    try {
      await invoke("init_sidecar");
      set({ sidecarReady: true });
      try {
        await get().loadModelConfigs();
      } catch (e) {
        console.error("Failed to load model config:", e);
      }
      get().loadPersona();
    } catch (e) {
      console.error("Failed to init sidecar:", e);
      throw e;
    }
  },
}));
