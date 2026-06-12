import { useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { open } from "@tauri-apps/plugin-dialog";
import { useAppStore } from "../../stores/appStore";
import Icon from "../Icon";
import { LanguageToggle, useLanguage } from "../../i18n";

export default function ConversationList() {
  const { language, text } = useLanguage();
  const {
    conversations,
    projects,
    projectFiles,
    projectFilesLoading,
    currentProjectId,
    currentConversationId,
    workspace,
    setWorkspace,
    createConversation,
    createProject,
    loadProjectFiles,
    selectProject,
    deleteProject,
    selectConversation,
    deleteConversation,
    permissionMode,
  } = useAppStore();
  const [search, setSearch] = useState("");

  const currentProject =
    projects.find((project) => project.id === currentProjectId) ?? null;
  const filtered = conversations.filter((c) =>
    c.title.toLowerCase().includes(search.toLowerCase())
  );
  const handleCreateProject = async () => {
    const selected = await open({ directory: true, multiple: false });
    if (!selected || Array.isArray(selected)) return;
    await createProject(selected);
  };

  const revealProject = async (path: string) => {
    await invoke("reveal_path", { path });
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <div style={{ padding: "16px 14px 12px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 14 }}>
          <div className="brand-mark">
            <Icon name="cube" size={18} />
          </div>
          <div>
            <div style={{ fontSize: 15, fontWeight: 800, lineHeight: 1.1 }}>Ultra Studio</div>
            <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 3 }}>
              {text("Agent + 3D 创作管线", "Agent + 3D Pipeline")}
            </div>
          </div>
          <div style={{ marginLeft: "auto" }}>
            <LanguageToggle compact />
          </div>
        </div>

        <button
          className="primary-button"
          onClick={createConversation}
          style={{ width: "100%", height: 38 }}
        >
          <Icon name="plus" size={16} />
          {currentProject ? text("项目新对话", "New project chat") : text("新对话", "New chat")}
        </button>
      </div>

      <div style={{ padding: "0 14px 10px" }}>
        <div className="surface" style={{ borderRadius: 12, padding: 8, background: "rgba(255, 254, 250, 0.56)" }}>
          <button
            className={`project-row ${currentProjectId === null ? "active" : ""}`}
            onClick={() => selectProject(null)}
            title={text("查看普通对话", "View regular chats")}
          >
            <Icon name="chat" size={14} />
            <span>{text("普通对话", "Regular chats")}</span>
          </button>

          {projects.map((project) => (
            <div
              key={project.id}
              className={`project-row-wrap ${currentProjectId === project.id ? "active" : ""}`}
            >
              <button
                className={`project-row ${currentProjectId === project.id ? "active" : ""}`}
                onClick={() => selectProject(project.id)}
                title={project.rootPath}
              >
                <Icon name="layers" size={14} />
                <span>{project.name}</span>
              </button>
              <button
                className="project-mini-button"
                onClick={() => revealProject(project.rootPath)}
                title={text("打开项目文件夹", "Open project folder")}
              >
                <Icon name="search" size={12} />
              </button>
              <button
                className="project-mini-button"
                onClick={() => {
                  if (
                    permissionMode !== "autonomous" &&
                    !window.confirm(text(`确认移除项目「${project.name}」吗？项目文件夹不会被删除。`, `Remove project "${project.name}"? The project folder will not be deleted.`))
                  ) {
                    return;
                  }
                  deleteProject(project.id);
                }}
                title={text("移除项目", "Remove project")}
              >
                <Icon name="trash" size={12} />
              </button>
            </div>
          ))}

          <button className="project-add-button" onClick={handleCreateProject}>
            <Icon name="plus" size={14} />
            {text("添加项目文件夹", "Add project folder")}
          </button>
        </div>
      </div>

      <div style={{ padding: "0 14px 10px" }}>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            padding: "0 10px",
            height: 36,
            borderRadius: 10,
            background: "rgba(255, 254, 250, 0.66)",
            border: "1px solid var(--border-subtle)",
            color: "var(--text-muted)",
          }}
        >
          <Icon name="search" size={15} />
          <input
            type="text"
            placeholder={text("搜索对话", "Search chats")}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            style={{
              flex: 1,
              background: "none",
              border: "none",
              outline: "none",
              color: "var(--text-primary)",
              fontSize: 13,
              minWidth: 0,
            }}
          />
        </div>
      </div>

      <div style={{ padding: "0 14px 12px" }}>
        <div className="segmented">
          <button
            className={`segment ${workspace === "agent" ? "active" : ""}`}
            onClick={() => setWorkspace("agent")}
            style={{ flex: 1 }}
          >
            <Icon name="chat" size={14} />
            {text("对话", "Chat")}
          </button>
          <button
            className={`segment ${workspace === "image_studio" ? "active" : ""}`}
            onClick={() => setWorkspace("image_studio")}
            style={{ flex: 1 }}
          >
            <Icon name="image" size={14} />
            {text("图像", "Visual")}
          </button>
          <button
            className={`segment ${workspace === "3d_studio" ? "active" : ""}`}
            onClick={() => setWorkspace("3d_studio")}
            style={{ flex: 1 }}
          >
            <Icon name="cube" size={14} />
            3D
          </button>
        </div>
      </div>

      {currentProject && (
        <div className="project-context">
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <div style={{ minWidth: 0, flex: 1 }}>
              <div className="project-context-title">{currentProject.name}</div>
              <div className="project-context-path" title={currentProject.rootPath}>
                {currentProject.rootPath}
              </div>
            </div>
            <button
              className="project-mini-button"
              onClick={() => loadProjectFiles(currentProject.id)}
              title={text("刷新可见文件", "Refresh visible files")}
              disabled={projectFilesLoading}
            >
              <Icon name="refresh" size={12} />
            </button>
          </div>
          <ProjectVisibleFiles files={projectFiles} loading={projectFilesLoading} language={language} />
        </div>
      )}

      <div style={{ flex: 1, overflowY: "auto", padding: "0 8px 14px" }}>
        {Object.entries(groupByDate(filtered, language)).map(([date, convs]) => (
          <div key={date} style={{ marginBottom: 8 }}>
            <div
              style={{
                padding: "7px 10px 4px",
                fontSize: 11,
                fontWeight: 750,
                color: "var(--text-muted)",
              }}
            >
              {date}
            </div>
            {convs.map((conv) => {
              const active = currentConversationId === conv.id;
              return (
                <div
                  key={conv.id}
                  onClick={() => selectConversation(conv.id)}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                    padding: "8px 8px",
                    borderRadius: 10,
                    cursor: "pointer",
                    transition: "background var(--transition), color var(--transition)",
                    background: active ? "rgba(255, 254, 250, 0.86)" : "transparent",
                    border: active ? "1px solid var(--border-subtle)" : "1px solid transparent",
                    color: active ? "var(--text-primary)" : "var(--text-secondary)",
                  }}
                >
                  <Icon name="chat" size={15} style={{ flexShrink: 0, opacity: active ? 0.95 : 0.58 }} />
                  <span
                    style={{
                      flex: 1,
                      fontSize: 13,
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                      fontWeight: active ? 700 : 500,
                    }}
                  >
                    {conv.title}
                  </span>
                  <button
                    className="icon-button"
                    onClick={(e) => {
                      e.stopPropagation();
                      if (
                        permissionMode !== "autonomous" &&
                        !window.confirm(text(`确认删除对话「${conv.title}」吗？`, `Delete conversation "${conv.title}"?`))
                      ) {
                        return;
                      }
                      deleteConversation(conv.id);
                    }}
                    title={text("删除对话", "Delete conversation")}
                    style={{
                      width: 26,
                      height: 26,
                      opacity: active ? 0.9 : 0,
                      background: "transparent",
                      border: "none",
                    }}
                  >
                    <Icon name="trash" size={14} />
                  </button>
                </div>
              );
            })}
          </div>
        ))}
        {conversations.length === 0 && (
          <div
            style={{
              margin: "38px 12px",
              padding: 18,
              textAlign: "center",
              color: "var(--text-muted)",
              fontSize: 13,
              lineHeight: 1.7,
              border: "1px dashed var(--border-subtle)",
              borderRadius: 14,
            }}
          >
            {currentProject
              ? text("在这个项目里开一个新对话，agent 会默认围绕该文件夹工作。", "Start a chat in this project and the agent will work from this folder by default.")
              : text("点击“新对话”开始。", 'Click "New chat" to begin.')}
          </div>
        )}
      </div>
    </div>
  );
}

function ProjectVisibleFiles({
  files,
  loading,
  language,
}: {
  files: ReturnType<typeof useAppStore.getState>["projectFiles"];
  loading: boolean;
  language: "zh" | "en";
}) {
  const text = (zh: string, en: string) => language === "zh" ? zh : en;
  if (loading) {
    return <div className="project-files-empty">{text("正在扫描可见文件...", "Scanning visible files...")}</div>;
  }
  if (!files) {
    return <div className="project-files-empty">{text("还没有文件清单", "No file inventory yet")}</div>;
  }
  const docs = files.documents.slice(0, 4);
  const images = files.images.slice(0, 4);
  return (
    <div className="project-files">
      <div className="project-files-stats">
        <span>{text("文档", "Documents")} {files.documentCount}</span>
        <span>{text("图片", "Images")} {files.imageCount}</span>
      </div>
      <ProjectFileGroup title={text("文档", "Documents")} icon="file" items={docs} />
      <ProjectFileGroup title={text("图片", "Images")} icon="image" items={images} />
      {files.documentCount + files.imageCount === 0 && (
        <div className="project-files-empty">{text("未发现 txt/docx/pdf 或图片", "No txt/docx/pdf files or images found")}</div>
      )}
    </div>
  );
}

function ProjectFileGroup({
  title,
  icon,
  items,
}: {
  title: string;
  icon: "file" | "image";
  items: { name: string; path: string; relativePath: string; extension: string }[];
}) {
  if (items.length === 0) return null;
  const reveal = async (path: string) => {
    await invoke("reveal_path", { path });
  };
  return (
    <div className="project-file-group">
      <div className="project-file-group-title">{title}</div>
      {items.map((item) => (
        <button
          key={item.path}
          className="project-file-row"
          onClick={() => reveal(item.path)}
          title={item.path}
        >
          <Icon name={icon} size={13} />
          <span>{item.relativePath || item.name}</span>
          <small>{item.extension}</small>
        </button>
      ))}
    </div>
  );
}

function groupByDate(
  conversations: { id: string; title: string; createdAt: string }[],
  language: "zh" | "en",
) {
  const groups: Record<string, typeof conversations> = {};
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterday = new Date(today.getTime() - 86400000);
  for (const conv of conversations) {
    const d = new Date(conv.createdAt);
    let label: string;
    if (d >= today) label = language === "zh" ? "今天" : "Today";
    else if (d >= yesterday) label = language === "zh" ? "昨天" : "Yesterday";
    else {
      label = d.toLocaleDateString(language === "zh" ? "zh-CN" : "en-US", {
        month: "short",
        day: "numeric",
      });
    }
    if (!groups[label]) groups[label] = [];
    groups[label].push(conv);
  }
  return groups;
}
