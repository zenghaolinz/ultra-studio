import { useCallback, useEffect, useRef, useState } from "react";
import { convertFileSrc, invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import { open } from "@tauri-apps/plugin-dialog";
import { useAppStore } from "../../stores/appStore";
import ComfyStatus from "../ComfyStatus";
import Icon from "../Icon";
import ModelPreview from "./ModelPreview";
import CreativeToolbox from "./CreativeToolbox";
import GenerationHistory from "./GenerationHistory";
import { useLanguage } from "../../i18n";

type PreviewTab = "3d" | "2d" | "normal" | "uv";

function assetUrl(localPath: string): string {
  if (!localPath) return "";
  if (localPath.startsWith("http")) return localPath;
  try {
    return convertFileSrc(localPath);
  } catch {
    return localPath;
  }
}

function messageOf(e: unknown) {
  return typeof e === "string" ? e : e instanceof Error ? e.message : String(e);
}

function notifyTaskUpdated() {
  window.dispatchEvent(new CustomEvent("generation-task-updated"));
}

export default function ThreeDStudio() {
  const { text } = useLanguage();
  const {
    threeDImages,
    threeDTextPrompt,
    threeDProgress,
    threeDProgressDesc,
    threeDModelPath,
    threeDPreview2D,
    threeDPreviewNormal,
    threeDPreviewUV,
    threeDIsGenerating,
    threeDQuality,
    threeDGenerateMode,
    addThreeDImage,
    setThreeDImages,
    removeThreeDImage,
    setThreeDTextPrompt,
    setThreeDQuality,
    setThreeDGenerateMode,
    clearThreeDResults,
  } = useAppStore();

  const [previewTab, setPreviewTab] = useState<PreviewTab>("3d");
  const [improvePrompt, setImprovePrompt] = useState("");
  const [isImproving, setIsImproving] = useState(false);
  const [improveMessage, setImproveMessage] = useState("");
  const unlistenersRef = useRef<UnlistenFn[]>([]);
  const maxImages = threeDGenerateMode === "multiview" ? 4 : 2;

  const cleanupListeners = useCallback(() => {
    unlistenersRef.current.forEach((fn) => {
      try {
        fn();
      } catch {}
    });
    unlistenersRef.current = [];
  }, []);

  useEffect(() => cleanupListeners, [cleanupListeners]);

  useEffect(() => {
    if (threeDModelPath) setPreviewTab("3d");
    else if (threeDPreview2D) setPreviewTab("2d");
  }, [threeDModelPath, threeDPreview2D]);

  const handleGenerate = useCallback(async () => {
    const state = useAppStore.getState();
    if (state.threeDIsGenerating) return;

    const imageSlots = state.threeDImages;
    const images = imageSlots.filter(Boolean);
    const prompt = state.threeDTextPrompt.trim();
    if (images.length === 0 && !prompt) return;

    useAppStore.setState({
      threeDIsGenerating: true,
      threeDProgress: 0,
      threeDProgressDesc: text("正在发送请求...", "Sending request..."),
      threeDModelPath: null,
      threeDPreview2D: null,
      threeDPreviewNormal: null,
      threeDPreviewUV: null,
    });

    cleanupListeners();

    const unlistenProgress = await listen<any>("three-d-progress", (event) => {
      const data = event.payload;
      const desc = data.description || data.desc || text("处理中...", "Processing...");
      if (data.type === "progress" && data.value !== undefined) {
        useAppStore.setState({ threeDProgress: data.value, threeDProgressDesc: desc });
      } else {
        useAppStore.setState({ threeDProgressDesc: desc });
      }
    });

    const unlistenResult = await listen<any>("three-d-result", (event) => {
      const data = event.payload;
      cleanupListeners();
      useAppStore.setState({
        threeDProgress: 1,
        threeDProgressDesc: text("完成", "Complete"),
        threeDIsGenerating: false,
        threeDModelPath: data.modelPath || null,
        threeDPreview2D: data.image2D || null,
        threeDPreviewNormal: data.imageNormal || null,
        threeDPreviewUV: data.imageUV || null,
        threeDSourceImage1: data.image1Path || null,
        threeDSourceImage2: data.image2Path || null,
      });
      notifyTaskUpdated();
    });

    const unlistenError = await listen<any>("three-d-error", (event) => {
      cleanupListeners();
      useAppStore.setState({
        threeDIsGenerating: false,
        threeDProgress: 0,
        threeDProgressDesc: text("错误：", "Error: ") + (event.payload.message || text("未知错误", "Unknown error")),
      });
      notifyTaskUpdated();
    });

    unlistenersRef.current = [unlistenProgress, unlistenResult, unlistenError];

    try {
      const quality = state.threeDQuality;
      if (state.threeDGenerateMode === "multiview") {
        const multiviewImages = [imageSlots[0] || "", imageSlots[1] || "", imageSlots[2] || "", imageSlots[3] || ""];
        if (!multiviewImages[0] || !multiviewImages[1] || !multiviewImages[3]) {
          useAppStore.setState({
            threeDIsGenerating: false,
            threeDProgress: 0,
            threeDProgressDesc: text("错误：多视角模式至少需要正面、左侧、背面 3 张图片；右侧可选", "Error: multiview mode needs front, left, and back images; right is optional"),
          });
          cleanupListeners();
          notifyTaskUpdated();
          return;
        }
        useAppStore.setState({ threeDProgressDesc: text("Hy3D 多视角生成中...", "Generating with Hy3D multiview...") });
        await invoke("generate_3d_multiview_stream", {
          imagePaths: multiviewImages,
          quality,
        });
      } else if (images.length >= 2) {
        useAppStore.setState({ threeDProgressDesc: text("双图融合生成中...", "Generating with image fusion...") });
        await invoke("generate_3d_fusion_stream", {
          image1Path: images[0],
          image2Path: images[1],
          prompt: prompt || text("融合这两张图片", "Fuse these two images"),
          quality,
        });
      } else if (images.length === 1) {
        useAppStore.setState({ threeDProgressDesc: text("图片转 3D 生成中...", "Generating 3D from image...") });
        await invoke("generate_3d_image_stream", { imagePath: images[0], quality });
      } else {
        useAppStore.setState({ threeDProgressDesc: text("文字生成 3D 模型中...", "Generating 3D from text...") });
        await invoke("generate_3d_text_stream", { prompt, quality });
      }
    } catch (e) {
      cleanupListeners();
      useAppStore.setState({
        threeDIsGenerating: false,
        threeDProgress: 0,
        threeDProgressDesc: text("错误：", "Error: ") + messageOf(e),
      });
      notifyTaskUpdated();
    }
  }, [cleanupListeners]);

  const handleCancel = useCallback(async () => {
    try {
      await invoke("cancel_3d_generation");
      cleanupListeners();
      useAppStore.setState({ threeDIsGenerating: false, threeDProgress: 0, threeDProgressDesc: text("已取消", "Cancelled") });
    } catch (e) {
      console.error("Cancel error:", e);
    }
  }, [cleanupListeners]);

  const handleImprove = useCallback(async () => {
    const state = useAppStore.getState();
    if (state.threeDImages.length < 1 || isImproving) return;
    const imgPath = state.threeDImages[0];
    const prompt = improvePrompt.trim() || text("提高清晰度，增强细节", "Improve clarity and enhance detail");
    setIsImproving(true);
    setImproveMessage(text("正在改进图片...", "Improving image..."));
    try {
      const result: any = await invoke("generate_3d_improve_image", {
        imagePath: imgPath,
        improvementPrompt: prompt,
      });
      if (result.status === "success" && result.imagePath) {
        useAppStore.getState().removeThreeDImage(0);
        useAppStore.getState().addThreeDImage(result.imagePath);
        setImproveMessage(text("图片改进完成", "Image improved"));
        notifyTaskUpdated();
      } else {
        setImproveMessage(text("改进失败：", "Improvement failed: ") + (result.message || text("未知错误", "Unknown error")));
        notifyTaskUpdated();
      }
    } catch (e) {
      setImproveMessage(text("错误：", "Error: ") + messageOf(e));
      notifyTaskUpdated();
    }
    setIsImproving(false);
  }, [improvePrompt, isImproving]);

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    if (threeDGenerateMode === "multiview") {
      const slots = [...useAppStore.getState().threeDImages].slice(0, 4);
      while (slots.length < 4) slots.push("");
      let slotIndex = slots.findIndex((item) => !item);
      if (slotIndex < 0) return;
      for (const f of Array.from(e.dataTransfer.files) as any[]) {
        const path = f.path || f.name;
        if (!(f.type?.startsWith("image/") || /\.(png|jpe?g|webp|gif|bmp)$/i.test(path))) continue;
        slots[slotIndex] = path;
        slotIndex = slots.findIndex((item) => !item);
        if (slotIndex < 0) break;
      }
      setThreeDImages(slots);
      return;
    }
    const availableSlots = Math.max(0, maxImages - useAppStore.getState().threeDImages.length);
    Array.from(e.dataTransfer.files)
      .slice(0, availableSlots)
      .forEach((f: any) => {
        const path = f.path || f.name;
        if (f.type?.startsWith("image/") || /\.(png|jpe?g|webp|gif|bmp)$/i.test(path)) {
          addThreeDImage(path);
        }
      });
  };

  const openFilePicker = async () => {
    try {
      const files = await open({
        multiple: true,
        filters: [{ name: text("图片", "Images"), extensions: ["png", "jpg", "jpeg", "webp", "gif", "bmp"] }],
      });
      if (files) {
        const paths = Array.isArray(files) ? files : [files];
        const availableSlots = Math.max(0, maxImages - useAppStore.getState().threeDImages.length);
        paths.slice(0, availableSlots).forEach((p: string) => addThreeDImage(p));
      }
    } catch (e) {
      console.error("File picker error:", e);
    }
  };

  const openMultiviewSlotPicker = async (index: number) => {
    try {
      const file = await open({
        multiple: false,
        filters: [{ name: text("图片", "Images"), extensions: ["png", "jpg", "jpeg", "webp", "gif", "bmp"] }],
      });
      if (typeof file !== "string") return;
      const slots = [...useAppStore.getState().threeDImages].slice(0, 4);
      while (slots.length < 4) slots.push("");
      slots[index] = file;
      setThreeDImages(slots);
    } catch (e) {
      console.error("File picker error:", e);
    }
  };

  const clearMultiviewSlot = (index: number) => {
    const slots = [...useAppStore.getState().threeDImages].slice(0, 4);
    while (slots.length < 4) slots.push("");
    slots[index] = "";
    setThreeDImages(slots);
  };

  const modeLabel =
    threeDGenerateMode === "multiview"
      ? text("多视角 Hy3D -> 3D", "Multiview Hy3D -> 3D")
      : threeDImages.length >= 2
        ? text("双图融合 -> 3D", "Image fusion -> 3D")
        : threeDImages.length === 1
          ? text("图片 -> 3D", "Image -> 3D")
          : text("文字 -> 3D", "Text -> 3D");
  const qualityLabel = threeDQuality === "quality" ? text("高质量", "High quality") : text("快速", "Fast");
  const isMultiviewMode = threeDGenerateMode === "multiview";
  const hasError = !threeDIsGenerating && !!threeDProgressDesc && (
    threeDProgressDesc.startsWith("错误") ||
    threeDProgressDesc.startsWith("失败") ||
    threeDProgressDesc.startsWith("Error") ||
    threeDProgressDesc.startsWith("Failed")
  );
  const multiviewFilledCount = [threeDImages[0], threeDImages[1], threeDImages[2], threeDImages[3]].filter(Boolean).length;
  const switchGenerateMode = (mode: "auto" | "multiview") => {
    setThreeDGenerateMode(mode);
    if (mode === "auto" && useAppStore.getState().threeDImages.length > 2) {
      useAppStore.setState({ threeDImages: useAppStore.getState().threeDImages.slice(0, 2) });
    }
  };

  const tabs: { key: PreviewTab; label: string; icon: "cube" | "image" | "layers" | "grid"; available: boolean }[] = [
    { key: "3d", label: text("3D 模型", "3D model"), icon: "cube", available: !!threeDModelPath },
    { key: "2d", label: text("渲染图", "Render"), icon: "image", available: !!threeDPreview2D },
    { key: "normal", label: text("法线图", "Normal map"), icon: "layers", available: !!threeDPreviewNormal },
    { key: "uv", label: text("UV 贴图", "UV texture"), icon: "grid", available: !!threeDPreviewUV },
  ];
  const multiviewSlots = [
    { label: text("正面", "Front"), hint: text("正面视图", "Front"), required: true },
    { label: text("左侧", "Left"), hint: text("左侧视图", "Left"), required: true },
    { label: text("右侧", "Right"), hint: text("右侧视图", "Right"), required: false },
    { label: text("背面", "Back"), hint: text("背面视图", "Back"), required: true },
  ];

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh", background: "transparent" }}>
      <header
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "12px 20px",
          flexShrink: 0,
          borderBottom: "1px solid var(--border-subtle)",
          background: "rgba(255,254,250,0.72)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div className="brand-mark" style={{ width: 32, height: 32 }}>
            <Icon name="cube" size={17} />
          </div>
          <div>
            <h1 style={{ fontSize: 16, fontWeight: 820, color: "var(--text-primary)", margin: 0 }}>{text("3D 资产工作区", "3D Asset Workspace")}</h1>
            <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>
              {modeLabel} · {qualityLabel}
            </div>
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <div className="segmented" style={{ height: 34 }}>
            <button className={`segment ${threeDQuality === "fast" ? "active" : ""}`} onClick={() => setThreeDQuality("fast")} disabled={threeDIsGenerating} title={text("快速预览模式", "Fast preview mode")}>
              {text("快速预览", "Fast preview")}
            </button>
            <button className={`segment ${threeDQuality === "quality" ? "active" : ""}`} onClick={() => setThreeDQuality("quality")} disabled={threeDIsGenerating} title={text("高质量模式", "High quality mode")}>
              {text("高质量", "High quality")}
            </button>
          </div>
          <ComfyStatus />
          <button className="tool-button" onClick={clearThreeDResults}>
            <Icon name="trash" size={15} />
            {text("清除结果", "Clear results")}
          </button>
        </div>
      </header>

      <div style={{ flex: 1, display: "flex", minHeight: 0 }}>
        <aside
          style={{
            width: 310,
            flexShrink: 0,
            padding: 16,
            display: "flex",
            flexDirection: "column",
            gap: 12,
            overflowY: "auto",
            overflowX: "hidden",
            borderRight: "1px solid var(--border-subtle)",
          }}
        >
          <div
            onDragOver={(e) => {
              e.preventDefault();
              e.currentTarget.style.borderColor = "var(--accent-blue)";
            }}
            onDragLeave={(e) => {
              e.currentTarget.style.borderColor = "var(--border-subtle)";
            }}
            onDrop={(e) => {
              e.currentTarget.style.borderColor = "var(--border-subtle)";
              handleDrop(e);
            }}
            onClick={openFilePicker}
            className="surface"
            style={{
              minHeight: 190,
              borderRadius: 16,
              borderStyle: "dashed",
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              justifyContent: "center",
              cursor: "pointer",
              transition: "border-color var(--transition), transform var(--transition)",
            }}
          >
            <div className="brand-mark" style={{ width: 44, height: 44, borderRadius: 14, marginBottom: 10 }}>
              <Icon name="upload" size={21} />
            </div>
            <div style={{ fontSize: 13, color: "var(--text-primary)", fontWeight: 760 }}>{text("上传参考图片", "Upload reference images")}</div>
            <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 4 }}>
              {threeDGenerateMode === "multiview" ? text("四宫格视角槽，右侧可不上传", "Four view slots; right is optional") : text("自动模式最多 2 张，可拖拽", "Up to 2 images in auto mode; drag and drop")}
            </div>
          </div>

          {threeDGenerateMode === "multiview" ? (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 8 }}>
              {multiviewSlots.map((slot, i) => {
                const img = threeDImages[i] || "";
                return (
                  <button
                    key={slot.hint}
                    type="button"
                    onClick={() => openMultiviewSlotPicker(i)}
                    title={`${slot.label}${slot.required ? text("（必填）", " (required)") : text("（可选，不传则不接入右视角）", " (optional)")}`}
                    style={{
                      position: "relative",
                      aspectRatio: "1",
                      borderRadius: 12,
                      overflow: "hidden",
                      border: `1px ${img ? "solid" : "dashed"} ${slot.required && !img ? "rgba(184,59,59,0.34)" : "var(--border-subtle)"}`,
                      background: img ? "var(--bg-input)" : "rgba(255,254,250,0.54)",
                      cursor: "pointer",
                      padding: 0,
                      color: "var(--text-muted)",
                    }}
                  >
                    {img ? (
                      <img src={assetUrl(img)} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} onError={(e) => { e.currentTarget.style.display = "none"; }} />
                    ) : (
                      <div style={{ height: "100%", display: "grid", placeItems: "center", fontSize: 10, lineHeight: 1.35, padding: 4 }}>
                        <span>{slot.required ? text("必填", "Required") : text("可选", "Optional")}</span>
                      </div>
                    )}
                    <span style={{ position: "absolute", left: 4, bottom: 4, padding: "2px 5px", borderRadius: 6, background: "rgba(23,22,21,0.72)", color: "#fffefa", fontSize: 9, fontWeight: 760 }}>
                      {slot.label}
                    </span>
                    {img && (
                      <span
                        role="button"
                        tabIndex={0}
                        onClick={(event) => {
                          event.stopPropagation();
                          clearMultiviewSlot(i);
                        }}
                        style={{ position: "absolute", top: 4, right: 4, width: 22, height: 22, borderRadius: 7, background: "rgba(23,22,21,0.72)", color: "#fffefa", display: "grid", placeItems: "center" }}
                        title={text("移除图片", "Remove image")}
                      >
                        <Icon name="close" size={13} />
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
          ) : threeDImages.length > 0 ? (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 8 }}>
              {threeDImages.filter(Boolean).map((img, i) => (
                <div key={`${img}-${i}`} style={{ position: "relative", aspectRatio: "1", borderRadius: 12, overflow: "hidden", border: "1px solid var(--border-subtle)", background: "var(--bg-input)" }}>
                  <img src={assetUrl(img)} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} onError={(e) => { e.currentTarget.style.display = "none"; }} />
                  <button onClick={() => removeThreeDImage(i)} className="icon-button" title={text("移除图片", "Remove image")} style={{ position: "absolute", top: 4, right: 4, width: 22, height: 22, borderRadius: 7, background: "rgba(23,22,21,0.72)", color: "#fffefa", border: "none" }}>
                    <Icon name="close" size={13} />
                  </button>
                </div>
              ))}
            </div>
          ) : null}

          {threeDGenerateMode === "multiview" && (
            <div style={{ fontSize: 10, color: "var(--text-muted)", lineHeight: 1.5, marginTop: -4 }}>
              {text("正面、左侧、背面必填；右侧可选，不传时不会接入 right 输入，也不会生成占位图。", "Front, left, and back are required; right is optional and will not be synthesized if omitted.")}
            </div>
          )}

          <div className="surface" style={{ borderRadius: 14, padding: 12 }}>
            <div style={{ fontSize: 12, color: "var(--text-secondary)", marginBottom: 8, fontWeight: 760 }}>{text("生成模式", "Generation mode")}</div>
            <div className="segmented" style={{ marginBottom: 10 }}>
              <button className={`segment ${threeDGenerateMode === "auto" ? "active" : ""}`} onClick={() => switchGenerateMode("auto")} disabled={threeDIsGenerating} style={{ flex: 1 }}>
                {text("自动", "Auto")}
              </button>
              <button className={`segment ${threeDGenerateMode === "multiview" ? "active" : ""}`} onClick={() => switchGenerateMode("multiview")} disabled={threeDIsGenerating} style={{ flex: 1 }}>
                {text("多视角", "Multiview")}
              </button>
            </div>
            <div style={{ fontSize: 12, color: "var(--text-secondary)", marginBottom: 8, fontWeight: 760 }}>{text("生成质量", "Quality")}</div>
            <div className="segmented">
              <button className={`segment ${threeDQuality === "fast" ? "active" : ""}`} onClick={() => setThreeDQuality("fast")} disabled={threeDIsGenerating} style={{ flex: 1 }}>{text("快速", "Fast")}</button>
              <button className={`segment ${threeDQuality === "quality" ? "active" : ""}`} onClick={() => setThreeDQuality("quality")} disabled={threeDIsGenerating} style={{ flex: 1 }}>{text("高质量", "High quality")}</button>
            </div>
          </div>

          {!isMultiviewMode && <CreativeToolbox />}

          <GenerationHistory />

          {threeDImages.length === 1 && (
            <div className="surface" style={{ borderRadius: 14, padding: 12 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, fontWeight: 760, marginBottom: 9 }}>
                <Icon name="wand" size={15} />
                {text("Flux 图片改进", "Flux image improvement")}
              </div>
              <input type="text" value={improvePrompt} onChange={(e) => setImprovePrompt(e.target.value)} placeholder={text("例如：改成黑色、增加细节、变成卡通风格", "Example: make it black, add detail, use a cartoon style")} style={{ width: "100%", height: 34, padding: "0 10px", borderRadius: 9, background: "var(--bg-input)", border: "1px solid var(--border-subtle)", color: "var(--text-primary)", fontSize: 12, outline: "none", marginBottom: 8 }} />
              <button disabled={isImproving || threeDIsGenerating} onClick={handleImprove} className="primary-button" style={{ width: "100%", height: 34 }}>
                <Icon name="wand" size={14} />
                {isImproving ? text("改进中", "Improving") : text("改进图片", "Improve image")}
              </button>
              {improveMessage && <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 7 }}>{improveMessage}</div>}
            </div>
          )}

        </aside>

        <section style={{ flex: 1, display: "flex", flexDirection: "column", padding: 18, gap: 12, minWidth: 0 }}>
          <textarea
            value={isMultiviewMode ? "" : threeDTextPrompt}
            onChange={(e) => {
              if (!isMultiviewMode) setThreeDTextPrompt(e.target.value);
            }}
            disabled={isMultiviewMode || threeDIsGenerating}
            placeholder={isMultiviewMode ? text("多视角模式不使用提示词，请在左侧四宫格上传正面、左侧、背面图片；右侧可选。", "Multiview mode does not use a prompt. Upload front, left, and back images; right is optional.") : text("描述你要生成的 3D 资产，例如：一只黑色卡通猫咪，大眼睛，柔软毛绒质感，适合游戏角色...", "Describe the 3D asset to create, e.g. a black cartoon cat with large eyes and a soft plush finish...")}
            rows={3}
            style={{
              width: "100%",
              padding: "13px 14px",
              borderRadius: 14,
              background: isMultiviewMode ? "rgba(238,235,229,0.72)" : "rgba(255,254,250,0.78)",
              border: "1px solid var(--border-subtle)",
              color: isMultiviewMode ? "var(--text-muted)" : "var(--text-primary)",
              fontSize: 14,
              lineHeight: 1.55,
              resize: "none",
              outline: "none",
              boxShadow: isMultiviewMode ? "none" : "var(--shadow-sm)",
              cursor: isMultiviewMode ? "not-allowed" : "text",
            }}
          />

          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <button disabled={threeDIsGenerating} onClick={handleGenerate} className="primary-button" style={{ height: 40, padding: "0 18px", borderRadius: 12 }}>
              {threeDIsGenerating ? (
                <>
                  <div style={{ width: 15, height: 15, borderRadius: "50%", border: "2px solid rgba(255,255,255,0.45)", borderTopColor: "#fffefa", animation: "spin 0.8s linear infinite" }} />
                  {text("生成中", "Generating")}
                </>
              ) : (
                <>
                  <Icon name="spark" size={17} />
                  {text("生成 3D 模型", "Generate 3D model")}
                </>
              )}
            </button>

            {threeDIsGenerating && (
              <button className="tool-button" onClick={handleCancel} style={{ height: 40, color: "var(--danger)" }}>
                <Icon name="stop" size={15} />
                {text("取消", "Cancel")}
              </button>
            )}

            <span style={{ fontSize: 12, color: "var(--text-muted)" }}>
              {modeLabel} · {qualityLabel}
              {threeDGenerateMode === "multiview" ? text(` · ${multiviewFilledCount}/4 张（右侧可选）`, ` · ${multiviewFilledCount}/4 views (right optional)`) : ""}
            </span>
          </div>

          {threeDIsGenerating && (
            <div className="surface" style={{ borderRadius: 12, padding: 12 }}>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, color: "var(--text-secondary)", marginBottom: 7 }}>
                <span>{threeDProgressDesc}</span>
                <span>{Math.round(threeDProgress * 100)}%</span>
              </div>
              <div className="generating-3d-flow" style={{ height: 6, borderRadius: 999, background: "var(--bg-input)" }}>
                <div style={{ width: `${threeDProgress * 100}%`, height: "100%", background: "linear-gradient(90deg, var(--accent-warm), var(--accent-blue))", borderRadius: 999, transition: "width 0.3s ease" }} />
              </div>
            </div>
          )}

          {hasError && <div style={{ padding: "10px 12px", borderRadius: 12, background: "rgba(184, 59, 59, 0.08)", border: "1px solid rgba(184, 59, 59, 0.18)", fontSize: 13, color: "var(--danger)" }}>{threeDProgressDesc}</div>}

          {threeDModelPath && (
            <div style={{ display: "flex", alignItems: "center", gap: 9, padding: "9px 12px", borderRadius: 12, background: "rgba(63, 127, 86, 0.10)", border: "1px solid rgba(63, 127, 86, 0.22)" }}>
              <Icon name="check" size={16} style={{ color: "var(--success)" }} />
              <span style={{ fontSize: 13, color: "var(--success)", fontWeight: 760 }}>{text("模型已生成", "Model generated")}</span>
            </div>
          )}

          <div className="surface" style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column", borderRadius: 16, overflow: "hidden" }}>
            <div style={{ display: "flex", borderBottom: "1px solid var(--border-subtle)", padding: 8, gap: 6 }}>
              {tabs.map((tab) => tab.available ? (
                <button key={tab.key} className={`segment ${previewTab === tab.key ? "active" : ""}`} onClick={() => setPreviewTab(tab.key)}>
                  <Icon name={tab.icon} size={14} />
                  {tab.label}
                </button>
              ) : null)}
            </div>
            <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", padding: 16, overflow: "hidden" }}>
              {previewTab === "3d" && threeDModelPath ? (
                <ModelPreview modelPath={threeDModelPath} />
              ) : previewTab === "2d" && threeDPreview2D ? (
                <img src={assetUrl(threeDPreview2D)} alt="2d render" style={{ maxWidth: "100%", maxHeight: "100%", borderRadius: 12, objectFit: "contain" }} />
              ) : previewTab === "normal" && threeDPreviewNormal ? (
                <img src={assetUrl(threeDPreviewNormal)} alt="normal map" style={{ maxWidth: "100%", maxHeight: "100%", borderRadius: 12, objectFit: "contain" }} />
              ) : previewTab === "uv" && threeDPreviewUV ? (
                <img src={assetUrl(threeDPreviewUV)} alt="uv texture" style={{ maxWidth: "100%", maxHeight: "100%", borderRadius: 12, objectFit: "contain" }} />
              ) : threeDIsGenerating ? (
                <div style={{ textAlign: "center" }}>
                  <div style={{ width: 58, height: 58, borderRadius: "50%", border: "3px solid var(--bg-input)", borderTopColor: "var(--accent-warm)", animation: "spin 1s linear infinite", margin: "0 auto 14px" }} />
                  <p style={{ color: "var(--text-secondary)", fontSize: 13, margin: 0, fontWeight: 700 }}>{text("正在生成", "Generating")}</p>
                  <p style={{ color: "var(--text-muted)", fontSize: 11, margin: "5px 0 0" }}>{text("这可能需要 30-90 秒", "This may take 30-90 seconds")}</p>
                </div>
              ) : (
                <div style={{ textAlign: "center", color: "var(--text-muted)" }}>
                  <Icon name="box" size={44} style={{ opacity: 0.48 }} />
                  <p style={{ fontSize: 13, margin: "10px 0 0" }}>{text("上传图片或输入描述，点击生成按钮", "Upload images or enter a description, then generate")}</p>
                </div>
              )}
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
