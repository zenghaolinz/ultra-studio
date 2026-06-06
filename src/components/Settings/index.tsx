import { useCallback, useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import type { EmbeddingConfig, LocalProvider, ModelConfig, Persona, ProviderType } from "../../types";
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
  const [tab, setTab] = useState<"persona" | "chat" | "embedding" | "memory" | "diagnostics">("chat");
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
  }, [loadConfigs, detectLocal]);

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
    <div style={{ padding: 20, position: "relative" }}>
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

      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 18 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div className="brand-mark" style={{ width: 32, height: 32 }}>
            <Icon name="settings" size={17} />
          </div>
          <div>
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

      {tab === "memory" && <MemorySettings />}
      {tab === "diagnostics" && <DiagnosticsPanel />}
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
