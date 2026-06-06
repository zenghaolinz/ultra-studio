import { useCallback, useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { open } from "@tauri-apps/plugin-dialog";
import type { ComfyUiLaunchMode, ComfyUiProfile, ComfyUiProfilesResponse, ComfyUiStatus, EmbeddingConfig, LocalProvider, ModelConfig, Persona, ProviderType } from "../../types";
import { PROVIDER_PRESETS } from "../../types";
import Icon from "../Icon";
import { useAppStore } from "../../stores/appStore";
import DiagnosticsPanel from "../DiagnosticsPanel";
import { useLanguage } from "../../i18n";

interface Props {
  onClose: () => void;
}

const PROVIDER_LABELS: Record<string, string> = {
  openai: "OpenAI",
  deepseek: "DeepSeek",
  qwen: "Qwen",
  glm: "GLM",
  ollama: "Ollama",
  llama_cpp: "llama.cpp",
  lmstudio: "LM Studio",
};

export default function Settings({ onClose }: Props) {
  const { language, text } = useLanguage();
  const [tab, setTab] = useState<"persona" | "chat" | "embedding" | "comfyui" | "memory" | "diagnostics">("chat");
  const [models, setModels] = useState<ModelConfig[]>([]);
  const [embeddings, setEmbeddings] = useState<EmbeddingConfig[]>([]);
  const [toast, setToast] = useState<string | null>(null);
  const loadModelConfigs = useAppStore((s) => s.loadModelConfigs);
  const selectModelConfig = useAppStore((s) => s.selectModelConfig);

  const [personaContent, setPersonaContent] = useState("");
  const [chatProvider, setChatProvider] = useState<ProviderType>("openai");
  const [chatModelName, setChatModelName] = useState("");
  const [chatApiKey, setChatApiKey] = useState("");
  const [chatBaseUrl, setChatBaseUrl] = useState(PROVIDER_PRESETS.openai.baseUrl);

  const [embProvider, setEmbProvider] = useState<ProviderType>("openai");
  const [embModelName, setEmbModelName] = useState("");
  const [embApiKey, setEmbApiKey] = useState("");
  const [embBaseUrl, setEmbBaseUrl] = useState(PROVIDER_PRESETS.openai.baseUrl);
  const [embDimensions, setEmbDimensions] = useState(768);

  const [localProviders, setLocalProviders] = useState<LocalProvider[]>([]);
  const [detecting, setDetecting] = useState(false);
  const [comfyProfiles, setComfyProfiles] = useState<ComfyUiProfile[]>([]);
  const [comfyStatus, setComfyStatus] = useState<ComfyUiStatus | null>(null);
  const [comfyName, setComfyName] = useState("Default");
  const [comfyPath, setComfyPath] = useState("");
  const [comfyLaunchMode, setComfyLaunchMode] = useState<ComfyUiLaunchMode>("portable");
  const [comfyBusy, setComfyBusy] = useState(false);

  const showToast = (msg: string) => {
    setToast(msg);
    window.setTimeout(() => setToast(null), 2600);
  };

  const loadConfigs = useCallback(async () => {
    try {
      const [m, e] = await Promise.all([
        invoke<ModelConfig[]>("list_model_configs"),
        invoke<EmbeddingConfig[]>("list_embedding_configs"),
      ]);
      setModels(m);
      setEmbeddings(e);
      await loadModelConfigs();
    } catch (e: any) {
      showToast(text("加载配置失败：", "Failed to load configuration: ") + (e?.message || String(e)));
    }

    try {
      const p = await invoke<Persona>("get_persona");
      setPersonaContent(p.content);
    } catch {}
  }, [loadModelConfigs, language]);

  const loadComfyProfiles = useCallback(async () => {
    try {
      const result = await invoke<ComfyUiProfilesResponse>("list_comfyui_profiles");
      setComfyProfiles(result.profiles);
      setComfyStatus(result.status);
      const selected = result.profiles.find((p) => p.selected) || result.profiles[0];
      if (selected) {
        setComfyName(selected.name);
        setComfyPath(selected.path);
        setComfyLaunchMode(selected.launch_mode || "portable");
      }
    } catch (e: any) {
      showToast(text("加载 ComfyUI 配置失败：", "Failed to load ComfyUI configuration: ") + (e?.message || String(e)));
    }
  }, [language]);

  const detectLocal = useCallback(async () => {
    setDetecting(true);
    try {
      const providers = await invoke<LocalProvider[]>("detect_local_models");
      setLocalProviders(providers);
    } catch {
      setLocalProviders([]);
    } finally {
      setDetecting(false);
    }
  }, []);

  useEffect(() => {
    loadConfigs();
    detectLocal();
    loadComfyProfiles();
  }, [loadConfigs, detectLocal, loadComfyProfiles]);

  const chooseComfyPath = async () => {
    const selected = await open({ directory: true, multiple: false });
    if (!selected || Array.isArray(selected)) return;
    setComfyPath(selected);
    if (!comfyName.trim()) setComfyName(selected.split(/[\\/]/).pop() || "ComfyUI");
  };

  const saveComfyProfile = async () => {
    if (!comfyPath.trim()) {
      showToast(text("请选择 ComfyUI 目录", "Choose a ComfyUI folder"));
      return;
    }
    setComfyBusy(true);
    try {
      const result = await invoke<ComfyUiProfilesResponse>("save_comfyui_profile", {
        profile: { name: comfyName.trim() || "ComfyUI", path: comfyPath.trim(), select: true, launchMode: comfyLaunchMode },
      });
      setComfyProfiles(result.profiles);
      setComfyStatus(result.status);
      showToast(text("ComfyUI 版本已保存", "ComfyUI version saved"));
    } catch (e: any) {
      showToast(text("保存失败：", "Save failed: ") + (e?.message || String(e)));
    } finally {
      setComfyBusy(false);
    }
  };

  const selectComfyProfile = async (id: string) => {
    setComfyBusy(true);
    try {
      const result = await invoke<ComfyUiProfilesResponse>("select_comfyui_profile", { id });
      setComfyProfiles(result.profiles);
      setComfyStatus(result.status);
      const selected = result.profiles.find((p) => p.selected);
      if (selected) {
        setComfyName(selected.name);
        setComfyPath(selected.path);
        setComfyLaunchMode(selected.launch_mode || "portable");
      }
      showToast(text("已切换 ComfyUI 版本", "ComfyUI version selected"));
    } catch (e: any) {
      showToast(text("切换失败：", "Switch failed: ") + (e?.message || String(e)));
    } finally {
      setComfyBusy(false);
    }
  };

  const startComfy = async () => {
    setComfyBusy(true);
    try {
      const next = await invoke<ComfyUiStatus>("start_comfyui");
      setComfyStatus(next);
      showToast(
        next.error
          ? text("启动失败", "Start failed")
          : next.started === false
            ? text("未检测到 ComfyUI，请先手动启动 Desktop/外部服务", "ComfyUI was not detected; start the Desktop/external service first")
            : text("ComfyUI 正在启动或已连接", "ComfyUI is starting or connected")
      );
    } catch (e: any) {
      showToast(text("启动失败：", "Start failed: ") + (e?.message || String(e)));
    } finally {
      setComfyBusy(false);
    }
  };

  const stopComfy = async () => {
    setComfyBusy(true);
    try {
      const next = await invoke<ComfyUiStatus>("stop_comfyui");
      setComfyStatus(next);
      showToast(text("ComfyUI 已停止", "ComfyUI stopped"));
    } catch (e: any) {
      showToast(text("停止失败：", "Stop failed: ") + (e?.message || String(e)));
    } finally {
      setComfyBusy(false);
    }
  };

  const savePersona = async () => {
    try {
      const result = await invoke<Persona>("update_persona", { content: personaContent });
      setPersonaContent(result.content);
      showToast(text("人设已保存", "Persona saved"));
    } catch (e: any) {
      showToast(text("保存失败：", "Save failed: ") + (e?.message || String(e)));
    }
  };

  const addModel = async () => {
    if (!chatModelName.trim()) {
      showToast(text("请输入模型名称", "Enter a model name"));
      return;
    }
    try {
      await invoke("add_model_config", {
        config: {
          id: crypto.randomUUID(),
          provider: chatProvider,
          modelName: chatModelName.trim(),
          apiKey: chatApiKey,
          baseUrl: chatBaseUrl,
          isDefault: models.length === 0,
        },
      });
      setChatModelName("");
      setChatApiKey("");
      showToast(text("模型已添加", "Model added"));
      await loadConfigs();
    } catch (e: any) {
      showToast(text("添加失败：", "Add failed: ") + (e?.message || String(e)));
    }
  };

  const addEmbedding = async () => {
    if (!embModelName.trim()) {
      showToast(text("请输入模型名称", "Enter a model name"));
      return;
    }
    try {
      await invoke("add_embedding_config", {
        config: {
          id: crypto.randomUUID(),
          provider: embProvider,
          modelName: embModelName.trim(),
          dimensions: embDimensions,
          apiKey: embApiKey,
          baseUrl: embBaseUrl,
          isDefault: embeddings.length === 0,
        },
      });
      setEmbModelName("");
      setEmbApiKey("");
      showToast(text("Embedding 模型已添加", "Embedding model added"));
      await loadConfigs();
    } catch (e: any) {
      showToast(text("添加失败：", "Add failed: ") + (e?.message || String(e)));
    }
  };

  const addLocalModel = async (provider: LocalProvider, modelId: string) => {
    try {
      const providerType =
        provider.name === "Ollama" ? "ollama" : provider.name === "llama.cpp" ? "llama_cpp" : "lmstudio";
      await invoke("add_model_config", {
        config: {
          id: crypto.randomUUID(),
          provider: providerType,
          modelName: modelId,
          apiKey: "",
          baseUrl: provider.baseUrl,
          isDefault: models.length === 0,
        },
      });
      showToast(text(`${provider.name} 模型已添加`, `${provider.name} model added`));
      await loadConfigs();
    } catch (e: any) {
      showToast(text("添加失败：", "Add failed: ") + (e?.message || String(e)));
    }
  };

  const removeModel = async (id: string) => {
    try {
      await invoke("remove_model_config", { id });
      await loadConfigs();
    } catch {
      showToast(text("删除失败", "Delete failed"));
    }
  };

  const removeEmbedding = async (id: string) => {
    try {
      await invoke("remove_embedding_config", { id });
      await loadConfigs();
    } catch {
      showToast(text("删除失败", "Delete failed"));
    }
  };

  const setDefaultModel = async (id: string) => {
    try {
      await invoke("set_default_model_config", { id });
      await loadConfigs();
      await selectModelConfig(id);
      showToast(text("已切换默认模型", "Default model updated"));
    } catch (e: any) {
      showToast(text("切换失败：", "Switch failed: ") + (e?.message || String(e)));
    }
  };

  const inputStyle: React.CSSProperties = {
    width: "100%",
    height: 36,
    padding: "0 11px",
    borderRadius: 10,
    background: "var(--bg-input)",
    border: "1px solid var(--border-subtle)",
    color: "var(--text-primary)",
    fontSize: 13,
    outline: "none",
  };
  return (
    <div className="settings-panel">
      {toast && (
        <div
          className="anim-fade-in"
          style={{
            position: "absolute",
            top: 12,
            right: 14,
            padding: "8px 12px",
            borderRadius: 10,
            background: "var(--accent)",
            color: "#fffefa",
            fontSize: 12,
            zIndex: 10,
            boxShadow: "var(--shadow-md)",
          }}
        >
          {toast}
        </div>
      )}

      <div className="settings-header">
        <div style={{ display: "flex", alignItems: "center", gap: 10, minWidth: 0 }}>
          <div className="brand-mark" style={{ width: 32, height: 32 }}>
            <Icon name="settings" size={17} />
          </div>
          <div style={{ minWidth: 0 }}>
            <h2 style={{ fontSize: 16, fontWeight: 820, color: "var(--text-primary)", margin: 0 }}>{text("设置", "Settings")}</h2>
            <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>{text("模型、记忆与助手人设", "Models, memory, and assistant persona")}</div>
          </div>
        </div>
        <button className="icon-button" onClick={onClose} title={text("关闭", "Close")}>
          <Icon name="close" size={16} />
        </button>
      </div>

      <div className="segmented" style={{ marginBottom: 16 }}>
        {[
          { k: "persona" as const, l: text("人设", "Persona") },
          { k: "chat" as const, l: text("聊天", "Chat") },
          { k: "embedding" as const, l: "Embedding" },
          { k: "comfyui" as const, l: "ComfyUI" },
          { k: "memory" as const, l: text("记忆", "Memory") },
          { k: "diagnostics" as const, l: text("诊断", "Diagnostics") },
        ].map((t) => (
          <button key={t.k} className={`segment ${tab === t.k ? "active" : ""}`} onClick={() => setTab(t.k)} style={{ flex: 1 }}>
            {t.l}
          </button>
        ))}
      </div>

      {tab === "persona" && (
        <section className="surface" style={{ borderRadius: 14, padding: 14 }}>
          <div style={{ fontSize: 13, fontWeight: 780, marginBottom: 8 }}>{text("助手人设", "Assistant persona")}</div>
          <textarea
            value={personaContent}
            onChange={(e) => setPersonaContent(e.target.value)}
            placeholder={text("例如：你是一个专业的 3D 资产设计助手，回答简洁，主动判断何时使用文生 3D、图生 3D 或图片修改。", "Example: You are a professional 3D asset assistant. Answer concisely and decide when to use text-to-3D, image-to-3D, or image editing.")}
            rows={8}
            style={{ ...inputStyle, height: "auto", padding: 12, lineHeight: 1.6, resize: "vertical", marginBottom: 10 }}
          />
          <button className="primary-button" onClick={savePersona} style={{ width: "100%", height: 36 }}>
            {text("保存人设", "Save persona")}
          </button>
        </section>
      )}

      {tab === "chat" && (
        <section style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <LocalModelPanel providers={localProviders} detecting={detecting} onDetect={detectLocal} onAdd={addLocalModel} />

          {models.map((m) => (
            <ConfigRow
              key={m.id}
              title={m.modelName}
              subtitle={`${PROVIDER_LABELS[m.provider] ?? m.provider}${m.apiKey ? text(" · Key 已保存", " · Key saved") : ""}`}
              active={m.isDefault}
              onSetDefault={() => setDefaultModel(m.id)}
              onRemove={() => removeModel(m.id)}
            />
          ))}

          <div className="surface" style={{ borderRadius: 14, padding: 14, display: "flex", flexDirection: "column", gap: 8 }}>
            <div style={{ fontSize: 13, fontWeight: 780 }}>{text("添加聊天模型", "Add chat model")}</div>
            <ProviderSelect value={chatProvider} onChange={setChatProvider} setBaseUrl={setChatBaseUrl} style={inputStyle} />
            <input style={inputStyle} placeholder={text("模型名称，例如 gpt-4o、deepseek-chat、qwen-max", "Model name, e.g. gpt-4o, deepseek-chat, or qwen-max")} value={chatModelName} onChange={(e) => setChatModelName(e.target.value)} />
            <input style={inputStyle} type="password" placeholder={text("API Key，本地模型可留空", "API Key, optional for local models")} value={chatApiKey} onChange={(e) => setChatApiKey(e.target.value)} />
            <input style={inputStyle} placeholder="Base URL" value={chatBaseUrl} onChange={(e) => setChatBaseUrl(e.target.value)} />
            <button className="primary-button" onClick={addModel} style={{ height: 36 }}>
              <Icon name="plus" size={15} />
              {text("添加", "Add")}
            </button>
          </div>
        </section>
      )}

      {tab === "embedding" && (
        <section style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {embeddings.map((e) => (
            <ConfigRow
              key={e.id}
              title={e.modelName}
              subtitle={`${PROVIDER_LABELS[e.provider] ?? e.provider} · ${e.dimensions}d${e.apiKey ? text(" · Key 已保存", " · Key saved") : ""}`}
              active={e.isDefault}
              onRemove={() => removeEmbedding(e.id)}
            />
          ))}

          <div className="surface" style={{ borderRadius: 14, padding: 14, display: "flex", flexDirection: "column", gap: 8 }}>
            <div style={{ fontSize: 13, fontWeight: 780 }}>{text("添加 Embedding 模型", "Add embedding model")}</div>
            <ProviderSelect value={embProvider} onChange={setEmbProvider} setBaseUrl={setEmbBaseUrl} style={inputStyle} />
            <input style={inputStyle} placeholder={text("模型名称，例如 text-embedding-3-small", "Model name, e.g. text-embedding-3-small")} value={embModelName} onChange={(e) => setEmbModelName(e.target.value)} />
            <input style={inputStyle} type="password" placeholder="API Key" value={embApiKey} onChange={(e) => setEmbApiKey(e.target.value)} />
            <input style={inputStyle} placeholder="Base URL" value={embBaseUrl} onChange={(e) => setEmbBaseUrl(e.target.value)} />
            <input style={inputStyle} type="number" placeholder={text("维度，例如 768", "Dimensions, e.g. 768")} value={embDimensions} onChange={(e) => setEmbDimensions(Number(e.target.value))} />
            <button className="primary-button" onClick={addEmbedding} style={{ height: 36 }}>
              <Icon name="plus" size={15} />
              {text("添加", "Add")}
            </button>
          </div>
        </section>
      )}

      {tab === "comfyui" && (
        <ComfyUiSettings
          profiles={comfyProfiles}
          status={comfyStatus}
          name={comfyName}
          path={comfyPath}
          launchMode={comfyLaunchMode}
          busy={comfyBusy}
          inputStyle={inputStyle}
          onNameChange={setComfyName}
          onPathChange={setComfyPath}
          onLaunchModeChange={setComfyLaunchMode}
          onBrowse={chooseComfyPath}
          onSave={saveComfyProfile}
          onSelect={selectComfyProfile}
          onStart={startComfy}
          onStop={stopComfy}
          onRefresh={loadComfyProfiles}
        />
      )}

      {tab === "memory" && <MemorySettings />}
      {tab === "diagnostics" && <DiagnosticsPanel />}
    </div>
  );
}

function ComfyUiSettings({
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
}: {
  profiles: ComfyUiProfile[];
  status: ComfyUiStatus | null;
  name: string;
  path: string;
  launchMode: ComfyUiLaunchMode;
  busy: boolean;
  inputStyle: React.CSSProperties;
  onNameChange: (v: string) => void;
  onPathChange: (v: string) => void;
  onLaunchModeChange: (v: ComfyUiLaunchMode) => void;
  onBrowse: () => void;
  onSave: () => void;
  onSelect: (id: string) => void;
  onStart: () => void;
  onStop: () => void;
  onRefresh: () => void;
}) {
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
        <select
          value={launchMode}
          onChange={(e) => onLaunchModeChange(e.target.value as ComfyUiLaunchMode)}
          style={inputStyle}
        >
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

function ProviderSelect({
  value,
  onChange,
  setBaseUrl,
  style,
}: {
  value: ProviderType;
  onChange: (v: ProviderType) => void;
  setBaseUrl: (v: string) => void;
  style: React.CSSProperties;
}) {
  return (
    <select
      value={value}
      onChange={(e) => {
        const next = e.target.value as ProviderType;
        onChange(next);
        setBaseUrl(PROVIDER_PRESETS[next].baseUrl);
      }}
      style={style}
    >
      {Object.keys(PROVIDER_PRESETS).map((k) => (
        <option key={k} value={k}>
          {PROVIDER_LABELS[k] ?? k}
        </option>
      ))}
    </select>
  );
}

function LocalModelPanel({
  providers,
  detecting,
  onDetect,
  onAdd,
}: {
  providers: LocalProvider[];
  detecting: boolean;
  onDetect: () => void;
  onAdd: (provider: LocalProvider, modelId: string) => void;
}) {
  const { text } = useLanguage();
  return (
    <div className="surface" style={{ borderRadius: 14, padding: 12 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
        <span style={{ fontSize: 13, fontWeight: 780 }}>{text("本地模型检测", "Local model detection")}</span>
        <button className="tool-button" onClick={onDetect} disabled={detecting} style={{ height: 28, padding: "0 8px" }}>
          <Icon name="refresh" size={13} />
          {detecting ? text("检测中", "Detecting") : text("重新检测", "Detect again")}
        </button>
      </div>
      {providers.length > 0 ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {providers.map((p) => (
            <div key={p.name}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12 }}>
                <span style={{ width: 8, height: 8, borderRadius: "50%", background: p.available ? "var(--success)" : "var(--danger)", flexShrink: 0 }} />
                <span style={{ color: p.available ? "var(--text-primary)" : "var(--text-muted)", flex: 1 }}>
                  {p.name} {p.available ? text(`(${p.models.length} 个模型)`, `(${p.models.length} models)`) : text("未运行", "Not running")}
                </span>
              </div>
              {p.available && p.models.length > 0 && (
                <div style={{ marginLeft: 16, marginTop: 4, display: "flex", flexDirection: "column", gap: 3 }}>
                  {p.models.slice(0, 6).map((m) => (
                    <div key={m.id} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <span style={{ flex: 1, minWidth: 0, fontSize: 11, color: "var(--text-secondary)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {m.name}
                      </span>
                      <button style={{ border: "none", background: "none", color: "var(--accent-blue)", cursor: "pointer", fontSize: 11 }} onClick={() => onAdd(p, m.id)}>
                        {text("添加", "Add")}
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      ) : (
        <div style={{ fontSize: 12, color: "var(--text-muted)", lineHeight: 1.6 }}>
          {detecting ? text("正在探测 Ollama / LM Studio / llama.cpp...", "Detecting Ollama / LM Studio / llama.cpp...") : text("点击重新检测扫描本地 LLM 服务。", "Detect local LLM services again.")}
        </div>
      )}
    </div>
  );
}

function ConfigRow({
  title,
  subtitle,
  active,
  onSetDefault,
  onRemove,
}: {
  title: string;
  subtitle: string;
  active: boolean;
  onSetDefault?: () => void;
  onRemove: () => void;
}) {
  const { text } = useLanguage();
  return (
    <div className="surface" style={{ borderRadius: 12, padding: "10px 12px", display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, minWidth: 0 }}>
        <span style={{ width: 8, height: 8, borderRadius: "50%", background: active ? "var(--success)" : "var(--text-muted)", flexShrink: 0 }} />
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: 13, fontWeight: 720, color: "var(--text-primary)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{title}</div>
          <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>{subtitle}</div>
        </div>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 6, flexShrink: 0 }}>
        {onSetDefault && !active && (
          <button className="tool-button" onClick={onSetDefault} style={{ height: 30, padding: "0 9px", fontSize: 11 }}>
            {text("设为默认", "Set default")}
          </button>
        )}
        <button className="icon-button" onClick={onRemove} title={text("删除", "Delete")} style={{ width: 30, height: 30 }}>
          <Icon name="trash" size={14} />
        </button>
      </div>
    </div>
  );
}

function MemorySettings() {
  const { text } = useLanguage();
  const [stm, setStm] = useState(20);
  const [chunk, setChunk] = useState(5);
  const [thresh, setThresh] = useState(0.7);

  return (
    <div className="surface" style={{ borderRadius: 14, padding: 14, display: "flex", flexDirection: "column", gap: 18 }}>
      <Slider label={text("短期记忆窗口", "Short-term memory window")} value={stm} min={5} max={100} onChange={setStm} />
      <Slider label={text("沉淀块大小", "Consolidation chunk size")} value={chunk} min={2} max={20} onChange={setChunk} />
      <Slider label={text("意图偏移阈值", "Intent shift threshold")} value={thresh} min={0.5} max={0.95} step={0.05} onChange={setThresh} />
    </div>
  );
}

function Slider({
  label,
  value,
  min,
  max,
  step = 1,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step?: number;
  onChange: (v: number) => void;
}) {
  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
        <span style={{ fontSize: 13, color: "var(--text-secondary)" }}>{label}</span>
        <span style={{ fontSize: 13, fontWeight: 760, color: "var(--text-primary)" }}>{value}</span>
      </div>
      <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} style={{ width: "100%", accentColor: "var(--accent)" }} />
    </div>
  );
}
