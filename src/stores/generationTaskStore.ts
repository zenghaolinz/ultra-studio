import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import { create } from "zustand";
import type { GenerationTask } from "../types";

interface GenerationTaskState {
  tasks: GenerationTask[];
  hydrated: boolean;
  connected: boolean;
  error: string;
  hydrate: () => Promise<void>;
  initialize: () => Promise<void>;
  cancelTask: (taskId: string) => Promise<void>;
  retryTask: (taskId: string) => Promise<GenerationTask>;
}

let initialization: Promise<void> | null = null;
let unlisteners: UnlistenFn[] = [];

function mergeTask(tasks: GenerationTask[], incoming: GenerationTask) {
  const current = tasks.find((task) => task.id === incoming.id);
  if (current && new Date(current.updatedAt).getTime() > new Date(incoming.updatedAt).getTime()) {
    return tasks;
  }
  return [incoming, ...tasks.filter((task) => task.id !== incoming.id)].sort(
    (left, right) => new Date(right.updatedAt).getTime() - new Date(left.updatedAt).getTime(),
  );
}

export const useGenerationTaskStore = create<GenerationTaskState>((set, get) => ({
  tasks: [],
  hydrated: false,
  connected: false,
  error: "",

  hydrate: async () => {
    try {
      const tasks = await invoke<GenerationTask[]>("list_generation_tasks", { limit: 100 });
      set({ tasks, hydrated: true, connected: true, error: "" });
    } catch (error) {
      set({ connected: false, error: error instanceof Error ? error.message : String(error) });
    }
  },

  initialize: async () => {
    if (initialization) return initialization;
    initialization = (async () => {
      unlisteners = [
        await listen<GenerationTask>("generation-task-updated", (event) => {
          set((state) => ({
            tasks: mergeTask(state.tasks, event.payload),
            connected: true,
            error: "",
          }));
        }),
        await listen("generation-task-resync", () => {
          void get().hydrate();
        }),
      ];
      await get().hydrate();
    })().catch((error) => {
      initialization = null;
      unlisteners.forEach((unlisten) => unlisten());
      unlisteners = [];
      throw error;
    });
    return initialization;
  },

  cancelTask: async (taskId) => {
    const task = await invoke<GenerationTask>("cancel_generation_task", { taskId });
    set((state) => ({ tasks: mergeTask(state.tasks, task) }));
  },

  retryTask: async (taskId) => {
    const task = await invoke<GenerationTask>("retry_generation_task", { taskId });
    set((state) => ({ tasks: mergeTask(state.tasks, task) }));
    return task;
  },
}));
