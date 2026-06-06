import { useEffect, useMemo, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import type { DiagnosticItem, DiagnosticsReport, DiagnosticStatus } from "../types";
import Icon from "./Icon";
import { useLanguage } from "../i18n";

const STATUS_META: Record<DiagnosticStatus, { label: [string, string]; color: string; bg: string; icon: "check" | "alert" }> = {
  ok: {
    label: ["正常", "OK"],
    color: "var(--success)",
    bg: "rgba(63,127,86,0.10)",
    icon: "check",
  },
  warn: {
    label: ["注意", "Warning"],
    color: "var(--accent-warm)",
    bg: "rgba(179,107,44,0.12)",
    icon: "alert",
  },
  error: {
    label: ["异常", "Error"],
    color: "var(--danger)",
    bg: "rgba(184,59,59,0.10)",
    icon: "alert",
  },
};

function formatTime(value: string, language: "zh" | "en") {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString(language === "zh" ? "zh-CN" : "en-US");
}

function localizeDiagnosticValue(value: string, language: "zh" | "en") {
  if (language === "zh") return value;
  const labels: Record<string, string> = {
    "本地数据库": "Local database",
    "聊天模型": "Chat model",
    "Embedding 模型": "Embedding model",
    "本地配置文件": "Local configuration file",
    "ComfyUI 路径": "ComfyUI path",
    "ComfyUI 运行状态": "ComfyUI runtime status",
    "生成输出目录": "Generation output folder",
  };
  if (labels[value]) return labels[value];
  return value
    .replace("后端服务已响应。", "Backend service responded.")
    .replace(/SQLite 可读写，路径：(.+)，会话 (\d+) 个，模型配置 (\d+) 个。/, "SQLite is readable and writable. Path: $1. Conversations: $2. Model configurations: $3.")
    .replace("SQLite 检查失败：", "SQLite check failed: ")
    .replace("确认 sidecar/data 目录可写，必要时备份后重建 agent.db。", "Ensure sidecar/data is writable; back up and rebuild agent.db if needed.")
    .replace("尚未配置聊天模型。", "No chat model is configured.")
    .replace(/已有 (\d+) 个聊天模型，但没有默认模型。/, "$1 chat models exist, but no default model is selected.")
    .replace(/已配置 (\d+) 个聊天模型，默认模型可用。/, "$1 chat models configured; the default model is available.")
    .replace("到设置 - 聊天中添加 OpenAI/Qwen/GLM 或本地模型。", "Add an OpenAI, Qwen, GLM, or local model under Settings - Chat.")
    .replace("在模型列表中选择一个默认模型。", "Select a default model from the model list.")
    .replace("模型配置读取失败：", "Failed to read model configuration: ")
    .replace("尚未配置 Embedding 模型，长期记忆检索质量可能受影响。", "No embedding model is configured; long-term memory retrieval quality may be affected.")
    .replace(/已有 (\d+) 个 Embedding 模型，但没有默认模型。/, "$1 embedding models exist, but no default model is selected.")
    .replace(/已配置 (\d+) 个 Embedding 模型。/, "$1 embedding models configured.")
    .replace("如需记忆检索，添加一个 Embedding 模型并设为默认。", "For memory retrieval, add an embedding model and set it as default.")
    .replace("选择一个默认 Embedding 模型。", "Select a default embedding model.")
    .replace("Embedding 配置读取失败：", "Failed to read embedding configuration: ")
    .replace("sidecar/config.ini 不存在。", "sidecar/config.ini does not exist.")
    .replace("运行 start.ps1 自动生成，或从 sidecar/config.example.ini 复制一份。", "Run start.ps1 to generate it, or copy sidecar/config.example.ini.")
    .replace("配置文件存在：", "Configuration file exists: ")
    .replace("尚未配置 ComfyUI 路径。", "No ComfyUI path is configured.")
    .replace("编辑 sidecar/config.ini 的 [ComfyUI] path。", "Edit the [ComfyUI] path in sidecar/config.ini.")
    .replace("路径无效：", "Invalid path: ")
    .replace("确认该目录包含 ComfyUI/main.py 或 main.py。", "Ensure the folder contains ComfyUI/main.py or main.py.")
    .replace("路径有效：", "Valid path: ")
    .replace("ComfyUI 已就绪。", "ComfyUI is ready.")
    .replace("端口已监听，但程序未确认完全就绪。", "The port is listening, but readiness is not confirmed.")
    .replace("稍等片刻后刷新，或查看 ComfyUI 日志。", "Refresh shortly, or review the ComfyUI logs.")
    .replace("ComfyUI 未运行，图片/3D 生成不可用。", "ComfyUI is not running; image and 3D generation are unavailable.")
    .replace("点击 ComfyUI 状态按钮启动，或手动启动 ComfyUI。", "Start it from the ComfyUI status button or launch ComfyUI manually.")
    .replace("ComfyUI 检查失败：", "ComfyUI check failed: ")
    .replace("输出目录可访问：", "Output folder is accessible: ")
    .replace("暂未检测到 ComfyUI 输出目录。", "No ComfyUI output folder was detected.")
    .replace("启动 ComfyUI 并完成一次生成后再刷新。", "Start ComfyUI, complete one generation, and refresh.")
    .replace("输出目录检查失败：", "Output folder check failed: ");
}

export default function DiagnosticsPanel() {
  const { language, text } = useLanguage();
  const [report, setReport] = useState<DiagnosticsReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = async () => {
    setLoading(true);
    setError(null);
    try {
      const next = await invoke<DiagnosticsReport>("get_diagnostics");
      setReport(next);
    } catch (e) {
      setError(typeof e === "string" ? e : e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
  }, []);

  const overall = report?.overall ?? "warn";
  const meta = STATUS_META[overall];
  const headline = useMemo(() => {
    if (!report) return loading ? text("正在检查运行环境", "Checking runtime environment") : text("尚未运行诊断", "Diagnostics not run yet");
    if (report.overall === "ok") return text("运行环境状态良好", "Runtime environment looks good");
    if (report.overall === "warn") return text("运行环境可用，但有事项需要注意", "Runtime works, with items needing attention");
    return text("检测到会影响使用的异常", "Issues affecting use were detected");
  }, [report, loading, language]);

  return (
    <section style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div className="surface" style={{ borderRadius: 14, padding: 14 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, minWidth: 0 }}>
            <div className="brand-mark" style={{ width: 34, height: 34, background: meta.bg, color: meta.color }}>
              <Icon name={meta.icon} size={17} />
            </div>
            <div style={{ minWidth: 0 }}>
              <div style={{ fontSize: 14, fontWeight: 820, color: "var(--text-primary)" }}>{headline}</div>
              <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 3 }}>
                {report ? text(`上次检查：${formatTime(report.checkedAt, language)}`, `Last checked: ${formatTime(report.checkedAt, language)}`) : text("检查 sidecar、数据库、模型、ComfyUI 和输出目录", "Check sidecar, database, models, ComfyUI, and output folder")}
              </div>
            </div>
          </div>
          <button className="tool-button" onClick={refresh} disabled={loading} style={{ height: 34 }}>
            <Icon name="refresh" size={14} />
            {loading ? text("检查中", "Checking") : text("刷新", "Refresh")}
          </button>
        </div>

        {report && (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 8, marginTop: 12 }}>
            <SummaryTile label={text("正常", "OK")} value={report.summary.ok} color="var(--success)" />
            <SummaryTile label={text("注意", "Warning")} value={report.summary.warn} color="var(--accent-warm)" />
            <SummaryTile label={text("异常", "Error")} value={report.summary.error} color="var(--danger)" />
          </div>
        )}

        {error && (
          <div style={{ marginTop: 12, padding: "9px 10px", borderRadius: 10, background: "rgba(184,59,59,0.10)", color: "var(--danger)", fontSize: 12, lineHeight: 1.55 }}>
            {error}
          </div>
        )}
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {(report?.items ?? []).map((item) => (
          <DiagnosticRow key={item.id} item={item} />
        ))}
      </div>
    </section>
  );
}

function SummaryTile({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div style={{ border: "1px solid var(--border-subtle)", borderRadius: 10, padding: "8px 9px", background: "rgba(255,254,250,0.55)" }}>
      <div style={{ fontSize: 10, color: "var(--text-muted)", marginBottom: 2 }}>{label}</div>
      <div style={{ fontSize: 17, fontWeight: 820, color }}>{value}</div>
    </div>
  );
}

function DiagnosticRow({ item }: { item: DiagnosticItem }) {
  const { language, text } = useLanguage();
  const meta = STATUS_META[item.status];
  return (
    <div className="surface" style={{ borderRadius: 12, padding: 12, display: "flex", gap: 10 }}>
      <div style={{ width: 26, height: 26, borderRadius: 9, background: meta.bg, color: meta.color, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
        <Icon name={meta.icon} size={14} />
      </div>
      <div style={{ minWidth: 0, flex: 1 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
          <span style={{ fontSize: 13, fontWeight: 780, color: "var(--text-primary)" }}>{localizeDiagnosticValue(item.label, language)}</span>
          <span style={{ fontSize: 10, fontWeight: 760, color: meta.color, background: meta.bg, borderRadius: 999, padding: "2px 7px" }}>
            {meta.label[language === "zh" ? 0 : 1]}
          </span>
        </div>
        <div style={{ fontSize: 12, color: "var(--text-secondary)", lineHeight: 1.55, wordBreak: "break-word" }}>{localizeDiagnosticValue(item.detail, language)}</div>
        {item.action && (
          <div style={{ fontSize: 11, color: "var(--text-muted)", lineHeight: 1.5, marginTop: 5 }}>
            {text("建议：", "Suggestion: ")}{localizeDiagnosticValue(item.action, language)}
          </div>
        )}
      </div>
    </div>
  );
}
