# Ultra Studio Single-Loop Agent Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the per-message LLM router and global textual-tool buffering with a measurable, policy-controlled, single-model agent loop.

**Architecture:** A new `sidecar/agent_runtime` package owns events, provider streaming, tool policy, registry, and the bounded loop. Existing services remain domain implementations behind adapters; a new SSE route runs beside the legacy chat route until replay tests permit cutover.

**Tech Stack:** Python 3.10+, FastAPI, Pydantic, OpenAI-compatible async clients, SQLite, Tauri SSE bridge, React/Zustand, unittest.

---

### Task 1: Define run events and latency metrics

**Files:**
- Create: `sidecar/agent_runtime/__init__.py`
- Create: `sidecar/agent_runtime/events.py`
- Test: `sidecar/tests/test_agent_runtime_events.py`

- [ ] Write tests for ordered sequence numbers, monotonic phase offsets, first-visible-token TTFT, and redacted metric logs.
- [ ] Run `python -m unittest sidecar.tests.test_agent_runtime_events -v`; expect import failure.
- [ ] Implement `RunEventEmitter` and `RunMetrics` without message-content fields.
- [ ] Re-run the focused test; expect PASS.

### Task 2: Define runtime contracts

**Files:**
- Create: `sidecar/agent_runtime/models.py`
- Test: `sidecar/tests/test_agent_runtime_models.py`

- [ ] Write tests for tool schema validation, terminal result states, and immutable run identifiers.
- [ ] Implement typed dataclasses/Pydantic models for run requests, calls, results, and completion.
- [ ] Run focused tests; expect PASS.

### Task 3: Build the policy-filtered tool registry

**Files:**
- Create: `sidecar/agent_runtime/tools.py`
- Create: `sidecar/agent_runtime/policy.py`
- Test: `sidecar/tests/test_agent_runtime_tools.py`
- Test: `sidecar/tests/test_agent_runtime_policy.py`

- [ ] Test allow/ask/deny decisions, schema rejection, capability filtering, and unknown tools.
- [ ] Implement registry and policy interfaces with no imports from `routes/chat.py`.
- [ ] Run focused tests; expect PASS.

### Task 4: Implement the native provider adapter

**Files:**
- Create: `sidecar/agent_runtime/providers.py`
- Test: `sidecar/tests/test_agent_runtime_providers.py`

- [ ] Test immediate text delta forwarding, structured tool-call assembly, provider errors, and cancellation.
- [ ] Implement an OpenAI-compatible native-tool streaming adapter.
- [ ] Verify ordinary text is never held for DSML scanning.

### Task 5: Implement the bounded agent loop

**Files:**
- Create: `sidecar/agent_runtime/loop.py`
- Test: `sidecar/tests/test_agent_runtime_loop.py`

- [ ] Test one-call ordinary chat, model→tool→model flow, confirmation stop, malformed arguments, and six-turn bound.
- [ ] Implement the state machine against injected provider/registry/policy interfaces.
- [ ] Assert first text delta is emitted before persistence and post-processing.

### Task 6: Adapt existing read-only capabilities

**Files:**
- Create: `sidecar/agent_runtime/legacy_bridge.py`
- Modify: `sidecar/services/mcp_tools.py`
- Test: `sidecar/tests/test_agent_runtime_legacy_bridge.py`

- [ ] Register web search/fetch, directory listing, file search/read, and document read adapters.
- [ ] Preserve existing tool result shapes and add adapter tests.

### Task 7: Add the parallel SSE route and replay harness

**Files:**
- Create: `sidecar/routes/agent_runs.py`
- Modify: `sidecar/main.py`
- Create: `sidecar/tests/test_agent_run_routes.py`
- Create: `sidecar/tests/test_agent_runtime_replay.py`

- [ ] Stream the event contract over SSE.
- [ ] Add deterministic replay cases for chat, read, search, confirmation, image, video, and 3D requests.
- [ ] Keep the legacy endpoint unchanged during this slice.

### Task 8: Migrate mutating and generation tools

**Files:**
- Modify: `sidecar/agent_runtime/legacy_bridge.py`
- Modify: `sidecar/agent_runtime/policy.py`
- Test: `sidecar/tests/test_agent_runtime_mutations.py`
- Test: `sidecar/tests/test_agent_runtime_generation.py`

- [ ] Adapt writes, edits, commands, image/video/3D generation, and task queue results.
- [ ] Require policy confirmation for destructive actions.
- [ ] Verify generation tools return queued task IDs without blocking the loop.

### Task 9: Cut over Tauri and remove the legacy orchestrator

**Files:**
- Modify: `src-tauri/src/commands/sidecar.rs`
- Modify: `src/stores/appStore.ts`
- Modify: `sidecar/routes/chat.py`
- Delete: `sidecar/services/chat_llm_router.py`
- Modify: `agent.md`

- [ ] Switch streaming transport after replay parity passes.
- [ ] Remove the per-message LLM router and global DSML buffer from the default path.
- [ ] Reduce `chat.py` to request validation, legacy compatibility during one release, and transport wiring.
- [ ] Run `npm run check`, `cargo test --manifest-path src-tauri/Cargo.toml`, `cargo check --manifest-path src-tauri/Cargo.toml`, and `npm run build`; expect PASS.
