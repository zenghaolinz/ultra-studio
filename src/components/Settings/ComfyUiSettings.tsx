import type { CSSProperties } from "react";
import type { ComfyUiLaunchMode, ComfyUiProfile, ComfyUiStatus } from "../../types";
import { useLanguage } from "../../i18n";
import Icon from "../Icon";

type Props = {
  profiles: ComfyUiProfile[];
  status: ComfyUiStatus | null;
  name: string;
  path: string;
  launchMode: ComfyUiLaunchMode;
  busy: boolean;
  inputStyle: CSSProperties;
  onNameChange: (v: string) => void;
  onPathChange: (v: string) => void;
  onLaunchModeChange: (v: ComfyUiLaunchMode) => void;
  onBrowse: () => void;
  onSave: () => void;
  onSelect: (id: string) => void;
  onStart: () => void;
  onStop: () => void;
  onRefresh: () => void;
};

export default function ComfyUiSettings({
  profiles,
  status,
  name,
  path,
  launchMode,
  busy,
  inputStyle,
  onNameChange,
  onPathChange,
  onLaunchModeChange,
  onBrowse,
  onSave,
  onSelect,
  onStart,
  onStop,
  onRefresh,
}: Props) {
  const { text } = useLanguage();
  const selected = profiles.find((p) => p.selected);
  const selectedLaunchMode = selected?.launch_mode || launchMode;
  const selectedIsExternal = selectedLaunchMode === "external";
  const stateLabel = status?.ready
    ? text("已就绪", "Ready")
    : status?.running || status?.process_alive
      ? text("启动中", "Starting")
      : text("未启动", "Stopped");
  const stateColor = status?.ready
    ? "var(--success)"
    : status?.running || status?.process_alive
      ? "var(--accent-warm)"
      : "var(--text-muted)";

  return (
    <section style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <div className="surface" style={{ borderRadius: 14, padding: 14 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, marginBottom: 10 }}>
          <div>
            <div style={{ fontSize: 13, fontWeight: 780 }}>{text("运行状态", "Runtime status")}</div>
            <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 3 }}>
              {selected ? `${selected.name} · ${selected.path}` : text("尚未选择版本", "No version selected")}
            </div>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span style={{ width: 8, height: 8, borderRadius: "50%", background: stateColor }} />
            <span style={{ fontSize: 12, fontWeight: 760, color: stateColor }}>{stateLabel}</span>
          </div>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 12 }}>
          <StatusPill label={text("端口", "Port")} value={status?.running ? text("8188 已监听", "8188 listening") : text("未监听", "Not listening")} ok={!!status?.running} />
          <StatusPill
            label={text("模式", "Mode")}
            value={selectedIsExternal ? text("Desktop/外部", "Desktop/external") : text("Portable", "Portable")}
            ok={!selectedIsExternal || !!status?.running}
          />
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 8 }}>
          <button className="primary-button" onClick={onStart} disabled={busy || status?.ready || !selected} style={{ height: 36 }}>
            <Icon name="play" size={15} />
            {selectedIsExternal ? text("检测", "Check") : text("启动", "Start")}
          </button>
          <button className="tool-button" onClick={onStop} disabled={busy || selectedIsExternal || !status?.process_alive} style={{ height: 36 }}>
            <Icon name="stop" size={14} />
            {text("停止", "Stop")}
          </button>
          <button className="tool-button" onClick={onRefresh} disabled={busy} style={{ height: 36 }}>
            <Icon name="refresh" size={14} />
            {text("刷新", "Refresh")}
          </button>
        </div>
      </div>

      <div className="surface" style={{ borderRadius: 14, padding: 14, display: "flex", flexDirection: "column", gap: 8 }}>
        <div style={{ fontSize: 13, fontWeight: 780 }}>{text("ComfyUI 版本", "ComfyUI versions")}</div>
        {profiles.length > 0 ? (
          profiles.map((profile) => (
            <button
              key={profile.id}
              className="tool-button"
              onClick={() => onSelect(profile.id)}
              disabled={busy}
              style={{
                minHeight: 42,
                height: "auto",
                justifyContent: "flex-start",
                padding: "8px 10px",
                background: profile.selected ? "var(--accent-muted)" : "rgba(255,254,250,0.54)",
              }}
            >
              <span style={{ width: 8, height: 8, borderRadius: "50%", background: profile.valid ? "var(--success)" : "var(--danger)", flexShrink: 0 }} />
              <span style={{ minWidth: 0, textAlign: "left" }}>
                <span style={{ display: "block", fontSize: 12, fontWeight: 760 }}>{profile.name}</span>
                <span style={{ display: "block", fontSize: 11, color: "var(--text-muted)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {(profile.launch_mode || "portable") === "external" ? text("Desktop/外部 · ", "Desktop/external · ") : text("Portable · ", "Portable · ")}
                  {profile.path}
                </span>
              </span>
            </button>
          ))
        ) : (
          <div style={{ fontSize: 12, color: "var(--text-muted)", lineHeight: 1.6 }}>
            {text("添加一个 ComfyUI 目录后再启动。应用启动时不会自动启动 ComfyUI。", "Add a ComfyUI folder before starting. The app no longer auto-starts ComfyUI.")}
          </div>
        )}
      </div>

      <div className="surface" style={{ borderRadius: 14, padding: 14, display: "flex", flexDirection: "column", gap: 8 }}>
        <div style={{ fontSize: 13, fontWeight: 780 }}>{text("添加或更新版本", "Add or update version")}</div>
        <input style={inputStyle} value={name} onChange={(e) => onNameChange(e.target.value)} placeholder={text("版本名称，例如 4B 快速版 / 9B 高质量版", "Version name, e.g. 4B Fast or 9B Quality")} />
        <select value={launchMode} onChange={(e) => onLaunchModeChange(e.target.value as ComfyUiLaunchMode)} style={inputStyle}>
          <option value="portable">{text("Portable：应用可启动该目录", "Portable: app can launch this folder")}</option>
          <option value="external">{text("Desktop/外部：只检测手动启动的服务", "Desktop/external: only detect a manually started service")}</option>
        </select>
        <div style={{ display: "flex", gap: 8 }}>
          <input style={{ ...inputStyle, flex: 1 }} value={path} onChange={(e) => onPathChange(e.target.value)} placeholder={text("ComfyUI Windows Portable 目录", "ComfyUI Windows Portable folder")} />
          <button className="tool-button" onClick={onBrowse} disabled={busy} style={{ height: 36, padding: "0 10px" }}>
            <Icon name="file" size={14} />
            {text("选择", "Choose")}
          </button>
        </div>
        <button className="primary-button" onClick={onSave} disabled={busy} style={{ height: 36 }}>
          <Icon name="check" size={15} />
          {text("保存并选中", "Save and select")}
        </button>
      </div>

      {status?.recent_logs && status.recent_logs.length > 0 && (
        <div
          style={{
            maxHeight: 170,
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
          {status.recent_logs.slice(-10).join("\n")}
        </div>
      )}
    </section>
  );
}

function StatusPill({ label, value, ok }: { label: string; value: string; ok: boolean }) {
  return (
    <div style={{ border: "1px solid var(--border-subtle)", borderRadius: 10, padding: "8px 10px" }}>
      <div style={{ fontSize: 11, color: "var(--text-muted)", marginBottom: 3 }}>{label}</div>
      <div style={{ fontSize: 12, color: ok ? "var(--success)" : "var(--text-secondary)", fontWeight: 700 }}>{value}</div>
    </div>
  );
}
