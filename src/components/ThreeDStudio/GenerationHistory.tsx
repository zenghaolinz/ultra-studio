import { useCallback, useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { useGenerationTaskStore } from "../../stores/generationTaskStore";
import type { GenerationTask, GenerationTaskStatus } from "../../types";
import { useAppStore } from "../../stores/appStore";
import Icon from "../Icon";
import { useLanguage } from "../../i18n";

const TYPE_LABELS: Record<string, [string, string]> = {
  text_to_3d: ["文字生成 3D", "Text to 3D"],
  image_to_3d: ["图片转 3D", "Image to 3D"],
  fusion_to_3d: ["双图融合 3D", "Image fusion to 3D"],
  multiview_to_3d: ["多视角 Hy3D", "Multiview Hy3D"],
  improve_image: ["图片改进", "Image improvement"],
  generate_image: ["概念图生成", "Concept image"],
  generate_video: ["视频生成", "Video generation"],
  showcase_materials: ["展示材料", "Showcase materials"],
};

const STATUS_META: Record<GenerationTaskStatus, { label: [string, string]; color: string; bg: string }> = {
  queued: { label: ["排队中", "Queued"], color: "var(--accent-blue)", bg: "rgba(47,111,130,0.10)" },
  running: { label: ["运行中", "Running"], color: "var(--accent-warm)", bg: "rgba(179,107,44,0.12)" },
  success: { label: ["完成", "Complete"], color: "var(--success)", bg: "rgba(63,127,86,0.10)" },
  error: { label: ["失败", "Failed"], color: "var(--danger)", bg: "rgba(184,59,59,0.10)" },
  cancelled: { label: ["已取消", "Cancelled"], color: "var(--text-muted)", bg: "var(--accent-muted)" },
};

function formatTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function firstOutput(task: GenerationTask) {
  return (
    task.outputPaths.modelPath ||
    task.outputPaths.imagePath ||
    task.outputPaths.videoPath ||
    task.outputPaths.image2D ||
    task.outputPaths.path ||
    ""
  );
}

export default function GenerationHistory() {
  const { text } = useLanguage();
  const [showAll, setShowAll] = useState(false);
  const allTasks = useGenerationTaskStore((state) => state.tasks);
  const loading = useGenerationTaskStore((state) => !state.hydrated);
  const error = useGenerationTaskStore((state) => state.error);
  const hydrate = useGenerationTaskStore((state) => state.hydrate);
  const refresh = useCallback(() => void hydrate(), [hydrate]);
  const tasks = allTasks.slice(0, showAll ? 100 : 20);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const reusePrompt = (task: GenerationTask) => {
    if (task.prompt) {
      useAppStore.getState().setThreeDTextPrompt(task.prompt);
    }
    if (task.qualityMode === "fast" || task.qualityMode === "quality") {
      useAppStore.getState().setThreeDQuality(task.qualityMode);
    }
  };

  const restoreResult = (task: GenerationTask) => {
    const output = task.outputPaths;
    const nextState: Record<string, unknown> = {};
    if (output.modelPath) nextState.threeDModelPath = output.modelPath;
    if (output.image2D) nextState.threeDPreview2D = output.image2D;
    if (output.imageNormal) nextState.threeDPreviewNormal = output.imageNormal;
    if (output.imageUV) nextState.threeDPreviewUV = output.imageUV;
    if (output.imagePath) {
      nextState.threeDPreview2D = output.imagePath;
      useAppStore.getState().addThreeDImage(output.imagePath);
    }
    if (Object.keys(nextState).length > 0) {
      useAppStore.setState(nextState as any);
    }
  };

  const reveal = async (task: GenerationTask) => {
    const path = firstOutput(task);
    if (!path) return;
    try {
      await invoke("reveal_path", { path });
    } catch {}
  };

  return (
    <section className="surface" style={{ borderRadius: 14, padding: 12 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <Icon name="clock" size={15} />
          <b style={{ fontSize: 12 }}>{text("生成历史", "Generation history")}</b>
        </div>
        <button className="icon-button" onClick={refresh} disabled={loading} title={text("刷新", "Refresh")} style={{ width: 28, height: 28 }}>
          <Icon name="refresh" size={13} />
        </button>
        {allTasks.length > 20 && (
          <button className="tool-button" onClick={() => setShowAll((value) => !value)} style={{ height: 28, fontSize: 10 }}>
            {showAll ? text("收起", "Collapse") : text("全部", "All")}
          </button>
        )}
      </div>

      {error && (
        <div style={{ fontSize: 11, color: "var(--danger)", lineHeight: 1.5, marginBottom: 8 }}>
          {error}
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 8, maxHeight: 360, overflowY: "auto" }}>
        {tasks.length === 0 ? (
          <div style={{ fontSize: 11, color: "var(--text-muted)", lineHeight: 1.55 }}>
            {text("还没有生成记录。完成一次图片、3D 或展示材料生成后会出现在这里。", "No generation records yet. Generated images, 3D assets, and showcase materials appear here.")}
          </div>
        ) : (
          tasks.map((task) => (
            <TaskRow
              key={task.id}
              task={task}
              onReuse={() => reusePrompt(task)}
              onRestore={() => restoreResult(task)}
              onReveal={() => reveal(task)}
            />
          ))
        )}
      </div>
    </section>
  );
}

function TaskRow({
  task,
  onReuse,
  onRestore,
  onReveal,
}: {
  task: GenerationTask;
  onReuse: () => void;
  onRestore: () => void;
  onReveal: () => void;
}) {
  const { language, text } = useLanguage();
  const status = STATUS_META[task.status] ?? STATUS_META.error;
  const output = firstOutput(task);
  const canRestore = !!(
    task.outputPaths.modelPath ||
    task.outputPaths.imagePath ||
    task.outputPaths.image2D
  );

  return (
    <div style={{ border: "1px solid var(--border-subtle)", borderRadius: 11, padding: 9, background: "rgba(255,254,250,0.54)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 7, marginBottom: 5 }}>
        <span style={{ fontSize: 11, fontWeight: 800, color: "var(--text-primary)", flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {TYPE_LABELS[task.taskType]?.[language === "zh" ? 0 : 1] ?? task.taskType}
        </span>
        <span style={{ fontSize: 10, fontWeight: 760, color: status.color, background: status.bg, borderRadius: 999, padding: "2px 7px" }}>
          {status.label[language === "zh" ? 0 : 1]}
        </span>
      </div>
      <div style={{ fontSize: 10, color: "var(--text-muted)", marginBottom: 5 }}>
        {formatTime(task.updatedAt)}
      </div>
      {task.error && (
        <div style={{ fontSize: 11, color: task.error ? "var(--danger)" : "var(--text-secondary)", lineHeight: 1.45, maxHeight: 47, overflow: "hidden", wordBreak: "break-word" }}>
          {task.error}
        </div>
      )}
      <div style={{ display: "flex", gap: 6, marginTop: 8 }}>
        <button className="tool-button" onClick={onReuse} disabled={!task.prompt} style={{ height: 28, padding: "0 8px", fontSize: 11 }}>
          {text("复用", "Reuse")}
        </button>
        <button className="tool-button" onClick={onRestore} disabled={!canRestore} style={{ height: 28, padding: "0 8px", fontSize: 11 }}>
          {text("恢复", "Restore")}
        </button>
        <button className="icon-button" onClick={onReveal} disabled={!output} title={text("打开位置", "Open location")} style={{ width: 28, height: 28 }}>
          <Icon name="file" size={13} />
        </button>
      </div>
    </div>
  );
}
