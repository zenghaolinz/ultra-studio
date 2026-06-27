import { useMemo, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { useGenerationTaskStore } from "../../stores/generationTaskStore";
import type { GenerationTaskStatus } from "../../types";
import Icon from "../Icon";
import { useLanguage } from "../../i18n";

type Filter = "all" | GenerationTaskStatus;

export default function GenerationTaskCenter({ onClose }: { onClose: () => void }) {
  const { text } = useLanguage();
  const [filter, setFilter] = useState<Filter>("all");
  const [busyTaskId, setBusyTaskId] = useState("");
  const [actionError, setActionError] = useState("");
  const tasks = useGenerationTaskStore((state) => state.tasks);
  const hydrate = useGenerationTaskStore((state) => state.hydrate);
  const cancelTask = useGenerationTaskStore((state) => state.cancelTask);
  const retryTask = useGenerationTaskStore((state) => state.retryTask);
  const visible = useMemo(
    () => tasks.filter((task) => filter === "all" || task.status === filter),
    [filter, tasks],
  );
  const filterLabels: Record<Filter, string> = {
    all: text("全部", "All"), queued: text("排队", "Queued"), running: text("运行中", "Running"),
    success: text("完成", "Complete"), error: text("失败", "Failed"), cancelled: text("已取消", "Cancelled"),
  };
  const runAction = async (taskId: string, action: () => Promise<unknown>) => {
    setBusyTaskId(taskId);
    setActionError("");
    try {
      await action();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : String(error));
    } finally {
      setBusyTaskId("");
    }
  };

  return (
    <aside className="generation-task-center surface anim-fade-in">
      <header className="generation-task-center__header">
        <div><b>{text("生成任务中心", "Generation task center")}</b><small>{text(`${tasks.length} 个任务`, `${tasks.length} tasks`)}</small></div>
        <button className="icon-button" onClick={onClose}><Icon name="close" size={15} /></button>
      </header>
      <div className="generation-task-center__filters">
        {(["all", "queued", "running", "success", "error", "cancelled"] as Filter[]).map((value) => (
          <button key={value} className={filter === value ? "primary-button" : "tool-button"} onClick={() => setFilter(value)}>{filterLabels[value]}</button>
        ))}
        <button className="icon-button" onClick={() => void hydrate()} title={text("刷新", "Refresh")}><Icon name="refresh" size={13} /></button>
      </div>
      {actionError && <p className="generation-task-center__banner">{actionError}</p>}
      <div className="generation-task-center__list">
        {visible.length === 0 && <p>{text("没有符合条件的任务。", "No matching tasks.")}</p>}
        {visible.map((task) => {
          const output = task.outputPaths.modelPath || task.outputPaths.imagePath || task.outputPaths.videoPath || task.outputPaths.path;
          const canCancel = task.status === "queued" || task.status === "running";
          const canRetry = (task.status === "error" || task.status === "cancelled") && Object.keys(task.requestPayload).length > 0;
          return (
            <article key={task.id} className="generation-task-center__row">
              <div className="generation-task-center__title"><b>{task.taskType.replaceAll("_", " ")}</b><span data-status={task.status}>{task.status}</span></div>
              <small>{new Date(task.updatedAt).toLocaleString()}{task.queuePosition != null ? ` · #${task.queuePosition}` : ""}</small>
              {task.prompt && <p>{task.prompt}</p>}
              {task.error && <p className="generation-task-center__error">{task.error}</p>}
              <div className="generation-task-center__actions">
                {canCancel && <button className="tool-button" disabled={busyTaskId === task.id} onClick={() => void runAction(task.id, () => cancelTask(task.id))}>{text("取消", "Cancel")}</button>}
                {canRetry && <button className="tool-button" disabled={busyTaskId === task.id} onClick={() => void runAction(task.id, () => retryTask(task.id))}>{text("重试", "Retry")}</button>}
                {output && <button className="tool-button" onClick={() => void invoke("reveal_path", { path: output })}>{text("打开位置", "Reveal")}</button>}
              </div>
            </article>
          );
        })}
      </div>
    </aside>
  );
}
