# Ultra Studio Single-Loop Agent Runtime Design

## Requirements

### Functional

- Stream ordinary conversational text from the first provider delta.
- Expose existing filesystem, document, web, MCP, image, video, and 3D capabilities as typed tools.
- Preserve confirmation and permission behavior for destructive actions.
- Preserve queued generation and artifact presentation.
- Support bounded tool iteration and deterministic terminal states.
- Retain provider compatibility without making textual tool parsing the default path.

### Non-functional

- Record request-to-provider, provider TTFT, application TTFT, tool latency, loop count, and total duration.
- Do not log message content, API keys, or tool secrets in performance records.
- Ordinary chat must perform one model request.
- The route adapter must not own orchestration behavior.
- Every migration slice must be independently testable and reversible until final cutover.

## Components

- `agent_runtime/events.py`: typed lifecycle event construction and phase timer.
- `agent_runtime/models.py`: run request, tool definition, tool call, result, and terminal result models.
- `agent_runtime/providers.py`: native OpenAI-compatible streaming adapter plus future textual compatibility adapter.
- `agent_runtime/tools.py`: registry, capability profiles, argument validation, and execution boundary.
- `agent_runtime/policy.py`: allow/ask/deny decisions independent of the model.
- `agent_runtime/loop.py`: bounded model → tool → model state machine.
- `agent_runtime/legacy_bridge.py`: temporary adapters to existing tool services and result presentation.
- `routes/agent_runs.py`: new SSE transport that serializes runtime events.

## Event Contract

Every event contains `runId`, `conversationId`, `type`, `sequence`, `timestamp`, and `data`.

Initial event types are:

- `run.started`
- `context.finished`
- `model.started`
- `text.delta`
- `model.finished`
- `tool.started`
- `tool.finished`
- `run.finished`
- `run.failed`

`model.started` records the monotonic request offset. The first `text.delta` or structured tool-call delta records provider TTFT. The first user-visible `text.delta` records application TTFT. Metrics are emitted as structured metadata at `run.finished` and logged without prompt contents.

## Agent Loop

The loop starts with fitted conversation context and a filtered tool registry. It streams one provider turn. Text deltas are forwarded immediately for native-tool providers. Complete structured calls are validated, checked against policy, executed, appended as tool messages, and followed by another provider turn.

The loop stops on final text, a required confirmation, a runtime error, or the configured maximum of six model turns. It never silently converts malformed tool text into executable actions.

## Tool Visibility

Tools are filtered before inference using deterministic facts: workspace, attachments, configured providers, ComfyUI availability, permission mode, and provider tool support. Filtering limits prompt size but does not attempt semantic intent classification.

## Migration

The new `/api/agent/runs/stream` route is introduced beside the legacy route. Automated replay cases compare selected tools, confirmation states, generated task IDs, and final artifact structure. Once parity gates pass, Tauri switches to the new route. The legacy route and LLM router are then removed rather than retained as permanent fallback architecture.

## Failure Modes

- Provider does not support native tools: select the explicit compatibility adapter or expose chat-only mode.
- Malformed tool arguments: emit a failed tool result to the loop; never execute partially parsed arguments.
- Permission requires confirmation: terminate with a structured confirmation event.
- Tool timeout: emit a bounded error result and allow the model one recovery turn.
- Stream disconnect: cancel the active provider stream; persisted visible messages remain consistent.
