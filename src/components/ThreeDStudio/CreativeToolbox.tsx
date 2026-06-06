import { useEffect, useMemo, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { useAppStore } from "../../stores/appStore";
import type { ComfyUiStatus } from "../../types";
import Icon from "../Icon";
import { useLanguage } from "../../i18n";

type Template = {
  id: string;
  title: string;
  titleEn: string;
  scene: string;
  sceneEn: string;
  prompt: string;
  promptEn: string;
  accent: string;
};

const templates: Template[] = [
  {
    id: "game-character",
    title: "游戏角色原型",
    titleEn: "Game character prototype",
    scene: "适合游戏角色、动画短片和 IP 原型。",
    sceneEn: "For game characters, animation shorts, and IP prototypes.",
    accent: "var(--accent-blue)",
    prompt:
      "一个适合游戏原型的卡通角色，完整身体，清晰轮廓，大眼睛，柔和材质，正面视角，白色背景，适合转为 3D 模型",
    promptEn:
      "A cartoon character for a game prototype, full body, clear silhouette, large eyes, soft material, front view, white background, suitable for conversion to a 3D model",
  },
  {
    id: "cultural-toy",
    title: "文创摆件",
    titleEn: "Cultural collectible",
    scene: "适合校园文创、纪念品和摆件设计。",
    sceneEn: "For campus creations, souvenirs, and decorative pieces.",
    accent: "var(--accent-warm)",
    prompt:
      "一个可爱的文创摆件设计，圆润造型，陶瓷质感，简洁花纹，正面产品图，干净背景，适合 3D 打印展示",
    promptEn:
      "A charming cultural collectible design with a rounded form, ceramic finish, simple patterns, front product view, clean background, suitable for 3D printing display",
  },
  {
    id: "teaching-model",
    title: "教学模型",
    titleEn: "Teaching model",
    scene: "适合课堂演示、技能训练和结构讲解。",
    sceneEn: "For class demonstrations, skills training, and structural explanation.",
    accent: "var(--success)",
    prompt:
      "一个用于教学演示的简洁 3D 模型，结构清晰，颜色分区明显，正面视角，白色背景，适合课堂讲解",
    promptEn:
      "A concise 3D model for teaching demonstration, clear structure, distinct color regions, front view, white background, suitable for classroom explanation",
  },
  {
    id: "industrial-concept",
    title: "工业概念件",
    titleEn: "Industrial concept",
    scene: "适合工业技能、产品概念和零件外观方案。",
    sceneEn: "For industrial skills, product concepts, and component appearance studies.",
    accent: "var(--danger)",
    prompt:
      "一个工业产品概念模型，硬表面结构，清晰边缘，金属和哑光塑料材质，产品展示图，白色背景，适合转 3D",
    promptEn:
      "An industrial product concept model with hard-surface construction, crisp edges, metal and matte plastic materials, product presentation view, white background, suitable for 3D conversion",
  },
];

function notifyTaskUpdated() {
  window.dispatchEvent(new CustomEvent("generation-task-updated"));
}

export default function CreativeToolbox() {
  const { language, text } = useLanguage();
  const {
    threeDTextPrompt,
    threeDQuality,
    threeDModelPath,
    threeDPreview2D,
    setThreeDTextPrompt,
    setThreeDQuality,
  } = useAppStore();

  const [selectedTemplate, setSelectedTemplate] = useState<Template | null>(null);
  const [status, setStatus] = useState<ComfyUiStatus | null>(null);
  const [showcaseMessage, setShowcaseMessage] = useState("");
  const [creatingShowcase, setCreatingShowcase] = useState(false);

  const activeScene = selectedTemplate
    ? (language === "zh" ? selectedTemplate.scene : selectedTemplate.sceneEn)
    : text("AI+应用开发与软件技能赛道的 3D 资产创作项目。", "A 3D asset creation project for the AI application development and software skills track.");

  const resourceAdvice = useMemo(() => {
    if (!status) return text("正在读取 ComfyUI 状态", "Reading ComfyUI status");
    if (status.error) return text("状态异常，建议打开日志查看失败节点", "Status error; review logs for the failed node");
    if (status.ready) return threeDQuality === "quality" ? text("高质量模式会占用更多显存", "High quality mode uses more VRAM") : text("快速模式适合比赛现场演示", "Fast mode is suited to live demos");
    if (status.running || status.process_alive) return text("ComfyUI 正在启动，等待就绪后再提交任务", "ComfyUI is starting; wait until ready to submit a task");
    return text("ComfyUI 未启动，可以从顶部状态按钮启动", "ComfyUI is stopped; start it from the status button above");
  }, [status, threeDQuality, language]);

  useEffect(() => {
    let cancelled = false;
    const refresh = async () => {
      try {
        const next = await invoke<ComfyUiStatus>("get_comfyui_status");
        if (!cancelled) setStatus(next);
      } catch (e) {
        if (!cancelled) setStatus({ error: typeof e === "string" ? e : String(e) });
      }
    };
    refresh();
    const timer = window.setInterval(refresh, 6000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  const applyTemplate = (template: Template) => {
    setSelectedTemplate(template);
    setThreeDTextPrompt(language === "zh" ? template.prompt : template.promptEn);
    if (template.id === "industrial-concept") setThreeDQuality("quality");
  };

  const createShowcase = async () => {
    if (creatingShowcase) return;
    setCreatingShowcase(true);
    setShowcaseMessage(text("正在整理展示材料...", "Preparing showcase materials..."));
    try {
      const result = await invoke<{ status: string; path?: string; message?: string }>("create_showcase_materials", {
        title: selectedTemplate ? `Ultra Studio_${language === "zh" ? selectedTemplate.title : selectedTemplate.titleEn}` : "Ultra Studio 3D Asset",
        prompt: threeDTextPrompt,
        modelPath: threeDModelPath || null,
        imagePath: threeDPreview2D || null,
        scene: activeScene,
      });
      setShowcaseMessage(result.path ? text("展示材料已生成。", "Showcase materials generated.") : result.message || text("展示材料已生成。", "Showcase materials generated."));
    } catch (e) {
      setShowcaseMessage(typeof e === "string" ? e : e instanceof Error ? e.message : String(e));
    } finally {
      setCreatingShowcase(false);
      notifyTaskUpdated();
    }
  };

  return (
    <div style={{ display: "grid", gap: 12 }}>
      <section className="surface" style={{ borderRadius: 14, padding: 12 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
          <Icon name="spark" size={15} />
          <b style={{ fontSize: 12 }}>{text("应用场景模板", "Scenario templates")}</b>
        </div>
        <div style={{ display: "grid", gap: 8 }}>
          {templates.map((template) => (
            <button
              key={template.id}
              type="button"
              onClick={() => applyTemplate(template)}
              style={{
                border: "1px solid var(--border-subtle)",
                borderLeft: `4px solid ${template.accent}`,
                background: selectedTemplate?.id === template.id ? "var(--accent-muted)" : "rgba(255,254,250,0.62)",
                borderRadius: 11,
                padding: "9px 10px",
                textAlign: "left",
                cursor: "pointer",
              }}
            >
              <div style={{ fontSize: 12, fontWeight: 800, color: "var(--text-primary)" }}>{language === "zh" ? template.title : template.titleEn}</div>
              <div style={{ fontSize: 10, color: "var(--text-muted)", marginTop: 4, lineHeight: 1.45 }}>{language === "zh" ? template.scene : template.sceneEn}</div>
            </button>
          ))}
        </div>
      </section>

      <section className="surface" style={{ borderRadius: 14, padding: 12 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
          <Icon name="cpu" size={15} />
          <b style={{ fontSize: 12 }}>{text("本地资源调度", "Local resource scheduling")}</b>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
          <ResourceBadge label="ComfyUI" value={status?.ready ? text("已就绪", "Ready") : status?.running ? text("启动中", "Starting") : text("未就绪", "Not ready")} ok={!!status?.ready} />
          <ResourceBadge label={text("模式", "Mode")} value={threeDQuality === "quality" ? text("高质量", "High quality") : text("快速", "Fast")} ok />
          <ResourceBadge label={text("进程", "Process")} value={status?.process_alive ? text("托管中", "Managed") : text("未托管", "Unmanaged")} ok={!!status?.process_alive || !!status?.ready} />
          <ResourceBadge label={text("建议", "Advice")} value={threeDQuality === "quality" ? text("稳态演示", "Stable demo") : text("现场演示", "Live demo")} ok />
        </div>
        <div style={{ marginTop: 9, fontSize: 10, color: "var(--text-muted)", lineHeight: 1.55 }}>{resourceAdvice}</div>
      </section>

      <section className="surface" style={{ borderRadius: 14, padding: 12 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
          <Icon name="file" size={15} />
          <b style={{ fontSize: 12 }}>{text("一键生成展示材料", "Generate showcase materials")}</b>
        </div>
        <button className="tool-button" onClick={createShowcase} disabled={creatingShowcase} style={{ width: "100%", height: 34 }}>
          <Icon name="download" size={14} />
          {creatingShowcase ? text("整理中", "Preparing") : text("生成作品说明", "Generate project summary")}
        </button>
        {showcaseMessage && <div style={{ fontSize: 10, color: "var(--text-muted)", marginTop: 8, lineHeight: 1.5 }}>{showcaseMessage}</div>}
      </section>
    </div>
  );
}

function ResourceBadge({ label, value, ok }: { label: string; value: string; ok: boolean }) {
  return (
    <div style={{ border: "1px solid var(--border-subtle)", borderRadius: 10, padding: "8px 9px", background: "rgba(255,254,250,0.54)" }}>
      <div style={{ fontSize: 10, color: "var(--text-muted)", marginBottom: 3 }}>{label}</div>
      <div style={{ fontSize: 11, color: ok ? "var(--success)" : "var(--text-secondary)", fontWeight: 800, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{value}</div>
    </div>
  );
}
