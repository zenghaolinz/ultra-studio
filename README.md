# Ultra Studio

Ultra Studio 是一个 Tauri 桌面应用，前端使用 React/Vite，后端使用 Python FastAPI sidecar，面向 Agent 对话、本地文件处理、图片生成和 3D 资产生成工作流。

当前版本：`0.7.1`

## 项目结构

- `src/`：React 前端界面和 Zustand 状态管理。
- `src-tauri/`：Tauri 桌面壳、Rust 命令桥接和应用配置。
- `sidecar/`：Python FastAPI 后端，负责模型配置、会话上下文、文件工具、ComfyUI/3D 生成接口。
- `docs/`：项目展示、讲稿、演示视频和比赛材料。
- `scripts/`：文档生成等辅助脚本。

## 环境要求

- Windows
- Node.js 18+
- Python 3.10+
- Rust 工具链
- 可选：ComfyUI Windows Portable，用于图片和 3D 生成链路

## 首次启动

推荐直接运行：

```powershell
.\start.ps1
```

脚本会自动创建 `sidecar/.venv`、安装 Python 依赖、检查 Node 依赖，并启动 Tauri 开发模式。

也可以手动启动：

```powershell
npm install
python -m venv sidecar\.venv
sidecar\.venv\Scripts\pip.exe install -r sidecar\requirements.txt
npm run tauri dev
```

## ComfyUI 配置

真实配置文件是 `sidecar/config.ini`，不纳入版本管理。首次运行 `start.ps1` 时，如果文件不存在，会从 `sidecar/config.example.ini` 自动复制一份。

编辑 `sidecar/config.ini`：

```ini
[ComfyUI]
host = 127.0.0.1
port = 8188
path = E:/ComfyUI_windows_portable
```

如果暂时不配置 ComfyUI，Agent 对话和模型配置仍可运行，但图片/3D 生成会显示未就绪或启动失败。

## 常用命令

```powershell
npm run dev
npm run check
npm run build
cargo check --manifest-path src-tauri/Cargo.toml
```

`npm run check` 会执行 TypeScript 类型检查和关键 Python 文件编译检查。

## 运行诊断

应用启动后，打开 `设置 -> 诊断` 可以检查当前运行环境。诊断项包括：

- Python Sidecar 是否响应
- SQLite 本地数据库是否可访问
- 聊天模型和 Embedding 模型是否配置
- `sidecar/config.ini` 是否存在
- ComfyUI 路径和运行状态
- ComfyUI 输出目录是否可访问

## 生成历史

3D 工作台会记录图片生成、图片改进、文字/图片/双图转 3D、展示材料生成等任务。历史记录保存在本地 SQLite 的 `generation_tasks` 表中。

在 3D 工作台的 `生成历史` 区域可以：

- 查看最近任务状态、提示词、错误和输出路径
- 复用历史提示词与质量模式
- 将历史输出恢复到当前预览
- 打开输出文件所在位置

## 0.7.1 单循环 Agent 与通用 Artifact

聊天链路已迁移到单循环 Agent Runtime，由模型在同一个运行循环中选择并连续调用文件、联网和生成工具，减少旧路由层的重复判断与额外等待。

本版本引入会话级 Artifact Ledger：

- 统一记录上传、生成和工具创建的图片、文档、代码、音频、视频、3D 模型、压缩包及普通文件。
- Artifact 关联用户消息、工具调用或生成任务，可可靠理解“上面的文件”“我上传的 PDF”“之前生成的图片/代码”等引用。
- 历史引用向模型注入经过确定性解析的真实本地路径，不让模型猜测或交换路径。
- 新接口使用 `attachment_paths`；旧桌面端的 `image_paths` 字段继续兼容。

运行时上下文也进行了收敛：前端配置的人设继续作为 system prompt 生效；旧的全局记忆地图、LTM 检索及 `recall_memory`/`save_memory` 工具不再进入活动 Agent 链路。当前会话的可见消息历史仍会保留。这样减少了每次请求携带的提示内容和不必要的记忆检索，有助于降低首字延迟。

## 0.7.0 生成任务中心

图片、视频和 3D 任务现在共用统一任务中心。任务状态通过 Sidecar SSE 和 Tauri 事件桥实时推送，聊天任务卡不再定时轮询。失败或因 Sidecar 重启中断且保存了请求参数的任务可以创建关联重试；排队中或运行中的任务可以单独取消，不会改写其他任务。

重启时遗留的 `running` 任务会明确标记为中断错误，避免显示没有 worker 的幽灵任务。VRAM 感知调度仍属于后续版本范围。

## Agent 连续编排

`0.4.0` 支持由 LLM 根据中间产物连续调用图片与 3D 工具。例如：

```text
生成一张飞船的图片，并生成三视图，然后生成模型
```

系统可以依次执行生图、三视图生成和多视角 3D 重建。当前没有直接编辑 `.glb` 模型材质的工具；如果用户要求修改上一模型的视觉外观，系统会修改其关联图片，再重建新的模型。

## 本地数据

以下内容属于本机运行数据：

- `sidecar/config.ini`
- `sidecar/data/`
- `sidecar/agent.db`
- `logs/`
- `outputs/`
- `src-tauri/target/`

`.gitignore` 已经覆盖这些路径。可运行以下命令查看工作区状态：

```powershell
git status --short
```

## 编码说明

项目源码按 UTF-8 保存。Windows PowerShell 默认编码有时会把中文显示成乱码；检查中文源码时建议显式指定 UTF-8：

```powershell
Get-Content -Encoding UTF8 sidecar\routes\chat.py -TotalCount 80
```
