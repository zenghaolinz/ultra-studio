import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { convertFileSrc, invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { open, save } from "@tauri-apps/plugin-dialog";
import { useAppStore } from "../../stores/appStore";
import type { GenerationTask, Message, ToolActivityEvent } from "../../types";
import ModelPreview from "../ThreeDStudio/ModelPreview";
import Icon from "../Icon";
import { useLanguage } from "../../i18n";

type ThreeDAsset = {
  modelPath: string;
  image2D?: string;
  imageNormal?: string;
  imageUV?: string;
};

type DocumentAsset = {
  path: string;
  label: string;
  type: "docx" | "pdf" | "text" | "file";
};

type ImageAsset = {
  path: string;
  label: string;
};

type MultiviewAsset = {
  front: string;
  left: string;
  back: string;
};

type PathResolutionRequest = {
  query: string;
  candidates: { type: string; path: string }[];
};

type DeleteConfirmationRequest = {
  target: string;
  targetType: string;
  warning?: string;
  continuation?: string;
};

type CommandConfirmationRequest = {
  command: string;
  cwd: string;
  warning?: string;
};

type ProjectCheckConfirmationRequest = {
  path: string;
  checkType: string;
  commands: string[];
  warning?: string;
};

type ImplementationChoiceRequest = {
  query: string;
  options: { id: string; title: string; description: string }[];
};

type AgentTrace = {
  model?: string;
  provider?: string;
  vision?: boolean;
  vision_reason?: string;
  action?: string;
  tool?: string;
  source?: string;
  reason?: string;
  prompt?: string;
  source_files?: string[];
  attached_images?: string[];
  attached_documents?: string[];
  project_documents?: string[];
  project_images?: string[];
  project_files?: { type?: string; path?: string; name?: string }[];
  latest_active_image?: string;
  outputs?: string[];
};

type DragDropPayload = {
  paths?: string[];
};

type AssetItem =
  | { id: string; kind: "3d"; title: string; path: string; preview?: string; asset: ThreeDAsset }
  | { id: string; kind: "doc"; title: string; path: string; doc: DocumentAsset }
  | { id: string; kind: "image"; title: string; path: string };

function isMarkdownTableSeparator(line: string) {
  return /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(line);
}

function splitMarkdownRow(line: string) {
  return line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((cell) => cell.trim());
}

function isMarkdownBlockStart(line: string, nextLine = "") {
  const trimmed = line.trim();
  return /^#{1,6}\s+/.test(trimmed)
    || /^-{3,}$/.test(trimmed)
    || /^```/.test(trimmed)
    || /^[-*+]\s+/.test(trimmed)
    || /^\d+\.\s+/.test(trimmed)
    || /^>\s?/.test(trimmed)
    || (trimmed.startsWith("|") && isMarkdownTableSeparator(nextLine));
}

function renderInlineMarkdown(text: string, keyPrefix: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  const pattern = /(`[^`]+`|\*\*[\s\S]+?\*\*|\[[^\]]+\]\((https?:\/\/[^)\s]+)\))/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(text))) {
    if (match.index > lastIndex) nodes.push(text.slice(lastIndex, match.index));
    const token = match[0];
    const key = `${keyPrefix}-${match.index}`;
    if (token.startsWith("`")) {
      nodes.push(<code key={key}>{token.slice(1, -1)}</code>);
    } else if (token.startsWith("**")) {
      nodes.push(<strong key={key}>{renderInlineMarkdown(token.slice(2, -2), `${key}-strong`)}</strong>);
    } else {
      const label = token.match(/^\[([^\]]+)\]/)?.[1] || match[2];
      nodes.push(<a key={key} href={match[2]} target="_blank" rel="noreferrer">{label}</a>);
    }
    lastIndex = match.index + token.length;
  }
  if (lastIndex < text.length) nodes.push(text.slice(lastIndex));
  return nodes;
}

function MarkdownContent({ content }: { content: string }) {
  const lines = content.replace(/\r\n/g, "\n").split("\n");
  const blocks: ReactNode[] = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index];
    const trimmed = line.trim();
    if (!trimmed) {
      index += 1;
      continue;
    }

    if (/^```/.test(trimmed)) {
      const codeLines: string[] = [];
      index += 1;
      while (index < lines.length && !lines[index].trim().startsWith("```")) {
        codeLines.push(lines[index]);
        index += 1;
      }
      if (index < lines.length) index += 1;
      blocks.push(<pre key={`code-${index}`} className="markdown-code-block"><code>{codeLines.join("\n")}</code></pre>);
      continue;
    }

    const heading = trimmed.match(/^(#{1,6})\s+(.+)$/);
    if (heading) {
      const level = Math.min(heading[1].length, 4);
      const headingContent = renderInlineMarkdown(heading[2], `heading-${index}`);
      if (level === 1) blocks.push(<h1 key={`heading-${index}`}>{headingContent}</h1>);
      else if (level === 2) blocks.push(<h2 key={`heading-${index}`}>{headingContent}</h2>);
      else if (level === 3) blocks.push(<h3 key={`heading-${index}`}>{headingContent}</h3>);
      else blocks.push(<h4 key={`heading-${index}`}>{headingContent}</h4>);
      index += 1;
      continue;
    }

    if (/^-{3,}$/.test(trimmed)) {
      blocks.push(<hr key={`hr-${index}`} />);
      index += 1;
      continue;
    }

    if (trimmed.startsWith("|") && isMarkdownTableSeparator(lines[index + 1] || "")) {
      const headers = splitMarkdownRow(trimmed);
      index += 2;
      const rows: string[][] = [];
      while (index < lines.length && lines[index].trim().startsWith("|")) {
        rows.push(splitMarkdownRow(lines[index]));
        index += 1;
      }
      blocks.push(
        <div key={`table-${index}`} className="markdown-table-wrap">
          <table>
            <thead><tr>{headers.map((cell, cellIndex) => <th key={cellIndex}>{renderInlineMarkdown(cell, `th-${index}-${cellIndex}`)}</th>)}</tr></thead>
            <tbody>
              {rows.map((row, rowIndex) => (
                <tr key={rowIndex}>
                  {headers.map((_, cellIndex) => <td key={cellIndex}>{renderInlineMarkdown(row[cellIndex] || "", `td-${index}-${rowIndex}-${cellIndex}`)}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>,
      );
      continue;
    }

    if (/^[-*+]\s+/.test(trimmed) || /^\d+\.\s+/.test(trimmed)) {
      const ordered = /^\d+\.\s+/.test(trimmed);
      const items: string[] = [];
      while (index < lines.length) {
        const item = lines[index].trim().match(ordered ? /^\d+\.\s+(.+)$/ : /^[-*+]\s+(.+)$/);
        if (!item) break;
        items.push(item[1]);
        index += 1;
      }
      const ListTag = ordered ? "ol" : "ul";
      blocks.push(<ListTag key={`list-${index}`}>{items.map((item, itemIndex) => <li key={itemIndex}>{renderInlineMarkdown(item, `li-${index}-${itemIndex}`)}</li>)}</ListTag>);
      continue;
    }

    if (/^>\s?/.test(trimmed)) {
      const quoteLines: string[] = [];
      while (index < lines.length && /^>\s?/.test(lines[index].trim())) {
        quoteLines.push(lines[index].trim().replace(/^>\s?/, ""));
        index += 1;
      }
      blocks.push(<blockquote key={`quote-${index}`}>{renderInlineMarkdown(quoteLines.join(" "), `quote-${index}`)}</blockquote>);
      continue;
    }

    const paragraphLines = [trimmed];
    index += 1;
    while (index < lines.length && lines[index].trim() && !isMarkdownBlockStart(lines[index], lines[index + 1] || "")) {
      paragraphLines.push(lines[index].trim());
      index += 1;
    }
    blocks.push(<p key={`p-${index}`}>{renderInlineMarkdown(paragraphLines.join(" "), `p-${index}`)}</p>);
  }

  return <div className="markdown-message">{blocks}</div>;
}

function assetUrl(localPath: string) {
  if (!localPath) return "";
  if (localPath.startsWith("http")) return localPath;
  try {
    return convertFileSrc(localPath);
  } catch {
    return localPath;
  }
}

function basename(path: string) {
  return path.split(/[\\/]/).pop() || path;
}

function isImageFile(path: string) {
  return /\.(png|jpe?g|webp|gif|bmp)$/i.test(path);
}

function isDocumentFile(path: string) {
  return /\.(pdf|docx|txt|md|markdown|csv|json|jsonl|ya?ml|xml|html|css|jsx?|tsx?|py|rs|toml|ini|log)$/i.test(path);
}

function docType(path: string): DocumentAsset["type"] {
  const ext = path.split(".").pop()?.toLowerCase() || "";
  if (ext === "docx") return "docx";
  if (ext === "pdf") return "pdf";
  if (isDocumentFile(path)) return "text";
  return "file";
}

function defaultAttachmentPrompt(paths: string[], language: "zh" | "en") {
  if (paths.every(isImageFile)) return language === "zh" ? "请分析这些图片。" : "Please analyze these images.";
  if (paths.some(isDocumentFile)) return language === "zh" ? "请阅读并分析这些附件。" : "Please read and analyze these attachments.";
  return language === "zh" ? "请处理这些附件。" : "Please process these attachments.";
}

function normalizeDroppedPaths(payload: unknown) {
  if (!payload || typeof payload !== "object") return [];
  const paths = (payload as DragDropPayload).paths;
  return Array.isArray(paths) ? paths.filter((path): path is string => typeof path === "string" && path.trim().length > 0) : [];
}

function parseThreeDAsset(content: string): ThreeDAsset | null {
  const read = (...patterns: RegExp[]) => {
    for (const pattern of patterns) {
      const match = content.match(pattern);
      if (match?.[1]) return match[1].trim();
    }
    return undefined;
  };
  const modelPath = read(/3D\s*模型\s*:\s*`([^`]+)`/i, /3D\s*model\s*:\s*`([^`]+)`/i);
  if (!modelPath) return null;
  return {
    modelPath,
    image2D: read(/预览图\s*:\s*`([^`]+)`/, /preview\s*:\s*`([^`]+)`/i),
    imageNormal: read(/法线图\s*:\s*`([^`]+)`/, /normal\s*:\s*`([^`]+)`/i),
    imageUV: read(/UV\s*贴图\s*:\s*`([^`]+)`/i, /texture\s*:\s*`([^`]+)`/i),
  };
}

function parseDocumentAssets(content: string): DocumentAsset[] {
  const results: DocumentAsset[] = [];
  const seen = new Set<string>();
  const patterns = [
    /(?:Word 文档|文档|文件|整理文档|已创建文件)[:：]?\s*`([^`]+\.(?:docx|pdf|txt|md|csv|json|jsonl|ya?ml|html?|css|jsx?|tsx?|py|rs|toml|ini|log))`/gi,
    /`([^`]+\.(?:docx|pdf|txt|md|csv|json|jsonl|ya?ml|html?|css|jsx?|tsx?|py|rs|toml|ini|log))`/gi,
  ];
  for (const pattern of patterns) {
    let match: RegExpExecArray | null;
    while ((match = pattern.exec(content))) {
      const path = match[1].trim();
      if (seen.has(path)) continue;
      seen.add(path);
      results.push({ path, label: basename(path), type: docType(path) });
    }
  }
  return results;
}

function parseGeneratedImageAssets(content: string): ImageAsset[] {
  const results: ImageAsset[] = [];
  const seen = new Set<string>();
  const patterns = [
    /(?:生成图片|编辑后图片)\s*:\s*`([^`]+\.(?:png|jpg|jpeg|webp|bmp))`/gi,
    /活跃图像路径="([^"]+\.(?:png|jpg|jpeg|webp|bmp))"/gi,
  ];
  for (const pattern of patterns) {
    let match: RegExpExecArray | null;
    while ((match = pattern.exec(content))) {
      const path = match[1].trim();
      if (/^(正面|左侧|背面)\s*[:：]/.test(content.slice(Math.max(0, match.index - 4), match.index + 4))) continue;
      if (seen.has(path)) continue;
      seen.add(path);
      results.push({ path, label: basename(path) });
    }
  }
  return results;
}

function cleanMultiviewPath(raw: string) {
  const cleaned = raw.trim().replace(/^[`"']+|[`"']+$/g, "").trim();
  const match = cleaned.match(/([A-Za-z]:[\\/].+?\.(?:png|jpg|jpeg|webp|bmp))/i);
  return (match?.[1] || cleaned).replace(/[`"']+$/g, "").trim();
}

function parseMultiviewAsset(content: string): MultiviewAsset | null {
  const paths: Partial<MultiviewAsset> = {};
  const assign = (label: string, raw: string) => {
    const path = cleanMultiviewPath(raw);
    if (!isImageFile(path)) return;
    if (label === "正面") paths.front = path;
    if (label === "左侧") paths.left = path;
    if (label === "背面") paths.back = path;
  };

  for (const line of content.split(/\r?\n/)) {
    const labelled = line.match(/^\s*(正面|左侧|背面)\s*[:：]\s*(.+?)\s*$/);
    if (labelled) assign(labelled[1], labelled[2]);

    const context = line.match(/活跃三视图(正面|左侧|背面)=["']([^"']+)["']/);
    if (context) assign(context[1], context[2]);
  }

  return paths.front && paths.left && paths.back
    ? { front: paths.front, left: paths.left, back: paths.back }
    : null;
}

function parsePathResolutionRequest(content: string): PathResolutionRequest | null {
  const block = content.match(/\[PATH_RESOLUTION_REQUIRED\]([\s\S]*?)\[\/PATH_RESOLUTION_REQUIRED\]/);
  if (!block) return null;
  const body = block[1];
  const query = body.match(/查询:\s*(.+)/)?.[1]?.trim() || "";
  const candidates = [...body.matchAll(/-\s*([^:：]+)[:：]\s*`([^`]+)`/g)].map((match) => ({
    type: match[1].trim(),
    path: match[2].trim(),
  }));
  return { query, candidates };
}

function parseDeleteConfirmationRequest(content: string): DeleteConfirmationRequest | null {
  const block = content.match(/\[CONFIRM_DELETE_REQUIRED\]([\s\S]*?)\[\/CONFIRM_DELETE_REQUIRED\]/);
  if (!block) return null;
  const body = block[1];
  const target = body.match(/目标:\s*`([^`]+)`/)?.[1]?.trim() || "";
  const targetType = body.match(/类型:\s*(.+)/)?.[1]?.trim() || "文件";
  const warning = body.match(/提示:\s*(.+)/)?.[1]?.trim();
  const continuation = body.match(/后续任务:\s*`([^`]+)`/)?.[1]?.trim();
  if (!target) return null;
  return { target, targetType, warning, continuation };
}

function parseCommandConfirmationRequest(content: string): CommandConfirmationRequest | null {
  const block = content.match(/\[CONFIRM_COMMAND_REQUIRED\]([\s\S]*?)\[\/CONFIRM_COMMAND_REQUIRED\]/);
  if (!block) return null;
  const body = block[1];
  const command = body.match(/命令:\s*`([^`]+)`/)?.[1]?.trim() || "";
  const cwd = body.match(/目录:\s*`([^`]+)`/)?.[1]?.trim() || "";
  const warning = body.match(/提示:\s*(.+)/)?.[1]?.trim();
  if (!command) return null;
  return { command, cwd, warning };
}

function parseProjectCheckConfirmationRequest(content: string): ProjectCheckConfirmationRequest | null {
  const block = content.match(/\[CONFIRM_PROJECT_CHECK_REQUIRED\]([\s\S]*?)\[\/CONFIRM_PROJECT_CHECK_REQUIRED\]/);
  if (!block) return null;
  const body = block[1];
  const path = body.match(/项目:\s*`([^`]+)`/)?.[1]?.trim() || "";
  const checkType = body.match(/类型:\s*(.+)/)?.[1]?.trim() || "auto";
  const commands = [...body.matchAll(/-\s*`([^`]+)`/g)].map((match) => match[1].trim());
  const warning = body.match(/提示:\s*(.+)/)?.[1]?.trim();
  if (!path) return null;
  return { path, checkType, commands, warning };
}

function parseImplementationChoiceRequest(content: string): ImplementationChoiceRequest | null {
  const block = content.match(/\[IMPLEMENTATION_CHOICE_REQUIRED\]([\s\S]*?)\[\/IMPLEMENTATION_CHOICE_REQUIRED\]/);
  if (!block) return null;
  const body = block[1];
  const query = body.match(/需求:\s*(.+)/)?.[1]?.trim() || "";
  const options = [...body.matchAll(/-\s*([^:：]+)[:：]\s*(.+)/g)].map((match) => {
    const id = match[1].trim();
    const description = match[2].trim();
    const title = description.split(/[，,]/)[0] || id;
    return { id, title, description };
  });
  if (options.length === 0) return null;
  return { query, options };
}

function parseAgentTrace(content: string): AgentTrace | null {
  const block = content.match(/\[AGENT_TRACE\]([\s\S]*?)\[\/AGENT_TRACE\]/);
  if (!block) return null;
  try {
    return JSON.parse(block[1]) as AgentTrace;
  } catch {
    return null;
  }
}

const textualToolBlockPattern = /<\s*\|\s*\|\s*DSML\s*\|\s*\|\s*tool_calls\s*>[\s\S]*?<\/\s*\|\s*\|\s*DSML\s*\|\s*\|\s*tool_calls\s*>/gi;
const textualToolMarkerPattern = /<\s*\/?\s*\|\s*\|\s*DSML\s*\|\s*\|/i;

function stripTextualToolBlocks(content: string) {
  const stripped = content.replace(textualToolBlockPattern, "").trim();
  const markerIndex = stripped.search(textualToolMarkerPattern);
  if (markerIndex < 0) return stripped;
  return stripped.slice(0, markerIndex).trim();
}

function stripActionBlocks(content: string) {
  return stripTextualToolBlocks(content)
    .replace(/\[PATH_RESOLUTION_REQUIRED\][\s\S]*?\[\/PATH_RESOLUTION_REQUIRED\]/g, "")
    .replace(/\[CONFIRM_DELETE_REQUIRED\][\s\S]*?\[\/CONFIRM_DELETE_REQUIRED\]/g, "")
    .replace(/\[CONFIRM_COMMAND_REQUIRED\][\s\S]*?\[\/CONFIRM_COMMAND_REQUIRED\]/g, "")
    .replace(/\[CONFIRM_PROJECT_CHECK_REQUIRED\][\s\S]*?\[\/CONFIRM_PROJECT_CHECK_REQUIRED\]/g, "")
    .replace(/\[IMPLEMENTATION_CHOICE_REQUIRED\][\s\S]*?\[\/IMPLEMENTATION_CHOICE_REQUIRED\]/g, "")
    .replace(/\[AGENT_TRACE\][\s\S]*?\[\/AGENT_TRACE\]/g, "")
    .replace(/^\[System Context:[^\n\r]*(?:\r?\n)?/gm, "")
    .trim();
}

function stripMultiviewAssetLines(content: string) {
  return content
    .split("\n")
    .filter((line) => !/^\s*(正面|左侧|背面)\s*[:：]/.test(line))
    .filter((line) => !/^\[System Context:\s*活跃三视图/.test(line))
    .join("\n")
    .trim();
}

function stripThreeDAssetLines(content: string) {
  return content
    .split("\n")
    .filter((line) => !/^\s*(3D\s*模型|预览图|法线图|UV\s*贴图|重建源图)\s*:/.test(line))
    .join("\n")
    .trim();
}

function stripTransientProgressLines(content: string) {
  return content
    .split("\n")
    .filter((line) => !/^\s*(?:已开始进行文字生成 3D|收到图片，已开始进行图片转 3D)。生成可能需要一点时间，我会在完成后直接返回模型预览和导出选项。\s*$/.test(line))
    .filter((line) => !/^\s*已根据你的要求选择 (?:3D|三视图生成|图片生成|图片编辑\/补全)工作流/.test(line))
    .join("\n")
    .trim();
}

function stripPrivateGenerationLines(content: string) {
  return content
    .split("\n")
    .filter((line) => !/^\s*(?:生成图片|编辑后图片|使用提示词)\s*[:：]/.test(line))
    .join("\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function translateAssistantContent(content: string, language: "zh" | "en") {
  if (language === "zh") return content;
  return content
    .replaceAll("生成图片已完成。", "Image generated.")
    .replaceAll("编辑后图片已完成。", "Image edited.")
    .replaceAll("三视图已生成。", "Multiview images generated.")
    .replaceAll("可以继续要求我用这三张已知视角图片生成 3D 模型。", "You can continue by generating a 3D model from these known views.")
    .replaceAll("图片任务失败。", "Image task failed.")
    .replaceAll("原因:", "Reason:")
    .replaceAll("已完成。", " complete.");
}

function diagnoseError(content: string, language: "zh" | "en") {
  const lowerContent = content.toLowerCase();
  const localized = (zh: string, en: string) => language === "zh" ? zh : en;
  if (!lowerContent.includes("error") && !content.includes("失败") && !content.includes("Errno") && !lowerContent.includes("traceback")) {
    return null;
  }
  if (lowerContent.includes("tool_choice") || lowerContent.includes("invalidparameter") || lowerContent.includes("invalid_parameter_error")) {
    return localized("诊断：聊天模型接口参数不兼容，不是 ComfyUI 报错。后端已改为兼容模式，重启后再试。", "Diagnosis: the chat model API parameters are incompatible; this is not a ComfyUI error. Restart the backend and retry.");
  }
  if (lowerContent.includes("mat1 and mat2 shapes cannot be multiplied")) {
    return localized("诊断：Flux 模型和文本编码器维度不匹配，请检查 UNet/GGUF 与文本编码器是否来自同一套配置。", "Diagnosis: the Flux model and text encoder dimensions do not match. Check that UNet/GGUF and the text encoder use the same configuration.");
  }
  if (lowerContent.includes("out of memory") || (lowerContent.includes("cuda") && lowerContent.includes("memory"))) {
    return localized("诊断：显存不足。建议关闭其他显存占用程序，或使用快速/低显存模式后重试。", "Diagnosis: GPU memory is insufficient. Close other GPU-intensive programs or retry in fast/low-memory mode.");
  }
  if (lowerContent.includes("connection refused") || lowerContent.includes("8188")) {
    return localized("诊断：ComfyUI 可能未就绪或端口不可用。请等待顶部状态变为就绪后重试。", "Diagnosis: ComfyUI may not be ready or its port is unavailable. Wait for Ready status, then retry.");
  }
  if (lowerContent.includes("invalid argument") || lowerContent.includes("transparentbgsession")) {
    return localized("诊断：ComfyUI 节点输入或残留状态异常，重启 ComfyUI 后通常可恢复。", "Diagnosis: a ComfyUI node input or stale state is invalid. Restarting ComfyUI usually resolves it.");
  }
  return localized("诊断：任务执行失败。复制错误信息继续让我分析会更快定位。", "Diagnosis: task execution failed. Share the error details to pinpoint the issue more quickly.");
}

function collectAssets(messages: { id: string; role: string; content: string; images?: string[] }[]): AssetItem[] {
  const items: AssetItem[] = [];
  const seen = new Set<string>();
  for (const msg of messages) {
    if (msg.role === "assistant") {
      const threeD = parseThreeDAsset(msg.content);
      if (threeD && !seen.has(threeD.modelPath)) {
        seen.add(threeD.modelPath);
        items.push({ id: `${msg.id}-3d`, kind: "3d", title: basename(threeD.modelPath), path: threeD.modelPath, preview: threeD.image2D, asset: threeD });
      }
      for (const doc of parseDocumentAssets(msg.content)) {
        if (seen.has(doc.path)) continue;
        seen.add(doc.path);
        items.push({ id: `${msg.id}-${doc.path}`, kind: "doc", title: doc.label, path: doc.path, doc });
      }
      for (const image of parseGeneratedImageAssets(msg.content)) {
        if (seen.has(image.path)) continue;
        seen.add(image.path);
        items.push({ id: `${msg.id}-${image.path}`, kind: "image", title: image.label, path: image.path });
      }
    }
    for (const path of msg.images || []) {
      if (seen.has(path)) continue;
      seen.add(path);
      if (isImageFile(path)) {
        items.push({ id: `${msg.id}-${path}`, kind: "image", title: basename(path), path });
      } else if (isDocumentFile(path)) {
        items.push({ id: `${msg.id}-${path}`, kind: "doc", title: basename(path), path, doc: { path, label: basename(path), type: docType(path) } });
      }
    }
  }
  return items.slice(-8).reverse();
}

function taskIdsFromContent(content: string) {
  const ids = new Set<string>();
  const patterns = [
    /\u4efb\u52a1\s*ID\s*[:\uff1a]\s*`?([a-f0-9]{20,})`?/gi,
    /Task\s*ID\s*[:\uff1a]\s*`?([a-f0-9]{20,})`?/gi,
  ];
  for (const pattern of patterns) {
    let match: RegExpExecArray | null;
    while ((match = pattern.exec(content))) {
      ids.add(match[1]);
    }
  }
  return Array.from(ids);
}

function collectTaskIds(messages: { role: string; content: string }[]) {
  const ids = new Set<string>();
  for (const msg of messages) {
    if (msg.role !== "assistant") continue;
    for (const id of taskIdsFromContent(msg.content)) ids.add(id);
  }
  return Array.from(ids);
}

function taskOutputPath(task: GenerationTask) {
  return (
    task.outputPaths.modelPath ||
    task.outputPaths.imagePath ||
    task.outputPaths.videoPath ||
    task.outputPaths.image2D ||
    task.outputPaths.path ||
    ""
  );
}

function ChatGenerationTasks({ messages, onToast }: { messages: Message[]; onToast: (text: string) => void }) {
  const { text } = useLanguage();
  const taskIds = useMemo(() => collectTaskIds(messages), [messages]);
  const [tasks, setTasks] = useState<GenerationTask[]>([]);

  const refresh = useCallback(async () => {
    if (taskIds.length === 0) {
      setTasks([]);
      return;
    }
    try {
      const result = await invoke<GenerationTask[]>("list_generation_tasks", { limit: 80 });
      const wanted = new Set(taskIds);
      setTasks(result.filter((task) => wanted.has(task.id)));
    } catch {
      setTasks([]);
    }
  }, [taskIds]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    if (taskIds.length === 0) return;
    const hasPending = tasks.length === 0 || tasks.some((task) => task.status === "queued" || task.status === "running");
    if (!hasPending) return;
    const timer = window.setInterval(refresh, 2500);
    return () => window.clearInterval(timer);
  }, [refresh, taskIds.length, tasks]);

  if (taskIds.length === 0 || tasks.length === 0) return null;

  return (
    <div style={{ width: "min(760px, 100%)", display: "flex", flexDirection: "column", gap: 10, margin: "4px 0 14px 42px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, color: "var(--text-muted)", fontWeight: 760 }}>
        <Icon name="clock" size={14} />
        {text("\u751f\u6210\u4efb\u52a1", "Generation tasks")}
      </div>
      {tasks.map((task) => (
        <ChatGenerationTaskCard key={task.id} task={task} onToast={onToast} />
      ))}
    </div>
  );
}

function ChatGenerationTaskCard({ task, onToast }: { task: GenerationTask; onToast: (text: string) => void }) {
  const { text } = useLanguage();
  const output = taskOutputPath(task);
  const title = task.taskType.replaceAll("_", " ");
  const statusText =
    task.status === "success"
      ? text("\u5df2\u5b8c\u6210", "Complete")
      : task.status === "error"
        ? text("\u5931\u8d25", "Failed")
        : task.status === "running"
          ? text("\u751f\u6210\u4e2d", "Running")
          : text("\u6392\u961f\u4e2d", "Queued");
  const statusColor =
    task.status === "success"
      ? "var(--success)"
      : task.status === "error"
        ? "var(--danger)"
        : task.status === "running"
          ? "var(--accent-warm)"
          : "var(--accent-blue)";

  if (task.status === "success" && task.outputPaths.modelPath) {
    return (
      <ThreeDAssetCard
        asset={{
          modelPath: task.outputPaths.modelPath,
          image2D: task.outputPaths.image2D || undefined,
          imageNormal: task.outputPaths.imageNormal || undefined,
          imageUV: task.outputPaths.imageUV || undefined,
        }}
      />
    );
  }

  if (task.status === "success" && task.outputPaths.imagePath) {
    return <ImageAssetCard image={{ label: basename(task.outputPaths.imagePath), path: task.outputPaths.imagePath }} onToast={onToast} />;
  }

  if (task.status === "success" && task.outputPaths.videoPath) {
    return (
      <div className="surface" style={{ width: "min(560px, 100%)", borderRadius: 16, overflow: "hidden" }}>
        <video src={assetUrl(task.outputPaths.videoPath)} controls style={{ width: "100%", display: "block", background: "var(--bg-input)", maxHeight: 360 }} />
        <div style={{ padding: 12, display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 14, fontWeight: 820 }}>{text("\u89c6\u9891\u5df2\u751f\u6210", "Video generated")}</div>
            <div title={task.outputPaths.videoPath} style={{ fontSize: 12, color: "var(--text-muted)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{basename(task.outputPaths.videoPath)}</div>
          </div>
          <button className="icon-button" onClick={() => navigator.clipboard.writeText(task.outputPaths.videoPath || "")} title={text("\u590d\u5236\u8def\u5f84", "Copy path")}><Icon name="copy" size={15} /></button>
        </div>
      </div>
    );
  }

  return (
    <div className="surface" style={{ width: "min(560px, 100%)", borderRadius: 14, padding: 12, borderColor: task.status === "error" ? "rgba(184,59,59,0.22)" : undefined }}>
      <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
        <span style={{ width: 9, height: 9, borderRadius: 999, background: statusColor, flexShrink: 0 }} />
        <b style={{ fontSize: 13, color: "var(--text-primary)", flex: 1 }}>{title}</b>
        <span style={{ fontSize: 11, color: statusColor, fontWeight: 800 }}>{statusText}</span>
      </div>
      <div style={{ marginTop: 7, fontSize: 12, color: "var(--text-muted)" }}>
        {text("\u4efb\u52a1 ID\uff1a", "Task ID: ")}<code>{task.id}</code>
      </div>
      {task.error && <div style={{ marginTop: 7, fontSize: 12, color: "var(--danger)", lineHeight: 1.5 }}>{task.error}</div>}
      {output && <div style={{ marginTop: 7, fontSize: 12, color: "var(--text-muted)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{output}</div>}
    </div>
  );
}

function AttachmentTile({ path, onRemove, compact = false }: { path: string; onRemove?: () => void; compact?: boolean }) {
  const { text } = useLanguage();
  if (isImageFile(path)) {
    return (
      <div className="surface" style={{ position: "relative", width: compact ? 88 : 70, height: compact ? 88 : 70, borderRadius: 12, overflow: "hidden" }}>
        <img src={assetUrl(path)} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} />
        {onRemove && <button className="icon-button" onClick={onRemove} title={text("移除附件", "Remove attachment")} style={{ position: "absolute", top: 4, right: 4, width: 22, height: 22 }}><Icon name="close" size={13} /></button>}
      </div>
    );
  }
  return (
    <div className="surface" title={path} style={{ position: "relative", display: "flex", alignItems: "center", gap: 8, maxWidth: compact ? 260 : 220, minHeight: compact ? 42 : 50, padding: onRemove ? "8px 32px 8px 10px" : "8px 10px", borderRadius: 12 }}>
      <Icon name="file" size={17} style={{ color: "var(--accent-blue)", flexShrink: 0 }} />
      <span style={{ fontSize: 12, color: "var(--text-secondary)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{basename(path)}</span>
      {onRemove && <button className="icon-button" onClick={onRemove} title={text("移除附件", "Remove attachment")} style={{ position: "absolute", right: 5, width: 22, height: 22, border: "none", background: "transparent" }}><Icon name="close" size={13} /></button>}
    </div>
  );
}

function DocumentAssetCard({ doc, onToast }: { doc: DocumentAsset; onToast: (text: string) => void }) {
  const { text } = useLanguage();
  const copyPath = async () => {
    await navigator.clipboard.writeText(doc.path);
    onToast(text("已复制文件路径", "File path copied"));
  };
  const reveal = async () => {
    try {
      await invoke("reveal_path", { path: doc.path });
    } catch {
      onToast(text("无法打开所在位置", "Unable to open location"));
    }
  };
  return (
    <div className="doc-card surface">
      <div className="doc-card-icon"><Icon name={doc.type === "pdf" ? "layers" : "file"} size={17} /></div>
      <div className="doc-card-main">
        <div className="doc-card-title">{doc.label}</div>
        <div className="doc-card-path">{text("已生成文档", "Generated document")}</div>
      </div>
      <button className="icon-button" onClick={copyPath} title={text("复制路径", "Copy path")}><Icon name="copy" size={15} /></button>
      <button className="icon-button" onClick={reveal} title={text("打开位置", "Open location")}><Icon name="search" size={15} /></button>
    </div>
  );
}

function ImageAssetCard({ image, onToast }: { image: ImageAsset; onToast: (text: string) => void }) {
  const { text } = useLanguage();
  const setThreeDImages = useAppStore((s) => s.setThreeDImages);
  const setThreeDTextPrompt = useAppStore((s) => s.setThreeDTextPrompt);
  const setWorkspace = useAppStore((s) => s.setWorkspace);
  const sendTo3D = () => {
    setThreeDImages([image.path]);
    setThreeDTextPrompt(text("基于这张图片生成 3D 模型", "Generate a 3D model from this image"));
    setWorkspace("3d_studio");
  };
  return (
    <div className="surface" style={{ width: "min(520px, 100%)", borderRadius: 16, overflow: "hidden", marginTop: 8 }}>
      <div style={{ background: "var(--bg-input)", display: "grid", placeItems: "center", minHeight: 240 }}>
        <img src={assetUrl(image.path)} alt={image.label} style={{ maxWidth: "100%", maxHeight: 380, objectFit: "contain" }} />
      </div>
      <div style={{ padding: 12, display: "flex", alignItems: "center", gap: 10 }}>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ fontSize: 14, fontWeight: 820 }}>{text("图片已生成", "Image generated")}</div>
          <div title={image.path} style={{ fontSize: 12, color: "var(--text-muted)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{image.label}</div>
        </div>
        <button className="icon-button" onClick={() => navigator.clipboard.writeText(image.path).then(() => onToast(text("已复制图片路径", "Image path copied")))} title={text("复制路径", "Copy path")}><Icon name="copy" size={15} /></button>
        <button className="primary-button" onClick={sendTo3D} style={{ height: 34, padding: "0 13px" }}><Icon name="cube" size={15} />{text("用于 3D", "Use for 3D")}</button>
      </div>
    </div>
  );
}

function MultiviewAssetCard({ asset, onToast }: { asset: MultiviewAsset; onToast: (text: string) => void }) {
  const { text } = useLanguage();
  const setThreeDImages = useAppStore((s) => s.setThreeDImages);
  const setThreeDTextPrompt = useAppStore((s) => s.setThreeDTextPrompt);
  const setThreeDGenerateMode = useAppStore((s) => s.setThreeDGenerateMode);
  const setWorkspace = useAppStore((s) => s.setWorkspace);
  const views: Array<[string, string]> = [[text("正面", "Front"), asset.front], [text("左侧", "Left"), asset.left], [text("背面", "Back"), asset.back]];
  const sendTo3D = () => {
    setThreeDImages([asset.front, asset.left, "", asset.back]);
    setThreeDTextPrompt(text("基于前、左、后三视图生成 3D 模型", "Generate a 3D model from the front, left, and back views"));
    setThreeDGenerateMode("multiview");
    setWorkspace("3d_studio");
  };
  return (
    <div className="surface" style={{ borderRadius: 16, padding: 12, marginTop: 10, maxWidth: 760 }}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 10 }}>
        {views.map(([label, path]) => (
          <div key={label} style={{ border: "1px solid var(--border-subtle)", borderRadius: 12, overflow: "hidden", background: "rgba(255,254,250,0.78)" }}>
            <img src={assetUrl(path)} alt={label} style={{ width: "100%", aspectRatio: "1", objectFit: "contain", display: "block", background: "#fffefa" }} />
            <div style={{ height: 34, display: "flex", alignItems: "center", justifyContent: "space-between", padding: "0 8px", borderTop: "1px solid var(--border-subtle)" }}>
              <b style={{ fontSize: 12 }}>{label}</b>
              <button className="icon-button" onClick={() => { navigator.clipboard.writeText(path); onToast(text("已复制路径", "Path copied")); }} title={text("复制路径", "Copy path")} style={{ width: 26, height: 26 }}>
                <Icon name="copy" size={13} />
              </button>
            </div>
          </div>
        ))}
      </div>
      <button className="primary-button" onClick={sendTo3D} style={{ height: 36, marginTop: 12, padding: "0 16px" }}>
        <Icon name="cube" size={14} />
        {text("送到 3D 工作区", "Send to 3D workspace")}
      </button>
    </div>
  );
}

function ThreeDAssetCard({ asset }: { asset: ThreeDAsset }) {
  const { text } = useLanguage();
  const [tab, setTab] = useState<"3d" | "preview" | "normal" | "uv">("3d");
  const exportModel = async () => {
    const target = await save({ defaultPath: basename(asset.modelPath), filters: [{ name: "GLB 3D Model", extensions: ["glb"] }] });
    if (target) await invoke("export_3d_model", { sourcePath: asset.modelPath, destinationPath: target });
  };
  return (
    <div className="surface" style={{ width: "min(680px, 100%)", borderRadius: 16, overflow: "hidden", marginTop: 8 }}>
      <div style={{ height: 320, background: "var(--bg-input)", position: "relative" }}>
        <div style={{ position: "absolute", top: 10, left: 10, display: "flex", gap: 6, zIndex: 2 }}>
          {(["3d", "preview", "normal", "uv"] as const).map((key) => (
            <button key={key} className={`segment ${tab === key ? "active" : ""}`} onClick={() => setTab(key)}>
              {key === "3d" ? text("实体", "Solid") : key === "preview" ? text("预览", "Preview") : key === "normal" ? text("法线", "Normal") : "UV"}
            </button>
          ))}
        </div>
        {tab === "3d" ? (
          <ModelPreview modelPath={asset.modelPath} compact />
        ) : (
          <img src={assetUrl(tab === "preview" ? asset.image2D || "" : tab === "normal" ? asset.imageNormal || "" : asset.imageUV || "")} alt="" style={{ width: "100%", height: "100%", objectFit: "contain" }} />
        )}
      </div>
      <div style={{ padding: 14, display: "flex", alignItems: "center", gap: 10 }}>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ fontSize: 15, fontWeight: 820 }}>{text("3D 模型已生成", "3D model generated")}</div>
          <div title={asset.modelPath} style={{ fontSize: 12, color: "var(--text-muted)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{basename(asset.modelPath)}</div>
        </div>
        <button className="icon-button" onClick={() => navigator.clipboard.writeText(asset.modelPath)} title={text("复制路径", "Copy path")}><Icon name="copy" size={15} /></button>
        <button className="primary-button" onClick={exportModel} style={{ height: 36, padding: "0 14px" }}><Icon name="download" size={15} />{text("导出", "Export")}</button>
      </div>
    </div>
  );
}

function PathResolutionCard({ request, onSelect }: { request: PathResolutionRequest; onSelect: (path: string) => void }) {
  const { text } = useLanguage();
  const [customPath, setCustomPath] = useState("");
  return (
    <div className="action-card surface">
      <div className="action-card-head"><Icon name="search" size={16} /><span>{text("没有找到明确路径", "No exact path found")}</span></div>
      <div className="action-card-desc">{text("选择一个相近路径，或手动输入文件夹路径继续。", "Select a nearby path or enter a folder path to continue.")}</div>
      <div className="action-card-list">
        {request.candidates.map((item) => (
          <button key={item.path} className="action-row" onClick={() => onSelect(item.path)} title={item.path}>
            <Icon name={item.type.includes("文件夹") ? "layers" : "file"} size={15} />
            <span>{basename(item.path)}</span>
            <small>{item.type}</small>
          </button>
        ))}
      </div>
      <div className="action-card-custom">
        <input value={customPath} onChange={(e) => setCustomPath(e.target.value)} placeholder={text("输入自定义文件夹路径", "Enter a custom folder path")} />
        <button className="primary-button" disabled={!customPath.trim()} onClick={() => onSelect(customPath.trim())}>{text("使用", "Use")}</button>
      </div>
    </div>
  );
}

function DeleteConfirmCard({ request, onConfirm, onCancel }: { request: DeleteConfirmationRequest; onConfirm: () => void; onCancel: () => void }) {
  const { text } = useLanguage();
  return (
    <div className="action-card danger surface">
      <div className="action-card-head"><Icon name="trash" size={16} /><span>{text(`确认删除${request.targetType}吗？`, "Confirm deletion?")}</span></div>
      <div className="action-card-path" title={request.target}>{request.target}</div>
      {request.warning && <div className="action-card-desc">{request.warning}</div>}
      <div className="action-card-actions">
        <button className="tool-button" onClick={onCancel}>{text("取消", "Cancel")}</button>
        <button className="primary-button danger-button" onClick={onConfirm}>{text("确认删除", "Delete")}</button>
      </div>
    </div>
  );
}

function CommandConfirmCard({ request, onConfirm, onCancel }: { request: CommandConfirmationRequest; onConfirm: () => void; onCancel: () => void }) {
  const { text } = useLanguage();
  return (
    <div className="action-card surface">
      <div className="action-card-head"><Icon name="play" size={16} /><span>{text("确认执行命令？", "Run command?")}</span></div>
      <div className="action-card-path" title={request.command}>{request.command}</div>
      {request.cwd && <div className="action-card-desc" title={request.cwd}>{text("目录：", "Directory: ")}{request.cwd}</div>}
      {request.warning && <div className="action-card-desc">{request.warning}</div>}
      <div className="action-card-actions">
        <button className="tool-button" onClick={onCancel}>{text("取消", "Cancel")}</button>
        <button className="primary-button" onClick={onConfirm}>{text("执行", "Run")}</button>
      </div>
    </div>
  );
}

function ProjectCheckConfirmCard({ request, onConfirm, onCancel }: { request: ProjectCheckConfirmationRequest; onConfirm: () => void; onCancel: () => void }) {
  const { text } = useLanguage();
  return (
    <div className="action-card surface">
      <div className="action-card-head"><Icon name="play" size={16} /><span>{text("确认运行项目检查？", "Run project check?")}</span></div>
      <div className="action-card-path" title={request.path}>{request.path}</div>
      <div className="action-card-desc">{text("类型：", "Type: ")}{request.checkType}</div>
      {request.commands.length > 0 && (
        <div className="action-card-desc">{request.commands.join(" / ")}</div>
      )}
      {request.warning && <div className="action-card-desc">{request.warning}</div>}
      <div className="action-card-actions">
        <button className="tool-button" onClick={onCancel}>{text("取消", "Cancel")}</button>
        <button className="primary-button" onClick={onConfirm}>{text("运行", "Run")}</button>
      </div>
    </div>
  );
}

function ImplementationChoiceCard({ request, onSelect }: { request: ImplementationChoiceRequest; onSelect: (id: string) => void }) {
  const { text } = useLanguage();
  const iconFor = (id: string): "play" | "layers" | "file" => {
    if (id === "python") return "play";
    if (id === "web") return "layers";
    return "file";
  };
  return (
    <div className="action-card surface">
      <div className="action-card-head"><Icon name="cpu" size={16} /><span>{text("选择实现方式", "Choose implementation")}</span></div>
      <div className="action-card-desc">{text("这个任务有多种常见做法，先选一种再创建文件。", "This task has several common implementation paths. Choose one before creating files.")}</div>
      <div className="action-card-list">
        {request.options.map((item) => (
          <button key={item.id} className="action-row" onClick={() => onSelect(item.id)} title={item.description}>
            <Icon name={iconFor(item.id)} size={15} />
            <span>{item.title}</span>
            <small>{item.id}</small>
          </button>
        ))}
      </div>
    </div>
  );
}

function AssetLibrary({ items, onToast }: { items: AssetItem[]; onToast: (text: string) => void }) {
  const { text } = useLanguage();
  if (items.length === 0) return null;
  const reveal = async (path: string) => {
    try {
      await invoke("reveal_path", { path });
    } catch {
      onToast(text("无法打开位置", "Unable to open location"));
    }
  };
  return (
    <div className="asset-library surface">
      <div className="asset-library-head"><span>{text("最近资产", "Recent assets")}</span><small>{items.length}</small></div>
      <div className="asset-list">
        {items.map((item) => (
          <div className="asset-row" key={item.id}>
            <div className="asset-row-thumb">
              {item.kind === "image" ? (
                <img src={assetUrl(item.path)} alt="" />
              ) : item.kind === "3d" && item.preview ? (
                <img src={assetUrl(item.preview)} alt="" />
              ) : (
                <Icon name={item.kind === "3d" ? "cube" : "file"} size={16} />
              )}
            </div>
            <div className="asset-row-main">
              <div className="asset-row-title">{item.title}</div>
              <div className="asset-row-kind">{item.kind === "3d" ? text("3D 模型", "3D model") : item.kind === "doc" ? text("文档", "Document") : text("图片", "Image")}</div>
            </div>
            <button className="icon-button" onClick={() => navigator.clipboard.writeText(item.path)} title={text("复制路径", "Copy path")}><Icon name="copy" size={13} /></button>
            <button className="icon-button" onClick={() => reveal(item.path)} title={text("打开位置", "Open location")}><Icon name="search" size={13} /></button>
          </div>
        ))}
      </div>
    </div>
  );
}

const TOOL_LABELS: Record<string, { zh: string; en: string }> = {
  generate_image: { zh: "图像生成", en: "Generate image" },
  edit_image: { zh: "图像编辑", en: "Edit image" },
  modify_image_with_flux: { zh: "Flux 图像编辑", en: "Flux image editing" },
  generate_multiview_images: { zh: "三视图生成", en: "Generate multiview images" },
  generate_multiview_images_from_image: { zh: "三视图生成", en: "Generate multiview images" },
  generate_3d_text: { zh: "文生 3D", en: "Text to 3D" },
  generate_3d_image: { zh: "图生 3D", en: "Image to 3D" },
  generate_3d_from_text: { zh: "文生 3D", en: "Text to 3D" },
  generate_3d_from_image: { zh: "图生 3D", en: "Image to 3D" },
  generate_3d_fusion: { zh: "多图融合 3D", en: "Multi-image 3D" },
  generate_3d_multiview: { zh: "三视图转 3D", en: "Multiview to 3D" },
  generate_3d_from_generated_multiview: { zh: "三视图转 3D", en: "Multiview to 3D" },
  read_document: { zh: "读取文档", en: "Read document" },
  create_docx: { zh: "创建 Word 文档", en: "Create Word document" },
  create_docx_document: { zh: "创建 Word 文档", en: "Create Word document" },
  edit_docx: { zh: "编辑 Word 文档", en: "Edit Word document" },
  edit_docx_document: { zh: "编辑 Word 文档", en: "Edit Word document" },
  create_text_file: { zh: "创建本地文件", en: "Create local file" },
  choose_implementation: { zh: "选择实现方式", en: "Choose implementation" },
  implementation_choice: { zh: "实现方式选择", en: "Implementation choice" },
  read_many_files: { zh: "批量读取文件", en: "Read many files" },
  search_files: { zh: "搜索文件", en: "Search files" },
  edit_text_file: { zh: "修改文件", en: "Edit file" },
  write_many_files: { zh: "批量写入文件", en: "Write many files" },
  run_command: { zh: "执行命令", en: "Run command" },
  run_project_check: { zh: "项目检查", en: "Project check" },
  list_directory: { zh: "浏览文件夹", en: "Browse folder" },
  delete_file: { zh: "删除文件", en: "Delete file" },
  general_tools: { zh: "工具编排", en: "Tool orchestration" },
  chat: { zh: "对话回复", en: "Chat response" },
};

const SOURCE_LABELS: Record<string, { zh: string; en: string }> = {
  none: { zh: "无外部素材", en: "No external asset" },
  direct: { zh: "直接匹配", en: "Direct match" },
  tool_call: { zh: "Agent 工具调用", en: "Agent tool call" },
  attached_image: { zh: "上传图片", en: "Attached image" },
  latest_active_image: { zh: "最近生成图片", en: "Latest generated image" },
  project_image: { zh: "项目图片", en: "Project image" },
  document: { zh: "附件文档", en: "Attached document" },
  project_document: { zh: "项目文档", en: "Project document" },
  project_path: { zh: "项目路径", en: "Project path" },
};

const REASON_LABELS: Record<string, { zh: string; en: string }> = {
  "LLM tool call produced multiview images": { zh: "模型选择工具并成功生成三视图", en: "The model selected a tool and produced multiview images" },
  "LLM tool call produced image result": { zh: "模型选择工具并成功生成图片", en: "The model selected a tool and produced an image" },
  "LLM tool call produced 3D result": { zh: "模型选择工具并成功生成 3D 结果", en: "The model selected a tool and produced a 3D result" },
  "LLM tool call produced delete result": { zh: "模型选择工具并处理删除请求", en: "The model selected a tool and handled deletion" },
  "matched direct tool path": { zh: "请求已匹配直接工具流程", en: "Request matched a direct tool flow" },
  "matched direct 3D request": { zh: "请求已匹配直接 3D 生成流程", en: "Request matched a direct 3D generation flow" },
  "matched previous 3D modification request": { zh: "请求已匹配已有 3D 结果修改流程", en: "Request matched modification of an existing 3D result" },
};

function localizedLabel(value: string | undefined, labels: Record<string, { zh: string; en: string }>, locale: "zh" | "en") {
  if (!value) return locale === "zh" ? "未记录" : "Not recorded";
  return labels[value]?.[locale] || value;
}

function activityFromStatus(status: string, language: "zh" | "en") {
  if (status === "ComfyUI 启动中/连接中") {
    return {
      label: language === "zh" ? "ComfyUI 启动中/连接中" : "Starting or connecting ComfyUI",
      detail: "comfyui",
    };
  }
  if (status === "请先启动 ComfyUI") {
    return {
      label: language === "zh" ? "请先启动 ComfyUI" : "Start ComfyUI first",
      detail: "comfyui",
    };
  }
  if (status === "ComfyUI 生成队列中") {
    return {
      label: language === "zh" ? "ComfyUI 生成队列中" : "Queued for ComfyUI generation",
      detail: "queue",
    };
  }
  const toolMatch = status.match(/^正在调用工具[：:]\s*(.+)$/);
  if (toolMatch) {
    const tool = toolMatch[1];
    return { label: language === "zh" ? `正在调用：${localizedLabel(tool, TOOL_LABELS, language)}` : `Using: ${localizedLabel(tool, TOOL_LABELS, language)}`, detail: tool };
  }
  const known: Record<string, string> = {
    "正在生成图片": "generate_image",
    "正在编辑图片": "edit_image",
    "正在生成正面、左侧、背面图片": "generate_multiview_images_from_image",
    "正在用已知三视图生成 3D 模型": "generate_3d_from_generated_multiview",
    "正在生成 3D 模型": "generate_3d_from_image",
  };
  const tool = known[status];
  if (tool) return { label: language === "zh" ? `正在调用：${localizedLabel(tool, TOOL_LABELS, language)}` : `Using: ${localizedLabel(tool, TOOL_LABELS, language)}`, detail: tool };
  return { label: status.replace(/[。.]$/, ""), detail: "workflow" };
}

function ActivityIndicator({ status }: { status?: string }) {
  const { language, text } = useLanguage();
  const activity = status ? activityFromStatus(status, language) : null;
  return (
    <div className="agent-activity" aria-live="polite">
      <span className="agent-activity-mark" aria-hidden="true"><i /></span>
      <span className="agent-activity-text">{activity?.label || text("正在思考", "Thinking")}</span>
      <span className="agent-activity-detail">{activity?.detail || "reasoning"}</span>
    </div>
  );
}

function ToolActivityTimeline({ events, active }: { events?: ToolActivityEvent[]; active?: boolean }) {
  const { language, text } = useLanguage();
  if (!events || events.length === 0) return null;
  const latest = events[events.length - 1];
  const latestActivity = activityFromStatus(latest.label, language);
  return (
    <details className={`tool-activity-timeline ${active ? "active" : "complete"}`} open={active}>
      <summary>
        {active ? (
          <ActivityIndicator status={latest.label} />
        ) : (
          <div className="tool-activity-summary-static" aria-label={latestActivity.label}>
            <span className="tool-activity-static-mark" aria-hidden="true" />
            <span className="tool-activity-static-text">
              {text("工具调用已完成", "Tool calls complete")}
            </span>
            <span className="tool-activity-row-detail">{latestActivity.detail}</span>
          </div>
        )}
        <span>{text(`${events.length} 条记录`, `${events.length} events`)}</span>
      </summary>
      <div className="tool-activity-list">
        {events.map((event, index) => {
          const activity = activityFromStatus(event.label, language);
          return (
            <div className="tool-activity-row" key={event.id}>
              <span className="tool-activity-index">{index + 1}</span>
              <span className="tool-activity-row-main">{activity.label}</span>
              <span className="tool-activity-row-detail">{activity.detail || latestActivity.detail}</span>
            </div>
          );
        })}
      </div>
    </details>
  );
}

function AgentTraceCard({ trace }: { trace: AgentTrace }) {
  const { language } = useLanguage();

  return (
    <details className="agent-trace-card surface">
      <summary>
        <span><Icon name="cpu" size={14} />{language === "zh" ? "Agent 决策" : "Agent Decision"}</span>
        <span className="agent-trace-summary-right">
          <small>
            {localizedLabel(trace.action || "chat", TOOL_LABELS, language)}
            {trace.tool ? ` / ${localizedLabel(trace.tool, TOOL_LABELS, language)}` : ""}
          </small>
        </span>
      </summary>
      <div className="agent-trace-grid">
        <div><b>{language === "zh" ? "模型" : "Model"}</b><span>{trace.model || (language === "zh" ? "未记录" : "Not recorded")}</span></div>
        <div><b>{language === "zh" ? "视觉理解" : "Vision"}</b><span>{trace.vision ? (language === "zh" ? "已开启" : "Enabled") : (language === "zh" ? "未开启" : "Disabled")}</span></div>
        <div><b>{language === "zh" ? "触发来源" : "Source"}</b><span>{localizedLabel(trace.source || "none", SOURCE_LABELS, language)}</span></div>
        <div><b>{language === "zh" ? "决策原因" : "Reason"}</b><span title={trace.reason}>{localizedLabel(trace.reason, REASON_LABELS, language)}</span></div>
      </div>
    </details>
  );
}

export default function ChatPanel() {
  const { language, text } = useLanguage();
  const {
    messages,
    sendMessage,
    isStreaming,
    currentConversationId,
    streamingMessageId,
    streamingStatus,
    memoryNotifications,
    clearMemoryNotification,
    attachedImages,
    addAttachedImage,
    removeAttachedImage,
    permissionMode,
    setPermissionMode,
    visionEnabled,
    setVisionEnabled,
    modelConfigs,
    modelConfig,
    selectModelConfig,
  } = useAppStore();
  const [input, setInput] = useState("");
  const [toast, setToast] = useState("");
  const [isDraggingFile, setIsDraggingFile] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const assets = collectAssets(messages);

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [messages, isStreaming]);

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(""), 2400);
    return () => window.clearTimeout(timer);
  }, [toast]);

  useEffect(() => {
    let dragDepth = 0;
    let disposed = false;
    let cleanup: (() => void) | undefined;

    const attachDragListeners = async () => {
      const unlistenDrop = await listen<DragDropPayload>("tauri://drag-drop", (event) => {
        dragDepth = 0;
        setIsDraggingFile(false);
        const paths = normalizeDroppedPaths(event.payload);
        if (paths.length === 0) return;
        paths.forEach((path) => addAttachedImage(path));
        setToast(text(`已添加 ${paths.length} 个附件`, `${paths.length} attachment(s) added`));
      });
      const unlistenEnter = await listen("tauri://drag-enter", () => {
        dragDepth += 1;
        setIsDraggingFile(true);
      });
      const unlistenLeave = await listen("tauri://drag-leave", () => {
        dragDepth = Math.max(0, dragDepth - 1);
        if (dragDepth === 0) setIsDraggingFile(false);
      });
      if (disposed) {
        unlistenDrop();
        unlistenEnter();
        unlistenLeave();
        return;
      }
      cleanup = () => {
        unlistenDrop();
        unlistenEnter();
        unlistenLeave();
      };
    };

    const preventDefault = (event: DragEvent) => {
      event.preventDefault();
    };
    window.addEventListener("dragover", preventDefault);
    window.addEventListener("drop", preventDefault);
    attachDragListeners().catch(() => {});

    return () => {
      disposed = true;
      cleanup?.();
      window.removeEventListener("dragover", preventDefault);
      window.removeEventListener("drop", preventDefault);
    };
  }, [addAttachedImage, language]);

  const handleSend = async () => {
    const messageText = input.trim();
    if ((!messageText && attachedImages.length === 0) || isStreaming || !currentConversationId) return;
    setInput("");
    await sendMessage(messageText || defaultAttachmentPrompt(attachedImages, language));
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      handleSend();
    }
  };

  const openAttachmentPicker = async () => {
    const files = await open({ multiple: true });
    if (!files) return;
    const paths = Array.isArray(files) ? files : [files];
    paths.forEach((path) => addAttachedImage(path));
  };

  const sendWithPath = (query: string, path: string) => {
    sendMessage(language === "zh" ? `使用路径 \`${path}\` 继续处理：${query || "请继续刚才的任务"}` : `Continue with path \`${path}\`: ${query || "Continue the previous task"}`);
  };

  const confirmDelete = (request: DeleteConfirmationRequest) => {
    const continuationText = request.continuation ? `\n\n后续任务：${request.continuation}` : "";
    sendMessage(text(`确认删除 \`${request.target}\`${continuationText}`, `Confirm deletion of \`${request.target}\`${request.continuation ? `\n\nContinue task: ${request.continuation}` : ""}`));
  };

  const confirmCommand = (request: CommandConfirmationRequest) => {
    const cwdText = request.cwd ? `，工作目录：\`${request.cwd}\`` : "";
    sendMessage(text(`确认执行命令：\`${request.command}\`${cwdText}`, `Confirm running command: \`${request.command}\`${request.cwd ? `, cwd: \`${request.cwd}\`` : ""}`));
  };

  const confirmProjectCheck = (request: ProjectCheckConfirmationRequest) => {
    sendMessage(text(`确认项目检查：\`${request.path}\`，类型：\`${request.checkType}\``, `Confirm project check: \`${request.path}\`, type: \`${request.checkType}\``));
  };

  const chooseImplementation = (request: ImplementationChoiceRequest, choiceId: string, sourceMessageId: string) => {
    const choicePrompt: Record<string, string> = {
      html: "请使用 HTML 单文件实现，文件可直接双击打开运行，不要创建 .bak 备份。",
      python: "请使用 Python Tkinter 单文件实现，本地运行，不要创建 .bak 备份。",
      web: "请使用多文件 Web 项目方式实现，可以一次创建 index.html、style.css、app.js 等文件，不要创建 .bak 备份。",
    };
    sendMessage(
      `${choicePrompt[choiceId] || "请按所选方式实现，不要创建 .bak 备份。"}\n\n原始需求：${request.query}`,
      { hideUserMessage: true, removeMessageId: sourceMessageId },
    );
  };

  if (!currentConversationId) {
    return (
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: "100%", gap: 14 }}>
        <div className="brand-mark" style={{ width: 54, height: 54, borderRadius: 16 }}><Icon name="cube" size={26} /></div>
        <h2 style={{ color: "var(--text-primary)", fontSize: 20, fontWeight: 820 }}>{text("准备创建点什么？", "What would you like to create?")}</h2>
        <p style={{ color: "var(--text-muted)", fontSize: 13, maxWidth: 360, textAlign: "center", lineHeight: 1.7 }}>{text("选择左侧对话，或者新建一个对话。", "Select a conversation on the left, or start a new one.")}</p>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <div ref={scrollRef} style={{ flex: 1, overflowY: "auto" }}>
        <div style={{ maxWidth: 1020, margin: "0 auto", padding: "24px 28px 18px" }}>
          <AssetLibrary items={assets} onToast={setToast} />
          {memoryNotifications.length > 0 && (
            <div className="anim-fade-in" style={{ display: "flex", justifyContent: "center", marginBottom: 18 }}>
              <button className="tool-button" onClick={clearMemoryNotification} style={{ height: 32, borderRadius: 999 }}>
                <Icon name="check" size={14} />{memoryNotifications[0]}
              </button>
            </div>
          )}
          {memoryNotifications.length === 0 && messages.length === 0 && (
            <div style={{ textAlign: "center", padding: "72px 0 48px", color: "var(--text-muted)", fontSize: 13 }}>{text("输入描述或添加附件开始。", "Enter a description or add an attachment to begin.")}</div>
          )}

          {messages.map((msg) => {
            const isStreamingMsg = isStreaming && msg.id === streamingMessageId;
            const threeDAsset = msg.role === "assistant" ? parseThreeDAsset(msg.content) : null;
            const pathRequest = msg.role === "assistant" ? parsePathResolutionRequest(msg.content) : null;
            const deleteRequest = msg.role === "assistant" ? parseDeleteConfirmationRequest(msg.content) : null;
            const commandRequest = msg.role === "assistant" ? parseCommandConfirmationRequest(msg.content) : null;
            const projectCheckRequest = msg.role === "assistant" ? parseProjectCheckConfirmationRequest(msg.content) : null;
            const implementationChoice = msg.role === "assistant" ? parseImplementationChoiceRequest(msg.content) : null;
            const agentTrace = msg.role === "assistant" ? parseAgentTrace(msg.content) : null;
            const docAssets = msg.role === "assistant" ? parseDocumentAssets(msg.content) : [];
            const multiviewAsset = msg.role === "assistant" ? parseMultiviewAsset(msg.content) : null;
            const imageAssets = msg.role === "assistant" ? parseGeneratedImageAssets(msg.content) : [];
            const diagnostic = msg.role === "assistant" ? diagnoseError(msg.content, language) : null;
            const rawContent = threeDAsset ? stripThreeDAssetLines(msg.content) : msg.content;
            const assetStrippedContent = multiviewAsset ? stripMultiviewAssetLines(rawContent) : rawContent;
            const displayContent = translateAssistantContent(
              stripPrivateGenerationLines(stripTransientProgressLines(stripActionBlocks(assetStrippedContent))),
              language,
            );
            const showThinking = msg.role === "assistant" && isStreamingMsg && !streamingStatus && !displayContent.trim() && !threeDAsset;

            return (
              <div key={msg.id} className="anim-fade-in" style={{ display: "flex", justifyContent: msg.role === "user" ? "flex-end" : "flex-start", marginBottom: 26 }}>
                {msg.role === "assistant" && (
                  <div style={{ width: 32, height: 32, borderRadius: 11, background: "var(--bg-elevated)", display: "grid", placeItems: "center", marginRight: 12, flexShrink: 0, marginTop: 2, border: "1px solid var(--border-subtle)", color: "var(--accent-blue)" }}>
                    <Icon name="bot" size={17} />
                  </div>
                )}
                <div style={{ maxWidth: msg.role === "user" ? "72%" : "90%", minWidth: 0 }}>
                  {msg.images && msg.images.length > 0 && (
                    <div style={{ display: "flex", gap: 8, marginBottom: 8, justifyContent: msg.role === "user" ? "flex-end" : "flex-start", flexWrap: "wrap" }}>
                      {msg.images.map((path, index) => <AttachmentTile key={`${path}-${index}`} path={path} compact />)}
                    </div>
                  )}

                  {(displayContent || showThinking) && (
                    <div
                      className={msg.role === "assistant" ? "assistant-message-body" : undefined}
                      style={{ padding: msg.role === "user" ? "11px 16px" : 0, borderRadius: msg.role === "user" ? "18px 18px 6px 18px" : 0, background: msg.role === "user" ? "var(--bg-user-msg)" : "transparent", color: msg.role === "user" ? "var(--text-user-msg)" : "var(--text-primary)", fontSize: 14, lineHeight: 1.78, whiteSpace: msg.role === "user" ? "pre-wrap" : "normal", wordBreak: "break-word", boxShadow: msg.role === "user" ? "var(--shadow-sm)" : "none", marginBottom: threeDAsset || pathRequest || deleteRequest || commandRequest || projectCheckRequest || implementationChoice ? 10 : 0 }}
                    >
                      {showThinking ? <ActivityIndicator /> : msg.role === "assistant" ? (
                        <>
                          <MarkdownContent content={displayContent} />
                          {isStreamingMsg && <span className="streaming-cursor">|</span>}
                        </>
                      ) : <span>{displayContent}{isStreamingMsg && <span className="streaming-cursor">|</span>}</span>}
                    </div>
                  )}

                  {msg.role === "assistant" && msg.toolEvents && msg.toolEvents.length > 0 ? (
                    <ToolActivityTimeline events={msg.toolEvents} active={isStreamingMsg} />
                  ) : isStreamingMsg && streamingStatus ? (
                    <ActivityIndicator status={streamingStatus} />
                  ) : null}

                  {threeDAsset && <ThreeDAssetCard asset={threeDAsset} />}
                  {multiviewAsset && <MultiviewAssetCard asset={multiviewAsset} onToast={setToast} />}
                  {docAssets.map((doc) => <DocumentAssetCard key={doc.path} doc={doc} onToast={setToast} />)}
                  {imageAssets.map((image) => <ImageAssetCard key={image.path} image={image} onToast={setToast} />)}
                  {pathRequest && <PathResolutionCard request={pathRequest} onSelect={(path) => sendWithPath(pathRequest.query, path)} />}
                  {deleteRequest && <DeleteConfirmCard request={deleteRequest} onConfirm={() => confirmDelete(deleteRequest)} onCancel={() => setToast(text("已取消删除", "Deletion cancelled"))} />}
                  {commandRequest && <CommandConfirmCard request={commandRequest} onConfirm={() => confirmCommand(commandRequest)} onCancel={() => setToast(text("已取消执行", "Command cancelled"))} />}
                  {projectCheckRequest && <ProjectCheckConfirmCard request={projectCheckRequest} onConfirm={() => confirmProjectCheck(projectCheckRequest)} onCancel={() => setToast(text("已取消项目检查", "Project check cancelled"))} />}
                  {implementationChoice && <ImplementationChoiceCard request={implementationChoice} onSelect={(id) => chooseImplementation(implementationChoice, id, msg.id)} />}
                  {agentTrace && <AgentTraceCard trace={agentTrace} />}
                  {diagnostic && <div className="diagnostic-card"><Icon name="alert" size={15} /><span>{diagnostic}</span></div>}
                </div>
                {msg.role === "user" && (
                  <div style={{ width: 32, height: 32, borderRadius: 11, background: "var(--accent)", display: "grid", placeItems: "center", marginLeft: 12, flexShrink: 0, marginTop: 2, color: "#fffefa" }}>
                    <Icon name="user" size={16} />
                  </div>
                )}
              </div>
            );
          })}
          <ChatGenerationTasks messages={messages} onToast={setToast} />
        </div>
      </div>

      {toast && <div className="toast-notice">{toast}</div>}

      <div style={{ flexShrink: 0, padding: "0 28px 22px" }}>
        <div className={`composer-shell ${isDraggingFile ? "is-file-dragging" : ""}`}>
          {attachedImages.length > 0 && (
            <div className="composer-attachments">
              {attachedImages.map((path, index) => <AttachmentTile key={`${path}-${index}`} path={path} onRemove={() => removeAttachedImage(index)} />)}
            </div>
          )}

          <div className="composer-card">
            {isDraggingFile && (
              <div className="composer-drop-hint">
                <Icon name="upload" size={17} />
                <span>{text("松开以添加附件", "Drop to attach files")}</span>
              </div>
            )}
            <textarea
              className="composer-input"
              value={input}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={text("随便问点什么，或拖入图片 / PDF / DOCX / TXT...", "Ask anything, or drop images / PDF / DOCX / TXT...")}
              rows={1}
            />

            <div className="composer-top-actions">
              <button className="composer-icon-button" onClick={openAttachmentPicker} disabled={isStreaming} title={text("添加附件", "Add attachment")}>
                <Icon name="plus" size={22} />
              </button>
              <button className="composer-send-button" onClick={handleSend} disabled={isStreaming || (!input.trim() && attachedImages.length === 0)} title={text("发送", "Send")}>
                <Icon name="send" size={18} />
              </button>
            </div>

            <div className="composer-meta">
              <div className="composer-left-meta">
                <div className="segmented composer-agent-mode">
                  <button className={`segment ${permissionMode === "standard" ? "active" : ""}`} onClick={() => setPermissionMode("standard")}>{text("标准", "Standard")}</button>
                  <button className={`segment ${permissionMode === "autonomous" ? "active" : ""}`} onClick={() => setPermissionMode("autonomous")}>{text("自主", "Autonomous")}</button>
                </div>
                <button
                  className={`composer-vision-toggle ${visionEnabled ? "active" : ""}`}
                  type="button"
                  onClick={() => setVisionEnabled(!visionEnabled)}
                    title={text("视觉理解", "Vision")}
                >
                  <Icon name="image" size={14} />
                  Vision
                </button>
                <div className="composer-model-select-wrap">
                  <Icon name="cube" size={14} />
                  <select
                    className="composer-model-select"
                    value={modelConfig?.id ?? ""}
                    onChange={(event) => selectModelConfig(event.target.value)}
                    disabled={modelConfigs.length === 0 || isStreaming}
                    title={text("选择本次对话使用的模型", "Choose a model for this conversation")}
                  >
                    {modelConfigs.length === 0 ? (
                      <option value="">{text("未配置模型", "No model configured")}</option>
                    ) : (
                      modelConfigs.map((model) => (
                        <option key={model.id} value={model.id}>
                          {model.modelName}
                        </option>
                      ))
                    )}
                  </select>
                </div>
              </div>
              <div className="composer-permission">
                <small>{permissionMode === "standard" ? text("危险操作会确认", "Confirm risky actions") : text("跳过二次确认", "Skip secondary confirmation")}</small>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
