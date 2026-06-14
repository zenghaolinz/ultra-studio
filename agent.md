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
  - Chat title generation helpers: `sidecar/services/chat_titles.py`
  - Chat tool-result selection/output helpers: `sidecar/services/chat_tool_results.py`
  - Chat direct image/3D generation flows: `sidecar/services/chat_direct_media.py`
  - Chat document-to-image/3D asset flows: `sidecar/services/chat_document_assets.py`
  - Chat folder-to-docx summary flow: `sidecar/services/chat_folder_summary.py`
  - Chat LLM router decision flow: `sidecar/services/chat_llm_router.py`
  - Chat router action execution flow: `sidecar/services/chat_router_actions.py`
  - Chat textual/DSML tool execution helpers: `sidecar/services/chat_textual_tools.py`
  - Chat OpenAI tool-call loop execution: `sidecar/services/chat_tool_loop.py`
  - Chat visual prompt helpers: `sidecar/services/chat_visual_prompts.py`
  - DSML/textual tool call parsing helpers: `sidecar/services/textual_tool_parser.py`
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
- Keep router constants, safe JSON parsing, model-capability inference, and pure trace payload formatting out of `sidecar/routes/chat.py`; use `sidecar/services/chat_router.py`.
- Keep router context gathering and agent trace block rendering out of `sidecar/routes/chat.py`; use `sidecar/services/chat_router_context.py`. Router action execution can stay in chat until those dependencies are split further.
- Keep routed-result formatting and post-route media context injection out of `sidecar/routes/chat.py`; use `sidecar/services/chat_router_results.py`.
- Keep deterministic result verification out of `sidecar/routes/chat.py`; use `sidecar/services/chat_result_verifier.py` for structural checks such as output files existing, generation tasks being queued/successful, edit results needing a prior read, and confirmation/path-resolution states. This layer is intentionally deterministic; add LLM semantic evaluators only as a separate bounded retry step.
- Keep folder document enumeration and direct document attachment reads out of `sidecar/routes/chat.py`; use `sidecar/services/chat_documents.py`.
- Keep project/attachment document read orchestration out of `sidecar/routes/chat.py`; use `sidecar/services/chat_document_read.py`.
- Keep image data-url creation and vision edit prompt generation out of `sidecar/routes/chat.py`; use `sidecar/services/chat_visual_prompts.py`.
- Keep tool-result selection/dedup helpers out of `sidecar/routes/chat.py`; use `sidecar/services/chat_tool_results.py` for first/best result selection, ComfyUI manual-start checks, and trace output path extraction.
- Keep direct image/3D generation and previous-asset media modification flows out of `sidecar/routes/chat.py`; use `sidecar/services/chat_direct_media.py` for these small ComfyUI dispatch paths.
- Keep document-to-image/3D asset intent detection, prompt building, and generation dispatch out of `sidecar/routes/chat.py`; use `sidecar/services/chat_document_assets.py`.
- Keep folder-to-docx summary orchestration out of `sidecar/routes/chat.py`; use `sidecar/services/chat_folder_summary.py`.
- Keep LLM router decision prompting/parsing out of `sidecar/routes/chat.py`; use `sidecar/services/chat_llm_router.py`.
- Keep router action execution out of `sidecar/routes/chat.py`; use `sidecar/services/chat_router_actions.py`.
- Keep DSML/textual tool parsing and execution out of `sidecar/routes/chat.py`; use `sidecar/services/textual_tool_parser.py` for parsing only, and `sidecar/services/chat_textual_tools.py` for textual tool dispatch and answer synthesis.
- Keep OpenAI tool-call loop execution out of `sidecar/routes/chat.py`; use `sidecar/services/chat_tool_loop.py`. The loop includes an explicit result-verification prompt after each tool batch: the model should inspect tool results against the user request, call more tools when results are incomplete or wrong, and only answer when the task is complete or waiting for confirmation/user input.
- SQLite migrations in `sidecar/db/sqlite.py` are transaction-protected; keep future schema changes inside that rollback-safe flow.
- Run `npm run check` after frontend changes and `cargo check --manifest-path src-tauri/Cargo.toml` after Tauri command changes.
