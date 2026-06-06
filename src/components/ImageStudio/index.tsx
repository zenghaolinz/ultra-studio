import { useEffect, useState, type CSSProperties } from "react";
import { convertFileSrc, invoke } from "@tauri-apps/api/core";
import { open } from "@tauri-apps/plugin-dialog";
import { useAppStore } from "../../stores/appStore";
import type { GenerateQuality } from "../../types";
import ComfyStatus from "../ComfyStatus";
import Icon from "../Icon";
import { useLanguage } from "../../i18n";

type ImageMode = "generate" | "edit" | "video";
type BusyKind = "image" | "edit" | "views" | "model" | "video" | null;
type ViewKey = "front" | "left" | "back";
type VideoResolution = "480p" | "576p" | "720p";
type VideoAspect = "source" | "16:9" | "9:16" | "1:1" | "4:3" | "3:4";
type VideoQualityMode = "fast" | "quality" | "experimental";
type VideoStandardModel = "5b" | "14b";
type ImageLoraOption = { id: string; name: string };
type ImageLoraCatalog = {
  qualityMode: GenerateQuality;
  family: string;
  directory: string;
  items: ImageLoraOption[];
};

type MultiviewImages = {
  front?: string;
  left?: string;
  back?: string;
};

type ThreeDResult = {
  status: string;
  modelPath?: string;
  image2D?: string;
  imageNormal?: string;
  imageUV?: string;
  image1Path?: string;
  image2Path?: string;
  message?: string;
};

const VIDEO_RESOLUTIONS: Record<VideoResolution, { label: string; width: number; height: number }> = {
  "480p": { label: "480p", width: 832, height: 480 },
  "576p": { label: "576p", width: 1024, height: 576 },
  "720p": { label: "720p", width: 1280, height: 704 },
};

const VIDEO_ASPECTS: Record<Exclude<VideoAspect, "source">, { label: string; ratio: number }> = {
  "16:9": { label: "16:9", ratio: 16 / 9 },
  "9:16": { label: "9:16", ratio: 9 / 16 },
  "1:1": { label: "1:1", ratio: 1 },
  "4:3": { label: "4:3", ratio: 4 / 3 },
  "3:4": { label: "3:4", ratio: 3 / 4 },
};

type ImageDimensions = { width: number; height: number };

function roundToMultiple(value: number, multiple = 32) {
  return Math.max(256, Math.round(value / multiple) * multiple);
}

function getVideoDimensions(
  resolution: VideoResolution,
  aspect: VideoAspect,
  sourceDimensions: ImageDimensions | null
) {
  const base = VIDEO_RESOLUTIONS[resolution];
  const longEdge = Math.max(base.width, base.height);
  const sourceRatio = sourceDimensions && sourceDimensions.height > 0
    ? sourceDimensions.width / sourceDimensions.height
    : null;
  const ratio = aspect === "source" ? (sourceRatio || VIDEO_ASPECTS["16:9"].ratio) : VIDEO_ASPECTS[aspect].ratio;

  if (ratio >= 1) {
    return {
      width: roundToMultiple(longEdge),
      height: roundToMultiple(longEdge / ratio),
    };
  }

  return {
    width: roundToMultiple(longEdge * ratio),
    height: roundToMultiple(longEdge),
  };
}

const DEFAULT_PROMPTS = {
  generate: {
    zh: "一个适合转 3D 的卡通角色概念图，完整身体，白色背景，清晰轮廓",
    en: "A cartoon character concept suitable for 3D conversion, full body, white background, clear silhouette",
  },
  edit: {
    zh: "保持主体结构，把风格变得更精致，增强细节",
    en: "Keep the subject structure, refine the style, and enhance details",
  },
};

function assetUrl(localPath: string) {
  if (!localPath) return "";
  try {
    return convertFileSrc(localPath);
  } catch {
    return localPath;
  }
}

function basename(path: string) {
  return path.split(/[\\/]/).pop() || path;
}

function hasThreeViews(views: MultiviewImages | null): views is Required<MultiviewImages> {
  return !!views?.front && !!views.left && !!views.back;
}

function isVideoFile(path: string) {
  return /\.(mp4|webm|mov|mkv)$/i.test(path);
}

export default function ImageStudio() {
  const { language, text } = useLanguage();
  const setThreeDImages = useAppStore((s) => s.setThreeDImages);
  const setThreeDTextPrompt = useAppStore((s) => s.setThreeDTextPrompt);
  const setThreeDGenerateMode = useAppStore((s) => s.setThreeDGenerateMode);
  const setWorkspace = useAppStore((s) => s.setWorkspace);
  const [mode, setMode] = useState<ImageMode>("generate");
  const [quality, setQuality] = useState<GenerateQuality>("fast");
  const [imageLoras, setImageLoras] = useState<ImageLoraOption[]>([]);
  const [imageLoraEnabled, setImageLoraEnabled] = useState(false);
  const [selectedImageLoraId, setSelectedImageLoraId] = useState("");
  const [imageLoraLoading, setImageLoraLoading] = useState(false);
  const [prompt, setPrompt] = useState(() => DEFAULT_PROMPTS.generate[language]);
  const [editPrompt, setEditPrompt] = useState(() => DEFAULT_PROMPTS.edit[language]);
  const [videoPrompt, setVideoPrompt] = useState(() => language === "zh" ? "镜头缓慢推进，主体自然运动，电影感光照" : "Slow camera push-in, natural subject motion, cinematic lighting");
  const [sourceImage, setSourceImage] = useState("");
  const [videoSourceImage, setVideoSourceImage] = useState("");
  const [videoSourceEnabled, setVideoSourceEnabled] = useState(false);
  const [videoDuration, setVideoDuration] = useState(4);
  const [videoResolution, setVideoResolution] = useState<VideoResolution>("576p");
  const [videoAspect, setVideoAspect] = useState<VideoAspect>("source");
  const [videoSourceDimensions, setVideoSourceDimensions] = useState<ImageDimensions | null>(null);
  const [videoQuality, setVideoQuality] = useState<VideoQualityMode>("fast");
  const [videoStandardModel, setVideoStandardModel] = useState<VideoStandardModel>("5b");
  const [videoStandardWanFast, setVideoStandardWanFast] = useState(true);
  const [resultImage, setResultImage] = useState("");
  const [resultVideo, setResultVideo] = useState("");
  const [multiviewImages, setMultiviewImages] = useState<MultiviewImages | null>(null);
  const [activeViewKey, setActiveViewKey] = useState<ViewKey | null>(null);
  const [history, setHistory] = useState<string[]>([]);
  const [busyKind, setBusyKind] = useState<BusyKind>(null);
  const [message, setMessage] = useState("");

  const currentImage = resultImage || sourceImage;
  const currentVideoSource = videoSourceEnabled ? (videoSourceImage || currentImage) : "";
  const videoOutputDimensions = getVideoDimensions(videoResolution, videoAspect, videoSourceDimensions);
  const videoTurboWarning = mode === "video" && videoQuality === "fast" && !!currentVideoSource;
  const videoExperimentalWarning = mode === "video" && videoQuality === "experimental";
  const busy = busyKind !== null;

  useEffect(() => {
    setPrompt((value) =>
      value === DEFAULT_PROMPTS.generate.zh || value === DEFAULT_PROMPTS.generate.en
        ? DEFAULT_PROMPTS.generate[language]
        : value
    );
    setEditPrompt((value) =>
      value === DEFAULT_PROMPTS.edit.zh || value === DEFAULT_PROMPTS.edit.en
        ? DEFAULT_PROMPTS.edit[language]
        : value
    );
  }, [language]);

  useEffect(() => {
    let active = true;
    if (mode === "video") return;
    setImageLoraEnabled(false);
    setSelectedImageLoraId("");
    setImageLoraLoading(true);
    invoke<ImageLoraCatalog>("list_image_loras", { quality })
      .then((catalog) => {
        if (!active) return;
        setImageLoras(catalog.items);
        setSelectedImageLoraId(catalog.items[0]?.id || "");
      })
      .catch((e) => {
        if (!active) return;
        console.error("Image LoRA list error:", e);
        setImageLoras([]);
      })
      .finally(() => {
        if (active) setImageLoraLoading(false);
      });
    return () => {
      active = false;
    };
  }, [mode, quality]);

  useEffect(() => {
    let active = true;
    setVideoSourceDimensions(null);
    if (!currentVideoSource) return;

    const img = new Image();
    img.onload = () => {
      if (!active) return;
      setVideoSourceDimensions({
        width: img.naturalWidth,
        height: img.naturalHeight,
      });
    };
    img.onerror = () => {
      if (active) setVideoSourceDimensions(null);
    };
    img.src = assetUrl(currentVideoSource);

    return () => {
      active = false;
    };
  }, [currentVideoSource]);

  const refreshImageLoras = async () => {
    setImageLoraLoading(true);
    try {
      const catalog = await invoke<ImageLoraCatalog>("list_image_loras", { quality });
      setImageLoras(catalog.items);
      setSelectedImageLoraId((value) => catalog.items.some((item) => item.id === value) ? value : (catalog.items[0]?.id || ""));
      if (catalog.items.length === 0) setImageLoraEnabled(false);
    } catch (e) {
      setMessage(typeof e === "string" ? e : e instanceof Error ? e.message : String(e));
    } finally {
      setImageLoraLoading(false);
    }
  };

  const pickImage = async (nextMode: ImageMode = "edit") => {
    try {
      const file = await open({
        multiple: false,
        filters: [{ name: text("图片", "Images"), extensions: ["png", "jpg", "jpeg", "webp", "gif", "bmp"] }],
      });
      if (typeof file === "string") {
        setSourceImage(file);
        setMode(nextMode);
        setVideoSourceImage(file);
        if (nextMode === "video") setVideoSourceEnabled(true);
        setMultiviewImages(null);
      }
    } catch (e) {
      console.error("Image picker error:", e);
    }
  };

  const rememberResult = (path: string) => {
    setResultImage(path);
    setResultVideo("");
    setMultiviewImages(null);
    setHistory((items) => [path, ...items.filter((item) => item !== path)].slice(0, 10));
  };

  const generateImage = async () => {
    const promptText = prompt.trim();
    if (!promptText || busy) return;
    setBusyKind("image");
    setMessage(text("正在调用 Flux 生成图片...", "Using Flux to generate an image..."));
    try {
      const result = await invoke<{ status: string; imagePath?: string; message?: string }>("generate_flux_image", {
        prompt: promptText,
        quality,
        imageLoraId: imageLoraEnabled ? selectedImageLoraId : null,
      });
      if (result.status === "success" && result.imagePath) {
        rememberResult(result.imagePath);
        setMessage(text("图片已生成。可以继续编辑，或发送到 3D 工作区建模。", "Image generated. Continue editing or send it to the 3D workspace."));
      } else {
        setMessage(result.message || text("图片生成失败。", "Image generation failed."));
      }
    } catch (e) {
      setMessage(typeof e === "string" ? e : e instanceof Error ? e.message : String(e));
    } finally {
      setBusyKind(null);
    }
  };

  const generateVideo = async () => {
    const promptText = videoPrompt.trim();
    if (!promptText || busy) return;
    setBusyKind("video");
    setMessage(text("正在调用 Wan 2.2 图生视频工作流...", "Using the Wan 2.2 image-to-video workflow..."));
    try {
      const result = await invoke<{ status: string; videoPath?: string; message?: string }>("generate_wan_video", {
        imagePath: currentVideoSource || null,
        prompt: promptText,
        quality: videoQuality,
        durationSeconds: videoDuration,
        width: videoOutputDimensions.width,
        height: videoOutputDimensions.height,
        standardModel: videoStandardModel,
        loraAcceleration: videoQuality === "quality" && videoStandardModel === "5b" && videoStandardWanFast,
      });
      if (result.status === "success" && result.videoPath) {
        setResultImage("");
        setMultiviewImages(null);
        setResultVideo(result.videoPath);
        setHistory((items) => [result.videoPath!, ...items.filter((item) => item !== result.videoPath)].slice(0, 10));
        setMessage(text("视频已生成。", "Video generated."));
      } else {
        setMessage(result.message || text("视频生成失败。", "Video generation failed."));
      }
    } catch (e) {
      setMessage(typeof e === "string" ? e : e instanceof Error ? e.message : String(e));
    } finally {
      setBusyKind(null);
    }
  };

  const editImage = async () => {
    const requestText = editPrompt.trim();
    if (!sourceImage || !requestText || busy) return;
    setBusyKind("edit");
    setMessage(text("正在调用 Flux 编辑图片...", "Using Flux to edit the image..."));
    try {
      const result = await invoke<{ status: string; imagePath?: string; modelPath?: string; message?: string }>(
        "generate_3d_improve_image",
        {
          imagePath: sourceImage,
          improvementPrompt: requestText,
          quality,
          imageLoraId: imageLoraEnabled ? selectedImageLoraId : null,
        }
      );
      const output = result.imagePath || result.modelPath;
      if (result.status === "success" && output) {
        rememberResult(output);
        setMessage(text("图片已编辑完成。可以继续编辑，或发送到 3D 工作区建模。", "Image edited. Continue editing or send it to the 3D workspace."));
      } else {
        setMessage(result.message || text("图片编辑失败。", "Image editing failed."));
      }
    } catch (e) {
      setMessage(typeof e === "string" ? e : e instanceof Error ? e.message : String(e));
    } finally {
      setBusyKind(null);
    }
  };

  const sendTo3D = (path = resultImage) => {
    if (!path) return;
    setThreeDImages([path]);
    setThreeDTextPrompt(text("基于这张图片生成 3D 模型", "Generate a 3D model from this image"));
    setThreeDGenerateMode("auto");
    setWorkspace("3d_studio");
  };

  const sendViewsTo3D = (views = multiviewImages) => {
    if (!hasThreeViews(views)) return;
    setThreeDImages([views.front, views.left, "", views.back]);
    setThreeDTextPrompt(text("基于前、左、后三视图生成 3D 模型", "Generate a 3D model from the front, left, and back views"));
    setThreeDGenerateMode("multiview");
    setWorkspace("3d_studio");
  };

  const generateReferenceViews = async (source = currentImage) => {
    if (!source || busy) return null;
    setBusyKind("views");
    setActiveViewKey("front");
    setMultiviewImages({});
    setMessage(text("正在用 Flux 图片编辑工作流生成正面、左侧、背面视图...", "Generating front, left, and back views with Flux..."));
    try {
      const result = await invoke<{
        status: string;
        frontPath?: string;
        leftPath?: string;
        backPath?: string;
        message?: string;
      }>("generate_flux_multiview_images", {
        imagePath: source,
        prompt: "",
        quality,
      });
      if (result.status !== "success" || !result.frontPath || !result.leftPath || !result.backPath) {
        throw new Error(result.message || text("三视图生成失败。", "Multiview generation failed."));
      }
      const nextViews: MultiviewImages = {
        front: result.frontPath,
        left: result.leftPath,
        back: result.backPath,
      };
      setMultiviewImages(nextViews);
      setHistory((items) => [result.frontPath!, result.leftPath!, result.backPath!, ...items].filter((item, index, all) => item && all.indexOf(item) === index).slice(0, 10));

      if (!hasThreeViews(nextViews)) {
        throw new Error(text("三视图生成未完成。", "Multiview generation is incomplete."));
      }
      setMessage(text("三视图已生成。请在预览区检查后，用三视图生成 3D 模型。", "Multiview images generated. Review them in Preview, then generate a 3D model."));
      return nextViews;
    } catch (e) {
      setMessage(typeof e === "string" ? e : e instanceof Error ? e.message : String(e));
      return null;
    } finally {
      setActiveViewKey(null);
      setBusyKind(null);
    }
  };

  const generateModelFromViews = async () => {
    if (busy) return;
    let views = multiviewImages;
    if (!hasThreeViews(views)) {
      views = await generateReferenceViews();
    }
    if (!hasThreeViews(views)) return;

    setBusyKind("model");
    setMessage(text("正在用三视图生成 3D 模型...", "Generating a 3D model from multiview images..."));
    setThreeDImages([views.front, views.left, "", views.back]);
    setThreeDTextPrompt(text("基于前、左、后三视图生成 3D 模型", "Generate a 3D model from the front, left, and back views"));
    setThreeDGenerateMode("multiview");
    useAppStore.setState({
      threeDIsGenerating: true,
      threeDProgress: 0,
      threeDProgressDesc: text("图片工作区已提交三视图建模任务...", "Multiview modeling task submitted from Image workspace..."),
      threeDModelPath: null,
      threeDPreview2D: null,
      threeDPreviewNormal: null,
      threeDPreviewUV: null,
    });
    try {
      const result = await invoke<ThreeDResult>("generate_3d_multiview", {
        imagePaths: [views.front, views.left, "", views.back],
        quality,
      });
      useAppStore.setState({
        threeDIsGenerating: false,
        threeDProgress: result.status === "success" ? 1 : 0,
        threeDProgressDesc: result.message || (result.status === "success" ? text("完成", "Complete") : text("模型生成失败", "Model generation failed")),
        threeDModelPath: result.modelPath || null,
        threeDPreview2D: result.image2D || null,
        threeDPreviewNormal: result.imageNormal || null,
        threeDPreviewUV: result.imageUV || null,
        threeDSourceImage1: result.image1Path || views.front,
        threeDSourceImage2: result.image2Path || views.left,
      });
      setMessage(result.status === "success" ? text("3D 模型已生成，已切换到 3D 工作区查看。", "3D model generated. Switched to the 3D workspace.") : result.message || text("模型生成失败。", "Model generation failed."));
      setWorkspace("3d_studio");
    } catch (e) {
      const errorText = typeof e === "string" ? e : e instanceof Error ? e.message : String(e);
      useAppStore.setState({ threeDIsGenerating: false, threeDProgressDesc: `${text("错误：", "Error: ")}${errorText}` });
      setMessage(errorText);
    } finally {
      setBusyKind(null);
    }
  };

  const useAsEditSource = (path: string) => {
    setSourceImage(path);
    setMode("edit");
    setMultiviewImages(null);
  };

  return (
    <div style={{ height: "100vh", display: "flex", flexDirection: "column", background: "transparent" }}>
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
            <Icon name="image" size={17} />
          </div>
          <div>
            <h1 style={{ fontSize: 16, fontWeight: 820, margin: 0 }}>{text("图像工作区", "Visual Workspace")}</h1>
            <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>
              {text("Flux 图像 / Wan 视频 / 发送到 3D 建模", "Flux images / Wan video / send to 3D")}
            </div>
          </div>
        </div>
        <ComfyStatus />
      </header>

      <main style={{ flex: 1, minHeight: 0, display: "grid", gridTemplateColumns: "360px minmax(0, 1fr) 280px", gap: 16, padding: 18 }}>
        <aside style={{ display: "flex", flexDirection: "column", gap: 12, minHeight: 0 }}>
          <section className="surface" style={{ borderRadius: 16, padding: 14 }}>
            <div className="segmented" style={{ marginBottom: 12 }}>
              <button className={`segment ${mode === "generate" ? "active" : ""}`} onClick={() => setMode("generate")} style={{ flex: 1 }}>
                <Icon name="spark" size={14} />
                {text("生图", "Generate")}
              </button>
              <button className={`segment ${mode === "edit" ? "active" : ""}`} onClick={() => setMode("edit")} style={{ flex: 1 }}>
                <Icon name="wand" size={14} />
                {text("图片编辑", "Edit image")}
              </button>
              <button className={`segment ${mode === "video" ? "active" : ""}`} onClick={() => setMode("video")} style={{ flex: 1 }}>
                <Icon name="play" size={14} />
                {text("视频", "Video")}
              </button>
            </div>

            <div style={{ fontSize: 12, color: "var(--text-secondary)", fontWeight: 760, marginBottom: 8 }}>{text("生成质量", "Quality")}</div>
            <div className="segmented" style={{ marginBottom: 14 }}>
              {mode === "video" ? (
                <>
                  <button className={`segment ${videoQuality === "fast" ? "active" : ""}`} onClick={() => setVideoQuality("fast")} disabled={busy} style={{ flex: 1 }}>
                    {text("速度", "Speed")}
                  </button>
                  <button className={`segment ${videoQuality === "quality" ? "active" : ""}`} onClick={() => setVideoQuality("quality")} disabled={busy} style={{ flex: 1 }}>
                    {text("标准", "Standard")}
                  </button>
                  <button className={`segment ${videoQuality === "experimental" ? "active" : ""}`} onClick={() => setVideoQuality("experimental")} disabled={busy} style={{ flex: 1, fontSize: 11 }}>
                    {text("实验加速", "Experimental")}
                  </button>
                </>
              ) : (
                <>
                  <button className={`segment ${quality === "fast" ? "active" : ""}`} onClick={() => setQuality("fast")} disabled={busy} style={{ flex: 1 }}>
                    {text("快速", "Fast")}
                  </button>
                  <button className={`segment ${quality === "quality" ? "active" : ""}`} onClick={() => setQuality("quality")} disabled={busy} style={{ flex: 1 }}>
                    {text("高质量", "High quality")}
                  </button>
                </>
              )}
            </div>

            {mode !== "video" && (
              <div style={{ marginBottom: 14, padding: "10px", border: "1px solid var(--border-subtle)", borderRadius: 10, background: "var(--bg-input)" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, marginBottom: 8 }}>
                  <label style={{ display: "flex", alignItems: "center", gap: 7, fontSize: 12, fontWeight: 780, color: "var(--text-secondary)", cursor: imageLoras.length && !busy ? "pointer" : "default" }}>
                    <input
                      type="checkbox"
                      checked={imageLoraEnabled}
                      onChange={(e) => setImageLoraEnabled(e.target.checked)}
                      disabled={busy || imageLoras.length === 0}
                    />
                    {text("图像 LoRA", "Image LoRA")}
                  </label>
                  <span style={{ padding: "3px 7px", border: "1px solid var(--border-subtle)", borderRadius: 7, fontSize: 10, fontWeight: 800, color: "var(--text-muted)" }}>
                    {quality === "quality" ? "9B" : "4B"}
                  </span>
                </div>
                <div style={{ display: "flex", gap: 8 }}>
                  <select
                    value={selectedImageLoraId}
                    onChange={(e) => setSelectedImageLoraId(e.target.value)}
                    disabled={busy || imageLoraLoading || imageLoras.length === 0}
                    style={{ ...pathBoxStyle, minWidth: 0, height: 36, fontSize: 12 }}
                  >
                    {imageLoras.length === 0 ? (
                      <option value="">{imageLoraLoading ? text("正在载入...", "Loading...") : text("未找到对应 LoRA", "No matching LoRA")}</option>
                    ) : imageLoras.map((item) => (
                      <option key={item.id} value={item.id}>{item.name}</option>
                    ))}
                  </select>
                  <button
                    className="tool-button"
                    onClick={refreshImageLoras}
                    disabled={busy || imageLoraLoading}
                    style={{ height: 36, width: 36, padding: 0, flexShrink: 0 }}
                    title={text("刷新 LoRA 列表", "Refresh LoRA list")}
                  >
                    <Icon name="refresh" size={14} />
                  </button>
                </div>
                {imageLoras.length === 0 && !imageLoraLoading && (
                  <div style={{ marginTop: 7, fontSize: 11, lineHeight: 1.45, color: "var(--text-muted)" }}>
                    {quality === "quality"
                      ? text("将 9B 模型放入 lora/9b，或在根目录文件名中标明 9B。", "Place 9B models in lora/9b, or include 9B in a root-level filename.")
                      : text("将 4B 模型放入 lora/4b，或在根目录文件名中标明 4B。", "Place 4B models in lora/4b, or include 4B in a root-level filename.")}
                  </div>
                )}
              </div>
            )}

            {mode === "generate" ? (
              <>
                <label style={{ fontSize: 12, fontWeight: 760, color: "var(--text-secondary)" }}>{text("提示词", "Prompt")}</label>
                <textarea
                  value={prompt}
                  onChange={(e) => setPrompt(e.target.value)}
                  rows={7}
                  placeholder={text("描述你要生成的图片...", "Describe the image to generate...")}
                  style={inputStyle}
                />
                <button className="primary-button" onClick={generateImage} disabled={busy || !prompt.trim()} style={{ width: "100%", height: 38, marginTop: 10 }}>
                  <Icon name="spark" size={15} />
                  {busy ? text("生成中", "Generating") : text("生成图片", "Generate image")}
                </button>
              </>
            ) : mode === "edit" ? (
              <>
                <label style={{ fontSize: 12, fontWeight: 760, color: "var(--text-secondary)" }}>{text("源图片", "Source image")}</label>
                <div style={{ display: "flex", gap: 8, margin: "6px 0 10px" }}>
                  <button className="tool-button" onClick={() => pickImage("edit")} disabled={busy} style={{ height: 36 }}>
                    <Icon name="upload" size={14} />
                    {text("选择图片", "Choose image")}
                  </button>
                  <div style={pathBoxStyle} title={sourceImage}>
                    {sourceImage ? basename(sourceImage) : text("未选择图片", "No image selected")}
                  </div>
                </div>
                <label style={{ fontSize: 12, fontWeight: 760, color: "var(--text-secondary)" }}>{text("编辑要求", "Edit request")}</label>
                <textarea
                  value={editPrompt}
                  onChange={(e) => setEditPrompt(e.target.value)}
                  rows={5}
                  placeholder={text("例如：改成黑色、增加细节、变成卡通风格...", "Example: change to black, add detail, use a cartoon style...")}
                  style={inputStyle}
                />
                <button className="primary-button" onClick={editImage} disabled={busy || !sourceImage || !editPrompt.trim()} style={{ width: "100%", height: 38, marginTop: 10 }}>
                  <Icon name="wand" size={15} />
                  {busy ? text("编辑中", "Editing") : text("编辑图片", "Edit image")}
                </button>
              </>
            ) : (
              <>
                <label style={{ fontSize: 12, fontWeight: 760, color: "var(--text-secondary)" }}>{text("源图像（可选）", "Source image (optional)")}</label>
                <div style={{ display: "flex", gap: 8, margin: "6px 0 10px" }}>
                  <button className="tool-button" onClick={() => pickImage("video")} disabled={busy} style={{ height: 36 }}>
                    <Icon name="upload" size={14} />
                    {text("选择图像", "Choose image")}
                  </button>
                  <button
                    className="tool-button"
                    onClick={() => {
                      setVideoSourceEnabled(false);
                      setVideoSourceImage("");
                    }}
                    disabled={busy || !currentVideoSource}
                    style={{ height: 36, width: 36, padding: 0 }}
                    title={text("取消源图像，改用文生视频", "Clear source image and use text-to-video")}
                  >
                    <Icon name="close" size={14} />
                  </button>
                  <div style={pathBoxStyle} title={currentVideoSource}>
                    {currentVideoSource ? basename(currentVideoSource) : text("未选择图像，将使用文生视频", "No image selected, text-to-video")}
                  </div>
                </div>
                {videoTurboWarning && (
                  <div style={{ marginBottom: 10, padding: "9px 10px", borderRadius: 10, border: "1px solid rgba(192, 116, 36, 0.32)", background: "rgba(255, 244, 224, 0.72)", color: "var(--text-secondary)", fontSize: 11, lineHeight: 1.55 }}>
                    {text("速度模式使用 Turbo 蒸馏模型。它可以用于图生视频，但对图像条件不稳定，可能出现意想不到的错误；需要更稳时请选择标准模式。", "Speed mode uses the Turbo distilled model. You can still use it for image-to-video, but image conditioning may be unstable and can produce unexpected errors; choose Standard for safer results.")}
                  </div>
                )}
                {videoExperimentalWarning && (
                  <div style={{ marginBottom: 10, padding: "9px 10px", borderRadius: 10, border: "1px solid rgba(192, 116, 36, 0.32)", background: "rgba(255, 244, 224, 0.72)", color: "var(--text-secondary)", fontSize: 11, lineHeight: 1.55 }}>
                    {text("实验加速使用 fp16 与双 LoRA 的 4 步配置，速度更快，但质量与稳定性可能低于标准模式。", "Experimental acceleration uses fp16 with two LoRAs in a 4-step configuration. It is faster, but quality and stability may be lower than Standard.")}
                  </div>
                )}
                <div style={{ display: "grid", gridTemplateColumns: "1fr auto", alignItems: "center", gap: 10, marginBottom: 8 }}>
                  <label style={{ fontSize: 12, fontWeight: 760, color: "var(--text-secondary)" }}>{text("时长", "Duration")}</label>
                  <div style={{ fontSize: 12, color: "var(--text-muted)", fontWeight: 760 }}>{videoDuration}s</div>
                </div>
                <input
                  type="range"
                  min={1}
                  max={5}
                  step={1}
                  value={videoDuration}
                  onChange={(e) => setVideoDuration(Number(e.target.value))}
                  disabled={busy}
                  style={{ width: "100%", marginBottom: 8 }}
                />
                <div style={{ marginBottom: 10, color: "var(--text-muted)", fontSize: 11, lineHeight: 1.5 }}>
                  {text("最多 5 秒，对应 121 帧。", "Maximum 5 seconds, 121 frames.")}
                </div>
                <label style={{ fontSize: 12, fontWeight: 760, color: "var(--text-secondary)" }}>{text("视频比例", "Aspect ratio")}</label>
                <div className="segmented" style={{ margin: "6px 0 8px", flexWrap: "wrap" }}>
                  <button
                    className={`segment ${videoAspect === "source" ? "active" : ""}`}
                    onClick={() => setVideoAspect("source")}
                    disabled={busy}
                    style={{ flex: "1 0 84px" }}
                    title={videoSourceDimensions ? `${videoSourceDimensions.width}x${videoSourceDimensions.height}` : text("使用源图比例；没有源图时按 16:9", "Use the source image aspect, or 16:9 without a source")}
                  >
                    {text("跟随源图", "Match source")}
                  </button>
                  {(Object.keys(VIDEO_ASPECTS) as Exclude<VideoAspect, "source">[]).map((key) => (
                    <button
                      key={key}
                      className={`segment ${videoAspect === key ? "active" : ""}`}
                      onClick={() => setVideoAspect(key)}
                      disabled={busy}
                      style={{ flex: "1 0 62px" }}
                      title={VIDEO_ASPECTS[key].label}
                    >
                      {VIDEO_ASPECTS[key].label}
                    </button>
                  ))}
                </div>
                <div style={{ marginBottom: 10, color: "var(--text-muted)", fontSize: 11, lineHeight: 1.5 }}>
                  {text("当前输出", "Current output")}: {videoOutputDimensions.width}x{videoOutputDimensions.height}
                  {videoAspect === "source" && !currentVideoSource ? ` (${text("无源图时使用 16:9", "16:9 without a source")})` : ""}
                </div>
                <label style={{ fontSize: 12, fontWeight: 760, color: "var(--text-secondary)" }}>{text("尺寸档位", "Size")}</label>
                <div className="segmented" style={{ margin: "6px 0 12px" }}>
                  {(Object.keys(VIDEO_RESOLUTIONS) as VideoResolution[]).map((key) => (
                    <button
                      key={key}
                      className={`segment ${videoResolution === key ? "active" : ""}`}
                      onClick={() => setVideoResolution(key)}
                      disabled={busy}
                      style={{ flex: 1 }}
                      title={text("按所选比例自动计算宽高", "Width and height are calculated from the selected aspect ratio")}
                    >
                      {VIDEO_RESOLUTIONS[key].label}
                    </button>
                  ))}
                </div>
                {videoQuality === "quality" && (
                  <>
                    <label style={{ fontSize: 12, fontWeight: 760, color: "var(--text-secondary)" }}>{text("标准模型", "Standard model")}</label>
                    <div className="segmented" style={{ margin: "6px 0 12px" }}>
                      <button
                        className={`segment ${videoStandardModel === "5b" ? "active" : ""}`}
                        onClick={() => setVideoStandardModel("5b")}
                        disabled={busy}
                        style={{ flex: 1 }}
                      >
                        5B
                      </button>
                      <button
                        className={`segment ${videoStandardModel === "14b" ? "active" : ""}`}
                        onClick={() => setVideoStandardModel("14b")}
                        disabled={busy}
                        style={{ flex: 1 }}
                      >
                        14B
                      </button>
                    </div>
                  </>
                )}
                {videoQuality === "quality" && videoStandardModel === "5b" && (
                  <label style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, marginBottom: 12, padding: "9px 10px", borderRadius: 10, border: "1px solid var(--border-subtle)", background: "var(--bg-input)", cursor: busy ? "default" : "pointer" }}>
                    <span style={{ minWidth: 0 }}>
                      <span style={{ display: "block", fontSize: 12, fontWeight: 780, color: "var(--text-secondary)" }}>{text("WanFast 加速", "WanFast acceleration")}</span>
                      <span style={{ display: "block", marginTop: 2, fontSize: 11, color: "var(--text-muted)", lineHeight: 1.4 }}>
                        {text("默认开启单 LoRA 加速；关闭后使用纯 fp16 标准质量，但耗时显著增加。", "Enabled by default with a single LoRA; disable it for pure fp16 standard quality at substantially longer runtime.")}
                      </span>
                    </span>
                    <input
                      type="checkbox"
                      checked={videoStandardWanFast}
                      onChange={(e) => setVideoStandardWanFast(e.target.checked)}
                      disabled={busy}
                    />
                  </label>
                )}
                <label style={{ fontSize: 12, fontWeight: 760, color: "var(--text-secondary)" }}>{text("视频提示词", "Video prompt")}</label>
                <textarea
                  value={videoPrompt}
                  onChange={(e) => setVideoPrompt(e.target.value)}
                  rows={5}
                  placeholder={text("描述镜头运动、主体动作和画面风格...", "Describe camera motion, subject action, and visual style...")}
                  style={inputStyle}
                />
                <button className="primary-button" onClick={generateVideo} disabled={busy || !videoPrompt.trim()} style={{ width: "100%", height: 38, marginTop: 10 }}>
                  <Icon name="play" size={15} />
                  {busy ? text("生成中", "Generating") : text("生成视频", "Generate video")}
                </button>
              </>
            )}

            {message && <div style={{ marginTop: 10, fontSize: 12, color: "var(--text-muted)", lineHeight: 1.55 }}>{message}</div>}
          </section>

          {mode !== "video" && (
          <section className="surface" style={{ borderRadius: 16, padding: 14 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, fontWeight: 820, marginBottom: 8 }}>
              <Icon name="cube" size={15} />
              {text("三视图建模", "Multiview modeling")}
            </div>
            <div style={{ fontSize: 12, color: "var(--text-muted)", lineHeight: 1.55, marginBottom: 10 }}>
              {text("使用当前预览图或已上传源图，自动生成正面、左侧、背面，再送入 Hy3D 多视角。", "Generate front, left, and back views from the current image, then send them to Hy3D.")}
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 6, marginBottom: 10 }}>
              {[text("正面", "Front"), text("左侧", "Left"), text("背面", "Back")].map((label) => (
                <div key={label} style={{ height: 28, borderRadius: 9, border: "1px solid var(--border-subtle)", background: "var(--bg-input)", display: "grid", placeItems: "center", fontSize: 11, fontWeight: 780, color: "var(--text-secondary)" }}>
                  {label}
                </div>
              ))}
            </div>
            <div style={{ marginTop: 10 }}>
              <button className="primary-button" onClick={() => generateReferenceViews()} disabled={busy || !currentImage} style={{ width: "100%", height: 36, padding: 0 }}>
                {text("生成三视图", "Generate views")}
              </button>
            </div>
            {!currentImage && (
              <div style={{ fontSize: 11, color: "var(--text-muted)", lineHeight: 1.5, marginTop: 8 }}>
                {text("先生成图片或上传一张源图后可用。", "Generate or upload a source image first.")}
              </div>
            )}
          </section>
          )}
        </aside>

        <section className="surface" style={{ borderRadius: 18, overflow: "hidden", display: "flex", flexDirection: "column", minWidth: 0 }}>
          <div style={{ height: 46, display: "flex", alignItems: "center", justifyContent: "space-between", padding: "0 14px", borderBottom: "1px solid var(--border-subtle)" }}>
            <div style={{ fontSize: 13, fontWeight: 800 }}>{text("预览", "Preview")}</div>
            {resultImage && (
              <div style={{ display: "flex", gap: 8 }}>
                <button className="tool-button" onClick={() => navigator.clipboard.writeText(resultImage)} style={{ height: 32 }}>
                  <Icon name="copy" size={14} />
                  {text("复制路径", "Copy path")}
                </button>
              </div>
            )}
          </div>
          <div style={{ flex: 1, minHeight: 0, display: "grid", placeItems: "center", padding: 18, background: "rgba(255,254,250,0.48)" }}>
            {busyKind === "views" ? (
              <div style={{ width: "100%", maxWidth: 980 }}>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 12 }}>
                  {[
                    ["front", text("正面", "Front")],
                    ["left", text("左侧", "Left")],
                    ["back", text("背面", "Back")],
                  ].map(([key, label]) => {
                    const viewKey = key as ViewKey;
                    const path = multiviewImages?.[viewKey];
                    const isActive = activeViewKey === viewKey;
                    return (
                      <div key={key} style={{ aspectRatio: "1", borderRadius: 14, border: path ? "1px solid var(--border-subtle)" : "1px dashed var(--border-subtle)", background: "rgba(255,254,250,0.72)", overflow: "hidden", display: "grid", placeItems: "center", boxShadow: "var(--shadow-sm)", position: "relative" }}>
                        {path ? (
                          <>
                            <img src={assetUrl(path)} alt={label} style={{ width: "100%", height: "100%", objectFit: "contain", background: "#fffefa" }} />
                            <div style={{ position: "absolute", left: 8, bottom: 8, padding: "3px 7px", borderRadius: 8, background: "rgba(23,22,21,0.72)", color: "#fffefa", fontSize: 11, fontWeight: 820 }}>
                              {label}{text("已完成", " complete")}
                            </div>
                          </>
                        ) : (
                          <div style={{ textAlign: "center", color: "var(--text-secondary)" }}>
                            {isActive ? (
                              <div style={{ width: 34, height: 34, borderRadius: "50%", border: "2px solid var(--bg-input)", borderTopColor: "var(--accent-warm)", animation: "spin 1s linear infinite", margin: "0 auto 10px" }} />
                            ) : (
                              <div style={{ width: 34, height: 34, borderRadius: "50%", border: "2px solid var(--border-subtle)", margin: "0 auto 10px", opacity: 0.48 }} />
                            )}
                            <div style={{ fontSize: 13, fontWeight: 820 }}>{label}</div>
                            <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 4 }}>{isActive ? text("Flux 编辑中", "Flux editing") : text("等待生成", "Waiting")}</div>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
                <div style={{ textAlign: "center", fontSize: 12, color: "var(--text-muted)", lineHeight: 1.6, marginTop: 14 }}>
                  {text("三视图由后端统一生成并校正左侧方向，完成后会显示正面、左侧、背面预览。", "The backend generates and aligns all three views; previews appear when complete.")}
                </div>
              </div>
            ) : busy ? (
              <div style={{ textAlign: "center", color: "var(--text-secondary)" }}>
                <div style={{ width: 56, height: 56, borderRadius: "50%", border: "3px solid var(--bg-input)", borderTopColor: "var(--accent-warm)", animation: "spin 1s linear infinite", margin: "0 auto 14px" }} />
                <div style={{ fontSize: 13, fontWeight: 760 }}>
                  {busyKind === "model" ? text("正在用三视图生成 3D 模型", "Generating a 3D model from views") : text("ComfyUI 正在处理", "ComfyUI is processing")}
                </div>
              </div>
            ) : resultVideo ? (
              <div style={{ width: "100%", height: "100%", minHeight: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 14 }}>
                <video src={assetUrl(resultVideo)} controls style={{ maxWidth: "100%", maxHeight: "calc(100% - 54px)", borderRadius: 14, boxShadow: "var(--shadow-md)", background: "#111" }} />
                <button className="tool-button" onClick={() => navigator.clipboard.writeText(resultVideo)} style={{ height: 36, padding: "0 14px" }}>
                  <Icon name="copy" size={14} />
                  {text("复制视频路径", "Copy video path")}
                </button>
              </div>
            ) : multiviewImages ? (
              <div style={{ width: "100%", maxWidth: 980 }}>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 12 }}>
                  {[
                    [text("正面", "Front"), multiviewImages.front],
                    [text("左侧", "Left"), multiviewImages.left],
                    [text("背面", "Back"), multiviewImages.back],
                  ].map(([label, path]) => (
                    <div key={label} style={{ border: "1px solid var(--border-subtle)", borderRadius: 14, overflow: "hidden", background: "rgba(255,254,250,0.82)", boxShadow: "var(--shadow-sm)" }}>
                      {path ? (
                        <img src={assetUrl(path)} alt={label} style={{ width: "100%", aspectRatio: "1", objectFit: "contain", display: "block", background: "#fffefa" }} />
                      ) : (
                        <div style={{ width: "100%", aspectRatio: "1", display: "grid", placeItems: "center", background: "rgba(255,254,250,0.72)", color: "var(--text-muted)", fontSize: 12 }}>
                          {text("未生成", "Not generated")}
                        </div>
                      )}
                      <div style={{ height: 34, display: "flex", alignItems: "center", justifyContent: "space-between", padding: "0 10px", borderTop: "1px solid var(--border-subtle)" }}>
                        <span style={{ fontSize: 12, fontWeight: 820 }}>{label}</span>
                        <button className="tool-button" onClick={() => path && useAsEditSource(path)} disabled={!path} style={{ height: 24, padding: "0 8px", fontSize: 11 }}>
                          {text("编辑", "Edit")}
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
                <div style={{ display: "flex", justifyContent: "center", gap: 10, marginTop: 14 }}>
                  <button className="tool-button" onClick={() => sendViewsTo3D()} disabled={!hasThreeViews(multiviewImages)} style={{ height: 36 }}>
                    <Icon name="cube" size={14} />
                    {text("送到 3D 工作区", "Send to 3D workspace")}
                  </button>
                  <button className="primary-button" onClick={generateModelFromViews} disabled={!hasThreeViews(multiviewImages)} style={{ height: 36, padding: "0 16px" }}>
                    <Icon name="cube" size={14} />
                    {text("用三视图生成 3D 模型", "Generate 3D from views")}
                  </button>
                </div>
              </div>
            ) : resultImage ? (
              <div style={{ width: "100%", height: "100%", minHeight: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 14 }}>
                <img src={assetUrl(resultImage)} alt="generated" style={{ maxWidth: "100%", maxHeight: "calc(100% - 54px)", objectFit: "contain", borderRadius: 14, boxShadow: "var(--shadow-md)" }} />
                <button className="primary-button" onClick={() => sendTo3D()} style={{ height: 38, padding: "0 16px" }}>
                  <Icon name="cube" size={14} />
                  {text("用单图生成 3D 模型", "Generate 3D from image")}
                </button>
              </div>
            ) : sourceImage && mode === "edit" ? (
              <div style={{ width: "100%", height: "100%", minHeight: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 14 }}>
                <img src={assetUrl(sourceImage)} alt="source" style={{ maxWidth: "100%", maxHeight: "calc(100% - 54px)", objectFit: "contain", borderRadius: 14, opacity: 0.78 }} />
                <button className="primary-button" onClick={() => sendTo3D(sourceImage)} style={{ height: 38, padding: "0 16px" }}>
                  <Icon name="cube" size={14} />
                  {text("用单图生成 3D 模型", "Generate 3D from image")}
                </button>
              </div>
            ) : (
              <div style={{ textAlign: "center", color: "var(--text-muted)" }}>
                <Icon name="image" size={52} style={{ opacity: 0.5 }} />
                <div style={{ marginTop: 12, fontSize: 13 }}>{text("生成或选择一张图片后在这里预览", "Generate or select an image to preview it here")}</div>
              </div>
            )}
          </div>
        </section>

        <aside className="surface" style={{ borderRadius: 16, padding: 12, overflowY: "auto" }}>
          <div style={{ fontSize: 13, fontWeight: 820, marginBottom: 10 }}>{text("图像历史", "Visual history")}</div>
          {history.length === 0 ? (
            <div style={{ color: "var(--text-muted)", fontSize: 12, lineHeight: 1.7, padding: "18px 4px" }}>
              {text("暂无生成图像。生成后的图像或视频会出现在这里，便于继续预览、编辑或发送到 3D。", "No generated visuals yet. Generated images or videos appear here for previewing, editing, or sending to 3D.")}
            </div>
          ) : (
            <div style={{ display: "grid", gap: 10 }}>
              {history.map((item) => (
                <div key={item} style={{ border: "1px solid var(--border-subtle)", borderRadius: 12, overflow: "hidden", background: "rgba(255,254,250,0.62)" }}>
                  {isVideoFile(item) ? (
                    <video src={assetUrl(item)} style={{ width: "100%", aspectRatio: "4 / 3", objectFit: "cover", display: "block", background: "#111" }} />
                  ) : (
                    <img src={assetUrl(item)} alt="" style={{ width: "100%", aspectRatio: "4 / 3", objectFit: "cover", display: "block" }} />
                  )}
                  <div style={{ padding: 8 }}>
                    <div title={item} style={{ fontSize: 11, color: "var(--text-muted)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", marginBottom: 7 }}>
                      {basename(item)}
                    </div>
                    <div style={{ display: "flex", gap: 6 }}>
                      {isVideoFile(item) ? (
                        <button className="tool-button" onClick={() => setResultVideo(item)} style={{ height: 28, flex: 1, padding: 0 }}>
                          {text("预览", "Preview")}
                        </button>
                      ) : (
                        <>
                          <button className="tool-button" onClick={() => useAsEditSource(item)} style={{ height: 28, flex: 1, padding: 0 }}>
                            {text("编辑", "Edit")}
                          </button>
                          <button className="tool-button" onClick={() => sendTo3D(item)} style={{ height: 28, flex: 1, padding: 0 }}>
                            {text("用于 3D", "Use for 3D")}
                          </button>
                        </>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </aside>
      </main>
    </div>
  );
}

const inputStyle: CSSProperties = {
  width: "100%",
  marginTop: 6,
  resize: "none",
  borderRadius: 12,
  padding: "11px 12px",
  border: "1px solid var(--border-subtle)",
  background: "var(--bg-input)",
  color: "var(--text-primary)",
  outline: "none",
  fontSize: 13,
  lineHeight: 1.6,
};

const pathBoxStyle: CSSProperties = {
  flex: 1,
  minWidth: 0,
  height: 36,
  borderRadius: 10,
  border: "1px solid var(--border-subtle)",
  background: "var(--bg-input)",
  color: "var(--text-muted)",
  fontSize: 12,
  display: "flex",
  alignItems: "center",
  padding: "0 10px",
  overflow: "hidden",
  textOverflow: "ellipsis",
  whiteSpace: "nowrap",
};
