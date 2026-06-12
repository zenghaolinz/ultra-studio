# Ultra Studio

Ultra Studio 是一个桌面端 AI 创作工作台。它使用 Tauri 承载 React/Vite 前端，并通过 Python sidecar 提供本地 Agent、记忆管理、模型配置、文件工具、ComfyUI 连接和 3D 资产生成能力。

## 功能

- Agent 对话与流式响应
- 会话列表、标题生成和上下文管理
- 短期/长期记忆与本地检索
- 聊天模型和 Embedding 模型配置
- 本地文件读取、项目文件检索和工具调用
- ComfyUI 状态检测与配置管理
- 图片生成、图片改进和 3D 资产生成工作流
- 生成历史记录、任务恢复和结果预览
- Tauri 桌面应用封装

## 技术栈

- Tauri 2
- React 18
- Vite
- TypeScript
- Zustand
- Three.js / React Three Fiber
- Python FastAPI sidecar
- SQLite 本地数据库
- Rust 命令桥接

## 目录结构

```text
ultra-studio/
├── src/              # React 前端界面、状态管理和类型定义
├── src-tauri/        # Tauri 桌面壳、Rust 命令和应用配置
├── sidecar/          # Python 后端服务、路由、工具、记忆和测试
├── scripts/          # 辅助脚本
├── package.json      # 前端依赖和 npm scripts
├── start.ps1         # Windows 启动脚本
└── README.md
```

## 环境要求

- Windows
- Node.js 18+
- Python 3.10+
- Rust 工具链
- 可选：ComfyUI Windows Portable，用于图片和 3D 生成链路

## 快速开始

推荐使用启动脚本：

```powershell
.\start.ps1
```

脚本会检查 Node 依赖、创建 `sidecar/.venv`、安装 Python 依赖，并启动 Tauri 开发模式。

也可以手动安装：

```powershell
npm install
python -m venv sidecar\.venv
sidecar\.venv\Scripts\pip.exe install -r sidecar\requirements.txt
npm run tauri dev
```

## 常用命令

```powershell
npm run dev
npm run typecheck
npm run check
npm run build
cargo check --manifest-path src-tauri/Cargo.toml
```

`npm run check` 会执行 TypeScript 类型检查、Python 编译检查和 sidecar 单元测试。

## 模型配置

应用启动后，在设置页配置聊天模型和 Embedding 模型。

API Key 会写入本地 SQLite 数据库，不会提交到仓库。仓库中只包含配置字段和占位测试值，不包含真实密钥。

## ComfyUI 配置

真实配置文件为：

```text
sidecar/config.ini
```

首次运行时可从示例配置复制：

```text
sidecar/config.example.ini
```

示例：

```ini
[ComfyUI]
host = 127.0.0.1
port = 8188
path = E:/ComfyUI_windows_portable
```

未配置 ComfyUI 时，Agent 对话和模型配置仍可使用；图片与 3D 生成相关功能会显示未就绪或启动失败。

## 本地数据

以下内容属于运行时数据，不包含在公开代码导出中：

- `sidecar/config.ini`
- `sidecar/data/`
- `sidecar/agent.db`
- `logs/`
- `outputs/`
- `node_modules/`
- `dist/`
- `src-tauri/target/`
- 模型权重文件

## 安全说明

本仓库公开版本已排除本地配置、数据库、日志、输出目录、构建产物、依赖目录和模型权重。提交前已扫描常见 API key/token 形态，未发现真实密钥。

如果你在本地配置过真实模型 API Key，请不要提交本地数据库或配置文件。

## 编码说明

项目源码按 UTF-8 保存。Windows PowerShell 默认编码有时会把中文显示成乱码；查看中文文件时建议显式指定 UTF-8：

```powershell
Get-Content -Encoding UTF8 sidecar\routes\chat.py -TotalCount 80
```
