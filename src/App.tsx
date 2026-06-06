import { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { useAppStore } from "./stores/appStore";
import ConversationList from "./components/ConversationList";
import ChatPanel from "./components/ChatPanel";
import ImageStudio from "./components/ImageStudio";
import ThreeDStudio from "./components/ThreeDStudio";
import Settings from "./components/Settings";
import Icon from "./components/Icon";
import ComfyStatus from "./components/ComfyStatus";
import { useLanguage } from "./i18n";

function errorMessage(e: unknown) {
  return typeof e === "string" ? e : e instanceof Error ? e.message : String(e);
}

export default function App() {
  const { text } = useLanguage();
  const [showSettings, setShowSettings] = useState(false);
  const [sidecarError, setSidecarError] = useState<string | null>(null);
  const {
    initSidecar,
    sidecarReady,
    workspace,
    loadConversations,
    loadProjects,
    showPersonaModal,
    dismissPersonaModal,
    personaContent,
  } = useAppStore();

  useEffect(() => {
    initSidecar().catch((e: unknown) => setSidecarError(errorMessage(e)));
  }, [initSidecar]);

  useEffect(() => {
    if (sidecarReady) {
      loadProjects();
      loadConversations();
    }
  }, [sidecarReady, loadConversations, loadProjects]);

  const retrySidecar = () => {
    setSidecarError(null);
    initSidecar().catch((e: unknown) => setSidecarError(errorMessage(e)));
  };

  if (sidecarError) {
    return (
      <div className="app-shell" style={{ alignItems: "center", justifyContent: "center" }}>
        <div className="surface" style={{ width: 430, borderRadius: 18, padding: 28, textAlign: "center" }}>
          <div className="brand-mark" style={{ margin: "0 auto 18px" }}>
            <Icon name="alert" size={18} />
          </div>
          <h2 style={{ fontSize: 18, fontWeight: 750, marginBottom: 8 }}>{text("无法连接后端服务", "Unable to connect to backend service")}</h2>
          <p style={{ color: "var(--text-secondary)", fontSize: 13, lineHeight: 1.7, marginBottom: 18 }}>
            {text("请确认 Python Sidecar 已启动，然后重新连接。", "Make sure the Python Sidecar is running, then reconnect.")}
          </p>
          <code
            style={{
              display: "block",
              padding: "10px 14px",
              borderRadius: 10,
              background: "var(--bg-input)",
              color: "var(--text-primary)",
              fontSize: 12,
              marginBottom: 18,
            }}
          >
            cd sidecar && python main.py
          </code>
          <button className="primary-button" onClick={retrySidecar} style={{ height: 38, padding: "0 22px" }}>
            <Icon name="refresh" size={16} />
            {text("重新连接", "Reconnect")}
          </button>
        </div>
      </div>
    );
  }

  if (!sidecarReady) {
    return (
      <div className="app-shell" style={{ alignItems: "center", justifyContent: "center" }}>
        <div style={{ textAlign: "center" }}>
          <div className="brand-mark" style={{ margin: "0 auto 18px" }}>
            <Icon name="cube" size={18} />
          </div>
          <div style={{ marginBottom: 12 }}>
            <span className="typing-dot" />
            <span className="typing-dot" />
            <span className="typing-dot" />
          </div>
          <p style={{ color: "var(--text-muted)", fontSize: 13 }}>{text("正在连接后端服务", "Connecting to backend service")}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="app-shell">
      <aside
        style={{
          width: 278,
          flexShrink: 0,
          background: "rgba(238, 236, 230, 0.84)",
          borderRight: "1px solid var(--border-subtle)",
          display: "flex",
          flexDirection: "column",
        }}
      >
        <ConversationList />
      </aside>

      <main style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
        {workspace === "agent" && (
          <>
            <header
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                padding: "0 18px",
                height: 54,
                flexShrink: 0,
                borderBottom: "1px solid var(--border-subtle)",
                background: "rgba(255, 254, 250, 0.72)",
              }}
            >
              <div style={{ fontSize: 13, color: "var(--text-muted)", fontWeight: 650 }}>{text("Agent 工作区", "Agent Workspace")}</div>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <ComfyStatus />
                <button className="tool-button" onClick={() => setShowSettings(!showSettings)} title={text("设置", "Settings")}>
                  <Icon name="settings" size={15} />
                  {text("设置", "Settings")}
                </button>
              </div>
            </header>
            <div style={{ flex: 1, overflow: "hidden" }}>
              <ChatPanel />
            </div>
          </>
        )}

        {workspace === "image_studio" && <ImageStudio />}
        {workspace === "3d_studio" && <ThreeDStudio />}
      </main>

      {showSettings && workspace === "agent" && (
        <aside
          className="anim-fade-in"
          style={{
            width: 560,
            flexShrink: 0,
            background: "rgba(255, 254, 250, 0.92)",
            borderLeft: "1px solid var(--border-subtle)",
            overflow: "hidden",
          }}
        >
          <Settings onClose={() => setShowSettings(false)} />
        </aside>
      )}

      {showPersonaModal && !showSettings && workspace === "agent" && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(23, 22, 21, 0.42)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 100,
          }}
        >
          <div className="surface" style={{ borderRadius: 18, padding: 28, maxWidth: 500, width: "90%" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 16 }}>
              <div className="brand-mark">
                <Icon name="bot" size={18} />
              </div>
              <div>
                <h2 style={{ fontSize: 18, fontWeight: 760, color: "var(--text-primary)", margin: 0 }}>
                  {text("设置你的 AI 助手", "Set up your AI assistant")}
                </h2>
                <p style={{ fontSize: 12, color: "var(--text-muted)", margin: "3px 0 0" }}>
                  {text("这会影响之后每个对话的默认行为。", "This affects the default behavior of future conversations.")}
                </p>
              </div>
            </div>
            <textarea
              value={personaContent}
              onChange={(e) => useAppStore.setState({ personaContent: e.target.value })}
              placeholder={text("描述你希望 AI 助手扮演的角色、性格和专业领域...", "Describe the role, personality, and expertise you want from the AI assistant...")}
              rows={6}
              style={{
                width: "100%",
                padding: "12px",
                borderRadius: 12,
                background: "var(--bg-input)",
                border: "1px solid var(--border-subtle)",
                color: "var(--text-primary)",
                fontSize: 13,
                lineHeight: 1.6,
                resize: "vertical",
                outline: "none",
                marginBottom: 12,
              }}
            />
            <div style={{ display: "flex", gap: 8 }}>
              <button
                className="primary-button"
                onClick={async () => {
                  try {
                    await invoke("update_persona", { content: personaContent });
                    useAppStore.setState({ personaContent });
                  } catch {}
                  dismissPersonaModal();
                }}
                style={{ flex: 1, height: 38 }}
              >
                {text("确认", "Confirm")}
              </button>
              <button className="tool-button" onClick={() => dismissPersonaModal()} style={{ flex: 1, height: 38 }}>
                {text("稍后再说", "Later")}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
