import { useEffect, useMemo, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import type { ComfyUiStatus } from "../types";
import Icon from "./Icon";
import { useLanguage } from "../i18n";

function labelFor(status: ComfyUiStatus | null, loading: boolean, language: "zh" | "en") {
  const text = (zh: string, en: string) => language === "zh" ? zh : en;
  if (loading && !status) return { text: text("检测中", "Checking"), color: "var(--text-muted)", bg: "var(--accent-muted)" };
  if (!status) return { text: text("未知", "Unknown"), color: "var(--text-muted)", bg: "var(--accent-muted)" };
  if (status.error) return { text: text("异常", "Error"), color: "var(--danger)", bg: "rgba(184,59,59,0.10)" };
  if (status.ready) return { text: text("已就绪", "Ready"), color: "var(--success)", bg: "rgba(63,127,86,0.12)" };
  if (status.running || status.process_alive) return { text: text("启动中", "Starting"), color: "var(--accent-warm)", bg: "rgba(179,107,44,0.13)" };
  return { text: text("未启动", "Stopped"), color: "var(--danger)", bg: "rgba(184,59,59,0.10)" };
}

export default function ComfyStatus() {
  const { language, text } = useLanguage();
  const [status, setStatus] = useState<ComfyUiStatus | null>(null);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [starting, setStarting] = useState(false);

  const refresh = async () => {
    setLoading(true);
    try {
      const next = await invoke<ComfyUiStatus>("get_comfyui_status");
      setStatus(next);
    } catch (e) {
      setStatus({ error: typeof e === "string" ? e : String(e) });
    } finally {
      setLoading(false);
    }
  };

  const start = async () => {
    setStarting(true);
    try {
      const next = await invoke<ComfyUiStatus>("start_comfyui");
      setStatus(next);
      setOpen(true);
    } catch (e) {
      setStatus({ error: typeof e === "string" ? e : String(e) });
      setOpen(true);
    } finally {
      setStarting(false);
    }
  };

  useEffect(() => {
    refresh();
    const timer = window.setInterval(refresh, 5000);
    return () => window.clearInterval(timer);
  }, []);

  const badge = useMemo(() => labelFor(status, loading, language), [status, loading, language]);
  const logs = status?.recent_logs || [];

  return (
    <div style={{ position: "relative" }}>
      <button
        className="tool-button"
        onClick={() => setOpen((v) => !v)}
        title={text("ComfyUI 状态", "ComfyUI status")}
        style={{
          height: 34,
          background: badge.bg,
          color: badge.color,
          borderColor: "transparent",
        }}
      >
        <span
          style={{
            width: 8,
            height: 8,
            borderRadius: "50%",
            background: badge.color,
            boxShadow: status?.ready ? "0 0 0 4px rgba(63,127,86,0.12)" : "none",
          }}
        />
        ComfyUI {badge.text}
      </button>

      {open && (
        <div
          className="surface anim-fade-in"
          style={{
            position: "absolute",
            right: 0,
            top: 42,
            width: 430,
            maxWidth: "calc(100vw - 32px)",
            borderRadius: 14,
            padding: 14,
            zIndex: 40,
            background: "var(--bg-elevated)",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, marginBottom: 10 }}>
            <div>
              <div style={{ fontSize: 14, fontWeight: 800, color: "var(--text-primary)" }}>
                {text("ComfyUI 状态", "ComfyUI status")}: {badge.text}
              </div>
              <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 3 }}>
                {status?.configured_path ? text("已配置工作目录", "Working directory configured") : text("未配置路径", "No path configured")}
              </div>
            </div>
            <div style={{ display: "flex", gap: 6 }}>
              <button className="icon-button" onClick={refresh} title={text("刷新", "Refresh")} disabled={loading}>
                <Icon name="refresh" size={15} />
              </button>
              <button className="tool-button" onClick={start} disabled={starting || status?.ready} style={{ height: 34 }}>
                <Icon name="play" size={14} />
                {starting ? text("启动中", "Starting") : text("启动", "Start")}
              </button>
            </div>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 10 }}>
            <StatusItem label={text("端口", "Port")} value={status?.running ? text("8188 已监听", "8188 listening") : text("未监听", "Not listening")} ok={!!status?.running} />
            <StatusItem label={text("进程", "Process")} value={status?.process_alive ? text("由程序管理", "Managed by app") : text("未跟踪", "Not tracked")} ok={!!status?.process_alive || !!status?.ready} />
          </div>

          {status?.error && (
            <div style={{ color: "var(--danger)", fontSize: 12, lineHeight: 1.55, marginBottom: 10 }}>
              {status.error}
            </div>
          )}

          <div style={{ fontSize: 12, fontWeight: 760, marginBottom: 6 }}>{text("最近日志", "Recent logs")}</div>
          <div
            style={{
              maxHeight: 210,
              overflow: "auto",
              padding: 10,
              borderRadius: 10,
              background: "var(--bg-input)",
              color: "var(--text-secondary)",
              fontFamily: "Consolas, monospace",
              fontSize: 11,
              lineHeight: 1.55,
              whiteSpace: "pre-wrap",
            }}
          >
            {logs.length > 0 ? logs.slice(-12).join("\n") : text("暂无日志", "No logs")}
          </div>
        </div>
      )}
    </div>
  );
}

function StatusItem({ label, value, ok }: { label: string; value: string; ok: boolean }) {
  return (
    <div style={{ border: "1px solid var(--border-subtle)", borderRadius: 10, padding: "8px 10px" }}>
      <div style={{ fontSize: 11, color: "var(--text-muted)", marginBottom: 3 }}>{label}</div>
      <div style={{ fontSize: 12, color: ok ? "var(--success)" : "var(--text-secondary)", fontWeight: 700 }}>
        {value}
      </div>
    </div>
  );
}
