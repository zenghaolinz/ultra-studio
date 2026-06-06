# Ultra Studio Agent Handoff

This repo is a Tauri desktop app with a React frontend and a Python sidecar. The current development direction is to keep chat, tools, ComfyUI, and generation queues decoupled so users can keep chatting while long image/video/model jobs run in the background.

## Project Shape

- Frontend: `src/`
  - Chat UI: `src/components/ChatPanel/index.tsx`
  - Settings UI: `src/components/SettingsPanel.tsx`
  - 3D/generation history UI: `src/components/ThreeDStudio/`
  - App state: `src/stores/appStore.ts`
  - Shared types: `src/types/index.ts`
- Tauri bridge: `src-tauri/src/`
  - Commands for chat, queue, settings, filesystem, and sidecar control.
- Python sidecar: `sidecar/`
  - Chat routes and orchestration: `sidecar/routes/chat.py`
  - Generation task API: `sidecar/routes/asset_3d.py`
  - Tool registry/execution and queue insertion: `sidecar/memory/manager.py`
  - Database helpers: `sidecar/db.py`

## Useful Commands

- Frontend/type check: `npm run check`
- Rust check: `cargo check --manifest-path src-tauri/Cargo.toml`
- Search quickly: `rg "pattern"`
- Run app in dev mode: `npm run tauri dev`

## Current Queue Model

Generation is stored in SQLite `generation_tasks`. Image, video, and model generation tools enqueue work and return a task ID immediately, so the chat can continue. Background workers update task status and write outputs into `outputPaths`.

Important output keys:

- Images: `imagePath`
- Videos: `videoPath`
- 3D models: `modelPath`, with optional `image2D`, `imageNormal`, `imageUV`

The chat panel parses queued task IDs from assistant messages and polls `list_generation_tasks`; when a task completes, it renders the final image/video/model card in the chat.

## ComfyUI State

ComfyUI is treated as an external runtime, not a hard dependency for opening chat or history. Users can configure the ComfyUI version/location in settings. If ComfyUI is unavailable when a generation tool needs it, the UI should show a clear "please start/configure ComfyUI" state instead of blocking the whole chat app.

For portable ComfyUI, startup can use its configured launch script. For desktop ComfyUI, prefer detecting the running API instead of trying to own the process.

## MCP Direction

There is an early MCP-style endpoint in the sidecar. Keep moving tools toward a protocol boundary:

- Tool metadata should be discoverable.
- Tool calls should be routed through one executor.
- Long-running tools should create queue tasks instead of blocking chat.
- Queue status should be readable by UI and future MCP clients.

## Test Data Policy

This is currently a personal test build. It is OK to clear conversation and task history when migrations or schema cleanup are easier.

Preserve API keys and provider configuration. Before destructive database cleanup, inspect table names and keep configuration-like tables such as model/provider config, embedding config, persona/project settings, and secrets.

Likely disposable tables:

- `conversations`
- `messages`
- `stm_entries`
- `message_tool_events`
- `generation_tasks`

## Near-Term Priorities

1. Replace chat-side polling with task status events from the sidecar/Tauri bridge.
2. Add task cancel/retry controls and persist enough state for recovery after app restart.
3. Finish a queue center for image, video, model, and ComfyUI jobs with VRAM-aware scheduling.
4. Continue splitting `sidecar/routes/chat.py` into route handlers, agent orchestration, tool execution, status events, and formatting.
5. Componentize settings into ComfyUI runtime, model providers, generation queue, MCP/tools, and app data sections.
6. Add integration tests for multi-conversation chat concurrency and queued generation concurrency.

## Coding Notes

- Prefer existing local patterns over new abstractions.
- Keep edits scoped; this repo has had dirty history, so inspect before changing.
- Use structured parsing and typed models where possible.
- Do not expose or log plaintext API keys.
- Run `npm run check` after frontend changes and `cargo check --manifest-path src-tauri/Cargo.toml` after Tauri command changes.
