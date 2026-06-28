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
  - Default single-loop agent runtime: `sidecar/agent_runtime/`
  - Default agent SSE route: `sidecar/routes/agent_runs.py`
  - Legacy chat compatibility route: `sidecar/routes/chat.py`
  - Conversation artifact ledger and projection: `sidecar/services/conversation_artifacts.py`
  - Deterministic media reference resolver: `sidecar/services/artifact_references.py`
  - Chat response formatting helpers: `sidecar/services/chat_response_formatters.py`
  - Chat confirmation parsing/execution helpers: `sidecar/services/chat_confirmations.py`
  - Chat confirmed delete/delete-then-create flow: `sidecar/services/chat_delete_flow.py`
  - Chat intent predicates: `sidecar/services/chat_intents.py`
  - Chat document-to-asset prompt helpers: `sidecar/services/chat_asset_prompts.py`
  - Chat document enumeration/read helpers: `sidecar/services/chat_documents.py`
  - Chat project/attachment document read orchestration: `sidecar/services/chat_document_read.py`
  - Chat generation context injection/history helpers: `sidecar/services/chat_generation_context.py`
  - Chat message persistence helpers: `sidecar/services/chat_messages.py`
  - Chat model context-window inference and message fitting: `sidecar/services/model_context.py`
  - Chat local path/attachment helpers: `sidecar/services/chat_paths.py`
  - Chat provider client lookup/creation: `sidecar/services/chat_provider_client.py`
  - Chat project file candidate scanners: `sidecar/services/chat_project_files.py`
  - Chat project context helpers: `sidecar/services/chat_projects.py`
  - Chat conversation artifact indexing/resolution: `sidecar/services/chat_artifacts.py`
  - Chat router action constants, JSON parsing, and trace payload helpers: `sidecar/services/chat_router.py`
  - Chat router context gathering and trace block helpers: `sidecar/services/chat_router_context.py`
  - Chat routed result formatting/context injection helpers: `sidecar/services/chat_router_results.py`
  - Chat deterministic result verification helpers: `sidecar/services/chat_result_verifier.py`
  - Chat bounded result repair helpers: `sidecar/services/chat_result_repair.py`
  - Chat title generation helpers: `sidecar/services/chat_titles.py`
  - Chat tool-result selection/output helpers: `sidecar/services/chat_tool_results.py`
  - Chat tool-call result presentation helpers: `sidecar/services/chat_tool_presentation.py`
  - Chat direct image/3D generation flows: `sidecar/services/chat_direct_media.py`
  - Chat document-to-image/3D asset flows: `sidecar/services/chat_document_assets.py`
  - Chat folder-to-docx summary flow: `sidecar/services/chat_folder_summary.py`
  - Chat router action execution flow: `sidecar/services/chat_router_actions.py`
  - Chat OpenAI tool-call loop execution: `sidecar/services/chat_tool_loop.py`
  - Chat visual prompt helpers: `sidecar/services/chat_visual_prompts.py`
  - Direct file intent helpers and direct file response formatting: `sidecar/routes/direct_files.py`
  - 3D/generation HTTP routes: `sidecar/routes/asset_3d.py`
  - Generation task CRUD/list/cancel helpers: `sidecar/services/generation_tasks.py`
  - Generation runtime queue counters and ComfyUI readiness: `sidecar/services/generation_runtime.py`
  - MCP tool registry/execution: `sidecar/services/mcp_tools.py`
  - Chat tool execution and queue insertion: `sidecar/memory/manager.py`
  - Database helpers and migrations: `sidecar/db/sqlite.py`

## Useful Commands

- Frontend/type check: `npm run check`
- Rust check: `cargo check --manifest-path src-tauri/Cargo.toml`
- Search quickly: `rg "pattern"`
- Run app in dev mode: `npm run tauri dev`

## Current Queue Model

Generation is stored in SQLite `generation_tasks`. Image, video, and model generation tools enqueue work and return a task ID immediately, so the chat can continue. Background workers update task status and write outputs into `outputPaths`.

Task table access should go through `sidecar/services/generation_tasks.py`. `asset_3d.py`, chat tools, MCP tools, and future queue UIs should not each hand-roll inserts, updates, list conversion, or cancellation.

In-process queue counters live in a `GenerationRuntimeState` instance inside `sidecar/services/generation_runtime.py`. The module-level functions remain as compatibility wrappers, but new tests or future schedulers can inject an isolated runtime state.

On sidecar startup, `sidecar/main.py` calls `mark_interrupted_generation_tasks()` to turn leftover `running` rows from a previous process into `error` tasks. Do not leave restarted worker-less tasks in `running`; add explicit retry/resume behavior before changing this policy.

Important output keys:

- Images: `imagePath`
- Videos: `videoPath`
- 3D models: `modelPath`, with optional `image2D`, `imageNormal`, `imageUV`

The chat panel parses queued task IDs from assistant messages and polls `list_generation_tasks`; when a task completes, it renders the final image/video/model card in the chat.

## ComfyUI State

ComfyUI is treated as an external runtime, not a hard dependency for opening chat or history. Users can configure the ComfyUI version/location in settings. If ComfyUI is unavailable when a generation tool needs it, the UI should show a clear "please start/configure ComfyUI" state instead of blocking the whole chat app.

For portable ComfyUI, startup can use its configured launch script. For desktop ComfyUI, prefer detecting the running API instead of trying to own the process.

## MCP Direction

There is an early MCP-style endpoint in the sidecar. Tool metadata, basic argument validation, numeric range validation, and `tools/call` execution now route through `sidecar/services/mcp_tools.py`; avoid adding new `if/elif` branches directly in `routes/mcp.py`.

Keep moving tools toward a protocol boundary:

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

## 0.7.0 Generation Task Center

- Generation task mutations publish committed snapshots through `sidecar/services/generation_events.py`.
- `sidecar/routes/generation_tasks.py` exposes the snapshot, SSE, per-task cancel, and retry boundary.
- Tauri forwards task events to the shared Zustand store in `src/stores/generationTaskStore.ts`.
- Chat task cards and generation history consume the shared store; do not restore component-local task polling.
- Retry runs through `sidecar/services/generation_dispatcher.py` and reuses the newly linked task row.

## 0.7.1 Single-Loop Agent Runtime

- Tauri chat streaming defaults to `POST /api/agent/runs/stream`.
- The runtime in `sidecar/agent_runtime/` uses one primary model/tool loop. Ordinary chat does not call a separate LLM router and text deltas are not buffered for DSML detection.
- Tool availability is selected deterministically from context, then filtered by capability and permission policy. Existing file, web, generation, and queue services remain the execution authority behind adapters.
- Build active runtime context with `sidecar/services/agent_context.py`. The frontend-configured `persona` is a static system prompt and remains active. Do not read the global memory map, LTM files, activated memory, or recall/save-memory tools. `stm_entries` is retained only as message history filtered by the current `conversation_id` and visible messages.
- Image, video, and 3D tools enqueue work and return task IDs to the model immediately.
- Standard mode stops destructive calls with a structured confirmation event. The route adapter formats the existing confirmation-card markers until the frontend consumes structured confirmations directly.
- Legacy `/api/chat/send` and `/api/chat/send/stream` URLs are thin adapters over the same single-loop runtime; they no longer contain a second orchestrator.
- The per-message LLM router and textual/DSML tool path were removed after real-provider smoke tests passed.
- Uploaded and generated media are indexed in `conversation_artifacts` with message/tool/task provenance. Resolve phrases such as “上面这张图”, “我上传的图片”, and “之前生成的图片” through `artifact_references.py`; never recover canonical tool paths by asking the model to guess from prose.
- Successful historical generation tasks are lazily projected into the ledger, so existing task-center outputs remain referenceable after upgrade.

## Near-Term Priorities

1. Add VRAM-aware scheduling and explicit concurrency policies to the task center.
2. Move external clients from the legacy chat URLs to `/api/agent/runs/stream`, then remove the thin compatibility route.
3. Componentize settings into ComfyUI runtime, model providers, generation queue, MCP/tools, and app data sections.
4. Expand real-runtime integration tests for multi-conversation chat and queued ComfyUI generation.

## Coding Notes

- Prefer existing local patterns over new abstractions.
- Keep edits scoped; this repo has had dirty history, so inspect before changing.
- Use structured parsing and typed models where possible.
- Do not expose or log plaintext API keys.
- Keep pure chat response formatting out of `sidecar/routes/chat.py`; add formatters to `sidecar/services/chat_response_formatters.py` and alias imports in chat when preserving old call names reduces risk.
- Keep confirmation parsing and simple confirmed command/project-check dispatch out of `sidecar/routes/chat.py`; those helpers live in `sidecar/services/chat_confirmations.py`. Leave flows that need the chat LLM client in chat until they have a cleaner orchestration boundary.
- Keep confirmed delete/delete-then-create execution out of `sidecar/routes/chat.py`; use `sidecar/services/chat_delete_flow.py`.
- Keep reusable chat intent predicates out of `sidecar/routes/chat.py`; use `sidecar/services/chat_intents.py` for small intent detectors that do not need DB/model context, including image/3D generation and previous-asset edit intent checks.
- Keep deterministic document-to-asset prompt extraction out of `sidecar/routes/chat.py`; use `sidecar/services/chat_asset_prompts.py` for requirement text cleanup and deterministic image/3D fallback prompts.
- Keep generation context injection and latest generated image/multiview lookup out of `sidecar/routes/chat.py`; use `sidecar/services/chat_generation_context.py` for STM context strings and history scanning.
- Keep simple chat message persistence out of `sidecar/routes/chat.py`; use `sidecar/services/chat_messages.py` for saving visible/user/assistant messages and removing internal source messages.
- Keep model context-window inference, token estimation, compression logging, and message fitting out of `sidecar/routes/chat.py`; use `sidecar/services/model_context.py`. New chat model configs should either set `context_window` explicitly or rely on that service's provider/model inference. Every `chat.completions.create` entry point in sidecar-owned code should pass messages through `fit_messages_to_context`, especially document/file flows and after tool results are appended. Compression logs (`[context] compressed ...`) are the first place to check when debugging lost context.
- Keep conversation title generation out of `sidecar/routes/chat.py`; use `sidecar/services/chat_titles.py`.
- Keep local path parsing, attachment classification, and path-resolution cards out of `sidecar/routes/chat.py`; use `sidecar/services/chat_paths.py` for extension sets and path helpers.
- Keep chat provider config lookup and `AsyncOpenAI` client construction out of `sidecar/routes/chat.py`; use `sidecar/services/chat_provider_client.py`.
- Keep project document/image/file candidate scanning out of `sidecar/routes/chat.py`; use `sidecar/services/chat_project_files.py` for fuzzy matching files under the current project root.
- Keep project path lookup, project-context injection text, and open-folder request handling out of `sidecar/routes/chat.py`; use `sidecar/services/chat_projects.py`.
- Keep conversation artifact reference parsing out of `sidecar/routes/chat.py`; use `sidecar/services/chat_artifacts.py` for generic image/file/document/code/model/video artifact markers, history scanning, ordinal references like "second image", and semantic references like "yellow dog". Do not add one-off keyword branches for a single asset type when the same behavior should generalize to files and other artifacts.
- The new runtime uses `sidecar/services/conversation_artifacts.py` and `sidecar/services/artifact_references.py` as its typed artifact ledger and deterministic resolver. It covers uploaded, generated, and tool-created image/document/code/audio/video/model/archive/file artifacts with message, task, and tool-call provenance. `image_paths` remains a legacy transport field; new callers may send `attachment_paths`, and runtime code must use `ChatRequest.all_attachment_paths`.
- Keep router constants, safe JSON parsing, model-capability inference, and pure trace payload formatting out of `sidecar/routes/chat.py`; use `sidecar/services/chat_router.py`.
- Keep router context gathering and agent trace block rendering out of `sidecar/routes/chat.py`; use `sidecar/services/chat_router_context.py`. Router action execution can stay in chat until those dependencies are split further.
- Keep routed-result formatting and post-route media context injection out of `sidecar/routes/chat.py`; use `sidecar/services/chat_router_results.py`.
- Keep deterministic result verification out of `sidecar/routes/chat.py`; use `sidecar/services/chat_result_verifier.py` for structural checks such as output files existing, generation tasks being queued/successful, edit results needing a prior read, and confirmation/path-resolution states. This layer is intentionally deterministic; add LLM semantic evaluators only as a separate bounded retry step.
- Keep bounded repair flows out of `sidecar/routes/chat.py`; use `sidecar/services/chat_result_repair.py` for one-hop deterministic repairs after verifier marks a result retryable or structurally invalid. Current repair paths cover text edits that need a safer fallback and text/code file creation results whose reported files are missing or incomplete. Do not introduce unbounded repair loops; each repair path should have explicit tests and a clear stop condition.
- Keep folder document enumeration and direct document attachment reads out of `sidecar/routes/chat.py`; use `sidecar/services/chat_documents.py`.
- Keep project/attachment document read orchestration out of `sidecar/routes/chat.py`; use `sidecar/services/chat_document_read.py`.
- Keep image data-url creation and vision edit prompt generation out of `sidecar/routes/chat.py`; use `sidecar/services/chat_visual_prompts.py`.
- Keep tool-result selection/dedup helpers out of `sidecar/routes/chat.py`; use `sidecar/services/chat_tool_results.py` for first/best result selection, ComfyUI manual-start checks, and trace output path extraction.
- Keep tool-call result presentation out of `sidecar/routes/chat.py`; use `sidecar/services/chat_tool_presentation.py` to map selected tool results into user-facing text plus trace metadata shared by streaming and non-streaming chat responses.
- Keep direct image/3D generation and previous-asset media modification flows out of `sidecar/routes/chat.py`; use `sidecar/services/chat_direct_media.py` for these small ComfyUI dispatch paths.
- Keep document-to-image/3D asset intent detection, prompt building, and generation dispatch out of `sidecar/routes/chat.py`; use `sidecar/services/chat_document_assets.py`.
- Keep folder-to-docx summary orchestration out of `sidecar/routes/chat.py`; use `sidecar/services/chat_folder_summary.py`.
- Keep router action execution out of `sidecar/routes/chat.py`; use `sidecar/services/chat_router_actions.py`.
- Keep OpenAI tool-call loop execution out of `sidecar/routes/chat.py`; use `sidecar/services/chat_tool_loop.py`. The loop includes an explicit result-verification prompt after each tool batch: the model should inspect tool results against the user request, call more tools when results are incomplete or wrong, and only answer when the task is complete or waiting for confirmation/user input.
- SQLite migrations in `sidecar/db/sqlite.py` are transaction-protected; keep future schema changes inside that rollback-safe flow.
- Run `npm run check` after frontend changes and `cargo check --manifest-path src-tauri/Cargo.toml` after Tauri command changes.
